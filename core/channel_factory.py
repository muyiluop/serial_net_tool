"""通道工厂：按类型创建 Channel 实例。"""
from .channel import Channel
from .serial_channel import SerialChannel
from .tcpudp_channel import TcpClientChannel, TcpServerChannel, UdpChannel
from .mqtt_channel import MqttChannel

_KIND_MAP = {
    "serial": SerialChannel,
    "tcp_client": TcpClientChannel,
    "tcp_server": TcpServerChannel,
    "udp": UdpChannel,
    "mqtt": MqttChannel,
}


def list_kinds() -> list:
    return list(_KIND_MAP.keys())


def create_channel(kind: str, session_id: str) -> Channel:
    cls = _KIND_MAP.get(kind)
    if not cls:
        raise ValueError(f"unknown channel kind: {kind}")
    return cls(session_id)
