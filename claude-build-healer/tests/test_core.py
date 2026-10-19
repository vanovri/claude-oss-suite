"""Behavioural tests for the bounded healing loop."""

import unittest

from build_healer.core import (
    HEAL_CODES,
    HealLoop,
    Target,
    build_plan,
)
from build_healer.parsers import Failure, parse_log

APP_ERROR = "src/app.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'."
CLIENT_ERROR = "src/api/client.ts(40,18): error TS2345: Argument of type '{ id: string; }' is not assignable to parameter of type 'Request'."
CLEAN = "> tsc --noEmit\n\nFound 0 errors.\n"


def observe(loop, *lines):
    return loop.observe(log_text="\n".join(lines) + "\n")


class BuildPlanTests(unittest.TestCase):
    def test_green_plan(self):
        plan = build_plan([])
        self.assertTrue(plan["green"])
        self.assertEqual(plan["targets"], [])
        self.assertIn("green", plan["advice"].lower())

    def test_duplicates_collapse_into_one_target(self):
        plan = build_plan(parse_log(APP_ERROR + "\n" + APP_ERROR))
        self.assertEqual(len(plan["targets"]), 1)
        self.assertEqual(plan["summary"]["blocking"], 1)

    def test_warnings_are_advisory_not_blocking(self):
        plan = build_plan(parse_log("src/app.ts(19,3): warning TS6133: 'debug' is never read."))
        self.assertTrue(plan["green"])
        self.assertEqual(len(plan["advisory"]), 1)

    def test_max_targets_truncates_but_reports_total(self):
        plan = build_plan(parse_log(APP_ERROR + "\n" + CLIENT_ERROR), max_targets=1)
        self.assertEqual(len(plan["targets"]), 1)
        self.assertEqual(plan["total_targets"], 2)

    def test_advice_points_at_the_hotspot(self):
        plan = build_plan(parse_log(APP_ERROR + "\n" + APP_ERROR.replace("2322", "2323")))
        self.assertIn("src/app.ts", plan["advice"])

    def test_target_hint_is_actionable(self):
        target = Target(Failure(tool="tsc", file="src/app.ts", line=12, message="mismatch"))
        hint = target.hint()
        self.assertIn("src/app.ts:12", hint)
        self.assertIn("tsc", hint)


class HealLoopStartTests(unittest.TestCase):
    def test_first_round_requests_another_round(self):
        loop = HealLoop()
        result = observe(loop, APP_ERROR, CLIENT_ERROR)
        self.assertEqual(result["round"], 1)
        self.assertFalse(result["green"])
        self.assertTrue(result["should_continue"])
        self.assertEqual(len(result["targets"]), 2)
        self.assertEqual(result["escalations"], [])
        self.assertTrue(result["advice"])

    def test_duplicate_lines_do_not_double_count_attempts(self):
        loop = HealLoop()
        observe(loop, APP_ERROR, APP_ERROR, APP_ERROR)
        self.assertEqual(len(loop.targets), 1)
        self.assertEqual(next(iter(loop.targets.values())).attempts, 1)

    def test_clean_first_round_is_green(self):
        result = observe(HealLoop(), CLEAN)
        self.assertTrue(result["green"])
        self.assertFalse(result["should_continue"])

    def test_observe_needs_input(self):
        with self.assertRaises(ValueError):
            HealLoop().observe()

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            HealLoop(max_attempts_per_failure=0)
        with self.assertRaises(ValueError):
            HealLoop(max_rounds=0)
        with self.assertRaises(ValueError):
            HealLoop(max_stalled_rounds=-1)

    def test_rounds_are_recorded(self):
        loop = HealLoop()
        observe(loop, APP_ERROR)
        observe(loop, CLEAN)
        self.assertEqual(len(loop.rounds), 2)
        self.assertEqual([r["round"] for r in loop.rounds], [1, 2])


