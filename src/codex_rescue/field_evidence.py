from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .transcript import MAX_RECORD_BYTES, _read_line_bounded


MAX_FIELD_EVIDENCE = 32
_STORAGE_AMPLIFICATION_MIN_BYTES = 128 * 1024 * 1024
_STORAGE_AMPLIFICATION_MIN_RATIO = 0.50
_OUTER_TYPE_PREFIX_RE = re.compile(br'"type"\s*:\s*"([^"\\]+)"')
_WSL_MNT_RE = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")
_WINDOWS_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


@dataclass(frozen=True)
class WorkspacePortabilityReport:
    saved_cwd: str | None
    runtime_platform: str
    saved_path_family: str
    mismatch: bool
    confidence: str
    reason: str
    suggested_native_cwd: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "saved_cwd": self.saved_cwd,
            "runtime_platform": self.runtime_platform,
            "saved_path_family": self.saved_path_family,
            "mismatch": self.mismatch,
            "confidence": self.confidence,
            "reason": self.reason,
            "suggested_native_cwd": self.suggested_native_cwd,
        }


@dataclass
class FieldEvidenceReport:
    source_bytes: int = 0
    classified_record_bytes: int = 0
    unclassified_oversized_bytes: int = 0
    compaction_record_count: int = 0
    compaction_physical_bytes: int = 0
    compaction_byte_ratio: float = 0.0
    storage_amplification: bool = False
    storage_statement: str = "No strong persisted storage-amplification signal observed"
    interrupted_input_boundary_count: int = 0
    interrupted_input_boundaries: list[dict[str, Any]] = field(default_factory=list)
    interrupted_input_statement: str = "No conservative interrupted-input persistence gap observed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_bytes": self.source_bytes,
            "classified_record_bytes": self.classified_record_bytes,
            "unclassified_oversized_bytes": self.unclassified_oversized_bytes,
            "compaction_record_count": self.compaction_record_count,
            "compaction_physical_bytes": self.compaction_physical_bytes,
            "compaction_byte_ratio": self.compaction_byte_ratio,
            "storage_amplification": self.storage_amplification,
            "storage_statement": self.storage_statement,
            "interrupted_input_boundary_count": self.interrupted_input_boundary_count,
            "interrupted_input_boundaries": self.interrupted_input_boundaries,
            "interrupted_input_statement": self.interrupted_input_statement,
        }


def inspect_workspace_portability(cwd: object) -> WorkspacePortabilityReport:
    runtime = "windows" if os.name == "nt" else "posix"
    if not isinstance(cwd, str) or not cwd.strip():
        return WorkspacePortabilityReport(
            saved_cwd=None,
            runtime_platform=runtime,
            saved_path_family="unknown",
            mismatch=False,
            confidence="unknown",
            reason="no persisted working directory is available",
        )

    value = cwd.strip()
    wsl_match = _WSL_MNT_RE.match(value)
    windows_match = _WINDOWS_DRIVE_RE.match(value)

    if wsl_match:
        drive = wsl_match.group(1).upper()
        suffix = (wsl_match.group(2) or "").replace("/", "\\")
        suggested = f"{drive}:\\{suffix}" if suffix else f"{drive}:\\"
        if runtime == "windows":
            return WorkspacePortabilityReport(
                saved_cwd=value,
                runtime_platform=runtime,
                saved_path_family="wsl_mnt",
                mismatch=True,
                confidence="strong",
                reason="persisted WSL /mnt/<drive> cwd is being inspected by a Windows-native runtime",
                suggested_native_cwd=suggested,
            )
        return WorkspacePortabilityReport(
            saved_cwd=value,
            runtime_platform=runtime,
            saved_path_family="wsl_mnt",
            mismatch=False,
            confidence="bounded",
            reason="persisted cwd uses a WSL-style /mnt/<drive> path on a POSIX runtime",
        )

    if windows_match:
        drive = windows_match.group(1).lower()
        suffix = windows_match.group(2).replace("\\", "/")
        suggested = f"/mnt/{drive}/{suffix}" if suffix else f"/mnt/{drive}"
        if runtime == "posix":
            return WorkspacePortabilityReport(
                saved_cwd=value,
                runtime_platform=runtime,
                saved_path_family="windows_drive",
                mismatch=True,
                confidence="bounded",
                reason="persisted Windows drive cwd is being inspected by a POSIX runtime",
                suggested_native_cwd=suggested,
            )
        return WorkspacePortabilityReport(
            saved_cwd=value,
            runtime_platform=runtime,
            saved_path_family="windows_drive",
            mismatch=False,
            confidence="strong",
            reason="persisted cwd and runtime both use Windows-native path semantics",
        )

    return WorkspacePortabilityReport(
        saved_cwd=value,
        runtime_platform=runtime,
        saved_path_family="posix" if value.startswith("/") else "other",
        mismatch=False,
        confidence="bounded",
        reason=f"no explicit cross-platform cwd mismatch recognized on {sys.platform}",
    )


