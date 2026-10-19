# agent-referee

> **Cryptographic testbench lock & anti-reward-hacking gate for autonomous coding agents** (Claude Code, Codex, Antigravity, any agent that can edit your repo).

[![CI](https://github.com/vanovri/agent-referee/actions/workflows/ci.yml/badge.svg)](https://github.com/vanovri/agent-referee/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/badge/pypi-agent--referee--gate-blue)](https://pypi.org/project/agent-referee-gate/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

Coding agents optimise for the objective you gave them. If the objective is
"make the tests pass", the cheapest strategy is often to **delete the failing
test**, **drop the failing assertion**, or **stub the function under test**.
`agent-referee` makes that strategy fail loudly, in CI, in under a second.

## What it enforces

| Gate | Failure mode it kills | Exit code |
| --- | --- | --- |
| SHA-256 per test file | deleting or rewriting a test file | `2` |
| AST assertion floor | `assert` / `self.assertX()` removed to fake a pass | `2` |
| Syntax check | committing broken tests to silence the counter | `2` |
| Runtime budget | "fixing" a test by making the suite 10x slower | `4` |
| Suite re-run | patch that leaves the suite red | `3` |

## Install

```bash
# from GitHub — works today
pip install git+https://github.com/vanovri/agent-referee

# from PyPI — once 0.1.0 is uploaded
pip install agent-referee-gate
```

The PyPI name `agent-referee` already belongs to an unrelated project, so the
distribution here is `agent-referee-gate` while the command stays
`agent-referee`.

## Usage (human)

```bash
# 1. Once, on a green main branch: freeze the testbench
agent-referee lock --tests tests --cmd "python -m unittest discover -s tests -q"

# 2. After an agent ran: verify nothing was hacked
agent-referee verify
# [PASS] testbench intact (3 files) | runtime 412.7 ms (baseline 401.2 ms, delta +2.9%)
```

Exit codes: `0` clean · `1` usage · `2` reward hacking · `3` suite red · `4` perf regression.

The lock file is plain JSON and is meant to be committed:

```json
{
  "schema_version": 1,
  "test_dir": "tests",
  "test_cmd": "python -m unittest discover -s tests -q",
  "baseline_runtime_ms": 401.2,
  "files": {
    "tests/test_api.py": {
      "sha256": "9f2b…",
      "assertions": 14,
      "size_bytes": 812
    }
  }
}
```

## Usage (GitHub Actions)

```yaml
name: agent-work
on: [pull_request]

jobs:
  referee:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: vanovri/agent-referee@v0.1.0
        with:
          test-dir: tests
          test-cmd: "python -m unittest discover -s tests -q"
          max-regression-pct: "20"
```

## Library use

```python
from agent_referee import build_lock_manifest, verify_manifest, scan_test_directory

locked = build_lock_manifest({"tests/test_api.py": "def test_x():\n    assert 1\n"})
current = scan_test_directory("tests")
violations = verify_manifest(locked, current)
if violations:
    raise SystemExit("\n".join(violations))
```

## Scope and honest limits

- The runtime gate is wall-clock and therefore advisory-noise-prone on shared
  CI runners; keep `max-regression-pct` generous (20–50) or run it on a
  dedicated runner. Integrity gates (hash + assertions) are fully deterministic.
- Only Python tests are AST-counted today. JS/TS, Rust and Go counters are
  tracked in [`GOOD_FIRST_ISSUES.md`](GOOD_FIRST_ISSUES.md) — those are text
  checksum gates until then.
- This tool detects *test tampering*, not *semantic cheating* (e.g. hard-coding
  the expected value in production code). Pair it with `redflag-loop` and
  property-based tests.

## Contributing

See [`GOOD_FIRST_ISSUES.md`](GOOD_FIRST_ISSUES.md) — the whole package is one
pure-logic module plus a thin CLI, so an adapter lands in a single file.

MIT © 2026 Ardhya Novri Ramadhan
