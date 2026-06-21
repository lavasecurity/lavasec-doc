---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Backend e dati

> **Pubblico:** ingegneri del backend. **Ambito:** il livello server — i due Cloudflare Workers, lo schema/RLS/auth di Supabase Postgres, gli archivi Cloudflare R2 e D1, l'intera superficie dell'API HTTP, configurazione e deploy, e come la regola "solo URL della sorgente" viene applicata sul server.
>
> **Riferimento autorevole:** quando un piano e il codice non concordano, **vince il codice** — le divergenze sono segnalate direttamente nel testo. Le etichette di stato usano la legenda del set di documenti: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente realizzato), **Pianificato** (progettato, non realizzato), **Abbandonato** (rifiutato o annullato).

## 1. La forma del backend {#1-the-shape-of-the-backend}

Il backend è volutamente piccolo e rispettoso della privacy. È un margine per metadati e account, non un servizio di filtraggio. **Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva solo i metadati del catalogo, un backup cifrato opaco per ciascun utente e diagnostiche anonimizzate che scegli di inviare.** Non ci sono tabelle per le query DNS di routine o per la telemetria per dominio, e l'accesso all'account è facoltativo e non è mai richiesto per la protezione.

Il livello server è suddiviso in due componenti: il codice del Worker del backend e lo schema del database.

| Componente | Ruolo |
|---|---|
| **Worker lavasec-api** | Margine principale: letture pubbliche del catalogo, sincronizzazione admin+cron delle blocklist e pubblicazione del catalogo, segnalazioni di bug anonime, feedback di aiuto, eliminazione account, mirroring dei diritti dell'App Store, pixel di sonda QA, controllo dell'accesso QA dell'account, promozione del triage delle segnalazioni di bug |
| **Worker lavasec-email** | Inoltratore di sola ricezione basato su Cloudflare Email Routing per `@lavasecurity.app` |
| **Supabase Postgres** (un progetto Supabase Postgres) | Account, backup cifrati, metadati del catalogo, tabelle riservate al ruolo di servizio; RLS su ogni tabella pubblica |
| **Cloudflare R2** (un bucket di produzione, con un bucket di anteprima separato per lo staging) | Snapshot del catalogo + il cursore di sincronizzazione; **mai** byte di blocklist di terze parti |
| **Cloudflare D1** (il database del feedback di aiuto) | Voti di feedback anonimi sugli articoli di aiuto, solo in aggiunta |

Il Worker raggiunge Supabase tramite PostgREST (`/rest/v1`) e Auth (`/auth/v1`) usando una credenziale del ruolo di servizio di Supabase — non c'è alcun SDK di Supabase sul server; le chiamate sono `fetch` grezze tramite gli helper `supabase()` / `supabaseAuth()`.

Stato: **Implementato**.

## 2. Worker lavasec-api {#2-lavasec-api-worker}

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, un binding R2 → il bucket di produzione (un bucket di anteprima separato per lo staging), un binding D1 → il database del feedback di aiuto, e **due trigger cron**: uno che scatta ogni 6 ore (sincronizzazione blocklist + pubblicazione catalogo) e uno che scatta ogni 2 minuti (promozione del triage delle segnalazioni di bug). È servito su `api.lavasecurity.app`.

### 2.1 Superficie dell'API {#21-api-surface}

Il routing è un dispatcher `route()` piatto. Tutto è **Implementato** salvo dove indicato.

**Pubblico / non autenticato**

