---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 设计系统

> **读者对象：** 在 Lava Security iOS App 上做设计和工程的同学。
> **以谁为准：** 当这份文档和某个方案对不上时，**以代码为准** —— 出现分歧的地方会在正文里直接标出来。状态反映的是代码里确认过的真实情况，不是方案里的美好愿景。状态图例：**已实现**（已上线并在代码里确认）、**进行中**（部分落地）、**计划中**（设计好了，但还没动手）、**已放弃**（被否决或被回退）。

这份文档讲的是设计理念、LavaTier 深度词汇、Guardian 吉祥物、文案与命名约定、新手引导体验，以及国际化。这些界面背后的架构管线（编译目标、VPN 生命周期、Guardian/防护状态模型的接线），请看 [iOS 客户端](../architecture/ios-client.md)；产品层面的整体说明，请看 [产品概览](../product/overview.md)。

---

## 1. 理念：核心从容，深度靠探索 {#1-philosophy-calm-core-earned-depth}

Lava 面向的是不太懂技术的普通用户 —— 比如家长、长辈 —— 设计也就顺着这一点来。日常那一层界面对每个人来说都「直接就能用」，安安静静；更多的细节、惊喜和控制项，只有当用户主动去找的时候才会显现出来（**靠探索解锁**）。不催不闹、不吓人，技术上的那套机器在你没去找它之前一直隐身。

这套 **「核心从容，深度靠探索」** 的模型，落到产品里就是三个深度层级：

- **从容（Calm）** —— 默认那一层、人人最先看到、直接就能用的防护。
- **庆祝（Celebratory）** —— 你愿意才会看到的那点觉察感和小惊喜（连胜、解锁、成功时刻）。绝不催你。
- **技术（Technical）** —— DNS、诊断、各种统计。在你主动去找之前都看不到。

有两条贯穿全局的配色/语气规则，撑起这种从容的姿态：

