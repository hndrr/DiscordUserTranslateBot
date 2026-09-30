/** Resolve only bot-owned Codex settings, without overriding Discord secrets. */
export function resolveBotCodexEnvironment(
  env: NodeJS.ProcessEnv,
  fileValues: Record<string, string> = {},
): NodeJS.ProcessEnv {
  return {
    ...env,
    // An assistant host may inject its own CODEX_HOME. Never silently use it.
    // Keep .env CODEX_HOME compatible, and prefer the unambiguous bot-specific key.
    CODEX_HOME: env.DISCORD_CODEX_HOME || fileValues.DISCORD_CODEX_HOME || fileValues.CODEX_HOME,
    CODEX_API_KEY: env.DISCORD_CODEX_API_KEY || fileValues.CODEX_API_KEY,
    // Explicit settings in the bot's file take precedence over host defaults.
    CODEX_MODEL: fileValues.CODEX_MODEL || env.CODEX_MODEL,
    CODEX_REASONING_EFFORT: fileValues.CODEX_REASONING_EFFORT || env.CODEX_REASONING_EFFORT,
  };
}
