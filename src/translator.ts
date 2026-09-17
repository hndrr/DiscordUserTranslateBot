import { Agent } from '@cursor/sdk';
import { config } from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

config();

const apiKey = process.env.CURSOR_API_KEY;
if (!apiKey) {
  console.error('❌ CURSOR_API_KEY is not set in .env file');
  process.exit(1);
}

const cwd = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export async function translateMessage(text: string, targetLanguage: string): Promise<string> {
  const languageName = targetLanguage === 'ja' ? 'Japanese' : 'English';
  const trimmed = text.trim();
  if (!trimmed) return targetLanguage === 'ja' ? '（空のメッセージです）' : '(empty message)';

  const source = trimmed.length > 4000 ? trimmed.slice(0, 4000) + '…' : trimmed;
  const prompt = `You are a translator. Translate the following Discord message into natural ${languageName}.
Rules:
- Output ONLY the ${languageName} translation
- No quotes, labels, romanization, or commentary
- Keep @mentions, emoji, and URLs unchanged
- Preserve line breaks when meaningful

Text:
${source}`;

  try {
    const result = await Agent.prompt(prompt, {
      apiKey,
      model: { id: process.env.CURSOR_MODEL || 'composer-2.5' },
      local: { cwd },
    });

    if (result.status !== 'finished') {
      throw new Error(`Translation agent did not finish: ${result.status}`);
    }

    const out = String(result.result ?? '').trim();
    if (!out) throw new Error('Translation result was empty');
    return out;
  } catch (error) {
    console.error('Cursor SDK error:', error);
    throw new Error('Translation failed');
  }
}
