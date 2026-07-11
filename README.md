# Discord Chat Cleaner

Discordサーバー内で `Vimop` ロールが明示的に選択されたチャンネルを探し、保存期間を過ぎたメッセージを削除するBotです。複数の参加サーバーを順番に処理します。

## 動作

各サーバーで、次の条件をすべて満たすチャンネルが削除対象になります。

- `Vimop` ロールがチャンネルの権限設定に登録されている
- または、`Vimop` ロールが登録されたカテゴリと権限が同期されている
- `Vimop` ロールの実効権限で「チャンネルを表示」「メッセージ履歴を読む」「メッセージを管理」が許可されている

`@everyone` や他のロールだけで閲覧可能なチャンネルは対象になりません。ピン留めされたメッセージも削除しません。

対象ロールが存在しない、同名ロールが複数ある、または必要な権限が不足しているサーバーは警告を出してスキップし、次のサーバーを処理します。

## Discord側の設定

Discord Developer PortalでBotを作成し、OAuth2でサーバーへ招待します。Botには次の権限が必要です。

- チャンネルを表示
- メッセージ履歴を読む
- メッセージを管理

OAuthによって作成・付与されるロール名は、既定では `Vimop` を想定しています。削除対象にするチャンネルの「チャンネル設定」→「権限」で、このロールを追加してください。個別権限が未設定でも、ロールが登録されていて上記3権限が実効的に許可されていれば対象になります。

https://discord.com/oauth2/authorize?client_id=1522254911755255919&permissions=74752&integration_type=0&scope=bot+applications.commands

## ローカル実行

Python 3.12を使用します。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` を設定します。

```env
DISCORD_BOT_TOKEN=your-bot-token
TARGET_ROLE_NAME=Vimop
RETENTION_HOURS=168
RUN_EVERY_DAYS=2
FORCE_RUN=true
```

実行します。

```powershell
python bot.py
```

この処理はメッセージを実際に削除します。削除は元に戻せないため、最初はテスト用サーバーとチャンネルで確認してください。

## 環境変数

| 名前 | 必須 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `DISCORD_BOT_TOKEN` | はい | なし | Discord Botのトークン |
| `TARGET_ROLE_NAME` | いいえ | `Vimop` | 削除対象チャンネルを示すロール名。完全一致 |
| `RETENTION_HOURS` | いいえ | `24` | この時間以上経過したメッセージを削除 |
| `RUN_EVERY_DAYS` | いいえ | `1` | 定期実行時に処理する日数間隔 |
| `FORCE_RUN` | いいえ | `false` | `true` の場合、日数間隔の判定を無視して実行 |

## GitHub Actions

ワークフローは毎日04:00（JST）に起動します。現在の設定では `RUN_EVERY_DAYS=2` のため削除処理は2日ごと、`RETENTION_HOURS=168` のため1週間以上前のメッセージが対象です。

リポジトリの `Settings` → `Secrets and variables` → `Actions` に、次のRepository secretを登録してください。

- `DISCORD_BOT_TOKEN`

`workflow_dispatch` による手動実行では `FORCE_RUN=true` となり、実行日の判定を無視します。

## ログ

起動時にBotが認識しているサーバー一覧を表示します。その後、サーバーごとの対象チャンネルと確認・削除件数を出力します。

```text
Connected servers: 2
- Example Server (123456789012345678)
Server 123456789012345678: found 1 channels with an explicit permission entry for role "Vimop".
Server 123456789012345678: cleanup target #cleanup-target (234567890123456789)
Channel 234567890123456789: checked 10, deleted 9.
```

`checked` にはピン留めメッセージも含まれるため、`deleted` より多くなる場合があります。
