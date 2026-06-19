---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Design System

> **Audience:** design + engineering working on the Lava Security iOS app.
> **Authority:** Where this doc and a plan disagree, **code wins** — divergences are called out inline. Status reflects the code-confirmed reality, not plan aspiration. Status legend: **Implemented** (shipped and confirmed in code), **In progress** (partially landed), **Planned** (designed, not built), **Dropped** (rejected or reverted).

This doc covers the design philosophy, the LavaTier depth vocabulary, the Guardian mascot, copy & naming conventions, onboarding UX, and internationalization. For the architectural plumbing behind these surfaces (targets, VPN lifecycle, the Guardian/protection state model wiring), see [the iOS client](../architecture/ios-client.md); for the product framing, see [the product overview](../product/overview.md).

---

## 1. Philosophy: calm core, earned depth

Lava's audience is non-technical everyday users — parents, older adults — and the design follows from that. The everyday surface "just works" calmly for everyone; additional detail, delight, and control are revealed (**earned**) only as the user goes looking for them. Nothing nags, nothing alarms, and the technical machinery stays invisible until sought.

This **"calm core, earned depth"** model resolves into three product depths:

- **Calm** — the default, just-works protection that everyone sees first.
- **Celebratory** — opt-in awareness and delight (streaks, unlocks, success moments). Never nags.
- **Technical** — DNS, diagnostics, and stats. Invisible until the user seeks them out.

Two cross-cutting palette/tone rules support the calm posture:

