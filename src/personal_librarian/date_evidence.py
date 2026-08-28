"""Typed M30 preferred-date evidence, policy, owner actions, and bounded queries."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import DateEvidenceError
from personal_librarian.catalogue.migrations import read_schema_version
from personal_librarian.safety import PathSafetyPolicy

DATE_SCHEMA_VERSION = 10
NORMALISATION_VERSION = "partial-date-v1"
PREFERRED_DATE_POLICY = "preferred-date-policy-v1"
PREFERRED_DATE_POLICY_NAME = "preferred-date-policy"
MAX_PAGE_SIZE = 500


class EvidenceType(StrEnum):
    OWNER_SET = "owner_set"
    EXIF_DATETIME_ORIGINAL = "exif_datetime_original"
    EMBEDDED_VIDEO_CAPTURE = "embedded_video_capture"
    GOOGLE_PHOTOS_TAKEOUT = "google_photos_takeout"
    ONEDRIVE_SOURCE_METADATA = "onedrive_source_metadata"
    FILENAME_DERIVED = "filename_derived"
    FILESYSTEM_MODIFIED = "filesystem_modified"
    FILESYSTEM_CREATED = "filesystem_created"
    SPECIALIST_IMPORT = "specialist_import"


class Precision(StrEnum):
    YEAR = "year"
    YEAR_MONTH = "year_month"
    DATE = "date"
    DATETIME = "datetime"


class TimePrecision(StrEnum):
    MINUTE = "minute"
    SECOND = "second"
    FRACTION = "fraction"


class TimezoneState(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"
    KNOWN_OFFSET = "known_offset"


class PreferredStatus(StrEnum):
    RESOLVED = "resolved"
    NEEDS_REVIEW = "needs_review"
    UNKNOWN = "unknown"


class SelectionMethod(StrEnum):
    OWNER_SELECTION = "owner_selection"
    POLICY_SELECTION = "policy_selection"
    NO_SELECTION = "no_selection"


class BasisRole(StrEnum):
    SELECTED = "selected"
    CORROBORATING = "corroborating"
    CONFLICTING = "conflicting"
    TIMEZONE_ADJACENT = "timezone_adjacent"
    IGNORED_LOWER_AUTHORITY = "ignored_lower_authority"


@dataclass(frozen=True, slots=True)
class PartialDate:
    year: int
    month: int | None = None
    day: int | None = None
    hour: int | None = None
    minute: int | None = None
    second: int | None = None
    fraction: str | None = None
    utc_offset_minutes: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.year <= 9999:
            raise DateEvidenceError("Year must be between 1 and 9999.")
        if self.month is None:
            if any(value is not None for value in (
                self.day, self.hour, self.minute, self.second, self.fraction,
                self.utc_offset_minutes,
            )):
                raise DateEvidenceError("Year precision cannot contain lower components.")
            return
        if not 1 <= self.month <= 12:
            raise DateEvidenceError("Month must be between 1 and 12.")
        if self.day is None:
            if any(value is not None for value in (
                self.hour, self.minute, self.second, self.fraction, self.utc_offset_minutes,
            )):
                raise DateEvidenceError("Year-month precision cannot contain lower components.")
            return
        if not 1 <= self.day <= calendar.monthrange(self.year, self.month)[1]:
            raise DateEvidenceError("Day is not valid for the supplied year and month.")
        if self.hour is None:
            if any(value is not None for value in (
                self.minute, self.second, self.fraction, self.utc_offset_minutes,
            )):
                raise DateEvidenceError("Date precision cannot contain time components.")
            return
        if self.minute is None or not 0 <= self.hour <= 23 or not 0 <= self.minute <= 59:
            raise DateEvidenceError("Datetime requires a valid hour and minute.")
        if self.second is not None and not 0 <= self.second <= 59:
            raise DateEvidenceError("Second must be between 0 and 59.")
        if self.fraction is not None:
            if self.second is None or not re.fullmatch(r"[0-9]{1,9}", self.fraction):
                raise DateEvidenceError("Fraction requires seconds and one to nine digits.")
        if self.utc_offset_minutes is not None and not -840 <= self.utc_offset_minutes <= 840:
            raise DateEvidenceError("UTC offset must be between -14:00 and +14:00.")

    @property
    def precision(self) -> Precision:
        if self.month is None:
            return Precision.YEAR
        if self.day is None:
            return Precision.YEAR_MONTH
        if self.hour is None:
            return Precision.DATE
        return Precision.DATETIME

    @property
    def time_precision(self) -> TimePrecision | None:
        if self.precision != Precision.DATETIME:
            return None
        if self.fraction is not None:
            return TimePrecision.FRACTION
        if self.second is not None:
            return TimePrecision.SECOND
        return TimePrecision.MINUTE

    @property
    def timezone_state(self) -> TimezoneState:
        if self.precision != Precision.DATETIME:
            return TimezoneState.NOT_APPLICABLE
        return (
            TimezoneState.KNOWN_OFFSET
            if self.utc_offset_minutes is not None
            else TimezoneState.UNKNOWN
        )

    def render(self) -> str:
        text = f"{self.year:04d}"
        if self.month is None:
            return text
        text += f"-{self.month:02d}"
        if self.day is None:
            return text
        text += f"-{self.day:02d}"
        if self.hour is None:
            return text
        text += f"T{self.hour:02d}:{self.minute:02d}"
        if self.second is not None:
            text += f":{self.second:02d}"
        if self.fraction is not None:
            text += f".{self.fraction}"
        if self.utc_offset_minutes is not None:
            if self.utc_offset_minutes == 0:
                text += "Z"
            else:
                sign = "+" if self.utc_offset_minutes >= 0 else "-"
                absolute = abs(self.utc_offset_minutes)
                text += f"{sign}{absolute // 60:02d}:{absolute % 60:02d}"
        return text

    def as_components(self, prefix: str = "") -> dict[str, object]:
        return {
            f"{prefix}precision": self.precision.value,
            f"{prefix}time_precision": (
                None if self.time_precision is None else self.time_precision.value
            ),
            f"{prefix}year": self.year,
            f"{prefix}month": self.month,
            f"{prefix}day": self.day,
            f"{prefix}hour": self.hour,
            f"{prefix}minute": self.minute,
            f"{prefix}second": self.second,
            f"{prefix}fraction": self.fraction,
            f"{prefix}timezone_state": self.timezone_state.value,
            f"{prefix}utc_offset_minutes": self.utc_offset_minutes,
        }


_PARTIAL_DATE_RE = re.compile(
    r"^(?P<year>[0-9]{4})(?:-(?P<month>[0-9]{2})(?:-(?P<day>[0-9]{2})"
    r"(?:[T ](?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})"
    r"(?::(?P<second>[0-9]{2})(?:\.(?P<fraction>[0-9]{1,9}))?)?"
    r"(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})?)?)?)?$"
)


def parse_partial_date(value: str) -> PartialDate:
    """Parse a strict locale-independent partial ISO date without inventing components."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise DateEvidenceError("Date value must be non-empty text without outer whitespace.")
    match = _PARTIAL_DATE_RE.fullmatch(value)
    if match is None:
        raise DateEvidenceError("Date must be year, year-month, date, or ISO-like datetime.")
    groups = match.groupdict()
    offset_text = groups["offset"]
    offset: int | None = None
    if offset_text == "Z":
        offset = 0
    elif offset_text:
        sign = 1 if offset_text[0] == "+" else -1
        hours, minutes = map(int, offset_text[1:].split(":"))
        if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
            raise DateEvidenceError("UTC offset is outside the supported range.")
        offset = sign * (hours * 60 + minutes)
    integers = {
        name: None if groups[name] is None else int(groups[name])
        for name in ("month", "day", "hour", "minute", "second")
    }
    return PartialDate(
        year=int(groups["year"]), fraction=groups["fraction"],
        utc_offset_minutes=offset, **integers,
    )


