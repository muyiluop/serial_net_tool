"""国际化字典一致性测试。"""
import re

from serial_net_tool.core.i18n import TRANSLATIONS, tr

ZH = TRANSLATIONS["zh"]
EN = TRANSLATIONS["en"]


def test_key_sets_align():
    assert set(ZH) == set(EN)


def test_no_empty_values():
    for lang, table in TRANSLATIONS.items():
        for key, val in table.items():
            assert isinstance(val, str) and val != "", f"{lang}:{key} empty"


def test_unknown_key_returns_key():
    assert tr("__definitely_missing__") == "__definitely_missing__"


def test_format_placeholders_match():
    """中英文案的 {} 占位符数量应一致。"""
    for key in ZH:
        zh_n = len(re.findall(r"\{\}", ZH[key]))
        en_n = len(re.findall(r"\{\}", EN[key]))
        assert zh_n == en_n, f"{key}: zh={zh_n} en={en_n}"


def test_new_feature_keys_present():
    required = {
        "mqtt_no_publish_topic",
        "mqtt_published",
    }
    assert required <= set(ZH)
