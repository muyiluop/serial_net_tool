"""插件管理面板（增强版 T8.2）：
- 启用/禁用 toggle：每行 checkbox 可切换插件启用状态
- 刷新按钮：重新扫描插件目录
- 错误详情：点击错误项可展开查看完整 traceback
- 持久化：启用/禁用状态保存到 config
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QPushButton,
    QCheckBox,
    QHeaderView,
    QPlainTextEdit,
    QDialog,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from ..core.plugin_manager import PluginManager
from ..core.i18n import tr
from ..core.theme import tokens


class PluginManagerWidget(QWidget):
    def __init__(self, manager: PluginManager, config=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.config = config
        self._build()
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 顶部：说明 + 刷新按钮
        top = QHBoxLayout()
        hint = QLabel(tr("plugins_loaded_hint"))
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        top.addWidget(hint, 1)
        self.refresh_btn = QPushButton(tr("refresh"))
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.clicked.connect(self._on_refresh)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        # 插件列表表
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            tr("col_enabled"), tr("name"), tr("status"), tr("error")
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.cellDoubleClicked.connect(self._on_cell_double_click)
        layout.addWidget(self.table)

    def refresh(self):
        ps = self.manager.plugins
        self.table.setRowCount(len(ps))
        for i, p in enumerate(ps):
            ok = p.get("enabled") and not p.get("error")

            # 启用/禁用 checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(chk_item.flags() | Qt.ItemIsUserCheckable)
            chk_item.setCheckState(Qt.Checked if p.get("enabled", True) else Qt.Unchecked)
            self.table.setItem(i, 0, chk_item)

            # 名称（含版本/描述提示）
            name_item = QTableWidgetItem(p["name"])
            tip_lines = [f"{p['name']}  v{p.get('version') or '-'}"]
            if p.get("author"):
                tip_lines.append(str(p["author"]))
            if p.get("description"):
                tip_lines.append(str(p["description"]))
            name_item.setToolTip("\n".join(tip_lines))
            self.table.setItem(i, 1, name_item)

            # 状态（以状态色区分）
            status_text = tr("enabled") if ok else tr("error_or_disabled")
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(tokens()["ok"] if ok else tokens()["err"]))
            self.table.setItem(i, 2, status_item)

            # 错误信息（截断显示，等宽便于阅读 traceback）
            err = p.get("error") or ""
            if len(err) > 200:
                err = err[:200] + "..."
            err_item = QTableWidgetItem(err)
            err_item.setFont(QFont("Consolas", 9))
            self.table.setItem(i, 3, err_item)

    def _on_refresh(self):
        """重新扫描插件目录（discover 已内含禁用状态恢复）。"""
        self.manager.discover()
        self.refresh()

    def _on_cell_double_click(self, row, col):
        """双击错误列查看完整 traceback。"""
        if col != 3:
            return
        ps = self.manager.plugins
        if row >= len(ps):
            return
        err = ps[row].get("error") or ""
        if not err:
            return
        # 弹出详情对话框
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("plugin_error_detail"))
        dlg.resize(640, 400)
        dl = QVBoxLayout(dlg)
        te = QPlainTextEdit()
        te.setPlainText(err)
        te.setReadOnly(True)
        dl.addWidget(te)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.reject)
        dl.addWidget(btns)
        dlg.exec()

    def apply_changes(self):
        """将 checkbox 状态写回 plugin manager 并持久化。"""
        disabled_ids = []
        for i in range(self.table.rowCount()):
            chk = self.table.item(i, 0)
            if chk and chk.checkState() == Qt.Unchecked:
                disabled_ids.append(self.manager.plugins[i]["id"])
                self.manager.plugins[i]["enabled"] = False
            else:
                self.manager.plugins[i]["enabled"] = True
        if self.config:
            self.config.set("disabled_plugins", disabled_ids)
