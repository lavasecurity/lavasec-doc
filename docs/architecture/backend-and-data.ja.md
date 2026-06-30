---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# バックエンドとデータ

> **想定読者:** バックエンドエンジニア。 **対象範囲:** サーバー層 — 2つの Cloudflare Workers、Supabase Postgres のスキーマ／RLS／認証、Cloudflare R2 と D1 のストア、HTTP API の全体像、設定とデプロイ、そして source-url-only をサーバー側でどう強制しているか。
>
> **正典となる参照先:** プランとコードが食い違ったときは **コードが正しい** — 食い違いはその場で明記します。ステータスラベルはドキュメントセット共通の凡例を使います。 **実装済み**（出荷済みでコードでも確認済み）、 **進行中**（一部だけ着地）、 **予定**（設計済みだがまだ作っていない）、 **取り下げ**（却下またはロールバック済み）。

## 1. バックエンドの全体像 {#1-the-shape-of-the-backend}

バックエンドはあえて小さく、プライバシーを守る作りにしています。これはフィルタリングサービスではなく、メタデータとアカウントを扱うエッジです。 **DNS フィルタリングはすべて端末上で行われます。Lava がブラウジングを自社サーバー経由でルーティングすることはなく、訪れたドメインの流れを受け取ることもありません — バックエンドが持つのはカタログのメタデータ、ユーザーごとの不透明な暗号化バックアップ、そしてユーザーが送信を選んだ匿名の診断情報だけです。** 日常的な DNS クエリやドメインごとのテレメトリのためのテーブルは存在せず、アカウントログインは任意で、保護のために必須になることは決してありません。

サーバー層は2つの構成要素に分かれています。バックエンドの Worker コードと、DB スキーマです。

| 構成要素 | 役割 |
|---|---|
| **lavasec-api Worker** | メインのエッジ: カタログの公開読み取り、管理者＋cron によるブロックリスト同期とカタログ公開、匿名の不具合レポート、ヘルプのフィードバック、アカウント削除、App Store のエンタイトルメントのミラーリング、QA プローブピクセル、アカウントの QA アクセスチェック、不具合レポートのトリアージ昇格 |
| **lavasec-email Worker** | `@lavasecurity.app` 宛ての受信専用 Cloudflare Email Routing フォワーダー |
| **Supabase Postgres**（Supabase Postgres プロジェクト） | アカウント、暗号化バックアップ、カタログのメタデータ、service-role 専用テーブル。すべての public テーブルに RLS |
| **Cloudflare R2**（本番バケット。ステージング用には別のプレビューバケット） | カタログのスナップショット＋同期カーソル。サードパーティのブロックリストのバイト列は **絶対に** 置かない |
| **Cloudflare D1**（ヘルプフィードバック用データベース） | 追記専用の匿名ヘルプ記事フィードバック投票 |

Worker は Supabase に対して、PostgREST（`/rest/v1`）と Auth（`/auth/v1`）経由で、Supabase の service-role 認証情報を使ってアクセスします — サーバー側に Supabase SDK は無く、呼び出しは `supabase()` / `supabaseAuth()` ヘルパー経由の生の `fetch` です。

ステータス: **実装済み**。

## 2. lavasec-api Worker {#2-lavasec-api-worker}

`wrangler.toml`: `name = "lavasec-api"`、`main = "src/index.ts"`、R2 バインディング → 本番バケット（ステージング用には別のプレビューバケット）、D1 バインディング → ヘルプフィードバック用データベース、そして **2つの cron トリガー**: 6時間ごとに発火するもの（ブロックリスト同期＋カタログ公開）と、2分ごとに発火するもの（不具合レポートのトリアージ昇格）。提供先は `api.lavasecurity.app` です。

### 2.1 API の全体像 {#21-api-surface}

ルーティングはフラットな `route()` ディスパッチャーです。特記がない限りすべて **実装済み** です。

**公開／未認証**

| メソッドとパス | ハンドラ | 備考 |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | R2 から `catalog/latest.json` を配信 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | R2 から `catalog/{version}.json` を配信。`Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS`（デフォルト 300秒） |
| `POST /v1/bug-reports` | `createBugReport` | 匿名、ログインは任意。許可リストに載ったデバッグフィールドのみ |
| `POST /v1/help-feedback` | `createHelpFeedback` | 匿名の記事投票 → Supabase ではなく **D1** へ |