def _record_outer_type_from_prefix(line: bytes) -> str | None:
    match = _OUTER_TYPE_PREFIX_RE.search(line[:4096])
    if match is None:
        return None
    try:
        return match.group(1).decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_field_evidence(
    path: str | Path,
    *,
    max_record_bytes: int = MAX_RECORD_BYTES,
) -> FieldEvidenceReport:
    """Collect bounded field-driven evidence without retaining transcript content.

    The scanner is deliberately conservative.  It reports physical compaction
    dominance and interrupted turn boundaries, but it never claims to recreate a
    prompt that was not durably persisted and never treats storage amplification
    as proof of transcript corruption.
    """

    source = Path(path).expanduser().resolve()
    result = FieldEvidenceReport(source_bytes=source.stat().st_size)
    offset = 0
    turn_start_offset: int | None = None
    turn_context_seen = False
    durable_user_input_seen = False

    with source.open("rb") as stream:
        while True:
            start = offset
            line, oversized, consumed = _read_line_bounded(
                stream, max_bytes=max_record_bytes, digest=None
            )
            if not line:
                break
            offset += consumed

            record: dict[str, Any] | None = None
            outer_type: str | None = None
            payload: dict[str, Any] = {}
            if oversized:
                outer_type = _record_outer_type_from_prefix(line)
                if outer_type is None:
                    result.unclassified_oversized_bytes += consumed
            else:
                try:
                    decoded = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    decoded = None
                if isinstance(decoded, dict):
                    record = decoded
                    outer_type = str(record.get("type") or "unknown")
                    raw_payload = record.get("payload")
                    if isinstance(raw_payload, dict):
                        payload = raw_payload

            if outer_type is not None:
                result.classified_record_bytes += consumed
            if outer_type == "compacted":
                result.compaction_record_count += 1
                result.compaction_physical_bytes += consumed

            if record is None:
                continue

            payload_type = str(payload.get("type") or "").lower()
            if outer_type == "event_msg" and payload_type == "task_started":
                turn_start_offset = start
                turn_context_seen = False
                durable_user_input_seen = False
                continue

            if turn_start_offset is None:
                continue

            if outer_type == "turn_context":
                turn_context_seen = True

            # event_msg/user_message is the strongest durable marker for the
            # submitted prompt.  A post-turn_context response_item user message
            # is accepted as a compatibility fallback.  Earlier role=user
            # records may be injected context and therefore do not suppress a
            # finding by themselves.
            if outer_type == "event_msg" and payload_type == "user_message":
                durable_user_input_seen = True
            elif (
                outer_type == "response_item"
                and payload_type == "message"
                and str(payload.get("role") or "").lower() == "user"
                and turn_context_seen
            ):
                durable_user_input_seen = True

            if outer_type == "event_msg" and payload_type in {
                "turn_aborted",
                "turn_interrupted",
            }:
                if not durable_user_input_seen:
                    result.interrupted_input_boundary_count += 1
                    if len(result.interrupted_input_boundaries) < MAX_FIELD_EVIDENCE:
                        result.interrupted_input_boundaries.append(
                            {
                                "task_started_offset": turn_start_offset,
                                "terminal_offset": start,
                                "terminal_type": payload_type,
                                "reason": "turn ended before a conservative durable submitted-user-input marker was observed",
                            }
                        )
                turn_start_offset = None
                turn_context_seen = False
                durable_user_input_seen = False
            elif outer_type == "event_msg" and payload_type in {
                "task_complete",
                "task_completed",
                "turn_complete",
                "turn_completed",
                "turn_failed",
            }:
                turn_start_offset = None
                turn_context_seen = False
                durable_user_input_seen = False

    if result.source_bytes:
        result.compaction_byte_ratio = result.compaction_physical_bytes / result.source_bytes
    if (
        result.source_bytes >= _STORAGE_AMPLIFICATION_MIN_BYTES
        and result.compaction_physical_bytes >= _STORAGE_AMPLIFICATION_MIN_BYTES
        and result.compaction_byte_ratio >= _STORAGE_AMPLIFICATION_MIN_RATIO
    ):
        result.storage_amplification = True
        result.storage_statement = (
            "Compacted records dominate a large persisted rollout; this is storage-amplification evidence, "
            "not by itself transcript-corruption evidence"
        )
    if result.interrupted_input_boundary_count:
        result.interrupted_input_statement = (
            "At least one persisted turn ended before a conservative durable submitted-user-input marker; "
            "missing prompt text cannot be reconstructed from absent rollout data"
        )
    return result


__all__ = [
    "FieldEvidenceReport",
    "WorkspacePortabilityReport",
    "inspect_workspace_portability",
    "scan_field_evidence",
]
