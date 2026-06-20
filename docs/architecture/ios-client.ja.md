---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# iOS クライアントアーキテクチャ {#ios-client-architecture}

> 想定読者: `lavasec-ios` を触る iOS エンジニア。

Lava Security は、プライバシーを最優先にした iOS アプリです。端末上の NetworkExtension パケットトンネルを通して DNS をローカルでフィルタリングし、危険なドメインや迷惑なドメインをブロックします。しかも、あなたのブラウジングを Lava のサーバー経由で流すことはありません。このドキュメントでは、iOS クライアントがどう組み立てられているかを説明します。各ターゲット、アプリがトンネル拡張とどうやり取りするか、VPN のライフサイクル、Guardian の状態モデル、Live Activity とウィジェット、オンボーディングの流れ、そしてアプリ側の状態の持ち主である `AppViewModel` まで取り上げます。

システム全体の絵姿（アプリ、カタログ Worker、Supabase）については [システム概要](./system-overview.md) を見てください。

---

## 1. ターゲットと役割分担 {#1-targets-responsibilities}

クライアントは、3 つの実行ターゲットに加えて、共有のコアライブラリという構成で出荷されます。3 つのターゲットはすべて同じ **App Group**（`group.com.lavasec`）に参加し、`LavaSecCore` をリンクしています。

