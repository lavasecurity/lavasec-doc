---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Panoramica del sistema

> **Destinatari:** ingegneri. Questa è l'intera Lava Security in una sola pagina: quali sono le parti, come i dati si muovono tra di esse e dove si collocano i confini di fiducia. La documentazione per singolo componente entra più nel dettaglio; questa esiste perché tu possa tenere a mente il sistema nel suo insieme prima di leggerle.
>
> **Autorità:** quando questo documento e un piano sono in disaccordo, **vince il codice**. Lo stato riflette la realtà confermata dal codice, non l'aspirazione del piano. Vedi la [Legenda degli stati](#8-status-legend) in fondo.

## 1. Il prodotto in una riga

Lava Security è un'app iOS privacy-first che filtra il DNS **localmente sul dispositivo** attraverso un packet tunnel NetworkExtension, bloccando domini dannosi e indesiderati per utenti non tecnici (genitori, persone anziane), con la protezione di base gratuita per sempre e senza alcun account richiesto.

## 2. La promessa sulla privacy (canonica)

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva solo metadati del catalogo, un backup cifrato per-utente opaco e i dati diagnostici anonimizzati che scegli di inviare.

Tutto ciò che segue mantiene vera quella frase. L'architettura è deliberatamente ridotta sul lato server: il dispositivo fa il lavoro e il backend non vede mai una query.

## 3. Componenti

### Client iOS (tre target eseguibili + codice condiviso, un App Group `group.com.lavasec`)

