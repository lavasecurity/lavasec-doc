---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 产品概览 {#product-overview}

欢迎使用 Lava Security。本页介绍 Lava 是什么、它承诺什么，以及更多内容可以去哪里读。

## Lava 是什么 {#what-lava-is}

Lava Security 是一款以隐私为先的 iOS App，它通过设备上的[NetworkExtension 数据包隧道](../architecture/ios-client.md)在本机直接过滤 DNS，拦掉已知的危险和不想要的域名，而不会把你的浏览数据绕到 Lava 的服务器上去。这条数据包隧道（`LavaSecTunnel`，一个 `NEPacketTunnelProvider`）会在手机上解析每一条 DNS 查询，将请求的域名与一份已编译、内存映射的过滤快照比对，只把允许通过的查询转发到上游。你的流量不会经过任何由 Lava 运营的代理：过滤是在你设备上本地做出的决定。

iOS 之所以把它标成「VPN」，是因为数据包隧道是 App 能在系统层面过滤 DNS 的唯一办法——但 Lava 做的是 **DNS／拦截列表过滤**，不是流量转发。我们想把范围说清楚：Lava 是本地的 DNS 域名过滤，**并不**保证每一个恶意域名或网址都会被拦下来。它看到的是域名，不是页面路径，因此无法在一个本身可信的主机上拦掉某个坏页面。另外，防护并非引导一结束就自动开启——App 里的 **Guard** 标签页才是判断防护当前是否生效的权威依据。

## 隐私承诺 {#the-privacy-promise}

> 所有 DNS 过滤都在设备上完成；Lava 从不把你的浏览数据绕经它的服务器，也从不收到你访问过的域名流——后端只保存目录元数据、一份不透明的、每个用户各自加密的备份，以及你自己选择发送的匿名诊断信息。

这句话是基准。这套文档里其他所有内容都要和它保持一致。付费购买可选层级**并不会**把过滤搬到服务器上，也不会让 Lava 拿到你访问过的域名流。当某个功能用到服务器时，文档会明确写出哪些东西**不会**被发送——你日常的 DNS 查询、你的浏览历史，以及任何明文，都留在设备上。完整情况请看[后端与数据模型](../architecture/backend-and-data.md)。

## 适合谁用 {#who-it-is-for}

Lava 面向任何想要更安全地上网、又不想费心打理的人。目标人群包括不懂技术的用户——为家人设置防护的父母、年长用户，以及完全不想操心 DNS 的人。默认体验开箱即用：打开防护，一份稳妥的拦截列表就开始过滤，全程不需要账户。与此同时，进阶用户想用更深入的控制（自定义拦截列表、其他解析器）时也随时能找到。

整套文案的语气都是朴实、平和、实用的——危险被当作一个比喻来讲，而不是用来吓唬人。

## 核心原则 {#core-principles}

- **隐私是定位，不是付费功能。** 过滤是在本地做出的决定。Lava 的后端刻意做得极简，从不收到你日常浏览的域名或 DNS 事件流。可选的账户备份是[零知识](../architecture/accounts-and-backup.md)的：服务器只存密文和不涉及秘密的信封元数据。
- **核心防护永久免费。** 防护开关、默认拦截列表更新，以及基础的本地计数，永远不设门槛，也永远不需要账户。
- **在设备上运行。** 防护引擎完全住在手机里——DNS 解析、域名判断和向上游转发，全都在数据包隧道扩展内部完成，并受 iOS 每个扩展约 50 MiB 的内存上限约束。拦截列表采用[仅源地址](../architecture/dns-filtering-and-blocklists.md)的模式：App 直接抓取每一份上游列表并在本地解析；Lava 从不托管或分发第三方拦截列表的字节。
- **付费只解锁定制，绝不解锁基线安全。** 威胁防线——一个凌驾于所有拦截列表之上、谁都不能加进允许例外（无论付费与否）的不可豁免层级——由决策优先级强制保障：**威胁防线 > 本地允许列表（允许例外） > 拦截列表 > 默认放行。** （这个优先级位置已接好线，并由获准的 SHA-256 哈希做完整性校验；目前出厂时里面没有任何条目。）隧道会忽略 `isPaid`。
- **核心平和，深度自取。** 默认界面安静而让人安心，由 Soft Shield Guardian 吉祥物和避免吓人措辞的文案打头阵。更丰富、更技术性的细节在你主动去找时就有，但绝不会硬塞给你。这种「核心平和，深度自取」的理念在 **LavaTier** 深度模型（Floor／Window／Workshop）里被正式确立下来——见[设计系统](../design-system/overview.md)。

## 高层能力 {#high-level-capabilities}

- **本地 DNS 过滤** —— 数据包隧道引擎负责解析 DNS、拿每个域名去比对已编译的快照，并把允许的查询转发到上游，同时带有设备 DNS 兜底。见 [iOS 客户端](../architecture/ios-client.md)和 [DNS 过滤与拦截列表](../architecture/dns-filtering-and-blocklists.md)。
- **精选拦截列表，仅源地址** —— Lava 只发布上游列表的 URL（外加用于缓存标识和审计的参考性哈希）；设备通过 TLS 抓取每一份列表，并在大小／规则上限之内本地解析，Lava 从不镜像或分发第三方拦截列表的字节。社区列表不做哈希钉定——TLS 加上精选的 URL 就是完整性边界——而 Lava 的威胁防线层级则保持哈希强制校验。出厂默认会启用 **Block List Basic**（`AppConfiguration.lavaRecommendedDefaults`，定义在 `OnboardingDefaults.swift`）；HaGeZi、OISD、AdGuard、1Hosts 等 copyleft 来源需要自行选择开启。见 [DNS 过滤与拦截列表](../architecture/dns-filtering-and-blocklists.md)。
- **加密 DNS 传输** —— DoH（带观测性的 DoH3 标注）、DoT（连接池，复用并刷新）以及 DoQ（每次查询都新建连接）。这三种都已实现；Device DNS（网络自带的解析器）是出厂默认，加密预设需要自行选择开启（`AppConfiguration.lavaRecommendedDefaults`，定义在 `Sources/LavaSecCore/OnboardingDefaults.swift`）。内置的解析器预设（Google／Cloudflare／Quad9 的 DoH 和 DoT 变体）免费；只有完全自定义的解析器才是付费解锁项。见 [DNS 过滤与拦截列表](../architecture/dns-filtering-and-blocklists.md)。
- **允许例外（允许列表）** —— 手动把某些域名加进来，即便它们在拦截列表上也予以放行；威胁防线依然优先。见[产品功能概览](features.md)。
- **The Soft Shield Guardian** —— Guard 标签页、Live Activity 和灵动岛上的吉祥物，用 7 种表情状态表达防护状态。见[设计系统](../design-system/overview.md)。
- **分层定制（Lava Security Plus）** —— 一个可选的付费层级，用来解锁定制（更大的过滤规则额度——免费 50 万／Plus 200 万条已编译规则，二者共用同一份设备安全护栏——更多允许／已拦截域名、自定义拦截列表，以及自定义 DNS 解析器）。Plus 永远不会绕过常开的护栏——隧道会忽略 `isPaid`。
- **可选的账户与备份** —— Apple 或 Google 登录，配端到端加密的（[零知识](../architecture/accounts-and-backup.md)）设置备份和恢复码；账户删除可自助完成。可选的通行密钥恢复位**同样是零知识**的——它的密钥由设备从认证器的 WebAuthn PRF 本地派生，服务器不持有任何秘密；在设备上达到生产可用，还要看 Associated Domains／AASA 托管 **（计划中）**。账户是可选的；不登录也能完整使用防护。
- **仅本地的活动与报告** —— 设备上的拦截／允许计数、隧道健康状况，以及一份需自行开启的错误报告包，全都由运行中的隧道留在设备上的数据生成——空闲时为空，防护进行中时实时更新。不会有日常域名历史离开设备。见[产品功能概览](features.md)。

## 平台 {#platforms}

- **iOS —— 已发布。** Lava 今天是一款 iOS App：三个 bundle 共用一个 App Group（`group.com.lavasec`）——主 App（`com.lavasec.app`）、数据包隧道扩展（`.tunnel`）和小组件（`.widget`）——加上共享源码，全都基于同一个 `LavaSecCore` 包。
- **Android —— 计划中。** 计划基于 Android 的 `VpnService`，用原生 Kotlin／Jetpack Compose 做一个移植版，沿用同样的隐私承诺和经过对等测试的核心过滤行为。目前还没有任何 Android App 代码发布。

可发布功能的稳定 id 以及 iOS／Android 之间的约定，请看[平台对等](platform-parity.md)。
