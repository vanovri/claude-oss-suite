"""Turn raw compiler / test output into structured, deduplicatable failures.

Supported grammars
------------------
``python``   tracebacks (``File "x.py", line 12`` + ``ValueError: msg``)
``pytest``   ``FAILED tests/test_x.py::test_y - AssertionError: ...``
``gcc``      ``src/main.c:12:5: error: use of undeclared identifier 'x'``
``tsc``      ``src/app.ts(12,5): error TS2322: Type 'string' is not assignable``
``rustc``    ``error[E0308]: mismatched types`` + ``--> src/main.rs:10:5``
``eslint``   ``  12:5  error  'x' is not defined  no-undef``
``go``       ``./main.go:10:5: undefined: x``
``generic``  any line containing ``error`` / ``failed`` / ``fatal``

The parsers are deliberately independent: ``parse_log`` runs all of them and
merges the results, so a mixed log (a compiler error followed by a pytest
summary) still yields one flat list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

DEFAULT_SEVERITY = "error"

_PY_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>.+))?\s*$')
_PY_ERROR = re.compile(r"^(?P<code>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))(?::\s*(?P<msg>.*))?$")

_PYTEST_FAILED = re.compile(r"^FAILED\s+(?P<file>[\w./\\:-]+?)(?:::(?P<test>[\w\[\]\-.:]+))?(?:\s+-\s+(?P<msg>.+))?$")
_PYTEST_LOCATION = re.compile(r"^(?P<file>[\w./\\-]+\.py):(?P<line>\d+): (?P<code>[A-Za-z_][\w.]*)(?::\s*(?P<msg>.*))?$")

_GCC = re.compile(
    r"^(?P<file>[^:\n]+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
    r"(?P<severity>fatal error|error|warning|note):\s*(?P<msg>.+)$"
)

_TSC = re.compile(
    r"^(?P<file>[^(]+?)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<severity>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.+)$"
)

_RUST_HEAD = re.compile(r"^(?P<severity>error|warning)(?:\[(?P<code>E\d+)\])?:\s*(?P<msg>.+)$")
_RUST_SPAN = re.compile(r"^\s*-->\s*(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+)\s*$")

_ESLINT_FILE = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^\s].*\.[cm]?[jt]sx?)$")
_ESLINT_ROW = re.compile(
    r"^\s*(?P<line>\d+):(?P<col>\d+)\s+(?P<severity>error|warning)\s+"
    r"(?P<msg>.+?)\s{2,}(?P<code>[\w@/-]+)\s*$"
)

_GO = re.compile(
    r"^(?:\./)?(?P<file>[\w./\\-]+\.go):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<msg>.+)$"
)

_GENERIC = re.compile(r"(?i)\b(?P<severity>fatal|error|failed|failure)\b[:\s]\s*(?P<msg>.+)")
_GENERIC_SUMMARY = re.compile(r"(?i)^(?:found\s+)?\d+\s+errors?\b")

_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
_TEMP_PATH = re.compile(r"(?:[A-Za-z]:\\|/)(?:[^\s:]*[/\\])?(?:tmp|Temp|temp)[/\\][^\s:]+")


@dataclass
class Failure:
    """One parsed build failure, identified by a stable fingerprint."""

    tool: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    code: Optional[str] = None
    severity: str = DEFAULT_SEVERITY
    context: str = ""

    @property
    def fingerprint(self) -> str:
        return fingerprint(self)

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "code": self.code,
            "message": self.message,
            "fingerprint": self.fingerprint,
        }

    def location(self) -> str:
        if not self.file:
            return "<unknown>"
        if self.line is None:
            return self.file
        if self.column is None:
            return f"{self.file}:{self.line}"
        return f"{self.file}:{self.line}:{self.column}"


def normalize_message(message: str) -> str:
    """Strip volatile parts so the same bug fingerprints the same way."""
    text = (message or "").strip()
    text = _ADDRESS.sub("0xADDR", text)
    text = _TEMP_PATH.sub("<tmp>", text)
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def fingerprint(failure: Failure) -> str:
    """Hash of tool + file + code + normalized message. Line numbers excluded."""
    import hashlib

    key = "|".join(
        [
            failure.tool,
            (failure.file or "").replace("\\", "/").lstrip("./"),
            failure.code or "",
            normalize_message(failure.message),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


ERROR_SEVERITIES = ("error", "fatal error")


# --------------------------------------------------------------------- python


def _scan_python(lines: Sequence[str]) -> List[tuple]:
    found: List[tuple] = []
    consumed = set()
    index = 0

    while index < len(lines):
        if not lines[index].strip().startswith("Traceback (most recent call last):"):
            index += 1
            continue

        frames = []
        code: Optional[str] = None
        message = ""
        cursor = index + 1
        while cursor < len(lines):
            raw = lines[cursor]
            if not raw.strip():
                cursor += 1
                continue
            frame = _PY_FRAME.match(raw)
            if frame:
                frames.append(frame)
                consumed.add(cursor)
                cursor += 2  # frame line + source line
                while (
                    cursor < len(lines)
                    and lines[cursor].strip()
                    and not _PY_FRAME.match(lines[cursor])
                    and (lines[cursor].startswith(" ") or lines[cursor].strip().startswith("^"))
                ):
                    consumed.add(cursor)
                    cursor += 1
                continue
            error = _PY_ERROR.match(raw.strip())
            if error and not raw.startswith(" "):
                code = error.group("code")
                message = (error.group("msg") or "").strip()
                consumed.add(cursor)
                cursor += 1
                break
            cursor += 1

        last = frames[-1] if frames else None
        found.append(
            (
                index,
                Failure(
                    tool="python",
                    file=last.group("file") if last else None,
                    line=int(last.group("line")) if last else None,
                    code=code,
                    message=message or "unhandled exception",
                    context="traceback",
                ),
            )
        )
        consumed.add(index)
        index = cursor

    # SyntaxError / ImportError style: "File ...", then the error line, no traceback.
    for cursor, raw in enumerate(lines):
        if cursor in consumed:
            continue
        error = _PY_ERROR.match(raw.strip())
        if not error or raw.startswith(" ") or cursor in consumed:
            continue
        for back in range(1, 7):
            probe = cursor - back
            if probe < 0:
                break
            frame = _PY_FRAME.match(lines[probe])
            if frame:
                found.append(
                    (
                        probe,
                        Failure(
                            tool="python",
                            file=frame.group("file"),
                            line=int(frame.group("line")),
                            code=error.group("code"),
                            message=(error.group("msg") or "").strip() or "syntax error",
                            context="syntax",
                        ),
                    )
                )
                consumed.update({probe, cursor})
                break

    return sorted(found, key=lambda item: item[0])


def parse_python_traceback(text: str) -> List[Failure]:
    return [failure for _, failure in _scan_python(text.splitlines())]


# --------------------------------------------------------------------- pytest


def _scan_pytest(lines: Sequence[str]) -> List[tuple]:
    found: List[tuple] = []
    for index, raw in enumerate(lines):
        match = _PYTEST_FAILED.match(raw.strip())
        if match:
            test = match.group("test") or ""
            message = match.group("msg") or (f"failed: {test}" if test else "failed")
            found.append(
                (
                    index,
                    Failure(
                        tool="pytest",
                        file=match.group("file"),
                        code=test or None,
                        message=message,
                        context="summary",
                    ),
                )
            )

    if found:
        # The short summary already names every failing test; the per-test
        # location lines below would only add duplicates.
        return found

    for index, raw in enumerate(lines):
        location = _PYTEST_LOCATION.match(raw.strip())
        if not location:
            continue
        code = location.group("code")
        if not code.endswith(("Error", "Exception")):
            continue
        found.append(
            (
                index,
                Failure(
                    tool="pytest",
                    file=location.group("file"),
                    line=int(location.group("line")),
                    code=code,
                    message=(location.group("msg") or "").strip() or code,
                    context="location",
                ),
            )
        )
    return found


def parse_pytest(text: str) -> List[Failure]:
    return [failure for _, failure in _scan_pytest(text.splitlines())]


# ------------------------------------------------------------- compiler family


def _scan_gcc(lines: Sequence[str]) -> List[tuple]:
    found: List[tuple] = []
    for index, raw in enumerate(lines):
        match = _GCC.match(raw.strip())
        if not match:
            continue
        found.append(
            (
                index,
                Failure(
                    tool="gcc",
                    file=match.group("file"),
                    line=int(match.group("line")),
                    column=int(match.group("col")) if match.group("col") else None,
                    severity=match.group("severity"),
                    message=match.group("msg").strip(),
                    context="diagnostic",
                ),
            )
        )
    return found


def parse_gcc(text: str) -> List[Failure]:
    return [failure for _, failure in _scan_gcc(text.splitlines())]


def _scan_tsc(lines: Sequence[str]) -> List[tuple]:
    found: List[tuple] = []
    for index, raw in enumerate(lines):
        match = _TSC.match(raw.strip())
        if not match:
            continue
        found.append(
            (
                index,
                Failure(
                    tool="tsc",
                    file=match.group("file"),
                    line=int(match.group("line")),
                    column=int(match.group("col")),
                    code=match.group("code"),
                    severity=match.group("severity"),
                    message=match.group("msg").strip(),
                    context="diagnostic",
                ),
            )
        )
    return found


def parse_tsc(text: str) -> List[Failure]:
    return [failure for _, failure in _scan_tsc(text.splitlines())]


def _scan_rustc(lines: Sequence[str]) -> List[tuple]:
    found: List[tuple] = []
    for index, raw in enumerate(lines):
        head = _RUST_HEAD.match(raw.strip())
        if not head or raw.startswith(" "):
            continue
        file = line = column = None
        for lookahead in range(index + 1, min(index + 4, len(lines))):
            span = _RUST_SPAN.match(lines[lookahead])
            if span:
                file = span.group("file")
                line = int(span.group("line"))
                column = int(span.group("col"))
                break
        found.append(
            (
                index,
                Failure(
                    tool="rustc",
                    file=file,
                    line=line,
                    column=column,
                    code=head.group("code"),
                    severity=head.group("severity"),
                    message=head.group("msg").strip(),
                    context="diagnostic",
                ),
            )
        )
    return found


def parse_rustc(text: str) -> List[Failure]:
    return [failure for _, failure in _scan_rustc(text.splitlines())]


def _scan_eslint(lines: Sequence[str]) -> List[tuple]:
    found: List[tuple] = []
    current_file: Optional[str] = None
    for index, raw in enumerate(lines):
        header = _ESLINT_FILE.match(raw.strip())
        if header and not _ESLINT_ROW.match(raw):
            current_file = header.group("file")
            continue
        row = _ESLINT_ROW.match(raw)
        if not row:
            continue
        found.append(
            (
                index,
                Failure(
                    tool="eslint",
                    file=current_file,
                    line=int(row.group("line")),
                    column=int(row.group("col")),
                    code=row.group("code"),
                    severity=row.group("severity"),
                    message=row.group("msg").strip(),
                    context="lint",
                ),
            )
        )
    return found


def parse_eslint(text: str) -> List[Failure]:
    return [failure for _, failure in _scan_eslint(text.splitlines())]


def _scan_go(lines: Sequence[str]) -> List[tuple]:
    found: List[tuple] = []
    for index, raw in enumerate(lines):
        match = _GO.match(raw.strip())
        if not match:
            continue
        message = match.group("msg").strip()
        if message.startswith(("error:", "warning:")):
            continue  # gcc grammar owns those
        code = message.split(":", 1)[0] if ":" in message else None
        found.append(
            (
                index,
                Failure(
                    tool="go",
                    file=match.group("file"),
                    line=int(match.group("line")),
                    column=int(match.group("col")) if match.group("col") else None,
                    code=code,
                    message=message,
                    context="diagnostic",
                ),
            )
        )
    return found


def parse_go(text: str) -> List[Failure]:
    return [failure for _, failure in _scan_go(text.splitlines())]


# -------------------------------------------------------------------- generic


def _scan_generic(lines: Sequence[str], consumed: set) -> List[tuple]:
    found: List[tuple] = []
    for index, raw in enumerate(lines):
        if index in consumed:
            continue
        if _GENERIC_SUMMARY.match(raw.strip()):
            continue  # "Found 1 error in 1 file" counts errors, it is not one
        match = _GENERIC.search(raw)
        if not match:
            continue
        message = match.group("msg").strip()
        if len(message) < 4 or message.isdigit() or message.startswith(":"):
            continue
        found.append(
            (
                index,
                Failure(
                    tool="generic",
                    severity="fatal error" if match.group("severity").lower() == "fatal" else "error",
                    message=message,
                    context=raw.strip()[:200],
                ),
            )
        )
    return found


SCANNERS = (
    ("python", _scan_python),
    ("pytest", _scan_pytest),
    ("tsc", _scan_tsc),
    ("rustc", _scan_rustc),
    ("eslint", _scan_eslint),
    ("go", _scan_go),
    ("gcc", _scan_gcc),
)


def parse_log(text: str, include_generic: bool = True, unique: bool = True) -> List[Failure]:
    """Parse a mixed build log with every grammar and merge the results."""
    lines = (text or "").splitlines()
    merged: List[tuple] = []
    consumed: set = set()

    for _name, scanner in SCANNERS:
        for index, failure in scanner(lines):
            merged.append((index, failure))
            consumed.add(index)

    if include_generic:
        merged.extend(_scan_generic(lines, consumed))

    merged.sort(key=lambda item: item[0])
    failures = [failure for _, failure in merged]
    return dedupe(failures) if unique else failures


def dedupe(failures: Iterable[Failure]) -> List[Failure]:
    """Keep the first occurrence of each fingerprint, preserving log order."""
    seen: dict = {}
    for failure in failures:
        seen.setdefault(failure.fingerprint, failure)
    return list(seen.values())


def split_severity(failures: Iterable[Failure]) -> tuple:
    """Split into (blocking errors, advisory warnings/notes)."""
    blocking: List[Failure] = []
    advisory: List[Failure] = []
    for failure in failures:
        (blocking if failure.severity in ERROR_SEVERITIES else advisory).append(failure)
    return blocking, advisory


def group_by_file(failures: Iterable[Failure]) -> dict:
    grouped: dict = {}
    for failure in failures:
        grouped.setdefault(failure.file or "<unknown>", []).append(failure)
    return grouped


def summarize(failures: Iterable[Failure]) -> dict:
    items = list(failures)
    blocking, advisory = split_severity(items)
    by_tool: dict = {}
    by_file: dict = {}
    for failure in items:
        by_tool[failure.tool] = by_tool.get(failure.tool, 0) + 1
        key = failure.file or "<unknown>"
        by_file[key] = by_file.get(key, 0) + 1
    return {
        "total": len(items),
        "blocking": len(blocking),
        "advisory": len(advisory),
        "by_tool": dict(sorted(by_tool.items())),
        "by_file": dict(sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0]))),
    }

