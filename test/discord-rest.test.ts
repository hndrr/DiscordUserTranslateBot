import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { createDiscordRestTransport } from '../src/discord-rest.js';

test('warms before starting, shares startup and stops periodic read-only probes', async () => {
  const transport = createDiscordRestTransport({ env: {}, intervalMs: 20 });
  let requests = 0;
  const rest = { async get(route: string, options: unknown) {
    assert.equal(route, '/gateway');
    assert.deepEqual(options, { auth: false });
    requests++;
  } };
  await Promise.all([transport.start(rest), transport.start(rest)]);
  assert.equal(requests, 1);
  await delay(55);
  assert.ok(requests >= 2);
  await transport.stop();
  const count = requests;
  await delay(40);
  assert.equal(requests, count);
  await assert.rejects(transport.start(rest), /stopped/);
});

test('fails startup when the initial warmup fails', async () => {
  const transport = createDiscordRestTransport({ env: {}, intervalMs: 10 });
  let requests = 0;
  const rest = { async get() { requests++; throw new Error('synthetic failure'); } };
  await assert.rejects(transport.start(rest), /synthetic failure/);
  await delay(30);
  assert.equal(requests, 1);
  await transport.stop();
});

test('does not overlap probes and reports periodic failures without raw errors', async () => {
  let active = 0;
  let maxActive = 0;
  let failures = 0;
  let requests = 0;
  const transport = createDiscordRestTransport({ env: {}, intervalMs: 10, onWarmFailure: () => { failures++; } });
  const rest = { async get() {
    requests++;
    active++;
    maxActive = Math.max(maxActive, active);
    await delay(25);
    active--;
    if (requests > 1) throw new Error('private content must not be forwarded');
  } };
  await transport.start(rest);
  await delay(80);
  await transport.stop();
  assert.equal(maxActive, 1);
  assert.ok(failures > 0);
});
