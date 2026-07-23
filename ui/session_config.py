"""会话配置表单：按会话类型动态生成字段，采用紧凑网格布局。

相比旧版 QFormLayout 单列平铺，这里用 2 列网格排列，显著降低纵向占用；
并提供 summary() 生成一行配置摘要，便于折叠时快速了解当前连接参数。
"""
from PySide6.QtWidgets import (
    QWidget,
    QGridLayout,
    QVBoxLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
)
from PySide6.QtCore import QTimer
from ..core.i18n import tr

# 每种会话类型的关键摘要字段（按顺序拼接展示）
_SUMMARY_KEYS = {
    "serial": ["port", "baud"],
    "tcp_client": ["host", "port"],
    "tcp_server": ["port"],
    "udp": ["host", "port"],
    "mqtt": ["host", "port"],
    "modbus": ["backend", "host", "port_tcp"],
}

def _ports() -> list:
    try:
        import serial.tools.list_ports

        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []


class SessionConfigWidget(QWidget):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._widgets: dict = {}
        self._labels: dict = {}
        self._port_combos: list[QComboBox] = []  # 需要热插拔刷新的端口下拉框
        self._build()
        # 串口类型：启动热插拔检测定时器
        if kind in ("serial", "modbus"):
            self._hotplug_timer = QTimer(self)
            self._hotplug_timer.timeout.connect(self._refresh_ports)
            self._hotplug_timer.start(2000)  # 每 2 秒检查一次

    def _refresh_ports(self):
        """热插拔：枚举可用串口，更新端口下拉框（保持当前选择）。"""
        ports = _ports()
        for cb in self._port_combos:
            if not cb.isEnabled():
                continue  # 连接中不刷新
            current = cb.currentText()
            old_items = [cb.itemText(i) for i in range(cb.count())]
            if set(ports) == set(old_items):
                continue  # 没有变化
            # 记住当前选择
            cb.clear()
            cb.addItems(ports)
            cb.setEditable(True)
            # 恢复选择（如果仍然存在）
            idx = cb.findText(current)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            elif current:
                cb.setCurrentText(current)

    # ---------- 字段构造 ----------
    def _add(self, key: str, label: str, widget: QWidget):
        self._widgets[key] = widget
        self._labels[key] = label

    def _combo(self, key, label, items, editable=False):
        cb = QComboBox()
        cb.addItems(items)
        cb.setEditable(editable)
        cb.setMinimumWidth(90)
        self._add(key, label, cb)
        return cb

    def _port_combo(self, key, label):
        """专用方法：创建端口下拉框并注册到热插拔刷新列表。"""
        cb = self._combo(key, label, _ports(), editable=True)
        self._port_combos.append(cb)
        return cb

    def _line(self, key, label, placeholder=""):
        le = QLineEdit()
        le.setPlaceholderText(placeholder)
        le.setMinimumWidth(90)
        self._add(key, label, le)
        return le

    def _multiline(self, key, label, placeholder=""):
        """多行文本编辑器（用于 MQTT 订阅主题列表等）。"""
        te = QPlainTextEdit()
        te.setPlaceholderText(placeholder)
        te.setMaximumHeight(60)
        self._add(key, label, te)
        return te

    def _spin(self, key, label, default, maximum=65535):
        sb = QSpinBox()
        sb.setMaximum(maximum)
        sb.setValue(default)
        sb.setMinimumWidth(70)
        self._add(key, label, sb)
        return sb

    def _check(self, key, label):
        c = QCheckBox(label)
        self._add(key, label, c)
        return c

    def _pkt_reassembly_fields(self) -> list:
        """粘包重组配置字段。"""
        pkt_mode = self._combo("pkt_mode", tr("pkt_mode"), ["none", "timeout", "delimiter", "length_prefix"])
        pkt_idle = self._spin("pkt_idle_ms", tr("pkt_idle_ms"), 50, maximum=10000)
        pkt_delim = self._line("pkt_delimiter", tr("pkt_delimiter"), "0D 0A")
        pkt_keep = self._check("pkt_keep_delimiter", tr("pkt_keep_delimiter"))
        pkt_len_bytes = self._combo("pkt_len_bytes", tr("pkt_len_bytes"), ["1", "2", "4"])
        pkt_len_endian = self._combo("pkt_len_endian", tr("pkt_len_endian"), ["big", "little"])
        pkt_len_incl = self._check("pkt_len_includes_header", tr("pkt_len_includes_header"))
        # 默认隐藏非 none 模式的参数
        pkt_idle.setEnabled(False)
        pkt_delim.setEnabled(False)
        pkt_keep.setEnabled(False)
        pkt_len_bytes.setEnabled(False)
        pkt_len_endian.setEnabled(False)
        pkt_len_incl.setEnabled(False)
        pkt_mode.currentTextChanged.connect(
            lambda mode: self._on_pkt_mode_change(mode)
        )
        return [
            ("pkt_mode", pkt_mode),
            ("pkt_idle_ms", pkt_idle),
            ("pkt_delimiter", pkt_delim),
            ("pkt_keep_delimiter", pkt_keep),
            ("pkt_len_bytes", pkt_len_bytes),
            ("pkt_len_endian", pkt_len_endian),
            ("pkt_len_includes_header", pkt_len_incl),
        ]

    def _on_pkt_mode_change(self, mode: str):
        """根据粘包模式启用/禁用对应字段。"""
        is_timeout = mode == "timeout"
        is_delim = mode == "delimiter"
        is_len = mode == "length_prefix"
        for key, enabled in [
            ("pkt_idle_ms", is_timeout),
            ("pkt_delimiter", is_delim),
            ("pkt_keep_delimiter", is_delim),
            ("pkt_len_bytes", is_len),
            ("pkt_len_endian", is_len),
            ("pkt_len_includes_header", is_len),
        ]:
            w = self._widgets.get(key)
            if w:
                w.setEnabled(enabled)

    def _build(self):
        # 先按类型创建字段（顺序即展示顺序）
        k = self.kind
        order: list = []
        if k == "serial":
            order = [
                ("port", self._port_combo("port", tr("port"))),
                ("baud", self._combo("baud", tr("baud"), ["9600", "19200", "38400", "57600", "115200"], editable=True)),
                ("bytesize", self._combo("bytesize", tr("bytesize"), ["8", "7", "6", "5"])),
                ("parity", self._combo("parity", tr("parity"), ["N", "E", "O", "M", "S"])),
                ("stopbits", self._combo("stopbits", tr("stopbits"), ["1", "1.5", "2"])),
                ("xonxoff", self._check("xonxoff", "XON/XOFF")),
                ("rtscts", self._check("rtscts", "RTS/CTS")),
            ]
        elif k in ("tcp_client", "udp"):
            order = [
                ("host", self._line("host", tr("host"), "127.0.0.1")),
                ("port", self._spin("port", tr("port"), 8080)),
            ]
            if k == "udp":
                order += [
                    ("local_port", self._spin("local_port", tr("local_port"), 0)),
                    ("broadcast", self._check("broadcast", tr("broadcast"))),
                ]
            if k == "tcp_client":
                order += self._pkt_reassembly_fields()
        elif k == "tcp_server":
            order = [("port", self._spin("port", tr("listen_port"), 8080))]
            order += self._pkt_reassembly_fields()
        elif k == "mqtt":
            order = [
                ("host", self._line("host", tr("broker_addr"), "test.mosquitto.org")),
                ("port", self._spin("port", tr("port"), 1883)),
                ("client_id", self._line("client_id", tr("client_id"), "serial_net_tool")),
                ("username", self._line("username", tr("username"), "")),
                ("password", self._line("password", tr("password"), "")),
                ("keepalive", self._spin("keepalive", tr("keepalive"), 60, maximum=3600)),
                ("use_tls", self._check("use_tls", tr("use_tls"))),
                ("subscribes", self._multiline("subscribes", tr("mqtt_topics"), "sensor/#\ncmd/+/status")),
            ]
        elif k == "modbus":
            order = [
                ("backend", self._combo("backend", tr("backend"), ["rtu", "tcp"])),
                ("port", self._port_combo("port", tr("serial_port_rtu"))),
                ("baud", self._spin("baud", tr("baud_rtu"), 9600)),
                ("parity", self._combo("parity", tr("parity_rtu"), ["N", "E", "O"])),
                ("stopbits", self._combo("stopbits", tr("stopbits_rtu"), ["1", "2"])),
                ("bytesize", self._combo("bytesize", tr("bytesize_rtu"), ["8", "7"])),
                ("host", self._line("host", tr("host_tcp"), "127.0.0.1")),
                ("port_tcp", self._spin("port_tcp", tr("port_tcp"), 502)),
            ]

        # 用 2 列网格紧凑排列：label+widget 为一组，两组一行
        grid = QGridLayout(self)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setContentsMargins(2, 2, 2, 2)
        col_pairs = 2
        for i, (key, w) in enumerate(order):
            row = i // col_pairs
            col = (i % col_pairs) * 2
            if isinstance(w, QCheckBox):
                grid.addWidget(w, row, col, 1, 2)
            else:
                lab = QLabel(self._labels[key])
                lab.setObjectName("dim")
                lab.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
                grid.addWidget(lab, row, col)
                grid.addWidget(w, row, col + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

    # ---------- 配置读写 ----------
    def get_config(self) -> dict:
        cfg = {}
        for key, w in self._widgets.items():
            if isinstance(w, QComboBox):
                cfg[key] = w.currentText()
            elif isinstance(w, QLineEdit):
                cfg[key] = w.text()
            elif isinstance(w, QPlainTextEdit):
                cfg[key] = w.toPlainText()
            elif isinstance(w, QSpinBox):
                cfg[key] = w.value()
            elif isinstance(w, QCheckBox):
                cfg[key] = w.isChecked()
        return cfg

    def apply_config(self, cfg: dict):
        for key, w in self._widgets.items():
            val = cfg.get(key)
            if val is None:
                continue
            if isinstance(w, QComboBox):
                idx = w.findText(str(val))
                if idx >= 0:
                    w.setCurrentIndex(idx)
                elif w.isEditable():
                    w.setCurrentText(str(val))
            elif isinstance(w, QLineEdit):
                w.setText(str(val))
            elif isinstance(w, QPlainTextEdit):
                w.setPlainText(str(val))
            elif isinstance(w, QSpinBox):
                try:
                    w.setValue(int(val))
                except (ValueError, TypeError):
                    pass
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(val))

    def set_enabled_all(self, enabled: bool):
        """整体启用/禁用（连接后锁定配置）。"""
        for w in self._widgets.values():
            w.setEnabled(enabled)

    def stop_hotplug(self):
        """停止热插拔检测（widget 销毁或关闭时调用）。"""
        timer = getattr(self, "_hotplug_timer", None)
        if timer:
            timer.stop()

    # ---------- 摘要 ----------
    def summary(self) -> str:
        """生成一行配置摘要，用于折叠时显示。"""
        cfg = self.get_config()
        keys = _SUMMARY_KEYS.get(self.kind, [])
        parts = []
        for key in keys:
            v = cfg.get(key)
            if v in (None, ""):
                continue
            parts.append(str(v))
        return " · ".join(parts) if parts else tr("not_configured")
