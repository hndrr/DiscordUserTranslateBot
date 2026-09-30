import { Agent, EnvHttpProxyAgent, type Dispatcher } from 'undici';

type WarmableRest = { get(route: '/gateway', options: { auth: false }): Promise<unknown> };

/** Share one explicitly configured, warm transport with interaction callbacks. */
export function createDiscordRestTransport(options: {
  env?: NodeJS.ProcessEnv;
  intervalMs?: number;
  onWarmFailure?: () => void;
} = {}): {
  agent: Dispatcher;
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
  const agent: Dispatcher = httpProxy || httpsProxy
    ? new EnvHttpProxyAgent({
      ...connectionOptions, httpProxy, httpsProxy,
      noProxy: env.no_proxy || env.NO_PROXY || '',
    })
    : new Agent(connectionOptions);
  let timer: NodeJS.Timeout | undefined;
  let stopped = false;
  let starting: Promise<void> | undefined;
  let inFlight: Promise<void> | undefined;

  async function warm(rest: WarmableRest): Promise<void> {
    if (stopped) throw new Error('Discord REST transport is stopped');
    if (inFlight) return inFlight;
    // This is a public, read-only endpoint on the same API origin. No token or
    // Discord message data is sent, and no commands are registered or changed.
    inFlight = rest.get('/gateway', { auth: false }).then(() => undefined);
    try { await inFlight; } finally { inFlight = undefined; }
  }

  return {
    agent,
    start(rest) {
      if (stopped) return Promise.reject(new Error('Discord REST transport is stopped'));
      if (starting) return starting;
      starting = (async () => {
        // Do not connect the gateway until the REST acknowledgement path is warm.
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
      await agent.destroy();
    },
  };
}
