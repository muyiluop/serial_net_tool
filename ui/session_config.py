"""会话配置表单：按会话类型动态生成字段。

布局规范（紧凑工程感）：
- 字段采用「上标签（11.5px 次要色）+ 下控件」的堆叠块，两列网格排列；
  避免旧版「左标签 + 右控件」在宽度变化时标签列不齐、控件被拉伸的问题。
- 控件宽度限制在 110–220px，不再无限拉伸。
- 复选框统一收进一个「流控 / 选项」分组，避免跨列错位。
- summary() 生成一行配置摘要（串口用 8N1 记法），便于折叠时快速了解参数。
"""
from PySide6.QtWidgets import (
    QWidget,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QGroupBox,
    QLabel,
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
}

# 控件尺寸约束
_CTRL_MIN_W = 110
_CTRL_MAX_W = 220


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
        if kind == "serial":
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
            cb.clear()
            cb.addItems(ports)
            cb.setEditable(True)
            idx = cb.findText(current)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            elif current:
                cb.setCurrentText(current)

    # ---------- 字段构造 ----------
    def _register(self, key: str, label: str, widget: QWidget) -> tuple:
        """登记字段并返回条目 (key, label, widget)。"""
        widget.setMinimumWidth(_CTRL_MIN_W)
        widget.setMaximumWidth(_CTRL_MAX_W)
        self._widgets[key] = widget
        self._labels[key] = label
        return (key, label, widget)

    def _combo(self, items, editable=False) -> QComboBox:
        cb = QComboBox()
        cb.addItems(items)
        cb.setEditable(editable)
        return cb

    def _port_combo(self) -> QComboBox:
        """端口下拉框（注册到热插拔刷新列表）。"""
        cb = self._combo(_ports(), editable=True)
        self._port_combos.append(cb)
        return cb

    def _line(self, placeholder="") -> QLineEdit:
        le = QLineEdit()
        le.setPlaceholderText(placeholder)
        return le

    def _spin(self, default, maximum=65535) -> QSpinBox:
        sb = QSpinBox()
        sb.setMaximum(maximum)
        sb.setValue(default)
        return sb

    @staticmethod
    def _check(label) -> QCheckBox:
        return QCheckBox(label)

    def _pkt_reassembly_fields(self) -> list:
        """粘包重组配置字段。"""
        pkt_mode = self._combo(["none", "timeout", "delimiter", "length_prefix"])
        pkt_idle = self._spin(50, maximum=10000)
        pkt_delim = self._line("0D 0A")
        pkt_keep = self._check(tr("pkt_keep_delimiter"))
        pkt_len_bytes = self._combo(["1", "2", "4"])
        pkt_len_endian = self._combo(["big", "little"])
        pkt_len_incl = self._check(tr("pkt_len_includes_header"))
        # 默认禁用非 none 模式的参数
        for w in (pkt_idle, pkt_delim, pkt_keep, pkt_len_bytes, pkt_len_endian, pkt_len_incl):
            w.setEnabled(False)
        pkt_mode.currentTextChanged.connect(self._on_pkt_mode_change)
        return [
            self._register("pkt_mode", tr("pkt_mode"), pkt_mode),
            self._register("pkt_idle_ms", tr("pkt_idle_ms"), pkt_idle),
            self._register("pkt_delimiter", tr("pkt_delimiter"), pkt_delim),
            self._register("pkt_keep_delimiter", "", pkt_keep),
            self._register("pkt_len_bytes", tr("pkt_len_bytes"), pkt_len_bytes),
            self._register("pkt_len_endian", tr("pkt_len_endian"), pkt_len_endian),
            self._register("pkt_len_includes_header", "", pkt_len_incl),
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
        k = self.kind
        items: list = []
        checks_title = tr("options")

        if k == "serial":
            checks_title = tr("flow_control")
            items = [
                self._register("port", tr("port"), self._port_combo()),
                self._register("baud", tr("baud"),
                               self._combo(["9600", "19200", "38400", "57600", "115200"], editable=True)),
                self._register("bytesize", tr("bytesize"), self._combo(["8", "7", "6", "5"])),
                self._register("parity", tr("parity"), self._combo(["N", "E", "O", "M", "S"])),
                self._register("stopbits", tr("stopbits"), self._combo(["1", "1.5", "2"])),
                self._register("xonxoff", "XON/XOFF", self._check("XON/XOFF")),
                self._register("rtscts", "RTS/CTS", self._check("RTS/CTS")),
            ]
        elif k in ("tcp_client", "udp"):
            items = [
                self._register("host", tr("host"), self._line("127.0.0.1")),
                self._register("port", tr("port"), self._spin(8080)),
            ]
            if k == "udp":
                items += [
                    self._register("local_port", tr("local_port"), self._spin(0)),
                    self._register("broadcast", tr("broadcast"), self._check(tr("broadcast"))),
                    self._register("multicast", tr("multicast"), self._check(tr("multicast"))),
                    self._register("multicast_group", tr("multicast_group"),
                                   self._line("239.0.0.1")),
                    self._register("multicast_iface", tr("multicast_iface"),
                                   self._line("0.0.0.0")),
                ]
            if k == "tcp_client":
                items += self._pkt_reassembly_fields()
        elif k == "tcp_server":
            items = [self._register("port", tr("listen_port"), self._spin(8080))]
            items += self._pkt_reassembly_fields()
        elif k == "mqtt":
            items = [
                self._register("host", tr("broker_addr"), self._line("test.mosquitto.org")),
                self._register("port", tr("port"), self._spin(1883)),
                self._register("client_id", tr("client_id"), self._line("serial_net_tool")),
                self._register("username", tr("username"), self._line("")),
                self._register("password", tr("password"), self._line("")),
                self._register("keepalive", tr("keepalive"), self._spin(60, maximum=3600)),
                self._register("use_tls", tr("use_tls"), self._check(tr("use_tls"))),
            ]

        fields = [(key, label, w) for key, label, w in items if not isinstance(w, QCheckBox)]
        checks = [(key, w) for key, _label, w in items if isinstance(w, QCheckBox)]

        # 两列网格：每列为「上标签 + 下控件」的字段块
        grid = QGridLayout(self)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setContentsMargins(2, 2, 2, 2)
        cols = 2
        for i, (_key, label, widget) in enumerate(fields):
            row, col = divmod(i, cols)
            grid.addWidget(self._field_block(label, widget), row, col)
        for c in range(cols):
            grid.setColumnStretch(c, 1)

        # 复选框收进分组，整行排列
        if checks:
            row = (len(fields) + cols - 1) // cols
            group = QGroupBox(checks_title)
            h = QHBoxLayout(group)
            h.setSpacing(14)
            for _key, cb in checks:
                h.addWidget(cb)
            h.addStretch()
            grid.addWidget(group, row, 0, 1, cols)

        # UDP 组播：仅在启用时允许编辑组播地址/网卡
        if k == "udp" and "multicast" in self._widgets:
            self._widgets["multicast"].toggled.connect(self._on_multicast_toggle)
            self._on_multicast_toggle(self._widgets["multicast"].isChecked())

    def _field_block(self, label: str, widget: QWidget) -> QWidget:
        """包装为「上标签 + 下控件」的字段块。"""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        lab = QLabel(label)
        lab.setObjectName("h2")
        v.addWidget(lab)
        v.addWidget(widget)
        return box

    def _on_multicast_toggle(self, enabled: bool):
        for key in ("multicast_group", "multicast_iface"):
            w = self._widgets.get(key)
            if w:
                w.setEnabled(enabled)

    # ---------- 配置读写 ----------
    def get_config(self) -> dict:
        cfg = {}
        for key, w in self._widgets.items():
            if isinstance(w, QComboBox):
                cfg[key] = w.currentText()
            elif isinstance(w, QLineEdit):
                cfg[key] = w.text()
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
        if self.kind == "serial":
            frame = (
                f"{cfg.get('bytesize', '8')}"
                f"{cfg.get('parity', 'N')}"
                f"{cfg.get('stopbits', '1')}"
            )
            parts = [cfg.get("port", ""), cfg.get("baud", ""), frame]
            if cfg.get("xonxoff"):
                parts.append("XON")
            if cfg.get("rtscts"):
                parts.append("RTS")
            text = " · ".join(str(p) for p in parts if p not in (None, ""))
            return text or tr("not_configured")
        keys = _SUMMARY_KEYS.get(self.kind, [])
        parts = []
        for key in keys:
            v = cfg.get(key)
            if v in (None, ""):
                continue
            parts.append(str(v))
        return " · ".join(parts) if parts else tr("not_configured")
