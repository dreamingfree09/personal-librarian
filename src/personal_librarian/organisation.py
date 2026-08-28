"""M28 owner-managed logical albums and manual tag foundation."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import OrganisationError
from personal_librarian.catalogue.migrations import read_schema_version
from personal_librarian.safety import PathSafetyPolicy


ORGANISATION_SCHEMA_VERSION = 9
MAX_PAGE_SIZE = 500

_YEAR_EVIDENCE_CTE = r"""
WITH observed_years AS (
    SELECT content_identity_id,
           CAST(substr(observed_created_at, 1, 4) AS INTEGER) AS evidence_year
    FROM physical_instances
    WHERE content_identity_id IS NOT NULL
      AND substr(observed_created_at, 1, 4) GLOB '[12][0-9][0-9][0-9]'
      AND CAST(substr(observed_created_at, 1, 4) AS INTEGER) BETWEEN 1900 AND 2100
    UNION
    SELECT content_identity_id,
           CAST(substr(observed_modified_at, 1, 4) AS INTEGER) AS evidence_year
    FROM physical_instances
    WHERE content_identity_id IS NOT NULL
      AND substr(observed_modified_at, 1, 4) GLOB '[12][0-9][0-9][0-9]'
      AND CAST(substr(observed_modified_at, 1, 4) AS INTEGER) BETWEEN 1900 AND 2100
), year_state AS (
    SELECT ci.content_identity_id,
           CASE WHEN COUNT(DISTINCT oy.evidence_year) = 1
                THEN MIN(oy.evidence_year) END AS browse_year,
           COUNT(DISTINCT oy.evidence_year) AS evidence_year_count
    FROM content_identities ci
    LEFT JOIN observed_years oy ON oy.content_identity_id = ci.content_identity_id
    GROUP BY ci.content_identity_id
)
"""


def list_browse_years(
    *, database_path: str | Path, safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    """List conservative catalogue-evidence browse years, including Unknown Date."""

    with _read_connection(database_path, safety_policy) as connection:
        rows = connection.execute(
            _YEAR_EVIDENCE_CTE
            + """
            SELECT browse_year, COUNT(*) AS content_count,
                   SUM(CASE WHEN evidence_year_count > 1 THEN 1 ELSE 0 END) AS conflict_count
            FROM year_state
            GROUP BY browse_year
            ORDER BY browse_year IS NULL, browse_year DESC
            """
        ).fetchall()
        return {
            "years": [
                {
                    "year": row["browse_year"],
                    "label": "Unknown Date" if row["browse_year"] is None else str(row["browse_year"]),
                    "content_count": int(row["content_count"]),
                    "conflict_count": int(row["conflict_count"] or 0),
                }
                for row in rows
            ],
            "evidence_policy": (
                "A year is shown only when all valid created/modified years currently "
                "catalogued for an identity agree; missing or conflicting evidence is Unknown Date."
            ),
        }


def list_year_content(
    *, database_path: str | Path, year: int | None, limit: int = 50, offset: int = 0,
    unorganised_only: bool = False,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    """Return one bounded logical-content row per identity for a browse year."""

    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2100):
        raise OrganisationError("Browse year must be between 1900 and 2100, or Unknown Date.")
    checked_limit, checked_offset = _page(limit, offset)
    year_clause = "ys.browse_year IS NULL" if year is None else "ys.browse_year = ?"
    parameters: list[Any] = [] if year is None else [year]
    unorganised_clause = """
      AND NOT EXISTS (
          SELECT 1 FROM album_memberships am
          JOIN albums a ON a.album_id = am.album_id
          WHERE am.content_identity_id = ci.content_identity_id
            AND am.membership_state = 'active' AND a.state = 'active'
      )
    """ if unorganised_only else ""
    base = f"""
        FROM year_state ys
        JOIN content_identities ci ON ci.content_identity_id = ys.content_identity_id
        LEFT JOIN physical_instances pi ON pi.physical_instance_id = (
            SELECT candidate.physical_instance_id FROM physical_instances candidate
            WHERE candidate.content_identity_id = ci.content_identity_id
            ORDER BY candidate.current_observed_path IS NULL, candidate.physical_instance_id
            LIMIT 1
        )
        LEFT JOIN sources s ON s.source_id = pi.source_id
        WHERE {year_clause} {unorganised_clause}
    """
    with _read_connection(database_path, safety_policy) as connection:
        total = int(connection.execute(
            _YEAR_EVIDENCE_CTE + "SELECT COUNT(*) " + base, parameters
        ).fetchone()[0])
        rows = connection.execute(
            _YEAR_EVIDENCE_CTE + """
            SELECT ci.content_identity_id, ci.identity_key, ys.browse_year,
                   ys.evidence_year_count,
                   CASE WHEN ys.evidence_year_count = 0 THEN 'missing'
                        WHEN ys.evidence_year_count = 1 THEN 'consistent'
                        ELSE 'conflicting' END AS evidence_state,
                   pi.physical_instance_id, pi.current_observed_path, pi.raw_relative_path,
                   pi.size_bytes, pi.extension, pi.observed_created_at,
                   pi.observed_modified_at, s.display_name AS source,
                   (SELECT COUNT(*) FROM physical_instances copies
                    WHERE copies.content_identity_id = ci.content_identity_id) AS physical_instance_count,
                   (SELECT COUNT(*) FROM album_memberships am
                    JOIN albums a ON a.album_id = am.album_id
                    WHERE am.content_identity_id = ci.content_identity_id
                      AND am.membership_state = 'active' AND a.state = 'active') AS album_count
            """
            + base
            + """
            ORDER BY COALESCE(pi.observed_created_at, pi.observed_modified_at, '') DESC,
                     ci.content_identity_id
            LIMIT ? OFFSET ?
            """,
            (*parameters, checked_limit, checked_offset),
        ).fetchall()
        return {
            "year": year, "label": "Unknown Date" if year is None else str(year),
            "content": [dict(row) for row in rows], "total_matching": total,
            "limit": checked_limit, "offset": checked_offset,
            "unorganised_only": bool(unorganised_only),
        }


def list_albums_for_browse_year(
    *, database_path: str | Path, year: int | None, include_archived: bool = False,
    limit: int = 100, offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    """Derive album presentation within a year from active member date evidence."""

    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2100):
        raise OrganisationError("Browse year must be between 1900 and 2100, or Unknown Date.")
    checked_limit, checked_offset = _page(limit, offset)
    year_clause = "ys.browse_year IS NULL" if year is None else "ys.browse_year = ?"
    state_clause = "" if include_archived else "AND a.state = 'active'"
    parameters: list[Any] = [] if year is None else [year]
    from_clause = f"""
        FROM albums a
        JOIN album_memberships am ON am.album_id = a.album_id
          AND am.membership_state = 'active'
        JOIN year_state ys ON ys.content_identity_id = am.content_identity_id
        WHERE {year_clause} {state_clause}
    """
    query = _YEAR_EVIDENCE_CTE + f"""
        SELECT a.*, COUNT(DISTINCT am.content_identity_id) AS year_member_count,
               (SELECT COUNT(*) FROM album_memberships all_members
                WHERE all_members.album_id = a.album_id
                  AND all_members.membership_state = 'active') AS member_count
        {from_clause}
        GROUP BY a.album_id
        ORDER BY a.name COLLATE NOCASE, a.album_id
        LIMIT ? OFFSET ?
    """
    with _read_connection(database_path, safety_policy) as connection:
        total = int(connection.execute(
            _YEAR_EVIDENCE_CTE
            + "SELECT COUNT(DISTINCT a.album_id) " + from_clause,
            parameters,
        ).fetchone()[0])
        rows = connection.execute(
            query, (*parameters, checked_limit, checked_offset)
        ).fetchall()
        return {
            "year": year, "albums": [dict(row) for row in rows],
            "total_matching": total, "limit": checked_limit, "offset": checked_offset,
        }


def create_album(
    *,
    database_path: str | Path,
    name: str,
    actor: str,
    description: str | None = None,
    reason: str | None = None,
    provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    checked_name = _text(name, "Album name", 200)
    checked_actor = _actor(actor)
    checked_description = _optional_text(description, "Album description", 4000)
    checked_reason = _optional_text(reason, "Reason", 2000)
    checked_provenance = _text(provenance, "Provenance", 500)
    album_uuid = str(uuid.uuid4())
    with _write_connection(database_path, safety_policy) as connection:
        cursor = connection.execute(
            """
            INSERT INTO albums(
                album_uuid, name, description, album_kind, state,
                created_by, provenance_type, provenance
            ) VALUES (?, ?, ?, 'manual', 'active', ?, 'owner', ?)
            """,
            (album_uuid, checked_name, checked_description, checked_actor, checked_provenance),
        )
        album_id = int(cursor.lastrowid)
        _append_event(
            connection,
            "album_created",
            actor=checked_actor,
            provenance=checked_provenance,
            reason=checked_reason,
            album_id=album_id,
            details={"name": checked_name, "album_kind": "manual"},
        )
        return _get_album(connection, album_uuid) | {"changed": True}


def rename_album(
    *, database_path: str | Path, album_uuid: str, name: str, actor: str,
    reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    checked_name = _text(name, "Album name", 200)
    checked_actor, checked_reason, checked_provenance = _mutation_evidence(
        actor, reason, provenance
    )
    with _write_connection(database_path, safety_policy) as connection:
        album = _album(connection, album_uuid)
        if str(album["name"]) == checked_name:
            return _get_album(connection, album_uuid) | {"changed": False}
        prior = str(album["name"])
        connection.execute(
            "UPDATE albums SET name = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE album_id = ?",
            (checked_name, int(album["album_id"])),
        )
        _append_event(
            connection, "album_renamed", actor=checked_actor,
            provenance=checked_provenance, reason=checked_reason,
            album_id=int(album["album_id"]),
            details={"prior_name": prior, "new_name": checked_name},
        )
        return _get_album(connection, album_uuid) | {"changed": True}


def archive_album(
    *, database_path: str | Path, album_uuid: str, actor: str,
    reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    return _set_album_state(
        database_path=database_path, album_uuid=album_uuid, actor=actor,
        target_state="archived", reason=reason, provenance=provenance,
        safety_policy=safety_policy,
    )


def restore_album(
    *, database_path: str | Path, album_uuid: str, actor: str,
    reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    return _set_album_state(
        database_path=database_path, album_uuid=album_uuid, actor=actor,
        target_state="active", reason=reason, provenance=provenance,
        safety_policy=safety_policy,
    )


def list_albums(
    *, database_path: str | Path, include_archived: bool = False,
    limit: int = 100, offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    checked_limit, checked_offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        where = "" if include_archived else "WHERE a.state = 'active'"
        rows = connection.execute(
            f"""
            SELECT a.*,
                   COUNT(CASE WHEN am.membership_state = 'active' THEN 1 END) AS member_count
            FROM albums a
            LEFT JOIN album_memberships am ON am.album_id = a.album_id
            {where}
            GROUP BY a.album_id
            ORDER BY a.name COLLATE NOCASE, a.album_id
            LIMIT ? OFFSET ?
            """,
            (checked_limit, checked_offset),
        ).fetchall()
        total = int(connection.execute(
            f"SELECT COUNT(*) FROM albums a {where}"
        ).fetchone()[0])
        return {
            "albums": [_album_result(row) for row in rows],
            "total_matching": total,
            "limit": checked_limit,
            "offset": checked_offset,
        }


def get_album(
    *, database_path: str | Path, album_uuid: str,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    with _read_connection(database_path, safety_policy) as connection:
        return _get_album(connection, album_uuid)


def add_content_to_album(
    *, database_path: str | Path, album_uuid: str, content_identity_id: int,
    actor: str, reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    return _set_album_membership(
        database_path=database_path, album_uuid=album_uuid,
        content_identity_id=content_identity_id, actor=actor, target_state="active",
        reason=reason, provenance=provenance, safety_policy=safety_policy,
    )


def remove_content_from_album(
    *, database_path: str | Path, album_uuid: str, content_identity_id: int,
    actor: str, reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    return _set_album_membership(
        database_path=database_path, album_uuid=album_uuid,
        content_identity_id=content_identity_id, actor=actor, target_state="removed",
        reason=reason, provenance=provenance, safety_policy=safety_policy,
    )


def list_album_members(
    *, database_path: str | Path, album_uuid: str, include_removed: bool = False,
    limit: int = 100, offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    checked_limit, checked_offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        album = _album(connection, album_uuid)
        state_clause = "" if include_removed else "AND am.membership_state = 'active'"
        rows = connection.execute(
            f"""
            SELECT am.album_membership_id, am.content_identity_id, ci.identity_key,
                   am.membership_state, am.created_at, am.created_by, am.provenance,
                   am.ended_at,
                   representative.physical_instance_id,
                   representative.current_observed_path,
                   representative.raw_relative_path,
                   representative.size_bytes, representative.extension,
                   representative.observed_created_at,
                   representative.observed_modified_at,
                   s.display_name AS source,
                   COUNT(pi.physical_instance_id) AS physical_instance_count
            FROM album_memberships am
            JOIN content_identities ci ON ci.content_identity_id = am.content_identity_id
            LEFT JOIN physical_instances pi
                ON pi.content_identity_id = am.content_identity_id
            LEFT JOIN physical_instances representative
                ON representative.physical_instance_id = (
                    SELECT candidate.physical_instance_id
                    FROM physical_instances candidate
                    WHERE candidate.content_identity_id = am.content_identity_id
                    ORDER BY candidate.current_observed_path IS NULL,
                             candidate.physical_instance_id
                    LIMIT 1
                )
            LEFT JOIN sources s ON s.source_id = representative.source_id
            WHERE am.album_id = ? {state_clause}
            GROUP BY am.album_membership_id
            ORDER BY am.album_membership_id
            LIMIT ? OFFSET ?
            """,
            (int(album["album_id"]), checked_limit, checked_offset),
        ).fetchall()
        total = int(connection.execute(
            f"SELECT COUNT(*) FROM album_memberships am "
            f"WHERE am.album_id = ? {state_clause}",
            (int(album["album_id"]),),
        ).fetchone()[0])
        return {
            "album": _get_album(connection, album_uuid),
            "members": [dict(row) for row in rows],
            "total_matching": total,
            "limit": checked_limit,
            "offset": checked_offset,
        }


def list_albums_for_content(
    *, database_path: str | Path, content_identity_id: int,
    include_removed: bool = False,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    checked_content = _positive_id(content_identity_id, "Content identity ID")
    with _read_connection(database_path, safety_policy) as connection:
        _content(connection, checked_content)
        state_clause = "" if include_removed else "AND am.membership_state = 'active'"
        rows = connection.execute(
            f"""
            SELECT a.*, am.membership_state, am.created_at AS membership_created_at,
                   am.ended_at
            FROM album_memberships am
            JOIN albums a ON a.album_id = am.album_id
            WHERE am.content_identity_id = ? {state_clause}
            ORDER BY a.name COLLATE NOCASE, a.album_id
            """,
            (checked_content,),
        ).fetchall()
        return {
            "content_identity_id": checked_content,
            "albums": [dict(row) for row in rows],
        }


def organisation_history(
    *, database_path: str | Path, album_uuid: str | None = None,
    content_identity_id: int | None = None, limit: int = 100, offset: int = 0,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    checked_limit, checked_offset = _page(limit, offset)
    with _read_connection(database_path, safety_policy) as connection:
        clauses: list[str] = []
        parameters: list[Any] = []
        if album_uuid is not None:
            album = _album(connection, album_uuid)
            clauses.append("oe.album_id = ?")
            parameters.append(int(album["album_id"]))
        if content_identity_id is not None:
            checked_content = _positive_id(content_identity_id, "Content identity ID")
            _content(connection, checked_content)
            clauses.append("oe.content_identity_id = ?")
            parameters.append(checked_content)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = connection.execute(
            f"""
            SELECT oe.*, a.album_uuid, t.tag_uuid
            FROM organisation_events oe
            LEFT JOIN albums a ON a.album_id = oe.album_id
            LEFT JOIN tags t ON t.tag_id = oe.tag_id
            {where}
            ORDER BY oe.organisation_event_id DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, checked_limit, checked_offset),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(str(item.pop("details_json")))
            result.append(item)
        total = int(connection.execute(
            f"SELECT COUNT(*) FROM organisation_events oe {where}", parameters
        ).fetchone()[0])
        return {
            "history": result, "total_matching": total,
            "limit": checked_limit, "offset": checked_offset,
        }


