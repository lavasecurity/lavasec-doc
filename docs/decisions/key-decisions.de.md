---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Wichtige Designentscheidungen

> Zielgruppe: Entwickler und Führungsebene. Das hier ist die ADR-artige Aufzeichnung der tragenden Designentscheidungen hinter Lava Security – also die, die die Architektur, das Datenschutzversprechen oder die Produktgrenzen geprägt haben, und besonders die, die ausprobiert und wieder zurückgenommen wurden. Jeder Eintrag nennt die **Entscheidung**, ihren **Kontext**, die **Begründung** und einen **Status** aus der Status-Legende des Projekts (Übernommen / Zurückgenommen / Ersetzt / Vorgeschlagen).
>
> **Der Code entscheidet.** Wo ein Plan und der ausgelieferte Code auseinandergehen, folgt diese Aufzeichnung dem Code und benennt die Abweichung direkt vor Ort.

**Status-Legende (auf die Status-Spuren des Doku-Sets abgebildet):**

| Status hier | Bedeutung der Doku-Set-Spur |
|---|---|
| **Übernommen** | Umgesetzt – ausgeliefert und im Code bestätigt |
| **Zurückgenommen** | Verworfen – gebaut, dann entfernt/zurückgenommen |
| **Ersetzt** | Eine frühere Entscheidung, abgelöst durch eine spätere |
| **Vorgeschlagen** | Geplant – entworfen, empfohlen oder festgehalten, aber in diesem Tree noch nicht umgesetzt |

Weiterführendes: das Modell der Katalogverteilung in [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) und [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); das ausgelieferte Verhalten in [`../product/features.md`](../product/features.md). Die zukunftsgerichtete Ausrichtung steht in der internen Roadmap.

---

## 1. DNS-Filterung direkt auf dem Gerät über `NEPacketTunnelProvider` {#1-on-device-dns-filtering-via-nepackettunnelprovider}

**Entscheidung.** DNS wird **lokal auf dem Gerät** über einen `NEPacketTunnelProvider`-Pakettunnel gefiltert (`LavaSecTunnel`, `com.lavasec.app.tunnel`), statt über `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` oder einen Safari-Content-Blocker.

**Kontext.** Das Produkt ist ein datenschutzorientierter Filter für nicht-technische Nutzer (Eltern, ältere Menschen), der über den Consumer-App-Store ausgeliefert wird, ganz ohne Konto. Die konkurrierenden NetworkExtension-Provider und die verwalteten DNS-APIs sind auf betreute / per MDM verwaltete Geräte beschränkt oder decken nicht das gesamte DNS einer App ab, und ein Modell auf Resolver-Seite würde den Domainstrom des Nutzers vom Gerät wegleiten.

**Begründung.** Der Pakettunnel ist der einzige Provider, der (a) auf nicht verwalteten Consumer-Geräten funktioniert und (b) jede DNS-Entscheidung direkt auf dem Gerät treffen lässt – das ist die Grundlage des Datenschutzversprechens: *Die gesamte DNS-Filterung passiert auf dem Gerät; Lava leitet dein Surfen nie über eigene Server und bekommt nie den Strom der Domains zu sehen, die du besuchst.* Der Preis, den wir dafür in Kauf nehmen, ist die iOS-Grenze von **~50 MiB Speicher pro Extension**, unter der der Tunnel bleiben muss – eine Einschränkung, die mehrere der weiter unten stehenden Entscheidungen prägt.

**Status.** **Übernommen** (grundlegend; seit dem ersten Prototyp im Code).

---

## 2. Verteilung der Blocklisten nur über die Quell-URL {#2-source-url-only-blocklist-distribution}

**Entscheidung.** Lava veröffentlicht nur die **URL der vorgelagerten Blockliste plus akzeptierte Hashes**; das Gerät holt sich die **Bytes** der Liste direkt von jeder `source_url` und parst, normalisiert, dedupliziert und filtert dann lokal. Lava speichert, spiegelt, transformiert oder liefert **niemals** Blocklisten-Bytes von Drittanbietern aus. Der Worker schreibt nur **Metadaten**-JSON des Katalogs nach R2 (`raw_r2_key`/`normalized_r2_key` sind null).

