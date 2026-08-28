"""Deterministic catalogue-only exact and near-duplicate review queues."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import DecisionError
from personal_librarian.catalogue.models import ReviewContextType
from personal_librarian.decisions import SCOPES, derive_context_state, load_context_states
from personal_librarian.safety import PathSafetyPolicy

REVIEW_STATUSES = frozenset(
    {"pending", "reviewed", "partially_reviewed", "decided", "abstained", "reopened"}
)


def _validate_page(limit: int, offset: int) -> None:
    if limit < 1:
        raise DecisionError("Review limit must be positive.")
    if offset < 0:
        raise DecisionError("Review offset must be non-negative.")


def _matches_status(actual: str, requested: str | None) -> bool:
    if requested is None:
        return True
    if requested not in REVIEW_STATUSES:
        raise DecisionError(f"Unsupported review status filter: {requested!r}.")
    if requested == "reviewed":
        return actual != "pending"
    return actual == requested


def _default_state() -> dict[str, object]:
    return {
        "review_status": "pending",
        "scopes": {
            scope: {
                "status": "pending",
                "approved": None,
                "pending_nominations": [],
                "nominations": [],
                "has_events": False,
            }
            for scope in SCOPES
        },
    }


def _sources_for_content(connection: sqlite3.Connection, content_id: int) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            """
            SELECT DISTINCT s.display_name
            FROM physical_instances pi JOIN sources s ON s.source_id = pi.source_id
            WHERE pi.content_identity_id = ? ORDER BY s.display_name
            """,
            (content_id,),
        )
    ]


def _physical_canonical_state(
    state: dict[str, object], physical_instance_id: int
) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    for scope in SCOPES:
        scope_state = state["scopes"][scope]
        approved = scope_state["approved"]
        result[scope] = {
            "nominated": any(
                int(item["physical_instance_id"]) == physical_instance_id
                for item in scope_state["pending_nominations"]
            ),
            "approved": (
                approved is not None
                and int(approved["physical_instance_id"]) == physical_instance_id
            ),
        }
    return result


def _physical_rows(
    connection: sqlite3.Connection,
    content_ids: list[int],
    state: dict[str, object],
) -> list[dict[str, object]]:
    placeholders = ",".join("?" for _ in content_ids)
    rows = connection.execute(
        f"""
        SELECT pi.physical_instance_id, pi.instance_key, pi.content_identity_id,
               ci.identity_key, cih.hash_value AS sha256, s.display_name AS source,
               pi.raw_relative_path, pi.current_observed_path, pi.size_bytes,
               pi.extension, pi.observed_created_at, pi.observed_modified_at
        FROM physical_instances pi
        JOIN content_identities ci ON ci.content_identity_id = pi.content_identity_id
        JOIN sources s ON s.source_id = pi.source_id
        LEFT JOIN content_identity_hashes cih
          ON cih.content_identity_id = ci.content_identity_id AND cih.algorithm = 'SHA-256'
        WHERE pi.content_identity_id IN ({placeholders})
        ORDER BY ci.identity_key, s.source_key, pi.raw_relative_path, pi.physical_instance_id
        """,
        content_ids,
    ).fetchall()
    copy_counts = {
        int(row[0]): int(row[1])
        for row in connection.execute(
            f"SELECT content_identity_id, COUNT(*) FROM physical_instances "
            f"WHERE content_identity_id IN ({placeholders}) GROUP BY content_identity_id",
            content_ids,
        )
    }
    return [
        {
            "physical_instance_id": int(row[0]),
            "instance_key": str(row[1]),
            "content_identity_id": int(row[2]),
            "content_identity_key": str(row[3]),
            "sha256": row[4],
            "source": str(row[5]),
            "raw_relative_path": str(row[6]),
            "current_observed_path": row[7],
            "size_bytes": row[8],
            "extension": row[9],
            "observed_created_at": row[10],
            "observed_modified_at": row[11],
            "exact_duplicate_count": copy_counts[int(row[2])],
            "canonical": _physical_canonical_state(state, int(row[0])),
        }
        for row in rows
    ]


def list_exact_reviews(
    *,
    database_path: str | Path,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    _validate_page(limit, offset)
    if status is not None and status not in REVIEW_STATUSES:
        raise DecisionError(f"Unsupported review status filter: {status!r}.")
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        states = load_context_states(connection)
        rows = connection.execute(
            """
            SELECT ci.content_identity_id, ci.identity_key, cih.hash_value,
                   COUNT(pi.physical_instance_id) AS copies,
                   MIN(pi.size_bytes), MAX(pi.size_bytes),
                   MIN(pi.observed_modified_at), MAX(pi.observed_modified_at)
            FROM content_identities ci
            JOIN physical_instances pi ON pi.content_identity_id = ci.content_identity_id
            LEFT JOIN content_identity_hashes cih
              ON cih.content_identity_id = ci.content_identity_id AND cih.algorithm = 'SHA-256'
            GROUP BY ci.content_identity_id, ci.identity_key, cih.hash_value
            HAVING COUNT(pi.physical_instance_id) >= 2
            ORDER BY ci.identity_key, ci.content_identity_id
            """
        ).fetchall()
        matched: list[tuple[sqlite3.Row, dict[str, object]]] = []
        for row in rows:
            content_id = int(row[0])
            state = states.get((ReviewContextType.EXACT.value, content_id), _default_state())
            if _matches_status(str(state["review_status"]), status):
                matched.append((row, state))
        page = matched[offset : offset + limit]
        items = [
            {
                "context_type": "exact",
                "context_id": int(row[0]),
                "content_identity_key": str(row[1]),
                "sha256": row[2],
                "group_size": int(row[3]),
                "sources": _sources_for_content(connection, int(row[0])),
                "size_bytes_min": row[4],
                "size_bytes_max": row[5],
                "modified_at_min": row[6],
                "modified_at_max": row[7],
                "review_status": state["review_status"],
                "canonical_scopes": {
                    scope: state["scopes"][scope]["status"] for scope in SCOPES
                },
            }
            for row, state in page
        ]
        return {
            "queue": "exact",
            "status_filter": status,
            "offset": offset,
            "limit": limit,
            "total_matching": len(matched),
            "items": items,
        }
    finally:
        connection.close()


def show_exact_review(
    *,
    database_path: str | Path,
    context_id: int,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        identity = connection.execute(
            """
            SELECT ci.identity_key, cih.hash_value, COUNT(pi.physical_instance_id)
            FROM content_identities ci
            JOIN physical_instances pi ON pi.content_identity_id = ci.content_identity_id
            LEFT JOIN content_identity_hashes cih
              ON cih.content_identity_id = ci.content_identity_id AND cih.algorithm = 'SHA-256'
            WHERE ci.content_identity_id = ?
            GROUP BY ci.content_identity_id, ci.identity_key, cih.hash_value
            """,
            (context_id,),
        ).fetchone()
        if identity is None or int(identity[2]) < 2:
            raise DecisionError(f"Exact review context {context_id} does not exist.")
        state = derive_context_state(connection, "exact", context_id)
        evidence_groups = [
            {
                "exact_duplicate_group_id": int(row[0]),
                "group_key": str(row[1]),
                "analysis_run_id": int(row[2]),
                "reported_copies": int(row[3]),
            }
            for row in connection.execute(
                """
                SELECT exact_duplicate_group_id, group_key, analysis_run_id, copies
                FROM exact_duplicate_groups WHERE content_identity_id = ?
                ORDER BY analysis_run_id, group_key
                """,
                (context_id,),
            )
        ]
        return {
            "context_type": "exact",
            "context_id": context_id,
            "content_identity_key": str(identity[0]),
            "sha256": identity[1],
            "group_size": int(identity[2]),
            "sources": _sources_for_content(connection, context_id),
            "review_status": state["review_status"],
            "decision_state": state,
            "evidence_groups": evidence_groups,
            "physical_instances": _physical_rows(connection, [context_id], state),
        }
    finally:
        connection.close()


def list_similar_reviews(
    *,
    database_path: str | Path,
    status: str | None = None,
    large_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    _validate_page(limit, offset)
    if status is not None and status not in REVIEW_STATUSES:
        raise DecisionError(f"Unsupported review status filter: {status!r}.")
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        states = load_context_states(connection)
        rows = connection.execute(
            """
            SELECT similarity_group_id, group_key, external_group_id, analysis_run_id,
                   unique_contents, candidate_pairs, min_phash_distance,
                   max_phash_distance, min_dhash_distance, max_dhash_distance,
                   unique_sources, sources_text, review_tier, is_large_ambiguous
            FROM similarity_groups ORDER BY group_key, similarity_group_id
            """
        ).fetchall()
        matched: list[tuple[sqlite3.Row, dict[str, object]]] = []
        for row in rows:
            group_id = int(row[0])
            state = states.get((ReviewContextType.SIMILAR.value, group_id), _default_state())
            is_large = bool(row[13]) or int(row[4]) > 20
            if _matches_status(str(state["review_status"]), status) and (
                not large_only or is_large
            ):
                matched.append((row, state))
        items = []
        for row, state in matched[offset : offset + limit]:
            items.append(
                {
                    "context_type": "similar",
                    "context_id": int(row[0]),
                    "group_key": str(row[1]),
                    "review_group_id": str(row[2]),
                    "analysis_run_id": int(row[3]),
                    "unique_contents": int(row[4]),
                    "candidate_pairs": int(row[5]),
                    "phash_distance_range": [int(row[6]), int(row[7])],
                    "dhash_distance_range": [int(row[8]), int(row[9])],
                    "unique_sources": int(row[10]),
                    "sources": str(row[11]),
                    "review_tier": str(row[12]),
                    "is_large_ambiguous": bool(row[13]),
                    "is_over_50": int(row[4]) > 50,
                    "review_status": state["review_status"],
                    "canonical_scopes": {
                        scope: state["scopes"][scope]["status"] for scope in SCOPES
                    },
                }
            )
        return {
            "queue": "similar",
            "status_filter": status,
            "large_only": large_only,
            "offset": offset,
            "limit": limit,
            "total_matching": len(matched),
            "items": items,
        }
    finally:
        connection.close()


def show_similar_review(
    *,
    database_path: str | Path,
    context_id: int,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        group = connection.execute(
            """
            SELECT sg.group_key, sg.external_group_id, sg.analysis_run_id,
                   sg.unique_contents, sg.candidate_pairs, sg.review_tier,
                   sg.is_large_ambiguous, ar.algorithm, ar.algorithm_version
            FROM similarity_groups sg
            JOIN analysis_runs ar ON ar.analysis_run_id = sg.analysis_run_id
            WHERE sg.similarity_group_id = ?
            """,
            (context_id,),
        ).fetchone()
        if group is None:
            raise DecisionError(f"Similarity review context {context_id} does not exist.")
        content_ids = [
            int(row[0])
            for row in connection.execute(
                """
                SELECT sgm.content_identity_id
                FROM similarity_group_memberships sgm
                JOIN content_identities ci ON ci.content_identity_id = sgm.content_identity_id
                WHERE sgm.similarity_group_id = ? ORDER BY ci.identity_key
                """,
                (context_id,),
            )
        ]
        state = derive_context_state(connection, "similar", context_id)
        relationships = [
            {
                "relationship_id": int(row[0]),
                "left_content_identity_id": int(row[1]),
                "right_content_identity_id": int(row[2]),
                "phash_distance": row[3],
                "dhash_distance": row[4],
                "review_tier": row[5],
                "relationship_type": str(row[6]),
            }
            for row in connection.execute(
                """
                SELECT sr.similarity_relationship_id, sr.left_content_identity_id,
                       sr.right_content_identity_id, sr.phash_distance,
                       sr.dhash_distance, sr.review_tier, sr.relationship_type
                FROM similarity_group_relationships sgr
                JOIN similarity_relationships sr
                  ON sr.similarity_relationship_id = sgr.similarity_relationship_id
                WHERE sgr.similarity_group_id = ?
                ORDER BY sr.left_content_identity_id, sr.right_content_identity_id
                """,
                (context_id,),
            )
        ]
        return {
            "context_type": "similar",
            "context_id": context_id,
            "group_key": str(group[0]),
            "review_group_id": str(group[1]),
            "analysis_run_id": int(group[2]),
            "unique_contents": int(group[3]),
            "candidate_pairs": int(group[4]),
            "review_tier": str(group[5]),
            "is_large_ambiguous": bool(group[6]),
            "is_over_50": int(group[3]) > 50,
            "analysis_algorithm": group[7],
            "analysis_version": group[8],
            "review_status": state["review_status"],
            "decision_state": state,
            "content_identity_ids": content_ids,
            "physical_instances": _physical_rows(connection, content_ids, state),
            "relationships": relationships,
        }
    finally:
        connection.close()
