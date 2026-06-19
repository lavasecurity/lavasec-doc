---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios, lavasec-infra]
grounded_at: {lavasec-ios: "1fbab70", lavasec-infra: "5f425af"}
---

# Feature Catalog

> Audience: PM / engineering. This catalog covers the **current, implemented** feature set only. Anything designed-but-not-built lives in the private roadmap, not here.

Lava Security is a privacy-first iOS app that filters DNS **locally on the device** through a NetworkExtension packet tunnel, blocking malicious and unwanted domains for non-technical users (parents, older adults) — with core protection free forever and no account required.

The privacy promise behind every feature below:

> All DNS filtering happens on the device; Lava never routes your browsing through its servers and never receives the stream of domains you visit — the backend holds only catalog metadata, an opaque per-user encrypted backup, and anonymized diagnostics you choose to send.

## How to read this catalog

- **Free** — available to everyone, no account, no purchase.
- **Plus** — unlocked by Lava Security Plus, the single optional paid tier. Plus unlocks **customization only**; it never gates baseline safety and never lets a paying user bypass the threat guardrail.
- Every row is **Implemented** unless flagged inline. Status legend: **Implemented** = shipped and confirmed in code; **Planned** = designed, not built; **Dropped** = rejected or reverted. Planned/Dropped items are documented in the private roadmap, not here.

Source-of-truth tier ceilings live in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, aliased as `.plus`). The Plus entitlement is a local flag (`isPaid`); there is no backend entitlement sync yet.

---

## 1. Protection & VPN

The core product: a local DNS-only packet tunnel and the calm state model around it.

