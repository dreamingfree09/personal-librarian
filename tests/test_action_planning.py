from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.action_planning import (
    create_plan,
    invalidate_plan,
    plan_report,
    preflight_plan,
    show_plan,
)
from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import PlanningError
from personal_librarian.cli import _show_structured, build_parser
from personal_librarian.decisions import approve, nominate, reject, supersede
from personal_librarian.safety import assess_write_destination, windows_collision_key


class ActionPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        self.database = self.base / "catalogue.sqlite3"
        self.media = self.base / "media"
        self.destination = self.base / "destination"
        self.media.mkdir()
        self.destination.mkdir()
        initialise_catalogue(self.database)
        self._populate()

    def connection(self):
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.addCleanup(connection.close)
        return connection

    def _populate(self) -> None:
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            run_id = int(connection.execute(
                "INSERT INTO analysis_runs(run_key, analysis_kind) VALUES ('m18-fixture', 'test')"
            ).lastrowid)
            source_id = int(connection.execute(
                "INSERT INTO sources(source_key, display_name, source_type) "
                "VALUES ('fixture', 'Fixture', 'test')"
            ).lastrowid)
            content_bytes = b"same exact content"
            digest = hashlib.sha256(content_bytes).hexdigest()
            self.content_id = int(connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES (?)",
                (f"sha256:{digest}",),
            ).lastrowid)
            connection.execute(
                "INSERT INTO content_identity_hashes VALUES (?, 'SHA-256', ?, ?, "
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (self.content_id, digest, run_id),
            )
            self.instances = []
            self.source_paths = []
            for index in range(3):
                directory = self.media / f"copy-{index}"
                directory.mkdir()
                path = directory / "photo.jpg"
                path.write_bytes(content_bytes)
                modified_seconds, modified_nanoseconds = divmod(
                    path.stat().st_mtime_ns, 1_000_000_000
                )
                observed_modified = (
                    datetime.fromtimestamp(modified_seconds, timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    )
                    + f".{modified_nanoseconds:09d}Z"
                )
                self.source_paths.append(path)
                instance_id = int(connection.execute(
                    """
                    INSERT INTO physical_instances(
                        instance_key, source_id, content_identity_id, raw_relative_path,
                        current_observed_path, size_bytes, extension, observed_modified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '.jpg', ?)
                    """,
                    (
                        f"instance-{index}", source_id, self.content_id,
                        f"copy-{index}/photo.jpg", str(path), len(content_bytes),
                        observed_modified,
                    ),
                ).lastrowid)
                self.instances.append(instance_id)
            exact_group = int(connection.execute(
                """
                INSERT INTO exact_duplicate_groups(
                    group_key, content_identity_id, analysis_run_id, copies,
                    unique_sources, source_pattern, size_bytes, redundant_copies,
                    reclaimable_bytes
                ) VALUES ('exact', ?, ?, 3, 1, 'Fixture', ?, 2, ?)
                """,
                (self.content_id, run_id, len(content_bytes), len(content_bytes) * 2),
            ).lastrowid)
            for instance in self.instances:
                connection.execute(
                    "INSERT INTO exact_duplicate_memberships VALUES (?, ?, 3)",
                    (exact_group, instance),
                )

            other_id = int(connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES ('sha256:other')"
            ).lastrowid)
            relationship = int(connection.execute(
                """
                INSERT INTO similarity_relationships(
                    relationship_key, left_content_identity_id, right_content_identity_id,
                    analysis_run_id, phash_distance, dhash_distance
                ) VALUES ('similar', ?, ?, ?, 1, 1)
                """,
                (min(self.content_id, other_id), max(self.content_id, other_id), run_id),
            ).lastrowid)
            self.similarity_group = int(connection.execute(
                """
                INSERT INTO similarity_groups(
                    group_key, analysis_run_id, external_group_id, unique_contents,
                    candidate_pairs, min_phash_distance, max_phash_distance,
                    min_dhash_distance, max_dhash_distance, unique_sources,
                    sources_text, review_tier, is_large_ambiguous
                ) VALUES ('near', ?, 'near', 2, 1, 1, 1, 1, 1, 1, 'Fixture', 'review_only', 0)
                """,
                (run_id,),
            ).lastrowid)
            connection.execute(
                "INSERT INTO similarity_group_memberships VALUES (?, ?)",
                (self.similarity_group, self.content_id),
            )
            connection.execute(
                "INSERT INTO similarity_group_memberships VALUES (?, ?)",
                (self.similarity_group, other_id),
            )
            connection.execute(
                "INSERT INTO similarity_group_relationships VALUES (?, ?)",
                (self.similarity_group, relationship),
            )
            connection.commit()
        finally:
            connection.close()

    def approve_archival(self, physical: int | None = None, prefix: str = "initial") -> str:
        physical = physical or self.instances[0]
        nomination = f"{prefix}-nomination"
        approval = f"{prefix}-approval"
        nominate(
            database_path=self.database, event_id=nomination,
            context_type="exact", context_id=self.content_id,
            physical_instance_id=physical, canonical_scope="archival", owner="owner",
        )
        approve(
            database_path=self.database, event_id=approval, nomination_id=nomination,
            physical_instance_id=physical, canonical_scope="archival", owner="owner",
            reason="Approved for M18 test",
        )
        return approval

    def quarantine_plan(self, approval: str, sources: list[int] | None = None):
        return create_plan(
            database_path=self.database, policy_id="exact-duplicate-quarantine-v1",
            context_type="exact", context_id=self.content_id,
            canonical_scope="archival", approval_event_id=approval,
            destination_root=self.destination, owner="owner",
            source_physical_instance_ids=sources or [self.instances[1]],
            safety_margin_bytes=0,
        )

    def test_current_approval_required_and_scopes_are_distinct(self) -> None:
        nominate(
            database_path=self.database, event_id="pending", context_type="exact",
            context_id=self.content_id, physical_instance_id=self.instances[0],
            canonical_scope="archival", owner="owner",
        )
        with self.assertRaisesRegex(PlanningError, "approval"):
            self.quarantine_plan("pending")
        approval = "approved"
        approve(
            database_path=self.database, event_id=approval, nomination_id="pending",
            physical_instance_id=self.instances[0], canonical_scope="archival", owner="owner",
            reason="Approved for M18 test",
        )
        with self.assertRaisesRegex(PlanningError, "scope"):
            create_plan(
                database_path=self.database, policy_id="exact-duplicate-quarantine-v1",
                context_type="exact", context_id=self.content_id,
                canonical_scope="display_export", approval_event_id=approval,
                destination_root=self.destination, owner="owner",
                source_physical_instance_ids=[self.instances[1]],
            )

        nominate(
            database_path=self.database, event_id="rejected-nomination",
            context_type="exact", context_id=self.content_id,
            physical_instance_id=self.instances[1], canonical_scope="display_export",
            owner="owner",
        )
        reject(
            database_path=self.database, event_id="rejection",
            nomination_id="rejected-nomination", physical_instance_id=self.instances[1],
            canonical_scope="display_export", owner="owner", reason="Not selected",
        )
        with self.assertRaisesRegex(PlanningError, "approval"):
            create_plan(
                database_path=self.database,
                policy_id="canonical-copy-to-destination-v1",
                context_type="exact", context_id=self.content_id,
                canonical_scope="display_export", approval_event_id="rejection",
                destination_root=self.destination, owner="owner",
            )

    def test_deterministic_plan_items_quarantine_and_no_execution_command(self) -> None:
        approval = self.approve_archival()
        first = self.quarantine_plan(approval)
        second = self.quarantine_plan(approval)
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(first["items"][0]["item_id"], second["items"][0]["item_id"])
        self.assertEqual(first["operation"], "quarantine")
        restore = first["items"][0]["restore_provenance"]
        self.assertEqual(restore["original_physical_instance_id"], self.instances[1])
        self.assertFalse(first["execution_available"])
        plan_choices = build_parser()._subparsers._group_actions[0].choices["plan"]
        subcommands = plan_choices._subparsers._group_actions[0].choices
        self.assertNotIn("execute", subcommands)

        operations = {}
        for operation in ("copy", "move", "rename"):
            candidate = create_plan(
                database_path=self.database,
                policy_id=f"canonical-{operation}-to-destination-v1",
                context_type="exact", context_id=self.content_id,
                canonical_scope="archival", approval_event_id=approval,
                destination_root=self.destination, owner="owner", safety_margin_bytes=0,
            )
            operations[operation] = candidate["operation"]
        self.assertEqual(operations, {"copy": "copy", "move": "move", "rename": "rename"})
        self.assertEqual(
            windows_collision_key(r"C:\Target\Café.JPG"),
            windows_collision_key(r"c:\target\CAFÉ.jpg"),
        )
        connection = self.connection()
        connection.execute(
            "UPDATE physical_instances SET observed_modified_at = ? "
            "WHERE physical_instance_id = ?",
            ("2026-08-22T12:00:00.000000000Z", self.instances[1]),
        )
        connection.commit()
        refreshed = self.quarantine_plan(approval)
        self.assertNotEqual(first["plan_id"], refreshed["plan_id"])

    def test_safe_preflight_and_source_changes(self) -> None:
        approval = self.approve_archival()
        plan = self.quarantine_plan(approval)
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in self.source_paths]
        report = preflight_plan(
            database_path=self.database, plan_id=plan["plan_id"], actor="tester"
        )
        self.assertEqual(report["status"], "preflight_passed")
        self.assertEqual(report["dry_run_summary"]["pass"], 1)
        self.assertEqual(report["dry_run_summary"]["message"], "NO FILESYSTEM CHANGES WERE PERFORMED")
        self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in self.source_paths])

        self.source_paths[1].write_bytes(b"changed size")
        failed = preflight_plan(
            database_path=self.database, plan_id=plan["plan_id"], actor="tester"
        )
        self.assertEqual(failed["items"][0]["latest_preflight"]["source_state"], "source_size_changed")
        self.assertEqual(failed["status"], "preflight_failed")

    def test_mtime_catalogue_identity_and_missing_source_fail(self) -> None:
        approval = self.approve_archival()
        plan = self.quarantine_plan(approval)
        original = self.source_paths[1].stat().st_mtime_ns
        os.utime(self.source_paths[1], ns=(original + 1_000_000, original + 1_000_000))
        result = preflight_plan(
            database_path=self.database, plan_id=plan["plan_id"], actor="tester"
        )
        self.assertEqual(result["items"][0]["latest_preflight"]["source_state"], "source_mtime_changed")

        self.source_paths[1].unlink()
        result = preflight_plan(
            database_path=self.database, plan_id=plan["plan_id"], actor="tester"
        )
        self.assertEqual(result["items"][0]["latest_preflight"]["source_state"], "source_missing")

        connection = self.connection()
        connection.execute(
            "UPDATE physical_instances SET content_identity_id = NULL WHERE physical_instance_id = ?",
            (self.instances[1],),
        )
        connection.commit()
        result = preflight_plan(
            database_path=self.database, plan_id=plan["plan_id"], actor="tester"
        )
        self.assertEqual(
            result["items"][0]["latest_preflight"]["source_state"],
            "source_catalogue_snapshot_changed",
        )

    def test_destination_conflicts_and_planned_collision(self) -> None:
        approval = self.approve_archival()
        plan = self.quarantine_plan(approval)
        destination = Path(plan["items"][0]["destination_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.source_paths[1].read_bytes())
        same = preflight_plan(
            database_path=self.database, plan_id=plan["plan_id"], actor="tester"
        )
        self.assertEqual(
            same["items"][0]["latest_preflight"]["conflict_state"],
            "destination_exists_same_content",
        )
        destination.write_bytes(b"different")
        different = preflight_plan(
            database_path=self.database, plan_id=plan["plan_id"], actor="tester"
        )
        self.assertEqual(
            different["items"][0]["latest_preflight"]["conflict_state"],
            "destination_exists_different_content",
        )

        collision_plan = self.quarantine_plan(
            approval, [self.instances[1], self.instances[2]]
        )
        collision = preflight_plan(
            database_path=self.database, plan_id=collision_plan["plan_id"], actor="tester"
        )
        self.assertTrue(all(
            item["latest_preflight"]["conflict_state"] == "planned_item_destination_collision"
            for item in collision["items"]
        ))

    def test_stale_after_supersession_and_invalidation_history(self) -> None:
        approval = self.approve_archival()
        plan = self.quarantine_plan(approval)
        nominate(
            database_path=self.database, event_id="replacement-nomination",
            context_type="exact", context_id=self.content_id,
            physical_instance_id=self.instances[2], canonical_scope="archival", owner="owner",
        )
        supersede(
            database_path=self.database, event_id="replacement-approval",
            nomination_id="replacement-nomination", prior_approval_id=approval,
            physical_instance_id=self.instances[2], canonical_scope="archival", owner="owner",
            reason="Replacement approved for M18 test",
        )
        stale = preflight_plan(
            database_path=self.database, plan_id=plan["plan_id"], actor="tester"
        )
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["items"][0]["latest_preflight"]["overall_state"], "STALE")
        with self.assertRaisesRegex(PlanningError, "current effective approval"):
            self.quarantine_plan(approval, [self.instances[1]])
        invalidated = invalidate_plan(
            database_path=self.database, plan_id=plan["plan_id"],
            event_id="invalidate-plan", owner="owner", reason="Owner cancelled plan",
        )
        self.assertEqual(invalidated["status"], "invalidated")
        self.assertGreaterEqual(len(invalidated["events"]), 3)
        self.assertEqual(show_plan(
            database_path=self.database, plan_id=plan["plan_id"]
        )["item_count"], 1)
        connection = self.connection()
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE action_plans SET policy_id = 'changed' WHERE plan_key = ?",
                (plan["plan_id"],),
            )

    def test_destination_safety_z_relative_outside_and_reparse(self) -> None:
        approval = self.approve_archival()
        for root in ("relative-root", r"Z:\never-access"):
            with self.assertRaises(PlanningError):
                create_plan(
                    database_path=self.database,
                    policy_id="exact-duplicate-quarantine-v1",
                    context_type="exact", context_id=self.content_id,
                    canonical_scope="archival", approval_event_id=approval,
                    destination_root=root, owner="owner",
                    source_physical_instance_ids=[self.instances[1]],
                )
        outside = assess_write_destination(
            self.destination, self.base / "outside" / "photo.jpg"
        )
        self.assertFalse(outside.allowed)
        self.assertEqual(outside.code, "OUTSIDE_DESTINATION_ROOT")

        escape = self.destination / "exact"
        outside_root = self.base / "reparse-outside"
        outside_root.mkdir()
        try:
            escape.symlink_to(outside_root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Host cannot create directory symlink: {exc}")
        escaped = assess_write_destination(
            self.destination, escape / str(self.content_id) / "photo.jpg"
        )
        self.assertFalse(escaped.allowed)
        self.assertEqual(escaped.code, "REPARSE_ESCAPE")

    def test_free_space_fail_unknown_and_near_similarity_alone(self) -> None:
        approval = self.approve_archival()
        plan = self.quarantine_plan(approval)
        usage = shutil._ntuple_diskusage(total=100, used=100, free=0)
        with mock.patch("personal_librarian.action_planning.shutil.disk_usage", return_value=usage):
            failed = preflight_plan(
                database_path=self.database, plan_id=plan["plan_id"], actor="tester"
            )
        self.assertEqual(failed["items"][0]["latest_preflight"]["free_space_state"], "FAIL")
        with mock.patch(
            "personal_librarian.action_planning.shutil.disk_usage", side_effect=OSError("unknown")
        ):
            unknown = preflight_plan(
                database_path=self.database, plan_id=plan["plan_id"], actor="tester"
            )
        self.assertEqual(unknown["items"][0]["latest_preflight"]["free_space_state"], "UNKNOWN")
        with self.assertRaisesRegex(PlanningError, "approval"):
            create_plan(
                database_path=self.database,
                policy_id="canonical-copy-to-destination-v1",
                context_type="similar", context_id=self.similarity_group,
                canonical_scope="archival", approval_event_id="similarity-alone",
                destination_root=self.destination, owner="owner",
            )

    def test_z_source_is_rejected_without_access(self) -> None:
        approval = self.approve_archival()
        connection = self.connection()
        connection.execute(
            "UPDATE physical_instances SET current_observed_path = ? WHERE physical_instance_id = ?",
            (r"Z:\never-access.jpg", self.instances[1]),
        )
        connection.commit()
        with self.assertRaisesRegex(PlanningError, "RETIRED_DRIVE"):
            self.quarantine_plan(approval)

    def test_structured_cli_output_survives_legacy_windows_encoding(self) -> None:
        raw = io.BytesIO()
        output = io.TextIOWrapper(raw, encoding="cp1252", write_through=True)
        with mock.patch("sys.stdout", output):
            _show_structured({"path": "Φωτογραφίες"}, "json")
        rendered = raw.getvalue().decode("cp1252")
        self.assertEqual(json.loads(rendered), {"path": "Φωτογραφίες"})
        self.assertIn(r"\u03a6", rendered)


if __name__ == "__main__":
    unittest.main()
