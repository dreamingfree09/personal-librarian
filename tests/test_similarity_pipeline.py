from __future__ import annotations

import os
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, PngImagePlugin

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.pipeline.common import PipelineInterrupted
from personal_librarian.pipeline.hashing import run_sha256
from personal_librarian.pipeline.inventory import run_inventory
from personal_librarian.pipeline.perceptual_hashing import (
    calculate_dhash,
    calculate_phash,
    run_perceptual_hashing,
)
from personal_librarian.pipeline.similarity import (
    dual_hash_accepts,
    run_similarity_analysis,
)
from personal_librarian.pipeline.similarity_groups import (
    connected_components,
    review_tier,
    run_similarity_groups,
)


class SimilarityPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        self.root = self.base / "media"
        self.root.mkdir()
        self.database = self.base / "catalogue.sqlite3"

    def patterned_image(self, width: int = 37, height: int = 29) -> Image.Image:
        image = Image.new("RGB", (width, height))
        pixels = image.load()
        assert pixels is not None
        for y in range(height):
            for x in range(width):
                pixels[x, y] = ((x * 7 + y * 3) % 256, (x * 2) % 256, (y * 9) % 256)
        return image

    def save_png(self, relative: str, image: Image.Image, marker: str | None = None) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pnginfo = None
        if marker is not None:
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_text("marker", marker)
        image.save(path, format="PNG", pnginfo=pnginfo)
        return path

    def prepare_exact_catalogue(self) -> None:
        run_inventory(
            database_path=self.database,
            job_id="inventory",
            source="Synthetic",
            root=self.root,
        )
        run_sha256(
            database_path=self.database,
            job_id="sha256",
            inventory_job_id="inventory",
            source="Synthetic",
            root=self.root,
        )

    def connect(self):
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.addCleanup(connection.close)
        return connection

    def test_deterministic_hashes_match_reference_values(self) -> None:
        image = self.patterned_image()
        self.assertEqual(calculate_phash(image), "9225ab3aaa3aab3a")
        self.assertEqual(calculate_dhash(image), "fffefefcfcfdf9f9")
        self.assertEqual(calculate_phash(image), calculate_phash(image.copy()))
        self.assertEqual(calculate_dhash(image), calculate_dhash(image.copy()))

    def test_exact_identity_is_hashed_once_and_similar_distinct_content_stays_separate(self) -> None:
        image = self.patterned_image()
        first = self.save_png("copy-a.png", image)
        second = self.root / "copy-b.png"
        second.write_bytes(first.read_bytes())
        self.save_png("visually-same-byte-different.png", image, marker="different bytes")
        initial_states = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.iterdir()
        }
        self.prepare_exact_catalogue()

        hash_report = run_perceptual_hashing(
            database_path=self.database, job_id="perceptual"
        )
        analysis_report = run_similarity_analysis(
            database_path=self.database,
            job_id="analysis",
            hash_job_id="perceptual",
        )
        group_report = run_similarity_groups(
            database_path=self.database,
            job_id="groups",
            analysis_job_id="analysis",
        )
        self.assertEqual(hash_report.metrics["candidate_content_identities"], 2)
        self.assertEqual(hash_report.metrics["phash_successes"], 2)
        self.assertEqual(hash_report.metrics["phashed_physical_copies_represented"], 3)
        self.assertEqual(analysis_report.metrics["accepted_dual_hash_pairs"], 1)
        self.assertEqual(group_report.metrics["review_groups"], 1)
        self.assertEqual(group_report.metrics["grouped_unique_contents"], 2)

        connection = self.connect()
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM content_hash_observations "
                "WHERE analysis_run_id = (SELECT analysis_run_id FROM similarity_pipeline_jobs "
                "WHERE job_id = 'perceptual') AND algorithm = 'pHash'"
            ).fetchone()[0],
            2,
        )
        relation = connection.execute(
            """
            SELECT left_content_identity_id, right_content_identity_id,
                   phash_distance, dhash_distance, relationship_key
            FROM similarity_relationships
            """
        ).fetchone()
        self.assertLess(relation[0], relation[1])
        self.assertNotEqual(relation[0], relation[1])
        self.assertEqual((relation[2], relation[3]), (0, 0))
        self.assertTrue(str(relation[4]).startswith("m16-similarity-relationship-v1:"))
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM content_identities").fetchone()[0], 2)
        for path, state in initial_states.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state)

    def test_thresholds_combined_rule_and_grouping_flags(self) -> None:
        accepted = dual_hash_accepts(
            "0000000000000000", "000000000000000f",
            "0000000000000000", "000000000000000f",
        )
        phash_rejected = dual_hash_accepts(
            "0000000000000000", "000000000000001f",
            "0000000000000000", "0000000000000001",
        )
        dhash_rejected = dual_hash_accepts(
            "0000000000000000", "0000000000000001",
            "0000000000000000", "000000000000001f",
        )
        self.assertEqual(accepted, (True, 4, 4))
        self.assertEqual(phash_rejected, (False, 5, 1))
        self.assertEqual(dhash_rejected, (False, 1, 5))
        self.assertEqual(connected_components([(3, 4), (1, 2), (2, 3), (10, 11)]), [(1, 2, 3, 4), (10, 11)])
        self.assertEqual(review_tier(20), "review_only")
        self.assertEqual(review_tier(21), "large_low_confidence_review_only")
        self.assertEqual(review_tier(51), "very_large_low_confidence_review_only")

    def test_invalid_zero_byte_unicode_and_normalization_variants_are_isolated(self) -> None:
        image = self.patterned_image()
        greek = self.save_png("φωτογραφίες/εικόνα.png", image)
        composed = "café.png"
        decomposed = unicodedata.normalize("NFD", composed)
        self.save_png(composed, image, marker="nfc")
        self.save_png(decomposed, image, marker="nfd")
        (self.root / "invalid.jpg").write_bytes(b"not an image")
        (self.root / "empty.png").write_bytes(b"")
        self.prepare_exact_catalogue()
        report = run_perceptual_hashing(
            database_path=self.database, job_id="perceptual-errors"
        )
        self.assertEqual(report.metrics["candidate_content_identities"], 5)
        self.assertEqual(report.metrics["phash_successes"], 3)
        self.assertEqual(report.metrics["phash_errors"], 2)
        self.assertEqual(report.metrics["outcomes"]["decode_error"], 1)
        self.assertEqual(report.metrics["outcomes"]["zero_byte"], 1)
        connection = self.connect()
        paths = {
            str(row[0])
            for row in connection.execute(
                "SELECT representative_path FROM content_hash_observations "
                "WHERE analysis_run_id = (SELECT analysis_run_id FROM similarity_pipeline_jobs "
                "WHERE job_id = 'perceptual-errors')"
            )
        }
        self.assertIn(str(greek.relative_to(self.root)), paths)
        self.assertIn(composed, paths)
        self.assertIn(decomposed, paths)

    def test_idempotency_reuse_resume_and_versioned_contexts(self) -> None:
        self.save_png("a.png", self.patterned_image(), marker="a")
        self.save_png("b.png", self.patterned_image(), marker="b")
        self.save_png("c.png", self.patterned_image(), marker="c")
        self.prepare_exact_catalogue()
        with self.assertRaises(PipelineInterrupted):
            run_perceptual_hashing(
                database_path=self.database,
                job_id="perceptual-resume",
                interrupt_after=1,
            )
        resumed = run_perceptual_hashing(
            database_path=self.database, job_id="perceptual-resume"
        )
        rerun = run_perceptual_hashing(
            database_path=self.database, job_id="perceptual-resume"
        )
        reused = run_perceptual_hashing(
            database_path=self.database, job_id="perceptual-reuse"
        )
        versioned = run_perceptual_hashing(
            database_path=self.database,
            job_id="perceptual-version-2",
            hash_suite_version="m16-test-version-2",
        )
        self.assertEqual(resumed.metrics, rerun.metrics)
        self.assertEqual(resumed.metrics["phash_successes"], 3)
        self.assertEqual(reused.metrics["outcomes"]["reused"], 3)
        self.assertEqual(versioned.metrics["outcomes"]["success"], 3)

        with self.assertRaises(PipelineInterrupted):
            run_similarity_analysis(
                database_path=self.database,
                job_id="analysis-resume",
                hash_job_id="perceptual-resume",
                interrupt_after=1,
            )
        analysis_resumed = run_similarity_analysis(
            database_path=self.database,
            job_id="analysis-resume",
            hash_job_id="perceptual-resume",
        )
        analysis_rerun = run_similarity_analysis(
            database_path=self.database,
            job_id="analysis-resume",
            hash_job_id="perceptual-resume",
        )
        self.assertEqual(analysis_resumed.metrics, analysis_rerun.metrics)
        self.assertEqual(analysis_resumed.metrics["accepted_dual_hash_pairs"], 3)

        with self.assertRaises(PipelineInterrupted):
            run_similarity_groups(
                database_path=self.database,
                job_id="groups-resume",
                analysis_job_id="analysis-resume",
                interrupt_after=1,
            )
        groups_resumed = run_similarity_groups(
            database_path=self.database,
            job_id="groups-resume",
            analysis_job_id="analysis-resume",
        )
        groups_rerun = run_similarity_groups(
            database_path=self.database,
            job_id="groups-resume",
            analysis_job_id="analysis-resume",
        )
        self.assertEqual(groups_resumed.metrics, groups_rerun.metrics)
        self.assertEqual(groups_resumed.metrics["review_groups"], 1)

        connection = self.connect()
        versions = {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT algorithm_version FROM content_hash_observations "
                "WHERE algorithm = 'pHash'"
            )
        }
        self.assertEqual(len(versions), 2)

    def test_z_catalogued_path_is_rejected_before_image_open(self) -> None:
        self.save_png("safe.png", self.patterned_image())
        self.prepare_exact_catalogue()
        connection = self.connect()
        connection.execute(
            "UPDATE physical_instances SET current_observed_path = ?",
            (r"Z:\never-access.png",),
        )
        connection.commit()
        connection.close()
        with mock.patch.object(Image, "open", side_effect=AssertionError("must not open")):
            with self.assertRaisesRegex(PipelineError, "RETIRED_DRIVE"):
                run_perceptual_hashing(
                    database_path=self.database, job_id="perceptual-z"
                )


if __name__ == "__main__":
    unittest.main()
