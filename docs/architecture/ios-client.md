---
last_reviewed: 2026-07-18
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "c8f2100"}
---

# iOS Client Architecture

> Audience: iOS engineers working in `lavasec-ios`.

Lava Security is a privacy-first iOS app that filters DNS locally on the device through an on-device NetworkExtension packet tunnel, blocking known risky and unwanted domains without routing your browsing through Lava's servers. This document covers how the iOS client is structured: the targets, the app-to-tunnel boundary, the VPN lifecycle, the Guardian state model, the Live Activity and widget, the onboarding flow, and the app-side state owner (`AppViewModel`).

For the whole-system picture (the app, the catalog Worker, and Supabase), see [System Overview](./system-overview.md).

---

## 1. Targets & responsibilities

The client ships as **four** executable targets that consume a layered Swift package (`LavaSecPackage`). All four join the same **App Group** (`group.com.lavasec`), but they do **not** link the same code: each production target links only the narrow package products it is approved for (`project.yml:258-269` app, `325-332` tunnel, `381-384` widget, `436-439` intents).

| Target | Bundle id | Responsibility |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | The SwiftUI app. Owns the UI, holds the NetworkExtension entitlement, and controls the tunnel via `NETunnelProviderManager`. `AppViewModel` is the VPN lifecycle source of truth. |
| **Packet tunnel** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | The `NEPacketTunnelProvider` subclass `PacketTunnelProvider` (a.k.a. `LavaSecTunnel`). Parses DNS packets, extracts the queried domain, evaluates it against the memory-mapped compiled snapshot, and forwards allowed queries upstream. Bounded by the ~50 MiB per-process jetsam memory ceiling. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | A `WidgetBundle` whose only member is `LavaProtectionLiveActivityWidget` — the Live Activity / Dynamic Island presentation. |
| **App Intents extension** (`LavaSecIntents`) | `com.lavasec.app.intents` | Hosts the `SetFocusFilterIntent` that switches the active filter from an iOS **Focus**, cross-process and with no `AppViewModel` — even while the app is closed (see [§2](#2-app-extension-ipc)). |

Shared code lives in two places:

- **The Swift package** (`Sources/`) — the platform-independent core, split across six layers: **`LavaSecKit`** (foundational value types, policies, protection stores, VPN-lifecycle math, DNS resolver presets), **`LavaSecNetworking`**, **`LavaSecDNS`**, **`LavaSecFilterPipeline`** (the compiled-snapshot filter engine), **`LavaSecPresentation`** (the `GuardianMascotAnimation` core and other UI-independent presentation), and **`LavaSecAppServices`**. **`LavaSecCore`** (`Sources/LavaSecCore/`) is now only the compatibility **façade** — a single `LavaSecCoreExports.swift` that `@_exported import`s all six layers; the executable test suite links it, production targets do not. Production targets link only their approved narrow products: the app links all six layers, the **tunnel** links only `LavaSecKit`/`LavaSecNetworking`/`LavaSecDNS`/`LavaSecFilterPipeline` (**not** Presentation, AppServices, or the façade), the widget links `LavaSecKit`/`LavaSecPresentation`, and the intents extension links `LavaSecKit`/`LavaSecFilterPipeline`. Per `VPNLifecycleController.swift:3-6` (in `LavaSecKit`), NetworkExtension types are intentionally kept out of the package so its lifecycle logic stays testable with fakes; the app target provides the `NetworkExtension`-backed conformances.
- **`Shared/`** — code compiled into more than one target (e.g. `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

The packet-tunnel internals (DNS parsing, the compiled snapshot, the encrypted resolver transports, and the filter-rules budget) are covered in depth in [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md). This document focuses on the app-side architecture and the boundary between the app and the extension.

---

## 2. App ↔ extension IPC

The app and the packet-tunnel extension are separate processes. They coordinate through three mechanisms, all anchored on the App Group.

### App Group container

`group.com.lavasec` is the shared container that lets the app, tunnel, and widget read and write the same `LavaSecCore` state and config. `LavaSecAppGroup` (`Shared/AppGroup.swift`) centralizes every shared key and filename so the processes can never drift on string constants, including:

- The compiled snapshot artifacts (`filter-snapshot.compact`, `filter-snapshot.json`), the serialized `app-configuration.json`, tunnel health (`tunnel-health.json`), diagnostics, and the network-activity log.
- Shared `UserDefaults` keys for the protection session and pause state. These alias the `LavaSecKit` stores directly (`AppGroup.swift:103-106`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — so the app, tunnel, and Live Activity intents share one key layout, one revision counter, and one dedup scheme.
- The catalog cache directory and the on-device debug log file.
- **Reboot / first-unlock durability.** Because Connect-On-Demand can launch the tunnel *before the device's first unlock after a reboot*, control-plane shared-state files (configuration, filter library, compiled artifacts) are written `NSFileProtectionNone` so they stay readable in that window (`INV-PERSIST-2`, e.g. `Sources/LavaSecFilterPipeline/FilterArtifactStore.swift:233`), while privacy stores stay Data-Protection Class C. Reads that still come back locked are classified **unreadable ≠ absent**, so no launch reseed or migration is ever persisted over a merely-locked store — this closed a reboot-before-first-unlock incident that had wiped the filter library (`INV-PERSIST-1`; classifier `Sources/LavaSecKit/SharedStateFileReader.swift`, tunnel bootstrap in `LavaSecTunnel/PacketTunnelProvider.swift`).

The container URL is resolved via `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Command / provider message (the control path)

The app drives the tunnel with **`sendProviderMessage`** for all commands. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:10003`) gets the active `NETunnelProviderSession` from the cached manager and calls `session.sendProviderMessage(...)`. The payload is encoded by `LavaSecProviderMessageCodec` (`AppGroup.swift:170-194`) into a small JSON envelope carrying a message `kind` and an optional `operationID` (used for end-to-end latency tracing).

The recognized message kinds are constants on `LavaSecAppGroup`:

| Message constant | Effect in the tunnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Force-reload the compiled filter snapshot. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Re-read shared pause state only. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Reload config; only a *resolver-identity* change triggers a visible reconnect. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Diagnostics/log maintenance. |

On the tunnel side, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:1154`) decodes the envelope and switches on `kind`. Notably, `reload-configuration` loads the new config so non-resolver fields (diagnostics toggles, paid status) take effect, but only resets the DNS runtime and reapplies tunnel network settings — a visible reconnect — when the resolver identity actually changed (`PacketTunnelProvider.swift:1259-1266`). A diagnostics-flag or paid-status change never drops the live connection.

The app's `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` helpers (`AppViewModel.swift:9828`/`9836`) are thin wrappers that send these messages.

### Why provider messages for app→tunnel control

**`sendProviderMessage` is the only app→tunnel control path — there is no app→tunnel Darwin signal.** An earlier design posted a `CFNotificationCenter` Darwin signal on pause and observed it inside the extension, but it never fired reliably in the NetworkExtension process and was removed. The command service no longer posts `CFNotificationCenterPostNotification`, and the tunnel no longer adds a `CFNotificationCenterAddObserver` — both are asserted absent by source-introspection tests (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` for the command-service post; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` for the tunnel observer) to guard against reintroduction. (The `import Darwin` lines that remain in the command service and tunnel are for `flock`/socket primitives, not notifications.)

A Darwin path *does* still ship in the other direction. The tunnel posts a health-changed nudge to the app: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecKit/TunnelHealthSignal.swift`) posts `CFNotificationCenterPostNotification` on the channel `com.lavasec.protection.tunnel-health-changed` (the channel name lives in `TunnelHealthSignal.swift`, not `AppGroup.swift`), and the app observes it via `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), wired up in `AppViewModel` to call `handleTunnelHealthNudge()`. This tunnel→app health nudge is asserted *present* by `LavaLiveActivitySourceTests.swift:1059-1075`.

For app→tunnel control, pause is delivered by writing the shared `ProtectionPauseStore` and following it with the `reload-protection-pause` provider message so the tunnel runs `refreshProtectionPauseStateOnly`. `AppViewModel.swift:6342-6343` documents the rule directly: the app "never relies on the snapshot Darwin observer either, always using `sendProviderMessage`." Treat the App Group (shared state) + `sendProviderMessage` (the wake/control signal) pair as the app→tunnel control path.

### Live Activity command service

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) is the entry point for Dynamic Island / Live Activity actions (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes` / `pause-configured` (the Live Activity's single Pause button, whose length is the user-configured value), `resume`, `reconnect`). The `LiveActivityIntent`s in `LavaLiveActivityIntents.swift` run in the app process (which holds the NetworkExtension entitlement), so:

- **Pause / resume** flow through a cross-process file lock (`protection-command.lock`, `flock`) and the `LavaSecCore` `ProtectionPauseStore` / `ProtectionSessionStore`, which own revision minting and duplicate-command dedup (the `commandID` threads the caller's operation id so a re-delivered command can't mint a second revision). The outcome schedules a revision-guarded Live Activity update.
- **Reconnect** is handled directly (`performReconnect`, `LavaProtectionCommandService.swift:141`): it calls `loadAllFromPreferences` and starts the first installed tunnel manager via `startVPNTunnel()` (because `loadAllFromPreferences` is already scoped to this app's NE configurations, that first manager is Lava's — unlike `VPNLifecycleController.matchingManagers()`, it does not do an explicit identity match). Connect-On-Demand is already enabled, so this just forces an immediate connect; the app's status reconcile then returns the Live Activity to `.on` once connected.

### Focus auto-switch (closed-app filter switching)

iOS **Focus** modes can switch the active filter automatically — including while the app is **closed** — via a dedicated App Intents extension (`LavaSecIntents`) that hosts a `SetFocusFilterIntent`. When a Focus activates, the extension's `perform()` runs the switch cross-process with no `AppViewModel`: it shares the `LavaSecCore` commit engine and the cross-process CAS writer (`SharedFilterStatePersistence`), writing configuration + library and flipping the artifact pointer. Available to all tiers.

**Enforcement latency.** How quickly the change takes effect depends on the app's state:

- **App terminated or foreground** — prompt: iOS launches the extension promptly, and a foregrounded app adopts the committed on-disk switch directly.
- **App suspended** — iOS may **defer the extension launch by several minutes** (a platform behavior, not fixable in-app); the filter-switch notification surfaces the change when it lands.
- **Tunnel pickup while the app isn't running** — the packet tunnel adopts a committed switch by polling the on-disk configuration generation roughly **every ~60 s**, so enforcement can lag up to ~60 s after the commit (an app→tunnel Darwin signal is contraindicated in the NetworkExtension process — see [§2 above](#2-app-extension-ipc)).

**Deferred switches and background drain.** The headless Focus / Shortcuts path only commits a *warm* switch (one whose compiled artifact is already on disk). When no reusable warm artifact exists at switch time, the engine records a durable pending-switch marker that self-applies with no further user action, drained by whichever runs first: the background catalog-refresh `BGTask` (`BackgroundPendingSwitchDrain`, which re-stamps catalog freshness on a verified-unchanged catalog precisely so the warm reuse can commit) or the next foreground reconcile — the tunnel then adopts the committed generation bump on its poll. The Shortcuts *Switch Filter* result dialog reflects this ("… will apply automatically") and, like the switch notifications, is rendered in the app's chosen language rather than the system language (`LavaSecApp/SwitchFilterShortcut.swift:133-152`).

**Cross-process filter / pause notifications.** `LavaNotificationCategory` (`Sources/LavaSecKit/LavaEventNotifications.swift:19-42`) defines four opt-out toggles shared across the app, intents extension, and tunnel via app-group defaults, so every process reads the same on/off switch: `filter-changed` ("Switched to <Filter>", posted only when the app is closed/backgrounded, for a Focus auto-switch *or* a Shortcuts "Switch Filter" run), `filter-could-not-apply`, `protection-resumed` ("Pause ended — protection is back on", posted by the **tunnel's** expiry timer when a temporary pause lapses with the app closed — the only process guaranteed alive at that moment), and `connectivity` (which gates the reconnect / DNS notifications from [§4](#4-guardian-state-model)). All copy is localized across the 10 supported locales via the package bundle, so it resolves even inside the extension and tunnel processes.

---

## 3. VPN lifecycle & control

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:719`) is the VPN lifecycle source of truth in the app. It orchestrates turn-on/turn-off, caches the active `NETunnelProviderManager`, and publishes status to SwiftUI.

