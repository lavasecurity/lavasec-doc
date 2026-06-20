---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 設計系統 {#design-system}

> **對象：** 在 Lava Security iOS 應用上工作的設計與工程團隊。
> **權威性：** 當本文件與計畫不一致時，**以程式碼為準** — 分歧會在行內標註。狀態反映程式碼確認的現實，而非計畫的願景。狀態圖例：**Implemented**（已上線並在程式碼中確認）、**In progress**（部分落地）、**Planned**（已設計，尚未建構）、**Dropped**（已駁回或還原）。

本文件涵蓋設計理念、LavaTier 深度詞彙、Guardian 吉祥物、文案與命名慣例、上手 UX，以及國際化。關於這些介面背後的架構管線（targets、VPN 生命週期、Guardian／防護狀態模型的接線），請參閱 [iOS 用戶端](../architecture/ios-client.md)；關於產品定位，請參閱 [產品概覽](../product/overview.md)。

---

## 1. 理念：平靜核心，深度需經爭取 {#1-philosophy-calm-core-earned-depth}

Lava 的對象是非技術背景的日常使用者 — 家長、長者 — 而設計正是由此衍生。日常介面對每個人都平靜地「就是能用」；額外的細節、樂趣與控制只在使用者主動尋找時才會（**經爭取**）顯露。沒有任何嘮叨、沒有任何驚擾，技術機制在被尋找之前都保持隱形。

這套 **「平靜核心，深度需經爭取」** 模型化解為三種產品深度：

- **Calm（平靜）** — 預設的、就是能用的防護，是每個人最先看到的。
- **Celebratory（慶祝）** — 可選擇開啟的覺察與樂趣（連續記錄、解鎖、成功時刻）。從不嘮叨。
- **Technical（技術）** — DNS、診斷與統計數據。在使用者主動尋找之前都保持隱形。

兩條橫貫各處的調色盤／語氣規則支撐著這份平靜姿態：

- **紅色＝僅限危險。** 紅色專門保留給危險與錯誤；平靜的調色盤是綠色／橘色。這讓紅色作為真正的警報訊號得以保持可信。危險紅以 `LavaStyle.dangerRed` 進行 token 化，並將 `LavaStyle.errorText` 設為其別名（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86），由各 view 中的錯誤文字所取用。防護色調是透過語意化的 `ProtectionTintRole` 角色表（lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7）解析，而非直接使用 `.green`／`.orange`。仍有少數直接使用 `.red` 的呼叫點確實存留（例如 lavasec-ios: LavaSecApp/SettingsView.swift:697、LavaSecApp/SecurityController.swift:600、LavaSecApp/FiltersView.swift）— 將這些遷移到 `LavaStyle.dangerRed` 是剩下的清理工作。
- **不使用充滿恐懼的安全用語。** 文案是平實、平靜且實用的。請參閱 [§4 文案與命名](#4-copy-naming)。

### 今日已存在的 token 化層 **(Implemented)** {#the-tokenized-layer-that-exists-today-implemented}

設計系統是一個真實的、token 化的 SwiftUI 層，與 `LavaTier` 深度詞彙（§2）並存：

- **`LavaStyle`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5）— 自適應色彩的單一事實來源：約 18 種語意色彩（`safeGreen`、`safeControlGreen`、`softGreen`、`lavaOrange`、`cream`、`ink`、`cardBackground`、`panelBackground`、`guardianSleepGray`、…），每種都由單一的 `adaptiveColor(light:dark:)` 工廠產生，因此淺色／深色是一起定義的。危險紅在此進行 token 化為 `dangerRed`／`errorText`（第 81／86 行）。
- **`LavaSurface`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101）— 卡片／面板／選取介面角色與圓角半徑：`cardCornerRadius` 20、`compactCornerRadius` 16、`selectionCornerRadius` 12。
- **`LavaSpacing`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183）— 間距尺度：`xs`／`sm`／`md`／`lg`／`xl` 外加 `screenHorizontal`／`screenTop`／`screenBottom`。
- **`LavaActionRole`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift，v1.0）— 一個語意化的動作角色 enum（`.cancel`、`.close`、`.confirm`、`.destructive`），對映到系統的 `ButtonRole`。`NativeToolbarIconButton` 新增了一個 `role:` 參數並被廣泛採用，因此工具列字符會在幾乎每一張表單／工具列上接收原生的角色樣式。

剩下的殘餘缺口是少數尚未遷移到 `LavaStyle.dangerRed` 的直接 `.red` 呼叫點（見 §1）。

> **元件汰換（v1.0）。** `LavaTabOverviewCard` 已被移除；篩選與活動的標題區塊現在共用 `LavaInfoCard` + `LavaOverviewMetricBlock`，因此它們在大小與位置上對齊一致。隨著篩選／活動改版一併登場的新共用元件有：`FiltersFlowDiagram`（「Phone → Lava → Internet」圖）、`ActivityFlowBar`／`ActivityFlowStatRow`（請求流程摘要）、`NetworkActivityPrivacyInfoPanel`，以及 `LavaGuardLookPickerSheet`（底部表單的 Guard 選擇器）。匯入／分享流程則以原生的 `importFlowToolbar` 取代了它們自訂的內容內標頭。

---

## 2. LavaTier — Floor / Window / Workshop **(Implemented)** {#2-lavatier-floor-window-workshop-implemented}

`LavaTier` 是輕量的深度詞彙，將「平靜核心，深度需經爭取」直接編碼進 token 層。它是一套詞彙加上少數 token 預設值 — 並非完整的重新主題化 — 並以 enum 形式上線於 lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227，接線到具代表性的介面，而非改造每一個 view。

| 層級 | 深度 | 含義 |
|---|---|---|
| **Floor** | calm | 給每個人的就是能用的防護 — 預設介面。 |
| **Window** | celebratory | 可選擇開啟的覺察與樂趣：連續記錄、解鎖、成功時刻。從不嘮叨。 |
| **Workshop** | technical | DNS、Nerd Stats、診斷。在被尋找之前都保持隱形。 |

`LavaTier` 是一個 `calm`／`celebratory`／`technical` enum，攜帶 token 預設值：

- 一個 **強調色**（`accent`），
- `allowsDelightMotion` — 僅在 celebratory／Window 時為真，
- `usesMonospacedMetadata` — 僅在 technical／Workshop 時為真，

透過一個 `EnvironmentKey` 加上 `.lavaTier(_:)` 修飾器與 `.lavaTierMetadata()` 修飾器（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263）公開。它接線到具代表性的介面 — 例如 lavasec-ios: LavaSecApp/SettingsView.swift 中的 `.lavaTier(.technical)` 與 `.lavaTier(.celebratory)` — 而非每一個 view。這種刻意的範圍劃定讓三種產品深度在程式碼中保持清晰可讀，並可移植到未來的 Android 消費端而不必重新推導意圖。

> **附註（強調色 token 化為 Planned，Phase 3）：** `LavaColorRole` 尚未建立，因此 `LavaTier.accent` 仍解析為原始的 `LavaStyle` 色彩（LavaTokens.swift:~230）。請將強調色 token 化視為一個尚未閉合的環節，而非已完成的介面。

---

## 3. Soft Shield Guardian 吉祥物 **(Implemented)** {#3-the-soft-shield-guardian-mascot-implemented}

**Soft Shield Guardian** 是 Lava 的吉祥物 — 一個帶有簡單、會變形臉孔的圓潤盾牌 — 它在防護分頁、Live Activity、Dynamic Island 與上手流程中以視覺方式表達防護狀態。它是平靜語氣最顯眼的載體。

狀態圖是平台無關的，存在於 `LavaSecCore`（lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift）；SwiftUI 渲染器是 lavasec-ios: Shared/SoftShieldGuardian.swift。

### 3.1 7 種表情狀態 {#31-the-7-expression-states}

吉祥物有**恰好 7 種**表情狀態，由一個允許轉移的狀態圖管轄（`GuardianMascotState.allowedNextStates`，由 lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift 鎖定）：

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

值得知道的圖約束：`sleeping` 的唯一出口是 `waking`，而 `grateful` 只會返回 `awake`。`awake ↔ grateful` 轉移有專屬的插值影格 — 這是整個系統唯一的一處 **delight motion（樂趣動態）**（Window 層級）。

> **`retrying` 與 `concerned` — 最重要的語氣區別。** 兩者都表示「並非完全健康」，但它們讀起來非常不同，且絕不可混為一談：
> - **`retrying`** 是*不擔憂、自我修復*的臉：放鬆（約 0.80）的眼皮、平視的雙眼、平直的嘴，且**沒有擔憂的傾斜**。動態由**狀態徽章承載，而非臉孔** — 短暫的自我復原絕不應驚擾使用者。（lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249）
> - **`concerned`** 是*溫和、尋求協助*的擔憂：抬起的內側眉毛（`concernAmount` 1、`mouthCurve` -0.22），讀起來像是「我可能需要幫個忙」，**絕不是嚴厲的瞪視**。真正的問題應該邀請協助，而非責備。（lavasec-ios: Shared/SoftShieldGuardian.swift:297）

### 3.2 連線狀態 → 表情對應（6 → 4） {#32-connectivity-expression-mapping-6-4}

防護健康度在 `LavaSecCore` 中以 **6 種連線嚴重度** + 2 種動作評估（lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift）：

- **嚴重度：** `healthy`、`recovering`、`usingDeviceDNSFallback`、`dnsSlow`、`networkUnavailable`、`needsReconnect`
- **動作：** `turnOff`、`reconnect`

防護分頁將這 6 種嚴重度收攏到 **4 張臉**（`guardianState`，於 lavasec-ios: LavaSecApp/GuardView.swift:122）。臉孔刻意成為一個比狀態徽章更*粗略、更平靜*的訊號 — 徽章承載細節，臉孔保持簡單：

| 條件 | 吉祥物狀態 |
|---|---|
| 暫時已暫停 | `paused` |
| 已連線 + `healthy`／`usingDeviceDNSFallback` | `awake` |
| 已連線 + `recovering`／`networkUnavailable` | `retrying` |
| 已連線 + `dnsSlow`／`needsReconnect` | `concerned` |
| `connecting`／`reasserting` | `waking` |
| 其他情況 | `sleeping` |

> **色調調和。** 防護色調的色彩粒度與這套表情切分保持調和，使色調與臉孔永不相互矛盾。表情對應與語意化的 `ProtectionTintRole` 角色表今日皆已上線（lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7，由 `AppViewModel.protectionTintRole` 取用）。僅剩會將角色對應到完全 token 化色彩的 `LavaColorRole` 色彩角色 token 化仍為 **Planned**（DS 計畫的 Phase 3）。

### 3.3 外觀（looks）**(Implemented)** {#33-skins-looks-implemented}

吉祥物隨附 **7 種可選的盾牌「外觀」**，以 `GuardianShieldStyle` 持久化（lavasec-ios: Shared/LavaActivityAttributes.swift:5）。每一種都有自己的配色與一個配對的 Dynamic Island 字符顏色：

`original`、`fireOpal`（原始值 `emberObsidian`）、`purpleObsidian`、`obsidian`、`cherryQuartz`（原始值 `strawberryObsidian`）、`emerald`、`kiwiCreme`。

那兩個遺留的原始值是刻意的 — 不要「修正」它們；那會破壞已持久化的使用者選擇。

### 3.4 隱私遮蔽 **(Implemented)** {#34-privacy-redaction-implemented}

Guardian 尊重隱私遮蔽：當介面處於隱私遮蔽狀態時，表情可被遮罩，而**盾牌本身保持可見**（`maskExpressionWhenPrivacyRedacted`／`keepsShieldVisibleWhenRedacted`，lavasec-ios: Shared/SoftShieldGuardian.swift:11）。防護存在感令人安心；隱藏的部分是具體的情緒狀態。

### 3.5 不在此程式樹中 **(Planned)** {#35-not-in-this-tree-planned}

一個防護彩蛋小遊戲（點一下＝感激動畫；長按 10 秒＝抓壞網域遊戲）屬於 **P3／待辦清單**。它會新增在某個功能分支上看到的額外吉祥物表情（`confused`／`dazed`／`inZone`／`powerSurge`）— 這些**不在**應用 target 中。依照權威事實，吉祥物恰好有 **7** 種狀態；不要將遊戲表情記載為已上線。

---

## 4. 文案與命名 {#4-copy-naming}

### 4.1 嗓音與語氣 {#41-voice-tone}

平實、平靜、實用。避免充滿恐懼的安全用語。對範圍誠實：Lava 是 **本機 DNS／封鎖清單篩選**，並非保證每一個惡意網域或 URL 都會被封鎖，而且防護**絕不**被描述為在上手流程完成的那一刻自動開啟 — **防護分頁對於目前防護是否生效具有權威性**。

### 4.2 DNS 傳輸標籤 {#42-dns-transport-labels}

傳輸註記遵循一套嚴格的精簡慣例（lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 與 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270，由 `DNSResolverPresetTests.swift` 鎖定）：

| 傳輸 | 標籤 | 備註 |
|---|---|---|
| DNS-over-HTTPS | `DoH` | 基於 URLSession。 |
| DNS-over-HTTP/3 | **`DoH3`（無斜線）** | 例如「Quad9 (DoH3)」。**僅在實際觀察到 h3 協商時**才註記 — 偏好但從不承諾；否則回退到 `DoH`。 |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| 純 DNS | `IP` | |
| 裝置解析器 | *（無註記）* | |

此處最常被破壞的單一規則是 **無斜線的 `DoH3`** — 寫成 `DoH3`，絕不寫成 `DoH/3` 或 `DoH3 (h3)`，也絕不臆測性地套用。這些傳輸標籤由 `DoHTransport`／`DNSResolverPreset` 發出；在每個語系中保持原樣，但請注意它們*不是*詞彙表的「不翻譯」項目（見 §4.3）。

### 4.3 不翻譯詞彙 {#43-do-not-translate-terms}

品牌與協定詞彙在**所有**語系中以原樣固定。本地化詞彙表的「不翻譯」清單是權威，它固定了：**Lava Security、Lava Security LLC、lavasecurity.app、support@lavasecurity.app、legal@lavasecurity.app、DNS、VPN、DoH、TCP、Apple、Google、Cloudflare、Quad9、The Block List Project、Phishing.Database、HaGeZi、OISD。**

在這些 DNS 傳輸中，只有 **DoH** 是詞彙表的「不翻譯」項目；`DoH3`、`DoT` 與 `DoQ` 是傳輸標籤（見 §4.2），而非詞彙表詞彙。它們仍然以原樣書寫，但不要引用詞彙表作為其來源。

### 4.4 安全定位 {#44-safety-framing}

付款絕不繞過經過雜湊驗證、不可放行的 **安全防護欄**。一致地陳述優先順序：**安全防護欄 > 本機允許清單（允許例外）> 封鎖清單 > 預設放行。**

---

## 5. 上手 UX **(Implemented)** {#5-onboarding-ux-implemented}

首次執行的上手流程是一個多頁流程 — **6 個頁面**（`OnboardingPage`：`lava → guardIntro → features → vpn → notifications → done`）— 實作於 lavasec-ios: LavaSecApp/OnboardingFlowView.swift。它重用 `SoftShieldGuardian` 來呈現守護者現身的時刻。

這 6 個頁面：

1. **網際網路就是熔岩**（`lava`）— 危險以隱喻呈現；主要動作為「認識 Lava」。
2. **Lava 在此守護**（`guardIntro`）— 守護者現身的時刻。
3. **功能交接**（`features`）— Lava 做些什麼；「設定防護」。
4. **安裝 Lava 的本機 VPN**（`vpn`）— 說明為什麼 iOS 對一個僅限 DNS 的封包通道稱之為「VPN」。
5. **啟用通知**（`notifications`）— 可選擇開啟的提示，在恰當的步驟呈現而非一開始就出現。
6. **設定完成**（`done`）—「開啟防護」，並可進行額外的選擇性設定。

烘焙進此流程的設計決策：

- **「使用預設」是主要動作，「自訂」是次要動作。** 為非技術背景使用者提供無摩擦的預設路徑；控制是經爭取而來，而非強加。
- **危險以隱喻呈現，而非恐懼**（「網際網路就是熔岩」），與平靜的語氣一致。
- **流程會說明為什麼 iOS 顯示「VPN」** — 封包通道是系統層級篩選 DNS 的唯一方式；它並非流量路由。
- **絕不宣稱防護在完成時自動開啟** — 防護分頁保持權威。
- 僅有箭頭的返回鍵，置於共用的步驟頁面版面上。

該流程安裝的首次執行預設值：**裝置 DNS** 解析器（`DNSResolverPreset.device`）、**裝置 DNS 後援開啟**、記錄開啟（計數 + 歷史記錄 + 活動），以及「不建立帳號繼續」。

> **預設封鎖清單分歧（以程式碼為準）。** 上手計畫文案將 HaGeZi Multi Light 列為預設封鎖清單，但已上線的程式碼預設是 **Block List Project Phishing + Scam**（`AppConfiguration.lavaRecommendedDefaults`，定義於 lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift）。真正的方案閘門是 **filter-rules budget（Free 500K／Plus 2M）**，*而非*清單數量。已於內部追蹤。關於方案模型與建議的預設配置，請參閱 [功能目錄](../product/features.md)。

---

## 6. 國際化 **(In progress)** {#6-internationalization-in-progress}

Lava 本地化為 **6 個語系**：**en**（來源）+ **ja、zh-Hant、zh-Hans、de、fr**，透過 Xcode string catalogs。

- **本地化接縫是 `.lavaLocalized`**（`String.lavaLocalized`／`.lavaLocalizedFormat`，由 `LavaStrings.localized` → `NSLocalizedString` 並具英文回退所支撐；lavasec-ios: LavaSecApp/LavaStrings.swift）。**所有元件文案**都必須經由它 — view 中不得有裸字串字面值。
- **zh-Hant** 在第一輪採用對台灣友善的用詞。
- 6 個語系皆有 App Store 中繼資料。
- 翻譯的優先順序：ja、zh-Hant、zh-Hans、de、fr。
- v1.0 發行納入了一輪五語系的 string-catalog 審查（約 56 處修正），且產品名詞由複數的 **「Filters」** 改為單數的 **「Filter」**，貫穿所有語系——請讓翻譯與單數的「我的篩選（my filter）」模型保持一致。

基礎已就位，但發行前完整的人工翻譯審查仍待進行，因此整體狀態為 **In progress**。

> **呈現邊界清理（Planned，Phase 4）。** `LavaSecCore`／`Shared` 應承載*語意*（嚴重度／動作 enum、圖示角色），而非英文字串。嚴重度色調呈現已被提升到語意化的 `ProtectionTintRole`。剩下的殘餘是解析器的 `displayName` 仍是硬編碼的英文字串（「Google」、「Cloudflare」、「Quad9」、「Device DNS」）於 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift。Phase 4 會將這些提升到一個按 OS 區分的應用端呈現對應表 — 對 i18n 與 Android 可移植性而言皆正確。

i18n 機制（本地化詞彙表、本地化檔案結構，以及翻譯審查檢核表）存在於內部 i18n 文件中，而非這套公開文件。

---

## 7. 參考素材 {#7-reference-artifacts}

HTML 設計參考（非上線、內部）：上手流程分鏡、一份 kiwi-creme 守護者外觀研究，以及面板內主要按鈕的視覺選項。

DS 基礎已落地：`LavaDesignSystem/` 群組、`LavaSpacing`／半徑／`dangerRed` token、`LavaTier` 深度語意，以及 `LavaIcon` 角色層皆已上線（lavasec-ios: LavaSecApp/LavaDesignSystem/）。在可移植性／基礎計畫中仍屬 **Planned** 的是 `LavaColorRole` 強調色 token 化（Phase 3）、針對核心端英文字串的按 OS 區分呈現對應表（Phase 4）、一份中立的跨平台 token JSON，以及更廣的 Android 可移植性接縫。