> 添付アップロード（かつての `PUT /v1/bug-reports/:id/attachment` ルート）は **削除されました**。スクリーンショットや追加の詳細は、人が介在するサポートチャネルで扱います。Worker はアカウント削除時に、レガシーな添付オブジェクトをベストエフォートで削除するだけです。

**アカウント（Supabase アクセストークンが必要）**

| メソッドとパス | ハンドラ | 備考 |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | ユーザーのアクセストークンを検証し、その行＋レガシーな R2 添付オブジェクトを削除し、その後 service role で Supabase Auth のユーザーを削除 |
| `GET /v1/account/qa-access` | `accountQAAccess` | service-role 専用の `qa_developers` 許可リストから `is_developer` を返す |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | クライアント検証済みの StoreKit JWS から `entitlements` 行（プラン `lava_security_plus`）をアップサート |

> **`/v1/backup` ルートは無し。** パスキー支援のバックアップ復元は今や **ゼロ知識** で、完全にクライアント側で行われます（§4.3 と §5 参照）。Worker には `/v1/backup/*` ルートも、WebAuthn／パスキーのコードもありません。

**管理者（`requireAdmin` 経由の管理者 API キー）**

| メソッドとパス | ハンドラ |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> 管理者向け HTTP エンドポイントは管理者 API キーでゲートされています。スケジュール（cron）の同期経路はこれらの HTTP ルートを **呼び出しません** — `scheduled` ハンドラの中で同期ロジック（`syncBlocklistSources`）を直接呼び出します。

**QA プローブホスト** — 4つの `*.qa-probe.lavasecurity.app` ホスト（`allowed`／`blocked`／`exception`／`guardrail`）へのリクエストは、ルーティングの前に短絡され、`getQAProbePixel` 経由で 1×1 の `no-store` PNG を返します。これらは Supabase にも R2 にも書き込まれません。

### 2.2 バインディングと cron {#22-bindings--cron}

- **R2 バインディング** — `catalog/latest.json`、`catalog/{version}.json`、そしてラウンドロビンのカーソル `catalog/scheduled-sync-cursor.json`。 **サードパーティのブロックリストのバイト列は決して保存しません。**（レガシーな不具合レポートの添付オブジェクトは、アカウント削除時にベストエフォートで *削除* されるだけで、書き込まれることはありません。）
- **D1 バインディング** — 追記専用の匿名 `article_id` / `locale` / `vote` / `path` 行。設計上、Supabase とは分離して保持します。
- **Cron（`scheduled`）** — ハンドラは cron id で分岐します:
  - **6時間ごと** — 1回の実行につき **1つ** のソースを同期し、R2 カーソル（`nextScheduledSyncSourceID`、`SCHEDULED_SYNC_CURSOR_KEY`）でラウンドロビンしてから、カタログを再公開します。負荷を分散することで、すべての上流を一度に叩くのを避けています。
  - **2分ごと** — 新しい匿名レポートを内部の課題トラッカーのキューへ昇格させる、内部の不具合レポートトリアージ経路を実行し、自前のウォーターマークカーソルを進めます。これは社内運用ツールであり、課題トラッカー／通知の識別子は設定であって、公開 API の一部ではありません。

## 3. カタログと source-url-only の強制 {#3-catalog--source-url-only-enforcement}

ここは Lava のコンプライアンス姿勢に最も固有なバックエンド部分なので、サーバー側で強制をかけています。

### 3.1 source-url-only モデル {#31-the-source-url-only-model}

> **source-url-only:** GPL／IP コンプライアンスのための配布モデルです。Lava は上流の URL ＋承認済みハッシュだけを公開し、端末自身がリストを取得・解析します。Lava はサードパーティのブロックリストのバイト列を **決して** 保存・ミラー・変換・配信しません。

各 `blocklist_sources` 行は `redistribution_mode` を持ち、許される値は `"source_url_only"` だけです。端末が読むカタログ（`/v1/catalog`、`schema_version` 2）はエントリを `sources[]` と `guardrails[]` に分け、すべてのエントリが上流の `source_url` ＋ `accepted_source_hashes`（SHA-256 ＋バイトサイズ＋エントリ数＋ `reviewed_at` ＋ステータス `accepted`）を持ちます — リストのバイト列は決して持ちません。`formatCatalogEntry` を参照してください。

