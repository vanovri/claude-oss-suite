"""redflag_loop — stop agents from looping, and from lying about "done"."""

from redflag_loop.core import (
    DEFAULT_MAX_IDENTICAL,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_ITERATIONS_WITHOUT_PROGRESS,
    REDFLAG_CODES,
    LoopGuard,
    RedFlag,
    action_signature,
    normalize_action,
    replay,
    verify_evidence,
)

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "DEFAULT_MAX_IDENTICAL",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MAX_ITERATIONS_WITHOUT_PROGRESS",
    "REDFLAG_CODES",
    "LoopGuard",
    "RedFlag",
    "action_signature",
    "normalize_action",
    "replay",
    "verify_evidence",
]
