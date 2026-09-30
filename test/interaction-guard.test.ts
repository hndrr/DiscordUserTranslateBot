import assert from 'node:assert/strict';
import { test } from 'node:test';
import { COMMAND_NAMES } from '../src/commands.js';
import {
  classifyInteractionFailure,
  runGuardedInteraction,
  type InteractionLog,
} from '../src/interaction-guard.js';

const secret = 'PRIVATE_MESSAGE_AND_REQUEST_TOKEN';
function discordError(code: number | string) {
  return Object.assign(new Error(secret), {
    code,
    url: `https://discord.example/interaction/${secret}`,
    requestBody: { content: secret, token: secret },
    rawError: { message: secret },
  });
}

for (const code of [10062, 40060, 'ETIMEDOUT', 'UNEXPECTED_SECRET_CODE']) {
  test(`failed acknowledgement (${code}) resolves without running work or replying again`, async () => {
    const entries: InteractionLog[] = [];
    let work = 0;
    let fallback = 0;
    let time = 0;
    await assert.doesNotReject(runGuardedInteraction({
      command: COMMAND_NAMES.TRANSLATE_EN,
      kind: 'message-context-menu',
      now: () => time,
      log: entry => entries.push(entry),
      run: async lifecycle => {
        await lifecycle.acknowledge(async () => {
          time = 3500;
          throw discordError(code);
        });
        work++;
      },
      onError: async () => { fallback++; },
    }));
    assert.equal(work, 0);
    assert.equal(fallback, 0);
    assert.deepEqual(entries.map(entry => entry.event), ['received', 'failed', 'completed']);
    assert.equal(entries[1].phase, 'acknowledgement');
    assert.equal(entries[1].elapsedMs, 3500);
    assert.equal(entries[2].outcome, 'failure');
    assert.ok(!JSON.stringify(entries).includes(secret));
    assert.ok(!JSON.stringify(entries).includes('UNEXPECTED_SECRET_CODE'));
  });
}

test('successful acknowledgement and completion log only safe labels and durations', async () => {
  const entries: InteractionLog[] = [];
  let time = 0;
  await runGuardedInteraction({
    command: COMMAND_NAMES.TRANSLATE_JA,
    kind: 'message-context-menu',
    createdTimestamp: Date.now() - 500,
    now: () => time,
    log: entry => entries.push(entry),
    run: async lifecycle => {
      await lifecycle.acknowledge(async () => { time = 25; });
      time = 200;
    },
  });
  assert.deepEqual(entries.map(entry => entry.event), ['received', 'acknowledged', 'completed']);
  assert.deepEqual(entries.map(entry => entry.elapsedMs), [0, 25, 200]);
  assert.equal(entries.at(-1)?.outcome, 'success');
  for (const entry of entries) {
    assert.equal(entry.command, COMMAND_NAMES.TRANSLATE_JA);
    assert.equal(entry.kind, 'message-context-menu');
    assert.ok(Number.isInteger(entry.ageMs));
    assert.ok(entry.ageMs! >= 500);
    assert.ok(Object.keys(entry).every(key => ['command', 'kind', 'event', 'elapsedMs', 'ageMs', 'outcome'].includes(key)));
  }
});

test('work errors recover once and rejection of the fallback reply cannot escape', async () => {
  const entries: InteractionLog[] = [];
  let fallback = 0;
  await assert.doesNotReject(runGuardedInteraction({
    command: COMMAND_NAMES.SUMMARIZE,
    kind: 'message-context-menu',
    log: entry => entries.push(entry),
    run: async lifecycle => {
      await lifecycle.acknowledge(async () => {});
      throw discordError('SENSITIVE_PROVIDER_ERROR');
    },
    onError: async state => {
      assert.equal(state.acknowledged, true);
      fallback++;
      throw discordError(10062);
    },
  }));
  assert.equal(fallback, 1);
  assert.deepEqual(entries.filter(entry => entry.event === 'failed').map(entry => [entry.phase, entry.failure]), [
    ['work', 'unexpected-error'], ['error-reply', 'unknown-interaction'],
  ]);
  assert.equal(entries.at(-1)?.outcome, 'failure');
  assert.ok(!JSON.stringify(entries).includes(secret));
  assert.ok(!JSON.stringify(entries).includes('SENSITIVE_PROVIDER_ERROR'));
});

