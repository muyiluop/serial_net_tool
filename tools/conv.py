"""进制与字节工具。"""
from typing import Literal


def to_bin(value: int, bits: int = 8) -> str:
    return format(value & ((1 << bits) - 1), f"0{bits}b")


def to_oct(value: int) -> str:
    return oct(value)[2:]


def to_dec(value: int) -> str:
    return str(value)


def to_hex(value: int) -> str:
    return format(value, "02X")


def swap_endian(data: bytes) -> bytes:
    """16 位大端/小端互换（按 2 字节分组）。"""
    if len(data) % 2 != 0:
        data = b"\x00" + data  # 补齐
    out = bytearray()
    for i in range(0, len(data), 2):
        out.extend(data[i + 1 : i + 2] + data[i : i + 1])
    return bytes(out)


def str_to_hex(s: str, encoding: str = "utf-8") -> str:
    return s.encode(encoding).hex(" ").upper()


def hex_to_str(h: str, encoding: str = "utf-8") -> str:
    clean = "".join(h.split())
    if len(clean) % 2 != 0:
        clean = "0" + clean
    return bytes.fromhex(clean).decode(encoding, errors="replace")


def int_to_base(value: int, base: Literal[2, 8, 10, 16]) -> str:
    return {
        2: to_bin(value),
        8: to_oct(value),
        10: to_dec(value),
        16: to_hex(value),
    }[base]
