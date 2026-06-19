---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# iOS 客户端架构 {#ios-client-architecture}

> 读者对象：在 `lavasec-ios` 里干活的 iOS 工程师。

Lava Security 是一款隐私优先的 iOS App，它通过设备上的 NetworkExtension 数据包隧道，在本机直接做 DNS 过滤，拦掉那些已知有风险、没人想要的域名——而且不会把你的浏览流量绕到 Lava 的服务器上。本文讲的是 iOS 客户端是怎么搭起来的：有哪些 target、App 怎么跟它的隧道扩展对话、VPN 的生命周期、Guardian 状态模型、Live Activity 和小组件、上手引导流程，以及 App 侧那个管状态的家伙（`AppViewModel`）。

想看整个系统的全貌（App、目录 Worker、还有 Supabase），请看 [系统概览](./system-overview.md)。

---

## 1. Target 与各自的职责 {#1-targets-responsibilities}

客户端会打包成三个可执行的 target，外加一个共享的核心库。这三个 target 都加入了同一个 **App Group**（`group.com.lavasec`），并都链接了 `LavaSecCore`。

| Target | Bundle id | 职责 |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | 这个 SwiftUI App。它管 UI、持有 NetworkExtension 权限，并通过 `NETunnelProviderManager` 控制隧道。VPN 生命周期以 `AppViewModel` 为准。 |
| **数据包隧道** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider` 的子类 `PacketTunnelProvider`（也叫 `LavaSecTunnel`）。它解析 DNS 数据包、取出被查询的域名、拿它去比对内存映射的已编译快照，再把放行的查询转发到上游。受限于每个进程约 50 MiB 的 jetsam 内存上限。 |
| **小组件** (`LavaSecWidget`) | `com.lavasec.app.widget` | 一个 `WidgetBundle`，唯一成员是 `LavaProtectionLiveActivityWidget`——也就是 Live Activity / 灵动岛的呈现。 |

共享代码放在两个地方：

- **`LavaSecCore`**（`Sources/LavaSecCore/`）——与平台无关的核心：过滤引擎、解析器传输、快照/预算的算术、防护存储，以及 `GuardianMascotAnimation` 核心。按照 `VPNLifecycleController.swift:3-6` 的说法，NetworkExtension 类型被有意挡在这个模块之外，这样它的生命周期逻辑就能用假对象来测试；NetworkExtension 那套实现由 App target 提供。
- **`Shared/`**——会被编进不止一个 target 的代码（比如 `AppGroup.swift`、`LavaActivityAttributes.swift`、`LavaProtectionCommandService.swift`、`SoftShieldGuardian.swift`、`LavaLiveActivityIntents.swift`）。

数据包隧道的内部细节（DNS 解析、已编译快照、加密的解析器传输，以及过滤规则预算）在 [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md) 里有深入讲解。本文聚焦在 App 侧的架构，以及 App 和扩展之间的那条边界。

---

## 2. App ↔ 扩展之间的 IPC {#2-app-extension-ipc}

App 和数据包隧道扩展是两个分开的进程。它们靠三种机制来协同，全都以 App Group 为锚点。

### App Group 容器 {#app-group-container}

`group.com.lavasec` 是那个共享容器，它让 App、隧道和小组件能读写同一份 `LavaSecCore` 状态和配置。`LavaSecAppGroup`（`Shared/AppGroup.swift`）把每一个共享键和文件名都集中管理起来，这样几个进程就绝不会在字符串常量上各跑各的，包括：

- 已编译快照的产物（`filter-snapshot.compact`、`filter-snapshot.json`）、序列化后的 `app-configuration.json`、隧道健康状态（`tunnel-health.json`）、诊断信息，以及网络活动日志。
- 用于防护会话和暂停状态的共享 `UserDefaults` 键。这些键直接给 `LavaSecCore` 存储起了别名（`AppGroup.swift:38-41`）——`ProtectionSessionStore.Keys`、`ProtectionPauseStore.Keys`——好让 App、隧道和 Live Activity intent 共用同一套键布局、同一个修订计数器、同一套去重方案。
- 目录缓存目录，以及设备上的调试日志文件。

容器 URL 通过 `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)` 解析出来。

### 命令 / provider message（控制通路） {#command-provider-message-the-control-path}

App 用 **`sendProviderMessage`** 来驱动隧道，所有命令都走这条路。`AppViewModel.sendTunnelMessage(_:)`（`AppViewModel.swift:7215`）从缓存的 manager 拿到当前活跃的 `NETunnelProviderSession`，然后调用 `session.sendProviderMessage(...)`。载荷由 `LavaSecProviderMessageCodec`（`AppGroup.swift:55-79`）编码成一个小小的 JSON 信封，里面带着一个消息 `kind` 和一个可选的 `operationID`（用来做端到端的延迟追踪）。

能识别的消息 kind 都是 `LavaSecAppGroup` 上的常量：

| 消息常量 | 在隧道里的效果 |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | 强制重新加载已编译的过滤快照。 |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | 只重新读取共享的暂停状态。 |
| `reloadConfigurationMessage` (`"reload-configuration"`) | 重新加载配置；只有*解析器身份*发生变化才会触发一次可见的重连。 |
| `clearDiagnosticsMessage`、`clearFilteringCountsMessage`、`clearNetworkActivityLogMessage`、`flushTunnelHealthMessage` | 诊断/日志维护。 |

在隧道这一侧，`PacketTunnelProvider.handleAppMessage(_:completionHandler:)`（`PacketTunnelProvider.swift:729`）会解码这个信封，并按 `kind` 做分支。值得注意的是，`reload-configuration` 会加载新配置，好让非解析器字段（诊断开关、付费状态）生效，但只有当解析器身份真的变了，它才会重置 DNS 运行时并重新套用隧道网络设置——也就是一次可见的重连（`PacketTunnelProvider.swift:768-792`）。诊断开关或付费状态的变化，绝不会掐断正在跑着的连接。

App 的 `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` 这两个辅助方法（`AppViewModel.swift:7062`/`7070`）只是发这些消息的薄薄一层包装。

### 为什么 App→隧道的控制要用 provider message {#why-provider-messages-for-apptunnel-control}

**`sendProviderMessage` 是 App→隧道唯一的控制通路——没有 App→隧道的 Darwin 信号。** 早先有个设计：暂停时投递一个 `CFNotificationCenter` 的 Darwin 信号，再在扩展里去观察它，但它在 NetworkExtension 进程里从来没能可靠地触发过，于是被移除了。命令服务不再调 `CFNotificationCenterPostNotification`，隧道也不再加 `CFNotificationCenterAddObserver`——这两点都由源码内省测试断言为缺失（命令服务那边的 post 见 `Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574`；隧道这边的 observer 见 `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847`），以防它被重新塞回来。（命令服务和隧道里还留着的那些 `import Darwin` 行，是为了 `flock`/socket 这些原语，不是为通知。）

反方向上倒是真的还有一条 Darwin 通路。隧道会给 App 推一个「健康状态变了」的轻推：`TunnelHealthSignal.DarwinProtectionSignalNotifier`（`Sources/LavaSecCore/TunnelHealthSignal.swift`）在 `com.lavasec.protection.tunnel-health-changed` 这个频道上调 `CFNotificationCenterPostNotification`（频道名住在 `TunnelHealthSignal.swift` 里，不在 `AppGroup.swift`），App 则通过 `DarwinNotificationObserver`（`LavaSecApp/DarwinNotificationObserver.swift`，`CFNotificationCenterAddObserver`）观察它，并在 `AppViewModel` 里接好线去调 `handleTunnelHealthNudge()`。这条隧道→App 的健康轻推被 `LavaLiveActivitySourceTests.swift:1059-1075` 断言为*存在*。

至于 App→隧道的控制，暂停是这么送达的：写入共享的 `ProtectionPauseStore`，紧接着发 `reload-protection-pause` 这个 provider message，好让隧道去跑 `refreshProtectionPauseStateOnly`。`AppViewModel.swift:4995-4996` 把这条规矩直接写明了：App「也从不依赖快照的 Darwin observer，永远用 `sendProviderMessage`」。请把「App Group（共享状态）+ `sendProviderMessage`（唤醒/控制信号）」这一对当成 App→隧道的控制通路。

### Live Activity 命令服务 {#live-activity-command-service}

`LavaProtectionCommandService.perform(_:)`（`Shared/LavaProtectionCommandService.swift`）是灵动岛 / Live Activity 操作（`LavaLiveActivityActionRequest`：`pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`、`resume`、`reconnect`）的入口。`LavaLiveActivityIntents.swift` 里的那些 `LiveActivityIntent` 跑在 App 进程里（App 进程持有 NetworkExtension 权限），所以：

- **暂停 / 恢复** 会流经一把跨进程的文件锁（`protection-command.lock`，`flock`）以及 `LavaSecCore` 的 `ProtectionPauseStore` / `ProtectionSessionStore`，由它们来负责铸造修订号和重复命令的去重（`commandID` 把调用方的操作 id 串了进来，这样一条被重发的命令就没法铸出第二个修订号）。结果会排上一个带修订号保护的 Live Activity 更新。
- **重新连接** 是直接处理的（`performReconnect`，`LavaProtectionCommandService.swift:112-135`）：它调 `loadAllFromPreferences`，再通过 `startVPNTunnel()` 启动第一个已安装的隧道 manager（因为 `loadAllFromPreferences` 本就已经限定在这个 App 自己的 NE 配置范围内，那第一个 manager 就是 Lava 的——这一点跟 `VPNLifecycleController.matchingManagers()` 不一样，它不做显式的身份匹配）。Connect-On-Demand 本来就开着，所以这步只是逼它立刻连上；连上之后，App 的状态对齐会把 Live Activity 拉回到 `.on`。

---

## 3. VPN 生命周期与控制 {#3-vpn-lifecycle-control}

`AppViewModel`（`@MainActor final class`，`AppViewModel.swift:723`）是 App 里 VPN 生命周期的权威来源。它负责编排开启/关闭、缓存当前活跃的 `NETunnelProviderManager`，并把状态发布给 SwiftUI。

### Manager 的挑选与生命周期算术 {#manager-selection-and-lifecycle-math}

那套可复用、不依赖 NetworkExtension 的生命周期逻辑住在 `VPNLifecycleController<Repository>`（`Sources/LavaSecCore/VPNLifecycleController.swift`）里。App 提供基于 `NETunnelProviderManager` 的 `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting` 实现；控制器负责：

- **挑选与去重**——`matchingManagers()` 通过 `LavaTunnelConfigurationIdentity.matches(...)` 筛出归 Lava 所有的 manager，按 `selectionPriority` 排序（活跃的优先，然后按规范的显示名），并由 `removeDuplicateManagers(keeping:)` 收敛到唯一的幸存者。
- **连接/停止的等待**——`waitForConnect` / `waitForStop` 会带着一点 `startGraceInterval` 的容差去轮询实时连接状态，因为刚 `startVPNTunnel` 完，连接有可能短暂读到一个非 pending 的状态，之后 iOS 才把它切到 `.connecting`。

### 开启 / 关闭 {#turn-on-turn-off}

`enableProtection(...)`（`AppViewModel.swift:5764`）是**缓存优先**的：当当前配置已经有一份确认可复用的备好产物时，VPN 可以直接从缓存里立刻拉起来，与此同时一个在途的目录同步会在后台继续刷新，`performCatalogSync` 在完成时再把正在跑的隧道对齐一下。只有在压根没有可用东西可以起步时（比如用户刚改了启用列表的集合，把缓存产物的身份作废了），它才会卡在同步上等。

`disableProtection(...)`（`AppViewModel.swift:5972`）会*先*把 Connect-On-Demand 关掉、*再*停隧道，这样 iOS 才不会立刻又把它连回来。`setManagerOnDemand(_:on:)`（`AppViewModel.swift:6253`）会装一条 `NEOnDemandRuleConnect`（接口匹配 `.any`）并保存偏好设置——必须保存（光设置还不行），iOS 才会认这个改动。

### 状态观测（外加一个发热的小提醒） {#status-observation-and-a-heat-caveat}

`AppViewModel` 观察 `.NEVPNStatusDidChange`（`AppViewModel.swift:1034-1056`），并发布 `vpnStatus`/`isVPNConfigurationInstalled`。关键在于，当某个 manager 已经被缓存时，它读的是这个缓存 manager 的实时连接，而不是逼着去做一次 `loadAllFromPreferences` 刷新：`loadAllFromPreferences` 自己会再次发出 `NEVPNStatusDidChange`，而在观察者里强行刷新会造成一场自我维持的风暴——源码里的注释（`AppViewModel.swift:1046-1048`）记下了实测约 370 事件/秒，以及它引发的 134% CPU 发热回归。发布出去的属性只在真正发生切换时才变，这样闲置时的滴答声就不会再去让 SwiftUI 作废重算。

### 故障即关闭的 on-demand 对齐 {#fail-closed-on-demand-reconcile}

Connect-On-Demand 可能在启动时（或者在 iOS 因网络变化把隧道拆掉之后）把隧道**冷**拉起来，赶在 App 还没推送快照之前。一个没有可复用持久化快照的冷隧道会以**故障即关闭**的方式加载——它会拦掉所有流量——而且自己永远缓不过来。`AppViewModel` 在两条启动路径里处理这件事，两条都以「上手引导已完成」为前提（`hasCompletedOnboarding`，对应 `@AppStorage("hasSeenLavaOnboarding")` 标志）：

- **引导完成之后**——`reconcileTunnelSnapshotAfterLaunch()`（`AppViewModel.swift:7122`）在启动时只要防护处于活跃状态就会跑：它备好启动快照、持久化共享状态，并发 `reload-snapshot` 让隧道把自己真正的规则重新加载进来，脱离故障即关闭。故障即关闭仍然是那个安全的默认值；这步只是赶紧把它替换掉。（修复了这样一个问题：App 重启后、Connect-On-Demand 还把隧道开着时，过滤器显示成红色 / 流量被拦掉。）
- **引导进行中**——`neutralizeInheritedProtectionDuringOnboarding()`（`AppViewModel.swift:7181`）在引导还没走完时，会赶在任何网络动作*之前*跑。iOS 在删 App 时并不可靠地移除 VPN 配置文件，所以重装可能会继承到一份没人管、还开着 on-demand 的孤儿配置，它会在用户还没选任何拦截列表之前就把一个故障即关闭的冷隧道拉起来。这条路会**移除**这份配置（`removeFromPreferences`），而不是给它存一个修改——`saveToPreferences` 会在这次安装并不拥有的配置文件上重新弹出「添加 VPN 配置」的系统提示，把那个对话框在 App 初始化时就触发，赶在引导面板渲染之前。在干净安装上它是个空操作，继承来的配置本就已经失效时也一样。

---

## 4. Guardian / 状态模型 {#4-guardian-state-model}

这里有两套相关的状态词汇：一套是连接性的*评估*，一套是 Guardian *吉祥物*的状态。

### 连接性评估 {#connectivity-assessment}

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)`（`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`）把一个 `TunnelHealthSnapshot` 映射成一个 `ProtectionConnectivityAssessment`，它有**六种严重程度**和**两种动作**：

