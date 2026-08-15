# AGENTS.md

## Project

Codex Rescue is a local-first diagnostic and recovery tool for persisted OpenAI Codex sessions.

The project is safety-sensitive. Correct conservative behavior is more important than adding features or making the code look cleaner.

## Read First

Before changing code, read:

1. `README.md`
2. `CONTRIBUTING.md`
3. the relevant implementation under `src/codex_rescue/`
4. the relevant tests under `tests/`
5. any issue-specific regression tests or sanitized fixtures related to the task

Do not infer behavior only from documentation. Verify the implementation and tests.

## Core Product Boundary

Codex Rescue may:

- discover persisted Codex rollouts;
- inspect rollout structure;
- diagnose recognized persistence/session failures;
- create forked recovery artifacts;
- verify repository state and recovery evidence;
- report uncertainty explicitly.

Codex Rescue must not pretend to repair upstream Codex Desktop, server, transport, WebSocket, HTTP 5xx, sidebar/index, or remote-metadata failures unless the implementation actually proves such behavior.

`HEALTHY` means only that no recognized structural/persistence issue was detected in the analyzed rollout.

`HEALTHY` does not prove:

- Desktop/sidebar correctness;
- Desktop/index correctness;
- remote metadata correctness;
- semantic completeness;
- absence of every upstream Codex failure mode.

## Non-Negotiable Safety Invariants

1. Never modify the original rollout.
2. Never overwrite the source session during salvage.
3. Never automatically replay an unknown side effect.
4. Never guess corrupted tool identity or semantics.
5. Preserve the distinction between `VERIFIED`, `RECONSTRUCTED`, and `UNKNOWN`.
6. Never promote uncertainty to `VERIFIED` without concrete evidence.
7. Fail closed when recovery correctness cannot be established.
8. Recovery artifacts must not leak raw secrets or unsafe corrupted metadata unnecessarily.
9. Do not mutate Codex SQLite/WAL state.
10. Do not introduce telemetry, hidden uploads, or runtime cloud dependencies.

Any change that weakens one of these invariants requires explicit user approval and strong evidence.

## Evidence-Driven Change Policy

Do not create production changes merely because an improvement seems plausible.

A runtime behavior change should normally require at least one of:

- confirmed false negative;
- confirmed false positive;
- demonstrated safety defect;
- demonstrated privacy leak;
- reproducible discovery failure;
- blocking diagnostic/recovery bug;
- new failure class supported by real public evidence or a faithful sanitized reproduction.

If the evidence is insufficient, prefer:

- a test;
- a minimized reproduction;
- an investigation note;
- or no code change.

Zero production-code changes is a valid successful outcome.

## Bug-Fix Protocol

For every claimed runtime bug:

1. Reproduce it.
2. Minimize the reproduction.
3. Record current behavior.
4. Explain why the behavior is wrong or unsafe.
5. Add a regression test that fails before the fix.
6. Apply the smallest fix.
7. Confirm the regression passes.
8. Run the broader affected tests.
9. Run the full suite.
10. Re-check the safety invariants.

Before finalizing, try to disprove your own finding.

Do not modify production code to satisfy a synthetic test whose expected semantics are not justified.

## Testing

The repository currently uses the standard-library `unittest` test suite.

Primary full-suite command:

```bash
python -m unittest discover -s tests -v
```

Fixture validation:

```bash
python -m codex_rescue.harness fixtures --output .validation-output/test
```

Use existing test conventions unless the user explicitly requests a testing-stack migration.

Do not migrate the project to pytest merely because an installed skill prefers pytest.

Do not add Hypothesis, Atheris, coverage packages, profilers, linters, or other dependencies to project metadata without explicit justification.

For temporary audit tooling, prefer an isolated environment or non-committed local tooling.

Every test involving doctor/salvage/verify should consider source-byte immutability where relevant.

## Adversarial Testing Priorities

High-value cases include:

- malformed/truncated JSONL;
- malformed middle records and malformed tails;
- unfinished tool calls;
- orphaned tool outputs;
- duplicate call/output IDs;
- unexpected ordering;
- corrupted tool names;
- control/NUL/ANSI/bidi/zero-width characters;
- unknown future event types;
- compaction interactions;
- oversized persisted payloads;
- base64/image-heavy payloads;
- source disappearance/change during analysis;
- destination write failures;
- symlink/path edge cases;
- unusual Git states;
- malformed data combined with otherwise recognizable findings.

