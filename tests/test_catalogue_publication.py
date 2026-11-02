"""Synthetic publication races; no owner catalogue is used."""
from pathlib import Path
import json
import subprocess
import sys
from unittest import mock

from tests.test_production import ProductionTestCase
from personal_librarian import production


class BootstrapPublicationTests(ProductionTestCase):
    def test_orphan_destination_wal_is_preserved_and_not_adopted(self):
        layout = production.application_data_layout(self.app_root)
        layout.catalogue_dir.mkdir(parents=True)
        wal = Path(f'{layout.catalogue_path}-wal')
        wal.write_bytes(b'unowned sidecar evidence')
        with self.assertRaisesRegex(production.ProductionError, 'sidecars'):
            self.bootstrap()
        self.assertFalse(layout.catalogue_path.exists())
        self.assertEqual(wal.read_bytes(), b'unowned sidecar evidence')
        self.assertEqual(len(list(layout.catalogue_dir.glob('.bootstrap-*.sqlite3'))), 1)

    def test_sidecar_appearing_at_publication_withdraws_only_own_database(self):
        layout = production.application_data_layout(self.app_root)
        original = production.publish_no_replace
        def introduce_sidecar(source, destination):
            original(source, destination)
            if Path(destination) == layout.catalogue_path:
                Path(f'{destination}-wal').write_bytes(b'intervening sidecar')
        with mock.patch.object(production, 'publish_no_replace', side_effect=introduce_sidecar):
            with self.assertRaisesRegex(production.ProductionError, 'sidecars appeared'):
                self.bootstrap()
        self.assertFalse(layout.catalogue_path.exists())
        self.assertEqual(Path(f'{layout.catalogue_path}-wal').read_bytes(), b'intervening sidecar')
        self.assertEqual(len(list(layout.catalogue_dir.glob('.bootstrap-*.sqlite3'))), 1)

    def test_two_processes_publish_exactly_one_catalogue(self):
        kwargs = {key: str(value) for key, value in self.evidence.kwargs(self.root / 'unused').items() if key not in {'database_path', 'baselines'}}
        kwargs.update(app_data_root=str(self.app_root), baselines=self.evidence.baselines)
        contract = self.root / 'bootstrap.json'
        contract.write_text(json.dumps(kwargs))
        gate = self.root / 'start'
        script = """
import json, sys, time
from pathlib import Path
sys.path.insert(0, 'src')
from personal_librarian.production import bootstrap_production
while not Path(sys.argv[2]).exists():
    time.sleep(.01)
try:
    bootstrap_production(**json.loads(Path(sys.argv[1]).read_text()))
except Exception:
    sys.exit(2)
"""
        processes = [subprocess.Popen([sys.executable, '-c', script, str(contract), str(gate)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        try:
            gate.touch()
            outputs = [process.communicate(timeout=30) for process in processes]
            self.assertEqual(sorted(process.returncode for process in processes), [0, 2], outputs)
            layout = production.application_data_layout(self.app_root)
            self.assertTrue(layout.catalogue_path.is_file())
            self.assertEqual(production.production_health(app_data_root=self.app_root).values['integrity_check'], 'ok')
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_intervening_destination_is_preserved(self):
        layout = production.application_data_layout(self.app_root)
        original_replace = production.os.replace
        original_rename = production.os.rename

        def race(operation):
            def publish(source, destination, *args, **kwargs):
                if Path(source).name.startswith('.bootstrap-') and Path(destination) == layout.catalogue_path:
                    layout.catalogue_path.write_bytes(b'concurrent catalogue must survive')
                return operation(source, destination, *args, **kwargs)
            return publish

        with mock.patch.object(production.os, 'replace', side_effect=race(original_replace)), mock.patch.object(production.os, 'rename', side_effect=race(original_rename)):
            with self.assertRaises((OSError, production.ProductionError)):
                self.bootstrap()
        self.assertEqual(layout.catalogue_path.read_bytes(), b'concurrent catalogue must survive')
        self.assertEqual(len(list(layout.catalogue_dir.glob('.bootstrap-*.sqlite3'))), 1)

    def test_interrupted_staging_is_retained(self):
        original = production.import_verified_evidence

        def interrupt(**kwargs):
            original(**kwargs)
            raise KeyboardInterrupt('synthetic staging interruption')

        with mock.patch.object(production, 'import_verified_evidence', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.bootstrap()
        layout = production.application_data_layout(self.app_root)
        self.assertFalse(layout.catalogue_path.exists())
        self.assertEqual(len(list(layout.catalogue_dir.glob('.bootstrap-*.sqlite3'))), 1)

    def test_failed_promotion_preserves_staging(self):
        original_replace = production.os.replace
        original_rename = production.os.rename

        def fail(operation):
            def publish(source, destination, *args, **kwargs):
                if Path(source).name.startswith('.bootstrap-'):
                    raise OSError('synthetic publication failure')
                return operation(source, destination, *args, **kwargs)
            return publish

        with mock.patch.object(production.os, 'replace', side_effect=fail(original_replace)), mock.patch.object(production.os, 'rename', side_effect=fail(original_rename)):
            with self.assertRaisesRegex(OSError, 'publication failure'):
                self.bootstrap()
        layout = production.application_data_layout(self.app_root)
        self.assertFalse(layout.catalogue_path.exists())
        self.assertEqual(len(list(layout.catalogue_dir.glob('.bootstrap-*.sqlite3'))), 1)
