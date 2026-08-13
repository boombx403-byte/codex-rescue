from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .gitstate import GitStateError, inspect_git_state
from .transcript import ParseResult, parse_transcript


SEVERITY = [
    "UNKNOWN_CORRUPTION",
    "MALFORMED_RECORD",
    "TRUNCATED_TRANSCRIPT",
    "OVERSIZED_PAYLOAD",
    "UNKNOWN_OPERATIONAL_SCHEMA",
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "status": self.status,
            "findings": self.findings,
            "transcript": self.transcript.to_dict(),
            "repository": self.repository,
        }


def doctor_session(path: str | Path, oversized_threshold: int = 1_000_000) -> DoctorResult:
    parsed = parse_transcript(path, oversized_threshold=oversized_threshold)
    findings: set[str] = set()
    if parsed.corruption_class:
        findings.add(parsed.corruption_class)
    if parsed.oversized_records:
        findings.add("OVERSIZED_PAYLOAD")
    if parsed.operational_schema_issues or parsed.correlation_ambiguities:
        findings.add("UNKNOWN_OPERATIONAL_SCHEMA")
    if parsed.unfinished_tool_calls:
        findings.add("UNFINISHED_TOOL_CALL")
    if parsed.compaction_state_loss:
        findings.add("COMPACTION_STATE_LOSS")

    cwd = parsed.session_metadata.get("cwd")
    repository: dict[str, Any]
    if cwd:
        try:
            repository = inspect_git_state(cwd).to_dict()
        except GitStateError as exc:
            findings.add("REPO_STATE_DIVERGED")
            repository = {"cwd": cwd, "error": str(exc), "confidence": "unknown"}
    else:
        repository = {"cwd": None, "confidence": "unknown"}

    if not findings:
        findings.add("HEALTHY")
    status = next(label for label in SEVERITY if label in findings)
    return DoctorResult(str(Path(path).resolve()), status, sorted(findings, key=SEVERITY.index), parsed, repository)
