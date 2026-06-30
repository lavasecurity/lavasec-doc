---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Decisioni di progettazione chiave

> Destinatari: ingegneri e leadership. Questo è il registro in stile ADR delle decisioni di progettazione portanti dietro Lava Security — quelle che hanno plasmato l'architettura, la promessa sulla privacy o il confine del prodotto, e in particolare quelle che sono state tentate e poi annullate. Ogni voce riporta la **Decisione**, il suo **Contesto**, la **Motivazione** e uno **Stato** tratto dalla legenda di stato del progetto (Adottata / Annullata / Sostituita / Proposta).
>
> **Il codice prevale.** Dove un piano e il codice rilasciato sono in disaccordo, questo registro segue il codice e segnala la divergenza inline.

**Legenda di stato (mappata alle corsie di stato del doc-set):**

| Stato qui | Significato della corsia del doc-set |
|---|---|
| **Adottata** | Implementata — rilasciata e confermata nel codice |
| **Annullata** | Abbandonata — costruita, poi rimossa/annullata |
| **Sostituita** | Una decisione precedente sostituita da una successiva |
| **Proposta** | Pianificata — progettata, raccomandata o registrata, ma non ancora applicata in questo albero |

Letture correlate: il modello di distribuzione del catalogo in [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) e [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); il comportamento rilasciato in [`../product/features.md`](../product/features.md). La direzione prospettica risiede nella roadmap interna.

---

## 1. Filtraggio DNS on-device tramite `NEPacketTunnelProvider`

