from __future__ import annotations

import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    get_catalogue_status,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import (
    CatalogueNotInitialisedError,
    CataloguePathError,
    SchemaVersionError,
)
from personal_librarian.catalogue.migrations import CURRENT_SCHEMA_VERSION
from personal_librarian.catalogue.models import (
    PATH_COMPARISON_KEY_VERSION,
    CanonicalScope,
    windows_path_comparison_key,
)
from personal_librarian.cli import main


EXPECTED_TABLES = {
    "schema_migrations",
    "sources",
    "acquisition_batches",
    "analysis_runs",
    "content_identities",
    "physical_instances",
    "hash_observations",
    "content_identity_hashes",
    "similarity_relationships",
    "decision_events",
    "evidence_import_stages",
    "inventory_observations",
    "instance_path_observations",
    "exact_duplicate_groups",
    "exact_duplicate_memberships",
    "content_hash_observations",
    "similarity_groups",
    "similarity_group_memberships",
    "similarity_group_relationships",
    "pipeline_jobs",
    "pipeline_job_items",
    "pipeline_hash_observations",
    "similarity_pipeline_jobs",
    "similarity_pipeline_items",
    "action_plans",
    "action_plan_items",
    "action_plan_preflight_results",
    "action_plan_events",
    "action_executions",
    "action_execution_events",
    "quarantine_records",
    "physical_instance_location_events",
    "catalogue_identity",
    "albums",
    "album_memberships",
    "tags",
    "content_tags",
    "organisation_events",
    "content_date_evidence",
    "content_preferred_dates",
    "preferred_date_basis",
    "date_evidence_jobs",
    "date_evidence_job_items",
    "collections",
    "collection_memberships",
}


class CatalogueTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "catalogue.sqlite3"

    def initialise(self) -> None:
        initialise_catalogue(self.database)

    def connection(self) -> sqlite3.Connection:
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.addCleanup(connection.close)
        return connection

    @staticmethod
    def add_source(connection: sqlite3.Connection, key: str = "source") -> int:
        cursor = connection.execute(
            "INSERT INTO sources(source_key, display_name, source_type) VALUES (?, ?, ?)",
            (key, key, "test"),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def add_run(connection: sqlite3.Connection, key: str = "run") -> int:
        cursor = connection.execute(
            "INSERT INTO analysis_runs(run_key, analysis_kind) VALUES (?, ?)",
            (key, "test"),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def add_content(connection: sqlite3.Connection, key: str) -> int:
        cursor = connection.execute(
            "INSERT INTO content_identities(identity_key) VALUES (?)",
            (key,),
        )
        return int(cursor.lastrowid)


class MigrationTests(CatalogueTestCase):
    def test_empty_catalogue_migrates_to_current_version(self) -> None:
        status = initialise_catalogue(self.database)
        self.assertEqual(status.schema_version, CURRENT_SCHEMA_VERSION)
        self.assertTrue(status.up_to_date)
        self.assertEqual(set(status.tables), EXPECTED_TABLES)

    def test_reopening_and_migration_are_idempotent(self) -> None:
        first = initialise_catalogue(self.database)
        second = initialise_catalogue(self.database)
        self.assertEqual(first.schema_version, second.schema_version)
        connection = self.connection()
        count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        self.assertEqual(count, CURRENT_SCHEMA_VERSION)

    def test_status_reopens_catalogue_read_only(self) -> None:
        self.initialise()
        status = get_catalogue_status(self.database)
        self.assertTrue(status.foreign_keys_enabled)
        self.assertEqual(status.schema_version, CURRENT_SCHEMA_VERSION)

    def test_future_schema_version_fails_safely(self) -> None:
        self.initialise()
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (CURRENT_SCHEMA_VERSION + 100, "future_schema"),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(SchemaVersionError):
            get_catalogue_status(self.database)

    def test_unrelated_database_is_not_adopted(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("CREATE TABLE unrelated(value TEXT)")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(CatalogueNotInitialisedError):
            initialise_catalogue(self.database)
        connection = sqlite3.connect(self.database)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        self.assertEqual(tables, {"unrelated"})

    def test_expected_indexes_and_append_only_triggers_exist(self) -> None:
        self.initialise()
        connection = self.connection()
        objects = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT type, name FROM sqlite_master WHERE type IN ('index', 'trigger')"
            )
        }
        self.assertIn(("index", "ix_hash_observations_digest"), objects)
        self.assertIn(("index", "ix_physical_instances_source_path_key"), objects)
        self.assertIn(("trigger", "decision_events_append_only_update"), objects)
        self.assertIn(("trigger", "decision_events_append_only_delete"), objects)
        self.assertIn(("trigger", "action_plans_snapshot_immutable"), objects)
        self.assertIn(("trigger", "action_preflight_append_only_update"), objects)
        self.assertIn(("trigger", "action_plan_events_append_only_delete"), objects)
        self.assertIn(("trigger", "action_execution_snapshot_immutable"), objects)
        self.assertIn(("trigger", "quarantine_record_snapshot_immutable"), objects)
        self.assertIn(("trigger", "action_execution_events_append_only_delete"), objects)
        self.assertIn(("trigger", "location_events_append_only_update"), objects)
        self.assertIn(("trigger", "catalogue_identity_snapshot_immutable"), objects)
        self.assertIn(("trigger", "catalogue_identity_production_one_way"), objects)
        self.assertIn(("trigger", "albums_no_delete"), objects)
        self.assertIn(("trigger", "album_memberships_snapshot_immutable"), objects)
        self.assertIn(("trigger", "organisation_events_append_only_delete"), objects)
        self.assertIn(("index", "ix_content_date_evidence_year_precision_content"), objects)
        self.assertIn(("index", "ix_content_preferred_dates_status_year_content"), objects)
        self.assertIn(("index", "ix_collection_memberships_content_state_collection"), objects)
        self.assertIn(("index", "ix_organisation_events_preferred_date"), objects)
        self.assertIn(("trigger", "content_date_evidence_append_only_update"), objects)
        self.assertIn(("trigger", "content_preferred_dates_validate_update"), objects)
        self.assertIn(("trigger", "collections_no_delete"), objects)
        self.assertIn(("trigger", "collection_memberships_no_delete"), objects)


class IntegrityTests(CatalogueTestCase):
    def test_foreign_keys_are_enabled_and_enforced(self) -> None:
        self.initialise()
        connection = self.connection()
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO acquisition_batches(source_id, batch_key) VALUES (?, ?)",
                (999999, "missing-source"),
            )

    def test_stable_source_key_is_unique(self) -> None:
        self.initialise()
        connection = self.connection()
        self.add_source(connection, "onedrive")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_source(connection, "onedrive")

    def test_instance_batch_must_belong_to_same_source(self) -> None:
        self.initialise()
        connection = self.connection()
        first_source = self.add_source(connection, "first")
        second_source = self.add_source(connection, "second")
        batch_id = connection.execute(
            "INSERT INTO acquisition_batches(source_id, batch_key) VALUES (?, ?)",
            (first_source, "batch"),
        ).lastrowid
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO physical_instances(
                    instance_key, source_id, acquisition_batch_id, raw_relative_path
                ) VALUES (?, ?, ?, ?)
                """,
                ("wrong-source", second_source, batch_id, "photo.jpg"),
            )

    def test_distinct_instances_can_map_to_one_content_identity(self) -> None:
        self.initialise()
        connection = self.connection()
        source_id = self.add_source(connection)
        content_id = self.add_content(connection, "content-one")
        for instance_key, raw_path in (("instance-a", "a.jpg"), ("instance-b", "copy\\a.jpg")):
            connection.execute(
                """
                INSERT INTO physical_instances(
                    instance_key, source_id, content_identity_id, raw_relative_path
                ) VALUES (?, ?, ?, ?)
                """,
                (instance_key, source_id, content_id, raw_path),
            )
        count = connection.execute(
            "SELECT COUNT(*) FROM physical_instances WHERE content_identity_id = ?",
            (content_id,),
        ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_similarity_keeps_content_identities_distinct(self) -> None:
        self.initialise()
        connection = self.connection()
        run_id = self.add_run(connection)
        left_id = self.add_content(connection, "content-left")
        right_id = self.add_content(connection, "content-right")
        connection.execute(
            """
            INSERT INTO similarity_relationships(
                relationship_key, left_content_identity_id, right_content_identity_id,
                analysis_run_id, phash_distance, dhash_distance, review_tier
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("similarity-one", left_id, right_id, run_id, 2, 4, "review"),
        )
        row = connection.execute(
            "SELECT left_content_identity_id, right_content_identity_id "
            "FROM similarity_relationships"
        ).fetchone()
        self.assertNotEqual(row[0], row[1])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM content_identities").fetchone()[0], 2)


