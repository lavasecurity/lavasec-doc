---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Backend & Daten

> **Zielgruppe:** Backend-Entwickler. **Umfang:** die Server-Ebene — die zwei Cloudflare Workers, das Supabase-Postgres-Schema/RLS/Auth, die Cloudflare-R2- und -D1-Speicher, die komplette HTTP-API-Oberfläche, Konfiguration & Deploy und wie source-url-only serverseitig durchgesetzt wird.
>
> **Maßgebliche Referenz:** Wenn ein Plan und der Code sich widersprechen, **gewinnt der Code** — Abweichungen werden direkt im Text genannt. Status-Labels folgen der Legende des Doku-Sets: **Umgesetzt** (ausgeliefert und im Code bestätigt), **In Arbeit** (teilweise gelandet), **Geplant** (entworfen, noch nicht gebaut), **Verworfen** (abgelehnt oder zurückgenommen).

## 1. Wie das Backend aufgebaut ist {#1-the-shape-of-the-backend}

Das Backend ist bewusst klein und datensparsam gehalten. Es ist eine Kante für Metadaten und Konten, kein Filterdienst. **Die gesamte DNS-Filterung passiert auf dem Gerät; Lava leitet dein Surfen niemals über seine Server und bekommt nie den Strom der Domains zu sehen, die du besuchst — das Backend hält nur Katalog-Metadaten, ein undurchsichtiges, pro Nutzer verschlüsseltes Backup und anonymisierte Diagnosedaten, die du selbst entscheidest zu senden.** Es gibt keine Tabellen für alltägliche DNS-Anfragen oder Telemetrie pro Domain, und ein Konto-Login ist optional und für den Schutz nie nötig.

Die Server-Ebene teilt sich auf zwei Komponenten auf: den Code des Backend-Workers und das DB-Schema.

| Komponente | Rolle |
|---|---|
| **lavasec-api Worker** | Hauptkante: öffentliche Katalog-Lesezugriffe, Admin- + Cron-Blocklisten-Sync & Katalog-Veröffentlichung, anonyme Fehlerberichte, Hilfe-Feedback, Kontolöschung, Spiegelung der App-Store-Berechtigungen, QA-Probe-Pixel, QA-Zugriffsprüfung für Konten, Triage-Promotion für Fehlerberichte |
| **lavasec-email Worker** | Nur-Empfang-Weiterleiter über Cloudflare Email Routing für `@lavasecurity.app` |
| **Supabase Postgres** (ein Supabase-Postgres-Projekt) | Konten, verschlüsselte Backups, Katalog-Metadaten, Tabellen nur für die Service-Rolle; RLS auf jeder öffentlichen Tabelle |
| **Cloudflare R2** (ein Produktions-Bucket, mit einem separaten Preview-Bucket für Staging) | Katalog-Snapshots + der Sync-Cursor; **niemals** Bytes von Drittanbieter-Blocklisten |
| **Cloudflare D1** (die Hilfe-Feedback-Datenbank) | Nur-Anhängen, anonyme Abstimmungen zum Feedback für Hilfe-Artikel |

Der Worker erreicht Supabase über PostgREST (`/rest/v1`) und Auth (`/auth/v1`) mit einer Supabase-Service-Rolle-Zugangsdaten — es gibt kein Supabase-SDK auf dem Server; die Aufrufe sind reines `fetch` über die Helfer `supabase()` / `supabaseAuth()`.

Status: **Umgesetzt**.

## 2. lavasec-api Worker {#2-lavasec-api-worker}

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, ein R2-Binding → der Produktions-Bucket (ein separater Preview-Bucket für Staging), ein D1-Binding → die Hilfe-Feedback-Datenbank, und **zwei Cron-Trigger**: einer, der alle 6 Stunden feuert (Blocklisten-Sync + Katalog-Veröffentlichung), und einer, der alle 2 Minuten feuert (Triage-Promotion für Fehlerberichte). Er läuft unter `api.lavasecurity.app`.

### 2.1 API-Oberfläche {#21-api-surface}

Das Routing ist ein flacher `route()`-Dispatcher. Alles ist **Umgesetzt**, sofern nicht anders vermerkt.

**Öffentlich / nicht authentifiziert**

