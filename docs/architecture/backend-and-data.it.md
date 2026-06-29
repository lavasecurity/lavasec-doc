---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Backend e dati

> **Pubblico:** ingegneri backend. **Ambito:** il livello server — i due Cloudflare Workers, lo schema/RLS/auth di Supabase Postgres, gli store Cloudflare R2 e D1, l'intera superficie dell'API HTTP, config e deploy, e come il modello source-url-only viene applicato sul server.
>
> **Riferimento autorevole:** quando un piano e il codice sono in disaccordo, **vince il codice** — le divergenze sono segnalate inline. Le etichette di stato usano la legenda dell'insieme di documenti: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente integrato), **Pianificato** (progettato, non costruito), **Abbandonato** (rifiutato o annullato).

## 1. La forma del backend

Il backend è deliberatamente piccolo e rispettoso della privacy. È un edge di metadati e account, non un servizio di filtraggio. **Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva solo metadati del catalogo, un backup cifrato opaco per utente e diagnostica anonimizzata che scegli di inviare.** Non ci sono tabelle per le query DNS di routine o per la telemetria per-dominio, e l'accesso all'account è facoltativo e mai richiesto per la protezione.

Il livello server è suddiviso in due componenti: il codice del Worker backend e lo schema del DB.

| Componente | Ruolo |
|---|---|
| **Worker lavasec-api** | Edge principale: letture pubbliche del catalogo, sync della blocklist admin+cron e pubblicazione del catalogo, segnalazioni di bug anonime, feedback di aiuto, eliminazione account, mirroring delle autorizzazioni App Store, pixel di probe QA, controllo dell'accesso QA all'account, promozione del triage delle segnalazioni di bug |
| **Worker lavasec-email** | Forwarder Cloudflare Email Routing solo-ricezione per `@lavasecurity.app` |
| **Supabase Postgres** (un progetto Supabase Postgres) | Account, backup cifrati, metadati del catalogo, tabelle accessibili solo dal service role; RLS su ogni tabella pubblica |
| **Cloudflare R2** (un bucket di produzione, con un bucket di preview separato per lo staging) | Snapshot del catalogo + il cursore di sync; **mai** i byte delle blocklist di terze parti |
| **Cloudflare D1** (il database del feedback di aiuto) | Voti anonimi append-only sul feedback degli articoli di aiuto |

Il Worker raggiunge Supabase tramite PostgREST (`/rest/v1`) e Auth (`/auth/v1`) usando una credenziale service-role di Supabase — non c'è alcun SDK Supabase sul server; le chiamate sono `fetch` grezze tramite gli helper `supabase()` / `supabaseAuth()`.

Stato: **Implementato**.

## 2. Worker lavasec-api

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, un binding R2 → il bucket di produzione (un bucket di preview separato per lo staging), un binding D1 → il database del feedback di aiuto, e **due trigger cron**: uno che si attiva ogni 6 ore (sync della blocklist + pubblicazione del catalogo) e uno che si attiva ogni 2 minuti (promozione del triage delle segnalazioni di bug). È servito su `api.lavasecurity.app`.

### 2.1 Superficie dell'API

Il routing è un dispatcher `route()` piatto. Tutto è **Implementato** se non diversamente indicato.

**Pubblico / non autenticato**

