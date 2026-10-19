"""Command line entry point: ``open-dmrv verify`` and ``open-dmrv merkle``.

Exit codes are part of the contract:

* ``0`` — every hard check passed and the bundle is signable
* ``1`` — at least one violation, or the bundle is not signable
* ``2`` — unreadable file, malformed batch, or invalid argument
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional, Sequence

from .core import (
    PROCESS_SPECS,
    load_batches,
    merkle_root,
    canonical_bytes,
    render_summary,
    verify_batches,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-dmrv",
        description="Verify pyrolysis telemetry before a removal bundle is signed.",
    )
    parser.add_argument("--version", action="version", version="open-dmrv 0.1.0")

    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify", help="run every gate over a batch file")
    verify.add_argument("path", help="JSON array, {'batches': [...]} object, or .jsonl")
    verify.add_argument("--json", action="store_true", help="emit the full report as JSON")
    verify.add_argument(
        "--allow-review",
        action="store_true",
        help="exit 0 when only soft checks fail (yield / moisture) and hard gates pass",
    )

    merkle = subparsers.add_parser("merkle", help="print the bundle Merkle root only")
    merkle.add_argument("path", help="JSON array, {'batches': [...]} object, or .jsonl")
    merkle.add_argument("--json", action="store_true", help="emit {'merkle_root', 'leaf_count'}")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        batches = load_batches(args.path)
    except ValueError as exc:
        print(f"open-dmrv: {exc}", file=sys.stderr)
        return 2

    if args.command == "merkle":
        root = merkle_root([canonical_bytes(batch.as_dict()) for batch in batches])
        if args.json:
            print(json.dumps({"merkle_root": root, "leaf_count": len(batches)}, indent=2))
        else:
            print(root)
        return 0

    result = verify_batches(batches)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_summary(result))

    if result["signable"]:
        return 0
    if args.allow_review and not result["hard_violations"]:
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
