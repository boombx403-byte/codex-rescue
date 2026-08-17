# CODEX RESCUE ALPHA5 — MASTER AUTONOMOUS END-TO-END PROMPT

You are the primary autonomous engineering, QA, packaging, CI/CD, release, and verification agent responsible for completing **Codex Rescue Alpha5** from the current repository state through a fully published and publicly verified release.

Your task is to **EXECUTE**, not to plan.

Repository:
- GitHub: `shleder/codex-rescue`
- Product: Codex Rescue
- Existing public Python release: `0.1.0a4`
- Existing GitHub prerelease/tag: `v0.1.0-alpha.4`
- Authoritative public Alpha4 replacement commit: `41d95ac0921a3a56dfb118eabcb6bf9d35e64b2f`

Target release:
- Python/PyPI: `0.1.0a5`
- npm: `0.1.0-alpha.5`
- GitHub tag: `v0.1.0-alpha.5`
- GitHub Release: prerelease

Do NOT create Alpha6, `0.1.0rc1`, or stable `0.1.0`.
Alpha5 is intentionally the large consolidation release.

---

## 0. EXECUTION CONTRACT

You are authorized to execute this work continuously from inspection through:
- implementation,
- tests,
- packaging,
- native binaries,
- npm/npx,
- CI,
- pull request,
- merge,
- release artifacts,
- GitHub prerelease,
- PyPI publication,
- npm publication,
- public post-release verification.

Do NOT stop after:
- producing a plan,
- explaining architecture,
- implementing only one subsystem,
- local tests,
- opening a PR,
- green CI,
- saying `ready to publish`,
- building artifacts.

If required tools, credentials, GitHub permissions, Trusted Publishing, or registry access are available, use them and finish.

Do not ask the operator to perform a manual action that you can perform.

Do not ask ordinary clarification questions. Inspect the repository and choose the safest implementation.

Only stop for a genuine external blocker. If blocked:
1. complete all independent work first,
2. leave the repository clean and tested,
3. preserve qualified artifacts/checksums,
4. report the exact blocker,
5. report the exact remaining action.

Do not invent blockers.

---

## 1. NON-NEGOTIABLE PRODUCT PRINCIPLES

Codex Rescue is local-first and conservative.

### 1.1 Original state is read-only by default
- `doctor` never mutates original rollout JSONL.
- diagnostics never mutate Codex SQLite.
- recovery creates a new fork/artifact instead of silently rewriting source.
- preserve source byte identity wherever read-only semantics promise it.

### 1.2 Fail closed
- never fabricate tool results,
- never assume missing output means a tool never executed,
- unknown operational schema must not silently become healthy,
- material uncertainty must not become HEALTHY.

### 1.3 HEALTHY is a strong verdict
HEALTHY means all applicable validated invariants have strong evidence.
Unresolved uncertainty in projection, schema, tool correlation, inventory, persistence, or recovery boundary prevents HEALTHY.

### 1.4 Bounded processing
- no whole-file loading for huge rollouts when streaming is possible,
- no memory proportional to total rollout size,
- no catastrophic regex on giant records,
- no unnecessary Base64 decoding,
- enforce safe record/line handling bounds.

### 1.5 Privacy
Do not print raw prompts, tool output, credentials, embedded media, private repository contents, opaque encrypted content, or unnecessarily detailed private paths.
Prefer counts, types, offsets, ordinals, structural metadata, and sanitized identifiers.

### 1.6 No telemetry
Do not add analytics, reporting, crash upload, usage tracking, or network callbacks.

### 1.7 Python remains canonical
npm/npx is a distribution layer. Do not rewrite Codex Rescue product logic in JavaScript.

### 1.8 Cross-platform
Windows and Linux are mandatory first-class targets.
macOS is first-class where CI/tooling is available.
WSL/path boundaries need explicit coverage.

---

## 2. ALPHA4 PROVENANCE — NEVER MUTATE

Alpha4 is finished and public.

Never:
- move its tag,
- change its release assets,
- republish `0.1.0a4`,
- rewrite its provenance,
- claim reconstructed SHAs equal lost historical SHAs.

Historical facts:
- bad historical tag once pointed to `cf90d09ba5b2a45a9fe59ec858c0eb9e5d40737d`
- lost intended Alpha4 RC `6d0efbec5740a638e4b2f2fbc752d607c4558767`
- lost parent `a1df018f24400602558fb3d805817a5f1c9a14fc`
- exact surviving ancestor `319636185ddac10249d0ab5ad3cbbade32d8f980`
- transparent reconstructed parent `14a2fe1f7d0cb75efc4fcd34a11362bf0d5018e7`
- public Alpha4 authoritative replacement `41d95ac0921a3a56dfb118eabcb6bf9d35e64b2f`

Alpha4 artifacts:
- wheel `codex_rescue-0.1.0a4-py3-none-any.whl`
  SHA256 `828763F50C68146F1EACF9DB5845E079205E9E01AE3F357A858AC24174EDC33E`
