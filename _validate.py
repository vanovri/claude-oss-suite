"""Validate packaging and automation metadata across the claude-oss-suite repos.

Run from anywhere:  python _validate.py
Exit code 0 = every check passed.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPOS = [
    "agent-referee",
    "mcp-spatial-critic",
    "redflag-loop",
    "claude-build-healer",
    "open-dmrv-engine",
]

failures: list[str] = []
notes: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def load_toml(path: Path) -> dict | None:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        failures.append(f"{path.relative_to(ROOT)}: missing")
    except Exception as exc:  # noqa: BLE001 - report any parse error
        failures.append(f"{path.relative_to(ROOT)}: {exc}")
    return None


try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - optional local dependency
    yaml = None
    notes.append("PyYAML not installed: YAML files were not parsed, only presence-checked")


for repo in REPOS:
    base = ROOT / repo
    check(base.is_dir(), f"{repo}: directory missing")
    if not base.is_dir():
        continue

    for required in ("README.md", "LICENSE", ".gitignore"):
        check((base / required).is_file(), f"{repo}/{required}: missing")

    data = load_toml(base / "pyproject.toml")
    if data is not None:
        project = data.get("project", {})
        check(bool(project.get("name")), f"{repo}/pyproject.toml: missing project.name")
        check(bool(project.get("version")), f"{repo}/pyproject.toml: missing version")
        check(
            bool(project.get("requires-python")),
            f"{repo}/pyproject.toml: missing requires-python",
        )
        packages = data.get("tool", {}).get("setuptools", {}).get("packages")
        check(bool(packages), f"{repo}/pyproject.toml: missing [tool.setuptools] packages")
        if packages:
            for package in packages:
                check(
                    (base / package / "__init__.py").is_file(),
                    f"{repo}/pyproject.toml: package {package!r} has no __init__.py",
                )
        check(
            bool(data.get("build-system", {}).get("build-backend")),
            f"{repo}/pyproject.toml: missing build-backend",
        )
        notes.append(f"{repo}: toml OK ({project.get('name')} {project.get('version')})")

    for yaml_file in list(base.rglob("*.yml")) + list(base.rglob("*.yaml")):
        text = yaml_file.read_text(encoding="utf-8")
        check(bool(text.strip()), f"{yaml_file.relative_to(ROOT)}: empty")
        if yaml is not None:
            try:
                parsed = yaml.safe_load(text)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{yaml_file.relative_to(ROOT)}: {exc}")
                continue
            check(isinstance(parsed, dict), f"{yaml_file.relative_to(ROOT)}: not a mapping")
        notes.append(f"{yaml_file.relative_to(ROOT)}: present")

    action = base / "action.yml"
    if action.is_file():
        text = action.read_text(encoding="utf-8")
        check("runs:" in text or "using:" in text, f"{repo}/action.yml: missing runs/using")
        if yaml is not None:
            try:
                parsed = yaml.safe_load(text)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{repo}/action.yml: {exc}")
            else:
                check("runs" in parsed, f"{repo}/action.yml: missing runs section")

    tests_dir = base / "tests"
    test_files = sorted(tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []
    check(bool(test_files), f"{repo}/tests: no test_*.py found")

print("\n".join(notes))
if failures:
    print("\nFAILURES:")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)
print("\nAll metadata checks passed.")
