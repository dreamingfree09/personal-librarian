"""D2A presentation checks over disposable catalogues and real Qt widgets."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time
import threading
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAccessible, QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton

from personal_librarian.desktop.library_page import CONTENT_ROLE, LibraryPage
from personal_librarian.desktop.main_window import MainWindow, OverviewPage
from personal_librarian.desktop.preferences import UiPreferences
from tests.test_desktop_m30 import DesktopM30Case


class QuietArchiveTests(DesktopM30Case):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if sys.platform=='win32':
            for name in ('segoeui.ttf','seguisb.ttf','segoeuib.ttf'):
                assert QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR'])/'Fonts'/name))>=0

    def page(self):
        page = LibraryPage(self.service, UiPreferences())
        self.addCleanup(page.close)
        page.run_async = lambda operation, completed: completed(operation())
        page.refresh()
        return page

    def report(self):
        return {'health': {'summary':'WARN','catalogue_uuid':'synthetic-catalogue',
                'schema_version':10,'file_size_bytes':4096,'backup_count':0,
                'recovery_required_executions':0},
                'counts':{'physical_instances':6,'content_identities':5,'exact_duplicate_groups':0,
                          'similarity_groups':0,'decision_events':0,'action_plans':0,'quarantine_records':0},
                'decision_writes_enabled':True,
                'year_shelves':self.service.browse_years(),
                'preferred_counts':self.service.preferred_counts()}

    def test_overview_values_distinguish_identity_copies_dates_and_independent_readiness(self):
        page = OverviewPage(self.service)
        self.addCleanup(page.close)
        page._loaded(self.report())
        self.assertEqual(page.values['content_identities'].text(), '5')
        self.assertEqual(page.values['physical_instances'].text(), '6')
        self.assertEqual(page.values['needs_review'].text(), '1')
        self.assertIn('0 accepted', page.values['operational_backup'].text())
        self.assertIn('NOT ASSESSED', page.values['independent_backup'].text())
        self.assertNotIn('verified', page.values['operational_backup'].text().lower())
        self.assertFalse(page.catalogue_details.isVisible())
        page._show_details(True)
        self.assertFalse(page.catalogue_details.isHidden())

    def test_overview_refresh_and_failure_clear_previous_counts_and_actions(self):
        page = OverviewPage(self.service)
        self.addCleanup(page.close)
        page._loaded(self.report())
        page.run_async = mock.Mock()
        page.refresh()
        self.assertEqual(page.values['content_identities'].text(), 'Not yet assessed')
        self.assertFalse(page.browse_button.isEnabled())
        page._failed('Synthetic unavailable state')
        self.assertFalse(page.dates_button.isEnabled())
        self.assertIn('Nothing was created',page.message.text())

    def test_overview_out_of_order_success_and_error_cannot_replace_current_state(self):
        page = OverviewPage(self.service)
        self.addCleanup(page.close)
        callbacks = []
        page.run_async = lambda op, done: callbacks.append(done)
        page.refresh(); page.refresh()
        callbacks[1]((2,self.report(),None))
        stale = self.report(); stale['counts']['content_identities']=999
        callbacks[0]((1,stale,None)); callbacks[0]((1,None,'obsolete failure'))
        self.assertEqual(page.values['content_identities'].text(),'5')
        self.assertTrue(page.browse_button.isEnabled())

    def test_real_overview_worker_delivers_to_bound_receiver_and_finishes(self):
        page=OverviewPage(self.service)
        self.addCleanup(page.close)
        with mock.patch.object(page,'_snapshot',return_value=self.report()):
            page.refresh()
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and not page.browse_button.isEnabled():
                self.application.processEvents()
                time.sleep(.01)
            self.assertTrue(page.browse_button.isEnabled())
            self.assertEqual(page.values['content_identities'].text(),'5')
            self.assertTrue(page.pool.waitForDone(5000))

    def test_pending_catalogue_read_does_not_block_event_loop(self):
        page=OverviewPage(self.service)
        self.addCleanup(page.close)
        entered, release=threading.Event(),threading.Event()
        ticks=[]
        def bounded_read():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Synthetic read timed out')
            return self.report()
        with mock.patch.object(page,'_snapshot',side_effect=bounded_read):
            try:
                page.refresh()
                self.assertTrue(entered.wait(2))
                QTimer.singleShot(0,lambda:ticks.append('responsive'))
                self.application.processEvents()
                self.assertEqual(ticks,['responsive'])
                self.assertFalse(page.browse_button.isEnabled())
            finally:
                release.set()
                self.assertTrue(page.pool.waitForDone(5000))
                self.application.processEvents()

    def test_schema_nine_does_not_call_preferred_date_service(self):
        service = mock.Mock()
        report = self.report(); report['health']['schema_version']=9
        report.pop('preferred_counts')
        service.dashboard.return_value=report
        service.browse_years.return_value={'years':[]}
        page = OverviewPage(service)
        self.addCleanup(page.close)
        page._loaded(page._snapshot())
        service.preferred_counts.assert_not_called()
        self.assertFalse(page.dates_button.isEnabled())
        self.assertIn('Unavailable',page.values['needs_review'].text())

    def test_collections_hide_year_shelf_without_losing_selection_or_identity(self):
        page=self.page()
        page.resize(1020,760); page.show(); self.application.processEvents()
        page.years.setCurrentRow(1)
        selected=page.current_year
        self.assertEqual([page.tabs.tabText(i) for i in range(4)],['Years','Collections','Tags','History'])
        page.tabs.setCurrentIndex(1); self.application.processEvents()
        self.assertFalse(page.years.isVisible())
        self.assertIn('does not filter',page.collection_availability.text())
        page.tabs.setCurrentIndex(0); self.application.processEvents()
        self.assertTrue(page.years.isVisible())
        self.assertEqual(page.current_year,selected)
        self.assertEqual(page.years.currentItem().data(CONTENT_ROLE),selected)

    def test_needs_review_unknown_only_and_year_precision_stay_distinct(self):
        page=self.page()
        page.date_filter.setCurrentIndex(1)
        self.assertEqual(page.content.count(),1)
        self.assertEqual(page.content.item(0).data(CONTENT_ROLE),self.content_ids[2])
        page.date_filter.setCurrentIndex(2)
        self.assertEqual(page.content.count(),2)
        self.assertNotIn(self.content_ids[2],[page.content.item(i).data(CONTENT_ROLE) for i in range(page.content.count())])
        page.date_filter.setCurrentIndex(0)
        for i in range(page.years.count()):
            if page.years.item(i).data(CONTENT_ROLE)==2019:
                page.years.setCurrentRow(i)
        self.assertIn('2019',page.content.item(0).text())
        self.assertNotIn('2019-01-01',page.content.item(0).text())

    def test_focus_accessible_names_and_long_plain_evidence(self):
        page=self.page(); page.resize(1020,760); page.show()
        page.actor.setFocus(); self.application.processEvents()
        self.assertTrue(page.actor.hasFocus())
        QTest.keyClick(page.actor,Qt.Key_Tab)
        self.assertTrue(page.reason.hasFocus())
        interface=QAccessible.queryAccessibleInterface(page.actor)
        self.assertIn('Owner',interface.text(QAccessible.Name))
        self.assertIn('Collections',page.collection_table.accessibleName())
        value='<b>synthetic literal evidence</b> '+('Long evidence ' * 60)
        page.content_detail.setText(value)
        self.assertEqual(page.content_detail.textFormat(),Qt.PlainText)
        self.assertTrue(page.content_detail.wordWrap())
        self.assertEqual(page.content_detail.text(),value)
        for _ in range(5):
            self.application.processEvents()
        self.assertGreaterEqual(page.content_detail.height(),
                                page.content_detail.heightForWidth(page.content_detail.width()))
        scroll=page.content_detail_scroll.verticalScrollBar()
        self.assertGreater(scroll.maximum(),0)
        scroll.setValue(scroll.maximum())
        self.assertEqual(scroll.value(),scroll.maximum())

    def test_control_rows_remain_horizontally_reachable_at_three_sizes(self):
        page=self.page()
        for width,height in ((790,720),(1030,720),(1670,960)):
            page.resize(width,height); page.show(); self.application.processEvents()
            for index in range(4):
                page.tabs.setCurrentIndex(index); self.application.processEvents()
                tab=page.tabs.currentWidget().widget()
                for button in tab.findChildren(QPushButton):
                    if button.isVisible():
                        point=button.mapTo(tab,QPoint(0,0))
                        self.assertGreaterEqual(point.x(),0,button.text())
                        self.assertLessEqual(point.x()+button.width(),tab.width()+2,(width,index,button.text(),tab.width()))
                        self.assertGreaterEqual(button.width(),button.minimumSizeHint().width()-2,button.text())

    def test_empty_and_no_selection_do_not_fabricate_content(self):
        page=self.page()
        page.years.clearSelection()
        self.assertFalse(page.has_year_selection)
        self.assertFalse(page.remove_button.isEnabled())
        page._year_loaded(({'content':[],'total_matching':0,'unorganised_only':False},{'albums':[]},{'albums':[]}))
        self.assertEqual(page.content.count(),0)
        self.assertFalse(page.next.isEnabled())
        self.assertIn('0',page.content_message.text())

    def test_overview_actions_use_existing_navigation_and_date_filter(self):
        with mock.patch('personal_librarian.desktop.main_window.AsyncPage.run_async'), mock.patch.object(LibraryPage,'run_async'):
            window=MainWindow(self.service)
        self.addCleanup(window.close)
        overview=window.pages[0]; library=window.pages[1]
        library.refresh=mock.Mock()
        library._reload_year=mock.Mock()
        overview._loaded(self.report())
        overview.browse_button.click()
        self.assertEqual(window.navigation.currentRow(),1)
        self.assertEqual(library.tabs.currentIndex(),0)
        overview.dates_button.click()
        self.assertEqual(library.date_filter.currentIndex(),1)
        with mock.patch.object(window.pages[7],'refresh'):
            overview.backups_button.click()
        self.assertEqual(window.navigation.currentRow(),7)
        self.assertEqual(tuple(window.navigation.item(i).text() for i in range(8)),MainWindow.SECTION_NAMES)

    def test_real_shell_uses_requested_viewports_without_hidden_page_minimums(self):
        with mock.patch('personal_librarian.desktop.main_window.AsyncPage.run_async'), mock.patch.object(LibraryPage,'run_async'):
            window=MainWindow(self.service)
            self.addCleanup(window.close)
            window.show()
            for section in (0,1):
                window.navigation.setCurrentRow(section)
                for width,height in ((1040,840),(1280,840),(1920,1080)):
                    window.resize(width,height)
                    self.application.processEvents()
                    self.assertEqual((window.width(),window.height()),(width,height))
                    self.assertEqual(window.stack.currentIndex(),section)
