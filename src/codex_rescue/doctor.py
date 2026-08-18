from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .alpha5 import Alpha5RolloutDiagnostics, ProjectionReport, scan_rollout_alpha5
from .field_evidence import (
    FieldEvidenceReport,
    WorkspacePortabilityReport,
    inspect_workspace_portability,
    scan_field_evidence,
)
from .gitstate import GitStateError, inspect_git_state
from .projection import inspect_projection_parity
from .schema_compat import SchemaCompatibilityReport, apply_schema_compatibility
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
    "INTERRUPTED_INPUT_NOT_DURABLE",
    "COMPACTION_STORAGE_AMPLIFICATION",
    "WORKSPACE_CONTEXT_MISMATCH",
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
    schema_compatibility: SchemaCompatibilityReport
    field_evidence: FieldEvidenceReport
    workspace_portability: WorkspacePortabilityReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "status": self.status,
            "findings": self.findings,
            "transcript": self.transcript.to_dict(),
            "repository": self.repository,
            "alpha5": self.alpha5.to_dict(),
            "projection": self.projection.to_dict(),
            "schema_compatibility": self.schema_compatibility.to_dict(),
            "field_evidence": self.field_evidence.to_dict(),
            "workspace_portability": self.workspace_portability.to_dict(),
        }


def _classify_git_error(exc: GitStateError) -> str:
    text = str(exc).lower()
    if "not a git repository" in text or "outside repository" in text:
        return "non_git_workspace"
    if "cwd does not exist" in text or "permission denied" in text or "access is denied" in text:
        return "inaccessible_repository"
    if "no such file or directory" in text or "not found" in text or "executable" in text:
        return "git_unavailable"
    return "git_unavailable_or_repository_inaccessible"


def doctor_session(path: str | Path, oversized_threshold: int = 1_000_000) -> DoctorResult:
    parsed = parse_transcript(path, oversized_threshold=oversized_threshold)
    schema_compatibility = apply_schema_compatibility(parsed)
    alpha5 = scan_rollout_alpha5(path)
    field_evidence = scan_field_evidence(path)
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

    if field_evidence.interrupted_input_boundary_count:
        findings.add("INTERRUPTED_INPUT_NOT_DURABLE")
    if field_evidence.storage_amplification:
        findings.add("COMPACTION_STORAGE_AMPLIFICATION")

    if projection.status == "wedged":
        findings.add("WEDGED_PROJECTION")
    elif projection.status == "active_write":
        findings.add("ACTIVE_WRITE_UNCERTAIN")
    elif projection.status == "unknown" and parsed.ordinal_mode == "paginated":
        findings.add("PROJECTION_STATE_UNKNOWN")

    cwd = parsed.session_metadata.get("cwd")
    workspace_portability = inspect_workspace_portability(cwd)
    repository: dict[str, Any]
    if cwd:
        try:
            repository = inspect_git_state(cwd).to_dict()
            repository["classification"] = "git_available"
        except GitStateError as exc:
            repository = {
                "cwd": cwd,
                "error": str(exc),
                "confidence": "unknown",
                "classification": _classify_git_error(exc),
            }
    else:
        repository = {"cwd": None, "confidence": "unknown", "classification": "no_workspace"}
    repository["workspace_portability"] = workspace_portability.to_dict()

    if (
        workspace_portability.mismatch
        and repository.get("classification") in {
            "inaccessible_repository",
            "git_unavailable_or_repository_inaccessible",
        }
    ):
        findings.add("WORKSPACE_CONTEXT_MISMATCH")

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
        schema_compatibility,
        field_evidence,
        workspace_portability,
    )
