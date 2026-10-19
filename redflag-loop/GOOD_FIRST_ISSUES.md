# Good first issues — redflag-loop

Nine scoped, unclaimed issues. Each one is self-contained: a failing test or a
clear before/after, no architecture debate required. Comment on the issue you
want and open a PR against `main`.

Test command for every issue:

```
python -m unittest discover -s tests -v
```

---

## 1. Detect near-duplicate actions, not just byte-identical ones

**Labels:** `good first issue`, `enhancement`

`action_signature` hashes the exact JSON, so `{"command": "pytest -q"}` and
`{"command": "pytest  -q"}` (double space) or `{"path": "./src/app.py"}` vs
`{"path": "src/app.py"}` look like different actions and the loop runs free.

**Do:** normalize before hashing — collapse whitespace in string values, strip a
leading `./` from path-like keys (`path`, `file`, `cwd`). Keep the existing
signature stable for already-clean actions so existing logs replay the same.

**Done when:** `tests/test_core.py` proves all four pairs above produce equal
signatures, and the existing 44 tests still pass.

---

## 2. `redflag-loop check --fail-on CODE` filter

**Labels:** `good first issue`, `cli`

Right now any redflag fails the process with exit `1`. Some teams only want
`UNSUPPORTED_COMPLETION` to be fatal and treat `NO_PROGRESS` as a warning.

**Do:** add a repeatable `--fail-on CODE` flag to `check`. When given, exit `1`
only if at least one open code is in that set; everything else exits `0` but is
still printed. Unknown code → exit `2` with a message listing valid codes.

**Done when:** `tests/test_cli.py` covers the filtered pass, the filtered fail,
and the unknown-code error.

---

## 3. GitHub Actions annotation output

**Labels:** `good first issue`, `cli`, `integrations`

A redflag should show up as an inline annotation on the PR, not just in the log.

**Do:** add `--format github` to `check`. For each redflag emit
`::error file=<log>:<line>,line=<line>,title=<CODE>::<detail>`. Action results
have no file, so use the log path and the event index + 1 as the line.

**Done when:** the output is asserted in a test and the README documents the
flag next to `--json`.

---

## 4. Summarise a whole directory of transcripts

**Labels:** `good first issue`, `cli`, `enhancement`

Agent runs are usually one directory: `runs/2026-10-20T09-14.jsonl` and friends.

**Do:** `redflag-loop check --dir runs/` walks `*.jsonl` (sorted), evaluates each
with the same limits, and prints one line per file plus a total:

```
runs/a.jsonl   CLEAN      6 events
runs/b.jsonl   REDFLAGS   LOOP_DETECTED  6 events
2 files, 1 clean, 1 with redflags
```

Exit `1` if any file is dirty, `2` if the directory is missing or empty.
`--json` returns `{"files": [...], "totals": {...}}`.

---

## 5. Accept JSON array input

**Labels:** `good first issue`, `enhancement`, `parsing`

Some harnesses dump one big JSON array instead of JSONL. Today that fails with
`invalid JSON` because each line is parsed separately.

**Do:** in `load_events`, if the file starts with `[`, parse the whole thing and
require a list of events. Keep the per-line path as the default and keep the
`:line:` error messages for JSONL.

**Done when:** both formats produce identical `replay()` reports for the same
events, with tests for each.

---

## 6. `NO_PROGRESS` should report which artifacts were missing

**Labels:** `good first issue`, `dx`

The message says "5 iterations without a new artifact" but not what the agent
kept touching. Debugging means re-reading the log.

**Do:** include the repeated action signatures and the last known artifacts in
`detail`, e.g.
`5 iterations without a new artifact (repeating ff09..., last artifacts: src/app.py)`.

**Done when:** the detail contains both pieces and a test asserts the format.

---

## 7. Per-task iteration budgets

**Labels:** `good first issue`, `enhancement`

One `LoopGuard` currently has one budget for the whole run. A 3-step refactor
and a 20-step migration cannot share `max_iterations=30` sanely.

**Do:** support `{"type": "task", "id": "T2", "max_iterations": 5}` events that
reset the budget counter (not the redflag history) for subsequent actions.
Document the interaction with `claim_done`.

**Done when:** a transcript with two tasks and different budgets behaves as
documented, and `status()` reports the active task.

---

## 8. Emit a Markdown report for PR comments

**Labels:** `good first issue`, `reporting`

**Do:** add `--format markdown` to `check`. Produce a table of events
(`# | action signature | verdict`) followed by a redflag list with the reason
text. No external template engine — plain f-strings.

**Done when:** the output is snapshot-tested and renders correctly in a GitHub
comment (paste it into any PR to check).

---

## 9. Property test: a guard never accepts an unsupported completion

**Labels:** `good first issue`, `testing`

The safety property is: if `claim_done` returns `accepted=True`, then the
evidence contained at least one item with `command` non-empty and
`exit_code == 0`, and no redflag was open beforehand.

**Do:** add a seeded, stdlib-only randomized test (`random.Random(1234)`) that
generates 200 transcripts of random actions and evidence (including booleans,
strings, missing keys, negative codes) and asserts the property. No new
dependencies.

**Done when:** it runs in under a second and would fail if the gate were
loosened.
