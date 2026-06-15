# iOS Client Architecture

> Audience: iOS engineers working in `apps/ios/`.

Lava Security is a privacy-first iOS app that filters DNS locally on the device through an on-device NetworkExtension packet tunnel, blocking known risky and unwanted domains without routing your browsing through Lava's servers. This document covers how the iOS client is structured: the targets, how the app talks to its tunnel extension, the VPN lifecycle, the Guardian state model, the Live Activity and widget, the onboarding flow, and the app-side state owner (`AppViewModel`).

For the whole-system picture (the app, the catalog Worker, and Supabase), see [System Overview](./system-overview.md).

---

## 1. Targets & responsibilities

The client ships as three executable targets plus a shared core library. All three targets join the same **App Group** (`group.com.lavasec`) and link `LavaSecCore`.

| Target | Bundle id | Responsibility |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | The SwiftUI app. Owns the UI, holds the NetworkExtension entitlement, and controls the tunnel via `NETunnelProviderManager`. `AppViewModel` is the VPN lifecycle source of truth. |
| **Packet tunnel** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | The `NEPacketTunnelProvider` subclass `PacketTunnelProvider` (a.k.a. `LavaSecTunnel`). Parses DNS packets, extracts the queried domain, evaluates it against the memory-mapped compiled snapshot, and forwards allowed queries upstream. Bounded by the ~50 MiB per-process jetsam memory ceiling. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | A `WidgetBundle` whose only member is `LavaProtectionLiveActivityWidget` — the Live Activity / Dynamic Island presentation. |

Shared code lives in two places:

- **`LavaSecCore`** (`apps/ios/Sources/LavaSecCore/`) — the platform-independent core: the filtering engine, resolver transports, snapshot/budget math, protection stores, and the `GuardianMascotAnimation` core. Per `VPNLifecycleController.swift:3-6`, NetworkExtension types are intentionally kept out of this module so its lifecycle logic stays testable with fakes; the app target provides the `NetworkExtension`-backed conformances.
- **`apps/ios/Shared/`** — code compiled into more than one target (e.g. `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

The packet-tunnel internals (DNS parsing, the compiled snapshot, the encrypted resolver transports, and the filter-rules budget) are covered in depth in [System Overview](./system-overview.md). This document focuses on the app-side architecture and the boundary between the app and the extension.

---

## 2. App ↔ extension IPC

The app and the packet-tunnel extension are separate processes. They coordinate through three mechanisms, all anchored on the App Group.

### App Group container

`group.com.lavasec` is the shared container that lets the app, tunnel, and widget read and write the same `LavaSecCore` state and config. `LavaSecAppGroup` (`apps/ios/Shared/AppGroup.swift`) centralizes every shared key and filename so the processes can never drift on string constants, including:

- The compiled snapshot artifacts (`filter-snapshot.compact`, `filter-snapshot.json`), the serialized `app-configuration.json`, tunnel health (`tunnel-health.json`), diagnostics, and the network-activity log.
- Shared `UserDefaults` keys for the protection session and pause state. These alias the `LavaSecCore` stores directly (`AppGroup.swift:31-37`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — so the app, tunnel, and Live Activity intents share one key layout, one revision counter, and one dedup scheme.
- The catalog cache directory and the on-device debug log file.

The container URL is resolved via `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Command / provider message (the control path)

The app drives the tunnel with **`sendProviderMessage`**, not Darwin notifications. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:6767`) gets the active `NETunnelProviderSession` from the cached manager and calls `session.sendProviderMessage(...)`. The payload is encoded by `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) into a small JSON envelope carrying a message `kind` and an optional `operationID` (used for end-to-end latency tracing).

The recognized message kinds are constants on `LavaSecAppGroup`:

| Message constant | Effect in the tunnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Force-reload the compiled filter snapshot. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Re-read shared pause state only. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Reload config; only a *resolver-identity* change triggers a visible reconnect. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Diagnostics/log maintenance. |

