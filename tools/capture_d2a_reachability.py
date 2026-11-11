"""Create-only offscreen reachability evidence using disposable synthetic Qt fixtures."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

os.environ['QT_QPA_PLATFORM']='offscreen'
ROOT=Path.cwd().resolve()
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from tests.test_desktop_quiet_archive import QuietArchiveTests
from personal_librarian.desktop.main_window import MainWindow
from personal_librarian.desktop.library_page import LibraryPage, CONTENT_ROLE
from personal_librarian.organisation import create_album, add_content_to_album


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve()
    assert out.is_relative_to(ROOT/'tmp')
    out.mkdir(parents=True,exist_ok=False)
    QuietArchiveTests.setUpClass()
    case=QuietArchiveTests('test_empty_album_table_keeps_header_and_no_selection')
    case.setUp()
    app=case.application
    app.setFont(QFont('Segoe UI',10))
    album=create_album(database_path=case.database,name='Synthetic reachability album',actor='Fixture')
    add_content_to_album(database_path=case.database,album_uuid=album['album_uuid'],content_identity_id=case.content_ids[0],actor='Fixture')
    before=hashlib.sha256(case.database.read_bytes()).hexdigest()
    window=None
    try:
        with mock.patch('personal_librarian.desktop.main_window.AsyncPage.run_async'),mock.patch.object(LibraryPage,'run_async'):
            window=MainWindow(case.service)
        page=window.pages[1]
        page.run_async=lambda operation,completed:completed(operation())
        window.navigation.setCurrentRow(1)
        for row in range(page.years.count()):
            if page.years.item(row).data(CONTENT_ROLE)==2019: page.years.setCurrentRow(row)
        window.show()
        page.albums.selectRow(0)
        page.content.setCurrentRow(0)  # Synthetic read-only selection precondition.
        outer=page.tabs.widget(0)
        clicks=QSignalSpy(page.remove_button.clicked)
        def settle():
            for _ in range(8): app.processEvents()
        def wheel(delta):
            bar=outer.verticalScrollBar();point=bar.rect().center()
            app.sendEvent(bar,QWheelEvent(QPointF(point),QPointF(bar.mapToGlobal(point)),QPoint(),QPoint(0,delta),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False))
            settle()
        def rect(widget,target):
            r=widget.rect().translated(target.mapFromGlobal(widget.mapToGlobal(QPoint())))
            return [r.x(),r.y(),r.width(),r.height()]
        def state():
            button=page.remove_button
            box=button.rect().translated(button.mapTo(outer.viewport(),QPoint()))
            return {'button_rect':rect(button,outer.viewport()),'viewport_rect':rect(outer.viewport(),outer.viewport()),
                    'scrollbar_rect':rect(outer.verticalScrollBar(),outer.viewport()),
                    'scroll_value':outer.verticalScrollBar().value(),'scroll_maximum':outer.verticalScrollBar().maximum(),
                    'fully_visible':outer.viewport().rect().contains(box) and button.visibleRegion().contains(button.rect()),
                    'button_focused':button.hasFocus(),'button_enabled':button.isEnabled(),
                    'content_split_rect':rect(page.content_split,outer.viewport()),
                    'detail_rect':rect(button.parentWidget(),outer.viewport()),
                    'evidence_rect':rect(page.content_detail_scroll,outer.viewport()),
                    'members_rect':rect(page.members,outer.viewport())}
        results=[]
        for width,height in ((1040,840),(1280,840),(1920,1080)):
            window.resize(width,height);settle()
            QTest.keyClick(outer.verticalScrollBar(),Qt.Key_Home);settle()
            initial=state()
            # Only read-only selection. Missing thumbnails are deliberately synthetic.
            row=page.albums.visualRect(page.albums.model().index(0,0))
            assert page.albums.viewport().rect().contains(row)
            for count in range(30):
                wheel(-120)
                if outer.verticalScrollBar().value()==outer.verticalScrollBar().maximum(): break
            after_wheel=state()
            assert after_wheel['fully_visible']
            member=page.members.visualItemRect(page.members.item(0)).intersected(page.members.viewport().rect())
            assert not member.isEmpty()
            assert outer.viewport().rect().contains(page.members.viewport().mapTo(outer.viewport(),member.center()))
            QTest.mouseClick(page.members.viewport(),Qt.LeftButton,pos=member.center());settle()
            assert app.focusWidget() is page.members
            wheel(120)
            before_tab=state()
            QTest.keyClick(page.members,Qt.Key_Tab);settle()
            after_tab=state()
            assert after_tab['fully_visible'] and after_tab['button_focused']
            assert clicks.count()==0
            assert hashlib.sha256(case.database.read_bytes()).hexdigest()==before
            raw=out/f'reachability-{width}x{height}-raw.png'
            assert window.grab().save(str(raw))
            with Image.open(raw) as image:
                labelled=Image.new('RGB',(image.width,image.height+48),'#F5F6F3')
                labelled.paste(image,(0,48))
                ImageDraw.Draw(labelled).text((12,17),f'D2A-V02 | OFFSCREEN QT | SYNTHETIC DATA | {width} x {height} | WHEEL + TAB, NO ACTION',fill='#203C3A')
                labelled.save(out/f'reachability-{width}x{height}.png')
            results.append({'window':[width,height],'initial':initial,'wheel_notches':count+1,'after_wheel':after_wheel,
                            'before_tab':before_tab,'after_tab':after_tab,'album_row':[row.x(),row.y(),row.width(),row.height()],
                            'album_viewport_height':page.albums.viewport().height(),'clicks':clicks.count(),'catalogue_unchanged':True})
        report={'source_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                'source_blob_sha256':hashlib.sha256((ROOT/'src/personal_librarian/desktop/library_page.py').read_bytes()).hexdigest(),
                'acceptance':'Offscreen Qt synthetic widget evidence; not interactive packaged application acceptance',
                'results':results,'action_activations':clicks.count(),'catalogue_unchanged':True,'actor_empty':page.actor.text()=='',
                'synthetic_catalogue_sha256':before}
        (out/'geometry.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report))
    finally:
        if window is not None:
            with mock.patch.object(window.preference_store,'save'): window.close()
            app.processEvents()
        case.doCleanups()

if __name__=='__main__': main()
