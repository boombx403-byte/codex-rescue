from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .thread_store import (
    ROLLOUT_MISSING,
    THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE,
    WINDOWS_ROLLOUT_PATH_IDENTITY_DIVERGENCE,
)
from .transcript import MAX_RECORD_BYTES, _read_line_bounded

STALE_ACTIVE_PRESENTATION = "STALE_ACTIVE_PRESENTATION"
LIVE_TURN_PRESENTATION_DIVERGENCE = "LIVE_TURN_PRESENTATION_DIVERGENCE"
ARCHIVED_SUBAGENT_PRESENTATION_DIVERGENCE = "ARCHIVED_SUBAGENT_PRESENTATION_DIVERGENCE"
_START_TYPES = {
    "task_started",
    "turn_started",
    "agent_started",
    "agent_spawned",
    "thread_started",
}
_TERMINAL_TYPES = {
    "task_complete",
    "task_completed",
    "turn_complete",
    "turn_completed",
    "turn_aborted",
    "turn_failed",
    "turn_interrupted",
    "agent_complete",
    "agent_completed",
}
_CLOSED_TYPES = {
    "agent_closed",
    "thread_closed",
}


@dataclass(frozen=True)
class LifecycleTruth:
    status: str
    durable_state: str
    runtime_state: str
    presentation_state: str = "UNKNOWN"
    dispatchable: bool | None = None
    findings: tuple[str, ...] = field(default_factory=tuple)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = list(self.findings)
        return data


@dataclass(frozen=True)
class PresentationTruth:
    status: str
    presentation_state: str
    runtime_state: str
    findings: tuple[str, ...] = field(default_factory=tuple)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = list(self.findings)
        return data


@dataclass(frozen=True)
class DurableLifecycle:
    state: str
    last_event: str | None = None
    explicit_close: bool = False
    scan_complete: bool = True
    reason: str | None = None


def classify_subagent_lifecycle(
    *,
    durable_state: str,
    runtime_active: bool | None,
    presentation_active: bool | None = None,
) -> LifecycleTruth:
    durable = durable_state.upper()
    runtime = "ACTIVE" if runtime_active is True else ("IDLE" if runtime_active is False else "UNKNOWN")
    presentation = (
        "ACTIVE"
        if presentation_active is True
        else ("IDLE" if presentation_active is False else "UNKNOWN")
    )

    if durable == "CLOSED":
        if runtime_active is True:
            return LifecycleTruth(
                status="UNKNOWN",
                durable_state=durable,
                runtime_state=runtime,
                presentation_state=presentation,
                dispatchable=None,
                reason="explicitly closed durable state conflicts with proven live runtime evidence",
            )
        return LifecycleTruth(
            status="INACTIVE",
            durable_state=durable,
            runtime_state=runtime,
            presentation_state=presentation,
            dispatchable=False,
            reason="explicit close is durable and no live runtime evidence overrides it",
        )

    if runtime_active is True:
        if durable == "NON_TERMINAL":
            return LifecycleTruth(
                status="WORKING",
                durable_state=durable,
                runtime_state=runtime,
                presentation_state=presentation,
                dispatchable=True,
                reason="non-terminal durable turn and live runtime evidence prove current execution",
            )
        return LifecycleTruth(
            status="UNKNOWN",
            durable_state=durable,
            runtime_state=runtime,
            presentation_state=presentation,
            dispatchable=None,
            reason="live runtime evidence is present but durable lifecycle does not prove a non-terminal turn",
        )

    if durable == "TERMINAL":
        return LifecycleTruth(
            status="DONE",
            durable_state=durable,
            runtime_state=runtime,
            presentation_state=presentation,
            dispatchable=None,
            reason="terminal durable state proves the turn ended but does not prove the child was closed",
        )

    return LifecycleTruth(
        status="UNKNOWN",
        durable_state=durable,
        runtime_state=runtime,
        presentation_state=presentation,
        dispatchable=None,
        reason="available durable/runtime evidence does not establish current liveness",
    )


