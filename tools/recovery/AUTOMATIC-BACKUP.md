# 自動バックアップ運用

v3 は、初回に復旧用パスワードで秘密鍵を保護し、その後は公開鍵だけで変更を暗号化します。ローカルの watcher と、承認された Library 保存を行う外部の処理は別です。依存のインストール・入力条件・v2 / v3 の復元は [README](README.md) を参照してください。

以下のコマンドはリポジトリルートから実行します。パスは説明用です。実際の専用ファイルと、実行ユーザーが管理する保存先に置き換えてください。

## 初回セットアップ（v3）

1. [setup-plan.example.json](setup-plan.example.json) をコピーし、`env_path`、`auth_path`、`destination_root` を設定します。`destination_root` 自体はまだ作らず、他人が書き込めない親ディレクトリを用意します
2. `existing_backup_path` は `null` にします。Library の保存先を新規作成する場合は `library_file_id` と `library_version` も両方 `null` にします。秘密情報の値やパスワードを plan に入れないでください
3. 対象ファイルの更新を止められる時間に、デスクトップ上でフォームを開きます

```bash
.venv-recovery/bin/python tools/recovery/migration_gui.py --plan /absolute/path/to/setup-plan.json
```

4. 本人が新しい復旧用パスワードと確認を入力し、準備ボタンを押します。v2 を先に作る必要はありません
5. 初回 v3 の作成とローカル復元検証が成功し、確定保存の警告がないことを確認します。準備先は新規ディレクトリとして公開され、フォームは閉じます。この時点では watcher も Library の定期保存も起動していません

plan は記載された8項目だけを含む version 1 の JSON です。自動バックアップでは、明示された `.env` と非空の JSON オブジェクトである専用 `auth.json` の両方が必要です。片方が消えた場合に、残る片方だけを保存することはありません。

## 既存 v2 からの移行

同じ plan の `existing_backup_path` に既存 v2 ファイルの絶対パスを設定し、`library_file_id` と `library_version` に、置換を承認された既存 Library 項目の確認済み ID・現在の版番号を指定します。移行ではこの2項目を `null` にできません。

同じ `migration_gui.py` を開き、本人が既存 v2 のパスワードを1回入力します。旧ファイルを復号してパスワードを確認した後、現在の専用ソースから初回 v3 を作成・検証します。元の v2 は変更しません。古い内容を現在の設定へ書き戻す操作ではありません。既存パスワードを失った場合、この移行はできません。