class PathIdentityTests(CatalogueTestCase):
    def test_raw_unicode_paths_survive_comparison_key_collisions(self) -> None:
        self.initialise()
        connection = self.connection()
        source_id = self.add_source(connection)
        composed = "φωτογραφίες\\café.jpg"
        decomposed = unicodedata.normalize("NFD", composed)
        self.assertNotEqual(composed, decomposed)
        comparison_key = windows_path_comparison_key(composed)
        self.assertEqual(comparison_key, windows_path_comparison_key(decomposed))

        for instance_key, raw_path in (("unicode-nfc", composed), ("unicode-nfd", decomposed)):
            connection.execute(
                """
                INSERT INTO physical_instances(
                    instance_key, source_id, raw_relative_path,
                    relative_path_comparison_key, path_comparison_key_version
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    instance_key,
                    source_id,
                    raw_path,
                    comparison_key,
                    PATH_COMPARISON_KEY_VERSION,
                ),
            )

        rows = connection.execute(
            "SELECT raw_relative_path, relative_path_comparison_key "
            "FROM physical_instances ORDER BY instance_key"
        ).fetchall()
        self.assertEqual({rows[0][0], rows[1][0]}, {composed, decomposed})
        self.assertEqual(rows[0][1], rows[1][1])

    def test_database_path_must_be_safe_and_absolute(self) -> None:
        with self.assertRaises(CataloguePathError):
            initialise_catalogue(r"Z:\must-not-be-accessed.sqlite3")
        with self.assertRaises(CataloguePathError):
            initialise_catalogue("relative.sqlite3")


class DecisionHistoryTests(CatalogueTestCase):
    def test_both_canonical_scopes_support_explicit_owner_approval(self) -> None:
        self.initialise()
        connection = self.connection()
        content_id = self.add_content(connection, "decision-content")
        for index, scope in enumerate(CanonicalScope, start=1):
            connection.execute(
                """
                INSERT INTO decision_events(
                    decision_key, canonical_scope, event_type,
                    subject_content_identity_id, actor_type, actor_identifier,
                    owner_approved, reason, occurred_at
                ) VALUES (?, ?, 'approval', ?, 'owner', 'owner', 1, ?, ?)
                """,
                (
                    f"decision-{index}",
                    scope.value,
                    content_id,
                    "Test approval",
                    "2026-08-21T00:00:00Z",
                ),
            )
        scopes = {
            row[0]
            for row in connection.execute("SELECT canonical_scope FROM decision_events")
        }
        self.assertEqual(scopes, {"archival", "display_export"})

    def test_approval_requires_owner_and_history_is_append_only(self) -> None:
        self.initialise()
        connection = self.connection()
        content_id = self.add_content(connection, "decision-content")
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO decision_events(
                    decision_key, canonical_scope, event_type,
                    subject_content_identity_id, actor_type, actor_identifier,
                    owner_approved, occurred_at
                ) VALUES ('invalid', 'archival', 'approval', ?, 'system', 'system', 0, ?)
                """,
                (content_id, "2026-08-21T00:00:00Z"),
            )
        connection.execute(
            """
            INSERT INTO decision_events(
                decision_key, canonical_scope, event_type,
                subject_content_identity_id, actor_type, actor_identifier,
                owner_approved, occurred_at
            ) VALUES ('valid', 'archival', 'approval', ?, 'owner', 'owner', 1, ?)
            """,
            (content_id, "2026-08-21T00:00:00Z"),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            connection.execute(
                "UPDATE decision_events SET reason = 'changed' WHERE decision_key = 'valid'"
            )


class CatalogueCliTests(CatalogueTestCase):
    def call_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(arguments)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_catalogue_init_and_status_smoke(self) -> None:
        init_exit, init_output, _ = self.call_cli(
            ["catalogue", "init", "--database", str(self.database)]
        )
        self.assertEqual(init_exit, 0)
        self.assertIn(f"schema_version: {CURRENT_SCHEMA_VERSION}", init_output)

        status_exit, status_output, _ = self.call_cli(
            ["catalogue", "status", "--database", str(self.database)]
        )
        self.assertEqual(status_exit, 0)
        self.assertIn("foreign_keys: enabled", status_output)

    def test_status_does_not_create_missing_database(self) -> None:
        exit_code, _, _ = self.call_cli(
            ["catalogue", "status", "--database", str(self.database)]
        )
        self.assertEqual(exit_code, 2)
        self.assertFalse(self.database.exists())

    def test_cli_rejects_z_database_path_without_access(self) -> None:
        exit_code, _, stderr = self.call_cli(
            ["catalogue", "init", "--database", r"z:\never-access.sqlite3"]
        )
        self.assertEqual(exit_code, 2)
        self.assertIn("RETIRED_DRIVE", stderr)


if __name__ == "__main__":
    unittest.main()