| ターゲット | Bundle id | 役割 |
|---|---|---|
| **App**（`LavaSecApp`） | `com.lavasec.app` | SwiftUI アプリ本体。UI を持ち、NetworkExtension のエンタイトルメントを保有し、`NETunnelProviderManager` を通じてトンネルを制御します。VPN ライフサイクルの拠り所は `AppViewModel` です。 |
| **Packet tunnel**（`LavaSecTunnel`） | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider` のサブクラスである `PacketTunnelProvider`（別名 `LavaSecTunnel`）。DNS パケットを解析して問い合わせ先ドメインを取り出し、メモリマップされたコンパイル済みスナップショットと照合し、許可されたクエリだけを上流へ転送します。プロセスごとに約 50 MiB という jetsam のメモリ上限に縛られています。 |
| **Widget**（`LavaSecWidget`） | `com.lavasec.app.widget` | 唯一のメンバーが `LavaProtectionLiveActivityWidget` である `WidgetBundle`。Live Activity / Dynamic Island の表示を担います。 |

共有コードは 2 か所にあります。

- **`LavaSecCore`**（`Sources/LavaSecCore/`）— プラットフォームに依存しないコア部分です。フィルタリングエンジン、リゾルバーのトランスポート、スナップショット／上限計算、保護用のストア、そして `GuardianMascotAnimation` のコアが入っています。`VPNLifecycleController.swift:3-6` にあるとおり、NetworkExtension の型はこのモジュールから意図的に外してあります。ライフサイクルのロジックをフェイクでテストできる状態に保つためです。`NetworkExtension` に裏打ちされた実装は、アプリターゲット側が提供します。
- **`Shared/`** — 複数のターゲットにコンパイルされるコード（例: `AppGroup.swift`、`LavaActivityAttributes.swift`、`LavaProtectionCommandService.swift`、`SoftShieldGuardian.swift`、`LavaLiveActivityIntents.swift`）。

パケットトンネルの内部（DNS の解析、コンパイル済みスナップショット、暗号化されたリゾルバートランスポート、フィルタールールの上限）については、[DNS フィルタリングとブロックリスト](./dns-filtering-and-blocklists.md) で詳しく扱います。このドキュメントは、アプリ側のアーキテクチャと、アプリと拡張の境界に焦点を当てます。

---

## 2. アプリ ↔ 拡張の IPC {#2-app-extension-ipc}

アプリとパケットトンネル拡張は別々のプロセスです。両者は 3 つの仕組みで連携していて、いずれも App Group を土台にしています。

### App Group コンテナ {#app-group-container}

`group.com.lavasec` は共有コンテナで、アプリ、トンネル、ウィジェットが同じ `LavaSecCore` の状態や設定を読み書きできるようにします。`LavaSecAppGroup`（`Shared/AppGroup.swift`）が、共有のキーやファイル名をすべて一元管理しているので、プロセス間で文字列定数がずれることはありません。具体的には次のものです。

- コンパイル済みスナップショットの成果物（`filter-snapshot.compact`、`filter-snapshot.json`）、シリアライズ済みの `app-configuration.json`、トンネルの健全性（`tunnel-health.json`）、診断情報、ネットワークアクティビティのログ。
- 保護セッションと一時停止状態のための共有 `UserDefaults` キー。これらは `LavaSecCore` のストアをそのまま別名参照しています（`AppGroup.swift:38-41`）— `ProtectionSessionStore.Keys`、`ProtectionPauseStore.Keys` — そのため、アプリ、トンネル、Live Activity のインテントが、1 つのキー構成、1 つのリビジョンカウンター、1 つの重複排除の仕組みを共有します。
- カタログキャッシュのディレクトリと、端末上のデバッグログファイル。

コンテナの URL は `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)` で解決します。

### コマンド / プロバイダーメッセージ（制御経路） {#command-provider-message-the-control-path}

アプリはすべてのコマンドを **`sendProviderMessage`** でトンネルに送ります。`AppViewModel.sendTunnelMessage(_:)`（`AppViewModel.swift:7215`）が、キャッシュ済みのマネージャーから有効な `NETunnelProviderSession` を取得し、`session.sendProviderMessage(...)` を呼びます。ペイロードは `LavaSecProviderMessageCodec`（`AppGroup.swift:55-79`）によって小さな JSON のエンベロープにエンコードされ、メッセージの `kind` と、任意の `operationID`（エンドツーエンドのレイテンシ追跡に使います）を運びます。

認識されるメッセージの種類は、`LavaSecAppGroup` 上の定数です。

| メッセージ定数 | トンネルでの効果 |
|---|---|
| `reloadSnapshotMessage`（`"reload-snapshot"`） | コンパイル済みのフィルタースナップショットを強制的に再読み込みします。 |
| `reloadProtectionPauseMessage`（`"reload-protection-pause"`） | 共有の一時停止状態だけを読み直します。 |
| `reloadConfigurationMessage`（`"reload-configuration"`） | 設定を再読み込みします。目に見える再接続が起きるのは、*リゾルバーの識別情報* が変わったときだけです。 |
| `clearDiagnosticsMessage`、`clearFilteringCountsMessage`、`clearNetworkActivityLogMessage`、`flushTunnelHealthMessage` | 診断／ログのメンテナンス。 |

トンネル側では、`PacketTunnelProvider.handleAppMessage(_:completionHandler:)`（`PacketTunnelProvider.swift:729`）がエンベロープをデコードし、`kind` で分岐します。特筆すべき点として、`reload-configuration` は新しい設定を読み込むので、リゾルバー以外のフィールド（診断トグル、有料ステータス）は反映されますが、DNS ランタイムをリセットしてトンネルのネットワーク設定を再適用する（＝目に見える再接続）のは、リゾルバーの識別情報が実際に変わったときだけです（`PacketTunnelProvider.swift:768-792`）。診断フラグや有料ステータスの変更で、稼働中の接続が切れることはありません。

アプリの `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` というヘルパー（`AppViewModel.swift:7062`／`7070`）は、これらのメッセージを送るだけの薄いラッパーです。

### app→tunnel の制御になぜプロバイダーメッセージを使うのか {#why-provider-messages-for-app-tunnel-control}

**`sendProviderMessage` は唯一の app→tunnel 制御経路で、app→tunnel の Darwin シグナルは存在しません。** 以前の設計では、一時停止のときに `CFNotificationCenter` の Darwin シグナルを投げて拡張内で観測していましたが、NetworkExtension プロセスでは安定して発火せず、削除されました。コマンドサービスはもう `CFNotificationCenterPostNotification` を投げず、トンネルももう `CFNotificationCenterAddObserver` を追加しません。どちらも、再導入を防ぐためにソース内省テストで「無い」ことが確認されています（コマンドサービスの post については `Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574`、トンネルの observer については `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847`）。（コマンドサービスとトンネルに残っている `import Darwin` の行は、通知用ではなく `flock`／ソケットのプリミティブ用です。）

一方、*逆方向* には今も Darwin 経路が出荷されています。トンネルはアプリに健全性変化のひと突きを投げます。`TunnelHealthSignal.DarwinProtectionSignalNotifier`（`Sources/LavaSecCore/TunnelHealthSignal.swift`）が `com.lavasec.protection.tunnel-health-changed` というチャンネルで `CFNotificationCenterPostNotification` を投げ（チャンネル名は `AppGroup.swift` ではなく `TunnelHealthSignal.swift` にあります）、アプリは `DarwinNotificationObserver`（`LavaSecApp/DarwinNotificationObserver.swift`、`CFNotificationCenterAddObserver`）でそれを観測します。これは `AppViewModel` に組み込まれていて、`handleTunnelHealthNudge()` を呼びます。この tunnel→app の健全性のひと突きは、`LavaLiveActivitySourceTests.swift:1059-1075` で「有る」ことが確認されています。

app→tunnel の制御では、一時停止は共有の `ProtectionPauseStore` への書き込みで届け、続けて `reload-protection-pause` のプロバイダーメッセージを送ることで、トンネルが `refreshProtectionPauseStateOnly` を実行します。`AppViewModel.swift:4995-4996` がこのルールをそのまま文書化していて、アプリは「スナップショットの Darwin observer にも一切頼らず、常に `sendProviderMessage` を使う」とあります。App Group（共有状態）＋ `sendProviderMessage`（起こす／制御するシグナル）のペアを、app→tunnel の制御経路だと捉えてください。

### Live Activity コマンドサービス {#live-activity-command-service}

`LavaProtectionCommandService.perform(_:)`（`Shared/LavaProtectionCommandService.swift`）は、Dynamic Island / Live Activity の操作（`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`、`resume`、`reconnect`）の入口です。`LavaLiveActivityIntents.swift` の `LiveActivityIntent` 群は（NetworkExtension のエンタイトルメントを持つ）アプリプロセスで動くので、次のようになります。

- **一時停止 / 再開** は、プロセスをまたぐファイルロック（`protection-command.lock`、`flock`）と、`LavaSecCore` の `ProtectionPauseStore` / `ProtectionSessionStore` を通って流れます。これらがリビジョンの発行と、重複コマンドの重複排除を担います（`commandID` が呼び出し元の operation id を引き回すので、再配送されたコマンドが 2 つ目のリビジョンを発行することはありません）。その結果として、リビジョンガード付きの Live Activity 更新がスケジュールされます。
- **再接続** は直接処理されます（`performReconnect`、`LavaProtectionCommandService.swift:112-135`）。`loadAllFromPreferences` を呼び、`startVPNTunnel()` で最初にインストールされたトンネルマネージャーを起動します（`loadAllFromPreferences` はすでにこのアプリの NE 構成にスコープされているので、その最初のマネージャーは Lava のものです。`VPNLifecycleController.matchingManagers()` とは違い、明示的な識別情報の照合はしません）。Connect-On-Demand はすでに有効なので、これは即時の接続を強制するだけです。その後、アプリのステータス調整が、接続できしだい Live Activity を `.on` に戻します。

---

## 3. VPN のライフサイクルと制御 {#3-vpn-lifecycle-control}

`AppViewModel`（`@MainActor final class`、`AppViewModel.swift:723`）は、アプリにおける VPN ライフサイクルの拠り所です。オン／オフの切り替えを取り仕切り、有効な `NETunnelProviderManager` をキャッシュし、ステータスを SwiftUI に公開します。

### マネージャーの選択とライフサイクル計算 {#manager-selection-and-lifecycle-math}

再利用できる NetworkExtension 非依存のライフサイクルロジックは、`VPNLifecycleController<Repository>`（`Sources/LavaSecCore/VPNLifecycleController.swift`）にあります。アプリは `NETunnelProviderManager` に裏打ちされた `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting` の実装を提供し、コントローラーが次を担います。

- **選択と重複排除** — `matchingManagers()` が `LavaTunnelConfigurationIdentity.matches(...)` を使って Lava 所有のマネージャーに絞り込み、`selectionPriority`（まず稼働中、次に正規の表示名）で並べ替え、`removeDuplicateManagers(keeping:)` が 1 つの生き残りに収束させます。
- **接続／停止の待機** — `waitForConnect` / `waitForStop` が、`startGraceInterval` の許容幅を持たせつつ稼働中の接続ステータスをポーリングします。これは、`startVPNTunnel` の直後に、iOS が `.connecting` へ遷移させる前の一瞬、接続が非 pending のステータスを読み取ることがあるためです。

### オン / オフ {#turn-on-turn-off}

`enableProtection(...)`（`AppViewModel.swift:5764`）は **キャッシュ優先** です。現在の構成に対して再利用確認済みの準備済み成果物があるときは、進行中のカタログ同期がバックグラウンドで更新を続けるあいだに、VPN はキャッシュからすぐ立ち上がれます。そして完了時に `performCatalogSync` が稼働中のトンネルを調整します。同期でブロックするのは、起動の土台になる有効なものが何もないとき（例: ユーザーが有効リストの集合を変えたばかりで、キャッシュ済み成果物の識別情報が無効になったとき）だけです。

`disableProtection(...)`（`AppViewModel.swift:5972`）は、iOS がすぐに再接続しないよう、トンネルを止める *前に* Connect-On-Demand をオフにします。`setManagerOnDemand(_:on:)`（`AppViewModel.swift:6253`）は `NEOnDemandRuleConnect`（インターフェース一致は `.any`）をインストールして設定を保存します。iOS に変更を反映させるには、設定するだけでなく保存することが必要です。

### ステータスの観測（と発熱の注意点） {#status-observation-and-a-heat-caveat}

`AppViewModel` は `.NEVPNStatusDidChange` を観測し（`AppViewModel.swift:1034-1056`）、`vpnStatus`／`isVPNConfigurationInstalled` を公開します。重要なのは、マネージャーがすでにキャッシュされているときは、`loadAllFromPreferences` の更新を強制せず、キャッシュ済みマネージャーの稼働中の接続を読むという点です。`loadAllFromPreferences` 自体が `NEVPNStatusDidChange` を再度投げるため、observer 内で更新を強制すると自己増殖的な嵐になりました。ソース内のコメント（`AppViewModel.swift:1046-1048`）には、計測された約 370 イベント/秒と、それが引き起こした 134% の CPU 発熱リグレッションが記録されています。公開プロパティは本物の遷移でのみ変化するので、アイドル時のチクタクが SwiftUI を無効化し続けることはなくなります。

### フェイルクローズドの on-demand 調整 {#fail-closed-on-demand-reconcile}

Connect-On-Demand は、アプリがスナップショットを送る前に、起動時（または iOS がネットワーク変化でトンネルを破棄した後）にトンネルを **コールド** で立ち上げることがあります。再利用可能な永続スナップショットを持たないコールドなトンネルは **フェイルクローズド** で読み込まれ、すべてのトラフィックをブロックし、自力では復帰しません。`AppViewModel` はこれを 2 つの起動経路で扱い、どちらもオンボーディング完了（`hasCompletedOnboarding`、`@AppStorage("hasSeenLavaOnboarding")` フラグを反映）を条件にしています。

- **オンボーディング後** — `reconcileTunnelSnapshotAfterLaunch()`（`AppViewModel.swift:7122`）は、起動時に保護が有効なら毎回走ります。起動用スナップショットを用意し、共有状態を永続化し、`reload-snapshot` を送って、トンネルがフェイルクローズドから本物のルールを読み直すようにします。フェイルクローズドは安全なデフォルトのままで、これは単にそれを速やかに上書きするだけです。（Connect-On-Demand がトンネルを上げ続けている状態でアプリを再起動した後、フィルターが赤く表示される／トラフィックがブロックされる問題を修正します。）
- **オンボーディング中** — `neutralizeInheritedProtectionDuringOnboarding()`（`AppViewModel.swift:7181`）は、オンボーディングが終わっていないときに、いかなるネットワーク処理 *より前に* 走ります。iOS はアプリ削除時に VPN プロファイルを確実には消さないので、再インストールすると、孤立した on-demand 有効の構成を引き継いでしまい、ユーザーがブロックリストを選ぶ前にフェイルクローズドのコールドなトンネルが立ち上がることがあります。この経路は、構成への変更を保存するのではなく、構成を **削除** します（`removeFromPreferences`）。`saveToPreferences` だと、このインストールが所有していないプロファイルに対して「VPN 構成の追加」というシステムのプロンプトを再表示してしまい、オンボーディングのシートが描画される前のアプリ起動時にダイアログが出てしまうからです。クリーンインストールのときや、引き継いだ構成がすでに不活性なときは何もしません。

---

## 4. Guardian / 状態モデル {#4-guardian-state-model}

関連する状態の語彙が 2 つあります。接続性の *評価* と、Guardian の *マスコット* 状態です。

### 接続性の評価 {#connectivity-assessment}

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)`（`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`）は、`TunnelHealthSnapshot` を `ProtectionConnectivityAssessment` にマッピングします。**6 つの深刻度** と **2 つのアクション** のいずれかを持ちます。

