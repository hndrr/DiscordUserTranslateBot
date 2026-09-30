import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolveBotCodexEnvironment } from '../src/bot-environment.js';

test('the dedicated bot home in .env wins over ambient assistant CODEX_HOME', () => {
  const env = resolveBotCodexEnvironment(
    { CODEX_HOME: '/host/assistant-home', DISCORD_TOKEN: 'keep-this-secret', CODEX_MODEL: 'host-model' },
    { CODEX_HOME: '/bot/dedicated-home', DISCORD_TOKEN: 'do-not-override', CODEX_MODEL: 'gpt-6-luna', CODEX_REASONING_EFFORT: 'low' },
  );
  assert.equal(env.CODEX_HOME, '/bot/dedicated-home');
  assert.equal(env.CODEX_MODEL, 'gpt-6-luna');
  assert.equal(env.CODEX_REASONING_EFFORT, 'low');
  assert.equal(env.DISCORD_TOKEN, 'keep-this-secret');
});

test('bot-specific environment home works without a file and takes explicit precedence', () => {
  assert.equal(resolveBotCodexEnvironment(
    { CODEX_HOME: '/host', DISCORD_CODEX_HOME: '/explicit-bot' },
    { CODEX_HOME: '/file-bot' },
  ).CODEX_HOME, '/explicit-bot');
  assert.equal(resolveBotCodexEnvironment({ DISCORD_CODEX_HOME: '/explicit-bot' }).CODEX_HOME, '/explicit-bot');
});

test('ambient CODEX_HOME is never used as a fallback', () => {
  assert.equal(resolveBotCodexEnvironment({ CODEX_HOME: '/host' }).CODEX_HOME, undefined);
  assert.equal(resolveBotCodexEnvironment({}, { DISCORD_CODEX_HOME: '/bot' }).CODEX_HOME, '/bot');
});

test('does not reuse an ambient host API key', () => {
  assert.equal(resolveBotCodexEnvironment({ CODEX_API_KEY: 'host-secret' }).CODEX_API_KEY, undefined);
  assert.equal(resolveBotCodexEnvironment({ DISCORD_CODEX_API_KEY: 'bot-secret' }).CODEX_API_KEY, 'bot-secret');
  assert.equal(resolveBotCodexEnvironment({ CODEX_API_KEY: 'host-secret' }, { CODEX_API_KEY: 'file-secret' }).CODEX_API_KEY, 'file-secret');
});
