"""校验和计算（求和/异或/LRC）。"""


def sum8(data: bytes) -> int:
    return sum(data) & 0xFF


def sum16(data: bytes) -> int:
    return sum(data) & 0xFFFF


def xor8(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return r


def lrc(data: bytes) -> int:
    """Modbus LRC：0x100 - (sum mod 0x100)，取低 8 位。"""
    return (0x100 - (sum(data) % 0x100)) & 0xFF


def all_checksums(data: bytes) -> dict:
    return {
        "SUM8": f"{sum8(data):02X}",
        "SUM16": f"{sum16(data):04X}",
        "XOR": f"{xor8(data):02X}",
        "LRC": f"{lrc(data):02X}",
    }
