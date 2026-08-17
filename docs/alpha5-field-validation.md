# Alpha5 field validation traceability

This document maps public `openai/codex` field evidence to Codex Rescue Alpha5 code and regression coverage. It does not treat upstream reports as proof that Rescue itself failed unless a report actually exercised Rescue.

Raw rollouts/databases are intentionally not copied here. The issue reports repeatedly warn that those artifacts contain private prompts, paths, tool output, credentials, and media.

## Classification definitions

Only these classifications are used:

- `FIXED_IN_CODE_UNVERIFIED` — Alpha5 code/regression was added, but this branch has not yet earned CI/runtime qualification for the change.
- `VERIFIED_BY_CI` — reserved for a change whose required CI has actually passed on the qualifying commit. Do not use this merely because workflow YAML exists.
- `ALREADY_FIXED_IN_A4` — code inspection of the authoritative Alpha4 baseline shows the defect already handled there.
- `DETECTED_BOUNDED` — Rescue intentionally detects/reports a bounded symptom or safely limits analysis; it does not claim to fix the upstream product defect.

At document creation time no Alpha5 row is promoted to `VERIFIED_BY_CI`.

## Field evidence map

| Issue | Field evidence used | Rescue version exercised by report | Rescue defect vs upstream-only | Alpha5 implementation | Regression test | Classification |
|---|---|---|---|---|---|---|
| [#31113](https://github.com/openai/codex/issues/31113) | Persisted tool chain can end without the expected durable output/result; execution state can remain ambiguous. | N/A — upstream Codex report | Upstream failure shape; Rescue must not call it healthy or invent output. | Existing bounded call/output correlation retained; Alpha5 tests explicit missing/unmatched/duplicate/family/overflow cases. | `tests/test_alpha5_diagnostics.py` tool-correlation cases | `DETECTED_BOUNDED` |
| [#38629](https://github.com/openai/codex/issues/38629) | Multiple app-server writers can append interleaved persisted history. | N/A | Upstream locking/writer defect; Rescue classification defect if it interprets one incoherent stream as healthy. | Explicit persisted writer identity A-B-A interleave detection; no SQLite/rollout repair. | `test_explicit_a_b_a_writer_interleave_detected` | `FIXED_IN_CODE_UNVERIFIED` |
| [#24550](https://github.com/openai/codex/issues/24550) | ~703 MB rollout; compacted replacement history dominated by inline images; very large compacted lines affect transport/resume. | N/A | Upstream compaction/transport defect. | Bounded physical-record scan, oversize count, inline-media indicator, no base64 decode. | `test_large_record_scan_is_bounded_and_reports_inline_media` | `DETECTED_BOUNDED` |
| [#34337](https://github.com/openai/codex/issues/34337) | Shared rollout store can reach tens/hundreds of GiB; repeated compaction, parent/child inheritance, images, and tool output dominate. | N/A | Upstream storage architecture. | Linear bounded scans; no whole-file JSON load; aggregate size/compaction/media diagnostics. | Alpha5 large-record test plus existing hardening/E2E large-history coverage | `DETECTED_BOUNDED` |
| [#30779](https://github.com/openai/codex/issues/30779) | Persisted subagent/start history can outlive the actual execution and should not be read as live process state. | N/A | Upstream lifecycle/UI evidence; Rescue wording risk. | Historical lifecycle markers separated from unavailable live state. | `test_lifecycle_never_claims_historical_start_is_live` | `FIXED_IN_CODE_UNVERIFIED` |
| [#20864](https://github.com/openai/codex/issues/20864) | Valid rollout inventory can disagree with derived/index state. | N/A | Upstream index/inventory behavior; Rescue discovery defect if DB is sole truth. | Filesystem-first supported-root discovery with read-only DB enrichment and mismatch reporting. | `test_rollout_exists_db_row_absent_remains_discoverable`, DB-only test | `FIXED_IN_CODE_UNVERIFIED` |
| [#38855](https://github.com/openai/codex/issues/38855) | Persisted response item IDs can have a valid-looking prefix that is wrong for the concrete item type. | N/A | Upstream persisted identity defect; Rescue needs strong validation. | Current upstream `ResponseItem::id_prefix()` mapping; wrong prefixed type blocks healthy; missing/legacy IDs remain compatible. | valid/invalid/missing/legacy/future ID tests | `FIXED_IN_CODE_UNVERIFIED` |
| [#23930](https://github.com/openai/codex/issues/23930) | UI can show stale agent/activity state from historical persistence. | N/A | Upstream lifecycle/UI defect; Rescue must not assert current running state. | Lifecycle report says persisted marker observed/no terminal marker observed and live state unavailable. | lifecycle tests | `FIXED_IN_CODE_UNVERIFIED` |
| [#35463](https://github.com/openai/codex/issues/35463) | Subagent history/context can be duplicated/inherited during normal multi-agent operation; duplication is not itself proof of corrupt concurrent writers. | N/A | Upstream persistence/accounting behavior; false-positive risk in Rescue. | Writer corruption requires explicit writer identities and A-B-A interleave; parent/subagent metadata alone is ignored. | `test_normal_subagent_metadata_is_not_writer_corruption` | `FIXED_IN_CODE_UNVERIFIED` |
| [#13724](https://github.com/openai/codex/issues/13724) | Invalid encrypted-content failures were observed around account/org changes, but later successful resume evidence means account/key mismatch is not safely inferable from ciphertext alone. | N/A | Upstream encrypted-content failure; diagnosis-causality risk. | Format-only opaque classification; no decryption and no account-key root-cause assertion. | opaque-format tests | `FIXED_IN_CODE_UNVERIFIED` |
| [#36704](https://github.com/openai/codex/issues/36704) | `ocx1:` was reported as a foreign/proxy persisted marker; native/legacy opaque blobs have a different shape. | N/A | Upstream/foreign-format interoperability. | Distinguish `foreign_ocx1`, legacy fernet-like envelope, unknown opaque, malformed; never display ciphertext. | opaque-format and malformed tests | `FIXED_IN_CODE_UNVERIFIED` |
| [#38787](https://github.com/openai/codex/issues/38787) | Very large histories expose quadratic/expensive upstream list/resume behavior. | N/A | Upstream performance defect. | Rescue keeps parser/Alpha5 diagnostics linear and memory-bounded; correlation/ordinal maps are capped. | bounded scan/correlation overflow tests | `DETECTED_BOUNDED` |
| [#38613](https://github.com/openai/codex/issues/38613) | Newly materializing sessions can briefly have a zero-byte rollout. | N/A | Normal/transient upstream write state; false corruption risk. | Zero-byte/header-only => `INCOMPLETE_ROLLOUT`; changed scan => `ACTIVE_WRITE_UNCERTAIN`. | zero-byte/header-only and changed-during-read tests | `FIXED_IN_CODE_UNVERIFIED` |
| [#33796](https://github.com/openai/codex/issues/33796) | Multi-GB rollouts and very large stores occur in the field. | N/A | Upstream storage pressure. | Bounded record allocation, no media decode, aggregate counts only. | large-record bounded test plus existing hardening stress coverage | `DETECTED_BOUNDED` |
| [#38856](https://github.com/openai/codex/issues/38856) | Remote compaction/service failure is an upstream failure mode outside local rollout repair. | N/A | Upstream-only. | README/diagnostics explicitly do not claim to repair transport/remote compaction; local persisted symptoms can still be diagnosed conservatively. | existing compaction/tool/rollout tests | `DETECTED_BOUNDED` |
| [#33493](https://github.com/openai/codex/issues/33493) | 4.16 GB image-heavy rollout, 224 compactions, retained inline image payloads repeatedly copied. | N/A | Upstream compaction/storage. | Large-history aggregate diagnostics and compaction/media counters; no payload dump. | large-record bounded test | `DETECTED_BOUNDED` |
| [#35746](https://github.com/openai/codex/issues/35746) | Historical paginated projection behavior can leave the canonical read boundary at one replayed ordinal before the expected ordinal. | N/A | Upstream historical projection/materialization behavior; Rescue false-healthy risk. | Read-only projection parity accepts the supported replay shape as strong `WEDGED_PROJECTION`. | `test_replayed_boundary_ordinal_is_detected_conservatively` | `FIXED_IN_CODE_UNVERIFIED` |
| [#31433](https://github.com/openai/codex/issues/31433) | Valid active/archived rollout files can be absent from `state_5.sqlite`; Windows/WSL path variants matter. | N/A | Upstream index state; Rescue discovery defect if DB-only. | Filesystem truth, DB enrichment, archived discovery, path normalization. | discovery missing-row, archived, Windows/WSL tests | `FIXED_IN_CODE_UNVERIFIED` |
| [#34863](https://github.com/openai/codex/issues/34863) | 10.2 GB rollout; sampled compacted records roughly 50–80 MB and dominated by inline PNG data; analysis itself had to be streaming/fixed-size. | N/A | Upstream storage/memory defect. | Bounded line draining and aggregate-only media/record diagnostics. | large-record bounded test | `DETECTED_BOUNDED` |
| [#34446](https://github.com/openai/codex/issues/34446) | A valid rollout/DB row can have empty `first_user_message`/preview and disappear from derived UI inventory. | N/A | Upstream sidebar/index behavior; Rescue discovery defect if preview is required. | Discovery does not require DB preview/first-user-message to surface the rollout. | `test_empty_preview_and_first_user_message_do_not_hide_rollout` | `FIXED_IN_CODE_UNVERIFIED` |
| [#38792](https://github.com/openai/codex/issues/38792) | Projection DB byte cursor can be at a clean boundary whose canonical ordinal is N+1 while DB says next ordinal N; some cursors can point mid-record. | N/A | Upstream projection-state defect; direct Alpha5 false-healthy blocker. | Stable clean N→N+1 boundary => `WEDGED_PROJECTION`; mid-record cursor => unknown/fail-closed; no DB write. | N-to-N+1 and mid-record projection tests | `FIXED_IN_CODE_UNVERIFIED` |
| [#32976](https://github.com/openai/codex/issues/32976) | Durable side effects can exist even when the Desktop-visible/persisted transcript omits expected turn/tool history. | N/A | Upstream cross-surface persistence; Rescue inference risk. | Missing persisted output is only an unfinished/unknown correlation state and never proves non-execution. | missing-output test asserts no “did not execute” claim | `FIXED_IN_CODE_UNVERIFIED` |
| [#32974](https://github.com/openai/codex/issues/32974) | Windows CLI can silently exit while waiting on a tool/PostToolUse path; rollout ends without matching result or terminal event. | N/A | Distinct upstream silent-exit/tool-wait failure; not the same as #32976. | Existing unfinished-tool/truncated-tail diagnostics retained; lifecycle wording stays historical/unknown. | unfinished tool and incomplete-tail coverage | `DETECTED_BOUNDED` |

## Alpha4 baseline audit

The authoritative Alpha4 implementation was inspected before Alpha5 edits. The following are not reintroduced as Alpha5 “new fixes”:

- valid `mcp_tool_call_end` compatibility — `ALREADY_FIXED_IN_A4`;
- unavailable/non-Git repository evidence not being asserted as `REPO_STATE_DIVERGED` — `ALREADY_FIXED_IN_A4`;
- bounded persisted paginated ordinal reuse detection — `ALREADY_FIXED_IN_A4`.

Alpha5 extends these areas but does not rewrite the released Alpha4 tag or release.

## Primary upstream source anchors

Issue reports are field evidence; protocol/storage rules are taken from current public upstream source where a strong rule is required:

- `codex-rs/thread-store/src/local/thread_history.rs` and `thread_history_materialization.rs` define/read `thread_history_projection_state`, `next_rollout_byte_offset`, and `next_rollout_ordinal`.
- `codex-rs/protocol/src/models.rs` defines `ResponseItem::id_prefix()` for concrete persisted response-item types.
- `codex-rs/protocol/src/response_item_id.rs` constructs prefixed IDs and deliberately preserves legacy deserialization compatibility.
- `codex-rs/protocol/src/protocol.rs` confirms current event variants such as `McpToolCallBegin`, `McpToolCallEnd`, `ViewImageToolCall`, and dynamic tool request/response events.

Unknown future operational schema is not whitelisted from naming guesses.

## Qualification boundary

Every Alpha5 code/test row above remains `FIXED_IN_CODE_UNVERIFIED` or `DETECTED_BOUNDED` until required GitHub Actions succeed on the qualifying branch/PR commit. A future qualification agent may promote a row to `VERIFIED_BY_CI` only with actual check evidence; it must not edit this document based on workflow presence alone.
