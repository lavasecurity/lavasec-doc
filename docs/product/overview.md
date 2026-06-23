---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Product Overview

Welcome to Lava Security. This page is the front door to the documentation set: a short, plain introduction to what Lava is, what it promises, and where to read more.

## What Lava is

Lava Security is a privacy-first iOS app that filters DNS locally on the device through an on-device [NetworkExtension packet tunnel](../architecture/ios-client.md), blocking known risky and unwanted domains without routing your browsing through Lava's servers. The packet tunnel (`LavaSecTunnel`, a `NEPacketTunnelProvider`) parses each DNS query on the phone, checks the requested domain against a compiled, memory-mapped filter snapshot, and forwards only allowed queries upstream. There is no Lava-operated proxy your traffic passes through: filtering is a local decision, made on your device.

iOS labels this a "VPN" because a packet tunnel is the only way an app can filter DNS system-wide — but Lava is **DNS/blocklist filtering**, not traffic routing. Be honest about scope: Lava is local DNS-domain filtering, **not** a guarantee that every malicious domain or URL is blocked. It sees domains, not page paths, so it cannot block one bad page on an otherwise-trusted host. Protection is also not auto-on the moment onboarding finishes — the in-app **Guard** tab is the authoritative source of whether protection is currently active.

## The privacy promise

> All DNS filtering happens on the device; Lava never routes your browsing through its servers and never receives the stream of domains you visit — the backend holds only catalog metadata, an opaque per-user encrypted backup, and anonymized diagnostics you choose to send.

This sentence is canonical. Everything else in these docs is meant to be consistent with it. Paying for the optional tier does **not** move filtering to the server or give Lava a stream of visited domains. When a feature touches a server, the docs spell out what is **not** sent — your routine DNS queries, your browsing history, and any plaintext all stay on the device. See [the backend and data model](../architecture/backend-and-data.md) for the full picture.

## Who it is for

Lava is built for anyone who wants safer browsing without managing it. The audience deliberately includes non-technical users — parents setting up protection for a family, older adults, and anyone who does not want to think about DNS at all. The default experience just works: turn protection on and a conservative blocklist starts filtering, with no account required. At the same time, power users can reach deeper controls (custom blocklists, alternate resolvers) when they want them.

The voice throughout is plain, calm, and practical — danger is framed as a metaphor, not fear.

## Core principles

- **Privacy is positioning, not a paid feature.** Filtering is a local decision. Lava's backend is intentionally minimal and never receives your routine browsing domains or DNS event streams. Optional account backup is [zero-knowledge](../architecture/accounts-and-backup.md): the servers store only ciphertext and non-secret envelope metadata.
- **Free core protection forever.** The protection switch, default blocklist updates, and basic local counts are never gated and never require an account.
- **On-device.** The protection engine lives entirely on the phone — DNS parsing, domain evaluation, and upstream forwarding all happen inside the packet-tunnel extension, bounded by the iOS ~50 MiB per-extension memory ceiling. Blocklists follow a [source-url-only](../architecture/dns-filtering-and-blocklists.md) model: the app fetches each upstream list directly and parses it locally; Lava never hosts or serves third-party blocklist bytes.
- **Payment unlocks customization only — never baseline safety.** The threat guardrail — a non-allowable tier above every blocklist that no one, paid or not, can allowlist — is enforced by decision precedence: **threat guardrail > local allowlist (allowed exceptions) > blocklist > default-allow.** (The precedence slot is wired and integrity-checked by accepted SHA-256 hashes; it currently ships with no entries.) The tunnel ignores `isPaid`.
- **Calm core, earned depth.** The default surfaces are quiet and reassuring, fronted by the Soft Shield Guardian mascot and copy that avoids fear-driven language. Richer, more technical detail is available when you go looking for it but is never forced on you. This "calm core, earned depth" philosophy is formalized in the **LavaTier** depth model (Floor / Window / Workshop) — see [the design system](../design-system/overview.md).

## High-level capabilities

- **Local DNS filtering** — the packet-tunnel engine that parses DNS, evaluates each domain against the compiled snapshot, and forwards allowed queries upstream with device-DNS fallback. See [the iOS client](../architecture/ios-client.md) and [DNS filtering and blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Curated blocklists, source-url-only** — Lava publishes only upstream list URLs (plus advisory hashes for cache identity and audit); the device fetches each list over TLS and parses it locally under size/rule caps, and Lava never mirrors or serves third-party blocklist bytes. Community lists are not hash-pinned — TLS + the curated URL is the integrity boundary — while Lava's threat-guardrail tier stays hash-enforced. The shipped default enables **Block List Basic** (`AppConfiguration.lavaRecommendedDefaults`, defined in `OnboardingDefaults.swift`); copyleft sources such as HaGeZi, OISD, AdGuard, and 1Hosts are opt-in. See [DNS filtering and blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Encrypted DNS transports** — DoH (with observational DoH3 annotation), DoT (pooled connections, reused and refreshed), and DoQ (fresh connection per query). All three are implemented; Device DNS (the network's own resolver) is the shipped default, and encrypted presets are opt-in (`AppConfiguration.lavaRecommendedDefaults`, defined in `Sources/LavaSecCore/OnboardingDefaults.swift`). The built-in resolver presets (Google / Cloudflare / Quad9 DoH and DoT variants) are free; only a fully custom resolver is a paid unlock. See [DNS filtering and blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Allowed exceptions (allowlist)** — manually add domains to permit despite a blocklist; the threat guardrail still wins. See [the product features overview](features.md).
- **The Soft Shield Guardian** — a mascot on the Guard tab, Live Activity, and Dynamic Island that expresses protection state across 7 expression states. See [the design system](../design-system/overview.md).
- **Tiered customization (Lava Security Plus)** — one optional paid tier that unlocks customization (a larger filter-rules budget — Free 500K / Plus 2M compiled rules under a shared device safety guardrail — more allowed/blocked domains, custom blocklists, and custom DNS resolvers). Plus never bypasses the always-on guardrails — the tunnel ignores `isPaid`.
- **Optional accounts and backup** — Apple or Google sign-in with an end-to-end-encrypted ([zero-knowledge](../architecture/accounts-and-backup.md)) settings backup and recovery phrase; account deletion is self-serve. The optional passkey recovery slot is **also zero-knowledge** — its key is derived on-device from the authenticator's WebAuthn PRF, with no server-held secret; on-device production readiness still depends on Associated Domains / AASA hosting **(Planned)**. Accounts are optional; protection works fully signed-out.
- **Local-only activity and reports** — on-device block/allow counts, tunnel health, and an opt-in bug-report bundle, built from data the running tunnel keeps on the device — empty when idle and live while protecting. No routine domain history leaves the device. See [the product features overview](features.md).

## Platforms

- **iOS — shipped.** Lava is an iOS app today: three bundles share one App Group (`group.com.lavasec`) — the app (`com.lavasec.app`), the packet-tunnel extension (`.tunnel`), and the widget (`.widget`) — plus shared sources, over a common `LavaSecCore` package.
- **Android — Planned.** A native Kotlin / Jetpack Compose port over Android's `VpnService` is planned, carrying the same privacy promise and a parity-tested core filtering behavior. No Android app code ships yet.

See [Platform Parity](platform-parity.md) for the stable feature ids and the iOS/Android contract.
