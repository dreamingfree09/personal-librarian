"""Read-only zoomable image preview dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class ImageViewerDialog(QDialog):
    def __init__(
        self,
        image: QImage,
        metadata: str,
        technical_metadata: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Read-only image preview")
        self.resize(1000, 760)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        for text, handler, tooltip in (
            ("Zoom in", self.zoom_in, "Zoom in (Ctrl++)"),
            ("Zoom out", self.zoom_out, "Zoom out (Ctrl+-)"),
            ("Fit", self.fit_to_window, "Fit image to window (F)"),
            ("100%", self.actual_size, "Show one image pixel per screen pixel (1)"),
        ):
            button = QPushButton(text)
            button.setToolTip(tooltip)
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        self.scene = QGraphicsScene(self)
        self.pixmap_item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        self.scene.addItem(self.pixmap_item)
        self.view = QGraphicsView(self.scene)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setAccessibleName("Zoomable read-only image preview")
        layout.addWidget(self.view, 1)
        self.primary_details = QLabel(metadata)
        self.primary_details.setObjectName("viewerPrimaryDetails")
        self.primary_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.primary_details.setWordWrap(True)
        layout.addWidget(self.primary_details)
        self.technical_toggle = QToolButton()
        self.technical_toggle.setText("Show technical details")
        self.technical_toggle.setCheckable(True)
        self.technical_toggle.setChecked(False)
        self.technical_toggle.setVisible(bool(technical_metadata))
        layout.addWidget(self.technical_toggle)
        self.technical_details = QLabel(technical_metadata)
        self.technical_details.setObjectName("viewerTechnicalDetails")
        self.technical_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.technical_details.setWordWrap(True)
        self.technical_details.setVisible(False)
        self.technical_toggle.toggled.connect(self.technical_details.setVisible)
        self.technical_toggle.toggled.connect(
            lambda checked: self.technical_toggle.setText(
                "Hide technical details" if checked else "Show technical details"
            )
        )
        layout.addWidget(self.technical_details)
        self.setStyleSheet(
            "QLabel#viewerPrimaryDetails { padding: 8px; background: #f4f7f9; }"
            "QLabel#viewerTechnicalDetails { color: #555; padding: 6px; }"
        )
        QShortcut(QKeySequence.ZoomIn, self, activated=self.zoom_in)
        QShortcut(QKeySequence.ZoomOut, self, activated=self.zoom_out)
        QShortcut(QKeySequence("F"), self, activated=self.fit_to_window)
        QShortcut(QKeySequence("1"), self, activated=self.actual_size)
        QShortcut(QKeySequence.Cancel, self, activated=self.close)

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        self.fit_to_window()

    def zoom_in(self) -> None:
        self.view.scale(1.25, 1.25)

    def zoom_out(self) -> None:
        self.view.scale(0.8, 0.8)

    def fit_to_window(self) -> None:
        self.view.fitInView(self.pixmap_item, Qt.KeepAspectRatio)

    def actual_size(self) -> None:
        self.view.resetTransform()
