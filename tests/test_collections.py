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

from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.errors import CollectionError
from personal_librarian.catalogue.migrations import MIGRATIONS
from personal_librarian.cli import main
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
from personal_librarian.date_evidence import set_owner_preferred_date


class CollectionServiceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "catalogue.sqlite3"
        initialise_catalogue(self.database)
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.source_id = int(connection.execute(
            "INSERT INTO sources(source_key,display_name,source_type) VALUES('s','Source','test')"
        ).lastrowid)
        self.content_a = int(connection.execute(
            "INSERT INTO content_identities(identity_key) VALUES('content-a')"
        ).lastrowid)
        self.content_b = int(connection.execute(
            "INSERT INTO content_identities(identity_key) VALUES('content-b')"
        ).lastrowid)
        for number in range(3):
            connection.execute(
                "INSERT INTO physical_instances(instance_key,source_id,content_identity_id,"
                "raw_relative_path,size_bytes) VALUES(?,?,?,?,?)",
                (f"exact-{number}", self.source_id, self.content_a,
                 f"family/exact-{number}.jpg", 100 + number),
            )
        connection.execute(
            "INSERT INTO physical_instances(instance_key,source_id,content_identity_id,"
            "raw_relative_path,size_bytes) VALUES('similar',?,?, 'family/similar.jpg',200)",
            (self.source_id, self.content_b),
        )
        connection.commit()
        connection.close()

    def create(
        self, name: str = "Family", action_id: str = "create-family",
        description: str | None = "Family photographs",
    ) -> dict[str, object]:
        return create_collection(
            database_path=self.database, name=name, description=description,
            actor="owner", action_id=action_id, reason="test reason",
            provenance="owner-test",
        )

    def event_count(self, collection_uuid: str) -> int:
        return int(collection_history(
            database_path=self.database, collection_uuid=collection_uuid
        )["total_matching"])


