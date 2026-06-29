---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# DNS-Filterung & Blocklisten

> Zielgruppe: Entwickler. Dieses Dokument beschreibt die DNS-Pipeline auf dem Gerät, den Resolver-Pfad über verschlüsselte Transporte, die Entscheidungslogik der Filterung und das Blocklisten-Katalogmodell, das nur Quell-URLs ausliefert — samt der genauen Zahlen, die der Code durchsetzt. Der Status spiegelt das wider, was im Code tatsächlich passiert. Wenn ein Plan und der Code sich widersprechen, **gewinnt der Code**, und die Abweichung wird direkt vor Ort benannt.

Die gesamte DNS-Filterung passiert auf dem Gerät; Lava leitet dein Surfen nie über eigene Server und bekommt nie den Strom der Domains zu sehen, die du besuchst — das Backend hält nur Katalog-Metadaten, ein undurchsichtiges, pro Nutzer verschlüsseltes Backup und anonymisierte Diagnosedaten, die du freiwillig sendest.

Lava ist **lokale DNS-/Blocklisten-Filterung** und keine Garantie dafür, dass wirklich jede bösartige Domain oder URL blockiert wird.

---

## 1. Die DNS-Pipeline (Umgesetzt) {#1-the-dns-pipeline-implemented}

Die Filter-/Resolve-Engine läuft im **NE / Packet-Tunnel** — der `NEPacketTunnelProvider`-Extension `LavaSecTunnel` (`com.lavasec.app.tunnel`), die ausschließlich DNS abfängt. Die Tunnel-Adressen sind `10.255.0.2` (Tunnel) und `10.255.0.1` (DNS-Server). Der App-Prozess sieht den Query-Verkehr nie; er schreibt nur kompilierte Artefakte in die **App Group** (`group.com.lavasec`) und signalisiert dem Tunnel über NETunnelProviderSession-**Provider-Messages** (keine Darwin-Notifications).

