"""主题系统（深色 / 浅色 / 跟随系统），基于 QPalette + QSS 令牌，跨平台一致。

设计规范（紧凑工程感）：
- 圆角只保留两档：控件 `r_ctl`(3px) / 容器 `r_ctr`(5px)；徽标为胶囊。禁止再引入散装圆角。
- 以背景层级（window → panel → panel_alt → sunken）区分区域，尽量少用描边；描边仅用于
  输入框与必要的分隔。
- 按钮分四级：`primary`（实心，一屏一个）/ `secondary`（默认，描边浅底）/ `ghost`（无边框）
  / `danger`（红字）。`accent` 保留为 `primary` 的历史别名。
- 选中态统一为「扁平浅色底 `sel_bg` +（列表类）左侧 2px 指示条」，不再用饱和实心块。
- Tab 采用下划线式（选中：强调色文字 + 底部 2px 条）。
- 箭头/勾选标记使用运行时生成的 SVG，避免 Fusion 默认渲染不可靠。

其它：
- 强制 Fusion 风格：只有 Fusion 完全由 palette/QSS 驱动，能正确应用深色背景与文字色。
- 暴露 `tokens()` / `status_colors()` / `direction_colors()` / `icon()` 供各面板复用。
- 支持 "system" 主题：自动检测操作系统深浅色偏好。
"""

import os
import sys
import tempfile

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor, QIcon, QPixmap

_CURRENT = "dark"
_RESOLVED = "dark"  # system 解析后的实际值

# 通信日志方向标记配色（按主题分别取对比度良好的值）
_DARK_DIRECTION = ("#3fb950", "#58a6ff")  # (发送-绿, 接收-蓝)
_LIGHT_DIRECTION = ("#1a7f37", "#0969da")

# 状态色（用于会话列表圆点/徽标，按主题区分保证对比度）
_DARK_STATUS = {
    "CONNECTED": "#3fb950",
    "LISTENING": "#58a6ff",
    "ERROR": "#f85149",
    "RECONNECTING": "#d29922",
    "CONNECTING": "#d29922",
    "DISCONNECTED": "#6e7681",
}
_LIGHT_STATUS = {
    "CONNECTED": "#1a7f37",
    "LISTENING": "#0969da",
    "ERROR": "#d1242f",
    "RECONNECTING": "#9a6700",
    "CONNECTING": "#9a6700",
    "DISCONNECTED": "#8c959f",
}


# ---------------------------------------------------------------------------
# 状态色（会话列表/徽标使用）；会话列表的圆点由 SessionItemDelegate 直接绘制。
# ---------------------------------------------------------------------------


