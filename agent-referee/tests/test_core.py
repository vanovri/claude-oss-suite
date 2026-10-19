import tempfile
import unittest
from pathlib import Path

from agent_referee.core import (
    build_lock_manifest,
    count_ast_assertions,
    make_lock_payload,
    read_lock,
    scan_test_directory,
    sha256_text,
    verify_manifest,
    write_lock,
)

TEST_SOURCE = """\
import unittest


class TestSample(unittest.TestCase):
    def test_truth(self):
        self.assertTrue(True)
        self.assertEqual(2 + 2, 4)
"""


class TestAssertionCounter(unittest.TestCase):
    def test_counts_assert_and_assert_methods(self):
        source = (
            "def test_a(self):\n"
            "    assert 1 == 1\n"
            "    self.assertEqual(2, 2)\n"
            "    self.assertTrue(True)\n"
        )
        self.assertEqual(count_ast_assertions(source), 3)

    def test_returns_minus_one_for_broken_syntax(self):
        self.assertEqual(count_ast_assertions("def broken(:\n"), -1)

    def test_counts_nothing_for_docstring_mentions(self):
        source = '"""assert in a docstring is not an assertion."""\n'
        self.assertEqual(count_ast_assertions(source), 0)


class TestManifest(unittest.TestCase):
    def test_manifest_records_hash_assertions_and_size(self):
        manifest = build_lock_manifest({"tests/test_sample.py": TEST_SOURCE})
        entry = manifest["tests/test_sample.py"]
        self.assertEqual(entry["sha256"], sha256_text(TEST_SOURCE))
        self.assertEqual(entry["assertions"], 2)
        self.assertEqual(entry["size_bytes"], len(TEST_SOURCE.encode("utf-8")))

    def test_scan_keys_are_repo_relative_and_skip_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests" / "__pycache__").mkdir(parents=True)
            (root / "tests" / "test_sample.py").write_text(TEST_SOURCE, encoding="utf-8")
            (root / "tests" / "__pycache__" / "junk.py").write_text(
                "assert True\n", encoding="utf-8"
            )
            manifest = scan_test_directory(root / "tests")
            self.assertEqual(list(manifest), ["tests/test_sample.py"])

    def test_lock_payload_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / ".referee_lock.json"
            payload = make_lock_payload(
                "tests", "python -m unittest", build_lock_manifest({"tests/a.py": TEST_SOURCE}), 42.0
            )
            write_lock(lock_path, payload)
            loaded = read_lock(lock_path)
            self.assertEqual(loaded["schema_version"], 1)
            self.assertEqual(loaded["baseline_runtime_ms"], 42.0)
            self.assertIn("tests/a.py", loaded["files"])

    def test_read_lock_rejects_missing_files_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / ".referee_lock.json"
            lock_path.write_text('{"test_dir": "tests"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_lock(lock_path)


class TestVerification(unittest.TestCase):
    def setUp(self):
        self.locked = build_lock_manifest({"tests/test_sample.py": TEST_SOURCE})

    def test_untouched_suite_has_no_violations(self):
        self.assertEqual(verify_manifest(self.locked, self.locked), [])

    def test_deleted_file_is_flagged(self):
        violations = verify_manifest(self.locked, {})
        self.assertTrue(any(v.startswith("DELETED_TEST_FILE") for v in violations))

    def test_weakened_assertions_are_flagged(self):
        tampered = TEST_SOURCE.replace("        self.assertEqual(2 + 2, 4)\n", "")
        current = build_lock_manifest({"tests/test_sample.py": tampered})
        violations = verify_manifest(self.locked, current)
        self.assertTrue(any(v.startswith("MODIFIED_IMMUTABLE_TEST") for v in violations))
        self.assertTrue(any(v.startswith("ASSERTION_WEAKENED") for v in violations))

    def test_unparseable_test_file_is_flagged(self):
        current = build_lock_manifest({"tests/test_sample.py": "def broken(:\n"})
        violations = verify_manifest(self.locked, current)
        self.assertTrue(any(v.startswith("UNPARSEABLE_TEST_FILE") for v in violations))

    def test_runtime_regression_above_budget_is_flagged(self):
        violations = verify_manifest(
            self.locked,
            self.locked,
            baseline_runtime_ms=100.0,
            current_runtime_ms=160.0,
            max_regression_pct=20.0,
        )
        self.assertTrue(any(v.startswith("PERFORMANCE_REGRESSION") for v in violations))

    def test_runtime_inside_budget_passes(self):
        violations = verify_manifest(
            self.locked,
            self.locked,
            baseline_runtime_ms=100.0,
            current_runtime_ms=110.0,
            max_regression_pct=20.0,
        )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
