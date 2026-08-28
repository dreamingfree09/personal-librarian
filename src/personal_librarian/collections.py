"""Owner-managed schema-10 cross-year Collections and audited memberships."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import CollectionError
from personal_librarian.catalogue.migrations import read_schema_version
from personal_librarian.safety import PathSafetyPolicy

COLLECTION_SCHEMA_VERSION = 10
MAX_PAGE_SIZE = 500


def create_collection(
    *, database_path: str | Path, name: str, actor: str, action_id: str,
    description: str | None = None, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    checked_name = _text(name, "Collection name", 200)
    checked_description = _optional_text(description, "Description", 4000)
    evidence = _action_evidence(actor, action_id, reason, provenance)
    with _write_connection(database_path, safety_policy) as connection:
        replay = _replayed_action(
            connection, evidence, "create",
            {"name": checked_name, "description": checked_description},
        )
        if replay is not None:
            return _collection_result(
                _collection_by_id(connection, int(replay["collection_id"])), connection
            ) | {"changed": False, "replayed": True}
        collection_uuid = str(uuid.uuid4())
        cursor = connection.execute(
            "INSERT INTO collections(collection_uuid,name,description,collection_kind,state,"
            "created_by,provenance_type,provenance) "
            "VALUES(?,?,?,'manual','active',?,'owner',?)",
            (collection_uuid, checked_name, checked_description, evidence.actor,
             evidence.provenance),
        )
        collection_id = int(cursor.lastrowid)
        _append_event(
            connection, "collection_created", collection_id=collection_id,
            evidence=evidence,
            details={"operation": "create", "name": checked_name,
                     "description": checked_description, "state": "active"},
        )
        return _collection_result(
            _collection_by_id(connection, collection_id), connection
        ) | {"changed": True, "replayed": False}


def rename_collection(
    *, database_path: str | Path, collection_uuid: str, name: str,
    actor: str, action_id: str, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    checked_uuid = _text(collection_uuid, "Collection UUID", 200)
    checked_name = _text(name, "Collection name", 200)
    evidence = _action_evidence(actor, action_id, reason, provenance)
    with _write_connection(database_path, safety_policy) as connection:
        collection = _collection(connection, checked_uuid)
        replay = _replayed_action(
            connection, evidence, "rename",
            {"collection_uuid": checked_uuid, "after_name": checked_name},
        )
        if replay is not None:
            return _collection_result(collection, connection) | {
                "changed": False, "replayed": True
            }
        if collection["state"] != "active":
            raise CollectionError("Archived Collections are read-only; restore first.")
        before = str(collection["name"])
        if before == checked_name:
            return _collection_result(collection, connection) | {
                "changed": False, "replayed": False
            }
        connection.execute(
            "UPDATE collections SET name=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE collection_id=?", (checked_name, int(collection["collection_id"])),
        )
        _append_event(
            connection, "collection_renamed",
            collection_id=int(collection["collection_id"]), evidence=evidence,
            details={"operation": "rename", "collection_uuid": checked_uuid,
                     "before_name": before, "after_name": checked_name},
        )
        return _collection_result(
            _collection(connection, checked_uuid), connection
        ) | {"changed": True, "replayed": False}


def archive_collection(
    *, database_path: str | Path, collection_uuid: str, actor: str,
    action_id: str, reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    return _set_collection_state(
        database_path=database_path, collection_uuid=collection_uuid, actor=actor,
        action_id=action_id, reason=reason, provenance=provenance,
        safety_policy=safety_policy, target_state="archived",
    )


def restore_collection(
    *, database_path: str | Path, collection_uuid: str, actor: str,
    action_id: str, reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    return _set_collection_state(
        database_path=database_path, collection_uuid=collection_uuid, actor=actor,
        action_id=action_id, reason=reason, provenance=provenance,
        safety_policy=safety_policy, target_state="active",
    )


def add_content_to_collection(
    *, database_path: str | Path, collection_uuid: str, content_identity_id: int,
    actor: str, action_id: str, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    return _set_membership(
        database_path=database_path, collection_uuid=collection_uuid,
        content_identity_id=content_identity_id, actor=actor, action_id=action_id,
        reason=reason, provenance=provenance, safety_policy=safety_policy,
        operation="add", target_state="active", require_existing=False,
    )


def remove_content_from_collection(
    *, database_path: str | Path, collection_uuid: str, content_identity_id: int,
    actor: str, action_id: str, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    return _set_membership(
        database_path=database_path, collection_uuid=collection_uuid,
        content_identity_id=content_identity_id, actor=actor, action_id=action_id,
        reason=reason, provenance=provenance, safety_policy=safety_policy,
        operation="remove", target_state="removed", require_existing=False,
    )


def restore_content_to_collection(
    *, database_path: str | Path, collection_uuid: str, content_identity_id: int,
    actor: str, action_id: str, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    return _set_membership(
        database_path=database_path, collection_uuid=collection_uuid,
        content_identity_id=content_identity_id, actor=actor, action_id=action_id,
        reason=reason, provenance=provenance, safety_policy=safety_policy,
        operation="restore_member", target_state="active", require_existing=True,
    )


def list_collections(
    *, database_path: str | Path, state: str = "active", limit: int = 100,
    offset: int = 0, safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    checked_state = _state_filter(state)
    limit, offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        clause, parameters = (
            ("", ()) if checked_state == "all" else ("WHERE c.state=?", (checked_state,))
        )
        rows = connection.execute(
            f"""
            WITH member_counts AS (
                SELECT collection_id,
                       SUM(membership_state='active') AS active_members,
                       SUM(membership_state='removed') AS removed_members
                FROM collection_memberships GROUP BY collection_id
            ), name_counts AS (
                SELECT lower(name) AS name_key,COUNT(*) AS duplicate_name_count
                FROM collections GROUP BY lower(name)
            )
            SELECT c.*,nc.duplicate_name_count,
                   COALESCE(mc.active_members,0) AS active_member_count,
                   COALESCE(mc.removed_members,0) AS removed_member_count
            FROM collections c
            JOIN name_counts nc ON nc.name_key=lower(c.name)
            LEFT JOIN member_counts mc ON mc.collection_id=c.collection_id
            {clause}
            ORDER BY c.name COLLATE NOCASE,c.collection_id LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        total = int(connection.execute(
            f"SELECT COUNT(*) FROM collections c {clause}", parameters
        ).fetchone()[0])
        return {"collections": [dict(row) for row in rows], "state": checked_state,
                "total_matching": total, "limit": limit, "offset": offset}


