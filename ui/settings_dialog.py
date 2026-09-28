"""设置对话框：两列卡片布局（外观 / 通用 / 隐私 / 配置）。

规范：
- 控件定宽（约 170px），不再横跨整个对话框；
- 字段用「上标签 + 下控件」堆叠，与会话配置表单一致；
- 按钮层级：仅「确定」为 primary，其余为 ghost/secondary；
- 主题即时预览，并同步主窗口状态栏的主题标签。
"""
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QApplication,
    QPlainTextEdit,
    QLabel,
)
from ..core.config import Config
from ..core.i18n import set_language, tr
from ..core.theme import apply_theme
from ..core.telemetry import get_telemetry

_CTRL_W = 170


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self._orig_theme = config.get("theme", "dark")
        self.setWindowTitle(tr("settings"))
        self.setMinimumWidth(560)
        self._build()

    # ---------- 布局 ----------
    @staticmethod
    def _stacked(label: str, widget) -> QGroupBox:
        """上标签 + 下控件的紧凑字段块。"""
        box = QGroupBox()
        box.setStyleSheet("QGroupBox { border: none; margin: 0; padding: 0; }")
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        lab = QLabel(label)
        lab.setObjectName("h2")
        v.addWidget(lab)
        widget.setFixedWidth(_CTRL_W)
        v.addWidget(widget)
        return box

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        columns = QHBoxLayout()
        columns.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        right = QVBoxLayout()
        right.setSpacing(12)

        # ---- 外观 ----
        appear = QGroupBox(tr("settings_appearance"))
        appear_grid = QGridLayout(appear)
        appear_grid.setSpacing(10)
        self.lang = QComboBox()
        self.lang.addItems(["zh", "en"])
        self.lang.setCurrentText(self.config.get("language", "zh"))
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light", "system"])
        self.theme.setCurrentText(self.config.get("theme", "dark"))
        self.theme.currentTextChanged.connect(self._preview_theme)
        appear_grid.addWidget(self._stacked(tr("language"), self.lang), 0, 0)
        appear_grid.addWidget(self._stacked(tr("theme"), self.theme), 0, 1)
        theme_hint = QLabel(tr("theme_hint"))
        theme_hint.setObjectName("dim")
        appear_grid.addWidget(theme_hint, 1, 0, 1, 2)
        left.addWidget(appear)

        # ---- 通用 ----
        general = QGroupBox(tr("settings_general"))
        general_grid = QGridLayout(general)
        general_grid.setSpacing(10)
        self.enc = QComboBox()
        self.enc.addItems(["utf-8", "gbk", "ascii"])
        self.enc.setCurrentText(self.config.get("default_encoding", "utf-8"))
        general_grid.addWidget(self._stacked(tr("default_encoding"), self.enc), 0, 0)
        general_grid.setColumnStretch(1, 1)
        left.addWidget(general)
        left.addStretch()

        # ---- 隐私 ----
        privacy = QGroupBox(tr("settings_privacy"))
        privacy_layout = QVBoxLayout(privacy)
        privacy_layout.setSpacing(8)
        self.tele = QCheckBox(tr("telemetry"))
        self.tele.setChecked(bool(self.config.get("telemetry", False)))
        privacy_layout.addWidget(self.tele)
        tele_hint = QLabel(tr("telemetry_hint"))
        tele_hint.setObjectName("dim")
        tele_hint.setWordWrap(True)
        privacy_layout.addWidget(tele_hint)
        tele_row = QHBoxLayout()
        self.tele_view_btn = QPushButton(tr("telemetry_view"))
        self.tele_view_btn.setObjectName("ghost")
        self.tele_clear_btn = QPushButton(tr("telemetry_clear"))
        self.tele_clear_btn.setObjectName("ghost")
        tele_row.addWidget(self.tele_view_btn)
        tele_row.addWidget(self.tele_clear_btn)
        tele_row.addStretch()
        privacy_layout.addLayout(tele_row)
        right.addWidget(privacy)

        # ---- 配置 ----
        cfg_box = QGroupBox(tr("settings_config"))
        cfg_layout = QHBoxLayout(cfg_box)
        cfg_layout.setSpacing(8)
        self.imp = QPushButton(tr("import_config"))
        self.imp.setObjectName("secondary")
        self.exp = QPushButton(tr("export_config"))
        self.exp.setObjectName("secondary")
        cfg_layout.addWidget(self.imp)
        cfg_layout.addWidget(self.exp)
        cfg_layout.addStretch()
        right.addWidget(cfg_box)
        right.addStretch()

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        root.addLayout(columns)

        # ---- 按钮 ----
        btns = QHBoxLayout()
        self.ok = QPushButton(tr("ok"))
        self.ok.setObjectName("accent")
        self.ok.setMinimumWidth(84)
        self.cancel = QPushButton(tr("cancel"))
        self.cancel.setObjectName("ghost")
        btns.addStretch()
        btns.addWidget(self.cancel)
        btns.addWidget(self.ok)
        root.addLayout(btns)

        self.ok.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        self.imp.clicked.connect(self._import)
        self.exp.clicked.connect(self._export)
        self.tele_view_btn.clicked.connect(self._view_telemetry)
        self.tele_clear_btn.clicked.connect(self._clear_telemetry)

    # ---------- 主题预览 ----------
    def _preview_theme(self, theme_name):
        """主题即时预览，并同步主窗口状态栏标签。"""
        apply_theme(QApplication.instance(), theme_name)
        parent = self.parent()
        if parent and hasattr(parent, "set_theme_label"):
            parent.set_theme_label(theme_name)

    def reject(self):
        """取消时还原即时预览造成的主题变化。"""
        apply_theme(QApplication.instance(), self._orig_theme)
        parent = self.parent()
        if parent and hasattr(parent, "refresh_theme"):
            parent.refresh_theme()
        super().reject()

    # ---------- 应用 ----------
    def apply(self):
        self.config.set("language", self.lang.currentText())
        self.config.set("theme", self.theme.currentText())
        self.config.set("default_encoding", self.enc.currentText())
        self.config.set("telemetry", self.tele.isChecked())
        set_language(self.config.get("language"))
        apply_theme(QApplication.instance(), self.config.get("theme"))
        parent = self.parent()
        if parent and hasattr(parent, "refresh_theme"):
            parent.refresh_theme()
        QMessageBox.information(self, tr("notice"), tr("lang_hint"))

    # ---------- 导入导出 ----------
    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("import_config"), "", "JSON (*.json)")
        if path:
            self.config.import_file(path)
            QMessageBox.information(self, tr("imported"), tr("config_imported_hint"))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("export_config"), "", "JSON (*.json)")
        if path:
            self.config.export_file(path)

    def _view_telemetry(self):
        """查看遥测统计。"""
        tele = get_telemetry(self.config)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("telemetry_view"))
        dlg.resize(420, 360)
        dl = QVBoxLayout(dlg)
        te = QPlainTextEdit()
        te.setObjectName("mono")
        te.setPlainText(tele.get_summary())
        te.setReadOnly(True)
        dl.addWidget(te)
        close_btn = QPushButton(tr("close"))
        close_btn.setObjectName("ghost")
        close_btn.clicked.connect(dlg.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)
        dl.addLayout(row)
        dlg.exec()

    def _clear_telemetry(self):
        """清除遥测数据。"""
        ret = QMessageBox.question(
            self, tr("telemetry_clear"),
            tr("telemetry_clear_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            get_telemetry(self.config).clear()
            QMessageBox.information(self, tr("notice"), tr("telemetry_cleared"))