- 深刻度: `healthy`、`recovering`、`usingDeviceDNSFallback`、`dnsSlow`、`networkUnavailable`、`needsReconnect`。
- 主アクション: `turnOff` または `reconnect`。

この単一の評価が、アプリ内のガード画面と、（さらにマッピングされて）Dynamic Island の状態の両方を動かすので、2 つが食い違うことはありません。

**正直さの下限（v1.0）。** 現在の、カバーされていない DNS スモークプローブの失敗が、`.healthy` と読まれることは決してありません — 評価は、プローブが実際に成功するまで `.recovering` を表示するので、行き詰まったプライマリの上をフォールバックで運ばれているトラフィックが「保護されている」と描かれることはもうありません。再接続のロジックは、汎用の上流カウンターではなく `consecutiveDNSSmokeProbeFailureCount` と `lastPrimaryUpstreamSuccessAt`（プライマリのみ）をキーにします。また、到達可能なままなのに既知の良好なプローブを**拒否し続ける**リゾルバー（ハイジャック／キャプティブ／古い状態）は、リゾルバーのアイデンティティにスコープされた `consecutiveRejectedSmokeResponseCount`（LAV-87）を通じて、再起動に値するものへとエスカレーションされます — チャーンの多いローミングネットワークで汎用の連続カウントがリセットされ続ける場合でもです。

