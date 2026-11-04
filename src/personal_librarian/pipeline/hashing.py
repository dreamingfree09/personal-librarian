"""Sequential streaming SHA-256 pipeline with conservative metadata-qualified reuse."""

from __future__ import annotations

import hashlib
import json
import ntpath
import sqlite3
from pathlib import Path

from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.pipeline.checkpoints import (
    PIPELINE_VERSION,
    completed_item,
    finish_job,
    job_outcomes,
    record_item,
    start_or_resume_job,
)
from personal_librarian.pipeline.common import (
    PipelineInterrupted,
    PipelineReport,
    format_mtime_ns,
    get_or_create_source,
    item_key,
    mark_interrupted,
    validate_root,
    windows_absolute_text,
)
from personal_librarian.safety import PathSafetyPolicy
from personal_librarian.safety import PathIntent

HASH_CHUNK_BYTES = 1024 * 1024
SUCCESS_STATES = ("hash_success", "hash_reused", "zero_byte_hashed", "zero_byte_reused")


def _assert_content(
    connection: sqlite3.Connection,
    *,
    physical_instance_id: int,
    run_id: int,
    sha256: str,
) -> int:
    identity_key = f"sha256:{sha256}"
    connection.execute(
        """
        INSERT INTO content_identities(identity_key, created_by_analysis_run_id)
        VALUES (?, ?) ON CONFLICT(identity_key) DO NOTHING
        """,
        (identity_key, run_id),
    )
    row = connection.execute(
        "SELECT content_identity_id FROM content_identities WHERE identity_key = ?",
        (identity_key,),
    ).fetchone()
    assert row is not None
    content_id = int(row[0])
    connection.execute(
        """
        INSERT INTO content_identity_hashes(
            content_identity_id, algorithm, hash_value, analysis_run_id
        ) VALUES (?, 'SHA-256', ?, ?)
        ON CONFLICT(content_identity_id, algorithm, hash_value) DO NOTHING
        """,
        (content_id, sha256, run_id),
    )
    connection.execute(
        "UPDATE physical_instances SET content_identity_id = ? WHERE physical_instance_id = ?",
        (content_id, physical_instance_id),
    )
    connection.execute(
        """
        INSERT INTO hash_observations(
            physical_instance_id, analysis_run_id, algorithm, algorithm_version, hash_value
        ) VALUES (?, ?, 'SHA-256', ?, ?)
        """,
        (physical_instance_id, run_id, PIPELINE_VERSION, sha256),
    )
    return content_id


def _record_hash_observation(
    connection: sqlite3.Connection,
    *,
    physical_instance_id: int,
    run_id: int,
    status: str,
    digest: str | None,
    before: tuple[int, int] | None,
    after: tuple[int, int] | None,
    reused_from: int | None,
    error: str | None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO pipeline_hash_observations(
            physical_instance_id, analysis_run_id, pipeline_version, status, hash_value,
            size_bytes_before, modified_time_ns_before, size_bytes_after,
            modified_time_ns_after, reused_from_hash_observation_id, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            physical_instance_id, run_id, PIPELINE_VERSION, status, digest,
            None if before is None else before[0], None if before is None else before[1],
            None if after is None else after[0], None if after is None else after[1],
            reused_from, error,
        ),
    )
    return int(cursor.lastrowid)


