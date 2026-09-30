# Discord User-Install Translation Bot

Discord のメッセージを右クリックして翻訳・要約・返信案を作る、公式 Discord Application 用 Bot です。**Codex CLI をバックグラウンドで呼び出すバックエンド**と、既存の Cursor SDK バックエンドを選べます。Discord 個人アカウントのトークンを使う selfbot ではありません。

## 機能

- **Translate to English / Translate to Japanese**: 選択したメッセージを翻訳
- **要約**: スレッド／返信の文脈を踏まえ、短く日本語要約
- **返信ドラフト**: 日本語と英語の返信案を生成。自動送信はしません
- **類似を探す**: 読み取れる周辺履歴から似た意図の投稿を探し、作者・抜粋・リンクを表示。履歴が取れなければメッセージ内の関連整理にフォールバック
- **指示して実行**: モーダルの指示で文章を変換。シェル実行やファイル操作の機能ではありません
- 結果は呼び出した本人だけに表示する **ephemeral 応答**

## 必要なもの

- Node.js **22.13 以上**（Cursor SDK の `node:sqlite` 要件も維持）
- 自分で管理する Discord Application の **Bot token** と Application ID
- Codex モード: 対応する Codex CLI と、この Bot 専用の認証環境
- Cursor モード: Cursor API key
- 常時稼働したい場合: 電源・ネットワーク・実行環境が維持されるホスト

## 1. Discord Application

