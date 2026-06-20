---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# DNS 过滤与拦截列表

> 读者对象：工程师。这篇文档讲的是设备本地的 DNS 处理流程、加密传输下的解析器路径、过滤决策引擎，以及「只发布来源 URL」的拦截列表目录模型——并附上代码里实际生效的精确数字。这里写的状态都对应代码里已经确认的真实情况。凡是计划和代码对不上的地方，**以代码为准**，并在文中直接点出差异。

所有 DNS 过滤都在设备上完成；Lava Security 从不把你的浏览流量经过它的服务器，也从不接收你访问过的域名列表——后端只持有目录元数据、一份不透明的、按用户加密的备份，以及你主动选择发送的匿名诊断信息。

Lava Security 提供的是**本地 DNS / 拦截列表过滤**，并不保证每一个恶意域名或 URL 都会被拦截。

---

## 1. DNS 处理流程（已实现） {#1-the-dns-pipeline-implemented}

过滤/解析引擎跑在 **NE / 数据包隧道** 里——也就是 `NEPacketTunnelProvider` 扩展 `LavaSecTunnel`（`com.lavasec.app.tunnel`），它只拦截 DNS。隧道地址是 `10.255.0.2`（隧道）和 `10.255.0.1`（DNS 服务器）。App 进程从不接触查询流量；它只把编译好的产物写进 **App Group**（`group.com.lavasec`），并通过 NETunnelProviderSession 的 **provider messages**（不是 Darwin 通知）给隧道发信号。

对每一个进来的 DNS 查询，隧道都会在 `DNSQueryDispatcher`（`Sources/LavaSecCore/DNSQueryDispatcher.swift`）里跑一套固定的**查询优先级**：

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap 优先是一条硬性不变量。** 一个用来解析所配置解析器*自身*主机名（也就是 DoH/DoT/DoQ 端点）的查询，绝对不能被拦截或暂停，否则隧道根本就没法把加密 DNS 跑起来。dispatcher 用的是惰性闭包，所以每一步只在真正轮到它时才会读取，从而保留短路逻辑（已经有 bootstrap 响应时就不读快照；正在 bootstrap 时就不读 pause）。
- **temporary pause** 在用户发起的暂停 TTL 还有效时，把查询直接转发给上游。
- **filter** 拿域名去比对编译好的快照，然后要么转发它，要么合成一个拦截响应。

通过过滤的查询（动作为 `.allow`）会被交给解析器路径（见 §3）。冷启动时如果没有可复用的快照，隧道会**故障即关闭（fail closed）**：它会装上一个故障即关闭的运行时快照，拦截掉所有流量，而不是放行未经过滤的流量。

---

## 2. 过滤引擎（已实现） {#2-the-filtering-engine-implemented}

### 2.1 决策优先级 {#21-decision-precedence}

`FilterSnapshot.decision(forNormalizedDomain:)`（`Sources/LavaSecCore/FilterSnapshot.swift:57-71`）采用这套标准的安全优先级：

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| 顺序 | 规则集 | 结果 | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | 拦截 | `.threatGuardrail` |
| 2 | `allowRules` | 允许 | `.localAllowlist` |
| 3 | `blockRules` | 拦截 | `.blocklist` |
| 4 | — | 允许 | `.defaultAllow` |

一个无法通过归一化的域名会被拦截，原因为 `.invalidDomain`（保险起见）。同样的优先级也镜像到了磁盘上的二进制形式（`CompactFilterSnapshot`）里。安全护栏特意排在本地允许列表之上：**付费永远绕不过这条不可放行的安全护栏**，用户的例外也无法把被护栏拦下的域名重新放行。

> 注意：在当前工作树里，`nonAllowableThreatRules` / `guardrailSources` 都是空的（`DefaultCatalog.guardrailSources = []`，`BlocklistModels.swift:254`）；这个优先级槽位已经接好线、也在强制执行，只是目前还没有任何护栏条目随包发布。

### 2.2 规则存储与常驻内存的计量单位 {#22-rule-storage-and-the-resident-memory-unit}

`DomainRuleSet`（`Sources/LavaSecCore/DomainRuleSet.swift`）存的是 `exactDomains` + `suffixDomains` 两个集合。匹配（`containsNormalized`）会在查询时做一次精确查找，外加一趟父级后缀遍历（类似 `hasSuffix`）——也就是说**编译时不做子域名归并**。一条有效的通配符行就是**一条规则**、一个内存表条目。正是这种「1 行 = 1 规则」的对应关系，让规则数成了诚实反映资源占用的指标（见 §4）。

