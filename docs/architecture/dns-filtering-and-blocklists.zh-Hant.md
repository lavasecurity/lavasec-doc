---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# DNS 篩選與封鎖清單

> 目標讀者：工程師。本文件說明裝置端的 DNS 管線、加密傳輸的解析器路徑、篩選決策引擎，以及僅以來源 URL 為基礎的封鎖清單目錄模型——並附上程式碼實際執行的精確數字。狀態反映程式碼確認的現實。當計畫與程式碼有出入時，**以程式碼為準**，並在內文中標出差異。

所有 DNS 篩選都發生在裝置上；Lava Security 從不把你的瀏覽流量導向自家伺服器，也從不接收你造訪的網域串流——後端只保有目錄中繼資料、每位使用者一份不透明的加密備份，以及你選擇傳送的匿名診斷資料。

Lava Security 提供的是**本機 DNS／封鎖清單篩選**，並非保證封鎖每一個惡意網域或 URL。

---

## 1. DNS 管線（Implemented） {#1-the-dns-pipeline-implemented}

篩選／解析引擎執行於 **NE／封包通道**內——即 `NEPacketTunnelProvider` 擴充功能 `LavaSecTunnel`（`com.lavasec.app.tunnel`），它只攔截 DNS。通道位址為 `10.255.0.2`（通道）與 `10.255.0.1`（DNS 伺服器）。App 程序從不看到查詢流量；它只把編譯後的成品寫入 **App Group**（`group.com.lavasec`），並透過 NETunnelProviderSession **provider messages**（而非 Darwin notifications）對通道發出訊號。

對於每一個進入的 DNS 查詢，通道在 `DNSQueryDispatcher`（`Sources/LavaSecCore/DNSQueryDispatcher.swift`）中執行固定的**查詢優先序**：

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap 優先是一條硬性不變量。** 用來解析所設定解析器*本身*主機名（DoH/DoT/DoQ 端點）的查詢，絕不能被封鎖或暫停，否則通道根本無法把加密 DNS 建立起來。dispatcher 接收 lazy closures，因此每個步驟只在抵達時才被讀取，保留短路特性（存在 bootstrap 回應時不讀取快照；bootstrap 進行中時不讀取暫停）。
- **temporary pause** 在使用者發起的暫停 TTL 仍有效時，將查詢轉發至上游。
- **filter** 將網域與編譯後的快照比對，要嘛轉發、要嘛合成一個封鎖回應。

通過篩選的查詢（動作 `.allow`）會交給解析器路徑（§3）。通道在缺乏可重用快照的冷啟動時會**失效時封閉（fail closed）**：它安裝一份失效封閉的執行期快照，封鎖所有流量，而非進行未篩選的解析。

---

## 2. 篩選引擎（Implemented） {#2-the-filtering-engine-implemented}

### 2.1 決策優先序 {#21-decision-precedence}

`FilterSnapshot.decision(forNormalizedDomain:)`（`Sources/LavaSecCore/FilterSnapshot.swift:57-71`）套用標準的安全優先序：

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| 順序 | 規則集 | 結果 | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | 封鎖 | `.threatGuardrail` |
| 2 | `allowRules` | 允許 | `.localAllowlist` |
| 3 | `blockRules` | 封鎖 | `.blocklist` |
| 4 | — | 允許 | `.defaultAllow` |

無法通過正規化的網域會被封鎖，原因為 `.invalidDomain`（fail-safe）。相同的優先序也鏡射在二進位的磁碟形式（`CompactFilterSnapshot`）。安全防護欄刻意置於本機允許清單之上：**付費永遠無法繞過不可允許的安全防護欄**，而使用者例外也無法解除對防護欄網域的封鎖。

> 注意：在目前的工作樹中，`nonAllowableThreatRules` / `guardrailSources` 為空（`DefaultCatalog.guardrailSources = []`，`BlocklistModels.swift:254`）；優先序的這個位置已接線並強制執行，但目前尚未隨附任何防護欄項目。

### 2.2 規則儲存與常駐記憶體單位 {#22-rule-storage-and-the-resident-memory-unit}

