"""进制与字节工具测试。"""
from serial_net_tool.tools.conv import (
    hex_to_str,
    int_to_base,
    str_to_hex,
    swap_endian,
    to_bin,
    to_dec,
    to_hex,
    to_oct,
)


def test_base_converters():
    assert to_bin(5) == "00000101"
    assert to_oct(8) == "10"
    assert to_dec(255) == "255"
    assert to_hex(255) == "FF"


def test_int_to_base():
    assert int_to_base(255, 16) == "FF"
    assert int_to_base(255, 2) == "11111111"
    assert int_to_base(255, 8) == "377"
    assert int_to_base(255, 10) == "255"


def test_swap_endian():
    assert swap_endian(b"\x01\x02\x03\x04") == b"\x02\x01\x04\x03"


def test_swap_endian_odd_length_keeps_size():
    # 奇数长度时实现会在前部补 0 后按 2 字节分组交换（保持长度 +1）
    out = swap_endian(b"\x01\x02\x03")
    assert out == b"\x01\x00\x03\x02"


def test_str_hex_roundtrip():
    h = str_to_hex("Hello")
    assert h == "48 65 6C 6C 6F"
    assert hex_to_str(h) == "Hello"


def test_hex_to_str_ignores_spaces():
    assert hex_to_str("48 65 6c 6c 6f") == "Hello"
