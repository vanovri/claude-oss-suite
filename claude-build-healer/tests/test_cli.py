"""End-to-end tests for the build-healer CLI."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from build_healer.cli import main

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "examples"

TSC = (
    "src/app.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.\n"
    "src/app.ts(19,3): warning TS6133: 'debug' is declared but its value is never read.\n"
)
CLEAN = "> tsc --noEmit\n\nFound 0 errors.\n"


def run(argv):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


class PlanCommandTests(unittest.TestCase):
    def test_failing_log_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "build.log"
            log.write_text(TSC, encoding="utf-8")
            code, output = run(["plan", str(log)])
        self.assertEqual(code, 1)
        self.assertIn("TS2322", output)
        self.assertIn("blocking: 1", output)
        self.assertIn("warning", output)

    def test_clean_log_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "build.log"
            log.write_text(CLEAN, encoding="utf-8")
            code, output = run(["plan", str(log)])
        self.assertEqual(code, 0)
        self.assertIn("green", output.lower())

    def test_json_output_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "build.log"
            log.write_text(TSC, encoding="utf-8")
            code, output = run(["plan", str(log), "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertFalse(payload["green"])
        self.assertEqual(payload["targets"][0]["code"], "TS2322")

    def test_max_targets_is_honoured(self):
        text = TSC + "src/app.ts(21,7): error TS2554: Expected 2 arguments, but got 1.\n"
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "build.log"
            log.write_text(text, encoding="utf-8")
            code, output = run(["plan", str(log), "--json", "--max-targets", "1"])
        payload = json.loads(output)
        self.assertEqual(len(payload["targets"]), 1)
        self.assertEqual(payload["total_targets"], 2)
        self.assertEqual(code, 1)

    def test_missing_file_exits_two(self):
        code, output = run(["plan", "does-not-exist.log"])
        self.assertEqual(code, 2)
        self.assertEqual(output, "")

    def test_example_pytest_log_parses(self):
        code, output = run(["plan", str(EXAMPLES / "pytest_failure.log")])
        self.assertEqual(code, 1)
        self.assertIn("test_discount_floor", output)
        self.assertIn("test_total_with_tax", output)


class RoundsCommandTests(unittest.TestCase):
    def test_example_rounds_end_green(self):
        code, output = run(["rounds", str(EXAMPLES / "rounds")])
        self.assertEqual(code, 0)
        self.assertIn("GREEN", output)
        self.assertIn("REPEATED_FAILURE", output)

    def test_rounds_json_reports_status(self):
        code, output = run(["rounds", str(EXAMPLES / "rounds"), "--json"])
        payload = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["rounds"]), 4)
        self.assertTrue(payload["status"]["green"])
        self.assertEqual(payload["status"]["round"], 4)

    def test_red_rounds_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "round1.log").write_text(TSC, encoding="utf-8")
            code, output = run(["rounds", str(directory)])
        self.assertEqual(code, 1)
        self.assertIn("RED", output)

    def test_empty_directory_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["rounds", tmp])
        self.assertEqual(code, 2)

    def test_missing_directory_exits_two(self):
        code, _ = run(["rounds", "no-such-dir"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
