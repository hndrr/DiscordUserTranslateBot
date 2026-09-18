import { Agent } from '@cursor/sdk';
import { config } from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { ContextLine } from './message-content.js';
import { messageJumpUrl } from './message-content.js';

config();

const apiKey = process.env.CURSOR_API_KEY;
if (!apiKey) {
  console.error('❌ CURSOR_API_KEY is not set in .env file');
  process.exit(1);
}

const cwd = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const modelId = process.env.CURSOR_MODEL || 'composer-2.5';

export type BilingualDraft = {
  japanese: string;
  english: string;
};

export type SimilarMatch = {
  id: string;
  author: string;
  snippet: string;
  url: string;
};

function clipSource(text: string, max = 4000): string {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return trimmed.slice(0, max) + '…';
}

async function runAgentPrompt(prompt: string, errorLabel: string): Promise<string> {
  try {
    const result = await Agent.prompt(prompt, {
      apiKey,
      model: { id: modelId },
      local: { cwd },
      // Empty allowlist: Discord-controlled prompts cannot invoke shell/read/write.
      tools: [],
    });

    if (result.status !== 'finished') {
      throw new Error(`${errorLabel} agent did not finish: ${result.status}`);
    }

    const out = String(result.result ?? '').trim();
    if (!out) throw new Error(`${errorLabel} result was empty`);
    return out;
  } catch (error) {
    console.error('Cursor SDK error:', error);
    throw new Error(`${errorLabel} failed`);
  }
}

export async function translateMessage(text: string, targetLanguage: string): Promise<string> {
  const languageName = targetLanguage === 'ja' ? 'Japanese' : 'English';
  const trimmed = text.trim();
  if (!trimmed) return targetLanguage === 'ja' ? '（空のメッセージです）' : '(empty message)';

  const source = clipSource(trimmed);
  const prompt = `You are a translator. Translate the following Discord message into natural ${languageName}.
Rules:
- Output ONLY the ${languageName} translation
- No quotes, labels, romanization, or commentary
- Keep @mentions, emoji, and URLs unchanged
- Preserve line breaks when meaningful

Text:
${source}`;

  return runAgentPrompt(prompt, 'Translation');
}

export async function summarizeMessage(input: {
  targetText: string;
  contextText?: string;
  authorName?: string;
}): Promise<string> {
  const target = clipSource(input.targetText);
  if (!target) return '（空のメッセージです）';

  const context = clipSource(input.contextText || target);
  const author = input.authorName || 'unknown';
  const prompt = `You summarize Discord messages for a Japanese-speaking user.
Write a short Japanese summary (2–5 short sentences). No title.

The line marked [対象] is the message the user selected. Other lines are nearby thread/reply context — use them only to make the summary of the selected message useful (what it means in the conversation). If there is no extra context, summarize the selected message alone.

Rules:
- Output ONLY the Japanese summary
- Keep it concise
- Preserve key facts, questions, decisions, and @mentions
- Do not invent information that is not in the text
- If the selected message is already very short, one sentence is enough

Selected author: ${author}

Conversation:
${context}`;

  return runAgentPrompt(prompt, 'Summarize');
}

export function parseBilingualDraft(raw: string): BilingualDraft {
  const markerSplit = raw.split(/\n?<<<EN>>>\s*\n?/i);
  if (markerSplit.length >= 2) {
    const japanese = markerSplit[0].replace(/^<<<JA>>>\s*\n?/i, '').trim();
    const english = markerSplit[1].trim();
    if (japanese && english) return { japanese, english };
  }

  const labeled = raw.match(/日本語[:：]\s*([\s\S]*?)\n\s*English[:：]\s*([\s\S]*)/i);
  if (labeled?.[1]?.trim() && labeled[2]?.trim()) {
    return { japanese: labeled[1].trim(), english: labeled[2].trim() };
  }

  return { japanese: raw.trim(), english: '' };
}

export async function draftReply(input: {
  targetText: string;
  contextText?: string;
  authorName?: string;
}): Promise<BilingualDraft> {
  const target = clipSource(input.targetText);
  if (!target) {
    return { japanese: '（空のメッセージです）', english: '(empty message)' };
  }

  const context = clipSource(input.contextText || `[対象] ${input.authorName || 'unknown'}: ${target}`);
  const author = input.authorName || 'unknown';
  const prompt = `You write a suggested Discord reply TO the selected [対象] message.

Output EXACTLY this format and nothing else:
<<<JA>>>
<Japanese reply draft>
<<<EN>>>
<English reply draft>

Rules:
- JA and EN must be counterparts of the SAME reply (対訳 / bilingual), not a translation of the original message
- Natural Discord chat tone (casual, concise). Match formality of the source: if the source is formal, be politely formal; otherwise casual chat — not corporate email
- Do not wrap the drafts in quotes
- Keep each draft short (typically 1–4 sentences)
- Suggest what the invoking user might send as a reply
- Keep @mentions, emoji, and URLs unchanged when they should appear in the reply
- If the selected message is a question, answer it when possible from context; otherwise a natural acknowledgment or follow-up

Selected author: ${author}

Conversation:
${context}`;

  const raw = await runAgentPrompt(prompt, 'Draft reply');
  return parseBilingualDraft(raw);
}

