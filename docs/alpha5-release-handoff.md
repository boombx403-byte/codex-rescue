# Alpha5 release handoff

Operational handoff for Codex Rescue `0.1.0a5` / npm `0.1.0-alpha.5`.

## Source identity

- `HARDENING_PR_NUMBER`: `7`
- `HARDENING_PR_STATE`: open and non-draft until the exact-head CI gates below are green; merge only after those gates pass.
- `QUALIFIED_SOURCE_SHA`: **the exact current PR #7 head that has green Core CI and Alpha5 Native/NPM qualification.** Do not trust a hardcoded SHA in this tracked file: changing this file changes the commit SHA. Resolve PR #7 immediately before merge and bind every later step to that exact value.
- `EXPECTED_PYTHON_VERSION`: `0.1.0a5`
- `EXPECTED_NPM_VERSION`: `0.1.0-alpha.5`
- `EXPECTED_TAG`: `v0.1.0-alpha.5`

PYPI_ALPHA5_POLICY: NOT_PUBLISHED. PyPI is intentionally not an Alpha5
distribution channel. Python remains the canonical implementation and stays
in qualification/build coverage, but Alpha5 publication is GitHub plus npm.

Official Alpha5 distribution channels:

- GitHub Release / standalone native binaries
- `npx codex-rescue@0.1.0-alpha.5`
- `npm install -g codex-rescue@0.1.0-alpha.5`

## NPM package names

Publish these exact packages only:

1. `codex-rescue-linux-x64`
2. `codex-rescue-win32-x64`
3. `codex-rescue-darwin-arm64`
4. `codex-rescue-darwin-x64`
5. `codex-rescue` — publish **last**

`NPM_NAME_PREFLIGHT_RESULT`: prior pre-release audit PASS: all five names returned unambiguous npm registry E404 and were therefore unregistered at that check. That result is time-sensitive and does **not** authorize publication by itself. The publish workflow must re-run registry checks, pass `npm whoami`, and pass the name/maintainer ownership gate immediately before publication.

## Required CI runs

For the exact PR #7 head that will be merged into the release source, require all of these green:

- `CI` core matrix: Linux, Windows, macOS; Python 3.11 and 3.13.
- `Alpha5 Native and NPM`: Linux x64, Windows x64, macOS arm64, macOS x64 plus npm security and Python/native/npm structured JSON parity.

If a separate Alpha5 qualification or registry-preflight workflow is present on the exact head, require it too. A green run for any different SHA does not qualify the release source.

After PR #7 is merged, **do not publish immediately just because the PR head was green**. Resolve the merge SHA on `main`, verify that the merge contains the exact qualified head without additional release-affecting changes, then build the deterministic release candidate at the final tagged release SHA. The release-candidate workflow is the final artifact qualification gate.

## Exact release sequence

1. Resolve PR #7 and record its exact current head SHA. Confirm it is mergeable, based on current `main`, and all required exact-head CI above is green.
2. Merge PR #7 without rewriting the qualified branch before merge. Record the resulting merge SHA.
3. Verify the merged source still reports Python `0.1.0a5`, npm `0.1.0-alpha.5`, and the five package names above. Confirm no unrelated release-affecting commits were introduced between qualification and the intended tag.
4. When npm publication is actually available and authorized, re-check all five npm names plus authenticated publisher identity/ownership. Stop if any name or identity gate changed.
5. Create `v0.1.0-alpha.5` at the exact intended release SHA. Immediately verify the tag resolves to that SHA.
6. Dispatch `Alpha5 Release Candidate` **at workflow ref `v0.1.0-alpha.5`** with `release_tag=v0.1.0-alpha.5` and `expected_sha=<exact release SHA>`. Require success. Record its workflow run ID and download `alpha5-release-bundle`. A run dispatched from a different workflow ref must be rejected if its `head_sha` is not the expected release SHA.
7. Verify `release-manifest.json`, `SHA256SUMS`, and the complete expected artifact set. Create the GitHub **prerelease** for `v0.1.0-alpha.5`, targeting the exact same SHA, and attach exactly the candidate bundle files.
8. Dispatch the npm-only `Publish Alpha5` workflow from current `main` with `release_tag=v0.1.0-alpha.5`, the exact release SHA, and the successful candidate run ID. The workflow must re-verify tag/SHA, candidate run/source SHA, GitHub prerelease assets/hashes, npm identity/name ownership, and version nonexistence.
9. Publish npm platform packages in deterministic order: Linux x64, Windows x64, macOS arm64, macOS x64.
10. Confirm each platform package version, integrity, shasum, and maintainer immediately after publication.
11. Confirm all four exact platform versions are public and owned by the authenticated npm identity; then publish `codex-rescue@0.1.0-alpha.5` **last** and verify its optional dependencies.
12. Perform public npm/npx and GitHub checks below. Stop on any mismatch; do not attempt destructive rollback of immutable package versions/tags.

## Expected artifacts

Exact release-candidate bundle:

- `codex_rescue-0.1.0a5-py3-none-any.whl`
- `codex_rescue-0.1.0a5.tar.gz`
- `codex-rescue-linux-x64`
- `codex-rescue-win32-x64.exe`
- `codex-rescue-darwin-arm64`
- `codex-rescue-darwin-x64`
- `codex-rescue-linux-x64-0.1.0-alpha.5.tgz`
- `codex-rescue-win32-x64-0.1.0-alpha.5.tgz`
- `codex-rescue-darwin-arm64-0.1.0-alpha.5.tgz`
- `codex-rescue-darwin-x64-0.1.0-alpha.5.tgz`
- `codex-rescue-0.1.0-alpha.5.tgz`
- `SHA256SUMS`
- `release-manifest.json`

## Post-publication checks

- GitHub tag and prerelease resolve to the intended release SHA.
- Download every GitHub release asset and verify SHA256 against `release-manifest.json` / `SHA256SUMS`.
- npm exposes all four platform packages and the meta package at exactly `0.1.0-alpha.5`.
- `npx codex-rescue@0.1.0-alpha.5 --version` and `--help` succeed on supported platforms without Python installed where practical.
- `npm install -g codex-rescue@0.1.0-alpha.5` succeeds on supported platforms.
- Public npm tarballs contain only their audited allowlisted files.
- Candidate Python/native/npm qualification and structured parity remain required; public Alpha5 verification is GitHub and npm only.

## Rollback / stop conditions

Stop immediately if any of these is true:

- PR #7 head differs from the SHA whose required CI is green at merge time.
- Any required exact-head CI is no longer green.
- `main` changes in a way that changes the intended release source before tagging and the new source has not been requalified.
- Any npm package name is no longer available/owned by the authenticated release identity.
- `npm whoami` fails or does not match the expected publisher identity.
- Any npm `0.1.0-alpha.5` unexpectedly already exists with different/unverified content.
- Candidate artifact set is incomplete or contains unexpected files.
- Any candidate/GitHub-release artifact SHA256 differs from the manifest.
- `v0.1.0-alpha.5` exists before the authorized tag step, or resolves to the wrong SHA.
- GitHub prerelease target/tag/source SHA is not exact.
- npm publication authentication or identity/ownership is unavailable or weaker than expected.
- Any publish workflow gate is skipped, disabled, or manually bypassed.

## Do not touch

- Alpha4 tag `v0.1.0-alpha.4`.
- Existing Alpha4 GitHub release.
- Existing Alpha4 PyPI publication (`0.1.0a4`).
- Released history.

Never force-push `main`, move released tags, overwrite published package versions, or publish the npm meta package before all platform packages have passed public verification.
