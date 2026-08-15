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

