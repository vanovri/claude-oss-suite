"""Deterministic MRV checks for pyrolysis batches.

The engine answers one question per batch: *can this telemetry back a signed
removal certificate?* Three physical invariants decide it — mass balance,
thermal regime, and organic carbon permanence — plus two accounting guards
(biochar yield, feedstock moisture). Nothing is inferred from a model: every
number is computed from the batch record, and a batch that fails any hard check
can never be part of a signable bundle.

Deterministic by construction: no clocks, no network, no randomness. The same
input always produces the same report and the same Merkle root.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

CODES = (
    "MASS_BALANCE",
    "BIOCHAR_YIELD",
    "THERMAL_REGIME",
    "RESIDENCE_TIME",
    "PERMANENCE",
    "MOISTURE",
    "INVALID_INPUT",
)

#: Hard gates: a violation here blocks signing.
HARD_CODES = ("MASS_BALANCE", "THERMAL_REGIME", "RESIDENCE_TIME", "PERMANENCE")

#: Physical envelope per declared process. Values are (min, max), inclusive.
PROCESS_SPECS: Dict[str, Dict[str, Any]] = {
    "slow": {
        "temp_c": (350.0, 500.0),
        "residence_min": (20.0, 180.0),
        "biochar_yield": (0.15, 0.45),
    },
    "fast": {
        "temp_c": (450.0, 650.0),
        "residence_min": (1.0, 60.0),
        "biochar_yield": (0.05, 0.35),
    },
    "torrefaction": {
        "temp_c": (200.0, 300.0),
        "residence_min": (10.0, 60.0),
        "biochar_yield": (0.50, 0.85),
    },
}

MASS_BALANCE_TOLERANCE = 0.05   # closure must land in 1 ± 0.05
H_C_LIMIT = 0.70                # above this the char is not durable carbon
H_C_DURABLE = 0.40              # below this, 100+ year stability per IBI
MAX_MOISTURE_PCT = 20.0         # wet feedstock invalidates energy accounting

EMPTY_ROOT = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True)
class Batch:
    """One pyrolysis run, as reported by the operator or the PLC."""

    batch_id: str
    process: str
    feedstock_kg: float
    biochar_kg: float
    peak_temp_c: float
    residence_min: float
    h_c_org: float
    syngas_kg: float = 0.0
    bio_oil_kg: float = 0.0
    moisture_pct: float = 0.0

    @property
    def outputs_kg(self) -> float:
        return self.biochar_kg + self.syngas_kg + self.bio_oil_kg

    @property
    def mass_closure(self) -> float:
        return self.outputs_kg / self.feedstock_kg if self.feedstock_kg else 0.0

    @property
    def biochar_yield(self) -> float:
        return self.biochar_kg / self.feedstock_kg if self.feedstock_kg else 0.0

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["mass_closure"] = round(self.mass_closure, 6)
        payload["biochar_yield"] = round(self.biochar_yield, 6)
        return payload


def _check(code: str, ok: bool, detail: str, value: Any, limit: Any) -> Dict[str, Any]:
    return {"code": code, "ok": ok, "detail": detail, "value": value, "limit": limit}


def _in_band(value: float, band: Sequence[float]) -> bool:
    low, high = band
    return low <= value <= high


def _fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def batch_from_dict(data: Mapping[str, Any]) -> Batch:
    """Build a :class:`Batch` or raise ``ValueError`` with a readable reason."""

    if not isinstance(data, Mapping):
        raise ValueError("batch must be a JSON object")

    batch_id = str(data.get("batch_id") or "").strip()
    if not batch_id:
        raise ValueError("batch_id is required")

    process = str(data.get("process") or "").strip().lower()
    if process not in PROCESS_SPECS:
        known = ", ".join(sorted(PROCESS_SPECS))
        raise ValueError(f"{batch_id}: unknown process {process!r} (expected one of {known})")

    numbers: Dict[str, float] = {}
    for field, default in (
        ("feedstock_kg", None),
        ("biochar_kg", None),
        ("peak_temp_c", None),
        ("residence_min", None),
        ("h_c_org", None),
        ("syngas_kg", 0.0),
        ("bio_oil_kg", 0.0),
        ("moisture_pct", 0.0),
    ):
        raw = data.get(field, default)
        if raw is None:
            raise ValueError(f"{batch_id}: {field} is required")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{batch_id}: {field} must be a number, got {raw!r}") from None
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{batch_id}: {field} must be finite, got {raw!r}")
        if value < 0:
            raise ValueError(f"{batch_id}: {field} cannot be negative, got {value}")
        numbers[field] = value

    if numbers["feedstock_kg"] <= 0:
        raise ValueError(f"{batch_id}: feedstock_kg must be greater than zero")
    if numbers["biochar_kg"] <= 0:
        raise ValueError(f"{batch_id}: biochar_kg must be greater than zero")

    return Batch(batch_id=batch_id, process=process, **numbers)


def verify_batch(batch: Batch) -> Dict[str, Any]:
    """Run every check against one batch and return a JSON-ready report."""

    spec = PROCESS_SPECS[batch.process]
    checks: List[Dict[str, Any]] = []

    low = 1.0 - MASS_BALANCE_TOLERANCE
    high = 1.0 + MASS_BALANCE_TOLERANCE
    closure = batch.mass_closure
    checks.append(
        _check(
            "MASS_BALANCE",
            low <= closure <= high,
            f"outputs {_fmt(batch.outputs_kg, 1)} kg / feedstock {_fmt(batch.feedstock_kg, 1)} kg "
            f"= {_fmt(closure)} (allowed {_fmt(low, 2)}-{_fmt(high, 2)})",
            round(closure, 6),
            [low, high],
        )
    )

    yield_fraction = batch.biochar_yield
    yield_band = spec["biochar_yield"]
    checks.append(
        _check(
            "BIOCHAR_YIELD",
            _in_band(yield_fraction, yield_band),
            f"biochar {_fmt(batch.biochar_kg, 1)} kg / feedstock {_fmt(batch.feedstock_kg, 1)} kg "
            f"= {_fmt(yield_fraction)} (allowed {_fmt(yield_band[0], 2)}-{_fmt(yield_band[1], 2)} for {batch.process})",
            round(yield_fraction, 6),
            list(yield_band),
        )
    )

    temp_band = spec["temp_c"]
    checks.append(
        _check(
            "THERMAL_REGIME",
            _in_band(batch.peak_temp_c, temp_band),
            f"peak {_fmt(batch.peak_temp_c, 0)} C (allowed {_fmt(temp_band[0], 0)}-{_fmt(temp_band[1], 0)} C for {batch.process})",
            batch.peak_temp_c,
            list(temp_band),
        )
    )

    residence_band = spec["residence_min"]
    checks.append(
        _check(
            "RESIDENCE_TIME",
            _in_band(batch.residence_min, residence_band),
            f"{_fmt(batch.residence_min, 1)} min (allowed {_fmt(residence_band[0], 1)}-{_fmt(residence_band[1], 1)} min for {batch.process})",
            batch.residence_min,
            list(residence_band),
        )
    )

    durable = batch.h_c_org <= H_C_DURABLE
    checks.append(
        _check(
            "PERMANENCE",
            batch.h_c_org <= H_C_LIMIT,
            f"H/C_org {_fmt(batch.h_c_org, 2)} (limit {_fmt(H_C_LIMIT, 2)}; "
            + ("100+ year durable" if durable else f"above {_fmt(H_C_DURABLE, 2)} durability band)")
            + ")",
            batch.h_c_org,
            H_C_LIMIT,
        )
    )

    checks.append(
        _check(
            "MOISTURE",
            batch.moisture_pct <= MAX_MOISTURE_PCT,
            f"feedstock moisture {_fmt(batch.moisture_pct, 1)}% (limit {_fmt(MAX_MOISTURE_PCT, 1)}%)",
            batch.moisture_pct,
            MAX_MOISTURE_PCT,
        )
    )

    violations = [check["code"] for check in checks if not check["ok"]]
    return {
        "batch_id": batch.batch_id,
        "process": batch.process,
        "status": "pass" if not violations else "fail",
        "checks": checks,
        "violations": violations,
        "hard_violations": [code for code in violations if code in HARD_CODES],
        "durable": durable,
        "metrics": {
            "outputs_kg": round(batch.outputs_kg, 6),
            "mass_closure": round(closure, 6),
            "biochar_yield": round(yield_fraction, 6),
            "peak_temp_c": batch.peak_temp_c,
            "residence_min": batch.residence_min,
            "h_c_org": batch.h_c_org,
            "moisture_pct": batch.moisture_pct,
        },
    }


def canonical_bytes(record: Mapping[str, Any]) -> bytes:
    """Stable serialisation used as a Merkle leaf."""

    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def merkle_root(leaves: Sequence[bytes]) -> str:
    """RFC 6962-style binary Merkle root over already-serialised leaves.

    An empty tree has the distinct ``EMPTY_ROOT`` value, so "no batches" can
    never collide with "one batch whose leaf hashes to zero".
    """

    if not leaves:
        return EMPTY_ROOT

    nodes = [hashlib.sha256(b"\x00" + leaf).digest() for leaf in leaves]
    while len(nodes) > 1:
        if len(nodes) % 2:
            nodes.append(nodes[-1])
        nodes = [
            hashlib.sha256(b"\x01" + nodes[i] + nodes[i + 1]).digest()
            for i in range(0, len(nodes), 2)
        ]
    return nodes[0].hex()


def verify_batches(batches: Sequence[Batch]) -> Dict[str, Any]:
    """Verify every batch and decide whether the bundle may be signed."""

    reports = [verify_batch(batch) for batch in batches]
    violations = sorted({code for report in reports for code in report["violations"]})
    hard = sorted({code for report in reports for code in report["hard_violations"]})
    passed = sum(1 for report in reports if report["status"] == "pass")
    failed = len(reports) - passed

    if not reports:
        status = "empty"
    elif hard:
        status = "blocked"
    elif failed:
        status = "review"
    else:
        status = "pass"

    return {
        "status": status,
        "signable": status == "pass",
        "batch_count": len(reports),
        "passed": passed,
        "failed": failed,
        "violations": violations,
        "hard_violations": hard,
        "merkle_root": merkle_root([canonical_bytes(batch.as_dict()) for batch in batches]),
        "reports": reports,
    }


def load_batches(path: "str | Path") -> List[Batch]:
    """Read ``.json`` (array or ``{"batches": [...]}``) or newline-delimited ``.jsonl``."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"{source}: file not found") from None
    except OSError as exc:
        raise ValueError(f"{source}: {exc}") from None

    try:
        if source.suffix.lower() == ".jsonl":
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            payload = json.loads(text)
            if isinstance(payload, Mapping):
                if "batches" not in payload:
                    raise ValueError("object must contain a 'batches' list")
                records = payload["batches"]
            else:
                records = payload
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source}: invalid JSON ({exc.msg} at line {exc.lineno})") from None

    if not isinstance(records, list):
        raise ValueError(f"{source}: expected a list of batches")
    if not records:
        raise ValueError(f"{source}: no batches found")

    return [batch_from_dict(record) for record in records]


def render_summary(result: Mapping[str, Any]) -> str:
    """Human-readable report, one line per batch, then the bundle verdict."""

    lines: List[str] = []
    width = max((len(report["batch_id"]) for report in result["reports"]), default=8)

    for report in result["reports"]:
        metrics = report["metrics"]
        verdict = "PASS" if report["status"] == "pass" else "FAIL"
        reason = "" if report["status"] == "pass" else "  " + ", ".join(report["violations"])
        lines.append(
            f"{report['batch_id']:<{width}}  {report['process']:<12} {verdict}  "
            f"closure {metrics['mass_closure']:.3f}  yield {metrics['biochar_yield']:.3f}  "
            f"H/C {metrics['h_c_org']:.2f}{reason}"
        )

    lines.append("")
    lines.append(
        f"{result['batch_count']} batch(es): {result['passed']} passed, {result['failed']} failed"
    )
    if result["violations"]:
        lines.append("violations: " + ", ".join(result["violations"]))
    lines.append(f"merkle: {result['merkle_root']}")
    lines.append(
        "bundle: signable" if result["signable"] else f"bundle: NOT signable ({result['status']})"
    )
    return "\n".join(lines)
