import { COMMAND_NAMES } from './commands.js';

type InteractionKind = 'message-context-menu' | 'modal-submit';
type CommandName = (typeof COMMAND_NAMES)[keyof typeof COMMAND_NAMES] | 'unknown';
type FailureKind =
  | 'unknown-interaction'
  | 'already-acknowledged'
  | 'unknown-webhook'
  | 'invalid-webhook-token'
  | 'missing-access'
  | 'missing-permissions'
  | 'request-timeout'
  | 'unexpected-error';
type Phase = 'preparation' | 'acknowledgement' | 'work' | 'error-reply' | 'optional-context-fetch';

export type InteractionLog = {
  event: 'received' | 'acknowledged' | 'failed' | 'completed';
  command: CommandName;
  kind: InteractionKind;
  elapsedMs: number;
  ageMs?: number;
  phase?: Phase;
  failure?: FailureKind;
  outcome?: 'success' | 'failure';
};

export type InteractionLifecycle = {
  /** A rejection aborts the handler; never retry an uncertain/expired acknowledgement. */
  acknowledge: (action: () => Promise<unknown>) => Promise<void>;
  warn: (error: unknown) => void;
};

type GuardOptions = {
  command: string;
  kind: InteractionKind;
  createdTimestamp?: number;
  run: (lifecycle: InteractionLifecycle) => Promise<void>;
  onError?: (state: { acknowledged: boolean }) => Promise<unknown>;
  log?: (entry: InteractionLog) => void;
  now?: () => number;
};

/** Return a fixed category only. Never serialize errors, messages, URLs or request bodies. */
export function classifyInteractionFailure(error: unknown): FailureKind {
  try {
    if (!error || typeof error !== 'object') return 'unexpected-error';
    const code = (error as { code?: unknown }).code;
    switch (code) {
      case 10062: return 'unknown-interaction';
      case 40060: return 'already-acknowledged';
      case 10015: return 'unknown-webhook';
      case 50027: return 'invalid-webhook-token';
      case 'InteractionAlreadyReplied': return 'already-acknowledged';
      case 50001: return 'missing-access';
      case 50013: return 'missing-permissions';
      case 'ETIMEDOUT':
      case 'UND_ERR_CONNECT_TIMEOUT':
      case 'UND_ERR_HEADERS_TIMEOUT':
      case 'UND_ERR_BODY_TIMEOUT': return 'request-timeout';
      default: return 'unexpected-error';
    }
  } catch {
    return 'unexpected-error';
  }
}

function defaultLog(entry: InteractionLog): void {
  // Only this allowlisted record reaches the local console, never an error object.
  const line = `[interaction] ${JSON.stringify(entry)}`;
  if (entry.event === 'failed') console.error(line);
  else console.log(line);
}

/**
 * EventEmitter does not await async listeners. This is the outer async boundary:
 * acknowledge, work and the error reply are all caught and the promise resolves.
 */
export async function runGuardedInteraction(options: GuardOptions): Promise<void> {
  const now = options.now ?? (() => performance.now());
  const started = now();
  const command = Object.values(COMMAND_NAMES).some((name) => name === options.command)
    ? options.command as CommandName : 'unknown';
  const log = options.log ?? defaultLog;
  let phase: Phase = 'preparation';
  let acknowledgementAttempted = false;
  let acknowledged = false;
  let outcome: 'success' | 'failure' = 'success';
  const emit = (fields: Omit<InteractionLog, 'command' | 'kind' | 'elapsedMs' | 'ageMs'>): void => {
    try {
      log({
        ...fields,
        command,
        kind: options.kind,
        elapsedMs: Math.max(0, Math.round(now() - started)),
        ...(options.createdTimestamp !== undefined && Number.isFinite(options.createdTimestamp)
          ? { ageMs: Math.max(0, Math.round(Date.now() - options.createdTimestamp)) } : {}),
      });
    } catch {
      // A broken logger must not create an unhandled interaction rejection either.
    }
  };
  emit({ event: 'received' });
  try {
    await options.run({
      async acknowledge(action) {
        phase = 'acknowledgement';
        acknowledgementAttempted = true;
        await action();
        acknowledged = true;
        phase = 'work';
        emit({ event: 'acknowledged' });
      },
      warn(error) {
        emit({ event: 'failed', phase: 'optional-context-fetch', failure: classifyInteractionFailure(error) });
      },
    });
  } catch (error) {
    outcome = 'failure';
    const failure = classifyInteractionFailure(error);
    emit({ event: 'failed', phase, failure });
    // An expired/uncertain acknowledgement cannot be recovered with another reply.
    // Also stop replying when a previously acknowledged interaction has expired.
    const invalidInteraction = ['unknown-interaction', 'already-acknowledged', 'unknown-webhook', 'invalid-webhook-token'].includes(failure);
    if ((!acknowledgementAttempted || acknowledged) && !invalidInteraction && options.onError) {
      try {
        await options.onError({ acknowledged });
      } catch (replyError) {
        emit({ event: 'failed', phase: 'error-reply', failure: classifyInteractionFailure(replyError) });
      }
    }
  } finally {
    emit({ event: 'completed', outcome });
  }
}
