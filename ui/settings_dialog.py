"""设置对话框：语言、主题、默认编码、匿名统计、遥测查看、配置导入导出。"""
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QComboBox,
    QCheckBox,
    QPushButton,
    QHBoxLayout,
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


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(tr("settings"))
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.lang = QComboBox()
        self.lang.addItems(["zh", "en"])
        self.lang.setCurrentText(self.config.get("language", "zh"))
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light", "system"])
        self.theme.setCurrentText(self.config.get("theme", "dark"))
        # 主题即时预览
        self.theme.currentTextChanged.connect(self._preview_theme)
        self.enc = QComboBox()
        self.enc.addItems(["utf-8", "gbk", "ascii"])
        self.enc.setCurrentText(self.config.get("default_encoding", "utf-8"))
        self.tele = QCheckBox()
        self.tele.setChecked(bool(self.config.get("telemetry", False)))
        form.addRow(tr("language"), self.lang)
        form.addRow(tr("theme"), self.theme)
        form.addRow(tr("default_encoding"), self.enc)
        form.addRow(tr("telemetry"), self.tele)
        tele_hint = QLabel(tr("telemetry_hint"))
        tele_hint.setObjectName("dim")
        form.addRow("", tele_hint)
        layout.addLayout(form)

        # 遥测统计查看
        tele_view = QHBoxLayout()
        self.tele_view_btn = QPushButton(tr("telemetry_view"))
        self.tele_view_btn.setObjectName("ghost")
        self.tele_clear_btn = QPushButton(tr("telemetry_clear"))
        self.tele_clear_btn.setObjectName("ghost")
        tele_view.addWidget(self.tele_view_btn)
        tele_view.addWidget(self.tele_clear_btn)
        tele_view.addStretch()
        layout.addLayout(tele_view)

        # 配置导入导出
        h = QHBoxLayout()
        self.imp = QPushButton(tr("import_config"))
        self.exp = QPushButton(tr("export_config"))
        h.addWidget(self.imp)
        h.addWidget(self.exp)
        layout.addLayout(h)

        btns = QHBoxLayout()
        self.ok = QPushButton(tr("ok"))
        self.cancel = QPushButton(tr("cancel"))
        btns.addStretch()
        btns.addWidget(self.ok)
        btns.addWidget(self.cancel)
        layout.addLayout(btns)

        self.ok.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        self.imp.clicked.connect(self._import)
        self.exp.clicked.connect(self._export)
        self.tele_view_btn.clicked.connect(self._view_telemetry)
        self.tele_clear_btn.clicked.connect(self._clear_telemetry)

    def _preview_theme(self, theme_name):
        """主题切换即时预览。"""
        apply_theme(QApplication.instance(), theme_name)

    def apply(self):
        self.config.set("language", self.lang.currentText())
        self.config.set("theme", self.theme.currentText())
        self.config.set("default_encoding", self.enc.currentText())
        self.config.set("telemetry", self.tele.isChecked())
        set_language(self.config.get("language"))
        apply_theme(QApplication.instance(), self.config.get("theme"))
        # 刷新主窗口的动态颜色（状态色、状态栏标签等）
        parent = self.parent()
        if parent and hasattr(parent, "refresh_theme"):
            parent.refresh_theme()
        QMessageBox.information(
            self, tr("notice"), tr("lang_hint")
        )

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
        summary = tele.get_summary()
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("telemetry_view"))
        dlg.resize(420, 360)
        dl = QVBoxLayout(dlg)
        te = QPlainTextEdit()
        te.setPlainText(summary)
        te.setReadOnly(True)
        dl.addWidget(te)
        close_btn = QPushButton(tr("close"))
        close_btn.clicked.connect(dlg.accept)
        dl.addWidget(close_btn)
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
