---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# iOS 用戶端架構

> 適用對象：在 `lavasec-ios` 中工作的 iOS 工程師。

Lava Security 是一款隱私優先的 iOS 應用程式，透過裝置上的 NetworkExtension 封包通道在本機篩選 DNS，封鎖已知的高風險與不受歡迎的網域，而不會將你的瀏覽流量導向 Lava 的伺服器。本文件說明 iOS 用戶端的結構：各個 target、應用程式如何與其通道擴充功能通訊、VPN 生命週期、Guardian 狀態模型、Live Activity 與小工具、引導流程，以及應用程式端的狀態擁有者（`AppViewModel`）。

如需整體系統的全貌（應用程式、catalog Worker 與 Supabase），請參閱 [系統總覽](./system-overview.md)。

---

## 1. Target 與職責 {#1-targets-responsibilities}

用戶端以三個可執行的 target 加上一個共用核心程式庫的形式發行。這三個 target 都加入同一個 **App Group**（`group.com.lavasec`）並連結 `LavaSecCore`。

| Target | Bundle id | 職責 |
|---|---|---|
| **App**（`LavaSecApp`） | `com.lavasec.app` | SwiftUI 應用程式。擁有 UI、持有 NetworkExtension entitlement，並透過 `NETunnelProviderManager` 控制通道。`AppViewModel` 是 VPN 生命週期的單一真相來源。 |
| **封包通道**（`LavaSecTunnel`） | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider` 的子類別 `PacketTunnelProvider`（亦稱 `LavaSecTunnel`）。剖析 DNS 封包、擷取被查詢的網域、對照記憶體對映的已編譯快照進行評估，並將獲准的查詢轉發至上游。受到每個 process 約 50 MiB jetsam 記憶體上限的約束。 |
| **小工具**（`LavaSecWidget`） | `com.lavasec.app.widget` | 一個 `WidgetBundle`，其唯一成員為 `LavaProtectionLiveActivityWidget`——即 Live Activity／Dynamic Island 的呈現。 |

共用程式碼分布於兩處：

- **`LavaSecCore`**（`Sources/LavaSecCore/`）——與平台無關的核心：篩選引擎、解析器傳輸層、快照／預算運算、防護儲存體，以及 `GuardianMascotAnimation` 核心。依據 `VPNLifecycleController.swift:3-6`，NetworkExtension 型別刻意排除在此模組之外，使其生命週期邏輯能以 fake 進行測試；應用程式 target 則提供以 `NetworkExtension` 為基礎的 conformance。
- **`Shared/`**——編譯進一個以上 target 的程式碼（例如 `AppGroup.swift`、`LavaActivityAttributes.swift`、`LavaProtectionCommandService.swift`、`SoftShieldGuardian.swift`、`LavaLiveActivityIntents.swift`）。

封包通道的內部機制（DNS 剖析、已編譯快照、加密解析器傳輸層，以及篩選規則預算）在 [DNS 篩選與封鎖清單](./dns-filtering-and-blocklists.md) 中有深入說明。本文件聚焦於應用程式端架構，以及應用程式與擴充功能之間的邊界。

---

## 2. 應用程式 ↔ 擴充功能 IPC {#2-app-extension-ipc}

應用程式與封包通道擴充功能是各自獨立的 process。它們透過三種機制協調，全部錨定在 App Group 上。

### App Group 容器 {#app-group-container}

`group.com.lavasec` 是共用容器，讓應用程式、通道與小工具讀寫相同的 `LavaSecCore` 狀態與設定。`LavaSecAppGroup`（`Shared/AppGroup.swift`）集中管理每一個共用鍵與檔名，使這些 process 永遠不會在字串常數上發生分歧，包括：

- 已編譯快照產物（`filter-snapshot.compact`、`filter-snapshot.json`）、序列化的 `app-configuration.json`、通道健康狀態（`tunnel-health.json`）、診斷資料，以及網路活動記錄。
- 防護工作階段與暫停狀態的共用 `UserDefaults` 鍵。這些直接別名（alias）至 `LavaSecCore` 儲存體（`AppGroup.swift:38-41`）——`ProtectionSessionStore.Keys`、`ProtectionPauseStore.Keys`——因此應用程式、通道與 Live Activity intent 共用同一套鍵配置、同一個版本計數器，以及同一套去重複（dedup）機制。
- catalog 快取目錄與裝置上的除錯記錄檔。

容器 URL 透過 `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)` 解析取得。

### 命令／provider 訊息（控制路徑） {#command-provider-message-the-control-path}

應用程式以 **`sendProviderMessage`** 驅動通道執行所有命令。`AppViewModel.sendTunnelMessage(_:)`（`AppViewModel.swift:7215`）會從快取的 manager 取得使用中的 `NETunnelProviderSession`，並呼叫 `session.sendProviderMessage(...)`。payload 由 `LavaSecProviderMessageCodec`（`AppGroup.swift:55-79`）編碼為一個小型 JSON 封套，攜帶一個訊息 `kind` 與一個選用的 `operationID`（用於端對端延遲追蹤）。

可辨識的訊息 kind 為 `LavaSecAppGroup` 上的常數：

| 訊息常數 | 在通道中的作用 |
|---|---|
| `reloadSnapshotMessage`（`"reload-snapshot"`） | 強制重新載入已編譯的篩選快照。 |
| `reloadProtectionPauseMessage`（`"reload-protection-pause"`） | 僅重新讀取共用的暫停狀態。 |
| `reloadConfigurationMessage`（`"reload-configuration"`） | 重新載入設定；只有*解析器身分（resolver-identity）*變更才會觸發可見的重新連線。 |
| `clearDiagnosticsMessage`、`clearFilteringCountsMessage`、`clearNetworkActivityLogMessage`、`flushTunnelHealthMessage` | 診斷／記錄維護。 |

在通道端，`PacketTunnelProvider.handleAppMessage(_:completionHandler:)`（`PacketTunnelProvider.swift:729`）會解碼封套並依 `kind` 進行分支。值得注意的是，`reload-configuration` 會載入新設定，使非解析器欄位（診斷開關、付費狀態）生效，但只有在解析器身分確實變更時才會重設 DNS 執行時並重新套用通道網路設定——即可見的重新連線（`PacketTunnelProvider.swift:768-792`）。診斷旗標或付費狀態的變更永遠不會中斷既有連線。

應用程式的 `notifyTunnelSnapshotUpdated()`／`notifyTunnelProtectionPauseUpdated()` 輔助函式（`AppViewModel.swift:7062`／`7070`）是傳送這些訊息的輕量包裝。

### 為何採用 provider 訊息作為 應用程式→通道 控制路徑 {#why-provider-messages-for-apptunnel-control}

**`sendProviderMessage` 是唯一的 應用程式→通道 控制路徑——並不存在 應用程式→通道 的 Darwin 訊號。** 早期設計曾在暫停時張貼一個 `CFNotificationCenter` Darwin 訊號，並在擴充功能內部觀察它，但它在 NetworkExtension process 中從未可靠地觸發，因而被移除。命令服務不再張貼 `CFNotificationCenterPostNotification`，通道也不再新增 `CFNotificationCenterAddObserver`——兩者都由原始碼自省（source-introspection）測試斷言為「不存在」（命令服務的張貼見 `Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574`；通道的觀察者見 `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847`），以防止再次被引入。（命令服務與通道中仍保留的 `import Darwin` 行是供 `flock`／socket 原語使用，並非用於通知。）

不過，反方向上*確實*仍有一條 Darwin 路徑存在。通道會向應用程式張貼一個健康狀態已變更的提示：`TunnelHealthSignal.DarwinProtectionSignalNotifier`（`Sources/LavaSecCore/TunnelHealthSignal.swift`）會在頻道 `com.lavasec.protection.tunnel-health-changed` 上張貼 `CFNotificationCenterPostNotification`（頻道名稱位於 `TunnelHealthSignal.swift`，而非 `AppGroup.swift`），應用程式則透過 `DarwinNotificationObserver`（`LavaSecApp/DarwinNotificationObserver.swift`、`CFNotificationCenterAddObserver`）觀察它，並在 `AppViewModel` 中接線以呼叫 `handleTunnelHealthNudge()`。這個 通道→應用程式 的健康提示由 `LavaLiveActivitySourceTests.swift:1059-1075` 斷言為*存在*。

對於 應用程式→通道 控制，暫停是透過寫入共用的 `ProtectionPauseStore`，並接著送出 `reload-protection-pause` provider 訊息來傳遞，使通道執行 `refreshProtectionPauseStateOnly`。`AppViewModel.swift:4995-4996` 直接記載了此規則：應用程式「也從不依賴快照 Darwin 觀察者，一律使用 `sendProviderMessage`」。請將 App Group（共用狀態）+ `sendProviderMessage`（喚醒／控制訊號）這一組合視為 應用程式→通道 的控制路徑。

### Live Activity 命令服務 {#live-activity-command-service}

`LavaProtectionCommandService.perform(_:)`（`Shared/LavaProtectionCommandService.swift`）是 Dynamic Island／Live Activity 動作的進入點（`LavaLiveActivityActionRequest`：`pause-5-minutes`／`pause-10-minutes`／`pause-15-minutes`／`pause-configured`（Live Activity 的單一暫停按鈕，其長度為使用者設定的值）、`resume`、`reconnect`）。`LavaLiveActivityIntents.swift` 中的 `LiveActivityIntent` 在應用程式 process（持有 NetworkExtension entitlement）中執行，因此：

- **暫停／恢復**會流經一個跨 process 檔案鎖（`protection-command.lock`、`flock`），以及 `LavaSecCore` 的 `ProtectionPauseStore`／`ProtectionSessionStore`，這些負責版本鑄造與重複命令去重複（`commandID` 將呼叫者的 operation id 串接起來，使重新送達的命令無法鑄造出第二個版本）。其結果會排程一次受版本守護的 Live Activity 更新。
- **重新連線**則直接處理（`performReconnect`、`LavaProtectionCommandService.swift:112-135`）：它呼叫 `loadAllFromPreferences` 並透過 `startVPNTunnel()` 啟動第一個已安裝的通道 manager（由於 `loadAllFromPreferences` 已限定在本應用程式的 NE 設定範圍內，第一個 manager 即為 Lava 的——這點與 `VPNLifecycleController.matchingManagers()` 不同，它不做明確的身分比對）。Connect-On-Demand 已啟用，因此這只是強制立即連線；應用程式的狀態調和接著會在連線完成後使 Live Activity 回到 `.on`。

---

## 3. VPN 生命週期與控制 {#3-vpn-lifecycle-control}

`AppViewModel`（`@MainActor final class`、`AppViewModel.swift:723`）是應用程式中 VPN 生命週期的單一真相來源。它統籌開啟／關閉、快取使用中的 `NETunnelProviderManager`，並將狀態發佈給 SwiftUI。

### Manager 選取與生命週期運算 {#manager-selection-and-lifecycle-math}

可重用、不依賴 NetworkExtension 的生命週期邏輯位於 `VPNLifecycleController<Repository>`（`Sources/LavaSecCore/VPNLifecycleController.swift`）。應用程式提供以 `NETunnelProviderManager` 為基礎的 `VPNManagerControlling`／`VPNManagerRepositoryProtocol`／`VPNStatusChangeWaiting` conformance；該 controller 負責：

- **選取與去重複**——`matchingManagers()` 透過 `LavaTunnelConfigurationIdentity.matches(...)` 篩選出 Lava 所擁有的 manager，依 `selectionPriority` 排序（使用中者優先，其次為標準顯示名稱），並由 `removeDuplicateManagers(keeping:)` 收斂至單一倖存者。
- **連線／停止等待**——`waitForConnect`／`waitForStop` 以 `startGraceInterval` 的容許度輪詢即時連線狀態，因為在 `startVPNTunnel` 之後不久，連線可能會短暫讀到非 pending 的狀態，之後 iOS 才將其轉換為 `.connecting`。

### 開啟／關閉 {#turn-on-turn-off}

`enableProtection(...)`（`AppViewModel.swift:5764`）採用**快取優先**：當目前設定存在一份已確認可重用的備妥產物時，VPN 可立即從快取啟動，同時進行中的 catalog 同步會在背景持續刷新，而 `performCatalogSync` 會在完成時調和正在執行的通道。只有在沒有任何有效起始點可用時（例如使用者剛變更已啟用清單集合，使快取產物身分失效），它才會阻塞等待同步。

`disableProtection(...)`（`AppViewModel.swift:5972`）會*先*關閉 Connect-On-Demand，*再*停止通道，以免 iOS 立即將其重新連線。`setManagerOnDemand(_:on:)`（`AppViewModel.swift:6253`）會安裝一個 `NEOnDemandRuleConnect`（介面比對為 `.any`）並儲存偏好設定——iOS 必須要儲存（而不只是設定）才會遵循此變更。

### 狀態觀察（以及一個發熱注意事項） {#status-observation-and-a-heat-caveat}

`AppViewModel` 觀察 `.NEVPNStatusDidChange`（`AppViewModel.swift:1034-1056`）並發佈 `vpnStatus`／`isVPNConfigurationInstalled`。關鍵在於，當已快取某個 manager 時，它會讀取該快取 manager 的即時連線，而非強制執行 `loadAllFromPreferences` 刷新：`loadAllFromPreferences` 本身會重新張貼 `NEVPNStatusDidChange`，而在觀察者中進行強制刷新會產生一個自我延續的風暴——原始碼內的註解（`AppViewModel.swift:1046-1048`）記錄了實測約 370 事件／秒，以及它所造成的 134% CPU 發熱迴歸。已發佈屬性只在真正的狀態轉換時才會改變，因此閒置時的滴答（idle tick）不再使 SwiftUI 失效。

### Fail-closed 的 on-demand 調和 {#fail-closed-on-demand-reconcile}

Connect-On-Demand 可能在啟動時（或在 iOS 因網路變更而拆除通道之後）於應用程式尚未推送快照前，**冷啟動**通道。沒有可重用持久化快照的冷通道會以 **fail-closed** 方式載入——封鎖所有流量——且永遠不會自行恢復。`AppViewModel` 在兩條啟動路徑中處理此情形，兩者皆以引導完成為前提（`hasCompletedOnboarding`，對映 `@AppStorage("hasSeenLavaOnboarding")` 旗標）：

- **引導完成後**——`reconcileTunnelSnapshotAfterLaunch()`（`AppViewModel.swift:7122`）會在啟動時防護為使用中狀態時執行：它會準備啟動快照、持久化共用狀態，並送出 `reload-snapshot`，使通道載入其真正規則、脫離 fail-closed。fail-closed 仍是安全的預設值；這只是迅速地將其取代。（修正了在 Connect-On-Demand 維持通道存活時，應用程式重啟後篩選器顯示為紅色／流量被封鎖的問題。）
- **引導進行中**——`neutralizeInheritedProtectionDuringOnboarding()`（`AppViewModel.swift:7181`）會在引導尚未完成時，*先於*任何網路工作執行。iOS 在刪除應用程式時不一定會可靠地移除 VPN 設定檔，因此重新安裝可能會繼承一份孤立、已啟用 on-demand 的設定，在使用者尚未選擇任何封鎖清單前就帶起一個 fail-closed 冷通道。此路徑會**移除**該設定（`removeFromPreferences`），而非對其儲存一項修改——對本次安裝並不擁有的設定檔呼叫 `saveToPreferences`，會在應用程式初始化時、引導 sheet 渲染之前，重新彈出「新增 VPN 設定」系統提示，觸發該對話框。在乾淨安裝時，以及在繼承的設定已是惰性時，它都是 no-op。

---

## 4. Guardian／狀態模型 {#4-guardian-state-model}

這裡有兩套相關的狀態詞彙：連線*評估*與 Guardian *吉祥物*狀態。

### 連線評估 {#connectivity-assessment}

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)`（`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`）將一個 `TunnelHealthSnapshot` 對映至一個 `ProtectionConnectivityAssessment`，其具有**六種嚴重程度**與**兩種動作**之一：

