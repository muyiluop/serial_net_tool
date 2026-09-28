"""TCP 服务端：客户端列表与定向发送。"""
from serial_net_tool.core.tcpudp_channel import TcpServerChannel


class FakeSock:
    def __init__(self):
        self.buf = b""

    def sendall(self, data):
        self.buf += data


class FakeReader:
    def __init__(self):
        self.sock = FakeSock()


def _channel_with(*tags):
    ch = TcpServerChannel("s")
    ch._clients = {t: FakeReader() for t in tags}
    ch._reassemblers = {t: None for t in tags}
    return ch


def test_peers_list():
    ch = _channel_with("a", "b")
    assert set(ch.peers()) == {"a", "b"}


def test_send_broadcast_by_default():
    ch = _channel_with("a", "b")
    ch.send(b"x")
    assert ch._clients["a"].sock.buf == b"x"
    assert ch._clients["b"].sock.buf == b"x"


def test_send_targeted():
    ch = _channel_with("a", "b")
    ch.send(b"y", target="a")
    assert ch._clients["a"].sock.buf == b"y"
    assert ch._clients["b"].sock.buf == b""


def test_peers_changed_on_close():
    ch = _channel_with("a", "b")
    seen = []
    ch.peers_changed.connect(lambda peers: seen.append(list(peers)))
    ch._on_client_close("a")
    assert seen and seen[-1] == ["b"]
    assert ch.peers() == ["b"]


def test_widget_targeted_send(qt_app, tmp_config):
    from serial_net_tool.core.autoreply import AutoReplyEngine
    from serial_net_tool.ui.recv_send import RecvSendWidget

    w = RecvSendWidget(AutoReplyEngine(), tmp_config, "tcp_server")
    ch = _channel_with("a", "b")
    w.bind(ch)
    # 全部 + 2 个客户端
    assert w.peer_cb.count() == 3

    w.peer_cb.setCurrentIndex(1)  # 指向 "a"
    w.send.setPlainText("AA")
    w._do_send()
    assert ch._clients["a"].sock.buf == b"AA"
    assert ch._clients["b"].sock.buf == b""

    w.peer_cb.setCurrentIndex(0)  # 全部客户端
    w._do_send()
    assert ch._clients["b"].sock.buf == b"AA"

    w.unbind()
    assert w._peer_picker_active is False
