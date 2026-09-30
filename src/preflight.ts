import { constants } from 'node:fs';
import { access, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { config } from 'dotenv';
import { resolveBotCodexEnvironment } from './bot-environment.js';
import { validateCodexConfiguration } from './codex-provider.js';

/** Offline checks only. Never read authentication files or start a provider. */
export async function checkStartup(
  env: NodeJS.ProcessEnv,
  fileValues: Record<string, string> = {},
  nodeVersion = process.versions.node,
): Promise<void> {
  const [major, minor] = nodeVersion.split('.').map(Number);
  if (!(major > 22 || (major === 22 && minor >= 13))) {
    throw new Error('Node.js 22.13 or newer is required');
  }
  const runtime = { ...fileValues, ...env };
  if (!runtime.DISCORD_TOKEN?.trim() || runtime.DISCORD_TOKEN === 'your_discord_bot_token_here') {
    throw new Error('Set DISCORD_TOKEN before starting the supervisor');
  }
  const provider = runtime.AI_PROVIDER || 'cursor';
  if (provider === 'cursor') {
    if (!runtime.CURSOR_API_KEY?.trim() || runtime.CURSOR_API_KEY === 'your_cursor_api_key_here') {
      throw new Error('Set CURSOR_API_KEY when AI_PROVIDER=cursor');
    }
    return;
  }
  if (provider !== 'codex') throw new Error('AI_PROVIDER must be cursor or codex');

  const codex = resolveBotCodexEnvironment(runtime, fileValues);
  validateCodexConfiguration(codex);
  const binary = codex.CODEX_BIN || 'codex';
  if ((binary.includes('/') || binary.includes('\\')) && !path.isAbsolute(binary)) {
    throw new Error('CODEX_BIN must be a command on PATH or an absolute executable path');
  }
  // The provider starts from a temporary cwd, so repo-relative entries cannot work.
  const candidates = path.isAbsolute(binary)
    ? [binary]
    : (codex.PATH || '').split(path.delimiter).filter(path.isAbsolute)
      .map(directory => path.join(directory, binary));
  let executable = false;
  for (const candidate of candidates) {
    try {
      if (!(await stat(candidate)).isFile()) continue;
      await access(candidate, constants.X_OK);
      executable = true;
      break;
    } catch { /* Try the next PATH entry without logging its value. */ }
  }
  if (!executable) throw new Error('Codex executable is unavailable; check CODEX_BIN and PATH');

  if (!codex.CODEX_API_KEY) {
    try {
      if (!(await stat(codex.CODEX_HOME!)).isDirectory()) throw new Error();
      await access(codex.CODEX_HOME!, constants.R_OK | constants.W_OK | constants.X_OK);
    } catch {
      throw new Error('Dedicated Codex home is missing or inaccessible; restore its setup before starting');
    }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const loaded = config({ quiet: true });
  try {
    if (loaded.error && (loaded.error as NodeJS.ErrnoException).code !== 'ENOENT') {
      throw new Error('Unable to read .env; check the configuration file permissions');
    }
    await checkStartup(process.env, loaded.parsed);
    console.log('Startup preflight passed (offline checks; login and network still need verification).');
  } catch (error) {
    // checkStartup exposes fixed diagnostics, never raw paths, values or provider errors.
    console.error(`Startup preflight failed: ${(error as Error).message}`);
    process.exitCode = 1;
  }
}
