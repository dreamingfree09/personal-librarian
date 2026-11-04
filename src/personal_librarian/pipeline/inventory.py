"""Deterministic, read-only filesystem inventory integrated with the catalogue."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.models import PATH_COMPARISON_KEY_VERSION, windows_path_comparison_key
from personal_librarian.catalogue.importers.common import stable_key
from personal_librarian.pipeline.checkpoints import (
    completed_item,
    finish_job,
    job_outcomes,
    record_item,
    start_or_resume_job,
)
from personal_librarian.pipeline.common import (
    MEDIA_EXTENSIONS,
    MEDIA_EXTENSION_POLICY_VERSION,
    PipelineInterrupted,
    PipelineReport,
    format_mtime_ns,
    get_or_create_batch,
    get_or_create_source,
    item_key,
    mark_interrupted,
    physical_instance_key,
    validate_root,
    windows_absolute_text,
)
from personal_librarian.safety import PathSafetyPolicy


def _sort_key(name: str) -> tuple[str, str]:
    return windows_path_comparison_key(name), name


def _existing_instance(
    connection: sqlite3.Connection,
    source_id: int,
    relative: str,
    absolute_path: str,
) -> int | None:
    rows = connection.execute(
        """
        SELECT physical_instance_id FROM physical_instances
        WHERE source_id = ? AND raw_relative_path = ?
        """,
        (source_id, relative),
    ).fetchall()
    if len(rows) > 1:
        from personal_librarian.catalogue.errors import PipelineError

        raise PipelineError(f"Multiple physical instances exist for source/path {relative!r}.")
    if rows:
        return int(rows[0][0])
    absolute_rows = connection.execute(
        """
        SELECT physical_instance_id FROM physical_instances
        WHERE source_id = ? AND current_observed_path = ?
        """,
        (source_id, absolute_path),
    ).fetchall()
    if len(absolute_rows) > 1:
        from personal_librarian.catalogue.errors import PipelineError

        raise PipelineError(f"Multiple physical instances exist for absolute path {absolute_path!r}.")
    return None if not absolute_rows else int(absolute_rows[0][0])


def run_inventory(
    *,
    database_path: str | Path,
    job_id: str,
    source: str,
    root: str | Path,
    max_media_items: int | None = None,
    safety_policy: PathSafetyPolicy | None = None,
    interrupt_after: int | None = None,
) -> PipelineReport:
    """Inventory supported media deterministically; media content is never opened."""

    if max_media_items is not None and max_media_items < 1:
        from personal_librarian.catalogue.errors import PipelineError

        raise PipelineError("max_media_items must be positive when supplied.")
    policy = safety_policy or PathSafetyPolicy()
    root_path = validate_root(root, safety_policy=policy)
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        config = {
            "source": source,
            "root": windows_absolute_text(root_path),
            "extension_policy": MEDIA_EXTENSION_POLICY_VERSION,
            "max_media_items": max_media_items,
        }
        job = start_or_resume_job(
            connection, job_id=job_id, job_kind="inventory", config=config,
            algorithm="filesystem-metadata",
        )
        source_id, source_key = get_or_create_source(connection, source)
        batch_id = get_or_create_batch(connection, source_id, source_key, job_id)
        connection.commit()
        if job.completed:
            return _report(connection, job_id, "completed")

        processed_this_call = 0
        supported_seen = 0
        stop = False

        def walk_error(error: OSError) -> None:
            nonlocal processed_this_call
            error_path = Path(error.filename) if error.filename else root_path
            try:
                relative = str(error_path.relative_to(root_path))
            except ValueError:
                relative = "<directory-enumeration-error>"
            outcome = "permission_denied" if isinstance(error, PermissionError) else "unreadable"
            record_item(
                connection, job_id=job_id,
                item_key=stable_key("pipeline-walk-error-v1", source_key, relative),
                physical_instance_id=None, raw_relative_path=relative,
                absolute_path=windows_absolute_text(error_path), extension="",
                size_bytes=None, modified_time_ns=None, outcome=outcome, error=str(error),
            )
            processed_this_call += 1

        for directory, directory_names, file_names in os.walk(root_path, onerror=walk_error):
            directory_names.sort(key=_sort_key)
            file_names.sort(key=_sort_key)
            for file_name in file_names:
                path = Path(directory) / file_name
                relative = str(path.relative_to(root_path))
                extension = path.suffix.casefold()
                key = item_key(source_key, relative)
                if extension not in MEDIA_EXTENSIONS:
                    if completed_item(connection, job_id, key, size_bytes=None, modified_time_ns=None) is None:
                        record_item(
                            connection, job_id=job_id, item_key=key,
                            physical_instance_id=None, raw_relative_path=relative,
                            absolute_path=windows_absolute_text(path), extension=extension,
                            size_bytes=None, modified_time_ns=None,
                            outcome="unsupported_extension",
                        )
                        processed_this_call += 1
                    continue
                if max_media_items is not None and supported_seen >= max_media_items:
                    stop = True
                    break
                supported_seen += 1
                try:
                    state = path.stat()
                    size = int(state.st_size)
                    modified_ns = int(state.st_mtime_ns)
                except FileNotFoundError as exc:
                    record_item(
                        connection, job_id=job_id, item_key=key, physical_instance_id=None,
                        raw_relative_path=relative, absolute_path=windows_absolute_text(path),
                        extension=extension, size_bytes=None, modified_time_ns=None,
                        outcome="disappeared", error=str(exc),
                    )
                    processed_this_call += 1
                    continue
                except PermissionError as exc:
                    record_item(
                        connection, job_id=job_id, item_key=key, physical_instance_id=None,
                        raw_relative_path=relative, absolute_path=windows_absolute_text(path),
                        extension=extension, size_bytes=None, modified_time_ns=None,
                        outcome="permission_denied", error=str(exc),
                    )
                    processed_this_call += 1
                    continue
                except OSError as exc:
                    record_item(
                        connection, job_id=job_id, item_key=key, physical_instance_id=None,
                        raw_relative_path=relative, absolute_path=windows_absolute_text(path),
                        extension=extension, size_bytes=None, modified_time_ns=None,
                        outcome="unreadable", error=str(exc),
                    )
                    processed_this_call += 1
                    continue

                if completed_item(
                    connection, job_id, key, size_bytes=size, modified_time_ns=modified_ns
                ) is not None:
                    continue
                instance_id = _existing_instance(
                    connection, source_id, relative, windows_absolute_text(path)
                )
                modified = format_mtime_ns(modified_ns)
                if instance_id is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO physical_instances(
                            instance_key, source_id, acquisition_batch_id, raw_relative_path,
                            display_path, relative_path_comparison_key,
                            path_comparison_key_version, current_observed_path, size_bytes,
                            extension, observed_modified_at, first_observed_analysis_run_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            physical_instance_key(source_key, relative), source_id, batch_id,
                            relative, relative, windows_path_comparison_key(relative),
                            PATH_COMPARISON_KEY_VERSION, windows_absolute_text(path), size,
                            extension, modified, job.analysis_run_id,
                        ),
                    )
                    instance_id = int(cursor.lastrowid)
                else:
                    connection.execute(
                        """
                        UPDATE physical_instances SET acquisition_batch_id = ?, display_path = ?,
                            relative_path_comparison_key = ?, path_comparison_key_version = ?,
                            current_observed_path = ?, size_bytes = ?, extension = ?,
                            observed_modified_at = ?
                        WHERE physical_instance_id = ?
                        """,
                        (
                            batch_id, relative, windows_path_comparison_key(relative),
                            PATH_COMPARISON_KEY_VERSION, windows_absolute_text(path), size,
                            extension, modified, instance_id,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO inventory_observations(
                        observation_key, analysis_run_id, source_id, acquisition_batch_id,
                        row_ordinal, raw_relative_path, relative_path_comparison_key,
                        path_comparison_key_version, extension, size_bytes,
                        observed_modified_at, timestamp_state, matched_physical_instance_id,
                        match_method
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'aware', ?, 'exact_path')
                    ON CONFLICT(observation_key) DO UPDATE SET
                        size_bytes = excluded.size_bytes,
                        observed_modified_at = excluded.observed_modified_at,
                        matched_physical_instance_id = excluded.matched_physical_instance_id
                    """,
                    (
                        stable_key("m15-inventory-observation-v1", job_id, relative),
                        job.analysis_run_id, source_id, batch_id,
                        int(item_key(source_key, relative).rsplit(":", 1)[1][:15], 16) + 1,
                        relative,
                        windows_path_comparison_key(relative), PATH_COMPARISON_KEY_VERSION,
                        extension, size, modified, instance_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO instance_path_observations(
                        observation_key, physical_instance_id, analysis_run_id, evidence_layer,
                        raw_relative_path, absolute_path, relative_path_comparison_key,
                        path_comparison_key_version, observed_modified_at, timestamp_state,
                        is_authoritative_current
                    ) VALUES (?, ?, ?, 'M15-inventory', ?, ?, ?, ?, ?, 'aware', 1)
                    ON CONFLICT(physical_instance_id, analysis_run_id, evidence_layer)
                    DO UPDATE SET absolute_path = excluded.absolute_path,
                        observed_modified_at = excluded.observed_modified_at
                    """,
                    (
                        stable_key("m15-path-observation-v1", job_id, relative), instance_id,
                        job.analysis_run_id, relative, windows_absolute_text(path),
                        windows_path_comparison_key(relative), PATH_COMPARISON_KEY_VERSION,
                        modified,
                    ),
                )
                outcome = "zero_byte_inventory" if size == 0 else "inventory_success"
                record_item(
                    connection, job_id=job_id, item_key=key,
                    physical_instance_id=instance_id, raw_relative_path=relative,
                    absolute_path=windows_absolute_text(path), extension=extension,
                    size_bytes=size, modified_time_ns=modified_ns, outcome=outcome,
                )
                processed_this_call += 1
                if interrupt_after is not None and processed_this_call >= interrupt_after:
                    mark_interrupted(connection, job_id)
                    raise PipelineInterrupted(f"Inventory job {job_id!r} interrupted after checkpoint.")
            if stop:
                break

        finish_job(connection, job)
        return _report(connection, job_id, "completed")
    finally:
        connection.close()


def _report(connection: sqlite3.Connection, job_id: str, status: str) -> PipelineReport:
    outcomes = job_outcomes(connection, job_id)
    row = connection.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(size_bytes), 0)
        FROM pipeline_job_items
        WHERE job_id = ? AND outcome IN ('inventory_success', 'zero_byte_inventory')
        """,
        (job_id,),
    ).fetchone()
    metrics: dict[str, object] = {
        "media_rows": int(row[0]),
        "media_bytes": int(row[1]),
        "extension_policy": MEDIA_EXTENSION_POLICY_VERSION,
        "outcomes": outcomes,
    }
    return PipelineReport(job_id, "inventory", status, metrics)
