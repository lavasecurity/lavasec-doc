---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Architektur des iOS-Clients

> Zielgruppe: iOS-Entwickler, die an `lavasec-ios` arbeiten.

Lava Security ist eine iOS-App nach dem Privacy-first-Prinzip. Sie filtert DNS direkt auf dem Gerät über einen NetworkExtension-Paket-Tunnel und blockiert bekannte riskante und unerwünschte Domains, ohne dein Surfen über die Server von Lava zu leiten. Dieses Dokument beschreibt, wie der iOS-Client aufgebaut ist: die Targets, die Grenze zwischen App und Tunnel, den VPN-Lebenszyklus, das Guardian-Zustandsmodell, die Live Activity und das Widget, den Onboarding-Ablauf und den app-seitigen Zustandsverwalter (`AppViewModel`).

Das Gesamtbild des Systems (die App, der Catalog-Worker und Supabase) findest du in der [Systemübersicht](./system-overview.md).

---

## 1. Targets und Zuständigkeiten {#1-targets-responsibilities}

Der Client wird als drei ausführbare Targets plus eine gemeinsam genutzte Core-Bibliothek ausgeliefert. Alle drei Targets gehören zur selben **App Group** (`group.com.lavasec`) und binden `LavaSecCore` ein.

| Target | Bundle id | Zuständigkeit |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | Die SwiftUI-App. Verwaltet die UI, hält das NetworkExtension-Entitlement und steuert den Tunnel über `NETunnelProviderManager`. `AppViewModel` ist die maßgebliche Quelle für den VPN-Lebenszyklus. |
| **Paket-Tunnel** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | Die `NEPacketTunnelProvider`-Unterklasse `PacketTunnelProvider` (auch `LavaSecTunnel` genannt). Sie analysiert DNS-Pakete, extrahiert die abgefragte Domain, prüft sie gegen den memory-mapped kompilierten Snapshot und leitet erlaubte Abfragen an den Upstream weiter. Begrenzt durch die jetsam-Speicherobergrenze von ~50 MiB pro Prozess. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Ein `WidgetBundle`, dessen einziges Mitglied `LavaProtectionLiveActivityWidget` ist — die Darstellung der Live Activity bzw. Dynamic Island. |

Gemeinsam genutzter Code liegt an zwei Stellen:

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — der plattformunabhängige Kern: die Filter-Engine, die Resolver-Transporte, die Snapshot-/Budget-Berechnungen, die Protection-Stores und der `GuardianMascotAnimation`-Kern. Laut `VPNLifecycleController.swift:3-6` werden NetworkExtension-Typen bewusst aus diesem Modul herausgehalten, damit seine Lebenszyklus-Logik mit Fakes testbar bleibt; das App-Target liefert die `NetworkExtension`-gestützten Konformitäten.
- **`Shared/`** — Code, der in mehr als ein Target kompiliert wird (z. B. `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

Die Interna des Paket-Tunnels (DNS-Parsing, der kompilierte Snapshot, die verschlüsselten Resolver-Transporte und das Filter-Regel-Budget) werden ausführlich in [DNS-Filterung und Blocklisten](./dns-filtering-and-blocklists.md) behandelt. Dieses Dokument konzentriert sich auf die app-seitige Architektur und die Grenze zwischen der App und der Extension.

---

## 2. App ↔ Extension IPC {#2-app-extension-ipc}

Die App und die Paket-Tunnel-Extension sind getrennte Prozesse. Sie stimmen sich über drei Mechanismen ab, die alle auf der App Group fußen.

### App-Group-Container {#app-group-container}

`group.com.lavasec` ist der gemeinsame Container, über den App, Tunnel und Widget denselben `LavaSecCore`-Zustand und dieselbe Konfiguration lesen und schreiben. `LavaSecAppGroup` (`Shared/AppGroup.swift`) bündelt jeden gemeinsamen Schlüssel und Dateinamen an einer Stelle, damit die Prozesse bei String-Konstanten nie auseinanderdriften können, darunter:

- Die kompilierten Snapshot-Artefakte (`filter-snapshot.compact`, `filter-snapshot.json`), die serialisierte `app-configuration.json`, der Tunnel-Zustand (`tunnel-health.json`), die Diagnose und das Netzwerkaktivitäts-Log.
- Gemeinsame `UserDefaults`-Schlüssel für die Schutz-Session und den Pause-Zustand. Diese verweisen direkt auf die `LavaSecCore`-Stores (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — sodass App, Tunnel und Live-Activity-Intents ein einziges Schlüssel-Layout, einen einzigen Revisionszähler und ein einziges Dedup-Schema teilen.
- Das Cache-Verzeichnis des Katalogs und die geräteinterne Debug-Log-Datei.

Die Container-URL wird über `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)` aufgelöst.

### Command / Provider-Message (der Steuerpfad) {#command-provider-message-the-control-path}

Die App steuert den Tunnel für alle Befehle mit **`sendProviderMessage`**. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) holt sich die aktive `NETunnelProviderSession` vom zwischengespeicherten Manager und ruft `session.sendProviderMessage(...)` auf. Die Nutzlast wird von `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) in einen kleinen JSON-Umschlag kodiert, der eine Message-`kind` und eine optionale `operationID` trägt (für End-to-End-Latenz-Tracing).

