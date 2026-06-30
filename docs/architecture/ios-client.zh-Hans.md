---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# iOS 客户端架构 {#ios-client-architecture}

> 读者对象：在 `lavasec-ios` 中工作的 iOS 工程师。

Lava Security 是一款隐私优先的 iOS App，它通过设备上的 NetworkExtension 数据包隧道在本机直接进行 DNS 过滤，拦截已知有风险及不需要的域名，且不会把你的浏览流量经由 Lava 的服务器转发。本文介绍 iOS 客户端的结构：包含哪些 target、App 与隧道扩展之间的边界、VPN 生命周期、Guardian 状态模型、Live Activity 与小组件、上手引导流程，以及 App 侧的状态持有者（`AppViewModel`）。

若需了解整个系统的全貌（App、目录 Worker 与 Supabase），请参阅 [系统概览](./system-overview.md)。

---

## 1. Target 与职责 {#1-targets-responsibilities}

客户端会打包成三个可执行的 target，外加一个共享的核心库。这三个 target 都加入了同一个 **App Group**（`group.com.lavasec`），并都链接了 `LavaSecCore`。

| Target | Bundle id | 职责 |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | 这个 SwiftUI App。它管 UI、持有 NetworkExtension 权限，并通过 `NETunnelProviderManager` 控制隧道。VPN 生命周期以 `AppViewModel` 为准。 |
| **数据包隧道** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider` 的子类 `PacketTunnelProvider`（也叫 `LavaSecTunnel`）。它解析 DNS 数据包、取出被查询的域名、拿它去比对内存映射的已编译快照，再把放行的查询转发到上游。受限于每个进程约 50 MiB 的 jetsam 内存上限。 |
| **小组件** (`LavaSecWidget`) | `com.lavasec.app.widget` | 一个 `WidgetBundle`，唯一成员是 `LavaProtectionLiveActivityWidget`——也就是 Live Activity / 灵动岛的呈现。 |

共享代码放在两个地方：

- **`LavaSecCore`**（`Sources/LavaSecCore/`）——与平台无关的核心：过滤引擎、解析器传输、快照/预算的算术、防护存储，以及 `GuardianMascotAnimation` 核心。根据 `VPNLifecycleController.swift:3-6`，NetworkExtension 类型被有意排除在该模块之外，使其生命周期逻辑可以用伪实现（fake）进行测试；基于 `NetworkExtension` 的实现由 App target 提供。
- **`Shared/`**——会被编进不止一个 target 的代码（比如 `AppGroup.swift`、`LavaActivityAttributes.swift`、`LavaProtectionCommandService.swift`、`SoftShieldGuardian.swift`、`LavaLiveActivityIntents.swift`）。

数据包隧道的内部细节（DNS 解析、已编译快照、加密的解析器传输，以及过滤规则预算）在 [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md) 中有深入讲解。本文聚焦于 App 侧的架构，以及 App 与扩展之间的边界。

---

## 2. App ↔ 扩展之间的 IPC {#2-app-extension-ipc}

App 与数据包隧道扩展是两个独立的进程。它们通过三种机制协同，且全部以 App Group 为锚点。

### App Group 容器 {#app-group-container}

`group.com.lavasec` 是共享容器，让 App、隧道和小组件能读写同一份 `LavaSecCore` 状态与配置。`LavaSecAppGroup`（`Shared/AppGroup.swift`）集中管理每一个共享键和文件名，使各进程绝不会在字符串常量上产生分歧，包括：

- 已编译快照的产物（`filter-snapshot.compact`、`filter-snapshot.json`）、序列化后的 `app-configuration.json`、隧道健康状态（`tunnel-health.json`）、诊断信息，以及网络活动日志。
- 用于防护会话和暂停状态的共享 `UserDefaults` 键。这些键直接给 `LavaSecCore` 存储起了别名（`AppGroup.swift:38-41`）——`ProtectionSessionStore.Keys`、`ProtectionPauseStore.Keys`——使 App、隧道和 Live Activity intent 共用同一套键布局、同一个修订计数器、同一套去重方案。
- 目录缓存目录，以及设备上的调试日志文件。

容器 URL 通过 `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)` 解析。

### 命令 / provider message（控制通路） {#command-provider-message-the-control-path}

App 通过 **`sendProviderMessage`** 驱动隧道，所有命令都走这条路径。`AppViewModel.sendTunnelMessage(_:)`（`AppViewModel.swift:7215`）从缓存的 manager 取得当前活跃的 `NETunnelProviderSession`，然后调用 `session.sendProviderMessage(...)`。载荷由 `LavaSecProviderMessageCodec`（`AppGroup.swift:55-79`）编码为一个小型 JSON 信封，其中携带一个消息 `kind` 和一个可选的 `operationID`（用于端到端的延迟追踪）。

能识别的消息 kind 都是 `LavaSecAppGroup` 上的常量：

| 消息常量 | 在隧道里的效果 |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | 强制重新加载已编译的过滤快照。 |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | 只重新读取共享的暂停状态。 |
| `reloadConfigurationMessage` (`"reload-configuration"`) | 重新加载配置；只有*解析器身份*发生变化才会触发一次可见的重连。 |
| `clearDiagnosticsMessage`、`clearFilteringCountsMessage`、`clearNetworkActivityLogMessage`、`flushTunnelHealthMessage` | 诊断/日志维护。 |

在隧道一侧，`PacketTunnelProvider.handleAppMessage(_:completionHandler:)`（`PacketTunnelProvider.swift:729`）会解码该信封，并按 `kind` 分支。值得注意的是，`reload-configuration` 会加载新配置，使非解析器字段（诊断开关、付费状态）生效，但只有当解析器身份确实发生变化时，它才会重置 DNS 运行时并重新套用隧道网络设置——即一次可见的重连（`PacketTunnelProvider.swift:768-792`）。诊断开关或付费状态的变化绝不会中断正在运行的连接。

App 的 `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` 这两个辅助方法（`AppViewModel.swift:7062`/`7070`）只是发送这些消息的轻量封装。

### 为什么 App→隧道的控制要用 provider message {#why-provider-messages-for-apptunnel-control}

**`sendProviderMessage` 是 App→隧道唯一的控制通路——不存在 App→隧道的 Darwin 信号。** 早期的一个设计会在暂停时投递一个 `CFNotificationCenter` Darwin 信号，并在扩展内观察它，但它在 NetworkExtension 进程中始终无法可靠触发，因此被移除。命令服务不再调用 `CFNotificationCenterPostNotification`，隧道也不再添加 `CFNotificationCenterAddObserver`——这两点都由源码内省测试断言为缺失（命令服务那边的 post 见 `Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574`；隧道这边的 observer 见 `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847`），以防它被重新塞回来。（命令服务和隧道里还留着的那些 `import Darwin` 行，是为了 `flock`/socket 这些原语，不是为通知。）

反方向上确实仍保留一条 Darwin 通路。隧道会向 App 推送一个「健康状态已变更」的轻推：`TunnelHealthSignal.DarwinProtectionSignalNotifier`（`Sources/LavaSecCore/TunnelHealthSignal.swift`）在 `com.lavasec.protection.tunnel-health-changed` 这个频道上调 `CFNotificationCenterPostNotification`（频道名位于 `TunnelHealthSignal.swift`，不在 `AppGroup.swift`），App 则通过 `DarwinNotificationObserver`（`LavaSecApp/DarwinNotificationObserver.swift`，`CFNotificationCenterAddObserver`）观察它，并在 `AppViewModel` 中接线调用 `handleTunnelHealthNudge()`。这条隧道→App 的健康轻推被 `LavaLiveActivitySourceTests.swift:1059-1075` 断言为*存在*。

至于 App→隧道的控制，暂停的送达方式是：写入共享的 `ProtectionPauseStore`，紧接着发送 `reload-protection-pause` 这个 provider message，使隧道运行 `refreshProtectionPauseStateOnly`。`AppViewModel.swift:4995-4996` 直接写明了这条规则：App「也从不依赖快照的 Darwin observer，始终使用 `sendProviderMessage`」。应将「App Group（共享状态）+ `sendProviderMessage`（唤醒/控制信号）」这一组合视为 App→隧道的控制通路。

### Live Activity 命令服务 {#live-activity-command-service}

`LavaProtectionCommandService.perform(_:)`（`Shared/LavaProtectionCommandService.swift`）是灵动岛 / Live Activity 操作（`LavaLiveActivityActionRequest`：`pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes` / `pause-configured`（Live Activity 上那个唯一的暂停按钮，时长取用户自定义的值）、`resume`、`reconnect`）的入口。`LavaLiveActivityIntents.swift` 里的那些 `LiveActivityIntent` 跑在 App 进程里（App 进程持有 NetworkExtension 权限），所以：

- **暂停 / 恢复** 会流经一把跨进程的文件锁（`protection-command.lock`，`flock`）以及 `LavaSecCore` 的 `ProtectionPauseStore` / `ProtectionSessionStore`，由它们负责修订号的铸造与重复命令的去重（`commandID` 串入调用方的操作 id，使被重新投递的命令无法铸出第二个修订号）。其结果会调度一次带修订号保护的 Live Activity 更新。
- **重新连接** 是直接处理的（`performReconnect`，`LavaProtectionCommandService.swift:112-135`）：它调 `loadAllFromPreferences`，再通过 `startVPNTunnel()` 启动第一个已安装的隧道 manager（因为 `loadAllFromPreferences` 本就已经限定在这个 App 自己的 NE 配置范围内，那第一个 manager 就是 Lava 的——这一点跟 `VPNLifecycleController.matchingManagers()` 不一样，它不做显式的身份匹配）。Connect-On-Demand 本就处于开启状态，因此这一步只是强制其立即连接；连接后，App 的状态对齐会将 Live Activity 恢复到 `.on`。

---

## 3. VPN 生命周期与控制 {#3-vpn-lifecycle-control}

`AppViewModel`（`@MainActor final class`，`AppViewModel.swift:723`）是 App 中 VPN 生命周期的权威来源。它负责编排开启/关闭、缓存当前活跃的 `NETunnelProviderManager`，并将状态发布给 SwiftUI。

### Manager 的选择与生命周期计算 {#manager-selection-and-lifecycle-math}

可复用、不依赖 NetworkExtension 的生命周期逻辑位于 `VPNLifecycleController<Repository>`（`Sources/LavaSecCore/VPNLifecycleController.swift`）。App 提供基于 `NETunnelProviderManager` 的 `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting` 实现；控制器负责：

- **选择与去重**——`matchingManagers()` 通过 `LavaTunnelConfigurationIdentity.matches(...)` 筛选出归 Lava 所有的 manager，按 `selectionPriority` 排序（活跃的优先，其次按规范显示名），并由 `removeDuplicateManagers(keeping:)` 收敛到唯一的存留项。
- **连接/停止的等待**——`waitForConnect` / `waitForStop` 以 `startGraceInterval` 容差轮询实时连接状态，因为刚执行完 `startVPNTunnel` 时，连接可能短暂读到一个非 pending 的状态，随后 iOS 才将其切换到 `.connecting`。

### 开启 / 关闭 {#turn-on-turn-off}

`enableProtection(...)`（`AppViewModel.swift:5764`）是**缓存优先**的：当当前配置存在一份确认可复用的预备产物时，VPN 会直接从缓存立即启动，同时一个在途的目录同步在后台刷新，`performCatalogSync` 在完成时再对齐正在运行的隧道。只有在没有任何可用的起始产物时（例如用户刚更改了启用列表集合，使缓存产物的身份失效），它才会阻塞等待同步。

`disableProtection(...)`（`AppViewModel.swift:5972`）会*先*关闭 Connect-On-Demand、*再*停止隧道，使 iOS 不会立即将其重新连接。`setManagerOnDemand(_:on:)`（`AppViewModel.swift:6253`）会安装一条 `NEOnDemandRuleConnect`（接口匹配 `.any`）并保存偏好设置——必须保存（仅设置不够），iOS 才会接受该改动。

### 状态观测（附一则发热的注意事项） {#status-observation-and-a-heat-caveat}

`AppViewModel` 观察 `.NEVPNStatusDidChange`（`AppViewModel.swift:1034-1056`），并发布 `vpnStatus`/`isVPNConfigurationInstalled`。关键在于，当某个 manager 已被缓存时，它读取的是该缓存 manager 的实时连接，而不是强制执行一次 `loadAllFromPreferences` 刷新：`loadAllFromPreferences` 本身会再次发出 `NEVPNStatusDidChange`，而在观察者中强制刷新会造成一场自我维持的风暴——源码中的注释（`AppViewModel.swift:1046-1048`）记录了实测约 370 事件/秒，以及由此引发的 134% CPU 发热回归。发布的属性只在真正发生切换时才变化，使空闲时的滴答不再令 SwiftUI 失效重算。

### 故障即关闭的 on-demand 对齐 {#fail-closed-on-demand-reconcile}


Connect-On-Demand 可能在启动时（或在 iOS 因网络变化拆除隧道之后）将隧道**冷**启动，发生在 App 尚未推送快照之前。一个没有可复用持久化快照的冷隧道会以**故障即关闭**的方式加载——它会拦截所有流量——并且无法自行恢复。`AppViewModel` 在两条启动路径里处理这件事，两条都以「上手引导已完成」为前提（`hasCompletedOnboarding`，对应 `@AppStorage("hasSeenLavaOnboarding")` 标志）：

- **引导完成之后**——`reconcileTunnelSnapshotAfterLaunch()`（`AppViewModel.swift:7122`）在启动时只要防护处于活跃状态便会运行：它准备启动快照、持久化共享状态，并发送 `reload-snapshot`，让隧道重新加载其真实规则，脱离故障即关闭。故障即关闭仍是安全的默认值；这一步只是迅速将其取代。（修复了以下问题：App 重启后、Connect-On-Demand 仍保持隧道开启时，过滤器显示为红色 / 流量被拦截。）
- **引导进行中**——`neutralizeInheritedProtectionDuringOnboarding()`（`AppViewModel.swift:7181`）在引导尚未完成时，会在任何网络操作*之前*运行。iOS 在删除 App 时并不能可靠地移除 VPN 配置文件，因此重装可能继承到一份无人管理、仍开启 on-demand 的孤儿配置，它会在用户尚未选择任何拦截列表之前就启动一个故障即关闭的冷隧道。这条路径会**移除**该配置（`removeFromPreferences`），而不是为其保存一处修改——在这次安装并不拥有的配置文件上，`saveToPreferences` 会重新弹出「添加 VPN 配置」的系统提示，使该对话框在 App 初始化时即触发，早于引导面板的渲染。在干净安装上它为空操作，继承的配置本已失效时亦然。

---

## 4. Guardian / 状态模型 {#4-guardian-state-model}

存在两套相关的状态词汇：一套是连接性*评估*，另一套是 Guardian *吉祥物*状态。

### 连接性评估 {#connectivity-assessment}

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)`（`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`）把一个 `TunnelHealthSnapshot` 映射成一个 `ProtectionConnectivityAssessment`，它有**六种严重程度**和**两种动作**：

