"""Modbus 引擎：期望帧长推导、按功能码轮询、帧描述。"""
from serial_net_tool.core.channel import Channel, ChannelStatus
from serial_net_tool.plugins.modbus_tool.engine import ModbusEngine
from serial_net_tool.plugins.modbus_tool.panel import _describe_frame
from serial_net_tool.plugins.modbus_tool.register_map import RegisterMap


class SinkChannel(Channel):
    def __init__(self, sid="s"):
        super().__init__(sid)
        self.sent = []

    def open(self, cfg):
        self.status = ChannelStatus.CONNECTED

    def close(self):
        pass

    def send(self, data):
        self.sent.append(data)


def test_expected_response_len_read():
    assert ModbusEngine._expected_response_len((0x03, 0, 1), b"\x01\x03\x02\x00") == 7
    assert ModbusEngine._expected_response_len((0x01, 0, 8), b"\x01\x01\x01\xFF") == 6


def test_expected_response_len_exception():
    assert ModbusEngine._expected_response_len((0x03, 0, 1), b"\x01\x83\x02") == 5


def test_expected_response_len_write():
    assert ModbusEngine._expected_response_len((0x06, 0, 1), b"\x01\x06\x00") == 8
    assert ModbusEngine._expected_response_len((0x10, 0, 2), b"\x01\x10\x00") == 8


def test_expected_response_len_unknown():
    # 0x41 无高位，且不属于已知功能码 → 无法推导
    assert ModbusEngine._expected_response_len((0x41, 0, 1), b"\x01\x41\x00") is None


def test_poll_next_uses_block_function_code():
    engine = ModbusEngine(RegisterMap())
    sink = SinkChannel()
    engine._channel = sink
    engine._poll_blocks = [(0x01, 5, 2)]
    engine._poll_index = 0
    engine._poll_next()
    # 线圈读请求：返回长度应为 (slave, fc, addr_hi, addr_lo, qty_hi, qty_lo, crc_lo, crc_hi)
    assert sink.sent and sink.sent[0][1] == 0x01
    assert engine._pending_request[0] == 0x01


def test_describe_read_request():
    frame = {"slave_id": 1, "func_code": 0x03, "data": b"\x00\x00\x00\x0A",
             "is_exception": False, "exc_code": 0}
    unit, fc, addr, qty, values, exc = _describe_frame(frame)
    assert unit == 1 and fc == "0x03" and addr == 0 and qty == 10


def test_describe_read_response():
    frame = {"slave_id": 1, "func_code": 0x03, "data": b"\x02\x00\x2A",
             "is_exception": False, "exc_code": 0}
    _unit, _fc, _addr, qty, values, _exc = _describe_frame(frame)
    assert qty == 1 and values == "42"


def test_describe_write_single_reg():
    frame = {"slave_id": 1, "func_code": 0x06, "data": b"\x00\x01\x01\x02",
             "is_exception": False, "exc_code": 0}
    _unit, _fc, addr, _qty, values, _exc = _describe_frame(frame)
    assert addr == 1 and values == "258"


def test_describe_write_multiple_regs():
    data = b"\x00\x01\x00\x02\x04\x00\x0A\x01\x02"
    frame = {"slave_id": 1, "func_code": 0x10, "data": data,
             "is_exception": False, "exc_code": 0}
    _unit, _fc, addr, qty, values, _exc = _describe_frame(frame)
    assert addr == 1 and qty == 2 and values == "10, 258"


def test_describe_exception():
    frame = {"slave_id": 1, "func_code": 0x03, "data": b"",
             "is_exception": True, "exc_code": 2}
    row = _describe_frame(frame)
    assert "Exception" in row[5]