**Decisione.** Filtrare il DNS **localmente sul dispositivo** attraverso un packet tunnel `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), anziché `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` o un content blocker di Safari.

**Contesto.** Il prodotto è un filtro privacy-first per utenti non tecnici (genitori, persone anziane) distribuito tramite l'App Store consumer, senza account. I provider NetworkExtension concorrenti e le API DNS gestite sono limitati a dispositivi supervisionati/gestiti via MDM o non coprono tutto il DNS di un'app, e un modello lato resolver instraderebbe il flusso di domini dell'utente fuori dal dispositivo.

**Motivazione.** Il packet tunnel è l'unico provider che (a) funziona per dispositivi consumer non gestiti e (b) consente a ogni decisione DNS di avvenire on-device, che è il fondamento della promessa sulla privacy: *tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i propri server e non riceve mai il flusso di domini che visiti.* Il compromesso accettato è il **tetto di memoria iOS di ~50 MiB per estensione** sotto cui il tunnel deve operare — un vincolo che plasma diverse decisioni successive qui sotto.

**Stato.** **Adottata** (fondamentale; presente nel codice fin dal prototipo iniziale).

---

## 2. Distribuzione della blocklist solo tramite source-url

**Decisione.** Lava pubblica solo l'**URL della blocklist upstream più gli hash accettati**; il dispositivo recupera i **byte** della lista direttamente da ciascun `source_url`, poi li analizza, normalizza, deduplica e filtra localmente. Lava **non** memorizza, replica, trasforma o serve mai i byte di blocklist di terze parti. Il Worker scrive su R2 solo i **metadati** del catalogo in JSON (`raw_r2_key`/`normalized_r2_key` sono null).

**Contesto.** Il design precedente replicava i byte grezzi della blocklist su R2 affinché i legali potessero rivedere la distribuzione. Molte liste upstream (HaGeZi, OISD) sono GPL-3.0, quindi ospitarne i byte renderebbe Lava un ridistributore di dati GPL.

**Motivazione.** Trattare Lava come un motore di filtraggio locale / user agent — anziché come un distributore di blocklist — minimizza la ridistribuzione GPLv3 e l'esposizione in fase di App Review. Il dispositivo recupera ciascuna lista via TLS direttamente dal suo `source_url` curato e la analizza localmente sotto rigorosi limiti di dimensione/regole; le liste della community sono accettate così come servite (gli `accepted_source_hashes` del catalogo sono indicativi, non un cancello rigido — un singolo hash fissato non può seguire un upstream a rotazione rapida e produceva solo falsi rifiuti), mentre il tier threat-guardrail di Lava rimane vincolato all'hash. La provenienza è imposta a livello di catalogo (una modifica di `source_url` deve usare un nuovo `list_id`), non da un cancello hash lato client. Ogni set di regole analizzato passa anche attraverso un filtro di domini protetti affinché una lista upstream non possa bloccare i domini di Lava/Apple/del provider di identità. Il modello è imposto in CI da `check-gpl-blocklist-distribution.sh` (nessun codice di mirror, nessun URL di artefatto ospitato da Lava, nessuna sorgente GPL abilitata di default, nessuna scrittura di byte su R2).

**Stato.** **Adottata**, e ha **Sostituito** il piano abbandonato di mirror grezzo su R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, intestazione "Superseded by the source-url-only implementation"). Vedi [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Trasporti resolver cifrati (DoH / DoH3 / DoT / DoQ)

**Decisione.** Rilasciare quattro trasporti upstream cifrati accanto al DNS in chiaro e a un fallback al DNS del dispositivo, estratti in LavaSecCore: **DoH** (URLSession), **DoH3** (DoH che predilige HTTP/3), **DoT** (`NWConnection` in pool, fino a 4 per endpoint, con refresh per staleness da inattività e un retry su connessione fresca) e **DoQ** (DNS-over-QUIC). Il routing, il degrado al DNS in chiaro, il failover per endpoint con un cancello di backoff e il fallback al DNS del dispositivo risiedono in `ResolverOrchestrator`.

**Contesto.** Inoltrare query non bloccate in chiaro a un resolver fa trapelare proprio il flusso di domini che il modello on-device dovrebbe proteggere. I trasporti sono stati costruiti in modo incrementale (DoH → DoH3 → DoT → DoQ).

**Motivazione.** Il trasporto upstream cifrato mantiene le query non bloccate private end-to-end. **DoH3** è etichettato in modo puramente osservativo — `assumesHTTP3Capable=true` è impostato e il protocollo negoziato viene osservato, e l'interfaccia annota `DoH3` (senza slash) **solo quando una negoziazione h3 è effettivamente osservata**, mai promessa, perché h3 è best-effort per connessione e una rivendicazione fissa sovrastimerebbe il comportamento dietro firewall che bloccano UDP. Il pooling DoT con refresh per inattività è stato una correzione diretta per il fatto che Cloudflare chiudeva silenziosamente le connessioni DoT inattive.

**Stato.** **Adottata** (tutti e quattro i trasporti presenti e collegati).

---

## 4. Riuso della connessione DoQ — costruito, testato su dispositivo, annullato

**Decisione.** **Non** riusare le connessioni QUIC per DoQ. `DoQTransport` apre una **connessione QUIC fresca per ogni query**; il pool a 4 corsie fornisce concorrenza, non riuso dell'handshake.

**Contesto.** RFC 9250 mappa ogni query DNS sul proprio stream QUIC, quindi un vero riuso richiede l'API multi-stream `NWConnectionGroup`/`openStream` che è **solo iOS 26.0+**, mentre il floor di deployment è iOS 17. Un percorso di riuso vincolato a iOS 26 è stato comunque implementato (compilato Debug+Release contro l'SDK Xcode 26) e **testato su dispositivo su iOS 26.5** contro DoQ di AdGuard.

**Motivazione.** Il percorso di riuso ha fallito a ogni tentativo su dispositivo (`openStream`/`receive` davano errore, poi il fallback colpiva "Socket is not connected"), misurando **nettamente peggio** rispetto alla baseline per-query (controllo: 34 handshake / 35 query, tutte riuscite). Questo ha confermato empiricamente la guida di Apple DTS "hold off on QUIC with the new Network framework", quindi il lavoro è stato annullato anziché rilasciato; solo la documentazione e la motivazione del guard-test conservano il risultato affinché non venga ritentato prima che l'API maturi.

**Stato.** **Annullata** (rinviata finché il floor di deployment non raggiunge iOS 26). Descrivere DoQ come connessioni fresche per ogni query.

---

## 5. Rifiuto di un protocollo unificante `DNSResolvingTransport`

**Decisione.** **Non** unificare i trasporti del resolver sotto un unico protocollo `DNSResolvingTransport`; mantenere il seam basato su closure `ResolverOrchestrator.Executors`.

**Contesto.** Un refactor (issue 407) proponeva un unico protocollo su tutti i trasporti.

**Motivazione.** I trasporti sono troppo dissimili — executor cifrati asincroni (DoH/DoT/DoQ) contro trasporti sincroni multi-indirizzo in chiaro/del dispositivo — quindi un protocollo unificante sarebbe un'astrazione peggiore rispetto al seam a closure iniettabile esistente, che già mantiene testabile l'esecuzione sul filo.

**Stato.** **Annullata** / won't-implement (chiusa come astrazione sbagliata).

---

## 6. Backup cifrato a conoscenza zero (senza password, con eccezione passkey annotata)

**Decisione.** Eseguire il backup di un payload di impostazioni **minimizzato** lato client: AES-256-GCM lo sigilla sotto una chiave di payload casuale di 32 byte, che viene incapsulata in **key slot** per-segreto tramite PBKDF2-HMAC-SHA256 (**210.000** iterazioni in produzione). Solo il ciphertext più metadati non segreti vengono caricati nella tabella Supabase `user_backups` (RLS per utente). Il flusso rilasciato è **senza password**: slot device-secret (Keychain locale del dispositivo) + slot assisted-recovery + slot passkey opzionale.

**Contesto.** Il login con account opzionale (solo Apple + Google) abilita il ripristino delle impostazioni cross-device. Il server non deve mai poter leggere le blocklist, le allowlist, la scelta del resolver o altre impostazioni di un utente.

**Motivazione.** Il testo in chiaro e i segreti decifranti esistono solo sul dispositivo; il server detiene una sola busta opaca per utente. L'assisted recovery è deliberatamente a due fattori — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (input delimitato da NUL) richiede **sia** la share detenuta dal server **sia** la frase di recupero di 8 parole dell'utente (~105 bit), quindi nessuna metà da sola decifra. Il materiale di sblocco è memorizzato in locale sul dispositivo (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **non** nel Keychain iCloud sincronizzabile — un irrobustimento della privacy che ha invertito il design sincronizzabile del piano originale. Anche lo **slot passkey è genuinamente a conoscenza zero**: è incapsulato con un output dell'authenticator WebAuthn **PRF / `hmac-secret`** (derivato HKDF-SHA256) che non lascia mai il client, quindi nessun valore detenuto dal server può scartarlo. Non c'è alcuna tabella passkey con service-role né alcun cancello di asserzione WebAuthn nel Worker — il precedente design passkey con gate lato server è stato abbandonato, rimuovendo tutto lo stato passkey lato server (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Stato.** **Adottata** (modello senza password, assisted recovery e uno slot passkey a conoscenza zero derivato da PRF, tutto nel codice). Rendere la passkey un fattore recuperabile pienamente pronto per la produzione su dispositivi fisici (hosting Associated Domains / AASA per il modello PRF) è **Proposta** (backlog).

---

## 7. Connect-On-Demand fail-closed

**Decisione.** Aggiungere una regola `NEOnDemandRuleConnect` affinché un tunnel arrestato dall'OS si riavvii automaticamente, con **fail-closed** come default sicuro: quando non c'è uno snapshot del filtro riutilizzabile, il tunnel blocca tutto il traffico anziché farlo passare non filtrato. On-demand viene **disabilitato prima di qualsiasi arresto** affinché la VPN resti disattivabile.

**Contesto.** iOS arrestava silenziosamente il tunnel (reason 17) senza che nulla lo riavviasse per ~45 minuti, lasciando gli utenti senza protezione. Abilitare on-demand in modo ingenuo rende la VPN impossibile da spegnere, e un default fail-open farebbe passare il traffico durante il vuoto.

**Motivazione.** On-demand chiude il vuoto dell'arresto silenzioso; disabilitare-prima-dell'arresto preserva la capacità dell'utente di spegnere la protezione; fail-closed garantisce che il vuoto sia sicuro anziché silenziosamente non filtrato, recuperato da `reconcileTunnelSnapshotAfterLaunch`. La modifica ha avuto effetti collaterali — on-demand ri-attivava il prompt di sistema "Add VPN Configurations" durante l'onboarding — il che ha generato una catena di fix multi-commit: smettere di abilitare on-demand all'installazione, vincolare il ripristino di launch/protection al completamento dell'onboarding e **neutralizzare una config ereditata/orfana rimuovendola** (`removeFromPreferences`, silente) anziché salvando `on-demand=false` (`saveToPreferences` rimostrava il prompt).

**Stato.** **Adottata** (riavvio on-demand più la catena di fix onboarding/fail-closed).

---

## 8. Refactor VPN modulare e la disciplina della heat-regression

**Decisione.** Ristrutturare il percorso VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) per accensione cache-first, fetch a parallelismo limitato e coalescenza dei flap — trattando batteria/latenza come requisiti di prodotto con target espliciti p50/p95 e profilazione **on-device** (non su Simulator).

**Contesto.** Accensione / refresh / pausa / ripresa erano lenti. Durante il refactor è comparsa una heat regression (134% CPU, energia Alta, telefono caldo). Un grande pannello di agenti ha dapprima confutato la causa sospettata usando evidenze pre-regressione; una cattura dal vivo su dispositivo l'ha poi confermata.

**Motivazione.** La causa reale era un loop di refresh `NEVPNStatusDidChange` auto-sostenuto — un loop di coalescenza che si ri-armava all'infinito (~370 eventi/s, main thread ~100%, `vpn-debug-log.jsonl` cresciuto a ~180–210 MB) dopo che una guardia drop-reentrant era stata sostituita. La correzione legge lo stato del manager dalla cache e limita il loop. Gli artefatti before/after su dispositivo del piano stesso registrano l'accensione a caldo (`action.turnOn`) calare da **2.722 ms → 287 ms** su iPhone 15 Pro; una separata e successiva review di opportunità post-modulare ha misurato il percorso a caldo a **112 ms** (decode 51 + managerSetup 57) sullo stesso dispositivo. L'episodio ha fissato lo standard: i refactor strutturali si fermano finché una heat regression misurata non è circoscritta, e i risultati termici/batteria del Simulator sono respinti come privi di significato.

**Stato.** **Adottata** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Una review post-modulare mantiene `PacketTunnelProvider` e `AppViewModel` come noti god-object sopravvissuti.

---

## 9. Budget di regole-di-filtro anziché un cap sul conteggio delle liste

**Decisione.** Vincolare i tier con un **budget di regole-di-filtro** — **Free 500K / Plus 2M** regole di dominio compilate — non con il conteggio delle liste abilitate. Un **guardrail di dispositivo rigido di ~3,26M regole** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`) si applica a **tutti** e **non è mai un paywall**. Il blob di dominio compatto è `mmap`'d (`.mappedIfSafe`) così resta file-backed e fuori dal `phys_footprint` conteggiato da jetsam; solo le tabelle di voci decodificate costano memoria residente.

