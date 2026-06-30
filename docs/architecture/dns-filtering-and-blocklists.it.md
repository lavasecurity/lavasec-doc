---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Filtraggio DNS e blocklist

> Pubblico: ingegneri. Questo documento descrive la pipeline DNS on-device, il percorso del resolver a trasporto cifrato, il motore decisionale di filtraggio e il modello di catalogo blocklist source-url-only — con i numeri precisi che il codice applica. Lo stato riflette la realtà confermata dal codice. Laddove un piano e il codice siano in disaccordo, **vince il codice** e la divergenza viene segnalata inline.

Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva soltanto i metadati del catalogo, un backup cifrato opaco per ogni utente e diagnostica anonimizzata che scegli di inviare.

Lava è **filtraggio DNS/blocklist locale**, non una garanzia che ogni dominio o URL malevolo venga bloccato.

---

## 1. La pipeline DNS (Implementata)

Il motore filter/resolve gira all'interno del **NE / packet tunnel** — l'estensione `NEPacketTunnelProvider` `LavaSecTunnel` (`com.lavasec.app.tunnel`), che intercetta solo il DNS. Gli indirizzi del tunnel sono `10.255.0.2` (tunnel) e `10.255.0.1` (server DNS). Il processo dell'app non vede mai il traffico delle query; scrive soltanto gli artefatti compilati nell'**App Group** (`group.com.lavasec`) e segnala al tunnel tramite i **provider messages** di NETunnelProviderSession (non notifiche Darwin).

Per ogni query DNS in ingresso il tunnel esegue una **precedenza di query** fissa in `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap-first è un invariante rigido.** Una query che risolve il nome host *proprio* del resolver configurato (l'endpoint DoH/DoT/DoQ) non deve mai essere bloccata o messa in pausa, altrimenti il tunnel non potrebbe nemmeno avviare il DNS cifrato. Il dispatcher accetta closure lazy, così ogni passo viene letto solo quando viene raggiunto, preservando lo short-circuit (nessuna lettura dello snapshot quando esiste una risposta di bootstrap; nessuna lettura della pausa durante il bootstrap).
- **temporary pause** inoltra a monte mentre è attivo un TTL di pausa avviata dall'utente.
- **filter** valuta il dominio rispetto allo snapshot compilato e lo inoltra oppure sintetizza una risposta bloccata.

Una query che supera il filtro (azione `.allow`) viene passata al percorso del resolver (§3). Il tunnel **fallisce in modo chiuso** all'avvio a freddo senza uno snapshot riutilizzabile: installa uno snapshot runtime fail-closed che blocca tutto il traffico anziché risolvere senza filtri.

---

## 2. Il motore di filtraggio (Implementato)

### 2.1 Precedenza decisionale

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) applica la precedenza di sicurezza canonica:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Ordine | Insieme di regole | Esito | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

Un dominio che fallisce la normalizzazione viene bloccato con motivazione `.invalidDomain` (fail-safe). La stessa precedenza è rispecchiata nella forma binaria su disco (`CompactFilterSnapshot`). Il threat guardrail sta sopra l'allowlist locale per progettazione: **il pagamento non aggira mai il threat guardrail non-aggirabile**, e un'eccezione utente non può sbloccare un dominio del guardrail.

> Nota: nel working tree attuale `nonAllowableThreatRules` / `guardrailSources` sono vuoti (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); lo slot di precedenza è collegato e applicato ma viene comunque distribuito ancora senza voci nel guardrail.

### 2.2 Archiviazione delle regole e l'unità di memoria residente

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) memorizza gli insiemi `exactDomains` + `suffixDomains`. Il matching (`containsNormalized`) esegue una ricerca esatta più un percorso sui suffissi padre (in stile `hasSuffix`) al momento della query — **non c'è subsunzione dei sottodomini a tempo di compilazione**. Una riga wildcard valida è **una regola** e una voce della tabella di memoria. Questa identità 1-riga = 1-regola è ciò che rende il conteggio delle regole la metrica di risorsa onesta (§4).

### 2.3 Forme dello snapshot compilato

- **`FilterSnapshot`** — il filtro compilato in memoria: `blockRules`, `allowRules`, `nonAllowableThreatRules` e il preset del resolver.
- **`CompactFilterSnapshot`** — la forma binaria, mmap-friendly, su disco che il tunnel legge effettivamente (magic `LSCFSNP1`, `fileVersion 1`). Viene caricata zero-copy tramite mmap (§4.3).

L'app scrive sia `filter-snapshot.json` sia `filter-snapshot.compact` nell'App Group; il tunnel decodifica l'artefatto compatto. Un percorso di **riuso a warm-startup** (`FilterArtifactStore`) consente al tunnel di riutilizzare l'artefatto compatto su disco senza ricompilare, vincolato da un'impronta di identità + un manifest scritto in modo atomico; il riuso viene rifiutato (motivazione privacy-safe, solo nome di campo) quando cambiano il trasporto del resolver, la copertura del catalogo o gli input dello snapshot.

---

## 3. Trasporti cifrati e il percorso del resolver (Implementato)

### 3.1 Enum dei trasporti

Le query non bloccate vengono inoltrate al resolver upstream configurato. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) ha **cinque** valori:

| Trasporto | Valore raw | Annotazione mostrata nella UI |
|---|---|---|
| Device DNS | `device-dns` | *(nessuna — il nome è il trasporto)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

I preset integrati sono Google, Cloudflare, Quad9, Mullvad (ciascuno nelle varianti IP / DoH / DoT) più Device DNS e Custom. I resolver personalizzati accettano un server IPv4/IPv6 semplice, un URL DoH, un URL DoT (`tls://` / `dot://`), un URL DoQ (`doq://` / `quic://`) o uno stamp DNS `sdns://`; nomi utente/password e localhost vengono rifiutati. DoT/DoQ usano per impostazione predefinita la porta `853`; DoH richiede un path.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) esegue DoH su `URLSession`. Ogni richiesta opta per HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); il loader di Apple ricade nativamente su H2/H1, quindi questo non rende mai irraggiungibile un resolver raggiungibile. Il protocollo negoziato viene letto da `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

