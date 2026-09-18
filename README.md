# Discord User-Install Translation Bot

Discord上でメッセージを右クリックして簡単に翻訳できるUser-Install対応のBotです。Cursor SDKを使用してAI翻訳を実行します。

## ⚠️ 重要な注意事項

**各自で専用のDiscord ApplicationとCursor API Keyを作成すること。**

- 他人のBotをインストールしない
- インストールリンクを共有しない
- トークン・APIキーを共有しない

## 機能

- 📱 **User-Install対応**: サーバー管理者権限不要で、個人アカウントにインストール可能
- 🌐 **メッセージコンテキストメニュー翻訳**: 
  - 「Translate to English」- 英語に翻訳
  - 「Translate to Japanese」- 日本語に翻訳
- 📝 **要約**: 「要約」で選択したメッセージを短く日本語要約。スレッドや返信チェーンがある場合は、前後の文脈（直近十数件／約4,000文字まで）も踏まえます
- 💬 **返信ドラフト**: 「返信ドラフト」で返信案を生成。日本語と英語の対訳つき
- 🔍 **類似を探す**: 周辺メッセージから同じ意図の投稿を探し、作者・短い抜粋・ジャンプリンクを一覧表示
- ⚡ **指示して実行**: モーダルに自由指示（例: 似た質問探して / 丁寧に言い換えて / 論点だけ3つ）を入力して実行
- 🤖 **Cursor SDK統合**: Composer 2.5モデルを使用した高品質な翻訳・要約・下書き・類似検索・指示実行
- 🔒 **プライベート応答**: 結果は自分だけに表示されます（ephemeral）

## 必要要件

- Node.js >= 22.13.0
- Discord Developer Account
- Cursor API Key

## 実行環境の選び方

このBotは以下の2つの方法で実行できます：

### 💡 A. Grok Bot のコンピュータで実行（推奨）

Grok Botのアシスタント（例：「Discord翻訳」）を利用している場合、アシスタントのLinux VM上でBotを常時起動できます。

**メリット：**
- ✅ 自分のPCを起動したままにする必要がない
- ✅ Botが24時間稼働し続ける
- ✅ セットアップをアシスタントに任せられる