**Contesto.** Il vecchio cap era un **conteggio** di liste (free 3 / paid 10). Una lista può contenere 1K o 1M regole, quindi il conteggio era un proxy disonesto della vera risorsa vincolata — il tetto di memoria NE di 50 MiB.

**Motivazione.** Le regole mappano sulla memoria reale, quindi qualsiasi combinazione di liste che entra è consentita. L'imposizione autoritativa gira a compile time sull'unione deduplicata in `FilterSnapshotPreparationService` (prima il guardrail di dispositivo, poi il limite di tier); il misuratore UI in fase di selezione usa una somma per-lista con un margine soft-ceiling di 1,10. Le config oltre budget vengono rifiutate in modo deterministico (mantenendo la protezione spenta) anziché lasciare che il tunnel finisca in jetsam.

**Stato.** **Adottata** nel codice (`SubscriptionPolicy.swift`), rilasciata in **v1.0.0**, che ha **Sostituito** il cap sul conteggio delle liste. Il budget di regole è ora il gate di tier attivo; anche i cap per-dominio sono stati alzati in 1.0 (Free 25 / Plus 1.000 domini consentiti e bloccati). Vedi [`../product/features.md`](../product/features.md).

---

## 10. Piani come markdown + sync unidirezionale verso Linear

**Decisione.** I file markdown in `plans/<lane>/` sono la **fonte di verità**; la **cartella di corsia è lo stato autoritativo** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Un push su `main` sincronizza i piani **unidirezionalmente** verso Linear (team LAV), aggiornando solo titolo/descrizione dopo la creazione; una **return-leg manuale e revisionata** separata riporta stato/priorità/corsia di Linear nel frontmatter del piano.