class CollectionCreationAndLifecycleTests(CollectionServiceCase):
    def test_create_duplicate_names_idempotency_and_validation(self) -> None:
        first = self.create()
        replay = self.create()
        duplicate = self.create(action_id="create-family-two")
        self.assertTrue(first["changed"])
        self.assertFalse(replay["changed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["collection_uuid"], replay["collection_uuid"])
        self.assertNotEqual(first["collection_uuid"], duplicate["collection_uuid"])
        self.assertEqual(duplicate["duplicate_name_count"], 2)
        self.assertEqual(list_collections(
            database_path=self.database
        )["total_matching"], 2)
        with self.assertRaises(CollectionError):
            self.create(name="   ", action_id="invalid")
        with self.assertRaisesRegex(CollectionError, "different request"):
            self.create(name="Other", action_id="create-family")
        with self.assertRaisesRegex(CollectionError, "different request"):
            create_collection(
                database_path=self.database, name="Family",
                description="Family photographs", actor="owner",
                action_id="create-family", reason="new reason",
                provenance="owner-test",
            )

    def test_rename_noop_duplicate_name_and_archived_rejection(self) -> None:
        first = self.create()
        second = self.create(name="Holidays", action_id="create-holidays")
        uuid = str(first["collection_uuid"])
        renamed = rename_collection(
            database_path=self.database, collection_uuid=uuid, name="Holidays",
            actor="owner", action_id="rename-family", reason="Combine names",
            provenance="owner-test",
        )
        self.assertTrue(renamed["changed"])
        self.assertEqual(renamed["duplicate_name_count"], 2)
        before_events = self.event_count(uuid)
        noop = rename_collection(
            database_path=self.database, collection_uuid=uuid, name="Holidays",
            actor="owner", action_id="rename-noop",
        )
        self.assertFalse(noop["changed"])
        self.assertEqual(self.event_count(uuid), before_events)
        replay = rename_collection(
            database_path=self.database, collection_uuid=uuid, name="Holidays",
            actor="owner", action_id="rename-family", reason="Combine names",
            provenance="owner-test",
        )
        self.assertTrue(replay["replayed"])
        archive_collection(
            database_path=self.database, collection_uuid=uuid, actor="owner",
            action_id="archive-before-rename",
        )
        replay_after_archive = rename_collection(
            database_path=self.database, collection_uuid=uuid, name="Holidays",
            actor="owner", action_id="rename-family", reason="Combine names",
            provenance="owner-test",
        )
        self.assertTrue(replay_after_archive["replayed"])
        with self.assertRaisesRegex(CollectionError, "read-only"):
            rename_collection(
                database_path=self.database, collection_uuid=uuid, name="Archived rename",
                actor="owner", action_id="bad-rename",
            )
        self.assertEqual(second["state"], "active")

    def test_archive_restore_timestamps_idempotency_and_membership_gate(self) -> None:
        collection = self.create()
        uuid = str(collection["collection_uuid"])
        archived = archive_collection(
            database_path=self.database, collection_uuid=uuid,
            actor="owner", action_id="archive", reason="Pause",
        )
        self.assertEqual(archived["state"], "archived")
        self.assertIsNotNone(archived["archived_at"])
        event_count = self.event_count(uuid)
        repeated = archive_collection(
            database_path=self.database, collection_uuid=uuid,
            actor="owner", action_id="archive-again",
        )
        self.assertFalse(repeated["changed"])
        self.assertEqual(self.event_count(uuid), event_count)
        with self.assertRaisesRegex(CollectionError, "Archived"):
            add_content_to_collection(
                database_path=self.database, collection_uuid=uuid,
                content_identity_id=self.content_a, actor="owner", action_id="blocked-add",
            )
        restored = restore_collection(
            database_path=self.database, collection_uuid=uuid,
            actor="owner", action_id="restore", reason="Continue",
        )
        self.assertEqual(restored["state"], "active")
        self.assertIsNone(restored["archived_at"])
        event_count = self.event_count(uuid)
        repeated = restore_collection(
            database_path=self.database, collection_uuid=uuid,
            actor="owner", action_id="restore-again",
        )
        self.assertFalse(repeated["changed"])
        self.assertEqual(self.event_count(uuid), event_count)


class CollectionMembershipAndQueryTests(CollectionServiceCase):
    def test_membership_lifecycle_idempotency_and_explicit_restore(self) -> None:
        collection = self.create()
        uuid = str(collection["collection_uuid"])
        added = add_content_to_collection(
            database_path=self.database, collection_uuid=uuid,
            content_identity_id=self.content_a, actor="owner", action_id="add-a",
        )
        self.assertTrue(added["changed"])
        event_count = self.event_count(uuid)
        duplicate = add_content_to_collection(
            database_path=self.database, collection_uuid=uuid,
            content_identity_id=self.content_a, actor="owner", action_id="add-a-again",
        )
        self.assertFalse(duplicate["changed"])
        self.assertEqual(self.event_count(uuid), event_count)
        removed = remove_content_from_collection(
            database_path=self.database, collection_uuid=uuid,
            content_identity_id=self.content_a, actor="owner", action_id="remove-a",
        )
        self.assertEqual(removed["membership_state"], "removed")
        self.assertIsNotNone(removed["ended_at"])
        event_count = self.event_count(uuid)
        repeated = remove_content_from_collection(
            database_path=self.database, collection_uuid=uuid,
            content_identity_id=self.content_a, actor="owner", action_id="remove-a-again",
        )
        self.assertFalse(repeated["changed"])
        self.assertEqual(self.event_count(uuid), event_count)
        with self.assertRaisesRegex(CollectionError, "restored explicitly"):
            add_content_to_collection(
                database_path=self.database, collection_uuid=uuid,
                content_identity_id=self.content_a, actor="owner", action_id="bad-readd",
            )
        restored = restore_content_to_collection(
            database_path=self.database, collection_uuid=uuid,
            content_identity_id=self.content_a, actor="owner", action_id="restore-a",
        )
        self.assertEqual(restored["membership_state"], "active")
        self.assertIsNone(restored["ended_at"])
        event_count = self.event_count(uuid)
        repeated = restore_content_to_collection(
            database_path=self.database, collection_uuid=uuid,
            content_identity_id=self.content_a, actor="owner", action_id="restore-a-again",
        )
        self.assertFalse(repeated["changed"])
        self.assertEqual(self.event_count(uuid), event_count)
        with self.assertRaisesRegex(CollectionError, "does not exist"):
            add_content_to_collection(
                database_path=self.database, collection_uuid=uuid,
                content_identity_id=999999, actor="owner", action_id="bad-content",
            )
        archive_collection(
            database_path=self.database, collection_uuid=uuid,
            actor="owner", action_id="archive-membership",
        )
        replay_after_archive = add_content_to_collection(
            database_path=self.database, collection_uuid=uuid,
            content_identity_id=self.content_a, actor="owner", action_id="add-a",
        )
        self.assertTrue(replay_after_archive["replayed"])

    def test_exact_identity_is_one_member_and_similar_identity_is_independent(self) -> None:
        collection = self.create()
        uuid = str(collection["collection_uuid"])
        set_owner_preferred_date(
            database_path=self.database, content_identity_id=self.content_a,
            value="2001-02", actor="owner", action_id="date-a",
        )
        for content_id, action in ((self.content_a, "add-a"), (self.content_b, "add-b")):
            add_content_to_collection(
                database_path=self.database, collection_uuid=uuid,
                content_identity_id=content_id, actor="owner", action_id=action,
            )
        members = list_collection_members(
            database_path=self.database, collection_uuid=uuid
        )
        self.assertEqual(members["total_matching"], 2)
        exact = next(row for row in members["members"]
                     if row["content_identity_id"] == self.content_a)
        similar = next(row for row in members["members"]
                       if row["content_identity_id"] == self.content_b)
        self.assertEqual(exact["physical_instance_count"], 3)
        self.assertEqual(exact["selected_year"], 2001)
        self.assertEqual(similar["physical_instance_count"], 1)
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM collection_memberships WHERE collection_id=?",
                (collection["collection_id"],),
            ).fetchone()[0], 2)
        finally:
            connection.close()

    def test_bounded_queries_removed_members_and_collections_for_content(self) -> None:
        first = self.create()
        second = self.create(name="Holidays", action_id="create-holidays")
        for collection, action in ((first, "first-add"), (second, "second-add")):
            add_content_to_collection(
                database_path=self.database,
                collection_uuid=str(collection["collection_uuid"]),
                content_identity_id=self.content_a, actor="owner", action_id=action,
            )
        remove_content_from_collection(
            database_path=self.database, collection_uuid=str(first["collection_uuid"]),
            content_identity_id=self.content_a, actor="owner", action_id="first-remove",
        )
        page = list_collections(
            database_path=self.database, state="all", limit=1, offset=1
        )
        self.assertEqual(page["total_matching"], 2)
        self.assertEqual(len(page["collections"]), 1)
        active_members = list_collection_members(
            database_path=self.database, collection_uuid=str(first["collection_uuid"])
        )
        all_members = list_collection_members(
            database_path=self.database, collection_uuid=str(first["collection_uuid"]),
            include_removed=True,
        )
        self.assertEqual(active_members["total_matching"], 0)
        self.assertEqual(all_members["total_matching"], 1)
        current = list_collections_for_content(
            database_path=self.database, content_identity_id=self.content_a
        )
        all_for_content = list_collections_for_content(
            database_path=self.database, content_identity_id=self.content_a,
            include_removed=True, limit=1,
        )
        self.assertEqual(current["total_matching"], 1)
        self.assertEqual(all_for_content["total_matching"], 2)
        self.assertEqual(len(all_for_content["collections"]), 1)
        shown = get_collection(
            database_path=self.database, collection_uuid=str(first["collection_uuid"])
        )
        self.assertEqual(shown["active_member_count"], 0)
        self.assertEqual(shown["removed_member_count"], 1)

    def test_history_targets_actor_reason_provenance_and_append_only(self) -> None:
        collection = self.create()
        uuid = str(collection["collection_uuid"])
        add_content_to_collection(
            database_path=self.database, collection_uuid=uuid,
            content_identity_id=self.content_a, actor="owner", action_id="add",
            reason="Include family", provenance="owner-explicit",
        )
        history = collection_history(
            database_path=self.database, collection_uuid=uuid, limit=1
        )
        self.assertEqual(history["total_matching"], 2)
        event = history["history"][0]
        self.assertEqual(event["event_type"], "collection_member_added")
        self.assertEqual(event["collection_id"], collection["collection_id"])
        self.assertIsNotNone(event["collection_membership_id"])
        self.assertEqual(event["content_identity_id"], self.content_a)
        self.assertEqual(event["actor_type"], "owner")
        self.assertEqual(event["actor_identifier"], "owner")
        self.assertEqual(event["provenance"], "owner-explicit")
        self.assertEqual(event["reason"], "Include family")
        self.assertEqual(event["details"]["action_id"], "add")
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute(
                    "UPDATE organisation_events SET reason='changed' "
                    "WHERE organisation_event_id=?", (event["organisation_event_id"],),
                )
        finally:
            connection.close()


