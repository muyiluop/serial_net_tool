"""日志导出对话框：格式（TXT/CSV/Hex）+ 方向筛选 + 时间范围 + 预览。"""
from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)
from PySide6.QtCore import QDateTime

from ..core.i18n import tr

_PREVIEW_LINES = 50


class LogExportDialog(QDialog):
    """选择导出参数并预览结果。"""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(tr("export_log"))
        self.resize(580, 520)
        self._build()
        self._update_preview()

    # ---------- UI ----------
    def _build(self):
        layout = QVBoxLayout(self)

        # 格式
        fmt_box = QGroupBox(tr("export_format"))
        fmt_row = QHBoxLayout(fmt_box)
        self.rb_txt = QRadioButton("TXT")
        self.rb_csv = QRadioButton("CSV")
        self.rb_hex = QRadioButton(tr("export_hex"))
        self.rb_txt.setChecked(True)
        for rb in (self.rb_txt, self.rb_csv, self.rb_hex):
            rb.toggled.connect(self._on_fmt_changed)
            fmt_row.addWidget(rb)
        fmt_row.addStretch()
        layout.addWidget(fmt_box)

        # 筛选
        filter_box = QGroupBox(tr("export_filter"))
        grid = QGridLayout(filter_box)
        self.chk_tx = QCheckBox(tr("export_dir_tx"))
        self.chk_rx = QCheckBox(tr("export_dir_rx"))
        self.chk_tx.setChecked(True)
        self.chk_rx.setChecked(True)
        self.chk_ts = QCheckBox(tr("export_include_ts"))
        self.chk_ts.setChecked(True)
        self.chk_dir = QCheckBox(tr("export_include_dir"))
        self.chk_dir.setChecked(True)
        grid.addWidget(self.chk_tx, 0, 0)
        grid.addWidget(self.chk_rx, 0, 1)
        grid.addWidget(self.chk_ts, 1, 0)
        grid.addWidget(self.chk_dir, 1, 1)

        self.chk_time = QCheckBox(tr("export_time_range"))
        self.dt_from = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3600))
        self.dt_to = QDateTimeEdit(QDateTime.currentDateTime())
        for dt in (self.dt_from, self.dt_to):
            dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            dt.setCalendarPopup(True)
            dt.setEnabled(False)
        self.chk_time.toggled.connect(self.dt_from.setEnabled)
        self.chk_time.toggled.connect(self.dt_to.setEnabled)
        grid.addWidget(self.chk_time, 2, 0)
        grid.addWidget(self.dt_from, 2, 1)
        grid.addWidget(self.dt_to, 3, 1)
        grid.addWidget(QLabel(tr("export_from_to")), 3, 0)
        layout.addWidget(filter_box)

        # 预览
        layout.addWidget(QLabel(tr("export_preview")))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setObjectName("mono")
        layout.addWidget(self.preview, 1)

        # 按钮
        btns = QHBoxLayout()
        self.export_btn = QPushButton(tr("export_btn"))
        self.export_btn.setObjectName("accent")
        self.cancel_btn = QPushButton(tr("cancel"))
        self.cancel_btn.setObjectName("ghost")
        btns.addStretch()
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.export_btn)
        layout.addLayout(btns)

        # 信号
        for w in (self.chk_tx, self.chk_rx, self.chk_ts, self.chk_dir, self.chk_time):
            w.toggled.connect(self._update_preview)
        self.dt_from.dateTimeChanged.connect(self._update_preview)
        self.dt_to.dateTimeChanged.connect(self._update_preview)
        self.export_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def _on_fmt_changed(self, _checked=False):
        # Hex 格式不使用时间戳/方向列
        is_hex = self.rb_hex.isChecked()
        self.chk_ts.setEnabled(not is_hex)
        self.chk_dir.setEnabled(not is_hex)
        self._update_preview()

    # ---------- 数据 ----------
    def _collect_records(self) -> list:
        include_tx = self.chk_tx.isChecked()
        include_rx = self.chk_rx.isChecked()
        since = until = None
        if self.chk_time.isChecked():
            since = datetime.fromtimestamp(self.dt_from.dateTime().toSecsSinceEpoch())
            until = datetime.fromtimestamp(self.dt_to.dateTime().toSecsSinceEpoch())
        out = []
        for r in self.store.all():
            if r.direction == "tx" and not include_tx:
                continue
            if r.direction == "rx" and not include_rx:
                continue
            if since and r.ts < since:
                continue
            if until and r.ts > until:
                continue
            out.append(r)
        return out

    def build_text(self, records: list = None) -> str:
        """按当前选项生成导出文本。"""
        records = self._collect_records() if records is None else records
        if self.rb_csv.isChecked():
            return self.store.to_csv(records, self.chk_ts.isChecked(), self.chk_dir.isChecked())
        if self.rb_hex.isChecked():
            return self.store.to_hex(records)
        return self.store.to_txt(records, self.chk_ts.isChecked(), self.chk_dir.isChecked())

    def _update_preview(self):
        text = self.build_text()
        lines = text.splitlines()
        shown = lines[:_PREVIEW_LINES]
        if len(lines) > _PREVIEW_LINES:
            shown.append(f"... ({len(lines) - _PREVIEW_LINES} " + tr("export_more_lines") + ")")
        self.preview.setPlainText("\n".join(shown))

    def suffix(self) -> str:
        if self.rb_csv.isChecked():
            return "csv"
        if self.rb_hex.isChecked():
            return "hex"
        return "txt"
