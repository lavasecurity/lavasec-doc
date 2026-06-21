---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Decisioni di progettazione principali

> Pubblico: ingegneri e dirigenza. Questo è il registro in stile ADR delle decisioni di progettazione portanti dietro Lava Security — quelle che hanno dato forma all'architettura, alla promessa sulla privacy o ai confini del prodotto, e in particolare quelle che sono state provate e poi annullate. Ogni voce indica la **Decisione**, il suo **Contesto**, la **Motivazione** e uno **Stato** tratto dalla legenda di stato del progetto (Adottata / Annullata / Sostituita / Proposta).
>
> **Il codice ha la precedenza.** Dove un piano e il codice rilasciato non concordano, questo registro segue il codice e segnala la divergenza nel testo.

**Legenda di stato (mappata alle corsie di stato del set di documenti):**

| Stato qui | Significato della corsia nel set di documenti |
|---|---|
| **Adottata** | Implementata — rilasciata e confermata nel codice |
| **Annullata** | Abbandonata — costruita, poi rimossa/annullata |
| **Sostituita** | Una decisione precedente sostituita da una successiva |
| **Proposta** | Pianificata — progettata, raccomandata o registrata, ma non ancora applicata in questo albero |

Letture correlate: modello di distribuzione del catalogo in [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) e [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); comportamento rilasciato in [`../product/features.md`](../product/features.md). La direzione futura vive nella roadmap interna.

---

## 1. Filtraggio DNS sul dispositivo tramite `NEPacketTunnelProvider` {#1-on-device-dns-filtering-via-nepackettunnelprovider}