On the tunnel side, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:611`) decodes the envelope and switches on `kind`. Notably, `reload-configuration` loads the new config so non-resolver fields (diagnostics toggles, paid status) take effect, but only resets the DNS runtime and reapplies tunnel network settings — a visible reconnect — when the resolver identity actually changed (`PacketTunnelProvider.swift:650-690`). A diagnostics-flag or paid-status change never drops the live connection.

The app's `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` helpers (`AppViewModel.swift:6614-6624`) are thin wrappers that send these messages.

### Why provider messages, not Darwin notifications

The command service (`LavaProtectionCommandService`, used by Live Activity intents) does post a pause Darwin signal. But **the packet-tunnel's `CFNotificationCenter` observer is not a reliable standalone trigger** — on device it stays dormant until a provider message wakes the extension's run loop. `AppViewModel.swift:4669-4675` documents this directly: the app "never relies on the snapshot Darwin observer either, always using `sendProviderMessage`," and a probe explicitly follows a command with `notifyTunnelProtectionPauseUpdated()` so the tunnel actually runs `refreshProtectionPauseStateOnly`. Treat the App Group + `sendProviderMessage` pair as the canonical control path; the Darwin signal is, at best, a hint that still needs a provider message to pump the run loop.

### Live Activity command service

`LavaProtectionCommandService.perform(_:)` (`apps/ios/Shared/LavaProtectionCommandService.swift`) is the entry point for Dynamic Island / Live Activity actions (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`). The `LiveActivityIntent`s in `LavaLiveActivityIntents.swift` run in the app process (which holds the NetworkExtension entitlement), so:

- **Pause / resume** flow through a cross-process file lock (`protection-command.lock`, `flock`) and the `LavaSecCore` `ProtectionPauseStore` / `ProtectionSessionStore`, which own revision minting and duplicate-command dedup (the `commandID` threads the caller's operation id so a re-delivered command can't mint a second revision). The outcome schedules a revision-guarded Live Activity update.
- **Reconnect** is handled directly (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): it calls `loadAllFromPreferences` and starts the first installed tunnel manager via `startVPNTunnel()` (because `loadAllFromPreferences` is already scoped to this app's NE configurations, that first manager is Lava's — unlike `VPNLifecycleController.matchingManagers()`, it does not do an explicit identity match). Connect-On-Demand is already enabled, so this just forces an immediate connect; the app's status reconcile then returns the Live Activity to `.on` once connected.

---

## 3. VPN lifecycle & control

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:805`) is the VPN lifecycle source of truth in the app. It orchestrates turn-on/turn-off, caches the active `NETunnelProviderManager`, and publishes status to SwiftUI.

### Manager selection and lifecycle math

The reusable, NetworkExtension-free lifecycle logic lives in `VPNLifecycleController<Repository>` (`apps/ios/Sources/LavaSecCore/VPNLifecycleController.swift`). The app provides `NETunnelProviderManager`-backed conformances of `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; the controller handles:

- **Selection & dedup** — `matchingManagers()` filters to Lava-owned managers via `LavaTunnelConfigurationIdentity.matches(...)`, sorts by `selectionPriority` (active first, then canonical display name), and `removeDuplicateManagers(keeping:)` converges on a single survivor.
- **Connect/stop waits** — `waitForConnect` / `waitForStop` poll the live connection status with a `startGraceInterval` tolerance, because right after `startVPNTunnel` the connection can briefly read a non-pending status before iOS transitions it to `.connecting`.

### Turn-on / turn-off

`enableProtection(...)` (`AppViewModel.swift:5419`) is **cache-first**: when a confirmed-reusable prepared artifact exists for the current configuration, the VPN can come up immediately from cache while an in-flight catalog sync keeps refreshing in the background, and `performCatalogSync` reconciles the running tunnel on completion. It only blocks on the sync when there is nothing valid to start from (e.g. the user just changed the enabled-list set, invalidating the cached artifact identity).

