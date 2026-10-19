"""Evidence-gated loop guard for autonomous coding agents.

A prompt that says "do not loop" is a wish. This module is a mechanism: every
agent action is recorded, hashed and checked against three hard rules, and a
completion claim is rejected unless it carries command evidence with exit 0.

Redflag codes
-------------
``LOOP_DETECTED``          the same action signature repeated N times in a row
``NO_PROGRESS``            N iterations produced no new artifact
``BUDGET_EXCEEDED``        the iteration budget is exhausted
``UNSUPPORTED_COMPLETION`` "done" claimed without passing evidence
``REDFLAGS_UNRESOLVED``    completion attempted while redflags are still open
``INVALID_EVENT``          the event log contained something unusable
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

REDFLAG_CODES = (
    "LOOP_DETECTED",
    "NO_PROGRESS",
    "BUDGET_EXCEEDED",
    "UNSUPPORTED_COMPLETION",
    "REDFLAGS_UNRESOLVED",
    "INVALID_EVENT",
)

DEFAULT_MAX_IDENTICAL = 3
DEFAULT_MAX_ITERATIONS = 30
DEFAULT_MAX_ITERATIONS_WITHOUT_PROGRESS = 5


def normalize_action(action: Dict[str, Any]) -> str:
    """Canonical JSON so key order and whitespace never change a signature."""
    return json.dumps(action or {}, sort_keys=True, separators=(",", ":"), default=str)


def action_signature(action: Dict[str, Any]) -> str:
    """Stable 16-hex-char fingerprint of one agent action."""
    return hashlib.sha256(normalize_action(action).encode("utf-8")).hexdigest()[:16]


def verify_evidence(evidence: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Every evidence item must be a command that exited 0."""
    failures: List[str] = []
    if not evidence:
        failures.append("NO_EVIDENCE")

    for index, item in enumerate(evidence or []):
        if not isinstance(item, dict):
            failures.append(f"EVIDENCE_{index}_NOT_OBJECT")
            continue
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            failures.append(f"EVIDENCE_{index}_NO_COMMAND")
        exit_code = item.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            failures.append(f"EVIDENCE_{index}_NO_EXIT_CODE")
        elif exit_code != 0:
            failures.append(f"EVIDENCE_{index}_EXIT_{exit_code}")

    return {"valid": not failures, "failures": failures, "count": len(evidence or [])}


@dataclass
class RedFlag:
    code: str
    iteration: int
    detail: str

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "iteration": self.iteration, "detail": self.detail}


