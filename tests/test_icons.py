"""自绘 SVG 图标集与主题联动测试。"""
import os

import pytest

from serial_net_tool.core import icons
from serial_net_tool.core.theme import apply_theme, icon, icon_pixmap, tokens

# 界面实际使用的图标清单（缺失会导致按钮无图）
REQUIRED = {
    # 会话类型
    "serial", "tcp_client", "tcp_server", "udp", "mqtt", "modbus",
    # 操作
    "add", "play", "pause", "stop", "refresh", "clear", "export", "import",
    "search", "settings", "plugin", "send", "file", "copy", "check", "rename", "list",
    # 方向 / 状态 / 导航
    "tx", "rx", "warn", "error", "info", "chevron_down", "chevron_right", "dot",
}


def test_required_icons_present():
    missing = REQUIRED - set(icons.names())
    assert not missing, f"缺少图标: {sorted(missing)}"


def test_all_icons_render(qt_app):
    for name in icons.names():
        pm = icons.pixmap(name, "#d0d0d0", 16)
        assert not pm.isNull(), f"{name} 渲染为空"
        assert pm.width() == 16 and pm.height() == 16


def test_aliases_resolve(qt_app):
    for alias in ("close", "delete", "trash", "save", "ok", "change_file"):
        assert icons.has(alias)
        assert not icons.pixmap(alias, "#ffffff", 16).isNull()


def test_unknown_icon_raises():
    with pytest.raises(KeyError):
        icons.svg("__definitely_missing__", "#ffffff")


def test_vector_scales_to_requested_size(qt_app):
    # SVG 矢量图标可按任意尺寸栅格化
    assert icons.pixmap("send", "#ffffff", 48).width() == 48
    assert icons.pixmap("send", "#ffffff", 16).width() == 16


def test_svg_embeds_color():
    svg = icons.svg("serial", "#123456")
    assert "#123456" in svg and svg.startswith("<svg")


def test_theme_icon_color_follows_theme(qt_app):
    try:
        apply_theme(qt_app, "dark")
        dark = icons.svg("serial", tokens()["text"])
        assert not icon("serial").isNull()
        assert not icon_pixmap("serial").isNull()

        apply_theme(qt_app, "light")
        light = icons.svg("serial", tokens()["text"])
        assert dark != light, "图标颜色应随主题变化"
    finally:
        apply_theme(qt_app, "dark")


def test_icon_paths_are_cached(qt_app):
    p1 = icons.svg_path("serial", "#abcdef")
    p2 = icons.svg_path("serial", "#abcdef")
    assert p1 == p2 and os.path.isfile(p1)
