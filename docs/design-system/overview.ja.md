---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# デザインシステム

> **対象読者:** Lava Security iOS アプリに携わるデザイナーとエンジニア。
> **権威:** このドキュメントとプランが食い違う場合は、**コードが正しい** — 食い違いはその場で注記してあります。ステータスはコードで確認できる実態を反映しており、プラン上の理想ではありません。ステータスの凡例: **実装済み**（出荷済みでコードでも確認済み）、**進行中**（一部だけ着地している）、**予定**（設計済み、未着手）、**取り下げ**（却下または差し戻し）。

このドキュメントでは、デザイン哲学、LavaTier の深さの語彙、Guardian マスコット、コピーと命名のルール、オンボーディング UX、そして国際化を扱います。これらの画面を支えるアーキテクチャ部分（ターゲット、VPN のライフサイクル、Guardian / 保護状態モデルの配線）については [iOS クライアント](../architecture/ios-client.md) を、製品としての位置づけについては [製品概要](../product/overview.md) を参照してください。

---

## 1. 哲学: 穏やかな中心、見つけて手に入れる奥行き {#1-philosophy-calm-core-earned-depth}

Lava が想定するのは技術に詳しくない普段使いのユーザー — 親世代や年配の方 — で、デザインもそこから出発しています。普段目にする画面は誰にとっても穏やかに「ただ動く」だけ。追加の情報や楽しさ、細かな操作は、ユーザーが自分で探しに行ったときにだけ姿を現します（**手に入れる**）。何もせかさず、何も警告で驚かさず、技術的な仕組みは求められるまで見えないままです。

この **「穏やかな中心、見つけて手に入れる奥行き」** モデルは、3 つの製品の深さに落とし込まれます。

- **Calm** — 誰もが最初に目にする、ただ動くだけの初期状態の保護。
- **Celebratory** — オプトインの気づきと楽しさ（連続記録、ロック解除、うまくいった瞬間）。決してせかしません。
- **Technical** — DNS、診断、統計。ユーザーが探しに行くまで見えません。

穏やかな姿勢を支える、全体に効く 2 つのパレット / トーンのルールがあります。

- **赤 = 危険だけ。** 赤は危険とエラー専用に取ってあります。穏やかなパレットは緑とオレンジです。こうすることで、赤は本物の警告サインとして信頼できる色のままでいられます。危険を表す赤は `LavaStyle.dangerRed` としてトークン化され、`LavaStyle.errorText` がそのエイリアスになっており（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86）、ビューのエラーテキストで使われます。保護のティント色は、生の `.green` / `.orange` ではなく、セマンティックな `ProtectionTintRole` のロールテーブル（lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7）を通して解決されます。生の `.red` を使っている箇所が実際にいくつか残っており（例: lavasec-ios: LavaSecApp/SettingsView.swift:697、LavaSecApp/SecurityController.swift:600、LavaSecApp/FiltersView.swift）、これらを `LavaStyle.dangerRed` に移すのが残りの片付けです。