Die erkannten Message-Arten sind Konstanten auf `LavaSecAppGroup`:

| Message-Konstante | Effekt im Tunnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Erzwingt das Neuladen des kompilierten Filter-Snapshots. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Liest nur den gemeinsamen Pause-Zustand neu ein. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Lädt die Konfiguration neu; nur eine Änderung der *Resolver-Identität* löst eine sichtbare Neuverbindung aus. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Diagnose-/Log-Wartung. |

Auf der Tunnel-Seite dekodiert `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) den Umschlag und verzweigt nach `kind`. Bemerkenswert: `reload-configuration` lädt die neue Konfiguration, sodass Nicht-Resolver-Felder (Diagnose-Schalter, Bezahlstatus) wirksam werden, setzt aber nur dann die DNS-Laufzeit zurück und wendet die Tunnel-Netzwerkeinstellungen erneut an — eine sichtbare Neuverbindung —, wenn sich die Resolver-Identität tatsächlich geändert hat (`PacketTunnelProvider.swift:768-792`). Eine Änderung eines Diagnose-Flags oder des Bezahlstatus unterbricht die laufende Verbindung nie.

Die Helfer `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` der App (`AppViewModel.swift:7062`/`7070`) sind schlanke Wrapper, die diese Messages versenden.

### Warum Provider-Messages für die App→Tunnel-Steuerung {#why-provider-messages-for-apptunnel-control}

**`sendProviderMessage` ist der einzige App→Tunnel-Steuerpfad — es gibt kein App→Tunnel-Darwin-Signal.** Ein früherer Entwurf postete bei einer Pause ein `CFNotificationCenter`-Darwin-Signal und beobachtete es in der Extension, doch es feuerte im NetworkExtension-Prozess nie zuverlässig und wurde entfernt. Der Command-Service postet `CFNotificationCenterPostNotification` nicht mehr, und der Tunnel fügt keinen `CFNotificationCenterAddObserver` mehr hinzu — beide Abwesenheiten werden von Source-Introspection-Tests bestätigt (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` für das Posten im Command-Service; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` für den Tunnel-Observer), um gegen ein Wiedereinführen abzusichern. (Die `import Darwin`-Zeilen, die im Command-Service und im Tunnel verbleiben, sind für `flock`-/Socket-Primitive da, nicht für Notifications.)

Ein Darwin-Pfad *wird* in der anderen Richtung weiterhin ausgeliefert. Der Tunnel sendet der App einen Health-Changed-Anstoß: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) postet `CFNotificationCenterPostNotification` auf dem Kanal `com.lavasec.protection.tunnel-health-changed` (der Kanalname steht in `TunnelHealthSignal.swift`, nicht in `AppGroup.swift`), und die App beobachtet ihn über `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), in `AppViewModel` verdrahtet, um `handleTunnelHealthNudge()` aufzurufen. Dieser Tunnel→App-Health-Anstoß wird von `LavaLiveActivitySourceTests.swift:1059-1075` als *vorhanden* bestätigt.

