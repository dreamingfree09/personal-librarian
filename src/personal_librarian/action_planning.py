"""Deterministic M18 physical-action planning and non-mutating preflight."""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import PlanningError
from personal_librarian.catalogue.importers.common import stable_key
from personal_librarian.catalogue.models import CanonicalScope, ReviewContextType
from personal_librarian.decisions import derive_context_state
from personal_librarian.safety import (
    PathIntent,
    PathSafetyPolicy,
    assess_write_destination,
    windows_collision_key,
)

PLANNER_VERSION = "m18-v1"
DEFAULT_SAFETY_MARGIN_BYTES = 1_073_741_824


@dataclass(frozen=True, slots=True)
class ActionPolicy:
    policy_id: str
    action_type: str
    context_requirement: str
    source_mode: str
    reversible: bool


POLICIES = {
    policy.policy_id: policy
    for policy in (
        ActionPolicy(
            "canonical-copy-to-destination-v1", "copy", "exact_or_similar",
            "approved_canonical", True,
        ),
        ActionPolicy(
            "canonical-move-to-destination-v1", "move", "exact_or_similar",
            "approved_canonical", True,
        ),
        ActionPolicy(
            "canonical-rename-to-destination-v1", "rename", "exact_or_similar",
            "approved_canonical", True,
        ),
        ActionPolicy(
            "exact-duplicate-quarantine-v1", "quarantine", "exact",
            "explicit_noncanonical", True,
        ),
    )
}