| Methode & Pfad | Handler | Hinweise |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Liefert `catalog/latest.json` aus R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Liefert `catalog/{version}.json` aus R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (Standard 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anonym, Login optional; nur per Allowlist freigegebene Debug-Felder |
| `POST /v1/help-feedback` | `createHelpFeedback` | Anonyme Artikel-Abstimmung → **D1**, nicht Supabase |

> Der Anhang-Upload (eine frühere Route `PUT /v1/bug-reports/:id/attachment`) wurde **entfernt**; Screenshots und zusätzliche Details laufen über einen von Menschen betreuten Support-Kanal. Der Worker löscht bei der Kontolöschung höchstens noch im Best-Effort-Verfahren alte Anhang-Objekte.

**Konto (Supabase-Access-Token erforderlich)**

| Methode & Pfad | Handler | Hinweise |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Prüft das Access-Token des Nutzers, löscht seine Zeilen + etwaige alte R2-Anhang-Objekte und löscht dann den Supabase-Auth-Nutzer mit der Service-Rolle |
| `GET /v1/account/qa-access` | `accountQAAccess` | Gibt `is_developer` aus der nur per Service-Rolle zugänglichen `qa_developers`-Allowlist zurück |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Schreibt per Upsert eine `entitlements`-Zeile (Plan `lava_security_plus`) aus einem client-verifizierten StoreKit-JWS |

> **Keine `/v1/backup`-Routen.** Die Passkey-gestützte Backup-Wiederherstellung ist jetzt **Zero-Knowledge** und vollständig clientseitig (siehe §4.3 und §5); der Worker hat keine `/v1/backup/*`-Routen und keinen WebAuthn-/Passkey-Code.

**Admin (ein Admin-API-Key über `requireAdmin`)**

| Methode & Pfad | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Die Admin-HTTP-Endpunkte sind durch einen Admin-API-Key abgesichert. Der geplante (Cron-)Sync-Pfad ruft diese HTTP-Routen **nicht** auf — er ruft die Sync-Logik (`syncBlocklistSources`) direkt im `scheduled`-Handler auf.

**QA-Probe-Hosts** — Anfragen an die vier `*.qa-probe.lavasecurity.app`-Hosts (`allowed`/`blocked`/`exception`/`guardrail`) werden noch vor dem Routing kurzgeschlossen und liefern über `getQAProbePixel` ein 1×1-`no-store`-PNG zurück. Diese werden nicht nach Supabase oder R2 geschrieben.

### 2.2 Bindings & Cron {#22-bindings--cron}

- **R2-Binding** — `catalog/latest.json`, `catalog/{version}.json` und der Round-Robin-Cursor `catalog/scheduled-sync-cursor.json`. **Es speichert niemals Bytes von Drittanbieter-Blocklisten.** (Alte Fehlerbericht-Anhang-Objekte werden nur jemals *gelöscht* — im Best-Effort-Verfahren während der Kontolöschung — niemals geschrieben.)
- **D1-Binding** — nur-anhängende, anonyme `article_id`- / `locale`- / `vote`- / `path`-Zeilen; absichtlich von Supabase getrennt gehalten.
- **Cron (`scheduled`)** — der Handler verzweigt anhand der Cron-ID:
  - **Alle 6 Stunden** — synchronisiert **eine** Quelle pro Lauf, im Round-Robin über den R2-Cursor (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), und veröffentlicht dann den Katalog neu. Das Verteilen der Last verhindert, dass alle Upstreams auf einmal beansprucht werden.
  - **Alle 2 Minuten** — führt einen internen Triage-Pfad für Fehlerberichte aus, der neue anonyme Berichte in eine interne Issue-Tracker-Warteschlange befördert und dabei seinen eigenen Wasserstand-Cursor weiterschiebt. Das ist internes Betriebs-Tooling; die Issue-Tracker-/Benachrichtigungs-Kennungen sind Konfiguration, nicht Teil der öffentlichen API.

## 3. Katalog & Durchsetzung von source-url-only {#3-catalog--source-url-only-enforcement}

Das ist der Teil des Backends, der am stärksten auf Lavas Compliance-Haltung zugeschnitten ist, deshalb bekommt er serverseitige Zähne.

### 3.1 Das source-url-only-Modell {#31-the-source-url-only-model}

> **Source-url-only:** GPL-/IP-konformes Verteilungsmodell: Lava veröffentlicht nur die Upstream-URL + akzeptierte Hashes; das Gerät holt und parst die Listen selbst. Lava **speichert, spiegelt, transformiert oder liefert niemals** Bytes von Drittanbieter-Blocklisten.

Jede `blocklist_sources`-Zeile trägt `redistribution_mode`, dessen einziger erlaubter Wert `"source_url_only"` ist. Der Katalog, den das Gerät liest (`/v1/catalog`, `schema_version` 2), teilt die Einträge in `sources[]` und `guardrails[]` auf; jeder Eintrag trägt die Upstream-`source_url` plus `accepted_source_hashes` (SHA-256 + Byte-Größe + Eintragsanzahl + `reviewed_at` + Status `accepted`) — niemals Listen-Bytes. Siehe `formatCatalogEntry`.

> **Verworfen:** Ein früherer Entwurf spiegelte byte-getreue GPL-Listendateien in R2 (der GPL-raw-R2-Compliance-Plan). Er wurde **am 2026-05-25 durch source-url-only abgelöst**. Lava speichert oder liefert keine Bytes von Drittanbieter-Blocklisten mehr. Der Tabellenname `mirror_events` ist ein Überbleibsel aus diesem aufgegebenen Entwurf — er ist jetzt nur noch das Audit-Log für Sync/Veröffentlichung.

### 3.2 Wie der Worker es bei Schreibvorgängen durchsetzt {#32-how-the-worker-enforces-it-on-writes}

Der Sync-Pfad (`syncOneBlocklist`, Admin und Cron) holt jede Upstream-`source_url`, normalisiert/validiert **nur lokal im Worker, um Metadaten zu berechnen** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), schreibt eine `blocklist_versions`-Zeile und veröffentlicht neu. Die Schlüssel für die Byte-Speicherung werden hart auf null geschrieben:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Eine Migration (`20260525000000_add_blocklist_distribution_mode.sql`) hat diese Spalten auf nullable umgestellt und vorhandene Werte auf null gesetzt, sodass die No-Mirror-Haltung auch auf Schema-Ebene durchgesetzt wird. Der veröffentlichte Katalog wird in R2 in **beide** Pfade geschrieben, `catalog/{version}.json` und `catalog/latest.json` (`publishCatalog`).

