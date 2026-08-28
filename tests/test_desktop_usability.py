from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from PIL import Image
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from personal_librarian.desktop.app import packaged_main
from personal_librarian.desktop.main_window import PreviewBinding, ReviewPage
from personal_librarian.desktop.library_page import (
    CreateAlbumDialog,
    LibraryPage,
    LibraryPreviewBinding,
)
from personal_librarian.desktop.preferences import PreferenceStore, UiPreferences
from personal_librarian.desktop.thumbnails import ThumbnailService
from personal_librarian.desktop.startup import StartupDialog, validate_runtime_roots
from personal_librarian.desktop.ui_helpers import (
    bounded_row,
    canonical_badge,
    decision_confirmation_text,
    display_timestamp,
    format_bytes,
    metadata_blocks,
    metadata_summary,
    owner_state_label,
    preview_caption,
    SIMILARITY_HELP_TEXT,
)
from personal_librarian.desktop.viewer import ImageViewerDialog
from personal_librarian.production import bootstrap_production
from tests.test_importers import SyntheticEvidence


class _CapturingPool:
    def __init__(self) -> None:
        self.tasks = []

    def start(self, task: object) -> None:
        self.tasks.append(task)


class DesktopUsabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_preferences_round_trip_under_application_state(self) -> None:
        app_root = self.root / "app-data"
        (app_root / "state").mkdir(parents=True)
        store = PreferenceStore(app_root)
        expected = UiPreferences(
            last_section=2, page_size=100, thumbnail_size=256,
            window_geometry="YWJj", shell_splitter=[180, 1000], review_splitter=[300, 600],
            exact_review_splitter=[230, 670], similar_review_splitter=[290, 610],
            last_actor="owner@example",
        )
        store.save(expected)
        self.assertEqual(store.load(), expected)
        self.assertEqual(store.path.parent, app_root / "state")

    def test_library_collection_gate_and_preview_stale_binding(self) -> None:
        service = mock.Mock()
        service.layout = SimpleNamespace(root=self.root / "app-data")
        page = LibraryPage(service, UiPreferences(last_actor="owner"))
        self.addCleanup(page.close)
        page.pool = _CapturingPool()
        collection_text = "\n".join(
            label.text() for label in page.tabs.widget(1).findChildren(QLabel)
        )
        self.assertIn("schema-10", collection_text)
        self.assertIn("does not fake", collection_text)

        row = {
            "content_identity_id": 11, "identity_key": "sha256:test",
            "physical_instance_id": 0, "current_observed_path": None,
            "raw_relative_path": "photo.jpg", "source": "Source", "size_bytes": 20,
            "extension": ".jpg", "observed_created_at": "2025-01-01T00:00:00Z",
            "observed_modified_at": "2025-01-02T00:00:00Z",
            "physical_instance_count": 3,
        }
        page.current_year = 2025
        page.has_year_selection = True
        page._year_loaded((
            {"content": [row], "total_matching": 1, "unorganised_only": False},
            {"albums": []}, {"albums": []},
        ))
        image = QImage(2, 2, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        stale = LibraryPreviewBinding(page._generation - 1, "year:2025", 11, 0, "")
        page._thumbnail_loaded(stale, image, "")
        self.assertTrue(page.content.item(0).icon().isNull())
        current = LibraryPreviewBinding(page._generation, "year:2025", 11, 0, "")
        page._thumbnail_loaded(current, image, "")
        self.assertFalse(page.content.item(0).icon().isNull())

    def test_create_album_keeps_actor_description_and_reason_separate(self) -> None:
        service = mock.Mock()
        service.layout = SimpleNamespace(root=self.root / "app-data")
        service.create_album.return_value = {"album_uuid": "album"}
        page = LibraryPage(service, UiPreferences(last_actor="owner-test"))
        self.addCleanup(page.close)
        page.reason.setText("Owner reason")
        page._confirm = mock.Mock(return_value=True)
        page.refresh = mock.Mock()
        page.run_async = lambda operation, completed: completed(operation())

        for description in (None, "Christmas photographs"):
            service.create_album.reset_mock()
            with mock.patch(
                "personal_librarian.desktop.library_page.CreateAlbumDialog"
            ) as dialog_type:
                dialog_type.return_value.exec.return_value = QDialog.Accepted
                dialog_type.return_value.values.return_value = ("Christmas", description)
                page._create_album()
            service.create_album.assert_called_once_with(
                name="Christmas",
                description=description,
                actor="owner-test",
                reason="Owner reason",
            )
            call = service.create_album.call_args.kwargs
            self.assertNotEqual(call["description"], call["actor"])
            self.assertNotEqual(call["description"], call["reason"])

        form = CreateAlbumDialog()
        self.addCleanup(form.close)
        self.assertEqual(form.values(), ("", None))

    def test_library_retains_worker_through_packaged_style_completion_callback(self) -> None:
        service = mock.Mock()
        service.layout = SimpleNamespace(root=self.root / "app-data")
        page = LibraryPage(service, UiPreferences())
        self.addCleanup(page.close)
        page.pool = _CapturingPool()
        completed: list[int] = []

        page.run_async(lambda: 42, completed.append)
        worker = page.pool.tasks[0]
        self.assertFalse(worker.autoDelete())
        self.assertIn(worker, page._active_workers)

        worker.run()
        self.assertEqual(completed, [42])
        self.assertNotIn(worker, page._active_workers)

    def test_invalid_preferences_recover_to_safe_defaults(self) -> None:
        app_root = self.root / "app-data"
        state = app_root / "state"
        state.mkdir(parents=True)
        store = PreferenceStore(app_root)
        store.path.write_text('{"version": 1, "page_size": 999, "thumbnail_size": -1}', encoding="utf-8")
        recovered = store.load()
        self.assertEqual(recovered.page_size, 50)
        self.assertEqual(recovered.thumbnail_size, 256)
        store.path.write_text("not json", encoding="utf-8")
        self.assertEqual(store.load(), UiPreferences())

    def test_exact_and_similar_splitters_restore_independently(self) -> None:
        app_root = self.root / "app-data"
        (app_root / "state").mkdir(parents=True)
        store = PreferenceStore(app_root)
        store.save(
            UiPreferences(
                exact_review_splitter=[250, 650],
                similar_review_splitter=[360, 540],
            )
        )
        restored = store.load()
        self.assertEqual(restored.exact_review_splitter, [250, 650])
        self.assertEqual(restored.similar_review_splitter, [360, 540])
        service = mock.Mock()
        service.layout = SimpleNamespace(root=app_root)
        exact = ReviewPage(service, similar=False, preferences=restored)
        similar = ReviewPage(service, similar=True, preferences=restored)
        self.addCleanup(exact.close)
        self.addCleanup(similar.close)
        for page in (exact, similar):
            page.resize(1000, 800)
            page.show()
        QApplication.processEvents()
        exact_sizes = exact.splitter.sizes()
        similar_sizes = similar.splitter.sizes()
        exact_ratio = exact_sizes[0] / sum(exact_sizes)
        similar_ratio = similar_sizes[0] / sum(similar_sizes)
        self.assertLess(exact_ratio, similar_ratio)

        restarted_exact = ReviewPage(service, similar=False, preferences=store.load())
        restarted_similar = ReviewPage(service, similar=True, preferences=store.load())
        self.addCleanup(restarted_exact.close)
        self.addCleanup(restarted_similar.close)
        for page in (restarted_exact, restarted_similar):
            page.resize(1000, 800)
            page.show()
        QApplication.processEvents()
        restarted_exact_sizes = restarted_exact.splitter.sizes()
        restarted_similar_sizes = restarted_similar.splitter.sizes()
        self.assertAlmostEqual(
            restarted_exact_sizes[0] / sum(restarted_exact_sizes), exact_ratio, delta=0.01
        )
        self.assertAlmostEqual(
            restarted_similar_sizes[0] / sum(restarted_similar_sizes), similar_ratio, delta=0.01
        )

    def test_navigation_boundaries(self) -> None:
        self.assertEqual(bounded_row(-1, 3, 1), 0)
        self.assertEqual(bounded_row(0, 3, -1), 0)
        self.assertEqual(bounded_row(1, 3, 1), 2)
        self.assertEqual(bounded_row(2, 3, 1), 2)
        self.assertEqual(bounded_row(0, 0, 1), -1)

    def test_metadata_rendering_has_no_quality_or_date_ranking(self) -> None:
        item = {
            "current_observed_path": r"C:\media\εικόνα.jpg",
            "source": "Greek source", "size_bytes": 2048,
            "observed_modified_at": "2026-01-01T00:00:00Z", "sha256": "abc",
            "exact_duplicate_count": 3,
            "canonical": {
                "archival": {"approved": True, "nominated": False},
                "display_export": {"approved": False, "nominated": True},
            },
        }
        rendered = metadata_summary(item)
        primary, technical = metadata_blocks(item)
        self.assertIn("εικόνα.jpg", rendered)
        self.assertIn("2.0 KiB", rendered)
        self.assertIn("Represented copies: 3", rendered)
        self.assertEqual(
            canonical_badge(item["canonical"]), "Archival: Approved · Display: Nominated"
        )
        self.assertLess(primary.index("Source:"), primary.index("Archival:"))
        self.assertNotIn("SHA-256", primary)
        self.assertIn("SHA-256: abc", technical)
        self.assertIn("Full path: C:\\media\\εικόνα.jpg", technical)
        self.assertNotIn("best", rendered.casefold())
        self.assertEqual(format_bytes(0), "0 bytes")
        self.assertEqual(display_timestamp("2026-01-01T00:00:00Z")[:11], "01 Jan 2026")

    def test_owner_state_similarity_help_and_confirmation_wording(self) -> None:
        self.assertEqual(owner_state_label("review_only"), "Review only")
        self.assertEqual(owner_state_label("large_low_confidence_review_only"), "Large · review only")
        self.assertIn("Lower pHash and dHash distances", SIMILARITY_HELP_TEXT)
        self.assertIn("do not prove byte-for-byte identity", SIMILARITY_HELP_TEXT)
        selected = {
            "physical_instance_id": 42,
            "current_observed_path": r"C:\media\photo.jpg",
            "source": "Phone",
        }
        primary, informative, technical = decision_confirmation_text(
            action="nominate", scope="archival", actor="Owner", reason="Preserve original",
            context_id=77, selected=selected,
        )
        self.assertEqual(primary, "Nominate this copy as the preferred archival candidate?")
        self.assertIn("photo.jpg", informative)
        self.assertIn("Nomination and approval are separate catalogue events.", informative)
        self.assertNotIn("Instance ID", informative)
        self.assertIn("Instance ID: 42", technical)

    def test_zoom_viewer_supports_fit_actual_and_zoom(self) -> None:
        image = QImage(320, 240, QImage.Format_RGB32)
        image.fill(0x336699)
        dialog = ImageViewerDialog(image, "read-only metadata")
        self.addCleanup(dialog.close)
        dialog.actual_size()
        self.assertEqual(dialog.view.transform().m11(), 1.0)
        dialog.zoom_in()
        self.assertGreater(dialog.view.transform().m11(), 1.0)
        dialog.zoom_out()
        self.assertAlmostEqual(dialog.view.transform().m11(), 1.0)

    def test_viewer_keeps_owner_metadata_primary_and_technical_details_collapsed(self) -> None:
        image = self._solid_image(0x224466)
        dialog = ImageViewerDialog(image, "Photo\nSource: Phone", "SHA-256: abc\nInstance ID: 4")
        self.addCleanup(dialog.close)
        self.assertIn("Source: Phone", dialog.primary_details.text())
        self.assertFalse(dialog.technical_details.isVisible())
        dialog.technical_toggle.setChecked(True)
        self.assertFalse(dialog.technical_details.isHidden())
        self.assertIn("SHA-256: abc", dialog.technical_details.text())

    def _review_page(self, *, similar: bool = False) -> tuple[ReviewPage, _CapturingPool]:
        app_root = self.root / "app-data"
        app_root.mkdir(exist_ok=True)
        service = mock.Mock()
        service.layout = SimpleNamespace(root=app_root)
        page = ReviewPage(service, similar=similar, preferences=UiPreferences())
        pool = _CapturingPool()
        page.pool = pool
        self.addCleanup(page.close)
        return page, pool

    def test_review_tables_and_previews_prioritise_owner_facing_evidence(self) -> None:
        path = self.root / "friendly-name.png"
        Image.new("RGB", (32, 32), "blue").save(path)
        exact, _ = self._review_page()
        exact._groups_loaded(
            {
                "items": [{
                    "context_id": 99, "group_size": 3, "sources": ["Phone", "Cloud"],
                    "size_bytes_max": 2048,
                    "canonical_scopes": {"archival": "pending", "display_export": "approved"},
                    "review_status": "pending",
                }],
                "total_matching": 1,
            }
        )
        exact_headers = [
            exact.groups.horizontalHeaderItem(index).text()
            for index in range(exact.groups.columnCount())
        ]
        self.assertEqual(
            exact_headers,
            ["Copies", "Sources", "Size", "Archival", "Display", "Review status", "Content ID"],
        )
        self.assertEqual(exact.groups.item(0, 3).text(), "Pending")
        self.assertEqual(exact.groups.item(0, 4).text(), "Approved")
        three_rows = exact.instances.verticalHeader().defaultSectionSize() * 3
        header = exact.instances.horizontalHeader().sizeHint().height()
        self.assertGreaterEqual(exact.instances.minimumHeight(), header + three_rows)
        exact._detail_loaded(self._detail(99, [(501, path)]))
        self.assertIn("byte-for-byte identical", exact.context_banner.text())
        caption = exact.previews.item(0).text()
        self.assertEqual(caption, preview_caption(exact.detail["physical_instances"][0]))
        self.assertNotIn("instance 501", caption.casefold())
        self.assertTrue(exact.preview_bindings_match_detail())

        similar, _ = self._review_page(similar=True)
        similar._groups_loaded(
            {
                "items": [{
                    "context_id": 7, "unique_contents": 2, "review_tier": "review_only",
                    "phash_distance_range": [1, 3], "dhash_distance_range": [2, 4],
                    "is_over_50": False, "is_large_ambiguous": False,
                    "review_status": "pending",
                }],
                "total_matching": 1,
            }
        )
        self.assertEqual(similar.groups.item(0, 1).text(), "Review only")
        self.assertIn("Lower pHash", similar.groups.horizontalHeaderItem(2).toolTip())

    def _detail(
        self,
        context_id: int,
        instances: list[tuple[int, Path]],
    ) -> dict[str, object]:
        physical = []
        for instance_id, path in instances:
            physical.append(
                {
                    "physical_instance_id": instance_id,
                    "content_identity_id": context_id,
                    "content_identity_key": f"sha256:content-{context_id}",
                    "source": f"source-{instance_id}",
                    "raw_relative_path": path.name,
                    "current_observed_path": str(path),
                    "extension": path.suffix,
                    "size_bytes": path.stat().st_size,
                    "observed_created_at": None,
                    "observed_modified_at": None,
                    "sha256": f"content-{context_id}",
                    "exact_duplicate_count": len(instances),
                    "canonical": {},
                }
            )
        empty_scope = {
            "status": "pending",
            "nominations": [],
            "pending_nominations": [],
            "approved": None,
        }
        return {
            "context_type": "exact",
            "context_id": context_id,
            "review_status": "pending",
            "physical_instances": physical,
            "decision_state": {
                "scopes": {
                    "archival": dict(empty_scope),
                    "display_export": dict(empty_scope),
                }
            },
        }

    @staticmethod
    def _solid_image(rgb: int) -> QImage:
        image = QImage(24, 24, QImage.Format_RGB32)
        image.fill(rgb)
        return image

    def test_preview_results_bind_by_instance_when_completed_out_of_order(self) -> None:
        paths = []
        for index in range(3):
            path = self.root / f"instance-{index}.png"
            Image.new("RGB", (32, 32), (10 + index, 20, 30)).save(path)
            paths.append(path)
        page, pool = self._review_page()
        page._detail_loaded(self._detail(41904, list(zip((101, 102, 103), paths))))
        tasks = list(pool.tasks)
        self.assertEqual(len(tasks), 3)
        colours = {101: 0xAA0000, 102: 0x00AA00, 103: 0x0000AA}
        for task in reversed(tasks):
            self.assertIsInstance(task.token, PreviewBinding)
            page._thumbnail_loaded(
                task.token, self._solid_image(colours[task.token.physical_instance_id]), ""
            )
        self.assertTrue(page.preview_bindings_match_detail())
        snapshot = page.preview_binding_snapshot()
        self.assertEqual([item["physical_instance_id"] for item in snapshot], [101, 102, 103])
        self.assertTrue(all(item["has_icon"] for item in snapshot))
        for index, instance_id in enumerate((101, 102, 103)):
            rendered = page.previews.item(index).icon().pixmap(24, 24).toImage()
            self.assertEqual(
                QColor(rendered.pixel(12, 12)).rgb() & 0xFFFFFF,
                colours[instance_id],
            )

    def test_stale_group_results_and_reselection_cannot_reuse_preview_slots(self) -> None:
        first_path = self.root / "first.png"
        second_path = self.root / "second.png"
        Image.new("RGB", (32, 32), "red").save(first_path)
        Image.new("RGB", (32, 32), "green").save(second_path)
        page, pool = self._review_page()

        page._pending_detail_request = (1, 1)
        page._clear_detail("Loading first")
        page._pending_detail_request = (2, 2)
        page._clear_detail("Loading second")
        page._detail_loaded(self._detail(1, [(11, first_path)]), (1, 1))
        self.assertIsNone(page.detail)
        page._detail_loaded(self._detail(2, [(22, second_path)]), (2, 2))
        self.assertEqual(page.detail["context_id"], 2)

        page._detail_loaded(self._detail(1, [(11, first_path)]))
        stale_task = pool.tasks[-1]
        page._detail_loaded(self._detail(2, [(22, second_path)]))
        current_task = pool.tasks[-1]
        self.assertTrue(page.previews.item(0).icon().isNull())
        page._thumbnail_loaded(stale_task.token, self._solid_image(0xAA0000), "")
        self.assertTrue(page.previews.item(0).icon().isNull())
        page._thumbnail_loaded(current_task.token, self._solid_image(0x00AA00), "")
        self.assertFalse(page.previews.item(0).icon().isNull())

        page._detail_loaded(self._detail(2, [(22, second_path)]))
        self.assertTrue(page.previews.item(0).icon().isNull())
        page._thumbnail_loaded(current_task.token, self._solid_image(0xAA0000), "")
        self.assertTrue(page.previews.item(0).icon().isNull())
        self.assertTrue(page.preview_bindings_match_detail())

    def test_same_sha_instances_use_distinct_matching_cache_evidence(self) -> None:
        sources = [self.root / f"copy-{index}.png" for index in range(3)]
        for source in sources:
            Image.new("RGB", (80, 60), (40, 80, 120)).save(source)
        original_bytes = [source.read_bytes() for source in sources]
        service = ThumbnailService(self.root / "app-data", max_size=(48, 48))
        results = [
            service.load(
                source,
                content_identity="sha256:same",
                physical_instance_id=instance_id,
            )
            for instance_id, source in zip((201, 202, 203), sources)
        ]
        self.assertTrue(all(result.error is None for result in results))
        self.assertEqual(len({result.cache_path for result in results}), 3)
        self.assertEqual(len({result.cache_path.read_bytes() for result in results}), 1)
        self.assertEqual([source.read_bytes() for source in sources], original_bytes)

    def test_runtime_root_validation_and_retired_drive_rejection(self) -> None:
        evidence_root = self.root / "evidence"
        evidence_root.mkdir()
        evidence = SyntheticEvidence(evidence_root)
        app_root = self.root / "app-data"
        bootstrap_production(
            app_data_root=app_root,
            baselines=evidence.baselines,
            **{
                key: value for key, value in evidence.kwargs(self.root / "unused").items()
                if key not in {"database_path", "baselines"}
            },
        )
        checked, independent = validate_runtime_roots(str(app_root))
        self.assertEqual(checked, app_root)
        self.assertIsNone(independent)
        with mock.patch.object(Path, "is_dir", side_effect=AssertionError("Z accessed")):
            with self.assertRaisesRegex(Exception, "RETIRED_DRIVE"):
                validate_runtime_roots(r"Z:\retired")

    def test_packaged_entry_without_arguments_routes_to_startup_dialog(self) -> None:
        with mock.patch.object(StartupDialog, "exec", return_value=StartupDialog.Rejected):
            self.assertEqual(packaged_main([]), 0)

    def test_runtime_and_packaging_sources_have_no_hard_coded_production_roots(self) -> None:
        files = list((SOURCE_ROOT / "personal_librarian" / "desktop").glob("*.py"))
        files.extend((REPOSITORY_ROOT / "packaging").glob("*"))
        text = "\n".join(
            path.read_text(encoding="utf-8") for path in files if path.is_file()
        )
        self.assertNotIn("H:\\PersonalLibrarianData", text)
        self.assertNotIn("X:\\PersonalLibrarianBackup", text)


if __name__ == "__main__":
    unittest.main()
