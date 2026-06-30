---
hide_feedback: true
---

# Lava Security 文档

Lava Security 是一款**隐私优先的 iOS App**，它通过设备上的 NetworkExtension 数据包隧道在本机完成 DNS 过滤——拦截已知的风险域名和不需要的域名，同时不会将你的上网流量绕经 Lava 的服务器。

!!! quote "隐私承诺"
    DNS 过滤完全在你的设备上进行；Lava 从不接收你日常的 DNS 查询、浏览历史或任何按域名记录的遥测数据，而且任何可选的账户备份都是端到端加密的，因此 Lava 始终只能存储密文。

本网站是关于 Lava 工作原理的公开手册——涵盖其架构、行为以及背后的设计决策。它与开源的 [iOS 客户端](https://github.com/lavasecurity/lavasec-ios)保持同步。

## 从这里开始 {#start-here}

<div class="grid cards" markdown>

-   :material-rocket-launch: **产品**

    Lava 能做什么，又是为谁而做。

    [概览](product/overview.md) · [功能目录](product/features.md) ·
    [平台一致性](product/platform-parity.md)

-   :material-sitemap: **架构**

    整个系统是怎么拼在一起的。

    [系统概览](architecture/system-overview.md) ·
    [iOS 客户端](architecture/ios-client.md) ·
    [DNS 过滤与拦截列表](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **隐私内部机制**

    真正撑起隐私承诺的那些部分。

    [后端与数据](architecture/backend-and-data.md) ·
    [账户与零知识备份](architecture/accounts-and-backup.md)

-   :material-scale-balance: **决策与合规**

    为什么要这样设计。

    [关键决策（ADR）](decisions/key-decisions.md) ·
    [第三方声明](legal/third-party-notices.md)

</div>

## 该怎么读这份文档 {#how-to-read-this}

这里的每一条说法都能在源代码里找到依据。全文都会标注状态：

| 状态 | 含义 |
|---|---|
| **已实现** | 已经在上线的代码里 |
| **进行中** | 正在做 |
| **计划中** | 一个方向，尚未实现 |
| **已放弃** | 权衡后决定不做——保留以备查阅 |

当文档与代码不一致时，以代码为准。这份文档只是一张快照，会随着产品演进、从源代码重新生成。

跨平台行为记录在[平台一致性](product/platform-parity.md)中：其中列出了稳定的功能 id、各平台状态，以及用于让 iOS 与 Android 保持一致的测试或测试夹具。
