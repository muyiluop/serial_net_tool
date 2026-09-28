"""TCP/UDP 通道：
- TcpClientChannel：单连接客户端
- TcpServerChannel：监听 + 多子连接管理
- UdpChannel：单播/广播/组播
"""
import socket
from PySide6.QtCore import QThread, Signal, QTimer

from .channel import Channel, ChannelStatus
from .packet_reassembler import PacketReassembler
from .i18n import tr

def _new_socket(udp: bool = False) -> socket.socket:
    return socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
    )


class _ReaderThread(QThread):
    data_received = Signal(bytes, dict)
    closed = Signal(str)
    error = Signal(str)

    def __init__(self, sock: socket.socket, tag: str = "", parent=None):
        super().__init__(parent)
        self.sock = sock
        self.tag = tag
        self._stop = False

    def run(self):
        self.sock.settimeout(0.2)
        while not self._stop:
            try:
                data, addr = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                self.closed.emit(self.tag)
                break
            self.data_received.emit(data, {"dir": "in", "peer": self.tag or (addr[0] if addr else "")})
        self._stop = True

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass


class TcpClientChannel(Channel):
    def open(self, cfg: dict):
        self.status = ChannelStatus.CONNECTING
        host, port = cfg["host"], int(cfg["port"])
        sock = _new_socket()
        try:
            sock.connect((host, port))
        except Exception as e:
            self.emit_error(str(e))
            self.status = ChannelStatus.ERROR
            return
        self.status = ChannelStatus.CONNECTED
        # 粘包重组
        self._peer = f"{host}:{port}"
        self._reassembler = _make_reassembler(cfg)
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start(20)
        self._reader = _ReaderThread(sock, self._peer, self)
        self._reader.data_received.connect(self._on_data)
        self._reader.closed.connect(lambda _: self._on_closed())
        self._reader.start()

    def _on_data(self, data, meta):
        frames = self._reassembler.on_data(data)
        for frame in frames:
            self.emit_received(frame, meta)

    def _check_idle(self):
        for frame in self._reassembler.check_idle():
            self.emit_received(frame, {"dir": "in", "peer": self._peer})

    def _on_closed(self):
        # flush 残留
        for frame in self._reassembler.flush():
            self.emit_received(frame, {"dir": "in", "peer": self._peer})
        self.status = ChannelStatus.DISCONNECTED
        self.emit_log("WARN", tr("tcp_peer_closed"))

    def close(self):
        if hasattr(self, "_idle_timer"):
            self._idle_timer.stop()
        if hasattr(self, "_reader"):
            self._reader.stop()
            self._reader.wait(2000)
        self.status = ChannelStatus.DISCONNECTED

    def send(self, data: bytes):
        if hasattr(self, "_reader"):
            try:
                self._reader.sock.sendall(data)
            except Exception as e:
                self.emit_error(str(e))


class TcpServerChannel(Channel):
    # 已连接客户端列表变化（供 UI 选择发送目标）
    peers_changed = Signal(list)

    def open(self, cfg: dict):
        self.status = ChannelStatus.CONNECTING
        port = int(cfg["port"])
        self._cfg = cfg
        self._sock = _new_socket()
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("0.0.0.0", port))
            self._sock.listen(5)
        except Exception as e:
            self.emit_error(str(e))
            self.status = ChannelStatus.ERROR
            return
        self.status = ChannelStatus.LISTENING
        self._clients: dict[str, _ReaderThread] = {}
        self._reassemblers: dict[str, PacketReassembler] = {}
        # idle 检测定时器（timeout 模式需要）
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start(20)
        self._acceptor = _Acceptor(self._sock, self)
        self._acceptor.accepted.connect(self._on_accept)
        self._acceptor.error.connect(self.emit_error)
        self._acceptor.start()

    def _check_idle(self):
        """timeout 模式下，检查所有客户端的空闲超时。"""
        for tag, r in list(self._reassemblers.items()):
            for frame in r.check_idle():
                self.emit_received(frame, {"dir": "in", "peer": tag})

    def _on_accept(self, sock: socket.socket, addr):
        tag = f"{addr[0]}:{addr[1]}"
        r = _ReaderThread(sock, tag, self)
        r.data_received.connect(lambda d, m, t=tag: self._on_client_data(d, m, t))
        r.closed.connect(lambda t=tag: self._on_client_close(t))
        r.start()
        self._clients[tag] = r
        # 每个客户端一个重组器
        self._reassemblers[tag] = _make_reassembler(self._cfg)
        self.emit_log("INFO", tr("client_connected").format(tag))
        self.peers_changed.emit(self.peers())

    def peers(self) -> list:
        """当前已连接客户端标识列表。"""
        return list(getattr(self, "_clients", {}).keys())

    def _on_client_data(self, data, meta, tag: str):
        r = self._reassemblers.get(tag)
        if r:
            for frame in r.on_data(data):
                self.emit_received(frame, {**meta, "peer": tag})
        else:
            self.emit_received(data, {**meta, "peer": tag})

    def _on_client_close(self, tag: str):
        # flush 残留
        r = self._reassemblers.pop(tag, None)
        if r:
            for frame in r.flush():
                self.emit_received(frame, {"dir": "in", "peer": tag})
        self._clients.pop(tag, None)
        self.emit_log("WARN", tr("client_disconnected").format(tag))
        self.peers_changed.emit(self.peers())

    def close(self):
        if hasattr(self, "_idle_timer"):
            self._idle_timer.stop()
        reassemblers = getattr(self, "_reassemblers", {})
        for tag, r in getattr(self, "_clients", {}).items():
            # flush 残留
            reasm = reassemblers.get(tag)
            if reasm:
                for frame in reasm.flush():
                    self.emit_received(frame, {"dir": "in", "peer": tag})
            r.stop()
            r.wait(1000)
        reassemblers.clear()
        if hasattr(self, "_acceptor"):
            self._acceptor.stop()
            self._acceptor.wait(2000)
        self.status = ChannelStatus.DISCONNECTED

    def send(self, data: bytes, target: str | None = None):
        if not hasattr(self, "_clients"):
            return
        for tag, r in self._clients.items():
            if target is None or tag == target:
                try:
                    r.sock.sendall(data)
                except Exception as e:
                    self.emit_error(str(e))


