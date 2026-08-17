# codex-rescue npm prerelease

Alpha5 target package for running Codex Rescue without a user-installed Python runtime.

The JavaScript entrypoint only selects the matching installed platform package and starts its bundled standalone executable with an argument array. It does not download binaries at runtime, invoke a shell, install Python, or emit telemetry.

Version mapping: npm `0.1.0-alpha.5` corresponds to Python `0.1.0a5` and the intended GitHub release tag `v0.1.0-alpha.5`.

The package names and native builds remain **UNVERIFIED** until registry preflight and the Alpha5 native/npm CI matrix complete successfully. Do not publish this package from ordinary pull-request CI.