> **取り下げ:** 以前の設計では、バイトを保持した GPL リストファイルを R2 にミラーしていました（GPL 生バイト R2 コンプライアンスプラン）。これは **2026-05-25 に source-url-only によって置き換えられました**。Lava はもはやサードパーティのブロックリストのバイト列を保存も配信もしません。`mirror_events` というテーブル名は、その放棄された設計から残った名残です — 今では単なる同期／公開の監査ログです。

### 3.2 Worker が書き込み時にどう強制するか {#32-how-the-worker-enforces-it-on-writes}

同期経路（`syncOneBlocklist`、管理者と cron）は、各上流の `source_url` を取得し、 **メタデータを計算するためだけに Worker 内でローカルに** 正規化・検証して（`entry_count`、`source_hash`、`normalized_hash`、`byte_size`）、`blocklist_versions` 行を書き込み、再公開します。バイト保存用のキーは null にハードコードされています:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

マイグレーション（`20260525000000_add_blocklist_distribution_mode.sql`）でこれらのカラムを nullable に変更し、既存の値を null に設定したので、ミラーしない方針はスキーマレベルでも強制されています。公開されたカタログは R2 の `catalog/{version}.json` と `catalog/latest.json` の **両方** に書き込まれます（`publishCatalog`）。

### 3.3 正規化のガードレール（メタデータのみ） {#33-normalization-guardrails-metadata-only}

Worker 側の正規化（`normalizeBlocklist`）は、保護対象ドメインをフィルタし、上限を強制し、重複排除＋ソートを行います。これは信頼できるメタデータを計算するためだけのものです。 **コミュニティリスト** については、端末はダウンロードを **ハッシュゲートしません** — 端末は厳選された `source_url` から TLS 越しに取得し、上限の下で解析します（カタログの承認済みハッシュは参考情報です）。したがって、この Worker 側の正規化はそれ自体がセキュリティ境界ではありません。（Lava の脅威ガードレール層は端末側でハッシュにピン留めされたままで、`source_url` の出所は公開時に強制されます — URL の変更は新しい `list_id` を使わなければなりません。）主要な定数:

- `PROTECTED_SUFFIXES` — Apple/iCloud/`mzstatic`/Lava Security のドメイン/Supabase/Cloudflare/Google/GitHub にマッチするルールをすべて取り除きます。これにより、毒入りの上流が Lava 自身のインフラやサインインプロバイダをブロックできないようにします。
- `MAX_BLOCKLIST_BYTES = 25 MiB`、`MAX_BLOCKLIST_LINE_LENGTH = 2048`、`MAX_NORMALIZED_DOMAINS = 500_000`。

### 3.4 何が公開可能か {#34-what-is-publishable}

`isPublicBlocklistSource` がソースを公開するのは、`status` が `sync` または `nosync` で、`redistribution_mode === "source_url_only"`、 **かつ** `isAllowedLaunchGPLSource` を通過したときだけです。ローンチ用 GPL ゲート（`isAllowedLaunchGPLSource`）は、非 GPL のソースは自由に許可し、確認済みの GPL-3.0 のソースファミリーを `list_id` のプレフィックスで許可します: `hagezi-`、`oisd-`、`adguard-`。

### 3.5 シードされたソースとデフォルト有効 {#35-seeded-sources--default-enabled}

用意されたソースは、正典の [ブロックリストカタログ](../legal/blocklist-catalog.md) 仕様（HaGeZi、OISD、The Block List Project、Phishing.Database、StevenBlack、AdGuard、1Hosts）から生成され、マイグレーション経由で source-url-only のメタデータとしてシードされます。カテゴリ拡張のマイグレーションは、多層防御のカテゴリ（nsfw／social／gambling／piracy）を追加し、新規インストールのデフォルトを **Block List Basic** に整え直し、AdGuard DNS Filter を弁護士フラグ付き・デフォルト無効の選択肢として再有効化します。ステータス: **実装済み**。

