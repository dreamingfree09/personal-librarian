"""Persistent job identity and per-item checkpoint support."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Mapping

from personal_librarian.catalogue.errors import PipelineError

PIPELINE_VERSION = "m15-v1"
SIMILARITY_PIPELINE_VERSION = "m16-v1"


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    analysis_run_id: int
    completed: bool


def fingerprint_config(config: Mapping[str, object]) -> tuple[str, str]:
    config_json = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
    return fingerprint, config_json


def start_or_resume_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    job_kind: str,
    config: Mapping[str, object],
    algorithm: str | None,
) -> Job:
    if not job_id or job_id.isspace():
        raise PipelineError("Job ID must be explicit and non-empty.")
    fingerprint, config_json = fingerprint_config(config)
    row = connection.execute(
        """
        SELECT job_kind, pipeline_version, config_fingerprint, config_json,
               analysis_run_id, status
        FROM pipeline_jobs WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    if row is not None:
        if tuple(row[:4]) != (job_kind, PIPELINE_VERSION, fingerprint, config_json):
            raise PipelineError(
                f"Job ID {job_id!r} already exists with different pipeline configuration."
            )
        return Job(job_id, int(row[4]), str(row[5]) == "completed")

    parameters_json = json.dumps(config, ensure_ascii=False, sort_keys=True)
    cursor = connection.execute(
        """
        INSERT INTO analysis_runs(
            run_key, analysis_kind, algorithm, algorithm_version, parameters_json,
            started_at
        ) VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        """,
        (f"pipeline:{job_kind}:{job_id}", job_kind, algorithm, PIPELINE_VERSION, parameters_json),
    )
    run_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO pipeline_jobs(
            job_id, job_kind, pipeline_version, config_fingerprint, config_json,
            analysis_run_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_id, job_kind, PIPELINE_VERSION, fingerprint, config_json, run_id),
    )
    connection.commit()
    return Job(job_id, run_id, False)


def completed_item(
    connection: sqlite3.Connection,
    job_id: str,
    item_key: str,
    *,
    size_bytes: int | None,
    modified_time_ns: int | None,
) -> sqlite3.Row | None:
    row = connection.execute(
        """
        SELECT * FROM pipeline_job_items WHERE job_id = ? AND item_key = ?
        """,
        (job_id, item_key),
    ).fetchone()
    if row is None:
        return None
    if row["size_bytes"] == size_bytes and row["modified_time_ns"] == modified_time_ns:
        return row
    return None


def record_item(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    item_key: str,
    physical_instance_id: int | None,
    raw_relative_path: str,
    absolute_path: str,
    extension: str,
    size_bytes: int | None,
    modified_time_ns: int | None,
    outcome: str,
    error: str | None = None,
    sha256: str | None = None,
    reused_from: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO pipeline_job_items(
            job_id, item_key, physical_instance_id, raw_relative_path, absolute_path,
            extension, size_bytes, modified_time_ns, outcome, error, sha256,
            reused_from_hash_observation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, item_key) DO UPDATE SET
            physical_instance_id = excluded.physical_instance_id,
            raw_relative_path = excluded.raw_relative_path,
            absolute_path = excluded.absolute_path,
            extension = excluded.extension,
            size_bytes = excluded.size_bytes,
            modified_time_ns = excluded.modified_time_ns,
            outcome = excluded.outcome,
            error = excluded.error,
            sha256 = excluded.sha256,
            reused_from_hash_observation_id = excluded.reused_from_hash_observation_id,
            completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            job_id, item_key, physical_instance_id, raw_relative_path, absolute_path,
            extension, size_bytes, modified_time_ns, outcome, error, sha256, reused_from,
        ),
    )
    connection.execute(
        "UPDATE pipeline_jobs SET status = 'running', updated_at = "
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?",
        (job_id,),
    )
    connection.commit()


def finish_job(connection: sqlite3.Connection, job: Job) -> None:
    connection.execute(
        """
        UPDATE pipeline_jobs
        SET status = 'completed', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE job_id = ?
        """,
        (job.job_id,),
    )
    connection.execute(
        """
        UPDATE analysis_runs
        SET completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE analysis_run_id = ?
        """,
        (job.analysis_run_id,),
    )
    connection.commit()


