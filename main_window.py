"""主窗口：会话侧边栏 + 工作区(可折叠配置 + 收发) + 工具面板(Dock) + 状态栏。

操作逻辑（重构版）：
- 左侧会话列表集中管理：新建 / 打开|关闭 / 重命名 / 删除（按钮 + 右键菜单）。
- 每个会话顶部是“可折叠配置卡片”：未连接时展开配置，连接后自动折叠并锁定，
  给收发区让出空间；标题栏右侧内嵌“打开/关闭”按钮，操作所见即所得。
- 状态以徽标/颜色实时反馈；会话项用状态色点标识连接状态。
"""

import uuid
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QSplitter,
    QDockWidget,
    QPushButton,
    QLabel,
    QDialog,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QMenu,
    QInputDialog,
    QFrame,
    QSizePolicy,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
)
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPainter

from .core.channel_factory import create_channel
from .core.config import Config
from .core.autoreply import AutoReplyEngine
from .core.plugin_manager import PluginManager
from .core.i18n import tr
from .core.telemetry import get_telemetry
from .core.theme import status_colors, tokens, icon, icon_pixmap
from .ui.session_config import SessionConfigWidget
from .ui.recv_send import RecvSendWidget
from .ui.mqtt_panel import MqttPanel
from .ui.tools_panel import ToolsPanel
from .ui.plugin_panel import PluginManagerWidget
from .ui.settings_dialog import SettingsDialog
from .ui.widgets import CollapsibleSection

KIND_LABELS = {
    "serial": "serial",
    "tcp_client": "tcp_client",
    "tcp_server": "tcp_server",
    "udp": "udp",
    "mqtt": "mqtt",
}
# 会话类型 → 图标名（core/icons.py）
KIND_ICONS = {
    "serial": "serial",
    "tcp_client": "tcp_client",
    "tcp_server": "tcp_server",
    "udp": "udp",
    "mqtt": "mqtt",
}

# 菜单项 i18n key → 图标名
MENU_ICONS = {
    "import_config": "import",
    "export_config": "export",
    "settings": "settings",
    "plugin_manager": "plugin",
}

# 会话项自定义数据角色
ROLE_STATUS = Qt.UserRole + 1


class SessionItemDelegate(QStyledItemDelegate):
    """会话列表项：类型图标 + 文本 + 行尾状态圆点，扁平选中高亮。

    自绘背景以摆脱 QSS 圆角方块：
    - 选中：`sel_bg` 扁平底 + 左侧 2px 指示条
    - 悬停：`sel_hover` 底
    - 行尾 8px 圆点表示连接状态（颜色取 status_colors()）
    """

    BAR_W = 2
    DOT_R = 3
    DOT_GAP = 14

    def paint(self, painter, option, index):
        t = tokens()
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        if selected:
            painter.fillRect(rect, QColor(t["sel_bg"]))
            painter.fillRect(
                QRect(rect.left(), rect.top() + 3, self.BAR_W, rect.height() - 6),
                QColor(t["sel_bar"]),
            )
        elif hovered:
            painter.fillRect(rect, QColor(t["sel_hover"]))
        painter.restore()

        # 交给基类绘制图标与文字（去掉选中/悬停态，避免重复画底）
        opt = QStyleOptionViewItem(option)
        opt.rect = rect.adjusted(0, 0, -self.DOT_GAP, 0)
        opt.state &= ~(QStyle.State_Selected | QStyle.State_MouseOver)
        super().paint(painter, opt, index)

        status = index.data(ROLE_STATUS)
        if status:
            colors = status_colors()
            color = colors.get(status, colors["DISCONNECTED"])
            cy = rect.center().y() + 1
            cx = rect.right() - 11
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QRect(cx - self.DOT_R, cy - self.DOT_R,
                                      self.DOT_R * 2, self.DOT_R * 2))
            painter.restore()


