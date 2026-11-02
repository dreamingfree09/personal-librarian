"""The diagnostic observer must preserve failures after a successful summary."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from diagnose_test_process import run_child


class ProcessExitTests(unittest.TestCase):
    def test_ok_summary_cannot_override_nonzero_process_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_child([
                sys.executable, "-u", "-c",
                "import sys; print('OK', file=sys.stderr); raise SystemExit(1)",
            ], Path(temporary) / "run")
            self.assertEqual(result["returncode"], 1)
            self.assertEqual(result["summary"], ["OK"])

    def test_clean_exit_and_separate_streams_are_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            result = run_child([
                sys.executable, "-u", "-c",
                "import sys; print('stdout'); print('stderr', file=sys.stderr)",
            ], root)
            self.assertEqual(result["returncode"], 0)
            self.assertFalse(result["timed_out"])
            self.assertGreater(result["pid"], 0)
            self.assertEqual((root / "stdout.log").read_text().strip(), "stdout")
            self.assertEqual((root / "stderr.log").read_text().strip(), "stderr")

    def test_timeout_is_a_failed_process_and_retains_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            result = run_child([sys.executable, "-c", "import time; time.sleep(30)"],
                               root, timeout=0.2)
            self.assertTrue(result["timed_out"])
            self.assertNotEqual(result["returncode"], 0)
            self.assertTrue((root / "started.json").is_file())
            self.assertTrue((root / "result.json").is_file())