- sdist `codex_rescue-0.1.0a4.tar.gz`
  SHA256 `131431E41EEFB9D6C84313E46C1065792C5A5E2440A9CAEB48C243077D1CD803`

Historical Alpha4 qualification:
- product blockers 11 PASS
- Area4 BVA 5 PASS
- packaging 5 PASS
- E2E 100/100
- harness 6/6
- full tests 196 passed, 0 failed, 0 errors, 1 skipped
- compileall PASS
- wheel/sdist build PASS
- twine PASS
- clean install PASS
- version/help PASS

Existing PyPI flow uses Trusted Publishing/OIDC. Preserve it.

---

## 3. SAFE REPOSITORY SETUP

Before editing:
1. inspect remote/default branch,
2. fetch origin,
3. record current `origin/main` SHA,
4. inspect worktree status,
5. inspect branches/worktrees,
6. inspect release workflows and package config.

Historically dirty local worktrees may exist:
- `C:\Users\777\Documents\Codex\oss-tools\codex-rescue`
- `C:\Users\777\Documents\Codex\oss-tools\codex-rescue-integration`

Do not overwrite unrelated dirty work.

Prefer a fresh clone or clean worktree from current `origin/main`.

Create a dedicated branch such as `feat/alpha5-complete`.
Base Alpha5 on CURRENT `origin/main`, not blindly on old Alpha4 SHA.

Never force-push main.
Never rewrite public history.

---

## 4. INSPECT CURRENT PRODUCT BEFORE PATCHING

Map the current implementation:
- CLI entrypoints,
- `sessions`,
- `doctor`,
- `salvage`,
- `verify`,
- transcript parsing,
- schema parsing,
- state/SQLite access,
- findings/diagnostic names,
- confidence/verdict model,
- HEALTHY requirements,
- bounded reader implementation,
- packaging,
- release workflow,
- tests/E2E,
- README/changelog,
- version source.

Find where current code produces:
- HEALTHY,
- REVIEW_REQUIRED,
- UNKNOWN,
- STATE_DIVERGED,
- UNKNOWN_OPERATIONAL_SCHEMA,
- UNFINISHED_TOOL_CALL,
- OVERSIZED_PAYLOAD,
- other current state/inventory findings.

Do not implement field reports blindly.
Some reports used Alpha3. Reproduce current Alpha4/main behavior first.

---

## 5. FIELD EVIDENCE SET

Current/new issue set:
- `openai/codex#31113`
- `openai/codex#38629`
- `openai/codex#24550`
- `openai/codex#34337`
- `openai/codex#30779`
- `openai/codex#20864`
- `openai/codex#38855`
- `openai/codex#23930`
- `openai/codex#35463`
- `openai/codex#13724`
- `openai/codex#36704`
- `openai/codex#38787`
- `openai/codex#38613`
- `openai/codex#33796`
- `openai/codex#38856`

Older engineering evidence:
- `openai/codex#33493`
- `openai/codex#35746`
- `openai/codex#31433`
- `openai/codex#34863`
- `openai/codex#34446`
- `openai/codex#38792`
- operator listed `openai/codex#32976`
- previous evidence referenced `openai/codex#32974`

Do not assume #32976 and #32974 are the same issue. Inspect actual content if relevant.

Use issues as engineering evidence.
Do NOT perform promotional mass outreach.
Do NOT post Codex Rescue promotion into #33493.
Do NOT re-contact users who asked not to be contacted.

---

## 6. CORE A — PROJECTION PARITY / FALSE HEALTHY

Known critical failure:
canonical rollout may be intact while persisted thread-history projection is stale/wedged, causing UI/resume to show only early history. Alpha4 can falsely report HEALTHY if it validates only the rollout.

Evidence:
- #38792
- #35746

Alpha5 MUST eliminate false HEALTHY for this class.

Preferred diagnostic: `WEDGED_PROJECTION`.
If naming conventions require another name, use a consistent name but keep it distinct from malformed rollout, generic state divergence, unavailable DB, and unsupported schema.

Requirements:
1. discover relevant thread-history SQLite/database dynamically,
2. open SQLite read-only,
3. introspect schema rather than assume table/column names,
4. compare where available:
   - session identity,
   - projection byte offset,
   - next/expected rollout ordinal,
   - canonical rollout extent,
   - next physical/semantic record,
   - projected item extent/count,
5. detect strong evidence of canonical suffix beyond cursor, stale cursor, replayed/duplicate boundary ordinal, or projection unable to advance despite later valid canonical history,
6. missing DB/table/schema => UNKNOWN/not-applicable, not corruption,
7. exact parity => no projection defect,
8. strong mismatch MUST block HEALTHY,
9. never modify SQLite,
10. never repair source rollout in `doctor`.

