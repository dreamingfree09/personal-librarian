"""Deterministic exact-duplicate derivation from a completed M15 SHA-256 job."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.catalogue.importers.common import stable_key
from personal_librarian.pipeline.checkpoints import finish_job, start_or_resume_job
from personal_librarian.pipeline.common import PipelineReport
from personal_librarian.safety import PathSafetyPolicy


def derive_exact_duplicates(
    *,
    database_path: str | Path,
    job_id: str,
    hash_job_id: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> PipelineReport:
    """Create informational exact groups; no recommendation or media action occurs."""

    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        hash_job = connection.execute(
            "SELECT status FROM pipeline_jobs WHERE job_id = ? AND job_kind = 'sha256'",
            (hash_job_id,),
        ).fetchone()
        if hash_job is None or str(hash_job[0]) != "completed":
            raise PipelineError("Exact-duplicate derivation requires a completed SHA-256 job.")
        job = start_or_resume_job(
            connection,
            job_id=job_id,
            job_kind="exact_duplicates",
            config={"hash_job_id": hash_job_id, "effect": "informational_only"},
            algorithm="SHA-256 grouping",
        )
        if not job.completed:
            try:
                connection.execute("BEGIN IMMEDIATE")
                groups = connection.execute(
                    """
                    SELECT pi.content_identity_id, COUNT(*) AS copies,
                           MIN(pi.size_bytes) AS min_size, MAX(pi.size_bytes) AS max_size,
                           GROUP_CONCAT(DISTINCT s.display_name) AS sources
                    FROM pipeline_job_items AS ji
                    JOIN physical_instances AS pi
                      ON pi.physical_instance_id = ji.physical_instance_id
                    JOIN sources AS s ON s.source_id = pi.source_id
                    WHERE ji.job_id = ? AND ji.sha256 IS NOT NULL
                    GROUP BY pi.content_identity_id HAVING COUNT(*) >= 2
                    ORDER BY pi.content_identity_id
                    """,
                    (hash_job_id,),
                ).fetchall()
                for row in groups:
                    content_id = int(row[0])
                    copies = int(row[1])
                    if row[2] is None or int(row[2]) != int(row[3]):
                        raise PipelineError(
                            f"Exact content identity {content_id} has inconsistent instance sizes."
                        )
                    size = int(row[2])
                    source_names = sorted(str(row[4]).split(","))
                    cursor = connection.execute(
                        """
                        INSERT INTO exact_duplicate_groups(
                            group_key, content_identity_id, analysis_run_id, copies,
                            unique_sources, source_pattern, size_bytes, redundant_copies,
                            reclaimable_bytes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            stable_key("m15-exact-group-v1", job_id, content_id), content_id,
                            job.analysis_run_id, copies, len(source_names),
                            " + ".join(source_names), size, copies - 1, (copies - 1) * size,
                        ),
                    )
                    group_id = int(cursor.lastrowid)
                    members = connection.execute(
                        """
                        SELECT pi.physical_instance_id
                        FROM pipeline_job_items AS ji
                        JOIN physical_instances AS pi
                          ON pi.physical_instance_id = ji.physical_instance_id
                        WHERE ji.job_id = ? AND pi.content_identity_id = ? AND ji.sha256 IS NOT NULL
                        ORDER BY pi.physical_instance_id
                        """,
                        (hash_job_id, content_id),
                    ).fetchall()
                    for member in members:
                        connection.execute(
                            """
                            INSERT INTO exact_duplicate_memberships(
                                exact_duplicate_group_id, physical_instance_id, reported_copies
                            ) VALUES (?, ?, ?)
                            """,
                            (group_id, int(member[0]), copies),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finish_job(connection, job)
        return _report(connection, job_id, job.analysis_run_id)
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
