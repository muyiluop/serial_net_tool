"""插件管理器：发现内置与用户插件，提供工具面板扩展点。

扩展约定：插件包 __init__.py 定义：
  NAME = "插件名"                      # 必须
  create_widget(ctx=None) -> QWidget   # 必须，ctx 为 MainWindow 引用
  TOOL_TYPE = "dock" | "window"         # 可选，默认 "dock"
    - "dock": widget 嵌入右侧 Dock 面板 Tab（需适配 240-340px 宽度）
    - "window": widget 由框架包装为独立 QDialog 窗口（适合复杂工具）

加载失败隔离，不影响主程序。
"""

import os
import importlib
import importlib.util
import traceback


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

    def _load(self, pid, init_path, builtin):
        entry = {
            "id": pid,
            "name": pid,
            "enabled": True,
            "error": None,
            "widget_factory": None,
            "tool_type": "dock",
        }
        try:
            if builtin:
                mod = importlib.import_module(f"serial_net_tool.plugins.{pid}")
            else:
                spec = importlib.util.spec_from_file_location(
                    f"user_plugin_{pid}", init_path
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            entry["name"] = getattr(mod, "NAME", pid)
            entry["widget_factory"] = getattr(mod, "create_widget", None)
            entry["tool_type"] = getattr(mod, "TOOL_TYPE", "dock")
            entry["enabled"] = getattr(mod, "ENABLE", True)
            if entry["widget_factory"] is None:
                entry["error"] = "未定义 create_widget"
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