Required tests:
- canonical ahead of projection -> defect
- exact boundary -> no defect
- DB absent -> unknown/not-applicable
- malformed SQLite -> fail closed/no crash
- duplicate/replayed boundary ordinal -> conservative detection
- legacy/non-paginated -> compatible
- existing healthy fixture -> remains healthy
- stale DB referencing unavailable rollout -> direction classified correctly

---

## 7. CORE B — SESSION DISCOVERY / INVENTORY PARITY

Evidence:
- #34446 hidden valid Desktop thread absent even with `sessions --limit 1000 --json`
- #31433 valid rollout files can exist while state DB rows are missing

Requirements:
1. determine supported session roots/formats from actual current code/evidence,
2. discovery cannot depend on one SQLite/index source only,
3. valid rollout remains discoverable if DB row missing, preview empty, first_user_message empty, or catalog/index missing,
4. indexes enrich but are not exclusive source of truth,
5. expose safe inventory relationships: rollout exists/DB row missing, DB row exists/rollout missing, both, duplicate/ambiguous path, unreadable/legacy candidate,
6. do not write/reindex Codex DB automatically,
7. preserve bounded scan,
8. do not search arbitrary unrelated directories,
9. deduplicate same logical session across sources,
10. preserve stable ordering and `--limit` semantics.

Tests:
- hidden valid rollout
- empty preview
- empty first_user_message
- missing catalog
- missing DB row
- stale DB row
- duplicate paths
- active/archived
- malformed header
- Windows/WSL normalization
- explicit `doctor --json path` independent of discovery

---

## 8. CORE C — MODERN/HISTORICAL SCHEMA COMPATIBILITY

Evidence:
- #20864: approximately 77 rollouts scanned, many old sessions produced UNKNOWN_OPERATIONAL_SCHEMA
- #32974 reported false schema/VCS findings but used Alpha3
- Alpha4 historical fix intended to recognize `mcp_tool_call_end`

Requirements:
1. reproduce current behavior first,
2. create compatibility matrix,
3. distinguish operational state-bearing records, stable identity records, harmless metadata, future/unknown operational records,
4. harmless historical metadata must not poison health,
5. future unknown operational records remain fail closed,
6. recognize current valid modern events such as `mcp_tool_call_end` if authoritative schema confirms them,
7. do not become overly permissive,
8. aggregate unknown type/count without dumping payloads.

Tests:
- modern known event
- historical known event
- harmless metadata
- future operational event
- unknown stable identity envelope
- unknown state-changing envelope
- unfinished call + benign metadata
- unknown operational event + otherwise healthy history

Add privacy-safe schema type-frequency output if useful.

---

## 9. CORE D — TYPE-SPECIFIC PERSISTED RESPONSE ITEM IDS

Evidence:
- #38855 reported reasoning item with `item_...` where downstream expected type-specific ID
- known test involved Alpha3

Requirements:
1. inspect authoritative current protocol/schema,
2. identify response families with strong ID contracts,
3. validate only evidence-backed rules,
4. do not hardcode speculative prefixes,
5. invalid typed persisted identity gets distinct finding,
6. strong invalid ID blocks HEALTHY,
7. legacy records remain compatible.

Tests:
- valid/invalid reasoning
- valid/invalid message
- valid/invalid function/tool call if applicable
- absent optional ID
- legacy record
- unknown future response type
- mixed histories

---

## 10. CORE E — TOOL CALL CHAIN / UNFINISHED OPERATIONS

Evidence:
- #31113 persisted missing custom tool output
- #32974 real UNFINISHED_TOOL_CALL signal

Requirements:
1. preserve/improve orphan/unmatched call correlation,
2. handle current MCP/tool forms,
3. distinguish started/no completion evidence, output without recognized call, known completion, malformed correlation, bounded correlation overflow,
4. keep memory bounded,
5. correlation overflow reduces confidence rather than yielding HEALTHY,
6. never fabricate result,
7. never claim missing output proves tool did not execute.

Tests:
- matching call/output
- missing output
- unmatched output
- duplicate call ID
- reused ID across phases
- correlation overflow
- MCP end/completion
- malformed tool record
- unknown tool family

---

## 11. CORE F — CONCURRENT WRITER / INTERLEAVED HISTORY

Evidence: #38629.

Rescue does not fix upstream writer ownership. It must not assume one authoritative stream when persisted history contradicts that.

Requirements:
1. detect strong evidence of incompatible/interleaved writers if persisted evidence allows,
2. examine conflicting ownership/lifecycle, impossible ordering, overlapping active turns, reused ordinals, multiple writer identities,
3. do not misdiagnose legitimate subagent concurrency,
4. if unsafe to linearize, fail closed,
5. salvage must not silently choose one branch without evidence.

Add synthetic interleaving fixtures.

---

## 12. CORE G — SUBAGENT / LIFECYCLE SEMANTICS

Evidence: #23930, #35463.

Historical persisted state is not authoritative live process state.

