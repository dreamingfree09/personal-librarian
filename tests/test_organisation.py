from __future__ import annotations

import contextlib
import io
import json
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
from personal_librarian.catalogue.errors import OrganisationError
from personal_librarian.catalogue.migrations import MIGRATIONS
from personal_librarian.cli import main
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
    list_tags_for_content,
    list_year_content,
    organisation_history,
    remove_content_from_album,
    remove_tag_from_content,
    rename_album,
    restore_album,
)
from personal_librarian.production import create_backup, verify_backup


class OrganisationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "catalogue.sqlite3"
        initialise_catalogue(self.database)
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            source_id = int(connection.execute(
                "INSERT INTO sources(source_key, display_name, source_type) "
                "VALUES ('source', 'Source', 'test')"
            ).lastrowid)
            self.content_ids = []
            self.instance_ids = []
            for index, copies in ((1, 3), (2, 1)):
                content_id = int(connection.execute(
                    "INSERT INTO content_identities(identity_key) VALUES (?)",
                    (f"sha256:{index:064x}",),
                ).lastrowid)
                self.content_ids.append(content_id)
                for copy_index in range(copies):
                    instance_id = int(connection.execute(
                        """
                        INSERT INTO physical_instances(
                            instance_key, source_id, content_identity_id, raw_relative_path
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (f"instance-{index}-{copy_index}", source_id, content_id,
                         f"content-{index}-{copy_index}.jpg"),
                    ).lastrowid)
                    self.instance_ids.append(instance_id)
            connection.commit()
        finally:
            connection.close()

    def album(self, name: str = "Family") -> dict[str, object]:
        return create_album(
            database_path=self.database, name=name, description="Owner album",
            actor="owner", reason="Manual curation", provenance="owner-test",
        )

    def call_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_album_create_rename_archive_restore_and_duplicate_names(self) -> None:
        first = self.album()
        second = self.album()
        self.assertNotEqual(first["album_uuid"], second["album_uuid"])
        self.assertEqual(get_album(
            database_path=self.database, album_uuid=str(first["album_uuid"])
        )["active_same_name_count"], 2)

        renamed = rename_album(
            database_path=self.database, album_uuid=str(first["album_uuid"]),
            name="Family archive", actor="owner", reason="Clarify",
        )
        self.assertEqual(renamed["name"], "Family archive")
        self.assertEqual(renamed["album_uuid"], first["album_uuid"])
        archived = archive_album(
            database_path=self.database, album_uuid=str(first["album_uuid"]),
            actor="owner", reason="Pause curation",
        )
        self.assertEqual(archived["state"], "archived")
        self.assertNotIn(
            first["album_uuid"],
            {item["album_uuid"] for item in list_albums(database_path=self.database)["albums"]},
        )
        restored = restore_album(
            database_path=self.database, album_uuid=str(first["album_uuid"]), actor="owner"
        )
        self.assertEqual(restored["state"], "active")

    def test_create_album_description_actor_and_reason_are_independent(self) -> None:
        blank = create_album(
            database_path=self.database, name="Christmas", description=None,
            actor="owner-test", reason="Reason is not a description",
        )
        explicit = create_album(
            database_path=self.database, name="Summer", description="Summer photographs",
            actor="owner-test", reason=None,
        )
        self.assertIsNone(blank["description"])
        self.assertEqual(blank["created_by"], "owner-test")
        self.assertEqual(explicit["description"], "Summer photographs")
        history = organisation_history(database_path=self.database)["history"]
        blank_event = next(
            row for row in history
            if row["album_uuid"] == blank["album_uuid"] and row["event_type"] == "album_created"
        )
        self.assertEqual(blank_event["actor_identifier"], "owner-test")
        self.assertEqual(blank_event["reason"], "Reason is not a description")
        self.assertNotIn("description", blank_event["details"])

    def test_conservative_year_browse_unknown_and_album_presentation(self) -> None:
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            connection.execute(
                "UPDATE physical_instances SET observed_created_at = '2025-03-01T00:00:00Z', "
                "observed_modified_at = '2025-11-01T00:00:00Z' WHERE content_identity_id = ?",
                (self.content_ids[0],),
            )
            connection.execute(
                "UPDATE physical_instances SET observed_created_at = '2024-03-01T00:00:00Z', "
                "observed_modified_at = '2025-03-01T00:00:00Z' WHERE content_identity_id = ?",
                (self.content_ids[1],),
            )
            connection.commit()
        finally:
            connection.close()

        years = list_browse_years(database_path=self.database)["years"]
        self.assertEqual([(row["year"], row["content_count"]) for row in years], [(2025, 1), (None, 1)])
        known = list_year_content(database_path=self.database, year=2025, limit=1)
        unknown = list_year_content(database_path=self.database, year=None, limit=1)
        self.assertEqual(known["total_matching"], 1)
        self.assertEqual(known["content"][0]["physical_instance_count"], 3)
        self.assertEqual(known["content"][0]["evidence_state"], "consistent")
        self.assertEqual(unknown["content"][0]["evidence_state"], "conflicting")

        album = self.album("Athens & Piraeus")
        add_content_to_album(
            database_path=self.database, album_uuid=str(album["album_uuid"]),
            content_identity_id=self.content_ids[0], actor="owner",
        )
        presented = list_albums_for_browse_year(database_path=self.database, year=2025)
        self.assertEqual(presented["albums"][0]["year_member_count"], 1)
        self.assertEqual(presented["albums"][0]["member_count"], 1)
        self.assertEqual(
            list_albums_for_browse_year(database_path=self.database, year=None)["albums"], []
        )

    def test_membership_history_duplicate_add_and_safe_missing_remove(self) -> None:
        album = self.album()
        album_uuid = str(album["album_uuid"])
        added = add_content_to_album(
            database_path=self.database, album_uuid=album_uuid,
            content_identity_id=self.content_ids[0], actor="owner", reason="Include",
        )
        duplicate = add_content_to_album(
            database_path=self.database, album_uuid=album_uuid,
            content_identity_id=self.content_ids[0], actor="owner",
        )
        self.assertTrue(added["changed"])
        self.assertFalse(duplicate["changed"])
        removed = remove_content_from_album(
            database_path=self.database, album_uuid=album_uuid,
            content_identity_id=self.content_ids[0], actor="owner", reason="Remove",
        )
        self.assertEqual(removed["membership_state"], "removed")
        missing = remove_content_from_album(
            database_path=self.database, album_uuid=album_uuid,
            content_identity_id=self.content_ids[1], actor="owner",
        )
        self.assertFalse(missing["changed"])
        restored = add_content_to_album(
            database_path=self.database, album_uuid=album_uuid,
            content_identity_id=self.content_ids[0], actor="owner", reason="Restore",
        )
        self.assertEqual(restored["membership_state"], "active")
        events = organisation_history(
            database_path=self.database, album_uuid=album_uuid
        )["history"]
        event_types = [item["event_type"] for item in reversed(events)]
        self.assertEqual(
            event_types,
            ["album_created", "album_member_added", "album_member_removed",
             "album_member_restored"],
        )
        self.assertTrue(all(item["actor_identifier"] == "owner" for item in events))

    def test_exact_copies_are_one_member_and_near_contents_remain_independent(self) -> None:
        album = self.album()
        album_uuid = str(album["album_uuid"])
        add_content_to_album(
            database_path=self.database, album_uuid=album_uuid,
            content_identity_id=self.content_ids[0], actor="owner",
        )
        members = list_album_members(database_path=self.database, album_uuid=album_uuid)
        self.assertEqual(members["total_matching"], 1)
        self.assertEqual(members["members"][0]["physical_instance_count"], 3)
        self.assertEqual(
            list_albums_for_content(
                database_path=self.database, content_identity_id=self.content_ids[1]
            )["albums"],
            [],
        )
        add_content_to_album(
            database_path=self.database, album_uuid=album_uuid,
            content_identity_id=self.content_ids[1], actor="owner",
        )
        self.assertEqual(
            list_album_members(database_path=self.database, album_uuid=album_uuid)[
                "total_matching"
            ],
            2,
        )

    def test_archived_album_invalid_content_actor_and_name_validation(self) -> None:
        album = self.album()
        album_uuid = str(album["album_uuid"])
        archive_album(database_path=self.database, album_uuid=album_uuid, actor="owner")
        with self.assertRaisesRegex(OrganisationError, "read-only"):
            add_content_to_album(
                database_path=self.database, album_uuid=album_uuid,
                content_identity_id=self.content_ids[0], actor="owner",
            )
        with self.assertRaisesRegex(OrganisationError, "does not exist"):
            add_content_to_album(
                database_path=self.database, album_uuid=str(self.album("Other")["album_uuid"]),
                content_identity_id=999999, actor="owner",
            )
        with self.assertRaisesRegex(OrganisationError, "Actor"):
            create_album(database_path=self.database, name="Valid", actor="   ")
        with self.assertRaisesRegex(OrganisationError, "Album name"):
            create_album(database_path=self.database, name="", actor="owner")

    def test_history_and_entities_cannot_be_hard_deleted(self) -> None:
        album = self.album()
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot be deleted"):
                connection.execute(
                    "DELETE FROM albums WHERE album_uuid = ?", (album["album_uuid"],)
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("DELETE FROM organisation_events")
        finally:
            connection.close()

    def test_manual_tag_foundation_and_history(self) -> None:
        tag = create_tag(
            database_path=self.database, name="Game development",
            namespace="topic", actor="owner", reason="Manual topic",
        )
        tag_uuid = str(tag["tag_uuid"])
        added = add_tag_to_content(
            database_path=self.database, tag_uuid=tag_uuid,
            content_identity_id=self.content_ids[0], actor="owner",
        )
        self.assertTrue(added["changed"])
        self.assertEqual(
            list_tags_for_content(
                database_path=self.database, content_identity_id=self.content_ids[0]
            )["tags"][0]["name"],
            "Game development",
        )
        removed = remove_tag_from_content(
            database_path=self.database, tag_uuid=tag_uuid,
            content_identity_id=self.content_ids[0], actor="owner",
        )
        self.assertEqual(removed["membership_state"], "removed")

    def test_cli_album_workflow_and_actor_requirement(self) -> None:
        exit_code, output, _ = self.call_cli([
            "albums", "create", "--database", str(self.database),
            "--name", "CLI album", "--actor", "owner", "--format", "json",
        ])
        self.assertEqual(exit_code, 0)
        album_uuid = str(json.loads(output)["album_uuid"])
        exit_code, output, _ = self.call_cli([
            "albums", "add-content", album_uuid, str(self.content_ids[0]),
            "--database", str(self.database), "--actor", "owner", "--format", "json",
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(output)["changed"])
        exit_code, output, _ = self.call_cli([
            "albums", "members", album_uuid, "--database", str(self.database),
            "--format", "json",
        ])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output)["total_matching"], 1)
        with self.assertRaises(SystemExit):
            main([
                "albums", "rename", album_uuid, "--database", str(self.database),
                "--name", "Missing actor",
            ])


class OrganisationMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "schema8.sqlite3"

    def test_schema_8_to_current_preserves_existing_rows_and_starts_empty(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            for migration in MIGRATIONS[:8]:
                connection.executescript(migration.sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                    (migration.version, migration.name),
                )
                connection.commit()
            source_id = int(connection.execute(
                "INSERT INTO sources(source_key, display_name, source_type) "
                "VALUES ('existing', 'Existing', 'test')"
            ).lastrowid)
            content_id = int(connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES ('existing-content')"
            ).lastrowid)
            connection.execute(
                "INSERT INTO physical_instances(instance_key, source_id, content_identity_id, "
                "raw_relative_path) VALUES ('existing-instance', ?, ?, 'existing.jpg')",
                (source_id, content_id),
            )
            connection.commit()
        finally:
            connection.close()

        status = initialise_catalogue(self.database)
        self.assertEqual(status.schema_version, 10)
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM content_identities").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM physical_instances").fetchone()[0], 1)
            for table in ("albums", "album_memberships", "tags", "content_tags", "organisation_events"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        finally:
            connection.close()

    def test_pre_migration_schema_8_backup_is_created_and_verified(self) -> None:
        app_root = Path(self.temporary_directory.name) / "app-data"
        database = app_root / "catalogue" / "personal_librarian.sqlite3"
        database.parent.mkdir(parents=True)
        (app_root / "backups").mkdir()
        connection = sqlite3.connect(database)
        try:
            for migration in MIGRATIONS[:8]:
                connection.executescript(migration.sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                    (migration.version, migration.name),
                )
                connection.commit()
            connection.execute(
                """
                INSERT INTO catalogue_identity(
                    singleton_id, catalogue_uuid, created_at, application_version,
                    schema_version_at_bootstrap, catalogue_role,
                    bootstrap_provenance_json, production_marked_at
                ) VALUES (1, 'schema8-backup-test', '2026-08-24T00:00:00Z',
                          '0.1.0rc3', 8, 'production', '{}', '2026-08-24T00:00:00Z')
                """
            )
            connection.commit()
        finally:
            connection.close()
        backup = create_backup(
            app_data_root=app_root, reason="M28 pre-migration test"
        ).values
        self.assertEqual(backup["source_schema_version"], 8)
        verified = verify_backup(
            backup["manifest_path"], expected_catalogue_uuid="schema8-backup-test"
        ).values
        self.assertEqual(verified["result"], "ACCEPTED")
        self.assertEqual(verified["source_schema_version"], 8)


if __name__ == "__main__":
    unittest.main()