### 2.3 编译后的快照形式 {#23-compiled-snapshot-forms}

- **`FilterSnapshot`** —— 内存中编译好的过滤器：`blockRules`、`allowRules`、`nonAllowableThreatRules`，以及解析器预设。
- **`CompactFilterSnapshot`** —— 二进制、对 mmap 友好的磁盘形式，也是隧道实际读取的那一份（魔数 `LSCFSNP1`，`fileVersion 1`）。它通过 mmap 零拷贝加载（见 §4.3）。

App 会把 `filter-snapshot.json` 和 `filter-snapshot.compact` 都写进 App Group；隧道解码的是 compact 那份产物。还有一条**热启动复用**路径（`FilterArtifactStore`），让隧道无需重新编译就能复用磁盘上的 compact 产物，由一个身份指纹 + 一份原子写入的清单（manifest）来把关；当解析器传输方式、目录覆盖范围或快照输入发生变化时，复用会被拒绝（出于隐私安全，原因里只给字段名）。

---

## 3. 加密传输与解析器路径（已实现） {#3-encrypted-transports--the-resolver-path-implemented}

### 3.1 传输枚举 {#31-transport-enum}

没被拦截的查询会被转发给所配置的上游解析器。`DNSResolverTransport`（`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`）有**五**个取值：

| 传输方式 | 原始值 | UI 中显示的标注 |
|---|---|---|
| Device DNS | `device-dns` | *（无——名字本身就是传输方式）* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

内置预设有 Google、Cloudflare、Quad9、Mullvad（每个都有 IP / DoH / DoT 三种变体），外加 Device DNS 和 Custom。自定义解析器接受：普通的 IPv4/IPv6 服务器地址、一个 DoH URL、一个 DoT URL（`tls://` / `dot://`）、一个 DoQ URL（`doq://` / `quic://`），或者一个 `sdns://` 的 DNS stamp；带用户名/密码的地址和 localhost 会被拒绝。DoT/DoQ 的默认端口是 `853`，而 DoH 需要带上路径。

### 3.2 DoH / DoH3 {#32-doh--doh3}

`DoHTransport`（`Sources/LavaSecCore/DoHTransport.swift`）通过 `URLSession` 执行 DoH。每个请求都会主动选用 HTTP/3（`request.assumesHTTP3Capable = true`，`DNSOverHTTPSRequest.swift:29`）；Apple 的加载器原生就能回落到 H2/H1，所以这绝不会让一个本来能连上的解析器变得连不上。实际协商出来的协议从 `URLSessionTaskTransactionMetrics.networkProtocolName` 里读取（ALPN：`h3`、`h2`、`http/1.1`）。

UI 只在**真正观测到 h3 协商成功时**，才把它标注成 **`DoH3`（中间没有斜杠）**——比如「Quad9 (DoH3)」（`DoHHTTPVersion.dohAnnotation`）；否则就显示 `DoH`。DoH3 是优先尝试、但从不承诺：这个标签是基于实际观测的，且只针对当前这个解析器，绝不持久化（跨重启沿用「确认为 DoH3」的做法已经被回退掉了）。请求用 POST 发送 `application/dns-message`；响应会校验 content-type 和长度，并在写回前还原事务 ID。

### 3.3 DoT {#33-dot}

`DoTTransport`（`Sources/LavaSecCore/DoTTransport.swift`）用的是池化的 `NWConnection`，**每个端点最多 4 条连接**（`maxConnectionsPerEndpoint = 4`），轮询使用，这样并行查询就不会被队头阻塞卡住。它还处理了**空闲过期**的问题：像 Cloudflare 这类提供方会在服务端把空闲的 DoT 连接关掉（大约 10 秒），且不会暴露任何状态变化，所以一条空闲超过 **8 秒**（`reusedConnectionMaxIdleInterval = 8`）的复用连接会在发送前先刷新一遍；而复用连接上若发生超时，**会重试且仅重试一次新连接**。

### 3.4 DoQ —— 每次查询都新建连接 {#34-doq--fresh-connection-per-query}

`DoQTransport`（`Sources/LavaSecCore/DoQTransport.swift`）会维持一个有上限的连接池，**每个端点 4 条通道**，但**每次查询都会新开一条 QUIC 连接**——也就是每次查询都做一次完整握手。这 4 条通道的池子提供的是**并发能力，而不是握手复用**。

