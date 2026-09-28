"""Modbus PDU 构造器（build_pdu_for_fc）测试。"""
import pytest

from serial_net_tool.plugins.modbus_tool.frame import build_pdu_for_fc


def test_read_pdu():
    assert build_pdu_for_fc(0x03, 0x0000, quantity=1) == b"\x00\x00\x00\x01"
    assert build_pdu_for_fc(0x01, 0x0010, quantity=8) == b"\x00\x10\x00\x08"


def test_write_single_coil():
    assert build_pdu_for_fc(0x05, 0x0001, coil_on=True) == b"\x00\x01\xFF\x00"
    assert build_pdu_for_fc(0x05, 0x0001, coil_on=False) == b"\x00\x01\x00\x00"


def test_write_single_reg():
    assert build_pdu_for_fc(0x06, 0x0002, value=0x0102) == b"\x00\x02\x01\x02"


def test_write_multiple_coils():
    pdu = build_pdu_for_fc(0x0F, 0x0013, multi_values=[1, 0, 1, 1])
    # 4 线圈 -> 1 字节；bit0=1,bit1=0,bit2=1,bit3=1 -> 0b1101 = 0x0D
    assert pdu == b"\x00\x13\x00\x04\x01\x0d"


def test_write_multiple_coils_truthy_ints():
    pdu = build_pdu_for_fc(0x0F, 0x0000, multi_values=[2, 0, 5])
    assert pdu[5] == 0b101


def test_write_multiple_regs():
    pdu = build_pdu_for_fc(0x10, 0x0001, multi_values=[0x000A, 0x0102])
    assert pdu == b"\x00\x01\x00\x02\x04\x00\x0a\x01\x02"


def test_write_multiple_regs_masks_16bit():
    pdu = build_pdu_for_fc(0x10, 0x0000, multi_values=[0x1FFFF])
    assert pdu == b"\x00\x00\x00\x01\x02\xff\xff"


@pytest.mark.parametrize("fc", [0x0F, 0x10])
def test_missing_values_raises(fc):
    with pytest.raises(ValueError):
        build_pdu_for_fc(fc, 0x0000)


def test_unsupported_fc_raises():
    with pytest.raises(ValueError):
        build_pdu_for_fc(0x99, 0x0000)
