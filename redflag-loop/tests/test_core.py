"""Tests for the loop guard state machine."""

import json
import unittest
from pathlib import Path

from redflag_loop.core import (
    REDFLAG_CODES,
    LoopGuard,
    action_signature,
    normalize_action,
    replay,
    verify_evidence,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

EDIT_A = {"tool": "edit", "path": "src/app.py"}
EDIT_B = {"tool": "edit", "path": "src/util.py"}
TEST = {"tool": "test", "command": "pytest -q"}
GREEN = [{"command": "pytest -q", "exit_code": 0, "output_tail": "12 passed"}]


def load_jsonl(name):
    events = []
    for line in (EXAMPLES / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            events.append(json.loads(line))
    return events


class SignatureTests(unittest.TestCase):
    def test_normalize_sorts_keys_and_strips_space(self):
        self.assertEqual(normalize_action({"b": 1, "a": 2}), '{"a":2,"b":1}')

    def test_signature_ignores_key_order(self):
        self.assertEqual(
            action_signature({"tool": "edit", "path": "a.py"}),
            action_signature({"path": "a.py", "tool": "edit"}),
        )

    def test_signature_is_sixteen_hex_chars(self):
        signature = action_signature(EDIT_A)
        self.assertEqual(len(signature), 16)
        int(signature, 16)  # raises if not hex

    def test_different_actions_have_different_signatures(self):
        self.assertNotEqual(action_signature(EDIT_A), action_signature(EDIT_B))

    def test_normalize_handles_empty_and_odd_values(self):
        self.assertEqual(normalize_action({}), "{}")
        self.assertIn("object", normalize_action({"value": object()}))


class EvidenceTests(unittest.TestCase):
    def test_green_evidence_is_valid(self):
        report = verify_evidence(GREEN)
        self.assertTrue(report["valid"])
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["count"], 1)

    def test_missing_evidence_is_invalid(self):
        self.assertEqual(verify_evidence([])["failures"], ["NO_EVIDENCE"])

    def test_non_zero_exit_code_is_invalid(self):
        failures = verify_evidence([{"command": "pytest -q", "exit_code": 1}])["failures"]
        self.assertIn("EVIDENCE_0_EXIT_1", failures)

    def test_boolean_exit_code_is_rejected(self):
        failures = verify_evidence([{"command": "pytest -q", "exit_code": True}])["failures"]
        self.assertIn("EVIDENCE_0_NO_EXIT_CODE", failures)

    def test_missing_command_and_string_exit_code(self):
        failures = verify_evidence([{"command": "  ", "exit_code": "0"}])["failures"]
        self.assertIn("EVIDENCE_0_NO_COMMAND", failures)
        self.assertIn("EVIDENCE_0_NO_EXIT_CODE", failures)

    def test_non_object_item_is_rejected(self):
        self.assertIn("EVIDENCE_0_NOT_OBJECT", verify_evidence(["pytest"])["failures"])


class LoopDetectionTests(unittest.TestCase):
    def test_third_identical_action_is_blocked(self):
        guard = LoopGuard()
        self.assertTrue(guard.record(TEST)["allowed"])
        self.assertTrue(guard.record(TEST)["allowed"])
        blocked = guard.record(TEST)
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["redflag"]["code"], "LOOP_DETECTED")
        self.assertEqual(blocked["repeat_streak"], 3)
        self.assertIn("change one variable", blocked["reason"])

    def test_alternating_actions_are_not_a_loop(self):
        guard = LoopGuard(max_identical=2, max_iterations_without_progress=10)
        for action in (EDIT_A, EDIT_B, EDIT_A, EDIT_B, EDIT_A):
            self.assertTrue(guard.record(action)["allowed"])
        self.assertEqual(guard.redflags, [])

    def test_streak_resets_after_a_different_action(self):
        guard = LoopGuard(max_identical=3)
        guard.record(EDIT_A)
        guard.record(EDIT_A)
        guard.record(EDIT_B)
        self.assertEqual(guard.record(EDIT_B)["repeat_streak"], 2)

    def test_custom_max_identical_of_two(self):
        guard = LoopGuard(max_identical=2)
        guard.record(TEST)
        self.assertEqual(guard.record(TEST)["redflag"]["code"], "LOOP_DETECTED")

    def test_iteration_budget_is_enforced(self):
        guard = LoopGuard(max_iterations=2)
        guard.record(EDIT_A)
        guard.record(EDIT_B)
        blocked = guard.record(TEST)
        self.assertEqual(blocked["redflag"]["code"], "BUDGET_EXCEEDED")
        self.assertEqual(blocked["iteration"], 3)

    def test_no_progress_after_n_mutations_without_artifacts(self):
        guard = LoopGuard(max_iterations_without_progress=2)
        guard.record(EDIT_A)
        blocked = guard.record(EDIT_B)
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["redflag"]["code"], "NO_PROGRESS")

    def test_read_only_actions_do_not_accrue_progress_debt(self):
        guard = LoopGuard(max_iterations_without_progress=1)
        for index in range(4):
            result = guard.record({"tool": "grep", "pattern": f"x{index}"}, mutation=False)
            self.assertTrue(result["allowed"])
        self.assertEqual(guard.redflags, [])

    def test_new_artifact_resets_progress_counter(self):
        guard = LoopGuard(max_iterations_without_progress=2)
        guard.record(EDIT_A, ["src/app.py"])
        guard.record(TEST)
        self.assertTrue(guard.record(EDIT_B, ["src/util.py"])["allowed"])
        self.assertEqual(guard.redflags, [])

    def test_flag_rejects_unknown_codes(self):
        with self.assertRaises(ValueError):
            LoopGuard().flag("MADE_UP", "nope")

    def test_all_documented_codes_are_accepted(self):
        guard = LoopGuard()
        for code in REDFLAG_CODES:
            self.assertEqual(guard.flag(code, "check")["code"], code)

    def test_constructor_validation(self):
        for kwargs in (
            {"max_identical": 1},
            {"max_iterations": 0},
            {"max_iterations_without_progress": 0},
        ):
            with self.assertRaises(ValueError):
                LoopGuard(**kwargs)