- 严重程度：`healthy`、`recovering`、`usingDeviceDNSFallback`、`dnsSlow`、`networkUnavailable`、`needsReconnect`。
- 主要动作：`turnOff` 或 `reconnect`。

这一份评估同时驱动 App 内的防护界面，以及（进一步映射后的）灵动岛状态，因此两者永远不会出现不一致。

**诚实下限（v1.0）。** 一次当前的、尚未被覆盖的 DNS 冒烟探测失败绝不能被判读为 `.healthy`——评估会持续呈现 `.recovering`，直到某次探测真正成功为止，从而使一个卡死的主解析器上由回退承载的流量不再被标记为「已保护」。重连逻辑依据的是 `consecutiveDNSSmokeProbeFailureCount` 和 `lastPrimaryUpstreamSuccessAt`（仅针对主解析器），而不是那套通用的上游计数器；而一个始终可达、却持续**拒绝**该已知正常探测的解析器（劫持／强制门户／陈旧），会通过一个按解析器身份限定范围的 `consecutiveRejectedSmokeResponseCount`（LAV-87）被升级为值得重启，即使在连接频繁变动的漫游网络上、通用连续计数不断被重置时亦然。

### 连通性通知 {#connectivity-notifications}

`ProtectionConnectivityNotificationPolicy`（`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`）把评估转化成最多一条尚未处理的本地通知，并做节流（600 秒）和去重。v1.0 增加了：

