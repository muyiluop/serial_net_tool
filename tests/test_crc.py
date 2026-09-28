"""CRC 算法已知向量测试。"""
import pytest

from serial_net_tool.tools.crc import (
    PRESETS,
    crc,
    crc_custom,
    crc_generic,
    crc_hex,
    crc_hex_custom,
)

CHECK = b"123456789"

# 标准检校值（check value）
KNOWN = {
    "CRC-8": 0xF4,
    "CRC-8/MAXIM": 0xA1,
    "CRC-16/MODBUS": 0x4B37,
    "CRC-16/CCITT-FALSE": 0x29B1,
    "CRC-16/USB": 0xB4C8,
    "CRC-32": 0xCBF43926,
}


@pytest.mark.parametrize("name,expected", KNOWN.items())
def test_preset_check_values(name, expected):
    assert crc(name, CHECK) == expected


def test_crc_hex_width():
    assert crc_hex("CRC-16/MODBUS", CHECK) == "4B37"
    assert crc_hex("CRC-8", CHECK) == "F4"
    assert crc_hex("CRC-32", CHECK) == "CBF43926"


def test_empty_data_uses_init():
    # 空数据应返回 init（再经 xorout / refout 处理）
    assert crc("CRC-16/CCITT-FALSE", b"") == 0xFFFF


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        crc("NOPE", b"")


def test_presets_have_all_fields():
    for name, params in PRESETS.items():
        assert len(params) == 5, name


def test_custom_params_match_preset():
    # 用 CRC-16/MODBUS 的参数走通用入口，结果应一致
    poly, init, refin, refout, xorout = PRESETS["CRC-16/MODBUS"]
    val = crc_generic(CHECK, 16, poly, init, refin, refout, xorout)
    assert val == 0x4B37
    # 便捷封装应与通用入口一致
    assert crc_custom(CHECK, 16, poly, init, refin, refout, xorout) == 0x4B37
    assert crc_hex_custom(CHECK, 16, poly, init, refin, refout, xorout) == "4B37"


def test_custom_widths_format():
    # CRC-8 自定义
    poly, init, refin, refout, xorout = PRESETS["CRC-8/MAXIM"]
    assert crc_hex_custom(CHECK, 8, poly, init, refin, refout, xorout) == "A1"
    # CRC-32 自定义
    poly, init, refin, refout, xorout = PRESETS["CRC-32"]
    assert crc_hex_custom(CHECK, 32, poly, init, refin, refout, xorout) == "CBF43926"


def test_custom_all_zero_params():
    assert crc_custom(CHECK, 16, 0, 0, False, False, 0) == 0