### 接続性の通知 {#connectivity-notifications}

`ProtectionConnectivityNotificationPolicy`（`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`）は、評価を、未処理のローカル通知が最大でも 1 つになるように変換し、スロットリング（600 秒）して重複排除します。v1.0 では次が加わりました。

- 独立した **`dnsSlow`** の種類（「Lava DNS is slow」） — 以前は遅い DNS が `reconnectNeeded` の種類を使い回していたため、本物の障害がそれを上書きできませんでした。
- **エスカレーション／上書き** — 厳密により緊急な問題（`reconnectNeeded` だけが他のすべてを上回ります）は、すでに立っている、より低いランクのバナーを上書きでき、「問題はすでに未処理」というガードとスロットルの両方を回避します。これにより、Device-DNS フォールバックのあとの行き詰まりが、安心させるバナーを立てたままにするのではなく、操作可能な「Reconnect」のプロンプトを表面化させます。
- **永続化のマイグレーション**（`ProtectionConnectivityNotificationStore`、スキーマ v2、`LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded` 経由で配線）が、レガシーの未処理の `reconnect-needed` マーカーを `dnsSlow` に格下げするので、アップグレードをまたいでもエスカレーションが機能します。

### Device-DNS のキャプチャリトライ {#device-dns-capture-retry}

