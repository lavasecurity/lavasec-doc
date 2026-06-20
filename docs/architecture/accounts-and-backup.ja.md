---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# アカウントとゼロ知識バックアップ

> **対象読者:** エンジニア。
> **権威:** このドキュメントとプランの内容が食い違うときは、**コードが正**——食い違いがある箇所はその都度本文で指摘します。ステータスはプランの理想ではなく、コードで裏が取れている実態を表します。ステータスの凡例: **実装済み**(出荷済みでコードでも確認済み)、**進行中**(一部だけ取り込み済み)、**予定**(設計済みだが未実装)、**取り下げ**(却下または差し戻し)。

アカウントは**任意**です。コアの保護はずっと無料で、アカウントは不要です。サインインがあるのは、あなたの*設定*を暗号化したまま保存しておき、新しいデバイスで復元できるようにするためだけです。このドキュメントでは、認証フロー、セッションの保存場所、ゼロ知識バックアップの封筒、復元の経路、そしてサーバーが見られるもの・見られないものを正確に解説します。

このドキュメントが守ろうとしている、プライバシーに関する根本的な約束はこれです。

> DNS フィルタリングはすべてデバイス上で行われます。Lava があなたの閲覧をサーバー経由でルーティングすることはなく、あなたが訪れたドメインの流れを受け取ることもありません——バックエンドが持っているのは、カタログのメタデータ、ユーザーごとの中身の見えない暗号化バックアップ、そしてあなたが送信を選んだ匿名化済みの診断情報だけです。

コンポーネントの分担: 純粋な暗号処理とリクエストの組み立ては `LavaSecCore` に、オーケストレーションと UI は `LavaSecApp` にあります。関連ページ: [システム概要](./system-overview.md)、[iOS クライアント](./ios-client.md)、[バックエンドとデータ](./backend-and-data.md)、[DNS フィルタリングとブロックリスト](./dns-filtering-and-blocklists.md)。

---

## 1. 認証フロー {#1-authentication-flow}

**プロバイダーは Apple と Google のみ。** **(実装済み)** `AccountAuthProvider` が列挙しているのはちょうど `.apple` と `.google` だけです(`AccountAuthService.swift`)。メール/パスワード——および認証を迂回するサポート主導の復元手段——は明確に**取り下げ**です。パスワードを自前で持つと、リセット/MFA/ロックアウト/漏洩対応といった義務が増えますが、Apple/Google で足りる以上、その複雑さに見合いません。また迂回型の復元はゼロ知識の保証を壊してしまいます。

両プロバイダーとも、Supabase Swift SDK でも web OAuth でもなく、**ネイティブの `id_token` グラント**を使います。

1. **ネイティブでサインインする。** Apple は AuthenticationServices 経由、Google は GoogleSignIn SDK 経由。それぞれがプロバイダーの `id_token`(Google はアクセストークンも)を返します。アプリは CSPRNG で生の nonce を生成し、SHA256 でハッシュ化してプロバイダーに渡すので、発行される `id_token` はその nonce に紐づきます。**(実装済み)**
2. **Supabase で交換する。** `SupabaseIDTokenAuth`(`LavaSecCore`)が Supabase Auth の `auth/v1/token?grant_type=id_token` 宛てに生の `URLRequest` を組み立て、`provider` + `id_token` + 任意の `access_token` + **生の** nonce(Supabase が紐づけを検証してリプレイを弾けるように)を `apikey` ヘッダー付きで POST します。SDK は使わないので、`LavaSecCore` はネットワーク/認証の依存を抱えずに済みます。**(実装済み)**
3. **セッションを受け取る。** Supabase はトークンを検証し、セッション——アクセストークン、リフレッシュトークン、有効期限、ユーザーレコード(provider/providers)——を返します。リフレッシュは同じヘルパーを `grant_type=refresh_token` で使います。

`AccountAuthService`(`@MainActor`、`LavaSecApp`)がこれら全体を取り仕切ります——ネイティブのフローを走らせ、交換を実行し、セッションを保存・更新し、`AccountAuthState` を公開し、Worker 経由のアカウント削除を進めます。

