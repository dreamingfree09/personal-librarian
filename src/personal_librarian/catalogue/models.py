"""Small typed models shared by the catalogue layer."""

from __future__ import annotations

import ntpath
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


PATH_COMPARISON_KEY_VERSION = "windows-lexical-v1"


class CanonicalScope(StrEnum):
    ARCHIVAL = "archival"
    DISPLAY_EXPORT = "display_export"


class DecisionEventType(StrEnum):
    PROPOSAL = "proposal"
    APPROVAL = "approval"
    REJECTION = "rejection"
    WITHDRAWAL = "withdrawal"
    SUPERSESSION = "supersession"


class ReviewContextType(StrEnum):
    EXACT = "exact"
    SIMILAR = "similar"


class WorkflowAction(StrEnum):
    NOMINATE = "nominate"
    APPROVE = "approve"
    REJECT = "reject"
    SUPERSEDE = "supersede"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class CatalogueStatus:
    database_path: str
    schema_version: int
    current_schema_version: int
    up_to_date: bool
    foreign_keys_enabled: bool
    tables: tuple[str, ...]


def windows_path_comparison_key(raw_path: str) -> str:
    """Derive a non-authoritative Windows lookup key while preserving raw text elsewhere."""

    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("Raw path must be a non-empty string.")
    if "\x00" in raw_path:
        raise ValueError("Raw path must not contain a NUL byte.")
    lexical = ntpath.normpath(raw_path.replace("/", "\\"))
    return unicodedata.normalize("NFC", lexical).casefold()
