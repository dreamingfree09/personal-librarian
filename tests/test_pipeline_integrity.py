"""Synthetic integrity regressions for the inventory/hash/duplicate boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from personal_librarian.action_planning import _catalogue_mtime_ns
from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.pipeline.inventory import run_inventory
from personal_librarian.pipeline.hashing import run_sha256
from personal_librarian.pipeline.exact_duplicates import derive_exact_duplicates


class PipelineIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'synthetic'
        self.root.mkdir()
        self.db = self.base / 'test.sqlite3'
        self.paths = [self.root / 'a.jpg', self.root / 'b.jpg']
        for path in self.paths:
            path.write_bytes(b'same synthetic content')
            os.utime(path, ns=(1700000000123456700, 1700000000123456700))

    def inventory(self, name='inv'):
        return run_inventory(database_path=self.db, job_id=name, source='Synthetic, original', root=self.root)

    def hashing(self, name='hash', inventory='inv'):
        return run_sha256(database_path=self.db, job_id=name, inventory_job_id=inventory,
                          source='Synthetic, original', root=self.root)

    def derive(self, name='duplicates', source='hash'):
        return derive_exact_duplicates(database_path=self.db, job_id=name, hash_job_id=source)

    def connect(self):
        c = connect_existing_catalogue(self.db, read_only=False)
        self.addCleanup(c.close)
        return c

    def prepare(self):
        self.inventory()
        self.hashing()

    def test_f11_inventory_and_hash_preserve_exact_observed_mtime(self):
        self.inventory()
        c = self.connect()
        actual = self.paths[0].stat().st_mtime_ns
        self.assertEqual(actual, 1700000000123456700, 'Fixture requires Windows 100 ns precision')
        row = c.execute('SELECT observed_modified_at FROM physical_instances ORDER BY physical_instance_id').fetchone()
        self.assertEqual(_catalogue_mtime_ns(row[0]), actual)
        self.hashing()
        row = c.execute('SELECT observed_modified_at FROM physical_instances ORDER BY physical_instance_id').fetchone()
        self.assertEqual(_catalogue_mtime_ns(row[0]), actual)

    def crash_at_finish(self, mode='before', job='duplicates'):
        code = """
import os, sys
from unittest import mock
sys.path.insert(0, sys.argv[1])
from personal_librarian.pipeline import exact_duplicates as d
original = d.finish_job
connect = d.connect_existing_catalogue
mode = sys.argv[4]
class Connection:
    def __init__(self, real): self.real = real
    def __getattr__(self, name): return getattr(self.real, name)
    def execute(self, sql, *args):
        result = self.real.execute(sql, *args)
        if mode == 'marker' and 'UPDATE pipeline_jobs' in sql and "status = 'completed'" in sql:
            os._exit(71)
        return result
    def commit(self):
        self.real.commit()
        row = self.real.execute("SELECT status FROM pipeline_jobs WHERE job_id=?", (sys.argv[3],)).fetchone()
        if mode == 'commit' and row and row[0] == 'completed': os._exit(71)
def crash(connection, job):
    if mode == 'legacy': connection.commit()
    if mode in ('after', 'commit', 'marker'): original(connection, job)
    os._exit(71)
with mock.patch.object(d, 'finish_job', crash), mock.patch.object(d, 'connect_existing_catalogue', lambda *a, **kw: Connection(connect(*a, **kw))):
    d.derive_exact_duplicates(database_path=sys.argv[2], job_id=sys.argv[3], hash_job_id='hash')