| Metodo e percorso | Handler | Note |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Serve `catalog/latest.json` da R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Serve `catalog/{version}.json` da R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (default 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anonimo, accesso facoltativo; solo campi di debug in allow-list |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto anonimo sull'articolo → **D1**, non Supabase |

> Il caricamento degli allegati (un'ex rotta `PUT /v1/bug-reports/:id/attachment`) è stato **rimosso**; gli screenshot e i dettagli aggiuntivi sono gestiti tramite un canale di supporto mediato da una persona. Il Worker si limita a eliminare con il massimo impegno qualunque oggetto allegato legacy durante l'eliminazione dell'account.

**Account (richiede un access token Supabase)**

| Metodo e percorso | Handler | Note |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valida l'access token dell'utente, elimina le sue righe + eventuali oggetti allegato R2 legacy, poi elimina l'utente Supabase Auth con il service role |
| `GET /v1/account/qa-access` | `accountQAAccess` | Restituisce `is_developer` dall'allowlist `qa_developers` accessibile solo dal service role |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Esegue l'upsert di una riga `entitlements` (piano `lava_security_plus`) da un JWS StoreKit verificato dal client |

> **Nessuna rotta `/v1/backup`.** Il recupero del backup assistito da passkey è ora **zero-knowledge** e interamente lato client (vedi §4.3 e §5); il Worker non ha rotte `/v1/backup/*` né codice WebAuthn/passkey.

**Admin (una chiave API admin tramite `requireAdmin`)**

| Metodo e percorso | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Gli endpoint HTTP admin sono protetti da una chiave API admin. Il percorso di sync schedulato (cron) **non** chiama queste rotte HTTP — invoca la logica di sync (`syncBlocklistSources`) direttamente all'interno dell'handler `scheduled`.

**Host di probe QA** — le richieste ai quattro host `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) vengono intercettate prima del routing e restituiscono un PNG `no-store` 1×1 tramite `getQAProbePixel`. Questi non vengono scritti su Supabase o R2.

### 2.2 Binding e cron

- **Binding R2** — `catalog/latest.json`, `catalog/{version}.json`, e il cursore round-robin `catalog/scheduled-sync-cursor.json`. **Non memorizza mai i byte delle blocklist di terze parti.** (Gli oggetti allegato legacy delle segnalazioni di bug vengono solo mai *eliminati* — con il massimo impegno durante l'eliminazione dell'account — mai scritti.)
- **Binding D1** — righe anonime append-only `article_id` / `locale` / `vote` / `path`; tenute separate da Supabase per scelta progettuale.
- **Cron (`scheduled`)** — l'handler si dirama in base all'id del cron:
  - **Ogni 6 ore** — sincronizza **una** sola sorgente per esecuzione, in round-robin tramite il cursore R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), poi ripubblica il catalogo. Distribuire il carico evita di martellare tutti gli upstream contemporaneamente.
  - **Ogni 2 minuti** — esegue un percorso interno di triage delle segnalazioni di bug che promuove le nuove segnalazioni anonime in una coda di issue-tracker interno, facendo avanzare il proprio cursore watermark. Questo è strumento di operations interno; gli identificatori dell'issue-tracker/notifica sono configurazione, non parte dell'API pubblica.

## 3. Catalogo e applicazione del modello source-url-only

Questa è la parte del backend più specifica della postura di conformità di Lava, quindi riceve un presidio lato server.

### 3.1 Il modello source-url-only

> **Source-url-only:** modello di distribuzione conforme a GPL/IP: Lava pubblica solo l'URL upstream + gli hash accettati; il dispositivo recupera/analizza le liste da sé. Lava **non** memorizza, replica, trasforma o serve mai i byte delle blocklist di terze parti.

Ogni riga `blocklist_sources` porta `redistribution_mode` il cui unico valore consentito è `"source_url_only"`. Il catalogo che il dispositivo legge (`/v1/catalog`, `schema_version` 2) suddivide le voci in `sources[]` e `guardrails[]`; ogni voce porta il `source_url` upstream più `accepted_source_hashes` (SHA-256 + dimensione in byte + conteggio voci + `reviewed_at` + stato `accepted`) — mai i byte delle liste. Vedi `formatCatalogEntry`.

> **Abbandonato:** un progetto precedente replicava in R2 i file delle liste GPL con i byte preservati (il piano di conformità GPL-raw-R2). È stato **superato il 2026-05-25** da source-url-only. Lava non memorizza né serve più i byte delle blocklist di terze parti. Il nome della tabella `mirror_events` è un residuo legacy di quel progetto abbandonato — ora è semplicemente il log di audit di sync/publish.

### 3.2 Come il Worker lo applica in scrittura

Il percorso di sync (`syncOneBlocklist`, admin e cron) recupera ciascun `source_url` upstream, normalizza/valida **localmente nel Worker solo per calcolare i metadati** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), scrive una riga `blocklist_versions` e ripubblica. Le chiavi di byte-storage sono forzate a null nel codice:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Una migrazione (`20260525000000_add_blocklist_distribution_mode.sql`) ha reso queste colonne nullable e ha impostato a null i valori esistenti, così la posizione no-mirror è applicata anche a livello di schema. Il catalogo pubblicato viene scritto in **entrambi** `catalog/{version}.json` e `catalog/latest.json` in R2 (`publishCatalog`).

### 3.3 Guardrail di normalizzazione (solo metadati)

La normalizzazione lato Worker (`normalizeBlocklist`) filtra i domini protetti, applica i tetti massimi e deduplica+ordina. Questo serve puramente a calcolare metadati affidabili; per le **liste community** il dispositivo **non** applica un hash-gate sul download — recupera su TLS dal `source_url` curato e analizza sotto i tetti massimi (gli hash accettati del catalogo sono indicativi), quindi questa normalizzazione lato Worker non è di per sé un confine di sicurezza. (Il livello threat-guardrail di Lava resta hash-pinned sul dispositivo, e la provenienza del `source_url` è applicata al momento della pubblicazione — un cambio di URL deve usare un nuovo `list_id`.) Costanti chiave:

- `PROTECTED_SUFFIXES` — rimuove qualunque regola che corrisponda ai domini Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, così che un upstream avvelenato non possa bloccare l'infrastruttura di Lava o i provider di accesso.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 Cosa è pubblicabile

`isPublicBlocklistSource` pubblica una sorgente solo quando `status` è `sync` o `nosync`, `redistribution_mode === "source_url_only"`, **e** `isAllowedLaunchGPLSource` ha esito positivo. Il gate launch-GPL (`isAllowedLaunchGPLSource`) consente liberamente le sorgenti non-GPL e permette le famiglie di sorgenti GPL-3.0 approvate in base al prefisso `list_id`: `hagezi-`, `oisd-` e `adguard-`.

### 3.5 Sorgenti pre-popolate e abilitate di default

Le sorgenti curate sono pre-popolate come metadati source-url-only tramite migrazioni, generate dalla specifica canonica [Catalogo blocklist](../legal/blocklist-catalog.md) (HaGeZi, OISD, The Block List Project, Phishing.Database, StevenBlack, AdGuard, 1Hosts). La migrazione di espansione delle categorie aggiunge le categorie di difesa in profondità (nsfw/social/gambling/piracy), riallinea il default di installazione pulita a **Block List Basic** e riattiva AdGuard DNS Filter come opzione segnalata dal legale e disabilitata di default. Stato: **Implementato**.

> **I default del catalogo coincidono con il client.** L'insieme `default_enabled` del catalogo è **{Block List Basic}** — una lista combinata ampia e permissiva che sostituisce la precedente coppia Phishing + Scam — corrispondente al default consigliato di iOS (`AppConfiguration.lavaRecommendedDefaults`). Sia la colonna `default_enabled` servita sia il `DefaultCatalog` iOS in bundle sono generati dalla stessa specifica canonica, quindi concordano per costruzione (questo risolve la precedente discrepanza di default client↔backend). Nota che `default_enabled` è informativo: il vero gate di tier è il **budget di regole di filtro (Free 500K / Plus 2M)**, non il conteggio delle liste. La motivazione legale per la pubblicazione degli URL (non dei byte) è in [Decisione di conformità GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres

Un progetto Supabase Postgres. RLS è abilitato su **ogni** tabella pubblica.

### 4.1 Schema core

`20260516034033_backend_core.sql` crea le fondamenta (RLS abilitato su tutte e 7 le tabelle pubbliche):

- **`profiles`, `user_settings`, `entitlements`** — stato dell'account per-utente. Un trigger `handle_new_user()` crea automaticamente le righe `profiles` + `user_settings` all'inserimento in `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — le tabelle dei metadati del catalogo. Una sorgente è una lista upstream curata (`list_id`, `source_url`, licenza, rischio, `default_enabled`, `status`, `redistribution_mode`); una versione è i metadati di uno snapshot sincronizzato (hash, `entry_count`, `byte_size`), collegata tramite `latest_version_id`.
- **`mirror_events`** — log di audit accessibile solo dal service role per gli eventi `sync` / `catalog_publish` (nome legacy; vedi §3.1).
- **`bug_reports`** — segnalazioni anonime accessibili solo dal service role.

Le migrazioni successive aggiungono **`user_backups`** (§4.3) e **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modello RLS

| Tabella/e | Policy | Effetto |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | per-utente `auth.uid() = user_id` | ogni utente vede solo le proprie righe |
| `blocklist_sources` | lettura pubblica dove `status in ('sync','nosync')` (`backend_core.sql:262-266`) | chiunque può leggere le sorgenti curate idonee al sync |
| `blocklist_versions` | lettura pubblica dove `validation_status = 'published'` (`backend_core.sql:268-272`) | chiunque può leggere i metadati delle versioni pubblicate |
| `bug_reports`, `mirror_events` | `using(false)` esplicito (`20260516034136_backend_core_advisor_fixes.sql`) | nessun accesso anon/authenticated — il Worker usa il service role |
| `qa_developers` | RLS attivo + **revoca tutto da anon, authenticated** | accessibile solo dal service role; l'allowlist QA non è mai leggibile dal client |

La separazione è importante: le segnalazioni di bug anonime devono essere *inseribili* dal Worker senza essere *leggibili* dai client, e l'allowlist QA deve poter essere letta solo dal service role.

### 4.3 Auth e la busta di backup cifrata

L'**Auth** è facoltativa. L'accesso è **solo Apple + Google** (email/password è **Abbandonato**). Entrambi usano il grant nativo `id_token` scambiato presso Supabase Auth `auth/v1/token?grant_type=id_token` con un nonce hashato; l'app memorizza solo la sessione risultante in locale sul dispositivo nel Keychain. Il flusso lato client risiede nell'app iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — vedi [Account e backup](./accounts-and-backup.md) per il modello completo account/backup.

> **Backup zero-knowledge:** busta AES-256-GCM lato client; solo il ciphertext + i metadati non segreti vengono caricati su Supabase `user_backups` (RLS per utente). Il server non può decifrare senza un segreto detenuto dall'utente.

Il fatto backend cruciale: **il client iOS legge/scrive `user_backups` direttamente tramite Supabase PostgREST sotto RLS per-utente** (upsert su `user_id`, vincolato dall'access token). Non ci sono **affatto rotte `/v1/backup`** sul Worker. Il Worker tocca `user_backups` esattamente una volta: per eliminarlo durante l'eliminazione dell'account (`deleteAccount`).

`user_backups` memorizza solo ciphertext opaco + metadati di busta non segreti (parametri/salt KDF, nonce, etichette degli slot di chiave, suggerimenti di schema del client). Tetti di dimensione (`20260605000000_tighten_backup_envelope_constraints.sql`): ciphertext ≤ 262144 byte (256 KiB) / ≤ 349528 caratteri, metadati ≤ 32768 byte (32 KiB). Il DB non memorizza mai impostazioni in chiaro, password, frasi o chiavi.

### 4.4 Eliminazione dell'account

`POST /v1/account/delete` valida l'access token dell'utente, poi elimina le sue righe `bug_reports` (e qualunque oggetto allegato R2 legacy corrispondente), `user_backups`, `entitlements`, `user_settings` e `profiles`, e infine elimina l'utente Supabase Auth tramite l'endpoint service-role `/admin/users`. Restituisce solo uno stato di eliminazione + i provider collegati. Stato: **Implementato** (il frontmatter del piano riporta `status: Done` e il file è in `plans/implemented/`; un'annotazione **nel corpo** ormai obsoleta dice ancora "Backlog", ma la cartella della corsia + la presenza nel codice lo rendono rilasciato).

### 4.5 Mirroring delle autorizzazioni App Store

`POST /v1/account/entitlements/app-store-sync` esegue l'upsert di una riga `entitlements` (piano `lava_security_plus`) da un JWS di transazione StoreKit verificato dal client, in conflitto per `user_id`. Il `verification_status` memorizzato è letteralmente `"client_verified_storekit"` — il server **non** verifica nuovamente il JWS. ID prodotto consentiti: `lava_security_plus_{monthly,yearly}`.

> Il mirroring è **Implementato**; la **verifica del JWS lato server è Pianificata** (non ancora costruita). Il JWS firmato viene memorizzato per una verifica successiva. Nota il modello di tier altrove: l'autorizzazione dell'app è locale (`isPaid`) **senza ancora alcun sync backend** come fonte di verità — questa riga è un mirror, non il gate.

## 5. Recupero assistito da passkey (zero-knowledge)

Il recupero del backup assistito da passkey è **zero-knowledge** e interamente lato client. Il materiale della chiave di recupero è derivato sul dispositivo dall'output **WebAuthn PRF / hmac-secret** della passkey; il server **non** memorizza alcun segreto di recupero, **non** registra alcuna passkey ed **non** emette alcuna challenge WebAuthn. Non c'è alcun percorso di escrow gestito dal server.

Le tabelle di escrow usate da un progetto precedente (`backup_passkey_recovery`, `backup_passkey_challenges`) sono state eliminate prima del lancio, e il Worker non porta alcuna rotta `/v1/backup/*` né codice WebAuthn/passkey. (Una voce `@simplewebauthn/server` resta nel `package.json` del Worker come dipendenza residua inutilizzata.)

Il lato client risiede nell'app iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` guida la creazione/asserzione della passkey con capacità PRF, e `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva lo slot dall'output hmac-secret. L'output PRF viene letto solo durante l'asserzione e non lascia mai il dispositivo. Un provider di passkey non-PRF non può supportare uno slot zero-knowledge, quindi la configurazione fallisce subito e l'utente ripiega su una frase di recupero. Stato: **Implementato**.

## 6. Worker lavasec-email

Solo ricezione e inoltro. Inoltra `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` a una casella di posta dell'operatore verificata, rifiuta i destinatari sconosciuti e la posta oltre 10 MiB, e **non memorizza i corpi delle email**. Le risposte automatiche di supporto sono codificate ma bloccate dietro l'invio di email Cloudflare a pagamento (rimandato). Le costanti di routing risiedono in `email-service.ts:9` (`ROUTED_RECIPIENTS`); l'handler in ingresso è `handleInboundEmail`. Stato: **Implementato** (percorso di risposta automatica **Pianificato**/rimandato).

## 7. Config e deploy

- **La configurazione è `wrangler.toml`, che è in gitignore**; `wrangler.toml.example` è il template committato. Tratta il `wrangler.toml` locale come canonico per i valori specifici dell'ambiente.
- **Vars** (non segrete, in `[vars]`): l'URL Supabase, l'origine API pubblica (`https://api.lavasecurity.app`), il TTL della cache del catalogo (default 300s), un tetto di dimensione delle segnalazioni di bug, un toggle di audit dell'eliminazione account e un flag di accelerazione del runtime Workers. Il triage interno delle segnalazioni di bug aggiunge una chiave della coda di triage interna e un'origine della dashboard usata nella composizione dei link di triage.
- **Segreti** (tramite `wrangler secret put`): una credenziale service-role Supabase, una chiave API admin e — per il percorso di triage delle segnalazioni di bug — una chiave API dell'issue-tracker e un webhook facoltativo di notifica chat.
- **Il deploy è manuale**: `npm run deploy` → `wrangler deploy`. Non c'è CI per il Worker.
- **Routing Cloudflare**: `lavasecurity.app` resta su Pages; `api.lavasecurity.app` e `*.qa-probe.lavasecurity.app` puntano a questo Worker.
- **Compatibilità**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` è impostato nelle vars ma non è referenziato dal codice del Worker; è un flag di accelerazione del runtime Workers piuttosto che un'impostazione applicativa.

## 8. Invarianti di privacy (cosa c'è e cosa non c'è qui)

Una rapida checklist per chiunque estenda il backend — nessuna di queste può essere infranta silenziosamente:

1. **Nessuna telemetria DNS/navigazione.** Non c'è alcuna tabella per le query DNS di routine o la telemetria per-dominio. Il filtraggio resta sul dispositivo.
2. **Nessun byte di blocklist di terze parti** in R2 o Postgres — solo `source_url` + hash accettati (§3).
3. **`user_backups` è opaco** — solo ciphertext + metadati non segreti; lo scrive il client (non il Worker) sotto RLS (§4.3).
4. **Isolamento del service role** per `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Tutti i percorsi di backup sono zero-knowledge** — incluso il recupero assistito da passkey, il cui materiale di chiave è derivato lato client dall'output WebAuthn PRF/hmac-secret. Il server non memorizza alcun segreto di recupero e non esegue alcun WebAuthn (§5).

## Vedi anche

- [Panoramica del sistema](./system-overview.md) — l'intero sistema in una pagina, inclusi i confini di fiducia.
- [Client iOS](./ios-client.md) — il lato dispositivo che consuma questo backend.
- [Account e backup](./accounts-and-backup.md) — auth lato client, la busta AES-256-GCM, gli slot di chiave e le frasi di recupero.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — il lato dispositivo del catalogo: download upstream diretto, parsing/normalizzazione e il budget di regole di filtro.
- [Decisione di conformità GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — perché il catalogo pubblica URL, non byte.
- **Tier e monetizzazione** (interno) — il budget di regole di filtro (Free 500K / Plus 2M) che è il vero gate Free/Plus.
- **Registro dei rischi IP** (interno) — la motivazione IP/conformità dietro source-url-only.