**Kontext.** Der frühere Entwurf spiegelte die rohen Blocklisten-Bytes in R2, damit die Rechtsabteilung die Verteilung prüfen konnte. Viele vorgelagerte Listen (HaGeZi, OISD) stehen unter GPL-3.0, das Hosten ihrer Bytes würde Lava also zu einem Weiterverteiler von GPL-Daten machen.

**Begründung.** Lava als lokale Filter-Engine / User Agent zu behandeln – und nicht als Verteiler von Blocklisten – minimiert die Berührungspunkte mit der GPLv3-Weiterverteilung und mit dem App Review. Das Gerät holt sich jede Liste über TLS direkt von ihrer kuratierten `source_url` und parst sie lokal unter strengen Größen-/Regelobergrenzen; Community-Listen werden so akzeptiert, wie sie ausgeliefert werden (die `accepted_source_hashes` des Katalogs sind beratend, kein hartes Gate – ein einzelner fest verankerter Hash kann eine sich schnell rotierende vorgelagerte Quelle nicht nachhalten und führte nur zu falschen Ablehnungen), während Lavas Bedrohungs-Schutzbarriere-Stufe hash-verankert bleibt. Die Herkunft wird am Katalog erzwungen (eine Änderung der `source_url` muss eine neue `list_id` verwenden), nicht durch ein Hash-Gate auf dem Client. Jeder geparste Regelsatz läuft außerdem durch einen Filter für geschützte Domains, damit eine vorgelagerte Liste keine Domains von Lava/Apple oder Identitätsanbietern blockieren kann. Das Modell wird in der CI durch `check-gpl-blocklist-distribution.sh` erzwungen (kein Spiegel-Code, keine von Lava gehosteten Artefakt-URLs, keine GPL-Quellen standardmäßig aktiv, keine Byte-Schreibvorgänge nach R2).