`DomainRuleSet`（`Sources/LavaSecCore/DomainRuleSet.swift`）儲存 `exactDomains` + `suffixDomains` 兩個集合。比對（`containsNormalized`）在查詢時進行一次精確查找，加上一趟父層後綴走訪（`hasSuffix` 風格）——在編譯期**沒有子網域包含關係的化簡**。一條有效的萬用字元行就是**一條規則**、一個記憶體表項目。這種「1 行 = 1 規則」的對應關係，正是讓規則數量成為誠實資源指標的原因（§4）。

### 2.3 編譯後的快照形式 {#23-compiled-snapshot-forms}

- **`FilterSnapshot`**——記憶體中編譯後的篩選器：`blockRules`、`allowRules`、`nonAllowableThreatRules`，以及解析器預設。
- **`CompactFilterSnapshot`**——通道實際讀取、適合 mmap 的二進位磁碟形式（magic `LSCFSNP1`、`fileVersion 1`）。它透過 mmap 以零複製方式載入（§4.3）。

App 會把 `filter-snapshot.json` 和 `filter-snapshot.compact` 都寫入 App Group；通道則解碼 compact 成品。一條**暖啟動重用**路徑（`FilterArtifactStore`）讓通道可重用磁碟上的 compact 成品而不必重新編譯，以一個識別指紋加上一份以原子方式寫入的 manifest 把關；當解析器傳輸、目錄覆蓋範圍或快照輸入有變動時，重用會被拒絕（隱私安全，僅以欄位名稱說明原因）。

---

## 3. 加密傳輸與解析器路徑（Implemented） {#3-encrypted-transports-the-resolver-path-implemented}

### 3.1 傳輸列舉 {#31-transport-enum}

未被封鎖的查詢會被轉發至所設定的上游解析器。`DNSResolverTransport`（`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`）有**五**個值：

| 傳輸 | 原始值 | UI 中呈現的註記 |
|---|---|---|
| Device DNS | `device-dns` | *（無——名稱本身就是傳輸）* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

內建預設為 Google、Cloudflare、Quad9、Mullvad（各有 IP / DoH / DoT 變體），再加上 Device DNS 與 Custom。自訂解析器接受純 IPv4/IPv6 伺服器、DoH URL、DoT URL（`tls://` / `dot://`）、DoQ URL（`doq://` / `quic://`），或一個 `sdns://` DNS stamp；使用者名稱／密碼與 localhost 會被拒絕。DoH/DoT/DoQ 中，DoT/DoQ 預設使用連接埠 `853`，而 DoH 則要求帶有路徑。

### 3.2 DoH / DoH3 {#32-doh-doh3}

`DoHTransport`（`Sources/LavaSecCore/DoHTransport.swift`）透過 `URLSession` 執行 DoH。每個請求都選用 HTTP/3（`request.assumesHTTP3Capable = true`，`DNSOverHTTPSRequest.swift:29`）；Apple 的載入器會原生回退至 H2/H1，因此這絕不會讓一個可連線的解析器變得無法連線。協商出的協定從 `URLSessionTaskTransactionMetrics.networkProtocolName` 讀取（ALPN：`h3`、`h2`、`http/1.1`）。

UI 只在**實際觀察到 h3 協商時**才標註 **`DoH3`（無斜線）**——例如「Quad9 (DoH3)」（`DoHHTTPVersion.dohAnnotation`）；否則顯示 `DoH`。DoH3 是優先採用，但從不保證：這個標籤是觀察性的、以解析器為範疇，且從不持久化（「已確認 DoH3」跨重啟沿用的行為已被回退）。請求以 POST 傳送 `application/dns-message`；回應會經過 content-type 與長度驗證，並在寫回前還原交易 ID。

### 3.3 DoT {#33-dot}

`DoTTransport`（`Sources/LavaSecCore/DoTTransport.swift`）使用集區化的 `NWConnection`，**每個端點最多 4 條連線**（`maxConnectionsPerEndpoint = 4`），以輪詢方式運作，使並行查詢避免隊頭阻塞（head-of-line blocking）。它帶有**閒置陳舊**處理：像 Cloudflare 這樣的供應商會在伺服器端關閉閒置的 DoT 連線（約 10 秒）而不顯現狀態變更，因此閒置超過 **8 秒**（`reusedConnectionMaxIdleInterval = 8`）的重用連線會在傳送前先重新整理，而重用連線發生逾時則會獲得**恰好一次的全新連線重試**。

