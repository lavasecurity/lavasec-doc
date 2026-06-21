---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# DNS フィルタリングとブロックリスト

> 対象読者: エンジニア。このドキュメントでは、端末上で動く DNS の処理の流れ、暗号化された通信経路を使うリゾルバーのルート、フィルタリングの判定エンジン、そして source-url-only のブロックリストカタログモデルについて、コードが実際に守っている数値とあわせて説明します。記載内容はコードで裏取りした実態を反映しています。プランとコードが食い違っている場合は **コードが正** とし、ズレている箇所はその場で明記します。

DNS のフィルタリングはすべて端末上で行われます。Lava はあなたのブラウジングを自社サーバー経由でやり取りすることはなく、あなたがアクセスしたドメインの流れを受け取ることもありません。バックエンドが持っているのはカタログのメタデータ、ユーザーごとの中身の読めない暗号化バックアップ、そしてあなたが自分で送ることを選んだ匿名化された診断データだけです。

Lava は **ローカルの DNS／ブロックリストによるフィルタリング** であって、あらゆる悪意のあるドメインや URL を必ずブロックすると保証するものではありません。

---

## 1. DNS の処理の流れ {#1-the-dns-pipeline}

フィルタリング／名前解決のエンジンは **NE／パケットトンネル** の中で動きます。具体的には `NEPacketTunnelProvider` の拡張機能 `LavaSecTunnel`（`com.lavasec.app.tunnel`）で、DNS だけを横取りします。トンネルのアドレスは `10.255.0.2`（トンネル）と `10.255.0.1`（DNS サーバー）です。アプリ本体のプロセスはクエリのトラフィックを一切見ません。コンパイル済みの成果物を **App Group**（`group.com.lavasec`）に書き込み、NETunnelProviderSession の **プロバイダーメッセージ**（Darwin 通知ではなく）でトンネルに合図するだけです。

入ってくる DNS クエリごとに、トンネルは `DNSQueryDispatcher`（`Sources/LavaSecCore/DNSQueryDispatcher.swift`）の中で決まった **クエリの優先順位** に従って処理します:

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap を最優先にすることは絶対のルールです。** 設定されたリゾルバー *自身* のホスト名（DoH/DoT/DoQ のエンドポイント）を解決するクエリは、決してブロックも一時停止もしてはいけません。さもないとトンネルは暗号化された DNS を立ち上げることすらできなくなります。ディスパッチャーは各ステップを遅延クロージャとして受け取り、そのステップに到達したときだけ読み込むので、ショートサーキットが保たれます（bootstrap の応答があればスナップショットは読まれず、bootstrap 中は pause も読まれません）。
- **temporary pause** は、ユーザーが始めた一時停止の TTL が有効な間、上流へそのまま転送します。
- **filter** はドメインをコンパイル済みのスナップショットと突き合わせ、転送するか、ブロック応答を合成して返します。

フィルターを通過した（アクション `.allow`）クエリは、リゾルバーのルート（§3）に渡されます。再利用できるスナップショットがないままコールドスタートすると、トンネルは **フェイルクローズ** します。フィルタなしで名前解決する代わりに、すべてのトラフィックをブロックするフェイルクローズ用のランタイムスナップショットを入れます。

---

## 2. フィルタリングエンジン {#2-the-filtering-engine}

### 2.1 判定の優先順位 {#21-decision-precedence}

`FilterSnapshot.decision(forNormalizedDomain:)`（`Sources/LavaSecCore/FilterSnapshot.swift:57-71`）は、安全のための正規の優先順位を適用します:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| 順位 | ルールセット | 結果 | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

正規化に失敗したドメインは、理由 `.invalidDomain` でブロックされます（フェイルセーフ）。同じ優先順位は、ディスク上のバイナリ形式（`CompactFilterSnapshot`）でも同じように再現されます。安全ガードレールがローカルの許可リストの上に来るのは意図的な設計です。**支払いをしても許可できない安全ガードレールを回り込むことはできず**、ユーザーが追加した例外でガードレールのドメインのブロックを解除することはできません。

