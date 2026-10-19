# open-dmrv-engine

**Pyrolysis telemetry cannot violate mass balance, thermal regime or H/C_org
permanence before a Merkle root is signed.**

A small, deterministic MRV (measurement, reporting, verification) engine for
biochar carbon-removal projects. It takes the numbers your kiln already logs,
runs six checks against explicit limits, and returns one of three verdicts:
`pass` (bundle is signable), `review` (soft accounting problems only), or
`blocked` (a physical invariant is broken) — plus `empty` when there is nothing
to verify. Every verdict is reproducible byte
for byte, and the Merkle root over the batch leaves is computed even when the
bundle is refused — so a rejection is auditable too.

No network, no LLM, no clock, no dependencies. Python 3.10+.

```bash
# from GitHub — works today
pip install git+https://github.com/vanovri/open-dmrv-engine

# from PyPI — once 0.1.0 is uploaded
pip install open-dmrv-engine
open-dmrv verify examples/batches_pass.json
```

```
SLOW-001  slow         PASS  closure 0.990  yield 0.280  H/C 0.38
FAST-002  fast         PASS  closure 0.990  yield 0.180  H/C 0.45
TOR-003   torrefaction PASS  closure 0.990  yield 0.750  H/C 0.60

3 batch(es): 3 passed, 0 failed
merkle: d11021fe7c452a205b2cfda9ad1e2762be3987216941e77f46cc34add812d931
bundle: signable
```

The failing example is one command away:

```
SLOW-BAD-01  slow  FAIL  closure 0.700  yield 0.600  H/C 0.90  MASS_BALANCE, BIOCHAR_YIELD, THERMAL_REGIME, RESIDENCE_TIME, PERMANENCE, MOISTURE
SLOW-004     slow  FAIL  closure 0.988  yield 0.300  H/C 0.78  PERMANENCE
FAST-005     fast  PASS  closure 0.985  yield 0.150  H/C 0.55

3 batch(es): 1 passed, 2 failed
violations: BIOCHAR_YIELD, MASS_BALANCE, MOISTURE, PERMANENCE, RESIDENCE_TIME, THERMAL_REGIME
merkle: 061ee1c9c32f264d05986be16c0557bdee877640e96f9eb9c21788187783976a
bundle: NOT signable (blocked)
```

Exit code `1`. A certificate authority that trusts this engine would refuse to
sign, and the log says exactly which number was wrong.

## The six checks

| Code | Hard? | Rule | Why it exists |
| --- | --- | --- | --- |
| `MASS_BALANCE` | yes | `(biochar + syngas + bio-oil) / feedstock` within `1 ± 0.05` | Mass appears in a removal claim; a 30% gap means the scale, the gas meter, or the record is wrong |
| `THERMAL_REGIME` | yes | peak temperature inside the band of the declared process | The process name is a claim: "slow pyrolysis" at 720 °C is not slow pyrolysis |
| `RESIDENCE_TIME` | yes | residence inside the same process band | Char quality and PAH destruction depend on time as much as temperature |
| `PERMANENCE` | yes | `H/C_org ≤ 0.70` (≤ 0.40 flagged "100+ year durable") | The standard proxy for how long the carbon stays put |
| `BIOCHAR_YIELD` | no | char mass fraction inside a process-specific band | 60% char from slow pyrolysis usually means unburnt feedstock, not efficiency |
| `MOISTURE` | no | feedstock moisture `≤ 20%` | Wet feedstock makes the energy accounting and the temperature record meaningless |

Process bands (`PROCESS_SPECS`, edit in one place):

| Process | Peak temp | Residence | Biochar yield |
| --- | --- | --- | --- |
| `slow` | 350–500 °C | 20–180 min | 0.15–0.45 |
| `fast` | 450–650 °C | 1–60 min | 0.05–0.35 |
| `torrefaction` | 200–300 °C | 10–60 min | 0.50–0.85 |

Hard checks block signing. Soft checks downgrade a bundle to `review`, which is
what `--allow-review` is for: an operator can accept an unusual yield while the
physics still holds, but cannot accept a broken mass balance.

