"""Tests for the CLI contract: exit codes, JSON output and Merkle command."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from open_dmrv.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PASS_FILE = str(EXAMPLES / "batches_pass.json")
FAIL_FILE = str(EXAMPLES / "batches_fail.json")


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


SOFT_ONLY = {
    "batches": [
        {
            "batch_id": "SLOW-SOFT",
            "process": "slow",
            "feedstock_kg": 1000,
            "biochar_kg": 700,
            "syngas_kg": 290,
            "bio_oil_kg": 0,
            "peak_temp_c": 480,
            "residence_min": 60,
            "h_c_org": 0.4,
            "moisture_pct": 21,
        }
    ]
}


class VerifyExitCodeTests(unittest.TestCase):
    def test_clean_bundle_exits_zero(self):
        code, out, err = run("verify", PASS_FILE)
        self.assertEqual(code, 0)
        self.assertIn("bundle: signable", out)
        self.assertEqual(err, "")

    def test_violating_bundle_exits_one(self):
        code, out, err = run("verify", FAIL_FILE)
        self.assertEqual(code, 1)
        self.assertIn("NOT signable (blocked)", out)
        self.assertEqual(err, "")

    def test_missing_file_exits_two(self):
        code, out, err = run("verify", "does-not-exist.json")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("not found", err)

    def test_malformed_json_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{oops", encoding="utf-8")
            code, _, err = run("verify", str(path))
        self.assertEqual(code, 2)
        self.assertIn("invalid JSON", err)

    def test_empty_batch_file_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text("[]", encoding="utf-8")
            code, _, err = run("verify", str(path))
        self.assertEqual(code, 2)
        self.assertIn("no batches", err)


class JsonOutputTests(unittest.TestCase):
    def test_json_report_matches_the_library_shape(self):
        code, out, _ = run("verify", PASS_FILE, "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["status"], "pass")
        self.assertTrue(data["signable"])
        self.assertEqual(data["batch_count"], 3)
        self.assertEqual(data["passed"], 3)
        self.assertEqual(len(data["reports"]), 3)
        self.assertRegex(data["merkle_root"], r"^[0-9a-f]{64}$")

    def test_json_report_is_emitted_even_when_blocked(self):
        code, out, _ = run("verify", FAIL_FILE, "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["status"], "blocked")
        self.assertFalse(data["signable"])
        self.assertIn("MASS_BALANCE", data["violations"])
        self.assertEqual(data["reports"][0]["batch_id"], "SLOW-BAD-01")


class MerkleCommandTests(unittest.TestCase):
    def test_merkle_matches_verify(self):
        merkle_code, merkle_out, _ = run("merkle", PASS_FILE)
        verify_code, verify_out, _ = run("verify", PASS_FILE, "--json")
        self.assertEqual((merkle_code, verify_code), (0, 0))
        self.assertEqual(merkle_out.strip(), json.loads(verify_out)["merkle_root"])

    def test_merkle_json_reports_the_leaf_count(self):
        code, out, _ = run("merkle", PASS_FILE, "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["leaf_count"], 3)
        self.assertRegex(data["merkle_root"], r"^[0-9a-f]{64}$")

    def test_merkle_is_order_sensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(Path(PASS_FILE).read_text(encoding="utf-8"))
            reversed_path = Path(tmp) / "reversed.json"
            payload["batches"].reverse()
            reversed_path.write_text(json.dumps(payload), encoding="utf-8")
            _, first, _ = run("merkle", PASS_FILE)
            _, second, _ = run("merkle", str(reversed_path))
        self.assertNotEqual(first, second)


class AllowReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "soft.json"
        self.path.write_text(json.dumps(SOFT_ONLY), encoding="utf-8")

    def test_soft_failures_exit_one_without_the_flag(self):
        code, out, _ = run("verify", str(self.path))
        self.assertEqual(code, 1)
        self.assertIn("NOT signable (review)", out)

    def test_soft_failures_exit_zero_with_the_flag(self):
        code, _, _ = run("verify", str(self.path), "--allow-review")
        self.assertEqual(code, 0)

    def test_hard_failures_still_exit_one_with_the_flag(self):
        code, _, _ = run("verify", FAIL_FILE, "--allow-review")
        self.assertEqual(code, 1)


class ArgumentTests(unittest.TestCase):
    def test_missing_command_is_a_usage_error(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_unknown_command_is_a_usage_error(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main(["audit", PASS_FILE])
        self.assertEqual(ctx.exception.code, 2)

    def test_version_flag(self):
        with redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("0.1.0", out.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