有効な設定がデバイスリゾルバーに依存している場合（プライマリとして、あるいはフォールバックとして）、ネットワークのハンドオフ／ウェイクによって、トンネルが空のシステムリゾルバーキャプチャを抱えたままになることがあります — 静かな行き詰まりです。`DeviceDNSFallbackPolicy` は **上限つきのリトライ**（`shouldRetryDeviceDNSCapture`、`deviceDNSCaptureRetryInterval` 1 秒、`deviceDNSCaptureMaxRetryAttempts` 5）を駆動します。トンネルは、キャプチャが空でなくなるまで最大 5 回、1 秒ごとにシステムリゾルバーを読み直し、そのまま採用します — トンネルを再起動せずに自動回復します（イベント `device-dns-capture-retry` ／ `-exhausted`）。純粋な DoH/DoT/DoQ の設定では何もしません（`currentConfigurationDependsOnDeviceDNS()`）。

### Guardian マスコットの状態 {#guardian-mascot-states}

Soft Shield Guardian のマスコットには、ちょうど **7 つ** の感情状態があります — `GuardianMascotState`（`GuardianMascotAnimation.swift:3`）: `sleeping`、`waking`、`awake`、`paused`、`retrying`、`concerned`、`grateful`。各状態は自分の `allowedNextStates` を宣言するので、遷移は制約されます（例: `grateful` は `awake` にしか戻れません。`GuardianMascotAnimation.swift:12-29`）。意味は次のとおりです。

