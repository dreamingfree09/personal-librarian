"""Exact filesystem timestamp round trips and planning preflight."""
from __future__ import annotations
import os
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from personal_librarian.action_planning import _catalogue_mtime_ns, create_plan, preflight_plan
from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.decisions import nominate, approve
from personal_librarian.pipeline.common import format_mtime_ns
from personal_librarian.pipeline.inventory import run_inventory
from personal_librarian.pipeline.hashing import run_sha256
from personal_librarian.pipeline.exact_duplicates import derive_exact_duplicates


class TimestampPrecisionTests(unittest.TestCase):
    def test_integer_round_trips_and_offset_semantics(self):
        for ns in [0, 1, -1, -123456789, 1700000000123456700,
                   1700000000123456800, 999999999999999999]:
            with self.subTest(ns=ns):
                self.assertEqual(_catalogue_mtime_ns(format_mtime_ns(ns)), ns)
        self.assertEqual(_catalogue_mtime_ns("2023-11-14T23:13:20.123456700+01:00"),
                         1700000000123456700)
        self.assertEqual(_catalogue_mtime_ns("1969-12-31T23:59:59.999999999Z"), -1)
        self.assertIsNone(_catalogue_mtime_ns("2023-11-14T22:13:20.123456"))
        self.assertIsNone(_catalogue_mtime_ns("not a timestamp"))
        # Existing lower-precision text stays exactly that, not reconstructed observations.
        self.assertIsNone(_catalogue_mtime_ns("2023-11-14T22:13:20.123456Z"))

    def test_inventory_hash_reuse_and_submicrosecond_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); root = base / "synthetic"; root.mkdir()
            db = base / "test.sqlite3"; destination = base / "destination"; destination.mkdir()
            paths = [root / "a.jpg", root / "b.jpg"]
            original = 1700000000123456700
            for path in paths:
                path.write_bytes(b"equal fixture content")
                os.utime(path, ns=(original, original))
                self.assertEqual(path.stat().st_mtime_ns, original)
            run_inventory(database_path=db, job_id="inv", source="Fixture", root=root)
            with closing(connect_existing_catalogue(db, read_only=True)) as c:
                for table in ["physical_instances", "inventory_observations", "instance_path_observations"]:
                    values = c.execute(f"SELECT observed_modified_at FROM {table}").fetchall()
                    self.assertEqual([_catalogue_mtime_ns(r[0]) for r in values], [original, original])
            for name in ["hash", "reuse"]:
                report = run_sha256(database_path=db, job_id=name, inventory_job_id="inv", source="Fixture", root=root)
                self.assertEqual(report.metrics["hash_reused"], 2 if name == "reuse" else 0)
                with closing(connect_existing_catalogue(db, read_only=True)) as c:
                    self.assertEqual([_catalogue_mtime_ns(r[0]) for r in c.execute("SELECT observed_modified_at FROM physical_instances")], [original, original])
            derive_exact_duplicates(database_path=db, job_id="dups", hash_job_id="hash")
            with closing(connect_existing_catalogue(db, read_only=True)) as c:
                ids = c.execute("SELECT physical_instance_id, content_identity_id FROM physical_instances ORDER BY physical_instance_id").fetchall()
            nominate(database_path=db, event_id="nom", context_type="exact", context_id=ids[0][1], physical_instance_id=ids[0][0], canonical_scope="archival", owner="synthetic owner")
            approve(database_path=db, event_id="approval", nomination_id="nom", physical_instance_id=ids[0][0], canonical_scope="archival", owner="synthetic owner", reason="synthetic test")
            plan = create_plan(database_path=db, policy_id="exact-duplicate-quarantine-v1", context_type="exact", context_id=ids[0][1], canonical_scope="archival", approval_event_id="approval", destination_root=destination, owner="synthetic owner", source_physical_instance_ids=[ids[1][0]], safety_margin_bytes=0)
            def source_state(selected=plan):
                result = preflight_plan(database_path=db, plan_id=selected["plan_id"], actor="synthetic test")
                return result["items"][0]["latest_preflight"]["source_state"]
            self.assertEqual(source_state(), "PASS")
            # Reproduce the historical planning contract at creation time; never update
            # append-only plan rows or disable their protection triggers.
            with closing(connect_existing_catalogue(db, read_only=False)) as c:
                c.execute("UPDATE physical_instances SET observed_modified_at='2023-11-14T22:13:20.123457Z' WHERE physical_instance_id=?", (ids[1][0],))
                c.commit()
            with mock.patch("personal_librarian.action_planning._catalogue_mtime_ns", return_value=1700000000123457000):
                legacy = create_plan(database_path=db, policy_id="exact-duplicate-quarantine-v1", context_type="exact", context_id=ids[0][1], canonical_scope="archival", approval_event_id="approval", destination_root=destination, owner="synthetic owner", source_physical_instance_ids=[ids[1][0]], safety_margin_bytes=0)
            os.utime(paths[1], ns=(1700000000123457000, 1700000000123457000))
            self.assertEqual(source_state(legacy), "source_mtime_precision_unavailable")
            with closing(connect_existing_catalogue(db, read_only=False)) as c:
                c.execute("UPDATE physical_instances SET observed_modified_at=? WHERE physical_instance_id=?", (format_mtime_ns(original), ids[1][0]))
                c.commit()
            os.utime(paths[1], ns=(original, original))
            # A rounded old timestamp would equal this later observable state.
            changed = 1700000000123457000
            os.utime(paths[1], ns=(changed, changed))
            self.assertEqual(source_state(), "source_mtime_changed")
            run_inventory(database_path=db, job_id="inv-later", source="Fixture", root=root)
            later = run_sha256(database_path=db, job_id="hash-later", inventory_job_id="inv-later", source="Fixture", root=root)
            self.assertEqual(later.metrics["hash_reused"], 1)
            with closing(connect_existing_catalogue(db, read_only=True)) as c:
                old = c.execute("SELECT modified_time_ns FROM pipeline_job_items WHERE job_id='inv' ORDER BY item_key").fetchall()
                self.assertEqual([r[0] for r in old], [original, original])
                new = c.execute("SELECT observed_modified_at FROM physical_instances WHERE physical_instance_id=?", (ids[1][0],)).fetchone()[0]
                self.assertEqual(_catalogue_mtime_ns(new), changed)
                self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])

if __name__ == "__main__":
    unittest.main()