## Input format

One object per batch. Only seven fields are required; the rest default to zero.

```json
{
  "batches": [
    {
      "batch_id": "SLOW-001",
      "process": "slow",
      "feedstock_kg": 1000.0,
      "biochar_kg": 280.0,
      "syngas_kg": 640.0,
      "bio_oil_kg": 70.0,
      "peak_temp_c": 480.0,
      "residence_min": 60.0,
      "h_c_org": 0.38,
      "moisture_pct": 12.0
    }
  ]
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `batch_id` | yes | Appears in every report and in the leaf hash; uniqueness is not yet enforced (see issue 1) |
| `process` | yes | `slow`, `fast` or `torrefaction` (case-insensitive) |
| `feedstock_kg` | yes | Dry feedstock charged to the reactor, > 0 |
| `biochar_kg` | yes | Char recovered, > 0 |
| `peak_temp_c` | yes | Highest sustained bed temperature |
| `residence_min` | yes | Time at temperature, minutes |
| `h_c_org` | yes | Organic H/C ratio from elemental analysis |
| `syngas_kg` | no | Gas mass, default `0` |
| `bio_oil_kg` | no | Condensate mass, default `0` |
| `moisture_pct` | no | Feedstock moisture, default `0` |

The loader accepts three shapes, all equivalent:

- a JSON array of batch objects;
- a JSON object with a `batches` list (extra keys such as `site` are ignored);
- `.jsonl`, one batch object per line, blank lines skipped.

Validation is strict and happens before any check runs: unknown process,
negative mass, non-numeric or non-finite value, zero feedstock or zero biochar
is an input error (exit `2`), never a failed batch. Rounding is left to the
report; the arithmetic uses the values you supplied.

## Output

Text by default, `--json` for machines. The JSON shape is stable:

```json
{
  "status": "blocked",
  "signable": false,
  "batch_count": 3,
  "passed": 1,
  "failed": 2,
  "violations": ["BIOCHAR_YIELD", "MASS_BALANCE", "MOISTURE", "PERMANENCE"],
  "hard_violations": ["MASS_BALANCE", "PERMANENCE", "RESIDENCE_TIME", "THERMAL_REGIME"],
  "merkle_root": "061ee1c9c32f264d05986be16c0557bdee877640e96f9eb9c21788187783976a",
  "reports": [
    {
      "batch_id": "SLOW-004",
      "process": "slow",
      "status": "fail",
      "violations": ["PERMANENCE"],
      "hard_violations": ["PERMANENCE"],
      "durable": false,
      "checks": [
        {
          "code": "PERMANENCE",
          "ok": false,
          "detail": "H/C_org 0.78 (limit 0.70; above 0.40 durability band)",
          "value": 0.78,
          "limit": 0.7
        }
      ],
      "metrics": {
        "outputs_kg": 790.0,
        "mass_closure": 0.9875,
        "biochar_yield": 0.3,
        "peak_temp_c": 470.0,
        "residence_min": 45.0,
        "h_c_org": 0.78,
        "moisture_pct": 14.0
      }
    }
  ]
}
```

`checks` always contains all six codes in the same order, so a diff between two
reports is readable: `ok` flips, nothing moves. `detail` is a sentence a human
can paste into an incident ticket, and it carries both the measured value and
the limit that rejected it.

### Verdicts

| `status` | Meaning | `signable` |
| --- | --- | --- |
| `pass` | every batch passed all six checks | `true` |
| `review` | only soft checks failed (yield, moisture) | `false` |
| `blocked` | at least one hard invariant failed | `false` |
| `empty` | no batches in the input | `false` |

`empty` exists so that "nothing to verify" can never be mistaken for "verified
nothing". Signing requires a non-empty, fully passing bundle.

## Merkle root

```
leaf  = sha256(0x00 || canonical_json(batch))          # sorted keys, no spaces
node  = sha256(0x01 || left || right)                  # odd node duplicated
root  = fold(leaves)                                   # sha256(b"") when empty
```

Domain separation matters: a leaf can never be replayed as an inner node, and an
empty bundle has a root that no real batch can produce. Order is part of the
commitment — reversing the batch list changes the root, which is what you want
when the order is the sequence of a run.

```bash
open-dmrv merkle examples/batches_pass.json --json
```

```json
{
  "merkle_root": "d11021fe7c452a205b2cfda9ad1e2762be3987216941e77f46cc34add812d931",
  "leaf_count": 3
}
```

The root is printed for refused bundles too, so a rejection can be filed with
the exact hash of the data that caused it. What this engine does **not** do is
sign: it decides whether signing is allowed, and gives you the value to sign.
Key management belongs to whoever issues the certificate.

## CLI

```
open-dmrv verify PATH [--json] [--allow-review]
open-dmrv merkle PATH [--json]
```

| Exit | Meaning |
| --- | --- |
| `0` | every hard check passed and the bundle is signable (or `merkle` succeeded) |
| `1` | at least one violation, or the bundle is not signable |
| `2` | file missing, malformed JSON, invalid batch, or bad arguments |

`--allow-review` turns `review` into exit `0` — soft checks are accepted, hard
gates are not. `merkle` never validates; it hashes exactly what you give it, so
you can commit a root before a review decision.

## GitHub Action

```yaml
- name: Verify removal batch
  id: dmrv
  uses: ardyanovri/open-dmrv-engine@v0.1.0
  with:
    path: runs/2026-05-12.json