### 3.4 DoQ——每個查詢一條全新連線 {#34-doq-fresh-connection-per-query}

`DoQTransport`（`Sources/LavaSecCore/DoQTransport.swift`）為每個端點維持一個上限為 **4 條通道（lane）**的有界集區，但**每個查詢都開啟一條全新的 QUIC 連線**——即每個查詢一次完整握手。這個 4 通道集區提供的是**並行能力，而非握手重用**。

**DoQ 連線重用狀態（Dropped／延後）。** 重用曾在裝置上經過檢視與基準測試（35 個查詢中有 34 次全新握手 ≈ 無重用），接著實作為一條以 iOS 26 為門檻的多串流 `NWConnectionGroup` 路徑，並在裝置上對 AdGuard DoQ 測試，最終因**淨負面而回退**（對真實伺服器出現串流失敗 + 回退錯誤）。RFC 9250 將每個查詢對應到它自己的 QUIC 串流，因此重用需要 `NWConnectionGroup`/`openStream`，而這**僅限 iOS 26.0+**；目前的部署底線是 **iOS 17**。重用會延後，直到底線提升至 iOS 26。在不支援的裝置上，自訂 DoQ 會被拒絕（「此裝置不支援 DNS over QUIC」）。

### 3.5 解析策略 {#35-resolution-policy}

`ResolverOrchestrator`（`Sources/LavaSecCore/ResolverOrchestrator.swift`）掌管上游策略：

1. 依所設定的傳輸進行**傳輸路由**。
2. 當加密計畫沒有端點時，**降級為 plain DNS**。
3. 帶有退避閘門的**每端點容錯切換**——處於退避中的端點絕不接觸線路（結果為 `backed-off`）。
4. 當主要端點未回傳回應*且*計畫允許時，進行**裝置 DNS 後援**（計畫屬性為 `shouldFallbackToDeviceDNS`，由 `fallbackToDeviceDNS` 設定欄位推導而來）；結果會被重新註記為裝置傳輸。線路執行被注入於執行器之後，使策略可單元測試；退避狀態則維持在純策略之外。

---

## 4. 篩選規則預算、NE 上限與 mmap {#4-filter-rules-budget-ne-ceiling-and-mmap}

實際出貨的層級指標是**篩選規則預算**：使用者可啟用的編譯後網域**規則**總數。它取代了舊的「已啟用清單**數量**上限」（免費 3／付費 10），那是個不誠實的代理指標——一份清單可以是 1K 條或 1M 條規則。這裡有**兩層**：一層人人共享的裝置防護欄，以及位於其下、依層級而定的營利限制。

### 4.1 層級限制（Implemented） {#41-tier-limits-implemented}

`FeatureLimits`（`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`）是真相來源：

| 層級 | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | 自訂封鎖清單／DNS |
|---|---|---|---|---|
| **免費方案** | **500,000** | 25 | 25 | 否 |
| **Plus**（`.paid` / `.plus`） | **2,000,000** | 1,000 | 1,000 | 是 |

層級限制是一條營利界線，**絕非對裝置防護欄的付費牆**。**Lava Security Plus** 只解鎖客製化——絕不解鎖基線安全，也絕不解鎖安全防護欄。自訂（付費）封鎖清單直接從使用者裝置擷取、在本機解析與快取，且絕不代理至 Lava Security 伺服器。

### 4.2 裝置記憶體防護欄 + NE 上限（Implemented） {#42-device-memory-guardrail-ne-ceiling-implemented}

封包通道受制於 iOS 的**每擴充功能約 50 MiB 記憶體上限**（自 iOS 15 起，這是針對封包通道的每擴充功能類型 OS 設計限制，並非隨 RAM 縮放；它存在於每個裝置型號的 `com.apple.jetsamproperties.{Model}.plist`，在較舊裝置上可能更低）。超出便會觸發 jetsam。這個上限沒有 API，因此預算在懸崖之下保留餘裕。

`FilterSnapshotMemoryBudget`（`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`）進行計算，以篩選規則（block + allow + guardrail）為單位：

| 常數 | 值 |
|---|---|
| `baselineMegabytes` | 4.0 MB（固定的程序開銷，實測約 3.5 MB，向上取整） |
| `estimatedBytesPerRule` | 每條規則 9.0 B dirty resident（實測約 8.5 B，向上取整） |
| `maxResidentMegabytes` | 32.0 MB（目標上限，在觀察到的約 40–46 MB jetsam 懸崖之下保留約 10 MB 餘裕） |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 條規則** |

