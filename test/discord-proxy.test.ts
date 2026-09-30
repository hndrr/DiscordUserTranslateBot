import assert from 'node:assert/strict';
import { test } from 'node:test';
import https from 'node:https';
import { ProxyAgent } from 'proxy-agent';
import { configureDiscordProxy, gatewayProxyOptions } from '../src/discord-proxy.js';

const keys = [...Object.keys(process.env).filter(key => /proxy/i.test(key)), 'https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY', 'all_proxy', 'ALL_PROXY', 'no_proxy', 'NO_PROXY'];

function cleanProxyEnvironment(): () => void {
  const saved = new Map(keys.map(key => [key, process.env[key]]));
  for (const key of keys) delete process.env[key];
  return () => {
    for (const [key, value] of saved) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  };
}

test('leaves HTTPS requests unchanged without a configured proxy', () => {
  const restore = cleanProxyEnvironment();
  const original = https.request;
  try {
    assert.equal(configureDiscordProxy(), undefined);
    assert.equal(https.request, original);
  } finally { restore(); }
});

test('honors existing HTTPS proxy and NO_PROXY; restores the request hook', async () => {
  const restore = cleanProxyEnvironment();
  const original = https.request;
  let configured: ReturnType<typeof configureDiscordProxy>;
  try {
    process.env.HTTPS_PROXY = 'http://proxy.example.invalid:8080';
    process.env.NO_PROXY = '.internal.invalid';
    configured = configureDiscordProxy();
    assert.ok(configured?.agent instanceof ProxyAgent);
    assert.notEqual(https.request, original);
    assert.ok(await configured.agent.getProxyForUrl('wss://gateway.discord.gg', {} as never) === process.env.HTTPS_PROXY);
    assert.equal(await configured.agent.getProxyForUrl('wss://service.internal.invalid', {} as never), '');
  } finally {
    configured?.restore();
    restore();
  }
  assert.equal(https.request, original);
});

test('only injects an agent into Discord gateway upgrades without an explicit agent', () => {
  const agent = new ProxyAgent();
  try {
    const gateway = { host: 'gateway.discord.gg', headers: { Upgrade: 'websocket' }, createConnection() {} };
    const resume = { host: 'gateway-us-east1-b.discord.gg', headers: { upgrade: 'websocket' } };
    assert.equal(gatewayProxyOptions(gateway, agent).agent, agent);
    assert.equal(gatewayProxyOptions(resume, agent).agent, agent);
    assert.equal(gateway.agent, undefined);
    for (const untouched of [
      { host: 'discord.com', headers: { Upgrade: 'websocket' } },
      { host: 'gateway.discord.gg.example.invalid', headers: { Upgrade: 'websocket' } },
      { host: 'gateway.discord.gg', headers: {} },
      { ...gateway, agent: false as const },
    ]) assert.equal(gatewayProxyOptions(untouched, agent), untouched);
  } finally { agent.destroy(); }
});