Für jede eingehende DNS-Query durchläuft der Tunnel eine feste **Query-Reihenfolge** in `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **Bootstrap zuerst ist eine harte Invariante.** Eine Query, die den *eigenen* Hostnamen des konfigurierten Resolvers auflöst (den DoH/DoT/DoQ-Endpunkt), darf niemals blockiert oder pausiert werden — sonst könnte der Tunnel verschlüsseltes DNS gar nicht erst hochfahren. Der Dispatcher nimmt lazy Closures, sodass jeder Schritt erst gelesen wird, wenn er drankommt; das erhält den Short-Circuit (kein Snapshot-Read, wenn schon eine Bootstrap-Antwort existiert; kein Pause-Read während des Bootstrappings).
- **temporary pause** leitet nach oben weiter, solange eine vom Nutzer gestartete Pause-TTL aktiv ist.
- **filter** prüft die Domain gegen den kompilierten Snapshot und leitet sie entweder weiter oder erzeugt eine Block-Antwort.

Eine Query, die den Filter passiert (Aktion `.allow`), wird an den Resolver-Pfad übergeben (§3). Beim Kaltstart ohne wiederverwendbaren Snapshot **fällt der Tunnel geschlossen** aus: Er installiert einen fail-closed-Laufzeit-Snapshot, der allen Verkehr blockiert, statt ungefiltert aufzulösen.

---

## 2. Die Filter-Engine (Umgesetzt) {#2-the-filtering-engine-implemented}

### 2.1 Entscheidungsreihenfolge {#21-decision-precedence}

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) wendet die kanonische Sicherheitsreihenfolge an:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Reihenfolge | Regelsatz | Ergebnis | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

Eine Domain, die die Normalisierung nicht besteht, wird mit dem Grund `.invalidDomain` blockiert (fail-safe). Dieselbe Reihenfolge spiegelt sich in der binären On-Disk-Form (`CompactFilterSnapshot`). Die Schutzbarriere steht bewusst über der lokalen Allowlist: **Eine Zahlung umgeht die nicht aufhebbare Schutzbarriere nie**, und eine Nutzer-Ausnahme kann eine Domain der Schutzbarriere nicht freischalten.

> Hinweis: Im aktuellen Working Tree sind `nonAllowableThreatRules` / `guardrailSources` leer (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); der Reihenfolge-Slot ist verdrahtet und wird durchgesetzt, wird aber noch ohne Schutzbarriere-Einträge ausgeliefert.

### 2.2 Regelspeicherung und die Einheit im Resident Memory {#22-rule-storage-and-the-resident-memory-unit}

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) speichert `exactDomains`- + `suffixDomains`-Sets. Der Abgleich (`containsNormalized`) macht zur Query-Zeit eine exakte Suche plus einen Eltern-Suffix-Durchlauf (`hasSuffix`-artig) — es gibt **keine Subdomain-Subsumption zur Compile-Zeit**. Eine gültige Wildcard-Zeile ist **eine Regel** und ein Eintrag in der Memory-Tabelle. Genau diese Gleichung 1 Zeile = 1 Regel macht die Regelanzahl zur ehrlichen Ressourcen-Metrik (§4).

### 2.3 Kompilierte Snapshot-Formen {#23-compiled-snapshot-forms}

- **`FilterSnapshot`** — der im Speicher kompilierte Filter: `blockRules`, `allowRules`, `nonAllowableThreatRules` und das Resolver-Preset.
- **`CompactFilterSnapshot`** — die binäre, mmap-freundliche On-Disk-Form, die der Tunnel tatsächlich liest (Magic `LSCFSNP1`, `fileVersion 1`). Sie wird per mmap zero-copy geladen (§4.3).

Die App schreibt sowohl `filter-snapshot.json` als auch `filter-snapshot.compact` in die App Group; der Tunnel dekodiert das Compact-Artefakt. Ein **Warm-Startup-Reuse**-Pfad (`FilterArtifactStore`) erlaubt dem Tunnel, das On-Disk-Compact-Artefakt ohne erneutes Kompilieren wiederzuverwenden — abgesichert über einen Identitäts-Fingerprint plus ein atomar geschriebenes Manifest. Die Wiederverwendung wird abgelehnt (datenschutzsicher, nur mit Feldnamen als Grund), wenn sich Resolver-Transport, Katalogabdeckung oder Snapshot-Eingaben ändern.

---

## 3. Verschlüsselte Transporte & der Resolver-Pfad (Umgesetzt) {#3-encrypted-transports--the-resolver-path-implemented}

### 3.1 Transport-Enum {#31-transport-enum}

Nicht blockierte Queries werden an den konfigurierten Upstream-Resolver weitergeleitet. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) hat **fünf** Werte:

| Transport | Rohwert | In der UI angezeigte Annotation |
|---|---|---|
| Device DNS | `device-dns` | *(keine — der Name ist der Transport)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

Eingebaute Presets sind Google, Cloudflare, Quad9, Mullvad (jeweils in den Varianten IP / DoH / DoT) plus Device DNS und Custom. Eigene Resolver akzeptieren einen einfachen IPv4-/IPv6-Server, eine DoH-URL, eine DoT-URL (`tls://` / `dot://`), eine DoQ-URL (`doq://` / `quic://`) oder einen `sdns://`-DNS-Stamp; Benutzernamen/Passwörter und localhost werden abgelehnt. DoT/DoQ verwenden standardmäßig Port `853`; DoH erfordert einen Pfad.

### 3.2 DoH / DoH3 {#32-doh--doh3}

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) führt DoH über `URLSession` aus. Jeder Request entscheidet sich aktiv für HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); Apples Loader fällt nativ auf H2/H1 zurück, also macht das einen erreichbaren Resolver nie unerreichbar. Das ausgehandelte Protokoll wird aus `URLSessionTaskTransactionMetrics.networkProtocolName` gelesen (ALPN: `h3`, `h2`, `http/1.1`).

Die UI annotiert **`DoH3` (ohne Schrägstrich)** — z. B. "Quad9 (DoH3)" — **nur, wenn tatsächlich eine h3-Aushandlung beobachtet wird** (`DoHHTTPVersion.dohAnnotation`); andernfalls zeigt sie `DoH`. DoH3 wird bevorzugt, aber nie versprochen: Das Label ist beobachtend und nur auf den aktuellen Resolver bezogen, wird nie gespeichert (das Übertragen von "bestätigtem DoH3" über einen Neustart hinweg wurde rückgängig gemacht). Requests POSTen `application/dns-message`; Antworten werden auf Content-Type und Länge geprüft, und die Transaktions-ID wird vor dem Zurückschreiben wiederhergestellt.