def job_outcomes(connection: sqlite3.Connection, job_id: str) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT outcome, COUNT(*) FROM pipeline_job_items "
            "WHERE job_id = ? GROUP BY outcome ORDER BY outcome",
            (job_id,),
        )
    }


def start_or_resume_similarity_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    job_kind: str,
    config: Mapping[str, object],
    algorithm: str,
    algorithm_version: str,
) -> Job:
    """Create or validate a persistent M16 stage identity."""

    if not job_id or job_id.isspace():
        raise PipelineError("Job ID must be explicit and non-empty.")
    fingerprint, config_json = fingerprint_config(config)
    row = connection.execute(
        """
        SELECT job_kind, pipeline_version, config_fingerprint, config_json,
               analysis_run_id, status
        FROM similarity_pipeline_jobs WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    if row is not None:
        if tuple(row[:4]) != (
            job_kind,
            SIMILARITY_PIPELINE_VERSION,
            fingerprint,
            config_json,
        ):
            raise PipelineError(
                f"Similarity job ID {job_id!r} already exists with different configuration."
            )
        return Job(job_id, int(row[4]), str(row[5]) == "completed")

    cursor = connection.execute(
        """
        INSERT INTO analysis_runs(
            run_key, analysis_kind, algorithm, algorithm_version, parameters_json,
            started_at
        ) VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        """,
        (
            f"similarity:{job_kind}:{job_id}",
            job_kind,
            algorithm,
            algorithm_version,
            json.dumps(config, ensure_ascii=False, sort_keys=True),
        ),
    )
    run_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO similarity_pipeline_jobs(
            job_id, job_kind, pipeline_version, config_fingerprint, config_json,
            analysis_run_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            job_kind,
            SIMILARITY_PIPELINE_VERSION,
            fingerprint,
            config_json,
            run_id,
        ),
    )
    connection.commit()
    return Job(job_id, run_id, False)


def similarity_item_exists(
    connection: sqlite3.Connection,
    job_id: str,
    item_key: str,
) -> bool:
    return connection.execute(
        "SELECT 1 FROM similarity_pipeline_items WHERE job_id = ? AND item_key = ?",
        (job_id, item_key),
    ).fetchone() is not None


def record_similarity_item(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    item_key: str,
    outcome: str,
    content_identity_id: int | None = None,
    physical_instance_id: int | None = None,
    payload: Mapping[str, object] | None = None,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO similarity_pipeline_items(
            job_id, item_key, content_identity_id, physical_instance_id,
            outcome, payload_json, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, item_key) DO NOTHING
        """,
        (
            job_id,
            item_key,
            content_identity_id,
            physical_instance_id,
            outcome,
            None if payload is None else json.dumps(payload, ensure_ascii=False, sort_keys=True),
            error,
        ),
    )
    connection.execute(
        "UPDATE similarity_pipeline_jobs SET status = 'running', updated_at = "
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?",
        (job_id,),
    )
    connection.commit()


def finish_similarity_job(connection: sqlite3.Connection, job: Job) -> None:
    connection.execute(
        """
        UPDATE similarity_pipeline_jobs
        SET status = 'completed', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE job_id = ?
        """,
        (job.job_id,),
    )
    connection.execute(
        "UPDATE analysis_runs SET completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE analysis_run_id = ?",
        (job.analysis_run_id,),
    )
    connection.commit()


def mark_similarity_interrupted(connection: sqlite3.Connection, job_id: str) -> None:
    connection.execute(
        "UPDATE similarity_pipeline_jobs SET status = 'interrupted', updated_at = "
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?",
        (job_id,),
    )
    connection.commit()


def similarity_outcomes(connection: sqlite3.Connection, job_id: str) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT outcome, COUNT(*) FROM similarity_pipeline_items "
            "WHERE job_id = ? GROUP BY outcome ORDER BY outcome",
            (job_id,),
        )
    }