class SessionView(QWidget):
    """单个会话的工作区：可折叠配置卡片 + 收发主体。"""

    def __init__(self, session, config, autoreply, parent=None):
        super().__init__(parent)
        self.session = session  # dict: id, kind, name, cfg
        self.config = config
        self.autoreply = autoreply
        self.channel = None
        self.main_window = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 可折叠配置卡片
        self.cfg_section = CollapsibleSection(self._title(), collapsed=False)
        self.cfg_section.set_leading_icon(icon_pixmap(self._kind_icon(), tokens()["text_dim"], 16))
        self.cfg_widget = SessionConfigWidget(self.session["kind"])
        if self.session.get("cfg"):
            self.cfg_widget.apply_config(self.session["cfg"])
        self.cfg_section.set_content_widget(self.cfg_widget)

        # 标题栏右侧：状态徽标 + 打开/关闭按钮
        self.state_badge = QLabel(tr("disconnected"))
        self.state_badge.setObjectName("badge_idle")
        self.toggle_btn = QPushButton(tr("open"))
        self.toggle_btn.setObjectName("accent")
        self.toggle_btn.setIcon(icon("play", tokens()["accent_text"], 14))
        self.toggle_btn.setMinimumWidth(84)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        # 阻止按钮点击触发折叠
        self.toggle_btn.setFocusPolicy(Qt.NoFocus)
        self.cfg_section.add_header_widget(self.state_badge)
        self.cfg_section.add_header_widget(self.toggle_btn)
        layout.addWidget(self.cfg_section)

        # MQTT 专属运行期面板（发布/订阅/遗嘱）
        self.mqtt_panel = None
        self.mqtt_section = None
        if self.session["kind"] == "mqtt":
            self.mqtt_panel = MqttPanel(self.config)
            if self.session.get("cfg"):
                self.mqtt_panel.apply_config(self.session["cfg"])
            self.mqtt_section = CollapsibleSection(tr("mqtt_panel_title"), collapsed=True)
            self.mqtt_section.set_content_widget(self.mqtt_panel)
            layout.addWidget(self.mqtt_section)

        # 主体
        self.body = RecvSendWidget(self.autoreply, self.config, self.session["kind"])
        layout.addWidget(self.body, 1)

    def _kind_icon(self) -> str:
        return KIND_ICONS.get(self.session["kind"], "serial")

    def _title(self) -> str:
        kind = tr(KIND_LABELS.get(self.session["kind"], self.session["kind"]))
        return f"{self.session['name']}   [{kind}]"

    def refresh_theme(self):
        """主题切换后刷新本视图的动态图标。"""
        self.cfg_section.set_leading_icon(icon_pixmap(self._kind_icon(), tokens()["text_dim"], 16))
        self._apply_toggle_visual()
        body = self.body
        if hasattr(body, "refresh_theme"):
            body.refresh_theme()

    def _apply_toggle_visual(self):
        """按连接状态更新“打开/关闭”按钮的文字与图标。"""
        self.toggle_btn.setText(tr("close") if self.channel else tr("open"))
        name = "stop" if self.channel else "play"
        self.toggle_btn.setIcon(icon(name, tokens()["accent_text"], 14))

    def refresh_title(self):
        self.cfg_section.set_title(self._title())

    def _on_toggle_clicked(self):
        if self.main_window:
            self.main_window.toggle_session(self.session["id"])

    def open_channel(self, mw):
        if self.channel:
            return
        self.main_window = mw
        self.channel = create_channel(self.session["kind"], self.session["id"])
        self.channel.status_changed.connect(lambda s, v=self: mw._on_status(v, s))
        self.channel.error_occurred.connect(mw._on_error)
        if isinstance(self.body, RecvSendWidget):
            self.body.bind(self.channel)
        cfg = self.cfg_widget.get_config()
        if self.mqtt_panel is not None:
            cfg.update(self.mqtt_panel.collect_config())
        self.session["cfg"] = cfg
        cfg.update({"id": self.session["id"], "kind": self.session["kind"]})
        self.channel.open(cfg)
        if self.mqtt_panel is not None:
            self.mqtt_panel.bind(self.channel)
        # 连接后：锁定并折叠配置，给收发区让位
        self.cfg_widget.set_enabled_all(False)
        self.cfg_section.set_collapsed(True)
        self.cfg_section.set_title(f"{self._title()}   —   {self.cfg_widget.summary()}")
        self._apply_toggle_visual()

    def close_channel(self):
        if self.channel:
            self.channel.close()
            if isinstance(self.body, RecvSendWidget):
                self.body.unbind()
            self.channel = None
        # 保存 MQTT 运行期设置（订阅/发布目标）
        if self.mqtt_panel is not None:
            if isinstance(self.session.get("cfg"), dict):
                self.session["cfg"].update(self.mqtt_panel.collect_config())
            self.mqtt_panel.unbind()
        # 断开后：解锁并展开配置
        self.cfg_widget.set_enabled_all(True)
        self.cfg_section.set_collapsed(False)
        self.refresh_title()
        self._apply_toggle_visual()
        self.state_badge.setText(tr("disconnected"))
        self.state_badge.setObjectName("badge_idle")
        self._repolish(self.state_badge)

    def set_status_badge(self, status):
        label = status.label
        self.state_badge.setText(label)
        name = status.name
        obj = "badge_idle"
        if name in ("CONNECTED", "LISTENING"):
            obj = "badge_ok"
        elif name == "ERROR":
            obj = "badge_err"
        elif name in ("CONNECTING", "RECONNECTING"):
            obj = "badge_warn"
        self.state_badge.setObjectName(obj)
        self._repolish(self.state_badge)

    @staticmethod
    def _repolish(w):
        w.style().unpolish(w)
        w.style().polish(w)