- 一种独立的 **`dnsSlow`** 类型（「Lava DNS is slow」）——DNS 慢以前复用 `reconnectNeeded` 类型，因此一次真正的中断无法将其取代。
- **升级／取代**——一个严格更紧急的问题（只有 `reconnectNeeded` 高于其余所有）可以取代一条已存在的、排名更低的横幅，绕过「问题已在等待处理」这道守卫以及节流限制，从而使一次 Device-DNS 回退之后发生的卡死呈现出可操作的「Reconnect」提示，而不是让一条令人安心的横幅持续挂着。
- 一次 **持久化迁移**（`ProtectionConnectivityNotificationStore`，schema v2，通过 `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded` 接线）会将一个遗留的、尚未处理的 `reconnect-needed` 标记降级为 `dnsSlow`，使升级机制在跨版本升级时也能正常工作。

### Device-DNS 捕获重试 {#device-dns-capture-retry}

当生效的配置依赖设备解析器时（作为主解析器或回退），一次网络切换／唤醒可能使隧道持有一份空的系统解析器捕获——一处无声的卡死。`DeviceDNSFallbackPolicy` 驱动一次**有上限的重试**（`shouldRetryDeviceDNSCapture`，`deviceDNSCaptureRetryInterval` 1 秒，`deviceDNSCaptureMaxRetryAttempts` 5）：隧道每秒重新读取一次系统解析器，最多尝试五次，直到捕获结果非空，然后就地采用它——无需重启隧道就自动恢复（事件 `device-dns-capture-retry` / `-exhausted`）。对于纯 DoH/DoT/DoQ 的配置，它是个空操作（`currentConfigurationDependsOnDeviceDNS()`）。

