"""Modbus RTU / TCP 帧编解码。

帧格式：
  RTU:  [Slave ID(1)] [FuncCode(1)] [Data(N)] [CRC(2)]
  TCP:  [TxnID(2)] [ProtoID(2)=0] [Length(2)] [UnitID(1)] [FuncCode(1)] [Data(N)]

支持功能码：
  0x01 Read Coils          0x05 Write Single Coil
  0x02 Read Discrete Inputs 0x06 Write Single Register
  0x03 Read Holding Regs    0x0F Write Multiple Coils
  0x04 Read Input Regs      0x10 Write Multiple Registers
"""
import struct
from typing import Optional

# 复用项目内置 CRC-16/MODBUS
from ...tools.crc import crc as _crc16


def _modbus_crc(data: bytes) -> bytes:
    """计算 Modbus CRC-16，返回 2 字节小端序。"""
    val = _crc16("CRC-16/MODBUS", data)
    return struct.pack("<H", val)


def _verify_crc(frame: bytes) -> bool:
    """校验 RTU 帧末尾 2 字节 CRC。"""
    if len(frame) < 4:
        return False
    payload = frame[:-2]
    recv_crc = frame[-2:]
    return _modbus_crc(payload) == recv_crc


# ==================== RTU 帧编解码 ====================

def build_rtu_request(slave_id: int, func_code: int, data: bytes) -> bytes:
    """构建 RTU 请求帧（不含 CRC → 追加 CRC）。"""
    payload = bytes([slave_id & 0xFF, func_code & 0xFF]) + data
    return payload + _modbus_crc(payload)


def build_rtu_response(slave_id: int, func_code: int, data: bytes) -> bytes:
    """构建 RTU 响应帧。"""
    return build_rtu_request(slave_id, func_code, data)


def build_rtu_exception(slave_id: int, func_code: int, exc_code: int) -> bytes:
    """构建 RTU 异常响应帧。"""
    data = bytes([func_code | 0x80, exc_code & 0xFF])
    payload = bytes([slave_id & 0xFF]) + data
    return payload + _modbus_crc(payload)


def parse_rtu_frame(data: bytes) -> Optional[dict]:
    """尝试从字节流解析一个完整 RTU 帧。
    返回 dict: {slave_id, func_code, data, is_exception, exc_code} 或 None（不完整/校验失败）。
    """
    if len(data) < 4:
        return None
    slave_id = data[0]
    func_code = data[1]
    # 异常响应
    if func_code & 0x80:
        if len(data) < 5:
            return None
        if not _verify_crc(data[:5]):
            return None
        return {
            "slave_id": slave_id,
            "func_code": func_code & 0x7F,
            "data": b"",
            "is_exception": True,
            "exc_code": data[2],
        }
    # 正常响应/请求：根据功能码推断长度
    expected = _rtu_frame_length(func_code, data)
    if expected is None or len(data) < expected:
        return None
    frame = data[:expected]
    if not _verify_crc(frame):
        return None
    return {
        "slave_id": slave_id,
        "func_code": func_code,
        "data": data[2:expected - 2],
        "is_exception": False,
        "exc_code": 0,
    }


def _rtu_frame_length(func_code: int, data: bytes) -> Optional[int]:
    """根据功能码和数据前几个字节推断 RTU 帧总长度（含 CRC）。
    兼容请求和响应两种格式：
    - 读请求(0x01-0x04)：固定 8 字节
    - 读响应(0x01-0x04)：Slave(1)+FC(1)+ByteCount(1)+Data(N)+CRC(2)
    - 写单值请求/响应(0x05/0x06)：固定 8 字节
    - 写多请求(0x0F/0x10)：Slave(1)+FC(1)+Addr(2)+Qty(2)+ByteCount(1)+Data(N)+CRC(2)
    - 写多响应(0x0F/0x10)：固定 8 字节
    """
    fc = func_code & 0x7F
    # 异常响应：Slave(1)+FC|0x80(1)+ExcCode(1)+CRC(2) = 5
    if func_code & 0x80:
        return 5
    # 读功能码：可能是请求(8字节)或响应(变长)
    if fc in (0x01, 0x02, 0x03, 0x04):
        # 如果 data[2] 看起来像 byte count 且对应长度的帧在缓冲区中，按响应处理
        if len(data) >= 3:
            byte_count = data[2]
            expected_response = 3 + byte_count + 2  # Slave+FC+ByteCount+Data+CRC
            # 优先检查响应格式：如果 byte_count 合理(2-250)且数据足够
            if 2 <= byte_count <= 250 and len(data) >= expected_response:
                return expected_response
        # 默认按请求格式（固定 8 字节）
        return 8
    # 写单值：固定 8 字节
    if fc in (0x05, 0x06):
        return 8
    # 写多请求/响应：请求是变长，响应是 8 字节
    if fc in (0x0F, 0x10):
        # 先检查是否为 8 字节（写多响应）
        if len(data) >= 7:
            byte_count = data[6]
            if byte_count > 0:
                # 写多请求格式
                return 7 + byte_count + 2
        return 8
    return None


