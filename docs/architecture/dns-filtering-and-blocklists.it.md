---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Filtraggio DNS e blocklist

> Destinatari: ingegneri. Questo documento descrive la pipeline DNS sul dispositivo, il percorso del resolver con trasporto cifrato, il motore decisionale di filtraggio e il modello del catalogo delle blocklist basato solo sull'URL di origine, con i numeri precisi che il codice applica. Lo stato riflette la realtà confermata dal codice. Dove un piano e il codice non concordano, **vince il codice** e la divergenza viene segnalata in linea.

Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i propri server e non riceve mai l'elenco dei domini che visiti — il backend conserva soltanto i metadati del catalogo, un backup cifrato per utente opaco e diagnostiche anonimizzate che scegli di inviare.

Lava è un sistema di **filtraggio DNS/blocklist locale**, non una garanzia che ogni dominio o URL dannoso venga bloccato.

---

## 1. La pipeline DNS (Implementata)

Il motore di filtraggio/risoluzione gira all'interno del **packet tunnel NE** — l'estensione `NEPacketTunnelProvider` `LavaSecTunnel` (`com.lavasec.app.tunnel`), che intercetta solo il DNS. Gli indirizzi del tunnel sono `10.255.0.2` (tunnel) e `10.255.0.1` (server DNS). Il processo dell'app non vede mai il traffico delle query; si limita a scrivere artefatti compilati nell'**App Group** (`group.com.lavasec`) e a segnalare al tunnel tramite i **provider messages** di NETunnelProviderSession (non le notifiche Darwin).

Per ogni query DNS in ingresso il tunnel esegue una **precedenza delle query** fissa in `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **il bootstrap prima di tutto è un invariante rigido.** Una query che risolve il nome host *del resolver stesso* configurato (l'endpoint DoH/DoT/DoQ) non deve mai essere bloccata o messa in pausa, altrimenti il tunnel non potrebbe nemmeno avviare il DNS cifrato. Il dispatcher accetta closure pigre, così ogni passo viene letto solo quando lo si raggiunge, preservando il corto circuito (nessuna lettura dello snapshot quando esiste una risposta di bootstrap; nessuna lettura della pausa durante il bootstrap).
- **temporary pause** inoltra a monte mentre è attivo un TTL di pausa avviato dall'utente.
- **filter** valuta il dominio rispetto allo snapshot compilato e lo inoltra oppure sintetizza una risposta bloccata.

Una query che supera il filtro (azione `.allow`) viene passata al percorso del resolver (§3). All'avvio a freddo, senza uno snapshot riutilizzabile, il tunnel **fallisce in modo chiuso**: installa uno snapshot di runtime fail-closed che blocca tutto il traffico anziché risolverlo senza filtri.

---

## 2. Il motore di filtraggio (Implementato)

### 2.1 Precedenza delle decisioni

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) applica la precedenza canonica di sicurezza:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Ordine | Insieme di regole | Esito | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

Un dominio che non supera la normalizzazione viene bloccato con motivo `.invalidDomain` (fail-safe). La stessa precedenza è rispecchiata nella forma binaria su disco (`CompactFilterSnapshot`). Il threat guardrail è collocato sopra la allowlist locale per scelta progettuale: **un pagamento non aggira mai il threat guardrail non aggirabile**, e un'eccezione dell'utente non può sbloccare un dominio del guardrail.

> Nota: nell'attuale working tree `nonAllowableThreatRules` / `guardrailSources` sono vuoti (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); lo slot di precedenza è cablato e applicato, ma viene distribuito senza ancora alcuna voce del guardrail.

### 2.2 Archiviazione delle regole e l'unità di memoria residente

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) memorizza gli insiemi `exactDomains` + `suffixDomains`. La corrispondenza (`containsNormalized`) effettua una ricerca esatta più un percorso sul suffisso padre (stile `hasSuffix`) al momento della query — **non c'è alcuna inclusione dei sottodomini al momento della compilazione**. Una riga wildcard valida è **una regola** e una voce nella tabella di memoria. Questa identità 1 riga = 1 regola è ciò che rende il conteggio delle regole una metrica onesta delle risorse (§4).

### 2.3 Forme dello snapshot compilato

- **`FilterSnapshot`** — il filtro compilato in memoria: `blockRules`, `allowRules`, `nonAllowableThreatRules` e il preset del resolver.
- **`CompactFilterSnapshot`** — la forma binaria su disco, adatta a mmap, che il tunnel legge effettivamente (magic `LSCFSNP1`, `fileVersion 1`). Viene caricata zero-copy tramite mmap (§4.3).

L'app scrive sia `filter-snapshot.json` sia `filter-snapshot.compact` nell'App Group; il tunnel decodifica l'artefatto compatto. Un percorso di **riutilizzo all'avvio a caldo** (`FilterArtifactStore`) consente al tunnel di riutilizzare l'artefatto compatto su disco senza ricompilarlo, vincolato da un'impronta di identità + un manifest scritto in modo atomico; il riutilizzo viene rifiutato (con un motivo rispettoso della privacy, basato solo sul nome del campo) quando cambiano il trasporto del resolver, la copertura del catalogo o gli input dello snapshot.

---

## 3. Trasporti cifrati e il percorso del resolver (Implementati)

### 3.1 Enum dei trasporti

Le query non bloccate vengono inoltrate al resolver a monte configurato. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) ha **cinque** valori:

| Trasporto | Valore grezzo | Annotazione mostrata nell'interfaccia |
|---|---|---|
| DNS del dispositivo | `device-dns` | *(nessuna — il nome è il trasporto)* |
| DNS in chiaro | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

I preset integrati sono Google, Cloudflare, Quad9, Mullvad (ciascuno nelle varianti IP / DoH / DoT) più il DNS del dispositivo e Personalizzato. I resolver personalizzati accettano un server IPv4/IPv6 in chiaro, un URL DoH, un URL DoT (`tls://` / `dot://`), un URL DoQ (`doq://` / `quic://`) o uno stamp DNS `sdns://`; nomi utente/password e localhost vengono rifiutati. DoH/DoT/DoQ usano per impostazione predefinita la porta `853` per DoT/DoQ e richiedono un percorso per DoH.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) esegue DoH su `URLSession`. Ogni richiesta abilita HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); il loader di Apple ripiega su H2/H1 in modo nativo, quindi questo non rende mai irraggiungibile un resolver raggiungibile. Il protocollo negoziato viene letto da `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