- `retrying` = 落ち着いた自己回復。
- `concerned` = やわらかい助けを求める状態。
- `grateful` = お祝いの成功（オンボーディング／設定の画面で使い、接続性のマップでは使いません）。

`GuardianMascotAnimation` は `LavaSecCore` 内の手続き的なアニメーションのコアです。`SoftShieldGuardian`（`Shared/SoftShieldGuardian.swift`）は SwiftUI 側の描画で、`GuardianShieldStyle` で選ばれるカスタマイズスキン（表示名は Original、Fire Opal、Amethyst、Obsidian、Cherry Quartz、Emerald、Kiwi Crème — `LavaActivityAttributes.swift:5-56`、`displayName` のマッピングは 18-35 行目）に対応します。いくつかの raw 値は表示名と食い違うので（例: `fireOpal = "emberObsidian"`、`cherryQuartz = "strawberryObsidian"`、そして `purpleObsidian` は "Amethyst" として描画されます）、ラベルではなく raw 値を永続化してください。

### 2 つはどうつながるか {#how-the-two-connect}

Live Activity の `LavaActivityAttributes.ProtectionState`（`Shared/LavaActivityAttributes.swift`）が、`guardianState` を介して評価をマスコット状態に橋渡しします。`on → awake`、`paused → paused`、`reconnecting`／`networkUnavailable → retrying`、`needsReconnect → concerned`（`LavaActivityAttributes.swift:95-105`）。`AppViewModel` は、Dynamic Island 用の保護状態を、同じ `protectionConnectivityAssessment` から選びます（`AppViewModel.swift:3131-3147`）。`networkUnavailable` の深刻度は `.networkUnavailable` になり、`recovering` は `.reconnecting` に、`reconnect` の主アクションは `.needsReconnect` に、それ以外は `.on` になります。