**Decisione.** Filtrare il DNS **localmente sul dispositivo** tramite un tunnel a pacchetti `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), anziché `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` o un content blocker di Safari.

**Contesto.** Il prodotto è un filtro privacy-first per utenti non tecnici (genitori, persone anziane) distribuito tramite l'App Store consumer, senza necessità di un account. Gli altri provider NetworkExtension e le API di DNS gestito sono riservati a dispositivi supervisionati/gestiti da MDM oppure non coprono tutto il DNS di un'app, e un modello lato resolver instraderebbe il flusso di domini dell'utente fuori dal dispositivo.

**Motivazione.** Il tunnel a pacchetti è l'unico provider che (a) funziona su dispositivi consumer non gestiti e (b) consente che ogni decisione DNS avvenga sul dispositivo, che è la base della promessa sulla privacy: *tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i propri server e non riceve mai il flusso dei domini che visiti.* Il compromesso accettato in cambio è il **limite di memoria di iOS di ~50 MiB per estensione** entro cui il tunnel deve restare — un vincolo che dà forma a diverse decisioni successive qui sotto.

**Stato.** **Adottata** (fondante; nel codice fin dal prototipo iniziale).

---

## 2. Distribuzione della blocklist solo tramite source-url {#2-source-url-only-blocklist-distribution}

**Decisione.** Lava pubblica soltanto l'**URL** della blocklist upstream **più gli hash accettati**; il dispositivo scarica i **byte** della lista direttamente da ciascun `source_url`, poi li analizza, normalizza, deduplica e filtra localmente. Lava **non** archivia, replica, trasforma o serve **mai** i byte delle blocklist di terze parti. Il Worker scrive su R2 soltanto i **metadati** del catalogo in JSON (`raw_r2_key`/`normalized_r2_key` sono null).

**Contesto.** Il progetto precedente replicava i byte grezzi delle blocklist su R2 affinché i legali potessero esaminare la distribuzione. Molte liste upstream (HaGeZi, OISD) sono GPL-3.0, quindi ospitarne i byte renderebbe Lava un ridistributore di dati GPL.

**Motivazione.** Trattare Lava come un motore di filtraggio locale / user agent — anziché come un distributore di blocklist — riduce al minimo l'esposizione alla ridistribuzione GPLv3 e alla revisione dell'App Store. Il dispositivo convalida i byte scaricati rispetto agli `accepted_source_hashes` del catalogo e ricade sull'ultima cache valida o fallisce in modo chiuso in caso di discrepanza, recuperando la proprietà di sicurezza che la pipeline di mirroring forniva. Ogni insieme di regole analizzato passa inoltre attraverso un filtro di domini protetti, così che una lista upstream non possa bloccare i domini di Lava/Apple/dei provider di identità. Il modello è imposto in CI da `check-gpl-blocklist-distribution.sh` (nessun codice di mirroring, nessun URL di artefatti ospitati da Lava, nessuna sorgente GPL abilitata per impostazione predefinita, nessuna scrittura di byte su R2).

**Stato.** **Adottata**, e ha **Sostituito** il piano abbandonato di raw-mirror su R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, intestazione "Superseded by the source-url-only implementation"). Vedi [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Trasporti resolver cifrati (DoH / DoH3 / DoT / DoQ) {#3-encrypted-resolver-transports-doh--doh3--dot--doq}

**Decisione.** Rilasciare quattro trasporti upstream cifrati accanto al DNS in chiaro e a un fallback sul DNS del dispositivo, estratti in LavaSecCore: **DoH** (URLSession), **DoH3** (DoH che preferisce HTTP/3), **DoT** (`NWConnection` in pool, fino a 4 per endpoint, con aggiornamento per inattività e un nuovo tentativo su connessione fresca) e **DoQ** (DNS-over-QUIC). Routing, degradazione al DNS in chiaro, failover per endpoint con un gate di backoff e fallback sul DNS del dispositivo vivono in `ResolverOrchestrator`.

**Contesto.** Inoltrare le query non bloccate in chiaro a un resolver espone proprio quel flusso di domini che il modello sul dispositivo deve proteggere. I trasporti sono stati costruiti in modo incrementale (DoH → DoH3 → DoT → DoQ).

**Motivazione.** Il trasporto upstream cifrato mantiene private le query non bloccate da un capo all'altro. **DoH3** è etichettato in modo puramente osservativo — `assumesHTTP3Capable=true` è impostato e il protocollo negoziato viene osservato, e la UI annota `DoH3` (senza slash) **solo quando una negoziazione h3 viene effettivamente osservata**, mai promessa, perché h3 è best-effort per connessione e un'affermazione permanente sovrastimerebbe il comportamento dietro firewall che bloccano UDP. Il pooling DoT con aggiornamento per inattività è stato una correzione diretta del fatto che Cloudflare chiudeva silenziosamente le connessioni DoT inattive.

**Stato.** **Adottata** (tutti e quattro i trasporti presenti e collegati).

---

## 4. Riuso delle connessioni DoQ — costruito, testato su dispositivo, annullato {#4-doq-connection-reuse--built-device-tested-reverted}

**Decisione.** **Non** riusare le connessioni QUIC per DoQ. `DoQTransport` apre una **nuova connessione QUIC per ogni query**; il pool a 4 corsie fornisce concorrenza, non riuso dell'handshake.

**Contesto.** RFC 9250 mappa ogni query DNS sul proprio stream QUIC, quindi il vero riuso richiede l'API multi-stream `NWConnectionGroup`/`openStream` che è **disponibile solo da iOS 26.0+**, mentre la soglia minima di deployment è iOS 17. È stato comunque implementato un percorso di riuso vincolato a iOS 26 (compilato in Debug+Release con l'SDK di Xcode 26) e **testato su dispositivo su iOS 26.5** contro DoQ di AdGuard.

**Motivazione.** Il percorso di riuso ha fallito a ogni tentativo sul dispositivo (`openStream`/`receive` davano errore, poi il fallback incappava in "Socket is not connected"), risultando **nettamente peggiore** rispetto al riferimento per-query (controllo: 34 handshake / 35 query, tutte riuscite). Questo ha confermato empiricamente la linea guida di Apple DTS "rimandare l'uso di QUIC con il nuovo framework Network", quindi il lavoro è stato annullato anziché rilasciato; solo i documenti e la motivazione del test di guardia conservano il risultato, così da non riprovarci prima che l'API maturi.

**Stato.** **Annullata** (rinviata fino a quando la soglia minima di deployment raggiungerà iOS 26). Descrivere DoQ come connessioni fresche per ogni query.

---

## 5. Rifiuto di un protocollo unificante `DNSResolvingTransport` {#5-reject-a-unifying-dnsresolvingtransport-protocol}

**Decisione.** **Non** unificare i trasporti del resolver sotto un unico protocollo `DNSResolvingTransport`; mantenere la giunzione `ResolverOrchestrator.Executors` basata su closure.

**Contesto.** Un refactor (issue 407) proponeva un unico protocollo su tutti i trasporti.

**Motivazione.** I trasporti sono troppo dissimili — executor cifrati asincroni (DoH/DoT/DoQ) rispetto a trasporti sincroni multi-indirizzo in chiaro/del dispositivo — quindi un protocollo unificante sarebbe un'astrazione peggiore della giunzione a closure iniettabile esistente, che già mantiene testabile l'esecuzione sul filo.

**Stato.** **Annullata** / non si implementa (chiusa come cattiva astrazione).

---

## 6. Backup cifrato a conoscenza zero (senza password, con l'eccezione passkey segnalata) {#6-zero-knowledge-encrypted-backup-passwordless-passkey-exception-noted}

**Decisione.** Effettuare il backup di un payload di impostazioni **minimizzato** lato client: AES-256-GCM lo sigilla con una chiave di payload casuale di 32 byte, che viene avvolta in **slot di chiave** per segreto tramite PBKDF2-HMAC-SHA256 (**210.000** iterazioni in produzione). Sulla tabella `user_backups` di Supabase (RLS per utente) carica solo il testo cifrato più i metadati non segreti. Il flusso rilasciato è **senza password**: slot del segreto del dispositivo (Keychain locale al dispositivo) + slot di recupero assistito + slot passkey opzionale.

**Contesto.** L'accesso opzionale con account (solo Apple + Google) abilita il ripristino delle impostazioni tra dispositivi. Il server non deve mai poter leggere le blocklist, le allowlist, la scelta del resolver o le altre impostazioni di un utente.

**Motivazione.** Il testo in chiaro e i segreti di decifratura esistono solo sul dispositivo; il server conserva una sola busta opaca per utente. Il recupero assistito è deliberatamente a due fattori — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (input delimitato da NUL) richiede **entrambi** la quota detenuta dal server e la frase di recupero di 8 parole dell'utente (~105 bit), così che nessuna delle due metà da sola decifri. Il materiale di sblocco è conservato localmente sul dispositivo (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **non** nel Keychain iCloud sincronizzabile — un irrobustimento della privacy che ha invertito il progetto sincronizzabile originale. Anche lo **slot passkey è genuinamente a conoscenza zero**: è avvolto con un output dell'autenticatore WebAuthn **PRF / `hmac-secret`** (derivato con HKDF-SHA256) che non lascia mai il client, così nessun valore detenuto dal server può sbloccarlo. Non esiste alcuna tabella passkey con ruolo di servizio né alcun gate di asserzione WebAuthn nel Worker — il precedente progetto di passkey con controllo lato server è stato abbandonato, rimuovendo tutto lo stato passkey lato server (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Stato.** **Adottata** (modello senza password, recupero assistito e uno slot passkey derivato da PRF a conoscenza zero, tutto nel codice). Rendere la passkey un fattore recuperabile pienamente pronto per la produzione su dispositivi fisici (Associated Domains / hosting AASA per il modello PRF) è **Proposta** (backlog).

---

## 7. Connect-On-Demand fail-closed {#7-fail-closed-connect-on-demand}

**Decisione.** Aggiungere una regola `NEOnDemandRuleConnect` affinché un tunnel fermato dal sistema operativo si riavvii automaticamente, con **fail-closed** come impostazione predefinita sicura: quando non c'è uno snapshot del filtro riutilizzabile, il tunnel blocca tutto il traffico anziché farlo passare senza filtro. L'on-demand viene **disabilitato prima di ogni arresto** così che la VPN resti spegnibile.

**Contesto.** iOS fermava silenziosamente il tunnel (motivo 17) senza che nulla lo riavviasse per ~45 minuti, lasciando gli utenti senza protezione. Abilitare l'on-demand in modo ingenuo rende impossibile spegnere la VPN, e un'impostazione predefinita fail-open farebbe passare il traffico durante l'intervallo.

**Motivazione.** L'on-demand chiude l'intervallo dell'arresto silenzioso; disabilitarlo-prima-dell'arresto preserva la capacità dell'utente di spegnere la protezione; il fail-closed garantisce che l'intervallo sia sicuro anziché silenziosamente senza filtro, recuperato da `reconcileTunnelSnapshotAfterLaunch`. La modifica ha avuto effetti collaterali — l'on-demand ha riattivato il prompt di sistema "Aggiungi configurazioni VPN" durante l'onboarding — che hanno generato una catena di correzioni in più commit: smettere di abilitare l'on-demand all'installazione, vincolare il ripristino di avvio/protezione al completamento dell'onboarding e **neutralizzare una configurazione ereditata/orfana rimuovendola** (`removeFromPreferences`, silenzioso) anziché salvando `on-demand=false` (`saveToPreferences` rimostrava il prompt).

**Stato.** **Adottata** (riavvio on-demand più la catena di correzioni onboarding/fail-closed).

---

## 8. Refactor modulare della VPN e la disciplina sulla regressione termica {#8-modular-vpn-refactor-and-the-heat-regression-discipline}

**Decisione.** Ristrutturare il percorso della VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) per un'attivazione cache-first, un fetch a parallelismo limitato e la coalescenza dei flap — trattando batteria/latenza come requisiti di prodotto con obiettivi espliciti p50/p95 e profilazione **sul dispositivo** (non sul Simulator).

**Contesto.** Attivazione / aggiornamento / pausa / ripresa erano lenti. Durante il refactor è comparsa una regressione termica (134% di CPU, energia alta, telefono caldo). Un ampio pannello di agenti ha dapprima smentito la causa sospetta usando prove pre-regressione; una cattura dal vivo sul dispositivo l'ha poi confermata.

**Motivazione.** La vera causa era un ciclo di aggiornamento `NEVPNStatusDidChange` auto-sostenuto — un ciclo di coalescenza che si riarmava all'infinito (~370 eventi/s, thread principale ~100%, `vpn-debug-log.jsonl` cresciuto a ~180–210 MB) dopo che una guardia drop-reentrant era stata sostituita. La correzione legge lo stato del manager dalla cache e limita il ciclo. Gli artefatti before/after sul dispositivo del piano stesso registrano l'attivazione a caldo (`action.turnOn`) scendere da **2.722 ms → 287 ms** su iPhone 15 Pro; una successiva e separata revisione delle opportunità post-modulare ha misurato il percorso a caldo a **112 ms** (decode 51 + managerSetup 57) sullo stesso dispositivo. L'episodio ha fissato lo standard: i refactor strutturali si fermano finché una regressione termica misurata non è contenuta, e i risultati termici/di batteria del Simulator sono respinti come privi di significato.

**Stato.** **Adottata** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Una revisione post-modulare mantiene `PacketTunnelProvider` e `AppViewModel` come noti god-object ancora sopravvissuti.

---

## 9. Budget di regole-filtro invece di un tetto al numero di liste {#9-filter-rules-budget-instead-of-a-list-count-cap}

**Decisione.** Vincolare i piani tramite un **budget di regole-filtro** — **Free 500K / Plus 2M** regole di dominio compilate — anziché tramite il numero di liste abilitate. Un rigido **guardrail del dispositivo di ~3,26M regole** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3.262.236`) si applica a **tutti** e **non è mai un paywall**. Il blob compatto dei domini è mappato con `mmap` (`.mappedIfSafe`) così da restare basato su file e fuori dal `phys_footprint` conteggiato da jetsam; solo le tabelle delle voci decodificate consumano memoria residente.