def same_calendar_date(left: PartialDate, right: PartialDate) -> bool:
    return (
        left.day is not None and right.day is not None
        and (left.year, left.month, left.day) == (right.year, right.month, right.day)
    )


def same_instant(left: PartialDate, right: PartialDate) -> bool:
    if not all(value.precision == Precision.DATETIME for value in (left, right)):
        return False
    if left.utc_offset_minutes is None or right.utc_offset_minutes is None:
        return False
    def aware(value: PartialDate) -> datetime:
        microseconds = int(((value.fraction or "0") + "000000")[:6])
        return datetime(
            value.year, value.month or 1, value.day or 1, value.hour or 0,
            value.minute or 0, value.second or 0, microseconds,
            tzinfo=timezone(timedelta(minutes=value.utc_offset_minutes)),
        )
    return aware(left).astimezone(timezone.utc) == aware(right).astimezone(timezone.utc)


def compatible(left: PartialDate, right: PartialDate) -> bool:
    """Return whether all components known by both values agree."""

    if same_instant(left, right) or same_calendar_date(left, right):
        return True
    for component in ("year", "month", "day"):
        left_value, right_value = getattr(left, component), getattr(right, component)
        if left_value is not None and right_value is not None and left_value != right_value:
            return False
    return True


def timezone_adjacent(left: PartialDate, right: PartialDate) -> bool:
    if left.precision != Precision.DATETIME or right.precision != Precision.DATETIME:
        return False
    left_local = datetime(
        left.year, left.month or 1, left.day or 1, left.hour or 0, left.minute or 0,
        left.second or 0,
    )
    right_local = datetime(
        right.year, right.month or 1, right.day or 1, right.hour or 0, right.minute or 0,
        right.second or 0,
    )
    return abs((left_local.date() - right_local.date()).days) == 1 and abs(
        (left_local - right_local).total_seconds()
    ) <= 14 * 3600


@dataclass(frozen=True, slots=True)
class FilenameParseResult:
    status: str
    value: PartialDate | None = None
    parser_id: str | None = None
    parser_version: str | None = None
    reason: str | None = None