**DoQ 连接复用的状态（已放弃 / 已延后）。** 复用方案做过评审，也在真机上跑过基准（35 次查询里有 34 次是全新握手 ≈ 基本没复用），随后实现成了一条需要 iOS 26 才启用的多流 `NWConnectionGroup` 路径，并在真机上对着 AdGuard 的 DoQ 测过，最后因为**净收益为负而被回退**（对着真实服务器时出现流失败 + 回退报错）。RFC 9250 把每个查询都映射到它自己的 QUIC 流上，所以复用需要用到 `NWConnectionGroup` / `openStream`，而这**只在 iOS 26.0+ 才有**；目前部署的最低系统门槛是 **iOS 17**。复用会一直延后到门槛抬到 iOS 26 为止。在不支持的设备上，自定义 DoQ 会被拒绝（提示「DNS over QUIC is not supported on this device」）。

### 3.5 解析策略 {#35-resolution-policy}

`ResolverOrchestrator`（`Sources/LavaSecCore/ResolverOrchestrator.swift`）负责管上游策略：

1. 按所配置的传输方式做**传输路由**。
2. 当某个加密方案没有可用端点时，**降级到 plain DNS**。
3. 带退避闸门的**逐端点故障转移**——一个处于退避状态的端点根本不会真正发包上网（结果为 `backed-off`）。
4. 当主解析器没有返回响应**且**方案允许时，**回落到 Device DNS**（方案上的属性是 `shouldFallbackToDeviceDNS`，由配置字段 `fallbackToDeviceDNS` 推导得来）；结果会被重新标注成 device 这个传输方式。真正的发包执行被注入到一组 executor 后面，让策略本身可以单元测试；退避状态则留在纯策略逻辑之外。

---

## 4. 过滤规则预算、NE 上限与 mmap {#4-filter-rules-budget-ne-ceiling-and-mmap}

随包发布的分层指标是**过滤规则预算**：一个用户最多能启用的编译后域名**规则**总数。它取代了过去那套按已启用列表**数量**来限制的上限（免费 3 个 / 付费 10 个），那是个不诚实的近似——一个列表可能是 1 千条规则，也可能是 100 万条。这里有**两层**：一层是面向所有人的设备护栏，另一层是排在它下面、用于变现的分层上限。

### 4.1 分层上限（已实现） {#41-tier-limits-implemented}

`FeatureLimits`（`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`）是唯一的事实来源：

| 分层 | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | 自定义拦截列表 / DNS |
|---|---|---|---|---|
| **免费方案** | **500,000** | 25 | 25 | 否 |
| **Plus**（`.paid` / `.plus`） | **2,000,000** | 1,000 | 1,000 | 是 |

分层上限是一条变现的边界，**绝不是把设备护栏拿来收费的门槛**。**Lava Security Plus** 解锁的只是自定义能力——绝不涉及基础安全，也绝不涉及安全护栏。自定义（付费）拦截列表是直接从用户设备这端去拉取、在本地解析并缓存的，绝不经过 Lava Security 的服务器中转。

### 4.2 设备内存护栏 + NE 上限（已实现） {#42-device-memory-guardrail--ne-ceiling-implemented}

数据包隧道受制于 iOS 的 **~50 MiB 单扩展内存上限**（这是自 iOS 15 起、操作系统针对数据包隧道这类扩展定的一个设计上限，不随 RAM 大小缩放；它写在一份按设备型号区分的 `com.apple.jetsamproperties.{Model}.plist` 里，在老设备上可能更低）。一旦超过就会触发 jetsam。这个上限没有 API 可查，所以预算会在悬崖边上预留余量。

`FilterSnapshotMemoryBudget`（`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`）负责算账，单位换算成过滤规则数（block + allow + guardrail）：

| 常量 | 取值 |
|---|---|
| `baselineMegabytes` | 4.0 MB（固定的进程开销，实测约 3.5 MB，向上取整） |
| `estimatedBytesPerRule` | 每条规则 9.0 B 的脏常驻内存（实测约 8.5 B，向上取整） |
| `maxResidentMegabytes` | 32.0 MB（目标上限，在观测到的约 40–46 MB jetsam 悬崖之下留出约 10 MB 余量） |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 条规则** |

