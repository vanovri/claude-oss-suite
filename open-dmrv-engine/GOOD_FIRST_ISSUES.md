# Good first issues — open-dmrv-engine

Nine scoped, unclaimed issues. Each one touches a single file, comes with a test
command, and needs no domain PhD to finish — the physics is already encoded in
`open_dmrv/core.py` and every check returns the same dict shape.

```
python -m unittest discover -s tests -v
```

Current state: 68 tests, stdlib `unittest`, no dependencies.

---

## 1. Reject duplicate `batch_id`s

**Labels:** `good first issue`, `bug`, `verification`

Two batches with the same `batch_id` are two Merkle leaves and two "removals",
but they describe one run. Nothing currently stops a double-counted bundle.

**Do:** detect duplicates in `load_batches` (after parsing, before returning)
and raise `ValueError` naming the id and both positions. Keep the check in the
loader so every caller — CLI, library, action — inherits it.

**Done when:** `tests/test_core.py` proves a duplicated id raises with
`"duplicate batch_id"`, that a JSONL file with the same id twice is rejected,
and that the two example fixtures still load.

---

## 2. CSV adapter for logger exports

**Labels:** `good first issue`, `adapter`, `dx`

Most kilns export CSV, not JSON, and hand-editing a 900-row file into JSON is
where transcription errors enter an MRV pipeline.

**Do:** accept `.csv` in `load_batches` using `csv.DictReader` (stdlib). Map the
headers in `CSV_COLUMNS = {"batch": "batch_id", "feed_kg": "feedstock_kg", ...}`
and let every other required field keep its canonical name. Empty optional cells
mean `0`, not `None`.

**Done when:** `examples/batches.csv` exists with three rows matching
`batches_pass.json`, both files produce the **same** Merkle root, and a CSV that
is missing `h_c_org` fails with the same readable error as JSON.

---

## 3. `open-dmrv explain CODE`

**Labels:** `good first issue`, `cli`, `docs`

`PERMANENCE` on line 3 of a report is terse for someone outside the field.

**Do:** add `explain CODE` printing the rule, the band, the physical reason, and
one sentence on what to change in the reactor. Source the text from a new
`EXPLANATIONS` dict in `core.py` so the CLI stays thin. Unknown code → exit `2`
and list the valid ones.

**Done when:** all six codes have an entry (a test asserts `set(EXPLANATIONS) ==
set(CODES)`), and `explain MASS_BALANCE` mentions the tolerance constant rather
than a hard-coded 0.05.

---

## 4. Markdown report for pull requests

**Labels:** `good first issue`, `reporting`, `cli`

Reviewers want the table, not a 400-line JSON blob.

**Do:** add `--format {text,json,markdown}` to `verify` (keep `--json` as an
alias). Markdown output: one summary line, a table with `batch | process |
status | closure | yield | H/C | violations`, and the Merkle root in a code
fence. Escape pipes in values.

**Done when:** `tests/test_cli.py` asserts the header row, the exact number of
table rows for the failing fixture, and that `--json` still emits valid JSON.

---

## 5. Registry presets for the process bands

**Labels:** `good first issue`, `domain`, `config`

`PROCESS_SPECS` is one set of defaults. Real projects report under a specific
methodology (IBI, Puro.earth, EBC) whose bands differ slightly.

**Do:** add `PRESETS = {"default": ..., "ibi": ..., "puro": ...}` as a mapping of
name → full spec dict, plus `--preset NAME` on both subcommands. Unknown preset
→ exit `2`. `PROCESS_SPECS` stays importable and equal to `PRESETS["default"]`.

**Done when:** a test verifies each preset has all three processes, that bands
are ordered (`min < max`), that `--preset ibi` changes a verdict on a fixture
crafted to sit between the two bands, and that the default run is unchanged.

---

## 6. Merkle inclusion proof

**Labels:** `good first issue`, `crypto`, `cli`

A root commits to a bundle; a single batch is often all an auditor is allowed to
see. Right now there is no way to prove one leaf belongs to the signed root.

**Do:** `open-dmrv proof FILE --batch-id ID` prints the sibling path as JSON
(`{"leaf_index": 1, "path": [{"side": "left", "hash": "..."}, ...]}`), and
`open_dmrv.merkle_proof(leaves, index)` / `merkle_verify(leaf, path, root)`
expose it to the library. Handle the duplicated odd node.

**Done when:** a test builds proofs for every index of a 1-, 2-, 3- and 5-leaf
tree, verifies them, then flips one byte in the leaf and asserts verification
fails. No new dependencies.

---

## 7. Energy balance check

**Labels:** `good first issue`, `physics`, `verification`

Mass closure says atoms were conserved; it says nothing about whether the
reactor ran itself. A batch that consumed more energy than it produced is a
removal with an emissions problem.

**Do:** add an optional `energy_in_kwh` / `energy_out_kwh` input pair and an
`ENERGY_BALANCE` check: `energy_out / energy_in ≥ 0.6`, hard gate, skipped
(recorded as `ok` with `"skipped": true`) when both fields are absent. Keep the
six existing checks untouched and their order stable.

**Done when:** the check appears in `checks` for a batch that supplies the
fields, is skipped for one that does not, and the legacy fixtures produce
byte-identical reports.

---

## 8. `verify --watch` for live kiln runs

**Labels:** `good first issue`, `cli`, `ops`

During a run the operator wants a refusal *before* the kiln cools, not after the
bundle is assembled.

**Do:** poll a JSONL file every `--interval` seconds, re-verify from scratch on
change (no incremental state — determinism first), print only the batches whose
status changed since the previous pass, and exit `1` on the first hard violation
unless `--keep-going`. Ctrl-C exits `0`.

**Done when:** a test writes a JSONL file, spawns the command against it in a
subprocess-free way (call `main(argv)` twice), asserts the second pass prints
only the changed batch. Document the flag under CLI in `README.md`.

---

## 9. Mutation fuzz over the commitment

**Labels:** `good first issue`, `testing`, `crypto`

The guarantee "one changed field changes the root" is currently asserted by
example, not proven over the field space.

**Do:** with a fixed seed, mutate each numeric field of a passing fixture in
turn (bump by one ULP, by 10%, and to the band boundary), and assert the Merkle
root changes every time and that re-verifying the mutated batch never returns
`pass` unless the mutation stayed inside the band. Fail the test with the exact
field name that slipped through.

**Done when:** the test is seeded and deterministic, covers all numeric fields
plus `process`, and runs in under two seconds.

