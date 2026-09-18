import { type Message } from 'discord.js';

const MAX_CONTEXT_MESSAGES = 25;
const MAX_CONTEXT_CHARS = 4000;
const MAX_REPLY_CHAIN_DEPTH = 6;

/** Broader window for 「類似を探す」 (~50–100 msgs / char budget). */
const MAX_NEARBY_MESSAGES = 100;
const MAX_NEARBY_CHARS = 12000;

export type ContextLine = {
  id: string;
  author: string;
  content: string;
  createdTimestamp: number;
  isTarget: boolean;
  channelId: string;
};

export function extractMessageText(message: Message): string {
  const parts: string[] = [];

  if (message.content?.trim()) {
    parts.push(message.content.trim());
  }

  for (const embed of message.embeds) {
    const embedParts: string[] = [];
    if (embed.author?.name) embedParts.push(embed.author.name);
    if (embed.title) embedParts.push(embed.title);
    if (embed.description) embedParts.push(embed.description);
    for (const field of embed.fields) {
      embedParts.push(`${field.name}: ${field.value}`);
    }
    if (embed.footer?.text) embedParts.push(embed.footer.text);
    if (embedParts.length) {
      parts.push(embedParts.join('\n'));
    }
  }

  if (message.attachments.size > 0) {
    const names = [...message.attachments.values()]
      .map((a) => a.name || a.url)
      .filter(Boolean);
    if (names.length) {
      parts.push(`[添付: ${names.join(', ')}]`);
    }
  }

  if (message.stickers.size > 0) {
    const names = [...message.stickers.values()].map((s) => s.name);
    if (names.length) {
      parts.push(`[スタンプ: ${names.join(', ')}]`);
    }
  }

  return parts.join('\n\n').trim();
}

export function displayAuthor(message: Message): string {
  return (
    message.member?.displayName ||
    message.author?.globalName ||
    message.author?.username ||
    'unknown'
  );
}

/** Discord jump link. DMs / null guild use `@me` as the guild segment. */
export function messageJumpUrl(
  guildId: string | null | undefined,
  channelId: string,
  messageId: string,
): string {
  const guildPart = guildId || '@me';
  return `https://discord.com/channels/${guildPart}/${channelId}/${messageId}`;
}

export function needsNearbyContext(message: Message): boolean {
  const channel = message.channel;
  const inThread =
    Boolean(channel) &&
    'isThread' in channel &&
    typeof channel.isThread === 'function' &&
    channel.isThread();
  return inThread || Boolean(message.reference) || Boolean(message.hasThread);
}

function toLine(message: Message, targetId: string): ContextLine | null {
  const content = extractMessageText(message);
  if (!content) return null;
  return {
    id: message.id,
    author: displayAuthor(message),
    content,
    createdTimestamp: message.createdTimestamp,
    isTarget: message.id === targetId,
    channelId: message.channelId,
  };
}

async function walkReplyChain(
  start: Message,
  targetId: string,
  seen: Map<string, ContextLine>,
): Promise<void> {
  let current: Message | null = start;
  for (let depth = 0; depth < MAX_REPLY_CHAIN_DEPTH && current; depth++) {
    const line = toLine(current, targetId);
    if (line) seen.set(line.id, line);

    const parentId = current.reference?.messageId;
    if (!parentId || seen.has(parentId)) break;
    try {
      current = await current.fetchReference();
    } catch {
      break;
    }
  }
}