La UI mostra l'annotazione **`DoH3` (senza slash)** — es. "Quad9 (DoH3)" — **solo quando una negoziazione h3 viene effettivamente osservata** (`DoHHTTPVersion.dohAnnotation`); altrimenti mostra `DoH`. DoH3 è preferito, mai promesso: l'etichetta è osservazionale e con ambito al resolver, mai persistita (il riporto di "DoH3 confermato" tra i riavvii è stato annullato). Le richieste fanno POST di `application/dns-message`; le risposte vengono validate per content-type e lunghezza e l'ID di transazione viene ripristinato prima della riscrittura.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection` in pool, **fino a 4 connessioni per endpoint** (`maxConnectionsPerEndpoint = 4`), in round-robin, così le query parallele evitano il head-of-line blocking. Gestisce la **staleness da idle**: provider come Cloudflare chiudono lato server le connessioni DoT inattive (~10s) senza segnalare un cambio di stato, quindi una connessione riutilizzata rimasta inattiva oltre **8 secondi** (`reusedConnectionMaxIdleInterval = 8`) viene rinfrescata prima dell'invio, e un timeout su una connessione riutilizzata ottiene **esattamente un retry con connessione nuova**.

### 3.4 DoQ — connessione nuova per ogni query

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantiene un pool limitato di **4 corsie per endpoint**, ma **ogni query apre una nuova connessione QUIC** — un handshake completo per ogni query. Il pool a 4 corsie fornisce **concorrenza, non riuso dell'handshake**.

