---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Filtraggio DNS e blocklist

> Destinatari: ingegneri. Questo documento descrive la pipeline DNS sul dispositivo, il percorso del resolver con trasporto cifrato, il motore decisionale di filtraggio e il modello del catalogo delle blocklist basato solo su source-url — con i numeri precisi che il codice impone. Lo stato riflette la realtà confermata dal codice. Dove un piano e il codice non concordano, **vince il codice** e la divergenza viene segnalata in linea.

Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva soltanto i metadati del catalogo, un backup cifrato e opaco per ogni utente e i dati diagnostici anonimizzati che scegli di inviare.

Lava è **filtraggio DNS/blocklist locale**, non una garanzia che ogni dominio o URL dannoso venga bloccato.

---

## 1. La pipeline DNS (Implementata) {#1-the-dns-pipeline-implemented}

Il motore di filtraggio/risoluzione gira all'interno del **tunnel NE / packet tunnel** — l'estensione `NEPacketTunnelProvider` `LavaSecTunnel` (`com.lavasec.app.tunnel`), che intercetta solo il DNS. Gli indirizzi del tunnel sono `10.255.0.2` (tunnel) e `10.255.0.1` (server DNS). Il processo dell'app non vede mai il traffico delle query; scrive soltanto gli artefatti compilati nell'**App Group** (`group.com.lavasec`) e segnala il tunnel tramite i **provider message** di NETunnelProviderSession (non le notifiche Darwin).

Per ogni query DNS in entrata, il tunnel applica una **precedenza fissa delle query** in `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap-first è un invariante rigido.** Una query che risolve il nome host *proprio* del resolver configurato (l'endpoint DoH/DoT/DoQ) non deve mai essere bloccata o messa in pausa, altrimenti il tunnel non riuscirebbe affatto ad avviare il DNS cifrato. Il dispatcher accetta closure lazy, così ogni passo viene letto solo quando viene raggiunto, preservando lo short-circuit (nessuna lettura dello snapshot quando esiste una risposta di bootstrap; nessuna lettura della pausa durante il bootstrap).
- **temporary pause** inoltra a monte mentre è attivo un TTL di pausa avviato dall'utente.
- **filter** valuta il dominio rispetto allo snapshot compilato e lo inoltra oppure sintetizza una risposta bloccata.

Una query che supera il filtro (azione `.allow`) viene passata al percorso del resolver (§3). Il tunnel **fallisce in chiusura** all'avvio a freddo senza uno snapshot riutilizzabile: installa uno snapshot di runtime fail-closed che blocca tutto il traffico anziché risolvere senza filtri.

---

## 2. Il motore di filtraggio (Implementato) {#2-the-filtering-engine-implemented}

### 2.1 Precedenza decisionale {#21-decision-precedence}

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) applica la precedenza di sicurezza canonica:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Ordine | Set di regole | Esito | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

Un dominio che non supera la normalizzazione viene bloccato con motivo `.invalidDomain` (fail-safe). La stessa precedenza è rispecchiata nella forma binaria su disco (`CompactFilterSnapshot`). Il threat guardrail sta sopra la allowlist locale per scelta progettuale: **il pagamento non aggira mai il threat guardrail non aggirabile**, e un'eccezione dell'utente non può sbloccare un dominio del guardrail.

> Nota: nel working tree attuale `nonAllowableThreatRules` / `guardrailSources` sono vuoti (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); lo slot di precedenza è cablato e applicato, ma per ora viene rilasciato senza voci di guardrail.

### 2.2 Archiviazione delle regole e l'unità di memoria residente {#22-rule-storage-and-the-resident-memory-unit}

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) memorizza gli insiemi `exactDomains` + `suffixDomains`. La corrispondenza (`containsNormalized`) esegue una ricerca esatta più una scansione dei suffissi padre (stile `hasSuffix`) al momento della query — **non c'è assorbimento dei sottodomini al momento della compilazione**. Una riga wildcard valida è **una regola** e una voce nella tabella di memoria. Questa identità 1 riga = 1 regola è ciò che rende il conteggio delle regole la metrica onesta delle risorse (§4).

### 2.3 Forme dello snapshot compilato {#23-compiled-snapshot-forms}

- **`FilterSnapshot`** — il filtro compilato in memoria: `blockRules`, `allowRules`, `nonAllowableThreatRules` e il preset del resolver.
- **`CompactFilterSnapshot`** — la forma binaria su disco, adatta a mmap, che il tunnel legge effettivamente (magic `LSCFSNP1`, `fileVersion 1`). Viene caricata zero-copy tramite mmap (§4.3).

L'app scrive sia `filter-snapshot.json` sia `filter-snapshot.compact` nell'App Group; il tunnel decodifica l'artefatto compatto. Un percorso di **riuso a caldo all'avvio** (`FilterArtifactStore`) consente al tunnel di riutilizzare l'artefatto compatto su disco senza ricompilare, condizionato da un'impronta di identità + un manifest scritto in modo atomico; il riuso viene rifiutato (motivo privacy-safe, con il solo nome del campo) quando cambiano il trasporto del resolver, la copertura del catalogo o gli input dello snapshot.

---

## 3. Trasporti cifrati e il percorso del resolver (Implementato) {#3-encrypted-transports--the-resolver-path-implemented}

### 3.1 Enum dei trasporti {#31-transport-enum}

Le query non bloccate vengono inoltrate al resolver a monte configurato. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) ha **cinque** valori:

| Trasporto | Valore raw | Annotazione mostrata nell'interfaccia |
|---|---|---|
| Device DNS | `device-dns` | *(nessuna — il nome è il trasporto)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

I preset integrati sono Google, Cloudflare, Quad9, Mullvad (ciascuno nelle varianti IP / DoH / DoT) più Device DNS e Custom. I resolver personalizzati accettano un server IPv4/IPv6 semplice, un URL DoH, un URL DoT (`tls://` / `dot://`), un URL DoQ (`doq://` / `quic://`) oppure uno stamp DNS `sdns://`; nomi utente/password e localhost vengono rifiutati. DoH/DoT/DoQ usano per impostazione predefinita la porta `853` per DoT/DoQ e richiedono un percorso per DoH.