**Contesto.** Il vecchio tetto era un **numero** di liste (free 3 / paid 10). Una lista può contenere 1K o 1M regole, quindi il numero era un proxy disonesto della vera risorsa vincolata — il limite di memoria di 50 MiB della NE.

**Motivazione.** Le regole corrispondono alla memoria reale, quindi è ammessa qualsiasi combinazione di liste che ci stia. L'applicazione autorevole avviene in fase di compilazione sull'unione deduplicata in `FilterSnapshotPreparationService` (prima il guardrail del dispositivo, poi il limite del piano); il misuratore della UI in fase di selezione usa una somma per lista con un margine soft-ceiling di 1,10. Le configurazioni oltre budget vengono respinte in modo deterministico (mantenendo la protezione spenta) anziché lasciare che il tunnel finisca in jetsam.

**Stato.** **Adottata** nel codice (`SubscriptionPolicy.swift`), rilasciata in **v1.0.0**, che ha **Sostituito** il tetto al numero di liste. Il budget di regole è ora il gate di piano attivo; anche i tetti per-dominio sono stati alzati alla 1.0 (Free 25 / Plus 1.000 domini consentiti e bloccati). Vedi [`../product/features.md`](../product/features.md).

---

## 10. Piani come markdown + sincronizzazione a senso unico verso Linear {#10-plans-as-markdown--one-way-linear-sync}

