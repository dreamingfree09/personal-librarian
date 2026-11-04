"""Deterministic Album races using real Qt widgets and retained Library workers."""
from __future__ import annotations
import copy
from contextlib import closing
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QListWidgetItem
from personal_librarian.desktop.library_page import (
    ALBUM_ROLE, CONTENT_ROLE, GENERATION_ROLE, LibraryPage, LibraryPreviewBinding,
)
from personal_librarian.desktop.preferences import UiPreferences

A = '00000000-0000-4000-8000-000000000001'
B = '00000000-0000-4000-8000-000000000002'

class CapturingPool:
    def __init__(self): self.tasks = []
    def start(self, task): self.tasks.append(task)

class AlbumSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = mock.Mock()
        self.service.layout = SimpleNamespace(root=Path(self.temp.name) / 'app')
        self.page = LibraryPage(self.service, UiPreferences(last_actor='synthetic-owner'))
        self.addCleanup(self.page.close)
        self.page.pool = CapturingPool()
        self.page._confirm = mock.Mock(return_value=True)
        for name in ('warning', 'information'):
            patcher = mock.patch('personal_librarian.desktop.library_page.QMessageBox.' + name)
            patcher.start(); self.addCleanup(patcher.stop)
        self.albums = [self.album(A), self.album(B)]
        self.results = {A: self.result(A, [11]), B: self.result(B, [22])}
        self.service.album_members.side_effect = lambda uuid: copy.deepcopy(self.results[uuid])
        self.page.album_rows = copy.deepcopy(self.albums)
        self.page._render_albums()

    @staticmethod
    def album(uuid, state='active'):
        return dict(album_uuid=uuid, name='Same visible name', state=state,
                    member_count=1, year_member_count=1, description='Synthetic ' + uuid[-1])

    @staticmethod
    def member(identity):
        return dict(content_identity_id=identity, identity_key=f'synthetic-{identity}',
                    physical_instance_id=0, current_observed_path=None,
                    raw_relative_path=f'synthetic-{identity}.jpg', size_bytes=12, source='Synthetic')

    def result(self, uuid, ids):
        album=self.album(uuid); album['member_count']=len(ids)
        return dict(album=album, members=[self.member(i) for i in ids])

    def select(self, uuid):
        for row in range(self.page.albums.rowCount()):
            if self.page.albums.item(row, 0).data(ALBUM_ROLE) == uuid:
                self.page.albums.selectRow(row)
                return self.page.pool.tasks[-1]
        self.fail('Album not visible')

    def deliver(self, worker, result=None):
        worker.signals.completed.emit(copy.deepcopy(result) if result is not None else worker.operation())
        worker.signals.finished.emit()

    def ids(self):
        return [self.page.members.item(i).data(CONTENT_ROLE) for i in range(self.page.members.count())]

    def snapshot(self):
        return (self.ids(), self.page.album_detail.text(), self.page._generation,
                getattr(self.page, '_loaded_album_uuid', None), self.page.remove_button.isEnabled())

    def test_out_of_order_same_name_albums_preserve_current_details(self):
        a=self.select(A); b=self.select(B)
        self.deliver(b); expected=self.snapshot()
        self.deliver(a)
        self.assertEqual(self.ids(), [22])
        self.assertEqual(self.snapshot(), expected)
        self.assertEqual(self.page._selected_album()['album_uuid'], B)

    def test_loading_new_selection_immediately_clears_old_members(self):
        self.deliver(self.select(A)); self.page.members.item(0).setSelected(True)
        self.select(B)
        self.assertEqual(self.ids(), [])
        self.assertFalse(self.page.remove_button.isEnabled())
        self.assertIn('Loading', self.page.album_detail.text())
        self.assertIsNone(self.page._loaded_album_uuid)

    def test_rapid_a_b_a_rejects_first_a_and_b(self):
        first=self.select(A); middle=self.select(B); last=self.select(A)
        self.deliver(last, self.result(A, [33])); expected=self.snapshot()
        self.deliver(first); self.deliver(middle)
        self.assertEqual(self.ids(), [33]); self.assertEqual(self.snapshot(), expected)

    def test_clear_selection_rejects_pending_response_and_current_row(self):
        a=self.select(A)
        self.page.albums.clearSelection()
        self.deliver(a)
        self.assertEqual(self.ids(), [])
        self.assertIsNone(self.page._selected_album())
        self.assertIn('Select an album', self.page.album_detail.text())

    def test_filter_change_and_same_row_replacement_clear_selection(self):
        a=self.select(A)
        self.page.album_filter.setCurrentText('Archived')
        self.deliver(a); self.assertEqual(self.ids(), [])
        self.assertIsNone(self.page._selected_album())
        self.page.album_filter.setCurrentText('Active')
        a=self.select(A)
        self.page.album_rows=[self.album(B)]
        self.page._render_albums(); self.deliver(a)
        self.assertEqual(self.ids(), []); self.assertIsNone(self.page._selected_album())

    def test_year_navigation_invalidates_members_before_year_load(self):
        a=self.select(A)
        item=QListWidgetItem('2020'); item.setData(CONTENT_ROLE, 2020)
        self.page.years.addItem(item); self.page.years.setCurrentItem(item)
        self.deliver(a)
        self.assertEqual(self.ids(), []); self.assertIsNone(self.page._selected_album())
        self.assertEqual(self.page.current_year, 2020)

    def test_refresh_rejects_pending_members_and_old_year_response(self):
        self.page.has_year_selection=True; self.page.current_year=2020
        self.page._reload_year(); old_year=self.page.pool.tasks[-1]
        self.page.album_rows=copy.deepcopy(self.albums); self.page._render_albums()
        a=self.select(A)
        self.page.refresh(); self.deliver(a)
        self.deliver(old_year, ({'content': [], 'total_matching': 0, 'unorganised_only': False},
                                {'albums': self.albums}, {'albums': self.albums}))
        self.assertEqual(self.ids(), []); self.assertEqual(self.page.albums.rowCount(), 0)

    def test_year_list_replacement_rejects_pending_members(self):
        a=self.select(A)
        self.page._year_loaded(({'content': [], 'total_matching': 0, 'unorganised_only': False},
                                {'albums': [self.album(B)]}, {'albums': []}))
        self.deliver(a)
        self.assertEqual(self.ids(), []); self.assertIsNone(self.page._selected_album())

    def test_mismatched_payload_and_duplicate_completion_have_no_effect(self):
        a=self.select(A); expected=self.snapshot()
        self.deliver(a, self.results[B]); self.assertEqual(self.snapshot(), expected)
        self.deliver(a); expected=self.snapshot()
        self.deliver(a, self.result(A, [99])); self.assertEqual(self.snapshot(), expected)

    def test_empty_and_archived_albums_display_without_mutation(self):
        self.results[A]=self.result(A, [])
        self.deliver(self.select(A)); self.assertEqual(self.ids(), [])
        self.assertIn('0 members', self.page.album_detail.text())
        self.page.album_rows=[self.album(B, 'archived')]
        self.page.album_filter.setCurrentText('Archived')
        self.results[B]['album']['state']='archived'
        self.deliver(self.select(B)); self.assertEqual(self.ids(), [22])
        self.assertFalse(self.page.remove_button.isEnabled())
        self.page.members.item(0).setSelected(True)
        self.page._remove_selected()
        self.service.set_album_membership.assert_not_called()

    def test_wrong_album_members_cannot_be_removed(self):
        self.deliver(self.select(A)); self.page.members.item(0).setSelected(True)
        self.page.albums.blockSignals(True)
        self.page.albums.selectRow(1)
        self.page.albums.blockSignals(False)
        previous=len(self.page.pool.tasks)
        self.page._remove_selected()
        self.assertEqual(len(self.page.pool.tasks), previous)
        self.service.set_album_membership.assert_not_called()
        self.page._confirm.assert_not_called()

    def test_selection_change_during_confirmation_cancels_mutation(self):
        self.deliver(self.select(A)); self.page.members.item(0).setSelected(True)
        def change(_): self.select(B); return True
        self.page._confirm.side_effect=change
        self.page._remove_selected()
        # Only the new B read is scheduled, never an A/B membership write.
        self.assertEqual(self.page.pool.tasks[-1].operation()['album']['album_uuid'], B)
        self.service.set_album_membership.assert_not_called()

    def test_remove_invalidates_read_replays_and_refreshes_after_mutation(self):
        a=self.select(A); self.deliver(a)
        self.page.members.item(0).setSelected(True)
        self.page._remove_selected(); mutation=self.page.pool.tasks[-1]
        self.assertEqual(self.ids(), [])
        self.deliver(a); self.assertEqual(self.ids(), [])
        self.deliver(mutation)
        self.service.set_album_membership.assert_called_once_with(
            album_uuid=A, content_identity_id=11, present=False, actor='synthetic-owner', reason=None)
        self.deliver(a); self.assertEqual(self.ids(), [])

    def test_add_invalidates_pending_members_and_keeps_captured_album(self):
        a=self.select(A)
        item=QListWidgetItem('Synthetic content'); item.setData(CONTENT_ROLE, 44)
        self.page.content.blockSignals(True)
        self.page.content.addItem(item); item.setSelected(True)
        self.page.content.blockSignals(False)
        self.page._add_selected(); mutation=self.page.pool.tasks[-1]
        self.select(B); self.deliver(a); self.assertEqual(self.ids(), [])
        self.deliver(mutation)
        self.service.set_album_membership.assert_called_once_with(
            album_uuid=A, content_identity_id=44, present=True, actor='synthetic-owner', reason=None)
        self.assertEqual(self.ids(), [])

    def test_actor_confirmation_and_fifty_item_bound_are_preserved(self):
        self.deliver(self.select(A), self.result(A, list(range(1, 56))))
        self.page.members.selectAll()
        self.page.actor.clear(); self.page._remove_selected()
        self.page._confirm.assert_not_called(); self.service.set_album_membership.assert_not_called()
        self.page.actor.setText('synthetic-owner'); self.page._confirm.return_value=False
        self.page._remove_selected(); self.service.set_album_membership.assert_not_called()
        self.page._confirm.return_value=True; self.page._remove_selected()
        self.deliver(self.page.pool.tasks[-1])
        self.assertEqual(self.service.set_album_membership.call_count, 50)
        self.assertEqual([c.kwargs['content_identity_id'] for c in self.service.set_album_membership.call_args_list], list(range(1, 51)))

    def test_preview_binding_rejects_old_album_generation(self):
        self.deliver(self.select(A))
        old=LibraryPreviewBinding(self.page._generation, 'album:'+A, 11, 0, '')
        # Shared content still cannot consume a thumbnail from the old selection.
        self.deliver(self.select(B), self.result(B, [11]))
        image=QImage(2, 2, QImage.Format_RGB32); image.fill(QColor('red'))
        self.page._thumbnail_loaded(old, image, '')
        self.assertTrue(self.page.members.item(0).icon().isNull())
        current=LibraryPreviewBinding(self.page._generation, 'album:'+B, 11, 0, '')
        self.page._thumbnail_loaded(current, image, '')
        self.assertFalse(self.page.members.item(0).icon().isNull())



class AlbumCatalogueIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_real_disposable_memberships_and_append_only_history(self):
        from personal_librarian.catalogue.database import initialise_catalogue, connect_existing_catalogue
        from personal_librarian.desktop.services import DesktopDataService
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); database=root/'catalogue'/'personal_librarian.sqlite3'
            database.parent.mkdir(); initialise_catalogue(database)
            with closing(connect_existing_catalogue(database, read_only=False)) as connection:
                for value in ('synthetic-a', 'synthetic-b'):
                    connection.execute('INSERT INTO content_identities(identity_key) VALUES(?)', (value,))
                connection.commit()
                ids=[row[0] for row in connection.execute('SELECT content_identity_id FROM content_identities ORDER BY content_identity_id')]
            service=DesktopDataService(root)
            albums=[service.create_album(name='Same name', description=None, actor='synthetic-owner', reason='test') for _ in range(2)]
            for album, identity in zip(albums, ids):
                service.set_album_membership(album_uuid=album['album_uuid'], content_identity_id=identity,
                                             present=True, actor='synthetic-owner', reason='test')
            original_history=service.organisation_history()['history']
            page=LibraryPage(service, UiPreferences(last_actor='synthetic-owner'))
            page.pool=CapturingPool(); page._confirm=mock.Mock(return_value=True)
            def select(uuid):
                page.album_rows=service.albums(include_archived=True)['albums']; page._render_albums()
                for row in range(page.albums.rowCount()):
                    if page.albums.item(row, 0).data(ALBUM_ROLE)==uuid:
                        page.albums.selectRow(row); page.pool.tasks[-1].run(); return
                self.fail('Synthetic Album missing')
            try:
                select(albums[0]['album_uuid'])
                self.assertEqual(page.members.item(0).data(CONTENT_ROLE), ids[0])
                page.members.item(0).setSelected(True); page._remove_selected(); page.pool.tasks[-1].run()
                self.assertEqual(service.album_members(albums[0]['album_uuid'])['members'], [])
                self.assertEqual(service.album_members(albums[1]['album_uuid'])['members'][0]['content_identity_id'], ids[1])
                select(albums[0]['album_uuid'])
                item=QListWidgetItem('Synthetic');item.setData(CONTENT_ROLE, ids[0])
                page.content.blockSignals(True);page.content.addItem(item);item.setSelected(True);page.content.blockSignals(False)
                page._add_selected(); page.pool.tasks[-1].run()
                self.assertEqual(service.album_members(albums[0]['album_uuid'])['members'][0]['content_identity_id'], ids[0])
                history=service.organisation_history()['history']
                self.assertEqual(history[2:], original_history)
                self.assertEqual([r['event_type'] for r in history[:2]], ['album_member_restored', 'album_member_removed'])
                self.assertTrue(all(r['actor_identifier']=='synthetic-owner' for r in history[:2]))
                self.assertEqual(page._active_workers, set())
            finally:
                page.close()

if __name__ == '__main__': unittest.main()
