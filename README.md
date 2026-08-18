# Codex Rescue 0.1.0 Alpha5

Codex Rescue inspects local OpenAI Codex session rollouts, diagnoses persistence/recovery hazards, and creates a separate recovery handoff without silently modifying the source session.

## What Codex Rescue is

Codex Rescue is a local, read-only-first diagnostic and recovery tool for Codex rollout JSONL and related local state. It treats persisted evidence as evidence, not as permission to invent missing tool results or replay uncertain side effects.

The core commands are `sessions`, `doctor`, `salvage`, and `verify`. Alpha5 adds read-only projection-parity and migration-consistency checks, filesystem-first session discovery, narrower schema compatibility, type-specific persisted response-item ID checks, conservative writer/lifecycle and interrupted-input diagnostics, workspace-portability evidence, and bounded large-rollout aggregates.

Codex Rescue does **not** fix upstream Codex transport, Desktop renderer, API, compaction-service, locking, cross-platform state migration, or authentication bugs.

## Alpha5 official installation

### npm/npx

Alpha5 is distributed through npm/npx:

```bash
npx codex-rescue@0.1.0-alpha.5 --help
```

The npm design does not install Python. A small Node launcher selects an installed platform package and starts its bundled standalone executable. It has no runtime binary downloader, no `curl | shell` path, no telemetry, and no `shell=true` execution.

## Global npm install

```bash
npm install -g codex-rescue@0.1.0-alpha.5
codex-rescue --help
```

## Standalone GitHub Release

The Alpha5 GitHub prerelease contains standalone binaries for Linux x64,
Windows x64, macOS arm64, and macOS x64. Use the matching binary from the
`v0.1.0-alpha.5` GitHub Release when npm is not suitable.

## Python development

Python remains the canonical implementation and is still covered by tests and
build qualification. PyPI is intentionally **not** an Alpha5 distribution
channel; use a checked-out source branch for Python development:

```bash
python -m pip install -e .
codex-rescue --help
```

The Python package has no runtime dependencies outside the standard library and requires Python 3.11 or newer.

## Quick start

```bash
codex-rescue --version
codex-rescue sessions
codex-rescue doctor --latest
codex-rescue salvage --latest --fork
codex-rescue verify <rescue-id>
```

For a known rollout path, bypass discovery and diagnose it directly:

```bash
codex-rescue doctor /path/to/rollout.jsonl
```

`salvage` requires `--fork`; recovery output is separate from the original rollout.

## `sessions`

```bash
codex-rescue sessions [--codex-home PATH] [--limit N] [--latest] [--json]
```

Alpha5 treats supported rollout roots as filesystem truth and uses compatible SQLite thread inventory only as read-only enrichment. This matters when a valid rollout exists but the sidebar/index DB row is missing or has empty preview fields.

Behavior:

- scans supported active and archived rollout roots, not the whole disk;
- keeps filesystem-only rollouts discoverable;
- surfaces DB-only rows whose rollout is missing;
- correlates by stable thread identity/path where available;
- normalizes common Windows/WSL path spellings for identity checks;
- deduplicates correlated candidates;
- applies a stable newest-first order and then `--limit`;
- never repairs or writes the SQLite inventory.

Inventory mismatch values are diagnostic evidence, not a request to rewrite Codex state.

## `doctor`

```bash
codex-rescue doctor SESSION [--json]
codex-rescue doctor --latest [--codex-home PATH] [--json]
```

`doctor` is read-only. It parses the rollout with bounded record handling, correlates tool-call/output state, evaluates known schema compatibility, inspects aggregate Alpha5 diagnostics, checks bounded interrupted-input and workspace-portability evidence, reads narrowly supported migration metadata, and where applicable compares a paginated canonical rollout with compatible projection state opened read-only.

Important findings include:

