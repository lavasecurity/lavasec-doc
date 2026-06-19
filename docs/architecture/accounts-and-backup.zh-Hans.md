---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 账户与零知识备份

> **读者对象：** 工程师。
> **权威来源：** 当这份文档和某个计划说法不一致时，**以代码为准**——分歧之处会在正文里直接指出。状态反映的是代码确认的真实情况，而不是计划里的设想。状态图例：**已实现**（已发布并在代码中确认）、**进行中**（部分落地）、**计划中**（已设计，但还没动手）、**已放弃**（被否决或回退）。

账户是**可选的**。核心防护永久免费，不需要账户；登录的唯一作用是把你的*设置*加密备份起来，方便你在新设备上恢复。本文档讲清楚认证流程、会话存在哪里、零知识备份的封装信封、各种恢复路径，以及服务器到底能看到什么、看不到什么。

这份文档要兑现的核心隐私承诺是：

> 所有 DNS 过滤都在设备上完成；Lava Security 绝不会把你的浏览流量经过它的服务器，也绝不会收到你访问的域名串流——后端只保存目录元数据、每个用户一份无法解读的加密备份，以及你主动选择发送的匿名诊断信息。

代码分工：纯加密 + 请求构建放在 `LavaSecCore`；编排 + UI 放在 `LavaSecApp`。同系列文档：[系统总览](./system-overview.md)、[iOS 客户端](./ios-client.md)、[后端与数据](./backend-and-data.md)、[DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md)。

---

## 1. 认证流程 {#1-authentication-flow}

**只支持 Apple 和 Google 两家。** **（已实现）** `AccountAuthProvider` 枚举的就只有 `.apple` 和 `.google`（`AccountAuthService.swift`）。邮箱/密码登录——以及任何绕过认证、靠客服协助来恢复账户的做法——都明确**已放弃**；自己管理密码会带来重置/多因素/锁定/泄露等一堆义务，在 Apple/Google 已经够用的前提下不值得这份复杂度，而绕过认证的恢复方式会破坏零知识保证。

两家都用**原生 `id_token` 授权**，既不走 Supabase Swift SDK，也不走网页 OAuth：

1. **原生登录。** Apple 走 AuthenticationServices；Google 走 GoogleSignIn SDK。各自返回一个供应商的 `id_token`（Google 还会给一个 access token）。App 生成一个 CSPRNG 原始 nonce，用 SHA256 把它哈希一遍，再把哈希值交给供应商，这样签发出来的 `id_token` 就和它绑定了。**（已实现）**
2. **在 Supabase 兑换。** `SupabaseIDTokenAuth`（`LavaSecCore`）会直接构造一个原始 `URLRequest`，发给 Supabase Auth 的 `auth/v1/token?grant_type=id_token`，把 `provider` + `id_token` + 可选的 `access_token` + **原始** nonce 一起 POST 过去（这样 Supabase 就能验证绑定关系、拒绝重放攻击），并带上 `apikey` 头。不用 SDK；`LavaSecCore` 保持没有任何网络/认证依赖。**（已实现）**
3. **拿到会话。** Supabase 验证令牌后返回一个会话：一个 access token、一个 refresh token、一个过期时间，以及一条用户记录（供应商/多供应商）。刷新会话用同一个辅助方法，带上 `grant_type=refresh_token`。

`AccountAuthService`（`@MainActor`，`LavaSecApp`）把这一整套都编排起来——它跑原生流程、做兑换、保存并刷新会话、暴露 `AccountAuthState`，还通过 Worker 来驱动账户删除。

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

## 2. 会话与 Keychain 存储 {#2-session--keychain-storage}

登录之后**唯一**被持久化保存的，就是 Supabase 会话——access token 和 refresh token，以 JSON 形式存着。除了 Supabase Auth 里的那个用户和你拥有的那些行之外，服务器端**不会**再镜像保存任何关于你身份的信息。