### Manager selection and lifecycle math

The reusable, NetworkExtension-free lifecycle logic lives in `VPNLifecycleController<Repository>` (`Sources/LavaSecKit/VPNLifecycleController.swift`). The app provides `NETunnelProviderManager`-backed conformances of `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; the controller handles:

- **Selection & dedup** — `matchingManagers()` filters to Lava-owned managers via `LavaTunnelConfigurationIdentity.matches(...)`, sorts by `selectionPriority` (active first, then canonical display name), and `removeDuplicateManagers(keeping:)` converges on a single survivor.
- **Connect/stop waits** — `waitForConnect` / `waitForStop` poll the live connection status with a `startGraceInterval` tolerance, because right after `startVPNTunnel` the connection can briefly read a non-pending status before iOS transitions it to `.connecting`.

### Turn-on / turn-off

`enableProtection(...)` (`AppViewModel.swift:7061`) is **cache-first**: when a confirmed-reusable prepared artifact exists for the current configuration, the VPN comes up immediately from cache while an in-flight catalog sync refreshes in the background, and `performCatalogSync` reconciles the running tunnel on completion. It only blocks on the sync when there is nothing valid to start from (e.g. the user just changed the enabled-list set, invalidating the cached artifact identity).

`disableProtection(...)` (`AppViewModel.swift:7273`) turns Connect-On-Demand off *before* stopping the tunnel so iOS does not immediately reconnect it. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:7571`) installs an `NEOnDemandRuleConnect` (interface match `.any`) and saves preferences — saving (not just setting) is required for iOS to honor the change.

