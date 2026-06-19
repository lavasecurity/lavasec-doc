---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 關鍵設計決策 {#key-design-decisions}

> 對象：工程師與管理層。這是 Lava Security 背後那些承重設計決策的 ADR 式記錄——那些形塑了架構、隱私承諾或產品邊界的決策，尤其是那些曾經嘗試又被回退的決策。每一條都列出**決策**、其**脈絡**、**理由**，以及一個取自專案狀態圖例的**狀態**（採用 / 回退 / 取代 / 提案）。
>
> **以程式碼為準。** 當計畫與已出貨的程式碼不一致時，本記錄以程式碼為準，並在行內標明分歧之處。

**狀態圖例（對應到文件集的狀態通道）：**

| 此處的狀態 | 文件集通道含意 |
|---|---|
| **採用** | Implemented——已出貨並在程式碼中確認 |
| **回退** | Dropped——已建置，隨後移除／回退 |
| **取代** | 較早的決策被較晚的決策取代 |
| **提案** | Planned——已設計、建議或記錄，但尚未套用到此程式樹 |

延伸閱讀：目錄散布模型見 [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) 與 [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md)；已出貨行為見 [`../product/features.md`](../product/features.md)。前瞻性方向見內部路線圖。

---

## 1. 透過 `NEPacketTunnelProvider` 在裝置端進行 DNS 篩選 {#1-on-device-dns-filtering-via-nepackettunnelprovider}

**決策。** 透過 `NEPacketTunnelProvider` 封包通道（`LavaSecTunnel`，`com.lavasec.app.tunnel`）在**裝置本機**篩選 DNS，而非採用 `NEDNSProxyProvider`、`NEFilterProvider`、`NEDNSSettingsManager` 或 Safari 內容封鎖器。

**脈絡。** 本產品是一款以隱私為先、面向非技術使用者（家長、長者）的篩選器，透過消費者 App Store 散布，且無需帳號。互相競爭的 NetworkExtension 供應器與受管 DNS API 都被限制在受監督／MDM 管理的裝置上，或無法涵蓋一個 App 的所有 DNS；而解析器端的模型會把使用者的網域串流路由到裝置之外。

**理由。** 封包通道是唯一能（a）在非受管的消費者裝置上運作，且（b）讓每一個 DNS 決策都在裝置端發生的供應器，這正是隱私承諾的基礎：*所有 DNS 篩選都在裝置上完成；Lava Security 絕不把你的瀏覽路由到其伺服器，也絕不接收你造訪的網域串流。* 為此接受的取捨是 iOS **每個擴充功能約 50 MiB 的記憶體上限**，通道必須在其之下運作——這個約束形塑了下文中數個後續決策。

**狀態。** **採用**（基礎性；自最初的原型起即在程式碼中）。

---

## 2. 僅以來源網址散布封鎖清單 {#2-source-url-only-blocklist-distribution}

**決策。** Lava Security 只發布上游封鎖清單的 **URL 加上可接受的雜湊值**；裝置直接從各個 `source_url` 抓取清單**位元組**，然後在本機解析、正規化、去重並篩選。Lava Security **絕不**儲存、鏡像、轉換或提供第三方封鎖清單位元組。Worker 只把目錄**中繼資料** JSON 寫入 R2（`raw_r2_key`／`normalized_r2_key` 為 null）。

**脈絡。** 較早的設計把原始封鎖清單位元組鏡像到 R2，好讓法務審查散布行為。許多上游清單（HaGeZi、OISD）採 GPL-3.0，因此託管其位元組會讓 Lava Security 成為 GPL 資料的再散布者。

**理由。** 把 Lava Security 視為本機篩選引擎／使用者代理程式——而非封鎖清單散布者——可將 GPLv3 再散布與 App Review 暴露降到最低。裝置會以目錄的 `accepted_source_hashes` 驗證下載的位元組，並在不相符時退回到上一筆可用快取，或以失敗即封閉的方式處理，藉此恢復鏡像管線原本提供的安全特性。每一組解析後的規則集也會通過一個受保護網域篩選器，使上游清單無法封鎖 Lava Security／Apple／身分提供者的網域。此模型在 CI 中由 `check-gpl-blocklist-distribution.sh` 強制執行（無鏡像程式碼、無 Lava Security 託管的成品 URL、無預設啟用的 GPL 來源、無 R2 位元組寫入）。

**狀態。** **採用**，並且**取代**了被放棄的 R2 原始鏡像計畫（`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`，標頭為「Superseded by the source-url-only implementation」）。見 [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md)。

---

## 3. 加密解析器傳輸（DoH / DoH3 / DoT / DoQ） {#3-encrypted-resolver-transports-doh-doh3-dot-doq}

**決策。** 除了純 DNS 與裝置 DNS 後援之外，再提供四種加密的上游傳輸，並抽取進 LavaSecCore：**DoH**（URLSession）、**DoH3**（偏好 HTTP/3 的 DoH）、**DoT**（採用集區化的 `NWConnection`，每端點最多 4 條，具閒置陳舊性刷新與一次全新連線重試），以及 **DoQ**（DNS-over-QUIC）。路由、純 DNS 降級、附帶退避閘的逐端點容錯切換，以及裝置 DNS 後援，都位於 `ResolverOrchestrator`。

**脈絡。** 以明文把未封鎖的查詢轉送給解析器，會洩漏裝置端模型原本要保護的那條網域串流。這些傳輸是逐步建置的（DoH → DoH3 → DoT → DoQ）。

**理由。** 加密的上游傳輸讓未封鎖的查詢得以端對端保持私密。**DoH3** 純粹是觀察性的標籤——設定了 `assumesHTTP3Capable=true` 並觀察協商出的協定，UI 僅在**實際觀察到 h3 協商時**才標註 `DoH3`（無斜線），絕不承諾，因為 h3 在每條連線上都是盡力而為，而黏著式的宣稱會在阻擋 UDP 的防火牆後誇大實際行為。具閒置刷新的 DoT 集區化，是針對 Cloudflare 默默關閉閒置 DoT 連線的直接修正。

**狀態。** **採用**（四種傳輸皆已具備並接線完成）。

---

## 4. DoQ 連線重用——已建置、已實機測試、已回退 {#4-doq-connection-reuse-built-device-tested-reverted}

**決策。** **不要**為 DoQ 重用 QUIC 連線。`DoQTransport` **每筆查詢開啟一條全新的 QUIC 連線**；4 條通道的集區提供的是並行性，而非交握重用。

**脈絡。** RFC 9250 把每筆 DNS 查詢對應到它自己的 QUIC 串流，因此真正的重用需要多串流的 `NWConnectionGroup`／`openStream` API，而那是 **iOS 26.0+ 才有**，但部署底線是 iOS 17。儘管如此，仍實作了一條以 iOS 26 為閘的重用路徑（針對 Xcode 26 SDK 編譯 Debug+Release），並在 **iOS 26.5 上實機測試**，對象為 AdGuard DoQ。

**理由。** 該重用路徑在裝置上每次嘗試都失敗（`openStream`／`receive` 報錯，隨後後援又遇到「Socket is not connected」），量測結果**比逐查詢基準更差**（對照組：34 次交握／35 筆查詢，全部成功）。這以實證確認了 Apple DTS 的「在新的 Network framework 上先別碰 QUIC」建議，因此這份工作被回退而非出貨；只有文件與防護測試的理由保留了這項發現，以免在該 API 成熟之前再次嘗試。

**狀態。** **回退**（延後至部署底線達到 iOS 26）。把 DoQ 描述為逐查詢的全新連線。

---

## 5. 駁回統一的 `DNSResolvingTransport` 協定 {#5-reject-a-unifying-dnsresolvingtransport-protocol}

**決策。** **不要**把各解析器傳輸統一在單一 `DNSResolvingTransport` 協定之下；保留以閉包為基礎的 `ResolverOrchestrator.Executors` 接縫。

**脈絡。** 一項重構（issue 407）提議用一個協定涵蓋所有傳輸。

**理由。** 這些傳輸彼此差異太大——非同步的加密執行器（DoH/DoT/DoQ）對上同步的多位址純／裝置傳輸——因此統一協定會是比現有可注入閉包接縫更糟的抽象，而後者已讓線路執行可被測試。

**狀態。** **回退**／不予實作（以糟糕抽象之名關閉）。

---

## 6. 零知識加密備份（無密碼，已標註通行密鑰例外） {#6-zero-knowledge-encrypted-backup-passwordless-passkey-exception-noted}

**決策。** 在用戶端備份一份**最小化**的設定酬載：AES-256-GCM 以一把隨機 32 位元組酬載金鑰加封，該金鑰再透過 PBKDF2-HMAC-SHA256（正式環境 **210,000** 次迭代）包裝進逐密鑰**金鑰槽**。只有密文加上非機密中繼資料會上傳至 Supabase `user_backups` 資料表（逐使用者 RLS）。已出貨的流程是**無密碼**：裝置密鑰槽（裝置本機 Keychain）+ 協助復原槽 + 選用的通行密鑰槽。

**脈絡。** 選用的帳號登入（僅 Apple + Google）讓跨裝置的設定還原成為可能。伺服器絕不可讀取使用者的封鎖清單、允許清單、解析器選擇或其他設定。

**理由。** 明文與解密用的密鑰只存在於裝置上；伺服器每位使用者只持有一個不透明的信封。協助復原刻意設計為雙因素——`SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)`（以 NUL 分隔的輸入）同時需要伺服器持有的份額**與**使用者的 8 個單字復原碼（約 105 位元），因此單獨任一半都無法解密。解鎖材料儲存在裝置本機（`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`），**不**放在可同步的 iCloud Keychain——這是一項隱私強化，反轉了原計畫的可同步設計。**通行密鑰槽同樣是真正的零知識**：它以一個 WebAuthn **PRF／`hmac-secret`** 驗證器輸出（HKDF-SHA256 衍生）來包裝，而該輸出絕不離開用戶端，因此沒有任何伺服器持有的值能將其解開。沒有 service-role 通行密鑰資料表，也沒有 Worker 的 WebAuthn 斷言閘——較早的伺服器設閘式通行密鑰設計已被捨棄，移除了所有伺服器端的通行密鑰狀態（`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`）。

**狀態。** **採用**（無密碼模型、協助復原，以及一個零知識、PRF 衍生的通行密鑰槽，全在程式碼中）。讓通行密鑰在實體裝置上成為一個完全可正式投產、可復原的因素（為 PRF 模型提供 Associated Domains／AASA 託管）則屬**提案**（待辦）。

---

## 7. 失敗即封閉的隨需連線（Connect-On-Demand） {#7-fail-closed-connect-on-demand}

**決策。** 加入一條 `NEOnDemandRuleConnect` 規則，使被 OS 停止的通道自動重啟，並以**失敗即封閉**作為安全預設：當沒有可重用的篩選快照時，通道封鎖所有流量，而非未經篩選地放行。隨需在**任何停止之前皆停用**，使 VPN 保持可關閉。

**脈絡。** iOS 一直默默地停止通道（reason 17），而約 45 分鐘內無物將其重啟，使使用者失去防護。天真地啟用隨需會讓 VPN 無法關閉，而失敗即放行的預設又會在空窗期放行流量。

**理由。** 隨需填補了默默停止的空窗；停止前先停用保住了使用者關閉防護的能力；失敗即封閉確保空窗期是安全的而非默默未篩選，並由 `reconcileTunnelSnapshotAfterLaunch` 恢復。這項變更有副作用——隨需在引導期間重新觸發了「加入 VPN 設定」的系統提示——進而催生出一條多次提交的修正鏈：在安裝時不再啟用隨需、把啟動／防護還原以引導完成為閘，並**以移除的方式中和一個繼承／孤立的設定**（`removeFromPreferences`，靜默），而非以儲存 `on-demand=false` 的方式（`saveToPreferences` 會再次顯示提示）。

**狀態。** **採用**（隨需重啟，加上引導／失敗即封閉的修正鏈）。

---

## 8. 模組化 VPN 重構與發熱回歸紀律 {#8-modular-vpn-refactor-and-the-heat-regression-discipline}

**決策。** 重構 VPN 路徑（VPNLifecycleController、ProtectionActionOrchestrator、ResolverOrchestrator、FilterArtifactStore、DNSResponseCache、RuleSetCache、FilterSnapshotPreparationService），以達成快取優先的開啟、有界並行抓取與抖動合併——把電池／延遲當作產品需求，並訂出明確的 p50/p95 目標，且採**實機**（非模擬器）剖析。

**脈絡。** 開啟／刷新／暫停／恢復都很慢。重構期間出現了一次發熱回歸（134% CPU、High energy、手機發燙）。一個大型代理面板先以回歸前的證據駁倒了被懷疑的成因；隨後一次實機擷取則加以確認。

**理由。** 真正的成因是一個自我維持的 `NEVPNStatusDidChange` 刷新迴圈——一個在 drop-reentrant 防護被替換後永遠重新啟動的合併迴圈（約 370 事件/秒、主執行緒約 100%、`vpn-debug-log.jsonl` 膨脹到約 180–210 MB）。修正方式是讀取快取的管理員狀態並為迴圈設界。計畫本身的前後實機成品記錄顯示，暖開啟（`action.turnOn`）在 iPhone 15 Pro 上自 **2,722 ms → 287 ms** 下降；另一次稍後的後模組化機會檢視在同一裝置上量到暖路徑為 **112 ms**（解碼 51 + managerSetup 57）。這段經歷立下了標準：結構性重構在量測到的發熱回歸被設界前暫停，而模擬器的熱／電池結果一律以無意義駁回。

**狀態。** **採用**（`plans/implemented/2026-06-12-modular-speed-up-plan.md`）。一次後模組化檢視把 `PacketTunnelProvider` 與 `AppViewModel` 列為已知尚存的上帝物件。

---

## 9. 以篩選規則預算取代清單數量上限 {#9-filter-rules-budget-instead-of-a-list-count-cap}

**決策。** 以**篩選規則預算**設立分級閘門——**免費 500K／Plus 2M** 條已編譯的網域規則——而非以已啟用清單的數量。一條硬性的 **約 3.26M 條規則的裝置防護欄**（`maxResidentMegabytes 32.0`、`baselineMegabytes 4.0`、`estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`）適用於**所有人**，且**絕非付費牆**。緊湊的網域 blob 以 `mmap`（`.mappedIfSafe`）映射，使其保持以檔案為後盾並落在 jetsam 計入的 `phys_footprint` 之外；只有解碼後的項目表才耗用常駐記憶體。

**脈絡。** 舊上限是清單**數量**（免費 3／付費 10）。一份清單可容納 1K 或 1M 條規則，因此數量是對真正受限資源——NE 50 MiB 記憶體上限——的不誠實代理。

**理由。** 規則對應到實際記憶體，因此任何能容下的清單組合都被允許。權威性的強制執行在編譯時於 `FilterSnapshotPreparationService` 中對去重後的聯集進行（先裝置防護欄，再分級上限）；選擇時的 UI 量表則使用逐清單加總，並帶一個 1.10 的軟上限餘裕。超出預算的設定會被確定性地拒絕（使防護保持關閉），而不是讓通道被 jetsam。

**狀態。** 在程式碼中**採用**（`SubscriptionPolicy.swift`），它**取代**了清單數量上限。驅動的計畫（`plans/under_review/2026-06-13-filter-rules-budget-tier-revamp.md`）仍在審查中，而公開網站的「Enabled blocklists 3 → 10」文案已**過時**——真正的閘門是規則預算。見 [`../product/features.md`](../product/features.md)。

---

## 10. 以 markdown 為計畫，單向同步至 Linear {#10-plans-as-markdown-one-way-linear-sync}

**決策。** `plans/<lane>/` 中的 markdown 檔案是**真實來源**；**lane 資料夾即權威狀態**（`implemented`、`inflight`、`under_review`、`backlog`、`dropped`）。推送到 `main` 會把計畫**單向**同步到 Linear（團隊 LAV），建立後只刷新標題／描述；另有一段獨立的**手動、經審查**的回程，把 Linear 的狀態／優先級／lane 拉回計畫的 frontmatter。

**脈絡。** 小型團隊需要與工具無關、可審查、又不與專案追蹤器相衝的規劃狀態，而自主代理迴圈需要一個穩定之處來讀寫計畫狀態。

**理由。** 欄位所有權的切分讓兩個系統互不衝突——markdown 擁有內容、Linear 擁有分流狀態——因此推送絕不會覆蓋人工分流。`dropped/` lane 把已取消的計畫排除在同步管線之外，使它們不再出現（在「允許例外」防護欄／LAV-5 被駁回時建立）。計畫內過時的 frontmatter 是文件臭蟲，不是狀態；資料夾為準，而當程式碼顯示某功能已出貨卻有「Backlog」frontmatter 時（例如帳號刪除），以程式碼為準。

**狀態。** **採用**（`scripts/sync-plans-to-linear.mjs`、`.github/workflows/sync-plans.yml`；`dropped/` lane 使用中）。

---

## 11. 倉庫拆分 + 用戶端的 copyleft 開源 {#11-repo-split-copyleft-open-source-of-the-client}

**決策。** 把單體倉庫拆成逐元件倉庫（`lavasec-ios`、`-android`、`-web`、`-infra`、`-doc`、`-runner`），並以 AGPL-3.0 **開源第一方用戶端**，取代 Apache-2.0，依循 Mullvad/ProtonVPN 的 copyleft 先例。

**脈絡。** 逐元件開發以及用戶端的開源。授權問題在於：競爭者是否可能 fork 用戶端、將其閉源，並在價格上削價競爭。

**理由。** copyleft 迫使衍生作品保持開放，防止用戶端被閉源 fork——一種「公開用戶端、私有後端／維運」的姿態，後端、法務與維運維持私有。選擇 AGPL-3.0（而非純 GPL-3.0）是為了堵住網路使用的漏洞。已知的 GPL 對 App Store 散布張力，由 Lava Security 自己以其自有著作權成為 App Store 二進位檔的散布者來處理。

**狀態。** **採用。** 倉庫拆分**已完成**：每個元件都住在自己的倉庫中——公開的 `lavasec-ios` 用戶端位於標籤 v0.4.0，另有 Android、行銷網站、後端／基礎設施、文件與 CI／發布管線的各自倉庫——而 `lavasec-ios` 的 `README.md`「Repository layout」一節只列出該倉庫的逐元件內容（`LavaSecApp/`、`LavaSecTunnel/`、`LavaSecWidget/`、`Shared/`、`Sources/`、`Tests/`），並註明基礎設施位於各自的私有倉庫。用戶端以 **AGPL-3.0** 開源：`lavasec-ios` 的 `LICENSE` 是 GNU Affero General Public License v3，而 `README.md` 帶有 AGPL-3.0 徽章。

---

## 附錄——其他已記錄的回退與駁回 {#appendix-other-recorded-reversals-and-rejections}

這些較小，但都是有記錄翻轉的真實決策；列出以求完整。

| 決策 | 理由 | 狀態 |
|---|---|---|
| 自訂 DNS 免費 vs 付費 | 變現定位；曾短暫在免費方案開放，隨後回到僅付費 | **回退**為僅付費 |
| 電子郵件／密碼登入 | 自行掌管密碼會帶來重設／MFA／鎖定／外洩／盜用負擔，而 Apple + Google 已足夠；繞過式復原會破壞零知識 | **回退**／從未出貨（僅 Apple + Google） |
| 允許例外防護欄（LAV-5） | 防護欄優先級已透過較簡單的篩選清單編輯改版出貨；付款絕不可繞過高信心的威脅防護欄 | **回退**（建立了 `dropped/` lane） |
| TestFlight 分支晉升鎖定 | 最初的鎖定被重新考慮；由一項計畫中的開源後 runner 鎖定取代 | **回退**，由一份待辦計畫取代 |
| App↔擴充功能控制通道 | `sendProviderMessage`（`NETunnelProviderSession`）是**唯一的 app→tunnel 控制路徑**——它承載具型別、有版次的狀態，並權威性地驅動擴充功能的執行迴圈。較早的擴充功能端 `CFNotificationCenter` 觀察者在裝置上從未可靠地觸發，已被**移除**（由原始碼內省測試斷言其不存在）。Darwin 通知只在 **tunnel→app** 方向存留，作為一個 health-changed 的提示。 | **採用**（provider-message 是唯一的 app→tunnel 控制；Darwin 僅為 tunnel→app 健康狀態） |

> 全篇引用的橫切安全不變式：付款絕不繞過經雜湊驗證、不可允許的**威脅防護欄**。決策優先級為 **威脅防護欄 > 本機允許清單（允許例外）> 封鎖清單 > 預設允許。**
