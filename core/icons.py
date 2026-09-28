"""自绘 SVG 线性图标集（零依赖，随主题着色）。

设计规范：
- 16×16 网格；线宽 1.5；圆头/圆角连接；单色线性（少数实心如 play）。
- 颜色由调用方注入（`{c}` 占位符），因此同一图标可在深浅主题下复用。
- 依赖 Qt 的 SVG 图标引擎（PySide6 内置 QtSvg），无需额外第三方库。
- 缓存按 (name, color) 命中，避免重复写盘。

用法：
    from .core.icons import icon, pixmap, names
    btn.setIcon(icon("send", "#2dd4bf"))
    label.setPixmap(pixmap("serial", "#9aa0a6", 16))

主题联动请改用 `core.theme.icon()`（它会按当前主题解析默认颜色）。
"""
import os
import tempfile

from PySide6.QtGui import QIcon, QPixmap, QColor

_GRID = 16
_DEFAULT_COLOR = "#8a8f98"  # 中性灰；主题接入时由 theme.icon() 覆盖

# 图标主体：16×16 网格上的 SVG 片段，{c} 为颜色占位符
_BODIES = {
    # ---- 会话类型 ----
    "serial": '<rect x="2.4" y="4.8" width="7.6" height="6.4" rx="1.5"/>'
              '<path d="M10 7h4M10 9h4"/>',
    "tcp_client": '<rect x="10.4" y="3.5" width="3.6" height="9" rx="1"/>'
                  '<path d="M2 8h6.6"/><path d="M6.4 5.6 8.8 8l-2.4 2.4"/>',
    "tcp_server": '<rect x="2" y="3.5" width="3.6" height="9" rx="1"/>'
                  '<path d="M14 8H7.4"/><path d="M9.6 5.6 7.2 8l2.4 2.4"/>',
    "udp": '<circle cx="8" cy="10.6" r="1.5"/>'
           '<path d="M4.9 7.5a4.4 4.4 0 0 1 6.2 0"/>'
           '<path d="M2.6 5.2a7.7 7.7 0 0 1 10.8 0"/>',
    "mqtt": '<path d="M5.5 12.6a3 3 0 0 1-.3-6 4 4 0 0 1 7.4 1.2 2.4 2.4 0 0 1-1.1 4.8z"/>',
    "modbus": '<rect x="2.5" y="2.5" width="11" height="11" rx="1.5"/>'
              '<path d="M2.5 6.2h11M2.5 9.8h11M6.2 2.5v11M9.8 2.5v11"/>',
    # ---- 操作 ----
    "add": '<path d="M8 3.2v9.6M3.2 8h9.6"/>',
    "play": '<path d="M6 4.2 11.8 8 6 11.8z" fill="{c}" stroke="{c}" stroke-width="1.2"/>',
    "pause": '<path d="M6.2 3.8v8.4M9.8 3.8v8.4"/>',
    "stop": '<rect x="4.4" y="4.4" width="7.2" height="7.2" rx="1.4"/>',
    "refresh": '<path d="M3.2 8a4.8 4.8 0 0 1 8.2-3.4"/><path d="M11.6 2.6v2.6H9"/>'
               '<path d="M12.8 8a4.8 4.8 0 0 1-8.2 3.4"/><path d="M4.4 13.4V10.8H7"/>',
    "clear": '<path d="M3.2 4.6h9.6"/><path d="M6.4 4.6V3.2h3.2v1.4"/>'
             '<path d="M4.8 4.6l.6 8.2h5.2l.6-8.2"/>',
    "export": '<path d="M8 9.2V2.6"/><path d="M5.4 5.2 8 2.6l2.6 2.6"/>'
              '<path d="M2.8 11v2.4h10.4V11"/>',
    "import": '<path d="M8 2.6v6.6"/><path d="M5.4 6.6 8 9.2l2.6-2.6"/>'
              '<path d="M2.8 11v2.4h10.4V11"/>',
    "search": '<circle cx="7.2" cy="7.2" r="4"/><path d="M10.3 10.3 13.4 13.4"/>',
    "list": '<path d="M3 4.4h.01M3 8h.01M3 11.6h.01"/>'
            '<path d="M6.4 4.4h6.8M6.4 8h6.8M6.4 11.6h6.8"/>',
    "settings": '<path d="M2.6 4.4h10.8M2.6 8h10.8M2.6 11.6h10.8"/>'
                '<circle cx="5.8" cy="4.4" r="1.8" fill="{c}" stroke="none"/>'
                '<circle cx="10.4" cy="8" r="1.8" fill="{c}" stroke="none"/>'
                '<circle cx="6.6" cy="11.6" r="1.8" fill="{c}" stroke="none"/>',
    "plugin": '<rect x="2.6" y="6.4" width="10.8" height="7" rx="1.4"/>'
              '<path d="M6.2 6.4V5a1.8 1.8 0 0 1 3.6 0v1.4"/>',
    "send": '<path d="M8 13V3.4"/><path d="M4.6 6.8 8 3.4l3.4 3.4"/>',
    "file": '<path d="M4.2 2.6h4.6l3 3v8.2H4.2z"/><path d="M8.8 2.6v3h3"/>',
    "copy": '<rect x="5.6" y="5.6" width="8" height="8" rx="1.2"/>'
            '<path d="M10.4 5.6V4.2a1.2 1.2 0 0 0-1.2-1.2H4.4a1.2 1.2 0 0 0-1.2 1.2v4.8'
            'a1.2 1.2 0 0 0 1.2 1.2h1.2"/>',
    "check": '<path d="M3.4 8.4 6.6 11.6 12.6 4.6"/>',
    "rename": '<path d="M11.2 2.6l2.2 2.2L6.2 12l-2.6.4.4-2.6z"/><path d="M9.9 3.9l2.2 2.2"/>',
    # ---- 方向 / 状态 ----
    "tx": '<path d="M3.6 12.4 12.4 3.6"/><path d="M6.4 3.6h6v6"/>',
    "rx": '<path d="M12.4 3.6 3.6 12.4"/><path d="M9.6 12.4h-6v-6"/>',
    "warn": '<path d="M8 2.9 14.2 13.1H1.8z"/><path d="M8 6.6v3.1M8 11.6v.1"/>',
    "error": '<circle cx="8" cy="8" r="5.8"/><path d="M8 5v3.6M8 10.8v.1"/>',
    "info": '<circle cx="8" cy="8" r="5.8"/><path d="M8 7.4v3.6M8 5.1v.1"/>',
    # ---- 导航 ----
    "chevron_down": '<path d="M4.2 6.4 8 10.2l3.8-3.8"/>',
    "chevron_right": '<path d="M6.4 4.2 10.2 8l-3.8 3.8"/>',
    "chevron_up": '<path d="M4.2 9.6 8 5.8l3.8 3.8"/>',
    "dot": '<circle cx="8" cy="8" r="2.6" fill="{c}" stroke="none"/>',
}