### Status observation (and a heat caveat)

`AppViewModel` observes `.NEVPNStatusDidChange` (`AppViewModel.swift:1452-1474`) and publishes `vpnStatus`/`isVPNConfigurationInstalled`. Crucially, when a manager is already cached, it reads the cached manager's live connection rather than forcing a `loadAllFromPreferences` refresh: `loadAllFromPreferences` itself re-posts `NEVPNStatusDidChange`, and a forced refresh in the observer produced a self-sustaining storm — the in-source comment (`AppViewModel.swift:1466-1467`) records the measured ~370 events/s and the 134% CPU heat regression it caused. Published properties only change on real transitions so idle ticks stop invalidating SwiftUI.

### Fail-closed on-demand reconcile

Connect-On-Demand can bring the tunnel up **cold** at launch (or after iOS tears it down on a network change) before the app has pushed a snapshot. A cold tunnel with no reusable persisted snapshot loads **fail-closed** — it blocks all traffic — and never recovers on its own. `AppViewModel` handles this in two launch paths, both gated on onboarding being complete (`hasCompletedOnboarding`, mirroring the `@AppStorage("hasSeenLavaOnboarding")` flag):

- **After onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:9901`) runs whenever protection is active at launch: it prepares the startup snapshot, persists shared state, and sends `reload-snapshot` so the tunnel reloads its real rules out of fail-closed. Fail-closed stays the safe default; this just supersedes it promptly. (Fixes filters shown red / traffic blocked after an app restart while Connect-On-Demand keeps the tunnel up.)
- **Mid-onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:9969`) runs *before* any network work when onboarding is not finished. iOS does not reliably remove a VPN profile on app delete, so a reinstall can inherit an orphaned, on-demand-enabled config that brings up a fail-closed cold tunnel before the user has chosen any blocklists. This path **removes** the config (`removeFromPreferences`) rather than saving a modification to it — `saveToPreferences` would re-show the "Add VPN Configurations" system prompt on a profile this install does not own, firing the dialog at app init before the onboarding sheet renders. It is a no-op on a clean install and when the inherited config is already inert.

