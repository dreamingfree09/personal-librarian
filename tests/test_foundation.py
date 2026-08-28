from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.cli import main
from personal_librarian.config import ConfigError, load_config
from personal_librarian.jobs import RunContext
from personal_librarian.safety import (
    OperationMode,
    PathIntent,
    PathSafetyPolicy,
    assess_operation,
)


class PathSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = PathSafetyPolicy()

    def test_rejects_retired_uppercase_drive_without_access(self) -> None:
        result = self.policy.check_path(r"Z:\PersonalLibrary\photo.jpg", intent=PathIntent.READ)
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "RETIRED_DRIVE")

    def test_rejects_retired_lowercase_drive_without_access(self) -> None:
        result = self.policy.check_path("z:/anything", intent=PathIntent.WRITE)
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "RETIRED_DRIVE")

    def test_accepts_safe_non_retired_drive(self) -> None:
        result = self.policy.check_path(r"C:\safe\example.txt", intent=PathIntent.READ)
        self.assertTrue(result.allowed)
        self.assertEqual(result.assessed_path, r"C:\safe\example.txt")

    def test_resolves_relative_path_lexically_against_safe_base(self) -> None:
        result = self.policy.check_path("reports\\item.csv", intent=PathIntent.READ, base_path=r"H:\workspace")
        self.assertTrue(result.allowed)
        self.assertEqual(result.assessed_path, r"H:\workspace\reports\item.csv")

    def test_rejects_relative_path_when_base_is_retired(self) -> None:
        result = self.policy.check_path("item.csv", intent=PathIntent.READ, base_path=r"z:\workspace")
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "RETIRED_DRIVE")

    def test_accepts_valid_unc_and_rejects_malformed_unc(self) -> None:
        self.assertTrue(
            self.policy.check_path(r"\\server\share\folder", intent=PathIntent.READ).allowed
        )
        malformed = self.policy.check_path(r"\\server", intent=PathIntent.READ)
        self.assertFalse(malformed.allowed)
        self.assertEqual(malformed.code, "MALFORMED_UNC_PATH")


class OperationModeTests(unittest.TestCase):
    def test_read_only_and_dry_run_allow_reads_but_not_writes(self) -> None:
        for mode in (OperationMode.READ_ONLY, OperationMode.DRY_RUN):
            self.assertTrue(assess_operation(mode, PathIntent.READ).allowed)
            self.assertFalse(assess_operation(mode, PathIntent.WRITE).allowed)

    def test_action_mode_is_unavailable(self) -> None:
        decision = assess_operation(OperationMode.ACTION, PathIntent.WRITE)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "ACTION_MODE_UNAVAILABLE")


class RunContextTests(unittest.TestCase):
    def test_run_ids_are_valid_and_unique(self) -> None:
        first = RunContext.create()
        second = RunContext.create()
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(str(UUID(first.run_id)), first.run_id)


class ConfigTests(unittest.TestCase):
    def test_defaults_are_unset_and_safe(self) -> None:
        config = load_config(None)
        self.assertIsNone(config.project_root)
        self.assertIsNone(config.data_root)

    def test_loads_valid_typed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[paths]\nproject_root = "C:\\\\project"\ndata_root = "H:\\\\data"\n', encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.project_root, r"C:\project")
        self.assertEqual(config.data_root, r"H:\data")

    def test_rejects_relative_and_retired_roots(self) -> None:
        for value in ("relative\\data", "Z:\\\\PersonalLibrary"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.toml"
                escaped = value.replace("\\", "\\\\")
                path.write_text(f'[paths]\ndata_root = "{escaped}"\n', encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_rejects_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[paths]\nsecret_root = "C:\\\\unexpected"\n', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)


class CliSmokeTests(unittest.TestCase):
    def test_version_command(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(["version"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Personal Librarian 0.1.0", stdout.getvalue())

    def test_doctor_does_not_require_configuration(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(["doctor"])
        self.assertEqual(exit_code, 0)
        self.assertIn("PASS retired-z-policy: RETIRED_DRIVE", stdout.getvalue())

    def test_cli_rejects_retired_path(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(["safety", "check-path", r"Z:\do-not-access"])
        self.assertEqual(exit_code, 2)
        self.assertIn("path_code: RETIRED_DRIVE", stdout.getvalue())


class HistoricalScriptGuardTests(unittest.TestCase):
    def test_guard_precedes_historical_script_body(self) -> None:
        script = REPOSITORY_ROOT / "scripts" / "Invoke-M5OneDriveAcquisition.ps1"
        text = script.read_text(encoding="utf-8")
        self.assertLess(text.index("M5_RETIRED_GUARD"), text.index("$roots = @("))
        self.assertLess(text.index("M5_RETIRED_GUARD"), text.index("CreateDirectory($auditDir)"))

    def test_script_exits_at_retired_guard(self) -> None:
        executable = (
            shutil.which("powershell.exe")
            or shutil.which("powershell")
            or shutil.which("pwsh")
        )
        if executable is None:
            self.skipTest("PowerShell is not available")
        script = REPOSITORY_ROOT / "scripts" / "Invoke-M5OneDriveAcquisition.ps1"
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-File", str(script)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("M5_RETIRED_GUARD", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
