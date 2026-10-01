# Discord User-Install Translation Bot

Discord のメッセージを右クリックして翻訳・要約・返信案を作る、公式 Discord Application 用 Bot です。AI 処理には **Cursor SDK** または **Codex CLI** を選べます。どちらでも同じ Discord コマンドを使えます。

| 利用する AI | 必要な認証 | 設定手順 |
| --- | --- | --- |
| Cursor SDK | Cursor API key | [Cursor 向け](#cursor-sdk) |
| Codex CLI | Bot 専用環境での Codex ログイン、または API key | [Codex 向け](#codex-cli) |

Discord の設定・インストール・起動は共通です。まず手順 1・2 を済ませ、手順 3 で使う AI を選んでください。

## 機能

- **Translate to English / Translate to Japanese**: 選択したメッセージを翻訳
- **要約**: スレッド／返信の文脈を踏まえ、短く日本語要約
- **返信ドラフト**: 日本語と英語の返信案を生成。自動送信はしません
- **類似を探す**: 読み取れる周辺履歴から似た意図の投稿を探し、作者・抜粋・リンクを表示。履歴が取れなければメッセージ内の関連整理にフォールバック
- **指示して実行**: モーダルの指示で文章を変換。シェル実行やファイル操作の機能ではありません
- 結果は呼び出した本人だけに表示する **ephemeral 応答**

## 必要なもの

- Node.js **22.13 以上**
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

周辺の投稿履歴を読むには、Bot が対象サーバーにも参加し、適切な権限を持つ必要があります。必要な場合のみ Portal の **Message Content Intent** を有効化し、`DISCORD_MESSAGE_CONTENT_INTENT=1` にしてください。使わない場合は `.env.example` の `0` を維持してください。Intent が許可されていないのに要求すると `Used disallowed intents` で切断されます。

## 2. インストール

```bash
git clone https://github.com/hndrr/DiscordUserTranslateBot.git
cd DiscordUserTranslateBot
npm ci
cp .env.example .env
```

`.env` に `DISCORD_TOKEN` と `DISCORD_APPLICATION_ID` を安全に設定します。秘密情報は `.env.example` やコマンド引数、会話ログに書かないでください。

## 3. AI の設定（Cursor / Codex のどちらか一方）

`.env` の `AI_PROVIDER` で使う AI を指定します。**`.env.example` は `codex` 設定です。Cursor を使う場合は `cursor` に変更してください。** `AI_PROVIDER` を省略した場合は、既存環境との互換性のため `cursor` になります。

### Cursor SDK

[Cursor Settings](https://cursor.com/settings) で API key を取得し、`.env` を次のように設定します。

```env
AI_PROVIDER=cursor
CURSOR_API_KEY=your_cursor_api_key_here
CURSOR_MODEL=composer-2.5
```

`CURSOR_API_KEY` は必須です。`CURSOR_MODEL` の既定値は `composer-2.5` なので、変更しなければ省略できます。Codex CLI のインストール・ログイン・`CODEX_*` の設定は不要です。

設定後は **手順 4「コマンド登録と起動」** に進んでください。

### Codex CLI

[公式セットアップ](https://learn.chatgpt.com/docs/cli) に従って Codex CLI を用意し、`.env` を次のように設定します。Cursor API key は不要です。

```env
AI_PROVIDER=codex
CODEX_BIN=codex
DISCORD_CODEX_HOME=/absolute/path/to/dedicated-discord-codex-home
CODEX_MODEL=gpt-6-luna
CODEX_REASONING_EFFORT=low
CODEX_TIMEOUT_MS=120000
CODEX_MAX_CONCURRENCY=2
```

- Bot 専用 OS ユーザー／コンテナと、**新しい専用 CODEX_HOME** を推奨します。その環境でユーザー自身が通常の `codex login` を行ってください。既存の認証ファイルをコピーしないでください
- 例: `CODEX_HOME=/absolute/path/to/dedicated-discord-codex-home codex login`。認証はサービス実行ユーザーで行い、サービスにも同じ絶対パスを設定します
- 通常のコーディング用 Codex home は使わないでください。保存済みの指示がモデルに送られる可能性があります。`AGENTS.md`、`AGENTS.override.md`、`memories` / `memories_v2` がある home は拒否します。skill は内容を読まずに `SKILL.md` のパスを列挙し、Codex プロセスの起動時に明示的に無効化します。symlink は拒否します。skill の自動参照を避けるため、入力は JSON 文字列として渡し、ドル記号をエスケープします
- 別案として `.env` の `CODEX_API_KEY`（または環境変数 `DISCORD_CODEX_API_KEY`）を秘密情報として設定すると、Codex プロセスの起動時に空の一時 CODEX_HOME を用意します。この場合 `CODEX_HOME` の指定や保存済みログインは不要です。API の利用料金は契約に従って発生します
- CLI は認証情報を通常の仕組みで参照します。Bot が認証ファイルを読み出したりコピーしたりすることはありません
- `CODEX_MODEL` 未指定時は軽量な `gpt-6-luna`、`CODEX_REASONING_EFFORT` 未指定時は `low` を明示します。利用可能なモデルはアカウントによって異なります。非対応なら利用可能なモデルを明示してください。高価なモデルへの自動フォールバックや、有料の fast/priority モードは有効化しません。ユーザーの `config.toml` のモデル設定には依存しません
- 推論を使わない翻訳には `CODEX_REASONING_EFFORT=none` を明示できます。検証した Luna の実 API 応答では reasoning token が 0 でした。CLI の表示候補に `none` がなくても API で受理される場合があります。処理時間にはネットワークや生成時間も含まれるため、必ず速くなるという保証ではありません

Bot の認証 home は `DISCORD_CODEX_HOME` で明示してください。既存の `.env` の `CODEX_HOME` も互換性のため使用できますが、ホストから継承した `CODEX_HOME` を暗黙に流用しません。Bot の `.env` にあるモデル／reasoning 設定もホストの既定より優先します。Discord token 等の他の環境変数を一括で上書きする設定ではありません。認証ファイルのコピーは不要です。[認証の公式説明](https://learn.chatgpt.com/docs/auth) も確認してください。

設定後は **手順 4「コマンド登録と起動」** に進んでください。Codex を運用する際の制限は以下を確認してください。

<details>
<summary>Codex の実行方式・制限・CLI の互換性（運用者向け）</summary>

Bot と Codex app-server を常駐させます。Codex プロセスは共有し、翻訳ごとに独立した ephemeral thread を作成するため、別の依頼の会話を混ぜません。

- shell を介さず、入力は標準入力へ渡すため、Discord の本文をコマンド引数として実行しません
- 一時 HOME、依頼ごとの空の作業ディレクトリ、ephemeral thread、`--strict-config`、read-only sandbox を使用
- shell、exec、apps、plugins、hooks、browser、computer、image、multi-agent、view_image、goals、memories、shell snapshot を無効化し、web search も無効化
- 承認を自動承認するオプションや sandbox の迂回は使用しません。`approval_policy=never` は権限昇格を許可せず、承認が必要な操作を失敗させる指定です
- Discord／Cursor token や無関係な環境変数は子プロセスに渡しません
- 同時実行は既定 2 件（上限 8）。満杯のときは追加要求を拒否し、無制限に待ち行列を作りません
- 既定 120 秒で打ち切り。入力・最終出力は各 64 KiB、protocol の1行は 256 KiB まで。タイムアウトした依頼だけを中断し、他の依頼が完了してから worker を再起動します。再起動待ちの間は新しい依頼を受け付けません
- 中断要求と終了通知を最大 1.5 秒待ちます。中断を確認できない場合は、生成を放置しないため共有プロセス全体を停止します。正常に完了した依頼はプロセス終了を待たずに結果を返します
- SIGINT／SIGTERM で処理中の Codex を中止し、POSIX では子プロセスグループも停止します
- CLI の生ログやプロバイダーの例外は Discord に返さず、Bot ログにも出しません

**互換性と境界:** 実 CLI のツール構成は `0.159.0-alpha.7` で、ローカルの模擬プロバイダーへの要求を使って確認しました。この構成では shell/file/MCP/browser/web ツールは提示されず、`request_user_input` のみが残ります。ツール実行・承認・追加入力の要求は拒否し、プロセスを終了します。別バージョンではオプションやツール構成が変わるため、更新後は再検証してください。未対応オプションではエラーにし、制限を緩めて再試行しません。

app-server は CLI の設定を読み込みます。Bot 専用の空の設定環境を使ってください。起動時と各依頼の開始時に MCP inventory が空であることを確認し、空でなければ処理を拒否します。システム／管理者配布設定の MCP 等がある環境は、この Bot 用の隔離環境として適しません。専用環境に追加の MCP・skills・hooks を設定せず、実効ツール構成を確認してから運用してください。read-only 単独は「ファイルを読めない」という意味ではなく、プロンプトの注意書きだけでは安全境界になりません。ephemeral thread も、CLI の認証・キャッシュ・診断状態まで一切保存しない保証ではありません。終了した thread は unsubscribe し、64件処理して idle になったらプロセスを再起動してメモリを制限します。

</details>

## 4. コマンド登録と起動

```bash
npm run preflight  # ローカルの設定・実行環境を確認（通信なし）
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

`run-forever.sh` は起動前チェックを1回行い、成功したら Bot の終了後に 5 秒待って再起動します。Node の要件、Discord token の未設定、選択した provider の設定、Codex 実行ファイルや専用 home の欠落は、再起動ループに入らず終了します。チェックは通信せず、認証ファイルを読みません。ログインの有効性・モデル利用可否・接続成功の確認は別途必要です。

Linux の `flock` が利用可能な環境では二重起動を防ぎます。`npm ci` とコマンド登録は先に完了してください。従来の起動時登録が必要な場合のみ `DEPLOY_COMMANDS=1 bash run-forever.sh` を指定できます。SIGTERM で supervisor を止めると Bot と進行中の Codex も停止します。終了を最大 15 秒待ち、応答しない子プロセスには強制終了を送って supervisor のロックを解放します。

未起動時だけ起動する既存の Linux ヘルパーも使えます。

```bash
bash ensure-running.sh
```

このヘルパーは Node.js が要件未満なら公式配布をインストールし、依存がなければ `npm ci` を行います。環境変更を許可できるホストでだけ実行してください。Node のインストールを避けたい場合は、あらかじめ要件を満たして `run-forever.sh` を直接実行します。Bot の起動確認と、Discord に接続済みであることは区別してください。

### 再起動後も復旧する Linux サーバー

`deploy/discord-translate.service` は **systemd のテンプレート**です。管理者が専用 OS ユーザー、Node のパス、リポジトリのパス、環境ファイル、専用 CODEX_HOME の所有権を確認してからインストール・有効化してください。環境ファイルにはサービスに必要な秘密情報のみを安全に保存します。systemd と `run-forever.sh` を同時に使わず、supervisor は一つにします。

**dot などの一時的なクラウド作業環境では、バックグラウンド化しても 24 時間稼働は保証されません。** ホストの停止・再作成・ネットワーク終了で Bot も止まります。このリポジトリのスクリプトはホスト自体を維持できません。常時運用には継続稼働が保証されたサーバーと、再起動時に復旧する仕組みが必要です。

### クラウド作業環境での起動・復旧

1. 既存の実行セッションと supervisor のロックを確認します。起動済みなら重ねて起動しません。`flock -n logs/bot.lock -c true` はロックが空いている場合だけ成功します
2. リポジトリ、`.env` のリンク先、専用 Codex home が残っていることを確認し、`npm run preflight` を実行します。資格情報を表示・コピーせず、専用ログインは `CODEX_HOME=/absolute/path/to/dedicated-home codex login status` で確認します。設定が消えていたら復旧を止め、本人による安全な入力・ログインに戻ります。ホスト側の Codex 認証を流用しません
3. 更新する場合は既存 supervisor を正常終了し、ロックが解放された後に更新と検証を行います。通常の再起動で Discord コマンドの再登録は不要です
4. 実行ツールが管理する環境では、Discord と選択した AI への通信が許可された実行セッションで、次を **foreground のまま** 実行します。セッション終了時に子プロセスも止まる環境では `nohup` に頼らず、実行セッションを保持します

```bash
mkdir -p logs
bash run-forever.sh >> logs/bot.out 2>&1
```

実行ツールが通信の許可レビューを必要とする場合は、その正式な仕組みを使って起動してください。シェルスクリプトから許可を付与することはできません。ポリシーで停止されたら理由を確認し、許可された同じ操作の再実行まで止めます。別のプロキシ・宛先へ切り替えて制限を回避しません。

起動後は、今回の `Bot is ready!` と実行セッションの生存を確認し、少なくとも接続維持の15秒間隔を越えて再確認します。その後、本人が右クリックで翻訳を1件試し、`received` → `acknowledged` → `completed` / `outcome: success` と実際の返信を確認します。READY だけでは翻訳の完了を証明しません。診断では本文・token・生ログを共有せず、固定の失敗分類と時刻差だけを使います。

自動再起動が対応するのは **supervisor が生きている間の Bot 終了** です。実行セッション自体の終了・通信ポリシー拒否・環境再作成には対応できません。共有ディレクトリへの保存も、環境再作成後の保持を保証するものではありません。これらを越える自動復旧には、永続ストレージと継続稼働が保証されたホストが必要です。

## Interaction の初回応答と診断

Discord の初回応答には 3 秒の期限があります。初回応答・通常の REST 通信・接続維持の確認には、それぞれ別のプロキシ対応接続プールを使います。Gateway 接続前に公開の `/gateway` で初回応答用の接続を準備します。稼働中は 15 秒間隔で予備の接続を確認し、完了してから初回応答用に切り替えます。履歴取得や接続確認が遅れても、その通信の後ろに初回応答を並べません。接続確認に Bot token やメッセージ本文は送信しません。

ネットワーク切断等で再接続が必要になれば、期限に間に合わない可能性は残ります。初回応答に失敗した場合は AI 実行や再返信をせず、Bot をクラッシュさせません。終了時には接続確認のタイマーとすべての接続プールを破棄します。

ローカル診断ログには command 名、interaction の種別、受付・初回応答・完了の時刻差、固定の失敗分類のみを記録します。本文・interaction token・ID・生の Discord 例外は記録しません。モーダルも表示を先に行い、任意の履歴取得で初回応答を遅らせません。

## 開発・検証

```bash
npm test       # Codex の起動・制限・失敗・終了処理を偽 CLI で検証
npm run check  # TypeScript 型チェック
npm run build
bash -n run-forever.sh ensure-running.sh
```

テストは実際の Discord 接続・投稿・AI 推論・認証情報を必要としません。ローカルの HTTP サーバーで初回応答と他の通信の分離を、模擬 RPC で会話の分離・タイムアウト時の並行処理・終了処理を検証します。実際の Codex 認証／モデル応答と Discord のエンドツーエンド動作確認は、専用環境で別途行ってください。

## トラブルシューティング

- **REST は通るのに接続待ちになる:** Gateway は WebSocket を使います。ホストの既存の `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`（小文字も対応）を設定している場合、Bot は `proxy-agent` でその設定を Gateway にも適用します。`NO_PROXY` を尊重し、別の経路や宛先へ迂回しません。プロキシ URL に秘密情報が含まれる場合はログや Git に残さないでください

- **起動しない:** Node のバージョン、`DISCORD_TOKEN`、選択した provider の設定を確認
- **Codex が失敗:** `CODEX_BIN`、対応 CLI、専用 CODEX_HOME、サービス実行ユーザーでのログイン、利用可能モデルと制限を確認。CLI を安全で合成的なテキストで試し、秘密情報をログに貼らないでください
- **コマンドが見えない:** `npm run deploy`、Application ID、User Install を確認
- **周辺履歴が読めない:** User Install だけでは取得できない場合があります。対象サーバーへの Bot 参加と権限を確認。取得できない場合はメッセージ内の関連整理に切り替わります
- **モーダルの文脈が期限切れ:** 右クリックメニューから開き直してください
- **自分用アプリを非公開にしたい:** Installation の Install Link を None にしてから Public Bot を OFF。初回セットアップには不要です

## セキュリティ

Cursor / Codex のどちらを使う場合も、選択メッセージ・作者名・取得した文脈・モーダルの指示は、選んだ AI プロバイダーへ送信されます。利用できる人、送信する情報、利用料金を確認してから有効化してください。Cursor は `tools: []`、Codex は上記の制限を使い、文章生成のみを行います。

`.env`、ログ、認証情報を Git に追加しないでください。漏えい時は該当サービスで無効化・再発行してください。Bot token は Discord Application のものだけを使用してください。

## ライセンス

MIT
