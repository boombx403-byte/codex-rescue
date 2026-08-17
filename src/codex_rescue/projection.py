from __future__ import annotations

from pathlib import Path

from .alpha5 import ProjectionReport, inspect_projection_parity as _inspect_projection_parity
from .transcript import ParseResult


def inspect_projection_parity(path: str | Path, parsed: ParseResult) -> ProjectionReport:
    """Apply field-supported Alpha5 projection classifications.

    The base inspector establishes stable byte-boundary evidence read-only.
    Codex 0.146.1 field evidence also shows a durable off-by-one wedge where
    the DB says it expects ordinal N while the canonical record exactly at the
    stored byte cursor is N+1.  That narrow stable shape is strong wedge
    evidence rather than a generic unknown mismatch.
    """

    report = _inspect_projection_parity(path, parsed)
    if (
        report.status == "unknown"
        and report.next_rollout_ordinal is not None
        and report.boundary_ordinal == report.next_rollout_ordinal + 1
        and report.reason == "canonical suffix skips ahead of the persisted next ordinal"
    ):
        report.status = "wedged"
        report.reason = (
            "stable projection cursor is off by one: canonical record at the persisted "
            "byte boundary is next_rollout_ordinal + 1"
        )
        report.confidence = "strong"
    return report


__all__ = ["inspect_projection_parity"]