> **コンポーネントの入れ替え（v1.0）。** `LavaTabOverviewCard` は削除されました。フィルターとアクティビティの見出しブロックは、いまや `LavaInfoCard` ＋ `LavaOverviewMetricBlock` を共有するので、サイズと位置がそろいます。フィルター／アクティビティの再設計とあわせて、新しい共有コンポーネントが入りました: `FiltersFlowDiagram`（「Phone → Lava → Internet」の図）、`ActivityFlowBar` ／ `ActivityFlowStatRow`（リクエストフローの要約）、`NetworkActivityPrivacyInfoPanel`、そして `LavaGuardLookPickerSheet`（ボトムシートのガードピッカー）です。インポート／共有のフローは、独自のコンテンツ内ヘッダーをネイティブの `importFlowToolbar` に置き換えました。
- **恐怖をあおるセキュリティ表現は使わない。** コピーはわかりやすく、穏やかで、実用的に。[§4 コピーと命名](#4-copy-naming) を参照。

### 今日存在するトークン化レイヤー **（実装済み）** {#the-tokenized-layer-that-exists-today}

デザインシステムは、本物のトークン化された SwiftUI レイヤーで、`LavaTier` の深さの語彙（§2）と並んで存在します。

- **`LavaStyle`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5） — 適応的なカラーの唯一の出どころ: 約 18 のセマンティックカラー（`safeGreen`、`safeControlGreen`、`softGreen`、`lavaOrange`、`cream`、`ink`、`cardBackground`、`panelBackground`、`guardianSleepGray`、…）。それぞれ単一の `adaptiveColor(light:dark:)` ファクトリで生成されるので、ライトとダークが一緒に定義されます。危険を表す赤も `dangerRed` / `errorText` としてここでトークン化されています（81/86 行目）。
- **`LavaSurface`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101） — カード / パネル / 選択サーフェスのロールと角丸: `cardCornerRadius` 20、`compactCornerRadius` 16、`selectionCornerRadius` 12。
- **`LavaSpacing`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183） — スペーシングのスケール: `xs` / `sm` / `md` / `lg` / `xl` に加えて `screenHorizontal` / `screenTop` / `screenBottom`。
- **`LavaActionRole`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift、v1.0） — システムの `ButtonRole` に対応づけられた、セマンティックなアクションロールの enum（`.cancel`、`.close`、`.confirm`、`.destructive`）。`NativeToolbarIconButton` は `role:` パラメーターを得て、ほぼあらゆるシート／ツールバーで広く使われるようになったので、ツールバーのグリフがネイティブのロールスタイルを受け取ります。

残っている積み残しは、まだ `LavaStyle.dangerRed` に移していない生の `.red` の数箇所だけです（§1 参照）。

---

## 2. LavaTier — Floor / Window / Workshop **（実装済み）** {#2-lavatier-floor-window-workshop}

`LavaTier` は、「穏やかな中心、見つけて手に入れる奥行き」をトークンレイヤーに直接コード化した、軽量な深さの語彙です。語彙といくつかのトークンのデフォルト値であって、テーマの全面再構築ではありません。lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227 に enum として出荷されており、すべてのビューに後付けするのではなく、代表的な画面に配線されています。

| ティア | 深さ | 意味 |
|---|---|---|
| **Floor** | calm | 誰にでも届く、ただ動くだけの保護 — 初期状態の画面。 |
| **Window** | celebratory | オプトインの気づきと楽しさ: 連続記録、ロック解除、うまくいった瞬間。決してせかしません。 |
| **Workshop** | technical | DNS、Nerd Stats、診断。探しに行くまで見えません。 |

`LavaTier` は `calm` / `celebratory` / `technical` の enum で、トークンのデフォルト値を持ちます。

- **アクセントカラー**（`accent`）、
- `allowsDelightMotion` — celebratory / Window のときだけ true、
- `usesMonospacedMetadata` — technical / Workshop のときだけ true、

これらは `EnvironmentKey` と `.lavaTier(_:)` モディファイア、`.lavaTierMetadata()` モディファイア（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263）を通して公開されます。すべてのビューではなく代表的な画面に配線されており — 例えば lavasec-ios: LavaSecApp/SettingsView.swift の `.lavaTier(.technical)` と `.lavaTier(.celebratory)` — このように意図的に範囲を絞ることで、3 つの製品の深さがコード上で読み取りやすくなり、将来の Android 版でも意図を再構築せずに持ち運べます。

> **注意（アクセントのトークン化は予定、Phase 3）:** `LavaColorRole` がまだ作られていないため、`LavaTier.accent` は今も生の `LavaStyle` カラーに解決されます（LavaTokens.swift:~230）。アクセントカラーのトークン化は、完成した画面ではなく開いたままのループとして扱ってください。

---

## 3. Soft Shield Guardian マスコット **（実装済み）** {#3-the-soft-shield-guardian-mascot}

**Soft Shield Guardian** は Lava のマスコット — 丸みのある盾にシンプルで表情の変わる顔がついたもの — で、ガードタブ、ライブアクティビティ、Dynamic Island、オンボーディングで保護状態を視覚的に表します。穏やかなトーンを一番よく伝える存在です。

状態グラフはプラットフォームに依存せず `LavaSecCore`（lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift）に置かれています。SwiftUI のレンダラーは lavasec-ios: Shared/SoftShieldGuardian.swift です。

### 3.1 7 つの表情の状態 {#31-the-7-expression-states}

マスコットには**ちょうど 7 つ**の表情の状態があり、許可された遷移だけを定めた状態グラフ（`GuardianMascotState.allowedNextStates`、lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift でロック）で管理されています。

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

知っておくと役立つグラフの制約: `sleeping` から出られる先は `waking` だけ、`grateful` は `awake` にしか戻りません。`awake ↔ grateful` の遷移には専用の補間フレームがあり — これがこのシステム唯一の **delight motion**（Window ティア）です。

> **`retrying` と `concerned` — もっとも大事なトーンの違い。** どちらも「完全に健全ではない」を示しますが、読まれ方はかなり違うので混同してはいけません。
> - **`retrying`** は *心配せず自己回復している* 顔です: ゆるんだ（約 0.80）まぶた、水平な目、まっすぐな口、そして**心配の傾きなし**。動きは**顔ではなくステータスバッジ**が担います — 一時的な自己回復で驚かせてはいけません。（lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249）
> - **`concerned`** は *やさしく助けを求める* 心配です: 内側の眉が上がり（`concernAmount` 1、`mouthCurve` -0.22）、「ちょっと手を貸してほしいな」と読めます。**決して厳しいにらみではありません**。本当の問題は、叱るのではなく助けを呼び込むべきだからです。（lavasec-ios: Shared/SoftShieldGuardian.swift:297）

### 3.2 接続状態 → 表情のマッピング（6 → 4） {#32-connectivity-expression-mapping-6-4}

保護の健全さは `LavaSecCore` で **6 つの接続状態の重大度** + 2 つのアクションとして評価されます（lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift）。

- **重大度:** `healthy`、`recovering`、`usingDeviceDNSFallback`、`dnsSlow`、`networkUnavailable`、`needsReconnect`
- **アクション:** `turnOff`、`reconnect`

ガードタブはこの 6 つの重大度を **4 つの顔**に集約します（lavasec-ios: LavaSecApp/GuardView.swift:122 の `guardianState`）。顔はステータスバッジよりも意図的に *粗く、穏やかな* シグナルになっています — 詳細はバッジが担い、顔はシンプルなままです。

| 状態 | マスコットの状態 |
|---|---|
| 一時停止中 | `paused` |
| 接続中 + `healthy` / `usingDeviceDNSFallback` | `awake` |
| 接続中 + `recovering` / `networkUnavailable` | `retrying` |
| 接続中 + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| それ以外 | `sleeping` |

> **ティントの整合。** 保護のティント色の細かさは、この表情の分け方と整合が取れているので、ティントと顔が食い違うことはありません。表情のマッピングとセマンティックな `ProtectionTintRole` のロールテーブルはどちらも今日出荷されています（lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7、`AppViewModel.protectionTintRole` で使用）。ロールを完全にトークン化された色に対応づける `LavaColorRole` のカラーロールのトークン化だけが **予定** のままです（DS プランの Phase 3）。

### 3.3 スキン（見た目） **（実装済み）** {#33-skins-looks}

マスコットは **7 種類の選べる盾の「見た目」** で出荷され、`GuardianShieldStyle` として保存されます（lavasec-ios: Shared/LavaActivityAttributes.swift:5）。それぞれ独自の配色と、対になる Dynamic Island のグリフ色を持ちます。

`original`、`fireOpal`（生の値 `emberObsidian`）、`purpleObsidian`、`obsidian`、`cherryQuartz`（生の値 `strawberryObsidian`）、`emerald`、`kiwiCreme`。

2 つのレガシーな生の値は意図的なものです — 「直そう」としないでください。直すと保存済みのユーザー選択が壊れてしまいます。

### 3.4 プライバシーの伏せ字 **（実装済み）** {#34-privacy-redaction}

Guardian はプライバシーの伏せ字を尊重します。画面がプライバシー伏せ字状態のときは表情をマスクできますが、**盾そのものは見えたまま**です（`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`、lavasec-ios: Shared/SoftShieldGuardian.swift:11）。保護があること自体は安心材料なので、隠すのはその時々の感情の部分だけです。

### 3.5 このツリーには入っていないもの **（予定）** {#35-not-in-this-tree}

ガードのイースターエッグのミニゲーム（タップ = 感謝アニメーション、10 秒長押し = 悪いドメインを捕まえるゲーム）は **P3 / バックログ** です。これはマスコットの表情を増やすもので（`confused` / `dazed` / `inZone` / `powerSurge`）、フィーチャーブランチで見られますが — アプリのターゲットには**入っていません**。正典の事実どおり、マスコットの状態はちょうど **7 つ** です。ゲームの表情を出荷済みとして書かないでください。

---

## 4. コピーと命名 {#4-copy-naming}

### 4.1 ボイスとトーン {#41-voice-tone}

わかりやすく、穏やかで、実用的に。恐怖をあおるセキュリティ表現は避けます。範囲については正直に: Lava は **ローカルの DNS / ブロックリストによるフィルタリング**であって、すべての悪意あるドメインや URL がブロックされる保証ではありません。そして保護がオンボーディング完了の瞬間に自動でオンになると説明することは**決してありません** — 保護が今オンかどうかは**ガードタブが正である**ことが基準です。

### 4.2 DNS トランスポートのラベル {#42-dns-transport-labels}

トランスポートの注記は、厳格でコンパクトな決まりに従います（lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 と lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270、`DNSResolverPresetTests.swift` でロック）。

| トランスポート | ラベル | 備考 |
|---|---|---|
| DNS-over-HTTPS | `DoH` | URLSession ベース。 |
| DNS-over-HTTP/3 | **`DoH3`（スラッシュなし）** | 例: 「Quad9 (DoH3)」。**h3 のネゴシエーションが実際に観測されたときだけ**注記されます — 優先はするが約束はしない。それ以外は `DoH` にフォールバック。 |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| プレーン DNS | `IP` | |
| デバイスのリゾルバー | *(注記なし)* | |

ここで一番よく破られるルールは、**スラッシュなしの `DoH3`** です — `DoH3` と書き、決して `DoH/3` や `DoH3 (h3)` とは書かず、推測で付けないこと。これらのトランスポートラベルは `DoHTransport` / `DNSResolverPreset` から出力されます。どのロケールでもそのまま書いてください。ただし、これらは用語集の Do-Not-Translate 項目ではない点に注意してください（§4.3 参照）。

### 4.3 翻訳しない用語 {#43-do-not-translate-terms}

ブランドとプロトコルの用語は **すべての** ロケールでそのまま固定されます。ローカライズ用語集の Do-Not-Translate リストが基準で、次が固定されています: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD。**

DNS トランスポートのうち、用語集の Do-Not-Translate 項目は **DoH** だけです。`DoH3`、`DoT`、`DoQ` はトランスポートラベル（§4.2 参照）であって、用語集の用語ではありません。これらもそのまま書きますが、出どころとして用語集を引用しないでください。

### 4.4 安全性の枠組み {#44-safety-framing}

支払いをしても、ハッシュ検証済みで許可不可の **安全ガードレール** を回避することはできません。優先順位を一貫して示すこと: **安全ガードレール > ローカルの許可リスト（許可する例外） > ブロックリスト > デフォルト許可。**

---

## 5. オンボーディング UX **（実装済み）** {#5-onboarding-ux}

初回起動のオンボーディングは複数ページの流れ — **6 ページ**（`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`） — で、lavasec-ios: LavaSecApp/OnboardingFlowView.swift に実装されています。guardian が現れる瞬間には `SoftShieldGuardian` を再利用します。

6 つのページ:

1. **ネットは溶岩**（`lava`） — 危険をメタファーとして提示。主アクションは「Lava に会う」。
2. **ここは Lava が見張っています**（`guardIntro`） — guardian が現れる瞬間。
3. **機能の引き継ぎ**（`features`） — Lava が何をするか。「保護をセットアップ」。
4. **Lava のローカル VPN をインストール**（`vpn`） — DNS だけのパケットトンネルなのに iOS が「VPN」と表示する理由を説明。
5. **通知を有効にする**（`notifications`） — オプトインのプロンプトを、最初ではなくちょうどよいステップで提示。
6. **セットアップは完了です**（`done`） — 「ガードを開く」、必要なら追加のセットアップも。

この流れに織り込まれた設計判断:

- **「デフォルトを使う」が主アクション、「カスタマイズ」が副アクション。** 技術に詳しくないユーザーのために、摩擦のないデフォルトの道筋を用意。操作は強制ではなく、手に入れるもの。
- **危険は恐怖ではなくメタファーとして提示**（「ネットは溶岩」）。穏やかなトーンと一貫しています。
- **iOS が「VPN」と表示する理由を流れの中で説明** — DNS をシステム全体でフィルタリングするにはパケットトンネルしか手段がなく、通信の経路変更ではありません。
- **完了時に保護が自動でオンになるとは決して主張しない** — ガードが基準のままです。
- 戻るはシェブロンのみ、共通のステップページレイアウト上。

この流れがインストールする初回のデフォルト: **デバイス DNS** リゾルバー（`DNSResolverPreset.device`）、**デバイス DNS フォールバック オン**、ログ オン（カウント + 履歴 + アクティビティ）、そして「アカウントなしで続ける」。

> **デフォルトブロックリストの食い違い（コードが正しい）。** オンボーディングプランのコピーはデフォルトのブロックリストとして HaGeZi Multi Light を挙げていますが、出荷されているコードのデフォルトは **Block List Project Phishing + Scam** です（`AppConfiguration.lavaRecommendedDefaults`、lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift で定義）。本当のプランの境目は**フィルタールールの上限（無料 500K / Plus 2M）**であって、リストの数ではありません。内部で追跡中です。プランのモデルと推奨デフォルトの設定については [機能カタログ](../product/features.md) を参照してください。

---

## 6. 国際化 **（進行中）** {#6-internationalization}

Lava は **6 ロケール** にローカライズされます: **en**（ソース） + **ja、zh-Hant、zh-Hans、de、fr**、Xcode の文字列カタログ経由で。

- **ローカライズの継ぎ目は `.lavaLocalized`** です（`String.lavaLocalized` / `.lavaLocalizedFormat`、`LavaStrings.localized` → 英語フォールバック付きの `NSLocalizedString` が裏にある。lavasec-ios: LavaSecApp/LavaStrings.swift）。**すべてのコンポーネントのコピー**はこれを通すこと — ビューに裸の文字列リテラルを置かない。
- **zh-Hant** は最初のパスで台湾向けの言い回しを使います。
- App Store のメタデータは 6 ロケールすべて分あります。
- 翻訳の優先順位: ja、zh-Hant、zh-Hans、de、fr。
- v1.0 のリリースでは、5 ロケールにわたる文字列カタログのレビュー（約 56 件の修正）が取り込まれ、製品の名詞が複数形の **「Filters」** から単数形の **「Filter」** へと、すべてのロケールで変わりました — 翻訳は単数形の「マイフィルター」のモデルと一貫させてください。

土台は整っていますが、リリース前の本格的な人手による翻訳レビューがまだ残っているので、全体のステータスは **進行中** です。

> **表示境界の片付け（予定、Phase 4）。** `LavaSecCore` / `Shared` は英語の文字列ではなく *セマンティクス*（重大度 / アクションの enum、アイコンのロール）を持つべきです。重大度のティント表示はすでにセマンティックな `ProtectionTintRole` に引き上げ済みです。残っているのは、リゾルバーの `displayName` がまだ英語のハードコード文字列（「Google」「Cloudflare」「Quad9」「Device DNS」）のままだという点です（lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift）。Phase 4 でこれらを OS ごとのアプリ側の表示マップに引き上げます — i18n にも Android への持ち運びにも正しいやり方です。

i18n の仕組み（ローカライズ用語集、ローカライズファイルのスキーマ、翻訳レビューのチェックリスト）は、この公開セットではなく内部の i18n ドキュメントにあります。

---

## 7. 参照アーティファクト {#7-reference-artifacts}

HTML のデザイン参照（出荷しない、内部用）: オンボーディングフローのストーリーボード、kiwi-creme の guardian の見た目スタディ、パネル内の主ボタンのビジュアル案。

DS の土台は着地済みです: `LavaDesignSystem/` グループ、`LavaSpacing` / 角丸 / `dangerRed` トークン、`LavaTier` の深さのセマンティクス、`LavaIcon` のロールレイヤーがすべて出荷されています（lavasec-ios: LavaSecApp/LavaDesignSystem/）。ポータビリティ / 土台のプランで **予定** のまま残っているのは、`LavaColorRole` のアクセントのトークン化（Phase 3）、コア側の英語文字列のための OS ごとの表示マップ（Phase 4）、中立的なクロスプラットフォームのトークン JSON、そしてより広い Android ポータビリティの継ぎ目です。
