---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 系统总览 {#system-overview}

> **读者对象：** 工程师。这一页就是 Lava Security 的全貌——各个部件是什么、数据在它们之间怎么流动、信任边界落在哪里。各组件的单独文档会讲得更细；这一页存在的意义，是让你在读那些细节之前，先把整个系统装进脑子里。
>
> **以谁为准：** 当这份文档和某个方案（plan）对不上时，**以代码为准**。这里写的状态反映的是代码里确认过的现实，不是方案里的设想。详见页面底部的 [状态说明](#8-status-legend)。

## 1. 产品一句话 {#1-product-one-liner}

Lava Security 是一款隐私优先的 iOS App，它**在设备本地**通过 NetworkExtension 数据包隧道来过滤 DNS，替不太懂技术的人（家长、年长者）拦掉恶意和不想要的域名——核心防护永久免费，也不需要注册账户。

## 2. 隐私承诺（标准表述） {#2-the-privacy-promise-canonical}

> 所有 DNS 过滤都在设备上完成；Lava 从不把你的上网流量绕道它的服务器，也从不接收你访问过的那一串域名——后端只保存目录元数据、一份只属于你且别人看不懂的加密备份，以及你主动选择发送的匿名诊断信息。

下面写的一切，都是为了让上面这句话一直成立。这套架构在服务端这边是刻意做小的：活儿都由设备干，后端永远看不到任何一次查询。

## 3. 组件 {#3-components}

### iOS 客户端（三个可执行目标 + 共享代码，共用一个 App Group `group.com.lavasec`） {#ios-client-three-executable-targets-shared-code-one-app-group-groupcomlavasec}

| 组件 | Bundle / 位置 | 角色 | 状态 |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | SwiftUI App 外壳；入口点，两个标签页的 防护 + 设置 导航（过滤器/活动是 防护 下的详情页；网络活动已挪到 设置 → 高级 下）。 | 已实现 |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`；设备端的 DNS 过滤/解析引擎。受 iOS **每个扩展约 50 MiB 的内存上限**约束。 | 已实现 |
| **LavaSecWidget** | `com.lavasec.app.widget` | WidgetKit 实时活动（锁屏 + 灵动岛）。 | 已实现 |
| **Shared/** | `Shared/` | 跨目标的共享源码：App Group、命令服务、吉祥物、实时活动属性/意图。 | 已实现 |

**App 侧的控制器（在 LavaSecApp 里）：**

- **AppViewModel** — App 侧的控制器（万能对象）：负责 `NETunnelProviderManager` 的生命周期、共享状态的持久化、provider 消息收发、实时活动对账、目录同步、备份、StoreKit 和身份认证。
- **RootView** — 两个标签页的 `TabView`（防护 + 设置），过滤器和活动作为 防护 下的详情页进入；它把控引导流程，承载安全锁 / 隐私遮罩这些覆盖层。
- **SecurityController** — 密码（Keychain 里加盐的 SHA256）+ 生物识别 + 按界面分别防护。
- **LavaLiveActivityController** — 单一活动对账器，做了去重并按 revision 把关。
- **OnboardingFlowView** — 多页的首次启动流程（6 页：`lava → guardIntro → features → vpn → notifications → done`）。

**LavaSecCore（与平台无关的 SwiftPM 包，`Sources/LavaSecCore/`）：**

- **FilterSnapshot / CompactFilterSnapshot** — 编译好的过滤器 + 判定优先级；其中紧凑形式是隧道读取的、对 mmap 友好的磁盘上产物。
- **DNSQueryDispatcher** — 查询优先级：bootstrap > pause > filter。
- **ResolverOrchestrator** — 传输路由、明文 DNS 降级、按端点逐个故障转移、回退到设备 DNS。
- **DoHTransport / DoTTransport / DoQTransport** — 加密传输执行器。
- **FeatureLimits**（在 `SubscriptionPolicy.swift` 里）— 各档位上限（事实来源），通过静态成员 `.free` / `.paid` 提供。
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — 设备护栏的算账逻辑 + 合并后权威的额度强制执行。
- **BlocklistCatalogSync / BlocklistParser** — 目录拉取、直接从上游下载、本地解析/规整/去重、过滤掉受保护的域名。
- **GuardianMascotAnimation** — 7 个状态的吉祥物状态图（由 `Shared/SoftShieldGuardian` 渲染）。
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — 备份加密 + 载荷。
- **SupabaseIDTokenAuth** — 直接用原始 URLRequest 做 `id_token` 认证（不用 SDK）。

### 后端 {#backend}

| 组件 | 角色 | 状态 |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker（`api.lavasecurity.app`）：目录读取、管理/定时任务的拦截列表同步 + 发布、匿名错误报告、账户删除、App Store 权益镜像、QA 探测。 | 已实现 |
| **lavasec-email Worker** | 只收不发的 Cloudflare 邮件路由转发器，负责 `@lavasecurity.app`；拒收未知或超大的邮件。 | 已实现 |
| **Supabase Postgres** | 账户、`user_backups`、目录元数据、仅 service-role 可访问的表；**每张 public 表都开了 RLS**。 | 已实现 |
| **Cloudflare R2**（生产 R2 桶，外加一个给预发布用的独立 preview 桶） | 目录快照 + 轮询同步游标。**绝不**存第三方拦截列表的字节；错误报告附件的上传路由已被移除（遗留对象只在账户删除时清理）。 | 已实现 |
| **Cloudflare D1**（帮助页反馈数据库） | 只追加写入的匿名帮助文章反馈投票。 | 已实现 |

## 4. 数据流图 {#4-data-flow-diagram}

最重要的一条性质：**加密 DNS 解析路径（右侧）从不碰 Lava 的后端（底部）。** 设备会从 Worker 拉取目录*元数据*，但列表的*字节*和真正的查询流都是直接发给第三方的。

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

## 5. 数据流向 {#5-data-flows}

### A. DNS 路径（每次查询，全在设备上）— 已实现 {#a-the-dns-path-per-query-all-on-device-implemented}

这是热路径，也是隐私的核心。它完全跑在 `LavaSecTunnel` 内部；这里没有任何东西会到达 Lava 的服务器。

1. 数据包隧道拦下一次 DNS 查询（隧道 DNS 服务器 `10.255.0.1`）。
2. **`DNSQueryDispatcher`** 套用查询优先级：**bootstrap > pause > filter**。bootstrap 优先是一条硬性不变量——解析器自己的主机名要在任何过滤之前先解析出来，这样解析器永远不会把自己拦掉。
3. 如果既不是 bootstrap、也没有处于暂停，域名就会拿去和 **`CompactFilterSnapshot`** 比对（通过 `Data(contentsOf:options:[.mappedIfSafe])` 从 App Group 以零拷贝 mmap 加载）。判定优先级是 **威胁护栏 > 本地允许列表（允许例外） > 拦截列表 > 默认放行**；无效域名一律拦截。
4. **被拦截** → 隧道在本地直接给出应答（不联系上游）。**被允许** → 这次查询交给 **`ResolverOrchestrator`**。
5. `ResolverOrchestrator` 把它路由到配置好的传输方式——**`DoH3` / `DoT` / `DoQ` / 明文 DNS（`IP`）**——在退避门控的背后按端点逐个做故障转移；当一个加密方案没有任何端点时降级为明文 DNS；当主端点没有应答、且方案允许时，**回退到设备 DNS**。
6. 解析器的回复返回给操作系统。用户的查询流只去往**用户自己选的公共解析器**，绝不去 Lava。

传输方式说明（照搬约定）：**只有真正观察到一次 h3 协商时**才会标注 `DoH3`（不带斜杠）——优先尝试，绝不保证。**`DoT`** 每个端点最多缓存 4 个 NWConnection，带空闲过期刷新 + 一次新连接重试。**`DoQ`** **每次查询都开一条全新的 QUIC 连接**（不复用）；那 4 条通道的缓存池给的是并发，不是握手复用——连接复用做出来过、在真机上测过、但**被回退了**（推迟到 iOS-26 成为部署下限之后再说）。详见 [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md)。

### B. 目录拉取 + 拦截列表加载（仅源 URL）— 已实现 {#b-catalog-fetch-blocklist-load-source-url-only-implemented}

过滤规则是怎么到设备上的。Lava 是一个**仅源 URL**的分发方：它只发布上游 URL + 认可的哈希，**从不存储、镜像、转换或托管第三方拦截列表的字节。**

1. 设备从 Worker 拉取目录**元数据**：`GET https://api.lavasecurity.app/v1/catalog` → 直接从 R2（`catalog/latest.json`）提供的 JSON，拆成 `sources[]` + `guardrails[]`，每一项都带着 `source_url` + `accepted_source_hashes`。
2. 对每个启用的源，设备**直接从 `source_url`**（也就是上游——HaGeZi、OISD、Block List Project 等等）下载列表**字节**，**而不是**从 Lava 下载。
3. 设备在大小/规则上限之下本地解析拉取到的字节。社区列表只要是通过 TLS 提供的就会被接受——目录里的 `accepted_source_hashes` 只是参考性的（缓存身份 + 审计用），不是硬性闸门——所以一个轮换过的列表绝不会因为偏离某个钉死的哈希而被拒。Lava 的威胁护栏档位则保持哈希钉死。
4. **`BlocklistParser`** 在本地解析/规整/去重（auto / plain / hosts / adblock / dnsmasq 格式），然后 **`DomainRuleSet.lavaSecProtectedDomains`** 剥掉受保护的域名（apple.com、icloud.com、lavasecurity.com/.app、google.com、accounts.google.com 等），这样上游列表永远不可能拦掉 Lava/Apple/身份提供商的域名。
5. **`FilterSnapshotPreparationService`** 把去重后的并集合并起来，并跑一遍**权威的额度强制执行**（先看设备上限，再看档位），然后把 `filter-snapshot.compact` 写进 App Group。
6. `AppViewModel` 发出一条 `reload-snapshot` provider 消息；隧道重新加载。

Worker 那边是对称的：它的管理/定时任务同步会拉取每个上游、对它做哈希/计数、写入 `raw_r2_key = null` / `normalized_r2_key = null`，然后只重新发布元数据。拦截列表目录模型和后端同步路径在 [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md) 和 [后端与数据](./backend-and-data.md) 里有讲。

**额度模型（两层）：**
- **设备护栏（人人有份，永远不是付费墙）：** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3,262,236 条规则** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule`——在 ~50 MiB 的 NE 上限之下设定的 32 MB 目标。超额的配置会被确定性地拒绝，而不是放任隧道被系统 jetsam 杀掉。
- **档位上限（`FeatureLimits`）：** **免费 50 万条规则 / Plus 200 万条规则**，这个值卡在设备护栏之下。它取代了旧的按启用列表**数量**来卡的上限（免费 3 个 / 付费 10 个）——列表数量上限已经作废。

> **默认启用的事实来源：** 出厂的免费默认值是 **Block List Basic**（`OnboardingDefaults.lavaRecommendedDefaults`）。它是在设备上从每个精选源的 `defaultEnabled` 标志推导出来的（`BlocklistSource.recommendedDefaultSourceIDs`），这个标志与后端目录的 `default_enabled` 列保持一致，而该列又是从同一份标准目录规范生成的。

### C. 备份（零知识，需主动开启）— 已实现 {#c-backup-zero-knowledge-opt-in-implemented}

可选、需要账户、是唯一会落到后端的用户数据——而且是以**别人看不懂的密文**形式。

1. 用户可以选择登录（只支持 Apple 或 Google；**邮箱/密码已放弃**），通过原生 `id_token` 在 Supabase Auth 处兑换（`grant_type=id_token`，哈希过的 nonce）。只有兑换出来的 Supabase 会话会被存下来，存在设备本地的 Keychain 里。
2. **`BackupConfigurationPayload`** 拼出一份精简的明文（启用的拦截列表 ID、允许/已拦截的域名、解析器偏好、本地日志偏好、LavaGuard 记录）。它**不包含** `isPaid`、QA、诊断信息和完整的拦截列表。
3. **`ZeroKnowledgeBackupEnvelope`** 用一个随机的 32 字节载荷密钥、以 **AES-256-GCM** 把它封住；那个密钥再通过 **PBKDF2-HMAC-SHA256（21 万次迭代）** 包进按密钥分的**密钥槽**——设备密钥槽、辅助恢复槽、可选的通行密钥槽。可选的通行密钥槽是用认证器的 **WebAuthn PRF / `hmac-secret`** 输出（经 HKDF 派生）来包裹的；那个输出从不离开客户端，所以通行密钥槽是真正的零知识——没有任何服务器持有的值能解开它（`ZeroKnowledgeBackupEnvelope.makeWithPRF`）。
4. **`BackupSyncService`** **只把密文 + 非机密的元数据**通过 PostgREST 直接上传到 Supabase 的 `user_backups`，并按用户用 **RLS** 隔离。（没有 Worker 上传路由；Worker 碰 `user_backups` 只是为了在账户删除时把它删掉。）
5. **恢复：** 同设备上通过设备密钥槽无缝还原；换设备时通过 **8 词的 CVCV 恢复码**（约 105 位）配合服务器持有的恢复分片、用 SHA256 组合起来（双因子——任何一半单独都解不开）；或者，当封进过通行密钥槽时，通过客户端侧的 WebAuthn PRF / `hmac-secret` 输出来恢复（不涉及任何服务器持有的值）。服务器从不注册通行密钥、不签发 WebAuthn challenge、也不存任何恢复秘密。

详见 [账户与备份](./accounts-and-backup.md)。

### D. App ↔ 扩展 控制平面 — 已实现 {#d-app-extension-control-plane-implemented}

三个进程（App、隧道、Widget）通过 App Group `group.com.lavasec` 协调：

- **控制 = NETunnelProviderSession 的 provider 消息**，**而不是** Darwin 通知。`AppViewModel` 编码一条 `LavaSecProviderMessage {kind, operationID}` 并调用 `session.sendProviderMessage`；隧道的 `handleAppMessage` 按 kind 分支处理（`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`）。
- **共享文件**承载规则/配置/健康状态（`filter-snapshot.compact`、`app-configuration.json`、`tunnel-health.json`）；**共享的 UserDefaults 存储**（`ProtectionSessionStore` / `ProtectionPauseStore`）承载会话 + 暂停状态。
- **`LavaProtectionCommandService`** 在一把 `flock` 文件锁之下执行 实时活动 / AppIntent 的暂停/恢复命令，带 revision 去重和「需要认证则拒绝」；**重新连接会绕过它**，直接重启隧道（`startVPNTunnel`）。
- **按需连接（Connect-On-Demand）**只会在隧道确认已连接*之后*才开启，绝不在装配置文件时就开——这样一份刚装好的引导配置文件就不会拉起一条关不掉的隧道。

详见 [iOS 客户端](./ios-client.md)。

## 6. 信任边界与隐私保护设计 {#6-trust-boundaries-privacy-preserving-design}

| # | 边界 | 什么会穿过它 | 什么是刻意不让穿过的 |
|---|---|---|---|
| 1 | **设备 ↔ 公共 DNS 解析器** | 被允许的 DNS 查询（加密：DoH3/DoT/DoQ，或明文 IP）发给用户自己选的解析器。 | Lava 从不看到查询流；它根本不在这条路径上。 |
| 2 | **设备 ↔ 上游拦截列表主机** | 设备直接从 `source_url` 下载列表字节。 | Lava 从不代理、镜像或存储第三方拦截列表的字节。 |
| 3 | **设备 ↔ lavasec-api Worker** | 目录**元数据**读取；可选的匿名错误报告；权益镜像；账户删除。 | 没有 DNS 查询、没有浏览历史、没有明文设置。 |
| 4 | **设备 ↔ Supabase** | 可选的**加密备份信封**（只有密文，PostgREST 在 RLS 之下）；账户行。 | 没有用户持有的秘密，服务器解不开这份备份。 |
| 5 | **App ↔ 隧道扩展**（设备上） | provider 消息 + App Group 的文件/默认值。 | 冷启动时若没有可复用的快照，隧道会**失败关闭**。 |

**隐私保护设计原则，落在上面这些事实之上：**

- **本地优先过滤。** 判定引擎和解析器都跑在设备上的 NE 扩展里。后端从设计上就只有元数据——没有任何表用来存放日常的 DNS 查询或按域名的遥测。
- **防护不需要账户。** 核心防护永久免费；认证和备份严格按需开启。
- **仅源 URL 的分发方式。** 把 Lava 和第三方列表字节解耦（兼顾 GPL/知识产权合规 + App 审核安全），并保留一道 CI 护栏，强制执行「没有镜像代码、没有 Lava 制品 URL、没有往 R2 写字节」。
- **静态零知识备份。** 客户端侧的 AES-256-GCM；服务器持有的是密文 + KDF 元数据 + 一个恢复分片，永远不会有明文、恢复码或解开后的密钥。可选的通行密钥槽是用客户端侧的 WebAuthn PRF / `hmac-secret` 输出包裹的，所以它同样是零知识——没有任何服务器持有的值能解开它。
- **设备本地的秘密。** 备份解锁材料用的是 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`——不走 iCloud 同步，也不进设备备份。
- **service-role 隔离。** `bug_reports`、`mirror_events` 和 `qa_developers` 对匿名/已认证的 PostgREST 角色都已撤权；只有 Worker（service role）能碰它们。
- **安全永远不卖钱。** 付费解锁的**只是定制能力**。它绝不绕过不可放行的**威胁护栏**，而护栏的完整性是靠认可的 SHA256 源哈希来保证的（不是服务器签名）。优先级处处一致：**威胁护栏 > 本地允许列表（允许例外） > 拦截列表 > 默认放行。**

## 7. 各组件文档 {#7-per-component-docs}

> 这些是架构文档集里的同级文档。DNS 过滤引擎和拦截列表目录被放在同一个文件里一起写。

- [iOS 客户端](./ios-client.md) — 目标、App Group、控制平面、防护状态模型、引导流程、实时活动。
- [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md) — 过滤快照、判定优先级、解析器传输方式（DoH3/DoT/DoQ）、内存额度、mmap；外加仅源 URL 的目录模型、目录拉取、本地解析/规整、受保护域名过滤、以及档位额度。
- [账户与备份](./accounts-and-backup.md) — Apple/Google 认证、零知识信封、密钥槽、恢复码、客户端侧 WebAuthn-PRF 的通行密钥恢复。
- [后端与数据](./backend-and-data.md) — lavasec-api + lavasec-email Worker、Supabase 表结构 + RLS、R2/D1、部署。

## 8. 状态说明 {#8-status-legend}

整套文档集用同一套状态词汇。**lane 文件夹是状态的权威来源**；方案里过期的 frontmatter 是文档 bug，不算状态。**代码盖过方案。**

| 状态 | 含义 | 方案 lane | 代码 |
|---|---|---|---|
| **已实现** | 已发布并在代码里确认 | `plans/implemented/` | 存在且已接好线 |
| **进行中** | 正在积极开发；部分已落地 | `plans/inflight/`、`plans/under_review/` | 部分存在 |
| **计划中** | 已设计，尚未构建 | `plans/backlog/` | 缺席 |
| **已放弃** | 被否决或被回退 | `plans/dropped/`（或被回退的提交） | 缺席 / 已移除 |

**本页提到的各项的状态：**

- **已实现：** 四个 iOS 目标 + App Group；provider 消息的控制平面；设备端 DNS 过滤，带 DoH3/DoT/DoQ/IP 传输方式；仅源 URL 的目录拉取 + 本地解析；过滤规则额度（免费 50 万 / Plus 200 万）+ 约 326 万的设备护栏；多页引导流程；密码/生物识别安全；单条去重过的实时活动；零知识备份；Apple + Google 认证；账户删除；权益镜像；QA 探测；`LavaDesignSystem` 令牌层（`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`），包括 `LavaTier` 深度模型（Floor/Window/Workshop = `calm`/`celebratory`/`technical`）、接进代表性界面（例如 `SettingsView`）的 `.lavaTier(_:)` / `.lavaTierMetadata()` 修饰符，以及 `dangerRed` 和 `LavaSpacing` 令牌——由 `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift` 锁定。
- **进行中：** 把设计系统的令牌层继续铺到更多界面上（`LavaTier` 深度模型和令牌层已经发布——见下文——但还没有专门的 `LavaColorRole`，所以强调色目前仍解析到原始颜色）。
- **计划中：** Lava Guard 彩蛋小游戏；额外的吉祥物表情（吉祥物正好有 **7** 个状态）；在实体设备上完全可上线的通行密钥恢复（Associated Domains / AASA）；服务端的 App Store JWS 二次校验（`verification_status` 目前是 `client_verified_storekit`）；一个专门的 `LavaColorRole` 令牌，让设计系统的强调色走一个语义角色、而不是原始颜色来解析。
- **已放弃：** DoQ 连接复用（改为每次查询都开新连接）；邮箱/密码登录（只留 Apple + Google）；GPL 的 raw-R2 镜像设计（被仅源 URL 方案取代）。
