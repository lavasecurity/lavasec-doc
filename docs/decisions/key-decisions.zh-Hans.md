---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 关键设计决策

> 读者对象：工程师和管理层。这是一份 ADR 风格的记录，记下了 Lava Security 背后那些起支撑作用的设计决策——也就是塑造了整体架构、隐私承诺或产品边界的那些决定，尤其是那些试过又被推翻的。每一条都给出了**决策**本身、它的**背景**、**理由**，以及一个取自项目状态图例的**状态**（已采纳 / 已撤销 / 已替代 / 提议中）。
>
> **代码说了算。** 当计划和已上线的代码对不上时，这份记录以代码为准，并在相应位置直接点出分歧。

**状态图例（对应到整套文档的状态分类）：**

| 这里的状态 | 整套文档分类的含义 |
|---|---|
| **已采纳** | 已实现——已上线并在代码中确认 |
| **已撤销** | 已放弃——做出来过，后来被移除/撤销 |
| **已替代** | 较早的决策被后来的决策替换掉 |
| **提议中** | 计划中——已设计、已推荐或已记录，但还没在这套代码里落地 |

延伸阅读：目录分发模式见 [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) 和 [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md)；已上线的行为见 [`../product/features.md`](../product/features.md)。面向未来的方向写在内部路线图里。

---

## 1. 通过 `NEPacketTunnelProvider` 在设备本地过滤 DNS {#1-on-device-dns-filtering-via-nepackettunnelprovider}

**决策。** 通过 `NEPacketTunnelProvider` 数据包隧道（`LavaSecTunnel`，`com.lavasec.app.tunnel`）**在设备本地**过滤 DNS，而不用 `NEDNSProxyProvider`、`NEFilterProvider`、`NEDNSSettingsManager` 或 Safari 内容拦截器。

**背景。** 这款产品是面向非技术用户（家长、年长者）、隐私优先的过滤工具，通过消费级 App Store 发布，不需要账户。那些与之竞争的 NetworkExtension 提供方和托管式 DNS API，要么只限于受监督/受 MDM 管理的设备，要么覆盖不到一个 App 的全部 DNS；而走解析器那一侧的方案，会把用户访问的域名流量送出设备。

**理由。** 数据包隧道是唯一一个既能（a）在没被托管的消费级设备上工作、又能（b）让每一次 DNS 判断都在设备本地完成的提供方，而后者正是隐私承诺的根基：*所有 DNS 过滤都在设备上进行；Lava 绝不会让你的浏览流量经过它的服务器，也绝不会接收你访问的那一串域名。* 作为交换接受的代价，是隧道必须待在 iOS **每个扩展约 50 MiB 的内存上限**之下——这个约束塑造了下面好几条后续决策。

**状态。** **已采纳**（基础性决策；从最初的原型起就在代码里）。

---

## 2. 只分发拦截列表的源地址 {#2-source-url-only-blocklist-distribution}

**决策。** Lava 只发布上游拦截列表的 **URL 加上接受的哈希值**；设备直接从每个 `source_url` 拉取列表**字节**，然后在本地解析、归一化、去重并过滤。Lava **从不**存储、镜像、转换或提供第三方拦截列表的字节。Worker 只把目录**元数据** JSON 写入 R2（`raw_r2_key`/`normalized_r2_key` 都是 null）。

**背景。** 早先的设计会把拦截列表的原始字节镜像进 R2，好让法务审查分发情况。很多上游列表（HaGeZi、OISD）是 GPL-3.0 的，所以托管它们的字节就会让 Lava 成为 GPL 数据的再分发方。

**理由。** 把 Lava 当作一个本地过滤引擎 / 用户代理——而不是拦截列表分发方——能把 GPLv3 再分发和 App 审核的风险降到最低。设备会拿下载下来的字节对照目录里的 `accepted_source_hashes` 做校验，对不上时回退到上一次的有效缓存、或干脆"失败即拦截"，把镜像流水线原本提供的那份安全特性给找了回来。每一组解析出来的规则集还会再过一道受保护域名过滤器，这样上游列表就没法拦掉 Lava/Apple/身份提供方的域名。这套模式由 CI 中的 `check-gpl-blocklist-distribution.sh` 强制执行（不许有镜像代码、不许有 Lava 托管的产物 URL、不许默认启用 GPL 来源、不许往 R2 写字节）。

