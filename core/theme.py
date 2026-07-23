"""主题系统（深色默认 / 浅色 / 跟随系统），基于 QPalette + QSS，跨平台一致。

设计原则：
- 强制使用 Fusion 风格。Fusion 完全由 palette/QSS 驱动，能正确应用深色背景与文字色；
  默认的 WindowsVista/macOS 原生风格会忽略大量 QSS 背景与文字色，导致"深色下文字看不见"。
- 颜色由 QPalette 统一控制（文字、背景、高亮、按钮等），保证所有控件一致可见。
- QSS 由设计令牌（spacing/radius/color）生成，控件风格统一、精致。
- 箭头与勾选标记使用运行时生成的 SVG 图标，避免依赖 Fusion 默认渲染不可靠的问题。
- 暴露 direction_colors() / tokens()，供各面板按主题取色与一致间距。
- 支持 "system" 主题：自动检测操作系统深浅色偏好。
"""

import os
import sys
import tempfile

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor

_CURRENT = "dark"
_RESOLVED = "dark"  # system 解析后的实际值

# 通信日志方向标记配色（按主题分别取对比度良好的值）
_DARK_DIRECTION = ("#3fb950", "#58a6ff")  # (发送-绿, 接收-蓝)
_LIGHT_DIRECTION = ("#1a7f37", "#0969da")

# 状态色（用于会话树节点等，按主题区分保证对比度）
_DARK_STATUS = {
    "CONNECTED": "#4ec9b0",
    "LISTENING": "#569cd6",
    "ERROR": "#f48771",
    "RECONNECTING": "#dcdcaa",
    "CONNECTING": "#dcdcaa",
    "DISCONNECTED": "#888888",
}
_LIGHT_STATUS = {
    "CONNECTED": "#1a7f37",
    "LISTENING": "#0969da",
    "ERROR": "#d1242f",
    "RECONNECTING": "#9a6700",
    "CONNECTING": "#9a6700",
    "DISCONNECTED": "#6b7280",
}


def _detect_system_theme() -> str:
    """检测操作系统是否使用深色模式。"""
    try:
        from PySide6.QtGui import QGuiApplication

        # Qt 6.5+ 支持 colorScheme
        scheme = QGuiApplication.styleHints().colorScheme()
        return "dark" if scheme.value == 2 else "light"  # Qt.ColorScheme.Dark = 2
    except Exception:
        pass
    # 回退：检查环境变量 / 注册表
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if val == 1 else "dark"
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            import subprocess

            r = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return "dark" if "Dark" in r.stdout else "light"
        except Exception:
            pass
    return "dark"  # 默认深色


def current_theme() -> str:
    return _RESOLVED


def direction_colors() -> tuple:
    """返回 (发送色, 接收色)，已按当前主题优化对比度。"""
    return _DARK_DIRECTION if _RESOLVED == "dark" else _LIGHT_DIRECTION


def status_colors() -> dict:
    """返回状态色映射表，按主题区分。"""
    return _DARK_STATUS if _RESOLVED == "dark" else _LIGHT_STATUS


# ---------------------------------------------------------------------------
# SVG 图标生成 —— QStyleSheetStyle 激活后默认箭头渲染不可靠，
# 用显式 SVG 文件 + image: url() 确保箭头/勾选标记在所有主题下都清晰可见。
# ---------------------------------------------------------------------------
_SVG_CACHE: dict = {}


