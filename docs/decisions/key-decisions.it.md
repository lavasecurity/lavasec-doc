---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Decisioni di progettazione chiave

> Pubblico: ingegneri e leadership. Questo è il registro in stile ADR delle decisioni di progettazione portanti dietro Lava Security — quelle che hanno plasmato l'architettura, la promessa sulla privacy o i confini del prodotto, e in particolare quelle che sono state provate e poi annullate. Ogni voce indica la **Decisione**, il suo **Contesto**, la **Motivazione** e uno **Stato** tratto dalla legenda di stato del progetto (Adottata / Annullata / Sostituita / Proposta).
>
> **Il codice ha la meglio.** Quando un piano e il codice effettivamente rilasciato non coincidono, questo registro segue il codice e segnala la divergenza direttamente nel testo.

**Legenda dello stato (mappata sulle corsie di stato del set di documenti):**

| Stato qui | Significato della corsia nel set di documenti |
|---|---|
| **Adottata** | Implementata — rilasciata e confermata nel codice |
| **Annullata** | Abbandonata — realizzata, poi rimossa/annullata |
| **Sostituita** | Una decisione precedente sostituita da una successiva |
| **Proposta** | Pianificata — progettata, raccomandata o registrata, ma non ancora applicata in questo tree |

Letture correlate: il modello di distribuzione del catalogo in [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) e [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); il comportamento effettivamente rilasciato in [`../product/features.md`](../product/features.md). La direzione futura è descritta nella roadmap interna.

---

## 1. Filtraggio DNS sul dispositivo tramite `NEPacketTunnelProvider`