这道 **~326 万条规则的设备护栏**是*每一个*用户的硬性安全底线，它高于任何订阅分层，并且**绝不是收费门槛**。锚定测量值（设备「chimmy」，2026-06-13）：**789,831 条规则 → 9.9 MB `phys_footprint`**，也就是约等于「基线 + 每条规则的成本」。

### 4.3 mmap 策略（已实现） {#43-mmap-strategy-implemented}

compact 快照通过 `Data(contentsOf:options:[.mappedIfSafe])`（`LavaSecTunnel/PacketTunnelProvider.swift:4431`、`:4665`）加载，`CompactBinaryReader` 返回的是零拷贝切片。那块好几 MB 的域名文本数据始终保持**文件支撑/干净（clean）**状态，不计入 jetsam 统计的 `phys_footprint`；只有解码出来的 `[Entry]` 表才占用常驻内存（磁盘上约 6 B/规则，脏常驻约 8.5 B）。这就把设备上能容纳的域名上限抬高了：常驻成本是那些条目表，而不是整份产物。

### 4.4 两层强制执行（已实现） {#44-two-layer-enforcement-implemented}

- **权威层（编译时）。** `FilterSnapshotPreparationService`（`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`）在所有已启用列表的**去重并集**上强制执行预算。设备护栏**先**检查（那条硬底线），分层上限则约束在它下面。超预算的配置会被确定性地拒绝——给出 `exceedsDeviceMemoryBudget` 或 `exceedsTierFilterRuleLimit`——而不是放任隧道触发 jetsam。报错里会点名贡献最大的两个列表，好让人一眼看清该怎么改。
- **提示层（选择时的 UI）。** `FilterRuleBudget`（`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`）用一个**按列表逐个求和**的方式来驱动选择计量条，并加上 **1.10 的软上限余量**，用来补偿大约 7–10% 的跨列表重复计数（逐列表求和会高估去重后的并集）。

### 4.5 解析器（parser）（已实现） {#45-the-parser-implemented}

`BlocklistParser`（`Sources/LavaSecCore/BlocklistParser.swift`）按字面规则逐条计数：它丢掉注释/空行/无效行，做归一化，在一个列表内对精确字符串去重（用一个 `Set`），并对每个列表封顶在 **`maxRules = 1,000,000`** 条（默认值），单行最长 4,096 个字符。支持的格式有：`auto`、`plainDomains`、`hosts`、`adblock`、`dnsmasq`（`auto` 会依次尝试 hosts → dnsmasq → adblock → plain）。一条有效行 = 一条规则 = 那个内存单位。

> **带多个主机的 `hosts` 行（解析器规则版本 2）。** 一条把一个 IP 映射到多个主机的 `hosts` 行（`0.0.0.0 a.com b.com c.com`）现在会把**每一个**主机都生成成它自己的一条规则，而不是只取第一个；`maxRules` 是**按规则**强制执行的（不是按行），所以一条靠近上限的多主机行不会超出。由于同样的上游字节现在能产出更多规则，解析器的规则版本被从 **1 → 2**，使得那些按旧的「只取第一个主机」行为解析出来的、已过期的 `RuleSetCache` 条目失效。

### 4.6 下载与解码的健壮性（已实现） {#46-download--decode-robustness-implemented}

隧道和目录同步都跑在 NE 的内存预算之内，所以列表的摄取过程针对恶意或畸形的输入做了加固：

- **流式下载。** `defaultDataFetcher` 通过 `URLSession.download` 把列表字节下载到一个临时文件里（峰值内存有上限），并在下载完成后做一次大小检查（`maximumBlocklistBytes`），而不是把整个响应体都缓冲在 RAM 里；超大的响应体会抛出 `BlocklistDownloadSizeLimitExceeded`。
- **目录元数据上限（8 MB）。** `BlocklistCatalogRepository.maximumCatalogBytes` 会在解码之前就拒掉一份超大的远程目录，这样恶意／中间人主机就没法逼着扩展去做一次 OOM 的 JSON 解码。
- **宽容的 UTF-8 解码。** 单个无效的 UTF-8 字节不再会让整份列表被拒（在失败即关闭下那会拦掉所有 DNS）；无效字节会变成 U+FFFD，只有那一行出问题的行才会在逐行校验里失败并被丢弃。
- **具名的自定义拦截列表错误。** 一份加载失败的自定义列表现在会浮现出 `customBlocklistUnavailable(displayName:reason:)` ——「Couldn't load the custom blocklist '<name>'. <why>」——而不是一个裸的 `URLError`；取消会作为取消被传播，而不是当作一次下载失败。

