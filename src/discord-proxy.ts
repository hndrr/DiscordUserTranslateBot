import https from 'node:https';
import type { RequestOptions } from 'node:https';
import { ProxyAgent } from 'proxy-agent';

export function gatewayProxyOptions(options: RequestOptions, agent: ProxyAgent): RequestOptions {
  const host = String(options.hostname || options.host || '').toLowerCase();
  const headers = options.headers;
  const upgrade = headers && !Array.isArray(headers)
    ? String((headers as Record<string, unknown>).Upgrade || (headers as Record<string, unknown>).upgrade || '').toLowerCase() : '';
  if (upgrade !== 'websocket' || !host.endsWith('.discord.gg') || options.agent !== undefined) {
    return options;
  }
  return { ...options, agent };
}

/** Honor the host's existing proxy policy for discord.js's `ws` transport. */
export function configureDiscordProxy(): { agent: ProxyAgent; restore: () => void } | undefined {
  if (!['https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY', 'all_proxy', 'ALL_PROXY']
    .some((key) => process.env[key])) return undefined;

  const agent = new ProxyAgent();
  const resolveProxy = agent.getProxyForUrl;
  agent.getProxyForUrl = (url, request) => resolveProxy(
    url.replace(/^wss:/, 'https:').replace(/^ws:/, 'http:'), request,
  );

  // discord.js omits ws's agent option; ws supplies createConnection, which
  // bypasses Node's default HTTPS agent. Attach an explicit standard Agent only
  // to Discord gateway upgrades, without changing REST or unrelated requests.
  const original = https.request;
  const patched = function (this: unknown, ...args: unknown[]) {
    const options = args[0];
    if (options && typeof options === 'object' && !(options instanceof URL)) {
      args[0] = gatewayProxyOptions(options as RequestOptions, agent);
    }
    return Reflect.apply(original, this, args);
  } as typeof https.request;
  https.request = patched;
  return {
    agent,
    restore() {
      if (https.request === patched) https.request = original;
      agent.destroy();
    },
  };
}
