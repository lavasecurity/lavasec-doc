---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# システム概要 {#system-overview}

> **対象読者:** エンジニア向けです。Lava Security の全体像を1ページにまとめたものです。どんな部品があって、その間でデータがどう流れて、信頼の境界はどこにあるのか、をざっと押さえられます。各コンポーネントの詳細はそれぞれの専用ドキュメントに譲りますが、まずはこのページでシステム全体を頭に入れてから読むとわかりやすいはずです。
>
> **何が正なのか:** このドキュメントとプランの内容が食い違っていたら、**コードが正です**。ステータスはプランの理想ではなく、コードで確認できた現実を反映しています。ページ末尾の [ステータスの凡例](#8-status-legend) を参照してください。

## 1. ひとことで言うと {#1-product-one-liner}

Lava Security はプライバシー最優先の iOS アプリで、DNS を **端末上でローカルに** フィルタリングします。NetworkExtension のパケットトンネルを使い、悪意のあるドメインや迷惑なドメインをブロックします。技術に詳しくない人（保護者や年配の方）のためのものです。コア保護はずっと無料で、アカウントも不要です。

## 2. プライバシーの約束（これが基準） {#2-the-privacy-promise-canonical}

> DNS フィルタリングはすべて端末上で行われます。Lava があなたのブラウジングを自社サーバー経由でやり取りすることはなく、あなたがアクセスするドメインの流れを受け取ることもありません。バックエンドが持っているのはカタログのメタデータ、ユーザーごとの中身が見えない暗号化バックアップ、そしてあなたが自分で送ると選んだ匿名の診断情報だけです。

ここから先のすべては、この一文を本当のものに保つためにあります。アーキテクチャはサーバー側をあえて小さく作ってあります。作業をするのは端末で、バックエンドはクエリを一切見ません。

## 3. コンポーネント {#3-components}

### iOS クライアント（実行ターゲット3つ + 共有コード、App Group は1つ `group.com.lavasec`） {#ios-client-three-executable-targets-shared-code-one-app-group-groupcomlavasec}

| コンポーネント | バンドル / 場所 | 役割 | ステータス |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | SwiftUI のアプリ本体。エントリーポイントで、ガード + 設定の2タブ構成（フィルターとアクティビティはガードの詳細画面。ネットワークアクティビティは設定 → 詳細設定の下に移動）。 | 実装済み |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`。端末上で動く DNS フィルター/解決エンジン。iOS の **拡張あたり ~50 MiB のメモリ上限** の制約を受けます。 | 実装済み |
| **LavaSecWidget** | `com.lavasec.app.widget` | WidgetKit のライブアクティビティ（ロック画面 + Dynamic Island）。 | 実装済み |
| **Shared/** | `Shared/` | ターゲットをまたいで共有するソース。App Group、コマンドサービス、マスコット、ライブアクティビティの属性/インテントなど。 | 実装済み |

**アプリ側のコントローラー（LavaSecApp 内）:**

- **AppViewModel** — アプリ側のコントローラー（いわゆる神オブジェクト）。`NETunnelProviderManager` のライフサイクル、共有状態の永続化、プロバイダーメッセージング、ライブアクティビティの整合、カタログ同期、バックアップ、StoreKit、認証を一手に持ちます。
- **RootView** — ガード + 設定の2タブ `TabView`。フィルターとアクティビティはガードの下の詳細画面として開きます。オンボーディングのゲート役で、セキュリティロックやプライバシーマスクのオーバーレイもここがホストします。
- **SecurityController** — パスコード（Keychain にソルト付き SHA256）+ 生体認証 + 画面ごとの保護。
- **LavaLiveActivityController** — 単一アクティビティの整合役。重複排除とリビジョンによるゲートあり。
- **OnboardingFlowView** — 初回起動時の複数ページのフロー（6ページ: `lava → guardIntro → features → vpn → notifications → done`）。

**LavaSecCore（プラットフォーム非依存の SwiftPM パッケージ、`Sources/LavaSecCore/`）:**

- **FilterSnapshot / CompactFilterSnapshot** — コンパイル済みのフィルター + 判定の優先順位。コンパクト形式は、トンネルが読む mmap しやすいディスク上のアーティファクトです。
- **DNSQueryDispatcher** — クエリの優先順位: bootstrap > pause > filter。
- **ResolverOrchestrator** — トランスポートのルーティング、プレーン DNS への切り下げ、エンドポイントごとのフェイルオーバー、デバイス DNS フォールバック。
- **DoHTransport / DoTTransport / DoQTransport** — 暗号化トランスポートの実行役。
- **FeatureLimits**（`SubscriptionPolicy.swift` 内）— プランごとの上限（これが正）。静的メンバー `.free` / `.paid` 経由で参照します。
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — 端末ガードレールの計算 + マージ後の予算を最終的に強制する役。
- **BlocklistCatalogSync / BlocklistParser** — カタログの取得、アップストリームからの直接ダウンロード、ローカルでのパース/正規化/重複排除、保護ドメインのフィルター。
- **GuardianMascotAnimation** — 7状態のマスコットの状態グラフ（`Shared/SoftShieldGuardian` が描画）。
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — バックアップの暗号処理 + ペイロード。
- **SupabaseIDTokenAuth** — 生の URLRequest による `id_token` 認証（SDK なし）。

### バックエンド {#backend}

| コンポーネント | 役割 | ステータス |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker（`api.lavasecurity.app`）。カタログの読み取り、admin/cron によるブロックリストの同期 + 公開、匿名の不具合レポート、アカウント削除、App Store のエンタイトルメントのミラーリング、QA プローブ。 | 実装済み |
| **lavasec-email Worker** | `@lavasecurity.app` 宛ての受信専用 Cloudflare Email Routing 転送。宛先不明や大きすぎるメールは拒否します。 | 実装済み |
| **Supabase Postgres** | アカウント、`user_backups`、カタログのメタデータ、サービスロール専用テーブル。**公開テーブルはすべて RLS 適用**。 | 実装済み |
| **Cloudflare R2**（本番の R2 バケット。ステージング用には別のプレビューバケット） | カタログのスナップショット + ラウンドロビン同期のカーソル。サードパーティのブロックリストのバイトは **絶対に** 置きません。不具合レポートの添付アップロード経路は削除済み（旧来のオブジェクトはアカウント削除時にのみ削除されます）。 | 実装済み |
| **Cloudflare D1**（ヘルプフィードバック用のデータベース） | 追記専用の、匿名のヘルプ記事フィードバック投票。 | 実装済み |

## 4. データフロー図 {#4-data-flow-diagram}

いちばん大事なポイント: **暗号化された DNS リゾルバーの経路（右側）は、Lava のバックエンド（下側）に一切触れません。** 端末はカタログの *メタデータ* を Worker から取りますが、リストの *バイト* と実際のクエリの流れは、直接サードパーティへ向かいます。

```
                                  YOUR iPHONE
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                                                                             │
 │   ┌──────────────┐   provider messages    ┌───────────────────────────┐    │
 │   │  LavaSecApp  │ ─────────────────────►  │      LavaSecTunnel        │    │
 │   │ (AppViewModel│   (reload-snapshot /    │  (NEPacketTunnelProvider) │    │
 │   │  controller) │    pause / config)      │                           │    │
 │   └──────┬───────┘                         │   DNSQueryDispatcher       │   │
 │          │                                 │   bootstrap > pause >      │   │
 │          │ writes / reads                  │   ┌──────────────────────┐ │   │
 │          ▼                                 │   │  CompactFilterSnapshot│ │   │
 │   ┌──────────────────────────┐  mmap       │   │  guardrail > allow >  │ │   │
 │   │  App Group container      │ ◄──(read)── │   │  block > default-allow│ │   │
 │   │  group.com.lavasec        │            │   └──────────┬───────────┘ │   │
 │   │  • filter-snapshot.compact│            │              │ allowed     │   │
 │   │  • app-configuration.json │            │              ▼             │   │
 │   │  • tunnel-health.json      │           │   ┌──────────────────────┐ │   │
 │   │  • pause/session UserDefs  │           │   │  ResolverOrchestrator│ │   │
 │   └──────────────────────────┘             │   │  DoH3/DoT/DoQ/IP +   │ │   │
 │          ▲                                 │   │  device-DNS fallback │ │   │
 │          │ reads (Live Activity)           │   └──────────┬───────────┘ │   │
 │   ┌──────┴───────┐                         └──────────────│─────────────┘   │
 │   │ LavaSecWidget│                                        │                 │
 │   │ (Dynamic Isl.│                                        │ encrypted DNS   │
 │   │  + lock scr.)│                                        │ (query stream)  │
 │   └──────────────┘                                        │                 │
 └──────────────────────────────────────────────────────────│─────────────────┘
        │ (a) catalog          │ (b) list bytes              │ (c) blocked → NXDOMAIN
        │  metadata            │  (direct from upstream)     │     allowed → forwarded
        ▼                      ▼                             ▼
 ┌──────────────┐   ┌──────────────────────┐    ┌───────────────────────────────┐
 │ lavasec-api  │   │  Upstream blocklists  │   │  Public DNS resolver           │
 │ Worker       │   │  (HaGeZi, OISD,       │   │  (Quad9 / Cloudflare / Google  │
 │ GET /v1/     │   │   Block List Project) │   │   / Mullvad; user-chosen)       │
 │  catalog     │   └──────────────────────┘    └───────────────────────────────┘
 └──────┬───────┘
        │ reads/writes (metadata only)
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  LAVA BACKEND (sees no DNS queries, no browsing history)                   │
 │  • Supabase Postgres: accounts, user_backups (opaque ciphertext), catalog │
 │  • Cloudflare R2: catalog/latest.json, the round-robin cursor             │
 │  • lavasec-email Worker: receive-only @lavasecurity.app forwarding         │
 └──────────────────────────────────────────────────────────────────────────┘
       ▲
       │ (d) optional: encrypted backup envelope (PostgREST, RLS) — ciphertext only
       │     entitlement mirror, anonymous bug reports, account deletion
       └──── from LavaSecApp, only when the user opts in
```

## 5. データの流れ {#5-data-flows}

### A. DNS の経路（クエリごと、すべて端末上で） — 実装済み {#a-the-dns-path-per-query-all-on-device-implemented}

ここがホットパスで、プライバシーの中核です。すべて `LavaSecTunnel` の中で完結し、ここのものが Lava のサーバーに届くことはありません。

1. パケットトンネルが DNS クエリを横取りします（トンネルの DNS サーバーは `10.255.0.1`）。
2. **`DNSQueryDispatcher`** がクエリの優先順位を適用します: **bootstrap > pause > filter**。bootstrap を最優先にするのは絶対のルールで、フィルタリングの前にリゾルバー自身のホスト名を解決します。こうすればリゾルバーが自分自身をブロックすることはあり得ません。
3. bootstrap でもなく一時停止中でもなければ、ドメインを **`CompactFilterSnapshot`** に照らして評価します（App Group から `Data(contentsOf:options:[.mappedIfSafe])` のゼロコピー mmap で読み込みます）。判定の優先順位は **安全ガードレール > ローカル許可リスト（許可する例外）> ブロックリスト > デフォルト許可** です。不正なドメインはブロックされます。
4. **ブロック** → トンネルがその場で応答します（アップストリームに接続しません）。**許可** → クエリは **`ResolverOrchestrator`** に渡されます。
5. `ResolverOrchestrator` は設定されたトランスポート（**`DoH3` / `DoT` / `DoQ` / プレーン DNS（`IP`）**）にルーティングします。バックオフのゲートの裏でエンドポイントごとのフェイルオーバーを行い、暗号化プランにエンドポイントがないときはプレーン DNS に切り下げ、プライマリが応答を返さずプランが許可している場合は **デバイス DNS フォールバック** を行います。
6. リゾルバーの応答が OS に返されます。ユーザーのクエリの流れは **ユーザーが選んだパブリックリゾルバー** にだけ向かい、Lava には決して向かいません。

トランスポートに関する補足（用語はそのまま）: `DoH3`（スラッシュなし）は **h3 のネゴシエーションが実際に観測されたときにだけ** 注記されます。優先するけれど約束はしない、という扱いです。**`DoT`** はエンドポイントごとに最大4本の NWConnection をプールし、アイドルで古くなったら更新 + 新規接続で1回リトライします。**`DoQ`** は **クエリごとに新しい QUIC 接続** を開きます（再利用なし）。4レーンのプールは並行性のためで、ハンドシェイクの再利用のためではありません。接続の再利用は実装して実機テストまでやりましたが、**差し戻し** ました（iOS 26 を最低動作環境にできるまで先送り）。[DNS フィルタリングとブロックリスト](./dns-filtering-and-blocklists.md) を参照してください。

### B. カタログの取得 + ブロックリストの読み込み（source-url のみ） — 実装済み {#b-catalog-fetch-blocklist-load-source-url-only-implemented}

フィルターのルールがどうやって端末に乗るか、という話です。Lava は **source-url だけ** を配る立場です。アップストリームの URL + 受け入れ可能なハッシュだけを公開し、**サードパーティのブロックリストのバイトを保存・ミラー・変換・配信することは一切ありません。**

1. 端末はカタログの **メタデータ** を Worker から取得します: `GET https://api.lavasecurity.app/v1/catalog` → R2（`catalog/latest.json`）からそのまま配信される JSON で、`sources[]` + `guardrails[]` に分かれ、各エントリが `source_url` + `accepted_source_hashes` を持ちます。
2. 有効なソースごとに、端末はリストの **バイトを `source_url` から直接** ダウンロードします（アップストリーム、つまり HaGeZi、OISD、Block List Project など）。Lava からではありません。
3. 端末は SHA256 を計算し、チェックサムが `accepted_source_hashes` にあるバイトだけを受け入れます。一致しなければ直近の正常キャッシュにフォールバックするか、安全側で失敗します（`checksumMismatch`）。
4. **`BlocklistParser`** がローカルでパース/正規化/重複排除します（auto / plain / hosts / adblock / dnsmasq 形式）。その後 **`DomainRuleSet.lavaSecProtectedDomains`** が保護ドメイン（apple.com、icloud.com、lavasecurity.com/.app、google.com、accounts.google.com、…）を取り除くので、アップストリームのリストが Lava/Apple/ID プロバイダーのドメインをブロックすることはあり得ません。
5. **`FilterSnapshotPreparationService`** が重複排除した和集合をマージし、**最終的な予算の強制** を行い（まず端末の上限、次にプラン）、`filter-snapshot.compact` を App Group に書き込みます。
6. `AppViewModel` が `reload-snapshot` のプロバイダーメッセージを送り、トンネルが再読み込みします。

Worker 側もこれを反映します。admin/cron の同期が各アップストリームを取得し、ハッシュ化/件数カウントして、`raw_r2_key = null` / `normalized_r2_key = null` を書き、メタデータだけを再公開します。ブロックリストカタログのモデルとバックエンドの同期経路は [DNS フィルタリングとブロックリスト](./dns-filtering-and-blocklists.md) と [バックエンドとデータ](./backend-and-data.md) で扱っています。

**予算のモデル（2層）:**
- **端末ガードレール（全員対象、決して有料の壁ではない）:** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3,262,236 ルール** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule`。これは ~50 MiB の NE 上限の下に置いた 32 MB のターゲットです。予算を超える設定は、トンネルが jetsam で落ちるに任せるのではなく、確定的に拒否されます。
- **プランの上限（`FeatureLimits`）:** **無料 500K ルール / Plus 2M ルール** で、端末ガードレールより下に効きます。これは旧来の有効リストの **件数** 上限（無料 3 / 有料 10）を置き換えたもので、リスト件数の上限はもう使われていません。

> **デフォルト有効の真実の出どころ:** 出荷されている無料のデフォルトは **Block List Basic** です（`OnboardingDefaults.lavaRecommendedDefaults`）。これは、用意された各ソースの `defaultEnabled` フラグ（`BlocklistSource.recommendedDefaultSourceIDs`）から端末上で導出され、同じ正規のカタログ仕様から生成されるバックエンドのカタログの `default_enabled` 列を反映しています。

### C. バックアップ（ゼロ知識、オプトイン） — 実装済み {#c-backup-zero-knowledge-opt-in-implemented}

任意で、アカウントが前提で、バックエンドに届く唯一のユーザーデータです。しかも **中身の見えない暗号文** としてです。

1. ユーザーは任意でサインインします（Apple または Google のみ。**メール/パスワードは取り下げ**）。ネイティブの `id_token` を Supabase Auth で交換します（`grant_type=id_token`、ハッシュ化した nonce）。保存されるのは結果として得られる Supabase セッションだけで、端末ローカルの Keychain に入ります。
2. **`BackupConfigurationPayload`** が最小化した平文を組み立てます（有効なブロックリストの ID、許可/ブロックしたドメイン、リゾルバーの設定、ローカルログの設定、LavaGuard の台帳）。`isPaid`、QA、診断、ブロックリスト全体は **含めません**。
3. **`ZeroKnowledgeBackupEnvelope`** がそれを **AES-256-GCM** でランダムな32バイトのペイロードキーで封をします。そのキーは秘密ごとの **キースロット** に **PBKDF2-HMAC-SHA256（21万回）** でラップされます。デバイス秘密スロット、補助リカバリースロット、任意のパスキースロットです。任意のパスキースロットは、認証器の **WebAuthn PRF / `hmac-secret`** 出力（HKDF で導出）でラップされます。その出力はクライアントから出ないので、パスキースロットは本当にゼロ知識です。サーバーが持つ値でアンラップできるものは存在しません（`ZeroKnowledgeBackupEnvelope.makeWithPRF`）。
4. **`BackupSyncService`** が **暗号文 + 秘密でないメタデータだけ** を Supabase の `user_backups` に PostgREST 経由で直接アップロードします。ユーザーごとの **RLS** でスコープされます。（Worker のアップロード経路はありません。Worker が `user_backups` に触れるのは、アカウント削除のときに削除する場合だけです。）
5. **復元:** デバイス秘密スロットによる、同じ端末でのシームレスな復元。端末外では、**8語の CVCV リカバリーコード**（~105 ビット）とサーバーが持つリカバリーシェアを SHA256 で組み合わせます（二要素。どちらか片方だけでは復号できません）。あるいは、パスキースロットが封じられていた場合は、クライアント側の WebAuthn PRF / `hmac-secret` 出力で（サーバーが持つ値は一切関与しません）。サーバーがパスキーを登録したり、WebAuthn チャレンジを発行したり、リカバリーの秘密を保存したりすることはありません。

[アカウントとバックアップ](./accounts-and-backup.md) を参照してください。

### D. アプリ ↔ 拡張のコントロールプレーン — 実装済み {#d-app-extension-control-plane-implemented}

3つのプロセス（アプリ、トンネル、ウィジェット）が App Group `group.com.lavasec` を通じて連携します:

- **制御は NETunnelProviderSession のプロバイダーメッセージ** であり、Darwin 通知 **ではありません**。`AppViewModel` が `LavaSecProviderMessage {kind, operationID}` をエンコードして `session.sendProviderMessage` を呼び、トンネルの `handleAppMessage` が kind で分岐します（`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`）。
- **共有ファイル** がルール/設定/ヘルスを運びます（`filter-snapshot.compact`、`app-configuration.json`、`tunnel-health.json`）。**共有 UserDefaults ストア**（`ProtectionSessionStore` / `ProtectionPauseStore`）がセッション + 一時停止の状態を運びます。
- **`LavaProtectionCommandService`** がライブアクティビティ / AppIntent の一時停止/再開コマンドを `flock` のファイルロックの下で実行します。リビジョンの重複排除と、認証が必要な場合の拒否付きです。**再接続はこれを迂回** してトンネルを直接再起動します（`startVPNTunnel`）。
- **Connect-On-Demand** はトンネルが接続済みを確認した *後* にのみ有効化され、プロファイルのインストール時には決して有効化されません。これにより、インストールしたばかりのオンボーディングプロファイルが、オフにできないトンネルを立ち上げてしまうことを防ぎます。

[iOS クライアント](./ios-client.md) を参照してください。

## 6. 信頼の境界とプライバシーを守る設計 {#6-trust-boundaries-privacy-preserving-design}

| # | 境界 | そこを越えるもの | あえて越えさせないもの |
|---|---|---|---|
| 1 | **端末 ↔ パブリック DNS リゾルバー** | 許可された DNS クエリ（暗号化: DoH3/DoT/DoQ、またはプレーンな IP）がユーザーの選んだリゾルバーへ向かいます。 | Lava はクエリの流れを一切見ません。そもそもこの経路にいません。 |
| 2 | **端末 ↔ アップストリームのブロックリストのホスト** | 端末がリストのバイトを `source_url` から直接ダウンロードします。 | Lava はサードパーティのブロックリストのバイトをプロキシ・ミラー・保存しません。 |
| 3 | **端末 ↔ lavasec-api Worker** | カタログの **メタデータ** の読み取り。オプトインの匿名不具合レポート。エンタイトルメントのミラー。アカウント削除。 | DNS クエリも、ブラウジング履歴も、平文の設定もありません。 |
| 4 | **端末 ↔ Supabase** | オプトインの **暗号化バックアップ封筒**（暗号文のみ、RLS 下の PostgREST）。アカウントの行。 | サーバーはユーザーが持つ秘密なしにはバックアップを復号できません。 |
| 5 | **アプリ ↔ トンネル拡張**（端末上） | プロバイダーメッセージ + App Group のファイル/defaults。 | 再利用できるスナップショットがないコールドスタートでは、トンネルは安全側で失敗します。 |

**プライバシーを守る設計の原則（上の表が裏付けです）:**

- **ローカルファーストのフィルタリング。** 判定エンジンとリゾルバーは端末上の NE 拡張の中で動きます。バックエンドは作りからしてメタデータだけです。日常的な DNS クエリやドメインごとのテレメトリのテーブルは存在しません。
- **保護にアカウントは不要。** コア保護はずっと無料で、認証とバックアップは完全にオプトインです。
- **source-url だけの配布。** Lava をサードパーティのリストのバイトから切り離します（GPL/IP コンプライアンス + App Review の安全性）。そして「ミラーのコードなし、Lava のアーティファクト URL なし、R2 へのバイト書き込みなし」を強制する CI ガードレールを維持しています。
- **保存時のゼロ知識バックアップ。** クライアント側の AES-256-GCM。サーバーが持つのは暗号文 + KDF のメタデータ + リカバリーシェアであり、平文も、リカバリーコードも、アンラップ済みのキーも決して持ちません。任意のパスキースロットはクライアント側の WebAuthn PRF / `hmac-secret` 出力でラップされるので、これもゼロ知識です。サーバーが持つ値でアンラップできるものはありません。
- **端末ローカルの秘密。** バックアップ解錠の材料は `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` を使います。iCloud 同期されず、端末のバックアップにも入りません。
- **サービスロールの分離。** `bug_reports`、`mirror_events`、`qa_developers` は anon/authenticated の PostgREST ロールから権限を剥奪してあります。これらに触れるのは Worker（サービスロール）だけです。
- **安全は決して売り物にしない。** 支払いで解放されるのは **カスタマイズだけ** です。許容しない **安全ガードレール** を回避することは決してありません。その整合性は、サーバーの署名ではなく、受け入れ可能な SHA256 ソースハッシュで担保されます。優先順位はどこでも一貫しています: **安全ガードレール > ローカル許可リスト（許可する例外）> ブロックリスト > デフォルト許可。**

## 7. 各コンポーネントのドキュメント {#7-per-component-docs}

> これらはアーキテクチャのドキュメント群の兄弟ドキュメントです。DNS フィルタリングエンジンとブロックリストカタログは、1つのファイルにまとめて書いています。

- [iOS クライアント](./ios-client.md) — ターゲット、App Group、コントロールプレーン、保護状態のモデル、オンボーディング、ライブアクティビティ。
- [DNS フィルタリングとブロックリスト](./dns-filtering-and-blocklists.md) — フィルタースナップショット、判定の優先順位、リゾルバーのトランスポート（DoH3/DoT/DoQ）、メモリ予算、mmap。さらに source-url だけのカタログモデル、カタログの取得、ローカルでのパース/正規化、保護ドメインのフィルター、プランの予算。
- [アカウントとバックアップ](./accounts-and-backup.md) — Apple/Google 認証、ゼロ知識封筒、キースロット、リカバリーコード、クライアント側 WebAuthn-PRF のパスキー復元。
- [バックエンドとデータ](./backend-and-data.md) — lavasec-api + lavasec-email Worker、Supabase のスキーマ + RLS、R2/D1、デプロイ。

## 8. ステータスの凡例 {#8-status-legend}

このドキュメント群はひとつのステータス語彙を使います。**レーンのフォルダが正のステータス** です。プランの中の古いフロントマターはドキュメントのバグであって、ステータスではありません。**コードがプランを上書きします。**

| ステータス | 意味 | プランのレーン | コード |
|---|---|---|---|
| **実装済み** | 出荷済みで、コードで確認済み | `plans/implemented/` | 存在し、配線済み |
| **進行中** | 鋭意構築中。一部は着地済み | `plans/inflight/`、`plans/under_review/` | 一部存在 |
| **予定** | 設計済み、未構築 | `plans/backlog/` | 不在 |
| **取り下げ** | 却下または差し戻し | `plans/dropped/`（または差し戻したコミット） | 不在 / 削除済み |

**このページで触れたもののステータス:**

- **実装済み:** iOS の4つのターゲット + App Group。プロバイダーメッセージのコントロールプレーン。DoH3/DoT/DoQ/IP のトランスポートを使った端末上の DNS フィルタリング。source-url だけのカタログ取得 + ローカルでのパース。フィルタールールの予算（無料 500K / Plus 2M）+ ~3.26M の端末ガードレール。複数ページのオンボーディング。パスコード/生体認証のセキュリティ。重複排除した単一のライブアクティビティ。ゼロ知識バックアップ。Apple + Google 認証。アカウント削除。エンタイトルメントのミラーリング。QA プローブ。`LavaDesignSystem` のトークン層（`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`）。これには `LavaTier` の深さモデル（Floor/Window/Workshop = `calm`/`celebratory`/`technical`）、代表的な画面（例: `SettingsView`）に配線された `.lavaTier(_:)` / `.lavaTierMetadata()` モディファイア、そして `dangerRed` と `LavaSpacing` トークンが含まれます。これらは `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift` でロックされています。
- **進行中:** デザインシステムのトークン層を、より多くの画面へ展開し続けています（`LavaTier` の深さモデルとトークン層は出荷済み。下記参照。ただし専用の `LavaColorRole` はまだ存在せず、アクセントは今も生の色に解決されます）。
- **予定:** Lava Guard のイースターエッグのミニゲーム。マスコットの追加表情（マスコットの状態はちょうど **7** つ）。実機での完全に本番対応のパスキー復元（Associated Domains / AASA）。サーバー側での App Store JWS の再検証（`verification_status` は `client_verified_storekit`）。デザインシステムのアクセントが生の色ではなく意味的なロールを通じて解決されるための専用 `LavaColorRole` トークン。
- **取り下げ:** DoQ の接続再利用（クエリごとに新規接続）。メール/パスワードのサインイン（Apple + Google のみ）。GPL の生 R2 ミラー設計（source-url だけの方式に置き換え）。
