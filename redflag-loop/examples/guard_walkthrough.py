"""Run me: python examples/guard_walkthrough.py

Shows the guard catching a stuck agent mid-run, then a clean run that earns
its "done".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redflag_loop import LoopGuard  # noqa: E402

TEST = {"tool": "bash", "command": "pytest -q"}


def stuck_run() -> None:
    print("== stuck agent ==")
    guard = LoopGuard()
    for step in range(1, 6):
        decision = guard.record(TEST)
        print(f"step {step}: allowed={decision['allowed']} streak={decision['repeat_streak']}")
        if not decision["allowed"]:
            print(f"  stopped: {decision['reason']}")
            break

    verdict = guard.claim_done("T1", [{"command": "pytest -q", "exit_code": 1}])
    print(f"completion accepted={verdict['accepted']} ({verdict['redflag']['code']})")


def honest_run() -> None:
    print("\n== honest agent ==")
    guard = LoopGuard()
    guard.record({"tool": "grep", "pattern": "def parse"}, mutation=False)
    guard.record({"tool": "edit", "path": "parser.py"}, ["parser.py"])
    guard.record(TEST)
    guard.record({"tool": "edit", "path": "tests/test_parser.py"}, ["tests/test_parser.py"])
    guard.record(TEST)

    verdict = guard.claim_done(
        "T1", [{"command": "pytest -q", "exit_code": 0, "output_tail": "18 passed"}]
    )
    print(f"completion accepted={verdict['accepted']} ({verdict['reason']})")
    print(f"guard clean={guard.status()['clean']}")


if __name__ == "__main__":
    stuck_run()
    honest_run()
