from __future__ import annotations
import concurrent.futures
import ctypes
from ctypes import wintypes as W
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PIL import Image
from personal_librarian.desktop.preferences import PreferenceStore, UiPreferences
from personal_librarian.desktop.thumbnails import ThumbnailService, ThumbnailTask
from personal_librarian.desktop import state_files


@unittest.skipUnless(os.name=='nt','Windows handle contract')
class StateContainmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.app=self.root/'app'; self.app.mkdir()
        self.outside=self.root/'outside'; self.outside.mkdir()
        self.source=self.root/'synthetic.jpg'
        Image.new('RGB',(24,24),'blue').save(self.source)

    def junction(self, link, target):
        subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],check=True,capture_output=True)

    def test_redirected_root_and_state_ancestors_reject(self):
        for placement in ('root','state','cache'):
            with self.subTest(placement=placement):
                app=self.root/placement
                if placement=='root': self.junction(app,self.outside)
                else:
                    app.mkdir()
                    if placement=='state': self.junction(app/'state',self.outside)
                    else:
                        (app/'state').mkdir();self.junction(app/'state'/'thumbnails',self.outside)
                result=ThumbnailService(app).load(self.source,content_identity=1)
                self.assertIsNotNone(result.error)
                self.assertEqual(list(self.outside.iterdir()),[])
                if placement!='cache':
                    store=PreferenceStore(app)
                    self.assertEqual(store.load(),UiPreferences())
                    with self.assertRaises(OSError): store.save(UiPreferences(last_actor='synthetic'))
                    self.assertEqual(list(self.outside.iterdir()),[])

    def test_preference_file_links_neither_read_nor_write_external_content(self):
        (self.app/'state').mkdir()
        external=self.outside/'sentinel.json'
        data=b'{"version":1,"last_actor":"external-sentinel"}'
        external.write_bytes(data)
        store=PreferenceStore(self.app)
        for hard in (False,True):
            with self.subTest(hard=hard):
                if hard: os.link(external,store.path)
                else: os.symlink(external,store.path)
                self.assertEqual(store.load().last_actor,'')
                with self.assertRaises(OSError): store.save(UiPreferences(last_actor='changed'))
                self.assertEqual(external.read_bytes(),data)
                store.path.unlink()

    def test_linked_cache_is_not_read(self):
        service=ThumbnailService(self.app)
        key=service.cache_key(1)
        cached=service.cache_root/key[:2]/(key+'.png')
        cached.parent.mkdir(parents=True)
        external=self.outside/'sentinel.png'
        Image.new('RGB',(4,4),'red').save(external)
        before=external.read_bytes()
        os.symlink(external,cached)
        with patch.object(Image,'open',side_effect=AssertionError('must reject before decode')):
            result=service.load(self.source,content_identity=1)
        self.assertIsNotNone(result.error)
        self.assertEqual(external.read_bytes(),before)

    def test_valid_preferences_and_malformed_recovery(self):
        store=PreferenceStore(self.app)
        store.save(UiPreferences(last_actor='first'))
        store.save(UiPreferences(last_actor='second'))
        self.assertEqual(store.load().last_actor,'second')
        store.path.write_bytes(b'{broken')
        self.assertEqual(store.load(),UiPreferences())
        store.save(UiPreferences(last_actor='recovered'))
        self.assertEqual(store.load().last_actor,'recovered')
        self.assertEqual(list(store.path.parent.glob('*.tmp')),[])

    def test_concurrent_cache_generation_has_one_complete_winner(self):
        service=ThumbnailService(self.app)
        before=self.source.read_bytes()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:service.load(self.source,content_identity=1),range(24)))
        self.assertTrue(all(r.error is None for r in results),[r.error for r in results])
        self.assertEqual(len({r.cache_path for r in results}),1)
        self.assertEqual(len({r.image_bytes for r in results}),1)
        self.assertEqual(len(list(service.cache_root.rglob('*.png'))),1)
        self.assertEqual(self.source.read_bytes(),before)

    def test_interrupted_publication_never_accepts_partial_cache(self):
        service=ThumbnailService(self.app)
        with patch.object(state_files,'_rename',side_effect=OSError('synthetic interruption')):
            result=service.load(self.source,content_identity=1)
        self.assertIsNotNone(result.error)
        self.assertFalse(list(service.cache_root.rglob('*.png')))
        self.assertIsNone(service.load(self.source,content_identity=1).error)
        key=service.cache_key(2);path=service.cache_root/key[:2]/(key+'.png')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'partial')
        self.assertIsNotNone(service.load(self.source,content_identity=2).error)

    def test_successful_rename_then_interruption_preserves_complete_object(self):
        service=ThumbnailService(self.app)
        original=state_files._rename
        def interrupted(*args):
            original(*args)
            raise OSError('interrupted after rename')
        with patch.object(state_files,'_rename',interrupted):
            result=service.load(self.source,content_identity=1)
        self.assertIsNotNone(result.error)
        self.assertEqual(len(list(service.cache_root.rglob('*.png'))),1)
        self.assertIsNone(service.load(self.source,content_identity=1).error)

    def test_held_ancestor_cannot_be_relocated_during_publication(self):
        service=ThumbnailService(self.app)
        original=state_files._rename
        attempts=[]
        def attempt(*args):
            with self.assertRaises(OSError):
                (self.app/'state').rename(self.root/'relocated')
            attempts.append(True)
            return original(*args)
        with patch.object(state_files,'_rename',attempt):
            result=service.load(self.source,content_identity=1)
        self.assertIsNone(result.error,result.error)
        self.assertEqual(attempts,[True])
        self.assertFalse((self.root/'relocated').exists())

    def test_task_uses_verified_bytes_not_a_later_path_reopen(self):
        service=ThumbnailService(self.app)
        service.load(self.source,content_identity=1)
        task=ThumbnailTask(service,str(self.source),1,'token')
        seen=[]
        task.signals.loaded.connect(lambda token,image,error:seen.append((image.isNull(),error)))
        with patch('PySide6.QtGui.QImage.load',side_effect=AssertionError('path reopen')):
            task.run()
        self.assertEqual(seen,[(False,'')])

    def test_directory_write_handle_is_denied_while_pinned(self):
        service=ThumbnailService(self.app)
        original=state_files._rename
        def attempt(k,*args):
            with self.assertRaises(OSError):
                state_files._open(k,self.app/'state',0x40000000,7,3,directory=True)
            return original(k,*args)
        with patch.object(state_files,'_rename',attempt):
            result=service.load(self.source,content_identity=1)
        self.assertIsNone(result.error,result.error)

    def test_redirected_ancestor_above_approved_root_rejects(self):
        link=self.root/'ancestor'
        self.junction(link,self.outside)
        service=ThumbnailService(link/'app')
        self.assertIsNotNone(service.load(self.source,content_identity=1).error)
        self.assertEqual(list(self.outside.iterdir()),[])

    def test_publication_parent_cannot_be_retagged_as_junction(self):
        service=ThumbnailService(self.app)
        original=state_files._rename
        target=('\\??\\'+str(self.outside)).encode('utf-16-le')
        import struct
        names=target+b'\0\0'+str(self.outside).encode('utf-16-le')+b'\0\0'
        payload=struct.pack('<IHHHHHH',0xA0000003,8+len(names),0,0,len(target),len(target)+2,len(names)-len(target)-4)+names
        calls=[]
        def attempt(k,handle,name,replace,parent):
            key=service.cache_key(1)
            directory=service.cache_root/key[:2]
            writer=state_files._open(k,directory,0x40000000,7,3,directory=True)
            try:
                ioctl=k.DeviceIoControl
                ioctl.argtypes=[W.HANDLE,W.DWORD,W.LPVOID,W.DWORD,W.LPVOID,W.DWORD,ctypes.POINTER(W.DWORD),W.LPVOID]
                ioctl.restype=W.BOOL
                returned=W.DWORD();buffer=ctypes.create_string_buffer(payload)
                self.assertFalse(ioctl(writer,0x900A4,buffer,len(payload),None,0,ctypes.byref(returned),None))
                self.assertEqual(ctypes.get_last_error(),145) # ERROR_DIR_NOT_EMPTY
                calls.append(True)
            finally:
                k.CloseHandle(writer)
            return original(k,handle,name,replace,parent)
        with patch.object(state_files,'_rename',attempt):
            result=service.load(self.source,content_identity=1)
        self.assertIsNone(result.error,result.error)
        self.assertEqual(calls,[True])
        self.assertEqual(list(self.outside.iterdir()),[])


if __name__=='__main__': unittest.main()