- 严重程度：`healthy`、`recovering`、`usingDeviceDNSFallback`、`dnsSlow`、`networkUnavailable`、`needsReconnect`。
- 主要动作：`turnOff` 或 `reconnect`。

这一份评估同时驱动 App 内的防护界面，以及（再往下映射后的）灵动岛状态，所以两者永远不会对不上。

### Guardian 吉祥物状态 {#guardian-mascot-states}

Soft Shield Guardian 吉祥物正好有**七种**情绪状态——`GuardianMascotState`（`GuardianMascotAnimation.swift:3`）：`sleeping`、`waking`、`awake`、`paused`、`retrying`、`concerned`、`grateful`。每个状态都声明了自己的 `allowedNextStates`，所以状态切换是受约束的（比如 `grateful` 只能回到 `awake`；`GuardianMascotAnimation.swift:12-29`）。语义如下：

- `retrying` = 平静地自我修复。
- `concerned` = 温和地求助。
- `grateful` = 庆祝式的成功（用在引导/设置界面，不在连接性映射里）。

`GuardianMascotAnimation` 是 `LavaSecCore` 里那套程序化的动画核心；`SoftShieldGuardian`（`Shared/SoftShieldGuardian.swift`）是 SwiftUI 的渲染部分，并支持由 `GuardianShieldStyle` 选定的自定义皮肤（显示名 Original、Fire Opal、Amethyst、Obsidian、Cherry Quartz、Emerald、Kiwi Crème——`LavaActivityAttributes.swift:5-56`，`displayName` 的映射在第 18-35 行）。有几个原始值跟它们的显示名对不上（比如 `fireOpal = "emberObsidian"`、`cherryQuartz = "strawberryObsidian"`，还有 `purpleObsidian` 渲染成 "Amethyst"），所以请持久化原始值，别存那个标签。

