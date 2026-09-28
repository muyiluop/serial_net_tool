"""自动回复规则引擎（纯逻辑）。
接收数据触发 -> 按序匹配（精确/包含/前缀/正则）-> 命中返回回复字节（可延时/限频）。
"""
import re
import time
from dataclasses import dataclass, fields
from typing import Literal

from .utils import text_to_bytes

VALID_MATCH = ("exact", "contains", "prefix", "regex")
VALID_REPLY_MODE = ("ascii", "hex")


@dataclass
class ReplyRule:
    match: Literal["exact", "contains", "prefix", "regex"] = "contains"
    pattern: str = ""
    reply: str = ""
    reply_mode: Literal["ascii", "hex"] = "ascii"
    delay_ms: int = 0
    rate_limit_ms: int = 0
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict, strict: bool = False) -> "ReplyRule":
        """从 dict 构造；忽略未知键。strict=True 时对非法规则抛 ValueError。"""
        known = {f.name for f in fields(cls)}
        rule = cls(**{k: v for k, v in data.items() if k in known})
        if strict:
            ok, err = validate_rule(rule)
            if not ok:
                raise ValueError(err)
        return rule


def validate_rule(rule: ReplyRule) -> tuple[bool, str]:
    """校验规则合法性，返回 (ok, error_message)。"""
    if rule.match not in VALID_MATCH:
        return False, f"invalid match: {rule.match}"
    if rule.reply_mode not in VALID_REPLY_MODE:
        return False, f"invalid reply_mode: {rule.reply_mode}"
    try:
        if int(rule.delay_ms) < 0 or int(rule.rate_limit_ms) < 0:
            return False, "delay/rate must be >= 0"
    except (TypeError, ValueError):
        return False, "delay/rate must be integers"
    if rule.match == "regex":
        try:
            re.compile(rule.pattern)
        except re.error as e:
            return False, f"invalid regex: {e}"
    else:
        try:
            text_to_bytes(rule.pattern, rule.reply_mode)
        except Exception as e:
            return False, f"invalid pattern: {e}"
    try:
        text_to_bytes(rule.reply, rule.reply_mode)
    except Exception as e:
        return False, f"invalid reply: {e}"
    return True, ""


class AutoReplyEngine:
    def __init__(self):
        self.rules: list[ReplyRule] = []
        self._last_sent: dict[int, float] = {}

    def set_rules(self, rules: list[ReplyRule]) -> None:
        self.rules = rules
        self._last_sent.clear()

    def load_config(self, cfg_list: list[dict]) -> None:
        self.rules = [ReplyRule(**r) for r in cfg_list]
        self._last_sent.clear()

    def to_config(self) -> list[dict]:
        return [vars(r) for r in self.rules]

    def _match_one(self, rule: ReplyRule, data: bytes) -> bool:
        try:
            pat = text_to_bytes(rule.pattern, rule.reply_mode)
        except Exception:
            return False
        if rule.match == "exact":
            return data == pat
        if rule.match == "contains":
            return pat in data
        if rule.match == "prefix":
            return data.startswith(pat)
        if rule.match == "regex":
            try:
                return re.search(rule.pattern, data.decode("latin1")) is not None
            except Exception:
                return False
        return False

    def match(self, data: bytes) -> list[tuple[bytes, int]]:
        """返回 [(回复字节, 延时ms), ...]，供调用方在延时后发送。"""
        results: list[tuple[bytes, int]] = []
        now = time.monotonic() * 1000
        for i, r in enumerate(self.rules):
            if not r.enabled:
                continue
            if not self._match_one(r, data):
                continue
            if r.rate_limit_ms > 0:
                last = self._last_sent.get(i, 0.0)
                if now - last < r.rate_limit_ms:
                    continue
                self._last_sent[i] = now
            try:
                reply = text_to_bytes(r.reply, r.reply_mode)
                results.append((reply, r.delay_ms))
            except Exception:
                continue
        return results