```
Apple / Google (native id_token + raw nonce)
        │
        ▼
SupabaseIDTokenAuth  ──POST──▶  Supabase Auth  auth/v1/token?grant_type=id_token
        │                              │
        ▼                              ▼
AccountAuthService  ◀────── session (access + refresh tokens, expiry, user)
        │
        ▼
AccountSessionKeychainStore  (Keychain, device-local)
```

---

## 2. セッションと Keychain への保存 {#2-session--keychain-storage}

サインインから永続化される**唯一**のものは Supabase のセッション——アクセストークンとリフレッシュトークンを JSON にしたもの——です。Supabase Auth のユーザーと、あなたが所有する行を超えて、あなたが誰かをサーバー側で写し取ったものは**ありません**。

- **保存先:** `AccountSessionKeychainStore`(`LavaSecApp`)、Keychain サービス `com.lavasec.account-session`、**プロバイダーごと**に保存(`supabase-session-apple` / `supabase-session-google`、加えて旧アカウントからの移行用)。**(実装済み)**
- **アクセシビリティ:** どのストアも `GenericKeychainStore`(`LavaSecCore`)を共有し、`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` に固定されています。つまり**このデバイス限定で、iCloud には同期されず、デバイスのバックアップにも含まれません**。**(実装済み)**

同じ `GenericKeychainStore` の仕組みが 3 つのストアを支えています: アカウントセッション、バックアップのロック解除材料(`BackupKeychainStore`、サービス `com.lavasec.zero-knowledge-backup`)、そしてアプリのパスコードです。いずれも iCloud キーチェーン経由では同期されません。

> **未解決のレビュー項目(主張する挙動ではありません):** 現在のアクセシビリティクラスには生体認証/ユーザー存在のゲートがありません(`SecAccessControl` の `.userPresence`/`.biometryCurrentSet` なし)。ロック解除材料を存在確認ゲート付きのアクセスコントロールに締めるかどうかは、リリースゲートのレビュー項目として追跡しています。今日出荷されている値は after-first-unlock-this-device-only です。**(予定)**

---

## 3. ゼロ知識バックアップ {#3-zero-knowledge-backup}

### 3.1 これが正確には何なのか {#31-what-it-is-precisely}

暗号化バックアップをオンにすると、**iOS クライアント**があなたの*設定*を最小化したコピーを暗号化し、暗号文と秘密でないメタデータだけを Supabase にアップロードします。平文と復号用の秘密が存在する場所は、スマートフォンだけです。

> **ゼロ知識バックアップ:** クライアント側の AES-256-GCM 封筒。ランダムなペイロードキーは鍵スロットごとにラップされます——パスワード/コード/デバイス/支援スロットには PBKDF2-HMAC-SHA256(21万回反復)、PRF パスキースロットには HKDF-SHA256 を使います。Supabase の `user_backups`(ユーザーごとに RLS)にアップロードされるのは暗号文 + 秘密でないメタデータだけです。サーバーはユーザーが持つ秘密なしには復号できません。パスキースロット**も**ゼロ知識です: そのアンラップ鍵は authenticator の WebAuthn PRF(`hmac-secret`)出力からデバイス上で導出され、サーバーはパスキーの秘密を一切持ちません(§4.3 参照)。

### 3.2 何がバックアップされるのか(最小化されたペイロード) {#32-what-gets-backed-up-the-minimized-payload}

`BackupConfigurationPayload`(`LavaSecCore`)が封をされる平文です。意図的に小さく作られていて、`AppConfiguration` と相互変換できます。**(実装済み)**

**含まれるもの:** 有効化されたブロックリストの **ID**(カタログへの参照であって、リストのバイト列ではありません)、許可したドメイン/ブロック済みドメイン、リゾルバープリセット / カスタムリゾルバー、ローカルログの設定、LavaGuard 台帳、保護のヒント、そしてカスタムブロックリストのソースメタデータ。

