"""Native Windows recovery failure injection, using disposable synthetic data."""
import hashlib
import json
import os
import shutil
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest import mock

from tests.test_production import ProductionTestCase
from personal_librarian import production
from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.maintenance import LEASE_NAME, exclusive_file


class RecoveryPreservationTests(ProductionTestCase):
    def setUp(self):
        super().setUp()
        self.bootstrap()
        self.layout = production.application_data_layout(self.app_root)
        self.backup = production.create_backup(app_data_root=self.app_root).values

    def recover(self):
        return production.recover_production(app_data_root=self.app_root,
            manifest_path=self.backup['manifest_path'], actor='synthetic-test', confirm_restore_catalogue=True).values

    def crash_wal(self):
        script = """
import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('CREATE TABLE later_marker(value TEXT)')
c.execute("INSERT INTO later_marker VALUES ('after selected backup')")
c.commit()
os._exit(0)
"""
        subprocess.run([sys.executable, '-c', script, str(self.layout.catalogue_path)], check=True, timeout=20)
        self.assertGreater(Path(f'{self.layout.catalogue_path}-wal').stat().st_size, 0)

    def test_crash_wal_is_preserved_and_selected_logical_state_restored(self):
        self.crash_wal()
        wal_hash = hashlib.sha256(Path(f'{self.layout.catalogue_path}-wal').read_bytes()).hexdigest()
        result = self.recover()
        self.assertEqual(result['result'], 'succeeded')
        self.assertEqual(result['selected_logical_sha256'], result['final_logical_sha256'])
        self.assertEqual(production._sha256_file(self.layout.catalogue_path), result['source_hash'])
        saved = Path(result['safeguarded_old_production_path'])
        self.assertEqual(production._sha256_file(Path(f'{saved}-wal')), wal_hash)
        c = sqlite3.connect(self.layout.catalogue_path)
        try:
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='later_marker'").fetchone())
        finally:
            c.close()
        # The preserved tuple still recovers the pre-recovery committed row.
        probe = self.root / 'rollback-proof.sqlite3'
        for suffix in ('', '-wal', '-shm'):
            old = Path(f'{saved}{suffix}')
            if old.exists():
                shutil.copyfile(old, Path(f'{probe}{suffix}'))
        c = sqlite3.connect(probe)
        try:
            self.assertEqual(c.execute('SELECT count(*) FROM later_marker').fetchone()[0], 1)
        finally:
            c.close()

    def test_competing_sqlite_connections_prevent_replacement(self):
        for read_only in (False, True):
            with self.subTest(read_only=read_only):
                c = sqlite3.connect(f'{self.layout.catalogue_path.as_uri()}?mode=ro', uri=True) if read_only else sqlite3.connect(self.layout.catalogue_path)
                try:
                    c.execute('SELECT * FROM catalogue_identity').fetchall()
                    with self.assertRaisesRegex(production.ProductionError, 'Exclusive maintenance'):
                        self.recover()
                    self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                finally:
                    c.close()

    def test_exclusive_handle_prevents_new_sqlite_open(self):
        with exclusive_file(self.layout.catalogue_path):
            with self.assertRaises(sqlite3.OperationalError):
                sqlite3.connect(self.layout.catalogue_path)

    def test_failed_final_verification_rolls_back_wal_and_database(self):
        self.crash_wal()
        expected = {suffix: production._sha256_file(Path(f'{self.layout.catalogue_path}{suffix}')) for suffix in ('', '-wal')}
        original_verify = production._verify_promoted_snapshot
        with mock.patch.object(production, '_verify_promoted_snapshot', side_effect=lambda path, stream, digest: original_verify(path, stream, '0' * 64)):
            with self.assertRaisesRegex(production.ProductionError, 'differs from the selected snapshot'):
                self.recover()
        for suffix, digest in expected.items():
            self.assertEqual(production._sha256_file(Path(f'{self.layout.catalogue_path}{suffix}')), digest)
        journal = json.loads(next(self.layout.recovery_root.glob('recovery-*.json')).read_text())
        self.assertEqual(journal['result'], 'failed')
        self.assertEqual(journal['rollback'], 'restored-original-file-set')
        self.assertEqual(len(list(self.layout.catalogue_dir.glob('failed-recovery-*.sqlite3'))), 1)

    def test_repeated_recovery_retains_selected_logical_state(self):
        first, second = self.recover(), self.recover()
        self.assertEqual(first['final_snapshot_sha256'], second['final_snapshot_sha256'])
        self.assertEqual(first['final_logical_sha256'], second['final_logical_sha256'])
        self.assertNotEqual(first['journal_path'], second['journal_path'])

    def test_interrupt_after_first_preserved_file_rolls_back(self):
        self.crash_wal()
        original = production.publish_no_replace

        def interrupt(source, destination):
            if str(source).endswith('-wal'):
                raise KeyboardInterrupt('synthetic interrupted sidecar move')
            original(source, destination)

        with mock.patch.object(production, 'publish_no_replace', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.recover()
        c = sqlite3.connect(self.layout.catalogue_path)
        try:
            self.assertEqual(c.execute('SELECT count(*) FROM later_marker').fetchone()[0], 1)
        finally:
            c.close()

    def test_abandoned_lease_blocks_catalogue_api(self):
        lease = self.layout.catalogue_dir / LEASE_NAME
        lease.write_text('{"operation":"interrupted recovery"}')
        for read_only in (True, False):
            with self.assertRaisesRegex(production.ProductionError, 'offline review'):
                connect_existing_catalogue(self.layout.catalogue_path, read_only=read_only)
        with self.assertRaisesRegex(production.ProductionError, 'lease already exists'):
            self.recover()

    def test_process_termination_retains_recoverable_tuple_and_blocks_reopen(self):
        self.crash_wal()
        script = """
import os, sys
from pathlib import Path
sys.path.insert(0, 'src')
from personal_librarian import production
original = production.publish_no_replace
def terminate(source, destination):
    original(source, destination)
    if Path(source).name == production.CATALOGUE_FILENAME:
        os._exit(73)
production.publish_no_replace = terminate
production.recover_production(app_data_root=sys.argv[1], manifest_path=sys.argv[2], actor='synthetic-crash', confirm_restore_catalogue=True)
"""
        result = subprocess.run([sys.executable, '-c', script, str(self.app_root), self.backup['manifest_path']], timeout=30)
        self.assertEqual(result.returncode, 73)
        self.assertTrue((self.layout.catalogue_dir / LEASE_NAME).exists())
        with self.assertRaises(production.ProductionError):
            connect_existing_catalogue(self.layout.catalogue_path)
        journal = json.loads(next(self.layout.recovery_root.glob('recovery-*.json')).read_text())
        self.assertEqual(journal['result'], 'started')
        # A new disposable location demonstrates offline rollback without
        # deleting the abandoned lease or changing original evidence.
        restored = self.root / 'offline-rollback.sqlite3'
        for entry in journal['original_files']:
            old, saved = Path(entry['original']), Path(entry['preserved'])
            available = saved if saved.exists() else old
            self.assertEqual(production._sha256_file(available), entry['sha256'])
            suffix = str(old)[len(str(self.layout.catalogue_path)):]
            shutil.copyfile(available, Path(f'{restored}{suffix}'))
        c = sqlite3.connect(restored)
        try:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(c.execute('SELECT count(*) FROM later_marker').fetchone()[0], 1)
        finally:
            c.close()

    def test_rollback_collision_preserves_intervening_file_and_retains_lease(self):
        original = production.publish_no_replace
        def collide(source, destination):
            if Path(source).name.startswith('.recovery-'):
                Path(destination).write_bytes(b'intervening unrelated file')
                raise OSError('synthetic publication collision')
            original(source, destination)
        with mock.patch.object(production, 'publish_no_replace', side_effect=collide):
            with self.assertRaisesRegex(OSError, 'publication collision'):
                self.recover()
        self.assertEqual(self.layout.catalogue_path.read_bytes(), b'intervening unrelated file')
        self.assertTrue((self.layout.catalogue_dir / LEASE_NAME).exists())
        journal = json.loads(next(self.layout.recovery_root.glob('recovery-*.json')).read_text())
        self.assertEqual(journal['result'], 'failed')
        self.assertEqual(journal['rollback'], 'offline-recovery-required')
        self.assertTrue(Path(journal['safeguarded_old_production_path']).is_file())
