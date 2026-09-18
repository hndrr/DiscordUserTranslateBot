import {
  ActionRowBuilder,
  Client,
  GatewayIntentBits,
  MessageContextMenuCommandInteraction,
  ModalBuilder,
  ModalSubmitInteraction,
  TextInputBuilder,
  TextInputStyle,
} from 'discord.js';
import { config } from 'dotenv';
import {
  COMMAND_NAMES,
  INSTRUCTION_INPUT_ID,
  INSTRUCTION_MODAL_PREFIX,
} from './commands.js';
import {
  collectMessageContext,
  collectNearbyMessages,
  extractMessageText,
  displayAuthor,
} from './message-content.js';
import {
  draftReply,
  findSimilarMessages,
  findSimilarWithinMessage,
  runInstruction,
  summarizeMessage,
  translateMessage,
} from './translator.js';

config();

const DISCORD_LIMIT = 2000;

const MODAL_CONTEXT_TTL_MS = 15 * 60 * 1000;

type InstructionModalContext = {
  targetText: string;
  contextText: string;
  authorName: string;
  guildId: string | null;
  channelId: string;
  messageId: string;
  userId: string;
  expiresAt: number;
};

/** Prefetched message context for instruction modals (User-Install often cannot REST-fetch channels). */
const instructionModalContext = new Map<string, InstructionModalContext>();

function pruneExpiredModalContexts(now = Date.now()): void {
  for (const [key, value] of instructionModalContext) {
    if (value.expiresAt <= now) instructionModalContext.delete(key);
  }
}

function storeInstructionModalContext(
  customId: string,
  ctx: Omit<InstructionModalContext, 'expiresAt'>,
): void {
  pruneExpiredModalContexts();
  instructionModalContext.set(customId, {
    ...ctx,
    expiresAt: Date.now() + MODAL_CONTEXT_TTL_MS,
  });
}

function takeInstructionModalContext(customId: string): InstructionModalContext | null {
  pruneExpiredModalContexts();
  const ctx = instructionModalContext.get(customId);
  if (!ctx) return null;
  if (ctx.expiresAt <= Date.now()) {
    instructionModalContext.delete(customId);
    return null;
  }
  instructionModalContext.delete(customId);
  return ctx;
}

const intents = [
  GatewayIntentBits.Guilds,
  GatewayIntentBits.GuildMessages,
  GatewayIntentBits.DirectMessages,
];
// Privileged: enable "Message Content Intent" in Discord Developer Portal (Bot → Privileged Gateway Intents).
// Helps 「類似を探す」 fetch nearby history when the bot is also in the guild; User-Install alone often cannot.
// Set DISCORD_MESSAGE_CONTENT_INTENT=0 to skip until the Portal toggle is ON (otherwise Discord closes with "Used disallowed intents").
if (process.env.DISCORD_MESSAGE_CONTENT_INTENT !== '0') {
  intents.push(GatewayIntentBits.MessageContent);
}

const client = new Client({ intents });

client.once('ready', () => {
  console.log(`✅ Bot is ready! Logged in as ${client.user?.tag}`);
  console.log(`📱 User-Install Translation Bot is running`);
});

client.on('interactionCreate', async (interaction) => {
  if (interaction.isModalSubmit()) {
    if (interaction.customId.startsWith(INSTRUCTION_MODAL_PREFIX)) {
      await handleInstructionModal(interaction);
    }
    return;
  }

  if (!interaction.isMessageContextMenuCommand()) return;

  const contextInteraction = interaction as MessageContextMenuCommandInteraction;

  switch (contextInteraction.commandName) {
    case COMMAND_NAMES.TRANSLATE_EN:
      await handleTranslation(contextInteraction, 'en');
      break;
    case COMMAND_NAMES.TRANSLATE_JA:
      await handleTranslation(contextInteraction, 'ja');
      break;
    case COMMAND_NAMES.SUMMARIZE:
      await handleSummarize(contextInteraction);
      break;
    case COMMAND_NAMES.DRAFT_REPLY:
      await handleDraftReply(contextInteraction);
      break;
    case COMMAND_NAMES.FIND_SIMILAR:
      await handleFindSimilar(contextInteraction);
      break;
    case COMMAND_NAMES.RUN_INSTRUCTION:
      await handleRunInstructionMenu(contextInteraction);
      break;
  }
});

function clipForDiscord(text: string, max = DISCORD_LIMIT): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + '…';
}

/** customId: instr:{channelId}:{messageId}:{userId} — must stay ≤ 100 chars. */
function buildInstructionModalCustomId(
  channelId: string,
  messageId: string,
  userId: string,
): string {
  const id = `${INSTRUCTION_MODAL_PREFIX}${channelId}:${messageId}:${userId}`;
  if (id.length > 100) {
    throw new Error(`Modal customId too long (${id.length} > 100)`);
  }
  return id;
}

function parseInstructionModalCustomId(customId: string): {
  channelId: string;
  messageId: string;
  userId: string;
} | null {
  if (!customId.startsWith(INSTRUCTION_MODAL_PREFIX)) return null;
  const rest = customId.slice(INSTRUCTION_MODAL_PREFIX.length);
  const parts = rest.split(':');
  if (parts.length !== 3) return null;
  const [channelId, messageId, userId] = parts;
  if (!channelId || !messageId || !userId) return null;
  return { channelId, messageId, userId };
}

