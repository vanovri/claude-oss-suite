"""Pure, side-effect-free logic for the immutable testbench referee.

Nothing in here spawns processes or talks to the network: the CLI layer
(``agent_referee.cli``) owns all I/O so that every rule below stays trivially
testable and deterministic.

The three invariants enforced against an agent's diff are:

1. **Existence**  — a locked test file may not be deleted.
2. **Integrity**  — a locked test file may not be rewritten (SHA-256).
3. **Strength**   — the number of ``assert`` statements / ``.assert*()`` calls
   may never drop (prevents "make the test pass by deleting the assertion").
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

LOCKFILE_NAME = ".referee_lock.json"
LOCK_SCHEMA_VERSION = 1
IGNORED_PATH_PARTS = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv"}
)


def sha256_text(content: str) -> str:
    """SHA-256 of a UTF-8 string, hex encoded."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    """SHA-256 of raw bytes, hex encoded."""
    return hashlib.sha256(payload).hexdigest()


def count_ast_assertions(source_code: str) -> int:
    """Count executable assertions in Python source.

    Counts ``assert`` statements plus every ``self.assertXxx(...)`` style call.
    Returns ``-1`` when the file does not parse, which callers must treat as a
    hard violation (an agent must not be able to silence the counter by
    committing syntactically broken tests).
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return -1

    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            count += 1
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr.startswith("assert"):
                count += 1
    return count


def _relative_key(path: Path, test_dir: Path) -> str:
    """Stable, OS independent manifest key (e.g. ``tests/test_api.py``)."""
    try:
        return path.resolve().relative_to(test_dir.resolve().parent).as_posix()
    except ValueError:  # pragma: no cover - only when test_dir is not a parent
        return path.as_posix()


def iter_test_files(test_dir: Path) -> Iterable[Path]:
    """Yield every ``*.py`` file under ``test_dir`` in deterministic order."""
    test_dir = Path(test_dir)
    if not test_dir.exists():
        return
    for path in sorted(test_dir.rglob("*.py")):
        if any(part in IGNORED_PATH_PARTS for part in path.parts):
            continue
        yield path


def build_lock_manifest(files_map: Mapping[str, str]) -> Dict[str, dict]:
    """Build the manifest payload from ``{relative_path: source_code}``."""
    manifest: Dict[str, dict] = {}
    for rel_path, code in sorted(files_map.items()):
        manifest[rel_path] = {
            "sha256": sha256_text(code),
            "assertions": count_ast_assertions(code),
            "size_bytes": len(code.encode("utf-8")),
        }
    return manifest


def scan_test_directory(test_dir: Path) -> Dict[str, dict]:
    """Hash every test file on disk into a manifest."""
    test_dir = Path(test_dir)
    files_map: Dict[str, str] = {}
    for path in iter_test_files(test_dir):
        files_map[_relative_key(path, test_dir)] = path.read_text(
            encoding="utf-8", errors="ignore"
        )
    return build_lock_manifest(files_map)


def verify_manifest(
    locked: Mapping[str, dict],
    current: Mapping[str, dict],
    baseline_runtime_ms: Optional[float] = None,
    current_runtime_ms: Optional[float] = None,
    max_regression_pct: float = 20.0,
) -> List[str]:
    """Return every violation found, in a deterministic order.

    An empty list means the testbench is intact and (when runtimes are given)
    the suite did not regress beyond ``max_regression_pct``.
    """
    violations: List[str] = []

    for rel_path in sorted(locked):
        meta = locked[rel_path]
        if rel_path not in current:
            violations.append(f"DELETED_TEST_FILE: {rel_path}")
            continue

        cur = current[rel_path]
        if cur["sha256"] != meta["sha256"]:
            violations.append(f"MODIFIED_IMMUTABLE_TEST: {rel_path}")
        if cur["assertions"] < meta["assertions"]:
            violations.append(
                f"ASSERTION_WEAKENED: {rel_path} "
                f"({meta['assertions']} -> {cur['assertions']})"
            )
        if cur["assertions"] < 0:
            violations.append(f"UNPARSEABLE_TEST_FILE: {rel_path}")

    if (
        not violations
        and baseline_runtime_ms is not None
        and current_runtime_ms is not None
    ):
        baseline = max(float(baseline_runtime_ms), 1.0)
        delta_pct = (float(current_runtime_ms) - baseline) / baseline * 100.0
        if delta_pct > max_regression_pct:
            violations.append(
                f"PERFORMANCE_REGRESSION: {delta_pct:+.1f}% exceeds "
                f"{max_regression_pct:.1f}% budget"
            )

    return violations


def write_lock(lock_path: Path, payload: Mapping[str, object]) -> Path:
    """Persist a lock payload as pretty, sorted JSON."""
    lock_path = Path(lock_path)
    lock_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return lock_path


def read_lock(lock_path: Path) -> dict:
    """Load a lock payload. Raises ``FileNotFoundError`` when absent."""
    lock_path = Path(lock_path)
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "files" not in data:
        raise ValueError(f"Corrupt referee lock: {lock_path}")
    return data


def make_lock_payload(
    test_dir: str,
    test_cmd: str,
    manifest: Mapping[str, dict],
    baseline_runtime_ms: float,
) -> dict:
    """Assemble a schema-versioned lock payload."""
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "test_dir": test_dir,
        "test_cmd": test_cmd,
        "baseline_runtime_ms": round(float(baseline_runtime_ms), 2),
        "file_count": len(manifest),
        "files": dict(manifest),
    }
