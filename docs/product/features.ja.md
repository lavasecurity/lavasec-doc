---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 機能カタログ

> 対象読者: PM / エンジニア。このカタログで扱うのは、いま実際に**動いている機能だけ**です。設計はしたけどまだ作っていないものは、ここではなく非公開のロードマップに置いてあります。

Lava Security は、プライバシーを最優先に考えた iOS アプリです。NetworkExtension のパケットトンネルを通して、**端末の中だけで**ローカルに DNS をフィルタリングし、悪意のあるドメインや邪魔なドメインをブロックします。技術にあまり詳しくない人（保護者や年配の方など）でも使えるように作ってあり、基本の保護はずっと無料、アカウントもいりません。

下に並ぶどの機能の裏にも、こんなプライバシーの約束があります。

> DNS のフィルタリングはすべて端末の上で行われます。Lava があなたのブラウジングを自社のサーバー経由で流すことは決してなく、あなたがアクセスしたドメインの記録を受け取ることもありません。バックエンドが持っているのは、カタログのメタデータ、ユーザーごとの中身の見えない暗号化バックアップ、そしてあなたが送ることを選んだ匿名化済みの診断データだけです。

## このカタログの読み方 {#how-to-read-this-catalog}

- **無料（Free）** — アカウントも購入もなしで、誰でも使えます。
- **Plus** — Lava Security Plus で解放される、唯一の任意の有料プランです。Plus が解放するのは**カスタマイズだけ**で、基本的な安全機能を制限することは決してありませんし、お金を払ったからといって安全ガードレールを回避できるわけでもありません。
- 行内で印が付いていない限り、どの項目も**実装済み**です。ステータスの見方: **実装済み** = リリース済みでコード上でも確認済み、**予定** = 設計はしたがまだ未実装、**取り下げ** = 不採用または取りやめ。予定・取り下げの項目は、ここではなく非公開のロードマップに記載しています。

各プランの上限の唯一の正となる値は `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` にあります（`FeatureLimits.free` / `FeatureLimits.paid`、`.plus` という別名つき）。Plus 権限の**ゲート**はローカルのフラグ（`isPaid`）で、これが正です。バックエンドは App Store の権限を**ミラー**しますが（`POST /v1/account/entitlements/app-store-sync` が `entitlements` 行を upsert します）、その行はあくまでミラーであってゲートではありません。バックエンドの同期がゲートを動かすことは、まだありません。

---

## 1. 保護と VPN {#1-protection--vpn}

製品の中核です。ローカルで DNS だけを扱うパケットトンネルと、その周りを落ち着いて表す状態モデルです。

| 機能 | プラン | 補足 |
|---|---|---|
| **ローカル DNS 専用パケットトンネル** | 無料 | `LavaSecTunnel`（`NEPacketTunnelProvider`、`com.lavasec.app.tunnel`）が DNS を横取りし、各ドメインを端末上で判定します。ブラウジングのトラフィックが Lava を経由することはありません。トンネルアドレスは `10.255.0.2`、DNS サーバーは `10.255.0.1`。 |
| **フィルター判定の優先順位** | 無料 | `安全ガードレールのブロック > ローカル許可リスト（許可する例外） > ブロックリスト > デフォルトで許可`。不正なドメインはブロックされます。（`FilterSnapshot.decision()`） |
| **クエリの優先順位（ブートストラップ優先）** | 無料 | `リゾルバーのブートストラップ > 一時停止 > フィルター`。リゾルバー自身のホスト名がブロックされることはありません。（`DNSQueryDispatcher`） |
| **フェイルクローズなコールドスタート** | 無料 | 再利用できるスナップショットがないままトンネルをコールドスタートすると、フィルタリングされていない DNS を漏らすのではなく、すべてのトラフィックをブロックする `FailClosedRuntimeSnapshot` を入れます。 |
| **Connect-On-Demand** | 無料 | `NEOnDemandRuleConnect` が保護を維持し、自動で再起動します。接続が確認できた**あとに限って**有効になり、プロファイルのインストール時には有効になりません。オンボーディング未完了の間は無効化されるので、入れたばかりのアプリが、オフにできないトンネルを勝手に立ち上げてしまうことはありません。 |
| **一時停止（5 / 10 分）と再開** | 無料 | 一時停止と再開は `LavaProtectionCommandService` を通り、flock のファイルロック下でリビジョンの重複排除をしながら動きます。 |
| **認証が必要な一時停止** | 無料 | 面ごとにオプトインで設定できるゲートです（`SecurityProtectedSurface.protectionPause`）。一時停止には端末のローカル認証が必要で、認証なしの一時停止はコマンドサービスが拒否し、Live Activity は一時停止ボタンを隠します。 |
| **再接続** | 無料 | トンネルを直接再起動します（コマンドサービスの一時停止パイプラインを通りません）。 |
| **Soft Shield の Guardian 状態モデル** | 無料 | 7 つの表情状態 — `sleeping, waking, awake, paused, retrying, concerned, grateful`（`GuardianMascotAnimation.swift`、LavaSecCore）。6 段階の接続性の深刻度が 4 つの顔にまとまり、アプリ内・オンボーディング・Live Activity で同じように表示されます。 |
| **接続性の評価** | 無料 | 6 段階の深刻度（`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`）が、Lava の顔と状態の表示文言を決めます。 |
| **パフォーマンスの強化** | 無料 | キャッシュ優先のオン、処理中クエリの統合、上限つき並列フェッチ、フラップの統合（ウォーム状態でのオンは、モジュール化の高速化作業で iPhone 15 Pro 上で約 112 ms を計測）。 |