### Guardian 吉祥物状态 {#guardian-mascot-states}

Soft Shield Guardian 吉祥物恰好有**七种**情绪状态——`GuardianMascotState`（`GuardianMascotAnimation.swift:3`）：`sleeping`、`waking`、`awake`、`paused`、`retrying`、`concerned`、`grateful`。每个状态都声明了自己的 `allowedNextStates`，所以状态切换是受约束的（比如 `grateful` 只能回到 `awake`；`GuardianMascotAnimation.swift:12-29`）。语义如下：

- `retrying` = 平静地自我修复。
- `concerned` = 温和地求助。
- `grateful` = 庆祝式的成功（用在引导/设置界面，不在连接性映射里）。

`GuardianMascotAnimation` 是 `LavaSecCore` 中的程序化动画核心；`SoftShieldGuardian`（`Shared/SoftShieldGuardian.swift`）是 SwiftUI 的渲染部分，并支持由 `GuardianShieldStyle` 选定的自定义皮肤（显示名 Original、Fire Opal、Amethyst、Obsidian、Cherry Quartz、Emerald、Kiwi Crème——`LavaActivityAttributes.swift:5-56`，`displayName` 的映射在第 18-35 行）。有几个原始值与其显示名不一致（例如 `fireOpal = "emberObsidian"`、`cherryQuartz = "strawberryObsidian"`，以及 `purpleObsidian` 渲染为 "Amethyst"），因此请持久化原始值，而非标签。

