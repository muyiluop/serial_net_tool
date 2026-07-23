"""粘包重组器：支持三种模式。

模式：
- none: 直通模式，不做任何处理（默认）
- timeout: 超时分隔模式。收到数据后等待 idle_timeout_ms 毫秒无新数据，
  则将缓冲区作为一帧发出。
- delimiter: 分隔符模式。按指定字节序列分隔，每段作为一帧发出
  （分隔符本身包含在帧内还是丢弃由 include_delimiter 控制）。
- length_prefix: 长度前缀模式。前 N 字节为大端/小端长度头，
  后跟该长度的 payload。

用法：
    r = PacketReassembler(mode="timeout", idle_timeout_ms=50)
    r.on_data(raw_bytes)  # 返回拆分后的帧列表
    r.flush()             # 取出缓冲区残留
"""
import struct
import time


class PacketReassembler:
    """粘包重组器。"""

    def __init__(self, mode: str = "none", **kwargs):
        self.mode = mode
        self._buf = bytearray()
        # timeout 模式参数
        self._idle_timeout_ms = kwargs.get("idle_timeout_ms", 50)
        self._last_recv_ts: float = 0.0
        # delimiter 模式参数
        self._delimiter: bytes = kwargs.get("delimiter", b"\r\n")
        self._include_delimiter: bool = kwargs.get("include_delimiter", False)
        # length_prefix 模式参数
        self._len_bytes: int = kwargs.get("len_bytes", 2)  # 1/2/4
        self._len_endian: str = kwargs.get("len_endian", "big")  # big/little
        self._len_includes_header: bool = kwargs.get("len_includes_header", False)

    # ---------- 公共方法 ----------
    def on_data(self, data: bytes) -> list[bytes]:
        """喂入原始数据，返回拆分后的完整帧列表。"""
        if not data:
            return []
        if self.mode == "none":
            return [data]
        if self.mode == "timeout":
            return self._on_timeout(data)
        if self.mode == "delimiter":
            return self._on_delimiter(data)
        if self.mode == "length_prefix":
            return self._on_length_prefix(data)
        return [data]

    def check_idle(self) -> list[bytes]:
        """timeout 模式：检查是否因空闲超时而需要 flush 缓冲区。"""
        if self.mode != "timeout" or not self._buf:
            return []
        if self._is_idle_timeout():
            return self._flush_buf()
        return []

    def flush(self) -> list[bytes]:
        """取出缓冲区残留（通常在连接关闭时调用）。"""
        if not self._buf:
            return []
        return self._flush_buf()

    def reset(self):
        """重置内部状态。"""
        self._buf.clear()
        self._last_recv_ts = 0.0

    # ---------- timeout 模式 ----------
    def _on_timeout(self, data: bytes) -> list[bytes]:
        frames = []
        # 如果缓冲区非空且已经超时，先 flush 上一帧
        if self._buf and self._is_idle_timeout():
            frames.append(bytes(self._buf))
            self._buf.clear()
        # 追加新数据
        self._buf.extend(data)
        self._last_recv_ts = time.monotonic()
        return frames

    def _is_idle_timeout(self) -> bool:
        if self._last_recv_ts == 0.0:
            return False
        elapsed_ms = (time.monotonic() - self._last_recv_ts) * 1000
        return elapsed_ms >= self._idle_timeout_ms

    # ---------- delimiter 模式 ----------
    def _on_delimiter(self, data: bytes) -> list[bytes]:
        self._buf.extend(data)
        frames = []
        while True:
            idx = self._buf.find(self._delimiter)
            if idx < 0:
                break
            end = idx + len(self._delimiter) if self._include_delimiter else idx
            frame = bytes(self._buf[:end])
            if frame:
                frames.append(frame)
            del self._buf[: idx + len(self._delimiter)]
        return frames

    # ---------- length_prefix 模式 ----------
    def _on_length_prefix(self, data: bytes) -> list[bytes]:
        self._buf.extend(data)
        frames = []
        while True:
            if len(self._buf) < self._len_bytes:
                break
            # 解析长度头
            header = bytes(self._buf[: self._len_bytes])
            if self._len_endian == "little":
                pkt_len = int.from_bytes(header, "little")
            else:
                pkt_len = int.from_bytes(header, "big")
            payload_len = pkt_len - self._len_bytes if self._len_includes_header else pkt_len
            if payload_len < 0:
                # 长度头非法，丢弃缓冲区
                self._buf.clear()
                break
            total = self._len_bytes + payload_len
            if len(self._buf) < total:
                break  # 数据不完整，等待更多
            frame = bytes(self._buf[:total])
            frames.append(frame)
            del self._buf[:total]
        return frames

    # ---------- 内部 ----------
    def _flush_buf(self) -> list[bytes]:
        frame = bytes(self._buf)
        self._buf.clear()
        self._last_recv_ts = 0.0
        return [frame] if frame else []
