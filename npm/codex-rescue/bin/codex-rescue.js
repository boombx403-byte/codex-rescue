#!/usr/bin/env node
'use strict';

const { spawn } = require('node:child_process');
const path = require('node:path');

const targets = {
  'linux-x64': ['codex-rescue-linux-x64', 'codex-rescue'],
  'win32-x64': ['codex-rescue-win32-x64', 'codex-rescue.exe'],
  'darwin-arm64': ['codex-rescue-darwin-arm64', 'codex-rescue'],
  'darwin-x64': ['codex-rescue-darwin-x64', 'codex-rescue'],
};

const key = `${process.platform}-${process.arch}`;
const target = targets[key];
if (!target) {
  console.error(`codex-rescue: unsupported platform ${key}`);
  process.exit(1);
}

const [packageName, executableName] = target;
let packageJson;
try {
  packageJson = require.resolve(`${packageName}/package.json`);
} catch (error) {
  console.error(
    `codex-rescue: platform package ${packageName} is not installed. ` +
    'This Alpha5 prerelease expects npm to install the matching optional dependency.'
  );
  process.exit(1);
}

const executable = path.join(path.dirname(packageJson), 'bin', executableName);
const child = spawn(executable, process.argv.slice(2), {
  stdio: 'inherit',
  shell: false,
  windowsHide: false,
});

child.once('error', (error) => {
  console.error(`codex-rescue: failed to start platform executable: ${error.message}`);
  process.exitCode = 1;
});

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  if (process.platform === 'win32' && signal === 'SIGHUP') continue;
  process.on(signal, () => {
    if (!child.killed) child.kill(signal);
  });
}

child.once('exit', (code, signal) => {
  if (signal && process.platform !== 'win32') {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code === null ? 1 : code);
});