| Componente | Bundle / posizione | Ruolo | Stato |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Shell dell'app SwiftUI; punto d'ingresso, navigazione a due tab Guard + Settings (Filtro/Attività sono schermate di dettaglio di Guard; Network Activity spostata sotto Settings → Advanced). | Implementato |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; il motore di filtraggio/risoluzione DNS sul dispositivo. Soggetto al **tetto di memoria iOS di ~50 MiB per estensione**. | Implementato |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity WidgetKit (schermata di blocco + Dynamic Island). | Implementato |
| **Shared/** | `Shared/` | Sorgenti cross-target: App Group, command service, mascotte, attributi/intent della Live Activity. | Implementato |

**Controller lato app (in LavaSecApp):**

- **AppViewModel** — il controller lato app (god-object): possiede il ciclo di vita di `NETunnelProviderManager`, la persistenza dello stato condiviso, la messaggistica con il provider, la riconciliazione della Live Activity, la sincronizzazione del catalogo, il backup, StoreKit e l'autenticazione.
- **RootView** — `TabView` a due tab (Guard + Settings), con Filtro e Attività raggiungibili come schermate di dettaglio sotto Guard; controlla l'onboarding, ospita gli overlay di blocco di sicurezza / mascheramento privacy.
- **SecurityController** — passcode (SHA256 con salt nel Keychain) + biometria + protezione per-superficie.
- **LavaLiveActivityController** — riconciliatore a singola Activity, deduplicato e protetto da revisione.
- **OnboardingFlowView** — flusso di primo avvio multipagina (6 pagine: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (pacchetto SwiftPM agnostico rispetto alla piattaforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — filtro compilato + precedenza delle decisioni; la forma compatta è l'artefatto su disco mmap-friendly che il tunnel legge.
- **DNSQueryDispatcher** — precedenza delle query: bootstrap > pause > filter.
- **ResolverOrchestrator** — routing del trasporto, degradazione a DNS in chiaro, failover per-endpoint, fallback al DNS del dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — esecutori dei trasporti cifrati.
- **FeatureLimits** (in `SubscriptionPolicy.swift`) — i tetti di tier (fonte di verità), tramite i membri statici `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — calcolo dei guardrail del dispositivo + applicazione autorevole del budget post-unione.
- **BlocklistCatalogSync / BlocklistParser** — fetch del catalogo, download diretto dall'upstream, parse/normalizzazione/dedup locale, filtro dei domini protetti.
- **GuardianMascotAnimation** — grafo a 7 stati della mascotte (renderizzato da `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — crittografia del backup + payload.
- **SupabaseIDTokenAuth** — autenticazione `id_token` con URLRequest grezza (nessun SDK).

### Backend

| Componente | Ruolo | Stato |
|---|---|---|
| **Worker lavasec-api** | Cloudflare Worker (`api.lavasecurity.app`): letture del catalogo, sync + pubblicazione admin/cron della blocklist, segnalazioni di bug anonime, eliminazione account, mirroring delle entitlement App Store, sonde QA. | Implementato |
| **Worker lavasec-email** | Forwarder Cloudflare Email Routing solo-ricezione per `@lavasecurity.app`; rifiuta posta sconosciuta/sovradimensionata. | Implementato |
| **Supabase Postgres** | Account, `user_backups`, metadati del catalogo, tabelle solo-service-role; **RLS su ogni tabella pubblica**. | Implementato |
| **Cloudflare R2** (il bucket R2 di produzione, un bucket di preview separato per lo staging) | Snapshot del catalogo + il cursore di sync round-robin. **Mai** i byte di blocklist di terze parti; la rotta di upload degli allegati delle segnalazioni di bug è stata rimossa (gli oggetti legacy vengono eliminati solo all'eliminazione dell'account). | Implementato |
| **Cloudflare D1** (il database help-feedback) | Voti di feedback anonimi append-only sugli articoli di aiuto. | Implementato |

## 4. Diagramma del flusso dati

La proprietà singola più importante: **il percorso del resolver DNS cifrato (lato destro) non tocca mai il backend di Lava (in basso).** Il dispositivo recupera i *metadati* del catalogo dal Worker, ma i *byte* delle liste e il flusso di query vanno direttamente a terze parti.

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

## 5. Flussi di dati

### A. Il percorso DNS (per query, tutto sul dispositivo) — Implementato

Questo è l'hot path e il nucleo della privacy. Gira interamente dentro `LavaSecTunnel`; nulla qui raggiunge i server di Lava.

1. Il packet tunnel intercetta una query DNS (server DNS del tunnel `10.255.0.1`).
2. **`DNSQueryDispatcher`** applica la precedenza delle query: **bootstrap > pause > filter**. Bootstrap-first è un'invariante rigida: l'hostname del resolver stesso viene risolto prima di qualsiasi filtraggio, così che il resolver non possa mai bloccare se stesso.
3. Se non è bootstrap e non è in pausa, il dominio viene valutato rispetto a **`CompactFilterSnapshot`** (caricato dall'App Group via `Data(contentsOf:options:[.mappedIfSafe])` con mmap zero-copy). La precedenza delle decisioni è **threat guardrail > allowlist locale (eccezioni consentite) > blocklist > default-allow**; i domini non validi vengono bloccati.
4. **Bloccato** → il tunnel risponde localmente (nessun contatto con l'upstream). **Consentito** → la query viene passata a **`ResolverOrchestrator`**.
5. `ResolverOrchestrator` instrada al trasporto configurato — **`DoH3` / `DoT` / `DoQ` / DNS in chiaro (`IP`)** — con failover per-endpoint dietro un backoff gate, degradazione a DNS in chiaro quando un piano cifrato non ha endpoint, e **fallback al DNS del dispositivo** quando il primario non restituisce risposta e il piano lo consente.
6. La risposta del resolver viene restituita al sistema operativo. Il flusso di query dell'utente va solo al **resolver pubblico scelto dall'utente**, mai a Lava.

Note sui trasporti (convenzioni testuali): `DoH3` (senza slash) viene annotato **solo quando una negoziazione h3 è effettivamente osservata** — preferito, mai promesso. **`DoT`** mette in pool fino a 4 NWConnection per endpoint con refresh per inattività + un retry su connessione fresca. **`DoQ`** apre una **connessione QUIC fresca per query** (nessun riuso); il pool a 4 corsie fornisce concorrenza, non riuso dell'handshake — il riuso delle connessioni è stato costruito, testato su dispositivo e **annullato** (rimandato fino al deployment floor di iOS-26). Vedi [Filtraggio DNS e Blocklist](./dns-filtering-and-blocklists.md).

### B. Fetch del catalogo + caricamento della blocklist (solo-source-url) — Implementato

Come le regole del filtro arrivano sul dispositivo. Lava è un distributore **solo-source-url**: pubblica solo l'URL dell'upstream + gli hash accettati e **non memorizza, mirrora, trasforma o serve mai i byte di blocklist di terze parti.**

1. Il dispositivo recupera i **metadati** del catalogo dal Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servito direttamente da R2 (`catalog/latest.json`), suddiviso in `sources[]` + `guardrails[]`, con ogni voce che porta `source_url` + `accepted_source_hashes`.
2. Per ogni source abilitata, il dispositivo scarica i **byte della lista direttamente da `source_url`** (l'upstream — HaGeZi, OISD, Block List Project, ecc.), **non** da Lava.
3. Il dispositivo effettua il parse dei byte recuperati localmente entro i tetti di dimensione/regole. Le liste della community vengono accettate così come servite su TLS — gli `accepted_source_hashes` del catalogo sono indicativi (identità della cache + audit), non un gate rigido — così una lista ruotata non viene mai rifiutata per essersi discostata da un hash pinnato. Il tier threat-guardrail di Lava resta pinnato all'hash.
4. **`BlocklistParser`** effettua parse/normalizzazione/dedup localmente (formati auto / plain / hosts / adblock / dnsmasq), poi **`DomainRuleSet.lavaSecProtectedDomains`** rimuove i domini protetti (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) così che una lista upstream non possa mai bloccare i domini di Lava/Apple/provider di identità.
5. **`FilterSnapshotPreparationService`** unisce l'unione deduplicata ed esegue l'**applicazione autorevole del budget** (prima il cap del dispositivo, poi il tier), quindi scrive `filter-snapshot.compact` nell'App Group.
6. `AppViewModel` invia un messaggio del provider `reload-snapshot`; il tunnel ricarica.

Il lato Worker rispecchia questo: la sua sync admin/cron recupera ogni upstream, ne calcola hash/conteggio, scrive `raw_r2_key = null` / `normalized_r2_key = null` e ripubblica solo i metadati. Il modello del catalogo blocklist e il percorso di sync del backend sono trattati in [Filtraggio DNS e Blocklist](./dns-filtering-and-blocklists.md) e [Backend e Dati](./backend-and-data.md).

**Modello di budget (due livelli):**
- **Guardrail del dispositivo (per tutti, mai un paywall):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 regole** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule` — un target di 32 MB sotto il tetto NE di ~50 MiB. Le configurazioni fuori budget vengono rifiutate in modo deterministico anziché lasciare che il tunnel finisca in jetsam.
- **Tetto di tier (`FeatureLimits`):** **Free 500K regole / Plus 2M regole**, che vincola sotto il guardrail del dispositivo. Questo ha sostituito il vecchio cap sul **conteggio** delle liste abilitate (free 3 / paid 10) — i cap sul conteggio delle liste sono obsoleti.

> **Fonte di verità sull'abilitazione di default:** il default gratuito spedito è **Block List Basic** (`OnboardingDefaults.lavaRecommendedDefaults`). Viene derivato sul dispositivo dal flag `defaultEnabled` di ciascuna source curata (`BlocklistSource.recommendedDefaultSourceIDs`), che rispecchia la colonna `default_enabled` del catalogo backend generata dalla stessa specifica canonica del catalogo.

### C. Backup (zero-knowledge, opt-in) — Implementato

Opzionale, vincolato all'account, e gli unici dati utente che finiscono nel backend — come **testo cifrato opaco**.

1. L'utente può facoltativamente accedere (solo Apple o Google; **email/password è Abbandonato**) tramite `id_token` nativo scambiato presso Supabase Auth (`grant_type=id_token`, nonce hashato). Viene memorizzata solo la sessione Supabase risultante, locale al dispositivo, nel Keychain.
2. **`BackupConfigurationPayload`** assembla un testo in chiaro minimizzato (ID delle blocklist abilitate, domini consentiti/bloccati, preferenze del resolver, preferenze dei log locali, ledger LavaGuard). **Esclude** `isPaid`, QA, diagnostica e le blocklist complete.
3. **`ZeroKnowledgeBackupEnvelope`** lo sigilla con **AES-256-GCM** sotto una chiave di payload casuale di 32 byte; quella chiave viene avvolta in **key slot** per-segreto via **PBKDF2-HMAC-SHA256 (210k iter)** — slot device-secret, slot di recupero assistito, slot passkey opzionale. Lo slot passkey opzionale viene avvolto con un output **WebAuthn PRF / `hmac-secret`** di un authenticator (derivato via HKDF); quell'output non lascia mai il client, quindi lo slot passkey è genuinamente zero-knowledge — nessun valore detenuto dal server lo scarta (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** carica **solo testo cifrato + metadati non segreti** su Supabase `user_backups` direttamente via PostgREST, con ambito per-utente tramite **RLS**. (Non c'è alcuna rotta di upload del Worker; il Worker tocca `user_backups` solo per eliminarlo durante l'eliminazione dell'account.)
5. **Recupero:** ripristino fluido sullo stesso dispositivo tramite lo slot device-secret; fuori dal dispositivo tramite la **frase di recupero CVCV a 8 parole** (~105 bit) combinata con una share di recupero detenuta dal server via SHA256 (a due fattori — nessuna delle due metà da sola decifra); oppure, quando uno slot passkey è stato sigillato, tramite l'output WebAuthn PRF / `hmac-secret` lato client (nessun valore detenuto dal server coinvolto). Il server non registra mai passkey, non emette challenge WebAuthn, né memorizza alcun segreto di recupero.

Vedi [Account e Backup](./accounts-and-backup.md).

### D. Piano di controllo app ↔ estensione — Implementato

Tre processi (app, tunnel, widget) si coordinano attraverso l'App Group `group.com.lavasec`:

- **Il controllo = messaggi del provider NETunnelProviderSession**, **non** notifiche Darwin. `AppViewModel` codifica un `LavaSecProviderMessage {kind, operationID}` e chiama `session.sendProviderMessage`; lo `handleAppMessage` del tunnel fa switch sul kind (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **I file condivisi** trasportano regole/config/health (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); gli **store UserDefaults condivisi** (`ProtectionSessionStore` / `ProtectionPauseStore`) trasportano lo stato di sessione + pausa.
- **`LavaProtectionCommandService`** esegue i comandi di pausa/ripresa di Live-Activity / AppIntent sotto un file lock `flock` con dedup di revisione e diniego quando è richiesta l'autenticazione; **la riconnessione lo bypassa** per riavviare il tunnel direttamente (`startVPNTunnel`).
- **Connect-On-Demand** viene abilitato solo *dopo* che il tunnel conferma la connessione, mai all'installazione del profilo — così un profilo di onboarding appena installato non può portare su un tunnel non-disattivabile.

Vedi [Client iOS](./ios-client.md).

## 6. Confini di fiducia e progettazione che preserva la privacy

| # | Confine | Cosa lo attraversa | Cosa deliberatamente NON lo attraversa |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolver DNS pubblico** | Le query DNS consentite (cifrate: DoH3/DoT/DoQ, o IP in chiaro) vanno al resolver scelto dall'utente. | Lava non vede mai il flusso di query; non è affatto in questo percorso. |
| 2 | **Dispositivo ↔ host blocklist upstream** | Il dispositivo scarica i byte della lista direttamente da `source_url`. | Lava non fa mai da proxy, mirror o memorizza i byte di blocklist di terze parti. |
| 3 | **Dispositivo ↔ Worker lavasec-api** | Letture dei **metadati** del catalogo; segnalazioni di bug anonime opt-in; mirror delle entitlement; eliminazione account. | Nessuna query DNS, nessuna cronologia di navigazione, nessuna impostazione in chiaro. |
| 4 | **Dispositivo ↔ Supabase** | **Envelope di backup cifrato** opt-in (solo testo cifrato, PostgREST sotto RLS); righe dell'account. | Il server non può decifrare il backup senza un segreto detenuto dall'utente. |
| 5 | **App ↔ estensione tunnel** (sul dispositivo) | Messaggi del provider + file/default dell'App Group. | Il tunnel fallisce in modalità **closed** al cold start senza uno snapshot riutilizzabile. |

**Principi di progettazione che preservano la privacy, fondati su quanto sopra:**

- **Filtraggio local-first.** Il motore decisionale e il resolver girano dentro l'estensione NE sul dispositivo. Il backend è metadata-only per costruzione — non ci sono tabelle per le query DNS di routine o la telemetria per-dominio.
- **Nessun account richiesto per la protezione.** La protezione di base è gratuita per sempre; autenticazione e backup sono rigorosamente opt-in.
- **Distribuzione solo-source-url.** Disaccoppia Lava dai byte delle liste di terze parti (conformità GPL/IP + sicurezza App Review) e mantiene un guardrail CI che impone "nessun codice di mirror, nessun URL di artefatti Lava, nessuna scrittura di byte su R2."
- **Backup zero-knowledge a riposo.** AES-256-GCM lato client; il server detiene testo cifrato + metadati KDF + una share di recupero, mai il testo in chiaro, la frase di recupero o la chiave scartata. Lo slot passkey opzionale viene avvolto con un output WebAuthn PRF / `hmac-secret` lato client, quindi anch'esso è zero-knowledge — nessun valore detenuto dal server lo scarta.
- **Segreti locali al dispositivo.** Il materiale di sblocco del backup usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — non sincronizzato su iCloud, non nei backup del dispositivo.
- **Isolamento del service-role.** `bug_reports`, `mirror_events` e `qa_developers` sono revocati dai ruoli PostgREST anon/authenticated; solo il Worker (service role) li tocca.
- **La sicurezza non è mai in vendita.** Il pagamento sblocca **solo la personalizzazione**. Non bypassa mai il **threat guardrail** non-aggirabile, la cui integrità è imposta dagli hash di source SHA256 accettati (non da una firma del server). La precedenza è coerente ovunque: **threat guardrail > allowlist locale (eccezioni consentite) > blocklist > default-allow.**

## 7. Documentazione per singolo componente

> Questi sono i documenti gemelli nel doc-set dell'architettura. Il motore di filtraggio DNS e il catalogo blocklist sono documentati insieme in un unico file.

- [Client iOS](./ios-client.md) — target, App Group, piano di controllo, modello dello stato di protezione, onboarding, Live Activity.
- [Filtraggio DNS e Blocklist](./dns-filtering-and-blocklists.md) — filter snapshot, precedenza delle decisioni, trasporti del resolver (DoH3/DoT/DoQ), budget di memoria, mmap; più il modello di catalogo solo-source-url, fetch del catalogo, parse/normalizzazione locale, filtro dei domini protetti e budget di tier.
- [Account e Backup](./accounts-and-backup.md) — autenticazione Apple/Google, envelope zero-knowledge, key slot, frase di recupero, recupero con passkey WebAuthn-PRF lato client.
- [Backend e Dati](./backend-and-data.md) — Worker lavasec-api + lavasec-email, schema Supabase + RLS, R2/D1, deployment.

## 8. Legenda degli stati

Questo doc-set usa un unico vocabolario di stato. La **cartella della lane è lo stato autorevole**; un frontmatter obsoleto dentro un piano è un bug della documentazione, non uno stato. **Il codice prevale sui piani.**

| Stato | Significato | Lane del piano | Codice |
|---|---|---|---|
| **Implementato** | Spedito e confermato nel codice | `plans/implemented/` | presente e cablato |
| **In corso** | Attivamente in costruzione; parzialmente atterrato | `plans/inflight/`, `plans/under_review/` | parzialmente presente |
| **Pianificato** | Progettato, non costruito | `plans/backlog/` | assente |
| **Abbandonato** | Rifiutato o annullato | `plans/dropped/` (o commit annullato) | assente / rimosso |

**Stato delle cose menzionate in questa pagina:**

- **Implementato:** i quattro target iOS + App Group; piano di controllo a messaggi del provider; filtraggio DNS sul dispositivo con trasporti DoH3/DoT/DoQ/IP; fetch del catalogo solo-source-url + parse locale; budget delle regole del filtro (Free 500K / Plus 2M) + guardrail del dispositivo di ~3,26M; onboarding multipagina; sicurezza con passcode/biometria; singola Live Activity deduplicata; backup zero-knowledge; autenticazione Apple + Google; eliminazione account; mirroring delle entitlement; sonde QA; il layer di token `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluso il modello di profondità `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), i modificatori `.lavaTier(_:)` / `.lavaTierMetadata()` cablati in superfici rappresentative (es. `SettingsView`), e i token `dangerRed` e `LavaSpacing` — bloccati da `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **In corso:** il continuo rollout del layer di token del design-system su più superfici (il modello di profondità `LavaTier` e il layer di token vengono spediti — vedi sotto — ma un `LavaColorRole` dedicato non è ancora presente, quindi gli accenti si risolvono ancora in colori grezzi).
- **Pianificato:** il mini-gioco easter-egg di Lava Guard; espressioni extra della mascotte (la mascotte ha esattamente **7** stati); recupero con passkey pienamente production-ready su dispositivi fisici (Associated Domains / AASA); ri-verifica JWS App Store lato server (`verification_status` è `client_verified_storekit`); un token `LavaColorRole` dedicato così che gli accenti del design-system si risolvano attraverso un ruolo semantico anziché colori grezzi.
- **Abbandonato:** riuso delle connessioni DoQ (connessioni fresche per query); accesso con email/password (solo Apple + Google); il design di mirror GPL raw-R2 (sostituito da solo-source-url).
