"""编码与字节工具（纯逻辑，无 GUI 依赖）。"""
from typing import Literal


def text_to_bytes(text: str, mode: Literal["ascii", "hex"], encoding: str = "utf-8") -> bytes:
    """发送编辑框内容 -> 字节。
    hex 模式：忽略空格/换行，每两字符一字节。
    """
    if mode == "hex":
        clean = "".join(text.split())
        # 奇数长度补前导 0
        if len(clean) % 2 != 0:
            clean = "0" + clean
        return bytes.fromhex(clean)
    return text.encode(encoding, errors="replace")


def bytes_to_text(data: bytes, mode: Literal["ascii", "hex"], encoding: str = "utf-8") -> str:
    """字节 -> 展示文本。"""
    if mode == "hex":
        return data.hex(" ").upper()
    return data.decode(encoding, errors="replace")


def count_bytes(text: str, mode: Literal["ascii", "hex"], encoding: str = "utf-8") -> int:
    try:
        return len(text_to_bytes(text, mode, encoding))
    except Exception:
        return 0


def format_timestamp(ts, fmt: str = "%H:%M:%S.%f") -> str:
    return ts.strftime(fmt)[:-3]
