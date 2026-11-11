"""Small presentation-only Quiet Archive primitives; no services or persistence."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLabel, QSizePolicy, QWidget

TOKENS = {
    "canvas": "#F5F6F3", "surface": "#FFFFFF", "ink": "#203C3A",
    "muted": "#5D6F6C", "accent": "#126557", "selection": "#E4F2EB",
    "line": "#D7E0DB", "focus": "#2456A6", "warning": "#87500B",
}


def apply_theme(widget: QWidget) -> None:
    """Scope styling to this page, never to the application or review workers."""
    widget.setObjectName("quietArchive")
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setStyleSheet("""
        QWidget#quietArchive, QWidget#archiveCanvas { background: %(canvas)s; color: %(ink)s; }
        QWidget#quietArchive QLabel { color: %(ink)s; }
        QWidget#quietArchive QLabel#pageTitle { font-size: 28px; font-weight: 600; }
        QWidget#quietArchive QLabel#metric { font-size: 28px; font-weight: 600; }
        QWidget#quietArchive QLabel#helpText { color: %(muted)s; }
        QWidget#quietArchive QLabel#boundaryNotice { background: %(selection)s; color: %(accent)s; padding: 10px; border-radius: 8px; }
        QWidget#quietArchive QGroupBox { background: %(surface)s; border: 1px solid %(line)s; border-radius: 14px; margin-top: 12px; padding: 18px 12px 12px; font-weight: 600; }
        QWidget#quietArchive QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 5px; }
        QWidget#quietArchive QPushButton { background: %(surface)s; color: %(ink)s; border: 1px solid %(line)s; border-radius: 8px; padding: 8px 12px; min-height: 20px; }
        QWidget#quietArchive QPushButton[primary="true"] { background: %(accent)s; color: white; }
        QWidget#quietArchive QPushButton:disabled { background: %(canvas)s; color: %(muted)s; border-color: %(line)s; }
        QWidget#quietArchive QPushButton:focus, QWidget#quietArchive QComboBox:focus,
        QWidget#quietArchive QLineEdit:focus, QWidget#quietArchive QListWidget:focus,
        QWidget#quietArchive QTableWidget:focus { border: 2px solid %(focus)s; }
        QWidget#quietArchive QComboBox, QWidget#quietArchive QLineEdit { background: %(surface)s; color: %(ink)s; border: 1px solid %(line)s; border-radius: 6px; padding: 6px; min-height: 22px; }
        QWidget#quietArchive QTabWidget::pane { border: 0; }
        QWidget#quietArchive QTabBar::tab { background: %(canvas)s; color: %(muted)s; padding: 10px 18px; }
        QWidget#quietArchive QTabBar::tab:selected { background: %(surface)s; color: %(accent)s; border-bottom: 3px solid %(accent)s; }
        QWidget#quietArchive QListWidget, QWidget#quietArchive QTableWidget { background: %(surface)s; color: %(ink)s; border: 1px solid %(line)s; border-radius: 8px; selection-background-color: %(selection)s; selection-color: %(ink)s; }
        QWidget#quietArchive QListWidget::item { padding: 6px; border: 1px solid transparent; }
        QWidget#quietArchive QListWidget::item:selected { background: %(selection)s; color: %(accent)s; border: 1px solid %(accent)s; border-radius: 6px; }
        QWidget#quietArchive QHeaderView::section { background: %(canvas)s; color: %(muted)s; padding: 7px; border: 0; }
        QWidget#quietArchive QScrollArea { border: 0; background: %(canvas)s; }
    """ % TOKENS)
    font = widget.font()
    font.setFamily("Segoe UI")
    font.setPointSize(10)
    widget.setFont(font)


def text_label(text: str, *, name: str = "", parent: QWidget | None = None) -> QLabel:
    label = QLabel(text, parent)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setObjectName(name)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setMinimumWidth(0)
    return label


class FlowLayout(QLayout):
    """Wrap existing controls without changing their identity, signals or ordering."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < self.count() else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < self.count() else None

    def addStretch(self, stretch=0):
        # Rows stay left aligned; a stretch would consume wrapping width.
        pass

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, apply):
        x, y, height = rect.x(), rect.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            # Ignored horizontal policy is useful for wrapping evidence labels,
            # but must not erase short labels in a control row.
            size = item.widget().sizeHint() if isinstance(item.widget(), QLabel) else item.sizeHint()
            width = min(size.width(), rect.width())
            if x > rect.x() and x + width > rect.right() + 1:
                x, y, height = rect.x(), y + height + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, size.height())))
            x += width + self.spacing()
            height = max(height, size.height())
        return y + height - rect.y()
