"""Shared M15 pipeline policy, reporting, and catalogue helpers."""

from __future__ import annotations

import json
import ntpath
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.catalogue.importers.common import stable_key
from personal_librarian.safety import PathIntent, PathSafetyPolicy

MEDIA_EXTENSION_POLICY_VERSION = "m9-media-extensions-v1"
MEDIA_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mpg", ".mkv", ".avi", ".3gp"}
)


def format_mtime_ns(value: int) -> str:
    """Encode observed epoch nanoseconds as UTC without a float/microsecond round trip."""
    seconds, fraction = divmod(value, 1_000_000_000)
    instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return instant.strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction:09d}+00:00"


@dataclass(frozen=True, slots=True)
class PipelineReport:
    job_id: str
    job_kind: str
    status: str
    metrics: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_kind": self.job_kind,
            "status": self.status,
            "metrics": self.metrics,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)

    def format_human(self) -> str:
        lines = [f"job_id: {self.job_id}", f"job_kind: {self.job_kind}", f"status: {self.status}"]
        lines.extend(f"{name}: {value}" for name, value in self.metrics.items())
        return "\n".join(lines)


class PipelineInterrupted(PipelineError):
    """Testable interruption signal after committed per-item checkpoints."""


def validate_root(
    root: str | os.PathLike[str],
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> Path:
    policy = safety_policy or PathSafetyPolicy()
    result = policy.check_path(root, intent=PathIntent.READ)
    if not result.allowed:
        raise PipelineError(f"Unsafe media root ({result.code}): {result.reason}")
    raw = os.fspath(root)
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if not candidate.is_dir():
        raise PipelineError(f"Media root is not an accessible directory: {candidate}")
    return candidate


def get_or_create_source(connection, label: str) -> tuple[int, str]:
    if not label or label.isspace():
        raise PipelineError("Source label must be explicit and non-empty.")
    known = {
        "OneDrive": "onedrive",
        "GooglePhotos": "google-photos",
        "Dropbox": "dropbox",
        "HDD_Disk2": "hdd-disk2",
    }
    source_key = known.get(label, stable_key("pipeline-source-v1", label))
    connection.execute(
        """
        INSERT INTO sources(source_key, display_name, source_type)
        VALUES (?, ?, 'filesystem') ON CONFLICT(source_key) DO NOTHING
        """,
        (source_key, label),
    )
    row = connection.execute(
        "SELECT source_id, display_name FROM sources WHERE source_key = ?", (source_key,)
    ).fetchone()
    if row is None or str(row[1]) != label:
        raise PipelineError(f"Source key collision for {label!r}.")
    return int(row[0]), source_key


def get_or_create_batch(connection, source_id: int, source_key: str, job_id: str) -> int:
    batch_key = f"pipeline:m15:{job_id}:source:{source_key}"
    connection.execute(
        """
        INSERT INTO acquisition_batches(
            source_id, batch_key, acquisition_method, verification_status
        ) VALUES (?, ?, 'read-only filesystem observation', 'verified')
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


def item_key(source_key: str, raw_relative_path: str) -> str:
    return stable_key("pipeline-item-v1", source_key, raw_relative_path)


def physical_instance_key(source_key: str, raw_relative_path: str) -> str:
    return stable_key("physical-instance-v2", source_key, raw_relative_path)


def windows_absolute_text(path: Path) -> str:
    return ntpath.normpath(str(path))


def mark_interrupted(connection, job_id: str) -> None:
    connection.execute(
        "UPDATE pipeline_jobs SET status = 'interrupted', updated_at = "
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?",
        (job_id,),
    )
    connection.commit()
