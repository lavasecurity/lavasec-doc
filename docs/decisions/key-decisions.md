# Key Design Decisions

This is an ADR-style log of the design decisions that shape Lava Security. Each
entry records the **Decision**, its **Context**, the **Rationale**, and a
**Status**. The ADR set uses its own status vocabulary, because design decisions
need to express *reversal* and *replacement* that the project-wide
[status legend](../architecture/system-overview.md#status-legend)
(Implemented / In progress / Planned / Dropped) does not:

- **Adopted** — decided and shipped.
- **Reverted** — built, then pulled back out.
- **Superseded** — replaced by a later decision.
- **Proposed** — decided in principle but not yet shipped.

Where a feature is also marked against the project status legend, that mapping is
called out in the entry (for example, a Reverted decision leaves the reverted
path **(Dropped)**).

Decisions are grounded in commits and plan files; where code and a plan
disagree, code wins. For deeper background see
[DNS filtering & blocklists](../architecture/dns-filtering-and-blocklists.md)
and the [system overview](../architecture/system-overview.md).

---

## ADR-001 — On-device DNS filtering, no routine domain upload

**Decision.** DNS filtering happens locally inside an on-device
`NEPacketTunnelProvider`; Lava's servers never receive routine DNS queries,
browsing history, or per-domain telemetry. The backend is minimal and
privacy-preserving — it serves a blocklist catalog and (optionally) stores
ciphertext backups, nothing more.

**Context.** Lava is positioned as a privacy-first DNS filter. A naive design
would route queries through Lava's resolvers, turning the company into a
custodian of everyone's browsing. The packet tunnel parses each DNS packet,
extracts the queried domain, evaluates it against the compiled snapshot, and
forwards allowed queries upstream — all on the device.

**Rationale.** Keeping the client as the source of truth for filtering means a
server compromise cannot reveal what users browse. It is the core privacy
promise that the rest of the product is built to preserve.

**Status.** **Adopted.** (`plans/implemented/2026-05-16-supabase-r2-backend-plan.md`;
tunnel in `apps/ios/LavaSecTunnel/PacketTunnelProvider.swift`.)

---

## ADR-002 — Source-url-only blocklist distribution (GPL compliance)

**Decision.** Lava publishes only catalog **metadata** plus each upstream
`source_url` and accepted SHA-256 hashes. The app fetches every third-party list
directly from its upstream URL, verifies the hash, and parses it on-device. Lava
never hosts, mirrors, transforms, merges, or serves third-party blocklist bytes
from R2. `source_url_only` is the only allowed `redistribution_mode`. A CI
guardrail fails the build if code mirrors list bytes, exposes Lava artifact URLs,
enables GPL sources as production defaults, or writes blocklist bytes to R2.

**Context.** An earlier plan proposed mirroring raw upstream bytes in R2 with
license notices. Several curated sources (HaGeZi, OISD) are GPL-3.0, which carries
verbatim-copy and modified-source obligations — and Apple-distribution risk — if
Lava redistributes them.

**Rationale.** By acting as a local filtering engine / user-agent rather than a
GPL blocklist distributor, Lava sidesteps redistribution obligations entirely.
The hash allowlist and last-good cache preserve the safety properties (fail-closed
on unverified bytes, protected-domain filtering) the old mirror pipeline had.

**Status.** **Adopted**, **superseding** the raw-R2-mirror approach, which is
**(Dropped)**. (`plans/implemented/2026-05-25-source-url-blocklist-safety-and-copy-plan.md`;
superseded `plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`;
`redistribution_mode` literal at `server/backend/worker/src/index.ts:75`;
`scripts/check-gpl-blocklist-distribution.sh`. See
[blocklist catalog](../architecture/dns-filtering-and-blocklists.md#4-blocklist-catalog-default-sources)
and the IP risk register.)

---

## ADR-003 — GPL sources opt-in and off by default

**Decision.** The single shipped default config (`lavaRecommendedDefaults`)
enables only the two permissive **Block List Project Phishing** and **Block List
Project Scam** sources — both **Unlicense** — and Google plain DNS. No GPL source
(HaGeZi, OISD) is default-enabled; they ship as opt-in, source-url-only options.
AdGuard DNS Filter stays inactive pending separate legal review.

**Context.** Even under source-url-only, defaulting a GPL list on is a stronger
posture than offering it as a user choice, and counsel review of GPL defaults was
not complete at ship time. The originating plan
(`plans/implemented/2026-05-26-low-risk-blocklist-source-direction-plan.md`)
called for **Block List Basic** as the sole default; the shipped code diverged
to Phishing + Scam (commit `37b1fafd`, "apply feedback round fixes"). Block List
Basic still exists in the catalog (`BlocklistModels.swift:118`) but is not
default-enabled in any shipped config. Per this document's code-wins rule, the
shipped Phishing + Scam default is canonical.

**Rationale.** Ship a low-legal-risk default while still offering GPL lists for
users who opt in. Both default lists are permissively licensed (Unlicense) and
threat-focused; nothing GPL or risky is enabled without a deliberate user action.

**Status.** **Adopted.** (`apps/ios/Sources/LavaSecCore/OnboardingDefaults.swift`
— `lavaRecommendedDefaults`, used by
`apps/ios/LavaSecApp/OnboardingFlowView.swift`; licenses in
`apps/ios/Sources/LavaSecCore/BlocklistModels.swift`;
`plans/implemented/2026-05-26-low-risk-blocklist-source-direction-plan.md`.)

---

## ADR-004 — Encrypted-DNS transports: ship DoH/DoT/DoQ, default to plain DNS

**Decision.** Implement three encrypted upstream transports — **DoH** (HTTP/3
preferred, earning the observational `DoH3` annotation), **DoT** (bounded
per-endpoint connection pool, round-robin, max 4, with idle-staleness refresh),
and **DoQ** — all wired into the tunnel on a shared response type. Keep encrypted
transports opt-in (Plus) with Google plain DNS as the shipped default. Expose DoQ
only through a custom DNS stamp/URL; ship no built-in DoQ preset.

**Context.** The resolver stack evolved DoH → DoT → DoQ. Device QA found DoH
functional but Quad9 DoH unstable under backoff, so there was not enough evidence
to promote DoH to the default. DoQ lacked a stable connection-reuse story and
built-in providers.

**Rationale.** Offer encrypted transport as a power-user customization without
making an under-verified transport the default for everyone. `DoH3` is labeled
truthfully — HTTP/3 is preferred but never promised, so the annotation is earned
only by an observed h3 ALPN negotiation.

**Status.** **Adopted.** (Commits `a56f4728`/`39be21b9`/`2173c70e`/`571e4cd3`/`f176027d`;
`DoHTransport.swift`, `DoTTransport.swift`, `DoQTransport.swift`;
`plans/under_review/2026-05-17-dns-over-https-device-qa.md`. See
[encrypted transports](../architecture/dns-filtering-and-blocklists.md#2-encrypted-transports-doh-dot-doq-doh3).)

---

## ADR-005 — DoQ connection reuse: build, device-test, revert

**Decision.** Build iOS-26-gated DoQ (DNS-over-QUIC) connection reuse — a pooled
`NetworkConnection<QUIC>` per lane with idle-refresh and a circuit-breaker — to
amortize the QUIC handshake across queries. Keep only the per-query path (fresh
connection per query) and retain docs/guard-test rationale so the reuse path is
not re-attempted prematurely.

**Context.** Per-query DoQ pays one handshake per query. Reuse promised lower
latency. The reuse implementation was device-tested on iOS 26.5.

**Rationale.** Every reuse attempt failed: `openStream`/`receive` errored, the
fallback hit "Socket is not connected," and net behavior was **worse** than the
per-query baseline. The OS QUIC reuse API is not ready; re-attempting before it
matures wastes effort.

**Status.** **Reverted.** Per-query DoQ ships; reuse is **(Dropped)** with no
defined re-attempt trigger. (Commit `fbdb1511`;
`apps/ios/Sources/LavaSecCore/DoQTransport.swift`. See
[DoQ and the reuse status](../architecture/dns-filtering-and-blocklists.md#doq-and-the-reuse-status).)

---

## ADR-006 — Zero-knowledge account backup

**Decision.** An optional account (Sign in with Apple / Google) authenticates an
**encrypted-backup** sync only — protection works with no login. The settings
payload is encrypted on-device with AES-256-GCM under a random 32-byte payload
key, which is wrapped into independent PBKDF2-HMAC-SHA256 key slots (device-secret
keychain, assisted-recovery phrase, optional passkey). Servers store only
ciphertext and non-secret envelope metadata. Recovery splits into an 8-word,
locally-CSPRNG recovery phrase plus a server-held recovery share combined via
SHA-256 — neither alone can decrypt.

**Context.** Users wanted to carry blocklist/allowlist/DNS settings to a new
device, but the privacy promise forbids Lava reading those settings. The team also
chose **passwordless**: a backup-password design was dropped to avoid
reset/MFA/lockout burden (the `.password` slot / `BackupPasswordPolicy` survive in
core but are unwired, tests-only). Email sign-in was likewise deferred.

**Rationale.** Encrypting client-side under keys that never leave the device means
even a full server compromise yields only ciphertext. The recovery-phrase +
server-share split enables account-assisted new-device restore while preserving
zero-knowledge. Passkey recovery is offered too, but it is **server-gated, not
zero-knowledge**: a Cloudflare Worker releases a stored recovery secret after a
successful WebAuthn assertion.

**Status.** **Adopted.** Password slot and email sign-in are **(Dropped)**.
(`plans/implemented/2026-05-18-zero-knowledge-account-backup-plan.md`,
`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`,
`plans/implemented/2026-05-18-defer-email-sign-in-plan.md`;
`apps/ios/Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`. See
[accounts & backup](../architecture/accounts-and-backup.md).)

---

## ADR-007 — Fail-closed on-demand VPN, reconciled after launch

**Decision.** Add Connect-On-Demand (`NEOnDemandRuleConnect(.any)`) so an
OS-stopped tunnel auto-restarts. Keep **fail-closed** as the safe default: when
the tunnel comes up without a reusable snapshot it blocks all traffic rather than
passing it unfiltered, and the app reconciles the real snapshot after launch
(`reconcileTunnelSnapshotAfterLaunch()`). Enable on-demand only **after** the
tunnel is confirmed connected.

**Context.** iOS silently stopped the tunnel on network changes (stop reason 17,
`internalError`) with no auto-restart for long stretches. Adding on-demand fixed
the silent-VPN-off but introduced two regressions: (1) enabling on-demand at
profile install brought up a fail-closed tunnel mid-onboarding; (2) on restart
iOS brought the tunnel up cold/fail-closed before the app pushed real rules.

**Rationale.** Fail-closed is the correct safety default — a tunnel with no rules
must not leak unfiltered traffic. Gating on-demand on a confirmed connection and
reconciling the snapshot on launch closes the two fail-closed edges without
abandoning auto-restart.

**Status.** **Adopted**, with two corrective fixes. (Commit `5dc76c42` added
Connect-On-Demand; `fb5730ac` stopped enabling on-demand at profile install;
`5e2afdac` fixed on-demand restart fail-closed. On-demand rule and
`reconcileTunnelSnapshotAfterLaunch()` live in
`apps/ios/LavaSecApp/AppViewModel.swift`.)

---

## ADR-008 — Onboarding: neutralize an inherited VPN config by removing it

**Decision.** When the app finds an orphaned/inherited VPN configuration during
onboarding, neutralize it by **removing** it (`removeFromPreferences`, silent),
not by saving it. Gate `restoreProtectionIfNeeded` on onboarding completion, and
request notification authorization only at the onboarding notifications step.

**Context.** The "Add VPN Configurations" system prompt was firing at onboarding
step 1. The first neutralize fix used `setManagerOnDemand` → `saveToPreferences`,
which re-fired the very prompt it was meant to suppress on an orphaned profile.
Notification authorization was also being requested at the wrong step on fresh
installs.

**Rationale.** Saving an orphaned profile re-triggers the system prompt; removing
it is silent and idempotent. Gating restore on onboarding completion closes a
stale-status race; deferring the notification prompt aligns the system dialog with
the step that explains it.

**Status.** **Adopted**, **superseding** the earlier save-based mechanism.
(Commit `d8dfe4e9` / PR #40; `5e2afdac`.)

---

## ADR-009 — Tier gating by filter-rules budget, not list count

**Decision.** Gate tiers by **total compiled filter rules** — Free 500K / Plus 2M
— under a ~3.26M hard device guardrail derived from the ~50 MiB NE memory ceiling.
The device cap is a safety floor, never a paywall, and the tunnel ignores
`isPaid` (Plus never bypasses guardrails). Manual blocked domains count toward the
total. This replaced the old enabled-list-count cap (free 3 / paid 10).

**Context.** List count was a dishonest proxy — one list can hold 1K or 1M rules —
and manual domains went uncounted. The real constraint is the packet tunnel's
memory ceiling, made measurable by the mmap strategy (ADR-010).

**Rationale.** Rules ≈ honest memory cost. Gating on rules aligns the product
limit with the real resource and lets users pick any combination that fits. The
authoritative check runs at compile time on the deduped union (device-cap-first,
then tier); the selection-meter UI is advisory with a 1.10 soft margin.

**Status.** **Adopted in code, In progress as a shipped tier** — the gating
mechanism (`SubscriptionPolicy`, `FilterRuleBudget`, `FilterSnapshotMemoryBudget`)
is present; the plan sits under review. (Commit `07e60793`;
`plans/under_review/2026-06-13-filter-rules-budget-tier-revamp.md`. See
[filter-rules budgets](../architecture/dns-filtering-and-blocklists.md#5-filter-rules-budgets-the-ne-memory-ceiling-and-mmap-strategy)
and tiers & monetization.)

---

## ADR-010 — mmap the domain table; gate snapshot reload to avoid NE jetsam

**Decision.** Load the compact domain-string blob with
`Data(contentsOf:options:[.mappedIfSafe])` (zero-copy mmap) and size the memory
budget in dirty rule-table bytes only. Add a pre-decode no-op reuse gate so a
live snapshot reload does not rebuild when the header is unchanged.

**Context.** Refreshing the filter while connected tore the tunnel down: peak
memory roughly doubled and exceeded the ~50 MiB packet-tunnel jetsam ceiling,
surfacing as a silent VPN-off with no turn-off log.

**Rationale.** Mapped/clean file pages are excluded from the jetsam-counted
`phys_footprint`, so on-disk list size stops being a memory factor — only decoded
entry tables count. This lifted the on-device domain ceiling from ~1.3M to ~3.7M
rules and is the honesty basis for the filter-rules budget.

**Status.** **Adopted.** (Commits `055970a8`, `71a9a99b`. See
[mmap strategy](../architecture/dns-filtering-and-blocklists.md#mmap-strategy).)

---

## ADR-011 — Modular VPN-lifecycle refactor (cache-first turn-on)

**Decision.** Re-architect the VPN action path into explicit, observable modules —
an extracted `VPNLifecycleController` for turn-on/pause/resume/on-demand/snapshot
reload, extracted resolver transports, off-main filter preparation, and content-
hash caches — to make turn-on/pause/resume **cache-first** and bound latency. De-
scope `AppViewModel` and `PacketTunnelProvider`. Drive tunnel pause via the
`sendProviderMessage` command, not Darwin `CFNotification` observers.

**Context.** A stop-the-line Xcode heat regression (134% CPU, High energy, device
overheating, traced to a self-sustaining status-refresh loop) plus slow
turn-on/refresh eroded trust. A 40-agent review panel later found 5 of 11 "done"
items were scaffold-plus-tests with no production call sites, and **refuted**
popular heat suspects (debug-log appends, diagnostics rewrites, RootView poll
cascade) as orders of magnitude too small. Dead `CFNotificationCenter` tunnel IPC
was removed because Darwin observers do not self-fire in the NE extension until a
provider message pumps the run loop.

**Rationale.** VPN-path reliability and speed is the highest-priority surface;
making the path modular, cache-first, and memory-bounded is what restores trust.
The provider message is the reliable trigger inside the extension.

**Status.** **Adopted (shipped)**; some scaffolded modules still pending real
wiring per the panel re-review. (`plans/implemented/2026-06-12-modular-speed-up-plan.md`;
commits `26926904`, `cb89dd7c`, `ef6e3db0`, `b19c3ff1`, `cda75f46`.)

---

## ADR-012 — Plans as markdown lanes, synced one-way to Linear

**Decision.** Keep plans as tool-agnostic markdown files in a top-level `plans/`
tree with lane subfolders (`backlog`, `inflight`, `under_review`, `implemented`,
`dropped`) and YAML frontmatter. Sync **one-way and idempotently** to Linear
(reconcile by title; content-only on update so board edits are not clobbered).
Retire the earlier GitHub Projects sync.

**Context.** Plans had lived under `docs/plans/`. A status source of truth was
needed that is readable by Linear, Obsidian, and GitHub at once, without a sync
that overwrites human board triage.

**Rationale.** Frontmatter files travel with the repo and are diffable; one-way
idempotent sync gives Linear visibility without making the board authoritative
over the files. Lane folders double as the status legend.

**Status.** **Adopted**; GitHub Projects sync **Superseded**. (Commits `578e45fb`,
and prior `f6ee7e7b`/`21936304`; `scripts/sync-plans-to-linear.mjs`. See
plans README.)

---

## ADR-013 — Signal-style repo split with AGPL clients

**Decision.** Split the monorepo into individual repos, Signal-style:
`lavasec-ios` and `lavasec-android` public under **AGPL/GPLv3**, `lavasec-web` and
`lavasec-infra` private, and `lavasec-legal` as a non-git **encrypted vault**.
Switch the first-party open-source license recommendation from Apache-2.0 to
GPL-3.0/AGPL.

**Context.** Open client code builds trust, but private infra, secrets, PII, and
legal strategy must never leak. A permissive license would let a competitor fork
and close the client. Mullvad and ProtonVPN set the copyleft precedent.

**Rationale.** A clean per-surface boundary gives zero chance of leaking private
material while making the clients auditable. Copyleft prevents a closed fork of
the very client whose openness is the trust argument.

**Status.** **Proposed / In progress** — all four repos are built and committed
locally and paused before any push (no GitHub repos created, monorepo untouched).
(`plans/backlog/2026-06-14-repo-split-individual-repos-plan.md`, status In
Progress; license recommendation captured in commit `d8dfe4e9`;
`plans/backlog/2026-05-26-open-source-release-readiness-plan.md`.)

---

## ADR-014 — Allowed-Exceptions Guardrails: not built

**Decision.** Do not build a dedicated Allowed-Exceptions Guardrails surface or a
user-selectable guardrail-import system. Guardrails remain always-on,
backend-curated rules delivered via the catalog `guardrails[]` array; the
allowlist stays exception-led, and guardrails cannot be overridden by it.

**Context.** A plan (LAV-5) proposed a protection-guardrails explanation surface
plus a future high-confidence threat-guardrail source. On review the abstraction
was judged to add churn without proportional value for the v1 surface.

**Rationale.** Keeping guardrails backend-curated keeps the precedence model
simple (guardrail > allow > blocklist > default-allow) and avoids a symmetric
allowlist-list system users would have to manage.

**Status.** **Dropped / Cancelled.** (`plans/dropped/2026-05-16-allowed-exceptions-guardrails-plan.md`,
status Cancelled; commit `0f5b03ee`.)

---

## Related reading

- [System overview](../architecture/system-overview.md) — components, data flows, trust boundaries, and the project status legend.
- [DNS filtering & blocklists](../architecture/dns-filtering-and-blocklists.md) — pipeline, transports, budgets, source-url-only compliance.
- [Accounts & backup](../architecture/accounts-and-backup.md) — zero-knowledge envelope and recovery.
- Tiers & monetization — Free vs Plus boundary.
- IP risk register — blocklist license posture and source-url-only record.
- Roadmap & directions — plan lanes and status.
