import { REST, Routes, ApplicationCommandType } from 'discord.js';
import { config } from 'dotenv';

config();

const commands = [
  {
    name: 'Translate to English',
    type: ApplicationCommandType.Message,
    integration_types: [0, 1],
    contexts: [0, 1, 2],
  },
  {
    name: 'Translate to Japanese',
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
  } catch (error) {
    console.error('❌ Error deploying commands:', error);
  }
})();
