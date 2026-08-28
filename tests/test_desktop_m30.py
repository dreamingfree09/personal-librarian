from __future__ import annotations

import os
import sqlite3
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

from PySide6.QtWidgets import QApplication, QDialog, QListWidgetItem

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.migrations import MIGRATIONS
from personal_librarian.collections import (
    add_content_to_collection,
    create_collection,
)
from personal_librarian.date_evidence import set_owner_preferred_date
from personal_librarian.desktop.library_page import (
    COLLECTION_ROLE,
    CONTENT_ROLE,
    CreateCollectionDialog,
    DateEvidenceDialog,
    LibraryPage,
    OwnerPreferredDateDialog,
    format_preferred_value,
    preferred_summary,
)
from personal_librarian.desktop.preferences import UiPreferences
from personal_librarian.desktop.services import DesktopDataService


class _CapturingPool:
    def __init__(self) -> None:
        self.tasks: list[object] = []

    def start(self, task: object) -> None:
        self.tasks.append(task)


class DesktopM30Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.app_root = self.root / "app-data"
        (self.app_root / "catalogue").mkdir(parents=True)
        self.database = self.app_root / "catalogue" / "personal_librarian.sqlite3"
        initialise_catalogue(self.database)
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.source_id = int(connection.execute(
            "INSERT INTO sources(source_key,display_name,source_type) "
            "VALUES('source','Owner source','test')"
        ).lastrowid)
        self.content_ids: list[int] = []
        for index in range(5):
            content_id = int(connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES(?)",
                (f"content-{index}",),
            ).lastrowid)
            self.content_ids.append(content_id)
            connection.execute(
                "INSERT INTO physical_instances(instance_key,source_id,content_identity_id,"
                "raw_relative_path,extension,size_bytes,observed_created_at) "
                "VALUES(?,?,?,?,'.jpg',?,?)",
                (f"instance-{index}", self.source_id, content_id, f"item-{index}.jpg",
                 100 + index, f"199{index}-01-01T00:00:00Z"),
            )
        connection.execute(
            "INSERT INTO physical_instances(instance_key,source_id,content_identity_id,"
            "raw_relative_path,extension,size_bytes) VALUES('exact-copy',?,?,'.\\copy.jpg','.jpg',200)",
            (self.source_id, self.content_ids[0]),
        )
        for content_id, status in (
            (self.content_ids[2], "needs_review"),
            (self.content_ids[3], "unknown"),
        ):
            connection.execute(
                "INSERT INTO content_preferred_dates(content_identity_id,status,selection_method,"
                "actor_type,actor_identifier,provenance,determined_at) "
                "VALUES(?,?,'no_selection','system','preferred-date-policy-v1',"
                "'deterministic-policy','2026-01-01T00:00:00Z')",
                (content_id, status),
            )
        connection.commit()
        connection.close()
        set_owner_preferred_date(
            database_path=self.database, content_identity_id=self.content_ids[0],
            value="2019", actor="owner", action_id="date-2019",
        )
        set_owner_preferred_date(
            database_path=self.database, content_identity_id=self.content_ids[1],
            value="2020-03-04", actor="owner", action_id="date-2020",
        )
        self.first_collection = create_collection(
            database_path=self.database, name="Family", actor="owner",
            action_id="collection-one",
        )
        self.second_collection = create_collection(
            database_path=self.database, name="Family", actor="owner",
            action_id="collection-two",
        )
        add_content_to_collection(
            database_path=self.database,
            collection_uuid=str(self.first_collection["collection_uuid"]),
            content_identity_id=self.content_ids[0], actor="owner", action_id="member-a",
        )
        add_content_to_collection(
            database_path=self.database,
            collection_uuid=str(self.first_collection["collection_uuid"]),
            content_identity_id=self.content_ids[1], actor="owner", action_id="member-b",
        )
        self.service = DesktopDataService(self.app_root)