# 语义别名，避免调用方记多套名字
_ALIASES = {
    "close": "stop",
    "delete": "clear",
    "trash": "clear",
    "change_file": "file",
    "save": "check",
    "ok": "check",
}

_CACHE: dict = {}


def names() -> list:
    """全部可用图标名（含别名）。"""
    return sorted(set(_BODIES) | set(_ALIASES))


def has(name: str) -> bool:
    return name in _BODIES or name in _ALIASES


def _resolve(name: str) -> str:
    if name in _BODIES:
        return name
    if name in _ALIASES:
        return _ALIASES[name]
    raise KeyError(f"unknown icon: {name}")


def _hex(color) -> str:
    if isinstance(color, QColor):
        return color.name(QColor.HexRgb)
    return str(color or _DEFAULT_COLOR)


def svg(name: str, color=None) -> str:
    """生成该图标的 SVG 文本。"""
    body = _BODIES[_resolve(name)].replace("{c}", _hex(color))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_GRID}" height="{_GRID}" viewBox="0 0 {_GRID} {_GRID}" '
        f'fill="none" stroke="{_hex(color)}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def svg_path(name: str, color=None) -> str:
    """把图标写成临时 SVG 文件并返回路径（QIcon/QLabel 可直接使用）。"""
    key = (_resolve(name), _hex(color))
    cached = _CACHE.get(key)
    if cached and os.path.isfile(cached):
        return cached
    out_dir = os.path.join(tempfile.gettempdir(), "snt_icons")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        out_dir = tempfile.gettempdir()
    safe = key[1].lstrip("#")
    path = os.path.join(out_dir, f"{key[0]}_{safe}.svg")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg(name, color))
    except OSError:
        return ""
    path = path.replace("\\", "/")
    _CACHE[key] = path
    return path


def icon(name: str, color=None, size: int = 16) -> QIcon:
    """按颜色生成 QIcon（矢量，可任意缩放）。"""
    path = svg_path(name, color)
    if not path:
        return QIcon()
    return QIcon(path)


def pixmap(name: str, color=None, size: int = 16) -> QPixmap:
    """按颜色与尺寸生成 QPixmap（用于 QLabel 等）。"""
    return icon(name, color, size).pixmap(size, size)


def clear_cache():
    """清空路径缓存（一般无需调用）。"""
    _CACHE.clear()
