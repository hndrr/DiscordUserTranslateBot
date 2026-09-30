import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { copyFile, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { test, type TestContext } from 'node:test';

const linux = process.platform === 'linux';

async function waitFor(check: () => Promise<boolean> | boolean, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (!await check()) {
    assert.ok(Date.now() < deadline, 'timed out waiting for the supervisor fixture');
    await delay(20);
  }
}

async function startSupervisor(t: TestContext, mode: 'graceful' | 'stubborn' | 'exit') {
  const directory = await mkdtemp(path.join(tmpdir(), 'supervisor-test-'));
  const bin = path.join(directory, 'bin');
  await mkdir(bin);
  await mkdir(path.join(directory, 'node_modules'));
  // Run only a copy and a fake executable, never the real bot or its configuration.
  await copyFile(new URL('../run-forever.sh', import.meta.url), path.join(directory, 'run-forever.sh'));
  await writeFile(path.join(bin, 'node'), `#!${process.execPath}
const fs = require('node:fs');
process.on('SIGTERM', () => {
  fs.appendFileSync('events', 'term\\n');
  if (process.env.BOT_TEST_MODE === 'graceful') process.exit(0);
});
fs.appendFileSync('events', 'start\\n');
fs.writeFileSync('child.pid', String(process.pid));
if (process.env.BOT_TEST_MODE !== 'exit') setInterval(() => {}, 1000);
`, { mode: 0o700 });
  const supervisor = spawn('bash', ['run-forever.sh'], {
    cwd: directory,
    env: {
      PATH: `${bin}:${process.env.PATH ?? '/usr/bin:/bin'}`,
      DISCORD_TOKEN: 'fake-supervisor-test-token',
      BOT_TEST_MODE: mode,
    },
    detached: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  supervisor.stdout.on('data', data => output += data);
  supervisor.stderr.on('data', data => output += data);
  const exited = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolve, reject) => {
    supervisor.once('error', reject);
    supervisor.once('exit', (code, signal) => resolve({ code, signal }));
  });
  t.after(async () => {
    // Only this test's new process group is eligible for cleanup.
    if (supervisor.pid !== undefined) {
      try { process.kill(-supervisor.pid, 'SIGKILL'); } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
      }
    }
    await exited;
    await rm(directory, { recursive: true, force: true });
  });
  let childPid = 0;
  await waitFor(async () => {
    try {
      childPid = Number(await readFile(path.join(directory, 'child.pid'), 'utf8'));
      return childPid > 0;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      return false;
    }
  });
  return {
    supervisor, exited, childPid,
    output: () => output,
    events: () => readFile(path.join(directory, 'events'), 'utf8'),
    assertLockReleased: () => {
      const result = spawnSync('flock', ['-n', path.join(directory, 'logs', 'bot.lock'), 'true']);
      assert.equal(result.status, 0, 'supervisor lock remained held after shutdown');
    },
  };
}

test('supervisor forwards SIGTERM and releases its lock after graceful shutdown', {
  skip: !linux, timeout: 10000,
}, async t => {
  const fixture = await startSupervisor(t, 'graceful');
  fixture.supervisor.kill('SIGTERM');
  assert.deepEqual(await fixture.exited, { code: 0, signal: null });
  assert.equal(await fixture.events(), 'start\nterm\n');
  assert.doesNotMatch(fixture.output(), /forcing shutdown|Restarting/);
  assert.throws(() => process.kill(fixture.childPid, 0), { code: 'ESRCH' });
  fixture.assertLockReleased();
});

test('supervisor bounds shutdown when the child ignores SIGTERM, even with repeated stop signals', {
  skip: !linux, timeout: 25000,
}, async t => {
  const fixture = await startSupervisor(t, 'stubborn');
  const started = Date.now();
  fixture.supervisor.kill('SIGTERM');
  await waitFor(async () => (await fixture.events()).includes('term\n'));
  fixture.supervisor.kill('SIGTERM');
  assert.deepEqual(await fixture.exited, { code: 0, signal: null });
  const elapsed = Date.now() - started;
  assert.ok(elapsed >= 14000 && elapsed < 22000, `unexpected shutdown duration: ${elapsed}ms`);
  assert.equal(await fixture.events(), 'start\nterm\n');
  assert.match(fixture.output(), /forcing shutdown/);
  assert.doesNotMatch(fixture.output(), /Restarting/);
  assert.throws(() => process.kill(fixture.childPid, 0), { code: 'ESRCH' });
  fixture.assertLockReleased();
});

test('supervisor stops during restart backoff without launching another child', {
  skip: !linux, timeout: 10000,
}, async t => {
  const fixture = await startSupervisor(t, 'exit');
  await waitFor(() => fixture.output().includes('Restarting in 5 seconds'));
  fixture.supervisor.kill('SIGTERM');
  assert.deepEqual(await fixture.exited, { code: 0, signal: null });
  assert.equal(await fixture.events(), 'start\n');
  assert.doesNotMatch(fixture.output(), /forcing shutdown/);
  fixture.assertLockReleased();
});