**Decisione.** Filtrare il DNS **localmente sul dispositivo** attraverso un packet tunnel `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), invece di `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` o un content blocker di Safari.

**Contesto.** Il prodotto è un filtro pensato prima di tutto per la privacy, rivolto a persone non tecniche (genitori, persone anziane), distribuito tramite l'App Store consumer e senza bisogno di un account. Gli altri provider NetworkExtension e le API di DNS gestito sono limitati a dispositivi supervisionati/gestiti via MDM oppure non coprono tutto il DNS di un'app, e un modello lato resolver instraderebbe il flusso dei domini dell'utente fuori dal dispositivo.

**Motivazione.** Il packet tunnel è l'unico provider che (a) funziona su dispositivi consumer non gestiti e (b) consente a ogni decisione DNS di avvenire sul dispositivo, che è il fondamento della promessa sulla privacy: *tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i propri server e non riceve mai il flusso dei domini che visiti.* Il compromesso accettato in cambio è il **limite di memoria di ~50 MiB per estensione** di iOS, sotto il quale il tunnel deve restare — un vincolo che plasma diverse decisioni successive descritte più avanti.

**Stato.** **Adottata** (fondamentale; presente nel codice fin dal primo prototipo).

---

## 2. Distribuzione delle blocklist solo tramite source-url

**Decisione.** Lava pubblica solo l'**URL della blocklist a monte e gli hash accettati**; il dispositivo scarica i **byte** della lista direttamente da ciascun `source_url`, quindi li analizza, normalizza, deduplica e filtra localmente. Lava **non** memorizza, replica, trasforma o serve mai i byte delle blocklist di terze parti. Il Worker scrive su R2 solo i **metadati** JSON del catalogo (`raw_r2_key`/`normalized_r2_key` sono null).

**Contesto.** Il progetto precedente replicava i byte grezzi delle blocklist su R2 affinché i legali potessero esaminare la distribuzione. Molte liste a monte (HaGeZi, OISD) sono GPL-3.0, quindi ospitarne i byte renderebbe Lava un ridistributore di dati GPL.

**Motivazione.** Trattare Lava come un motore di filtraggio locale / user agent — anziché come un distributore di blocklist — riduce al minimo l'esposizione legata alla ridistribuzione GPLv3 e all'App Review. Il dispositivo verifica i byte scaricati rispetto agli `accepted_source_hashes` del catalogo e, in caso di mancata corrispondenza, ricade sull'ultima cache valida oppure si chiude in sicurezza, recuperando la proprietà di sicurezza che la pipeline di mirror aveva fornito. Ogni set di regole analizzato passa anche attraverso un filtro di domini protetti, così che una lista a monte non possa bloccare i domini di Lava/Apple/provider di identità. Il modello è verificato in CI da `check-gpl-blocklist-distribution.sh` (nessun codice di mirror, nessun URL di artefatti ospitati da Lava, nessuna sorgente GPL abilitata per impostazione predefinita, nessuna scrittura di byte su R2).

**Stato.** **Adottata**, e ha **Sostituito** l'abbandonato piano di mirror grezzo su R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, intestazione "Superseded by the source-url-only implementation"). Vedi [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Trasporti resolver cifrati (DoH / DoH3 / DoT / DoQ)

**Decisione.** Rilasciare quattro trasporti a monte cifrati accanto al DNS in chiaro e a un fallback sul DNS del dispositivo, estratti in LavaSecCore: **DoH** (URLSession), **DoH3** (DoH che preferisce HTTP/3), **DoT** (`NWConnection` in pool, fino a 4 per endpoint, con aggiornamento per inattività e un nuovo tentativo su connessione fresca) e **DoQ** (DNS-over-QUIC). Il routing, il degrado verso il DNS in chiaro, il failover per endpoint con un gate di backoff e il fallback sul DNS del dispositivo vivono in `ResolverOrchestrator`.

**Contesto.** Inoltrare in chiaro a un resolver le query non bloccate rivela proprio quel flusso di domini che il modello sul dispositivo è pensato per proteggere. I trasporti sono stati costruiti in modo incrementale (DoH → DoH3 → DoT → DoQ).

**Motivazione.** Il trasporto a monte cifrato mantiene private le query non bloccate da un capo all'altro. **DoH3** è etichettato in modo puramente osservativo — `assumesHTTP3Capable=true` è impostato e il protocollo negoziato viene osservato, e l'interfaccia annota `DoH3` (senza barra) **solo quando una negoziazione h3 viene effettivamente osservata**, mai promessa, perché h3 è best-effort per ogni connessione e un'affermazione fissa sovrastimerebbe il comportamento dietro firewall che bloccano l'UDP. Il pool DoT con aggiornamento per inattività è stato una correzione diretta al fatto che Cloudflare chiudeva silenziosamente le connessioni DoT inattive.

**Stato.** **Adottata** (tutti e quattro i trasporti presenti e collegati).

---

## 4. Riutilizzo della connessione DoQ — realizzato, testato su dispositivo, annullato

**Decisione.** **Non** riutilizzare le connessioni QUIC per DoQ. `DoQTransport` apre una **nuova connessione QUIC per ogni query**; il pool a 4 corsie fornisce concorrenza, non riutilizzo dell'handshake.

**Contesto.** L'RFC 9250 mappa ciascuna query DNS sul proprio stream QUIC, quindi un vero riutilizzo richiede l'API multi-stream `NWConnectionGroup`/`openStream`, disponibile **solo da iOS 26.0+**, mentre il limite minimo di distribuzione è iOS 17. È stato comunque implementato un percorso di riutilizzo limitato a iOS 26 (compilato in Debug+Release con l'SDK di Xcode 26) e **testato su dispositivo con iOS 26.5** contro AdGuard DoQ.

**Motivazione.** Il percorso di riutilizzo ha fallito a ogni tentativo sul dispositivo (`openStream`/`receive` davano errore, poi il fallback incappava in "Socket is not connected"), risultando **nettamente peggiore** della baseline per-query (controllo: 34 handshake / 35 query, tutte riuscite). Questo ha confermato empiricamente l'indicazione di Apple DTS di "soprassedere sull'uso di QUIC con il nuovo framework Network", quindi il lavoro è stato annullato anziché rilasciato; solo la documentazione e la motivazione del guard-test conservano la scoperta, così da non riprovarci prima che l'API maturi.

**Stato.** **Annullata** (rinviata finché il limite minimo di distribuzione non raggiunge iOS 26). Descrivere DoQ come connessioni fresche per ogni query.

---

## 5. Rifiuto di un protocollo unificante `DNSResolvingTransport`

**Decisione.** **Non** unificare i trasporti resolver sotto un unico protocollo `DNSResolvingTransport`; mantenere il seam basato su closure `ResolverOrchestrator.Executors`.

**Contesto.** Un refactor (issue 407) proponeva un unico protocollo per tutti i trasporti.

**Motivazione.** I trasporti sono troppo dissimili — executor cifrati asincroni (DoH/DoT/DoQ) rispetto a trasporti sincroni multi-indirizzo in chiaro/del dispositivo — quindi un protocollo unificante sarebbe un'astrazione peggiore del seam a closure iniettabile già esistente, che mantiene già testabile l'esecuzione sul filo.

**Stato.** **Annullata** / non si implementerà (chiusa come cattiva astrazione).

---

## 6. Backup cifrato a conoscenza zero (senza password, con eccezione passkey segnalata)

**Decisione.** Eseguire il backup di un payload di impostazioni **minimizzato** lato client: AES-256-GCM lo sigilla con una chiave di payload casuale da 32 byte, che viene avvolta in **key slot** per ciascun segreto tramite PBKDF2-HMAC-SHA256 (**210.000** iterazioni in produzione). Sulla tabella Supabase `user_backups` (RLS per utente) vengono caricati solo il testo cifrato e i metadati non segreti. Il flusso effettivamente rilasciato è **senza password**: slot del segreto del dispositivo (Keychain locale del dispositivo) + slot di recupero assistito + slot passkey opzionale.

**Contesto.** L'accesso facoltativo con account (solo Apple + Google) consente il ripristino delle impostazioni tra dispositivi. Il server non deve mai poter leggere le blocklist, le allowlist, la scelta del resolver o le altre impostazioni di un utente.

**Motivazione.** Il testo in chiaro e la decifratura dei segreti esistono solo sul dispositivo; il server detiene una sola busta opaca per utente. Il recupero assistito è deliberatamente a due fattori — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (input delimitato da NUL) richiede **sia** la parte detenuta dal server **sia** la frase di recupero di 8 parole dell'utente (~105 bit), così che nessuna delle due metà da sola permetta la decifratura. Il materiale di sblocco è memorizzato in locale sul dispositivo (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **non** nel Keychain iCloud sincronizzabile — un irrobustimento della privacy che ha invertito il progetto sincronizzabile originale. Anche lo **slot passkey è davvero a conoscenza zero**: è avvolto con un output dell'autenticatore WebAuthn **PRF / `hmac-secret`** (derivato via HKDF-SHA256) che non lascia mai il client, così che nessun valore detenuto dal server possa svolgerlo. Non esiste alcuna tabella passkey con ruolo di servizio né alcun gate di asserzione WebAuthn nel Worker — il precedente progetto con passkey gestita dal server è stato abbandonato, rimuovendo tutto lo stato passkey lato server (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Stato.** **Adottata** (modello senza password, recupero assistito e slot passkey a conoscenza zero derivato via PRF, tutti nel codice). Rendere la passkey un fattore di recupero pienamente pronto per la produzione su dispositivi fisici (Associated Domains / hosting AASA per il modello PRF) è **Proposta** (backlog).

---

## 7. Connect-On-Demand a chiusura sicura

**Decisione.** Aggiungere una regola `NEOnDemandRuleConnect` così che un tunnel fermato dal sistema operativo si riavvii automaticamente, con la **chiusura sicura** come impostazione predefinita: quando non c'è uno snapshot di filtro riutilizzabile, il tunnel blocca tutto il traffico anziché lasciarlo passare non filtrato. L'on-demand viene **disattivato prima di ogni arresto** così che la VPN resti spegnibile.

**Contesto.** iOS fermava silenziosamente il tunnel (motivo 17) senza che nulla lo riavviasse per ~45 minuti, lasciando gli utenti senza protezione. Abilitare ingenuamente l'on-demand rende impossibile spegnere la VPN, e un'impostazione a chiusura aperta lascerebbe passare il traffico durante l'intervallo.

**Motivazione.** L'on-demand colma l'intervallo di arresto silenzioso; la disattivazione-prima-dell'arresto preserva la possibilità dell'utente di spegnere la protezione; la chiusura sicura garantisce che l'intervallo sia sicuro anziché silenziosamente non filtrato, recuperato da `reconcileTunnelSnapshotAfterLaunch`. La modifica ha avuto effetti collaterali — l'on-demand riattivava il prompt di sistema "Add VPN Configurations" durante l'onboarding — che hanno generato una catena di correzioni su più commit: smettere di abilitare l'on-demand all'installazione, condizionare il ripristino dell'avvio/della protezione al completamento dell'onboarding e **neutralizzare una configurazione ereditata/orfana rimuovendola** (`removeFromPreferences`, in modo silenzioso) anziché salvando `on-demand=false` (`saveToPreferences` rimostrava il prompt).

**Stato.** **Adottata** (riavvio on-demand più la catena di correzioni onboarding/chiusura sicura).

---

## 8. Refactor modulare della VPN e la disciplina della regressione di calore

**Decisione.** Ristrutturare il percorso VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) per un'attivazione cache-first, un recupero parallelo limitato e la coalescenza dei flap — trattando batteria/latenza come requisiti di prodotto con obiettivi p50/p95 espliciti e profilazione **sul dispositivo** (non sul Simulator).

**Contesto.** Attivazione / aggiornamento / pausa / ripresa erano lenti. Durante il refactor è comparsa una regressione di calore (134% CPU, energia elevata, telefono caldo). Un grande pannello di agenti ha dapprima smentito la causa sospettata usando prove pre-regressione; una cattura dal vivo sul dispositivo l'ha poi confermata.

**Motivazione.** La vera causa era un loop di aggiornamento `NEVPNStatusDidChange` auto-sostenuto — un loop di coalescenza che si riarmava all'infinito (~370 eventi/s, thread principale ~100%, `vpn-debug-log.jsonl` cresciuto fino a ~180–210 MB) dopo la sostituzione di una guardia drop-reentrant. La correzione legge lo stato del manager dalla cache e limita il loop. Gli stessi artefatti prima/dopo del piano sul dispositivo registrano l'attivazione a caldo (`action.turnOn`) scendere da **2.722 ms → 287 ms** su iPhone 15 Pro; una successiva e separata revisione delle opportunità post-modulare ha misurato il percorso a caldo a **112 ms** (decode 51 + managerSetup 57) sullo stesso dispositivo. L'episodio ha fissato lo standard: i refactor strutturali si fermano finché una regressione di calore misurata non è contenuta, e i risultati termici/di batteria del Simulator sono respinti come privi di significato.

**Stato.** **Adottata** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Una revisione post-modulare mantiene `PacketTunnelProvider` e `AppViewModel` come noti god-object ancora presenti.

---

## 9. Budget di regole di filtro invece di un limite sul numero di liste

**Decisione.** Differenziare i tier in base a un **budget di regole di filtro** — **Free 500K / Plus 2M** regole di dominio compilate — non in base al numero di liste abilitate. Un rigido **guardrail del dispositivo di ~3,26M di regole** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3.262.236`) si applica a **tutti** e **non è mai un paywall**. Il blob di domini compatto è mappato con `mmap` (`.mappedIfSafe`) così da restare file-backed e fuori dal `phys_footprint` conteggiato da jetsam; solo le tabelle di voci decodificate costano memoria residente.

