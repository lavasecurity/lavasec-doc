---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 后端与数据 {#backend-data}

> **读者对象：** 后端工程师。**涉及范围：** 服务器这一层 —— 两个 Cloudflare Workers、Supabase Postgres 的表结构 / RLS / 鉴权、Cloudflare R2 和 D1 这两个存储、完整的 HTTP API、配置与部署，以及服务端是怎么把「只发 source-url」这条规矩落地的。
>
> **以谁为准：** 当计划文档和代码对不上时，**以代码为准** —— 不一致的地方会在文中直接点出来。状态标签沿用整套文档的图例：**已实现**（已上线并在代码里确认过）、**进行中**（部分落地）、**计划中**（设计好了但还没动工）、**已放弃**（被否决或回滚）。

## 1. 后端长什么样 {#1-the-shape-of-the-backend}

后端有意做得很小，而且很注重隐私。它是一层放元数据和账户的边缘服务，不是一个做筛选的服务。**所有 DNS 过滤都在设备上完成；Lava 从不把你的浏览流量绕经自家服务器，也从不收到你访问过的域名列表 —— 后端只保存目录元数据、每个用户一份看不懂内容的加密备份，以及你主动选择发送的匿名诊断信息。** 这里没有任何表用来记录日常 DNS 查询或逐域名的遥测数据，而且账户登录是可选的，开启防护从来都不需要它。

服务器这一层分成两块：后端 Worker 代码，以及数据库表结构。

| 组件 | 作用 |
|---|---|
| **lavasec-api Worker** | 主边缘：公开目录读取、管理端 + cron 拦截列表同步与目录发布、匿名错误报告、帮助反馈、账户删除、App Store 权益镜像、QA 探测像素、账户 QA 访问检查、错误报告分流提升 |
| **lavasec-email Worker** | 只收不存的 Cloudflare Email Routing 转发器，处理 `@lavasecurity.app` |
| **Supabase Postgres**（一个 Supabase Postgres 项目） | 账户、加密备份、目录元数据、仅 service-role 可访问的表；每张公开表都开了 RLS |
| **Cloudflare R2**（一个生产桶，另有一个独立的预览桶供 staging 用） | 目录快照 + 同步游标；**绝不**存第三方拦截列表的字节内容 |
| **Cloudflare D1**（帮助反馈数据库） | 只追加的匿名帮助文章反馈投票 |

Worker 通过 PostgREST（`/rest/v1`）和 Auth（`/auth/v1`）访问 Supabase，用的是 Supabase service-role 凭证 —— 服务器上没有 Supabase SDK；这些调用是经 `supabase()` / `supabaseAuth()` 辅助函数发出的原始 `fetch`。

状态：**已实现**。

## 2. lavasec-api Worker {#2-lavasec-api-worker}

`wrangler.toml`：`name = "lavasec-api"`、`main = "src/index.ts"`，一个 R2 绑定 → 生产桶（staging 另用一个独立的预览桶），一个 D1 绑定 → 帮助反馈数据库，外加**两个 cron 触发器**：一个每 6 小时触发（拦截列表同步 + 目录发布），一个每 2 分钟触发（错误报告分流提升）。它部署在 `api.lavasecurity.app`。

### 2.1 API 一览 {#21-api-surface}

路由是一个扁平的 `route()` 分发器。除非另有说明，下面这些都是**已实现**。

**公开 / 免鉴权**

| 方法和路径 | 处理函数 | 说明 |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | 从 R2 提供 `catalog/latest.json` |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | 从 R2 提供 `catalog/{version}.json`；`Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS`（默认 300 秒） |
| `POST /v1/bug-reports` | `createBugReport` | 匿名，登录可选；只接受白名单里的调试字段 |
| `POST /v1/help-feedback` | `createHelpFeedback` | 匿名文章投票 → 写入 **D1**，不是 Supabase |

> 附件上传（以前的 `PUT /v1/bug-reports/:id/attachment` 路由）已被**移除**；截图和额外细节改由人工对接的支持渠道处理。Worker 只会在账户删除时尽力删掉任何遗留的附件对象。

**账户（需要 Supabase access token）**

| 方法和路径 | 处理函数 | 说明 |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | 校验用户的 access token，删掉他们的各行数据 + 任何遗留的 R2 附件对象，然后用 service role 删掉 Supabase Auth 用户 |
| `GET /v1/account/qa-access` | `accountQAAccess` | 从仅 service-role 可访问的 `qa_developers` 白名单返回 `is_developer` |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | 根据客户端已验证的 StoreKit JWS，写入/更新一行 `entitlements`（plan 为 `lava_security_plus`） |

> **没有 `/v1/backup` 路由。** 通行密钥辅助的备份恢复现在是**零知识**的，完全在客户端完成（见 §4.3 和 §5）；Worker 没有任何 `/v1/backup/*` 路由，也没有任何 WebAuthn/通行密钥代码。

**管理端（经 `requireAdmin` 校验的管理 API key）**

| 方法和路径 | 处理函数 |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> 管理端 HTTP 接口由管理 API key 把守。定时（cron）同步那条路径**不会**调这些 HTTP 路由 —— 它直接在 `scheduled` 处理函数里调用同步逻辑（`syncBlocklistSources`）。

**QA 探测主机** —— 发往四个 `*.qa-probe.lavasecurity.app` 主机（`allowed`/`blocked`/`exception`/`guardrail`）的请求会在进入路由前就被短路处理，由 `getQAProbePixel` 返回一个 1×1 的 `no-store` PNG。这些都不会写进 Supabase 或 R2。

### 2.2 绑定与 cron {#22-bindings-cron}

- **R2 绑定** —— `catalog/latest.json`、`catalog/{version}.json`，以及轮转游标 `catalog/scheduled-sync-cursor.json`。**它从不存第三方拦截列表的字节内容。**（遗留的错误报告附件对象只会被*删除* —— 在账户删除时尽力而为 —— 从不写入。）
- **D1 绑定** —— 只追加的匿名行：`article_id` / `locale` / `vote` / `path`；按设计与 Supabase 分开存放。
- **Cron（`scheduled`）** —— 处理函数按 cron id 分支：
  - **每 6 小时** —— 每次运行只同步**一个**来源，借助 R2 游标轮转（`nextScheduledSyncSourceID`、`SCHEDULED_SYNC_CURSOR_KEY`），随后重新发布目录。把负载摊开，就不会一下子把所有上游都打爆。
  - **每 2 分钟** —— 跑一条内部的错误报告分流路径，把新的匿名报告提升进内部 issue-tracker 队列，并推进它自己的水位游标。这属于内部运维工具；issue-tracker / 通知用的那些标识符是配置项，不属于公开 API。

## 3. 目录与「只发 source-url」的落地 {#3-catalog-source-url-only-enforcement}

这是后端里最贴合 Lava 合规姿态的部分，所以它在服务端长了「牙齿」。

### 3.1 「只发 source-url」模型 {#31-the-source-url-only-model}

> **只发 source-url：** 一种符合 GPL/IP 合规的分发模式：Lava 只发布上游 URL + 已认可的哈希；列表由设备自己去抓取和解析。Lava **绝不**存储、镜像、转换或提供第三方拦截列表的字节内容。

每一行 `blocklist_sources` 都带着 `redistribution_mode`，它唯一允许的取值就是 `"source_url_only"`。设备读取的那份目录（`/v1/catalog`，`schema_version` 为 2）会把条目拆成 `sources[]` 和 `guardrails[]`；每个条目都带上游的 `source_url` 加上 `accepted_source_hashes`（SHA-256 + 字节大小 + 条目数 + `reviewed_at` + 状态 `accepted`）—— 从不带列表字节。见 `formatCatalogEntry`。

> **已放弃：** 早先有个设计是在 R2 里镜像保留字节的 GPL 列表文件（即 GPL-raw-R2 合规方案）。它在 **2026-05-25 被「只发 source-url」取代**。Lava 不再存储或提供第三方拦截列表的字节内容。`mirror_events` 这个表名是那个废弃设计留下来的老叫法 —— 现在它就只是同步/发布的审计日志而已。

### 3.2 Worker 在写入时如何落地这条规矩 {#32-how-the-worker-enforces-it-on-writes}

同步路径（`syncOneBlocklist`，管理端和 cron 都走它）会抓取每个上游 `source_url`，**只在 Worker 本地做归一化/校验，目的仅仅是算出元数据**（`entry_count`、`source_hash`、`normalized_hash`、`byte_size`），写一行 `blocklist_versions`，然后重新发布。那两个存字节的键被硬写成了 null：

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

有一个迁移（`20260525000000_add_blocklist_distribution_mode.sql`）把这些列改成了可空，并把已有的值都设成了 null，所以「不镜像」这条立场在表结构层面也被强制住了。发布出来的目录会**同时**写到 R2 的 `catalog/{version}.json` 和 `catalog/latest.json`（`publishCatalog`）。

### 3.3 归一化护栏（只算元数据） {#33-normalization-guardrails-metadata-only}

Worker 端的归一化（`normalizeBlocklist`）会过滤掉受保护的域名、强制各项上限，并去重 + 排序。这纯粹是为了算出可信的元数据；**设备在下载真正的列表时会重新校验已认可的哈希**，所以这本身并不是一道安全边界。几个关键常量：

- `PROTECTED_SUFFIXES` —— 把任何命中 Apple/iCloud/`mzstatic`/Lava Security 域名/Supabase/Cloudflare/Google/GitHub 的规则都剥掉，这样就算上游被投毒，也没法拦掉 Lava 自家的基础设施或登录服务商。
- `MAX_BLOCKLIST_BYTES = 25 MiB`、`MAX_BLOCKLIST_LINE_LENGTH = 2048`、`MAX_NORMALIZED_DOMAINS = 500_000`。

### 3.4 哪些来源能发布 {#34-what-is-publishable}

`isPublicBlocklistSource` 只在满足这些条件时才发布一个来源：`status` 是 `sync` 或 `nosync`、`redistribution_mode === "source_url_only"`，**而且** `isAllowedLaunchGPLSource` 通过。这道上线 GPL 门（`isAllowedLaunchGPLSource`）对非 GPL 来源不设限，但把 GPL-3.0 来源限制在 `list_id` 前缀为 `hagezi-` 或 `oisd-` 的范围内。

### 3.5 预置来源与默认启用 {#35-seeded-sources-default-enabled}

精选来源通过迁移以「只发 source-url」的元数据形式预置进来（HaGeZi、OISD、Block List Project、Phishing.Database、AdGuard）。那个低风险迁移（`20260526000000_low_risk_blocklist_sources.sql`）一开始把 `blocklistproject-basic`（Unlicense）设成了 `default_enabled = true`，并把**所有 GPL（HaGeZi/OISD）来源强制设成 `default_enabled = false`**，等待法务意见，同时把 AdGuard DNS Filter 暂搁在 `license_review`。**那次最初的「基础默认开」预置后来被取代了** —— 下面那个对齐迁移把基础翻成了 `false`，把钓鱼 + 诈骗翻成了 `true`（这就是当前对外提供的默认）。状态：**已实现**。

> **目录默认值和客户端对齐。** 目录的 `default_enabled` 集合现在是 **{Block List Project Phishing、Block List Project Scam}**，与 iOS 推荐的默认（`AppConfiguration.lavaRecommendedDefaults`，位于 `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`）一致。有个迁移把 `blocklistproject-basic default_enabled` 设成 `false`，把 `blocklistproject-phishing` / `blocklistproject-scam default_enabled` 设成 `true`，这样对外提供的元数据就如实反映现状了。（这个对齐决定现在已经上线。）注意 `default_enabled` 只是说明性的：真正的方案门是**过滤规则配额（免费方案 500K / Plus 200 万）**，不是列表数量。发布 URL（而非字节）的法律依据见 [GPL 只发 source-url 合规决定](../legal/gpl-source-url-only-compliance-decision.md)。

## 4. Supabase Postgres {#4-supabase-postgres}

一个 Supabase Postgres 项目。**每一张**公开表都开了 RLS。

### 4.1 核心表结构 {#41-core-schema}

`20260516034033_backend_core.sql` 搭起了地基（所有 7 张公开表都开了 RLS）：

- **`profiles`、`user_settings`、`entitlements`** —— 每个用户的账户状态。一个触发器 `handle_new_user()` 会在 `auth.users` 插入时自动建出 `profiles` + `user_settings` 行。
- **`blocklist_sources`、`blocklist_versions`** —— 目录元数据表。一个来源就是一份精选的上游列表（`list_id`、`source_url`、许可证、风险、`default_enabled`、`status`、`redistribution_mode`）；一个版本就是某次同步快照的元数据（哈希、`entry_count`、`byte_size`），通过 `latest_version_id` 反向关联回去。
- **`mirror_events`** —— 仅 service-role 可访问的审计日志，记 `sync` / `catalog_publish` 事件（老名字；见 §3.1）。
- **`bug_reports`** —— 仅 service-role 可访问的匿名报告。

后续的迁移又加了 **`user_backups`**（§4.3）和 **`qa_developers`**（`20260608000000_qa_developers_allowlist.sql`）。

### 4.2 RLS 模型 {#42-rls-model}

| 表 | 策略 | 效果 |
|---|---|---|
| `profiles`、`user_settings`、`entitlements`、`user_backups` | 按用户 `auth.uid() = user_id` | 每个用户只看得到自己的那些行 |
| `blocklist_sources` | 当 `status in ('sync','nosync')` 时公开可读（`backend_core.sql:262-266`） | 任何人都能读精选的、符合同步条件的来源 |
| `blocklist_versions` | 当 `validation_status = 'published'` 时公开可读（`backend_core.sql:268-272`） | 任何人都能读已发布版本的元数据 |
| `bug_reports`、`mirror_events` | 显式 `using(false)`（`20260516034136_backend_core_advisor_fixes.sql`） | 匿名/已登录用户都无法访问 —— Worker 用 service role |
| `qa_developers` | 开 RLS + **撤销 anon、authenticated 的所有权限** | 仅 service-role 可访问；QA 白名单永远不会被客户端读到 |

这种拆分很重要：匿名错误报告必须能被 Worker *写入*，但不能被客户端 *读取*；而 QA 白名单则必须只能由 service role 读到。

### 4.3 鉴权与加密备份信封 {#43-auth-the-encrypted-backup-envelope}

**鉴权**是可选的。登录**只支持 Apple + Google**（邮箱/密码已**放弃**）。两者都用原生的 `id_token` 授权，在 Supabase Auth 的 `auth/v1/token?grant_type=id_token` 用一个哈希后的 nonce 完成交换；App 只把得到的会话设备本地地存进 Keychain。客户端这套流程在 iOS App 里（`lavasec-ios: LavaSecApp/AccountAuthService.swift`、`lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`）—— 完整的账户/备份模型见 [账户与备份](./accounts-and-backup.md)。

> **零知识备份：** 客户端 AES-256-GCM 信封；只有密文 + 非机密元数据会上传到 Supabase 的 `user_backups`（按用户做 RLS）。没有用户手里的那个秘密，服务器没法解密。

这里最关键的后端事实是：**iOS 客户端通过 Supabase PostgREST、在按用户的 RLS 下直接读写 `user_backups`**（按 `user_id` upsert，由 access token 限定范围）。Worker 上**根本没有任何 `/v1/backup` 路由**。Worker 只碰 `user_backups` 一次：在账户删除时把它删掉（`deleteAccount`）。

`user_backups` 只存看不懂内容的密文 + 非机密的信封元数据（KDF 参数/盐、nonce、密钥槽标签、客户端结构提示）。大小上限（`20260605000000_tighten_backup_envelope_constraints.sql`）：密文 ≤ 262144 字节（256 KiB）/ ≤ 349528 字符，元数据 ≤ 32768 字节（32 KiB）。数据库从不存明文设置、密码、短语或密钥。

### 4.4 账户删除 {#44-account-deletion}

`POST /v1/account/delete` 校验用户的 access token，然后删掉他们的 `bug_reports`（以及任何匹配的遗留 R2 附件对象）、`user_backups`、`entitlements`、`user_settings` 和 `profiles` 行，最后通过 service-role 的 `/admin/users` 接口删掉 Supabase Auth 用户。它只返回一个已删除状态 + 关联的登录服务商。状态：**已实现**（计划文档的 frontmatter 写着 `status: Done`，文件就在 `plans/implemented/` 里；正文里还有一处过时的注释仍写着「Backlog」，但所在文件夹 + 代码确实存在，说明它已经上线了）。

### 4.5 App Store 权益镜像 {#45-app-store-entitlement-mirroring}

`POST /v1/account/entitlements/app-store-sync` 根据客户端已验证的 StoreKit 交易 JWS，按 `user_id` 冲突时 upsert 一行 `entitlements`（plan 为 `lava_security_plus`）。存下来的 `verification_status` 字面就是 `"client_verified_storekit"` —— 服务器**不会**重新验证这个 JWS。允许的 product ID：`lava_security_plus_{monthly,yearly,lifetime}`。

> 镜像**已实现**；**服务端 JWS 验证为计划中**（还没动工）。签名的 JWS 会被存下来以备日后验证。注意别处的方案模型：App 权益是本地的（`isPaid`），**目前还没有后端同步**作为唯一可信源 —— 这一行是个镜像，不是那道门。

## 5. 通行密钥辅助恢复（零知识） {#5-passkey-assisted-recovery-zero-knowledge}

通行密钥辅助的备份恢复是**零知识**的，完全在客户端完成。恢复密钥材料是在设备上、从通行密钥的 **WebAuthn PRF / hmac-secret** 输出派生出来的；服务器**不存**任何恢复秘密、**不注册**任何通行密钥、也**不签发**任何 WebAuthn 挑战。这里没有服务器把门的托管路径。

早先一个设计用过的托管表（`backup_passkey_recovery`、`backup_passkey_challenges`）在上线前就被删掉了，Worker 里没有任何 `/v1/backup/*` 路由，也没有任何 WebAuthn/通行密钥代码。（Worker 的 `package.json` 里还留着一个 `@simplewebauthn/server` 条目，那是个没用上的残留依赖。）

客户端这一侧在 iOS App 里：`lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` 负责驱动支持 PRF 的通行密钥创建/断言，`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` 从 hmac-secret 输出派生出密钥槽。PRF 输出只在断言时读取，从不离开设备。不支持 PRF 的通行密钥服务商撑不起一个零知识密钥槽，所以设置会早早失败，用户会退回到用恢复码。状态：**已实现**。

## 6. lavasec-email Worker {#6-lavasec-email-worker}

只收不转存。它把 `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` 转发到一个已验证的运营邮箱，拒收未知收件人和超过 10 MiB 的邮件，而且**不存邮件正文**。支持类自动回复代码写好了，但被卡在付费的 Cloudflare 出站邮件后面（暂缓）。路由常量在 `email-service.ts:9`（`ROUTED_RECIPIENTS`）；入站处理函数是 `handleInboundEmail`。状态：**已实现**（自动回复路径为**计划中**/暂缓）。

## 7. 配置与部署 {#7-config-deploy}

- **配置是 `wrangler.toml`，它被 gitignore 了**；`wrangler.toml.example` 才是提交进库的模板。对于和环境相关的取值，把本地那份 `wrangler.toml` 当作准绳。
- **Vars**（非机密，放在 `[vars]`）：Supabase URL、公开 API origin（`https://api.lavasecurity.app`）、目录缓存 TTL（默认 300 秒）、一个错误报告大小上限、一个账户删除审计开关，以及一个 Workers 运行时加速标志。内部错误报告分流还加了一个内部分流队列键，以及一个拼分流链接时用到的面板 origin。
- **Secrets**（经 `wrangler secret put`）：一个 Supabase service-role 凭证、一个管理 API key，以及 —— 为了错误报告分流路径 —— 一个 issue-tracker API key 和一个可选的聊天通知 webhook。
- **部署是手动的**：`npm run deploy` → `wrangler deploy`。Worker 没有 CI。
- **Cloudflare 路由**：`lavasecurity.app` 留在 Pages；`api.lavasecurity.app` 和 `*.qa-probe.lavasecurity.app` 解析到这个 Worker。
- **兼容性**：`compatibility_date = "2026-05-16"`、`compatibility_flags = ["nodejs_compat"]`。

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` 在 vars 里设了，但 Worker 代码并没有引用它；它是个 Workers 运行时加速标志，而不是应用层设置。

## 8. 隐私不变量（这里有什么、没什么） {#8-privacy-invariants-what-is-and-isnt-here}

给任何要扩展后端的人的一份快速清单 —— 下面这些一条都不能被悄悄打破：

1. **没有 DNS/浏览遥测。** 没有任何表记录日常 DNS 查询或逐域名的遥测。过滤始终留在设备上。
2. R2 或 Postgres 里**没有第三方拦截列表的字节内容** —— 只有 `source_url` + 已认可的哈希（§3）。
3. **`user_backups` 是看不懂内容的** —— 只有密文 + 非机密元数据；是客户端（而不是 Worker）在 RLS 下写入它（§4.3）。
4. **`bug_reports`、`mirror_events`、`qa_developers` 做 service-role 隔离**（§4.2）。
5. **所有备份路径都是零知识的** —— 包括通行密钥辅助恢复，它的密钥材料是在客户端从 WebAuthn PRF/hmac-secret 输出派生的。服务器不存任何恢复秘密，也不跑任何 WebAuthn（§5）。

## 另见 {#see-also}

- [系统总览](./system-overview.md) —— 一页看完整个系统，包括信任边界。
- [iOS 客户端](./ios-client.md) —— 消费这套后端的设备这一侧。
- [账户与备份](./accounts-and-backup.md) —— 客户端鉴权、AES-256-GCM 信封、密钥槽和恢复码。
- [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md) —— 目录的设备这一侧：直接从上游下载、解析/归一化，以及过滤规则配额。
- [GPL 只发 source-url 合规决定](../legal/gpl-source-url-only-compliance-decision.md) —— 为什么目录发布的是 URL 而不是字节。
- **方案分级与变现**（内部） —— 那个真正划分免费/Plus 的过滤规则配额（免费方案 500K / Plus 200 万）。
- **IP 风险登记册**（内部） —— 「只发 source-url」背后的 IP/合规依据。