### 3.3 DoT {#33-dot}

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) nutzt gepoolte `NWConnection`s, **bis zu 4 Verbindungen pro Endpunkt** (`maxConnectionsPerEndpoint = 4`), im Round-Robin, sodass parallele Queries kein Head-of-Line-Blocking erleben. Es behandelt auch **Idle-Staleness**: Anbieter wie Cloudflare schließen ungenutzte DoT-Verbindungen serverseitig (~10 s), ohne das nach außen sichtbar zu machen, also wird eine wiederverwendete Verbindung, die länger als **8 Sekunden** untätig war (`reusedConnectionMaxIdleInterval = 8`), vor dem Senden aufgefrischt, und ein Timeout auf einer wiederverwendeten Verbindung bekommt **genau einen Retry mit frischer Verbindung**.

### 3.4 DoQ — frische Verbindung pro Query {#34-doq--fresh-connection-per-query}

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) hält einen begrenzten Pool von **4 Lanes pro Endpunkt**, aber **jede Query öffnet eine frische QUIC-Verbindung** — ein vollständiger Handshake pro Query. Der 4-Lane-Pool liefert **Nebenläufigkeit, keine Handshake-Wiederverwendung**.

**Status der DoQ-Verbindungswiederverwendung (Verworfen / zurückgestellt).** Die Wiederverwendung wurde geprüft und auf dem Gerät gemessen (34 frische Handshakes über 35 Queries ≈ keine Wiederverwendung), dann als iOS-26-abhängiger Multi-Stream-`NWConnectionGroup`-Pfad umgesetzt, gegen AdGuard DoQ auf dem Gerät getestet und **als unterm Strich nachteilig zurückgenommen** (Stream-Fehler + Fallback-Fehler gegen einen echten Server). RFC 9250 ordnet jede Query ihrem eigenen QUIC-Stream zu, also braucht die Wiederverwendung `NWConnectionGroup`/`openStream`, was **erst ab iOS 26.0** verfügbar ist; die aktuelle Mindestversion liegt bei **iOS 17**. Die Wiederverwendung ist zurückgestellt, bis die Mindestversion iOS 26 erreicht. Eigenes DoQ wird auf Geräten abgelehnt, die es nicht unterstützen ("DNS over QUIC is not supported on this device").

### 3.5 Auflösungs-Policy {#35-resolution-policy}

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) besitzt die Upstream-Policy:

1. **Transport-Routing** nach dem konfigurierten Transport.
2. **Herabstufung auf Plain DNS**, wenn ein verschlüsselter Plan keine Endpunkte hat.
3. **Failover pro Endpunkt** mit einem Backoff-Gate — ein zurückgestellter Endpunkt berührt nie die Leitung (Ergebnis `backed-off`).
4. **Geräte-DNS-Ausweichoption**, wenn der primäre Resolver keine Antwort liefert *und* der Plan es erlaubt (die Plan-Eigenschaft ist `shouldFallbackToDeviceDNS`, abgeleitet aus dem Config-Feld `fallbackToDeviceDNS`); das Ergebnis wird als Geräte-Transport neu annotiert. Die Wire-Ausführung wird hinter Executors injiziert, damit die Policy per Unit-Test prüfbar ist; der Backoff-Zustand bleibt außerhalb der reinen Policy.

---

## 4. Filter-Regel-Budget, NE-Obergrenze und mmap {#4-filter-rules-budget-ne-ceiling-and-mmap}

Die ausgelieferte Tier-Metrik ist das **Filter-Regel-Budget**: die Gesamtzahl der kompilierten Domain-**Regeln**, die ein Nutzer aktivieren kann. Das ersetzte die alte **Anzahl**-Begrenzung aktivierter Listen (kostenlos 3 / kostenpflichtig 10), die ein unehrlicher Stellvertreter war — eine Liste kann 1K oder 1M Regeln haben. Es gibt **zwei Schichten**: eine Geräte-Schutzbarriere für alle und darunter eine Monetarisierungsgrenze je Tier.

### 4.1 Tier-Limits (Umgesetzt) {#41-tier-limits-implemented}

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) ist die maßgebliche Quelle:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Eigene Blocklisten / DNS |
|---|---|---|---|---|
| **Free** | **500.000** | 25 | 25 | Nein |
| **Plus** (`.paid` / `.plus`) | **2.000.000** | 1.000 | 1.000 | Ja |

