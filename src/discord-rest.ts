import { Agent, EnvHttpProxyAgent, type Dispatcher } from 'undici';
import { DefaultRestOptions, type RESTOptions } from 'discord.js';

type WarmableRest = { get(route: '/gateway', options: { auth: false; dispatcher?: Agent }): Promise<unknown> };

/** Keep interaction callbacks off the queue used by history fetches and probes. */
export function createDiscordRestTransport(options: {
  env?: NodeJS.ProcessEnv;
  intervalMs?: number;
  onWarmFailure?: () => void;
} = {}): {
  agent: Dispatcher;
  makeRequest: RESTOptions['makeRequest'];
  start: (rest: WarmableRest) => Promise<void>;
  stop: () => Promise<void>;
} {
  const env = options.env || process.env;
  const allProxy = env.all_proxy || env.ALL_PROXY;
  const httpProxy = env.http_proxy || env.HTTP_PROXY || allProxy;
  const httpsProxy = env.https_proxy || env.HTTPS_PROXY || httpProxy;
  const connectionOptions = {
    connections: 1,
    pipelining: 1,
    keepAliveTimeout: 60_000,
    keepAliveMaxTimeout: 60_000,
    connect: { timeout: 12_000 },
  };
  const createAgent = (): Dispatcher => httpProxy || httpsProxy
    ? new EnvHttpProxyAgent({
      ...connectionOptions, httpProxy, httpsProxy,
      noProxy: env.no_proxy || env.NO_PROXY || '',
    })
    : new Agent(connectionOptions);
  const agent = createAgent();
  let acknowledgementAgent = createAgent();
  let standbyAgent = createAgent();
  let timer: NodeJS.Timeout | undefined;
  let stopped = false;
  let starting: Promise<void> | undefined;
  let inFlight: Promise<void> | undefined;

  async function warm(rest: WarmableRest): Promise<void> {
    if (stopped) throw new Error('Discord REST transport is stopped');
    if (inFlight) return inFlight;
    // This is a public, read-only endpoint on the same API origin. No token or
    // Discord message data is sent, and no commands are registered or changed.
    const warming = standbyAgent;
    // Only promote a pool after its probe has completed. A slow probe never
    // occupies the pool currently serving callbacks, including after idle time.
    // REST narrows the override type to Agent; undici accepts any Dispatcher.
    inFlight = rest.get('/gateway', { auth: false, dispatcher: warming as Agent }).then(() => {
      if (!stopped) [acknowledgementAgent, standbyAgent] = [warming, acknowledgementAgent];
    });
    try { await inFlight; } finally { inFlight = undefined; }
  }

  return {
    agent,
    makeRequest(url, init) {
      const callback = init.method === 'POST'
        && /^\/api\/v\d+\/interactions\/\d+\/[^/]+\/callback$/.test(new URL(url).pathname);
      return DefaultRestOptions.makeRequest(url, {
        ...init,
        dispatcher: callback ? acknowledgementAgent : init.dispatcher ?? agent,
      });
    },
    start(rest) {
      if (stopped) return Promise.reject(new Error('Discord REST transport is stopped'));
      if (starting) return starting;
      starting = (async () => {
        await warm(rest);
        if (stopped) return;
        timer = setInterval(() => {
          if (inFlight || stopped) return;
          void warm(rest).catch(() => {
            if (!stopped) options.onWarmFailure?.();
          });
        }, options.intervalMs ?? 15_000);
        timer.unref();
      })();
      return starting;
    },
    async stop() {
      stopped = true;
      if (timer) clearInterval(timer);
      await Promise.all([agent.destroy(), acknowledgementAgent.destroy(), standbyAgent.destroy()]);
    },
  };
}
