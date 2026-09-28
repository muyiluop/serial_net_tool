"""UDP 组播配置测试（假 socket，确定性）。"""
import socket

import pytest

from serial_net_tool.core import tcpudp_channel as mod
from serial_net_tool.core.tcpudp_channel import UdpChannel


class FakeSock:
    def __init__(self, *args, **kwargs):
        self.opts = []
        self.bound = None
        self.sent = []

    def setsockopt(self, level, opt, value):
        self.opts.append((level, opt, value))

    def bind(self, addr):
        self.bound = addr

    def sendto(self, data, target):
        self.sent.append((data, target))

    def settimeout(self, t):
        pass

    def close(self):
        pass

    def recvfrom(self, n):
        raise socket.timeout


@pytest.fixture
def fake_net(monkeypatch):
    holder = {}

    def make_sock(udp=False):
        holder["sock"] = FakeSock()
        return holder["sock"]

    class _Sig:
        def connect(self, *args, **kwargs):
            pass

    class DummyThread:
        data_received = _Sig()

        def __init__(self, sock, tag="", parent=None):
            self.sock = sock

        def start(self):
            pass

        def stop(self):
            pass

        def wait(self, *a):
            pass

    monkeypatch.setattr(mod, "_new_socket", make_sock)
    monkeypatch.setattr(mod, "_ReaderThread", DummyThread)
    return holder


def _opts(sock, opt):
    return [o for o in sock.opts if o[1] == opt]


def test_multicast_joins_group(fake_net):
    ch = UdpChannel("s")
    ch.open({
        "host": "239.0.0.1", "port": 5000, "local_port": 5000,
        "multicast": True, "multicast_group": "239.0.0.1",
    })
    sock = fake_net["sock"]
    assert _opts(sock, socket.IP_ADD_MEMBERSHIP)
    assert sock.bound == ("", 5000)
    assert ch._target == ("239.0.0.1", 5000)


def test_multicast_shared_addr(fake_net):
    ch = UdpChannel("s")
    ch.open({"host": "x", "port": 5001, "multicast": True,
             "multicast_group": "239.1.1.1"})
    sock = fake_net["sock"]
    assert _opts(sock, socket.SO_REUSEADDR)
    assert sock.bound == ("", 5001)


def test_multicast_requires_group(fake_net):
    ch = UdpChannel("s")
    errors = []
    ch.error_occurred.connect(errors.append)
    ch.open({"host": "x", "port": 5002, "multicast": True, "multicast_group": ""})
    assert errors  # 报错且不崩溃


def test_plain_unicast_unchanged(fake_net):
    ch = UdpChannel("s")
    ch.open({"host": "127.0.0.1", "port": 6000})
    sock = fake_net["sock"]
    assert not _opts(sock, socket.IP_ADD_MEMBERSHIP)
    assert sock.bound is None  # 未指定本地端口则不绑定
    assert ch._target == ("127.0.0.1", 6000)


def test_broadcast_sets_option(fake_net):
    ch = UdpChannel("s")
    ch.open({"host": "255.255.255.255", "port": 6001, "broadcast": True})
    assert _opts(fake_net["sock"], socket.SO_BROADCAST)


def test_send_uses_target(fake_net):
    ch = UdpChannel("s")
    ch.open({"host": "239.0.0.1", "port": 6002, "multicast": True,
             "multicast_group": "239.0.0.1"})
    ch.send(b"hi")
    assert fake_net["sock"].sent == [(b"hi", ("239.0.0.1", 6002))]
