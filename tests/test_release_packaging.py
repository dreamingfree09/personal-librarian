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
        for name,data in [('PersonalLibrarian.exe',b'executable'),('_internal/runtime.dll',b'runtime'),('_internal/resource.json',b'{}')]:
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
