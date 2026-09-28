"""Modbus RTU/TCP 帧编解码测试。"""
import struct

from serial_net_tool.plugins.modbus_tool.frame import (
    build_rtu_exception,
    build_rtu_request,
    build_rtu_response,
    build_tcp_exception,
    build_tcp_request,
    format_exception,
    parse_rtu_frame,
    parse_tcp_frame,
    tcp_frame_length,
)


def test_rtu_roundtrip_read_request():
    frame = build_rtu_request(1, 0x03, struct.pack(">HH", 0x0000, 1))
    parsed = parse_rtu_frame(frame)
    assert parsed["slave_id"] == 1
    assert parsed["func_code"] == 0x03
    assert parsed["is_exception"] is False


def test_rtu_known_frame():
    # 经典样例：01 03 00 00 00 01 84 0A
    assert build_rtu_request(1, 0x03, b"\x00\x00\x00\x01").hex(" ").upper() == "01 03 00 00 00 01 84 0A"


def test_rtu_exception():
    frame = build_rtu_exception(1, 0x03, 0x02)
    parsed = parse_rtu_frame(frame)
    assert parsed["is_exception"] is True
    assert parsed["exc_code"] == 0x02
    assert parsed["func_code"] == 0x03


def test_rtu_bad_crc_returns_none():
    frame = bytearray(build_rtu_request(1, 0x03, b"\x00\x00\x00\x01"))
    frame[-1] ^= 0xFF
    assert parse_rtu_frame(bytes(frame)) is None


def test_rtu_incomplete_returns_none():
    assert parse_rtu_frame(b"\x01\x03\x00") is None


def test_rtu_response_parsed_by_byte_count():
    # Slave=1 FC=3 ByteCount=2 Data=0x00 0x2A CRC
    payload = bytes([1, 0x03, 2, 0x00, 0x2A])
    frame = build_rtu_response(1, 0x03, b"\x02\x00\x2A")
    parsed = parse_rtu_frame(frame)
    assert parsed is not None and parsed["data"] == b"\x02\x00\x2A"


def test_tcp_roundtrip():
    frame = build_tcp_request(1, 0x03, b"\x00\x00\x00\x01", txn_id=7)
    assert tcp_frame_length(frame) == len(frame)
    parsed = parse_tcp_frame(frame)
    assert parsed["txn_id"] == 7
    assert parsed["unit_id"] == 1
    assert parsed["func_code"] == 0x03


def test_tcp_exception():
    frame = build_tcp_exception(1, 0x03, 0x01, txn_id=2)
    parsed = parse_tcp_frame(frame)
    assert parsed["is_exception"] is True
    assert parsed["exc_code"] == 0x01


def test_tcp_incomplete():
    assert tcp_frame_length(b"\x00\x01") == 0
    assert parse_tcp_frame(b"\x00\x01") is None


def test_format_exception_known_and_unknown():
    assert "Illegal" in format_exception(1)
    assert "Unknown" in format_exception(99)