### 这两套是怎么连起来的 {#how-the-two-connect}

Live Activity 的 `LavaActivityAttributes.ProtectionState`（`Shared/LavaActivityAttributes.swift`）通过 `guardianState` 把评估桥接到一个吉祥物状态：`on → awake`、`paused → paused`、`reconnecting`/`networkUnavailable → retrying`、`needsReconnect → concerned`（`LavaActivityAttributes.swift:95-105`）。`AppViewModel` 给灵动岛挑的防护状态也来自同一个 `protectionConnectivityAssessment`（`AppViewModel.swift:3131-3147`）：`networkUnavailable` 严重程度变成 `.networkUnavailable`，`recovering` 变成 `.reconnecting`，`reconnect` 这个主要动作变成 `.needsReconnect`，其余情况则是 `.on`。

> 注意：`LavaTier`（平静 → **Floor** / 庆祝 → **Window** / 技术 → **Workshop** 这个设计系统的深度枚举）随设计系统层一起发布（`LavaSecApp/LavaDesignSystem/LavaTokens.swift`），并接进了一些代表性界面——见 [设计系统](../design-system/overview.md)。它管的是设计系统的深度，跟本文讲的防护/隧道客户端这条路无关。

---

## 5. Live Activity 与小组件 {#5-live-activity-widget}

