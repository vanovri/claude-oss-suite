"""Bounded, deduplicated fix loop for failing builds.

The healer answers one question per round: *what should the agent try next, and
when must it stop?* It never invents a fix. It narrows the failure list,
removes duplicates, counts attempts per fingerprint, and escalates instead of
letting the agent patch the same error for the tenth time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .parsers import (
    Failure,
    dedupe,
    group_by_file,
    parse_log,
    split_severity,
    summarize,
)

HEAL_CODES = (
    "REPEATED_FAILURE",
    "REGRESSION",
    "NO_PROGRESS",
    "ROUNDS_EXHAUSTED",
    "INVALID_INPUT",
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_ROUNDS = 8
DEFAULT_MAX_STALLED_ROUNDS = 2

ESCALATION_ADVICE = (
    "Stop patching. Quote the full error with its file:line, state what you tried "
    "in each attempt, and ask for a decision: revert, change approach, or narrow scope."
)


def _sentence(text: str) -> str:
    """End a fragment with exactly one period."""
    text = text.strip()
    return text if text.endswith((".", "!", "?", ":")) else text + "."


@dataclass
class Target:
    """One unique failure the agent may work on."""

    failure: Failure
    attempts: int = 0
    first_round: int = 1
    last_round: int = 1
    status: str = "open"

    def as_dict(self) -> Dict[str, Any]:
        payload = self.failure.as_dict()
        payload.update(
            attempts=self.attempts,
            first_round=self.first_round,
            last_round=self.last_round,
            status=self.status,
        )
        return payload

    def hint(self) -> str:
        where = self.failure.location()
        code = f" [{self.failure.code}]" if self.failure.code else ""
        return f"[{self.failure.tool}] {where}{code}: {self.failure.message}"


def build_plan(failures: Iterable[Failure], max_targets: Optional[int] = None) -> Dict[str, Any]:
    """Turn a failure list into an ordered, deduplicated fix plan."""
    if max_targets is not None and max_targets < 1:
        raise ValueError("max_targets must be >= 1")

    unique = dedupe(failures)
    blocking, advisory = split_severity(unique)
    targets = [Target(failure=failure) for failure in blocking]
    if max_targets is not None:
        targets = targets[:max_targets]

    grouped = group_by_file(blocking)
    ordered_files = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))

    return {
        "green": not blocking,
        "summary": summarize(unique),
        "targets": [target.as_dict() for target in targets],
        "total_targets": len(blocking),
        "advisory": [failure.as_dict() for failure in advisory],
        "files": {
            path: [failure.fingerprint for failure in items] for path, items in ordered_files
        },
        "advice": _plan_advice(targets, ordered_files, len(blocking)),
    }


def _plan_advice(targets: Sequence[Target], ordered_files: Sequence[tuple], total: int) -> str:
    if not targets:
        return "Build is green: no blocking errors. Do not refactor; commit the working state."

    first = targets[0]
    hotspots = [path for path, items in ordered_files if len(items) > 1]

    parts = [
        f"Start with {_sentence(first.hint())}",
        f"{total} blocking error(s) in {len(ordered_files)} file(s); fix one target per "
        "iteration, then re-run the build.",
    ]
    if hotspots:
        parts.append(
            "Files with more than one error (fix these first, they usually share a root "
            "cause): " + ", ".join(hotspots[:3]) + "."
        )
    parts.append("Do not edit files that are not listed in the plan.")
    return " ".join(parts)


class HealLoop:
    """Stateful multi-round healer: observe a build log, decide whether to go on."""

    def __init__(
        self,
        max_attempts_per_failure: int = DEFAULT_MAX_ATTEMPTS,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        max_stalled_rounds: int = DEFAULT_MAX_STALLED_ROUNDS,
    ) -> None:
        if max_attempts_per_failure < 2:
            raise ValueError("max_attempts_per_failure must be >= 2")
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        if max_stalled_rounds < 1:
            raise ValueError("max_stalled_rounds must be >= 1")

        self.max_attempts_per_failure = max_attempts_per_failure
        self.max_rounds = max_rounds
        self.max_stalled_rounds = max_stalled_rounds

        self.round = 0
        self.green = False
        self.targets: Dict[str, Target] = {}
        self.escalations: List[Dict[str, Any]] = []
        self.rounds: List[Dict[str, Any]] = []

        self._previous: set = set()
        self._ever_open: set = set()
        self._escalated: set = set()
        self._stalled = 0
        self._no_progress_raised = False
        self._budget_raised = False

    # ------------------------------------------------------------- internals

    def _escalate(self, code: str, fingerprint: Optional[str], detail: str) -> Dict[str, Any]:
        key = (code, fingerprint)
        if key in self._escalated:
            return {}
        self._escalated.add(key)
        event = {
            "code": code,
            "fingerprint": fingerprint,
            "round": self.round,
            "detail": detail,
            "advice": ESCALATION_ADVICE,
        }
        self.escalations.append(event)
        return event

    def _advice(self, current: Dict[str, Failure], escalations: Sequence[Dict[str, Any]]) -> str:
        if not current:
            return "Build is green. Stop editing, commit, and report the passing command."
        if escalations:
            return " ".join(
                [_sentence(f"{event['code']}: {event['detail']}") for event in escalations]
                + [ESCALATION_ADVICE]
            )
        first = next(iter(current.values()))
        remaining = len(current) - 1
        tail = (
            f" Then re-run the build; {remaining} error(s) remain."
            if remaining
            else " Then re-run the build."
        )
        return (
            f"Fix {first.location()}: {_sentence(first.message)} "
            f"Change one thing, keep the diff minimal.{tail}"
        )

    # --------------------------------------------------------------- observe

    def observe(
        self,
        log_text: Optional[str] = None,
        failures: Optional[Iterable[Failure]] = None,
    ) -> Dict[str, Any]:
        """Record one build round and return the decision for the next iteration."""
        if log_text is None and failures is None:
            raise ValueError("observe() needs log_text or failures")

        self.round += 1
        items = list(failures) if failures is not None else parse_log(log_text or "")
        blocking, advisory = split_severity(dedupe(items))

        current: Dict[str, Failure] = {}
        for failure in blocking:
            current.setdefault(failure.fingerprint, failure)
        current_set = set(current)

        fixed = self._previous - current_set
        repeated = current_set & self._previous
        regressed = current_set & (self._ever_open - self._previous)

        for fingerprint, failure in current.items():
            target = self.targets.get(fingerprint)
            if target is None:
                target = Target(failure=failure, first_round=self.round)
                self.targets[fingerprint] = target
            target.attempts += 1
            target.last_round = self.round
            target.status = "open"

        for fingerprint in fixed:
            target = self.targets.get(fingerprint)
            if target is not None:
                target.status = "fixed"

        new_escalations: List[Dict[str, Any]] = []

        if current_set and current_set == self._previous:
            self._stalled += 1
        else:
            self._stalled = 0
            self._no_progress_raised = False

        for fingerprint, failure in current.items():
            target = self.targets[fingerprint]
            if target.attempts >= self.max_attempts_per_failure:
                target.status = "escalated"
                event = self._escalate(
                    "REPEATED_FAILURE",
                    fingerprint,
                    f"{failure.location()} failed {target.attempts} rounds in a row "
                    f"({failure.message.rstrip('.')})",
                )
                if event:
                    new_escalations.append(event)

        for fingerprint in sorted(regressed):
            failure = current[fingerprint]
            event = self._escalate(
                "REGRESSION",
                fingerprint,
                f"{failure.location()} was fixed in an earlier round and is failing "
                f"again ({failure.message.rstrip('.')})",
            )
            if event:
                new_escalations.append(event)

        if current_set and self._stalled >= self.max_stalled_rounds and not self._no_progress_raised:
            self._no_progress_raised = True
            event = self._escalate(
                "NO_PROGRESS",
                None,
                f"round {self.round}: the failure set is unchanged for "
                f"{self._stalled} rounds ({len(current_set)} error(s))",
            )
            if event:
                new_escalations.append(event)

        if current_set and self.round > self.max_rounds and not self._budget_raised:
            self._budget_raised = True
            event = self._escalate(
                "ROUNDS_EXHAUSTED",
                None,
                f"round {self.round} > budget {self.max_rounds} with "
                f"{len(current_set)} error(s) still open",
            )
            if event:
                new_escalations.append(event)

        self._ever_open |= current_set
        self._previous = current_set
        self.green = not current_set

        result = {
            "round": self.round,
            "green": self.green,
            "should_continue": bool(current_set) and not self.escalations,
            "targets": [self.targets[fingerprint].as_dict() for fingerprint in current],
            "fixed": sorted(fixed),
            "regressed": sorted(regressed),
            "repeated": sorted(repeated),
            "escalations": new_escalations,
            "advisory_count": len(advisory),
            "summary": summarize(items),
            "advice": self._advice(current, new_escalations),
        }
        self.rounds.append(result)
        return result


    def status(self) -> Dict[str, Any]:
        return {
            "round": self.round,
            "green": self.green,
            "should_continue": bool(self._previous) and not self.escalations,
            "max_rounds": self.max_rounds,
            "open": sorted(self._previous),
            "targets": [target.as_dict() for target in self.targets.values()],
            "escalations": list(self.escalations),
            "rounds": [entry["round"] for entry in self.rounds],
            "ever_open": len(self._ever_open),
        }


