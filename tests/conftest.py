"""pytest 全局配置：无头 Qt、包路径、通用 fixture。"""
import os
import sys

# 无显示环境（CI/容器）下也能构建 Qt 控件
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 使 serial_net_tool 包可被导入：把包所在目录的父目录加入 sys.path
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IMPORT_ROOT = os.path.dirname(_PROJECT_DIR)
if _IMPORT_ROOT not in sys.path:
    sys.path.insert(0, _IMPORT_ROOT)

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    """全测试会话共享一个 QApplication。"""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def tmp_config(tmp_path):
    """指向临时文件的 Config（不污染用户真实配置）。"""
    from serial_net_tool.core.config import Config

    return Config(str(tmp_path / "config.json"))