`disableProtection(...)` (`AppViewModel.swift:5627`) turns Connect-On-Demand off *before* stopping the tunnel so iOS does not immediately reconnect it. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:5860`) installs an `NEOnDemandRuleConnect` (interface match `.any`) and saves preferences — saving (not just setting) is required for iOS to honor the change.

### Status observation (and a heat caveat)

`AppViewModel` observes `.NEVPNStatusDidChange` (`AppViewModel.swift:1116-1135`) and publishes `vpnStatus`/`isVPNConfigurationInstalled`. Crucially, when a manager is already cached, it reads the cached manager's live connection rather than forcing a `loadAllFromPreferences` refresh: `loadAllFromPreferences` itself re-posts `NEVPNStatusDidChange`, and a forced refresh in the observer produced a self-sustaining storm (measured ~370 events/s, the source of a 134% CPU heat regression). Published properties only change on real transitions so idle ticks stop invalidating SwiftUI.

### Fail-closed on-demand reconcile

Connect-On-Demand can bring the tunnel up **cold** at launch (or after iOS tears it down on a network change) before the app has pushed a snapshot. A cold tunnel with no reusable persisted snapshot loads **fail-closed** — it blocks all traffic — and never recovers on its own. `AppViewModel` handles this in two launch paths, both gated on onboarding being complete (`hasCompletedOnboarding`, mirroring the `@AppStorage("hasSeenLavaOnboarding")` flag):

- **After onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:6674`) runs whenever protection is active at launch: it prepares the startup snapshot, persists shared state, and sends `reload-snapshot` so the tunnel reloads its real rules out of fail-closed. Fail-closed stays the safe default; this just supersedes it promptly. (Fixes filters shown red / traffic blocked after an app restart while Connect-On-Demand keeps the tunnel up.)
- **Mid-onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:6733`) runs *before* any network work when onboarding is not finished. iOS does not reliably remove a VPN profile on app delete, so a reinstall can inherit an orphaned, on-demand-enabled config that brings up a fail-closed cold tunnel before the user has chosen any blocklists. This path **removes** the config (`removeFromPreferences`) rather than saving a modification to it — `saveToPreferences` would re-show the "Add VPN Configurations" system prompt on a profile this install does not own, firing the dialog at app init before the onboarding sheet renders. It is a no-op on a clean install and when the inherited config is already inert.

---

## 4. Guardian / state model

There are two related state vocabularies: a connectivity *assessment* and a Guardian *mascot* state.

### Connectivity assessment

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`apps/ios/Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) maps a `TunnelHealthSnapshot` to a `ProtectionConnectivityAssessment` with one of **six severities** and **two actions**:

- Severities: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Primary actions: `turnOff` or `reconnect`.

This single assessment drives both the in-app Guard surface and (mapped further) the Dynamic Island state, so the two never disagree.

### Guardian mascot states

The Soft Shield Guardian mascot has exactly **seven** emotional states — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Each state declares its `allowedNextStates` so transitions are constrained (e.g. `grateful` only returns to `awake`; `GuardianMascotAnimation.swift:12-29`). Semantics:

- `retrying` = calm self-healing.
- `concerned` = gentle help-seeking.
- `grateful` = celebratory success (used on onboarding/settings surfaces, not the connectivity map).

