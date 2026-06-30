---
hide_feedback: true
---

# Lava Security 文件 {#lava-security-documentation}

Lava Security 是一款**以隱私為優先的 iOS app**，透過裝置端的 NetworkExtension 封包通道在本機篩選 DNS——封鎖已知的高風險與不必要的網域，同時不會將你的瀏覽流量導向 Lava Security 的伺服器。

!!! quote "隱私承諾"
    DNS 篩選會在你的裝置本機完成；Lava Security 永遠不會收到你日常的 DNS 查詢、瀏覽歷史記錄或逐網域的遙測資料，而任何選用的帳號備份都是端對端加密的，因此 Lava Security 只可能儲存密文。

本站是說明 Lava Security 運作方式的公開手冊——涵蓋其架構、行為，以及背後的決策，並追蹤開源的 [iOS 用戶端](https://github.com/lavasecurity/lavasec-ios)。

## 從這裡開始 {#start-here}

<div class="grid cards" markdown>

-   :material-rocket-launch: **產品**

    Lava Security 的功能以及它適合誰。

    [概覽](product/overview.md) · [功能目錄](product/features.md) ·
    [平台一致性](product/platform-parity.md)

-   :material-sitemap: **架構**

    整個系統如何組合在一起。

    [系統概覽](architecture/system-overview.md) ·
    [iOS 用戶端](architecture/ios-client.md) ·
    [DNS 篩選與封鎖清單](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **隱私內部機制**

    承載隱私承諾的各個部分。

    [後端與資料](architecture/backend-and-data.md) ·
    [帳號與零知識備份](architecture/accounts-and-backup.md)

-   :material-scale-balance: **決策與合規**

    為何採用這樣的設計。

    [關鍵決策（ADR）](decisions/key-decisions.md) ·
    [第三方聲明](legal/third-party-notices.md)

</div>

## 如何閱讀本文件 {#how-to-read-this}

這裡的每一項主張都立基於原始碼。狀態會在全文中標示：

| 狀態 | 含義 |
|---|---|
| **已實作** | 已存在於出貨的程式碼中 |
| **進行中** | 正在建構中 |
| **已規劃** | 一個方向，尚未建構 |
| **已捨棄** | 已決定不採用——保留以供記錄 |

當文件與程式碼不一致時，以程式碼為準。本文件是一份快照，會隨著產品演進從原始碼重新產生。

跨平台行為記錄於[平台一致性](product/platform-parity.md)：當中列出穩定的功能 id、平台狀態，以及用來讓 iOS 與 Android 保持一致的測試或固定資料。
