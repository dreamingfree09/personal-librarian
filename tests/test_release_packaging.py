from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_release", REPOSITORY / "packaging/build_release.py"
)
assert SPEC is not None and SPEC.loader is not None
BUILD_RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_RELEASE)


class ReleasePackagingTests(unittest.TestCase):
    def test_canonical_version_matches_all_metadata(self) -> None:
        BUILD_RELEASE.verify_version_metadata(REPOSITORY)

    def test_distribution_selection_is_sorted_and_rejects_catalogues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            distribution = Path(temporary)
            (distribution / "z.txt").write_text("z", encoding="utf-8")
            (distribution / "A.txt").write_text("a", encoding="utf-8")
            files = BUILD_RELEASE.distribution_files(distribution)
            self.assertEqual([path.name for path in files], ["A.txt", "z.txt"])
            (distribution / "private.sqlite3").write_bytes(b"not a catalogue")
            with self.assertRaisesRegex(ValueError, "Catalogue-like"):
                BUILD_RELEASE.distribution_files(distribution)

    def test_archive_has_one_folder_and_normalized_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            distribution = root / "dist"
            distribution.mkdir()
            (distribution / "PersonalLibrarian.exe").write_bytes(b"exe")
            internal = distribution / "_internal"
            internal.mkdir()
            (internal / "runtime.dll").write_bytes(b"dll")
            archive = root / "candidate.zip"
            files = BUILD_RELEASE.distribution_files(distribution)
            BUILD_RELEASE.create_archive(distribution, files, archive)
            with zipfile.ZipFile(archive) as candidate:
                self.assertEqual(
                    candidate.namelist(),
                    [
                        "PersonalLibrarian/_internal/runtime.dll",
                        "PersonalLibrarian/PersonalLibrarian.exe",
                    ],
                )
                self.assertTrue(
                    all(entry.date_time == (1980, 1, 1, 0, 0, 0) for entry in candidate.infolist())
                )
            with self.assertRaises(FileExistsError):
                BUILD_RELEASE.create_archive(distribution, files, archive)


if __name__ == "__main__":
    unittest.main()
