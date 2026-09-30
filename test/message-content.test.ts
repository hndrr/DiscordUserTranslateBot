import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import type { Message } from 'discord.js';
import { collectMessageContext, collectNearbyMessages } from '../src/message-content.js';

type FetchOptions = { limit: number; around?: string; before?: string; after?: string };
const collection = (messages: Message[]) => new Map(messages.map(message => [message.id, message]));

function message(id: string, content: string): Message {
  return {
    id, content, createdTimestamp: Number(id), channelId: 'channel', channel: null,
    author: { username: `author-${id}` }, embeds: [], attachments: new Map(), stickers: new Map(),
  } as unknown as Message;
}

function setHistory(target: Message, fetch: (options: FetchOptions) => Promise<Map<string, Message>>, cached: Message[] = []) {
  Object.assign(target, {
    channel: { isThread: () => true, messages: { cache: collection(cached), fetch } },
  });
}

function captureWarnings(t: TestContext): string[] {
  const warnings: string[] = [];
  t.mock.method(console, 'warn', (...args: unknown[]) => warnings.push(args.join(' ')));
  return warnings;
}

test('context and similar-search budgets keep the target and nearest messages in chronological order', async () => {
  for (const mode of ['context', 'similar']) {
    const padding = mode === 'context' ? 1500 : 4500;
    const messages = [0, 1, 2, 3, 4].map(id => message(String(id), id === 2 ? 'selected' : 'x'.repeat(padding)));
    const target = messages[2];
    setHistory(target, async () => collection([...messages].reverse()));

    if (mode === 'context') {
      const result = await collectMessageContext(target);
      assert.equal(result.contextText, `author-1: ${messages[1].content}\n\n[対象] author-2: selected\n\nauthor-3: ${messages[3].content}`);
      assert.ok(result.contextText.length <= 4000);
      assert.equal(result.targetText, 'selected');
      assert.equal(result.authorName, 'author-2');
    } else {
      const result = await collectNearbyMessages(target);
      assert.deepEqual(result.lines.map(line => line.id), ['1', '2', '3']);
      assert.deepEqual(result.lines.map(line => line.isTarget), [false, true, false]);
      assert.equal(result.historyUnavailable, false);
    }
  }
});

test('an oversized target is preserved even when all surrounding messages must be omitted', async () => {
  const target = message('2', 'x'.repeat(13000));
  setHistory(target, async () => collection([message('1', 'before'), target, message('3', 'after')]));
  assert.equal((await collectMessageContext(target)).contextText, `[対象] author-2: ${target.content}`);
  const nearby = await collectNearbyMessages(target);
  assert.deepEqual(nearby.lines.map(line => line.id), ['2']);
  assert.equal(nearby.historyUnavailable, true);
});

test('a target-only around result fetches before and after, keeping cached and reply context on partial failure', async t => {
  const warnings = captureWarnings(t);
  const target = message('3', 'selected');
  const parent = message('2', 'parent');
  Object.assign(target, { reference: { messageId: parent.id }, fetchReference: async () => parent });
  const requests: FetchOptions[] = [];
  setHistory(target, async options => {
    requests.push(options);
    if (options.around) return collection([target]);
    if (options.before) throw Object.assign(new Error('PRIVATE_FAILURE'), { code: 50001 });
    return collection([message('4', 'after'), target]);
  }, [message('1', 'cached')]);

  const result = await collectNearbyMessages(target);
  assert.deepEqual(requests, [
    { limit: 100, around: '3' }, { limit: 50, before: '3' }, { limit: 50, after: '3' },
  ]);
  assert.deepEqual(result.lines.map(line => line.id), ['1', '2', '3', '4']);
  assert.equal(result.historyUnavailable, false);
  assert.ok(warnings.some(line => line.includes('missing-access')));
  assert.ok(warnings.every(line => !line.includes('PRIVATE_FAILURE')));
});

test('an around failure still allows before and after results to supply history', async t => {
  captureWarnings(t);
  const target = message('2', 'selected');
  const requests: FetchOptions[] = [];
  setHistory(target, async options => {
    requests.push(options);
    if (options.around) throw new Error('offline');
    return collection([options.before ? message('1', 'before') : message('3', 'after')]);
  });
  const result = await collectNearbyMessages(target);
  assert.equal(requests.length, 3);
  assert.deepEqual(result.lines.map(line => line.id), ['1', '2', '3']);
  assert.equal(result.historyUnavailable, false);
});

test('available around history skips extra range requests and merges attached thread messages', async () => {
  const target = message('2', 'selected');
  const requests: FetchOptions[] = [];
  setHistory(target, async options => {
    requests.push(options);
    return collection([target, message('1', 'before')]);
  });
  Object.assign(target, {
    hasThread: true,
    thread: { messages: { fetch: async () => collection([message('3', 'thread reply'), target]) } },
  });
  const result = await collectNearbyMessages(target);
  assert.deepEqual(requests, [{ limit: 100, around: '2' }]);
  assert.deepEqual(result.lines.map(line => line.id), ['1', '2', '3']);
  assert.equal(result.historyUnavailable, false);
});

test('unavailable or silently empty history falls back to the selected message', async t => {
  captureWarnings(t);
  for (const mode of ['no-channel', 'empty', 'failed']) {
    const target = message('1', 'selected');
    if (mode !== 'no-channel') {
      setHistory(target, async () => {
        if (mode === 'failed') throw new Error('offline');
        return collection([]);
      });
    }
    assert.equal((await collectMessageContext(target)).contextText, '[対象] author-1: selected');
    const result = await collectNearbyMessages(target);
    assert.deepEqual(result.lines.map(line => line.id), ['1']);
    assert.equal(result.historyUnavailable, true);
  }
  const empty = message('1', '');
  assert.equal((await collectMessageContext(empty)).contextText, '');
  assert.deepEqual((await collectNearbyMessages(empty)).lines, []);
});