> 補足: 現在の作業ツリーでは `nonAllowableThreatRules` / `guardrailSources` は空です（`DefaultCatalog.guardrailSources = []`、`BlocklistModels.swift:254`）。優先順位の枠は配線されて有効ですが、ガードレールのエントリーはまだ入っていません。

### 2.2 ルールの保存とメモリ常駐の単位 {#22-rule-storage-and-the-resident-memory-unit}

`DomainRuleSet`（`Sources/LavaSecCore/DomainRuleSet.swift`）は `exactDomains` + `suffixDomains` のセットを保存します。マッチング（`containsNormalized`）は、クエリ時に完全一致の検索に加えて親サフィックスをたどる（`hasSuffix` 方式の）処理を行います。つまり **コンパイル時にサブドメインをまとめてしまうことはありません**。有効なワイルドカード 1 行は **1 ルール** であり、メモリテーブルの 1 エントリーです。この「1 行 = 1 ルール」という対応関係こそが、ルール数を正直なリソース指標にしているものです（§4）。

### 2.3 コンパイル済みスナップショットの形式 {#23-compiled-snapshot-forms}

- **`FilterSnapshot`** — メモリ上のコンパイル済みフィルター: `blockRules`、`allowRules`、`nonAllowableThreatRules`、そしてリゾルバープリセット。
- **`CompactFilterSnapshot`** — トンネルが実際に読み込む、ディスク上のバイナリで mmap に向いた形式（マジック `LSCFSNP1`、`fileVersion 1`）。mmap でゼロコピー読み込みされます（§4.3）。

アプリは `filter-snapshot.json` と `filter-snapshot.compact` の両方を App Group に書き込み、トンネルはコンパクトな方の成果物をデコードします。**ウォームスタートの再利用** ルート（`FilterArtifactStore`）により、トンネルは再コンパイルせずにディスク上のコンパクト成果物を再利用できます。これは識別用のフィンガープリントと、アトミックに書き込まれるマニフェストでガードされており、リゾルバーの通信方式・カタログの範囲・スナップショットの入力が変わった場合は再利用が拒否されます（プライバシー上安全な、フィールド名だけの理由を返します）。

---

## 3. 暗号化された通信経路とリゾルバーのルート {#3-encrypted-transports--the-resolver-path}

### 3.1 通信方式の enum {#31-transport-enum}

ブロックされなかったクエリは、設定された上流リゾルバーに転送されます。`DNSResolverTransport`（`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`）には **5 つ** の値があります:

| 通信方式 | Raw value | UI に表示される注記 |
|---|---|---|
| Device DNS | `device-dns` | *(なし — 名前がそのまま通信方式)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

組み込みのプリセットは Google、Cloudflare、Quad9、Mullvad（それぞれ IP / DoH / DoT の各バリアント）に加えて、Device DNS と Custom です。カスタムリゾルバーは、ふつうの IPv4／IPv6 サーバー、DoH の URL、DoT の URL（`tls://` / `dot://`）、DoQ の URL（`doq://` / `quic://`）、または `sdns://` の DNS スタンプを受け付けます。ユーザー名／パスワードと localhost は拒否されます。DoH/DoT/DoQ は、DoT/DoQ ではポート `853` がデフォルトで、DoH ではパスが必須です。

### 3.2 DoH / DoH3 {#32-doh--doh3}

`DoHTransport`（`Sources/LavaSecCore/DoHTransport.swift`）は `URLSession` を使って DoH を実行します。すべてのリクエストは HTTP/3 を選びます（`request.assumesHTTP3Capable = true`、`DNSOverHTTPSRequest.swift:29`）。Apple のローダーが H2/H1 へネイティブにフォールバックしてくれるので、これで到達可能なリゾルバーが到達不能になることは決してありません。実際にネゴシエートされたプロトコルは `URLSessionTaskTransactionMetrics.networkProtocolName`（ALPN: `h3`、`h2`、`http/1.1`）から読み取ります。

