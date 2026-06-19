---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 功能清单 {#feature-catalog}

> 读者对象：产品经理 / 工程师。这份清单只涵盖**当前已经做出来、已经上线**的功能。那些只画在图纸上、还没动手做的，都放在内部路线图里，不在这儿。

Lava Security 是一款隐私优先的 iOS App，它通过 NetworkExtension 的数据包隧道，**就在你手机本地**完成 DNS 过滤，替不太懂技术的人（比如家长、长辈）拦掉恶意和不想要的域名——核心防护永久免费，也不用注册账户。

下面每一项功能背后，都是同一个隐私承诺：

> 所有 DNS 过滤都在你的设备上完成；Lava Security 绝不会把你的浏览流量绕到自己的服务器，也绝不会拿到你访问过哪些域名的记录——后端手里只有目录元数据、一份看不懂内容的、按用户加密的备份，以及你自己选择发送的匿名诊断信息。

## 怎么读这份清单 {#how-to-read-this-catalog}

- **免费** —— 所有人都能用，不用账户，不用花钱。
- **Plus** —— 由 Lava Security Plus 解锁，这是唯一一个可选的付费档。Plus 只解锁**自定义功能**；它从不限制基础安全防护，也绝不会让付费用户绕过安全护栏。
- 除非那一行单独标了别的，否则每一项都是**已实现**。状态说明：**已实现** = 已上线并在代码里确认过；**计划中** = 已设计，还没做；**已放弃** = 被否决或回退掉了。计划中／已放弃的内容记在内部路线图里，不在这儿。

各档位的真正上限，源头在 `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`（`FeatureLimits.free` / `FeatureLimits.paid`，别名是 `.plus`）。Plus 权益的**开关**是一个本地标记（`isPaid`）——这才是真正说了算的。后端会**同步**一份 App Store 的权益（`POST /v1/account/entitlements/app-store-sync` 会写入一行 `entitlements`），但那一行只是个副本，不是开关；目前还没有任何后端同步会驱动权限控制。

---

## 1. 防护与 VPN {#1-protection--vpn}

这是产品的核心：一条只走 DNS 的本地数据包隧道，以及围绕它的那套从容的状态模型。

| 功能 | 档位 | 说明 |
|---|---|---|
| **只走 DNS 的本地数据包隧道** | 免费 | `LavaSecTunnel`（`NEPacketTunnelProvider`，`com.lavasec.app.tunnel`）拦下 DNS，在设备上逐个判断每个域名。浏览流量不会经过 Lava Security。隧道地址 `10.255.0.2`，DNS 服务器 `10.255.0.1`。 |
| **过滤判定的优先级** | 免费 | `安全护栏拦截 > 本地允许列表（允许例外）> 拦截列表 > 默认放行`；无效域名一律拦截。（`FilterSnapshot.decision()`。） |
| **查询优先级（解析器优先）** | 免费 | `解析器引导 > 临时暂停 > 过滤`——解析器自己的主机名永远不会被拦。（`DNSQueryDispatcher`。） |
| **冷启动时安全失效保护** | 免费 | 冷启动的隧道如果没有可复用的快照，就装上一份 `FailClosedRuntimeSnapshot`，宁可把所有流量都拦住，也不放出没过滤的 DNS。 |
| **按需连接（Connect-On-Demand）** | 免费 | `NEOnDemandRuleConnect` 让防护一直在线／自动重启——只在**确认连上之后**才启用，绝不在安装配置文件时就启用，并且在引导没走完的时候会被中和掉，这样新装的 App 不会冒出一条你关都关不掉的隧道。 |
| **临时暂停（5 / 10 分钟）+ 恢复** | 免费 | 暂停／恢复都走 `LavaProtectionCommandService`，用 flock 文件锁加修订号去重。 |
| **暂停需要验证身份** | 免费 | 可按每个界面单独开启的开关（`SecurityProtectedSurface.protectionPause`）：暂停时需要本地设备验证；没验证的暂停会被命令服务拒掉，实时活动也会把暂停按钮藏起来。 |
| **重新连接** | 免费 | 直接重启隧道（绕过命令服务那套暂停流程）。 |
| **岩酱柔盾状态模型** | 免费 | 7 种表情状态——`sleeping, waking, awake, paused, retrying, concerned, grateful`（`GuardianMascotAnimation.swift`，LavaSecCore）。6 种连接状态严重度收拢成 4 张脸；在 App 里、引导里、实时活动里渲染得一模一样。 |
| **连接状况评估** | 免费 | 6 种严重度（`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`）决定岩酱的表情和状态文案。 |
| **性能优化** | 免费 | 缓存优先开启、合并进行中的查询、有上限的并行抓取、抖动合并（按模块化提速那项工作的测量，热开启在 iPhone 15 Pro 上约 112 毫秒）。 |

> **设备护栏（人人都有，绝不是付费墙）：** 对所有用户、不分档位都强制一个硬上限 `约326万条规则`（在 iOS `约50 MiB` 的单扩展内存上限下，常驻内存目标为 32 MB）（`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`，`maxFilterRuleCount`）。超预算的配置会被确定性地拒掉（`exceedsDeviceMemoryBudget`），而不是放任隧道被系统强杀。

---

## 2. 拦截列表与过滤 {#2-blocklists--filtering}

哪些会被拦、列表怎么选，以及档位的分界线。

| 功能 | 档位 | 说明 |
|---|---|---|
| **只发布来源 URL 的拦截列表** | 免费 | Lava Security 只发布上游 URL 加上认可的哈希值；列表的**字节内容**由设备自己去抓、自己去解析。Lava Security **绝不**存储、镜像、转换或分发第三方拦截列表的字节。详见 [GPL 只发布来源 URL 的合规决定](../legal/gpl-source-url-only-compliance-decision.md)。 |
| **精选目录（10 个来源）** | 可免费启用 | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift`（`DefaultCatalog.curatedSources`）：Block List Basic、Block List Project Phishing / Scam / Ransomware、Phishing.Database Active Domains、HaGeZi Multi Light / Normal / PRO mini / PRO、OISD Small。 |
| **默认免费拦截列表** | 免费 | 新装的 App 会启用 **Block List Project Phishing + Scam**（这两个来源标了 `defaultEnabled: true`；`DefaultCatalog.recommendedDefaultSourceIDs`）。 |
| **在设备上解析／规范化／去重** | 免费 | `BlocklistParser` 支持 auto/plain/hosts/adblock/dnsmasq，会丢掉注释／空行／无效项，对完全相同的字符串去重，每个列表最多 1,000,000 条规则。 |
| **上游字节校验** | 免费 | 抓回来的字节会算 SHA-256，只有校验值在目录的 `accepted_source_hashes` 里才接受；对不上时，Lava Security 会退回上一份正常的缓存，或者安全失效（全部拦住）。 |
| **受保护域名过滤** | 免费 | 每个解析出来的来源都会剔除掉受保护的 Lava Security / Apple / 身份提供方域名（apple.com、icloud.com、lavasecurity.app、google.com、accounts.google.com……），这样上游列表就没法搞坏 App、隧道或登录。 |
| **允许例外（允许列表）** | 免费 | 由用户管理的允许列表，让某些域名即便在拦截列表里也能放行。免费上限：10 个允许的 / 10 个已拦截域名（`FeatureLimits.free`）。 |
| **过滤规则配额（档位指标）** | 免费 / Plus | 上线的档位指标是编译后的域名**规则**总数：**免费 50 万 / Plus 200 万**（`lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` 里的 `maxFilterRules`）。取代了原先按列表数量算的上限。超档的配置会冒出 `exceedsTierFilterRuleLimit`。 |
| **更高的域名上限** | Plus | 500 个允许的 / 500 个已拦截域名（`FeatureLimits.plus`）。 |
| **自定义拦截列表** | Plus | `allowsCustomBlocklists`。自定义列表在设备上抓取和解析，本地缓存，绝不会代理到 Lava Security 的服务器。 |
| **热启动产物复用** | 免费 | 靠一份清单加上身份指纹，隧道可以直接复用磁盘上的紧凑快照，不用重新编译；当输入变了，复用会被拒绝（理由只给字段名，保护隐私）。 |

> 真正说了算的配额检查在编译期对去重后的并集运行（`FilterSnapshotPreparationService`）；先查设备上限，再查档位上限。选择时界面上那个进度条用的是各列表的累加值，再留 1.10 的软上限余量。

---

## 3. 加密 DNS {#3-encrypted-dns}

没被拦下的查询，用什么传输方式、怎么路由。

| 功能 | 档位 | 说明 |
|---|---|---|
| **五种解析器传输方式** | 免费 | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic`（`DNSResolverTransport`）。 |
| **DoH / DoH3** | 免费 | 基于 URLSession 的 DoH，优先用 HTTP/3。界面上**只有在真的观察到 h3 协商成功时**，才会标注 **`DoH3`（没有斜杠）**，比如「Quad9 (DoH3)」——这是优先尝试，从不承诺（`DoHTransport`）。 |
| **DoT** | 免费 | 用连接池里的 `NWConnection`（每个端点最多 4 条），带空闲过期刷新和一次新建连接重试。 |
| **DoQ**（仅自定义） | Plus | DNS-over-QUIC **没有内置预设**——只能通过**自定义的 `doq://` 解析器**用到，而自定义 DNS 是 Plus 功能。它**每次查询都新开一条 QUIC 连接**（4 条通道的连接池给的是并发，不是握手复用）；连接复用要等 iOS-26 作为部署底线后再做。 |
| **预设解析器** | 免费 | Device DNS（默认）、Google Public DNS、Cloudflare 1.1.1.1、Quad9 Secure、Mullvad——在提供的地方分 IP / DoH / DoT 几种变体（`DNSResolverPreset.allPresets`）。 |
| **解析器路由与故障切换** | 免费 | `ResolverOrchestrator` 按传输方式路由，当某个加密方案没有可用端点时降级为普通 DNS，再按端点逐个故障切换（带退避闸门），最后退回 device-DNS。 |
| **退回设备 DNS** | 免费 | 当所选解析器不可用时，退回到当前网络自己的解析器；**默认开启**。表现为 `usingDeviceDNSFallback` 这个严重度。 |
| **自定义 DNS** | Plus | `allowsCustomDNS` —— 用户自己填的解析器（自定义预设还支持解析 DNS-stamp）。 |

---

## 4. 账户与零知识备份 {#4-accounts--zero-knowledge-backup}

可选的账户登录和加密的设置备份。这些都不是用防护的必要条件。

| 功能 | 档位 | 说明 |
|---|---|---|
| **可选的账户登录（Apple + Google）** | 免费 | 原生 id_token 流程，在 Supabase Auth 处兑换（`grant_type=id_token`），带一个哈希过的 nonce；只有兑换出来的 Supabase 会话会本地存在 Keychain 里。邮箱／密码登录是有意不提供的（已放弃）。 |
| **零知识加密备份** | 免费 | 客户端 AES-256-GCM 信封；随机的载荷密钥被包进 PBKDF2-HMAC-SHA256（21 万次迭代）的密钥槽里。只有密文加上非机密的元数据会上传到 Supabase `user_backups`（按用户做 RLS）。没有用户自己手里的密钥，服务器解不开。 |
| **精简过的备份载荷** | 免费 | 备份已启用的拦截列表 ID、允许／已拦截域名、解析器设置、本地日志偏好、岩酱外观等等——并且明确**不**包含 `isPaid`、QA 标记、诊断信息、快照和完整的拦截列表字节。 |
| **设备密钥槽** | 免费 | 在仅限本机的 Keychain 里放一个 32 字节的设备密钥（`...ThisDeviceOnly`，不同步到 iCloud），用来在同一台设备上无感恢复。 |
| **恢复码 + 协助恢复** | 免费 | 一串 8 个词的 CVCV 短语（约 105 位），通过 SHA256 与服务器持有的一份恢复分片组合起来，解锁协助恢复槽。两个因素：单凭哪一半都解不开。 |
| **通行密钥恢复槽** | 免费 | 可选的、由 WebAuthn 把关的密钥槽，而且是**零知识**的：它的解包密钥是**在设备上**从认证器的 WebAuthn PRF（`hmac-secret`）输出派生出来的（HKDF-SHA256）。服务器不注册任何通行密钥、不发起任何挑战、不持有任何恢复密钥，也不暴露任何通行密钥相关接口——早先那套服务器托管的设计已经放弃了。在实体设备上的生产可用性，取决于 Associated Domains / AASA 托管（计划中）。 |
| **账户删除 / 数据权利** | 免费 | 经过身份验证的 Worker 接口会删掉备份、设置、权益、个人资料和错误报告附件，然后删掉 Supabase Auth 用户；App 随即登出并清掉本地的解锁材料。 |

---

## 5. 小组件与实时活动 {#5-widget--live-activity}

锁屏和灵动岛上的呈现。

| 功能 | 档位 | 说明 |
|---|---|---|
| **实时活动** | 免费 | `LavaSecWidget`（`com.lavasec.app.widget`）：锁屏和灵动岛上的一个 `Activity<LavaActivityAttributes>`（展开时居中 / compactLeading 显示岩酱 / compactTrailing + 最小化的状态图标）。 |
| **5 种状态的防护显示** | 免费 | `ProtectionState`：`on, paused, reconnecting, needsReconnect, networkUnavailable`——每种都对应一个岩酱姿势、一个 SF Symbol 和一个标题。 |
| **实时活动操作按钮** | 免费 | 暂停 5 / 10 分钟、恢复、重新连接——这些 `LiveActivityIntent` 会在 App 进程里通过 `LavaProtectionCommandService` 运行。需要验证身份的暂停变体要先做本地设备验证。 |
| **去重、按修订号把关的单一对账** | 免费 | `LavaLiveActivityController` 只保留一个 Activity，只在 id／内容真正变了时才更新，并且按 `ProtectionPauseStore` 的修订号给更新把关，这样过期的意图重试就没法把状态拉回旧值。 |
| **实时活动开关** | 免费 | 在设置里可由用户开关（`setUsesLiveActivities`），仅在 iPhone/iPad 上提供。 |

---

## 6. 引导流程 {#6-onboarding}

首次运行的流程，它会装好本地 VPN 配置并设好合理的默认值。

| 功能 | 档位 | 说明 |
|---|---|---|
| **多页首次运行流程** | 免费 | `OnboardingFlowView` —— 6 个页面：`lava, guardIntro, features, vpn, notifications, done`。（配置文件安装和通知请求都安排在合适的那一步，不会一上来就弹。） |
| **安装本地 VPN 配置文件** | 免费 | 在引导期间装好本地 VPN 配置，但**不**启用按需连接，这样完成时防护绝不会悄悄自动开着——以防护界面为准。 |
| **请求通知权限** | 免费 | 在流程中的通知那一步请求。 |
| **应用推荐的默认值** | 免费 | Device DNS 解析器、退回设备 DNS 开启、本地日志开启（计数 + 历史 + 活动）、Block List Project Phishing + Scam 启用、不使用账户继续（`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`，`lavaRecommendedDefaults`）。 |

---

## 7. 设置 {#7-settings}

配置、安全、诊断和反馈相关的界面。

| 功能 | 档位 | 说明 |
|---|---|---|
| **App 解锁密码 + 生物识别** | 免费 | `SecurityController`：Keychain 里加盐的 SHA256 密码校验器 + `LAContext` 生物识别，配上 App 解锁时的遮挡层，以及在场景阶段切换时的隐私遮罩。 |
| **按界面的防护** | 免费 | `SecurityProtectedSurface` 给六个界面把关：`appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`。每个都能单独要求本地设备验证（比如设置标签页就返回 `.requires(.appSettings)`）。 |
| **Lava Guard 外观选择器（7 种外观）** | 免费 | `GuardianShieldStyle`：`original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`，每种都配一个对应的灵动岛图标颜色。 |
| **匹配 App 图标** | 免费 | 可选的备用 App 图标，与所选岩酱外观相配。 |
| **外观** | 免费 | 浅色／深色／跟随系统的配色方案。 |
| **仅本地的日志控制** | 免费 | 过滤计数、域名历史（诊断）和网络活动的开关——全都存在设备上。 |
| **报告 / 活动（防护详情）** | 免费 | 动态的、仅本地的诊断：拦截／允许计数、隧道健康状况、热门域名。只有在打开了历史记录的情况下，域名那几行才会出现。从防护标签页进入的一个详情页（`GuardDestination.activity`）。 |
| **过滤器（防护详情）** | 免费 | 概览优先的过滤界面，带已拦截域名 / 允许例外的详情，以及一套分步的查看／编辑／确认草稿流程（`GuardDestination.filters`）。 |
| **网络与 Lava State 活动日志** | 免费 | 有上限的、仅本地的事件流，记录网络／运行时／用户的状态变化，通过 App Group 共享（`NetworkActivityLog`）。 |
| **错误报告** | 免费 | 由用户触发的向导，把一份匿名化的数据包发到 `POST /v1/bug-reports`；v1 里不含域名历史。也可以摇一摇来报告（`RageShakeDetector`）。 |
| **法律声明 + 版本** | 免费 | 设置里会呈现第三方法律声明（见 [第三方声明](../legal/third-party-notices.md)）和一个版本／构建页面。 |

---

## App 架构（方便快速上手） {#app-architecture-for-orientation}

三个 bundle 共用一个 App Group `group.com.lavasec`，旁边还有一个 `lavasec-ios: Shared/` 源码文件夹被编译进它们：

- **LavaSecApp**（`com.lavasec.app`）—— SwiftUI 的 App 外壳；在这个构建里，根是一个两标签的 `TabView`（**防护** + **设置**），过滤器和活动作为防护标签页下的详情页进入。
- **LavaSecTunnel**（`.tunnel`）—— 设备上的 DNS 过滤／解析引擎。
- **LavaSecWidget**（`.widget`）—— WidgetKit 的实时活动。
- **Shared/** —— 跨目标的源码（不是一个 bundle）：App Group、命令服务、岩酱、实时活动的属性／意图。

App ↔ 扩展之间的控制走 `NETunnelProviderSession` 的**提供方消息**（`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`），不是 Darwin 通知。过滤规则从 App 到扩展，是以 App-Group 快照文件的形式传过去的（`filter-snapshot.json` / `.compact`）。

---

## 相关文档 {#related-docs}

- 路线图 —— 计划中和已放弃的功能（Plus 的定价／StoreKit 定位、Android 移植、URL 级防护、通行密钥的 Associated-Domain 就绪、彩蛋小游戏、GPL-3.0 开源发布等等）都放在内部路线图里，不在这份公开清单中。
- [GPL 只发布来源 URL 的合规决定](../legal/gpl-source-url-only-compliance-decision.md)
- [开源列表数据条款的特别说明](../legal/open-source-list-data-terms-carveout.md)
- [第三方声明](../legal/third-party-notices.md)