> **カタログのデフォルトはクライアントと一致。** カタログの `default_enabled` 集合は **{Block List Basic}** で、これは以前の Phishing ＋ Scam のペアを置き換える、幅広く寛容な統合リストであり、iOS の推奨デフォルト（`AppConfiguration.lavaRecommendedDefaults`）と一致します。配信される `default_enabled` カラムと、同梱される iOS の `DefaultCatalog` は、どちらも同じ正典の仕様から生成されるので、構造上一致します（これにより、以前のクライアント↔バックエンドのデフォルトの食い違いが解消されます）。注意: `default_enabled` は参考情報です。本当のプランのゲートはリストの数ではなく、 **filter-rules budget（無料プラン 500K / Plus 2M）** です。バイト列ではなく URL を公開する法的根拠は [GPL source-url-only コンプライアンス判断](../legal/gpl-source-url-only-compliance-decision.md) にあります。

## 4. Supabase Postgres {#4-supabase-postgres}

Supabase Postgres プロジェクトです。RLS は **すべての** public テーブルで有効になっています。

### 4.1 コアスキーマ {#41-core-schema}

`20260516034033_backend_core.sql` が基盤を作ります（7つの public テーブルすべてで RLS を有効化）:

- **`profiles`、`user_settings`、`entitlements`** — ユーザーごとのアカウント状態。トリガー `handle_new_user()` が `auth.users` への挿入時に `profiles` ＋ `user_settings` 行を自動作成します。
- **`blocklist_sources`、`blocklist_versions`** — カタログのメタデータテーブル。ソースは用意された上流リスト（`list_id`、`source_url`、ライセンス、リスク、`default_enabled`、`status`、`redistribution_mode`）で、バージョンは同期されたスナップショットのメタデータ（ハッシュ、`entry_count`、`byte_size`）で、`latest_version_id` 経由で紐づけられます。
- **`mirror_events`** — `sync` / `catalog_publish` イベントの service-role 専用監査ログ（レガシー名。§3.1 参照）。
- **`bug_reports`** — service-role 専用の匿名レポート。

後のマイグレーションが **`user_backups`**（§4.3）と **`qa_developers`**（`20260608000000_qa_developers_allowlist.sql`）を追加します。

### 4.2 RLS モデル {#42-rls-model}

| テーブル | ポリシー | 効果 |
|---|---|---|
| `profiles`、`user_settings`、`entitlements`、`user_backups` | ユーザーごとの `auth.uid() = user_id` | 各ユーザーは自分の行だけを見る |
| `blocklist_sources` | `status in ('sync','nosync')` の場合に public-read（`backend_core.sql:262-266`） | 誰でも、用意された同期対象のソースを読める |
| `blocklist_versions` | `validation_status = 'published'` の場合に public-read（`backend_core.sql:268-272`） | 誰でも、公開済みバージョンのメタデータを読める |
| `bug_reports`、`mirror_events` | 明示的な `using(false)`（`20260516034136_backend_core_advisor_fixes.sql`） | anon／authenticated のアクセス無し — Worker は service role を使う |
| `qa_developers` | RLS 有効 ＋ **anon, authenticated からすべて revoke** | service-role 専用。QA 許可リストはクライアントから決して読めない |

この分け方が重要です: 匿名の不具合レポートは、クライアントから *読める* ことなく Worker から *挿入できる* 必要があり、QA 許可リストは service role からしか読めてはいけません。

### 4.3 認証と暗号化バックアップのエンベロープ {#43-auth--the-encrypted-backup-envelope}

**認証** は任意です。サインインは **Apple ＋ Google のみ**（メール／パスワードは **取り下げ**）。どちらもネイティブの `id_token` グラントを使い、ハッシュ化された nonce 付きで Supabase Auth の `auth/v1/token?grant_type=id_token` で交換します。アプリは、その結果のセッションを端末上の Keychain にローカルにのみ保存します。クライアント側のフローは iOS アプリにあります（`lavasec-ios: LavaSecApp/AccountAuthService.swift`、`lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`）— アカウント／バックアップの全体モデルは [アカウントとバックアップ](./accounts-and-backup.md) を参照してください。