def _detect_system_theme() -> str:
    """检测操作系统是否使用深色模式。"""
    try:
        from PySide6.QtGui import QGuiApplication

        # Qt 6.5+ 支持 colorScheme
        scheme = QGuiApplication.styleHints().colorScheme()
        return "dark" if scheme.value == 2 else "light"  # Qt.ColorScheme.Dark = 2
    except Exception:
        pass
    # 回退：检查注册表 / defaults
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

    stroke = (
        'stroke="{c}" stroke-width="1.5" fill="none" '
        'stroke-linecap="round" stroke-linejoin="round"'
    )
    shapes = {
        "up": f'<path d="M2.5 8 L6 4.5 L9.5 8" {stroke}/>',
        "down": f'<path d="M2.5 4.5 L6 8 L9.5 4.5" {stroke}/>',
        "left": f'<path d="M8 2.5 L4.5 6 L8 9.5" {stroke}/>',
        "right": f'<path d="M4.5 2.5 L8 6 L4.5 9.5" {stroke}/>',
        "check": (
            '<path d="M3 7 L5.5 9.5 L11 3.5" stroke="{c}" stroke-width="2.2" '
            'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        ),
    }
    tmpl = shapes.get(name, "")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" '
        f'viewBox="0 0 12 12">{tmpl.format(c=color)}</svg>'
    )
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
            window="#1b1c1e",
            panel="#202124",
            panel_alt="#26282b",
            sunken="#1a1b1d",
            # 描边/分隔
            border="#34363a",
            border_soft="#2b2d31",
            sep="#2b2d31",
            # 文字层
            text="#d7d9dd",
            text_dim="#9aa0a6",
            text_inv="#ffffff",
            # 强调
            accent="#2dd4bf",
            accent_soft="#14b8a6",
            accent_text="#06231d",
            primary="#2dd4bf",
            primary_hov="#3ee0cb",
            # 选中
            sel_bg="#1f3b37",
            sel_bar="#2dd4bf",
            sel_hover="#2a2d31",
            # 状态
            ok="#3fb950",
            err="#f85149",
            warn="#d29922",
            info="#58a6ff",
            # 徽标淡底
            badge_ok_bg="#17301f",
            badge_err_bg="#331d1c",
            badge_warn_bg="#33290f",
            badge_idle_bg="#26282b",
            log_bg="#1a1b1d",
            # 尺寸令牌
            r_ctl="3px",
            r_ctr="5px",
            sp_1="4px",
            sp_2="8px",
            sp_3="12px",
            sp_4="16px",
            h_ctl="24px",
        )
    return dict(
        # 背景层
        window="#f5f6f7",
        panel="#ffffff",
        panel_alt="#f0f1f2",
        sunken="#fafbfc",
        # 描边/分隔
        border="#d8dade",
        border_soft="#e8eaed",
        sep="#eceef0",
        # 文字层
        text="#1f2328",
        text_dim="#6b7280",
        text_inv="#ffffff",
        # 强调
        accent="#0f766e",
        accent_soft="#0b5e50",
        accent_text="#ffffff",
        primary="#0f766e",
        primary_hov="#0b5e50",
        # 选中
        sel_bg="#e2f1ee",
        sel_bar="#0f766e",
        sel_hover="#f2f3f5",
        # 状态
        ok="#1a7f37",
        err="#d1242f",
        warn="#9a6700",
        info="#0969da",
        # 徽标淡底
        badge_ok_bg="#e6f4ea",
        badge_err_bg="#fdecea",
        badge_warn_bg="#fdf3e2",
        badge_idle_bg="#f0f1f2",
        log_bg="#fafbfc",
        # 尺寸令牌
        r_ctl="3px",
        r_ctr="5px",
        sp_1="4px",
        sp_2="8px",
        sp_3="12px",
        sp_4="16px",
        h_ctl="24px",
    )


def tokens() -> dict:
    """当前主题的设计令牌（颜色与尺寸）。"""
    return _tokens(_RESOLVED == "dark")


def icon(name: str, color: str = None, size: int = 16) -> QIcon:
    """按当前主题生成矢量图标（默认取正文色；可显式指定颜色）。"""
    from . import icons

    if color is None:
        color = tokens()["text"]
    return icons.icon(name, color, size)


def icon_pixmap(name: str, color: str = None, size: int = 16) -> QPixmap:
    """生成图标 pixmap（用于 QLabel 等）。"""
    from . import icons

    if color is None:
        color = tokens()["text"]
    return icons.pixmap(name, color, size)


def _dark_palette() -> QPalette:
    t = _tokens(True)
    p = QPalette()
    p.setColor(QPalette.Window, QColor(t["window"]))
    p.setColor(QPalette.WindowText, QColor(t["text"]))
    p.setColor(QPalette.Base, QColor(t["panel"]))
    p.setColor(QPalette.AlternateBase, QColor(t["panel_alt"]))
    p.setColor(QPalette.Text, QColor(t["text"]))
    p.setColor(QPalette.PlaceholderText, QColor("#7c8288"))
    p.setColor(QPalette.BrightText, QColor(t["text_inv"]))
    p.setColor(QPalette.Highlight, QColor(t["sel_bg"]))
    p.setColor(QPalette.HighlightedText, QColor(t["text"]))
    p.setColor(QPalette.Button, QColor(t["panel_alt"]))
    p.setColor(QPalette.ButtonText, QColor(t["text"]))
    p.setColor(QPalette.Link, QColor(t["info"]))
    p.setColor(QPalette.ToolTipBase, QColor(t["panel_alt"]))
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
    p.setColor(QPalette.PlaceholderText, QColor("#9198a1"))
    p.setColor(QPalette.BrightText, QColor(t["text_inv"]))
    p.setColor(QPalette.Highlight, QColor(t["sel_bg"]))
    p.setColor(QPalette.HighlightedText, QColor(t["text"]))
    p.setColor(QPalette.Button, QColor(t["panel_alt"]))
    p.setColor(QPalette.ButtonText, QColor(t["text"]))
    p.setColor(QPalette.Link, QColor(t["info"]))
    p.setColor(QPalette.ToolTipBase, QColor(t["panel_alt"]))
    p.setColor(QPalette.ToolTipText, QColor(t["text"]))
    return p