- 嚴重程度：`healthy`、`recovering`、`usingDeviceDNSFallback`、`dnsSlow`、`networkUnavailable`、`needsReconnect`。
- 主要動作：`turnOff` 或 `reconnect`。

這一個單一評估同時驅動應用程式內的 Guard 介面以及（進一步對映後的）Dynamic Island 狀態，因此兩者永不矛盾。

**誠實底線（v1.0）。** 一次當前、未被涵蓋的 DNS smoke-probe 失敗永遠不能被讀為 `.healthy`——評估會浮現 `.recovering`，直到某次探測真正成功為止，因此在卡住的主要上游上由後援承載的流量，不再被描繪為「已保護」。重新連線邏輯所依據的是 `consecutiveDNSSmokeProbeFailureCount` 與 `lastPrimaryUpstreamSuccessAt`（僅限主要），而非通用的上游計數器；而一個保持可連線卻持續**拒絕**那個已知良好探測的解析器（劫持／captive／過時），會透過一個以解析器身分為範疇的 `consecutiveRejectedSmokeResponseCount` 被升級為值得重啟（LAV-87），即使通用連敗計數在不穩定的漫遊網路上不斷被重設。

### 連線通知 {#connectivity-notifications}

`ProtectionConnectivityNotificationPolicy`（`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`）會把評估轉化為至多一則待處理的本機通知，並加以節流（600 秒）與去重。v1.0 新增：