**除外されるもの:** `isPaid`(エンタイトルメントはローカル)、QA フラグ、診断、フィルターのスナップショット、そしてブロックリストの中身そのもの(カタログ ID で参照するだけ)。あなたの閲覧履歴と DNS クエリは、デバイスが日常的なテレメトリーの流れとしてそれらを記録しないので、このペイロードには決して含まれません。

### 3.3 封筒(クライアント側の暗号処理) {#33-the-envelope-client-side-crypto}

`ZeroKnowledgeBackupEnvelope`(`LavaSecCore`)が暗号処理を実装しています。**(実装済み)**

1. **ペイロードの暗号化。** 最小化されたペイロードは、ランダムな **32 バイトのペイロードキー**(`SecRandomCopyBytes` で生成)のもとで **AES-256-GCM** によって一度だけ封をされます。
2. **鍵のラップ(鍵スロット)。** その単一のペイロードキーは、秘密ごとに 1 つずつ、1 つ以上の**鍵スロット**へ独立してラップされ、ペイロードキーのコピーを AES-GCM でラップします。どれか 1 つのスロットの秘密だけでバックアップ全体が解錠できます。ラップ鍵の導出はスロットの種類ごとに異なります: `password` / `recoveryPhrase` / `keychain`(デバイス)/ `assistedRecovery` の各スロットは **PBKDF2-HMAC-SHA256、21万回反復**(本番; `defaultPasswordIterations = 210_000`)を、スロットごとに新しい 16 バイトのランダムソルトとともに使います。`passkey` スロットは authenticator の PRF 出力に対する **HKDF-SHA256**(info `"LavaSec passkey backup PRF v1"`)を使い、復元時に同じ出力を再現できるよう、秘密でない PRF ソルトをスロットに保存します。
3. **スロットの種類。** 封筒は 5 種類のスロットに対応します: `password`、`recoveryPhrase`、`keychain`(デバイスの秘密)、`assistedRecovery`、`passkey`。

出荷されているセットアップは**パスワードレス**(`makePasswordless`、`AppViewModel.turnOnEncryptedBackup` が駆動)です。これは **`keychain`(デバイス)スロット + `assistedRecovery` スロット + 任意の `passkey` スロット**を作ります。`password` / `recoveryPhrase` のファクトリーと復号メソッドは、レガシー/後方互換の封筒のためにまだ存在します(動かすのはテストだけ)が、稼働中の UI がパスワードのみの封筒を作ることは決してありません——パスワードバックアップは未出荷だと考えてください。**(実装済み; パスワードスロットは稼働フローからは取り下げ。)**

**完全性 / ダウングレード防止:** `envelopeVersion` は `1` に固く固定され、各スロットの KDF も種類ごとに固定されています——パスワード/コード/デバイス/支援スロットは `PBKDF2-HMAC-SHA256`、PRF パスキースロットは `HKDF-SHA256`。サポート外のバージョンや KDF の不一致は拒否されるので、偽造されたりダウングレードされたりしたメタデータでアンラップを弱めることはできません。**(実装済み)**

### 3.4 アップロードと保存 {#34-upload--storage}

`BackupSyncService`(`SupabaseBackupSyncService`、`LavaSecApp`)が封筒を Supabase の PostgREST テーブル `user_backups` へ**直接**アップロードし、`user_id` で upsert します。スコープはユーザーのアクセストークンで絞られます。**封筒のアップロード用の Worker ルートはありません**——クライアントは RLS のもとで Supabase に直接話しかけます。Worker が `user_backups` に触れるのは、アカウント削除時にそれを消すときだけです。**(実装済み)**

`user_backups` に入るもの:

- **暗号文**、そして
- **秘密でないメタデータだけ:** 暗号方式名、鍵スロットのレコード(ソルト、反復回数、ラップ済みの鍵、スロットのラベル)、`server_recovery_share`、`createdAt`、そしてバイトサイズ。

この行は**行レベルセキュリティ**で守られています: 各行はその所有者だけが読み書きでき(`auth.uid() = user_id`)、匿名ロールにはアクセス権がありません。サイズは DB レベルで暗号文 ~256 KiB / メタデータ 32 KiB に上限が設けられています(`20260518000000_zero_knowledge_backups.sql`、`20260605000000_tighten_backup_envelope_constraints.sql` で締め直し)。**(実装済み)**

