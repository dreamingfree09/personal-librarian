from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import MigrationError
from personal_librarian.catalogue.migrations import MIGRATIONS, apply_migrations, read_schema_version


OLD_EVENT_COLUMNS = (
    "organisation_event_id", "event_uuid", "event_type", "album_id",
    "album_membership_id", "tag_id", "content_tag_id", "content_identity_id",
    "actor_type", "actor_identifier", "provenance", "reason", "details_json",
    "recorded_at",
)


class Schema10TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "catalogue.sqlite3"
        initialise_catalogue(self.database)
        self.connection = connect_existing_catalogue(self.database, read_only=False)
        self.addCleanup(self.connection.close)
        self.source_a = int(self.connection.execute(
            "INSERT INTO sources(source_key, display_name, source_type) VALUES ('a', 'A', 'test')"
        ).lastrowid)
        self.source_b = int(self.connection.execute(
            "INSERT INTO sources(source_key, display_name, source_type) VALUES ('b', 'B', 'test')"
        ).lastrowid)
        self.content_a = int(self.connection.execute(
            "INSERT INTO content_identities(identity_key) VALUES ('content-a')"
        ).lastrowid)
        self.content_b = int(self.connection.execute(
            "INSERT INTO content_identities(identity_key) VALUES ('content-b')"
        ).lastrowid)
        self.instance_a = int(self.connection.execute(
            "INSERT INTO physical_instances(instance_key, source_id, content_identity_id, "
            "raw_relative_path) VALUES ('instance-a', ?, ?, 'a.jpg')",
            (self.source_a, self.content_a),
        ).lastrowid)
        self.run_id = int(self.connection.execute(
            "INSERT INTO analysis_runs(run_key, analysis_kind) VALUES ('date-run', 'date-evidence')"
        ).lastrowid)

    def owner_evidence(self, key: str = "owner", **changes: object) -> int:
        values: dict[str, object] = {
            "evidence_key": key,
            "content_identity_id": self.content_a,
            "physical_instance_id": None,
            "source_id": None,
            "evidence_type": "owner_set",
            "evidence_role": "owner_correction",
            "raw_value": "2024-02-29",
            "precision": "date",
            "time_precision": None,
            "date_year": 2024,
            "date_month": 2,
            "date_day": 29,
            "time_hour": None,
            "time_minute": None,
            "time_second": None,
            "time_fraction": None,
            "timezone_state": "not_applicable",
            "utc_offset_minutes": None,
            "actor_type": "owner",
            "actor_identifier": "owner",
            "provenance": "owner-test",
        }
        values.update(changes)
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        return int(self.connection.execute(
            f"INSERT INTO content_date_evidence({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        ).lastrowid)

    def system_evidence(self, key: str = "system", **changes: object) -> int:
        values: dict[str, object] = {
            "evidence_key": key,
            "content_identity_id": self.content_a,
            "physical_instance_id": self.instance_a,
            "source_id": self.source_a,
            "analysis_run_id": self.run_id,
            "evidence_type": "exif_datetime_original",
            "evidence_role": "observed",
            "source_field": "DateTimeOriginal",
            "source_locator": "EXIF",
            "raw_value": "2024:02:29 13:14:15.25",
            "precision": "datetime",
            "time_precision": "fraction",
            "date_year": 2024,
            "date_month": 2,
            "date_day": 29,
            "time_hour": 13,
            "time_minute": 14,
            "time_second": 15,
            "time_fraction": "25",
            "timezone_state": "known_offset",
            "utc_offset_minutes": 60,
            "timezone_name": "Europe/London",
            "extractor_name": "test-extractor",
            "extractor_version": "1",
            "actor_type": "system",
            "actor_identifier": "date-pipeline",
            "provenance": "test",
        }
        values.update(changes)
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        return int(self.connection.execute(
            f"INSERT INTO content_date_evidence({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        ).lastrowid)

    def insert_preferred(
        self, evidence_id: int, *, method: str = "owner_selection", actor: str = "owner",
        content_id: int | None = None, **changes: object,
    ) -> int:
        evidence = self.connection.execute(
            "SELECT * FROM content_date_evidence WHERE date_evidence_id = ?", (evidence_id,)
        ).fetchone()
        values: dict[str, object] = {
            "content_identity_id": content_id or self.content_a,
            "status": "resolved",
            "selection_method": method,
            "selected_evidence_id": evidence_id,
            "selected_precision": evidence["precision"],
            "selected_time_precision": evidence["time_precision"],
            "selected_year": evidence["date_year"],
            "selected_month": evidence["date_month"],
            "selected_day": evidence["date_day"],
            "selected_hour": evidence["time_hour"],
            "selected_minute": evidence["time_minute"],
            "selected_second": evidence["time_second"],
            "selected_fraction": evidence["time_fraction"],
            "selected_timezone_state": evidence["timezone_state"],
            "selected_utc_offset_minutes": evidence["utc_offset_minutes"],
            "actor_type": actor,
            "actor_identifier": actor,
            "provenance": "test",
            "determined_at": "2026-08-25T00:00:00Z",
        }
        values.update(changes)
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        return int(self.connection.execute(
            f"INSERT INTO content_preferred_dates({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        ).lastrowid)


class DateEvidenceConstraintTests(Schema10TestCase):
    def test_job_bookkeeping_is_resumable_and_relationship_safe(self) -> None:
        self.connection.execute(
            "INSERT INTO date_evidence_jobs(job_id, pipeline_version, policy_name, "
            "policy_version, config_fingerprint, config_json, analysis_run_id) "
            "VALUES ('job-1', '1', 'm30', '1', 'fingerprint', '{}', ?)",
            (self.run_id,),
        )
        self.connection.execute(
            "INSERT INTO date_evidence_job_items(job_id, item_key, content_identity_id, "
            "physical_instance_id, outcome, evidence_count, size_bytes_before, "
            "modified_time_ns_before, size_bytes_after, modified_time_ns_after, "
            "payload_json) VALUES ('job-1', 'item-1', ?, ?, 'recorded', 1, 10, 20, 10, 20, '{}')",
            (self.content_a, self.instance_a),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO date_evidence_job_items(job_id, item_key, content_identity_id, "
                "outcome, payload_json) VALUES ('job-1', 'item-1', ?, 'reused', '{}')",
                (self.content_a,),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "mismatch"):
            self.connection.execute(
                "INSERT INTO date_evidence_job_items(job_id, item_key, content_identity_id, "
                "physical_instance_id, outcome, payload_json) "
                "VALUES ('job-1', 'item-2', ?, ?, 'failed', '{}')",
                (self.content_b, self.instance_a),
            )

    def test_precision_calendar_and_timezone_shapes(self) -> None:
        no_time = dict(
            time_precision=None, time_hour=None, time_minute=None, time_second=None,
            time_fraction=None, timezone_state="not_applicable", utc_offset_minutes=None,
            timezone_name=None,
        )
        valid = (
            ("year", dict(raw_value="2020", precision="year", date_year=2020,
                          date_month=None, date_day=None, **no_time)),
            ("month", dict(raw_value="2020-02", precision="year_month", date_year=2020,
                           date_month=2, date_day=None, **no_time)),
            ("date", dict(raw_value="2020-02-29", precision="date", date_year=2020,
                          date_month=2, date_day=29, **no_time)),
            ("minute", dict(raw_value="2020-02-29 12:30", precision="datetime",
                            time_precision="minute", date_year=2020, date_month=2,
                            date_day=29, time_hour=12, time_minute=30,
                            time_second=None, time_fraction=None, timezone_state="unknown",
                            utc_offset_minutes=None, timezone_name=None)),
            ("second", dict(raw_value="2020-02-29 12:30:59", precision="datetime",
                            time_precision="second", date_year=2020, date_month=2,
                            date_day=29, time_hour=12, time_minute=30, time_second=59,
                            time_fraction=None, timezone_state="known_offset",
                            utc_offset_minutes=-300)),
            ("fraction", {}),
        )
        for key, changes in valid:
            self.system_evidence(key, **changes)

        invalid = (
            dict(key="bad-leap", date_year=2023, date_month=2, date_day=29),
            dict(key="fake-month", precision="year", date_month=1, date_day=None,
                 time_precision=None, time_hour=None, time_minute=None, time_second=None,
                 time_fraction=None, timezone_state="not_applicable",
                 utc_offset_minutes=None, timezone_name=None),
            dict(key="missing-day", precision="date", date_day=None, time_precision=None,
                 time_hour=None, time_minute=None, time_second=None, time_fraction=None,
                 timezone_state="not_applicable", utc_offset_minutes=None,
                 timezone_name=None),
            dict(key="minute-second", time_precision="minute", time_second=1,
                 time_fraction=None),
            dict(key="bad-fraction", time_fraction="1x"),
            dict(key="offset-unknown", timezone_state="unknown", utc_offset_minutes=60,
                 timezone_name=None),
            dict(key="offset-range", utc_offset_minutes=841),
        )
        for values in invalid:
            key = str(values.pop("key"))
            with self.subTest(key=key), self.assertRaises(sqlite3.IntegrityError):
                self.system_evidence(key, **values)

    def test_evidence_provenance_relationship_and_immutability(self) -> None:
        evidence_id = self.system_evidence()
        raw = self.connection.execute(
            "SELECT raw_value FROM content_date_evidence WHERE date_evidence_id = ?",
            (evidence_id,),
        ).fetchone()[0]
        self.assertEqual(raw, "2024:02:29 13:14:15.25")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.connection.execute(
                "UPDATE content_date_evidence SET raw_value = 'changed' WHERE date_evidence_id = ?",
                (evidence_id,),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.connection.execute(
                "DELETE FROM content_date_evidence WHERE date_evidence_id = ?", (evidence_id,)
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "mismatch"):
            self.system_evidence("wrong-content", content_identity_id=self.content_b)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "mismatch"):
            self.system_evidence("wrong-source", source_id=self.source_b)
        with self.assertRaises(sqlite3.IntegrityError):
            self.owner_evidence("owner-with-run", analysis_run_id=self.run_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.system_evidence("extractor-missing", extractor_name=None)


class PreferredDateConstraintTests(Schema10TestCase):
    def test_resolved_owner_and_policy_selection(self) -> None:
        owner = self.owner_evidence()
        preferred = self.insert_preferred(owner)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot be deleted"):
            self.connection.execute(
                "DELETE FROM content_preferred_dates WHERE preferred_date_id = ?", (preferred,)
            )

        system = self.system_evidence(
            content_identity_id=self.content_b, physical_instance_id=None, source_id=None
        )
        self.insert_preferred(
            system, method="policy_selection", actor="system", content_id=self.content_b,
            policy_name="m30", policy_version="1",
            determined_by_analysis_run_id=self.run_id,
        )

    def test_invalid_preferred_shapes_and_exact_projection(self) -> None:
        owner = self.owner_evidence()
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO content_preferred_dates(content_identity_id, status, "
                "selection_method, actor_type, actor_identifier, provenance, determined_at) "
                "VALUES (?, 'resolved', 'no_selection', 'system', 'system', 'test', 'now')",
                (self.content_a,),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "same content"):
            self.insert_preferred(owner, content_id=self.content_b)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "exactly project"):
            self.insert_preferred(owner, selected_day=28)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_preferred(
                owner, method="policy_selection", actor="system",
                policy_name=None, policy_version=None,
                determined_by_analysis_run_id=None,
            )
        system = self.system_evidence()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "exactly project"):
            self.insert_preferred(system, method="owner_selection", actor="owner")
        for status in ("needs_review", "unknown"):
            self.connection.execute(
                "INSERT INTO content_preferred_dates(content_identity_id, status, "
                "selection_method, actor_type, actor_identifier, provenance, determined_at) "
                "VALUES (?, ?, 'no_selection', 'system', 'system', 'test', 'now')",
                (self.content_a if status == "needs_review" else self.content_b, status),
            )

    def test_basis_state_uniqueness_and_content_consistency(self) -> None:
        evidence = self.owner_evidence()
        preferred = self.insert_preferred(evidence)
        self.connection.execute(
            "INSERT INTO preferred_date_basis(preferred_date_id, date_evidence_id, basis_role) "
            "VALUES (?, ?, 'selected')", (preferred, evidence),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO preferred_date_basis(preferred_date_id, date_evidence_id, "
                "basis_role) VALUES (?, ?, 'corroborating')", (preferred, evidence),
            )
        other = self.owner_evidence("other", content_identity_id=self.content_b)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "different content"):
            self.connection.execute(
                "INSERT INTO preferred_date_basis(preferred_date_id, date_evidence_id, "
                "basis_role) VALUES (?, ?, 'conflicting')", (preferred, other),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE preferred_date_basis SET basis_state = 'superseded'"
            )
        self.connection.execute(
            "UPDATE preferred_date_basis SET basis_state = 'superseded', "
            "superseded_at = '2026-08-25T01:00:00Z'"
        )


class CollectionAndHistoryTests(Schema10TestCase):
    def collection(self, uuid: str = "collection-1", name: str = "Family") -> int:
        return int(self.connection.execute(
            "INSERT INTO collections(collection_uuid, name, created_by, provenance_type, "
            "provenance) VALUES (?, ?, 'owner', 'owner', 'test')", (uuid, name),
        ).lastrowid)

    def test_collection_lifecycle_membership_and_no_delete(self) -> None:
        collection = self.collection()
        second = self.collection("collection-2")
        self.assertNotEqual(collection, second)
        membership = int(self.connection.execute(
            "INSERT INTO collection_memberships(collection_id, content_identity_id, "
            "created_by, provenance_type, provenance) VALUES (?, ?, 'owner', 'owner', 'test')",
            (collection, self.content_a),
        ).lastrowid)
        self.connection.execute(
            "UPDATE collection_memberships SET membership_state = 'removed', "
            "ended_at = '2026-08-25T00:00:00Z' WHERE collection_membership_id = ?",
            (membership,),
        )
        self.connection.execute(
            "UPDATE collection_memberships SET membership_state = 'active', ended_at = NULL "
            "WHERE collection_membership_id = ?", (membership,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE collections SET state = 'archived' WHERE collection_id = ?", (collection,)
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot be deleted"):
            self.connection.execute("DELETE FROM collections WHERE collection_id = ?", (collection,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot be deleted"):
            self.connection.execute(
                "DELETE FROM collection_memberships WHERE collection_membership_id = ?",
                (membership,),
            )

    def test_new_organisation_event_target_shapes(self) -> None:
        collection = self.collection()
        membership = int(self.connection.execute(
            "INSERT INTO collection_memberships(collection_id, content_identity_id, "
            "created_by, provenance_type, provenance) VALUES (?, ?, 'owner', 'owner', 'test')",
            (collection, self.content_a),
        ).lastrowid)
        evidence = self.owner_evidence()
        preferred = self.insert_preferred(evidence)
        common = "'owner', 'owner', 'test', '{}'"
        self.connection.execute(
            "INSERT INTO organisation_events(event_uuid, event_type, collection_id, actor_type, "
            f"actor_identifier, provenance, details_json) VALUES ('ce1', 'collection_created', ?, {common})",
            (collection,),
        )
        self.connection.execute(
            "INSERT INTO organisation_events(event_uuid, event_type, collection_id, "
            "collection_membership_id, content_identity_id, actor_type, actor_identifier, "
            f"provenance, details_json) VALUES ('ce2', 'collection_member_added', ?, ?, ?, {common})",
            (collection, membership, self.content_a),
        )
        self.connection.execute(
            "INSERT INTO organisation_events(event_uuid, event_type, preferred_date_id, "
            "content_identity_id, actor_type, actor_identifier, provenance, details_json) "
            f"VALUES ('pe1', 'preferred_date_owner_set', ?, ?, {common})",
            (preferred, self.content_a),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO organisation_events(event_uuid, event_type, collection_id, "
                "content_identity_id, actor_type, actor_identifier, provenance, details_json) "
                f"VALUES ('bad1', 'collection_created', ?, ?, {common})",
                (collection, self.content_a),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO organisation_events(event_uuid, event_type, preferred_date_id, "
                "actor_type, actor_identifier, provenance, details_json) "
                f"VALUES ('bad2', 'preferred_date_unknown', ?, {common})", (preferred,),
            )


class Schema10MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "schema9.sqlite3"

    def schema9_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        for migration in MIGRATIONS[:9]:
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, f"2026-08-{migration.version:02d}T00:00:00Z"),
            )
            connection.commit()
        return connection

    def populate_production_like(self, connection: sqlite3.Connection) -> dict[str, object]:
        connection.execute(
            "INSERT INTO catalogue_identity(singleton_id, catalogue_uuid, created_at, "
            "application_version, schema_version_at_bootstrap, catalogue_role, "
            "bootstrap_provenance_json, production_marked_at) VALUES "
            "(1, 'catalogue-stable', '2026-08-01T00:00:00Z', 'test', 8, 'production', "
            "'{\"source\":\"test\"}', '2026-08-01T00:00:00Z')"
        )
        source = int(connection.execute(
            "INSERT INTO sources(source_key, display_name, source_type) VALUES ('source', 'Source', 'test')"
        ).lastrowid)
        content_ids = []
        for number in (1, 2):
            content = int(connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES (?)", (f"content-{number}",)
            ).lastrowid)
            content_ids.append(content)
            connection.execute(
                "INSERT INTO physical_instances(instance_key, source_id, content_identity_id, "
                "raw_relative_path) VALUES (?, ?, ?, ?)",
                (f"instance-{number}", source, content, f"{number}.jpg"),
            )
        album = int(connection.execute(
            "INSERT INTO albums(album_uuid, name, description, created_at, created_by, "
            "provenance_type, provenance, updated_at) VALUES "
            "('christmas-uuid', 'Christmas', 'Christmas fixture', '2026-08-20T00:00:00Z', "
            "'owner', 'owner', 'fixture', '2026-08-20T00:00:00Z')"
        ).lastrowid)
        membership_ids = []
        for number, content in enumerate(content_ids, start=1):
            membership_ids.append(int(connection.execute(
                "INSERT INTO album_memberships(album_id, content_identity_id, created_at, "
                "created_by, provenance_type, provenance) VALUES "
                "(?, ?, ?, 'owner', 'owner', 'fixture')",
                (album, content, f"2026-08-2{number}T00:00:00Z"),
            ).lastrowid))
        events = (
            (1, "event-created", "album_created", None, None, "{\"n\":1}", "2026-08-20T01:00:00Z"),
            (2, "event-added-1", "album_member_added", membership_ids[0], content_ids[0],
             "{\"n\":2}", "2026-08-21T01:00:00Z"),
            (3, "event-added-2", "album_member_added", membership_ids[1], content_ids[1],
             "{\"n\":3}", "2026-08-22T01:00:00Z"),
        )
        for event_id, uuid, event_type, membership, content, details, recorded in events:
            connection.execute(
                "INSERT INTO organisation_events(organisation_event_id, event_uuid, event_type, "
                "album_id, album_membership_id, content_identity_id, actor_type, actor_identifier, "
                "provenance, reason, details_json, recorded_at) VALUES "
                "(?, ?, ?, ?, ?, ?, 'owner', 'owner', 'fixture', 'exact reason', ?, ?)",
                (event_id, uuid, event_type, album, membership, content, details, recorded),
            )
        connection.commit()
        return {"album": album, "content_ids": content_ids}

    def test_schema9_to_10_preserves_production_like_and_christmas_fixture(self) -> None:
        connection = self.schema9_connection()
        fixture = self.populate_production_like(connection)
        select_old = "SELECT " + ", ".join(OLD_EVENT_COLUMNS) + " FROM organisation_events ORDER BY 1"
        before_events = [tuple(row) for row in connection.execute(select_old)]
        before_album = tuple(connection.execute(
            "SELECT * FROM albums WHERE album_id = ?", (fixture["album"],)
        ).fetchone())
        before_memberships = [tuple(row) for row in connection.execute(
            "SELECT * FROM album_memberships ORDER BY album_membership_id"
        )]
        before_uuid = connection.execute(
            "SELECT catalogue_uuid FROM catalogue_identity WHERE singleton_id = 1"
        ).fetchone()[0]

        self.assertEqual(apply_migrations(connection), 10)
        self.assertEqual([tuple(row) for row in connection.execute(select_old)], before_events)
        self.assertEqual(tuple(connection.execute(
            "SELECT * FROM albums WHERE album_id = ?", (fixture["album"],)
        ).fetchone()), before_album)
        self.assertEqual([tuple(row) for row in connection.execute(
            "SELECT * FROM album_memberships ORDER BY album_membership_id"
        )], before_memberships)
        self.assertEqual(connection.execute(
            "SELECT catalogue_uuid FROM catalogue_identity WHERE singleton_id = 1"
        ).fetchone()[0], before_uuid)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM albums").fetchone()[0], 1)
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM album_memberships WHERE membership_state = 'active'"
        ).fetchone()[0], 2)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM content_tags").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM organisation_events").fetchone()[0], 3)
        for table in (
            "collections", "collection_memberships", "content_date_evidence",
            "content_preferred_dates", "preferred_date_basis",
        ):
            self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        christmas = connection.execute(
            "SELECT album_uuid, name, description, state FROM albums"
        ).fetchone()
        self.assertEqual(tuple(christmas),
                         ("christmas-uuid", "Christmas", "Christmas fixture", "active"))
        self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        connection.close()

    def test_deliberate_migration_failure_rolls_back_to_schema9(self) -> None:
        connection = self.schema9_connection()
        self.populate_production_like(connection)
        connection.execute("CREATE TABLE collections(collision TEXT)")
        connection.commit()
        before_events = connection.execute("SELECT COUNT(*) FROM organisation_events").fetchone()[0]
        with self.assertRaises(MigrationError):
            apply_migrations(connection)
        self.assertEqual(read_schema_version(connection), 9)
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM organisation_events"
        ).fetchone()[0], before_events)
        self.assertIsNone(connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'content_date_evidence'"
        ).fetchone())
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        connection.close()


if __name__ == "__main__":
    unittest.main()
