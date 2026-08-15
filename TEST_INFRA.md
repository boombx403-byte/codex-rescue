# E2E Test Infra: Codex Rescue (0.1.0a3)

## Test Philosophy
- Opaque-box, requirement-driven. No dependency on internal module private methods.
- Testing methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Testing + Real-World Workload Scenarios.
- Strict defense of Non-Negotiable Invariants P1–P10.

## Feature Inventory
| # | Feature Area | Requirement Source | Tier 1 (Features) | Tier 2 (Boundaries) | Tier 3 (Pairwise) | Tier 4 (Workloads) |
|---|--------------|-------------------|:-----------------:|:-------------------:|:-----------------:|:------------------:|
| 1 | Session Discovery & Head/Tail Scan | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 2 | Transcript Parsing & Stream Handling | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 3 | Tool Correlation & Sentinel Sanitization | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 4 | Doctor Failure Classification Hierarchy | ORIGINAL_REQUEST §R1-R3 | 5 | 5 | ✓ | ✓ |
| 5 | Forked Salvage & Source Immutability (P1, P2) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 6 | Verification & Git State Tracking (P5, P6, P7) | ORIGINAL_REQUEST §R1, R3 | 5 | 5 | ✓ | ✓ |
| 7 | Win32 Handle Sharing & Locking Mechanics | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 8 | Multi-Process Writer Races & TOCTOU Defense | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 9 | Black-Box CLI Envelopes & Exit Codes | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 10 | Packaging, Sdist/Wheel & NPM Launcher Shim | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- **E2E Test Runner**: `tests/e2e/harness_e2e.py` executing standalone or through standard `unittest`.
- **Pass/Fail Semantics**: Exit code 0 on 100% pass across all tiers; nonzero on any assertion or invariant failure.
- **Source Byte Immutability**: Cryptographic SHA-256 validation performed before and after every test execution.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Active Developer IDE Crash during multi-file edit with unclosed tool call | Discovery, Transcript, Doctor, Salvage, Verify | High |
| 2 | Shell session killed by OS OOM during large payload output (10MB+) | Transcript, Doctor, Redaction, Immutability | High |
| 3 | Git repository with dirty working tree, untracked files, and index trust flags | GitState, Verify, Exit Codes, Fail-Closed | High |
| 4 | Corrupted rollout with mixed UTF-8 BOM, NUL bytes, and corrupted tool names | Fuzzer, Sanitization, Sentinels, Diagnostics | High |
| 5 | High-frequency session rotation and concurrent writer race on Windows | Win32 Sharing, TOCTOU, LockFileEx, Concurrency | Very High |
| 6 | Clean sdist/wheel build extraction and NPM zero-network launcher invocation | Packaging, CLI Envelopes, Node shim, Offline P10 | Medium |

## Coverage Thresholds
- Tier 1: ≥50 test cases (≥5 per feature area across 10 areas)
- Tier 2: ≥50 boundary & corner test cases (≥5 per feature area)
- Tier 3: ≥10 pairwise interaction test cases covering major cross-feature combinations
- Tier 4: ≥6 realistic application workload scenarios
- **Total Minimum Threshold: ≥116 test cases**
