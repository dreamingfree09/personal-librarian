"""Deterministic connected-component review grouping for M16 relationships."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
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
from personal_librarian.safety import PathSafetyPolicy

GROUP_VERSION = "m16-connected-components-v1"


def review_tier(group_size: int) -> str:
    if group_size > 50:
        return "very_large_low_confidence_review_only"
    if group_size > 20:
        return "large_low_confidence_review_only"
    return "review_only"


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, value: int) -> int:
        self.parent.setdefault(value, value)
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        lower, upper = sorted((left_root, right_root))
        self.parent[upper] = lower


def connected_components(edges: list[tuple[int, int]]) -> list[tuple[int, ...]]:
    union = _UnionFind()
    for left, right in sorted(edges):
        union.union(left, right)
    groups: dict[int, list[int]] = defaultdict(list)
    for value in sorted(union.parent):
        groups[union.find(value)].append(value)
    return sorted((tuple(values) for values in groups.values()), key=lambda values: values)


def run_similarity_groups(
    *,
    database_path: str | Path,
    job_id: str,
    analysis_job_id: str,
    safety_policy: PathSafetyPolicy | None = None,
    interrupt_after: int | None = None,
) -> PipelineReport:
    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        analysis_job = connection.execute(
            """
            SELECT status, analysis_run_id, config_json
            FROM similarity_pipeline_jobs
            WHERE job_id = ? AND job_kind = 'similarity_analysis'
            """,
            (analysis_job_id,),
        ).fetchone()
        if analysis_job is None or str(analysis_job[0]) != "completed":
            raise PipelineError("Grouping requires a completed similarity-analysis job.")
        analysis_config = json.loads(str(analysis_job[2]))
        config = {
            "analysis_job_id": analysis_job_id,
            "rule_version": analysis_config["rule_version"],
            "group_version": GROUP_VERSION,
            "large_group_threshold": 20,
            "very_large_group_threshold": 50,
            "effect": "review_only",
        }
        job = start_or_resume_similarity_job(
            connection,
            job_id=job_id,
            job_kind="similarity_groups",
            config=config,
            algorithm="connected components",
            algorithm_version=GROUP_VERSION,
        )
        relationships = connection.execute(
            """
            SELECT similarity_relationship_id, left_content_identity_id,
                   right_content_identity_id, phash_distance, dhash_distance
            FROM similarity_relationships
            WHERE analysis_run_id = ?
            ORDER BY left_content_identity_id, right_content_identity_id
            """,
            (int(analysis_job[1]),),
        ).fetchall()
        edges = [(int(row[1]), int(row[2])) for row in relationships]
        components = connected_components(edges)
        if not job.completed:
            relationship_by_component: dict[int, list[sqlite3.Row]] = defaultdict(list)
            component_for_member = {
                member: index for index, component in enumerate(components) for member in component
            }
            for relationship in relationships:
                relationship_by_component[component_for_member[int(relationship[1])]].append(
                    relationship
                )
            completed_this_call = 0
            for index, component in enumerate(components):
                identity_rows = connection.execute(
                    f"SELECT content_identity_id, identity_key FROM content_identities "
                    f"WHERE content_identity_id IN ({','.join('?' for _ in component)}) "
                    "ORDER BY identity_key",
                    component,
                ).fetchall()
                identity_keys = [str(row[1]) for row in identity_rows]
                external_group_id = stable_key(
                    "m16-review-group-id-v1", analysis_config["rule_version"], *identity_keys
                ).split(":", 1)[1][:16]
                item_key = stable_key("m16-group-item-v1", external_group_id)
                if similarity_item_exists(connection, job_id, item_key):
                    continue
                group_relationships = relationship_by_component[index]
                phash_distances = [int(row[3]) for row in group_relationships]
                dhash_distances = [int(row[4]) for row in group_relationships]
                source_names = sorted({
                    str(row[0])
                    for row in connection.execute(
                        f"SELECT DISTINCT s.display_name FROM physical_instances pi "
                        f"JOIN sources s ON s.source_id = pi.source_id "
                        f"WHERE pi.content_identity_id IN "
                        f"({','.join('?' for _ in component)})",
                        component,
                    )
                })
                tier = review_tier(len(component))
                cursor = connection.execute(
                    """
                    INSERT INTO similarity_groups(
                        group_key, analysis_run_id, external_group_id, unique_contents,
                        candidate_pairs, min_phash_distance, max_phash_distance,
                        min_dhash_distance, max_dhash_distance, unique_sources, sources_text,
                        review_tier, is_large_ambiguous
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stable_key("m16-review-group-v1", job_id, external_group_id),
                        job.analysis_run_id,
                        f"M16-{external_group_id}",
                        len(component),
                        len(group_relationships),
                        min(phash_distances),
                        max(phash_distances),
                        min(dhash_distances),
                        max(dhash_distances),
                        len(source_names),
                        " + ".join(source_names),
                        tier,
                        int(len(component) > 20),
                    ),
                )
                group_id = int(cursor.lastrowid)
                for content_id in component:
                    connection.execute(
                        """
                        INSERT INTO similarity_group_memberships(
                            similarity_group_id, content_identity_id
                        ) VALUES (?, ?)
                        """,
                        (group_id, content_id),
                    )
                for relationship in group_relationships:
                    connection.execute(
                        """
                        INSERT INTO similarity_group_relationships(
                            similarity_group_id, similarity_relationship_id
                        ) VALUES (?, ?)
                        """,
                        (group_id, int(relationship[0])),
                    )
                record_similarity_item(
                    connection,
                    job_id=job_id,
                    item_key=item_key,
                    outcome="group",
                    payload={
                        "similarity_group_id": group_id,
                        "external_group_id": f"M16-{external_group_id}",
                        "unique_contents": len(component),
                        "candidate_pairs": len(group_relationships),
                        "review_tier": tier,
                        "over_20": len(component) > 20,
                        "over_50": len(component) > 50,
                    },
                )
                completed_this_call += 1
                if interrupt_after is not None and completed_this_call >= interrupt_after:
                    mark_similarity_interrupted(connection, job_id)
                    raise PipelineInterrupted(
                        f"Similarity-group job {job_id!r} interrupted after group checkpoint."
                    )
            finish_similarity_job(connection, job)
        return _group_report(connection, job_id, job.analysis_run_id)
    finally:
        connection.close()


def _group_report(
    connection: sqlite3.Connection,
    job_id: str,
    run_id: int,
) -> PipelineReport:
    row = connection.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(unique_contents), 0),
               COALESCE(MAX(unique_contents), 0),
               COALESCE(SUM(unique_contents > 20), 0),
               COALESCE(SUM(unique_contents > 50), 0)
        FROM similarity_groups WHERE analysis_run_id = ?
        """,
        (run_id,),
    ).fetchone()
    grouped_contents = int(connection.execute(
        """
        SELECT COUNT(DISTINCT sgm.content_identity_id)
        FROM similarity_group_memberships sgm
        JOIN similarity_groups sg ON sg.similarity_group_id = sgm.similarity_group_id
        WHERE sg.analysis_run_id = ?
        """,
        (run_id,),
    ).fetchone()[0])
    return PipelineReport(
        job_id,
        "similarity_groups",
        "completed",
        {
            "review_groups": int(row[0]),
            "grouped_unique_contents": grouped_contents,
            "largest_group": int(row[2]),
            "groups_over_20": int(row[3]),
            "groups_over_50": int(row[4]),
        },
    )