For generated/fuzz cases, distinguish:

- confirmed defect;
- possible defect;
- expected conservative behavior;
- invalid synthetic state;
- out of project scope.

Do not turn every fuzzer crash or unusual input into a product bug without semantic analysis.

## Hermes Skills Setup & Policy

Do NOT bulk-install thousands of skills.

First inspect every third-party/community skill:
```bash
hermes skills inspect <identifier>
```

Install only after the scan and manual review are acceptable:
```bash
hermes skills install <identifier>
```

### Recommended Bundled Hermes Skills
(already shipped with Hermes; verify with `hermes skills list`):
- `github-code-review`
- `github-pr-workflow`
- `requesting-code-review`
- `systematic-debugging`
- `test-driven-development`
- `plan`
- `writing-plans`

### Important Project Rule on Skills
Codex Rescue currently uses stdlib unittest. Do not migrate it to pytest just because a generic testing skill recommends pytest.

### High-Value Third-Party Candidates for Codex Rescue

1. **Trail of Bits — Property-Based Testing**
   ```bash
   hermes skills inspect skills-sh/trailofbits/skills/property-based-testing
   hermes skills install skills-sh/trailofbits/skills/property-based-testing
   ```
   *Use for*: parser/normalizer/invariant testing. Do not add Hypothesis to project metadata unless explicitly justified.

2. **Trail of Bits — Atheris**
   ```bash
   hermes skills inspect skills-sh/trailofbits/skills/atheris
   hermes skills install skills-sh/trailofbits/skills/atheris
   ```
   *Use for*: isolated coverage-guided fuzz experiments. Do not make Atheris a runtime dependency.

3. **Trail of Bits — Audit Context Building**
   ```bash
   hermes skills inspect skills-sh/trailofbits/skills/audit-context-building
   hermes skills install skills-sh/trailofbits/skills/audit-context-building
   ```
   *Use for*: mapping assumptions, invariants, and flows before deep safety/security audits.

4. **Trail of Bits — Differential Review**
   ```bash
   hermes skills inspect skills-sh/trailofbits/skills/differential-review
   hermes skills install skills-sh/trailofbits/skills/differential-review
   ```
   *Use for*: reviewing a concrete fix/PR against its baseline. Do not let it broaden a narrow bug fix into a general refactor.

5. **Trail of Bits — Variant Analysis**
   ```bash
   hermes skills inspect skills-sh/trailofbits/skills/variant-analysis
   hermes skills install skills-sh/trailofbits/skills/variant-analysis
   ```
   *Use for*: searching the codebase for the same root-cause pattern after finding one real bug.

6. **Trail of Bits — Coverage Analysis**
   ```bash
   hermes skills inspect skills-sh/trailofbits/skills/coverage-analysis
   hermes skills install skills-sh/trailofbits/skills/coverage-analysis
   ```
   *Use for*: fuzz-harness effectiveness, not as a line-coverage vanity metric.

7. **W. Shobson Agents — Python Testing Patterns**
   ```bash
   hermes skills inspect skills-sh/wshobson/agents/python-testing-patterns
   hermes skills install skills-sh/wshobson/agents/python-testing-patterns
   ```
   *Use for*: test design selectively. Preserve Codex Rescue's unittest conventions unless migration is explicitly authorized.

8. **W. Shobson Agents — Python Performance Optimization**
   ```bash
   hermes skills inspect skills-sh/wshobson/agents/python-performance-optimization
   hermes skills install skills-sh/wshobson/agents/python-performance-optimization
   ```
   *Use for*: measured large-rollout performance work only.

9. **W. Shobson Agents — Python Packaging**
   ```bash
   hermes skills inspect skills-sh/wshobson/agents/python-packaging
   hermes skills install skills-sh/wshobson/agents/python-packaging
   ```
   *Use for*: PyPI/build/release work, not during normal runtime bug audits.

10. **OpenAI Agents Python — Final Release Review**
    ```bash
    hermes skills inspect skills-sh/openai/openai-agents-python/final-release-review
    hermes skills install skills-sh/openai/openai-agents-python/final-release-review
    ```
    *Use for*: preparing an explicitly authorized release only.

### Suggested Core Set to Install Now
- `property-based-testing`
- `audit-context-building`
- `differential-review`
- `variant-analysis`
- `python-testing-patterns`

### Optional for Specific Sessions
- `atheris`
- `coverage-analysis`
- `python-performance-optimization`
- `python-packaging`
- `final-release-review`