この準備では既存 Library 項目へまだ保存していません。[prepare / confirm](#定期保存prepare--confirm) を通し、最初の v3 の受領記録を確認してください。新規セットアップでも、承認済みの既存項目へ保存する場合は確認済み ID・版番号を指定できます。

## 新しい Library 項目の初回作成と紐付け

Library 未紐付けの状態では、この順序を守ります。

1. 初回ファイルを取得します。セットアップ時に固定した `initial-snapshot.json` と `initial-upload/discord-backup.encrypted.json` が照合され、アップロード対象の `file`、SHA-256、snapshot ID、サイズが返ります

```bash
.venv-recovery/bin/python tools/recovery/migration.py prepare-created /absolute/path/to/state
```

2. 操作者が保存を承認した Library に、対応する公式の Library 機能で、返された `file` の暗号化ファイルだけを新規保存します。固定のファイル名は `discord-backup.encrypted.json` です。平文ソース、パスワード、復号済み秘密鍵は渡しません
3. 作成が成功した際の `structuredContent` を加工せず、安全なローカルファイルに保持し、次へ標準入力で渡します

```bash
.venv-recovery/bin/python tools/recovery/migration.py bind-created /absolute/path/to/state < /absolute/path/to/create-response.json
```

4. `initial_library_binding_confirmed` と受領記録を確認してから、watcher と外部の定期保存処理を開始します

このローカル処理は Library の作成・アップロードを行いません。紐付けは最新 manifest ではなく固定した初回暗号化ファイルを検証し、成功応答の項目 ID、version 0、サイズを確認して `bridge-state.json` と `upload-receipt.json` に記録します。初回の後に新しいスナップショットができていても、初回として扱わず、以降の prepare / confirm で送ります。

応答がその暗号化ファイルを保存した本物の結果であることは、外部の呼び出し側で保証する必要があります。手書きの成功 JSON や別のアップロード結果で代用しないでください。作成の成否が不明なら新規作成を繰り返さず、Library 側の正確な項目・版・暗号化ファイルを照合します。紐付け途中の失敗も、状態ファイルを削除して成功扱いにしないでください。

## ローカル watcher

```bash
.venv-recovery/bin/python tools/recovery/automatic_backup.py --state-dir /absolute/path/to/state
```

状態ディレクトリごとに1プロセスだけ動かします。二重起動はロックで拒否されます。5秒間隔のメタデータ確認で、2回続けて安定した変更を観測すると短命の子プロセスで読み込み・暗号化します。通常は変更が安定してから約10秒以内が目安ですが、保証時間ではありません。

全ソースを再度開いて比較し、読み取り中の変更、パスの差し替え、symlink、認証ファイルの欠落・不正 JSON、所有者の不一致などを拒否します。複数ファイルの同一時点を保証するアプリケーション側のトランザクションではありません。

暗号化ファイルを `outbox/snapshot-UUID.encrypted.json` に確定してから `outbox/latest.json` を更新します。ローカルに作られただけでは、環境外に保存されたバックアップにはなりません。

## 定期保存（prepare / confirm）

Bot、watcher、transport に Library のクライアント・token・ログイン・スケジューラはありません。同じ実行環境のファイルへアクセスでき、Library 保存が承認されている外部処理を別途用意します。たとえば、対応する外部の定期タスクで1時間ごとに次の一連の処理を実行できます。作成・有効化できたことを確認するまでは、自動保存が有効とは扱わないでください。

```bash
.venv-recovery/bin/python tools/recovery/transport.py prepare /absolute/path/to/state
```

- `noop`: 最新の確定済み暗号化ファイルは、すでに受領記録と一致しています。アップロード不要です
- `ready`: `file`、保存先 `library_file_id`、`expected_current_version`、`request_id`、`snapshot_id`、`sha256` などが返ります。送信前に pending が保存されます。prepare 自体は送信しません
- 失敗: アップロードせず、原因を確認します。未紐付け、未確定の送信、版・受領記録の不整合、容量上限などは停止理由です

`ready` の場合、外部処理は対応する Library 機能で、返された `file` を**同じ項目**へ置換保存し、`expected_current_version` をそのまま版の条件に使います。現在の Library 機能が要求する成功後のファイルメタデータ反映も行います。prepare のステージングは非公開の一意な `upload-UUID/` に、固定名 `discord-backup.encrypted.json` を作ります。

成功後、次の4項目だけを含む JSON を confirm の標準入力に渡します。

- `request_id`、`snapshot_id`、`sha256`: 対応する prepare が返した値
- `library_response`: Library の成功結果全体、またはその完全な `structuredContent` を変更せず格納。結果全体なら `isError: false` が明示されている必要があります

```bash
.venv-recovery/bin/python tools/recovery/transport.py confirm /absolute/path/to/state < /absolute/path/to/confirmation.json
```

confirm は pending との相関、同じ項目、次の版番号、バイト数、ローカル暗号化ファイルを検証します。成功すると受領記録と版を更新し、pending を取り除きます。受領記録に応答 URL や拡張属性は保存しません。本物のツール応答を正しく渡す呼び出し側と、その保存先の保護は信頼境界の一部です。

タイムアウト、成否不明、版競合、重複実行、ローカル更新途中の失敗は pending を保持し、次の送信を止めます。版の条件を外す、pending を勝手に削除する、応答から成功を推測することは避け、リモートの正確な版と暗号化ファイルを照合してから承認された復旧を行ってください。受領記録と状態の更新は順序付きの確定書き込みであり、複数ファイルをまとめた原子的更新ではありません。

## 稼働確認・容量・限界

- `health.json` は watcher の状態です。通常の `updated_at` は状態変更時の時刻であり、定期的な生存通知ではありません。更新が古いだけで停止とは断定できず、新しいだけで継続稼働も証明できません。プロセスや外部の実行記録を別途確認します
- `watching` / `encrypted_snapshot_pending_upload` は Library 保存成功を示しません。`outbox/latest.json` と `upload-receipt.json` の snapshot・sequence を比較し、外部タスクの実行結果も確認します
- outbox と送信ステージングは、それぞれ暗号化ファイル256件が安全上限です。上限では停止し、自動削除しません。古いスナップショット、元の v2、Library の履歴を自動で間引く仕組みはありません。容量警告・pending・失敗を外部で通知し、保存済みの内容と必要な保持期間を確認した運用者が対処します
- 正常に1時間ごとの処理が実行される場合、Library 保存はおおむね1時間とローカル取得・転送時間を足した間隔が目安です。各変更をすべて Library の別バージョンに残す保証はなく、その時点の最新スナップショットを送ります
- スケジューラ遅延・実行環境停止・消失を含む最悪時のデータ損失時間に有限の上限はありません。最後に保存が確認された版以降の更新はすべて失われる可能性があります
- これらのヘルパーはホストを維持せず、24時間稼働や環境再作成後の無人復旧を保証しません。永続ストレージと継続稼働する実行環境は別途必要です。通信ポリシーで拒否された場合は停止し、別プロキシや宛先で制限を迂回しません

## 暗号化の範囲

v3 はスナップショットごとに新しい AES-256-GCM 鍵・nonce を使い、データ鍵を RSA-3072 / OAEP-SHA256 で保護します。復旧用秘密鍵は scrypt / AES-256-GCM でパスワード保護されます。受信者情報とスナップショットの識別情報も認証対象になり、公開鍵を含む bundle の SHA-256 をローカル設定に固定します。

通常の保存物は公開鍵、暗号化された秘密鍵、非秘密の設定・受領記録、暗号化ファイルです。パスワード、平文の秘密鍵、使い捨てデータ鍵、平文ソースのコピーを意図して永続保存しません。ただし Python のメモリ消去は保証できません。復元操作では指定した新規フォルダへ平文を書き出します。

公開鍵による暗号化は、作成者の本人性を証明する署名ではありません。公開鍵を持つ者は別の暗号化ファイルを作れます。完全なファイル差し替えや過去版への巻き戻しへの対処には、保護されたローカル状態、Library の書き込み経路、版付き受領記録の照合が必要です。