### 3.2 DoH / DoH3 {#32-doh--doh3}

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) esegue DoH su `URLSession`. Ogni richiesta opta per HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); il loader di Apple ricade nativamente su H2/H1, quindi questo non rende mai irraggiungibile un resolver raggiungibile. Il protocollo negoziato viene letto da `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

L'interfaccia annota **`DoH3` (senza barra)** — ad es. "Quad9 (DoH3)" — **solo quando viene effettivamente osservata una negoziazione h3** (`DoHHTTPVersion.dohAnnotation`); altrimenti mostra `DoH`. DoH3 è preferito, mai promesso: l'etichetta è osservativa e legata al resolver, mai persistita (il riporto di "DoH3 confermato" tra un riavvio e l'altro è stato annullato). Le richieste fanno POST di `application/dns-message`; le risposte vengono validate per content-type e lunghezza e l'ID di transazione viene ripristinato prima della riscrittura.

### 3.3 DoT {#33-dot}

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection` in pool, **fino a 4 connessioni per endpoint** (`maxConnectionsPerEndpoint = 4`), round-robin, così le query parallele evitano il blocco testa-coda (head-of-line). Gestisce la **scadenza per inattività**: provider come Cloudflare chiudono lato server le connessioni DoT inattive (~10s) senza segnalare un cambio di stato, quindi una connessione riutilizzata inattiva da più di **8 secondi** (`reusedConnectionMaxIdleInterval = 8`) viene rinfrescata prima dell'invio, e un timeout su una connessione riutilizzata si guadagna **esattamente un nuovo tentativo con connessione fresca**.

### 3.4 DoQ — connessione nuova per ogni query {#34-doq--fresh-connection-per-query}

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantiene un pool limitato di **4 corsie per endpoint**, ma **ogni query apre una nuova connessione QUIC** — un handshake completo per ogni query. Il pool a 4 corsie fornisce **concorrenza, non riuso dell'handshake**.

