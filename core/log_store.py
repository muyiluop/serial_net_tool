"""结构化通信日志：有界存储、按条件检索、多种格式导出。

设计：
- 纯逻辑 + Qt 信号，无控件依赖，便于单测。
- 记录（LogRecord）保存格式无关的原始数据，展示/导出时才按需渲染。
- 有界 deque 控制内存：超出后丢弃最旧记录（PRD「超大日志限长滚动」）。
"""
import csv
import io
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal


@dataclass
class LogRecord:
    """一条通信日志记录。"""

    direction: str  # "tx" | "rx"
    text: str  # 展示文本（按当前 Hex/ASCII 模式渲染）
    raw: bytes = b""  # 原始字节，用于 Hex 导出与字节统计
    ts: datetime = field(default_factory=datetime.now)
    peer: str = ""  # TCP 对端 / 来源
    topic: str = ""  # MQTT 主题
    tag: str = ""  # 可选事件标记（如 "文件"）


class LogStore(QObject):
    """有界日志存储。"""

    appended = Signal(object)  # LogRecord
    cleared = Signal()

    def __init__(self, max_lines: int = 5000, parent=None):
        super().__init__(parent)
        self._max = max(1, int(max_lines))
        self._records: deque = deque(maxlen=self._max)
        self._rx_bytes = 0
        self._tx_bytes = 0

    # ---------- 容量 ----------
    @property
    def max_lines(self) -> int:
        return self._max

    def set_max_lines(self, n: int):
        n = max(1, int(n))
        if n == self._max:
            return
        self._max = n
        self._records = deque(self._records, maxlen=n)

    # ---------- 写入 ----------
    def add(self, record: LogRecord) -> LogRecord:
        if record.direction == "rx":
            self._rx_bytes += len(record.raw)
        elif record.direction == "tx":
            self._tx_bytes += len(record.raw)
        self._records.append(record)
        self.appended.emit(record)
        return record

    def log(
        self,
        direction: str,
        text: str,
        raw: bytes = b"",
        peer: str = "",
        topic: str = "",
        tag: str = "",
        ts: Optional[datetime] = None,
    ) -> LogRecord:
        return self.add(
            LogRecord(
                direction=direction,
                text=text,
                raw=raw or b"",
                peer=peer,
                topic=topic,
                tag=tag,
                ts=ts or datetime.now(),
            )
        )

    def clear(self):
        self._records.clear()
        self._rx_bytes = 0
        self._tx_bytes = 0
        self.cleared.emit()

    # ---------- 统计 ----------
    @property
    def rx_bytes(self) -> int:
        return self._rx_bytes

    @property
    def tx_bytes(self) -> int:
        return self._tx_bytes

    def __len__(self) -> int:
        return len(self._records)

    # ---------- 检索 ----------
    def all(self) -> list:
        return list(self._records)

    def records(
        self,
        direction: str = None,
        query: str = "",
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list:
        q = (query or "").lower()
        out = []
        for r in self._records:
            if direction and direction != "both" and r.direction != direction:
                continue
            if since and r.ts < since:
                continue
            if until and r.ts > until:
                continue
            if q and q not in r.text.lower() and q not in r.peer.lower() and q not in r.topic.lower():
                continue
            out.append(r)
        return out

    # ---------- 导出 ----------
    @staticmethod
    def _format_ts(ts: datetime) -> str:
        return ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    @staticmethod
    def _dir_tag(direction: str) -> str:
        return "TX" if direction == "tx" else "RX"

    def to_txt(self, records: list = None, include_ts: bool = True, include_dir: bool = True) -> str:
        records = self.all() if records is None else records
        lines = []
        for r in records:
            parts = []
            if include_ts:
                parts.append(self._format_ts(r.ts))
            if include_dir:
                parts.append(f"[{self._dir_tag(r.direction)}]")
            if r.peer:
                parts.append(f"@{r.peer}")
            if r.topic:
                parts.append(f"#{r.topic}")
            parts.append(r.text)
            lines.append(" ".join(parts))
        return "\n".join(lines)

    def to_csv(self, records: list = None, include_ts: bool = True, include_dir: bool = True) -> str:
        records = self.all() if records is None else records
        buf = io.StringIO()
        writer = csv.writer(buf)
        header = []
        if include_ts:
            header.append("time")
        if include_dir:
            header.append("direction")
        header += ["peer", "topic", "text"]
        writer.writerow(header)
        for r in records:
            row = []
            if include_ts:
                row.append(self._format_ts(r.ts))
            if include_dir:
                row.append(r.direction)
            row += [r.peer, r.topic, r.text]
            writer.writerow(row)
        return buf.getvalue()

    def to_hex(self, records: list = None) -> str:
        """Hex dump：每 16 字节一行，含偏移与 ASCII 侧栏。"""
        records = self.all() if records is None else records
        lines = []
        for r in records:
            lines.append(
                f"[{self._format_ts(r.ts)}] {self._dir_tag(r.direction)} "
                f"{len(r.raw)} bytes"
            )
            data = r.raw
            for off in range(0, len(data), 16):
                chunk = data[off : off + 16]
                hexpart = " ".join(f"{b:02X}" for b in chunk)
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                lines.append(f"{off:08X}  {hexpart:<47}  {ascii_part}")
        return "\n".join(lines)
