"""Tests for the ``redflag-loop`` CLI (exit codes, JSON output, bad input)."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from redflag_loop.cli import (
    EXIT_BAD_INPUT,
    EXIT_CLEAN,
    EXIT_REDFLAG,
    load_events,
    main,
    render_summary,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"


def run(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
    def test_clean_log_exits_zero(self):
        code, out, err = run(["check", str(EXAMPLES / "clean_events.jsonl")])
        self.assertEqual(code, EXIT_CLEAN)
        self.assertIn("status: CLEAN", out)
        self.assertIn("accepted", out)
        self.assertEqual(err, "")

    def test_loop_log_exits_one(self):
        code, out, _ = run(["check", str(EXAMPLES / "loop_events.jsonl")])
        self.assertEqual(code, EXIT_REDFLAG)
        self.assertIn("REDFLAGS", out)
        self.assertIn("LOOP_DETECTED", out)
        self.assertIn("REDFLAGS_UNRESOLVED", out)

    def test_json_output_is_machine_readable(self):
        code, out, _ = run(["check", str(EXAMPLES / "loop_events.jsonl"), "--json"])
        self.assertEqual(code, EXIT_REDFLAG)
        report = json.loads(out)
        self.assertFalse(report["clean"])
        self.assertIn("LOOP_DETECTED", report["open_codes"])
        self.assertEqual(len(report["results"]), 6)

    def test_custom_limits_change_the_verdict(self):
        code, out, _ = run(
            [
                "check",
                str(EXAMPLES / "clean_events.jsonl"),
                "--max-iterations",
                "2",
                "--json",
            ]
        )
        self.assertEqual(code, EXIT_REDFLAG)
        self.assertIn("BUDGET_EXCEEDED", json.loads(out)["open_codes"])

    def test_missing_file_exits_two(self):
        code, out, err = run(["check", "does-not-exist.jsonl"])
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertEqual(out, "")
        self.assertIn("redflag-loop:", err)

    def test_invalid_json_reports_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "broken.jsonl"
            target.write_text('{"type": "action"}\n{oops\n', encoding="utf-8")
            code, _, err = run(["check", str(target)])
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn(":2:", err)
        self.assertIn("invalid JSON", err)

    def test_load_events_skips_comments_and_blanks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "log.jsonl"
            target.write_text('\n# comment\n{"type": "action"}\n\n', encoding="utf-8")
            events = load_events(str(target))
        self.assertEqual(events, [{"type": "action"}])

    def test_missing_subcommand_exits_via_argparse(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main([])
        self.assertEqual(caught.exception.code, 2)

    def test_render_summary_lists_refusals(self):
        report = {
            "events": 1,
            "iterations": 1,
            "clean": False,
            "open_codes": ["LOOP_DETECTED"],
            "redflags": [{"code": "LOOP_DETECTED", "iteration": 1, "detail": "x"}],
            "results": [{"allowed": False, "redflag": {"code": "LOOP_DETECTED"}}],
        }
        text = render_summary(report)
        self.assertIn("[LOOP_DETECTED]", text)
        self.assertIn("event 0: LOOP_DETECTED", text)


if __name__ == "__main__":
    unittest.main()
