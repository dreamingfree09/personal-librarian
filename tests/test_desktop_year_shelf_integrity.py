"""F14: the primary Year shelves partition all identities, across calendar range."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from unittest import mock

from test_desktop_m30 import DesktopM30Case
from personal_librarian.catalogue.database import CatalogueError
from personal_librarian.date_evidence import set_owner_preferred_date
from personal_librarian.desktop.library_page import CONTENT_ROLE, LibraryPage
from personal_librarian.desktop.preferences import UiPreferences


class YearShelfIntegrityTests(DesktopM30Case):
    def add_date(self, value: str) -> int:
        with closing(sqlite3.connect(self.database)) as connection:
            content = connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES(?)", ("date-" + value,)
            ).lastrowid
            connection.commit()
        set_owner_preferred_date(database_path=self.database, content_identity_id=content,
                                 value=value, actor="synthetic", action_id="date-" + value)
        return content

    def assert_partition(self) -> None:
        seen = []
        for shelf in self.service.browse_years()["years"]:
            members = []
            for offset in range(shelf["content_count"] + 1):
                page = self.service.year_content(year=shelf["year"], limit=1, offset=offset)
                self.assertEqual(page["total_matching"], shelf["content_count"])
                members.extend(row["content_identity_id"] for row in page["content"])
            self.assertEqual(len(members), shelf["content_count"])
            self.assertEqual(len(set(members)), len(members))
            seen.extend(members)
        with closing(sqlite3.connect(self.database)) as connection:
            expected = {row[0] for row in connection.execute("SELECT content_identity_id FROM content_identities")}
        self.assertEqual(set(seen), expected)
        self.assertEqual(len(seen), len(expected))

    def test_all_supported_calendar_shelves_open_and_page(self) -> None:
        for value in ("0001", "0001-02-03", "1899", "2101-12-31", "9999"):
            self.add_date(value)
        self.assert_partition()
        self.assertEqual(self.service.year_content(year=7777, limit=1, offset=0)["content"], [])
        for invalid in (0, 10000, True, "2000"):
            with self.assertRaises(CatalogueError):
                self.service.year_content(year=invalid, limit=1, offset=0)

    def test_status_transition_never_hides_or_duplicates_an_identity(self) -> None:
        self.assert_partition()
        set_owner_preferred_date(database_path=self.database, content_identity_id=self.content_ids[2],
                                 value="1800", actor="synthetic", action_id="resolve-review")
        self.assert_partition()
        self.assertEqual(self.service.preferred_review_page(status="needs_review", limit=25)["items"], [])

    def test_album_membership_uses_the_same_unknown_and_extreme_year_contract(self) -> None:
        ancient = self.add_date("0001")
        album = self.service.create_album(name="Synthetic", description=None, actor="synthetic", reason=None)
        for content in (ancient, self.content_ids[2], self.content_ids[3]):
            self.service.set_album_membership(album_uuid=album["album_uuid"], content_identity_id=content,
                                              present=True, actor="synthetic", reason=None)
        self.assertEqual(self.service.year_albums(year=1)["albums"][0]["year_member_count"], 1)
        self.assertEqual(self.service.year_albums(year=None)["albums"][0]["year_member_count"], 2)
        self.assertEqual(self.service.year_albums(year=7777)["albums"], [])
        unorganised = self.service.year_content(year=None, limit=25, offset=0, unorganised_only=True)
        self.assertEqual([r["content_identity_id"] for r in unorganised["content"]], [self.content_ids[4]])

    def test_actual_library_navigation_filters_and_paging(self) -> None:
        ancient = self.add_date("0001")
        self.add_date("0001-02-03")
        self.add_date("9999")
        page = LibraryPage(self.service, UiPreferences())
        self.addCleanup(page.close)
        page.page_size = 1
        page.run_async = lambda operation, completed: completed(operation())
        # No file reads or preview jobs: these fixtures have no media.
        page.refresh()
        for index in range(page.years.count()):
            page.years.setCurrentRow(index)
            year = page.years.item(index).data(CONTENT_ROLE)
            self.assertEqual(page.current_year, year)
            self.assertEqual(page.total, self.service.year_content(year=year, limit=1, offset=0)["total_matching"])
        page.date_filter.setCurrentIndex(1)
        self.assertEqual(page.content.item(0).data(CONTENT_ROLE), self.content_ids[2])
        page.date_filter.setCurrentIndex(2)
        self.assertNotIn(self.content_ids[2], [row["content_identity_id"] for row in page.content_rows])
        page.date_filter.setCurrentIndex(0)
        for index in range(page.years.count()):
            if page.years.item(index).data(CONTENT_ROLE) == 1:
                page.years.setCurrentRow(index)
                break
        self.assertEqual(page.total, 2)
        first = page.content.item(0).data(CONTENT_ROLE)
        page.next.click()
        self.assertEqual(page.offset, 1)
        second = page.content.item(0).data(CONTENT_ROLE)
        self.assertNotEqual(first, second)
        self.assertIn(ancient, (first, second))
        page.previous.click()
        self.assertEqual(page.content.item(0).data(CONTENT_ROLE), first)
