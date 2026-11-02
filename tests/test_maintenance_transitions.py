"""Interrupt after the real rename, before the caller can record completion."""
import json
import os
from pathlib import Path
from unittest import mock

from tests import test_recovery_preservation as recovery_fixtures
from tests.test_production import ProductionTestCase
from personal_librarian import production
from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.maintenance import LEASE_NAME, exclusive_file, file_identity, require_local_ntfs


class RecoveryTransitionTests(ProductionTestCase):
    recover = recovery_fixtures.RecoveryPreservationTests.recover
    crash_wal = recovery_fixtures.RecoveryPreservationTests.crash_wal

    def setUp(self):
        super().setUp()
        self.bootstrap()
        self.layout = production.application_data_layout(self.app_root)
        self.backup = production.create_backup(app_data_root=self.app_root).values

    def assert_safe_or_blocked(self):
        journal = json.loads(next(self.layout.recovery_root.glob('recovery-*.json')).read_text())
        lease = self.layout.catalogue_dir / LEASE_NAME
        restored = True
        for item in journal['original_files']:
            old, saved = Path(item['original']), Path(item['preserved'])
            if (not old.exists() or production._sha256_file(old) != item['sha256']
                    or file_identity(old) != tuple(item['identity'])):
                restored = False
            available = [p for p in (old, saved) if p.exists()
                         and production._sha256_file(p) == item['sha256']
                         and file_identity(p) == tuple(item['identity'])]
            self.assertTrue(available, 'Original evidence lost')
        if not lease.exists():
            self.assertTrue(restored, 'Lease released before complete restoration')
            self.assertEqual(journal['rollback'], 'restored-original-file-set')
        else:
            with self.assertRaises(production.ProductionError):
                connect_existing_catalogue(self.layout.catalogue_path)
        if not restored:
            self.assertNotEqual(journal.get('rollback'), 'restored-original-file-set')

    def interrupt_after_preservation(self, suffix):
        self.crash_wal()
        original = production.publish_no_replace
        hit = False
        def interrupt(source, destination):
            nonlocal hit
            original(source, destination)
            if not hit and Path(source) == Path(f'{self.layout.catalogue_path}{suffix}'):
                hit = True
                raise KeyboardInterrupt('after successful preservation rename')
        with mock.patch.object(production, 'publish_no_replace', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.recover()
        self.assertTrue(hit)
        self.assert_safe_or_blocked()

    def test_after_database_preservation(self):
        self.interrupt_after_preservation('')

    def test_after_wal_preservation(self):
        self.interrupt_after_preservation('-wal')

    def test_after_shm_preservation(self):
        self.interrupt_after_preservation('-shm')

    def test_after_snapshot_publication(self):
        self.crash_wal()
        original = production.publish_no_replace
        def interrupt(source, destination):
            original(source, destination)
            if Path(source).name.startswith('.recovery-'):
                raise KeyboardInterrupt('after successful snapshot publication')
        with mock.patch.object(production, 'publish_no_replace', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.recover()
        self.assert_safe_or_blocked()

    def interrupt_after_rollback(self, suffix):
        self.crash_wal()
        original = production.publish_no_replace
        hit = False
        def interrupt(source, destination):
            nonlocal hit
            if Path(source).name.startswith('.recovery-'):
                raise OSError('force rollback')
            original(source, destination)
            if (not hit and Path(source).name.startswith('pre-recovery-')
                    and Path(destination) == Path(f'{self.layout.catalogue_path}{suffix}')):
                hit = True
                raise KeyboardInterrupt('after successful rollback rename')
        with mock.patch.object(production, 'publish_no_replace', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.recover()
        self.assertTrue(hit)
        self.assert_safe_or_blocked()

    def test_after_rollback_database_rename(self):
        self.interrupt_after_rollback('')

    def test_after_rollback_wal_rename(self):
        self.interrupt_after_rollback('-wal')

    def test_after_rollback_shm_rename(self):
        self.interrupt_after_rollback('-shm')

    def test_failed_restoration_verification_retains_lease(self):
        with mock.patch.object(production, '_verify_promoted_snapshot', side_effect=OSError('force rollback')), mock.patch.object(production, '_verify_original_file_set', side_effect=production.ProductionError('cannot prove original set')):
            with self.assertRaisesRegex(OSError, 'force rollback'):
                self.recover()
        self.assertTrue((self.layout.catalogue_dir / LEASE_NAME).exists())
        journal = json.loads(next(self.layout.recovery_root.glob('recovery-*.json')).read_text())
        self.assertEqual(journal['rollback'], 'offline-recovery-required')
        self.assert_safe_or_blocked()

    def test_same_bytes_intervening_file_is_not_adopted(self):
        data = self.layout.catalogue_path.read_bytes()
        original = production.publish_no_replace
        def intervene(source, destination):
            original(source, destination)
            if Path(source) == self.layout.catalogue_path:
                self.layout.catalogue_path.write_bytes(data)
                raise KeyboardInterrupt('intervening file after rename')
        with mock.patch.object(production, 'publish_no_replace', side_effect=intervene):
            with self.assertRaises(KeyboardInterrupt):
                self.recover()
        self.assertEqual(self.layout.catalogue_path.read_bytes(), data)
        self.assertTrue((self.layout.catalogue_dir / LEASE_NAME).exists())
        journal = json.loads(next(self.layout.recovery_root.glob('recovery-*.json')).read_text())
        self.assertNotEqual(journal.get('rollback'), 'restored-original-file-set')
        self.assert_safe_or_blocked()


class BootstrapTransitionTests(ProductionTestCase):
    def test_after_publication_remains_blocked_until_verification(self):
        layout = production.application_data_layout(self.app_root)
        original = production.publish_no_replace
        def interrupt(source, destination):
            original(source, destination)
            if Path(source).name.startswith('.bootstrap-'):
                raise KeyboardInterrupt('after successful bootstrap publication')
        with mock.patch.object(production, 'publish_no_replace', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.bootstrap()
        self.assertTrue((layout.catalogue_dir / LEASE_NAME).exists())
        self.assertTrue(layout.catalogue_path.exists())
        journal = json.loads(next(layout.recovery_root.glob('bootstrap-*.json')).read_text())
        self.assertEqual(journal['result'], 'failed')
        self.assertEqual(file_identity(layout.catalogue_path), tuple(journal['snapshot_identity']))
        self.assertEqual(production._sha256_file(layout.catalogue_path), journal['snapshot_sha256'])
        with self.assertRaises(production.ProductionError):
            connect_existing_catalogue(layout.catalogue_path)

    def test_windows_identity_survives_rename_and_distinguishes_same_bytes(self):
        require_local_ntfs(self.root)
        first, moved, other = (self.root / name for name in ('first', 'moved', 'other'))
        first.write_bytes(b'synthetic identity test')
        other.write_bytes(first.read_bytes())
        with exclusive_file(first) as stream:
            before = os.fstat(stream.fileno())
            production.publish_no_replace(first, moved)
            after = moved.stat()
            self.assertNotEqual(before.st_ino, 0)
            self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
            self.assertNotEqual((after.st_dev, after.st_ino), (other.stat().st_dev, other.stat().st_ino))

    def test_unc_rejected_before_filesystem_probe(self):
        with mock.patch('personal_librarian.catalogue.maintenance.ctypes.WinDLL') as api:
            with self.assertRaisesRegex(production.ProductionError, 'UNC/network'):
                require_local_ntfs(Path(r'\\synthetic.invalid\share\catalogue'))
            api.assert_not_called()

    def test_public_bootstrap_rejects_unc_before_layout_creation(self):
        with mock.patch.object(production, '_create_layout') as create:
            with self.assertRaisesRegex(production.ProductionError, 'UNC/network'):
                production.bootstrap_production(app_data_root=r'\\synthetic.invalid\share\app')
            create.assert_not_called()

    def test_recovery_rejects_network_manifest_before_read(self):
        self.bootstrap()
        with mock.patch.object(production, '_read_manifest') as read:
            with self.assertRaisesRegex(production.ProductionError, 'UNC/network'):
                production.recover_production(app_data_root=self.app_root,
                    manifest_path=r'\\synthetic.invalid\share\backup.json',
                    actor='test', confirm_restore_catalogue=True)
            read.assert_not_called()

    def test_mapped_remote_and_non_ntfs_are_rejected(self):
        kernel = mock.Mock()
        kernel.GetDriveTypeW.return_value = 4
        with mock.patch('personal_librarian.catalogue.maintenance.ctypes.WinDLL', return_value=kernel):
            with self.assertRaisesRegex(production.ProductionError, 'network/removable/unknown'):
                require_local_ntfs(self.root)
            kernel.GetVolumeInformationW.assert_not_called()
        kernel.GetDriveTypeW.return_value = 3
        def volume(root, label, size, serial, component, flags, filesystem, length):
            filesystem.value = 'ReFS'
            return 1
        kernel.GetVolumeInformationW.side_effect = volume
        with mock.patch('personal_librarian.catalogue.maintenance.ctypes.WinDLL', return_value=kernel):
            with self.assertRaisesRegex(production.ProductionError, 'NTFS only'):
                require_local_ntfs(self.root)
