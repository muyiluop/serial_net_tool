"""编码/字节工具测试。"""
import pytest

from serial_net_tool.core.utils import (
    bytes_to_text,
    count_bytes,
    parse_int,
    text_to_bytes,
)


def test_text_to_bytes_hex():
    assert text_to_bytes("01 AB CD", "hex") == b"\x01\xab\xcd"
    assert text_to_bytes("01abcd", "hex") == b"\x01\xab\xcd"


def test_text_to_bytes_hex_odd_length_pads_front():
    assert text_to_bytes("ABC", "hex") == b"\x0a\xbc"


def test_text_to_bytes_ascii():
    assert text_to_bytes("hi", "ascii") == b"hi"


def test_bytes_to_text():
    assert bytes_to_text(b"\x01\xab", "hex") == "01 AB"
    assert bytes_to_text(b"hi", "ascii") == "hi"


def test_count_bytes():
    assert count_bytes("01 AB CD", "hex") == 3
    assert count_bytes("abc", "ascii") == 3
    assert count_bytes("zz", "hex") == 0  # 非法输入返回 0


def test_parse_int():
    assert parse_int("255") == 255
    assert parse_int("0x4000") == 0x4000
    assert parse_int("0b1010") == 10
    assert parse_int("0o17") == 15
    assert parse_int(" 42 ") == 42


def test_parse_int_invalid_raises():
    with pytest.raises(ValueError):
        parse_int("nope")
    with pytest.raises(ValueError):
        parse_int("")
