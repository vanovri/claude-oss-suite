# Good first issues — `agent-referee`

Self-contained, one-file tasks. Comment `I'll take this` on the matching GitHub
issue and open a PR against `main`; the whole package is `core.py` (pure logic)
plus `cli.py` (I/O), so nothing here requires deep context.

1. **Add a Jest / Vitest assertion counter**
   - Files: `agent_referee/core.py`, `tests/test_core.py`
   - Do: `count_js_assertions(source)` counting `expect(...)` chains (`.toBe`, `.toEqual`, …) and `assert.*` calls; reuse the `-1 on parse failure` contract via a regex pre-check.
   - Done when: tests cover pass-through, weakened file and unparseable file.

2. **Add a Rust `#[test]` + `assert_eq!` counter**
   - Files: `agent_referee/core.py`, `tests/test_core.py`
   - Do: `count_rust_assertions(source)` skipping `#[cfg(test)]`-free files; count `assert!`, `assert_eq!`, `assert_ne!`, `debug_assert*!`.
   - Done when: a file with 3 macros returns 3.

3. **Add a Go `*_test.go` table-test counter**
   - Files: `agent_referee/core.py`, `tests/test_core.py`
   - Do: count `t.Error*`, `t.Fatal*` and `if … != …` blocks inside `func Test*` bodies.
   - Done when: deleting one assertion lowers the count.

4. **`pytest` plugin: auto-lock on first run, auto-verify afterwards**
   - Files: new `agent_referee/pytest_plugin.py`, `pyproject.toml` (`[project.entry-points.pytest11]`)
   - Do: `pytest_configure` verifies when `.referee_lock.json` exists, otherwise writes it once.
   - Done when: `pytest` twice in a row keeps the lock byte-identical.

5. **PR comment reporter for GitHub Actions**
   - Files: new `agent_referee/report.py`, `action.yml`
   - Do: render violations as a Markdown table and post it with `gh pr comment` when `GITHUB_TOKEN` is present.
   - Done when: the action outputs `summary` and a comment body can be generated offline in a test.

6. **`--json` output mode for both subcommands**
   - Files: `agent_referee/cli.py`, `tests/test_cli.py`
   - Do: emit `{"status": "pass|fail", "violations": [...], "runtime_ms": …}` on stdout for machine consumption.
   - Done when: exit codes stay unchanged and JSON parses.

7. **Allow an explicit allow-list of mutable test files**
   - Files: `agent_referee/core.py`, `agent_referee/cli.py`
   - Do: `--allow tests/test_generated_*.py` glob, documented as a deliberate escape hatch (e.g. snapshot files).
   - Done when: allow-listed rewrites pass, everything else still fails with code `2`.

8. **Detect assertion-count inflation (assertion stuffing)**
   - Files: `agent_referee/core.py`, `tests/test_core.py`
   - Do: flag a file whose assertion count more than doubles while the suite gets slower, as a heuristic `SUSPICIOUS_ASSERTION_INFLATION` warning (never a hard failure).
   - Done when: covered by tests and documented in the README limits section.

9. **Baseline drift helper**
   - Files: `agent_referee/cli.py`
   - Do: `agent-referee relock --reason "..."` re-locks and appends the reason to a `CHANGELOG` block inside the lock file, so reviewers see why the baseline moved.
   - Done when: relock keeps `files` sorted and records the reason.
