from __future__ import annotations

import csv
import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import (
    CataloguePathError,
    EvidenceValidationError,
    ReconciliationError,
)
from personal_librarian.catalogue.importers import import_verified_evidence
from personal_librarian.catalogue.importers.m9 import import_m9
from personal_librarian.cli import build_parser


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def write_csv(path: Path, headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


class SyntheticEvidence:
    def __init__(self, root: Path) -> None:
        self.m9 = root / "m9.csv"
        self.m10_manifest = root / "m10-manifest.csv"
        self.m10_groups = root / "m10-groups.csv"
        self.m10_rows = root / "m10-rows.csv"
        self.m11_dualhash = root / "m11-dualhash.csv"
        self.m11_pairs = root / "m11-pairs.csv"
        self.m11_groups = root / "m11-groups.csv"
        self.m11_summary = root / "m11-summary.csv"

        write_csv(
            self.m9,
            ("Source", "RelativePath", "Extension", "SizeBytes", "ModTime"),
            [
                ("OneDrive", r"Photos\cafÃ©.jpg", ".jpg", 100, "2024-01-01T00:00:00Z"),
                ("Dropbox", r"same\a.jpg", ".jpg", 50, "2024-01-02T00:00:00"),
                ("Dropbox", r"same\b.jpg", ".jpg", 50, "2024-01-02T00:00:00"),
                ("GooglePhotos", r"old\niÃ±o.jpg", ".jpg", 70, ""),
                ("HDD_Disk2", r"old\ambiguous-1.jpg", ".jpg", 80, "2024-01-03T00:00:00"),
                ("HDD_Disk2", r"old\ambiguous-2.jpg", ".jpg", 80, "2024-01-03T00:00:00"),
            ],
        )
        manifest_rows = [
            ("OneDrive", r"Photos\café.jpg", r"C:\OneDrive\Photos\café.jpg", ".jpg", 100, "2024-01-01T00:00:00Z", SHA_B, "Hashed"),
            ("Dropbox", r"same\a.jpg", r"C:\Dropbox\same\a.jpg", ".jpg", 50, "2024-01-02T00:00:00", SHA_A, "Hashed"),
            ("Dropbox", r"same\b.jpg", r"C:\Dropbox\same\b.jpg", ".jpg", 50, "2024-01-02T00:00:00", SHA_A, "Hashed"),
            ("GooglePhotos", r"new\niño.jpg", r"C:\Google\new\niño.jpg", ".jpg", 70, "", SHA_C, "Hashed"),
            ("HDD_Disk2", r"new\ambiguous-a.jpg", r"D:\new\ambiguous-a.jpg", ".jpg", 80, "2024-01-03T00:00:00", SHA_D, "Hashed"),
            ("HDD_Disk2", r"new\ambiguous-b.jpg", r"D:\new\ambiguous-b.jpg", ".jpg", 80, "2024-01-03T00:00:00", SHA_E, "Hashed"),
        ]
        write_csv(
            self.m10_manifest,
            ("Source", "RelativePath", "AbsolutePath", "Extension", "SizeBytes", "ModTime", "SHA256", "HashStatus"),
            manifest_rows,
        )
        write_csv(
            self.m10_groups,
            ("SHA256", "Copies", "UniqueSources", "SourcePattern", "SizeBytes", "RedundantCopies", "ReclaimableBytes"),
            [(SHA_A, 2, 1, "Dropbox", 50, 1, 50)],
        )
        write_csv(
            self.m10_rows,
            ("SHA256", "Copies", "Source", "RelativePath", "SizeBytes"),
            [
                (SHA_A, 2, "Dropbox", r"same\a.jpg", 50),
                (SHA_A, 2, "Dropbox", r"same\b.jpg", 50),
            ],
        )
        write_csv(
            self.m11_dualhash,
            ("SHA256", "PHash", "RepresentativePath", "Source", "Copies", "DHash", "DHashStatus", "DHashError"),
            [
                (SHA_A, "0000000000000000", r"same\a.jpg", "Dropbox", 2, "0000000000000000", "Hashed", ""),
                (SHA_B, "0000000000000001", r"Photos\café.jpg", "OneDrive", 1, "0000000000000003", "Hashed", ""),
            ],
        )
        pair = (
            1, SHA_A, SHA_B, "0000000000000000", "0000000000000001",
            "Dropbox", "OneDrive", 2, 1, r"same\a.jpg", r"Photos\café.jpg",
            "0000000000000000", "0000000000000003", 2,
        )
        pair_headers = (
            "Distance", "SHA256_A", "SHA256_B", "PHash_A", "PHash_B", "Source_A", "Source_B",
            "Copies_A", "Copies_B", "RepresentativePath_A", "RepresentativePath_B",
            "DHash_A", "DHash_B", "DHashDistance",
        )
        write_csv(self.m11_pairs, pair_headers, [pair])
        write_csv(self.m11_groups, pair_headers + ("GroupID",), [pair + ("G0001",)])
        write_csv(
            self.m11_summary,
            ("GroupID", "UniqueContents", "CandidatePairs", "MinPHashDistance", "MaxPHashDistance", "MinDHashDistance", "MaxDHashDistance", "UniqueSources", "Sources"),
            [("G0001", 2, 1, 1, 1, 2, 2, 2, "Dropbox|OneDrive")],
        )

    @property
    def baselines(self) -> dict[str, dict[str, object]]:
        return {
            "m9": {
                "rows": 6,
                "bytes": 430,
                "source_counts": {
                    "Dropbox": 2, "GooglePhotos": 1, "HDD_Disk2": 2, "OneDrive": 1,
                },
            },
            "m10": {
                "manifest_rows": 6, "valid_sha256": 6, "invalid_sha256": 0,
                "physical_instances_mapped": 6, "exact_duplicate_groups": 1,
                "duplicate_memberships": 2, "redundant_copies": 1,
                "reclaimable_bytes": 50,
            },
            "m11": {
                "unique_dualhash_contents": 2, "phashed_physical_copies": 3,
                "dhash_coverage": 2, "similarity_pairs": 1, "review_groups": 1,
                "unique_group_contents": 2, "largest_group": 2,
                "groups_over_20": 0, "groups_over_50": 0,
            },
        }

    def kwargs(self, database: Path) -> dict[str, object]:
        return {
            "database_path": database,
            "m9_path": self.m9,
            "m10_manifest_path": self.m10_manifest,
            "m10_groups_path": self.m10_groups,
            "m10_rows_path": self.m10_rows,
            "m11_dualhash_path": self.m11_dualhash,
            "m11_pairs_path": self.m11_pairs,
            "m11_groups_path": self.m11_groups,
            "m11_summary_path": self.m11_summary,
            "baselines": self.baselines,
        }


class EvidenceImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.database = self.root / "catalogue.sqlite3"
        self.evidence = SyntheticEvidence(self.root)

    def connect(self) -> sqlite3.Connection:
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.addCleanup(connection.close)
        return connection

    def test_full_import_reconciles_and_rerun_is_idempotent(self) -> None:
        first = import_verified_evidence(**self.evidence.kwargs(self.database))
        second = import_verified_evidence(**self.evidence.kwargs(self.database))
        self.assertTrue(first.matches_baselines)
        self.assertTrue(all(stage.skipped_existing for stage in second.stages))
        connection = self.connect()
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM physical_instances").fetchone()[0], 6)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM content_identities").fetchone()[0], 5)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM similarity_relationships").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence_import_stages").fetchone()[0], 3)

    def test_unicode_repair_precedence_matching_and_timestamp_state(self) -> None:
        report = import_verified_evidence(**self.evidence.kwargs(self.database))
        m10_metrics = report.stages[1].metrics
        self.assertEqual(m10_metrics["m9_exact_path_links"], 2)
        self.assertEqual(m10_metrics["m9_unique_metadata_links"], 2)
        self.assertEqual(m10_metrics["m9_unlinked_observations"], 2)
        connection = self.connect()
        raw_paths = {
            row[0] for row in connection.execute("SELECT raw_relative_path FROM inventory_observations")
        }
        current_paths = {
            row[0] for row in connection.execute("SELECT raw_relative_path FROM physical_instances")
        }
        self.assertIn(r"Photos\cafÃ©.jpg", raw_paths)
        self.assertIn(r"Photos\café.jpg", current_paths)
        states = {
            row[0] for row in connection.execute("SELECT DISTINCT timestamp_state FROM inventory_observations")
        }
        self.assertEqual(states, {"aware", "naive", "missing"})

    def test_reconciliation_mismatch_rolls_back_entire_stage(self) -> None:
        initialise_catalogue(self.database)
        connection = self.connect()
        wrong = dict(self.evidence.baselines["m9"])
        wrong["rows"] = 999
        with self.assertRaises(ReconciliationError) as captured:
            import_m9(connection, self.evidence.m9, baseline=wrong)
        self.assertFalse(captured.exception.report.matches_baseline)
        self.assertFalse(captured.exception.report.matches["rows"])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM inventory_observations").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence_import_stages").fetchone()[0], 0)

    def test_malformed_csv_rolls_back_and_z_path_is_rejected_before_access(self) -> None:
        initialise_catalogue(self.database)
        connection = self.connect()
        malformed = self.root / "malformed.csv"
        write_csv(
            malformed,
            ("Source", "RelativePath", "Extension", "SizeBytes", "ModTime"),
            [("OneDrive", "bad.jpg", ".jpg", "not-an-integer", "")],
        )
        with self.assertRaises(EvidenceValidationError):
            import_m9(connection, malformed, baseline={"rows": 1})
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM inventory_observations").fetchone()[0], 0)
        with self.assertRaises(CataloguePathError):
            import_m9(connection, r"Z:\never-access.csv", baseline={})

    def test_import_cli_requires_explicit_database(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args([
                    "catalogue", "import-evidence", "--m9", str(self.evidence.m9)
                ])


if __name__ == "__main__":
    unittest.main()
