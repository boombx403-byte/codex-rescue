from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TranscriptEvent:
    offset: int
    end_offset: int
    type: str | None
    payload: dict[str, Any]


@dataclass
class ParseResult:
    path: str
    source_size: int = 0
    last_valid_offset: int = 0
    first_invalid_offset: int | None = None
    valid_record_count: int = 0
    record_types: Counter[str] = field(default_factory=Counter)
    oversized_records: list[dict[str, Any]] = field(default_factory=list)
    corruption_class: str | None = None
    recoverable_prefix: bool = True
    sha256: str = ""
    session_metadata: dict[str, Any] = field(default_factory=dict)
    events: list[TranscriptEvent] = field(default_factory=list)
    unfinished_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    compacted: bool = False
    operational_events_after_compaction: int = 0
    compaction_state_loss: bool = False
    compaction_loss_evidence: list[dict[str, Any]] = field(default_factory=list)
    malformed_tool_arguments: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source_size": self.source_size,
            "last_valid_offset": self.last_valid_offset,
            "first_invalid_offset": self.first_invalid_offset,
            "valid_record_count": self.valid_record_count,
            "record_types": dict(self.record_types),
            "oversized_records": self.oversized_records,
            "corruption_class": self.corruption_class,
            "recoverable_prefix": self.recoverable_prefix,
            "sha256": self.sha256,
            "session_metadata": self.session_metadata,
            "unfinished_tool_calls": self.unfinished_tool_calls,
            "compacted": self.compacted,
            "operational_events_after_compaction": self.operational_events_after_compaction,
            "compaction_state_loss": self.compaction_state_loss,
            "compaction_loss_evidence": self.compaction_loss_evidence,
            "malformed_tool_arguments": self.malformed_tool_arguments,
        }


def _record_kind(record: dict[str, Any]) -> str:
    outer = str(record.get("type") or "unknown")
    payload = record.get("payload")
    inner = payload.get("type") if isinstance(payload, dict) else None
    return f"{outer}/{inner}" if inner else outer


def _safe_session_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "session_id", "id", "parent_thread_id", "timestamp", "cwd",
        "originator", "cli_version", "source", "thread_source",
        "model_provider", "history_mode", "context_window",
    )
    return {key: payload.get(key) for key in allowed if key in payload}


