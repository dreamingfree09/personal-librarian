"""Year-centred owner organisation UI over the schema-9 service facade."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QScrollArea, QSizePolicy,
)

from personal_librarian.desktop.quiet_archive import FlowLayout, apply_theme
from personal_librarian.desktop.preferences import UiPreferences
from personal_librarian.desktop.services import DesktopDataService
from personal_librarian.desktop.thumbnails import ThumbnailService, ThumbnailTask, thumbnail_icon_size
from personal_librarian.desktop.ui_helpers import display_timestamp, format_bytes, item_filename


CONTENT_ROLE = int(Qt.ItemDataRole.UserRole)
INSTANCE_ROLE = CONTENT_ROLE + 1
PATH_ROLE = CONTENT_ROLE + 2
GENERATION_ROLE = CONTENT_ROLE + 3
ALBUM_ROLE = CONTENT_ROLE + 4
TAG_ROLE = CONTENT_ROLE + 5
COLLECTION_ROLE = CONTENT_ROLE + 6
MEMBERSHIP_STATE_ROLE = CONTENT_ROLE + 7
MAX_MUTATION_SELECTION = 50


_EVIDENCE_LABELS = {
    "owner_set": "Owner-set",
    "exif_datetime_original": "EXIF DateTimeOriginal",
    "embedded_video_capture": "Embedded video capture",
    "google_photos_takeout": "Google Photos Takeout",
    "onedrive_source_metadata": "OneDrive source metadata",
    "filename_derived": "Filename-derived",
    "filesystem_modified": "Filesystem modified",
    "filesystem_created": "Filesystem created",
    "specialist_import": "Specialist import",
}


def format_preferred_value(row: dict[str, Any] | None) -> str:
    if not row or row.get("preferred_status", row.get("status")) != "resolved":
        return "Unknown Date"
    precision = row.get("selected_precision")
    year = int(row["selected_year"])
    if precision == "year":
        return f"{year:04d}"
    month = int(row["selected_month"])
    if precision == "year_month":
        return f"{year:04d}-{month:02d}"
    day = int(row["selected_day"])
    rendered = f"{year:04d}-{month:02d}-{day:02d}"
    if precision != "datetime":
        return rendered
    rendered += f" {int(row['selected_hour']):02d}:{int(row['selected_minute']):02d}"
    if row.get("selected_second") is not None:
        rendered += f":{int(row['selected_second']):02d}"
    fraction = row.get("selected_fraction")
    if fraction:
        rendered += f".{fraction}"
    if row.get("selected_timezone_state") == "known_offset":
        offset = int(row.get("selected_utc_offset_minutes") or 0)
        sign = "+" if offset >= 0 else "-"
        rendered += f"{sign}{abs(offset) // 60:02d}:{abs(offset) % 60:02d}"
    return rendered


def preferred_summary(row: dict[str, Any]) -> tuple[str, str, str]:
    status = row.get("preferred_status", row.get("status")) or "unknown"
    if status == "resolved":
        source = (
            "Owner-set" if row.get("selection_method") == "owner_selection"
            else _EVIDENCE_LABELS.get(
                str(row.get("selected_evidence_type")),
                str(row.get("selected_evidence_source_field") or "Policy-selected"),
            )
        )
        return format_preferred_value(row), source, "Resolved"
    if status == "needs_review":
        return "Date needs review", str(row.get("reason") or "Conflicting evidence"), "Needs review"
    return "Unknown Date", str(row.get("reason") or "No resolved preferred date"), "Unknown"


@dataclass(frozen=True, slots=True)
class LibraryPreviewBinding:
    generation: int
    context: str
    content_identity_id: int
    physical_instance_id: int
    source_path: str


class _Signals(QObject):
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()


class _Worker(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:
            try:
                self.signals.failed.emit(str(exc))
            except RuntimeError:
                pass  # The Library page may have closed while the operation finished.
        else:
            try:
                self.signals.completed.emit(result)
            except RuntimeError:
                pass  # The Library page may have closed while the operation finished.
        finally:
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class CreateAlbumDialog(QDialog):
    """Named album fields; actor and reason deliberately do not enter this form."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create album")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        self.description = QPlainTextEdit()
        self.description.setPlainText("")
        self.description.setPlaceholderText("Optional; leave blank for no description")
        self.description.setMaximumHeight(120)
        form.addRow("Album name", self.name)
        form.addRow("Description (optional)", self.description)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name.setFocus()

    def values(self) -> tuple[str, str | None]:
        return self.name.text().strip(), self.description.toPlainText().strip() or None