### 3.5 保証——サーバーが見られるものと見られないもの {#35-the-guarantee--what-the-server-can-and-cannot-see}

**サーバーが保存するもの:** 暗号文、KDF のソルト/反復回数、ラップされた鍵スロット、`server_recovery_share`、そしてわずかな秘密でないフィールド(暗号方式、サイズ、タイムスタンプ)。

**サーバーが決して受け取らず保存もしないもの:** 平文の設定/ドメイン/DNS の好み、リカバリーコード、いかなるバックアップパスワード、そしてアンラップされたペイロードキー。

**したがって:** Supabase はユーザーが持つ秘密なしには**バックアップを復号できません**。3 つの復元経路——デバイス鍵スロット、リカバリーコード(サーバーシェアと組み合わせ、§4.2)、パスキースロット(authenticator の PRF 出力、§4.3)——はすべて**デバイス上で**復号され、サーバーはそのどれについても復号用の秘密を持ちません。これはマイグレーションのコメントとプライバシープランで明言されており、テストもされています(封筒のテストは、アップロードされる形に平文のドメイン/URL が漏れないことを確認しています)。

**正確な脅威モデルの注意——過大に主張しないこと。** **支援復元**スロットについては、サーバーは `server_recovery_share` *と* ラップされた `assistedRecovery` スロットの*両方*を `user_backups` に保持しています。サーバーに欠けている唯一のものは、ユーザーのリカバリーコードで、これを Lava が受け取ることはありません。ですからサーバーが完全に侵害された場合、リカバリーコードのエントロピー(~105 ビット、§4.1 参照)に 21万回反復の PBKDF2 のコストを加えたものが、そのスロットをオフラインで総当たりされるのを防ぐ**唯一の**壁になります。これは意図的なものです(支援復元は設計上の二要素——どちらの半分も単独では復号できません)が、リカバリーコードのエントロピーは飾りではなく、要を担っているということです。`keychain`(デバイス)スロットの秘密はデバイスから出ないので、サーバー侵害には一切さらされません。

---

## 4. 復元 {#4-recovery}

バックアップは復元できてこそ役に立ちます。`restoreEncryptedBackup`(`AppViewModel` 内)は、使えるスロット——デバイス鍵、リカバリーコード、パスキー——を順に試して復号します。どのモードでも封筒はローカルで読み込まれ(または Supabase から取得され)、そのうえで**デバイス上で復号**されます——サーバーが復号することはありません。

### 4.1 リカバリーコード {#41-recovery-phrase}

`BackupRecoveryPhrase`(`LavaSecCore`)は `SecRandom` から棄却サンプリングを使って **8 語の CVCV コード**(子音-母音-子音-母音)を生成し(~13.2 ビット/トークン → **合計 ~105 ビット**)、小文字に正規化します。**(実装済み)** 復元では、スロットを試す前に解析/正規化を通すことで、ユーザーの書式(スペースや大文字小文字)を許容します。

これはユーザーの**デバイス外**の復元要素です——ユーザーが保存するもので、アップロードはされません。プライバシー強化(§5)に従い、コードのコピーは**任意**で、使う場合もグローバルなペーストボードに露出させるのではなく、ローカル限定 / 期限切れ(10 分)のペーストボードを通します。

### 4.2 支援復元(二要素の組み合わせ) {#42-assisted-recovery-the-two-factor-combination}

リカバリーコードだけでは `assistedRecovery` スロットは解錠**できません**。スロットの秘密は**両方**の半分から導出されます:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

実際の UTF-8 入力では、3 つのセグメントは **NUL バイト(`0x00`)の区切り**で連結されます——つまりハッシュ化される文字列は `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` であり、上記の `‖` はただの連結ではなく NUL 区切りの連結を表します。`serverRecoveryShare` は封筒のメタデータとしてサーバー側に保存されるランダム値、`normalizedPhrase` はユーザーのリカバリーコードです。**どちらの半分も単独では復号できません**——復元にはサーバーシェア(バックアップとともに取得)*と* ユーザーが持つコードの両方が必要です。**(実装済み)**

