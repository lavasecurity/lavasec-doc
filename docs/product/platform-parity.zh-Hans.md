# 平台一致性 {#platform-parity}

Lava 的平台一致性体系用于记录哪些产品承诺在 iOS、Android 以及未来的客户端之间共通。它是功能行为的公开约定：哪些必须在所有平台上保持同一含义、哪些有意做成各系统原生、哪些尚未承诺。

一致性文档不替代实现计划或测试。

- `lavasec-doc` 负责产品和行为的约定。
- 内部计划负责交付进度、排期、私有风险，以及董事会同步。
- 各平台仓库负责存放代码、夹具，以及证明行为的测试。

当文档与已上线的代码不一致时，以代码为准，直至文档更新跟进。当某个计划与本页不一致时，将本页视为产品约定，将计划视为待办队列。

## 状态术语 {#status-vocabulary}

| 状态 | 含义 |
|---|---|
| **Shipped** | 已在该平台的生产代码中实现。 |
| **Partial** | 部分行为已经有了，但公开约定还没完全满足。 |
| **Planned** | 已确认是平台约定的一部分，但还没实现。 |
| **Deferred** | 是个有效的功能，但下一个平台里程碑不要求它。 |
| **Platform-native** | 给用户的承诺一样，只是各系统的实现方式不同。 |
| **Not applicable** | 这个平台上本就不该有对应功能。 |
| **Dropped** | 之前考虑过或做过，后来特意拿掉了。 |

## 功能记录格式 {#feature-record-format}

每个纳入一致性追踪的功能都需要一个稳定的功能 id。使用 `area.capability` 这类命名，使其不受 UI 文案改动影响，例如 `filtering.guardrail-precedence` 或 `dns.encrypted-transports`。

一条完整的功能记录要回答这些问题：

| 字段 | 用途 |
|---|---|
| `feature_id` | 在计划、PR、测试和文档里都用得上的稳定 id。 |
| 产品承诺 | 用户能依赖的东西，用不分平台的话来说。 |
| 一致性要求 | Android 须与 iOS 完全一致、按意图一致，还是有意保持不同。 |
| 平台状态 | iOS、Android 以及未来客户端的进展。 |
| 保障机制 | 确保行为如实的测试、夹具、源文件或评审检查。 |
| 平台说明 | 各系统特有的差异，得写清楚，别等以后再去重新发现。 |

## 更新流程 {#update-workflow}

1. 当某个改动影响到产品承诺、隐私声明、套餐边界或跨平台行为时，新增或更新功能 id。
2. 需要做事时，从实现计划里链接到同一个功能 id。
3. 为必须保持一致的行为新增或更新平台测试或基准夹具。
4. 当某个平台把这个行为做上线后，在这里更新状态，并刷新相关的功能页或架构页。
5. 把只涉及实现细节、私有、定价、法律风险和运营的内部内容留在内部；这里只总结公开约定。

## 当前一致性账本 {#current-parity-ledger}

| 功能 id | 产品承诺 | iOS | Android | 一致性要求 | 保障机制 / 来源 |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava 在设备本地过滤 DNS，不会把浏览流量通过 Lava 的服务器中转。 | Shipped | Planned | 按意图一致；各系统隧道 API 不一样。 | iOS 数据包隧道架构；Android `VpnService` 计划。 |
| `protection.vpn-disclosure` | 在请求 VPN 权限/配置之前，App 会解释为什么系统把本地 DNS 过滤叫作 VPN。 | Shipped | Planned | 文案和权限流程各系统原生。 | 引导文档；Android Play 披露计划。 |
| `filtering.guardrail-precedence` | 常驻安全护栏优先于用户的允许列表；付费身份永远无法绕过护栏。 | Shipped | Planned | 行为完全一致。 | `CompactFilterSnapshotTests`；移植后的 Android `FilterSnapshotTest`。 |
| `filtering.source-url-only-catalog` | Lava 发布的是目录的元数据和上游来源 URL，而不是第三方拦截列表的字节内容。 | Shipped | Planned | 隐私/知识产权模型完全一致。 | 目录架构；GPL/仅来源 URL 的法律文档。 |
| `filtering.on-device-parsing` | 选中的列表是在设备上下载并解析的；日常的域名历史不会上传给 Lava。 | Shipped | Planned | 隐私完全一致，允许使用原生存储。 | `BlocklistParserTests`；移植后的 Android 解析器一致性测试。 |
| `filtering.rule-budget` | 过滤上限取决于编译后的规则条数和设备安全，而非任意设定的列表数量。 | Shipped | Planned | 面向用户的模型一致；各平台的内存上限可能不同。 | iOS 过滤预算测试；摸清设备上限后的 Android 预算测试。 |
| `dns.built-in-resolvers` | 用户可选用内置解析器预设，而不会将允许的查询发送给 Lava。 | Shipped | Planned | 解析器策略一致；预设集合可能分阶段推出。 | 解析器预设测试；移植后的 Android 解析器 DTO 测试。 |
| `dns.encrypted-transports` | 对于允许的查询，可以使用加密的上游 DNS。 | Shipped | Planned | 允许分阶段达成一致；Android v1 可能先上 DoH，再上 DoT/DoQ。 | iOS 传输测试；Android 解析器测试和设备 QA。 |
| `reports.local-only-diagnostics` | 报告和诊断信息会留在本地，除非用户主动发送支持包。 | Shipped | Planned | 隐私完全一致；UI 可以不同。 | 错误报告打包测试；构建后的 Android 调试报告预览测试。 |
| `account.optional-sign-in` | 不用账户也能防护；登录是可选的。 | Shipped | Deferred | 在 Android 暴露账户功能之前，产品承诺要完全一致。 | 账户认证文档；Android 引导/设置评审。 |
| `backup.zero-knowledge-settings` | 可选的设置备份只存密文；Lava 读不到备份的明文内容。 | Shipped | Deferred | 在 Android 提供备份之前，隐私要完全一致。 | 零知识备份测试；构建后的 Android 加密一致性测试。 |
| `plus.customization-boundary` | 免费防护依然实用；Plus 解锁进阶自定义，永远不会改变护栏的安全性。 | Shipped | Planned | 产品边界一致；商店实现各平台原生。 | 订阅策略测试；构建后的 Play Billing 权益测试。 |
| `design.calm-earned-depth` | 默认体验是平静的，更深入的技术界面或庆祝界面只在合适或用户主动要求时才出现。 | Partial | Planned | 通过共享的 token/角色，按设计意图一致。 | 设计系统文档和可移植性基础计划。 |
| `platform.ambient-presence` | 当系统支持原生的环境界面时，防护状态可以出现在 App 之外。 | Platform-native | Planned | 意图一致，但界面不要求一致。 | iOS Live Activity 文档；Android 通知/快捷设置方案待定。 |

## Android 就绪用途 {#android-readiness-use}

在 Android 开始实现之前，本页应当和 Android 计划以及设计系统可移植性计划一起评审。Android 就绪的最低约定是：

- 每个涉及隐私的功能都有一个功能 id；
- 完全一致的行为，都有一个明确的 iOS 测试或夹具来源；
- 各系统原生的行为，都有一个明确的 Android 立场；
- 已延后的功能需明确列出，以免 Android MVP 让人误以为它们将要上线。

该评审应放在实现计划或评审记录中，而本页只保留公开、长期有效的约定。