**Decisione.** I file markdown in `plans/<lane>/` sono la **fonte di verità**; la **cartella della corsia è lo stato autorevole** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Un push su `main` sincronizza i piani **a senso unico** verso Linear (team LAV), aggiornando solo titolo/descrizione dopo la creazione; una tratta di ritorno separata, **manuale e revisionata** riporta stato/priorità/corsia di Linear nel frontmatter del piano.

**Contesto.** Un piccolo team ha bisogno di uno stato di pianificazione indipendente dagli strumenti e revisionabile, che non vada in conflitto con un tracker di progetto, e un loop di agente autonomo ha bisogno di un posto stabile dove leggere e scrivere lo stato dei piani.

**Motivazione.** La divisione della proprietà dei campi mantiene i due sistemi privi di conflitti — il markdown possiede i contenuti, Linear possiede lo stato di triage — così un push non sovrascrive mai il triage umano. La corsia `dropped/` tiene i piani annullati fuori dalla pipeline di sincronizzazione così che non riappaiano (creata quando Allowed Exceptions Guardrails / LAV-5 è stato respinto). Il frontmatter obsoleto all'interno di un piano è un bug di documentazione, non uno stato; la cartella ha la precedenza, e dove il codice mostra una funzione rilasciata nonostante un frontmatter "Backlog" (ad es. l'eliminazione dell'account), il codice ha la precedenza.