class LoopGuard:
    """Stateful guard: record actions, then gate the completion claim."""

    def __init__(
        self,
        max_identical: int = DEFAULT_MAX_IDENTICAL,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_iterations_without_progress: int = DEFAULT_MAX_ITERATIONS_WITHOUT_PROGRESS,
    ) -> None:
        if max_identical < 2:
            raise ValueError("max_identical must be >= 2")
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if max_iterations_without_progress < 1:
            raise ValueError("max_iterations_without_progress must be >= 1")

        self.max_identical = max_identical
        self.max_iterations = max_iterations
        self.max_iterations_without_progress = max_iterations_without_progress

        self.iteration = 0
        self.redflags: List[RedFlag] = []
        self.history: List[Dict[str, Any]] = []

        self._last_signature: Optional[str] = None
        self._repeat_streak = 0
        self._known_artifacts: set = set()
        self._iterations_without_progress = 0
        self._completed_tasks: set = set()

    # ------------------------------------------------------------------ flags

    def flag(self, code: str, detail: str) -> Dict[str, Any]:
        """Record one redflag and return it as a plain dict."""
        if code not in REDFLAG_CODES:
            raise ValueError(f"unknown redflag code: {code}")
        redflag = RedFlag(code=code, iteration=self.iteration, detail=detail)
        self.redflags.append(redflag)
        return redflag.as_dict()

    def open_codes(self) -> List[str]:
        """Unique redflag codes in first-seen order."""
        seen: List[str] = []
        for redflag in self.redflags:
            if redflag.code not in seen:
                seen.append(redflag.code)
        return seen

    # ----------------------------------------------------------------- record

    def record(
        self,
        action: Dict[str, Any],
        artifacts: Sequence[str] = (),
        mutation: bool = True,
    ) -> Dict[str, Any]:
        """Record one agent action and decide whether it may proceed.

        ``mutation=False`` marks read-only exploration: it never counts as
        progress debt, so grepping for context cannot trip ``NO_PROGRESS``.
        """
        self.iteration += 1
        signature = action_signature(action)

        if signature == self._last_signature:
            self._repeat_streak += 1
        else:
            self._repeat_streak = 1
            self._last_signature = signature

        artifact_list = [str(item) for item in (artifacts or [])]
        new_artifacts = [item for item in artifact_list if item not in self._known_artifacts]
        self._known_artifacts.update(new_artifacts)
        if mutation:
            self._iterations_without_progress = (
                0 if new_artifacts else self._iterations_without_progress + 1
            )

        result: Dict[str, Any] = {
            "iteration": self.iteration,
            "signature": signature,
            "repeat_streak": self._repeat_streak,
            "new_artifacts": new_artifacts,
            "allowed": True,
            "redflag": None,
            "reason": None,
        }

        if self._repeat_streak >= self.max_identical:
            redflag = self.flag(
                "LOOP_DETECTED",
                f"action {signature} repeated {self._repeat_streak}x in a row",
            )
            result.update(
                allowed=False,
                redflag=redflag,
                reason=(
                    "Identical action repeated. Stop, re-read the failure output, "
                    "and change one variable before retrying."
                ),
            )
        elif self.iteration > self.max_iterations:
            redflag = self.flag(
                "BUDGET_EXCEEDED",
                f"iteration {self.iteration} > budget {self.max_iterations}",
            )
            result.update(
                allowed=False,
                redflag=redflag,
                reason="Iteration budget exhausted. Report BLOCKED with the last error.",
            )
        elif self._iterations_without_progress >= self.max_iterations_without_progress:
            redflag = self.flag(
                "NO_PROGRESS",
                f"{self._iterations_without_progress} iterations without a new artifact",
            )
            result.update(
                allowed=False,
                redflag=redflag,
                reason="No artifact changed. Pick a different hypothesis or escalate.",
            )

        self.history.append(result)
        return result

    # ------------------------------------------------------------------ done

    def claim_done(
        self,
        task_id: str,
        evidence: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Accept completion only if the guard is clean and evidence passes."""
        prior_codes = self.open_codes()
        verification = verify_evidence(evidence)
        result: Dict[str, Any] = {
            "task": task_id,
            "iteration": self.iteration,
            "accepted": False,
            "redflag": None,
            "reason": None,
            "evidence_failures": verification["failures"],
        }

        if not isinstance(task_id, str) or not task_id.strip():
            result["redflag"] = self.flag("INVALID_EVENT", "completion event has no task id")
            result["reason"] = "Every completion claim needs a task id."
            return result

        if prior_codes:
            redflag = self.flag(
                "REDFLAGS_UNRESOLVED",
                "completion attempted with open redflags: " + ", ".join(prior_codes),
            )
            result.update(
                redflag=redflag,
                reason="Resolve open redflags before claiming done: " + ", ".join(prior_codes),
            )
            return result

        if not verification["valid"]:
            redflag = self.flag(
                "UNSUPPORTED_COMPLETION",
                "evidence failed: " + ", ".join(verification["failures"]),
            )
            result.update(
                redflag=redflag,
                reason=(
                    "Completion needs at least one command with exit_code 0. "
                    "Failures: " + ", ".join(verification["failures"])
                ),
            )
            return result

        self._completed_tasks.add(task_id)
        result["accepted"] = True
        result["reason"] = f"{verification['count']} passing evidence item(s) accepted"
        return result

    # ---------------------------------------------------------------- status

    def status(self) -> Dict[str, Any]:
        return {
            "iterations": self.iteration,
            "artifacts": sorted(self._known_artifacts),
            "completed_tasks": sorted(self._completed_tasks),
            "open_codes": self.open_codes(),
            "redflags": [redflag.as_dict() for redflag in self.redflags],
            "clean": not self.redflags,
        }


def replay(
    events: Sequence[Any],
    max_identical: int = DEFAULT_MAX_IDENTICAL,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_iterations_without_progress: int = DEFAULT_MAX_ITERATIONS_WITHOUT_PROGRESS,
) -> Dict[str, Any]:
    """Replay an ``action`` / ``complete`` event list through a fresh guard."""
    guard = LoopGuard(
        max_identical=max_identical,
        max_iterations=max_iterations,
        max_iterations_without_progress=max_iterations_without_progress,
    )
    results: List[Dict[str, Any]] = []

    for index, event in enumerate(events or []):
        if not isinstance(event, dict):
            results.append(
                {
                    "event": index,
                    "redflag": guard.flag("INVALID_EVENT", f"event {index} is not an object"),
                    "reason": "event is not a JSON object",
                }
            )
            continue

        kind = event.get("type")
        if kind == "action":
            results.append(
                guard.record(
                    event.get("action") or {},
                    event.get("artifacts") or [],
                    event.get("mutation", True),
                )
            )
        elif kind == "complete":
            results.append(
                guard.claim_done(str(event.get("task") or ""), event.get("evidence") or [])
            )
        else:
            results.append(
                {
                    "event": index,
                    "redflag": guard.flag(
                        "INVALID_EVENT", f"event {index} has unknown type {kind!r}"
                    ),
                    "reason": f"unknown event type: {kind!r}",
                }
            )

    return {
        "events": len(events or []),
        "iterations": guard.iteration,
        "clean": not guard.redflags,
        "open_codes": guard.open_codes(),
        "redflags": [redflag.as_dict() for redflag in guard.redflags],
        "results": results,
    }