> 注: `LavaTier`（穏やか → **Floor** / お祝い → **Window** / 技術的 → **Workshop** というデザインシステムの深さを表す enum）は、デザインシステム層（`LavaSecApp/LavaDesignSystem/LavaTokens.swift`）に出荷され、代表的な画面に組み込まれています — [デザインシステム](../design-system/overview.md) を参照してください。これはデザインシステムの深さを司るもので、ここで説明している保護／トンネルのクライアント経路ではありません。

---

## 5. Live Activity とウィジェット {#5-live-activity-widget}

ウィジェットターゲットは Live Activity と Dynamic Island だけを描画します。`LavaSecWidgetBundle`（`LavaSecWidget/LavaSecWidget.swift`）は、単一の `LavaProtectionLiveActivityWidget` を公開します。これは `ActivityConfiguration(for: LavaActivityAttributes.self)` で、次を持ちます。

- ロック画面ビュー、展開された Dynamic Island の中央領域、そして `SoftShieldGuardian` とステータスのグリフを描画する compact／minimal の表示。compact／ロックのビューは、1 秒ごとの `TimelineView` で *実効* の保護状態を再計算するので、プッシュなしでも一時停止のカウントダウンがライブのまま保たれます。

`LavaActivityAttributes.ContentState` は、`protectionState`、`resumeDate`（一時停止のカウントダウン用）、`pauseRequiresAuthentication`、そして選ばれた `shieldStyle` を運びます。デコードは寛容で、`shieldStyle` が無ければ `.original` にフォールバックするので、古い Live Activity のペイロードも動き続けます。

