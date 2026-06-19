---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 功能目錄 {#feature-catalog}

> 對象：PM／工程。本目錄僅涵蓋**目前已實作**的功能集。任何已設計但尚未建置的內容皆位於私有藍圖中，而非此處。

Lava Security 是一款隱私優先的 iOS 應用程式，透過 NetworkExtension 封包通道在**裝置本機**篩選 DNS，為非技術使用者（父母、長者）封鎖惡意與不需要的網域——核心防護永久免費，且無需帳號。

下方每項功能背後的隱私承諾：

> 所有 DNS 篩選都在裝置上完成；Lava Security 絕不會將你的瀏覽流量導向其伺服器，也絕不會接收你所造訪的網域串流——後端僅保有目錄中繼資料、不透明的每位使用者加密備份，以及你選擇傳送的匿名化診斷資料。

## 如何閱讀本目錄 {#how-to-read-this-catalog}

- **免費**——人人皆可使用，無需帳號、無需購買。
- **Plus**——由 Lava Security Plus 解鎖，這是唯一可選的付費層級。Plus 僅解鎖**自訂功能**；它絕不會限制基本安全，也絕不會讓付費使用者繞過安全防護欄。
- 每一列皆為**已實作**，除非另有標示。狀態圖例：**已實作**＝已發佈並在程式碼中確認；**規劃中**＝已設計、尚未建置；**已捨棄**＝遭否決或還原。規劃中／已捨棄的項目記錄於私有藍圖，而非此處。

各層級上限的真實來源位於 `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`（`FeatureLimits.free` / `FeatureLimits.paid`，別名為 `.plus`）。Plus 權益的**閘門**是一個本機旗標（`isPaid`）——即真實來源。後端**鏡像** App Store 權益（`POST /v1/account/entitlements/app-store-sync` 會更新插入一筆 `entitlements` 記錄），但該記錄只是鏡像，並非閘門；目前尚無後端同步驅動閘門控制。

---

## 1. 防護與 VPN {#1-protection-vpn}

核心產品：本機僅限 DNS 的封包通道，以及圍繞其運作的平靜狀態模型。

| 功能 | 層級 | 備註 |
|---|---|---|
| **本機僅限 DNS 的封包通道** | 免費 | `LavaSecTunnel`（`NEPacketTunnelProvider`、`com.lavasec.app.tunnel`）攔截 DNS 並在裝置上評估每個網域。沒有瀏覽流量會經由 Lava Security 導向。通道位址 `10.255.0.2`，DNS 伺服器 `10.255.0.1`。 |
| **篩選決策優先序** | 免費 | `threat guardrail block > local allowlist (allowed exceptions) > blocklist > default-allow`；無效網域會被封鎖。（`FilterSnapshot.decision()`。） |
| **查詢優先序（bootstrap 優先）** | 免費 | `resolver-bootstrap > temporary-pause > filter`——解析器自身的主機名稱絕不會被封鎖。（`DNSQueryDispatcher`。） |
| **失敗即封閉的冷啟動** | 免費 | 沒有可重用快照的冷通道會安裝一個 `FailClosedRuntimeSnapshot`，封鎖所有流量，而非洩漏未篩選的 DNS。 |
| **Connect-On-Demand** | 免費 | `NEOnDemandRuleConnect` 讓防護持續運作／自動重啟——**僅在**確認連線**之後**啟用，絕不在描述檔安裝時啟用，並在引導尚未完成時停用，使全新安裝無法啟動一個無法關閉的通道。 |
| **暫時暫停（5／10 分鐘）＋恢復** | 免費 | 暫停／恢復透過 `LavaProtectionCommandService`，在 flock 檔案鎖下執行，並對修訂進行去重。 |
| **需驗證的暫停** | 免費 | 可選的逐介面閘門（`SecurityProtectedSurface.protectionPause`）：暫停需要本機裝置驗證；命令服務會拒絕未經驗證的暫停，且 Live Activity 會隱藏暫停按鈕。 |
| **重新連線** | 免費 | 直接重啟通道（繞過命令服務的暫停管線）。 |
| **Soft Shield Guardian 狀態模型** | 免費 | 7 種表情狀態——`sleeping, waking, awake, paused, retrying, concerned, grateful`（`GuardianMascotAnimation.swift`，LavaSecCore）。6 種連線嚴重度收斂為 4 種面孔；在應用程式內、引導流程中與 Live Activity 中皆以相同方式呈現。 |
| **連線評估** | 免費 | 6 種嚴重度（`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`）驅動 guardian 面孔與狀態文案。 |
| **效能強化** | 免費 | 快取優先的啟動、進行中查詢的合併、有界平行擷取，以及抖動合併（依模組化加速工作的量測，在 iPhone 15 Pro 上熱啟動約 ~112 ms）。 |

> **裝置防護欄（人人適用，絕非付費牆）：** 為所有使用者強制執行一個硬性的 `~3.26M-rule` 上限（在 iOS `~50 MiB` 的每個擴充功能記憶體上限下，以 32 MB 常駐為目標），凌駕於任何層級之上（`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`、`maxFilterRuleCount`）。超出預算的設定會被確定性地拒絕（`exceedsDeviceMemoryBudget`），而非讓通道被 jetsam 終止。

---

## 2. 封鎖清單與篩選 {#2-blocklists-filtering}

何者會被封鎖、如何選擇清單，以及層級界線。

| 功能 | 層級 | 備註 |
|---|---|---|
| **僅來源 URL 的封鎖清單** | 免費 | Lava Security 只發佈上游 URL ＋ 接受的雜湊值；裝置自行擷取／解析清單**位元組**。Lava Security **絕不**儲存、鏡像、轉換或提供第三方封鎖清單位元組。請參閱 [GPL 僅來源 URL 合規決策](../legal/gpl-source-url-only-compliance-decision.md)。 |
| **精選目錄（10 個來源）** | 免費可啟用 | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift`（`DefaultCatalog.curatedSources`）：Block List Basic、Block List Project Phishing／Scam／Ransomware、Phishing.Database Active Domains、HaGeZi Multi Light／Normal／PRO mini／PRO、OISD Small。 |
| **免費預設封鎖清單** | 免費 | 全新安裝會啟用 **Block List Project Phishing ＋ Scam**（兩個標示為 `defaultEnabled: true` 的來源；`DefaultCatalog.recommendedDefaultSourceIDs`）。 |
| **裝置端解析／正規化／去重** | 免費 | `BlocklistParser` 支援 auto/plain/hosts/adblock/dnsmasq，捨棄註解／空白／無效項，對完全相同的字串去重，每份清單上限 1,000,000 條規則。 |
| **上游位元組驗證** | 免費 | 擷取的位元組會計算 SHA-256，僅當校驗碼存在於目錄的 `accepted_source_hashes` 時才接受；不符時 Lava Security 會回退至上次良好的快取或失敗即封閉。 |
| **受保護網域篩選** | 免費 | 每個解析後的來源都會剝除受保護的 Lava Security／Apple／身分提供者網域（apple.com、icloud.com、lavasecurity.app、google.com、accounts.google.com 等），使上游清單無法破壞應用程式、通道或登入。 |
| **允許例外（允許清單）** | 免費 | 使用者管理的允許清單，可在封鎖清單之外允許網域。免費上限：10 個允許／10 個封鎖網域（`FeatureLimits.free`）。 |
| **篩選規則預算（層級量度）** | 免費／Plus | 已發佈的層級量度為已編譯網域**規則**總數：**免費 500K／Plus 2M**（`lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` 中的 `maxFilterRules`）。取代舊有的清單數量上限。超出層級的設定會呈現 `exceedsTierFilterRuleLimit`。 |
| **更高的網域上限** | Plus | 500 個允許／500 個封鎖網域（`FeatureLimits.plus`）。 |
| **自訂封鎖清單** | Plus | `allowsCustomBlocklists`。自訂清單在裝置上擷取與解析，於本機快取，絕不代理至 Lava Security 伺服器。 |
| **熱啟動成品重用** | 免費 | 一份資訊清單＋身分指紋讓通道得以重用磁碟上的精簡快照而無需重新編譯；當輸入變更時，重用會被拒絕（並附上僅含欄位名稱、保護隱私的原因）。 |

> 權威性的預算強制執行在編譯時針對去重後的聯集進行（`FilterSnapshotPreparationService`）；先檢查裝置上限，再檢查層級限制。選取時的 UI 計量表使用逐清單加總，並帶有 1.10 的軟性上限餘裕。

---

## 3. 加密 DNS {#3-encrypted-dns}

未封鎖查詢的解析器傳輸與路由。

| 功能 | 層級 | 備註 |
|---|---|---|
| **五種解析器傳輸** | 免費 | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic`（`DNSResolverTransport`）。 |
| **DoH／DoH3** | 免費 | 以 URLSession 為基礎的 DoH，優先採用 HTTP/3。UI **僅在實際觀察到 h3 協商時**才標註 **`DoH3`（無斜線）**，例如「Quad9 (DoH3)」——偏好採用，絕不承諾（`DoHTransport`）。 |
| **DoT** | 免費 | 集區化的 `NWConnection`（每個端點最多 4 條），具備閒置過時刷新與一次全新連線重試。 |
| **DoQ**（僅限自訂） | Plus | DNS-over-QUIC **沒有內建預設值**——只能透過**自訂 `doq://` 解析器**取得，而自訂 DNS 屬於 Plus。**每次查詢開啟一條全新的 QUIC 連線**（4 通道集區提供並行性，而非握手重用）；連線重用延後至 iOS-26 部署下限。 |
| **預設解析器** | 免費 | 裝置 DNS（預設）、Google Public DNS、Cloudflare 1.1.1.1、Quad9 Secure、Mullvad——在有提供之處以 IP／DoH／DoT 變體形式（`DNSResolverPreset.allPresets`）。 |
| **解析器路由與容錯移轉** | 免費 | `ResolverOrchestrator` 依傳輸方式路由，當加密方案沒有端點時降級至 plain DNS，進行逐端點容錯移轉並帶有退避閘門，然後是裝置 DNS 後援。 |
| **裝置 DNS 後援** | 免費 | 當所選解析器無法使用時，回退至目前網路的解析器；**預設開啟**。以 `usingDeviceDNSFallback` 嚴重度呈現。 |
| **自訂 DNS** | Plus | `allowsCustomDNS`——使用者提供的解析器（包含為自訂預設值解析 DNS-stamp）。 |

---

## 4. 帳號與零知識備份 {#4-accounts-zero-knowledge-backup}

可選的帳號登入與加密設定備份。這些皆非使用防護的必要條件。

| 功能 | 層級 | 備註 |
|---|---|---|
| **可選的帳號登入（Apple ＋ Google）** | 免費 | 原生 id_token 流程在 Supabase Auth 進行交換（`grant_type=id_token`），帶有雜湊過的 nonce；只有最終產生的 Supabase 工作階段會儲存於裝置本機的 Keychain。電子郵件／密碼登入刻意不提供（已捨棄）。 |
| **零知識加密備份** | 免費 | 用戶端 AES-256-GCM 信封；隨機的酬載金鑰由 PBKDF2-HMAC-SHA256（210k 次迭代）金鑰槽包裝。只有密文＋非機密中繼資料會上傳至 Supabase `user_backups`（依使用者 RLS）。伺服器在沒有使用者持有的祕密下無法解密。 |
| **最小化的備份酬載** | 免費 | 備份已啟用的封鎖清單 ID、允許／封鎖網域、解析器設定、本機記錄偏好、guardian 外觀等——並明確排除 `isPaid`、QA 旗標、診斷、快照與完整封鎖清單位元組。 |
| **裝置祕密金鑰槽** | 免費 | 在僅限本裝置的 Keychain（`...ThisDeviceOnly`，不與 iCloud 同步）中的 32 位元組裝置祕密，用於無縫的同裝置復原。 |
| **復原碼＋輔助復原** | 免費 | 一組 8 字的 CVCV 復原碼（~105 位元），透過 SHA256 與伺服器持有的復原分片結合，以解鎖輔助復原金鑰槽。雙因子：任一半單獨都無法解密。 |
| **通行密鑰復原金鑰槽** | 免費 | 可選的 WebAuthn 閘控金鑰槽，且為**零知識**：其解包金鑰是**在裝置上**從驗證器的 WebAuthn PRF（`hmac-secret`）輸出衍生（HKDF-SHA256）。伺服器不註冊任何通行密鑰、不發出任何挑戰、不持有任何復原祕密，也不公開任何通行密鑰路由——先前的伺服器託管設計已被捨棄。在實體裝置上的生產就緒度取決於 Associated Domains／AASA 託管（規劃中）。 |
| **帳號刪除／資料權利** | 免費 | 經驗證的 Worker 端點會刪除備份、設定、權益、個人檔案與錯誤回報附件，然後刪除 Supabase Auth 使用者；應用程式會登出並清除本機的解鎖材料。 |

---

## 5. Widget 與 Live Activity {#5-widget-live-activity}

鎖定畫面與動態島呈現。

| 功能 | 層級 | 備註 |
|---|---|---|
| **Live Activity** | 免費 | `LavaSecWidget`（`com.lavasec.app.widget`）：鎖定畫面與動態島上的單一 `Activity<LavaActivityAttributes>`（展開置中／compactLeading guardian／compactTrailing ＋ minimal 狀態字符）。 |
| **5 狀態防護顯示** | 免費 | `ProtectionState`：`on, paused, reconnecting, needsReconnect, networkUnavailable`——每一種對應到一個 guardian 姿態、SF Symbol 與標題。 |
| **Live Activity 動作按鈕** | 免費 | 暫停 5／10 分鐘、恢復、重新連線——`LiveActivityIntent` 透過 `LavaProtectionCommandService` 在應用程式行程中執行。需驗證的暫停變體需要本機裝置驗證。 |
| **單一去重、受修訂閘控的調和** | 免費 | `LavaLiveActivityController` 維持單一 Activity，只在實際 id／內容變更時更新，並依 `ProtectionPauseStore` 修訂閘控更新，使過時的意圖重試無法讓狀態倒退。 |
| **Live Activities 開關** | 免費 | 可在設定中由使用者切換（`setUsesLiveActivities`），僅在 iPhone／iPad 上可用。 |

---

## 6. 引導流程 {#6-onboarding}

首次執行流程，會安裝本機 VPN 設定並設定合理的預設值。

| 功能 | 層級 | 備註 |
|---|---|---|
| **多頁首次執行流程** | 免費 | `OnboardingFlowView`——6 頁：`lava, guardIntro, features, vpn, notifications, done`。（描述檔安裝與通知提示會在適當步驟發生，而非一開始。） |
| **本機 VPN 描述檔安裝** | 免費 | 在引導期間安裝本機 VPN 設定，但**不**啟用 Connect-On-Demand，因此防護絕不會在完成時悄悄自動開啟——防護介面維持權威地位。 |
| **通知權限提示** | 免費 | 在通知步驟於流程中請求。 |
| **套用建議的預設值** | 免費 | 裝置 DNS 解析器、裝置 DNS 後援開啟、本機記錄開啟（計數＋歷史＋活動）、啟用 Block List Project Phishing ＋ Scam、不使用帳號繼續（`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`、`lavaRecommendedDefaults`）。 |

---

## 7. 設定 {#7-settings}

設定、安全、診斷與意見回饋介面。

| 功能 | 層級 | 備註 |
|---|---|---|
| **應用程式解鎖密碼＋生物辨識** | 免費 | `SecurityController`：Keychain 中加鹽的 SHA256 密碼驗證器＋ `LAContext` 生物辨識，並具備應用程式解鎖的阻擋覆蓋層，以及在場景階段變更時的隱私遮罩。 |
| **逐介面防護** | 免費 | `SecurityProtectedSurface` 對六個介面進行閘控：`appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`。每一個都可獨立要求本機裝置驗證（例如設定分頁會回傳 `.requires(.appSettings)`）。 |
| **Lava Guard 外觀選擇器（7 種外觀）** | 免費 | `GuardianShieldStyle`：`original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`，每一種都搭配一個動態島字符顏色。 |
| **比對應用程式圖示** | 免費 | 可選的替代應用程式圖示，搭配所選的 guardian 外觀。 |
| **外觀** | 免費 | 淺色／深色／系統配色方案。 |
| **僅本機的記錄控制** | 免費 | 篩選計數、網域歷史記錄（診斷）與網路活動的開關——皆儲存於裝置上。 |
| **報表／活動（Guard 詳細）** | 免費 | 動態的僅本機診斷：封鎖／允許計數、通道健康度、熱門網域。網域列僅在歷史記錄選擇加入開啟時出現。可從 Guard 分頁進入詳細畫面（`GuardDestination.activity`）。 |
| **篩選器（Guard 詳細）** | 免費 | 概覽優先的篩選器畫面，含已封鎖網域／允許例外詳細內容，以及分階段的檢視／編輯／確認草稿流程（`GuardDestination.filters`）。 |
| **網路與 Lava State 活動記錄** | 免費 | 有界的僅本機事件串流，記錄網路／執行時／使用者轉換，透過 App Group 共享（`NetworkActivityLog`）。 |
| **錯誤回報** | 免費 | 由使用者觸發的精靈，會將匿名化套件傳送至 `POST /v1/bug-reports`；v1 中沒有網域歷史記錄。也可透過搖晃回報（`RageShakeDetector`）進入。 |
| **法律聲明＋版本** | 免費 | 設定中會呈現第三方法律聲明（請參閱 [第三方聲明](../legal/third-party-notices.md)）以及版本／組建頁面。 |

---

## 應用程式架構（供定位之用） {#app-architecture-for-orientation}

三個套件共享一個 App Group `group.com.lavasec`，並與一個編譯進它們的 `lavasec-ios: Shared/` 來源資料夾並存：

- **LavaSecApp**（`com.lavasec.app`）——SwiftUI 應用程式外殼；在此組建中，根層是一個雙分頁 `TabView`（**防護** ＋ **設定**），篩選器與活動則作為防護分頁下的詳細畫面進入。
- **LavaSecTunnel**（`.tunnel`）——裝置端的 DNS 篩選／解析引擎。
- **LavaSecWidget**（`.widget`）——WidgetKit Live Activity。
- **Shared/**——跨目標來源（並非套件）：App Group、命令服務、吉祥物、Live Activity 屬性／意圖。

應用程式 ↔ 擴充功能的控制使用 `NETunnelProviderSession` **provider 訊息**（`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`），而非 Darwin 通知。篩選規則以 App-Group 快照檔案（`filter-snapshot.json` / `.compact`）從應用程式 → 擴充功能傳遞。

---

## 相關文件 {#related-docs}

- 藍圖——規劃中與已捨棄的功能（Plus 定價／StoreKit 定位、Android 移植、URL 層級防護、通行密鑰 Associated-Domain 就緒度、彩蛋迷你遊戲、GPL-3.0 開源發佈等）位於私有藍圖，而非此公開目錄。
- [GPL 僅來源 URL 合規決策](../legal/gpl-source-url-only-compliance-decision.md)
- [開源清單資料條款的排除條款](../legal/open-source-list-data-terms-carveout.md)
- [第三方聲明](../legal/third-party-notices.md)