L'interfaccia annota **`DoH3` (senza slash)** — ad es. "Quad9 (DoH3)" — **solo quando si osserva effettivamente una negoziazione h3** (`DoHHTTPVersion.dohAnnotation`); altrimenti mostra `DoH`. DoH3 è preferito, mai promesso: l'etichetta è osservativa e legata al resolver, mai persistita (il riporto di "DoH3 confermato" tra un riavvio e l'altro è stato annullato). Le richieste inviano in POST `application/dns-message`; le risposte vengono validate per content-type e lunghezza e l'ID della transazione viene ripristinato prima della riscrittura.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection` raggruppate in un pool, **fino a 4 connessioni per endpoint** (`maxConnectionsPerEndpoint = 4`), a rotazione (round-robin), così le query parallele evitano il blocco in testa alla coda. Gestisce la **stanchezza da inattività**: provider come Cloudflare chiudono lato server le connessioni DoT inattive (~10s) senza segnalare alcun cambio di stato, quindi una connessione riutilizzata inattiva per più di **8 secondi** (`reusedConnectionMaxIdleInterval = 8`) viene rinfrescata prima dell'invio, e un timeout su una connessione riutilizzata vale **esattamente un nuovo tentativo con connessione fresca**.

### 3.4 DoQ — connessione fresca per ogni query

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantiene un pool limitato di **4 corsie per endpoint**, ma **ogni query apre una connessione QUIC fresca** — un handshake completo per query. Il pool a 4 corsie fornisce **concorrenza, non il riutilizzo dell'handshake**.

**Stato del riutilizzo delle connessioni DoQ (Abbandonato / rinviato).** Il riutilizzo è stato esaminato e sottoposto a benchmark su dispositivo (34 handshake freschi su 35 query ≈ nessun riutilizzo), poi implementato come percorso multi-stream `NWConnectionGroup` vincolato a iOS 26, testato su dispositivo contro AdGuard DoQ, e **annullato perché netto negativo** (errori di stream + errori di fallback contro un server reale). L'RFC 9250 mappa ogni query sul proprio stream QUIC, quindi il riutilizzo richiede `NWConnectionGroup`/`openStream`, disponibili **solo su iOS 26.0+**; l'attuale soglia minima di distribuzione è **iOS 17**. Il riutilizzo è rinviato finché la soglia non raggiungerà iOS 26. Il DoQ personalizzato viene rifiutato sui dispositivi che non lo supportano ("DNS over QUIC is not supported on this device").

### 3.5 Politica di risoluzione

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) gestisce la politica a monte:

1. **Instradamento del trasporto** in base al trasporto configurato.
2. **Degradazione al DNS in chiaro** quando un piano cifrato non ha endpoint.
3. **Failover per endpoint** con un cancello di backoff — un endpoint in backoff non tocca mai il filo (esito `backed-off`).
4. **Fallback al DNS del dispositivo** quando il primario non restituisce alcuna risposta *e* il piano lo consente (la proprietà del piano è `shouldFallbackToDeviceDNS`, derivata dal campo di configurazione `fallbackToDeviceDNS`); il risultato viene riannotato come trasporto del dispositivo. L'esecuzione sul filo è iniettata dietro a degli executor così la politica è verificabile con i test unitari; lo stato di backoff resta al di fuori della politica pura.

---

## 4. Budget delle regole di filtraggio, soffitto NE e mmap

La metrica di tier distribuita è il **budget delle regole di filtraggio**: il totale delle **regole** di dominio compilate che un utente può abilitare. Questo ha sostituito il vecchio limite sul **numero** di elenchi abilitati (free 3 / paid 10), che era un proxy disonesto — un elenco può avere da 1K a 1M di regole. Ci sono **due livelli**: un guardrail del dispositivo per tutti e un limite di monetizzazione per tier al di sotto di esso.

### 4.1 Limiti per tier (Implementati)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) è la fonte di verità:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Blocklist / DNS personalizzati |
|---|---|---|---|---|
| **Free** | **500.000** | 10 | 10 | No |
| **Plus** (`.paid` / `.plus`) | **2.000.000** | 500 | 500 | Sì |

Il limite di tier è un confine di monetizzazione, **mai un paywall sul guardrail del dispositivo**. **Lava Security Plus** sblocca soltanto la personalizzazione — mai la sicurezza di base, mai il threat guardrail. Le blocklist personalizzate (a pagamento) vengono recuperate direttamente dal dispositivo dell'utente, analizzate e memorizzate localmente, e mai inoltrate ai server di Lava.

### 4.2 Guardrail di memoria del dispositivo + soffitto NE (Implementati)

Il packet tunnel è soggetto al **soffitto di memoria di iOS di ~50 MiB per estensione** (un limite di progettazione dell'OS per tipo di estensione per i packet tunnel a partire da iOS 15, non scalato con la RAM; risiede in un file `com.apple.jetsamproperties.{Model}.plist` per modello di dispositivo e può essere più basso sui dispositivi più vecchi). Superarlo provoca il jetsam. Non esiste alcuna API per conoscere il soffitto, quindi il budget mantiene un margine sotto il limite.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) fa i calcoli, espressi in regole di filtraggio (block + allow + guardrail):

| Costante | Valore |
|---|---|
| `baselineMegabytes` | 4,0 MB (overhead fisso del processo, misurato ≈3,5 MB, arrotondato per eccesso) |
| `estimatedBytesPerRule` | 9,0 B residenti dirty per regola (misurati ≈8,5 B, arrotondati per eccesso) |
| `maxResidentMegabytes` | 32,0 MB (soffitto obiettivo, lasciando ~10 MB di margine sotto il limite di jetsam osservato a ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1.048.576) / 9 = 3.262.236 regole** |

Questo **guardrail del dispositivo di ~3,26M di regole** è il piano di sicurezza rigido per *ogni* utente, collocato sopra qualsiasi tier di abbonamento, e **non è mai un paywall**. Misurazione di riferimento (dispositivo "chimmy", 2026-06-13): **789.831 regole → 9,9 MB di `phys_footprint`**, ovvero ≈ baseline + costo per regola.

### 4.3 Strategia mmap (Implementata)

Lo snapshot compatto viene caricato con `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), e `CompactBinaryReader` restituisce slice zero-copy. Il blob di testo dei domini, grande diversi megabyte, rimane **file-backed/clean** ed è escluso dal `phys_footprint` conteggiato dal jetsam; solo le tabelle `[Entry]` decodificate costano memoria residente (~6 B/regola su disco, ~8,5 B residenti dirty). Questo alza il soffitto dei domini sul dispositivo: il costo residente sono le tabelle delle voci, non l'intero artefatto.

