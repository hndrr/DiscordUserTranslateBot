# Discord User-Install Translation Bot

Discord上でメッセージを右クリックして簡単に翻訳できるUser-Install対応のBotです。Cursor SDKを使用してAI翻訳を実行します。

## ⚠️ 重要な注意事項

**このBotを使用するには、各自が必ず自分専用のDiscord ApplicationとCursor API Keyを作成する必要があります。**

- ❌ 他の人が作成したBotをインストールしないでください
- ❌ 他の人のインストールリンクを共有しないでください
- ❌ トークンやAPIキーを絶対に共有しないでください

各ユーザーが以下の手順に従って、自分専用のBotを作成してください。

## 機能

- 📱 **User-Install対応**: サーバー管理者権限不要で、個人アカウントにインストール可能
- 🌐 **メッセージコンテキストメニュー翻訳**: 
  - 「Translate to English」- 英語に翻訳
  - 「Translate to Japanese」- 日本語に翻訳
- 🤖 **Cursor SDK統合**: Composer-2モデルを使用した高品質な翻訳
- 💬 **プライベート応答**: 翻訳結果は自分だけに表示されます

## 必要要件

- Node.js >= 22.13.0
- Discord Developer Account
- Cursor API Key

## セットアップ手順

### 1. Discord Applicationの作成

1. [Discord Developer Portal](https://discord.com/developers/applications)にアクセス
2. 「New Application」をクリックして新しいアプリケーションを作成
3. 「Bot」タブに移動し、Botを作成
4. 「TOKEN」をコピー（後で使用します）
5. 「OAuth2」→「General」タブで「APPLICATION ID」をコピー
6. 「Installation」タブで以下を設定:
   - **Installation Contexts**: `User Install` にチェック
   - **Install Link**: `Discord Provided Link` を選択
   - **Default Install Settings**: 
     - Scopes: `applications.commands`
     - Permissions: 不要（User Installの場合）

### 2. Cursor API Keyの取得

1. [Cursor Settings](https://cursor.com/settings)にアクセス
2. API Keyを生成してコピー

### 3. プロジェクトのセットアップ

```bash
# リポジトリをクローン
git clone https://github.com/hndrr/DiscordUserTranslateBot.git
cd DiscordUserTranslateBot

# 依存関係のインストール
npm install

# 環境変数の設定
cp .env.example .env
```

### 4. 環境変数の設定

`.env`ファイルを編集して、以下の値を設定します：

```env
DISCORD_TOKEN=あなたのDiscord Botトークン
DISCORD_APPLICATION_ID=あなたのApplication ID
CURSOR_API_KEY=あなたのCursor APIキー
```

### 5. コマンドのデプロイ

```bash
npm run deploy
```

### 6. Botの起動

```bash
# 通常起動
npm start

# 開発モード（ホットリロード）
npm run dev

# 永続実行（再起動機能付き）
chmod +x run-forever.sh
./run-forever.sh
```

## 使い方

1. Discord Developer PortalのInstallationタブからインストールリンクを取得
2. 自分のDiscordアカウントにBotをインストール
3. 任意のメッセージを右クリック
4. 「Apps」→「Translate to English」または「Translate to Japanese」を選択
5. 翻訳結果が自分だけに表示されます

## プロジェクト構造

```
.
├── src/
│   ├── index.ts           # Botのメインファイル
│   ├── deploy-commands.ts # コマンド登録スクリプト
│   └── translator.ts      # Cursor SDK翻訳機能
├── package.json           # 依存関係とスクリプト
├── tsconfig.json          # TypeScript設定
├── .env.example           # 環境変数テンプレート
├── run-forever.sh         # 永続実行スクリプト
└── README.md              # このファイル
```

## 技術スタック

- **Discord.js v14**: Discord API インタラクション
- **Cursor SDK**: AI翻訳エンジン（Composer-2モデル）
- **TypeScript**: 型安全な開発
- **tsx**: TypeScript実行環境

## トラブルシューティング

### Botが起動しない

- `.env`ファイルが正しく設定されているか確認
- `DISCORD_TOKEN`と`DISCORD_APPLICATION_ID`が正しいか確認
- Node.jsのバージョンが22.13以上か確認

### コマンドが表示されない

- `npm run deploy`を実行してコマンドを再デプロイ
- Discordを再起動
- BotがUser Installとして正しくインストールされているか確認

### 翻訳が動作しない

- `CURSOR_API_KEY`が正しく設定されているか確認
- Cursor APIの利用可能クレジットがあるか確認
- コンソールログでエラーメッセージを確認

## セキュリティに関する注意

- ⚠️ `.env`ファイルは絶対にGitにコミットしないでください
- ⚠️ トークンやAPIキーは他人と共有しないでください
- ⚠️ Botのインストールリンクを公開しないでください

## ライセンス

MIT

## サポート

問題が発生した場合は、GitHubのIssuesで報告してください。
