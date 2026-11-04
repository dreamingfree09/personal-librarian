"""F16: original accepted job membership and inputs survive mutable catalogues."""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from unittest.mock import patch

from test_date_evidence import DateServiceCase
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.pipeline.common import PipelineInterrupted
from personal_librarian.pipeline import date_evidence as pipeline


class DateJobSelectionTests(DateServiceCase):
    def insert(self, physical: int, content: int | None = 0) -> None:
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("INSERT INTO physical_instances(physical_instance_id,instance_key,source_id,"
                        "content_identity_id,raw_relative_path,observed_modified_at) VALUES(?,?,?,?,?,?)",
                        (physical, f"i-{physical}", self.source_id,
                         None if content is None else self.content_ids[content],
                         f"folder{physical}/IMG_20200102_030405.jpg", "2024-01-01T00:00:00Z"))
            con.commit()

    def run_job(self, **kwargs):
        return pipeline.run_date_evidence_pipeline(database_path=self.database,
                                                  job_id=kwargs.pop("job_id", "frozen"), limit=4, **kwargs)

    def state(self):
        with closing(sqlite3.connect(self.database)) as con:
            return list(con.iterdump())

    def ids(self):
        with closing(sqlite3.connect(self.database)) as con:
            return [r[0] for r in con.execute("SELECT physical_instance_id FROM date_evidence_job_items "
                                             "WHERE job_id='frozen' ORDER BY physical_instance_id")]

    def test_completed_retry_cannot_absorb_sparse_insertions_or_eligibility_changes(self):
        self.insert(10)
        self.insert(30, 1)
        self.insert(20, None)
        first = self.run_job()
        self.insert(5, 2)
        self.insert(40, 3)
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("UPDATE physical_instances SET content_identity_id=? WHERE physical_instance_id=20",
                        (self.content_ids[4],))
            con.commit()
        before = self.state()
        again = self.run_job()
        self.assertEqual(self.ids(), [10, 30])
        self.assertEqual(again.as_dict(), first.as_dict())
        self.assertEqual(self.state(), before)
        future = self.run_job(job_id="future", after_physical_instance_id=30)
        self.assertEqual(future.metrics["selected_count"], 1)
        self.assertEqual(future.metrics["next_cursor"], 40)

    def test_empty_completed_selection_stays_empty(self):
        first = self.run_job(after_physical_instance_id=50)
        self.insert(60)
        before = self.state()
        again = self.run_job(after_physical_instance_id=50)
        self.assertEqual(again.as_dict(), first.as_dict())
        self.assertEqual(self.ids(), [])
        self.assertEqual(self.state(), before)

    def test_nonzero_cursor_retry_ignores_new_records_on_both_sides(self):
        self.insert(10)
        self.insert(30, 1)
        first = self.run_job(after_physical_instance_id=8)
        for physical in (5, 20, 40):
            self.insert(physical, 2)
        before = self.state()
        self.assertEqual(self.run_job(after_physical_instance_id=8).as_dict(), first.as_dict())
        self.assertEqual(self.ids(), [10, 30])
        self.assertEqual(self.state(), before)

    def test_identical_completed_retry_is_byte_for_byte_logically_read_only(self):
        self.insert(10)
        self.run_job()
        before = self.state()
        self.run_job()
        self.assertEqual(self.state(), before)

    def test_interrupted_job_ignores_new_lower_ids_and_newly_eligible_rows(self):
        self.insert(10)
        self.insert(30, 1)
        self.insert(20, None)
        with self.assertRaises(PipelineInterrupted):
            self.run_job(interrupt_after=1)
        self.insert(5, 2)
        self.insert(40, 3)
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("UPDATE physical_instances SET content_identity_id=? WHERE physical_instance_id=20",
                        (self.content_ids[4],))
            con.commit()
        report = self.run_job()
        self.assertEqual(self.ids(), [10, 30])
        self.assertEqual(report.metrics["selected_count"], 2)
        self.assertEqual(report.metrics["next_cursor"], 30)
        self.assertTrue(report.metrics["end_of_catalogue"])

    def test_resume_rejects_changed_content_and_source_fields_without_writes(self):
        self.insert(10)
        self.insert(30, 1)
        with self.assertRaises(PipelineInterrupted):
            self.run_job(interrupt_after=1)
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("UPDATE physical_instances SET raw_relative_path='IMG_19990101_010101.jpg' "
                        "WHERE physical_instance_id=30")
            con.commit()
        before = self.state()
        with self.assertRaisesRegex(PipelineError, "selection.*changed|changed.*selection"):
            self.run_job()
        self.assertEqual(self.state(), before)

    def test_original_selection_survives_crash_before_first_checkpoint(self):
        self.insert(10)
        self.insert(30, 1)
        with patch.object(pipeline, "_process_item", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job()
        self.insert(5, 2)
        self.run_job()
        self.assertEqual(self.ids(), [10, 30])

    def test_crash_after_evidence_before_checkpoint_rolls_back_item(self):
        self.insert(10)
        original = pipeline._process_item
        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise KeyboardInterrupt
        with patch.object(pipeline, "_process_item", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job()
        with closing(sqlite3.connect(self.database)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM content_date_evidence").fetchone()[0], 0)
        self.run_job()
        before = self.state()
        self.run_job()
        self.assertEqual(self.state(), before)

    def test_each_source_binding_is_checked_even_for_checkpointed_members(self):
        self.insert(10)
        self.insert(30, 1)
        with self.assertRaises(PipelineInterrupted):
            self.run_job(interrupt_after=1)
        with closing(sqlite3.connect(self.database)) as con:
            source = con.execute("INSERT INTO sources(source_key,display_name,source_type) "
                                 "VALUES('other','Other','test')").lastrowid
            con.commit()
        for physical in (10, 30):
            for field, changed in (("content_identity_id", self.content_ids[5]),
                                   ("content_identity_id", None), ("source_id", source),
                                   ("raw_relative_path", "changed.jpg"),
                                   ("observed_created_at", "2000-01-01"),
                                   ("observed_modified_at", "2001-01-01")):
                with self.subTest(physical=physical, field=field, changed=changed):
                    with closing(sqlite3.connect(self.database)) as con:
                        old = con.execute(f"SELECT {field} FROM physical_instances WHERE physical_instance_id=?",
                                          (physical,)).fetchone()[0]
                        con.execute(f"UPDATE physical_instances SET {field}=? WHERE physical_instance_id=?",
                                    (changed, physical))
                        con.commit()
                    before = self.state()
                    with self.assertRaisesRegex(PipelineError, "selection inputs changed"):
                        self.run_job()
                    self.assertEqual(self.state(), before)
                    with closing(sqlite3.connect(self.database)) as con:
                        con.execute(f"UPDATE physical_instances SET {field}=? WHERE physical_instance_id=?",
                                    (old, physical))
                        con.commit()
        self.run_job()
        self.assertEqual(self.ids(), [10, 30])

    def test_snapshot_and_job_insert_are_atomic_on_database_failure(self):
        self.insert(10)
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("CREATE TRIGGER reject_job BEFORE INSERT ON date_evidence_jobs "
                        "BEGIN SELECT RAISE(ABORT,'injected job failure'); END")
            con.commit()
        before = self.state()
        with self.assertRaisesRegex(PipelineError, "injected job failure"):
            self.run_job()
        self.assertEqual(self.state(), before)
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("DROP TRIGGER reject_job")
            con.commit()
        self.run_job()
        self.assertEqual(self.ids(), [10])

    def test_snapshot_corruption_and_missing_checkpoint_fail_without_mutation(self):
        self.insert(10)
        self.run_job()
        with closing(sqlite3.connect(self.database)) as con:
            original = con.execute("SELECT parameters_json FROM analysis_runs").fetchone()[0]
            data = json.loads(original)
            data["selection"]["members"][0]["raw_relative_path"] = "substitute.jpg"
            con.execute("UPDATE analysis_runs SET parameters_json=?", (json.dumps(data),))
            con.commit()
        before = self.state()
        with self.assertRaisesRegex(PipelineError, "Invalid durable date-job selection"):
            self.run_job()
        self.assertEqual(self.state(), before)
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("UPDATE analysis_runs SET parameters_json=?", (original,))
            con.execute("DELETE FROM date_evidence_job_items")
            con.commit()
        before = self.state()
        with self.assertRaisesRegex(PipelineError, "incomplete checkpoints"):
            self.run_job()
        self.assertEqual(self.state(), before)

    def test_completed_retry_does_not_reinterpret_later_source_metadata(self):
        self.insert(10)
        first = self.run_job()
        with closing(sqlite3.connect(self.database)) as con:
            con.execute("UPDATE physical_instances SET raw_relative_path='IMG_19990101_010101.jpg', "
                        "observed_modified_at='1999-01-01'")
            con.commit()
        before = self.state()
        self.assertEqual(self.run_job().as_dict(), first.as_dict())
        self.assertEqual(self.state(), before)

    def test_real_process_exit_mid_item_retains_selection_and_rolls_back_evidence(self):
        import subprocess
        import sys
        self.insert(10)
        self.insert(30, 1)
        code = """
import os,sys
sys.path.insert(0, 'src')
from personal_librarian.pipeline import date_evidence as p
original=p._process_item
def stop(*a, **k):
    original(*a, **k)
    os._exit(73)
p._process_item=stop
p.run_date_evidence_pipeline(database_path=sys.argv[1],job_id='frozen',limit=4)
"""
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code, str(self.database)],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 73, result.stderr)
        with closing(sqlite3.connect(self.database)) as con:
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM content_date_evidence").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM date_evidence_jobs").fetchone()[0], 1)
        self.insert(5, 2)
        self.run_job()
        self.assertEqual(self.ids(), [10, 30])

    def test_crash_after_completion_commit_does_not_reopen_job(self):
        self.insert(10)
        with patch.object(pipeline, "_report", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job()
        self.insert(20, 1)
        before = self.state()
        result = self.run_job()
        self.assertEqual(result.metrics["selected_count"], 1)
        self.assertEqual(self.state(), before)

    def test_reporting_database_error_does_not_undo_durable_completion(self):
        self.insert(10)
        with patch.object(pipeline, "_report", side_effect=sqlite3.OperationalError("report interrupted")):
            with self.assertRaisesRegex(PipelineError, "report interrupted"):
                self.run_job()
        with closing(sqlite3.connect(self.database)) as con:
            self.assertEqual(con.execute("SELECT status FROM date_evidence_jobs").fetchone()[0], "completed")
        before = self.state()
        self.run_job()
        self.assertEqual(self.state(), before)

    def test_invalid_checkpoint_identity_is_not_silently_adopted(self):
        self.insert(10)
        self.insert(30, 1)
        with self.assertRaises(PipelineInterrupted):
            self.run_job(interrupt_after=1)
        with closing(sqlite3.connect(self.database)) as con:
            # Simulate externally corrupted state, not a supported catalogue write.
            con.execute("DROP TRIGGER date_evidence_job_items_relationship_update")
            con.execute("UPDATE date_evidence_job_items SET content_identity_id=?", (self.content_ids[5],))
            con.commit()
        before = self.state()
        with self.assertRaisesRegex(PipelineError, "Checkpoint does not match"):
            self.run_job()
        self.assertEqual(self.state(), before)

    def test_interrupted_historical_job_without_snapshot_is_preserved(self):
        self.insert(10)
        self.insert(30, 1)
        with self.assertRaises(PipelineInterrupted):
            self.run_job(interrupt_after=1)
        with closing(sqlite3.connect(self.database)) as con:
            request = con.execute("SELECT config_json FROM date_evidence_jobs").fetchone()[0]
            con.execute("UPDATE analysis_runs SET parameters_json=?", (request,))
            con.commit()
        self.insert(5, 2)
        before = self.state()
        with self.assertRaisesRegex(PipelineError, "no provable original selection"):
            self.run_job()
        self.assertEqual(self.state(), before)