> **端末のガードレール（全員対象、決して有料の壁ではありません）:** すべてのユーザーに対し、プランを問わず `約 326 万ルール` という固定の上限（iOS の拡張ごとのメモリ上限 `約 50 MiB` の下で、常駐 32 MB を目標）を強制します（`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`、`maxFilterRuleCount`）。上限を超える設定は、トンネルが jetsam で落ちるのを待つのではなく、確実に拒否されます（`exceedsDeviceMemoryBudget`）。

---

## 2. ブロックリストとフィルタリング {#2-blocklists--filtering}

何がブロックされるのか、リストはどう選ばれるのか、そしてプランの境界線について。

| 機能 | プラン | 補足 |
|---|---|---|
| **ソース URL のみのブロックリスト** | 無料 | Lava が公開するのは、上流の URL と受け入れ可能なハッシュだけです。リストの**バイト**そのものは、端末が自分で取得・解析します。Lava がサードパーティのブロックリストのバイトを保存・ミラー・変換・配信することは**決してありません**。[GPL ソース URL のみのコンプライアンス判断](../legal/gpl-source-url-only-compliance-decision.md)を参照してください。 |
| **用意されたカタログ（10 ソース）** | 無料で有効化 | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift`（`DefaultCatalog.curatedSources`）: Block List Basic、Block List Project Phishing / Scam / Ransomware、Phishing.Database Active Domains、HaGeZi Multi Light / Normal / PRO mini / PRO、OISD Small。 |
| **無料のデフォルトブロックリスト** | 無料 | 入れたばかりの状態では、**Block List Project Phishing + Scam** が有効になっています（`defaultEnabled: true` の印が付いた 2 つのソース。`DefaultCatalog.recommendedDefaultSourceIDs`）。 |
| **端末上での解析 / 正規化 / 重複排除** | 無料 | `BlocklistParser` は auto/plain/hosts/adblock/dnsmasq に対応し、コメント・空行・不正な行を捨て、完全一致の重複を排除し、リストごとに最大 1,000,000 ルールで打ち切ります。複数ホストの `hosts` 行は、いまや最初の 1 つだけでなく、その行に並ぶ**すべて**のホストをルールとして出力します（parser rules version 2）。 |
| **上流バイトの検証** | 無料 | 取得したバイトは SHA-256 を取り、カタログの `accepted_source_hashes` にチェックサムがある場合だけ受け入れます。不一致なら、Lava は直近の正常なキャッシュにフォールバックするか、フェイルクローズします。 |
| **保護ドメインのフィルター** | 無料 | 解析したどのソースからも、保護対象の Lava / Apple / ID プロバイダーのドメイン（apple.com、icloud.com、lavasecurity.app、google.com、accounts.google.com、…）を取り除きます。これにより、上流のリストがアプリ・トンネル・サインインを壊すことはありません。 |
| **許可する例外（許可リスト）** | 無料 | ユーザーが管理する許可リストで、ブロックリストに載っていてもドメインを許可します。無料の上限は、許可するドメイン 25 件 / ブロックするドメイン 25 件（`FeatureLimits.free`）。 |
| **フィルタールール上限（プランの指標）** | 無料 / Plus | リリースしているプランの指標は、コンパイル後のドメイン**ルール**の合計数です: **無料 50 万 / Plus 200 万**（`lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` の `maxFilterRules`）。以前のリスト数の上限に代わるものです。プランの上限を超える設定は `exceedsTierFilterRuleLimit` を出します。 |
| **より高いドメイン上限** | Plus | 許可するドメイン 1,000 件 / ブロックするドメイン 1,000 件（`FeatureLimits.plus`）。 |
| **カスタムブロックリスト** | Plus | `allowsCustomBlocklists`。カスタムリストは端末で取得・解析され、ローカルにキャッシュされます。Lava のサーバーを経由することはありません。 |
| **ウォーム起動時の成果物の再利用** | 無料 | マニフェストと識別フィンガープリントにより、トンネルはディスク上のコンパクトなスナップショットを再コンパイルせずに再利用できます。入力が変わった場合は（プライバシー上安全な、フィールド名だけの理由とともに）再利用が拒否されます。 |
| **Smart Save（弱める変更だけ確認）** | 無料 | フィルターへの編集のうち、保護を*強める*だけのものや中立なもの（ブロックリストの追加や、ブロックするドメインの追加）はそのまま反映されます。保護を*弱める*編集 — ブロックリストの削除、ブロックするドメインの削除、許可する例外の追加 — は、まずレビュー確認シートを経由します。例外を追加するときは「特に気をつけて」パネルも表示されます（`FiltersView.saveChanges()`、`weakensProtection`）。 |
| **予算メーター（保存可能な選択）** | 無料 / Plus | 選択メーターはカウントを略記し（500K / 1.2M / 2M）、1.10 のソフト上限マージンを使います（リストごとの合計は、重複排除後の和集合を約 7〜10% 多めに見積もります）。許容の範囲内に収まっているカウントは、ソフト上限を超えるまで、たとえば「500K of 500K」と読めるよう丸め込まれます（`FilterRuleBudget`）。 |

> 確定的な上限の強制は、重複排除した和集合に対してコンパイル時に行われます（`FilterSnapshotPreparationService`）。まず端末の上限をチェックし、次にプランの上限をチェックします。選択時の UI メーターは、リストごとの合計に 1.10 のソフト上限の余裕を見て表示します。

---

## 3. 暗号化 DNS {#3-encrypted-dns}

ブロックされなかったクエリのための、リゾルバーのトランスポートとルーティング。

| 機能 | プラン | 補足 |
|---|---|---|
| **5 つのリゾルバートランスポート** | 無料 | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic`（`DNSResolverTransport`）。 |
| **DoH / DoH3** | 無料 | HTTP/3 を優先する URLSession ベースの DoH。UI は、h3 のネゴシエーションが実際に観測された場合**に限って**、たとえば「Quad9 (DoH3)」のように **`DoH3`（スラッシュなし）** と注記します。優先はしますが、約束はしません（`DoHTransport`）。 |
| **DoT** | 無料 | プールされた `NWConnection`（エンドポイントごとに最大 4 本）。アイドルで古くなったら更新し、新しい接続で 1 回だけリトライします。 |
| **DoQ**（カスタムのみ） | Plus | DNS-over-QUIC には**組み込みのプリセットがありません**。**カスタムの `doq://` リゾルバー**経由でのみ使え、カスタム DNS は Plus です。**クエリごとに新しい QUIC 接続**を開きます（4 レーンのプールは同時並行性を生むだけで、ハンドシェイクの再利用ではありません）。接続の再利用は、iOS 26 を最低デプロイ条件として先送りしています。 |
| **プリセットのリゾルバー** | 無料 | Device DNS（デフォルト）、Google Public DNS、Cloudflare 1.1.1.1、Quad9 Secure、Mullvad — 提供がある場合は IP / DoH / DoT のバリエーションで（`DNSResolverPreset.allPresets`）。 |
| **リゾルバーのルーティングとフェイルオーバー** | 無料 | `ResolverOrchestrator` がトランスポートごとにルーティングし、暗号化された経路にエンドポイントがなければプレーン DNS に下げ、バックオフのゲートつきでエンドポイントごとにフェイルオーバーし、最後に Device DNS にフォールバックします。 |
| **デバイス DNS フォールバック** | 無料 | 選んだリゾルバーが使えないとき、いま接続中のネットワークのリゾルバーにフォールバックします。**デフォルトでオン**。`usingDeviceDNSFallback` の深刻度として表示されます。 |
| **カスタム DNS** | Plus | `allowsCustomDNS` — ユーザーが指定するリゾルバー（カスタムプリセット用の DNS スタンプ解析を含む）。 |

