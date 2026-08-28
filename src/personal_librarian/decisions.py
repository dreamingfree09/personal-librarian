"""Append-only owner review decisions and deterministic current-state derivation."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import DecisionError
from personal_librarian.catalogue.models import CanonicalScope, ReviewContextType
from personal_librarian.safety import PathSafetyPolicy

SCOPES = tuple(scope.value for scope in CanonicalScope)
CONTEXT_TYPES = tuple(context.value for context in ReviewContextType)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _required_text(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise DecisionError(f"{label} must be explicit and non-empty.")
    return text


def _scope(value: str) -> str:
    try:
        return CanonicalScope(value).value
    except ValueError as exc:
        raise DecisionError(f"Unsupported canonical scope: {value!r}.") from exc


def _context_type(value: str) -> str:
    try:
        return ReviewContextType(value).value
    except ValueError as exc:
        raise DecisionError(f"Unsupported review context type: {value!r}.") from exc


def _resolve_context(
    connection: sqlite3.Connection,
    context_type: str,
    context_id: int,
) -> None:
    if context_id < 1:
        raise DecisionError("Review context ID must be positive.")
    if context_type == ReviewContextType.EXACT.value:
        row = connection.execute(
            "SELECT COUNT(*) FROM physical_instances WHERE content_identity_id = ?",
            (context_id,),
        ).fetchone()
        if row is None or int(row[0]) < 2:
            raise DecisionError(
                f"Exact review context {context_id} is not a content identity with multiple instances."
            )
        return
    row = connection.execute(
        "SELECT 1 FROM similarity_groups WHERE similarity_group_id = ?",
        (context_id,),
    ).fetchone()
    if row is None:
        raise DecisionError(f"Similarity review context {context_id} does not exist.")


def _physical_in_context(
    connection: sqlite3.Connection,
    context_type: str,
    context_id: int,
    physical_instance_id: int,
) -> bool:
    if context_type == ReviewContextType.EXACT.value:
        query = (
            "SELECT 1 FROM physical_instances "
            "WHERE physical_instance_id = ? AND content_identity_id = ?"
        )
        parameters = (physical_instance_id, context_id)
    else:
        query = """
            SELECT 1
            FROM physical_instances pi
            JOIN similarity_group_memberships sgm
              ON sgm.content_identity_id = pi.content_identity_id
            WHERE pi.physical_instance_id = ? AND sgm.similarity_group_id = ?
        """
        parameters = (physical_instance_id, context_id)
    return connection.execute(query, parameters).fetchone() is not None


def _content_in_context(
    connection: sqlite3.Connection,
    context_type: str,
    context_id: int,
    content_identity_id: int,
) -> bool:
    if context_type == ReviewContextType.EXACT.value:
        return content_identity_id == context_id
    return connection.execute(
        "SELECT 1 FROM similarity_group_memberships "
        "WHERE similarity_group_id = ? AND content_identity_id = ?",
        (context_id, content_identity_id),
    ).fetchone() is not None


def _context_columns(context_type: str, context_id: int) -> tuple[int | None, int | None]:
    if context_type == ReviewContextType.EXACT.value:
        return context_id, None
    return None, context_id


def _event_rows(
    connection: sqlite3.Connection,
    *,
    context_type: str | None = None,
    context_id: int | None = None,
) -> list[sqlite3.Row]:
    if context_type is None and context_id is not None:
        raise DecisionError("Context type is required with a context ID.")
    where = ["de.workflow_action IS NOT NULL"]
    parameters: list[object] = []
    if context_type is not None:
        context_type = _context_type(context_type)
        if context_id is None:
            raise DecisionError("Context ID is required with a context type.")
        column = (
            "de.exact_content_identity_id"
            if context_type == ReviewContextType.EXACT.value
            else "de.similarity_group_id"
        )
        where.append(f"{column} = ?")
        parameters.append(context_id)
    return connection.execute(
        f"""
        SELECT de.*,
               related.decision_key AS related_event_key,
               secondary.decision_key AS secondary_related_event_key
        FROM decision_events de
        LEFT JOIN decision_events related
          ON related.decision_event_id = de.related_decision_event_id
        LEFT JOIN decision_events secondary
          ON secondary.decision_event_id = de.secondary_related_decision_event_id
        WHERE {' AND '.join(where)}
        ORDER BY de.decision_event_id
        """,
        parameters,
    ).fetchall()


def _derive_scope(rows: Iterable[sqlite3.Row], scope: str) -> dict[str, object]:
    nominations: dict[str, dict[str, object]] = {}
    approval_to_nomination: dict[str, str] = {}
    current: dict[str, object] | None = None
    fallback_status = "pending"
    latest_fallback_event = 0
    had_events = False
    had_supersession = False

    for row in rows:
        if str(row["canonical_scope"]) != scope:
            continue
        had_events = True
        action = str(row["workflow_action"])
        event_key = str(row["decision_key"])
        event_id = int(row["decision_event_id"])
        physical_id = row["subject_physical_instance_id"]
        if action == "nominate":
            nominations[event_key] = {
                "nomination_event_id": event_key,
                "physical_instance_id": int(physical_id),
                "status": "pending",
                "owner": str(row["actor_identifier"]),
                "reason": row["reason"],
                "occurred_at": str(row["occurred_at"]),
            }
            if current is None and event_id >= latest_fallback_event:
                fallback_status = "pending"
                latest_fallback_event = event_id
        elif action in {"approve", "reject"}:
            nomination_key = str(row["related_event_key"])
            nomination = nominations.get(nomination_key)
            if nomination is None:
                continue
            nomination["status"] = "approved" if action == "approve" else "rejected"
            nomination["terminal_event_id"] = event_key
            if action == "approve":
                approval_to_nomination[event_key] = nomination_key
                current = {
                    "physical_instance_id": nomination["physical_instance_id"],
                    "nomination_event_id": nomination_key,
                    "approval_event_id": event_key,
                }
            elif current is None and event_id >= latest_fallback_event:
                fallback_status = "rejected"
                latest_fallback_event = event_id
        elif action == "supersede":
            nomination_key = str(row["related_event_key"])
            prior_approval_key = str(row["secondary_related_event_key"])
            nomination = nominations.get(nomination_key)
            if nomination is None:
                continue
            prior_nomination_key = approval_to_nomination.get(prior_approval_key)
            if prior_nomination_key in nominations:
                nominations[prior_nomination_key]["status"] = "superseded"
                nominations[prior_nomination_key]["terminal_event_id"] = event_key
            nomination["status"] = "approved"
            nomination["terminal_event_id"] = event_key
            approval_to_nomination[event_key] = nomination_key
            current = {
                "physical_instance_id": nomination["physical_instance_id"],
                "nomination_event_id": nomination_key,
                "approval_event_id": event_key,
                "superseded_approval_event_id": prior_approval_key,
            }
            had_supersession = True
        elif action == "abstain":
            related_key = row["related_event_key"]
            if (
                current is not None
                and related_key is not None
                and str(current["approval_event_id"]) == str(related_key)
            ):
                prior_nomination_key = approval_to_nomination.get(str(related_key))
                if prior_nomination_key in nominations:
                    nominations[prior_nomination_key]["status"] = "withdrawn"
                    nominations[prior_nomination_key]["terminal_event_id"] = event_key
                current = None
            if current is None and event_id >= latest_fallback_event:
                fallback_status = "abstained"
                latest_fallback_event = event_id

    pending = [
        nomination
        for nomination in nominations.values()
        if nomination["status"] == "pending"
    ]
    if current is not None:
        status = "approved"
    elif fallback_status == "abstained":
        status = "abstained"
    elif had_supersession:
        status = "reopened"
    else:
        status = fallback_status
    return {
        "status": status,
        "approved": current,
        "pending_nominations": pending,
        "nominations": list(nominations.values()),
        "has_events": had_events,
    }


def derive_context_state_from_rows(rows: list[sqlite3.Row]) -> dict[str, object]:
    scopes = {scope: _derive_scope(rows, scope) for scope in SCOPES}
    statuses = [str(scopes[scope]["status"]) for scope in SCOPES]
    has_events = any(bool(scopes[scope]["has_events"]) for scope in SCOPES)
    if not has_events:
        review_status = "pending"
    elif all(status == "abstained" for status in statuses):
        review_status = "abstained"
    elif all(status in {"approved", "abstained"} for status in statuses):
        review_status = "decided"
    elif any(status == "reopened" for status in statuses):
        review_status = "reopened"
    else:
        review_status = "partially_reviewed"
    return {"review_status": review_status, "scopes": scopes}


def derive_context_state(
    connection: sqlite3.Connection,
    context_type: str,
    context_id: int,
) -> dict[str, object]:
    return derive_context_state_from_rows(
        _event_rows(connection, context_type=context_type, context_id=context_id)
    )


def load_context_states(
    connection: sqlite3.Connection,
) -> dict[tuple[str, int], dict[str, object]]:
    grouped: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
    for row in _event_rows(connection):
        if row["exact_content_identity_id"] is not None:
            key = (ReviewContextType.EXACT.value, int(row["exact_content_identity_id"]))
        else:
            key = (ReviewContextType.SIMILAR.value, int(row["similarity_group_id"]))
        grouped[key].append(row)
    return {key: derive_context_state_from_rows(rows) for key, rows in grouped.items()}


def _default_state() -> dict[str, object]:
    return derive_context_state_from_rows([])


def _event_by_key(connection: sqlite3.Connection, event_key: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM decision_events WHERE decision_key = ? AND workflow_action IS NOT NULL",
        (event_key,),
    ).fetchone()
    if row is None:
        raise DecisionError(f"Decision event {event_key!r} does not exist.")
    return row


def _row_context(row: sqlite3.Row) -> tuple[str, int]:
    if row["exact_content_identity_id"] is not None:
        return ReviewContextType.EXACT.value, int(row["exact_content_identity_id"])
    if row["similarity_group_id"] is not None:
        return ReviewContextType.SIMILAR.value, int(row["similarity_group_id"])
    raise DecisionError("Referenced event is not an M17 workflow event.")


def _insert_event(
    connection: sqlite3.Connection,
    *,
    event_key: str,
    scope: str,
    action: str,
    event_type: str,
    owner: str,
    context_type: str,
    context_id: int,
    physical_instance_id: int | None = None,
    content_identity_id: int | None = None,
    related_event_id: int | None = None,
    secondary_related_event_id: int | None = None,
    owner_approved: int,
    reason: str | None = None,
) -> dict[str, object]:
    exact_id, similar_id = _context_columns(context_type, context_id)
    cursor = connection.execute(
        """
        INSERT INTO decision_events(
            decision_key, canonical_scope, event_type,
            subject_content_identity_id, subject_physical_instance_id,
            related_decision_event_id, secondary_related_decision_event_id,
            actor_type, actor_identifier, owner_approved, reason, occurred_at,
            workflow_action, exact_content_identity_id, similarity_group_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'owner', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_key,
            scope,
            event_type,
            content_identity_id,
            physical_instance_id,
            related_event_id,
            secondary_related_event_id,
            owner,
            owner_approved,
            reason,
            _now(),
            action,
            exact_id,
            similar_id,
        ),
    )
    return {
        "decision_event_id": int(cursor.lastrowid),
        "event_id": event_key,
        "action": action,
        "context_type": context_type,
        "context_id": context_id,
        "canonical_scope": scope,
        "physical_instance_id": physical_instance_id,
        "content_identity_id": content_identity_id,
        "owner": owner,
    }


