# DNS Filtering & Blocklists

This document explains how Lava Security decides whether to allow or block a DNS
query, the encrypted transports it forwards allowed queries over, the compiled
filtering engine inside `LavaSecCore`, the blocklist catalog and its budgets, and
the source-url-only redistribution model that keeps Lava out of the business of
hosting third-party (GPL) list bytes.

Audience: engineers. Every claim is grounded in code or a plan; file paths are
repo-relative. Status tags follow the shared legend — **(Implemented)**,
**(In progress)**, **(Planned)**, **(Dropped)** — and where a plan and the code
disagree, the code wins.

> **Privacy promise.** DNS filtering happens locally on your device; Lava never
> receives your routine DNS queries, browsing history, or per-domain telemetry,
> and any optional account backup is end-to-end encrypted so Lava can only ever
> store ciphertext.

All filtering and forwarding runs inside the on-device `NEPacketTunnelProvider`.
Nothing about a query leaves the device except the upstream resolution itself,
which goes to the resolver you chose (Google plain DNS by default), not to Lava.

---

## 1. The DNS pipeline in the packet tunnel

The packet tunnel is `PacketTunnelProvider` (target name `LavaSecTunnel`,
`apps/ios/LavaSecTunnel/PacketTunnelProvider.swift`). For each outbound DNS
packet the tunnel:

1. **Parses the DNS packet** and extracts the queried domain.
2. **Evaluates the domain** against the compiled, memory-mapped filter snapshot
   (`CompactFilterSnapshot`) to get a `FilterDecision`.
3. **Blocks or forwards.** Blocked queries get a synthesized negative response;
   allowed queries are forwarded upstream over the configured transport, and the
   upstream answer is returned to the app that asked.

The forwarding path is optimized for latency, not just correctness: there is an
in-memory DNS response cache, in-flight query coalescing (identical concurrent
queries share one upstream resolution), and a reused UDP resolver socket per
upstream. The allow/block precedence is unchanged by these optimizations
(`plans/implemented/2026-05-16-dns-forwarding-performance.md:32-48`).
**(Implemented)**

