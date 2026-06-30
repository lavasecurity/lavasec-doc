---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# DNS Filtering & Blocklists

> Audience: engineers. This document describes the on-device DNS pipeline, the encrypted-transport resolver path, the filtering decision engine, and the source-url-only blocklist catalog model — with the precise numbers the code enforces. Status reflects code-confirmed reality. Where a plan and the code disagree, **code wins** and the divergence is called out inline.

All DNS filtering happens on the device; Lava never routes your browsing through its servers and never receives the stream of domains you visit — the backend holds only catalog metadata, an opaque per-user encrypted backup, and anonymized diagnostics you choose to send.

Lava is **local DNS/blocklist filtering**, not a guarantee that every malicious domain or URL is blocked.

---

## 1. The DNS pipeline (Implemented)

The filter/resolve engine runs inside the **NE / packet tunnel** — the `NEPacketTunnelProvider` extension `LavaSecTunnel` (`com.lavasec.app.tunnel`), which intercepts DNS only. The tunnel addresses are `10.255.0.2` (tunnel) and `10.255.0.1` (DNS server). The app process never sees query traffic; it only writes compiled artifacts into the **App Group** (`group.com.lavasec`) and signals the tunnel via NETunnelProviderSession **provider messages** (not Darwin notifications).

For each inbound DNS query the tunnel runs a fixed **query precedence** in `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap-first is a hard invariant.** A query that resolves the configured resolver's *own* hostname (the DoH/DoT/DoQ endpoint) must never be blocked or paused, or the tunnel could not bring encrypted DNS up. The dispatcher takes lazy closures so each step is read only when reached, preserving short-circuit (no snapshot read when a bootstrap response exists; no pause read when bootstrapping).
- **temporary pause** forwards upstream while a user-initiated pause TTL is active.
- **filter** evaluates the domain against the compiled snapshot and either forwards it or synthesizes a blocked response.

A query that passes the filter (action `.allow`) is handed to the resolver path (§3). The tunnel **fails closed** on cold start without a reusable snapshot: it installs a fail-closed runtime snapshot that blocks all traffic rather than resolving unfiltered.

---

## 2. The filtering engine (Implemented)

### 2.1 Decision precedence

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) applies the canonical safety precedence:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Order | Rule set | Outcome | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

A domain that fails normalization is blocked with reason `.invalidDomain` (fail-safe). The same precedence is mirrored in the binary on-disk form (`CompactFilterSnapshot`). The threat guardrail sits above the local allowlist by design: **payment never bypasses the non-allowable threat guardrail**, and a user exception cannot un-block a guardrail domain.

> Note: in the current working tree `nonAllowableThreatRules` / `guardrailSources` are empty (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); the precedence slot is wired and enforced but ships with no guardrail entries yet.

### 2.2 Rule storage and the resident-memory unit

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) stores `exactDomains` + `suffixDomains` sets. Matching (`containsNormalized`) does an exact lookup plus a parent-suffix walk (`hasSuffix`-style) at query time — there is **no subdomain subsumption at compile time**. One valid wildcard line is **one rule** and one memory-table entry. This 1-line = 1-rule identity is what makes the rule count the honest resource metric (§4).

### 2.3 Compiled snapshot forms

- **`FilterSnapshot`** — the in-memory compiled filter: `blockRules`, `allowRules`, `nonAllowableThreatRules`, and the resolver preset.
- **`CompactFilterSnapshot`** — the binary, mmap-friendly on-disk form the tunnel actually reads (magic `LSCFSNP1`, `fileVersion 1`). It is loaded zero-copy via mmap (§4.3).

The app writes both `filter-snapshot.json` and `filter-snapshot.compact` into the App Group; the tunnel decodes the compact artifact. A **warm-startup reuse** path (`FilterArtifactStore`) lets the tunnel reuse the on-disk compact artifact without recompiling, gated by an identity fingerprint and an atomically-written manifest; reuse is rejected (privacy-safe, field-name-only reason) when resolver transport, catalog coverage, or snapshot inputs change.

---

## 3. Encrypted transports & the resolver path (Implemented)

### 3.1 Transport enum

Unblocked queries are forwarded to the configured upstream resolver. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) has **five** values:

| Transport | Raw value | Annotation surfaced in UI |
|---|---|---|
| Device DNS | `device-dns` | *(none — the name is the transport)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

Built-in presets are Google, Cloudflare, Quad9, Mullvad (each in IP / DoH / DoT variants) plus Device DNS and Custom. Custom resolvers accept a plain IPv4/IPv6 server, a DoH URL, a DoT URL (`tls://` / `dot://`), a DoQ URL (`doq://` / `quic://`), or an `sdns://` DNS stamp; usernames/passwords and localhost are rejected. DoT/DoQ default to port `853`; DoH requires a path.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) executes DoH over `URLSession`. Every request opts into HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); Apple's loader falls back to H2/H1 natively, so it never makes a reachable resolver unreachable. The negotiated protocol is read from `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