class MainWindow(QMainWindow):
    def __init__(
        self, config: Config, autoreply: AutoReplyEngine, plugins: PluginManager
    ):
        super().__init__()
        self.config = config
        self.autoreply = autoreply
        self.plugins = plugins
        self.views: dict = {}
        self.sessions: list = []
        self._ext_actions = []
        self._extension_windows = []
        self.setWindowTitle(tr("app_title"))
        self.resize(1280, 780)
        self._build_menus()
        self._build_central()
        self._build_docks()
        self._build_statusbar()
        self._restore_sessions()

    # ================= 构建 =================
    def _build_menus(self):
        mb = self.menuBar()
        self._menu_icon_actions = []
        f = mb.addMenu(tr("menu_file"))
        for key, slot in (("import_config", self._import_cfg), ("export_config", self._export_cfg)):
            act = f.addAction(icon(MENU_ICONS[key], tokens()["text"], 14), tr(key), slot)
            self._menu_icon_actions.append((act, MENU_ICONS[key]))
        f.addSeparator()
        f.addAction(tr("quit"), self.close)
        t = mb.addMenu(tr("menu_tools"))
        for key, slot in (("settings", self._open_settings), ("plugin_manager", self._open_plugins)):
            act = t.addAction(icon(MENU_ICONS[key], tokens()["text"], 14), tr(key), slot)
            self._menu_icon_actions.append((act, MENU_ICONS[key]))
        self._menu_ext = t
        self._build_ext_menu()
        v = mb.addMenu(tr("menu_view"))
        self._tools_toggle = v.addAction(tr("tools_panel"), self._toggle_tools)
        self._tools_toggle.setCheckable(True)
        self._tools_toggle.setChecked(True)

    def _refresh_menu_icons(self):
        """主题切换后刷新菜单项图标。"""
        for act, name in getattr(self, "_menu_icon_actions", []):
            try:
                act.setIcon(icon(name, tokens()["text"], 14))
            except RuntimeError:
                pass

    def _build_ext_menu(self):
        """重建 Tools 菜单中的扩展工具项。"""
        for act in self._ext_actions:
            self._menu_ext.removeAction(act)
        self._ext_actions.clear()
        entries = self.plugins.window_entries()
        if entries:
            sep = self._menu_ext.addSeparator()
            self._ext_actions.append(sep)
            for entry in entries:
                act = self._menu_ext.addAction(
                    entry["name"],
                    lambda pid=entry["id"]: self._launch_extension(pid),
                )
                self._ext_actions.append(act)

    def _build_central(self):
        # 左侧会话侧边栏（以背景分层，不用描边圆角卡片）
        sidebar = QFrame()
        sidebar.setObjectName("panel")
        sidebar.setMaximumWidth(280)
        sidebar.setMinimumWidth(220)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(10, 10, 10, 10)
        sb.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(6)
        head_icon = QLabel()
        head_icon.setPixmap(icon_pixmap("list", tokens()["text_dim"], 16))
        head.addWidget(head_icon)
        title = QLabel(tr("session_tree"))
        title.setObjectName("h1")
        head.addWidget(title)
        head.addStretch()
        self._new_btn = QPushButton(tr("add_session"))
        self._new_btn.setObjectName("secondary")
        self._new_btn.setIcon(icon("add", tokens()["text"], 14))
        self._new_btn.clicked.connect(self._new_session)
        head.addWidget(self._new_btn)
        sb.addLayout(head)

        self.tree = QListWidget()
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.currentItemChanged.connect(self._on_select)
        self.tree.itemDoubleClicked.connect(lambda _it: self.toggle_current())
        # 长名称用省略号而非横向滚动条
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setTextElideMode(Qt.ElideRight)
        self.tree.setItemDelegate(SessionItemDelegate(self.tree))
        self.tree.setUniformItemSizes(True)
        self.tree.setSpacing(0)
        self.tree.setFrameShape(QFrame.NoFrame)
        sb.addWidget(self.tree, 1)

        # 底部操作按钮：开/关 占满一行，重命名/删除 各占半
        ops1 = QHBoxLayout()
        ops1.setSpacing(6)
        self._open_btn = QPushButton(tr("toggle"))
        self._open_btn.setObjectName("secondary")
        self._open_btn.setMinimumWidth(0)
        self._open_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._open_btn.clicked.connect(self.toggle_current)
        ops1.addWidget(self._open_btn)
        sb.addLayout(ops1)

        ops2 = QHBoxLayout()
        ops2.setSpacing(6)
        self._rename_btn = QPushButton(tr("rename"))
        self._rename_btn.setObjectName("ghost")
        self._rename_btn.setIcon(icon("rename", tokens()["text_dim"], 14))
        self._rename_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._rename_btn.clicked.connect(self._rename_current)
        self._del_btn = QPushButton(tr("delete"))
        self._del_btn.setObjectName("danger")
        self._del_btn.setIcon(icon("clear", tokens()["err"], 14))
        self._del_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._del_btn.clicked.connect(self._delete_current)
        ops2.addWidget(self._rename_btn)
        ops2.addWidget(self._del_btn)
        sb.addLayout(ops2)

        self.stack = QStackedWidget()
        self.stack.setMinimumWidth(680)

        spl = QSplitter()
        spl.addWidget(sidebar)
        spl.addWidget(self.stack)
        spl.setStretchFactor(0, 0)
        spl.setStretchFactor(1, 1)
        spl.setCollapsible(0, False)
        spl.setCollapsible(1, False)
        spl.setSizes([240, 900])
        self.setCentralWidget(spl)

        # 空状态提示
        self._empty = QLabel(tr("empty_hint"))
        self._empty.setObjectName("dim")
        self._empty.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self._empty)
        self._refresh_open_btn()

    def _build_docks(self):
        self.tools = ToolsPanel(self.autoreply, self.config, self)
        # dock 型插件 Tab
        for name, w in self.plugins.dock_widgets(self):
            self.tools.add_dock_tab(name, w)
        # QDockWidget
        self.tools_dock = QDockWidget(tr("tools"))
        self.tools_dock.setObjectName("tools_dock")
        self.tools_dock.setWidget(self.tools)
        self.tools_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.tools_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable
        )
        self.tools_dock.setMinimumWidth(260)
        self.tools_dock.setMaximumWidth(440)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tools_dock)
        self.tools_dock.visibilityChanged.connect(self._on_dock_visibility)

    def get_active_sessions(self):
        """返回所有已连接的会话列表，供插件使用。
        返回 [(sid, name, kind, channel), ...]
        """
        out = []
        for sid, view in self.views.items():
            if view.channel:
                from .core.channel import ChannelStatus

                if view.channel.status in (
                    ChannelStatus.CONNECTED,
                    ChannelStatus.LISTENING,
                ):
                    out.append(
                        (sid, view.session["name"], view.session["kind"], view.channel)
                    )
        return out

    def fill_send_text(self, text: str):
        """将文本填充到当前活动会话的发送区。"""
        view, _ = self._current_view()
        if view and hasattr(view.body, "set_send_text"):
            view.body.set_send_text(text)

    def _on_dock_visibility(self, vis):
        try:
            self._tools_toggle.setChecked(bool(vis))
        except RuntimeError:
            # 退出时 action 可能已被销毁，忽略
            pass

    def _build_statusbar(self):
        self.status_lbl = QLabel(tr("disconnected"))
        self.status_lbl.setObjectName("dim")
        self.statusBar().addPermanentWidget(self.status_lbl)
        # 分隔符
        sep1 = QFrame()
        sep1.setObjectName("vline")
        sep1.setFixedWidth(1)
        sep1.setFixedHeight(14)
        self.statusBar().addPermanentWidget(sep1)
        # 编码显示
        enc = self.config.get("default_encoding", "utf-8")
        self.enc_lbl = QLabel(f"ENC {enc}")
        self.enc_lbl.setObjectName("chip")
        self.statusBar().addPermanentWidget(self.enc_lbl)
        # 主题显示
        theme_name = self.config.get("theme", "dark")
        self.theme_lbl = QLabel(f"{tr('theme')}: {tr(theme_name)}")
        self.theme_lbl.setObjectName("chip")
        self.statusBar().addPermanentWidget(self.theme_lbl)
        self.statusBar().showMessage(tr("ready"))

    def refresh_theme(self):
        """主题切换后重新刷新所有动态颜色与图标。"""
        # 刷新会话树状态点与类型图标
        for i in range(self.tree.count()):
            it = self.tree.item(i)
            sid = it.data(Qt.UserRole)
            view = self.views.get(sid)
            status = view.channel.status.name if (view and view.channel) else "DISCONNECTED"
            it.setData(ROLE_STATUS, status)
            it.setIcon(icon(KIND_ICONS.get(it.data(Qt.UserRole + 2), "serial"), tokens()["text_dim"], 16))
        self.tree.viewport().update()
        # 刷新各会话视图的动态图标 + 重渲染日志（方向配色随主题变化）
        for view in self.views.values():
            if hasattr(view, "refresh_theme"):
                view.refresh_theme()
            body = getattr(view, "body", None)
            if hasattr(body, "_rerender"):
                body._rerender()
        # 刷新工具面板图标与状态栏标签
        if hasattr(self.tools, "refresh_theme"):
            self.tools.refresh_theme()
        self._refresh_action_icons()
        self._refresh_menu_icons()
        theme_name = self.config.get("theme", "dark")
        self.set_theme_label(theme_name)
        enc = self.config.get("default_encoding", "utf-8")
        self.enc_lbl.setText(f"ENC {enc}")
        self._repolish(self.enc_lbl)

    def set_theme_label(self, theme_name: str):
        """更新状态栏主题标签（供设置对话框即时预览同步）。"""
        try:
            self.theme_lbl.setText(f"{tr('theme')}: {tr(theme_name)}")
            self._repolish(self.theme_lbl)
        except RuntimeError:
            pass

    def _refresh_action_icons(self):
        """按主题刷新侧边栏与菜单动作的图标。"""
        for btn, name, color_key in (
            (self._new_btn, "add", "text"),
            (self._rename_btn, "rename", "text_dim"),
            (self._del_btn, "clear", "err"),
        ):
            btn.setIcon(icon(name, tokens()[color_key], 14))
        self._refresh_open_btn()

    def _toggle_tools(self):
        self.tools_dock.setVisible(not self.tools_dock.isVisible())

    def _launch_extension(self, plugin_id):
        """启动扩展型插件 — 每次创建新实例，支持多个独立窗口。"""
        for entry in self.plugins.window_entries():
            if entry["id"] == plugin_id:
                widget = entry["factory"](self)
                idx = len(self._extension_windows) + 1
                dlg = QDialog(self)
                dlg.setWindowTitle(f"{entry['name']} #{idx}")
                # dlg.resize(720, 560)
                dlg.adjustSize()
                dlg.resize(max(dlg.width(), 720), max(dlg.height(), 600))
                # dlg.setMinimumSize(560, 400)
                layout = QVBoxLayout(dlg)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addWidget(widget)
                # 窗口关闭时释放插件资源（若提供 shutdown）
                if hasattr(widget, "shutdown"):
                    dlg.finished.connect(lambda _=0, w=widget: w.shutdown())
                    dlg.destroyed.connect(lambda _=None, w=widget: w.shutdown())
                # 窗口关闭时从列表中移除
                dlg.destroyed.connect(lambda _=None, d=dlg: self._on_ext_closed(d))
                self._extension_windows.append(dlg)
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                break

    def _on_ext_closed(self, dlg):
        if dlg in self._extension_windows:
            self._extension_windows.remove(dlg)

    def _rebuild_plugin_tabs(self):
        """插件管理变更后，重建 dock 型 Tab 和扩展菜单。"""
        self.tools.remove_plugin_tabs()
        for name, w in self.plugins.dock_widgets(self):
            self.tools.add_dock_tab(name, w)
        self._build_ext_menu()

    # ================= 会话管理 =================
    def _new_session(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("new_session_title"))
        dlg.setMinimumWidth(340)
        fl = QFormLayout(dlg)
        kind = QComboBox()
        for key, label in KIND_LABELS.items():
            kind.addItem(tr(label), key)
        name = QLineEdit()
        name.setPlaceholderText(tr("name_placeholder"))
        fl.addRow(tr("type"), kind)
        fl.addRow(tr("name"), name)
        btns = QHBoxLayout()
        ok = QPushButton(tr("create"))
        ok.setObjectName("accent")
        cancel = QPushButton(tr("cancel"))
        cancel.setObjectName("ghost")
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        fl.addRow(btns)
        ok.clicked.connect(dlg.accept)
        cancel.clicked.connect(dlg.reject)
        if dlg.exec() == QDialog.Accepted:
            k = kind.currentData()
            sid = str(uuid.uuid4())[:8]
            session = {
                "id": sid,
                "kind": k,
                "name": name.text().strip() or tr(KIND_LABELS[k]),
                "cfg": {},
            }
            self._add_view(session)

    def _item_label(self, kind: str, name: str) -> str:
        """会话列表项显示文本（图标由 QListWidgetItem.setIcon 提供）。"""
        return name

    def _item_tooltip(self, kind: str, name: str) -> str:
        kind_label = tr(KIND_LABELS.get(kind, kind))
        return f"{kind_label} · {name}"

    def _add_view(self, session):
        view = SessionView(session, self.config, self.autoreply)
        view.main_window = self
        self.views[session["id"]] = view
        self.sessions.append(session)
        item = QListWidgetItem(self._item_label(session["kind"], session["name"]))
        item.setData(Qt.UserRole, session["id"])
        item.setData(Qt.UserRole + 2, session["kind"])  # 类型（供主题刷新重建图标）
        item.setIcon(icon(KIND_ICONS.get(session["kind"], "serial"), tokens()["text_dim"], 16))
        item.setToolTip(self._item_tooltip(session["kind"], session["name"]))
        self._set_item_status(item, "DISCONNECTED")
        self.tree.addItem(item)
        self.stack.addWidget(view)
        self.tree.setCurrentItem(item)
        self._update_empty_state()
        self._refresh_open_btn()
        # 遥测：记录会话创建
        get_telemetry(self.config).record_session(session["kind"])

    def _current_view(self):
        item = self.tree.currentItem()
        if not item:
            return None, None
        sid = item.data(Qt.UserRole)
        return self.views.get(sid), item

    def _on_select(self, cur, _prev):
        if not cur:
            return
        view, _ = self._current_view()
        if view:
            self.stack.setCurrentWidget(view)
            if view.channel:
                self.status_lbl.setText(view.channel.status.label)
            else:
                self.status_lbl.setText(tr("disconnected"))
                self.status_lbl.setObjectName("dim")
                self._repolish(self.status_lbl)
        self._refresh_open_btn()

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        view, _ = self._current_view()
        is_open = bool(view and view.channel)
        act_toggle = menu.addAction(
            icon("stop" if is_open else "play", tokens()["text"], 14),
            tr("close") if is_open else tr("open"),
        )
        menu.addSeparator()
        act_rename = menu.addAction(icon("rename", tokens()["text"], 14), tr("rename"))
        act_delete = menu.addAction(icon("clear", tokens()["err"], 14), tr("delete"))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == act_toggle:
            self.toggle_current()
        elif chosen == act_rename:
            self._rename_current()
        elif chosen == act_delete:
            self._delete_current()

    def toggle_current(self):
        view, _ = self._current_view()
        if view:
            self.toggle_session(view.session["id"])

    def toggle_session(self, sid: str):
        view = self.views.get(sid)
        if not view:
            return
        if view.channel:
            view.close_channel()
            self._refresh_item_status(sid, "DISCONNECTED")
            self._refresh_open_btn()
            cur, _ = self._current_view()
            if cur is view:
                self.status_lbl.setText(tr("disconnected"))
                self.status_lbl.setObjectName("dim")
                self._repolish(self.status_lbl)
        else:
            view.open_channel(self)
            self._refresh_open_btn()

    def _rename_current(self):
        view, item = self._current_view()
        if not view:
            return
        old = view.session["name"]
        name, ok = QInputDialog.getText(
            self, tr("rename_title"), tr("name_label"), QLineEdit.Normal, old
        )
        if ok and name.strip():
            new_name = name.strip()
            view.session["name"] = new_name
            item.setText(self._item_label(view.session["kind"], new_name))
            item.setToolTip(self._item_tooltip(view.session["kind"], new_name))
            view.refresh_title()

    def _delete_current(self):
        view, item = self._current_view()
        if not view:
            return
        ret = QMessageBox.question(
            self,
            tr("delete_title"),
            tr("delete_confirm").format(view.session["name"]),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        sid = view.session["id"]
        if view.channel:
            view.close_channel()
        self.stack.removeWidget(view)
        view.deleteLater()
        del self.views[sid]
        self.sessions = [s for s in self.sessions if s["id"] != sid]
        row = self.tree.row(item)
        self.tree.takeItem(row)
        self._update_empty_state()
        self._refresh_open_btn()

    # ================= 状态反馈 =================
    def _on_status(self, view, status):
        view.set_status_badge(status)
        self._refresh_item_status(view.session["id"], status.name)
        self._refresh_open_btn()
        cur, _ = self._current_view()
        if cur is view:
            self.status_lbl.setText(status.label)
            name = status.name
            obj = "dim"
            if name in ("CONNECTED", "LISTENING"):
                obj = "status_ok"
            elif name == "ERROR":
                obj = "status_err"
            self.status_lbl.setObjectName(obj)
            self._repolish(self.status_lbl)

    def _refresh_open_btn(self):
        """侧边栏“打开/关闭”按钮随当前会话状态更新图标与文字。"""
        view, _ = self._current_view()
        is_open = bool(view and view.channel)
        self._open_btn.setText(tr("close") if is_open else tr("toggle"))
        self._open_btn.setIcon(icon("stop" if is_open else "play", tokens()["text"], 14))

    def _on_error(self, msg):
        self.statusBar().showMessage(tr("error_msg").format(msg), 5000)

    def _refresh_item_status(self, sid, status_name):
        for i in range(self.tree.count()):
            it = self.tree.item(i)
            if it.data(Qt.UserRole) == sid:
                self._set_item_status(it, status_name)
                break

    def _set_item_status(self, item, status_name):
        """会话项状态可视化：由 delegate 在行尾绘制状态圆点。"""
        item.setData(ROLE_STATUS, status_name)
        self.tree.viewport().update()

    def _update_empty_state(self):
        has = self.tree.count() > 0
        self._empty.setVisible(not has)

    @staticmethod
    def _repolish(w):
        w.style().unpolish(w)
        w.style().polish(w)

    # ================= 菜单动作 =================
    def _open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply()

    def _open_plugins(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("plugin_manager"))
        dlg.resize(620, 360)
        pmw = PluginManagerWidget(self.plugins, self.config, dlg)
        layout = QVBoxLayout(dlg)
        layout.addWidget(pmw)
        # 确定按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("ok"), dlg)
        ok_btn.setObjectName("accent")
        ok_btn.clicked.connect(dlg.accept)
        btn_btn = QPushButton(tr("cancel"), dlg)
        btn_btn.setObjectName("ghost")
        btn_btn.clicked.connect(dlg.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(btn_btn)
        layout.addLayout(btn_layout)
        if dlg.exec() == QDialog.Accepted:
            pmw.apply_changes()
            # 更新工具面板中的插件 widgets
            self._rebuild_plugin_tabs()

    def _import_cfg(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, tr("import_config"), "", "JSON (*.json)"
        )
        if path:
            self.config.import_file(path)
            QMessageBox.information(self, tr("imported"), tr("config_imported"))

    def _export_cfg(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, tr("export_config"), "", "JSON (*.json)"
        )
        if path:
            self.config.export_file(path)

    # ================= 持久化 =================
    def _restore_sessions(self):
        for s in self.config.get("sessions", []):
            self._add_view(dict(s))

    def closeEvent(self, event):
        # 关闭所有扩展窗口
        for dlg in list(self._extension_windows):
            dlg.close()
        self._extension_windows.clear()
        self.config.set("sessions", self.sessions)
        self.config.save()
        super().closeEvent(event)
