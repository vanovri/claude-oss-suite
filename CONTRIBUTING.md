# Contributing

Thanks for helping make autonomous coding agents verifiable. This suite is
deliberately built so that **one contributor can land one file** in under an hour.

## Ground rules

- Standard library only. A PR that adds a runtime dependency needs a very good reason.
- Every behaviour change ships with a test in `tests/` that fails before the change.
- Keep public function signatures stable; `agent-referee` exists because signature
  churn breaks downstream CI.
- Run the full suite locally before opening the PR:

```bash
python -m unittest discover -s tests -v
```

## The three easiest contribution shapes

**1. Add a compiler adapter** (`claude-build-healer/build_healer/adapters/`)

Create one module exposing `NAME` and `PATTERN`; the registry discovers it
automatically:

```python
# build_healer/adapters/go_build.py
import re

NAME = "go_build"
PATTERN = re.compile(
    r"^(?P<file>[^\s:]+\.go):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.+)$",
    re.MULTILINE,
)
```

**2. Add an exploit rule** (`redflag-loop/redflag_loop/rules/`)

Subclass `ExploitRule`, implement `probe(handler) -> str | None` (return the
evidence string when the handler is still vulnerable, `None` when it is blocked),
then add the rule to `RULES` in `redflag_loop/rules/__init__.py`.

**3. Add a CAD preset or a carbon methodology**

- `mcp-spatial-critic/presets/*.scad` — parametric OpenSCAD, must stay dimension-driven.
- `open-dmrv-engine/open_dmrv/methodologies/*.py` — one `Methodology` instance with
  documented permanence factor and thermal window, plus a reference to the
  published methodology it encodes.

## Pull request checklist

- [ ] `python -m unittest discover -s tests -v` is green
- [ ] New code has a docstring explaining *the invariant it enforces*
- [ ] `GOOD_FIRST_ISSUES.md` entry removed/updated if you closed one
- [ ] No network access, no API keys, no wall-clock dependence in scoring logic

## Commit style

`feat(adapter): add go build parser` / `fix(merkle): handle odd leaf counts`

## Code of conduct

Be precise, be kind, assume the other person is optimizing for correctness too.
