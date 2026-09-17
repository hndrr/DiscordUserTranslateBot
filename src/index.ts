import { Client, GatewayIntentBits, MessageContextMenuCommandInteraction } from 'discord.js';
import { config } from 'dotenv';
import { COMMAND_NAMES } from './commands.js';
import { collectMessageContext } from './message-content.js';
import { draftReply, summarizeMessage, translateMessage } from './translator.js';

config();

const DISCORD_LIMIT = 2000;

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.DirectMessages,
  ],
});

client.once('ready', () => {
  console.log(`✅ Bot is ready! Logged in as ${client.user?.tag}`);
  console.log(`📱 User-Install Translation Bot is running`);
});

client.on('interactionCreate', async (interaction) => {
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
  }
});

function clipForDiscord(text: string, max = DISCORD_LIMIT): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + '…';
}

async function handleTranslation(
  interaction: MessageContextMenuCommandInteraction,
  targetLanguage: string
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
  const enHeader = '\n\n**English**\n';
  const overhead = header.length + jaHeader.length + enHeader.length;
  const budget = DISCORD_LIMIT - overhead;

  let ja = japanese.trim();
  let en = english.trim();
  if (ja.length + en.length > budget) {
    const half = Math.max(1, Math.floor(budget / 2));
    if (ja.length > half) ja = ja.slice(0, half - 1) + '…';
    const enBudget = budget - ja.length;
    if (en.length > enBudget) en = en.slice(0, Math.max(1, enBudget) - 1) + '…';
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

const token = process.env.DISCORD_TOKEN;
if (!token) {
  console.error('❌ DISCORD_TOKEN is not set in .env file');
  process.exit(1);
}

client.login(token);