| Feature | Tier | Notes |
|---|---|---|
| **Local DNS-only packet tunnel** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercepts DNS and evaluates each domain on-device. No browsing traffic is routed through Lava. Tunnel addr `10.255.0.2`, DNS server `10.255.0.1`. |
| **Filter decision precedence** | Free | `threat guardrail block > local allowlist (allowed exceptions) > blocklist > default-allow`; invalid domains are blocked. (`FilterSnapshot.decision()`.) |
| **Query precedence (bootstrap-first)** | Free | `resolver-bootstrap > temporary-pause > filter` — the resolver's own hostname is never blocked. (`DNSQueryDispatcher`.) |
| **Fail-closed cold start** | Free | A cold tunnel with no reusable snapshot installs a `FailClosedRuntimeSnapshot` that blocks all traffic rather than leaking unfiltered DNS. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` keeps protection up / auto-restarts it — enabled **only after** a confirmed connection, never at profile install, and neutralized during incomplete onboarding so a fresh install can't bring up an un-turn-off-able tunnel. |
| **Temporary pause (5 / 10 min) + resume** | Free | Pause/resume run through `LavaProtectionCommandService` under a flock file lock with revision dedup. |
| **Authentication-required pause** | Free | Opt-in per-surface gate (`SecurityProtectedSurface.protectionPause`): pause requires local device auth; the command service denies an unauthenticated pause and the Live Activity hides the pause buttons. |
| **Reconnect** | Free | Restarts the tunnel directly (bypasses the command-service pause pipeline). |
| **Soft Shield Guardian state model** | Free | 7 expression states — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 connectivity severities collapse to 4 faces; rendered identically in-app, in onboarding, and in the Live Activity. |
| **Connectivity assessment** | Free | 6 severities (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) drive the guardian face and status copy. |
| **Performance hardening** | Free | Cache-first turn-on, in-flight query coalescing, bounded-parallel fetch, and flap coalescing (warm turn-on measured ~112 ms on iPhone 15 Pro per the modular speed-up work). |

> **Device guardrail (everyone, never a paywall):** a hard `~3.26M-rule` ceiling (32 MB resident target under the iOS `~50 MiB` per-extension memory ceiling) is enforced for all users above any tier (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Over-budget configs are rejected deterministically (`exceedsDeviceMemoryBudget`) instead of letting the tunnel jetsam.

---

## 2. Blocklists & filtering

What gets blocked, how lists are chosen, and the tier boundary.

| Feature | Tier | Notes |
|---|---|---|
| **Source-url-only blocklists** | Free | Lava publishes only the upstream URL + accepted hashes; the device fetches/parses the list **bytes** itself. Lava **never** stores, mirrors, transforms, or serves third-party blocklist bytes. See [GPL source-url-only compliance decision](../legal/gpl-source-url-only-compliance-decision.md). |
| **Curated catalog (10 sources)** | Free to enable | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **Free default blocklists** | Free | Fresh install enables **Block List Project Phishing + Scam** (the two sources flagged `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **On-device parse / normalize / dedup** | Free | `BlocklistParser` supports auto/plain/hosts/adblock/dnsmasq, drops comments/blanks/invalid, dedups exact strings, caps at 1,000,000 rules per list. |
| **Upstream byte validation** | Free | Fetched bytes are SHA-256'd and accepted only if the checksum is in the catalog's `accepted_source_hashes`; on mismatch Lava falls back to last-good cache or fails closed. |
| **Protected-domain filter** | Free | Every parsed source is stripped of protected Lava / Apple / identity-provider domains (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …) so an upstream list can't break the app, tunnel, or sign-in. |
| **Allowed Exceptions (allowlist)** | Free | User-managed allowlist permitting domains despite blocklists. Free cap: 10 allowed / 10 blocked domains (`FeatureLimits.free`). |
| **Filter-rules budget (tier metric)** | Free / Plus | The shipped tier metric is total compiled domain **rules**: **Free 500K / Plus 2M** (`maxFilterRules` in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Replaces the old list-count cap. Over-tier configs surface `exceedsTierFilterRuleLimit`. |
| **Higher domain limits** | Plus | 500 allowed / 500 blocked domains (`FeatureLimits.plus`). |
| **Custom blocklists** | Plus | `allowsCustomBlocklists`. Custom lists are fetched and parsed on the device, cached locally, never proxied to Lava servers. |
| **Warm-startup artifact reuse** | Free | A manifest + identity fingerprint lets the tunnel reuse the on-disk compact snapshot without recompiling; reuse is rejected (with a privacy-safe field-name-only reason) when inputs change. |

> Authoritative budget enforcement runs at compile time on the deduped union (`FilterSnapshotPreparationService`); the device cap is checked first, then the tier limit. The selection-time UI meter uses a per-list sum with a 1.10 soft-ceiling margin.

---

## 3. Encrypted DNS

Resolver transports and routing for unblocked queries.

| Feature | Tier | Notes |
|---|---|---|
| **Five resolver transports** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | URLSession-based DoH that prefers HTTP/3. The UI annotates **`DoH3` (no slash)**, e.g. "Quad9 (DoH3)", **only when an h3 negotiation is actually observed** — preferred, never promised (`DoHTransport`). |
| **DoT** | Free | Pooled `NWConnection`s (up to 4/endpoint) with idle-staleness refresh and one fresh-connection retry. |
| **DoQ** | Free | Opens a **fresh QUIC connection per query** (no reuse); the 4-lane pool gives concurrency, not handshake reuse. |
| **Preset resolvers** | Free | Device DNS (default), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — in IP / DoH / DoT variants where offered (`DNSResolverPreset.allPresets`). |
| **Resolver routing & failover** | Free | `ResolverOrchestrator` routes by transport, degrades to plain DNS when an encrypted plan has no endpoints, does per-endpoint failover with a backoff gate, then device-DNS fallback. |
| **Device-DNS fallback** | Free | Falls back to the current network's resolver when the selected resolver is unavailable; **on by default**. Surfaced as the `usingDeviceDNSFallback` severity. |
| **Custom DNS** | Plus | `allowsCustomDNS` — user-supplied resolver (including DNS-stamp parsing for custom presets). |

---

## 4. Accounts & zero-knowledge backup

Optional account login and encrypted settings backup. None of this is required to use protection.

| Feature | Tier | Notes |
|---|---|---|
| **Optional account login (Apple + Google)** | Free | Native id_token flow exchanged at Supabase Auth (`grant_type=id_token`) with a hashed nonce; only the resulting Supabase session is stored device-locally in the Keychain. Email/password sign-in is intentionally not offered (Dropped). |
| **Zero-knowledge encrypted backup** | Free | Client-side AES-256-GCM envelope; the random payload key is wrapped in PBKDF2-HMAC-SHA256 (210k iters) key slots. Only ciphertext + non-secret metadata upload to Supabase `user_backups` (RLS per user). The server cannot decrypt without a user-held secret. |
| **Minimized backup payload** | Free | Backs up enabled blocklist IDs, allowed/blocked domains, resolver settings, local-log prefs, guardian look, etc. — and explicitly excludes `isPaid`, QA flags, diagnostics, snapshots, and full blocklist bytes. |
| **Device-secret key slot** | Free | A 32-byte device secret in the device-only Keychain (`...ThisDeviceOnly`, not iCloud-synced) for seamless same-device restore. |
| **Recovery phrase + assisted recovery** | Free | An 8-word CVCV phrase (~105 bits) combined with a server-held recovery share via SHA256 to unlock the assisted-recovery slot. Two-factor: neither half alone decrypts. |
| **Passkey recovery slot** | Free | Optional WebAuthn-gated slot. **Note:** passkey recovery is **server-gated, not zero-knowledge** — the secret is released by the Worker only after a verified passkey assertion. Production readiness on physical devices depends on Associated Domains / AASA hosting (Planned). |
| **Account deletion / data rights** | Free | Authenticated Worker endpoint deletes backups, settings, entitlements, profile, and bug-report attachments, then the Supabase Auth user; the app signs out and clears local unlock material. |

---

## 5. Widget & Live Activity

Lock screen and Dynamic Island presence.

| Feature | Tier | Notes |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): a single `Activity<LavaActivityAttributes>` on the lock screen and in the Dynamic Island (expanded center / compactLeading guardian / compactTrailing + minimal status glyph). |
| **5-state protection display** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — each maps to a guardian pose, SF Symbol, and title. |
| **Live Activity action buttons** | Free | Pause 5 / 10 min, Resume, Reconnect — `LiveActivityIntent`s that run in the app process via `LavaProtectionCommandService`. Authenticated pause variants require local device auth. |
| **Single deduped, revision-gated reconcile** | Free | `LavaLiveActivityController` keeps one Activity, updates only on real id/content change, and gates updates by `ProtectionPauseStore` revision so stale intent retries can't regress state. |
| **Live Activities toggle** | Free | User-toggleable in Settings (`setUsesLiveActivities`), available on iPhone/iPad only. |

