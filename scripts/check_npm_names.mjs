import { spawnSync } from 'node:child_process';

const names = [
  'codex-rescue',
  'codex-rescue-linux-x64',
  'codex-rescue-win32-x64',
  'codex-rescue-darwin-arm64',
  'codex-rescue-darwin-x64',
];

const registered = [];
const unregistered = [];
const indeterminate = [];

for (const name of names) {
  const result = spawnSync('npm', ['view', name, 'name', '--json'], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
  });
  const text = `${result.stdout || ''}\n${result.stderr || ''}`;
  if (result.status === 0) {
    registered.push(name);
  } else if (/E404|404 Not Found|is not in this registry/i.test(text)) {
    unregistered.push(name);
  } else {
    indeterminate.push({ name, status: result.status, message: text.slice(0, 500) });
  }
}

console.log(JSON.stringify({ registered, unregistered, indeterminate }, null, 2));
if (registered.length || indeterminate.length) {
  console.error('Registry preflight is fail-closed: existing names require ownership verification; registry errors require retry.');
  process.exit(1);
}
