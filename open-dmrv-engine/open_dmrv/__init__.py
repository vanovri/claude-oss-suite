"""open-dmrv-engine — deterministic MRV gates for pyrolysis carbon removal.

Public surface::

    from open_dmrv import Batch, batch_from_dict, verify_batch, verify_batches, load_batches

    result = verify_batches(load_batches("examples/batches_pass.json"))
    if not result["signable"]:
        raise SystemExit(result["violations"])

Only stdlib. No clocks, no network, no randomness inside the checks.
"""

from .core import (
    CODES,
    EMPTY_ROOT,
    HARD_CODES,
    H_C_DURABLE,
    H_C_LIMIT,
    MASS_BALANCE_TOLERANCE,
    MAX_MOISTURE_PCT,
    PROCESS_SPECS,
    Batch,
    batch_from_dict,
    canonical_bytes,
    load_batches,
    merkle_root,
    render_summary,
    verify_batch,
    verify_batches,
)

__all__ = [
    "Batch",
    "CODES",
    "EMPTY_ROOT",
    "HARD_CODES",
    "H_C_DURABLE",
    "H_C_LIMIT",
    "MASS_BALANCE_TOLERANCE",
    "MAX_MOISTURE_PCT",
    "PROCESS_SPECS",
    "batch_from_dict",
    "canonical_bytes",
    "load_batches",
    "merkle_root",
    "render_summary",
    "verify_batch",
    "verify_batches",
]

__version__ = "0.1.0"