**Contesto.** Il vecchio limite era sul **numero** di liste (3 in free / 10 a pagamento). Una lista può contenere 1K o 1M di regole, quindi il numero era un indicatore poco onesto della risorsa realmente vincolata — il limite di memoria di 50 MiB della NE.

**Motivazione.** Le regole corrispondono alla memoria effettiva, quindi è ammessa qualsiasi combinazione di liste che ci stia. L'applicazione autorevole avviene in fase di compilazione sull'unione deduplicata in `FilterSnapshotPreparationService` (prima il guardrail del dispositivo, poi il limite del tier); il misuratore dell'interfaccia in fase di selezione usa una somma per lista con un margine soft di 1,10. Le configurazioni fuori budget vengono rifiutate in modo deterministico (mantenendo la protezione spenta) anziché lasciare che il tunnel finisca in jetsam.

**Stato.** **Adottata** nel codice (`SubscriptionPolicy.swift`), che ha **Sostituito** il limite sul numero di liste. Il piano che la guida (`plans/under_review/2026-06-13-filter-rules-budget-tier-revamp.md`) è ancora in revisione e il testo del sito pubblico "Blocklist abilitate 3 → 10" è **obsoleto** — la vera differenziazione è il budget di regole. Vedi [`../product/features.md`](../product/features.md).