class HealLoopEscalationTests(unittest.TestCase):
    def test_repeated_failure_escalates_after_max_attempts(self):
        loop = HealLoop(max_stalled_rounds=10)
        observe(loop, APP_ERROR)
        observe(loop, APP_ERROR)
        result = observe(loop, APP_ERROR)
        self.assertEqual([event["code"] for event in result["escalations"]], ["REPEATED_FAILURE"])
        self.assertFalse(result["should_continue"])
        target = next(iter(loop.targets.values()))
        self.assertEqual(target.attempts, 3)
        self.assertEqual(target.status, "escalated")

    def test_escalation_is_reported_once(self):
        loop = HealLoop(max_stalled_rounds=10)
        for _ in range(5):
            result = observe(loop, APP_ERROR)
        codes = [event["code"] for event in loop.escalations]
        self.assertEqual(codes, ["REPEATED_FAILURE"])
        self.assertEqual(result["escalations"], [])
        self.assertFalse(result["should_continue"])

    def test_no_progress_escalates_on_unchanged_failure_set(self):
        loop = HealLoop(max_attempts_per_failure=99, max_stalled_rounds=2)
        observe(loop, APP_ERROR)
        observe(loop, APP_ERROR)
        result = observe(loop, APP_ERROR)
        self.assertEqual([event["code"] for event in result["escalations"]], ["NO_PROGRESS"])

    def test_fixing_one_error_resets_the_stall_counter(self):
        loop = HealLoop(max_attempts_per_failure=99, max_stalled_rounds=2)
        observe(loop, APP_ERROR)
        observe(loop, APP_ERROR)
        observe(loop, CLIENT_ERROR)
        self.assertEqual(loop._stalled, 0)
        self.assertEqual([event["code"] for event in loop.escalations], [])

    def test_regression_after_a_green_round(self):
        loop = HealLoop()
        observe(loop, APP_ERROR)
        green = observe(loop, CLEAN)
        self.assertTrue(green["green"])
        result = observe(loop, APP_ERROR)
        self.assertEqual([event["code"] for event in result["escalations"]], ["REGRESSION"])
        self.assertEqual(len(result["regressed"]), 1)

    def test_rounds_exhausted_stops_the_loop(self):
        loop = HealLoop(max_rounds=1, max_attempts_per_failure=99, max_stalled_rounds=5)
        observe(loop, APP_ERROR)
        result = observe(loop, APP_ERROR)
        self.assertEqual([event["code"] for event in result["escalations"]], ["ROUNDS_EXHAUSTED"])
        self.assertFalse(result["should_continue"])
        self.assertIn(HEAL_CODES[3], [event["code"] for event in loop.escalations])

    def test_fixed_targets_are_marked(self):
        loop = HealLoop()
        observe(loop, APP_ERROR, CLIENT_ERROR)
        result = observe(loop, CLIENT_ERROR)
        self.assertEqual(len(result["fixed"]), 1)
        app = [t for t in loop.targets.values() if t.failure.file == "src/app.ts"][0]
        self.assertEqual(app.status, "fixed")
        self.assertEqual(result["fixed"][0], app.failure.fingerprint)
        self.assertEqual(result["repeated"], [parse_log(CLIENT_ERROR)[0].fingerprint])

    def test_observe_accepts_failure_objects(self):
        loop = HealLoop()
        failures = parse_log(APP_ERROR)
        result = loop.observe(failures=failures)
        self.assertEqual(result["round"], 1)
        self.assertEqual(len(result["targets"]), 1)

    def test_status_snapshot(self):
        loop = HealLoop()
        observe(loop, APP_ERROR)
        snapshot = loop.status()
        self.assertEqual(snapshot["round"], 1)
        self.assertFalse(snapshot["green"])
        self.assertTrue(snapshot["should_continue"])
        self.assertEqual(snapshot["rounds"], [1])
        self.assertEqual(snapshot["ever_open"], 1)
        self.assertEqual(len(snapshot["targets"]), 1)


if __name__ == "__main__":
    unittest.main()
