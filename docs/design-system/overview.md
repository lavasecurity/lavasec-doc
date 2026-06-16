# Design System

Audience: design and engineering.

This document is the reference for how Lava Security looks, behaves, and speaks. It covers the governing philosophy, the **LavaTier** depth model, the Soft Shield Guardian mascot, copy and naming conventions, onboarding UX principles, and localization. Where a behavior is shipped versus planned, it is tagged with the [status legend](../architecture/system-overview.md#status-legend) — **Implemented**, **(In progress)**, **(Planned)**, or **(Dropped)** — and grounded in code or a plan.

The product this design system dresses is a privacy-first iOS app: DNS filtering happens locally on your device through an on-device NetworkExtension packet tunnel; Lava never receives your routine DNS queries, browsing history, or per-domain telemetry, and any optional account backup is end-to-end encrypted so Lava can only ever store ciphertext. The design system's job is to make that promise feel calm and obvious without ever raising the user's pulse.

Related docs: [Product overview](../product/overview.md) · [System overview](../architecture/system-overview.md) · [DNS filtering and blocklists](../architecture/dns-filtering-and-blocklists.md) · i18n glossary · Localization file schema · Translation review checklist.

---

## 1. Philosophy: calm core, earned depth

The governing philosophy is **calm core, earned depth**:

- **Calm core** — the default experience just works and stays quiet for everyone, including the non-technical audience (parents, older adults). Nothing nags, alarms, or demands attention.
- **Earned depth** — richer celebratory and technical surfaces exist, but they are revealed only when the user seeks them. Delight and diagnostics are opt-in, never pushed.

Every design decision is measured against this: would a first-time, non-technical user feel reassured rather than warned? Would an enthusiast still be able to dig into transport details, Nerd Stats, and diagnostics without that complexity leaking into the default surfaces? The copy, the mascot's trouble expressions, and the tier model below all exist to keep those two answers "yes."

This philosophy is encoded both conceptually (in copy and mascot behavior) and now in code as the **`LavaTier`** enum described next.

---

## 2. The LavaTier model (Floor / Window / Workshop)

**Status: Implemented.** `LavaTier` ships in `apps/ios/LavaSecApp/LavaDesignSystem/LavaTokens.swift:198-216` as a `calm` / `celebratory` / `technical` enum, with an `accent` color, an `allowsDelightMotion` flag, and a `usesMonospacedMetadata` flag, plus a `lavaTier(_:)` environment modifier and a `lavaTierMetadata()` read-through modifier. It is a deliberately lightweight *vocabulary + defaults*, not a full re-theme — wired into representative surfaces only (e.g. the Nerd Stats / DNS-resolver containers as `.technical` and the Settings customization surface as `.celebratory` in `SettingsView.swift`), with Guard and the four tab roots left at the default `.calm`. (Landed in the design-system foundation work — `plans/inflight/2026-06-14-design-system-portability-foundation-plan.md`, Phase 1, PR #7.)

LavaTier maps the three emotional registers of the philosophy to three named surface tiers:

| Emotional register | Tier | Surfaces | Intent | Accent (iOS) |
|---|---|---|---|---|
| Calm | **Floor** | Guard panel + the four tab roots | Default, just-works surfaces seen by everyone | `safeGreen` |
| Celebratory | **Window** | Streaks, unlocks, delight-motion | Opt-in awareness and delight; never nags | `lavaOrange` |
| Technical | **Workshop** | DNS settings, Nerd Stats, diagnostics, monospaced metadata | Advanced, inspectable surfaces; invisible until sought | `ink` |

Design rules the tier encodes:

- **Delight-motion lives only in the Window tier.** The calm Floor stays still; celebratory motion is reserved for the opt-in awareness layer.
- **Monospaced metadata lives only in the Workshop tier.** Technical detail (transport annotations, diagnostics) is presented in its own register and does not bleed into Floor surfaces.
- The tier model exists primarily so the three depths stay legible in code and **portable to Android** without a full re-theme.

One open thread remains (per the inflight plan): `LavaTier.accent` ships pointing at the raw `LavaStyle` colors (`safeGreen`/`lavaOrange`/`ink`), and the planned repoint through a `LavaColorRole` was deferred — `LavaColorRole` does not yet exist. The button corner-radius disagreement is **resolved**: both styles now use `LavaSurface.controlCornerRadius = 12`.

### Token layer today (LavaStyle / LavaSurface)

**Status: Implemented.** The color and surface foundation the tier model builds on now lives in its own module at `apps/ios/LavaSecApp/LavaDesignSystem/LavaTokens.swift` (extracted out of `RootView.swift` in Phase 0a):

- `LavaStyle` centralizes roughly 18 adaptive light/dark semantic colors through one `adaptiveColor(light:dark:)` factory (including `safeGreen`, `lavaOrange`, `ink`, `cream`), plus the reserved **`dangerRed`** danger/error token and its `errorText` alias.
- `LavaSurface` defines surface roles with radius tokens — card `20`, compact `16`, selection `12`, plus the named `controlCornerRadius` `12`, `pillCornerRadius` `14`, and `iconBadgeCornerRadius` `10`.
- `LavaSpacing` provides the shared spacing scale (`xs`…`xl` plus screen insets), replacing the ~17 ad-hoc padding values that used to coexist.

The previously-missing pieces have all landed: spacing, named radii, the `dangerRed` token (raw `.red` no longer marks error text), and the neutral cross-platform token source — `apps/ios/design/lava-design-tokens.json` (v1.0.0), the versioned, hand-synced contract for the Android port. The JSON→Swift/Compose **codegen and CI drift-guard are intentionally deferred** until Android is a second consumer of the spec.

---

## 3. The Guardian mascot

The **Soft Shield Guardian** is Lava's mascot: a procedurally drawn shield with a face that animates to communicate protection status. The animation is built from SwiftUI `Shape`s with interpolated frames, a constrained `allowedNextStates` state machine, and privacy-redaction face masking. Core: `apps/ios/Sources/LavaSecCore/GuardianMascotAnimation.swift`; SwiftUI rendering: `apps/ios/Shared/SoftShieldGuardian.swift`.

### 3.1 The seven states

**Status: Implemented.** The Guardian has exactly **seven** emotional states (do not assert "six"):

| State | Register | Meaning |
|---|---|---|
| `sleeping` | calm | Protection off / tunnel disconnected |
| `waking` | calm | Tunnel connecting or reasserting |
| `awake` | calm | Protection on and healthy |
| `paused` | calm | Protection temporarily paused by the user |
| `retrying` | calm | **Self-healing, unworried.** The relaxed counterpart to `concerned`: relaxed lids, flat mouth, no concern tilt — motion is carried by the status badge, not the face. |
| `concerned` | calm | **Gentle help-seeking.** Inner eye corners are raised to read as worry, never a stern glare. |
| `grateful` | celebratory | **Success.** Happy closed eyes, big smile (`mouthCurve 1.18`), reached via a custom awake-to-grateful interpolation. |

The two trouble states deserve emphasis because they embody the philosophy: rather than alarm a non-technical user, four problem severities collapse into just two reassuring faces. `retrying` says "I've got this," `concerned` says "I might need you." Definitions: `GuardianMascotAnimation.swift:3-30,249-282`; rendering: `SoftShieldGuardian.swift:127-147`.

### 3.2 Connectivity → expression mapping

**Status: Implemented.** The Guard panel derives the mascot's expression from VPN status plus the `ProtectionConnectivitySeverity` (six severities, defined in `apps/ios/Sources/LavaSecCore/ProtectionConnectivityPolicy.swift:3-10`). The mapping now lives in `apps/ios/LavaSecApp/GuardView.swift` (moved out of `RootView.swift` in Phase 0b):

| Condition | Severity | Expression |
|---|---|---|
| Protection temporarily paused | — | `paused` |
| VPN connecting / reasserting | — | `waking` |
| VPN disconnected | — | `sleeping` |
| VPN connected | `healthy` | `awake` |
| VPN connected | `usingDeviceDNSFallback` | `awake` |
| VPN connected | `recovering` | `retrying` |
| VPN connected | `networkUnavailable` | `retrying` |
| VPN connected | `dnsSlow` | `concerned` |
| VPN connected | `needsReconnect` | `concerned` |

Note the deliberate collapse: six severities map onto two trouble expressions. `recovering` + `networkUnavailable` → `retrying`; `dnsSlow` + `needsReconnect` → `concerned`.

### 3.3 `grateful` is not a connectivity state

**Status: Implemented.** `grateful` is the only celebratory expression and is **never** reached through the connectivity map. It is triggered exclusively at success moments in onboarding and settings — see the ready-mascot transition in `apps/ios/LavaSecApp/OnboardingFlowView.swift:601-616` and the awake-to-grateful interpolation in `GuardianMascotAnimation.swift:271-282,353-392`. When documenting the Guard connectivity panel, do not list `grateful` among its outcomes.

### 3.4 Skins

**Status: Implemented.** The Guardian ships in **seven** swappable shield / app-icon skins, each paired with an alternate app icon and a Dynamic Island glyph accent color (`apps/ios/Shared/LavaActivityAttributes.swift:5-53`; `SoftShieldGuardian.swift:98-115,442-636`). The raw enum case is on the left; the user-facing `displayName` is in parentheses:

`original` (Original), `fireOpal` (Fire Opal), `purpleObsidian` (Amethyst), `obsidian` (Obsidian), `cherryQuartz` (Cherry Quartz), `emerald` (Emerald), `kiwiCreme` (Kiwi Crème).

Note that several raw values differ from the display name (e.g. `fireOpal` has raw value `emberObsidian`, `cherryQuartz` has raw value `strawberryObsidian`, and `purpleObsidian` displays as **Amethyst**). Kiwi Crème carries a playful mascot voice — an example of earned-depth personality that appears only for users who choose it (`docs/mockups/kiwi-creme-lava-guard.html:108-109`).

### 3.5 Known presentation debt

**Status: Implemented (fixed).** This presentation boundary used to be inverted — the platform-agnostic core shipped English copy and Apple SF Symbol ids. It has since been lifted out (Phase 4, PR #15):

- `ProtectionConnectivityPolicy.assessment` now returns **severity + primary action only** (`ProtectionConnectivityPolicy.swift:33-48`); the only string it exposes is `severity.diagnosticLabel`, a stable, locale-independent id for logs.
- The user-facing connectivity titles/subtitles moved app-side to `ProtectionConnectivityPresentation` (`apps/ios/LavaSecApp/ProtectionConnectivityPresentation.swift:16-28`), the correct home for localized copy.
- `LavaActivityAttributes.ProtectionState.statusSymbolName` is **gone from `Shared`/`LavaSecCore`**; the Live Activity glyph (`checkmark`, `pause.fill`, `arrow.triangle.2.circlepath`, `exclamationmark.triangle.fill`, `wifi.slash`) is now resolved at render time in the widget (`apps/ios/LavaSecWidget/LavaSecWidget.swift:89-101`).

The **broad copy lift** of the remaining user-facing strings that still originate in the core (`DNSResolverPreset.displayName`, `SourceSyncState.userFacingStatus`, `GuardianShieldStyle.displayName`, etc.) is the one tracked follow-up — see `plans/inflight/2026-06-14-design-system-portability-foundation-plan.md`, Phase 4.

---

## 4. Copy and naming conventions

### 4.1 Tone

**Status: Implemented.** Copy is **plain, calm, and practical**, and deliberately avoids fear-driven language — the audience includes non-technical users, parents, and older adults. The protection panel is reassuring rather than triumphant:

- Healthy title **"Protected"**, subtitle **"Filtering happens locally on this phone"** (`ProtectionConnectivityPresentation.swift:16-28`).
- Trouble titles stay plain and unalarming: **"Network Lost"**, **"Reconnect Needed"**, **"DNS Slow"**, **"Reconnecting"** (`ProtectionConnectivityPresentation.swift:16-23`).

(As of Phase 4, this copy lives app-side in `ProtectionConnectivityPresentation`, not in the platform-agnostic core — see §3.5.)

Writing rules (from the shared conventions): present tense; second person ("you") for user-facing copy; third person for components ("`AppViewModel` owns…"). Never state an aspiration as shipped — tag non-shipped features **(Planned)** / **(In progress)** / **(Dropped)**. When describing any server interaction, state what is **not** sent (routine DNS queries, browsing history, plaintext), and distinguish zero-knowledge storage from server-gated recovery.

### 4.2 Transport naming

**Status: Implemented.** The encrypted upstream DNS transports have strict labels (`apps/ios/Sources/LavaSecCore/DoHTransport.swift:16-21`; `apps/ios/Sources/LavaSecCore/DNSResolverPreset.swift:270-288`; `apps/ios/LavaSecApp/SettingsView.swift:1839`):

- **`DoH3`** — DNS-over-HTTP/3, **written with no slash** (never `DoH/3`). It is an annotation, e.g. `Quad9 (DoH3)`, **earned only by an observed `h3` ALPN negotiation**. HTTP/3 is preferred but never promised, so the label is purely observational; otherwise the transport shows **`DoH`**.
- **`DoH`** — DNS-over-HTTPS.
- **`DoT`** — DNS-over-TLS.
- **`DoQ`** — DNS-over-QUIC.
- **`IP`** — plain DNS.

The settings explainer copy: "DNS over HTTPS (DoH), TLS (DoT), and QUIC (DoQ) encrypt allowed lookups to the resolver."

**Rule for writers and engineers:** always annotate the *effective* transport truthfully — preferred, never promised. Write `DoH3` with no slash. For transport behavior and the per-query-versus-pooled distinctions, see [DNS filtering and blocklists](../architecture/dns-filtering-and-blocklists.md) (DoT pools connections; DoQ opens a fresh connection per query — connection reuse was built, device-failed on iOS 26.5, and is **(Dropped)**).

### 4.3 Onboarding copy discipline

**Status: Implemented.** Onboarding copy was tightened to avoid over-promising, because Lava is DNS/blocklist protection — not full malicious-URL coverage, and not a traffic-routing VPN (`plans/implemented/2026-05-25-multi-page-onboarding-flow-plan.md:14-70`):

- "blocks **known risky domains from selected blocklists**" (not "blocks all threats")
- "**Install Lava's Local VPN**" (frames the VPN as local)
- "traffic **not sent through Lava servers**"
- "**Continue without account**" (free protection never requires sign-in)

### 4.4 Do-not-translate / canonical terms

Use the canonical term and component names verbatim. Brand and protocol tokens (`Lava`, `DoH`, `DoH3`, `DoT`, `DoQ`, `Guardian`, skin names, etc.) are do-not-translate; see the i18n glossary and translation review checklist.

### 4.5 In-panel buttons

**Status: Implemented (mockup direction).** Embedded panel/list-card actions are lower-emphasis and squarer than the main control: shorter, less pill-shaped, no pre-button divider, no inner border, neutral press highlight. The adopted directions are "Soft fill, no border" (variant B) inside panels and "Compact primary" (S1) for sheet submits. The main Guard turn-on control stays a distinct special capsule so the protection toggle keeps its primacy and never competes with content (`docs/in-panel-button-options.html:705-712,758-760,841-849,873-875`). This avoids a border-within-a-border inside the green Guard panel.

---

## 5. Onboarding UX principles

**Status: Implemented.** A multi-page onboarding flow ships in `apps/ios/LavaSecApp/OnboardingFlowView.swift`. The `OnboardingPage` enum has **eight** cases (`OnboardingFlowView.swift:560-575`), matching the eight steps numbered in `plans/implemented/2026-05-25-multi-page-onboarding-flow-plan.md:14-98`:

1. **`lava` — The Internet Is Lava** — the metaphor and the problem.
2. **`guardIntro` — Lava Stands Guard Here** — the Guardian reveal.
3. **`features` — Feature Handoff** — what Lava does (and what it does not promise).
4. **`vpn` — Install Lava's Local VPN** — the on-device VPN configuration step.
5. **`notifications` — Enable Notifications** — framed as help for protection issues only (reconnect, network unavailable, Device DNS fallback); "Not Now" never blocks protection.
6. **`settings` — Decide How Lava Works** — shows the safe defaults; "Use Default" is the primary action.
7. **`customize` — Customize Lava** — *conditional*; only shown if the user chooses to customize. Lets the user choose blocklist intensity, DNS resolver, Device DNS fallback, local-logging controls, and optional account sign-in.
8. **`done` — Setup Complete** — calm close; does not claim protection is on automatically, and sends the user to Guard where the protection state stays authoritative.

Principles the flow embodies:

- **Promise honestly.** Copy is scoped to what Lava actually does (see §4.3): selected-blocklist filtering, local VPN, no traffic routed through Lava servers.
- **No forced account.** "Continue without account" is first-class — free protection must not gate behind sign-in.
- **Celebrate at the end, calmly.** Success moments use the Guardian's `grateful` expression (`OnboardingFlowView.swift:601-616`) — the one place celebratory depth surfaces by default, and even there it is gentle.
- **Ship the safe defaults.** The shipped default config is `AppConfiguration.lavaRecommendedDefaults` (`apps/ios/Sources/LavaSecCore/OnboardingDefaults.swift:4-18`): it enables **two** blocklists — the Phishing and Scam lists (`DefaultCatalog.blockListProjectPhishing` + `blockListProjectScam`) — with **Google Public DNS (plain)** as the resolver preset (`DNSResolverPreset.google`) and **Device DNS fallback on**. So the calm core works the instant onboarding completes. (`OnboardingDefaultsSummary` is a separate display-string struct, not the config itself; "Block List Basic" is a real but separate blocklist that is **not** enabled by default.)

The shipped onboarding strings live in SwiftUI; some storyboard mockups (`docs/mockups/lava-onboarding-flow.html`) may differ from live copy, so treat live SwiftUI as authoritative.

---

## 6. Localization and i18n

**Status: (In progress).** The runtime hook is shipped; full multi-language coverage is not release-ready.

### What ships today

- A localization runtime hook: `LavaStrings` / `lavaLocalized` wrap `NSLocalizedString` with an English-source fallback (and a format-argument variant) — `apps/ios/LavaSecApp/LavaStrings.swift:1-23`.

### What is in progress

Full i18n is **(In progress)** with foundations started but not release-ready (`plans/backlog/2026-05-22-i18n-localization-plan.md:14-37`):

- English stays the **source locale**; copy migrates into Xcode string catalogs (`.xcstrings`).
- Target locales: **ja**, **zh-Hant** (Taiwan-friendly), **zh-Hans**, **de**, **fr** — iOS first.
- Governance is defined in `docs/i18n/`: a glossary of do-not-translate terms and tone, a per-string lifecycle (`draft` → `translated` → `reviewed` → `locked`) with `sensitive` and `maxLength` flags, and a translation review checklist.

### Hard rule

**Non-English `sensitive` strings must not ship while in `draft`.** Privacy, legal, VPN, DNS, account, backup, and safety-claim copy is flagged `sensitive` and must be human-reviewed against the English source before release; machine translations stay `translated` until reviewed. This protects the privacy promise across languages.

### Known boundary debt

**Status: Implemented (fixed).** The presentation boundary was inverted — the platform-agnostic `LavaSecCore` / `Shared` layer shipped English copy (`ProtectionConnectivityPolicy` titles/subtitles) and Apple SF Symbol ids (`LavaActivityAttributes.statusSymbolName`). Phase 4 of the design-system plan lifted these into the app-side presentation layer (`ProtectionConnectivityPresentation`), which is also the correct home for localized copy (see §3.5). The remaining user-facing strings still in the core (`DNSResolverPreset.displayName` et al.) are the tracked copy-lift follow-up.

---

## Quick reference

| Topic | Status | Source of truth |
|---|---|---|
| Philosophy (calm core, earned depth) | Implemented (concept + `LavaTier` enum) | `plans/inflight/2026-06-14-design-system-portability-foundation-plan.md` |
| LavaTier (Floor / Window / Workshop) | **Implemented** | `apps/ios/LavaSecApp/LavaDesignSystem/LavaTokens.swift:198-216` |
| Token layer (`LavaStyle` / `LavaSurface` / `LavaSpacing`) | Implemented | `apps/ios/LavaSecApp/LavaDesignSystem/LavaTokens.swift` |
| Neutral cross-platform token spec | Implemented (codegen deferred) | `apps/ios/design/lava-design-tokens.json` |
| Guardian: 7 states | Implemented | `apps/ios/Sources/LavaSecCore/GuardianMascotAnimation.swift` |
| Connectivity → expression mapping | Implemented | `apps/ios/LavaSecApp/GuardView.swift` |
| Guardian skins (7) | Implemented | `apps/ios/Shared/LavaActivityAttributes.swift:5-53` |
| `DoH3` no-slash naming | Implemented | `apps/ios/Sources/LavaSecCore/DNSResolverPreset.swift:270-288` |
| Tone / calm copy | Implemented | `apps/ios/LavaSecApp/ProtectionConnectivityPresentation.swift:16-28` |
| Onboarding flow (8 pages, 1 conditional) | Implemented | `apps/ios/LavaSecApp/OnboardingFlowView.swift:560-575` |
| Recommended defaults (Phishing + Scam, Google plain DNS) | Implemented | `apps/ios/Sources/LavaSecCore/OnboardingDefaults.swift:4-18` |
| Localization runtime hook | Implemented | `apps/ios/LavaSecApp/LavaStrings.swift` |
| Full i18n (ja/zh-Hant/zh-Hans/de/fr) | **(In progress)** | `plans/backlog/2026-05-22-i18n-localization-plan.md` |
| Presentation boundary fix (copy + glyphs out of core) | **Implemented** (broad copy-lift tail remains) | inflight plan, phase 4 |
