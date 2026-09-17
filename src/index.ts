import { Client, GatewayIntentBits, ApplicationCommandType, MessageContextMenuCommandInteraction } from 'discord.js';
import { config } from 'dotenv';
import { translateMessage } from './translator.js';

config();

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

  if (contextInteraction.commandName === 'Translate to English') {
    await handleTranslation(contextInteraction, 'en');
  } else if (contextInteraction.commandName === 'Translate to Japanese') {
    await handleTranslation(contextInteraction, 'ja');
  }
});

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
      content: `**🌐 ${languageName}翻訳:**\n${translation}\n\n*元のメッセージ:* ${originalText.substring(0, 100)}${originalText.length > 100 ? '...' : ''}`,
    });
  } catch (error) {
    console.error('Translation error:', error);
    await interaction.editReply('❌ 翻訳中にエラーが発生しました。');
  }
}

const token = process.env.DISCORD_TOKEN;
if (!token) {
  console.error('❌ DISCORD_TOKEN is not set in .env file');
  process.exit(1);
}

client.login(token);