---

## 4. アカウントとゼロ知識バックアップ {#4-accounts--zero-knowledge-backup}

任意のアカウントログインと、暗号化された設定バックアップ。どれも保護を使うのに必須ではありません。

| 機能 | プラン | 補足 |
|---|---|---|
| **任意のアカウントログイン（Apple + Google）** | 無料 | ネイティブの id_token フローを Supabase Auth（`grant_type=id_token`）でハッシュ化した nonce つきで交換します。保存されるのは、できあがった Supabase のセッションだけで、端末のローカルの Keychain に置かれます。メール/パスワードでのサインインは、あえて提供していません（取り下げ）。 |
| **ゼロ知識の暗号化バックアップ** | 無料 | クライアント側の AES-256-GCM エンベロープです。ランダムなペイロード鍵は PBKDF2-HMAC-SHA256（21 万回）の鍵スロットでラップされます。Supabase `user_backups` にアップロードされるのは暗号文と秘密でないメタデータだけです（ユーザーごとに RLS）。サーバーは、ユーザーが持つ秘密なしには復号できません。 |
| **最小化されたバックアップのペイロード** | 無料 | 有効なブロックリストの ID、許可した/ブロック済みのドメイン、リゾルバー設定、ローカルログの設定、Lava の見た目などをバックアップします。`isPaid`、QA フラグ、診断データ、スナップショット、ブロックリストのバイトそのものは、はっきりと除外します。 |
| **端末の秘密の鍵スロット** | 無料 | 端末だけの Keychain にある 32 バイトの端末秘密（`...ThisDeviceOnly`、iCloud には同期されません）で、同じ端末への復元をスムーズにします。 |
| **リカバリーコード + アシスト復元** | 無料 | 8 単語の CVCV のコード（約 105 ビット）を、サーバーが持つ復元シェアと SHA256 で組み合わせて、アシスト復元のスロットを解放します。二要素で、どちらか片方だけでは復号できません。 |
| **パスキー復元スロット** | 無料 | 任意の WebAuthn によるスロットで、これも**ゼロ知識**です。ラップを解く鍵は、認証器の WebAuthn PRF（`hmac-secret`）の出力から**端末上で**導出されます（HKDF-SHA256）。サーバーはパスキーを登録せず、チャレンジを出さず、復元の秘密を持たず、パスキーのルートも公開しません。以前のサーバーエスクロー設計は取り下げました。実機での本番運用は、Associated Domains / AASA のホスティング次第です（予定）。 |
| **アカウント削除 / データに関する権利** | 無料 | 認証済みの Worker エンドポイントが、バックアップ・設定・権限・プロフィール・不具合レポートの添付ファイルを削除し、続いて Supabase Auth のユーザーを削除します。アプリはサインアウトし、ローカルのロック解除材料を消します。 |

