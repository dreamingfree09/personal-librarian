"""Harmless, recoverable desktop preferences stored under application state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from personal_librarian.safety import PathIntent, PathSafetyPolicy
from personal_librarian.desktop.state_files import StateFiles

PREFERENCES_VERSION = 1
ALLOWED_PAGE_SIZES = (25, 50, 100)
ALLOWED_THUMBNAIL_SIZES = (128, 160, 192, 256, 320)


@dataclass(slots=True)
class UiPreferences:
    version: int = PREFERENCES_VERSION
    last_section: int = 0
    page_size: int = 50
    thumbnail_size: int = 256
    window_geometry: str | None = None
    shell_splitter: list[int] | None = None
    review_splitter: list[int] | None = None
    exact_review_splitter: list[int] | None = None
    similar_review_splitter: list[int] | None = None
    last_actor: str = ""
    library_tab: int = 0
    last_year: int | None = None
    collection_filter: str = "active"


class PreferenceStore:
    def __init__(
        self, app_data_root: str | Path, *, safety_policy: PathSafetyPolicy | None = None
    ) -> None:
        self.policy = safety_policy or PathSafetyPolicy()
        root_check = self.policy.check_path(app_data_root, intent=PathIntent.READ)
        if not root_check.allowed:
            raise OSError(f"Unsafe application-data root: {root_check.code}")
        self.path = Path(app_data_root) / "state" / "ui_preferences.json"
        self.state = StateFiles(app_data_root, self.policy)

    def load(self) -> UiPreferences:
        try:
            value = json.loads(self.state.read(self.path, limit=64*1024).decode('utf-8'))
            return self._validated(value)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return UiPreferences()

    def save(self, preferences: UiPreferences) -> None:
        checked = self._validated(asdict(preferences))
        result = self.policy.check_path(str(self.path), intent=PathIntent.WRITE)
        if not result.allowed:
            raise OSError(f"Unsafe UI preference path: {result.code}")
        self.state.publish(
            self.path,
            (json.dumps(asdict(checked), ensure_ascii=False, indent=2) + "\n").encode('utf-8'),
            replace=True,
        )

    @staticmethod
    def _validated(value: Any) -> UiPreferences:
        if not isinstance(value, dict) or value.get("version") != PREFERENCES_VERSION:
            return UiPreferences()
        section = value.get("last_section")
        page_size = value.get("page_size")
        thumbnail_size = value.get("thumbnail_size")
        geometry = value.get("window_geometry")
        shell = value.get("shell_splitter")
        review = value.get("review_splitter")
        exact_review = value.get("exact_review_splitter")
        similar_review = value.get("similar_review_splitter")
        actor = value.get("last_actor")
        library_tab = value.get("library_tab")
        last_year = value.get("last_year")
        collection_filter = value.get("collection_filter")
        return UiPreferences(
            last_section=section if isinstance(section, int) and 0 <= section <= 7 else 0,
            page_size=page_size if page_size in ALLOWED_PAGE_SIZES else 50,
            thumbnail_size=thumbnail_size if thumbnail_size in ALLOWED_THUMBNAIL_SIZES else 256,
            window_geometry=geometry if isinstance(geometry, str) and len(geometry) <= 10000 else None,
            shell_splitter=PreferenceStore._sizes(shell),
            review_splitter=PreferenceStore._sizes(review),
            exact_review_splitter=PreferenceStore._sizes(exact_review),
            similar_review_splitter=PreferenceStore._sizes(similar_review),
            last_actor=actor.strip() if isinstance(actor, str) and len(actor) <= 200 else "",
            library_tab=library_tab if isinstance(library_tab, int) and 0 <= library_tab <= 3 else 0,
            last_year=(last_year if isinstance(last_year, int)
                       and not isinstance(last_year, bool) and 1900 <= last_year <= 2100 else None),
            collection_filter=(collection_filter if collection_filter in
                               {"active", "archived", "all"} else "active"),
        )

    @staticmethod
    def _sizes(value: Any) -> list[int] | None:
        if not isinstance(value, list) or not 2 <= len(value) <= 4:
            return None
        if not all(isinstance(item, int) and 0 <= item <= 10000 for item in value):
            return None
        return value
