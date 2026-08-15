# Project: Codex Rescue (0.1.0a3) Defensive Reliability Validation Campaign

## Architecture
Codex Rescue is a local-first, zero-runtime-dependency diagnostic, recovery, and verification tool for persisted OpenAI Codex sessions (`rollout-*.jsonl` and session directories).

### Core Modules & Flow
- **Discovery** (`discovery.py`): Scans `~/.codex/sessions` (or custom paths), discovers session rollout trees, performs bounded head/tail inspection, extracts session metadata.
- **Transcript Parser** (`transcript.py`): Parses JSONL records, extracts message history, tracks tool calls and outputs via pairwise correlation state machine, replaces corrupted tool names with sentinels (`<corrupted-tool-name>`), limits memory and line size.
- **Doctor / Diagnostics** (`doctor.py`): Evaluates transcript health, identifies failure classes (`UNFINISHED_TOOL_CALL`, `COMPACTION_STATE_LOSS`, `MALFORMED_RECORD`, `OVERSIZED_PAYLOAD`, `MISSING_SESSION_HEADER`), enforces strict severity ordering.
- **Salvage / Recovery** (`salvage.py`, `artifacts.py`): Produces immutable forked recovery artifacts (`.jsonl`, markdown transcripts, journal summaries) with 4-point SHA-256 / `mtime_ns` snapshot verification without ever modifying source session files.
- **Verification** (`verify.py`, `gitstate.py`): Validates rescue handoffs against live Git working tree state, tree hashes, untracked files, index trust flags (`assume-unchanged`, `skip-worktree`), and classified tool evidence (`VERIFIED`, `RECONSTRUCTED`, `UNKNOWN`).
- **CLI & Harness** (`cli.py`, `harness.py`, `fixtures.py`): Provides JSON/text CLI envelopes, exit codes (0=HEALTHY/VERIFIED, 1=UNHEALTHY, 2=CLI/OS error, 3=REVIEW_REQUIRED), and synthetic fixture regression harness.

### Non-Negotiable Safety Invariants (P1–P10)
- **P1: Source Immutability**: Source rollout bytes and SHA-256 hashes must remain 100% identical before, during, and after any operation.
- **P2: Forked Salvage**: Recovery artifacts must always be written to distinct target files/directories, never overwriting source sessions.
- **P3: No Auto-Replay**: Unexecuted or partially executed side effects must never be replayed automatically.
- **P4: Corrupted Tool Sanitization**: Corrupted or control-character-laden tool names must be sanitized to sentinels without guessing semantics.
- **P5: Explicit Uncertainty**: Preserves strict boundaries between `VERIFIED`, `RECONSTRUCTED`, and `UNKNOWN`.
- **P6: Concrete Evidence**: No uncertainty may be promoted to `VERIFIED` without cryptographic or repository-level proof.
- **P7: Fail Closed**: When invariants or recovery correctness cannot be established, fail closed to `STATE_DIVERGED` or `REVIEW_REQUIRED`.
- **P8: Privacy & Secret Redaction**: Credentials, tokens, keys, and raw private payloads must not leak into logs or artifacts.
- **P9: Database Immutability**: No mutation of Codex SQLite or WAL state.
- **P10: Offline Isolation**: Zero runtime cloud dependencies, telemetry, or hidden network egress.

---

## Feature Inventory
Every phase across the 63-phase campaign (Phases 0–62) is assigned to a milestone:

| # | Phase | Feature / Requirement | Milestone | Source |
|---|-------|------------------------|-----------|--------|
| 1 | 0 | Test harness & baseline survey, fixture validation (6/6 passing) | M0 (Complete) | Survey |
| 2 | 1 | Dedicated branch setup (`test/day2-concurrency-and-stress`) & baseline validation | M1 | R1 |
| 3 | 2 | Multi-process concurrent writer harness (1,000+ iterations live appends, rotations, truncations) | M1 | R1 |
| 4 | 3 | Byte-by-byte streaming, codepoint splits, unclosed lines, and rapid delete races | M1 | R1 |
| 5 | 4 | Win32 handle sharing harness (`CreateFileW` flags: `FILE_SHARE_READ/WRITE/DELETE`) via `ctypes` | M1 | R1 |
| 6 | 5 | Win32 byte-range lock harness (`LockFileEx`, exclusive vs shared) & error handling (32, 33) | M1 | R1 |
| 7 | 6 | TOCTOU mutation injection across 5 critical synchronization points (`snapshot->parse->verify`) | M1 | R1 |
| 8 | 7 | Generative streaming JSONL property fuzzer (5,000+ synthetic stream variations) | M2 | R2 |
| 9 | 8 | Boundary torture: mixed CRLF/LF, UTF-8 BOM, NUL bytes, ANSI escape sequences, BiDi overrides | M2 | R2 |
| 10 | 9 | Extreme record payload handling (up to 500MB streaming, 8MB line boundaries, memory capping) | M2 | R2 |
| 11 | 10 | Pairwise correlation state machine (tool calls, tool outputs, custom tools, search outputs) | M2 | R2 |
| 12 | 11 | Independent differential reference oracle for correlation validation | M2 | R2 |
| 13 | 12 | Adversarial correlation torture: duplicate IDs, orphaned outputs, cross-family mismatches | M2 | R2 |
| 14 | 13 | AST mutation testing on core logic (`transcript.py`, `salvage.py`, `verify.py`, `doctor.py`) | M2 | R2 |
| 15 | 14 | Assertion strength verification & mutant kill rate measurement (>95% target) | M2 | R2 |
| 16 | 15 | Scale session generator (up to 10,000 synthetic rollout session trees) | M3 | R3 |
| 17 | 16 | Scale discovery benchmarks: duration, limit slicing, tie-breaking determinism | M3 | R3 |
| 18 | 17 | Continuous soak test (10,000 cycles) measuring handle lifetimes ($\Delta \text{Handles} = 0$) & memory | M3 | R3 |
| 19 | 18 | Memory monotonicity & leak detection under continuous live writes and directory churn | M3 | R3 |
| 20 | 19 | Black-box CLI verification: subcommands (`doctor`, `salvage`, `verify`, `sessions`, `inspect`) | M3 | R3 |
| 21 | 20 | CLI JSON envelope schema stability, exit code contracts (0, 1, 2, 3), and permission errors | M3 | R3 |
| 22 | 21 | Isolated clean-room build verification for standard `sdist` (.tar.gz) and `wheel` (.whl) | M4 | R4 |
| 23 | 22 | Zero runtime dependency audit & standard library enforcement (`dependencies = []`) | M4 | R4 |
| 24 | 23 | Defensive supply chain review & STRIDE privacy threat model audit | M4 | R4 |
| 25 | 24 | NPM distribution architecture prototype (`@codex-rescue/win32-x64`, `@codex-rescue/darwin-arm64`, etc.) | M4 | R4 |
| 26 | 25 | Zero-network pure JS launcher shim (`bin/codex-rescue.js`) defending Invariant P10 | M4 | R4 |
| 27 | 26 | Automatic minimal bug-fix protocol verification & reproduction harness | M5 | R5 |
| 28 | 27 | Test suite consolidation: prune into `tests/test_adversarial_audit.py` & isolate `tests/stress/` | M5 | R5 |
| 29 | 28 | Assembly and verification of the master 28-section Defensive Software Reliability Report | M5 | R5 |
| 30 | 29-62 | Multi-tier E2E verification suites (Tiers 1–5), regression hardening, and final acceptance | E2E Track | E2E |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M0 | Survey & Architecture Mapping | Codebase survey, test baseline, requirement decomposition | None | DONE |
| E2E | E2E Testing Suite | Multi-tier opaque-box test runner & harness (Tiers 1–4, publishing `TEST_READY.md`) | M0 | IN_PROGRESS |
| M1 | Concurrency, TOCTOU & Win32 Sharing | Multi-process writer races, Win32 handle flags (`ctypes`), TOCTOU mutations (Phases 0–5) | M0 | IN_PROGRESS |
| M2 | Streaming Torture & Fuzzing | 5k property fuzzer, correlation state machine, differential oracle, mutation testing (Phases 6–23) | M1 | PLANNED |
| M3 | Scale, Memory & CLI Verification | 10k session trees, continuous soak test, handle leak audit, CLI black-box envelopes (Phases 24–30, 46–52) | M1 | PLANNED |
| M4 | Packaging, Supply Chain & NPM | Sdist/wheel builds, threat model, npm optionalDependencies & zero-network JS shim (Phases 31–36, 44–45) | M0 | PLANNED |
| M5 | Minimal Fixes & 28-Section Report | Bug fix protocol, test consolidation (`tests/stress/`), 28-section final deliverables (Phases 41–43, 59–62) | M2, M3, M4 | PLANNED |
| M_FINAL | Final Acceptance & Phase 2 Hardening | 100% E2E test pass + Tier 5 Adversarial Coverage Hardening | M5, E2E | PLANNED |