小组件 target 只渲染 Live Activity 和灵动岛。`LavaSecWidgetBundle`（`LavaSecWidget/LavaSecWidget.swift`）只暴露一个 `LavaProtectionLiveActivityWidget`，它是一个 `ActivityConfiguration(for: LavaActivityAttributes.self)`，包含：

- 一个锁屏视图、一个展开的灵动岛中央区域，以及紧凑/极简的呈现——它们会渲染 `SoftShieldGuardian` 加一个状态字形。紧凑/锁屏视图会在一个每秒一拍的 `TimelineView` 上重算*实际生效*的防护状态，这样暂停倒计时就算没收到推送也能保持实时。

`LavaActivityAttributes.ContentState` 携带 `protectionState`、一个 `resumeDate`（用于暂停倒计时）、`pauseRequiresAuthentication`，以及选定的 `shieldStyle`。解码是宽容的——缺了 `shieldStyle` 就回落到 `.original`——这样旧的 Live Activity 载荷也能继续用。

在 App 这边，`LavaLiveActivityController`（`LavaSecApp/LavaLiveActivityController.swift`）持有实时的 `Activity<LavaActivityAttributes>`：它观察 ActivityKit 授权的变化、只在手机/平板形态上提供 Live Activity，并由 `reconcile(...)` 来开始/更新/结束这个 activity，好对上所请求的防护状态。`AppViewModel.reconcileLiveActivity()`（`AppViewModel.swift:3069`）是唯一的那个漏斗，它重算出期望状态并调用控制器。灵动岛上的按钮会派发 `LiveActivityIntent`，后者会按 [§2](#2-app-extension-ipc) 里讲的去调 `LavaProtectionCommandService`。

---

## 6. 上手引导流程 {#6-onboarding-flow}

上手引导由 `LavaOnboardingView`（`LavaSecApp/OnboardingFlowView.swift`）呈现，并由 `RootView`（`RootView.swift:32`）里声明的 `@AppStorage("hasSeenLavaOnboarding")` 标志来把关。整个流程是一串 `OnboardingPage`（`OnboardingFlowView.swift:403-409`）：`lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`。

打包好的起始配置来自 `OnboardingDefaults`（`Sources/LavaSecCore/OnboardingDefaults.swift`）。`AppConfiguration.lavaRecommendedDefaults` 只启用那些宽松的推荐来源（Block List Project 的 钓鱼 + 诈骗），把解析器选为 **Device DNS**——`DNSResolverPreset.device`（id `device-dns`），也就是网络自带的 DNS；像 Google DoH 这类加密预设是选择性开启的，不会被提为默认值——它会启用 device-DNS 回落，并保持本地日志开着——同时 `protectionEnabled: false`，所以防护只有在用户主动选择时才会打开。`OnboardingDefaultsSummary` 会把这些选择格式化出来给人看（账户的默认值是「不使用账户继续」）。

在最后把 `hasSeenLavaOnboarding = true` 设上，就是它翻动了 `hasCompletedOnboarding`，进而把 [§3](#3-vpn-lifecycle-control) 里讲的启动对齐路径武装起来。在那之前，引导进行中的中和路径会一直挡着，不让任何继承来的故障即关闭隧道拦掉流量。

---

## 7. App 状态：`AppViewModel` {#7-app-state-appviewmodel}

`AppViewModel`（`@MainActor final class AppViewModel: ObservableObject`，`AppViewModel.swift:723`）是 App 侧的中央状态持有者。除了 VPN 生命周期，它还发布 UI 要绑定的那些界面状态，包括：

- **防护与隧道**——`vpnStatus`、`isVPNConfigurationInstalled`、`isConfiguringVPN`、`tunnelHealth`（`TunnelHealthSnapshot`）、`temporaryProtectionPauseUntil`，以及给用户看的 `vpnMessage`/`vpnMessageIsError`。
- **配置与目录**——`AppConfiguration`、`isSyncingCatalog`、`catalogVersion`/`catalogGeneratedAt`，以及已编译的规则数量（`compiledRuleCount`、`protectedRuleCount`、`compiledBlocklistRuleCount`）。
- **诊断**——`DiagnosticsStore` 和 `NetworkActivityLog`（全部在本地；见下方的隐私承诺）。
- **账户与备份**——`accountAuthState`、`encryptedBackupState`、`isAutomaticBackupEnabled`，以及 **Lava Security Plus** 的优惠/权益状态。
- **自定义与呈现**——`appearancePreference`、`lavaGuardLook`（`GuardianShieldStyle`）、`lavaGuardProgress`，以及 `usesLiveActivities`。

它把生命周期的串行化交给一个 `protectionActionOrchestrator`（这样后台的恢复就不会跟用户的一次开启交错在一起），持有缓存的 `tunnelManager`，并通过 [§2](#2-app-extension-ipc) 里那些 provider-message 辅助方法，把所有快照/配置/暂停的变化驱动到扩展那边。

> **隐私这件事怎么看。** DNS 过滤在这台设备上本地完成。`AppViewModel` 发布的诊断和网络活动界面都只存在本地——Lava 永远收不到你日常的 DNS 查询、浏览历史，或是逐域名的遥测数据。任何可选的账户备份都是**零知识**的（在设备上加密；Lava 顶多只能存到密文），通行密钥的恢复也一样——它的密钥在设备上由 PRF 派生，服务器手里没有任何秘密。服务器边界请看 [系统概览](./system-overview.md)。

---

## 相关文档 {#related-docs}

- [系统概览](./system-overview.md)——一屏看完整个系统：App、目录 Worker、还有 Supabase，外加各条信任边界和全文通用的状态图例。
- [DNS 过滤与拦截列表](./dns-filtering-and-blocklists.md)——本文只在控制边界上提到的那些数据包隧道内部细节：已编译的过滤引擎、加密的解析器传输（DoH / DoH3 / DoT / DoQ）、过滤规则预算、拦截列表目录，以及只给源 url 的再分发模型。
- [账户与零知识备份](./accounts-and-backup.md)——`AppViewModel` 所编排的登录提供方，以及那个零知识的备份信封（包括那个零知识、由 PRF 派生的通行密钥恢复槽）。
- [后端与数据](./backend-and-data.md)——`lavasec-api` 目录 Worker、Cloudflare R2，以及坐在 App↔服务器边界另一侧的 Supabase schema/RLS。
- [设计系统](../design-system/overview.md)——`LavaTier` 深度模型、Soft Shield Guardian 的七种状态和盾牌皮肤，以及客户端渲染时用的文案/本地化约定。
- [第三方声明](../legal/third-party-notices.md) 和 [GPL 只给源 url 的合规决定](../legal/gpl-source-url-only-compliance-decision.md)——客户端所消费的那条目录/过滤流水线背后的分发约束。
