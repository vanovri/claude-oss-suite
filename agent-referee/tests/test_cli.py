import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

from agent_referee import cli
from agent_referee.core import (
    LOCKFILE_NAME,
    make_lock_payload,
    scan_test_directory,
    write_lock,
)

TEST_SOURCE = """\
import unittest


class TestSample(unittest.TestCase):
    def test_truth(self):
        self.assertTrue(True)
        self.assertEqual(2 + 2, 4)
"""

WEAKENED_SOURCE = """\
import unittest


class TestSample(unittest.TestCase):
    def test_truth(self):
        self.assertTrue(True)
"""


def quiet(func, *args, **kwargs):
    """Call a CLI function while swallowing its human-readable output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
        io.StringIO()
    ):
        return func(*args, **kwargs)


class TestRefereeCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "tests").mkdir()
        self.test_file = self.root / "tests" / "test_sample.py"
        self.test_file.write_text(TEST_SOURCE, encoding="utf-8")
        self.cmd = f'"{sys.executable}" -m unittest discover -s tests -q'

    def _lock(self):
        return quiet(cli.lock, self.root, "tests", self.cmd)

    def test_lock_creates_baseline_then_verify_passes(self):
        self.assertEqual(self._lock(), cli.EXIT_OK)
        self.assertTrue((self.root / LOCKFILE_NAME).exists())
        self.assertEqual(quiet(cli.verify, self.root), cli.EXIT_OK)

    def test_lock_refuses_missing_test_directory(self):
        self.assertEqual(
            quiet(cli.lock, self.root, "does-not-exist", self.cmd), cli.EXIT_USAGE
        )

    def test_lock_refuses_red_baseline(self):
        failing = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
        self.assertEqual(
            quiet(cli.lock, self.root, "tests", failing), cli.EXIT_TEST_FAILURE
        )
        self.assertFalse((self.root / LOCKFILE_NAME).exists())

    def test_verify_without_lock_is_usage_error(self):
        self.assertEqual(quiet(cli.verify, self.root), cli.EXIT_USAGE)

    def test_verify_detects_weakened_assertions(self):
        self._lock()
        self.test_file.write_text(WEAKENED_SOURCE, encoding="utf-8")
        self.assertEqual(quiet(cli.verify, self.root), cli.EXIT_REWARD_HACK)

    def test_verify_detects_deleted_test_file(self):
        self._lock()
        self.test_file.unlink()
        self.assertEqual(quiet(cli.verify, self.root), cli.EXIT_REWARD_HACK)

    def test_verify_reports_suite_failure(self):
        manifest = scan_test_directory(self.root / "tests")
        failing = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
        write_lock(
            self.root / LOCKFILE_NAME,
            make_lock_payload("tests", failing, manifest, 5.0),
        )
        self.assertEqual(quiet(cli.verify, self.root), cli.EXIT_TEST_FAILURE)

    def test_verify_reports_runtime_regression(self):
        manifest = scan_test_directory(self.root / "tests")
        write_lock(
            self.root / LOCKFILE_NAME,
            make_lock_payload("tests", self.cmd, manifest, 0.001),
        )
        self.assertEqual(
            quiet(cli.verify, self.root, None, 20.0), cli.EXIT_PERF_REGRESSION
        )

    def test_main_wires_argparse_subcommands(self):
        self.assertEqual(
            quiet(cli.main, ["verify", "--root", str(self.root)]), cli.EXIT_USAGE
        )
        self.assertEqual(
            quiet(cli.main, ["lock", "--root", str(self.root), "--tests", "tests",
                             "--cmd", self.cmd]),
            cli.EXIT_OK,
        )
        self.assertEqual(
            quiet(cli.main, ["verify", "--root", str(self.root)]), cli.EXIT_OK
        )


if __name__ == "__main__":
    unittest.main()