class DesktopM30ServiceTests(DesktopM30Case):
    def test_preferred_year_cutover_and_unknown_status_pages(self) -> None:
        years = self.service.browse_years()
        counts = {row["year"]: row["content_count"] for row in years["years"]}
        self.assertEqual(counts, {2020: 1, 2019: 1, None: 2})
        self.assertIn("not a fallback", years["evidence_policy"])
        year_only = self.service.year_content(year=2019, limit=25, offset=0)
        self.assertEqual([row["content_identity_id"] for row in year_only["content"]],
                         [self.content_ids[0]])
        self.assertEqual(year_only["content"][0]["selected_precision"], "year")
        unknown = self.service.year_content(year=None, limit=25, offset=0)
        self.assertEqual(
            {row["content_identity_id"] for row in unknown["content"]},
            set(self.content_ids[3:]),
        )
        self.assertNotIn(self.content_ids[2], {
            row["content_identity_id"] for row in unknown["content"]
        })
        # The missing preferred row has a valid 1994 observed timestamp but no 1994 shelf.
        self.assertNotIn(1994, counts)
        review = self.service.preferred_review_page(
            status="needs_review", limit=25, offset=0
        )
        self.assertEqual(review["items"][0]["content_identity_id"], self.content_ids[2])
        self.assertEqual(review["items"][0]["raw_relative_path"], "item-2.jpg")

    def test_unknown_pagination_and_representative_instance_are_deterministic(self) -> None:
        connection = connect_existing_catalogue(self.database, read_only=False)
        chosen_instance_id = int(connection.execute(
            "INSERT INTO physical_instances(instance_key,source_id,content_identity_id,"
            "raw_relative_path,current_observed_path,extension,size_bytes) "
            "VALUES('unknown-present-a',?,?,'.\\present-a.jpg','C:\\present-a.jpg','.jpg',201)",
            (self.source_id, self.content_ids[3]),
        ).lastrowid)
        connection.execute(
            "INSERT INTO physical_instances(instance_key,source_id,content_identity_id,"
            "raw_relative_path,current_observed_path,extension,size_bytes) "
            "VALUES('unknown-present-b',?,?,'.\\present-b.jpg','C:\\present-b.jpg','.jpg',202)",
            (self.source_id, self.content_ids[3]),
        )
        added_ids = []
        for index in range(3):
            content_id = int(connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES(?)",
                (f"unknown-page-{index}",),
            ).lastrowid)
            added_ids.append(content_id)
            connection.execute(
                "INSERT INTO physical_instances(instance_key,source_id,content_identity_id,"
                "raw_relative_path,extension,size_bytes) VALUES(?,?,?,?,'.jpg',?)",
                (f"unknown-page-instance-{index}", self.source_id, content_id,
                 f"unknown-page-{index}.jpg", 300 + index),
            )
        connection.commit()
        connection.close()

        expected = [self.content_ids[3], self.content_ids[4], *added_ids]
        first = self.service.year_content(year=None, limit=2, offset=0)
        second = self.service.year_content(year=None, limit=2, offset=2)
        third = self.service.year_content(year=None, limit=2, offset=4)
        actual = [
            row["content_identity_id"]
            for page in (first, second, third) for row in page["content"]
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(first["total_matching"], len(expected))
        representative = first["content"][0]
        self.assertEqual(representative["physical_instance_id"], chosen_instance_id)
        self.assertEqual(representative["current_observed_path"], r"C:\present-a.jpg")
        self.assertEqual(representative["physical_instance_count"], 3)
        self.assertEqual(sum(row["content_identity_id"] == self.content_ids[3]
                             for row in first["content"]), 1)

    def test_unknown_page_can_be_empty_while_needs_review_remains_separate(self) -> None:
        for index, content_id in enumerate(self.content_ids[3:]):
            set_owner_preferred_date(
                database_path=self.database, content_identity_id=content_id,
                value=f"201{index}", actor="owner",
                action_id=f"resolve-unknown-{index}",
            )
        unknown = self.service.year_content(year=None, limit=25, offset=0)
        self.assertEqual(unknown["total_matching"], 0)
        self.assertEqual(unknown["content"], [])
        review = self.service.preferred_review_page(
            status="needs_review", limit=25, offset=0
        )
        self.assertEqual(review["total_matching"], 1)
        self.assertEqual(review["items"][0]["content_identity_id"], self.content_ids[2])

    def test_unknown_facade_uses_three_bounded_queries_without_n_plus_one(self) -> None:
        write_connection = connect_existing_catalogue(self.database, read_only=False)
        write_connection.executemany(
            "INSERT INTO content_identities(identity_key) VALUES(?)",
            ((f"large-unknown-{index}",) for index in range(600)),
        )
        write_connection.commit()
        write_connection.close()
        connection = connect_existing_catalogue(self.database, read_only=True)
        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        with mock.patch(
            "personal_librarian.desktop.services.connect_existing_catalogue",
            return_value=connection,
        ):
            result = self.service._preferred_unknown_content(
                limit=1, offset=0, unorganised_only=False
            )
        selects = [
            statement for statement in statements
            if statement.lstrip().upper().startswith(("SELECT", "WITH"))
        ]
        self.assertEqual(len(selects), 3)
        self.assertNotIn("physical_instances", selects[0])
        self.assertNotIn("ORDER BY", selects[0].upper())
        self.assertNotIn("JOIN", selects[0].upper())
        self.assertIn("status IN ('resolved','needs_review')", selects[0])
        self.assertIn("ORDER BY ci.content_identity_id", selects[1])
        self.assertIn("LIMIT 1 OFFSET 0", selects[1])
        self.assertIn("WITH page(content_identity_id,page_order) AS (VALUES", selects[2])
        self.assertEqual(result["total_matching"], 602)
        self.assertEqual(len(result["content"]), 1)

    def test_year_and_unknown_counts_share_exact_projection_arithmetic(self) -> None:
        years = self.service.browse_years()
        unknown = self.service.year_content(year=None, limit=2, offset=0)
        year_counts = {row["year"]: row["content_count"] for row in years["years"]}

        self.assertEqual(year_counts, {2020: 1, 2019: 1, None: 2})
        self.assertEqual(year_counts[None], unknown["total_matching"])
        self.assertEqual(
            [row["content_identity_id"] for row in unknown["content"]],
            self.content_ids[3:],
        )

        connection = connect_existing_catalogue(self.database, read_only=True)
        reference_unknown = int(connection.execute(
            """
            SELECT COUNT(*)
            FROM content_identities ci
            LEFT JOIN content_preferred_dates p
              ON p.content_identity_id=ci.content_identity_id
            WHERE p.preferred_date_id IS NULL OR p.status='unknown'
            """
        ).fetchone()[0])
        connection.close()
        self.assertEqual(reference_unknown, unknown["total_matching"])

        connection = connect_existing_catalogue(self.database, read_only=True)
        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        with mock.patch(
            "personal_librarian.desktop.services.connect_existing_catalogue",
            return_value=connection,
        ):
            preferred_years = self.service._preferred_browse_years()
        selects = [
            statement for statement in statements
            if statement.lstrip().upper().startswith("SELECT")
        ]
        self.assertEqual(len(selects), 1)
        self.assertNotIn("JOIN", selects[0].upper())
        self.assertIn("status IN ('resolved','needs_review')", selects[0])
        self.assertEqual(preferred_years, years)

    def test_preferred_detail_owner_replacement_and_precision_rendering(self) -> None:
        detail = self.service.preferred_date_detail(self.content_ids[0], limit=25)
        self.assertEqual(detail["preferred_date"]["selected_precision"], "year")
        self.assertEqual(detail["evidence"][0]["source_name"], None)
        replaced = self.service.set_owner_date(
            content_identity_id=self.content_ids[0], value="2019-08-14T12:30+01:00",
            actor="owner", action_id="replace-date", reason="Owner correction", replace=True,
        )
        self.assertTrue(replaced["changed"])
        current = self.service.preferred_date_detail(self.content_ids[0])["preferred_date"]
        self.assertEqual(format_preferred_value(current), "2019-08-14 12:30+01:00")
        self.assertEqual(preferred_summary(current),
                         ("2019-08-14 12:30+01:00", "Owner-set", "Resolved"))

    def test_collections_are_distinct_bounded_and_history_is_domain_filtered(self) -> None:
        collections = self.service.collections(state="active", limit=1, offset=0)
        self.assertEqual(len(collections["collections"]), 1)
        self.assertEqual(collections["total_matching"], 2)
        all_collections = self.service.collections(state="active", limit=25, offset=0)
        self.assertEqual(
            len({row["collection_uuid"] for row in all_collections["collections"]}), 2
        )
        members = self.service.collection_members(
            str(self.first_collection["collection_uuid"]), limit=25
        )
        self.assertEqual(members["total_matching"], 2)
        self.assertEqual(
            next(row for row in members["members"]
                 if row["content_identity_id"] == self.content_ids[0])["physical_instance_count"],
            2,
        )
        collection_history = self.service.desktop_history(
            domain="collections", limit=1, offset=0
        )
        date_history = self.service.desktop_history(
            domain="preferred_dates", limit=1, offset=0
        )
        self.assertEqual(len(collection_history["history"]), 1)
        self.assertGreaterEqual(collection_history["total_matching"], 4)
        self.assertEqual(len(date_history["history"]), 1)
        self.assertEqual(date_history["total_matching"], 2)

    def test_desktop_history_normalises_exact_timestamps_for_every_source(self) -> None:
        album = self.service.create_album(
            name="History album", description=None, actor="owner", reason=None,
        )
        histories = (
            self.service.desktop_history(domain="preferred_dates", limit=25, offset=0),
            self.service.organisation_history(
                album_uuid=str(album["album_uuid"]), limit=25, offset=0
            ),
            self.service.collection_history(
                str(self.first_collection["collection_uuid"]), limit=25, offset=0
            ),
        )
        connection = connect_existing_catalogue(self.database, read_only=True)
        source_timestamps = {
            int(row[0]): str(row[1])
            for row in connection.execute(
                "SELECT organisation_event_id,recorded_at FROM organisation_events"
            ).fetchall()
        }
        connection.close()

        page = LibraryPage(self.service, UiPreferences())
        for history in histories:
            rows = history["history"]
            event_ids = [int(row["organisation_event_id"]) for row in rows]
            self.assertEqual(event_ids, sorted(event_ids, reverse=True))
            self.assertEqual(len(event_ids), len(set(event_ids)))
            for row in rows:
                self.assertIn("occurred_at", row)
                self.assertNotIn("recorded_at", row)
                self.assertEqual(
                    row["occurred_at"],
                    source_timestamps[int(row["organisation_event_id"])],
                )
            page._history_loaded(history)
            self.assertEqual(page.history.rowCount(), len(rows))
        page._history_loaded({"history": [], "total_matching": 0})
        self.assertEqual(page.history.rowCount(), 0)
        page.close()

    def test_collection_facade_lifecycle_and_membership_round_trip(self) -> None:
        created = self.service.create_collection(
            name="Holidays", description=None, actor="owner", action_id="ui-create",
            reason="Desktop test",
        )
        uuid = str(created["collection_uuid"])
        renamed = self.service.rename_collection(
            collection_uuid=uuid, name="Trips", actor="owner",
            action_id="ui-rename", reason=None,
        )
        self.assertEqual(renamed["name"], "Trips")
        added = self.service.set_collection_membership(
            collection_uuid=uuid, content_identity_id=self.content_ids[2],
            operation="add", actor="owner", action_id="ui-add", reason=None,
        )
        self.assertEqual(added["membership_state"], "active")
        removed = self.service.set_collection_membership(
            collection_uuid=uuid, content_identity_id=self.content_ids[2],
            operation="remove", actor="owner", action_id="ui-remove", reason=None,
        )
        self.assertEqual(removed["membership_state"], "removed")
        restored = self.service.set_collection_membership(
            collection_uuid=uuid, content_identity_id=self.content_ids[2],
            operation="restore", actor="owner", action_id="ui-restore", reason=None,
        )
        self.assertEqual(restored["membership_state"], "active")
        archived = self.service.set_collection_archived(
            collection_uuid=uuid, archived=True, actor="owner",
            action_id="ui-archive", reason=None,
        )
        self.assertEqual(archived["state"], "archived")
        active = self.service.set_collection_archived(
            collection_uuid=uuid, archived=False, actor="owner",
            action_id="ui-restore-collection", reason=None,
        )
        self.assertEqual(active["state"], "active")

    def test_schema9_uses_legacy_years_and_reports_m30_unavailable(self) -> None:
        legacy_root = self.root / "legacy"
        (legacy_root / "catalogue").mkdir(parents=True)
        database = legacy_root / "catalogue" / "personal_librarian.sqlite3"
        connection = sqlite3.connect(database)
        for migration in MIGRATIONS[:9]:
            escaped = migration.name.replace("'", "''")
            connection.executescript(
                "BEGIN IMMEDIATE;\n" + migration.sql +
                f"\nINSERT INTO schema_migrations(version,name) VALUES({migration.version},'{escaped}');\nCOMMIT;"
            )
        connection.execute(
            "INSERT INTO content_identities(identity_key) VALUES('legacy-content')"
        )
        connection.commit()
        connection.close()
        service = DesktopDataService(legacy_root)
        self.assertEqual(service.schema_capabilities(), {
            "schema_version": 9, "preferred_dates_enabled": False,
            "collections_enabled": False, "legacy_years": True,
        })
        self.assertTrue(service.browse_years()["evidence_policy"].startswith("A year is shown"))
        self.assertEqual(
            service.desktop_history(domain="collections", limit=25)["history"], []
        )


class DesktopM30WidgetTests(DesktopM30Case):
    def test_preferred_value_rendering_preserves_each_precision(self) -> None:
        base = {"status": "resolved", "selected_year": 2019}
        self.assertEqual(format_preferred_value(base | {"selected_precision": "year"}), "2019")
        self.assertEqual(format_preferred_value(base | {
            "selected_precision": "year_month", "selected_month": 8,
        }), "2019-08")
        self.assertEqual(format_preferred_value(base | {
            "selected_precision": "date", "selected_month": 8, "selected_day": 14,
        }), "2019-08-14")
        self.assertEqual(format_preferred_value(base | {
            "selected_precision": "datetime", "selected_month": 8, "selected_day": 14,
            "selected_hour": 9, "selected_minute": 5, "selected_second": 7,
            "selected_timezone_state": "unknown",
        }), "2019-08-14 09:05:07")

    def test_date_and_collection_dialogs_open_cancel_repeatedly_with_ownership(self) -> None:
        service = mock.Mock()
        service.layout = SimpleNamespace(root=self.app_root)
        page = LibraryPage(service, UiPreferences())
        self.addCleanup(page.close)
        detail = {
            "preferred_date": None, "reason": "No preferred record",
            "evidence": [], "basis": [],
        }
        for _ in range(5):
            dialogs = (
                CreateCollectionDialog(page),
                OwnerPreferredDateDialog(1, None, page),
                DateEvidenceDialog(detail, page),
            )
            for dialog in dialogs:
                self.assertIs(dialog.parent(), page)
                dialog.reject()
                dialog.close()

    def test_collection_form_keeps_actor_reason_and_description_separate(self) -> None:
        service = mock.Mock()
        service.layout = SimpleNamespace(root=self.app_root)
        page = LibraryPage(service, UiPreferences(last_actor="owner-test"))
        self.addCleanup(page.close)
        page.m30_enabled = True
        page.reason.setText("Owner reason")
        page._confirm = mock.Mock(return_value=True)
        page._reload_collections = mock.Mock()
        page.run_async = lambda operation, completed: completed(operation())
        with mock.patch(
            "personal_librarian.desktop.library_page.CreateCollectionDialog"
        ) as dialog_type:
            dialog_type.return_value.exec.return_value = QDialog.Accepted
            dialog_type.return_value.values.return_value = ("Family", "Family photographs")
            page._create_collection()
        call = service.create_collection.call_args.kwargs
        self.assertEqual(call["description"], "Family photographs")
        self.assertEqual(call["actor"], "owner-test")
        self.assertEqual(call["reason"], "Owner reason")
        self.assertNotIn(call["description"], (call["actor"], call["reason"]))
        self.assertTrue(call["action_id"].startswith("desktop:collection-create:"))
        form = CreateCollectionDialog()
        self.addCleanup(form.close)
        self.assertEqual(form.values(), ("", None))

    def test_owner_date_dialog_requires_explicit_replacement_and_refreshes(self) -> None:
        service = mock.Mock()
        service.layout = SimpleNamespace(root=self.app_root)
        service.preferred_date_detail.return_value = {
            "preferred_date": {
                "status": "resolved", "selection_method": "owner_selection",
                "selected_precision": "year", "selected_year": 2019,
            }, "evidence": [], "basis": [],
        }
        service.set_owner_date.return_value = {"changed": True}
        page = LibraryPage(service, UiPreferences(last_actor="owner-test"))
        self.addCleanup(page.close)
        page.m30_enabled = True
        page.reason.setText("Correction")
        item = QListWidgetItem("Content")
        item.setData(CONTENT_ROLE, 7)
        page.content.addItem(item)
        item.setSelected(True)
        page._confirm = mock.Mock(return_value=True)
        page.refresh = mock.Mock()
        page.run_async = lambda operation, completed: completed(operation())
        with mock.patch(
            "personal_librarian.desktop.library_page.OwnerPreferredDateDialog"
        ) as dialog_type:
            dialog_type.return_value.exec.return_value = QDialog.Accepted
            dialog_type.return_value.values.return_value = ("date", "2020-02-03", True)
            page._set_owner_date()
        call = service.set_owner_date.call_args.kwargs
        self.assertTrue(call["replace"])
        self.assertEqual(call["actor"], "owner-test")
        self.assertEqual(call["reason"], "Correction")
        self.assertEqual(call["value"], "2020-02-03")
        self.assertTrue(call["action_id"].startswith("desktop:preferred-date:"))
        page.refresh.assert_called_once()

    def test_rapid_year_and_collection_switches_reject_stale_results(self) -> None:
        service = mock.Mock()
        service.layout = SimpleNamespace(root=self.app_root)
        service.year_content.side_effect = lambda year, **_: {
            "content": [{
                "content_identity_id": year, "identity_key": f"content-{year}",
                "raw_relative_path": f"{year}.jpg", "physical_instance_id": 0,
                "current_observed_path": None, "physical_instance_count": 1,
                "preferred_status": "resolved", "selection_method": "owner_selection",
                "selected_precision": "year", "selected_year": year,
            }], "total_matching": 1, "unorganised_only": False,
        }
        service.year_albums.return_value = {"albums": []}
        service.albums.return_value = {"albums": []}
        service.albums_for_content.return_value = {"albums": []}
        service.tags_for_content.return_value = {"tags": []}
        service.collections_for_content.return_value = {"collections": []}
        service.collections.side_effect = lambda state, **_: {
            "collections": [{
                "collection_uuid": state, "name": state, "state": state,
                "active_member_count": 0, "removed_member_count": 0,
                "duplicate_name_count": 1,
            }], "total_matching": 1,
        }
        page = LibraryPage(service, UiPreferences())
        self.addCleanup(page.close)
        page.pool = _CapturingPool()
        page.has_year_selection = True
        page.current_year = 2019
        page._reload_year()
        page.current_year = 2020
        page._reload_year()
        page.pool.tasks[1].run()
        page.pool.tasks[0].run()
        self.assertEqual(page.content.item(0).data(CONTENT_ROLE), 2020)

        page.m30_enabled = True
        page.collection_filter.blockSignals(True)
        page.collection_filter.setCurrentText("Active")
        page._reload_collections()
        page.collection_filter.setCurrentText("Archived")
        page.collection_filter.blockSignals(False)
        page._reload_collections()
        page.pool.tasks[3].run()
        page.pool.tasks[2].run()
        self.assertEqual(page.collection_rows[0]["state"], "archived")

    def test_schema9_ui_disables_m30_controls_without_querying_collections(self) -> None:
        service = mock.Mock()
        service.layout = SimpleNamespace(root=self.app_root)
        page = LibraryPage(service, UiPreferences())
        self.addCleanup(page.close)
        page._top_level_loaded((
            {"schema_version": 9, "preferred_dates_enabled": False,
             "collections_enabled": False, "legacy_years": True},
            {"years": [], "evidence_policy": "legacy"},
            {"tags": []}, None,
        ))
        self.assertFalse(page.owner_date_button.isEnabled())
        self.assertFalse(page.collection_table.isEnabled())
        self.assertIn("unavailable", page.collection_availability.text())
        service.collections.assert_not_called()


if __name__ == "__main__":
    unittest.main()