Für die App→Tunnel-Steuerung wird eine Pause ausgeliefert, indem der gemeinsame `ProtectionPauseStore` geschrieben wird und darauf die `reload-protection-pause`-Provider-Message folgt, sodass der Tunnel `refreshProtectionPauseStateOnly` ausführt. `AppViewModel.swift:4995-4996` dokumentiert die Regel direkt: Die App "verlässt sich auch nie auf den Snapshot-Darwin-Observer, sondern verwendet immer `sendProviderMessage`." Behandle das Paar aus App Group (gemeinsamer Zustand) + `sendProviderMessage` (das Aufweck-/Steuersignal) als den App→Tunnel-Steuerpfad.

### Live-Activity-Command-Service {#live-activity-command-service}

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) ist der Einstiegspunkt für Dynamic-Island-/Live-Activity-Aktionen (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes` / `pause-configured` (der einzelne Pause-Button der Live Activity, dessen Dauer der vom Nutzer konfigurierte Wert ist), `resume`, `reconnect`). Die `LiveActivityIntent`s in `LavaLiveActivityIntents.swift` laufen im App-Prozess (der das NetworkExtension-Entitlement hält), also:

- **Pause / Resume** laufen über einen prozessübergreifenden Datei-Lock (`protection-command.lock`, `flock`) und die `LavaSecCore`-Stores `ProtectionPauseStore` / `ProtectionSessionStore`, die das Vergeben von Revisionen und das Dedup doppelter Befehle übernehmen (die `commandID` fädelt die Operations-ID des Aufrufers durch, sodass ein erneut zugestellter Befehl keine zweite Revision vergeben kann). Das Ergebnis plant ein revisionsgeschütztes Live-Activity-Update.
- **Reconnect** wird direkt behandelt (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): Es ruft `loadAllFromPreferences` auf und startet den ersten installierten Tunnel-Manager über `startVPNTunnel()` (da `loadAllFromPreferences` bereits auf die NE-Konfigurationen dieser App beschränkt ist, ist dieser erste Manager der von Lava — anders als `VPNLifecycleController.matchingManagers()` führt es keinen expliziten Identitätsabgleich durch). Connect-On-Demand ist bereits aktiviert, also erzwingt das nur eine sofortige Verbindung; der Status-Abgleich der App bringt die Live Activity dann zurück auf `.on`, sobald sie verbunden ist.

---

## 3. VPN-Lebenszyklus und Steuerung {#3-vpn-lifecycle-control}

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) ist die maßgebliche Quelle für den VPN-Lebenszyklus in der App. Es steuert das Ein-/Ausschalten, cacht den aktiven `NETunnelProviderManager` und veröffentlicht den Status an SwiftUI.

### Manager-Auswahl und Lebenszyklus-Berechnung {#manager-selection-and-lifecycle-math}

Die wiederverwendbare, NetworkExtension-freie Lebenszyklus-Logik liegt in `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). Die App liefert die `NETunnelProviderManager`-gestützten Konformitäten von `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; der Controller übernimmt:

- **Auswahl und Dedup** — `matchingManagers()` filtert über `LavaTunnelConfigurationIdentity.matches(...)` auf Lava-eigene Manager, sortiert nach `selectionPriority` (aktive zuerst, dann kanonischer Anzeigename), und `removeDuplicateManagers(keeping:)` konvergiert auf einen einzigen Überlebenden.
- **Connect-/Stop-Wartezeiten** — `waitForConnect` / `waitForStop` pollen den Live-Verbindungsstatus mit einer `startGraceInterval`-Toleranz, denn direkt nach `startVPNTunnel` kann die Verbindung kurz einen Nicht-pending-Status anzeigen, bevor iOS sie auf `.connecting` umschaltet.

### Ein-/Ausschalten {#turn-on-turn-off}

`enableProtection(...)` (`AppViewModel.swift:5764`) arbeitet **cache-first**: Wenn für die aktuelle Konfiguration ein bestätigt wiederverwendbares vorbereitetes Artefakt existiert, kann das VPN sofort aus dem Cache hochkommen, während eine laufende Katalog-Synchronisierung im Hintergrund weiter aktualisiert, und `performCatalogSync` gleicht den laufenden Tunnel beim Abschluss ab. Es blockiert nur dann auf der Synchronisierung, wenn es nichts Gültiges zum Starten gibt (z. B. wenn der Nutzer gerade die aktivierte Listen-Auswahl geändert hat und damit die Identität des gecachten Artefakts ungültig geworden ist).

`disableProtection(...)` (`AppViewModel.swift:5972`) schaltet Connect-On-Demand *vor* dem Stoppen des Tunnels aus, damit iOS ihn nicht sofort wieder verbindet. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) installiert eine `NEOnDemandRuleConnect` (Interface-Match `.any`) und speichert die Einstellungen — das Speichern (nicht nur das Setzen) ist erforderlich, damit iOS die Änderung berücksichtigt.

### Status-Beobachtung (und ein Hitze-Vorbehalt) {#status-observation-and-a-heat-caveat}

`AppViewModel` beobachtet `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) und veröffentlicht `vpnStatus`/`isVPNConfigurationInstalled`. Entscheidend: Wenn ein Manager bereits gecacht ist, liest es die Live-Verbindung des gecachten Managers, statt einen `loadAllFromPreferences`-Refresh zu erzwingen: `loadAllFromPreferences` postet selbst erneut `NEVPNStatusDidChange`, und ein erzwungener Refresh im Observer erzeugte einen sich selbst nährenden Sturm — der Kommentar im Quellcode (`AppViewModel.swift:1046-1048`) hält die gemessenen ~370 Ereignisse/s und die dadurch verursachte 134%-CPU-Hitze-Regression fest. Veröffentlichte Properties ändern sich nur bei echten Übergängen, sodass Leerlauf-Ticks SwiftUI nicht mehr invalidieren.