FILENAME_PARSER_VERSION = "1"
_FILENAME_PATTERNS = (
    ("filename-img-yyyymmdd-hhmmss", re.compile(r"^IMG_([0-9]{8})_([0-9]{6})$")),
    ("filename-vid-yyyymmdd-hhmmss", re.compile(r"^VID_([0-9]{8})_([0-9]{6})$")),
    ("filename-iso-date-time", re.compile(
        r"^([0-9]{4})-([0-9]{2})-([0-9]{2})_([0-9]{2})-([0-9]{2})-([0-9]{2})$"
    )),
    ("filename-yyyymmdd-hhmmss", re.compile(r"^([0-9]{8})_([0-9]{6})$")),
)


def parse_allowlisted_filename(filename: str) -> FilenameParseResult:
    """Parse an exact allow-listed filename stem; extensions are the only ignored suffix."""

    if not isinstance(filename, str) or not filename:
        return FilenameParseResult("no_match")
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    matches: list[tuple[str, PartialDate]] = []
    invalid = False
    for parser_id, pattern in _FILENAME_PATTERNS:
        match = pattern.fullmatch(stem)
        if match is None:
            continue
        groups = match.groups()
        if len(groups) == 2:
            date_text, time_text = groups
            parts = (
                int(date_text[:4]), int(date_text[4:6]), int(date_text[6:]),
                int(time_text[:2]), int(time_text[2:4]), int(time_text[4:]),
            )
        else:
            parts = tuple(map(int, groups))
        try:
            matches.append((parser_id, PartialDate(*parts)))
        except DateEvidenceError:
            invalid = True
    if not matches:
        return FilenameParseResult(
            "invalid" if invalid else "no_match",
            reason="invalid_candidate" if invalid else None,
        )
    rendered = {value.render() for _, value in matches}
    if len(rendered) != 1:
        return FilenameParseResult("ambiguous", reason="ambiguous_filename")
    parser_id, parsed = matches[0]
    return FilenameParseResult("matched", parsed, parser_id, FILENAME_PARSER_VERSION)


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    content_identity_id: int
    evidence_type: EvidenceType
    raw_value: str
    value: PartialDate
    actor_type: str
    actor_identifier: str
    provenance: str
    physical_instance_id: int | None = None
    source_id: int | None = None
    analysis_run_id: int | None = None
    source_field: str | None = None
    source_locator: str | None = None
    extractor_name: str | None = None
    extractor_version: str | None = None
    owner_action_key: str | None = None
    timezone_name: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceRecordResult:
    date_evidence_id: int
    evidence_key: str
    created: bool