> **ゼロ知識バックアップ:** クライアント側の AES-256-GCM エンベロープ。暗号文＋秘密でないメタデータだけが Supabase の `user_backups`（ユーザーごとの RLS）にアップロードされます。サーバーはユーザーが保持する秘密なしには復号できません。

重要なバックエンドの事実: **iOS クライアントは、ユーザーごとの RLS の下で、Supabase PostgREST 経由で `user_backups` を直接読み書きします**（`user_id` でアップサートし、アクセストークンでスコープされます）。Worker には `/v1/backup` ルートは一切ありません。Worker が `user_backups` に触れるのはちょうど1回だけ: アカウント削除時に削除するときです（`deleteAccount`）。

`user_backups` が保存するのは、不透明な暗号文＋秘密でないエンベロープのメタデータ（KDF パラメータ／ソルト、nonce、key-slot ラベル、クライアントのスキーマヒント）だけです。サイズ上限（`20260605000000_tighten_backup_envelope_constraints.sql`）: 暗号文は ≤ 262144 バイト（256 KiB）／ ≤ 349528 文字、メタデータは ≤ 32768 バイト（32 KiB）。DB は平文の設定・パスワード・フレーズ・鍵を決して保存しません。

### 4.4 アカウント削除 {#44-account-deletion}

`POST /v1/account/delete` はユーザーのアクセストークンを検証し、その後そのユーザーの `bug_reports`（および一致するレガシーな R2 添付オブジェクト）、`user_backups`、`entitlements`、`user_settings`、`profiles` の行を削除し、最後に service-role の `/admin/users` エンドポイント経由で Supabase Auth のユーザーを削除します。返すのは削除ステータス＋紐づいたプロバイダだけです。ステータス: **実装済み**（プランのフロントマターは `status: Done` で、ファイルは `plans/implemented/` にあります。古い **本文中の** 注記には今も「Backlog」とありますが、レーンフォルダ＋コードの存在から出荷済みです）。

### 4.5 App Store エンタイトルメントのミラーリング {#45-app-store-entitlement-mirroring}

`POST /v1/account/entitlements/app-store-sync` は、クライアント検証済みの StoreKit トランザクション JWS から `entitlements` 行（プラン `lava_security_plus`）を、`user_id` で衝突したらアップサートします。保存される `verification_status` は文字どおり `"client_verified_storekit"` です — サーバーは JWS を **再検証しません**。許可される product ID: `lava_security_plus_{monthly,yearly}`。

> ミラーリングは **実装済み**。 **サーバー側の JWS 検証は予定**（まだ作っていません）。署名済みの JWS は後で検証するために保存されます。他のところでのプランモデルにも注意: アプリのエンタイトルメントはローカル（`isPaid`）で、真実の源としての **バックエンド同期はまだありません** — この行はミラーであって、ゲートではありません。

## 5. パスキー支援の復元（ゼロ知識） {#5-passkey-assisted-recovery-zero-knowledge}

パスキー支援のバックアップ復元は **ゼロ知識** で、完全にクライアント側です。復元用の鍵素材は、パスキーの **WebAuthn PRF / hmac-secret** 出力から端末上で導出されます。サーバーは復元の秘密を **一切** 保存せず、パスキーを **一切** 登録せず、WebAuthn のチャレンジを **一切** 発行しません。サーバーがゲートするエスクローの経路はありません。

以前の設計が使っていたエスクローテーブル（`backup_passkey_recovery`、`backup_passkey_challenges`）はローンチ前に削除され、Worker には `/v1/backup/*` ルートも WebAuthn／パスキーのコードもありません。（Worker の `package.json` には `@simplewebauthn/server` のエントリが、使われていない残りものの依存として残っています。）

