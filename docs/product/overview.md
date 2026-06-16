# Product Overview

Welcome to Lava Security. This page is the front door to the documentation set: a short, plain introduction to what Lava is, what it promises, and where to read more.

## What Lava is

Lava Security is a privacy-first iOS app that filters DNS locally on the device through an on-device [NetworkExtension packet tunnel](../architecture/ios-client.md), blocking known risky and unwanted domains without routing your browsing through Lava's servers. The packet tunnel (`PacketTunnelProvider` / `LavaSecTunnel`) parses each DNS query on the phone, checks the requested domain against a compiled, memory-mapped filter snapshot, and forwards only allowed queries upstream. There is no Lava-operated proxy your traffic passes through: filtering is a local decision, made on your device.

## The privacy promise

> DNS filtering happens locally on your device; Lava never receives your routine DNS queries, browsing history, or per-domain telemetry, and any optional account backup is end-to-end encrypted so Lava can only ever store ciphertext.

This sentence is canonical. Everything else in these docs is meant to be consistent with it. When a feature touches a server, the docs spell out what is **not** sent — your routine DNS queries, your browsing history, and any plaintext all stay on the device. See [the backend and data model](../architecture/backend-and-data.md) for the full picture.

## Who it is for

Lava is built for anyone who wants safer browsing without managing it. The audience deliberately includes non-technical users — parents setting up protection for a family, older adults, and anyone who does not want to think about DNS at all. The default experience just works: turn protection on and a conservative blocklist starts filtering, with no account required. At the same time, power users can reach deeper controls (custom blocklists, alternate resolvers) when they want them.

## Core principles

- **Privacy-first.** Filtering is a local decision. Lava's backend is intentionally minimal and never receives your routine browsing domains or DNS event streams. Optional account backup is [zero-knowledge](../architecture/accounts-and-backup.md): the servers store only ciphertext and non-secret envelope metadata.
- **On-device.** The protection engine lives entirely on the phone — DNS parsing, domain evaluation, and upstream forwarding all happen inside the packet-tunnel extension, bounded by the iOS ~50 MiB per-process memory ceiling. Blocklists follow a [source-url-only](../architecture/dns-filtering-and-blocklists.md) model: the app fetches each upstream list directly and parses it locally; Lava never hosts or serves third-party blocklist bytes.
- **Calm UX with earned depth.** The default surfaces are quiet and reassuring, fronted by the Soft Shield Guardian mascot and copy that avoids fear-driven language. Richer, more technical detail is available when you go looking for it but is never forced on you. This "calm core, earned depth" philosophy is now formalized in code as the **LavaTier** depth model (Floor / Window / Workshop) — see [the design system](../design-system/overview.md).

## High-level capabilities

- **Local DNS filtering** — the packet-tunnel engine that parses DNS, evaluates each domain against the compiled snapshot, and forwards allowed queries upstream. See [the iOS client](../architecture/ios-client.md) and [DNS filtering and blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Curated blocklists** — a source-url-only catalog of curated lists with always-on guardrails; the shipped default enables Block List Project Phishing + Scam, and GPL sources (HaGeZi, OISD) are opt-in. See [DNS filtering and blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Encrypted DNS transports** — DoH (with observational DoH3 annotation), DoT (pooled, reused connections), and DoQ (fresh connection per query). All three are implemented; DoH is opt-in and Google plain DNS remains the default resolver. Encrypted transports work for free on the built-in resolver presets (Google / Cloudflare / Quad9 / DNS.SB); only a fully custom resolver is a paid unlock. See [DNS filtering and blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Tiered customization (Lava Security Plus)** — an optional paid tier that unlocks custom blocklists, custom DNS resolvers, higher manual allow/block caps (10 → 500), and a higher filter-rules budget (Free 500K / Plus 2M compiled rules, under a device safety guardrail). Plus never bypasses the always-on guardrails — the tunnel ignores `isPaid`. See tiers and monetization.
- **Optional accounts and backup** — Apple or Google sign-in with an end-to-end-encrypted ([zero-knowledge](../architecture/accounts-and-backup.md)) settings backup and recovery phrase. Server-gated passkey recovery is **(Planned)** — server-side WebAuthn verification is not yet shipped. Accounts are optional; protection works fully signed-out.
- **Local-only activity and reports** — Reports and an Activity log built from data the running tunnel keeps on the device, empty when idle and live while protecting. See [the product features overview](features.md).

## Platforms

- **iOS — shipped.** Lava is an iOS app today: the app, the packet-tunnel extension, and a widget share `LavaSecCore` and the `group.com.lavasec` App Group.
- **Android — Planned.** A native Kotlin / Jetpack Compose port on Android's `VpnService` is planned (backlog), carrying the same privacy promise and parity-tested core filtering behavior. No Android app code ships yet.

See [Platform Parity](platform-parity.md) for the stable feature ids and the
iOS/Android contract.
