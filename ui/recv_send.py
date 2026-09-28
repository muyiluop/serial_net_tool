"""收发工作区：通信日志(发送+接收)、发送编辑、定时发送、流量统计、日志导出。

布局与交互：
- 日志工具条：显示模式/时间戳/自动滚动/换行/上限/方向筛选/暂停 + 搜索/清空/导出。
- 通信日志：由 LogStore 统一存储，按方向着色，支持筛选与关键字高亮。
- 发送区：编辑框 + 紧凑工具条（模式/定时/间隔/发送）+ 可选文件分块发送。
"""
import os

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QLabel,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QFrame,
    QFileDialog,
    QMessageBox,
    QToolButton,
)
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QShortcut, QKeySequence

from ..core.channel import Channel
from ..core.utils import text_to_bytes, bytes_to_text
from ..core.autoreply import AutoReplyEngine
from ..core.config import Config
from ..core.log_store import LogStore
from ..core.theme import direction_colors, tokens
from ..core.i18n import tr
from .log_export_dialog import LogExportDialog

_DEFAULT_CHUNK_SIZE = 4096
_DEFAULT_CHUNK_DELAY_MS = 5
_DEFAULT_MAX_LINES = 5000


class RecvSendWidget(QWidget):
    def __init__(
        self,
        autoreply: AutoReplyEngine,
        config: Config,
        kind: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.autoreply = autoreply
        self.config = config
        self.kind = kind
        self.channel = None
        self._search_sels: list = []
        self._search_idx = -1
        self._peer_picker_active = False
        # 结构化日志（单一数据源）
        self.store = LogStore(int(config.get("log_max_lines", _DEFAULT_MAX_LINES)), self)
        self.store.appended.connect(self._on_appended)
        self._pending_since_pause = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        # 文件发送状态
        self._file_data: bytes | None = None
        self._file_offset = 0
        self._file_name = ""
        self._file_total = 0
        self._file_sending = False
        self._file_timer = QTimer(self)
        self._file_timer.timeout.connect(self._send_file_chunk)
        self._build()

    # ================= UI =================
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ---------- 日志工具条（两行，避免窄宽溢出） ----------
        bar1 = QHBoxLayout()
        bar1.setSpacing(8)
        bar1.addWidget(self._mk_label(tr("display")))
        self.rb_ascii = QRadioButton(tr("ascii"))
        self.rb_hex = QRadioButton(tr("hex"))
        self.rb_ascii.setChecked(True)
        self.bg = QButtonGroup(self)
        self.bg.addButton(self.rb_ascii)
        self.bg.addButton(self.rb_hex)
        self.bg.buttonClicked.connect(lambda _b: self._rerender())
        bar1.addWidget(self.rb_ascii)
        bar1.addWidget(self.rb_hex)
        bar1.addWidget(self._vline())

        self.ts_chk = QCheckBox(tr("timestamp"))
        self.ts_chk.setChecked(bool(self.config.get("rx_timestamp")))
        self.ts_chk.toggled.connect(lambda v: self.config.set("rx_timestamp", v))
        self.ts_chk.toggled.connect(lambda _v: self._rerender())
        bar1.addWidget(self.ts_chk)

        self.autoscroll_chk = QCheckBox(tr("auto_scroll"))
        self.autoscroll_chk.setChecked(True)
        bar1.addWidget(self.autoscroll_chk)

        self.wrap_chk = QCheckBox(tr("log_wrap"))
        self.wrap_chk.setChecked(bool(self.config.get("log_wrap", True)))
        self.wrap_chk.toggled.connect(self._on_wrap_toggled)
        bar1.addWidget(self.wrap_chk)

        bar1.addWidget(self._mk_label(tr("log_max_lines")))
        self.max_lines = QSpinBox()
        self.max_lines.setRange(100, 200000)
        self.max_lines.setSingleStep(500)
        self.max_lines.setValue(int(self.config.get("log_max_lines", _DEFAULT_MAX_LINES)))
        self.max_lines.setFixedWidth(96)
        self.max_lines.valueChanged.connect(self._on_max_lines_changed)
        bar1.addWidget(self.max_lines)

        bar1.addWidget(self._mk_label(tr("log_filter")))
        self.filter_cb = QComboBox()
        self.filter_cb.addItem(tr("log_filter_all"), "both")
        self.filter_cb.addItem(tr("export_dir_tx"), "tx")
        self.filter_cb.addItem(tr("export_dir_rx"), "rx")
        idx = self.filter_cb.findData(self.config.get("log_filter_dir", "both"))
        self.filter_cb.setCurrentIndex(max(0, idx))
        self.filter_cb.currentIndexChanged.connect(self._on_filter_changed)
        bar1.addWidget(self.filter_cb)

        bar1.addStretch()
        self.clear_btn = self._mk_btn(tr("clear"), ghost=True)
        self.export_btn = self._mk_btn(tr("export_log"), ghost=True)
        bar1.addWidget(self.clear_btn)
        bar1.addWidget(self.export_btn)
        layout.addLayout(bar1)

        bar2 = QHBoxLayout()
        bar2.setSpacing(6)
        self.pause_btn = QToolButton()
        self.pause_btn.setObjectName("tool")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setText(tr("log_pause"))
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        bar2.addWidget(self.pause_btn)

        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText(tr("log_search"))
        self.search_in.setClearButtonEnabled(True)
        self.search_in.setMinimumWidth(120)
        self.search_in.textChanged.connect(self._apply_search)
        self.search_in.returnPressed.connect(self._search_next)
        bar2.addWidget(self.search_in, 1)

        self.search_prev_btn = self._mk_btn(tr("log_search_prev"), ghost=True)
        self.search_next_btn = self._mk_btn(tr("log_search_next"), ghost=True)
        self.search_prev_btn.clicked.connect(self._search_prev)
        self.search_next_btn.clicked.connect(self._search_next)
        bar2.addWidget(self.search_prev_btn)
        bar2.addWidget(self.search_next_btn)

        self.stat = QLabel("RX 0  ·  TX 0")
        self.stat.setObjectName("stat")
        bar2.addWidget(self.stat)
        layout.addLayout(bar2)

        # ---------- 通信日志 ----------
        self.recv = QTextEdit()
        self.recv.setObjectName("recv")
        self.recv.setReadOnly(True)
        self.recv.document().setMaximumBlockCount(self.store.max_lines)
        layout.addWidget(self.recv, 1)
        self._on_wrap_toggled(self.wrap_chk.isChecked())

        # ---------- 发送区 ----------
        send_card = QFrame()
        send_card.setObjectName("card")
        send_v = QVBoxLayout(send_card)
        send_v.setContentsMargins(10, 8, 10, 8)
        send_v.setSpacing(8)

        self.send = QPlainTextEdit()
        self.send.setObjectName("mono")
        self.send.setPlaceholderText(tr("send_placeholder"))
        self.send.setFixedHeight(84)
        send_v.addWidget(self.send, 1)

        sctrl = QHBoxLayout()
        sctrl.setSpacing(10)
        sctrl.addWidget(self._mk_label(tr("mode")))
        self.tx_ascii = QRadioButton(tr("ascii"))
        self.tx_hex = QRadioButton(tr("hex"))
        self.tx_ascii.setChecked(True)
        self.tbg = QButtonGroup(self)
        self.tbg.addButton(self.tx_ascii)
        self.tbg.addButton(self.tx_hex)
        sctrl.addWidget(self.tx_ascii)
        sctrl.addWidget(self.tx_hex)

        sctrl.addWidget(self._vline())
        self.periodic = QCheckBox(tr("periodic"))
        sctrl.addWidget(self.periodic)
        self.interval = QSpinBox()
        self.interval.setRange(100, 60000)
        self.interval.setValue(1000)
        self.interval.setSuffix(" ms")
        self.interval.setFixedWidth(96)
        sctrl.addWidget(self.interval)
        self.timer_btn = self._mk_btn(tr("start_timer"), ghost=True)
        sctrl.addWidget(self.timer_btn)

        # TCP 服务端：发送目标选择（全部 / 指定客户端）
        self.peer_lbl = self._mk_label(tr("send_target"))
        self.peer_cb = QComboBox()
        self.peer_cb.setMinimumWidth(130)
        self.peer_lbl.setVisible(False)
        self.peer_cb.setVisible(False)
        sctrl.addWidget(self.peer_lbl)
        sctrl.addWidget(self.peer_cb)

        sctrl.addStretch()
        self.file_btn = self._mk_btn(tr("select_file"), ghost=True)
        self.file_btn.setEnabled(False)
        sctrl.addWidget(self.file_btn)
        self.send_btn = self._mk_btn(tr("send"), accent=True)
        self.send_btn.setMinimumWidth(110)
        self.send_btn.setEnabled(False)
        sctrl.addWidget(self.send_btn)
        send_v.addLayout(sctrl)

        # ---------- 文件发送控制行（选文件后显示） ----------
        self.file_row = QFrame()
        self.file_row.setObjectName("card")
        fr_layout = QHBoxLayout(self.file_row)
        fr_layout.setContentsMargins(10, 6, 10, 6)
        fr_layout.setSpacing(8)

        self.file_info = QLabel("")
        self.file_info.setObjectName("dim")
        fr_layout.addWidget(self.file_info)
        fr_layout.addStretch()

        fr_layout.addWidget(self._mk_label(tr("chunk_size")))
        self.chunk_size = QSpinBox()
        self.chunk_size.setRange(1, 65536)
        self.chunk_size.setValue(_DEFAULT_CHUNK_SIZE)
        self.chunk_size.setSuffix(" B")
        self.chunk_size.setFixedWidth(100)
        fr_layout.addWidget(self.chunk_size)

        fr_layout.addWidget(self._mk_label(tr("chunk_interval")))
        self.chunk_delay = QSpinBox()
        self.chunk_delay.setRange(0, 60000)
        self.chunk_delay.setValue(_DEFAULT_CHUNK_DELAY_MS)
        self.chunk_delay.setSuffix(" ms")
        self.chunk_delay.setFixedWidth(90)
        fr_layout.addWidget(self.chunk_delay)

        self.file_send_btn = self._mk_btn(tr("start_file_send"), accent=True)
        self.file_send_btn.setVisible(False)
        fr_layout.addWidget(self.file_send_btn)

        self.file_cancel_btn = self._mk_btn(tr("cancel"), ghost=True)
        self.file_cancel_btn.setVisible(False)
        fr_layout.addWidget(self.file_cancel_btn)

        self.file_row.setVisible(False)
        send_v.addWidget(self.file_row)

        self.file_progress = QLabel("")
        self.file_progress.setObjectName("dim")
        self.file_progress.setVisible(False)
        send_v.addWidget(self.file_progress)
        layout.addWidget(send_card)

        # ---------- 信号 ----------
        self.clear_btn.clicked.connect(self._clear)
        self.export_btn.clicked.connect(self._export)
        self.send_btn.clicked.connect(self._do_send)
        self.timer_btn.clicked.connect(self._toggle_timer)
        self.file_btn.clicked.connect(self._pick_file)
        self.file_send_btn.clicked.connect(self._toggle_file_send)
        self.file_cancel_btn.clicked.connect(self._cancel_file)

        # ---------- 快捷键 ----------
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._do_send)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._do_send)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._clear)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search_in.setFocus())
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._export)

    def _mk_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("dim")
        return lab

    def _mk_btn(self, text: str, ghost: bool = False, accent: bool = False) -> QPushButton:
        b = QPushButton(text)
        if accent:
            b.setObjectName("accent")
        elif ghost:
            b.setObjectName("ghost")
        # 保证按钮文字完整显示：每字约 14px + padding 34px，最少 64px
        min_w = max(64, len(text) * 14 + 34)
        b.setMinimumWidth(min_w)
        return b

    def _vline(self) -> QFrame:
        line = QFrame()
        line.setObjectName("vline")
        line.setFixedWidth(1)
        return line

    # ================= 通道绑定 =================
    def bind(self, channel: Channel):
        self.channel = channel
        channel.received.connect(self._on_received)
        self.send_btn.setEnabled(True)
        self.file_btn.setEnabled(True)
        if self._file_data is not None:
            self.file_send_btn.setEnabled(True)
        # TCP 服务端：展示发送目标选择
        if hasattr(channel, "peers_changed"):
            channel.peers_changed.connect(self._on_peers_changed)
            self._peer_picker_active = True
            self.peer_lbl.setVisible(True)
            self.peer_cb.setVisible(True)
            if hasattr(channel, "peers"):
                self._on_peers_changed(channel.peers())

    def unbind(self):
        if self.channel:
            try:
                self.channel.received.disconnect(self._on_received)
            except Exception:
                pass
            if hasattr(self.channel, "peers_changed"):
                try:
                    self.channel.peers_changed.disconnect(self._on_peers_changed)
                except Exception:
                    pass
        self.channel = None
        self._peer_picker_active = False
        self.peer_lbl.setVisible(False)
        self.peer_cb.setVisible(False)
        # 停止定时发送，复位按钮与开关，避免断开后残留运行中状态
        self._timer.stop()
        self.timer_btn.setText(tr("start_timer"))
        self.periodic.setChecked(False)
        self.send_btn.setEnabled(False)
        self.file_btn.setEnabled(False)
        self.file_send_btn.setEnabled(False)
        self._stop_file_send()

    def _on_peers_changed(self, peers):
        """更新发送目标下拉（全部 + 各客户端）。"""
        current = self.peer_cb.currentData()
        self.peer_cb.clear()
        self.peer_cb.addItem(tr("send_target_all"), None)
        for p in peers:
            self.peer_cb.addItem(p, p)
        idx = self.peer_cb.findData(current)
        self.peer_cb.setCurrentIndex(idx if idx >= 0 else 0)

    def _send_data(self, data: bytes):
        """发送字节；若选定了具体客户端则定向发送。"""
        target = self.peer_cb.currentData() if self._peer_picker_active else None
        if target:
            try:
                self.channel.send(data, target=target)
                return
            except TypeError:
                pass  # 通道不支持定向发送，退回广播
        self.channel.send(data)

    def set_send_text(self, text: str):
        """外部填充发送区文本（如 Modbus 报文构造器）。"""
        self.send.setPlainText(text)

    def _mode(self):
        return "hex" if self.rb_hex.isChecked() else "ascii"

    def _tx_mode(self):
        return "hex" if self.tx_hex.isChecked() else "ascii"

    def _enc(self):
        return self.config.get("default_encoding", "utf-8")

    # ================= 日志渲染 =================
    def _record_line(self, rec) -> str:
        ts = ""
        if self.ts_chk.isChecked():
            ts = rec.ts.strftime("%H:%M:%S.%f")[:-3] + " "
        tag = tr("tx_tag") if rec.direction == "tx" else tr("rx_tag")
        prefix = ""
        if rec.peer:
            prefix += f" @{rec.peer}"
        if rec.topic:
            prefix += f" #{rec.topic}"
        return f"{ts}{tag}{prefix} {rec.text}"

    def _append_record(self, rec):
        send_color, recv_color = direction_colors()
        color = send_color if rec.direction == "tx" else recv_color
        self.recv.setTextColor(QColor(color))
        self.recv.append(self._record_line(rec))

    def _on_appended(self, rec):
        """LogStore 有新记录：按筛选条件决定是否渲染。"""
        if self.pause_btn.isChecked():
            self._pending_since_pause += 1
            self._update_stat()
            return
        if self._passes_filter(rec):
            self._append_record(rec)
            if self.autoscroll_chk.isChecked():
                self.recv.moveCursor(QTextCursor.End)
        self._update_stat()

    def _passes_filter(self, rec) -> bool:
        direction = self.filter_cb.currentData()
        return not direction or direction == "both" or rec.direction == direction

    def _rerender(self):
        """按当前筛选/时间戳设置重建日志视图。"""
        self.recv.clear()
        for rec in self.store.all():
            if self._passes_filter(rec):
                self._append_record(rec)
        self.recv.moveCursor(QTextCursor.End)
        self._apply_search()

    def _on_filter_changed(self, _idx):
        self.config.set("log_filter_dir", self.filter_cb.currentData())
        self._rerender()

    def _on_wrap_toggled(self, checked):
        self.config.set("log_wrap", bool(checked))
        self.recv.setLineWrapMode(
            QTextEdit.WidgetWidth if checked else QTextEdit.NoWrap
        )

    def _on_max_lines_changed(self, value):
        self.config.set("log_max_lines", int(value))
        self.store.set_max_lines(int(value))
        self.recv.document().setMaximumBlockCount(int(value))

    def _on_pause_toggled(self, paused):
        self.pause_btn.setText(tr("log_resume") if paused else tr("log_pause"))
        if not paused:
            self._pending_since_pause = 0
            self._rerender()
        else:
            self._update_stat()

    # ================= 搜索 =================
    def _apply_search(self):
        text = self.search_in.text()
        self._search_sels = []
        self._search_idx = -1
        if text:
            t = tokens()
            hl = QColor(t["accent"])
            hl.setAlpha(70)
            fmt = QTextCharFormat()
            fmt.setBackground(hl)
            doc = self.recv.document()
            cursor = QTextCursor(doc)
            while True:
                cursor = doc.find(text, cursor)
                if cursor.isNull():
                    break
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                self._search_sels.append(sel)
        self.recv.setExtraSelections(self._search_sels)

    def _jump_to_match(self, index: int):
        if not self._search_sels:
            return
        self._search_idx = index % len(self._search_sels)
        cursor = self._search_sels[self._search_idx].cursor
        self.recv.setTextCursor(cursor)
        self.recv.ensureCursorVisible()

    def _search_next(self):
        self._jump_to_match(self._search_idx + 1)

    def _search_prev(self):
        self._jump_to_match(self._search_idx - 1)

    # ================= 日志写入 =================
    def _log(self, direction: str, text: str, raw: bytes = b"", meta: dict | None = None):
        """向通信日志写入一条；direction 为 'tx'(发送) 或 'rx'(接收)。"""
        meta = meta or {}
        self.store.log(
            direction,
            text,
            raw=raw,
            peer=str(meta.get("peer", "") or ""),
            topic=str(meta.get("topic", "") or ""),
        )

    def _on_received(self, data: bytes, meta: dict):
        text = bytes_to_text(data, self._mode(), self._enc())
        self._log("rx", text, raw=data, meta=meta)
        # 自动回复
        for reply, delay in self.autoreply.match(data):
            if delay and delay > 0:
                QTimer.singleShot(delay, lambda r=reply: self._auto_send(r))
            else:
                self._auto_send(reply)

    def _auto_send(self, data: bytes):
        if self.channel:
            self.channel.send(data)
            self._log("tx", bytes_to_text(data, self._tx_mode(), self._enc()), raw=data)

    def _do_send(self):
        if not self.channel:
            return
        try:
            data = text_to_bytes(self.send.toPlainText(), self._tx_mode(), self._enc())
        except Exception as e:
            QMessageBox.warning(self, tr("error"), tr("invalid_send_content").format(e))
            return
        if not data:
            return
        self._send_data(data)
        self._log("tx", bytes_to_text(data, self._tx_mode(), self._enc()), raw=data)

    def _on_timer(self):
        if self.periodic.isChecked() and self.channel:
            self._do_send()

    def _toggle_timer(self):
        if self._timer.isActive():
            self._timer.stop()
            self.timer_btn.setText(tr("start_timer"))
        else:
            if not self.channel:
                return
            self._timer.start(self.interval.value())
            self.timer_btn.setText(tr("stop_timer"))

    # ================= 文件发送 =================
    def _pick_file(self):
        """选择文件，加载到内存但不自动发送。"""
        if self._file_sending:
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("select_file"), "", "All Files (*.*)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                self._file_data = f.read()
        except Exception as e:
            QMessageBox.warning(self, tr("error"), tr("file_read_error").format(e))
            return

        self._file_name = os.path.basename(path)
        self._file_total = len(self._file_data)
        self._file_offset = 0
        self.file_row.setVisible(True)
        self.file_info.setText(
            tr("file_selected_info").format(self._file_name, self._file_total)
        )
        self.file_progress.setVisible(False)
        self.file_send_btn.setVisible(True)
        self.file_send_btn.setText(tr("start_file_send"))
        self.file_send_btn.setEnabled(bool(self.channel))
        self.file_cancel_btn.setVisible(True)
        self.file_btn.setText(tr("change_file"))

    def _cancel_file(self):
        """取消已选择的文件。"""
        self._stop_file_send()
        self._file_data = None
        self._file_name = ""
        self._file_total = 0
        self.file_row.setVisible(False)
        self.file_progress.setVisible(False)
        self.file_btn.setText(tr("select_file"))

    def _toggle_file_send(self):
        """切换文件发送/停止。"""
        if self._file_sending:
            self._stop_file_send()
            self._log("tx", tr("file_send_stopped").format(self._file_name, self._file_offset, self._file_total))
        else:
            self._start_file_send()

    def _start_file_send(self):
        """开始分块发送文件。"""
        if self._file_data is None or not self.channel:
            return
        self._file_sending = True
        self._file_offset = 0
        self.file_send_btn.setText(tr("stop_file_send"))
        self.file_progress.setVisible(True)
        self.file_progress.setText(
            tr("file_sending").format(self._file_name, 0, self._file_total, 0)
        )
        self._log("tx", tr("file_send_start").format(self._file_name, self._file_total))
        delay = self.chunk_delay.value()
        self._file_timer.start(delay if delay > 0 else 1)

    def _send_file_chunk(self):
        if self._file_data is None or not self.channel or not self._file_sending:
            self._stop_file_send()
            return
        chunk_size = self.chunk_size.value()
        end = min(self._file_offset + chunk_size, self._file_total)
        chunk = self._file_data[self._file_offset:end]
        try:
            self.channel.send(chunk)
        except Exception as e:
            self._log("tx", tr("file_send_error").format(e))
            self._stop_file_send()
            return
        self.store.log("tx", tr("file_chunk_tag").format(len(chunk)), raw=chunk, tag="file")
        self._file_offset = end
        pct = int(self._file_offset / self._file_total * 100) if self._file_total else 100
        self.file_progress.setText(
            tr("file_sending").format(self._file_name, self._file_offset, self._file_total, pct)
        )
        if self._file_offset >= self._file_total:
            self._log("tx", tr("file_send_done").format(self._file_name))
            self._stop_file_send()
            self.file_send_btn.setText(tr("start_file_send"))
            self._file_offset = 0

    def _stop_file_send(self):
        self._file_sending = False
        self._file_timer.stop()
        if self._file_data is not None:
            self.file_send_btn.setText(tr("start_file_send"))
            self.file_send_btn.setEnabled(bool(self.channel))
        QTimer.singleShot(
            2000,
            lambda: self.file_progress.setVisible(False) if not self._file_sending else None,
        )

    # ================= 统计/清空/导出 =================
    def _update_stat(self):
        text = f"RX {self.store.rx_bytes}  ·  TX {self.store.tx_bytes}"
        if self.pause_btn.isChecked() and self._pending_since_pause:
            text += f"  ·  +{self._pending_since_pause}"
        self.stat.setText(text)

    def _clear(self):
        self.store.clear()
        self.recv.clear()
        self._pending_since_pause = 0
        self._search_sels = []
        self.recv.setExtraSelections([])
        self._update_stat()

    def _export(self):
        dlg = LogExportDialog(self.store, self)
        if dlg.exec() != LogExportDialog.Accepted:
            return
        suffix = dlg.suffix()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export_log"), f"log.{suffix}", f"*.{suffix}"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(dlg.build_text())
        except Exception as e:
            QMessageBox.warning(self, tr("error"), tr("export_failed").format(e))
