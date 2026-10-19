# claude-build-healer

**Stop the agent from patching the same error nine times.**

`claude-build-healer` turns a failing build log into a bounded, deduplicated fix
plan: it parses the errors, fingerprints them so a moved line is still the same
bug, orders the work, and escalates the moment a round stops making progress.

No LLM calls. No network. No dependencies. It reads text you already have.

```
# from GitHub — works today
pip install git+https://github.com/vanovri/claude-build-healer

# from PyPI — once 0.1.0 is uploaded
pip install claude-build-healer
build-healer plan examples/tsc_failure.log
```

```
blocking: 2  advisory: 1  files: 2
targets:
  1. src/app.ts:12:5 [TS2322]: Type 'string' is not assignable to type 'number'.
     fingerprint=95c860aa77a2a1be tool=tsc
  2. src/api/client.ts:40:18 [TS2345]: Argument of type '{ id: string; }' is not assignable to parameter of type 'Request'.
     fingerprint=dac2e163c012ba89 tool=tsc
  warning: src/app.ts: 'debug' is declared but its value is never read.
advice: Start with [tsc] src/app.ts:12:5 [TS2322]: Type 'string' is not assignable to type 'number'. 2 blocking error(s) in 2 file(s); fix one target per iteration, then re-run the build. Do not edit files that are not listed in the plan.
```

Replay a sequence of rounds and the loop tells you when to stop:

```
build-healer rounds examples/rounds
```

```
[round1.log]
round 1: RED  errors=2 fixed=0 repeated=0
  next: Fix src/app.ts:12:5: Type 'string' is not assignable to type 'number'. Change one thing, keep the diff minimal. Then re-run the build; 1 error(s) remain.
[round2.log]
round 2: RED  errors=2 fixed=0 repeated=2
[round3.log]
round 3: RED  errors=1 fixed=1 repeated=1
  escalate [REPEATED_FAILURE]: src/app.ts:14:5 failed 3 rounds in a row (Type 'string' is not assignable to type 'number')
  next: REPEATED_FAILURE: src/app.ts:14:5 failed 3 rounds in a row (Type 'string' is not assignable to type 'number'). Stop patching. Quote the full error with its file:line, state what you tried in each attempt, and ask for a decision: revert, change approach, or narrow scope.
[round4.log]
round 4: GREEN  errors=0 fixed=1 repeated=0
  next: Build is green. Stop editing, commit, and report the passing command.
```

Exit code `0` on a green final round, `1` while errors remain, `2` on bad input.

## The problem

An agent that can run `pytest` will run it again. Three patterns repeat across
every harness I have watched:

1. **The rerun loop.** The failure is real, the fix is cosmetic, the log is
   identical. Round 4 looks like round 1 and nobody notices until the budget is
   gone.
2. **The duplicate swarm.** One type error re-exported through six files arrives
   as six lines. The agent edits all six, breaks two, and now owns eight errors.
3. **The silent regression.** Round 3 fixes the failing test and re-breaks the
   import from round 1. The transcript shows progress; the build does not.

A prompt that says *fix the build* is a wish. This package is the bookkeeping:
explicit targets, per-error attempt counts, and a hard stop with an escalation
message a human can act on.

## What it does

```
log text ──▶ parsers ──▶ Failure records ──▶ dedupe by fingerprint ──▶ plan
                                                    │
                                      HealLoop.observe() per round
                                                    │
                        repeated / regressed / stalled / over budget
```

| Step | Function | Output |
| --- | --- | --- |
| Parse | `parse_log(text)` | `Failure` list, one per diagnostic, each tagged with its grammar |
| Fingerprint | `failure.fingerprint` | 16 hex chars, stable across line moves and volatile details |
| Plan | `build_plan(failures)` | deduplicated targets in file order, advisory warnings, one sentence of advice |
| Loop | `HealLoop().observe(log_text=...)` | per-round verdict: `should_continue`, `fixed`, `regressed`, `escalations`, `advice` |

### Escalation codes

| Code | Fires when | What you do |
| --- | --- | --- |
| `REPEATED_FAILURE` | one target has failed `max_attempts_per_failure` rounds (default 3) | stop patching this target; change approach or ask for a decision |
| `NO_PROGRESS` | the open failure set is unchanged for `max_stalled_rounds` rounds (default 2) | the diff is not reaching the cause; re-read the error before editing again |
| `REGRESSION` | a fingerprint that was fixed in an earlier round is failing again | revert the last change, then re-apply it in smaller pieces |
| `ROUNDS_EXHAUSTED` | `round > max_rounds` with errors still open (default 8) | report state and ask for scope, not another attempt |

Each escalation is emitted once per fingerprint, carries the detail string and a
fixed piece of advice, and is appended to `loop.escalations`. After the first
escalation `should_continue` stays `False`: the loop does not quietly resume.


## Supported grammars

| Tool | Recognised line | Extracted |
| --- | --- | --- |
| Python | `File "app.py", line 6, in run` + `ZeroDivisionError: division by zero` | last frame file/line, exception type and message; also bare `SyntaxError` blocks |
| pytest | `FAILED tests/test_x.py::test_name - assertion text` | test id as code, assertion text; falls back to `file:line: Error` lines when the summary is missing |
| TypeScript | `src/app.ts(12,5): error TS2322: ...` | file, line, column, diagnostic code, severity |
| GCC / Clang | `src/main.c:12:5: error: ...` | file, line, column, `error` / `warning` / `fatal error` |
| rustc | `error[E0308]: mismatched types` + ` --> src/main.rs:10:5` | code, span, message |
| ESLint | `src/app.js` header + `12:5  error  'x' is not defined  no-undef` | file inherited from the header, rule as code, severity |
| Go | `./main.go:10:5: undefined: cfg` | file (leading `./` dropped), line, column, message |
| generic | `Error: Cannot find module 'left-pad'` | message only — the fallback when nothing else matches |

