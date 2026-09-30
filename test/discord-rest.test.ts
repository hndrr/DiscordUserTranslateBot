import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { ChatInputCommandInteraction, Client, MessageFlags } from 'discord.js';
import { createDiscordRestTransport } from '../src/discord-rest.js';

test('warms before starting, shares startup and stops periodic read-only probes', async () => {
  const transport = createDiscordRestTransport({ env: {}, intervalMs: 20 });
  let requests = 0;
  const probeAgents: unknown[] = [];
  const rest = { async get(route: string, options: unknown) {
    assert.equal(route, '/gateway');
    assert.equal((options as { auth: boolean }).auth, false);
    probeAgents.push((options as { dispatcher: unknown }).dispatcher);
    requests++;
  } };
  await Promise.all([transport.start(rest), transport.start(rest)]);
  assert.equal(requests, 1);
  await delay(55);
  assert.ok(requests >= 2);
  assert.ok(probeAgents.every(Boolean));
  assert.notEqual(probeAgents[0], probeAgents[1]);
  for (let i = 2; i < probeAgents.length; i++) assert.equal(probeAgents[i], probeAgents[i % 2]);
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

test('real discord.js replies and modals bypass blocked probes and history fetches', { timeout: 5000 }, async t => {
  let blockProbes = false;
  let signalProbe!: () => void;
  const probeStarted = new Promise<void>(resolve => { signalProbe = resolve; });
  let releaseProbe!: () => void;
  const probeReleased = new Promise<void>(resolve => { releaseProbe = resolve; });
  let signalHistory!: () => void;
  const historyStarted = new Promise<void>(resolve => { signalHistory = resolve; });
  const callbacks: { type: number; data?: { flags?: number } }[] = [];
  const warmedSockets = new Set();
  let blockedProbeSocket: unknown;
  let historySocket: unknown;
  const server = createServer(async (req, res) => {
    if (req.url === '/api/v10/gateway' && blockProbes) {
      blockedProbeSocket = req.socket;
      signalProbe();
      await probeReleased;
    }
    if (req.url?.startsWith('/api/v10/channels/')) {
      historySocket = req.socket;
      signalHistory();
      await probeReleased;
    }
    if (req.url?.includes('/callback')) {
      assert.ok(warmedSockets.has(req.socket));
      assert.notEqual(req.socket, blockedProbeSocket);
      assert.notEqual(req.socket, historySocket);
      let body = '';
      for await (const chunk of req) body += chunk;
      callbacks.push(JSON.parse(body));
      res.writeHead(204).end();
    } else {
      if (req.url === '/api/v10/gateway') warmedSockets.add(req.socket);
      res.writeHead(200, { 'content-type': 'application/json' }).end('{}');
    }
  });
  const transport = createDiscordRestTransport({ env: {}, intervalMs: 20 });
  t.after(async () => {
    releaseProbe();
    await transport.stop();
    server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  const client = new Client({
    intents: [],
    rest: {
      api: `http://127.0.0.1:${address.port}/api`,
      agent: transport.agent, makeRequest: transport.makeRequest, timeout: 2000, retries: 0,
    },
  });
  t.after(() => client.destroy());
  await transport.start(client.rest);
  blockProbes = true;
  await probeStarted;
  let historyCompleted = false;
  const history = client.rest.get('/channels/1/messages', { auth: false }).then(() => { historyCompleted = true; });
  void history.catch(() => {});
  await historyStarted;
  for (const [index, action] of ['defer', 'reply', 'modal'].entries()) {
    const interaction = new ChatInputCommandInteraction(client, {
      id: String(100 + index), application_id: '1', type: 2, version: 1,
      data: { name: 'test', type: 1 }, token: 'synthetic-test-token',
      user: { id: '2', username: 'test', discriminator: '0', avatar: null },
      entitlements: [], authorizing_integration_owners: {},
    });
    if (action === 'defer') await interaction.deferReply({ flags: MessageFlags.Ephemeral });
    else if (action === 'reply') await interaction.reply({ content: 'test', flags: MessageFlags.Ephemeral });
    else await interaction.showModal({
      custom_id: 'test-modal', title: 'Test', components: [{ type: 1, components: [
        { type: 4, custom_id: 'text', label: 'Text', style: 2 },
      ] }],
    });
    assert.equal(historyCompleted, false);
  }
  assert.deepEqual(callbacks.map(body => body.type), [5, 4, 9]);
  assert.equal(callbacks[0].data?.flags, MessageFlags.Ephemeral);
  assert.equal(callbacks[1].data?.flags, MessageFlags.Ephemeral);
  releaseProbe();
  await history;
});
