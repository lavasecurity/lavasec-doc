---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 系統總覽 {#system-overview}

> **適用對象：** 工程師。這是 Lava Security 的全貌，濃縮於一頁之中——各個組成部分是什麼、資料如何在它們之間流動，以及信任邊界落在何處。各元件的專屬文件會深入細節；這份文件的存在，是為了讓你在閱讀那些文件之前，先能把整個系統裝進腦海裡。
>
> **權威性：** 當這份文件與某項計畫出現分歧時，**以程式碼為準**。狀態反映的是程式碼確認的現實，而非計畫的願景。請參閱底部的[狀態圖例](#8-status-legend)。

## 1. 產品一句話 {#1-product-one-liner}

Lava Security 是一款隱私優先的 iOS app，它**在裝置本機上**透過 NetworkExtension 封包通道篩選 DNS，為非技術背景的使用者（家長、長者）封鎖惡意與不需要的網域——核心防護永久免費，且無需帳號。

## 2. 隱私承諾（權威版本） {#2-the-privacy-promise-canonical}

> 所有 DNS 篩選都在裝置上進行；Lava Security 從不將你的瀏覽流量經過它的伺服器轉送，也從不接收你造訪的網域串流——後端只持有目錄中繼資料、一份不透明的每位使用者加密備份，以及你選擇傳送的匿名診斷資訊。

以下的一切，都是為了讓那句話保持為真。這套架構在伺服器端刻意保持精簡：工作交由裝置完成，後端從不會看到任何查詢。

## 3. 元件 {#3-components}

### iOS 用戶端（三個可執行目標 + 共用程式碼，一個 App Group `group.com.lavasec`） {#ios-client-three-executable-targets-shared-code-one-app-group-groupcomlavasec}

| 元件 | Bundle／位置 | 角色 | 狀態 |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | SwiftUI app 外殼；進入點，雙分頁的「防護」+「設定」導覽（「篩選」/「活動」是「防護」的明細畫面；網路活動已移至「設定 → 進階」之下）。 | 已實作 |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`；裝置端的 DNS 篩選／解析引擎。受 iOS **每個擴充功能約 50 MiB 記憶體上限**約束。 | 已實作 |
| **LavaSecWidget** | `com.lavasec.app.widget` | WidgetKit 即時動態（鎖定畫面 + 動態島）。 | 已實作 |
| **Shared/** | `Shared/` | 跨目標的原始碼：App Group、命令服務、吉祥物、即時動態的屬性／意圖。 | 已實作 |

**App 端控制器（位於 LavaSecApp 內）：**

- **AppViewModel** — app 端控制器（god-object）：負責 `NETunnelProviderManager` 生命週期、共享狀態持久化、provider 訊息傳遞、即時動態調和、目錄同步、備份、StoreKit 與驗證。
- **RootView** — 雙分頁 `TabView`（「防護」+「設定」），「篩選」與「活動」作為「防護」下的明細畫面進入；控管初始引導流程，並承載安全鎖／隱私遮罩覆蓋層。
- **SecurityController** — 密碼（Keychain 中加鹽的 SHA256）+ 生物辨識 + 各介面分別防護。
- **LavaLiveActivityController** — 單一即時動態的調和器，已去重並以版號控管。
- **OnboardingFlowView** — 多頁的首次執行流程（6 頁：`lava → guardIntro → features → vpn → notifications → done`）。

**LavaSecCore（平台無關的 SwiftPM 套件，`Sources/LavaSecCore/`）：**

- **FilterSnapshot / CompactFilterSnapshot** — 編譯後的篩選器 + 決策優先序；compact 形式是供通道讀取、便於 mmap 的磁碟上產物。
- **DNSQueryDispatcher** — 查詢優先序：bootstrap > pause > filter。
- **ResolverOrchestrator** — 傳輸路由、純 DNS 降級、各端點故障切換、裝置 DNS 後援。
- **DoHTransport / DoTTransport / DoQTransport** — 加密傳輸執行器。
- **FeatureLimits**（位於 `SubscriptionPolicy.swift`）— 方案上限（真相來源），透過靜態的 `.free` / `.paid` 成員。
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — 裝置防護欄運算 + 權威的合併後預算強制執行。
- **BlocklistCatalogSync / BlocklistParser** — 目錄擷取、直接從上游下載、本機解析／正規化／去重、受保護網域篩選。
- **GuardianMascotAnimation** — 7 狀態的吉祥物狀態圖（由 `Shared/SoftShieldGuardian` 渲染）。
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — 備份加密 + payload。
- **SupabaseIDTokenAuth** — 原始 URLRequest 的 `id_token` 驗證（不使用 SDK）。

### 後端 {#backend}

| 元件 | 角色 | 狀態 |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker（`api.lavasecurity.app`）：目錄讀取、admin/cron 封鎖清單同步 + 發佈、匿名錯誤回報、帳號刪除、App Store 權益鏡像、QA 探測。 | 已實作 |
| **lavasec-email Worker** | 僅接收的 Cloudflare Email Routing 轉發器，服務 `@lavasecurity.app`；拒絕未知／過大的郵件。 | 已實作 |
| **Supabase Postgres** | 帳號、`user_backups`、目錄中繼資料、僅限 service-role 的資料表；**每張 public 資料表都有 RLS**。 | 已實作 |
| **Cloudflare R2**（正式環境 R2 儲存桶，另有一個獨立的 preview 儲存桶供 staging 使用） | 目錄快照 + 輪詢同步游標。**從不**儲存第三方封鎖清單位元組；錯誤回報附件上傳路由已移除（遺留物件僅在帳號刪除時才會刪除）。 | 已實作 |
| **Cloudflare D1**（說明回饋資料庫） | 僅可附加的匿名說明文章回饋投票。 | 已實作 |

## 4. 資料流圖 {#4-data-flow-diagram}

最重要的單一特性：**加密 DNS 解析路徑（右側）從不碰觸 Lava Security 的後端（底部）。** 裝置會向 Worker 擷取目錄*中繼資料*，但清單*位元組*與實際的查詢串流則直接送往第三方。

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

## 5. 資料流 {#5-data-flows}

### A. DNS 路徑（每次查詢，全部在裝置上）— 已實作 {#a-the-dns-path-per-query-all-on-device-implemented}

這是熱路徑，也是隱私核心。它完全在 `LavaSecTunnel` 內部執行；這裡沒有任何東西會抵達 Lava 的伺服器。

1. 封包通道攔截一次 DNS 查詢（通道 DNS 伺服器 `10.255.0.1`）。
2. **`DNSQueryDispatcher`** 套用查詢優先序：**bootstrap > pause > filter**。bootstrap 優先是一條硬性不變量——解析器自身的主機名會在任何篩選之前先被解析，如此解析器永遠不會封鎖自己。
3. 若非 bootstrap 且未暫停，則該網域會對照 **`CompactFilterSnapshot`** 進行評估（透過 `Data(contentsOf:options:[.mappedIfSafe])` 零拷貝 mmap 從 App Group 載入）。決策優先序為**安全防護欄 > 本機允許清單（允許例外） > 封鎖清單 > 預設允許**；無效網域一律封鎖。
4. **已封鎖** → 通道在本機作答（不與上游接觸）。**已允許** → 該查詢交給 **`ResolverOrchestrator`**。
5. `ResolverOrchestrator` 路由到所設定的傳輸——**`DoH3` / `DoT` / `DoQ` / 純 DNS（`IP`）**——在退避閘門之後對各端點進行故障切換，當某加密方案沒有任何端點時降級為純 DNS，並在主要解析無回應且方案允許時啟用**裝置 DNS 後援**。
6. 解析器回覆會回傳給作業系統。使用者的查詢串流只會送往**使用者選擇的公開解析器**，從不送往 Lava Security。

傳輸說明（逐字慣例）：**只有在實際觀察到 h3 協商時**才會標註 `DoH3`（無斜線）——以偏好為主，從不承諾。**`DoT`** 每個端點匯集最多 4 條 NWConnection，並以閒置過期更新加上一次全新連線重試。**`DoQ`** **每次查詢都開啟一條全新的 QUIC 連線**（不重用）；4 條通道的匯集池提供的是並行性，而非交握重用——連線重用曾被建構、在裝置上測試過，隨後被**還原**（延後至 iOS-26 部署下限）。請參閱 [DNS 篩選與封鎖清單](./dns-filtering-and-blocklists.md)。

### B. 目錄擷取 + 封鎖清單載入（僅來源 URL）— 已實作 {#b-catalog-fetch-blocklist-load-source-url-only-implemented}

篩選規則如何進入裝置。Lava Security 是一個**僅來源 URL**的散布者：它只發佈上游 URL + 接受的雜湊值，且**從不儲存、鏡像、轉換或提供第三方封鎖清單位元組。**

1. 裝置向 Worker 擷取目錄**中繼資料**：`GET https://api.lavasecurity.app/v1/catalog` → 直接從 R2 提供的 JSON（`catalog/latest.json`），拆分為 `sources[]` + `guardrails[]`，每一項都帶有 `source_url` + `accepted_source_hashes`。
2. 對每個已啟用的來源，裝置**直接從 `source_url` 下載清單位元組**（即上游——HaGeZi、OISD、Block List Project 等），而**非**從 Lava Security。
3. 裝置計算 SHA256，並僅接受其校驗和位於 `accepted_source_hashes` 中的位元組；不相符時，它會回退到最後一份良好快取，或以失敗關閉處理（`checksumMismatch`）。
4. **`BlocklistParser`** 在本機進行解析／正規化／去重（auto / plain / hosts / adblock / dnsmasq 格式），然後 **`DomainRuleSet.lavaSecProtectedDomains`** 剝除受保護網域（apple.com、icloud.com、lavasecurity.com/.app、google.com、accounts.google.com、…），如此上游清單就永遠無法封鎖 Lava Security／Apple／身分提供者的網域。
5. **`FilterSnapshotPreparationService`** 合併去重後的聯集，並執行**權威的預算強制執行**（先裝置上限，再方案），然後將 `filter-snapshot.compact` 寫入 App Group。
6. `AppViewModel` 送出一則 `reload-snapshot` provider 訊息；通道重新載入。

Worker 端鏡像了這個流程：它的 admin/cron 同步會擷取每個上游，計算雜湊／數量，寫入 `raw_r2_key = null` / `normalized_r2_key = null`，並僅重新發佈中繼資料。封鎖清單目錄模型與後端同步路徑記載於 [DNS 篩選與封鎖清單](./dns-filtering-and-blocklists.md) 及 [後端與資料](./backend-and-data.md)。

**預算模型（兩層）：**
- **裝置防護欄（人人適用，從不作為付費牆）：** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3,262,236 條規則** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule`——在約 50 MiB NE 上限之下，以 32 MB 為目標。超出預算的設定會被確定性地拒絕，而不是任由通道被系統終止（jetsam）。
- **方案上限（`FeatureLimits`）：** **免費 500K 條規則／Plus 200 萬條規則**，其上限低於裝置防護欄。這取代了舊有以已啟用清單**數量**為準的上限（免費 3／付費 10）——清單數量上限已過時。

> **預設啟用的真相來源：** 出貨的免費預設為 **Block List Basic**（`OnboardingDefaults.lavaRecommendedDefaults`）。它是在裝置上，依各精選來源的 `defaultEnabled` 旗標（`BlocklistSource.recommendedDefaultSourceIDs`）推導而來，並鏡像由同一份標準目錄規格所產生的後端目錄 `default_enabled` 欄位。

### C. 備份（零知識，選擇加入）— 已實作 {#c-backup-zero-knowledge-opt-in-implemented}

可選、需帳號，也是唯一會落入後端的使用者資料——以**不透明密文**形式。

1. 使用者可選擇性地登入（僅限 Apple 或 Google；**電子郵件／密碼已捨棄**），透過在 Supabase Auth 交換的原生 `id_token`（`grant_type=id_token`，雜湊後的 nonce）。只有所產生的 Supabase 工作階段會被儲存，且僅存於裝置本機的 Keychain 中。
2. **`BackupConfigurationPayload`** 組裝一份最小化的明文（已啟用的封鎖清單 ID、允許／已封鎖網域、解析器偏好、本機記錄偏好、LavaGuard 帳本）。它**排除** `isPaid`、QA、診斷資訊與完整封鎖清單。
3. **`ZeroKnowledgeBackupEnvelope`** 以隨機 32 位元組 payload 金鑰，用 **AES-256-GCM** 將其封緘；該金鑰再透過 **PBKDF2-HMAC-SHA256（210k 次疊代）** 包裝進各個秘密的**金鑰槽**——裝置秘密槽、輔助復原槽、可選的通行密鑰槽。可選的通行密鑰槽以一個 authenticator 的 **WebAuthn PRF / `hmac-secret`** 輸出（經 HKDF 衍生）包裝；該輸出從不離開用戶端，因此通行密鑰槽是真正零知識的——沒有任何伺服器持有的值能解開它（`ZeroKnowledgeBackupEnvelope.makeWithPRF`）。
4. **`BackupSyncService`** 透過 PostgREST，將**僅密文 + 非秘密中繼資料**直接上傳到 Supabase `user_backups`，並以每位使用者的 **RLS** 加以限定範圍。（沒有 Worker 上傳路由；Worker 觸碰 `user_backups` 僅是在帳號刪除期間將其刪除。）
5. **復原：** 透過裝置秘密槽進行無縫的同裝置復原；跨裝置則透過 **8 個字的 CVCV 復原碼**（約 105 位元）結合一份伺服器持有的復原分片，以 SHA256 組合（雙因素——任一半單獨都無法解密）；或者，當封緘了通行密鑰槽時，透過用戶端的 WebAuthn PRF / `hmac-secret` 輸出（不涉及任何伺服器持有的值）。伺服器從不註冊通行密鑰、不發出 WebAuthn 挑戰，也不儲存任何復原秘密。

請參閱 [帳號與備份](./accounts-and-backup.md)。

### D. App ↔ 擴充功能控制平面 — 已實作 {#d-app-extension-control-plane-implemented}

三個行程（app、通道、widget）透過 App Group `group.com.lavasec` 協調：

- **控制 = NETunnelProviderSession provider 訊息**，而**非** Darwin 通知。`AppViewModel` 編碼一則 `LavaSecProviderMessage {kind, operationID}` 並呼叫 `session.sendProviderMessage`；通道的 `handleAppMessage` 依 kind 切換（`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`）。
- **共享檔案**承載規則／設定／健康狀態（`filter-snapshot.compact`、`app-configuration.json`、`tunnel-health.json`）；**共享 UserDefaults 儲存**（`ProtectionSessionStore` / `ProtectionPauseStore`）承載工作階段 + 暫停狀態。
- **`LavaProtectionCommandService`** 在 `flock` 檔案鎖之下執行即時動態／AppIntent 的暫停／繼續命令，並有版號去重與需驗證的拒絕機制；**重新連線會繞過它**以直接重啟通道（`startVPNTunnel`）。
- **隨選連線（Connect-On-Demand）** 只在通道*確認已連線之後*才啟用，從不在設定檔安裝時啟用——如此一個剛安裝的初始引導設定檔，就不會帶起一個無法關閉的通道。

請參閱 [iOS 用戶端](./ios-client.md)。

## 6. 信任邊界與隱私保護設計 {#6-trust-boundaries-privacy-preserving-design}

| # | 邊界 | 什麼會跨越它 | 什麼刻意不會跨越 |
|---|---|---|---|
| 1 | **裝置 ↔ 公開 DNS 解析器** | 已允許的 DNS 查詢（加密：DoH3/DoT/DoQ，或純 IP）送往使用者選擇的解析器。 | Lava Security 從不看到查詢串流；它根本不在這條路徑上。 |
| 2 | **裝置 ↔ 上游封鎖清單主機** | 裝置直接從 `source_url` 下載清單位元組。 | Lava Security 從不代理、鏡像或儲存第三方封鎖清單位元組。 |
| 3 | **裝置 ↔ lavasec-api Worker** | 目錄**中繼資料**讀取；選擇加入的匿名錯誤回報；權益鏡像；帳號刪除。 | 沒有 DNS 查詢、沒有瀏覽歷史、沒有明文設定。 |
| 4 | **裝置 ↔ Supabase** | 選擇加入的**加密備份信封**（僅密文，RLS 下的 PostgREST）；帳號資料列。 | 沒有使用者持有的秘密，伺服器無法解密備份。 |
| 5 | **App ↔ 通道擴充功能**（裝置端） | provider 訊息 + App Group 檔案／defaults。 | 在沒有可重用快照的冷啟動時，通道會以失敗**關閉**處理。 |

**隱私保護的設計原則，立基於上述：**

- **本機優先篩選。** 決策引擎與解析器在裝置上的 NE 擴充功能內執行。後端在設計上即為僅中繼資料——沒有任何資料表存放例行的 DNS 查詢或逐網域遙測。
- **防護無需帳號。** 核心防護永久免費；驗證與備份嚴格採選擇加入。
- **僅來源 URL 散布。** 將 Lava Security 與第三方清單位元組解耦（符合 GPL／智財合規 + App Review 安全性），並維持一道 CI 防護欄，強制執行「無鏡像程式碼、無 Lava Security 產物 URL、無 R2 位元組寫入」。
- **靜態下的零知識備份。** 用戶端 AES-256-GCM；伺服器持有密文 + KDF 中繼資料 + 一份復原分片，從不持有明文、復原碼或已解包的金鑰。可選的通行密鑰槽以用戶端的 WebAuthn PRF / `hmac-secret` 輸出包裝，因此它同樣是零知識的——沒有任何伺服器持有的值能解開它。
- **裝置本機秘密。** 備份解鎖材料使用 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`——不與 iCloud 同步、不在裝置備份中。
- **Service-role 隔離。** `bug_reports`、`mirror_events` 與 `qa_developers` 已從 anon／authenticated 的 PostgREST 角色撤銷；只有 Worker（service role）會觸碰它們。
- **安全永不出售。** 付費只解鎖**自訂功能**。它從不繞過不可豁免的**安全防護欄**，後者的完整性由所接受的 SHA256 來源雜湊強制執行（而非伺服器簽章）。優先序在各處皆一致：**安全防護欄 > 本機允許清單（允許例外） > 封鎖清單 > 預設允許。**

## 7. 各元件文件 {#7-per-component-docs}

> 以下是架構文件集中的同層文件。DNS 篩選引擎與封鎖清單目錄合併記載於同一份檔案中。

- [iOS 用戶端](./ios-client.md) — 目標、App Group、控制平面、防護狀態模型、初始引導、即時動態。
- [DNS 篩選與封鎖清單](./dns-filtering-and-blocklists.md) — 篩選快照、決策優先序、解析器傳輸（DoH3/DoT/DoQ）、記憶體預算、mmap；外加僅來源 URL 的目錄模型、目錄擷取、本機解析／正規化、受保護網域篩選，以及方案預算。
- [帳號與備份](./accounts-and-backup.md) — Apple/Google 驗證、零知識信封、金鑰槽、復原碼、用戶端 WebAuthn-PRF 通行密鑰復原。
- [後端與資料](./backend-and-data.md) — lavasec-api + lavasec-email Worker、Supabase 結構 + RLS、R2/D1、部署。

## 8. 狀態圖例 {#8-status-legend}

這份文件集使用同一套狀態詞彙。**lane 資料夾是權威狀態**；計畫內過時的 frontmatter 是一個文件錯誤，而非狀態。**程式碼覆蓋計畫。**

| 狀態 | 含義 | 計畫 lane | 程式碼 |
|---|---|---|---|
| **已實作** | 已出貨並在程式碼中確認 | `plans/implemented/` | 存在且已接線 |
| **進行中** | 正在積極建構；已部分落地 | `plans/inflight/`、`plans/under_review/` | 部分存在 |
| **已規劃** | 已設計，尚未建構 | `plans/backlog/` | 不存在 |
| **已捨棄** | 已否決或已還原 | `plans/dropped/`（或已還原的提交） | 不存在／已移除 |

**本頁所提及事項的狀態：**

- **已實作：** 四個 iOS 目標 + App Group；provider 訊息控制平面；具 DoH3/DoT/DoQ/IP 傳輸的裝置端 DNS 篩選；僅來源 URL 的目錄擷取 + 本機解析；篩選規則預算（免費 500K／Plus 200 萬）+ 約 326 萬條的裝置防護欄；多頁初始引導；密碼／生物辨識安全；單一去重的即時動態；零知識備份；Apple + Google 驗證；帳號刪除；權益鏡像；QA 探測；`LavaDesignSystem` token 層（`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`），包含 `LavaTier` 深度模型（Floor/Window/Workshop = `calm`/`celebratory`/`technical`）、已接線到代表性介面（例如 `SettingsView`）的 `.lavaTier(_:)` / `.lavaTierMetadata()` 修飾器，以及 `dangerRed` 與 `LavaSpacing` token——由 `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift` 鎖定。
- **進行中：** 設計系統 token 層持續向更多介面推展（`LavaTier` 深度模型與 token 層已出貨——見下——但專屬的 `LavaColorRole` 尚未存在，因此強調色仍解析為原始顏色）。
- **已規劃：** Lava Guard 彩蛋小遊戲；額外的吉祥物表情（吉祥物恰有 **7** 個狀態）；在實體裝置上完全可上線的通行密鑰復原（Associated Domains／AASA）；伺服器端 App Store JWS 重新驗證（`verification_status` 為 `client_verified_storekit`）；一個專屬的 `LavaColorRole` token，使設計系統的強調色透過語意角色解析，而非原始顏色。
- **已捨棄：** DoQ 連線重用（改為每次查詢全新連線）；電子郵件／密碼登入（僅限 Apple + Google）；GPL 原始 R2 鏡像設計（已被僅來源 URL 取代）。
