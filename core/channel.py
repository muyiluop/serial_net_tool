"""通信通道统一抽象层。
所有通道（串口/TCP/UDP/MQTT/插件）继承 Channel，对外暴露统一信号与接口，
具体 I/O 在各自 worker 线程中执行，避免阻塞 UI。
"""
from abc import ABC, abstractmethod
from enum import Enum
from PySide6.QtCore import QObject, Signal

from .i18n import tr


class ChannelStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    LISTENING = "listening"
    ERROR = "error"
    RECONNECTING = "reconnecting"

    @property
    def label(self) -> str:
        return {
            ChannelStatus.DISCONNECTED: tr("disconnected"),
            ChannelStatus.CONNECTING: tr("connecting"),
            ChannelStatus.CONNECTED: tr("connected"),
            ChannelStatus.LISTENING: tr("listening"),
            ChannelStatus.ERROR: tr("error"),
            ChannelStatus.RECONNECTING: tr("reconnecting"),
        }[self]


class Channel(QObject):
    # 收到数据：payload(bytes) + meta(dict, 可选 note/方向等)
    received = Signal(bytes, dict)
    # 状态变化
    status_changed = Signal(ChannelStatus)
    # 错误描述
    error_occurred = Signal(str)
    # 日志：级别, 消息
    log_message = Signal(str, str)

    def __init__(self, session_id: str, parent: QObject | None = None):
        super().__init__(parent)
        self.session_id = session_id
        self._status = ChannelStatus.DISCONNECTED

    @property
    def status(self) -> ChannelStatus:
        return self._status

    @status.setter
    def status(self, value: ChannelStatus):
        self._status = value
        self.status_changed.emit(value)

    @abstractmethod
    def open(self, cfg: dict) -> None:
        """按配置建立连接/启动监听。"""
        ...

    @abstractmethod
    def close(self) -> None:
        """关闭连接/停止监听并释放资源。"""
        ...

    @abstractmethod
    def send(self, data: bytes) -> None:
        """发送字节数据。"""
        ...

    def emit_received(self, data: bytes, meta: dict | None = None) -> None:
        self.received.emit(data, meta or {})

    def emit_error(self, msg: str) -> None:
        self.error_occurred.emit(msg)
        self.log_message.emit("ERROR", msg)

    def emit_log(self, level: str, msg: str) -> None:
        self.log_message.emit(level, msg)
