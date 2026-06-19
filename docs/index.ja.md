---
hide_feedback: true
---

# Lava Security ドキュメント

Lava Security は、端末上の NetworkExtension パケットトンネルを使って DNS を
このスマートフォン上でローカルにフィルタリングする**プライバシー優先の iOS アプリ**です。
あなたの通信を Lava のサーバー経由にすることなく、危険だとわかっているドメインや
不要なドメインをブロックします。

!!! quote "プライバシーの約束"
    DNS フィルタリングは端末上でローカルに行われます。Lava があなたの日常的な
    DNS クエリやブラウジング履歴、ドメインごとの利用状況を受け取ることはありません。
    そして任意のアカウントバックアップはエンドツーエンドで暗号化されているので、
    Lava が保管できるのは暗号文だけです。

このサイトは、Lava がどう動くのか（その仕組み、振る舞い、そしてその背後にある
判断）を説明する公開マニュアルです。内容はオープンソースの
[iOS クライアント](https://github.com/lavasecurity/lavasec-ios)に追従しています。

## ここから始める {#start-here}

<div class="grid cards" markdown>

-   :material-rocket-launch: **製品**

    Lava は何をするもので、誰のためのものか。

    [概要](product/overview.md) · [機能カタログ](product/features.md) ·
    [プラットフォーム間の対応状況](product/platform-parity.md)

-   :material-sitemap: **アーキテクチャ**

    システム全体がどう組み合わさっているか。

    [システム概要](architecture/system-overview.md) ·
    [iOS クライアント](architecture/ios-client.md) ·
    [DNS フィルタリングとブロックリスト](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **プライバシーの内部構造**

    プライバシーの約束を支えている部分。

    [バックエンドとデータ](architecture/backend-and-data.md) ·
    [アカウントとゼロ知識バックアップ](architecture/accounts-and-backup.md)

-   :material-scale-balance: **判断とコンプライアンス**

    なぜこういう作りになっているのか。

    [主要な判断（ADR）](decisions/key-decisions.md) ·
    [サードパーティ通知](legal/third-party-notices.md)

</div>

## この資料の読み方 {#how-to-read-this}

ここに書かれていることは、すべてソースコードに裏付けられています。状態は全体を通して
次のように示されています。

| 状態 | 意味 |
|---|---|
| **実装済み** | 出荷済みのコードに存在する |
| **進行中** | いま作っている最中 |
| **予定** | 方向性であり、まだ作られていない |
| **取り下げ** | 見送ると決めたもの — 記録として残してある |

ドキュメントとコードが食い違っている場合は、コードが正です。このドキュメントは
ある時点のスナップショットで、製品の進化に合わせてソースから作り直されます。

プラットフォーム間の振る舞いの違いは[プラットフォーム間の対応状況](product/platform-parity.md)で
追跡しています。そこには安定した機能 id、各プラットフォームの状態、そして iOS と
Android の足並みをそろえるためのテストやフィクスチャがまとめられています。
