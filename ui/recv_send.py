"""收发工作区：通信日志(发送+接收)、发送编辑、定时发送、流量统计、日志导出。

布局与交互（重构版）：
- 顶部信息条：连接摘要 + RX/TX 统计 + 清空/导出。
- 通信日志：同时显示 [发送]/[接收]，按方向着色；支持“自动滚动”开关，便于回看历史。
- 发送区：编辑框 + 紧凑工具条（模式/定时/间隔/发送）。
"""
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
    QSpinBox,
    QFrame,
    QFileDialog,
    QMessageBox,
)
from PySide6.QtCore import QTimer, QDateTime, Qt
from PySide6.QtGui import QColor, QPalette, QTextCursor

from ..core.channel import Channel
from ..core.utils import text_to_bytes, bytes_to_text
from ..core.autoreply import AutoReplyEngine
from ..core.config import Config
from ..core.theme import direction_colors
from ..core.i18n import tr

_DEFAULT_CHUNK_SIZE = 4096
_DEFAULT_CHUNK_DELAY_MS = 5


class RecvSendWidget(QWidget):
    def __init__(self, autoreply: AutoReplyEngine, config: Config, parent=None):
        super().__init__(parent)
        self.autoreply = autoreply
        self.config = config
        self.channel = None
        self._rx = 0
        self._tx = 0
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
        layout.setSpacing(8)

        # ---------- 顶部：日志工具条 ----------
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self._mk_label(tr("display")))
        self.rb_ascii = QRadioButton(tr("ascii"))
        self.rb_hex = QRadioButton(tr("hex"))
        self.rb_ascii.setChecked(True)
        self.bg = QButtonGroup(self)
        self.bg.addButton(self.rb_ascii)
        self.bg.addButton(self.rb_hex)
        top.addWidget(self.rb_ascii)
        top.addWidget(self.rb_hex)

        self.ts_chk = QCheckBox(tr("timestamp"))
        self.ts_chk.setChecked(bool(self.config.get("rx_timestamp")))
        self.ts_chk.toggled.connect(lambda v: self.config.set("rx_timestamp", v))
        top.addWidget(self.ts_chk)

        self.autoscroll_chk = QCheckBox(tr("auto_scroll"))
        self.autoscroll_chk.setChecked(True)
        top.addWidget(self.autoscroll_chk)

        top.addStretch()
        self.stat = QLabel("RX 0  ·  TX 0")
        self.stat.setObjectName("stat")
        top.addWidget(self.stat)
        self.clear_btn = self._mk_btn(tr("clear"), ghost=True)
        self.export_btn = self._mk_btn(tr("export_log"), ghost=True)
        top.addWidget(self.clear_btn)
        top.addWidget(self.export_btn)
        layout.addLayout(top)

        # ---------- 通信日志 ----------
        self.recv = QTextEdit()
        self.recv.setObjectName("recv")
        self.recv.setReadOnly(True)
        layout.addWidget(self.recv, 1)

        # ---------- 发送区 ----------
        send_card = QFrame()
        send_card.setObjectName("card")
        send_v = QVBoxLayout(send_card)
        send_v.setContentsMargins(10, 8, 10, 8)
        send_v.setSpacing(8)

        self.send = QPlainTextEdit()
        self.send.setPlaceholderText(tr("send_placeholder"))
        self.send.setMaximumBlockCount(0)
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

        # 文件发送进度条（发送中显示）
        self.file_progress = QLabel("")
        self.file_progress.setObjectName("dim")
        self.file_progress.setVisible(False)
        send_v.addWidget(self.file_progress)
        layout.addWidget(send_card)

        # 让发送编辑框紧凑一些
        self.send.setFixedHeight(84)

        # ---------- 信号 ----------
        self.clear_btn.clicked.connect(self.recv.clear)
        self.export_btn.clicked.connect(self._export)
        self.send_btn.clicked.connect(self._do_send)
        self.timer_btn.clicked.connect(self._toggle_timer)
        self.file_btn.clicked.connect(self._pick_file)
        self.file_send_btn.clicked.connect(self._toggle_file_send)
        self.file_cancel_btn.clicked.connect(self._cancel_file)

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
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet("color: #808080;")
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

    def unbind(self):
        if self.channel:
            try:
                self.channel.received.disconnect(self._on_received)
            except Exception:
                pass
        self.channel = None
        self.send_btn.setEnabled(False)
        self.file_btn.setEnabled(False)
        self.file_send_btn.setEnabled(False)
        self._stop_file_send()

    def set_send_text(self, text: str):
        """外部填充发送区文本（如 Modbus 报文构造器）。"""
        self.send.setPlainText(text)

    def _mode(self):
        return "hex" if self.rb_hex.isChecked() else "ascii"

    def _tx_mode(self):
        return "hex" if self.tx_hex.isChecked() else "ascii"

    def _enc(self):
        return self.config.get("default_encoding", "utf-8")

    # ================= 日志 =================
    def _log(self, direction: str, text: str):
        """向通信日志写入一行；direction 为 'tx'(发送) 或 'rx'(接收)。"""
        ts = ""
        if self.ts_chk.isChecked():
            ts = QDateTime.currentDateTime().toString("hh:mm:ss.zzz") + " "
        tag = tr("tx_tag") if direction == "tx" else tr("rx_tag")
        send_color, recv_color = direction_colors()
        color = send_color if direction == "tx" else recv_color
        self.recv.setTextColor(QColor(color))
        self.recv.append(f"{ts}{tag} {text}")
        self.recv.setTextColor(self.recv.palette().color(QPalette.Text))
        if self.autoscroll_chk.isChecked():
            self.recv.moveCursor(QTextCursor.End)

    def _on_received(self, data: bytes, meta: dict):
        text = bytes_to_text(data, self._mode(), self._enc())
        self._log("rx", text)
        self._rx += len(data)
        self._update_stat()
        # 自动回复
        for reply, delay in self.autoreply.match(data):
            if delay and delay > 0:
                QTimer.singleShot(delay, lambda r=reply: self._auto_send(r))
            else:
                self._auto_send(reply)

    def _auto_send(self, data: bytes):
        if self.channel:
            self.channel.send(data)
            self._tx += len(data)
            self._update_stat()
            self._log("tx", bytes_to_text(data, self._tx_mode(), self._enc()))

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
        self.channel.send(data)
        self._tx += len(data)
        self._update_stat()
        self._log("tx", bytes_to_text(data, self._tx_mode(), self._enc()))

    def _on_timer(self):
        if self.periodic.isChecked():
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
        import os

        self._file_name = os.path.basename(path)
        self._file_total = len(self._file_data)
        self._file_offset = 0
        # 显示文件信息行
        self.file_row.setVisible(True)
        self.file_info.setText(
            tr("file_selected_info").format(self._file_name, self._file_total)
        )
        self.file_progress.setVisible(False)
        # 启用发送按钮
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
        self._tx += len(chunk)
        self._update_stat()
        self._file_offset = end
        pct = int(self._file_offset / self._file_total * 100) if self._file_total else 100
        self.file_progress.setText(
            tr("file_sending").format(self._file_name, self._file_offset, self._file_total, pct)
        )
        if self._file_offset >= self._file_total:
            self._log("tx", tr("file_send_done").format(self._file_name))
            self._stop_file_send()
            # 文件发完，恢复选择状态
            self.file_send_btn.setText(tr("start_file_send"))
            self._file_offset = 0

    def _stop_file_send(self):
        self._file_sending = False
        self._file_timer.stop()
        if self._file_data is not None:
            self.file_send_btn.setText(tr("start_file_send"))
            self.file_send_btn.setEnabled(bool(self.channel))
        # 延迟隐藏进度条
        QTimer.singleShot(2000, lambda: self.file_progress.setVisible(False) if not self._file_sending else None)

    def _update_stat(self):
        self.stat.setText(f"RX {self._rx}  ·  TX {self._tx}")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("export_log"), "", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.recv.toPlainText())
