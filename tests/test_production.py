from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.catalogue.errors import ProductionError, ReconciliationError
from personal_librarian.cli import build_parser, main
from personal_librarian.production import (
    application_data_layout,
    bootstrap_production,
    create_backup,
    independent_backup_readiness,
    list_backups,
    production_health,
    recover_production,
    retention_report,
    verify_backup,
)
from tests.test_importers import SyntheticEvidence


class ProductionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        evidence_root = self.root / "evidence"
        evidence_root.mkdir()
        self.evidence = SyntheticEvidence(evidence_root)
        self.app_root = self.root / "app-data"

    def bootstrap(self):
        return bootstrap_production(
            app_data_root=self.app_root,
            baselines=self.evidence.baselines,
            **{key: value for key, value in self.evidence.kwargs(self.root / "unused").items()
               if key not in {"database_path", "baselines"}},
        )


class LayoutAndBootstrapTests(ProductionTestCase):
    def test_explicit_absolute_layout_and_z_rejection(self) -> None:
        layout = application_data_layout(self.app_root)
        self.assertEqual(layout.catalogue_path, self.app_root / "catalogue" / "personal_librarian.sqlite3")
        self.assertEqual(layout.backup_root, self.app_root / "backups" / "catalogue")
        with self.assertRaises(ProductionError):
            application_data_layout("relative-root")
        with self.assertRaisesRegex(ProductionError, "RETIRED_DRIVE"):
            application_data_layout(r"Z:\must-not-access")
        missing_parent = self.root / "not-created" / "app-data"
        with self.assertRaisesRegex(ProductionError, "outside"):
            bootstrap_production(
                app_data_root=missing_parent, baselines=self.evidence.baselines,
                **{key: value for key, value in self.evidence.kwargs(self.root / "unused").items()
                   if key not in {"database_path", "baselines"}},
            )
        self.assertFalse(missing_parent.parent.exists())

    def test_successful_bootstrap_identity_mode_and_existing_refusal(self) -> None:
        report = self.bootstrap().values
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["baseline_reconciliation"], "MATCH")
        layout = application_data_layout(self.app_root)
        self.assertEqual(list(layout.catalogue_dir.glob(".bootstrap-*")), [])
        connection = sqlite3.connect(layout.catalogue_path)
        try:
            identity = connection.execute(
                "SELECT catalogue_uuid, catalogue_role, app_data_root_fingerprint FROM catalogue_identity"
            ).fetchone()
            self.assertEqual(identity[0], report["catalogue_uuid"])
            self.assertEqual(identity[1], "production")
            self.assertEqual(len(identity[2]), 64)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE catalogue_identity SET catalogue_role='non-production' WHERE singleton_id=1"
                )
        finally:
            connection.close()
        with self.assertRaisesRegex(ProductionError, "refuses overwrite"):
            self.bootstrap()

    def test_mismatch_does_not_leave_production_or_staging_database(self) -> None:
        baselines = {key: dict(value) for key, value in self.evidence.baselines.items()}
        baselines["m9"]["rows"] = 999
        kwargs = {key: value for key, value in self.evidence.kwargs(self.root / "unused").items()
                  if key not in {"database_path", "baselines"}}
        with self.assertRaises(ReconciliationError):
            bootstrap_production(app_data_root=self.app_root, baselines=baselines, **kwargs)
        layout = application_data_layout(self.app_root)
        self.assertFalse(layout.catalogue_path.exists())
        self.assertEqual(list(layout.catalogue_dir.glob(".bootstrap-*")), [])