---

## 6. Onboarding

First-run flow that installs the local VPN config and sets sensible defaults.

| Feature | Tier | Notes |
|---|---|---|
| **Multi-page first-run flow** | Free | `OnboardingFlowView` — 6 pages: `lava, guardIntro, features, vpn, notifications, done`. (Profile install and the notification prompt happen at the right step, not up front.) |
| **Local VPN profile install** | Free | Installs the local VPN config during onboarding **without** enabling Connect-On-Demand, so protection is never silently auto-on at completion — the Guard surface stays authoritative. |
| **Notification permission prompt** | Free | Requested in-flow at the notifications step. |
| **Recommended defaults applied** | Free | Device DNS resolver, device-DNS fallback on, local logging on (counts + history + activity), Block List Project Phishing + Scam enabled, continue without account (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Settings

Configuration, security, diagnostics, and feedback surfaces.

| Feature | Tier | Notes |
|---|---|---|
| **App-unlock passcode + biometrics** | Free | `SecurityController`: salted SHA256 passcode verifier in the Keychain + `LAContext` biometrics, with an app-unlock blocking overlay and privacy mask on scene-phase changes. |
| **Per-surface protection** | Free | `SecurityProtectedSurface` gates six surfaces: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Each can independently require local device auth (e.g. the Settings tab returns `.requires(.appSettings)`). |
| **Lava Guard look picker (7 looks)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, each with a paired Dynamic Island glyph color. |
| **Match App Icon** | Free | Optional alternate app icon paired to the selected guardian look. |
| **Appearance** | Free | Light/dark/system color scheme. |
| **Local-only logging controls** | Free | Toggles for filtering counts, domain history (diagnostics), and network activity — all stored on-device. |
| **Reports / Activity (Guard detail)** | Free | Dynamic local-only diagnostics: block/allow counts, tunnel health, top domains. Domain rows appear only when history opt-in is on. Reached as a detail screen from the Guard tab (`GuardDestination.activity`). |
| **Filters (Guard detail)** | Free | Overview-first filter screen with Blocked Domains / Allowed Exceptions detail and a staged view/edit/confirm draft flow (`GuardDestination.filters`). |
| **Network & Lava State activity log** | Free | Bounded local-only event stream of network/runtime/user transitions, shared via App Group (`NetworkActivityLog`). |
| **Bug report** | Free | User-triggered wizard sending an anonymized bundle to `POST /v1/bug-reports`; no domain history in v1. Also reachable via shake-to-report (`RageShakeDetector`). |
| **Legal Notices + Version** | Free | Settings surfaces third-party legal notices (see [Third-party notices](../legal/third-party-notices.md)) and a version/build page. |

---

## App architecture (for orientation)

Three bundles share one App Group `group.com.lavasec`, alongside a `lavasec-ios: Shared/` sources folder compiled into them:

- **LavaSecApp** (`com.lavasec.app`) — SwiftUI app shell; in this build the root is a two-tab `TabView` (**Guard** + **Settings**), with Filters and Activity reached as detail screens under the Guard tab.
- **LavaSecTunnel** (`.tunnel`) — the on-device DNS filter/resolve engine.
- **LavaSecWidget** (`.widget`) — the WidgetKit Live Activity.
- **Shared/** — cross-target sources (not a bundle): App Group, command service, mascot, Live Activity attributes/intents.

App ↔ extension control uses `NETunnelProviderSession` **provider messages** (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), not Darwin notifications. Filter rules cross app → extension as App-Group snapshot files (`filter-snapshot.json` / `.compact`).

---

## Related docs

- Roadmap — planned and dropped features (Plus pricing/StoreKit positioning, Android port, URL-level protection, passkey Associated-Domain readiness, easter-egg mini-game, GPL-3.0 open-source release, etc.) live in the private roadmap, not in this public catalog.
- [GPL source-url-only compliance decision](../legal/gpl-source-url-only-compliance-decision.md)
- [Open-source list data terms carve-out](../legal/open-source-list-data-terms-carveout.md)
- [Third-party notices](../legal/third-party-notices.md)
