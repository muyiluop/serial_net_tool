"""粘包重组器测试（none / timeout / delimiter / length_prefix）。"""
from serial_net_tool.core.packet_reassembler import PacketReassembler


def test_none_mode_passthrough():
    r = PacketReassembler(mode="none")
    assert r.on_data(b"abc") == [b"abc"]
    assert r.on_data(b"") == []


def test_delimiter_mode_drop_delimiter():
    r = PacketReassembler(mode="delimiter", delimiter=b"\r\n", include_delimiter=False)
    assert r.on_data(b"a\r\nb\r\nc") == [b"a", b"b"]
    assert r.flush() == [b"c"]


def test_delimiter_mode_keep_delimiter():
    r = PacketReassembler(mode="delimiter", delimiter=b"\r\n", include_delimiter=True)
    assert r.on_data(b"a\r\nb\r\n") == [b"a\r\n", b"b\r\n"]


def test_delimiter_split_across_chunks():
    r = PacketReassembler(mode="delimiter", delimiter=b"\n")
    assert r.on_data(b"ab") == []
    assert r.on_data(b"c\n") == [b"abc"]


def test_length_prefix_big_endian():
    r = PacketReassembler(mode="length_prefix", len_bytes=2, len_endian="big")
    # 长度头 00 03 + payload abc
    assert r.on_data(b"\x00\x03abc") == [b"\x00\x03abc"]


def test_length_prefix_partial_then_complete():
    r = PacketReassembler(mode="length_prefix", len_bytes=2, len_endian="big")
    assert r.on_data(b"\x00\x03ab") == []
    assert r.on_data(b"c") == [b"\x00\x03abc"]


def test_length_prefix_includes_header():
    r = PacketReassembler(
        mode="length_prefix", len_bytes=2, len_endian="big", len_includes_header=True
    )
    # 总长 5 = 头(2) + 载荷(3)
    assert r.on_data(b"\x00\x05abc") == [b"\x00\x05abc"]


def test_length_prefix_little_endian():
    r = PacketReassembler(mode="length_prefix", len_bytes=2, len_endian="little")
    assert r.on_data(b"\x03\x00abc") == [b"\x03\x00abc"]


def test_timeout_mode_flushes_on_next_burst():
    r = PacketReassembler(mode="timeout", idle_timeout_ms=0)
    assert r.on_data(b"ab") == []          # 先入缓冲
    assert r.on_data(b"cd") == [b"ab"]     # 新数据到达 → 上一帧超时发出
    assert r.check_idle() == [b"cd"]       # 空闲检查发出剩余


def test_timeout_mode_no_idle_before_first_data():
    r = PacketReassembler(mode="timeout", idle_timeout_ms=999999)
    assert r.check_idle() == []
    assert r.flush() == []


def test_reset_clears_buffer():
    r = PacketReassembler(mode="delimiter", delimiter=b"\n")
    r.on_data(b"abc")
    r.reset()
    assert r.flush() == []
