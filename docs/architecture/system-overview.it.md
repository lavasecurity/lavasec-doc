---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Panoramica del sistema

> **Pubblico:** ingegneri. Questa è l'intera Lava Security in una sola pagina: quali sono le sue parti, come i dati si muovono tra di esse e dove si trovano i confini di fiducia. La documentazione dei singoli componenti scende più nel dettaglio; questa esiste perché tu possa avere il sistema chiaro in mente prima di leggerla.
>
> **Riferimento:** quando questo documento e un piano sono in disaccordo, **vince il codice**. Lo stato riflette la realtà confermata dal codice, non le aspirazioni del piano. Vedi la [Legenda degli stati](#8-legenda-degli-stati) in fondo.

## 1. Il prodotto in una riga

Lava Security è un'app iOS attenta alla privacy che filtra le richieste DNS **localmente sul dispositivo** attraverso un tunnel a pacchetti NetworkExtension, bloccando i domini dannosi e indesiderati per le persone non esperte di tecnologia (genitori, persone anziane), con la protezione di base gratuita per sempre e senza bisogno di un account.

## 2. La promessa sulla privacy (canonica)

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i propri server e non riceve mai l'elenco dei domini che visiti: il backend conserva solo i metadati del catalogo, una copia di backup cifrata e opaca per ogni utente, e i dati di diagnostica anonimizzati che scegli di inviare.

Tutto ciò che segue serve a mantenere vera quella frase. L'architettura è volutamente ridotta sul lato server: il dispositivo fa il lavoro, e il backend non vede mai una richiesta.

## 3. Componenti

### Client iOS (tre target eseguibili + codice condiviso, un App Group `group.com.lavasec`)

| Componente | Bundle / posizione | Ruolo | Stato |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Guscio dell'app SwiftUI; punto di ingresso, navigazione a due schede Guard + Impostazioni (Filtri/Attività sono schermate di dettaglio di Guard). | Implementato |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; il motore di filtro/risoluzione DNS sul dispositivo. Soggetto al **limite di memoria di ~50 MiB per estensione** di iOS. | Implementato |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity di WidgetKit (schermata di blocco + Dynamic Island). | Implementato |
| **Shared/** | `Shared/` | Sorgenti condivisi tra i target: App Group, servizio comandi, mascotte, attributi/intent della Live Activity. | Implementato |

**Controller lato app (in LavaSecApp):**

- **AppViewModel** — il controller lato app (oggetto onnicomprensivo): gestisce il ciclo di vita di `NETunnelProviderManager`, la persistenza dello stato condiviso, lo scambio di messaggi con il provider, la riconciliazione della Live Activity, la sincronizzazione del catalogo, il backup, StoreKit e l'autenticazione.
- **RootView** — `TabView` a due schede (Guard + Impostazioni), con Filtri e Attività raggiungibili come schermate di dettaglio sotto Guard; controlla l'accesso all'onboarding, ospita le sovrapposizioni di blocco di sicurezza / mascheramento per la privacy.
- **SecurityController** — codice di accesso (SHA256 con salt nel Keychain) + biometria + protezione per ciascuna schermata.
- **LavaLiveActivityController** — riconciliatore a singola Activity, deduplicato e regolato per revisione.
- **OnboardingFlowView** — flusso di primo avvio su più pagine (6 pagine: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (pacchetto SwiftPM indipendente dalla piattaforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — filtro compilato + precedenza delle decisioni; la forma compatta è l'artefatto su disco compatibile con mmap che il tunnel legge.
- **DNSQueryDispatcher** — precedenza delle richieste: bootstrap > pausa > filtro.
- **ResolverOrchestrator** — instradamento del trasporto, degrado a DNS in chiaro, failover per endpoint, ripiego sul DNS del dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — esecutori del trasporto cifrato.
- **FeatureLimits** (in `SubscriptionPolicy.swift`) — limiti per livello (fonte di verità), tramite i membri statici `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — calcolo dei limiti del dispositivo + applicazione autorevole del budget dopo l'unione.
- **BlocklistCatalogSync / BlocklistParser** — recupero del catalogo, download diretto dalla fonte, analisi/normalizzazione/deduplica in locale, filtro dei domini protetti.
- **GuardianMascotAnimation** — grafo di stati della mascotte a 7 stati (renderizzato da `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — crittografia + payload del backup.
- **SupabaseIDTokenAuth** — autenticazione `id_token` con richiesta URLRequest grezza (nessun SDK).

### Backend

| Componente | Ruolo | Stato |
|---|---|---|
| **Worker lavasec-api** | Cloudflare Worker (`api.lavasecurity.app`): letture del catalogo, sincronizzazione e pubblicazione della blocklist da admin/cron, segnalazioni di bug anonime, cancellazione dell'account, mirroring dei diritti d'accesso dell'App Store, sonde QA. | Implementato |
| **Worker lavasec-email** | Inoltratore Cloudflare Email Routing in sola ricezione per `@lavasecurity.app`; rifiuta la posta sconosciuta o troppo grande. | Implementato |
| **Supabase Postgres** | Account, `user_backups`, metadati del catalogo, tabelle accessibili solo al ruolo di servizio; **RLS su ogni tabella pubblica**. | Implementato |
| **Cloudflare R2** (il bucket R2 di produzione, un bucket di anteprima separato per lo staging) | Snapshot del catalogo + il cursore di sincronizzazione a rotazione (round-robin). **Mai** byte di blocklist di terze parti; la route di caricamento degli allegati alle segnalazioni di bug è stata rimossa (gli oggetti preesistenti vengono eliminati solo alla cancellazione dell'account). | Implementato |
| **Cloudflare D1** (il database del riscontro sull'aiuto) | Voti di riscontro anonimi e solo in aggiunta sugli articoli di aiuto. | Implementato |

## 4. Diagramma del flusso dei dati

La proprietà più importante di tutte: **il percorso del resolver DNS cifrato (lato destro) non tocca mai il backend di Lava (in basso).** Il dispositivo recupera i *metadati* del catalogo dal Worker, ma i *byte* delle liste e l'effettivo flusso delle richieste vanno direttamente a terze parti.

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

## 5. Flussi dei dati

### A. Il percorso DNS (per ogni richiesta, tutto sul dispositivo) — Implementato

Questo è il percorso più sollecitato e il cuore della privacy. Si svolge interamente dentro `LavaSecTunnel`; nulla qui raggiunge i server di Lava.

1. Il tunnel a pacchetti intercetta una richiesta DNS (server DNS del tunnel `10.255.0.1`).
2. **`DNSQueryDispatcher`** applica la precedenza delle richieste: **bootstrap > pausa > filtro**. La priorità al bootstrap è un'invariante rigida: il nome host del resolver stesso viene risolto prima di qualunque filtraggio, così il resolver non può mai bloccare se stesso.
3. Se non è bootstrap e non è in pausa, il dominio viene valutato rispetto a **`CompactFilterSnapshot`** (caricato dall'App Group tramite mmap zero-copy con `Data(contentsOf:options:[.mappedIfSafe])`). La precedenza delle decisioni è **guardrail di minaccia > lista di permessi locale (eccezioni consentite) > blocklist > permesso predefinito**; i domini non validi vengono bloccati.
4. **Bloccato** → il tunnel risponde localmente (nessun contatto con la fonte). **Consentito** → la richiesta viene passata a **`ResolverOrchestrator`**.
5. `ResolverOrchestrator` instrada verso il trasporto configurato — **`DoH3` / `DoT` / `DoQ` / DNS in chiaro (`IP`)** — con failover per endpoint dietro un controllo di backoff, degrado a DNS in chiaro quando un piano cifrato non ha endpoint, e **ripiego sul DNS del dispositivo** quando il trasporto principale non restituisce risposta e il piano lo consente.
6. La risposta del resolver viene restituita al sistema operativo. Il flusso delle richieste dell'utente va solo al **resolver pubblico scelto dall'utente**, mai a Lava.

Note sui trasporti (convenzioni testuali): `DoH3` (senza barra) viene indicato **solo quando si osserva effettivamente una negoziazione h3** — preferito, mai promesso. **`DoT`** mantiene un pool di un massimo di 4 NWConnections per endpoint con rinnovo per inattività + un nuovo tentativo con connessione fresca. **`DoQ`** apre una **connessione QUIC fresca per ogni richiesta** (nessun riuso); il pool a 4 corsie offre concorrenza, non riuso dell'handshake — il riuso delle connessioni era stato sviluppato, testato sul dispositivo e **ripristinato** (rinviato fino al livello minimo di distribuzione iOS-26). Vedi [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md).

### B. Recupero del catalogo + caricamento della blocklist (solo URL della fonte) — Implementato

Come le regole del filtro arrivano sul dispositivo. Lava è un distributore **solo URL della fonte**: pubblica solo l'URL della fonte + gli hash accettati e **non memorizza, replica, trasforma o serve mai i byte delle blocklist di terze parti.**

1. Il dispositivo recupera i **metadati** del catalogo dal Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servito direttamente da R2 (`catalog/latest.json`), suddiviso in `sources[]` + `guardrails[]`, dove ogni voce porta con sé `source_url` + `accepted_source_hashes`.
2. Per ogni fonte attiva, il dispositivo scarica i **byte della lista direttamente da `source_url`** (la fonte — HaGeZi, OISD, Block List Project, ecc.), **non** da Lava.
3. Il dispositivo calcola lo SHA256 e accetta solo i byte il cui checksum è in `accepted_source_hashes`; in caso di discrepanza ripiega sull'ultima cache valida o fallisce in modo conservativo (`checksumMismatch`).
4. **`BlocklistParser`** analizza/normalizza/deduplica in locale (formati auto / plain / hosts / adblock / dnsmasq), poi **`DomainRuleSet.lavaSecProtectedDomains`** rimuove i domini protetti (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) così che una lista esterna non possa mai bloccare i domini di Lava/Apple/del provider di identità.
5. **`FilterSnapshotPreparationService`** unisce l'unione deduplicata ed esegue l'**applicazione autorevole del budget** (prima il limite del dispositivo, poi quello del livello), quindi scrive `filter-snapshot.compact` nell'App Group.
6. `AppViewModel` invia un messaggio `reload-snapshot` al provider; il tunnel ricarica.

Il lato Worker fa lo stesso: la sua sincronizzazione admin/cron recupera ogni fonte, ne calcola hash e conteggio, scrive `raw_r2_key = null` / `normalized_r2_key = null` e ripubblica solo i metadati. Il modello del catalogo delle blocklist e il percorso di sincronizzazione del backend sono trattati in [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) e [Backend e dati](./backend-and-data.md).

**Modello del budget (due livelli):**
- **Guardrail del dispositivo (per tutti, mai un paywall):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 regole** = `((32.0 − 4.0) MB × 1.048.576) / 9.0 B/regola` — un obiettivo di 32 MB sotto il limite NE di ~50 MiB. Le configurazioni oltre il budget vengono rifiutate in modo deterministico anziché lasciare che il tunnel venga terminato per memoria (jetsam).
- **Limite del livello (`FeatureLimits`):** **Free 500K regole / Plus 2M regole**, che vincola al di sotto del guardrail del dispositivo. Questo ha sostituito il vecchio limite sul **numero** di liste attive (free 3 / paid 10) — i limiti sul numero di liste sono obsoleti.

> **Avvertenza sui valori predefiniti (vince il codice):** i valori predefiniti gratuiti distribuiti sono **Block List Project Phishing + Scam** (`OnboardingDefaults.lavaRecommendedDefaults`). Sono ricavati sul dispositivo dal flag `defaultEnabled` di ogni fonte curata (`BlocklistSource.recommendedDefaultSourceIDs`), che è la fonte di verità sul dispositivo e rispecchia la colonna `default_enabled` del catalogo del backend. I testi di piano/catalogo che dicono "Block List Basic è l'unico valore predefinito" sono errati per il dispositivo (tracciato internamente).

### C. Backup (zero-knowledge, opzionale) — Implementato

Facoltativo, vincolato all'account, e l'unico dato dell'utente che finisce nel backend — come **testo cifrato opaco**.

1. L'utente, se vuole, accede (solo Apple o Google; **email/password è Abbandonato**) tramite scambio nativo di `id_token` presso Supabase Auth (`grant_type=id_token`, nonce con hash). Viene memorizzata solo la sessione Supabase risultante, in locale sul dispositivo, nel Keychain.
2. **`BackupConfigurationPayload`** assembla un testo in chiaro ridotto al minimo (ID delle blocklist attive, domini consentiti/bloccati, preferenze del resolver, preferenze dei log locali, registro LavaGuard). **Esclude** `isPaid`, QA, diagnostica e le blocklist complete.
3. **`ZeroKnowledgeBackupEnvelope`** lo sigilla con **AES-256-GCM** sotto una chiave di payload casuale di 32 byte; quella chiave viene racchiusa in **slot di chiave** per ogni segreto tramite **PBKDF2-HMAC-SHA256 (210k iterazioni)** — slot del segreto del dispositivo, slot di recupero assistito, slot opzionale per passkey. Lo slot opzionale per passkey è racchiuso con un output **WebAuthn PRF / `hmac-secret`** dell'autenticatore (derivato con HKDF); quell'output non lascia mai il client, quindi lo slot della passkey è autenticamente zero-knowledge — nessun valore conservato sul server lo sblocca (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** carica **solo testo cifrato + metadati non segreti** su Supabase `user_backups` direttamente tramite PostgREST, delimitato dalla **RLS** per ogni utente. (Non esiste una route di caricamento sul Worker; il Worker tocca `user_backups` solo per eliminarlo durante la cancellazione dell'account.)
5. **Recupero:** ripristino fluido sullo stesso dispositivo tramite lo slot del segreto del dispositivo; su un altro dispositivo tramite la **frase di recupero CVCV di 8 parole** (~105 bit) combinata con una quota di recupero conservata sul server tramite SHA256 (a due fattori — nessuna delle due metà da sola decifra); oppure, quando era stato sigillato uno slot per passkey, tramite l'output WebAuthn PRF / `hmac-secret` lato client (senza alcun valore conservato sul server). Il server non registra mai passkey, non emette sfide WebAuthn e non conserva alcun segreto di recupero.

Vedi [Account e backup](./accounts-and-backup.md).

### D. Piano di controllo app ↔ estensione — Implementato

Tre processi (app, tunnel, widget) si coordinano attraverso l'App Group `group.com.lavasec`:

- **Il controllo = messaggi del provider NETunnelProviderSession**, **non** notifiche Darwin. `AppViewModel` codifica un `LavaSecProviderMessage {kind, operationID}` e chiama `session.sendProviderMessage`; l'`handleAppMessage` del tunnel valuta il tipo (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **I file condivisi** trasportano regole/configurazione/stato di salute (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **gli archivi UserDefaults condivisi** (`ProtectionSessionStore` / `ProtectionPauseStore`) trasportano lo stato di sessione + pausa.
- **`LavaProtectionCommandService`** esegue i comandi di pausa/ripresa di Live Activity / AppIntent sotto un blocco di file `flock` con deduplica per revisione e rifiuto quando serve l'autenticazione; **la riconnessione lo aggira** per riavviare direttamente il tunnel (`startVPNTunnel`).
- **Connect-On-Demand** viene abilitato solo *dopo* che il tunnel conferma la connessione, mai all'installazione del profilo — così un profilo di onboarding appena installato non può attivare un tunnel impossibile da disattivare.

Vedi [Client iOS](./ios-client.md).

## 6. Confini di fiducia e progettazione attenta alla privacy

| # | Confine | Cosa lo attraversa | Cosa deliberatamente NON lo attraversa |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolver DNS pubblico** | Le richieste DNS consentite (cifrate: DoH3/DoT/DoQ, o IP in chiaro) vanno al resolver scelto dall'utente. | Lava non vede mai il flusso delle richieste; non è affatto presente in questo percorso. |
| 2 | **Dispositivo ↔ host delle blocklist di origine** | Il dispositivo scarica i byte della lista direttamente da `source_url`. | Lava non fa mai da proxy, non replica e non memorizza i byte delle blocklist di terze parti. |
| 3 | **Dispositivo ↔ Worker lavasec-api** | Letture dei **metadati** del catalogo; segnalazioni di bug anonime e facoltative; mirroring dei diritti d'accesso; cancellazione dell'account. | Nessuna richiesta DNS, nessuna cronologia di navigazione, nessuna impostazione in chiaro. |
| 4 | **Dispositivo ↔ Supabase** | **Busta di backup cifrata** facoltativa (solo testo cifrato, PostgREST sotto RLS); righe dell'account. | Il server non può decifrare il backup senza un segreto in possesso dell'utente. |
| 5 | **App ↔ estensione del tunnel** (sul dispositivo) | Messaggi del provider + file/preferenze dell'App Group. | Il tunnel fallisce in modo **conservativo** all'avvio a freddo senza uno snapshot riutilizzabile. |

**Principi di progettazione attenta alla privacy, fondati su quanto sopra:**

- **Filtraggio locale prima di tutto.** Il motore decisionale e il resolver girano dentro l'estensione NE sul dispositivo. Il backend è per costruzione solo metadati — non ci sono tabelle per le richieste DNS ordinarie o per la telemetria per dominio.
- **Nessun account richiesto per la protezione.** La protezione di base è gratuita per sempre; autenticazione e backup sono rigorosamente facoltativi.
- **Distribuzione solo URL della fonte.** Disaccoppia Lava dai byte delle liste di terze parti (conformità GPL/proprietà intellettuale + sicurezza in fase di App Review) e mantiene un guardrail di CI che impone "nessun codice di mirroring, nessun URL di artefatto Lava, nessuna scrittura di byte su R2".
- **Backup zero-knowledge a riposo.** AES-256-GCM lato client; il server conserva testo cifrato + metadati KDF + una quota di recupero, mai il testo in chiaro, la frase di recupero o la chiave sbloccata. Lo slot opzionale per passkey è racchiuso con un output WebAuthn PRF / `hmac-secret` lato client, quindi anch'esso è zero-knowledge — nessun valore conservato sul server lo sblocca.
- **Segreti locali al dispositivo.** Il materiale di sblocco del backup usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — non sincronizzato su iCloud, non presente nei backup del dispositivo.
- **Isolamento del ruolo di servizio.** `bug_reports`, `mirror_events` e `qa_developers` sono revocati ai ruoli PostgREST anon/authenticated; solo il Worker (ruolo di servizio) li tocca.
- **La sicurezza non è mai in vendita.** Il pagamento sblocca **solo la personalizzazione**. Non aggira mai il **guardrail di minaccia** non disattivabile, la cui integrità è garantita dagli hash di origine SHA256 accettati (non da una firma del server). La precedenza è coerente ovunque: **guardrail di minaccia > lista di permessi locale (eccezioni consentite) > blocklist > permesso predefinito.**

## 7. Documentazione dei singoli componenti

> Questi sono i documenti affini nell'insieme di documentazione dell'architettura. Il motore di filtraggio DNS e il catalogo delle blocklist sono documentati insieme in un unico file.

- [Client iOS](./ios-client.md) — target, App Group, piano di controllo, modello dello stato di protezione, onboarding, Live Activity.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — snapshot del filtro, precedenza delle decisioni, trasporti del resolver (DoH3/DoT/DoQ), budget di memoria, mmap; più il modello di catalogo solo URL della fonte, il recupero del catalogo, l'analisi/normalizzazione locale, il filtro dei domini protetti e il budget per livello.
- [Account e backup](./accounts-and-backup.md) — autenticazione Apple/Google, busta zero-knowledge, slot di chiave, frase di recupero, recupero tramite passkey con WebAuthn-PRF lato client.
- [Backend e dati](./backend-and-data.md) — Worker lavasec-api + lavasec-email, schema Supabase + RLS, R2/D1, distribuzione.

## 8. Legenda degli stati

Questo insieme di documenti usa un solo vocabolario degli stati. La **cartella della corsia è lo stato autorevole**; un frontmatter obsoleto dentro un piano è un errore di documentazione, non uno stato. **Il codice ha la precedenza sui piani.**

| Stato | Significato | Corsia del piano | Codice |
|---|---|---|---|
| **Implementato** | Distribuito e confermato nel codice | `plans/implemented/` | presente e collegato |
| **In corso** | In attiva costruzione; in parte già presente | `plans/inflight/`, `plans/under_review/` | parzialmente presente |
| **Pianificato** | Progettato, non costruito | `plans/backlog/` | assente |
| **Abbandonato** | Respinto o ripristinato | `plans/dropped/` (o commit ripristinato) | assente / rimosso |

**Stato delle cose menzionate in questa pagina:**

- **Implementato:** i quattro target iOS + App Group; il piano di controllo a messaggi del provider; il filtraggio DNS sul dispositivo con i trasporti DoH3/DoT/DoQ/IP; il recupero del catalogo solo URL della fonte + l'analisi locale; il budget delle regole del filtro (Free 500K / Plus 2M) + il guardrail del dispositivo di ~3,26M; l'onboarding su più pagine; la sicurezza con codice di accesso/biometria; la singola Live Activity deduplicata; il backup zero-knowledge; l'autenticazione Apple + Google; la cancellazione dell'account; il mirroring dei diritti d'accesso; le sonde QA; il livello di token `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluso il modello di profondità `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), i modificatori `.lavaTier(_:)` / `.lavaTierMetadata()` collegati a schermate rappresentative (ad es. `SettingsView`), e i token `dangerRed` e `LavaSpacing` — vincolati da `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **In corso:** il proseguimento dell'adozione del livello di token del design system su più schermate (il modello di profondità `LavaTier` e il livello di token sono distribuiti — vedi sotto — ma un `LavaColorRole` dedicato non è ancora presente, quindi gli accenti si risolvono ancora in colori grezzi).
- **Pianificato:** il mini-gioco easter-egg di Lava Guard; espressioni aggiuntive della mascotte (la mascotte ha esattamente **7** stati); il recupero tramite passkey pienamente pronto per la produzione su dispositivi fisici (Associated Domains / AASA); la ri-verifica JWS lato server dell'App Store (`verification_status` è `client_verified_storekit`); un token `LavaColorRole` dedicato così che gli accenti del design system si risolvano attraverso un ruolo semantico anziché colori grezzi.
- **Abbandonato:** il riuso delle connessioni DoQ (connessioni fresche per ogni richiesta); l'accesso con email/password (solo Apple + Google); la progettazione del mirror raw-R2 con GPL (superata dal solo URL della fonte).
