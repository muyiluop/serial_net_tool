"""应用入口。"""
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .core.config import Config
from .core.i18n import set_language
from .core.theme import apply_theme
from .core.autoreply import AutoReplyEngine, ReplyRule
from .core.plugin_manager import PluginManager
from .core.telemetry import get_telemetry


def main():
    app = QApplication(sys.argv)
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
