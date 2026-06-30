---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Key Design Decisions

> Audience: engineers and leadership. This is the ADR-style record of the load-bearing design decisions behind Lava Security — the ones that shaped the architecture, the privacy promise, or the product boundary, and especially the ones that were tried and reversed. Each entry gives the **Decision**, its **Context**, the **Rationale**, and a **Status** drawn from the project status legend (Adopted / Reverted / Superseded / Proposed).
>
> **Code wins.** Where a plan and the shipped code disagree, this record follows the code and calls out the divergence inline.

**Status legend (mapped to the doc-set status lanes):**

| Status here | Doc-set lane meaning |
|---|---|
| **Adopted** | Implemented — shipped and confirmed in code |
| **Reverted** | Dropped — built, then removed/reverted |
| **Superseded** | An earlier decision replaced by a later one |
| **Proposed** | Planned — designed, recommended, or recorded, but not yet applied in this tree |

Related reading: catalog distribution model in [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) and [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); shipped behavior in [`../product/features.md`](../product/features.md). Forward-looking direction lives in the internal roadmap.

---

## 1. On-device DNS filtering via `NEPacketTunnelProvider`

**Decision.** Filter DNS **locally on the device** through a `NEPacketTunnelProvider` packet tunnel (`LavaSecTunnel`, `com.lavasec.app.tunnel`), rather than `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager`, or a Safari content blocker.

**Context.** The product is a privacy-first filter for non-technical users (parents, older adults) shipping through the consumer App Store, with no account required. The competing NetworkExtension providers and managed-DNS APIs are restricted to supervised/MDM-managed devices or don't cover all of an app's DNS, and a resolver-side model would route the user's domain stream off the device.

**Rationale.** The packet tunnel is the only provider that (a) works for unmanaged consumer devices and (b) lets every DNS decision happen on-device, which is the foundation of the privacy promise: *all DNS filtering happens on the device; Lava never routes your browsing through its servers and never receives the stream of domains you visit.* The accepted trade-off is the iOS **~50 MiB per-extension memory ceiling** the tunnel must live under — a constraint that shapes several later decisions below.

**Status.** **Adopted** (foundational; in code from the initial prototype).

---

## 2. Source-url-only blocklist distribution

**Decision.** Lava publishes only the upstream blocklist **URL plus accepted hashes**; the device fetches the list **bytes** directly from each `source_url`, then parses, normalizes, dedups, and filters locally. Lava **never** stores, mirrors, transforms, or serves third-party blocklist bytes. The Worker writes only catalog **metadata** JSON to R2 (`raw_r2_key`/`normalized_r2_key` are null).

**Context.** The earlier design mirrored raw blocklist bytes into R2 so counsel could review distribution. Many upstream lists (HaGeZi, OISD) are GPL-3.0, so hosting their bytes would make Lava a redistributor of GPL data.

