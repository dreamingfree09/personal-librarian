from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, UTC

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from personal_librarian import production, storage_identity
from tests.test_production import ProductionTestCase


class CurrentReadinessTests(ProductionTestCase):
    def setUp(self):
        super().setUp(); self.bootstrap()
        self.backup_root=self.root/'independent';self.backup_root.mkdir()
        with patch.object(production,'_physical_device_identity',side_effect=('historical-a','historical-b')):
            self.backup=production.create_backup(app_data_root=self.app_root,backup_root=self.backup_root,
                                                backup_class='independent-local').values
        self.manifest=Path(self.backup['manifest_path'])
        self.before=self.manifest.read_bytes()

    def assess(self, source='current-a', backup='current-b', root=None):
        def provider(path):
            return source if Path(path)==production.application_data_layout(self.app_root).catalogue_path else backup
        with patch.object(production,'_physical_device_identity',side_effect=provider) as probe:
            report=production.independent_backup_readiness(app_data_root=self.app_root,
                independent_backup_root=root or self.backup_root).values
        self.assertGreaterEqual(probe.call_count,2)
        self.assertEqual(self.manifest.read_bytes(),self.before)
        return report,probe

    def test_current_independence_is_measured_on_every_evaluation(self):
        for _ in range(2):
            report,probe=self.assess()
            self.assertEqual(report['summary'],'PASS')
            self.assertEqual(probe.call_count,4)
            self.assertEqual(probe.call_args_list[-1].args[0],Path(self.backup['database_path']))
            self.assertEqual(report['current_device_independence'],'confirmed')
            self.assertEqual(report['historical_source_device_identity'],'historical-a')
            self.assertEqual(report['historical_destination_device_identity'],'historical-b')

    def test_same_disk_partitions_cannot_use_historical_independence(self):
        report,_=self.assess('disk-7','disk-7')
        self.assertEqual(report['summary'],'FAIL')
        self.assertEqual(report['current_device_independence'],'same-device')
        self.assertEqual(report['latest_verification'],'ACCEPTED')

    def test_relocated_backup_uses_current_snapshot_location(self):
        relocated=self.root/'relocated';shutil.copytree(self.backup_root,relocated)
        report,probe=self.assess('disk-7','disk-7',relocated)
        self.assertEqual(report['summary'],'FAIL')
        self.assertIn(relocated,probe.call_args_list[-1].args[0].parents)

    def test_swapped_letters_do_not_override_current_physical_ids(self):
        report,_=self.assess('historical-b','historical-a')
        self.assertEqual(report['summary'],'PASS')
        self.assertEqual(report['current_source_device_identity'],'historical-b')

    def test_unknown_unavailable_and_changing_topology_never_pass(self):
        for identities in [(None,'disk-1'),('disk-1',None),(None,None)]:
            with self.subTest(identities=identities):
                report,_=self.assess(*identities)
                self.assertEqual(report['summary'],'WARN')
                self.assertEqual(report['current_device_independence'],'unknown')
        report,_=self.assess(root=self.root/'disconnected')
        self.assertEqual(report['summary'],'WARN');self.assertFalse(report['connected'])
        with patch.object(production,'_physical_device_identity',side_effect=['a','b','c','b']):
            report=production.independent_backup_readiness(app_data_root=self.app_root,independent_backup_root=self.backup_root).values
        self.assertEqual(report['summary'],'WARN');self.assertFalse(report['current_topology_stable'])

    def test_integrity_and_freshness_still_required(self):
        manifest=json.loads(self.before)
        manifest['created_at']=(datetime.now(UTC)-timedelta(days=8)).isoformat()
        self.manifest.write_text(json.dumps(manifest));self.before=self.manifest.read_bytes()
        stale,_=self.assess();self.assertEqual(stale['summary'],'WARN')
        self.assertEqual(stale['current_device_independence'],'confirmed')
        with Path(self.backup['database_path']).open('ab') as stream: stream.write(b'synthetic damage')
        damaged,_=self.assess();self.assertEqual(damaged['summary'],'FAIL')
        self.assertEqual(damaged['valid_independent_backup_count'],0)

    def test_desktop_displays_current_result(self):
        from PySide6.QtWidgets import QApplication
        from personal_librarian.desktop.services import DesktopDataService
        from personal_librarian.desktop.main_window import OverviewPage
        app=QApplication.instance() or QApplication([])
        service=DesktopDataService(self.app_root,independent_backup_root=self.backup_root)
        with patch.object(production,'_physical_device_identity',return_value='same-device'):
            dashboard=service.dashboard()
        self.assertEqual(dashboard['health']['disaster_recovery']['summary'],'FAIL')
        page=OverviewPage(service)
        try:
            page._loaded(dashboard)
            self.assertTrue(page.values['independent_backup'].text().startswith('FAIL'))
        finally: page.close()


class DeviceProviderTests(unittest.TestCase):
    def descriptor(self,bus):
        value=bytearray(36);struct.pack_into('<II',value,0,36,36);struct.pack_into('<I',value,28,bus)
        return bytes(value)

    def test_only_supported_single_disk_topologies(self):
        for bus in (3,7,11,17):
            self.assertTrue(storage_identity._supported_bus(self.descriptor(bus)))
        for bus in (0,1,8,9,10,14,15,16,999):
            self.assertFalse(storage_identity._supported_bus(self.descriptor(bus)))
        self.assertFalse(storage_identity._supported_bus(b'short'))
        self.assertEqual(storage_identity._single_disk(struct.pack('<I4xI4xqq',1,7,0,4096)),7)
        self.assertIsNone(storage_identity._single_disk(struct.pack('<I4xI4xqq',2,7,0,4096)))
        self.assertIsNone(storage_identity._single_disk(b'short'))

    def test_provider_measures_only_the_requested_volume_and_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            extents=struct.pack('<I4xI4xqq',1,7,0,4096)
            with patch.object(storage_identity,'require_local_ntfs'), patch.object(storage_identity,'_query',side_effect=[extents,self.descriptor(11)]) as query:
                self.assertEqual(storage_identity.physical_device_identity(path),'windows-physical-disk:7')
            self.assertEqual(query.call_count,2)
            self.assertEqual(query.call_args_list[1].args[0],r'\\.\PhysicalDrive7')
            self.assertEqual(len(query.call_args_list[1].args[2]),12)
            with patch.object(storage_identity,'require_local_ntfs'), patch.object(storage_identity,'_query',side_effect=OSError('unavailable')):
                self.assertIsNone(storage_identity.physical_device_identity(path))


if __name__=='__main__': unittest.main()