Requirements:
1. never say currently active only because historical start/spawn exists,
2. distinguish historical lifecycle, terminal marker, persisted snapshot, live state unavailable,
3. if no live registry, explicitly say persisted evidence only,
4. prefer `no terminal marker observed in persisted history` over `agent is still running`,
5. handle copied parent/child bookkeeping.

Tests:
- complete lifecycle
- missing terminal marker
- stale snapshot after completion
- conflicting lifecycle
- copied historical bookkeeping

---

## 13. CORE H — ENCRYPTION / FOREIGN PROXY FORMAT DISTINCTION

Evidence:
- #13724: account switching did not reproduce universal account-bound encryption failure
- #36704: `ocx1:` identified as OpenCodex proxy format, not native OpenAI encryption

Requirements:
1. do not infer account/key mismatch solely from account change,
2. distinguish recognized native opaque envelope from clearly identifiable foreign/proxy format,
3. unknown opaque data stays opaque,
4. never decrypt,
5. never print encrypted content,
6. foreign format may be labeled unsupported/foreign only with strong evidence,
7. do not call provider translation failure OpenAI corruption without evidence.

Tests:
- native opaque content
- recognized foreign marker
- unknown opaque prefix
- malformed envelope
- mixed history

---

## 14. CORE I — TRANSIENT EMPTY / PARTIAL ROLLOUTS

Evidence: #38613.

Requirements:
1. distinguish stable empty, recently-created partial, truncated tail,
2. avoid destructive recommendations for likely active file,
3. detect recent/active writer evidence where safe,
4. deterministic zero-length behavior,
5. if file changes during scan, return unstable/retry/review rather than false certainty,
6. do not sleep/wait for long periods in normal CLI.

Tests:
- zero length
- header only
- incomplete final line
- growth during scan simulation
- stable empty archived file
- stable valid file

---

## 15. CORE J — HUGE ROLLOUT / INLINE MEDIA HARDENING

Evidence:
- #24550
- #34337
- #30779
- #33796
- #34863
- #33493

Real field scale includes hundreds of MB, GB, tens/hundreds of GB, giant compacted records, Base64 images, and inherited subagent history duplication.

Rescue does NOT own the upstream amplification bug. It must diagnose safely at scale.

Requirements:
1. streaming/bounded scan,
2. giant single JSONL record cannot cause unbounded allocation,
3. detect oversized record without decoding media where possible,
4. aggregate file size, record count where feasible, oversized count, largest record, compacted count, inline-media indicators/counts, repeated structural-payload indicators if bounded,
5. do not hash multi-GB media by default,
6. do not Base64 decode merely to diagnose,
7. emit OVERSIZED_PAYLOAD or consistent equivalent,
8. do not claim upstream storage repair,
9. severe findings must not be hidden by size warnings,
10. define severity/precedence deliberately.

Stress tests:
- many small records
- soft-bound record
- hard-bound record
- sparse/generated huge fixture
- long line
- giant data:image marker
- replacement_history marker
- repeated child history
- truncated giant record
- Windows newlines

Acceptance:
- retained memory not proportional to full file,
- no quadratic behavior,
- no catastrophic regex,
- predictable classification under hard bounds.

---

## 16. CORE K — VCS SEMANTICS

Historical intended behavior:
- non-Git/unavailable -> confidence unknown
- verify -> REVIEW_REQUIRED
- not STATE_DIVERGED

Reverify current main.

Requirements:
1. non-Git != Git divergence,
2. unsupported VCS != repository state mismatch,
3. SVN-like workspace should not cause false Git corruption,
4. interpret git failures defensively,
5. no shell injection from paths/repo metadata.

Tests:
- healthy Git
- dirty Git if relevant
- not Git
- git unavailable
- SVN-like
- inaccessible repo
- malformed `.git`

---

## 17. SAFE RECOVERY / SALVAGE

Alpha5 should make existing recovery genuinely useful, without unsafe in-place repair.

Inspect current `salvage` and `verify`.

Required model:
1. original source unchanged,
2. recovery creates new fork/artifact,
3. transformations recorded in report/manifest,
4. preserve order/identity where safe,
5. quarantine/remove only definitely unsafe content or content beyond trusted boundary,
6. unknown tool effects remain fail closed,
7. no silent Codex SQLite mutation,
8. verify produced fork,
9. if trustworthy continuation cannot be established: REVIEW_REQUIRED, preserve usable history, do not claim successful continuation.

Support where architecture allows:
- truncated/malformed tail salvage,
- unfinished-tool boundary salvage,
- safe fork from trusted boundary,
- structural verification,
- explicit unsafe-continuation reason.

Do NOT add generic in-place `fix everything`.
In-place SQLite repair should be omitted unless an explicitly opt-in, backup-first, transactionally safe design with extensive tests is completed.

---

## 18. NPM / NPX — MANDATORY

Alpha5 must support:

