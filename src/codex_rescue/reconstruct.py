from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .gitstate import GitState


CONFIDENCE = {"verified", "reconstructed", "unknown"}


_SECRET_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_TOKEN]"),
)


def evidence(source: str, locator: str, note: str, digest: str | None = None) -> dict[str, Any]:
    return {"source": source, "locator": locator, "digest": digest, "note": note[:240]}


def _bounded(value: object, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = re.sub(r"data:[^;]+;base64,[A-Za-z0-9+/=]+", "[REDACTED_INLINE_PAYLOAD]", text)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > limit:
        digest = hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()[:16]
        return f"{text[:limit]}… [bounded sha256:{digest}]"
    return text


def _get(parsed: Any, name: str, default: Any = None) -> Any:
    if isinstance(parsed, dict):
        return parsed.get(name, default)
    return getattr(parsed, name, default)


def _event_payload(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        payload = event.get("payload")
    else:
        payload = getattr(event, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _event_type(event: Any) -> str | None:
    if isinstance(event, dict):
        return event.get("type") or _event_payload(event).get("type")
    return getattr(event, "type", None) or _event_payload(event).get("type")


def _events(parsed: Any) -> Iterable[Any]:
    return _get(parsed, "events", ()) or _get(parsed, "operational_events", ()) or ()


def build_handoff(
    session_ref: str,
    parsed: Any,
    git_state: GitState | None,
    journal_entries: list[dict[str, Any]],
    doctor_status: str,
    findings: list[str],
) -> dict[str, Any]:
    events = list(_events(parsed))
    metadata = _get(parsed, "session_metadata", {}) or {}
    cwd = metadata.get("cwd") if isinstance(metadata, dict) else None
    source_id = metadata.get("session_id") if isinstance(metadata, dict) else None
    source_id = source_id or Path(session_ref).stem

    last_prompt: str | None = None
    last_prompt_ref: dict[str, Any] | None = None
    completed: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        payload = _event_payload(event)
        payload_type = payload.get("type")
        if payload_type == "user_message":
            last_prompt = _bounded(payload.get("message"))
            last_prompt_ref = evidence("transcript", f"record:{index}", "last durable user message")
        if payload_type in {"function_call_output", "custom_tool_call_output", "tool_search_output"}:
            output = _bounded(payload.get("output"), 240)
            output_object = payload.get("output") if isinstance(payload.get("output"), dict) else {}
            raw_status = str(payload.get("status") or output_object.get("status") or "").lower()
            exit_code_value = payload.get("exit_code", output_object.get("exit_code"))
            failed = raw_status in {"failed", "error", "timeout", "cancelled", "canceled"} or (isinstance(exit_code_value, int) and exit_code_value != 0)
            completed.append(
                {
                    "action": f"tool result: {output or '[result recorded]'}",
                    "status": "failed" if failed else "completed",
                    "confidence": "verified",
                    "evidence_refs": [evidence("durable_tool_result", f"record:{index}", "durable tool output exists")],
                }
            )
        raw_output = payload.get("output")
        output_object = raw_output if isinstance(raw_output, dict) else {}
        command = payload.get("command") or output_object.get("command")
        exit_code = payload.get("exit_code")
        if exit_code is None:
            exit_code = output_object.get("exit_code")
        if command and exit_code is not None:
            tests.append(
                {
                    "command": _bounded(command, 240),
                    "result": "pass" if exit_code == 0 else "fail",
                    "exit_code": exit_code,
                    "confidence": "verified",
                    "evidence_refs": [evidence("durable_tool_result", f"record:{index}", "command exit code recorded")],
                }
            )

    latest_journal = journal_entries[-1] if journal_entries else {}
    if not last_prompt and latest_journal.get("last_user_prompt"):
        last_prompt = _bounded(latest_journal.get("last_user_prompt"))
        last_prompt_ref = evidence("journal", "latest:last_user_prompt", "external checkpoint")

    unfinished = _get(parsed, "unfinished_tool_calls", ()) or _get(parsed, "unfinished_calls", ()) or ()
    unfinished_items: list[dict[str, Any]] = []
    for raw_item in unfinished[:20]:
        item = raw_item if isinstance(raw_item, dict) else getattr(raw_item, "__dict__", {"value": str(raw_item)})
        unfinished_items.append(
            {
                "call_id": item.get("call_id"),
                "type": item.get("tool_name") or item.get("type") or "tool_call",
                "command_or_args_ref": _bounded(item.get("command") or item.get("arguments") or item, 300),
                "status": "unknown",
                "confidence": "unknown",
                "evidence_refs": [evidence("transcript", str(item.get("offset", "tail")), "call has no durable completion")],
            }
        )
    unfinished_item = unfinished_items[0] if unfinished_items else None

    transcript_hash = _get(parsed, "sha256") or _get(parsed, "transcript_hash")
    transcript = {
        "last_valid_offset": _get(parsed, "last_valid_offset", 0),
        "first_invalid_offset": _get(parsed, "first_invalid_offset"),
        "valid_record_count": _get(parsed, "valid_record_count", 0),
        "record_types": dict(_get(parsed, "record_types", {}) or {}),
        "oversized_records": list(_get(parsed, "oversized_records", ()) or ()),
        "hash": transcript_hash,
        "size": _get(parsed, "source_size"),
        "compacted": bool(_get(parsed, "compacted", False)),
        "corruption_class": doctor_status,
        "evidence_refs": [evidence("transcript", session_ref, "read-only source", transcript_hash)],
    }

    if git_state:
        repo_refs = [evidence("git", git_state.root, "current Git and working-tree state", git_state.diff_hash)]
        repository = {
            **git_state.to_dict(),
            "confidence": "verified",
            "evidence_refs": repo_refs,
        }
        session_cwd = git_state.cwd
        worktree = git_state.worktree
        head = git_state.head_sha
    else:
        repository = {"changed_files": [], "diff_hash": None, "confidence": "unknown", "evidence_refs": []}
        session_cwd = cwd
        worktree = None
        head = None

    pending = latest_journal.get("pending_action")
    pending_confidence = "reconstructed" if pending else "unknown"
    blocking_unknown = unfinished_item is not None or git_state is None or doctor_status in {
        "MALFORMED_RECORD", "TRUNCATED_TRANSCRIPT", "UNKNOWN_CORRUPTION", "REPO_STATE_DIVERGED"
    }
    overall = "unknown" if blocking_unknown else ("reconstructed" if last_prompt else "unknown")

    return {
        "version": 1,
        "session": {
            "source_id": source_id,
            "source_ref": session_ref,
            "cwd": session_cwd,
            "worktree": worktree,
            "base_sha": latest_journal.get("base_sha"),
            "current_head": head,
            "evidence_refs": transcript["evidence_refs"],
        },
        "goal": {
            "last_user_prompt": last_prompt,
            "confidence": "reconstructed" if last_prompt else "unknown",
            "evidence_refs": [last_prompt_ref] if last_prompt_ref else [],
        },
        "repository": repository,
        "progress": {
            "completed_actions": completed[-12:],
            "pending_action": {
                "action": _bounded(pending, 300),
                "confidence": pending_confidence,
                "evidence_refs": [evidence("journal", "latest:pending_action", "external checkpoint")] if pending else [],
            },
        },
        "tests": tests[-10:],
        "tool_state": {
            "unfinished_action": unfinished_item,
            "unfinished_actions": unfinished_items,
            "confidence": "unknown" if unfinished_item else "verified",
        },
        "transcript": transcript,
        "findings": findings,
        "overall_confidence": overall,
    }


def recovery_brief(handoff: dict[str, Any]) -> str:
    repo = handoff["repository"]
    progress = handoff["progress"]
    lines = [
        "# Codex Rescue Handoff",
        "",
        "## Goal",
        handoff["goal"].get("last_user_prompt") or "Unknown — inspect source evidence.",
        "",
        "## Verified repository state",
        f"- HEAD: {repo.get('head_sha') or 'unknown'}",
        f"- Diff hash: {repo.get('diff_hash') or 'unknown'}",
        f"- Changed files: {', '.join(repo.get('changed_files') or []) or 'none recorded'}",
        "",
        "## Completed with durable evidence",
    ]
    for action in progress.get("completed_actions") or []:
        lines.append(f"- [{action['confidence']}] {action['action']}")
    if not progress.get("completed_actions"):
        lines.append("- None safely established.")
    lines.extend(["", "## Uncertain / pending"])
    unfinished_actions = handoff["tool_state"].get("unfinished_actions") or []
    if not unfinished_actions and handoff["tool_state"].get("unfinished_action"):
        unfinished_actions = [handoff["tool_state"]["unfinished_action"]]
    for unfinished in unfinished_actions:
        lines.append(f"- [unknown] {unfinished.get('type')} ({unfinished.get('call_id') or 'unknown id'}): verify before repeating")
    pending = progress.get("pending_action", {}).get("action")
    lines.append(f"- {pending or 'Pending action is unknown.'}")
    lines.extend(["", "## Do not repeat", "- Do not replay any unknown tool call or reapply edits until the current diff is inspected."])
    return "\n".join(lines) + "\n"


def continuation_prompt(handoff_path: Path) -> str:
    return f"""You are continuing recovered work.

Read the structured handoff at: {handoff_path}

Treat VERIFIED facts as authoritative.
Treat RECONSTRUCTED facts as hypotheses.
Treat UNKNOWN facts as unresolved.

Before editing:
1. verify HEAD and diff against the handoff;
2. inspect unfinished or unknown actions;
3. do not repeat verified completed edits;
4. never replay an uncertain side-effecting command without checking its effects;
5. rerun tests only when evidence is missing or stale.
"""