- name: Show the root that would be signed
  run: echo "${{ steps.dmrv.outputs.merkle-root }}"
```

The action installs the package from its own checkout, runs `verify --json`,
writes `dmrv-report.json`, exposes `status` and `merkle-root`, and fails the job
when the bundle is not signable. On a violation it annotates the run with the
list of codes; on an unreadable input it exits `2` and removes the half-written
report. `allow-review: true` accepts a `review` bundle but still fails on any
hard violation.

## Library use

```python
from open_dmrv import load_batches, verify_batches, verify_batch

batches = load_batches("runs/2026-05-12.json")
result = verify_batches(batches)

if not result["signable"]:
    for report in result["reports"]:
        for check in report["checks"]:
            if not check["ok"]:
                print(report["batch_id"], check["code"], check["detail"])
    raise SystemExit(1)

sign(result["merkle_root"])          # your KMS / wallet
```

`verify_batch(batch)` is the single-batch primitive if you build batches
yourself; `Batch` is a frozen dataclass, so a verified batch cannot be mutated
afterwards. Every public function is pure: same input, same dict, same hash.

## Scope

**It does.** Deterministic arithmetic and thresholds over declared telemetry;
stable JSON; a Merkle commitment with domain separation; strict input validation
that distinguishes "bad record" from "bad process".

**It does not.** Measure anything, replace a lab, model pyrolysis chemistry,
compute CO₂e, issue certificates, or verify signatures. The numbers are only as
honest as the log they came from; this engine makes dishonest numbers *visible*
— mass that does not add up, a temperature that contradicts the process name, a
char that will not stay in the ground — not impossible. Bands are defaults from
common practice, not a specific registry's methodology: check them against the
standard you report under, and change `PROCESS_SPECS` in one place if needed.

## Related

Part of the [`claude-oss-suite`](https://github.com/vanovri/claude-oss-suite):
[`agent-referee`](https://github.com/vanovri/agent-referee) for rubric-scored
review of finished work, [`redflag-loop`](https://github.com/vanovri/redflag-loop)
for evidence-gated loop guards, [`claude-build-healer`](https://github.com/vanovri/claude-build-healer)
for bounded fix loops on failing builds, and
[`mcp-spatial-critic`](https://github.com/vanovri/mcp-spatial-critic) for
3D-print mesh audits.

## Contributing

See [`GOOD_FIRST_ISSUES.md`](GOOD_FIRST_ISSUES.md). Tests are stdlib
`unittest`, no extra install:

```
python -m unittest discover -s tests -v
```

A new process band, a new check, or a new input adapter is one focused PR — the
whole engine is `open_dmrv/core.py`, and every check returns the same dict shape.

## License

MIT © Ardhya Novri Ramadhan