---

## 5. 拦截列表目录与默认来源 {#5-blocklist-catalog--default-sources}

### 5.1 目录模型（已实现） {#51-catalog-model-implemented}

**拦截列表目录**就是那份对外发布的、可用来源清单。**lavasec-api Worker** 从一个 R2 桶里通过 `GET /v1/catalog`（以及 `/v1/catalog/:version`）提供 JSON 元数据；设备则直接从每个上游 `source_url` 去拉取实际的列表**字节**。iOS 端的目录端点是 `https://api.lavasecurity.app/v1/catalog`（`BlocklistCatalogSync.swift:4-15`）。

在设备上，`BlocklistCatalogSynchronizer`（`BlocklistCatalogSync.swift`）会：

1. 直接从 `source.sourceURL` 拉取列表字节，并执行大小上限。
2. 计算 SHA-256，只有当校验和在目录的 `accepted_source_hashes` 里时才接受这些字节。
3. 若对不上，就回落到上一份正常的本地缓存，或者**故障即关闭**（`checksumMismatch`）——除非该来源明确允许直接做上游轮换。
4. 在本地解析/归一化/去重。
5. 把每一份解析出来的规则集都过一遍 `DomainRuleSet.lavaSecProtectedDomains`（`AppConfiguration.swift:262-276`），这样上游列表就永远没法拦掉 Lava / Apple / 身份提供方的域名。

**受保护域名集合**（在启用前会被过滤掉）：`apple.com`、`icloud.com`、`mzstatic.com`、`itunes.apple.com`、`apps.apple.com`、`lavasecurity.com`、`lavasecurity.app`、`api.lavasecurity.app`、`lavasec.app`、`lavasec.example`、`accounts.google.com`、`google.com`（全部按后缀匹配）。Worker 在计算元数据时会套用一个等价的 `PROTECTED_SUFFIXES` 过滤器；不管怎样，设备端都会再校验一遍。

### 5.2 精选来源（已实现） {#52-curated-sources-implemented}

`DefaultCatalog.curatedSources`（`BlocklistModels.swift:232-243`）列出了 **10** 个来源：

| 来源 | 许可证 |
|---|---|
| Block List Basic | Unlicense |
| Block List Project Phishing | Unlicense |
| Block List Project Scam | Unlicense |
| Block List Project Ransomware | Unlicense |
| Phishing.Database Active Domains | MIT |
| HaGeZi Multi Light | GPL-3.0 |
| HaGeZi Multi Normal | GPL-3.0 |
| HaGeZi Multi PRO mini | GPL-3.0 |
| HaGeZi Multi PRO | GPL-3.0 |
| OISD Small | GPL-3.0 |

`guardrailSources` 是空的。GPL 来源（HaGeZi、OISD）在目录里是可见的，但**需要手动开启 / 默认是关的**，要等法务批准；Worker 会把上线时的同步/发布限定在 `source_url_only` 加上允许的 GPL 前缀（`hagezi-` / `oisd-`）范围内。

### 5.3 免费用户默认启用的列表（已实现） {#53-default-enabled-lists-for-free-users-implemented}

实际的免费默认配置是 `OnboardingDefaults.lavaRecommendedDefaults`（`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`），它会启用 **Block List Project Phishing + Block List Project Scam**，搭配 device-DNS 解析器预设（`resolverPresetID = DNSResolverPreset.device.id`），并开启 device-DNS 回落。

这套免费默认是**由 `defaultEnabled` 产生的**，不是写死的。`blockListProjectPhishing`（`BlocklistModels.swift:139`）和 `blockListProjectScam`（`BlocklistModels.swift:148`）都设了 `defaultEnabled: true`，而 `DefaultCatalog.recommendedDefaultSourceIDs`（`BlocklistModels.swift:250-252`）是由 `curatedSources.filter(\.defaultEnabled)` 推导出来的。源码里的注释（`BlocklistModels.swift:246-249`）把 `defaultEnabled` 称作「全新安装默认值的唯一事实来源」，与后端目录的 `default_enabled` 列相对应。`defaultEnabled` 经由 `recommendedDefaultSourceIDs` 一路流到 `OnboardingDefaults`，是真正生效的机制——把某个来源上的这个标志翻一下，就能改默认值。

