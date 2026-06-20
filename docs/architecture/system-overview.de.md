---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Systemüberblick

> **Zielgruppe:** Entwickler. Das hier ist ganz Lava Security auf einer Seite — woraus die Teile bestehen, wie Daten zwischen ihnen fließen und wo die Vertrauensgrenzen liegen. Die Docs zu den einzelnen Komponenten gehen tiefer; diese hier gibt es, damit du das System im Kopf hast, bevor du sie liest.
>
> **Maßgeblich:** Wenn diese Doc und ein Plan sich widersprechen, **gewinnt der Code**. Der Status spiegelt die im Code bestätigte Realität wider, nicht den Wunsch aus dem Plan. Siehe die [Status-Legende](#8-status-legend) ganz unten.

## 1. Das Produkt in einem Satz {#1-product-one-liner}

Lava Security ist eine iOS-App mit Datenschutz an erster Stelle, die DNS **lokal auf dem Gerät** durch einen NetworkExtension-Paket-Tunnel filtert und schädliche sowie unerwünschte Domains für nicht-technische Nutzer (Eltern, ältere Menschen) blockiert — wobei der Kernschutz für immer kostenlos ist und kein Konto nötig ist.

## 2. Das Datenschutzversprechen (verbindlich) {#2-the-privacy-promise-canonical}

> Die gesamte DNS-Filterung passiert auf dem Gerät; Lava leitet dein Surfen nie über seine Server und bekommt nie den Strom der Domains zu sehen, die du besuchst — das Backend hält nur Katalog-Metadaten, ein undurchsichtiges, pro Nutzer verschlüsseltes Backup und anonymisierte Diagnosedaten, die du selbst senden möchtest.

Alles weiter unten dient dazu, diesen Satz wahr zu halten. Die Architektur ist serverseitig absichtlich klein gehalten: Das Gerät macht die Arbeit, und das Backend bekommt nie eine Anfrage zu sehen.

## 3. Komponenten {#3-components}

### iOS-Client (drei ausführbare Targets + gemeinsamer Code, eine App Group `group.com.lavasec`) {#ios-client-three-executable-targets-shared-code-one-app-group-groupcomlavasec}

| Komponente | Bundle / Ort | Rolle | Status |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | SwiftUI-App-Hülle; Einstiegspunkt, Navigation mit zwei Tabs Schutz + Einstellungen (Filter/Aktivität sind Detailansichten unter Schutz; Netzwerkaktivität nach Einstellungen → Erweitert verschoben). | Umgesetzt |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; die DNS-Filter-/Auflöse-Engine direkt auf dem Gerät. Unterliegt der iOS-**Speichergrenze von ~50 MiB pro Extension**. | Umgesetzt |
| **LavaSecWidget** | `com.lavasec.app.widget` | WidgetKit Live Activity (Sperrbildschirm + Dynamic Island). | Umgesetzt |
| **Shared/** | `Shared/` | Quellen, die über Targets hinweg geteilt werden: App Group, Command-Service, Maskottchen, Live-Activity-Attribute/-Intents. | Umgesetzt |

**App-seitige Controller (in LavaSecApp):**

- **AppViewModel** — der app-seitige Controller (Gott-Objekt): kümmert sich um den Lebenszyklus von `NETunnelProviderManager`, die Persistenz des geteilten Zustands, die Provider-Kommunikation, den Live-Activity-Abgleich, den Katalog-Sync, das Backup, StoreKit und die Authentifizierung.
- **RootView** — `TabView` mit zwei Tabs (Schutz + Einstellungen), wobei Filter und Aktivität als Detailansichten unter Guard erreichbar sind; steuert das Onboarding, beherbergt die Overlays für Sicherheitssperre und Datenschutzmaske.
- **SecurityController** — Passcode (gesalzenes SHA256 im Keychain) + Biometrie + Schutz pro Oberfläche.
- **LavaLiveActivityController** — Abgleicher für eine einzelne Activity, dedupliziert und revisionsgesteuert.
- **OnboardingFlowView** — mehrseitiger Ablauf beim ersten Start (6 Seiten: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (plattformunabhängiges SwiftPM-Paket, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — kompilierter Filter + Entscheidungsreihenfolge; die kompakte Form ist das mmap-freundliche Artefakt auf der Festplatte, das der Tunnel liest.
- **DNSQueryDispatcher** — Reihenfolge der Anfragen: bootstrap > pause > filter.
- **ResolverOrchestrator** — Transport-Routing, Rückfall auf einfaches DNS, Failover pro Endpunkt, Geräte-DNS-Ausweichoption.
- **DoHTransport / DoTTransport / DoQTransport** — Ausführer für die verschlüsselten Transporte.
- **FeatureLimits** (in `SubscriptionPolicy.swift`) — Obergrenzen pro Stufe (Quelle der Wahrheit), über die statischen Member `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — Rechnung für die Geräte-Schutzbarriere + verbindliche Budget-Durchsetzung nach der Vereinigung.
- **BlocklistCatalogSync / BlocklistParser** — Katalogabruf, direkter Upstream-Download, lokales Parsen/Normalisieren/Deduplizieren, Filter für geschützte Domains.
- **GuardianMascotAnimation** — Zustandsgraph des Maskottchens mit 7 Zuständen (gerendert von `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — Backup-Krypto + Payload.
- **SupabaseIDTokenAuth** — `id_token`-Authentifizierung über rohe URLRequest (kein SDK).

### Backend {#backend}

| Komponente | Rolle | Status |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker (`api.lavasecurity.app`): Katalog-Lesezugriffe, Admin-/Cron-Blocklist-Sync + -Veröffentlichung, anonyme Fehlerberichte, Kontolöschung, Spiegelung der App-Store-Berechtigungen, QA-Probes. | Umgesetzt |
| **lavasec-email Worker** | Nur empfangender Cloudflare-Email-Routing-Weiterleiter für `@lavasecurity.app`; lehnt unbekannte/zu große Mails ab. | Umgesetzt |
| **Supabase Postgres** | Konten, `user_backups`, Katalog-Metadaten, Tabellen nur für die Service-Rolle; **RLS auf jeder öffentlichen Tabelle**. | Umgesetzt |
| **Cloudflare R2** (der R2-Bucket für die Produktion, ein separater Preview-Bucket fürs Staging) | Katalog-Snapshots + der Round-Robin-Sync-Cursor. **Niemals** Bytes von Drittanbieter-Blocklisten; die Upload-Route für Anhänge von Fehlerberichten wurde entfernt (alte Objekte werden nur bei einer Kontolöschung gelöscht). | Umgesetzt |
| **Cloudflare D1** (die Hilfe-Feedback-Datenbank) | Nur-anfügende, anonyme Feedback-Stimmen zu Hilfe-Artikeln. | Umgesetzt |

## 4. Datenfluss-Diagramm {#4-data-flow-diagram}

Die mit Abstand wichtigste Eigenschaft: **Der Pfad des verschlüsselten DNS-Resolvers (rechte Seite) berührt nie das Backend von Lava (unten).** Das Gerät holt sich Katalog-*Metadaten* vom Worker, aber die *Bytes* der Listen und der eigentliche Anfragestrom gehen direkt an Dritte.

```
                                  YOUR iPHONE
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                                                                             │
 │   ┌──────────────┐   provider messages    ┌───────────────────────────┐    │
 │   │  LavaSecApp  │ ─────────────────────►  │      LavaSecTunnel        │    │
 │   │ (AppViewModel│   (reload-snapshot /    │  (NEPacketTunnelProvider) │    │
 │   │  controller) │    pause / config)      │                           │    │
 │   └──────┬───────┘                         │   DNSQueryDispatcher       │   │
 │          │                                 │   bootstrap > pause >      │   │
 │          │ writes / reads                  │   ┌──────────────────────┐ │   │
 │          ▼                                 │   │  CompactFilterSnapshot│ │   │
 │   ┌──────────────────────────┐  mmap       │   │  guardrail > allow >  │ │   │
 │   │  App Group container      │ ◄──(read)── │   │  block > default-allow│ │   │
 │   │  group.com.lavasec        │            │   └──────────┬───────────┘ │   │
 │   │  • filter-snapshot.compact│            │              │ allowed     │   │
 │   │  • app-configuration.json │            │              ▼             │   │
 │   │  • tunnel-health.json      │           │   ┌──────────────────────┐ │   │
 │   │  • pause/session UserDefs  │           │   │  ResolverOrchestrator│ │   │
 │   └──────────────────────────┘             │   │  DoH3/DoT/DoQ/IP +   │ │   │
 │          ▲                                 │   │  device-DNS fallback │ │   │
 │          │ reads (Live Activity)           │   └──────────┬───────────┘ │   │
 │   ┌──────┴───────┐                         └──────────────│─────────────┘   │
 │   │ LavaSecWidget│                                        │                 │
 │   │ (Dynamic Isl.│                                        │ encrypted DNS   │
 │   │  + lock scr.)│                                        │ (query stream)  │
 │   └──────────────┘                                        │                 │
 └──────────────────────────────────────────────────────────│─────────────────┘
        │ (a) catalog          │ (b) list bytes              │ (c) blocked → NXDOMAIN
        │  metadata            │  (direct from upstream)     │     allowed → forwarded
        ▼                      ▼                             ▼
 ┌──────────────┐   ┌──────────────────────┐    ┌───────────────────────────────┐
 │ lavasec-api  │   │  Upstream blocklists  │   │  Public DNS resolver           │
 │ Worker       │   │  (HaGeZi, OISD,       │   │  (Quad9 / Cloudflare / Google  │
 │ GET /v1/     │   │   Block List Project) │   │   / Mullvad; user-chosen)       │
 │  catalog     │   └──────────────────────┘    └───────────────────────────────┘
 └──────┬───────┘
        │ reads/writes (metadata only)
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  LAVA BACKEND (sees no DNS queries, no browsing history)                   │
 │  • Supabase Postgres: accounts, user_backups (opaque ciphertext), catalog │
 │  • Cloudflare R2: catalog/latest.json, the round-robin cursor             │
 │  • lavasec-email Worker: receive-only @lavasecurity.app forwarding         │
 └──────────────────────────────────────────────────────────────────────────┘
       ▲
       │ (d) optional: encrypted backup envelope (PostgREST, RLS) — ciphertext only
       │     entitlement mirror, anonymous bug reports, account deletion
       └──── from LavaSecApp, only when the user opts in
```

## 5. Datenflüsse {#5-data-flows}

### A. Der DNS-Pfad (pro Anfrage, alles auf dem Gerät) — Umgesetzt {#a-the-dns-path-per-query-all-on-device-implemented}

Das ist der heiße Pfad und der Kern des Datenschutzes. Er läuft komplett innerhalb von `LavaSecTunnel`; nichts hier erreicht die Server von Lava.

1. Der Paket-Tunnel fängt eine DNS-Anfrage ab (Tunnel-DNS-Server `10.255.0.1`).
2. **`DNSQueryDispatcher`** wendet die Reihenfolge der Anfragen an: **bootstrap > pause > filter**. Bootstrap zuerst ist eine harte Invariante — der Hostname des Resolvers selbst wird vor jeder Filterung aufgelöst, damit der Resolver sich niemals selbst blockieren kann.
3. Wenn es kein Bootstrap und keine Pause ist, wird die Domain gegen **`CompactFilterSnapshot`** geprüft (aus der App Group geladen über `Data(contentsOf:options:[.mappedIfSafe])` als Zero-Copy-mmap). Die Entscheidungsreihenfolge ist **Schutzbarriere > lokale Erlaubnisliste (Erlaubte Ausnahmen) > Blockliste > Standard-Erlauben**; ungültige Domains werden blockiert.
4. **Blockiert** → der Tunnel antwortet lokal (kein Kontakt nach oben). **Erlaubt** → die Anfrage wird an **`ResolverOrchestrator`** übergeben.
5. `ResolverOrchestrator` leitet zum konfigurierten Transport — **`DoH3` / `DoT` / `DoQ` / einfaches DNS (`IP`)** — mit Failover pro Endpunkt hinter einem Backoff-Gate, Rückfall auf einfaches DNS, wenn ein verschlüsselter Plan keine Endpunkte hat, und **Geräte-DNS-Ausweichoption**, wenn der primäre Pfad keine Antwort liefert und der Plan es erlaubt.
6. Die Antwort des Resolvers geht zurück ans Betriebssystem. Der Anfragestrom des Nutzers geht nur an den **vom Nutzer gewählten öffentlichen Resolver**, niemals an Lava.

Hinweise zu Transporten (wörtliche Konventionen): `DoH3` (ohne Schrägstrich) wird **nur dann vermerkt, wenn eine h3-Aushandlung tatsächlich beobachtet wird** — bevorzugt, nie versprochen. **`DoT`** bündelt bis zu 4 NWConnections pro Endpunkt mit Auffrischung bei Leerlauf + einem Wiederholungsversuch über eine frische Verbindung. **`DoQ`** öffnet **pro Anfrage eine frische QUIC-Verbindung** (keine Wiederverwendung); der Pool mit 4 Bahnen bringt Nebenläufigkeit, keine Wiederverwendung des Handshakes — die Wiederverwendung von Verbindungen wurde gebaut, auf Geräten getestet und **zurückgenommen** (vertagt bis zur iOS-26-Mindestversion). Siehe [DNS-Filterung & Blocklisten](./dns-filtering-and-blocklists.md).

### B. Katalogabruf + Blocklist-Laden (nur Quell-URL) — Umgesetzt {#b-catalog-fetch-blocklist-load-source-url-only-implemented}

Wie die Filterregeln aufs Gerät kommen. Lava ist ein Verteiler, der **nur die Quell-URL** weitergibt: Es veröffentlicht nur die Upstream-URL + akzeptierte Hashes und **speichert, spiegelt, transformiert oder liefert niemals Bytes von Drittanbieter-Blocklisten.**

1. Das Gerät holt sich Katalog-**Metadaten** vom Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON, das direkt aus R2 (`catalog/latest.json`) geliefert wird, aufgeteilt in `sources[]` + `guardrails[]`, jeder Eintrag mit `source_url` + `accepted_source_hashes`.
2. Für jede aktivierte Quelle lädt das Gerät die **Bytes der Liste direkt von `source_url`** herunter (dem Upstream — HaGeZi, OISD, Block List Project usw.), **nicht** von Lava.
3. Das Gerät berechnet SHA256 und akzeptiert nur Bytes, deren Prüfsumme in `accepted_source_hashes` steht; bei einer Abweichung fällt es auf den letzten funktionierenden Cache zurück oder schlägt sicher fehl (`checksumMismatch`).
4. **`BlocklistParser`** parst/normalisiert/dedupliziert lokal (Formate auto / plain / hosts / adblock / dnsmasq), dann entfernt **`DomainRuleSet.lavaSecProtectedDomains`** die geschützten Domains (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …), damit eine Upstream-Liste niemals Lava-/Apple-/Identitätsanbieter-Domains blockieren kann.
5. **`FilterSnapshotPreparationService`** vereint die deduplizierte Menge und führt die **verbindliche Budget-Durchsetzung** aus (zuerst Gerätegrenze, dann Stufe), dann schreibt es `filter-snapshot.compact` in die App Group.
6. `AppViewModel` schickt eine `reload-snapshot`-Provider-Nachricht; der Tunnel lädt neu.

Die Worker-Seite spiegelt das: Ihr Admin-/Cron-Sync holt jeden Upstream, hasht/zählt ihn, schreibt `raw_r2_key = null` / `normalized_r2_key = null` und veröffentlicht nur Metadaten neu. Das Modell des Blocklist-Katalogs und der Sync-Pfad im Backend werden in [DNS-Filterung & Blocklisten](./dns-filtering-and-blocklists.md) und [Backend & Daten](./backend-and-data.md) behandelt.

**Budget-Modell (zwei Schichten):**
- **Geräte-Schutzbarriere (für alle, nie eine Paywall):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 Regeln** = `((32.0 − 4.0) MB × 1.048.576) / 9.0 B/Regel` — ein Ziel von 32 MB unter der NE-Grenze von ~50 MiB. Konfigurationen über dem Budget werden deterministisch abgelehnt, statt den Tunnel ins Jetsam laufen zu lassen.
- **Stufen-Obergrenze (`FeatureLimits`):** **Kostenlos 500K Regeln / Plus 2M Regeln**, was unterhalb der Geräte-Schutzbarriere greift. Das ersetzte die alte **Anzahl**-Obergrenze für aktivierte Listen (kostenlos 3 / bezahlt 10) — Obergrenzen für die Listenanzahl sind veraltet.

> **Standard-aktiviert-Vorbehalt (Code gewinnt):** Die ausgelieferten kostenlosen Standards sind **Block List Project Phishing + Scam** (`OnboardingDefaults.lavaRecommendedDefaults`). Sie werden auf dem Gerät aus dem `defaultEnabled`-Flag jeder geprüften Quelle abgeleitet (`BlocklistSource.recommendedDefaultSourceIDs`), was die Quelle der Wahrheit auf dem Gerät ist und die Spalte `default_enabled` im Backend-Katalog spiegelt. Plan-/Katalogtext, der sagt "Block List Basic ist der einzige Standard", ist für das Gerät falsch (intern verfolgt).

### C. Backup (Zero-Knowledge, optional) — Umgesetzt {#c-backup-zero-knowledge-opt-in-implemented}

Optional, kontogebunden und die einzigen Nutzerdaten, die im Backend landen — als **undurchsichtiger Chiffretext**.

1. Der Nutzer meldet sich optional an (nur Apple oder Google; **E-Mail/Passwort ist Verworfen**) über natives `id_token`, das bei Supabase Auth getauscht wird (`grant_type=id_token`, gehashte Nonce). Nur die daraus entstehende Supabase-Sitzung wird gespeichert, gerätelokal, im Keychain.
2. **`BackupConfigurationPayload`** setzt einen minimierten Klartext zusammen (aktivierte Blocklist-IDs, erlaubte/blockierte Domains, Resolver-Einstellungen, Einstellungen für lokale Logs, LavaGuard-Ledger). Es **schließt** `isPaid`, QA, Diagnose und vollständige Blocklisten **aus**.
3. **`ZeroKnowledgeBackupEnvelope`** versiegelt ihn mit **AES-256-GCM** unter einem zufälligen 32-Byte-Payload-Schlüssel; dieser Schlüssel wird über **PBKDF2-HMAC-SHA256 (210k Iterationen)** in **Key-Slots** pro Geheimnis verpackt — ein Slot für das Gerätegeheimnis, ein Slot für die unterstützte Wiederherstellung, ein optionaler Passkey-Slot. Der optionale Passkey-Slot wird mit einer **WebAuthn-PRF / `hmac-secret`**-Ausgabe eines Authentifikators verpackt (HKDF-abgeleitet); diese Ausgabe verlässt nie den Client, also ist der Passkey-Slot echtes Zero-Knowledge — kein vom Server gehaltener Wert entpackt ihn (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** lädt **nur Chiffretext + nicht-geheime Metadaten** direkt über PostgREST zu Supabase `user_backups` hoch, abgegrenzt durch **RLS** pro Nutzer. (Es gibt keine Worker-Upload-Route; der Worker berührt `user_backups` nur, um es bei einer Kontolöschung zu löschen.)
5. **Wiederherstellung:** nahtlose Wiederherstellung auf demselben Gerät über den Slot fürs Gerätegeheimnis; geräteübergreifend über den **8-Wort-CVCV-Wiederherstellungscode** (~105 Bit) kombiniert mit einem vom Server gehaltenen Recovery-Anteil per SHA256 (Zwei-Faktor — keine Hälfte entschlüsselt allein); oder, wenn ein Passkey-Slot versiegelt wurde, über die client-seitige WebAuthn-PRF- / `hmac-secret`-Ausgabe (kein vom Server gehaltener Wert beteiligt). Der Server registriert nie Passkeys, stellt nie WebAuthn-Challenges aus und speichert nie ein Recovery-Geheimnis.

Siehe [Konten & Backup](./accounts-and-backup.md).

### D. Steuerungsebene App ↔ Extension — Umgesetzt {#d-app-extension-control-plane-implemented}

Drei Prozesse (App, Tunnel, Widget) koordinieren sich über die App Group `group.com.lavasec`:

- **Steuerung = NETunnelProviderSession-Provider-Nachrichten**, **nicht** Darwin-Benachrichtigungen. `AppViewModel` kodiert ein `LavaSecProviderMessage {kind, operationID}` und ruft `session.sendProviderMessage` auf; das `handleAppMessage` des Tunnels verzweigt nach dem Kind (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Gemeinsame Dateien** tragen Regeln/Konfiguration/Zustand (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **gemeinsame UserDefaults-Stores** (`ProtectionSessionStore` / `ProtectionPauseStore`) tragen Sitzungs- und Pausenzustand.
- **`LavaProtectionCommandService`** führt Live-Activity-/AppIntent-Befehle zum Pausieren/Fortsetzen unter einem `flock`-Dateilock mit Revisions-Dedup und Ablehnung bei nötiger Authentifizierung aus; **Neu verbinden umgeht das**, um den Tunnel direkt neu zu starten (`startVPNTunnel`).
- **Connect-On-Demand** wird erst *nachdem* der Tunnel als verbunden bestätigt ist aktiviert, nie bei der Profilinstallation — damit ein frisch installiertes Onboarding-Profil keinen nicht-abschaltbaren Tunnel hochfahren kann.

Siehe [iOS-Client](./ios-client.md).

## 6. Vertrauensgrenzen & datenschutzfreundliches Design {#6-trust-boundaries-privacy-preserving-design}

| # | Grenze | Was sie überquert | Was bewusst NICHT |
|---|---|---|---|
| 1 | **Gerät ↔ öffentlicher DNS-Resolver** | Erlaubte DNS-Anfragen (verschlüsselt: DoH3/DoT/DoQ, oder einfaches IP) gehen an den vom Nutzer gewählten Resolver. | Lava sieht nie den Anfragestrom; es ist auf diesem Pfad gar nicht dabei. |
| 2 | **Gerät ↔ Upstream-Blocklist-Hosts** | Das Gerät lädt die Bytes der Liste direkt von `source_url` herunter. | Lava proxyt, spiegelt oder speichert nie Bytes von Drittanbieter-Blocklisten. |
| 3 | **Gerät ↔ lavasec-api Worker** | Lesen von Katalog-**Metadaten**; optionale anonyme Fehlerberichte; Berechtigungs-Spiegel; Kontolöschung. | Keine DNS-Anfragen, kein Surfverlauf, keine Klartext-Einstellungen. |
| 4 | **Gerät ↔ Supabase** | Optionales **verschlüsseltes Backup-Envelope** (nur Chiffretext, PostgREST unter RLS); Kontozeilen. | Der Server kann das Backup ohne ein vom Nutzer gehaltenes Geheimnis nicht entschlüsseln. |
| 5 | **App ↔ Tunnel-Extension** (auf dem Gerät) | Provider-Nachrichten + App-Group-Dateien/-Defaults. | Der Tunnel schlägt beim Kaltstart ohne wiederverwendbaren Snapshot **sicher** (closed) fehl. |

**Datenschutzfreundliche Designprinzipien, gegründet auf dem oben Gesagten:**

- **Filterung zuerst lokal.** Die Entscheidungs-Engine und der Resolver laufen innerhalb der NE-Extension auf dem Gerät. Das Backend ist von Bauart her nur Metadaten — es gibt keine Tabellen für routinemäßige DNS-Anfragen oder Telemetrie pro Domain.
- **Kein Konto nötig für Schutz.** Der Kernschutz ist für immer kostenlos; Authentifizierung und Backup sind strikt optional.
- **Verteilung nur über die Quell-URL.** Entkoppelt Lava von den Bytes der Drittanbieter-Listen (GPL-/IP-Konformität + App-Review-Sicherheit) und hält eine CI-Schutzbarriere am Laufen, die "kein Spiegel-Code, keine Lava-Artefakt-URLs, keine R2-Byte-Schreibvorgänge" durchsetzt.
- **Zero-Knowledge-Backup im Ruhezustand.** Client-seitiges AES-256-GCM; der Server hält Chiffretext + KDF-Metadaten + einen Recovery-Anteil, nie den Klartext, den Wiederherstellungscode oder den entpackten Schlüssel. Der optionale Passkey-Slot wird mit einer client-seitigen WebAuthn-PRF- / `hmac-secret`-Ausgabe verpackt, also ist auch er Zero-Knowledge — kein vom Server gehaltener Wert entpackt ihn.
- **Gerätelokale Geheimnisse.** Das Material zum Entsperren des Backups nutzt `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — nicht über iCloud synchronisiert, nicht in Geräte-Backups.
- **Service-Rollen-Isolation.** `bug_reports`, `mirror_events` und `qa_developers` sind den anon/authenticated PostgREST-Rollen entzogen; nur der Worker (Service-Rolle) berührt sie.
- **Sicherheit steht nie zum Verkauf.** Eine Zahlung schaltet **nur Anpassung** frei. Sie umgeht nie die nicht-zulässige **Schutzbarriere**, deren Integrität durch akzeptierte SHA256-Quell-Hashes durchgesetzt wird (nicht durch eine Serversignatur). Die Reihenfolge ist überall gleich: **Schutzbarriere > lokale Erlaubnisliste (Erlaubte Ausnahmen) > Blockliste > Standard-Erlauben.**

## 7. Docs zu den einzelnen Komponenten {#7-per-component-docs}

> Das sind die Schwester-Dokumente im Architektur-Doc-Set. Die DNS-Filter-Engine und der Blocklist-Katalog werden zusammen in einer Datei dokumentiert.

- [iOS-Client](./ios-client.md) — Targets, App Group, Steuerungsebene, Schutzzustands-Modell, Onboarding, Live Activity.
- [DNS-Filterung & Blocklisten](./dns-filtering-and-blocklists.md) — Filter-Snapshot, Entscheidungsreihenfolge, Resolver-Transporte (DoH3/DoT/DoQ), Speicherbudget, mmap; dazu das Nur-Quell-URL-Katalogmodell, der Katalogabruf, das lokale Parsen/Normalisieren, der Filter für geschützte Domains und das Stufen-Budget.
- [Konten & Backup](./accounts-and-backup.md) — Apple-/Google-Authentifizierung, Zero-Knowledge-Envelope, Key-Slots, Wiederherstellungscode, client-seitige Passkey-Wiederherstellung per WebAuthn-PRF.
- [Backend & Daten](./backend-and-data.md) — lavasec-api + lavasec-email Worker, Supabase-Schema + RLS, R2/D1, Deployment.

## 8. Status-Legende {#8-status-legend}

Dieses Doc-Set nutzt ein einziges Status-Vokabular. Der **Lane-Ordner ist der maßgebliche Status**; veraltetes Frontmatter in einem Plan ist ein Doc-Bug, kein Status. **Code überschreibt Pläne.**

| Status | Bedeutung | Plan-Lane | Code |
|---|---|---|---|
| **Umgesetzt** | Ausgeliefert und im Code bestätigt | `plans/implemented/` | vorhanden & verdrahtet |
| **In Arbeit** | Wird aktiv gebaut; teilweise gelandet | `plans/inflight/`, `plans/under_review/` | teilweise vorhanden |
| **Geplant** | Entworfen, nicht gebaut | `plans/backlog/` | nicht vorhanden |
| **Verworfen** | Abgelehnt oder zurückgenommen | `plans/dropped/` (oder zurückgenommener Commit) | nicht vorhanden / entfernt |

**Status der auf dieser Seite erwähnten Dinge:**

- **Umgesetzt:** die vier iOS-Targets + App Group; die Steuerungsebene über Provider-Nachrichten; DNS-Filterung auf dem Gerät mit DoH3/DoT/DoQ/IP-Transporten; Katalogabruf nur über die Quell-URL + lokales Parsen; Budget der Filterregeln (Kostenlos 500K / Plus 2M) + ~3,26M Geräte-Schutzbarriere; mehrseitiges Onboarding; Passcode-/Biometrie-Sicherheit; eine einzelne deduplizierte Live Activity; Zero-Knowledge-Backup; Apple- + Google-Authentifizierung; Kontolöschung; Berechtigungs-Spiegelung; QA-Probes; die Token-Schicht `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), inklusive des Tiefenmodells `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), der Modifier `.lavaTier(_:)` / `.lavaTierMetadata()`, die in repräsentative Oberflächen eingebunden sind (z. B. `SettingsView`), und die Tokens `dangerRed` und `LavaSpacing` — festgehalten durch `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **In Arbeit:** das weitere Ausrollen der Design-System-Token-Schicht über mehr Oberflächen (das Tiefenmodell `LavaTier` und die Token-Schicht sind ausgeliefert — siehe unten — aber ein eigenes `LavaColorRole` ist noch nicht vorhanden, also lösen sich Akzente noch zu rohen Farben auf).
- **Geplant:** das Lava Guard-Easter-Egg-Minispiel; zusätzliche Maskottchen-Ausdrücke (das Maskottchen hat genau **7** Zustände); voll produktionsreife Passkey-Wiederherstellung auf physischen Geräten (Associated Domains / AASA); server-seitige erneute Verifizierung der App-Store-JWS (`verification_status` ist `client_verified_storekit`); ein eigenes `LavaColorRole`-Token, damit sich Design-System-Akzente über eine semantische Rolle statt über rohe Farben auflösen.
- **Verworfen:** Wiederverwendung von DoQ-Verbindungen (frische Verbindungen pro Anfrage); E-Mail-/Passwort-Anmeldung (nur Apple + Google); das GPL-Roh-R2-Spiegel-Design (abgelöst durch Nur-Quell-URL).