- `WEDGED_PROJECTION` — strong, stable projection cursor/ordinal evidence does not match canonical rollout progression;
- `PROJECTION_STATE_UNKNOWN` — projection evidence exists or is expected but cannot be interpreted safely;
- `SUBAGENT_HISTORY_BOUNDARY_SUSPECT` — a migrated zero-based paginated subagent has the exact field-reported EOF history-boundary shape that can hide still-present raw child history;
- `THREAD_NAME_METADATA_DIVERGED` — a legacy `session_index.jsonl` name is present while paginated SQLite thread metadata has no name; the raw name is not emitted;
- `INTERRUPTED_INPUT_NOT_DURABLE` — the retained bounded event window shows a turn start followed by abort/interruption before a conservative durable submitted-user marker; missing prompt text is not reconstructed;
- `WORKSPACE_CONTEXT_MISMATCH` — persisted Windows/WSL path-family evidence conflicts with the current runtime and the saved repository cwd is inaccessible;
- `INVALID_PERSISTED_ITEM_ID` — a persisted prefixed response-item ID conflicts with the concrete item type supported by current Codex protocol evidence;
- `INTERLEAVED_WRITERS` — explicit persisted writer identities show a conservative A-B-A interleave;
- `UNFINISHED_TOOL_CALL` — a persisted supported call has no matching persisted output; this does **not** prove the tool never executed;
- `UNKNOWN_OPERATIONAL_SCHEMA` — an unknown state-bearing operational record or ambiguous correlation remains fail-closed;
- `PERSISTED_PAGINATED_ORDINAL_REUSE` / `ORDINAL_ANALYSIS_INCOMPLETE` — persisted paginated ordinal evidence is reused or bounded tracking cannot prove uniqueness;
- `OVERSIZED_PAYLOAD` — at least one record exceeds the configured diagnostic threshold;
- `ACTIVE_WRITE_UNCERTAIN` — the rollout changed during a stability-sensitive scan;
- `INCOMPLETE_ROLLOUT` — zero-byte/header-only persisted state is incomplete and may be transient;
- `COMPACTION_STATE_LOSS`, `TRUNCATED_TRANSCRIPT`, `MALFORMED_RECORD`, `CORRUPTED_TOOL_CALL` — existing conservative Alpha diagnostics.

`HEALTHY` means no recognized structural/persistence finding was produced from the available evidence. It is not proof that upstream Codex, Desktop, transport, API, path migration, or semantic task state is healthy. A missing projection DB or unavailable optional metadata is not corruption and can be reported as not applicable/unknown.

## `salvage`

```bash
codex-rescue salvage SESSION --fork
codex-rescue salvage --latest --fork
```

The recovery model remains:

```text
ORIGINAL ROLLOUT -> READ ONLY
RECOVERY OUTPUT  -> NEW FORK / ARTIFACT
```

`salvage` snapshots source evidence, creates a separate rescue directory, records the recovery boundary/findings, and produces a continuation handoff. It does not silently mutate the source rollout, repair SQLite in place, fabricate missing tool output or prompt text, or automatically replay an uncertain side effect.

When a tail/tool boundary cannot be trusted, the recovery result stays conservative and requires review.

## `verify`

```bash
codex-rescue verify <rescue-id>
```

`verify` checks the rescue artifact and current repository evidence before continuation. A changed Git HEAD/worktree/fingerprint can force `REVIEW_REQUIRED` rather than pretending the previously captured state still applies.

A non-Git workspace, unavailable Git executable, or inaccessible repository is not automatically classified as Git divergence. Alpha5 reports those evidence states separately with unknown confidence where appropriate.

## Alpha5 detection capabilities

Alpha5 implements the following additional detection/compatibility boundaries:

- read-only dynamic inspection of compatible projection-state schemas;
- stale canonical suffix detection at a stored byte/ordinal projection cursor;
- exact boundary acceptance;
- conservative replayed boundary ordinal and field-reported N-to-N+1 cursor wedge detection;
- filesystem/index inventory mismatch discovery;
- narrow read-only migrated-subagent EOF-boundary detection without rewriting SessionMeta;
- bounded `session_index.jsonl` ↔ paginated SQLite thread-name consistency checking without emitting the raw name or a name digest;
- explicit compatibility for known current/historical event/response item types while unknown future operational schema remains fail-closed;
- current-protocol type-specific persisted response-item ID prefixes with legacy unprefixed-ID compatibility;
- bounded tool correlation with ambiguity/overflow lowering confidence;
- explicit persisted writer interleave evidence without equating normal subagent fan-out with corruption;
- persisted lifecycle wording that never turns a historical start marker into a claim that an agent is currently running;
- bounded retained-tail evidence for an interrupted turn whose submitted prompt never became durably observable;
- read-only Windows/WSL workspace path-family evidence without rewriting persisted paths;
- format-only opaque/encrypted-content classification without decryption or account-key diagnosis;
- zero-byte/header-only/changed-during-scan states;
- large-history aggregate record/media/compaction metrics without dumping large payloads.

