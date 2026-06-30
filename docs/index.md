---
hide_feedback: true
---

# Lava Security Documentation

Lava Security is a **privacy-first iOS app** that filters DNS locally on the
device through an on-device NetworkExtension packet tunnel — blocking known
risky and unwanted domains without routing your browsing through Lava's servers.

!!! quote "The privacy promise"
    DNS filtering happens locally on your device; Lava never receives your
    routine DNS queries, browsing history, or per-domain telemetry, and any
    optional account backup is end-to-end encrypted so Lava can only ever store
    ciphertext.

This site is the public manual for how Lava works: its architecture, behavior, and the decisions behind it. It tracks the open-source
[iOS client](https://github.com/lavasecurity/lavasec-ios).

## Start here

<div class="grid cards" markdown>

-   :material-rocket-launch: **Product**

    What Lava does and who it's for.

    [Overview](product/overview.md) · [Feature Catalog](product/features.md) ·
    [Platform Parity](product/platform-parity.md)

-   :material-sitemap: **Architecture**

    How the whole system fits together.

    [System Overview](architecture/system-overview.md) ·
    [iOS Client](architecture/ios-client.md) ·
    [DNS Filtering & Blocklists](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **Privacy internals**

    The parts that carry the privacy promise.

    [Backend & Data](architecture/backend-and-data.md) ·
    [Accounts & Zero-Knowledge Backup](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Decisions & compliance**

    Why it's built this way.

    [Key Decisions (ADRs)](decisions/key-decisions.md) ·
    [Third-Party Notices](legal/third-party-notices.md)

</div>

## How to read this

Every claim here is grounded in the source. Status is marked throughout:

| Status | Meaning |
|---|---|
| **Implemented** | Present in shipped code |
| **In progress** | Being built now |
| **Planned** | A direction, not yet built |
| **Dropped** | Decided against — kept for the record |

When the docs and the code disagree, the code wins. These docs are a snapshot,
regenerated from the source as the product evolves.

Cross-platform behavior is tracked in [Platform Parity](product/platform-parity.md):
it names stable feature ids, platform status, and the tests or fixtures that
should keep iOS and Android aligned.