def classify_presentation_truth(
    *,
    ui_active: bool | None,
    ui_progress_visible: bool | None,
    backend_active: bool | None,
    backend_progress_observed: bool | None,
) -> PresentationTruth:
    if ui_active is None:
        runtime = "ACTIVE" if backend_active is True else ("IDLE" if backend_active is False else "UNKNOWN")
        return PresentationTruth(
            status="UNKNOWN",
            presentation_state="UNKNOWN",
            runtime_state=runtime,
            reason="Desktop presentation is not observable",
        )

    presentation = "ACTIVE" if ui_active else "IDLE"
    runtime = "ACTIVE" if backend_active is True else ("IDLE" if backend_active is False else "UNKNOWN")

    if ui_active is True and backend_active is False:
        return PresentationTruth(
            status="DIVERGED",
            presentation_state=presentation,
            runtime_state=runtime,
            findings=(STALE_ACTIVE_PRESENTATION,),
            reason="presentation reports active after backend/runtime evidence is idle",
        )

    if (
        ui_active is True
        and ui_progress_visible is False
        and backend_active is True
        and backend_progress_observed is True
    ):
        return PresentationTruth(
            status="DIVERGED",
            presentation_state=presentation,
            runtime_state=runtime,
            findings=(LIVE_TURN_PRESENTATION_DIVERGENCE,),
            reason="backend remains active with progress while the visible renderer stream is absent",
        )

    if backend_active is None:
        return PresentationTruth(
            status="UNKNOWN",
            presentation_state=presentation,
            runtime_state=runtime,
            reason="presentation is known but backend/runtime liveness is unknown",
        )

    return PresentationTruth(
        status="CONSISTENT",
        presentation_state=presentation,
        runtime_state=runtime,
        reason="observed presentation and backend/runtime evidence do not conflict",
    )


def classify_archived_subagent_presentation(
    *,
    is_subagent: bool,
    archived: bool,
    presented_top_level: bool | None,
) -> tuple[str, ...]:
    if is_subagent and archived and presented_top_level is True:
        return (ARCHIVED_SUBAGENT_PRESENTATION_DIVERGENCE,)
    return ()


def classify_archive_failure(
    *,
    source_exists: bool | None,
    error_text: str | None,
    windows_identity_divergence: bool | None,
) -> tuple[str, ...]:
    if source_exists is False:
        return (ROLLOUT_MISSING,)
    if source_exists is not True:
        return ()
    if windows_identity_divergence is True:
        return (WINDOWS_ROLLOUT_PATH_IDENTITY_DIVERGENCE,)
    text = (error_text or "").casefold()
    if any(token in text for token in ("os error 2", "thread not found", "archive", "unarchive", "reference")):
        return (THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE,)
    return ()


def scan_durable_lifecycle(path: str | Path, *, max_lines: int = 100_000) -> DurableLifecycle:
    source = Path(path)
    last_event: str | None = None
    last_state = "UNKNOWN"
    explicit_close = False
    lines = 0
    try:
        with source.open("rb") as stream:
            while lines < max_lines:
                line, oversized, _ = _read_line_bounded(stream, MAX_RECORD_BYTES)
                if not line:
                    break
                lines += 1
                if oversized:
                    return DurableLifecycle(
                        state="UNKNOWN",
                        last_event=last_event,
                        explicit_close=explicit_close,
                        scan_complete=False,
                        reason="oversized lifecycle record prevents complete classification",
                    )
                try:
                    record = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return DurableLifecycle(
                        state="UNKNOWN",
                        last_event=last_event,
                        explicit_close=explicit_close,
                        scan_complete=False,
                        reason="malformed lifecycle record prevents complete classification",
                    )
                payload = record.get("payload")
                payload = payload if isinstance(payload, dict) else {}
                candidates = [
                    record.get("type"),
                    record.get("event"),
                    payload.get("type"),
                    payload.get("event"),
                ]
                recognized = _START_TYPES | _TERMINAL_TYPES | _CLOSED_TYPES
                event = next(
                    (
                        str(value).casefold()
                        for value in candidates
                        if isinstance(value, str) and str(value).casefold() in recognized
                    ),
                    None,
                )
                if event in _START_TYPES:
                    last_event = event
                    last_state = "NON_TERMINAL"
                    explicit_close = False
                elif event in _TERMINAL_TYPES:
                    last_event = event
                    last_state = "TERMINAL"
                    explicit_close = False
                elif event in _CLOSED_TYPES:
                    last_event = event
                    last_state = "CLOSED"
                    explicit_close = True
            if lines >= max_lines:
                return DurableLifecycle(
                    state="UNKNOWN",
                    last_event=last_event,
                    explicit_close=explicit_close,
                    scan_complete=False,
                    reason="lifecycle scan limit reached",
                )
    except OSError as exc:
        return DurableLifecycle(
            state="UNKNOWN",
            scan_complete=False,
            reason=f"lifecycle source unreadable: {exc.__class__.__name__}",
        )
    return DurableLifecycle(
        state=last_state,
        last_event=last_event,
        explicit_close=explicit_close,
        scan_complete=True,
        reason="latest recognized durable lifecycle marker classified",
    )


__all__ = [
    "ARCHIVED_SUBAGENT_PRESENTATION_DIVERGENCE",
    "DurableLifecycle",
    "LIVE_TURN_PRESENTATION_DIVERGENCE",
    "LifecycleTruth",
    "PresentationTruth",
    "STALE_ACTIVE_PRESENTATION",
    "THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE",
    "classify_archive_failure",
    "classify_archived_subagent_presentation",
    "classify_presentation_truth",
    "classify_subagent_lifecycle",
    "scan_durable_lifecycle",
]
