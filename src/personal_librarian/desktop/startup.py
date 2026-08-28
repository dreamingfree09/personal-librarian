"""Packaged first-launch root selection and validation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from personal_librarian.production import application_data_layout, production_health
from personal_librarian.safety import PathIntent, PathSafetyPolicy


def validate_runtime_roots(
    app_data_root: str, independent_backup_root: str | None = None,
    *, safety_policy: PathSafetyPolicy | None = None,
) -> tuple[Path, Path | None]:
    policy = safety_policy or PathSafetyPolicy()
    if not app_data_root.strip():
        raise ValueError("Select an existing Personal Librarian application-data root.")
    layout = application_data_layout(app_data_root, safety_policy=policy)
    if not layout.root.is_dir() or not layout.catalogue_path.is_file():
        raise ValueError("The selected root does not contain a production catalogue.")
    independent = None
    if independent_backup_root and independent_backup_root.strip():
        result = policy.check_path(independent_backup_root, intent=PathIntent.READ)
        if not result.allowed:
            raise ValueError(f"Independent backup root is unsafe: {result.code}.")
        independent = Path(independent_backup_root)
        if not independent.is_dir():
            raise ValueError("The independent backup root is unavailable.")
    health = production_health(
        app_data_root=layout.root,
        independent_backup_root=independent,
        safety_policy=policy,
    ).values
    if health.get("summary") == "FAIL":
        raise ValueError("The selected production catalogue failed its health validation.")
    return layout.root, independent


class StartupDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Connect Personal Librarian")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        message = QLabel(
            "Select the existing application-data root. This dialog never creates or bootstraps a catalogue."
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        form = QFormLayout()
        self.app_root = QLineEdit()
        self.independent_root = QLineEdit()
        form.addRow("Application-data root", self._picker(self.app_root))
        form.addRow("Independent backup root (optional)", self._picker(self.independent_root))
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _picker(self, field: QLineEdit) -> QHBoxLayout:
        row = QHBoxLayout()
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse(field))
        row.addWidget(field)
        row.addWidget(browse)
        return row

    def _browse(self, field: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select existing folder")
        if selected:
            field.setText(selected)

    def _accept_checked(self) -> None:
        try:
            validate_runtime_roots(self.app_root.text(), self.independent_root.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot open catalogue", str(exc))
            return
        self.accept()