"""
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-u', '-c', code,
                                 str(Path(__file__).resolve().parents[1] / 'src'), str(self.db), job, mode],
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 71, result.stderr)

    def test_f12_process_death_at_completion_boundary_is_resumable(self):
        self.prepare()
        self.crash_at_finish()
        result = self.derive()
        self.assertEqual(result.metrics['exact_duplicate_groups'], 1)
        self.assertEqual(result.metrics['duplicate_memberships'], 2)
        self.assertEqual(self.derive().metrics, result.metrics)

    def test_f13_new_hash_does_not_change_old_derivation(self):
        self.prepare()
        original = self.derive('original')
        self.paths[1].write_bytes(b'different newer synthetic content')
        self.inventory('inv-new')
        self.hashing('hash-new', 'inv-new')
        repeated = self.derive('rederived')
        self.assertEqual(repeated.metrics, original.metrics)
        c = self.connect()
        groups = c.execute('SELECT content_identity_id, copies, size_bytes, source_pattern FROM exact_duplicate_groups ORDER BY exact_duplicate_group_id').fetchall()
        self.assertEqual(tuple(groups[0]), tuple(groups[1]))
        self.assertEqual(groups[0][3], 'Synthetic, original')

    def snapshot(self):
        c = self.connect()
        try:
            return tuple(c.iterdump())
        finally:
            c.close()

    def assert_consistent(self):
        c = self.connect()
        self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_f12_post_commit_and_marker_interruptions(self):
        self.prepare()
        for mode in ['after', 'commit', 'marker']:
            with self.subTest(mode=mode):
                self.crash_at_finish(mode, mode)
                c = self.connect()
                row = c.execute('SELECT status, analysis_run_id FROM pipeline_jobs WHERE job_id=?', (mode,)).fetchone()
                count = c.execute('SELECT COUNT(*) FROM exact_duplicate_groups WHERE analysis_run_id=?', (row[1],)).fetchone()[0]
                self.assertEqual((row[0], count), ('running', 0) if mode == 'marker' else ('completed', 1))
                result = self.derive(mode)
                before = self.snapshot()
                self.assertEqual(self.derive(mode).metrics, result.metrics)
                self.assertEqual(self.snapshot(), before)
                self.assert_consistent()

    def test_f12_legacy_committed_output_reconciles_without_replacement(self):
        self.prepare()
        unrelated = self.derive('unrelated')
        self.crash_at_finish('legacy')
        c = self.connect()
        before = [tuple(r) for r in c.execute('SELECT * FROM exact_duplicate_groups ORDER BY exact_duplicate_group_id')]
        members = [tuple(r) for r in c.execute('SELECT * FROM exact_duplicate_memberships ORDER BY 1,2')]
        self.assertEqual(c.execute("SELECT status FROM pipeline_jobs WHERE job_id='duplicates'").fetchone()[0], 'running')
        result = self.derive()
        self.assertEqual(result.metrics, unrelated.metrics)
        self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM exact_duplicate_groups ORDER BY exact_duplicate_group_id')], before)
        self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM exact_duplicate_memberships ORDER BY 1,2')], members)
        self.assert_consistent()

    def test_f12_partial_legacy_output_is_preserved_and_not_completed(self):
        self.prepare()
        self.derive('unrelated')
        self.crash_at_finish('legacy')
        c = self.connect()
        c.execute("DELETE FROM exact_duplicate_memberships WHERE physical_instance_id=(SELECT MIN(physical_instance_id) FROM physical_instances) AND exact_duplicate_group_id=(SELECT exact_duplicate_group_id FROM exact_duplicate_groups WHERE analysis_run_id=(SELECT analysis_run_id FROM pipeline_jobs WHERE job_id='duplicates'))")
        c.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(PipelineError, 'offline review'):
            self.derive()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(c.execute("SELECT status FROM pipeline_jobs WHERE job_id='duplicates'").fetchone()[0], 'running')

    def test_f12_completed_but_incomplete_output_never_reports_success(self):
        self.prepare(); self.derive()
        c = self.connect()
        c.execute('DELETE FROM exact_duplicate_memberships WHERE physical_instance_id=1'); c.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(PipelineError, 'offline review'):
            self.derive()
        self.assertEqual(self.snapshot(), before)

    def test_f13_current_metadata_is_not_historical_evidence(self):
        self.prepare(); original = self.derive('original')
        c = self.connect()
        c.execute("UPDATE sources SET display_name='Renamed current source'")
        c.execute("UPDATE physical_instances SET size_bytes=987654, observed_modified_at='2000-01-01T00:00:00Z', current_observed_path='C:/different-current-locator', raw_relative_path='new-current-name', content_identity_id=NULL")
        c.commit()
        # No filesystem access is needed to reproduce a named completed hash job.
        with mock.patch.object(Path, 'open', side_effect=AssertionError('no content read')):
            result = self.derive('historical')
            self.assertEqual(result.metrics, original.metrics)
            self.assertEqual(self.derive('original').metrics, original.metrics)
        rows = c.execute('SELECT content_identity_id,copies,size_bytes,source_pattern,unique_sources FROM exact_duplicate_groups ORDER BY exact_duplicate_group_id').fetchall()
        self.assertEqual(tuple(rows[0]), tuple(rows[1]))
        self.assertEqual(tuple(rows[0][3:]), ('Synthetic, original', 1))

    def test_f13_interrupted_old_derivation_after_new_hash(self):
        self.prepare(); self.crash_at_finish('legacy')
        self.paths[1].write_bytes(b'new longer synthetic bytes')
        self.inventory('new-inventory'); self.hashing('new-hash', 'new-inventory')
        result = self.derive()
        self.assertEqual(result.metrics['duplicate_memberships'], 2)
        self.assertEqual(result.metrics['reclaimable_bytes'], len(b'same synthetic content'))
        self.assertEqual(self.derive('new-groups', 'new-hash').metrics['exact_duplicate_groups'], 0)

    def test_f13_source_job_configuration_and_completion_required(self):
        self.prepare(); self.derive()
        self.hashing('another-hash')
        before = self.snapshot()
        with self.assertRaisesRegex(PipelineError, 'different pipeline configuration'):
            self.derive(source='another-hash')
        self.assertEqual(self.snapshot(), before)
        for source in ['inv', 'missing']:
            with self.assertRaisesRegex(PipelineError, 'completed SHA-256'):
                self.derive(source=source)
        c = self.connect(); c.execute("UPDATE pipeline_jobs SET status='interrupted' WHERE job_id='hash'"); c.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(PipelineError, 'completed SHA-256'):
            self.derive()
        self.assertEqual(self.snapshot(), before)

    def test_f13_missing_or_altered_historical_evidence_fails_closed(self):
        self.prepare(); self.derive()
        c = self.connect()
        for sql in [
            "UPDATE pipeline_job_items SET size_bytes=size_bytes+1 WHERE job_id='hash'",
            "UPDATE pipeline_job_items SET modified_time_ns=modified_time_ns+100 WHERE job_id='hash'",
            "UPDATE pipeline_job_items SET sha256='" + 'f'*64 + "' WHERE job_id='hash'",
            "DELETE FROM pipeline_job_items WHERE job_id='hash'",
            "UPDATE pipeline_jobs SET config_fingerprint='invalid' WHERE job_id='hash'",
            "UPDATE pipeline_hash_observations SET analysis_run_id=(SELECT analysis_run_id FROM pipeline_jobs WHERE job_id='inv')",
        ]:
            with self.subTest(sql=sql):
                before = self.snapshot()
                c.execute('BEGIN'); c.execute(sql); c.commit()
                corrupted = self.snapshot()
                with self.assertRaises(PipelineError): self.derive()
                self.assertEqual(self.snapshot(), corrupted)
                # Restore only the disposable fixture to exercise an independent corruption.
                c.close()
                replacement = self.base / 'restored.sqlite3'
                restore = sqlite3.connect(replacement)
                restore.executescript('\n'.join(before)); restore.close()
                os.replace(replacement, self.db)
                c = self.connect()

    def test_f13_hash_reuse_zero_bytes_and_unique_nonmembers(self):
        for path in self.paths: path.write_bytes(b'')
        (self.root / 'unique.jpg').write_bytes(b'one unique')
        self.prepare(); self.hashing('reused')
        first = self.derive(); replay = self.derive('reused-groups', 'reused')
        self.assertEqual(first.metrics, replay.metrics)
        self.assertEqual(first.metrics['duplicate_memberships'], 2)
        self.assertEqual(first.metrics['reclaimable_bytes'], 0)
        self.assert_consistent()


if __name__ == '__main__':
    unittest.main()