### 4.3 パスキー復元——ゼロ知識、PRF 由来 {#43-passkey-recovery--zero-knowledge-prf-derived}

任意の `passkey` スロットはハードウェアに裏打ちされた要素を加えるもので、**ゼロ知識**です: そのアンラップ鍵は authenticator の WebAuthn PRF(`hmac-secret`)出力から**デバイス上で**導出されます。サーバーはパスキーを登録せず、WebAuthn のチャレンジを発行せず、復元用の秘密も保存しません——サーバー側の解放ステップは存在しません。

- **登録/アサーション:** `BackupPasskeyCoordinator`(`LavaSecApp`)が `ASAuthorizationPlatformPublicKeyCredentialProvider` を使って WebAuthn を走らせます。relying party は **`lavasecurity.app`**、資格情報ごとのソルトで PRF 拡張を要求し、ユーザー認証を必須にします。
- **鍵の導出(ゼロ知識):** authenticator は PRF 出力を返しますが、それは**デバイスから決して出ません**。`ZeroKnowledgeBackupEnvelope.makeWithPRF`(`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`)が、その PRF 出力からスロットのラップ鍵を HKDF-SHA256 で導出し(info `"LavaSec passkey backup PRF v1"`)、ペイロードキーを AES-GCM でラップします。スロットに保存されるのは秘密でない PRF ソルトと資格情報 ID だけです。復元時は `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` が資格情報を再アサートして同じ PRF 出力を再現し、`decryptWithPasskeyPRFOutput` がスロットをローカルでアンラップします。サーバーはパスキーの秘密を**一切**持たないので、サービスロールのどの経路でもパスキー保護されたバックアップは復元できません。

以前のエスクロー設計(サービスロールの `backup_passkey_recovery` テーブルにサーバー側の `recovery_secret` を保持し、加えて `backup_passkey_challenges` テーブルと `/v1/backup/passkeys/*` の Worker エンドポイントを置く方式)は**取り下げ**ました: これらのテーブルはバックエンドのマイグレーションで削除され、Worker にパスキー関連のルートはなく、`lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` は `BackupPasskeyRecoveryService` やサーバーエスクローの経路が存在しないことを明示的に主張しています。**(実装済み)**

> **本番対応の注意:** 保存されたパスキーを、物理デバイス上で完全に本番対応した復元可能な要素として扱うには、いまだに `lavasecurity.app` の webcredentials 関連付けに依存します。iOS 側は宣言済みです——`lavasec-ios: LavaSecApp/LavaSecApp.entitlements` が `webcredentials:lavasecurity.app` を持っています——そしてサーバー側(`apple-app-site-association` ファイルとヘッダー)はマーケティングサイトでホストされるようになりました。その関連付けがあるデバイスで解決するまでは、webcredentials 関連付けの経路は失敗することがあり、`BackupPasskeyError.webCredentialsAssociationUnavailable` を返します。パスキー要素そのものは実装済みですが、実機でのエンドツーエンドの準備度は**予定**です。

---

## 5. データ最小化とプライバシーの姿勢 {#5-data-minimization--privacy-posture}

- **任意のアカウント。** 保護はアカウントなしで動きます。サインインは設定のバックアップを有効にするだけです。
- **平文はローカルだけ。** 平文の設定と復号用の秘密が存在する唯一の場所はスマートフォンです。Supabase が持つのはユーザーごとに中身の見えない封筒 1 つだけです。
- **最小化されたペイロード。** バックアップされるのは §3.2 の設定だけで、`isPaid`、QA フラグ、診断、スナップショット、ブロックリストの全バイト列は除外されます。ブロックリストはカタログ ID で参照され、決して埋め込まれません。
- **閲覧/DNS のテレメトリーなし。** 日常的な DNS クエリやドメインごとのテレメトリーのためのサーバー側テーブルはありません。フィルタリングはデバイスにとどまります。
- **ロック解除材料はデバイスローカル。** バックアップのロック解除材料は `…ThisDeviceOnly` のアクセシビリティで保存され、iCloud には同期され**ません**。これは元のプランの同期可能 Keychain 設計を**ひっくり返した**もので、Lava がロック解除材料を iCloud 経由でこっそり同期することはありません(`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`)。**(実装済み; 以前のプランを覆す。)**