def run_sha256(
    *,
    database_path: str | Path,
    job_id: str,
    inventory_job_id: str,
    source: str,
    root: str | Path,
    max_items: int | None = None,
    safety_policy: PathSafetyPolicy | None = None,
    interrupt_after: int | None = None,
) -> PipelineReport:
    """Hash catalogued inventory items, reusing only exact physical/state matches."""

    if max_items is not None and max_items < 1:
        raise PipelineError("max_items must be positive when supplied.")
    policy = safety_policy or PathSafetyPolicy()
    root_path = validate_root(root, safety_policy=policy)
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        config = {
            "inventory_job_id": inventory_job_id,
            "source": source,
            "root": windows_absolute_text(root_path),
            "max_items": max_items,
            "reuse_policy": "same-physical-instance+size+mtime-ns+prior-verified-sha256-v1",
            "chunk_bytes": HASH_CHUNK_BYTES,
        }
        job = start_or_resume_job(
            connection, job_id=job_id, job_kind="sha256", config=config, algorithm="SHA-256"
        )
        source_id, source_key = get_or_create_source(connection, source)
        inventory = connection.execute(
            "SELECT status, config_json FROM pipeline_jobs WHERE job_id = ? AND job_kind = 'inventory'",
            (inventory_job_id,),
        ).fetchone()
        if inventory is None or str(inventory[0]) != "completed":
            raise PipelineError("Hashing requires the named completed inventory job.")
        inventory_config = json.loads(str(inventory[1]))
        if inventory_config.get("source") != source or inventory_config.get("root") != windows_absolute_text(root_path):
            raise PipelineError("Hash source/root must exactly match the completed inventory job.")
        if job.completed:
            return _report(connection, job_id, "completed")

        items = connection.execute(
            """
            SELECT pji.physical_instance_id, pji.raw_relative_path, pji.absolute_path,
                   pji.extension
            FROM pipeline_job_items AS pji
            JOIN physical_instances AS pi
              ON pi.physical_instance_id = pji.physical_instance_id
            WHERE pji.job_id = ?
              AND pji.outcome IN ('inventory_success', 'zero_byte_inventory')
              AND pi.source_id = ?
            ORDER BY pji.raw_relative_path
            """,
            (inventory_job_id, source_id),
        ).fetchall()
        if max_items is not None:
            items = items[:max_items]
        processed_this_call = 0
        for row in items:
            instance_id = int(row[0])
            relative = str(row[1])
            path = Path(str(row[2]))
            extension = str(row[3] or "")
            key = item_key(source_key, relative)
            path_result = policy.check_path(path, intent=PathIntent.READ)
            if not path_result.allowed:
                raise PipelineError(
                    f"Unsafe catalogued media path ({path_result.code}): {path_result.reason}"
                )
            try:
                within_root = ntpath.commonpath(
                    (windows_absolute_text(root_path), windows_absolute_text(path))
                ).casefold() == windows_absolute_text(root_path).casefold()
            except ValueError:
                within_root = False
            if not within_root:
                raise PipelineError(f"Catalogued path is outside the explicit media root: {path}")
            try:
                before_state = path.stat()
                before = (int(before_state.st_size), int(before_state.st_mtime_ns))
            except FileNotFoundError as exc:
                _record_error(
                    connection, job, key, instance_id, relative, path, extension,
                    "disappeared", exc,
                )
                processed_this_call += 1
                continue
            except PermissionError as exc:
                _record_error(
                    connection, job, key, instance_id, relative, path, extension,
                    "permission_denied", exc,
                )
                processed_this_call += 1
                continue
            except OSError as exc:
                _record_error(
                    connection, job, key, instance_id, relative, path, extension,
                    "unreadable", exc,
                )
                processed_this_call += 1
                continue

            if completed_item(
                connection, job_id, key, size_bytes=before[0], modified_time_ns=before[1]
            ) is not None:
                continue

            cached = connection.execute(
                """
                SELECT pipeline_hash_observation_id, hash_value
                FROM pipeline_hash_observations
                WHERE physical_instance_id = ? AND size_bytes_after = ?
                  AND modified_time_ns_after = ?
                  AND status IN ('hash_success', 'hash_reused', 'zero_byte_hashed', 'zero_byte_reused')
                  AND hash_value IS NOT NULL
                ORDER BY pipeline_hash_observation_id DESC LIMIT 1
                """,
                (instance_id, before[0], before[1]),
            ).fetchone()
            if cached is not None:
                digest = str(cached[1])
                status = "zero_byte_reused" if before[0] == 0 else "hash_reused"
                modified = format_mtime_ns(before[1])
                connection.execute(
                    """
                    UPDATE physical_instances
                    SET size_bytes = ?, observed_modified_at = ?, current_observed_path = ?
                    WHERE physical_instance_id = ?
                    """,
                    (before[0], modified, windows_absolute_text(path), instance_id),
                )
                _assert_content(
                    connection, physical_instance_id=instance_id,
                    run_id=job.analysis_run_id, sha256=digest,
                )
                _record_hash_observation(
                    connection, physical_instance_id=instance_id, run_id=job.analysis_run_id,
                    status=status, digest=digest, before=before, after=before,
                    reused_from=int(cached[0]), error=None,
                )
                record_item(
                    connection, job_id=job_id, item_key=key,
                    physical_instance_id=instance_id, raw_relative_path=relative,
                    absolute_path=windows_absolute_text(path), extension=extension,
                    size_bytes=before[0], modified_time_ns=before[1], outcome=status,
                    sha256=digest, reused_from=int(cached[0]),
                )
                processed_this_call += 1
                _maybe_interrupt(connection, job_id, processed_this_call, interrupt_after)
                continue

            digest_builder = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    while chunk := handle.read(HASH_CHUNK_BYTES):
                        digest_builder.update(chunk)
                after_state = path.stat()
                after = (int(after_state.st_size), int(after_state.st_mtime_ns))
            except FileNotFoundError as exc:
                _record_error(
                    connection, job, key, instance_id, relative, path, extension,
                    "disappeared", exc, before=before,
                )
                processed_this_call += 1
                continue
            except PermissionError as exc:
                _record_error(
                    connection, job, key, instance_id, relative, path, extension,
                    "permission_denied", exc, before=before,
                )
                processed_this_call += 1
                continue
            except OSError as exc:
                _record_error(
                    connection, job, key, instance_id, relative, path, extension,
                    "unreadable", exc, before=before,
                )
                processed_this_call += 1
                continue

            if after != before:
                error = "File size or modified time changed while SHA-256 was being read."
                _record_hash_observation(
                    connection, physical_instance_id=instance_id, run_id=job.analysis_run_id,
                    status="changed_during_hash", digest=None, before=before, after=after,
                    reused_from=None, error=error,
                )
                record_item(
                    connection, job_id=job_id, item_key=key,
                    physical_instance_id=instance_id, raw_relative_path=relative,
                    absolute_path=windows_absolute_text(path), extension=extension,
                    size_bytes=after[0], modified_time_ns=after[1],
                    outcome="changed_during_hash", error=error,
                )
            else:
                digest = digest_builder.hexdigest()
                status = "zero_byte_hashed" if before[0] == 0 else "hash_success"
                modified = format_mtime_ns(after[1])
                connection.execute(
                    """
                    UPDATE physical_instances
                    SET size_bytes = ?, observed_modified_at = ?, current_observed_path = ?
                    WHERE physical_instance_id = ?
                    """,
                    (before[0], modified, windows_absolute_text(path), instance_id),
                )
                _assert_content(
                    connection, physical_instance_id=instance_id,
                    run_id=job.analysis_run_id, sha256=digest,
                )
                _record_hash_observation(
                    connection, physical_instance_id=instance_id, run_id=job.analysis_run_id,
                    status=status, digest=digest, before=before, after=after,
                    reused_from=None, error=None,
                )
                record_item(
                    connection, job_id=job_id, item_key=key,
                    physical_instance_id=instance_id, raw_relative_path=relative,
                    absolute_path=windows_absolute_text(path), extension=extension,
                    size_bytes=before[0], modified_time_ns=before[1], outcome=status,
                    sha256=digest,
                )
            processed_this_call += 1
            _maybe_interrupt(connection, job_id, processed_this_call, interrupt_after)

        finish_job(connection, job)
        return _report(connection, job_id, "completed")
    finally:
        connection.close()


