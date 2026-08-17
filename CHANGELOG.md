# Changelog

All notable changes to Codex Rescue are documented here.

## v0.1.0-alpha.5 — prepared, unreleased

### Added

- Read-only projection parity diagnostics with `WEDGED_PROJECTION` for stable canonical suffix/cursor mismatches supported by upstream field evidence, including exact expected-ordinal suffixes, one replayed boundary ordinal followed by the expected ordinal, and the field-reported stable N-to-N+1 cursor wedge.
- `PROJECTION_STATE_UNKNOWN` for malformed, ambiguous, misaligned, or otherwise unsafe-to-interpret projection evidence; missing projection state remains not-applicable rather than corruption.
- Filesystem-first session discovery with read-only SQLite thread-inventory enrichment, DB/filesystem mismatch reporting, archived-session handling, stable ordering/limits, logical deduplication, and Windows/WSL path identity normalization.
- Explicit current/historical schema compatibility for known records that Alpha4's conservative heuristic could misclassify, while future state-bearing operational records remain fail-closed.
- Privacy-safe unknown schema type/count aggregation.
- Type-specific persisted response-item ID prefix validation based on current Codex protocol evidence, with compatibility for missing optional IDs and legacy unprefixed IDs.
- Conservative A-B-A persisted writer interleave detection using explicit writer identities; normal subagent fan-out alone is not corruption evidence.
- Persisted lifecycle diagnostics that distinguish historical start/terminal records from unavailable live state.
- Format-only opaque-content classification for recognized legacy opaque envelopes, the reported foreign `ocx1:` marker, unknown opaque values, and malformed fields; no decryption or account-key diagnosis.
- Zero-byte/header-only and changed-during-scan diagnostics.
- Bounded large-rollout aggregates for physical record size, bounded overflows, inline-media indicators, and compaction counts without base64 decoding.
- Alpha5 synthetic regression suites for projection, discovery, schema compatibility, typed IDs, tool correlation, writer/lifecycle semantics, opaque formats, incomplete rollouts, and bounded large-record scanning.
- Standalone executable build entrypoint using PyInstaller.
- Thin npm launcher and provisional unscoped platform packages for Linux x64, Windows x64, macOS arm64, and macOS x64.
- npm package allowlist/security tests, local tarball assembly/audit helpers, SHA256 recording, structured Python/native/npm JSON parity tooling, and fail-closed manual npm registry-name preflight.
- Cross-platform core CI plus Alpha5 Python qualification and native/npm build/smoke/parity workflows.
- `docs/alpha5-field-validation.md` field-evidence traceability.

### Changed

- Python package version is `0.1.0a5`; npm mapping is `0.1.0-alpha.5`.
- `sessions` now treats compatible SQLite/sidebar state as enrichment instead of the only inventory authority.
- `doctor` now includes Alpha5 aggregate diagnostics, projection state, schema-compatibility aggregation, and more precise repository evidence classifications.
- The README is rewritten around actual Alpha5 capabilities, safety boundaries, target npm/native distribution, and unverified qualification state.

### Preserved from Alpha4

- Valid `mcp_tool_call_end` no longer causes a false `UNKNOWN_OPERATIONAL_SCHEMA`.
- Persisted paginated ordinal reuse remains bounded and fail-closed.
- Non-Git/unavailable Git evidence is not falsely asserted as repository divergence.
- Source rollouts stay read-only; recovery is a separate fork/artifact; unknown side effects are not automatically replayed.
- Existing Alpha4 PyPI Trusted Publishing workflow remains preserved and tightly scoped to the released Alpha4 artifact.

### Safety / evidence boundaries

- Alpha5 does not write projection/state SQLite and does not repair SQLite in place.
- Alpha5 does not modify source rollouts during diagnosis or salvage.
- Alpha5 does not invent missing tool results or infer that a tool failed to execute merely because persisted output is absent.
- The npm launcher does not download binaries at runtime, invoke a shell, bootstrap Python, or include telemetry.
- Ordinary pull-request CI does not publish Alpha5, create an Alpha5 tag, or merge the Alpha5 branch.
- npm package names and native/package functionality remain **UNVERIFIED** until the corresponding CI/preflight actually runs successfully.

### Known limitations