def get_collection(
    *, database_path: str | Path, collection_uuid: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    with _read_connection(database_path, safety_policy) as connection:
        return _collection_result(
            _collection(connection, _text(collection_uuid, "Collection UUID", 200)),
            connection,
        )


def list_collection_members(
    *, database_path: str | Path, collection_uuid: str,
    include_removed: bool = False, limit: int = 100, offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    limit, offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        collection = _collection(
            connection, _text(collection_uuid, "Collection UUID", 200)
        )
        state_clause = "" if include_removed else "AND cm.membership_state='active'"
        rows = connection.execute(
            f"""
            SELECT cm.*,ci.identity_key,
                   (SELECT COUNT(*) FROM physical_instances copies
                    WHERE copies.content_identity_id=ci.content_identity_id)
                       AS physical_instance_count,
                   representative.physical_instance_id AS representative_physical_instance_id,
                   representative.raw_relative_path AS representative_raw_relative_path,
                   representative.display_path AS representative_display_path,
                   representative.current_observed_path AS representative_current_observed_path,
                   representative.extension AS representative_extension,
                   representative.size_bytes AS representative_size_bytes,
                   representative.observed_created_at AS representative_observed_created_at,
                   representative.observed_modified_at AS representative_observed_modified_at,
                   source.display_name AS representative_source,
                   preferred.status AS preferred_status,
                   preferred.selected_precision,preferred.selected_year,
                   preferred.selected_month,preferred.selected_day,
                   preferred.selected_hour,preferred.selected_minute,
                   preferred.selected_second,preferred.selected_timezone_state,
                   preferred.selected_utc_offset_minutes
            FROM collection_memberships cm
            JOIN content_identities ci ON ci.content_identity_id=cm.content_identity_id
            LEFT JOIN physical_instances representative
              ON representative.physical_instance_id=(
                SELECT MIN(candidate.physical_instance_id) FROM physical_instances candidate
                WHERE candidate.content_identity_id=ci.content_identity_id
              )
            LEFT JOIN sources source ON source.source_id=representative.source_id
            LEFT JOIN content_preferred_dates preferred
              ON preferred.content_identity_id=ci.content_identity_id
            WHERE cm.collection_id=? {state_clause}
            ORDER BY cm.collection_membership_id LIMIT ? OFFSET ?
            """,
            (int(collection["collection_id"]), limit, offset),
        ).fetchall()
        total = int(connection.execute(
            f"SELECT COUNT(*) FROM collection_memberships cm WHERE cm.collection_id=? "
            f"{state_clause}", (int(collection["collection_id"]),),
        ).fetchone()[0])
        return {"collection_uuid": str(collection["collection_uuid"]),
                "members": [dict(row) for row in rows], "include_removed": include_removed,
                "total_matching": total, "limit": limit, "offset": offset}


def list_collections_for_content(
    *, database_path: str | Path, content_identity_id: int,
    include_removed: bool = False, limit: int = 100, offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    content_identity_id = _positive_id(content_identity_id, "Content identity ID")
    limit, offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        _content_exists(connection, content_identity_id)
        state_clause = "" if include_removed else "AND cm.membership_state='active'"
        rows = connection.execute(
            f"""
            WITH member_counts AS (
                SELECT collection_id,SUM(membership_state='active') AS active_member_count,
                       SUM(membership_state='removed') AS removed_member_count
                FROM collection_memberships GROUP BY collection_id
            )
            SELECT c.*,cm.collection_membership_id,cm.membership_state,
                   cm.created_at AS membership_created_at,cm.ended_at,
                   COALESCE(mc.active_member_count,0) AS active_member_count,
                   COALESCE(mc.removed_member_count,0) AS removed_member_count
            FROM collection_memberships cm JOIN collections c ON c.collection_id=cm.collection_id
            LEFT JOIN member_counts mc ON mc.collection_id=c.collection_id
            WHERE cm.content_identity_id=? {state_clause}
            ORDER BY c.name COLLATE NOCASE,c.collection_id LIMIT ? OFFSET ?
            """,
            (content_identity_id, limit, offset),
        ).fetchall()
        total = int(connection.execute(
            f"SELECT COUNT(*) FROM collection_memberships cm "
            f"WHERE cm.content_identity_id=? {state_clause}", (content_identity_id,),
        ).fetchone()[0])
        return {"content_identity_id": content_identity_id,
                "collections": [dict(row) for row in rows],
                "include_removed": include_removed, "total_matching": total,
                "limit": limit, "offset": offset}


def collection_history(
    *, database_path: str | Path, collection_uuid: str,
    limit: int = 100, offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    limit, offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        collection = _collection(
            connection, _text(collection_uuid, "Collection UUID", 200)
        )
        collection_id = int(collection["collection_id"])
        rows = connection.execute(
            "SELECT * FROM organisation_events WHERE collection_id=? "
            "ORDER BY organisation_event_id DESC LIMIT ? OFFSET ?",
            (collection_id, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(str(item.pop("details_json")))
            items.append(item)
        total = int(connection.execute(
            "SELECT COUNT(*) FROM organisation_events WHERE collection_id=?",
            (collection_id,),
        ).fetchone()[0])
        return {"collection_uuid": str(collection["collection_uuid"]), "history": items,
                "total_matching": total, "limit": limit, "offset": offset}


@dataclass(frozen=True, slots=True)
class _ActionEvidence:
    actor: str
    action_id: str
    reason: str | None
    provenance: str


def _set_collection_state(
    *, database_path: str | Path, collection_uuid: str, actor: str,
    action_id: str, target_state: str, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, object]:
    checked_uuid = _text(collection_uuid, "Collection UUID", 200)
    evidence = _action_evidence(actor, action_id, reason, provenance)
    operation = "archive" if target_state == "archived" else "restore"
    with _write_connection(database_path, safety_policy) as connection:
        collection = _collection(connection, checked_uuid)
        replay = _replayed_action(
            connection, evidence, operation, {"collection_uuid": checked_uuid}
        )
        if replay is not None:
            return _collection_result(collection, connection) | {
                "changed": False, "replayed": True
            }
        before = str(collection["state"])
        if before == target_state:
            return _collection_result(collection, connection) | {
                "changed": False, "replayed": False
            }
        archived = "strftime('%Y-%m-%dT%H:%M:%fZ','now')" if target_state == "archived" else "NULL"
        connection.execute(
            f"UPDATE collections SET state=?,archived_at={archived},"
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE collection_id=?",
            (target_state, int(collection["collection_id"])),
        )
        _append_event(
            connection, f"collection_{'archived' if target_state == 'archived' else 'restored'}",
            collection_id=int(collection["collection_id"]), evidence=evidence,
            details={"operation": operation, "collection_uuid": checked_uuid,
                     "before_state": before, "after_state": target_state},
        )
        return _collection_result(
            _collection(connection, checked_uuid), connection
        ) | {"changed": True, "replayed": False}


def _set_membership(
    *, database_path: str | Path, collection_uuid: str, content_identity_id: int,
    actor: str, action_id: str, reason: str | None, provenance: str,
    safety_policy: PathSafetyPolicy | None, operation: str, target_state: str,
    require_existing: bool,
) -> dict[str, object]:
    checked_uuid = _text(collection_uuid, "Collection UUID", 200)
    content_identity_id = _positive_id(content_identity_id, "Content identity ID")
    evidence = _action_evidence(actor, action_id, reason, provenance)
    with _write_connection(database_path, safety_policy) as connection:
        collection = _collection(connection, checked_uuid)
        _content_exists(connection, content_identity_id)
        replay = _replayed_action(
            connection, evidence, operation,
            {"collection_uuid": checked_uuid, "content_identity_id": content_identity_id},
        )
        if replay is not None:
            membership = connection.execute(
                "SELECT * FROM collection_memberships WHERE collection_id=? "
                "AND content_identity_id=?",
                (int(collection["collection_id"]), content_identity_id),
            ).fetchone()
            return _membership_result(collection, membership, content_identity_id) | {
                "changed": False, "replayed": True
            }
        if collection["state"] != "active":
            raise CollectionError("Archived Collections reject membership mutation.")
        membership = connection.execute(
            "SELECT * FROM collection_memberships WHERE collection_id=? AND content_identity_id=?",
            (int(collection["collection_id"]), content_identity_id),
        ).fetchone()
        if membership is None:
            if require_existing:
                raise CollectionError("Removed Collection membership does not exist.")
            if target_state == "removed":
                return _membership_result(collection, None, content_identity_id) | {
                    "changed": False, "replayed": False
                }
            cursor = connection.execute(
                "INSERT INTO collection_memberships(collection_id,content_identity_id,"
                "membership_state,created_by,provenance_type,provenance) "
                "VALUES(?,?,'active',?,'owner',?)",
                (int(collection["collection_id"]), content_identity_id,
                 evidence.actor, evidence.provenance),
            )
            membership_id = int(cursor.lastrowid)
            event_type = "collection_member_added"
            before_state = "absent"
        else:
            current_state = str(membership["membership_state"])
            if operation == "add" and current_state == "removed":
                raise CollectionError(
                    "Removed membership must be restored explicitly; add does not recreate it."
                )
            if current_state == target_state:
                return _membership_result(collection, membership, content_identity_id) | {
                    "changed": False, "replayed": False
                }
            membership_id = int(membership["collection_membership_id"])
            ended = "strftime('%Y-%m-%dT%H:%M:%fZ','now')" if target_state == "removed" else "NULL"
            connection.execute(
                f"UPDATE collection_memberships SET membership_state=?,ended_at={ended} "
                "WHERE collection_membership_id=?", (target_state, membership_id),
            )
            event_type = (
                "collection_member_removed" if target_state == "removed"
                else "collection_member_restored"
            )
            before_state = current_state
        _append_event(
            connection, event_type, collection_id=int(collection["collection_id"]),
            collection_membership_id=membership_id,
            content_identity_id=content_identity_id, evidence=evidence,
            details={"operation": operation, "collection_uuid": checked_uuid,
                     "content_identity_id": content_identity_id,
                     "before_state": before_state, "after_state": target_state},
        )
        current = connection.execute(
            "SELECT * FROM collection_memberships WHERE collection_membership_id=?",
            (membership_id,),
        ).fetchone()
        return _membership_result(collection, current, content_identity_id) | {
            "changed": True, "replayed": False
        }


def _append_event(
    connection: sqlite3.Connection, event_type: str, *, collection_id: int,
    evidence: _ActionEvidence, details: Mapping[str, object],
    collection_membership_id: int | None = None,
    content_identity_id: int | None = None,
) -> None:
    payload = {"action_id": evidence.action_id, **details}
    connection.execute(
        "INSERT INTO organisation_events(event_uuid,event_type,collection_id,"
        "collection_membership_id,content_identity_id,actor_type,actor_identifier,"
        "provenance,reason,details_json) VALUES(?,?,?,?,?,'owner',?,?,?,?)",
        (str(uuid.uuid4()), event_type, collection_id, collection_membership_id,
         content_identity_id, evidence.actor, evidence.provenance, evidence.reason,
         json.dumps(payload, ensure_ascii=False, sort_keys=True)),
    )


def _replayed_action(
    connection: sqlite3.Connection, evidence: _ActionEvidence,
    operation: str, expected: Mapping[str, object],
) -> sqlite3.Row | None:
    rows = connection.execute(
        "SELECT * FROM organisation_events WHERE actor_type='owner' "
        "AND event_type LIKE 'collection_%' "
        "AND json_extract(CASE WHEN json_valid(details_json) THEN details_json ELSE '{}' END,"
        "'$.action_id')=? ORDER BY organisation_event_id",
        (evidence.action_id,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise CollectionError("Owner action ID is not unique in immutable history.")
    row = rows[0]
    details = json.loads(str(row["details_json"]))
    if (
        row["actor_identifier"] != evidence.actor
        or row["provenance"] != evidence.provenance
        or row["reason"] != evidence.reason
        or details.get("operation") != operation
        or any(details.get(key) != value for key, value in expected.items())
    ):
        raise CollectionError("Owner action ID was already used for a different request.")
    return row


def _collection_result(row: sqlite3.Row, connection: sqlite3.Connection) -> dict[str, object]:
    result = dict(row)
    counts = connection.execute(
        "SELECT SUM(membership_state='active'),SUM(membership_state='removed') "
        "FROM collection_memberships WHERE collection_id=?", (int(row["collection_id"]),),
    ).fetchone()
    result["active_member_count"] = int(counts[0] or 0)
    result["removed_member_count"] = int(counts[1] or 0)
    result["duplicate_name_count"] = int(connection.execute(
        "SELECT COUNT(*) FROM collections WHERE name=? COLLATE NOCASE", (str(row["name"]),),
    ).fetchone()[0])
    return result


def _membership_result(
    collection: sqlite3.Row, membership: sqlite3.Row | None, content_identity_id: int,
) -> dict[str, object]:
    result: dict[str, object] = {
        "collection_uuid": str(collection["collection_uuid"]),
        "content_identity_id": content_identity_id,
        "membership_state": "absent" if membership is None else str(membership["membership_state"]),
    }
    if membership is not None:
        result["collection_membership_id"] = int(membership["collection_membership_id"])
        result["ended_at"] = membership["ended_at"]
    return result


def _collection(connection: sqlite3.Connection, collection_uuid: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM collections WHERE collection_uuid=?", (collection_uuid,),
    ).fetchone()
    if row is None:
        raise CollectionError("Collection does not exist.")
    return row


def _collection_by_id(connection: sqlite3.Connection, collection_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM collections WHERE collection_id=?", (collection_id,),
    ).fetchone()
    if row is None:
        raise CollectionError("Collection does not exist.")
    return row


def _content_exists(connection: sqlite3.Connection, content_identity_id: int) -> None:
    if connection.execute(
        "SELECT 1 FROM content_identities WHERE content_identity_id=?", (content_identity_id,),
    ).fetchone() is None:
        raise CollectionError("Content identity does not exist.")


def _action_evidence(
    actor: str, action_id: str, reason: str | None, provenance: str,
) -> _ActionEvidence:
    return _ActionEvidence(
        _text(actor, "Actor", 200), _text(action_id, "Action ID", 200),
        _optional_text(reason, "Reason", 2000), _text(provenance, "Provenance", 500),
    )


def _text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CollectionError(f"{label} must be non-empty text without NUL bytes.")
    checked = value.strip()
    if len(checked) > maximum:
        raise CollectionError(f"{label} must be at most {maximum} characters.")
    return checked


def _optional_text(value: str | None, label: str, maximum: int) -> str | None:
    return None if value is None else _text(value, label, maximum)


def _positive_id(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CollectionError(f"{label} must be a positive integer.")
    return value


def _page(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
        raise CollectionError(f"Limit must be between 1 and {MAX_PAGE_SIZE}.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise CollectionError("Offset must be a non-negative integer.")
    return limit, offset


def _state_filter(state: str) -> str:
    if state not in {"active", "archived", "all"}:
        raise CollectionError("Collection state filter must be active, archived, or all.")
    return state


def _require_schema(connection: sqlite3.Connection) -> None:
    if read_schema_version(connection) < COLLECTION_SCHEMA_VERSION:
        raise CollectionError("Catalogue schema 10 is required for Collection services.")


@contextmanager
def _read_connection(
    database_path: str | Path, safety_policy: PathSafetyPolicy | None,
) -> Iterator[sqlite3.Connection]:
    connection = connect_existing_catalogue(
        database_path, read_only=True, safety_policy=safety_policy
    )
    try:
        _require_schema(connection)
        yield connection
    finally:
        connection.close()


@contextmanager
def _write_connection(
    database_path: str | Path, safety_policy: PathSafetyPolicy | None,
) -> Iterator[sqlite3.Connection]:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=safety_policy
    )
    try:
        _require_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except CollectionError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise CollectionError(f"Collection catalogue write failed: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