**Stato del riuso delle connessioni DoQ (Abbandonato / rinviato).** Il riuso è stato esaminato e sottoposto a benchmark su dispositivo (34 handshake nuovi su 35 query ≈ nessun riuso), poi implementato come percorso `NWConnectionGroup` multi-stream condizionato a iOS 26, testato su dispositivo contro AdGuard DoQ, e **annullato perché netto-negativo** (errori di stream + errori di fallback contro un server reale). RFC 9250 mappa ogni query sul proprio stream QUIC, quindi il riuso richiede `NWConnectionGroup`/`openStream`, disponibile **solo su iOS 26.0+**; il floor di deployment attuale è **iOS 17**. Il riuso è rinviato finché il floor non raggiunge iOS 26. Il DoQ personalizzato viene rifiutato sui dispositivi che non lo supportano ("DNS over QUIC is not supported on this device").

### 3.5 Politica di risoluzione {#35-resolution-policy}

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) detiene la politica a monte:

1. **Instradamento del trasporto** in base al trasporto configurato.
2. **Degradazione a plain DNS** quando un piano cifrato non ha endpoint.
3. **Failover per endpoint** con un gate di backoff — un endpoint in backoff non tocca mai il filo (esito `backed-off`).
4. **Fallback su Device-DNS** quando il primario non restituisce risposta *e* il piano lo consente (la proprietà del piano è `shouldFallbackToDeviceDNS`, derivata dal campo di configurazione `fallbackToDeviceDNS`); il risultato viene riannotato come trasporto del dispositivo. L'esecuzione sul filo viene iniettata dietro gli executor, così la politica è testabile con unit test; lo stato di backoff resta fuori dalla politica pura.

---

## 4. Budget delle regole di filtro, ceiling NE e mmap {#4-filter-rules-budget-ne-ceiling-and-mmap}

La metrica del tier rilasciata è il **budget delle regole di filtro**: il totale delle **regole** di dominio compilate che un utente può abilitare. Ha sostituito il vecchio cap sul **numero** di liste abilitate (free 3 / a pagamento 10), che era un proxy disonesto — una lista può avere 1K o 1M di regole. Ci sono **due livelli**: un guardrail di dispositivo per tutti e un limite di monetizzazione per tier al di sotto di esso.

### 4.1 Limiti di tier (Implementati) {#41-tier-limits-implemented}

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) è la fonte di verità:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Blocklist / DNS personalizzati |
|---|---|---|---|---|
| **Free** | **500.000** | 25 | 25 | No |
| **Plus** (`.paid` / `.plus`) | **2.000.000** | 1.000 | 1.000 | Sì |

Il limite di tier è un confine di monetizzazione, **mai un paywall sul guardrail di dispositivo**. **Lava Security Plus** sblocca solo la personalizzazione — mai la sicurezza di base, mai il threat guardrail. Le blocklist personalizzate (a pagamento) vengono recuperate direttamente dal dispositivo dell'utente, analizzate e memorizzate nella cache localmente, e mai instradate ai server di Lava.

### 4.2 Guardrail di memoria del dispositivo + ceiling NE (Implementato) {#42-device-memory-guardrail--ne-ceiling-implemented}

Il packet tunnel è soggetto al **ceiling di memoria iOS di ~50 MiB per estensione** (un limite di progettazione dell'OS per ogni tipo di estensione per i packet tunnel dai tempi di iOS 15, non scalato sulla RAM; risiede in un `com.apple.jetsamproperties.{Model}.plist` per modello di dispositivo e può essere più basso sui dispositivi più vecchi). Superarlo provoca il jetsam. Non esiste un'API per il ceiling, quindi il budget mantiene un margine sotto il precipizio.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) fa il calcolo, espresso in regole di filtro (block + allow + guardrail):

| Costante | Valore |
|---|---|
| `baselineMegabytes` | 4.0 MB (overhead fisso del processo, misurato ≈3,5 MB, arrotondato per eccesso) |
| `estimatedBytesPerRule` | 9.0 B dirty residenti per regola (misurati ≈8,5 B, arrotondati per eccesso) |
| `maxResidentMegabytes` | 32.0 MB (ceiling obiettivo, lasciando ~10 MB di margine sotto il precipizio jetsam osservato di ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1.048.576) / 9 = 3.262.236 regole** |

Questo **guardrail di dispositivo da ~3,26M di regole** è il floor di sicurezza rigido per *ogni* utente, posto sopra qualsiasi tier di abbonamento, e **non è mai un paywall**. Misurazione di riferimento (dispositivo "chimmy", 2026-06-13): **789.831 regole → 9,9 MB di `phys_footprint`**, ovvero ≈ baseline + costo per regola.