---

## 4. Guardian / state model

There are two related state vocabularies: a connectivity *assessment* and a Guardian *mascot* state.

### Connectivity assessment

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecKit/ProtectionConnectivityPolicy.swift`) maps a `TunnelHealthSnapshot` to a `ProtectionConnectivityAssessment` with one of **seven severities** and **two actions**:

- Severities: `healthy`, `recovering`, `usingDeviceDNSFallback`, `usingEncryptedFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`. (`usingEncryptedFallback` is the honest-but-covered state: the primary resolver's health probe is failing on a transition-induced staleness while the *encrypted* fallback actively carries DNS, so protection is up and no user-visible self-reconnect is warranted; the held wedge marker keeps re-probing the primary so it resumes in place once it un-masks.)
- Primary actions: `turnOff` or `reconnect`.

This single assessment drives both the in-app Guard surface and (mapped further) the Dynamic Island state, so the two never disagree.

**Honesty floor (v1.0).** A current, uncovered DNS smoke-probe failure can never read as `.healthy` — the assessment surfaces `.recovering` until a probe actually succeeds, so fallback-carried traffic over a wedged primary is no longer painted "Protected." Reconnect logic keys on `consecutiveDNSSmokeProbeFailureCount` and `lastPrimaryUpstreamSuccessAt` (primary-only) rather than the generic upstream counters, and a resolver that stays reachable but keeps **rejecting** the known-good probe (hijack/captive/stale) is escalated to restart-worthy via a resolver-identity-scoped `consecutiveRejectedSmokeResponseCount` (LAV-87), even when the generic streak keeps getting reset on churny roaming networks.

### Connectivity notifications

`ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecKit/ProtectionConnectivityNotificationPolicy.swift`) turns the assessment into at-most-one outstanding local notification, throttled (600s) and deduped. v1.0 adds:

- A distinct **`dnsSlow`** kind ("Lava DNS is slow") — slow DNS used to reuse the `reconnectNeeded` kind, so a real outage couldn't supersede it.
- **Escalation/superseding** — a strictly more-urgent problem (only `reconnectNeeded` outranks the rest) can supersede a standing lower-ranked banner, bypassing both the "problem already outstanding" guard and the throttle, so a wedge after a Device-DNS fallback surfaces the actionable "Reconnect" prompt instead of leaving a reassuring banner up.
- A **persistence migration** (`ProtectionConnectivityNotificationStore`, schema v2, wired via `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) demotes a legacy outstanding `reconnect-needed` marker to `dnsSlow` so escalation works across upgrade.