UI は **`DoH3`（スラッシュなし）** を注記します。たとえば「Quad9 (DoH3)」のように。ただし **h3 のネゴシエーションが実際に観測されたときだけ** です（`DoHHTTPVersion.dohAnnotation`）。そうでなければ `DoH` と表示します。DoH3 は優先はされても約束はされません。このラベルは観測にもとづくもので、そのリゾルバーに限ったものであり、保存もされません（「DoH3 確認済み」を再起動をまたいで引き継ぐ挙動は取り下げられました）。リクエストは `application/dns-message` を POST し、応答はコンテンツタイプと長さが検証され、書き戻し前にトランザクション ID が復元されます。

### 3.3 DoT {#33-dot}

`DoTTransport`（`Sources/LavaSecCore/DoTTransport.swift`）はプールされた `NWConnection` を使い、**エンドポイントごとに最大 4 接続**（`maxConnectionsPerEndpoint = 4`）をラウンドロビンで回すので、並列のクエリがヘッドオブラインブロッキングを避けられます。**アイドルによる劣化** の扱いも備えています。Cloudflare のようなプロバイダーはアイドル状態の DoT 接続をサーバー側で（約 10 秒で）状態変化を出さずに閉じてしまうので、**8 秒**（`reusedConnectionMaxIdleInterval = 8`）より長くアイドルだった再利用接続は送信前にリフレッシュされ、再利用接続でタイムアウトが起きた場合は **新しい接続でちょうど 1 回だけ** リトライします。

### 3.4 DoQ — クエリごとに新しい接続 {#34-doq--fresh-connection-per-query}

`DoQTransport`（`Sources/LavaSecCore/DoQTransport.swift`）は **エンドポイントごとに 4 レーン** の限られたプールを保ちますが、**クエリごとに新しい QUIC 接続を開きます** — つまりクエリのたびにフルハンドシェイクが走ります。この 4 レーンのプールが提供するのは **同時実行であって、ハンドシェイクの再利用ではありません**。

**DoQ の接続再利用の状況（取り下げ／先送り）。** 再利用は実機でレビュー・ベンチマークされました（35 クエリに対して 34 回の新規ハンドシェイク ≈ 再利用なし）。その後、iOS 26 ゲートのマルチストリーム `NWConnectionGroup` ルートとして実装し、AdGuard DoQ に対して実機テストしましたが、**差し引きマイナス（ストリーム失敗＋実サーバーに対するフォールバックエラー）として差し戻されました**。RFC 9250 は各クエリをそれ自身の QUIC ストリームに対応づけるため、再利用には `NWConnectionGroup`／`openStream` が必要で、これは **iOS 26.0 以降のみ** です。現在の対応下限は **iOS 17** です。再利用は下限が iOS 26 に達するまで先送りされます。カスタム DoQ は、対応していない端末では拒否されます（「DNS over QUIC is not supported on this device」）。

### 3.5 名前解決のポリシー {#35-resolution-policy}

`ResolverOrchestrator`（`Sources/LavaSecCore/ResolverOrchestrator.swift`）が上流のポリシーを担います:

1. 設定された通信方式による **通信経路のルーティング**。
2. 暗号化されたプランにエンドポイントが 1 つもないときの **plain DNS への格下げ**。
3. バックオフのゲートを伴う **エンドポイントごとのフェイルオーバー** — バックオフ中のエンドポイントは決して通信に出ません（結果は `backed-off`）。
4. プライマリが応答を返さず *かつ* プランがそれを許す場合の **デバイス DNS フォールバック**（プランのプロパティは `shouldFallbackToDeviceDNS` で、設定フィールド `fallbackToDeviceDNS` から導出されます）。結果はデバイスの通信方式として注記し直されます。通信の実行はエグゼキューターの背後に注入されるのでポリシーは単体テスト可能で、バックオフの状態は純粋なポリシーの外側に置かれます。

---

## 4. フィルタールール上限、NE の上限、そして mmap {#4-filter-rules-budget-ne-ceiling-and-mmap}

出荷されているプランの指標は **フィルタールール上限** です。これはユーザーが有効化できる、コンパイル済みドメイン **ルール** の合計数です。これは古い、有効化リストの **件数** の上限（無料 3／有料 10）に取って代わりました。あの件数上限は不誠実な代理指標でした — 1 つのリストは 1K ルールにも 1M ルールにもなりうるからです。**2 つの層** があります: 全員共通の端末ガードレールと、その下にあるプランごとの収益化上限です。