class _Acceptor(QThread):
    accepted = Signal(object, tuple)
    error = Signal(str)

    def __init__(self, sock, parent=None):
        super().__init__(parent)
        self.sock = sock
        self._stop = False

    def run(self):
        self.sock.settimeout(0.5)
        while not self._stop:
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.accepted.emit(conn, addr)
        self._stop = True

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass


class UdpChannel(Channel):
    def open(self, cfg: dict):
        self.status = ChannelStatus.CONNECTING
        self._sock = _new_socket(udp=True)
        port = int(cfg["port"])
        local_port = int(cfg.get("local_port", 0) or 0)
        is_mcast = bool(cfg.get("multicast"))
        group = (cfg.get("multicast_group", "") or "").strip()
        iface = (cfg.get("multicast_iface", "") or "").strip()
        try:
            if is_mcast or local_port:
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if is_mcast:
                if not group:
                    raise ValueError("multicast group required")
                # 绑定组播端口以接收组内数据
                self._sock.bind(("", local_port or port))
                mreq = socket.inet_aton(group) + socket.inet_aton(iface or "0.0.0.0")
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            elif local_port:
                self._sock.bind(("0.0.0.0", local_port))
        except Exception as e:
            self.emit_error(str(e))
            self.status = ChannelStatus.ERROR
            return
        self._target = (group if is_mcast else cfg["host"], port)
        if cfg.get("broadcast"):
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.status = ChannelStatus.CONNECTED
        self._reader = _ReaderThread(self._sock, "", self)
        self._reader.data_received.connect(self._on_data)
        self._reader.start()

    def _on_data(self, data, meta):
        self.emit_received(data, meta)

    def close(self):
        if hasattr(self, "_reader"):
            self._reader.stop()
            self._reader.wait(2000)
        self.status = ChannelStatus.DISCONNECTED

    def send(self, data: bytes):
        if hasattr(self, "_sock"):
            try:
                self._sock.sendto(data, self._target)
            except Exception as e:
                self.emit_error(str(e))


def _make_reassembler(cfg: dict) -> PacketReassembler:
    """根据会话配置创建粘包重组器。"""
    mode = cfg.get("pkt_mode", "none")
    if mode == "none":
        return PacketReassembler(mode="none")
    elif mode == "timeout":
        return PacketReassembler(
            mode="timeout",
            idle_timeout_ms=int(cfg.get("pkt_idle_ms", 50)),
        )
    elif mode == "delimiter":
        delim_str = cfg.get("pkt_delimiter", "0D 0A")
        delim_bytes = bytes.fromhex("".join(delim_str.split()))
        return PacketReassembler(
            mode="delimiter",
            delimiter=delim_bytes,
            include_delimiter=bool(cfg.get("pkt_keep_delimiter", False)),
        )
    elif mode == "length_prefix":
        return PacketReassembler(
            mode="length_prefix",
            len_bytes=int(cfg.get("pkt_len_bytes", 2)),
            len_endian=cfg.get("pkt_len_endian", "big"),
            len_includes_header=bool(cfg.get("pkt_len_includes_header", False)),
        )
    return PacketReassembler(mode="none")