def _qss(dark: bool) -> str:
    t = _tokens(dark)
    mono = 'Consolas, "Cascadia Mono", "Courier New", monospace'
    up_svg = _svg_path("up", t["text_dim"])
    down_svg = _svg_path("down", t["text_dim"])
    left_svg = _svg_path("left", t["text_dim"])
    right_svg = _svg_path("right", t["text_dim"])
    check_svg = _svg_path("check", t["accent_text"])

    return f"""
    /* ===================== 基础 ===================== */
    QWidget {{ font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 12.5px; }}
    QMainWindow, QDialog {{ background-color: {t["window"]}; }}
    QWidget#sidebar, QFrame#sidebar {{ background-color: {t["window"]}; }}

    /* ===================== 菜单 ===================== */
    QMenuBar {{ background-color: {t["panel"]}; color: {t["text"]}; border-bottom: 1px solid {t["sep"]}; padding: 1px 4px; }}
    QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: {t["r_ctl"]}; }}
    QMenuBar::item:selected {{ background: {t["sel_hover"]}; }}
    QMenu {{ background-color: {t["panel"]}; color: {t["text"]}; border: 1px solid {t["border"]}; border-radius: {t["r_ctr"]}; padding: 4px; }}
    QMenu::item {{ padding: 5px 20px 5px 24px; border-radius: {t["r_ctl"]}; }}
    QMenu::item:selected {{ background: {t["sel_bg"]}; color: {t["text"]}; }}
    QMenu::separator {{ height: 1px; background: {t["sep"]}; margin: 4px 8px; }}

    /* ===================== 状态栏 ===================== */
    QStatusBar {{ background-color: {t["panel"]}; color: {t["text_dim"]}; border-top: 1px solid {t["sep"]}; font-size: 11.5px; }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ color: {t["text_dim"]}; margin: 0 6px; }}
    QStatusBar QLabel#status_ok {{ color: {t["ok"]}; font-weight: 600; }}
    QStatusBar QLabel#status_err {{ color: {t["err"]}; font-weight: 600; }}

    /* ===================== 按钮（四级） ===================== */
    QPushButton {{
        background-color: {t["panel_alt"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_ctl"]};
        padding: 3px 12px;
        min-height: 20px;
    }}
    QPushButton:hover {{ background-color: {t["sel_hover"]}; border-color: {t["accent"]}; }}
    QPushButton:pressed {{ background-color: {t["sel_bg"]}; }}
    QPushButton:disabled {{ color: {t["text_dim"]}; background-color: transparent; border-color: {t["border_soft"]}; }}

    /* primary：实心强调色，一屏一个 */
    QPushButton#primary, QPushButton#accent {{
        background-color: {t["primary"]};
        color: {t["accent_text"]};
        border: 1px solid {t["primary"]};
        font-weight: 600;
    }}
    QPushButton#primary:hover, QPushButton#accent:hover {{ background-color: {t["primary_hov"]}; border-color: {t["primary_hov"]}; }}
    QPushButton#primary:pressed, QPushButton#accent:pressed {{ background-color: {t["accent_soft"]}; border-color: {t["accent_soft"]}; }}
    QPushButton#primary:disabled, QPushButton#accent:disabled {{ background-color: {t["panel_alt"]}; color: {t["text_dim"]}; border-color: {t["border_soft"]}; }}

    /* secondary：显式声明的次级实心 */
    QPushButton#secondary {{ background-color: {t["panel_alt"]}; color: {t["text"]}; border: 1px solid {t["border"]}; }}
    QPushButton#secondary:hover {{ border-color: {t["accent"]}; color: {t["accent"]}; background-color: {t["sel_hover"]}; }}

    /* ghost：无边框，hover 才显底 */
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {t["text"]}; }}
    QPushButton#ghost:hover {{ background-color: {t["sel_hover"]}; border-color: {t["border"]}; }}
    QPushButton#ghost:disabled {{ color: {t["text_dim"]}; background: transparent; border-color: transparent; }}

    /* danger：红字，hover 实红 */
    QPushButton#danger {{ background: transparent; border: 1px solid transparent; color: {t["err"]}; }}
    QPushButton#danger:hover {{ background-color: {t["badge_err_bg"]}; border-color: {t["err"]}; }}

    QToolButton {{
        background: transparent; color: {t["text"]};
        border: 1px solid transparent; border-radius: {t["r_ctl"]};
        padding: 2px 8px; min-height: 20px;
    }}
    QToolButton:hover {{ background: {t["sel_hover"]}; border-color: {t["border"]}; }}
    QToolButton:checked {{ background: {t["sel_bg"]}; color: {t["accent"]}; border-color: {t["accent"]}; font-weight: 600; }}
    QToolButton:disabled {{ color: {t["text_dim"]}; }}

    /* ===================== 输入控件 ===================== */
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {t["sunken"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_ctl"]};
        padding: 2px 8px;
        min-height: {t["h_ctl"]};
        selection-background-color: {t["sel_bg"]};
        selection-color: {t["text"]};
    }}
    QLineEdit {{ min-width: 70px; }}
    QSpinBox, QDoubleSpinBox {{ min-width: 60px; }}
    QComboBox {{ min-width: 80px; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 1px solid {t["accent"]};
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        color: {t["text_dim"]}; background-color: {t["panel_alt"]};
    }}
    QLineEdit#error, QPlainTextEdit#error {{ border-color: {t["err"]}; }}

    /* 下拉按钮：细箭头右对齐，去掉分隔线与底色 */
    QComboBox {{ padding-right: 22px; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: center right;
        width: 20px; border: none; background: transparent;
    }}
    QComboBox::down-arrow {{ image: url("{down_svg}"); width: 10px; height: 10px; }}
    QComboBox::drop-down:hover {{
        background: {t["sel_hover"]};
        border-top-right-radius: {t["r_ctl"]}; border-bottom-right-radius: {t["r_ctl"]};
    }}
    QComboBox QAbstractItemView {{
        background-color: {t["panel"]}; color: {t["text"]};
        border: 1px solid {t["border"]}; border-radius: {t["r_ctl"]};
        padding: 4px; outline: 0;
        selection-background-color: {t["sel_bg"]}; selection-color: {t["text"]};
    }}

    /* 步进按钮：右侧上下堆叠细箭头 */
    QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border; subcontrol-position: top right;
        width: 18px; background: {t["panel_alt"]};
        border-left: 1px solid {t["border_soft"]};
        border-bottom: 1px solid {t["border_soft"]};
        border-top-right-radius: {t["r_ctl"]};
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right;
        width: 18px; background: {t["panel_alt"]};
        border-left: 1px solid {t["border_soft"]};
        border-bottom-right-radius: {t["r_ctl"]};
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {t["sel_hover"]}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up_svg}"); width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down_svg}"); width: 10px; height: 10px; }}

    /* ===================== 等宽文本 ===================== */
    QPlainTextEdit#mono, QTextEdit#mono, QLineEdit#mono, QLabel#mono, QTableWidget#mono {{
        font-family: {mono}; font-size: 12px;
    }}
    QTextEdit#recv {{
        background-color: {t["log_bg"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_ctr"]};
        font-family: {mono};
        font-size: 12px;
        padding: 6px 8px;
    }}

    /* ===================== 单选/复选 ===================== */
    QRadioButton, QCheckBox {{ spacing: 6px; color: {t["text"]}; background: transparent; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; }}
    QRadioButton::indicator:unchecked {{ border: 1.5px solid {t["border"]}; border-radius: 8px; background: transparent; }}
    QRadioButton::indicator:unchecked:hover {{ border-color: {t["accent"]}; }}
    QRadioButton::indicator:checked {{
        border: 1.5px solid {t["accent"]}; border-radius: 8px;
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                    stop:0 {t["accent"]}, stop:0.5 {t["accent"]}, stop:0.62 transparent);
    }}
    QRadioButton:checked {{ color: {t["text"]}; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1.5px solid {t["border"]}; border-radius: {t["r_ctl"]}; background: transparent; }}
    QCheckBox::indicator:hover {{ border-color: {t["accent"]}; }}
    QCheckBox::indicator:checked {{ background: {t["accent"]}; border: 1.5px solid {t["accent"]}; image: url("{check_svg}"); }}
    QCheckBox::indicator:checked:disabled {{ background: {t["border"]}; border-color: {t["border"]}; }}

    /* ===================== 列表/树/表 ===================== */
    QTreeWidget, QListWidget, QTableWidget {{
        background-color: {t["panel"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: {t["r_ctr"]};
        gridline-color: {t["sep"]};
        outline: 0;
        alternate-background-color: {t["panel_alt"]};
    }}
    QListWidget::item, QTreeWidget::item {{ padding: 5px 6px; margin: 1px 3px; border-radius: {t["r_ctl"]}; }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
        background-color: {t["sel_bg"]}; color: {t["text"]};
    }}
    QListWidget::item:hover:!selected, QTreeWidget::item:hover:!selected {{ background-color: {t["sel_hover"]}; }}
    QTableWidget::item {{ padding: 3px 6px; }}
    QHeaderView::section {{
        background-color: {t["panel_alt"]};
        color: {t["text_dim"]};
        border: none;
        border-right: 1px solid {t["sep"]};
        border-bottom: 1px solid {t["border"]};
        padding: 5px 8px;
        font-size: 11.5px;
        font-weight: 600;
    }}
    QHeaderView::section:hover {{ background-color: {t["sel_hover"]}; }}
    QTableCornerButton::section {{ background-color: {t["panel_alt"]}; border: none; }}

    /* ===================== Tab（下划线式） ===================== */
    QTabWidget::pane {{ border: none; border-top: 1px solid {t["sep"]}; background: transparent; top: -1px; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent; color: {t["text_dim"]};
        padding: 6px 10px; margin: 0 1px;
        border: none; border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {t["accent"]}; border-bottom: 2px solid {t["accent"]}; font-weight: 600; }}
    QTabBar::tab:hover:!selected {{ color: {t["text"]}; border-bottom-color: {t["border"]}; }}
    QTabBar QToolButton {{ background: transparent; border: none; border-radius: {t["r_ctl"]}; padding: 2px; }}
    QTabBar QToolButton:hover {{ background: {t["sel_hover"]}; }}
    QTabBar QToolButton::right-arrow {{ image: url("{right_svg}"); width: 10px; height: 10px; }}
    QTabBar QToolButton::left-arrow {{ image: url("{left_svg}"); width: 10px; height: 10px; }}
    QTabWidget#dock_tabs QTabBar::tab {{ padding: 5px 8px; font-size: 11.5px; }}
    QTabWidget#dock_tabs::pane {{ padding: 6px; }}

    /* ===================== 标签 / 徽标 ===================== */
    QLabel {{ color: {t["text"]}; background: transparent; }}
    QLabel#dim {{ color: {t["text_dim"]}; }}
    QLabel#h1 {{ font-size: 13px; font-weight: 600; }}
    QLabel#h2 {{ font-size: 11.5px; font-weight: 600; color: {t["text_dim"]}; }}
    QLabel#stat {{ color: {t["text_dim"]}; font-family: {mono}; font-size: 11.5px; }}
    QLabel#mono {{ font-family: {mono}; font-size: 12px; }}
    QLabel#chip {{
        background-color: {t["panel_alt"]}; color: {t["text_dim"]};
        border: 1px solid {t["border_soft"]}; border-radius: {t["r_ctl"]};
        padding: 0 6px; font-size: 11.5px;
    }}
    QLabel#badge_ok, QLabel#badge_err, QLabel#badge_warn, QLabel#badge_idle {{
        border: none; border-radius: 9px; padding: 1px 8px; font-size: 11.5px;
    }}
    QLabel#badge_ok {{ color: {t["ok"]}; background-color: {t["badge_ok_bg"]}; font-weight: 600; }}
    QLabel#badge_err {{ color: {t["err"]}; background-color: {t["badge_err_bg"]}; font-weight: 600; }}
    QLabel#badge_warn {{ color: {t["warn"]}; background-color: {t["badge_warn_bg"]}; font-weight: 600; }}
    QLabel#badge_idle {{ color: {t["text_dim"]}; background-color: {t["badge_idle_bg"]}; }}
    QLabel#status_ok {{ color: {t["ok"]}; font-weight: 600; }}
    QLabel#status_err {{ color: {t["err"]}; font-weight: 600; }}
    QLabel#section {{ color: {t["text_dim"]}; font-size: 11.5px; font-weight: 600; }}

    /* ===================== 容器 ===================== */
    QFrame#card {{ background-color: {t["panel"]}; border: 1px solid {t["border_soft"]}; border-radius: {t["r_ctr"]}; }}
    QFrame#panel {{ background-color: {t["panel"]}; border: none; }}
    QGroupBox {{
        background: transparent;
        border: 1px solid {t["border_soft"]};
        border-radius: {t["r_ctr"]};
        margin-top: 13px;
        padding: 10px 10px 8px 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; subcontrol-position: top left;
        left: 8px; padding: 0 4px;
        color: {t["text_dim"]}; background: transparent;
        font-size: 11.5px; font-weight: 600;
    }}
    QFrame#collapsible_header {{ background-color: {t["panel_alt"]}; border: 1px solid {t["border_soft"]}; border-radius: {t["r_ctr"]}; }}
    QFrame#collapsible_header:hover {{ border-color: {t["border"]}; background-color: {t["sel_hover"]}; }}
    QFrame#accent_bar {{ background-color: {t["accent"]}; border: none; }}
    QLabel#arrow {{ color: {t["text_dim"]}; font-size: 12px; }}
    QFrame#hsep {{ background-color: {t["sep"]}; border: none; max-height: 1px; }}
    QFrame#vline {{ background-color: {t["sep"]}; border: none; max-width: 1px; }}

    /* ===================== 滚动 ===================== */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 1px; }}
    QScrollBar::handle:vertical {{ background: {t["border"]}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {t["text_dim"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 1px 2px; }}
    QScrollBar::handle:horizontal {{ background: {t["border"]}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: {t["text_dim"]}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

    /* ===================== 分割条 / Dock / 进度条 ===================== */
    QSplitter::handle {{ background: {t["sep"]}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QSplitter::handle:hover {{ background: {t["accent"]}; }}
    QDockWidget {{ background-color: {t["panel"]}; color: {t["text"]}; }}
    QDockWidget::title {{
        background-color: {t["panel"]};
        color: {t["text_dim"]};
        padding: 6px 10px;
        border-bottom: 1px solid {t["sep"]};
        font-size: 11.5px; font-weight: 600;
    }}
    QDockWidget::close-button, QDockWidget::float-button {{ background: transparent; border: none; padding: 2px; }}
    QDockWidget::close-button:hover, QDockWidget::float-button:hover {{ background: {t["sel_hover"]}; border-radius: {t["r_ctl"]}; }}
    QProgressBar {{
        background-color: {t["panel_alt"]}; color: {t["text"]};
        border: none; border-radius: {t["r_ctl"]};
        text-align: center; height: 6px; font-size: 11px;
    }}
    QProgressBar::chunk {{ background-color: {t["accent"]}; border-radius: {t["r_ctl"]}; }}

    /* ===================== 其它 ===================== */
    QToolTip {{
        background-color: {t["panel_alt"]}; color: {t["text"]};
        border: 1px solid {t["border"]}; padding: 4px 8px;
        border-radius: {t["r_ctl"]};
    }}
    QSizeGrip {{ background: transparent; }}
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
