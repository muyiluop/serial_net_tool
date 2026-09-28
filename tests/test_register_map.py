"""寄存器映射与数值解析测试。"""
from serial_net_tool.plugins.modbus_tool.register_map import (
    RegisterConfig,
    RegisterMap,
    encode_value,
    parse_value,
    reg_count_for_type,
)


def test_reg_count():
    assert reg_count_for_type("uint16") == 1
    assert reg_count_for_type("uint32_be") == 2
    assert reg_count_for_type("float32_le") == 2
    assert reg_count_for_type("nope") == 1


def test_parse_uint16_int16():
    assert parse_value([0x00FF], "uint16") == 255
    assert parse_value([0xFFFF], "int16") == -1


def test_parse_uint32_be():
    # 两个寄存器按大端拼成 32 位
    assert parse_value([0x0001, 0x0002], "uint32_be") == 0x00010002


def test_parse_int32_be_negative():
    assert parse_value([0xFFFF, 0xFFFF], "int32_be") == -1


def test_32bit_endian_roundtrip():
    for reg_type, value in [
        ("uint32_be", 0x12345678),
        ("uint32_le", 0x12345678),
        ("float32_be", 1.5),
        ("float32_le", 1.5),
    ]:
        raw = encode_value(value, reg_type)
        assert parse_value(raw, reg_type) == value


def test_parse_float32_be():
    # 1.0 的 IEEE754 大端：0x3F80 0x0000
    assert parse_value([0x3F80, 0x0000], "float32_be") == 1.0


def test_encode_value_roundtrip():
    for reg_type, value in [("uint16", 1234), ("int16", -5), ("uint32_be", 0x12345678)]:
        raw = encode_value(value, reg_type)
        assert parse_value(raw, reg_type) == value


def test_set_raw_values_updates_configs():
    m = RegisterMap()
    m.add("R0", 0, "uint16")
    m.add("R1", 1, "uint32_be")
    m.set_raw_values(0, [0x0001, 0x0002, 0x0003])
    assert m.configs[0].value == 0x0001
    assert m.configs[1].value == 0x00020003


def test_unknown_type_parses_zero():
    m = RegisterMap()
    c = m.add("R", 0, "nope")
    m.set_raw_values(0, [7])
    assert reg_count_for_type("nope") == 1
    assert c.value == 0  # 未知类型无法解析，退化为 0


def test_poll_blocks_merge_contiguous():
    m = RegisterMap()
    m.add("A", 0, "uint16")
    m.add("B", 1, "uint16")
    m.add("C", 2, "uint16")
    blocks = m.get_poll_blocks()
    assert blocks == [(0x03, 0, 3)]


def test_poll_blocks_separate_far_addresses():
    m = RegisterMap()
    m.add("A", 0, "uint16")
    m.add("B", 100, "uint16")
    blocks = m.get_poll_blocks()
    assert blocks == [(0x03, 0, 1), (0x03, 100, 1)]


def test_poll_blocks_grouped_by_function_code():
    m = RegisterMap()
    m.add("Holding", 0, "uint16", func_code=0x03)
    m.add("Coil", 0, "uint16", func_code=0x01)
    m.add("Input", 10, "uint16", func_code=0x04)
    blocks = m.get_poll_blocks()
    assert (0x01, 0, 1) in blocks
    assert (0x03, 0, 1) in blocks
    assert (0x04, 10, 1) in blocks
    assert len(blocks) == 3


def test_poll_blocks_empty():
    assert RegisterMap().get_poll_blocks() == []


def test_to_from_list():
    m = RegisterMap()
    m.add("A", 0, "int16", "desc", func_code=0x04)
    data = m.to_list()
    assert data[0]["func_code"] == 0x04
    m2 = RegisterMap()
    m2.from_list(data)
    assert m2.configs[0].func_code == 0x04
    assert m2.configs[0] == RegisterConfig(
        name="A", address=0, reg_type="int16", description="desc", func_code=0x04
    )
