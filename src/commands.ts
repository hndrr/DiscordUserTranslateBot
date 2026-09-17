export const COMMAND_NAMES = {
  TRANSLATE_EN: 'Translate to English',
  TRANSLATE_JA: 'Translate to Japanese',
  SUMMARIZE: '要約',
  DRAFT_REPLY: '返信ドラフト',
  FIND_SIMILAR: '類似を探す',
  RUN_INSTRUCTION: '指示して実行',
} as const;

/** Modal customId prefix for 「指示して実行」. Format: instr:{channelId}:{messageId}:{userId} */
export const INSTRUCTION_MODAL_PREFIX = 'instr:';
export const INSTRUCTION_INPUT_ID = 'instruction';
