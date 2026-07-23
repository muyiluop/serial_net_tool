"""应用入口。"""
import os
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from .main_window import MainWindow
from .core.config import Config
from .core.i18n import set_language
from .core.theme import apply_theme
from .core.autoreply import AutoReplyEngine, ReplyRule
from .core.plugin_manager import PluginManager
from .core.telemetry import get_telemetry


def _resource_path(relative_path: str) -> str:
    """获取资源绝对路径，兼容开发环境与 PyInstaller 打包。"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(_resource_path("resources/icon.ico")))
    config = Config()
    set_language(config.get("language", "zh"))
    apply_theme(app, config.get("theme", "dark"))

    autoreply = AutoReplyEngine()
    autoreply.set_rules([ReplyRule(**r) for r in config.get("autoreply_rules", [])])

    plugins = PluginManager(config)
    plugins.discover()

    # 遥测：记录应用启动
    telemetry = get_telemetry(config)
    telemetry.record("app_launch")
    telemetry.record("plugin_loaded", len(plugins.plugins))

    win = MainWindow(config, autoreply, plugins)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
