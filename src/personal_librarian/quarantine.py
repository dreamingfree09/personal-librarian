"""M19 narrowly scoped, same-volume exact-duplicate quarantine and restore."""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import QuarantineError
from personal_librarian.catalogue.importers.common import stable_key
from personal_librarian.decisions import derive_context_state
from personal_librarian.safety import (
    PathIntent,
    PathSafetyPolicy,
    assess_write_destination,
    windows_collision_key,
)

EXECUTOR_VERSION = "m19-exact-quarantine-v1"
QUARANTINE_POLICY = "exact-duplicate-quarantine-v1"


def execute_quarantine(
    *,
    database_path: str | Path,
    plan_id: str,
    item_id: str,
    quarantine_root: str | Path,
    actor: str,
    confirm_quarantine: bool,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    """Move one verified exact duplicate into quarantine after fresh validation."""

    if not confirm_quarantine:
        raise QuarantineError("Explicit --confirm-quarantine acknowledgement is required.")
    actor = _required(actor, "Execution actor")
    policy = safety_policy or PathSafetyPolicy()
    root = _explicit_root(quarantine_root, policy)
    initialise_catalogue(database_path, safety_policy=policy)

    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=policy
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _plan_item(connection, plan_id, item_id)
        existing = connection.execute(
            "SELECT execution_key FROM action_executions WHERE action_plan_item_id = ?",
            (int(row["action_plan_item_id"]),),
        ).fetchone()
        if existing is not None:
            connection.rollback()
            result = quarantine_status(
                database_path=database_path,
                execution_id=str(existing[0]),
                safety_policy=policy,
            )
            result["idempotent_replay"] = True
            result["message"] = "NO SECOND FILESYSTEM ACTION WAS PERFORMED"
            return result
        _assert_plan_gate(connection, row)
        if windows_collision_key(root) != windows_collision_key(
            str(row["destination_root"])
        ):
            raise QuarantineError(
                "Explicit quarantine root must exactly match the M18 plan destination root."
            )
        destination = _execution_destination(
            root, str(row["plan_key"]), str(row["item_key"]),
            str(row["source_current_path"]),
        )
        boundary = assess_write_destination(root, destination, safety_policy=policy)
        if not boundary.allowed:
            raise QuarantineError(
                f"Unsafe quarantine destination ({boundary.code}): {boundary.reason}"
            )
        execution_key = stable_key(EXECUTOR_VERSION, str(row["item_key"]))
        cursor = connection.execute(
            """
            INSERT INTO action_executions(
                execution_key, action_plan_id, action_plan_item_id,
                preflight_result_id, action_type, actor_identifier,
                source_path_snapshot, quarantine_root, destination_path,
                original_physical_instance_id, content_identity_id,
                approval_decision_event_id, expected_sha256,
                expected_size_bytes, status
            ) VALUES (?, ?, ?, ?, 'quarantine', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'requested')
            """,
            (
                execution_key, int(row["action_plan_id"]),
                int(row["action_plan_item_id"]), int(row["preflight_result_id"]),
                actor, str(row["source_current_path"]), root, destination,
                int(row["source_physical_instance_id"]),
                int(row["content_identity_id"]),
                int(row["approval_decision_event_id"]), str(row["sha256"]),
                int(row["expected_size_bytes"]),
            ),
        )
        execution_row_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO quarantine_records(
                record_key, action_execution_id, original_physical_instance_id,
                content_identity_id, original_path, quarantine_path,
                expected_sha256, expected_size_bytes, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                stable_key("m19-quarantine-record-v1", execution_key), execution_row_id,
                int(row["source_physical_instance_id"]),
                int(row["content_identity_id"]), str(row["source_current_path"]),
                destination, str(row["sha256"]), int(row["expected_size_bytes"]),
            ),
        )
        _insert_event(
            connection, execution_row_id, "requested", actor,
            {
                "confirmation": "confirm-quarantine",
                "executor_version": EXECUTOR_VERSION,
                "plan_id": plan_id,
                "item_id": item_id,
            },
        )
        connection.commit()
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise QuarantineError(f"Execution request could not be journaled: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    moved = False
    try:
        _transition(
            database_path, execution_key, "validating", "validating", actor,
            {"fresh_validation": True}, policy,
        )
        execution = _execution_row(database_path, execution_key, policy)
        source = Path(str(execution["source_path_snapshot"]))
        destination_path = Path(str(execution["destination_path"]))
        source_hash = _fresh_source_validation(
            database_path, execution, source, destination_path, policy
        )
        _set_pre_execution_hash(database_path, execution_key, source_hash, policy)

        # Recheck catalogue decision and source evidence after hashing, immediately
        # before the only physical mutation.
        _recheck_database_gate(database_path, execution, policy)
        current_stat = source.stat()
        if current_stat.st_size != int(execution["expected_size_bytes"]):
            raise QuarantineError("Source size changed after cryptographic verification.")
        expected_mtime = execution["expected_filesystem_mtime_ns"]
        if expected_mtime is not None and current_stat.st_mtime_ns != int(expected_mtime):
            raise QuarantineError("Source mtime changed after cryptographic verification.")
        if destination_path.exists():
            raise QuarantineError("Quarantine destination now exists; overwrite is forbidden.")

        _transition(
            database_path, execution_key, "moving", "moving", actor,
            {"same_volume_only": True}, policy,
        )
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        boundary = assess_write_destination(
            str(execution["quarantine_root"]), str(destination_path), safety_policy=policy
        )
        if not boundary.allowed:
            raise QuarantineError(
                f"Destination became unsafe ({boundary.code}): {boundary.reason}"
            )
        if destination_path.exists():
            raise QuarantineError("Quarantine destination exists; overwrite is forbidden.")
        os.rename(source, destination_path)
        moved = True

        _transition(
            database_path, execution_key, "verifying", "verifying", actor,
            {"source_absent": not source.exists()}, policy,
        )
        if source.exists() or not destination_path.is_file():
            raise QuarantineError("Post-move source/destination state is not unambiguous.")
        destination_stat = destination_path.stat()
        if destination_stat.st_size != int(execution["expected_size_bytes"]):
            raise QuarantineError("Post-move destination size does not match the plan.")
        destination_hash = _sha256_file(destination_path)
        if destination_hash != str(execution["expected_sha256"]):
            raise QuarantineError("Post-move destination SHA-256 verification failed.")
        _finalise_quarantine(
            database_path, execution_key, source_hash, destination_hash, actor, policy
        )
    except Exception as exc:
        reason = str(exc) or exc.__class__.__name__
        _record_failure(
            database_path, execution_key, actor, reason,
            recovery_required=moved, safety_policy=policy,
        )
        if isinstance(exc, QuarantineError):
            raise
        raise QuarantineError(f"Quarantine execution failed safely: {reason}") from exc

    result = quarantine_status(
        database_path=database_path, execution_id=execution_key, safety_policy=policy
    )
    result["message"] = "ONE FILE WAS QUARANTINED AND CRYPTOGRAPHICALLY VERIFIED"
    return result


def restore_quarantine(
    *,
    database_path: str | Path,
    execution_id: str,
    actor: str,
    confirm_restore: bool,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    """Restore one successfully quarantined file to its exact original path."""

    if not confirm_restore:
        raise QuarantineError("Explicit --confirm-restore acknowledgement is required.")
    actor = _required(actor, "Restore actor")
    policy = safety_policy or PathSafetyPolicy()
    execution = _execution_row(database_path, execution_id, policy)
    if str(execution["status"]) == "restored":
        result = quarantine_status(
            database_path=database_path, execution_id=execution_id, safety_policy=policy
        )
        result["idempotent_replay"] = True
        result["message"] = "NO SECOND FILESYSTEM ACTION WAS PERFORMED"
        return result
    if str(execution["status"]) != "succeeded" or str(execution["record_state"]) != "quarantined":
        raise QuarantineError("Only a verified, successfully quarantined record can be restored.")

    _append_event(
        database_path, int(execution["action_execution_id"]), "restore_requested",
        actor, {"confirmation": "confirm-restore"}, policy,
    )
    moved = False
    quarantine_path = Path(str(execution["destination_path"]))
    original_path = Path(str(execution["source_path_snapshot"]))
    try:
        source_check = policy.check_path(str(quarantine_path), intent=PathIntent.READ)
        if not source_check.allowed:
            raise QuarantineError(
                f"Unsafe quarantine source ({source_check.code}): {source_check.reason}"
            )
        if not quarantine_path.is_file():
            raise QuarantineError("Quarantine file is missing.")
        if quarantine_path.stat().st_size != int(execution["expected_size_bytes"]):
            raise QuarantineError("Quarantine file size no longer matches the record.")
        quarantine_hash = _sha256_file(quarantine_path)
        if quarantine_hash != str(execution["expected_sha256"]):
            raise QuarantineError("Quarantine file SHA-256 no longer matches the record.")
        original_check = policy.check_path(str(original_path), intent=PathIntent.WRITE)
        if not original_check.allowed:
            raise QuarantineError(
                f"Unsafe original restore path ({original_check.code}): "
                f"{original_check.reason}"
            )
        if original_path.exists():
            raise QuarantineError("Original path is occupied; restore will not overwrite it.")
        original_parent = original_path.parent
        boundary = assess_write_destination(
            str(original_parent), str(original_path), safety_policy=policy
        )
        if not boundary.allowed:
            raise QuarantineError(
                f"Original restore path is unsafe ({boundary.code}): {boundary.reason}"
            )
        _require_same_volume(quarantine_path, original_parent)

        _transition(
            database_path, execution_id, "moving", "restoring", actor,
            {"destination": str(original_path), "overwrite": False}, policy,
        )
        if original_path.exists():
            raise QuarantineError("Original path became occupied; restore stopped.")
        os.rename(quarantine_path, original_path)
        moved = True
        _transition(
            database_path, execution_id, "verifying", "verifying", actor,
            {"restore_verification": True}, policy,
        )
        if quarantine_path.exists() or not original_path.is_file():
            raise QuarantineError("Post-restore source/destination state is ambiguous.")
        if original_path.stat().st_size != int(execution["expected_size_bytes"]):
            raise QuarantineError("Restored file size does not match the record.")
        restored_hash = _sha256_file(original_path)
        if restored_hash != str(execution["expected_sha256"]):
            raise QuarantineError("Restored file SHA-256 verification failed.")
        _finalise_restore(database_path, execution_id, restored_hash, actor, policy)
    except Exception as exc:
        reason = str(exc) or exc.__class__.__name__
        if moved:
            _record_failure(
                database_path, execution_id, actor, reason,
                recovery_required=True, safety_policy=policy,
            )
        else:
            _append_event(
                database_path, int(execution["action_execution_id"]), "restore_failed",
                actor, {"reason": reason, "filesystem_mutation": False}, policy,
            )
        if isinstance(exc, QuarantineError):
            raise
        raise QuarantineError(f"Restore failed safely: {reason}") from exc

    result = quarantine_status(
        database_path=database_path, execution_id=execution_id, safety_policy=policy
    )
    result["message"] = "ONE QUARANTINED FILE WAS RESTORED AND VERIFIED"
    return result


def reconcile_quarantine(
    *,
    database_path: str | Path,
    execution_id: str,
    actor: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    """Classify journal/filesystem disagreement without moving or deleting files."""

    actor = _required(actor, "Reconciliation actor")
    policy = safety_policy or PathSafetyPolicy()
    execution = _execution_row(database_path, execution_id, policy)
    source = Path(str(execution["source_path_snapshot"]))
    destination = Path(str(execution["destination_path"]))
    source_exists = _safe_file_exists(source, policy)
    destination_boundary = assess_write_destination(
        str(execution["quarantine_root"]), str(destination), safety_policy=policy
    )
    if not destination_boundary.allowed:
        classification = "destination_unsafe"
        source_hash = destination_hash = None
    else:
        destination_exists = destination.is_file()
        source_hash = _sha256_file(source) if source_exists else None
        destination_hash = _sha256_file(destination) if destination_exists else None
        expected = str(execution["expected_sha256"])
        latest_event = str(execution["latest_event_type"] or "")
        if source_exists and not destination_exists:
            if source_hash != expected:
                classification = "source_hash_mismatch"
            elif str(execution["status"]) == "restored" or latest_event in {
                "restore_requested", "restoring", "verifying"
            }:
                classification = "restored_verified"
            elif str(execution["status"]) == "succeeded":
                classification = "source_only_after_quarantine"
            else:
                classification = "not_moved"
        elif not source_exists and destination_exists:
            classification = (
                "quarantined_verified"
                if destination_hash == expected
                else "destination_hash_mismatch"
            )
        elif source_exists and destination_exists:
            classification = "both_source_and_destination_exist"
        else:
            classification = "neither_source_nor_destination_exists"

    if classification == "quarantined_verified":
        _finalise_quarantine(
            database_path, execution_id,
            str(execution["pre_execution_sha256"] or execution["expected_sha256"]),
            str(destination_hash), actor, policy, reconciled=True,
        )
    elif classification == "restored_verified":
        _finalise_restore(
            database_path, execution_id, str(source_hash), actor, policy, reconciled=True
        )
    elif classification == "not_moved":
        _set_reconciliation(
            database_path, execution_id, actor, classification,
            status="failed", record_state="pending", safety_policy=policy,
        )
    else:
        _set_reconciliation(
            database_path, execution_id, actor, classification,
            status="recovery_required", record_state="recovery_required",
            safety_policy=policy,
        )
    result = quarantine_status(
        database_path=database_path, execution_id=execution_id, safety_policy=policy
    )
    result["reconciliation"] = {
        "classification": classification,
        "source_exists": source_exists,
        "destination_exists": destination.is_file(),
        "source_sha256": source_hash,
        "destination_sha256": destination_hash,
        "filesystem_mutation": False,
    }
    return result


def quarantine_status(
    *,
    database_path: str | Path,
    execution_id: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(
        database_path, read_only=True, safety_policy=policy
    )
    try:
        row = _execution_by_key(connection, execution_id)
        events = [
            {
                "event_id": str(event[0]), "event_type": str(event[1]),
                "actor": str(event[2]), "details": json.loads(str(event[3])),
                "recorded_at": str(event[4]),
            }
            for event in connection.execute(
                """
                SELECT event_key, event_type, actor_identifier, details_json, recorded_at
                FROM action_execution_events WHERE action_execution_id = ?
                ORDER BY action_execution_event_id
                """,
                (int(row["action_execution_id"]),),
            )
        ]
        locations = [
            {
                "event_id": str(event[0]), "action": str(event[1]),
                "from_path": str(event[2]), "to_path": str(event[3]),
                "sha256": str(event[4]), "size_bytes": int(event[5]),
                "recorded_at": str(event[6]),
            }
            for event in connection.execute(
                """
                SELECT event_key, location_action, from_path, to_path,
                       verified_sha256, verified_size_bytes, recorded_at
                FROM physical_instance_location_events WHERE action_execution_id = ?
                ORDER BY location_event_id
                """,
                (int(row["action_execution_id"]),),
            )
        ]
        return _serialise_execution(row, events, locations)
    finally:
        connection.close()


def quarantine_history(
    *,
    database_path: str | Path,
    plan_id: str | None = None,
    item_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    if limit < 1 or offset < 0:
        raise QuarantineError("History limit must be positive and offset non-negative.")
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(
        database_path, read_only=True, safety_policy=policy
    )
    try:
        clauses: list[str] = []
        parameters: list[object] = []
        if plan_id:
            clauses.append("ap.plan_key = ?")
            parameters.append(plan_id)
        if item_id:
            clauses.append("api.item_key = ?")
            parameters.append(item_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            f"""
            SELECT ae.execution_key, ap.plan_key, api.item_key, ae.status,
                   ae.actor_identifier, ae.source_path_snapshot, ae.destination_path,
                   ae.expected_sha256, ae.expected_size_bytes, ae.requested_at,
                   ae.finished_at, ae.failure_reason, qr.state
            FROM action_executions ae
            JOIN action_plans ap ON ap.action_plan_id = ae.action_plan_id
            JOIN action_plan_items api ON api.action_plan_item_id = ae.action_plan_item_id
            JOIN quarantine_records qr ON qr.action_execution_id = ae.action_execution_id
            {where}
            ORDER BY ae.action_execution_id DESC LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        return {
            "executions": [
                {
                    "execution_id": str(row[0]), "plan_id": str(row[1]),
                    "item_id": str(row[2]), "status": str(row[3]),
                    "actor": str(row[4]), "source_path": str(row[5]),
                    "destination_path": str(row[6]), "sha256": str(row[7]),
                    "size_bytes": int(row[8]), "requested_at": str(row[9]),
                    "finished_at": row[10], "failure_reason": row[11],
                    "quarantine_state": str(row[12]),
                }
                for row in rows
            ],
            "limit": limit, "offset": offset,
        }
    finally:
        connection.close()


def _plan_item(
    connection: sqlite3.Connection, plan_id: str, item_id: str
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT ap.action_plan_id, ap.plan_key, ap.policy_id, ap.action_type AS plan_action,
               ap.canonical_scope, ap.context_type, ap.context_id,
               ap.approval_decision_event_id, ap.destination_root,
               ap.safety_margin_bytes, ap.status AS plan_status,
               api.action_plan_item_id, api.item_key, api.action_type AS item_action,
               api.source_physical_instance_id, api.source_current_path,
               api.content_identity_id, api.sha256, api.expected_size_bytes,
               api.expected_filesystem_mtime_ns,
               api.approval_decision_event_id AS item_approval_decision_event_id,
               latest.action_plan_preflight_result_id AS preflight_result_id,
               latest.overall_state AS preflight_overall_state
        FROM action_plans ap
        JOIN action_plan_items api ON api.action_plan_id = ap.action_plan_id
        LEFT JOIN action_plan_preflight_results latest
          ON latest.action_plan_preflight_result_id = (
              SELECT MAX(candidate.action_plan_preflight_result_id)
              FROM action_plan_preflight_results candidate
              WHERE candidate.action_plan_item_id = api.action_plan_item_id
          )
        WHERE ap.plan_key = ? AND api.item_key = ?
        """,
        (plan_id, item_id),
    ).fetchone()
    if row is None:
        raise QuarantineError("The specified M18 plan/item pair does not exist.")
    return row


def _assert_plan_gate(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    if str(row["policy_id"]) != QUARANTINE_POLICY:
        raise QuarantineError("Only the exact-duplicate quarantine policy is executable.")
    if str(row["plan_action"]) != "quarantine" or str(row["item_action"]) != "quarantine":
        raise QuarantineError("Only quarantine plan items are executable in M19.")
    if str(row["context_type"]) != "exact":
        raise QuarantineError("Near-duplicate contexts cannot execute quarantine.")
    if str(row["plan_status"]) != "preflight_passed":
        raise QuarantineError("Plan must currently be preflight-passed.")
    if row["preflight_result_id"] is None or str(row["preflight_overall_state"]) != "PASS":
        raise QuarantineError("The latest item preflight must be PASS.")
    if int(row["item_approval_decision_event_id"]) != int(row["approval_decision_event_id"]):
        raise QuarantineError("Plan/item decision provenance is inconsistent.")
    state = derive_context_state(connection, "exact", int(row["context_id"]))
    approved = state["scopes"][str(row["canonical_scope"])]["approved"]
    if approved is None:
        raise QuarantineError("No current approved canonical instance exists.")
    approval = connection.execute(
        "SELECT decision_key FROM decision_events WHERE decision_event_id = ?",
        (int(row["approval_decision_event_id"]),),
    ).fetchone()
    if approval is None or str(approved["approval_event_id"]) != str(approval[0]):
        raise QuarantineError("Plan decision is stale; execution is forbidden.")
    canonical_id = int(approved["physical_instance_id"])
    if canonical_id == int(row["source_physical_instance_id"]):
        raise QuarantineError("The current canonical physical instance cannot be quarantined.")
    canonical = connection.execute(
        "SELECT content_identity_id FROM physical_instances WHERE physical_instance_id = ?",
        (canonical_id,),
    ).fetchone()
    if canonical is None or canonical[0] is None or int(canonical[0]) != int(row["context_id"]):
        raise QuarantineError("Current canonical instance lacks the expected exact identity.")
    current = connection.execute(
        """
        SELECT pi.content_identity_id, pi.current_observed_path, pi.size_bytes,
               cih.hash_value
        FROM physical_instances pi
        LEFT JOIN content_identity_hashes cih
          ON cih.content_identity_id = pi.content_identity_id AND cih.algorithm = 'SHA-256'
        WHERE pi.physical_instance_id = ?
        """,
        (int(row["source_physical_instance_id"]),),
    ).fetchone()
    if (
        current is None or current[0] is None or current[1] is None or current[2] is None
        or int(current[0]) != int(row["content_identity_id"])
        or int(current[0]) != int(row["context_id"])
        or str(current[1]) != str(row["source_current_path"])
        or int(current[2]) != int(row["expected_size_bytes"])
        or str(current[3]) != str(row["sha256"])
    ):
        raise QuarantineError("Source catalogue evidence no longer matches the plan snapshot.")


def _fresh_source_validation(
    database_path: str | Path,
    execution: sqlite3.Row,
    source: Path,
    destination: Path,
    policy: PathSafetyPolicy,
) -> str:
    path_result = policy.check_path(str(source), intent=PathIntent.READ)
    if not path_result.allowed:
        raise QuarantineError(
            f"Unsafe source ({path_result.code}): {path_result.reason}"
        )
    if not source.is_file():
        raise QuarantineError("Source file is missing.")
    source_stat = source.stat()
    if source_stat.st_size != int(execution["expected_size_bytes"]):
        raise QuarantineError("Source size changed after preflight.")
    expected_mtime = execution["expected_filesystem_mtime_ns"]
    if expected_mtime is not None and source_stat.st_mtime_ns != int(expected_mtime):
        raise QuarantineError("Source mtime changed after preflight.")
    if windows_collision_key(str(source)) == windows_collision_key(str(destination)):
        raise QuarantineError("Source is already the quarantine destination.")
    boundary = assess_write_destination(
        str(execution["quarantine_root"]), str(destination), safety_policy=policy
    )
    if not boundary.allowed:
        raise QuarantineError(
            f"Unsafe quarantine destination ({boundary.code}): {boundary.reason}"
        )
    if destination.exists():
        raise QuarantineError("Quarantine destination exists; overwrite is forbidden.")
    _require_same_volume(source, Path(str(execution["quarantine_root"])))
    required = int(execution["expected_size_bytes"]) + int(execution["safety_margin_bytes"])
    try:
        free = int(shutil.disk_usage(str(execution["quarantine_root"])).free)
    except OSError as exc:
        raise QuarantineError(f"Destination free space is unknown: {exc}") from exc
    if free < required:
        raise QuarantineError(
            f"Insufficient destination space: required {required}, available {free}."
        )
    digest = _sha256_file(source)
    if digest != str(execution["expected_sha256"]):
        raise QuarantineError("Source SHA-256 does not match the exact plan identity.")
    return digest


def _recheck_database_gate(
    database_path: str | Path, execution: sqlite3.Row, policy: PathSafetyPolicy
) -> None:
    connection = connect_existing_catalogue(
        database_path, read_only=True, safety_policy=policy
    )
    try:
        row = _plan_item(
            connection, str(execution["plan_key"]), str(execution["item_key"])
        )
        _assert_plan_gate(connection, row)
    finally:
        connection.close()


def _execution_row(
    database_path: str | Path, execution_id: str, policy: PathSafetyPolicy
) -> sqlite3.Row:
    connection = connect_existing_catalogue(
        database_path, read_only=True, safety_policy=policy
    )
    try:
        return _execution_by_key(connection, execution_id)
    finally:
        connection.close()


def _execution_by_key(connection: sqlite3.Connection, execution_id: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT ae.*, ap.plan_key, ap.policy_id, ap.canonical_scope,
               ap.context_type, ap.context_id, ap.safety_margin_bytes,
               api.item_key, api.expected_filesystem_mtime_ns,
               qr.state AS record_state, qr.last_reconciliation_state,
               (
                   SELECT event_type FROM action_execution_events latest
                   WHERE latest.action_execution_id = ae.action_execution_id
                   ORDER BY latest.action_execution_event_id DESC LIMIT 1
               ) AS latest_event_type
        FROM action_executions ae
        JOIN action_plans ap ON ap.action_plan_id = ae.action_plan_id
        JOIN action_plan_items api ON api.action_plan_item_id = ae.action_plan_item_id
        JOIN quarantine_records qr ON qr.action_execution_id = ae.action_execution_id
        WHERE ae.execution_key = ?
        """,
        (execution_id,),
    ).fetchone()
    if row is None:
        raise QuarantineError(f"Quarantine execution {execution_id!r} does not exist.")
    return row


def _transition(
    database_path: str | Path,
    execution_id: str,
    status: str,
    event_type: str,
    actor: str,
    details: dict[str, object],
    policy: PathSafetyPolicy,
) -> None:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=policy
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _execution_by_key(connection, execution_id)
        connection.execute(
            "UPDATE action_executions SET status = ?, "
            "started_at = COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
            "WHERE action_execution_id = ?",
            (status, int(row["action_execution_id"])),
        )
        _insert_event(connection, int(row["action_execution_id"]), event_type, actor, details)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _set_pre_execution_hash(
    database_path: str | Path, execution_id: str, digest: str, policy: PathSafetyPolicy
) -> None:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=policy
    )
    try:
        row = _execution_by_key(connection, execution_id)
        connection.execute(
            "UPDATE action_executions SET pre_execution_sha256 = ? "
            "WHERE action_execution_id = ?",
            (digest, int(row["action_execution_id"])),
        )
        connection.commit()
    finally:
        connection.close()


def _finalise_quarantine(
    database_path: str | Path,
    execution_id: str,
    pre_hash: str,
    post_hash: str,
    actor: str,
    policy: PathSafetyPolicy,
    *,
    reconciled: bool = False,
) -> None:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=policy
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _execution_by_key(connection, execution_id)
        connection.execute(
            """
            UPDATE action_executions SET status = 'succeeded',
                pre_execution_sha256 = ?, post_execution_sha256 = ?,
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                failure_reason = NULL, recovery_details_json = NULL
            WHERE action_execution_id = ?
            """,
            (pre_hash, post_hash, int(row["action_execution_id"])),
        )
        connection.execute(
            """
            UPDATE quarantine_records SET state = 'quarantined',
                quarantined_at = COALESCE(
                    quarantined_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                ), last_reconciliation_state = ?
            WHERE action_execution_id = ?
            """,
            ("quarantined_verified" if reconciled else None, int(row["action_execution_id"])),
        )
        connection.execute(
            "UPDATE physical_instances SET current_observed_path = ? "
            "WHERE physical_instance_id = ?",
            (str(row["destination_path"]), int(row["original_physical_instance_id"])),
        )
        _insert_location_event(
            connection, row, "quarantined", str(row["source_path_snapshot"]),
            str(row["destination_path"]), post_hash,
        )
        _insert_event(
            connection, int(row["action_execution_id"]),
            "reconciled" if reconciled else "succeeded", actor,
            {"classification": "quarantined_verified", "sha256": post_hash},
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _finalise_restore(
    database_path: str | Path,
    execution_id: str,
    digest: str,
    actor: str,
    policy: PathSafetyPolicy,
    *,
    reconciled: bool = False,
) -> None:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=policy
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _execution_by_key(connection, execution_id)
        connection.execute(
            """
            UPDATE action_executions SET status = 'restored',
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                failure_reason = NULL, recovery_details_json = NULL
            WHERE action_execution_id = ?
            """,
            (int(row["action_execution_id"]),),
        )
        connection.execute(
            """
            UPDATE quarantine_records SET state = 'restored',
                restored_at = COALESCE(
                    restored_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                ), last_reconciliation_state = ?
            WHERE action_execution_id = ?
            """,
            ("restored_verified" if reconciled else None, int(row["action_execution_id"])),
        )
        connection.execute(
            "UPDATE physical_instances SET current_observed_path = ? "
            "WHERE physical_instance_id = ?",
            (str(row["source_path_snapshot"]), int(row["original_physical_instance_id"])),
        )
        _insert_location_event(
            connection, row, "restored", str(row["destination_path"]),
            str(row["source_path_snapshot"]), digest,
        )
        _insert_event(
            connection, int(row["action_execution_id"]),
            "reconciled" if reconciled else "restored", actor,
            {"classification": "restored_verified", "sha256": digest},
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _record_failure(
    database_path: str | Path,
    execution_id: str,
    actor: str,
    reason: str,
    *,
    recovery_required: bool,
    safety_policy: PathSafetyPolicy,
) -> None:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=safety_policy
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _execution_by_key(connection, execution_id)
        status = "recovery_required" if recovery_required else "failed"
        details = json.dumps(
            {"reason": reason, "filesystem_may_have_moved": recovery_required},
            sort_keys=True,
        )
        connection.execute(
            """
            UPDATE action_executions SET status = ?, failure_reason = ?,
                recovery_details_json = ?,
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE action_execution_id = ?
            """,
            (status, reason, details, int(row["action_execution_id"])),
        )
        if recovery_required:
            connection.execute(
                "UPDATE quarantine_records SET state = 'recovery_required' "
                "WHERE action_execution_id = ?",
                (int(row["action_execution_id"]),),
            )
        _insert_event(
            connection, int(row["action_execution_id"]), status, actor,
            json.loads(details),
        )
        connection.commit()
    except Exception:
        connection.rollback()
    finally:
        connection.close()


def _set_reconciliation(
    database_path: str | Path,
    execution_id: str,
    actor: str,
    classification: str,
    *,
    status: str,
    record_state: str,
    safety_policy: PathSafetyPolicy,
) -> None:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=safety_policy
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _execution_by_key(connection, execution_id)
        connection.execute(
            "UPDATE action_executions SET status = ?, recovery_details_json = ? "
            "WHERE action_execution_id = ?",
            (
                status, json.dumps({"classification": classification}, sort_keys=True),
                int(row["action_execution_id"]),
            ),
        )
        connection.execute(
            "UPDATE quarantine_records SET state = ?, last_reconciliation_state = ? "
            "WHERE action_execution_id = ?",
            (record_state, classification, int(row["action_execution_id"])),
        )
        _insert_event(
            connection, int(row["action_execution_id"]), "reconciled", actor,
            {"classification": classification, "filesystem_mutation": False},
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _append_event(
    database_path: str | Path,
    execution_row_id: int,
    event_type: str,
    actor: str,
    details: dict[str, object],
    policy: PathSafetyPolicy,
) -> None:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=policy
    )
    try:
        _insert_event(connection, execution_row_id, event_type, actor, details)
        connection.commit()
    finally:
        connection.close()


def _insert_event(
    connection: sqlite3.Connection,
    execution_row_id: int,
    event_type: str,
    actor: str,
    details: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO action_execution_events(
            event_key, action_execution_id, event_type, actor_identifier, details_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            stable_key("m19-execution-event-v1", execution_row_id, event_type, str(uuid4())),
            execution_row_id, event_type, actor,
            json.dumps(details, ensure_ascii=False, sort_keys=True),
        ),
    )


def _insert_location_event(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    action: str,
    from_path: str,
    to_path: str,
    digest: str,
) -> None:
    existing = connection.execute(
        "SELECT 1 FROM physical_instance_location_events "
        "WHERE action_execution_id = ? AND location_action = ?",
        (int(row["action_execution_id"]), action),
    ).fetchone()
    if existing is not None:
        return
    connection.execute(
        """
        INSERT INTO physical_instance_location_events(
            event_key, action_execution_id, physical_instance_id, location_action,
            from_path, to_path, verified_sha256, verified_size_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stable_key("m19-location-event-v1", str(row["execution_key"]), action),
            int(row["action_execution_id"]),
            int(row["original_physical_instance_id"]), action, from_path, to_path,
            digest, int(row["expected_size_bytes"]),
        ),
    )


def _serialise_execution(
    row: sqlite3.Row,
    events: list[dict[str, object]],
    locations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "execution_id": str(row["execution_key"]),
        "plan_id": str(row["plan_key"]),
        "item_id": str(row["item_key"]),
        "action": "quarantine",
        "status": str(row["status"]),
        "quarantine_state": str(row["record_state"]),
        "actor": str(row["actor_identifier"]),
        "source_path": str(row["source_path_snapshot"]),
        "destination_path": str(row["destination_path"]),
        "quarantine_root": str(row["quarantine_root"]),
        "physical_instance_id": int(row["original_physical_instance_id"]),
        "content_identity_id": int(row["content_identity_id"]),
        "expected_sha256": str(row["expected_sha256"]),
        "pre_execution_sha256": row["pre_execution_sha256"],
        "post_execution_sha256": row["post_execution_sha256"],
        "size_bytes": int(row["expected_size_bytes"]),
        "requested_at": str(row["requested_at"]),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "failure_reason": row["failure_reason"],
        "last_reconciliation_state": row["last_reconciliation_state"],
        "events": events,
        "location_history": locations,
        "delete_available": False,
        "general_execution_available": False,
    }


def _execution_destination(root: str, plan_key: str, item_key: str, source: str) -> str:
    plan_token = plan_key.rsplit(":", 1)[-1][:16]
    item_token = item_key.rsplit(":", 1)[-1][:16]
    basename = ntpath.basename(source)
    return ntpath.normpath(
        ntpath.join(root, f"plan-{plan_token}", f"item-{item_token}", basename)
    )


def _explicit_root(root: str | Path, policy: PathSafetyPolicy) -> str:
    raw = os.fspath(root).replace("/", "\\")
    drive, tail = ntpath.splitdrive(raw)
    if not ((len(drive) == 2 and tail.startswith("\\")) or raw.startswith("\\\\")):
        raise QuarantineError("Quarantine root must be an explicit absolute Windows path.")
    if ".." in tail.split("\\"):
        raise QuarantineError("Quarantine root cannot contain parent traversal.")
    result = policy.check_path(raw, intent=PathIntent.WRITE)
    if not result.allowed:
        raise QuarantineError(f"Unsafe quarantine root ({result.code}): {result.reason}")
    assert result.assessed_path is not None
    normal = ntpath.normpath(result.assessed_path)
    path = Path(normal)
    if not path.is_dir():
        raise QuarantineError("Explicit quarantine root must already exist as a directory.")
    return normal


def _require_same_volume(source: Path, destination_root: Path) -> None:
    try:
        if source.stat().st_dev != destination_root.stat().st_dev:
            raise QuarantineError(
                "Cross-volume quarantine/restore is unsupported in M19; no copy-delete fallback exists."
            )
    except OSError as exc:
        raise QuarantineError(f"Volume identity could not be verified: {exc}") from exc


def _safe_file_exists(path: Path, policy: PathSafetyPolicy) -> bool:
    result = policy.check_path(str(path), intent=PathIntent.READ)
    if not result.allowed:
        return False
    try:
        return path.is_file()
    except OSError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _required(value: str, label: str) -> str:
    checked = value.strip()
    if not checked:
        raise QuarantineError(f"{label} must be explicit.")
    return checked