クライアント側は iOS アプリにあります: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` が PRF 対応のパスキーの作成／アサーションを駆動し、`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` が hmac-secret 出力からスロットを導出します。PRF 出力はアサーションの間だけ読まれ、端末から決して出ません。PRF 非対応のパスキープロバイダはゼロ知識スロットを支えられないので、セットアップは早い段階で失敗し、ユーザーはリカバリーフレーズにフォールバックします。ステータス: **実装済み**。

## 6. lavasec-email Worker {#6-lavasec-email-worker}

受信して転送するだけです。`support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` を検証済みの運用者の受信箱へ転送し、未知の宛先と 10 MiB を超えるメールを拒否し、 **メール本文を保存しません**。サポートの自動返信はコードはありますが、有料の Cloudflare アウトバウンドメールの後ろにゲートされています（先送り）。ルーティングの定数は `email-service.ts:9`（`ROUTED_RECIPIENTS`）にあり、受信ハンドラは `handleInboundEmail` です。ステータス: **実装済み**（自動返信の経路は **予定**／先送り）。

## 7. 設定とデプロイ {#7-config--deploy}

- **設定は `wrangler.toml` で、これは gitignore されています**。`wrangler.toml.example` がコミット済みのテンプレートです。環境固有の値については、ローカルの `wrangler.toml` を正典として扱ってください。
- **Vars**（秘密でない、`[vars]` 内）: Supabase の URL、公開 API オリジン（`https://api.lavasecurity.app`）、カタログのキャッシュ TTL（デフォルト 300秒）、不具合レポートのサイズ上限、アカウント削除の監査トグル、そして Workers ランタイムのアクセラレーションフラグ。内部の不具合レポートトリアージは、内部のトリアージキューのキーと、トリアージリンクを組み立てるときに使うダッシュボードのオリジンを追加します。
- **Secrets**（`wrangler secret put` 経由）: Supabase の service-role 認証情報、管理者 API キー、そして — 不具合レポートトリアージの経路用に — 課題トラッカーの API キーと、任意のチャット通知 webhook。
- **デプロイは手動**: `npm run deploy` → `wrangler deploy`。Worker 用の CI はありません。
- **Cloudflare のルーティング**: `lavasecurity.app` は Pages のままで、`api.lavasecurity.app` と `*.qa-probe.lavasecurity.app` はこの Worker に解決されます。
- **互換性**: `compatibility_date = "2026-05-16"`、`compatibility_flags = ["nodejs_compat"]`。

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` は vars に設定されていますが、Worker のコードからは参照されていません。これはアプリケーションの設定ではなく、Workers ランタイムのアクセラレーションフラグです。

## 8. プライバシーの不変条件（ここに何があり、何が無いか） {#8-privacy-invariants-what-is-and-isnt-here}

バックエンドを拡張する人向けの簡単なチェックリストです — これらのどれも、ひそかに破ってはいけません:

1. **DNS／ブラウジングのテレメトリは無し。** 日常的な DNS クエリやドメインごとのテレメトリのためのテーブルはありません。フィルタリングは端末上にとどまります。
2. **サードパーティのブロックリストのバイト列は無し** — R2 にも Postgres にも。あるのは `source_url` ＋承認済みハッシュだけです（§3）。
3. **`user_backups` は不透明** — 暗号文＋秘密でないメタデータだけ。Worker ではなくクライアントが RLS の下で書き込みます（§4.3）。
4. **service-role の隔離** — `bug_reports`、`mirror_events`、`qa_developers` について（§4.2）。
5. **すべてのバックアップ経路はゼロ知識** — パスキー支援の復元も含めて。その鍵素材はクライアント側で WebAuthn PRF／hmac-secret 出力から導出されます。サーバーは復元の秘密を保存せず、WebAuthn を一切動かしません（§5）。

## 関連項目 {#see-also}

- [システム概要](./system-overview.md) — システム全体を1ページで。信頼境界も含みます。
- [iOS クライアント](./ios-client.md) — このバックエンドを利用する端末側。
- [アカウントとバックアップ](./accounts-and-backup.md) — クライアント側の認証、AES-256-GCM エンベロープ、key slot、リカバリーフレーズ。
- [DNS フィルタリングとブロックリスト](./dns-filtering-and-blocklists.md) — カタログの端末側: 上流からの直接ダウンロード、解析／正規化、そして filter-rules budget。
- [GPL source-url-only コンプライアンス判断](../legal/gpl-source-url-only-compliance-decision.md) — なぜカタログがバイト列ではなく URL を公開するのか。
- **プランと収益化**（内部） — 本当の無料プラン／Plus のゲートである filter-rules budget（無料プラン 500K / Plus 2M）。
- **IP リスク登録簿**（内部） — source-url-only の背後にある IP／コンプライアンスの根拠。