function shortSnippet(text: string, max = 80): string {
  const oneLine = text.replace(/\s+/g, ' ').trim();
  if (oneLine.length <= max) return oneLine;
  return oneLine.slice(0, max - 1) + '…';
}

/** Parse agent output into ordered message IDs (JSON array or bare snowflakes). */
export function parseSimilarIds(raw: string, validIds: Set<string>, excludeId: string): string[] {
  const found: string[] = [];
  const push = (id: string) => {
    if (id === excludeId) return;
    if (!validIds.has(id)) return;
    if (found.includes(id)) return;
    found.push(id);
  };

  const jsonMatch = raw.match(/\[[\s\S]*?\]/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]) as unknown;
      if (Array.isArray(parsed)) {
        for (const item of parsed) {
          if (typeof item === 'string') push(item);
          else if (item && typeof item === 'object' && 'id' in item) {
            push(String((item as { id: unknown }).id));
          }
        }
      }
    } catch {
      // fall through to regex
    }
  }

  if (found.length === 0) {
    for (const m of raw.matchAll(/\b(\d{17,20})\b/g)) {
      push(m[1]);
    }
  }

  return found;
}

export async function findSimilarMessages(input: {
  targetText: string;
  authorName?: string;
  lines: ContextLine[];
  guildId: string | null | undefined;
  channelId: string;
}): Promise<SimilarMatch[]> {
  const target = clipSource(input.targetText);
  if (!target) return [];

  const candidates = input.lines.filter((l) => !l.isTarget);
  if (candidates.length === 0) return [];

  const catalog = candidates
    .map((l) => `- id=${l.id} | ${l.author}: ${clipSource(l.content, 400)}`)
    .join('\n');

  const prompt = `You find Discord messages with the SAME INTENT as the selected target message.
Paraphrases and rephrasings count as matches. Exact wording is not required.
Do NOT include the target itself. Prefer the strongest matches (max 8).

Output ONLY a JSON array of message id strings, e.g. ["123","456"].
No commentary. If none match, output [].

Target author: ${input.authorName || 'unknown'}
Target:
${target}

Candidates:
${catalog}`;

  const raw = await runAgentPrompt(prompt, 'Find similar');
  const validIds = new Set(candidates.map((c) => c.id));
  const targetId = input.lines.find((l) => l.isTarget)?.id || '';
  const ids = parseSimilarIds(raw, validIds, targetId).slice(0, 8);
  const byId = new Map(candidates.map((c) => [c.id, c]));

  return ids
    .map((id) => {
      const line = byId.get(id);
      if (!line) return null;
      return {
        id,
        author: line.author,
        snippet: shortSnippet(line.content),
        url: messageJumpUrl(input.guildId, line.channelId || input.channelId, id),
      } satisfies SimilarMatch;
    })
    .filter((m): m is SimilarMatch => m !== null);
}

export async function runInstruction(input: {
  instruction: string;
  targetText: string;
  contextText?: string;
  authorName?: string;
}): Promise<string> {
  const instruction = input.instruction.trim();
  if (!instruction) return '（指示が空です）';

  const target = clipSource(input.targetText);
  if (!target) return '（対象メッセージにテキストがありません）';

  const context = clipSource(input.contextText || `[対象] ${input.authorName || 'unknown'}: ${target}`, 6000);
  const author = input.authorName || 'unknown';

  const prompt = `You help a Japanese-speaking Discord user by following their free-form instruction on a selected message.

User instruction:
${clipSource(instruction, 1000)}

The line marked [対象] is the selected message. Other lines are nearby context.

Rules:
- Follow the instruction carefully
- Output ONLY the result the user asked for (no meta commentary, no "sure", no restating the instruction)
- Prefer Japanese unless the instruction asks for another language
- Keep @mentions, emoji, and URLs when relevant
- Be concise when possible
- Do not invent facts not present in the message/context

Selected author: ${author}

Conversation:
${context}`;

  return runAgentPrompt(prompt, 'Run instruction');
}