`GuardianMascotAnimation` is the procedural animation core in `LavaSecCore`; `SoftShieldGuardian` (`apps/ios/Shared/SoftShieldGuardian.swift`) is the SwiftUI rendering and supports the customization skins selected by `GuardianShieldStyle` (display names Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, with the `displayName` mapping at lines 17-35). A few raw values diverge from their display names (e.g. `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, and `purpleObsidian` renders as "Amethyst"), so persist the raw value, not the label.

### How the two connect

The Live Activity's `LavaActivityAttributes.ProtectionState` (`apps/ios/Shared/LavaActivityAttributes.swift`) bridges the assessment to a mascot state via `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-106`). `AppViewModel` chooses the protection state for the Dynamic Island from the same `protectionConnectivityAssessment` (`AppViewModel.swift:3076-3092`): a `networkUnavailable` severity becomes `.networkUnavailable`, `recovering` becomes `.reconnecting`, a `reconnect` primary action becomes `.needsReconnect`, and otherwise `.on`.

> Note: `LavaTier` (the calm → **Floor** / celebratory → **Window** / technical → **Workshop** design-system depth enum) is **(Planned)** and not yet in code; it does not appear in the iOS client today.

---

## 5. Live Activity & widget

The widget target renders the Live Activity and Dynamic Island only. `LavaSecWidgetBundle` (`apps/ios/LavaSecWidget/LavaSecWidget.swift`) exposes a single `LavaProtectionLiveActivityWidget`, an `ActivityConfiguration(for: LavaActivityAttributes.self)` with:

- A lock-screen view, an expanded Dynamic Island center region, and compact/minimal presentations that render `SoftShieldGuardian` plus a status glyph. The compact/lock views recompute the *effective* protection state on a per-second `TimelineView` so a pause countdown stays live without a push.

`LavaActivityAttributes.ContentState` carries `protectionState`, a `resumeDate` (for pause countdowns), `pauseRequiresAuthentication`, and the chosen `shieldStyle`. Decoding is tolerant — a missing `shieldStyle` falls back to `.original` — so older Live Activity payloads keep working.

On the app side, `LavaLiveActivityController` (`apps/ios/LavaSecApp/LavaLiveActivityController.swift`) owns the live `Activity<LavaActivityAttributes>`: it observes ActivityKit authorization changes, only offers Live Activities on phone/pad idioms, and `reconcile(...)` starts/updates/ends the activity to match the requested protection state. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3029`) is the single funnel that recomputes desired state and calls the controller. Dynamic Island buttons dispatch `LiveActivityIntent`s, which call `LavaProtectionCommandService` as described in [§2](#2-app-extension-ipc).

---

## 6. Onboarding flow

Onboarding is presented by `LavaOnboardingView` (`apps/ios/LavaSecApp/OnboardingFlowView.swift`) and gated by the `@AppStorage("hasSeenLavaOnboarding")` flag read in `RootView` (`RootView.swift:1165`). The flow is a sequence of `OnboardingPage`s (`OnboardingFlowView.swift:560-575`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `settings` → `customize` → `done`. Inline picker sheets (`OnboardingPickerSheet`: `blocklist`, `dnsResolver`, `account`) let the user adjust the starting config without leaving the flow.

The shipped starting configuration comes from `OnboardingDefaults` (`apps/ios/Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` enables only the permissive recommended sources (Block List Project Phishing + Scam), selects **Google plain DNS** as the resolver (DoH is opt-in and not promoted to default), enables device-DNS fallback, and keeps local logging on — with `protectionEnabled: false`, so protection is only turned on when the user chooses it. `OnboardingDefaultsSummary` formats those choices for display ("Continue without account" is the account default).

Setting `hasSeenLavaOnboarding = true` at the end is what flips `hasCompletedOnboarding`, which in turn arms the launch reconcile path described in [§3](#3-vpn-lifecycle-control). Until then, the mid-onboarding neutralize path keeps any inherited fail-closed tunnel from blocking traffic.

---

## 7. App state: `AppViewModel`

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:805`) is the central app-side state owner. Beyond the VPN lifecycle, it publishes the surfaces the UI binds to, including:

- **Protection & tunnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, and user-facing `vpnMessage`/`vpnMessageIsError`.
- **Config & catalog** — the `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, and compiled rule counts (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnostics** — `DiagnosticsStore` and `NetworkActivityLog` (all local; see the privacy promise below).
- **Account & backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, and the **Lava Security Plus** offers/entitlement state.
- **Customization & presentation** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress`, and `usesLiveActivities`.

It delegates lifecycle serialization to a `protectionActionOrchestrator` (so a background restore won't interleave with a user turn-on), holds the cached `tunnelManager`, and drives all snapshot/config/pause changes to the extension via the provider-message helpers in [§2](#2-app-extension-ipc).

> **Privacy framing.** DNS filtering happens locally on this device. The diagnostics and network-activity surfaces `AppViewModel` publishes are stored locally only — Lava never receives your routine DNS queries, browsing history, or per-domain telemetry. Any optional account backup is **zero-knowledge** (encrypted on-device; Lava can only ever store ciphertext); passkey-based recovery is **server-gated**, not zero-knowledge. See [System Overview](./system-overview.md) for the server boundary.

---

## See also

- [System Overview](./system-overview.md) — the app, the catalog Worker, and Supabase, including the filtering engine, resolver transports (DoH / DoT / DoQ / DoH3), the filter-rules budget, and the source-url-only blocklist model.
