#!/bin/bash

# Discord User-Install Translation Bot - Run Forever Script
# このスクリプトはBotをバックグラウンドで永続的に実行します

echo "🚀 Starting Discord User-Install Translation Bot..."

# .envファイルの存在確認
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please copy .env.example to .env and configure your tokens."
    exit 1
fi

# node_modulesの存在確認
if [ ! -d node_modules ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

# コマンドのデプロイ
echo "📝 Deploying commands..."
npm run deploy

# Botの起動（永続実行）
echo "✅ Bot is starting..."
while true; do
    npm start
    echo "⚠️ Bot stopped. Restarting in 5 seconds..."
    sleep 5
done
