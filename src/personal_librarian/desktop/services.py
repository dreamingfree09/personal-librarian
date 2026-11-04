"""Bounded backend facade used by desktop views.

Qt widgets deliberately do not own SQL or reproduce domain rules.  All writes are
delegated to the append-only M17 decision service.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from personal_librarian.action_planning import list_plans, show_plan
from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import CatalogueError
from personal_librarian.catalogue.migrations import read_schema_version
from personal_librarian.collections import (
    add_content_to_collection,
    archive_collection,
    collection_history,
    create_collection,
    get_collection,
    list_collection_members,
    list_collections,
    list_collections_for_content,
    remove_content_from_collection,
    rename_collection,
    restore_collection,
    restore_content_to_collection,
)
from personal_librarian.date_evidence import (
    PreferredStatus,
    get_preferred_date,
    list_date_evidence,
    list_preferred_basis,
    list_preferred_identities,
    preferred_date_counts,
    replace_owner_preferred_date,
    set_owner_preferred_date,
)
from personal_librarian.decisions import (
    abstain,
    approve,
    decision_history,
    nominate,
    reject,
    supersede,
)
from personal_librarian.production import application_data_layout, list_backups, production_health
from personal_librarian.quarantine import quarantine_history, quarantine_status
from personal_librarian.organisation import (
    add_content_to_album,
    add_tag_to_content,
    archive_album,
    create_album,
    create_tag,
    get_album,
    list_album_members,
    list_albums,
    list_albums_for_browse_year,
    list_albums_for_content,
    list_browse_years,
    list_tags,
    list_tags_for_content,
    list_year_content,
    organisation_history,
    remove_content_from_album,
    remove_tag_from_content,
    rename_album,
    restore_album,
)
from personal_librarian.review import (
    list_exact_reviews,
    list_similar_reviews,
    show_exact_review,
    show_similar_review,
)
from personal_librarian.safety import PathSafetyPolicy


def _desktop_history_timestamps(result: dict[str, Any]) -> dict[str, Any]:
    """Expose the stable desktop timestamp contract without changing stored events."""

    for row in result.get("history", []):
        if "recorded_at" in row:
            recorded_at = row.pop("recorded_at")
            if "occurred_at" in row and row["occurred_at"] != recorded_at:
                raise CatalogueError("History timestamp fields disagree.")
            row["occurred_at"] = recorded_at
    return result


class DesktopDataService:
    """Small, testable interface between Qt presentation and existing services."""

    def __init__(
        self,
        app_data_root: str | Path,
        independent_backup_root: str | Path | None = None,
        *,
        safety_policy: PathSafetyPolicy | None = None,
    ) -> None:
        self.policy = safety_policy or PathSafetyPolicy()
        self.layout = application_data_layout(app_data_root, safety_policy=self.policy)
        self.independent_backup_root = independent_backup_root

    @property
    def database_path(self) -> Path:
        return self.layout.catalogue_path

    def health(self) -> dict[str, Any]:
        return production_health(
            app_data_root=self.layout.root,
            independent_backup_root=self.independent_backup_root,
            safety_policy=self.policy,
        ).values

    def schema_capabilities(self) -> dict[str, Any]:
        """Report desktop feature compatibility without migrating the catalogue."""

        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            version = read_schema_version(connection)
        finally:
            connection.close()
        return {
            "schema_version": version,
            "preferred_dates_enabled": version >= 10,
            "collections_enabled": version >= 10,
            "legacy_years": version < 10,
        }

    def dashboard(self) -> dict[str, Any]:
        health = self.health()
        if health.get("summary") == "FAIL":
            return {"health": health, "decision_writes_enabled": False}
        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            schema_version = read_schema_version(connection)
            tables = [
                "inventory_observations",
                "physical_instances",
                "content_identities",
                "exact_duplicate_groups",
                "similarity_groups",
                "decision_events",
                "action_plans",
                "quarantine_records",
                "albums",
                "album_memberships",
                "tags",
                "content_tags",
                "organisation_events",
            ]
            if schema_version >= 10:
                tables.extend((
                    "content_date_evidence", "content_preferred_dates",
                    "collections", "collection_memberships",
                ))
            counts = {
                table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                for table in tables
            }
        finally:
            connection.close()
        return {
            "health": health,
            "counts": counts,
            "decision_writes_enabled": health.get("integrity_check") == "ok"
            and not health.get("foreign_key_violations"),
        }

    def exact_reviews(self, *, status: str | None, limit: int, offset: int) -> dict[str, Any]:
        return list_exact_reviews(
            database_path=self.database_path,
            status=status,
            limit=limit,
            offset=offset,
            safety_policy=self.policy,
        )

    def exact_detail(self, context_id: int) -> dict[str, Any]:
        return show_exact_review(
            database_path=self.database_path,
            context_id=context_id,
            safety_policy=self.policy,
        )

    def similar_reviews(
        self, *, status: str | None, limit: int, offset: int, large_only: bool = False
    ) -> dict[str, Any]:
        return list_similar_reviews(
            database_path=self.database_path,
            status=status,
            large_only=large_only,
            limit=limit,
            offset=offset,
            safety_policy=self.policy,
        )

    def similar_detail(self, context_id: int) -> dict[str, Any]:
        return show_similar_review(
            database_path=self.database_path,
            context_id=context_id,
            safety_policy=self.policy,
        )

    def decisions(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return decision_history(
            database_path=self.database_path,
            limit=limit,
            offset=offset,
            safety_policy=self.policy,
        )

    def plans(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return list_plans(
            database_path=self.database_path,
            limit=limit,
            offset=offset,
            safety_policy=self.policy,
        )

    def plan(self, plan_id: str) -> dict[str, Any]:
        return show_plan(
            database_path=self.database_path, plan_id=plan_id, safety_policy=self.policy
        )

    def quarantine(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return quarantine_history(
            database_path=self.database_path,
            limit=limit,
            offset=offset,
            safety_policy=self.policy,
        )

    def quarantine_detail(self, execution_id: str) -> dict[str, Any]:
        return quarantine_status(
            database_path=self.database_path,
            execution_id=execution_id,
            safety_policy=self.policy,
        )

    def backups(self) -> dict[str, Any]:
        operational = list_backups(
            app_data_root=self.layout.root,
            backup_class="operational-local",
            safety_policy=self.policy,
        ).values
        independent: dict[str, Any] = {
            "backup_class": "independent-local",
            "count": 0,
            "backups": [],
            "unavailable": True,
        }
        if self.independent_backup_root is not None:
            try:
                independent = list_backups(
                    app_data_root=self.layout.root,
                    backup_root=self.independent_backup_root,
                    backup_class="independent-local",
                    safety_policy=self.policy,
                ).values
                independent["unavailable"] = False
            except Exception as exc:  # A disconnected independent disk is a view state.
                independent["error"] = str(exc)
        return {
            "operational": operational,
            "independent": independent,
            "health": self.health(),
        }

    # Organisation presentation and mutations remain behind this facade so Qt
    # widgets never own SQL or reproduce schema policy.
    def browse_years(self) -> dict[str, Any]:
        if self.schema_capabilities()["preferred_dates_enabled"]:
            return self._preferred_browse_years()
        return list_browse_years(database_path=self.database_path, safety_policy=self.policy)

    def year_content(
        self, *, year: int | None, limit: int, offset: int,
        unorganised_only: bool = False,
    ) -> dict[str, Any]:
        if self.schema_capabilities()["preferred_dates_enabled"]:
            return self._preferred_year_content(
                year=year, limit=limit, offset=offset,
                unorganised_only=unorganised_only,
            )
        return list_year_content(
            database_path=self.database_path, year=year, limit=limit, offset=offset,
            unorganised_only=unorganised_only, safety_policy=self.policy,
        )

    def year_albums(
        self, *, year: int | None, include_archived: bool = False,
        limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        if self.schema_capabilities()["preferred_dates_enabled"]:
            return self._preferred_year_albums(
                year=year, include_archived=include_archived,
                limit=limit, offset=offset,
            )
        return list_albums_for_browse_year(
            database_path=self.database_path, year=year, include_archived=include_archived,
            limit=limit, offset=offset, safety_policy=self.policy,
        )

    def _preferred_browse_years(self) -> dict[str, Any]:
        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            rows = connection.execute(
                """
                SELECT * FROM (
                    SELECT p.selected_year AS browse_year,COUNT(*) AS content_count,
                           0 AS conflict_count
                    FROM content_preferred_dates p
                    WHERE p.status='resolved'
                    GROUP BY p.selected_year
                    UNION ALL
                    SELECT NULL,
                           (SELECT COUNT(*) FROM content_identities)
                           - (SELECT COUNT(*) FROM content_preferred_dates
                              WHERE status='resolved'),
                           0
                )
                ORDER BY browse_year IS NULL,browse_year DESC
                """
            ).fetchall()
        finally:
            connection.close()
        return {
            "years": [
                {
                    "year": row["browse_year"],
                    "label": "Unknown Date" if row["browse_year"] is None
                    else str(row["browse_year"]),
                    "content_count": int(row["content_count"]),
                    "conflict_count": int(row["conflict_count"] or 0),
                }
                for row in rows if int(row["content_count"])
            ],
            "evidence_policy": (
                "Schema 10 uses only the current preferred-date projection. Resolved "
                "values use selected_year; needs-review, unknown, and missing records "
                "appear under Unknown Date. Observed filesystem timestamps are not a fallback."
            ),
            "schema_version": 10,
        }

    def _preferred_year_content(
        self, *, year: int | None, limit: int, offset: int,
        unorganised_only: bool,
    ) -> dict[str, Any]:
        self._validate_year_page(year, limit, offset)
        if year is None:
            return self._preferred_unknown_content(
                limit=limit, offset=offset, unorganised_only=unorganised_only,
            )
        year_clause = "p.status='resolved' AND p.selected_year=?"
        parameters: list[object] = [year]
        unorganised = """
          AND NOT EXISTS (
              SELECT 1 FROM album_memberships am JOIN albums a ON a.album_id=am.album_id
              WHERE am.content_identity_id=ci.content_identity_id
                AND am.membership_state='active' AND a.state='active'
          )
        """ if unorganised_only else ""
        base = f"""
            FROM content_identities ci
            LEFT JOIN content_preferred_dates p ON p.content_identity_id=ci.content_identity_id
            LEFT JOIN content_date_evidence selected
              ON selected.date_evidence_id=p.selected_evidence_id
            LEFT JOIN physical_instances pi ON pi.physical_instance_id=(
                SELECT candidate.physical_instance_id FROM physical_instances candidate
                WHERE candidate.content_identity_id=ci.content_identity_id
                ORDER BY candidate.current_observed_path IS NULL,candidate.physical_instance_id
                LIMIT 1
            )
            LEFT JOIN sources s ON s.source_id=pi.source_id
            WHERE {year_clause} {unorganised}
        """
        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            total = int(connection.execute(
                "SELECT COUNT(*) " + base, parameters
            ).fetchone()[0])
            rows = connection.execute(
                """
                SELECT ci.content_identity_id,ci.identity_key,
                       CASE WHEN p.status='resolved' THEN p.selected_year END AS browse_year,
                       COALESCE(p.status,'unknown') AS preferred_status,
                       p.selection_method,p.selected_precision,p.selected_time_precision,
                       p.selected_year,p.selected_month,p.selected_day,p.selected_hour,
                       p.selected_minute,p.selected_second,p.selected_fraction,
                       p.selected_timezone_state,p.selected_utc_offset_minutes,
                       p.actor_type AS preferred_actor_type,
                       p.actor_identifier AS preferred_actor_identifier,
                       p.provenance AS preferred_provenance,
                       selected.evidence_type AS selected_evidence_type,
                       selected.raw_value AS selected_evidence_raw_value,
                       selected.source_field AS selected_evidence_source_field,
                       pi.physical_instance_id,pi.current_observed_path,pi.raw_relative_path,
                       pi.size_bytes,pi.extension,pi.observed_created_at,
                       pi.observed_modified_at,s.display_name AS source,
                       (SELECT COUNT(*) FROM physical_instances copies
                        WHERE copies.content_identity_id=ci.content_identity_id)
                           AS physical_instance_count,
                       (SELECT COUNT(*) FROM album_memberships am JOIN albums a
                        ON a.album_id=am.album_id
                        WHERE am.content_identity_id=ci.content_identity_id
                          AND am.membership_state='active' AND a.state='active') AS album_count
                """ + base + """
                ORDER BY COALESCE(p.selected_month,0) DESC,
                         COALESCE(p.selected_day,0) DESC,ci.content_identity_id
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()
        finally:
            connection.close()
        return {
            "year": year, "label": "Unknown Date" if year is None else str(year),
            "content": [dict(row) for row in rows], "total_matching": total,
            "limit": limit, "offset": offset,
            "unorganised_only": bool(unorganised_only), "schema_version": 10,
        }

    def _preferred_unknown_content(
        self, *, limit: int, offset: int, unorganised_only: bool,
    ) -> dict[str, Any]:
        """Return Unknown identities after bounding IDs, before display enrichment."""

        unknown_clause = "(p.preferred_date_id IS NULL OR p.status IN ('unknown','needs_review'))"
        unorganised = """
          AND NOT EXISTS (
              SELECT 1 FROM album_memberships am JOIN albums a ON a.album_id=am.album_id
              WHERE am.content_identity_id=ci.content_identity_id
                AND am.membership_state='active' AND a.state='active'
          )
        """ if unorganised_only else ""
        candidate_from = f"""
            FROM content_identities ci
            LEFT JOIN content_preferred_dates p ON p.content_identity_id=ci.content_identity_id
            WHERE {unknown_clause} {unorganised}
        """
        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            connection.execute("BEGIN")
            # Keep the authoritative count free of representative/display joins and sorting.
            if unorganised_only:
                total = int(connection.execute(
                    "SELECT COUNT(*) " + candidate_from
                ).fetchone()[0])
            else:
                # Schema 10 permits one projection per identity and exactly three states.
                # Missing, Unknown and needs-review projections are total identities
                # minus resolved projections.  Counting the two
                # covering indexes avoids a point probe for every content identity.
                total = int(connection.execute(
                    """
                    SELECT (SELECT COUNT(*) FROM content_identities)
                           - (SELECT COUNT(*) FROM content_preferred_dates
                              WHERE status='resolved')
                    """
                ).fetchone()[0])
            page_ids = [
                int(row[0]) for row in connection.execute(
                    "SELECT ci.content_identity_id " + candidate_from
                    + " ORDER BY ci.content_identity_id LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            ]
            rows = []
            if page_ids:
                values = ",".join(
                    f"(?,{page_order})" for page_order in range(len(page_ids))
                )
                rows = connection.execute(
                    f"""
                    WITH page(content_identity_id,page_order) AS (VALUES {values})
                    SELECT ci.content_identity_id,ci.identity_key,
                           NULL AS browse_year,
                           COALESCE(p.status,'unknown') AS preferred_status,
                           p.selection_method,p.selected_precision,p.selected_time_precision,
                           p.selected_year,p.selected_month,p.selected_day,p.selected_hour,
                           p.selected_minute,p.selected_second,p.selected_fraction,
                           p.selected_timezone_state,p.selected_utc_offset_minutes,
                           p.actor_type AS preferred_actor_type,
                           p.actor_identifier AS preferred_actor_identifier,
                           p.provenance AS preferred_provenance,
                           selected.evidence_type AS selected_evidence_type,
                           selected.raw_value AS selected_evidence_raw_value,
                           selected.source_field AS selected_evidence_source_field,
                           pi.physical_instance_id,pi.current_observed_path,
                           pi.raw_relative_path,pi.size_bytes,pi.extension,
                           pi.observed_created_at,pi.observed_modified_at,
                           s.display_name AS source,
                           (SELECT COUNT(*) FROM physical_instances copies
                            WHERE copies.content_identity_id=ci.content_identity_id)
                               AS physical_instance_count,
                           (SELECT COUNT(*) FROM album_memberships am JOIN albums a
                            ON a.album_id=am.album_id
                            WHERE am.content_identity_id=ci.content_identity_id
                              AND am.membership_state='active' AND a.state='active')
                               AS album_count
                    FROM page
                    JOIN content_identities ci
                      ON ci.content_identity_id=page.content_identity_id
                    LEFT JOIN content_preferred_dates p
                      ON p.content_identity_id=ci.content_identity_id
                    LEFT JOIN content_date_evidence selected
                      ON selected.date_evidence_id=p.selected_evidence_id
                    LEFT JOIN physical_instances pi ON pi.physical_instance_id=(
                        SELECT candidate.physical_instance_id
                        FROM physical_instances candidate
                        WHERE candidate.content_identity_id=ci.content_identity_id
                        ORDER BY candidate.current_observed_path IS NULL,
                                 candidate.physical_instance_id
                        LIMIT 1
                    )
                    LEFT JOIN sources s ON s.source_id=pi.source_id
                    ORDER BY page.page_order
                    """,
                    page_ids,
                ).fetchall()
        finally:
            connection.close()
        return {
            "year": None, "label": "Unknown Date",
            "content": [dict(row) for row in rows], "total_matching": total,
            "limit": limit, "offset": offset,
            "unorganised_only": bool(unorganised_only), "schema_version": 10,
        }

    def _preferred_year_albums(
        self, *, year: int | None, include_archived: bool,
        limit: int, offset: int,
    ) -> dict[str, Any]:
        self._validate_year_page(year, limit, offset)
        year_clause = (
            "(p.preferred_date_id IS NULL OR p.status IN ('unknown','needs_review'))"
            if year is None else "p.status='resolved' AND p.selected_year=?"
        )
        state_clause = "" if include_archived else "AND a.state='active'"
        parameters: list[object] = [] if year is None else [year]
        base = f"""
            FROM albums a JOIN album_memberships am ON am.album_id=a.album_id
              AND am.membership_state='active'
            JOIN content_identities ci ON ci.content_identity_id=am.content_identity_id
            LEFT JOIN content_preferred_dates p ON p.content_identity_id=ci.content_identity_id
            WHERE {year_clause} {state_clause}
        """
        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            total = int(connection.execute(
                "SELECT COUNT(DISTINCT a.album_id) " + base, parameters
            ).fetchone()[0])
            rows = connection.execute(
                "SELECT a.*,COUNT(DISTINCT am.content_identity_id) AS year_member_count,"
                "(SELECT COUNT(*) FROM album_memberships all_members WHERE "
                "all_members.album_id=a.album_id AND all_members.membership_state='active') "
                "AS member_count " + base +
                " GROUP BY a.album_id ORDER BY a.name COLLATE NOCASE,a.album_id LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        finally:
            connection.close()
        return {"year": year, "albums": [dict(row) for row in rows],
                "total_matching": total, "limit": limit, "offset": offset}

    @staticmethod
    def _validate_year_page(year: int | None, limit: int, offset: int) -> None:
        if year is not None and (
            isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999
        ):
            raise CatalogueError("Browse year must be between 1 and 9999, or Unknown Date.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise CatalogueError("Limit must be between 1 and 500.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise CatalogueError("Offset must be a non-negative integer.")

    def albums(self, *, include_archived: bool = False) -> dict[str, Any]:
        return list_albums(
            database_path=self.database_path, include_archived=include_archived,
            safety_policy=self.policy,
        )

    def album(self, album_uuid: str) -> dict[str, Any]:
        return get_album(database_path=self.database_path, album_uuid=album_uuid,
                         safety_policy=self.policy)

    def album_members(self, album_uuid: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return list_album_members(
            database_path=self.database_path, album_uuid=album_uuid,
            limit=limit, offset=offset, safety_policy=self.policy,
        )

    def create_album(self, *, name: str, description: str | None, actor: str,
                     reason: str | None) -> dict[str, Any]:
        return create_album(database_path=self.database_path, name=name, description=description,
                            actor=actor, reason=reason, safety_policy=self.policy)

    def rename_album(self, *, album_uuid: str, name: str, actor: str,
                     reason: str | None) -> dict[str, Any]:
        return rename_album(database_path=self.database_path, album_uuid=album_uuid, name=name,
                            actor=actor, reason=reason, safety_policy=self.policy)

    def set_album_archived(self, *, album_uuid: str, archived: bool, actor: str,
                           reason: str | None) -> dict[str, Any]:
        operation = archive_album if archived else restore_album
        return operation(database_path=self.database_path, album_uuid=album_uuid, actor=actor,
                         reason=reason, safety_policy=self.policy)

    def set_album_membership(self, *, album_uuid: str, content_identity_id: int,
                             present: bool, actor: str, reason: str | None) -> dict[str, Any]:
        operation = add_content_to_album if present else remove_content_from_album
        return operation(database_path=self.database_path, album_uuid=album_uuid,
                         content_identity_id=content_identity_id, actor=actor,
                         reason=reason, safety_policy=self.policy)

    def albums_for_content(self, content_identity_id: int) -> dict[str, Any]:
        return list_albums_for_content(database_path=self.database_path,
                                       content_identity_id=content_identity_id,
                                       safety_policy=self.policy)

    def tags(self) -> dict[str, Any]:
        return list_tags(database_path=self.database_path, safety_policy=self.policy)

    def create_tag(self, *, name: str, namespace: str | None, actor: str,
                   reason: str | None) -> dict[str, Any]:
        return create_tag(database_path=self.database_path, name=name, namespace=namespace,
                          actor=actor, reason=reason, safety_policy=self.policy)

    def tags_for_content(self, content_identity_id: int) -> dict[str, Any]:
        return list_tags_for_content(database_path=self.database_path,
                                     content_identity_id=content_identity_id,
                                     safety_policy=self.policy)

    def set_tag_membership(self, *, tag_uuid: str, content_identity_id: int,
                           present: bool, actor: str, reason: str | None) -> dict[str, Any]:
        operation = add_tag_to_content if present else remove_tag_from_content
        return operation(database_path=self.database_path, tag_uuid=tag_uuid,
                         content_identity_id=content_identity_id, actor=actor,
                         reason=reason, safety_policy=self.policy)

    def organisation_history(self, *, album_uuid: str | None = None,
                             content_identity_id: int | None = None,
                             limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return _desktop_history_timestamps(organisation_history(
            database_path=self.database_path, album_uuid=album_uuid,
            content_identity_id=content_identity_id, limit=limit, offset=offset,
            safety_policy=self.policy,
        ))

    # Schema-10 preferred-date facade.
    def preferred_date_detail(
        self, content_identity_id: int, *, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        preferred = get_preferred_date(
            database_path=self.database_path, content_identity_id=content_identity_id,
            safety_policy=self.policy,
        )
        evidence = list_date_evidence(
            database_path=self.database_path, content_identity_id=content_identity_id,
            limit=limit, offset=offset, safety_policy=self.policy,
        )
        basis = list_preferred_basis(
            database_path=self.database_path, content_identity_id=content_identity_id,
            safety_policy=self.policy,
        )
        roles: dict[int, list[str]] = {}
        for row in basis["basis"]:
            if row["basis_state"] == "current":
                roles.setdefault(int(row["date_evidence_id"]), []).append(str(row["basis_role"]))
        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            metadata = {
                int(row["date_evidence_id"]): dict(row)
                for row in connection.execute(
                    """
                    SELECT e.date_evidence_id,pi.raw_relative_path,pi.current_observed_path,
                           s.display_name AS source_name
                    FROM content_date_evidence e
                    LEFT JOIN physical_instances pi
                      ON pi.physical_instance_id=e.physical_instance_id
                    LEFT JOIN sources s ON s.source_id=COALESCE(e.source_id,pi.source_id)
                    WHERE e.content_identity_id=?
                    """, (content_identity_id,),
                ).fetchall()
            }
        finally:
            connection.close()
        for row in evidence["evidence"]:
            row.update(metadata.get(int(row["date_evidence_id"]), {}))
            row["basis_roles"] = roles.get(int(row["date_evidence_id"]), [])
        return {**preferred, **evidence, **basis}

    def preferred_counts(self) -> dict[str, Any]:
        return preferred_date_counts(
            database_path=self.database_path, safety_policy=self.policy
        )

    def preferred_review_page(
        self, *, status: str, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        try:
            checked = PreferredStatus(status)
        except ValueError as exc:
            raise CatalogueError("Preferred-date status must be needs_review or unknown.") from exc
        if checked not in {PreferredStatus.NEEDS_REVIEW, PreferredStatus.UNKNOWN}:
            raise CatalogueError("Preferred-date review supports needs_review or unknown.")
        result = list_preferred_identities(
            database_path=self.database_path, status=checked, limit=limit, offset=offset,
            safety_policy=self.policy,
        )
        identities = [int(row["content_identity_id"]) for row in result["items"]]
        if not identities:
            return result
        placeholders = ",".join("?" for _ in identities)
        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            rows = connection.execute(
                f"""
                SELECT ci.content_identity_id,ci.identity_key,
                       pi.physical_instance_id,pi.current_observed_path,pi.raw_relative_path,
                       pi.size_bytes,pi.extension,pi.observed_created_at,pi.observed_modified_at,
                       s.display_name AS source,
                       (SELECT COUNT(*) FROM physical_instances copies
                        WHERE copies.content_identity_id=ci.content_identity_id)
                           AS physical_instance_count
                FROM content_identities ci
                LEFT JOIN physical_instances pi ON pi.physical_instance_id=(
                    SELECT candidate.physical_instance_id FROM physical_instances candidate
                    WHERE candidate.content_identity_id=ci.content_identity_id
                    ORDER BY candidate.current_observed_path IS NULL,
                             candidate.physical_instance_id LIMIT 1
                )
                LEFT JOIN sources s ON s.source_id=pi.source_id
                WHERE ci.content_identity_id IN ({placeholders})
                """, identities,
            ).fetchall()
        finally:
            connection.close()
        metadata = {int(row["content_identity_id"]): dict(row) for row in rows}
        for item in result["items"]:
            item.update(metadata[int(item["content_identity_id"])])
            item["preferred_status"] = item.get("status")
        return result

    def set_owner_date(
        self, *, content_identity_id: int, value: str, actor: str,
        action_id: str, reason: str | None, replace: bool,
    ) -> dict[str, Any]:
        operation = replace_owner_preferred_date if replace else set_owner_preferred_date
        return operation(
            database_path=self.database_path, content_identity_id=content_identity_id,
            value=value, actor=actor, action_id=action_id, reason=reason,
            safety_policy=self.policy,
        )

    # Schema-10 Collection facade. Each owner mutation retains its explicit action ID.
    def collections(
        self, *, state: str = "active", limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        return list_collections(
            database_path=self.database_path, state=state, limit=limit, offset=offset,
            safety_policy=self.policy,
        )

    def collection(self, collection_uuid: str) -> dict[str, Any]:
        return get_collection(
            database_path=self.database_path, collection_uuid=collection_uuid,
            safety_policy=self.policy,
        )

    def collection_members(
        self, collection_uuid: str, *, include_removed: bool = False,
        limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        result = list_collection_members(
            database_path=self.database_path, collection_uuid=collection_uuid,
            include_removed=include_removed, limit=limit, offset=offset,
            safety_policy=self.policy,
        )
        identities = [int(row["content_identity_id"]) for row in result["members"]]
        counts: dict[int, int] = {}
        if identities:
            placeholders = ",".join("?" for _ in identities)
            connection = connect_existing_catalogue(
                self.database_path, read_only=True, safety_policy=self.policy
            )
            try:
                counts = {
                    int(row["content_identity_id"]): int(row["album_count"])
                    for row in connection.execute(
                        f"""
                        SELECT am.content_identity_id,COUNT(*) AS album_count
                        FROM album_memberships am JOIN albums a ON a.album_id=am.album_id
                        WHERE am.membership_state='active' AND a.state='active'
                          AND am.content_identity_id IN ({placeholders})
                        GROUP BY am.content_identity_id
                        """, identities,
                    ).fetchall()
                }
            finally:
                connection.close()
        for row in result["members"]:
            row["album_count"] = counts.get(int(row["content_identity_id"]), 0)
        return result

    def collections_for_content(
        self, content_identity_id: int, *, include_removed: bool = False,
        limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        return list_collections_for_content(
            database_path=self.database_path, content_identity_id=content_identity_id,
            include_removed=include_removed, limit=limit, offset=offset,
            safety_policy=self.policy,
        )

    def create_collection(
        self, *, name: str, description: str | None, actor: str,
        action_id: str, reason: str | None,
    ) -> dict[str, Any]:
        return create_collection(
            database_path=self.database_path, name=name, description=description,
            actor=actor, action_id=action_id, reason=reason, safety_policy=self.policy,
        )

    def rename_collection(
        self, *, collection_uuid: str, name: str, actor: str,
        action_id: str, reason: str | None,
    ) -> dict[str, Any]:
        return rename_collection(
            database_path=self.database_path, collection_uuid=collection_uuid, name=name,
            actor=actor, action_id=action_id, reason=reason, safety_policy=self.policy,
        )

    def set_collection_archived(
        self, *, collection_uuid: str, archived: bool, actor: str,
        action_id: str, reason: str | None,
    ) -> dict[str, Any]:
        operation = archive_collection if archived else restore_collection
        return operation(
            database_path=self.database_path, collection_uuid=collection_uuid,
            actor=actor, action_id=action_id, reason=reason, safety_policy=self.policy,
        )

    def set_collection_membership(
        self, *, collection_uuid: str, content_identity_id: int,
        operation: str, actor: str, action_id: str, reason: str | None,
    ) -> dict[str, Any]:
        operations = {
            "add": add_content_to_collection,
            "remove": remove_content_from_collection,
            "restore": restore_content_to_collection,
        }
        if operation not in operations:
            raise CatalogueError("Collection membership operation is invalid.")
        return operations[operation](
            database_path=self.database_path, collection_uuid=collection_uuid,
            content_identity_id=content_identity_id, actor=actor,
            action_id=action_id, reason=reason, safety_policy=self.policy,
        )

    def collection_history(
        self, collection_uuid: str, *, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        result = collection_history(
            database_path=self.database_path, collection_uuid=collection_uuid,
            limit=limit, offset=offset, safety_policy=self.policy,
        )
        for row in result["history"]:
            row["collection_uuid"] = collection_uuid
        return _desktop_history_timestamps(result)

    def desktop_history(
        self, *, domain: str = "all", limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        """Return one bounded history page filtered by owner-facing domain."""

        if domain not in {"all", "albums_tags", "collections", "preferred_dates"}:
            raise CatalogueError("History domain is invalid.")
        self._validate_year_page(None, limit, offset)
        capabilities = self.schema_capabilities()
        if not capabilities["preferred_dates_enabled"]:
            if domain in {"collections", "preferred_dates"}:
                return {"history": [], "total_matching": 0, "limit": limit,
                        "offset": offset, "domain": domain}
            result = organisation_history(
                database_path=self.database_path, limit=limit, offset=offset,
                safety_policy=self.policy,
            )
            return _desktop_history_timestamps(result | {"domain": domain})
        clauses = {
            "all": "",
            "albums_tags": "WHERE oe.event_type LIKE 'album_%' OR oe.event_type LIKE 'tag_%'",
            "collections": "WHERE oe.event_type LIKE 'collection_%'",
            "preferred_dates": "WHERE oe.event_type LIKE 'preferred_date_%'",
        }
        where = clauses[domain]
        connection = connect_existing_catalogue(
            self.database_path, read_only=True, safety_policy=self.policy
        )
        try:
            rows = connection.execute(
                f"""
                SELECT oe.*,a.album_uuid,t.tag_uuid,c.collection_uuid
                FROM organisation_events oe
                LEFT JOIN albums a ON a.album_id=oe.album_id
                LEFT JOIN tags t ON t.tag_id=oe.tag_id
                LEFT JOIN collections c ON c.collection_id=oe.collection_id
                {where}
                ORDER BY oe.organisation_event_id DESC LIMIT ? OFFSET ?
                """, (limit, offset),
            ).fetchall()
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM organisation_events oe {where}"
            ).fetchone()[0])
        finally:
            connection.close()
        items = []
        for row in rows:
            item = dict(row)
            details = item.pop("details_json")
            try:
                item["details"] = json.loads(str(details))
            except (TypeError, ValueError):
                item["details"] = {"unparsed": str(details)}
            items.append(item)
        return _desktop_history_timestamps({
            "history": items, "total_matching": total, "limit": limit,
            "offset": offset, "domain": domain,
        })

    def decision_writes_enabled(self) -> bool:
        return bool(self.dashboard().get("decision_writes_enabled"))

    def nominate(
        self, *, context_type: str, context_id: int, physical_instance_id: int,
        canonical_scope: str, actor: str, reason: str | None = None,
    ) -> dict[str, Any]:
        self._require_writable_health()
        return nominate(
            database_path=self.database_path,
            event_id=f"desktop:{uuid4()}",
            context_type=context_type,
            context_id=context_id,
            physical_instance_id=physical_instance_id,
            canonical_scope=canonical_scope,
            owner=actor,
            reason=reason,
            safety_policy=self.policy,
        )

    def resolve_nomination(
        self, *, action: str, nomination_id: str, physical_instance_id: int,
        canonical_scope: str, actor: str, reason: str | None = None,
        prior_approval_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_writable_health()
        operations = {"approve": approve, "reject": reject, "supersede": supersede}
        if action not in operations:
            raise ValueError(f"Unsupported nomination action: {action}")
        arguments: dict[str, Any] = {
            "database_path": self.database_path,
            "event_id": f"desktop:{uuid4()}",
            "nomination_id": nomination_id,
            "physical_instance_id": physical_instance_id,
            "canonical_scope": canonical_scope,
            "owner": actor,
            "reason": reason,
            "safety_policy": self.policy,
        }
        if action == "supersede":
            arguments["prior_approval_id"] = prior_approval_id
        return operations[action](**arguments)

    def abstain(
        self, *, context_type: str, context_id: int, content_identity_id: int,
        canonical_scope: str, actor: str, reason: str | None = None,
        prior_approval_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_writable_health()
        return abstain(
            database_path=self.database_path,
            event_id=f"desktop:{uuid4()}",
            context_type=context_type,
            context_id=context_id,
            content_identity_id=content_identity_id,
            canonical_scope=canonical_scope,
            owner=actor,
            reason=reason,
            prior_approval_id=prior_approval_id,
            safety_policy=self.policy,
        )

    def _require_writable_health(self) -> None:
        if not self.decision_writes_enabled():
            raise RuntimeError("Catalogue health does not permit owner decision writes.")