Das Tier-Limit ist eine Monetarisierungsgrenze und **niemals eine Paywall auf der Geräte-Schutzbarriere**. **Lava Security Plus** schaltet ausschließlich Anpassbarkeit frei — niemals die grundlegende Sicherheit, niemals die Schutzbarriere. Eigene (kostenpflichtige) Blocklisten werden direkt vom Gerät des Nutzers abgerufen, lokal geparst und gecacht und nie über Lava-Server geleitet.

### 4.2 Geräte-Speicher-Schutzbarriere + NE-Obergrenze (Umgesetzt) {#42-device-memory-guardrail--ne-ceiling-implemented}

Der Packet-Tunnel unterliegt der iOS-**Speicher-Obergrenze von ~50 MiB pro Extension** (ein OS-Designlimit pro Extension-Typ für Packet-Tunnel seit iOS 15, nicht RAM-skaliert; es lebt in einer `com.apple.jetsamproperties.{Model}.plist` je Gerätemodell und kann auf älteren Geräten niedriger sein). Wird sie überschritten, löst das Jetsam aus. Es gibt keine API für die Obergrenze, also hält das Budget Sicherheitsabstand unter der Klippe.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) rechnet das aus, in Filter-Regeln (block + allow + guardrail):

| Konstante | Wert |
|---|---|
| `baselineMegabytes` | 4,0 MB (fester Prozess-Overhead, gemessen ≈3,5 MB, aufgerundet) |
| `estimatedBytesPerRule` | 9,0 B dirty resident pro Regel (gemessen ≈8,5 B, aufgerundet) |
| `maxResidentMegabytes` | 32,0 MB (Ziel-Obergrenze, lässt ~10 MB Spielraum unter der beobachteten Jetsam-Klippe von ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1.048.576) / 9 = 3.262.236 Regeln** |

Diese **Geräte-Schutzbarriere von ~3,26 Mio. Regeln** ist die harte Sicherheitsuntergrenze für *jeden* Nutzer, liegt über jedem Abo-Tier und ist **niemals eine Paywall**. Anker-Messung (Gerät "chimmy", 2026-06-13): **789.831 Regeln → 9,9 MB `phys_footprint`**, also ≈ Baseline + Kosten pro Regel.

### 4.3 mmap-Strategie (Umgesetzt) {#43-mmap-strategy-implemented}

Der Compact-Snapshot wird mit `Data(contentsOf:options:[.mappedIfSafe])` geladen (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), und `CompactBinaryReader` gibt zero-copy-Slices zurück. Der mehrere Megabyte große Domain-Text-Blob bleibt **file-backed/clean** und ist vom jetsam-gezählten `phys_footprint` ausgenommen; nur die dekodierten `[Entry]`-Tabellen kosten Resident Memory (~6 B/Regel auf der Platte, ~8,5 B dirty resident). Das hebt die Domain-Obergrenze auf dem Gerät an: Die Resident-Kosten sind die Entry-Tabellen, nicht das ganze Artefakt.

### 4.4 Zweischichtige Durchsetzung (Umgesetzt) {#44-two-layer-enforcement-implemented}

- **Maßgeblich (zur Compile-Zeit).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) setzt das Budget auf der **deduplizierten Vereinigung** aller aktivierten Listen durch. Die Geräte-Schutzbarriere wird **zuerst** geprüft (die harte Untergrenze); das Tier-Limit greift darunter. Über-Budget-Konfigurationen werden deterministisch abgelehnt — `exceedsDeviceMemoryBudget` oder `exceedsTierFilterRuleLimit` —, statt den Tunnel ins Jetsam laufen zu lassen. Der Fehler nennt die beiden größten beitragenden Listen, damit klar ist, wie man es behebt.
- **Hinweisgebend (UI zur Auswahlzeit).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) treibt die Auswahlanzeige über eine **Summe** je Liste mit einem **Soft-Ceiling-Spielraum von 1,10**, der den listenübergreifenden Über-Zählwert von ~7–10 % ausgleicht (die Pro-Liste-Summe überschätzt die deduplizierte Vereinigung).