---

## Interface Contracts

### Concurrency & Win32 Harness ↔ Core Modules
- `Win32FileHandle`: Wrapped `ctypes.windll.kernel32.CreateFileW` handle with context manager closing via `CloseHandle`.
- `TOCTOUMutator`: Intercepts file I/O hooks during `file_snapshot()`, `salvage_session()`, and `verify_rescue()` to inject appends, truncations, or deletions, verifying that operations raise `RuntimeError` or produce `STATE_DIVERGED` / `REVIEW_REQUIRED`.

### Streaming & Fuzzing Harness ↔ Transcript Parser
- `StreamFuzzer`: Generates syntactically varied JSONL streams with extreme record sizes, NUL bytes, ANSI sequences, mixed line endings, verifying that `parse_transcript()` never crashes with unhandled exceptions and properly sanitizes sentinels.
- `CorrelationOracle`: Reference state machine computing expected tool call/output pairings to compare 1:1 against `transcript.py` pairings.

### Scale Harness ↔ Discovery & CLI
- `ScaleTreeGenerator`: Emits deterministic directory structures of N sessions with synthetic rollouts.
- `SoakTestRunner`: Iterates 10,000 inspection/discovery cycles measuring process handle count via Win32 `GetProcessHandleCount` and memory via `gc` / OS counters.

---

## Code Layout
```
src/codex_rescue/
├── __init__.py
├── artifacts.py
├── cli.py
├── config.py
├── discovery.py
├── doctor.py
├── fixtures.py
├── gitstate.py
├── harness.py
├── hooks.py
├── journal.py
├── reconstruct.py
├── salvage.py
├── transcript.py
└── verify.py

tests/
├── __init__.py
├── fixtures/                         # 6 baseline fixtures
├── test_adversarial_audit.py         # Consolidated regression suite
├── test_concurrency_win32.py         # M1: Concurrency & Win32 handle sharing tests
├── test_streaming_fuzz.py            # M2: Streaming torture & property fuzzing
├── test_correlation_oracle.py        # M2: Differential reference oracle
├── test_cli_blackbox.py              # M3: Black-box CLI & JSON envelope tests
├── test_packaging_npm.py             # M4: Sdist/wheel & npm shim verification
├── stress/                           # Isolated heavy stress & scale tests
│   ├── test_scale_discovery.py       # 10k session benchmarks
│   ├── test_handle_soak.py           # 10,000-cycle handle soak test
│   └── test_payload_500mb.py         # 500MB payload streaming stress
└── e2e/                              # E2E Testing Track (Tiers 1-4)
    ├── harness_e2e.py                # Multi-tier E2E test runner
    ├── tier1_features/
    ├── tier2_boundaries/
    ├── tier3_interactions/
    └── tier4_scenarios/

npm/
├── package.json
├── bin/
│   └── codex-rescue.js               # Zero-network launcher shim
└── platforms/                        # Platform packages metadata
```