**Status.** **Übernommen**, und das hat den aufgegebenen R2-Rohspiegel-Plan **ersetzt** (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, Kopfzeile „Superseded by the source-url-only implementation"). Siehe [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Verschlüsselte Resolver-Transporte (DoH / DoH3 / DoT / DoQ) {#3-encrypted-resolver-transports-doh--doh3--dot--doq}

**Entscheidung.** Wir liefern vier verschlüsselte vorgelagerte Transporte neben einfachem DNS und einer Geräte-DNS-Ausweichoption aus, ausgelagert in LavaSecCore: **DoH** (URLSession), **DoH3** (DoH mit Vorzug für HTTP/3), **DoT** (gepoolte `NWConnection`s, bis zu 4 pro Endpunkt, mit Auffrischung bei Veralten durch Leerlauf und einem Wiederholversuch mit frischer Verbindung) und **DoQ** (DNS-over-QUIC). Routing, Herabstufung auf einfaches DNS, Failover pro Endpunkt mit einem Backoff-Gate und die Geräte-DNS-Ausweichoption liegen im `ResolverOrchestrator`.

**Kontext.** Unblockierte Anfragen im Klartext an einen Resolver weiterzuleiten, gibt genau den Domainstrom preis, den das Modell auf dem Gerät schützen soll. Die Transporte wurden Schritt für Schritt gebaut (DoH → DoH3 → DoT → DoQ).

**Begründung.** Ein verschlüsselter vorgelagerter Transport hält unblockierte Anfragen Ende-zu-Ende privat. **DoH3** ist rein beobachtend benannt – `assumesHTTP3Capable=true` wird gesetzt und das ausgehandelte Protokoll beobachtet, und die Oberfläche kennzeichnet `DoH3` (ohne Schrägstrich) **nur, wenn tatsächlich eine h3-Aushandlung beobachtet wird**, nie versprochen, denn h3 ist pro Verbindung nur ein Best-Effort, und eine fest behauptete Angabe würde das Verhalten hinter UDP-blockierenden Firewalls übertreiben. Das DoT-Pooling mit Leerlauf-Auffrischung war eine direkte Reaktion darauf, dass Cloudflare im Leerlauf liegende DoT-Verbindungen klammheimlich schloss.

**Status.** **Übernommen** (alle vier Transporte vorhanden und verdrahtet).

---

## 4. DoQ-Verbindungswiederverwendung – gebaut, am Gerät getestet, zurückgenommen {#4-doq-connection-reuse--built-device-tested-reverted}

**Entscheidung.** QUIC-Verbindungen für DoQ **nicht** wiederverwenden. `DoQTransport` öffnet **pro Anfrage eine frische QUIC-Verbindung**; der 4-Spuren-Pool sorgt für Parallelität, nicht für Wiederverwendung des Handshakes.

**Kontext.** RFC 9250 bildet jede DNS-Anfrage auf ihren eigenen QUIC-Stream ab, echte Wiederverwendung braucht also die Multi-Stream-API `NWConnectionGroup`/`openStream`, die es **erst ab iOS 26.0** gibt, während die Mindestversion bei iOS 17 liegt. Ein auf iOS 26 begrenzter Wiederverwendungspfad wurde trotzdem umgesetzt (Debug+Release gegen das Xcode-26-SDK kompiliert) und **auf einem Gerät mit iOS 26.5** gegen AdGuard DoQ **getestet**.

**Begründung.** Der Wiederverwendungspfad scheiterte am Gerät bei jedem Versuch (`openStream`/`receive` warfen Fehler, dann lief die Ausweichoption in „Socket is not connected") und schnitt **unterm Strich schlechter** ab als die Basis mit einer Anfrage pro Verbindung (Kontrolle: 34 Handshakes / 35 Anfragen, alle erfolgreich). Das bestätigte empirisch die Empfehlung von Apple DTS, „mit QUIC im neuen Network-Framework noch zu warten", also wurde die Arbeit zurückgenommen statt ausgeliefert; nur die Doku und die Begründung im Guard-Test behalten den Befund, damit es nicht erneut versucht wird, bevor die API reif ist.

**Status.** **Zurückgenommen** (verschoben, bis die Mindestversion iOS 26 erreicht). Beschreibe DoQ als frische Verbindungen pro Anfrage.

---

## 5. Ein vereinheitlichendes `DNSResolvingTransport`-Protokoll ablehnen {#5-reject-a-unifying-dnsresolvingtransport-protocol}

**Entscheidung.** Die Resolver-Transporte **nicht** unter einem einzigen `DNSResolvingTransport`-Protokoll vereinheitlichen; die closure-basierte Naht `ResolverOrchestrator.Executors` beibehalten.

**Kontext.** Ein Refactor (Issue 407) schlug ein Protokoll über alle Transporte vor.

**Begründung.** Die Transporte sind zu unterschiedlich – asynchrone verschlüsselte Executors (DoH/DoT/DoQ) gegenüber synchronen Mehradress-Transporten für einfaches DNS und Geräte-DNS – ein vereinheitlichendes Protokoll wäre also eine schlechtere Abstraktion als die bestehende einsetzbare Closure-Naht, die die Wire-Ausführung schon jetzt testbar hält.

**Status.** **Zurückgenommen** / wird nicht umgesetzt (als schlechte Abstraktion abgelehnt).

---

## 6. Verschlüsseltes Backup nach dem Zero-Knowledge-Prinzip (passwortlos, Passkey-Ausnahme vermerkt) {#6-zero-knowledge-encrypted-backup-passwordless-passkey-exception-noted}

**Entscheidung.** Ein **minimierter** Einstellungs-Payload wird clientseitig gesichert: AES-256-GCM versiegelt ihn unter einem zufälligen 32-Byte-Payload-Schlüssel, der über PBKDF2-HMAC-SHA256 (**210.000** Iterationen in Produktion) in **Schlüssel-Slots** pro Geheimnis eingewickelt wird. Nur Chiffretext plus nicht-geheime Metadaten landen in der Supabase-Tabelle `user_backups` (RLS pro Nutzer). Der ausgelieferte Ablauf ist **passwortlos**: Slot mit Gerätegeheimnis (gerätelokaler Keychain) + Slot für die unterstützte Wiederherstellung + optionaler Passkey-Slot.

**Kontext.** Optionale Konto-Anmeldung (nur Apple + Google) ermöglicht das geräteübergreifende Wiederherstellen der Einstellungen. Der Server darf die Sperrlisten, erlaubten Domains, die Resolver-Wahl oder andere Einstellungen eines Nutzers niemals lesen können.

**Begründung.** Klartext und entschlüsselnde Geheimnisse gibt es nur auf dem Gerät; der Server hält pro Nutzer einen einzigen undurchsichtigen Umschlag. Die unterstützte Wiederherstellung ist bewusst zweifaktorig – `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (NUL-getrennte Eingabe) braucht **beides**, den vom Server gehaltenen Anteil und den 8-Wort-Wiederherstellungscode des Nutzers (~105 Bit), keine Hälfte allein entschlüsselt also. Das Material zum Entsperren liegt gerätelokal (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **nicht** im synchronisierbaren iCloud-Keychain – eine Datenschutz-Härtung, die das synchronisierbare Design des ursprünglichen Plans umgekehrt hat. Der **Passkey-Slot ist ebenfalls echt Zero-Knowledge**: Er wird mit einer WebAuthn-**PRF / `hmac-secret`**-Authenticator-Ausgabe (per HKDF-SHA256 abgeleitet) eingewickelt, die den Client nie verlässt, kein vom Server gehaltener Wert kann ihn also auswickeln. Es gibt keine Passkey-Tabelle mit Service-Rolle und kein Worker-Gate für WebAuthn-Assertions – das frühere serverseitig kontrollierte Passkey-Design wurde verworfen, womit jeglicher serverseitige Passkey-Zustand entfernt wurde (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Status.** **Übernommen** (passwortloses Modell, unterstützte Wiederherstellung und ein per PRF abgeleiteter Zero-Knowledge-Passkey-Slot, alles im Code). Den Passkey zu einem vollständig produktionsreifen, auf physischen Geräten wiederherstellbaren Faktor zu machen (Associated Domains / AASA-Hosting für das PRF-Modell) ist **Vorgeschlagen** (Backlog).

---

## 7. Fail-closed Connect-On-Demand {#7-fail-closed-connect-on-demand}

**Entscheidung.** Eine `NEOnDemandRuleConnect`-Regel hinzufügen, damit ein vom Betriebssystem gestoppter Tunnel automatisch neu startet, mit **fail-closed** als sicherem Standard: Wenn es keinen wiederverwendbaren Filter-Snapshot gibt, blockiert der Tunnel allen Verkehr, statt ihn ungefiltert durchzulassen. On-Demand wird **vor jedem Stopp deaktiviert**, damit das VPN abschaltbar bleibt.

**Kontext.** iOS stoppte den Tunnel klammheimlich (Grund 17), ohne dass etwas ihn ~45 Minuten lang neu startete, sodass Nutzer ungeschützt waren. On-Demand naiv zu aktivieren macht das VPN unmöglich abschaltbar, und ein fail-open-Standard würde während der Lücke Verkehr durchlassen.

**Begründung.** On-Demand schließt die Lücke des stillen Stopps; das Deaktivieren-vor-dem-Stopp bewahrt die Fähigkeit des Nutzers, den Schutz auszuschalten; fail-closed sorgt dafür, dass die Lücke sicher und nicht still ungefiltert ist, wiederhergestellt durch `reconcileTunnelSnapshotAfterLaunch`. Die Änderung hatte Nebenwirkungen – On-Demand löste während des Onboardings erneut die Systemabfrage „VPN-Konfigurationen hinzufügen" aus – was eine Korrekturkette über mehrere Commits anstieß: On-Demand bei der Installation nicht mehr aktivieren, Start und Schutz-Wiederherstellung an den Abschluss des Onboardings koppeln und eine **geerbte/verwaiste Konfiguration durch Entfernen neutralisieren** (`removeFromPreferences`, stillschweigend) statt durch Speichern von `on-demand=false` (`saveToPreferences` zeigte die Abfrage erneut).

**Status.** **Übernommen** (On-Demand-Neustart plus die Onboarding-/fail-closed-Korrekturkette).

---

## 8. Modularer VPN-Refactor und die Disziplin gegen Hitze-Regressionen {#8-modular-vpn-refactor-and-the-heat-regression-discipline}

**Entscheidung.** Den VPN-Pfad neu strukturieren (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) für ein cache-first-Einschalten, beschränkt-parallelen Abruf und Flap-Coalescing – und dabei Akku/Latenz als Produktanforderungen mit ausdrücklichen p50/p95-Zielen und Profiling **auf dem Gerät** (nicht im Simulator) behandeln.

**Kontext.** Einschalten / Aktualisieren / Pausieren / Fortsetzen waren langsam. Während des Refactors trat eine Hitze-Regression auf (134 % CPU, hoher Energieverbrauch, heißes Telefon). Ein großes Agent-Panel widerlegte zunächst die vermutete Ursache anhand von Belegen vor der Regression; eine Live-Aufzeichnung am Gerät bestätigte sie dann.

**Begründung.** Die wahre Ursache war eine sich selbst erhaltende `NEVPNStatusDidChange`-Refresh-Schleife – eine Coalescing-Schleife, die sich endlos neu scharf stellte (~370 Ereignisse/s, Main-Thread ~100 %, `vpn-debug-log.jsonl` auf ~180–210 MB angewachsen), nachdem ein drop-reentrant-Guard ersetzt worden war. Die Korrektur liest den gecachten Manager-Zustand und begrenzt die Schleife. Das Geräte-Artefakt vorher/nachher im Plan selbst hält fest, wie das warme Einschalten (`action.turnOn`) von **2.722 ms → 287 ms** auf einem iPhone 15 Pro fiel; eine separate, spätere Untersuchung von Verbesserungschancen nach der Modularisierung maß den warmen Pfad mit **112 ms** (Decode 51 + managerSetup 57) auf demselben Gerät. Die Episode setzte den Maßstab: Strukturelle Refactors pausieren, bis eine gemessene Hitze-Regression eingegrenzt ist, und thermische/Akku-Ergebnisse aus dem Simulator werden als bedeutungslos verworfen.

**Status.** **Übernommen** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Eine Untersuchung nach der Modularisierung führt `PacketTunnelProvider` und `AppViewModel` weiter als bekannte, noch überlebende Gott-Objekte.

---

## 9. Budget für Filterregeln statt einer Obergrenze für die Listenanzahl {#9-filter-rules-budget-instead-of-a-list-count-cap}

**Entscheidung.** Die Stufen über ein **Budget für Filterregeln** abgrenzen – **Free 500K / Plus 2M** kompilierte Domain-Regeln – nicht über die Anzahl aktivierter Listen. Eine harte **Schutzbarriere von ~3,26M Regeln auf dem Gerät** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3.262.236`) gilt für **alle** und ist **niemals eine Bezahlschranke**. Der kompakte Domain-Blob wird per `mmap` (`.mappedIfSafe`) eingebunden, damit er datei-gestützt bleibt und außerhalb des von jetsam gezählten `phys_footprint` liegt; nur die dekodierten Eintragstabellen kosten residenten Speicher.

**Kontext.** Die alte Obergrenze war eine **Anzahl** von Listen (Free 3 / Bezahlt 10). Eine Liste kann 1K oder 1M Regeln enthalten, die Anzahl war also ein unehrlicher Stellvertreter für die wirklich knappe Ressource – die NE-Speichergrenze von 50 MiB.

**Begründung.** Regeln entsprechen tatsächlichem Speicher, jede Kombination von Listen, die passt, ist also erlaubt. Die maßgebliche Durchsetzung läuft zur Kompilierzeit auf der deduplizierten Vereinigung in `FilterSnapshotPreparationService` (erst die Geräte-Schutzbarriere, dann das Stufenlimit); die Anzeige zur Auswahlzeit in der Oberfläche nutzt eine Summe pro Liste mit einer weichen Obergrenzen-Marge von 1,10. Über dem Budget liegende Konfigurationen werden deterministisch abgelehnt (der Schutz bleibt aus), statt den Tunnel ins jetsam laufen zu lassen.

**Status.** **Übernommen** im Code (`SubscriptionPolicy.swift`), ausgeliefert in **v1.0.0**, was die Obergrenze für die Listenanzahl **ersetzt** hat. Das Regelbudget ist jetzt das lebende Tier-Gate; die Domain-Obergrenzen pro Nutzer wurden bei 1.0 ebenfalls angehoben (Free 25 / Plus 1.000 erlaubte und blockierte Domains). Siehe [`../product/features.md`](../product/features.md).

---

## 10. Pläne als Markdown + einseitiger Linear-Sync {#10-plans-as-markdown--one-way-linear-sync}

**Entscheidung.** Markdown-Dateien in `plans/<lane>/` sind die **Quelle der Wahrheit**; der **Lane-Ordner ist der maßgebliche Status** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Ein Push nach `main` synchronisiert die Pläne **einseitig** nach Linear (Team LAV) und frischt nach dem Anlegen nur Titel/Beschreibung auf; ein separater **manueller, geprüfter** Rückweg zieht Status/Priorität/Lane aus Linear zurück in das Frontmatter des Plans.

**Kontext.** Ein kleines Team braucht einen werkzeug-agnostischen, prüfbaren Planungszustand, der nicht gegen einen Projekt-Tracker arbeitet, und eine autonome Agent-Schleife braucht einen stabilen Ort, um den Planzustand zu lesen und zu schreiben.

**Begründung.** Die Aufteilung der Feld-Hoheit hält die beiden Systeme konfliktfrei – Markdown besitzt den Inhalt, Linear besitzt den Triage-Zustand – ein Push überschreibt also nie die menschliche Triage. Der `dropped/`-Lane hält abgebrochene Pläne aus der Sync-Pipeline heraus, damit sie nicht wieder auftauchen (angelegt, als Allowed Exceptions Guardrails / LAV-5 abgelehnt wurde). Veraltetes Frontmatter in einem Plan ist ein Doku-Fehler, kein Status; der Ordner gewinnt, und wo der Code zeigt, dass ein Feature trotz eines „Backlog"-Frontmatters ausgeliefert wurde (z. B. Kontolöschung), gewinnt der Code.

**Status.** **Übernommen** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; `dropped/`-Lane im Einsatz).