| Metodo e percorso | Handler | Note |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Serve `catalog/latest.json` da R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Serve `catalog/{version}.json` da R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (predefinito 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anonimo, login facoltativo; solo campi di debug nella allow-list |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto anonimo su articolo → **D1**, non Supabase |

> Il caricamento di allegati (un precedente percorso `PUT /v1/bug-reports/:id/attachment`) è stato **rimosso**; gli screenshot e i dettagli aggiuntivi sono gestiti tramite un canale di supporto mediato da una persona. Il Worker si limita a eliminare con il massimo impegno qualsiasi oggetto allegato legacy durante l'eliminazione dell'account.

**Account (richiede un access token di Supabase)**

| Metodo e percorso | Handler | Note |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valida l'access token dell'utente, elimina le sue righe + eventuali oggetti allegati R2 legacy, poi elimina l'utente di Supabase Auth con il ruolo di servizio |
| `GET /v1/account/qa-access` | `accountQAAccess` | Restituisce `is_developer` dalla allowlist `qa_developers` riservata al ruolo di servizio |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Esegue l'upsert di una riga `entitlements` (piano `lava_security_plus`) da un JWS StoreKit verificato dal client |

> **Nessun percorso `/v1/backup`.** Il recupero del backup assistito da passkey è ora **zero-knowledge** e interamente lato client (vedi §4.3 e §5); il Worker non ha percorsi `/v1/backup/*` né codice WebAuthn/passkey.

**Admin (una chiave API admin tramite `requireAdmin`)**

| Metodo e percorso | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Gli endpoint HTTP admin sono protetti da una chiave API admin. Il percorso di sincronizzazione pianificato (cron) **non** chiama queste route HTTP — invoca la logica di sincronizzazione (`syncBlocklistSources`) direttamente all'interno dell'handler `scheduled`.

**Host di sonda QA** — le richieste ai quattro host `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) vengono intercettate prima del routing e restituiscono un PNG 1×1 `no-store` tramite `getQAProbePixel`. Questi non vengono scritti su Supabase o R2.

### 2.2 Binding e cron {#22-bindings--cron}

- **Binding R2** — `catalog/latest.json`, `catalog/{version}.json` e il cursore round-robin `catalog/scheduled-sync-cursor.json`. **Non memorizza mai byte di blocklist di terze parti.** (Gli oggetti allegati legacy delle segnalazioni di bug vengono solo *eliminati* — con il massimo impegno durante l'eliminazione dell'account — mai scritti.)
- **Binding D1** — righe anonime `article_id` / `locale` / `vote` / `path` solo in aggiunta; tenute separate da Supabase per scelta progettuale.
- **Cron (`scheduled`)** — l'handler si dirama in base all'id del cron:
  - **Ogni 6 ore** — sincronizza **una sola** sorgente per esecuzione, a rotazione round-robin tramite il cursore R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), poi ripubblica il catalogo. Distribuire il carico evita di tempestare tutte le sorgenti a monte contemporaneamente.
  - **Ogni 2 minuti** — esegue un percorso interno di triage delle segnalazioni di bug che promuove le nuove segnalazioni anonime in una coda interna di issue-tracker, facendo avanzare il proprio cursore watermark. Si tratta di strumentazione operativa interna; gli identificatori dell'issue-tracker/delle notifiche sono configurazione, non parte dell'API pubblica.

## 3. Catalogo e applicazione della regola "solo URL della sorgente" {#3-catalog--source-url-only-enforcement}

Questa è la parte del backend più specifica della postura di conformità di Lava, perciò ottiene un controllo lato server.

### 3.1 Il modello "solo URL della sorgente" {#31-the-source-url-only-model}

> **Solo URL della sorgente:** modello di distribuzione conforme a GPL/proprietà intellettuale: Lava pubblica solo l'URL a monte + gli hash accettati; il dispositivo scarica/analizza le liste da sé. Lava **non** memorizza, replica, trasforma o serve mai byte di blocklist di terze parti.

Ogni riga `blocklist_sources` porta `redistribution_mode`, il cui unico valore consentito è `"source_url_only"`. Il catalogo che il dispositivo legge (`/v1/catalog`, `schema_version` 2) suddivide le voci in `sources[]` e `guardrails[]`; ogni voce porta l'`source_url` a monte più gli `accepted_source_hashes` (SHA-256 + dimensione in byte + conteggio voci + `reviewed_at` + stato `accepted`) — mai i byte della lista. Vedi `formatCatalogEntry`.

> **Abbandonato:** un progetto precedente replicava in R2 i file di lista GPL con byte preservati (il piano di conformità GPL-raw-R2). È stato **sostituito il 2026-05-25** dalla regola "solo URL della sorgente". Lava non memorizza né serve più byte di blocklist di terze parti. Il nome della tabella `mirror_events` è un residuo legacy di quel progetto abbandonato — ora è semplicemente il log di audit di sincronizzazione/pubblicazione.

### 3.2 Come il Worker la applica in scrittura {#32-how-the-worker-enforces-it-on-writes}

Il percorso di sincronizzazione (`syncOneBlocklist`, admin e cron) scarica ogni `source_url` a monte, normalizza/valida **localmente nel Worker solo per calcolare i metadati** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), scrive una riga `blocklist_versions` e ripubblica. Le chiavi di archiviazione dei byte sono impostate fisse a null:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Una migrazione (`20260525000000_add_blocklist_distribution_mode.sql`) ha reso queste colonne nullable e ha impostato i valori esistenti a null, così la posizione "nessun mirror" è applicata anche a livello di schema. Il catalogo pubblicato viene scritto **sia** in `catalog/{version}.json` sia in `catalog/latest.json` su R2 (`publishCatalog`).

### 3.3 Guardrail di normalizzazione (solo metadati) {#33-normalization-guardrails-metadata-only}

La normalizzazione lato Worker (`normalizeBlocklist`) filtra i domini protetti, applica i limiti e deduplica+ordina. Serve esclusivamente a calcolare metadati affidabili; il **dispositivo riconvalida gli hash accettati** quando scarica la lista reale, quindi di per sé questo non è un confine di sicurezza. Costanti chiave:

- `PROTECTED_SUFFIXES` — rimuove qualsiasi regola che corrisponda ai domini di Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, così una sorgente a monte compromessa non può bloccare l'infrastruttura di Lava né i provider di accesso.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 Cosa è pubblicabile {#34-what-is-publishable}

`isPublicBlocklistSource` pubblica una sorgente solo quando `status` è `sync` o `nosync`, `redistribution_mode === "source_url_only"`, **e** `isAllowedLaunchGPLSource` passa. Il gate GPL di lancio (`isAllowedLaunchGPLSource`) consente liberamente le sorgenti non GPL ma limita le sorgenti GPL-3.0 ai prefissi di `list_id` `hagezi-` o `oisd-`.

### 3.5 Sorgenti precaricate e abilitate per impostazione predefinita {#35-seeded-sources--default-enabled}

Le sorgenti curate vengono precaricate come metadati "solo URL della sorgente" tramite migrazioni (HaGeZi, OISD, Block List Project, Phishing.Database, AdGuard). La migrazione a basso rischio (`20260526000000_low_risk_blocklist_sources.sql`) inizialmente precaricava `blocklistproject-basic` (Unlicense) con `default_enabled = true`, forzava **tutte le sorgenti GPL (HaGeZi/OISD) a `default_enabled = false`** in attesa del parere legale, e parcheggiava AdGuard DNS Filter in `license_review`. **Quel precaricamento iniziale con Basic come predefinita è stato poi sostituito** — la migrazione di allineamento qui sotto porta Basic a `false` e Phishing + Scam a `true` (l'attuale predefinita servita). Stato: **Implementato**.

> **I valori predefiniti del catalogo coincidono con il client.** L'insieme `default_enabled` del catalogo è ora **{Block List Project Phishing, Block List Project Scam}**, in linea con la predefinita consigliata di iOS (`AppConfiguration.lavaRecommendedDefaults`, in `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`). Una migrazione imposta `blocklistproject-basic default_enabled = false` e `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`, così che i metadati serviti siano veritieri. (la decisione di allineamento è ora rilasciata.) Nota che `default_enabled` è informativo: il vero limite di livello è il **budget delle regole di filtro (Free 500K / Plus 2M)**, non il numero di liste. La motivazione legale per pubblicare gli URL (non i byte) è in [Decisione di conformità GPL "solo URL della sorgente"](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres {#4-supabase-postgres}

Un progetto Supabase Postgres. RLS è abilitato su **ogni** tabella pubblica.

### 4.1 Schema di base {#41-core-schema}

`20260516034033_backend_core.sql` crea le fondamenta (RLS abilitato su tutte le 7 tabelle pubbliche):

- **`profiles`, `user_settings`, `entitlements`** — stato dell'account per utente. Un trigger `handle_new_user()` crea automaticamente le righe `profiles` + `user_settings` all'inserimento in `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — le tabelle dei metadati del catalogo. Una sorgente è una lista a monte curata (`list_id`, `source_url`, licenza, rischio, `default_enabled`, `status`, `redistribution_mode`); una versione è i metadati di uno snapshot sincronizzato (hash, `entry_count`, `byte_size`), collegata tramite `latest_version_id`.
- **`mirror_events`** — log di audit riservato al ruolo di servizio degli eventi `sync` / `catalog_publish` (nome legacy; vedi §3.1).
- **`bug_reports`** — segnalazioni anonime riservate al ruolo di servizio.

Migrazioni successive aggiungono **`user_backups`** (§4.3) e **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modello RLS {#42-rls-model}

| Tabella/e | Policy | Effetto |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | per utente `auth.uid() = user_id` | ogni utente vede solo le proprie righe |
| `blocklist_sources` | lettura pubblica dove `status in ('sync','nosync')` (`backend_core.sql:262-266`) | chiunque può leggere le sorgenti curate idonee alla sincronizzazione |
| `blocklist_versions` | lettura pubblica dove `validation_status = 'published'` (`backend_core.sql:268-272`) | chiunque può leggere i metadati delle versioni pubblicate |
| `bug_reports`, `mirror_events` | `using(false)` esplicito (`20260516034136_backend_core_advisor_fixes.sql`) | nessun accesso anon/authenticated — il Worker usa il ruolo di servizio |
| `qa_developers` | RLS attivo + **revoca tutto da anon, authenticated** | riservato al ruolo di servizio; la allowlist QA non è mai leggibile dal client |

La distinzione conta: le segnalazioni di bug anonime devono essere *inseribili* dal Worker senza essere *leggibili* dai client, e la allowlist QA deve poter essere letta solo dal ruolo di servizio.

### 4.3 Auth e la busta di backup cifrata {#43-auth--the-encrypted-backup-envelope}

L'**Auth** è facoltativa. L'accesso è **solo Apple + Google** (email/password è **Abbandonato**). Entrambi usano il grant nativo `id_token` scambiato su Supabase Auth `auth/v1/token?grant_type=id_token` con un nonce sottoposto a hash; l'app memorizza solo la sessione risultante in locale sul dispositivo nel Keychain. Il flusso lato client risiede nell'app iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — vedi [Account e Backup](./accounts-and-backup.md) per il modello completo di account/backup.

> **Backup zero-knowledge:** busta AES-256-GCM lato client; solo il testo cifrato + i metadati non segreti vengono caricati su Supabase `user_backups` (RLS per utente). Il server non può decifrare senza un segreto detenuto dall'utente.

Il fatto cruciale per il backend: **il client iOS legge/scrive `user_backups` direttamente tramite Supabase PostgREST sotto RLS per utente** (upsert su `user_id`, delimitato dall'access token). Non ci sono affatto percorsi `/v1/backup` sul Worker. Il Worker tocca `user_backups` esattamente una volta: per eliminarlo durante l'eliminazione dell'account (`deleteAccount`).

`user_backups` memorizza solo testo cifrato opaco + metadati di busta non segreti (parametri/salt KDF, nonce, etichette degli slot di chiave, suggerimenti sullo schema del client). Limiti di dimensione (`20260605000000_tighten_backup_envelope_constraints.sql`): testo cifrato ≤ 262144 byte (256 KiB) / ≤ 349528 caratteri, metadati ≤ 32768 byte (32 KiB). Il database non memorizza mai impostazioni in chiaro, password, frasi o chiavi.

### 4.4 Eliminazione dell'account {#44-account-deletion}

`POST /v1/account/delete` valida l'access token dell'utente, poi elimina le sue righe `bug_reports` (e qualsiasi oggetto allegato R2 legacy corrispondente), `user_backups`, `entitlements`, `user_settings` e `profiles`, e infine elimina l'utente di Supabase Auth tramite l'endpoint `/admin/users` del ruolo di servizio. Restituisce solo uno stato di eliminazione + i provider collegati. Stato: **Implementato** (il frontmatter del piano riporta `status: Done` e il file è in `plans/implemented/`; un'annotazione **nel corpo** ormai obsoleta dice ancora "Backlog", ma la cartella della corsia + la presenza del codice lo rendono rilasciato).

### 4.5 Mirroring dei diritti dell'App Store {#45-app-store-entitlement-mirroring}

`POST /v1/account/entitlements/app-store-sync` esegue l'upsert di una riga `entitlements` (piano `lava_security_plus`) da un JWS di transazione StoreKit verificato dal client, in conflitto su `user_id`. Il `verification_status` memorizzato è letteralmente `"client_verified_storekit"` — il server **non** riverifica il JWS. ID prodotto consentiti: `lava_security_plus_{monthly,yearly,lifetime}`.

> Il mirroring è **Implementato**; la **verifica lato server del JWS è Pianificata** (non ancora realizzata). Il JWS firmato viene memorizzato per una verifica successiva. Nota il modello di livelli altrove: il diritto dell'app è locale (`isPaid`) **senza ancora alcuna sincronizzazione backend** come fonte di verità — questa riga è un mirror, non il controllo di accesso.

## 5. Recupero assistito da passkey (zero-knowledge) {#5-passkey-assisted-recovery-zero-knowledge}

Il recupero del backup assistito da passkey è **zero-knowledge** e interamente lato client. Il materiale della chiave di recupero è derivato sul dispositivo dall'output **WebAuthn PRF / hmac-secret** della passkey; il server non memorizza **alcun** segreto di recupero, non registra **alcuna** passkey e non emette **alcuna** sfida WebAuthn. Non esiste alcun percorso di escrow controllato dal server.

Le tabelle di escrow che un progetto precedente utilizzava (`backup_passkey_recovery`, `backup_passkey_challenges`) sono state eliminate prima del lancio, e il Worker non porta alcun percorso `/v1/backup/*` né codice WebAuthn/passkey. (Una voce `@simplewebauthn/server` rimane nel `package.json` del Worker come dipendenza residua inutilizzata.)

Il lato client risiede nell'app iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` guida la creazione/asserzione della passkey con supporto PRF, e `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva lo slot dall'output hmac-secret. L'output PRF viene letto solo durante l'asserzione e non lascia mai il dispositivo. Un provider di passkey non PRF non può sostenere uno slot zero-knowledge, perciò la configurazione fallisce subito e l'utente ricade su una frase di recupero. Stato: **Implementato**.

## 6. Worker lavasec-email {#6-lavasec-email-worker}

Solo ricezione e inoltro. Inoltra `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` a una casella di posta dell'operatore verificata, rifiuta i destinatari sconosciuti e la posta oltre 10 MiB, e **non memorizza i corpi delle email**. Le risposte automatiche di supporto sono codificate ma bloccate dietro l'invio email in uscita a pagamento di Cloudflare (rinviato). Le costanti di routing risiedono in `email-service.ts:9` (`ROUTED_RECIPIENTS`); l'handler in entrata è `handleInboundEmail`. Stato: **Implementato** (percorso di risposta automatica **Pianificato**/rinviato).

## 7. Configurazione e deploy {#7-config--deploy}

- **La configurazione è `wrangler.toml`, che è in gitignore**; `wrangler.toml.example` è il modello incluso nel repository. Tratta il `wrangler.toml` locale come canonico per i valori specifici dell'ambiente.
- **Var** (non segrete, in `[vars]`): l'URL di Supabase, l'origine API pubblica (`https://api.lavasecurity.app`), il TTL della cache del catalogo (predefinito 300s), un limite di dimensione delle segnalazioni di bug, un interruttore di audit per l'eliminazione account e un flag di accelerazione del runtime di Workers. Il triage interno delle segnalazioni di bug aggiunge una chiave della coda di triage interna e un'origine di dashboard usata nella composizione dei link di triage.
- **Segreti** (tramite `wrangler secret put`): una credenziale del ruolo di servizio di Supabase, una chiave API admin e — per il percorso di triage delle segnalazioni di bug — una chiave API dell'issue-tracker e un webhook di notifica chat facoltativo.
- **Il deploy è manuale**: `npm run deploy` → `wrangler deploy`. Non c'è CI per il Worker.
- **Routing di Cloudflare**: `lavasecurity.app` resta su Pages; `api.lavasecurity.app` e `*.qa-probe.lavasecurity.app` puntano a questo Worker.
- **Compatibilità**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` è impostato nelle var ma non è referenziato dal codice del Worker; è un flag di accelerazione del runtime di Workers piuttosto che un'impostazione dell'applicazione.

## 8. Invarianti di privacy (cosa c'è e cosa non c'è qui) {#8-privacy-invariants-what-is-and-isnt-here}

Una lista di controllo rapida per chiunque estenda il backend — nessuna di queste può essere infranta in sordina:

1. **Nessuna telemetria DNS/di navigazione.** Non c'è alcuna tabella per le query DNS di routine o per la telemetria per dominio. Il filtraggio resta sul dispositivo.
2. **Nessun byte di blocklist di terze parti** in R2 o Postgres — solo `source_url` + hash accettati (§3).
3. **`user_backups` è opaco** — solo testo cifrato + metadati non segreti; lo scrive il client (non il Worker) sotto RLS (§4.3).
4. **Isolamento del ruolo di servizio** per `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Tutti i percorsi di backup sono zero-knowledge** — incluso il recupero assistito da passkey, il cui materiale di chiave è derivato lato client dall'output WebAuthn PRF/hmac-secret. Il server non memorizza alcun segreto di recupero e non esegue alcun WebAuthn (§5).

## Vedi anche {#see-also}

- [Panoramica del sistema](./system-overview.md) — l'intero sistema in una pagina, inclusi i confini di fiducia.
- [Client iOS](./ios-client.md) — il lato dispositivo che consuma questo backend.
- [Account e Backup](./accounts-and-backup.md) — auth lato client, la busta AES-256-GCM, gli slot di chiave e le frasi di recupero.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — il lato dispositivo del catalogo: download diretto dalla sorgente a monte, parsing/normalizzazione e il budget delle regole di filtro.
- [Decisione di conformità GPL "solo URL della sorgente"](../legal/gpl-source-url-only-compliance-decision.md) — perché il catalogo pubblica gli URL, non i byte.
- **Livelli e monetizzazione** (interno) — il budget delle regole di filtro (Free 500K / Plus 2M) che è il vero controllo di accesso Free/Plus.
- **Registro dei rischi sulla proprietà intellettuale** (interno) — la motivazione di proprietà intellettuale/conformità dietro la regola "solo URL della sorgente".
