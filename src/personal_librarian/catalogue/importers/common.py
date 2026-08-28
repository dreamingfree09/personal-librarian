"""Shared evidence-import validation, identity and reconciliation helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import ntpath
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from personal_librarian.catalogue.errors import (
    CataloguePathError,
    EvidenceValidationError,
    InputFingerprintMismatchError,
    ReconciliationError,
)
from personal_librarian.safety import PathIntent, PathSafetyPolicy


IMPORTER_VERSION = "1"


DEFAULT_BASELINES: dict[str, dict[str, object]] = {
    "m9": {
        "rows": 69_444,
        "bytes": 122_312_861_984,
        "source_counts": {
            "OneDrive": 23_538,
            "GooglePhotos": 4_287,
            "Dropbox": 837,
            "HDD_Disk2": 40_782,
        },
    },
    "m10": {
        "manifest_rows": 69_444,
        "valid_sha256": 69_444,
        "invalid_sha256": 0,
        "physical_instances_mapped": 69_444,
        "exact_duplicate_groups": 7_707,
        "duplicate_memberships": 21_024,
        "redundant_copies": 13_317,
        "reclaimable_bytes": 25_488_473_284,
    },
    "m11": {
        "unique_dualhash_contents": 54_839,
        "phashed_physical_copies": 64_569,
        "dhash_coverage": 54_839,
        "similarity_pairs": 9_403,
        "review_groups": 5_067,
        "unique_group_contents": 11_325,
        "largest_group": 135,
        "groups_over_20": 12,
        "groups_over_50": 1,
    },
}


@dataclass(frozen=True, slots=True)
class StageReport:
    stage: str
    importer_version: str
    metrics: dict[str, object]
    expected: dict[str, object]
    matches: dict[str, bool]
    skipped_existing: bool = False

    @property
    def matches_baseline(self) -> bool:
        return all(self.matches.values())

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "importer_version": self.importer_version,
            "metrics": self.metrics,
            "expected": self.expected,
            "matches": self.matches,
            "matches_baseline": self.matches_baseline,
            "skipped_existing": self.skipped_existing,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object], *, skipped_existing: bool) -> "StageReport":
        return cls(
            stage=str(value["stage"]),
            importer_version=str(value["importer_version"]),
            metrics=dict(value["metrics"]),  # type: ignore[arg-type]
            expected=dict(value["expected"]),  # type: ignore[arg-type]
            matches={key: bool(item) for key, item in dict(value["matches"]).items()},  # type: ignore[arg-type]
            skipped_existing=skipped_existing,
        )


@dataclass(frozen=True, slots=True)
class EvidenceImportReport:
    stages: tuple[StageReport, ...]
    table_counts: dict[str, int]

    @property
    def matches_baselines(self) -> bool:
        return all(stage.matches_baseline for stage in self.stages)

    def as_dict(self) -> dict[str, object]:
        return {
            "matches_baselines": self.matches_baselines,
            "stages": [stage.as_dict() for stage in self.stages],
            "table_counts": self.table_counts,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)

    def format_human(self) -> str:
        lines = ["Evidence reconciliation:"]
        for stage in self.stages:
            status = "MATCH" if stage.matches_baseline else "DIFFER"
            suffix = " (already imported)" if stage.skipped_existing else ""
            lines.append(f"  {stage.stage}: {status}{suffix}")
            for name, value in stage.metrics.items():
                marker = ""
                if name in stage.matches:
                    marker = " MATCH" if stage.matches[name] else " DIFFER"
                lines.append(f"    {name}: {value}{marker}")
        lines.append("Catalogue table counts:")
        for table, count in sorted(self.table_counts.items()):
            lines.append(f"  {table}: {count}")
        return "\n".join(lines)


def build_stage_report(
    stage: str,
    metrics: dict[str, object],
    expected: Mapping[str, object],
) -> StageReport:
    expected_copy = dict(expected)
    matches = {name: metrics.get(name) == value for name, value in expected_copy.items()}
    return StageReport(stage, IMPORTER_VERSION, metrics, expected_copy, matches)


def require_reconciliation(report: StageReport) -> None:
    if not report.matches_baseline:
        differences = ", ".join(name for name, matched in report.matches.items() if not matched)
        raise ReconciliationError(
            f"{report.stage} reconciliation differs for: {differences}",
            report,
        )


def stable_key(namespace: str, *parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        value = "" if part is None else str(part)
        encoded = value.encode("utf-8", errors="strict")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return f"{namespace}:{digest.hexdigest()}"


def validate_input_file(
    path: str | os.PathLike[str],
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> Path:
    policy = safety_policy or PathSafetyPolicy()
    raw = os.fspath(path)
    result = policy.check_path(raw, intent=PathIntent.READ)
    if not result.allowed:
        raise CataloguePathError(f"Unsafe evidence path ({result.code}): {result.reason}")
    candidate = raw.replace("/", "\\")
    drive, tail = ntpath.splitdrive(candidate)
    absolute_drive = len(drive) == 2 and drive[1] == ":" and tail.startswith("\\")
    absolute_unc = candidate.startswith("\\\\") and bool(drive)
    if not (absolute_drive or absolute_unc):
        raise CataloguePathError("Evidence path must be an explicit absolute drive or UNC path.")
    resolved = Path(raw)
    if not resolved.is_file():
        raise EvidenceValidationError(f"Evidence file does not exist: {resolved}")
    return resolved


def fingerprint_files(paths: Mapping[str, Path]) -> dict[str, object]:
    files: dict[str, object] = {}
    for label, path in sorted(paths.items()):
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        files[label] = {
            "path": str(path),
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }
    return {"files": files}


def iter_csv(
    path: Path,
    expected_headers: Sequence[str],
) -> Iterator[tuple[int, dict[str, str]]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise EvidenceValidationError(f"Cannot read CSV '{path}': {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(expected_headers):
            raise EvidenceValidationError(
                f"Unexpected CSV header in '{path}'. Expected {list(expected_headers)}, "
                f"found {reader.fieldnames}."
            )
        try:
            for ordinal, row in enumerate(reader, start=1):
                if None in row or any(value is None for value in row.values()):
                    raise EvidenceValidationError(
                        f"Malformed CSV row {ordinal} in '{path}'."
                    )
                yield ordinal, {key: str(value) for key, value in row.items()}
        except (csv.Error, UnicodeError) as exc:
            raise EvidenceValidationError(f"Invalid CSV data in '{path}': {exc}") from exc


def parse_nonnegative_int(value: str, field: str, ordinal: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise EvidenceValidationError(
            f"Row {ordinal}: {field} must be an integer, found {value!r}."
        ) from exc
    if parsed < 0:
        raise EvidenceValidationError(f"Row {ordinal}: {field} must not be negative.")
    return parsed


def parse_timestamp(value: str, field: str, ordinal: int) -> tuple[str | None, str]:
    if value == "":
        return None, "missing"
    parse_value = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise EvidenceValidationError(
            f"Row {ordinal}: {field} is not a supported ISO-8601 timestamp: {value!r}."
        ) from exc
    state = "aware" if parsed.utcoffset() is not None else "naive"
    return value, state


def validate_sha256(value: str, field: str, ordinal: int) -> str:
    normalised = value.lower()
    if len(normalised) != 64 or any(character not in "0123456789abcdef" for character in normalised):
        raise EvidenceValidationError(f"Row {ordinal}: {field} is not a valid SHA-256 digest.")
    return normalised


@contextmanager
def stage_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    if connection.in_transaction:
        raise EvidenceValidationError("Importer requires a clean connection transaction state.")
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def completed_stage(
    connection: sqlite3.Connection,
    stage_key: str,
    fingerprint: Mapping[str, object],
) -> StageReport | None:
    row = connection.execute(
        """
        SELECT importer_version, input_fingerprint_json, reconciliation_json
        FROM evidence_import_stages WHERE stage_key = ?
        """,
        (stage_key,),
    ).fetchone()
    if row is None:
        return None
    expected_fingerprint = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True)
    if row[0] != IMPORTER_VERSION or row[1] != expected_fingerprint:
        raise InputFingerprintMismatchError(
            f"Completed stage '{stage_key}' has different importer or input fingerprints."
        )
    stored = json.loads(str(row[2]))
    return StageReport.from_dict(stored, skipped_existing=True)


def record_completed_stage(
    connection: sqlite3.Connection,
    *,
    stage_key: str,
    importer_name: str,
    analysis_run_id: int,
    fingerprint: Mapping[str, object],
    report: StageReport,
) -> None:
    connection.execute(
        """
        INSERT INTO evidence_import_stages(
            stage_key, importer_name, importer_version, analysis_run_id,
            input_fingerprint_json, reconciliation_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            stage_key,
            importer_name,
            IMPORTER_VERSION,
            analysis_run_id,
            json.dumps(fingerprint, ensure_ascii=False, sort_keys=True),
            json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True),
        ),
    )