def _record_error(
    connection: sqlite3.Connection,
    job,
    key: str,
    instance_id: int,
    relative: str,
    path: Path,
    extension: str,
    status: str,
    error: OSError,
    *,
    before: tuple[int, int] | None = None,
) -> None:
    _record_hash_observation(
        connection, physical_instance_id=instance_id, run_id=job.analysis_run_id,
        status=status, digest=None, before=before, after=None,
        reused_from=None, error=str(error),
    )
    record_item(
        connection, job_id=job.job_id, item_key=key,
        physical_instance_id=instance_id, raw_relative_path=relative,
        absolute_path=windows_absolute_text(path), extension=extension,
        size_bytes=None if before is None else before[0],
        modified_time_ns=None if before is None else before[1],
        outcome=status, error=str(error),
    )


def _maybe_interrupt(
    connection: sqlite3.Connection,
    job_id: str,
    processed: int,
    interrupt_after: int | None,
) -> None:
    if interrupt_after is not None and processed >= interrupt_after:
        mark_interrupted(connection, job_id)
        raise PipelineInterrupted(f"SHA-256 job {job_id!r} interrupted after checkpoint.")


def _report(connection: sqlite3.Connection, job_id: str, status: str) -> PipelineReport:
    outcomes = job_outcomes(connection, job_id)
    successful = sum(outcomes.get(name, 0) for name in SUCCESS_STATES)
    reused = outcomes.get("hash_reused", 0) + outcomes.get("zero_byte_reused", 0)
    row = connection.execute(
        """
        SELECT COUNT(DISTINCT sha256) FROM pipeline_job_items
        WHERE job_id = ? AND sha256 IS NOT NULL
        """,
        (job_id,),
    ).fetchone()
    return PipelineReport(
        job_id, "sha256", status,
        {
            "hash_successes": successful,
            "hash_reused": reused,
            "hash_errors": sum(outcomes.values()) - successful,
            "distinct_sha256": int(row[0]),
            "outcomes": outcomes,
        },
    )