The UI annotates **`DoH3` (no slash)** — e.g. "Quad9 (DoH3)" — **only when an h3 negotiation is actually observed** (`DoHHTTPVersion.dohAnnotation`); otherwise it shows `DoH`. DoH3 is preferred, never promised: the label is observational and resolver-scoped, never persisted ("confirmed DoH3" carry-over across restart was reverted). Requests POST `application/dns-message`; responses are content-type and length validated and the transaction ID is restored before write-back.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) uses pooled `NWConnection`s, **up to 4 connections per endpoint** (`maxConnectionsPerEndpoint = 4`), round-robin, so parallel queries avoid head-of-line blocking. It carries **idle-staleness** handling: providers like Cloudflare close idle DoT connections server-side (~10s) without surfacing a state change, so a reused connection idle longer than **8 seconds** (`reusedConnectionMaxIdleInterval = 8`) is refreshed before send, and a timeout on a reused connection earns **exactly one fresh-connection retry**.

### 3.4 DoQ — fresh connection per query

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) keeps a bounded pool of **4 lanes per endpoint**, but **each query opens a fresh QUIC connection** — a full handshake per query. The 4-lane pool provides **concurrency, not handshake reuse**.

**DoQ connection reuse status (Dropped / deferred).** Reuse was reviewed and benchmarked on device (34 fresh handshakes across 35 queries ≈ no reuse), then implemented as an iOS-26-gated multi-stream `NWConnectionGroup` path, device-tested against AdGuard DoQ, and **reverted as net-negative** (stream failures and fallback errors against a real server). RFC 9250 maps each query to its own QUIC stream, so reuse requires `NWConnectionGroup`/`openStream`, which is **iOS 26.0+ only**; the current deployment floor is **iOS 17**. Reuse is deferred until the floor reaches iOS 26. Custom DoQ is rejected on devices that don't support it ("DNS over QUIC is not supported on this device").

### 3.5 Resolution policy

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) owns the upstream policy:

1. **Transport routing** by the configured transport.
2. **Degradation to plain DNS** when an encrypted plan has no endpoints.
3. **Per-endpoint failover** with a backoff gate — a backed-off endpoint never touches the wire (outcome `backed-off`).
4. **Device-DNS fallback** when the primary returns no response *and* the plan allows it (the plan property is `shouldFallbackToDeviceDNS`, derived from the `fallbackToDeviceDNS` config field); the result is re-annotated as the device transport. Wire execution is injected behind executors so the policy is unit-testable; backoff state stays outside the pure policy.

---

## 4. Filter-rules budget, NE ceiling, and mmap

The shipped tier metric is the **filter-rules budget**: the total compiled domain **rules** a user can enable. This replaced the old enabled-list **count** cap (free 3 / paid 10), a dishonest proxy — one list can be 1K or 1M rules. There are **two layers**: a per-everyone device guardrail, and a per-tier monetization limit below it.