- 一種獨立的 **`dnsSlow`** 類別（「Lava DNS is slow」）——DNS 緩慢以往會重用 `reconnectNeeded` 類別，因此真正的中斷無法將其取代。
- **升級／取代**——一個嚴格更急迫的問題（只有 `reconnectNeeded` 凌駕其餘）可以取代一個正在顯示、排名較低的橫幅，繞過「問題已待處理」防護與節流，因此在 Device-DNS 後援之後發生卡住時，會浮現可操作的「重新連線」提示，而不是留著一個讓人安心的橫幅。
- 一次**持久化遷移**（`ProtectionConnectivityNotificationStore`，schema v2，透過 `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded` 接線）會把一個舊有、待處理的 `reconnect-needed` 標記降級為 `dnsSlow`，使升級在升版後仍能運作。

### Device-DNS 擷取重試 {#device-dns-capture-retry}

當作用中的設定依賴裝置解析器（作為主要或後援）時，一次網路交接／喚醒可能讓通道持有一份空的系統解析器擷取——一種無聲的卡住。`DeviceDNSFallbackPolicy` 驅動一次**有界重試**（`shouldRetryDeviceDNSCapture`、`deviceDNSCaptureRetryInterval` 1 秒、`deviceDNSCaptureMaxRetryAttempts` 5）：通道每秒重讀系統解析器，最多五次嘗試，直到擷取非空，然後就地採用它——無需重啟通道即可自動復原（事件 `device-dns-capture-retry`／`-exhausted`）。對於純 DoH/DoT/DoQ 設定，它是 no-op（`currentConfigurationDependsOnDeviceDNS()`）。

