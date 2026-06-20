---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Funktionskatalog {#feature-catalog}

> Zielgruppe: PM / Engineering. Dieser Katalog deckt nur den **aktuellen, umgesetzten** Funktionsumfang ab. Alles, was zwar entworfen, aber noch nicht gebaut ist, steht in der internen Roadmap und nicht hier.

Lava Security ist eine iOS-App, bei der Privatsphäre an erster Stelle steht. Sie filtert DNS **lokal auf dem Gerät** über einen NetworkExtension-Pakettunnel und blockiert schädliche und unerwünschte Domains für alle, die sich technisch nicht auskennen (Eltern, ältere Menschen) — mit kostenlosem Grundschutz für immer und ganz ohne Konto.

Das Datenschutzversprechen, das hinter jeder der folgenden Funktionen steckt:

> Die gesamte DNS-Filterung passiert auf dem Gerät; Lava leitet dein Surfen nie über die eigenen Server und bekommt nie zu sehen, welche Domains du besuchst — das Backend hält nur Katalog-Metadaten, ein undurchsichtiges, pro Nutzer verschlüsseltes Backup und anonymisierte Diagnosedaten, die du selbst zum Senden freigibst.

## So liest du diesen Katalog {#how-to-read-this-catalog}

- **Free** — für alle verfügbar, kein Konto, kein Kauf.
- **Plus** — freigeschaltet durch Lava Security Plus, die einzige optionale, kostenpflichtige Stufe. Plus schaltet **ausschließlich Anpassungen** frei; es sperrt nie den grundlegenden Schutz weg und lässt zahlende Nutzer nie die Schutzbarriere umgehen.
- Jede Zeile ist **Umgesetzt**, sofern nicht direkt anders gekennzeichnet. Statuslegende: **Umgesetzt** = ausgeliefert und im Code bestätigt; **Geplant** = entworfen, nicht gebaut; **Verworfen** = abgelehnt oder zurückgenommen. Geplante/verworfene Punkte sind in der internen Roadmap dokumentiert, nicht hier.

Die maßgeblichen Obergrenzen der Stufen leben in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, mit dem Alias `.plus`). Der **Schalter** für die Plus-Berechtigung ist ein lokales Flag (`isPaid`) — die maßgebliche Quelle. Das Backend **spiegelt** die App-Store-Berechtigungen (`POST /v1/account/entitlements/app-store-sync` fügt eine `entitlements`-Zeile ein oder aktualisiert sie), aber diese Zeile ist eine Spiegelung, kein Schalter; bislang steuert noch kein Backend-Sync die Freischaltung.

---

## 1. Schutz & VPN {#1-protection-vpn}

Das Kernprodukt: ein lokaler, reiner DNS-Pakettunnel und das ruhige Zustandsmodell drumherum.