**状态。** **已采纳**，并且它**替代**了那个被放弃的 R2 原始镜像计划（`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`，标题写着"已被 source-url-only 实现替代"）。见 [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md)。

---

## 3. 加密的解析器传输（DoH / DoH3 / DoT / DoQ） {#3-encrypted-resolver-transports-doh--doh3--dot--doq}

**决策。** 在普通 DNS 和设备 DNS 回退之外，再提供四种加密的上游传输方式，全都抽取进 LavaSecCore：**DoH**（URLSession）、**DoH3**（优先用 HTTP/3 的 DoH）、**DoT**（用连接池管理的 `NWConnection`，每个端点最多 4 条，带空闲过期刷新和一次新连接重试）、以及 **DoQ**（DNS-over-QUIC）。路由、降级到普通 DNS、带退避闸门的逐端点故障转移、以及设备 DNS 回退，都放在 `ResolverOrchestrator` 里。

**背景。** 把没被拦截的查询用明文转发给解析器，会泄露本来要靠设备本地模型保护的那条域名流。这些传输方式是一步步建起来的（DoH → DoH3 → DoT → DoQ）。

**理由。** 加密的上游传输让没被拦截的查询从头到尾都保持私密。**DoH3** 这个标注纯粹是观察出来的——代码里设了 `assumesHTTP3Capable=true`，然后去观察实际协商出来的协议，**只有真的观察到 h3 协商成功时**，界面才标上 `DoH3`（不带斜杠），从不事先承诺，因为 h3 是逐连接尽力而为的，要是粘性地宣称用了它，在屏蔽 UDP 的防火墙后面就会夸大实际行为。DoT 带空闲刷新的连接池，正是为了解决 Cloudflare 悄悄关掉空闲 DoT 连接这个问题。

**状态。** **已采纳**（四种传输全都在位并已接好线）。

---

## 4. DoQ 连接复用——做出来了、真机测了、又撤销了 {#4-doq-connection-reuse--built-device-tested-reverted}

**决策。** DoQ **不**复用 QUIC 连接。`DoQTransport` **每次查询都开一条全新的 QUIC 连接**；那 4 条通道的连接池提供的是并发，不是握手复用。

**背景。** RFC 9250 把每次 DNS 查询映射到它自己的 QUIC 流，所以真正的复用需要多流的 `NWConnectionGroup`/`openStream` API，而那是 **仅 iOS 26.0+** 才有的，而部署底线是 iOS 17。尽管如此，还是实现了一条只在 iOS 26 上启用的复用路径（用 Xcode 26 SDK 编译过 Debug+Release 两种配置），并**在 iOS 26.5 真机上对着 AdGuard DoQ 测过**。

**理由。** 这条复用路径在真机上每次都失败（`openStream`/`receive` 报错，然后回退又撞上"Socket is not connected"），测出来**比**每次查询新建连接的基线**还要差**（对照组：35 次查询用了 34 次握手，全部成功）。这从实测上印证了 Apple DTS"先别用新 Network 框架配 QUIC"的建议，所以这块工作被撤销而非上线；只有文档和守护测试的理由里留下了这条发现，免得在这个 API 成熟之前又有人去重试。

**状态。** **已撤销**（推迟到部署底线提升到 iOS 26 再说）。把 DoQ 描述成每次查询都新建连接。

---

## 5. 否决一个统一的 `DNSResolvingTransport` 协议 {#5-reject-a-unifying-dnsresolvingtransport-protocol}

**决策。** **不**把各个解析器传输统一到一个 `DNSResolvingTransport` 协议下；保留基于闭包的 `ResolverOrchestrator.Executors` 接缝。

**背景。** 一次重构（issue 407）提议用一个协议罩住所有传输。

**理由。** 这些传输彼此差异太大——异步加密执行器（DoH/DoT/DoQ）跟同步的多地址普通/设备传输——所以一个统一协议会是个比现有可注入闭包接缝更糟糕的抽象，而那个接缝本来就已经让线上执行可测试了。

**状态。** **已撤销** / 不予实现（作为糟糕的抽象被关掉）。

---