### Guardian 吉祥物狀態 {#guardian-mascot-states}

Soft Shield Guardian 吉祥物恰好有**七種**情緒狀態——`GuardianMascotState`（`GuardianMascotAnimation.swift:3`）：`sleeping`、`waking`、`awake`、`paused`、`retrying`、`concerned`、`grateful`。每個狀態都宣告其 `allowedNextStates`，因此狀態轉換受到約束（例如 `grateful` 只會回到 `awake`；`GuardianMascotAnimation.swift:12-29`）。語意如下：

- `retrying` = 平靜的自我修復。
- `concerned` = 溫和的求助。
- `grateful` = 慶祝性的成功（用於引導／設定介面，並非連線對映）。

`GuardianMascotAnimation` 是 `LavaSecCore` 中的程序化動畫核心；`SoftShieldGuardian`（`Shared/SoftShieldGuardian.swift`）是 SwiftUI 渲染，並支援由 `GuardianShieldStyle` 選取的自訂外觀（顯示名稱為 Original、Fire Opal、Amethyst、Obsidian、Cherry Quartz、Emerald、Kiwi Crème——`LavaActivityAttributes.swift:5-56`，`displayName` 對映位於第 18-35 行）。少數原始值與其顯示名稱不一致（例如 `fireOpal = "emberObsidian"`、`cherryQuartz = "strawberryObsidian"`，且 `purpleObsidian` 渲染為「Amethyst」），因此請持久化原始值，而非標籤。