class CompletionTests(unittest.TestCase):
    def test_green_evidence_is_accepted(self):
        guard = LoopGuard()
        guard.record(EDIT_A, ["src/app.py"])
        result = guard.claim_done("T1", GREEN)
        self.assertTrue(result["accepted"])
        self.assertIn("1 passing evidence", result["reason"])
        self.assertIn("T1", guard.status()["completed_tasks"])

    def test_empty_evidence_is_refused(self):
        result = LoopGuard().claim_done("T1", [])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["redflag"]["code"], "UNSUPPORTED_COMPLETION")
        self.assertIn("NO_EVIDENCE", result["evidence_failures"])

    def test_red_test_is_refused(self):
        evidence = [{"command": "pytest -q", "exit_code": 1}]
        result = LoopGuard().claim_done("T1", evidence)
        self.assertFalse(result["accepted"])
        self.assertIn("EVIDENCE_0_EXIT_1", result["evidence_failures"])

    def test_completion_after_loop_is_refused(self):
        guard = LoopGuard()
        for _ in range(3):
            guard.record(TEST)
        result = guard.claim_done("T1", GREEN)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["redflag"]["code"], "REDFLAGS_UNRESOLVED")
        self.assertIn("LOOP_DETECTED", result["reason"])

    def test_completion_requires_a_task_id(self):
        result = LoopGuard().claim_done("  ", GREEN)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["redflag"]["code"], "INVALID_EVENT")

    def test_status_shape(self):
        guard = LoopGuard()
        guard.record(EDIT_A, ["src/app.py"])
        status = guard.status()
        self.assertEqual(status["iterations"], 1)
        self.assertEqual(status["artifacts"], ["src/app.py"])
        self.assertTrue(status["clean"])
        self.assertEqual(status["redflags"], [])


class ReplayTests(unittest.TestCase):
    def test_clean_example_replays_without_redflags(self):
        events = load_jsonl("clean_events.jsonl")
        report = replay(events)
        self.assertTrue(report["clean"])
        self.assertEqual(report["open_codes"], [])
        self.assertEqual(report["events"], len(events))
        self.assertTrue(report["results"][-1]["accepted"])

    def test_loop_example_is_flagged(self):
        report = replay(load_jsonl("loop_events.jsonl"))
        self.assertFalse(report["clean"])
        self.assertIn("LOOP_DETECTED", report["open_codes"])
        self.assertIn("REDFLAGS_UNRESOLVED", report["open_codes"])
        self.assertEqual(report["iterations"], 5)
        self.assertFalse(report["results"][-1]["accepted"])

    def test_unknown_event_type_is_invalid(self):
        report = replay([{"type": "teleport", "action": {}}])
        self.assertEqual(report["open_codes"], ["INVALID_EVENT"])
        self.assertIn("has unknown type", report["redflags"][0]["detail"])

    def test_non_object_event_is_invalid(self):
        report = replay(["not-an-object"])
        self.assertEqual(report["open_codes"], ["INVALID_EVENT"])

    def test_empty_log_is_clean(self):
        report = replay([])
        self.assertTrue(report["clean"])
        self.assertEqual(report["events"], 0)
        self.assertEqual(report["results"], [])

    def test_replay_honours_custom_limits(self):
        events = [{"type": "action", "action": EDIT_A}, {"type": "action", "action": EDIT_A}]
        self.assertTrue(replay(events, max_identical=3)["clean"])
        self.assertFalse(replay(events, max_identical=2)["clean"])

    def test_mutation_false_in_event_is_respected(self):
        events = [
            {"type": "action", "action": {"tool": "read", "path": f"f{i}.py"}, "mutation": False}
            for i in range(6)
        ]
        report = replay(events, max_iterations_without_progress=1)
        self.assertTrue(report["clean"])


if __name__ == "__main__":
    unittest.main()