### 3.3 Normalisierungs-Schutzbarrieren (nur Metadaten) {#33-normalization-guardrails-metadata-only}

Die Worker-seitige Normalisierung (`normalizeBlocklist`) filtert geschützte Domains, erzwingt Obergrenzen und dedupliziert + sortiert. Das dient rein dazu, vertrauenswürdige Metadaten zu berechnen; das **Gerät validiert die akzeptierten Hashes neu**, wenn es die echte Liste herunterlädt, also ist das für sich genommen keine Sicherheitsgrenze. Wichtige Konstanten:

- `PROTECTED_SUFFIXES` — entfernt jede Regel, die auf Apple/iCloud/`mzstatic`/Lava-Security-Domains/Supabase/Cloudflare/Google/GitHub passt, damit ein vergifteter Upstream nicht Lavas eigene Infrastruktur oder Anmelde-Anbieter blockieren kann.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 Was veröffentlichbar ist {#34-what-is-publishable}

`isPublicBlocklistSource` veröffentlicht eine Quelle nur, wenn `status` `sync` oder `nosync` ist, `redistribution_mode === "source_url_only"` gilt **und** `isAllowedLaunchGPLSource` besteht. Das Launch-GPL-Gate (`isAllowedLaunchGPLSource`) lässt Nicht-GPL-Quellen frei zu, beschränkt GPL-3.0-Quellen aber auf `list_id`-Präfixe `hagezi-` oder `oisd-`.

### 3.5 Vorbefüllte Quellen & default-enabled {#35-seeded-sources--default-enabled}

Kuratierte Quellen werden per Migrationen als source-url-only-Metadaten vorbefüllt (HaGeZi, OISD, Block List Project, Phishing.Database, AdGuard). Die Low-Risk-Migration (`20260526000000_low_risk_blocklist_sources.sql`) befüllte anfangs `blocklistproject-basic` (Unlicense) mit `default_enabled = true`, erzwang für **alle GPL-Quellen (HaGeZi/OISD) `default_enabled = false`** bis zur Klärung durch die Rechtsabteilung und parkte den AdGuard DNS Filter in `license_review`. **Diese anfängliche Basic-Default-Vorbefüllung wurde später abgelöst** — die untenstehende Abgleich-Migration setzt Basic auf `false` und Phishing + Scam auf `true` (der aktuell ausgelieferte Standard). Status: **Umgesetzt**.

> **Die Katalog-Standards stimmen mit dem Client überein.** Das `default_enabled`-Set des Katalogs ist jetzt **{Block List Project Phishing, Block List Project Scam}** und passt damit zum empfohlenen iOS-Standard (`AppConfiguration.lavaRecommendedDefaults`, in `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`). Eine Migration setzt `blocklistproject-basic default_enabled = false` und `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`, damit die ausgelieferten Metadaten ehrlich sind. (Die Abgleich-Entscheidung ist jetzt ausgeliefert.) Beachte, dass `default_enabled` informativ ist: Das eigentliche Tier-Gate ist das **Filterregel-Budget (Free 500K / Plus 2M)**, nicht die Anzahl der Listen. Die rechtliche Begründung dafür, URLs (nicht Bytes) zu veröffentlichen, steht in [GPL-source-url-only-Compliance-Entscheidung](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres {#4-supabase-postgres}

Ein Supabase-Postgres-Projekt. RLS ist auf **jeder** öffentlichen Tabelle aktiviert.

### 4.1 Kern-Schema {#41-core-schema}

`20260516034033_backend_core.sql` legt das Fundament an (RLS auf allen 7 öffentlichen Tabellen aktiviert):

- **`profiles`, `user_settings`, `entitlements`** — Kontostatus pro Nutzer. Ein Trigger `handle_new_user()` legt beim Einfügen in `auth.users` automatisch `profiles`- + `user_settings`-Zeilen an.
- **`blocklist_sources`, `blocklist_versions`** — die Tabellen mit Katalog-Metadaten. Eine Quelle ist eine kuratierte Upstream-Liste (`list_id`, `source_url`, Lizenz, Risiko, `default_enabled`, `status`, `redistribution_mode`); eine Version sind die Metadaten eines synchronisierten Snapshots (Hashes, `entry_count`, `byte_size`), zurückverlinkt über `latest_version_id`.
- **`mirror_events`** — Audit-Log nur für die Service-Rolle für `sync`- / `catalog_publish`-Ereignisse (alter Name; siehe §3.1).
- **`bug_reports`** — anonyme Berichte, nur für die Service-Rolle.

Spätere Migrationen fügen **`user_backups`** (§4.3) und **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`) hinzu.

### 4.2 RLS-Modell {#42-rls-model}

| Tabelle(n) | Policy | Wirkung |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | pro Nutzer `auth.uid() = user_id` | jeder Nutzer sieht nur seine eigenen Zeilen |
| `blocklist_sources` | öffentlich lesbar, wenn `status in ('sync','nosync')` (`backend_core.sql:262-266`) | jeder kann kuratierte, sync-fähige Quellen lesen |
| `blocklist_versions` | öffentlich lesbar, wenn `validation_status = 'published'` (`backend_core.sql:268-272`) | jeder kann Metadaten veröffentlichter Versionen lesen |
| `bug_reports`, `mirror_events` | explizit `using(false)` (`20260516034136_backend_core_advisor_fixes.sql`) | kein anonymer/authentifizierter Zugriff — der Worker nutzt die Service-Rolle |
| `qa_developers` | RLS an + **alle Rechte für anon, authenticated entzogen** | nur für die Service-Rolle; die QA-Allowlist ist nie clientseitig lesbar |

Die Trennung ist wichtig: Anonyme Fehlerberichte müssen vom Worker *einfügbar* sein, ohne von Clients *lesbar* zu sein, und die QA-Allowlist darf nur jemals von der Service-Rolle gelesen werden.

### 4.3 Auth & der verschlüsselte Backup-Umschlag {#43-auth--the-encrypted-backup-envelope}

**Auth** ist optional. Die Anmeldung läuft **nur über Apple + Google** (E-Mail/Passwort ist **Verworfen**). Beide nutzen den nativen `id_token`-Grant, der bei Supabase Auth unter `auth/v1/token?grant_type=id_token` mit einer gehashten Nonce eingetauscht wird; die App speichert nur die daraus entstehende Session gerätelokal im Keychain. Der clientseitige Ablauf lebt in der iOS-App (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — siehe [Konten & Backup](./accounts-and-backup.md) für das vollständige Konto-/Backup-Modell.

> **Zero-Knowledge-Backup:** Clientseitiger AES-256-GCM-Umschlag; nur Chiffretext + nicht-geheime Metadaten landen in Supabase `user_backups` (RLS pro Nutzer). Der Server kann ohne ein vom Nutzer gehaltenes Geheimnis nicht entschlüsseln.

Die entscheidende Backend-Tatsache: **Der iOS-Client liest/schreibt `user_backups` direkt über Supabase PostgREST unter RLS pro Nutzer** (Upsert auf `user_id`, eingegrenzt durch das Access-Token). Es gibt am Worker **gar keine `/v1/backup`-Routen**. Der Worker fasst `user_backups` genau einmal an: um es bei der Kontolöschung zu löschen (`deleteAccount`).

`user_backups` speichert nur undurchsichtigen Chiffretext + nicht-geheime Umschlag-Metadaten (KDF-Parameter/Salts, Nonces, Key-Slot-Labels, Client-Schema-Hinweise). Größenobergrenzen (`20260605000000_tighten_backup_envelope_constraints.sql`): Chiffretext ≤ 262144 Bytes (256 KiB) / ≤ 349528 Zeichen, Metadaten ≤ 32768 Bytes (32 KiB). Die DB speichert nie Klartext-Einstellungen, Passwörter, Phrasen oder Schlüssel.

### 4.4 Kontolöschung {#44-account-deletion}

`POST /v1/account/delete` prüft das Access-Token des Nutzers und löscht dann seine `bug_reports` (und jedes passende alte R2-Anhang-Objekt), `user_backups`, `entitlements`, `user_settings` und `profiles`-Zeilen, und löscht schließlich den Supabase-Auth-Nutzer über den Service-Rolle-Endpunkt `/admin/users`. Es gibt nur einen Lösch-Status + die verknüpften Anbieter zurück. Status: **Umgesetzt** (das Frontmatter des Plans liest `status: Done` und die Datei liegt in `plans/implemented/`; eine veraltete **im-Text-Annotation** sagt noch "Backlog", aber der Lane-Ordner + die Code-Präsenz machen es zu einem ausgelieferten Feature).

### 4.5 Spiegelung der App-Store-Berechtigungen {#45-app-store-entitlement-mirroring}

`POST /v1/account/entitlements/app-store-sync` schreibt per Upsert eine `entitlements`-Zeile (Plan `lava_security_plus`) aus einem client-verifizierten StoreKit-Transaktions-JWS, bei Konflikt nach `user_id`. Der gespeicherte `verification_status` ist wörtlich `"client_verified_storekit"` — der Server verifiziert den JWS **nicht** erneut. Erlaubte Produkt-IDs: `lava_security_plus_{monthly,yearly,lifetime}`.

> Die Spiegelung ist **Umgesetzt**; die **serverseitige JWS-Verifizierung ist Geplant** (noch nicht gebaut). Der signierte JWS wird für eine spätere Verifizierung aufbewahrt. Beachte das Tier-Modell an anderer Stelle: Die App-Berechtigung ist lokal (`isPaid`) mit **noch keinem Backend-Sync** als Quelle der Wahrheit — diese Zeile ist eine Spiegelung, kein Gate.

## 5. Passkey-gestützte Wiederherstellung (Zero-Knowledge) {#5-passkey-assisted-recovery-zero-knowledge}

Die Passkey-gestützte Backup-Wiederherstellung ist **Zero-Knowledge** und vollständig clientseitig. Das Schlüsselmaterial für die Wiederherstellung wird auf dem Gerät aus dem **WebAuthn-PRF-/hmac-secret**-Output des Passkeys abgeleitet; der Server speichert **kein** Wiederherstellungs-Geheimnis, registriert **keine** Passkeys und stellt **keine** WebAuthn-Challenges aus. Es gibt keinen server-gegateten Escrow-Pfad.

Die Escrow-Tabellen, die ein früherer Entwurf nutzte (`backup_passkey_recovery`, `backup_passkey_challenges`), wurden vor dem Launch entfernt, und der Worker trägt keine `/v1/backup/*`-Routen und keinen WebAuthn-/Passkey-Code. (Ein `@simplewebauthn/server`-Eintrag bleibt in der `package.json` des Workers als ungenutzte Altlast-Abhängigkeit.)

Die Client-Seite lebt in der iOS-App: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` treibt die PRF-fähige Passkey-Erstellung/-Assertion, und `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` leitet den Slot aus dem hmac-secret-Output ab. Der PRF-Output wird nur während der Assertion gelesen und verlässt das Gerät nie. Ein nicht-PRF-fähiger Passkey-Anbieter kann keinen Zero-Knowledge-Slot tragen, also schlägt die Einrichtung früh fehl und der Nutzer fällt auf einen Wiederherstellungscode zurück. Status: **Umgesetzt**.

## 6. lavasec-email Worker {#6-lavasec-email-worker}

Nur Empfangen-und-Weiterleiten. Er leitet `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` an einen verifizierten Betreiber-Posteingang weiter, weist unbekannte Empfänger und Mail über 10 MiB ab und **speichert keine E-Mail-Inhalte**. Automatische Support-Antworten sind codiert, aber hinter kostenpflichtigem ausgehendem Cloudflare-E-Mail-Versand gesperrt (zurückgestellt). Die Routing-Konstanten liegen in `email-service.ts:9` (`ROUTED_RECIPIENTS`); der Inbound-Handler ist `handleInboundEmail`. Status: **Umgesetzt** (Auto-Reply-Pfad **Geplant**/zurückgestellt).

## 7. Konfiguration & Deploy {#7-config--deploy}

- **Die Konfiguration ist `wrangler.toml`, die per gitignore ausgeschlossen ist**; `wrangler.toml.example` ist die eingecheckte Vorlage. Behandle die lokale `wrangler.toml` als maßgeblich für umgebungsspezifische Werte.
- **Vars** (nicht-geheim, in `[vars]`): die Supabase-URL, der öffentliche API-Origin (`https://api.lavasecurity.app`), die Katalog-Cache-TTL (Standard 300s), eine Größenobergrenze für Fehlerberichte, ein Audit-Schalter für die Kontolöschung und ein Beschleunigungs-Flag der Workers-Runtime. Die interne Fehlerbericht-Triage fügt einen internen Triage-Queue-Schlüssel und einen Dashboard-Origin hinzu, der beim Zusammenstellen von Triage-Links genutzt wird.
- **Secrets** (über `wrangler secret put`): eine Supabase-Service-Rolle-Zugangsdaten, ein Admin-API-Key und — für den Fehlerbericht-Triage-Pfad — ein Issue-Tracker-API-Key und ein optionaler Chat-Benachrichtigungs-Webhook.
- **Das Deploy ist manuell**: `npm run deploy` → `wrangler deploy`. Es gibt keine CI für den Worker.
- **Cloudflare-Routing**: `lavasecurity.app` bleibt auf Pages; `api.lavasecurity.app` und `*.qa-probe.lavasecurity.app` zeigen auf diesen Worker.
- **Kompatibilität**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` ist in den Vars gesetzt, wird aber vom Worker-Code nicht referenziert; es ist ein Beschleunigungs-Flag der Workers-Runtime, keine Anwendungseinstellung.

## 8. Datenschutz-Invarianten (was hier ist und was nicht) {#8-privacy-invariants-what-is-and-isnt-here}

Eine kurze Checkliste für alle, die das Backend erweitern — keine davon darf stillschweigend gebrochen werden:

1. **Keine DNS-/Browsing-Telemetrie.** Es gibt keine Tabelle für alltägliche DNS-Anfragen oder Telemetrie pro Domain. Die Filterung bleibt auf dem Gerät.
2. **Keine Bytes von Drittanbieter-Blocklisten** in R2 oder Postgres — nur `source_url` + akzeptierte Hashes (§3).
3. **`user_backups` ist undurchsichtig** — nur Chiffretext + nicht-geheime Metadaten; der Client (nicht der Worker) schreibt es unter RLS (§4.3).
4. **Service-Rollen-Isolation** für `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Alle Backup-Pfade sind Zero-Knowledge** — einschließlich der Passkey-gestützten Wiederherstellung, deren Schlüsselmaterial clientseitig aus dem WebAuthn-PRF-/hmac-secret-Output abgeleitet wird. Der Server speichert kein Wiederherstellungs-Geheimnis und führt kein WebAuthn aus (§5).

## Siehe auch {#see-also}

- [Systemüberblick](./system-overview.md) — das ganze System auf einer Seite, inklusive Vertrauensgrenzen.
- [iOS-Client](./ios-client.md) — die Geräteseite, die dieses Backend nutzt.
- [Konten & Backup](./accounts-and-backup.md) — clientseitige Auth, der AES-256-GCM-Umschlag, Key-Slots und Wiederherstellungscodes.
- [DNS-Filterung & Blocklisten](./dns-filtering-and-blocklists.md) — die Geräteseite des Katalogs: direkter Upstream-Download, Parsen/Normalisieren und das Filterregel-Budget.
- [GPL-source-url-only-Compliance-Entscheidung](../legal/gpl-source-url-only-compliance-decision.md) — warum der Katalog URLs veröffentlicht, nicht Bytes.
- **Tiers & Monetarisierung** (intern) — das Filterregel-Budget (Free 500K / Plus 2M), das das eigentliche Free/Plus-Gate ist.
- **IP-Risikoregister** (intern) — die IP-/Compliance-Begründung hinter source-url-only.
