# Original User Request

## 2026-08-14T20:12:25Z

Execute a deep defensive software reliability validation campaign (Phases 0 through 62) for Codex Rescue (0.1.0a3) focusing on real Windows concurrent writers, TOCTOU races, Win32 handle sharing modes, streaming JSONL fuzzing, and scale stress.

Working directory: c:\Users\777\Documents\Codex\oss-tools\codex-rescue
Integrity mode: development

## Requirements

### R1. Concurrency, TOCTOU & Windows File Sharing Harnesses (Phases 0–5)
- Create a dedicated branch `test/day2-concurrency-and-stress` from `test/alpha3-adversarial-regressions`.
- Implement multi-process concurrent writer and reader test harnesses testing 1,000+ iterations of live appends, byte-by-byte streaming, codepoint splits, unclosed lines, truncations, file rotations, and rapid deletes.
- Implement Win32 handle sharing harnesses using standard library `ctypes.windll.kernel32` (`CreateFileW`, `LockFileEx`) validating behavior under `FILE_SHARE_READ`, `FILE_SHARE_WRITE`, `FILE_SHARE_DELETE`, and exclusive locks.
- Systematically inject mutations at synchronization points across `snapshot -> parse -> snapshot`, `stat -> open -> truncate`, and `source hash -> verify`.

### R2. Streaming Torture, Correlation State Machine & Fuzzing (Phases 6–23)
- Build a generative property fuzzer exercising JSONL boundaries, CRLF/LF mix, BOMs, NUL bytes, control characters, and record sizes up to 500MB.
- Build a pairwise correlation state machine and an independent differential reference oracle for tool calls, custom tools, search outputs, duplicate IDs, and family mismatches.
- Perform temporary mutation testing on core logic (`transcript.py`, `salvage.py`, `verify.py`, `doctor.py`) to verify test suite assertion strength.

### R3. Scale, Memory & Black-Box CLI Verification (Phases 24–30, 46–52)
- Generate session trees up to 10,000 rollouts and test discovery duration, limit slicing, tie-breaking determinism, and memory bounding.
- Execute a bounded continuous soak test measuring handle lifetimes, monotonic memory trends, and directory churn under live writes.
- Test full CLI subcommands and JSON envelope stability with invalid paths, extreme limits, and permission constraints.

### R4. Packaging, Supply Chain & NPM Distribution Architecture (Phases 31–36, 44–45)
- Verify local wheel and sdist builds in clean isolated environments.
- Conduct a defensive supply-chain review and privacy threat model audit.
- Prototype/research the npm distribution architecture using platform-specific optional dependencies (`@codex-rescue/win32-x64`, etc.) and a zero-network pure JS launcher shim.

### R5. Automatic Minimal Fixes & Final Deliverables (Phases 41–43, 59–62)
- If a confirmed bug or false positive/negative is reproduced, write a failing regression, apply the smallest localized fix in `src/codex_rescue/`, and verify the entire test suite and harness.
- Prune redundant tests into `tests/test_adversarial_audit.py` and isolate heavy stress tests in `tests/stress/`.
- Assemble the complete 28-section final deliverables report.

## Acceptance Criteria

### Concurrency & Invariant Verification
- [ ] 1,000+ concurrent writer race iterations complete with 100% source byte immutability verified before/after.
- [ ] Win32 handle sharing tests run via `ctypes` without unhandled crashes or false confidence.
- [ ] TOCTOU mutation injection reliably fails closed to `STATE_DIVERGED` or `REVIEW_REQUIRED`.
- [ ] Property fuzzer runs 5,000+ synthetic stream variations defending invariants P1–P10.
- [ ] Differential oracle verifies 100% agreement on standard correlation pairs.
- [ ] Scale testing validates up to 10,000 synthetic session files without memory exhaustion.
- [ ] Standard test discovery suite and 6-fixture harness pass cleanly.
- [ ] Final 28-section defensive reliability report is produced.

## 2026-08-14T20:33:19Z

User Requirement Update:
Ensure that ALL tests, harnesses, and validation scripts are fully compatible with and runnable in GitHub Codespaces (Linux/Ubuntu environment).

Key guidelines:
1. Platform conditioning: Windows-specific Win32 `ctypes.windll` tests must be cleanly isolated or conditionally skipped on non-Windows (`@unittest.skipUnless(sys.platform == 'win32', ...)`), while POSIX equivalents or portable cross-platform concurrency harnesses run seamlessly on Linux/Codespaces.
2. Standard test discovery (`python -m unittest discover -s tests -v`) and harness execution (`python -m codex_rescue.harness fixtures ...`) must execute with 100% pass rate in a standard GitHub Codespaces Linux container.
3. Ensure path separators, encoding (UTF-8), temp directories, and Git subprocess invocations are portable across Linux/Codespaces and Windows.

## 2026-08-15T07:11:12Z

# Objective: Resume Defensive Reliability Campaign (R2 -> R5) with Strict Cloud-Offloaded Execution (GitHub Codespaces)

## Current Workspace & Checkpoint Baseline
- **Repository**: `shleder/codex-rescue`
- **Branch**: `test/day2-concurrency-and-stress` (pushed to origin)
- **Completed Baseline**:
  - Phase 0: Baseline Survey & Analysis (`PROJECT.md`, `TEST_INFRA.md`).
  - Milestone R1: Concurrency, Win32 Handle Sharing & TOCTOU (`tests/test_concurrency_win32.py` - 25/25 passing).
  - Milestone E2E: Tiers 1 & 2 comprehensive feature and boundary suites (`tests/e2e/tier1_features/` and `tests/e2e/tier2_boundaries/` - 20 modules).
  - Codespaces Infra: `.devcontainer/devcontainer.json`, `scripts/codespaces_test.sh`.