def _looks_like_large_inline_payload(line: bytes, record_kind: str, threshold: int) -> bool:
    if len(line) > threshold:
        return True
    # Small/medium data URLs are normal Codex records and must not make an
    # otherwise healthy session look damaged. Only flag an inline payload when
    # the record itself is materially large.
    payload_floor = max(256 * 1024, threshold // 2)
    if len(line) < payload_floor:
        return False
    return b"data:image" in line or b"base64" in line


def _call_data(event: TranscriptEvent) -> tuple[str | None, str | None, object | None]:
    payload = event.payload
    kind = payload.get("type")
    if kind in {"function_call", "custom_tool_call", "tool_search_call"}:
        return str(payload.get("call_id") or payload.get("id") or ""), str(payload.get("name") or "tool_call"), payload.get("arguments", payload.get("input"))
    return None, None, None


def parse_transcript(path: str | Path, oversized_threshold: int = 1_000_000, max_events: int = 5000) -> ParseResult:
    source = Path(path).resolve()
    result = ParseResult(path=str(source), source_size=source.stat().st_size)
    digest = hashlib.sha256()
    calls: dict[str, dict[str, Any]] = {}
    completions: set[str] = set()
    last_compaction_index: int | None = None
    offset = 0
    event_tail: deque[TranscriptEvent] = deque(maxlen=max_events)
    invalid_seen = False

    with source.open("rb") as stream:
        while True:
            start = offset
            line = stream.readline()
            if not line:
                break
            offset += len(line)
            digest.update(line)
            has_nul = b"\x00" in line
            if has_nul:
                if result.first_invalid_offset is None:
                    result.first_invalid_offset = start
                result.corruption_class = "MALFORMED_RECORD"
                invalid_seen = True
                break
            complete_line = line.endswith(b"\n")
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("record must be a JSON object")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                if result.first_invalid_offset is None:
                    result.first_invalid_offset = start
                result.corruption_class = "TRUNCATED_TRANSCRIPT" if not complete_line and not invalid_seen else "MALFORMED_RECORD"
                invalid_seen = True
                break

            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            kind = _record_kind(record)
            is_oversized = _looks_like_large_inline_payload(line, kind, oversized_threshold)
            stored_payload = payload
            if is_oversized:
                stored_payload = {
                    key: payload.get(key)
                    for key in ("type", "id", "call_id", "name", "role")
                    if key in payload
                }
                stored_payload["_oversized_payload"] = {"byte_length": len(line), "sha256": hashlib.sha256(line).hexdigest()}
            event = TranscriptEvent(start, offset, record.get("type"), stored_payload)
            result.valid_record_count += 1
            if not invalid_seen:
                result.last_valid_offset = offset
            result.record_types[kind] += 1
            event_tail.append(event)
            if record.get("type") == "session_meta":
                result.session_metadata = _safe_session_metadata(payload)
            if is_oversized:
                result.oversized_records.append(
                    {"start_offset": start, "end_offset": offset, "byte_length": len(line), "record_type": kind, "reason": "record/payload exceeds bounded processing threshold"}
                )
            if record.get("type") == "compacted":
                result.compacted = True
                last_compaction_index = result.valid_record_count
                replacement = payload.get("replacement_history")
                summary = payload.get("message") or payload.get("summary")
                prior_tool_events = [
                    item for item in list(event_tail)[-25:-1]
                    if item.payload.get("type") in {"function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output"}
                ]
                # A current-format compacted record with an explicitly empty replacement
                # history despite a recent durable operational tail is a conservative,
                # structural loss signal. Merely having later events is not.
                if replacement == [] and summary and prior_tool_events:
                    result.compaction_state_loss = True
                    result.compaction_loss_evidence.append(
                        {
                            "compaction_offset": start,
                            "recent_operational_records": len(prior_tool_events),
                            "reason": "empty replacement_history omitted a recent durable operational tail",
                        }
                    )
            elif payload.get("type") == "context_compacted":
                result.compacted = True
                last_compaction_index = result.valid_record_count
            elif last_compaction_index is not None and (record.get("type") in {"response_item", "event_msg"}):
                result.operational_events_after_compaction += 1

            call_id, tool_name, arguments = _call_data(event)
            if call_id:
                malformed_args = False
                if isinstance(arguments, str):
                    try:
                        json.loads(arguments)
                    except json.JSONDecodeError:
                        # apply_patch and free-form custom tools legitimately use raw text.
                        malformed_args = tool_name not in {"apply_patch"} and arguments.lstrip().startswith(("{", "["))
                if malformed_args:
                    result.malformed_tool_arguments.append({"offset": start, "call_id": call_id, "tool_name": tool_name})
                calls[call_id] = {"offset": start, "call_id": call_id, "tool_name": tool_name, "arguments": arguments}
            if payload.get("type") in {"function_call_output", "custom_tool_call_output", "tool_search_output"}:
                completion_id = str(payload.get("call_id") or payload.get("id") or "")
                if completion_id:
                    completions.add(completion_id)

    # Continue hashing remaining bytes without parsing after the first invalid record.
    with source.open("rb") as stream:
        stream.seek(offset)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    result.sha256 = digest.hexdigest()
    result.events = list(event_tail)
    result.unfinished_tool_calls = [value for key, value in calls.items() if key not in completions]
    if result.malformed_tool_arguments and result.corruption_class is None:
        result.corruption_class = "MALFORMED_RECORD"
    elif result.oversized_records and result.corruption_class is None:
        result.corruption_class = "OVERSIZED_PAYLOAD"
    return result
