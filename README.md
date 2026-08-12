# Codex Rescue

When Codex can't resume safely, Rescue tells you what actually happened and gets you back to work.

Codex Rescue is a local-first recovery tool for [OpenAI Codex](https://github.com/openai/codex) sessions.
It diagnoses interrupted or damaged sessions, verifies the repository state,
and creates an evidence-backed continuation — without modifying the original rollout.

> [!WARNING]
> **Codex Rescue is experimental alpha software.**
> It is an evidence-gathering release intended to collect real recovery cases.
> See [Alpha limitations](#alpha-limitations) below.

## What it does

| Command | Purpose |
|---------|---------|
| `sessions` | Find recent Codex sessions |
| `doctor` | Diagnose a suspicious or damaged session (read-only) |
| `salvage` | Create an immutable evidence-backed recovery handoff |
| `verify` | Detect repository divergence before continuation |

**Key property:** the original Codex rollout is never modified.

## Confidence model

Every recovered fact is labeled with one of three confidence levels:

| Level | Meaning |
|-------|---------|
| **VERIFIED** | Directly supported by durable evidence (Git HEAD, working tree, diff hash, tool result) |
| **RECONSTRUCTED** | Strongly inferred from available evidence, but not directly proven |
| **UNKNOWN** | Cannot be proven safely |

**UNKNOWN is deliberate.** Rescue refuses to guess when execution state cannot be proven.
An unfinished action whose result is unknown is never automatically replayed.

## Quick start

```bash
# Install globally from GitHub
pipx install git+https://github.com/shleder/codex-rescue.git@v0.1.0-alpha

# Or via pip
pip install git+https://github.com/shleder/codex-rescue.git@v0.1.0-alpha

# Find recent sessions
codex-rescue sessions

# Diagnose the latest session
codex-rescue doctor --latest

# Create an immutable recovery handoff
codex-rescue salvage --latest --fork

# Verify repository state before continuing
codex-rescue verify <rescue-id>
```

## Example output

```
$ codex-rescue doctor --latest

Doctor: UNFINISHED_TOOL_CALL
Findings: UNFINISHED_TOOL_CALL
Repository: /path/to/repo (HEAD abc1234)

$ codex-rescue salvage --latest --fork

Salvage: a1b2c3d4e5f6g7h8i9j0k1l2
Original session untouched: yes
Rescue directory: .codex-rescue/rescues/a1b2c3d4e5f6g7h8i9j0k1l2

$ codex-rescue verify a1b2c3d4e5f6g7h8i9j0k1l2

Verify: REVIEW_REQUIRED
Review: unfinished tool call requires manual inspection
```

## Alpha limitations

> [!IMPORTANT]
> This is an experimental alpha release. The following limitations are known and documented honestly.

- **Compaction recovery** — broad real compaction-related recovery is not yet validated; only synthetic fixtures exist
- **Interactive continuation** — automatic fresh continuation depends on terminal/TTY environment; ConPTY limitations on Windows are known
- **Previous versions** — recovery validation is limited to Codex CLI 0.147.0; earlier versions have only been smoke-tested or observed
- **Corruption coverage** — not every arbitrary malformed session type is supported
- **Side-effect detection** — Rescue does not automatically replay unknown side effects; it reports them for manual review
- **Platform validation** — no Linux or macOS real-failure validation has been performed yet

## Privacy

- **Local-only** — no telemetry, no analytics, no cloud upload, no account required
- Codex rollout files can contain **secrets, API keys, and private code**
- **Sanitize all data before sharing** in issue reports or attachments
- Built-in secret redaction is bounded and not a guaranteed complete DLP system
- Current redaction covers common patterns (API keys, bearer tokens, OpenAI keys) but is not exhaustive

## Codex version support

| Version | Status |
|---------|--------|
| Codex CLI 0.147.0 | **Validated** — real interrupted session recovery demonstrated |
| Codex CLI 0.146.1 | Smoke-tested — isolated authentication and basic operation verified |
| Codex 0.145.0-alpha.18 | Observed sanitized format compatibility |

Do not assume compatibility with all Codex versions.

## Development

```bash
# Install for development
pip install -e .

# Run tests
python -m unittest discover -s tests -v

# Run fixture harness
python -m codex_rescue.harness fixtures --output .validation-output/test

# Run alpha demo
python scripts/demo_alpha.py
```

## Submit a recovery report

The main goal of this alpha is **collecting real broken Codex sessions**.

If you encounter a Codex session that can't resume safely, please [open a Recovery Report](https://github.com/shleder/codex-rescue/issues/new?template=recovery-report.yml).

⚠️ **Do NOT upload raw rollout files containing secrets.** Sanitize all session data before attaching.

## License

[MIT](LICENSE)