### 兩者如何連結 {#how-the-two-connect}

Live Activity 的 `LavaActivityAttributes.ProtectionState`（`Shared/LavaActivityAttributes.swift`）透過 `guardianState` 將評估橋接至吉祥物狀態：`on → awake`、`paused → paused`、`reconnecting`／`networkUnavailable → retrying`、`needsReconnect → concerned`（`LavaActivityAttributes.swift:95-105`）。`AppViewModel` 從相同的 `protectionConnectivityAssessment`（`AppViewModel.swift:3131-3147`）為 Dynamic Island 選擇防護狀態：`networkUnavailable` 嚴重程度成為 `.networkUnavailable`、`recovering` 成為 `.reconnecting`、`reconnect` 主要動作成為 `.needsReconnect`，其餘情況則為 `.on`。

> 注意：`LavaTier`（平靜 → **Floor**／慶祝 → **Window**／技術 → **Workshop** 的設計系統深度 enum）發行於設計系統層（`LavaSecApp/LavaDesignSystem/LavaTokens.swift`），並接線至代表性介面——參見 [設計系統](../design-system/overview.md)。它治理的是設計系統的深度，而非此處所述的防護／通道用戶端路徑。

---

## 5. Live Activity 與小工具 {#5-live-activity-widget}

小工具 target 僅渲染 Live Activity 與 Dynamic Island。`LavaSecWidgetBundle`（`LavaSecWidget/LavaSecWidget.swift`）公開單一的 `LavaProtectionLiveActivityWidget`，這是一個 `ActivityConfiguration(for: LavaActivityAttributes.self)`，具有：