- **存在哪：** `AccountSessionKeychainStore`（`LavaSecApp`），Keychain 服务名 `com.lavasec.account-session`，**按供应商分别**存（`supabase-session-apple` / `supabase-session-google`，外加一份旧账户迁移用的）。**（已实现）**
- **可访问性：** 所有存储都共用 `GenericKeychainStore`（`LavaSecCore`），固定为 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`。也就是说**只在本设备上、不通过 iCloud 同步、也不会进设备备份**。**（已实现）**

同一套 `GenericKeychainStore` 机制支撑着三个存储：账户会话、备份解锁材料（`BackupKeychainStore`，服务名 `com.lavasec.zero-knowledge-backup`），以及 App 密码。三个都不会通过 iCloud Keychain 同步。

> **待评审项（不是已声明的行为）：** 当前的可访问性等级没有生物识别/用户在场验证的门槛（没有 `SecAccessControl` 的 `.userPresence`/`.biometryCurrentSet`）。要不要把解锁材料收紧到一个需要用户在场的访问控制，作为一个发布门评审项在跟进；今天发布的值就是 after-first-unlock-this-device-only。**（计划中）**

---

## 3. 零知识备份 {#3-zero-knowledge-backup}

### 3.1 它到底是什么 {#31-what-it-is-precisely}

当你开启加密备份时，**iOS 客户端**会把你*设置*的一份精简副本加密，然后只把密文和非机密的元数据上传到 Supabase。明文和那些用来解密的秘密，只存在于手机这一个地方。

> **零知识备份：** 客户端做 AES-256-GCM 信封封装；随机的载荷密钥被包进每个密钥槽里——密码/恢复短语/设备/协助恢复这几个槽用 PBKDF2-HMAC-SHA256（21 万次迭代），PRF 通行密钥槽用 HKDF-SHA256。只有密文 + 非机密元数据会上传到 Supabase 的 `user_backups`（按用户做 RLS）。没有用户持有的秘密，服务器没法解密。通行密钥槽**同样**是零知识的：它的解包密钥是在设备上从认证器的 WebAuthn PRF（`hmac-secret`）输出派生出来的，服务器不持有任何通行密钥秘密（见 §4.3）。

### 3.2 哪些东西会被备份（精简后的载荷） {#32-what-gets-backed-up-the-minimized-payload}

`BackupConfigurationPayload`（`LavaSecCore`）就是那份要被封装的明文。它特意做得很小，并且能和 `AppConfiguration` 来回无损转换。**（已实现）**

**包含：** 已启用拦截列表的 **ID**（目录引用，不是列表本身的字节）、允许的域名/已拦截域名、解析器预设 / 自定义解析器、本地日志偏好、LavaGuard 账本、一个防护提示，以及自定义拦截列表的来源元数据。

**不包含：** `isPaid`（权益是本地的）、QA 标志、诊断信息、过滤器快照，以及完整的拦截列表内容（只用目录 ID 引用）。你的浏览历史和 DNS 查询从来不在这份载荷里，因为设备压根不会把它们当成常规遥测流来记录。

### 3.3 信封（客户端加密） {#33-the-envelope-client-side-crypto}

`ZeroKnowledgeBackupEnvelope`（`LavaSecCore`）实现了这套加密。**（已实现）**

1. **载荷加密。** 精简后的载荷用一个随机的 **32 字节载荷密钥**（用 `SecRandomCopyBytes` 生成）做一次 **AES-256-GCM** 封装。
2. **密钥包装（密钥槽）。** 这把唯一的载荷密钥会被独立地包进一个或多个**密钥槽**里，每个秘密一个槽，然后用 AES-GCM 把载荷密钥的一份副本包起来。任何一个槽的秘密都能解开整份备份。包装密钥的派生方式按槽的类型而定：`password` / `recoveryPhrase` / `keychain`（设备）/ `assistedRecovery` 这几个槽用 **PBKDF2-HMAC-SHA256，21 万次迭代**（生产环境；`defaultPasswordIterations = 210_000`），每个槽都用一份新鲜的 16 字节随机盐；`passkey` 槽则在认证器的 PRF 输出之上用 **HKDF-SHA256**（info 为 `"LavaSec passkey backup PRF v1"`），并把那份非机密的 PRF 盐存在槽里，这样恢复时就能重新算出同样的输出。
3. **槽的类型。** 信封支持五种槽：`password`、`recoveryPhrase`、`keychain`（设备秘密）、`assistedRecovery` 和 `passkey`。

实际发布的设置是**无密码**的（`makePasswordless`，由 `AppViewModel.turnOnEncryptedBackup` 驱动）。它会创建一个 **`keychain`（设备）槽 + 一个 `assistedRecovery` 槽 + 一个可选的 `passkey` 槽**。`password` / `recoveryPhrase` 的工厂方法和解密方法仍然保留着，用于旧版/向后兼容的信封（只在测试里被用到），但实际 UI 从来不会创建一个只有密码的信封——把密码备份当成没发布就对了。**（已实现；密码槽已从实际流程中放弃。）**

**完整性 / 防降级：** `envelopeVersion` 硬钉死为 `1`，每个槽的 KDF 也按类型钉死——密码/短语/设备/协助槽用 `PBKDF2-HMAC-SHA256`，PRF 通行密钥槽用 `HKDF-SHA256`。不支持的版本或对不上的 KDF 会被拒绝，所以伪造或降级的元数据没法削弱解包过程。**（已实现）**

### 3.4 上传与存储 {#34-upload--storage}

`BackupSyncService`（`SupabaseBackupSyncService`，`LavaSecApp`）把信封**直接**上传到 Supabase 的 PostgREST 表 `user_backups`，按 `user_id` 做 upsert，作用域由用户的 access token 限定。**信封上传没有走任何 Worker 路由**——客户端在 RLS 下直接和 Supabase 对话；Worker 只在账户删除时才碰 `user_backups`，去把它删掉。**（已实现）**

落进 `user_backups` 里的东西：

- **密文**，以及
- **只有非机密元数据：** cipher 名称、各密钥槽记录（盐、迭代次数、被包装的密钥、槽标签）、`server_recovery_share`、`createdAt`，还有字节大小。

这一行受**行级安全（RLS）**保护：每一行只有它的拥有者能读/写（`auth.uid() = user_id`）；匿名角色没有任何访问权限。大小在数据库层做了上限：密文约 256 KiB / 元数据 32 KiB（`20260518000000_zero_knowledge_backups.sql`，并在 `20260605000000_tighten_backup_envelope_constraints.sql` 里进一步收紧）。**（已实现）**

### 3.5 这份保证——服务器能看到什么、看不到什么 {#35-the-guarantee--what-the-server-can-and-cannot-see}

**服务器存的是：** 密文、KDF 的盐/迭代次数、被包装的密钥槽、`server_recovery_share`，以及几个非机密字段（cipher、大小、时间戳）。

**服务器绝不会收到或存储：** 明文设置/域名/DNS 偏好、恢复短语、任何备份密码，或者解包后的载荷密钥。

**所以：** 没有用户持有的秘密，Supabase **没法解密任何一份备份**。三条恢复路径——设备密钥槽、恢复短语（和服务器份额结合，§4.2），以及通行密钥槽（认证器的 PRF 输出，§4.3）——全都**在设备上**解密，服务器对其中任何一条都不持有解密秘密。这一点在迁移文件的注释和隐私计划里都有声明，也有测试（信封测试确认上传出去的形态里不会泄露任何明文域名/URL）。

**精确的威胁模型注意事项——别夸大其词。** 对于**协助恢复**槽，服务器在 `user_backups` 里*同时*持有 `server_recovery_share` *和*被包装的 `assistedRecovery` 槽。它唯一缺的是用户的恢复短语，而 Lava Security 从来不会收到这个。所以假如服务器被彻底攻破，恢复短语的熵（约 105 位，见 §4.1）加上 21 万次迭代的 PBKDF2 成本，就是抵挡对那个槽做离线暴力破解的**唯一**屏障。这是有意为之的（协助恢复在设计上就是双因素——两半里任何一半单独都解不开），但这也意味着恢复短语的熵是真正承重的，不是摆设。`keychain`（设备）槽的秘密从不离开设备，所以它完全不会暴露在服务器被攻破的情形下。

---

## 4. 恢复 {#4-recovery}

备份只有在你能恢复时才有用。`restoreEncryptedBackup`（在 `AppViewModel` 里）通过逐个尝试可用的槽来解密：设备密钥、恢复短语，或通行密钥。无论哪种模式，信封都是在本地加载（或从 Supabase 取回）后**在设备上解密**的——服务器从不解密。

### 4.1 恢复短语 {#41-recovery-phrase}

`BackupRecoveryPhrase`（`LavaSecCore`）会从 `SecRandom` 用拒绝采样生成一个 **8 个词的 CVCV 短语**（辅音-元音-辅音-元音）（每个 token 约 13.2 位 → **总共约 105 位**），并归一化成小写。**（已实现）** 恢复时会先做解析/归一化，再去尝试那个槽，所以能容忍用户输入的格式差异（空格/大小写）。

这是用户的**离设备**恢复因子——由用户自己保存，从不上传。按隐私加固方案（§5），复制短语是**可选的**，而且用到时会走一个仅本地 / 会过期（10 分钟）的剪贴板，而不是强行暴露到全局剪贴板。

### 4.2 协助恢复（双因素组合） {#42-assisted-recovery-the-two-factor-combination}

光有恢复短语**解不开** `assistedRecovery` 槽。槽的秘密是从**两半**一起派生出来的：

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

在实际的 UTF-8 输入里，这三段是用一个 **NUL 字节（`0x00`）分隔符**连起来的——也就是说被哈希的字符串是 `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase`——所以上面那个 `‖` 表示的是以 NUL 分隔的拼接，而不是直接拼起来。`serverRecoveryShare` 是一个随机值，存在服务器端的信封元数据里；`normalizedPhrase` 是用户的恢复短语。**两半里任何一半单独都解不开**——恢复需要服务器份额（随备份一起取回）*以及*用户持有的短语。**（已实现）**

### 4.3 通行密钥恢复——零知识、由 PRF 派生 {#43-passkey-recovery--zero-knowledge-prf-derived}

可选的 `passkey` 槽加上了一个有硬件背书的因子，而且它是**零知识**的：它的解包密钥是**在设备上**从认证器的 WebAuthn PRF（`hmac-secret`）输出派生出来的。服务器不注册任何通行密钥、不签发任何 WebAuthn 挑战，也不存储任何恢复秘密——根本没有服务器放行这一步。

- **注册/断言：** `BackupPasskeyCoordinator`（`LavaSecApp`）通过 `ASAuthorizationPlatformPublicKeyCredentialProvider` 跑 WebAuthn，依赖方为 **`lavasecurity.app`**，在一个每凭证一份的盐上请求 PRF 扩展，并要求用户验证。
- **密钥派生（零知识）：** 认证器返回的 PRF 输出**从不离开设备**。`ZeroKnowledgeBackupEnvelope.makeWithPRF`（`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`）用 HKDF-SHA256 从那份 PRF 输出派生出槽的包装密钥（info 为 `"LavaSec passkey backup PRF v1"`），再用 AES-GCM 包装载荷密钥；只有非机密的 PRF 盐和凭证 ID 会被存进槽里。恢复时，`passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` 会重新断言这个凭证，复现出同样的 PRF 输出，然后 `decryptWithPasskeyPRFOutput` 在本地解包这个槽。服务器**不**持有任何通行密钥秘密，所以没有任何 service-role 路径能恢复一份受通行密钥保护的备份。

早先那套托管设计（一个 service-role 的 `backup_passkey_recovery` 表，存着服务器端的 `recovery_secret`，外加一个 `backup_passkey_challenges` 表和若干 `/v1/backup/passkeys/*` Worker 端点）已经**放弃**了：那些表在一次后端迁移里被移除，Worker 不带任何通行密钥路由，而且 `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` 明确断言 `BackupPasskeyRecoveryService` 和任何服务器托管路径都不存在。**（已实现）**

> **生产就绪注意事项：** 要把保存的通行密钥当成一个在实体设备上完全生产就绪的可恢复因子，还得依赖 `lavasecurity.app` 的 webcredentials 关联。iOS 这一半已经声明了——`lavasec-ios: LavaSecApp/LavaSecApp.entitlements` 里带着 `webcredentials:lavasecurity.app`——而服务器那一半（`apple-app-site-association` 文件和相关头）现在已托管在营销网站上。在某台设备上这个关联还没解析成功之前，webcredentials 关联路径可能会失败，并抛出 `BackupPasskeyError.webCredentialsAssociationUnavailable`。通行密钥因子本身是已实现的；它在真实硬件上的端到端就绪状态仍是**计划中**。

---

## 5. 数据最小化与隐私姿态 {#5-data-minimization--privacy-posture}

- **账户可选。** 防护不需要账户也能用；登录只是开启设置备份。
- **明文只在本地。** 手机是明文设置和解密秘密唯一存在的地方；Supabase 每个用户只持有一份无法解读的信封。
- **载荷已精简。** 只有 §3.2 里那些设置会被备份；`isPaid`、QA 标志、诊断、快照，以及完整的拦截列表字节都被排除在外。拦截列表只用目录 ID 引用，从不嵌入。
- **没有浏览/DNS 遥测。** 不存在任何用于常规 DNS 查询或单域名遥测的服务器端表；过滤一直留在设备上。
- **解锁材料只在本设备。** 备份解锁材料以 `…ThisDeviceOnly` 可访问性存储，**不**通过 iCloud 同步。这**反转**了原计划里那套可同步 Keychain 的设计，所以 Lava Security 不会悄悄通过 iCloud 同步解锁材料（`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`）。**（已实现；反转了早先的计划。）**

### 账户删除 {#account-deletion}

删除功能**已实现**，并且走的是一个需要认证的 Worker 端点，而不是客户端直接删除。`AccountAuthService.deleteAccount` 把用户的 access token 发到 `POST /v1/account/delete`；`lavasec-api` Worker（service role）会删除该用户的 `bug_reports`（连同它们在 R2 上的附件）、`user_backups`、`entitlements`、`user_settings` 和 `profiles` 各行，然后通过 admin API 删除 Supabase Auth 用户，只返回一个已删除状态 + 关联的供应商。之后 App 会在本地登出并清掉备份解锁材料（`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`）。

> 注：删除计划的 YAML frontmatter 已经写着 `status: Done`，文件也放在 `plans/implemented/` 里。有一处过时的**正文内**标注写着 `Status: Backlog.`，但按照分道文件夹规则（文件夹才是权威）和代码现状（App 和 Worker 都存在），该功能是**已实现**的；正文里那一行是文档 bug，不是 frontmatter。

---

## 6. 状态汇总 {#6-status-summary}

| 领域 | 详情 | 状态 |
|---|---|---|
| 通过 Supabase 的 Apple / Google `id_token` 登录 | 原生流程、哈希 nonce、原始 URLRequest 兑换 | 已实现 |
| 邮箱/密码登录 | 拒绝自己管理密码 | 已放弃 |
| 会话存在 Keychain（仅本设备、按供应商分） | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | 已实现 |
| AES-256-GCM 信封 + PBKDF2-HMAC-SHA256（21 万）密钥槽 | 客户端；只有密文 + 非机密元数据上传到 `user_backups`（RLS） | 已实现 |
| 无密码设置（设备 + 协助恢复 + 可选通行密钥槽） | `makePasswordless` | 已实现 |
| 实际流程里的密码密钥槽 | 在 `LavaSecCore` 里只为测试保留 | 已放弃 |
| 恢复短语（8 词 CVCV，约 105 位） | 离设备因子 | 已实现 |
| 协助恢复（服务器份额 + 短语经 SHA256，NUL 分隔） | 双因素；任一半单独都不行 | 已实现 |
| 通行密钥恢复（零知识、WebAuthn PRF/`hmac-secret`，RP 为 `lavasecurity.app`） | PRF 输出经 HKDF 派生的槽，无服务器秘密 | 已实现 |
| 通行密钥作为硬件上生产就绪的因子 | 需要 webcredentials 关联（AASA 已托管在营销网站） | 计划中 |
| 账户删除（认证 Worker，service role） | 移除备份/设置/权益/资料/附件 + Auth 用户 | 已实现 |
| 解锁材料上的生物识别/用户在场门槛 | 发布门评审项 | 计划中 |
| 把 `EncryptedBackupCoordinator` 从 `AppViewModel` 抽出来 | 仅模块化；不改动安全模型 | 进行中 |

---

## 相关文档 {#related}

- [系统总览](./system-overview.md) —— 一屏看完整个系统，包括各信任边界。
- [iOS 客户端](./ios-client.md) —— `AppViewModel` 以及驱动备份的那些 App 目标。
- [后端与数据](./backend-and-data.md) —— `lavasec-api` Worker、Supabase RLS，以及 `user_backups` 存储。
- [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md) —— 解析器预设，以及那些设置被带进备份载荷里的传输方式。