アプリ側では、`LavaLiveActivityController`（`LavaSecApp/LavaLiveActivityController.swift`）が稼働中の `Activity<LavaActivityAttributes>` を持ちます。ActivityKit の認可変化を観測し、Live Activity を phone／pad のイディオムでのみ提供し、`reconcile(...)` がリクエストされた保護状態に合うようにアクティビティを開始／更新／終了します。`AppViewModel.reconcileLiveActivity()`（`AppViewModel.swift:3069`）は、望ましい状態を再計算してコントローラーを呼ぶ唯一の合流点です。Dynamic Island のボタンは `LiveActivityIntent` をディスパッチし、それが [§2](#2-app-extension-ipc) で説明したとおり `LavaProtectionCommandService` を呼びます。

---

## 6. オンボーディングの流れ {#6-onboarding-flow}

オンボーディングは `LavaOnboardingView`（`LavaSecApp/OnboardingFlowView.swift`）が提示し、`RootView`（`RootView.swift:32`）で宣言された `@AppStorage("hasSeenLavaOnboarding")` フラグでゲートされます。流れは `OnboardingPage` の並び（`OnboardingFlowView.swift:403-409`）です: `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`。

出荷される初期構成は `OnboardingDefaults`（`Sources/LavaSecCore/OnboardingDefaults.swift`）から来ます。`AppConfiguration.lavaRecommendedDefaults` は、控えめなおすすめソース（Block List Project の Phishing + Scam）だけを有効にし、リゾルバーとして **デバイス DNS** を選び — `DNSResolverPreset.device`（id `device-dns`）、ネットワーク自身の DNS。Google DoH のような暗号化プリセットはオプトインで、デフォルトには昇格しません — デバイス DNS フォールバックを有効にし、ローカルログをオンのままにします — そして `protectionEnabled: false` なので、保護はユーザーが選んだときだけオンになります。`OnboardingDefaultsSummary` がそれらの選択を表示用に整えます（「アカウントなしで続ける」がアカウントのデフォルトです）。

最後に `hasSeenLavaOnboarding = true` を設定することが、`hasCompletedOnboarding` を反転させ、それが [§3](#3-vpn-lifecycle-control) で説明した起動時の調整経路を起動可能にします。それまでは、オンボーディング中の中和経路が、引き継いだフェイルクローズドのトンネルがトラフィックをブロックしないよう抑えます。

---

## 7. アプリの状態: `AppViewModel` {#7-app-state-appviewmodel}

`AppViewModel`（`@MainActor final class AppViewModel: ObservableObject`、`AppViewModel.swift:723`）は、アプリ側の状態の中心的な持ち主です。VPN のライフサイクルに加えて、UI がバインドする画面を公開します。たとえば次のとおりです。

- **保護とトンネル** — `vpnStatus`、`isVPNConfigurationInstalled`、`isConfiguringVPN`、`tunnelHealth`（`TunnelHealthSnapshot`）、`temporaryProtectionPauseUntil`、そしてユーザー向けの `vpnMessage`／`vpnMessageIsError`。
- **設定とカタログ** — `AppConfiguration`、`isSyncingCatalog`、`catalogVersion`／`catalogGeneratedAt`、そしてコンパイル済みのルール数（`compiledRuleCount`、`protectedRuleCount`、`compiledBlocklistRuleCount`）。
- **診断** — `DiagnosticsStore` と `NetworkActivityLog`（すべてローカル。下のプライバシーの約束を参照）。
- **アカウントとバックアップ** — `accountAuthState`、`encryptedBackupState`、`isAutomaticBackupEnabled`、そして **Lava Security Plus** のオファー／エンタイトルメントの状態。
- **カスタマイズと表示** — `appearancePreference`、`lavaGuardLook`（`GuardianShieldStyle`）、`lavaGuardProgress`、`usesLiveActivities`。

ライフサイクルの直列化は `protectionActionOrchestrator` に委ね（バックグラウンドの復元がユーザーのオン操作と入り混じらないように）、キャッシュ済みの `tunnelManager` を保持し、スナップショット／設定／一時停止の変更をすべて [§2](#2-app-extension-ipc) のプロバイダーメッセージのヘルパー経由で拡張に届けます。

> **プライバシーの考え方。** DNS のフィルタリングはこの端末上でローカルに行われます。`AppViewModel` が公開する診断やネットワークアクティビティの画面は、ローカルにのみ保存されます — Lava があなたの日常の DNS クエリ、ブラウジング履歴、ドメイン単位のテレメトリを受け取ることは決してありません。任意のアカウントバックアップは **ゼロ知識** です（端末上で暗号化され、Lava が保存できるのは暗号文だけです）。パスキーによる復元も同様で、その鍵は端末上で PRF 由来に作られ、サーバーが保持する秘密はありません。サーバーとの境界については [システム概要](./system-overview.md) を参照してください。

---

## 関連ドキュメント {#related-docs}

- [システム概要](./system-overview.md) — システム全体を一画面で: アプリ、カタログ Worker、Supabase、それに信頼境界と、全体で使うステータス凡例。
- [DNS フィルタリングとブロックリスト](./dns-filtering-and-blocklists.md) — ここでは制御の境界でしか触れていないパケットトンネルの内部: コンパイル済みのフィルタリングエンジン、暗号化されたリゾルバートランスポート（DoH / DoH3 / DoT / DoQ）、フィルタールールの上限、ブロックリストのカタログ、そしてソース URL のみ再配布モデル。
- [アカウントとゼロ知識バックアップ](./accounts-and-backup.md) — サインインプロバイダーと、`AppViewModel` が取り仕切るゼロ知識バックアップのエンベロープ（ゼロ知識で PRF 由来のパスキー復元スロットを含む）。
- [バックエンドとデータ](./backend-and-data.md) — `lavasec-api` のカタログ Worker、Cloudflare R2、そしてアプリ↔サーバー境界の反対側にある Supabase のスキーマ／RLS。
- [デザインシステム](../design-system/overview.md) — `LavaTier` の深さモデル、Soft Shield Guardian の 7 つの状態とシールドのスキン、そしてクライアントが描画するコピー／ローカライズの取り決め。
- [サードパーティ通知](../legal/third-party-notices.md) と [GPL のソース URL のみ準拠の判断](../legal/gpl-source-url-only-compliance-decision.md) — クライアントが利用するカタログ／フィルターのパイプラインの背後にある配布上の制約。
