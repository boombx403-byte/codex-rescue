from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .alpha5 import Alpha5RolloutDiagnostics, ProjectionReport, inspect_projection_parity, scan_rollout_alpha5
from .gitstate import GitStateError, inspect_git_state
from .transcript import ParseResult, parse_transcript


SEVERITY = [
    "UNKNOWN_CORRUPTION",
    "CORRUPTED_TOOL_CALL",
    "MALFORMED_RECORD",
    "TRUNCATED_TRANSCRIPT",
    "OVERSIZED_PAYLOAD",
    "INTERLEAVED_WRITERS",
    "INVALID_PERSISTED_ITEM_ID",
    "UNKNOWN_OPERATIONAL_SCHEMA",
    "PROJECTION_STATE_UNKNOWN",
    "WEDGED_PROJECTION",
    "PERSISTED_PAGINATED_ORDINAL_REUSE",
    "ORDINAL_ANALYSIS_INCOMPLETE",
    "ACTIVE_WRITE_UNCERTAIN",
    "INCOMPLETE_ROLLOUT",
    "UNFINISHED_TOOL_CALL",
    "COMPACTION_STATE_LOSS",
    "REPO_STATE_DIVERGED",
    "HEALTHY",
]


@dataclass
class DoctorResult:
    session: str
    status: str
    findings: list[str]
    transcript: ParseResult
    repository: dict[str, Any]
    alpha5: Alpha5RolloutDiagnostics
    projection: ProjectionReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "status": self.status,
            "findings": self.findings,
            "transcript": self.transcript.to_dict(),
            "repository": self.repository,
            "alpha5": self.alpha5.to_dict(),
            "projection": self.projection.to_dict(),
        }


def doctor_session(path: str | Path, oversized_threshold: int = 1_000_000) -> DoctorResult:
    parsed = parse_transcript(path, oversized_threshold=oversized_threshold)
    alpha5 = scan_rollout_alpha5(path)
    projection = inspect_projection_parity(path, parsed)
    findings: set[str] = set()
    if parsed.corruption_class:
        findings.add(parsed.corruption_class)
    if parsed.oversized_records:
        findings.add("OVERSIZED_PAYLOAD")
    if parsed.operational_schema_issues or parsed.correlation_ambiguities:
        findings.add("UNKNOWN_OPERATIONAL_SCHEMA")
    if parsed.ordinal_mode not in {None, "legacy", "paginated"}:
        findings.add("UNKNOWN_OPERATIONAL_SCHEMA")
    if parsed.ordinal_reuse:
        findings.add("PERSISTED_PAGINATED_ORDINAL_REUSE")
    if parsed.ordinal_tracking_overflow:
        findings.add("ORDINAL_ANALYSIS_INCOMPLETE")
    if parsed.unfinished_tool_calls:
        findings.add("UNFINISHED_TOOL_CALL")
    if parsed.compaction_state_loss:
        findings.add("COMPACTION_STATE_LOSS")

    if alpha5.typed_id_violation_count:
        findings.add("INVALID_PERSISTED_ITEM_ID")
    if alpha5.interleaved_writer_evidence:
        findings.add("INTERLEAVED_WRITERS")
    if alpha5.source_changed_during_scan:
        findings.add("ACTIVE_WRITE_UNCERTAIN")
    if alpha5.empty_rollout or alpha5.header_only_rollout:
        findings.add("INCOMPLETE_ROLLOUT")
    if alpha5.malformed_opaque_field_count:
        findings.add("UNKNOWN_OPERATIONAL_SCHEMA")

    if projection.status == "wedged":
        findings.add("WEDGED_PROJECTION")
    elif projection.status == "active_write":
        findings.add("ACTIVE_WRITE_UNCERTAIN")
    elif projection.status == "unknown" and parsed.ordinal_mode == "paginated":
        findings.add("PROJECTION_STATE_UNKNOWN")

    cwd = parsed.session_metadata.get("cwd")
    repository: dict[str, Any]
    if cwd:
        try:
            repository = inspect_git_state(cwd).to_dict()
            repository["classification"] = "git_available"
        except GitStateError as exc:
            # An unavailable/non-Git/inaccessible repository is not evidence of
            # divergence.  Keep the repository evidence explicitly unknown.
            repository = {
                "cwd": cwd,
                "error": str(exc),
                "confidence": "unknown",
                "classification": "git_unavailable_or_non_git",
            }
    else:
        repository = {"cwd": None, "confidence": "unknown", "classification": "no_workspace"}

    if not findings:
        findings.add("HEALTHY")
    status = next(label for label in SEVERITY if label in findings)
    return DoctorResult(
        str(Path(path).resolve()),
        status,
        sorted(findings, key=SEVERITY.index),
        parsed,
        repository,
        alpha5,
        projection,
    )