### 这两套如何关联 {#how-the-two-connect}

Live Activity 的 `LavaActivityAttributes.ProtectionState`（`Shared/LavaActivityAttributes.swift`）通过 `guardianState` 把评估桥接到一个吉祥物状态：`on → awake`、`paused → paused`、`reconnecting`/`networkUnavailable → retrying`、`needsReconnect → concerned`（`LavaActivityAttributes.swift:95-105`）。`AppViewModel` 为灵动岛选取的防护状态也来自同一个 `protectionConnectivityAssessment`（`AppViewModel.swift:3131-3147`）：`networkUnavailable` 严重程度变成 `.networkUnavailable`，`recovering` 变成 `.reconnecting`，`reconnect` 这个主要动作变成 `.needsReconnect`，其余情况则是 `.on`。

> 注意：`LavaTier`（平静 → **Floor** / 庆祝 → **Window** / 技术 → **Workshop** 这一设计系统深度枚举）随设计系统层一起发布（`LavaSecApp/LavaDesignSystem/LavaTokens.swift`），并接入了若干代表性界面——参见 [设计系统](../design-system/overview.md)。它管控的是设计系统深度，与本文所述的防护/隧道客户端路径无关。

---

## 5. Live Activity 与小组件 {#5-live-activity-widget}

小组件 target 只渲染 Live Activity 和灵动岛。`LavaSecWidgetBundle`（`LavaSecWidget/LavaSecWidget.swift`）只暴露一个 `LavaProtectionLiveActivityWidget`，它是一个 `ActivityConfiguration(for: LavaActivityAttributes.self)`，包含：