**Contesto.** Un piccolo team ha bisogno di uno stato di pianificazione tool-agnostico e revisionabile che non si scontri con un project tracker, e un loop di agenti autonomo ha bisogno di un posto stabile dove leggere e scrivere lo stato dei piani.

**Motivazione.** La separazione di proprietà-dei-campi mantiene i due sistemi privi di conflitti — il markdown possiede il contenuto, Linear possiede lo stato di triage — così un push non sovrascrive mai il triage umano. La corsia `dropped/` tiene i piani annullati fuori dalla pipeline di sync affinché non ricompaiano (creata quando Allowed Exceptions Guardrails / LAV-5 è stato rifiutato). Un frontmatter obsoleto dentro un piano è un bug di documentazione, non uno stato; la cartella prevale, e dove il codice mostra una funzionalità rilasciata nonostante un frontmatter "Backlog" (es. l'eliminazione dell'account), il codice prevale.

**Stato.** **Adottata** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; corsia `dropped/` in uso).

---

## 11. Split del repo + open-source copyleft del client

**Decisione.** Suddividere il monorepo in repo per-componente (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) e **rendere open-source il client first-party sotto AGPL-3.0** al posto di Apache-2.0, sul precedente copyleft di Mullvad/ProtonVPN.

**Contesto.** Sviluppo per-componente e un'apertura del codice del client. La questione della licenza è se un concorrente potrebbe forkare il client, chiuderlo e fare concorrenza sul prezzo.