### 4.5 Der Parser (Umgesetzt) {#45-the-parser-implemented}

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) zählt Regeln wörtlich: Er verwirft Kommentare/Leerzeilen/ungültige Zeilen, normalisiert, dedupliziert exakte Strings innerhalb einer Liste (über ein `Set`) und deckelt bei **`maxRules = 1.000.000`** pro Liste (Standard), mit einer maximalen Zeilenlänge von 4.096 Zeichen. Unterstützte Formate: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (`auto` probiert hosts → dnsmasq → adblock → plain). Eine gültige Zeile = eine Regel = die Speichereinheit.

> **`hosts`-Zeilen mit mehreren Hosts (Parser-Regelversion 2).** Eine `hosts`-Zeile, die eine IP auf mehrere Hosts abbildet (`0.0.0.0 a.com b.com c.com`), gibt jetzt **jeden** Host als eigene Regel aus, nicht nur den ersten; `maxRules` wird **pro Regel** durchgesetzt (nicht pro Zeile), sodass eine Zeile mit mehreren Hosts nahe der Obergrenze nicht überschießen kann. Weil dieselben Upstream-Bytes jetzt mehr Regeln ergeben können, wurde die Regelversion des Parsers von **1 → 2** angehoben, was veraltete `RuleSetCache`-Einträge ungültig macht, die unter dem alten Verhalten (nur erster Host) geparst wurden.

### 4.6 Robustheit von Download & Decode (Umgesetzt) {#46-download--decode-robustness-implemented}

Der Tunnel und der Katalog-Sync laufen innerhalb des NE-Speicherbudgets, daher ist die Listen-Aufnahme gegen feindliche oder fehlerhafte Eingaben gehärtet:

- **Gestreamte Downloads.** `defaultDataFetcher` lädt die Listen-Bytes über `URLSession.download` in eine temporäre Datei (begrenzter Speicher-Peak) mit einer Größenprüfung nach dem Download (`maximumBlocklistBytes`), statt den gesamten Body im RAM zu puffern; ein übergroßer Body löst `BlocklistDownloadSizeLimitExceeded` aus.
- **Obergrenze für Katalog-Metadaten (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes` lehnt einen übergroßen Remote-Katalog vor dem Decode ab, sodass ein feindlicher/MITM-Host keinen OOM-JSON-Decode in der Erweiterung erzwingen kann.
- **Nachsichtiges UTF-8-Decoding.** Ein einzelnes ungültiges UTF-8-Byte lehnt nicht mehr eine ganze Liste ab (was unter Fail-Closed alles DNS blockieren würde); ungültige Bytes werden zu U+FFFD, und nur die betreffende Zeile scheitert an der zeilenweisen Validierung und wird verworfen.
- **Benannte Fehler für eigene Blocklisten.** Eine fehlgeschlagene eigene Liste meldet jetzt `customBlocklistUnavailable(displayName:reason:)` — „Die eigene Blockliste ‚<name>' konnte nicht geladen werden. <warum>" — statt eines rohen `URLError`; ein Abbruch wird als Abbruch weitergereicht, nicht als Download-Fehler.

---

## 5. Blocklisten-Katalog & Standardquellen {#5-blocklist-catalog--default-sources}

### 5.1 Katalogmodell (Umgesetzt) {#51-catalog-model-implemented}

Der **Blocklisten-Katalog** ist die veröffentlichte Liste der verfügbaren Quellen. Der **lavasec-api-Worker** liefert JSON-Metadaten aus einem R2-Bucket unter `GET /v1/catalog` (und `/v1/catalog/:version`); das Gerät holt die eigentlichen Listen-**Bytes** direkt von jeder Upstream-`source_url`. Die iOS-Katalog-Endpunkte sind `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

Auf dem Gerät macht `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`) Folgendes:

1. Holt die Listen-Bytes direkt von `source.sourceURL` und erzwingt dabei eine Größenobergrenze.
2. Berechnet SHA-256 und akzeptiert die Bytes nur, wenn die Prüfsumme in den `accepted_source_hashes` des Katalogs steht.
3. Bei Nichtübereinstimmung fällt es auf den zuletzt funktionierenden lokalen Cache zurück oder **fällt geschlossen aus** (`checksumMismatch`) — es sei denn, die Quelle erlaubt direkte Upstream-Rotation ausdrücklich.
4. Parst/normalisiert/dedupliziert lokal.
5. Filtert jeden geparsten Regelsatz durch `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`), damit eine Upstream-Liste niemals Lava-/Apple-/Identity-Provider-Domains blockieren kann.