```bash
npx codex-rescue@0.1.0-alpha.5 --help
npx codex-rescue@0.1.0-alpha.5 --version
npx codex-rescue@0.1.0-alpha.5 doctor --json "/path/to/rollout.jsonl"

npm install -g codex-rescue@0.1.0-alpha.5
codex-rescue sessions
```

CRITICAL: do NOT make npm simply run `pip install`.
Normal npm usage should require NO preinstalled Python.

Python remains canonical implementation.

Preferred architecture:
- standalone binaries frozen from Python,
- top-level npm launcher/meta package,
- platform-specific binary npm packages,
- launcher selects correct platform package,
- argv/stdin/stdout/stderr/exit code preserved.

Inspect dependencies and choose bundler empirically: PyInstaller, Nuitka, or another mature compatible option.
Do not rewrite business logic in JS.

---

## 19. NPM PACKAGE DESIGN / SECURITY

Check npm registry availability before publication.

Preferred meta: `codex-rescue`.

Platform packages if scope ownership exists:
- `@codex-rescue/win32-x64`
- `@codex-rescue/linux-x64`
- `@codex-rescue/darwin-x64`
- `@codex-rescue/darwin-arm64`

If scope unavailable, use deterministic unscoped names such as:
- `codex-rescue-win32-x64`
- `codex-rescue-linux-x64`
- `codex-rescue-darwin-x64`
- `codex-rescue-darwin-arm64`

Use `os`, `cpu`, and `optionalDependencies` where appropriate.

Launcher:
- use spawn/execFile with argument arrays,
- never `shell=true` with user args,
- propagate exit status/signals,
- preserve stdout/stderr,
- no runtime binary download,
- no arbitrary `latest` fetch,
- no curl/wget installer,
- no telemetry.

Native binary arrives through npm package contents/dependencies.
Audit package tarball contents.
No secrets.
Use npm provenance/trusted publishing if available.
Do not weaken PyPI OIDC.

---

## 20. STANDALONE TARGETS

Mandatory:
- Windows x64
- Linux x64

Target if supported by CI:
- macOS arm64
- macOS x64

Do not claim unsupported targets.

Standalone binary:
- requires no Python,
- reports correct version,
- same CLI/help semantics,
- same diagnostics,
- bounded behavior preserved,
- required resources included,
- no phone-home.

---

## 21. CLI PARITY HARNESS

Compare:
A. Python CLI
B. native binary
C. npm/npx launcher -> native binary

For identical synthetic fixtures compare:
- exit status,
- JSON schema,
- semantic findings,
- version,
- help structure,
- stderr classification.

Commands:
- `--version`
- `--help`
- `sessions`
- `sessions --json`
- `doctor --json <fixture>`
- `verify`
- `salvage`

Only allow documented irrelevant platform path-formatting differences.

---

## 22. CROSS-PLATFORM HARDENING

Windows:
- paths
- CRLF
- locked/shared files
- subprocess invocation
- npm `.cmd`
- PowerShell/CMD
- SQLite read-only

WSL:
- Linux paths
- mounted Windows paths where practical
- never turn `/home/...` into `C:\home...`
- preserve identity semantics

Linux:
- permissions
- symlinks
- read-only files

macOS:
- arm64 where runner exists
- x64 where runner exists
- standard read-only DB/path behavior

Do not add untested platform hacks.

---

## 23. REGRESSION TEST STRATEGY

Every field defect fixed gets regression coverage.
Use small synthetic fixtures. Do not commit real private rollouts.

Layers:
1. unit
2. diagnostic-specific
3. BVA/boundary
4. product-blocker
5. E2E
6. CLI parity
7. packaging
8. native smoke
9. npm pack/install/npx
10. full suite

Do not delete/weaken tests just to ship.
If old behavior is wrong, replace its test with a stronger correct test and document why.

---

## 24. ADVERSARIAL COVERAGE

Test as applicable:
- malformed JSON
- invalid UTF-8
- deep nesting
- huge strings
- unexpected arrays/maps
- incomplete final line
- random unknown types
- giant numbers
- negative/overflow ordinals
- invalid SQLite schema
- locked/unavailable SQLite
- symlink/path weirdness
- malicious-looking local paths
- unusual tool IDs

Persisted data must never be executed as code or shell.

---

## 25. DOCUMENTATION

Update README/changelog.

Quick start:
```bash
npx codex-rescue@0.1.0-alpha.5 --help
```

Global:
```bash
npm install -g codex-rescue@0.1.0-alpha.5
```

Python:
```bash
pipx install codex-rescue==0.1.0a5
pip install codex-rescue==0.1.0a5
```

Document:
- read-only default,
- sessions,
- doctor,
- salvage,
- verify,
- safe fork semantics,
- supported platforms,
- npm/PyPI version mapping,
- privacy,
- known limitations,
- upstream-vs-Rescue boundaries,
- never recommend posting raw rollouts.

---