### Device-DNS capture retry

When the active configuration depends on the device resolver (as primary or as fallback), a network handoff/wake can leave the tunnel holding an empty system-resolver capture — a silent wedge. `DeviceDNSFallbackPolicy` drives a **bounded retry** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1s, `deviceDNSCaptureMaxRetryAttempts` 5): the tunnel re-reads system resolvers every second for up to five attempts until the capture is non-empty, then adopts it in place — auto-recovering without a tunnel restart (events `device-dns-capture-retry` / `-exhausted`). It is a no-op for pure DoH/DoT/DoQ configs (`currentConfigurationDependsOnDeviceDNS()`).

### Guardian mascot states

The Soft Shield Guardian mascot has exactly **seven** emotional states — `GuardianMascotState` (`Sources/LavaSecKit/GuardianMascotState.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Each state declares its `allowedNextStates` so transitions are constrained (e.g. `grateful` only returns to `awake`; `GuardianMascotState.swift:12-29`). Semantics:

- `retrying` = calm self-healing.
- `concerned` = gentle help-seeking.
- `grateful` = celebratory success (used on onboarding/settings surfaces, not the connectivity map).

`GuardianMascotAnimation` is the procedural animation core in `LavaSecPresentation`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) is the SwiftUI rendering and supports the customization skins selected by `GuardianShieldStyle` (display names Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, with the `displayName` mapping at lines 18-35). A few raw values diverge from their display names (e.g. `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, and `purpleObsidian` renders as "Amethyst"), so persist the raw value, not the label.