### 4.1 プランごとの上限 {#41-tier-limits}

`FeatureLimits`（`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`）が真実の出どころです:

| プラン | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | カスタムブロックリスト／DNS |
|---|---|---|---|---|
| **無料プラン** | **500,000** | 25 | 25 | なし |
| **Plus**（`.paid` / `.plus`） | **2,000,000** | 1,000 | 1,000 | あり |

プランの上限は収益化の境界であって、**端末ガードレールに対するペイウォールでは決してありません**。**Lava Security Plus** がアンロックするのはカスタマイズだけです — 基本的な安全性は決してアンロック対象ではなく、安全ガードレールも対象ではありません。カスタム（有料）のブロックリストは、ユーザーの端末から直接取得され、ローカルでパース・キャッシュされ、Lava のサーバーを経由することは決してありません。

### 4.2 端末メモリのガードレール ＋ NE の上限 {#42-device-memory-guardrail--ne-ceiling}

パケットトンネルは、iOS の **拡張機能あたり約 50 MiB のメモリ上限** の対象です（これは iOS 15 以降のパケットトンネル向けの、拡張機能タイプごとの OS の設計上の制限で、RAM に比例してスケールするものではありません。端末モデルごとの `com.apple.jetsamproperties.{Model}.plist` にあり、古い端末ではこれより低いこともあります）。これを超えると jetsam が発動します。この上限には API がないので、上限は崖の手前に余裕を残しておきます。

`FilterSnapshotMemoryBudget`（`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`）が、フィルタールール（block + allow + guardrail）を単位として計算します:

| 定数 | 値 |
|---|---|
| `baselineMegabytes` | 4.0 MB（固定のプロセスオーバーヘッド、実測 ≈3.5 MB を切り上げ） |
| `estimatedBytesPerRule` | ルールあたり 9.0 B のダーティ常駐（実測 ≈8.5 B を切り上げ） |
| `maxResidentMegabytes` | 32.0 MB（目標とする上限。観測された ≈40〜46 MB の jetsam の崖の手前に約 10 MB の余裕を残す） |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 ルール** |

この **約 3.26M ルールの端末ガードレール** は、*すべての* ユーザーにとっての固い安全の下限で、どのサブスクリプションのプランよりも上に位置し、**決してペイウォールではありません**。基準となる実測（端末「chimmy」、2026-06-13）: **789,831 ルール → 9.9 MB の `phys_footprint`**、つまり ≈ ベースライン ＋ ルールあたりのコスト、です。

### 4.3 mmap の戦略 {#43-mmap-strategy}

コンパクトなスナップショットは `Data(contentsOf:options:[.mappedIfSafe])`（`LavaSecTunnel/PacketTunnelProvider.swift:4431`、`:4665`）で読み込まれ、`CompactBinaryReader` がゼロコピーのスライスを返します。数メガバイトのドメインテキストの塊は **ファイルバック／クリーン** のまま残り、jetsam にカウントされる `phys_footprint` からは除外されます。常駐メモリのコストになるのはデコード済みの `[Entry]` テーブルだけです（ディスク上は約 6 B/ルール、ダーティ常駐は約 8.5 B）。これにより端末上のドメイン上限が引き上がります: 常駐コストはエントリーテーブルであって、成果物全体ではありません。

### 4.4 2 層の強制 {#44-two-layer-enforcement}

- **権威的（コンパイル時）。** `FilterSnapshotPreparationService`（`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`）は、有効化されたすべてのリストの **重複排除後の和集合** に対して上限を強制します。端末ガードレールが **最初に** チェックされ（固い下限）、プラン上限はその下で効きます。上限を超える設定は決定論的に拒否されます — `exceedsDeviceMemoryBudget` または `exceedsTierFilterRuleLimit` — トンネルを jetsam させる代わりに。エラーは寄与の大きいリスト上位 2 つの名前を挙げるので、直し方が一目で分かります。
- **助言的（選択時の UI）。** `FilterRuleBudget`（`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`）は、リストごとの **合計** に **1.10 のソフト上限マージン** を掛けて選択メーターを動かします。このマージンは、リスト間で約 7〜10% の重複カウントが起きること（リストごとの合計が重複排除後の和集合を多めに見積もること）を補うためのものです。

