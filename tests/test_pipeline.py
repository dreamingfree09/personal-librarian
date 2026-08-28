from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.pipeline.common import (
    MEDIA_EXTENSIONS,
    MEDIA_EXTENSION_POLICY_VERSION,
    PipelineInterrupted,
    validate_root,
)
from personal_librarian.pipeline.exact_duplicates import derive_exact_duplicates
from personal_librarian.pipeline.hashing import run_sha256
from personal_librarian.pipeline.inventory import run_inventory
from personal_librarian.pipeline.reconciliation import reconcile_historical_baseline
from personal_librarian.cli import build_parser


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        self.root = self.base / "media"
        self.root.mkdir()
        self.database = self.base / "catalogue.sqlite3"

    def write(self, relative: str, content: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def inventory(self, job_id: str = "inventory-1", **kwargs):
        return run_inventory(
            database_path=self.database, job_id=job_id, source="Synthetic",
            root=self.root, **kwargs,
        )

    def hashing(self, job_id: str, inventory_job: str = "inventory-1", **kwargs):
        return run_sha256(
            database_path=self.database, job_id=job_id,
            inventory_job_id=inventory_job, source="Synthetic", root=self.root, **kwargs,
        )

    def connect(self):
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.addCleanup(connection.close)
        return connection

    def test_deterministic_inventory_extensions_nested_unicode_and_zero_bytes(self) -> None:
        greek = self.write("φωτογραφίες/άλφα.JPG", b"greek")
        composed = "café.png"
        decomposed = unicodedata.normalize("NFD", composed)
        self.write(composed, b"nfc")
        self.write(decomposed, b"nfd")
        self.write("nested/empty.mp4", b"")
        self.write("nested/ignored.txt", b"not media")
        states = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.root.rglob("*") if path.is_file()}

        report = self.inventory()
        rerun = self.inventory()
        self.assertEqual(report.metrics["media_rows"], 4)
        self.assertEqual(report.metrics["extension_policy"], MEDIA_EXTENSION_POLICY_VERSION)
        self.assertEqual(report.metrics["outcomes"]["unsupported_extension"], 1)
        self.assertEqual(report.metrics["outcomes"]["zero_byte_inventory"], 1)
        self.assertEqual(rerun.metrics, report.metrics)
        connection = self.connect()
        raw = [row[0] for row in connection.execute(
            "SELECT raw_relative_path FROM physical_instances ORDER BY raw_relative_path"
        )]
        self.assertIn(str(greek.relative_to(self.root)), raw)
        self.assertIn(composed, raw)
        self.assertIn(decomposed, raw)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM physical_instances").fetchone()[0], 4)
        for path, state in states.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state)

    def test_streaming_hash_correctness_reuse_and_exact_duplicate_derivation(self) -> None:
        payload = (b"streamed-content" * 100_000) + b"end"
        self.write("a.jpg", payload)
        self.write("nested/b.jpeg", payload)
        self.write("empty.png", b"")
        self.inventory()
        first = self.hashing("hash-1")
        second = self.hashing("hash-2")
        exact = derive_exact_duplicates(
            database_path=self.database, job_id="duplicates-1", hash_job_id="hash-1"
        )
        self.assertEqual(first.metrics["hash_successes"], 3)
        self.assertEqual(first.metrics["hash_reused"], 0)
        self.assertEqual(second.metrics["hash_reused"], 3)
        self.assertEqual(first.metrics["distinct_sha256"], 2)
        self.assertEqual(exact.metrics["exact_duplicate_groups"], 1)
        self.assertEqual(exact.metrics["duplicate_memberships"], 2)
        self.assertEqual(exact.metrics["redundant_copies"], 1)
        self.assertEqual(exact.metrics["reclaimable_bytes"], len(payload))
        connection = self.connect()
        digest = connection.execute(
            "SELECT sha256 FROM pipeline_job_items WHERE job_id = 'hash-1' "
            "AND raw_relative_path = 'a.jpg'"
        ).fetchone()[0]
        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM content_identities").fetchone()[0], 2
        )

    def test_size_and_mtime_changes_force_rehash(self) -> None:
        path = self.write("change.jpg", b"first")
        self.inventory()
        self.hashing("hash-first")
        path.write_bytes(b"second-and-longer")
        size_changed = self.hashing("hash-size-changed")
        self.assertEqual(size_changed.metrics["hash_reused"], 0)
        self.assertEqual(size_changed.metrics["outcomes"]["hash_success"], 1)

        original = path.read_bytes()
        new_ns = path.stat().st_mtime_ns + 2_000_000_000
        os.utime(path, ns=(new_ns, new_ns))
        mtime_changed = self.hashing("hash-mtime-changed")
        self.assertEqual(mtime_changed.metrics["hash_reused"], 0)
        self.assertEqual(path.read_bytes(), original)

    def test_disappeared_and_permission_denied_are_not_empty_files(self) -> None:
        vanished = self.write("vanished.jpg", b"gone")
        blocked = self.write("blocked.png", b"blocked")
        self.inventory()
        vanished.unlink()
        original_open = Path.open

        def guarded_open(path: Path, *args, **kwargs):
            if path == blocked:
                raise PermissionError("synthetic denial")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", guarded_open):
            report = self.hashing("hash-errors")
        self.assertEqual(report.metrics["outcomes"]["disappeared"], 1)
        self.assertEqual(report.metrics["outcomes"]["permission_denied"], 1)
        self.assertEqual(report.metrics["hash_successes"], 0)

    def test_interrupted_inventory_resumes_from_committed_checkpoint(self) -> None:
        self.write("a.jpg", b"a")
        self.write("b.jpg", b"b")
        self.write("c.jpg", b"c")
        with self.assertRaises(PipelineInterrupted):
            self.inventory(interrupt_after=1)
        connection = self.connect()
        self.assertEqual(
            connection.execute("SELECT status FROM pipeline_jobs WHERE job_id = 'inventory-1'").fetchone()[0],
            "interrupted",
        )
        connection.close()
        report = self.inventory()
        self.assertEqual(report.metrics["media_rows"], 3)
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM physical_instances").fetchone()[0], 3)
        finally:
            connection.close()

    def test_interrupted_hash_resumes_without_rehashing_checkpointed_item(self) -> None:
        self.write("a.jpg", b"a")
        self.write("b.jpg", b"b")
        self.inventory()
        with self.assertRaises(PipelineInterrupted):
            self.hashing("hash-resume", interrupt_after=1)
        report = self.hashing("hash-resume")
        self.assertEqual(report.metrics["hash_successes"], 2)
        connection = self.connect()
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM pipeline_hash_observations pho "
                "JOIN pipeline_jobs pj ON pj.analysis_run_id = pho.analysis_run_id "
                "WHERE pj.job_id = 'hash-resume'"
            ).fetchone()[0],
            2,
        )

    def test_changed_during_hash_is_explicit_and_digest_is_discarded(self) -> None:
        target = self.write("changing.jpg", b"stable bytes")
        self.inventory()
        original_stat = Path.stat
        target_calls = 0

        def changing_stat(path: Path, *args, **kwargs):
            nonlocal target_calls
            state = original_stat(path, *args, **kwargs)
            if path == target:
                target_calls += 1
                if target_calls >= 2:
                    return SimpleNamespace(
                        st_size=state.st_size + 1,
                        st_mtime_ns=state.st_mtime_ns,
                        st_mtime=state.st_mtime,
                    )
            return state

        with mock.patch.object(Path, "stat", changing_stat):
            report = self.hashing("hash-changing")
        self.assertEqual(report.metrics["outcomes"]["changed_during_hash"], 1)
        connection = self.connect()
        self.assertIsNone(connection.execute(
            "SELECT hash_value FROM pipeline_hash_observations"
        ).fetchone()[0])

    def test_python_native_long_path_when_supported(self) -> None:
        relative = "/".join(["long-segment-12345678"] * 12) + "/photo.jpg"
        try:
            path = self.write(relative, b"long")
        except OSError as exc:
            self.skipTest(f"Host does not permit this long path: {exc}")
        report = self.inventory()
        self.assertEqual(report.metrics["media_rows"], 1)
        self.assertGreater(len(str(path)), 260)

    def test_relative_root_policy_and_z_rejection_precede_access(self) -> None:
        prior = Path.cwd()
        try:
            os.chdir(self.base)
            self.assertEqual(validate_root("media"), self.root)
        finally:
            os.chdir(prior)
        with mock.patch.object(Path, "is_dir", side_effect=AssertionError("must not access")):
            with self.assertRaisesRegex(PipelineError, "RETIRED_DRIVE"):
                validate_root(r"Z:\never-access")

    def test_media_extension_policy_is_frozen_and_case_insensitive(self) -> None:
        self.assertEqual(
            MEDIA_EXTENSIONS,
            frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mpg", ".mkv", ".avi", ".3gp"}),
        )
        self.write("upper.JPEG", b"yes")
        report = self.inventory()
        self.assertEqual(report.metrics["media_rows"], 1)

    def test_reconciliation_diff_is_explicit_and_cli_database_is_required(self) -> None:
        self.write("one.jpg", b"one")
        self.inventory()
        report = reconcile_historical_baseline(self.database)
        self.assertFalse(report.matches_baseline)
        self.assertFalse(report.matches["inventory_rows"])
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                build_parser().parse_args([
                    "inventory", "scan", "--job-id", "missing-db",
                    "--source", "Synthetic", "--root", str(self.root),
                ])


if __name__ == "__main__":
    unittest.main()