這條**約 3.26M 條規則的裝置防護欄**是*每一位*使用者的硬性安全底線，凌駕於任何訂閱層級之上，且**絕非付費牆**。錨點量測（裝置「chimmy」，2026-06-13）：**789,831 條規則 → 9.9 MB `phys_footprint`**，即 ≈ 基線 + 每規則成本。

### 4.3 mmap 策略（Implemented） {#43-mmap-strategy-implemented}

compact 快照以 `Data(contentsOf:options:[.mappedIfSafe])`（`LavaSecTunnel/PacketTunnelProvider.swift:4431`、`:4665`）載入，而 `CompactBinaryReader` 回傳零複製的切片。數 MB 的網域文字 blob 維持**檔案後援／clean**，並被排除在受 jetsam 計入的 `phys_footprint` 之外；只有解碼後的 `[Entry]` 表會耗用常駐記憶體（磁碟上每規則約 6 B，dirty resident 約 8.5 B）。這提升了裝置端的網域上限：常駐成本是 entry 表，而非整份成品。

### 4.4 兩層強制執行（Implemented） {#44-two-layer-enforcement-implemented}

- **權威性（編譯期）。** `FilterSnapshotPreparationService`（`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`）對所有已啟用清單的**去重後聯集**強制執行預算。裝置防護欄會被**最先**檢查（硬性底線）；層級限制則約束於其下。超出預算的設定會被確定性地拒絕——`exceedsDeviceMemoryBudget` 或 `exceedsTierFilterRuleLimit`——而非任由通道發生 jetsam。錯誤會點名貢獻最大的兩份清單，使修正一目了然。
- **建議性（選取期 UI）。** `FilterRuleBudget`（`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`）以每份清單的**加總**驅動選取量表，並帶有 **1.10 的軟上限餘裕**，以補償約 7–10% 的跨清單重複計數（每份清單的加總會高估去重後的聯集）。

### 4.5 解析器（Implemented） {#45-the-parser-implemented}

`BlocklistParser`（`Sources/LavaSecCore/BlocklistParser.swift`）逐字計數規則：它丟棄註解／空白／無效行，進行正規化，於清單內去除重複的精確字串（透過一個 `Set`），並對每份清單設上限 **`maxRules = 1,000,000`**（預設），單行最大長度 4,096 字元。支援的格式：`auto`、`plainDomains`、`hosts`、`adblock`、`dnsmasq`（`auto` 依序嘗試 hosts → dnsmasq → adblock → plain）。一條有效行 = 一條規則 = 記憶體單位。

> **多主機的 `hosts` 行（解析器規則版本 2）。** 一條把單一 IP 對映到多個主機的 `hosts` 行（`0.0.0.0 a.com b.com c.com`）現在會把**每一個**主機都發出成它自己的規則，而不只是第一個；`maxRules` 是**逐規則**強制執行（而非逐行），因此接近上限的多主機行不會超量。由於相同的上游位元組現在可能產出更多規則，解析器的規則版本被自 **1 → 2** 提升，使在舊有「只取第一個主機」行為下解析的過時 `RuleSetCache` 項目失效。

### 4.6 下載與解碼的強健性（Implemented） {#46-download--decode-robustness-implemented}

通道與目錄同步都在 NE 記憶體預算內執行，因此清單擷取已針對惡意或畸形輸入加以強化：

- **串流式下載。** `defaultDataFetcher` 透過 `URLSession.download` 把清單位元組下載到一個暫存檔（有界的尖峰記憶體），並在下載後進行大小檢查（`maximumBlocklistBytes`），而非把整個內文緩衝在 RAM 中；過大的內文會引發 `BlocklistDownloadSizeLimitExceeded`。
- **目錄中繼資料上限（8 MB）。** `BlocklistCatalogRepository.maximumCatalogBytes` 會在解碼前拒絕過大的遠端目錄，因此惡意／MITM 主機無法在擴充功能中強迫一次 OOM 的 JSON 解碼。
- **寬鬆的 UTF-8 解碼。** 單一個無效的 UTF-8 位元組不再會拒絕整份清單（在失敗即封閉下這會封鎖所有 DNS）；無效位元組會變成 U+FFFD，只有出問題的那一行會在逐行驗證時失敗並被丟棄。
- **具名的自訂封鎖清單錯誤。** 失敗的自訂清單現在會浮現 `customBlocklistUnavailable(displayName:reason:)`——「無法載入自訂封鎖清單『<name>』。<why>」——而非原始的 `URLError`；取消會被傳播為取消，而非下載失敗。

