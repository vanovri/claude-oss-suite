"""agent_referee — immutable testbench gate for autonomous coding agents.

Pure logic for locking a test suite cryptographically and detecting reward
hacking (deleted test files, rewritten assertions, regressed runtime).
"""

from agent_referee.core import (
    LOCKFILE_NAME,
    build_lock_manifest,
    count_ast_assertions,
    read_lock,
    scan_test_directory,
    sha256_bytes,
    sha256_text,
    verify_manifest,
    write_lock,
)

__version__ = "0.1.0"
__all__ = [
    "LOCKFILE_NAME",
    "__version__",
    "build_lock_manifest",
    "count_ast_assertions",
    "read_lock",
    "scan_test_directory",
    "sha256_bytes",
    "sha256_text",
    "verify_manifest",
    "write_lock",
]
