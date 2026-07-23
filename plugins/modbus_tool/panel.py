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

from ...core.i18n import tr
from .register_map import RegisterMap
from .engine import ModbusEngine


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
        self._build()
        # 延迟刷新会话列表
        QTimer.singleShot(300, self._refresh_sessions)

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
        self.add_btn.setObjectName("accent")
        self.del_btn = QPushButton(tr("delete_selected"))
        self.del_btn.setObjectName("ghost")
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.del_btn)
        toolbar.addStretch()
        self.reg_count_lbl = QLabel("0")
        self.reg_count_lbl.setObjectName("dim")
        toolbar.addWidget(_label(tr("mb_reg_count")))
        toolbar.addWidget(self.reg_count_lbl)
        layout.addLayout(toolbar)

        # 配置表
        self.cfg_table = QTableWidget(0, 5)
        self.cfg_table.setHorizontalHeaderLabels(
            [
                tr("name"),
                tr("address"),
                tr("mb_reg_type"),
                tr("value"),
                tr("description"),
            ]
        )
        self.cfg_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cfg_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.cfg_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.cfg_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.cfg_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.cfg_table.setMinimumHeight(200)
        # self.cfg_table.setMinimumHeight(160)
        # self.cfg_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cfg_table.setMinimumHeight(120)
        self.cfg_table.setMaximumHeight(400)
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
        self.set_val_btn.setObjectName("ghost")
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
        self.data_table.setMinimumHeight(200)
        layout.addWidget(self.data_table)
        return w

    def _build_log_tab(self) -> QWidget:
        """帧日志 Tab。"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)
        self.frame_log = QPlainTextEdit()
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
        self.cfg_table.setItem(row, 2, QTableWidgetItem("uint16"))
        self.cfg_table.setItem(row, 3, QTableWidgetItem("0"))
        self.cfg_table.setItem(row, 4, QTableWidgetItem(""))
        self.cfg_table.blockSignals(False)
        self._sync_to_map()
        self._update_reg_count()

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
            rtype = self.cfg_table.item(r, 2)
            desc = self.cfg_table.item(r, 4)
            configs.append(
                {
                    "name": name.text() if name else "",
                    "address": int(addr.text())
                    if addr and addr.text().isdigit()
                    else 0,
                    "reg_type": rtype.text() if rtype else "uint16",
                    "description": desc.text() if desc else "",
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
                val_item = self.cfg_table.item(i, 3)
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
