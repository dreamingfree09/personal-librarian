"""Deterministic dual-hash candidate search and review-only relationships."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.catalogue.importers.common import stable_key
from personal_librarian.pipeline.checkpoints import (
    finish_similarity_job,
    mark_similarity_interrupted,
    record_similarity_item,
    similarity_item_exists,
    start_or_resume_similarity_job,
)
from personal_librarian.pipeline.common import PipelineInterrupted, PipelineReport
from personal_librarian.pipeline.perceptual_hashing import hamming_distance
from personal_librarian.safety import PathSafetyPolicy

DUAL_HASH_RULE_VERSION = "m16-phash4-dhash4-v1"
MAX_PHASH_DISTANCE = 4
MAX_DHASH_DISTANCE = 4


def dual_hash_accepts(
    phash_left: str,
    phash_right: str,
    dhash_left: str,
    dhash_right: str,
) -> tuple[bool, int, int]:
    phash_distance = hamming_distance(phash_left, phash_right)
    dhash_distance = hamming_distance(dhash_left, dhash_right)
    return (
        phash_distance <= MAX_PHASH_DISTANCE
        and dhash_distance <= MAX_DHASH_DISTANCE,
        phash_distance,
        dhash_distance,
    )


@dataclass(slots=True)
class _BKNode:
    value: int
    item_indexes: list[int] = field(default_factory=list)
    children: dict[int, "_BKNode"] = field(default_factory=dict)


class HammingBKTree:
    """Small deterministic BK-tree for 64-bit Hamming distance."""

    def __init__(self) -> None:
        self.root: _BKNode | None = None

    def add(self, value: int, item_index: int) -> None:
        if self.root is None:
            self.root = _BKNode(value, [item_index])
            return
        node = self.root
        while True:
            distance = (value ^ node.value).bit_count()
            if distance == 0:
                node.item_indexes.append(item_index)
                return
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = _BKNode(value, [item_index])
                return
            node = child

    def search(self, value: int, maximum_distance: int) -> list[int]:
        if self.root is None:
            return []
        found: list[int] = []
        pending = [self.root]
        while pending:
            node = pending.pop()
            distance = (value ^ node.value).bit_count()
            if distance <= maximum_distance:
                found.extend(node.item_indexes)
            lower = distance - maximum_distance
            upper = distance + maximum_distance
            for edge in sorted(node.children, reverse=True):
                if lower <= edge <= upper:
                    pending.append(node.children[edge])
        return sorted(found)


def run_similarity_analysis(
    *,
    database_path: str | Path,
    job_id: str,
    hash_job_id: str,
    limit: int | None = None,
    rule_version: str = DUAL_HASH_RULE_VERSION,
    safety_policy: PathSafetyPolicy | None = None,
    interrupt_after: int | None = None,
) -> PipelineReport:
    """Generate pHash<=4 AND dHash<=4 review relationships using a BK-tree."""

    if limit is not None and limit < 2:
        raise PipelineError("Similarity analysis limit must be at least 2.")
    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        hash_job = connection.execute(
            """
            SELECT status, analysis_run_id, config_json
            FROM similarity_pipeline_jobs
            WHERE job_id = ? AND job_kind = 'perceptual_hash'
            """,
            (hash_job_id,),
        ).fetchone()
        if hash_job is None or str(hash_job[0]) != "completed":
            raise PipelineError("Similarity analysis requires a completed perceptual-hash job.")
        hash_config = json.loads(str(hash_job[2]))
        config = {
            "hash_job_id": hash_job_id,
            "hash_suite_version": hash_config["hash_suite_version"],
            "rule_version": rule_version,
            "phash_max_distance": MAX_PHASH_DISTANCE,
            "dhash_max_distance": MAX_DHASH_DISTANCE,
            "index": "deterministic-hamming-bk-tree-v1",
            "limit": limit,
            "effect": "review_only",
        }
        job = start_or_resume_similarity_job(
            connection,
            job_id=job_id,
            job_kind="similarity_analysis",
            config=config,
            algorithm="pHash+dHash Hamming candidate rule",
            algorithm_version=rule_version,
        )
        records = _hash_records(connection, int(hash_job[1]))
        if limit is not None:
            records = records[:limit]
        if not job.completed:
            tree = HammingBKTree()
            accepted_this_call = 0
            for index, record in enumerate(records):
                phash_int = int(record[2], 16)
                for other_index in tree.search(phash_int, MAX_PHASH_DISTANCE):
                    other = records[other_index]
                    accepted, phash_distance, dhash_distance = dual_hash_accepts(
                        str(other[2]), str(record[2]), str(other[3]), str(record[3])
                    )
                    if not accepted:
                        continue
                    left, right = sorted((int(other[0]), int(record[0])))
                    identity_keys = sorted((str(other[1]), str(record[1])))
                    item_key = stable_key(
                        "m16-similarity-item-v1", rule_version, *identity_keys
                    )
                    if similarity_item_exists(connection, job_id, item_key):
                        continue
                    relationship_key = stable_key(
                        "m16-similarity-relationship-v1",
                        job_id,
                        rule_version,
                        *identity_keys,
                    )
                    cursor = connection.execute(
                        """
                        INSERT INTO similarity_relationships(
                            relationship_key, left_content_identity_id,
                            right_content_identity_id, analysis_run_id,
                            relationship_type, phash_distance, dhash_distance, review_tier
                        ) VALUES (?, ?, ?, ?, 'dual_hash_review', ?, ?, 'review_only')
                        """,
                        (
                            relationship_key,
                            left,
                            right,
                            job.analysis_run_id,
                            phash_distance,
                            dhash_distance,
                        ),
                    )
                    relationship_id = int(cursor.lastrowid)
                    record_similarity_item(
                        connection,
                        job_id=job_id,
                        item_key=item_key,
                        outcome="relationship",
                        payload={
                            "relationship_id": relationship_id,
                            "left_content_identity_id": left,
                            "right_content_identity_id": right,
                            "phash_distance": phash_distance,
                            "dhash_distance": dhash_distance,
                            "rule_version": rule_version,
                        },
                    )
                    accepted_this_call += 1
                    if interrupt_after is not None and accepted_this_call >= interrupt_after:
                        mark_similarity_interrupted(connection, job_id)
                        raise PipelineInterrupted(
                            f"Similarity job {job_id!r} interrupted after relationship checkpoint."
                        )
                tree.add(phash_int, index)
            finish_similarity_job(connection, job)
        return _analysis_report(
            connection, job_id, job.analysis_run_id, len(records), rule_version
        )
    finally:
        connection.close()


def _hash_records(connection: sqlite3.Connection, run_id: int) -> list[tuple[int, str, str, str]]:
    rows = connection.execute(
        """
        SELECT ci.content_identity_id, ci.identity_key,
               MAX(CASE WHEN cho.algorithm = 'pHash' THEN cho.hash_value END) AS phash,
               MAX(CASE WHEN cho.algorithm = 'dHash' THEN cho.hash_value END) AS dhash
        FROM content_hash_observations AS cho
        JOIN content_identities AS ci
          ON ci.content_identity_id = cho.content_identity_id
        WHERE cho.analysis_run_id = ? AND cho.status IN ('success', 'reused')
        GROUP BY ci.content_identity_id, ci.identity_key
        HAVING phash IS NOT NULL AND dhash IS NOT NULL
        ORDER BY ci.identity_key
        """,
        (run_id,),
    ).fetchall()
    return [(int(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in rows]


def _analysis_report(
    connection: sqlite3.Connection,
    job_id: str,
    run_id: int,
    candidate_count: int,
    rule_version: str,
) -> PipelineReport:
    accepted = int(connection.execute(
        "SELECT COUNT(*) FROM similarity_relationships WHERE analysis_run_id = ?",
        (run_id,),
    ).fetchone()[0])
    return PipelineReport(
        job_id,
        "similarity_analysis",
        "completed",
        {
            "candidate_content_identities": candidate_count,
            "accepted_dual_hash_pairs": accepted,
            "phash_max_distance": MAX_PHASH_DISTANCE,
            "dhash_max_distance": MAX_DHASH_DISTANCE,
            "rule_version": rule_version,
        },
    )
