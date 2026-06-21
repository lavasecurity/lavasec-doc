---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Catalogo delle funzionalità {#feature-catalog}

> Pubblico: PM / sviluppo. Questo catalogo copre solo l'insieme di funzionalità **attuali e già realizzate**. Tutto ciò che è progettato ma non ancora costruito si trova nella roadmap privata, non qui.

Lava Security è un'app iOS che mette la privacy al primo posto e filtra il DNS **localmente sul dispositivo** tramite un tunnel a pacchetti NetworkExtension, bloccando i domini dannosi e indesiderati per le persone non esperte di tecnologia (genitori, persone anziane) — con la protezione di base gratuita per sempre e senza bisogno di un account.

La promessa sulla privacy che sta dietro a ogni funzionalità qui sotto:

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i propri server e non riceve mai il flusso dei domini che visiti — il backend conserva solo i metadati del catalogo, un backup cifrato e opaco per ciascun utente e le diagnostiche anonimizzate che scegli di inviare.

## Come leggere questo catalogo {#how-to-read-this-catalog}

- **Free** — disponibile per tutti, senza account, senza acquisto.
- **Plus** — sbloccato da Lava Security Plus, l'unico livello a pagamento opzionale. Plus sblocca **solo la personalizzazione**; non limita mai la sicurezza di base e non consente mai a un utente pagante di aggirare la barriera di protezione dalle minacce.
- Ogni riga è **Implementata** salvo indicazione contraria. Legenda degli stati: **Implementata** = rilasciata e confermata nel codice; **Pianificata** = progettata, non costruita; **Scartata** = rifiutata o annullata. Gli elementi Pianificati/Scartati sono documentati nella roadmap privata, non qui.

I tetti dei livelli che fanno fede si trovano in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, con alias `.plus`). La **barriera** di abilitazione di Plus è un flag locale (`isPaid`) — la fonte di verità. Il backend **rispecchia** le abilitazioni dell'App Store (`POST /v1/account/entitlements/app-store-sync` inserisce o aggiorna una riga `entitlements`), ma quella riga è uno specchio, non la barriera; al momento nessuna sincronizzazione del backend regola le limitazioni.

---

## 1. Protezione e VPN {#1-protection-vpn}

Il cuore del prodotto: un tunnel a pacchetti locale solo per il DNS e il modello di stati sereno che lo circonda.