function formatContext(seen: Map<string, ContextLine>, targetId: string, maxChars = MAX_CONTEXT_CHARS): string {
  const lines = [...seen.values()].sort((a, b) => a.createdTimestamp - b.createdTimestamp);
  if (lines.length === 0) return '';

  const formatted = lines.map((line) => {
    const tag = line.isTarget ? '[対象] ' : '';
    return `${tag}${line.author}: ${line.content}`;
  });

  const joined = formatted.join('\n\n');
  if (joined.length <= maxChars) return joined;

  const targetIndex = Math.max(0, lines.findIndex((line) => line.id === targetId));
  const include = new Set<number>();
  let total = 0;
  const order: number[] = [targetIndex];
  for (let distance = 1; distance < lines.length; distance++) {
    if (targetIndex - distance >= 0) order.push(targetIndex - distance);
    if (targetIndex + distance < lines.length) order.push(targetIndex + distance);
  }

  for (const idx of order) {
    const text = formatted[idx];
    const extra = text.length + (include.size ? 2 : 0);
    if (total + extra > maxChars && include.size > 0) continue;
    include.add(idx);
    total += extra;
  }

  return [...include]
    .sort((a, b) => a - b)
    .map((i) => formatted[i])
    .join('\n\n');
}

function trimLinesToCharBudget(lines: ContextLine[], targetId: string, maxChars: number): ContextLine[] {
  if (lines.length === 0) return lines;
  const formattedLens = lines.map((line) => {
    const tag = line.isTarget ? '[対象] ' : '';
    return `${tag}${line.author}: ${line.content}`.length;
  });
  const total = formattedLens.reduce((a, b) => a + b, 0) + Math.max(0, lines.length - 1) * 2;
  if (total <= maxChars) return lines;

  const targetIndex = Math.max(0, lines.findIndex((line) => line.id === targetId));
  const include = new Set<number>();
  let used = 0;
  const order: number[] = [targetIndex];
  for (let distance = 1; distance < lines.length; distance++) {
    if (targetIndex - distance >= 0) order.push(targetIndex - distance);
    if (targetIndex + distance < lines.length) order.push(targetIndex + distance);
  }
  for (const idx of order) {
    const extra = formattedLens[idx] + (include.size ? 2 : 0);
    if (used + extra > maxChars && include.size > 0) continue;
    include.add(idx);
    used += extra;
  }
  return [...include].sort((a, b) => a - b).map((i) => lines[i]);
}

export async function collectMessageContext(message: Message): Promise<{
  targetText: string;
  contextText: string;
  authorName: string;
  usedNearby: boolean;
}> {
  const targetText = extractMessageText(message);
  const authorName = displayAuthor(message);
  const seen = new Map<string, ContextLine>();
  const targetLine = toLine(message, message.id);
  if (targetLine) seen.set(targetLine.id, targetLine);

  let usedNearby = false;

  if (needsNearbyContext(message)) {
    await walkReplyChain(message, message.id, seen);

    try {
      const channel = message.channel;
      if (channel && 'messages' in channel) {
        const fetched = await channel.messages.fetch({
          limit: MAX_CONTEXT_MESSAGES,
          around: message.id,
        });
        for (const nearby of fetched.values()) {
          const line = toLine(nearby, message.id);
          if (line) seen.set(line.id, line);
        }
        if (fetched.size > 1) usedNearby = true;
      }
    } catch (error) {
      console.warn('Could not fetch nearby messages:', error);
    }

    try {
      if (message.hasThread && message.thread) {
        const threadMsgs = await message.thread.messages.fetch({
          limit: MAX_CONTEXT_MESSAGES,
        });
        for (const nearby of threadMsgs.values()) {
          const line = toLine(nearby, message.id);
          if (line) seen.set(line.id, line);
        }
        if (threadMsgs.size > 0) usedNearby = true;
      }
    } catch (error) {
      console.warn('Could not fetch thread messages:', error);
    }
  }

  return {
    targetText,
    contextText: formatContext(seen, message.id),
    authorName,
    usedNearby: usedNearby || seen.size > 1,
  };
}

/**
 * Fetch a wider window of nearby messages for similarity search.
 * Degrades gracefully when fetch fails (returns target-only).
 */
