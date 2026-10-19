# redflag-loop

**Your agent says "done". Make it prove it.**

`redflag-loop` is a tiny, dependency-free loop guard for autonomous coding
agents. It records every action, fingerprints it, and blocks the three failure
modes that burn your tokens: the same command on repeat, iterations that change
nothing, and the completion claim that arrives while the test suite is red.

No LLM calls. No network. No telemetry. Just a state machine you can drop into a
harness, a CI job, or a pre-commit hook.

```
# from GitHub — works today
pip install git+https://github.com/vanovri/redflag-loop

# from PyPI — once 0.1.0 is uploaded
pip install redflag-loop
redflag-loop check examples/loop_events.jsonl
```

```
events: 6  iterations: 5
status: REDFLAGS: LOOP_DETECTED, REDFLAGS_UNRESOLVED
  [LOOP_DETECTED] iteration 5: action ff0961a15540b0d0 repeated 3x in a row
  [REDFLAGS_UNRESOLVED] iteration 5: completion attempted with open redflags: LOOP_DETECTED
  event 0: allowed
  event 1: allowed
  event 2: allowed
  event 3: allowed
  event 4: LOOP_DETECTED
  event 5: REDFLAGS_UNRESOLVED
```

Exit code `1` means "the agent is stuck or lying". Wire that into CI and the
build fails on the transcript itself, not only on the diff.

## The problem

Three transcripts I have watched too many times:

1. **The loop.** `pytest -q` fails, the agent "fixes" a docstring, runs
   `pytest -q` again, gets the same failure, and repeats until the context
   window runs out.
2. **The treadmill.** Twenty iterations, forty edited lines, zero new files
   touched. Every step looks like work; nothing lands.
3. **The optimistic exit.** `Task complete!` — while the failing test is still
   in the output four lines above.

A prompt that says *do not loop* is a wish. `redflag-loop` turns that wish into
a mechanism: a checked guard the harness has to ask before it proceeds.

## Three rules and a gate

| Rule | Trigger | Code |
| --- | --- | --- |
| Same action, three times | Identical action signature (SHA-256 of canonical JSON) `max_identical` times consecutively | `LOOP_DETECTED` |
| No artifact | `max_iterations_without_progress` consecutive mutating iterations with no new artifact | `NO_PROGRESS` |
| Budget | Step count above `max_iterations` | `BUDGET_EXCEEDED` |
| Evidence gate | Completion claim with no passing `command` + `exit_code: 0` | `UNSUPPORTED_COMPLETION` |
| Ordering gate | Completion claim while any redflag is still open | `REDFLAGS_UNRESOLVED` |

Defaults: `max_identical=3`, `max_iterations=30`,
`max_iterations_without_progress=5`.

Read-only actions (`mutation=False`, e.g. `grep`, `read`) still count against
the iteration budget and against repeated-action detection, but never accrue
progress debt. Exploring for context is not a treadmill.

## Event format

One JSON object per line. Blank lines and `#` comments are ignored.

```jsonl
{"type": "action", "action": {"tool": "edit", "path": "src/app.py"}, "artifacts": ["src/app.py"]}
{"type": "action", "action": {"tool": "grep", "pattern": "TODO"}, "mutation": false}
{"type": "complete", "task": "T1", "evidence": [{"command": "pytest -q", "exit_code": 0, "output_tail": "12 passed"}]}
```

`action` is any JSON object; its canonical form is what gets hashed, so
`{"tool": "edit", "path": "a.py"}` and `{"path": "a.py", "tool": "edit"}` are
the same action. Put the discriminators that matter (command, path, args) in
there and leave timestamps and durations out.

## Library use

```python
from redflag_loop import LoopGuard

guard = LoopGuard(max_identical=3, max_iterations=30)

for step in agent_steps:
    decision = guard.record(step.action, artifacts=step.touched, mutation=step.writes)
    if not decision["allowed"]:
        # decision["redflag"]["code"] -> LOOP_DETECTED / NO_PROGRESS / BUDGET_EXCEEDED
        raise SystemExit(decision["reason"])

verdict = guard.claim_done("T1", evidence=[{"command": "pytest -q", "exit_code": 0}])
assert verdict["accepted"]
```

Or pass a whole transcript:

```python
from redflag_loop import replay
report = replay(events)
report["clean"]        # False
report["open_codes"]   # ['LOOP_DETECTED', 'REDFLAGS_UNRESOLVED']
report["results"]      # one dict per event, in order
```

Every decision dict carries `allowed`, `redflag`, `reason`, `iteration`,
`signature`, `repeat_streak` and `new_artifacts`, so a harness can log exactly
why it was stopped.

## CLI

```
redflag-loop check LOG [--json] [--max-identical N] [--max-iterations N]
                        [--max-iterations-without-progress N]
```

| Exit | Meaning |
| --- | --- |
| `0` | Transcript is clean |
| `1` | At least one redflag |
| `2` | Log missing, unreadable, or invalid JSON |

`--json` prints the full report for dashboards. In CI:

```yaml
- name: Grade the agent transcript
  run: redflag-loop check runs/agent.jsonl --json
```

## Scope

**It does.** Deterministic, auditable machine checks over an event log;
zero dependencies; Python 3.10+.

**It does not.** Judge whether the work is *good*, watch a live agent, or stop
one by force. It sees only what the harness reports — an agent that never logs
its actions is out of reach, and a harness that fabricates `exit_code: 0` will
fool it. Pair it with a real test run: the guard is only as honest as the log.

The evidence gate is the part worth trusting: it refuses completion on anything
other than a recorded command that exited `0`, and refuses that completion
while any earlier redflag is still open.

## Related

Part of the [`claude-oss-suite`](https://github.com/vanovri/claude-oss-suite):
[`agent-referee`](https://github.com/vanovri/agent-referee) for rubric-scored
review of finished work, [`mcp-spatial-critic`](https://github.com/vanovri/mcp-spatial-critic)
for 3D-print mesh audits, [`claude-build-healer`](https://github.com/vanovri/claude-build-healer)
for fix-loop discipline on failing builds, and
[`open-dmrv-engine`](https://github.com/vanovri/open-dmrv-engine) for
MRV-style measurement pipelines.

## Contributing

See [`GOOD_FIRST_ISSUES.md`](GOOD_FIRST_ISSUES.md). Tests are stdlib
`unittest`, no extra install:

```
python -m unittest discover -s tests -v
```

## License

MIT © Ardhya Novri Ramadhan