## Recovery workflow

Use this order:

1. `sessions` to locate the candidate rollout or use a known direct path.
2. `doctor` to collect structural, projection, migration, schema, tool, lifecycle, writer, workspace, and size evidence.
3. Stop and inspect if the verdict is unknown/ambiguous or if the rollout appears actively written.
4. `salvage --fork` only when a separate recovery handoff is useful.
5. `verify <rescue-id>` immediately before continuation so repository drift is not ignored.
6. Continue manually from the verified fork/handoff; do not replay an uncertain tool call just because no persisted output exists, and do not invent a prompt that was never persisted.

## Alpha5 improvements

Compared with the Alpha4 code baseline, Alpha5 currently includes in code:

- `WEDGED_PROJECTION` and projection-state uncertainty reporting;
- filesystem-first discovery with read-only SQLite enrichment;
- read-only migrated-subagent boundary and thread-name metadata divergence diagnostics;
- bounded interrupted-input and Windows/WSL workspace-portability diagnostics;
- narrowed current/historical schema compatibility including `mcp_tool_call_begin` while preserving Alpha4's `mcp_tool_call_end` fix;
- type-specific persisted ResponseItem ID validation based on current upstream protocol prefixes;
- explicit interleaved-writer, lifecycle, opaque-format, incomplete-rollout, and active-write diagnostics;
- additional bounded large-rollout aggregates;
- Python version `0.1.0a5`;
- target npm version `0.1.0-alpha.5` with platform packages and a shell-free launcher;
- PyInstaller standalone build infrastructure;
- cross-platform core, native, npm packaging/security, parity, and Python package qualification workflows;
- Alpha5 regression suites and field-traceability documentation.

These are code changes. Runtime/build success must be established by CI; this README does not convert unexecuted workflow YAML into a validation claim.

## Platform support

Canonical Python source targets Python 3.11+.

Alpha5 CI is configured to exercise Python core tests on:

- Linux x64;
- Windows x64;
- macOS runners.

Standalone/npm qualification targets:

- Linux x64;
- Windows x64;
- macOS arm64;
- macOS x64/Intel while the GitHub Intel runner is available.

These targets have been exercised by the Alpha5 native/npm CI. Release support is qualified only when the current exact release-source SHA has the required jobs green; historical green runs do not qualify a later SHA.

## Safety model

Codex Rescue follows these boundaries:

- source rollout is read-only;
- projection/state SQLite is opened read-only and `query_only`;
- no generic in-place SQLite repair command;
- no automatic missing-output fabrication;
- no reconstruction of prompt text absent from durable rollout evidence;
- no automatic replay of unknown side effects;
- no automatic WSL/Windows path rewrite;
- no SessionMeta/session-index/thread-name repair in place;
- salvage writes a separate artifact/fork;
- malformed/unknown state-bearing operational schema fails closed;
- missing evidence becomes unknown/not-applicable rather than invented certainty;
- ordinary PR CI builds/tests artifacts but does not publish Alpha5, create a tag, or merge a PR.

The existing public Alpha4 tag/release is a separate released artifact and must not be moved or rewritten by Alpha5 work.

## Privacy

Session rollouts and Codex SQLite state can contain private prompts, source code, tool output, credentials, local paths, images, thread names, and encrypted/opaque content.

Codex Rescue analysis does not require uploading raw session data. Alpha5 diagnostics retain bounded metadata/aggregates where possible, do not decrypt opaque content, do not include opaque ciphertext in the Alpha5 aggregate report, and do not emit raw legacy thread names from the migration-consistency check.

Do **not** publish raw:

- rollout JSONL;
- Codex session/state databases;
- prompts or model/tool output;
- credentials/tokens/cookies;
- private repository paths or thread names;
- inline images/base64 media;
- encrypted/opaque payloads.
