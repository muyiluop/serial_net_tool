"""CRC 计算（纯 Python 实现，支持常用算法与参数化通用算法）。"""


def _reflect(data: int, width: int) -> int:
    res = 0
    for i in range(width):
        if data & (1 << i):
            res |= 1 << (width - 1 - i)
    return res


def crc_generic(
    data: bytes,
    width: int,
    poly: int,
    init: int,
    refin: bool,
    refout: bool,
    xorout: int,
) -> int:
    topbit = 1 << (width - 1)
    mask = (1 << width) - 1
    crc = init & mask
    for b in data:
        if refin:
            b = _reflect(b, 8)
        crc ^= b << (width - 8)
        crc &= mask
        for _ in range(8):
            if crc & topbit:
                crc = ((crc << 1) ^ poly) & mask
            else:
                crc = (crc << 1) & mask
    if refout:
        crc = _reflect(crc, width)
    return (crc ^ xorout) & mask


# 预置算法表：(poly, init, refin, refout, xorout)
PRESETS = {
    "CRC-8": (0x07, 0x00, False, False, 0x00),
    "CRC-8/MAXIM": (0x31, 0x00, True, True, 0x00),
    "CRC-16/MODBUS": (0x8005, 0xFFFF, True, True, 0x0000),
    "CRC-16/CCITT-FALSE": (0x1021, 0xFFFF, False, False, 0x0000),
    "CRC-16/USB": (0x8005, 0xFFFF, True, True, 0xFFFF),
    "CRC-32": (0x04C11DB7, 0xFFFFFFFF, True, True, 0xFFFFFFFF),
}


def crc(name: str, data: bytes) -> int:
    if name not in PRESETS:
        raise ValueError(f"unknown crc preset: {name}")
    poly, init, refin, refout, xorout = PRESETS[name]
    return crc_generic(data, _width_of(name), poly, init, refin, refout, xorout)


def _width_of(name: str) -> int:
    return 8 if "CRC-8" in name else (32 if "CRC-32" in name else 16)


def crc_hex(name: str, data: bytes) -> str:
    val = crc(name, data)
    width = _width_of(name)
    return format(val, f"0{width // 4}x").upper()


def crc_custom(
    data: bytes,
    width: int,
    poly: int,
    init: int,
    refin: bool,
    refout: bool,
    xorout: int,
) -> int:
    """任意参数 CRC 计算（参数由调用方提供）。"""
    return crc_generic(data, int(width), int(poly), int(init),
                       bool(refin), bool(refout), int(xorout))


def crc_hex_custom(
    data: bytes,
    width: int,
    poly: int,
    init: int,
    refin: bool,
    refout: bool,
    xorout: int,
) -> str:
    """任意参数 CRC，按位宽输出定长大写十六进制。"""
    val = crc_custom(data, width, poly, init, refin, refout, xorout)
    return format(val, f"0{int(width) // 4}X")