### Fail-Closed-On-Demand-Abgleich {#fail-closed-on-demand-reconcile}

Connect-On-Demand kann den Tunnel beim Start **kalt** hochbringen (oder nachdem iOS ihn bei einem Netzwerkwechsel abgebaut hat), bevor die App einen Snapshot übergeben hat. Ein kalter Tunnel ohne wiederverwendbaren persistierten Snapshot lädt **fail-closed** — er blockiert allen Traffic — und erholt sich nie von selbst. `AppViewModel` behandelt das in zwei Start-Pfaden, beide daran gekoppelt, dass das Onboarding abgeschlossen ist (`hasCompletedOnboarding`, spiegelt das Flag `@AppStorage("hasSeenLavaOnboarding")`):

- **Nach dem Onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) läuft immer dann, wenn der Schutz beim Start aktiv ist: Es bereitet den Startup-Snapshot vor, persistiert den gemeinsamen Zustand und sendet `reload-snapshot`, damit der Tunnel seine echten Regeln aus dem Fail-Closed-Zustand heraus neu lädt. Fail-Closed bleibt der sichere Standard; das löst es nur zügig ab. (Behebt rot angezeigte Filter / blockierten Traffic nach einem App-Neustart, während Connect-On-Demand den Tunnel oben hält.)
- **Mitten im Onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) läuft *vor* jeglicher Netzwerkarbeit, wenn das Onboarding noch nicht abgeschlossen ist. iOS entfernt ein VPN-Profil beim App-Löschen nicht zuverlässig, sodass eine Neuinstallation eine verwaiste, On-Demand-aktivierte Konfiguration erben kann, die einen Fail-Closed-Kalt-Tunnel hochbringt, bevor der Nutzer überhaupt Blocklisten gewählt hat. Dieser Pfad **entfernt** die Konfiguration (`removeFromPreferences`), statt eine Änderung daran zu speichern — `saveToPreferences` würde bei einem Profil, das diese Installation nicht besitzt, erneut den System-Prompt "VPN-Konfigurationen hinzufügen" anzeigen und den Dialog beim App-Init auslösen, bevor das Onboarding-Sheet gerendert wird. Bei einer sauberen Installation und wenn die geerbte Konfiguration ohnehin schon inaktiv ist, ist es ein No-op.

---

## 4. Guardian / Zustandsmodell {#4-guardian-state-model}

Es gibt zwei verwandte Zustands-Vokabulare: eine Konnektivitäts-*Einschätzung* und einen Guardian-*Maskottchen*-Zustand.

### Konnektivitäts-Einschätzung {#connectivity-assessment}

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) bildet einen `TunnelHealthSnapshot` auf ein `ProtectionConnectivityAssessment` mit einer von **sechs Schweregraden** und **zwei Aktionen** ab:

- Schweregrade: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Primäre Aktionen: `turnOff` oder `reconnect`.

Diese eine Einschätzung steuert sowohl die In-App-Schutz-Oberfläche als auch (weiter abgebildet) den Dynamic-Island-Zustand, sodass beide nie widersprüchlich sind.