---

## 5. ウィジェットと Live Activity {#5-widget--live-activity}

ロック画面と Dynamic Island での表示。

| 機能 | プラン | 補足 |
|---|---|---|
| **Live Activity** | 無料 | `LavaSecWidget`（`com.lavasec.app.widget`）: ロック画面と Dynamic Island に出る 1 つの `Activity<LavaActivityAttributes>`（展開時は中央 / compactLeading に Lava / compactTrailing + minimal の状態グリフ）。 |
| **5 状態の保護表示** | 無料 | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — それぞれが Lava のポーズ、SF Symbol、タイトルに対応します。 |
| **Live Activity のアクションボタン** | 無料 | 5 / 10 分の一時停止、再開、再接続 — アプリのプロセス内で `LavaProtectionCommandService` を通って動く `LiveActivityIntent` です。認証つきの一時停止のバリエーションは端末のローカル認証が必要です。 |
| **重複排除・リビジョンゲートつきの単一リコンサイル** | 無料 | `LavaLiveActivityController` は Activity を 1 つに保ち、実際に ID や内容が変わったときだけ更新し、`ProtectionPauseStore` のリビジョンで更新をゲートするので、古い intent のリトライで状態が逆戻りすることはありません。 |
| **Live Activities のトグル** | 無料 | 設定でユーザーが切り替えられます（`setUsesLiveActivities`）。iPhone / iPad のみで利用できます。 |

