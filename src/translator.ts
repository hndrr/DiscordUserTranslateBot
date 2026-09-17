import { Agent } from '@cursor/sdk';
import { config } from 'dotenv';

config();

const apiKey = process.env.CURSOR_API_KEY;
if (!apiKey) {
  console.error('❌ CURSOR_API_KEY is not set in .env file');
  process.exit(1);
}

export async function translateMessage(text: string, targetLanguage: string): Promise<string> {
  const languageName = targetLanguage === 'ja' ? 'Japanese' : 'English';
  
  const prompt = `Translate the following text to ${languageName}. 
Only output the translated text, nothing else. Do not include any explanations or notes.

Text to translate:
${text}`;

  try {
    const result = await Agent.prompt({
      apiKey,
      model: 'composer-2',
      prompt,
      temperature: 0.3,
    });

    return result.trim();
  } catch (error) {
    console.error('Cursor SDK error:', error);
    throw new Error('Translation failed');
  }
}
