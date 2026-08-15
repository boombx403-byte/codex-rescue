#!/usr/bin/env node
/**
 * Codex Rescue - Zero-Network Pure JS Launcher Shim.
 *
 * Enforces Invariant P10: Zero network calls, telemetry, or hidden uploads.
 * Dispatches directly to python -m codex_rescue.cli.
 */

const { spawnSync } = require("child_process");
const process = require("process");

const args = ["-m", "codex_rescue.cli", ...process.argv.slice(2)];

// Attempt python3 first, fallback to python
let pyExec = "python3";
let check = spawnSync(pyExec, ["--version"], { stdio: "ignore" });
if (check.error || check.status !== 0) {
  pyExec = "python";
}

const child = spawnSync(pyExec, args, {
  stdio: "inherit",
  env: {
    ...process.env,
    PYTHONUNBUFFERED: "1",
  },
});

process.exit(child.status !== null ? child.status : 1);