**Stato del riuso connessione DoQ (Abbandonato / rimandato).** Il riuso è stato esaminato e sottoposto a benchmark su dispositivo (34 handshake nuovi su 35 query ≈ nessun riuso), poi implementato come percorso `NWConnectionGroup` multi-stream vincolato a iOS 26, testato su dispositivo contro AdGuard DoQ, e **annullato come net-negativo** (errori di stream + errori di fallback contro un server reale). RFC 9250 mappa ogni query al proprio stream QUIC, quindi il riuso richiede `NWConnectionGroup`/`openStream`, disponibile **solo da iOS 26.0+**; l'attuale soglia minima di distribuzione è **iOS 17**. Il riuso è rimandato finché la soglia non raggiunge iOS 26. Il DoQ personalizzato viene rifiutato sui dispositivi che non lo supportano ("DNS over QUIC is not supported on this device").

### 3.5 Policy di risoluzione

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) detiene la policy di upstream:

1. **Routing del trasporto** in base al trasporto configurato.
2. **Degradazione a plain DNS** quando un piano cifrato non ha endpoint.
3. **Failover per endpoint** con un gate di backoff — un endpoint in backoff non tocca mai la rete (esito `backed-off`).
4. **Fallback a Device-DNS** quando il primario non restituisce risposta *e* il piano lo consente (la proprietà del piano è `shouldFallbackToDeviceDNS`, derivata dal campo di configurazione `fallbackToDeviceDNS`); il risultato viene ri-annotato come trasporto del dispositivo. L'esecuzione sulla rete è iniettata dietro executor in modo che la policy sia testabile a livello di unità; lo stato di backoff resta fuori dalla policy pura.

---

## 4. Budget delle regole di filtro, soglia NE e mmap

La metrica di tier distribuita è il **budget delle regole di filtro**: il totale delle **regole** di dominio compilate che un utente può abilitare. Questo ha sostituito il vecchio cap sul **conteggio** delle liste abilitate (free 3 / paid 10), che era un proxy disonesto — una lista può avere 1K o 1M di regole. Ci sono **due livelli**: un guardrail per dispositivo valido per tutti, e un limite di monetizzazione per tier al di sotto di esso.

### 4.1 Limiti di tier (Implementato)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) è la fonte di verità:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Blocklist / DNS personalizzati |
|---|---|---|---|---|
| **Free** | **500,000** | 25 | 25 | No |
| **Plus** (`.paid` / `.plus`) | **2,000,000** | 1,000 | 1,000 | Sì |

Il limite di tier è un confine di monetizzazione, **mai un paywall sul guardrail del dispositivo**. **Lava Security Plus** sblocca soltanto la personalizzazione — mai la sicurezza di base, mai il threat guardrail. Le blocklist personalizzate (a pagamento) vengono recuperate direttamente dal dispositivo dell'utente, analizzate e memorizzate nella cache localmente, e mai inoltrate ai server Lava.

### 4.2 Guardrail di memoria del dispositivo + soglia NE (Implementato)

Il packet tunnel è soggetto alla **soglia di memoria di ~50 MiB per estensione** di iOS (un limite di progettazione del SO per tipo di estensione per i packet tunnel sin da iOS 15, non scalato con la RAM; risiede in un `com.apple.jetsamproperties.{Model}.plist` per modello di dispositivo e può essere inferiore sui dispositivi più vecchi). Superarla innesca il jetsam. Non esiste API per la soglia, quindi il budget mantiene un margine sotto il precipizio.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) esegue il calcolo, espresso in regole di filtro (block + allow + guardrail):

