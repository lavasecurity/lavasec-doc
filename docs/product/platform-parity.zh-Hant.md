# 平台一致性 {#platform-parity}

Lava 的平台一致性系統會追蹤哪些產品承諾在 iOS、Android 以及未來的用戶端之間共享。它是功能行為的公開合約：什麼必須在各處代表相同的意義、什麼是刻意採用平台原生的做法，以及什麼尚未承諾。

一致性文件並不會取代實作計畫或測試。

- `lavasec-doc` 擁有產品與行為合約。
- 內部計畫擁有交付狀態、排序、私有風險，以及董事會同步。
- 平台儲存庫擁有用以證明行為的程式碼、fixture 與測試。

當文件與已上線的程式碼互相牴觸時，在文件更新之前以程式碼為準。當某個計畫與本頁互相牴觸時，請將本頁視為產品合約，並將該計畫視為工作佇列。

## 狀態詞彙 {#status-vocabulary}

| 狀態 | 意義 |
|---|---|
| **Shipped** | 已在該平台的生產程式碼中實作。 |
| **Partial** | 部分行為已存在，但尚未完全滿足公開合約。 |
| **Planned** | 已接受為平台合約的一部分，但尚未實作。 |
| **Deferred** | 有效的功能，但下一個平台里程碑並不需要。 |
| **Platform-native** | 相同的使用者承諾，但採用不同的 OS 專屬實作。 |
| **Not applicable** | 該平台不應存在對應的功能。 |
| **Dropped** | 先前曾考慮或建置過，後來刻意移除。 |

## 功能記錄格式 {#feature-record-format}

每個納入一致性追蹤的功能都應該有一個穩定的功能 id。請使用能在 UI 文案變動後仍然存續的 `area.capability` 名稱，例如 `filtering.guardrail-precedence` 或 `dns.encrypted-transports`。

一份完整的功能記錄需回答：

| 欄位 | 用途 |
|---|---|
| `feature_id` | 用於計畫、PR、測試與文件的穩定 id。 |
| 產品承諾 | 使用者可以依賴的事項，以平台中立的語言描述。 |
| 一致性需求 | Android 是否必須與 iOS 完全一致、依意圖一致，或刻意維持不同。 |
| 平台狀態 | iOS、Android 與未來用戶端的狀態。 |
| 落實機制 | 用以維持行為誠實的測試、fixture、原始檔，或審查檢查。 |
| 平台註記 | 必須明確說明、而非日後重新發現的 OS 專屬差異。 |

## 更新流程 {#update-workflow}

1. 當某個變更改變了產品承諾、隱私聲明、方案界線，或跨平台行為時，新增或更新功能 id。
2. 當需要進行工作時，從實作計畫連結到相同的功能 id。
3. 為必須一致的行為新增或更新平台測試或 golden fixture。
4. 當某個平台交付了該行為時，在此更新狀態並更新相關的功能或架構頁面。
5. 將僅與實作相關、私有、定價、法律風險與營運相關的內部細節保持私有；在此僅摘述公開合約。

## 目前的一致性分類帳 {#current-parity-ledger}

