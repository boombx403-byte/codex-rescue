'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const launcher = fs.readFileSync(path.join(root, 'npm', 'codex-rescue', 'bin', 'codex-rescue.js'), 'utf8');
const top = JSON.parse(fs.readFileSync(path.join(root, 'npm', 'codex-rescue', 'package.json'), 'utf8'));

const platformDirs = ['linux-x64', 'win32-x64', 'darwin-arm64', 'darwin-x64'];

test('launcher has no runtime downloader or shell execution path', () => {
  assert.doesNotMatch(launcher, /https?:\/\//i);
  assert.doesNotMatch(launcher, /curl|wget|powershell|invoke-webrequest/i);
  assert.doesNotMatch(launcher, /execSync|execFileSync|\bexec\s*\(/);
  assert.doesNotMatch(launcher, /shell\s*:\s*true/);
  assert.match(launcher, /spawn\(executable, process\.argv\.slice\(2\)/);
  assert.match(launcher, /shell:\s*false/);
});

test('top package uses an explicit content allowlist and no lifecycle scripts', () => {
  assert.deepEqual(top.files.sort(), ['README.md', 'bin/codex-rescue.js'].sort());
  assert.equal(top.scripts, undefined);
  assert.equal(top.version, '0.1.0-alpha.5');
});

test('platform packages are restricted and script-free', () => {
  for (const directory of platformDirs) {
    const pkg = JSON.parse(fs.readFileSync(path.join(root, 'npm', 'platforms', directory, 'package.json'), 'utf8'));
    assert.equal(pkg.version, '0.1.0-alpha.5');
    assert.equal(pkg.scripts, undefined);
    assert.equal(pkg.os.length, 1);
    assert.equal(pkg.cpu.length, 1);
    assert.ok(Array.isArray(pkg.files) && pkg.files.length === 2);
  }
});
