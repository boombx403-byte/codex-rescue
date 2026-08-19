# Alpha6 lifecycle and presentation truth

This stabilization pass separates four evidence layers instead of treating Desktop presentation text as authoritative state:

1. canonical persisted rollout source;
2. durable derived/thread-store state;
3. live runtime evidence that Rescue can actually observe;
4. Desktop presentation state.

If two observable authoritative layers conflict, Rescue reports divergence. If a layer cannot be inspected, it remains `UNKNOWN`. Alpha6 does **not** instrument the Desktop renderer, so graph/session diagnostics must not fabricate `Thinking`, `Working`, or renderer-stream state from persisted history.

## Subagent lifecycle

A non-terminal durable turn plus proven live runtime evidence may be classified `WORKING`.

A terminal/completed durable child is classified `DONE` unless there is stronger contradictory evidence. Terminal does **not** mean explicitly closed, and the absence of a live writer does not prove that a retained child is non-dispatchable. Therefore `DONE` leaves dispatchability unknown unless real reusable/closed evidence exists.

An explicit durable `agent_closed` or `thread_closed` state with no conflicting proven live runtime is `INACTIVE` and not dispatchable. If durable close and proven live runtime disagree, Rescue reports lifecycle state as `UNKNOWN` rather than choosing one layer arbitrarily.

Nested subagent edges are traversed read-only. Existing `lifecycle_status` remains for compatibility; additive fields expose `lifecycle_class`, `durable_state`, `runtime_state`, `presentation_state`, `dispatchable`, and deterministic finding IDs.

## Presentation findings

`STALE_ACTIVE_PRESENTATION` means explicit presentation evidence says active while backend/runtime evidence says idle.

`LIVE_TURN_PRESENTATION_DIVERGENCE` means explicit presentation evidence is active but its visible progress stream is absent while backend/runtime evidence remains active and continues to show progress.

`ARCHIVED_SUBAGENT_PRESENTATION_DIVERGENCE` is only valid when evidence establishes all three facts: the session is a subagent, it is archived, and it is being presented as a top-level conversation. Archived storage alone is not corruption, accidental unarchive, source data loss, or a deletion candidate.

Because Alpha6 has no direct Desktop UI probe, these presentation findings are domain classifications unless a caller supplies actual presentation evidence. Normal graph output therefore reports `presentation_state: UNKNOWN`.

## Archive and thread-store failures

`THREAD_STORE_PATH_OR_REFERENCE_DIVERGENCE` is the generic read-only classification when persisted thread-store/reference evidence is proven inconsistent but the exact Windows extended-path identity bug is not established.

An archive failure containing `os error 2` or `thread not found` while the source rollout still exists is not enough to emit `ROLLOUT_MISSING`. If the `C:\...` versus `\\?\C:\...` identity boundary is independently proven, Rescue uses the more specific `WINDOWS_ROLLOUT_PATH_IDENTITY_DIVERGENCE` finding instead.

No classifier in this pass rewrites Codex SQLite, archives/unarchives sessions, deletes source rollouts, renames files, repairs references, or changes Desktop state.
