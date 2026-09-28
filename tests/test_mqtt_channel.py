"""MQTT 通道：遗嘱、订阅恢复、send→publish 行为（使用假客户端）。"""
import pytest

from serial_net_tool.core import mqtt_channel as mod
from serial_net_tool.core.mqtt_channel import MqttChannel


class FakeReasonCode:
    def __init__(self, ok=True):
        self.is_success = ok

    def __str__(self):
        return "Success" if self.is_success else "Fail"


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None

    def reconnect_delay_set(self, **kwargs):
        pass

    def username_pw_set(self, *args):
        pass

    def tls_set(self, *args):
        pass

    def will_set(self, *args, **kwargs):
        self.calls.append(("will", args, kwargs))

    def connect_async(self, *args, **kwargs):
        self.calls.append(("connect", args, kwargs))

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def subscribe(self, topic, qos):
        self.calls.append(("sub", topic, qos))

    def unsubscribe(self, topic):
        self.calls.append(("unsub", topic))

    def publish(self, topic, payload, **kwargs):
        self.calls.append(("pub", topic, payload, kwargs))

    def _find(self, kind):
        return [c for c in self.calls if c[0] == kind]


@pytest.fixture
def fake_mqtt(monkeypatch):
    holder = {}

    def factory(*args, **kwargs):
        holder["client"] = FakeClient(*args, **kwargs)
        return holder["client"]

    monkeypatch.setattr(mod.mqtt, "Client", factory)
    return holder


BASE_CFG = {
    "host": "localhost",
    "port": 1883,
    "client_id": "test",
    "publish_topic": "cmd/out",
    "publish_qos": 1,
    "publish_retain": True,
}


def test_will_set_before_connect(fake_mqtt):
    ch = MqttChannel("s")
    cfg = dict(BASE_CFG, lwt_enable=True, lwt_topic="status/off",
               lwt_payload="offline", lwt_qos=2, lwt_retain=True)
    ch.open(cfg)
    kinds = [c[0] for c in fake_mqtt["client"].calls]
    assert "will" in kinds and "connect" in kinds
    assert kinds.index("will") < kinds.index("connect")


def test_send_publishes_to_default_topic(fake_mqtt):
    ch = MqttChannel("s")
    ch.open(dict(BASE_CFG))
    ch.send(b"hello")
    pubs = fake_mqtt["client"]._find("pub")
    assert pubs
    assert pubs[0][1] == "cmd/out"
    assert pubs[0][2] == b"hello"
    assert pubs[0][3] == {"qos": 1, "retain": True}


def test_send_without_topic_warns(fake_mqtt):
    ch = MqttChannel("s")
    ch.open(dict(BASE_CFG, publish_topic=""))
    logs = []
    ch.log_message.connect(lambda level, msg: logs.append((level, msg)))
    ch.send(b"x")
    assert not fake_mqtt["client"]._find("pub")
    assert any(level == "WARN" for level, _ in logs)


def test_configured_subscriptions_restored_on_connect(fake_mqtt):
    ch = MqttChannel("s")
    ch.open(dict(BASE_CFG, subscriptions=[{"topic": "a/#", "qos": 0},
                                          {"topic": "b/+", "qos": 1}]))
    client = fake_mqtt["client"]
    ch._on_connect(client, None, None, FakeReasonCode(True), None)
    subs = client._find("sub")
    assert ("sub", "a/#", 0) in subs
    assert ("sub", "b/+", 1) in subs
    assert len(ch.get_subscriptions()) == 2


def test_legacy_subscribes_string_supported(fake_mqtt):
    ch = MqttChannel("s")
    ch.open(dict(BASE_CFG, subscribes="sensor/#\ncmd/+/status"))
    client = fake_mqtt["client"]
    ch._on_connect(client, None, None, FakeReasonCode(True), None)
    topics = {c[1] for c in client._find("sub")}
    assert topics == {"sensor/#", "cmd/+/status"}


def test_runtime_subscribe_emits_signal_and_persists(fake_mqtt):
    ch = MqttChannel("s")
    ch.open(dict(BASE_CFG))
    seen = []
    ch.subscriptions_changed.connect(lambda s: seen.append(s))
    ch.subscribe("new/topic", 1)
    assert ("sub", "new/topic", 1) in fake_mqtt["client"]._find("sub")
    assert seen and seen[-1][0]["topic"] == "new/topic"

    ch.unsubscribe("new/topic")
    assert ("unsub", "new/topic") in fake_mqtt["client"]._find("unsub")
    assert ch.get_subscriptions() == []


def test_set_publish_defaults(fake_mqtt):
    ch = MqttChannel("s")
    ch.open(dict(BASE_CFG))
    ch.set_publish_defaults("other", 2, False)
    ch.send(b"z")
    pub = fake_mqtt["client"]._find("pub")[-1]
    assert pub[1] == "other" and pub[3] == {"qos": 2, "retain": False}