---

## 5. 封鎖清單目錄與預設來源 {#5-blocklist-catalog-default-sources}

### 5.1 目錄模型（Implemented） {#51-catalog-model-implemented}

**封鎖清單目錄**是已發佈、可用來源的清單。**lavasec-api Worker** 從 R2 bucket 在 `GET /v1/catalog`（以及 `/v1/catalog/:version`）提供 JSON 中繼資料；裝置則直接從每個上游 `source_url` 擷取實際的清單**位元組**。iOS 的目錄端點為 `https://api.lavasecurity.app/v1/catalog`（`BlocklistCatalogSync.swift:4-15`）。

在裝置上，`BlocklistCatalogSynchronizer`（`BlocklistCatalogSync.swift`）：

1. 直接從 `source.sourceURL` 擷取清單位元組，並強制執行大小上限。
2. 計算 SHA-256，僅在校驗碼存在於目錄的 `accepted_source_hashes` 中時才接受該位元組。
3. 不相符時，回退至最後一份良好的本機快取，或**失效封閉**（`checksumMismatch`）——除非該來源明確允許直接的上游輪替。
4. 在本機解析／正規化／去重。
5. 將每一份解析後的規則集通過 `DomainRuleSet.lavaSecProtectedDomains`（`AppConfiguration.swift:262-276`）篩選，使上游清單永遠無法封鎖 Lava Security／Apple／身分提供者的網域。

**受保護網域集**（在啟用前被濾除）：`apple.com`、`icloud.com`、`mzstatic.com`、`itunes.apple.com`、`apps.apple.com`、`lavasecurity.com`、`lavasecurity.app`、`api.lavasecurity.app`、`lavasec.app`、`lavasec.example`、`accounts.google.com`、`google.com`（皆以後綴比對）。Worker 在計算中繼資料時套用等價的 `PROTECTED_SUFFIXES` 篩選；裝置則無論如何都會重新驗證。

### 5.2 精選來源（Implemented） {#52-curated-sources-implemented}

`DefaultCatalog.curatedSources` 由標準的 [封鎖清單目錄](../legal/blocklist-catalog.md) 產生，目前涵蓋六大類別共 **33** 個來源：Security & Threat Intel、Ads & Trackers、Social Media、Adult Content、Gambling，以及 Piracy & Torrent。來源家族包括 The Block List Project、Phishing.Database、HaGeZi、OISD、StevenBlack、AdGuard 與 1Hosts。

`guardrailSources` 為空。GPL 來源（HaGeZi、OISD、AdGuard）在目錄中可見，但**選擇加入／預設關閉**；Worker 將上線時的同步／發佈限制為 `source_url_only` 加上已核准的 GPL 前綴（`hagezi-`、`oisd-`、`adguard-`）。

### 5.3 免費使用者的預設啟用清單（Implemented） {#53-default-enabled-lists-for-free-users-implemented}

實際的免費預設設定是 `OnboardingDefaults.lavaRecommendedDefaults`，它啟用 **Block List Basic**——一份廣泛、採寬鬆授權的綜合清單（廣告 + 追蹤 + 惡意軟體 + 釣魚／詐騙）——搭配 device-DNS 解析器預設（`resolverPresetID = DNSResolverPreset.device.id`）並開啟裝置 DNS 後援。這取代了先前的 Block List Project Phishing + Scam 組合：Basic 的綜合涵蓋範圍已將兩者納入，且兩者仍維持為可選擇加入的清單。

該免費預設是由 `defaultEnabled` **產生**的，並非硬編碼。**Block List Basic** 設定了 `defaultEnabled: true`，而 `DefaultCatalog.recommendedDefaultSourceIDs` 則由 `curatedSources.filter(\.defaultEnabled)` 推導而來。原始碼註解稱 `defaultEnabled` 為「全新安裝預設的單一真相來源」，鏡射後端目錄的 `default_enabled` 欄位。經由 `recommendedDefaultSourceIDs` 流入 `OnboardingDefaults`，`defaultEnabled` 是實際運作的機制——翻動某個來源上的這個旗標即可改變預設。