class BackupHealthRecoveryTests(ProductionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.bootstrap()

    def test_backup_manifest_hash_listing_health_and_retention_reporting(self) -> None:
        first = create_backup(app_data_root=self.app_root, reason="test-one").values
        second = create_backup(app_data_root=self.app_root, reason="test-two").values
        self.assertNotEqual(first["backup_id"], second["backup_id"])
        self.assertEqual(first["integrity_check"], "ok")
        self.assertEqual(first["foreign_key_violations"], 0)
        verified = verify_backup(first["manifest_path"]).values
        self.assertEqual(verified["result"], "ACCEPTED")
        backup_root = application_data_layout(self.app_root).backup_root
        self.assertEqual(list(backup_root.glob("*.sqlite3-wal")), [])
        self.assertEqual(list(backup_root.glob("*.sqlite3-shm")), [])
        self.assertEqual(list(backup_root.glob(".*.incomplete.sqlite3-*")), [])
        unknown = application_data_layout(self.app_root).backup_root / "owner-notes.txt"
        unknown.write_text("preserve", encoding="utf-8")
        listing = list_backups(app_data_root=self.app_root).values
        self.assertEqual(listing["count"], 2)
        retention = retention_report(app_data_root=self.app_root, keep_latest=1).values
        self.assertEqual(retention["mode"], "report-only")
        self.assertEqual(len(retention["retention_candidates"]), 1)
        self.assertEqual(retention["deleted"], [])
        self.assertEqual(unknown.read_text(encoding="utf-8"), "preserve")
        health = production_health(app_data_root=self.app_root).values
        self.assertEqual(health["summary"], "PASS")
        self.assertEqual(health["backup_count"], 2)

    def test_health_warn_and_fail_examples(self) -> None:
        warning = production_health(app_data_root=self.app_root).values
        self.assertEqual(warning["summary"], "WARN")
        missing = production_health(app_data_root=self.root / "missing-app").values
        self.assertEqual(missing["summary"], "FAIL")

    def test_health_warns_when_latest_backup_is_older_than_seven_days(self) -> None:
        backup = create_backup(app_data_root=self.app_root).values
        manifest_path = Path(backup["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["created_at"] = (
            datetime.now(UTC) - timedelta(days=8)
        ).isoformat().replace("+00:00", "Z")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        health = production_health(app_data_root=self.app_root).values
        self.assertEqual(health["summary"], "WARN")
        self.assertEqual(health["backup_warning_age_seconds"], 604800)
        self.assertIn("older than", health["warnings"][0])

    def test_wal_committed_state_is_present_in_safe_snapshot(self) -> None:
        layout = application_data_layout(self.app_root)
        connection = sqlite3.connect(layout.catalogue_path)
        try:
            connection.execute(
                "INSERT INTO sources(source_key, display_name, source_type) VALUES ('wal-test', 'WAL', 'test')"
            )
            connection.commit()
            self.assertTrue(Path(f"{layout.catalogue_path}-wal").exists())
            backup = create_backup(app_data_root=self.app_root).values
        finally:
            connection.close()
        snapshot = sqlite3.connect(backup["database_path"])
        try:
            self.assertEqual(snapshot.execute("SELECT COUNT(*) FROM sources WHERE source_key='wal-test'").fetchone()[0], 1)
        finally:
            snapshot.close()

    def test_hash_uuid_integrity_and_foreign_key_failures_are_rejected(self) -> None:
        backup = create_backup(app_data_root=self.app_root).values
        database = Path(backup["database_path"])
        with database.open("ab") as handle:
            handle.write(b"tamper")
        self.assertEqual(verify_backup(backup["manifest_path"]).values["result"], "REJECTED")

        clean = create_backup(app_data_root=self.app_root).values
        connection = sqlite3.connect(clean["database_path"])
        try:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                "INSERT INTO acquisition_batches(source_id, batch_key) VALUES (999999, 'bad-fk')"
            )
            connection.commit()
        finally:
            connection.close()
        manifest = Path(clean["manifest_path"])
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["backup_sha256"] = hashlib.sha256(Path(clean["database_path"]).read_bytes()).hexdigest()
        manifest.write_text(json.dumps(value), encoding="utf-8")
        rejected = verify_backup(manifest).values
        self.assertEqual(rejected["result"], "REJECTED")
        self.assertGreater(rejected["foreign_key_violations"], 0)

    def test_recovery_requires_confirmation_and_safeguards_old_catalogue(self) -> None:
        backup = create_backup(app_data_root=self.app_root, reason="recovery-source").values
        layout = application_data_layout(self.app_root)
        connection = sqlite3.connect(layout.catalogue_path)
        try:
            connection.execute(
                "INSERT INTO sources(source_key, display_name, source_type) VALUES ('after-backup', 'Later', 'test')"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ProductionError, "confirm-restore-catalogue"):
            recover_production(
                app_data_root=self.app_root, manifest_path=backup["manifest_path"],
                actor="owner", confirm_restore_catalogue=False,
            )
        result = recover_production(
            app_data_root=self.app_root, manifest_path=backup["manifest_path"],
            actor="owner", confirm_restore_catalogue=True,
        ).values
        self.assertEqual(result["result"], "succeeded")
        self.assertTrue(Path(result["safeguarded_old_production_path"]).is_file())
        self.assertTrue(Path(result["journal_path"]).is_file())
        self.assertEqual(list(layout.catalogue_dir.glob(".recovery-*")), [])
        restored = sqlite3.connect(layout.catalogue_path)
        try:
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM sources WHERE source_key='after-backup'").fetchone()[0], 0)
        finally:
            restored.close()
        journal = json.loads(Path(result["journal_path"]).read_text(encoding="utf-8"))
        self.assertEqual(journal["result"], "succeeded")
        self.assertTrue(Path(journal["pre_recovery_backup"]).is_file())

    def test_interrupted_promotion_restores_current_and_leaves_diagnostic_journal(self) -> None:
        backup = create_backup(app_data_root=self.app_root).values
        layout = application_data_layout(self.app_root)
        original_hash = __import__("hashlib").sha256(layout.catalogue_path.read_bytes()).hexdigest()
        real_replace = __import__("os").replace

        def interrupt_staged_promotion(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            if source_path.name.startswith(".recovery-") and destination_path == layout.catalogue_path:
                raise OSError("synthetic interrupted promotion")
            return real_replace(source, destination)

        with mock.patch("personal_librarian.production.os.replace", side_effect=interrupt_staged_promotion):
            with self.assertRaisesRegex(OSError, "interrupted promotion"):
                recover_production(
                    app_data_root=self.app_root, manifest_path=backup["manifest_path"],
                    actor="owner", confirm_restore_catalogue=True,
                )
        self.assertTrue(layout.catalogue_path.is_file())
        self.assertEqual(
            __import__("hashlib").sha256(layout.catalogue_path.read_bytes()).hexdigest(),
            original_hash,
        )
        journals = list(layout.recovery_root.glob("recovery-*.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads(journals[0].read_text(encoding="utf-8"))["result"], "failed")

    def test_wrong_catalogue_uuid_is_rejected(self) -> None:
        other_root = self.root / "other-app"
        kwargs = {key: value for key, value in self.evidence.kwargs(self.root / "unused").items()
                  if key not in {"database_path", "baselines"}}
        bootstrap_production(app_data_root=other_root, baselines=self.evidence.baselines, **kwargs)
        other_backup = create_backup(app_data_root=other_root).values
        with self.assertRaisesRegex(ProductionError, "UUID"):
            recover_production(
                app_data_root=self.app_root, manifest_path=other_backup["manifest_path"],
                actor="owner", confirm_restore_catalogue=True,
            )


class ProductionCliTests(unittest.TestCase):
    def test_commands_require_explicit_roots_and_confirmation_flag_exists(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(["production", "health"])
        args = parser.parse_args([
            "production", "recover", "--app-data-root", r"C:\safe",
            "--manifest", r"C:\safe\backup.json", "--actor", "owner",
            "--confirm-restore-catalogue",
        ])
        self.assertTrue(args.confirm_restore_catalogue)
        standalone = parser.parse_args([
            "catalogue", "backup", "verify", "--manifest", r"X:\backup\manifest.json"
        ])
        self.assertIsNone(standalone.app_data_root)

    def test_cli_rejects_z_without_access(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["production", "health", "--app-data-root", r"Z:\never-access"])
        self.assertEqual(code, 2)
        self.assertIn("RETIRED_DRIVE", stderr.getvalue())


class IndependentBackupTests(ProductionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.bootstrap()
        self.independent_root = self.root / "independent"
        self.independent_root.mkdir()

    def create_independent(self):
        def device(path: Path) -> str:
            return "device-production" if Path(path) == self.app_root else "device-independent"

        with mock.patch("personal_librarian.production._physical_device_identity", side_effect=device):
            return create_backup(
                app_data_root=self.app_root,
                backup_root=self.independent_root,
                backup_class="independent-local",
                reason="independent test",
            ).values

    def test_explicit_safe_independent_root_and_separate_device_are_required(self) -> None:
        with self.assertRaisesRegex(ProductionError, "explicit backup root"):
            create_backup(app_data_root=self.app_root, backup_class="independent-local")
        with self.assertRaisesRegex(ProductionError, "RETIRED_DRIVE"):
            create_backup(
                app_data_root=self.app_root,
                backup_root=r"Z:\never-access",
                backup_class="independent-local",
            )
        with self.assertRaisesRegex(ProductionError, "same physical device"):
            create_backup(
                app_data_root=self.app_root,
                backup_root=self.independent_root,
                backup_class="independent-local",
            )
        with mock.patch(
            "personal_librarian.production._physical_device_identity",
            side_effect=("device-production", "device-independent"),
        ):
            with self.assertRaisesRegex(ProductionError, "outside production app data"):
                create_backup(
                    app_data_root=self.app_root,
                    backup_root=self.app_root,
                    backup_class="independent-local",
                )

    def test_independent_manifest_inventory_verification_and_unknown_files(self) -> None:
        backup = self.create_independent()
        manifest = json.loads(Path(backup["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["backup_class"], "independent-local")
        self.assertEqual(manifest["device_independence"], "confirmed")
        self.assertEqual(manifest["source_device_identity"], "device-production")
        self.assertEqual(manifest["destination_device_identity"], "device-independent")
        self.assertEqual(manifest["catalogue_counts"]["physical_instances"], 6)
        unknown = self.independent_root / "owner-file.txt"
        unknown.write_text("preserve", encoding="utf-8")
        listing = list_backups(
            app_data_root=self.app_root,
            backup_root=self.independent_root,
            backup_class="independent-local",
        ).values
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["backups"][0]["backup_class"], "independent-local")
        verified = verify_backup(
            backup["manifest_path"], expected_catalogue_uuid=backup["source_catalogue_uuid"]
        ).values
        self.assertEqual(verified["result"], "ACCEPTED")
        self.assertEqual(verified["catalogue_counts"]["similarity_relationships"], 1)
        self.assertEqual(unknown.read_text(encoding="utf-8"), "preserve")

    def test_readiness_freshness_disconnection_and_catalogue_health_are_separate(self) -> None:
        create_backup(app_data_root=self.app_root)
        backup = self.create_independent()
        ready = independent_backup_readiness(
            app_data_root=self.app_root, independent_backup_root=self.independent_root
        ).values
        self.assertEqual(ready["summary"], "PASS")
        manifest_path = Path(backup["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["created_at"] = (
            datetime.now(UTC) - timedelta(days=8)
        ).isoformat().replace("+00:00", "Z")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        stale = independent_backup_readiness(
            app_data_root=self.app_root, independent_backup_root=self.independent_root
        ).values
        self.assertEqual(stale["summary"], "WARN")
        health = production_health(
            app_data_root=self.app_root,
            independent_backup_root=self.root / "disconnected",
        ).values
        self.assertEqual(health["summary"], "PASS")
        self.assertEqual(health["disaster_recovery"]["summary"], "WARN")

    def test_corrupt_independent_copy_and_wrong_manifest_uuid_are_rejected(self) -> None:
        corrupt = self.create_independent()
        with Path(corrupt["database_path"]).open("ab") as handle:
            handle.write(b"corrupt")
        failed = independent_backup_readiness(
            app_data_root=self.app_root, independent_backup_root=self.independent_root
        ).values
        self.assertEqual(failed["summary"], "FAIL")
        self.assertEqual(failed["valid_independent_backup_count"], 0)

        second_root = self.root / "independent-two"
        second_root.mkdir()
        original_root = self.independent_root
        self.independent_root = second_root
        try:
            wrong = self.create_independent()
        finally:
            self.independent_root = original_root
        manifest_path = Path(wrong["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_catalogue_uuid"] = "00000000-0000-0000-0000-000000000000"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        rejected = verify_backup(
            manifest_path,
            expected_catalogue_uuid=wrong["source_catalogue_uuid"],
        ).values
        self.assertEqual(rejected["result"], "REJECTED")
        self.assertIn("manifest catalogue UUID mismatch", rejected["errors"])

    def test_independent_copy_stages_with_matching_counts_and_production_unchanged(self) -> None:
        backup = self.create_independent()
        production = application_data_layout(self.app_root).catalogue_path
        before = hashlib.sha256(production.read_bytes()).hexdigest()
        staged = self.root / "staged-independent.sqlite3"
        source = sqlite3.connect(Path(backup["database_path"]))
        target = sqlite3.connect(staged)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        production_db = sqlite3.connect(production)
        staged_db = sqlite3.connect(staged)
        try:
            tables = (
                "physical_instances", "content_identities", "exact_duplicate_groups",
                "similarity_relationships", "similarity_groups",
            )
            self.assertEqual(
                {table: production_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables},
                {table: staged_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables},
            )
            self.assertEqual(staged_db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(staged_db.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            staged_db.close()
            production_db.close()
        self.assertEqual(hashlib.sha256(production.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
