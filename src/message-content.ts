import { type Message } from 'discord.js';

const MAX_CONTEXT_MESSAGES = 25;
const MAX_CONTEXT_CHARS = 4000;
const MAX_REPLY_CHAIN_DEPTH = 6;

export type ContextLine = {
  id: string;
  author: string;
  content: string;
  createdTimestamp: number;
  isTarget: boolean;
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
    parts.push(`[スタンプ: ${names.join(', ')}]`);
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

function formatContext(seen: Map<string, ContextLine>, targetId: string): string {
  const lines = [...seen.values()].sort((a, b) => a.createdTimestamp - b.createdTimestamp);
  if (lines.length === 0) return '';

  const formatted = lines.map((line) => {
    const tag = line.isTarget ? '[対象] ' : '';
    return `${tag}${line.author}: ${line.content}`;
  });

  const joined = formatted.join('\n\n');
  if (joined.length <= MAX_CONTEXT_CHARS) return joined;

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
    if (total + extra > MAX_CONTEXT_CHARS && include.size > 0) continue;
    include.add(idx);
    total += extra;
  }

  return [...include]
    .sort((a, b) => a - b)
    .map((i) => formatted[i])
    .join('\n\n');
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