---

## 6. オンボーディング {#6-onboarding}

初回起動の流れで、ローカル VPN の設定をインストールし、ちょうどよいデフォルトを設定します。

| 機能 | プラン | 補足 |
|---|---|---|
| **複数ページの初回起動フロー** | 無料 | `OnboardingFlowView` — 6 ページ: `lava, guardIntro, features, vpn, notifications, done`。（プロファイルのインストールと通知の確認は、最初にまとめてではなく、適切なステップで行われます。） |
| **ローカル VPN プロファイルのインストール** | 無料 | オンボーディング中にローカル VPN の設定をインストールしますが、Connect-On-Demand は有効にしません。そのため完了時に保護が黙って自動でオンになることはなく、ガードの面が常に正のままです。 |
| **通知許可の確認** | 無料 | 通知のステップで、フロー内で確認します。 |
| **おすすめのデフォルトを適用** | 無料 | Device DNS リゾルバー、デバイス DNS フォールバックをオン、ローカルログをオン（カウント + 履歴 + アクティビティ）、Block List Project Phishing + Scam を有効化、アカウントなしで続ける（`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`、`lavaRecommendedDefaults`）。 |

---

## 7. 設定 {#7-settings}

設定、セキュリティ、診断、フィードバックの面。

| 機能 | プラン | 補足 |
|---|---|---|
| **アプリのロック解除パスコード + 生体認証** | 無料 | `SecurityController`: Keychain にあるソルト付き SHA256 のパスコード照合 + `LAContext` の生体認証。アプリのロック解除をブロックするオーバーレイと、シーンフェーズの変化時のプライバシーマスクつき。 |
| **面ごとの保護** | 無料 | `SecurityProtectedSurface` が 6 つの面をゲートします: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`。それぞれ独立して端末のローカル認証を必要にできます（たとえば設定タブは `.requires(.appSettings)` を返します）。 |
| **Lava ガードの見た目ピッカー（7 種類）** | 無料 | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`。それぞれに対応する Dynamic Island のグリフ色があります。ボトムシートのラジオピッカー（「Choose your Guard」、`LavaGuardLookPickerSheet`）から選びます。まだゲートされている見た目にはロックのグリフが付き、解除／アップグレードのパネルはそのシートの中にあります。 |
| **アプリアイコンに合わせる** | 無料 | 選んだ Lava の見た目に合わせた、任意の代替アプリアイコン。 |
| **外観** | 無料 | ライト / ダーク / システムの配色。 |
| **ローカル限定のログ設定** | 無料 | フィルタリングのカウント、ドメイン履歴（診断）、ネットワークアクティビティのトグル — すべて端末に保存されます。きめ細かいログ（ドメイン履歴 ＋ ネットワークアクティビティ）は **7 日間** のウィンドウに刈り込まれます（`LocalLogRetention.fineGrainedDays = 7`）。カウントと Lava Guard の進捗は、より長く保持されます。 |
| **アクティビティ / ドメインログ（ガードの詳細）** | 無料 | 動的なローカル限定の診断で、ガードタブから開けます（`GuardDestination.activity`）。要約はリクエストの**フロー**です — 「処理されたリクエスト」の合計を、許可 / ブロックの量を示すバーと「ローカルで保護された割合 %」に分けて表示します（正直な丸め: ごくわずかな割合は `<1%`、ほぼ全部の割合は `>99%` と表示します）。**ドメインログ**のセクションには、**上位ドメイン**（最もブロック／許可されたもの、クエリ数で順位づけ）と、**ドメイン履歴**（最近のルックアップと判定）があります。ドメインの行は、履歴をオプトインしたときだけ表示されます。 |
| **フィルター（ガードの詳細）** | 無料 | ガードタブから開ける、ひとつに統合されたフィルター画面です。「マイフィルター」のハブが、ひとつにまとまった **マイフィルター** 画面を開き、ふたつの棚 — **「Lava はこれらをブロックします」**（ブロックリスト ＋ 個別にブロックしたドメイン）と **「Lava はこれらを通します」**（許可する例外）— が、ひとつの編集 / 保存の下書きフローの下に並びます。「Phone → Lava → Internet」のフロー図がタブの先頭に置かれ、マイフィルターを開くとカタログが自動で更新されます。 |
| **ネットワークアクティビティ（設定 → 詳細設定）** | 無料 | ネットワーク / ランタイム / ユーザーの遷移を、上限つきのローカル限定イベントストリームで記録し、App Group で共有します（`NetworkActivityLog`）。アクティビティの面から **設定 → 詳細設定** へ移されました（「Nerd Stats」のあと、`SettingsRoute.networkActivity`）。`.activityViewing` のロックの裏にあり、独自のプライバシーパネル（「この iPhone にとどまります」、7 日間保持）を持ちます。 |
| **不具合レポート** | 無料 | ユーザーが起動するウィザードで、匿名化したバンドルを `POST /v1/bug-reports` に送ります。v1 ではドメイン履歴は含みません。シェイクして報告でも開けます（`RageShakeDetector`）。バンドルにはビルドの出どころ（`appVersion`／`appBuild`／`sourceRevision`）と、接続性の正直なカウンターも含まれるようになりました。 |
| **サブスクリプション管理** | Plus | 契約中のユーザーには、アップグレード画面に「サブスクリプションを管理」（自動更新プラン、`AppStore.showManageSubscriptions` 経由）、「購入を復元」、そして権限の有効期限が表示されます。買い切りのアンロックでは、管理の行は表示されません。 |
| **法的通知 + バージョン** | 無料 | 設定にサードパーティの法的通知（[サードパーティの通知](../legal/third-party-notices.md)を参照）と、バージョン / ビルドのページがあります。 |