class CollectionCliAndSchemaTests(CollectionServiceCase):
    def call_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_confirmation_create_add_remove_smoke(self) -> None:
        common = ["--database", str(self.database), "--actor", "owner"]
        code, _, error = self.call_cli([
            "collections", "create", *common, "--action-id", "cli-create",
            "--name", "Family", "--format", "json",
        ])
        self.assertEqual(code, 2)
        self.assertIn("confirm-collection-action", error)
        code, output, _ = self.call_cli([
            "collections", "create", *common, "--action-id", "cli-create",
            "--name", "Family", "--confirm-collection-action", "--format", "json",
        ])
        self.assertEqual(code, 0)
        collection_uuid = str(json.loads(output)["collection_uuid"])
        code, output, _ = self.call_cli([
            "collections", "add", collection_uuid, str(self.content_a), *common,
            "--action-id", "cli-add", "--confirm-collection-action", "--format", "json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["membership_state"], "active")
        code, output, _ = self.call_cli([
            "collections", "remove", collection_uuid, str(self.content_a), *common,
            "--action-id", "cli-remove", "--confirm-collection-action", "--format", "json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["membership_state"], "removed")

    def test_schema9_is_rejected_without_migration(self) -> None:
        database = Path(self.temporary_directory.name) / "schema9.sqlite3"
        connection = sqlite3.connect(database)
        for migration in MIGRATIONS[:9]:
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations(version,name) VALUES(?,?)",
                (migration.version, migration.name),
            )
            connection.commit()
        connection.close()
        with self.assertRaisesRegex(CollectionError, "schema 10"):
            list_collections(database_path=database)


if __name__ == "__main__":
    unittest.main()
