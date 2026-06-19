---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 帳號與零知識備份 {#accounts-zero-knowledge-backup}

> **適用對象：** 工程師。
> **權威來源：** 當本文件與某份計畫文件不一致時，**以程式碼為準** — 分歧之處會在內文中標註。狀態反映程式碼確認的實況，而非計畫的願景。狀態圖例：**已實作**（已上線並經程式碼確認）、**進行中**（部分落地）、**規劃中**（已設計、尚未建置）、**已捨棄**（被否決或回退）。

帳號是**選用的**。核心防護永遠免費且不需要帳號；登入只是為了將你的*設定*加密備份起來，讓你能在新裝置上復原它們。本文件涵蓋認證流程、工作階段存放的位置、零知識備份信封、復原路徑，以及伺服器究竟能看到什麼、不能看到什麼。

本文件所服務的核心隱私承諾：

> 所有 DNS 篩選都在裝置上進行；Lava Security 從不將你的瀏覽流量導向自家伺服器，也從不接收你造訪的網域串流 — 後端只持有目錄中繼資料、每位使用者一份不透明的加密備份，以及你選擇傳送的匿名診斷資訊。

元件分工：純加密 + 請求建構位於 `LavaSecCore`；協調 + UI 位於 `LavaSecApp`。相關文件：[系統總覽](./system-overview.md)、[iOS 用戶端](./ios-client.md)、[後端與資料](./backend-and-data.md)、[DNS 篩選與封鎖清單](./dns-filtering-and-blocklists.md)。

---

## 1. 認證流程 {#1-authentication-flow}

**提供者：僅限 Apple 與 Google。** **(已實作)** `AccountAuthProvider` 列舉的正好是 `.apple` 與 `.google`（`AccountAuthService.swift`）。電子郵件／密碼 — 以及任何繞過認證的客服協助復原 — 明確被**捨棄**；自行掌管密碼會帶來重設／MFA／鎖定／外洩等義務，在 Apple／Google 已足夠的情況下並不值得這份複雜度，而繞過式復原則會破壞零知識保證。

兩種提供者都使用**原生 `id_token` 授權**，而非 Supabase Swift SDK，也非網頁 OAuth：

1. **原生登入。** Apple 透過 AuthenticationServices；Google 透過 GoogleSignIn SDK。各自產生一個提供者 `id_token`（Google 還會給一個 access token）。應用程式產生一個 CSPRNG 原始 nonce，以 SHA256 雜湊之，並將雜湊值傳給提供者，讓所簽發的 `id_token` 與之綁定。**(已實作)**
2. **在 Supabase 交換。** `SupabaseIDTokenAuth`（`LavaSecCore`）建構一個原始 `URLRequest` 送往 Supabase Auth `auth/v1/token?grant_type=id_token`，提交 `provider` + `id_token` + 選用的 `access_token` + **原始** nonce（讓 Supabase 能驗證綁定並拒絕重放），並帶上 `apikey` 標頭。不使用 SDK；`LavaSecCore` 保持不依賴網路／認證。**(已實作)**
3. **接收工作階段。** Supabase 驗證 token 後回傳一個工作階段：一個 access token、一個 refresh token、一個到期時間，以及一筆使用者記錄（provider／providers）。重新整理使用同一個輔助器搭配 `grant_type=refresh_token`。

`AccountAuthService`（`@MainActor`，`LavaSecApp`）協調這一切 — 它執行原生流程、進行交換、保存並重新整理工作階段、揭露 `AccountAuthState`，並透過 Worker 驅動帳號刪除。

```
Apple / Google (native id_token + raw nonce)
        │
        ▼
SupabaseIDTokenAuth  ──POST──▶  Supabase Auth  auth/v1/token?grant_type=id_token
        │                              │
        ▼                              ▼
AccountAuthService  ◀────── session (access + refresh tokens, expiry, user)
        │
        ▼
AccountSessionKeychainStore  (Keychain, device-local)
```

---

## 2. 工作階段與 Keychain 儲存 {#2-session-keychain-storage}

登入後**唯一**會被保存的東西就是 Supabase 工作階段 — 以 JSON 形式存放的 access 與 refresh token。除了 Supabase Auth 使用者與你所擁有的資料列之外，伺服器端**沒有**任何關於你身分的鏡像。

- **位置：** `AccountSessionKeychainStore`（`LavaSecApp`），Keychain 服務 `com.lavasec.account-session`，**依提供者**分別存放（`supabase-session-apple` / `supabase-session-google`，外加一個舊版帳號遷移）。**(已實作)**
- **可存取性：** 所有儲存區共用 `GenericKeychainStore`（`LavaSecCore`），釘選為 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`。這表示**僅限本機、不透過 iCloud 同步，也不會被帶進裝置備份**。**(已實作)**

同一套 `GenericKeychainStore` 機制支撐三個儲存區：帳號工作階段、備份解鎖材料（`BackupKeychainStore`，服務 `com.lavasec.zero-knowledge-backup`），以及應用程式通行碼。它們都不會透過 iCloud Keychain 同步。

> **待審查項目（並非已宣稱的行為）：** 目前的可存取性類別沒有生物辨識／使用者在場閘門（沒有 `SecAccessControl` 的 `.userPresence`／`.biometryCurrentSet`）。是否要將解鎖材料收緊為以在場為閘門的存取控制，列為一個發布閘門審查項目；今日上線的值是 after-first-unlock-this-device-only。**(規劃中)**

---

## 3. 零知識備份 {#3-zero-knowledge-backup}

### 3.1 它究竟是什麼 {#31-what-it-is-precisely}

當你開啟加密備份時，**iOS 用戶端**會加密你*設定*的最小化副本，並只將密文加上非機密中繼資料上傳到 Supabase。手機是明文與解密用機密唯一存在的地方。

> **零知識備份：** 用戶端 AES-256-GCM 信封；隨機的酬載金鑰被包裝在每槽位的金鑰槽中 — password／phrase／device／assisted 槽使用 PBKDF2-HMAC-SHA256（210k 次迭代），PRF 通行密鑰槽則使用 HKDF-SHA256。只有密文 + 非機密中繼資料會上傳到 Supabase `user_backups`（每位使用者 RLS）。伺服器在沒有使用者持有機密的情況下無法解密。通行密鑰槽**同樣**是零知識的：其解包金鑰是在裝置端從認證器的 WebAuthn PRF（`hmac-secret`）輸出衍生而來，伺服器不持有任何通行密鑰機密（見 §4.3）。

### 3.2 哪些東西會被備份（最小化酬載） {#32-what-gets-backed-up-the-minimized-payload}

`BackupConfigurationPayload`（`LavaSecCore`）是會被封裝的明文。它刻意保持精簡，並可往返轉換成 `AppConfiguration`。**(已實作)**

**包含：** 已啟用封鎖清單的 **ID**（目錄參照，而非清單位元組）、允許的網域／已封鎖網域、解析器預設／自訂解析器、本機日誌偏好、LavaGuard 帳本、一個防護提示，以及自訂封鎖清單來源中繼資料。

**排除：** `isPaid`（權益屬本機）、QA 旗標、診斷、篩選快照，以及完整的封鎖清單內容（僅以目錄 ID 參照）。你的瀏覽歷史與 DNS 查詢從不屬於此酬載的一部分，因為裝置從不將它們記錄為例行的遙測串流。

### 3.3 信封（用戶端加密） {#33-the-envelope-client-side-crypto}

`ZeroKnowledgeBackupEnvelope`（`LavaSecCore`）實作了加密。**(已實作)**

1. **酬載加密。** 最小化酬載以一個隨機 **32 位元組酬載金鑰**（以 `SecRandomCopyBytes` 產生）用 **AES-256-GCM** 封裝一次。
2. **金鑰包裝（金鑰槽）。** 那把單一的酬載金鑰會被各自獨立地包裝進一個或多個**金鑰槽**，每個機密一個，然後以 AES-GCM 包裝酬載金鑰的一份副本。任何單一槽位的機密都能解鎖整份備份。包裝金鑰的衍生依槽位種類而異：`password` / `recoveryPhrase` / `keychain`（裝置）/ `assistedRecovery` 槽使用 **PBKDF2-HMAC-SHA256，210,000 次迭代**（生產環境；`defaultPasswordIterations = 210_000`），每槽配一份全新的 16 位元組隨機鹽值；`passkey` 槽則在認證器的 PRF 輸出上使用 **HKDF-SHA256**（info 為 `"LavaSec passkey backup PRF v1"`），並將非機密的 PRF 鹽值保存在槽中，使復原時能重現該輸出。
3. **槽位種類。** 信封支援五種槽位：`password`、`recoveryPhrase`、`keychain`（裝置機密）、`assistedRecovery` 與 `passkey`。

上線的設定是**無密碼的**（`makePasswordless`，由 `AppViewModel.turnOnEncryptedBackup` 驅動）。它會建立一個 **`keychain`（裝置）槽 + 一個 `assistedRecovery` 槽 + 一個選用的 `passkey` 槽**。`password` / `recoveryPhrase` 工廠與解密方法仍然存在，用於舊版／向後相容的信封（僅由測試演練），但實際運作中的 UI 從不建立只有密碼的信封 — 請將密碼備份視為未上線。**(已實作；password 槽已從實際流程捨棄。)**

**完整性／防降級：** `envelopeVersion` 被硬釘為 `1`，且每個槽位的 KDF 依種類釘選 — password／phrase／device／assisted 槽為 `PBKDF2-HMAC-SHA256`，PRF 通行密鑰槽為 `HKDF-SHA256`。不支援的版本或不相符的 KDF 會被拒絕，因此偽造或降級的中繼資料無法削弱解包。**(已實作)**

### 3.4 上傳與儲存 {#34-upload-storage}

`BackupSyncService`（`SupabaseBackupSyncService`，`LavaSecApp`）將信封**直接**上傳到 Supabase PostgREST 資料表 `user_backups`，以 `user_id` 做 upsert，並由使用者的 access token 限定範圍。**信封上傳沒有任何 Worker 路由** — 用戶端在 RLS 之下直接與 Supabase 對話；Worker 只在帳號刪除期間觸碰 `user_backups` 以將其刪除。**(已實作)**

落入 `user_backups` 的內容：

- **密文**，以及
- **僅非機密中繼資料：** 加密法名稱、金鑰槽記錄（鹽值、迭代次數、被包裝的金鑰、槽位標籤）、`server_recovery_share`、`createdAt`，以及位元組大小。

該資料列受**資料列層級安全性**保護：每一列僅其擁有者可讀／可寫（`auth.uid() = user_id`）；匿名角色無存取權限。在 DB 層級，大小上限約為 256 KiB 密文 / 32 KiB 中繼資料（`20260518000000_zero_knowledge_backups.sql`，在 `20260605000000_tighten_backup_envelope_constraints.sql` 中再收緊）。**(已實作)**

### 3.5 保證 — 伺服器能看到與不能看到什麼 {#35-the-guarantee-what-the-server-can-and-cannot-see}

**伺服器儲存：** 密文、KDF 鹽值／迭代次數、被包裝的金鑰槽、`server_recovery_share`，以及少數非機密欄位（加密法、大小、時間戳記）。

**伺服器從不接收或儲存：** 明文設定／網域／DNS 偏好、復原碼、任何備份密碼，或已解包的酬載金鑰。

**因此：** 在沒有使用者持有機密的情況下，Supabase **無法解密備份**。三條復原路徑 — 裝置金鑰槽、復原碼（與伺服器份額結合，§4.2），以及通行密鑰槽（認證器的 PRF 輸出，§4.3）— 全都在**裝置端**解密，且伺服器對任何一條都不持有解密機密。這在遷移註解與隱私計畫中均有斷言，並經過測試（信封測試確認上傳的形狀中沒有明文網域／URL 外洩）。

**精確的威脅模型注意事項 — 切勿過度宣稱。** 對於 **assisted-recovery** 槽，伺服器在 `user_backups` 中*同時*持有 `server_recovery_share` *與*被包裝的 `assistedRecovery` 槽。它唯一欠缺的是使用者的復原碼，而 Lava Security 從不接收它。因此若伺服器被完全攻陷，復原碼的熵（約 105 位元，見 §4.1）加上 210k 次迭代的 PBKDF2 成本，是抵禦對該槽進行離線暴力破解的**唯一**屏障。這是刻意設計的（協助復原在設計上即為雙因素 — 任一半單獨都無法解密），但這也意味著復原碼的熵是承重的，而非裝飾性的。`keychain`（裝置）槽的機密從不離開裝置，因此它完全不會暴露於伺服器攻陷。

---

## 4. 復原 {#4-recovery}

備份唯有在你能復原它時才有用。`restoreEncryptedBackup`（在 `AppViewModel` 中）藉由嘗試可用的槽位來解密：裝置金鑰、復原碼，或通行密鑰。在每一種模式下，信封都會在本機載入（或從 Supabase 取得）然後在**裝置端解密** — 伺服器從不解密。

### 4.1 復原碼 {#41-recovery-phrase}

`BackupRecoveryPhrase`（`LavaSecCore`）以拒絕取樣從 `SecRandom` 產生一組 **8 字 CVCV 詞組**（子音-母音-子音-母音）（約 13.2 位元／token → **總計約 105 位元**），正規化為小寫。**(已實作)** 復原在嘗試槽位之前，會透過解析／正規化容許使用者的格式（間距／大小寫）。

這是使用者的**離裝置**復原因素 — 由使用者自行保存、從不上傳。依據隱私強化（§5），複製此詞組是**選用的**，而當使用時，會走本機限定／到期（10 分鐘）的剪貼簿，而非強制暴露於全域剪貼簿。

### 4.2 協助復原（雙因素組合） {#42-assisted-recovery-the-two-factor-combination}

僅有復原碼**並不會**解鎖 `assistedRecovery` 槽。槽位機密是從**兩**半衍生而來：

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

這三個區段在實際的 UTF-8 輸入中以一個 **NUL 位元組（`0x00`）分隔符**串接 — 也就是被雜湊的字串是 `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — 因此上面的 `‖` 表示以 NUL 分隔的串接，而非裸串接。`serverRecoveryShare` 是儲存在伺服器端信封中繼資料裡的一個隨機值；`normalizedPhrase` 是使用者的復原碼。**任一半單獨都無法解密** — 復原同時需要伺服器份額（隨備份取得）*與*使用者持有的詞組。**(已實作)**

### 4.3 通行密鑰復原 — 零知識、PRF 衍生 {#43-passkey-recovery-zero-knowledge-prf-derived}

選用的 `passkey` 槽增加了一個由硬體支撐的因素，而它是**零知識**的：其解包金鑰是在**裝置端**從認證器的 WebAuthn PRF（`hmac-secret`）輸出衍生而來。伺服器不註冊任何通行密鑰、不發出任何 WebAuthn 挑戰、也不儲存任何復原機密 — 沒有伺服器釋放步驟。

- **註冊／斷言：** `BackupPasskeyCoordinator`（`LavaSecApp`）透過 `ASAuthorizationPlatformPublicKeyCredentialProvider` 執行 WebAuthn，依賴方（relying party）為 **`lavasecurity.app`**，在每個憑證的鹽值上請求 PRF 擴充，並要求使用者驗證。
- **金鑰衍生（零知識）：** 認證器回傳一個**從不離開裝置**的 PRF 輸出。`ZeroKnowledgeBackupEnvelope.makeWithPRF`（`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`）以 HKDF-SHA256 從該 PRF 輸出衍生出槽位的包裝金鑰（info 為 `"LavaSec passkey backup PRF v1"`），並以 AES-GCM 包裝酬載金鑰；只有非機密的 PRF 鹽值與憑證 ID 會被保存在槽中。復原時，`passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` 重新斷言該憑證以重現相同的 PRF 輸出，而 `decryptWithPasskeyPRFOutput` 在本機解包該槽。伺服器**不**持有任何通行密鑰機密，因此沒有任何 service-role 路徑能復原受通行密鑰保護的備份。

先前的代管（escrow）設計（一個 service-role 的 `backup_passkey_recovery` 資料表持有伺服器端 `recovery_secret`，加上一個 `backup_passkey_challenges` 資料表與 `/v1/backup/passkeys/*` Worker 端點）已被**捨棄**：這些資料表在一次後端遷移中被移除、Worker 不帶任何通行密鑰路由，而 `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` 明確斷言 `BackupPasskeyRecoveryService` 與任何伺服器代管路徑皆不存在。**(已實作)**

> **生產就緒性注意事項：** 要將已儲存的通行密鑰視為實體裝置上完全生產就緒的可復原因素，仍取決於 `lavasecurity.app` 的 webcredentials 關聯。iOS 那一半已聲明 — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` 帶有 `webcredentials:lavasecurity.app` — 而伺服器那一半（`apple-app-site-association` 檔案與標頭）現已託管於行銷網站。在某台裝置上該關聯解析完成之前，webcredentials 關聯路徑可能失敗並回報 `BackupPasskeyError.webCredentialsAssociationUnavailable`。通行密鑰因素本身已實作；其在真實硬體上的端到端就緒性則為**規劃中**。

---

## 5. 資料最小化與隱私態勢 {#5-data-minimization-privacy-posture}

- **選用帳號。** 防護不需要帳號即可運作；登入只是啟用設定備份。
- **僅本機明文。** 手機是明文設定與解密用機密唯一存在的地方；Supabase 持有每位使用者一份不透明的信封。
- **最小化酬載。** 只有 §3.2 中的設定會被備份；`isPaid`、QA 旗標、診斷、快照與完整的封鎖清單位元組均被排除。封鎖清單以目錄 ID 參照，從不內嵌。
- **無瀏覽／DNS 遙測。** 不存在任何用於例行 DNS 查詢或逐網域遙測的伺服器端資料表；篩選留在裝置上。
- **解鎖材料屬本機。** 備份解鎖材料以 `…ThisDeviceOnly` 可存取性儲存，且**不**透過 iCloud 同步。這**反轉**了原始計畫中可同步 Keychain 的設計，因此 Lava Security 不會悄悄透過 iCloud 同步解鎖材料（`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`）。**(已實作；反轉先前計畫。)**

### 帳號刪除 {#account-deletion}

刪除為**已實作**，並透過一個經過認證的 Worker 端點執行，而非用戶端直接刪除。`AccountAuthService.deleteAccount` 將使用者的 access token 送往 `POST /v1/account/delete`；`lavasec-api` Worker（service role）刪除使用者的 `bug_reports`（及其 R2 附件）、`user_backups`、`entitlements`、`user_settings` 與 `profiles` 資料列，然後透過 admin API 刪除 Supabase Auth 使用者，只回傳一個已刪除狀態 + 已連結的提供者。應用程式接著在本機登出並清除備份解鎖材料（`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`）。

> 注意：刪除計畫的 YAML frontmatter 已寫著 `status: Done`，且它位於 `plans/implemented/` 中。有一行過時的**內文**註記寫著 `Status: Backlog.`，但依據通道資料夾規則（資料夾具權威性）與程式碼存在性（app + Worker 兩者皆存在），此功能為**已實作**；那行內文是文件錯誤，而非 frontmatter。

---

## 6. 狀態總覽 {#6-status-summary}

| 領域 | 細節 | 狀態 |
|---|---|---|
| 透過 Supabase 的 Apple / Google `id_token` 登入 | 原生流程、雜湊 nonce、原始 URLRequest 交換 | 已實作 |
| 電子郵件／密碼登入 | 自行掌管密碼被否決 | 已捨棄 |
| Keychain 中的工作階段（本機、依提供者） | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | 已實作 |
| AES-256-GCM 信封 + PBKDF2-HMAC-SHA256（210k）金鑰槽 | 用戶端；只有密文 + 非機密中繼資料送往 `user_backups`（RLS） | 已實作 |
| 無密碼設定（裝置 + 協助復原 + 選用通行密鑰槽） | `makePasswordless` | 已實作 |
| 實際流程中的密碼金鑰槽 | 僅為測試而存留於 `LavaSecCore` | 已捨棄 |
| 復原碼（8 字 CVCV，約 105 位元） | 離裝置因素 | 已實作 |
| 協助復原（伺服器份額 + 詞組經 SHA256，NUL 分隔） | 雙因素；任一半單獨皆不可 | 已實作 |
| 通行密鑰復原（零知識、WebAuthn PRF／`hmac-secret`、RP `lavasecurity.app`） | PRF 輸出 HKDF 衍生的槽，無伺服器機密 | 已實作 |
| 通行密鑰作為硬體上的生產就緒因素 | 需要 webcredentials 關聯（AASA 託管於行銷網站） | 規劃中 |
| 帳號刪除（經認證的 Worker，service role） | 移除備份／設定／權益／個人檔案／附件 + Auth 使用者 | 已實作 |
| 解鎖材料的生物辨識／使用者在場閘門 | 發布閘門審查項目 | 規劃中 |
| 從 `AppViewModel` 抽出 `EncryptedBackupCoordinator` | 僅模組化；無安全模型變更 | 進行中 |

---

## 相關文件 {#related}

- [系統總覽](./system-overview.md) — 整個系統一覽，包含信任邊界。
- [iOS 用戶端](./ios-client.md) — `AppViewModel` 以及驅動備份的應用程式目標。
- [後端與資料](./backend-and-data.md) — `lavasec-api` Worker、Supabase RLS 與 `user_backups` 儲存。
- [DNS 篩選與封鎖清單](./dns-filtering-and-blocklists.md) — 解析器預設與傳輸，其設定攜帶於備份酬載中。
