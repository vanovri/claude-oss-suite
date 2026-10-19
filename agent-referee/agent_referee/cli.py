"""``agent-referee`` command line gate (used by CI and the GitHub Action).

Exit codes are part of the public contract so that pipelines can branch on them:

======  ==================================================================
code    meaning
======  ==================================================================
0       testbench intact, suite green, no runtime regression
1       usage error (missing lock file, missing test directory, bad args)
2       reward hacking detected (deleted / rewritten / weakened tests)
3       test suite failed after the agent's changes
4       runtime regression above the allowed budget
======  ==================================================================
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from .core import (
    LOCKFILE_NAME,
    make_lock_payload,
    read_lock,
    scan_test_directory,
    verify_manifest,
    write_lock,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REWARD_HACK = 2
EXIT_TEST_FAILURE = 3
EXIT_PERF_REGRESSION = 4

DEFAULT_TEST_CMD = "python -m unittest discover -s tests -q"


def _resolve(root: Path, target: str) -> Path:
    path = Path(target)
    return path if path.is_absolute() else (root / path)


def _run_suite(cmd: str, cwd: Path):
    """Run the suite once, returning ``(completed_process, elapsed_ms)``."""
    started = time.perf_counter()
    proc = subprocess.run(
        cmd, shell=True, cwd=str(cwd), capture_output=True, text=True
    )
    return proc, (time.perf_counter() - started) * 1000.0


def _tail(text: str, limit: int = 40) -> str:
    lines = (text or "").strip().splitlines()
    return "\n".join(lines[-limit:])


def lock(root: Path, test_dir: str, test_cmd: str) -> int:
    """Freeze the current test suite as the immutable baseline."""
    root = Path(root)
    test_path = _resolve(root, test_dir)
    if not test_path.is_dir():
        print(f"[REFEREE] ERROR: test directory not found: {test_path}")
        return EXIT_USAGE

    manifest = scan_test_directory(test_path)
    if not manifest:
        print(f"[REFEREE] ERROR: no *.py test files found under {test_path}")
        return EXIT_USAGE

    proc, baseline_ms = _run_suite(test_cmd, root)
    if proc.returncode != 0:
        print("[REFEREE] ERROR: baseline suite must be green before locking.")
        print(_tail(proc.stdout + "\n" + proc.stderr))
        return EXIT_TEST_FAILURE

    payload = make_lock_payload(
        test_dir=test_dir,
        test_cmd=test_cmd,
        manifest=manifest,
        baseline_runtime_ms=baseline_ms,
    )
    lock_path = write_lock(root / LOCKFILE_NAME, payload)
    assertions = sum(meta["assertions"] for meta in manifest.values())
    print(
        f"[LOCKED] {len(manifest)} files / {assertions} assertions | "
        f"baseline {baseline_ms:.1f} ms -> {lock_path}"
    )
    return EXIT_OK


def verify(
    root: Path,
    test_cmd: Optional[str] = None,
    max_regression_pct: float = 20.0,
) -> int:
    """Re-check integrity, then re-run the suite and the runtime budget."""
    root = Path(root)
    lock_path = root / LOCKFILE_NAME
    if not lock_path.exists():
        print(
            f"[REFEREE] ERROR: {LOCKFILE_NAME} not found in {root}. "
            "Run 'agent-referee lock' first."
        )
        return EXIT_USAGE

    locked = read_lock(lock_path)
    test_path = _resolve(root, locked["test_dir"])
    current = scan_test_directory(test_path)

    violations = verify_manifest(locked["files"], current)
    if violations:
        for violation in violations:
            print(f"[FAIL] {violation}")
        return EXIT_REWARD_HACK

    cmd = test_cmd or locked["test_cmd"]
    proc, elapsed_ms = _run_suite(cmd, root)
    if proc.returncode != 0:
        print("[FAIL] test suite failed after agent changes:")
        print(_tail(proc.stdout + "\n" + proc.stderr))
        return EXIT_TEST_FAILURE

    baseline_ms = float(locked.get("baseline_runtime_ms", 0.0))
    delta_pct = (elapsed_ms - baseline_ms) / max(baseline_ms, 1.0) * 100.0
    tag = "PASS" if delta_pct <= max_regression_pct else "FAIL"
    print(
        f"[{tag}] testbench intact ({len(current)} files) | runtime "
        f"{elapsed_ms:.1f} ms (baseline {baseline_ms:.1f} ms, "
        f"delta {delta_pct:+.1f}%)"
    )
    if delta_pct > max_regression_pct:
        print(
            f"[FAIL] runtime regression {delta_pct:+.1f}% exceeds "
            f"{max_regression_pct:.1f}% budget"
        )
        return EXIT_PERF_REGRESSION
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-referee",
        description="Immutable testbench lock / anti-reward-hacking gate.",
    )
    parser.add_argument("--version", action="version", version="agent-referee 0.1.0")
    sub = parser.add_subparsers(dest="command")

    p_lock = sub.add_parser("lock", help="freeze the test suite as the baseline")
    p_lock.add_argument("--root", default=".", help="repository root (default: .)")
    p_lock.add_argument(
        "--tests", default="tests", help="test directory (default: tests)"
    )
    p_lock.add_argument("--cmd", default=DEFAULT_TEST_CMD, help="test command to run")

    p_verify = sub.add_parser("verify", help="verify integrity + runtime budget")
    p_verify.add_argument("--root", default=".", help="repository root (default: .)")
    p_verify.add_argument(
        "--cmd", default=None, help="override the locked test command"
    )
    p_verify.add_argument(
        "--max-regression-pct",
        type=float,
        default=20.0,
        help="allowed runtime regression percentage (default: 20)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "lock":
        return lock(Path(args.root), args.tests, args.cmd)

    if args.command in (None, "verify"):
        return verify(
            Path(getattr(args, "root", ".")),
            getattr(args, "cmd", None),
            getattr(args, "max_regression_pct", 20.0),
        )

    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