### 4.3 Strategia mmap (Implementata) {#43-mmap-strategy-implemented}

Lo snapshot compatto viene caricato con `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), e `CompactBinaryReader` restituisce slice zero-copy. Il blob multi-megabyte di testo dei domini resta **file-backed/clean** ed è escluso dal `phys_footprint` conteggiato dal jetsam; solo le tabelle `[Entry]` decodificate costano memoria residente (~6 B/regola su disco, ~8,5 B dirty residenti). Questo alza il ceiling dei domini sul dispositivo: il costo residente sono le tabelle delle voci, non l'intero artefatto.

### 4.4 Applicazione a due livelli (Implementata) {#44-two-layer-enforcement-implemented}

- **Autorevole (al momento della compilazione).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) applica il budget sull'**unione deduplicata** di tutte le liste abilitate. Il guardrail di dispositivo viene controllato **per primo** (il floor rigido); il limite di tier vincola al di sotto. Le configurazioni fuori budget vengono rifiutate in modo deterministico — `exceedsDeviceMemoryBudget` o `exceedsTierFilterRuleLimit` — anziché lasciare che il tunnel finisca in jetsam. L'errore nomina le due liste che contribuiscono di più, così la correzione è ovvia.
- **Indicativa (interfaccia al momento della selezione).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) pilota il misuratore di selezione usando una **somma** per lista con un **margine di soft-ceiling di 1,10** che compensa il conteggio eccessivo cross-list del ~7–10% (la somma per lista sovrastima l'unione deduplicata).

### 4.5 Il parser (Implementato) {#45-the-parser-implemented}

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) conta le regole letteralmente: scarta commenti/righe vuote/righe non valide, normalizza, deduplica le stringhe esatte all'interno di una lista (tramite un `Set`) e applica un cap di **`maxRules = 1.000.000`** per lista (predefinito), con una lunghezza massima di riga di 4.096 caratteri. Formati supportati: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (auto prova hosts → dnsmasq → adblock → plain). Una riga valida = una regola = l'unità di memoria.

> **Righe `hosts` multi-host (versione 2 delle regole del parser).** Una riga `hosts` che mappa un IP a più host (`0.0.0.0 a.com b.com c.com`) ora emette **ogni** host come regola a sé, non solo il primo; `maxRules` viene applicato **per regola** (non per riga), così una riga multi-host vicina al cap non può sforare. Poiché gli stessi byte a monte ora possono produrre più regole, la versione delle regole del parser è stata portata da **1 → 2**, invalidando le voci `RuleSetCache` stantie analizzate con il vecchio comportamento solo-primo-host.

### 4.6 Robustezza di download e decodifica (Implementata) {#46-download--decode-robustness-implemented}

Il tunnel e la sincronizzazione del catalogo girano dentro il budget di memoria NE, quindi l'ingestione delle liste è irrobustita contro input ostili o malformati:

- **Download in streaming.** `defaultDataFetcher` scarica i byte della lista su un file temporaneo tramite `URLSession.download` (picco di memoria limitato) con un controllo della dimensione post-download (`maximumBlocklistBytes`) invece di bufferizzare l'intero corpo in RAM; un corpo sovradimensionato solleva `BlocklistDownloadSizeLimitExceeded`.
- **Cap sui metadati del catalogo (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes` rifiuta un catalogo remoto sovradimensionato prima della decodifica, così un host ostile/MITM non può forzare una decodifica JSON in OOM nell'estensione.
- **Decodifica UTF-8 indulgente.** Un singolo byte UTF-8 non valido non rifiuta più un'intera lista (cosa che, in regime fail-closed, bloccherebbe tutto il DNS); i byte non validi diventano U+FFFD e solo la riga incriminata non supera la validazione per riga e viene scartata.
- **Errori nominati per le blocklist personalizzate.** Una lista personalizzata fallita ora mostra `customBlocklistUnavailable(displayName:reason:)` — "Couldn't load the custom blocklist '<name>'. <why>" — invece di un `URLError` grezzo; l'annullamento viene propagato come annullamento, non come fallimento del download.

---

## 5. Catalogo delle blocklist e sorgenti predefinite {#5-blocklist-catalog--default-sources}