**Ehrlichkeits-Untergrenze (v1.0).** Ein aktuelles, nicht abgedecktes Scheitern der DNS-Smoke-Probe kann nie als `.healthy` gelesen werden — die Einschätzung zeigt `.recovering`, bis eine Probe tatsächlich erfolgreich ist, sodass per Fallback getragener Traffic über einen verklemmten Primär-Resolver nicht mehr als „Geschützt" dargestellt wird. Die Reconnect-Logik stützt sich auf `consecutiveDNSSmokeProbeFailureCount` und `lastPrimaryUpstreamSuccessAt` (nur primär) statt auf die generischen Upstream-Zähler, und ein Resolver, der erreichbar bleibt, aber die bekannte-gute Probe weiterhin **ablehnt** (Hijack/Captive/veraltet), wird über einen auf die Resolver-Identität bezogenen `consecutiveRejectedSmokeResponseCount` zu einem neustartwürdigen Zustand eskaliert (LAV-87), selbst wenn die generische Serie auf wechselhaften Roaming-Netzwerken immer wieder zurückgesetzt wird.

### Konnektivitäts-Benachrichtigungen {#connectivity-notifications}

`ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`) verwandelt die Einschätzung in höchstens eine ausstehende lokale Benachrichtigung, gedrosselt (600 s) und dedupliziert. v1.0 ergänzt:

- Eine eigene **`dnsSlow`**-Art („Lava DNS ist langsam") — langsames DNS verwendete früher dieselbe `reconnectNeeded`-Art wieder, sodass ein echter Ausfall sie nicht ablösen konnte.
- **Eskalation/Ablösung** — ein strikt dringenderes Problem (nur `reconnectNeeded` rangiert über dem Rest) kann ein bestehendes, niedriger eingestuftes Banner ablösen und umgeht dabei sowohl den „Problem bereits ausstehend"-Schutz als auch die Drosselung, sodass eine Verklemmung nach einem Geräte-DNS-Fallback die handlungsrelevante „Neu verbinden"-Aufforderung anzeigt, statt ein beruhigendes Banner stehen zu lassen.
- Eine **Persistenz-Migration** (`ProtectionConnectivityNotificationStore`, Schema v2, verdrahtet über `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) stuft einen veralteten ausstehenden `reconnect-needed`-Marker auf `dnsSlow` herab, damit die Eskalation auch über ein Upgrade hinweg funktioniert.

### Geräte-DNS-Capture-Retry {#device-dns-capture-retry}

Wenn die aktive Konfiguration vom Geräte-Resolver abhängt (als primär oder als Fallback), kann ein Netzwerkwechsel/Aufwachen den Tunnel mit einem leeren System-Resolver-Capture zurücklassen — eine stille Verklemmung. `DeviceDNSFallbackPolicy` treibt einen **begrenzten Retry** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1 s, `deviceDNSCaptureMaxRetryAttempts` 5): Der Tunnel liest die System-Resolver jede Sekunde für bis zu fünf Versuche erneut, bis das Capture nicht leer ist, und übernimmt es dann an Ort und Stelle — Selbstheilung ohne Tunnel-Neustart (Events `device-dns-capture-retry` / `-exhausted`). Es ist ein No-op für reine DoH/DoT/DoQ-Konfigurationen (`currentConfigurationDependsOnDeviceDNS()`).

### Guardian-Maskottchen-Zustände {#guardian-mascot-states}

Das Soft-Shield-Guardian-Maskottchen hat genau **sieben** emotionale Zustände — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Jeder Zustand deklariert seine `allowedNextStates`, sodass Übergänge eingeschränkt sind (z. B. kehrt `grateful` nur zu `awake` zurück; `GuardianMascotAnimation.swift:12-29`). Semantik:

- `retrying` = ruhige Selbstheilung.
- `concerned` = sanftes Hilfesuchen.
- `grateful` = feierlicher Erfolg (wird auf Onboarding-/Einstellungs-Oberflächen verwendet, nicht in der Konnektivitäts-Abbildung).

`GuardianMascotAnimation` ist der prozedurale Animations-Kern in `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) ist das SwiftUI-Rendering und unterstützt die Anpassungs-Skins, die über `GuardianShieldStyle` ausgewählt werden (Anzeigenamen Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, mit der `displayName`-Zuordnung in den Zeilen 18-35). Ein paar Rohwerte weichen von ihren Anzeigenamen ab (z. B. `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, und `purpleObsidian` wird als "Amethyst" gerendert), persistiere also den Rohwert, nicht das Label.

### Wie die beiden zusammenhängen {#how-the-two-connect}

Die `LavaActivityAttributes.ProtectionState` der Live Activity (`Shared/LavaActivityAttributes.swift`) brückt die Einschätzung über `guardianState` zu einem Maskottchen-Zustand: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). `AppViewModel` wählt den Schutz-Zustand für die Dynamic Island aus demselben `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): Ein Schweregrad `networkUnavailable` wird zu `.networkUnavailable`, `recovering` wird zu `.reconnecting`, eine primäre Aktion `reconnect` wird zu `.needsReconnect`, und ansonsten `.on`.

> Hinweis: `LavaTier` (das Design-System-Tiefen-Enum: ruhig → **Floor** / feierlich → **Window** / technisch → **Workshop**) wird in der Design-System-Schicht ausgeliefert (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`) und ist in repräsentative Oberflächen verdrahtet — siehe [das Design-System](../design-system/overview.md). Es steuert die Tiefe des Design-Systems, nicht den hier beschriebenen Schutz-/Tunnel-Client-Pfad.

---

## 5. Live Activity und Widget {#5-live-activity-widget}

Das Widget-Target rendert ausschließlich die Live Activity und die Dynamic Island. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) stellt ein einziges `LavaProtectionLiveActivityWidget` bereit, eine `ActivityConfiguration(for: LavaActivityAttributes.self)` mit:

- Einer Sperrbildschirm-Ansicht, einer erweiterten Dynamic-Island-Mittelregion und kompakten/minimalen Darstellungen, die `SoftShieldGuardian` plus ein Status-Glyph rendern. Die kompakten/Sperrbildschirm-Ansichten berechnen den *effektiven* Schutz-Zustand sekündlich über eine `TimelineView` neu, sodass ein Pause-Countdown ohne Push live bleibt.

`LavaActivityAttributes.ContentState` trägt `protectionState`, ein `resumeDate` (für Pause-Countdowns), `pauseRequiresAuthentication` und den gewählten `shieldStyle`. Die Dekodierung ist tolerant — ein fehlendes `shieldStyle` fällt auf `.original` zurück —, sodass ältere Live-Activity-Nutzlasten weiter funktionieren.

Auf der App-Seite verwaltet `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) die laufende `Activity<LavaActivityAttributes>`: Es beobachtet Änderungen der ActivityKit-Autorisierung, bietet Live Activities nur auf Phone-/Pad-Idiomen an, und `reconcile(...)` startet/aktualisiert/beendet die Activity, damit sie zum angeforderten Schutz-Zustand passt. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) ist der einzige Trichter, der den gewünschten Zustand neu berechnet und den Controller aufruft. Dynamic-Island-Buttons lösen `LiveActivityIntent`s aus, die `LavaProtectionCommandService` aufrufen, wie in [§2](#2-app-extension-ipc) beschrieben.

---

## 6. Onboarding-Ablauf {#6-onboarding-flow}

Das Onboarding wird von `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) präsentiert und durch das in `RootView` deklarierte Flag `@AppStorage("hasSeenLavaOnboarding")` gesteuert (`RootView.swift:32`). Der Ablauf ist eine Folge von `OnboardingPage`s (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

Die ausgelieferte Startkonfiguration kommt aus `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` aktiviert nur die permissive empfohlene Quelle (Block List Basic), wählt **Device DNS** als Resolver — `DNSResolverPreset.device` (id `device-dns`), das eigene DNS des Netzwerks; verschlüsselte Presets wie Google DoH sind optional und werden nicht zum Standard erhoben —, aktiviert die Geräte-DNS-Ausweichoption und lässt das lokale Logging an — mit `protectionEnabled: false`, sodass der Schutz erst eingeschaltet wird, wenn der Nutzer es wählt. `OnboardingDefaultsSummary` formatiert diese Auswahl für die Anzeige ("Ohne Konto fortfahren" ist die Konto-Standardeinstellung).

Das Setzen von `hasSeenLavaOnboarding = true` am Ende ist es, was `hasCompletedOnboarding` umlegt, was wiederum den in [§3](#3-vpn-lifecycle-control) beschriebenen Start-Abgleich-Pfad scharf schaltet. Bis dahin hält der Neutralisierungs-Pfad mitten im Onboarding jeden geerbten Fail-Closed-Tunnel davon ab, Traffic zu blockieren.

---

## 7. App-Zustand: `AppViewModel` {#7-app-state-appviewmodel}

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) ist der zentrale app-seitige Zustandsverwalter. Über den VPN-Lebenszyklus hinaus veröffentlicht es die Oberflächen, an die sich die UI bindet, darunter:

- **Schutz und Tunnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil` sowie die für Nutzer sichtbaren `vpnMessage`/`vpnMessageIsError`.
- **Konfiguration und Katalog** — die `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt` und die kompilierten Regel-Zähler (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnose** — `DiagnosticsStore` und `NetworkActivityLog` (alles lokal; siehe das Datenschutzversprechen unten).
- **Konto und Backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled` und der Angebots-/Entitlement-Zustand von **Lava Security Plus**.
- **Anpassung und Darstellung** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress` und `usesLiveActivities`.

Es delegiert die Lebenszyklus-Serialisierung an einen `protectionActionOrchestrator` (damit ein Hintergrund-Restore nicht mit einem Nutzer-Einschalten verschachtelt wird), hält den gecachten `tunnelManager` und treibt alle Snapshot-/Konfigurations-/Pause-Änderungen über die Provider-Message-Helfer aus [§2](#2-app-extension-ipc) zur Extension.

> **Datenschutz-Einordnung.** Die DNS-Filterung passiert lokal auf diesem Gerät. Die Diagnose- und Netzwerkaktivitäts-Oberflächen, die `AppViewModel` veröffentlicht, werden nur lokal gespeichert — Lava erhält nie deine alltäglichen DNS-Abfragen, deinen Browserverlauf oder Telemetrie pro Domain. Jedes optionale Konto-Backup ist **Zero-Knowledge** (auf dem Gerät verschlüsselt; Lava kann immer nur Chiffretext speichern), einschließlich der Passkey-basierten Wiederherstellung — ihr Schlüssel wird auf dem Gerät per PRF abgeleitet, ohne ein serverseitig gehaltenes Geheimnis. Die Server-Grenze findest du in der [Systemübersicht](./system-overview.md).

---

## Verwandte Dokumente {#related-docs}

- [Systemübersicht](./system-overview.md) — das gesamte System auf einem Bildschirm: die App, der Catalog-Worker und Supabase, plus die Vertrauensgrenzen und die durchgängig verwendete Status-Legende.
- [DNS-Filterung und Blocklisten](./dns-filtering-and-blocklists.md) — die Interna des Paket-Tunnels, hier nur an der Steuergrenze referenziert: die kompilierte Filter-Engine, die verschlüsselten Resolver-Transporte (DoH / DoH3 / DoT / DoQ), das Filter-Regel-Budget, der Blocklisten-Katalog und das Modell der Weiterverbreitung nur über Quell-URLs.
- [Konten und Zero-Knowledge-Backup](./accounts-and-backup.md) — die Anmelde-Anbieter und der Zero-Knowledge-Backup-Umschlag, den `AppViewModel` orchestriert (einschließlich des Zero-Knowledge-, PRF-abgeleiteten Passkey-Wiederherstellungs-Slots).
- [Backend und Daten](./backend-and-data.md) — der `lavasec-api`-Catalog-Worker, Cloudflare R2 und das Supabase-Schema/RLS, die auf der anderen Seite der App↔Server-Grenze sitzen.
- [Design-System](../design-system/overview.md) — das `LavaTier`-Tiefenmodell, die sieben Zustände des Soft-Shield-Guardian und die Shield-Skins sowie die Copy-/Lokalisierungs-Konventionen, die der Client rendert.
- [Hinweise zu Drittanbietern](../legal/third-party-notices.md) und [GPL-Compliance-Entscheidung zur Verbreitung nur über Quell-URLs](../legal/gpl-source-url-only-compliance-decision.md) — die Verbreitungs-Einschränkungen hinter der Katalog-/Filter-Pipeline, die der Client konsumiert.