- 一个锁屏视图、一个展开的灵动岛中央区域，以及紧凑/极简的呈现——它们会渲染 `SoftShieldGuardian` 及一个状态字形。紧凑/锁屏视图会在一个每秒一拍的 `TimelineView` 上重算*实际生效*的防护状态，使暂停倒计时即便未收到推送也能保持实时。

`LavaActivityAttributes.ContentState` 携带 `protectionState`、一个 `resumeDate`（用于暂停倒计时）、`pauseRequiresAuthentication`，以及选定的 `shieldStyle`。解码是宽容的——缺少 `shieldStyle` 时回落到 `.original`——使旧的 Live Activity 载荷也能继续使用。

在 App 这边，`LavaLiveActivityController`（`LavaSecApp/LavaLiveActivityController.swift`）持有实时的 `Activity<LavaActivityAttributes>`：它观察 ActivityKit 授权的变化、只在手机/平板形态上提供 Live Activity，并由 `reconcile(...)` 来开始/更新/结束这个 activity，好对上所请求的防护状态。`AppViewModel.reconcileLiveActivity()`（`AppViewModel.swift:3069`）是唯一的汇聚点，它重算出期望状态并调用控制器。灵动岛上的按钮会派发 `LiveActivityIntent`，后者会按 [§2](#2-app-extension-ipc) 所述调用 `LavaProtectionCommandService`。

---

## 6. 上手引导流程 {#6-onboarding-flow}

上手引导由 `LavaOnboardingView`（`LavaSecApp/OnboardingFlowView.swift`）呈现，并由 `RootView`（`RootView.swift:32`）中声明的 `@AppStorage("hasSeenLavaOnboarding")` 标志把关。整个流程是一串 `OnboardingPage`（`OnboardingFlowView.swift:403-409`）：`lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`。

随包发布的起始配置来自 `OnboardingDefaults`（`Sources/LavaSecCore/OnboardingDefaults.swift`）。`AppConfiguration.lavaRecommendedDefaults` 只启用那个宽松的推荐来源（Block List Basic），将解析器选为 **Device DNS**——`DNSResolverPreset.device`（id `device-dns`），即网络自带的 DNS；Google DoH 等加密预设为选择性开启，不会被提升为默认值——它会启用 device-DNS 回落，并保持本地日志开启——同时 `protectionEnabled: false`，因此防护仅在用户主动选择时才会开启。`OnboardingDefaultsSummary` 会将这些选择格式化以供显示（账户的默认值为「不使用账户继续」）。

在最后将 `hasSeenLavaOnboarding = true` 设上，正是这一步翻转了 `hasCompletedOnboarding`，进而启用 [§3](#3-vpn-lifecycle-control) 所述的启动对齐路径。在此之前，引导进行中的中和路径会持续阻止任何继承来的故障即关闭隧道拦截流量。

---

## 7. App 状态：`AppViewModel` {#7-app-state-appviewmodel}

`AppViewModel`（`@MainActor final class AppViewModel: ObservableObject`，`AppViewModel.swift:723`）是 App 侧的中央状态持有者。除了 VPN 生命周期，它还发布 UI 要绑定的那些界面状态，包括：

- **防护与隧道**——`vpnStatus`、`isVPNConfigurationInstalled`、`isConfiguringVPN`、`tunnelHealth`（`TunnelHealthSnapshot`）、`temporaryProtectionPauseUntil`，以及给用户看的 `vpnMessage`/`vpnMessageIsError`。
- **配置与目录**——`AppConfiguration`、`isSyncingCatalog`、`catalogVersion`/`catalogGeneratedAt`，以及已编译的规则数量（`compiledRuleCount`、`protectedRuleCount`、`compiledBlocklistRuleCount`）。
- **诊断**——`DiagnosticsStore` 和 `NetworkActivityLog`（全部在本地；参见下方的隐私承诺）。
- **账户与备份**——`accountAuthState`、`encryptedBackupState`、`isAutomaticBackupEnabled`，以及 **Lava Security Plus** 的优惠/权益状态。
- **自定义与呈现**——`appearancePreference`、`lavaGuardLook`（`GuardianShieldStyle`）、`lavaGuardProgress`，以及 `usesLiveActivities`。

它将生命周期的串行化委托给一个 `protectionActionOrchestrator`（使后台恢复不会与用户的开启操作交错），持有缓存的 `tunnelManager`，并通过 [§2](#2-app-extension-ipc) 中的 provider-message 辅助方法，将所有快照/配置/暂停的变化驱动到扩展。

> **隐私说明。** DNS 过滤在本设备上本地完成。`AppViewModel` 发布的诊断与网络活动界面均仅存储于本地——Lava 永远不会收到你日常的 DNS 查询、浏览历史或逐域名的遥测数据。任何可选的账户备份都是**零知识**的（在设备上加密；Lava 至多只能存储密文），通行密钥的恢复也是如此——其密钥在设备上由 PRF 派生，服务器不持有任何秘密。服务器边界请参阅 [系统概览](./system-overview.md)。

---

## 相关文档 {#related-docs}

- [系统概览](./system-overview.md)——一屏看完整个系统：App、目录 Worker 与 Supabase，外加各条信任边界以及全文通用的状态图例。
- [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md)——本文仅在控制边界处提及的数据包隧道内部细节：已编译的过滤引擎、加密的解析器传输（DoH / DoH3 / DoT / DoQ）、过滤规则预算、拦截列表目录，以及仅提供源 url 的再分发模型。
- [账户与零知识备份](./accounts-and-backup.md)——`AppViewModel` 所编排的登录提供方，以及那个零知识的备份信封（包括那个零知识、由 PRF 派生的通行密钥恢复槽）。
- [后端与数据](./backend-and-data.md)——`lavasec-api` 目录 Worker、Cloudflare R2，以及坐在 App↔服务器边界另一侧的 Supabase schema/RLS。
- [设计系统](../design-system/overview.md)——`LavaTier` 深度模型、Soft Shield Guardian 的七种状态和盾牌皮肤，以及客户端渲染时用的文案/本地化约定。
- [第三方声明](../legal/third-party-notices.md) 和 [GPL 只给源 url 的合规决定](../legal/gpl-source-url-only-compliance-decision.md)——客户端所消费的那条目录/过滤流水线背后的分发约束。