### 4.1 Tier limits (Implemented)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) is the source of truth:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Custom blocklists / DNS |
|---|---|---|---|---|
| **Free** | **500,000** | 25 | 25 | No |
| **Plus** (`.paid` / `.plus`) | **2,000,000** | 1,000 | 1,000 | Yes |

The tier limit is a monetization boundary, **never a paywall on the device guardrail**. **Lava Security Plus** unlocks customization only — never baseline safety, never the threat guardrail. Custom (paid) blocklists are fetched directly from the user's device, parsed and cached locally, and never proxied to Lava servers.

### 4.2 Device memory guardrail + NE ceiling (Implemented)

The packet tunnel is subject to the iOS **~50 MiB per-extension memory ceiling** (an OS per-extension-type design limit for packet tunnels since iOS 15, not RAM-scaled; it lives in a per-device-model `com.apple.jetsamproperties.{Model}.plist` and can be lower on older devices). Exceeding it triggers jetsam. There is no API for the ceiling, so the budget keeps margin under the cliff.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) does the math, denominated in filter rules (block + allow + guardrail):

| Constant | Value |
|---|---|
| `baselineMegabytes` | 4.0 MB (fixed process overhead, measured ≈3.5 MB, rounded up) |
| `estimatedBytesPerRule` | 9.0 B dirty resident per rule (measured ≈8.5 B, rounded up) |
| `maxResidentMegabytes` | 32.0 MB (target ceiling, leaving ~10 MB headroom under the observed ~40–46 MB jetsam cliff) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 rules** |

This **~3.26M-rule device guardrail** is the hard safety floor for *every* user, sitting above any subscription tier, and is **never a paywall**. Anchor measurement (device "chimmy", 2026-06-13): **789,831 rules → 9.9 MB `phys_footprint`**, i.e. ≈ baseline + per-rule cost.

### 4.3 mmap strategy (Implemented)

The compact snapshot is loaded with `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), and `CompactBinaryReader` returns zero-copy slices. The multi-megabyte domain-text blob stays **file-backed/clean** and is excluded from the jetsam-counted `phys_footprint`; only the decoded `[Entry]` tables cost resident memory (~6 B/rule on disk, ~8.5 B dirty resident). This lifts the on-device domain ceiling: the resident cost is the entry tables, not the whole artifact.

### 4.4 Two-layer enforcement (Implemented)

- **Authoritative (compile-time).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) enforces the budget on the **deduped union** of all enabled lists. The device guardrail is checked **first** (the hard floor); the tier limit binds below it. Over-budget configs are rejected deterministically — `exceedsDeviceMemoryBudget` or `exceedsTierFilterRuleLimit` — rather than letting the tunnel jetsam. The error names the two largest contributing lists so the fix is obvious.
- **Advisory (selection-time UI).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) drives the selection meter using a per-list **sum** with a **1.10 soft-ceiling margin** that compensates for the ~7–10% cross-list over-count (the per-list sum over-estimates the deduped union).

### 4.5 The parser (Implemented)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) counts rules literally: it drops comments/blanks/invalid lines, normalizes, dedups exact strings within a list (via a `Set`), and caps at **`maxRules = 1,000,000`** per list (default), with a 4,096-char max line length. Supported formats: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (auto tries hosts → dnsmasq → adblock → plain). One valid line = one rule = the memory unit.

> **Multi-host `hosts` lines (parser rules version 2).** A `hosts` line that maps one IP to several hosts (`0.0.0.0 a.com b.com c.com`) now emits **every** host as its own rule, not just the first; `maxRules` is enforced **per rule** (not per line) so a multi-host line near the cap can't overshoot. Because the same upstream bytes can now yield more rules, the parser's rules version was bumped **1 → 2**, invalidating stale `RuleSetCache` entries parsed under the old first-host-only behavior.

### 4.6 Download & decode robustness (Implemented)

The tunnel and catalog sync run inside the NE memory budget, so list ingestion is hardened against hostile or malformed inputs:

- **Streamed downloads.** `defaultDataFetcher` downloads list bytes to a temp file via `URLSession.download` (bounded peak memory) with a post-download size check (`maximumBlocklistBytes`) instead of buffering the whole body in RAM; an oversized body raises `BlocklistDownloadSizeLimitExceeded`.
- **Catalog metadata cap (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes` rejects an oversized remote catalog before decode, so a hostile/MITM host can't force an OOM JSON decode in the extension.
- **Lenient UTF-8 decoding.** A single invalid UTF-8 byte no longer rejects an entire list (which under fail-closed would block all DNS); invalid bytes become U+FFFD and only the offending line fails per-line validation and is dropped.
- **Named custom-blocklist errors.** A failed custom list now surfaces `customBlocklistUnavailable(displayName:reason:)` — "Couldn't load the custom blocklist '<name>'. <why>" — instead of a raw `URLError`; cancellation is propagated as cancellation, not a download failure.