- 一個鎖定畫面檢視、一個展開的 Dynamic Island 中央區域，以及渲染 `SoftShieldGuardian` 加上一個狀態符號（glyph）的 compact／minimal 呈現。compact／鎖定畫面檢視會在每秒一次的 `TimelineView` 上重新計算*有效*防護狀態，使暫停倒數無需推播即可保持即時。

`LavaActivityAttributes.ContentState` 攜帶 `protectionState`、一個 `resumeDate`（供暫停倒數使用）、`pauseRequiresAuthentication`，以及所選的 `shieldStyle`。解碼具有容錯性——缺少 `shieldStyle` 時會回退至 `.original`——因此較舊的 Live Activity payload 仍能正常運作。

在應用程式端，`LavaLiveActivityController`（`LavaSecApp/LavaLiveActivityController.swift`）擁有即時的 `Activity<LavaActivityAttributes>`：它觀察 ActivityKit 授權變更、僅在 phone／pad idiom 上提供 Live Activity，並由 `reconcile(...)` 啟動／更新／結束活動以符合所請求的防護狀態。`AppViewModel.reconcileLiveActivity()`（`AppViewModel.swift:3069`）是重新計算期望狀態並呼叫 controller 的單一通道。Dynamic Island 按鈕會派發 `LiveActivityIntent`，這些 intent 會如 [§2](#2-app-extension-ipc) 所述呼叫 `LavaProtectionCommandService`。

---

## 6. 引導流程 {#6-onboarding-flow}

引導由 `LavaOnboardingView`（`LavaSecApp/OnboardingFlowView.swift`）呈現，並由宣告於 `RootView`（`RootView.swift:32`）的 `@AppStorage("hasSeenLavaOnboarding")` 旗標把關。此流程是一連串 `OnboardingPage`（`OnboardingFlowView.swift:403-409`）：`lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`。

發行版的起始設定來自 `OnboardingDefaults`（`Sources/LavaSecCore/OnboardingDefaults.swift`）。`AppConfiguration.lavaRecommendedDefaults` 只啟用較寬鬆的建議來源（Block List Basic）、選擇 **Device DNS** 作為解析器——`DNSResolverPreset.device`（id `device-dns`），即網路自身的 DNS；像 Google DoH 這類加密預設為選擇性加入（opt-in），不會被提升為預設——啟用 device-DNS 後援，並保持本機記錄開啟——同時 `protectionEnabled: false`，因此防護只有在使用者選擇時才會開啟。`OnboardingDefaultsSummary` 會將這些選擇格式化以供顯示（「Continue without account」為帳號預設）。

在最後設定 `hasSeenLavaOnboarding = true`，正是翻轉 `hasCompletedOnboarding` 的動作，而後者接著會啟動 [§3](#3-vpn-lifecycle-control) 中所述的啟動調和路徑。在那之前，引導進行中的中性化路徑會避免任何繼承的 fail-closed 通道封鎖流量。

---

## 7. 應用程式狀態：`AppViewModel` {#7-app-state-appviewmodel}

`AppViewModel`（`@MainActor final class AppViewModel: ObservableObject`、`AppViewModel.swift:723`）是核心的應用程式端狀態擁有者。除了 VPN 生命週期之外，它還發佈 UI 所綁定的各個介面，包括：

- **防護與通道**——`vpnStatus`、`isVPNConfigurationInstalled`、`isConfiguringVPN`、`tunnelHealth`（`TunnelHealthSnapshot`）、`temporaryProtectionPauseUntil`，以及面向使用者的 `vpnMessage`／`vpnMessageIsError`。
- **設定與 catalog**——`AppConfiguration`、`isSyncingCatalog`、`catalogVersion`／`catalogGeneratedAt`，以及已編譯規則計數（`compiledRuleCount`、`protectedRuleCount`、`compiledBlocklistRuleCount`）。
- **診斷**——`DiagnosticsStore` 與 `NetworkActivityLog`（全部在本機；參見下方的隱私承諾）。
- **帳號與備份**——`accountAuthState`、`encryptedBackupState`、`isAutomaticBackupEnabled`，以及 **Lava Security Plus** 方案／權益狀態。
- **自訂與呈現**——`appearancePreference`、`lavaGuardLook`（`GuardianShieldStyle`）、`lavaGuardProgress`，以及 `usesLiveActivities`。

它將生命週期序列化委派給一個 `protectionActionOrchestrator`（如此一來背景復原不會與使用者的開啟動作交錯），持有快取的 `tunnelManager`，並透過 [§2](#2-app-extension-ipc) 中的 provider 訊息輔助函式，將所有快照／設定／暫停變更驅動至擴充功能。

> **隱私框架。** DNS 篩選會在本裝置上於本機完成。`AppViewModel` 所發佈的診斷與網路活動介面僅儲存於本機——Lava 永遠不會收到你的日常 DNS 查詢、瀏覽歷史或逐網域遙測資料。任何選用的帳號備份皆為**零知識**（在裝置上加密；Lava 至多只能儲存密文），包括基於通行密鑰的復原——其金鑰在裝置上以 PRF 衍生，沒有伺服器持有的密鑰。伺服器邊界請參見 [系統總覽](./system-overview.md)。

---

## 相關文件 {#related-docs}

- [系統總覽](./system-overview.md)——在一個畫面上呈現整個系統：應用程式、catalog Worker 與 Supabase，以及貫穿全文使用的信任邊界與狀態圖例。
- [DNS 篩選與封鎖清單](./dns-filtering-and-blocklists.md)——此處僅在控制邊界提及的封包通道內部機制：已編譯的篩選引擎、加密解析器傳輸層（DoH／DoH3／DoT／DoQ）、篩選規則預算、封鎖清單 catalog，以及僅來源 URL（source-url-only）的重新散布模型。
- [帳號與零知識備份](./accounts-and-backup.md)——`AppViewModel` 所統籌的登入提供者與零知識備份封套（包括零知識、PRF 衍生的通行密鑰復原插槽）。
- [後端與資料](./backend-and-data.md)——`lavasec-api` catalog Worker、Cloudflare R2，以及位於 應用程式↔伺服器 邊界另一側的 Supabase schema／RLS。
- [設計系統](../design-system/overview.md)——`LavaTier` 深度模型、Soft Shield Guardian 的七種狀態與盾牌外觀，以及用戶端所渲染的文案／在地化慣例。
- [第三方聲明](../legal/third-party-notices.md) 與 [GPL 僅來源 URL 合規決策](../legal/gpl-source-url-only-compliance-decision.md)——用戶端所使用的 catalog／篩選管線背後的散布限制。