async function handleTranslation(
  interaction: MessageContextMenuCommandInteraction,
  targetLanguage: string,
) {
  await interaction.deferReply({ ephemeral: true });

  try {
    const message = interaction.targetMessage;
    const originalText = message.content;

    if (!originalText) {
      await interaction.editReply('❌ このメッセージには翻訳可能なテキストがありません。');
      return;
    }

    const languageName = targetLanguage === 'ja' ? '日本語' : '英語';
    const translation = await translateMessage(originalText, targetLanguage);

    await interaction.editReply({
      content: clipForDiscord(
        `**🌐 ${languageName}翻訳:**\n${translation}\n\n*元のメッセージ:* ${originalText.substring(0, 100)}${originalText.length > 100 ? '...' : ''}`,
      ),
    });
  } catch (error) {
    console.error('Translation error:', error);
    await interaction.editReply('❌ 翻訳中にエラーが発生しました。');
  }
}

async function handleSummarize(interaction: MessageContextMenuCommandInteraction) {
  await interaction.deferReply({ ephemeral: true });

  try {
    const { targetText, contextText, authorName } = await collectMessageContext(
      interaction.targetMessage,
    );

    if (!targetText) {
      await interaction.editReply(
        '❌ このメッセージには要約できるテキストがありません。（本文・埋め込み・添付が空です）',
      );
      return;
    }

    const summary = await summarizeMessage({ targetText, contextText, authorName });
    await interaction.editReply({
      content: clipForDiscord(`**📝 要約**\n${summary}`),
    });
  } catch (error) {
    console.error('Summarize error:', error);
    await interaction.editReply('❌ 要約の生成中にエラーが発生しました。');
  }
}

function formatDraftReply(japanese: string, english: string): string {
  const header = '**💬 返信ドラフト**\n\n';
  const jaHeader = '**日本語**\n';
  let ja = japanese.trim();
  let en = english.trim();
  const enHeader = en ? '\n\n**English**\n' : '';
  const overhead = header.length + jaHeader.length + enHeader.length;
  const budget = DISCORD_LIMIT - overhead;

  if (ja.length + en.length > budget) {
    if (!en) {
      if (ja.length > budget) ja = ja.slice(0, Math.max(1, budget) - 1) + '…';
    } else {
      const half = Math.max(1, Math.floor(budget / 2));
      if (ja.length > half) ja = ja.slice(0, half - 1) + '…';
      const enBudget = budget - ja.length;
      if (en.length > enBudget) en = en.slice(0, Math.max(1, enBudget) - 1) + '…';
    }
  }

  return `${header}${jaHeader}${ja}${enHeader}${en}`;
}

async function handleDraftReply(interaction: MessageContextMenuCommandInteraction) {
  await interaction.deferReply({ ephemeral: true });

  try {
    const { targetText, contextText, authorName } = await collectMessageContext(
      interaction.targetMessage,
    );

    if (!targetText) {
      await interaction.editReply(
        '❌ このメッセージには返信ドラフトを作れるテキストがありません。（本文・埋め込み・添付が空です）',
      );
      return;
    }

    const draft = await draftReply({ targetText, contextText, authorName });
    await interaction.editReply({
      content: formatDraftReply(draft.japanese, draft.english),
    });
  } catch (error) {
    console.error('Draft reply error:', error);
    await interaction.editReply('❌ 返信ドラフトの生成中にエラーが発生しました。');
  }
}

async function handleFindSimilar(interaction: MessageContextMenuCommandInteraction) {
  await interaction.deferReply({ ephemeral: true });

  try {
    const message = interaction.targetMessage;
    const { targetText, authorName, lines, historyUnavailable } =
      await collectNearbyMessages(message);

    if (!targetText) {
      await interaction.editReply(
        '❌ このメッセージには類似検索できるテキストがありません。（本文・埋め込み・添付が空です）',
      );
      return;
    }

    const candidates = lines.filter((l) => !l.isTarget);
    if (historyUnavailable || candidates.length === 0) {
      // User-Install often cannot fetch channel history — fall back like 「指示して実行」
      // on the single selected message (+ reply-chain context when available).
      const { targetText: ctxTarget, contextText, authorName: ctxAuthor } =
        await collectMessageContext(message);
      const fallbackTarget = ctxTarget || targetText;
      const fallbackAuthor = ctxAuthor || authorName;
      const result = await findSimilarWithinMessage({
        targetText: fallbackTarget,
        contextText:
          contextText || `[対象] ${fallbackAuthor}: ${fallbackTarget}`,
        authorName: fallbackAuthor,
      });
      const note =
        '\n\n_チャンネル履歴が読めないためメッセージ内の関連整理です。サーバーにBotを入れると投稿横断の類似検索ができます。_';
      await interaction.editReply({
        content: clipForDiscord(`**🔍 類似を探す**\n\n${result}${note}`),
      });
      return;
    }

    const matches = await findSimilarMessages({
      targetText,
      authorName,
      lines,
      guildId: message.guildId,
      channelId: message.channelId,
    });

    if (matches.length === 0) {
      await interaction.editReply(
        'ℹ️ 同じ意図のメッセージは見つかりませんでした。',
      );
      return;
    }

    const items = matches.map((m, i) => {
      return `${i + 1}. **${m.author}**: ${m.snippet}\n   → ${m.url}`;
    });
    const body = `**🔍 類似を探す**（${matches.length}件）\n\n${items.join('\n\n')}`;
    await interaction.editReply({ content: clipForDiscord(body) });
  } catch (error) {
    console.error('Find similar error:', error);
    await interaction.editReply('❌ 類似メッセージの検索中にエラーが発生しました。');
  }
}