---

## 10. Piani come markdown + sincronizzazione a senso unico verso Linear

**Decisione.** I file markdown in `plans/<lane>/` sono la **fonte di verità**; la **cartella della corsia è lo stato autorevole** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Un push su `main` sincronizza i piani **a senso unico** verso Linear (team LAV), aggiornando solo titolo/descrizione dopo la creazione; un percorso di ritorno separato, **manuale e revisionato**, riporta stato/priorità/corsia da Linear nel frontmatter del piano.

**Contesto.** Un piccolo team ha bisogno di uno stato di pianificazione indipendente dagli strumenti e revisionabile, che non entri in conflitto con un tracker di progetto, e un loop di agenti autonomo ha bisogno di un posto stabile dove leggere e scrivere lo stato del piano.

**Motivazione.** La suddivisione della proprietà dei campi mantiene i due sistemi senza conflitti — il markdown possiede il contenuto, Linear possiede lo stato di triage — così un push non sovrascrive mai il triage umano. La corsia `dropped/` tiene i piani annullati fuori dalla pipeline di sincronizzazione così che non riappaiano (creata quando Allowed Exceptions Guardrails / LAV-5 è stata respinta). Un frontmatter obsoleto all'interno di un piano è un bug del documento, non uno stato; la cartella ha la meglio, e dove il codice mostra una funzione rilasciata nonostante un frontmatter "Backlog" (ad es. l'eliminazione dell'account), il codice ha la meglio.

