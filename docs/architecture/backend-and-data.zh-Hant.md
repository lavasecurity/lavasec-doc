---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 後端與資料 {#backend-data}

> **對象：** 後端工程師。**範圍：** 伺服器層 — 兩個 Cloudflare Workers、Supabase Postgres 結構描述／RLS／驗證、Cloudflare R2 與 D1 儲存區、完整的 HTTP API 介面、設定與部署，以及伺服器端如何落實 source-url-only。
>
> **權威參考：** 當計畫與程式碼不一致時，**以程式碼為準** — 分歧之處會就地標註。狀態標籤採用文件集圖例：**已實作**（已發布並在程式碼中確認）、**進行中**（部分落地）、**規劃中**（已設計，尚未建置）、**已捨棄**（遭否決或回退）。

## 1. 後端的樣貌 {#1-the-shape-of-the-backend}

後端刻意保持精簡且兼顧隱私。它是一個中繼資料與帳號的邊緣層，不是篩選服務。**所有 DNS 篩選都在裝置上進行；Lava Security 從不將你的瀏覽流量導向其伺服器，也從不接收你造訪的網域串流 — 後端只保存目錄中繼資料、不透明的每位使用者加密備份，以及你選擇傳送的匿名診斷資料。** 這裡沒有任何用於例行 DNS 查詢或每個網域遙測的資料表，而且帳號登入是選用的，防護絕不需要登入。

伺服器層拆分為兩個元件：後端 Worker 程式碼與 DB 結構描述。

| 元件 | 角色 |
|---|---|
| **lavasec-api Worker** | 主要邊緣層：公開目錄讀取、管理者＋cron 封鎖清單同步與目錄發布、匿名錯誤回報、說明回饋、帳號刪除、App Store 權益鏡像、QA 探測像素、帳號 QA 存取檢查、錯誤回報分流提升 |
| **lavasec-email Worker** | 僅接收的 Cloudflare Email Routing 轉寄器，服務 `@lavasecurity.app` |
| **Supabase Postgres**（一個 Supabase Postgres 專案） | 帳號、加密備份、目錄中繼資料、僅限服務角色的資料表；每張公開資料表都啟用 RLS |
| **Cloudflare R2**（一個正式環境 bucket，另有獨立的預覽 bucket 供測試環境使用） | 目錄快照＋同步游標；**絕不**存放第三方封鎖清單位元組 |
| **Cloudflare D1**（說明回饋資料庫） | 僅供附加的匿名說明文章回饋投票 |

Worker 透過 PostgREST（`/rest/v1`）與 Auth（`/auth/v1`），使用 Supabase 服務角色憑證連到 Supabase — 伺服器上沒有 Supabase SDK；呼叫是經由 `supabase()` ／ `supabaseAuth()` 輔助函式發出的原始 `fetch`。

狀態：**已實作**。

## 2. lavasec-api Worker {#2-lavasec-api-worker}

`wrangler.toml`：`name = "lavasec-api"`、`main = "src/index.ts"`、一個 R2 繫結 → 正式環境 bucket（另有獨立的預覽 bucket 供測試環境使用）、一個 D1 繫結 → 說明回饋資料庫，以及**兩個 cron 觸發器**：一個每 6 小時觸發一次（封鎖清單同步＋目錄發布），另一個每 2 分鐘觸發一次（錯誤回報分流提升）。它服務於 `api.lavasecurity.app`。

### 2.1 API 介面 {#21-api-surface}

路由是一個扁平的 `route()` 分派器。除非另有標註，否則一切皆為**已實作**。

**公開／未驗證**

| 方法與路徑 | 處理常式 | 備註 |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | 從 R2 提供 `catalog/latest.json` |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | 從 R2 提供 `catalog/{version}.json`；`Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS`（預設 300s） |
| `POST /v1/bug-reports` | `createBugReport` | 匿名、登入選用；僅允許清單內的除錯欄位 |
| `POST /v1/help-feedback` | `createHelpFeedback` | 匿名文章投票 → **D1**，非 Supabase |

> 附件上傳（先前的 `PUT /v1/bug-reports/:id/attachment` 路由）已被**移除**；螢幕截圖與額外細節改由人工中介的支援管道處理。Worker 僅在帳號刪除期間盡力刪除任何遺留的附件物件。

**帳號（需要 Supabase 存取權杖）**

| 方法與路徑 | 處理常式 | 備註 |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | 驗證使用者的存取權杖，刪除其資料列＋任何遺留的 R2 附件物件，然後以服務角色刪除該 Supabase Auth 使用者 |
| `GET /v1/account/qa-access` | `accountQAAccess` | 從僅限服務角色的 `qa_developers` 允許清單回傳 `is_developer` |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | 從用戶端驗證過的 StoreKit JWS 更新插入一筆 `entitlements` 資料列（方案 `lava_security_plus`） |

> **沒有 `/v1/backup` 路由。** 通行密鑰輔助的備份復原現在是**零知識**且完全在用戶端進行（見 §4.3 與 §5）；Worker 沒有任何 `/v1/backup/*` 路由，也沒有 WebAuthn／通行密鑰程式碼。

**管理者（透過 `requireAdmin` 的管理者 API 金鑰）**

| 方法與路徑 | 處理常式 |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> 管理者 HTTP 端點由管理者 API 金鑰把關。排程（cron）同步路徑**不會**呼叫這些 HTTP 路由 — 它在 `scheduled` 處理常式內直接呼叫同步邏輯（`syncBlocklistSources`）。

**QA 探測主機** — 對四個 `*.qa-probe.lavasecurity.app` 主機（`allowed`／`blocked`／`exception`／`guardrail`）的請求會在路由前被短路，並透過 `getQAProbePixel` 回傳一張 1×1 的 `no-store` PNG。這些不會寫入 Supabase 或 R2。

### 2.2 繫結與 cron {#22-bindings-cron}

- **R2 繫結** — `catalog/latest.json`、`catalog/{version}.json`，以及輪詢游標 `catalog/scheduled-sync-cursor.json`。**它絕不存放第三方封鎖清單位元組。**（遺留的錯誤回報附件物件只會被*刪除* — 在帳號刪除期間盡力刪除 — 絕不寫入。）
- **D1 繫結** — 僅供附加的匿名 `article_id` ／ `locale` ／ `vote` ／ `path` 資料列；依設計與 Supabase 分開保存。
- **Cron（`scheduled`）** — 處理常式依 cron id 分支：
  - **每 6 小時** — 每次執行同步**一個**來源，透過 R2 游標（`nextScheduledSyncSourceID`、`SCHEDULED_SYNC_CURSOR_KEY`）輪詢，然後重新發布目錄。分散負載可避免一次猛烈衝擊所有上游。
  - **每 2 分鐘** — 執行一條內部錯誤回報分流路徑，將新的匿名回報提升至內部問題追蹤佇列，並推進其專屬的水位游標。這是內部運維工具；問題追蹤／通知識別碼屬於設定，而非公開 API 的一部分。

## 3. 目錄與 source-url-only 落實 {#3-catalog-source-url-only-enforcement}

這是後端最貼近 Lava Security 合規態勢的部分，因此在伺服器端具備實質約束力。

### 3.1 source-url-only 模型 {#31-the-source-url-only-model}

> **source-url-only：** GPL／IP 合規散布模型：Lava Security 只發布上游 URL ＋已接受的雜湊；裝置自行擷取／解析清單。Lava Security **絕不**儲存、鏡像、轉換或提供第三方封鎖清單位元組。

每一筆 `blocklist_sources` 資料列都帶有 `redistribution_mode`，其唯一允許值為 `"source_url_only"`。裝置讀取的目錄（`/v1/catalog`，`schema_version` 2）將項目拆為 `sources[]` 與 `guardrails[]`；每一項都帶有上游 `source_url` 加上 `accepted_source_hashes`（SHA-256 ＋位元組大小＋項目數＋`reviewed_at` ＋狀態 `accepted`） — 絕不帶清單位元組。見 `formatCatalogEntry`。

> **已捨棄：** 較早的設計曾在 R2 中鏡像保留位元組的 GPL 清單檔案（GPL-raw-R2 合規計畫）。它於 **2026-05-25** 被 source-url-only **取代**。Lava Security 不再儲存或提供第三方封鎖清單位元組。`mirror_events` 這個資料表名稱是那個已放棄設計留下的遺留命名 — 它現在只是同步／發布的稽核記錄。

### 3.2 Worker 如何在寫入時落實它 {#32-how-the-worker-enforces-it-on-writes}

同步路徑（`syncOneBlocklist`，管理者與 cron）會擷取每個上游 `source_url`，**僅在 Worker 中本機正規化／驗證以計算中繼資料**（`entry_count`、`source_hash`、`normalized_hash`、`byte_size`），寫入一筆 `blocklist_versions` 資料列，並重新發布。位元組儲存鍵被硬寫為 null：

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

一個遷移（`20260525000000_add_blocklist_distribution_mode.sql`）將這些欄位改為可為 null 並將現有值設為 null，因此不鏡像的立場也在結構描述層級被落實。發布的目錄會**同時**寫入 R2 中的 `catalog/{version}.json` 與 `catalog/latest.json`（`publishCatalog`）。

### 3.3 正規化防護欄（僅中繼資料） {#33-normalization-guardrails-metadata-only}

Worker 端的正規化（`normalizeBlocklist`）會過濾受保護網域、強制上限，並去重＋排序。這純粹是為了計算可信的中繼資料；**裝置在下載真正的清單時會重新驗證已接受的雜湊**，因此這本身不是一道安全邊界。關鍵常數：

- `PROTECTED_SUFFIXES` — 移除任何符合 Apple／iCloud／`mzstatic`／Lava Security 網域／Supabase／Cloudflare／Google／GitHub 的規則，因此遭污染的上游無法封鎖 Lava Security 自身的基礎設施或登入提供者。
- `MAX_BLOCKLIST_BYTES = 25 MiB`、`MAX_BLOCKLIST_LINE_LENGTH = 2048`、`MAX_NORMALIZED_DOMAINS = 500_000`。

### 3.4 哪些可以發布 {#34-what-is-publishable}

`isPublicBlocklistSource` 只在 `status` 為 `sync` 或 `nosync`、`redistribution_mode === "source_url_only"`，**且** `isAllowedLaunchGPLSource` 通過時才發布來源。launch-GPL 閘門（`isAllowedLaunchGPLSource`）自由允許非 GPL 來源，但將 GPL-3.0 來源限制為 `list_id` 前綴為 `hagezi-` 或 `oisd-`。

### 3.5 種子來源與預設啟用 {#35-seeded-sources-default-enabled}

精選來源透過遷移以 source-url-only 中繼資料形式植入種子（HaGeZi、OISD、Block List Project、Phishing.Database、AdGuard）。低風險遷移（`20260526000000_low_risk_blocklist_sources.sql`）最初將 `blocklistproject-basic`（Unlicense）以 `default_enabled = true` 植入，強制**所有 GPL（HaGeZi／OISD）來源 `default_enabled = false`** 以待法律顧問審查，並將 AdGuard DNS Filter 停放在 `license_review`。**那個最初的 Basic 預設種子後來被取代** — 下方的對齊遷移將 Basic 翻為 `false`，並將 Phishing ＋ Scam 翻為 `true`（目前提供的預設值）。狀態：**已實作**。

> **目錄預設值與用戶端一致。** 目錄的 `default_enabled` 集合現在為 **{Block List Project Phishing、Block List Project Scam}**，與 iOS 建議預設值（`AppConfiguration.lavaRecommendedDefaults`，位於 `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`）一致。一個遷移將 `blocklistproject-basic default_enabled = false`，並將 `blocklistproject-phishing` ／ `blocklistproject-scam default_enabled = true`，因此提供的中繼資料是真實的。（對齊決策現已發布。）請注意 `default_enabled` 屬於資訊性質：真正的方案閘門是**篩選規則預算（免費 500K ／ Plus 2M）**，而非清單數量。發布 URL（而非位元組）的法律依據見 [GPL source-url-only 合規決策](../legal/gpl-source-url-only-compliance-decision.md)。

## 4. Supabase Postgres {#4-supabase-postgres}

一個 Supabase Postgres 專案。**每一張**公開資料表都啟用 RLS。

### 4.1 核心結構描述 {#41-core-schema}

`20260516034033_backend_core.sql` 建立基礎（在全部 7 張公開資料表上啟用 RLS）：

- **`profiles`、`user_settings`、`entitlements`** — 每位使用者的帳號狀態。一個觸發器 `handle_new_user()` 會在 `auth.users` 插入時自動建立 `profiles` ＋ `user_settings` 資料列。
- **`blocklist_sources`、`blocklist_versions`** — 目錄中繼資料表。來源是一份精選的上游清單（`list_id`、`source_url`、授權、風險、`default_enabled`、`status`、`redistribution_mode`）；版本是某次同步快照的中繼資料（雜湊、`entry_count`、`byte_size`），透過 `latest_version_id` 連回。
- **`mirror_events`** — 僅限服務角色的 `sync` ／ `catalog_publish` 事件稽核記錄（遺留命名；見 §3.1）。
- **`bug_reports`** — 僅限服務角色的匿名回報。

後續的遷移加入了 **`user_backups`**（§4.3）與 **`qa_developers`**（`20260608000000_qa_developers_allowlist.sql`）。

### 4.2 RLS 模型 {#42-rls-model}

| 資料表 | 政策 | 效果 |
|---|---|---|
| `profiles`、`user_settings`、`entitlements`、`user_backups` | 每位使用者 `auth.uid() = user_id` | 每位使用者只看得到自己的資料列 |
| `blocklist_sources` | 在 `status in ('sync','nosync')` 時公開讀取（`backend_core.sql:262-266`） | 任何人都能讀取精選、符合同步資格的來源 |
| `blocklist_versions` | 在 `validation_status = 'published'` 時公開讀取（`backend_core.sql:268-272`） | 任何人都能讀取已發布的版本中繼資料 |
| `bug_reports`、`mirror_events` | 明確 `using(false)`（`20260516034136_backend_core_advisor_fixes.sql`） | 無 anon／authenticated 存取 — Worker 使用服務角色 |
| `qa_developers` | RLS 啟用 ＋ **撤銷 anon、authenticated 的所有權限** | 僅限服務角色；QA 允許清單絕不能被用戶端讀取 |

這道切分很重要：匿名錯誤回報必須能被 Worker *插入*，卻不能被用戶端*讀取*，而 QA 允許清單必須只能被服務角色讀取。

### 4.3 驗證與加密備份信封 {#43-auth-the-encrypted-backup-envelope}

**驗證**是選用的。登入**僅限 Apple ＋ Google**（電子郵件／密碼已**捨棄**）。兩者都使用原生 `id_token` 授權，在 Supabase Auth `auth/v1/token?grant_type=id_token` 以雜湊過的 nonce 交換；app 只將產生的工作階段以裝置本機方式儲存在 Keychain。用戶端流程位於 iOS app（`lavasec-ios: LavaSecApp/AccountAuthService.swift`、`lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`） — 完整的帳號／備份模型見 [帳號與備份](./accounts-and-backup.md)。

> **零知識備份：** 用戶端 AES-256-GCM 信封；只有密文＋非機密中繼資料會上傳至 Supabase `user_backups`（每位使用者 RLS）。伺服器在沒有使用者持有的機密下無法解密。

關鍵的後端事實：**iOS 用戶端在每位使用者 RLS 下，透過 Supabase PostgREST 直接讀寫 `user_backups`**（以 `user_id` 更新插入，並由存取權杖限定範圍）。Worker 上**根本沒有 `/v1/backup` 路由**。Worker 只在一處接觸 `user_backups`：在帳號刪除期間刪除它（`deleteAccount`）。

`user_backups` 只儲存不透明的密文＋非機密信封中繼資料（KDF 參數／鹽值、nonce、金鑰槽標籤、用戶端結構描述提示）。大小上限（`20260605000000_tighten_backup_envelope_constraints.sql`）：密文 ≤ 262144 位元組（256 KiB）／ ≤ 349528 字元，中繼資料 ≤ 32768 位元組（32 KiB）。DB 絕不儲存明文設定、密碼、復原碼或金鑰。

### 4.4 帳號刪除 {#44-account-deletion}

`POST /v1/account/delete` 驗證使用者的存取權杖，然後刪除其 `bug_reports`（以及任何相符的遺留 R2 附件物件）、`user_backups`、`entitlements`、`user_settings` 與 `profiles` 資料列，最後透過服務角色的 `/admin/users` 端點刪除該 Supabase Auth 使用者。它只回傳已刪除狀態＋關聯的提供者。狀態：**已實作**（計畫的 frontmatter 寫著 `status: Done`，且檔案位於 `plans/implemented/`；一段過時的**本文內**註解仍寫著「Backlog」，但其所在的分組資料夾＋程式碼存在使其為已發布）。

### 4.5 App Store 權益鏡像 {#45-app-store-entitlement-mirroring}

`POST /v1/account/entitlements/app-store-sync` 從用戶端驗證過的 StoreKit 交易 JWS，依 `user_id` 衝突時更新插入一筆 `entitlements` 資料列（方案 `lava_security_plus`）。儲存的 `verification_status` 字面上就是 `"client_verified_storekit"` — 伺服器**不會**重新驗證該 JWS。允許的產品 ID：`lava_security_plus_{monthly,yearly,lifetime}`。

> 鏡像為**已實作**；**伺服器端 JWS 驗證為規劃中**（尚未建置）。簽署過的 JWS 會被儲存以待日後驗證。請注意他處的方案模型：app 權益是本機的（`isPaid`），目前**尚無後端同步**作為真相來源 — 這一資料列是鏡像，而非閘門。

## 5. 通行密鑰輔助的復原（零知識） {#5-passkey-assisted-recovery-zero-knowledge}

通行密鑰輔助的備份復原是**零知識**且完全在用戶端進行。復原金鑰材料是在裝置上從通行密鑰的 **WebAuthn PRF ／ hmac-secret** 輸出衍生出來的；伺服器**不**儲存任何復原機密、**不**註冊任何通行密鑰，也**不**發出任何 WebAuthn 挑戰。沒有任何由伺服器把關的託管路徑。

較早設計使用的託管資料表（`backup_passkey_recovery`、`backup_passkey_challenges`）已在發布前移除，而 Worker 不帶任何 `/v1/backup/*` 路由，也沒有 WebAuthn／通行密鑰程式碼。（Worker 的 `package.json` 中仍殘留一筆 `@simplewebauthn/server`，是未使用的遺留相依套件。）

用戶端部分位於 iOS app：`lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` 驅動具 PRF 能力的通行密鑰建立／斷言，而 `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` 從 hmac-secret 輸出衍生出金鑰槽。PRF 輸出只在斷言期間讀取，且絕不離開裝置。不具 PRF 的通行密鑰提供者無法支撐零知識金鑰槽，因此設定會提早失敗，使用者改回退到復原碼。狀態：**已實作**。

## 6. lavasec-email Worker {#6-lavasec-email-worker}

僅接收與轉寄。它將 `support@` ／ `hello@` ／ `jimmy@` ／ `legal@lavasecurity.app` 轉寄至一個已驗證的營運者收件匣，拒絕未知收件人與超過 10 MiB 的郵件，且**不儲存郵件內文**。支援自動回覆已寫好程式碼，但被閘門擋在付費的 Cloudflare 對外電子郵件之後（延後）。路由常數位於 `email-service.ts:9`（`ROUTED_RECIPIENTS`）；入站處理常式為 `handleInboundEmail`。狀態：**已實作**（自動回覆路徑為**規劃中**／延後）。

## 7. 設定與部署 {#7-config-deploy}

- **設定為 `wrangler.toml`，且被 gitignore**；`wrangler.toml.example` 是已提交的範本。對環境特定的值，請將本機的 `wrangler.toml` 視為權威。
- **Vars**（非機密，位於 `[vars]`）：Supabase URL、公開 API origin（`https://api.lavasecurity.app`）、目錄快取 TTL（預設 300s）、錯誤回報大小上限、帳號刪除稽核開關，以及一個 Workers 執行階段加速旗標。內部錯誤回報分流另加一個內部分流佇列鍵，以及一個在組合分流連結時使用的儀表板 origin。
- **Secrets**（透過 `wrangler secret put`）：一份 Supabase 服務角色憑證、一把管理者 API 金鑰，以及 — 供錯誤回報分流路徑使用 — 一把問題追蹤 API 金鑰與一個選用的聊天通知 webhook。
- **部署為手動**：`npm run deploy` → `wrangler deploy`。Worker 沒有 CI。
- **Cloudflare 路由**：`lavasecurity.app` 留在 Pages；`api.lavasecurity.app` 與 `*.qa-probe.lavasecurity.app` 解析至此 Worker。
- **相容性**：`compatibility_date = "2026-05-16"`、`compatibility_flags = ["nodejs_compat"]`。

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` 設於 vars，但未被 Worker 程式碼參照；它是一個 Workers 執行階段加速旗標，而非應用程式設定。

## 8. 隱私不變式（這裡有什麼、沒有什麼） {#8-privacy-invariants-what-is-and-isnt-here}

給任何要擴充後端的人的快速檢查清單 — 以下任一項都不得被悄悄打破：

1. **無 DNS／瀏覽遙測。** 沒有任何用於例行 DNS 查詢或每個網域遙測的資料表。篩選留在裝置上。
2. **無第三方封鎖清單位元組** 存於 R2 或 Postgres — 只有 `source_url` ＋已接受的雜湊（§3）。
3. **`user_backups` 不透明** — 只有密文＋非機密中繼資料；由用戶端（而非 Worker）在 RLS 下寫入（§4.3）。
4. **服務角色隔離** 適用於 `bug_reports`、`mirror_events`、`qa_developers`（§4.2）。
5. **所有備份路徑皆為零知識** — 包括通行密鑰輔助的復原，其金鑰材料在用戶端從 WebAuthn PRF／hmac-secret 輸出衍生。伺服器不儲存任何復原機密，也不執行任何 WebAuthn（§5）。

## 另見 {#see-also}

- [系統總覽](./system-overview.md) — 整個系統一頁呈現，包含信任邊界。
- [iOS 用戶端](./ios-client.md) — 消費此後端的裝置端。
- [帳號與備份](./accounts-and-backup.md) — 用戶端驗證、AES-256-GCM 信封、金鑰槽與復原碼。
- [DNS 篩選與封鎖清單](./dns-filtering-and-blocklists.md) — 目錄的裝置端：直接從上游下載、解析／正規化，以及篩選規則預算。
- [GPL source-url-only 合規決策](../legal/gpl-source-url-only-compliance-decision.md) — 為何目錄發布 URL 而非位元組。
- **方案與營收**（內部） — 作為真正免費／Plus 閘門的篩選規則預算（免費 500K ／ Plus 2M）。
- **IP 風險登記簿**（內部） — source-url-only 背後的 IP／合規依據。