**Rationale.** Treating Lava as a local filtering engine / user agent — rather than a blocklist distributor — minimizes GPLv3 redistribution and App Review exposure. The device fetches each list over TLS directly from its curated `source_url` and parses it locally under strict size/rule caps; community lists are accepted as served (the catalog's `accepted_source_hashes` are advisory, not a hard gate — a single pinned hash cannot track a fast-rotating upstream and only produced false rejections), while Lava's threat-guardrail tier stays hash-pinned. Provenance is enforced at the catalog (a `source_url` change must use a new `list_id`), not by a client hash gate. Every parsed rule set is also passed through a protected-domain filter so an upstream list cannot block Lava/Apple/identity-provider domains. The model is enforced in CI by `check-gpl-blocklist-distribution.sh` (no mirror code, no Lava-hosted artifact URLs, no GPL sources default-enabled, no R2 byte writes).

**Status.** **Adopted**, and it **Superseded** the abandoned R2 raw-mirror plan (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, header "Superseded by the source-url-only implementation"). See [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Encrypted resolver transports (DoH / DoH3 / DoT / DoQ)

**Decision.** Ship four encrypted upstream transports alongside plain DNS and a device-DNS fallback, extracted into LavaSecCore: **DoH** (URLSession), **DoH3** (DoH preferring HTTP/3), **DoT** (pooled `NWConnection`s, up to 4/endpoint, with idle-staleness refresh and one fresh-connection retry), and **DoQ** (DNS-over-QUIC). Routing, plain-DNS degradation, per-endpoint failover with a backoff gate, and device-DNS fallback live in `ResolverOrchestrator`.

**Context.** Forwarding unblocked queries in cleartext to a resolver leaks the very domain stream the on-device model is meant to protect. The transports were built incrementally (DoH → DoH3 → DoT → DoQ).

**Rationale.** Encrypted upstream transport keeps unblocked queries private end-to-end. **DoH3** is labeled purely observationally — `assumesHTTP3Capable=true` is set and the negotiated protocol is observed, and the UI annotates `DoH3` (no slash) **only when an h3 negotiation is actually observed**, never promised, because h3 is best-effort per connection and a sticky claim would over-state behavior behind UDP-blocking firewalls. DoT pooling with idle refresh was a direct fix for Cloudflare silently closing idle DoT connections.

**Status.** **Adopted** (all four transports present and wired).

---

## 4. DoQ connection reuse — built, device-tested, reverted

**Decision.** **Do not** reuse QUIC connections for DoQ. `DoQTransport` opens a **fresh QUIC connection per query**; the 4-lane pool provides concurrency, not handshake reuse.

**Context.** RFC 9250 maps each DNS query to its own QUIC stream, so true reuse needs the multi-stream `NWConnectionGroup`/`openStream` API that is **iOS 26.0+ only**, while the deployment floor is iOS 17. An iOS-26-gated reuse path was nonetheless implemented (compiled Debug+Release against the Xcode 26 SDK) and **device-tested on iOS 26.5** against AdGuard DoQ.

**Rationale.** The reuse path failed on every attempt on device (`openStream`/`receive` errored, then the fallback hit "Socket is not connected"), measuring **net worse** than the per-query baseline (control: 34 handshakes / 35 queries, all-success). This empirically confirmed Apple DTS's "hold off on QUIC with the new Network framework" guidance, so the work was reverted rather than shipped; only the docs and guard-test rationale retain the finding so it is not re-attempted before the API matures.

**Status.** **Reverted** (deferred until the deployment floor reaches iOS 26). Describe DoQ as per-query fresh connections.

---

## 5. Reject a unifying `DNSResolvingTransport` protocol

**Decision.** **Do not** unify the resolver transports under a single `DNSResolvingTransport` protocol; keep the closure-based `ResolverOrchestrator.Executors` seam.

**Context.** A refactor (issue 407) proposed one protocol over all transports.

**Rationale.** The transports are too dissimilar — async encrypted executors (DoH/DoT/DoQ) versus synchronous multi-address plain/device transports — so a unifying protocol would be a worse abstraction than the existing injectable closure seam, which already keeps wire execution testable.

**Status.** **Reverted** / won't-implement (closed as a bad abstraction).

---

## 6. Zero-knowledge encrypted backup (passwordless, passkey exception noted)

**Decision.** Back up a **minimized** settings payload client-side: AES-256-GCM seals it under a random 32-byte payload key, which is wrapped into per-secret **key slots** via PBKDF2-HMAC-SHA256 (**210,000** iterations in production). Only ciphertext plus non-secret metadata upload to the Supabase `user_backups` table (RLS per user). The shipped flow is **passwordless**: device-secret slot (device-local Keychain) + assisted-recovery slot + optional passkey slot.

**Context.** Optional account login (Apple + Google only) enables cross-device settings restore. The server must never be able to read a user's blocklists, allowlists, resolver choice, or other settings.

**Rationale.** Plaintext and decrypting secrets exist only on the device; the server holds one opaque envelope per user. Assisted recovery is deliberately two-factor — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (NUL-delimited input) requires **both** the server-held share and the user's 8-word recovery phrase (~105 bits), so neither half alone decrypts. Unlock material is stored device-local (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **not** in synchronizable iCloud Keychain — a privacy hardening that reversed the original plan's synchronizable design. The **passkey slot is also genuinely zero-knowledge**: it is wrapped with a WebAuthn **PRF / `hmac-secret`** authenticator output (HKDF-SHA256 derived) that never leaves the client, so no server-held value can unwrap it. There is no service-role passkey table and no Worker WebAuthn-assertion gate — the earlier server-gated passkey design was dropped, removing all server-side passkey state (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Status.** **Adopted** (passwordless model, assisted recovery, and a zero-knowledge PRF-derived passkey slot, all in code). Making the passkey a fully production-ready recoverable factor on physical devices (Associated Domains / AASA hosting for the PRF model) is **Proposed** (backlog).

---

## 7. Fail-closed Connect-On-Demand

**Decision.** Add an `NEOnDemandRuleConnect` rule so an OS-stopped tunnel auto-restarts, with **fail-closed** as the safe default: when there is no reusable filter snapshot the tunnel blocks all traffic rather than passing it unfiltered. On-demand is **disabled before any stop** so the VPN stays turn-off-able.

**Context.** iOS was silently stopping the tunnel (reason 17) with nothing restarting it for ~45 minutes, leaving users unprotected. Naively enabling on-demand makes the VPN impossible to turn off, and a fail-open default would pass traffic during the gap.

**Rationale.** On-demand closes the silent-stop gap; disabling-before-stop preserves the user's ability to turn protection off; fail-closed ensures the gap is safe rather than silently unfiltered, recovered by `reconcileTunnelSnapshotAfterLaunch`. The change had side effects — on-demand re-triggered the "Add VPN Configurations" system prompt during onboarding — which spawned a multi-commit fix chain: stop enabling on-demand at install, gate launch/protection restore on onboarding completion, and **neutralize an inherited/orphaned config by removing it** (`removeFromPreferences`, silent) rather than by saving `on-demand=false` (`saveToPreferences` re-showed the prompt).

**Status.** **Adopted** (on-demand restart plus the onboarding/fail-closed fix chain).

---

## 8. Modular VPN refactor and the heat-regression discipline

**Decision.** Restructure the VPN path (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) for cache-first turn-on, bounded-parallel fetch, and flap coalescing — treating battery/latency as product requirements with explicit p50/p95 targets and **on-device** (not Simulator) profiling.

**Context.** Turn-on / refresh / pause / resume were slow. During the refactor a heat regression appeared (134% CPU, High energy, hot phone). A large agent panel first refuted the suspected cause using pre-regression evidence; a live device capture then confirmed it.

**Rationale.** The real cause was a self-sustaining `NEVPNStatusDidChange` refresh loop — a coalescing loop that re-armed forever (~370 events/s, main thread ~100%, `vpn-debug-log.jsonl` grown to ~180–210 MB) after a drop-reentrant guard was replaced. The fix reads the cached manager state and bounds the loop. The plan's own before/after device artifact records warm turn-on (`action.turnOn`) dropping from **2,722 ms → 287 ms** on iPhone 15 Pro; a separate, later post-modular opportunity review measured the warm path at **112 ms** (decode 51 + managerSetup 57) on the same device. The episode set the standard: structural refactors pause until a measured heat regression is bounded, and Simulator thermal/battery results are rejected as meaningless.

**Status.** **Adopted** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). A post-modular review keeps `PacketTunnelProvider` and `AppViewModel` as known surviving god-objects.

---

## 9. Filter-rules budget instead of a list-count cap

**Decision.** Gate tiers by a **filter-rules budget** — **Free 500K / Plus 2M** compiled domain rules — not by enabled-list count. A hard **~3.26M-rule device guardrail** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`) applies to **everyone** and is **never a paywall**. The compact domain blob is `mmap`'d (`.mappedIfSafe`) so it stays file-backed and outside jetsam-counted `phys_footprint`; only the decoded entry tables cost resident memory.

**Context.** The old cap was a list **count** (free 3 / paid 10). One list can hold 1K or 1M rules, so count was a dishonest proxy for the real constrained resource — the NE 50 MiB memory ceiling.

**Rationale.** Rules map to actual memory, so any combination of lists that fits is allowed. Authoritative enforcement runs at compile time on the deduped union in `FilterSnapshotPreparationService` (device guardrail first, then tier limit); the selection-time UI meter uses a per-list sum with a 1.10 soft-ceiling margin. Over-budget configs are rejected deterministically (keeping protection off) rather than letting the tunnel jetsam.

**Status.** **Adopted** in code (`SubscriptionPolicy.swift`), shipped in **v1.0.0**, which **Superseded** the list-count cap. The rules budget is now the live tier gate; the per-domain caps were also raised at 1.0 (Free 25 / Plus 1,000 allowed and blocked domains). See [`../product/features.md`](../product/features.md).

---

## 10. Plans as markdown + one-way Linear sync

**Decision.** Markdown files in `plans/<lane>/` are the **source of truth**; the **lane folder is the authoritative status** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). A push to `main` syncs plans **one-way** to Linear (team LAV), refreshing only title/description after creation; a separate **manual, reviewed** return-leg pulls Linear status/priority/lane back into plan frontmatter.

**Context.** A small team needs tool-agnostic, reviewable planning state that doesn't fight a project tracker, and an autonomous agent loop needs a stable place to read and write plan state.

**Rationale.** The field-ownership split keeps the two systems conflict-free — markdown owns content, Linear owns triage state — so a push never clobbers human triage. The `dropped/` lane keeps cancelled plans out of the sync pipeline so they don't reappear (created when Allowed Exceptions Guardrails / LAV-5 was rejected). Stale frontmatter inside a plan is a doc bug, not a status; the folder wins, and where code shows a feature shipped despite a "Backlog" frontmatter (e.g. account deletion), the code wins.

**Status.** **Adopted** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; `dropped/` lane in use).

---

## 11. Repo split + copyleft open-source of the client

**Decision.** Split the monorepo into per-component repos (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) and **open-source the first-party client under AGPL-3.0** in place of Apache-2.0, on the Mullvad/ProtonVPN copyleft precedent.

**Context.** Per-component development and an open-sourcing of the client. The license question is whether a competitor could fork the client, close it, and undercut on price.

**Rationale.** Copyleft forces derivatives to stay open, preventing a closed fork of the client — a "public client, private backend/ops" posture, with backend, legal, and ops kept private. AGPL-3.0 (rather than plain GPL-3.0) was chosen to close the network-use gap. The known GPL-vs-App-Store distribution tension is handled by Lava itself being the distributor of the App Store binary under its own copyright.

**Status.** **Adopted.** The repo split is **complete**: each component lives in its own repository — the public `lavasec-ios` client at tag v0.4.0, plus separate repositories for Android, the marketing site, backend/infrastructure, docs, and the CI/release pipeline — and `lavasec-ios`'s `README.md` "Repository layout" section lists only that repo's per-component contents (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`) with infrastructure noted as living in separate private repositories. The client is open-sourced under **AGPL-3.0**: the `lavasec-ios` `LICENSE` is the GNU Affero General Public License v3 and `README.md` carries the AGPL-3.0 badge.

---

## Appendix — other recorded reversals and rejections

These are smaller decisions, but each had a recorded flip.

| Decision | Rationale | Status |
|---|---|---|
| Custom DNS free vs paid | Monetization positioning; briefly allowed on free, then returned to paid-only | **Reverted** to paid-only |
| Email/password sign-in | Owning passwords adds reset/MFA/lockout/breach/takeover burden while Apple + Google suffice; bypass recovery would break zero-knowledge | **Reverted** / never shipped (Apple + Google only) |
| Allowed Exceptions Guardrails (LAV-5) | Guardrail precedence shipped via the simpler filter-list-edit revamp; payment must never bypass the high-confidence threat guardrail | **Reverted** (`dropped/` lane created) |
| TestFlight branch-promotion lockdown | Initial lockdown reconsidered; replaced by a planned post-open-source runner lockdown | **Reverted**, superseded by a backlog plan |
| App↔extension control channel | `sendProviderMessage` (`NETunnelProviderSession`) is the **sole app→tunnel control path** — it carries the typed, revisioned state and authoritatively drives the extension run loop. The earlier extension-side `CFNotificationCenter` observer never fired reliably on device and was **removed** (asserted absent by source-introspection tests). Darwin notifications survive only in the **tunnel→app** direction, as a health-changed nudge. | **Adopted** (provider-message is the only app→tunnel control; Darwin is tunnel→app health only) |

> Cross-cutting safety invariant referenced throughout: payment never bypasses the hash-validated, non-allowable **threat guardrail**. Decision precedence is **threat guardrail > local allowlist (allowed exceptions) > blocklist > default-allow.**
