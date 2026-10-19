"""Tests for the deterministic verification core."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from open_dmrv import (
    EMPTY_ROOT,
    H_C_DURABLE,
    H_C_LIMIT,
    MASS_BALANCE_TOLERANCE,
    PROCESS_SPECS,
    Batch,
    batch_from_dict,
    canonical_bytes,
    load_batches,
    merkle_root,
    render_summary,
    verify_batch,
    verify_batches,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def make_batch(**overrides) -> Batch:
    payload = dict(
        batch_id="B-001",
        process="slow",
        feedstock_kg=1000.0,
        biochar_kg=280.0,
        syngas_kg=640.0,
        bio_oil_kg=70.0,
        peak_temp_c=480.0,
        residence_min=60.0,
        h_c_org=0.38,
        moisture_pct=12.0,
    )
    payload.update(overrides)
    return Batch(**payload)


def codes_of(report) -> list[str]:
    return report["violations"]


class MassBalanceTests(unittest.TestCase):
    def test_closure_sums_all_three_outputs(self):
        batch = make_batch()
        self.assertAlmostEqual(batch.outputs_kg, 990.0)
        self.assertAlmostEqual(batch.mass_closure, 0.99)

    def test_closure_is_zero_without_feedstock(self):
        batch = Batch("B", "slow", 0.0, 10.0, 400.0, 60.0, 0.3)
        self.assertEqual(batch.mass_closure, 0.0)
        self.assertEqual(batch.biochar_yield, 0.0)

    def test_tolerance_edges_are_inclusive(self):
        low = make_batch(syngas_kg=1000.0 * (1 - MASS_BALANCE_TOLERANCE) - 280.0 - 70.0)
        high = make_batch(syngas_kg=1000.0 * (1 + MASS_BALANCE_TOLERANCE) - 280.0 - 70.0)
        self.assertEqual(codes_of(verify_batch(low)), [])
        self.assertEqual(codes_of(verify_batch(high)), [])

    def test_closure_outside_tolerance_is_a_hard_violation(self):
        report = verify_batch(make_batch(syngas_kg=500.0))
        self.assertIn("MASS_BALANCE", report["violations"])
        self.assertIn("MASS_BALANCE", report["hard_violations"])
        self.assertEqual(report["status"], "fail")

    def test_closure_detail_carries_both_sides_of_the_ratio(self):
        report = verify_batch(make_batch(syngas_kg=500.0))
        check = next(c for c in report["checks"] if c["code"] == "MASS_BALANCE")
        self.assertIn("850.0 kg", check["detail"])
        self.assertIn("1000.0 kg", check["detail"])
        self.assertEqual(check["value"], 0.85)


class YieldTests(unittest.TestCase):
    def test_slow_yield_inside_band(self):
        self.assertNotIn("BIOCHAR_YIELD", codes_of(verify_batch(make_batch())))

    def test_yield_band_depends_on_process(self):
        torrefied = verify_batch(
            make_batch(
                process="torrefaction",
                biochar_kg=700.0,
                syngas_kg=290.0,
                bio_oil_kg=0.0,
                peak_temp_c=260.0,
                residence_min=30.0,
                h_c_org=0.6,
            )
        )
        self.assertEqual(codes_of(torrefied), [], "70% yield is normal for torrefaction")

        slow = verify_batch(make_batch(biochar_kg=700.0, syngas_kg=290.0, bio_oil_kg=0.0))
        self.assertEqual(codes_of(slow), ["BIOCHAR_YIELD"])

    def test_yield_is_soft_not_hard(self):
        report = verify_batch(make_batch(biochar_kg=700.0, syngas_kg=290.0, bio_oil_kg=0.0))
        self.assertEqual(report["hard_violations"], [])

    def test_every_process_spec_has_three_bands(self):
        for name, spec in PROCESS_SPECS.items():
            with self.subTest(process=name):
                self.assertEqual(set(spec), {"temp_c", "residence_min", "biochar_yield"})
                for band in spec.values():
                    self.assertLess(band[0], band[1])



class ThermalTests(unittest.TestCase):
    def test_band_boundaries_pass(self):
        for temp in (350.0, 500.0):
            with self.subTest(temp=temp):
                self.assertNotIn("THERMAL_REGIME", codes_of(verify_batch(make_batch(peak_temp_c=temp))))

    def test_temperature_outside_band_fails(self):
        for temp in (349.9, 500.1, 720.0):
            with self.subTest(temp=temp):
                self.assertIn("THERMAL_REGIME", codes_of(verify_batch(make_batch(peak_temp_c=temp))))

    def test_fast_process_allows_higher_peak(self):
        batch = make_batch(
            process="fast",
            peak_temp_c=600.0,
            residence_min=5.0,
            biochar_kg=90.0,
            syngas_kg=380.0,
            bio_oil_kg=25.0,
        )
        self.assertNotIn("THERMAL_REGIME", codes_of(verify_batch(batch)))


class ResidenceTests(unittest.TestCase):
    def test_too_short_and_too_long_are_reported(self):
        for minutes in (5.0, 181.0):
            with self.subTest(minutes=minutes):
                self.assertIn("RESIDENCE_TIME", codes_of(verify_batch(make_batch(residence_min=minutes))))

    def test_boundaries_pass(self):
        for minutes in (20.0, 180.0):
            with self.subTest(minutes=minutes):
                self.assertNotIn("RESIDENCE_TIME", codes_of(verify_batch(make_batch(residence_min=minutes))))


class PermanenceTests(unittest.TestCase):
    def test_limit_is_inclusive(self):
        report = verify_batch(make_batch(h_c_org=H_C_LIMIT))
        self.assertNotIn("PERMANENCE", codes_of(report))
        self.assertFalse(report["durable"])

    def test_above_limit_fails(self):
        report = verify_batch(make_batch(h_c_org=H_C_LIMIT + 0.01))
        self.assertIn("PERMANENCE", report["violations"])
        self.assertIn("PERMANENCE", report["hard_violations"])

    def test_durability_flag_uses_the_strict_band(self):
        self.assertTrue(verify_batch(make_batch(h_c_org=H_C_DURABLE))["durable"])
        self.assertFalse(verify_batch(make_batch(h_c_org=H_C_DURABLE + 0.01))["durable"])


class MoistureTests(unittest.TestCase):
    def test_limit_is_inclusive(self):
        self.assertNotIn("MOISTURE", codes_of(verify_batch(make_batch(moisture_pct=20.0))))

    def test_wet_feedstock_fails_softly(self):
        report = verify_batch(make_batch(moisture_pct=20.1))
        self.assertIn("MOISTURE", report["violations"])
        self.assertEqual(report["hard_violations"], [])


class ReportShapeTests(unittest.TestCase):
    def test_report_has_one_check_per_code(self):
        report = verify_batch(make_batch())
        self.assertEqual([c["code"] for c in report["checks"]], [
            "MASS_BALANCE",
            "BIOCHAR_YIELD",
            "THERMAL_REGIME",
            "RESIDENCE_TIME",
            "PERMANENCE",
            "MOISTURE",
        ])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["violations"], [])
        self.assertTrue(report["durable"])

    def test_report_is_json_serialisable(self):
        report = verify_batch(make_batch(syngas_kg=100.0, peak_temp_c=700.0))
        round_tripped = json.loads(json.dumps(report))
        self.assertEqual(round_tripped, report)

    def test_metrics_are_rounded_copies_of_the_inputs(self):
        report = verify_batch(make_batch())
        self.assertEqual(report["metrics"]["mass_closure"], 0.99)
        self.assertEqual(report["metrics"]["biochar_yield"], 0.28)
        self.assertEqual(report["metrics"]["h_c_org"], 0.38)


class BatchFromDictTests(unittest.TestCase):
    def test_optional_outputs_default_to_zero(self):
        batch = batch_from_dict(
            {
                "batch_id": "X-1",
                "process": "slow",
                "feedstock_kg": 100,
                "biochar_kg": 30,
                "peak_temp_c": 400,
                "residence_min": 60,
                "h_c_org": 0.5,
            }
        )
        self.assertEqual(batch.syngas_kg, 0.0)
        self.assertEqual(batch.bio_oil_kg, 0.0)
        self.assertEqual(batch.moisture_pct, 0.0)

    def test_process_and_id_are_normalised(self):
        batch = batch_from_dict(
            {
                "batch_id": "  X-1  ",
                "process": "  FAST ",
                "feedstock_kg": 100,
                "biochar_kg": 20,
                "peak_temp_c": 500,
                "residence_min": 10,
                "h_c_org": 0.5,
            }
        )
        self.assertEqual(batch.batch_id, "X-1")
        self.assertEqual(batch.process, "fast")

    def test_invalid_inputs_raise_with_a_useful_message(self):
        base = {
            "batch_id": "X-1",
            "process": "slow",
            "feedstock_kg": 100,
            "biochar_kg": 30,
            "peak_temp_c": 400,
            "residence_min": 60,
            "h_c_org": 0.5,
        }
        cases = {
            "missing batch_id": {**base, "batch_id": "  "},
            "unknown process": {**base, "process": "plasma"},
            "missing field": {k: v for k, v in base.items() if k != "h_c_org"},
            "negative mass": {**base, "biochar_kg": -1},
            "non numeric": {**base, "feedstock_kg": "many"},
            "infinite": {**base, "feedstock_kg": float("inf")},
            "nan": {**base, "h_c_org": float("nan")},
            "zero feedstock": {**base, "feedstock_kg": 0},
            "zero biochar": {**base, "biochar_kg": 0},
        }
        for label, payload in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    batch_from_dict(payload)

    def test_non_mapping_is_rejected(self):
        for payload in ([], "batch", 7, None):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    batch_from_dict(payload)


class MerkleTests(unittest.TestCase):
    def test_empty_tree_has_a_distinct_root(self):
        self.assertEqual(merkle_root([]), EMPTY_ROOT)
        self.assertEqual(len(EMPTY_ROOT), 64)

    def test_single_leaf_is_domain_separated(self):
        leaf = b'{"batch_id":"A"}'
        expected = hashlib.sha256(b"\x00" + leaf).hexdigest()
        self.assertEqual(merkle_root([leaf]), expected)

    def test_order_changes_the_root(self):
        a, b, c = b"a", b"b", b"c"
        self.assertNotEqual(merkle_root([a, b, c]), merkle_root([c, b, a]))

    def test_odd_node_is_duplicated(self):
        a, b, c = b"a", b"b", b"c"
        self.assertEqual(merkle_root([a, b, c]), merkle_root([a, b, c, c]))

    def test_duplicate_leaf_changes_the_root(self):
        a = b"a"
        self.assertNotEqual(merkle_root([a]), merkle_root([a, a]))

    def test_roots_are_stable_across_calls(self):
        leaves = [b"x", b"y", b"z", b"w"]
        self.assertEqual(merkle_root(leaves), merkle_root(leaves))
        self.assertRegex(merkle_root(leaves), r"^[0-9a-f]{64}$")

    def test_canonical_bytes_ignores_key_order(self):
        self.assertEqual(
            canonical_bytes({"b": 1, "a": 2}),
            canonical_bytes({"a": 2, "b": 1}),
        )
        self.assertEqual(canonical_bytes({"a": 2, "b": 1}), b'{"a":2,"b":1}')


class VerifyBatchesTests(unittest.TestCase):
    def test_clean_fixture_is_signable(self):
        result = verify_batches(load_batches(EXAMPLES / "batches_pass.json"))
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["signable"])
        self.assertEqual(result["batch_count"], 3)
        self.assertEqual((result["passed"], result["failed"]), (3, 0))
        self.assertEqual(result["violations"], [])
        self.assertRegex(result["merkle_root"], r"^[0-9a-f]{64}$")

    def test_violating_fixture_blocks_signing(self):
        result = verify_batches(load_batches(EXAMPLES / "batches_fail.json"))
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["signable"])
        self.assertEqual((result["passed"], result["failed"]), (1, 2))
        for code in ("MASS_BALANCE", "THERMAL_REGIME", "RESIDENCE_TIME", "PERMANENCE", "BIOCHAR_YIELD", "MOISTURE"):
            self.assertIn(code, result["violations"])
        self.assertEqual(result["reports"][1]["violations"], ["PERMANENCE"])

    def test_soft_failures_alone_are_review_not_blocked(self):
        batch = make_batch(biochar_kg=700.0, syngas_kg=290.0, bio_oil_kg=0.0)
        result = verify_batches([batch])
        self.assertEqual(result["status"], "review")
        self.assertFalse(result["signable"])
        self.assertEqual(result["hard_violations"], [])
        self.assertEqual(result["violations"], ["BIOCHAR_YIELD"])

    def test_empty_bundle_is_never_signable(self):
        result = verify_batches([])
        self.assertEqual(result["status"], "empty")
        self.assertFalse(result["signable"])
        self.assertEqual(result["merkle_root"], EMPTY_ROOT)
        self.assertEqual(result["batch_count"], 0)

    def test_bundle_root_matches_the_standalone_root(self):
        batches = load_batches(EXAMPLES / "batches_pass.json")
        result = verify_batches(batches)
        self.assertEqual(
            result["merkle_root"],
            merkle_root([canonical_bytes(batch.as_dict()) for batch in batches]),
        )

    def test_input_order_is_preserved_in_reports(self):
        batches = load_batches(EXAMPLES / "batches_fail.json")
        result = verify_batches(batches)
        self.assertEqual(
            [report["batch_id"] for report in result["reports"]],
            ["SLOW-BAD-01", "SLOW-004", "FAST-005"],
        )


class LoadBatchesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def record(self, **overrides):
        payload = {
            "batch_id": "L-1",
            "process": "slow",
            "feedstock_kg": 100,
            "biochar_kg": 28,
            "syngas_kg": 64,
            "bio_oil_kg": 7,
            "peak_temp_c": 450,
            "residence_min": 60,
            "h_c_org": 0.4,
            "moisture_pct": 10,
        }
        payload.update(overrides)
        return payload

    def test_example_file_loads_three_batches(self):
        batches = load_batches(EXAMPLES / "batches_pass.json")
        self.assertEqual([b.batch_id for b in batches], ["SLOW-001", "FAST-002", "TOR-003"])

    def test_json_array(self):
        path = self.write("array.json", json.dumps([self.record(), self.record(batch_id="L-2")]))
        self.assertEqual([b.batch_id for b in load_batches(path)], ["L-1", "L-2"])

    def test_object_with_batches_key(self):
        path = self.write("object.json", json.dumps({"site": "x", "batches": [self.record()]}))
        self.assertEqual(len(load_batches(path)), 1)

    def test_jsonl_skips_blank_lines(self):
        text = "\n".join([json.dumps(self.record()), "", json.dumps(self.record(batch_id="L-2")), ""])
        path = self.write("log.jsonl", text)
        self.assertEqual([b.batch_id for b in load_batches(path)], ["L-1", "L-2"])

    def test_missing_file_names_the_path(self):
        with self.assertRaises(ValueError) as ctx:
            load_batches(self.tmp / "nope.json")
        self.assertIn("not found", str(ctx.exception))

    def test_invalid_json_reports_the_line(self):
        path = self.write("bad.json", '{"batches": [}')
        with self.assertRaises(ValueError) as ctx:
            load_batches(path)
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_empty_list_is_rejected(self):
        path = self.write("empty.json", "[]")
        with self.assertRaises(ValueError) as ctx:
            load_batches(path)
        self.assertIn("no batches", str(ctx.exception))

    def test_object_without_batches_key_is_rejected(self):
        path = self.write("nokey.json", '{"site": "x"}')
        with self.assertRaises(ValueError) as ctx:
            load_batches(path)
        self.assertIn("batches", str(ctx.exception))

    def test_batches_value_must_be_a_list(self):
        path = self.write("shape.json", '{"batches": {"batch_id": "x"}}')
        with self.assertRaises(ValueError) as ctx:
            load_batches(path)
        self.assertIn("list of batches", str(ctx.exception))

    def test_invalid_record_surfaces_the_batch_reason(self):
        path = self.write("badrecord.json", json.dumps([self.record(process="plasma")]))
        with self.assertRaises(ValueError) as ctx:
            load_batches(path)
        self.assertIn("unknown process", str(ctx.exception))


class RenderSummaryTests(unittest.TestCase):
    def test_clean_summary_states_that_the_bundle_is_signable(self):
        text = render_summary(verify_batches(load_batches(EXAMPLES / "batches_pass.json")))
        self.assertIn("SLOW-001", text)
        self.assertIn("PASS", text)
        self.assertIn("3 batch(es): 3 passed, 0 failed", text)
        self.assertIn("bundle: signable", text)
        self.assertNotIn("NOT signable", text)

    def test_blocked_summary_lists_the_codes(self):
        result = verify_batches(load_batches(EXAMPLES / "batches_fail.json"))
        text = render_summary(result)
        self.assertIn("FAIL", text)
        self.assertIn("violations: ", text)
        self.assertIn(result["merkle_root"], text)
        self.assertIn("NOT signable (blocked)", text)

    def test_review_summary_is_not_green(self):
        text = render_summary(verify_batches([make_batch(biochar_kg=700.0, syngas_kg=290.0, bio_oil_kg=0.0)]))
        self.assertIn("NOT signable (review)", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
