# Good first issues — claude-build-healer

Nine scoped, unclaimed issues. Each has a fixture, a before/after, and a test
command. Comment on the issue you want and open a PR against `main`.

```
python -m unittest discover -s tests -v
```

Current state: 57 tests, stdlib `unittest`, no dependencies.

---

## 1. Java grammar (javac + Maven)

**Labels:** `good first issue`, `parser`, `enhancement`

`javac` and `mvn` print errors the current grammars miss, so they fall through
to `generic` and lose the file and line:

```
[ERROR] /home/ci/src/main/java/app/Main.java:[12,5] cannot find symbol
src/Main.java:12: error: ';' expected
```

**Do:** add `parse_javac` + `_scan_javac` to `build_healer/parsers.py` handling
both shapes, strip the `[ERROR] ` prefix, and register it in `SCANNERS` before
`gcc` (a `file.java:[12,5]` line must not be read as a Go or GCC diagnostic).

**Done when:** `examples/javac_failure.log` exists, `tests/test_parsers.py`
asserts file/line/column/code for both shapes, and a mixed log still dedupes to
one target per error.

---

## 2. `plan --format github` annotations

**Labels:** `good first issue`, `cli`, `integrations`

A target should appear as an inline annotation on the PR, not only in the log.

**Do:** add `--format {text,json,github}` to `plan` (keep `--json` as an alias
for `--format json`). For each blocking target emit:

```
::error file=src/app.ts,line=12,col=5,title=TS2322::Type 'string' is not assignable to type 'number'.
```

Advisory warnings use `::warning`. Targets without a file fall back to the log
path with `line=1`.

**Done when:** `tests/test_cli.py` asserts the exact annotation for a tsc
fixture, and the README documents the flag.

---

## 3. `build-healer history DIRECTORY FINGERPRINT`

**Labels:** `good first issue`, `cli`, `dx`

When a `REPEATED_FAILURE` fires, the first question is "since when?". The data
is already in `loop.targets`, but only as a Python object.

**Do:** add a `history` subcommand that replays a directory of rounds and prints
one line per round for one fingerprint:

```
round 1  open     first seen
round 2  open     unchanged (line 12 -> 14)
round 3  open     unchanged
round 4  fixed
```


---

## 4. Baseline diff: `plan --baseline previous.json`

**Labels:** `good first issue`, `cli`, `enhancement`

On a big repository, most errors in a log are old news. Teams want "what is new
since the last green build?".

**Do:** accept a JSON file produced by an earlier `build-healer plan --json` and
add a `new` key (`true`/`false`) to every target, plus a `--new-only` flag that
prints just the additions. Unknown or corrupt baseline → exit `2`, never a
traceback.

**Done when:** the behaviour is tested with a plan file written by the CLI
itself (no hand-written fixtures), and `--new-only` on an unchanged build prints
nothing and exits `0`.

---

## 5. Windows paths in every grammar

**Labels:** `good first issue`, `parser`, `testing`

`C:\work\app\src\app.ts(12,5): error TS2322: ...` currently keeps the drive
letter in the file, so `group_by_file` splits one file into two entries and the
hotspot advice misses it.

**Do:** normalise paths once, in `Failure.__post_init__` or a shared helper:
collapse `\\`, keep the drive letter, strip a leading `./`. Then assert every
grammar accepts both separators.

**Done when:** a new `PathTests` class proves `C:\a\b.ts` and `C:/a/b.ts` share
a fingerprint, `C:\a\b.ts` and `D:\a\b.ts` do not, and the existing 57 tests
still pass.

---

## 6. SARIF output for code scanning

**Labels:** `good first issue`, `integrations`, `reporting`

GitHub code scanning ingests SARIF, which would let a healer plan show up in the
Security tab next to the real linters.

**Do:** add `--format sarif` to `plan`. Emit a minimal SARIF 2.1.0 document with
one `run`, one `tool.driver` named `claude-build-healer`, and one `result` per
blocking target using `ruleId` = code (or tool when absent), `level` = `error`,
and a `physicalLocation` with `artifactLocation.uri` + `region.startLine`.
Validate the JSON shape in a test; no schema download.

**Done when:** the output parses with `json.loads`, has `version == "2.1.0"`,
and every target maps to exactly one result.

Show line movement when the underlying `Failure.line` changes. Exit `0` if the
fingerprint is not found, `1` if it was never fixed.


---

## 7. Group errors that share a root cause

**Labels:** `good first issue`, `enhancement`, `core`

Six `TS2345` errors with the same message in six files are usually one wrong
type exported six times. Today they are six independent targets, which inflates
`REPEATED_FAILURE` and hides the cause.

**Do:** add `group_by_message(failures)` returning `{(tool, code, normalized
message): [failures]}` and surface it in `build_plan` as a `families` list with
`count` and `files`. Do not change the target list or the loop semantics — this
is an additive view.

**Done when:** `tests/test_core.py` proves a family spanning three files reports
`count: 3`, and families of one are omitted.

---

## 8. Ignore rules and severity overrides

**Labels:** `good first issue`, `config`, `enhancement`

Vendored code and generated files produce errors nobody will fix, and some teams
want a specific warning to be blocking.

**Do:** read an optional `healer.toml` (stdlib `tomllib`, Python 3.11+; skip the
test on 3.10) with two keys:

```toml
ignore = ["vendor/**", "*_generated.go"]
blocking = ["TS6133"]
```

Apply `ignore` to file paths (fnmatch) before planning, and treat codes listed in
`blocking` as blocking even when their severity is `warning`.

**Done when:** tests cover an ignored vendor path, a promoted warning, and a
missing config file (no error).

---

## 9. Property test: moving lines never looks like a regression

**Labels:** `good first issue`, `testing`

The safety property behind `REGRESSION` and `REPEATED_FAILURE` is: if a round
contains the same errors with shifted line numbers, the loop must report them as
`repeated`, never as `regressed`, and `fixed` must stay empty.

**Do:** add a seeded, stdlib-only randomised test (`random.Random(1234)`) that
generates 200 sequences of rounds from a fixed error pool, randomly shifts line
numbers and inserts duplicates, and asserts the invariant above for every round.
No new dependencies, under a second.

**Done when:** the test fails if line numbers are added to the fingerprint
(try it: add `line` to the hash input and watch it go red).

**Done when:** `tests/test_cli.py` covers a fingerprint that is fixed, one that
escalates, and one that never appears.