| Funktion | Stufe | Hinweise |
|---|---|---|
| **Lokaler, reiner DNS-Pakettunnel** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) fängt DNS ab und bewertet jede Domain direkt auf dem Gerät. Kein Surf-Traffic wird über Lava geleitet. Tunnel-Adresse `10.255.0.2`, DNS-Server `10.255.0.1`. |
| **Vorrang der Filterentscheidung** | Free | `Block durch Schutzbarriere > lokale Allowlist (Erlaubte Ausnahmen) > Blockliste > standardmäßig erlauben`; ungültige Domains werden blockiert. (`FilterSnapshot.decision()`.) |
| **Anfrage-Vorrang (Bootstrap zuerst)** | Free | `Resolver-Bootstrap > vorübergehende Pause > Filter` — der eigene Hostname des Resolvers wird nie blockiert. (`DNSQueryDispatcher`.) |
| **Fail-closed beim Kaltstart** | Free | Ein kalter Tunnel ohne wiederverwendbaren Snapshot installiert einen `FailClosedRuntimeSnapshot`, der allen Traffic blockiert, statt ungefiltertes DNS durchzulassen. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` hält den Schutz aufrecht / startet ihn automatisch neu — aktiviert **erst nach** einer bestätigten Verbindung, nie schon bei der Profilinstallation, und während unvollständigem Onboarding deaktiviert, damit eine frische Installation keinen Tunnel hochfahren kann, den man nicht mehr ausschalten kann. |
| **Vorübergehende Pause (5 / 10 Min.) + Fortsetzen** | Free | Pause/Fortsetzen laufen über `LavaProtectionCommandService` unter einem flock-Dateisperre mit Revisions-Dedup. |
| **Pause mit erforderlicher Authentifizierung** | Free | Optionale Sperre pro Oberfläche (`SecurityProtectedSurface.protectionPause`): Eine Pause erfordert lokale Geräte-Authentifizierung; der Command-Service verweigert eine nicht authentifizierte Pause, und die Live Activity blendet die Pausen-Buttons aus. |
| **Neu verbinden** | Free | Startet den Tunnel direkt neu (umgeht die Pausen-Pipeline des Command-Service). |
| **Soft-Shield-Zustandsmodell von Lava** | Free | 7 Ausdruckszustände — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 Verbindungs-Schweregrade fallen zu 4 Gesichtern zusammen; identisch dargestellt in der App, im Onboarding und in der Live Activity. |
| **Verbindungsbewertung** | Free | 6 Schweregrade (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) steuern Lavas Gesicht und den Statustext. |
| **Performance-Härtung** | Free | Cache-first beim Einschalten, Zusammenführen laufender Anfragen, begrenzt paralleles Abrufen und Flap-Coalescing (warmes Einschalten mit ~112 ms auf dem iPhone 15 Pro gemessen, laut der modularen Beschleunigungsarbeit). |

> **Geräte-Schutzbarriere (für alle, nie eine Paywall):** Eine harte Obergrenze von `~3,26 Mio. Regeln` (Ziel: 32 MB resident unter der iOS-Speichergrenze von `~50 MiB` pro Erweiterung) gilt für alle Nutzer über jeder Stufe hinaus (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Konfigurationen über dem Budget werden deterministisch abgelehnt (`exceedsDeviceMemoryBudget`), statt den Tunnel ins Jetsam laufen zu lassen.

---

## 2. Blocklisten & Filterung {#2-blocklists-filtering}

Was blockiert wird, wie Listen ausgewählt werden und wo die Grenze zwischen den Stufen verläuft.

| Funktion | Stufe | Hinweise |
|---|---|---|
| **Blocklisten nur per Quell-URL** | Free | Lava veröffentlicht nur die Upstream-URL + akzeptierte Hashes; das Gerät holt und parst die **Bytes** der Liste selbst. Lava speichert, spiegelt, verändert oder serviert **niemals** die Bytes von Blocklisten Dritter. Siehe [GPL-Konformitätsentscheidung: nur Quell-URL](../legal/gpl-source-url-only-compliance-decision.md). |
| **Kuratierter Katalog (10 Quellen)** | Free aktivierbar | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **Kostenlose Standard-Blocklisten** | Free | Eine frische Installation aktiviert **Block List Project Phishing + Scam** (die beiden Quellen mit dem Flag `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **Parsen / Normalisieren / Dedup auf dem Gerät** | Free | `BlocklistParser` unterstützt auto/plain/hosts/adblock/dnsmasq, wirft Kommentare/Leerzeilen/Ungültiges raus, entfernt exakte Duplikate und deckelt bei 1.000.000 Regeln pro Liste. Eine `hosts`-Zeile mit mehreren Hosts gibt jetzt **jeden** Host der Zeile aus, nicht nur den ersten (Parser-Regelversion 2). |
| **Validierung der Upstream-Bytes** | Free | Geholte Bytes werden per SHA-256 geprüft und nur akzeptiert, wenn die Prüfsumme in den `accepted_source_hashes` des Katalogs steht; bei Abweichung fällt Lava auf den letzten guten Cache zurück oder geht fail-closed. |
| **Filter für geschützte Domains** | Free | Aus jeder geparsten Quelle werden geschützte Lava-/Apple-/Identitätsanbieter-Domains entfernt (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …), damit eine Upstream-Liste die App, den Tunnel oder das Anmelden nicht kaputtmachen kann. |
| **Erlaubte Ausnahmen (Allowlist)** | Free | Nutzerverwaltete Allowlist, die Domains trotz Blocklisten zulässt. Free-Limit: 25 erlaubte / 25 blockierte Domains (`FeatureLimits.free`). |
| **Budget für Filterregeln (Stufenmetrik)** | Free / Plus | Die ausgelieferte Stufenmetrik ist die Gesamtzahl der kompilierten Domain-**Regeln**: **Free 500K / Plus 2M** (`maxFilterRules` in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Ersetzt die alte Begrenzung über die Anzahl der Listen. Konfigurationen über der Stufe lösen `exceedsTierFilterRuleLimit` aus. |
| **Höhere Domain-Limits** | Plus | 1.000 erlaubte / 1.000 blockierte Domains (`FeatureLimits.plus`). |
| **Eigene Blocklisten** | Plus | `allowsCustomBlocklists`. Eigene Listen werden auf dem Gerät geholt und geparst, lokal zwischengespeichert und nie über Lava-Server geleitet. |
| **Wiederverwendung des Warmstart-Artefakts** | Free | Ein Manifest + Identitäts-Fingerabdruck lässt den Tunnel den kompakten Snapshot auf der Platte ohne Neukompilieren wiederverwenden; die Wiederverwendung wird abgelehnt (mit einem datenschutzsicheren Grund, der nur den Feldnamen nennt), wenn sich die Eingaben ändern. |
| **Smart Save (Bestätigung nur bei Abschwächung)** | Free | Änderungen an deinem Filter, die den Schutz nur *verstärken* oder neutral sind (eine Blockliste oder eine blockierte Domain hinzufügen), werden direkt angewendet; Änderungen, die den Schutz *abschwächen* — eine Blockliste entfernen, eine blockierte Domain entfernen oder eine erlaubte Ausnahme hinzufügen — laufen zuerst über ein Prüf-Bestätigungs-Sheet, mit einem Panel „Sei besonders vorsichtig", wenn Ausnahmen hinzugefügt werden (`FiltersView.saveChanges()`, `weakensProtection`). |
| **Budget-Messung (speicherbare Auswahl)** | Free / Plus | Die Auswahl-Messung kürzt Zählwerte ab (500K / 1.2M / 2M) und nutzt einen Soft-Ceiling-Spielraum von 1,10 (die Summe pro Liste überzählt die deduplizierte Vereinigung um ~7–10 %); ein Zählwert, der noch innerhalb der Toleranz liegt, wird gekappt und liest sich z. B. als „500K von 500K", bis er das Soft-Ceiling überschreitet (`FilterRuleBudget`). |

> Die maßgebliche Budgetprüfung läuft zur Kompilierzeit auf der deduplizierten Vereinigung (`FilterSnapshotPreparationService`); zuerst wird das Gerätelimit geprüft, dann das Stufenlimit. Die UI-Anzeige bei der Auswahl nutzt eine Summe pro Liste mit einem weichen Spielraum von 1,10.

---

## 3. Verschlüsseltes DNS {#3-encrypted-dns}

Resolver-Transporte und Routing für nicht blockierte Anfragen.

| Funktion | Stufe | Hinweise |
|---|---|---|
| **Fünf Resolver-Transporte** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | URLSession-basiertes DoH, das HTTP/3 bevorzugt. Die UI ergänzt **`DoH3` (kein Schrägstrich)**, z. B. „Quad9 (DoH3)“, **nur dann, wenn eine h3-Aushandlung tatsächlich beobachtet wird** — bevorzugt, nie versprochen (`DoHTransport`). |
| **DoT** | Free | Gepoolte `NWConnection`s (bis zu 4/Endpunkt) mit Auffrischung bei Inaktivität und einem Wiederholungsversuch über eine frische Verbindung. |
| **DoQ** (nur eigene) | Plus | DNS-over-QUIC hat **kein eingebautes Preset** — es ist nur über einen **eigenen `doq://`-Resolver** erreichbar, und eigenes DNS ist Plus. Öffnet **pro Anfrage eine frische QUIC-Verbindung** (der 4-spurige Pool bringt Parallelität, nicht die Wiederverwendung des Handshakes); die Wiederverwendung von Verbindungen ist auf eine iOS-26-Mindestversion verschoben. |
| **Preset-Resolver** | Free | Device DNS (Standard), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — in den Varianten IP / DoH / DoT, wo angeboten (`DNSResolverPreset.allPresets`). |
| **Resolver-Routing & Failover** | Free | `ResolverOrchestrator` routet nach Transport, fällt auf einfaches DNS zurück, wenn ein verschlüsselter Plan keine Endpunkte hat, macht Failover pro Endpunkt mit einer Backoff-Sperre und dann die Geräte-DNS-Ausweichoption. |
| **Geräte-DNS-Ausweichoption** | Free | Fällt auf den Resolver des aktuellen Netzwerks zurück, wenn der gewählte Resolver nicht verfügbar ist; **standardmäßig an**. Sichtbar als Schweregrad `usingDeviceDNSFallback`. |
| **Eigenes DNS** | Plus | `allowsCustomDNS` — vom Nutzer angegebener Resolver (inkl. DNS-Stamp-Parsing für eigene Presets). |

---

## 4. Konten & Zero-Knowledge-Backup {#4-accounts-zero-knowledge-backup}

Optionale Konto-Anmeldung und verschlüsseltes Backup der Einstellungen. Nichts davon ist nötig, um den Schutz zu nutzen.

| Funktion | Stufe | Hinweise |
|---|---|---|
| **Optionale Konto-Anmeldung (Apple + Google)** | Free | Nativer id_token-Flow, der bei Supabase Auth eingelöst wird (`grant_type=id_token`) mit einem gehashten Nonce; nur die daraus entstehende Supabase-Sitzung wird gerätelokal im Keychain gespeichert. Anmeldung per E-Mail/Passwort wird bewusst nicht angeboten (Verworfen). |
| **Zero-Knowledge-verschlüsseltes Backup** | Free | Clientseitiger AES-256-GCM-Umschlag; der zufällige Payload-Schlüssel wird in PBKDF2-HMAC-SHA256-Schlüsselslots (210k Iterationen) eingepackt. Nur Chiffretext + nicht geheime Metadaten gehen zu Supabase `user_backups` (RLS pro Nutzer) hoch. Der Server kann ohne ein vom Nutzer gehaltenes Geheimnis nicht entschlüsseln. |
| **Minimierte Backup-Payload** | Free | Sichert aktivierte Blocklisten-IDs, erlaubte/blockierte Domains, Resolver-Einstellungen, lokale Log-Einstellungen, Lavas Look usw. — und schließt `isPaid`, QA-Flags, Diagnosedaten, Snapshots und vollständige Blocklisten-Bytes ausdrücklich aus. |
| **Schlüsselslot mit Gerätegeheimnis** | Free | Ein 32-Byte-Gerätegeheimnis im rein gerätelokalen Keychain (`...ThisDeviceOnly`, nicht iCloud-synchronisiert) für reibungsloses Wiederherstellen auf demselben Gerät. |
| **Wiederherstellungscode + unterstützte Wiederherstellung** | Free | Ein 8-Wort-CVCV-Code (~105 Bit), per SHA256 mit einem serverseitig gehaltenen Wiederherstellungsanteil kombiniert, um den Slot für die unterstützte Wiederherstellung zu entsperren. Zwei Faktoren: keine Hälfte allein entschlüsselt. |
| **Slot für Passkey-Wiederherstellung** | Free | Optionaler, per WebAuthn gesicherter Slot, und **Zero-Knowledge**: Sein Entpack-Schlüssel wird **auf dem Gerät** aus der WebAuthn-PRF-Ausgabe (`hmac-secret`) des Authentifikators abgeleitet (HKDF-SHA256). Der Server registriert keinen Passkey, stellt keine Challenges aus, hält kein Wiederherstellungsgeheimnis und stellt keine Passkey-Routen bereit — das frühere Server-Escrow-Design wurde verworfen. Die Produktionsreife auf physischen Geräten hängt vom Associated-Domains-/AASA-Hosting ab (Geplant). |
| **Kontolöschung / Datenrechte** | Free | Ein authentifizierter Worker-Endpunkt löscht Backups, Einstellungen, Berechtigungen, Profil und Fehlerbericht-Anhänge, dann den Supabase-Auth-Nutzer; die App meldet sich ab und löscht das lokale Entsperr-Material. |

---

## 5. Widget & Live Activity {#5-widget-live-activity}

Präsenz auf dem Sperrbildschirm und in der Dynamic Island.

| Funktion | Stufe | Hinweise |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): eine einzelne `Activity<LavaActivityAttributes>` auf dem Sperrbildschirm und in der Dynamic Island (expanded center / compactLeading guardian / compactTrailing + minimaler Status-Glyph). |
| **Schutzanzeige mit 5 Zuständen** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — jeder ist auf eine Pose von Lava, ein SF Symbol und einen Titel abgebildet. |
| **Aktions-Buttons der Live Activity** | Free | Pause 5 / 10 Min., Fortsetzen, Neu verbinden — `LiveActivityIntent`s, die im App-Prozess über `LavaProtectionCommandService` laufen. Die authentifizierten Pausen-Varianten erfordern lokale Geräte-Authentifizierung. |
| **Einzelner, deduplizierter, revisionsgesteuerter Abgleich** | Free | `LavaLiveActivityController` hält genau eine Activity, aktualisiert nur bei echter Änderung von ID/Inhalt und steuert Updates über die Revision von `ProtectionPauseStore`, damit veraltete Intent-Wiederholungen den Zustand nicht zurückwerfen. |
| **Live-Activities-Schalter** | Free | In den Einstellungen umschaltbar (`setUsesLiveActivities`), nur auf iPhone/iPad verfügbar. |