- **红色只代表危险。** 红色专门留给危险和错误；从容的配色用的是绿色/橙色。这样红色才能一直保持可信，真出事时才像个货真价实的警报。危险红被收成 token `LavaStyle.dangerRed`，并把 `LavaStyle.errorText` 设成它的别名（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86），由各个视图里的错误文字来使用。防护色调走的是语义化的 `ProtectionTintRole` 角色表（lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7），而不是直接写死的 `.green`/`.orange`。确实还有几处直接写 `.red` 的地方残留着（比如 lavasec-ios: LavaSecApp/SettingsView.swift:697、LavaSecApp/SecurityController.swift:600、LavaSecApp/FiltersView.swift）—— 把它们迁到 `LavaStyle.dangerRed` 就是剩下要收的尾。
- **不用吓人的安全话术。** 文案要朴实、从容、实在。见 [§4 文案与命名](#4-copy-naming)。

### 今天已经存在的 token 化层 **（已实现）** {#the-tokenized-layer-that-exists-today-implemented}

设计系统是一层货真价实、已经 token 化的 SwiftUI 层，和 `LavaTier` 深度词汇（§2）并存：

- **`LavaStyle`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5）—— 自适应颜色的唯一来源：约 18 个语义色（`safeGreen`、`safeControlGreen`、`softGreen`、`lavaOrange`、`cream`、`ink`、`cardBackground`、`panelBackground`、`guardianSleepGray`、……），每一个都由同一个 `adaptiveColor(light:dark:)` 工厂产出，所以浅色/深色是一起定义的。危险红在这里被 token 化成 `dangerRed`/`errorText`（第 81/86 行）。
- **`LavaSurface`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101）—— 卡片/面板/选中态这些表面角色，以及各圆角值：`cardCornerRadius` 20、`compactCornerRadius` 16、`selectionCornerRadius` 12。
- **`LavaSpacing`**（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183）—— 间距刻度：`xs`/`sm`/`md`/`lg`/`xl`，再加上 `screenHorizontal`/`screenTop`/`screenBottom`。

剩下还没补齐的小缺口，就是那几处还没迁到 `LavaStyle.dangerRed` 的直接写死的 `.red`（见 §1）。

---

## 2. LavaTier —— Floor / Window / Workshop **（已实现）** {#2-lavatier-floor-window-workshop-implemented}

`LavaTier` 是一套轻量的深度词汇，把「核心从容，深度靠探索」直接写进了 token 层。它是一套词汇加上几个 token 默认值 —— 不是一整套重新换肤 —— 以一个枚举的形式发布在 lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227，接到了一些有代表性的界面上，而不是把每个视图都改造一遍。

| 层级 | 深度 | 含义 |
|---|---|---|
| **Floor** | 从容 | 给每个人的、直接就能用的防护 —— 默认那一层界面。 |
| **Window** | 庆祝 | 你愿意才会看到的觉察感和小惊喜：连胜、解锁、成功时刻。绝不催你。 |
| **Workshop** | 技术 | DNS、极客统计、诊断。在你主动去找之前都看不到。 |

`LavaTier` 是一个 `calm`/`celebratory`/`technical` 枚举，带着几个 token 默认值：

- 一个 **强调色**（`accent`），
- `allowsDelightMotion` —— 只有 celebratory / Window 时才为 true，
- `usesMonospacedMetadata` —— 只有 technical / Workshop 时才为 true，

通过一个 `EnvironmentKey`，再加上一个 `.lavaTier(_:)` 修饰符和一个 `.lavaTierMetadata()` 修饰符暴露出来（lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263）。它被接到了一些有代表性的界面上 —— 比如 lavasec-ios: LavaSecApp/SettingsView.swift 里的 `.lavaTier(.technical)` 和 `.lavaTier(.celebratory)` —— 而不是每个视图都接。这种有意为之的圈定范围，让三个产品深度在代码里一眼就看得懂，将来移植到 Android 端时也不用重新推导一遍当初的意图。

> **注意事项（强调色 token 化属于「计划中」，第 3 阶段）：** `LavaColorRole` 还没建出来，所以 `LavaTier.accent` 目前还是解析成直接写死的 `LavaStyle` 颜色（LavaTokens.swift:~230）。把强调色的 token 化当成一个还没合上的环，而不是一块已经完工的界面。

---

## 3. Soft Shield Guardian 吉祥物 **（已实现）** {#3-the-soft-shield-guardian-mascot-implemented}

**Soft Shield Guardian** 是 Lava 的吉祥物 —— 一面圆乎乎的盾牌，配一张简单、会变形的脸 —— 它在「防护」标签页、实时活动（Live Activity）、灵动岛（Dynamic Island）以及新手引导里，用视觉表达出当前的防护状态。它是从容语气最显眼的载体。

这套状态图是跨平台、与具体平台无关的，住在 `LavaSecCore` 里（lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift）；SwiftUI 那边的渲染器是 lavasec-ios: Shared/SoftShieldGuardian.swift。

### 3.1 7 种表情状态 {#31-the-7-expression-states}

吉祥物**正好有 7 种**表情状态，由一张「允许哪些转换」的状态图来管（`GuardianMascotState.allowedNextStates`，由 lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift 锁定）：

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

有几条图里的约束值得记一下：`sleeping` 唯一的出口是 `waking`，而 `grateful` 只会回到 `awake`。`awake ↔ grateful` 这组转换有专门定制的插值帧 —— 这是整个系统里唯一的一点 **惊喜动效**（Window 层级）。

> **`retrying` vs `concerned` —— 最重要的语气区分。** 两者都在传达「不是完全健康」，但读起来很不一样，绝不能混为一谈：
> - **`retrying`** 是那张 *不担心、自己会好* 的脸：眼皮放松（约 0.80）、眼睛平视、嘴是平的，**没有担忧的歪头**。动起来的是 **状态徽章，不是脸** —— 短暂的自我恢复绝不该惊动谁。（lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249）
> - **`concerned`** 是那种 *温和、想求助* 的担忧：内侧眉毛微微上挑（`concernAmount` 1、`mouthCurve` -0.22），读起来像「我有点需要搭把手」，**绝不是严厉的瞪眼**。真出了问题应该是邀请你来帮忙，而不是责备你。（lavasec-ios: Shared/SoftShieldGuardian.swift:297）

### 3.2 连通性 → 表情的映射（6 → 4） {#32-connectivity-expression-mapping-6-4}

防护是否健康在 `LavaSecCore` 里被评成 **6 种连通性严重程度** + 2 个动作（lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift）：

- **严重程度：** `healthy`、`recovering`、`usingDeviceDNSFallback`、`dnsSlow`、`networkUnavailable`、`needsReconnect`
- **动作：** `turnOff`、`reconnect`

「防护」标签页把这 6 种严重程度收成 **4 张脸**（lavasec-ios: LavaSecApp/GuardView.swift:122 里的 `guardianState`）。这张脸是有意做得比状态徽章 *更粗、更从容* 的信号 —— 细节交给徽章去带，脸保持简单：

| 条件 | 吉祥物状态 |
|---|---|
| 临时暂停 | `paused` |
| 已连接 + `healthy` / `usingDeviceDNSFallback` | `awake` |
| 已连接 + `recovering` / `networkUnavailable` | `retrying` |
| 已连接 + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| 其他情况 | `sleeping` |

> **色调对齐。** 防护色调的颗粒度会和这套表情划分保持一致，这样色调和脸永远不会自相矛盾。表情映射和语义化的 `ProtectionTintRole` 角色表现在都已经上线（lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7，由 `AppViewModel.protectionTintRole` 使用）。只有那块把角色映射到完全 token 化颜色的 `LavaColorRole` 颜色角色 token 化还停在 **计划中**（设计系统方案的第 3 阶段）。

### 3.3 皮肤（外观）**（已实现）** {#33-skins-looks-implemented}

吉祥物自带 **7 种可选的盾牌「外观」**，以 `GuardianShieldStyle` 持久化（lavasec-ios: Shared/LavaActivityAttributes.swift:5）。每种都有自己的配色，并配一个对应的灵动岛字形颜色：

`original`、`fireOpal`（原始值 `emberObsidian`）、`purpleObsidian`、`obsidian`、`cherryQuartz`（原始值 `strawberryObsidian`）、`emerald`、`kiwiCreme`。

那两个老的原始值是故意保留的 —— 别去「修」它们；改了会让用户已经存下来的选择失效。

### 3.4 隐私遮蔽 **（已实现）** {#34-privacy-redaction-implemented}

Guardian 会尊重隐私遮蔽：当某个界面被做隐私遮蔽时，表情可以被遮住，但 **盾牌本身仍然可见**（`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`，lavasec-ios: Shared/SoftShieldGuardian.swift:11）。让人安心的是「防护还在」这件事；藏起来的是具体那点情绪状态。

### 3.5 不在这个代码树里的东西 **（计划中）** {#35-not-in-this-tree-planned}

「防护」彩蛋小游戏（轻点 = 感谢动画；长按 10 秒 = 一个抓坏域名的小游戏）属于 **P3 / 待办**。它会加进几个额外的吉祥物表情（`confused` / `dazed` / `inZone` / `powerSurge`），这些在某个功能分支上见过 —— 它们 **不在** App 的编译目标里。按照权威事实，吉祥物正好有 **7** 种状态；别把这些游戏表情当成已上线的来写进文档。

---

## 4. 文案与命名 {#4-copy-naming}

### 4.1 声音与语气 {#41-voice-tone}

朴实、从容、实在。别用吓人的安全话术。对能力范围要诚实：Lava 做的是 **本地 DNS/拦截列表过滤**，并不保证每一个恶意域名或网址都会被拦下来；而且 **绝不会** 把防护描述成新手引导一走完就自动开启 —— **「防护」标签页才是判断当前防护是否生效的权威**。

### 4.2 DNS 传输标签 {#42-dns-transport-labels}

传输方式的标注遵循一套严格的紧凑约定（lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 和 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270，由 `DNSResolverPresetTests.swift` 锁定）：

| 传输方式 | 标签 | 说明 |
|---|---|---|
| DNS-over-HTTPS | `DoH` | 基于 URLSession。 |
| DNS-over-HTTP/3 | **`DoH3`（不带斜杠）** | 例如「Quad9 (DoH3)」。**只有真的观察到 h3 协商时**才标注 —— 优先用，但绝不承诺；否则回退到 `DoH`。 |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| 普通 DNS | `IP` | |
| 设备解析器 | *（不标注）* | |

这里最常被破坏的一条规则就是 **不带斜杠的 `DoH3`** —— 要写成 `DoH3`，绝不写 `DoH/3` 或 `DoH3 (h3)`，也绝不凭猜测就贴上去。这些传输标签是从 `DoHTransport`/`DNSResolverPreset` 发出来的；在每种语言里都保持原样，但注意它们 *不是* 词汇表里的「不翻译」条目（见 §4.3）。

### 4.3 不翻译的术语 {#43-do-not-translate-terms}

品牌和协议术语在 **所有** 语言里都钉死保持原样。本地化词汇表的「不翻译」清单是权威，它钉死了：**Lava Security、Lava Security LLC、lavasecurity.app、support@lavasecurity.app、legal@lavasecurity.app、DNS、VPN、DoH、TCP、Apple、Google、Cloudflare、Quad9、The Block List Project、Phishing.Database、HaGeZi、OISD。**

DNS 这些传输方式里，只有 **DoH** 是词汇表里的「不翻译」条目；`DoH3`、`DoT`、`DoQ` 是传输标签（见 §4.2），不是词汇表术语。它们照样原样书写，但别拿词汇表当它们的出处来引用。

### 4.4 安全表述 {#44-safety-framing}

付费永远绕不过那道经过哈希校验、不可被允许的 **安全护栏**。优先级要说得前后一致：**安全护栏 > 本地允许列表（允许例外）> 拦截列表 > 默认放行。**

---

## 5. 新手引导体验 **（已实现）** {#5-onboarding-ux-implemented}

首次启动的新手引导是一个多页流程 —— **6 页**（`OnboardingPage`：`lava → guardIntro → features → vpn → notifications → done`）—— 实现在 lavasec-ios: LavaSecApp/OnboardingFlowView.swift。它复用了 `SoftShieldGuardian` 来做守护者登场的那一刻。

这 6 页是：

1. **网上有岩浆**（`lava`）—— 把危险包装成一个比喻；主操作是「认识岩酱」。
2. **岩酱在这里替你守着**（`guardIntro`）—— 守护者登场的那一刻。
3. **功能交接**（`features`）—— Lava 都能做些什么；「设置防护」。
4. **安装 Lava 的本地 VPN**（`vpn`）—— 解释为什么明明是只走 DNS 的数据包隧道，iOS 却说是「VPN」。
5. **开启通知**（`notifications`）—— 这个授权提示放在合适的那一步弹出，而不是一上来就弹。
6. **设置完成**（`done`）—— 「打开防护」，并可选地做些额外设置。

这套流程里固化下来的几个设计决定：

- **「使用默认」是主操作，「自定义」是次操作。** 给不懂技术的用户一条没有摩擦的默认路径；控制项是靠探索来的，不是硬塞的。
- **把危险包装成比喻，而不是恐吓**（「网上有岩浆」），和从容的语气一致。
- **流程会解释为什么 iOS 说是「VPN」** —— 要在全系统范围内过滤 DNS，数据包隧道是唯一的办法；这并不是在路由流量。
- **绝不宣称走完流程就自动开启防护** —— 「防护」始终是权威。
- 只用尖角箭头做返回，落在一套共享的步骤页布局上。

这套流程装上的首次启动默认值是：**Device DNS** 解析器（`DNSResolverPreset.device`）、**Device DNS 回退开启**、日志开启（计数 + 历史 + 活动），以及「不使用账户继续」。

> **默认拦截列表的分歧（以代码为准）。** 新手引导方案的文案把 HaGeZi Multi Light 列为默认拦截列表，但上线代码里的默认其实是 **Block List Project Phishing + Scam**（`AppConfiguration.lavaRecommendedDefaults`，定义在 lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift）。真正卡住档位的是 **过滤规则预算（免费 500K / Plus 200 万）**，*不是* 列表数量。已在内部跟进。档位模型和推荐默认配置，请看 [功能目录](../product/features.md)。

---

## 6. 国际化 **（进行中）** {#6-internationalization-in-progress}

Lava 本地化到 **6 种语言**：**en**（源语言）+ **ja、zh-Hant、zh-Hans、de、fr**，走 Xcode 字符串目录（string catalogs）。

- **本地化的接缝是 `.lavaLocalized`**（`String.lavaLocalized` / `.lavaLocalizedFormat`，底层是 `LavaStrings.localized` → `NSLocalizedString`，带英文兜底；lavasec-ios: LavaSecApp/LavaStrings.swift）。**所有组件文案** 都得走它 —— 视图里不许出现裸的字符串字面量。
- **zh-Hant** 在第一遍里用的是适合台湾的措辞。
- 6 种语言的 App Store 元数据都已具备。
- 翻译的优先顺序：ja、zh-Hant、zh-Hans、de、fr。

底子已经铺好，但发布前完整的人工翻译审校还没做，所以整体状态是 **进行中**。

> **表现层边界的清理（计划中，第 4 阶段）。** `LavaSecCore`/`Shared` 该携带的是 *语义*（严重程度/动作枚举、图标角色），而不是英文字符串。严重程度色调的呈现已经被提到语义化的 `ProtectionTintRole` 里了。剩下的尾巴是解析器的 `displayName` 还是硬编码的英文字符串（「Google」「Cloudflare」「Quad9」「Device DNS」），在 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift。第 4 阶段会把这些提到一张按操作系统区分、放在 App 端的呈现映射表里 —— 对 i18n 和 Android 移植都对路。

i18n 的具体机制（本地化词汇表、本地化文件的结构，以及翻译审校清单）住在内部的 i18n 文档里，不在这套公开文档里。

---

## 7. 参考素材 {#7-reference-artifacts}

HTML 设计参考（不随包发布、仅供内部）：新手引导流程的故事板、一份 kiwi-creme 守护者外观的研究稿，以及面板内主按钮的几种视觉方案。

设计系统的底子已经落地：`LavaDesignSystem/` 分组、`LavaSpacing`/圆角/`dangerRed` 这些 token、`LavaTier` 深度语义，还有 `LavaIcon` 角色层全都已上线（lavasec-ios: LavaSecApp/LavaDesignSystem/）。在可移植性/底层方案里仍停在 **计划中** 的，是 `LavaColorRole` 强调色 token 化（第 3 阶段）、给核心端英文字符串用的按操作系统区分的呈现映射表（第 4 阶段）、一份中立的跨平台 token JSON，以及更广的 Android 可移植性接缝。