/** First response MUST be showModal (no defer). */
async function handleRunInstructionMenu(
  interaction: MessageContextMenuCommandInteraction,
) {
  try {
    const message = interaction.targetMessage;
    const customId = buildInstructionModalCustomId(
      message.channelId,
      message.id,
      interaction.user.id,
    );

    // Prefetch before showModal — User-Install often cannot REST-fetch the channel later.
    const { targetText, contextText, authorName } = await collectMessageContext(message);
    storeInstructionModalContext(customId, {
      targetText,
      contextText,
      authorName,
      guildId: message.guildId,
      channelId: message.channelId,
      messageId: message.id,
      userId: interaction.user.id,
    });

    const modal = new ModalBuilder()
      .setCustomId(customId)
      .setTitle('指示して実行');

    const input = new TextInputBuilder()
      .setCustomId(INSTRUCTION_INPUT_ID)
      .setLabel('指示内容')
      .setStyle(TextInputStyle.Paragraph)
      .setPlaceholder('例: 似た質問探して / 丁寧に言い換えて / 論点だけ3つ')
      .setRequired(true)
      .setMinLength(1)
      .setMaxLength(1000);

    modal.addComponents(
      new ActionRowBuilder<TextInputBuilder>().addComponents(input),
    );

    await interaction.showModal(modal);
  } catch (error) {
    console.error('Show instruction modal error:', error);
    // showModal is the first response — if it failed we may still reply once
    if (interaction.replied || interaction.deferred) {
      await interaction.followUp({
        content: '❌ モーダルの表示に失敗しました。',
        ephemeral: true,
      });
    } else {
      await interaction.reply({
        content: '❌ モーダルの表示に失敗しました。',
        ephemeral: true,
      });
    }
  }
}

async function handleInstructionModal(interaction: ModalSubmitInteraction) {
  await interaction.deferReply({ ephemeral: true });

  try {
    const parsed = parseInstructionModalCustomId(interaction.customId);
    if (!parsed) {
      await interaction.editReply('❌ モーダル情報が不正です。');
      return;
    }

    if (interaction.user.id !== parsed.userId) {
      await interaction.editReply('❌ このモーダルはあなた専用です。');
      return;
    }

    const instruction = interaction.fields.getTextInputValue(INSTRUCTION_INPUT_ID).trim();
    if (!instruction) {
      await interaction.editReply('❌ 指示が空です。');
      return;
    }

    // Prefer prefetched context (User-Install often cannot client.channels.fetch).
    let targetText = '';
    let contextText = '';
    let authorName = '';

    const cached = takeInstructionModalContext(interaction.customId);
    if (cached) {
      targetText = cached.targetText;
      contextText = cached.contextText;
      authorName = cached.authorName;
    } else {
      // Optional fallback: interaction.channel if it exposes messages (no client.channels.fetch).
      try {
        const channel = interaction.channel;
        if (channel && 'messages' in channel && channel.messages) {
          const message = await channel.messages.fetch(parsed.messageId);
          const collected = await collectMessageContext(message);
          targetText = collected.targetText || extractMessageText(message);
          contextText = collected.contextText;
          authorName = collected.authorName || displayAuthor(message);
        }
      } catch (error) {
        console.warn('Instruction modal optional channel fetch failed:', error);
      }

      if (!targetText) {
        await interaction.editReply(
          '❌ User Install ではチャンネルを再取得できないことがあります。\n' +
            '右クリックメニューから「指示して実行」をもう一度開き直してください。',
        );
        return;
      }
    }

    const text = targetText;
    if (!text) {
      await interaction.editReply(
        '❌ このメッセージには実行できるテキストがありません。（本文・埋め込み・添付が空です）',
      );
      return;
    }

    const result = await runInstruction({
      instruction,
      targetText: text,
      contextText: contextText || `[対象] ${authorName || 'unknown'}: ${text}`,
      authorName: authorName || 'unknown',
    });

    await interaction.editReply({
      content: clipForDiscord(`**⚡ 指示して実行**\n\n${result}`),
    });
  } catch (error) {
    console.error('Instruction modal error:', error);
    await interaction.editReply('❌ 指示の実行中にエラーが発生しました。');
  }
}

const token = process.env.DISCORD_TOKEN;
if (!token) {
  console.error('❌ DISCORD_TOKEN is not set in .env file');
  process.exit(1);
}

client.login(token);