### 4.5 パーサー {#45-the-parser}

`BlocklistParser`（`Sources/LavaSecCore/BlocklistParser.swift`）はルールを文字どおりに数えます: コメント／空行／無効な行を落とし、正規化し、リスト内で完全一致の文字列を重複排除し（`Set` を使って）、リストごとに **`maxRules = 1,000,000`**（デフォルト）で打ち切ります。1 行の最大長は 4,096 文字です。対応フォーマット: `auto`、`plainDomains`、`hosts`、`adblock`、`dnsmasq`（`auto` は hosts → dnsmasq → adblock → plain の順に試します）。有効な 1 行 = 1 ルール = メモリの単位、です。

> **複数ホストの `hosts` 行（parser rules version 2）。** 1 つの IP を複数のホストに対応づける `hosts` 行（`0.0.0.0 a.com b.com c.com`）は、いまや最初の 1 つだけでなく、**すべて**のホストをそれぞれ独立したルールとして出力します。`maxRules` は**ルール単位**（行単位ではなく）で強制されるので、上限近くにある複数ホストの行が上限を超過してしまうことはありません。同じ上流のバイト列がより多くのルールを生みうるようになったため、パーサーの rules version は **1 → 2** に上がり、古い「最初のホストだけ」の挙動でパースされた `RuleSetCache` の古いエントリーは無効化されます。

### 4.6 ダウンロードとデコードの堅牢性（実装済み） {#46-download--decode-robustness-implemented}

トンネルとカタログ同期は NE のメモリ予算の中で動くので、リストの取り込みは敵対的・不正な入力に対して堅牢化されています。

- **ストリーミングダウンロード。** `defaultDataFetcher` は `URLSession.download` でリストのバイト列を一時ファイルにダウンロードし（ピークメモリを抑えます）、ボディ全体を RAM にバッファリングする代わりに、ダウンロード後にサイズチェックを行います（`maximumBlocklistBytes`）。サイズ超過のボディは `BlocklistDownloadSizeLimitExceeded` を発生させます。
- **カタログメタデータの上限（8 MB）。** `BlocklistCatalogRepository.maximumCatalogBytes` が、デコードの前にサイズ超過のリモートカタログを拒否するので、敵対的／MITM のホストが拡張機能内で OOM の JSON デコードを強制することはできません。
- **寛容な UTF-8 デコード。** 1 つの不正な UTF-8 バイトがあっても、リスト全体を拒否することはなくなりました（フェイルクローズの下では、これがすべての DNS をブロックしてしまうおそれがありました）。不正なバイトは U+FFFD になり、問題のある行だけが行単位の検証に失敗して捨てられます。
- **名前付きのカスタムブロックリストエラー。** 失敗したカスタムリストは、生の `URLError` ではなく `customBlocklistUnavailable(displayName:reason:)` —「カスタムブロックリスト『<name>』を読み込めませんでした。<why>」— として表面化するようになりました。キャンセルは、ダウンロード失敗ではなくキャンセルとして伝播されます。

---

## 5. ブロックリストカタログとデフォルトのソース {#5-blocklist-catalog--default-sources}

### 5.1 カタログモデル {#51-catalog-model}

**ブロックリストカタログ** は、利用できるソースの公開リストです。**lavasec-api の Worker** が R2 バケットから JSON のメタデータを `GET /v1/catalog`（と `/v1/catalog/:version`）で配信します。端末は実際のリストの **バイト** を、各上流の `source_url` から直接取得します。iOS のカタログのエンドポイントは `https://api.lavasecurity.app/v1/catalog`（`BlocklistCatalogSync.swift:4-15`）です。

端末側では、`BlocklistCatalogSynchronizer`（`BlocklistCatalogSync.swift`）が次を行います:

1. リストのバイトを `source.sourceURL` から直接取得し、サイズ上限を課します。
2. SHA-256 を計算し、そのチェックサムがカタログの `accepted_source_hashes` に含まれている場合だけバイトを受け入れます。
3. 不一致の場合は、直近で正常だったローカルキャッシュにフォールバックするか、**フェイルクローズ** します（`checksumMismatch`） — ただしそのソースが上流の直接ローテーションを明示的に許している場合は別です。
4. ローカルでパース／正規化／重複排除します。
5. パース済みのすべてのルールセットを `DomainRuleSet.lavaSecProtectedDomains`（`AppConfiguration.swift:262-276`）でフィルタリングし、上流のリストが Lava／Apple／ID プロバイダーのドメインを決してブロックできないようにします。

**保護対象ドメインのセット**（有効化の前に除外される）: `apple.com`、`icloud.com`、`mzstatic.com`、`itunes.apple.com`、`apps.apple.com`、`lavasecurity.com`、`lavasecurity.app`、`api.lavasecurity.app`、`lavasec.app`、`lavasec.example`、`accounts.google.com`、`google.com`（すべてサフィックス一致）。Worker はメタデータを計算するときに同等の `PROTECTED_SUFFIXES` フィルターを適用しますが、端末はそれとは関係なく再検証します。

### 5.2 用意されたソース {#52-curated-sources}

`DefaultCatalog.curatedSources` は、正規の [ブロックリストカタログ](../legal/blocklist-catalog.md) から生成されます。現在は 6 つのカテゴリーにまたがる **33** 個のソースです: Security & Threat Intel、Ads & Trackers、Social Media、Adult Content、Gambling、Piracy & Torrent。ソースのファミリーには The Block List Project、Phishing.Database、HaGeZi、OISD、StevenBlack、AdGuard、1Hosts が含まれます。

`guardrailSources` は空です。GPL のソース（HaGeZi、OISD、AdGuard）はカタログには見えますが、**オプトイン／デフォルトは OFF** です。Worker は起動時の同期／公開を `source_url_only` と、承認済みの GPL プレフィックス（`hagezi-`、`oisd-`、`adguard-`）に限定します。

### 5.3 無料ユーザー向けにデフォルトで有効なリスト {#53-default-enabled-lists-for-free-users}

実際の無料デフォルト設定は `OnboardingDefaults.lavaRecommendedDefaults`（`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`）で、**Block List Basic** — 広範でゆるやかなライセンスの統合リスト（広告 ＋ トラッキング ＋ マルウェア ＋ フィッシング／詐欺）— を有効化し、リゾルバープリセットはデバイス DNS（`resolverPresetID = DNSResolverPreset.device.id`）、デバイス DNS フォールバックはオン、です。これは以前の Block List Project Phishing ＋ Scam の組み合わせに取って代わるものです: Basic の統合カバレッジがそれらを包含し、両者は引き続きオプトインで選択できるリストとして残ります。

その無料デフォルトは **`defaultEnabled` から作られる** もので、ハードコードされているわけではありません。`DefaultCatalog.recommendedDefaultSourceIDs`（`BlocklistModels.swift:250-252`）は `curatedSources.filter(\.defaultEnabled)` から導出されます。ソースのコメント（`BlocklistModels.swift:246-249`）は `defaultEnabled` を「新規インストール時のデフォルトの唯一の真実の出どころ」と呼んでおり、バックエンドカタログの `default_enabled` カラムを反映しています。`recommendedDefaultSourceIDs` を通って `OnboardingDefaults` に流れ込む `defaultEnabled` が、生きた仕組みです — あるソースのフラグを切り替えればデフォルトが変わります。

> **デフォルトの真実の出どころ（コードが正）。** 新規インストール時のデフォルトは **Block List Basic** です。端末は `defaultEnabled: true` をもとにこれを出荷しており、iOS の `BlocklistSource.defaultEnabled` フラグが権威ある生きた仕組みです。バックエンドカタログの `default_enabled` カラムは、同じ正規のカタログ仕様から生成されているので、配信される `/v1/catalog` のメタデータはクライアントと一致します。公開サイトの「有効なブロックリスト 3 → 10」という文言はまだ **古いまま** です — 実際のゲートはリスト件数ではなく、500K/2M のフィルタールール上限です。