---

## 5. Blocklist catalog & default sources

### 5.1 Catalog model (Implemented)

The **blocklist catalog** is the published list of available sources. The **lavasec-api Worker** serves JSON metadata from an R2 bucket at `GET /v1/catalog` (and `/v1/catalog/:version`); the device fetches the actual list **bytes** directly from each upstream `source_url`. The iOS catalog endpoints are `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

On device, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Fetches list bytes directly from `source.sourceURL`, enforcing a size cap.
2. Computes SHA-256 and accepts the bytes only if the checksum is in the catalog's `accepted_source_hashes`.
3. On mismatch, falls back to the last-good local cache, or **fails closed** (`checksumMismatch`) — unless the source explicitly allows direct upstream rotation.
4. Parses/normalizes/dedups locally.
5. Filters every parsed rule set through `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`) so an upstream list can never block Lava/Apple/identity-provider domains.

The **protected-domain set** (filtered out before activation): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (all suffix-matched). The Worker applies an equivalent `PROTECTED_SUFFIXES` filter when computing metadata; the device re-validates regardless.

### 5.2 Curated sources (Implemented)

`DefaultCatalog.curatedSources` is generated from the canonical [Blocklist Catalog](../legal/blocklist-catalog.md), currently **32** sources across seven categories: Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling, and Piracy & Torrent. The source families include The Block List Project, Phishing.Database, HaGeZi, OISD, StevenBlack, AdGuard, and 1Hosts.

`guardrailSources` is empty. GPL sources (HaGeZi, OISD, AdGuard) are catalog-visible but **opt-in / OFF by default**; the Worker gates launch sync/publish to `source_url_only` plus the cleared GPL prefixes (`hagezi-`, `oisd-`, `adguard-`).

### 5.3 Default-enabled lists for free users (Implemented)

The free default config is `OnboardingDefaults.lavaRecommendedDefaults`, which enables **Block List Basic** — a broad, permissively licensed combined list (ads + tracking + malware + phishing/scam) — with the device-DNS resolver preset (`resolverPresetID = DNSResolverPreset.device.id`) and the encrypted Device-DNS fallback **on** (`usesEncryptedDeviceDNSFallback = true`), routing to **Mullvad DoH** (`fallbackResolverPresetID = DNSResolverPreset.mullvadDoH.id`): if the device's own DNS wedges, allowed lookups are carried transiently over Mullvad DoH and then return to the device's DNS automatically. (The bare `AppConfiguration()` initializer defaults this fallback **off** — it is enabled only by accepting the recommended onboarding defaults.) This supersedes the earlier Block List Project Phishing + Scam pair: Basic's combined coverage subsumes them, and both remain selectable opt-in lists.

That free default is **produced by `defaultEnabled`**, not hardcoded. `blockListProjectBasic` sets `defaultEnabled: true`, and `DefaultCatalog.recommendedDefaultSourceIDs` is derived from `curatedSources.filter(\.defaultEnabled)`. `defaultEnabled` is "the single source of truth for the fresh-install default," mirroring the backend catalog's `default_enabled` column. Flowing through `recommendedDefaultSourceIDs` into `OnboardingDefaults`, it is the live mechanism — flip the flag on a source to change the default.

> **Default source-of-truth (one generated spec).** The catalog is generated from a single canonical spec ([Blocklist Catalog](../legal/blocklist-catalog.md)) that produces both the iOS `DefaultCatalog` and the backend seed, so the device and the served `/v1/catalog` metadata agree by construction. The fresh-install default is **Block List Basic**, off its `defaultEnabled: true` flag. The real tier gate is the 500K/2M filter-rules budget, not a list count.

### 5.4 Source-url-only GPL distribution model (Implemented)

**Source-url-only** is the GPL/IP-compliance distribution model: Lava publishes only the upstream URL + accepted hashes; the device fetches and parses lists itself. Lava **never** stores, mirrors, transforms, or serves third-party blocklist bytes. This **superseded the abandoned R2-mirror design** (the original "raw R2 mirror" plan was reverted on 2026-05-25).

On the Worker side, `syncOneBlocklist` fetches each upstream source and normalizes+hashes it (computing `source_hash`, `normalized_hash`, `entry_count`) but writes `raw_r2_key = null` / `normalized_r2_key = null` — only the catalog JSON metadata reaches R2. `check-gpl-blocklist-distribution.sh` is the CI guardrail enforcing the whole model: no mirror/transform code, no Lava artifact/download URLs, no GPL sources default-enabled, no Worker R2 writes of list bytes, no "Lava-hosted mirror" copy, no bundled GPL `.txt`/`.json`, and `source_url_only` required in migrations + legal docs.

> **License note:** first-party Lava code ships under **AGPL-3.0** (the `LICENSE` file is GNU AGPL v3, matching the README badge). The third-party blocklists (including HaGeZi, OISD, and AdGuard) remain under their own upstream licenses — the source-url-only model exists precisely so Lava can use them without ever redistributing copyleft list bytes. GPL-3.0 here is a property of the upstream lists, not of the Lava app.

---

## 6. Status summary

| Area | Status |
|---|---|
| DNS query precedence (bootstrap > pause > filter) | Implemented |
| Filter decision precedence (guardrail > allowlist > blocklist > default-allow) | Implemented |
| Threat-guardrail precedence slot (wired; ships with no entries yet) | Implemented |
| DoH / DoH3 (observational h3 label) | Implemented |
| DoT (4/endpoint pool, 8s idle refresh, one fresh retry) | Implemented |
| DoQ (fresh connection per query, 4-lane concurrency) | Implemented |
| DoQ connection reuse | Dropped / deferred to iOS-26 floor |
| Resolver degradation + per-endpoint failover + device-DNS fallback | Implemented |
| Filter-rules budget (Free 500K / Plus 2M) | Implemented |
| ~3.26M-rule device guardrail (32 MB target under 50 MiB NE ceiling) | Implemented |
| Zero-copy mmap of compact snapshot | Implemented |
| Source-url-only catalog + direct upstream fetch + hash validation | Implemented |
| Protected-domain filter | Implemented |
| Free default = Block List Basic | Implemented (generated catalog + iOS/backend projections agree) |
| First-party Lava code license | AGPL-3.0 (`LICENSE`); third-party lists stay GPL-3.0 upstream |

---

## See also

- [`../product/overview.md`](../product/overview.md) — product one-liner, privacy promise, tabs.
- Tiers & monetization (internal reference) — Lava Security Plus and the filter-rules budget as the tier metric.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — the source-url-only compliance decision.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — upstream blocklist/resolver licenses and attributions.