## 26. VERSIONING

Use exactly:
- Python `0.1.0a5`
- npm `0.1.0-alpha.5`
- tag `v0.1.0-alpha.5`

Synchronize all version sources.
Add/keep version-consistency test.
Do not create later release versions.

---

## 27. CI / RELEASE INFRASTRUCTURE

Preserve existing PyPI flow.

CI must cover:

Core:
- supported Python versions
- Linux
- Windows
- macOS if available

Product:
- unit/full
- E2E
- compileall
- packaging
- wheel/sdist validation

Native:
- build per target
- smoke
- artifact archive
- checksum

npm:
- platform-package assembly
- meta-package assembly
- `npm pack`
- tarball audit
- clean temp install
- launcher/npx smoke
- CLI parity

Security:
- expected file manifest
- secret scan
- no runtime binary downloader
- no unexpected executables

Release:
- exact commit/version gates
- exact qualified artifact reuse where possible
- no silent rebuild drift

---

## 28. REPRODUCIBLE ARTIFACTS

Published artifacts must be the qualified artifacts.

PyPI:
- build once,
- hash,
- twine check,
- clean install exact artifacts,
- publish exact artifacts.

GitHub:
- attach exact qualified artifacts and checksums.

Native:
- hash every binary/archive.

npm:
- pack exact packages,
- hash tarballs,
- test exact tarballs,
- publish exact contents when possible.

If platform CI necessarily rebuilds, prove exact source SHA, exact version, full tests, content manifest, artifact hashes.

---

## 29. RELEASE GATES

Do not publish until mandatory gates pass.

P0:
- false HEALTHY regression addressed
- source immutability
- no fabricated tool results
- no uncontrolled-memory regression
- full suite green
- versions synchronized

Projection:
- wedge tests pass

Discovery:
- hidden rollout tests pass

Schema:
- modern/historical known forms pass
- future operational unknown fails closed

Typed IDs:
- invalid typed-ID tests pass

Tool calls:
- unfinished/orphan tests pass

Large rollout:
- bounded stress passes

Recovery:
- source unchanged
- fork verifies

Platforms:
- Windows PASS
- Linux PASS
- macOS PASS if claimed

Python:
- build
- twine
- clean install
- CLI smoke

npm:
- names confirmed
- npm pack
- package-content audit
- clean install
- npx
- Python required = NO

Security:
- no runtime binary fetch
- no shell interpolation
- no telemetry
- no secrets

---

## 30. PR / MERGE

Use coherent commits.

Suggested slices:
1. projection/state parity
2. discovery/inventory
3. schema + typed IDs
4. tool/lifecycle/concurrency
5. huge-rollout hardening
6. recovery
7. native/npm
8. CI/docs/version/release

Open PR from Alpha5 branch.
PR description includes scope, field-evidence matrix, safety invariants, tests, packaging, release plan.

Do not merge until CI is green.
Use expected-head protection if available.

---

## 31. FIELD TRACEABILITY DOCUMENT

Create `docs/alpha5-field-validation.md` or equivalent.

For every relevant issue record:
- issue
- failure class
- tested Rescue version if known
- upstream-only vs Rescue defect
- Alpha5 implementation/test
- status: FIXED / DETECTED_BOUNDED / OUT_OF_SCOPE_UPSTREAM / ALREADY_FIXED_IN_A4 / NEEDS_MORE_EVIDENCE / NOT_REPRODUCED

Interpretation anchors:

#38792
- known Alpha4 false negative
- projection wedge

#38855
- known test used Alpha3
- typed ID gap likely relevant
- mcp_tool_call_end complaint may already be fixed in A4

#32974
- known test used Alpha3
- unfinished tool useful
- schema/VCS complaints may already be fixed

#34446
- discovery gap strongly supported

#20864
- historical schema noise strongly supported

#23930 / #35463
- persisted lifecycle != live state

#13724 / #36704
- avoid false encryption causality

#38856
- upstream JetBrains/PyCharm integration resolution; do not invent Rescue fix

#24550 / #34337 / #30779 / #33796 / #34863 / #33493
- huge persistence/media/subagent amplification
- diagnose safely/boundedly
- do not claim upstream storage repair

#38629
- multi-writer safety boundary

#38613
- transient empty rollout

#38787
- large-thread/device performance; only diagnose persisted evidence if applicable

Inspect all remaining issues directly.

---

## 32. QUALIFICATION REPORT BEFORE RELEASE

Create a report with:

Repository:
- base SHA
- branch
- PR
- PR head
- merge SHA

Versions:
- Python
- npm
- tag

Changes:
- files
- diagnostics
- recovery
- packaging
- CI

Tests:
- projection
- discovery
- schema
- typed IDs
- tool/lifecycle
- huge rollout
- recovery
- BVA
- product blockers
- E2E
- full suite
- compileall
- adversarial

Python artifacts:
- wheel/hash
- sdist/hash
- twine
- clean install