---

## 6. Onboarding {#6-onboarding}

Der Ablauf beim ersten Start, der die lokale VPN-Konfiguration installiert und sinnvolle Standardwerte setzt.

| Funktion | Stufe | Hinweise |
|---|---|---|
| **Mehrseitiger Erst-Start-Ablauf** | Free | `OnboardingFlowView` — 6 Seiten: `lava, guardIntro, features, vpn, notifications, done`. (Die Profilinstallation und die Benachrichtigungsabfrage passieren beim richtigen Schritt, nicht gleich am Anfang.) |
| **Installation des lokalen VPN-Profils** | Free | Installiert die lokale VPN-Konfiguration während des Onboardings **ohne** Connect-On-Demand zu aktivieren, damit der Schutz nach Abschluss nie heimlich automatisch an ist — die Schutz-Oberfläche bleibt maßgeblich. |
| **Abfrage der Benachrichtigungserlaubnis** | Free | Wird im Ablauf beim Benachrichtigungsschritt angefordert. |
| **Empfohlene Standardwerte angewendet** | Free | Device-DNS-Resolver, Geräte-DNS-Ausweichoption an, lokales Logging an (Zähler + Verlauf + Aktivität), Block List Project Phishing + Scam aktiviert, ohne Konto fortfahren (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Einstellungen {#7-settings}

Oberflächen für Konfiguration, Sicherheit, Diagnose und Feedback.

| Funktion | Stufe | Hinweise |
|---|---|---|
| **App-Entsperrcode + Biometrie** | Free | `SecurityController`: gesalzener SHA256-Code-Verifier im Keychain + `LAContext`-Biometrie, mit einer App-Entsperr-Sperrschicht und Privatsphäre-Maske bei Wechseln der Szenenphase. |
| **Schutz pro Oberfläche** | Free | `SecurityProtectedSurface` schützt sechs Oberflächen: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Jede kann unabhängig lokale Geräte-Authentifizierung verlangen (z. B. gibt der Einstellungen-Tab `.requires(.appSettings)` zurück). |
| **Lava Guard Look-Auswahl (7 Looks)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, jeweils mit einer passenden Glyph-Farbe für die Dynamic Island. Auswahl über eine Radio-Auswahl in einem Bottom-Sheet („Wähle deinen Guard", `LavaGuardLookPickerSheet`); noch gesperrte Looks tragen ein Schloss-Glyph, und das Freischalt-/Upgrade-Panel lebt im Sheet. |
| **Passend zum App-Icon** | Free | Optionales alternatives App-Icon, abgestimmt auf den gewählten Look von Lava. |
| **Erscheinungsbild** | Free | Hell/Dunkel/System-Farbschema. |
| **Steuerung für rein lokales Logging** | Free | Schalter für Filterzähler, Domainverlauf (Diagnose) und Netzwerkaktivität — alles auf dem Gerät gespeichert. Feingranulare Logs (Domainverlauf + Netzwerkaktivität) werden auf ein **7-Tage**-Fenster zurechtgestutzt (`LocalLogRetention.fineGrainedDays = 7`); Zähler und Lava-Guard-Fortschritt werden länger aufbewahrt. |
| **Aktivität / Domain-Logs (Guard-Detail)** | Free | Dynamische, rein lokale Diagnose, erreichbar vom Guard-Tab (`GuardDestination.activity`). Die Zusammenfassung ist ein Anfrage-**Fluss** — eine Gesamtsumme „verarbeitete Anfragen", aufgeteilt in einen Mengenbalken Erlaubt/Blockiert mit „% lokal geschützt" (ehrliches Runden: ein winziger Anteil liest sich als `<1%`, ein nahezu vollständiger Anteil als `>99%`). Ein Abschnitt **Domain-Logs** enthält **Top-Domains** (am häufigsten blockiert & erlaubt, nach Anzahl der Anfragen sortiert) und **Domainverlauf** (jüngste Auflösungen & Entscheidungen); Domain-Zeilen erscheinen nur, wenn das Opt-in für den Verlauf an ist. |
| **Filter (Guard-Detail)** | Free | Einzelner, vereinheitlichter Filterbildschirm, erreichbar vom Guard-Tab. Ein „My filter"-Hub öffnet einen konsolidierten **My filter**-Bildschirm mit zwei Regalen — **„Lava blockiert diese"** (Blocklisten + einzeln blockierte Domains) und **„Lava lässt diese durch"** (erlaubte Ausnahmen) — unter einem einzigen Bearbeiten/Speichern-Entwurfsablauf. Ein Flussdiagramm „Phone → Lava → Internet" steht am Anfang des Tabs, und das Öffnen von My filter aktualisiert den Katalog automatisch. |
| **Netzwerkaktivität (Einstellungen → Erweitert)** | Free | Begrenzter, rein lokaler Ereignisstrom von Netzwerk-/Laufzeit-/Nutzerübergängen, geteilt über die App Group (`NetworkActivityLog`). Von der Aktivitäts-Oberfläche nach **Einstellungen → Erweitert** verschoben (nach „Nerd Stats", `SettingsRoute.networkActivity`), hinter der Sperre `.activityViewing`, mit einem eigenen Datenschutz-Panel („Bleibt auf diesem iPhone", 7 Tage aufbewahrt). |
| **Fehlerbericht** | Free | Vom Nutzer ausgelöster Assistent, der ein anonymisiertes Paket an `POST /v1/bug-reports` schickt; kein Domainverlauf in v1. Auch per Schütteln-zum-Melden erreichbar (`RageShakeDetector`). Das Paket trägt jetzt außerdem die Build-Provenienz (`appVersion`/`appBuild`/`sourceRevision`) und Zähler zur Konnektivitäts-Ehrlichkeit. |
| **Abo-Verwaltung** | Plus | Für aktive Abonnenten zeigt der Upgrade-Bildschirm Abo verwalten (automatisch verlängernde Tarife, über `AppStore.showManageSubscriptions`), Kauf wiederherstellen und das Ablaufdatum der Berechtigung; eine lebenslange Freischaltung zeigt keine Zeile „Verwalten". |
| **Rechtliche Hinweise + Version** | Free | Die Einstellungen zeigen rechtliche Hinweise Dritter (siehe [Hinweise zu Drittanbietern](../legal/third-party-notices.md)) und eine Versions-/Build-Seite. |

---

## App-Architektur (zur Orientierung) {#app-architecture-for-orientation}

Drei Bundles teilen sich eine App Group `group.com.lavasec`, daneben ein Quellordner `lavasec-ios: Shared/`, der in sie hineinkompiliert wird:

- **LavaSecApp** (`com.lavasec.app`) — die SwiftUI-App-Hülle; in diesem Build ist die Wurzel eine `TabView` mit zwei Tabs (**Schutz** + **Einstellungen**), wobei Filter und Aktivität als Detailbildschirme unter dem Guard-Tab erreichbar sind (Netzwerkaktivität lebt jetzt unter Einstellungen → Erweitert).
- **LavaSecTunnel** (`.tunnel`) — die DNS-Filter-/Resolve-Engine auf dem Gerät.
- **LavaSecWidget** (`.widget`) — die WidgetKit Live Activity.
- **Shared/** — zielübergreifende Quellen (kein Bundle): App Group, Command-Service, Maskottchen, Live-Activity-Attribute/-Intents.

Die Steuerung zwischen App ↔ Erweiterung nutzt **Provider-Nachrichten** über `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), keine Darwin-Benachrichtigungen. Filterregeln gehen von App → Erweiterung als App-Group-Snapshot-Dateien (`filter-snapshot.json` / `.compact`).

---

## Verwandte Dokumente {#related-docs}

- Roadmap — geplante und verworfene Funktionen (Plus-Preise/StoreKit-Positionierung, Android-Portierung, Schutz auf URL-Ebene, Passkey-Reife für Associated-Domains, Easter-Egg-Minispiel, GPL-3.0-Open-Source-Release usw.) leben in der internen Roadmap, nicht in diesem öffentlichen Katalog.
- [GPL-Konformitätsentscheidung: nur Quell-URL](../legal/gpl-source-url-only-compliance-decision.md)
- [Ausnahme zu den Datenbedingungen von Open-Source-Listen](../legal/open-source-list-data-terms-carveout.md)
- [Hinweise zu Drittanbietern](../legal/third-party-notices.md)
