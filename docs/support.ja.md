---
hide_feedback: true
---

# サポートとヘルプ {#support--help}

困ったとき、不具合を見つけたとき、何かを報告したいときの行き先をまとめました。

## アプリで何かうまく動かない？ {#something-not-working-in-the-app}

**アプリ内の不具合レポート**を使ってください。これが一番早く、必要な診断情報も一緒に送られます。設計上、データは最小限に抑えてあります（あなたが見ているドメインは一切含まれません）。レポートはチームが確認・対応します。

## セキュリティの脆弱性を見つけた？ {#found-a-security-vulnerability}

**公開のイシューは立てないでください。** **security@lavasecurity.app** 宛てに、内容・影響・再現手順を添えてメールしてください。対象範囲と開示の流れについては、iOS クライアントの[セキュリティポリシー](https://github.com/lavasecurity/lavasec-ios/blob/main/SECURITY.md)をご覧ください。_（アドレスは確定予定です。）_

## オープンソースのクライアントについて質問がある？ {#question-about-the-open-source-client}

Lava の iOS クライアントはオープンソースです。技術的な質問、ビルドの問題、機能の提案などは、[**lavasecurity/lavasec-ios**](https://github.com/lavasecurity/lavasec-ios/issues) でイシューを立ててください。

## このドキュメントに間違いがある？ {#something-wrong-in-these-docs}

どのページにも一番下に **「このページは役に立ちましたか？」** という質問があります。*「改善できそう」* を選ぶと、[**lavasecurity/lavasec-doc**](https://github.com/lavasecurity/lavasec-doc/issues) に内容を下書きした状態でイシューが開きます。修正やプルリクエストはいつでも歓迎です。

## Lava の仕組みを知りたい {#understanding-how-lava-works}

「これって普通？」という疑問のほとんどは、ドキュメントそのもので解決できます。

- [製品概要](product/overview.md)と[機能カタログ](product/features.md) — Lava ができること。
- [DNS フィルタリングとブロックリスト](architecture/dns-filtering-and-blocklists.md) — フィルタリングと暗号化された DNS の動き。
- [アカウントとゼロ知識バックアップ](architecture/accounts-and-backup.md) — 何が暗号化され、サーバーから何が見えるのか。
- [主要な決定](decisions/key-decisions.md) — なぜこの作りになっているのか。