Das **Set geschützter Domains** (vor der Aktivierung herausgefiltert): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (alle suffix-abgeglichen). Der Worker wendet beim Berechnen der Metadaten einen gleichwertigen `PROTECTED_SUFFIXES`-Filter an; das Gerät validiert trotzdem nochmal selbst.

### 5.2 Kuratierte Quellen (Umgesetzt) {#52-curated-sources-implemented}

`DefaultCatalog.curatedSources` wird aus dem kanonischen [Blocklisten-Katalog](../legal/blocklist-catalog.md) generiert und führt aktuell **32** Quellen über sieben Kategorien hinweg: Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling sowie Piracy & Torrent. Zu den Quellfamilien gehören The Block List Project, Phishing.Database, HaGeZi, OISD, StevenBlack, AdGuard und 1Hosts.

`guardrailSources` ist leer. GPL-Quellen (HaGeZi, OISD, AdGuard) sind im Katalog sichtbar, aber **opt-in / standardmäßig AUS**; der Worker beschränkt Launch-Sync/-Publish auf `source_url_only` plus die freigegebenen GPL-Präfixe (`hagezi-`, `oisd-`, `adguard-`).

### 5.3 Standardmäßig aktivierte Listen für kostenlose Nutzer (Umgesetzt) {#53-default-enabled-lists-for-free-users-implemented}

Die Free-Standardkonfiguration ist `OnboardingDefaults.lavaRecommendedDefaults`, die **Block List Basic** aktiviert — eine breite, permissiv lizenzierte kombinierte Liste (Werbung + Tracking + Malware + Phishing/Scam) — mit dem Geräte-DNS-Resolver-Preset (`resolverPresetID = DNSResolverPreset.device.id`) und **eingeschalteter** verschlüsselter Geräte-DNS-Ausweichoption (`usesEncryptedDeviceDNSFallback = true`), die zu **Mullvad DoH** routet (`fallbackResolverPresetID = DNSResolverPreset.mullvadDoH.id`): Wenn das geräteeigene DNS hängenbleibt, werden erlaubte Lookups vorübergehend über Mullvad DoH abgewickelt und kehren dann automatisch zum geräteeigenen DNS zurück. (Der schlichte `AppConfiguration()`-Initializer setzt diese Ausweichoption standardmäßig **aus** — sie wird nur durch Annahme der empfohlenen Onboarding-Standardwerte aktiviert.) Das löst das frühere Paar Block List Project Phishing + Scam ab: Die kombinierte Abdeckung von Basic schließt sie ein, und beide bleiben optional auswählbare Listen.

Dieser Free-Standard wird **von `defaultEnabled` erzeugt**, nicht hartcodiert. `blockListProjectBasic` setzt `defaultEnabled: true`, und `DefaultCatalog.recommendedDefaultSourceIDs` wird aus `curatedSources.filter(\.defaultEnabled)` abgeleitet. `defaultEnabled` ist "the single source of truth for the fresh-install default" und spiegelt damit die `default_enabled`-Spalte des Backend-Katalogs. Über `recommendedDefaultSourceIDs` fließt es in `OnboardingDefaults` ein und ist der lebende Mechanismus — kippe das Flag an einer Quelle, um den Standard zu ändern.

> **Maßgebliche Standard-Quelle (eine generierte Spezifikation).** Der Katalog wird aus einer einzigen kanonischen Spezifikation generiert ([Blocklisten-Katalog](../legal/blocklist-catalog.md)), die sowohl den iOS-`DefaultCatalog` als auch den Backend-Seed erzeugt, sodass das Gerät und die ausgelieferten `/v1/catalog`-Metadaten per Konstruktion übereinstimmen. Der Fresh-Install-Standard ist **Block List Basic**, über sein `defaultEnabled: true`-Flag. Das echte Tier-Gate ist das Filter-Regel-Budget von 500K/2M, keine Listenanzahl.

### 5.4 Source-url-only-Verteilmodell für GPL (Umgesetzt) {#54-source-url-only-gpl-distribution-model-implemented}

