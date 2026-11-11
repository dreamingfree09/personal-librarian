"""Render actual widgets offscreen with create-only disposable synthetic data.

This is neither interactive desktop evidence nor packaged application acceptance.
Run from the selected source checkout; PYTHONPATH is not used to select source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path.cwd().resolve()
assert (ROOT/'src/personal_librarian/desktop/main_window.py').is_file()
sys.path[:0] = [str(ROOT/'src'),str(ROOT)]

from PIL import Image, ImageDraw
import PySide6
from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.date_evidence import set_owner_preferred_date
from personal_librarian.desktop.main_window import MainWindow
from personal_librarian.desktop.preferences import PreferenceStore, UiPreferences
from personal_librarian.organisation import create_album, add_content_to_album
from personal_librarian.collections import create_collection, add_content_to_collection
from personal_librarian.production import bootstrap_production
from personal_librarian.desktop.services import DesktopDataService
from tests.test_importers import SyntheticEvidence


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--label',required=True,choices=['before','after'])
    args=parser.parse_args()
    out=args.output.resolve()
    assert out.is_relative_to(ROOT/'tmp'), 'Disposable output must be worktree-local tmp/'
    out.mkdir(parents=True,exist_ok=False)
    fixture=out/'fixture'; fixture.mkdir()
    inputs=fixture/'inputs'; inputs.mkdir()
    evidence=SyntheticEvidence(inputs)
    app_root=fixture/'app-data'
    bootstrap_production(app_data_root=app_root,baselines=evidence.baselines,
        **{k:v for k,v in evidence.kwargs(fixture/'unused').items() if k not in {'database_path','baselines'}})
    service=DesktopDataService(app_root)
    connection=connect_existing_catalogue(service.database_path,read_only=False)
    rows=connection.execute('SELECT physical_instance_id,content_identity_id FROM physical_instances').fetchall()
    images=fixture/'synthetic-images'; images.mkdir()
    for n,row in enumerate(rows):
        path=images/f'demo-landscape-{n+1}.png'
        im=Image.new('RGB',(640,400),(202,223,220)); draw=ImageDraw.Draw(im)
        draw.ellipse((480,30,550,100),fill=(255,247,213))
        draw.polygon([(0,300),(170+n*10,100),(370,290),(640,120),(640,400),(0,400)],fill=(89,133,135))
        draw.polygon([(0,340),(320,270),(640,330),(640,400),(0,400)],fill=(42,86,80)); im.save(path)
        connection.execute('UPDATE physical_instances SET current_observed_path=?,raw_relative_path=?,extension=? WHERE physical_instance_id=?',(str(path),path.name,'.png',row['physical_instance_id']))
    connection.execute("UPDATE sources SET display_name='Synthetic camera'")
    ids=[int(r[0]) for r in connection.execute('SELECT content_identity_id FROM content_identities ORDER BY content_identity_id')]
    connection.commit(); connection.close()
    for i,identity in enumerate(ids[:-1]):
        set_owner_preferred_date(database_path=service.database_path,content_identity_id=identity,
            value='2025' if i<3 else '2024',actor='Synthetic fixture',action_id=f'fixture-date-{i}')
    album=create_album(database_path=service.database_path,name='Coast and mountains',actor='Synthetic fixture')
    collection=create_collection(database_path=service.database_path,name='Favourite places',actor='Synthetic fixture',action_id='fixture-collection')
    for identity in ids[:2]:
        add_content_to_album(database_path=service.database_path,album_uuid=album['album_uuid'],content_identity_id=identity,actor='Synthetic fixture')
        add_content_to_collection(database_path=service.database_path,collection_uuid=collection['collection_uuid'],content_identity_id=identity,actor='Synthetic fixture',action_id=f'fixture-collection-{identity}')
    PreferenceStore(app_root).save(UiPreferences(last_year=2025))
    before=hashlib.sha256(service.database_path.read_bytes()).hexdigest()
    app=QApplication.instance() or QApplication([])
    # The offscreen plugin does not discover installed Windows fonts itself.
    # Register existing fonts for this disposable capture process only.
    for font in ('segoeui.ttf','seguisb.ttf','segoeuib.ttf'):
        font_path=Path(os.environ['WINDIR'])/'Fonts'/font
        assert QFontDatabase.addApplicationFont(str(font_path))>=0
    app.setFont(QFont('Segoe UI',10))
    window=MainWindow(service)
    window.show()

    def settle():
        deadline=time.monotonic()+10
        stable=0
        while time.monotonic()<deadline:
            app.processEvents()
            if QThreadPool.globalInstance().activeThreadCount()==0:
                stable+=1
                if stable>=5: return
            else: stable=0
            time.sleep(.02)
        raise RuntimeError('Synthetic render did not become idle')

    manifest=[]
    def capture(name,w,h):
        window.resize(w,h); settle()
        album_geometry=None
        if window.navigation.currentRow()==1 and window.pages[1].tabs.currentIndex()==0:
            content=window.pages[1].content
            assert content.count()==3, 'Synthetic year selection did not settle'
            assert all(not content.item(i).icon().isNull() for i in range(content.count())), \
                'Synthetic previews unavailable; capture is not complete'
            albums=window.pages[1].albums
            assert albums.rowCount()==1, 'Expected one populated synthetic Album'
            row=albums.visualRect(albums.model().index(0,0))
            viewport=albums.viewport().rect()
            if args.label=='after':
                assert viewport.contains(row), 'First Album row is clipped'
            album_geometry={'row_rect':[row.x(),row.y(),row.width(),row.height()],
                'viewport':[viewport.width(),viewport.height()],
                'table_height':albums.height(),'header_height':albums.horizontalHeader().height(),
                'horizontal_scrollbar_visible':albums.horizontalScrollBar().isVisible(),
                'horizontal_scrollbar_height':albums.horizontalScrollBar().height(),
                'row_fully_contained':viewport.contains(row)}
        shot=window.grab()
        if args.label=='after':
            assert window.width()==w and window.height()==h, (name,window.size(),w,h)
        canvas=QPixmap(shot.width(),shot.height()+42); canvas.fill(QColor('#F5F6F3'))
        painter=QPainter(canvas); painter.drawPixmap(0,42,shot)
        painter.setPen(QColor('#203C3A')); painter.setFont(QFont('Segoe UI',10))
        painter.drawText(12,27,f'D2A {args.label.upper()} | OFFSCREEN QT PROTOTYPE | SYNTHETIC DATA | NOT INTERACTIVE / PACKAGE ACCEPTANCE')
        painter.end()
        target=out/(name+'.png'); assert canvas.save(str(target))
        manifest.append({'file':target.name,'viewport':[w,h],'rendered':[canvas.width(),canvas.height()],
                         'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'label':'OFFSCREEN QT PROTOTYPE - SYNTHETIC DATA',
                         'album_geometry':album_geometry})

    for width,height in ((1280,840),(1040,840),(1920,1080)):
        window.navigation.setCurrentRow(0); settle(); capture(f'{args.label}-overview-{width}',width,height)
        window.navigation.setCurrentRow(1); settle()
        library=window.pages[1]; library.tabs.setCurrentIndex(0); settle()
        capture(f'{args.label}-library-years-{width}',width,height)
    library.tabs.setCurrentIndex(1); settle(); capture(f'{args.label}-collections-1280',1280,840)
    library.tabs.setCurrentIndex(0); settle()
    if library.content.count(): library.content.item(0).setSelected(True)
    settle(); capture(f'{args.label}-selected-content-1280',1280,840)
    window.close(); settle()
    after=hashlib.sha256(service.database_path.read_bytes()).hexdigest()
    assert before==after,'UI capture mutated synthetic catalogue'
    result={'label':args.label,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'source_files':{name:hashlib.sha256((ROOT/'src/personal_librarian/desktop'/name).read_bytes()).hexdigest()
                        for name in ('main_window.py','library_page.py','quiet_archive.py')
                        if (ROOT/'src/personal_librarian/desktop'/name).exists()},
        'python':platform.python_version(),'qt':PySide6.__version__,'platform':'offscreen',
        'pid':os.getpid(),'native_display_scaling':'UNVERIFIED','catalogue_unchanged':before==after,
        'source_data':'generated disposable images only','captures':manifest}
    (out/'capture-manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
