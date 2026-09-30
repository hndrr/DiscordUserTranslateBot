import { config } from 'dotenv';
import { runCodexPrompt, stopCodexRequests, validateCodexConfiguration } from './codex-provider.js';

config();

export function getAgentProvider(env: NodeJS.ProcessEnv = process.env): 'cursor' | 'codex' {
  // Preserve existing installations; the example config opts new installs into Codex.
  const provider = env.AI_PROVIDER || 'cursor';
  if (provider !== 'cursor' && provider !== 'codex') {
    throw new Error('AI_PROVIDER must be cursor or codex');
  }
  return provider;
}

export function validateAgentConfiguration(): void {
  if (getAgentProvider() === 'codex') validateCodexConfiguration();
  if (getAgentProvider() === 'cursor' && !process.env.CURSOR_API_KEY) {
    throw new Error('CURSOR_API_KEY is required when AI_PROVIDER=cursor');
  }
}

export async function runAgentPrompt(prompt: string, errorLabel: string): Promise<string> {
  try {
    if (getAgentProvider() === 'codex') return await runCodexPrompt(prompt);

    const apiKey = process.env.CURSOR_API_KEY;
    if (!apiKey) throw new Error('Missing Cursor API key');
    // Codex-only runs do not import or initialize the Cursor SDK.
    const { Agent } = await import('@cursor/sdk');
    const result = await Agent.prompt(prompt, {
      apiKey,
      model: { id: process.env.CURSOR_MODEL || 'composer-2.5' },
      local: { cwd: process.cwd() },
      tools: [],
    });
    if (result.status !== 'finished') throw new Error('Agent did not finish');
    const out = String(result.result ?? '').trim();
    if (!out) throw new Error('Empty result');
    return out;
  } catch {
    // SDK/CLI errors may contain source text, credentials or provider diagnostics.
    // Keep both logs and Discord responses free of the raw provider error.
    throw new Error(`${errorLabel} failed; check provider configuration, capacity and authentication`);
  }
}

export function stopAgentRequests(): void {
  stopCodexRequests();
}