# ==================== TCP (MBAP) 帧编解码 ====================

def build_tcp_request(unit_id: int, func_code: int, data: bytes, txn_id: int = 1) -> bytes:
    """构建 TCP (MBAP) 请求帧。
    MBAP: [TxnID(2)][ProtoID(2)][Length(2)][UnitID(1)][FuncCode(1)][Data(N)]
    Length = UnitID(1) + FuncCode(1) + Data(N) = 2 + N
    """
    length = 2 + len(data)
    mbap = struct.pack(">HHHB", txn_id & 0xFFFF, 0, length, unit_id & 0xFF)
    return mbap + bytes([func_code & 0xFF]) + data


def build_tcp_response(unit_id: int, func_code: int, data: bytes, txn_id: int = 1) -> bytes:
    """构建 TCP (MBAP) 响应帧。"""
    return build_tcp_request(unit_id, func_code, data, txn_id)


def build_tcp_exception(unit_id: int, func_code: int, exc_code: int, txn_id: int = 1) -> bytes:
    """构建 TCP 异常响应帧。"""
    data = bytes([func_code | 0x80, exc_code & 0xFF])
    # Length = UnitID(1) + ExceptionFC(1) + ExcCode(1) = 3
    mbap = struct.pack(">HHHB", txn_id & 0xFFFF, 0, 3, unit_id & 0xFF)
    return mbap + data


def parse_tcp_frame(data: bytes) -> Optional[dict]:
    """尝试从字节流解析一个完整 TCP (MBAP) 帧。
    返回 dict: {txn_id, unit_id, func_code, data, is_exception, exc_code} 或 None。
    """
    # MBAP header = 7 字节
    if len(data) < 7:
        return None
    txn_id, proto_id, length, unit_id = struct.unpack(">HHHB", data[:7])
    if proto_id != 0:
        return None
    # length 至少包含 UnitID(1)+FunctionCode(1)
    if length < 2:
        return None
    total = 6 + length  # MBAP header 6 bytes + length field covers UnitID+PDU
    if len(data) < total:
        return None
    frame = data[:total]
    func_code = frame[7]
    pdu_data = frame[8:]
    if func_code & 0x80:
        return {
            "txn_id": txn_id,
            "unit_id": unit_id,
            "func_code": func_code & 0x7F,
            "data": b"",
            "is_exception": True,
            "exc_code": pdu_data[0] if pdu_data else 0,
        }
    return {
        "txn_id": txn_id,
        "unit_id": unit_id,
        "func_code": func_code,
        "data": pdu_data,
        "is_exception": False,
        "exc_code": 0,
    }


def tcp_frame_length(data: bytes) -> int:
    """返回 TCP 帧预期总长度（含 MBAP header），0 表示数据不足或非法。"""
    if len(data) < 7:
        return 0
    _, proto_id, length, _ = struct.unpack(">HHHB", data[:7])
    if proto_id != 0 or length < 2:
        return 0
    return 6 + length


# ==================== 请求/响应 PDU 构建辅助 ====================

def make_read_pdu(func_code: int, start_addr: int, quantity: int) -> bytes:
    """构建读请求 PDU（不含 Slave/Unit ID 和 CRC/MBAP）。"""
    return struct.pack(">HH", start_addr, quantity)