The tunnel owns the live resolver instances (`doh` / `dot` / `doq`) and the
resolver runtime reset; it is bounded by the NetworkExtension memory ceiling
discussed in [§5](#5-filter-rules-budgets-the-ne-memory-ceiling-and-mmap-strategy).
Lifecycle (turn-on, pause/resume, on-demand, snapshot reload) is factored into
`VPNLifecycleController`; the app drives the tunnel via `sendProviderMessage`
(the command/provider-message mechanism), not Darwin `CFNotification` observers,
which don't self-fire inside the extension until a provider message pumps the run
loop. The app, the packet-tunnel extension, and the widget share `LavaSecCore`
state through the App Group `group.com.lavasec`. See
[the iOS client overview](./ios-client.md) for the target/App-Group topology.

**Scope: domain-only.** DNS sees only the queried domain, never the HTTPS path
or page. Blocking a whole trusted host (e.g. `docs.google.com`) to suppress one
scam page would overblock, so Lava does not do it. A separate URL-level rule
model is documented but **not built** — it is backlog-only (P3),
`plans/backlog/2026-05-19-url-level-protection-plan.md:13-39`. **(Planned)**

---

## 2. Encrypted transports (DoH / DoT / DoQ / DoH3)

`LavaSecCore` models five resolver transports — `plainDNS`, `dnsOverHTTPS`,
`dnsOverTLS`, `dnsOverQUIC`, and `deviceDNS` — in
`DNSResolverPreset.swift:6-11`. The three encrypted transports are all
implemented and instantiated in the tunnel (`PacketTunnelProvider.swift:251-275`).
The choice of transport is part of the resolver preset. The built-in encrypted
presets (Google/Cloudflare/Quad9 DoH and DoT variants) are not paid-gated — the
preset model carries no `isPaid`/premium flag. What **Lava Security Plus** gates
is **custom DNS resolvers and custom blocklists**, via
`FeatureLimits.allowsCustomDNS` / `FeatureLimits.allowsCustomBlocklists` (free =
`false`, paid = `true` — `SubscriptionPolicy.swift:12-13, 33-34, 41-42`). The
tunnel never bypasses guardrails for paid users; it ignores `isPaid`.

| Transport | What it is | Connection model | Status |
|---|---|---|---|
| **DoH** | DNS-over-HTTPS over `URLSession` | New request per query; HTTP/3 opportunistic (see DoH3) | **Implemented** |
| **DoT** | DNS-over-TLS | Bounded per-endpoint pool (round-robin, **max 4**) that reuses connections and refreshes idle/stale ones, with one fresh-connection retry on timeout | **Implemented** |
| **DoQ** | DNS-over-QUIC | **Fresh QUIC connection per query** (handshake paid each time); reuse not shipped | **Implemented** (per-query); reuse **Dropped** |
| **DoH3** | DNS-over-HTTP/3, written with no slash | Observational annotation on DoH | **Implemented** |

### DoH and the DoH3 annotation

`DoHTransport` (`apps/ios/Sources/LavaSecCore/DoHTransport.swift:4-22`) opts every
request into HTTP/3 and reports the negotiated ALPN. HTTP/3 is *preferred but
never promised*: a preset earns the `DoH3` annotation (e.g. `Quad9 (DoH3)`) only
when an `h3` ALPN negotiation is actually observed, and falls back to the plain
`DoH` label otherwise. Write `DoH3` with no slash; treat it as purely
observational, never as a guarantee. **(Implemented)**

DoH is opt-in and is **not** promoted to default — Google plain DNS remains the
default resolver (`OnboardingDefaults.swift:11`). Device QA found DoH functional
overall, with Cloudflare DoH the strongest candidate and Quad9 DoH showing
instability/backoff (`plans/under_review/2026-05-17-dns-over-https-device-qa.md:102-108`).
**(Implemented)**

### DoT

`DoTTransport` (`apps/ios/Sources/LavaSecCore/DoTTransport.swift:3-12`) keeps a
bounded per-endpoint connection pool (round-robin, capped at 4), reuses
connections, refreshes idle/stale ones, and retries once on a fresh connection
after a timeout. DoT therefore reuses connections, unlike DoQ. **(Implemented)**

### DoQ and the reuse status

`DoQTransport` (`apps/ios/Sources/LavaSecCore/DoQTransport.swift:4-10`) keeps a
bounded set of lanes per endpoint (also max 4) so parallel queries avoid
head-of-line blocking, but **each query opens a fresh QUIC connection** and pays
the handshake — connection reuse is **not shipped**. Reuse is a tracked "Track 4"
item; a reuse attempt was built and device-tested on iOS 26.5, failed with
`Socket-not-connected`, and was reverted. Per the status legend this makes DoQ
**reuse** a **Dropped** design (the OS QUIC reuse API is not ready), while
per-query DoQ itself ships. Do not re-attempt reuse until the OS QUIC API
matures.

There is **no built-in DoQ resolver preset**. `allPresets` exposes only
plain/DoH/DoT variants for Google, Cloudflare, Quad9, and DNS.SB
(`DNSResolverPreset.swift:1024-1038`). DoQ is reachable **only via a custom
resolver** — a DNS stamp (`sdns://`, protocol `0x04`) or a DoQ URL parsed by
`DNSResolverPreset` / `DNSResolverTransport` (`DNSResolverPreset.swift:381-393,
1072-1073, 1214-1228`). This keeps DoQ a power-user path until a stable reuse
story exists. **(Implemented)**

---

## 3. The filtering engine (`LavaSecCore`)

### Decision precedence

`CompactFilterSnapshot` / `CompactDomainRuleSet`
(`apps/ios/Sources/LavaSecCore/CompactFilterSnapshot.swift:123-137`) is the
binary, mmap-friendly compiled snapshot. It owns the `FilterDecision` precedence,
evaluated in this fixed order:

1. **Threat guardrail → block.** Always-on, backend-curated guardrail rules.
2. **Local allowlist → allow.** Your manual allow entries.
3. **Blocklist → block.** Your enabled blocklist sources.
4. **Default → allow.** Anything not matched is allowed through.

Guardrail rules **cannot** be overridden by the allowlist — they are checked
first and win. Guardrails are an always-on safety set published in the catalog's
`guardrails[]` array, not a user-selectable list. **(Implemented)**

### How a snapshot is built

`FilterSnapshotPreparationService`
(`apps/ios/Sources/LavaSecCore/FilterSnapshotPreparationService.swift`) is an
off-main actor that:

- syncs the catalog and any custom lists through a cache/network fallback ladder
  (fresh cache prefers cached then network; stale cache prefers network then
  cached; custom lists are cache-first on startup, network-first on refresh —
  `:34-41, 84-116`),
- merges and deduplicates rules into a single union,
- enforces the budget **authoritatively at compile time** on the deduped union
  (`:146-176`), and
- builds the snapshot/artifact.

The compile-time check is the authoritative one because it sees the real,
post-dedup union (including not-yet-fetched custom lists). Two distinct
over-budget errors are thrown on that union, with the device cap checked first:

- `exceedsDeviceMemoryBudget` — the hard device cap (jetsam safety).
- `exceedsTierFilterRuleLimit` — the subscription-tier cap, which binds *below*
  the device cap.

Both count the full union of block + guardrail + allowed-domain + blocked-domain
rules (`FilterSnapshotMemoryBudget.swift:75-94`). The two errors are kept
separate so the user copy can offer an upgrade for the tier case but not imply
the device can't cope for the device case. **(Implemented)**

### Local parsing and protected domains

`BlocklistParser` (`apps/ios/Sources/LavaSecCore/BlocklistParser.swift:58-62, 78,
120`) parses hosts / adblock / plain / dnsmasq formats locally, normalizes lines,
drops invalid / comment / IP lines, and dedups exact strings **within** a list
(via a `Set`). There is **no subdomain subsumption**: one valid wildcard line
counts as exactly one rule. A per-list parse cap of **1,000,000 rules**
(`maxRules`) applies.

Before any rule reaches the snapshot, the client filters out its own
**protected domains** so a raw or compromised upstream list can never block
Lava's update endpoints, Apple services, or the identity providers Lava signs in
with. The client-side allowlist (`DomainRuleSet.lavaSecProtectedDomains`,
`apps/ios/Sources/LavaSecCore/AppConfiguration.swift:211-233`) contains exactly:
`apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`
(Apple / iCloud / App Store); `lavasecurity.com`, `lavasecurity.app`,
`api.lavasecurity.app`, `lavasec.app`, `lavasec.example` (Lava domains); and
`accounts.google.com`, `google.com` (Google sign-in). A separate, broader
protected-suffix list runs **server-side** in the Worker — see
[§6](#6-source-url-only-gpl-compliance-model). **(Implemented)**

---

## 4. Blocklist catalog & default sources

### The catalog

The catalog is an R2-hosted JSON document (`schema_version` 2) at
`catalog/latest.json` (plus versioned `catalog/{version}.json`), served by the
API Worker (`lavasec-api`) at `GET /v1/catalog`
(`server/backend/worker/src/index.ts:110-139, 336-342, 556-588`). Each entry
carries `source_url`, `parse_format`, `license_name`, `accepted_source_hashes`,
`entry_count`, and `source_hash`, plus an always-on `guardrails[]` array
(`server/backend/worker/src/index.ts:116, 557`). The catalog lists **metadata
and the upstream `source_url` only** — never list bytes.

The app fetches each upstream `source_url` directly, verifies the downloaded
bytes against the **non-empty accepted-hash allowlist**, filters protected
domains, and parses locally (`BlocklistCatalogSync`). It **fails closed** — it
requires a non-empty accepted-hash set before it will trust any payload
(`apps/ios/Sources/LavaSecCore/BlocklistCatalogSync.swift:873-875, 915-916`,
`noAcceptedSourceHashes`), checks `sha256(data)` against an accepted hash and
throws `checksumMismatch` on any mismatch (`:899, 946, 952`), and serves the
**cached last-good** payload rather than a bad one when the network copy fails
verification (`:879-880, 895, 906-907`). **(Implemented)**

### Curated sources

`DefaultCatalog` (`apps/ios/Sources/LavaSecCore/BlocklistModels.swift:117-241`)
defines the curated sources and their licenses:

| Source | License | Notes |
|---|---|---|
| Block List Basic, Phishing, Scam, Ransomware (Block List Project) | Unlicense | Permissive; default-eligible |
| Phishing.Database Active Domains | MIT | Permissive |
| HaGeZi Multi (Light / Normal / PRO mini / PRO) | GPL-3.0 | Opt-in, source-url-only |
| OISD Small | GPL-3.0 | Opt-in, source-url-only |

HaGeZi presets fetch the **compressed** `*-onlydomains.txt` (wildcard) form, so
the compiled rule count is the device-truthful compressed number (e.g. PRO is
≈219K rules, not the ~473K uncompressed headline —
`plans/under_review/2026-06-13-filter-rules-budget-tier-revamp.md:26`). On the
backend, GPL sync is allowed only for `hagezi-*` / `oisd-*` list IDs, and AdGuard
remains inactive (`server/backend/worker/src/index.ts:539-545`). **(Implemented)**

### Shipped defaults

The shipped default config enables **only** the permissive Block List Basic
(`blocklistproject-basic`, Unlicense) — the single default-enabled source per the
low-risk source-direction decision
(`plans/implemented/2026-05-26-low-risk-blocklist-source-direction-plan.md:25,39`;
source defined at `BlocklistModels.swift:118-124`). The recommended onboarding
defaults instead enable Block List Project **Phishing + Scam** and select the
Google plain-DNS preset with device-DNS fallback on
(`OnboardingDefaults.swift:7-10, 11`). **No GPL source is default-enabled** —
HaGeZi/OISD stay off pending counsel and are only ever user-selected.
**(Implemented)**

### Custom lists (Plus)

**Lava Security Plus** unlocks custom Pi-hole-style HTTPS blocklist URLs and
custom DNS (gated by `FeatureLimits.allowsCustomBlocklists` /
`FeatureLimits.allowsCustomDNS`). Custom lists are fetched **directly on-device**,
never proxied through or logged to Lava servers, and are excluded from bug-report
payloads. They union with the catalog at tunnel compile time and replace
catalog-ID collisions at app prepare time
(`SubscriptionPolicy.swift:37-43`,
`FilterSnapshotPreparationService.swift:276-296`). **(Implemented)**

---

## 5. Filter-rules budgets, the NE memory ceiling, and mmap strategy

Lava gates by **compiled filter rules**, not by list count. A filter rule is one
compiled block/allow/guardrail entry — the honest unit, because one list can be
1K rules or 1M. This **replaced** the old enabled-list *count* cap (free 3 / paid
10), which was a dishonest proxy.

### The NE memory ceiling

The hard constraint is the NetworkExtension **packet-tunnel per-process jetsam
ceiling of ~50 MiB** — an OS per-extension-type design number since iOS 15, not
RAM-scaled. It lives in a per-device-model plist and can be **lower** on older
devices, and `vm-pageshortage` / `fc-thrashing` can jetsam a within-budget
extension under system pressure. There is no API to read it; jetsam is the only
signal, so the budget keeps margin under the cliff
(`FilterSnapshotMemoryBudget.swift:7-14`). **(Implemented)**

### mmap strategy

The domain-string blob is loaded zero-copy with
`Data(contentsOf:options:[.mappedIfSafe])`. Mapped/clean file pages are excluded
from the jetsam-counted `phys_footprint`, so the on-disk artifact size and the
number of lists are **not** memory factors — only the decoded, dirty rule-table
entries count. Measured on device: **789,831 rules → 9.9 MB `phys_footprint`**
(`FilterSnapshotMemoryBudget.swift:15-26`,
`PacketTunnelProvider.swift:555-557, 3684`). **(Implemented)**

### Budget math

The device guardrail is derived from these constants
(`FilterSnapshotMemoryBudget.swift:30-55`):

- baseline: **4.0 MB** process overhead
- per-rule dirty cost: **~9.0 bytes/rule** (table entry; domain text is mapped)
- target steady-state resident ceiling: **32 MB** (≈10 MB headroom under the
  observed ~40–46 MB cliff)
- ⇒ `maxFilterRuleCount` ≈ **3.26M rules**

This **~3.26M-rule device cap is a hard safety floor that applies to everyone,
above any tier — never a paywall.**

### Tier budgets

| Tier | Filter-rules budget | Source |
|---|---|---|
| **Free** | **500,000** | `SubscriptionPolicy.swift:29-35` |
| **Plus** | **2,000,000** | `SubscriptionPolicy.swift:37-45` |
| **Device guardrail (all users)** | **~3,260,000** | `FilterSnapshotMemoryBudget.swift:30-55` |

The curated catalog alone maxes out **under 1M rules**, so the 2M ceiling is only
reachable via large custom lists. Free also caps manual allowed/blocked domains
at 10 each; Plus raises both to 500
(`plans/under_review/2026-06-13-filter-rules-budget-tier-revamp.md:16,33`).

**Status nuance:** the gating mechanism (`SubscriptionPolicy` /
`FilterRuleBudget` / `FilterSnapshotMemoryBudget`) is **Implemented in code**; the
tier-revamp plan still sits under review, so treat it as **shipped in code,
In progress as a formalized tier rollout**.

### The advisory UI meter

`FilterRuleBudget` (`apps/ios/Sources/LavaSecCore/FilterRuleBudget.swift:9-26`) is
**pure UI math** for the selection meter: it sums per-list counts (which
over-count the deduped union by ~7–10%) and applies a soft **1.10** ceiling
margin before it blocks selection. It is **advisory only** — the authoritative
enforcement is the compile-time post-union check in
`FilterSnapshotPreparationService`. **(Implemented)**

---

## 6. Source-url-only (GPL) compliance model

Lava treats itself as a **local filtering engine / user-agent**, not a
distributor of third-party blocklists. The redistribution model is
**source-url-only** — the only allowed `redistribution_mode` value:

> Lava publishes only catalog **metadata** plus accepted SHA-256 hashes and the
> upstream `source_url`. The app fetches each list directly from its upstream URL
> and parses it on-device. Lava never hosts, mirrors, merges, transforms, or
> serves third-party (GPL) blocklist bytes from R2.

This is the live, shipped model
(`plans/implemented/2026-05-25-source-url-blocklist-safety-and-copy-plan.md:10-58`;
`server/backend/worker/src/index.ts:75, 1230-1231`). In the catalog,
`raw_r2_key` / `normalized_r2_key` are forced `NULL`, and the rationale is to
sidestep GPLv3 verbatim-copy / modified-source obligations and Apple-distribution
risk by never becoming a redistributor of third-party artifacts. **(Implemented)**

The earlier **raw-R2-mirror** approach (`raw_mirror_app_processing` — storing and
serving list bytes from R2) was **built then superseded/dropped** on 2026-05-25 in
favor of source-url-only
(`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md:8,21`).
**(Dropped)**

### Server-side validation (metadata only)

When the Worker syncs a source it runs `normalizeBlocklist` **only to compute
metadata** (`entry_count` / `normalized_hash`) — not to store bytes. Limits:
upstream response ≤ **25 MiB** (`MAX_BLOCKLIST_BYTES`), line ≤ **2048** chars,
normalized domain count ≤ **500,000** (`MAX_NORMALIZED_DOMAINS`). The Worker also
strips a broader **`PROTECTED_SUFFIXES`** set than the client — including
`supabase.co`, `cloudflare.com`, and `github.com` alongside Apple, iCloud, Lava,
and Google — so server-computed metadata never reflects rules that would block
Lava's own infrastructure dependencies
(`server/backend/worker/src/index.ts:172-191, 1183, 1348`). **(Implemented)**

### CI guardrail

`scripts/check-gpl-blocklist-distribution.sh:32-65` fails the build if code:
mirrors list bytes, exposes Lava artifact URLs
(`download_path`/`manifest_path`/`artifact_kind`), enables GPL sources as
production defaults, writes blocklist bytes to R2, or uses Lava-hosted-mirror
copy. It also requires `source_url_only` to be present in migrations and legal
docs. **(Implemented)**

### Out of scope for distribution hardening

Stricter mirror validation — canary domains, percent-change thresholds,
pending-review, admin approval, signed catalog, and a scheduled threat-intel
feed — is backlog-only (P2),
`plans/backlog/2026-05-16-mirror-validation-threat-intelligence-plan.md:20-63`.
Current Worker validation is technical limits plus protected-domain skip.
**(Planned)**

---

## Related docs

- [iOS client overview](./ios-client.md) — targets, App Group, VPN lifecycle.
- [Resolver transports](./dns-filtering-and-blocklists.md) — preset/transport enum and DNS-stamp parsing detail.
- [Backend & data architecture](./backend-and-data.md) — the catalog Worker, R2, and Supabase RLS.
- Plan: `plans/under_review/2026-06-13-filter-rules-budget-tier-revamp.md` — the filter-rules budget revamp.
- Plan: `plans/implemented/2026-05-25-source-url-blocklist-safety-and-copy-plan.md` — source-url-only safety and copy.