**セットアップの流れ:**  
詳しくは下記の [A. Grok Bot のコンピュータでの実行手順](#a-grok-bot-のコンピュータでの実行手順) をご覧ください。

### 🖥️ B. ローカルPCで実行

従来通り、自分のMac/Windows/Linux PCでBotを実行できます。

**メリット：**
- ✅ 自分のPC環境で直接管理できる
- ✅ 開発・カスタマイズがしやすい

**セットアップの流れ:**  
詳しくは下記の [B. ローカルPCでの実行手順](#b-ローカルpcでの実行手順) をご覧ください。

---

## セットアップ手順

### 共通: Discord Applicationの作成

**※この手順はどちらの実行環境でも必要です。ブラウザで実施してください。**

### 1. Discord Applicationの作成

1. [Discord Developer Portal](https://discord.com/developers/applications)にアクセス
2. 「New Application」をクリックして新しいアプリケーションを作成
3. 「Bot」タブに移動し、Botを作成
4. 「TOKEN」をコピー（後で使用します）
5. 同じ「Bot」タブの **Privileged Gateway Intents** で **Message Content Intent** を ON にする（「類似を探す」で周辺履歴を読むために必要。User Install のみでは読めないことが多い）
   - 有効化前に Bot を起動すると `Used disallowed intents` で落ちます。一時的に `DISCORD_MESSAGE_CONTENT_INTENT=0` でスキップ可能
6. 「OAuth2」→「General」タブで「APPLICATION ID」をコピー
7. 「Installation」タブで以下を設定:
   - **Installation Contexts**: `User Install` にチェック
   - **Install Link**: `Discord Provided Link` を選択
   - **Default Install Settings**: 
     - Scopes: `applications.commands`
     - Permissions: 不要（User Installの場合）

### 2. Cursor API Keyの取得

**※この手順もどちらの実行環境でも必要です。ブラウザで実施してください。**

1. [Cursor Settings](https://cursor.com/settings)にアクセス
2. API Keyを生成してコピー

---

## A. Grok Bot のコンピュータでの実行手順

Grok Botアシスタント（例：「Discord翻訳」や他のGrok Bot）に以下のようにお願いすることで、アシスタントのLinux VM上でBotをセットアップ・起動できます。

### 1. アシスタントにセットアップを依頼

Grok Botとの会話で、次のようにお願いしてください：

```
https://github.com/hndrr/DiscordUserTranslateBot をあなたのコンピュータにクローンして、
セットアップして起動してください。
```

アシスタントは以下を自動的に実行します：

1. リポジトリをVM上にクローン
2. Node.js >= 22.13.0 が利用可能か確認（必要に応じてインストール）
3. `npm install` で依存関係をインストール
4. 環境変数（`.env`）の設定を要求

### 2. 環境変数を安全に提供

アシスタントから環境変数の入力を求められたら、以下の情報を**安全な方法**で提供してください：

```
DISCORD_TOKEN=（Discord Developer Portalで取得したBotトークン）
DISCORD_APPLICATION_ID=（あなたのApplication ID）
CURSOR_API_KEY=（あなたのCursor APIキー）
```

⚠️ **重要**: これらのトークンやキーは、会話ログに平文で残らないよう、アシスタントが提供するセキュアな入力方法（マスク入力やVM上の環境変数設定）を使用してください。チャット画面にそのまま貼り付けないでください。

### 3. コマンドのデプロイと起動

アシスタントに以下を依頼してください：

```
npm run deploy を実行してDiscordコマンドを登録してください。
その後、run-forever.sh を使ってBotをバックグラウンドで起動してください。
```

アシスタントが以下を実行します：

```bash
npm run deploy          # Discordコマンドを登録
chmod +x run-forever.sh
./run-forever.sh        # バックグラウンドで永続起動
```

### 4. Bot の動作確認

1. Discord Developer PortalのInstallationタブからインストールリンクを取得
2. 自分のDiscordアカウントにBotをインストール
3. 任意のメッセージを右クリックして「Apps」からコマンドを選択
   - 「Translate to English」/「Translate to Japanese」: 翻訳
   - 「要約」: 日本語の短い要約
   - 「返信ドラフト」: 日本語・英語の返信案
   - 「類似を探す」: 同じ意図の周辺メッセージ一覧
   - 「指示して実行」: モーダルに指示を入れて実行
4. 結果が自分だけに表示されることを確認

### 5. ログの確認・再起動

Botが正常に動作しているか確認したい場合や、再起動したい場合は、アシスタントに以下のようにお願いしてください：

```
Discord翻訳Botのログを確認してください
```

```
Discord翻訳Botを再起動してください
```

アシスタントがVM上でプロセスの状態確認やログ表示、再起動を実行します。

---

## B. ローカルPCでの実行手順

### 1. プロジェクトのセットアップ

```bash
# リポジトリをクローン
git clone https://github.com/hndrr/DiscordUserTranslateBot.git
cd DiscordUserTranslateBot

# 依存関係のインストール
npm install

# 環境変数の設定
cp .env.example .env
```

### 2. 環境変数の設定

`.env`ファイルを編集して、以下の値を設定します：

```env
DISCORD_TOKEN=あなたのDiscord Botトークン
DISCORD_APPLICATION_ID=あなたのApplication ID
CURSOR_API_KEY=あなたのCursor APIキー
```

### 3. コマンドのデプロイ

```bash
npm run deploy
```

### 4. Botの起動

```bash
# 通常起動
npm start

# 開発モード（ホットリロード）
npm run dev

# 永続実行（再起動機能付き）
chmod +x run-forever.sh
./run-forever.sh
```

### 5. Bot の動作確認

1. Discord Developer PortalのInstallationタブからインストールリンクを取得
2. 自分のDiscordアカウントにBotをインストール
3. 任意のメッセージを右クリック
4. 「Apps」から「Translate to English」「Translate to Japanese」「要約」「返信ドラフト」「類似を探す」「指示して実行」のいずれかを選択
5. 結果が自分だけに表示されます

---

## 使い方

インストール後は、どちらの実行環境でも以下の手順で利用できます：

1. Discord上の任意のメッセージを右クリック
2. 「Apps」から使いたいメニューを選択
   - **Translate to English** / **Translate to Japanese** — 翻訳
   - **要約** — 選択メッセージの短い日本語要約（スレッド／返信なら前後の文脈も参照）
   - **返信ドラフト** — そのメッセージへの返信案。日本語と英語の対訳を表示
   - **類似を探す** — チャンネル／スレッドの周辺メッセージ（最大約100件）から同じ意図の投稿を探し、作者・短い抜粋・ジャンプリンクを ephemeral で一覧表示（**Message Content Intent** とサーバー招待があると安定）
   - **指示して実行** — まずモーダルが開き、自由な指示（例: 似た質問探して / 丁寧に言い換えて / 論点だけ3つ）を入力。送信後に対象メッセージと文脈を踏まえて実行し、結果を ephemeral で返す（2000文字まで）
3. 結果は自分だけに表示されます（他のユーザーには見えません）

## プロジェクト構造

```
.
├── src/
│   ├── index.ts           # Botのメインファイル
│   ├── commands.ts        # コンテキストメニュー名
│   ├── deploy-commands.ts # コマンド登録スクリプト
│   ├── message-content.ts # 本文抽出・スレッド／返信の文脈収集
│   └── translator.ts      # Cursor SDK（翻訳・要約・返信ドラフト）
├── package.json           # 依存関係とスクリプト
├── tsconfig.json          # TypeScript設定
├── .env.example           # 環境変数テンプレート
├── run-forever.sh         # 永続実行スクリプト
└── README.md              # このファイル
```

## 技術スタック

- **Discord.js v14**: Discord API インタラクション
- **Cursor SDK**: AI翻訳・要約・返信ドラフト・類似検索・指示実行（Composer 2.5モデル）
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

### 「類似を探す」で履歴が読めない / 候補が空

User Install だけではチャンネル履歴を REST / Gateway から取得できないことが多くあります。

- Discord Developer Portal → Bot → **Message Content Intent** を ON
- 可能なら Bot を対象サーバーにも入れる（Guild メンバーシップがあると履歴取得が改善しやすい）
- 単一メッセージの処理なら「要約」や「指示して実行」を使う

### 「指示して実行」で Missing Access

モーダル表示時にメッセージ文脈をキャッシュするため、再取得は不要です。古いデプロイで `Missing Access` が出る場合は最新版に更新し、メニューから開き直してください。

## セキュリティに関する注意

- ⚠️ `.env`ファイルは絶対にGitにコミットしないでください
- ⚠️ トークンやAPIキーは他人と共有しないでください
- ⚠️ Botのインストールリンクを公開しないでください

## ライセンス

MIT

## サポート

問題が発生した場合は、GitHubのIssuesで報告してください。
