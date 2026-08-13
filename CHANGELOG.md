# Changelog

All notable changes to Codex Rescue will be documented in this file.

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
- Sanitized synthetic regression corpus (5 fixture types)
- Sanitized real-origin regression corpus (3 cases)
- Crash-safe append-only journal
- Bounded recovery brief generation
- Secret redaction in handoff artifacts

### Known limitations

- Broad real compaction recovery not yet validated
- Interactive continuation depends on terminal/TTY environment
- Previous Codex version recovery coverage is limited
- Not every arbitrary corruption type is supported