## 6. 零知识加密备份（无密码，通行密钥那条例外已记录） {#6-zero-knowledge-encrypted-backup-passwordless-passkey-exception-noted}

**决策。** 在客户端备份一份**精简过的**设置数据：用 AES-256-GCM 在一个随机 32 字节的数据密钥下封装它，再通过 PBKDF2-HMAC-SHA256（生产环境 **210,000** 次迭代）把这个密钥包进每个密钥各自的**密钥槽**里。上传到 Supabase `user_backups` 表（每个用户 RLS）的只有密文加上非机密的元数据。已上线的流程是**无密码**的：设备密钥槽（设备本地 Keychain）+ 辅助恢复槽 + 可选的通行密钥槽。

**背景。** 可选的账户登录（仅限 Apple + Google）让设置能跨设备恢复。服务器绝不能读到用户的拦截列表、允许列表、解析器选择或其他任何设置。

**理由。** 明文和用来解密的密钥只存在于设备上；服务器每个用户只持有一个看不透的信封。辅助恢复是刻意设计成双因素的——`SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)`（以 NUL 分隔的输入）同时需要服务器持有的那一份和用户的 8 词恢复短语（约 105 位），所以光有任何一半都解不开。解锁材料存在设备本地（`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`），**不**放进可同步的 iCloud Keychain——这是一处隐私加固，推翻了原计划里可同步的设计。**通行密钥槽也是真正零知识的**：它是用一个 WebAuthn **PRF / `hmac-secret`** 认证器输出（经 HKDF-SHA256 派生）来包装的，这个输出从不离开客户端，所以没有任何服务器持有的值能把它解开。不存在服务角色的通行密钥表，也没有 Worker 的 WebAuthn 断言闸门——早先那套服务器把关的通行密钥设计被放弃了，所有服务器侧的通行密钥状态都被移除（`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`）。

**状态。** **已采纳**（无密码模式、辅助恢复，以及一个零知识的 PRF 派生通行密钥槽，全都在代码里）。要把通行密钥做成物理设备上完全可用于生产、可恢复的因素（为 PRF 模型托管 Associated Domains / AASA），还是**提议中**（待办）。

---

## 7. 失败即拦截的按需连接 {#7-fail-closed-connect-on-demand}

**决策。** 加一条 `NEOnDemandRuleConnect` 规则，让被系统停掉的隧道能自动重启，并以**失败即拦截**作为安全默认：当没有可复用的过滤快照时，隧道拦掉所有流量，而不是不过滤就放行。任何停止动作之前都会先**关掉**按需连接，这样 VPN 始终能被关掉。

**背景。** iOS 在悄悄停掉隧道（原因 17），又没东西去重启它，长达约 45 分钟，让用户处于没防护的状态。要是天真地启用按需连接，VPN 就再也关不掉了；而失败即放行的默认设置，会在这段空档里放行流量。

**理由。** 按需连接补上了"悄悄停掉"的空档；停止前先关掉它保住了用户关闭防护的能力；失败即拦截保证这段空档是安全的、而不是悄无声息地不过滤，由 `reconcileTunnelSnapshotAfterLaunch` 来兜底恢复。这个改动有副作用——按需连接在引导过程中又触发了"添加 VPN 配置"的系统提示——这引出了一连串的多次提交修复：安装时不再启用按需连接；把启动/防护恢复门控在引导完成之后；并通过**移除**来中和一个继承下来/孤立的配置（`removeFromPreferences`，静默），而不是通过保存 `on-demand=false`（`saveToPreferences` 会让提示再次弹出）。

**状态。** **已采纳**（按需重启加上那一连串引导/失败即拦截的修复）。

---

## 8. 模块化的 VPN 重构与发热回归纪律 {#8-modular-vpn-refactor-and-the-heat-regression-discipline}

**决策。** 重新组织 VPN 这条路径（VPNLifecycleController、ProtectionActionOrchestrator、ResolverOrchestrator、FilterArtifactStore、DNSResponseCache、RuleSetCache、FilterSnapshotPreparationService），实现缓存优先的开启、有上限的并行拉取，以及抖动合并——把电量/延迟当作产品需求来对待，定了明确的 p50/p95 目标，并在**真机**（不是模拟器）上做性能剖析。