Native:
- target/hash/smoke

npm:
- meta
- platform packages
- tarball hashes
- clean install
- npx
- Python required = NO

Cross-platform:
- Windows
- WSL
- Linux
- macOS

Security:
- source immutability
- SQLite read-only
- no telemetry
- no runtime download
- shell safety
- secret scan
- package audit

Do not publish if mandatory qualification fails.

---

## 33. PUBLICATION AUTHORIZATION

This prompt authorizes publishing Alpha5 after all gates pass and required credentials/permissions are available.

Do not stop at `ready to publish`.

Sequence:
1. merge Alpha5 PR after green CI,
2. record exact merge SHA,
3. verify version at SHA,
4. build/qualify exact artifacts,
5. tag exact SHA `v0.1.0-alpha.5`,
6. create GitHub prerelease,
7. publish exact Python artifacts via PyPI Trusted Publishing,
8. verify PyPI metadata/hashes,
9. publish npm platform packages,
10. publish npm meta package,
11. verify npm metadata/integrity,
12. download GitHub public assets and hash-check,
13. fresh PyPI install smoke,
14. fresh public npm/npx smoke,
15. verify GitHub tag/release target,
16. only then declare RELEASED.

Use pinned exact versions, not `latest`, during verification.

---

## 34. NPM PUBLICATION

Before publishing:
- `npm view codex-rescue`
- confirm name/ownership
- confirm scope/package names
- confirm 2FA/trusted publishing
- confirm public access settings

Publish platform packages first, meta last.

Verify:
```bash
npm view codex-rescue@0.1.0-alpha.5 version
npm view codex-rescue@0.1.0-alpha.5 dist
```

Public smoke:
```bash
npx --yes codex-rescue@0.1.0-alpha.5 --version
npx --yes codex-rescue@0.1.0-alpha.5 --help
```

Windows:
```powershell
npm install -g codex-rescue@0.1.0-alpha.5
codex-rescue --version
codex-rescue --help
```

No Python prerequisite.

---

## 35. PYPI PUBLICATION

Before publish:
- verify `0.1.0a5` does not already exist,
- verify exact hashes,
- verify OIDC/Trusted Publishing,
- do not rebuild after qualification.

After:
- verify filenames/hashes,
- clean install `pip install codex-rescue==0.1.0a5`,
- version/help smoke,
- safe synthetic doctor smoke.

If immutable version already exists with different artifacts, STOP and report conflict.

---

## 36. GITHUB RELEASE

Create prerelease:
- title `Codex Rescue 0.1.0 Alpha 5`
- tag `v0.1.0-alpha.5`
- target exact qualified merge SHA

Attach as appropriate:
- wheel
- sdist
- native binaries/archives
- checksums
- npm checksum manifest if useful

Release notes:
- changes
- safety/read-only
- npm/npx
- known limitations
- no claim of fixing upstream Codex infrastructure
- no private tester data

---

## 37. POST-RELEASE VERIFICATION

GitHub:
- tag exists
- exact SHA
- prerelease true
- assets correct
- downloaded hashes match

PyPI:
- version exists
- exact artifacts
- exact hashes
- clean install
- version/help

npm:
- exact version exists
- platform dependencies resolve
- npx works
- global install works on tested platforms
- version/help
- safe doctor smoke
- no Python required

If public artifact differs from qualified artifact, status is PARTIAL/FAILED until safely corrected.

---

## 38. OUTREACH

Do NOT mass-post Alpha5 to upstream issues.

Only reply if:
- a tester directly asked for a build/update or explicitly offered branch testing,
- operator authorization permits it,
- response is narrow and technical.

Never re-contact DO_NOT_CONTACT users.
Never promote in #33493.
Never request raw rollouts, SQLite DBs, prompts, tool output, secrets, or private paths.

---

## 39. PROHIBITED ACTIONS

Do NOT:
- mutate Alpha4
- republish Alpha4
- rewrite historical provenance
- rewrite product in JS
- make npm call pip as normal install path
- add telemetry
- add arbitrary runtime binary download
- use curl|shell installers
- interpolate persisted data into shell
- fabricate tool outputs
- mutate source rollout during doctor
- mutate Codex DB during doctor
- mislabel foreign proxy data as OpenAI corruption
- label non-Git workspace STATE_DIVERGED
- call uncertain state HEALTHY
- hide bounds/parser errors
- weaken tests to ship
- claim untested platform support
- create Alpha6
- create stable 0.1.0
- spam issues
- re-contact users who asked not to be contacted

---

## 40. AUTONOMOUS FAILURE HANDLING

When bug found:
- reproduce
- regression test
- root-cause fix
- targeted retest
- continue

When CI fails:
- inspect exact logs
- fix root cause
- push
- rerun

When packaging fails:
- fix it
- do not remove npm requirement

When platform fails:
- fix reasonable compatibility issue
- do not silently remove platform from support matrix

