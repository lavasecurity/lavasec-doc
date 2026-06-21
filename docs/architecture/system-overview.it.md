---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Panoramica del sistema

> **Pubblico:** ingegneri. Questa è tutta Lava Security in una sola pagina: quali sono le parti, come si muovono i dati tra di esse e dove si trovano i confini di fiducia. I documenti dei singoli componenti vanno più in profondità; questo esiste perché tu possa avere il sistema bene in mente prima di leggerli.
>
> **Autorità:** dove questo documento e un piano non concordano, **vince il codice**. Lo stato riflette la realtà confermata dal codice, non le aspirazioni del piano. Vedi la [Legenda degli stati](#8-status-legend) in fondo alla pagina.

## 1. Il prodotto in una riga

Lava Security è un'app iOS che mette la privacy al primo posto e filtra il DNS **localmente sul dispositivo** attraverso un tunnel a pacchetti NetworkExtension, bloccando i domini dannosi e indesiderati per le persone non tecniche (genitori, persone anziane): con la protezione di base gratuita per sempre e senza bisogno di alcun account.

## 2. La promessa sulla privacy (canonica)

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti: il backend conserva solo i metadati del catalogo, un backup cifrato opaco per ogni utente e le diagnostiche anonime che scegli di inviare.

Tutto ciò che segue è al servizio di mantenere vera quella frase. L'architettura è volutamente ridotta sul lato server: il dispositivo fa il lavoro e il backend non vede mai una query.

## 3. Componenti

### Client iOS (tre target eseguibili + codice condiviso, un solo App Group `group.com.lavasec`)

| Componente | Bundle / posizione | Ruolo | Stato |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Guscio dell'app SwiftUI; punto di ingresso, navigazione a due schede Protezione + Impostazioni (Filtro/Attività sono schermate di dettaglio di Protezione; Attività di rete è stata spostata sotto Impostazioni → Avanzate). | Implementato |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; il motore di filtraggio/risoluzione DNS sul dispositivo. Soggetto al **tetto di memoria iOS di ~50 MiB per estensione**. | Implementato |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity di WidgetKit (schermata di blocco + Dynamic Island). | Implementato |
| **Shared/** | `Shared/` | Sorgenti condivise tra i target: App Group, servizio comandi, mascotte, attributi/intent della Live Activity. | Implementato |

**Controller lato app (in LavaSecApp):**

- **AppViewModel** — il controller lato app (oggetto-tuttofare): gestisce il ciclo di vita di `NETunnelProviderManager`, la persistenza dello stato condiviso, la messaggistica verso il provider, la riconciliazione della Live Activity, la sincronizzazione del catalogo, il backup, StoreKit e l'autenticazione.
- **RootView** — `TabView` a due schede (Protezione + Impostazioni), con Filtro e Attività raggiungibili come schermate di dettaglio sotto Protezione; controlla l'onboarding, ospita gli overlay di blocco di sicurezza / mascheramento per la privacy.
- **SecurityController** — codice di accesso (SHA256 con salt nel Keychain) + biometria + protezione per singola superficie.
- **LavaLiveActivityController** — riconciliatore a singola Activity, deduplicato e controllato per revisione.
- **OnboardingFlowView** — flusso multi-pagina al primo avvio (6 pagine: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (pacchetto SwiftPM indipendente dalla piattaforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — filtro compilato + precedenza delle decisioni; la forma compatta è l'artefatto su disco adatto al mmap che il tunnel legge.
- **DNSQueryDispatcher** — precedenza delle query: bootstrap > pausa > filtro.
- **ResolverOrchestrator** — instradamento del trasporto, degradazione a DNS in chiaro, failover per singolo endpoint, ripiego sul DNS del dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — esecutori del trasporto cifrato.
- **FeatureLimits** (in `SubscriptionPolicy.swift`) — limiti massimi per livello (fonte di verità), tramite i membri statici `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — calcolo dei limiti di sicurezza del dispositivo + applicazione autorevole del budget dopo l'unione.
- **BlocklistCatalogSync / BlocklistParser** — recupero del catalogo, download diretto dall'origine, analisi/normalizzazione/deduplicazione locale, filtro dei domini protetti.
- **GuardianMascotAnimation** — grafo di stati della mascotte a 7 stati (resa da `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — crittografia + payload del backup.
- **SupabaseIDTokenAuth** — autenticazione `id_token` con URLRequest grezza (senza SDK).

### Backend

| Componente | Ruolo | Stato |
|---|---|---|
| **Worker lavasec-api** | Cloudflare Worker (`api.lavasecurity.app`): letture del catalogo, sincronizzazione e pubblicazione delle blocklist via admin/cron, segnalazioni di bug anonime, eliminazione dell'account, mirroring dei diritti dell'App Store, sonde di QA. | Implementato |
| **Worker lavasec-email** | Inoltratore Cloudflare Email Routing solo in ricezione per `@lavasecurity.app`; rifiuta la posta sconosciuta/troppo grande. | Implementato |
| **Supabase Postgres** | Account, `user_backups`, metadati del catalogo, tabelle solo per il ruolo di servizio; **RLS su ogni tabella pubblica**. | Implementato |
| **Cloudflare R2** (il bucket R2 di produzione, un bucket di anteprima separato per lo staging) | Snapshot del catalogo + il cursore di sincronizzazione round-robin. **Mai** i byte delle blocklist di terze parti; la rotta di caricamento degli allegati delle segnalazioni di bug è stata rimossa (gli oggetti legacy vengono eliminati solo all'eliminazione dell'account). | Implementato |
| **Cloudflare D1** (il database del feedback di aiuto) | Voti di feedback anonimi sugli articoli di aiuto, solo in aggiunta. | Implementato |

## 4. Diagramma del flusso di dati

La proprietà di gran lunga più importante: **il percorso del resolver DNS cifrato (lato destro) non tocca mai il backend di Lava (in basso).** Il dispositivo recupera i *metadati* del catalogo dal Worker, ma i *byte* delle liste e il flusso effettivo delle query vanno direttamente a terze parti.

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

### A. Il percorso DNS (per ogni query, tutto sul dispositivo) — Implementato

Questo è il percorso caldo e il cuore della privacy. Si svolge interamente all'interno di `LavaSecTunnel`; nulla qui raggiunge i server di Lava.

1. Il tunnel a pacchetti intercetta una query DNS (server DNS del tunnel `10.255.0.1`).
2. **`DNSQueryDispatcher`** applica la precedenza delle query: **bootstrap > pausa > filtro**. Bootstrap-per-primo è un invariante rigido: il nome host del resolver stesso viene risolto prima di qualsiasi filtraggio, così il resolver non può mai bloccare sé stesso.
3. Se non è bootstrap e non è in pausa, il dominio viene valutato rispetto a **`CompactFilterSnapshot`** (caricato dall'App Group tramite `Data(contentsOf:options:[.mappedIfSafe])`, mmap a copia zero). La precedenza delle decisioni è **guardrail contro le minacce > allowlist locale (eccezioni consentite) > blocklist > consenti-per-default**; i domini non validi vengono bloccati.
4. **Bloccato** → il tunnel risponde localmente (nessun contatto con l'origine). **Consentito** → la query viene passata a **`ResolverOrchestrator`**.
5. `ResolverOrchestrator` instrada verso il trasporto configurato — **`DoH3` / `DoT` / `DoQ` / DNS in chiaro (`IP`)** — con failover per singolo endpoint dietro una soglia di backoff, degradazione a DNS in chiaro quando un piano cifrato non ha endpoint e **ripiego sul DNS del dispositivo** quando il primario non restituisce risposta e il piano lo consente.
6. La risposta del resolver viene restituita al sistema operativo. Il flusso di query dell'utente va solo al **resolver pubblico scelto dall'utente**, mai a Lava.

Note sul trasporto (convenzioni testuali): `DoH3` (senza barra) viene annotato **solo quando una negoziazione h3 viene effettivamente osservata**: preferito, mai promesso. **`DoT`** usa un pool fino a 4 NWConnection per endpoint con aggiornamento per inattività + un nuovo tentativo su connessione fresca. **`DoQ`** apre una **nuova connessione QUIC per ogni query** (nessun riutilizzo); il pool a 4 corsie offre concorrenza, non riutilizzo dell'handshake — il riutilizzo della connessione è stato realizzato, testato sul dispositivo e **annullato** (rinviato fino al pavimento di distribuzione iOS-26). Vedi [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md).

### B. Recupero del catalogo + caricamento delle blocklist (solo source-url) — Implementato

Come le regole di filtro arrivano sul dispositivo. Lava è un distributore **solo source-url**: pubblica solo l'URL dell'origine + gli hash accettati e **non memorizza, replica, trasforma o serve mai i byte delle blocklist di terze parti.**

1. Il dispositivo recupera i **metadati** del catalogo dal Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servito direttamente da R2 (`catalog/latest.json`), suddiviso in `sources[]` + `guardrails[]`, dove ogni voce porta con sé `source_url` + `accepted_source_hashes`.
2. Per ogni origine abilitata, il dispositivo scarica i **byte della lista direttamente da `source_url`** (l'origine — HaGeZi, OISD, Block List Project, ecc.), **non** da Lava.
3. Il dispositivo calcola lo SHA256 e accetta solo i byte il cui checksum è in `accepted_source_hashes`; in caso di mancata corrispondenza ripiega sull'ultima cache valida o fallisce in modo chiuso (`checksumMismatch`).
4. **`BlocklistParser`** analizza/normalizza/deduplica localmente (formati auto / plain / hosts / adblock / dnsmasq), poi **`DomainRuleSet.lavaSecProtectedDomains`** rimuove i domini protetti (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …), così una lista d'origine non può mai bloccare i domini di Lava/Apple/provider d'identità.
5. **`FilterSnapshotPreparationService`** unisce l'unione deduplicata ed esegue l'**applicazione autorevole del budget** (prima il limite del dispositivo, poi il livello), quindi scrive `filter-snapshot.compact` nell'App Group.
6. `AppViewModel` invia un messaggio al provider `reload-snapshot`; il tunnel ricarica.

Il lato Worker rispecchia tutto questo: la sua sincronizzazione admin/cron recupera ogni origine, ne calcola hash/conteggio, scrive `raw_r2_key = null` / `normalized_r2_key = null` e ripubblica solo i metadati. Il modello del catalogo delle blocklist e il percorso di sincronizzazione del backend sono trattati in [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) e [Backend e dati](./backend-and-data.md).

**Modello di budget (due livelli):**
- **Guardrail del dispositivo (per tutti, mai un paywall):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 regole** = `((32.0 − 4.0) MB × 1.048.576) / 9.0 B/regola` — un obiettivo di 32 MB sotto il tetto NE di ~50 MiB. Le configurazioni fuori budget vengono rifiutate in modo deterministico anziché lasciare che il tunnel venga terminato per jetsam.
- **Limite del livello (`FeatureLimits`):** **Free 500K regole / Plus 2M regole**, che vincola al di sotto del guardrail del dispositivo. Questo ha sostituito il vecchio limite sul **numero** di liste abilitate (free 3 / paid 10) — i limiti sul numero di liste sono obsoleti.

> **Avvertenza sui valori abilitati per default (vince il codice):** i default gratuiti distribuiti sono **Block List Project Phishing + Scam** (`OnboardingDefaults.lavaRecommendedDefaults`). Vengono derivati sul dispositivo dal flag `defaultEnabled` di ogni origine curata (`BlocklistSource.recommendedDefaultSourceIDs`), che è la fonte di verità sul dispositivo e rispecchia la colonna `default_enabled` del catalogo backend. I testi di piano/catalogo che dicono "Block List Basic è l'unico default" sono errati per il dispositivo (tracciato internamente).

### C. Backup (a conoscenza zero, su consenso) — Implementato

Facoltativo, vincolato all'account, e gli unici dati utente che arrivano nel backend — come **testo cifrato opaco**.

1. L'utente accede facoltativamente (solo Apple o Google; **email/password è Abbandonato**) tramite `id_token` nativo scambiato presso Supabase Auth (`grant_type=id_token`, nonce con hash). Viene conservata solo la sessione Supabase risultante, locale al dispositivo, nel Keychain.
2. **`BackupConfigurationPayload`** assembla un testo in chiaro minimizzato (ID delle blocklist abilitate, domini consentiti/bloccati, preferenze del resolver, preferenze dei log locali, registro LavaGuard). **Esclude** `isPaid`, QA, diagnostiche e blocklist complete.
3. **`ZeroKnowledgeBackupEnvelope`** lo sigilla con **AES-256-GCM** sotto una chiave di payload casuale di 32 byte; quella chiave viene avvolta in **slot di chiave** per ogni segreto tramite **PBKDF2-HMAC-SHA256 (210k iterazioni)** — slot del segreto del dispositivo, slot di recupero assistito, slot passkey facoltativo. Lo slot passkey facoltativo viene avvolto con un output **WebAuthn PRF / `hmac-secret`** dell'autenticatore (derivato con HKDF); quell'output non lascia mai il client, quindi lo slot passkey è genuinamente a conoscenza zero — nessun valore conservato sul server lo apre (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** carica **solo il testo cifrato + metadati non segreti** su Supabase `user_backups` direttamente tramite PostgREST, delimitato dalla **RLS** per ogni utente. (Non esiste una rotta di caricamento sul Worker; il Worker tocca `user_backups` solo per eliminarlo durante l'eliminazione dell'account.)
5. **Recupero:** ripristino fluido sullo stesso dispositivo tramite lo slot del segreto del dispositivo; fuori dal dispositivo tramite la **frase di recupero CVCV di 8 parole** (~105 bit) combinata con una quota di recupero conservata sul server tramite SHA256 (a due fattori — nessuna metà da sola decifra); oppure, quando uno slot passkey è stato sigillato, tramite l'output WebAuthn PRF / `hmac-secret` lato client (senza alcun valore conservato sul server). Il server non registra mai passkey, non emette sfide WebAuthn e non conserva alcun segreto di recupero.

Vedi [Account e backup](./accounts-and-backup.md).

### D. Piano di controllo app ↔ estensione — Implementato

Tre processi (app, tunnel, widget) si coordinano attraverso l'App Group `group.com.lavasec`:

- **Il controllo = messaggi al provider NETunnelProviderSession**, **non** notifiche Darwin. `AppViewModel` codifica un `LavaSecProviderMessage {kind, operationID}` e chiama `session.sendProviderMessage`; il `handleAppMessage` del tunnel commuta in base al tipo (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **I file condivisi** trasportano regole/configurazione/stato di salute (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); gli **store UserDefaults condivisi** (`ProtectionSessionStore` / `ProtectionPauseStore`) trasportano lo stato di sessione + pausa.
- **`LavaProtectionCommandService`** esegue i comandi di pausa/ripresa di Live-Activity / AppIntent sotto un lock di file `flock` con deduplica per revisione e rifiuto quando serve autenticazione; **la riconnessione lo aggira** per riavviare il tunnel direttamente (`startVPNTunnel`).
- **Connect-On-Demand** viene abilitato solo *dopo* che il tunnel conferma la connessione, mai all'installazione del profilo — così un profilo di onboarding appena installato non può attivare un tunnel impossibile da spegnere.

Vedi [Client iOS](./ios-client.md).

## 6. Confini di fiducia e progettazione a tutela della privacy

| # | Confine | Cosa lo attraversa | Cosa volutamente NON lo fa |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolver DNS pubblico** | Le query DNS consentite (cifrate: DoH3/DoT/DoQ, oppure IP in chiaro) vanno al resolver scelto dall'utente. | Lava non vede mai il flusso di query; non è affatto in questo percorso. |
| 2 | **Dispositivo ↔ host delle blocklist d'origine** | Il dispositivo scarica i byte della lista direttamente da `source_url`. | Lava non fa mai da proxy, non replica e non memorizza i byte delle blocklist di terze parti. |
| 3 | **Dispositivo ↔ Worker lavasec-api** | Letture dei **metadati** del catalogo; segnalazioni di bug anonime su consenso; mirror dei diritti; eliminazione dell'account. | Nessuna query DNS, nessuna cronologia di navigazione, nessuna impostazione in chiaro. |
| 4 | **Dispositivo ↔ Supabase** | **Busta di backup cifrata** su consenso (solo testo cifrato, PostgREST sotto RLS); righe dell'account. | Il server non può decifrare il backup senza un segreto conservato dall'utente. |
| 5 | **App ↔ estensione tunnel** (sul dispositivo) | Messaggi al provider + file/default dell'App Group. | Il tunnel fallisce in modo **chiuso** all'avvio a freddo senza uno snapshot riutilizzabile. |

**Principi di progettazione a tutela della privacy, fondati su quanto sopra:**

- **Filtraggio locale prima di tutto.** Il motore decisionale e il resolver girano dentro l'estensione NE sul dispositivo. Il backend è solo metadati per costruzione — non ci sono tabelle per le normali query DNS o per la telemetria per dominio.
- **Nessun account richiesto per la protezione.** La protezione di base è gratuita per sempre; autenticazione e backup sono rigorosamente su consenso.
- **Distribuzione solo source-url.** Disaccoppia Lava dai byte delle liste di terze parti (conformità GPL/proprietà intellettuale + sicurezza per l'App Review) e mantiene un guardrail di CI che impone "nessun codice di mirror, nessun URL di artefatti Lava, nessuna scrittura di byte su R2."
- **Backup a conoscenza zero a riposo.** AES-256-GCM lato client; il server conserva il testo cifrato + i metadati KDF + una quota di recupero, mai il testo in chiaro, la frase di recupero o la chiave non avvolta. Lo slot passkey facoltativo viene avvolto con un output WebAuthn PRF / `hmac-secret` lato client, quindi è anch'esso a conoscenza zero — nessun valore conservato sul server lo apre.
- **Segreti locali al dispositivo.** Il materiale di sblocco del backup usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — non sincronizzato con iCloud, non nei backup del dispositivo.
- **Isolamento del ruolo di servizio.** `bug_reports`, `mirror_events` e `qa_developers` sono revocati ai ruoli PostgREST anon/authenticated; solo il Worker (ruolo di servizio) li tocca.
- **La sicurezza non è mai in vendita.** Il pagamento sblocca **solo la personalizzazione**. Non aggira mai il **guardrail contro le minacce** non eludibile, la cui integrità è garantita dagli hash SHA256 accettati delle origini (non da una firma del server). La precedenza è coerente ovunque: **guardrail contro le minacce > allowlist locale (eccezioni consentite) > blocklist > consenti-per-default.**

## 7. Documenti dei singoli componenti

> Questi sono i documenti fratelli nell'insieme di documenti sull'architettura. Il motore di filtraggio DNS e il catalogo delle blocklist sono documentati insieme in un unico file.

- [Client iOS](./ios-client.md) — target, App Group, piano di controllo, modello dello stato di protezione, onboarding, Live Activity.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — snapshot del filtro, precedenza delle decisioni, trasporti del resolver (DoH3/DoT/DoQ), budget di memoria, mmap; più il modello di catalogo solo source-url, il recupero del catalogo, l'analisi/normalizzazione locale, il filtro dei domini protetti e il budget per livello.
- [Account e backup](./accounts-and-backup.md) — autenticazione Apple/Google, busta a conoscenza zero, slot di chiave, frase di recupero, recupero passkey con WebAuthn-PRF lato client.
- [Backend e dati](./backend-and-data.md) — Worker lavasec-api + lavasec-email, schema Supabase + RLS, R2/D1, distribuzione.

## 8. Legenda degli stati {#8-status-legend}

Questo insieme di documenti usa un unico vocabolario di stati. La **cartella di corsia è lo stato autorevole**; metadati frontmatter obsoleti dentro un piano sono un difetto di documentazione, non uno stato. **Il codice prevale sui piani.**

| Stato | Significato | Corsia del piano | Codice |
|---|---|---|---|
| **Implementato** | Distribuito e confermato nel codice | `plans/implemented/` | presente e collegato |
| **In corso** | In fase attiva di sviluppo; parzialmente arrivato | `plans/inflight/`, `plans/under_review/` | parzialmente presente |
| **Pianificato** | Progettato, non costruito | `plans/backlog/` | assente |
| **Abbandonato** | Rifiutato o annullato | `plans/dropped/` (o commit annullato) | assente / rimosso |

**Stato delle cose menzionate in questa pagina:**

- **Implementato:** i quattro target iOS + App Group; piano di controllo con messaggi al provider; filtraggio DNS sul dispositivo con trasporti DoH3/DoT/DoQ/IP; recupero del catalogo solo source-url + analisi locale; budget delle regole di filtro (Free 500K / Plus 2M) + guardrail del dispositivo di ~3,26M; onboarding multi-pagina; sicurezza con codice di accesso/biometria; singola Live Activity deduplicata; backup a conoscenza zero; autenticazione Apple + Google; eliminazione dell'account; mirroring dei diritti; sonde di QA; il livello di token `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluso il modello di profondità `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), i modificatori `.lavaTier(_:)` / `.lavaTierMetadata()` collegati a superfici rappresentative (ad es. `SettingsView`) e i token `dangerRed` e `LavaSpacing` — bloccati da `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **In corso:** continuazione dell'estensione del livello di token del design system a più superfici (il modello di profondità `LavaTier` e il livello di token sono già distribuiti — vedi sotto — ma un `LavaColorRole` dedicato non è ancora presente, quindi gli accenti si risolvono ancora in colori grezzi).
- **Pianificato:** il mini-gioco easter-egg di Lava Guard; espressioni aggiuntive della mascotte (la mascotte ha esattamente **7** stati); recupero passkey pienamente pronto per la produzione su dispositivi fisici (Associated Domains / AASA); ri-verifica JWS dell'App Store lato server (`verification_status` è `client_verified_storekit`); un token `LavaColorRole` dedicato in modo che gli accenti del design system si risolvano attraverso un ruolo semantico anziché colori grezzi.
- **Abbandonato:** riutilizzo della connessione DoQ (connessioni fresche per ogni query); accesso con email/password (solo Apple + Google); il design del mirror raw-R2 GPL (sostituito da solo source-url).
