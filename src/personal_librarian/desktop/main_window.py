"""Conventional, restrained Qt desktop shell for bounded catalogue review."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from personal_librarian.desktop.quiet_archive import apply_theme, text_label
from personal_librarian.desktop.services import DesktopDataService
from personal_librarian.desktop.library_page import LibraryPage
from personal_librarian.desktop.preferences import (
    ALLOWED_PAGE_SIZES,
    ALLOWED_THUMBNAIL_SIZES,
    PreferenceStore,
    UiPreferences,
)
from personal_librarian.desktop.thumbnails import ThumbnailService, ThumbnailTask, thumbnail_icon_size
from personal_librarian.desktop.ui_helpers import (
    SIMILARITY_HELP_TEXT,
    bounded_row,
    canonical_scope_label,
    decision_confirmation_text,
    display_timestamp,
    format_bytes,
    item_filename,
    metadata_blocks,
    metadata_summary,
    owner_state_label,
    preview_caption,
)
from personal_librarian.desktop.viewer import ImageViewerDialog


def _format_age(seconds: object) -> str:
    if seconds is None:
        return "unavailable"
    hours = float(seconds) / 3600
    return f"{hours:.1f} hours" if hours < 48 else f"{hours / 24:.1f} days"


@dataclass(frozen=True, slots=True)
class PreviewBinding:
    generation: int
    context_type: str
    context_id: int
    physical_instance_id: int
    source_path: str


PREVIEW_INSTANCE_ROLE = int(Qt.ItemDataRole.UserRole)
PREVIEW_PATH_ROLE = PREVIEW_INSTANCE_ROLE + 1
PREVIEW_CONTEXT_ROLE = PREVIEW_INSTANCE_ROLE + 2
PREVIEW_GENERATION_ROLE = PREVIEW_INSTANCE_ROLE + 3


class WorkerSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:
            try:
                self.signals.failed.emit(str(exc))
            except RuntimeError:
                pass  # The owning window may have closed while the bounded read finished.
        else:
            try:
                self.signals.completed.emit(result)
            except RuntimeError:
                pass  # The owning window may have closed while the bounded read finished.


class AsyncPage(QWidget):
    def __init__(self, service: DesktopDataService) -> None:
        super().__init__()
        self.service = service
        self.pool = QThreadPool.globalInstance()

    def run_async(
        self, operation: Callable[[], Any], completed: Callable[[Any], None],
        failed: Callable[[str], None] | None = None,
    ) -> None:
        worker = Worker(operation)
        worker.signals.completed.connect(completed)
        worker.signals.failed.connect(failed or self.show_error)
        self.pool.start(worker)

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Personal Librarian", message)

    def refresh(self) -> None:
        pass


class OverviewPage(AsyncPage):
    navigate_requested = Signal(int)
    library_requested = Signal(str)

    def __init__(self, service: DesktopDataService) -> None:
        super().__init__(service)
        apply_theme(self)
        self._request_generation = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        layout.addWidget(text_label("Your library, at a glance", name="pageTitle"))
        layout.addWidget(text_label("Find your years. Review what needs attention. Keep recovery in view.", name="helpText"))
        self.message = text_label("Loading catalogue health…")
        self.message.setAccessibleName("Catalogue connection and owner decision availability")
        layout.addWidget(self.message)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("archiveCanvas")
        body.setMinimumWidth(0)
        cards = QGridLayout(body)
        cards.setSpacing(16)
        self.values: dict[str, QLabel] = {}

        def card(title: str, fields: tuple, row: int, column: int):
            group = QGroupBox(title)
            form = QVBoxLayout(group)
            for key, label in fields:
                form.addWidget(text_label(label, name="helpText"))
                value = text_label("Not yet assessed", name="metric" if key in {
                    "content_identities", "physical_instances", "exact_duplicate_groups",
                    "similarity_groups", "needs_review"} else "")
                value.setTextInteractionFlags(Qt.TextSelectableByMouse)
                value.setAccessibleName(label)
                self.values[key] = value
                form.addWidget(value)
            cards.addWidget(group, row, column)
            return group, form

        _, library = card("Library", (("content_identities", "Library items · distinct content"),
                          ("physical_instances", "Physical copies")), 0, 0)
        self.year_summary = text_label("Year shelves are loading…", name="helpText")
        library.addWidget(self.year_summary)
        self.browse_button = QPushButton("Browse your years")
        self.browse_button.setProperty("primary", True)
        self.browse_button.clicked.connect(lambda: self.library_requested.emit("years"))
        library.addWidget(self.browse_button)
        _, review = card("Review", (("exact_duplicate_groups", "Exact groups · identical content"),
                        ("similarity_groups", "Similar groups · distinct images"),
                        ("needs_review", "Preferred dates needing review")), 0, 1)
        self.dates_button = QPushButton("Review conflicting dates")
        self.dates_button.clicked.connect(lambda: self.library_requested.emit("needs_review"))
        review.addWidget(self.dates_button)
        _, backups = card("Backups", (("operational_backup", "Operational recovery point"),
                           ("independent_backup", "Independent disaster recovery")), 1, 0)
        backups.addWidget(text_label("Catalogue health does not prove independent recovery readiness.", name="helpText"))
        self.backups_button = QPushButton("View backup details")
        self.backups_button.clicked.connect(lambda: self.navigate_requested.emit(7))
        backups.addWidget(self.backups_button)
        _, safety = card("Safety / Actions", (("decision_events", "Owner decisions · preserved history"),
                          ("action_plans", "Read-only plans"),
                          ("quarantine_records", "Quarantine history"),
                          ("recovery_required", "Executions requiring recovery")), 1, 1)
        self.history_button = QPushButton("View decision history")
        self.history_button.clicked.connect(lambda: self.navigate_requested.emit(4))
        safety.addWidget(self.history_button)
        self.details_button = QPushButton("Show catalogue details")
        self.details_button.setCheckable(True)
        cards.addWidget(self.details_button, 2, 0, 1, 2)
        self.catalogue_details, _ = card("Catalogue", (("health", "Health result"),
                              ("catalogue_uuid", "Catalogue identity"),
                              ("schema_version", "Schema"), ("file_size_bytes", "Catalogue size")), 3, 0)
        cards.removeWidget(self.catalogue_details)
        cards.addWidget(self.catalogue_details, 3, 0, 1, 2)
        self.catalogue_details.hide()
        self.details_button.toggled.connect(self._show_details)
        cards.setColumnStretch(0, 1)
        cards.setColumnStretch(1, 1)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        layout.addWidget(text_label("Organisation is logical. Albums and Collections never move files. Physical actions are unavailable here.", name="boundaryNotice"))
        self._clear_pending()

    def _show_details(self, checked: bool) -> None:
        self.catalogue_details.setVisible(checked)
        self.details_button.setText("Hide catalogue details" if checked else "Show catalogue details")

    def _clear_pending(self) -> None:
        for value in self.values.values():
            value.setText("Not yet assessed")
        for button in (self.browse_button, self.dates_button, self.backups_button, self.history_button):
            button.setEnabled(False)
            button.setToolTip("Unavailable until the current catalogue read succeeds.")
        self.year_summary.setText("Year shelves are loading…")

    def _snapshot(self) -> dict[str, Any]:
        report = self.service.dashboard()
        if report["health"].get("summary") != "FAIL":
            report["year_shelves"] = self.service.browse_years()
            if int(report["health"].get("schema_version", 0)) >= 10:
                report["preferred_counts"] = self.service.preferred_counts()
        return report

    def refresh(self) -> None:
        self._request_generation += 1
        request = self._request_generation
        self._clear_pending()
        self.message.setText("Loading catalogue health…")
        # Retain AsyncPage's bound QObject receiver pattern. A transient lambda
        # receiver can disappear with its auto-deleted QRunnable wrapper.
        self.run_async(lambda: self._snapshot_for_request(request), self._snapshot_ready)

    def _snapshot_for_request(self, request: int) -> tuple:
        try:
            return request, self._snapshot(), None
        except Exception as exc:
            return request, None, str(exc)

    def _snapshot_ready(self, result: tuple) -> None:
        request, report, error = result
        if request != self._request_generation:
            return
        if error is not None:
            self._failed(error)
        else:
            self._loaded(report)

    def _failed(self, message: str) -> None:
        self._clear_pending()
        self.year_summary.setText("Year shelves unavailable")
        self.message.setText(f"Catalogue unavailable: {message}\nNothing was created or changed.")

    def _loaded(self, report: dict[str, Any]) -> None:
        health = report["health"]
        if health.get("summary") == "FAIL":
            self._failed("; ".join(health.get("failures", ["health check failed"])))
            return
        counts = report["counts"]
        disaster = health.get("disaster_recovery", {})
        def backup_age(value: object) -> str:
            return "verification time unavailable" if value is None else f"latest {_format_age(value)} old"
        self.message.setText("Catalogue connected. Owner decision writes are "
                             + ("available with confirmation." if report["decision_writes_enabled"]
                                else "disabled by health state."))
        values = {
            "health": health["summary"], "catalogue_uuid": health["catalogue_uuid"],
            "schema_version": health["schema_version"], "file_size_bytes": format_bytes(health["file_size_bytes"]),
            "physical_instances": f"{counts['physical_instances']:,}",
            "content_identities": f"{counts['content_identities']:,}",
            "exact_duplicate_groups": f"{counts['exact_duplicate_groups']:,}",
            "similarity_groups": f"{counts['similarity_groups']:,}",
            "operational_backup": f"{health['backup_count']} accepted · {backup_age(health.get('backup_age_seconds'))}",
            "independent_backup": f"{str(disaster.get('summary', 'NOT ASSESSED')).replace('_', ' ')} · {backup_age(disaster.get('backup_age_seconds'))}",
            "recovery_required": health["recovery_required_executions"],
            "decision_events": counts["decision_events"], "action_plans": counts["action_plans"],
            "quarantine_records": counts["quarantine_records"],
            "needs_review": (str(sum(int(row["content_count"]) for row in report["preferred_counts"]["counts"]
                                     if row["status"] == "needs_review"))
                             if "preferred_counts" in report else "Unavailable in this catalogue"),
        }
        for key, value in values.items():
            self.values[key].setText(str(value))
        shelves = report.get("year_shelves", {}).get("years")
        self.year_summary.setText(
            "Browse by recorded year, with unresolved dates kept on the Unknown Date shelf."
            if shelves else "No year shelves are available yet.")
        for button in (self.browse_button, self.backups_button, self.history_button):
            button.setEnabled(True)
            button.setToolTip("Open the existing read-only view.")
        self.dates_button.setEnabled("preferred_counts" in report)
        self.dates_button.setToolTip("Open Needs Review; no date is chosen automatically."
                                    if self.dates_button.isEnabled() else "Preferred-date review is unavailable in this catalogue.")


class ReviewPage(AsyncPage):
    def __init__(
        self, service: DesktopDataService, *, similar: bool, preferences: UiPreferences
    ) -> None:
        super().__init__(service)
        self.similar = similar
        self.offset = 0
        self.page_size = preferences.page_size
        self.items: list[dict[str, Any]] = []
        self.total = 0
        self.detail: dict[str, Any] | None = None
        self.writes_enabled = False
        self.thumbnail_size = preferences.thumbnail_size
        self.thumbnail_service = ThumbnailService(
            service.layout.root, max_size=(self.thumbnail_size, self.thumbnail_size)
        )
        self.detail_thumbnail_service = ThumbnailService(
            service.layout.root, max_size=(1600, 1200)
        )
        self.preview_items: list[dict[str, Any]] = []
        self._detail_generation = 0
        self._pending_detail_request: tuple[int, int] | None = None
        self._preview_generation = 0
        layout = QVBoxLayout(self)
        title = QLabel("Similar Images" if similar else "Exact Duplicates")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        if similar:
            warning = QLabel(
                "Similarity evidence keeps content identities distinct and never implies an exact duplicate or automatic canonical choice."
            )
            warning.setWordWrap(True)
            warning.setObjectName("boundaryNotice")
            layout.addWidget(warning)
            similarity_help = QLabel(SIMILARITY_HELP_TEXT)
            similarity_help.setWordWrap(True)
            similarity_help.setObjectName("helpText")
            similarity_help.setToolTip(SIMILARITY_HELP_TEXT)
            layout.addWidget(similarity_help)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Status"))
        self.status = QComboBox()
        self.status.addItem("All", None)
        values = ("pending", "decided", "large") if similar else ("pending", "decided", "abstained")
        for value in values:
            self.status.addItem("Large groups" if value == "large" else value.title(), value)
        self.status.currentIndexChanged.connect(self._filter_changed)
        controls.addWidget(self.status)
        controls.addWidget(QLabel("Page size"))
        self.page_size_box = QComboBox()
        for value in ALLOWED_PAGE_SIZES:
            self.page_size_box.addItem(str(value), value)
        self.page_size_box.setCurrentIndex(ALLOWED_PAGE_SIZES.index(self.page_size))
        self.page_size_box.currentIndexChanged.connect(self._page_size_changed)
        self.page_size_box.setToolTip("Number of review groups loaded per page")
        controls.addWidget(self.page_size_box)
        controls.addWidget(QLabel("Preview"))
        self.thumbnail_size_box = QComboBox()
        for value in ALLOWED_THUMBNAIL_SIZES:
            self.thumbnail_size_box.addItem(f"{value}px", value)
        self.thumbnail_size_box.setCurrentIndex(ALLOWED_THUMBNAIL_SIZES.index(self.thumbnail_size))
        self.thumbnail_size_box.currentIndexChanged.connect(self._thumbnail_size_changed)
        controls.addWidget(self.thumbnail_size_box)
        self.previous = QPushButton("Previous")
        self.next = QPushButton("Next")
        self.previous.clicked.connect(self._previous)
        self.next.clicked.connect(self._next)
        self.previous.setToolTip("Previous review page (Ctrl+Page Up)")
        self.next.setToolTip("Next review page (Ctrl+Page Down)")
        controls.addStretch()
        controls.addWidget(self.previous)
        controls.addWidget(self.next)
        self.page_label = QLabel()
        controls.addWidget(self.page_label)
        layout.addLayout(controls)
        splitter = QSplitter(Qt.Vertical)
        self.splitter = splitter
        self.groups = QTableWidget()
        self.groups.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.groups.setSelectionMode(QAbstractItemView.SingleSelection)
        self.groups.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.groups.setAlternatingRowColors(True)
        self.groups.verticalHeader().setVisible(False)
        self.groups.itemSelectionChanged.connect(self._group_selected)
        splitter.addWidget(self.groups)
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        self.context_banner = QLabel()
        self.context_banner.setObjectName("exactIdentityBanner" if not similar else "similarityBanner")
        self.context_banner.setWordWrap(True)
        self.context_banner.setVisible(False)
        detail_layout.addWidget(self.context_banner)
        self.detail_label = QLabel("Select a review group.")
        self.detail_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_label)
        self.instances = QTableWidget()
        self.instances.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.instances.setSelectionMode(QAbstractItemView.SingleSelection)
        self.instances.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.instances.setAlternatingRowColors(True)
        self.instances.verticalHeader().setVisible(False)
        if not similar:
            three_rows = self.instances.verticalHeader().defaultSectionSize() * 3
            header = self.instances.horizontalHeader().sizeHint().height()
            self.instances.setMinimumHeight(header + three_rows + 8)
        self.instances.itemSelectionChanged.connect(self._instance_selected)
        self.instances.itemDoubleClicked.connect(
            lambda item: QApplication.clipboard().setText(item.text())
        )
        detail_layout.addWidget(self.instances)
        self.previews = QListWidget()
        self.previews.setViewMode(QListWidget.IconMode)
        self.previews.setIconSize(thumbnail_icon_size(self.thumbnail_size))
        self.previews.setResizeMode(QListWidget.Adjust)
        self.previews.setSpacing(10)
        self.previews.setGridSize(QSize(self.thumbnail_size + 52, self.thumbnail_size + 86))
        self.previews.setMinimumHeight(min(300, self.thumbnail_size + 90))
        self.previews.setMaximumHeight(self.thumbnail_size + 120)
        self.previews.setAccessibleName("Read-only preview evidence")
        detail_layout.addWidget(self.previews)
        copy_widget = QWidget()
        copy_controls = QHBoxLayout(copy_widget)
        copy_controls.setContentsMargins(0, 0, 0, 0)
        self.copy_path_button = QPushButton("Copy path")
        self.copy_hash_button = QPushButton("Copy SHA-256")
        self.copy_path_button.setToolTip("Copy selected current path to the clipboard")
        self.copy_hash_button.setToolTip("Copy selected full SHA-256 to the clipboard")
        self.copy_path_button.clicked.connect(self._copy_path)
        self.copy_hash_button.clicked.connect(self._copy_hash)
        self.copy_path_button.setEnabled(False)
        self.copy_hash_button.setEnabled(False)
        copy_controls.addWidget(self.copy_path_button)
        copy_controls.addWidget(self.copy_hash_button)
        copy_controls.addStretch()
        detail_layout.addWidget(copy_widget)
        self.decision_widget = QWidget()
        decision_controls = QVBoxLayout(self.decision_widget)
        decision_controls.setContentsMargins(0, 4, 0, 0)
        owner_row = QHBoxLayout()
        self.actor = QLineEdit()
        self.actor.setPlaceholderText("Explicit owner/actor")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Optional reason")
        self.scope = QComboBox()
        self.scope.addItem("Archival", "archival")
        self.scope.addItem("Display / export", "display_export")
        self.scope.setToolTip(
            "Archival chooses the preferred preservation copy; display/export chooses the copy "
            "preferred for viewing or sharing. They may be different."
        )
        self.scope.currentIndexChanged.connect(self._update_decision_buttons)
        self.nominate_button = QPushButton("Nominate selected")
        self.nominate_button.setToolTip(
            "Record this copy as a candidate. Nomination does not approve it."
        )
        self.approve_button = QPushButton("Approve pending")
        self.approve_button.setToolTip(
            "Approve the selected pending nomination as a separate owner event."
        )
        self.reject_button = QPushButton("Reject pending")
        self.supersede_button = QPushButton("Supersede approval")
        self.abstain_button = QPushButton("Abstain")
        self.nominate_button.clicked.connect(lambda: self._decision("nominate"))
        self.approve_button.clicked.connect(lambda: self._decision("approve"))
        self.reject_button.clicked.connect(lambda: self._decision("reject"))
        self.supersede_button.clicked.connect(lambda: self._decision("supersede"))
        self.abstain_button.clicked.connect(lambda: self._decision("abstain"))
        for label, widget in (("Owner", self.actor), ("Reason", self.reason), ("Scope", self.scope)):
            owner_row.addWidget(QLabel(label))
            owner_row.addWidget(widget)
        owner_row.addStretch()
        decision_controls.addLayout(owner_row)
        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("Nomination"))
        action_row.addWidget(self.nominate_button)
        action_row.addSpacing(14)
        action_row.addWidget(QLabel("Resolve nomination"))
        for button in (self.approve_button, self.reject_button, self.supersede_button):
            action_row.addWidget(button)
        action_row.addStretch()
        action_row.addWidget(self.abstain_button)
        decision_controls.addLayout(action_row)
        self.decision_widget.setVisible(not similar)
        detail_layout.addWidget(self.decision_widget)
        splitter.addWidget(detail_widget)
        saved_splitter = (
            preferences.similar_review_splitter
            if similar
            else preferences.exact_review_splitter
        )
        splitter.setSizes(
            saved_splitter
            or preferences.review_splitter
            or ([290, 610] if similar else [230, 670])
        )
        layout.addWidget(splitter)
        self.previews.itemDoubleClicked.connect(self._open_preview)
        QShortcut(QKeySequence("Alt+Down"), self, activated=lambda: self._move_group(1))
        QShortcut(QKeySequence("Alt+Up"), self, activated=lambda: self._move_group(-1))
        QShortcut(QKeySequence("Ctrl+PgDown"), self, activated=self._next)
        QShortcut(QKeySequence("Ctrl+PgUp"), self, activated=self._previous)
        QShortcut(QKeySequence("Return"), self, activated=self._open_current_preview)

    def refresh(self) -> None:
        self._detail_generation += 1
        self._pending_detail_request = None
        self._clear_detail("Loading bounded review page…")
        if not self.similar:
            self.run_async(self.service.decision_writes_enabled, self._decision_health_loaded)
        selected_filter = self.status.currentData()
        if self.similar:
            self.run_async(
                lambda: self.service.similar_reviews(
                    status=None if selected_filter == "large" else selected_filter,
                    large_only=selected_filter == "large",
                    limit=self.page_size,
                    offset=self.offset,
                ),
                self._groups_loaded,
            )
        else:
            self.run_async(
                lambda: self.service.exact_reviews(
                    status=selected_filter, limit=self.page_size, offset=self.offset
                ),
                self._groups_loaded,
            )

    def _decision_health_loaded(self, enabled: bool) -> None:
        self.writes_enabled = bool(enabled)
        self._update_decision_buttons()

    def _groups_loaded(self, report: dict[str, Any]) -> None:
        self.items = report["items"]
        columns = (
            ["Images", "Review tier", "pHash distance", "dHash distance", "Attention", "Status", "Group ID"]
            if self.similar else
            ["Copies", "Sources", "Size", "Archival", "Display", "Review status", "Content ID"]
        )
        self.groups.setColumnCount(len(columns))
        self.groups.setHorizontalHeaderLabels(columns)
        self.groups.setRowCount(len(self.items))
        for row_index, item in enumerate(self.items):
            if self.similar:
                values = (
                    item["unique_contents"], owner_state_label(item["review_tier"]),
                    "–".join(map(str, item["phash_distance_range"])),
                    "–".join(map(str, item["dhash_distance_range"])),
                    "Very large / low confidence" if item["is_over_50"] else (
                        "Large / ambiguous" if item["is_large_ambiguous"] else ""
                    ), owner_state_label(item["review_status"]), item["context_id"],
                )
            else:
                scopes = item["canonical_scopes"]
                values = (
                    item["group_size"], ", ".join(item["sources"]),
                    format_bytes(item["size_bytes_max"]),
                    owner_state_label(scopes["archival"]),
                    owner_state_label(scopes["display_export"]),
                    owner_state_label(item["review_status"]), item["context_id"],
                )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value or "—"))
                if column == len(columns) - 1:
                    cell.setForeground(QColor("#666666"))
                self.groups.setItem(row_index, column, cell)
        header = self.groups.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(4 if self.similar else 1, QHeaderView.Stretch)
        if self.similar:
            self.groups.horizontalHeaderItem(2).setToolTip(SIMILARITY_HELP_TEXT)
            self.groups.horizontalHeaderItem(3).setToolTip(SIMILARITY_HELP_TEXT)
            self.groups.horizontalHeaderItem(1).setToolTip(
                "Owner-facing review category; similarity never means exact identity."
            )
        else:
            self.groups.horizontalHeaderItem(3).setToolTip(
                "Preferred copy for preservation; explicit owner approval is required."
            )
            self.groups.horizontalHeaderItem(4).setToolTip(
                "Preferred copy for viewing, sharing, or export; it may differ from archival."
            )
        total = report["total_matching"]
        self.total = total
        self.page_label.setText(f"{self.offset + 1 if total else 0}–{min(self.offset + len(self.items), total)} of {total}")
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset + self.page_size < total)
        if self.detail is None:
            self.detail_label.setText("Select a review group.")

    def _group_selected(self) -> None:
        row = self.groups.currentRow()
        if row < 0 or row >= len(self.items):
            return
        context_id = int(self.items[row]["context_id"])
        self._detail_generation += 1
        request = (self._detail_generation, context_id)
        self._pending_detail_request = request
        self._clear_detail("Loading group detail…")
        operation = self.service.similar_detail if self.similar else self.service.exact_detail
        self.run_async(
            lambda: operation(context_id),
            lambda detail, request=request: self._detail_loaded(detail, request),
        )

    def _clear_detail(self, message: str) -> None:
        self._preview_generation += 1
        self.detail = None
        self.preview_items = []
        self.instances.clearContents()
        self.instances.setRowCount(0)
        self.previews.clear()
        self.context_banner.setVisible(False)
        self.copy_path_button.setEnabled(False)
        self.copy_hash_button.setEnabled(False)
        self.detail_label.setText(message)

    def _detail_loaded(
        self,
        detail: dict[str, Any],
        request: tuple[int, int] | None = None,
    ) -> None:
        if request is not None and (
            request != self._pending_detail_request
            or int(detail["context_id"]) != request[1]
        ):
            return
        self._pending_detail_request = None
        self.detail = detail
        self._preview_generation += 1
        preview_generation = self._preview_generation
        warning = ""
        if self.similar and (detail["is_large_ambiguous"] or detail["is_over_50"]):
            warning = " — large low-confidence review cluster"
        if self.similar:
            self.context_banner.setText(
                "These images are visually similar, not byte-for-byte identical. Review the previews before drawing conclusions."
            )
            self.context_banner.setToolTip(
                "Similar-image groups use perceptual evidence and do not establish exact identity."
            )
            self.detail_label.setText(
                f"Similar group {detail['context_id']} · "
                f"{len(detail['physical_instances'])} files · "
                f"{len(detail.get('relationships', []))} relationships · "
                f"{owner_state_label(detail['review_status'])}{warning}"
            )
        else:
            self.context_banner.setText(
                "These files are byte-for-byte identical according to their verified SHA-256 evidence."
            )
            self.context_banner.setToolTip(
                "Exact duplicate means the catalogue records the same verified SHA-256 content identity."
            )
            scopes = detail["decision_state"]["scopes"]
            self.detail_label.setText(
                f"Exact group {detail['context_id']} · {len(detail['physical_instances'])} copies · "
                f"Archival: {owner_state_label(scopes['archival']['status'])} · "
                f"Display: {owner_state_label(scopes['display_export']['status'])} · "
                f"{owner_state_label(detail['review_status'])}"
            )
        self.context_banner.setVisible(True)
        rows = detail["physical_instances"]
        columns = [
            "Filename", "Source", "Size", "Modified", "Archival", "Display",
            "Instance ID", "Content ID", "SHA-256", "Current path", "Raw path", "Type", "Created",
        ]
        self.instances.setColumnCount(len(columns))
        self.instances.setHorizontalHeaderLabels(columns)
        self.instances.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            values = (
                item_filename(item), item["source"], format_bytes(item["size_bytes"]),
                display_timestamp(item["observed_modified_at"]),
                canonical_scope_label(item["canonical"], "archival"),
                canonical_scope_label(item["canonical"], "display_export"),
                item["physical_instance_id"], item["content_identity_id"], item["sha256"],
                item["current_observed_path"], item["raw_relative_path"], item["extension"],
                display_timestamp(item["observed_created_at"]),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value or "—"))
                raw_tooltip = (
                    str(item["observed_modified_at"] or "") if column == 3 else
                    str(item["observed_created_at"] or "") if column == 12 else
                    str(value or "")
                )
                cell.setToolTip(raw_tooltip)
                if column >= 6:
                    cell.setForeground(QColor("#666666"))
                self.instances.setItem(row_index, column, cell)
        detail_header = self.instances.horizontalHeader()
        detail_header.setSectionResizeMode(QHeaderView.Interactive)
        detail_header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4, 5, 6, 7, 11, 12):
            detail_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.instances.setColumnWidth(8, 150)
        self.instances.setColumnWidth(9, 220)
        self.instances.setColumnWidth(10, 220)
        self.previews.clear()
        self.preview_items = rows[:12]
        for item in self.preview_items:
            label = QListWidgetItem(preview_caption(item))
            path = str(item["current_observed_path"] or "")
            label.setToolTip(
                metadata_summary(item)
                + f"\nInstance: {item['physical_instance_id']}\nPath: {path or 'Unavailable'}"
            )
            binding = PreviewBinding(
                generation=preview_generation,
                context_type=str(detail["context_type"]),
                context_id=int(detail["context_id"]),
                physical_instance_id=int(item["physical_instance_id"]),
                source_path=path,
            )
            label.setData(PREVIEW_INSTANCE_ROLE, binding.physical_instance_id)
            label.setData(PREVIEW_PATH_ROLE, binding.source_path)
            label.setData(PREVIEW_CONTEXT_ROLE, binding.context_id)
            label.setData(PREVIEW_GENERATION_ROLE, binding.generation)
            self.previews.addItem(label)
            if path:
                task = ThumbnailTask(
                    self.thumbnail_service,
                    path,
                    item["content_identity_key"],
                    binding,
                    binding.physical_instance_id,
                )
                task.signals.loaded.connect(self._thumbnail_loaded)
                self.pool.start(task)
        self._update_decision_buttons()

    def _thumbnail_loaded(self, token: object, image: object, error: str) -> None:
        if not isinstance(token, PreviewBinding) or not self._binding_is_current(token):
            return
        item = self._preview_widget_for_binding(token)
        if item is None:
            return
        if not image.isNull():
            item.setIcon(QIcon(QPixmap.fromImage(image)))
        elif error:
            item.setText(item.text() + "\nPreview unavailable")
            item.setToolTip(error)

    def _binding_is_current(self, binding: PreviewBinding) -> bool:
        return bool(
            self.detail is not None
            and binding.generation == self._preview_generation
            and binding.context_type == self.detail["context_type"]
            and binding.context_id == int(self.detail["context_id"])
        )

    def _preview_widget_for_binding(
        self, binding: PreviewBinding
    ) -> QListWidgetItem | None:
        for index in range(self.previews.count()):
            item = self.previews.item(index)
            if (
                int(item.data(PREVIEW_INSTANCE_ROLE)) == binding.physical_instance_id
                and str(item.data(PREVIEW_PATH_ROLE)) == binding.source_path
                and int(item.data(PREVIEW_CONTEXT_ROLE)) == binding.context_id
                and int(item.data(PREVIEW_GENERATION_ROLE)) == binding.generation
            ):
                return item
        return None

    def preview_binding_snapshot(self) -> list[dict[str, Any]]:
        """Return test/diagnostic preview bindings; no debug UI is exposed."""

        return [
            {
                "physical_instance_id": int(self.previews.item(index).data(PREVIEW_INSTANCE_ROLE)),
                "source_path": str(self.previews.item(index).data(PREVIEW_PATH_ROLE)),
                "context_id": int(self.previews.item(index).data(PREVIEW_CONTEXT_ROLE)),
                "generation": int(self.previews.item(index).data(PREVIEW_GENERATION_ROLE)),
                "caption": self.previews.item(index).text(),
                "tooltip": self.previews.item(index).toolTip(),
                "has_icon": not self.previews.item(index).icon().isNull(),
            }
            for index in range(self.previews.count())
        ]

    def preview_bindings_match_detail(self) -> bool:
        if self.detail is None:
            return self.previews.count() == 0
        expected = [
            (int(item["physical_instance_id"]), str(item.get("current_observed_path") or ""))
            for item in self.detail["physical_instances"][:12]
        ]
        snapshot = self.preview_binding_snapshot()
        actual = [
            (item["physical_instance_id"], item["source_path"])
            for item in snapshot
        ]
        return bool(
            actual == expected
            and all(
                item["context_id"] == int(self.detail["context_id"])
                and item["generation"] == self._preview_generation
                and str(item["physical_instance_id"]) in item["tooltip"]
                and item["source_path"] in item["tooltip"]
                for item in snapshot
            )
        )

    def _instance_selected(self) -> None:
        row = self.instances.currentRow()
        self.copy_path_button.setEnabled(row >= 0)
        self.copy_hash_button.setEnabled(row >= 0)
        if 0 <= row < self.previews.count():
            self.previews.setCurrentRow(row)
        self._update_decision_buttons()

    def _selected_instance(self) -> dict[str, Any] | None:
        if self.detail is None:
            return None
        row = self.instances.currentRow()
        values = self.detail["physical_instances"]
        return values[row] if 0 <= row < len(values) else None

    def _scope_state(self) -> dict[str, Any] | None:
        if self.detail is None:
            return None
        return self.detail["decision_state"]["scopes"][self.scope.currentData()]

    def _update_decision_buttons(self) -> None:
        if self.similar:
            return
        selected = self._selected_instance()
        scope = self._scope_state()
        pending = [] if scope is None else scope["pending_nominations"]
        self.nominate_button.setEnabled(self.writes_enabled and selected is not None)
        selected_pending = selected is not None and any(
            int(item["physical_instance_id"]) == int(selected["physical_instance_id"])
            for item in pending
        )
        self.approve_button.setEnabled(bool(self.writes_enabled and selected_pending and not scope["approved"]))
        self.reject_button.setEnabled(bool(self.writes_enabled and selected_pending))
        self.supersede_button.setEnabled(bool(self.writes_enabled and selected_pending and scope["approved"]))
        self.abstain_button.setEnabled(self.writes_enabled and self.detail is not None)

    def _decision(self, action: str) -> None:
        actor = self.actor.text().strip()
        reason = self.reason.text().strip() or None
        selected = self._selected_instance()
        scope_name = self.scope.currentData()
        scope = self._scope_state()
        if not actor:
            self.show_error("Enter the explicit owner/actor before recording a decision.")
            return
        if self.detail is None or scope is None or (action != "abstain" and selected is None):
            self.show_error("Select a physical representation first.")
            return
        primary, informative, technical = decision_confirmation_text(
            action=action,
            scope=str(scope_name),
            actor=actor,
            reason=reason,
            context_id=int(self.detail["context_id"]),
            selected=None if action == "abstain" else selected,
        )
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle("Confirm owner decision")
        confirmation.setIcon(QMessageBox.Question)
        confirmation.setText(primary)
        confirmation.setInformativeText(informative)
        confirmation.setDetailedText(technical)
        confirmation.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        confirmation.setDefaultButton(QMessageBox.Cancel)
        if selected is not None and action != "abstain":
            for index in range(self.previews.count()):
                preview = self.previews.item(index)
                if int(preview.data(PREVIEW_INSTANCE_ROLE)) == int(
                    selected["physical_instance_id"]
                ) and not preview.icon().isNull():
                    confirmation.setIconPixmap(preview.icon().pixmap(128, 128))
                    break
        if confirmation.exec() != QMessageBox.Yes:
            return
        if action == "nominate":
            operation = lambda: self.service.nominate(
                context_type="exact", context_id=int(self.detail["context_id"]),
                physical_instance_id=int(selected["physical_instance_id"]),
                canonical_scope=scope_name, actor=actor, reason=reason,
            )
        elif action == "abstain":
            content_id = int(self.detail["context_id"])
            prior = scope["approved"]
            operation = lambda: self.service.abstain(
                context_type="exact", context_id=content_id, content_identity_id=content_id,
                canonical_scope=scope_name, actor=actor, reason=reason,
                prior_approval_id=None if prior is None else prior["approval_event_id"],
            )
        else:
            pending = next(
                item for item in scope["pending_nominations"]
                if int(item["physical_instance_id"]) == int(selected["physical_instance_id"])
            )
            prior = scope["approved"]
            operation = lambda: self.service.resolve_nomination(
                action=action, nomination_id=pending["nomination_event_id"],
                physical_instance_id=int(selected["physical_instance_id"]),
                canonical_scope=scope_name, actor=actor, reason=reason,
                prior_approval_id=None if prior is None else prior["approval_event_id"],
            )
        self.run_async(operation, self._decision_succeeded)

    def _decision_succeeded(self, result: dict[str, Any]) -> None:
        scope = self.scope.currentData()
        status = result["current_state"]["scopes"][scope]["status"]
        QMessageBox.information(
            self, "Decision recorded", f"Append-only decision recorded.\n{scope}: {status}"
        )
        self._group_selected()

    def _copy_path(self) -> None:
        selected = self._selected_instance()
        if selected is not None:
            QApplication.clipboard().setText(
                str(selected.get("current_observed_path") or selected.get("raw_relative_path") or "")
            )

    def _copy_hash(self) -> None:
        selected = self._selected_instance()
        if selected is not None:
            QApplication.clipboard().setText(str(selected.get("sha256") or ""))

    def _open_preview(self, item: QListWidgetItem) -> None:
        self._open_preview_index(self.previews.row(item))

    def _open_current_preview(self) -> None:
        self._open_preview_index(self.previews.currentRow())

    def _open_preview_index(self, index: int) -> None:
        if not 0 <= index < len(self.preview_items):
            return
        item = self.preview_items[index]
        path = item.get("current_observed_path")
        if not path:
            self.show_error("The selected physical representation is unavailable.")
            return
        self.detail_label.setText("Loading enlarged read-only preview…")
        binding = PreviewBinding(
            generation=self._preview_generation,
            context_type=str(self.detail["context_type"]),
            context_id=int(self.detail["context_id"]),
            physical_instance_id=int(item["physical_instance_id"]),
            source_path=str(path),
        )
        task = ThumbnailTask(
            self.detail_thumbnail_service,
            str(path),
            item["content_identity_key"],
            binding,
            binding.physical_instance_id,
        )
        task.signals.loaded.connect(self._large_preview_loaded)
        self.pool.start(task)

    def _large_preview_loaded(self, token: object, image: object, error: str) -> None:
        if not isinstance(token, PreviewBinding) or not self._binding_is_current(token):
            return
        selected = next(
            (
                item for item in self.preview_items
                if int(item["physical_instance_id"]) == token.physical_instance_id
                and str(item.get("current_observed_path") or "") == token.source_path
            ),
            None,
        )
        if selected is None:
            return
        if error or image.isNull():
            self.show_error(error or "The selected preview could not be decoded.")
            return
        primary, technical = metadata_blocks(selected)
        dialog = ImageViewerDialog(image, primary, technical, self)
        dialog.exec()

    def _move_group(self, delta: int) -> None:
        row = bounded_row(self.groups.currentRow(), self.groups.rowCount(), delta)
        if row >= 0:
            self.groups.selectRow(row)
            self.groups.scrollToItem(self.groups.item(row, 0))

    def _filter_changed(self) -> None:
        self.offset = 0
        self.refresh()

    def _page_size_changed(self) -> None:
        self.page_size = int(self.page_size_box.currentData())
        self.offset = 0
        self.refresh()

    def _thumbnail_size_changed(self) -> None:
        self.thumbnail_size = int(self.thumbnail_size_box.currentData())
        self.thumbnail_service = ThumbnailService(
            self.service.layout.root, max_size=(self.thumbnail_size, self.thumbnail_size)
        )
        self.previews.setIconSize(thumbnail_icon_size(self.thumbnail_size))
        self.previews.setGridSize(QSize(self.thumbnail_size + 52, self.thumbnail_size + 86))
        self.previews.setMinimumHeight(min(300, self.thumbnail_size + 90))
        self.previews.setMaximumHeight(self.thumbnail_size + 120)
        if self.detail is not None:
            self._detail_loaded(self.detail)

    def _previous(self) -> None:
        self.offset = max(0, self.offset - self.page_size)
        self.refresh()

    def _next(self) -> None:
        if self.offset + self.page_size < self.total:
            self.offset += self.page_size
            self.refresh()


class TablePage(AsyncPage):
    def __init__(
        self, service: DesktopDataService, title: str,
        loader: Callable[[], Any], rows: Callable[[Any], list[dict[str, Any]]],
        columns: tuple[tuple[str, str], ...], notice: str,
        detail_loader: Callable[[dict[str, Any]], Any] | None = None,
        empty_message: str = "No records are available.",
        stretch_column: int | None = None,
    ) -> None:
        super().__init__(service)
        self.loader = loader
        self.row_adapter = rows
        self.columns = columns
        self.detail_loader = detail_loader
        self.empty_message = empty_message
        self.stretch_column = stretch_column
        self.rows: list[dict[str, Any]] = []
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        boundary = QLabel(notice)
        boundary.setWordWrap(True)
        boundary.setObjectName("boundaryNotice")
        if title == "Quarantine":
            boundary.setToolTip(
                "This screen is read-only. It cannot quarantine or restore files."
            )
        layout.addWidget(boundary)
        self.message = QLabel()
        layout.addWidget(self.message)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemDoubleClicked.connect(
            lambda item: QApplication.clipboard().setText(item.text())
        )
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a row to inspect its read-only detail and history.")
        self.detail.setVisible(detail_loader is not None)
        layout.addWidget(self.detail)

    def refresh(self) -> None:
        self.message.setText("Loading…")
        self.run_async(self.loader, self._loaded, lambda error: self.message.setText(error))

    def _loaded(self, report: Any) -> None:
        rows = self.row_adapter(report)
        self.rows = rows
        self.message.setText(
            f"{len(rows)} records shown" if rows else self.empty_message
        )
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([label for _, label in self.columns])
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, (key, _) in enumerate(self.columns):
                value = row.get(key)
                if key.endswith("_bytes") or key in {"total_bytes", "backup_database_size_bytes"}:
                    displayed = format_bytes(value)
                elif key in {"occurred_at", "created_at", "requested_at"}:
                    displayed = display_timestamp(value)
                elif key in {
                    "status", "quarantine_state", "action", "canonical_scope", "backup_class"
                }:
                    displayed = owner_state_label(value, empty="—")
                else:
                    displayed = str(value if value is not None else "—")
                cell = QTableWidgetItem(displayed)
                cell.setToolTip(str(value or ""))
                self.table.setItem(row_index, column, cell)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        if self.stretch_column is not None and self.columns:
            header.setSectionResizeMode(self.stretch_column, QHeaderView.Stretch)

    def _selection_changed(self) -> None:
        if self.detail_loader is None:
            return
        row = self.table.currentRow()
        if not 0 <= row < len(self.rows):
            return
        self.detail.setPlainText("Loading detail…")
        self.run_async(
            lambda: self.detail_loader(self.rows[row]),
            lambda value: self.detail.setPlainText(
                json.dumps(value, indent=2, ensure_ascii=False, default=str)
            ),
            lambda error: self.detail.setPlainText(error),
        )


class BackupPage(TablePage):
    def __init__(self, service: DesktopDataService) -> None:
        super().__init__(
            service, "Backups / Recovery", service.backups, self._rows,
            (("backup_class", "Class"), ("created_at", "Created"),
             ("backup_database_size_bytes", "Size"), ("status", "Verification"),
             ("backup_id", "Backup ID"), ("backup_sha256", "SHA-256"),
             ("manifest_path", "Manifest path")),
            "Read-only backup and disaster-recovery visibility. Catalogue restore is unavailable here.",
            empty_message="No verified catalogue backups are currently listed.",
            stretch_column=1,
        )

    def _loaded(self, report: Any) -> None:
        super()._loaded(report)
        for column, width in ((4, 175), (5, 190), (6, 240)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Interactive)
            self.table.setColumnWidth(column, width)

    @staticmethod
    def _rows(report: dict[str, Any]) -> list[dict[str, Any]]:
        rows = list(report["operational"]["backups"])
        rows.extend(report["independent"]["backups"])
        return rows


class MainWindow(QMainWindow):
    SECTION_NAMES = (
        "Overview", "Library", "Exact Duplicates", "Similar Images", "Decisions",
        "Plans", "Quarantine", "Backups / Recovery",
    )

    def __init__(self, service: DesktopDataService) -> None:
        super().__init__()
        self.service = service
        self.preference_store = PreferenceStore(service.layout.root)
        self.preferences = self.preference_store.load()
        self.setWindowTitle("Personal Librarian")
        self.resize(1280, 840)
        if self.preferences.window_geometry:
            try:
                self.restoreGeometry(
                    QByteArray.fromBase64(self.preferences.window_geometry.encode("ascii"))
                )
            except (ValueError, TypeError):
                pass
        container = QWidget()
        outer = QVBoxLayout(container)
        header = QHBoxLayout()
        title = QLabel("Personal Librarian")
        title.setObjectName("appTitle")
        self.health_label = QLabel("Catalogue: checking…")
        self.health_label.setAccessibleName("Production catalogue and disaster-recovery health")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Refresh the current section and health (F5)")
        self.refresh_button.clicked.connect(self.refresh_current)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.health_label)
        header.addWidget(self.refresh_button)
        outer.addLayout(header)
        shell = QSplitter(Qt.Horizontal)
        self.shell = shell
        self.navigation = QListWidget()
        self.navigation.setAccessibleName("Application sections")
        self.navigation.addItems(self.SECTION_NAMES)
        self.navigation.setMinimumWidth(190)
        self.navigation.setMaximumWidth(230)
        self.navigation.setSpacing(2)
        shell.addWidget(self.navigation)
        self.stack = QStackedWidget()
        self.exact_page = ReviewPage(service, similar=False, preferences=self.preferences)
        self.similar_page = ReviewPage(service, similar=True, preferences=self.preferences)
        self.exact_page.page_size_box.currentIndexChanged.connect(
            lambda index: self._sync_combo(self.similar_page.page_size_box, index)
        )
        self.similar_page.page_size_box.currentIndexChanged.connect(
            lambda index: self._sync_combo(self.exact_page.page_size_box, index)
        )
        self.exact_page.thumbnail_size_box.currentIndexChanged.connect(
            lambda index: self._sync_combo(self.similar_page.thumbnail_size_box, index)
        )
        self.similar_page.thumbnail_size_box.currentIndexChanged.connect(
            lambda index: self._sync_combo(self.exact_page.thumbnail_size_box, index)
        )
        self.pages: list[AsyncPage] = [
            OverviewPage(service),
            LibraryPage(service, self.preferences),
            self.exact_page,
            self.similar_page,
            TablePage(
                service, "Decision History", lambda: service.decisions(limit=100), lambda value: value,
                (("occurred_at", "Timestamp"), ("action", "Event"), ("owner", "Actor"),
                 ("context_type", "Context"), ("context_id", "Context ID"),
                 ("physical_instance_id", "Target"), ("canonical_scope", "Scope"),
                 ("reason", "Reason"), ("related_event_id", "Related event")),
                "Append-only history. Historical decisions cannot be edited or deleted here.",
                empty_message="No owner decisions recorded yet.",
                stretch_column=7,
            ),
            TablePage(
                service, "Plans", lambda: service.plans(limit=50), lambda value: value["plans"],
                (("plan_id", "Plan ID"), ("policy", "Policy"), ("status", "Status"),
                 ("context_type", "Context"), ("context_id", "Context ID"),
                 ("item_count", "Items"), ("total_bytes", "Bytes"),
                 ("destination_root", "Destination")),
                "Read-only dry-run plan visibility. Generic plan execution is unavailable.",
                detail_loader=lambda row: service.plan(str(row["plan_id"])),
                empty_message="No action plans currently exist.",
                stretch_column=1,
            ),
            TablePage(
                service, "Quarantine", lambda: service.quarantine(limit=100),
                lambda value: value["executions"],
                (("execution_id", "Execution"), ("status", "Result"),
                 ("quarantine_state", "State"), ("source_path", "Original path"),
                 ("destination_path", "Quarantine path"), ("sha256", "SHA-256"),
                 ("failure_reason", "Recovery / failure")),
                "Read-only execution history. Quarantine and restore remain CLI-only.",
                detail_loader=lambda row: service.quarantine_detail(str(row["execution_id"])),
                empty_message="No quarantine history exists.",
                stretch_column=6,
            ),
            BackupPage(service),
        ]
        self.pages[0].navigate_requested.connect(self.navigation.setCurrentRow)
        self.pages[0].library_requested.connect(self._open_library)
        for page in self.pages:
            self.stack.addWidget(page)
        shell.addWidget(self.stack)
        shell.setSizes(self.preferences.shell_splitter or [205, 1075])
        outer.addWidget(shell)
        self.setCentralWidget(container)
        self.statusBar().showMessage("Read-only views · explicit owner decisions only · physical actions unavailable")
        self.navigation.currentRowChanged.connect(self._section_changed)
        last = self.preferences.last_section
        self.navigation.setCurrentRow(max(0, min(last, len(self.pages) - 1)))
        QShortcut(QKeySequence.Refresh, self, activated=self.refresh_current)
        self.setStyleSheet(
            "QLabel#appTitle { font-size: 20px; font-weight: 600; }"
            "QLabel#pageTitle { font-size: 18px; font-weight: 600; margin-bottom: 4px; }"
            "QLabel#boundaryNotice { background: #edf3f8; padding: 7px; color: #29465b; }"
            "QLabel#helpText { color: #4e5d68; padding: 2px 6px; }"
            "QLabel#exactIdentityBanner { background: #e9f6ed; color: #205c34; "
            "font-weight: 600; padding: 9px; border-left: 4px solid #3b8b55; }"
            "QLabel#similarityBanner { background: #fff7e6; color: #694d16; "
            "font-weight: 600; padding: 9px; border-left: 4px solid #c7922f; }"
            "QGroupBox#overviewCard { font-weight: 600; margin-top: 8px; padding: 8px; }"
            "QGroupBox#overviewCard::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
            "QListWidget { padding: 6px; }"
            "QListWidget::item { padding: 5px; border: 1px solid transparent; }"
            "QListWidget::item:selected { background: #dcecf7; border: 1px solid #4f86a6; color: #172b38; }"
            "QTableWidget { gridline-color: #d8d8d8; }"
        )
        self._refresh_health()

    def _open_library(self, mode: str) -> None:
        library = self.pages[1]
        library.tabs.setCurrentIndex(0)
        library.date_filter.setCurrentIndex(1 if mode == "needs_review" else 0)
        self.navigation.setCurrentRow(1)

    def _section_changed(self, index: int) -> None:
        if index < 0:
            return
        # Only the two responsive prototype pages may ignore hidden pages' size
        # hints. Keep legacy pages' normal minimum sizing when they are active.
        policy = QSizePolicy.Ignored if index in (0, 1) else QSizePolicy.Preferred
        self.stack.setSizePolicy(policy, policy)
        self.stack.setCurrentIndex(index)
        self.statusBar().showMessage(
            f"{self.SECTION_NAMES[index]} · "
            + (
                "logical organisation available with owner confirmation" if index == 1
                else "owner catalogue decisions available with confirmation" if index == 2
                else "read-only view"
            )
            + " · physical actions unavailable"
        )
        self.pages[index].refresh()

    @staticmethod
    def _sync_combo(target: QComboBox, index: int) -> None:
        if target.currentIndex() != index:
            target.setCurrentIndex(index)

    def refresh_current(self) -> None:
        self.pages[self.stack.currentIndex()].refresh()
        self._refresh_health()

    def _refresh_health(self) -> None:
        page = self.pages[0]
        page.run_async(
            self.service.health,
            self._health_loaded,
            lambda error: self.health_label.setText(f"Catalogue: unavailable · {error}"),
        )

    def _health_loaded(self, value: dict[str, Any]) -> None:
        catalogue = value.get("summary", "UNKNOWN")
        disaster = value.get("disaster_recovery", {}).get("summary", "NOT ASSESSED")
        self.health_label.setText(
            f"Catalogue {catalogue} · DR {disaster} · schema {value.get('schema_version', '—')}"
        )
        colour = {"PASS": "#247a3c", "WARN": "#8a6500", "FAIL": "#a32d2d"}.get(
            str(catalogue), "#555555"
        )
        self.health_label.setStyleSheet(f"font-weight: 600; color: {colour};")

    def closeEvent(self, event: object) -> None:
        self.preferences.last_section = self.navigation.currentRow()
        self.preferences.page_size = self.exact_page.page_size
        self.preferences.thumbnail_size = self.exact_page.thumbnail_size
        self.preferences.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.preferences.shell_splitter = self.shell.sizes()
        self.preferences.review_splitter = self.exact_page.splitter.sizes()
        self.preferences.exact_review_splitter = self.exact_page.splitter.sizes()
        self.preferences.similar_review_splitter = self.similar_page.splitter.sizes()
        self.preferences.last_actor = self.pages[1].actor.text().strip()
        self.preferences.library_tab = self.pages[1].tabs.currentIndex()
        self.preferences.last_year = self.pages[1].current_year
        self.preferences.collection_filter = (
            self.pages[1].collection_filter.currentText().casefold()
        )
        try:
            self.preference_store.save(self.preferences)
        except OSError:
            pass
        super().closeEvent(event)