Summary counters (`Found 1 error in 1 file`, `2 failed, 12 passed`) are counts,
not failures, and are skipped rather than reported as a phantom target.

A mixed log is fine: every grammar runs, results are merged in log order, then
deduplicated. When two grammars match the same line, the more specific one has
already claimed it, so the generic fallback cannot double-count.

**Honest limits.** These are regex grammars, tested against the fixtures in
`examples/` and `tests/test_parsers.py`. Compilers change their wording; a
grammar that misses your variant will fall through to `generic`, which loses
the file and line. Add a fixture that reproduces your output, then extend the
scanner — that is the whole contribution.

## Fingerprints

```
fingerprint = sha256(tool | normalized-file | code | normalized-message)[:16]
```

Normalisation is deliberately aggressive:

- line and column are **excluded**, so an error that moves down four lines after
  an edit is still the same error;
- messages are lowercased, whitespace-collapsed, hex addresses become `0xADDR`,
  temp paths become `<tmp>`;
- leading `./` and `\` are dropped from file paths.

So `src/app.ts(12,5)` and `src/app.ts(99,1)` with the same code and message share
one target and one attempt counter, while changing the tool, the file, or the
message produces a new target. That is what makes `REPEATED_FAILURE` and
`REGRESSION` meaningful instead of noisy.


## Library use

```python
from build_healer import HealLoop, build_plan, parse_log

plan = build_plan(parse_log(log_text), max_targets=3)
if plan["green"]:
    return "commit the working state"

for target in plan["targets"]:
    print(target["file"], target["line"], target["code"], target["message"])

loop = HealLoop(max_attempts_per_failure=3, max_rounds=8, max_stalled_rounds=2)

while True:
    log = run_build()                    # your subprocess call
    result = loop.observe(log_text=log)

    if result["green"]:
        break
    if not result["should_continue"]:
        raise SystemExit("\n".join(e["detail"] for e in result["escalations"]))

    agent.fix(result["advice"])          # one target, one edit
```

`observe()` also accepts `failures=[...]` if you already parsed the output
yourself. Every round dict contains `round`, `green`, `should_continue`,
`targets` (with `attempts`, `first_round`, `last_round`, `status`), `fixed`,
`regressed`, `repeated`, `escalations`, `summary`, `advisory_count` and
`advice`; `loop.status()` returns the whole run as one JSON-ready dict.

Passing the same log twice is not a stall: rounds are compared by fingerprint
set, so identical duplicate lines inside one round count as one attempt.

## CLI

```
build-healer plan LOG [--json] [--max-targets N]
build-healer rounds DIRECTORY [--json] [--max-attempts N] [--max-rounds N]
                              [--max-stalled-rounds N]
```

`plan` reads one log. `rounds` reads `*.log` / `*.txt` from a directory in
filename order — name them `round1.log`, `round2.log`, … — and feeds them to a
single `HealLoop`, which is how you replay a transcript after the fact.

| Exit | Meaning |
| --- | --- |
| `0` | green build / final round green |
| `1` | blocking errors / loop ended red |
| `2` | missing file or directory, empty directory, invalid argument |

`--json` emits the full structure (the same dicts the library returns), so a CI
job can archive it as an artifact:

```yaml
- name: Plan the fix
  run: build-healer plan build.log --json > healer.json
- name: Replay the rounds
  run: build-healer rounds runs/build --json
```

### In a harness loop

```python
import subprocess

log = subprocess.run(["pytest", "-q"], capture_output=True, text=True).stdout
result = loop.observe(log_text=log)
prompt += "\n\n" + result["advice"]
```

The healer never edits a file and never calls a model. It decides *what to look
at next* and *when to stop*; the agent still does the work.

## Scope

**It does.** Deterministic parsing, deduplication and budget accounting over
text you already produce; zero dependencies; Python 3.10+; identical results on
every platform (paths are normalised, no shell involved).

**It does not.** Invent fixes, verify that a fix is correct, run your build, or
read a compiler's mind. It trusts the log it is given: a log that hides an error
hides it from the healer too.

## Related

Part of the [`claude-oss-suite`](https://github.com/vanovri/claude-oss-suite):
[`agent-referee`](https://github.com/vanovri/agent-referee) for rubric-scored
review of finished work, [`redflag-loop`](https://github.com/vanovri/redflag-loop)
for evidence-gated loop guards, [`mcp-spatial-critic`](https://github.com/vanovri/mcp-spatial-critic)
for 3D-print mesh audits, and [`open-dmrv-engine`](https://github.com/vanovri/open-dmrv-engine)
for MRV-style measurement pipelines.

## Contributing

See [`GOOD_FIRST_ISSUES.md`](GOOD_FIRST_ISSUES.md). Tests are stdlib
`unittest`, no extra install:

```
python -m unittest discover -s tests -v
```

## License

MIT © Ardhya Novri Ramadhan