def nominate(
    *,
    database_path: str | Path,
    event_id: str,
    context_type: str,
    context_id: int,
    physical_instance_id: int,
    canonical_scope: str,
    owner: str,
    reason: str | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        connection.execute("BEGIN IMMEDIATE")
        context_type = _context_type(context_type)
        scope = _scope(canonical_scope)
        event_id = _required_text(event_id, "Event ID")
        owner = _required_text(owner, "Owner")
        _resolve_context(connection, context_type, context_id)
        if not _physical_in_context(connection, context_type, context_id, physical_instance_id):
            raise DecisionError("Physical instance is not a member of the review context.")
        state = derive_context_state(connection, context_type, context_id)
        pending = state["scopes"][scope]["pending_nominations"]
        if any(int(item["physical_instance_id"]) == physical_instance_id for item in pending):
            raise DecisionError("This physical instance already has a pending nomination in scope.")
        result = _insert_event(
            connection,
            event_key=event_id,
            scope=scope,
            action="nominate",
            event_type="proposal",
            owner=owner,
            context_type=context_type,
            context_id=context_id,
            physical_instance_id=physical_instance_id,
            owner_approved=0,
            reason=reason,
        )
        connection.commit()
        result["current_state"] = derive_context_state(connection, context_type, context_id)
        return result
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise DecisionError(f"Decision event could not be recorded: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _terminal_nomination_event(
    *,
    database_path: str | Path,
    event_id: str,
    nomination_id: str,
    physical_instance_id: int,
    canonical_scope: str,
    owner: str,
    action: str,
    reason: str | None,
    prior_approval_id: str | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        connection.execute("BEGIN IMMEDIATE")
        event_id = _required_text(event_id, "Event ID")
        owner = _required_text(owner, "Owner")
        scope = _scope(canonical_scope)
        nomination = _event_by_key(connection, nomination_id)
        if str(nomination["workflow_action"]) != "nominate":
            raise DecisionError("Referenced event is not a nomination.")
        context_type, context_id = _row_context(nomination)
        if str(nomination["canonical_scope"]) != scope:
            raise DecisionError("Canonical scope does not match the nomination.")
        if int(nomination["subject_physical_instance_id"]) != physical_instance_id:
            raise DecisionError("Physical instance does not match the nomination.")
        state = derive_context_state(connection, context_type, context_id)
        scope_state = state["scopes"][scope]
        nomination_states = {
            str(item["nomination_event_id"]): str(item["status"])
            for item in scope_state["nominations"]
        }
        if nomination_states.get(nomination_id) != "pending":
            raise DecisionError("Only a pending nomination can receive this event.")

        secondary_id = None
        if action == "approve":
            if scope_state["approved"] is not None:
                raise DecisionError(
                    "Scope already has an approved canonical; use explicit supersession."
                )
            event_type = "approval"
        elif action == "reject":
            event_type = "rejection"
        elif action == "supersede":
            prior_key = _required_text(prior_approval_id or "", "Prior approval ID")
            prior = _event_by_key(connection, prior_key)
            current = scope_state["approved"]
            if current is None or str(current["approval_event_id"]) != prior_key:
                raise DecisionError("Prior approval is not the current approval for this context/scope.")
            if _row_context(prior) != (context_type, context_id):
                raise DecisionError("Prior approval belongs to another review context.")
            if str(prior["canonical_scope"]) != scope:
                raise DecisionError("Prior approval belongs to another canonical scope.")
            if int(current["physical_instance_id"]) == physical_instance_id:
                raise DecisionError("Supersession must select a different physical instance.")
            secondary_id = int(prior["decision_event_id"])
            event_type = "supersession"
        else:
            raise DecisionError(f"Unsupported terminal action: {action!r}.")

        result = _insert_event(
            connection,
            event_key=event_id,
            scope=scope,
            action=action,
            event_type=event_type,
            owner=owner,
            context_type=context_type,
            context_id=context_id,
            physical_instance_id=physical_instance_id,
            related_event_id=int(nomination["decision_event_id"]),
            secondary_related_event_id=secondary_id,
            owner_approved=1,
            reason=reason,
        )
        connection.commit()
        result["current_state"] = derive_context_state(connection, context_type, context_id)
        return result
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise DecisionError(f"Decision event could not be recorded: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def approve(**kwargs: object) -> dict[str, object]:
    return _terminal_nomination_event(action="approve", **kwargs)


def reject(**kwargs: object) -> dict[str, object]:
    return _terminal_nomination_event(action="reject", **kwargs)


def supersede(**kwargs: object) -> dict[str, object]:
    return _terminal_nomination_event(action="supersede", **kwargs)


def abstain(
    *,
    database_path: str | Path,
    event_id: str,
    context_type: str,
    context_id: int,
    content_identity_id: int,
    canonical_scope: str,
    owner: str,
    reason: str | None = None,
    prior_approval_id: str | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        connection.execute("BEGIN IMMEDIATE")
        context_type = _context_type(context_type)
        scope = _scope(canonical_scope)
        event_id = _required_text(event_id, "Event ID")
        owner = _required_text(owner, "Owner")
        _resolve_context(connection, context_type, context_id)
        if not _content_in_context(connection, context_type, context_id, content_identity_id):
            raise DecisionError("Content identity is not a member of the review context.")
        state = derive_context_state(connection, context_type, context_id)
        current = state["scopes"][scope]["approved"]
        related_id = None
        if current is not None:
            prior_key = _required_text(prior_approval_id or "", "Prior approval ID")
            if str(current["approval_event_id"]) != prior_key:
                raise DecisionError(
                    "Prior approval is not the current approval for this context/scope."
                )
            prior = _event_by_key(connection, prior_key)
            if _row_context(prior) != (context_type, context_id):
                raise DecisionError("Prior approval belongs to another review context.")
            if str(prior["canonical_scope"]) != scope:
                raise DecisionError("Prior approval belongs to another canonical scope.")
            related_id = int(prior["decision_event_id"])
        elif prior_approval_id is not None:
            raise DecisionError("This context/scope has no current approval to withdraw.")
        result = _insert_event(
            connection,
            event_key=event_id,
            scope=scope,
            action="abstain",
            event_type="withdrawal",
            owner=owner,
            context_type=context_type,
            context_id=context_id,
            content_identity_id=content_identity_id,
            related_event_id=related_id,
            owner_approved=1,
            reason=reason,
        )
        connection.commit()
        result["current_state"] = derive_context_state(connection, context_type, context_id)
        return result
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise DecisionError(f"Decision event could not be recorded: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def decision_history(
    *,
    database_path: str | Path,
    context_type: str | None = None,
    context_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> list[dict[str, object]]:
    if limit < 1 or offset < 0:
        raise DecisionError("History limit must be positive and offset must be non-negative.")
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        rows = _event_rows(connection, context_type=context_type, context_id=context_id)
        result = []
        for row in rows[offset : offset + limit]:
            row_context_type, row_context_id = _row_context(row)
            result.append(
                {
                    "event_id": str(row["decision_key"]),
                    "sequence": int(row["decision_event_id"]),
                    "action": str(row["workflow_action"]),
                    "context_type": row_context_type,
                    "context_id": row_context_id,
                    "canonical_scope": str(row["canonical_scope"]),
                    "physical_instance_id": row["subject_physical_instance_id"],
                    "content_identity_id": row["subject_content_identity_id"],
                    "related_event_id": row["related_event_key"],
                    "secondary_related_event_id": row["secondary_related_event_key"],
                    "owner": str(row["actor_identifier"]),
                    "reason": row["reason"],
                    "occurred_at": str(row["occurred_at"]),
                    "recorded_at": str(row["recorded_at"]),
                }
            )
        return result
    finally:
        connection.close()


def current_decisions(
    *,
    database_path: str | Path,
    context_type: str | None = None,
    context_id: int | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> list[dict[str, object]]:
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        states = load_context_states(connection)
        if context_type is not None:
            checked_type = _context_type(context_type)
            if context_id is None:
                raise DecisionError("Context ID is required with a context type.")
            _resolve_context(connection, checked_type, context_id)
            key = (checked_type, context_id)
            states = {key: states.get(key, _default_state())}
        elif context_id is not None:
            raise DecisionError("Context type is required with a context ID.")
        result: list[dict[str, object]] = []
        for (item_type, item_id), state in sorted(states.items()):
            for scope in SCOPES:
                scope_state = state["scopes"][scope]
                result.append(
                    {
                        "context_type": item_type,
                        "context_id": item_id,
                        "canonical_scope": scope,
                        "status": scope_state["status"],
                        "approved": scope_state["approved"],
                        "pending_nominations": scope_state["pending_nominations"],
                    }
                )
        return result
    finally:
        connection.close()