export async function collectNearbyMessages(message: Message): Promise<{
  targetText: string;
  authorName: string;
  lines: ContextLine[];
  usedNearby: boolean;
  fetchFailed: boolean;
  /** True when history could not be read beyond the target (User-Install / missing intents). */
  historyUnavailable: boolean;
}> {
  const targetText = extractMessageText(message);
  const authorName = displayAuthor(message);
  const seen = new Map<string, ContextLine>();
  const targetLine = toLine(message, message.id);
  if (targetLine) seen.set(targetLine.id, targetLine);

  let usedNearby = false;
  let fetchFailed = false;

  await walkReplyChain(message, message.id, seen);

  const channel = message.channel;
  if (channel && 'messages' in channel) {
    // Merge anything already in the channel cache (gateway may have partial history).
    try {
      for (const cached of channel.messages.cache.values()) {
        const line = toLine(cached, message.id);
        if (line) seen.set(line.id, line);
      }
    } catch {
      // ignore cache walk issues
    }

    let aroundSize = 0;
    let beforeSize = 0;
    let afterSize = 0;

    try {
      const fetched = await channel.messages.fetch({
        limit: MAX_NEARBY_MESSAGES,
        around: message.id,
      });
      aroundSize = fetched.size;
      for (const nearby of fetched.values()) {
        const line = toLine(nearby, message.id);
        if (line) seen.set(line.id, line);
      }
      if (fetched.size > 1) usedNearby = true;
    } catch (error) {
      console.warn('Could not fetch nearby messages for similar search (around):', error);
      fetchFailed = true;
    }

    // User-Install / missing Message Content often returns only the target (or empty) without throwing.
    if (aroundSize <= 1) {
      try {
        const before = await channel.messages.fetch({
          limit: 50,
          before: message.id,
        });
        beforeSize = before.size;
        for (const nearby of before.values()) {
          const line = toLine(nearby, message.id);
          if (line) seen.set(line.id, line);
        }
        if (before.size > 0) usedNearby = true;
      } catch (error) {
        console.warn('Could not fetch nearby messages for similar search (before):', error);
        fetchFailed = true;
      }

      try {
        const after = await channel.messages.fetch({
          limit: 50,
          after: message.id,
        });
        afterSize = after.size;
        for (const nearby of after.values()) {
          const line = toLine(nearby, message.id);
          if (line) seen.set(line.id, line);
        }
        if (after.size > 0) usedNearby = true;
      } catch (error) {
        console.warn('Could not fetch nearby messages for similar search (after):', error);
        fetchFailed = true;
      }

      console.warn(
        `collectNearbyMessages: around=${aroundSize} before=${beforeSize} after=${afterSize} seen=${seen.size} (target=${message.id})`,
      );
    }
  } else {
    fetchFailed = true;
  }

  try {
    if (message.hasThread && message.thread) {
      const threadMsgs = await message.thread.messages.fetch({
        limit: Math.min(MAX_NEARBY_MESSAGES, 100),
      });
      for (const nearby of threadMsgs.values()) {
        const line = toLine(nearby, message.id);
        if (line) seen.set(line.id, line);
      }
      if (threadMsgs.size > 0) usedNearby = true;
    }
  } catch (error) {
    console.warn('Could not fetch thread messages for similar search:', error);
    fetchFailed = true;
  }

  const sorted = [...seen.values()].sort((a, b) => a.createdTimestamp - b.createdTimestamp);
  const lines = trimLinesToCharBudget(sorted, message.id, MAX_NEARBY_CHARS);
  const candidatesBeyondTarget = lines.filter((l) => !l.isTarget).length;
  const historyUnavailable = candidatesBeyondTarget === 0;

  if (historyUnavailable && !fetchFailed) {
    // Silent empty history under User-Install — treat like a fetch failure for UX.
    fetchFailed = true;
  }

  return {
    targetText,
    authorName,
    lines,
    usedNearby: usedNearby || lines.length > 1,
    fetchFailed: fetchFailed && historyUnavailable,
    historyUnavailable,
  };
}
