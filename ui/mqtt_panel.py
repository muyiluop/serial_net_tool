"""MQTT 运行期面板：发布目标、订阅管理、遗嘱(LWT) 配置。

- 发布组：默认发布主题/QoS/保留，直接映射到 Channel.send()。
- 订阅组：运行期动态订阅/取消订阅（支持 +/# 通配符），与通道双向同步。
- 遗嘱组：连接前生效（由 SessionView 在 open_channel 时合并进 cfg）。
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QComboBox,
    QLineEdit,
    QLabel,
    QCheckBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from ..core.i18n import tr


class MqttPanel(QWidget):
    """MQTT 会话的运行期配置面板。"""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.channel = None
        self._subs: list[dict] = []
        self._build()

    # ================= UI =================
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ---- 发布 ----
        pub = QGroupBox(tr("mqtt_publish"))
        grid = QGridLayout(pub)
        grid.addWidget(self._label(tr("mqtt_topic")), 0, 0)
        self.pub_topic = QLineEdit()
        self.pub_topic.setPlaceholderText("sensor/cmd")
        grid.addWidget(self.pub_topic, 0, 1, 1, 3)
        grid.addWidget(self._label(tr("qos")), 1, 0)
        self.pub_qos = self._qos_combo()
        grid.addWidget(self.pub_qos, 1, 1)
        self.pub_retain = QCheckBox(tr("mqtt_retain"))
        grid.addWidget(self.pub_retain, 1, 2, 1, 2)
        grid.setColumnStretch(3, 1)
        layout.addWidget(pub)

        # ---- 订阅 ----
        sub = QGroupBox(tr("mqtt_subscribe"))
        sl = QVBoxLayout(sub)
        add_row = QHBoxLayout()
        self.sub_topic = QLineEdit()
        self.sub_topic.setPlaceholderText("sensor/#")
        self.sub_qos = self._qos_combo()
        self.sub_add = QPushButton(tr("mqtt_add_sub"))
        self.sub_add.setObjectName("ghost")
        self.sub_del = QPushButton(tr("mqtt_remove_sub"))
        self.sub_del.setObjectName("ghost")
        add_row.addWidget(self.sub_topic, 1)
        add_row.addWidget(self.sub_qos)
        add_row.addWidget(self.sub_add)
        add_row.addWidget(self.sub_del)
        sl.addLayout(add_row)

        self.sub_table = QTableWidget(0, 2)
        self.sub_table.setHorizontalHeaderLabels([tr("mqtt_topic"), tr("qos")])
        self.sub_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.sub_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.sub_table.setMaximumHeight(110)
        self.sub_table.verticalHeader().setVisible(False)
        sl.addWidget(self.sub_table)
        layout.addWidget(sub)

        # ---- 遗嘱 ----
        lwt = QGroupBox(tr("mqtt_lwt"))
        lg = QGridLayout(lwt)
        self.lwt_enable = QCheckBox(tr("mqtt_lwt_enable"))
        lg.addWidget(self.lwt_enable, 0, 0, 1, 2)
        lg.addWidget(self._label(tr("mqtt_topic")), 1, 0)
        self.lwt_topic = QLineEdit()
        lg.addWidget(self.lwt_topic, 1, 1)
        lg.addWidget(self._label(tr("mqtt_payload")), 2, 0)
        self.lwt_payload = QLineEdit()
        lg.addWidget(self.lwt_payload, 2, 1)
        lg.addWidget(self._label(tr("qos")), 3, 0)
        self.lwt_qos = self._qos_combo()
        lg.addWidget(self.lwt_qos, 3, 1)
        self.lwt_retain = QCheckBox(tr("mqtt_retain"))
        lg.addWidget(self.lwt_retain, 4, 0, 1, 2)
        lg.setColumnStretch(1, 1)
        layout.addWidget(lwt)

        # ---- 信号 ----
        self.pub_topic.textChanged.connect(self._on_publish_changed)
        self.pub_qos.currentIndexChanged.connect(self._on_publish_changed)
        self.pub_retain.toggled.connect(self._on_publish_changed)
        self.sub_add.clicked.connect(self._on_add_sub)
        self.sub_del.clicked.connect(self._on_remove_sub)
        self.sub_topic.returnPressed.connect(self._on_add_sub)

    def _label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("dim")
        return lab

    def _qos_combo(self) -> QComboBox:
        cb = QComboBox()
        for q in (0, 1, 2):
            cb.addItem(str(q), q)
        cb.setMinimumWidth(60)
        return cb

    # ================= 配置读写 =================
    def apply_config(self, cfg: dict):
        """从会话配置载入初始值。"""
        self.pub_topic.setText(str(cfg.get("publish_topic", "") or ""))
        self._set_qos(self.pub_qos, cfg.get("publish_qos", 0))
        self.pub_retain.setChecked(bool(cfg.get("publish_retain", False)))

        self.lwt_enable.setChecked(bool(cfg.get("lwt_enable", False)))
        self.lwt_topic.setText(str(cfg.get("lwt_topic", "") or ""))
        self.lwt_payload.setText(str(cfg.get("lwt_payload", "") or ""))
        self._set_qos(self.lwt_qos, cfg.get("lwt_qos", 0))
        self.lwt_retain.setChecked(bool(cfg.get("lwt_retain", False)))

        self._subs = [
            dict(s) if isinstance(s, dict) else {"topic": str(s), "qos": 0}
            for s in cfg.get("subscriptions", []) or []
        ]
        self._refresh_subs()

    def collect_config(self) -> dict:
        """导出为会话配置片段（open_channel 时合并）。"""
        return {
            "publish_topic": self.pub_topic.text().strip(),
            "publish_qos": self.pub_qos.currentData(),
            "publish_retain": self.pub_retain.isChecked(),
            "lwt_enable": self.lwt_enable.isChecked(),
            "lwt_topic": self.lwt_topic.text().strip(),
            "lwt_payload": self.lwt_payload.text(),
            "lwt_qos": self.lwt_qos.currentData(),
            "lwt_retain": self.lwt_retain.isChecked(),
            "subscriptions": [dict(s) for s in self._subs],
        }

    @staticmethod
    def _set_qos(combo: QComboBox, value):
        try:
            idx = combo.findData(int(value))
        except (TypeError, ValueError):
            idx = 0
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    # ================= 通道绑定 =================
    def bind(self, channel):
        self.channel = channel
        if hasattr(channel, "subscriptions_changed"):
            channel.subscriptions_changed.connect(self._on_subs_changed)
        self._sync_publish_to_channel()
        # 以通道当前订阅为准刷新
        if hasattr(channel, "get_subscriptions"):
            self._subs = [dict(s) for s in channel.get_subscriptions()] or self._subs
        self._refresh_subs()

    def unbind(self):
        if self.channel and hasattr(self.channel, "subscriptions_changed"):
            try:
                self.channel.subscriptions_changed.disconnect(self._on_subs_changed)
            except Exception:
                pass
        self.channel = None

    def _sync_publish_to_channel(self):
        if self.channel and hasattr(self.channel, "set_publish_defaults"):
            self.channel.set_publish_defaults(
                self.pub_topic.text().strip(),
                self.pub_qos.currentData(),
                self.pub_retain.isChecked(),
            )

    def _on_publish_changed(self, *_):
        self._sync_publish_to_channel()

    # ================= 订阅 =================
    def _on_subs_changed(self, subs):
        self._subs = [dict(s) for s in subs]
        self._refresh_subs()

    def _refresh_subs(self):
        self.sub_table.setRowCount(len(self._subs))
        for i, s in enumerate(self._subs):
            self.sub_table.setItem(i, 0, QTableWidgetItem(str(s.get("topic", ""))))
            self.sub_table.setItem(i, 1, QTableWidgetItem(str(s.get("qos", 0))))

    def _on_add_sub(self):
        topic = self.sub_topic.text().strip()
        if not topic:
            return
        qos = self.sub_qos.currentData()
        if not any(s.get("topic") == topic for s in self._subs):
            self._subs.append({"topic": topic, "qos": qos})
            self._refresh_subs()
        if self.channel and hasattr(self.channel, "subscribe"):
            self.channel.subscribe(topic, qos)
        self.sub_topic.clear()

    def _on_remove_sub(self):
        row = self.sub_table.currentRow()
        if row < 0 or row >= len(self._subs):
            return
        topic = self._subs[row].get("topic", "")
        del self._subs[row]
        self._refresh_subs()
        if self.channel and hasattr(self.channel, "unsubscribe") and topic:
            self.channel.unsubscribe(topic)