---

## CRITICAL SAFETY & EXECUTION INVARIANTS
1. **P1–P10 Safety Invariants**:
   - P1: Source Immutability (0% modification to source sessions).
   - P2: Forked Salvage (never overwrite source session file).
   - P3: No Auto-Replay of unverified side-effects.
   - P4: Corrupted tool name sanitization to sentinels.
   - P5: Explicit uncertainty (VERIFIED vs RECONSTRUCTED vs UNKNOWN).
   - P6: Concrete evidence required for VERIFIED.
   - P7: Fail closed.
   - P8: Zero credential / secret leakage.
   - P9: Zero Codex SQLite/WAL mutation.
   - P10: Zero runtime cloud dependencies / offline isolation.
2. **ZERO LAPTOP HEAT / CPU OVERLOAD CONSTRAINT**:
   - **STRICT REQUIREMENT**: Do NOT execute heavy CPU-saturating loops (e.g. 5,000 heavy fuzzing cycles, 10,000 session generation, long continuous soak loops) directly on the local Windows host.
   - For local verification, execute only lightweight, single-threaded, bounded unit tests (`python -m unittest`).
   - Package all heavy fuzzers, scale benchmarks, soak tests, and mutation suites into standalone, runnable scripts (`scripts/run_fuzzing_codespaces.py`, `scripts/run_scale_soak_codespaces.py`, etc.) and push them to the branch for execution on GitHub Codespaces.

---

## REMAINING CAMPAIGN MILESTONES TO EXECUTE

### 1. Milestone R2: Streaming Torture, Correlation State Machine & Fuzzing (Phases 6–23)
- **Fuzzing Harness** (`tests/test_streaming_fuzzing.py` & `scripts/fuzz_codespaces.py`):
  - Generative property fuzzer exercising JSONL boundary mutations, CRLF/LF mix, UTF-8 BOM, NUL bytes, ANSI escapes, BiDi overrides, control chars.
  - Extreme record handling (up to 500MB payload defense, 8MB line boundaries, memory capping).
- **Tool Correlation Oracle** (`tests/test_correlation_oracle.py`):
  - Independent differential reference oracle for tool calls, custom tools, search outputs, duplicate IDs, and family mismatches.
- **AST Mutation Verification** (`tests/test_mutation_defense.py`):
  - Invariant mutation testing on core logic (`transcript.py`, `salvage.py`, `verify.py`, `doctor.py`) asserting >95% mutant kill rate.

### 2. Milestone R3: Scale, Memory & Black-Box CLI Verification (Phases 24–30, 46–52)
- **Scale Benchmarks & Soak Test** (`tests/test_scale_soak.py` & `scripts/soak_codespaces.py`):
  - Scale session tree generator (up to 10,000 synthetic sessions) testing discovery duration, limit slicing, tie-breaking determinism.
  - Soak test measuring handle lifetimes (\Delta \text{Handles} = 0) and monotonic memory bounds.
- **Black-Box CLI Envelope Suite** (`tests/test_cli_blackbox.py`):
  - Subcommands (`doctor`, `salvage`, `verify`, `sessions`, `inspect`), JSON envelope stability, exit codes (0, 1, 2, 3), and permission constraints.

### 3. Milestone R4: Packaging, Supply Chain & NPM Distribution (Phases 31–36, 44–45)
- **Packaging Verification** (`tests/test_packaging_supplychain.py`):
  - Isolated clean-room build verification for standard `sdist` (.tar.gz) and `wheel` (.whl).
  - Supply chain review, STRIDE privacy threat model audit, zero-runtime-dependency enforcement.
- **NPM Distribution Architecture Prototype** (`npm-distribution/`):
  - Prototype platform-specific optional dependencies structure (`@codex-rescue/win32-x64`, `@codex-rescue/linux-x64`, etc.).
  - Pure JS launcher shim (`bin/codex-rescue.js`) defending Invariant P10.

### 4. Milestone R5: Consolidation, Fixes & Final Deliverables (Phases 41–43, 59–62)
- If any confirmed defect or false positive/negative is discovered: apply minimal localized fix in `src/codex_rescue/` with a failing regression test first.
- Consolidate & prune tests: ensure `tests/test_adversarial_audit.py` has high-value invariant tests, while isolating heavy stress scripts in `tests/stress/` or `scripts/`.
- Assemble the complete **28-section Defensive Reliability Report** (`RELIABILITY_REPORT_28_SECTION.md`).
- Commit all deliverables to `test/day2-concurrency-and-stress` and push to GitHub origin.

---

## Multi-Agent Team Structure
1. **Lead Orchestrator**: Manages milestones, gates, and git pushes.
2. **R2 Specialist (Fuzzing & Correlation)**: Implements streaming fuzzer, correlation oracle, mutation tests.
3. **R3 Specialist (Scale & CLI)**: Implements scale harness, soak tests, and CLI blackbox envelopes.
4. **R4 Specialist (Packaging & NPM)**: Implements packaging verification, supply chain audit, and NPM shim.
5. **Auditor & Challenger**: Adversarial invariant checker, verifies P1–P10 adherence and Linux/Codespaces portability.