### How the two connect

The Live Activity's `LavaActivityAttributes.ProtectionState` (`Shared/LavaActivityAttributes.swift:113-116`) now has just three cases — `on`, `paused`, `restarting` — each mapped to a mascot state via `guardianState`: `on → awake`, `paused → paused`, `restarting → retrying` (`LavaActivityAttributes.swift:118-127`). `AppViewModel.liveActivityProtectionState(restartInFlightDeadline:)` (`AppViewModel.swift:4511-4541`) computes the Dynamic Island state and **deliberately never surfaces transient connectivity** (reconnecting / needs-reconnect / no-network): those states originate in the always-running tunnel and change while the app is suspended, so the app can never push a timely correction — a stale alarm or stale all-clear would be the result. Because Lava is fail-closed, a reconnect wobble blocks traffic rather than exposing it, which makes a steady "On" honest; the user's recovery affordance is the always-available Restart action, and the in-app Guard tab still renders live connectivity detail. A user-initiated Restart in flight holds the surface on `.restarting` (via a shared deadline) so the restart's own status churn can't end or clobber the activity.

> Note: `LavaTier` (the calm → **Floor** / celebratory → **Window** / technical → **Workshop** design-system depth enum) ships in the design-system layer (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), wired into representative surfaces — see [the design system](../design-system/overview.md). It governs design-system depth, not the protection/tunnel client path described here.

---

## 5. Live Activity & widget

The widget target renders the Live Activity and Dynamic Island only. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) exposes a single `LavaProtectionLiveActivityWidget`, an `ActivityConfiguration(for: LavaActivityAttributes.self)` with:

- A lock-screen view, an expanded Dynamic Island center region, and compact/minimal presentations that render `SoftShieldGuardian` plus a status glyph. The compact/lock views recompute the *effective* protection state on a per-second `TimelineView` so a pause countdown stays live without a push.

`LavaActivityAttributes.ContentState` carries `protectionState`, a `resumeDate` (for pause countdowns), `pauseRequiresAuthentication`, and the chosen `shieldStyle`. Decoding is tolerant — a missing `shieldStyle` falls back to `.original` — so older Live Activity payloads keep working.

