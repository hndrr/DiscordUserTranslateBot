import { REST, Routes, ApplicationCommandType } from 'discord.js';
import { config } from 'dotenv';
import { COMMAND_NAMES } from './commands.js';

config();

const commands = [
  {
    name: COMMAND_NAMES.TRANSLATE_EN,
    type: ApplicationCommandType.Message,
    integration_types: [0, 1],
    contexts: [0, 1, 2],
  },
  {
    name: COMMAND_NAMES.TRANSLATE_JA,
    type: ApplicationCommandType.Message,
    integration_types: [0, 1],
    contexts: [0, 1, 2],
  },
  {
    name: COMMAND_NAMES.SUMMARIZE,
    type: ApplicationCommandType.Message,
    integration_types: [0, 1],
    contexts: [0, 1, 2],
  },
  {
    name: COMMAND_NAMES.DRAFT_REPLY,
    type: ApplicationCommandType.Message,
    integration_types: [0, 1],
    contexts: [0, 1, 2],
  },
  {
    name: COMMAND_NAMES.FIND_SIMILAR,
    type: ApplicationCommandType.Message,
    integration_types: [0, 1],
    contexts: [0, 1, 2],
  },
  {
    name: COMMAND_NAMES.RUN_INSTRUCTION,
    type: ApplicationCommandType.Message,
    integration_types: [0, 1],
    contexts: [0, 1, 2],
  },
];

const token = process.env.DISCORD_TOKEN;
const applicationId = process.env.DISCORD_APPLICATION_ID;

if (!token || !applicationId) {
  console.error('❌ DISCORD_TOKEN and DISCORD_APPLICATION_ID must be set in .env file');
  process.exit(1);
}

const rest = new REST({ version: '10' }).setToken(token);

(async () => {
  try {
    console.log('🚀 Started refreshing application commands...');

    await rest.put(Routes.applicationCommands(applicationId), {
      body: commands,
    });

    console.log('✅ Successfully registered application commands!');
    console.log('📱 Commands are available as User-Install context menus');
    console.log(Object.values(COMMAND_NAMES).map((name) => `  - ${name}`).join('\n'));
  } catch (error) {
    console.error('❌ Error deploying commands:', error);
  }
})();
