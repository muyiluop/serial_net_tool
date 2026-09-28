"""Modbus 工具完整面板（由框架包装到独立 QDialog 中显示）。

布局策略：核心配置（会话）置顶 + Tab 子配置（寄存器/实时数据/帧日志），
整体包裹在 QScrollArea 中，窗口高度不足时滚动而非挤压。
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QComboBox,
    QSpinBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QGroupBox,
    QPlainTextEdit,
    QHeaderView,
    QTabWidget,
    QScrollArea,
    QMessageBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QDateTime
from PySide6.QtGui import QFontMetrics

import struct

from ...core.i18n import tr
from ...core.utils import parse_int
from .register_map import RegisterMap, REG_TYPE_NAMES
from .engine import ModbusEngine
from .frame import (
    parse_rtu_frame,
    parse_tcp_frame,
    parse_read_response,
    tcp_frame_length,
    format_exception,
)


def _describe_frame(frame: dict) -> tuple:
    """把解析后的帧整理为表格行：(unit, fc, addr, qty, values, exception)。"""
    unit = frame.get("slave_id", frame.get("unit_id", ""))
    fc = frame.get("func_code", 0)
    data = frame.get("data", b"") or b""
    if frame.get("is_exception"):
        return unit, f"0x{fc:02X}", "", "", "", format_exception(frame.get("exc_code", 0))
    addr = qty = ""
    values = ""
    try:
        if fc in (0x01, 0x02, 0x03, 0x04):
            if len(data) == 4:
                a, q = struct.unpack(">HH", data)
                addr, qty = a, q
            elif data:
                parsed = parse_read_response(data, fc)
                qty = len(parsed)
                values = ", ".join("1" if v else "0" for v in parsed) if fc in (0x01, 0x02) else ", ".join(map(str, parsed))
        elif fc in (0x05, 0x06):
            a, v = struct.unpack(">HH", data[:4])
            addr = a
            values = ("ON" if v == 0xFF00 else "OFF") if fc == 0x05 else str(v)
        elif fc in (0x0F, 0x10):
            if len(data) >= 6:
                a, q = struct.unpack(">HH", data[:4])
                addr, qty = a, q
                bc = data[4]
                payload = data[5:5 + bc]
                if fc == 0x10:
                    regs = [struct.unpack(">H", payload[i:i + 2])[0]
                            for i in range(0, len(payload) - 1, 2)]
                    values = ", ".join(map(str, regs))
                else:
                    bits = []
                    for i in range(q):
                        bits.append("1" if payload[i // 8] & (1 << (i % 8)) else "0")
                    values = ", ".join(bits)
            elif len(data) == 4:
                a, q = struct.unpack(">HH", data)
                addr, qty = a, q
        else:
            values = data.hex(" ").upper()
    except Exception as e:
        values = f"parse error: {e}"
    return unit, f"0x{fc:02X}", addr, qty, values, ""


def _label(text: str) -> QLabel:
    """构造不会被布局截断的标签。"""
    lab = QLabel(text)
    lab.setObjectName("dim")
    fm = QFontMetrics(lab.font())
    lab.setMinimumWidth(fm.horizontalAdvance(text) + 8)
    lab.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    return lab


class ModbusToolWidget(QWidget):
    """Modbus 工具完整面板。

    由 MainWindow._launch_extension() 包装到非模态 QDialog 中显示。
    通过 main_window.get_active_sessions() 复用已有串口/TCP 连接。
    """

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.reg_map = RegisterMap()
        self.engine = ModbusEngine(self.reg_map)
        self._shutdown_done = False
        self._build()
        # 延迟刷新会话列表
        QTimer.singleShot(300, self._refresh_sessions)

    def shutdown(self):
        """窗口关闭/销毁时释放资源：解绑通道并停止轮询（幂等）。"""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            self.engine.detach()
        except Exception:
            pass

    # ================= 布局构建 =================

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 滚动区域包裹全部内容 ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setMinimumWidth(520)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(8)

        # ---- 核心配置：会话 ----
        cl.addWidget(self._build_session_group())

        # ---- Tab 子配置 ----
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_reg_tab(), tr("mb_register_config"))
        self.tabs.addTab(self._build_data_tab(), tr("mb_live_data"))
        self.tabs.addTab(self._build_parse_tab(), tr("mb_parse"))
        self.tabs.addTab(self._build_log_tab(), tr("mb_frame_log"))
        self.tabs.setMinimumHeight(320)
        cl.addWidget(self.tabs, 1)

        # ---- 状态 ----
        self.status_lbl = QLabel(tr("disconnected"))
        self.status_lbl.setObjectName("dim")
        cl.addWidget(self.status_lbl)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # ---- 信号 ----
        self.refresh_btn.clicked.connect(self._refresh_sessions)
        self.start_btn.clicked.connect(self._toggle_engine)
        self.mode_cb.currentIndexChanged.connect(self._on_mode_change)
        self.add_btn.clicked.connect(self._add_register)
        self.del_btn.clicked.connect(self._del_register)
        self.set_val_btn.clicked.connect(self._set_value)
        self.cfg_table.itemChanged.connect(self._on_cfg_changed)

        self.engine.status_message.connect(self._on_status)
        self.engine.error_occurred.connect(self._on_error)
        self.engine.values_updated.connect(self._on_values_updated)
        self.engine.frame_log.connect(self._on_frame_log)

    def _build_session_group(self) -> QGroupBox:
        """核心配置区：会话/模式/启停。"""
        grp = QGroupBox(tr("mb_session"))
        grid = QGridLayout(grp)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        # Row 0: 会话选择 + 刷新
        self.session_cb = QComboBox()
        self.session_cb.setMinimumWidth(200)
        self.refresh_btn = QPushButton(tr("refresh"))
        self.refresh_btn.setObjectName("ghost")
        grid.addWidget(_label(tr("mb_link_session")), 0, 0, Qt.AlignRight)
        grid.addWidget(self.session_cb, 0, 1)
        grid.addWidget(self.refresh_btn, 0, 2)

        # Row 1: 模式 + 从站ID
        self.mode_cb = QComboBox()
        self.mode_cb.addItem(tr("mb_master"), "master")
        self.mode_cb.addItem(tr("mb_slave"), "slave")
        self.mode_cb.setMinimumWidth(100)

        self.slave_spin = QSpinBox()
        self.slave_spin.setRange(1, 247)
        self.slave_spin.setValue(1)

        self.format_cb = QComboBox()
        self.format_cb.addItem("RTU", "rtu")
        self.format_cb.addItem("TCP", "tcp")

        grid.addWidget(_label(tr("mb_mode")), 1, 0, Qt.AlignRight)
        grid.addWidget(self.mode_cb, 1, 1)
        grid.addWidget(_label(tr("mb_slave_id")), 1, 2, Qt.AlignRight)
        grid.addWidget(self.slave_spin, 1, 3)

        # Row 2: 轮询间隔 + 格式
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(100, 60000)
        self.poll_spin.setValue(1000)
        self.poll_spin.setSuffix(" ms")

        grid.addWidget(_label(tr("mb_poll_interval")), 2, 0, Qt.AlignRight)
        grid.addWidget(self.poll_spin, 2, 1)
        grid.addWidget(_label(tr("mb_format")), 2, 2, Qt.AlignRight)
        grid.addWidget(self.format_cb, 2, 3)

        # Row 3: 启停按钮全宽
        self.start_btn = QPushButton(tr("mb_start"))
        self.start_btn.setObjectName("accent")
        grid.addWidget(self.start_btn, 3, 0, 1, 4)

        # 列拉伸：第 1 列（控件列）可拉伸
        grid.setColumnStretch(1, 1)
        return grp

    def _build_reg_tab(self) -> QWidget:
        """寄存器配置 Tab。"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.add_btn = QPushButton(tr("add"))
        self.add_btn.setObjectName("secondary")
        self.del_btn = QPushButton(tr("delete_selected"))
        self.del_btn.setObjectName("danger")
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.del_btn)
        toolbar.addStretch()
        self.reg_count_lbl = QLabel("0")
        self.reg_count_lbl.setObjectName("dim")
        toolbar.addWidget(_label(tr("mb_reg_count")))
        toolbar.addWidget(self.reg_count_lbl)
        layout.addLayout(toolbar)

        # 配置表
        self.cfg_table = QTableWidget(0, 6)
        self.cfg_table.setHorizontalHeaderLabels(
            [
                tr("name"),
                tr("address"),
                tr("function"),
                tr("mb_reg_type"),
                tr("value"),
                tr("description"),
            ]
        )
        header = self.cfg_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.cfg_table.setMinimumHeight(120)
        self.cfg_table.setMaximumHeight(400)
        self.cfg_table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.cfg_table, 1)

        # 设值行
        val_row = QHBoxLayout()
        val_row.setSpacing(6)
        val_row.addWidget(_label(tr("mb_set_value")))
        self.val_addr = QSpinBox()
        self.val_addr.setRange(0, 65535)
        self.val_spin = QSpinBox()
        self.val_spin.setRange(0, 65535)
        self.set_val_btn = QPushButton(tr("mb_set_value"))
        self.set_val_btn.setObjectName("secondary")
        val_row.addWidget(self.val_addr)
        val_row.addWidget(self.val_spin)
        val_row.addWidget(self.set_val_btn)
        val_row.addStretch()
        layout.addLayout(val_row)

        return w

    def _build_data_tab(self) -> QWidget:
        """实时数据 Tab。"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)
        self.data_table = QTableWidget(0, 4)
        self.data_table.setHorizontalHeaderLabels(
            [tr("name"), tr("address"), tr("mb_reg_type"), tr("value")]
        )
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.data_table.setObjectName("mono")
        self.data_table.verticalHeader().setDefaultSectionSize(26)
        self.data_table.setMinimumHeight(200)
        layout.addWidget(self.data_table)
        return w

    def _build_parse_tab(self) -> QWidget:
        """帧解析 Tab：粘贴 Hex 帧 → 解析为字段表格。"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(_label(tr("mb_format")))
        self.parse_fmt = QComboBox()
        self.parse_fmt.addItem(tr("mb_auto"), "auto")
        self.parse_fmt.addItem("RTU", "rtu")
        self.parse_fmt.addItem("TCP", "tcp")
        self.parse_fmt.setMinimumWidth(90)
        top.addWidget(self.parse_fmt)
        self.parse_btn = QPushButton(tr("mb_parse_btn"))
        self.parse_btn.setObjectName("secondary")
        top.addWidget(self.parse_btn)
        top.addStretch()
        layout.addLayout(top)

        self.parse_in = QPlainTextEdit()
        self.parse_in.setObjectName("mono")
        self.parse_in.setPlaceholderText("01 03 00 00 00 01 84 0A")
        self.parse_in.setMaximumHeight(70)
        layout.addWidget(self.parse_in)

        self.parse_table = QTableWidget(0, 6)
        self.parse_table.setHorizontalHeaderLabels([
            tr("mb_col_unit"), tr("mb_col_fc"), tr("mb_col_addr"),
            tr("mb_col_qty"), tr("mb_col_values"), tr("mb_col_exception"),
        ])
        self.parse_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.parse_table.setObjectName("mono")
        self.parse_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.parse_table.verticalHeader().setDefaultSectionSize(26)
        layout.addWidget(self.parse_table, 1)

        self.parse_btn.clicked.connect(self._on_parse)
        return w

    def _append_parse_row(self, row: tuple):
        r = self.parse_table.rowCount()
        self.parse_table.insertRow(r)
        for c, val in enumerate(row):
            self.parse_table.setItem(r, c, QTableWidgetItem(str(val)))

    def _on_parse(self):
        self.parse_table.setRowCount(0)
        text = self.parse_in.toPlainText().strip()
        if not text:
            return
        try:
            data = bytes.fromhex("".join(text.split()))
        except Exception as e:
            self._append_parse_row(("", "", "", "", "", tr("mb_parse_bad_hex").format(e)))
            return
        fmt = self.parse_fmt.currentData()
        frame = None
        if fmt == "rtu":
            frame = parse_rtu_frame(data)
        elif fmt == "tcp":
            frame = parse_tcp_frame(data)
        else:
            # 自动：MBAP 协议标识为 0 且长度字段自洽则按 TCP，否则按 RTU
            looks_tcp = len(data) >= 8 and data[2:4] == b"\x00\x00"
            if looks_tcp and tcp_frame_length(data) == len(data):
                frame = parse_tcp_frame(data)
            else:
                frame = parse_rtu_frame(data)
                if frame is None and looks_tcp:
                    frame = parse_tcp_frame(data)
        if frame is None:
            self._append_parse_row(("", "", "", "", "", tr("mb_parse_fail")))
            return
        self._append_parse_row(_describe_frame(frame))

    def _build_log_tab(self) -> QWidget:
        """帧日志 Tab。"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)
        self.frame_log = QPlainTextEdit()
        self.frame_log.setObjectName("mono")
        self.frame_log.setReadOnly(True)
        self.frame_log.setMinimumHeight(200)
        layout.addWidget(self.frame_log)
        return w

    # ================= 会话管理 =================

    def _refresh_sessions(self):
        """刷新可用会话列表。"""
        self.session_cb.clear()
        if not self.main_window:
            return
        try:
            sessions = self.main_window.get_active_sessions()
        except Exception:
            sessions = []
        for sid, name, kind, channel in sessions:
            label = f"{name} [{tr(kind)}]"
            self.session_cb.addItem(label, (sid, channel))

    def _toggle_engine(self):
        """启动/停止引擎。"""
        if self.engine.is_running:
            self.engine.stop()
            self.engine.detach()
            self.start_btn.setText(tr("mb_start"))
        else:
            idx = self.session_cb.currentIndex()
            if idx < 0:
                QMessageBox.warning(self, tr("error"), tr("mb_no_session"))
                return
            _, channel = self.session_cb.itemData(idx)
            if not channel:
                return
            self.engine.mode = self.mode_cb.currentData()
            self.engine.frame_format = self.format_cb.currentData()
            self.engine.slave_id = self.slave_spin.value()
            self.engine.poll_interval_ms = self.poll_spin.value()
            self.engine.attach(channel)
            self.engine.start()
            self.start_btn.setText(tr("mb_stop"))

    def _on_mode_change(self):
        mode = self.mode_cb.currentData()
        self.poll_spin.setEnabled(mode == "master")

    # ================= 寄存器配置 =================

    def _add_register(self):
        row = self.cfg_table.rowCount()
        self.cfg_table.blockSignals(True)
        self.cfg_table.insertRow(row)
        self.cfg_table.setItem(row, 0, QTableWidgetItem(f"Reg{row}"))
        self.cfg_table.setItem(row, 1, QTableWidgetItem(str(row * 2)))
        self.cfg_table.setCellWidget(row, 2, self._make_fc_combo(0x03))
        self.cfg_table.setCellWidget(row, 3, self._make_type_combo("uint16"))
        val_item = QTableWidgetItem("0")
        val_item.setFlags(val_item.flags() & ~Qt.ItemIsEditable)  # 值列只读展示
        self.cfg_table.setItem(row, 4, val_item)
        self.cfg_table.setItem(row, 5, QTableWidgetItem(""))
        self.cfg_table.blockSignals(False)
        self._sync_to_map()
        self._update_reg_count()

    def _make_type_combo(self, reg_type: str) -> QComboBox:
        """寄存器类型下拉单元格。"""
        cb = QComboBox()
        cb.addItems(REG_TYPE_NAMES)
        idx = cb.findText(reg_type)
        cb.setCurrentIndex(idx if idx >= 0 else 0)
        cb.currentTextChanged.connect(self._on_cfg_changed)
        return cb

    def _make_fc_combo(self, func_code: int) -> QComboBox:
        """读取功能码下拉单元格（0x01/0x02/0x03/0x04）。"""
        cb = QComboBox()
        for code, key in ((0x01, "mb_read_coils"), (0x02, "mb_read_discrete"),
                          (0x03, "mb_read_holding"), (0x04, "mb_read_input")):
            cb.addItem(f"0x{code:02X}", code)
        idx = cb.findData(int(func_code))
        cb.setCurrentIndex(idx if idx >= 0 else 2)
        cb.currentIndexChanged.connect(self._on_cfg_changed)
        return cb

    def _row_reg_type(self, row: int) -> str:
        """读取某行的寄存器类型（优先取下拉单元格）。"""
        cb = self.cfg_table.cellWidget(row, 3)
        if isinstance(cb, QComboBox):
            return cb.currentText()
        item = self.cfg_table.item(row, 3)
        text = item.text() if item else "uint16"
        return text if text in REG_TYPE_NAMES else "uint16"

    def _row_func_code(self, row: int) -> int:
        """读取某行的功能码。"""
        cb = self.cfg_table.cellWidget(row, 2)
        if isinstance(cb, QComboBox):
            return int(cb.currentData())
        return 0x03

    def _del_register(self):
        rows = sorted(
            set(idx.row() for idx in self.cfg_table.selectedIndexes()), reverse=True
        )
        if not rows:
            return
        self.cfg_table.blockSignals(True)
        for r in rows:
            self.cfg_table.removeRow(r)
        self.cfg_table.blockSignals(False)
        self._sync_to_map()
        self._update_reg_count()

    def _sync_to_map(self):
        """从配置表同步到 RegisterMap。"""
        configs = []
        for r in range(self.cfg_table.rowCount()):
            name = self.cfg_table.item(r, 0)
            addr = self.cfg_table.item(r, 1)
            desc = self.cfg_table.item(r, 5)
            try:
                address = parse_int(addr.text()) if addr else 0
            except ValueError:
                address = 0
            configs.append(
                {
                    "name": name.text() if name else "",
                    "address": address,
                    "reg_type": self._row_reg_type(r),
                    "description": desc.text() if desc else "",
                    "func_code": self._row_func_code(r),
                }
            )
        self.reg_map.from_list(configs)

    def _on_cfg_changed(self):
        self._sync_to_map()
        self._update_reg_count()
        self.refresh_values()

    def _set_value(self):
        addr = self.val_addr.value()
        val = self.val_spin.value()
        self.reg_map.set_raw_value(addr, val)
        self.refresh_values()

    def _update_reg_count(self):
        self.reg_count_lbl.setText(str(self.cfg_table.rowCount()))

    # ================= 实时数据 =================

    def refresh_values(self):
        """刷新实时数据表。"""
        self.data_table.blockSignals(True)
        self.data_table.setRowCount(len(self.reg_map.configs))
        for i, cfg in enumerate(self.reg_map.configs):
            self.data_table.setItem(i, 0, QTableWidgetItem(cfg.name))
            self.data_table.setItem(i, 1, QTableWidgetItem(str(cfg.address)))
            self.data_table.setItem(i, 2, QTableWidgetItem(cfg.reg_type))
            if isinstance(cfg.value, float):
                val_str = f"{cfg.value:.4f}"
            else:
                val_str = str(cfg.value)
            self.data_table.setItem(i, 3, QTableWidgetItem(val_str))
        self.data_table.blockSignals(False)
        # 同步配置表中的值列
        for i, cfg in enumerate(self.reg_map.configs):
            if i < self.cfg_table.rowCount():
                val_item = self.cfg_table.item(i, 4)
                if val_item:
                    if isinstance(cfg.value, float):
                        val_item.setText(f"{cfg.value:.4f}")
                    else:
                        val_item.setText(str(cfg.value))

    def append_frame_log(self, direction: str, hex_str: str, note: str):
        ts = QDateTime.currentDateTime().toString("hh:mm:ss.zzz")
        tag = "\u2192" if direction == "tx" else "\u2190"
        line = f"[{ts}] {tag} {hex_str}"
        if note:
            line += f"  ({note})"
        self.frame_log.appendPlainText(line)

    # ================= 引擎回调 =================

    def _on_status(self, msg):
        self.status_lbl.setText(
            tr(msg) if msg in ("master_started", "slave_started", "stopped") else msg
        )
        self.status_lbl.setObjectName("stat")
        self._repolish(self.status_lbl)

    def _on_error(self, msg):
        self.status_lbl.setText(f"\u26a0 {msg}")
        self.status_lbl.setObjectName("badge_err")
        self._repolish(self.status_lbl)

    def _on_values_updated(self):
        self.refresh_values()

    def _on_frame_log(self, direction, hex_str, note):
        self.append_frame_log(direction, hex_str, note)

    @staticmethod
    def _repolish(w):
        w.style().unpolish(w)
        w.style().polish(w)
