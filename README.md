# Claude OSS Suite — deterministic verification infrastructure for autonomous coding agents

Five small, composable open-source tools that make unattended AI coding runs
**safe, auditable and token-efficient**. Every package is installable in one
`pip install`, ships with a deterministic unit-test suite, and runs as a CLI in
CI; the two signing gates ([`agent-referee`](agent-referee/) and
[`open-dmrv-engine`](open-dmrv-engine/)) also ship composite GitHub Actions.

| Repo | What it guarantees | CLI | Install |
| --- | --- | --- | --- |
| [`agent-referee`](agent-referee/) | Failing tests can never be deleted, weakened or rewritten by an agent (SHA-256 lock + AST assertion floor + runtime regression gate) | `agent-referee` | `pip install agent-referee-gate` |
| [`redflag-loop`](redflag-loop/) | A security patch is only accepted after the exploit is *proven* against the old handler and *blocked* by the new one | `redflag-loop` | `pip install redflag-loop` |
| [`claude-build-healer`](claude-build-healer/) | 5,000-line compiler dumps become a <300-token diagnostic JSON with source context | `build-healer` | `pip install claude-build-healer` |
| [`mcp-spatial-critic`](mcp-spatial-critic/) | STL meshes are manifold, grounded on Z=0, single-shell and thick enough to print | `mcp-spatial-critic` | `pip install mcp-spatial-critic` |
| [`open-dmrv-engine`](open-dmrv-engine/) | Pyrolysis telemetry cannot violate mass balance, thermal regime or H/C_org permanence before a Merkle root is signed | `open-dmrv` | `pip install open-dmrv-engine` |

## Quick start (all five, offline)

```bash
# from the suite root, run every deterministic suite (231 tests, no deps)
for d in agent-referee redflag-loop claude-build-healer mcp-spatial-critic open-dmrv-engine; do
  (cd "$d" && python -m unittest discover -s tests -q)
done

# structural check: pyproject metadata, actions, CI workflows
python _validate.py
```

On Windows PowerShell:

```powershell
foreach ($r in 'agent-referee','redflag-loop','claude-build-healer','mcp-spatial-critic','open-dmrv-engine') {
  Push-Location $r; python -m unittest discover -s tests -q; Pop-Location
}
python _validate.py
```

Or work on a single package:

```bash
cd agent-referee
python -m venv .venv && .venv/Scripts/activate      # Windows
python -m unittest discover -s tests -v
python -m agent_referee.cli lock --tests tests --cmd "python -m unittest discover -s tests -q"
python -m agent_referee.cli verify
```

## Design rules of the suite

1. **No silent passes.** Every gate exits non-zero with a machine-readable reason.
2. **Deterministic.** No network calls, no LLM calls, no clocks inside the scoring logic.
3. **Dependency-light.** Standard library only — auditability beats convenience.
4. **Tiny surface, real logic.** Each package is one pure-logic module plus a thin CLI,
   so contributors can add an adapter/rule/methodology in a single file.
5. **Physics and cryptography are hard gates**, never "warnings that get ignored".

## Releasing

Each folder is published as its own repository and its own PyPI project; the
suite repo stays as the monorepo source of truth.

```bash
# 1. split one package into its own repo (history preserved)
git subtree push --prefix=open-dmrv-engine git@github.com:vanovri/open-dmrv-engine.git main

# 2. every repo: tag the release the READMEs reference
git tag -a v0.1.0 -m "open-dmrv-engine 0.1.0" && git push origin v0.1.0

# 3. build and upload (test index first)
python -m pip install --upgrade build twine
cd open-dmrv-engine
python -m build                       # sdist + wheel in dist/
python -m twine upload --repository testpypi dist/*
python -m twine upload dist/*
```

`_validate.py` must print `All metadata checks passed.` before tagging: it checks
that each `pyproject.toml` parses, that declared actions exist, and that every
repo has a CI workflow. PyPI trusted publishing (OIDC) is preferable to a stored
token — add `pypi` as a trusted publisher for each project and upload from the
`package` job of its workflow.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Every repo carries a
`GOOD_FIRST_ISSUES.md` with self-contained, one-file tasks (adapters, presets, rules,
methodologies) designed to be merged without deep context.

## License

MIT © 2026 Ardhya Novri Ramadhan
