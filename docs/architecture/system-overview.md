---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# System Overview

> **Audience:** engineers. This is the whole of Lava Security on one page — what the parts are, how data moves between them, and where the trust boundaries sit. Per-component docs go deeper; this one exists so you can hold the system in your head before reading them.
>
> **Authority:** where this doc and a plan disagree, **code wins**. Status reflects the code-confirmed reality, not plan aspiration. See the [Status legend](#8-status-legend) at the bottom.

## 1. Product one-liner

Lava Security is a privacy-first iOS app that filters DNS **locally on the device** through a NetworkExtension packet tunnel, blocking malicious and unwanted domains for non-technical users (parents, older adults) — with core protection free forever and no account required.

## 2. The privacy promise (canonical)

> All DNS filtering happens on the device; Lava never routes your browsing through its servers and never receives the stream of domains you visit — the backend holds only catalog metadata, an opaque per-user encrypted backup, and anonymized diagnostics you choose to send.

Everything below is in service of keeping that sentence true. The architecture is deliberately small on the server side: the device does the work, and the backend never sees a query.

## 3. Components

### iOS client (three executable targets + shared code, one App Group `group.com.lavasec`)

| Component | Bundle / location | Role | Status |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | SwiftUI app shell; entry point, two-tab Guard + Settings nav (Filter/Activity are Guard detail screens; Network Activity moved under Settings → Advanced). | Implemented |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; the on-device DNS filter/resolve engine. Subject to the iOS **~50 MiB per-extension memory ceiling**. | Implemented |
| **LavaSecWidget** | `com.lavasec.app.widget` | WidgetKit Live Activity (lock screen + Dynamic Island). | Implemented |
| **Shared/** | `Shared/` | Cross-target sources: App Group, command service, mascot, Live Activity attributes/intents. | Implemented |

**App-side controllers (in LavaSecApp):**

- **AppViewModel** — the app-side controller (god-object): owns the `NETunnelProviderManager` lifecycle, shared-state persistence, provider messaging, Live Activity reconcile, catalog sync, backup, StoreKit, and auth.
- **RootView** — two-tab `TabView` (Guard + Settings), with Filter and Activity reached as detail screens under Guard; gates onboarding, hosts security-lock / privacy-mask overlays.
- **SecurityController** — passcode (salted SHA256 in Keychain) + biometrics + per-surface protection.
- **LavaLiveActivityController** — single-Activity reconciler, deduped and revision-gated.
- **OnboardingFlowView** — multi-page first-run flow (6 pages: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (platform-agnostic SwiftPM package, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — compiled filter + decision precedence; the compact form is the mmap-friendly on-disk artifact the tunnel reads.
- **DNSQueryDispatcher** — query precedence: bootstrap > pause > filter.
- **ResolverOrchestrator** — transport routing, plain-DNS degradation, per-endpoint failover, device-DNS fallback.
- **DoHTransport / DoTTransport / DoQTransport** — encrypted transport executors.
- **FeatureLimits** (in `SubscriptionPolicy.swift`) — tier ceilings (source of truth), via the static `.free` / `.paid` members.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — device-guardrail math + authoritative post-union budget enforcement.
- **BlocklistCatalogSync / BlocklistParser** — catalog fetch, direct upstream download, local parse/normalize/dedup, protected-domain filter.
- **GuardianMascotAnimation** — 7-state mascot state graph (rendered by `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — backup crypto + payload.
- **SupabaseIDTokenAuth** — raw-URLRequest `id_token` auth (no SDK).

### Backend

| Component | Role | Status |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker (`api.lavasecurity.app`): catalog reads, admin/cron blocklist sync + publish, anonymous bug reports, account deletion, App Store entitlement mirroring, QA probes. | Implemented |
| **lavasec-email Worker** | Receive-only Cloudflare Email Routing forwarder for `@lavasecurity.app`; rejects unknown/oversized mail. | Implemented |
| **Supabase Postgres** | Accounts, `user_backups`, catalog metadata, service-role-only tables; **RLS on every public table**. | Implemented |
| **Cloudflare R2** (the production R2 bucket, a separate preview bucket for staging) | Catalog snapshots + the round-robin sync cursor. **Never** third-party blocklist bytes; the bug-report attachment upload route was removed (legacy objects are only deleted on account deletion). | Implemented |
| **Cloudflare D1** (the help-feedback database) | Append-only anonymous help-article feedback votes. | Implemented |

## 4. Data-flow diagram

The single most important property: **the encrypted DNS resolver path (right side) never touches Lava's backend (bottom).** The device fetches catalog *metadata* from the Worker, but list *bytes* and the actual query stream go directly to third parties.

```
                                  YOUR iPHONE
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                                                                             │
 │   ┌──────────────┐   provider messages    ┌───────────────────────────┐    │
 │   │  LavaSecApp  │ ─────────────────────►  │      LavaSecTunnel        │    │
 │   │ (AppViewModel│   (reload-snapshot /    │  (NEPacketTunnelProvider) │    │
 │   │  controller) │    pause / config)      │                           │    │
 │   └──────┬───────┘                         │   DNSQueryDispatcher       │   │
 │          │                                 │   bootstrap > pause >      │   │
 │          │ writes / reads                  │   ┌──────────────────────┐ │   │
 │          ▼                                 │   │  CompactFilterSnapshot│ │   │
 │   ┌──────────────────────────┐  mmap       │   │  guardrail > allow >  │ │   │
 │   │  App Group container      │ ◄──(read)── │   │  block > default-allow│ │   │
 │   │  group.com.lavasec        │            │   └──────────┬───────────┘ │   │
 │   │  • filter-snapshot.compact│            │              │ allowed     │   │
 │   │  • app-configuration.json │            │              ▼             │   │
 │   │  • tunnel-health.json      │           │   ┌──────────────────────┐ │   │
 │   │  • pause/session UserDefs  │           │   │  ResolverOrchestrator│ │   │
 │   └──────────────────────────┘             │   │  DoH3/DoT/DoQ/IP +   │ │   │
 │          ▲                                 │   │  device-DNS fallback │ │   │
 │          │ reads (Live Activity)           │   └──────────┬───────────┘ │   │
 │   ┌──────┴───────┐                         └──────────────│─────────────┘   │
 │   │ LavaSecWidget│                                        │                 │
 │   │ (Dynamic Isl.│                                        │ encrypted DNS   │
 │   │  + lock scr.)│                                        │ (query stream)  │
 │   └──────────────┘                                        │                 │
 └──────────────────────────────────────────────────────────│─────────────────┘
        │ (a) catalog          │ (b) list bytes              │ (c) blocked → NXDOMAIN
        │  metadata            │  (direct from upstream)     │     allowed → forwarded
        ▼                      ▼                             ▼
 ┌──────────────┐   ┌──────────────────────┐    ┌───────────────────────────────┐
 │ lavasec-api  │   │  Upstream blocklists  │   │  Public DNS resolver           │
 │ Worker       │   │  (HaGeZi, OISD,       │   │  (Quad9 / Cloudflare / Google  │
 │ GET /v1/     │   │   Block List Project) │   │   / Mullvad; user-chosen)       │
 │  catalog     │   └──────────────────────┘    └───────────────────────────────┘
 └──────┬───────┘
        │ reads/writes (metadata only)
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  LAVA BACKEND (sees no DNS queries, no browsing history)                   │
 │  • Supabase Postgres: accounts, user_backups (opaque ciphertext), catalog │
 │  • Cloudflare R2: catalog/latest.json, the round-robin cursor             │
 │  • lavasec-email Worker: receive-only @lavasecurity.app forwarding         │
 └──────────────────────────────────────────────────────────────────────────┘
       ▲
       │ (d) optional: encrypted backup envelope (PostgREST, RLS) — ciphertext only
       │     entitlement mirror, anonymous bug reports, account deletion
       └──── from LavaSecApp, only when the user opts in
```

## 5. Data flows

### A. The DNS path (per query, all on-device) — Implemented

This is the hot path and the privacy core. It runs entirely inside `LavaSecTunnel`; nothing here reaches Lava's servers.

1. The packet tunnel intercepts a DNS query (tunnel DNS server `10.255.0.1`).
2. **`DNSQueryDispatcher`** applies query precedence: **bootstrap > pause > filter**. Bootstrap-first is a hard invariant — the resolver's own hostname is resolved before any filtering so the resolver can never block itself.
3. If not bootstrap and not paused, the domain is evaluated against **`CompactFilterSnapshot`** (loaded from the App Group via `Data(contentsOf:options:[.mappedIfSafe])` zero-copy mmap). Decision precedence is **threat guardrail > local allowlist (allowed exceptions) > blocklist > default-allow**; invalid domains are blocked.
4. **Blocked** → the tunnel answers locally (no upstream contact). **Allowed** → the query is handed to **`ResolverOrchestrator`**.
5. `ResolverOrchestrator` routes to the configured transport — **`DoH3` / `DoT` / `DoQ` / plain DNS (`IP`)** — with per-endpoint failover behind a backoff gate, plain-DNS degradation when an encrypted plan has no endpoints, and **device-DNS fallback** when the primary returns no response and the plan allows it.
6. The resolver reply is returned to the OS. The user's query stream goes only to the **user-chosen public resolver**, never to Lava.

Transport notes (verbatim conventions): `DoH3` (no slash) is annotated **only when an h3 negotiation is actually observed** — preferred, never promised. **`DoT`** pools up to 4 NWConnections per endpoint with idle-staleness refresh + one fresh-connection retry. **`DoQ`** opens a **fresh QUIC connection per query** (no reuse); the 4-lane pool gives concurrency, not handshake reuse — connection reuse was built, device-tested, and **reverted** (deferred until the iOS-26 deployment floor). See [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md).

### B. Catalog fetch + blocklist load (source-url-only) — Implemented

How the filter rules get onto the device. Lava is a **source-url-only** distributor: it publishes only the upstream URL + accepted hashes and **never stores, mirrors, transforms, or serves third-party blocklist bytes.**

1. The device fetches catalog **metadata** from the Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON served straight from R2 (`catalog/latest.json`), split into `sources[]` + `guardrails[]`, each entry carrying `source_url` + `accepted_source_hashes`.
2. For each enabled source, the device downloads the list **bytes directly from `source_url`** (the upstream — HaGeZi, OISD, Block List Project, etc.), **not** from Lava.
3. The device parses the fetched bytes locally under size/rule caps. Community lists are accepted as served over TLS — the catalog's `accepted_source_hashes` are advisory (cache identity + audit), not a hard gate — so a rotated list is never rejected for drifting from a pinned hash. Lava's threat-guardrail tier stays hash-pinned.
4. **`BlocklistParser`** parses/normalizes/dedups locally (auto / plain / hosts / adblock / dnsmasq formats), then **`DomainRuleSet.lavaSecProtectedDomains`** strips protected domains (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) so an upstream list can never block Lava/Apple/identity-provider domains.
5. **`FilterSnapshotPreparationService`** merges the deduped union and runs **authoritative budget enforcement** (device cap first, then tier), then writes `filter-snapshot.compact` into the App Group.
6. `AppViewModel` sends a `reload-snapshot` provider message; the tunnel reloads.

The Worker side mirrors this: its admin/cron sync fetches each upstream, hashes/counts it, writes `raw_r2_key = null` / `normalized_r2_key = null`, and republishes metadata only. The blocklist-catalog model and the backend sync path are covered in [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) and [Backend & Data](./backend-and-data.md).

**Budget model (two layers):**
- **Device guardrail (everyone, never a paywall):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3,262,236 rules** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule` — a 32 MB target under the ~50 MiB NE ceiling. Over-budget configs are rejected deterministically rather than letting the tunnel jetsam.
- **Tier ceiling (`FeatureLimits`):** **Free 500K rules / Plus 2M rules**, which binds below the device guardrail. This replaced the old enabled-list **count** cap (free 3 / paid 10) — list-count caps are obsolete.

> **Default-enabled source of truth:** the shipped free default is **Block List Basic** (`OnboardingDefaults.lavaRecommendedDefaults`). It is derived on-device from each curated source's `defaultEnabled` flag (`BlocklistSource.recommendedDefaultSourceIDs`), which mirrors the backend catalog `default_enabled` column generated from the same canonical catalog spec.

### C. Backup (zero-knowledge, opt-in) — Implemented

Optional, account-gated, and the only user data that lands in the backend — as **opaque ciphertext**.

1. The user optionally signs in (Apple or Google only; **email/password is Dropped**) via native `id_token` exchanged at Supabase Auth (`grant_type=id_token`, hashed nonce). Only the resulting Supabase session is stored, device-local, in the Keychain.
2. **`BackupConfigurationPayload`** assembles a minimized plaintext (enabled blocklist IDs, allowed/blocked domains, resolver prefs, local-log prefs, LavaGuard ledger). It **excludes** `isPaid`, QA, diagnostics, and full blocklists.
3. **`ZeroKnowledgeBackupEnvelope`** seals it with **AES-256-GCM** under a random 32-byte payload key; that key is wrapped into per-secret **key slots** via **PBKDF2-HMAC-SHA256 (210k iters)** — device-secret slot, assisted-recovery slot, optional passkey slot. The optional passkey slot is wrapped with an authenticator **WebAuthn PRF / `hmac-secret`** output (HKDF-derived); that output never leaves the client, so the passkey slot is genuinely zero-knowledge — no server-held value unwraps it (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** uploads **only ciphertext + non-secret metadata** to Supabase `user_backups` directly via PostgREST, scoped by per-user **RLS**. (There is no Worker upload route; the Worker touches `user_backups` only to delete it during account deletion.)
5. **Recovery:** seamless same-device restore via the device-secret slot; off-device via the **8-word CVCV recovery phrase** (~105 bits) combined with a server-held recovery share via SHA256 (two-factor — neither half alone decrypts); or, when a passkey slot was sealed, via the client-side WebAuthn PRF / `hmac-secret` output (no server-held value involved). The server never registers passkeys, issues WebAuthn challenges, or stores any recovery secret.

See [Accounts & Backup](./accounts-and-backup.md).

### D. App ↔ extension control plane — Implemented

Three processes (app, tunnel, widget) coordinate through the App Group `group.com.lavasec`:

- **Control = NETunnelProviderSession provider messages**, **not** Darwin notifications. `AppViewModel` encodes a `LavaSecProviderMessage {kind, operationID}` and calls `session.sendProviderMessage`; the tunnel's `handleAppMessage` switches on the kind (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Shared files** carry rules/config/health (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **shared UserDefaults stores** (`ProtectionSessionStore` / `ProtectionPauseStore`) carry session + pause state.
- **`LavaProtectionCommandService`** executes Live-Activity / AppIntent pause/resume commands under a `flock` file lock with revision dedup and auth-required denial; **reconnect bypasses it** to restart the tunnel directly (`startVPNTunnel`).
- **Connect-On-Demand** is enabled only *after* the tunnel confirms connected, never at profile install — so a freshly installed onboarding profile can't bring up an un-turn-off-able tunnel.

See [iOS Client](./ios-client.md).

## 6. Trust boundaries & privacy-preserving design

| # | Boundary | What crosses it | What deliberately does NOT |
|---|---|---|---|
| 1 | **Device ↔ public DNS resolver** | Allowed DNS queries (encrypted: DoH3/DoT/DoQ, or plain IP) go to the user-chosen resolver. | Lava never sees the query stream; it is not in this path at all. |
| 2 | **Device ↔ upstream blocklist hosts** | The device downloads list bytes directly from `source_url`. | Lava never proxies, mirrors, or stores third-party blocklist bytes. |
| 3 | **Device ↔ lavasec-api Worker** | Catalog **metadata** reads; opt-in anonymous bug reports; entitlement mirror; account deletion. | No DNS queries, no browsing history, no plaintext settings. |
| 4 | **Device ↔ Supabase** | Opt-in **encrypted backup envelope** (ciphertext only, PostgREST under RLS); account rows. | The server cannot decrypt the backup without a user-held secret. |
| 5 | **App ↔ tunnel extension** (on-device) | Provider messages + App Group files/defaults. | The tunnel fails **closed** on cold start with no reusable snapshot. |

**Privacy-preserving design principles, grounded in the above:**

- **Local-first filtering.** The decision engine and resolver run inside the NE extension on the device. The backend is metadata-only by construction — there are no tables for routine DNS queries or per-domain telemetry.
- **No account required for protection.** Core protection is free forever; auth and backup are strictly opt-in.
- **Source-url-only distribution.** Decouples Lava from third-party list bytes (GPL/IP-compliance + App Review safety) and keeps a CI guardrail enforcing "no mirror code, no Lava artifact URLs, no R2 byte writes."
- **Zero-knowledge backup at rest.** Client-side AES-256-GCM; the server holds ciphertext + KDF metadata + a recovery share, never the plaintext, the recovery phrase, or the unwrapped key. The optional passkey slot is wrapped with a client-side WebAuthn PRF / `hmac-secret` output, so it too is zero-knowledge — no server-held value unwraps it.
- **Device-local secrets.** Backup unlock material uses `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — not iCloud-synced, not in device backups.
- **Service-role isolation.** `bug_reports`, `mirror_events`, and `qa_developers` are revoked from anon/authenticated PostgREST roles; only the Worker (service role) touches them.
- **Safety is never for sale.** Payment unlocks **customization only**. It never bypasses the non-allowable **threat guardrail**, whose integrity is enforced by accepted SHA256 source hashes (not a server signature). Precedence is consistent everywhere: **threat guardrail > local allowlist (allowed exceptions) > blocklist > default-allow.**

## 7. Per-component docs

> These are the sibling documents in the architecture doc-set. The DNS filtering engine and the blocklist catalog are documented together in one file.

- [iOS Client](./ios-client.md) — targets, App Group, control plane, protection state model, onboarding, Live Activity.
- [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) — filter snapshot, decision precedence, resolver transports (DoH3/DoT/DoQ), memory budget, mmap; plus the source-url-only catalog model, catalog fetch, local parse/normalize, protected-domain filter, and tier budget.
- [Accounts & Backup](./accounts-and-backup.md) — Apple/Google auth, zero-knowledge envelope, key slots, recovery phrase, client-side WebAuthn-PRF passkey recovery.
- [Backend & Data](./backend-and-data.md) — lavasec-api + lavasec-email Workers, Supabase schema + RLS, R2/D1, deployment.

## 8. Status legend

This doc-set uses one status vocabulary. The **lane folder is the authoritative status**; stale frontmatter inside a plan is a doc bug, not a status. **Code overrides plans.**

| Status | Meaning | Plan lane | Code |
|---|---|---|---|
| **Implemented** | Shipped and confirmed in code | `plans/implemented/` | present & wired |
| **In progress** | Actively being built; partially landed | `plans/inflight/`, `plans/under_review/` | partially present |
| **Planned** | Designed, not built | `plans/backlog/` | absent |
| **Dropped** | Rejected or reverted | `plans/dropped/` (or reverted commit) | absent / removed |

**Status of things mentioned on this page:**

- **Implemented:** the four iOS targets + App Group; provider-message control plane; on-device DNS filtering with DoH3/DoT/DoQ/IP transports; source-url-only catalog fetch + local parse; filter-rules budget (Free 500K / Plus 2M) + ~3.26M device guardrail; multi-page onboarding; passcode/biometric security; single deduped Live Activity; zero-knowledge backup; Apple + Google auth; account deletion; entitlement mirroring; QA probes; the `LavaDesignSystem` token layer (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), including the `LavaTier` depth model (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), the `.lavaTier(_:)` / `.lavaTierMetadata()` modifiers wired into representative surfaces (e.g. `SettingsView`), and the `dangerRed` and `LavaSpacing` tokens — locked by `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **In progress:** continued rollout of the design-system token layer across more surfaces (the `LavaTier` depth model and the token layer ship — see below — but a dedicated `LavaColorRole` is not yet present, so accents still resolve to raw colors).
- **Planned:** the Lava Guard easter-egg mini-game; extra mascot expressions (the mascot has exactly **7** states); fully production-ready passkey recovery on physical devices (Associated Domains / AASA); server-side App Store JWS re-verification (`verification_status` is `client_verified_storekit`); a dedicated `LavaColorRole` token so design-system accents resolve through a semantic role rather than raw colors.
- **Dropped:** DoQ connection reuse (per-query fresh connections); email/password sign-in (Apple + Google only); the GPL raw-R2 mirror design (superseded by source-url-only).
