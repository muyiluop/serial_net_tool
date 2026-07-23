"""全局配置与会话持久化（JSON）。"""
import json
import os
from typing import Any


class Config:
    DEFAULTS = {
        "language": "zh",
        "theme": "dark",
        "telemetry": False,
        "rx_timestamp": False,
        "tx_newline": True,
        "default_encoding": "utf-8",
        "sessions": [],
        "disabled_plugins": ["modbus_tool"],  # Modbus 插件默认禁用
    }

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(
            os.path.expanduser("~"), ".serial_net_tool", "config.json"
        )
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
        except Exception as e:  # 损坏配置不致命
            print(f"[Config] load failed, using defaults: {e}")

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Config] save failed: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    # —— 整份配置导入/导出（便于团队共享）——
    def export_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def import_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        self.save()

    def add_session(self, session: dict) -> None:
        self.data.setdefault("sessions", [])
        self.data["sessions"].append(session)
        self.save()

    def remove_session(self, session_id: str) -> None:
        self.data["sessions"] = [
            s for s in self.data.get("sessions", []) if s.get("id") != session_id
        ]
        self.save()
