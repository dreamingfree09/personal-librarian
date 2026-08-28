from __future__ import annotations

import hashlib
import os
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

from personal_librarian.action_planning import create_plan, preflight_plan
from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import PlanningError, QuarantineError
from personal_librarian.cli import build_parser
from personal_librarian.decisions import approve, nominate, supersede
from personal_librarian.quarantine import (
    _execution_destination,
    execute_quarantine,
    quarantine_history,
    quarantine_status,
    reconcile_quarantine,
    restore_quarantine,
)


class QuarantineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.database = self.base / "catalogue.sqlite3"
        self.media = self.base / "media"
        self.quarantine_root = self.base / "quarantine"
        self.media.mkdir()
        self.quarantine_root.mkdir()
        initialise_catalogue(self.database)
        self.content = b"exact duplicate fixture"
        self.digest = hashlib.sha256(self.content).hexdigest()
        self._populate()

    def connection(self):
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.addCleanup(connection.close)
        return connection

    def _populate(self) -> None:
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            run_id = int(connection.execute(
                "INSERT INTO analysis_runs(run_key, analysis_kind) VALUES ('m19-run', 'test')"
            ).lastrowid)
            source_id = int(connection.execute(
                "INSERT INTO sources(source_key, display_name, source_type) "
                "VALUES ('fixture', 'Fixture', 'test')"
            ).lastrowid)
            self.content_id = int(connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES (?)",
                (f"sha256:{self.digest}",),
            ).lastrowid)
            connection.execute(
                "INSERT INTO content_identity_hashes VALUES (?, 'SHA-256', ?, ?, "
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (self.content_id, self.digest, run_id),
            )
            self.paths: list[Path] = []
            self.instances: list[int] = []
            for index in range(3):
                directory = self.media / f"copy-{index}"
                directory.mkdir()
                path = directory / "photo.jpg"
                path.write_bytes(self.content)
                self.paths.append(path)
                seconds, nanoseconds = divmod(path.stat().st_mtime_ns, 1_000_000_000)
                observed = (
                    datetime.fromtimestamp(seconds, timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    )
                    + f".{nanoseconds:09d}Z"
                )
                instance = int(connection.execute(
                    """
                    INSERT INTO physical_instances(
                        instance_key, source_id, content_identity_id, raw_relative_path,
                        current_observed_path, size_bytes, observed_modified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"instance-{index}", source_id, self.content_id,
                        f"copy-{index}/photo.jpg", str(path), len(self.content), observed,
                    ),
                ).lastrowid)
                self.instances.append(instance)
            connection.commit()
        finally:
            connection.close()

    def approve(self, physical: int | None = None, prefix: str = "initial") -> str:
        physical = self.instances[0] if physical is None else physical
        nomination = f"{prefix}-nomination"
        approval = f"{prefix}-approval"
        nominate(
            database_path=self.database, event_id=nomination, context_type="exact",
            context_id=self.content_id, physical_instance_id=physical,
            canonical_scope="archival", owner="owner", reason="M19 test nomination",
        )
        approve(
            database_path=self.database, event_id=approval, nomination_id=nomination,
            physical_instance_id=physical, canonical_scope="archival", owner="owner",
            reason="M19 test approval",
        )
        return approval

    def ready_plan(self) -> dict[str, object]:
        approval = self.approve()
        plan = create_plan(
            database_path=self.database, policy_id="exact-duplicate-quarantine-v1",
            context_type="exact", context_id=self.content_id,
            canonical_scope="archival", approval_event_id=approval,
            destination_root=self.quarantine_root, owner="owner",
            source_physical_instance_ids=[self.instances[1]], safety_margin_bytes=0,
        )
        report = preflight_plan(
            database_path=self.database, plan_id=str(plan["plan_id"]), actor="preflight"
        )
        self.assertEqual(report["status"], "preflight_passed")
        return report

    def execute(self, plan: dict[str, object]) -> dict[str, object]:
        return execute_quarantine(
            database_path=self.database, plan_id=str(plan["plan_id"]),
            item_id=str(plan["items"][0]["item_id"]),
            quarantine_root=self.quarantine_root, actor="executor",
            confirm_quarantine=True,
        )

    def actual_destination(self, plan: dict[str, object]) -> Path:
        return Path(_execution_destination(
            str(self.quarantine_root), str(plan["plan_id"]),
            str(plan["items"][0]["item_id"]), str(self.paths[1]),
        ))

    def test_exact_quarantine_success_restore_and_provenance(self) -> None:
        plan = self.ready_plan()
        original_identity = self.content_id
        canonical_before = (self.paths[0].read_bytes(), self.paths[0].stat().st_mtime_ns)
        result = self.execute(plan)
        destination = Path(str(result["destination_path"]))
        self.assertEqual(result["status"], "succeeded")
        self.assertFalse(self.paths[1].exists())
        self.assertEqual(destination.read_bytes(), self.content)
        self.assertEqual(result["pre_execution_sha256"], self.digest)
        self.assertEqual(result["post_execution_sha256"], self.digest)
        self.assertEqual(canonical_before, (self.paths[0].read_bytes(), self.paths[0].stat().st_mtime_ns))

        replay = self.execute(plan)
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(self.paths[1].exists())
        restored = restore_quarantine(
            database_path=self.database, execution_id=str(result["execution_id"]),
            actor="restorer", confirm_restore=True,
        )
        self.assertEqual(restored["status"], "restored")
        self.assertEqual(self.paths[1].read_bytes(), self.content)
        self.assertFalse(destination.exists())
        self.assertEqual([event["action"] for event in restored["location_history"]], [
            "quarantined", "restored",
        ])
        connection = self.connection()
        physical = connection.execute(
            "SELECT content_identity_id, current_observed_path FROM physical_instances "
            "WHERE physical_instance_id = ?", (self.instances[1],),
        ).fetchone()
        self.assertEqual(int(physical[0]), original_identity)
        self.assertEqual(str(physical[1]), str(self.paths[1]))
        self.assertEqual(quarantine_history(database_path=self.database)["executions"][0]["status"], "restored")

    def test_confirmation_and_cli_surface_are_narrow(self) -> None:
        plan = self.ready_plan()
        with self.assertRaisesRegex(QuarantineError, "confirm-quarantine"):
            execute_quarantine(
                database_path=self.database, plan_id=str(plan["plan_id"]),
                item_id=str(plan["items"][0]["item_id"]),
                quarantine_root=self.quarantine_root, actor="executor",
                confirm_quarantine=False,
            )
        self.assertTrue(self.paths[1].exists())
        connection = self.connection()
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM action_executions").fetchone()[0], 0)
        parser = build_parser()
        root_commands = parser._subparsers._group_actions[0].choices
        plan_commands = root_commands["plan"]._subparsers._group_actions[0].choices
        quarantine_commands = root_commands["quarantine"]._subparsers._group_actions[0].choices
        self.assertNotIn("execute", plan_commands)
        self.assertNotIn("delete", quarantine_commands)
        self.assertNotIn("force", " ".join(
            option for command in quarantine_commands.values()
            for action in command._actions for option in action.option_strings
        ))

    def test_pending_canonical_and_near_only_cannot_reach_execution(self) -> None:
        nominate(
            database_path=self.database, event_id="pending", context_type="exact",
            context_id=self.content_id, physical_instance_id=self.instances[0],
            canonical_scope="archival", owner="owner",
        )
        with self.assertRaises(PlanningError):
            create_plan(
                database_path=self.database, policy_id="exact-duplicate-quarantine-v1",
                context_type="exact", context_id=self.content_id,
                canonical_scope="archival", approval_event_id="pending",
                destination_root=self.quarantine_root, owner="owner",
                source_physical_instance_ids=[self.instances[1]],
            )
        approval = "approved-approval"
        approve(
            database_path=self.database, event_id=approval, nomination_id="pending",
            physical_instance_id=self.instances[0], canonical_scope="archival",
            owner="owner", reason="Approved after pending gate test",
        )
        with self.assertRaisesRegex(PlanningError, "canonical"):
            create_plan(
                database_path=self.database, policy_id="exact-duplicate-quarantine-v1",
                context_type="exact", context_id=self.content_id,
                canonical_scope="archival", approval_event_id=approval,
                destination_root=self.quarantine_root, owner="owner",
                source_physical_instance_ids=[self.instances[0]],
            )
        with self.assertRaisesRegex(PlanningError, "similarity context"):
            create_plan(
                database_path=self.database, policy_id="exact-duplicate-quarantine-v1",
                context_type="similar", context_id=1, canonical_scope="archival",
                approval_event_id=approval, destination_root=self.quarantine_root,
                owner="owner", source_physical_instance_ids=[self.instances[1]],
            )

    def test_stale_or_failed_latest_preflight_cannot_execute(self) -> None:
        plan = self.ready_plan()
        nominate(
            database_path=self.database, event_id="replacement-nomination",
            context_type="exact", context_id=self.content_id,
            physical_instance_id=self.instances[2], canonical_scope="archival", owner="owner",
        )
        supersede(
            database_path=self.database, event_id="replacement-approval",
            nomination_id="replacement-nomination", prior_approval_id="initial-approval",
            physical_instance_id=self.instances[2], canonical_scope="archival", owner="owner",
            reason="Decision changed",
        )
        with self.assertRaisesRegex(QuarantineError, "stale"):
            self.execute(plan)
        self.assertTrue(self.paths[1].exists())

        # A separate fixture demonstrates a genuine failed latest preflight gate.
        fixture = QuarantineTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        failed_plan = fixture.ready_plan()
        fixture.paths[1].write_bytes(b"changed size")
        failed_report = preflight_plan(
            database_path=fixture.database, plan_id=str(failed_plan["plan_id"]),
            actor="failed-preflight",
        )
        self.assertEqual(failed_report["status"], "preflight_failed")
        with self.assertRaisesRegex(QuarantineError, "preflight-passed"):
            fixture.execute(failed_plan)
        self.assertEqual(fixture.paths[1].read_bytes(), b"changed size")

    def test_catalogue_z_source_change_fails_before_execution(self) -> None:
        plan = self.ready_plan()
        connection = self.connection()
        connection.execute(
            "UPDATE physical_instances SET current_observed_path = ? "
            "WHERE physical_instance_id = ?",
            (r"Z:\never-access.jpg", self.instances[1]),
        )
        connection.commit()
        with self.assertRaisesRegex(QuarantineError, "catalogue evidence"):
            self.execute(plan)
        self.assertTrue(self.paths[1].exists())

    def test_source_missing_size_mtime_and_sha_changes_fail_without_move(self) -> None:
        for change, expected in (("missing", "missing"), ("size", "size"), ("mtime", "mtime"), ("sha", "SHA-256")):
            with self.subTest(change=change):
                # Rebuild a complete isolated fixture for each destructive variation.
                fixture = QuarantineTests(methodName="runTest")
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                plan = fixture.ready_plan()
                source = fixture.paths[1]
                original_mtime = source.stat().st_mtime_ns
                if change == "missing":
                    source.unlink()
                elif change == "size":
                    source.write_bytes(b"changed size")
                elif change == "mtime":
                    os.utime(source, ns=(original_mtime + 1_000_000, original_mtime + 1_000_000))
                else:
                    source.write_bytes(b"X" * len(fixture.content))
                    os.utime(source, ns=(original_mtime, original_mtime))
                with self.assertRaisesRegex(QuarantineError, expected):
                    fixture.execute(plan)
                self.assertFalse(fixture.actual_destination(plan).exists())

    def test_destination_conflict_z_and_reparse_escape_fail_closed(self) -> None:
        plan = self.ready_plan()
        destination = self.actual_destination(plan)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"conflict")
        with self.assertRaisesRegex(QuarantineError, "destination exists"):
            self.execute(plan)
        self.assertTrue(self.paths[1].exists())
        with self.assertRaisesRegex(QuarantineError, "RETIRED_DRIVE"):
            execute_quarantine(
                database_path=self.database, plan_id=str(plan["plan_id"]),
                item_id=str(plan["items"][0]["item_id"]),
                quarantine_root=r"Z:\never-access", actor="executor",
                confirm_quarantine=True,
            )

        fixture = QuarantineTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        escape_plan = fixture.ready_plan()
        escape_destination = fixture.actual_destination(escape_plan)
        outside = fixture.base / "outside"
        outside.mkdir()
        try:
            escape_destination.parents[1].symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Host cannot create directory symlink: {exc}")
        with self.assertRaisesRegex(QuarantineError, "unsafe|Unsafe"):
            fixture.execute(escape_plan)
        self.assertTrue(fixture.paths[1].exists())

    def test_cross_volume_is_unsupported_and_no_copy_delete_fallback(self) -> None:
        plan = self.ready_plan()
        with mock.patch(
            "personal_librarian.quarantine._require_same_volume",
            side_effect=QuarantineError("Cross-volume quarantine is unsupported"),
        ):
            with self.assertRaisesRegex(QuarantineError, "Cross-volume"):
                self.execute(plan)
        self.assertTrue(self.paths[1].exists())
        self.assertFalse(self.actual_destination(plan).exists())

    def test_post_move_verification_failure_and_reconciliation(self) -> None:
        plan = self.ready_plan()
        real_hash = hashlib.sha256(self.content).hexdigest()
        with mock.patch(
            "personal_librarian.quarantine._sha256_file",
            side_effect=[real_hash, "0" * 64],
        ):
            with self.assertRaisesRegex(QuarantineError, "SHA-256"):
                self.execute(plan)
        destination = self.actual_destination(plan)
        self.assertFalse(self.paths[1].exists())
        self.assertTrue(destination.exists())
        history = quarantine_history(database_path=self.database)["executions"][0]
        self.assertEqual(history["status"], "recovery_required")
        reconciled = reconcile_quarantine(
            database_path=self.database, execution_id=str(history["execution_id"]),
            actor="reconciler",
        )
        self.assertEqual(reconciled["reconciliation"]["classification"], "quarantined_verified")
        self.assertEqual(reconciled["status"], "succeeded")

    def test_reconciliation_classifies_both_neither_and_wrong_destination(self) -> None:
        plan = self.ready_plan()
        result = self.execute(plan)
        execution_id = str(result["execution_id"])
        destination = Path(str(result["destination_path"]))
        self.paths[1].write_bytes(self.content)
        both = reconcile_quarantine(
            database_path=self.database, execution_id=execution_id, actor="reconciler"
        )
        self.assertEqual(both["reconciliation"]["classification"], "both_source_and_destination_exist")
        self.paths[1].unlink()
        destination.write_bytes(b"wrong")
        wrong = reconcile_quarantine(
            database_path=self.database, execution_id=execution_id, actor="reconciler"
        )
        self.assertEqual(wrong["reconciliation"]["classification"], "destination_hash_mismatch")
        destination.unlink()
        neither = reconcile_quarantine(
            database_path=self.database, execution_id=execution_id, actor="reconciler"
        )
        self.assertEqual(neither["reconciliation"]["classification"], "neither_source_nor_destination_exists")

    def test_restore_hash_mismatch_and_original_conflict_never_overwrite(self) -> None:
        plan = self.ready_plan()
        result = self.execute(plan)
        destination = Path(str(result["destination_path"]))
        with self.assertRaisesRegex(QuarantineError, "confirm-restore"):
            restore_quarantine(
                database_path=self.database, execution_id=str(result["execution_id"]),
                actor="restorer", confirm_restore=False,
            )
        self.assertTrue(destination.exists())
        destination.write_bytes(b"X" * len(self.content))
        with self.assertRaisesRegex(QuarantineError, "SHA-256"):
            restore_quarantine(
                database_path=self.database, execution_id=str(result["execution_id"]),
                actor="restorer", confirm_restore=True,
            )
        self.assertFalse(self.paths[1].exists())
        destination.write_bytes(self.content)
        self.paths[1].write_bytes(b"occupied")
        with self.assertRaisesRegex(QuarantineError, "occupied"):
            restore_quarantine(
                database_path=self.database, execution_id=str(result["execution_id"]),
                actor="restorer", confirm_restore=True,
            )
        self.assertEqual(self.paths[1].read_bytes(), b"occupied")
        self.assertEqual(destination.read_bytes(), self.content)


if __name__ == "__main__":
    unittest.main()