### 5.1 Modello del catalogo (Implementato) {#51-catalog-model-implemented}

Il **catalogo delle blocklist** è l'elenco pubblicato delle sorgenti disponibili. Il **Worker lavasec-api** serve i metadati JSON da un bucket R2 su `GET /v1/catalog` (e `/v1/catalog/:version`); il dispositivo recupera i **byte** effettivi della lista direttamente da ciascun `source_url` a monte. Gli endpoint del catalogo iOS sono `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

Sul dispositivo, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Recupera i byte della lista direttamente da `source.sourceURL`, applicando un cap di dimensione.
2. Calcola lo SHA-256 e accetta i byte solo se il checksum è negli `accepted_source_hashes` del catalogo.
3. In caso di mancata corrispondenza, ricade sull'ultima cache locale valida, oppure **fallisce in chiusura** (`checksumMismatch`) — a meno che la sorgente non consenta esplicitamente la rotazione diretta a monte.
4. Analizza/normalizza/deduplica localmente.
5. Filtra ogni set di regole analizzato tramite `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`), così una lista a monte non può mai bloccare i domini di Lava/Apple/provider di identità.

L'**insieme dei domini protetti** (filtrato prima dell'attivazione): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (tutti con corrispondenza per suffisso). Il Worker applica un filtro `PROTECTED_SUFFIXES` equivalente quando calcola i metadati; il dispositivo rivalida comunque.

### 5.2 Sorgenti curate (Implementate) {#52-curated-sources-implemented}

`DefaultCatalog.curatedSources` (`BlocklistModels.swift:232-243`) elenca **10** sorgenti:

| Sorgente | Licenza |
|---|---|
| Block List Basic | Unlicense |
| Block List Project Phishing | Unlicense |
| Block List Project Scam | Unlicense |
| Block List Project Ransomware | Unlicense |
| Phishing.Database Active Domains | MIT |
| HaGeZi Multi Light | GPL-3.0 |
| HaGeZi Multi Normal | GPL-3.0 |
| HaGeZi Multi PRO mini | GPL-3.0 |
| HaGeZi Multi PRO | GPL-3.0 |
| OISD Small | GPL-3.0 |

`guardrailSources` è vuoto. Le sorgenti GPL (HaGeZi, OISD) sono visibili nel catalogo ma **opt-in / DISATTIVATE per impostazione predefinita** in attesa dell'approvazione legale; il Worker condiziona la sincronizzazione/pubblicazione al lancio a `source_url_only` più i prefissi GPL consentiti (`hagezi-`/`oisd-`).

### 5.3 Liste abilitate per impostazione predefinita per gli utenti free (Implementate) {#53-default-enabled-lists-for-free-users-implemented}

La configurazione free predefinita effettiva è `OnboardingDefaults.lavaRecommendedDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`), che abilita **Block List Project Phishing + Block List Project Scam**, con il preset del resolver device-DNS (`resolverPresetID = DNSResolverPreset.device.id`) e il fallback su device-DNS attivo.

Quella impostazione predefinita free è **prodotta da `defaultEnabled`**, non hardcoded. `blockListProjectPhishing` (`BlocklistModels.swift:139`) e `blockListProjectScam` (`BlocklistModels.swift:148`) impostano entrambi `defaultEnabled: true`, e `DefaultCatalog.recommendedDefaultSourceIDs` (`BlocklistModels.swift:250-252`) è derivato da `curatedSources.filter(\.defaultEnabled)`. Il commento nel codice (`BlocklistModels.swift:246-249`) definisce `defaultEnabled` "l'unica fonte di verità per l'impostazione predefinita all'installazione pulita", rispecchiando la colonna `default_enabled` del catalogo di backend. Scorrendo attraverso `recommendedDefaultSourceIDs` dentro `OnboardingDefaults`, `defaultEnabled` è il meccanismo attivo — basta cambiare il flag su una sorgente per cambiare l'impostazione predefinita.

