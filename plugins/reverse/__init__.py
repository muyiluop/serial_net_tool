"""示例插件（dock 型）：字节反转 / 16 位字节序交换 / 位反转。

演示要点：
- 通过 plugin.json manifest 声明工具类型与元信息（本文件不写 TOOL_TYPE）。
- 使用主程序提供的 tools.conv 能力，不重复造轮子。
- Dock 型插件需适配 240-340px 窄宽度，控件纵向排列。
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from serial_net_tool.core.i18n import get_language
from serial_net_tool.tools.conv import swap_endian

NAME = "字节反转"

_LANG = {
    "zh": {
        "input": "输入 Hex",
        "output": "结果",
        "reverse": "字节反转",
        "endian": "16位字节序交换",
        "bits": "位反转(逐字节)",
        "hint": "示例插件：演示插件 SDK 与 tools.conv 复用",
    },
    "en": {
        "input": "Input Hex",
        "output": "Result",
        "reverse": "Reverse Bytes",
        "endian": "Swap 16-bit Endian",
        "bits": "Reverse Bits (per byte)",
        "hint": "Example plugin: shows the plugin SDK and tools.conv reuse",
    },
}


def _t(key: str) -> str:
    return _LANG.get(get_language(), _LANG["en"]).get(key, key)


def _parse_hex(text: str) -> bytes:
    clean = "".join((text or "").split())
    if len(clean) % 2:
        clean = "0" + clean
    return bytes.fromhex(clean)


def create_widget(ctx=None) -> QWidget:
    """创建插件界面。ctx 为 MainWindow 引用（此处未使用）。"""
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setSpacing(6)

    layout.addWidget(QLabel(_t("input")))
    inp = QLineEdit("01 02 03 04")
    inp.setObjectName("mono")
    layout.addWidget(inp)

    out_lbl = QLabel(_t("output"))
    out_lbl.setObjectName("dim")
    layout.addWidget(out_lbl)
    out = QLineEdit("")
    out.setObjectName("mono")
    out.setReadOnly(True)
    layout.addWidget(out)

    def apply(fn):
        try:
            out.setText(fn(_parse_hex(inp.text())).hex(" ").upper())
        except Exception as e:
            out.setText(f"ERR: {e}")

    row = QHBoxLayout()
    btn_rev = QPushButton(_t("reverse"))
    btn_rev.setObjectName("ghost")
    btn_end = QPushButton(_t("endian"))
    btn_end.setObjectName("ghost")
    row.addWidget(btn_rev)
    row.addWidget(btn_end)
    layout.addLayout(row)

    btn_bits = QPushButton(_t("bits"))
    btn_bits.setObjectName("ghost")
    layout.addWidget(btn_bits)

    hint = QLabel(_t("hint"))
    hint.setObjectName("dim")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    layout.addStretch()

    btn_rev.clicked.connect(lambda: apply(lambda b: b[::-1]))
    btn_end.clicked.connect(lambda: apply(swap_endian))
    btn_bits.clicked.connect(
        lambda: apply(lambda b: bytes(int(f"{x:08b}"[::-1], 2) for x in b))
    )
    return w