> **預設的真相來源（以程式碼為準）。** 全新安裝的預設是 **Block List Basic**，由各來源上的 `defaultEnabled: true` 旗標啟用；iOS 的 `BlocklistSource.defaultEnabled` 旗標是權威的實際運作機制。後端目錄的 `default_enabled` 欄位由同一份標準目錄規格產生，因此所提供的 `/v1/catalog` 中繼資料與用戶端相符。真正的閘門是 500K/2M 的篩選規則預算，而非清單數量。

### 5.4 僅來源 URL 的 GPL 散布模型（Implemented） {#54-source-url-only-gpl-distribution-model-implemented}

**僅來源 URL（Source-url-only）**是 GPL／智財合規的散布模型：Lava Security 只發佈上游 URL + 接受的雜湊；裝置自行擷取並解析清單。Lava Security **從不**儲存、鏡像、轉換或提供第三方封鎖清單的位元組。這**取代了已被廢棄的 R2 鏡像設計**（原本的「raw R2 mirror」計畫已於 2026-05-25 回退）。

在 Worker 端，`syncOneBlocklist` 擷取每個上游來源並進行正規化 + 雜湊（計算 `source_hash`、`normalized_hash`、`entry_count`），但寫入 `raw_r2_key = null` / `normalized_r2_key = null`——只有目錄 JSON 中繼資料會抵達 R2。`check-gpl-blocklist-distribution.sh` 是強制執行整套模型的 CI 防護：無鏡像／轉換程式碼、無 Lava Security 成品／下載 URL、無 GPL 來源預設啟用、Worker 不寫入清單位元組到 R2、無「Lava 自託管鏡像」文案、無內附的 GPL `.txt`/`.json`，且遷移檔 + 法務文件中必須有 `source_url_only`。

> **授權附註：** 第一方 Lava Security 程式碼以 **AGPL-3.0** 出貨（`LICENSE` 檔案為 GNU AGPL v3，與 README 徽章相符）。第三方封鎖清單（HaGeZi、OISD）依其各自的上游授權仍為 **GPL-3.0**——僅來源 URL 模型存在的目的，正是讓 Lava Security 能使用它們，而從不重新散布受 GPL 授權的位元組。此處的 GPL-3.0 是上游清單的屬性，而非 Lava Security app 的屬性。

---

## 6. 狀態摘要 {#6-status-summary}

| 領域 | 狀態 |
|---|---|
| DNS 查詢優先序（bootstrap > pause > filter） | Implemented |
| 篩選決策優先序（guardrail > allowlist > blocklist > default-allow） | Implemented |
| 安全防護欄優先序位置（已接線；目前尚無項目） | Implemented |
| DoH / DoH3（觀察性 h3 標籤） | Implemented |
| DoT（每端點 4 連線集區、8 秒閒置重新整理、一次全新重試） | Implemented |
| DoQ（每個查詢一條全新連線、4 通道並行） | Implemented |
| DoQ 連線重用 | Dropped／延後至 iOS 26 底線 |
| 解析器降級 + 每端點容錯切換 + 裝置 DNS 後援 | Implemented |
| 篩選規則預算（免費 500K／Plus 2M） | Implemented |
| 約 3.26M 條規則的裝置防護欄（50 MiB NE 上限下的 32 MB 目標） | Implemented |
| compact 快照的零複製 mmap | Implemented |
| 僅來源 URL 目錄 + 直接上游擷取 + 雜湊驗證 | Implemented |
| 受保護網域篩選 | Implemented |
| 免費預設 = Block List Basic | Implemented（產生的目錄與 iOS／後端投影一致） |
| 第一方 Lava Security 程式碼授權 | AGPL-3.0（`LICENSE`）；第三方清單於上游仍為 GPL-3.0 |

---

## 另見 {#see-also}

- [`../product/overview.md`](../product/overview.md)——產品一句話介紹、隱私承諾、分頁。
- 層級與營利（內部參考）——Lava Security Plus 與作為層級指標的篩選規則預算。
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md)——僅來源 URL 的合規決策。
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md)——上游封鎖清單／解析器的授權與標註。