def create_tag(
    *, database_path: str | Path, name: str, actor: str,
    namespace: str | None = None, reason: str | None = None,
    provenance: str = "owner-manual", safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    checked_name = _text(name, "Tag name", 200)
    checked_namespace = _optional_text(namespace, "Tag namespace", 100)
    checked_actor, checked_reason, checked_provenance = _mutation_evidence(
        actor, reason, provenance
    )
    tag_uuid = str(uuid.uuid4())
    with _write_connection(database_path, safety_policy) as connection:
        cursor = connection.execute(
            "INSERT INTO tags(tag_uuid, name, namespace, created_by, provenance_type, provenance) "
            "VALUES (?, ?, ?, ?, 'owner', ?)",
            (tag_uuid, checked_name, checked_namespace, checked_actor, checked_provenance),
        )
        tag_id = int(cursor.lastrowid)
        _append_event(
            connection, "tag_created", actor=checked_actor,
            provenance=checked_provenance, reason=checked_reason, tag_id=tag_id,
            details={"name": checked_name, "namespace": checked_namespace},
        )
        return _tag_result(_tag(connection, tag_uuid)) | {"changed": True}


def list_tags(
    *, database_path: str | Path, include_archived: bool = False,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    with _read_connection(database_path, safety_policy) as connection:
        where = "" if include_archived else "WHERE state = 'active'"
        rows = connection.execute(
            f"SELECT * FROM tags {where} ORDER BY namespace, name COLLATE NOCASE, tag_id"
        ).fetchall()
        return {"tags": [_tag_result(row) for row in rows]}


def add_tag_to_content(
    *, database_path: str | Path, tag_uuid: str, content_identity_id: int,
    actor: str, reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    return _set_tag_membership(
        database_path=database_path, tag_uuid=tag_uuid,
        content_identity_id=content_identity_id, actor=actor, target_state="active",
        reason=reason, provenance=provenance, safety_policy=safety_policy,
    )


def remove_tag_from_content(
    *, database_path: str | Path, tag_uuid: str, content_identity_id: int,
    actor: str, reason: str | None = None, provenance: str = "owner-manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    return _set_tag_membership(
        database_path=database_path, tag_uuid=tag_uuid,
        content_identity_id=content_identity_id, actor=actor, target_state="removed",
        reason=reason, provenance=provenance, safety_policy=safety_policy,
    )


def list_tags_for_content(
    *, database_path: str | Path, content_identity_id: int,
    safety_policy: PathSafetyPolicy | None = None,
) -> dict[str, Any]:
    checked_content = _positive_id(content_identity_id, "Content identity ID")
    with _read_connection(database_path, safety_policy) as connection:
        _content(connection, checked_content)
        rows = connection.execute(
            """
            SELECT t.*, ct.membership_state, ct.created_at AS membership_created_at
            FROM content_tags ct JOIN tags t ON t.tag_id = ct.tag_id
            WHERE ct.content_identity_id = ? AND ct.membership_state = 'active'
            ORDER BY t.namespace, t.name COLLATE NOCASE, t.tag_id
            """,
            (checked_content,),
        ).fetchall()
        return {"content_identity_id": checked_content, "tags": [dict(row) for row in rows]}


def _set_album_state(
    *, database_path: str | Path, album_uuid: str, actor: str,
    target_state: str, reason: str | None, provenance: str,
    safety_policy: PathSafetyPolicy | None,
) -> dict[str, Any]:
    checked_actor, checked_reason, checked_provenance = _mutation_evidence(
        actor, reason, provenance
    )
    with _write_connection(database_path, safety_policy) as connection:
        album = _album(connection, album_uuid)
        if str(album["state"]) == target_state:
            return _get_album(connection, album_uuid) | {"changed": False}
        archived_expression = (
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')" if target_state == "archived" else "NULL"
        )
        connection.execute(
            f"UPDATE albums SET state = ?, archived_at = {archived_expression}, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE album_id = ?",
            (target_state, int(album["album_id"])),
        )
        event_type = "album_archived" if target_state == "archived" else "album_restored"
        _append_event(
            connection, event_type, actor=checked_actor, provenance=checked_provenance,
            reason=checked_reason, album_id=int(album["album_id"]),
            details={"prior_state": str(album["state"]), "new_state": target_state},
        )
        return _get_album(connection, album_uuid) | {"changed": True}


def _set_album_membership(
    *, database_path: str | Path, album_uuid: str, content_identity_id: int,
    actor: str, target_state: str, reason: str | None, provenance: str,
    safety_policy: PathSafetyPolicy | None,
) -> dict[str, Any]:
    checked_content = _positive_id(content_identity_id, "Content identity ID")
    checked_actor, checked_reason, checked_provenance = _mutation_evidence(
        actor, reason, provenance
    )
    with _write_connection(database_path, safety_policy) as connection:
        album = _album(connection, album_uuid)
        if str(album["state"]) != "active":
            raise OrganisationError("Archived albums are read-only; restore the album first.")
        _content(connection, checked_content)
        membership = connection.execute(
            "SELECT * FROM album_memberships WHERE album_id = ? AND content_identity_id = ?",
            (int(album["album_id"]), checked_content),
        ).fetchone()
        if membership is None:
            if target_state == "removed":
                return _membership_result(album, None, checked_content, changed=False)
            cursor = connection.execute(
                """
                INSERT INTO album_memberships(
                    album_id, content_identity_id, membership_state,
                    created_by, provenance_type, provenance
                ) VALUES (?, ?, 'active', ?, 'owner', ?)
                """,
                (int(album["album_id"]), checked_content, checked_actor, checked_provenance),
            )
            membership_id = int(cursor.lastrowid)
            event_type = "album_member_added"
        elif str(membership["membership_state"]) == target_state:
            return _membership_result(album, membership, checked_content, changed=False)
        else:
            membership_id = int(membership["album_membership_id"])
            ended = (
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
                if target_state == "removed" else "NULL"
            )
            connection.execute(
                f"UPDATE album_memberships SET membership_state = ?, ended_at = {ended} "
                "WHERE album_membership_id = ?",
                (target_state, membership_id),
            )
            event_type = (
                "album_member_removed" if target_state == "removed"
                else "album_member_restored"
            )
        _append_event(
            connection, event_type, actor=checked_actor, provenance=checked_provenance,
            reason=checked_reason, album_id=int(album["album_id"]),
            album_membership_id=membership_id, content_identity_id=checked_content,
            details={"membership_state": target_state},
        )
        current = connection.execute(
            "SELECT * FROM album_memberships WHERE album_membership_id = ?",
            (membership_id,),
        ).fetchone()
        return _membership_result(album, current, checked_content, changed=True)


def _set_tag_membership(
    *, database_path: str | Path, tag_uuid: str, content_identity_id: int,
    actor: str, target_state: str, reason: str | None, provenance: str,
    safety_policy: PathSafetyPolicy | None,
) -> dict[str, Any]:
    checked_content = _positive_id(content_identity_id, "Content identity ID")
    checked_actor, checked_reason, checked_provenance = _mutation_evidence(
        actor, reason, provenance
    )
    with _write_connection(database_path, safety_policy) as connection:
        tag = _tag(connection, tag_uuid)
        if str(tag["state"]) != "active":
            raise OrganisationError("Archived tags are read-only.")
        _content(connection, checked_content)
        membership = connection.execute(
            "SELECT * FROM content_tags WHERE tag_id = ? AND content_identity_id = ?",
            (int(tag["tag_id"]), checked_content),
        ).fetchone()
        if membership is None:
            if target_state == "removed":
                return {"tag_uuid": str(tag["tag_uuid"]), "content_identity_id": checked_content,
                        "membership_state": "absent", "changed": False}
            cursor = connection.execute(
                "INSERT INTO content_tags(tag_id, content_identity_id, created_by, "
                "provenance_type, provenance) VALUES (?, ?, ?, 'owner', ?)",
                (int(tag["tag_id"]), checked_content, checked_actor, checked_provenance),
            )
            membership_id = int(cursor.lastrowid)
            event_type = "tag_member_added"
        elif str(membership["membership_state"]) == target_state:
            return dict(membership) | {"tag_uuid": str(tag["tag_uuid"]), "changed": False}
        else:
            membership_id = int(membership["content_tag_id"])
            ended = (
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
                if target_state == "removed" else "NULL"
            )
            connection.execute(
                f"UPDATE content_tags SET membership_state = ?, ended_at = {ended} "
                "WHERE content_tag_id = ?",
                (target_state, membership_id),
            )
            event_type = "tag_member_removed" if target_state == "removed" else "tag_member_restored"
        _append_event(
            connection, event_type, actor=checked_actor, provenance=checked_provenance,
            reason=checked_reason, tag_id=int(tag["tag_id"]),
            content_tag_id=membership_id, content_identity_id=checked_content,
            details={"membership_state": target_state},
        )
        current = connection.execute(
            "SELECT * FROM content_tags WHERE content_tag_id = ?", (membership_id,)
        ).fetchone()
        return dict(current) | {"tag_uuid": str(tag["tag_uuid"]), "changed": True}


def _append_event(
    connection: sqlite3.Connection, event_type: str, *, actor: str,
    provenance: str, reason: str | None, details: dict[str, Any],
    album_id: int | None = None, album_membership_id: int | None = None,
    tag_id: int | None = None, content_tag_id: int | None = None,
    content_identity_id: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO organisation_events(
            event_uuid, event_type, album_id, album_membership_id,
            tag_id, content_tag_id, content_identity_id,
            actor_type, actor_identifier, provenance, reason, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'owner', ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()), event_type, album_id, album_membership_id,
            tag_id, content_tag_id, content_identity_id,
            actor, provenance, reason,
            json.dumps(details, ensure_ascii=False, sort_keys=True),
        ),
    )


def _get_album(connection: sqlite3.Connection, album_uuid: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT a.*,
               COUNT(CASE WHEN am.membership_state = 'active' THEN 1 END) AS member_count,
               COUNT(CASE WHEN am.membership_state = 'removed' THEN 1 END) AS removed_member_count
        FROM albums a LEFT JOIN album_memberships am ON am.album_id = a.album_id
        WHERE a.album_uuid = ? GROUP BY a.album_id
        """,
        (_identifier(album_uuid, "Album UUID"),),
    ).fetchone()
    if row is None:
        raise OrganisationError("Album does not exist.")
    result = _album_result(row)
    duplicate_count = int(connection.execute(
        "SELECT COUNT(*) FROM albums WHERE state = 'active' AND name = ? COLLATE NOCASE",
        (str(row["name"]),),
    ).fetchone()[0])
    result["active_same_name_count"] = duplicate_count
    return result


def _album(connection: sqlite3.Connection, album_uuid: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM albums WHERE album_uuid = ?",
        (_identifier(album_uuid, "Album UUID"),),
    ).fetchone()
    if row is None:
        raise OrganisationError("Album does not exist.")
    return row


def _tag(connection: sqlite3.Connection, tag_uuid: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM tags WHERE tag_uuid = ?", (_identifier(tag_uuid, "Tag UUID"),)
    ).fetchone()
    if row is None:
        raise OrganisationError("Tag does not exist.")
    return row


def _content(connection: sqlite3.Connection, content_identity_id: int) -> None:
    if connection.execute(
        "SELECT 1 FROM content_identities WHERE content_identity_id = ?",
        (content_identity_id,),
    ).fetchone() is None:
        raise OrganisationError("Content identity does not exist.")


def _album_result(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _tag_result(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _membership_result(
    album: sqlite3.Row, membership: sqlite3.Row | None,
    content_identity_id: int, *, changed: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "album_uuid": str(album["album_uuid"]),
        "content_identity_id": content_identity_id,
        "membership_state": "absent" if membership is None else str(membership["membership_state"]),
        "changed": changed,
    }
    if membership is not None:
        result["album_membership_id"] = int(membership["album_membership_id"])
    return result


def _mutation_evidence(actor: str, reason: str | None, provenance: str) -> tuple[str, str | None, str]:
    return (
        _actor(actor),
        _optional_text(reason, "Reason", 2000),
        _text(provenance, "Provenance", 500),
    )


def _actor(value: str) -> str:
    return _text(value, "Actor", 200)


def _identifier(value: str, label: str) -> str:
    return _text(value, label, 200)


def _text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise OrganisationError(f"{label} must be text.")
    checked = value.strip()
    if not checked:
        raise OrganisationError(f"{label} must not be empty.")
    if "\x00" in checked:
        raise OrganisationError(f"{label} must not contain a NUL byte.")
    if len(checked) > maximum:
        raise OrganisationError(f"{label} must be at most {maximum} characters.")
    return checked


def _optional_text(value: str | None, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, label, maximum)


def _positive_id(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise OrganisationError(f"{label} must be a positive integer.")
    return value


def _page(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
        raise OrganisationError(f"Limit must be between 1 and {MAX_PAGE_SIZE}.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise OrganisationError("Offset must be a non-negative integer.")
    return limit, offset


@contextmanager
def _read_connection(
    database_path: str | Path, safety_policy: PathSafetyPolicy | None
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
    database_path: str | Path, safety_policy: PathSafetyPolicy | None
) -> Iterator[sqlite3.Connection]:
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=safety_policy
    )
    try:
        _require_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except OrganisationError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise OrganisationError(f"Organisation catalogue write failed: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _require_schema(connection: sqlite3.Connection) -> None:
    if read_schema_version(connection) < ORGANISATION_SCHEMA_VERSION:
        raise OrganisationError(
            "Catalogue schema 9 is required; migrate the catalogue before using organisation commands."
        )
