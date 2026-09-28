"""MQTT 通道：paho-mqtt 客户端（连接外部 Broker）。
内置 Broker 本版不做（见 PRD Won't 项）。

功能：
- 连接/订阅/发布（QoS、保留）、通配符订阅、遗嘱(LWT)
- 退避重连：由 paho-mqtt 内置 auto-reconnect 处理（1s→30s）
- 主题收藏：订阅列表持久化，重连后自动恢复（含运行期新增的订阅）
"""
from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from PySide6.QtCore import Signal

from .channel import Channel, ChannelStatus
from .i18n import tr

# 退避重连参数（仅用于状态提示文案，实际重连由 paho 内置处理）
_BACKOFF_INITIAL_MS = 1000
_BACKOFF_MAX_MS = 30000
_BACKOFF_FACTOR = 2


class MqttChannel(Channel):
    # 订阅列表变化（供 UI 同步持久化）
    subscriptions_changed = Signal(list)

    def open(self, cfg: dict):
        self.status = ChannelStatus.CONNECTING
        self._cfg = cfg
        self._reconnect_attempts = 0
        self._subscribed_topics: list[dict] = []
        self._restore_configured_subscriptions(cfg)
        # 默认发布目标（可经 set_publish_defaults 运行期修改）
        self._publish_topic = cfg.get("publish_topic", "") or ""
        try:
            self._publish_qos = int(cfg.get("publish_qos", 0) or 0)
        except (TypeError, ValueError):
            self._publish_qos = 0
        self._publish_retain = bool(cfg.get("publish_retain", False))
        try:
            self._client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2,
                client_id=cfg.get("client_id", ""),
            )
        except Exception:
            self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        # 启用自动重连（paho-mqtt v2 内置）
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        if cfg.get("username"):
            self._client.username_pw_set(cfg["username"], cfg.get("password", ""))
        if cfg.get("use_tls"):
            self._client.tls_set()
        # 遗嘱必须设置于连接之前
        if cfg.get("lwt_enable") and cfg.get("lwt_topic"):
            try:
                self._client.will_set(
                    cfg["lwt_topic"],
                    cfg.get("lwt_payload", ""),
                    qos=int(cfg.get("lwt_qos", 0) or 0),
                    retain=bool(cfg.get("lwt_retain", False)),
                )
            except Exception as e:
                self.emit_log("WARN", f"LWT config error: {e}")
        try:
            self._client.connect_async(
                cfg["host"], int(cfg["port"]), keepalive=int(cfg.get("keepalive", 60))
            )
            self._client.loop_start()
        except Exception as e:
            self.emit_error(str(e))
            self.status = ChannelStatus.ERROR

    def _restore_configured_subscriptions(self, cfg: dict):
        """从会话配置预置订阅列表（subscriptions 或旧格式 subscribes）。"""
        subs = cfg.get("subscriptions", [])
        if not subs:
            topic_list = cfg.get("subscribes", "")
            if topic_list:
                subs = [
                    {"topic": t.strip(), "qos": 0}
                    for t in topic_list.split("\n")
                    if t.strip()
                ]
        for sub in subs:
            if isinstance(sub, dict):
                topic, qos = sub.get("topic", ""), sub.get("qos", 0)
            else:
                topic, qos = str(sub), 0
            if topic:
                self._subscribed_topics.append({"topic": topic, "qos": qos})

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_success:
            self._reconnect_attempts = 0
            self.status = ChannelStatus.CONNECTED
            self.emit_log("INFO", tr("mqtt_connected"))
            # 恢复订阅（重连时使用运行期累积的列表，保证新增订阅不丢失）
            for sub in self._subscribed_topics:
                client.subscribe(sub["topic"], sub.get("qos", 0))
                self.emit_log("INFO", tr("mqtt_subscribed").format(sub["topic"]))
            self.subscriptions_changed.emit(self.get_subscriptions())
        else:
            self.emit_error(tr("mqtt_connect_failed").format(reason_code))
            self.status = ChannelStatus.ERROR

    def _on_message(self, client, userdata, msg):
        self.emit_received(
            msg.payload, {"topic": msg.topic, "qos": msg.qos, "dir": "in"}
        )

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_success:
            self.status = ChannelStatus.DISCONNECTED
        else:
            # 指数退避重连
            self._reconnect_attempts += 1
            delay_ms = min(
                _BACKOFF_INITIAL_MS * (_BACKOFF_FACTOR ** (self._reconnect_attempts - 1)),
                _BACKOFF_MAX_MS,
            )
            self.status = ChannelStatus.RECONNECTING
            self.emit_log("WARN", tr("mqtt_reconnecting").format(
                self._reconnect_attempts, int(delay_ms / 1000)
            ))
            # paho-mqtt v2 内置 auto-reconnect，这里额外更新状态
            # 不需要手动 reconnect，client.loop_start() 会自动处理

    def subscribe(self, topic: str, qos: int = 0):
        """运行时动态订阅主题，并记录到订阅列表。"""
        if not topic:
            return
        if hasattr(self, "_client"):
            self._client.subscribe(topic, qos)
        if not any(s["topic"] == topic for s in self._subscribed_topics):
            self._subscribed_topics.append({"topic": topic, "qos": qos})
        self.emit_log("INFO", tr("mqtt_subscribed").format(topic))
        self.subscriptions_changed.emit(self.get_subscriptions())

    def unsubscribe(self, topic: str):
        """取消订阅主题。"""
        if hasattr(self, "_client"):
            self._client.unsubscribe(topic)
        self._subscribed_topics = [
            s for s in self._subscribed_topics if s["topic"] != topic
        ]
        self.emit_log("INFO", tr("mqtt_unsubscribed").format(topic))
        self.subscriptions_changed.emit(self.get_subscriptions())

    def get_subscriptions(self) -> list[dict]:
        """返回当前已订阅的主题列表（含通配符）。"""
        return [dict(s) for s in self._subscribed_topics]

    def set_publish_defaults(self, topic: str, qos: int = 0, retain: bool = False):
        """设置统一 send 接口使用的默认发布目标。"""
        self._publish_topic = topic or ""
        try:
            self._publish_qos = int(qos)
        except (TypeError, ValueError):
            self._publish_qos = 0
        self._publish_retain = bool(retain)

    def publish(self, topic: str, payload, qos: int = 0, retain: bool = False):
        if hasattr(self, "_client"):
            self._client.publish(topic, payload, qos=qos, retain=retain)

    def close(self):
        if hasattr(self, "_client"):
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._subscribed_topics.clear()
        self.status = ChannelStatus.DISCONNECTED

    def send(self, data: bytes):
        """统一 send 接口：MQTT 下等价于向默认主题发布。"""
        topic = getattr(self, "_publish_topic", "")
        if not topic:
            self.emit_log("WARN", tr("mqtt_no_publish_topic"))
            return
        self.publish(topic, data, getattr(self, "_publish_qos", 0),
                     getattr(self, "_publish_retain", False))
        self.emit_log("INFO", tr("mqtt_published").format(topic, len(data)))
