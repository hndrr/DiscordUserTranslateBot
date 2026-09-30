import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmod, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, type TestContext } from 'node:test';
import { checkStartup } from '../src/preflight.js';

async function fixture(t: TestContext) {
  const directory = await mkdtemp(path.join(tmpdir(), 'bot-preflight-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const home = path.join(directory, 'codex-home');
  const binary = path.join(directory, 'codex');
  await mkdir(home);
  // Preflight must only inspect this executable, never run it.
  await writeFile(binary, '#!/bin/sh\nexit 99\n', { mode: 0o700 });
  return { directory, home, binary, env: {
    DISCORD_TOKEN: 'fake-discord-token', AI_PROVIDER: 'codex',
    CODEX_BIN: binary, DISCORD_CODEX_HOME: home,
  } };
}

test('missing, blank and example credentials fail; Cursor skips all Codex requirements', async () => {
  for (const token of [undefined, '', ' ', 'your_discord_bot_token_here']) {
    await assert.rejects(checkStartup({ DISCORD_TOKEN: token }), /DISCORD_TOKEN/);
  }
  const env = { DISCORD_TOKEN: 'fake-token', CURSOR_API_KEY: 'fake-cursor-key', CODEX_HOME: '/missing' };
  await checkStartup(env); // Unset AI_PROVIDER preserves Cursor installations.
  await assert.rejects(checkStartup({ ...env, CURSOR_API_KEY: '' }), /CURSOR_API_KEY/);
  await assert.rejects(checkStartup({ ...env, AI_PROVIDER: 'invalid' }), /AI_PROVIDER/);
  await assert.rejects(checkStartup(env, {}, '22.12.0'), /Node.js/);
  await checkStartup(env, {}, '22.13.0');
});

test('bot-owned Codex configuration is checked with the same precedence as runtime', async t => {
  const f = await fixture(t);
  await checkStartup({ ...f.env, CODEX_HOME: '/missing-ambient-home', CODEX_REASONING_EFFORT: 'bad' }, {
    CODEX_REASONING_EFFORT: 'none',
  });
  const ambientOnly = { ...f.env, DISCORD_CODEX_HOME: undefined, CODEX_HOME: f.home, CODEX_API_KEY: 'ambient-key' };
  await assert.rejects(checkStartup(ambientOnly), /explicit absolute dedicated/);
  await checkStartup(ambientOnly, { CODEX_HOME: f.home });
  await checkStartup({ ...f.env, DISCORD_CODEX_HOME: '/missing', DISCORD_CODEX_API_KEY: 'fake-api-key' });
  await assert.rejects(checkStartup({ ...f.env, CODEX_TIMEOUT_MS: 'invalid' }), /limit configuration/);
});

test('missing homes and unusable executables fail before any provider starts', async t => {
  const f = await fixture(t);
  for (const home of ['/missing-preflight-home', f.binary]) {
    await assert.rejects(checkStartup({ ...f.env, DISCORD_CODEX_HOME: home }), /missing or inaccessible/);
  }
  await assert.rejects(checkStartup({ ...f.env, DISCORD_CODEX_HOME: 'relative' }), /explicit absolute/);
  for (const binary of ['/missing-preflight-binary', f.home]) {
    await assert.rejects(checkStartup({ ...f.env, CODEX_BIN: binary }), /executable is unavailable/);
  }
  await assert.rejects(checkStartup({ ...f.env, CODEX_BIN: './codex' }), /absolute executable path/);
  await assert.rejects(checkStartup({ ...f.env, CODEX_BIN: 'codex', PATH: '.' }), /executable is unavailable/);
  await checkStartup({ ...f.env, CODEX_BIN: 'codex', PATH: f.directory });
  if (process.platform !== 'win32') {
    await chmod(f.binary, 0o600);
    await assert.rejects(checkStartup(f.env), /executable is unavailable/);
  }
});

test('CLI reads a symlinked .env without printing its secret values or raw paths', async t => {
  const f = await fixture(t);
  const { symlink } = await import('node:fs/promises');
  const configFile = path.join(f.directory, 'bot-config');
  await writeFile(configFile, 'DISCORD_TOKEN=synthetic-secret-token\nAI_PROVIDER=codex\nDISCORD_CODEX_HOME=/synthetic-secret-home\nCODEX_BIN=/synthetic-secret-binary\n');
  await symlink(configFile, path.join(f.directory, '.env'));
  const result = spawnSync(process.execPath, [
    '--import', import.meta.resolve('tsx'), fileURLToPath(new URL('../src/preflight.ts', import.meta.url)),
  ], { cwd: f.directory, env: { PATH: process.env.PATH }, encoding: 'utf8' });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Startup preflight failed: Codex executable is unavailable/);
  assert.doesNotMatch(result.stdout + result.stderr, /synthetic-secret/);
});