### 5.4 source-url-only の GPL 配布モデル {#54-source-url-only-gpl-distribution-model}

**source-url-only** は、GPL／知財コンプライアンスの配布モデルです。Lava は上流の URL ＋ 受け入れ可能なハッシュだけを公開し、端末がリストを自分で取得してパースします。Lava は第三者のブロックリストのバイトを **決して** 保存・ミラー・変換・配信しません。これは **放棄された R2 ミラー設計に取って代わった** ものです（元々の「生の R2 ミラー」プランは 2026-05-25 に差し戻されました）。

Worker 側では、`syncOneBlocklist` が各上流ソースを取得して正規化＋ハッシュ化します（`source_hash`、`normalized_hash`、`entry_count` を計算）が、`raw_r2_key = null` / `normalized_r2_key = null` を書き込みます — R2 に届くのはカタログの JSON メタデータだけです。`check-gpl-blocklist-distribution.sh` がこのモデル全体を強制する CI のガードレールです: ミラー／変換のコードなし、Lava の成果物／ダウンロード URL なし、GPL ソースのデフォルト有効なし、Worker による R2 へのリストバイトの書き込みなし、「Lava がホストするミラー」の文言なし、同梱の GPL `.txt`/`.json` なし、そしてマイグレーション ＋ 法的文書で `source_url_only` が必須、です。

> **ライセンスについての注記:** ファーストパーティの Lava コードは **AGPL-3.0** で出荷されます（`LICENSE` ファイルは GNU AGPL v3 で、README のバッジと一致しています）。第三者のブロックリスト（HaGeZi、OISD）は、それぞれの上流ライセンスのもとで **GPL-3.0** のままです — source-url-only モデルは、まさに Lava が GPL ライセンスのバイトを再配布することなくそれらを使えるようにするために存在します。ここでの GPL-3.0 は上流リストの性質であって、Lava アプリの性質ではありません。

---

## 6. ステータスのまとめ {#6-status-summary}

| 領域 | ステータス |
|---|---|
| DNS クエリの優先順位（bootstrap > pause > filter） | 実装済み |
| フィルター判定の優先順位（guardrail > allowlist > blocklist > default-allow） | 実装済み |
| 安全ガードレールの優先順位の枠（配線済み、エントリーはまだなし） | 実装済み |
| DoH / DoH3（観測ベースの h3 ラベル） | 実装済み |
| DoT（エンドポイントあたり 4 接続プール、8 秒のアイドルリフレッシュ、新規 1 回リトライ） | 実装済み |
| DoQ（クエリごとに新しい接続、4 レーンの同時実行） | 実装済み |
| DoQ の接続再利用 | 取り下げ／iOS 26 下限まで先送り |
| リゾルバーの格下げ ＋ エンドポイントごとのフェイルオーバー ＋ デバイス DNS フォールバック | 実装済み |
| フィルタールール上限（無料 500K / Plus 2M） | 実装済み |
| 約 3.26M ルールの端末ガードレール（50 MiB の NE 上限の手前で 32 MB を目標） | 実装済み |
| コンパクトスナップショットのゼロコピー mmap | 実装済み |
| source-url-only カタログ ＋ 上流からの直接取得 ＋ ハッシュ検証 | 実装済み |
| 保護対象ドメインのフィルター | 実装済み |
| 無料デフォルト = Block List Basic | 実装済み（生成カタログと iOS／バックエンドの投影が一致） |
| ファーストパーティの Lava コードのライセンス | AGPL-3.0（`LICENSE`）；第三者リストは上流では GPL-3.0 のまま |

---

## 関連項目 {#see-also}

- [`../product/overview.md`](../product/overview.md) — プロダクトの一言説明、プライバシーの約束、タブ。
- ティアと収益化（社内リファレンス） — Lava Security Plus と、プランの指標としてのフィルタールール上限。
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — source-url-only のコンプライアンス判断。
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — 上流のブロックリスト／リゾルバーのライセンスと帰属表示。