for (const code of [10062, 40060, 10015, 50027]) {
  test(`expired/invalid response (${code}) does not trigger another invalid reply`, async () => {
    let fallback = 0;
    await runGuardedInteraction({
      command: COMMAND_NAMES.RUN_INSTRUCTION,
      kind: 'modal-submit',
      log: () => {},
      run: async lifecycle => {
        await lifecycle.acknowledge(async () => {});
        throw discordError(code);
      },
      onError: async () => { fallback++; },
    });
    assert.equal(fallback, 0);
  });
}

test('modal acknowledgement failure skips optional fetch and error response', async () => {
  let fetches = 0;
  let replies = 0;
  await runGuardedInteraction({
    command: COMMAND_NAMES.RUN_INSTRUCTION,
    kind: 'message-context-menu',
    log: () => {},
    run: async lifecycle => {
      await lifecycle.acknowledge(async () => { throw discordError(10062); });
      fetches++;
    },
    onError: async () => { replies++; },
  });
  assert.equal(fetches, 0);
  assert.equal(replies, 0);
});

test('preparation errors can safely respond before an acknowledgement was attempted', async () => {
  let fallback = 0;
  await runGuardedInteraction({
    command: COMMAND_NAMES.RUN_INSTRUCTION,
    kind: 'message-context-menu',
    log: () => {},
    run: async () => { throw new Error(secret); },
    onError: async ({ acknowledged }) => { assert.equal(acknowledged, false); fallback++; },
  });
  assert.equal(fallback, 1);
});

test('optional errors and unknown command names cannot leak raw input', async () => {
  const entries: InteractionLog[] = [];
  await runGuardedInteraction({
    command: secret,
    kind: 'modal-submit',
    log: entry => entries.push(entry),
    run: async lifecycle => {
      await lifecycle.acknowledge(async () => {});
      lifecycle.warn(discordError(50001));
    },
  });
  assert.ok(entries.every(entry => entry.command === 'unknown'));
  assert.equal(entries.find(entry => entry.event === 'failed')?.failure, 'missing-access');
  assert.equal(entries.at(-1)?.outcome, 'success');
  assert.ok(!JSON.stringify(entries).includes(secret));
});

test('sanitizer never coerces arbitrary errors or reads their message/body', () => {
  let inspectedSecret = false;
  const error = {
    code: 10062,
    get message() { inspectedSecret = true; throw new Error(secret); },
    get requestBody() { inspectedSecret = true; throw new Error(secret); },
    toString() { inspectedSecret = true; throw new Error(secret); },
    toJSON() { inspectedSecret = true; throw new Error(secret); },
  };
  assert.equal(classifyInteractionFailure(error), 'unknown-interaction');
  assert.equal(inspectedSecret, false);
  assert.equal(classifyInteractionFailure({ get code() { throw new Error(secret); } }), 'unexpected-error');
  assert.equal(classifyInteractionFailure(secret), 'unexpected-error');
});

test('logging failures do not prevent acknowledgement, work, or safe completion', async () => {
  let work = 0;
  await assert.doesNotReject(runGuardedInteraction({
    command: COMMAND_NAMES.DRAFT_REPLY,
    kind: 'message-context-menu',
    log: () => { throw new Error('broken logger'); },
    run: async lifecycle => {
      await lifecycle.acknowledge(async () => {});
      work++;
      throw new Error(secret);
    },
    onError: async () => { throw discordError(10062); },
  }));
  assert.equal(work, 1);
});