- **red = danger only.** Red is reserved exclusively for danger and error; the calm palette is green/orange. This keeps red trustworthy as a genuine alarm signal. Danger-red is tokenized as `LavaStyle.dangerRed`, with `LavaStyle.errorText` aliased to it (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) and consumed by error text in the views. The protection tint is resolved through the semantic `ProtectionTintRole` role table (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) rather than raw `.green`/`.orange`. A few raw `.red` call sites genuinely persist (e.g. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrating those to `LavaStyle.dangerRed` is the remaining cleanup.
- **No fear-heavy security language.** Copy is plain, calm, and practical. See [§4 Copy & naming](#4-copy-naming).

### The tokenized layer that exists today **(Implemented)**

The design system is a real, tokenized SwiftUI layer, alongside the `LavaTier` depth vocabulary (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — the adaptive color source of truth: ~18 semantic colors (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), each produced by a single `adaptiveColor(light:dark:)` factory so light/dark are defined together. Danger-red is tokenized here as `dangerRed`/`errorText` (lines 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — card/panel/selection surface roles and corner radii: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — the spacing scale: `xs`/`sm`/`md`/`lg`/`xl` plus `screenHorizontal`/`screenTop`/`screenBottom`.

The remaining residual gap is the handful of raw `.red` call sites not yet migrated to `LavaStyle.dangerRed` (see §1).

---

## 2. LavaTier — Floor / Window / Workshop **(Implemented)**

`LavaTier` is the lightweight depth vocabulary that encodes "calm core, earned depth" directly in the token layer. It is a vocabulary plus a few token defaults — not a full re-theme — and ships as an enum at lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, wired into representative surfaces rather than retrofitting every view.

| Tier | Depth | Meaning |
|---|---|---|
| **Floor** | calm | Just-works protection for everyone — the default surface. |
| **Window** | celebratory | Opt-in awareness & delight: streaks, unlocks, success moments. Never nags. |
| **Workshop** | technical | DNS, Nerd Stats, diagnostics. Invisible until sought. |

`LavaTier` is a `calm`/`celebratory`/`technical` enum carrying token defaults:

- an **accent color** (`accent`),
- `allowsDelightMotion` — true only for celebratory / Window,
- `usesMonospacedMetadata` — true only for technical / Workshop,

exposed via an `EnvironmentKey` plus a `.lavaTier(_:)` modifier and a `.lavaTierMetadata()` modifier (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). It is wired into representative surfaces — e.g. `.lavaTier(.technical)` and `.lavaTier(.celebratory)` in lavasec-ios: LavaSecApp/SettingsView.swift — rather than every view. The deliberate scoping keeps the three product depths legible in code and portable to a future Android consumer without re-deriving intent.

> **Caveat (accent tokenization Planned, Phase 3):** `LavaColorRole` is not yet created, so `LavaTier.accent` still resolves to raw `LavaStyle` colors (LavaTokens.swift:~230). Treat the accent-color tokenization as an open loop, not a finished surface.

---

## 3. The Soft Shield Guardian mascot **(Implemented)**

The **Soft Shield Guardian** is Lava's mascot — a rounded shield with a simple, morphing face — that visually expresses protection state on the Guard tab, the Live Activity, the Dynamic Island, and onboarding. It is the most-visible carrier of the calm tone.

The state graph is platform-agnostic, living in `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); the SwiftUI renderer is lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 The 7 expression states

The mascot has **exactly 7** expression states, governed by an allowed-transition state graph (`GuardianMascotState.allowedNextStates`, locked by lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Graph constraints worth knowing: `sleeping`'s only exit is `waking`, and `grateful` only returns to `awake`. The `awake ↔ grateful` transitions have bespoke interpolation frames — this is the system's one bit of **delight motion** (Window-tier).

> **`retrying` vs `concerned` — the most important tone distinction.** Both signal "not perfectly healthy," but they read very differently and must not be conflated:
> - **`retrying`** is the *unworried, self-healing* face: relaxed (~0.80) lids, level eyes, a flat mouth, and **no concern tilt**. The motion is carried by the **status badge, not the face** — transient self-recovery should never alarm. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** is *gentle, help-seeking* worry: raised inner brows (`concernAmount` 1, `mouthCurve` -0.22) reading as "I could use a hand," **never a stern glare**. Genuine problems should invite help, not scold. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Connectivity → expression mapping (6 → 4)

Protection health is assessed in `LavaSecCore` as **6 connectivity severities** + 2 actions (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Severities:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Actions:** `turnOff`, `reconnect`

The Guard tab collapses those 6 severities onto **4 faces** (`guardianState` in lavasec-ios: LavaSecApp/GuardView.swift:122). The face is intentionally a *coarser, calmer* signal than the status badge — the badge carries the detail, the face stays simple:

| Condition | Mascot state |
|---|---|
| Temporarily paused | `paused` |
| connected + `healthy` / `usingDeviceDNSFallback` | `awake` |
| connected + `recovering` / `networkUnavailable` | `retrying` |
| connected + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| otherwise | `sleeping` |

> **Tint reconciliation.** The protection tint color granularity stays reconciled with this expression split so tint and face never disagree. The expression mapping and the semantic `ProtectionTintRole` role table both ship today (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, consumed by `AppViewModel.protectionTintRole`). Only the `LavaColorRole` color-role tokenization that would map roles to fully tokenized colors remains **Planned** (Phase 3 of the DS plan).

### 3.3 Skins (looks) **(Implemented)**

The mascot ships in **7 selectable shield "looks"**, persisted as `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Each has its own colorway and a paired Dynamic Island glyph color:

`original`, `fireOpal` (raw value `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (raw value `strawberryObsidian`), `emerald`, `kiwiCreme`.

The two legacy raw values are intentional — do not "fix" them; they would break persisted user selections.

### 3.4 Privacy redaction **(Implemented)**

The Guardian honors privacy redaction: the expression can be masked when the surface is privacy-redacted while the **shield itself stays visible** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). Protection presence is reassuring; the specific emotional state is the part that hides.

### 3.5 Not in this tree **(Planned)**

A Guard easter-egg mini-game (tap = gratitude animation; 10s long-press = a catch-bad-domains game) is **P3 / backlog**. It would add extra mascot expressions (`confused` / `dazed` / `inZone` / `powerSurge`) seen on a feature branch — these are **not** in the app target. Per the canonical facts, the mascot has exactly **7** states; do not document the game expressions as shipped.

---

## 4. Copy & naming

### 4.1 Voice & tone

Plain, calm, practical. Avoid fear-heavy security language. Be honest about scope: Lava is **local DNS/blocklist filtering**, not a guarantee that every malicious domain or URL is blocked, and protection is **never** described as auto-on the moment onboarding completes — the **Guard tab is authoritative** for whether protection is currently active.

### 4.2 DNS transport labels

Transport annotations follow a strict compact convention (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 and lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, locked by `DNSResolverPresetTests.swift`):

| Transport | Label | Notes |
|---|---|---|
| DNS-over-HTTPS | `DoH` | URLSession-based. |
| DNS-over-HTTP/3 | **`DoH3` (no slash)** | e.g. "Quad9 (DoH3)". Annotated **only when an h3 negotiation is actually observed** — preferred, never promised; otherwise falls back to `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| plain DNS | `IP` | |
| device resolver | *(no annotation)* | |

The single most-broken rule here is the **no-slash `DoH3`** — write `DoH3`, never `DoH/3` or `DoH3 (h3)`, and never apply it speculatively. These transport labels are emitted from `DoHTransport`/`DNSResolverPreset`; keep them verbatim in every locale, but note they are *not* glossary Do-Not-Translate entries (see §4.3).

### 4.3 Do-Not-Translate terms

Brand and protocol terms are pinned verbatim in **all** locales. The localization glossary's Do-Not-Translate list is the authority, and it pins: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

Of the DNS transports, only **DoH** is a glossary Do-Not-Translate entry; `DoH3`, `DoT`, and `DoQ` are transport labels (see §4.2), not glossary terms. They are still written verbatim, but do not cite the glossary as their source.

### 4.4 Safety framing

Payment never bypasses the server-signed non-allowable **threat guardrail**. State the precedence consistently: **threat guardrail > local allowlist (allowed exceptions) > blocklist > default-allow.**

---

## 5. Onboarding UX **(Implemented)**

First-run onboarding is a multi-page flow — **6 pages** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implemented in lavasec-ios: LavaSecApp/OnboardingFlowView.swift. It reuses the `SoftShieldGuardian` for the guardian-emergence moment.

The 6 pages:

1. **The Internet Is Lava** (`lava`) — danger framed as metaphor; primary action "Meet Lava".
2. **Lava Stands Guard Here** (`guardIntro`) — the guardian-emergence moment.
3. **Feature Handoff** (`features`) — what Lava does; "Set Up Protection".
4. **Install Lava's Local VPN** (`vpn`) — explains why iOS says "VPN" for a DNS-only packet tunnel.
5. **Enable Notifications** (`notifications`) — the opt-in prompt, presented at the right step rather than up front.
6. **Setup Complete** (`done`) — "Open Guard", with optional additional setup.

Design decisions baked into the flow:

- **"Use Default" is the primary action, "Customize" the secondary.** A friction-free default path for non-technical users; control is earned, not forced.
- **Danger framed as metaphor, not fear** ("The Internet Is Lava"), consistent with the calm tone.
- **The flow explains why iOS says "VPN"** — a packet tunnel is the only way to filter DNS system-wide; it is not traffic routing.
- **Never claims protection is auto-on at completion** — Guard stays authoritative.
- Chevron-only Back, on a shared step-page layout.

The first-run defaults the flow installs: **Device DNS** resolver (`DNSResolverPreset.device`), **Device DNS fallback ON**, logging on (counts + history + activity), and "Continue without account."

> **Default-blocklist divergence (code wins).** The onboarding plan copy lists HaGeZi Multi Light as the default blocklist, but the shipped code default is **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, defined in lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). The real tier gate is the **filter-rules budget (Free 500K / Plus 2M)**, *not* a list count. Tracked internally. For the tier model and the recommended-default config, see [the feature catalog](../product/features.md).

---

## 6. Internationalization **(In progress)**

Lava localizes into **6 locales**: **en** (source) + **ja, zh-Hant, zh-Hans, de, fr**, via Xcode string catalogs.

- **The localization seam is `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, backed by `LavaStrings.localized` → `NSLocalizedString` with an English fallback; lavasec-ios: LavaSecApp/LavaStrings.swift). **All component copy** must go through it — no bare string literals in views.
- **zh-Hant** uses Taiwan-friendly wording on the first pass.
- App Store metadata exists for all 6 locales.
- Priority order for translation: ja, zh-Hant, zh-Hans, de, fr.

Foundations are in place but full human translation review is still pending before release, so the overall status is **In progress**.

> **Presentation-boundary cleanup (Planned, Phase 4).** `LavaSecCore`/`Shared` should carry *semantics* (severity/action enums, icon roles), not English strings. The severity tint presentation has already been lifted into the semantic `ProtectionTintRole`. The remaining residual is that resolver `displayName`s are still hardcoded English strings ("Google", "Cloudflare", "Quad9", "Device DNS") in lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. Phase 4 lifts these into a per-OS app-side presentation map — correct for both i18n and Android portability.

The i18n mechanics (the localization glossary, the localization-file schema, and the translation-review checklist) live in the internal i18n docs, not this public set.

---

## 7. Reference artifacts

HTML design references (non-shipping, internal): the onboarding flow storyboard, a kiwi-creme guardian look study, and in-panel primary-button visual options.

The DS foundation has landed: the `LavaDesignSystem/` group, the `LavaSpacing`/radius/`dangerRed` tokens, `LavaTier` depth semantics, and the `LavaIcon` role layer all ship (lavasec-ios: LavaSecApp/LavaDesignSystem/). What remains **Planned** in the portability/foundation plan is the `LavaColorRole` accent tokenization (Phase 3), the per-OS presentation map for core-side English strings (Phase 4), a neutral cross-platform token JSON, and the broader Android-portability seams.