def _svg_path(name: str, color: str) -> str:
    """生成/缓存一个 SVG 图标文件，返回 QSS 可用的 url() 路径（正斜杠）。"""
    key = (name, color)
    if key in _SVG_CACHE:
        p = _SVG_CACHE[key]
        if os.path.isfile(p):
            return p

    shapes = {
        "up": '<path d="M2 7 L9 7 L5.5 2.5 Z" fill="{c}"/>',
        "down": '<path d="M2 2 L9 2 L5.5 6.5 Z" fill="{c}"/>',
        "left": '<path d="M7 1.5 L2 5 L7 8.5 Z" fill="{c}"/>',
        "right": '<path d="M3 1.5 L8 5 L3 8.5 Z" fill="{c}"/>',
        "check": '<path d="M3 7 L5.5 9.5 L11 3.5" stroke="{c}" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    }
    tmpl = shapes.get(name, "")
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="10">{tmpl.format(c=color)}</svg>'
    safe_color = color.lstrip("#")
    out_dir = os.path.join(tempfile.gettempdir(), "snt_icons")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        out_dir = tempfile.gettempdir()
    path = os.path.join(out_dir, f"{name}_{safe_color}.svg")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    except OSError:
        return ""
    # QSS url() 要求正斜杠
    path = path.replace("\\", "/")
    _SVG_CACHE[key] = path
    return path


def _tokens(dark: bool) -> dict:
    if dark:
        return dict(
            # 背景层
            window="#1e1e1e",
            panel="#252526",
            panel_alt="#2d2d30",
            border="#3c3c3c",
            border_soft="#333333",
            # 文字层
            text="#d4d4d4",
            text_dim="#9a9a9a",
            text_inv="#ffffff",
            # 强调色
            accent="#4ec9b0",
            accent_soft="#2ea18c",
            accent_text="#06231d",
            primary="#0e639c",
            primary_hov="#1177bb",
            sel="#094771",
            sel_hover="#2a2d2e",
            # 状态色
            ok="#4ec9b0",
            err="#f48771",
            warn="#dcdcaa",
            info="#569cd6",
            recv_bg="#1b1b1b",
            # 间距令牌
            sp_grid_h="14px",
            sp_grid_v="8px",
            sp_card_pad="12px",
            sp_ctrl_pad_h="8px",
            sp_ctrl_pad_v="5px",
            sp_btn_h="6px",
            sp_btn_w="16px",
            r_sm="4px",
            r_md="6px",
            r_lg="8px",
            # 侧边栏
            sidebar_bg="#252526",
            sidebar_min="200px",
            sidebar_max="260px",
        )
    # 浅色模式
    return dict(
        # 背景层
        window="#f5f5f5",
        panel="#ffffff",
        panel_alt="#f0f0f0",
        border="#d1d5db",
        border_soft="#e5e7eb",
        # 文字层
        text="#1f2937",
        text_dim="#6b7280",
        text_inv="#ffffff",
        # 强调色
        accent="#0e7d6a",
        accent_soft="#0b5e50",
        accent_text="#ffffff",
        primary="#2563eb",
        primary_hov="#1d4ed8",
        sel="#3b82f6",
        sel_hover="#eff6ff",
        # 状态色
        ok="#16a34a",
        err="#dc2626",
        warn="#d97706",
        info="#2563eb",
        recv_bg="#fafbfc",
        # 间距令牌
        sp_grid_h="14px",
        sp_grid_v="8px",
        sp_card_pad="12px",
        sp_ctrl_pad_h="8px",
        sp_ctrl_pad_v="5px",
        sp_btn_h="6px",
        sp_btn_w="16px",
        r_sm="4px",
        r_md="6px",
        r_lg="8px",
        # 侧边栏
        sidebar_bg="#ffffff",
        sidebar_min="200px",
        sidebar_max="260px",
    )


def tokens() -> dict:
    """当前主题的设计令牌（颜色等）。"""
    return _tokens(_RESOLVED == "dark")


def _dark_palette() -> QPalette:
    t = _tokens(True)
    p = QPalette()
    p.setColor(QPalette.Window, QColor(t["window"]))
    p.setColor(QPalette.WindowText, QColor(t["text"]))
    p.setColor(QPalette.Base, QColor(t["panel"]))
    p.setColor(QPalette.AlternateBase, QColor(t["panel_alt"]))
    p.setColor(QPalette.Text, QColor(t["text"]))
    p.setColor(QPalette.PlaceholderText, QColor("#7a7a7a"))
    p.setColor(QPalette.BrightText, QColor(t["text_inv"]))
    p.setColor(QPalette.Highlight, QColor(t["sel"]))
    p.setColor(QPalette.HighlightedText, QColor(t["text_inv"]))
    p.setColor(QPalette.Button, QColor(t["panel_alt"]))
    p.setColor(QPalette.ButtonText, QColor(t["text"]))
    p.setColor(QPalette.Link, QColor(t["info"]))
    p.setColor(QPalette.ToolTipBase, QColor(t["panel"]))
    p.setColor(QPalette.ToolTipText, QColor(t["text"]))
    return p


def _light_palette() -> QPalette:
    t = _tokens(False)
    p = QPalette()
    p.setColor(QPalette.Window, QColor(t["window"]))
    p.setColor(QPalette.WindowText, QColor(t["text"]))
    p.setColor(QPalette.Base, QColor(t["panel"]))
    p.setColor(QPalette.AlternateBase, QColor(t["panel_alt"]))
    p.setColor(QPalette.Text, QColor(t["text"]))
    p.setColor(QPalette.PlaceholderText, QColor("#9ca3af"))
    p.setColor(QPalette.BrightText, QColor(t["text_inv"]))
    p.setColor(QPalette.Highlight, QColor(t["sel"]))
    p.setColor(QPalette.HighlightedText, QColor(t["text_inv"]))
    p.setColor(QPalette.Button, QColor("#e8eaed"))
    p.setColor(QPalette.ButtonText, QColor(t["text"]))
    p.setColor(QPalette.Link, QColor(t["info"]))
    p.setColor(QPalette.ToolTipBase, QColor(t["panel"]))
    p.setColor(QPalette.ToolTipText, QColor(t["text"]))
    return p


def _qss(dark: bool) -> str:
    t = _tokens(dark)
    # 运行时生成 SVG 箭头/勾选图标，确保 QStyleSheetStyle 下也能正确显示
    arrow_clr = t["text_dim"]
    check_clr = t["accent_text"]
    up_svg = _svg_path("up", arrow_clr)
    down_svg = _svg_path("down", arrow_clr)
    left_svg = _svg_path("left", arrow_clr)
    right_svg = _svg_path("right", arrow_clr)
    check_svg = _svg_path("check", check_clr)

    # 状态栏专属样式
    if dark:
        sb_bg = "#1a1a1a"
        sb_border = "#333333"
    else:
        sb_bg = "#ececec"
        sb_border = "#d1d5db"

    return f"""
    QWidget {{ font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 13px; }}
    QMainWindow, QDialog {{ background-color: {t["window"]}; }}
    QDockWidget {{ background-color: {t["panel"]}; color: {t["text"]}; titlebar-close-icon: none; }}
    QDockWidget::title {{
        background-color: {t["panel"]};
        color: {t["text"]};
        padding: 8px 10px;
        border-bottom: 1px solid {t["border"]};
        font-weight: 600;
    }}
    QToolBar {{
        background-color: {t["panel"]};
        border: none;
        border-bottom: 1px solid {t["border"]};
        spacing: 6px;
        padding: 6px;
    }}
    QMenuBar {{ background-color: {t["panel"]}; color: {t["text"]}; border-bottom: 1px solid {t["border"]}; }}
    QMenuBar::item {{ padding: 6px 12px; background: transparent; }}
    QMenuBar::item:selected {{ background: {t["sel_hover"]}; border-radius: 4px; }}
    QMenu {{ background-color: {t["panel"]}; color: {t["text"]}; border: 1px solid {t["border"]}; }}
    QMenu::item {{ padding: 6px 24px 6px 20px; }}
    QMenu::item:selected {{ background: {t["sel"]}; color: {t["text_inv"]}; }}

    /* ---------- 状态栏 ---------- */
    QStatusBar {{
        background-color: {sb_bg};
        color: {t["text_dim"]};
        border-top: 1px solid {sb_border};
        font-size: 12px;
        padding: 2px 8px;
    }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ color: {t["text_dim"]}; margin: 0 6px; }}
    QStatusBar QLabel#status_ok {{ color: {t["ok"]}; font-weight: 600; }}
    QStatusBar QLabel#status_err {{ color: {t["err"]}; font-weight: 600; }}

    /* ---------- 按钮 ---------- */
    QPushButton {{
        background-color: {t["primary"]};
        color: {t["text_inv"]};
        border: none;
        padding: {t["sp_btn_h"]} {t["sp_btn_w"]};
        border-radius: {t["r_md"]};
    }}
    QPushButton:hover {{ background-color: {t["primary_hov"]}; }}
    QPushButton:pressed {{ background-color: {t["primary"]}; }}
    QPushButton:disabled {{ background-color: {t["panel_alt"]}; color: {t["text_dim"]}; }}
    QPushButton#ghost {{
        background-color: transparent;
        color: {t["text"]};
        border: 1px solid {t["border"]};
    }}
    QPushButton#ghost:hover {{ background-color: {t["sel_hover"]}; border-color: {t["accent"]}; }}
    QPushButton#ghost:disabled {{ color: {t["text_dim"]}; border-color: {t["border_soft"]}; background-color: transparent; }}
    QPushButton#accent {{
        background-color: {t["accent"]};
        color: {t["accent_text"]};
        font-weight: 600;
    }}
    QPushButton#accent:hover {{ background-color: {t["accent_soft"]}; color: {t["text_inv"]}; }}
    QPushButton#accent:pressed {{ background-color: {t["accent_soft"]}; color: {t["text_inv"]}; }}
    QPushButton#accent:disabled {{ background-color: {t["panel_alt"]}; color: {t["text_dim"]}; }}

/* ---------- 卡片/分组 ---------- */
    QGroupBox {{
        background-color: {t["panel"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_lg"]};
        /* 核心修改：使用 3ex (大约3个字符高度) 动态适配高分屏，Qt官方推荐做法 */
        margin-top: 3ex; 
        padding: 10px 10px 8px 10px;
        font-weight: 600;
        color: {t["text"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        /* 核心修改：移除 top 属性，让 Qt 自己在 margin 区域内垂直居中 */
        padding: 0 5px;
        background-color: {t["panel"]};
        color: {t["text_dim"]};
        font-size: 12px;
        font-weight: 600;
    }}
    QFrame#card {{
        background-color: {t["panel"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_lg"]};
    }}
    QFrame#card:hover {{
        border-color: {t["accent"]};
    }}
    QFrame#collapsible_header {{
        background-color: {t["panel_alt"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_md"]};
    }}
    QFrame#collapsible_header:hover {{ border-color: {t["accent"]}; background-color: {t["sel_hover"]}; }}

    /* ---------- 输入控件 ---------- */
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
        background-color: {t["panel"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_md"]};
        padding: {t["sp_ctrl_pad_v"]} {t["sp_ctrl_pad_h"]};
        selection-background-color: {t["sel"]};
    }}
    QLineEdit {{ min-width: 80px; }}
    QSpinBox, QDoubleSpinBox {{ min-width: 70px; }}
    QComboBox {{ min-width: 90px; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 1px solid {t["accent"]};
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
        color: {t["text_dim"]};
        background-color: {t["panel_alt"]};
    }}
    /* ---------- SpinBox 上下箭头 ---------- */
    QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
    QComboBox {{ padding-right: 26px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 20px;
        border-left: 1px solid {t["border_soft"]};
        border-bottom: 1px solid {t["border_soft"]};
        border-top-right-radius: {t["r_md"]};
        background: {t["panel_alt"]};
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 20px;
        border-left: 1px solid {t["border_soft"]};
        border-bottom-right-radius: {t["r_md"]};
        background: {t["panel_alt"]};
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {t["sel_hover"]}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: url("{up_svg}");
        width: 12px; height: 10px;
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: url("{down_svg}");
        width: 12px; height: 10px;
    }}
    /* ---------- ComboBox 下拉按钮 ---------- */
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 24px;
        border-left: 1px solid {t["border_soft"]};
        border-top-right-radius: {t["r_md"]};
        border-bottom-right-radius: {t["r_md"]};
        background: {t["panel_alt"]};
    }}
    QComboBox::drop-down:hover {{ background: {t["sel_hover"]}; }}
    QComboBox::down-arrow {{
        image: url("{down_svg}");
        width: 12px; height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t["panel"]};
        color: {t["text"]};
        selection-background-color: {t["sel"]};
        selection-color: {t["text_inv"]};
        border: 1px solid {t["border"]};
        outline: 0;
        padding: 2px;
    }}
    QTextEdit#recv {{
        background-color: {t["recv_bg"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_md"]};
        font-family: Consolas, "Courier New", monospace;
        font-size: 12.5px;
        padding: 6px;
    }}

    /* ---------- 单选/复选 ---------- */
    QRadioButton, QCheckBox {{ spacing: 7px; color: {t["text"]}; background: transparent; }}
    QRadioButton::indicator {{ width: 16px; height: 16px; }}
    QRadioButton::indicator:unchecked {{
        border: 1.5px solid {t["border"]}; border-radius: 9px; background: transparent;
    }}
    QRadioButton::indicator:unchecked:hover {{ border-color: {t["accent"]}; }}
    QRadioButton::indicator:checked {{
        border: 1.5px solid {t["accent"]}; border-radius: 9px;
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                    stop:0 {t["accent"]}, stop:0.55 {t["accent"]}, stop:0.6 transparent);
    }}
    QRadioButton:checked {{ color: {t["accent"]}; font-weight: 600; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border: 1.5px solid {t["border"]};
        border-radius: {t["r_sm"]}; background: transparent;
    }}
    QCheckBox::indicator:hover {{ border-color: {t["accent"]}; }}
    QCheckBox::indicator:checked {{
        background: {t["accent"]};
        border: 1.5px solid {t["accent"]};
        border-radius: {t["r_sm"]};
        image: url("{check_svg}");
    }}
    QCheckBox::indicator:checked:disabled {{
        background: {t["border"]}; border-color: {t["border"]};
    }}

    /* ---------- 列表/树/表 ---------- */
    QTreeWidget, QListWidget, QTableWidget {{
        background-color: {t["panel"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_md"]};
        gridline-color: {t["border_soft"]};
        outline: 0;
        alternate-background-color: {t["panel_alt"]};
    }}
    QTreeWidget::item, QListWidget::item {{ padding: 5px 4px; border-radius: {t["r_sm"]}; }}
    QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {{
        background-color: {t["sel"]}; color: {t["text_inv"]};
    }}
    QTreeWidget::item:hover:!selected, QListWidget::item:hover:!selected {{
        background-color: {t["sel_hover"]};
    }}
    QHeaderView::section {{
        background-color: {t["panel_alt"]};
        color: {t["text"]};
        border: none;
        border-right: 1px solid {t["border_soft"]};
        border-bottom: 1px solid {t["border"]};
        padding: 6px;
        font-weight: 600;
    }}

    /* ---------- 标签页 ---------- */
    QTabWidget::pane {{
        border: 1px solid {t["border"]};
        border-radius: {t["r_lg"]};
        top: -1px;
        background: {t["panel"]};
    }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {t["text_dim"]};
        padding: 7px 16px;
        margin: 4px 2px 0px 2px;
        border: 1px solid transparent;
        border-radius: {t["r_md"]};
    }}
    QTabBar::tab:selected {{
        background: {t["sel"]};
        color: {t["text_inv"]};
    }}
    QTabBar::tab:hover:!selected {{
        background: {t["sel_hover"]};
        color: {t["text"]};
    }}
    /* 两侧溢出滚动箭头：做成小巧的幽灵按钮 */
    QTabBar QToolButton {{
        background: transparent;
        color: {t["text_dim"]};
        border: 1px solid transparent;
        border-radius: 5px;
        padding: 2px;
        margin: 4px 1px 0 1px;
    }}
    QTabBar QToolButton:hover {{ background: {t["sel_hover"]}; color: {t["text"]}; }}
    QTabBar QToolButton::right-arrow {{ image: url("{right_svg}"); width: 12px; height: 10px; }}
    QTabBar QToolButton::left-arrow {{ image: url("{left_svg}"); width: 12px; height: 10px; }}

    /* Dock 工具面板紧凑 Tab */
    QTabWidget#dock_tabs QTabBar::tab {{
        padding: 6px 10px;
        margin: 4px 1px 0px 1px;
    }}

    /* ---------- 状态徽标/标签 ---------- */
    QLabel {{ color: {t["text"]}; background: transparent; min-height: 18px; }}
    QLabel#dim {{ color: {t["text_dim"]}; }}
    QLabel#h1 {{ font-size: 15px; font-weight: 700; }}
    QLabel#badge_ok {{ color: {t["ok"]}; font-weight: 600; }}
    QLabel#badge_err {{ color: {t["err"]}; font-weight: 600; }}
    QLabel#badge_warn {{ color: {t["warn"]}; font-weight: 600; }}
    QLabel#status_ok {{ color: {t["ok"]}; font-weight: 600; }}
    QLabel#status_err {{ color: {t["err"]}; font-weight: 600; }}
    QLabel#stat {{ color: {t["text_dim"]}; font-family: Consolas, monospace; font-size: 12px; }}

    /* ---------- 其它 ---------- */
    QSplitter::handle {{ background: {t["border_soft"]}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical {{
        background: {t["border"]}; border-radius: 5px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t["text_dim"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent; height: 10px; margin: 2px;
        border-radius: 5px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t["border"]}; border-radius: 5px; min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {t["text_dim"]}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
    QToolTip {{
        background-color: {t["panel"]}; color: {t["text"]};
        border: 1px solid {t["border"]}; padding: 4px 6px;
        border-radius: 4px;
    }}
    """


def _base_is_fusion(app: QApplication) -> bool:
    """判断当前（可能被 QStyleSheetStyle 包装的）基础风格是否为 Fusion。"""
    st = app.style()
    seen = 0
    while st is not None and seen < 5:
        if "Fusion" in st.metaObject().className():
            return True
        base = getattr(st, "baseStyle", None)
        if not callable(base):
            break
        st = base()
        seen += 1
    return False


def apply_theme(app: QApplication, name: str) -> None:
    """应用主题。name 可为 'dark' / 'light' / 'system'。"""
    global _CURRENT, _RESOLVED
    _CURRENT = name
    # system 主题：检测操作系统偏好
    if name == "system":
        _RESOLVED = _detect_system_theme()
    else:
        _RESOLVED = "dark" if name == "dark" else "light"
    # Fusion 风格能正确消费 palette/QSS，避免原生风格下深色背景文字不可见。
    # setStyleSheet 会把基础风格包成 QStyleSheetStyle，故用基础风格判断是否已为 Fusion。
    if not _base_is_fusion(app):
        try:
            app.setStyle("Fusion")
        except Exception:
            pass
    palette = _dark_palette() if _RESOLVED == "dark" else _light_palette()
    app.setPalette(palette)
    app.setStyleSheet(_qss(_RESOLVED == "dark"))
