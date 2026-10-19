"""``redflag-loop`` command line: replay a JSONL agent event log.

Exit codes
----------
``0`` the log is clean
``1`` at least one redflag was raised
``2`` the log is missing or contains invalid JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .core import (
    DEFAULT_MAX_IDENTICAL,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_ITERATIONS_WITHOUT_PROGRESS,
    replay,
)

EXIT_CLEAN = 0
EXIT_REDFLAG = 1
EXIT_BAD_INPUT = 2


def load_events(path: str) -> List[Any]:
    """Read JSONL, ignoring blank lines and ``#`` comments."""
    events: List[Any] = []
    content = Path(path).read_text(encoding="utf-8")
    for number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            events.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON ({exc.msg})") from exc
    return events


def render_summary(report: Dict[str, Any]) -> str:
    lines = [
        f"events: {report['events']}  iterations: {report['iterations']}",
        "status: " + ("CLEAN" if report["clean"] else "REDFLAGS: " + ", ".join(report["open_codes"])),
    ]
    for redflag in report["redflags"]:
        lines.append(
            f"  [{redflag['code']}] iteration {redflag['iteration']}: {redflag['detail']}"
        )
    for index, result in enumerate(report["results"]):
        raised = result.get("redflag")
        if raised:
            verdict = raised["code"]
        elif result.get("accepted") or result.get("allowed"):
            verdict = "accepted" if "accepted" in result else "allowed"
        else:
            verdict = "refused"
        lines.append(f"  event {index}: {verdict}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redflag-loop",
        description="Evidence-gated loop guard for autonomous coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="replay a JSONL event log")
    check.add_argument("log", help="path to a .jsonl event log")
    check.add_argument("--max-identical", type=int, default=DEFAULT_MAX_IDENTICAL)
    check.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    check.add_argument(
        "--max-iterations-without-progress",
        type=int,
        default=DEFAULT_MAX_ITERATIONS_WITHOUT_PROGRESS,
    )
    check.add_argument("--json", action="store_true", help="emit the full report as JSON")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command != "check":
        return EXIT_BAD_INPUT

    try:
        events = load_events(args.log)
    except (OSError, ValueError) as exc:
        print(f"redflag-loop: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    report = replay(
        events,
        max_identical=args.max_identical,
        max_iterations=args.max_iterations,
        max_iterations_without_progress=args.max_iterations_without_progress,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_summary(report))

    return EXIT_CLEAN if report["clean"] else EXIT_REDFLAG


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
