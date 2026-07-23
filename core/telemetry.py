"""隐私遥测框架（T9.3）。

设计原则：
- 默认关闭，用户在设置中显式开启
- 仅收集匿名使用统计：启动次数、各会话类型使用次数、工具面板使用次数
- 绝不包含任何通信报文、地址、凭据等敏感数据
- 数据本地存储，用户可随时查看和清除
"""
import json
import os
import time
from datetime import datetime


class TelemetryCollector:
    """匿名遥测数据收集器。"""

    # 统计的事件类型
    EVENTS = (
        "app_launch",          # 应用启动次数
        "session_serial",      # 串口会话创建
        "session_tcp_client",  # TCP 客户端
        "session_tcp_server",  # TCP 服务端
        "session_udp",         # UDP
        "session_mqtt",        # MQTT
        "session_modbus",      # Modbus
        "tool_crc",            # CRC 工具使用
        "tool_checksum",       # 校验和使用
        "tool_convert",        # 进制转换使用
        "tool_hex_to_file",    # Hex转文件使用
        "tool_autoreply",      # 自动回复使用
        "file_send",           # 文件发送次数
        "plugin_loaded",       # 插件加载数
    )

    def __init__(self, config=None):
        self.config = config
        self._data: dict = {}
        self._load()

    def _get_path(self) -> str:
        """获取遥测数据存储路径。"""
        return os.path.join(
            os.path.expanduser("~"),
            ".serial_net_tool",
            "telemetry.json",
        )

    def _load(self):
        """从磁盘加载遥测数据。"""
        path = self._get_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception:
            self._data = {}
        # 确保所有事件类型都有初始值
        for evt in self.EVENTS:
            if evt not in self._data:
                self._data[evt] = 0
        if "first_launch" not in self._data:
            self._data["first_launch"] = datetime.now().isoformat()
        if "last_launch" not in self._data:
            self._data["last_launch"] = datetime.now().isoformat()

    def _save(self):
        """保存遥测数据到磁盘。"""
        path = self._get_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # 遥测失败不影响主程序

    def is_enabled(self) -> bool:
        """遥测是否启用。"""
        if self.config:
            return bool(self.config.get("telemetry", False))
        return False

    def record(self, event: str, count: int = 1):
        """记录一次事件。仅当遥测启用时才记录。"""
        if not self.is_enabled():
            return
        if event not in self.EVENTS:
            return
        self._data[event] = self._data.get(event, 0) + count
        self._data["last_launch"] = datetime.now().isoformat()
        self._save()

    def record_session(self, kind: str):
        """记录创建会话事件。"""
        key = f"session_{kind}"
        self.record(key)

    def get_stats(self) -> dict:
        """获取统计数据的只读副本。"""
        return dict(self._data)

    def get_summary(self) -> str:
        """获取人类可读的统计摘要。"""
        d = self._data
        lines = [
            f"First Launch: {d.get('first_launch', 'N/A')}",
            f"Last Launch: {d.get('last_launch', 'N/A')}",
            f"App Launches: {d.get('app_launch', 0)}",
            "",
            "Sessions:",
        ]
        for k in ("session_serial", "session_tcp_client", "session_tcp_server",
                   "session_udp", "session_mqtt", "session_modbus"):
            lines.append(f"  {k}: {d.get(k, 0)}")
        lines.append("")
        lines.append("Tools:")
        for k in ("tool_crc", "tool_checksum", "tool_convert",
                   "tool_hex_to_file", "tool_autoreply", "file_send"):
            lines.append(f"  {k}: {d.get(k, 0)}")
        return "\n".join(lines)

    def clear(self):
        """清除所有遥测数据。"""
        self._data = {}
        for evt in self.EVENTS:
            self._data[evt] = 0
        self._data["first_launch"] = datetime.now().isoformat()
        self._data["last_launch"] = datetime.now().isoformat()
        self._save()

    def export_file(self, path: str):
        """导出遥测数据到文件。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)


# 全局单例（懒加载）
_instance: TelemetryCollector | None = None


def get_telemetry(config=None) -> TelemetryCollector:
    """获取全局遥测收集器实例。"""
    global _instance
    if _instance is None:
        _instance = TelemetryCollector(config)
    return _instance