**背景。** 开启 / 刷新 / 暂停 / 恢复都很慢。重构过程中冒出了一次发热回归（134% CPU，高能耗，手机发烫）。先是一大组 agent 用回归之前的证据驳倒了大家怀疑的原因；随后一次真机抓取又确认了它。

**理由。** 真正的原因是一个自我维持的 `NEVPNStatusDidChange` 刷新循环——一个会永远重新触发自己的合并循环（约每秒 370 个事件，主线程约 100%，`vpn-debug-log.jsonl` 涨到约 180–210 MB），起因是一个"丢弃重入"的守卫被换掉了。修复办法是读取缓存里的管理器状态，并给循环设上上限。计划里自己的前后对比真机记录显示，热启动开启（`action.turnOn`）在 iPhone 15 Pro 上从 **2,722 ms 降到 287 ms**；之后另有一次模块化之后的优化机会评估，在同一台设备上把热路径测到了 **112 ms**（解码 51 + managerSetup 57）。这件事立下了标准：结构性重构要先暂停，直到测出来的发热回归被控制住；模拟器上的散热/电量结果一律当无意义驳回。

**状态。** **已采纳**（`plans/implemented/2026-06-12-modular-speed-up-plan.md`）。一次模块化之后的评估把 `PacketTunnelProvider` 和 `AppViewModel` 留作已知的、还活着的"上帝对象"。

---

## 9. 用过滤规则预算取代列表数量上限 {#9-filter-rules-budget-instead-of-a-list-count-cap}

**决策。** 用**过滤规则预算**来区分套餐——**免费 500K / Plus 200 万**条编译后的域名规则——而不是按启用的列表数量来分。一道硬性的 **约 326 万规则的设备护栏**（`maxResidentMegabytes 32.0`、`baselineMegabytes 4.0`、`estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`）对**所有人**生效，**绝不是**一道付费墙。那块紧凑的域名数据块用了 `mmap`（`.mappedIfSafe`），所以它始终由文件支撑、待在 jetsam 计数的 `phys_footprint` 之外；只有解码后的条目表才占用常驻内存。

**背景。** 旧的上限是按列表**数量**算的（免费 3 个 / 付费 10 个）。一个列表可以装 1K 条规则、也可以装 100 万条，所以数量是个不诚实的代理指标，根本反映不了真正受限的资源——NE 那 50 MiB 的内存上限。

**理由。** 规则对应的是实际内存，所以只要装得下，任何列表组合都允许。权威的强制执行发生在编译期，作用在去重合并后的并集上，位于 `FilterSnapshotPreparationService`（先过设备护栏，再过套餐上限）；选择时界面上的那个量表用的是按列表求和、加 1.10 的软上限余量。超出预算的配置会被确定性地拒绝（让防护保持关闭），而不是放任隧道被 jetsam 杀掉。

**状态。** 在代码里**已采纳**（`SubscriptionPolicy.swift`），已在 **v1.0.0** 上线，它**替代**了列表数量上限。规则预算现在就是生效的档位门槛；按域名的上限也在 1.0 一并提高了（免费 25 / Plus 1,000 个允许和已拦截域名）。见 [`../product/features.md`](../product/features.md)。

---

## 10. 计划用 markdown + 单向同步到 Linear {#10-plans-as-markdown--one-way-linear-sync}

**决策。** `plans/<lane>/` 里的 markdown 文件是**唯一真相来源**；**所在的 lane 文件夹就是权威状态**（`implemented`、`inflight`、`under_review`、`backlog`、`dropped`）。往 `main` 推送时会把计划**单向**同步到 Linear（团队 LAV），创建之后只刷新标题/描述；另有一条**手动、经过审查**的回流路径，把 Linear 的状态/优先级/lane 拉回计划的 frontmatter。

**背景。** 一支小团队需要一种工具无关、可审查、又不跟项目追踪器打架的计划状态，而一个自主的 agent 循环需要一个稳定的地方去读写计划状态。

**理由。** 这种字段归属的切分让两套系统互不冲突——markdown 拥有内容，Linear 拥有分流状态——所以一次推送永远不会覆盖掉人工分流。`dropped/` 这个 lane 把取消掉的计划挡在同步流水线之外，免得它们再冒出来（在"允许例外护栏 / LAV-5"被否决时建立）。计划里过时的 frontmatter 是个文档 bug，不是状态；文件夹说了算；当代码显示某个功能已经上线、尽管 frontmatter 还写着"Backlog"（比如账户删除），以代码为准。