| 功能 id | 產品承諾 | iOS | Android | 一致性需求 | 落實機制／來源 |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava 會在裝置本機上篩選 DNS，且不會透過 Lava 伺服器代理瀏覽流量。 | Shipped | Planned | 依意圖一致；OS 通道 API 各異。 | iOS 封包通道架構；Android `VpnService` 計畫。 |
| `protection.vpn-disclosure` | 在請求 VPN 權限／設定之前，App 會說明為何 OS 將本機 DNS 篩選稱為 VPN。 | Shipped | Planned | 平台原生的文案與權限流程。 | 導覽文件；Android Play 揭露計畫。 |
| `filtering.guardrail-precedence` | 永遠啟用的安全防護欄會覆寫使用者的允許清單；付費狀態絕不會繞過安全防護欄。 | Shipped | Planned | 完全一致的行為。 | `CompactFilterSnapshotTests`；移植後的 Android `FilterSnapshotTest`。 |
| `filtering.source-url-only-catalog` | Lava 發佈的是目錄中繼資料與上游來源 URL，而非第三方封鎖清單的位元組內容。 | Shipped | Planned | 完全一致的隱私／智財模型。 | 目錄架構；GPL／僅來源 URL 的法律文件。 |
| `filtering.on-device-parsing` | 選定的清單會在裝置上擷取與解析；日常的網域歷史記錄不會上傳到 Lava。 | Shipped | Planned | 完全一致的隱私；允許原生儲存。 | `BlocklistParserTests`；移植後的 Android 解析器一致性測試。 |
| `filtering.rule-budget` | 篩選限制是依據已編譯的規則數量與裝置安全性，而非任意的清單數量。 | Shipped | Planned | 相同的使用者面向模型；平台記憶體上限可能不同。 | iOS 篩選預算測試；得知裝置限制後的 Android 預算測試。 |
| `dns.built-in-resolvers` | 使用者可以選擇內建的解析器預設組合，而不會將允許的查詢送到 Lava。 | Shipped | Planned | 相同的解析器政策；預設組合可能分階段推出。 | 解析器預設測試；移植後的 Android 解析器 DTO 測試。 |
| `dns.encrypted-transports` | 對於允許的查詢，可使用加密的上游 DNS。 | Shipped | Planned | 允許分階段一致；Android v1 可能先以 DoH 起步，再支援 DoT／DoQ。 | iOS 傳輸測試；Android 解析器測試與裝置 QA。 |
| `reports.local-only-diagnostics` | 除非使用者明確送出支援封包，否則報告與診斷會保留在本機。 | Shipped | Planned | 完全一致的隱私；UI 可以不同。 | 錯誤回報封包測試；建置後的 Android 除錯報告預覽測試。 |
| `account.optional-sign-in` | 不需帳號即可運作防護；登入為選用。 | Shipped | Deferred | 在 Android 開放帳號功能之前，需有完全一致的產品承諾。 | 帳號驗證文件；Android 導覽／設定審查。 |
| `backup.zero-knowledge-settings` | 選用的設定備份僅儲存密文；Lava 無法讀取備份內容的明文。 | Shipped | Deferred | 在 Android 提供備份之前，需有完全一致的隱私。 | 零知識備份測試；建置後的 Android 加密一致性測試。 |
| `plus.customization-boundary` | 免費防護仍然實用；Plus 解鎖進階自訂功能，且絕不改變安全防護欄的安全性。 | Shipped | Planned | 相同的產品界線；商店實作為平台原生。 | 訂閱政策測試；建置後的 Play Billing 權益測試。 |
| `design.calm-earned-depth` | 預設使用體驗保持沉穩，僅在獲得或被請求時才呈現更深入的技術或慶祝性介面。 | Partial | Planned | 透過共享 token／role 依設計意圖一致。 | 設計系統文件與可移植性基礎計畫。 |
| `platform.ambient-presence` | 當 OS 支援原生環境介面時，防護狀態可顯示於 App 之外。 | Platform-native | Planned | 意圖一致，而非介面一致。 | iOS Live Activity 文件；Android 通知／快速設定決策待定。 |

## Android 就緒度的運用 {#android-readiness-use}

在 Android 實作開始之前，本頁應與 Android 計畫及設計系統可移植性計畫並排檢視。最低限度的 Android 就緒合約為：

- 每個涉及隱私的功能都有一個功能 id；
- 完全一致的行為都有可識別的 iOS 測試或 fixture 來源；
- 平台原生的行為都有明確的 Android 立場；
- 已延後的功能都已命名，使 Android MVP 不會意外暗示它們已交付。

該項檢視屬於實作計畫或審查筆記，而本頁則維持公開、持久的合約。