---

## 11. Repo-Aufteilung + Copyleft-Open-Source des Clients {#11-repo-split--copyleft-open-source-of-the-client}

**Entscheidung.** Das Monorepo in Repos pro Komponente aufteilen (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) und den **Erstanbieter-Client unter AGPL-3.0 quelloffen** machen, anstelle von Apache-2.0, auf dem Copyleft-Vorbild von Mullvad/ProtonVPN.

**Kontext.** Entwicklung pro Komponente und ein Quelloffenmachen des Clients. Die Lizenzfrage ist, ob ein Wettbewerber den Client forken, schließen und beim Preis unterbieten könnte.

**Begründung.** Copyleft zwingt Derivate, offen zu bleiben, und verhindert so einen geschlossenen Fork des Clients – eine Haltung „öffentlicher Client, privates Backend/Ops", wobei Backend, Recht und Ops privat bleiben. AGPL-3.0 (statt einfaches GPL-3.0) wurde gewählt, um die Lücke bei der Netzwerknutzung zu schließen. Die bekannte Spannung zwischen GPL und App-Store-Verteilung wird damit aufgelöst, dass Lava selbst unter eigenem Copyright der Verteiler des App-Store-Binaries ist.

**Status.** **Übernommen.** Die Repo-Aufteilung ist **abgeschlossen**: Jede Komponente lebt in ihrem eigenen Repository – der öffentliche `lavasec-ios`-Client beim Tag v0.4.0, plus separate Repositories für Android, die Marketing-Website, Backend/Infrastruktur, Docs und die CI-/Release-Pipeline – und der Abschnitt „Repository layout" in der `README.md` von `lavasec-ios` listet nur die Komponenten-Inhalte dieses Repos (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`), wobei vermerkt ist, dass die Infrastruktur in separaten privaten Repositories lebt. Der Client ist unter **AGPL-3.0** quelloffen: Die `LICENSE` von `lavasec-ios` ist die GNU Affero General Public License v3, und die `README.md` trägt das AGPL-3.0-Abzeichen.