| Costante | Valore |
|---|---|
| `baselineMegabytes` | 4.0 MB (overhead di processo fisso, misurato ≈3.5 MB, arrotondato per eccesso) |
| `estimatedBytesPerRule` | 9.0 B dirty resident per regola (misurato ≈8.5 B, arrotondato per eccesso) |
| `maxResidentMegabytes` | 32.0 MB (soglia obiettivo, lasciando ~10 MB di margine sotto la soglia jetsam osservata di ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 regole** |

Questo **guardrail del dispositivo a ~3.26M regole** è il limite di sicurezza inferiore rigido per *ogni* utente, posto sopra qualsiasi tier di abbonamento, e **non è mai un paywall**. Misurazione di riferimento (dispositivo "chimmy", 2026-06-13): **789,831 regole → 9.9 MB di `phys_footprint`**, cioè ≈ baseline + costo per regola.

### 4.3 Strategia mmap (Implementata)

Lo snapshot compatto viene caricato con `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), e `CompactBinaryReader` restituisce slice zero-copy. Il blob di testo dei domini, di diversi megabyte, rimane **file-backed/clean** ed è escluso dal `phys_footprint` conteggiato dal jetsam; solo le tabelle `[Entry]` decodificate costano memoria residente (~6 B/regola su disco, ~8.5 B dirty resident). Questo alza la soglia dei domini on-device: il costo residente sono le tabelle delle voci, non l'intero artefatto.

### 4.4 Applicazione a due livelli (Implementata)

- **Autoritativa (a tempo di compilazione).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) applica il budget sull'**unione deduplicata** di tutte le liste abilitate. Il guardrail del dispositivo viene controllato **per primo** (il limite inferiore rigido); il limite di tier vincola al di sotto di esso. Le configurazioni fuori budget vengono rifiutate in modo deterministico — `exceedsDeviceMemoryBudget` o `exceedsTierFilterRuleLimit` — anziché lasciare che il tunnel finisca in jetsam. L'errore nomina le due liste che contribuiscono di più, così la correzione è ovvia.
- **Indicativa (UI a tempo di selezione).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) alimenta il misuratore di selezione usando una **somma** per lista con un **margine di soft-ceiling di 1.10** che compensa l'over-count cross-lista del ~7–10% (la somma per lista sovrastima l'unione deduplicata).

### 4.5 Il parser (Implementato)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) conta le regole letteralmente: scarta commenti/righe vuote/righe non valide, normalizza, deduplica le stringhe esatte all'interno di una lista (tramite un `Set`), e limita a **`maxRules = 1,000,000`** per lista (default), con una lunghezza massima di riga di 4,096 caratteri. Formati supportati: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (auto prova hosts → dnsmasq → adblock → plain). Una riga valida = una regola = l'unità di memoria.

> **Righe `hosts` multi-host (parser rules version 2).** Una riga `hosts` che mappa un IP a più host (`0.0.0.0 a.com b.com c.com`) ora emette **ogni** host come propria regola, non solo il primo; `maxRules` viene applicato **per regola** (non per riga) così che una riga multi-host vicina al cap non possa superarlo. Poiché gli stessi byte upstream possono ora produrre più regole, la rules version del parser è stata incrementata **1 → 2**, invalidando le voci `RuleSetCache` obsolete analizzate sotto il vecchio comportamento solo-primo-host.

### 4.6 Robustezza di download e decodifica (Implementata)

Il tunnel e la sincronizzazione del catalogo girano dentro il budget di memoria NE, quindi l'ingestione delle liste è irrobustita contro input ostili o malformati:

- **Download in streaming.** `defaultDataFetcher` scarica i byte della lista in un file temporaneo tramite `URLSession.download` (memoria di picco limitata) con un controllo della dimensione post-download (`maximumBlocklistBytes`) anziché bufferizzare l'intero corpo in RAM; un corpo sovradimensionato solleva `BlocklistDownloadSizeLimitExceeded`.
- **Cap sui metadati del catalogo (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes` rifiuta un catalogo remoto sovradimensionato prima della decodifica, così un host ostile/MITM non può forzare una decodifica JSON OOM nell'estensione.
- **Decodifica UTF-8 indulgente.** Un singolo byte UTF-8 non valido non rifiuta più un'intera lista (che, sotto fail-closed, bloccherebbe tutto il DNS); i byte non validi diventano U+FFFD e solo la riga incriminata fallisce la validazione per riga e viene scartata.
- **Errori nominati per blocklist personalizzata.** Una lista personalizzata fallita ora mostra `customBlocklistUnavailable(displayName:reason:)` — "Couldn't load the custom blocklist '<name>'. <why>" — anziché un `URLError` grezzo; la cancellazione viene propagata come cancellazione, non come fallimento del download.

---

## 5. Catalogo delle blocklist e sorgenti predefinite

### 5.1 Modello del catalogo (Implementato)

Il **catalogo delle blocklist** è la lista pubblicata delle sorgenti disponibili. Il **Worker lavasec-api** serve i metadati JSON da un bucket R2 su `GET /v1/catalog` (e `/v1/catalog/:version`); il dispositivo recupera i **byte** effettivi della lista direttamente da ogni `source_url` upstream. Gli endpoint del catalogo iOS sono `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

Sul dispositivo, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Recupera i byte della lista direttamente da `source.sourceURL`, applicando un cap di dimensione.
2. Calcola lo SHA-256 e accetta i byte solo se il checksum è negli `accepted_source_hashes` del catalogo.
3. In caso di mismatch, ricade sull'ultima cache locale valida, oppure **fallisce in modo chiuso** (`checksumMismatch`) — a meno che la sorgente non consenta esplicitamente la rotazione diretta upstream.
4. Analizza/normalizza/deduplica localmente.
5. Filtra ogni insieme di regole analizzato attraverso `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`) così che una lista upstream non possa mai bloccare i domini di Lava/Apple/identity-provider.

L'**insieme dei domini protetti** (filtrati prima dell'attivazione): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (tutti con match sui suffissi). Il Worker applica un filtro `PROTECTED_SUFFIXES` equivalente quando calcola i metadati; il dispositivo ri-valida comunque.

### 5.2 Sorgenti curate (Implementato)

`DefaultCatalog.curatedSources` è generato dal [Blocklist Catalog](../legal/blocklist-catalog.md) canonico, attualmente **32** sorgenti su sette categorie: Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling e Piracy & Torrent. Le famiglie di sorgenti includono The Block List Project, Phishing.Database, HaGeZi, OISD, StevenBlack, AdGuard e 1Hosts.

`guardrailSources` è vuoto. Le sorgenti GPL (HaGeZi, OISD, AdGuard) sono visibili nel catalogo ma **opt-in / OFF per impostazione predefinita**; il Worker limita il sync/publish di lancio a `source_url_only` più i prefissi GPL sdoganati (`hagezi-`, `oisd-`, `adguard-`).

### 5.3 Liste abilitate per impostazione predefinita per gli utenti free (Implementato)

La configurazione di default per gli utenti free è `OnboardingDefaults.lavaRecommendedDefaults`, che abilita **Block List Basic** — una lista combinata ampia e con licenza permissiva (ads + tracking + malware + phishing/scam) — con il preset di resolver device-DNS (`resolverPresetID = DNSResolverPreset.device.id`) e il fallback cifrato Device-DNS **attivo** (`usesEncryptedDeviceDNSFallback = true`), instradando verso **Mullvad DoH** (`fallbackResolverPresetID = DNSResolverPreset.mullvadDoH.id`): se il DNS proprio del dispositivo si blocca, le risoluzioni consentite vengono trasportate transitoriamente su Mullvad DoH e poi tornano automaticamente al DNS del dispositivo. (L'inizializzatore nudo `AppConfiguration()` imposta questo fallback **disattivato** per impostazione predefinita — viene abilitato solo accettando i default di onboarding consigliati.) Questo sostituisce la precedente coppia Block List Project Phishing + Scam: la copertura combinata di Basic le ingloba, ed entrambe rimangono liste opt-in selezionabili.

Quel default free è **prodotto da `defaultEnabled`**, non hardcoded. `blockListProjectBasic` imposta `defaultEnabled: true`, e `DefaultCatalog.recommendedDefaultSourceIDs` è derivato da `curatedSources.filter(\.defaultEnabled)`. `defaultEnabled` è "l'unica fonte di verità per il default di fresh-install", rispecchiando la colonna `default_enabled` del catalogo backend. Fluendo attraverso `recommendedDefaultSourceIDs` dentro `OnboardingDefaults`, è il meccanismo vivo — cambia il flag su una sorgente per modificare il default.

> **Fonte di verità del default (una spec generata).** Il catalogo è generato da un'unica spec canonica ([Blocklist Catalog](../legal/blocklist-catalog.md)) che produce sia il `DefaultCatalog` iOS sia il seed del backend, così che il dispositivo e i metadati serviti su `/v1/catalog` concordino per costruzione. Il default di fresh-install è **Block List Basic**, dal suo flag `defaultEnabled: true`. Il vero gate di tier è il budget di regole di filtro 500K/2M, non un conteggio di liste.

### 5.4 Modello di distribuzione GPL source-url-only (Implementato)

**Source-url-only** è il modello di distribuzione di conformità GPL/IP: Lava pubblica soltanto l'URL upstream + gli hash accettati; il dispositivo recupera e analizza le liste da sé. Lava **non** memorizza, replica, trasforma o serve mai byte di blocklist di terze parti. Questo ha **sostituito il design R2-mirror abbandonato** (il piano originale "raw R2 mirror" è stato annullato il 2026-05-25).

Sul lato Worker, `syncOneBlocklist` recupera ogni sorgente upstream, la normalizza e ne calcola l'hash (computando `source_hash`, `normalized_hash`, `entry_count`) ma scrive `raw_r2_key = null` / `normalized_r2_key = null` — solo i metadati JSON del catalogo raggiungono R2. `check-gpl-blocklist-distribution.sh` è il guardrail di CI che applica l'intero modello: nessun codice di mirror/transform, nessun artefatto Lava/URL di download, nessuna sorgente GPL abilitata di default, nessuna scrittura R2 di byte di lista dal Worker, nessun testo "Lava-hosted mirror", nessun `.txt`/`.json` GPL inclusi nel bundle, e `source_url_only` richiesto nelle migrazioni + nei documenti legali.

> **Nota sulla licenza:** il codice Lava first-party viene distribuito sotto **AGPL-3.0** (il file `LICENSE` è la GNU AGPL v3, coerente con il badge del README). Le blocklist di terze parti (incluse HaGeZi, OISD e AdGuard) rimangono sotto le proprie licenze upstream — il modello source-url-only esiste proprio perché Lava possa usarle senza mai ridistribuire byte di liste copyleft. Qui GPL-3.0 è una proprietà delle liste upstream, non dell'app Lava.

---

## 6. Riepilogo dello stato

| Area | Stato |
|---|---|
| Precedenza delle query DNS (bootstrap > pause > filter) | Implementata |
| Precedenza decisionale del filtro (guardrail > allowlist > blocklist > default-allow) | Implementata |
| Slot di precedenza del threat-guardrail (collegato; distribuito ancora senza voci) | Implementato |
| DoH / DoH3 (etichetta h3 osservazionale) | Implementato |
| DoT (pool 4/endpoint, refresh idle a 8s, un retry nuovo) | Implementato |
| DoQ (connessione nuova per query, concorrenza a 4 corsie) | Implementato |
| Riuso connessione DoQ | Abbandonato / rimandato alla soglia iOS-26 |
| Degradazione del resolver + failover per endpoint + fallback device-DNS | Implementato |
| Budget delle regole di filtro (Free 500K / Plus 2M) | Implementato |
| Guardrail del dispositivo a ~3.26M regole (obiettivo 32 MB sotto la soglia NE di 50 MiB) | Implementato |
| mmap zero-copy dello snapshot compatto | Implementato |
| Catalogo source-url-only + fetch upstream diretto + validazione hash | Implementato |
| Filtro dei domini protetti | Implementato |
| Default free = Block List Basic | Implementato (catalogo generato + proiezioni iOS/backend concordi) |
| Licenza del codice Lava first-party | AGPL-3.0 (`LICENSE`); le liste di terze parti restano GPL-3.0 upstream |

---

## Vedi anche

- [`../product/overview.md`](../product/overview.md) — riga di presentazione del prodotto, promessa di privacy, schede.
- Tier e monetizzazione (riferimento interno) — Lava Security Plus e il budget delle regole di filtro come metrica di tier.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — la decisione di conformità source-url-only.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licenze e attribuzioni delle blocklist/resolver upstream.
