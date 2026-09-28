"""日志存储与导出测试。"""
from datetime import datetime, timedelta

import pytest

from serial_net_tool.core.log_store import LogRecord, LogStore


def test_add_and_counters():
    s = LogStore(max_lines=10)
    s.log("rx", "hello", raw=b"hello")
    s.log("tx", "world", raw=b"world!")
    assert len(s) == 2
    assert s.rx_bytes == 5
    assert s.tx_bytes == 6


def test_bounded_eviction():
    s = LogStore(max_lines=3)
    for i in range(5):
        s.log("rx", f"line{i}", raw=bytes([i]))
    assert len(s) == 3
    assert [r.text for r in s.all()] == ["line2", "line3", "line4"]


def test_set_max_lines_trims():
    s = LogStore(max_lines=10)
    for i in range(8):
        s.log("rx", str(i))
    s.set_max_lines(4)
    assert len(s) == 4
    assert [r.text for r in s.all()] == ["4", "5", "6", "7"]


def test_clear_resets_counters_and_emits():
    s = LogStore()
    emitted = []
    s.cleared.connect(lambda: emitted.append(True))
    s.log("rx", "x", raw=b"x")
    s.clear()
    assert len(s) == 0 and s.rx_bytes == 0
    assert emitted == [True]


def test_records_filter_by_direction_and_query():
    s = LogStore()
    s.log("rx", "alpha", peer="1.2.3.4")
    s.log("tx", "beta")
    s.log("rx", "gamma", topic="sensor/1")
    assert [r.text for r in s.records(direction="rx")] == ["alpha", "gamma"]
    assert [r.text for r in s.records(direction="tx")] == ["beta"]
    assert [r.text for r in s.records(query="gam")] == ["gamma"]
    assert [r.text for r in s.records(query="1.2.3.4")] == ["alpha"]  # 命中 peer
    assert [r.text for r in s.records(query="sensor")] == ["gamma"]  # 命中 topic


def test_records_filter_by_time():
    s = LogStore()
    now = datetime(2026, 1, 1, 12, 0, 0)
    s.log("rx", "old", ts=now - timedelta(hours=2))
    s.log("rx", "mid", ts=now)
    s.log("rx", "new", ts=now + timedelta(hours=2))
    got = s.records(since=now - timedelta(minutes=1), until=now + timedelta(minutes=1))
    assert [r.text for r in got] == ["mid"]


def test_appended_signal():
    s = LogStore()
    seen = []
    s.appended.connect(lambda rec: seen.append(rec.text))
    s.log("rx", "a")
    s.log("tx", "b")
    assert seen == ["a", "b"]


def test_to_txt():
    s = LogStore()
    ts = datetime(2026, 1, 2, 3, 4, 5, 678000)
    s.log("rx", "hi", ts=ts, peer="1.1.1.1")
    out = s.to_txt()
    assert "2026-01-02 03:04:05.678" in out
    assert "[RX]" in out and "@1.1.1.1" in out and out.endswith("hi")
    # 关闭时间戳/方向
    out2 = s.to_txt(include_ts=False, include_dir=False)
    assert "2026" not in out2 and "[RX]" not in out2


def test_to_csv():
    s = LogStore()
    s.log("tx", "a,b", topic="t/1")
    out = s.to_csv()
    lines = out.strip().splitlines()
    assert lines[0] == "time,direction,peer,topic,text"
    assert '"a,b"' in lines[1]


def test_to_hex_dump():
    s = LogStore()
    s.log("tx", "16 bytes", raw=bytes(range(16)))
    out = s.to_hex()
    assert "00000000" in out
    assert "00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F" in out


def test_log_returns_record():
    s = LogStore()
    rec = s.log("rx", "x")
    assert isinstance(rec, LogRecord)
    assert rec.direction == "rx"