### 4.4 Applicazione a due livelli (Implementata)

- **Autorevole (al momento della compilazione).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) applica il budget sull'**unione deduplicata** di tutti gli elenchi abilitati. Il guardrail del dispositivo viene controllato **per primo** (il piano rigido); il limite di tier vincola al di sotto di esso. Le configurazioni fuori budget vengono rifiutate in modo deterministico — `exceedsDeviceMemoryBudget` o `exceedsTierFilterRuleLimit` — invece di lasciare che il tunnel vada in jetsam. L'errore nomina i due elenchi che contribuiscono di più, così la soluzione è ovvia.
- **Indicativa (interfaccia al momento della selezione).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) alimenta il misuratore di selezione usando una **somma** per elenco con un **margine di soffitto morbido di 1,10** che compensa la sovrastima del ~7–10% tra gli elenchi (la somma per elenco sovrastima l'unione deduplicata).

### 4.5 Il parser (Implementato)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) conta le regole alla lettera: scarta commenti/righe vuote/righe non valide, normalizza, deduplica le stringhe esatte all'interno di un elenco (tramite un `Set`) e impone un limite di **`maxRules = 1.000.000`** per elenco (predefinito), con una lunghezza massima di riga di 4.096 caratteri. Formati supportati: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (`auto` prova hosts → dnsmasq → adblock → plain). Una riga valida = una regola = l'unità di memoria.

---

## 5. Catalogo delle blocklist e fonti predefinite

### 5.1 Modello del catalogo (Implementato)

Il **catalogo delle blocklist** è l'elenco pubblicato delle fonti disponibili. Il **Worker lavasec-api** serve i metadati JSON da un bucket R2 su `GET /v1/catalog` (e `/v1/catalog/:version`); il dispositivo recupera i **byte** effettivi dell'elenco direttamente da ogni `source_url` a monte. Gli endpoint del catalogo iOS sono `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

Sul dispositivo, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Recupera i byte dell'elenco direttamente da `source.sourceURL`, imponendo un limite di dimensione.
2. Calcola lo SHA-256 e accetta i byte solo se il checksum è presente in `accepted_source_hashes` del catalogo.
3. In caso di discrepanza, ripiega sull'ultima cache locale valida, oppure **fallisce in modo chiuso** (`checksumMismatch`) — a meno che la fonte non consenta esplicitamente la rotazione diretta a monte.
4. Analizza/normalizza/deduplica localmente.
5. Filtra ogni insieme di regole analizzato attraverso `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`), così un elenco a monte non può mai bloccare i domini di Lava/Apple/del provider di identità.

L'**insieme di domini protetti** (escluso prima dell'attivazione): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (tutti confrontati per suffisso). Il Worker applica un filtro `PROTECTED_SUFFIXES` equivalente quando calcola i metadati; il dispositivo rivalida comunque.

### 5.2 Fonti curate (Implementate)

`DefaultCatalog.curatedSources` (`BlocklistModels.swift:232-243`) elenca **10** fonti:

| Fonte | Licenza |
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

`guardrailSources` è vuoto. Le fonti GPL (HaGeZi, OISD) sono visibili nel catalogo ma **opzionali / DISATTIVATE per impostazione predefinita** in attesa dell'approvazione legale; il Worker limita la sincronizzazione/pubblicazione al lancio a `source_url_only` più i prefissi GPL consentiti (`hagezi-`/`oisd-`).

### 5.3 Elenchi abilitati per impostazione predefinita per gli utenti free (Implementato)

La configurazione predefinita effettiva per il piano free è `OnboardingDefaults.lavaRecommendedDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`), che abilita **Block List Project Phishing + Block List Project Scam**, con il preset del resolver DNS del dispositivo (`resolverPresetID = DNSResolverPreset.device.id`) e il fallback al DNS del dispositivo attivo.

Quella configurazione predefinita free è **prodotta da `defaultEnabled`**, non scritta a codice. `blockListProjectPhishing` (`BlocklistModels.swift:139`) e `blockListProjectScam` (`BlocklistModels.swift:148`) impostano entrambi `defaultEnabled: true`, e `DefaultCatalog.recommendedDefaultSourceIDs` (`BlocklistModels.swift:250-252`) è derivato da `curatedSources.filter(\.defaultEnabled)`. Il commento nel codice (`BlocklistModels.swift:246-249`) definisce `defaultEnabled` "la singola fonte di verità per il valore predefinito all'installazione pulita", rispecchiando la colonna `default_enabled` del catalogo backend. Fluendo attraverso `recommendedDefaultSourceIDs` dentro `OnboardingDefaults`, `defaultEnabled` è il meccanismo attivo — basta cambiare il flag su una fonte per cambiare il valore predefinito.

> **Fonte di verità sul valore predefinito (vince il codice).** Qualsiasi testo di piano/catalogo che dica "Block List Basic è l'unico valore predefinito" è errato per il dispositivo; il dispositivo distribuisce Phishing + Scam tramite `defaultEnabled: true`, e il flag iOS `BlocklistSource.defaultEnabled` è il meccanismo attivo autorevole. La colonna `default_enabled` del catalogo backend è stata riallineata allo stesso insieme Phishing + Scam da una migrazione, quindi i metadati serviti da `/v1/catalog` ora corrispondono al client. Il testo del sito pubblico "Blocklist abilitate 3 → 10" è ancora **obsoleto** — il vero limite è il budget delle regole di filtraggio da 500K/2M, non un numero di elenchi.

### 5.4 Modello di distribuzione GPL basato solo sull'URL di origine (Implementato)

**Source-url-only** è il modello di distribuzione conforme a GPL/proprietà intellettuale: Lava pubblica solo l'URL a monte + gli hash accettati; il dispositivo recupera e analizza gli elenchi da sé. Lava **non** archivia, replica, trasforma o serve mai i byte delle blocklist di terze parti. Questo ha **sostituito il design abbandonato del mirror R2** (il piano originale del "mirror R2 grezzo" è stato annullato il 2026-05-25).

Sul lato Worker, `syncOneBlocklist` recupera ogni fonte a monte e la normalizza+hasha (calcolando `source_hash`, `normalized_hash`, `entry_count`) ma scrive `raw_r2_key = null` / `normalized_r2_key = null` — solo i metadati JSON del catalogo raggiungono R2. `check-gpl-blocklist-distribution.sh` è il controllo di CI che applica l'intero modello: niente codice di mirror/trasformazione, niente URL di artefatti/download di Lava, nessuna fonte GPL abilitata per impostazione predefinita, nessuna scrittura su R2 dei byte degli elenchi da parte del Worker, nessun testo "mirror ospitato da Lava", nessun file GPL `.txt`/`.json` incluso, e `source_url_only` richiesto nelle migrazioni + nei documenti legali.

> **Nota sulle licenze:** il codice di prima parte di Lava è distribuito sotto **AGPL-3.0** (il file `LICENSE` è la GNU AGPL v3, in linea con il badge del README). Le blocklist di terze parti (HaGeZi, OISD) restano **GPL-3.0** sotto le proprie licenze a monte — il modello basato solo sull'URL di origine esiste proprio perché Lava possa usarle senza mai ridistribuire byte sotto licenza GPL. Qui GPL-3.0 è una proprietà degli elenchi a monte, non dell'app Lava.

---

## 6. Riepilogo dello stato

| Area | Stato |
|---|---|
| Precedenza delle query DNS (bootstrap > pausa > filtro) | Implementata |
| Precedenza delle decisioni di filtraggio (guardrail > allowlist > blocklist > default-allow) | Implementata |
| Slot di precedenza del threat guardrail (cablato; distribuito ancora senza voci) | Implementato |
| DoH / DoH3 (etichetta h3 osservativa) | Implementato |
| DoT (pool di 4/endpoint, refresh dopo 8s di inattività, un nuovo tentativo fresco) | Implementato |
| DoQ (connessione fresca per query, concorrenza a 4 corsie) | Implementato |
| Riutilizzo delle connessioni DoQ | Abbandonato / rinviato alla soglia iOS 26 |
| Degradazione del resolver + failover per endpoint + fallback al DNS del dispositivo | Implementato |
| Budget delle regole di filtraggio (Free 500K / Plus 2M) | Implementato |
| Guardrail del dispositivo di ~3,26M di regole (obiettivo 32 MB sotto il soffitto NE di 50 MiB) | Implementato |
| mmap zero-copy dello snapshot compatto | Implementato |
| Catalogo basato solo sull'URL di origine + recupero diretto a monte + validazione hash | Implementato |
| Filtro dei domini protetti | Implementato |
| Default free = Phishing + Scam (non Basic) | Implementato (catalogo riallineato per corrispondere) |
| Licenza del codice di prima parte di Lava | AGPL-3.0 (`LICENSE`); gli elenchi di terze parti restano GPL-3.0 a monte |

---

## Vedi anche

- [`../product/overview.md`](../product/overview.md) — descrizione del prodotto in una riga, promessa sulla privacy, schede.
- Tier e monetizzazione (riferimento interno) — Lava Security Plus e il budget delle regole di filtraggio come metrica di tier.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — la decisione di conformità basata solo sull'URL di origine.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licenze e attribuzioni delle blocklist/resolver a monte.
