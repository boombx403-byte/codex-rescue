<p align="center">
  <a href="https://github.com/shleder/codex-rescue/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/shleder/codex-rescue/ci.yml?branch=main&style=flat-square&label=CI&logo=github" alt="CI Status"></a>
  <img src="https://img.shields.io/badge/version-v0.1.0--alpha.3-3fb950?style=flat-square" alt="Version">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-1f6feb?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="#privacy"><img src="https://img.shields.io/badge/privacy-100%25%20local--first-238636?style=flat-square" alt="Privacy"></a>
</p>

---

## Overview

When **OpenAI Codex CLI** can't resume safely, **Rescue** tells you what actually happened and gets you back to work.

Codex Rescue is a local-first fsck and crash-recovery tool for OpenAI Codex sessions. It diagnoses interrupted or damaged sessions, verifies repository working tree state, and reconstructs a bounded evidence-backed continuation **without modifying the original Codex rollout**.

> [!WARNING]
> **Codex Rescue is experimental alpha software.**
> It is an evidence-gathering release designed to collect real failure cases.
> See [Alpha Limitations](#alpha-limitations) below.

---

## Core Commands

Rescue provides four narrow diagnostic and recovery entry points. The original
Codex rollout is read-only; `salvage` writes only a new handoff under the
rescue root.

| Command | Usage | Description |
|---|---|---|
| **`sessions`** | `codex-rescue sessions` | Discover and list recent local Codex rollout sessions |
| **`doctor`** | `codex-rescue doctor --latest` | Inspect and diagnose a damaged session (**read-only**) |
| **`salvage`** | `codex-rescue salvage --latest --fork` | Create an immutable, content-addressed recovery handoff |
| **`verify`** | `codex-rescue verify <rescue-id>` | Detect repository divergence before executing continuation |

When a persisted `function_call.name` contains NUL or another ASCII control
character, `doctor` reports `CORRUPTED_TOOL_CALL` and keeps only bounded
metadata (call id, family, length, codepoints, and a hash) for manual review.
The original rollout remains untouched. Rescue does not infer or automatically
repair the intended tool name, repair Codex HTTP 400 responses, repair
arbitrary malformed arguments, or replay the corrupted call; `verify` remains
fail-closed with `REVIEW_REQUIRED`.

---

## Confidence Model

Rescue reconstructs facts with explicit, uncompromised confidence levels. Model prose alone is **never** accepted as source of truth.

| Level | Badge | Meaning & Source of Truth |
|---|---|---|
| **VERIFIED** | `VERIFIED` | Directly proven by durable evidence: Git HEAD SHA, working tree diff, tool execution exit code, or durable output record |
| **RECONSTRUCTED** | `RECONSTRUCTED` | Strongly inferred from available evidence with no unresolved contradictions |
| **UNKNOWN** | `UNKNOWN` | Cannot be proven safely. **UNKNOWN is deliberate.** Rescue refuses to guess when execution state is uncertain |

> [!NOTE]
> **Safety Invariants:**
> 1. Source rollouts are **immutable** (`doctor`, `salvage`, and `verify` never write to the original `.jsonl` file).
> 2. **No automatic replay** — an action whose execution status is `UNKNOWN` is never automatically re-executed.

---

## Quick Start

### 1. Installation

Install directly from PyPI:

```bash
# Recommended global installation via pipx
pipx install codex-rescue

# Or via standard pip
pip install codex-rescue
```

### 2. First 5 minutes

Use this sequence with a local Codex installation. It never needs a raw
rollout upload:

```bash
# 1. Confirm the installation
codex-rescue --version

# 2. Discover recent Codex sessions
codex-rescue sessions

# 3. Diagnose the latest session
codex-rescue doctor --latest

# 4. Generate an immutable recovery handoff (the --fork is required)
codex-rescue salvage --latest --fork

# 5. Verify repository state before continuing
codex-rescue verify <rescue-id>
```

`sessions` reads the default Codex home. If it returns no sessions, that is
normal on a new machine or before Codex has created a rollout; use
`--codex-home PATH` when Codex runs with a non-default home. `doctor` and
`salvage` exit with an explanatory “no session discovered” error when there is
nothing to inspect. `salvage --fork` is deliberately required so recovery
artifacts are written separately under
`.codex-rescue/rescues/<rescue-id>` and the original rollout is preserved.

`verify` returns exit code 3 for `REVIEW_REQUIRED`. That is a conservative
result, not a command to replay an uncertain action. Inspect the report and
do not automatically repeat unknown side effects.

### Troubleshooting

- **No sessions found:** run `codex-rescue sessions --json`, check the Codex
  home path, and confirm that Codex has written at least one rollout. Do not
  copy or upload an unsanitized session just to make discovery succeed.
- **Permission or unsupported-environment errors:** record the OS, Python,
  Codex CLI, and Git versions plus the failing command and exit code. Check
  that the account running Rescue can read the Codex home and repository; do
  not modify the original rollout to work around a permission error.
- **`UNKNOWN` or `REVIEW_REQUIRED`:** these statuses are fail-closed. They
  mean the available evidence cannot prove that continuing is safe. Preserve
  the original files and report the sanitized diagnostics instead of replaying
  the action.

When reporting a failure, use the [Recovery Report template](https://github.com/shleder/codex-rescue/issues/new?template=recovery-report.yml).
Include sanitized JSON, versions, the exact command and exit code, and whether
the original rollout stayed unchanged. Never attach raw `.jsonl`/SQLite files,
credentials, private prompts, or unredacted absolute home paths.

### 3. Sample output

```text
$ codex-rescue doctor --latest

Doctor: UNFINISHED_TOOL_CALL
Findings: UNFINISHED_TOOL_CALL
Repository: /path/to/repo (HEAD a6cfe48)

$ codex-rescue salvage --latest --fork

Salvage: 8f8f4e822c9ce353ed584c5f
Original session untouched: yes
Rescue directory: .codex-rescue/rescues/8f8f4e822c9ce353ed584c5f

$ codex-rescue verify 8f8f4e822c9ce353ed584c5f

Verify: REVIEW_REQUIRED
Review: unfinished action requires inspection before replay
Review: handoff contains load-bearing unknowns
```

---

## Proven Compatibility & Evidence

| Version / Scope | Status | Proven Real-World Evidence |
|---|---|---|
| **Codex CLI 0.147.0** | **Validated** | Genuine interrupted session diagnosed (`UNFINISHED_TOOL_CALL`), source rollout preserved, repo state verified |
| **Codex CLI 0.146.1** | **Smoke-tested** | Isolated authentication & basic rollout parser validation |
| **Codex 0.145.0-alpha.18** | **Observed** | Legacy envelope format compatibility observed |
| **Synthetic Fixtures** | **6/6 PASS** | `kill_apply_patch`, `kill_shell_before_result`, `lost_tail_after_compaction`, `malformed_jsonl`, `oversized_payload`, `issue_14824_orphaned_tool_output` |
| **Public real-case regressions** | **Validated** | #14824 orphaned/missing tool output, #37719 oversized persisted tool output, #24369 corrupted persisted tool-call name |

---

## Alpha Limitations

> [!IMPORTANT]
> The following limitations are documented honestly. Do not claim recovery guarantees that have not been validated.

- **Compaction recovery** — broad real compaction-related recovery is not yet validated; only synthetic fixtures exist.
- **Interactive continuation** — automatic fresh continuation depends on terminal/TTY environment (Windows ConPTY limitations noted).
- **Previous versions** — validation is focused on Codex CLI 0.147.0; earlier versions are smoke-tested or observed.
- **Side-effect replay** — Rescue does not automatically replay unknown side effects; it reports them as `REVIEW_REQUIRED`.

---

## Privacy & Security

- **100% Local-First** — zero telemetry, zero analytics, zero network uploads, zero cloud dependencies.
- **No private DB mutation** — Rescue never modifies `state_*.sqlite` or internal Codex databases.
- **Secret Redaction** — built-in secret redaction automatically filters common API key patterns (`sk-*`, `ghp_*`, `AKIA*`, Bearer tokens).
- **Sanitization Notice** — Codex rollouts can contain secrets; sanitize all session files before attaching to public issues.

---

## Development & Verification

```bash
# Clone the repository
git clone https://github.com/shleder/codex-rescue.git
cd codex-rescue

# Install in editable mode
pip install -e .

# Run full unit test suite (58 passed, 1 expected skip)
python -m unittest discover -s tests -v

# Run synthetic fixture harness (5/5 PASS)
python -m codex_rescue.harness fixtures --output .validation-output/test

# Run deterministic alpha demo
python scripts/demo_alpha.py
```

---

## Submit a Recovery Report

The primary goal of this public alpha is collecting real broken Codex sessions to expand our sanitized regression corpus.

[**Open a Recovery Report →**](https://github.com/shleder/codex-rescue/issues/new?template=recovery-report.yml)

> [!CAUTION]
> **Do NOT upload raw rollout files containing secrets or credentials.** Always sanitize session data before attaching.

---

## License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 shleder.
