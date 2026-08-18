from __future__ import annotations

import json
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .diff import diff_session
from .evidence import collect_session_evidence
from .redact import audit_privacy, sanitize_path
from .schema_inspector import inspect_schemas
from .timeline import build_timeline


@dataclass
class DiagnosticBundle:
    tool_version: str = f"codex-rescue {__version__}"
    platform: str = platform.platform()
    session_id: str = ""
    evidence_summary: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    state_diff: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, Any] = field(default_factory=dict)
    schema_info: dict[str, Any] = field(default_factory=dict)
    redaction_audit_passed: bool = False
    redaction_report: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_support_bundle(
    session_path: Path | str,
    output_bundle_path: Path | str | None = None,
    codex_home: Path | str | None = None,
) -> tuple[DiagnosticBundle, str | None]:
    path = Path(session_path).resolve()
    ev = collect_session_evidence(path, codex_home=codex_home)
    diff = diff_session(path, codex_home=codex_home)
    tl = build_timeline(path, max_events=200)
    schema = inspect_schemas(codex_home=codex_home, session_files=[path])

    bundle = DiagnosticBundle(
        session_id=ev.session_id,
        evidence_summary={
            "session_path": ev.session_path,
            "is_archived": ev.is_archived,
            "size_bytes": ev.size_bytes,
            "total_lines": ev.rollout.total_lines,
            "turn_count": ev.rollout.turn_count,
            "tool_call_count": ev.rollout.tool_call_count,
            "compaction_count": ev.rollout.compaction_count,
            "last_ordinal": ev.rollout.last_ordinal,
            "status": ev.status,
            "confidence": ev.confidence,
        },
        findings=ev.findings,
        state_diff=diff.to_dict(),
        timeline={"total_events": tl.total_events, "events_sample": [e.to_dict() for e in tl.events[:50]]},
        schema_info=schema.to_dict(),
    )

    bundle_dict = bundle.to_dict()
    violations = audit_privacy(bundle_dict)
    bundle.redaction_report = violations
    bundle.redaction_audit_passed = (len(violations) == 0)

    if not bundle.redaction_audit_passed:
        raise ValueError(f"Privacy Redaction Audit FAILED: Detected {len(violations)} leakage violation(s): {violations}")

    target_file = Path(output_bundle_path) if output_bundle_path else Path(f"support_bundle_{ev.session_id}.json")
    target_file.write_text(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    return bundle, str(target_file)


def audit_bundle_file(bundle_path: Path | str) -> list[str]:
    p = Path(bundle_path)
    if not p.exists():
        return [f"File not found: {bundle_path}"]
    try:
        content = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"Invalid JSON in artifact: {e}"]
    return audit_privacy(content)