def evidence_key(evidence: EvidenceInput) -> str:
    identity = {
        "normalisation_version": NORMALISATION_VERSION,
        "content_identity_id": evidence.content_identity_id,
        "physical_instance_id": evidence.physical_instance_id,
        "source_id": evidence.source_id,
        "evidence_type": evidence.evidence_type.value,
        "source_field": evidence.source_field,
        "source_locator": evidence.source_locator,
        "raw_value": evidence.raw_value,
        "extractor_name": evidence.extractor_name,
        "extractor_version": evidence.extractor_version,
        "owner_action_key": evidence.owner_action_key,
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "date-evidence-v1:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_evidence(connection: sqlite3.Connection, evidence: EvidenceInput) -> EvidenceRecordResult:
    _require_schema(connection)
    _positive_id(evidence.content_identity_id, "Content identity ID")
    if not isinstance(evidence.raw_value, str):
        raise DateEvidenceError("Raw evidence value must be text.")
    key = evidence_key(evidence)
    existing = connection.execute(
        "SELECT date_evidence_id FROM content_date_evidence WHERE evidence_key = ?", (key,)
    ).fetchone()
    if existing is not None:
        return EvidenceRecordResult(int(existing[0]), key, False)
    values = evidence.value.as_components()
    try:
        cursor = connection.execute(
            """
            INSERT INTO content_date_evidence(
                evidence_key, content_identity_id, physical_instance_id, source_id,
                analysis_run_id, evidence_type, evidence_role, source_field, source_locator,
                raw_value, precision, time_precision, date_year, date_month, date_day,
                time_hour, time_minute, time_second, time_fraction, timezone_state,
                utc_offset_minutes, timezone_name, extractor_name, extractor_version,
                actor_type, actor_identifier, provenance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?)
            """,
            (
                key, evidence.content_identity_id, evidence.physical_instance_id,
                evidence.source_id, evidence.analysis_run_id, evidence.evidence_type.value,
                "owner_correction" if evidence.evidence_type == EvidenceType.OWNER_SET else "observed",
                evidence.source_field, evidence.source_locator, evidence.raw_value,
                values["precision"], values["time_precision"], values["year"],
                values["month"], values["day"], values["hour"], values["minute"],
                values["second"], values["fraction"], values["timezone_state"],
                values["utc_offset_minutes"], evidence.timezone_name,
                evidence.extractor_name, evidence.extractor_version, evidence.actor_type,
                _text(evidence.actor_identifier, "Actor", 200),
                _text(evidence.provenance, "Provenance", 500),
            ),
        )
    except sqlite3.Error as exc:
        raise DateEvidenceError(f"Date evidence could not be recorded: {exc}") from exc
    return EvidenceRecordResult(int(cursor.lastrowid), key, True)


def record_date_evidence(
    *, database_path: str | Path, evidence: EvidenceInput,
    safety_policy: PathSafetyPolicy | None = None,
) -> EvidenceRecordResult:
    """Atomically insert or reuse one immutable evidence row."""

    with _write_connection(database_path, safety_policy) as connection:
        return record_evidence(connection, evidence)


@dataclass(frozen=True, slots=True)
class PolicyResult:
    status: PreferredStatus
    selection_method: SelectionMethod
    selected_evidence_id: int | None
    reason: str
    basis: tuple[tuple[int, BasisRole], ...]


def _row_value(row: sqlite3.Row | Mapping[str, object]) -> PartialDate:
    return PartialDate(
        int(row["date_year"]), row["date_month"], row["date_day"], row["time_hour"],
        row["time_minute"], row["time_second"], row["time_fraction"],
        row["utc_offset_minutes"],
    )


def _tier(evidence_type: str) -> int:
    if evidence_type == EvidenceType.OWNER_SET.value:
        return 1
    if evidence_type in {
        EvidenceType.EXIF_DATETIME_ORIGINAL.value,
        EvidenceType.EMBEDDED_VIDEO_CAPTURE.value,
    }:
        return 2
    if evidence_type in {
        EvidenceType.GOOGLE_PHOTOS_TAKEOUT.value,
        EvidenceType.ONEDRIVE_SOURCE_METADATA.value,
        EvidenceType.SPECIALIST_IMPORT.value,
    }:
        return 3
    if evidence_type == EvidenceType.FILENAME_DERIVED.value:
        return 4
    return 5


def evaluate_policy(evidence_rows: Sequence[sqlite3.Row | Mapping[str, object]]) -> PolicyResult:
    rows = list(evidence_rows)
    if not rows:
        return PolicyResult(
            PreferredStatus.UNKNOWN, SelectionMethod.NO_SELECTION, None, "no_evidence", ()
        )
    non_filesystem = [row for row in rows if _tier(str(row["evidence_type"])) < 5]
    if not non_filesystem:
        return PolicyResult(
            PreferredStatus.UNKNOWN, SelectionMethod.NO_SELECTION, None,
            "weak_evidence_only",
            tuple((int(row["date_evidence_id"]), BasisRole.IGNORED_LOWER_AUTHORITY)
                  for row in rows),
        )
    ordered = sorted(non_filesystem, key=lambda row: (_tier(str(row["evidence_type"])), int(row["date_evidence_id"])))
    strong = [row for row in ordered if _tier(str(row["evidence_type"])) in (2, 3)]
    conflicts: set[int] = set()
    adjacent: set[int] = set()
    for index, left in enumerate(strong):
        for right in strong[index + 1:]:
            left_value, right_value = _row_value(left), _row_value(right)
            if compatible(left_value, right_value):
                continue
            if timezone_adjacent(left_value, right_value):
                if _tier(str(left["evidence_type"])) == _tier(str(right["evidence_type"])):
                    conflicts.update((int(left["date_evidence_id"]), int(right["date_evidence_id"])))
                else:
                    weaker = left if _tier(str(left["evidence_type"])) > _tier(str(right["evidence_type"])) else right
                    adjacent.add(int(weaker["date_evidence_id"]))
            else:
                conflicts.update((int(left["date_evidence_id"]), int(right["date_evidence_id"])))
    if conflicts:
        basis = tuple(
            (int(row["date_evidence_id"]),
             BasisRole.CONFLICTING if int(row["date_evidence_id"]) in conflicts
             else BasisRole.IGNORED_LOWER_AUTHORITY)
            for row in rows
        )
        return PolicyResult(
            PreferredStatus.NEEDS_REVIEW, SelectionMethod.NO_SELECTION, None,
            "strong_conflict", basis,
        )
    best_tier = _tier(str(ordered[0]["evidence_type"]))
    peers = [row for row in ordered if _tier(str(row["evidence_type"])) == best_tier]
    selected = peers[0]
    peer_conflict = any(not compatible(_row_value(selected), _row_value(row)) for row in peers[1:])
    if peer_conflict:
        reason = "ambiguous_filename" if best_tier == 4 else "strong_conflict"
        return PolicyResult(
            PreferredStatus.NEEDS_REVIEW, SelectionMethod.NO_SELECTION, None, reason,
            tuple((int(row["date_evidence_id"]), BasisRole.CONFLICTING) for row in peers),
        )
    selected_id = int(selected["date_evidence_id"])
    selected_value = _row_value(selected)
    basis: list[tuple[int, BasisRole]] = []
    for row in rows:
        row_id = int(row["date_evidence_id"])
        if row_id == selected_id:
            role = BasisRole.SELECTED
        elif row_id in adjacent:
            role = BasisRole.TIMEZONE_ADJACENT
        elif compatible(selected_value, _row_value(row)):
            role = BasisRole.CORROBORATING
        else:
            role = BasisRole.IGNORED_LOWER_AUTHORITY
        basis.append((row_id, role))
    return PolicyResult(
        PreferredStatus.RESOLVED, SelectionMethod.POLICY_SELECTION, selected_id,
        "selected_by_authority", tuple(basis),
    )


def resolve_preferred_date(
    connection: sqlite3.Connection, *, content_identity_id: int,
    analysis_run_id: int, policy_version: str = PREFERRED_DATE_POLICY,
) -> dict[str, object]:
    """Evaluate and atomically project policy state; preserve active owner selection."""

    _require_schema(connection)
    _content_exists(connection, content_identity_id)
    current = connection.execute(
        "SELECT * FROM content_preferred_dates WHERE content_identity_id = ?",
        (content_identity_id,),
    ).fetchone()
    if current is not None and current["selection_method"] == SelectionMethod.OWNER_SELECTION.value:
        return {"changed": False, "owner_override_preserved": True,
                "status": current["status"], "reason": "owner_override"}
    evidence_rows = connection.execute(
        "SELECT * FROM content_date_evidence WHERE content_identity_id = ? ORDER BY date_evidence_id",
        (content_identity_id,),
    ).fetchall()
    result = evaluate_policy(evidence_rows)
    selected = None
    if result.selected_evidence_id is not None:
        selected = next(row for row in evidence_rows
                        if int(row["date_evidence_id"]) == result.selected_evidence_id)
    desired_signature = (
        result.status.value, result.selection_method.value, result.selected_evidence_id,
        PREFERRED_DATE_POLICY_NAME, policy_version,
    )
    current_signature = None if current is None else (
        current["status"], current["selection_method"], current["selected_evidence_id"],
        current["policy_name"], current["policy_version"],
    )
    if current_signature == desired_signature:
        return {"changed": False, "owner_override_preserved": False,
                "status": result.status.value, "reason": result.reason}
    previous = _preferred_snapshot(current)
    selected_values = _selected_values(selected)
    if current is None:
        cursor = connection.execute(
            """
            INSERT INTO content_preferred_dates(
                content_identity_id, status, selection_method, selected_evidence_id,
                selected_precision, selected_time_precision, selected_year, selected_month,
                selected_day, selected_hour, selected_minute, selected_second,
                selected_fraction, selected_timezone_state, selected_utc_offset_minutes,
                policy_name, policy_version, determined_by_analysis_run_id,
                actor_type, actor_identifier, provenance, determined_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      'system', 'preferred-date-policy-v1', 'deterministic-policy',
                      strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (content_identity_id, result.status.value, result.selection_method.value,
             result.selected_evidence_id, *selected_values,
             desired_signature[3], desired_signature[4], analysis_run_id),
        )
        preferred_id = int(cursor.lastrowid)
    else:
        preferred_id = int(current["preferred_date_id"])
        connection.execute(
            """
            UPDATE content_preferred_dates SET
                status=?, selection_method=?, selected_evidence_id=?, selected_precision=?,
                selected_time_precision=?, selected_year=?, selected_month=?, selected_day=?,
                selected_hour=?, selected_minute=?, selected_second=?, selected_fraction=?,
                selected_timezone_state=?, selected_utc_offset_minutes=?, policy_name=?,
                policy_version=?, determined_by_analysis_run_id=?, actor_type='system',
                actor_identifier='preferred-date-policy-v1', provenance='deterministic-policy',
                determined_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE preferred_date_id=?
            """,
            (result.status.value, result.selection_method.value, result.selected_evidence_id,
             *selected_values, desired_signature[3], desired_signature[4],
             analysis_run_id, preferred_id),
        )
    _sync_basis(connection, preferred_id, result.basis)
    new_row = connection.execute(
        "SELECT * FROM content_preferred_dates WHERE preferred_date_id=?", (preferred_id,)
    ).fetchone()
    _append_preferred_event(
        connection, _event_type(result.status), preferred_id, content_identity_id,
        actor_type="system", actor="preferred-date-policy-v1", provenance="deterministic-policy",
        reason=result.reason, previous=previous, current=_preferred_snapshot(new_row),
    )
    return {"changed": True, "owner_override_preserved": False,
            "status": result.status.value, "reason": result.reason,
            "preferred_date_id": preferred_id}


def set_owner_preferred_date(
    *, database_path: str | Path, content_identity_id: int, value: str,
    actor: str, action_id: str, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    """Create/reuse immutable owner evidence and select it as the current projection."""

    parsed = parse_partial_date(value)
    checked_actor = _text(actor, "Actor", 200)
    checked_action = _text(action_id, "Action ID", 200)
    checked_reason = _optional_text(reason, "Reason", 2000)
    checked_provenance = _text(provenance, "Provenance", 500)
    with _write_connection(database_path, safety_policy) as connection:
        _content_exists(connection, content_identity_id)
        record = record_evidence(connection, EvidenceInput(
            content_identity_id=content_identity_id, evidence_type=EvidenceType.OWNER_SET,
            raw_value=value, value=parsed, actor_type="owner",
            actor_identifier=checked_actor, provenance=checked_provenance,
            owner_action_key=checked_action,
        ))
        current = connection.execute(
            "SELECT * FROM content_preferred_dates WHERE content_identity_id=?",
            (content_identity_id,),
        ).fetchone()
        if current is not None and current["selection_method"] == "owner_selection" \
                and int(current["selected_evidence_id"]) == record.date_evidence_id:
            return {"changed": False, "evidence_created": record.created,
                    "date_evidence_id": record.date_evidence_id,
                    "preferred_date_id": int(current["preferred_date_id"]),
                    "value": parsed.render()}
        previous = _preferred_snapshot(current)
        selected_values = _selected_values(connection.execute(
            "SELECT * FROM content_date_evidence WHERE date_evidence_id=?",
            (record.date_evidence_id,),
        ).fetchone())
        if current is None:
            cursor = connection.execute(
                """
                INSERT INTO content_preferred_dates(
                    content_identity_id, status, selection_method, selected_evidence_id,
                    selected_precision, selected_time_precision, selected_year, selected_month,
                    selected_day, selected_hour, selected_minute, selected_second,
                    selected_fraction, selected_timezone_state, selected_utc_offset_minutes,
                    actor_type, actor_identifier, provenance, determined_at, reviewed_at
                ) VALUES (?, 'resolved', 'owner_selection', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'owner', ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (content_identity_id, record.date_evidence_id, *selected_values,
                 checked_actor, checked_provenance),
            )
            preferred_id = int(cursor.lastrowid)
            event_type = "preferred_date_owner_set"
        else:
            preferred_id = int(current["preferred_date_id"])
            connection.execute(
                "UPDATE preferred_date_basis SET basis_state='superseded', "
                "superseded_at=COALESCE(superseded_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
                "WHERE preferred_date_id=? AND basis_state='current'", (preferred_id,),
            )
            connection.execute(
                """
                UPDATE content_preferred_dates SET status='resolved',
                    selection_method='owner_selection', selected_evidence_id=?,
                    selected_precision=?, selected_time_precision=?, selected_year=?,
                    selected_month=?, selected_day=?, selected_hour=?, selected_minute=?,
                    selected_second=?, selected_fraction=?, selected_timezone_state=?,
                    selected_utc_offset_minutes=?, policy_name=NULL, policy_version=NULL,
                    determined_by_analysis_run_id=NULL, actor_type='owner', actor_identifier=?,
                    provenance=?, determined_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE preferred_date_id=?
                """,
                (record.date_evidence_id, *selected_values, checked_actor,
                 checked_provenance, preferred_id),
            )
            event_type = "preferred_date_changed"
        _sync_basis(connection, preferred_id, ((record.date_evidence_id, BasisRole.SELECTED),))
        new_row = connection.execute(
            "SELECT * FROM content_preferred_dates WHERE preferred_date_id=?", (preferred_id,)
        ).fetchone()
        _append_preferred_event(
            connection, event_type, preferred_id, content_identity_id,
            actor_type="owner", actor=checked_actor, provenance=checked_provenance,
            reason=checked_reason, previous=previous, current=_preferred_snapshot(new_row),
        )
        return {"changed": True, "evidence_created": record.created,
                "date_evidence_id": record.date_evidence_id,
                "preferred_date_id": preferred_id, "value": parsed.render()}


def replace_owner_preferred_date(
    *, database_path: str | Path, content_identity_id: int, value: str,
    actor: str, action_id: str, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    """Explicitly replace an existing owner selection with a new owner action."""

    current = get_preferred_date(
        database_path=database_path, content_identity_id=content_identity_id,
        safety_policy=safety_policy,
    )["preferred_date"]
    if current is None or current["selection_method"] != SelectionMethod.OWNER_SELECTION.value:
        raise DateEvidenceError("An active owner preferred date is required for replacement.")
    return set_owner_preferred_date(
        database_path=database_path, content_identity_id=content_identity_id, value=value,
        actor=actor, action_id=action_id, reason=reason, provenance=provenance,
        safety_policy=safety_policy,
    )


def get_preferred_date(
    *, database_path: str | Path, content_identity_id: int,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    with _read_connection(database_path, safety_policy) as connection:
        _content_exists(connection, content_identity_id)
        row = connection.execute(
            "SELECT * FROM content_preferred_dates WHERE content_identity_id=?",
            (content_identity_id,),
        ).fetchone()
        return {"content_identity_id": content_identity_id,
                "preferred_date": None if row is None else dict(row),
                "reason": _current_reason(connection, content_identity_id, row)}


def list_date_evidence(
    *, database_path: str | Path, content_identity_id: int, limit: int = 100,
    offset: int = 0, safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    limit, offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        _content_exists(connection, content_identity_id)
        rows = connection.execute(
            "SELECT * FROM content_date_evidence WHERE content_identity_id=? "
            "ORDER BY date_evidence_id LIMIT ? OFFSET ?",
            (content_identity_id, limit, offset),
        ).fetchall()
        total = int(connection.execute(
            "SELECT COUNT(*) FROM content_date_evidence WHERE content_identity_id=?",
            (content_identity_id,),
        ).fetchone()[0])
        return {"content_identity_id": content_identity_id, "evidence": [dict(r) for r in rows],
                "total_matching": total, "limit": limit, "offset": offset}


def list_preferred_basis(
    *, database_path: str | Path, content_identity_id: int,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    with _read_connection(database_path, safety_policy) as connection:
        _content_exists(connection, content_identity_id)
        rows = connection.execute(
            "SELECT b.*, e.evidence_type, e.raw_value FROM content_preferred_dates p "
            "JOIN preferred_date_basis b ON b.preferred_date_id=p.preferred_date_id "
            "JOIN content_date_evidence e ON e.date_evidence_id=b.date_evidence_id "
            "WHERE p.content_identity_id=? ORDER BY b.preferred_date_basis_id",
            (content_identity_id,),
        ).fetchall()
        return {"content_identity_id": content_identity_id, "basis": [dict(r) for r in rows]}


def preferred_date_counts(
    *, database_path: str | Path, safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    with _read_connection(database_path, safety_policy) as connection:
        rows = connection.execute(
            "SELECT status, selected_year, COUNT(*) AS content_count "
            "FROM content_preferred_dates GROUP BY status, selected_year "
            "ORDER BY status, selected_year"
        ).fetchall()
        no_record = int(connection.execute(
            "SELECT COUNT(*) FROM content_identities ci WHERE NOT EXISTS "
            "(SELECT 1 FROM content_preferred_dates p WHERE p.content_identity_id=ci.content_identity_id)"
        ).fetchone()[0])
        return {"counts": [dict(r) for r in rows], "without_preferred_record": no_record}


def list_preferred_identities(
    *, database_path: str | Path, status: PreferredStatus, limit: int = 50,
    offset: int = 0, safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    limit, offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        if status == PreferredStatus.UNKNOWN:
            rows = connection.execute(
                "SELECT ci.content_identity_id AS identity_id, p.* FROM content_identities ci "
                "LEFT JOIN content_preferred_dates p ON p.content_identity_id=ci.content_identity_id "
                "WHERE p.status='unknown' OR p.preferred_date_id IS NULL "
                "ORDER BY ci.content_identity_id LIMIT ? OFFSET ?", (limit, offset),
            ).fetchall()
            total = int(connection.execute(
                "SELECT COUNT(*) FROM content_identities ci LEFT JOIN content_preferred_dates p "
                "ON p.content_identity_id=ci.content_identity_id "
                "WHERE p.status='unknown' OR p.preferred_date_id IS NULL"
            ).fetchone()[0])
            items = []
            for row in rows:
                item = dict(row)
                item["content_identity_id"] = int(item.pop("identity_id"))
                item["status"] = item["status"] or PreferredStatus.UNKNOWN.value
                item["reason"] = _current_reason(connection, item["content_identity_id"], row)
                items.append(item)
        else:
            rows = connection.execute(
                "SELECT * FROM content_preferred_dates WHERE status=? "
                "ORDER BY content_identity_id LIMIT ? OFFSET ?", (status.value, limit, offset),
            ).fetchall()
            total = int(connection.execute(
                "SELECT COUNT(*) FROM content_preferred_dates WHERE status=?", (status.value,)
            ).fetchone()[0])
            items = []
            for row in rows:
                item = dict(row)
                item["reason"] = _current_reason(
                    connection, int(row["content_identity_id"]), row
                )
                items.append(item)
        return {"status": status.value, "items": items,
                "total_matching": total, "limit": limit, "offset": offset}


def list_owner_overrides(
    *, database_path: str | Path, limit: int = 50, offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    limit, offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        rows = connection.execute(
            "SELECT * FROM content_preferred_dates WHERE selection_method='owner_selection' "
            "ORDER BY content_identity_id LIMIT ? OFFSET ?", (limit, offset),
        ).fetchall()
        total = int(connection.execute(
            "SELECT COUNT(*) FROM content_preferred_dates WHERE selection_method='owner_selection'"
        ).fetchone()[0])
        return {"owner_overrides": [dict(r) for r in rows], "total_matching": total,
                "limit": limit, "offset": offset}


def _selected_values(row: sqlite3.Row | None) -> tuple[object, ...]:
    if row is None:
        return (None,) * 11
    return tuple(row[name] for name in (
        "precision", "time_precision", "date_year", "date_month", "date_day",
        "time_hour", "time_minute", "time_second", "time_fraction", "timezone_state",
        "utc_offset_minutes",
    ))


def _current_reason(
    connection: sqlite3.Connection, content_identity_id: int,
    preferred: sqlite3.Row | Mapping[str, object] | None,
) -> str:
    if preferred is None or preferred["preferred_date_id"] is None:
        return "no_preferred_record"
    if preferred["selection_method"] == SelectionMethod.OWNER_SELECTION.value:
        return "owner_override"
    if preferred["status"] == PreferredStatus.RESOLVED.value:
        return "selected_by_authority"
    types = [str(row[0]) for row in connection.execute(
        "SELECT evidence_type FROM content_date_evidence WHERE content_identity_id=?",
        (content_identity_id,),
    )]
    if preferred["status"] == PreferredStatus.UNKNOWN.value:
        if not types:
            return "no_evidence"
        return "weak_evidence_only" if all(_tier(value) == 5 for value in types) else "unknown"
    conflicting = [str(row[0]) for row in connection.execute(
        "SELECT e.evidence_type FROM preferred_date_basis b "
        "JOIN content_date_evidence e ON e.date_evidence_id=b.date_evidence_id "
        "WHERE b.preferred_date_id=? AND b.basis_state='current' "
        "AND b.basis_role='conflicting'", (preferred["preferred_date_id"],),
    )]
    if conflicting and all(value == EvidenceType.FILENAME_DERIVED.value for value in conflicting):
        return "ambiguous_filename"
    return "strong_conflict"


def _sync_basis(
    connection: sqlite3.Connection, preferred_id: int,
    desired: Sequence[tuple[int, BasisRole]],
) -> None:
    desired_ids = {evidence_id for evidence_id, _ in desired}
    connection.execute(
        "UPDATE preferred_date_basis SET basis_state='superseded', "
        "superseded_at=COALESCE(superseded_at,strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
        "WHERE preferred_date_id=? AND basis_state='current' "
        + ("AND date_evidence_id NOT IN (" + ",".join("?" * len(desired_ids)) + ")"
           if desired_ids else ""),
        (preferred_id, *sorted(desired_ids)),
    )
    for evidence_id, role in desired:
        connection.execute(
            "INSERT INTO preferred_date_basis(preferred_date_id,date_evidence_id,basis_role) "
            "VALUES(?,?,?) ON CONFLICT(preferred_date_id,date_evidence_id) DO UPDATE SET "
            "basis_role=excluded.basis_role,basis_state='current',superseded_at=NULL",
            (preferred_id, evidence_id, role.value),
        )


def _preferred_snapshot(row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    keys = (
        "status", "selection_method", "selected_evidence_id", "selected_precision",
        "selected_time_precision", "selected_year", "selected_month", "selected_day",
        "selected_hour", "selected_minute", "selected_second", "selected_fraction",
        "selected_timezone_state", "selected_utc_offset_minutes", "policy_name",
        "policy_version",
    )
    return {key: row[key] for key in keys}


def _event_type(status: PreferredStatus) -> str:
    return {
        PreferredStatus.RESOLVED: "preferred_date_resolved",
        PreferredStatus.NEEDS_REVIEW: "preferred_date_needs_review",
        PreferredStatus.UNKNOWN: "preferred_date_unknown",
    }[status]


def _append_preferred_event(
    connection: sqlite3.Connection, event_type: str, preferred_id: int,
    content_identity_id: int, *, actor_type: str, actor: str, provenance: str,
    reason: str | None, previous: object, current: object,
) -> None:
    connection.execute(
        "INSERT INTO organisation_events(event_uuid,event_type,preferred_date_id,"
        "content_identity_id,actor_type,actor_identifier,provenance,reason,details_json) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), event_type, preferred_id, content_identity_id, actor_type,
         actor, provenance, reason,
         json.dumps({"previous": previous, "new": current}, ensure_ascii=False, sort_keys=True)),
    )


def _content_exists(connection: sqlite3.Connection, content_identity_id: int) -> None:
    _positive_id(content_identity_id, "Content identity ID")
    if connection.execute(
        "SELECT 1 FROM content_identities WHERE content_identity_id=?", (content_identity_id,)
    ).fetchone() is None:
        raise DateEvidenceError("Content identity does not exist.")


def _positive_id(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DateEvidenceError(f"{label} must be a positive integer.")
    return value


def _text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DateEvidenceError(f"{label} must be non-empty text without NUL bytes.")
    checked = value.strip()
    if len(checked) > maximum:
        raise DateEvidenceError(f"{label} must be at most {maximum} characters.")
    return checked


def _optional_text(value: str | None, label: str, maximum: int) -> str | None:
    return None if value is None else _text(value, label, maximum)


def _page(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
        raise DateEvidenceError(f"Limit must be between 1 and {MAX_PAGE_SIZE}.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise DateEvidenceError("Offset must be a non-negative integer.")
    return limit, offset


def _require_schema(connection: sqlite3.Connection) -> None:
    if read_schema_version(connection) < DATE_SCHEMA_VERSION:
        raise DateEvidenceError("Catalogue schema 10 is required for preferred-date services.")


@contextmanager
def _read_connection(
    database_path: str | Path, safety_policy: PathSafetyPolicy | None,
) -> Iterator[sqlite3.Connection]:
    connection = connect_existing_catalogue(
        database_path, read_only=True, safety_policy=safety_policy
    )
    try:
        _require_schema(connection)
        yield connection
    finally:
        connection.close()


@contextmanager
def _write_connection(
    database_path: str | Path, safety_policy: PathSafetyPolicy | None,
) -> Iterator[sqlite3.Connection]:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=safety_policy
    )
    try:
        _require_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except DateEvidenceError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise DateEvidenceError(f"Preferred-date catalogue write failed: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
