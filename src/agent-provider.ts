import { config } from 'dotenv';
import { resolveBotCodexEnvironment } from './bot-environment.js';
import { runCodexPrompt, stopCodexRequests, validateCodexConfiguration, DEFAULT_CODEX_MODEL } from './codex-provider.js';

const loadedConfig = config();
const codexEnv = resolveBotCodexEnvironment(process.env, loadedConfig.parsed);

export function getAgentProvider(env: NodeJS.ProcessEnv = process.env): 'cursor' | 'codex' {
  // Preserve existing installations; the example config opts new installs into Codex.
  const provider = env.AI_PROVIDER || 'cursor';
  if (provider !== 'cursor' && provider !== 'codex') {
    throw new Error('AI_PROVIDER must be cursor or codex');
  }
  return provider;
}

export function validateAgentConfiguration(): void {
  if (getAgentProvider() === 'codex') {
    validateCodexConfiguration(codexEnv);
    const selectedModel = codexEnv.CODEX_MODEL || DEFAULT_CODEX_MODEL;
    const safeModel = /^(gpt|codex)-[a-zA-Z0-9_.-]{1,60}$/.test(selectedModel) ? selectedModel : 'custom-model';
    console.log(`[provider-config] ${JSON.stringify({ provider: 'codex', model: safeModel, reasoning: codexEnv.CODEX_REASONING_EFFORT || 'low', dedicatedHome: Boolean(codexEnv.CODEX_HOME) })}`);
  }
  if (getAgentProvider() === 'cursor' && !process.env.CURSOR_API_KEY) {
    throw new Error('CURSOR_API_KEY is required when AI_PROVIDER=cursor');
  }
}

export function classifyProviderFailure(error: unknown): string {
  if (!error || typeof error !== 'object') return 'provider-failed';
  const value = error as { message?: unknown; code?: unknown };
  if (value.code === 'ENOENT') return 'provider-path-missing';
  if (value.code === 'EACCES' || value.code === 'EROFS') return 'provider-filesystem';
  switch (value.message) {
    case 'Codex runtime state is not writable': return 'provider-read-only-runtime';
    case 'Codex could not start; check CODEX_BIN': return 'provider-binary-missing';
    case 'Codex request cancelled or timed out': return 'provider-timeout';
    case 'Codex is busy; retry shortly': return 'provider-busy';
    case 'Use a dedicated Codex home without instructions or memories':
    case 'Use a dedicated Codex home without custom skills':
    case 'Codex needs an explicit absolute dedicated CODEX_HOME or CODEX_API_KEY':
    case 'Invalid Codex reasoning effort configuration':
    case 'Invalid Codex limit configuration':
    case 'Codex skill symlinks are not allowed':
    case 'Codex skill configuration limit exceeded': return 'provider-configuration';
    default: return 'provider-failed';
  }
}

export async function runAgentPrompt(prompt: string, errorLabel: string): Promise<string> {
  try {
    if (getAgentProvider() === 'codex') return await runCodexPrompt(prompt, codexEnv);

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
  } catch (error) {
    console.error(`[provider] ${classifyProviderFailure(error)}`);
    // SDK/CLI errors may contain source text, credentials or provider diagnostics.
    // Keep both logs and Discord responses free of the raw provider error.
    throw new Error(`${errorLabel} failed; check provider configuration, capacity and authentication`);
  }
}

export function stopAgentRequests(): void {
  stopCodexRequests();
}