**Stato.** **Adottata** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; corsia `dropped/` in uso).

---

## 11. Suddivisione del repo + open-source copyleft del client {#11-repo-split--copyleft-open-source-of-the-client}

**Decisione.** Suddividere il monorepo in repo per componente (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) e **rendere open-source il client di prima parte sotto AGPL-3.0** al posto di Apache-2.0, sul precedente copyleft di Mullvad/ProtonVPN.

**Contesto.** Sviluppo per componente e apertura del codice del client. La questione della licenza è se un concorrente potrebbe forkare il client, chiuderlo e farci concorrenza sul prezzo.

**Motivazione.** Il copyleft costringe i derivati a restare aperti, impedendo un fork chiuso del client — una postura "client pubblico, backend/ops privati", con backend, ambito legale e operazioni tenuti privati. AGPL-3.0 (anziché la semplice GPL-3.0) è stata scelta per chiudere la lacuna dell'uso in rete. La nota tensione di distribuzione GPL-vs-App-Store è gestita dal fatto che Lava stessa è il distributore del binario dell'App Store sotto il proprio copyright.

**Stato.** **Adottata.** La suddivisione del repo è **completa**: ogni componente vive nel proprio repository — il client pubblico `lavasec-ios` al tag v0.4.0, più repository separati per Android, il sito di marketing, backend/infrastruttura, documenti e la pipeline di CI/release — e la sezione "Repository layout" del `README.md` di `lavasec-ios` elenca solo i contenuti per componente di quel repo (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`) con l'infrastruttura indicata come residente in repository privati separati. Il client è reso open-source sotto **AGPL-3.0**: il `LICENSE` di `lavasec-ios` è la GNU Affero General Public License v3 e il `README.md` riporta il badge AGPL-3.0.

---

## Appendice — altre inversioni e rifiuti registrati {#appendix--other-recorded-reversals-and-rejections}

Queste sono più piccole ma erano decisioni genuine con un'inversione registrata; elencate per completezza.

| Decisione | Motivazione | Stato |
|---|---|---|
| DNS personalizzato free vs paid | Posizionamento di monetizzazione; brevemente consentito sul piano free, poi tornato a solo-paid | **Annullata** a solo-paid |
| Accesso con email/password | Possedere le password aggiunge l'onere di reset/MFA/blocco/violazione/takeover mentre Apple + Google bastano; un recupero di bypass romperebbe la conoscenza zero | **Annullata** / mai rilasciata (solo Apple + Google) |
| Allowed Exceptions Guardrails (LAV-5) | La precedenza dei guardrail è stata rilasciata tramite il più semplice rinnovamento della modifica delle filter-list; il pagamento non deve mai bypassare il guardrail sulle minacce ad alta confidenza | **Annullata** (corsia `dropped/` creata) |
| Blocco della promozione di branch su TestFlight | Il blocco iniziale è stato riconsiderato; sostituito da un blocco del runner pianificato dopo l'apertura del codice | **Annullata**, sostituita da un piano in backlog |
| Canale di controllo app↔estensione | `sendProviderMessage` (`NETunnelProviderSession`) è l'**unico percorso di controllo app→tunnel** — trasporta lo stato tipizzato e versionato e guida in modo autorevole il run loop dell'estensione. Il precedente observer `CFNotificationCenter` lato estensione non si attivava mai in modo affidabile sul dispositivo ed è stato **rimosso** (asserito assente dai test di source-introspection). Le notifiche Darwin sopravvivono solo nella direzione **tunnel→app**, come spinta di health-changed. | **Adottata** (il provider-message è l'unico controllo app→tunnel; Darwin è solo health tunnel→app) |

> Invariante di sicurezza trasversale richiamata in tutto il documento: il pagamento non bypassa mai il **guardrail sulle minacce** non aggirabile e convalidato tramite hash. La precedenza delle decisioni è **guardrail sulle minacce > allowlist locale (eccezioni consentite) > blocklist > default-allow.**
