"""Informational exact groups bound to a named completed SHA-256 job."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.catalogue.importers.common import stable_key
from personal_librarian.pipeline.checkpoints import (
    PIPELINE_VERSION, fingerprint_config, finish_job, start_or_resume_job,
)
from personal_librarian.pipeline.common import PipelineReport
from personal_librarian.pipeline.hashing import SUCCESS_STATES
from personal_librarian.safety import PathSafetyPolicy


def _historical_groups(connection: sqlite3.Connection, hash_job_id: str) -> list[tuple]:
    """Read checkpoint/observation evidence, never current instance identity or metadata."""
    job = connection.execute(
        "SELECT analysis_run_id, config_json, config_fingerprint, pipeline_version "
        "FROM pipeline_jobs WHERE job_id=? AND job_kind='sha256' AND status='completed'",
        (hash_job_id,),
    ).fetchone()
    if job is None:
        raise PipelineError("Exact-duplicate derivation requires a completed SHA-256 job.")
    try:
        config = json.loads(job[1])
        fingerprint, canonical = fingerprint_config(config)
        source = config["source"]
        if (fingerprint != job[2] or canonical != job[1] or job[3] != PIPELINE_VERSION
                or not isinstance(source, str) or not source.strip()):
            raise ValueError("invalid job identity")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PipelineError("Hash-job configuration evidence is inconsistent.") from exc

    rows = connection.execute(
        """
        SELECT ji.physical_instance_id, ji.sha256, ji.size_bytes, ji.modified_time_ns,
               ji.outcome, pho.status, pho.hash_value, pho.size_bytes_before,
               pho.size_bytes_after, pho.modified_time_ns_before, pho.modified_time_ns_after,
               ci.content_identity_id, cih.hash_value, ho.hash_value,
               ji.reused_from_hash_observation_id, pho.reused_from_hash_observation_id
        FROM pipeline_job_items ji
        LEFT JOIN pipeline_hash_observations pho
          ON pho.physical_instance_id=ji.physical_instance_id AND pho.analysis_run_id=?
        LEFT JOIN hash_observations ho
          ON ho.physical_instance_id=ji.physical_instance_id AND ho.analysis_run_id=?
             AND ho.algorithm='SHA-256'
        LEFT JOIN content_identities ci ON ci.identity_key='sha256:' || ji.sha256
        LEFT JOIN content_identity_hashes cih
          ON cih.content_identity_id=ci.content_identity_id AND cih.algorithm='SHA-256'
        WHERE ji.job_id=? ORDER BY ji.item_key
        """, (job[0], job[0], hash_job_id),
    ).fetchall()
    grouped: dict[int, tuple[int, list[int]]] = {}
    seen: set[int] = set()
    for row in rows:
        if row[4] not in SUCCESS_STATES:
            if row[1] is not None:
                raise PipelineError("Failed hash checkpoint contains a digest.")
            continue
        if (row[0] is None or row[0] in seen or row[1] is None or row[2] is None
                or row[3] is None or row[11] is None
                or row[4] != row[5] or row[1] != row[6] or row[1] != row[12]
                or row[1] != row[13] or row[2] != row[7] or row[2] != row[8]
                or row[3] != row[9] or row[3] != row[10] or row[14] != row[15]):
            raise PipelineError("Hash-job checkpoint lacks consistent historical hash evidence.")
        seen.add(int(row[0]))
        content_id, size = int(row[11]), int(row[2])
        prior_size, members = grouped.setdefault(content_id, (size, []))
        if prior_size != size:
            raise PipelineError("Historical exact content has inconsistent checkpoint sizes.")
        members.append(int(row[0]))
    # A missing successful checkpoint must not silently shrink historical membership.
    observation_ids = {
        int(r[0]) for r in connection.execute(
            "SELECT physical_instance_id FROM pipeline_hash_observations WHERE analysis_run_id=? "
            "AND status IN ('hash_success','hash_reused','zero_byte_hashed','zero_byte_reused')",
            (job[0],),
        )
    }
    if seen != observation_ids:
        raise PipelineError("Historical hash checkpoint membership is incomplete.")
    return [(content, size, source, tuple(sorted(members)))
            for content, (size, members) in sorted(grouped.items()) if len(members) >= 2]


def _published(connection: sqlite3.Connection, run_id: int) -> list[tuple]:
    groups = connection.execute(
        "SELECT exact_duplicate_group_id, group_key, content_identity_id, copies, "
        "unique_sources, source_pattern, size_bytes, redundant_copies, reclaimable_bytes "
        "FROM exact_duplicate_groups WHERE analysis_run_id=? ORDER BY content_identity_id",
        (run_id,),
    ).fetchall()
    result = []
    for row in groups:
        members = tuple(tuple(m) for m in connection.execute(
            "SELECT physical_instance_id, reported_copies FROM exact_duplicate_memberships "
            "WHERE exact_duplicate_group_id=? ORDER BY physical_instance_id", (row[0],),
        ))
        result.append((*tuple(row[1:]), members))
    return result


def derive_exact_duplicates(
    *, database_path: str | Path, job_id: str, hash_job_id: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> PipelineReport:
    """Publish complete groups and completion atomically; reconcile legacy committed output."""
    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        # Preserve the original completed-source requirement even on completed retries.
        if connection.execute(
            "SELECT 1 FROM pipeline_jobs WHERE job_id=? AND job_kind='sha256' AND status='completed'",
            (hash_job_id,),
        ).fetchone() is None:
            raise PipelineError("Exact-duplicate derivation requires a completed SHA-256 job.")
        job = start_or_resume_job(
            connection, job_id=job_id, job_kind="exact_duplicates",
            config={"hash_job_id": hash_job_id, "effect": "informational_only"},
            algorithm="SHA-256 grouping",
        )
        connection.execute("BEGIN IMMEDIATE")
        groups = _historical_groups(connection, hash_job_id)
        expected = []
        for content, size, source, members in groups:
            copies = len(members)
            expected.append((stable_key("m15-exact-group-v1", job_id, content), content,
                             copies, 1, source, size, copies - 1, (copies - 1) * size,
                             tuple((m, copies) for m in members)))
        existing = _published(connection, job.analysis_run_id)
        completed = connection.execute(
            "SELECT status FROM pipeline_jobs WHERE job_id=?", (job_id,),
        ).fetchone()[0] == "completed"
        if existing or completed:
            if existing != expected:
                raise PipelineError(
                    "Published exact-duplicate evidence differs from its hash job; "
                    "retained unchanged for offline review."
                )
        else:
            for group in expected:
                cursor = connection.execute(
                    "INSERT INTO exact_duplicate_groups(group_key, content_identity_id, "
                    "copies, unique_sources, source_pattern, size_bytes, redundant_copies, "
                    "reclaimable_bytes, analysis_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*group[:-1], job.analysis_run_id),
                )
                connection.executemany(
                    "INSERT INTO exact_duplicate_memberships "
                    "(exact_duplicate_group_id, physical_instance_id, reported_copies) VALUES (?, ?, ?)",
                    [(cursor.lastrowid, member, copies) for member, copies in group[-1]],
                )
        if not completed:
            # finish_job commits the caller's pending groups and both completion markers.
            # There must be no earlier publication commit here.
            finish_job(connection, job)
        else:
            connection.rollback()  # read-only completed replay
        return _report(connection, job_id, job.analysis_run_id)
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _report(connection: sqlite3.Connection, job_id: str, run_id: int) -> PipelineReport:
    row = connection.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(copies), 0), COALESCE(SUM(redundant_copies), 0),
               COALESCE(SUM(reclaimable_bytes), 0)
        FROM exact_duplicate_groups WHERE analysis_run_id = ?
        """,
        (run_id,),
    ).fetchone()
    return PipelineReport(
        job_id, "exact_duplicates", "completed",
        {
            "exact_duplicate_groups": int(row[0]),
            "duplicate_memberships": int(row[1]),
            "redundant_copies": int(row[2]),
            "reclaimable_bytes": int(row[3]),
        },
    )
