"""Synthetic contract/physical-boundary and truthful provenance regressions."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPOSITORY=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('build_release',REPOSITORY/'packaging/build_release.py')
BUILD_RELEASE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(BUILD_RELEASE)
import build_contract as C

class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.dist=self.root/'dist';self.dist.mkdir()
        self.inputs=self.root/'inputs';self.inputs.mkdir()
        self.expected={}
        for name,data in [('PersonalLibrarian.exe',b'executable'),('_internal/runtime.dll',b'runtime'),('_internal/second.pyd',b'extension')]:
            source=self.inputs/name;source.parent.mkdir(parents=True,exist_ok=True);source.write_bytes(data)
            dest=self.dist/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            self.expected[name]=source
        self.contract=C.contract_from_inputs(self.dist,self.expected,{'validation':'NOT_PERFORMED'})
        self.archive=self.root/'candidate.zip'

    def test_canonical_version_matches_all_metadata(self):
        BUILD_RELEASE.verify_version_metadata(REPOSITORY)

    def test_valid_contract_and_exact_archive(self):
        files=C.distribution_files(self.dist,self.contract)
        self.assertEqual([p.relative_to(self.dist).as_posix() for p in files],sorted(self.expected,key=str.casefold))
        BUILD_RELEASE.create_archive(self.dist,self.contract,self.archive)
        BUILD_RELEASE.verify_archive(self.archive,self.contract)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(archive.namelist(),['PersonalLibrarian/'+x for x in sorted(self.expected,key=str.casefold)])
            for info in archive.infolist():
                self.assertEqual(info.date_time,(1980,1,1,0,0,0))
                self.assertEqual(archive.read(info),self.expected[info.filename.removeprefix('PersonalLibrarian/')].read_bytes())
        original=self.archive.read_bytes()
        with self.assertRaises(FileExistsError): BUILD_RELEASE.create_archive(self.dist,self.contract,self.archive)
        self.assertEqual(self.archive.read_bytes(),original)

    def test_unexpected_private_file_classes_fail_before_archive(self):
        for name in ('photo.jpg','photo.png','inventory.csv','catalogue.db','catalogue.sqlite3','catalogue.sqlite3-wal','catalogue.sqlite3-shm','database.bak','backup.zip','debug.log','.env','credential.pem','secret.key','unfinished.tmp'):
            with self.subTest(name=name):
                added=self.dist/name;added.write_bytes(b'synthetic private sentinel')
                try:
                    with self.assertRaises(ValueError): BUILD_RELEASE.create_archive(self.dist,self.contract,self.archive)
                    self.assertFalse(self.archive.exists())
                    self.assertEqual(added.read_bytes(),b'synthetic private sentinel')
                finally: added.unlink()

    def test_declared_private_artifact_is_not_approved_by_manifest(self):
        source=self.inputs/'inventory.csv';source.write_bytes(b'synthetic')
        (self.dist/'inventory.csv').write_bytes(b'synthetic')
        with self.assertRaises(ValueError):
            C.contract_from_inputs(self.dist,{**self.expected,'inventory.csv':source},{'validation':'NOT_PERFORMED'})

    def test_intervening_archive_is_never_overwritten(self):
        original=BUILD_RELEASE.verify_archive
        def intervene(path,contract):
            original(path,contract)
            self.archive.write_bytes(b'intervening output')
        with patch.object(BUILD_RELEASE,'verify_archive',intervene),self.assertRaises(FileExistsError):
            BUILD_RELEASE.create_archive(self.dist,self.contract,self.archive)
        self.assertEqual(self.archive.read_bytes(),b'intervening output')

    def test_unexpected_empty_directory_rejects(self):
        (self.dist/'backup').mkdir()
        with self.assertRaises(ValueError): C.distribution_files(self.dist,self.contract)

    def test_missing_and_mutated_expected_artifacts_reject(self):
        source=self.dist/'_internal/runtime.dll';source.write_bytes(b'changed')
        with self.assertRaises(ValueError): BUILD_RELEASE.create_archive(self.dist,self.contract,self.archive)
        source.unlink()
        with self.assertRaises(ValueError): BUILD_RELEASE.create_archive(self.dist,self.contract,self.archive)
        self.assertFalse(self.archive.exists())

    def test_input_hash_not_distribution_hash_establishes_contract(self):
        (self.dist/'PersonalLibrarian.exe').write_bytes(b'contaminated before manifest')
        with self.assertRaises(ValueError): C.contract_from_inputs(self.dist,self.expected,{'validation':'NOT_PERFORMED'})

    def test_contract_tampering_and_validation_claim_rejected(self):
        changed=json.loads(json.dumps(self.contract));changed['files']['PersonalLibrarian.exe']['size']+=1
        with self.assertRaises(ValueError): C.validate_contract(changed)
        changed=json.loads(json.dumps(self.contract));changed['provenance']['validation']='PASSED'
        changed['fingerprint']=C.seal({k:v for k,v in changed.items() if k!='fingerprint'})
        with self.assertRaises(ValueError): C.validate_contract(changed)

    def test_path_traversal_and_case_collision_contracts_reject(self):
        for name in ('../outside.dll','/absolute.dll','C:/outside.dll','x\\outside.dll','x/../outside.dll','x/stream:secret','CON','file.','x//y'):
            with self.subTest(name=name),self.assertRaises(ValueError): C.relative_name(name)
        changed=json.loads(json.dumps(self.contract));changed['files']['PERSONALLIBRARIAN.EXE']=changed['files']['PersonalLibrarian.exe']
        changed['fingerprint']=C.seal({k:v for k,v in changed.items() if k!='fingerprint'})
        with self.assertRaises(ValueError): C.validate_contract(changed)

    @unittest.skipUnless(os.name=='nt','Windows junction regression')
    def test_external_directory_junction_and_ancestor_rejected(self):
        external=self.root/'external';external.mkdir();sentinel=external/'secret.txt';sentinel.write_bytes(b'preserve')
        link=self.dist/'external-link'
        subprocess.run(['cmd','/c','mklink','/J',str(link),str(external)],check=True,capture_output=True)
        try:
            with self.assertRaises(ValueError): C.distribution_files(self.dist,self.contract)
            with self.assertRaises(ValueError):
                with C.read_regular(link/'secret.txt'): self.fail('must not read linked data')
            with self.assertRaises(ValueError): BUILD_RELEASE.create_archive(self.dist,self.contract,link/'out.zip')
            self.assertEqual(sentinel.read_bytes(),b'preserve')
            self.assertFalse((external/'out.zip').exists())
        finally: link.rmdir()  # remove only the synthetic junction, never its target

    def test_symlink_and_hardlink_rejected(self):
        source=self.dist/'_internal/runtime.dll';source.unlink()
        outside=self.root/'outside.dll';outside.write_bytes(b'runtime')
        os.link(outside,source)
        with self.assertRaises(ValueError): C.distribution_files(self.dist,self.contract)
        source.unlink()
        try: source.symlink_to(outside)
        except OSError as error:
            # Non-elevated Windows without Developer Mode cannot create symlinks;
            # junction and attribute-based rejection are separately mandatory.
            if getattr(error,'winerror',None)!=1314: raise
            self.skipTest('Windows symlink creation privilege unavailable; junction and hardlink checks ran')
        with self.assertRaises(ValueError): C.distribution_files(self.dist,self.contract)
        self.assertEqual(outside.read_bytes(),b'runtime')

    @unittest.skipUnless(os.name=='nt','Windows native short-name test')
    def test_native_short_name_alias_is_not_an_escape(self):
        import ctypes
        from ctypes import wintypes
        path=self.dist/'PersonalLibrarian.exe'
        function=ctypes.WinDLL('kernel32',use_last_error=True).GetShortPathNameW
        function.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD]
        function.restype=wintypes.DWORD
        buffer=ctypes.create_unicode_buffer(32768)
        self.assertTrue(function(str(path),buffer,len(buffer)))
        if buffer.value.casefold()==str(path).casefold():
            self.skipTest('Native volume has no short-name alias; exact paths remain tested')
        self.assertEqual(C.file_record(Path(buffer.value)),C.file_record(path))

    def test_unknown_reparse_attribute_rejected(self):
        original=Path.lstat
        def fake(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path==self.dist/'PersonalLibrarian.exe':
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=result.st_mode,st_file_attributes=0x400)
            return result
        with patch.object(Path,'lstat',fake),self.assertRaises(ValueError): C.distribution_files(self.dist,self.contract)

    def test_changed_during_archive_and_intervening_output_preserved(self):
        original=BUILD_RELEASE.read_regular;triggered=False
        def change(path):
            nonlocal triggered
            if path.name=='PersonalLibrarian.exe' and not triggered:
                triggered=True;path.write_bytes(b'changed while archiving')
            return original(path)
        with patch.object(BUILD_RELEASE,'read_regular',change),self.assertRaises(ValueError):
            BUILD_RELEASE.create_archive(self.dist,self.contract,self.archive)
        self.assertFalse(self.archive.exists());self.assertFalse(list(self.root.glob('*.tmp')))

    def test_zip_membership_and_hash_tampering_rejected(self):
        BUILD_RELEASE.create_archive(self.dist,self.contract,self.archive)
        with zipfile.ZipFile(self.archive,'a') as archive: archive.writestr('PersonalLibrarian/extra.txt',b'x')
        with self.assertRaises(ValueError): BUILD_RELEASE.verify_archive(self.archive,self.contract)

    def test_zip_exact_names_with_wrong_bytes_rejected(self):
        with zipfile.ZipFile(self.archive,'w') as archive:
            for name,source in sorted(self.expected.items(),key=lambda item:item[0].casefold()):
                data=source.read_bytes()
                if name=='PersonalLibrarian.exe': data=b'x'*len(data)
                archive.writestr('PersonalLibrarian/'+name,data)
        with self.assertRaisesRegex(ValueError,'content mismatch'):
            BUILD_RELEASE.verify_archive(self.archive,self.contract)

    def test_runtime_resource_rules_are_case_equivalent(self):
        allowed = ('PersonalLibrarian.exe', '_internal/runtime.dll',
                   '_internal/base_library.zip', '_internal/PySide6/translations/qt_en.qm',
                   '_internal/PySide6/translations/qtbase_en.qm',
                   '_internal/numpy-2.5.4.dist-info/METADATA')
        for name in allowed:
            for variant in (name, name.upper(), name.swapcase()):
                self.assertEqual(C.require_resource_name(variant), C.require_resource_name(name))
        for name in ('_internal/unapproved.txt', '_internal/unapproved.bin'):
            for variant in (name, name.upper(), name.swapcase()):
                with self.assertRaises(ValueError): C.require_resource_name(variant)

    def test_declared_resource_cannot_self_approve(self):
        for name in ('_internal/unapproved.txt', '_internal/base_library.zip'):
            source = self.inputs / 'unapproved'; source.write_bytes(b'synthetic')
            target = self.dist / name; target.write_bytes(b'synthetic')
            try:
                with self.assertRaises(ValueError):
                    C.contract_from_inputs(self.dist, {**self.expected, name: source}, {'validation':'NOT_PERFORMED'})
            finally: target.unlink()
        # An unapproved name is rejected even with a freshly recomputed seal.
        forged = json.loads(json.dumps(self.contract))
        forged['files']['_internal/unapproved.txt'] = C.file_record(source)
        forged['fingerprint'] = C.seal({k:v for k,v in forged.items() if k!='fingerprint'})
        with self.assertRaises(ValueError): C.validate_contract(forged)
        with self.assertRaises(ValueError): BUILD_RELEASE.create_archive(self.dist, forged, self.archive)
        with self.assertRaises(ValueError): BUILD_RELEASE.verify_archive(self.archive, forged)

    def test_generated_base_library_has_narrow_origin_and_membership(self):
        work = self.root/'work'; work.mkdir(); source = work/'base_library.zip'
        with zipfile.ZipFile(source,'w') as archive: archive.writestr('encodings/__init__.pyc',b'synthetic code')
        name = '_internal/base_library.zip'; (self.dist/name).write_bytes(source.read_bytes())
        contract = C.contract_from_inputs(self.dist, {**self.expected,name:source}, {'validation':'NOT_PERFORMED'}, workpath=work)
        BUILD_RELEASE.create_archive(self.dist,contract,self.archive)
        with zipfile.ZipFile(source,'a') as archive: archive.writestr('unapproved.txt',b'synthetic')
        with self.assertRaises(ValueError): C.verify_resource_origin(name,source,workpath=work)

    def test_runtime_data_requires_matching_dependency_record(self):
        import base64, hashlib
        from types import SimpleNamespace
        name='_internal/PySide6/translations/qt_en.qm';source=self.inputs/'qt_en.qm';source.write_bytes(b'translation')
        class Record:
            hash=SimpleNamespace(mode='sha256',value=base64.urlsafe_b64encode(hashlib.sha256(source.read_bytes()).digest()).decode().rstrip('='))
            def __str__(self): return 'PySide6/translations/qt_en.qm'
        distribution=SimpleNamespace(files=[Record()],locate_file=lambda item:source)
        with patch.object(C.importlib.metadata,'distributions',return_value=[distribution]):
            C.verify_resource_origin(name.swapcase(),source,workpath=None)
            source.write_bytes(b'changed')
            with self.assertRaises(ValueError): C.verify_resource_origin(name,source,workpath=None)
        with patch.object(C.importlib.metadata,'distributions',return_value=[]):
            with self.assertRaises(ValueError): C.verify_resource_origin(name,source,workpath=None)

    def prepare_release(self):
        repository=self.root/'repo';repository.mkdir();(repository/'tmp').mkdir()
        distribution=repository/'tmp'/'dist'
        self.dist.rename(distribution);self.dist=distribution
        return repository,repository/'release'

    def test_incomplete_release_set_never_validates(self):
        repository,output=self.prepare_release()
        for suffix in ('.manifest.json','.sha256','.build-complete.json'):
            # Separate synthetic roots; failed earlier outputs must survive.
            destination=output if suffix=='.manifest.json' else self.root/('repo'+str(len(suffix)))
            if destination!=output:
                destination.mkdir();(destination/'tmp').mkdir()
                import shutil
                dist=destination/'tmp'/'dist';shutil.copytree(self.dist,dist)
                repo=destination;destination=destination/'release'
            else: repo=repository;dist=self.dist
            original=Path.open
            def interrupted(path,*args,**kwargs):
                if path.name.endswith(suffix) and args and args[0]=='x':
                    raise OSError('synthetic publication interruption')
                return original(path,*args,**kwargs)
            with patch.object(BUILD_RELEASE,'verify_version_metadata'),patch.object(BUILD_RELEASE,'verify_provenance'),patch.object(Path,'open',interrupted):
                with self.assertRaises(OSError): BUILD_RELEASE.write_release_files(repo,dist,destination,self.contract)
            self.assertTrue((destination/BUILD_RELEASE.ARCHIVE_NAME).is_file())
            with self.assertRaises((OSError,ValueError)): BUILD_RELEASE.verify_release_files(destination,self.contract)
            before={p.name:p.read_bytes() for p in destination.iterdir()}
            with patch.object(BUILD_RELEASE,'verify_version_metadata'),patch.object(BUILD_RELEASE,'verify_provenance'):
                with self.assertRaises(FileExistsError): BUILD_RELEASE.write_release_files(repo,dist,destination,self.contract)
            self.assertEqual(before,{p.name:p.read_bytes() for p in destination.iterdir()})

    def test_complete_release_set_is_unaccepted_and_hash_bound(self):
        repository,output=self.prepare_release()
        with patch.object(BUILD_RELEASE,'verify_version_metadata'),patch.object(BUILD_RELEASE,'verify_provenance'):
            receipt=BUILD_RELEASE.write_release_files(repository,self.dist,output,self.contract)
        self.assertEqual(receipt['validation']['status'],'NOT_PERFORMED')
        self.assertEqual(BUILD_RELEASE.verify_release_files(output,self.contract),receipt)
        (output/(BUILD_RELEASE.ARCHIVE_NAME+'.sha256')).write_text('changed')
        with self.assertRaises(ValueError): BUILD_RELEASE.verify_release_files(output,self.contract)

    def git(self,*args):
        return subprocess.run(['git',*args],cwd=self.root,check=True,capture_output=True,text=True).stdout.strip()

    def test_clean_dirty_and_wrong_source_provenance(self):
        self.git('init','-q');self.git('config','user.name','Synthetic');self.git('config','user.email','synthetic@example.invalid')
        (self.root/'.gitignore').write_text('dist/\ninputs/\n*.zip\n')
        (self.root/'code.py').write_text('print(1)\n')
        self.git('add','.gitignore','code.py');self.git('commit','-qm','synthetic source')
        clean=BUILD_RELEASE.build_provenance(self.root)
        self.assertEqual(json.loads(json.dumps(clean)),clean)
        self.assertFalse(clean['working_tree_dirty']);self.assertEqual(clean['validation'],'NOT_PERFORMED')
        self.assertEqual(clean['source_tree'],self.git('rev-parse','HEAD^{tree}'))
        BUILD_RELEASE.verify_provenance(self.root,clean)
        (self.root/'code.py').write_text('print(2)\n')
        with self.assertRaises(ValueError): BUILD_RELEASE.build_provenance(self.root)
        dirty=BUILD_RELEASE.build_provenance(self.root,allow_dirty=True)
        self.assertTrue(dirty['working_tree_dirty'])
        self.assertNotEqual(clean['tracked_content_fingerprint'],dirty['tracked_content_fingerprint'])
        with self.assertRaises(ValueError): BUILD_RELEASE.verify_provenance(self.root,clean,allow_dirty=True)
        BUILD_RELEASE.verify_provenance(self.root,dirty,allow_dirty=True)
        dirty['source_commit']='0'*40
        with self.assertRaises(ValueError): BUILD_RELEASE.verify_provenance(self.root,dirty,allow_dirty=True)

if __name__=='__main__': unittest.main()
