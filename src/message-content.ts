import { type Message } from 'discord.js';
import { classifyInteractionFailure } from './interaction-guard.js';

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

function formatContextLine(line: ContextLine): string {
  return `${line.isTarget ? '[対象] ' : ''}${line.author}: ${line.content}`;
}

function trimLinesToCharBudget(lines: ContextLine[], targetId: string, maxChars: number): ContextLine[] {
  if (lines.length === 0) return lines;
  const formattedLens = lines.map((line) => formatContextLine(line).length);
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
}> {
  const targetText = extractMessageText(message);
  const authorName = displayAuthor(message);
  const seen = new Map<string, ContextLine>();
  const targetLine = toLine(message, message.id);
  if (targetLine) seen.set(targetLine.id, targetLine);

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
      }
    } catch (error) {
      console.warn('Could not fetch nearby messages:', classifyInteractionFailure(error));
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
      }
    } catch (error) {
      console.warn('Could not fetch thread messages:', classifyInteractionFailure(error));
    }
  }

  const sorted = [...seen.values()].sort((a, b) => a.createdTimestamp - b.createdTimestamp);
  return {
    targetText,
    contextText: trimLinesToCharBudget(sorted, message.id, MAX_CONTEXT_CHARS)
      .map(formatContextLine).join('\n\n'),
    authorName,
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
  /** True when history could not be read beyond the target (User-Install / missing intents). */
  historyUnavailable: boolean;
}> {
  const targetText = extractMessageText(message);
  const authorName = displayAuthor(message);
  const seen = new Map<string, ContextLine>();
  const targetLine = toLine(message, message.id);
  if (targetLine) seen.set(targetLine.id, targetLine);

  await walkReplyChain(message, message.id, seen);

  const channel = message.channel;
  if (channel && 'messages' in channel) {
    const messages = channel.messages;
    // Merge anything already in the channel cache (gateway may have partial history).
    try {
      for (const cached of messages.cache.values()) {
        const line = toLine(cached, message.id);
        if (line) seen.set(line.id, line);
      }
    } catch {
      // ignore cache walk issues
    }

    async function fetchNearby(position: 'around' | 'before' | 'after', limit: number): Promise<number> {
      try {
        const fetched = await messages.fetch({ limit, [position]: message.id });
        for (const nearby of fetched.values()) {
          const line = toLine(nearby, message.id);
          if (line) seen.set(line.id, line);
        }
        return fetched.size;
      } catch (error) {
        console.warn(`Could not fetch nearby messages for similar search (${position}):`, classifyInteractionFailure(error));
        return 0;
      }
    }

    // User-Install / missing Message Content often returns only the target (or empty) without throwing.
    const aroundSize = await fetchNearby('around', MAX_NEARBY_MESSAGES);
    if (aroundSize <= 1) {
      const beforeSize = await fetchNearby('before', 50);
      const afterSize = await fetchNearby('after', 50);

      console.warn(
        `collectNearbyMessages: around=${aroundSize} before=${beforeSize} after=${afterSize} seen=${seen.size} (target=${message.id})`,
      );
    }
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
    }
  } catch (error) {
    console.warn('Could not fetch thread messages for similar search:', classifyInteractionFailure(error));
  }

  const sorted = [...seen.values()].sort((a, b) => a.createdTimestamp - b.createdTimestamp);
  const lines = trimLinesToCharBudget(sorted, message.id, MAX_NEARBY_CHARS);
  return {
    targetText,
    authorName,
    lines,
    historyUnavailable: !lines.some((line) => !line.isTarget),
  };
}