**状态。** **已采纳**（`scripts/sync-plans-to-linear.mjs`、`.github/workflows/sync-plans.yml`；`dropped/` lane 在用）。

---

## 11. 仓库拆分 + 用 copyleft 开源客户端 {#11-repo-split--copyleft-open-source-of-the-client}

**决策。** 把单体仓库拆成按组件划分的多个仓库（`lavasec-ios`、`-android`、`-web`、`-infra`、`-doc`、`-runner`），并参照 Mullvad/ProtonVPN 的 copyleft 先例，把第一方客户端**用 AGPL-3.0 开源**，取代原来的 Apache-2.0。

**背景。** 按组件开发，以及把客户端开源。许可证的问题在于：竞争对手会不会把客户端 fork 走、闭源化，然后靠低价来抢生意。

**理由。** Copyleft 强制衍生作品保持开放，挡住了客户端被闭源 fork 的可能——是一种"客户端公开、后端/运维私有"的姿态，把后端、法务和运维都留作私有。选 AGPL-3.0（而非普通 GPL-3.0）是为了堵上网络使用这个缺口。众所周知的 GPL 与 App Store 分发之间的张力，靠 Lava 自己以自有版权作为 App Store 二进制的分发方来处理。

**状态。** **已采纳。** 仓库拆分**已完成**：每个组件都住在自己的仓库里——公开的 `lavasec-ios` 客户端打了 v0.4.0 标签，外加 Android、营销站点、后端/基础设施、文档、以及 CI/发布流水线各自独立的仓库——而 `lavasec-ios` 的 `README.md` "Repository layout"一节只列出了这个仓库自己按组件划分的内容（`LavaSecApp/`、`LavaSecTunnel/`、`LavaSecWidget/`、`Shared/`、`Sources/`、`Tests/`），并注明基础设施住在独立的私有仓库里。客户端以 **AGPL-3.0** 开源：`lavasec-ios` 的 `LICENSE` 是 GNU Affero General Public License v3，`README.md` 上挂着 AGPL-3.0 的徽章。

---

## 附录——其他记录在案的撤销与否决 {#appendix--other-recorded-reversals-and-rejections}

这些都更小，但都是有过明确反转记录的真实决策；为求完整在此列出。

| 决策 | 理由 | 状态 |
|---|---|---|
| 自定义 DNS 免费版还是付费版 | 变现定位问题；曾短暂在免费版放开，后来又回到仅付费 | **已撤销**，回到仅付费 |
| 邮箱/密码登录 | 自己管密码会带来重置/MFA/锁定/泄露/盗号一堆负担，而 Apple + Google 已经够用了；绕开恢复机制会破坏零知识 | **已撤销** / 从未上线（仅 Apple + Google） |
| 允许例外护栏（LAV-5） | 护栏优先级已经通过更简单的过滤列表编辑改版上线了；付费绝不能绕过高置信度的威胁护栏 | **已撤销**（建立了 `dropped/` lane） |
| TestFlight 分支晋升锁定 | 最初的锁定被重新考虑；由一个计划中的、开源之后的 runner 锁定取代 | **已撤销**，被一个待办计划替代 |
| App↔扩展控制通道 | `sendProviderMessage`（`NETunnelProviderSession`）是 **App→隧道唯一的控制路径**——它承载着带类型、带版本号的状态，并权威地驱动扩展的运行循环。早先扩展那一侧的 `CFNotificationCenter` 观察者在真机上从来没可靠触发过，已被**移除**（由源码内省测试断言其不存在）。Darwin 通知只在 **隧道→App** 方向上保留，作为一次"健康状态变了"的提醒。 | **已采纳**（provider-message 是 App→隧道唯一的控制；Darwin 仅用于隧道→App 的健康状态） |

> 贯穿全文引用的横切安全不变式：付费永远不绕过那道经哈希校验、不可被允许放行的**威胁护栏**。决策优先级是 **威胁护栏 > 本地允许列表（允许例外）> 拦截列表 > 默认放行。**