| Funzionalità | Livello | Note |
|---|---|---|
| **Tunnel a pacchetti locale solo per il DNS** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercetta il DNS e valuta ogni dominio sul dispositivo. Nessun traffico di navigazione viene instradato attraverso Lava. Indirizzo del tunnel `10.255.0.2`, server DNS `10.255.0.1`. |
| **Precedenza nelle decisioni di filtraggio** | Free | `barriera di protezione dalle minacce > lista locale dei permessi (eccezioni consentite) > lista di blocco > consenti per impostazione predefinita`; i domini non validi vengono bloccati. (`FilterSnapshot.decision()`.) |
| **Precedenza delle query (prima l'avvio)** | Free | `avvio del resolver > pausa temporanea > filtro` — il nome host del resolver stesso non viene mai bloccato. (`DNSQueryDispatcher`.) |
| **Avvio a freddo a chiusura sicura** | Free | Un tunnel a freddo senza uno snapshot riutilizzabile installa un `FailClosedRuntimeSnapshot` che blocca tutto il traffico invece di lasciar passare DNS non filtrato. |
| **Connessione su richiesta** | Free | `NEOnDemandRuleConnect` mantiene attiva la protezione / la riavvia automaticamente — abilitata **solo dopo** una connessione confermata, mai all'installazione del profilo, e neutralizzata durante un onboarding incompleto, così che un'installazione nuova non possa avviare un tunnel impossibile da disattivare. |
| **Pausa temporanea (5 / 10 min) + ripresa** | Free | La pausa/ripresa passa attraverso `LavaProtectionCommandService` sotto un blocco file flock con deduplicazione delle revisioni. |
| **Pausa con autenticazione richiesta** | Free | Barriera opzionale per ciascuna superficie (`SecurityProtectedSurface.protectionPause`): la pausa richiede l'autenticazione locale del dispositivo; il servizio comandi nega una pausa non autenticata e la Live Activity nasconde i pulsanti di pausa. |
| **Riconnessione** | Free | Riavvia il tunnel direttamente (aggira la pipeline di pausa del servizio comandi). |
| **Modello di stati Soft Shield Guardian** | Free | 7 stati di espressione — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 livelli di gravità della connettività si riducono a 4 volti; resi in modo identico nell'app, nell'onboarding e nella Live Activity. |
| **Valutazione della connettività** | Free | 6 livelli di gravità (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) determinano il volto del guardiano e il testo di stato. |
| **Ottimizzazione delle prestazioni** | Free | Attivazione con priorità alla cache, accorpamento delle query in corso, fetch a parallelismo limitato e accorpamento delle oscillazioni (attivazione a caldo misurata in ~112 ms su iPhone 15 Pro secondo il lavoro di velocizzazione modulare). |

> **Barriera del dispositivo (per tutti, mai un paywall):** un tetto fisso di `~3,26 mln di regole` (obiettivo di 32 MB residenti entro il limite di memoria per estensione di iOS di `~50 MiB`) è imposto per tutti gli utenti, al di sopra di qualsiasi livello (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Le configurazioni oltre il budget vengono rifiutate in modo deterministico (`exceedsDeviceMemoryBudget`) invece di lasciare che il tunnel venga terminato dal jetsam.

---

## 2. Liste di blocco e filtraggio {#2-blocklists-filtering}

Cosa viene bloccato, come si scelgono le liste e il confine tra i livelli.

| Funzionalità | Livello | Note |
|---|---|---|
| **Liste di blocco solo come URL di origine** | Free | Lava pubblica solo l'URL a monte + gli hash accettati; è il dispositivo a recuperare/analizzare i **byte** della lista. Lava **non** archivia, rispecchia, trasforma o distribuisce mai i byte delle liste di blocco di terze parti. Vedi [Decisione di conformità GPL "solo URL di origine"](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catalogo curato (10 fonti)** | Free per l'attivazione | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **Liste di blocco predefinite gratuite** | Free | Un'installazione nuova abilita **Block List Project Phishing + Scam** (le due fonti contrassegnate con `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **Analisi / normalizzazione / deduplicazione sul dispositivo** | Free | `BlocklistParser` supporta auto/plain/hosts/adblock/dnsmasq, scarta commenti/righe vuote/voci non valide, deduplica le stringhe identiche, con un limite di 1.000.000 di regole per lista. Una riga `hosts` con più host ora emette **ogni** host presente sulla riga, non solo il primo (regole del parser versione 2). |
| **Validazione dei byte a monte** | Free | Sui byte recuperati viene calcolato lo SHA-256 e vengono accettati solo se la somma di controllo è presente in `accepted_source_hashes` del catalogo; in caso di discrepanza Lava ricade sull'ultima cache valida o si chiude in sicurezza. |
| **Filtro dei domini protetti** | Free | Da ogni fonte analizzata vengono rimossi i domini protetti di Lava / Apple / provider di identità (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …) in modo che una lista a monte non possa rompere l'app, il tunnel o l'accesso. |
| **Eccezioni consentite (lista dei permessi)** | Free | Lista dei permessi gestita dall'utente che consente domini nonostante le liste di blocco. Limite Free: 25 domini consentiti / 25 bloccati (`FeatureLimits.free`). |
| **Budget delle regole di filtro (metrica di livello)** | Free / Plus | La metrica di livello rilasciata è il numero totale di **regole** di dominio compilate: **Free 500K / Plus 2M** (`maxFilterRules` in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Sostituisce il vecchio limite sul numero di liste. Le configurazioni oltre il livello restituiscono `exceedsTierFilterRuleLimit`. |
| **Limiti di domini più alti** | Plus | 1.000 domini consentiti / 1.000 bloccati (`FeatureLimits.plus`). |
| **Liste di blocco personalizzate** | Plus | `allowsCustomBlocklists`. Le liste personalizzate vengono recuperate e analizzate sul dispositivo, memorizzate nella cache locale, mai inoltrate ai server di Lava. |
| **Riutilizzo dell'artefatto di avvio a caldo** | Free | Un manifest + un'impronta di identità permettono al tunnel di riutilizzare lo snapshot compatto su disco senza ricompilarlo; il riutilizzo viene rifiutato (con un motivo rispettoso della privacy basato solo sul nome del campo) quando gli input cambiano. |
| **Salvataggio intelligente (conferma solo per gli indebolimenti)** | Free | Le modifiche al filtro che *rafforzano* soltanto o sono neutre (aggiungere una lista di blocco o un dominio bloccato) vengono applicate direttamente; le modifiche che *indeboliscono* la protezione — rimuovere una lista di blocco, rimuovere un dominio bloccato o aggiungere un'eccezione consentita — passano prima attraverso una scheda di conferma e revisione, con un pannello "Fai molta attenzione" quando vengono aggiunte eccezioni (`FiltersView.saveChanges()`, `weakensProtection`). |
| **Indicatore di budget (selezione salvabile)** | Free / Plus | L'indicatore di selezione abbrevia i conteggi (500K / 1.2M / 2M) e usa un margine di soglia morbida di 1,10 (la somma per singola lista sovrastima l'unione deduplicata di circa il 7–10%); un conteggio ancora entro la tolleranza viene riportato fisso, ad esempio "500K di 500K", finché non supera la soglia morbida (`FilterRuleBudget`). |

> L'imposizione autorevole del budget avviene al momento della compilazione sull'unione deduplicata (`FilterSnapshotPreparationService`); viene verificato prima il limite del dispositivo, poi quello del livello. L'indicatore dell'interfaccia al momento della selezione usa una somma per singola lista con un margine di soglia morbida di 1,10.

---

## 3. DNS cifrato {#3-encrypted-dns}

Trasporti del resolver e instradamento per le query non bloccate.

| Funzionalità | Livello | Note |
|---|---|---|
| **Cinque trasporti del resolver** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH basato su URLSession che preferisce HTTP/3. L'interfaccia annota **`DoH3` (senza barra)**, ad esempio "Quad9 (DoH3)", **solo quando una negoziazione h3 viene effettivamente osservata** — preferito, mai promesso (`DoHTransport`). |
| **DoT** | Free | `NWConnection` raggruppate (fino a 4 per endpoint) con aggiornamento per inattività e un singolo tentativo con connessione nuova. |
| **DoQ** (solo personalizzato) | Plus | DNS-over-QUIC **non ha alcun preset integrato** — è raggiungibile solo tramite un **resolver `doq://` personalizzato**, e il DNS personalizzato è Plus. Apre una **connessione QUIC nuova per ogni query** (il pool a 4 corsie offre concorrenza, non riutilizzo dell'handshake); il riutilizzo della connessione è rimandato a un livello minimo di distribuzione iOS-26. |
| **Resolver preimpostati** | Free | Device DNS (predefinito), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — nelle varianti IP / DoH / DoT dove offerte (`DNSResolverPreset.allPresets`). |
| **Instradamento del resolver e failover** | Free | `ResolverOrchestrator` instrada in base al trasporto, ripiega sul DNS in chiaro quando un piano cifrato non ha endpoint, esegue il failover per ciascun endpoint con una barriera di backoff, poi ricade sul device-DNS. |
| **Ripiego sul device-DNS** | Free | Ripiega sul resolver della rete attuale quando il resolver selezionato non è disponibile; **attivo per impostazione predefinita**. Mostrato come livello di gravità `usingDeviceDNSFallback`. |
| **DNS personalizzato** | Plus | `allowsCustomDNS` — resolver fornito dall'utente (inclusa l'analisi dei DNS-stamp per i preset personalizzati). |

---

## 4. Account e backup a conoscenza zero {#4-accounts-zero-knowledge-backup}

Accesso opzionale all'account e backup cifrato delle impostazioni. Niente di tutto questo è richiesto per usare la protezione.

| Funzionalità | Livello | Note |
|---|---|---|
| **Accesso opzionale all'account (Apple + Google)** | Free | Flusso nativo con id_token scambiato presso Supabase Auth (`grant_type=id_token`) con un nonce sottoposto a hash; solo la sessione Supabase risultante viene memorizzata localmente sul dispositivo nel Keychain. L'accesso con email/password non è offerto di proposito (Scartato). |
| **Backup cifrato a conoscenza zero** | Free | Busta AES-256-GCM lato client; la chiave casuale del payload è racchiusa in slot di chiave PBKDF2-HMAC-SHA256 (210k iterazioni). Solo il testo cifrato + metadati non segreti vengono caricati su Supabase `user_backups` (RLS per utente). Il server non può decifrare senza un segreto in possesso dell'utente. |
| **Payload di backup minimizzato** | Free | Effettua il backup degli ID delle liste di blocco abilitate, dei domini consentiti/bloccati, delle impostazioni del resolver, delle preferenze dei log locali, dell'aspetto del guardiano, ecc. — ed esclude esplicitamente `isPaid`, i flag di QA, le diagnostiche, gli snapshot e i byte completi delle liste di blocco. |
| **Slot di chiave con segreto del dispositivo** | Free | Un segreto del dispositivo di 32 byte nel Keychain solo del dispositivo (`...ThisDeviceOnly`, non sincronizzato con iCloud) per un ripristino fluido sullo stesso dispositivo. |
| **Frase di recupero + recupero assistito** | Free | Una frase CVCV di 8 parole (~105 bit) combinata tramite SHA256 con una quota di recupero conservata dal server per sbloccare lo slot di recupero assistito. A due fattori: nessuna delle due metà da sola decifra. |
| **Slot di recupero con passkey** | Free | Slot opzionale protetto da WebAuthn, e **a conoscenza zero**: la sua chiave di apertura è derivata **sul dispositivo** dall'output WebAuthn PRF (`hmac-secret`) dell'autenticatore (HKDF-SHA256). Il server non registra alcuna passkey, non emette challenge, non conserva alcun segreto di recupero e non espone alcuna route per le passkey — il precedente design con escrow lato server è stato scartato. La disponibilità in produzione sui dispositivi fisici dipende dall'hosting di Associated Domains / AASA (Pianificato). |
| **Eliminazione dell'account / diritti sui dati** | Free | Un endpoint Worker autenticato elimina backup, impostazioni, abilitazioni, profilo e allegati delle segnalazioni di bug, poi l'utente di Supabase Auth; l'app esegue la disconnessione e cancella il materiale di sblocco locale. |

---

## 5. Widget e Live Activity {#5-widget-live-activity}

Presenza sulla schermata di blocco e nella Dynamic Island.

| Funzionalità | Livello | Note |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): una singola `Activity<LavaActivityAttributes>` sulla schermata di blocco e nella Dynamic Island (guardiano espanso al centro / compactLeading / compactTrailing + glifo di stato minimale). |
| **Visualizzazione della protezione a 5 stati** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — ciascuno corrisponde a una posa del guardiano, un SF Symbol e un titolo. |
| **Pulsanti d'azione della Live Activity** | Free | Pausa 5 / 10 min, Riprendi, Riconnetti — `LiveActivityIntent` che girano nel processo dell'app tramite `LavaProtectionCommandService`. Le varianti di pausa autenticata richiedono l'autenticazione locale del dispositivo. |
| **Riconciliazione singola, deduplicata e controllata per revisione** | Free | `LavaLiveActivityController` mantiene una sola Activity, aggiorna solo in caso di un reale cambio di id/contenuto e regola gli aggiornamenti in base alla revisione di `ProtectionPauseStore` così che i nuovi tentativi di intent obsoleti non possano far regredire lo stato. |
| **Interruttore delle Live Activity** | Free | Attivabile dall'utente nelle Impostazioni (`setUsesLiveActivities`), disponibile solo su iPhone/iPad. |

---

## 6. Onboarding {#6-onboarding}

Flusso al primo avvio che installa la configurazione VPN locale e imposta valori predefiniti sensati.

| Funzionalità | Livello | Note |
|---|---|---|
| **Flusso al primo avvio su più pagine** | Free | `OnboardingFlowView` — 6 pagine: `lava, guardIntro, features, vpn, notifications, done`. (L'installazione del profilo e la richiesta delle notifiche avvengono al momento giusto, non all'inizio.) |
| **Installazione del profilo VPN locale** | Free | Installa la configurazione VPN locale durante l'onboarding **senza** abilitare la Connessione su richiesta, così che la protezione non sia mai attivata automaticamente in modo silenzioso al completamento — la superficie Guard resta autorevole. |
| **Richiesta di autorizzazione per le notifiche** | Free | Richiesta nel flusso al passaggio delle notifiche. |
| **Valori predefiniti consigliati applicati** | Free | Resolver Device DNS, ripiego sul device-DNS attivo, logging locale attivo (conteggi + cronologia + attività), Block List Project Phishing + Scam abilitate, continua senza account (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Impostazioni {#7-settings}

Superfici di configurazione, sicurezza, diagnostica e feedback.

| Funzionalità | Livello | Note |
|---|---|---|
| **Codice di sblocco dell'app + dati biometrici** | Free | `SecurityController`: verificatore del codice SHA256 con sale nel Keychain + dati biometrici `LAContext`, con un overlay di blocco allo sblocco dell'app e una maschera di privacy ai cambi di fase della scena. |
| **Protezione per ciascuna superficie** | Free | `SecurityProtectedSurface` regola sei superfici: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Ciascuna può richiedere in modo indipendente l'autenticazione locale del dispositivo (ad esempio la scheda Impostazioni restituisce `.requires(.appSettings)`). |
| **Selettore dell'aspetto di Lava Guard (7 aspetti)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, ciascuno con un colore di glifo della Dynamic Island abbinato. Scelto da un selettore radio a scheda inferiore ("Scegli la tua Guard", `LavaGuardLookPickerSheet`); gli aspetti ancora bloccati riportano un glifo a lucchetto e il pannello di sblocco/aggiornamento si trova nella scheda. |
| **Abbina l'icona dell'app** | Free | Icona alternativa opzionale dell'app abbinata all'aspetto del guardiano selezionato. |
| **Aspetto** | Free | Combinazione di colori chiara/scura/di sistema. |
| **Controlli del logging solo locale** | Free | Interruttori per i conteggi del filtraggio, la cronologia dei domini (diagnostica) e l'attività di rete — tutto memorizzato sul dispositivo. I log dettagliati (cronologia dei domini + attività di rete) vengono ridotti a una finestra di **7 giorni** (`LocalLogRetention.fineGrainedDays = 7`); i conteggi e i progressi di Lava Guard vengono conservati più a lungo. |
| **Log di Attività / Domini (dettaglio Guard)** | Free | Diagnostica dinamica solo locale, raggiungibile dalla scheda Guard (`GuardDestination.activity`). Il riepilogo è un **flusso** di richieste — un totale di "richieste elaborate" suddiviso in una barra di volume Consentite/Bloccate con "% protette localmente" (arrotondamento onesto: una quota minima si legge `<1%`, una quota quasi totale si legge `>99%`). Una sezione **Log dei domini** contiene i **Domini principali** (i più bloccati e consentiti, ordinati per numero di query) e la **Cronologia dei domini** (ricerche e decisioni recenti); le righe dei domini compaiono solo quando l'adesione alla cronologia è attiva. |
| **Filtro (dettaglio Guard)** | Free | Un'unica schermata di filtro unificata raggiungibile dalla scheda Guard. Un hub "Il mio filtro" apre un'unica schermata consolidata **Il mio filtro** con due scaffali — **"Lava blocca questi"** (liste di blocco + domini bloccati singolarmente) e **"Lava lascia passare questi"** (eccezioni consentite) — sotto un unico flusso di bozza Modifica/Salva. Un diagramma di flusso "Telefono → Lava → Internet" apre la scheda e l'apertura di "Il mio filtro" aggiorna automaticamente il catalogo. |
| **Attività di rete (Impostazioni → Avanzate)** | Free | Flusso di eventi solo locale e limitato delle transizioni di rete/runtime/utente, condiviso tramite App Group (`NetworkActivityLog`). Spostato dalla superficie Attività a **Impostazioni → Avanzate** (dopo "Statistiche da smanettoni", `SettingsRoute.networkActivity`), dietro la barriera `.activityViewing`, con un proprio pannello sulla privacy ("Resta su questo iPhone", conservato 7 giorni). |
| **Segnalazione di bug** | Free | Procedura guidata avviata dall'utente che invia un pacchetto anonimizzato a `POST /v1/bug-reports`; nessuna cronologia dei domini nella v1. Il pacchetto ora include anche la provenienza della build (`appVersion`/`appBuild`/`sourceRevision`) e i contatori di onestà sulla connettività. Raggiungibile anche tramite scuoti-per-segnalare (`RageShakeDetector`). |
| **Gestione dell'abbonamento** | Plus | Per gli abbonati attivi la schermata di Aggiornamento mostra Gestisci abbonamento (piani con rinnovo automatico, tramite `AppStore.showManageSubscriptions`), Ripristina acquisto e la data di scadenza dell'abilitazione; uno sblocco a vita non mostra alcuna riga Gestisci. |
| **Note legali + Versione** | Free | Le Impostazioni mostrano le note legali di terze parti (vedi [Note di terze parti](../legal/third-party-notices.md)) e una pagina di versione/build. |

---

## Architettura dell'app (per orientarsi) {#app-architecture-for-orientation}

Tre bundle condividono un unico App Group `group.com.lavasec`, insieme a una cartella di sorgenti `lavasec-ios: Shared/` compilata al loro interno:

- **LavaSecApp** (`com.lavasec.app`) — shell dell'app SwiftUI; in questa build la radice è una `TabView` a due schede (**Guard** + **Impostazioni**), con Filtro e Attività raggiungibili come schermate di dettaglio sotto la scheda Guard (Attività di rete ora si trova sotto Impostazioni → Avanzate).
- **LavaSecTunnel** (`.tunnel`) — il motore di filtraggio/risoluzione DNS sul dispositivo.
- **LavaSecWidget** (`.widget`) — la Live Activity WidgetKit.
- **Shared/** — sorgenti condivise tra i target (non un bundle): App Group, servizio comandi, mascotte, attributi/intent della Live Activity.

Il controllo tra app ↔ estensione usa i **provider message** di `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), non le notifiche Darwin. Le regole di filtro passano da app → estensione come file snapshot dell'App Group (`filter-snapshot.json` / `.compact`).

---

## Documenti correlati {#related-docs}

- Roadmap — le funzionalità pianificate e scartate (posizionamento dei prezzi/StoreKit di Plus, port Android, protezione a livello di URL, disponibilità di Associated-Domain per le passkey, mini-gioco easter-egg, rilascio open-source GPL-3.0, ecc.) si trovano nella roadmap privata, non in questo catalogo pubblico.
- [Decisione di conformità GPL "solo URL di origine"](../legal/gpl-source-url-only-compliance-decision.md)
- [Esclusione sui termini dei dati delle liste open-source](../legal/open-source-list-data-terms-carveout.md)
- [Note di terze parti](../legal/third-party-notices.md)