**Motivazione.** Il copyleft costringe i derivati a restare aperti, prevenendo un fork chiuso del client — una postura "client pubblico, backend/ops privati", con backend, legale e ops tenuti privati. AGPL-3.0 (anziché la semplice GPL-3.0) è stata scelta per chiudere il network-use gap. La nota tensione tra GPL e la distribuzione su App Store è gestita dal fatto che Lava stessa è il distributore del binario dell'App Store sotto il proprio copyright.

**Stato.** **Adottata.** Lo split del repo è **completo**: ogni componente risiede nel proprio repository — il client pubblico `lavasec-ios` al tag v0.4.0, più repository separati per Android, il sito di marketing, backend/infrastruttura, documentazione e la pipeline CI/release — e la sezione "Repository layout" del `README.md` di `lavasec-ios` elenca solo i contenuti per-componente di quel repo (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`) con l'infrastruttura annotata come residente in repository privati separati. Il client è reso open-source sotto **AGPL-3.0**: il `LICENSE` di `lavasec-ios` è la GNU Affero General Public License v3 e il `README.md` riporta il badge AGPL-3.0.

---

## Appendice — altre inversioni e rifiuti registrati

Sono decisioni minori, ma ciascuna ha avuto un'inversione registrata.

| Decisione | Motivazione | Stato |
|---|---|---|
| DNS personalizzato free vs paid | Posizionamento di monetizzazione; brevemente consentito su free, poi tornato a solo-a-pagamento | **Annullata** a solo-a-pagamento |
| Accesso con email/password | Possedere le password aggiunge il carico di reset/MFA/lockout/breach/takeover mentre Apple + Google bastano; un recupero che bypassasse romperebbe la conoscenza zero | **Annullata** / mai rilasciata (solo Apple + Google) |
| Allowed Exceptions Guardrails (LAV-5) | La precedenza del guardrail è stata rilasciata tramite il più semplice revamp di filter-list-edit; il pagamento non deve mai bypassare il threat guardrail ad alta confidenza | **Annullata** (corsia `dropped/` creata) |
| Lockdown della branch-promotion su TestFlight | Lockdown iniziale riconsiderato; sostituito da un lockdown pianificato del runner post-open-source | **Annullata**, sostituita da un piano in backlog |
| Canale di controllo app↔extension | `sendProviderMessage` (`NETunnelProviderSession`) è l'**unico percorso di controllo app→tunnel** — porta lo stato tipizzato e con revisione e guida autoritativamente il run loop dell'estensione. Il precedente observer `CFNotificationCenter` lato estensione non si attivava mai in modo affidabile su dispositivo ed è stato **rimosso** (asserito assente dai test di source-introspection). Le notifiche Darwin sopravvivono solo nella direzione **tunnel→app**, come notifica di health-changed. | **Adottata** (provider-message è l'unico controllo app→tunnel; Darwin è solo health tunnel→app) |

> Invariante di sicurezza trasversale referenziato in tutto il documento: il pagamento non bypassa mai il **threat guardrail** validato tramite hash e non escludibile. La precedenza delle decisioni è **threat guardrail > allowlist locale (eccezioni consentite) > blocklist > default-allow.**