def make_write_single_coil_pdu(addr: int, on: bool) -> bytes:
    """构建写单个线圈 PDU。"""
    value = 0xFF00 if on else 0x0000
    return struct.pack(">HH", addr, value)


def make_write_single_reg_pdu(addr: int, value: int) -> bytes:
    """构建写单个保持寄存器 PDU。"""
    return struct.pack(">HH", addr, value & 0xFFFF)


def make_write_multiple_regs_pdu(addr: int, values: list) -> bytes:
    """构建写多个保持寄存器 PDU。"""
    byte_count = len(values) * 2
    data = struct.pack(">HHB", addr, len(values), byte_count)
    for v in values:
        data += struct.pack(">H", v & 0xFFFF)
    return data


def make_write_multiple_coils_pdu(addr: int, values: list) -> bytes:
    """构建写多个线圈 PDU。values 为 bool 列表。"""
    qty = len(values)
    byte_count = (qty + 7) // 8
    packed = bytearray(byte_count)
    for i, v in enumerate(values):
        if v:
            packed[i // 8] |= (1 << (i % 8))
    return struct.pack(">HHB", addr, qty, byte_count) + bytes(packed)


def build_pdu_for_fc(
    func_code: int,
    address: int,
    quantity: int = 1,
    value: int = 0,
    coil_on: bool = False,
    multi_values: Optional[list] = None,
) -> bytes:
    """按功能码构建请求 PDU（纯函数，便于单元测试与报文构造器复用）。

    0x01-0x04 读请求；0x05 写单线圈；0x06 写单寄存器；
    0x0F 写多线圈（值转 bool）；0x10 写多寄存器（值按 16 位截断）。
    参数不合法时抛 ValueError。
    """
    if func_code in (0x01, 0x02, 0x03, 0x04):
        return make_read_pdu(func_code, address, quantity)
    if func_code == 0x05:
        return make_write_single_coil_pdu(address, coil_on)
    if func_code == 0x06:
        return make_write_single_reg_pdu(address, value)
    if func_code == 0x0F:
        vals = [bool(v) for v in (multi_values or [])]
        if not vals:
            raise ValueError("FC 0x0F requires multi_values")
        return make_write_multiple_coils_pdu(address, vals)
    if func_code == 0x10:
        vals = [int(v) & 0xFFFF for v in (multi_values or [])]
        if not vals:
            raise ValueError("FC 0x10 requires multi_values")
        return make_write_multiple_regs_pdu(address, vals)
    raise ValueError(f"unsupported function code: 0x{func_code:02X}")


def parse_read_response(data: bytes, func_code: int) -> list:
    """解析读响应 PDU，返回值列表。
    对 0x03/0x04：返回 16 位寄存器值列表
    对 0x01/0x02：返回 bool 列表
    """
    if not data:
        return []
    byte_count = data[0]
    payload = data[1:1 + byte_count]
    if func_code in (0x03, 0x04):
        # 每 2 字节一个寄存器
        regs = []
        for i in range(0, len(payload), 2):
            if i + 2 <= len(payload):
                regs.append(struct.unpack(">H", payload[i:i + 2])[0])
        return regs
    elif func_code in (0x01, 0x02):
        # 每 bit 一个线圈/离散输入
        bits = []
        for byte in payload:
            for bit in range(8):
                bits.append(bool(byte & (1 << bit)))
        return bits
    return []


# ==================== 异常码 ====================

EXCEPTION_CODES = {
    1: ("Illegal Function", "非法功能码"),
    2: ("Illegal Data Address", "非法数据地址"),
    3: ("Illegal Data Value", "非法数据值"),
    4: ("Slave Device Failure", "从站设备故障"),
    5: ("Acknowledge", "已确认"),
    6: ("Slave Device Busy", "从站设备忙"),
    8: ("Memory Parity Error", "内存奇偶校验错误"),
    10: ("Gateway Path Unavailable", "网关路径不可用"),
    11: ("Gateway No Response", "网关无响应"),
}


def format_exception(code: int) -> str:
    """格式化异常码为人话描述。"""
    entry = EXCEPTION_CODES.get(code)
    if entry:
        en, zh = entry
        return f"Exception 0x{code:02X} ({en} / {zh})"
    return f"Exception 0x{code:02X} (Unknown)"
