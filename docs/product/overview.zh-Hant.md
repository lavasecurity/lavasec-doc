---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 產品總覽 {#product-overview}

歡迎使用 Lava Security。本頁介紹 Lava 是什麼、它承諾什麼，以及到哪裡可以閱讀更多內容。

## Lava 是什麼 {#what-lava-is}

Lava Security 是一款以隱私為先的 iOS 應用程式，透過裝置上的 [NetworkExtension 封包通道](../architecture/ios-client.md)在裝置本機篩選 DNS，封鎖已知的風險與不需要的網域，而不會把你的瀏覽流量繞經 Lava 的伺服器。這個封包通道（`LavaSecTunnel`，一個 `NEPacketTunnelProvider`）會在手機上剖析每一筆 DNS 查詢，將請求的網域與一份已編譯、記憶體對映的篩選快照進行比對，僅將獲允許的查詢往上游轉發。沒有任何由 Lava 營運、讓你的流量經過的代理伺服器：篩選是在你的裝置上做出的本機決定。

iOS 之所以將它標示為「VPN」，是因為封包通道是應用程式能在系統層級篩選 DNS 的唯一方式——但 Lava 做的是 **DNS／封鎖清單篩選**，而非流量路由。我們對範圍誠實以告：Lava 是本機的 DNS 網域篩選，**並非**保證每一個惡意網域或網址都會被封鎖。它看得到網域，看不到頁面路徑，因此無法封鎖一個原本可信主機上的某個惡意頁面。防護也不會在引導流程一結束就自動開啟——應用程式內的**防護**分頁才是判斷防護目前是否生效的權威來源。

## 隱私承諾 {#the-privacy-promise}

> 所有 DNS 篩選都在裝置上完成；Lava 絕不會把你的瀏覽流量繞經其伺服器，也絕不會收到你造訪網域的串流——後端只保有目錄中繼資料、一份不透明的逐使用者加密備份，以及你選擇傳送的匿名化診斷資料。

這句話是正規定義。本套文件中的其他一切，都應與它保持一致。付費購買選用方案**並不會**把篩選移到伺服器，也不會讓 Lava 取得你造訪網域的串流。當某項功能涉及伺服器時，文件會明確說明哪些內容**不會**被傳送——你的日常 DNS 查詢、你的瀏覽歷史，以及任何明文，全都留在裝置上。完整圖像請參閱[後端與資料模型](../architecture/backend-and-data.md)。

## 它適合誰 {#who-it-is-for}

Lava 是為任何想要更安全瀏覽、又不想費心管理的人而打造。其目標對象刻意涵蓋非技術使用者——為家庭設定防護的家長、年長者，以及任何完全不想去想 DNS 的人。預設體驗就是順手可用：開啟防護，一份保守的封鎖清單便開始篩選，無需帳號。同時，進階使用者在需要時也能深入更進階的控制項（自訂封鎖清單、替代解析器）。

全篇的語氣都是平實、沉穩、實用的——危險以隱喻來呈現，而非以恐懼。

## 核心原則 {#core-principles}

- **隱私是定位，而非付費功能。** 篩選是本機決定。Lava 的後端刻意保持極簡，絕不會收到你日常的瀏覽網域或 DNS 事件串流。選用的帳號備份是[零知識](../architecture/accounts-and-backup.md)的：伺服器只儲存密文與非機密的封套中繼資料。
- **核心防護永久免費。** 防護開關、預設封鎖清單更新，以及基本的本機計數，永遠不會被設限，也永遠不需要帳號。
- **裝置端。** 防護引擎完全存在於手機上——DNS 剖析、網域評估與上游轉發全都發生在封包通道擴充功能之內，受 iOS 每個擴充功能約 50 MiB 的記憶體上限所限。封鎖清單遵循[僅來源網址](../architecture/dns-filtering-and-blocklists.md)模型：應用程式直接擷取每一份上游清單並在本機剖析；Lava 絕不託管或提供第三方封鎖清單的位元組。
- **付費僅解鎖客製化——絕不解鎖基本安全。** 威脅防護欄——一個位於所有封鎖清單之上、任何人（無論付費與否）都無法加入允許清單的不可允許層級——透過決策優先順序強制執行：**威脅防護欄 > 本機允許清單（允許例外） > 封鎖清單 > 預設允許。**（此優先順序欄位已接好，並由獲接受的 SHA-256 雜湊值進行完整性檢查；目前出貨時沒有任何項目。）通道會忽略 `isPaid`。
- **沉穩的核心，循序漸進的深度。** 預設介面安靜而令人安心，由 Soft Shield Guardian 吉祥物與避免恐懼導向用語的文案領銜。更豐富、更技術性的細節在你主動尋找時隨手可得，但絕不會強加於你。這套「沉穩核心、循序漸進的深度」哲學在 **LavaTier** 深度模型（Floor／Window／Workshop）中被正式化——請參閱[設計系統](../design-system/overview.md)。

## 高階能力 {#high-level-capabilities}

- **本機 DNS 篩選**——封包通道引擎會剖析 DNS、將每個網域與已編譯的快照進行評估，並將獲允許的查詢以裝置 DNS 後援的方式往上游轉發。請參閱 [iOS 用戶端](../architecture/ios-client.md)以及 [DNS 篩選與封鎖清單](../architecture/dns-filtering-and-blocklists.md)。
- **精選封鎖清單，僅來源網址**——Lava 只發布上游清單網址（加上供快取識別與稽核之用的建議雜湊值）；裝置會透過 TLS 擷取每一份清單，並在本機於大小／規則上限之下剖析，而且 Lava 絕不鏡像或提供第三方封鎖清單的位元組。社群清單並未以雜湊值釘選——TLS 加上精選網址就是其完整性邊界——而 Lava 的威脅防護欄層級則維持以雜湊值強制執行。出貨的預設會啟用 **Block List Basic**（`AppConfiguration.lavaRecommendedDefaults`，定義於 `OnboardingDefaults.swift`）；HaGeZi、OISD、AdGuard、1Hosts 等 copyleft 來源為選擇性加入。請參閱 [DNS 篩選與封鎖清單](../architecture/dns-filtering-and-blocklists.md)。
- **加密的 DNS 傳輸**——DoH（附帶觀測用的 DoH3 註記）、DoT（連線池化，可重複使用並刷新）以及 DoQ（每次查詢使用全新連線）。三者皆已實作；Device DNS（網路本身的解析器）是出貨的預設，加密的預設組合為選擇性加入（`AppConfiguration.lavaRecommendedDefaults`，定義於 `Sources/LavaSecCore/OnboardingDefaults.swift`）。內建的解析器預設組合（Google／Cloudflare／Quad9 的 DoH 與 DoT 變體）為免費；只有完全自訂的解析器才是付費解鎖。請參閱 [DNS 篩選與封鎖清單](../architecture/dns-filtering-and-blocklists.md)。
- **允許例外（允許清單）**——手動加入網域，使其在封鎖清單之外仍被允許；威脅防護欄仍然優先。請參閱[產品功能總覽](features.md)。
- **Soft Shield Guardian**——防護分頁、即時動態與動態島上的吉祥物，以 7 種表情狀態表達防護狀態。請參閱[設計系統](../design-system/overview.md)。
- **分層客製化（Lava Security Plus）**——一個選用的付費方案，用以解鎖客製化（更大的篩選規則預算——免費方案 500K／Plus 2M 條已編譯規則，置於共用的裝置安全防護欄之下——更多允許／封鎖網域、自訂封鎖清單，以及自訂 DNS 解析器）。Plus 絕不會繞過恆常開啟的防護欄——通道會忽略 `isPaid`。
- **選用的帳號與備份**——以 Apple 或 Google 登入，搭配端對端加密（[零知識](../architecture/accounts-and-backup.md)）的設定備份與復原碼；帳號刪除為自助式。選用的通行密鑰復原欄位**同樣是零知識**的——其金鑰在裝置上自驗證器的 WebAuthn PRF 衍生，沒有任何伺服器持有的祕密；裝置端的正式上線整備仍取決於 Associated Domains／AASA 託管 **（規劃中）**。帳號為選用；防護在完全登出的狀態下也能完整運作。
- **僅本機的活動與報告**——裝置端的封鎖／允許計數、通道健康狀態，以及一個選擇性加入的錯誤回報組合，皆由運行中的通道留在裝置上的資料建構而成——閒置時為空，防護進行中則為即時。沒有任何日常網域歷史記錄會離開裝置。請參閱[產品功能總覽](features.md)。

## 平台 {#platforms}

- **iOS——已出貨。** Lava 目前是一款 iOS 應用程式：三個套件共用一個 App Group（`group.com.lavasec`）——應用程式（`com.lavasec.app`）、封包通道擴充功能（`.tunnel`）與小工具（`.widget`）——再加上共用原始碼，建構於一個共通的 `LavaSecCore` 套件之上。
- **Android——規劃中。** 一個建構於 Android `VpnService` 之上的原生 Kotlin／Jetpack Compose 移植版本正在規劃中，承載相同的隱私承諾與經過對等性測試的核心篩選行為。目前尚無任何 Android 應用程式碼出貨。

關於穩定的功能 id 以及 iOS／Android 契約，請參閱[平台對等性](platform-parity.md)。