def create_plan(
    *,
    database_path: str | Path,
    policy_id: str,
    context_type: str,
    context_id: int,
    canonical_scope: str,
    approval_event_id: str,
    destination_root: str | Path,
    owner: str,
    source_physical_instance_ids: list[int] | None = None,
    safety_margin_bytes: int = DEFAULT_SAFETY_MARGIN_BYTES,
    reason: str | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    """Create or return one immutable plan snapshot; never alter media."""

    policy = safety_policy or PathSafetyPolicy()
    if policy_id not in POLICIES:
        raise PlanningError(f"Unsupported explicit action policy: {policy_id!r}.")
    action_policy = POLICIES[policy_id]
    try:
        scope = CanonicalScope(canonical_scope).value
        checked_context = ReviewContextType(context_type).value
    except ValueError as exc:
        raise PlanningError("Unsupported canonical scope or review context type.") from exc
    if context_id < 1 or safety_margin_bytes < 0:
        raise PlanningError("Context ID must be positive and safety margin non-negative.")
    owner = owner.strip()
    approval_event_id = approval_event_id.strip()
    if not owner or not approval_event_id:
        raise PlanningError("Owner and approval event ID must be explicit.")
    if action_policy.context_requirement == "exact" and checked_context != "exact":
        raise PlanningError("Exact-duplicate quarantine policy cannot use a similarity context.")

    raw_root = os.fspath(destination_root).replace("/", "\\")
    raw_drive, raw_tail = ntpath.splitdrive(raw_root)
    if not (
        (len(raw_drive) == 2 and raw_tail.startswith("\\"))
        or raw_root.startswith("\\\\")
    ):
        raise PlanningError("Destination root must be an explicit absolute Windows path.")
    if ".." in raw_tail.split("\\"):
        raise PlanningError("Destination root must not contain parent traversal components.")
    root_result = policy.check_path(destination_root, intent=PathIntent.WRITE)
    if not root_result.allowed:
        raise PlanningError(
            f"Unsafe destination root ({root_result.code}): {root_result.reason}"
        )
    assert root_result.assessed_path is not None
    root = ntpath.normpath(root_result.assessed_path)
    drive, tail = ntpath.splitdrive(root)
    if not ((len(drive) == 2 and tail.startswith("\\")) or root.startswith("\\\\")):
        raise PlanningError("Destination root must be an explicit absolute Windows path.")

    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        connection.execute("BEGIN IMMEDIATE")
        approval = connection.execute(
            """
            SELECT decision_event_id, workflow_action, canonical_scope,
                   subject_physical_instance_id, exact_content_identity_id,
                   similarity_group_id, owner_approved
            FROM decision_events WHERE decision_key = ?
            """,
            (approval_event_id,),
        ).fetchone()
        if approval is None or str(approval[1]) not in {"approve", "supersede"}:
            raise PlanningError("Plan requires an explicit M17 approval or supersession event.")
        if int(approval[6]) != 1 or str(approval[2]) != scope:
            raise PlanningError("Approval is not owner-approved for the requested scope.")
        approval_context = (
            ("exact", int(approval[4]))
            if approval[4] is not None
            else ("similar", int(approval[5]))
        )
        if approval_context != (checked_context, context_id):
            raise PlanningError("Approval belongs to another review context.")
        state = derive_context_state(connection, checked_context, context_id)
        current = state["scopes"][scope]["approved"]
        if current is None or str(current["approval_event_id"]) != approval_event_id:
            raise PlanningError("Approval event is not the current effective approval.")
        canonical_physical_id = int(current["physical_instance_id"])

        supplied_sources = sorted(set(source_physical_instance_ids or []))
        if action_policy.source_mode == "approved_canonical":
            if supplied_sources and supplied_sources != [canonical_physical_id]:
                raise PlanningError("Canonical policy source must be the approved physical instance.")
            source_ids = [canonical_physical_id]
        else:
            if not supplied_sources:
                raise PlanningError(
                    "Quarantine planning requires explicit non-canonical source instance IDs."
                )
            if canonical_physical_id in supplied_sources:
                raise PlanningError("Approved canonical instance cannot be a quarantine source.")
            source_ids = supplied_sources

        prepared_sources: list[tuple[sqlite3.Row, str, int | None]] = []
        source_snapshot_semantics: list[dict[str, object]] = []
        for source_id in source_ids:
            source = _source_snapshot(connection, source_id)
            if not _source_in_context(
                connection, checked_context, context_id, source_id, int(source[2])
            ):
                raise PlanningError(f"Source physical instance {source_id} is outside the context.")
            source_safety = policy.check_path(str(source[5]), intent=PathIntent.READ)
            if not source_safety.allowed:
                raise PlanningError(
                    f"Unsafe source ({source_safety.code}): {source_safety.reason}"
                )
            filename = ntpath.basename(str(source[5]))
            if not filename:
                raise PlanningError("Source path does not contain a usable filename.")
            destination = ntpath.normpath(ntpath.join(root, filename))
            if windows_collision_key(str(source[5])) == windows_collision_key(destination):
                raise PlanningError("Source is already the intended destination.")
            filesystem_mtime_ns = _catalogue_mtime_ns(source[7])
            prepared_sources.append((source, destination, filesystem_mtime_ns))
            source_snapshot_semantics.append(
                {
                    "physical_instance_id": source_id,
                    "instance_key": str(source[1]),
                    "content_identity_id": int(source[2]),
                    "sha256": str(source[3]),
                    "raw_path": str(source[4]),
                    "current_path": str(source[5]),
                    "size_bytes": int(source[6]),
                    "observed_modified_at": source[7],
                    "filesystem_mtime_ns": filesystem_mtime_ns,
                    "destination": destination,
                }
            )

        decision_snapshot = {
            "context_type": checked_context,
            "context_id": context_id,
            "canonical_scope": scope,
            "approval_event_id": approval_event_id,
            "canonical_physical_instance_id": canonical_physical_id,
            "scope_state": state["scopes"][scope],
        }
        snapshot_json = json.dumps(decision_snapshot, sort_keys=True, separators=(",", ":"))
        decision_fingerprint = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        semantics = {
            "planner_version": PLANNER_VERSION,
            "policy_id": policy_id,
            "context_type": checked_context,
            "context_id": context_id,
            "canonical_scope": scope,
            "approval_event_id": approval_event_id,
            "decision_fingerprint": decision_fingerprint,
            "destination_root": root,
            "source_snapshots": source_snapshot_semantics,
            "safety_margin_bytes": safety_margin_bytes,
            "reason": reason,
        }
        plan_key = stable_key(
            "m18-action-plan-v1",
            json.dumps(semantics, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        existing = connection.execute(
            "SELECT action_plan_id FROM action_plans WHERE plan_key = ?", (plan_key,)
        ).fetchone()
        if existing is not None:
            connection.rollback()
            return show_plan(database_path=database_path, plan_id=plan_key, safety_policy=policy)

        cursor = connection.execute(
            """
            INSERT INTO action_plans(
                plan_key, planner_version, policy_id, action_type, canonical_scope,
                context_type, context_id, approval_decision_event_id,
                decision_fingerprint, destination_root, requested_by,
                safety_margin_bytes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (
                plan_key, PLANNER_VERSION, policy_id, action_policy.action_type, scope,
                checked_context, context_id, int(approval[0]), decision_fingerprint,
                root, owner, safety_margin_bytes,
            ),
        )
        plan_row_id = int(cursor.lastrowid)
        for source, destination, filesystem_mtime_ns in prepared_sources:
            source_id = int(source[0])
            item_key = stable_key(
                "m18-action-item-v1", plan_key, source_id,
                action_policy.action_type, destination, policy_id,
            )
            restore = None
            if action_policy.action_type == "quarantine":
                restore = json.dumps(
                    {
                        "original_physical_instance_id": source_id,
                        "original_raw_path": str(source[4]),
                        "original_current_path": str(source[5]),
                        "content_identity_id": int(source[2]),
                        "sha256": str(source[3]),
                        "planned_quarantine_path": destination,
                        "plan_key": plan_key,
                        "approval_event_id": approval_event_id,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            item_reason = reason or (
                "Explicit planning of a non-canonical exact copy for reversible quarantine."
                if action_policy.action_type == "quarantine"
                else "Explicit planning from the current owner-approved canonical decision."
            )
            connection.execute(
                """
                INSERT INTO action_plan_items(
                    action_plan_id, item_key, action_type, source_physical_instance_id,
                    source_raw_path, source_current_path, destination_path,
                    content_identity_id, sha256, expected_size_bytes,
                    expected_modified_at, expected_filesystem_mtime_ns,
                    canonical_scope, context_type, context_id,
                    approval_decision_event_id, reason,
                    expected_preconditions_json, expected_postconditions_json,
                    restore_provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_row_id, item_key, action_policy.action_type, source_id,
                    str(source[4]), str(source[5]), destination, int(source[2]),
                    str(source[3]), int(source[6]), source[7], filesystem_mtime_ns,
                    scope, checked_context, context_id, int(approval[0]), item_reason,
                    json.dumps(
                        {
                            "decision_current": True,
                            "source_catalogue_identity_matches": True,
                            "source_size_bytes": int(source[6]),
                            "source_modified_at": source[7],
                            "overwrite": False,
                        },
                        sort_keys=True,
                    ),
                    json.dumps(
                        {
                            "destination_path": destination,
                            "sha256": str(source[3]),
                            "overwrite": False,
                            "execution_available": False,
                        },
                        sort_keys=True,
                    ),
                    restore,
                ),
            )
        connection.execute(
            """
            INSERT INTO action_plan_events(
                event_key, action_plan_id, event_type, actor_identifier, reason
            ) VALUES (?, ?, 'created', ?, ?)
            """,
            (stable_key("m18-plan-created-v1", plan_key), plan_row_id, owner, reason),
        )
        connection.commit()
        return show_plan(database_path=database_path, plan_id=plan_key, safety_policy=policy)
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise PlanningError(f"Plan could not be recorded: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def preflight_plan(
    *,
    database_path: str | Path,
    plan_id: str,
    actor: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    """Inspect bounded source/destination state and append results; never write media."""

    policy = safety_policy or PathSafetyPolicy()
    actor = actor.strip()
    if not actor:
        raise PlanningError("Preflight actor must be explicit.")
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        connection.execute("BEGIN IMMEDIATE")
        plan = _plan_row(connection, plan_id)
        if str(plan[13]) == "invalidated":
            raise PlanningError("Invalidated plans cannot be preflighted.")
        items = _item_rows(connection, int(plan[0]))
        if not items:
            raise PlanningError("Plan contains no items.")
        attempt_id = str(uuid4())
        decision_current = _approval_is_current(connection, plan)
        collision_counts: dict[str, int] = {}
        for item in items:
            key = windows_collision_key(str(item[7]))
            collision_counts[key] = collision_counts.get(key, 0) + 1
        planned_bytes = sum(
            int(item[10]) for item in items if str(item[3]) != "rename"
        )
        required_bytes = planned_bytes + int(plan[12])
        free_state, free_bytes = _free_space(str(plan[10]), required_bytes)
        overall_states: list[str] = []
        for item in items:
            details: dict[str, object] = {
                "decision_current": decision_current,
                "overwrite_policy": "NO",
                "execution_available": False,
            }
            source_state = _preflight_source(connection, item, plan, policy, details)
            boundary = assess_write_destination(
                str(plan[10]), str(item[7]), safety_policy=policy
            )
            details["destination_boundary"] = {
                "code": boundary.code,
                "reason": boundary.reason,
                "resolved_root": boundary.resolved_root,
                "resolved_existing_ancestor": boundary.resolved_existing_ancestor,
            }
            safety_state = "PASS" if boundary.allowed else "FAIL"
            destination_state, destination_conflict = _destination_state(item, details)
            collision_key = windows_collision_key(str(item[7]))
            if collision_counts[collision_key] > 1:
                conflict_state = "planned_item_destination_collision"
            elif windows_collision_key(str(item[6])) == collision_key:
                conflict_state = "source_destination_collision"
            else:
                conflict_state = destination_conflict
            if not decision_current:
                overall = "STALE"
            elif (
                source_state == "PASS"
                and destination_state == "available"
                and conflict_state == "none"
                and safety_state == "PASS"
                and free_state == "PASS"
            ):
                overall = "PASS"
            else:
                overall = "FAIL"
            overall_states.append(overall)
            connection.execute(
                """
                INSERT INTO action_plan_preflight_results(
                    attempt_id, action_plan_id, action_plan_item_id,
                    source_state, destination_state, conflict_state,
                    free_space_state, safety_state, overall_state,
                    observed_free_bytes, required_bytes, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id, int(plan[0]), int(item[0]), source_state,
                    destination_state, conflict_state, free_state, safety_state,
                    overall, free_bytes, required_bytes,
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                ),
            )
        if "STALE" in overall_states:
            status, event_type = "stale", "stale"
        elif all(state == "PASS" for state in overall_states):
            status, event_type = "preflight_passed", "preflight_passed"
        else:
            status, event_type = "preflight_failed", "preflight_failed"
        connection.execute(
            "UPDATE action_plans SET status = ? WHERE action_plan_id = ?",
            (status, int(plan[0])),
        )
        connection.execute(
            """
            INSERT INTO action_plan_events(
                event_key, action_plan_id, event_type, actor_identifier,
                reason, attempt_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                stable_key("m18-plan-preflight-event-v1", attempt_id), int(plan[0]),
                event_type, actor, "Non-mutating M18 preflight", attempt_id,
            ),
        )
        connection.commit()
        return plan_report(
            database_path=database_path, plan_id=str(plan[1]), safety_policy=policy
        )
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise PlanningError(f"Preflight could not be recorded: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def invalidate_plan(
    *,
    database_path: str | Path,
    plan_id: str,
    event_id: str,
    owner: str,
    reason: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    policy = safety_policy or PathSafetyPolicy()
    if not event_id.strip() or not owner.strip() or not reason.strip():
        raise PlanningError("Invalidation requires explicit event ID, owner, and reason.")
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        connection.execute("BEGIN IMMEDIATE")
        plan = _plan_row(connection, plan_id)
        if str(plan[13]) == "invalidated":
            raise PlanningError("Plan is already invalidated.")
        connection.execute(
            """
            UPDATE action_plans SET status = 'invalidated',
                invalidated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                invalidation_reason = ? WHERE action_plan_id = ?
            """,
            (reason, int(plan[0])),
        )
        connection.execute(
            """
            INSERT INTO action_plan_events(
                event_key, action_plan_id, event_type, actor_identifier, reason
            ) VALUES (?, ?, 'invalidated', ?, ?)
            """,
            (event_id, int(plan[0]), owner, reason),
        )
        connection.commit()
        return show_plan(
            database_path=database_path, plan_id=str(plan[1]), safety_policy=policy
        )
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise PlanningError(f"Invalidation could not be recorded: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_plans(
    *,
    database_path: str | Path,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    if limit < 1 or offset < 0:
        raise PlanningError("Plan limit must be positive and offset non-negative.")
    allowed = {"draft", "preflight_passed", "preflight_failed", "stale", "invalidated"}
    if status is not None and status not in allowed:
        raise PlanningError(f"Unsupported plan status: {status!r}.")
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        where = "WHERE status = ?" if status else ""
        parameters: tuple[object, ...] = (status,) if status else ()
        rows = connection.execute(
            f"""
            SELECT ap.plan_key, ap.policy_id, ap.action_type, ap.canonical_scope,
                   ap.context_type, ap.context_id, ap.status, ap.destination_root,
                   ap.created_at, COUNT(api.action_plan_item_id),
                   COALESCE(SUM(api.expected_size_bytes), 0)
            FROM action_plans ap
            LEFT JOIN action_plan_items api ON api.action_plan_id = ap.action_plan_id
            {where}
            GROUP BY ap.action_plan_id ORDER BY ap.plan_key
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        return {
            "plans": [
                {
                    "plan_id": str(row[0]), "policy": str(row[1]),
                    "action_type": str(row[2]), "canonical_scope": str(row[3]),
                    "context_type": str(row[4]), "context_id": int(row[5]),
                    "status": str(row[6]), "destination_root": str(row[7]),
                    "created_at": str(row[8]), "item_count": int(row[9]),
                    "total_bytes": int(row[10]),
                }
                for row in rows
            ],
            "status_filter": status,
            "limit": limit,
            "offset": offset,
        }
    finally:
        connection.close()


def show_plan(
    *,
    database_path: str | Path,
    plan_id: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        plan = _plan_row(connection, plan_id)
        items = _item_rows(connection, int(plan[0]))
        return _serialise_plan(connection, plan, items, include_results=True)
    finally:
        connection.close()


def plan_report(
    *,
    database_path: str | Path,
    plan_id: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    result = show_plan(
        database_path=database_path, plan_id=plan_id, safety_policy=safety_policy
    )
    states = [
        (item.get("latest_preflight") or {}).get("overall_state")
        for item in result["items"]
    ]
    result["dry_run_summary"] = {
        "pass": states.count("PASS"),
        "fail": states.count("FAIL"),
        "stale": states.count("STALE"),
        "message": "NO FILESYSTEM CHANGES WERE PERFORMED",
    }
    return result


def _source_snapshot(connection: sqlite3.Connection, source_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT pi.physical_instance_id, pi.instance_key, pi.content_identity_id,
               cih.hash_value, pi.raw_relative_path, pi.current_observed_path,
               pi.size_bytes, pi.observed_modified_at
        FROM physical_instances pi
        LEFT JOIN content_identity_hashes cih
          ON cih.content_identity_id = pi.content_identity_id AND cih.algorithm = 'SHA-256'
        WHERE pi.physical_instance_id = ?
        """,
        (source_id,),
    ).fetchone()
    if row is None:
        raise PlanningError(f"Physical instance {source_id} does not exist.")
    if row[2] is None or row[3] is None or row[5] is None or row[6] is None:
        raise PlanningError("Source lacks content identity, SHA-256, path, or byte size.")
    return row


def _source_in_context(
    connection: sqlite3.Connection,
    context_type: str,
    context_id: int,
    physical_id: int,
    content_id: int,
) -> bool:
    if context_type == "exact":
        return content_id == context_id and connection.execute(
            "SELECT 1 FROM physical_instances WHERE physical_instance_id = ? "
            "AND content_identity_id = ?", (physical_id, context_id),
        ).fetchone() is not None
    return connection.execute(
        "SELECT 1 FROM similarity_group_memberships WHERE similarity_group_id = ? "
        "AND content_identity_id = ?", (context_id, content_id),
    ).fetchone() is not None


_AWARE_TIMESTAMP = re.compile(
    r"^(?P<seconds>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?(?P<zone>Z|[+-]\d{2}:\d{2})$"
)


def _catalogue_mtime_ns(value: object) -> int | None:
    """Convert an aware catalogue timestamp to exact epoch nanoseconds."""

    if value is None:
        return None
    match = _AWARE_TIMESTAMP.fullmatch(str(value))
    if match is None:
        return None
    zone = "+00:00" if match.group("zone") == "Z" else match.group("zone")
    instant = datetime.fromisoformat(f"{match.group('seconds')}{zone}")
    seconds = int(instant.timestamp())
    fraction = (match.group("fraction") or "").ljust(9, "0")
    return seconds * 1_000_000_000 + int(fraction or "0")


def _plan_row(connection: sqlite3.Connection, plan_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM action_plans WHERE plan_key = ?", (plan_id,),
    ).fetchone()
    if row is None:
        raise PlanningError(f"Action plan {plan_id!r} does not exist.")
    return row


def _item_rows(connection: sqlite3.Connection, plan_row_id: int) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM action_plan_items WHERE action_plan_id = ? ORDER BY item_key",
        (plan_row_id,),
    ).fetchall()


def _approval_is_current(connection: sqlite3.Connection, plan: sqlite3.Row) -> bool:
    approval_key = connection.execute(
        "SELECT decision_key FROM decision_events WHERE decision_event_id = ?",
        (int(plan[8]),),
    ).fetchone()
    if approval_key is None:
        return False
    state = derive_context_state(connection, str(plan[6]), int(plan[7]))
    current = state["scopes"][str(plan[5])]["approved"]
    return current is not None and str(current["approval_event_id"]) == str(approval_key[0])


def _preflight_source(
    connection: sqlite3.Connection,
    item: sqlite3.Row,
    plan: sqlite3.Row,
    policy: PathSafetyPolicy,
    details: dict[str, object],
) -> str:
    current = connection.execute(
        """
        SELECT pi.content_identity_id, pi.raw_relative_path, pi.current_observed_path,
               pi.size_bytes, pi.observed_modified_at, cih.hash_value
        FROM physical_instances pi
        LEFT JOIN content_identity_hashes cih
          ON cih.content_identity_id = pi.content_identity_id AND cih.algorithm = 'SHA-256'
        WHERE pi.physical_instance_id = ?
        """,
        (int(item[4]),),
    ).fetchone()
    if current is None:
        return "source_missing_from_catalogue"
    if (
        current[0] is None
        or int(current[0]) != int(item[8])
        or str(current[1]) != str(item[5])
        or str(current[2]) != str(item[6])
        or current[3] is None
        or int(current[3]) != int(item[10])
        or str(current[5]) != str(item[9])
    ):
        return "source_catalogue_snapshot_changed"
    if not _source_in_context(
        connection, str(plan[6]), int(plan[7]), int(item[4]), int(item[8])
    ):
        return "source_context_mismatch"
    path_result = policy.check_path(str(item[6]), intent=PathIntent.READ)
    if not path_result.allowed:
        details["source_safety"] = {"code": path_result.code, "reason": path_result.reason}
        return "source_unsafe"
    path = Path(str(item[6]))
    try:
        if not path.exists() or not path.is_file():
            return "source_missing"
        stat_result = path.stat()
    except OSError as exc:
        details["source_error"] = str(exc)
        return "source_unreadable"
    if stat_result.st_size != int(item[10]):
        return "source_size_changed"
    if item[12] is not None and stat_result.st_mtime_ns != int(item[12]):
        return "source_mtime_changed"
    return "PASS"


def _destination_state(
    item: sqlite3.Row,
    details: dict[str, object],
) -> tuple[str, str]:
    destination = Path(str(item[7]))
    try:
        if destination.exists():
            if not destination.is_file():
                return "file_directory_conflict", "destination_file_directory_conflict"
            digest = _sha256_file(destination)
            details["destination_sha256"] = digest
            if digest == str(item[9]):
                return "exists_same_content", "destination_exists_same_content"
            return "exists_different_content", "destination_exists_different_content"
        parent = destination.parent
        if parent.exists():
            desired_key = windows_collision_key(str(destination))
            for sibling in parent.iterdir():
                if windows_collision_key(str(sibling)) == desired_key:
                    return "case_unicode_collision", "destination_case_unicode_collision"
        return "available", "none"
    except OSError as exc:
        details["destination_error"] = str(exc)
        return "unknown", "destination_state_unknown"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _free_space(root: str, required_bytes: int) -> tuple[str, int | None]:
    try:
        free = int(shutil.disk_usage(root).free)
    except OSError:
        return "UNKNOWN", None
    return ("PASS" if free >= required_bytes else "FAIL"), free


def _serialise_plan(
    connection: sqlite3.Connection,
    plan: sqlite3.Row,
    items: list[sqlite3.Row],
    *,
    include_results: bool,
) -> dict[str, object]:
    approval_key = connection.execute(
        "SELECT decision_key FROM decision_events WHERE decision_event_id = ?",
        (int(plan[8]),),
    ).fetchone()[0]
    serialised_items = []
    for item in items:
        value: dict[str, object] = {
            "item_id": str(item[2]),
            "operation": str(item[3]),
            "source_physical_instance_id": int(item[4]),
            "source_raw_path": str(item[5]),
            "source_current_path": str(item[6]),
            "destination_path": str(item[7]),
            "content_identity_id": int(item[8]),
            "sha256": str(item[9]),
            "size_bytes": int(item[10]),
            "expected_modified_at": item[11],
            "approval_event_id": approval_key,
            "reason": str(item[17]),
            "expected_preconditions": json.loads(str(item[18])),
            "expected_postconditions": json.loads(str(item[19])),
            "restore_provenance": (
                None if item[20] is None else json.loads(str(item[20]))
            ),
        }
        if include_results:
            results = connection.execute(
                """
                SELECT attempt_id, source_state, destination_state, conflict_state,
                       free_space_state, safety_state, overall_state,
                       observed_free_bytes, required_bytes, details_json, checked_at
                FROM action_plan_preflight_results
                WHERE action_plan_item_id = ?
                ORDER BY action_plan_preflight_result_id
                """,
                (int(item[0]),),
            ).fetchall()
            history = [
                {
                    "attempt_id": str(result[0]), "source_state": str(result[1]),
                    "destination_state": str(result[2]),
                    "conflict_state": str(result[3]),
                    "free_space_state": str(result[4]),
                    "safety_state": str(result[5]),
                    "overall_state": str(result[6]),
                    "observed_free_bytes": result[7],
                    "required_bytes": int(result[8]),
                    "details": json.loads(str(result[9])),
                    "checked_at": str(result[10]),
                }
                for result in results
            ]
            value["preflight_history"] = history
            value["latest_preflight"] = history[-1] if history else None
        serialised_items.append(value)
    events = [
        {
            "event_id": str(row[0]), "event_type": str(row[1]),
            "actor": str(row[2]), "reason": row[3], "attempt_id": row[4],
            "recorded_at": str(row[5]),
        }
        for row in connection.execute(
            """
            SELECT event_key, event_type, actor_identifier, reason, attempt_id, recorded_at
            FROM action_plan_events WHERE action_plan_id = ? ORDER BY action_plan_event_id
            """,
            (int(plan[0]),),
        )
    ]
    return {
        "plan_id": str(plan[1]),
        "planner_version": str(plan[2]),
        "policy": str(plan[3]),
        "operation": str(plan[4]),
        "canonical_scope": str(plan[5]),
        "context_type": str(plan[6]),
        "context_id": int(plan[7]),
        "approval_event_id": str(approval_key),
        "decision_fingerprint": str(plan[9]),
        "destination_root": str(plan[10]),
        "requested_by": str(plan[11]),
        "safety_margin_bytes": int(plan[12]),
        "status": str(plan[13]),
        "created_at": str(plan[14]),
        "invalidated_at": plan[15],
        "invalidation_reason": plan[16],
        "item_count": len(items),
        "total_bytes": sum(int(item[10]) for item in items),
        "items": serialised_items,
        "events": events,
        "execution_available": False,
        "message": "NO FILESYSTEM CHANGES WERE PERFORMED",
    }