When release flow fails:
- inspect run/logs
- fix workflow in PR
- test
- merge
- rerun safely

Do not destructively retry immutable registry versions.

---

## 41. SUCCESS CRITERIA

Alpha5 is complete only when all reasonably achievable mandatory work is actually done:

- core field-driven defects fixed or explicitly classified
- false HEALTHY addressed
- discovery hardened
- schema compatibility hardened
- typed IDs validated where authoritative
- tool-call safety preserved
- multi-writer ambiguity handled conservatively
- lifecycle semantics corrected
- encryption/proxy distinction corrected
- empty/partial rollout handled
- huge rollouts bounded
- VCS semantics correct
- recovery useful and safe
- npm/npx implemented
- standalone binaries implemented
- npm requires no Python
- Windows/Linux tested
- macOS tested if claimed
- regression suite green
- E2E green
- compileall green
- packaging green
- CI green
- PR merged
- exact SHA known
- tag created
- GitHub prerelease published
- PyPI published and verified
- npm published and verified
- public asset hashes checked
- clean public installations tested
- Alpha4 unchanged
- no unsolicited spam

---

## 42. FINAL RESPONSE FORMAT

Return the final report with EXACTLY these top-level headings:

ALPHA5_FINAL_STATUS:
- RELEASED / PARTIAL / BLOCKED

REPOSITORY:
- BASE_SHA:
- BRANCH:
- PR:
- PR_HEAD_SHA:
- MERGE_SHA:
- TAG:
- TAG_SHA:

VERSION:
- PYTHON:
- NPM:
- GITHUB:

CORE_FIXES:
- PROJECTION_PARITY:
- SESSION_DISCOVERY:
- SCHEMA_COMPATIBILITY:
- TYPED_ITEM_IDS:
- TOOL_CALL_CHAIN:
- CONCURRENT_WRITER_SAFETY:
- LIFECYCLE_SEMANTICS:
- ENCRYPTION_FORMAT_DISTINCTION:
- TRANSIENT_EMPTY_ROLLOUT:
- LARGE_ROLLOUT_HARDENING:
- VCS_SEMANTICS:
- SAFE_RECOVERY:

DIAGNOSTICS_ADDED:
- list

FILES_CHANGED:
- count
- grouped summary

TESTS:
- TARGETED:
- BVA:
- PRODUCT_BLOCKERS:
- E2E:
- FULL_SUITE:
- COMPILEALL:
- ADVERSARIAL:

PYTHON_ARTIFACTS:
- WHEEL:
- WHEEL_SHA256:
- SDIST:
- SDIST_SHA256:
- TWINE:
- CLEAN_INSTALL:

NATIVE_ARTIFACTS:
- WINDOWS_X64:
- WINDOWS_SHA256:
- LINUX_X64:
- LINUX_SHA256:
- MACOS_ARM64:
- MACOS_ARM64_SHA256:
- MACOS_X64:
- MACOS_X64_SHA256:

NPM:
- META_PACKAGE:
- PLATFORM_PACKAGES:
- VERSION:
- PACKAGE_NAMES_AVAILABLE:
- NPM_PACK:
- CLEAN_GLOBAL_INSTALL:
- CLEAN_NPX:
- PYTHON_REQUIRED:
- TARBALL_HASHES:
- PROVENANCE_TRUSTED_PUBLISHING:

CLI_PARITY:
- PYTHON_VS_NATIVE:
- PYTHON_VS_NPX:

CROSS_PLATFORM:
- WINDOWS:
- WSL:
- LINUX:
- MACOS:

SECURITY:
- ORIGINAL_SOURCE_IMMUTABILITY:
- SQLITE_READ_ONLY:
- NO_TELEMETRY:
- NO_RUNTIME_BINARY_DOWNLOAD:
- NO_SHELL_INTERPOLATION:
- SECRET_SCAN:
- PACKAGE_CONTENT_AUDIT:

FIELD_EVIDENCE:
- FIXED:
- ALREADY_FIXED_IN_A4:
- DETECTED_BUT_UPSTREAM_ONLY:
- NEEDS_MORE_EVIDENCE:
- DO_NOT_CONTACT_THREADS:

PUBLICATION:
- GITHUB_RELEASE:
- GITHUB_RELEASE_SHA_VERIFIED:
- PYPI:
- PYPI_HASHES_VERIFIED:
- NPM:
- NPM_PUBLIC_SMOKE_VERIFIED:

KNOWN_LIMITATIONS:
- list

BLOCKERS:
- NONE or exact blockers

ALPHA4_UNCHANGED:
- YES/NO

READY_FOR_0_1_0_RC_EVALUATION:
- YES/NO

Do not hide failures.
Do not call PARTIAL `released`.
Do not claim support you did not test.
Do not claim a fix without regression coverage or strong direct evidence.

**Begin now and execute from repository inspection through final public Alpha5 verification.**