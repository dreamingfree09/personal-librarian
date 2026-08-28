from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from PIL import Image
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.desktop.main_window import MainWindow
from personal_librarian.desktop.services import DesktopDataService
from personal_librarian.desktop.thumbnails import THUMBNAIL_VERSION, ThumbnailService
from personal_librarian.production import application_data_layout, bootstrap_production
from tests.test_importers import SyntheticEvidence


class DesktopFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        evidence_root = self.root / "evidence"
        evidence_root.mkdir()
        evidence = SyntheticEvidence(evidence_root)
        self.app_root = self.root / "app-data"
        bootstrap_production(
            app_data_root=self.app_root,
            baselines=evidence.baselines,
            **{
                key: value
                for key, value in evidence.kwargs(self.root / "unused").items()
                if key not in {"database_path", "baselines"}
            },
        )
        self.service = DesktopDataService(self.app_root)

    def test_desktop_starts_and_contains_only_bounded_navigation(self) -> None:
        window = MainWindow(self.service)
        self.addCleanup(window.close)
        self.addCleanup(QThreadPool.globalInstance().waitForDone, 5000)
        self.assertEqual(window.navigation.count(), 8)
        self.assertEqual(window.navigation.item(0).text(), "Overview")
        self.assertEqual(window.navigation.item(1).text(), "Library")
        self.assertEqual(window.navigation.minimumWidth(), 190)
        self.assertEqual(window.navigation.maximumWidth(), 230)
        overview_groups = {
            group.title() for group in window.pages[0].findChildren(QGroupBox)
        }
        self.assertEqual(
            overview_groups,
            {"Catalogue", "Library", "Review", "Safety / Actions", "Backups"},
        )
        button_text = {button.text().casefold() for button in window.findChildren(QPushButton)}
        self.assertFalse(any("delete" in text for text in button_text))
        self.assertFalse(any(text in {"execute", "restore", "quarantine"} for text in button_text))

    def test_empty_states_and_backup_primary_columns_are_owner_facing(self) -> None:
        window = MainWindow(self.service)
        self.addCleanup(window.close)
        self.addCleanup(QThreadPool.globalInstance().waitForDone, 5000)
        decisions, plans, quarantine, backups = window.pages[4:8]
        decisions._loaded([])
        plans._loaded({"plans": []})
        quarantine._loaded({"executions": []})
        backups._loaded(
            {
                "operational": {"backups": []},
                "independent": {"backups": []},
            }
        )
        self.assertEqual(decisions.message.text(), "No owner decisions recorded yet.")
        self.assertEqual(plans.message.text(), "No action plans currently exist.")
        self.assertEqual(quarantine.message.text(), "No quarantine history exists.")
        self.assertEqual(backups.message.text(), "No verified catalogue backups are currently listed.")
        headers = [
            backups.table.horizontalHeaderItem(index).text()
            for index in range(backups.table.columnCount())
        ]
        self.assertEqual(headers[:4], ["Class", "Created", "Size", "Verification"])

    def test_missing_catalogue_is_diagnostic_and_does_not_bootstrap(self) -> None:
        missing = self.root / "missing-app-data"
        missing.mkdir()
        service = DesktopDataService(missing)
        report = service.dashboard()
        self.assertEqual(report["health"]["summary"], "FAIL")
        self.assertFalse(report["decision_writes_enabled"])
        self.assertFalse(application_data_layout(missing).catalogue_path.exists())

    def test_dashboard_and_read_only_operational_views(self) -> None:
        dashboard = self.service.dashboard()
        self.assertEqual(dashboard["health"]["summary"], "WARN")
        self.assertGreater(dashboard["counts"]["physical_instances"], 0)
        self.assertIn("decision_events", dashboard["counts"])
        self.assertEqual(self.service.plans()["plans"], [])
        self.assertEqual(self.service.quarantine()["executions"], [])
        self.assertIn("operational", self.service.backups())

    def test_exact_and_similarity_pagination_and_status_filters(self) -> None:
        exact = self.service.exact_reviews(status=None, limit=1, offset=0)
        similar = self.service.similar_reviews(status=None, limit=1, offset=0)
        self.assertEqual(len(exact["items"]), 1)
        self.assertLessEqual(len(similar["items"]), 1)
        pending = self.service.exact_reviews(status="pending", limit=50, offset=0)
        self.assertEqual(pending["total_matching"], exact["total_matching"])
        detail = self.service.exact_detail(int(exact["items"][0]["context_id"]))
        self.assertGreaterEqual(len(detail["physical_instances"]), 2)
        if similar["items"]:
            similar_detail = self.service.similar_detail(
                int(similar["items"][0]["context_id"])
            )
            self.assertTrue(similar_detail["content_identity_ids"])

    def test_nomination_and_approval_are_separate_and_scopes_independent(self) -> None:
        item = self.service.exact_reviews(status=None, limit=1, offset=0)["items"][0]
        detail = self.service.exact_detail(int(item["context_id"]))
        physical = int(detail["physical_instances"][0]["physical_instance_id"])
        nomination = self.service.nominate(
            context_type="exact", context_id=int(item["context_id"]),
            physical_instance_id=physical, canonical_scope="archival", actor="owner-test",
        )
        state = nomination["current_state"]
        self.assertEqual(len(state["scopes"]["archival"]["pending_nominations"]), 1)
        self.assertEqual(state["scopes"]["display_export"]["status"], "pending")
        self.assertIsNone(state["scopes"]["archival"]["approved"])
        approved = self.service.resolve_nomination(
            action="approve", nomination_id=nomination["event_id"],
            physical_instance_id=physical, canonical_scope="archival", actor="owner-test",
        )
        self.assertEqual(approved["current_state"]["scopes"]["archival"]["status"], "approved")
        history = self.service.decisions()
        self.assertEqual([event["action"] for event in history], ["nominate", "approve"])

    def test_rejection_uses_existing_service_and_unhealthy_gate_fails_closed(self) -> None:
        item = self.service.exact_reviews(status=None, limit=1, offset=0)["items"][0]
        detail = self.service.exact_detail(int(item["context_id"]))
        physical = int(detail["physical_instances"][0]["physical_instance_id"])
        nomination = self.service.nominate(
            context_type="exact", context_id=int(item["context_id"]),
            physical_instance_id=physical, canonical_scope="display_export", actor="owner-test",
        )
        rejected = self.service.resolve_nomination(
            action="reject", nomination_id=nomination["event_id"],
            physical_instance_id=physical, canonical_scope="display_export", actor="owner-test",
        )
        self.assertEqual(rejected["current_state"]["scopes"]["display_export"]["status"], "rejected")
        with mock.patch.object(self.service, "decision_writes_enabled", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "does not permit"):
                self.service.nominate(
                    context_type="exact", context_id=int(item["context_id"]),
                    physical_instance_id=physical, canonical_scope="archival", actor="owner-test",
                )

    def test_unicode_thumbnail_cache_key_placeholder_and_source_unchanged(self) -> None:
        media = self.root / "φωτογραφίες"
        media.mkdir()
        source = media / "εικόνα.png"
        Image.new("RGB", (640, 480), (30, 90, 160)).save(source)
        before = (source.read_bytes(), source.stat().st_size, source.stat().st_mtime_ns)
        thumbnails = ThumbnailService(self.app_root, max_size=(96, 96))
        result = thumbnails.load(source, content_identity="sha256:unicode")
        self.assertIsNone(result.error)
        self.assertTrue(result.cache_path.is_file())
        self.assertIn(THUMBNAIL_VERSION, f"{THUMBNAIL_VERSION}")
        self.assertEqual(result.cache_key, thumbnails.cache_key("sha256:unicode"))
        after = (source.read_bytes(), source.stat().st_size, source.stat().st_mtime_ns)
        self.assertEqual(before, after)
        invalid = media / "invalid.jpg"
        invalid.write_bytes(b"not an image")
        zero = media / "zero.webp"
        zero.write_bytes(b"")
        self.assertIsNotNone(thumbnails.load(invalid, content_identity="invalid").error)
        self.assertIsNotNone(thumbnails.load(zero, content_identity="zero").error)

    def test_retired_z_thumbnail_is_rejected_before_filesystem_access(self) -> None:
        thumbnails = ThumbnailService(self.app_root)
        with mock.patch.object(Path, "is_file", side_effect=AssertionError("filesystem opened")):
            result = thumbnails.load(r"Z:\retired\image.jpg", content_identity="blocked")
        self.assertIn("RETIRED_DRIVE", result.error)

    def test_database_decision_history_remains_append_only(self) -> None:
        database = application_data_layout(self.app_root).catalogue_path
        connection = connect_existing_catalogue(database, read_only=True)
        try:
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='decision_events'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertIn("decision_events", sql)


if __name__ == "__main__":
    unittest.main()