[Developer Portal](https://discord.com/developers/applications) で Application を作成します。

1. Bot タブで Bot token を取得。チャットや Git に貼り付けず、安全な秘密情報入力で保存します
2. Application ID を控えます
3. Installation → Installation Contexts で **User Install** を有効化
4. Install Link は **Discord Provided Link**、User Install の scope は `applications.commands`
5. 取得したリンクから自分の Discord アカウントにインストール

周辺の投稿履歴を読むには、Bot が対象サーバーにも参加し、適切な権限を持つ必要があります。必要な場合のみ Portal の **Message Content Intent** を有効化し、`DISCORD_MESSAGE_CONTENT_INTENT=1` にしてください。未設定では `0` のままで利用できます。Intent が許可されていないのに要求すると `Used disallowed intents` で切断されます。

## 2. インストール

```bash
git clone https://github.com/hndrr/DiscordUserTranslateBot.git
cd DiscordUserTranslateBot
npm ci
cp .env.example .env
```

`.env` に `DISCORD_TOKEN` と `DISCORD_APPLICATION_ID` を安全に設定します。秘密情報は `.env.example` やコマンド引数、会話ログに書かないでください。

## 3. AI バックエンド

### Codex CLI

[公式セットアップ](https://learn.chatgpt.com/docs/cli) に従って Codex CLI を用意します。

```env
AI_PROVIDER=codex
CODEX_BIN=codex
CODEX_HOME=/absolute/path/to/dedicated-discord-codex-home
CODEX_TIMEOUT_MS=120000
CODEX_MAX_CONCURRENCY=2
# CODEX_MODEL=利用可能なモデル名
```

- Bot 専用 OS ユーザー／コンテナと、**新しい専用 CODEX_HOME** を推奨します。その環境でユーザー自身が通常の `codex login` を行ってください。既存の認証ファイルをコピーしないでください
- 例: `CODEX_HOME=/absolute/path/to/dedicated-discord-codex-home codex login`。認証はサービス実行ユーザーで行い、サービスにも同じ絶対パスを設定します
- 通常のコーディング用 Codex home は使わないでください。保存済みの指示や skill 情報がモデルに送られる可能性があります。`AGENTS.md`、`AGENTS.override.md`、独自の `skills`、`memories` / `memories_v2` がある home は拒否します。CLI が生成する組み込み `skills/.system` は許可します
- 別案として `CODEX_API_KEY` を秘密情報として設定すると、リクエストごとに空の一時 CODEX_HOME を使います。この場合 `CODEX_HOME` の指定や保存済みログインは不要です。API の利用料金は契約に従って発生します
- CLI は認証情報を通常の仕組みで参照します。Bot が認証ファイルを読み出したりコピーしたりすることはありません
- `CODEX_MODEL` 未指定なら CLI の既定モデルを使います。ユーザーの `config.toml` は読み込まないため、そこに設定したモデル指定には依存しません

既存のログインを共有するために、このアシスタントの認証ファイルを取り出す操作は不要です。[認証の公式説明](https://learn.chatgpt.com/docs/auth) も確認してください。

#### Codex の実行と制限

Bot は常駐し、操作ごとに独立した `codex exec` 子プロセスを起動します。

- shell を介さず、入力は標準入力へ渡すため、Discord の本文をコマンド引数として実行しません
- 一時 HOME／作業ディレクトリ、`--ephemeral`、`--ignore-user-config`、`--strict-config`、`--sandbox read-only` を使用
- shell、exec、apps、plugins、hooks、browser、computer、image、multi-agent、view_image、goals、memories、shell snapshot を無効化し、web search も無効化
- 承認を自動承認するオプションや sandbox の迂回は使用しません。`approval_policy=never` は権限昇格を許可せず、承認が必要な操作を失敗させる指定です
- Discord／Cursor token や無関係な環境変数は子プロセスに渡しません
- 同時実行は既定 2 件（上限 8）。満杯のときは追加要求を拒否し、無制限に待ち行列を作りません
- 既定 120 秒で打ち切り。入力・最終出力は各 64 KiB、診断出力は 256 KiB まで。終了時にはリクエスト用一時ファイルを削除します
- SIGINT／SIGTERM で処理中の Codex を中止し、POSIX では子プロセスグループも停止します
- CLI の生ログやプロバイダーの例外は Discord に返さず、Bot ログにも出しません

**互換性と境界:** 実 CLI のツール構成は `0.159.0-alpha.7` で、ローカルの模擬プロバイダーへの要求を使って確認しました。この構成では shell/file/MCP/browser/web ツールは提示されず、`request_user_input` のみが残ります。非対話実行では追加質問には回答せず、タイムアウトで終了します。別バージョンではオプションやツール構成が変わるため、更新後は再検証してください。未対応オプションではエラーにし、制限を緩めて再試行しません。

`--ignore-user-config` は**すべての設定を無効化する指定ではありません**。システム／管理者配布設定の MCP 等がある環境は、この Bot 用の隔離環境として適しません。専用環境に追加の MCP・skills・hooks を設定せず、実効ツール構成を確認してから運用してください。read-only 単独は「ファイルを読めない」という意味ではなく、プロンプトの注意書きだけでは安全境界になりません。`--ephemeral` も、CLI の認証・キャッシュ・診断状態まで一切保存しない保証ではありません。

選択メッセージ・作者名・取得した文脈・モーダルの指示は、選んだ AI プロバイダーへ送信されます。機密情報の取り扱い、Bot を利用できる人、利用料金を確認してから有効化してください。

### Cursor SDK（既存の動作）

```env
AI_PROVIDER=cursor
CURSOR_API_KEY=安全に設定したキー
CURSOR_MODEL=composer-2.5
```

`AI_PROVIDER` 未指定の場合は後方互換のため `cursor` です。Codex モードでは Cursor API key は不要で、Cursor SDK を初期化しません。Cursor モードは引き続き `tools: []` で文章生成のみを行います。

## 4. コマンド登録と起動

```bash
npm run deploy   # Discord の Application commands を登録／更新
npm start
```

右クリック → Apps から操作して、結果が本人だけに表示されることを確認します。コマンド登録はリモート設定を変更するため、初回とコマンド変更時に明示的に実行してください。失敗した登録は非ゼロで終了します。

## バックグラウンド／常時稼働

### 稼働中の Linux ホストでの再起動付き実行

```bash
mkdir -p logs
nohup bash run-forever.sh >> logs/bot.out 2>&1 &
```

`run-forever.sh` は Bot の終了後に 5 秒待って再起動します。Linux の `flock` が利用可能な環境では二重起動を防ぎます。`npm ci` とコマンド登録は先に完了してください。従来の起動時登録が必要な場合のみ `DEPLOY_COMMANDS=1 bash run-forever.sh` を指定できます。SIGTERM で supervisor を止めると Bot と進行中の Codex も停止します。終了を最大 15 秒待ち、応答しない子プロセスには強制終了を送って supervisor のロックを解放します。

未起動時だけ起動する既存の Linux ヘルパーも使えます。

```bash
bash ensure-running.sh
```

このヘルパーは Node.js が要件未満なら公式配布をインストールし、依存がなければ `npm ci` を行います。環境変更を許可できるホストでだけ実行してください。Node のインストールを避けたい場合は、あらかじめ要件を満たして `run-forever.sh` を直接実行します。Bot の起動確認と、Discord に接続済みであることは区別してください。

### 再起動後も復旧する Linux サーバー

`deploy/discord-translate.service` は **systemd のテンプレート**です。管理者が専用 OS ユーザー、Node のパス、リポジトリのパス、環境ファイル、専用 CODEX_HOME の所有権を確認してからインストール・有効化してください。環境ファイルにはサービスに必要な秘密情報のみを安全に保存します。systemd と `run-forever.sh` を同時に使わず、supervisor は一つにします。

**dot などの一時的なクラウド作業環境では、バックグラウンド化しても 24 時間稼働は保証されません。** ホストの停止・再作成・ネットワーク終了で Bot も止まります。このリポジトリのスクリプトはホスト自体を維持できません。常時運用には継続稼働が保証されたサーバーと、再起動時に復旧する仕組みが必要です。

## Interaction の初回応答と診断

Discord の初回応答には 3 秒の期限があります。REST も明示的なプロキシ対応 dispatcher と共有接続プールを使い、Gateway 接続前に公開の `/gateway` を読み取って接続を準備します。稼働中は同じ公開エンドポイントを 15 秒間隔で読み取り、接続を維持します。重複した probe は作らず、終了時には timer と接続を破棄します。この維持要求に Bot token やメッセージ本文は送信しません。

実環境の検証では、cold 接続に約 11.5 秒かかる一方、共有 pool は 147 ms、35 秒の idle 区間後も 111 ms でした。ネットワーク切断等で再接続が必要になれば、期限に間に合わない可能性は残ります。acknowledgement 失敗時は AI 実行や再返信をせず、Bot をクラッシュさせません。

ローカル診断ログには command 名、interaction の種別、受付・初回応答・完了の時刻差、固定の失敗分類のみを記録します。本文・interaction token・ID・生の Discord 例外は記録しません。モーダルも表示を先に行い、任意の履歴取得で初回応答を遅らせません。

## 開発・検証

```bash
npm test       # Codex の起動・制限・失敗・終了処理を偽 CLI で検証
npm run check  # TypeScript 型チェック
npm run build
bash -n run-forever.sh ensure-running.sh
```

テストは実際の Discord 接続・投稿・AI 推論・認証情報を必要としません。実際の Codex 認証／モデル応答と Discord のエンドツーエンド動作確認は、専用環境で別途行ってください。

## トラブルシューティング

- **REST は通るのに接続待ちになる:** Gateway は WebSocket を使います。ホストの既存の `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`（小文字も対応）を設定している場合、Bot は `proxy-agent` でその設定を Gateway にも適用します。`NO_PROXY` を尊重し、別の経路や宛先へ迂回しません。プロキシ URL に秘密情報が含まれる場合はログや Git に残さないでください

- **起動しない:** Node のバージョン、`DISCORD_TOKEN`、選択した provider の設定を確認
- **Codex が失敗:** `CODEX_BIN`、対応 CLI、専用 CODEX_HOME、サービス実行ユーザーでのログイン、利用可能モデルと制限を確認。CLI を安全で合成的なテキストで試し、秘密情報をログに貼らないでください
- **コマンドが見えない:** `npm run deploy`、Application ID、User Install を確認
- **周辺履歴が読めない:** User Install だけでは取得できない場合があります。対象サーバーへの Bot 参加と権限を確認。取得できない場合はメッセージ内の関連整理に切り替わります
- **モーダルの文脈が期限切れ:** 右クリックメニューから開き直してください
- **自分用アプリを非公開にしたい:** Installation の Install Link を None にしてから Public Bot を OFF。初回セットアップには不要です

## セキュリティ

`.env`、ログ、認証情報を Git に追加しないでください。漏えい時は該当サービスで無効化・再発行してください。Bot token は Discord Application のものだけを使用してください。

## ライセンス

MIT