On the app side, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) owns the live `Activity<LavaActivityAttributes>`: it observes ActivityKit authorization changes, only offers Live Activities on phone/pad idioms, and `reconcile(...)` starts/updates/ends the activity to match the requested protection state. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:4425`) is the single funnel that recomputes desired state and calls the controller. Dynamic Island buttons dispatch `LiveActivityIntent`s, which call `LavaProtectionCommandService` as described in [§2](#2-app-extension-ipc).

---

## 6. Onboarding flow

Onboarding is presented by `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) and gated by the `@AppStorage("hasSeenLavaOnboarding")` flag declared in `RootView` (`RootView.swift:32`). The flow is a sequence of `OnboardingPage`s (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

The shipped starting configuration comes from `OnboardingDefaults` (`Sources/LavaSecKit/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` enables the permissive recommended sources (Block List Basic + StevenBlack Unified Hosts), selects **Device DNS** as the resolver — `DNSResolverPreset.device` (id `device-dns`), the network's own DNS; encrypted presets like Google DoH are opt-in and not promoted to default — enables device-DNS fallback, and keeps local logging on — with `protectionEnabled: false`, so protection is only turned on when the user chooses it. `OnboardingDefaultsSummary` formats those choices for display ("Continue without account" is the account default).

Setting `hasSeenLavaOnboarding = true` at the end is what flips `hasCompletedOnboarding`, which in turn arms the launch reconcile path described in [§3](#3-vpn-lifecycle-control). Until then, the mid-onboarding neutralize path stops any inherited fail-closed tunnel from blocking traffic.

---

## 7. App state: `AppViewModel`

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:719`) is the central app-side state owner. Beyond the VPN lifecycle, it publishes the surfaces the UI binds to, including:

- **Protection & tunnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, and user-facing `vpnMessage`/`vpnMessageIsError`.
- **Config & catalog** — the `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, and compiled rule counts (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnostics** — `DiagnosticsStore` and `NetworkActivityLog` (all local; see the privacy promise below).
- **Account & backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, and the **Lava Security Plus** offers/entitlement state.
- **Customization & presentation** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress`, and `usesLiveActivities`.

It delegates lifecycle serialization to a `protectionActionOrchestrator` (so a background restore won't interleave with a user turn-on), holds the cached `tunnelManager`, and drives all snapshot/config/pause changes to the extension via the provider-message helpers in [§2](#2-app-extension-ipc).

Two app-only affordances also live on this side. The app coalesces concurrent biometric prompts through `BiometricAuthenticationCoalescer` (`Sources/LavaSecKit/BiometricAuthenticationCoalescer.swift`) so a simultaneous Guard long-press + settings-toggle tap can't stack two Face ID prompts — a UI anti-fan-out gate, **not** a cryptographic boundary (`INV-LOCK-1`; the app lock is anti-snooping only, `LavaSecApp/SecurityController.swift:475`). And a QA-gated review moment drives Apple's native `requestReview` via `ReviewPromptPolicy` (`Sources/LavaSecKit/ReviewPromptPolicy.swift`), wired through `RootView` (`LavaSecApp/RootView.swift:492`); Lava never routes users to the App Store based on how they might rate.

> **Privacy framing.** DNS filtering happens locally on this device. The diagnostics and network-activity surfaces `AppViewModel` publishes are stored locally only — Lava never receives your routine DNS queries, browsing history, or per-domain telemetry. Any optional account backup is **zero-knowledge** (encrypted on-device; Lava can only ever store ciphertext), including passkey-based recovery — its key is PRF-derived on-device with no server-held secret. See [System Overview](./system-overview.md) for the server boundary.

---

## Related docs

- [System Overview](./system-overview.md) — the whole system on one screen: the app, the catalog Worker, and Supabase, plus the trust boundaries and the status legend used throughout.
- [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) — the packet-tunnel internals referenced here only at the control boundary: the compiled filtering engine, the encrypted resolver transports (DoH / DoH3 / DoT / DoQ), the filter-rules budget, the blocklist catalog, and the source-url-only redistribution model.
- [Accounts & Zero-Knowledge Backup](./accounts-and-backup.md) — the sign-in providers and the zero-knowledge backup envelope that `AppViewModel` orchestrates (including the zero-knowledge, PRF-derived passkey recovery slot).
- [Backend & Data](./backend-and-data.md) — the `lavasec-api` catalog Worker, Cloudflare R2, and the Supabase schema/RLS that sit on the other side of the app↔server boundary.
- [Design System](../design-system/overview.md) — the `LavaTier` depth model, the Soft Shield Guardian's seven states and shield skins, and the copy/localization conventions the client renders.
- [Third-Party Notices](../legal/third-party-notices.md) and [GPL source-url-only compliance decision](../legal/gpl-source-url-only-compliance-decision.md) — the distribution constraints behind the catalog/filter pipeline the client consumes.
