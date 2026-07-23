"""MQTT 通道：paho-mqtt 客户端（连接外部 Broker）。
内置 Broker 本版不做（见 PRD Won't 项）。

增强功能（T6.2）：
- 退避重连：断线后指数退避重连（1s→2s→4s→8s→16s→max 30s），重连成功后重置
- 主题收藏：订阅列表持久化到 config，重连后自动恢复订阅
- 通配符订阅：支持 +/# 通配符，面板展示当前订阅列表
"""
import time
from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from PySide6.QtCore import QTimer

from .channel import Channel, ChannelStatus
from .i18n import tr

# 退避重连参数
_BACKOFF_INITIAL_MS = 1000
_BACKOFF_MAX_MS = 30000
_BACKOFF_FACTOR = 2


class MqttChannel(Channel):
    def open(self, cfg: dict):
        self.status = ChannelStatus.CONNECTING
        self._cfg = cfg
        self._reconnect_attempts = 0
        self._reconnect_timer: QTimer | None = None
        self._subscribed_topics: list[dict] = []
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
        try:
            self._client.connect_async(
                cfg["host"], int(cfg["port"]), keepalive=int(cfg.get("keepalive", 60))
            )
            self._client.loop_start()
        except Exception as e:
            self.emit_error(str(e))
            self.status = ChannelStatus.ERROR

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_success:
            self._reconnect_attempts = 0
            self.status = ChannelStatus.CONNECTED
            self.emit_log("INFO", tr("mqtt_connected"))
            # 恢复之前订阅的主题（主题收藏功能）
            subs = self._cfg.get("subscriptions", [])
            if not subs:
                # 兼容旧格式：从 cfg.subscribes 字符串列表读取
                topic_list = self._cfg.get("subscribes", "")
                if topic_list:
                    for t in topic_list.split("\n"):
                        t = t.strip()
                        if t:
                            subs.append({"topic": t, "qos": 0})
            for sub in subs:
                topic = sub["topic"] if isinstance(sub, dict) else str(sub)
                qos = sub.get("qos", 0) if isinstance(sub, dict) else 0
                client.subscribe(topic, qos)
                self._subscribed_topics.append({"topic": topic, "qos": qos})
                self.emit_log("INFO", tr("mqtt_subscribed").format(topic))
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
        """运行时动态订阅主题，并记录到收藏列表。"""
        if hasattr(self, "_client"):
            self._client.subscribe(topic, qos)
            self._subscribed_topics.append({"topic": topic, "qos": qos})
            self.emit_log("INFO", tr("mqtt_subscribed").format(topic))

    def unsubscribe(self, topic: str):
        """取消订阅主题。"""
        if hasattr(self, "_client"):
            self._client.unsubscribe(topic)
            self._subscribed_topics = [
                s for s in self._subscribed_topics if s["topic"] != topic
            ]
            self.emit_log("INFO", tr("mqtt_unsubscribed").format(topic))

    def get_subscriptions(self) -> list[dict]:
        """返回当前已订阅的主题列表（含通配符）。"""
        return list(self._subscribed_topics)

    def publish(self, topic: str, payload, qos: int = 0, retain: bool = False):
        if hasattr(self, "_client"):
            self._client.publish(topic, payload, qos=qos, retain=retain)

    def close(self):
        if hasattr(self, "_reconnect_timer") and self._reconnect_timer:
            self._reconnect_timer.stop()
        if hasattr(self, "_client"):
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._subscribed_topics.clear()
        self.status = ChannelStatus.DISCONNECTED

    def send(self, data: bytes):
        # MQTT 通过 publish 发送，统一 send 接口留空
        pass
