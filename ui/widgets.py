"""可复用的通用 UI 小组件（折叠区、卡片等）。"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, Signal


class _HeaderFrame(QFrame):
    """折叠区标题栏：仅在未被子控件(如按钮)消耗时响应整栏点击。"""

    def __init__(self, on_toggle, parent=None):
        super().__init__(parent)
        self._on_toggle = on_toggle

    def mousePressEvent(self, event):
        # 若点击落在某个子控件上，让子控件自行处理（不触发折叠）
        child = self.childAt(event.position().toPoint())
        if child is not None and child is not self:
            event.ignore()
            return
        if callable(self._on_toggle):
            self._on_toggle()
        event.accept()


class CollapsibleSection(QWidget):
    """可折叠区域：标题栏(可点击展开/收起) + 内容区。

    - collapsed=True 时只显示标题栏，内容隐藏，常用于节省纵向空间。
    - title 右侧可追加任意操作按钮（如“打开/关闭”）。
    - 对外提供 toggled 信号与 set_collapsed()/is_collapsed()。
    """

    toggled = Signal(bool)  # True=展开, False=收起

    def __init__(self, title: str = "", collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = _HeaderFrame(self.toggle)
        self._header.setObjectName("collapsible_header")
        h = QHBoxLayout(self._header)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)
        self._arrow = QLabel("▸" if collapsed else "▾")
        self._arrow.setObjectName("dim")
        self._title = QLabel(title)
        self._title.setObjectName("h1")
        h.addWidget(self._arrow)
        h.addWidget(self._title)
        h.addStretch()
        self._header_btns = QHBoxLayout()
        self._header_btns.setSpacing(6)
        h.addLayout(self._header_btns)
        root.addWidget(self._header)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(10, 4, 10, 10)
        self._content_layout.setSpacing(6)
        root.addWidget(self._content)

        self._header.setCursor(Qt.PointingHandCursor)
        self._apply()

    def add_header_widget(self, w: QWidget):
        """在标题栏右侧追加控件（如按钮）。"""
        self._header_btns.addWidget(w)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_content_widget(self, w: QWidget):
        self._content_layout.addWidget(w)

    def set_title(self, text: str):
        self._title.setText(text)

    def title(self) -> str:
        return self._title.text()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool):
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self._apply()
        self.toggled.emit(not collapsed)

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def _apply(self):
        self._content.setVisible(not self._collapsed)
        self._arrow.setText("▸" if self._collapsed else "▾")
