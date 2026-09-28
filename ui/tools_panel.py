"""右侧工具面板：CRC / 校验和 / 进制转换 / Hex转文件 / 自动回复 / Modbus报文 + 插件。

导航采用「顶部下拉选择器 + 内容区」而非横向 Tab：
- 在 260–440px 的窄 Dock 内不会出现 Tab 溢出的滚动箭头与标签截断；
- 选择器按「内置 / 插件」分组，插件新增一项即可。
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QComboBox,
    QFrame,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QFileDialog,
    QMessageBox,
    QLabel,
    QScrollArea,
    QStackedWidget,
)
from PySide6.QtGui import QColor

from ..core.utils import text_to_bytes, parse_int
from ..core.autoreply import ReplyRule, validate_rule
from ..tools.crc import PRESETS, crc, crc_custom, crc_hex
from ..tools.check import all_checksums
from ..tools.conv import int_to_base, swap_endian, str_to_hex, hex_to_str
from ..core.config import Config
from ..core.autoreply import AutoReplyEngine
from ..core.i18n import tr
from ..core.theme import tokens, icon, icon_pixmap


class ToolsPanel(QWidget):
    def __init__(
        self, autoreply: AutoReplyEngine, config: Config, main_window=None, parent=None
    ):
        super().__init__(parent)
        self.autoreply = autoreply
        self.config = config
        self.main_window = main_window
        # 页面表：[(名称, 控件, 是否内置)]
        self._pages: list = []
        self._builtin_tab_count = 0
        self._stack = QStackedWidget()

        self._selector = QComboBox()
        self._selector.setObjectName("tool_selector")
        self._selector.currentIndexChanged.connect(self._on_selector_changed)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._header_icon = QLabel()
        header.addWidget(self._header_icon)
        header.addWidget(self._selector, 1)

        # 内置工具页（按顺序）
        builtin = [
            (tr("crc"), self._crc_tab()),
            (tr("checksum"), self._checksum_tab()),
            (tr("convert"), self._conv_tab()),
            (tr("hex_to_file"), self._hexfile_tab()),
            (tr("auto_reply"), self._autoreply_tab()),
            (tr("modbus_frame"), self._modbus_tab()),
        ]
        for name, widget in builtin:
            self._append_page(name, widget, builtin=True)
        self._builtin_tab_count = len(self._pages)
        self._rebuild_selector()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._stack, 1)
        self.refresh_theme()

    # ================= 页面与导航 =================
    def _append_page(self, name: str, widget: QWidget, builtin: bool):
        self._stack.addWidget(widget)
        self._pages.append((name, widget, builtin))

    def _add_group_header(self, text: str):
        """在下拉中加入不可选的组标题（含上方分隔线）。"""
        self._selector.insertSeparator(self._selector.count())
        self._selector.addItem(text)
        item = self._selector.model().item(self._selector.count() - 1)
        if item is not None:
            item.setEnabled(False)

    def _rebuild_selector(self):
        """按页面表重建下拉项（itemData 存 stack 索引，组标题为 None）。"""
        current = self._stack.currentIndex()
        self._selector.blockSignals(True)
        self._selector.clear()
        builtin_added = plugin_added = False
        for idx, (name, _widget, builtin) in enumerate(self._pages):
            if builtin and not builtin_added:
                self._add_group_header(tr("tools_builtin"))
                builtin_added = True
            elif not builtin and not plugin_added:
                self._add_group_header(tr("tools_plugins"))
                plugin_added = True
            self._selector.addItem(name, idx)
        self._selector.blockSignals(False)
        target = 0
        for i in range(self._selector.count()):
            if self._selector.itemData(i) == current:
                target = i
                break
        else:
            for i in range(self._selector.count()):
                if self._selector.itemData(i) is not None:
                    target = i
                    break
        self._selector.setCurrentIndex(target)
        self._on_selector_changed(target)

    def _on_selector_changed(self, index: int):
        data = self._selector.itemData(index)
        if data is not None:
            self._stack.setCurrentIndex(int(data))

    def add_dock_tab(self, name, widget):
        """添加 dock 型插件页。"""
        self._append_page(name, widget, builtin=False)
        self._rebuild_selector()

    def remove_plugin_tabs(self):
        """移除所有插件页（保留内置页）。"""
        while len(self._pages) > self._builtin_tab_count:
            _name, widget, _builtin = self._pages.pop()
            self._stack.removeWidget(widget)
            widget.deleteLater()
        self._rebuild_selector()

    def refresh_theme(self):
        """主题切换后刷新头部图标。"""
        self._header_icon.setPixmap(icon_pixmap("settings", tokens()["text_dim"], 16))

    def current_tool_name(self) -> str:
        """当前选中的工具名（便于测试与调试）。"""
        data = self._selector.currentData()
        if data is None:
            return ""
        return self._pages[int(data)][0]

    # ================= CRC =================

    def _crc_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        self.crc_algo = QComboBox()
        for name in PRESETS:
            self.crc_algo.addItem(name, name)
        self.crc_algo.addItem(tr("crc_custom"), "__custom__")
        layout.addWidget(self.crc_algo)

        h = QHBoxLayout()
        h.setSpacing(6)
        self.crc_ascii = QRadioButton(tr("ascii"))
        self.crc_hex = QRadioButton(tr("hex"))
        self.crc_ascii.setChecked(True)
        self.crc_bg = QButtonGroup(self)
        self.crc_bg.addButton(self.crc_ascii)
        self.crc_bg.addButton(self.crc_hex)
        h.addWidget(self.crc_ascii)
        h.addWidget(self.crc_hex)
        h.addStretch()
        layout.addLayout(h)

        self.crc_in = QPlainTextEdit()
        self.crc_in.setPlaceholderText(tr("input_data"))
        layout.addWidget(self.crc_in, 1)

        # ---- 自定义参数（仅"自定义"时显示） ----
        self.crc_custom_box = QGroupBox(tr("crc_custom_params"))
        cg = QGridLayout(self.crc_custom_box)
        cg.setSpacing(4)
        self.crc_width = QComboBox()
        for bits in (8, 16, 32):
            self.crc_width.addItem(f"{bits}", bits)
        self.crc_width.setCurrentText("16")
        self.crc_poly = QLineEdit("0x8005")
        self.crc_init = QLineEdit("0xFFFF")
        self.crc_xorout = QLineEdit("0x0000")
        self.crc_refin = QCheckBox(tr("crc_refin"))
        self.crc_refout = QCheckBox(tr("crc_refout"))
        self.crc_refin.setChecked(True)
        self.crc_refout.setChecked(True)
        for i, (lbl, wid) in enumerate([
            (tr("crc_width"), self.crc_width),
            (tr("crc_poly"), self.crc_poly),
            (tr("crc_init"), self.crc_init),
            (tr("crc_xorout"), self.crc_xorout),
        ]):
            lab = QLabel(lbl)
            lab.setObjectName("dim")
            cg.addWidget(lab, i, 0)
            cg.addWidget(wid, i, 1)
        cg.addWidget(self.crc_refin, 4, 0, 1, 2)
        cg.addWidget(self.crc_refout, 5, 0, 1, 2)
        cg.setColumnStretch(1, 1)
        self.crc_custom_box.setVisible(False)
        layout.addWidget(self.crc_custom_box)

        layout.addWidget(QLabel(tr("result")))
        self.crc_out = QLineEdit()
        self.crc_out.setReadOnly(True)
        self.crc_out.setText("0")
        self.crc_out.setObjectName("mono")
        layout.addWidget(self.crc_out)
        self.crc_dec = QLabel("DEC: 0")
        self.crc_dec.setObjectName("dim")
        self.crc_bin = QLabel("BIN: 0")
        self.crc_bin.setObjectName("dim")
        self.crc_bin.setWordWrap(True)
        layout.addWidget(self.crc_dec)
        layout.addWidget(self.crc_bin)

        self.crc_algo.currentIndexChanged.connect(self._on_crc_algo_changed)
        self.crc_in.textChanged.connect(self._crc_update)
        self.crc_bg.buttonClicked.connect(self._crc_update)
        for wid in (self.crc_poly, self.crc_init, self.crc_xorout):
            wid.textChanged.connect(self._crc_update)
        self.crc_width.currentIndexChanged.connect(self._crc_update)
        self.crc_refin.toggled.connect(self._crc_update)
        self.crc_refout.toggled.connect(self._crc_update)
        self._crc_update()
        return w

    def _on_crc_algo_changed(self, _idx):
        self.crc_custom_box.setVisible(self.crc_algo.currentData() == "__custom__")
        self._crc_update()

    def _crc_update(self):
        try:
            text = self.crc_in.toPlainText()
            mode = "hex" if self.crc_hex.isChecked() else "ascii"
            data = text_to_bytes(
                text, mode, self.config.get("default_encoding", "utf-8")
            )
            algo = self.crc_algo.currentData()
            if algo is None:
                return
            if algo == "__custom__":
                width = int(self.crc_width.currentData())
                val = crc_custom(
                    data,
                    width,
                    parse_int(self.crc_poly.text() or "0"),
                    parse_int(self.crc_init.text() or "0"),
                    self.crc_refin.isChecked(),
                    self.crc_refout.isChecked(),
                    parse_int(self.crc_xorout.text() or "0"),
                )
                self.crc_out.setText(format(val, f"0{width // 4}X"))
            else:
                val = crc(algo, data)
                self.crc_out.setText(crc_hex(algo, data))
            self.crc_dec.setText(f"DEC: {val}")
            self.crc_bin.setText(f"BIN: {val:b}")
        except Exception as e:
            self.crc_out.setText(f"ERR:{e}")

    # ================= 校验和 =================

    def _checksum_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        h = QHBoxLayout()
        h.setSpacing(6)
        self.cs_ascii = QRadioButton(tr("ascii"))
        self.cs_hex = QRadioButton(tr("hex"))
        self.cs_ascii.setChecked(True)
        self.cs_bg = QButtonGroup(self)
        self.cs_bg.addButton(self.cs_ascii)
        self.cs_bg.addButton(self.cs_hex)
        h.addWidget(self.cs_ascii)
        h.addWidget(self.cs_hex)
        h.addStretch()
        layout.addLayout(h)

        self.cs_in = QPlainTextEdit()
        self.cs_in.setPlaceholderText(tr("input_data"))
        layout.addWidget(self.cs_in, 1)

        layout.addWidget(QLabel(tr("result")))
        # 2x2 网格结果
        grid = QGridLayout()
        grid.setSpacing(4)
        self.cs_sum8 = QLabel("SUM8: 0")
        self.cs_sum16 = QLabel("SUM16: 0")
        self.cs_xor = QLabel("XOR: 0")
        self.cs_lrc = QLabel("LRC: 0")
        for lbl in (self.cs_sum8, self.cs_sum16, self.cs_xor, self.cs_lrc):
            lbl.setWordWrap(True)
        grid.addWidget(self.cs_sum8, 0, 0)
        grid.addWidget(self.cs_sum16, 0, 1)
        grid.addWidget(self.cs_xor, 1, 0)
        grid.addWidget(self.cs_lrc, 1, 1)
        layout.addLayout(grid)

        layout.addStretch()

        self.cs_in.textChanged.connect(self._cs_update)
        self.cs_bg.buttonClicked.connect(self._cs_update)
        return w

    def _cs_update(self):
        try:
            text = self.cs_in.toPlainText()
            mode = "hex" if self.cs_hex.isChecked() else "ascii"
            data = text_to_bytes(
                text, mode, self.config.get("default_encoding", "utf-8")
            )
            res = all_checksums(data)
            self.cs_sum8.setText(f"SUM8: {res['SUM8']}")
            self.cs_sum16.setText(f"SUM16: {res['SUM16']}")
            self.cs_xor.setText(f"XOR: {res['XOR']}")
            self.cs_lrc.setText(f"LRC: {res['LRC']}")
        except Exception as e:
            self.cs_sum8.setText(f"ERR:{e}")

    # ================= 进制转换 =================

    def _conv_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # --- 整数进制 ---
        lbl1 = QLabel(tr("integer"))
        lbl1.setObjectName("dim")
        layout.addWidget(lbl1)

        h1 = QHBoxLayout()
        h1.setSpacing(4)
        self.conv_int = QLineEdit("255")
        self.conv_base = QComboBox()
        self.conv_base.addItems(["DEC", "HEX", "BIN", "OCT"])
        self.conv_base.setCurrentText("DEC")
        self.conv_base.setMinimumWidth(70)
        h1.addWidget(self.conv_int, 1)
        h1.addWidget(self.conv_base)
        layout.addLayout(h1)

        self.conv_out = QLabel("")
        self.conv_out.setWordWrap(True)
        layout.addWidget(self.conv_out)

        # --- 字符串 ↔ Hex ---
        sep1 = QFrame()
        sep1.setObjectName("hsep")
        sep1.setFixedHeight(1)
        layout.addWidget(sep1)

        lbl2 = QLabel(tr("str_to_hex"))
        lbl2.setObjectName("dim")
        layout.addWidget(lbl2)

        self.conv_str = QLineEdit("Hello")
        layout.addWidget(self.conv_str)

        h2 = QHBoxLayout()
        h2.setSpacing(4)
        self.conv_tohex = QPushButton(tr("str_to_hex"))
        self.conv_tohex.setObjectName("ghost")
        self.conv_fromhex = QPushButton(tr("hex_to_str"))
        self.conv_fromhex.setObjectName("ghost")
        h2.addWidget(self.conv_tohex, 1)
        h2.addWidget(self.conv_fromhex, 1)
        layout.addLayout(h2)

        self.conv_strout = QLabel("")
        self.conv_strout.setWordWrap(True)
        layout.addWidget(self.conv_strout)

        # --- 字节序交换 ---
        sep2 = QFrame()
        sep2.setObjectName("hsep")
        sep2.setFixedHeight(1)
        layout.addWidget(sep2)

        lbl3 = QLabel(tr("swap_endian_btn"))
        lbl3.setObjectName("dim")
        layout.addWidget(lbl3)

        self.conv_hexin = QLineEdit("01 02 03 04")
        layout.addWidget(self.conv_hexin)

        self.conv_swap = QPushButton(tr("swap_endian_btn"))
        self.conv_swap.setObjectName("ghost")
        layout.addWidget(self.conv_swap)

        self.conv_swapout = QLabel("")
        self.conv_swapout.setWordWrap(True)
        layout.addWidget(self.conv_swapout)

        layout.addStretch()

        self.conv_int.textChanged.connect(self._conv_update)
        self.conv_base.currentTextChanged.connect(self._conv_update)
        self.conv_tohex.clicked.connect(self._str_to_hex)
        self.conv_fromhex.clicked.connect(self._hex_to_str)
        self.conv_swap.clicked.connect(self._swap)
        self._conv_update()
        return w

    def _conv_update(self):
        try:
            v = int(self.conv_int.text(), 0) if self.conv_int.text() else 0
            base = {"DEC": 10, "HEX": 16, "BIN": 2, "OCT": 8}[
                self.conv_base.currentText()
            ]
            if base != 10:
                v = int(self.conv_int.text(), base)
            self.conv_out.setText(
                f"DEC={int_to_base(v, 10)}  HEX={int_to_base(v, 16)}  BIN={int_to_base(v, 2)}  OCT={int_to_base(v, 8)}"
            )
        except Exception as e:
            self.conv_out.setText(f"ERR:{e}")

    def _str_to_hex(self):
        try:
            self.conv_strout.setText(
                str_to_hex(
                    self.conv_str.text(),
                    self.config.get("default_encoding", "utf-8"),
                )
            )
        except Exception as e:
            self.conv_strout.setText(f"ERR:{e}")

    def _hex_to_str(self):
        try:
            self.conv_strout.setText(
                hex_to_str(
                    self.conv_str.text(),
                    self.config.get("default_encoding", "utf-8"),
                )
            )
        except Exception as e:
            self.conv_strout.setText(f"ERR:{e}")

    def _swap(self):
        try:
            data = bytes.fromhex("".join(self.conv_hexin.text().split()))
            self.conv_swapout.setText(swap_endian(data).hex(" ").upper())
        except Exception as e:
            self.conv_swapout.setText(f"ERR:{e}")

    # ================= Hex 转文件 =================

    def _hexfile_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        self.hf_in = QPlainTextEdit()
        self.hf_in.setPlaceholderText(tr("hex_to_file_input"))
        layout.addWidget(self.hf_in, 1)

        self.hf_save = QPushButton(tr("hex_to_file_save"))
        self.hf_save.setObjectName("accent")
        layout.addWidget(self.hf_save)

        layout.addWidget(QLabel(tr("hex_to_file_preview")))
        self.hf_preview = QLabel("")
        self.hf_preview.setObjectName("dim")
        self.hf_preview.setWordWrap(True)
        layout.addWidget(self.hf_preview)

        layout.addStretch()

        self.hf_save.clicked.connect(self._hex_to_file)
        self.hf_in.textChanged.connect(self._hex_preview)
        return w

    def _parse_hex_input(self) -> bytes | None:
        text = self.hf_in.toPlainText().strip()
        if not text:
            return None
        try:
            cleaned = "".join(text.split())
            return bytes.fromhex(cleaned)
        except Exception:
            return None

    def _hex_preview(self):
        data = self._parse_hex_input()
        if data is None:
            text = self.hf_in.toPlainText().strip()
            if text:
                self.hf_preview.setText(tr("hex_to_file_error").format(""))
            else:
                self.hf_preview.setText("")
            return
        preview = data[:256]
        hex_str = preview.hex(" ").upper()
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in preview)
        self.hf_preview.setText(f"{len(data)} bytes\n{hex_str}\n{ascii_str}")

    def _hex_to_file(self):
        data = self._parse_hex_input()
        if data is None or len(data) == 0:
            QMessageBox.warning(self, tr("error"), tr("hex_to_file_empty"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("hex_to_file_save"), "", "All Files (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(data)
            QMessageBox.information(
                self, tr("notice"), tr("hex_to_file_ok").format(len(data), path)
            )
        except Exception as e:
            QMessageBox.warning(self, tr("error"), tr("hex_to_file_error").format(e))

    # ================= 自动回复（列表 + 详情） =================

    def _autoreply_tab(self):
        # 内容较长，包裹在 QScrollArea 中防止控件被挤压
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(6)

        self.ar_enabled = QCheckBox(tr("enable_autoreply"))
        layout.addWidget(self.ar_enabled)

        # 操作按钮（两行各两个，均分宽度）
        h1 = QHBoxLayout()
        h1.setSpacing(4)
        self.ar_add = QPushButton(tr("add"))
        self.ar_add.setObjectName("ghost")
        self.ar_del = QPushButton(tr("delete_selected"))
        self.ar_del.setObjectName("ghost")
        h1.addWidget(self.ar_add, 1)
        h1.addWidget(self.ar_del, 1)
        layout.addLayout(h1)

        h2 = QHBoxLayout()
        h2.setSpacing(4)
        self.ar_imp = QPushButton(tr("import_btn"))
        self.ar_imp.setObjectName("ghost")
        self.ar_exp = QPushButton(tr("export_btn"))
        self.ar_exp.setObjectName("ghost")
        h2.addWidget(self.ar_imp, 1)
        h2.addWidget(self.ar_exp, 1)
        layout.addLayout(h2)

        # 规则列表
        self.ar_list = QListWidget()
        self.ar_list.setMaximumHeight(120)
        layout.addWidget(self.ar_list)

        # 规则详情编辑区
        detail = QGroupBox(tr("ar_rule_detail"))
        form = QFormLayout(detail)
        form.setSpacing(4)

        self.ar_det_enabled = QCheckBox(tr("ar_enabled_short"))
        form.addRow(self.ar_det_enabled)

        self.ar_det_match = QComboBox()
        self.ar_det_match.addItems(["exact", "contains", "prefix", "regex"])
        form.addRow(tr("ar_match_type"), self.ar_det_match)

        self.ar_det_mode = QComboBox()
        self.ar_det_mode.addItems(["ascii", "hex"])
        form.addRow(tr("ar_reply_mode"), self.ar_det_mode)

        self.ar_det_pattern = QLineEdit()
        form.addRow(tr("ar_pattern"), self.ar_det_pattern)

        self.ar_det_reply = QLineEdit()
        form.addRow(tr("ar_reply_content"), self.ar_det_reply)

        self.ar_det_delay = QSpinBox()
        self.ar_det_delay.setMaximum(999999)
        form.addRow(tr("ar_delay_ms"), self.ar_det_delay)

        self.ar_det_rate = QSpinBox()
        self.ar_det_rate.setMaximum(999999)
        form.addRow(tr("ar_rate_ms"), self.ar_det_rate)

        self.ar_error = QLabel("")
        self.ar_error.setObjectName("badge_err")
        self.ar_error.setWordWrap(True)
        form.addRow(self.ar_error)

        layout.addWidget(detail)

        # 信号连接
        self.ar_enabled.toggled.connect(self._ar_apply)
        self.ar_add.clicked.connect(self._ar_add)
        self.ar_del.clicked.connect(self._ar_del)
        self.ar_imp.clicked.connect(self._ar_import)
        self.ar_exp.clicked.connect(self._ar_export)
        self.ar_list.currentRowChanged.connect(self._ar_on_select)
        # 详情表单修改时回写
        self.ar_det_enabled.toggled.connect(self._ar_on_detail_changed)
        self.ar_det_match.currentTextChanged.connect(self._ar_on_detail_changed)
        self.ar_det_mode.currentTextChanged.connect(self._ar_on_detail_changed)
        self.ar_det_pattern.textChanged.connect(self._ar_on_detail_changed)
        self.ar_det_reply.textChanged.connect(self._ar_on_detail_changed)
        self.ar_det_delay.valueChanged.connect(self._ar_on_detail_changed)
        self.ar_det_rate.valueChanged.connect(self._ar_on_detail_changed)

        self._ar_data = []  # 内部数据列表
        self._ar_loading = False
        self._ar_load()

        scroll.setWidget(content)
        return scroll

    def _ar_load(self):
        cfgs = self.config.get("autoreply_rules", [])
        self._ar_data = [dict(r) for r in cfgs]
        self._ar_refresh_list()

    @staticmethod
    def _ar_rule_valid(r: dict):
        """校验单条规则，返回 (ok, error)。"""
        return validate_rule(ReplyRule.from_dict(r))

    def _ar_refresh_list(self):
        self._ar_loading = True
        self.ar_list.clear()
        err_color = QColor(tokens()["err"])
        for i, r in enumerate(self._ar_data):
            enabled = r.get("enabled", True)
            match = r.get("match", "contains")
            pattern = r.get("pattern", "")
            reply = r.get("reply", "")
            ok, err = self._ar_rule_valid(r)
            if not ok:
                mark = "\u26a0"  # 非法
            else:
                mark = "\u2713" if enabled else "\u2717"
            text = f"{mark} [{match}] {pattern} \u2192 {reply}"
            item = QListWidgetItem(text)
            if not ok:
                item.setForeground(err_color)
                item.setToolTip(err)
            self.ar_list.addItem(item)
        self._ar_loading = False
        if self._ar_data:
            self.ar_list.setCurrentRow(0)
        else:
            self._ar_clear_detail()

    def _ar_on_select(self, row):
        if self._ar_loading:
            return
        if row < 0 or row >= len(self._ar_data):
            self._ar_clear_detail()
            return
        r = self._ar_data[row]
        self._ar_loading = True
        self.ar_det_enabled.setChecked(r.get("enabled", True))
        self.ar_det_match.setCurrentText(r.get("match", "contains"))
        self.ar_det_mode.setCurrentText(r.get("reply_mode", "ascii"))
        self.ar_det_pattern.setText(r.get("pattern", ""))
        self.ar_det_reply.setText(r.get("reply", ""))
        self.ar_det_delay.setValue(r.get("delay_ms", 0))
        self.ar_det_rate.setValue(r.get("rate_limit_ms", 0))
        self._ar_loading = False

    def _ar_clear_detail(self):
        self._ar_loading = True
        self.ar_det_enabled.setChecked(True)
        self.ar_det_match.setCurrentIndex(0)
        self.ar_det_mode.setCurrentIndex(0)
        self.ar_det_pattern.setText("")
        self.ar_det_reply.setText("")
        self.ar_det_delay.setValue(0)
        self.ar_det_rate.setValue(0)
        self._ar_loading = False

    def _ar_on_detail_changed(self):
        if self._ar_loading:
            return
        row = self.ar_list.currentRow()
        if row < 0 or row >= len(self._ar_data):
            return
        r = self._ar_data[row]
        r["enabled"] = self.ar_det_enabled.isChecked()
        r["match"] = self.ar_det_match.currentText()
        r["reply_mode"] = self.ar_det_mode.currentText()
        r["pattern"] = self.ar_det_pattern.text()
        r["reply"] = self.ar_det_reply.text()
        r["delay_ms"] = self.ar_det_delay.value()
        r["rate_limit_ms"] = self.ar_det_rate.value()
        # 校验并给出内联提示
        ok, err = self._ar_rule_valid(r)
        self.ar_error.setText("" if ok else err)
        item = self.ar_list.item(row)
        if ok:
            mark = "\u2713" if r["enabled"] else "\u2717"
            item.setForeground(self.ar_list.palette().text())
            item.setToolTip("")
        else:
            mark = "\u26a0"
            item.setForeground(QColor(tokens()["err"]))
            item.setToolTip(err)
        item.setText(f"{mark} [{r['match']}] {r['pattern']} \u2192 {r['reply']}")
        self._ar_apply()

    def _ar_apply(self):
        self.config.set("autoreply_rules", self._ar_data)
        if not self.ar_enabled.isChecked():
            self.autoreply.set_rules([])
            return
        # 仅合法规则进入引擎；非法规则保留在编辑区但不生效
        valid = []
        for r in self._ar_data:
            ok, _err = self._ar_rule_valid(r)
            if ok:
                valid.append(ReplyRule.from_dict(r))
        self.autoreply.set_rules(valid)

    def _ar_add(self):
        self._ar_data.append(
            {
                "enabled": True,
                "match": "contains",
                "reply_mode": "ascii",
                "pattern": "",
                "reply": "",
                "delay_ms": 0,
                "rate_limit_ms": 0,
            }
        )
        self._ar_refresh_list()
        self.ar_list.setCurrentRow(len(self._ar_data) - 1)
        self._ar_apply()

    def _ar_del(self):
        row = self.ar_list.currentRow()
        if row >= 0 and row < len(self._ar_data):
            del self._ar_data[row]
            self._ar_refresh_list()
            self._ar_apply()

    def _ar_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("import_rules"), "", "JSON (*.json)"
        )
        if path:
            import json

            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, tr("error"), tr("ar_import_failed").format(e))
                return
            if not isinstance(data, list):
                QMessageBox.warning(self, tr("error"), tr("ar_import_failed").format("not a list"))
                return
            self._ar_data = [dict(r) for r in data if isinstance(r, dict)]
            invalid = sum(1 for r in self._ar_data if not self._ar_rule_valid(r)[0])
            self._ar_refresh_list()
            self._ar_apply()
            if invalid:
                QMessageBox.warning(
                    self, tr("notice"), tr("ar_import_invalid").format(invalid)
                )

    def _ar_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export_rules"), "", "JSON (*.json)"
        )
        if path:
            import json

            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._ar_data, f, ensure_ascii=False, indent=2)

    # ================= Modbus 报文构造器 =================

    def _modbus_tab(self):
        """Modbus 报文构造器：选择功能码/地址/值 → 构造帧 → 填充到发送区。"""
        from ..plugins.modbus_tool.frame import (
            build_rtu_request,
            build_tcp_request,
            build_pdu_for_fc,
        )

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        # --- 功能码 ---
        FUNC_CODES = [
            ("0x01", tr("mb_read_coils"), 0x01),
            ("0x02", tr("mb_read_discrete"), 0x02),
            ("0x03", tr("mb_read_holding"), 0x03),
            ("0x04", tr("mb_read_input"), 0x04),
            ("0x05", tr("mb_write_single_coil"), 0x05),
            ("0x06", tr("mb_write_holding"), 0x06),
            ("0x0F", tr("mb_write_coils"), 0x0F),
            ("0x10", tr("mb_write_multi_holding"), 0x10),
        ]

        # Slave ID + Format
        sid_row = QHBoxLayout()
        sid_row.setSpacing(4)
        sid_lbl = QLabel(tr("mb_slave_id"))
        sid_lbl.setObjectName("dim")
        self.mb_sid = QSpinBox()
        self.mb_sid.setRange(1, 247)
        self.mb_sid.setValue(1)
        self.mb_sid.setMaximumWidth(70)
        sid_row.addWidget(sid_lbl)
        sid_row.addWidget(self.mb_sid)
        sid_row.addStretch()
        mb_fmt_lbl = QLabel(tr("mb_format"))
        mb_fmt_lbl.setObjectName("dim")
        self.mb_fmt = QComboBox()
        self.mb_fmt.addItem("RTU", "rtu")
        self.mb_fmt.addItem("TCP", "tcp")
        self.mb_fmt.setMinimumWidth(70)
        sid_row.addWidget(mb_fmt_lbl)
        sid_row.addWidget(self.mb_fmt)
        layout.addLayout(sid_row)

        # 功能码
        fc_row = QHBoxLayout()
        fc_row.setSpacing(4)
        fc_lbl = QLabel(tr("function"))
        fc_lbl.setObjectName("dim")
        self.mb_fc = QComboBox()
        for hex_str, name, code in FUNC_CODES:
            self.mb_fc.addItem(f"{hex_str} {name}", code)
        fc_row.addWidget(fc_lbl)
        fc_row.addWidget(self.mb_fc, 1)
        layout.addLayout(fc_row)

        # 地址（支持十进制和 0x 十六进制）
        addr_row = QHBoxLayout()
        addr_row.setSpacing(4)
        addr_lbl = QLabel(tr("address"))
        addr_lbl.setObjectName("dim")
        self.mb_addr = QLineEdit("0")
        self.mb_addr.setMaximumWidth(100)
        self.mb_addr.setPlaceholderText(tr("mb_addr_hint"))
        addr_row.addWidget(addr_lbl)
        addr_row.addWidget(self.mb_addr)
        addr_row.addStretch()
        layout.addLayout(addr_row)

        # 数量（读操作：0x01-0x04）
        qty_wrap = QWidget()
        qty_row = QHBoxLayout(qty_wrap)
        qty_row.setContentsMargins(0, 0, 0, 0)
        qty_row.setSpacing(4)
        qty_lbl = QLabel(tr("mb_reg_count"))
        qty_lbl.setObjectName("dim")
        self.mb_qty = QSpinBox()
        self.mb_qty.setRange(1, 2000)
        self.mb_qty.setValue(1)
        self.mb_qty.setMaximumWidth(100)
        qty_row.addWidget(qty_lbl)
        qty_row.addWidget(self.mb_qty)
        qty_row.addStretch()
        layout.addWidget(qty_wrap)
        self._mb_qty_wrap = qty_wrap

        # 写入值（写单个：0x05/0x06）
        val_wrap = QWidget()
        val_row = QHBoxLayout(val_wrap)
        val_row.setContentsMargins(0, 0, 0, 0)
        val_row.setSpacing(4)
        val_lbl = QLabel(tr("mb_set_value"))
        val_lbl.setObjectName("dim")
        self.mb_val = QSpinBox()
        self.mb_val.setRange(0, 65535)
        self.mb_val.setMaximumWidth(100)
        val_row.addWidget(val_lbl)
        val_row.addWidget(self.mb_val)
        val_row.addStretch()
        layout.addWidget(val_wrap)
        self._mb_val_wrap = val_wrap

        # 线圈 ON（0x05 专用）
        coil_wrap = QWidget()
        coil_row = QHBoxLayout(coil_wrap)
        coil_row.setContentsMargins(0, 0, 0, 0)
        coil_row.setSpacing(4)
        self.mb_coil_on = QCheckBox(tr("mb_write_coils"))
        coil_row.addWidget(self.mb_coil_on)
        coil_row.addStretch()
        layout.addWidget(coil_wrap)
        self._mb_coil_wrap = coil_wrap

        # 批量写入值（0x0F/0x10）
        multi_wrap = QWidget()
        multi_row = QVBoxLayout(multi_wrap)
        multi_row.setContentsMargins(0, 0, 0, 0)
        multi_row.setSpacing(4)
        multi_lbl = QLabel(tr("mb_write_values"))
        multi_lbl.setObjectName("dim")
        self.mb_multi_vals = QLineEdit()
        self.mb_multi_vals.setPlaceholderText(tr("mb_multi_hint"))
        multi_row.addWidget(multi_lbl)
        multi_row.addWidget(self.mb_multi_vals)
        layout.addWidget(multi_wrap)
        self._mb_multi_wrap = multi_wrap

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.mb_build = QPushButton(tr("mb_build_frame"))
        self.mb_build.setObjectName("accent")
        self.mb_fill = QPushButton(tr("mb_fill_tx"))
        self.mb_fill.setObjectName("ghost")
        btn_row.addWidget(self.mb_build, 1)
        btn_row.addWidget(self.mb_fill, 1)
        layout.addLayout(btn_row)

        # 预览
        lbl = QLabel(tr("mb_frame_preview"))
        lbl.setObjectName("dim")
        layout.addWidget(lbl)
        self.mb_preview = QLineEdit()
        self.mb_preview.setReadOnly(True)
        self.mb_preview.setPlaceholderText("01 03 00 00 00 01 84 0A")
        layout.addWidget(self.mb_preview)

        layout.addStretch()

        # 信号
        self.mb_fc.currentIndexChanged.connect(self._mb_on_fc_change)
        self.mb_build.clicked.connect(self._mb_do_build)
        self.mb_fill.clicked.connect(self._mb_do_fill)
        self._mb_on_fc_change()
        return w

    def _mb_on_fc_change(self):
        """根据功能码切换显示字段。"""
        fc = self.mb_fc.currentData()
        self._mb_qty_wrap.setVisible(fc in (0x01, 0x02, 0x03, 0x04))
        self._mb_val_wrap.setVisible(fc in (0x05, 0x06))
        self._mb_coil_wrap.setVisible(fc == 0x05)
        self._mb_multi_wrap.setVisible(fc in (0x0F, 0x10))

    def _mb_do_build(self):
        """构造 Modbus 报文并显示预览。"""
        try:
            sid = self.mb_sid.value()
            fc = self.mb_fc.currentData()
            addr = parse_int(self.mb_addr.text())
            fmt = self.mb_fmt.currentData()

            pdu = build_pdu_for_fc(
                fc,
                addr,
                quantity=self.mb_qty.value(),
                value=self.mb_val.value(),
                coil_on=self.mb_coil_on.isChecked(),
                multi_values=self._mb_parse_multi(),
            )

            # 包装帧头
            if fmt == "tcp":
                frame = build_tcp_request(sid, fc, pdu)
            else:
                frame = build_rtu_request(sid, fc, pdu)

            self.mb_preview.setText(frame.hex(" ").upper())
        except Exception as e:
            self.mb_preview.setText(f"ERR: {e}")

    def _mb_do_fill(self):
        """将预览报文填充到发送区。"""
        text = self.mb_preview.text().strip()
        if not text or text.startswith("ERR"):
            return
        if self.main_window:
            self.main_window.fill_send_text(text)

    def _mb_parse_multi(self) -> list:
        """解析批量值输入为整数列表。"""
        text = self.mb_multi_vals.text().strip()
        if not text:
            return []
        text = text.replace(",", " ")
        vals = []
        for part in text.split():
            part = part.strip()
            if not part:
                continue
            if part.lower().startswith("0x"):
                vals.append(int(part, 16))
            else:
                vals.append(int(part))
        return vals
