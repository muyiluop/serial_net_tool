"""校验和（SUM8/SUM16/XOR/LRC）测试。"""
from serial_net_tool.tools.check import all_checksums, lrc, sum8, sum16, xor8


def test_sum8_sum16():
    assert sum8(b"\x01\x02\x03") == 0x06
    assert sum16(b"\x01\x02\x03") == 0x0006
    assert sum8(b"\xff\xff") == 0xFE  # 截断
    assert sum16(b"\xff\xff") == 0x01FE


def test_xor():
    assert xor8(b"\x01\x02\x03") == 0x00
    assert xor8(b"AB") == 65 ^ 66


def test_lrc():
    # Modbus LRC = 0x100 - sum
    assert lrc(b"\x01\x02\x03") == 0xFA
    assert lrc(b"AB") == 0x7D
    # 两字节补码等价性
    assert lrc(b"AB") == ((~(65 + 66) + 1) & 0xFF)


def test_all_checksums_format():
    res = all_checksums(b"\x01\x02\x03")
    assert res == {"SUM8": "06", "SUM16": "0006", "XOR": "00", "LRC": "FA"}


def test_all_checksums_empty():
    assert all_checksums(b"") == {"SUM8": "00", "SUM16": "0000", "XOR": "00", "LRC": "00"}