- Projection parity is deliberately narrow and can return unknown/not-applicable when schema, boundary, stability, or identity evidence is insufficient.
- Discovery remains bounded to supported rollout roots and bounded immediate Codex-home DB inspection.
- Alpha5 adds a second bounded sequential rollout scan for aggregate diagnostics; memory is bounded but I/O increases on very large files.
- Writer/lifecycle/opaque-format conclusions are structural diagnostics only and do not claim live process state or upstream root cause.
- Rescue still does not fix upstream Codex transport, Desktop/UI, compaction service, API, app-server locking, or process lifecycle defects.
- Standalone binaries and npm packages are not considered supported merely because build workflow YAML exists.

## v0.1.0-alpha.4

### Added

- Detect persisted rollout-local reuse of paginated ordinals.

### Fixed

- Accept valid current-format `event_msg` / `mcp_tool_call_end` records without a false `UNKNOWN_OPERATIONAL_SCHEMA`.
- Classify unavailable or non-Git repository state conservatively instead of asserting `REPO_STATE_DIVERGED` without Git evidence.
- Keep genuinely unknown future operational records fail-closed so they cannot silently produce `HEALTHY`; harmless metadata on known records remains compatible.

### Safety / Evidence Boundaries

- RC validation includes full unit/E2E suites, fixture harness, package build, and clean-install smoke checks.
- Preserve source rollouts, keep salvage forked, avoid replaying unknown side effects, and retain conservative `UNKNOWN` / `REVIEW_REQUIRED` boundaries.
- Alpha 4 is an experimental engineering release. Historical public-alpha evidence includes two Rescue users; no qualified-build external Rescue run, confirmed external salvage run, or confirmed external recovery success is included.

### Known Limitations

- Discovery can miss sessions absent from upstream index state; direct path diagnosis may still be useful.
- Rescue does not repair private SQLite or projection state, Codex Desktop behavior, compaction/media retention, or unknown side effects.
- Unsupported future operational records may require review rather than a healthy verdict.

## v0.1.0-alpha.3

Third experimental alpha release, with a narrow diagnostic fix derived from openai/codex#24369.

### Corrupted persisted tool-call names

- Detect persisted `function_call.name` values containing NUL or other ASCII control characters and classify them as `CORRUPTED_TOOL_CALL`.
- Preserve only bounded metadata for the damaged name; do not guess or automatically repair the intended tool name.
- Keep the original rollout untouched, do not replay the corrupted call, and keep verification fail-closed with `REVIEW_REQUIRED`.
- Retain real-world regression coverage for #14824 (orphaned/missing tool output) and #37719 (oversized persisted tool output).

### Limitations

- This does not repair Codex HTTP 400 responses, server-side replay, arbitrary malformed arguments, or broad corrupted-session/compaction recovery.

## v0.1.0-alpha.2

Second experimental alpha release.

### Safety and recovery hardening

- Fail closed on compaction state loss, ambiguous tool correlation, and unknown operational records.
- Verify coherent source snapshots before producing a rescue artifact.
- Strengthen Git-state fingerprinting against hostile environment overrides, external diff hooks, hidden index flags, and untracked-file edge cases.
- Bound transcript, event-tail, and file-hashing memory use; preserve a conservative review-required outcome when limits are exceeded.
- Expand and align secret redaction across recovery artifacts, discovery, and hooks.
- Use structured continuation arguments and explicit untrusted-evidence boundaries in recovery prompts.
- Improve artifact identifier validation, atomic-write retry behavior, and fixture portability around transient Git lock files.
- Exclude the default local rescue-artifact directory from source distributions.

### Validation

- Full Windows and Linux validation completed on the exact candidate.
- Strict real-macOS GitHub Actions evidence gate completed for the exact 105-file candidate archive.
- Wheel and sdist were built, inspected, and smoke-tested from fresh isolated environments.

## v0.1.0-alpha

Initial experimental alpha release.

### Included

- Recent Codex session discovery (`sessions` command)
- Interrupted and damaged session diagnosis (`doctor` command)
- Immutable evidence-backed recovery salvage (`salvage` command)
- Git repository state verification (`verify` command)
- Confidence-labeled recovery handoff (VERIFIED / RECONSTRUCTED / UNKNOWN)
- Sanitized synthetic regression corpus
- Crash-safe append-only journal
- Bounded recovery brief generation
- Secret redaction in handoff artifacts

### Known limitations

- Broad real compaction recovery not yet validated
- Interactive continuation depends on terminal/TTY environment
- Previous Codex version recovery coverage is limited
- Not every arbitrary corruption type is supported