class CreateCollectionDialog(QDialog):
    """Collection entity fields; owner evidence stays on the Library page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Collection")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Optional; leave blank for no description")
        self.description.setMaximumHeight(120)
        form.addRow("Collection name", self.name)
        form.addRow("Description (optional)", self.description)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name.setFocus()

    def values(self) -> tuple[str, str | None]:
        return self.name.text().strip(), self.description.toPlainText().strip() or None


class OwnerPreferredDateDialog(QDialog):
    def __init__(
        self, content_identity_id: int, current: dict[str, Any] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set preferred date")
        layout = QVBoxLayout(self)
        current_text = format_preferred_value(current) if current else "No preferred date"
        layout.addWidget(QLabel(
            f"Content {content_identity_id}\nCurrent interpretation: {current_text}\n"
            "Raw evidence remains unchanged."
        ))
        form = QFormLayout()
        self.precision = QComboBox()
        self.precision.addItems(("Year", "Year-month", "Date", "Date and time"))
        self.value = QLineEdit()
        self.value.setPlaceholderText("Examples: 2019, 2019-08, 2019-08-14, 2019-08-14T16:30+01:00")
        form.addRow("Genuine precision", self.precision)
        form.addRow("Exact value", self.value)
        layout.addLayout(form)
        self.replacement = QCheckBox("Explicitly replace the current owner-set selection")
        self.replacement.setVisible(bool(current and current.get("selection_method") == "owner_selection"))
        layout.addWidget(self.replacement)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, bool]:
        precision = ("year", "year_month", "date", "datetime")[self.precision.currentIndex()]
        return precision, self.value.text().strip(), self.replacement.isChecked()


class DateEvidenceDialog(QDialog):
    def __init__(self, detail: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferred date and raw evidence")
        self.resize(1050, 520)
        layout = QVBoxLayout(self)
        preferred = detail.get("preferred_date")
        evidence = detail.get("evidence", [])
        value, source, status = preferred_summary(preferred or {})
        selected = next(
            (row for row in evidence if "selected" in row.get("basis_roles", [])), None
        )
        if selected is not None and (preferred or {}).get("selection_method") != "owner_selection":
            source = _EVIDENCE_LABELS.get(
                str(selected.get("evidence_type")), str(selected.get("evidence_type"))
            )
        reason = detail.get("reason") or "—"
        precision = (preferred or {}).get("selected_precision") or "none"
        provenance = (preferred or {}).get("provenance") or "—"
        actor = (preferred or {}).get("actor_identifier") or "—"
        layout.addWidget(QLabel(
            f"Preferred interpretation: {value} · {status}\n"
            f"Selection: {source} · Precision: {precision} · "
            f"Method: {(preferred or {}).get('selection_method') or 'none'}\n"
            f"Preferred provenance: {provenance} · Actor/policy: {actor}\n"
            f"Reason: {reason}\nRaw evidence below is preserved; the preferred date is an interpretation."
        ))
        self.table = QTableWidget(len(evidence), 9)
        self.table.setHorizontalHeaderLabels((
            "Type", "Raw value", "Precision", "Source field", "Source",
            "Path", "Basis role", "Timezone", "Provenance",
        ))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for row_index, row in enumerate(evidence):
            timezone = row.get("timezone_state") or "—"
            if row.get("utc_offset_minutes") is not None:
                timezone += f" ({int(row['utc_offset_minutes']):+d} min)"
            values = (
                _EVIDENCE_LABELS.get(str(row.get("evidence_type")), row.get("evidence_type")),
                row.get("raw_value"), row.get("precision"), row.get("source_field"),
                row.get("source_name"), row.get("current_observed_path") or row.get("raw_relative_path"),
                ", ".join(row.get("basis_roles", [])) or "—", timezone, row.get("provenance"),
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value or "—")))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class LibraryPage(QWidget):
    """Bounded Year-first browser with schema-aware dates and logical organisation."""

    def __init__(self, service: DesktopDataService, preferences: UiPreferences) -> None:
        super().__init__()
        self.service = service
        apply_theme(self)
        self.pool = QThreadPool.globalInstance()
        self._active_workers: set[_Worker] = set()
        self.page_size = preferences.page_size
        self.offset = 0
        self.total = 0
        self.current_year: int | None = preferences.last_year
        self.has_year_selection = preferences.last_year is not None
        self.content_rows: list[dict[str, Any]] = []
        self.album_rows: list[dict[str, Any]] = []
        self.member_rows: list[dict[str, Any]] = []
        self.collection_rows: list[dict[str, Any]] = []
        self.collection_member_rows: list[dict[str, Any]] = []
        self.collection_offset = 0
        self.collection_total = 0
        self.collection_member_offset = 0
        self.collection_member_total = 0
        self._loaded_collection_uuid: str | None = None
        self.history_offset = 0
        self.history_total = 0
        self._history_context: tuple[str, str] | None = None
        self.schema_version = 0
        self.m30_enabled = False
        self._generation = 0
        self._year_request_generation = 0
        self._album_request_generation = 0
        self._album_member_request: tuple[int, str] | None = None
        self._loaded_album_uuid: str | None = None
        self._collection_request_generation = 0
        self._history_request_generation = 0
        self.thumbnail_service = ThumbnailService(service.layout.root, max_size=(160, 160))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        heading = QLabel("Library")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        notice = QLabel(
            "Browse by year. Albums, tags and Collections are logical groupings — they never "
            "create folders or move files. Date evidence and history remain available."
        )
        notice.setObjectName("boundaryNotice")
        notice.setWordWrap(True)
        notice.setToolTip("Raw date evidence is preserved separately from the preferred interpretation.")
        layout.addWidget(notice)
        actor_row = FlowLayout()
        actor_row.addWidget(QLabel("Owner / actor"))
        self.actor = QLineEdit(preferences.last_actor)
        self.actor.setPlaceholderText("Required for changes")
        self.actor.setToolTip("An explicit owner or actor is required for every organisation change.")
        self.actor.setMaximumWidth(320)
        self.actor.setMinimumWidth(230)
        actor_row.addWidget(self.actor)
        actor_row.addWidget(QLabel("Reason (optional)"))
        self.reason = QLineEdit()
        self.reason.setMaximumWidth(420)
        self.reason.setMinimumWidth(180)
        actor_row.addWidget(self.reason)
        actor_row.addStretch()
        layout.addLayout(actor_row)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self._build_years_tab()
        self._build_collections_tab()
        self._build_tags_tab()
        self._build_history_tab()
        self._label_controls()
        self.tabs.setCurrentIndex(preferences.library_tab)
        self.collection_filter.setCurrentText(preferences.collection_filter.title())

    def _build_years_tab(self) -> None:
        tab = QWidget()
        root = QHBoxLayout(tab)
        # A layout propagates wrapped control heights to the outer scroll area.
        # A splitter here hides height-for-width and can clip the final action.
        self.years = QListWidget()
        self.years.setMinimumWidth(170)
        self.years.setMaximumWidth(215)
        self.years.setSpacing(5)
        self.years.setAccessibleName("Year shelves, including Unknown Date")
        self.years.itemSelectionChanged.connect(self._year_selected)
        root.addWidget(self.years)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.year_heading = QLabel("Select a year")
        self.year_heading.setObjectName("pageTitle")
        right_layout.addWidget(self.year_heading)
        album_controls = FlowLayout()
        album_controls.addWidget(QLabel("Albums"))
        self.album_filter = QComboBox()
        self.album_filter.addItems(("Active", "Archived", "All"))
        self.album_filter.currentIndexChanged.connect(self._render_albums)
        album_controls.addWidget(self.album_filter)
        for label, handler in (
            ("Create album", self._create_album), ("Rename", self._rename_album),
            ("Archive / restore", self._toggle_album), ("View history", self._view_album_history),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            album_controls.addWidget(button)
        album_controls.addStretch()
        right_layout.addLayout(album_controls)
        self.albums = QTableWidget(0, 6)
        self.albums.setHorizontalHeaderLabels(
            ("Name", "Members in year", "State", "Created", "Creator", "UUID")
        )
        self.albums.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.albums.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.albums.setSelectionMode(QAbstractItemView.SingleSelection)
        self.albums.setMaximumHeight(190)
        self.albums.itemSelectionChanged.connect(self._album_selected)
        right_layout.addWidget(self.albums)
        self.album_message = QLabel("No albums have been created for this year yet.")
        right_layout.addWidget(self.album_message)
        browser_controls = FlowLayout()
        self.unorganised = QComboBox()
        self.unorganised.addItems(("All Photos & Videos", "Unsorted / Not yet organised"))
        self.unorganised.currentIndexChanged.connect(self._filter_changed)
        browser_controls.addWidget(self.unorganised)
        self.date_filter = QComboBox()
        self.date_filter.addItems(("Selected shelf", "Needs review", "Unknown only"))
        self.date_filter.currentIndexChanged.connect(self._date_filter_changed)
        browser_controls.addWidget(self.date_filter)
        self.previous = QPushButton("Previous")
        self.next = QPushButton("Next")
        self.previous.clicked.connect(lambda: self._move_page(-1))
        self.next.clicked.connect(lambda: self._move_page(1))
        browser_controls.addWidget(self.previous)
        browser_controls.addWidget(self.next)
        self.add_button = QPushButton("Add selected to album")
        self.add_button.clicked.connect(self._add_selected)
        browser_controls.addWidget(self.add_button)
        browser_controls.addStretch()
        right_layout.addLayout(browser_controls)
        self.content_message = QLabel("No content with reliable year evidence was found.")
        right_layout.addWidget(self.content_message)
        content_split = QSplitter(Qt.Horizontal)
        self.content_split = content_split
        self.content = self._preview_list(multi=True)
        self.content.itemSelectionChanged.connect(self._content_selected)
        content_split.addWidget(self.content)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.content_detail = QLabel("Select content to see its logical organisation.")
        self.content_detail.setWordWrap(True)
        self.content_detail_scroll = QScrollArea()
        self.content_detail_scroll.setWidgetResizable(True)
        self.content_detail_scroll.setMinimumHeight(100)
        self.content_detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_detail_scroll.setAccessibleName("Selected content organisation details")
        self.content_detail_scroll.setWidget(self.content_detail)
        detail_layout.addWidget(self.content_detail_scroll)
        date_actions = FlowLayout()
        self.evidence_button = QPushButton("View date evidence")
        self.evidence_button.clicked.connect(self._view_date_evidence)
        self.owner_date_button = QPushButton("Set / replace preferred date")
        self.owner_date_button.clicked.connect(self._set_owner_date)
        date_actions.addWidget(self.evidence_button)
        date_actions.addWidget(self.owner_date_button)
        detail_layout.addLayout(date_actions)
        self.album_detail = QLabel("Select an album to view its members.")
        self.album_detail.setWordWrap(True)
        detail_layout.addWidget(self.album_detail)
        self.members = self._preview_list(multi=True)
        detail_layout.addWidget(self.members)
        self.remove_button = QPushButton("Remove selected from album")
        self.remove_button.clicked.connect(self._remove_selected)
        self.remove_button.setEnabled(False)
        detail_layout.addWidget(self.remove_button)
        content_split.addWidget(detail)
        content_split.setSizes([700, 420])
        content_split.setMinimumHeight(350)
        detail.setMinimumWidth(0)
        right_layout.addWidget(content_split)
        root.addWidget(right, 1)
        self.tabs.addTab(self._scroll_tab(tab), "Years")
        # Let the outer Years page scroll rather than starving the Albums row.
        # Reserve scrollbar space even when hidden to avoid resize oscillation.
        self.albums.ensurePolished()
        self.albums.setMinimumHeight(
            2 * self.albums.frameWidth()
            + self.albums.horizontalHeader().sizeHint().height()
            + self.albums.verticalHeader().defaultSectionSize()
            + self.albums.horizontalScrollBar().sizeHint().height()
        )

    def _build_collections_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        heading = QLabel("Collections · across all years")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        self.collection_availability = QLabel(
            "Collections require schema-10. Compatibility mode does not fake them with tags "
            "and never queries schema-10 tables."
        )
        self.collection_availability.setWordWrap(True)
        self.collection_availability.setObjectName("boundaryNotice")
        layout.addWidget(self.collection_availability)
        controls = FlowLayout()
        self.collection_filter = QComboBox()
        self.collection_filter.addItems(("Active", "Archived", "All"))
        self.collection_filter.currentIndexChanged.connect(self._collections_filter_changed)
        controls.addWidget(QLabel("Show"))
        controls.addWidget(self.collection_filter)
        self.collection_include_removed = QCheckBox("Include removed members")
        self.collection_include_removed.stateChanged.connect(
            self._collection_member_filter_changed
        )
        controls.addWidget(self.collection_include_removed)
        self.collection_mutation_buttons: list[QPushButton] = []
        for label, handler in (
            ("Create", self._create_collection), ("Rename", self._rename_collection),
            ("Archive / restore", self._toggle_collection),
            ("Add selected Year content", self._add_to_collection),
            ("View history", self._view_collection_history),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
            self.collection_mutation_buttons.append(button)
        controls.addStretch()
        layout.addLayout(controls)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.collection_message = QLabel("No Collections loaded.")
        left_layout.addWidget(self.collection_message)
        self.collection_table = QTableWidget(0, 7)
        self.collection_table.setHorizontalHeaderLabels(
            ("Name", "Short UUID", "State", "Active", "Removed", "Created", "Creator")
        )
        self.collection_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.collection_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.collection_table.itemSelectionChanged.connect(self._collection_selected)
        left_layout.addWidget(self.collection_table)
        collection_pages = FlowLayout()
        self.collection_previous = QPushButton("Previous Collections")
        self.collection_next = QPushButton("Next Collections")
        self.collection_previous.clicked.connect(lambda: self._move_collection_page(-1))
        self.collection_next.clicked.connect(lambda: self._move_collection_page(1))
        collection_pages.addWidget(self.collection_previous)
        collection_pages.addWidget(self.collection_next)
        collection_pages.addStretch()
        left_layout.addLayout(collection_pages)
        split.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.collection_detail = QLabel("Select a Collection to view its logical members.")
        self.collection_detail.setWordWrap(True)
        right_layout.addWidget(self.collection_detail)
        self.collection_members = self._preview_list(multi=True)
        right_layout.addWidget(self.collection_members)
        member_pages = FlowLayout()
        self.collection_member_previous = QPushButton("Previous members")
        self.collection_member_next = QPushButton("Next members")
        self.collection_member_previous.clicked.connect(
            lambda: self._move_collection_member_page(-1)
        )
        self.collection_member_next.clicked.connect(
            lambda: self._move_collection_member_page(1)
        )
        member_pages.addWidget(self.collection_member_previous)
        member_pages.addWidget(self.collection_member_next)
        member_pages.addStretch()
        right_layout.addLayout(member_pages)
        member_controls = FlowLayout()
        remove = QPushButton("Remove selected")
        remove.clicked.connect(lambda: self._change_collection_members("remove"))
        restore = QPushButton("Restore selected")
        restore.clicked.connect(lambda: self._change_collection_members("restore"))
        member_controls.addWidget(remove)
        member_controls.addWidget(restore)
        self.collection_mutation_buttons.extend((remove, restore))
        member_controls.addStretch()
        right_layout.addLayout(member_controls)
        split.addWidget(right)
        split.setSizes([520, 680])
        layout.addWidget(split)
        self.tabs.addTab(self._scroll_tab(tab), "Collections")

    def _build_tags_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Tags are owner-created descriptive labels, not albums or Collections."))
        controls = FlowLayout()
        create = QPushButton("Create tag")
        create.clicked.connect(self._create_tag)
        add = QPushButton("Add tag to selected content")
        add.clicked.connect(lambda: self._tag_selected(True))
        remove = QPushButton("Remove tag from selected content")
        remove.clicked.connect(lambda: self._tag_selected(False))
        controls.addWidget(create)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch()
        layout.addLayout(controls)
        self.tag_message = QLabel("No tags have been created yet.")
        layout.addWidget(self.tag_message)
        self.tags = QListWidget()
        layout.addWidget(self.tags)
        self.tabs.addTab(self._scroll_tab(tab), "Tags")

    def _build_history_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = FlowLayout()
        self.history_domain = QComboBox()
        self.history_domain.addItems(("All", "Albums / Tags", "Collections", "Preferred Dates"))
        self.history_domain.currentIndexChanged.connect(self._history_filter_changed)
        controls.addWidget(QLabel("Domain"))
        controls.addWidget(self.history_domain)
        refresh = QPushButton("Refresh read-only history")
        refresh.clicked.connect(lambda: self._load_history())
        controls.addWidget(refresh)
        self.history_previous = QPushButton("Previous")
        self.history_next = QPushButton("Next")
        self.history_previous.clicked.connect(lambda: self._move_history_page(-1))
        self.history_next.clicked.connect(lambda: self._move_history_page(1))
        controls.addWidget(self.history_previous)
        controls.addWidget(self.history_next)
        controls.addStretch()
        layout.addLayout(controls)
        self.history_message = QLabel("No organisation history exists yet.")
        layout.addWidget(self.history_message)
        self.history = QTableWidget(0, 9)
        self.history.setHorizontalHeaderLabels(
            ("Timestamp", "Operation", "Actor", "Album", "Tag", "Collection", "Content", "Reason", "Provenance")
        )
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.history)
        self.tabs.addTab(self._scroll_tab(tab), "History")

    @staticmethod
    def _scroll_tab(tab: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tab.setMinimumWidth(0)
        tab.setObjectName("archiveCanvas")
        scroll.setWidget(tab)
        return scroll

    def _label_controls(self) -> None:
        names = ((self.actor, "Owner or actor; required for changes"),
                 (self.reason, "Optional reason for the explicit owner change"),
                 (self.tabs, "Library views"), (self.content, "Content in the selected year or date filter"),
                 (self.members, "Selected Album members"), (self.albums, "Logical Albums in this year"),
                 (self.collection_table, "Collections across all years"),
                 (self.collection_members, "Selected Collection members"),
                 (self.date_filter, "Preferred-date filter"), (self.unorganised, "Organisation filter"))
        for widget, name in names:
            widget.setAccessibleName(name)
        for label in self.findChildren(QLabel):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        for button in self.findChildren(QPushButton):
            button.setAccessibleName(button.text())
        self.content.setAccessibleDescription("Selection is by content identity. At most 50 items may be changed; changes require owner confirmation.")
        self.collection_table.setAccessibleDescription("Independent of the Year shelf. Collections contain content directly, not Albums.")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        narrow = self.width() < 1000
        orientation = Qt.Vertical if narrow else Qt.Horizontal
        if self.content_split.orientation() != orientation:
            self.content_split.setOrientation(orientation)
            self.content_split.setMinimumHeight(560 if narrow else 350)
            self.content_split.setSizes([300, 260] if narrow else [600, 360])

    @staticmethod
    def _preview_list(*, multi: bool) -> QListWidget:
        widget = QListWidget()
        widget.setViewMode(QListWidget.IconMode)
        widget.setResizeMode(QListWidget.Adjust)
        widget.setIconSize(thumbnail_icon_size(160))
        widget.setGridSize(QSize(225, 235))
        widget.setSelectionMode(
            QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.SingleSelection
        )
        return widget

    def run_async(self, operation: Callable[[], Any], completed: Callable[[Any], None]) -> None:
        worker = _Worker(operation)
        # PySide must not release a QRunnable wrapper while its queued signals or
        # completion callback are still in flight. This is especially important
        # for packaged mutation callbacks that immediately schedule a refresh.
        worker.setAutoDelete(False)
        self._active_workers.add(worker)
        worker.signals.completed.connect(completed)
        worker.signals.failed.connect(lambda message: QMessageBox.warning(self, "Personal Librarian", message))
        worker.signals.finished.connect(lambda worker=worker: self._active_workers.discard(worker))
        self.pool.start(worker)

    def refresh(self) -> None:
        self._year_request_generation += 1
        self.album_rows = []
        self._render_albums()
        self.run_async(
            lambda: self._load_top_level(),
            self._top_level_loaded,
        )

    def _load_top_level(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        capabilities = self.service.schema_capabilities()
        return (
            capabilities, self.service.browse_years(), self.service.tags(),
            self.service.collections(
                state=self.collection_filter.currentText().casefold(),
                limit=self.page_size, offset=self.collection_offset,
            ) if capabilities["collections_enabled"] else None,
        )

    def _top_level_loaded(
        self, result: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None],
    ) -> None:
        capabilities, years, tags, collections = result
        self.schema_version = int(capabilities["schema_version"])
        self.m30_enabled = bool(capabilities["preferred_dates_enabled"])
        self.date_filter.setEnabled(self.m30_enabled)
        self.evidence_button.setEnabled(self.m30_enabled)
        self.owner_date_button.setEnabled(self.m30_enabled)
        self.collection_filter.setEnabled(self.m30_enabled)
        self.collection_include_removed.setEnabled(self.m30_enabled)
        self.collection_table.setEnabled(self.m30_enabled)
        self.collection_members.setEnabled(self.m30_enabled)
        self.collection_previous.setEnabled(self.m30_enabled and self.collection_offset > 0)
        self.collection_next.setEnabled(
            self.m30_enabled
            and self.collection_offset + self.page_size < self.collection_total
        )
        self.collection_member_previous.setEnabled(False)
        self.collection_member_next.setEnabled(False)
        for button in self.collection_mutation_buttons:
            button.setEnabled(self.m30_enabled)
        self.collection_availability.setText(
            "Collections span all years. The Year shelf does not filter this view. Logical membership only; no media effect."
            if self.m30_enabled else
            f"Schema {self.schema_version} compatibility mode: preferred dates and Collections "
            "are unavailable; no schema-10 query or automatic migration is attempted."
        )
        selected = self.current_year if self.has_year_selection else object()
        self.years.clear()
        for row in years["years"]:
            item = QListWidgetItem(f"{row['label']}  ({row['content_count']:,})")
            item.setData(CONTENT_ROLE, row["year"])
            item.setToolTip(years["evidence_policy"] + (
                f"\n{row['conflict_count']:,} identities have conflicting year evidence."
                if row["conflict_count"] else ""
            ))
            self.years.addItem(item)
            if selected == row["year"]:
                self.years.setCurrentItem(item)
        self.tags.clear()
        for row in tags["tags"]:
            label = f"{row.get('namespace') + ': ' if row.get('namespace') else ''}{row['name']}"
            item = QListWidgetItem(label)
            item.setData(TAG_ROLE, row["tag_uuid"])
            self.tags.addItem(item)
        self.tag_message.setText(
            f"{self.tags.count()} manual tags" if self.tags.count() else "No tags have been created yet."
        )
        if collections is not None:
            self._collections_loaded(collections)
        else:
            self.collection_rows = []
            self.collection_table.setRowCount(0)
            self.collection_message.setText("Collections unavailable until schema 10.")
        if not self.has_year_selection and self.years.count():
            self.years.setCurrentRow(0)

    def _year_selected(self) -> None:
        item = self.years.currentItem()
        if item is None or not item.isSelected():
            self.has_year_selection = False
            self._year_request_generation += 1
            self.album_rows = []
            self._render_albums()
            return
        self.current_year = item.data(CONTENT_ROLE)
        self.has_year_selection = True
        self.offset = 0
        self._reload_year()

    def _reload_year(self) -> None:
        self.album_rows = []
        self._render_albums()
        if not self.has_year_selection:
            return
        if self.m30_enabled and self.date_filter.currentIndex() > 0:
            self._reload_date_status()
            return
        year = self.current_year
        self.year_heading.setText("Unknown Date" if year is None else str(year))
        self.content_message.setText("Loading bounded catalogue content…")
        self._year_request_generation += 1
        request = self._year_request_generation
        self.run_async(
            lambda: (
                self.service.year_content(
                    year=year, limit=self.page_size, offset=self.offset,
                    unorganised_only=self.unorganised.currentIndex() == 1,
                ),
                self.service.year_albums(year=year, include_archived=True),
                self.service.albums(include_archived=True),
            ),
            lambda result, request=request: (
                self._year_loaded(result)
                if request == self._year_request_generation else None
            ),
        )

    def _reload_date_status(self) -> None:
        status = "needs_review" if self.date_filter.currentIndex() == 1 else "unknown"
        self.year_heading.setText("Date needs review" if status == "needs_review" else "Unknown Date")
        self.content_message.setText("Loading bounded preferred-date review items…")
        self._year_request_generation += 1
        request = self._year_request_generation
        self.run_async(
            lambda: self.service.preferred_review_page(
                status=status, limit=self.page_size, offset=self.offset
            ),
            lambda result, request=request: (
                self._date_review_loaded(result)
                if request == self._year_request_generation else None
            ),
        )

    def _date_review_loaded(self, review: dict[str, Any]) -> None:
        content = {
            "content": review["items"], "total_matching": review["total_matching"],
            "unorganised_only": False,
        }
        self._year_loaded((content, {"albums": []}, {"albums": []}))

    def _year_loaded(self, result: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> None:
        content, derived, all_albums = result
        self.total = int(content["total_matching"])
        self.content_rows = content["content"]
        derived_by_uuid = {row["album_uuid"]: row for row in derived["albums"]}
        for row in all_albums["albums"]:
            if int(row.get("member_count", 0)) == 0 and row["album_uuid"] not in derived_by_uuid:
                derived_by_uuid[row["album_uuid"]] = row | {"year_member_count": 0, "unplaced": True}
        self.album_rows = list(derived_by_uuid.values())
        self._render_albums()
        self._generation += 1
        self.content.clear()
        for row in self.content_rows:
            date_value, date_source, date_status = preferred_summary(row)
            caption = (
                f"{item_filename(row)}\n{row.get('source') or 'Unknown source'} · "
                f"{date_value}\n{date_source} · {date_status}\n"
                f"{(row.get('extension') or 'unknown').lstrip('.').upper()} · Content {row['content_identity_id']}"
            )
            item = QListWidgetItem(caption)
            self._bind_preview(item, row, f"year:{self.current_year}")
            self.content.addItem(item)
        first = self.offset + 1 if self.total else 0
        last = min(self.offset + len(self.content_rows), self.total)
        suffix = " · Unsorted only" if content["unorganised_only"] else ""
        self.content_message.setText(f"Showing {first:,}–{last:,} of {self.total:,}{suffix}")
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset + self.page_size < self.total)

    def _bind_preview(self, item: QListWidgetItem, row: dict[str, Any], context: str) -> None:
        content_id = int(row["content_identity_id"])
        instance_id = int(
            row.get("physical_instance_id")
            or row.get("representative_physical_instance_id") or 0
        )
        path = str(
            row.get("current_observed_path")
            or row.get("representative_current_observed_path") or ""
        )
        token = LibraryPreviewBinding(self._generation, context, content_id, instance_id, path)
        item.setData(CONTENT_ROLE, content_id)
        item.setData(INSTANCE_ROLE, instance_id)
        item.setData(PATH_ROLE, path)
        item.setData(GENERATION_ROLE, self._generation)
        date_value, date_source, date_status = preferred_summary(row)
        item.setToolTip(
            f"{item_filename(row)}\nSource: {row.get('source') or '—'}\n"
            f"Size: {format_bytes(row.get('size_bytes'))}\nContent ID: {content_id}\n"
            f"Physical copies represented: {row.get('physical_instance_count', 1)}\n"
            f"Preferred date: {date_value} · {date_source} · {date_status}\n"
            f"Path: {path or 'Unavailable'}"
        )
        if path and instance_id:
            task = ThumbnailTask(self.thumbnail_service, path, row["identity_key"], token, instance_id)
            task.signals.loaded.connect(self._thumbnail_loaded)
            self.pool.start(task)

    def _thumbnail_loaded(self, token: object, image: object, error: str) -> None:
        if not isinstance(token, LibraryPreviewBinding) or token.generation != self._generation:
            return
        for widget in (self.content, self.members, self.collection_members):
            for index in range(widget.count()):
                item = widget.item(index)
                if (
                    int(item.data(CONTENT_ROLE)) == token.content_identity_id
                    and int(item.data(INSTANCE_ROLE)) == token.physical_instance_id
                    and str(item.data(PATH_ROLE)) == token.source_path
                    and int(item.data(GENERATION_ROLE)) == token.generation
                ):
                    if not image.isNull():
                        item.setIcon(QIcon(QPixmap.fromImage(image)))
                    elif error:
                        item.setToolTip(item.toolTip() + f"\n{error}")
                    return

    def _render_albums(self) -> None:
        if not hasattr(self, "album_rows"):
            return
        self._invalidate_album_members()
        # Replacing rows must not reuse a numeric currentRow as owner selection.
        self.albums.blockSignals(True)
        self.albums.clearSelection()
        self.albums.setCurrentCell(-1, -1)
        self.albums.setRowCount(0)
        self.albums.blockSignals(False)
        mode = self.album_filter.currentText().casefold()
        rows = [row for row in self.album_rows if mode == "all" or row["state"] == mode]
        self.albums.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row["name"], row.get("year_member_count", 0), row["state"],
                display_timestamp(row.get("created_at")), row.get("created_by"), row["album_uuid"],
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value or "—"))
                cell.setData(ALBUM_ROLE, row["album_uuid"])
                if row.get("unplaced"):
                    cell.setToolTip("Empty album: not associated with a year until content is added.")
                self.albums.setItem(row_index, column, cell)
        self.albums.resizeColumnsToContents()
        self.album_message.setText(
            f"{len(rows)} albums shown. Empty albums remain unplaced until content is added."
            if rows else "No albums have been created for this year yet."
        )

    def _selected_album(self) -> dict[str, Any] | None:
        cell = self.albums.item(self.albums.currentRow(), 0)
        if cell is None or not cell.isSelected():
            return None
        uuid = cell.data(ALBUM_ROLE)
        return next((row for row in self.album_rows if row["album_uuid"] == uuid), None)

    def _invalidate_album_members(self) -> None:
        self._album_request_generation += 1
        self._album_member_request = None
        self._loaded_album_uuid = None
        self.member_rows = []
        self._generation += 1
        self.members.clear()
        self.remove_button.setEnabled(False)
        self.album_detail.setText("Select an album to view its members.")

    def _album_selected(self) -> None:
        album = self._selected_album()
        self._invalidate_album_members()
        if album is None:
            return
        uuid = str(album["album_uuid"])
        request = (self._album_request_generation, uuid)
        self._album_member_request = request
        self.album_detail.setText(f"Loading members of {album['name']}…")
        self.run_async(
            lambda: self.service.album_members(uuid),
            lambda result: self._members_loaded(result, request),
        )

    def _members_loaded(self, result: dict[str, Any], request: tuple[int, str]) -> None:
        selected = self._selected_album()
        if (request != self._album_member_request or selected is None
                or str(selected["album_uuid"]) != request[1]):
            return
        album = result["album"]
        if str(album["album_uuid"]) != request[1]:
            return
        self._album_member_request = None
        self._loaded_album_uuid = request[1]
        self.remove_button.setEnabled(album["state"] == selected["state"] == "active")
        self.member_rows = result["members"]
        self.album_detail.setText(
            f"{album['name']} · {album['state']} · {album['member_count']} members\n"
            f"{album.get('description') or 'No description'}\nLogical membership only; media paths are unchanged."
        )
        self._generation += 1
        self.members.clear()
        for row in self.member_rows:
            item = QListWidgetItem(
                f"{item_filename(row)}\n{row.get('source') or 'Unknown source'} · "
                f"{format_bytes(row.get('size_bytes'))}\nContent {row['content_identity_id']}"
            )
            item.setData(ALBUM_ROLE, self._loaded_album_uuid)
            self._bind_preview(item, row, f"album:{album['album_uuid']}")
            self.members.addItem(item)

    def _content_selected(self) -> None:
        selected = self.content.selectedItems()
        if len(selected) > MAX_MUTATION_SELECTION:
            for item in selected[MAX_MUTATION_SELECTION:]:
                item.setSelected(False)
            QMessageBox.information(self, "Bounded selection", "At most 50 items may be changed at once.")
            selected = selected[:MAX_MUTATION_SELECTION]
        if not selected:
            self.content_detail.setText("Select content to see its logical organisation.")
            return
        content_id = int(selected[0].data(CONTENT_ROLE))
        row = next(
            (value for value in self.content_rows
             if int(value["content_identity_id"]) == content_id), {}
        )
        date_value, date_source, date_status = preferred_summary(row)
        self.run_async(
            lambda: (
                self.service.albums_for_content(content_id),
                self.service.tags_for_content(content_id),
                self.service.collections_for_content(content_id, include_removed=True)
                if self.m30_enabled else {"collections": []},
            ),
            lambda result: self._content_organisation_loaded(
                content_id, date_value, date_source, date_status, result
            ),
        )

    def _content_organisation_loaded(
        self, content_id: int, date_value: str, date_source: str, date_status: str,
        result: object,
    ) -> None:
        if self._selected_content_id() != content_id:
            return
        if not isinstance(result, tuple) or len(result) != 3 \
                or not all(isinstance(value, dict) for value in result):
            return
        albums, tags, collections = result
        self.content_detail.setText(
            f"Content {content_id}\nPreferred date: {date_value} · {date_source} · {date_status}\n"
            f"Albums containing this item: "
            f"{', '.join(row['name'] for row in albums['albums']) or 'None'}\n"
            f"Tags: {', '.join(row['name'] for row in tags['tags']) or 'None'}\n"
            f"Collections: {', '.join(row['name'] for row in collections['collections']) or 'None'}\n"
            "One identity may belong to multiple logical groupings without creating copies."
        )

    def _selected_content_id(self) -> int | None:
        selected = self.content.selectedItems()
        return int(selected[0].data(CONTENT_ROLE)) if selected else None

    def _view_date_evidence(self) -> None:
        content_id = self._selected_content_id()
        if content_id is None or not self.m30_enabled:
            QMessageBox.information(self, "Select content", "Select one schema-10 content item first.")
            return
        self.run_async(
            lambda: self.service.preferred_date_detail(content_id, limit=self.page_size),
            lambda detail: DateEvidenceDialog(detail, self).exec(),
        )

    def _set_owner_date(self) -> None:
        content_id = self._selected_content_id()
        evidence = self._actor_reason()
        if content_id is None or evidence is None or not self.m30_enabled:
            return
        self.run_async(
            lambda: self.service.preferred_date_detail(content_id, limit=self.page_size),
            lambda detail: self._show_owner_date_dialog(content_id, detail, evidence),
        )

    def _show_owner_date_dialog(
        self, content_id: int, detail: dict[str, Any],
        evidence: tuple[str, str | None],
    ) -> None:
        current = detail.get("preferred_date")
        dialog = OwnerPreferredDateDialog(content_id, current, self)
        if dialog.exec() != QDialog.Accepted:
            return
        precision, value, replace = dialog.values()
        if not value:
            QMessageBox.warning(self, "Preferred date required", "Enter the exact proposed value.")
            return
        current_owner = bool(current and current.get("selection_method") == "owner_selection")
        if current_owner and not replace:
            QMessageBox.warning(
                self, "Explicit replacement required",
                "Confirm that this action replaces the current owner-set selection.",
            )
            return
        try:
            proposed = self._validate_owner_precision(value, precision)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid preferred date", str(exc))
            return
        if not self._confirm(
            f"Set Content {content_id} preferred date to {proposed}?\n"
            f"Genuine precision: {precision.replace('_', '-')}\n\nRaw evidence will not be changed."
        ):
            return
        actor, reason = evidence
        action_id = f"desktop:preferred-date:{uuid4()}"
        self.run_async(
            lambda: self.service.set_owner_date(
                content_identity_id=content_id, value=proposed, actor=actor,
                action_id=action_id, reason=reason, replace=current_owner,
            ),
            lambda _: self.refresh(),
        )

    @staticmethod
    def _validate_owner_precision(value: str, precision: str) -> str:
        import re
        patterns = {
            "year": r"\d{4}", "year_month": r"\d{4}-\d{2}",
            "date": r"\d{4}-\d{2}-\d{2}",
            "datetime": r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?",
        }
        if not re.fullmatch(patterns[precision], value):
            raise ValueError(f"Value does not match selected {precision.replace('_', '-')} precision.")
        return value

    def _actor_reason(self) -> tuple[str, str | None] | None:
        actor = self.actor.text().strip()
        if not actor:
            QMessageBox.warning(self, "Owner / actor required", "Enter the explicit owner/actor first.")
            return None
        return actor, self.reason.text().strip() or None

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Confirm logical organisation change", text,
                                    QMessageBox.Yes | QMessageBox.Cancel,
                                    QMessageBox.Cancel) == QMessageBox.Yes

    def _create_album(self) -> None:
        evidence = self._actor_reason()
        if evidence is None:
            return
        dialog = CreateAlbumDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        name, description = dialog.values()
        if not name:
            QMessageBox.warning(self, "Album name required", "Enter an album name.")
            return
        if not self._confirm(f'Create album "{name}"?\n\nNo disk folder will be created.'):
            return
        actor, reason = evidence
        self.run_async(lambda: self.service.create_album(name=name, description=description,
                                                         actor=actor, reason=reason),
                       lambda _: self.refresh())

    def _rename_album(self) -> None:
        album, evidence = self._selected_album(), self._actor_reason()
        if album is None or evidence is None:
            return
        name, ok = QInputDialog.getText(self, "Rename album", f"Current name: {album['name']}\nNew name")
        if not ok or not name.strip() or not self._confirm(
            f'Rename album "{album["name"]}" to "{name.strip()}"?\n\nUUID, membership, and media paths stay unchanged.'
        ):
            return
        actor, reason = evidence
        self.run_async(lambda: self.service.rename_album(album_uuid=album["album_uuid"], name=name,
                                                         actor=actor, reason=reason),
                       lambda _: self.refresh())

    def _toggle_album(self) -> None:
        album, evidence = self._selected_album(), self._actor_reason()
        if album is None or evidence is None:
            return
        archived = album["state"] == "active"
        action = "Archive" if archived else "Restore"
        if not self._confirm(f'{action} album "{album["name"]}"?\n\nNo media will be changed.'):
            return
        actor, reason = evidence
        self.run_async(lambda: self.service.set_album_archived(album_uuid=album["album_uuid"],
                                                               archived=archived, actor=actor, reason=reason),
                       lambda _: self.refresh())

    def _add_selected(self) -> None:
        album, evidence = self._selected_album(), self._actor_reason()
        ids = [int(item.data(CONTENT_ROLE)) for item in self.content.selectedItems()][:MAX_MUTATION_SELECTION]
        if album is None or evidence is None or not ids:
            return
        if album["state"] != "active":
            QMessageBox.warning(self, "Archived album", "Restore the album before adding content.")
            return
        context = (self._album_request_generation, str(album["album_uuid"]))
        if not self._confirm(f"Add {len(ids)} logical content item(s) to {album['name']}?"):
            return
        if not self._album_context_matches(context):
            return
        self._invalidate_album_members()
        actor, reason = evidence
        self.run_async(
            lambda: [self.service.set_album_membership(album_uuid=album["album_uuid"],
                                                       content_identity_id=value, present=True,
                                                       actor=actor, reason=reason) for value in ids],
            lambda _: self._reload_year(),
        )

    def _album_context_matches(self, context: tuple[int, str]) -> bool:
        album = self._selected_album()
        return (album is not None and context == (
            self._album_request_generation, str(album["album_uuid"])
        ))

    def _remove_selected(self) -> None:
        album = self._selected_album()
        selected = self.members.selectedItems()[:MAX_MUTATION_SELECTION]
        if album is None or not selected:
            return
        uuid = str(album["album_uuid"])
        loaded_ids = {int(row["content_identity_id"]) for row in self.member_rows}
        if (self._loaded_album_uuid != uuid or self._album_member_request is not None
                or any(item.data(ALBUM_ROLE) != uuid
                       or int(item.data(CONTENT_ROLE)) not in loaded_ids for item in selected)):
            QMessageBox.warning(self, "Album selection changed", "Select the album again before removing members.")
            return
        if album["state"] != "active":
            QMessageBox.warning(self, "Archived album", "Restore the album before removing content.")
            return
        evidence = self._actor_reason()
        if evidence is None:
            return
        ids = [int(item.data(CONTENT_ROLE)) for item in selected]
        context = (self._album_request_generation, uuid)
        if not self._confirm(f"Remove {len(ids)} logical content item(s) from {album['name']}?"):
            return
        # A modal confirmation processes Qt events; selection may change meanwhile.
        if not self._album_context_matches(context) or self._loaded_album_uuid != uuid:
            return
        self._invalidate_album_members()
        actor, reason = evidence
        self.run_async(
            lambda: [self.service.set_album_membership(album_uuid=uuid,
                                                       content_identity_id=value, present=False,
                                                       actor=actor, reason=reason) for value in ids],
            lambda _: self._reload_year(),
        )

    def _collections_filter_changed(self) -> None:
        self.collection_offset = 0
        if self.m30_enabled:
            self._reload_collections()

    def _reload_collections(self) -> None:
        self._collection_request_generation += 1
        request = self._collection_request_generation
        state = self.collection_filter.currentText().casefold()
        self.run_async(
            lambda: self.service.collections(
                state=state, limit=self.page_size, offset=self.collection_offset
            ),
            lambda result, request=request: (
                self._collections_loaded(result)
                if request == self._collection_request_generation else None
            ),
        )

    def _collections_loaded(self, result: dict[str, Any]) -> None:
        selected = self._selected_collection()
        selected_uuid = selected.get("collection_uuid") if selected else None
        self.collection_rows = result["collections"]
        self.collection_total = int(result["total_matching"])
        self.collection_table.setRowCount(len(self.collection_rows))
        selected_row = -1
        for row_index, row in enumerate(self.collection_rows):
            uuid = str(row["collection_uuid"])
            values = (
                row["name"], uuid[:8], row["state"], row.get("active_member_count", 0),
                row.get("removed_member_count", 0), display_timestamp(row.get("created_at")),
                row.get("created_by"),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value or "—"))
                cell.setData(COLLECTION_ROLE, uuid)
                cell.setToolTip(
                    f"Full UUID: {uuid}\nDuplicate-name count: {row.get('duplicate_name_count', 1)}"
                )
                self.collection_table.setItem(row_index, column, cell)
            if uuid == selected_uuid:
                selected_row = row_index
        self.collection_table.resizeColumnsToContents()
        self.collection_message.setText(
            f"Showing {len(self.collection_rows)} of {self.collection_total} bounded Collections. "
            "Duplicate names are distinguished by UUID."
            if self.collection_rows else "No Collections match this lifecycle filter."
        )
        self.collection_previous.setEnabled(self.collection_offset > 0)
        self.collection_next.setEnabled(
            self.collection_offset + self.page_size < self.collection_total
        )
        if selected_row >= 0:
            self.collection_table.selectRow(selected_row)

    def _move_collection_page(self, direction: int) -> None:
        self.collection_offset = max(
            0, self.collection_offset + direction * self.page_size
        )
        self._reload_collections()

    def _selected_collection(self) -> dict[str, Any] | None:
        cell = self.collection_table.item(self.collection_table.currentRow(), 0)
        if cell is None:
            return None
        uuid = str(cell.data(COLLECTION_ROLE))
        return next(
            (row for row in self.collection_rows if str(row["collection_uuid"]) == uuid), None
        )

    def _collection_selected(self) -> None:
        collection = self._selected_collection()
        if collection is None or not self.m30_enabled:
            return
        self._collection_request_generation += 1
        request = self._collection_request_generation
        uuid = str(collection["collection_uuid"])
        if uuid != self._loaded_collection_uuid:
            self.collection_member_offset = 0
            self._loaded_collection_uuid = uuid
        self.run_async(
            lambda: (
                self.service.collection(uuid),
                self.service.collection_members(
                    uuid, include_removed=self.collection_include_removed.isChecked(),
                    limit=self.page_size, offset=self.collection_member_offset,
                ),
            ),
            lambda result, request=request: (
                self._collection_detail_loaded(result)
                if request == self._collection_request_generation else None
            ),
        )

    def _collection_detail_loaded(
        self, result: tuple[dict[str, Any], dict[str, Any]],
    ) -> None:
        collection, members = result
        self.collection_member_total = int(members["total_matching"])
        self.collection_detail.setText(
            f"{collection['name']} · {str(collection['collection_uuid'])[:8]} · {collection['state']}\n"
            f"{collection.get('description') or 'No description'}\n"
            f"{collection.get('active_member_count', 0)} active · "
            f"{collection.get('removed_member_count', 0)} removed · "
            f"{collection.get('provenance') or '—'}\n"
            "Logical content-identity membership only; media is unchanged."
        )
        self.collection_member_rows = []
        self._generation += 1
        self.collection_members.clear()
        for source_row in members["members"]:
            row = dict(source_row)
            row.update({
                "physical_instance_id": row.get("representative_physical_instance_id"),
                "current_observed_path": row.get("representative_current_observed_path"),
                "raw_relative_path": row.get("representative_raw_relative_path"),
                "size_bytes": row.get("representative_size_bytes"),
                "extension": row.get("representative_extension"),
                "observed_created_at": row.get("representative_observed_created_at"),
                "observed_modified_at": row.get("representative_observed_modified_at"),
                "source": row.get("representative_source"),
                "preferred_status": row.get("preferred_status") or "unknown",
            })
            self.collection_member_rows.append(row)
            date_value, _, date_status = preferred_summary(row)
            item = QListWidgetItem(
                f"{item_filename(row)}\n{row.get('source') or 'Unknown source'} · "
                f"{(row.get('extension') or 'unknown').lstrip('.').upper()}\n"
                f"{date_value} · {date_status} · {row['physical_instance_count']} physical instance(s)\n"
                f"Membership: {row['membership_state']} · {row.get('album_count', 0)} active Album(s)"
            )
            item.setData(MEMBERSHIP_STATE_ROLE, row["membership_state"])
            self._bind_preview(item, row, f"collection:{collection['collection_uuid']}")
            self.collection_members.addItem(item)
        self.collection_member_previous.setEnabled(self.collection_member_offset > 0)
        self.collection_member_next.setEnabled(
            self.collection_member_offset + self.page_size < self.collection_member_total
        )

    def _collection_member_filter_changed(self) -> None:
        self.collection_member_offset = 0
        self._collection_selected()

    def _move_collection_member_page(self, direction: int) -> None:
        self.collection_member_offset = max(
            0, self.collection_member_offset + direction * self.page_size
        )
        self._collection_selected()

    def _create_collection(self) -> None:
        evidence = self._actor_reason()
        if evidence is None or not self.m30_enabled:
            return
        dialog = CreateCollectionDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        name, description = dialog.values()
        if not name:
            QMessageBox.warning(self, "Collection name required", "Enter a Collection name.")
            return
        if not self._confirm(f'Create Collection "{name}"?\n\nNo folder or media copy will be created.'):
            return
        actor, reason = evidence
        action_id = f"desktop:collection-create:{uuid4()}"
        self.run_async(
            lambda: self.service.create_collection(
                name=name, description=description, actor=actor,
                action_id=action_id, reason=reason,
            ),
            lambda _: self._reload_collections(),
        )

    def _rename_collection(self) -> None:
        collection, evidence = self._selected_collection(), self._actor_reason()
        if collection is None or evidence is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Collection", f"Current name: {collection['name']}\nNew name"
        )
        if not ok or not name.strip() or not self._confirm(
            f'Rename Collection "{collection["name"]}" to "{name.strip()}"?'
        ):
            return
        actor, reason = evidence
        action_id = f"desktop:collection-rename:{uuid4()}"
        self.run_async(
            lambda: self.service.rename_collection(
                collection_uuid=str(collection["collection_uuid"]), name=name.strip(),
                actor=actor, action_id=action_id, reason=reason,
            ), lambda _: self._reload_collections(),
        )

    def _toggle_collection(self) -> None:
        collection, evidence = self._selected_collection(), self._actor_reason()
        if collection is None or evidence is None:
            return
        archived = collection["state"] == "active"
        action = "Archive" if archived else "Restore"
        if not self._confirm(f'{action} Collection "{collection["name"]}"?\n\nNo media will change.'):
            return
        actor, reason = evidence
        action_id = f"desktop:collection-{action.casefold()}:{uuid4()}"
        self.run_async(
            lambda: self.service.set_collection_archived(
                collection_uuid=str(collection["collection_uuid"]), archived=archived,
                actor=actor, action_id=action_id, reason=reason,
            ), lambda _: self._reload_collections(),
        )

    def _add_to_collection(self) -> None:
        collection, evidence = self._selected_collection(), self._actor_reason()
        ids = [int(item.data(CONTENT_ROLE)) for item in self.content.selectedItems()]
        if len(ids) > MAX_MUTATION_SELECTION:
            ids = ids[:MAX_MUTATION_SELECTION]
        if collection is None or evidence is None or not ids:
            QMessageBox.information(
                self, "Select content", "Select up to 50 items in Years and one Collection."
            )
            return
        if collection["state"] != "active":
            QMessageBox.warning(self, "Archived Collection", "Restore the Collection before adding.")
            return
        if not self._confirm(
            f"Add {len(ids)} logical content item(s) to {collection['name']} "
            f"({str(collection['collection_uuid'])[:8]})?"
        ):
            return
        actor, reason = evidence
        action_ids = {value: f"desktop:collection-add:{uuid4()}" for value in ids}
        self.run_async(
            lambda: [self.service.set_collection_membership(
                collection_uuid=str(collection["collection_uuid"]),
                content_identity_id=value, operation="add", actor=actor,
                action_id=action_ids[value], reason=reason,
            ) for value in ids],
            lambda _: self._reload_collections(),
        )

    def _change_collection_members(self, operation: str) -> None:
        collection, evidence = self._selected_collection(), self._actor_reason()
        selected = self.collection_members.selectedItems()[:MAX_MUTATION_SELECTION]
        if collection is None or evidence is None or not selected:
            return
        desired = "active" if operation == "restore" else "removed"
        selected = [item for item in selected if item.data(MEMBERSHIP_STATE_ROLE) != desired]
        if not selected:
            return
        if collection["state"] != "active":
            QMessageBox.warning(self, "Archived Collection", "Restore the Collection first.")
            return
        if not self._confirm(
            f"{operation.title()} {len(selected)} logical Collection membership(s)?\n"
            "No media will be changed."
        ):
            return
        actor, reason = evidence
        ids = [int(item.data(CONTENT_ROLE)) for item in selected]
        action_ids = {value: f"desktop:collection-{operation}:{uuid4()}" for value in ids}
        self.run_async(
            lambda: [self.service.set_collection_membership(
                collection_uuid=str(collection["collection_uuid"]),
                content_identity_id=value, operation=operation, actor=actor,
                action_id=action_ids[value], reason=reason,
            ) for value in ids],
            lambda _: self._collection_selected(),
        )

    def _view_collection_history(self) -> None:
        collection = self._selected_collection()
        if collection is None:
            return
        self.tabs.setCurrentIndex(3)
        self.history_domain.blockSignals(True)
        self.history_domain.setCurrentIndex(2)
        self.history_domain.blockSignals(False)
        self.history_offset = 0
        self._load_history(collection_uuid=str(collection["collection_uuid"]))

    def _create_tag(self) -> None:
        evidence = self._actor_reason()
        if evidence is None:
            return
        name, ok = QInputDialog.getText(self, "Create tag", "Tag name")
        if not ok or not name.strip() or not self._confirm(f'Create descriptive tag "{name.strip()}"?'):
            return
        actor, reason = evidence
        self.run_async(lambda: self.service.create_tag(name=name, namespace=None, actor=actor, reason=reason),
                       lambda _: self.refresh())

    def _tag_selected(self, present: bool) -> None:
        evidence, tag = self._actor_reason(), self.tags.currentItem()
        ids = [int(item.data(CONTENT_ROLE)) for item in self.content.selectedItems()][:MAX_MUTATION_SELECTION]
        if evidence is None or tag is None or not ids:
            QMessageBox.information(self, "Select content", "Select a tag and content in the Years tab first.")
            return
        action = "Add" if present else "Remove"
        if not self._confirm(f"{action} tag for {len(ids)} selected logical item(s)?"):
            return
        actor, reason = evidence
        self.run_async(
            lambda: [self.service.set_tag_membership(tag_uuid=str(tag.data(TAG_ROLE)),
                                                     content_identity_id=value, present=present,
                                                     actor=actor, reason=reason) for value in ids],
            lambda _: self._content_selected(),
        )

    def _view_album_history(self) -> None:
        album = self._selected_album()
        if album is None:
            return
        self.tabs.setCurrentIndex(3)
        self.history_domain.blockSignals(True)
        self.history_domain.setCurrentIndex(1)
        self.history_domain.blockSignals(False)
        self.history_offset = 0
        self._load_history(str(album["album_uuid"]))

    def _load_history(
        self, album_uuid: str | None = None, collection_uuid: str | None = None,
    ) -> None:
        if album_uuid is not None:
            self._history_context = ("album", album_uuid)
        elif collection_uuid is not None:
            self._history_context = ("collection", collection_uuid)
        domains = ("all", "albums_tags", "collections", "preferred_dates")
        domain = domains[self.history_domain.currentIndex()]
        context = self._history_context
        self._history_request_generation += 1
        request = self._history_request_generation
        self.run_async(
            lambda: (
                self.service.organisation_history(
                    album_uuid=context[1], limit=self.page_size,
                    offset=self.history_offset,
                ) if context and context[0] == "album" else
                self.service.collection_history(
                    context[1], limit=self.page_size, offset=self.history_offset,
                ) if context and context[0] == "collection" else
                self.service.desktop_history(
                    domain=domain, limit=self.page_size, offset=self.history_offset
                )
            ),
            lambda result, request=request: (
                self._history_loaded(result)
                if request == self._history_request_generation else None
            ),
        )

    def _history_loaded(self, result: dict[str, Any]) -> None:
        rows = result["history"]
        self.history_total = int(result.get("total_matching", len(rows)))
        self.history.setRowCount(len(rows))
        labels = {
            "album_created": "Album created", "album_renamed": "Album renamed",
            "album_archived": "Album archived", "album_restored": "Album restored",
            "album_member_added": "Added to album", "album_member_restored": "Added to album",
            "album_member_removed": "Removed from album", "tag_created": "Tag created",
            "tag_member_added": "Tag added", "tag_member_restored": "Tag added",
            "tag_member_removed": "Tag removed",
            "collection_created": "Collection created",
            "collection_renamed": "Collection renamed",
            "collection_archived": "Collection archived",
            "collection_restored": "Collection restored",
            "collection_member_added": "Added to Collection",
            "collection_member_removed": "Removed from Collection",
            "collection_member_restored": "Restored to Collection",
            "preferred_date_resolved": "Preferred date resolved",
            "preferred_date_needs_review": "Date needs review",
            "preferred_date_unknown": "Preferred date unknown",
            "preferred_date_owner_set": "Owner preferred date set",
            "preferred_date_changed": "Preferred date changed",
        }
        for row_index, row in enumerate(rows):
            values = (
                display_timestamp(row["occurred_at"]), labels.get(row["event_type"], row["event_type"]),
                row["actor_identifier"], row.get("album_uuid"), row.get("tag_uuid"),
                row.get("collection_uuid"), row.get("content_identity_id"),
                row.get("reason"), row.get("provenance"),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value or "—"))
                cell.setToolTip(json.dumps(row.get("details", {}), ensure_ascii=False))
                self.history.setItem(row_index, column, cell)
        self.history.resizeColumnsToContents()
        self.history_message.setText(
            f"Showing {len(rows)} of {result.get('total_matching', len(rows))} bounded append-only events"
            if rows else "No history exists for this domain."
        )
        self.history_previous.setEnabled(self.history_offset > 0)
        self.history_next.setEnabled(
            self.history_offset + self.page_size < self.history_total
        )

    def _filter_changed(self) -> None:
        self.offset = 0
        self._reload_year()

    def _date_filter_changed(self) -> None:
        self.offset = 0
        self._reload_year()

    def _history_filter_changed(self) -> None:
        self.history_offset = 0
        self._history_context = None
        self._load_history()

    def _move_history_page(self, direction: int) -> None:
        self.history_offset = max(0, self.history_offset + direction * self.page_size)
        self._load_history()

    def _move_page(self, direction: int) -> None:
        self.offset = max(0, self.offset + direction * self.page_size)
        self._reload_year()
