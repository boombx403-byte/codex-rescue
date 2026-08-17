# Codex Rescue 0.1.0 Alpha5

Codex Rescue inspects local OpenAI Codex session rollouts, diagnoses persistence/recovery hazards, and creates a separate recovery handoff without silently modifying the source session.

## What Codex Rescue is

Codex Rescue is a local, read-only-first diagnostic and recovery tool for Codex rollout JSONL and related local state. It treats persisted evidence as evidence, not as permission to invent missing tool results or replay uncertain side effects.

The core commands are `sessions`, `doctor`, `salvage`, and `verify`. Alpha5 adds read-only projection-parity checks, filesystem-first session discovery, narrower schema compatibility, type-specific persisted response-item ID checks, conservative writer/lifecycle diagnostics, and bounded large-rollout aggregates.

Codex Rescue does **not** fix upstream Codex transport, Desktop renderer, API, compaction-service, locking, or authentication bugs.

## Fastest npm/npx install

Alpha5 targets the following command:

```bash
npx codex-rescue@0.1.0-alpha.5 --help
```

**UNVERIFIED / prerelease target:** the npm package names, native binaries, tarballs, and registry availability are not considered qualified until the Alpha5 native/npm CI matrix and manual registry-name preflight pass. The repository does not claim that this command is currently publishable or available from npm.

The npm design does not install Python. A small Node launcher selects an installed platform package and starts its bundled standalone executable. It has no runtime binary downloader, no `curl | shell` path, no telemetry, and no `shell=true` execution.

## Global npm install

Alpha5 target:

```bash
npm install -g codex-rescue@0.1.0-alpha.5
codex-rescue --help
```

This is subject to the same **UNVERIFIED prerelease** qualification boundary as the `npx` path above.

## pipx

Python remains the canonical implementation. Alpha5 target:

```bash
pipx install codex-rescue==0.1.0a5
codex-rescue --help
```

Until Alpha5 is actually released to PyPI, install from a checked-out source branch for development instead of assuming the version exists on the registry.

## pip

Alpha5 target:

```bash
python -m pip install codex-rescue==0.1.0a5
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

`doctor` is read-only. It parses the rollout with bounded record handling, correlates tool-call/output state, evaluates known schema compatibility, inspects aggregate Alpha5 diagnostics, and where applicable compares a paginated canonical rollout with compatible projection state opened read-only.

Important findings include:

- `WEDGED_PROJECTION` — strong, stable projection cursor/ordinal evidence does not match canonical rollout progression;
- `PROJECTION_STATE_UNKNOWN` — projection evidence exists or is expected but cannot be interpreted safely;
- `INVALID_PERSISTED_ITEM_ID` — a persisted prefixed response-item ID conflicts with the concrete item type supported by current Codex protocol evidence;
- `INTERLEAVED_WRITERS` — explicit persisted writer identities show a conservative A-B-A interleave;
- `UNFINISHED_TOOL_CALL` — a persisted supported call has no matching persisted output; this does **not** prove the tool never executed;
- `UNKNOWN_OPERATIONAL_SCHEMA` — an unknown state-bearing operational record or ambiguous correlation remains fail-closed;
- `PERSISTED_PAGINATED_ORDINAL_REUSE` / `ORDINAL_ANALYSIS_INCOMPLETE` — persisted paginated ordinal evidence is reused or bounded tracking cannot prove uniqueness;
- `OVERSIZED_PAYLOAD` — at least one record exceeds the configured diagnostic threshold;
- `ACTIVE_WRITE_UNCERTAIN` — the rollout changed during a stability-sensitive scan;
- `INCOMPLETE_ROLLOUT` — zero-byte/header-only persisted state is incomplete and may be transient;
- `COMPACTION_STATE_LOSS`, `TRUNCATED_TRANSCRIPT`, `MALFORMED_RECORD`, `CORRUPTED_TOOL_CALL` — existing conservative Alpha diagnostics.

`HEALTHY` means no recognized structural/persistence finding was produced from the available evidence. It is not proof that upstream Codex, Desktop, transport, API, or semantic task state is healthy. A missing projection DB is not corruption and can be reported as not applicable.

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

`salvage` snapshots source evidence, creates a separate rescue directory, records the recovery boundary/findings, and produces a continuation handoff. It does not silently mutate the source rollout, repair SQLite in place, fabricate missing tool output, or automatically replay an uncertain side effect.

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
- explicit compatibility for known current/historical event/response item types while unknown future operational schema remains fail-closed;
- current-protocol type-specific persisted response-item ID prefixes with legacy unprefixed-ID compatibility;
- bounded tool correlation with ambiguity/overflow lowering confidence;
- explicit persisted writer interleave evidence without equating normal subagent fan-out with corruption;
- persisted lifecycle wording that never turns a historical start marker into a claim that an agent is currently running;
- format-only opaque/encrypted-content classification without decryption or account-key diagnosis;
- zero-byte/header-only/changed-during-scan states;
- large-history aggregate record/media/compaction metrics without dumping large payloads.

## Recovery workflow

Use this order:

1. `sessions` to locate the candidate rollout or use a known direct path.
2. `doctor` to collect structural, projection, schema, tool, lifecycle, writer, and size evidence.
3. Stop and inspect if the verdict is unknown/ambiguous or if the rollout appears actively written.
4. `salvage --fork` only when a separate recovery handoff is useful.
5. `verify <rescue-id>` immediately before continuation so repository drift is not ignored.
6. Continue manually from the verified fork/handoff; do not replay an uncertain tool call just because no persisted output exists.

## Alpha5 improvements

Compared with the Alpha4 code baseline, Alpha5 currently includes in code:

- `WEDGED_PROJECTION` and projection-state uncertainty reporting;
- filesystem-first discovery with read-only SQLite enrichment;
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
- macOS arm64.

Standalone/npm qualification targets:

- Linux x64;
- Windows x64;
- macOS arm64;
- macOS x64/Intel while the GitHub Intel runner is available.

**Native/npm support remains UNVERIFIED until the corresponding CI jobs actually succeed.** A workflow target is not proof that a binary runs.

## Safety model

Codex Rescue follows these boundaries:

- source rollout is read-only;
- projection/state SQLite is opened read-only and `query_only`;
- no generic in-place SQLite repair command;
- no automatic missing-output fabrication;
- no automatic replay of unknown side effects;
- salvage writes a separate artifact/fork;
- malformed/unknown state-bearing operational schema fails closed;
- missing evidence becomes unknown/not-applicable rather than invented certainty;
- ordinary PR CI builds/tests artifacts but does not publish Alpha5, create a tag, or merge a PR.

The existing public Alpha4 tag/release is a separate released artifact and must not be moved or rewritten by Alpha5 work.

## Privacy

Session rollouts and Codex SQLite state can contain private prompts, source code, tool output, credentials, local paths, images, and encrypted/opaque content.

Codex Rescue analysis does not require uploading raw session data. Alpha5 diagnostics retain bounded metadata/aggregates where possible and do not decrypt opaque content or include opaque ciphertext in the Alpha5 aggregate report.

Do **not** publish raw:

- rollout JSONL;
- Codex session/state databases;
- prompts or model/tool output;
- credentials/tokens/cookies;
- private repository paths;
- inline images/base64 media;
- encrypted/opaque payloads.

Sanitize evidence before opening a public issue.

## JSON output

`sessions`, `doctor`, `salvage`, and `verify` support JSON where the CLI exposes `--json`. CLI JSON is wrapped in:

```json
{
  "schema_version": 1,
  "data": {}
}
```

`doctor` includes transcript evidence plus Alpha5 aggregate diagnostics, projection status, schema-compatibility counts, and repository evidence classification. Unknown schema reporting aggregates type/count information and does not dump the unknown payload body.

Consumers should treat unknown fields/statuses as forward-compatible data, not as permission to assume health.

## Large-rollout behavior

The canonical parser and Alpha5 scan are sequential and bounded-memory rather than whole-file JSON loads. Oversized physical JSONL records are drained in bounded chunks; Alpha5 does not base64-decode media just to diagnose size pressure.

Alpha5 can expose aggregate information such as:

- total rollout size from filesystem metadata/parser output;
- largest physical record observed;
- bounded-record overflow count;
- inline media indicators observed in the bounded record prefix;
- compaction record count.

Limits are deliberate. A record too large to parse within the bounded record window is not fully semantically inspected. Correlation/ordinal state also has explicit caps; overflow reduces confidence instead of producing false `HEALTHY`.

Alpha5 currently performs an additional bounded linear scan for these aggregates, so very large rollouts incur additional sequential I/O even though memory stays bounded.

## Known limitations

- Alpha5 code and tests in the preparation branch are not runtime-verified until Actions complete successfully.
- npm package-name availability/ownership is not assumed; manual registry preflight is required before release.
- No Alpha5 package, native binary, npm package, GitHub tag, or release is published by ordinary PR CI.
- Projection parity only applies when a stable thread identity, paginated rollout evidence, supported session root, readable compatible state, and trustworthy byte boundary are available.
- A missing projection DB is not a defect. A malformed/ambiguous projection store fails closed rather than being repaired.
- Discovery is bounded to supported rollout roots and immediate Codex-home database candidates; it is not an arbitrary whole-disk crawler.
- Inventory scanning is bounded; Rescue does not claim to reconstruct every undocumented future Codex DB schema.
- Interleaved-writer detection requires explicit persisted writer identity evidence and deliberately avoids treating ordinary subagent concurrency as corruption.
- Persisted lifecycle records cannot prove current live process/agent state.
- Opaque/encrypted content is never decrypted; format labels are diagnostic only and do not prove an account/key root cause.
- An absent persisted tool output does not prove the tool did not execute.
- Rescue does not fix upstream Codex networking, remote compaction, Desktop UI/renderer, app-server locking, process lifecycle, API, or service bugs.
- No in-place SQLite repair is provided in Alpha5.

## npm ↔ Python version mapping

| Distribution surface | Alpha5 version |
|---|---|
| Python package | `0.1.0a5` |
| npm top/platform packages | `0.1.0-alpha.5` |
| Intended GitHub tag | `v0.1.0-alpha.5` |

The intended tag is a mapping convention only. Alpha5 preparation must not create the tag before qualification/release authorization.

## Development/testing

Source development:

```bash
python -m pip install -e .
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
python tests/e2e/harness_e2e.py --tier all
node --test npm/tests/*.test.cjs
```

Python package qualification:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Native/npm builds are intentionally delegated to `.github/workflows/alpha5-native-npm.yml`. That workflow builds PyInstaller one-file executables, smoke-tests them, records SHA256, assembles platform npm packages, runs `npm pack`, audits tarball allowlists, installs local tarballs with lifecycle scripts disabled, runs version/help/doctor smoke checks, and compares structured JSON semantics across Python/native/npm paths.

Do not replace CI evidence with a claim that workflow configuration alone proves a target works.

## License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 shleder.
