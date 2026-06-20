---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Backend e dati

> **Pubblico:** ingegneri backend. **Ambito:** lo strato server — i due Cloudflare Workers, lo schema/RLS/auth di Supabase Postgres, gli store Cloudflare R2 e D1, l'intera superficie dell'API HTTP, configurazione e deploy, e come la modalità source-url-only viene applicata sul server.
>
> **Riferimento autorevole:** quando un piano e il codice sono in disaccordo, **vince il codice** — le divergenze sono segnalate in linea. Le etichette di stato seguono la legenda della raccolta di documenti: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente integrato), **Pianificato** (progettato, non ancora costruito), **Abbandonato** (rifiutato o annullato).

## 1. La forma del backend

Il backend è volutamente piccolo e rispettoso della privacy. È un margine per metadati e account, non un servizio di filtraggio. **Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i propri server e non riceve mai l'elenco dei domini che visiti — il backend conserva solo i metadati del catalogo, un backup cifrato e opaco per ogni utente, e le diagnostiche anonime che scegli di inviare.** Non esistono tabelle per le normali query DNS o per la telemetria per dominio, e l'accesso all'account è facoltativo e mai necessario per la protezione.

Lo strato server è suddiviso in due componenti: il codice del Worker backend e lo schema del database.

| Componente | Ruolo |
|---|---|
| **lavasec-api Worker** | Margine principale: letture pubbliche del catalogo, sincronizzazione admin+cron delle blocklist e pubblicazione del catalogo, segnalazioni di bug anonime, feedback sull'aiuto, eliminazione account, mirroring delle abilitazioni App Store, pixel di sonda QA, verifica dell'accesso QA dell'account, promozione delle segnalazioni di bug verso il triage |
| **lavasec-email Worker** | Inoltratore in sola ricezione basato su Cloudflare Email Routing per `@lavasecurity.app` |
| **Supabase Postgres** (un progetto Supabase Postgres) | Account, backup cifrati, metadati del catalogo, tabelle accessibili solo dal ruolo di servizio; RLS su ogni tabella pubblica |
| **Cloudflare R2** (un bucket di produzione, con un bucket di anteprima separato per lo staging) | Snapshot del catalogo + il cursore di sincronizzazione; **mai** i byte delle blocklist di terze parti |
| **Cloudflare D1** (il database del feedback sull'aiuto) | Voti di feedback anonimi e in sola aggiunta sugli articoli di aiuto |

Il Worker raggiunge Supabase tramite PostgREST (`/rest/v1`) e Auth (`/auth/v1`) usando una credenziale del ruolo di servizio di Supabase — sul server non c'è alcun SDK di Supabase; le chiamate sono semplici `fetch` tramite gli helper `supabase()` / `supabaseAuth()`.

Stato: **Implementato**.

## 2. lavasec-api Worker

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, un binding R2 → il bucket di produzione (un bucket di anteprima separato per lo staging), un binding D1 → il database del feedback sull'aiuto, e **due trigger cron**: uno che scatta ogni 6 ore (sincronizzazione delle blocklist + pubblicazione del catalogo) e uno che scatta ogni 2 minuti (promozione delle segnalazioni di bug verso il triage). È servito su `api.lavasecurity.app`.

### 2.1 Superficie dell'API

Il routing è un dispatcher `route()` piatto. Tutto è **Implementato** salvo dove indicato.

**Pubblico / non autenticato**

| Metodo e percorso | Handler | Note |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Serve `catalog/latest.json` da R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Serve `catalog/{version}.json` da R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (default 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anonimo, accesso facoltativo; solo campi di debug nella lista consentita |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto anonimo su un articolo → **D1**, non Supabase |

> Il caricamento degli allegati (l'ex route `PUT /v1/bug-reports/:id/attachment`) è stato **rimosso**; gli screenshot e i dettagli aggiuntivi sono gestiti tramite un canale di supporto mediato da una persona. Il Worker si limita a eliminare con il massimo impegno qualsiasi oggetto allegato legacy durante l'eliminazione dell'account.

**Account (richiesto un token di accesso Supabase)**

| Metodo e percorso | Handler | Note |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Convalida il token di accesso dell'utente, elimina le sue righe + eventuali oggetti allegato R2 legacy, poi elimina l'utente di Supabase Auth con il ruolo di servizio |
| `GET /v1/account/qa-access` | `accountQAAccess` | Restituisce `is_developer` dalla lista consentita `qa_developers`, accessibile solo dal ruolo di servizio |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Esegue l'upsert di una riga `entitlements` (piano `lava_security_plus`) da una JWS StoreKit verificata dal client |

> **Nessuna route `/v1/backup`.** Il ripristino del backup assistito da passkey è ora **a conoscenza zero** e interamente lato client (vedi §4.3 e §5); il Worker non ha route `/v1/backup/*` né codice WebAuthn/passkey.

**Admin (una chiave API admin tramite `requireAdmin`)**

| Metodo e percorso | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Gli endpoint HTTP admin sono protetti da una chiave API admin. Il percorso di sincronizzazione pianificato (cron) **non** chiama queste route HTTP — invoca la logica di sincronizzazione (`syncBlocklistSources`) direttamente all'interno dell'handler `scheduled`.

**Host di sonda QA** — le richieste ai quattro host `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) vengono intercettate prima del routing e restituiscono un PNG `no-store` 1×1 tramite `getQAProbePixel`. Questi non vengono scritti su Supabase o R2.

### 2.2 Binding e cron

- **Binding R2** — `catalog/latest.json`, `catalog/{version}.json`, e il cursore round-robin `catalog/scheduled-sync-cursor.json`. **Non memorizza mai i byte delle blocklist di terze parti.** (Gli oggetti allegato legacy delle segnalazioni di bug vengono solo ed esclusivamente *eliminati* — con il massimo impegno durante l'eliminazione dell'account — mai scritti.)
- **Binding D1** — righe anonime e in sola aggiunta `article_id` / `locale` / `vote` / `path`; tenute separate da Supabase per scelta progettuale.
- **Cron (`scheduled`)** — l'handler si dirama in base all'id del cron:
  - **Ogni 6 ore** — sincronizza **una** sola fonte per esecuzione, a rotazione tramite il cursore R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), poi ripubblica il catalogo. Distribuire il carico evita di sovraccaricare tutte le fonti a monte contemporaneamente.
  - **Ogni 2 minuti** — esegue un percorso interno di triage delle segnalazioni di bug che promuove le nuove segnalazioni anonime in una coda interna di un tracker delle issue, facendo avanzare il proprio cursore di riferimento. Questo è uno strumento operativo interno; gli identificatori del tracker delle issue e delle notifiche sono configurazione, non fanno parte dell'API pubblica.

## 3. Catalogo e applicazione della modalità source-url-only

Questa è la parte del backend più specifica all'impostazione di conformità di Lava, quindi riceve un rinforzo lato server.

### 3.1 Il modello source-url-only

> **Source-url-only:** modello di distribuzione conforme a GPL/proprietà intellettuale: Lava pubblica solo l'URL a monte + gli hash accettati; il dispositivo scarica/analizza gli elenchi da sé. Lava **non** memorizza, replica, trasforma o serve mai i byte delle blocklist di terze parti.

Ogni riga `blocklist_sources` riporta `redistribution_mode`, il cui unico valore consentito è `"source_url_only"`. Il catalogo che il dispositivo legge (`/v1/catalog`, `schema_version` 2) suddivide le voci in `sources[]` e `guardrails[]`; ogni voce riporta l'`source_url` a monte più gli `accepted_source_hashes` (SHA-256 + dimensione in byte + numero di voci + `reviewed_at` + stato `accepted`) — mai i byte degli elenchi. Vedi `formatCatalogEntry`.

> **Abbandonato:** un progetto precedente replicava i file degli elenchi GPL con i byte preservati in R2 (il piano di conformità GPL-raw-R2). È stato **superato il 2026-05-25** dalla modalità source-url-only. Lava non memorizza né serve più i byte delle blocklist di terze parti. Il nome della tabella `mirror_events` è un residuo legacy di quel progetto abbandonato — ora è semplicemente il registro di audit di sincronizzazione/pubblicazione.

### 3.2 Come il Worker la applica in scrittura

Il percorso di sincronizzazione (`syncOneBlocklist`, admin e cron) scarica ogni `source_url` a monte, normalizza/convalida **localmente nel Worker solo per calcolare i metadati** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), scrive una riga `blocklist_versions` e ripubblica. Le chiavi di memorizzazione dei byte sono fissate a null in modo esplicito:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Una migrazione (`20260525000000_add_blocklist_distribution_mode.sql`) ha reso queste colonne nullable e ha impostato i valori esistenti a null, così la posizione di non-replica viene applicata anche a livello di schema. Il catalogo pubblicato viene scritto in **entrambi** `catalog/{version}.json` e `catalog/latest.json` in R2 (`publishCatalog`).

### 3.3 Protezioni di normalizzazione (solo metadati)

La normalizzazione lato Worker (`normalizeBlocklist`) filtra i domini protetti, applica i limiti e deduplica+ordina. Questo serve esclusivamente a calcolare metadati affidabili; il **dispositivo riconvalida gli hash accettati** quando scarica l'elenco reale, quindi questo da solo non è un confine di sicurezza. Costanti principali:

- `PROTECTED_SUFFIXES` — rimuove qualsiasi regola che corrisponda ai domini Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, così una fonte a monte compromessa non può bloccare l'infrastruttura di Lava o i provider di accesso.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 Cosa è pubblicabile

`isPublicBlocklistSource` pubblica una fonte solo quando `status` è `sync` o `nosync`, `redistribution_mode === "source_url_only"`, **e** `isAllowedLaunchGPLSource` passa. Il controllo launch-GPL (`isAllowedLaunchGPLSource`) consente liberamente le fonti non GPL ma limita le fonti GPL-3.0 ai prefissi `list_id` `hagezi-` o `oisd-`.

### 3.5 Fonti predefinite e default-enabled

Le fonti curate vengono inserite come metadati source-url-only tramite migrazioni (HaGeZi, OISD, Block List Project, Phishing.Database, AdGuard). La migrazione a basso rischio (`20260526000000_low_risk_blocklist_sources.sql`) inizialmente ha inserito `blocklistproject-basic` (Unlicense) con `default_enabled = true`, ha forzato **tutte le fonti GPL (HaGeZi/OISD) a `default_enabled = false`** in attesa del parere legale, e ha messo da parte AdGuard DNS Filter in `license_review`. **Quel primo inserimento con default Basic è stato in seguito superato** — la migrazione di allineamento qui sotto porta Basic a `false` e Phishing + Scam a `true` (il default attualmente servito). Stato: **Implementato**.

> **I default del catalogo corrispondono al client.** L'insieme `default_enabled` del catalogo è ora **{Block List Project Phishing, Block List Project Scam}**, in linea con i default consigliati su iOS (`AppConfiguration.lavaRecommendedDefaults`, in `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`). Una migrazione imposta `blocklistproject-basic default_enabled = false` e `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`, così i metadati serviti sono fedeli alla realtà. (la decisione di allineamento è ora rilasciata.) Nota che `default_enabled` è informativo: il vero limite di livello è il **budget di regole di filtraggio (Free 500K / Plus 2M)**, non il numero di elenchi. La motivazione legale per pubblicare gli URL (non i byte) è in [Decisione di conformità GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres

Un progetto Supabase Postgres. L'RLS è abilitato su **ogni** tabella pubblica.

### 4.1 Schema di base

`20260516034033_backend_core.sql` crea le fondamenta (RLS abilitato su tutte e 7 le tabelle pubbliche):

- **`profiles`, `user_settings`, `entitlements`** — stato dell'account per utente. Un trigger `handle_new_user()` crea automaticamente le righe `profiles` + `user_settings` all'inserimento in `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — le tabelle dei metadati del catalogo. Una fonte è un elenco a monte curato (`list_id`, `source_url`, licenza, rischio, `default_enabled`, `status`, `redistribution_mode`); una versione è i metadati di uno snapshot sincronizzato (hash, `entry_count`, `byte_size`), collegata tramite `latest_version_id`.
- **`mirror_events`** — registro di audit accessibile solo dal ruolo di servizio per gli eventi `sync` / `catalog_publish` (nome legacy; vedi §3.1).
- **`bug_reports`** — segnalazioni anonime accessibili solo dal ruolo di servizio.

Migrazioni successive aggiungono **`user_backups`** (§4.3) e **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modello RLS

| Tabella/e | Policy | Effetto |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | per utente `auth.uid() = user_id` | ogni utente vede solo le proprie righe |
| `blocklist_sources` | lettura pubblica dove `status in ('sync','nosync')` (`backend_core.sql:262-266`) | chiunque può leggere le fonti curate idonee alla sincronizzazione |
| `blocklist_versions` | lettura pubblica dove `validation_status = 'published'` (`backend_core.sql:268-272`) | chiunque può leggere i metadati delle versioni pubblicate |
| `bug_reports`, `mirror_events` | `using(false)` esplicito (`20260516034136_backend_core_advisor_fixes.sql`) | nessun accesso anon/authenticated — il Worker usa il ruolo di servizio |
| `qa_developers` | RLS attivo + **revoca di tutto da anon, authenticated** | accessibile solo dal ruolo di servizio; la lista consentita QA non è mai leggibile dal client |

La distinzione conta: le segnalazioni di bug anonime devono essere *inseribili* dal Worker senza essere *leggibili* dai client, e la lista consentita QA deve poter essere letta solo dal ruolo di servizio.

### 4.3 Auth e l'envelope di backup cifrato

L'**auth** è facoltativa. L'accesso è **solo Apple + Google** (email/password è **Abbandonato**). Entrambi usano il grant nativo `id_token` scambiato presso Supabase Auth `auth/v1/token?grant_type=id_token` con un nonce sottoposto a hash; l'app memorizza solo la sessione risultante in locale sul dispositivo, nel Keychain. Il flusso lato client risiede nell'app iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — vedi [Account e backup](./accounts-and-backup.md) per il modello completo di account/backup.

> **Backup a conoscenza zero:** envelope AES-256-GCM lato client; su Supabase `user_backups` (RLS per utente) viene caricato solo il testo cifrato + metadati non segreti. Il server non può decifrare senza un segreto detenuto dall'utente.

Il fatto cruciale lato backend: **il client iOS legge/scrive `user_backups` direttamente tramite Supabase PostgREST sotto l'RLS per utente** (upsert su `user_id`, delimitato dal token di accesso). Sul Worker non c'è **alcuna route `/v1/backup`**. Il Worker tocca `user_backups` esattamente una volta: per eliminarla durante l'eliminazione dell'account (`deleteAccount`).

`user_backups` memorizza solo testo cifrato opaco + metadati dell'envelope non segreti (parametri/salt del KDF, nonce, etichette degli slot di chiave, suggerimenti sullo schema del client). Limiti di dimensione (`20260605000000_tighten_backup_envelope_constraints.sql`): testo cifrato ≤ 262144 byte (256 KiB) / ≤ 349528 caratteri, metadati ≤ 32768 byte (32 KiB). Il database non memorizza mai impostazioni in chiaro, password, frasi o chiavi.

### 4.4 Eliminazione dell'account

`POST /v1/account/delete` convalida il token di accesso dell'utente, poi elimina le righe `bug_reports` (e qualsiasi oggetto allegato R2 legacy corrispondente), `user_backups`, `entitlements`, `user_settings` e `profiles`, e infine elimina l'utente di Supabase Auth tramite l'endpoint `/admin/users` con il ruolo di servizio. Restituisce solo uno stato di eliminazione + i provider collegati. Stato: **Implementato** (il frontmatter del piano riporta `status: Done` e il file è in `plans/implemented/`; un'annotazione **nel corpo** ormai obsoleta dice ancora "Backlog", ma la cartella della corsia + la presenza del codice lo rendono rilasciato).

### 4.5 Mirroring delle abilitazioni App Store

`POST /v1/account/entitlements/app-store-sync` esegue l'upsert di una riga `entitlements` (piano `lava_security_plus`) da una JWS di transazione StoreKit verificata dal client, in conflitto per `user_id`. Lo `verification_status` memorizzato è letteralmente `"client_verified_storekit"` — il server **non** verifica nuovamente la JWS. ID prodotto consentiti: `lava_security_plus_{monthly,yearly,lifetime}`.

> Il mirroring è **Implementato**; la **verifica lato server della JWS è Pianificata** (non ancora costruita). La JWS firmata viene memorizzata per una verifica successiva. Nota il modello dei livelli altrove: l'abilitazione dell'app è locale (`isPaid`), **senza ancora alcuna sincronizzazione backend** come fonte di verità — questa riga è un mirror, non il controllo d'accesso.

## 5. Ripristino assistito da passkey (a conoscenza zero)

Il ripristino del backup assistito da passkey è **a conoscenza zero** e interamente lato client. Il materiale della chiave di ripristino è derivato sul dispositivo dall'output **WebAuthn PRF / hmac-secret** della passkey; il server **non** memorizza alcun segreto di ripristino, **non** registra alcuna passkey e **non** emette alcuna challenge WebAuthn. Non esiste un percorso di escrow controllato dal server.

Le tabelle di escrow usate da un progetto precedente (`backup_passkey_recovery`, `backup_passkey_challenges`) sono state rimosse prima del lancio, e il Worker non contiene route `/v1/backup/*` né codice WebAuthn/passkey. (Una voce `@simplewebauthn/server` resta nel `package.json` del Worker come dipendenza inutilizzata residua.)

Il lato client risiede nell'app iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` guida la creazione/assertion della passkey con capacità PRF, e `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva lo slot dall'output hmac-secret. L'output PRF viene letto solo durante l'assertion e non lascia mai il dispositivo. Un provider di passkey senza PRF non può sostenere uno slot a conoscenza zero, quindi la configurazione fallisce subito e l'utente ripiega su una frase di ripristino. Stato: **Implementato**.

## 6. lavasec-email Worker

Solo ricezione e inoltro. Inoltra `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` a una casella di posta dell'operatore verificata, rifiuta i destinatari sconosciuti e la posta oltre i 10 MiB, e **non memorizza i corpi delle email**. Le risposte automatiche di supporto sono già codificate ma bloccate dietro l'invio email a pagamento di Cloudflare (rinviato). Le costanti di routing risiedono in `email-service.ts:9` (`ROUTED_RECIPIENTS`); l'handler in entrata è `handleInboundEmail`. Stato: **Implementato** (il percorso di risposta automatica **Pianificato**/rinviato).

## 7. Configurazione e deploy

- **La configurazione è `wrangler.toml`, che è in gitignore**; `wrangler.toml.example` è il template versionato. Tratta il `wrangler.toml` locale come riferimento autorevole per i valori specifici dell'ambiente.
- **Vars** (non segrete, in `[vars]`): l'URL di Supabase, l'origine pubblica dell'API (`https://api.lavasecurity.app`), il TTL della cache del catalogo (default 300s), un limite di dimensione per le segnalazioni di bug, un interruttore per l'audit dell'eliminazione account, e un flag di accelerazione del runtime Workers. Il triage interno delle segnalazioni di bug aggiunge una chiave della coda di triage interna e un'origine della dashboard usata per comporre i link di triage.
- **Secrets** (tramite `wrangler secret put`): una credenziale del ruolo di servizio di Supabase, una chiave API admin e — per il percorso di triage delle segnalazioni di bug — una chiave API del tracker delle issue e un webhook opzionale di notifica chat.
- **Il deploy è manuale**: `npm run deploy` → `wrangler deploy`. Non c'è CI per il Worker.
- **Routing Cloudflare**: `lavasecurity.app` resta su Pages; `api.lavasecurity.app` e `*.qa-probe.lavasecurity.app` puntano a questo Worker.
- **Compatibilità**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` è impostato nelle vars ma non è referenziato dal codice del Worker; è un flag di accelerazione del runtime Workers, non un'impostazione dell'applicazione.

## 8. Invarianti di privacy (cosa c'è e cosa non c'è)

Una rapida checklist per chiunque estenda il backend — nessuna di queste può essere violata di nascosto:

1. **Nessuna telemetria DNS/di navigazione.** Non c'è alcuna tabella per le normali query DNS o per la telemetria per dominio. Il filtraggio resta sul dispositivo.
2. **Nessun byte di blocklist di terze parti** in R2 o Postgres — solo `source_url` + hash accettati (§3).
3. **`user_backups` è opaca** — solo testo cifrato + metadati non segreti; è il client (non il Worker) a scriverla sotto RLS (§4.3).
4. **Isolamento del ruolo di servizio** per `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Tutti i percorsi di backup sono a conoscenza zero** — incluso il ripristino assistito da passkey, il cui materiale di chiave è derivato lato client dall'output WebAuthn PRF/hmac-secret. Il server non memorizza alcun segreto di ripristino e non esegue alcun WebAuthn (§5).

## Vedi anche

- [Panoramica del sistema](./system-overview.md) — l'intero sistema in una pagina, inclusi i confini di fiducia.
- [Client iOS](./ios-client.md) — il lato dispositivo che consuma questo backend.
- [Account e backup](./accounts-and-backup.md) — auth lato client, l'envelope AES-256-GCM, gli slot di chiave e le frasi di ripristino.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — il lato dispositivo del catalogo: download diretto dalla fonte a monte, parsing/normalizzazione e il budget di regole di filtraggio.
- [Decisione di conformità GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — perché il catalogo pubblica gli URL, non i byte.
- **Livelli e monetizzazione** (interno) — il budget di regole di filtraggio (Free 500K / Plus 2M) che è il vero controllo Free/Plus.
- **Registro dei rischi di proprietà intellettuale** (interno) — la motivazione di proprietà intellettuale/conformità dietro la modalità source-url-only.
