"""串口通道：pyserial + 工作线程读取。"""
import serial
from PySide6.QtCore import QThread, Signal

from .channel import Channel, ChannelStatus
from .i18n import tr


class SerialWorker(QThread):
    data_received = Signal(bytes)
    opened = Signal()
    port_error = Signal(str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._ser = None
        self._stop = False

    def run(self):
        try:
            self._ser = serial.Serial(
                port=self.cfg["port"],
                baudrate=int(self.cfg.get("baud", 9600)),
                bytesize=int(self.cfg.get("bytesize", 8)),
                parity=self.cfg.get("parity", "N"),
                stopbits=float(self.cfg.get("stopbits", 1)),
                xonxoff=bool(self.cfg.get("xonxoff", False)),
                rtscts=bool(self.cfg.get("rtscts", False)),
                timeout=0.05,
            )
        except Exception as e:
            self.port_error.emit(str(e))
            return
        self.opened.emit()
        while not self._stop:
            try:
                n = self._ser.in_waiting
                if n:
                    self.data_received.emit(self._ser.read(n))
            except Exception as e:
                self.port_error.emit(str(e))
                break
            self.msleep(10)
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        except Exception:
            pass

    def write(self, data: bytes):
        if self._ser and self._ser.is_open:
            try:
                self._ser.write(data)
            except Exception as e:
                self.port_error.emit(str(e))

    def stop(self):
        self._stop = True


class SerialChannel(Channel):
    def open(self, cfg: dict):
        self.status = ChannelStatus.CONNECTING
        self._worker = SerialWorker(cfg, self)
        self._worker.data_received.connect(self._on_data)
        self._worker.port_error.connect(self._on_err)
        self._worker.opened.connect(lambda: self._set_connected())
        self._worker.start()

    def _set_connected(self):
        self.status = ChannelStatus.CONNECTED
        self.emit_log("INFO", tr("serial_opened"))

    def _on_data(self, data: bytes):
        self.emit_received(data, {"dir": "in"})

    def _on_err(self, msg: str):
        self.emit_error(msg)
        self.status = ChannelStatus.ERROR

    def close(self):
        if hasattr(self, "_worker"):
            self._worker.stop()
            self._worker.wait(2000)
        self.status = ChannelStatus.DISCONNECTED
        self.emit_log("INFO", tr("serial_closed"))

    def send(self, data: bytes):
        if hasattr(self, "_worker"):
            self._worker.write(data)