**Source-url-only** ist das GPL-/IP-konforme Verteilmodell: Lava veröffentlicht nur die Upstream-URL + die akzeptierten Hashes; das Gerät holt und parst die Listen selbst. Lava speichert, spiegelt, transformiert oder liefert **niemals** Drittanbieter-Blocklisten-Bytes aus. Das **ersetzte das aufgegebene R2-Mirror-Design** (der ursprüngliche "raw R2 mirror"-Plan wurde am 2026-05-25 rückgängig gemacht).

Auf der Worker-Seite holt `syncOneBlocklist` jede Upstream-Quelle und normalisiert+hasht sie (berechnet `source_hash`, `normalized_hash`, `entry_count`), schreibt aber `raw_r2_key = null` / `normalized_r2_key = null` — nur die Katalog-JSON-Metadaten landen in R2. `check-gpl-blocklist-distribution.sh` ist das CI-Schutzgitter, das das ganze Modell durchsetzt: kein Mirror-/Transform-Code, keine Lava-Artefakt-/Download-URLs, keine GPL-Quellen standardmäßig aktiviert, keine Worker-R2-Schreibvorgänge von Listen-Bytes, kein "Lava-hosted mirror"-Text, keine gebündelten GPL-`.txt`/`.json` und `source_url_only` ist in Migrationen + Rechtsdokumenten Pflicht.

> **Lizenzhinweis:** Der First-Party-Code von Lava wird unter **AGPL-3.0** ausgeliefert (die `LICENSE`-Datei ist GNU AGPL v3, passend zum README-Badge). Die Drittanbieter-Blocklisten (darunter HaGeZi, OISD und AdGuard) bleiben unter ihren eigenen Upstream-Lizenzen — das Source-url-only-Modell existiert genau deshalb, damit Lava sie nutzen kann, ohne je Copyleft-Listen-Bytes weiterzuverteilen. GPL-3.0 ist hier eine Eigenschaft der Upstream-Listen, nicht der Lava-App.

---

## 6. Statusübersicht {#6-status-summary}

| Bereich | Status |
|---|---|
| DNS-Query-Reihenfolge (bootstrap > pause > filter) | Umgesetzt |
| Filter-Entscheidungsreihenfolge (guardrail > allowlist > blocklist > default-allow) | Umgesetzt |
| Schutzbarriere-Reihenfolge-Slot (verdrahtet; wird noch ohne Einträge ausgeliefert) | Umgesetzt |
| DoH / DoH3 (beobachtendes h3-Label) | Umgesetzt |
| DoT (Pool 4/Endpunkt, 8 s Idle-Refresh, ein frischer Retry) | Umgesetzt |
| DoQ (frische Verbindung pro Query, 4-Lane-Nebenläufigkeit) | Umgesetzt |
| DoQ-Verbindungswiederverwendung | Verworfen / zurückgestellt bis iOS-26-Mindestversion |
| Resolver-Herabstufung + Failover pro Endpunkt + Geräte-DNS-Ausweichoption | Umgesetzt |
| Filter-Regel-Budget (Free 500K / Plus 2M) | Umgesetzt |
| Geräte-Schutzbarriere von ~3,26 Mio. Regeln (Ziel 32 MB unter 50-MiB-NE-Obergrenze) | Umgesetzt |
| Zero-copy-mmap des Compact-Snapshots | Umgesetzt |
| Source-url-only-Katalog + direkter Upstream-Abruf + Hash-Validierung | Umgesetzt |
| Geschützte-Domains-Filter | Umgesetzt |
| Free-Standard = Block List Basic | Umgesetzt (generierter Katalog + iOS-/Backend-Projektionen stimmen überein) |
| Lizenz des First-Party-Lava-Codes | AGPL-3.0 (`LICENSE`); Drittanbieter-Listen bleiben upstream GPL-3.0 |

---

## Siehe auch {#see-also}

- [`../product/overview.md`](../product/overview.md) — Produkt-Einzeiler, Datenschutzversprechen, Tabs.
- Tiers & Monetarisierung (interne Referenz) — Lava Security Plus und das Filter-Regel-Budget als Tier-Metrik.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — die Source-url-only-Compliance-Entscheidung.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — Upstream-Blocklisten-/Resolver-Lizenzen und -Zuschreibungen.