### Skills Security Rule
Third-party skills are executable instructions and may include scripts. Never use `--force` just to get past a warning. Read `SKILL.md` and referenced scripts/resources first. If the scanner reports dangerous behavior, do not install.

After installing:
```bash
hermes skills check
hermes skills list
```

Start a fresh session (or use Hermes' supported prompt-cache invalidation mechanism) before relying on newly installed skills.

## Discovery

Treat `sessions` as a bounded listing, not as proof that a missing rollout is undiscoverable.

Do not change default listing limits or discovery semantics without a demonstrated reason.

When investigating a discovery failure, distinguish:

- bounded-window cutoff;
- wrong/missing sessions root;
- inaccessible filesystem entry;
- candidate-selection bug;
- parsing/scanning failure;
- actual false negative.

## Salvage

Salvage must remain forked and source-preserving.

For failure injection or recovery-path changes, verify before/after source SHA-256 and byte size.

Never implement automatic replacement of the live Codex session file unless explicitly requested as a separately reviewed product change.

## Verify / Git State

Treat `VERIFIED` as a strong claim.

For any path producing `VERIFIED`, identify the exact evidence that justifies it.

Exercise relevant states when changing verification logic:

- clean working tree;
- dirty tracked files;
- untracked files;
- deleted files;
- renames;
- detached HEAD;
- branch/commit divergence;
- missing/unavailable Git repository;
- Git command failure;
- worktree/submodule edge cases when applicable.

Ambiguity should remain conservative.

## Privacy and Fixtures

Never commit:

- raw private rollouts;
- private prompts;
- credentials;
- tokens;
- API keys;
- secrets;
- private repository contents;
- private SQLite/WAL files;
- exact sensitive local paths;
- unsanitized user logs;
- private attachments/images.

Real bugs should become sanitized, minimal regression fixtures whenever possible.

Synthetic fixtures must not be presented as actual user data.

## Dependencies

The runtime package should remain minimal.

Do not add a runtime dependency for convenience when the standard library is sufficient.

Audit-only tools must not silently become runtime dependencies.

Any new dependency requires:

- clear need;
- license/security review;
- impact analysis;
- explanation of why existing code cannot reasonably avoid it.

## Scope Discipline

Do not:

- redesign the architecture during a bug audit;
- rewrite in Rust/TypeScript/another language;
- refactor unrelated modules;
- rename broad APIs for style;
- reformat unrelated files;
- create speculative compaction recovery;
- add automatic unknown-tool replay;
- add live SQLite repair;
- change JSON schemas casually;
- change CLI defaults casually;
- implement an idea merely because a skill recommends it.

Installed skills are advisory procedures, not project authority.

This file and the user's current task take precedence over generic skill guidance.

## Git / PR Workflow

Do not work directly on `main`.

Use a focused branch.

Keep commits logically scoped.

Before opening a PR:

1. inspect the final diff;
2. confirm no unrelated files changed;
3. run targeted tests;
4. run the full suite;
5. check for accidental secrets/private data;
6. state what was not tested.

Do not merge a PR automatically unless the user explicitly asks.

## Releases

Do not:

- bump the version;
- create a tag;
- publish to PyPI;
- publish npm packages;
- create a GitHub Release;
- announce a release;

unless the user explicitly authorizes a release task.

Documentation-only or clarification-only changes do not automatically justify a new release.

## External Communication

Do not autonomously:

- comment on upstream GitHub issues;
- contact testers;
- ask for stars;
- post promotional messages;
- open external issues;
- publish announcements.

External communication requires explicit user authorization.

Public research is allowed when needed for the task.

Separate:

- FACT
- INFERENCE
- HYPOTHESIS
- UNKNOWN

## Working Style

Prefer:

- evidence over intuition;
- minimized reproductions over broad rewrites;
- targeted tests over coverage theater;
- conservative statuses over optimistic claims;
- small diffs over architecture churn;
- explicit uncertainty over guessing.

When uncertain about a safety-relevant behavior, stop and investigate before changing production semantics.

## Final Report

For non-trivial engineering tasks report:

- commit/base audited;
- files changed;
- confirmed findings;
- unconfirmed findings;
- tests actually run;
- pass/fail/skip counts when available;
- safety invariant impact;
- dependencies added, if any;
- branch/commit/PR;
- limitations and untested areas.

Never claim a test, reproduction, security property, or external fact was verified unless it was actually checked.