def get_or_create_source(connection: sqlite3.Connection, label: str) -> int:
    known = {
        "OneDrive": "onedrive",
        "GooglePhotos": "google-photos",
        "Dropbox": "dropbox",
        "HDD_Disk2": "hdd-disk2",
    }
    source_key = known.get(label, stable_key("source", label))
    connection.execute(
        """
        INSERT INTO sources(source_key, display_name, source_type)
        VALUES (?, ?, 'evidence') ON CONFLICT(source_key) DO NOTHING
        """,
        (source_key, label),
    )
    row = connection.execute(
        "SELECT source_id, display_name FROM sources WHERE source_key = ?",
        (source_key,),
    ).fetchone()
    if row is None or row[1] != label:
        raise EvidenceValidationError(f"Source key collision for label {label!r}.")
    return int(row[0])


def get_or_create_batch(
    connection: sqlite3.Connection,
    source_id: int,
    stage: str,
) -> int:
    source_row = connection.execute(
        "SELECT source_key FROM sources WHERE source_id = ?", (source_id,)
    ).fetchone()
    if source_row is None:
        raise EvidenceValidationError(f"Unknown source id {source_id} for acquisition batch.")
    batch_key = f"evidence:{stage}:source:{source_row[0]}"
    connection.execute(
        """
        INSERT INTO acquisition_batches(
            source_id, batch_key, acquisition_method, verification_status
        ) VALUES (?, ?, 'verified evidence import', 'verified')
        ON CONFLICT(source_id, batch_key) DO NOTHING
        """,
        (source_id, batch_key),
    )
    row = connection.execute(
        "SELECT batch_id FROM acquisition_batches WHERE source_id = ? AND batch_key = ?",
        (source_id, batch_key),
    ).fetchone()
    assert row is not None
    return int(row[0])


def get_or_create_analysis_run(
    connection: sqlite3.Connection,
    *,
    run_key: str,
    analysis_kind: str,
    algorithm: str | None,
    algorithm_version: str | None,
    parameters: Mapping[str, object],
) -> int:
    parameters_json = json.dumps(parameters, ensure_ascii=False, sort_keys=True)
    connection.execute(
        """
        INSERT INTO analysis_runs(
            run_key, analysis_kind, algorithm, algorithm_version, parameters_json
        ) VALUES (?, ?, ?, ?, ?) ON CONFLICT(run_key) DO NOTHING
        """,
        (run_key, analysis_kind, algorithm, algorithm_version, parameters_json),
    )
    row = connection.execute(
        """
        SELECT analysis_run_id, analysis_kind, algorithm, algorithm_version, parameters_json
        FROM analysis_runs WHERE run_key = ?
        """,
        (run_key,),
    ).fetchone()
    if row is None or tuple(row[1:]) != (
        analysis_kind,
        algorithm,
        algorithm_version,
        parameters_json,
    ):
        raise EvidenceValidationError(f"Analysis run key collision for {run_key!r}.")
    return int(row[0])


def catalogue_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }
