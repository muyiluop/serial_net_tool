"""自动回复引擎与规则校验测试。"""
import pytest

from serial_net_tool.core.autoreply import AutoReplyEngine, ReplyRule, validate_rule


def _engine(*rules):
    e = AutoReplyEngine()
    e.set_rules(list(rules))
    return e


def test_contains_match_and_reply():
    e = _engine(ReplyRule(match="contains", pattern="AA", reply="BB"))
    assert e.match(b"xxAAxx") == [(b"BB", 0)]


def test_exact_prefix_regex():
    assert _engine(ReplyRule(match="exact", pattern="AA", reply="1")).match(b"AA") == [(b"1", 0)]
    assert _engine(ReplyRule(match="exact", pattern="AA", reply="1")).match(b"AAB") == []
    assert _engine(ReplyRule(match="prefix", pattern="AA", reply="1")).match(b"AAB") == [(b"1", 0)]
    assert _engine(ReplyRule(match="regex", pattern=r"^A\d+B$", reply="1")).match(b"A12B") == [(b"1", 0)]


def test_disabled_rule_skipped():
    e = _engine(ReplyRule(match="contains", pattern="AA", reply="BB", enabled=False))
    assert e.match(b"AA") == []


def test_delay_returned():
    e = _engine(ReplyRule(match="contains", pattern="AA", reply="BB", delay_ms=250))
    assert e.match(b"AA") == [(b"BB", 250)]


def test_rate_limit():
    e = _engine(ReplyRule(match="contains", pattern="AA", reply="BB", rate_limit_ms=10000))
    assert e.match(b"AA") == [(b"BB", 0)]
    # 窗口内第二次被限频
    assert e.match(b"AA") == []


def test_hex_pattern_and_reply():
    e = _engine(ReplyRule(match="exact", pattern="AA BB", reply="CC DD", reply_mode="hex"))
    assert e.match(b"\xaa\xbb") == [(b"\xcc\xdd", 0)]


# ---------- validate_rule ----------

def test_validate_ok():
    ok, err = validate_rule(ReplyRule(match="contains", pattern="AA", reply="BB"))
    assert ok and err == ""


def test_validate_bad_match():
    ok, err = validate_rule(ReplyRule(match="fuzzy", pattern="a", reply="b"))
    assert not ok and "match" in err


def test_validate_bad_regex():
    ok, err = validate_rule(ReplyRule(match="regex", pattern="([", reply="x"))
    assert not ok and "regex" in err


def test_validate_bad_hex():
    ok, err = validate_rule(ReplyRule(match="exact", pattern="ZZ", reply_mode="hex", reply="AA"))
    assert not ok


def test_validate_negative_delay():
    ok, err = validate_rule(ReplyRule(delay_ms=-1))
    assert not ok


# ---------- from_dict ----------

def test_from_dict_ignores_unknown_keys():
    rule = ReplyRule.from_dict({"match": "exact", "pattern": "A", "reply": "B", "bogus": 1})
    assert rule.match == "exact"


def test_from_dict_strict_raises_on_invalid():
    with pytest.raises(ValueError):
        ReplyRule.from_dict({"match": "regex", "pattern": "([", "reply": "x"}, strict=True)


def test_from_dict_defaults():
    rule = ReplyRule.from_dict({})
    assert rule.match == "contains" and rule.enabled is True
