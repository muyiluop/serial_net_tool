"""插件管理器：发现内置与用户插件，提供工具面板扩展点。

扩展约定（二选一或并用，模块属性优先于 manifest）：
  插件包 __init__.py 可定义：
    NAME = "插件名"                      # 必须（或由 plugin.json 提供）
    VERSION / AUTHOR / DESCRIPTION       # 可选元信息
    TOOL_TYPE = "dock" | "window"         # 可选，默认 "dock"
    ENABLE = True|False                   # 可选，默认 True
    create_widget(ctx=None) -> QWidget    # 必须，ctx 为 MainWindow 引用

  也可在插件目录放置 plugin.json（可选 manifest）：
    {
      "id": "my_plugin",
      "name": "My Plugin",
      "version": "1.0",
      "author": "...",
      "description": "...",
      "tool_type": "dock" | "window",
      "entry": "create_widget",           # 入口函数名，默认 create_widget
      "min_app_version": "0.1.0"          # 可选，低于此版本则拒绝加载
    }

加载失败隔离，不影响主程序。
"""

import os
import importlib
import importlib.util
import json
import traceback

from .. import __version__ as APP_VERSION
from .i18n import tr


def _parse_version(v) -> tuple:
    """把 '0.2.0' 之类版本串解析为可比较元组。"""
    parts = []
    for seg in str(v or "").split("."):
        num = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


class PluginManager:
    def __init__(self, config=None):
        self.plugins: list = []
        self.config = config

    def discover(self, extra_dirs=None):
        """扫描插件目录并加载，恢复持久化的禁用状态。"""
        self.plugins.clear()
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")
        dirs = [base]
        if extra_dirs:
            dirs += list(extra_dirs)
        for d in dirs:
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                pdir = os.path.join(d, name)
                init = os.path.join(pdir, "__init__.py")
                if os.path.isdir(pdir) and os.path.exists(init):
                    self._load(name, init, builtin=(d == base))
        # 恢复持久化的禁用状态
        if self.config:
            disabled = self.config.get("disabled_plugins", [])
            for p in self.plugins:
                if p["id"] in disabled:
                    p["enabled"] = False

    @staticmethod
    def _read_manifest(plugin_dir: str) -> dict:
        """读取可选的 plugin.json；缺失或非法时返回空 dict。"""
        path = os.path.join(plugin_dir, "plugin.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _load(self, pid, init_path, builtin):
        manifest = self._read_manifest(os.path.dirname(init_path))
        entry = {
            "id": manifest.get("id") or pid,
            "name": manifest.get("name") or pid,
            "version": manifest.get("version", ""),
            "author": manifest.get("author", ""),
            "description": manifest.get("description", ""),
            "enabled": True,
            "error": None,
            "widget_factory": None,
            "tool_type": manifest.get("tool_type", "dock"),
        }
        # manifest 声明的最低版本校验
        min_ver = manifest.get("min_app_version")
        if min_ver and _parse_version(APP_VERSION) < _parse_version(min_ver):
            entry["error"] = tr("plugin_min_version").format(min_ver, APP_VERSION)
            self.plugins.append(entry)
            return
        try:
            if builtin:
                mod = importlib.import_module(f"serial_net_tool.plugins.{pid}")
            else:
                spec = importlib.util.spec_from_file_location(
                    f"user_plugin_{pid}", init_path
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            # 模块属性优先，manifest 兜底
            entry["name"] = getattr(mod, "NAME", None) or entry["name"]
            entry["version"] = getattr(mod, "VERSION", entry["version"])
            entry["author"] = getattr(mod, "AUTHOR", entry["author"])
            entry["description"] = getattr(mod, "DESCRIPTION", entry["description"])
            entry["tool_type"] = getattr(mod, "TOOL_TYPE", entry["tool_type"])
            entry["widget_factory"] = getattr(mod, "create_widget", None)
            # manifest 可指定入口函数名
            entry_name = manifest.get("entry")
            if entry_name:
                fn = getattr(mod, entry_name, None)
                if callable(fn):
                    entry["widget_factory"] = fn
            entry["enabled"] = bool(getattr(mod, "ENABLE", True))
            if entry["widget_factory"] is None:
                entry["error"] = tr("plugin_missing_entry")
        except Exception:
            entry["error"] = traceback.format_exc()
        self.plugins.append(entry)

    # ---- 分类访问 ----

    def dock_widgets(self, context=None):
        """返回 [(name, widget), ...]，仅 tool_type=="dock" 的已启用插件。"""
        out = []
        for p in self.plugins:
            if (
                p.get("enabled")
                and p.get("widget_factory")
                and not p.get("error")
                and p.get("tool_type") == "dock"
            ):
                try:
                    out.append((p["name"], p["widget_factory"](context)))
                except Exception as e:
                    p["error"] = str(e)
        return out

    def window_entries(self):
        """返回 [{id, name, factory}, ...]，仅 tool_type=="window" 的已启用插件。"""
        out = []
        for p in self.plugins:
            if (
                p.get("enabled")
                and p.get("widget_factory")
                and not p.get("error")
                and p.get("tool_type") == "window"
            ):
                out.append(
                    {"id": p["id"], "name": p["name"], "factory": p["widget_factory"]}
                )
        return out

    def tool_widgets(self, context=None):
        """向后兼容：等同于 dock_widgets()。"""
        return self.dock_widgets(context)