---

## Anhang – weitere festgehaltene Rücknahmen und Ablehnungen {#appendix--other-recorded-reversals-and-rejections}

Diese sind kleiner, waren aber echte Entscheidungen mit einer festgehaltenen Kehrtwende; der Vollständigkeit halber aufgeführt.

| Entscheidung | Begründung | Status |
|---|---|---|
| Eigener DNS Free vs. bezahlt | Positionierung der Monetarisierung; kurz auf Free erlaubt, dann zurück zu „nur bezahlt" | **Zurückgenommen** zu nur bezahlt |
| Anmeldung per E-Mail/Passwort | Passwörter selbst zu verwalten bringt die Last von Zurücksetzen/MFA/Aussperrung/Datenleck/Übernahme, während Apple + Google genügen; eine Umgehung der Wiederherstellung würde Zero-Knowledge brechen | **Zurückgenommen** / nie ausgeliefert (nur Apple + Google) |
| Allowed Exceptions Guardrails (LAV-5) | Vorrang der Schutzbarriere wurde über das einfachere Überarbeiten der Filterlisten-Bearbeitung ausgeliefert; Bezahlung darf die hochsichere Schutzbarriere niemals umgehen | **Zurückgenommen** (`dropped/`-Lane angelegt) |
| Sperrung der TestFlight-Branch-Promotion | Anfängliche Sperrung neu überdacht; ersetzt durch eine geplante Runner-Sperrung nach dem Open-Sourcing | **Zurückgenommen**, ersetzt durch einen Backlog-Plan |
| Steuerkanal App↔Extension | `sendProviderMessage` (`NETunnelProviderSession`) ist der **einzige Steuerpfad App→Tunnel** – er trägt den typisierten, versionierten Zustand und treibt maßgeblich die Run-Loop der Extension. Der frühere `CFNotificationCenter`-Observer auf Extension-Seite feuerte am Gerät nie zuverlässig und wurde **entfernt** (von Source-Introspektions-Tests als abwesend bestätigt). Darwin-Benachrichtigungen überleben nur in der Richtung **Tunnel→App**, als Anstoß bei Zustandsänderung. | **Übernommen** (Provider-Message ist die einzige Steuerung App→Tunnel; Darwin ist nur Tunnel→App für Zustand) |

> Durchgängige Sicherheitsinvariante, auf die hier überall verwiesen wird: Bezahlung umgeht niemals die hash-validierte, nicht erlaubbare **Schutzbarriere**. Die Vorrangordnung der Entscheidungen ist **Schutzbarriere > lokale erlaubte Domains (Erlaubte Ausnahmen) > Sperrliste > Standard-Erlauben.**