### アカウント削除 {#account-deletion}

削除は**実装済み**で、クライアントが直接削除するのではなく、認証済みの Worker エンドポイントを通して行われます。`AccountAuthService.deleteAccount` がユーザーのアクセストークンを `POST /v1/account/delete` に送り、`lavasec-api` Worker(サービスロール)がそのユーザーの `bug_reports`(およびその R2 添付)、`user_backups`、`entitlements`、`user_settings`、`profiles` の各行を削除し、続いて管理 API 経由で Supabase Auth のユーザーを削除して、削除ステータス + 連携プロバイダーだけを返します。その後アプリはローカルでサインアウトし、バックアップのロック解除材料をクリアします(`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`)。

> 注: 削除プランの YAML フロントマターはすでに `status: Done` と書かれており、`plans/implemented/` に置かれています。**本文中**の古い注記には `Status: Backlog.` とありますが、レーンフォルダーのルール(フォルダーが権威)とコードの存在(アプリと Worker の両方が存在)に従い、この機能は**実装済み**です。本文中のその行はドキュメントのバグであって、フロントマターではありません。

---

## 6. ステータスまとめ {#6-status-summary}

| 領域 | 詳細 | ステータス |
|---|---|---|
| Supabase 経由の Apple / Google `id_token` サインイン | ネイティブフロー、ハッシュ化した nonce、生の URLRequest での交換 | 実装済み |
| メール/パスワードサインイン | パスワードを自前で持つことは却下 | 取り下げ |
| Keychain 内のセッション(デバイスローカル、プロバイダーごと) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | 実装済み |
| AES-256-GCM 封筒 + PBKDF2-HMAC-SHA256(21万)鍵スロット | クライアント側; 暗号文 + 秘密でないメタデータだけを `user_backups`(RLS)へ | 実装済み |
| パスワードレスのセットアップ(デバイス + 支援復元 + 任意のパスキースロット) | `makePasswordless` | 実装済み |
| 稼働フロー内のパスワード鍵スロット | テスト用にのみ `LavaSecCore` に残存 | 取り下げ |
| リカバリーコード(8 語 CVCV、~105 ビット) | デバイス外の要素 | 実装済み |
| 支援復元(サーバーシェア + コードを SHA256、NUL 区切り) | 二要素; どちらの半分も単独では不可 | 実装済み |
| パスキー復元(ゼロ知識、WebAuthn PRF/`hmac-secret`、RP `lavasecurity.app`) | PRF 出力から HKDF 導出したスロット、サーバー秘密なし | 実装済み |
| ハードウェア上で本番対応の要素としてのパスキー | webcredentials 関連付けが必要(AASA はマーケティングサイトでホスト) | 予定 |
| アカウント削除(認証済み Worker、サービスロール) | バックアップ/設定/エンタイトルメント/プロフィール/添付 + Auth ユーザーを削除 | 実装済み |
| ロック解除材料への生体認証/ユーザー存在ゲート | リリースゲートのレビュー項目 | 予定 |
| `AppViewModel` からの `EncryptedBackupCoordinator` 切り出し | モジュール化のみ; セキュリティモデルの変更なし | 進行中 |

---

## 関連 {#related}

- [システム概要](./system-overview.md) — トラスト境界を含め、システム全体を 1 画面で。
- [iOS クライアント](./ios-client.md) — `AppViewModel` と、バックアップを駆動するアプリターゲット。
- [バックエンドとデータ](./backend-and-data.md) — `lavasec-api` Worker、Supabase の RLS、そして `user_backups` の保存。
- [DNS フィルタリングとブロックリスト](./dns-filtering-and-blocklists.md) — リゾルバープリセットとトランスポート。その設定はバックアップのペイロードに含まれます。