---

## アプリのアーキテクチャ（全体像のために） {#app-architecture-for-orientation}

3 つのバンドルが 1 つの App Group `group.com.lavasec` を共有し、そこにコンパイルされる `lavasec-ios: Shared/` のソースフォルダーが一緒に入っています。

- **LavaSecApp**（`com.lavasec.app`） — SwiftUI のアプリシェル。このビルドでは、ルートが 2 タブの `TabView`（**ガード** + **設定**）で、フィルターとアクティビティはガードタブの下の詳細画面として開けます（ネットワークアクティビティは、いまや設定 → 詳細設定の下にあります）。
- **LavaSecTunnel**（`.tunnel`） — 端末上の DNS フィルター / 解決エンジン。
- **LavaSecWidget**（`.widget`） — WidgetKit の Live Activity。
- **Shared/** — ターゲットをまたぐソース（バンドルではありません）: App Group、コマンドサービス、マスコット、Live Activity の属性 / intent。

アプリ ↔ 拡張のあいだの制御には、Darwin 通知ではなく `NETunnelProviderSession` の**プロバイダーメッセージ**（`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`）を使います。フィルタールールは、App Group のスナップショットファイル（`filter-snapshot.json` / `.compact`）としてアプリ → 拡張に渡ります。

---

## 関連ドキュメント {#related-docs}

- ロードマップ — 予定および取り下げの機能（Plus の価格 / StoreKit のポジショニング、Android 版、URL レベルの保護、パスキーの Associated-Domain 対応、隠し要素のミニゲーム、GPL-3.0 のオープンソース公開など）は、この公開カタログではなく非公開のロードマップにあります。
- [GPL ソース URL のみのコンプライアンス判断](../legal/gpl-source-url-only-compliance-decision.md)
- [オープンソースのリストデータの利用規約に関する除外](../legal/open-source-list-data-terms-carveout.md)
- [サードパーティの通知](../legal/third-party-notices.md)