> **Fonte di verità dell'impostazione predefinita (vince il codice).** Qualsiasi testo del piano/catalogo che dica "Block List Basic è l'unica predefinita" è errato per il dispositivo; il dispositivo rilascia Phishing + Scam in base a `defaultEnabled: true`, e il flag iOS `BlocklistSource.defaultEnabled` è il meccanismo attivo autorevole. La colonna `default_enabled` del catalogo di backend è stata riallineata allo stesso set Phishing + Scam da una migrazione, quindi i metadati serviti da `/v1/catalog` ora corrispondono al client. Il testo del sito pubblico "Enabled blocklists 3 → 10" è ancora **stantio** — il vero gate è il budget delle regole di filtro 500K/2M, non un conteggio di liste.

### 5.4 Modello di distribuzione GPL basato solo su source-url (Implementato) {#54-source-url-only-gpl-distribution-model-implemented}

**Source-url-only** è il modello di distribuzione conforme a GPL/IP: Lava pubblica solo l'URL a monte + gli hash accettati; il dispositivo recupera e analizza le liste da solo. Lava **non** archivia, mirrora, trasforma o serve mai i byte di blocklist di terze parti. Questo **ha soppiantato il progetto R2-mirror abbandonato** (il piano originale "raw R2 mirror" è stato annullato il 2026-05-25).

Lato Worker, `syncOneBlocklist` recupera ogni sorgente a monte e la normalizza+hasha (calcolando `source_hash`, `normalized_hash`, `entry_count`) ma scrive `raw_r2_key = null` / `normalized_r2_key = null` — solo i metadati JSON del catalogo raggiungono R2. `check-gpl-blocklist-distribution.sh` è la sentinella CI che impone l'intero modello: niente codice di mirror/trasformazione, niente URL di artefatti/download di Lava, nessuna sorgente GPL abilitata per impostazione predefinita, nessuna scrittura R2 di byte di lista da parte del Worker, nessun testo "mirror ospitato da Lava", nessun `.txt`/`.json` GPL incluso nel bundle, e `source_url_only` richiesto nelle migrazioni + nei documenti legali.

> **Nota sulla licenza:** il codice di prima parte di Lava viene rilasciato sotto **AGPL-3.0** (il file `LICENSE` è GNU AGPL v3, in linea con il badge del README). Le blocklist di terze parti (HaGeZi, OISD) restano **GPL-3.0** sotto le loro licenze a monte — il modello source-url-only esiste proprio perché Lava possa usarle senza mai ridistribuire byte con licenza GPL. GPL-3.0 qui è una proprietà delle liste a monte, non dell'app Lava.

---

## 6. Riepilogo dello stato {#6-status-summary}

| Area | Stato |
|---|---|
| Precedenza delle query DNS (bootstrap > pause > filter) | Implementata |
| Precedenza decisionale del filtro (guardrail > allowlist > blocklist > default-allow) | Implementata |
| Slot di precedenza del threat-guardrail (cablato; rilasciato senza voci per ora) | Implementato |
| DoH / DoH3 (etichetta h3 osservativa) | Implementato |
| DoT (pool 4/endpoint, refresh idle a 8s, un nuovo tentativo fresco) | Implementato |
| DoQ (connessione nuova per query, concorrenza a 4 corsie) | Implementato |
| Riuso delle connessioni DoQ | Abbandonato / rinviato al floor iOS-26 |
| Degradazione del resolver + failover per endpoint + fallback device-DNS | Implementati |
| Budget delle regole di filtro (Free 500K / Plus 2M) | Implementato |
| Guardrail di dispositivo da ~3,26M di regole (obiettivo 32 MB sotto il ceiling NE da 50 MiB) | Implementato |
| mmap zero-copy dello snapshot compatto | Implementato |
| Catalogo source-url-only + recupero diretto a monte + validazione hash | Implementato |
| Filtro dei domini protetti | Implementato |
| Predefinita free = Phishing + Scam (non Basic) | Implementato (catalogo riallineato per corrispondere) |
| Licenza del codice di prima parte di Lava | AGPL-3.0 (`LICENSE`); le liste di terze parti restano GPL-3.0 a monte |

---

## Vedi anche {#see-also}

- [`../product/overview.md`](../product/overview.md) — descrizione del prodotto in una riga, promessa sulla privacy, schede.
- Tier e monetizzazione (riferimento interno) — Lava Security Plus e il budget delle regole di filtro come metrica del tier.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — la decisione di conformità source-url-only.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licenze e attribuzioni delle blocklist/resolver a monte.
