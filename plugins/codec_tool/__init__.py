"""示例插件（window 型）：Base64 / URL / JSON 编解码。

演示要点：
- TOOL_TYPE="window"：由框架包装为非模态独立窗口（更大展示空间）。
- 仅依赖标准库（base64 / urllib.parse / json），零额外依赖。
- 元信息同时来自模块属性与 plugin.json（模块属性优先）。
"""
import base64
import json
import urllib.parse

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
)

from serial_net_tool.core.i18n import get_language

NAME = "编解码工具"
VERSION = "1.0"
TOOL_TYPE = "window"

_LANG = {
    "zh": {
        "input": "输入",
        "output": "输出",
        "b64e": "Base64 编码",
        "b64d": "Base64 解码",
        "urle": "URL 编码",
        "urld": "URL 解码",
        "jsonp": "JSON 美化",
        "jsonm": "JSON 压缩",
        "hint": "示例插件：window 型，独立窗口展示",
    },
    "en": {
        "input": "Input",
        "output": "Output",
        "b64e": "Base64 Encode",
        "b64d": "Base64 Decode",
        "urle": "URL Encode",
        "urld": "URL Decode",
        "jsonp": "JSON Pretty",
        "jsonm": "JSON Minify",
        "hint": "Example plugin: window type, shown in a standalone window",
    },
}


def _t(key: str) -> str:
    return _LANG.get(get_language(), _LANG["en"]).get(key, key)


def create_widget(ctx=None) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setSpacing(6)

    layout.addWidget(QLabel(_t("input")))
    inp = QPlainTextEdit()
    inp.setObjectName("mono")
    inp.setPlaceholderText("hello / aGVsbG8= / {\"a\":1}")
    layout.addWidget(inp, 1)

    def show(fn):
        try:
            out.setPlainText(fn(inp.toPlainText()))
        except Exception as e:
            out.setPlainText(f"ERR: {e}")

    def b64_enc(s: str) -> str:
        return base64.b64encode(s.encode("utf-8")).decode("ascii")

    def b64_dec(s: str) -> str:
        return base64.b64decode(s.strip()).decode("utf-8", errors="replace")

    def url_enc(s: str) -> str:
        return urllib.parse.quote(s, safe="")

    def url_dec(s: str) -> str:
        return urllib.parse.unquote(s)

    def json_pretty(s: str) -> str:
        return json.dumps(json.loads(s), ensure_ascii=False, indent=2)

    def json_min(s: str) -> str:
        return json.dumps(json.loads(s), ensure_ascii=False, separators=(",", ":"))

    row1 = QHBoxLayout()
    for label, fn in ((_t("b64e"), b64_enc), (_t("b64d"), b64_dec),
                      (_t("urle"), url_enc), (_t("urld"), url_dec)):
        b = QPushButton(label)
        b.setObjectName("ghost")
        b.clicked.connect(lambda _=False, f=fn: show(f))
        row1.addWidget(b)
    layout.addLayout(row1)

    row2 = QHBoxLayout()
    for label, fn in ((_t("jsonp"), json_pretty), (_t("jsonm"), json_min)):
        b = QPushButton(label)
        b.setObjectName("ghost")
        b.clicked.connect(lambda _=False, f=fn: show(f))
        row2.addWidget(b)
    row2.addStretch()
    layout.addLayout(row2)

    layout.addWidget(QLabel(_t("output")))
    out = QPlainTextEdit()
    out.setObjectName("mono")
    out.setReadOnly(True)
    layout.addWidget(out, 1)

    hint = QLabel(_t("hint"))
    hint.setObjectName("dim")
    layout.addWidget(hint)
    return w