> **默认值的事实来源（以代码为准）。** 任何说「Block List Basic 是唯一默认」的计划/目录文案，对设备而言都是错的；设备靠 `defaultEnabled: true` 随包启用的是 Phishing + Scam，而 iOS 上的 `BlocklistSource.defaultEnabled` 标志才是权威的、真正生效的机制。后端目录的 `default_enabled` 列已经被一次迁移重新对齐到同一套 Phishing + Scam，所以现在 `/v1/catalog` 提供的元数据和客户端一致了。公开站点上那句「Enabled blocklists 3 → 10」的文案仍然是**过时的**——真正的关卡是 500K/2M 的过滤规则预算，而不是列表数量。

### 5.4 只发布来源 URL 的 GPL 分发模型（已实现） {#54-source-url-only-gpl-distribution-model-implemented}

**只发布来源 URL（source-url-only）** 是为满足 GPL / 知识产权合规而采用的分发模型：Lava Security 只发布上游 URL + 接受的哈希；列表由设备自己去拉取并解析。Lava Security **从不**存储、镜像、转换或提供任何第三方拦截列表的字节。这一模型**取代了被弃用的 R2 镜像方案**（最初那套「裸 R2 镜像」计划已在 2026-05-25 回退）。

在 Worker 这边，`syncOneBlocklist` 会拉取每个上游来源，并对它做归一化 + 哈希（算出 `source_hash`、`normalized_hash`、`entry_count`），但写入的是 `raw_r2_key = null` / `normalized_r2_key = null`——只有目录 JSON 元数据会进到 R2。`check-gpl-blocklist-distribution.sh` 是把整套模型钉死的 CI 守卫：不许有镜像/转换代码、不许有 Lava 的产物/下载 URL、不许有 GPL 来源默认启用、不许 Worker 往 R2 里写列表字节、不许出现「Lava 自托管镜像」的文案、不许打包 GPL 的 `.txt`/`.json`，并且迁移脚本 + 法律文档里必须出现 `source_url_only`。

> **许可证说明：** Lava Security 的第一方代码以 **AGPL-3.0** 发布（`LICENSE` 文件就是 GNU AGPL v3，与 README 徽章一致）。第三方拦截列表（HaGeZi、OISD）则按它们各自的上游许可证保持 **GPL-3.0**——只发布来源 URL 这套模型存在的意义，恰恰就是让 Lava Security 能用上它们，又从不重新分发任何 GPL 许可的字节。这里的 GPL-3.0 是那些上游列表的属性，而不是 Lava Security App 的属性。

---

## 6. 状态汇总 {#6-status-summary}

| 领域 | 状态 |
|---|---|
| DNS 查询优先级（bootstrap > pause > filter） | 已实现 |
| 过滤决策优先级（guardrail > allowlist > blocklist > default-allow） | 已实现 |
| 安全护栏优先级槽位（已接线；目前随包发布时没有条目） | 已实现 |
| DoH / DoH3（基于观测的 h3 标签） | 已实现 |
| DoT（每端点 4 连接池、8 秒空闲刷新、一次新连接重试） | 已实现 |
| DoQ（每次查询新建连接、4 通道并发） | 已实现 |
| DoQ 连接复用 | 已放弃 / 延后到 iOS 26 门槛 |
| 解析器降级 + 逐端点故障转移 + Device DNS 回落 | 已实现 |
| 过滤规则预算（免费 500K / Plus 2M） | 已实现 |
| ~326 万条规则的设备护栏（50 MiB NE 上限之下定 32 MB 目标） | 已实现 |
| compact 快照的零拷贝 mmap | 已实现 |
| 只发布来源 URL 的目录 + 直接上游拉取 + 哈希校验 | 已实现 |
| 受保护域名过滤 | 已实现 |
| 免费默认 = Phishing + Scam（不是 Basic） | 已实现（目录已重新对齐一致） |
| 第一方 Lava Security 代码许可证 | AGPL-3.0（`LICENSE`）；第三方列表上游保持 GPL-3.0 |

---

## 另见 {#see-also}

- [`../product/overview.md`](../product/overview.md) —— 产品一句话简介、隐私承诺、各个标签页。
- 分层与变现（内部参考）—— Lava Security Plus，以及作为分层指标的过滤规则预算。
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) —— 只发布来源 URL 的合规决定。
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) —— 上游拦截列表/解析器的许可证与署名。
