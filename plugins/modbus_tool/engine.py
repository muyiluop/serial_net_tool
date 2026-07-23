"""Modbus 引擎：主站 / 从站模式。

通过 Channel 的 received 信号和 send 方法与传输层交互，
不直接创建连接，复用已有串口/TCP 会话。

主站模式：
  - 定时轮询寄存器地址块
  - 发送读请求 → 解析响应 → 更新寄存器映射
  - 支持手动写操作

从站模式：
  - 监听传入的 Modbus 请求帧
  - 自动响应读/写请求
  - 寄存器映射作为数据源
"""
import struct
from typing import Optional, Callable
from PySide6.QtCore import QObject, Signal, QTimer, QByteArray

from .frame import (
    build_rtu_request, build_rtu_response, build_rtu_exception,
    parse_rtu_frame, _rtu_frame_length,
    build_tcp_request, build_tcp_response, build_tcp_exception,
    parse_tcp_frame, tcp_frame_length,
    make_read_pdu, make_write_single_coil_pdu, make_write_single_reg_pdu,
    make_write_multiple_regs_pdu, make_write_multiple_coils_pdu,
    parse_read_response, format_exception,
)
from .register_map import RegisterMap, reg_count_for_type


class ModbusEngine(QObject):
    """Modbus 协议引擎，主站或从站模式。"""

    # 信号：值更新（配置项索引列表）
    values_updated = Signal()
    # 信号：帧日志 (direction: 'tx'|'rx', hex_str: str, note: str)
    frame_log = Signal(str, str, str)
    # 信号：状态消息
    status_message = Signal(str)
    # 信号：错误
    error_occurred = Signal(str)

    def __init__(self, reg_map: RegisterMap, parent=None):
        super().__init__(parent)
        self.reg_map = reg_map
        self.mode = "master"        # "master" | "slave"
        self.frame_format = "rtu"   # "rtu" | "tcp"
        self.slave_id = 1
        self.poll_interval_ms = 1000
        self._channel = None
        self._running = False
        self._rx_buffer = bytearray()
        # 主站轮询
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_next)
        self._poll_blocks = []
        self._poll_index = 0
        self._pending_request = None  # (func_code, start_addr, count)
        # 从站响应的 TCP 事务 ID 跟踪
        self._last_txn_id = 1

    # ==================== 绑定/解绑通道 ====================

    def attach(self, channel):
        """绑定到已有 Channel（复用串口/TCP 连接）。"""
        self._channel = channel
        channel.received.connect(self._on_raw_data)

    def detach(self):
        """解绑通道。"""
        if self._channel:
            try:
                self._channel.received.disconnect(self._on_raw_data)
            except Exception:
                pass
            self._channel = None
        self._rx_buffer.clear()
        self.stop()

    # ==================== 启停控制 ====================

    def start(self):
        """启动引擎。"""
        if not self._channel:
            self.error_occurred.emit("no_channel")
            return
        self._running = True
        self._rx_buffer.clear()
        if self.mode == "master":
            self._poll_blocks = self.reg_map.get_poll_blocks()
            self._poll_index = 0
            if self._poll_blocks:
                self._poll_timer.start(self.poll_interval_ms)
                # 立即执行一轮
                QTimer.singleShot(100, self._poll_next)
            self.status_message.emit("master_started")
        else:
            self.status_message.emit("slave_started")

    def stop(self):
        """停止引擎。"""
        self._running = False
        self._poll_timer.stop()
        self._pending_request = None
        self.status_message.emit("stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ==================== 原始数据接收 ====================

    def _on_raw_data(self, data: bytes, meta: dict):
        """Channel received 信号回调。"""
        if not self._running:
            return
        self._rx_buffer.extend(data)
        self._try_process_frames()

    def _try_process_frames(self):
        """尝试从接收缓冲区中提取完整帧并处理。"""
        while self._rx_buffer:
            if self.frame_format == "tcp":
                consumed = self._process_tcp_stream()
            else:
                consumed = self._process_rtu_stream()
            if consumed == 0:
                break
            del self._rx_buffer[:consumed]

    def _process_rtu_stream(self) -> int:
        """从 RTU 字节流中提取一帧，返回消耗的字节数。"""
        if len(self._rx_buffer) < 4:
            return 0
        data = bytes(self._rx_buffer)
        # 尝试推断帧长度
        func_code = data[1]
        expected = _rtu_frame_length(func_code, data)
        if expected is None:
            # 未知功能码，尝试逐字节跳过
            return 1
        if len(data) < expected:
            return 0
        frame = parse_rtu_frame(data[:expected])
        if frame is None:
            # CRC 校验失败，跳过 1 字节继续尝试
            return 1
        self._handle_frame(frame)
        return expected

    def _process_tcp_stream(self) -> int:
        """从 TCP 字节流中提取一帧，返回消耗的字节数。"""
        expected = tcp_frame_length(bytes(self._rx_buffer))
        if expected == 0:
            return 0
        if len(self._rx_buffer) < expected:
            return 0
        frame = parse_tcp_frame(bytes(self._rx_buffer[:expected]))
        if frame is None:
            return expected  # 跳过无效帧
        self._handle_frame(frame)
        return expected

    # ==================== 帧处理 ====================

    def _handle_frame(self, frame: dict):
        """处理一个完整的 Modbus 帧。"""
        is_response = self._is_response_frame(frame)
        hex_str = " ".join(f"{b:02X}" for b in self._frame_to_bytes(frame))

        if is_response:
            # 主站模式：处理响应
            self.frame_log.emit("rx", hex_str, "")
            self._handle_response(frame)
        else:
            # 从站模式：处理请求
            self.frame_log.emit("rx", hex_str, "")
            self._handle_request(frame)

    def _is_response_frame(self, frame: dict) -> bool:
        """判断帧是请求还是响应。
        简单策略：主站模式下收到的都是响应，从站模式下收到的都是请求。
        """
        return self.mode == "master"

    def _frame_to_bytes(self, frame: dict) -> bytes:
        """将解析后的帧 dict 转回字节（仅用于日志显示）。"""
        # 由于我们已经在原始数据中有了帧字节，这里返回简化表示
        slave = frame.get("slave_id", frame.get("unit_id", 0))
        fc = frame["func_code"]
        data = frame.get("data", b"")
        if frame.get("is_exception"):
            return bytes([slave, fc | 0x80, frame["exc_code"]])
        return bytes([slave, fc]) + data

    # ==================== 主站：响应处理 ====================

    def _handle_response(self, frame: dict):
        """主站模式：处理从站返回的响应帧。"""
        if frame.get("is_exception"):
            desc = format_exception(frame["exc_code"])
            self.status_message.emit(desc)
            self._pending_request = None
            return

        if not self._pending_request:
            return

        req_fc, req_addr, req_count = self._pending_request
        self._pending_request = None

        fc = frame["func_code"]
        if fc != req_fc:
            return

        if fc in (0x03, 0x04):
            # 读寄存器响应
            values = parse_read_response(frame["data"], fc)
            self.reg_map.set_raw_values(req_addr, values)
            self.values_updated.emit()
        elif fc in (0x01, 0x02):
            # 读线圈/离散输入响应
            values = parse_read_response(frame["data"], fc)
            self.reg_map.set_raw_values(req_addr, [1 if v else 0 for v in values[:req_count]])
            self.values_updated.emit()

    def _poll_next(self):
        """主站模式：发送下一个轮询请求。"""
        if not self._channel or not self._poll_blocks:
            return
        # 如果上一个请求还没收到响应，跳过本轮
        if self._pending_request:
            return
        start_addr, count = self._poll_blocks[self._poll_index]
        self._poll_index = (self._poll_index + 1) % len(self._poll_blocks)
        self._send_read(0x03, start_addr, count)

    # ==================== 主站：发送请求 ====================

    def _send_read(self, func_code: int, start_addr: int, count: int):
        """发送读请求。"""
        pdu = make_read_pdu(func_code, start_addr, count)
        self._send_request(func_code, pdu, start_addr, count)

    def send_write_single_reg(self, addr: int, value: int):
        """主站：写单个保持寄存器。"""
        pdu = make_write_single_reg_pdu(addr, value)
        self._send_request(0x06, pdu, addr, 1)

    def send_write_multiple_regs(self, addr: int, values: list):
        """主站：写多个保持寄存器。"""
        pdu = make_write_multiple_regs_pdu(addr, values)
        self._send_request(0x10, pdu, addr, len(values))

    def send_write_single_coil(self, addr: int, on: bool):
        """主站：写单个线圈。"""
        pdu = make_write_single_coil_pdu(addr, on)
        self._send_request(0x05, pdu, addr, 1)

    def send_write_multiple_coils(self, addr: int, values: list):
        """主站：写多个线圈。"""
        pdu = make_write_multiple_coils_pdu(addr, values)
        self._send_request(0x0F, pdu, addr, len(values))

    def _send_request(self, func_code: int, pdu: bytes, start_addr: int = 0, count: int = 0):
        """构建并发送一个 Modbus 请求帧。"""
        if not self._channel:
            return
        if self.frame_format == "rtu":
            frame_bytes = build_rtu_request(self.slave_id, func_code, pdu)
        else:
            self._last_txn_id = (self._last_txn_id + 1) & 0xFFFF
            if self._last_txn_id == 0:
                self._last_txn_id = 1
            frame_bytes = build_tcp_request(self.slave_id, func_code, pdu, self._last_txn_id)
        # 记录待处理请求（主站模式）
        if self.mode == "master":
            self._pending_request = (func_code, start_addr, count)
        # 发送
        self._channel.send(frame_bytes)
        hex_str = " ".join(f"{b:02X}" for b in frame_bytes)
        self.frame_log.emit("tx", hex_str, f"FC=0x{func_code:02X}")

    # ==================== 从站：请求处理 ====================

    def _handle_request(self, frame: dict):
        """从站模式：处理主站发来的请求帧，自动响应。"""
        fc = frame["func_code"]
        slave_id = frame.get("slave_id", frame.get("unit_id", 0))
        data = frame.get("data", b"")
        txn_id = frame.get("txn_id", 1)

        # 检查从站 ID
        if slave_id != self.slave_id:
            return  # 不是发给本从站的

        try:
            if fc in (0x01, 0x02, 0x03, 0x04):
                # 读请求
                start_addr, quantity = struct.unpack(">HH", data[:4])
                response_data = self._build_read_response(fc, start_addr, quantity)
                self._send_response(fc, response_data, txn_id)
            elif fc == 0x05:
                # 写单个线圈
                addr, value = struct.unpack(">HH", data[:4])
                on = (value == 0xFF00)
                self.reg_map.set_raw_value(addr, 1 if on else 0)
                self.values_updated.emit()
                # 回显
                self._send_response(fc, data[:4], txn_id)
            elif fc == 0x06:
                # 写单个寄存器
                addr, value = struct.unpack(">HH", data[:4])
                self.reg_map.set_raw_value(addr, value)
                self.values_updated.emit()
                # 回显
                self._send_response(fc, data[:4], txn_id)
            elif fc == 0x0F:
                # 写多个线圈
                addr, qty = struct.unpack(">HH", data[:4])
                byte_count = data[4]
                coil_data = data[5:5 + byte_count]
                for i in range(qty):
                    byte_idx = i // 8
                    bit_idx = i % 8
                    val = bool(coil_data[byte_idx] & (1 << bit_idx)) if byte_idx < len(coil_data) else False
                    self.reg_map.set_raw_value(addr + i, 1 if val else 0)
                self.values_updated.emit()
                # 响应：回显地址和数量
                resp_data = struct.pack(">HH", addr, qty)
                self._send_response(fc, resp_data, txn_id)
            elif fc == 0x10:
                # 写多个寄存器
                addr, qty = struct.unpack(">HH", data[:4])
                byte_count = data[4]
                reg_data = data[5:5 + byte_count]
                values = []
                for i in range(0, len(reg_data), 2):
                    if i + 2 <= len(reg_data):
                        values.append(struct.unpack(">H", reg_data[i:i + 2])[0])
                self.reg_map.set_raw_values(addr, values)
                self.values_updated.emit()
                # 响应：回显地址和数量
                resp_data = struct.pack(">HH", addr, qty)
                self._send_response(fc, resp_data, txn_id)
            else:
                # 不支持的功能码
                self._send_exception(fc, 1, txn_id)  # Illegal Function
        except Exception as e:
            self.error_occurred.emit(str(e))
            self._send_exception(fc, 4, txn_id)  # Slave Device Failure

    def _build_read_response(self, fc: int, start_addr: int, quantity: int) -> bytes:
        """构建读响应 PDU 数据。"""
        if fc in (0x03, 0x04):
            # 读寄存器
            values = self.reg_map.get_raw_values(start_addr, quantity)
            byte_count = len(values) * 2
            data = bytes([byte_count])
            for v in values:
                data += struct.pack(">H", v & 0xFFFF)
            return data
        elif fc in (0x01, 0x02):
            # 读线圈/离散输入
            raw = self.reg_map.get_raw_values(start_addr, quantity)
            byte_count = (quantity + 7) // 8
            packed = bytearray(byte_count)
            for i in range(min(quantity, len(raw))):
                if raw[i]:
                    packed[i // 8] |= (1 << (i % 8))
            return bytes([byte_count]) + bytes(packed)
        return b""

    def _send_response(self, func_code: int, data: bytes, txn_id: int = 1):
        """从站：发送响应帧。"""
        if not self._channel:
            return
        if self.frame_format == "rtu":
            frame_bytes = build_rtu_response(self.slave_id, func_code, data)
        else:
            frame_bytes = build_tcp_response(self.slave_id, func_code, data, txn_id)
        self._channel.send(frame_bytes)
        hex_str = " ".join(f"{b:02X}" for b in frame_bytes)
        self.frame_log.emit("tx", hex_str, f"FC=0x{func_code:02X} Response")

    def _send_exception(self, func_code: int, exc_code: int, txn_id: int = 1):
        """从站：发送异常响应帧。"""
        if not self._channel:
            return
        if self.frame_format == "rtu":
            frame_bytes = build_rtu_exception(self.slave_id, func_code, exc_code)
        else:
            frame_bytes = build_tcp_exception(self.slave_id, func_code, exc_code, txn_id)
        self._channel.send(frame_bytes)
        hex_str = " ".join(f"{b:02X}" for b in frame_bytes)
        desc = format_exception(exc_code)
        self.frame_log.emit("tx", hex_str, desc)