**Stato.** **Adottata** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; corsia `dropped/` in uso).

---

## 11. Suddivisione del repo + open-source copyleft del client

**Decisione.** Suddividere il monorepo in repo per componente (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) e **rilasciare il client first-party come open-source sotto AGPL-3.0** al posto di Apache-2.0, sul precedente copyleft di Mullvad/ProtonVPN.

**Contesto.** Sviluppo per componente e apertura del client come open-source. La questione della licenza è se un concorrente possa fare un fork del client, chiuderlo e venderlo a un prezzo più basso.

**Motivazione.** Il copyleft costringe i derivati a restare aperti, impedendo un fork chiuso del client — una postura "client pubblico, backend/operazioni privati", con backend, aspetti legali e operazioni tenuti privati. AGPL-3.0 (anziché la semplice GPL-3.0) è stata scelta per chiudere la lacuna dell'uso in rete. La nota tensione di distribuzione tra GPL e App Store è gestita dal fatto che Lava stessa è il distributore del binario dell'App Store sotto il proprio copyright.

**Stato.** **Adottata.** La suddivisione del repo è **completata**: ogni componente vive nel proprio repository — il client pubblico `lavasec-ios` al tag v0.4.0, più repository separati per Android, il sito di marketing, backend/infrastruttura, documenti e la pipeline di CI/release — e la sezione "Repository layout" del `README.md` di `lavasec-ios` elenca solo i contenuti per componente di quel repo (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`), con l'infrastruttura indicata come residente in repository privati separati. Il client è rilasciato come open-source sotto **AGPL-3.0**: la `LICENSE` di `lavasec-ios` è la GNU Affero General Public License v3 e il `README.md` riporta il badge AGPL-3.0.

---

## Appendice — altre inversioni e rifiuti registrati

Sono più piccoli, ma erano decisioni vere e proprie con un cambio di rotta registrato; elencati per completezza.

| Decisione | Motivazione | Stato |
|---|---|---|
| DNS personalizzato gratuito vs a pagamento | Posizionamento di monetizzazione; brevemente concesso nel piano gratuito, poi tornato a solo a pagamento | **Annullata**, tornata a solo a pagamento |
| Accesso con email/password | Gestire le password aggiunge oneri di reset/MFA/blocco/violazione/furto d'identità mentre Apple + Google bastano; un recupero che le aggira romperebbe la conoscenza zero | **Annullata** / mai rilasciata (solo Apple + Google) |
| Allowed Exceptions Guardrails (LAV-5) | La precedenza dei guardrail è arrivata tramite il più semplice rinnovamento della modifica delle liste di filtro; il pagamento non deve mai aggirare il guardrail sulle minacce ad alta affidabilità | **Annullata** (creata la corsia `dropped/`) |
| Lockdown della promozione di branch su TestFlight | Il lockdown iniziale è stato riconsiderato; sostituito da un lockdown del runner pianificato dopo l'apertura open-source | **Annullata**, sostituita da un piano in backlog |
| Canale di controllo app↔estensione | `sendProviderMessage` (`NETunnelProviderSession`) è l'**unico percorso di controllo app→tunnel** — trasporta lo stato tipizzato e versionato e guida in modo autorevole il run loop dell'estensione. Il precedente observer `CFNotificationCenter` lato estensione non scattava mai in modo affidabile sul dispositivo ed è stato **rimosso** (assenza confermata dai test di introspezione del sorgente). Le notifiche Darwin sopravvivono solo nella direzione **tunnel→app**, come un avviso di cambiamento dello stato di salute. | **Adottata** (il messaggio del provider è l'unico controllo app→tunnel; Darwin è solo salute tunnel→app) |

> Invariante di sicurezza trasversale richiamato in tutto il documento: il pagamento non aggira mai il **guardrail sulle minacce** validato tramite hash e non escludibile. La precedenza delle decisioni è **guardrail sulle minacce > allowlist locale (eccezioni consentite) > blocklist > consenti per impostazione predefinita.**
