"""``build-healer`` CLI: plan a fix from one log, or replay many build rounds.

Exit codes
----------
``0`` green build / healing loop finished green
``1`` blocking errors / loop escalated or still red
``2`` bad input (missing file, empty directory, invalid JSON output request)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .core import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MAX_STALLED_ROUNDS,
    HealLoop,
    build_plan,
)
from .parsers import parse_log

EXIT_GREEN = 0
EXIT_RED = 1
EXIT_BAD_INPUT = 2


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def render_plan(plan: Dict[str, Any]) -> str:
    summary = plan["summary"]
    lines = [
        f"blocking: {summary['blocking']}  advisory: {summary['advisory']}  "
        f"files: {len(summary['by_file'])}"
    ]
    if plan["targets"]:
        lines.append("targets:")
    for index, target in enumerate(plan["targets"], start=1):
        code = f" [{target['code']}]" if target.get("code") else ""
        location = target["file"] or "<unknown>"
        if target.get("line"):
            location += f":{target['line']}"
            if target.get("column"):
                location += f":{target['column']}"
        lines.append(f"  {index}. {location}{code}: {target['message']}")
        lines.append(f"     fingerprint={target['fingerprint']} tool={target['tool']}")
    for warning in plan["advisory"]:
        lines.append(f"  warning: {warning['file'] or '<unknown>'}: {warning['message']}")
    lines.append(f"advice: {plan['advice']}")
    return "\n".join(lines)


def render_round(result: Dict[str, Any]) -> str:
    status = "GREEN" if result["green"] else "RED"
    lines = [
        f"round {result['round']}: {status}  "
        f"errors={result['summary']['blocking']} fixed={len(result['fixed'])} "
        f"repeated={len(result['repeated'])}"
    ]
    for event in result["escalations"]:
        lines.append(f"  escalate [{event['code']}]: {event['detail']}")
    lines.append(f"  next: {result['advice']}")
    return "\n".join(lines)


def run_plan(args: argparse.Namespace) -> int:
    try:
        text = _read(args.log)
    except OSError as exc:
        print(f"build-healer: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    plan = build_plan(parse_log(text), max_targets=args.max_targets)
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(render_plan(plan))
    return EXIT_GREEN if plan["green"] else EXIT_RED


def run_rounds(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"build-healer: {directory} is not a directory", file=sys.stderr)
        return EXIT_BAD_INPUT

    logs: List[Path] = sorted(
        (path for path in directory.iterdir() if path.suffix in {".log", ".txt"}),
        key=lambda path: path.name,
    )
    if not logs:
        print(f"build-healer: no .log files in {directory}", file=sys.stderr)
        return EXIT_BAD_INPUT

    loop = HealLoop(
        max_attempts_per_failure=args.max_attempts,
        max_rounds=args.max_rounds,
        max_stalled_rounds=args.max_stalled_rounds,
    )
    results: List[Dict[str, Any]] = []
    for path in logs:
        try:
            result = loop.observe(log_text=_read(str(path)))
        except OSError as exc:
            print(f"build-healer: {exc}", file=sys.stderr)
            return EXIT_BAD_INPUT
        result["log"] = path.name
        results.append(result)
        if not args.json:
            print(f"[{path.name}]")
            print(render_round(result))

    if args.json:
        print(json.dumps({"rounds": results, "status": loop.status()}, indent=2))

    last = results[-1]
    return EXIT_GREEN if last["green"] else EXIT_RED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-healer",
        description="Turn failing build output into a bounded, deduplicated fix plan.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="plan a fix from one build log")
    plan.add_argument("log", help="path to a build/test log")
    plan.add_argument("--json", action="store_true", help="emit JSON")
    plan.add_argument("--max-targets", type=int, default=None)
    plan.set_defaults(handler=run_plan)

    rounds = subparsers.add_parser("rounds", help="replay successive build logs")
    rounds.add_argument("directory", help="directory of .log files, sorted by name")
    rounds.add_argument("--json", action="store_true", help="emit JSON")
    rounds.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    rounds.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    rounds.add_argument("--max-stalled-rounds", type=int, default=DEFAULT_MAX_STALLED_ROUNDS)
    rounds.set_defaults(handler=run_rounds)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:  # pragma: no cover - argparse enforces a subcommand
        return EXIT_BAD_INPUT
    try:
        return handler(args)
    except ValueError as exc:
        print(f"build-healer: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
