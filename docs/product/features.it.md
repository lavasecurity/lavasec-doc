---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Catalogo delle funzioni

> Destinatari: PM / sviluppo. Questo catalogo descrive solo l'insieme di funzioni **attuale e già realizzato**. Tutto ciò che è stato progettato ma non ancora costruito si trova nella roadmap privata, non qui.

Lava Security è un'app iOS che mette la privacy al primo posto e filtra il DNS **localmente sul dispositivo** attraverso un tunnel a pacchetti NetworkExtension, bloccando i domini dannosi e indesiderati per le persone non tecniche (genitori, anziani) — con la protezione di base gratuita per sempre e senza bisogno di un account.

La promessa sulla privacy che sta dietro a ogni funzione qui sotto:

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai l'elenco dei domini che visiti — il backend conserva soltanto i metadati del catalogo, un backup cifrato per utente in forma opaca e diagnostiche anonime che scegli di inviare.

## Come leggere questo catalogo

- **Free** — disponibile per tutti, senza account, senza acquisto.
- **Plus** — sbloccato da Lava Security Plus, l'unico livello a pagamento, facoltativo. Plus sblocca **solo la personalizzazione**; non limita mai la sicurezza di base e non permette mai a chi paga di aggirare la protezione contro le minacce.
- Ogni riga è **Implementata** se non indicato diversamente accanto. Legenda dello stato: **Implementata** = rilasciata e confermata nel codice; **Pianificata** = progettata, non costruita; **Scartata** = respinta o annullata. Le voci Pianificate/Scartate sono documentate nella roadmap privata, non qui.

I limiti per livello, che fanno fede, si trovano in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, con alias `.plus`). Il **controllo** del diritto Plus è un flag locale (`isPaid`) — la fonte di verità. Il backend **rispecchia** i diritti dell'App Store (`POST /v1/account/entitlements/app-store-sync` aggiorna una riga `entitlements`), ma quella riga è uno specchio, non il controllo; al momento nessuna sincronizzazione con il backend governa l'attivazione delle funzioni.

---

## 1. Protezione e VPN

Il cuore del prodotto: un tunnel a pacchetti solo-DNS, locale, e il modello di stato sereno che lo accompagna.

| Funzione | Livello | Note |
|---|---|---|
| **Tunnel a pacchetti solo-DNS, locale** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercetta il DNS e valuta ogni dominio sul dispositivo. Nessun traffico di navigazione viene instradato attraverso Lava. Indirizzo del tunnel `10.255.0.2`, server DNS `10.255.0.1`. |
| **Ordine di precedenza delle decisioni di filtro** | Free | `blocco protezione minacce > lista consentiti locale (eccezioni permesse) > lista bloccati > consenti per impostazione predefinita`; i domini non validi vengono bloccati. (`FilterSnapshot.decision()`.) |
| **Precedenza delle query (prima il bootstrap)** | Free | `bootstrap del resolver > pausa temporanea > filtro` — il nome host del resolver stesso non viene mai bloccato. (`DNSQueryDispatcher`.) |
| **Avvio a freddo fail-closed** | Free | Un tunnel avviato a freddo senza uno snapshot riutilizzabile installa un `FailClosedRuntimeSnapshot` che blocca tutto il traffico anziché lasciar passare DNS non filtrato. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` mantiene attiva la protezione / la riavvia in automatico — abilitato **solo dopo** una connessione confermata, mai all'installazione del profilo, e neutralizzato durante un onboarding incompleto, così una nuova installazione non può attivare un tunnel impossibile da disattivare. |
| **Pausa temporanea (5 / 10 min) + ripresa** | Free | Pausa e ripresa passano attraverso `LavaProtectionCommandService` con un blocco file flock e deduplicazione per revisione. |
| **Pausa con autenticazione richiesta** | Free | Controllo facoltativo per singola area (`SecurityProtectedSurface.protectionPause`): la pausa richiede l'autenticazione locale sul dispositivo; il servizio comandi rifiuta una pausa non autenticata e la Live Activity nasconde i pulsanti di pausa. |
| **Riconnessione** | Free | Riavvia il tunnel direttamente (saltando il flusso di pausa del servizio comandi). |
| **Modello di stato Soft Shield Guardian** | Free | 7 stati espressivi — `dorme, si sveglia, sveglio, in pausa, riprova, preoccupato, riconoscente` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 livelli di gravità della connettività si riducono a 4 espressioni; resi in modo identico nell'app, nell'onboarding e nella Live Activity. |
| **Valutazione della connettività** | Free | 6 livelli di gravità (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) determinano l'espressione del guardiano e il testo di stato. |
| **Ottimizzazioni delle prestazioni** | Free | Attivazione cache-first, accorpamento delle query in corso, recupero a parallelismo limitato e accorpamento dei flap (attivazione a caldo misurata in ~112 ms su iPhone 15 Pro secondo il lavoro modulare di velocizzazione). |

> **Protezione del dispositivo (per tutti, mai a pagamento):** un limite massimo rigido di `~3,26M di regole` (obiettivo di 32 MB residenti sotto il tetto di memoria iOS di `~50 MiB` per estensione) viene applicato a tutti gli utenti al di sopra di qualsiasi livello (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Le configurazioni oltre il limite vengono rifiutate in modo deterministico (`exceedsDeviceMemoryBudget`) invece di lasciare che il tunnel venga terminato per jetsam.

---

## 2. Liste di blocco e filtraggio

Cosa viene bloccato, come si scelgono le liste e il confine tra i livelli.

| Funzione | Livello | Note |
|---|---|---|
| **Liste di blocco solo-URL-sorgente** | Free | Lava pubblica solo l'URL di origine + gli hash accettati; è il dispositivo a recuperare e analizzare i **byte** della lista. Lava **non** memorizza, replica, trasforma o serve mai i byte delle liste di blocco di terze parti. Vedi [decisione di conformità solo-URL-sorgente GPL](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catalogo curato (10 fonti)** | Free, attivabile | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **Liste di blocco predefinite gratuite** | Free | Una nuova installazione attiva **Block List Project Phishing + Scam** (le due fonti contrassegnate con `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **Analisi / normalizzazione / deduplicazione sul dispositivo** | Free | `BlocklistParser` supporta auto/plain/hosts/adblock/dnsmasq, elimina commenti/righe vuote/voci non valide, deduplica le stringhe identiche e limita a 1.000.000 di regole per lista. |
| **Validazione dei byte di origine** | Free | Dei byte recuperati viene calcolato lo SHA-256 e vengono accettati solo se il checksum è nell'elenco `accepted_source_hashes` del catalogo; in caso di mancata corrispondenza, Lava ripiega sull'ultima cache valida o passa a fail-closed. |
| **Filtro dei domini protetti** | Free | Da ogni fonte analizzata vengono rimossi i domini protetti di Lava / Apple / fornitori di identità (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …), così che una lista di origine non possa compromettere l'app, il tunnel o l'accesso. |
| **Eccezioni permesse (lista consentiti)** | Free | Lista consentiti gestita dall'utente che permette alcuni domini nonostante le liste di blocco. Limite Free: 10 domini consentiti / 10 bloccati (`FeatureLimits.free`). |
| **Budget delle regole di filtro (metrica per livello)** | Free / Plus | La metrica per livello rilasciata è il totale delle **regole** di dominio compilate: **Free 500K / Plus 2M** (`maxFilterRules` in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Sostituisce il vecchio limite sul numero di liste. Le configurazioni oltre il livello segnalano `exceedsTierFilterRuleLimit`. |
| **Limiti di domini più alti** | Plus | 500 domini consentiti / 500 bloccati (`FeatureLimits.plus`). |
| **Liste di blocco personalizzate** | Plus | `allowsCustomBlocklists`. Le liste personalizzate vengono recuperate e analizzate sul dispositivo, salvate in cache localmente e mai inoltrate ai server di Lava. |
| **Riutilizzo dell'artefatto di avvio a caldo** | Free | Un manifest + un'impronta identificativa permettono al tunnel di riutilizzare lo snapshot compatto già su disco senza ricompilare; il riutilizzo viene rifiutato (con un motivo rispettoso della privacy, limitato al solo nome del campo) quando gli input cambiano. |

> L'applicazione autorevole del budget avviene in fase di compilazione sull'unione deduplicata (`FilterSnapshotPreparationService`); viene controllato prima il limite del dispositivo, poi il limite del livello. L'indicatore nell'interfaccia in fase di selezione usa una somma per lista con un margine di tolleranza dell'1,10.

---

## 3. DNS cifrato

Trasporti del resolver e instradamento per le query non bloccate.

| Funzione | Livello | Note |
|---|---|---|
| **Cinque trasporti del resolver** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH basato su URLSession che preferisce HTTP/3. L'interfaccia annota **`DoH3` (senza barra)**, ad esempio "Quad9 (DoH3)", **solo quando una negoziazione h3 viene effettivamente osservata** — preferito, mai promesso (`DoHTransport`). |
| **DoT** | Free | `NWConnection` in pool (fino a 4 per endpoint) con rinnovo per inattività e un nuovo tentativo con connessione fresca. |
| **DoQ** (solo personalizzato) | Plus | DNS-over-QUIC **non ha un preset integrato** — è raggiungibile solo tramite un **resolver `doq://` personalizzato**, e il DNS personalizzato è Plus. Apre una **nuova connessione QUIC per ogni query** (il pool a 4 corsie offre concorrenza, non il riutilizzo dell'handshake); il riutilizzo delle connessioni è rinviato al requisito minimo di iOS 26. |
| **Resolver preimpostati** | Free | DNS del dispositivo (predefinito), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — nelle varianti IP / DoH / DoT dove disponibili (`DNSResolverPreset.allPresets`). |
| **Instradamento e failover del resolver** | Free | `ResolverOrchestrator` instrada in base al trasporto, ripiega su DNS in chiaro quando un piano cifrato non ha endpoint, esegue il failover per singolo endpoint con un freno di backoff, poi ripiega sul DNS del dispositivo. |
| **Ripiego sul DNS del dispositivo** | Free | Ripiega sul resolver della rete corrente quando il resolver selezionato non è disponibile; **attivo per impostazione predefinita**. Indicato con il livello di gravità `usingDeviceDNSFallback`. |
| **DNS personalizzato** | Plus | `allowsCustomDNS` — resolver fornito dall'utente (incluso il parsing dei DNS-stamp per i preset personalizzati). |

---

## 4. Account e backup a conoscenza zero

Accesso facoltativo con account e backup cifrato delle impostazioni. Niente di tutto questo è necessario per usare la protezione.

| Funzione | Livello | Note |
|---|---|---|
| **Accesso facoltativo con account (Apple + Google)** | Free | Flusso nativo con id_token scambiato presso Supabase Auth (`grant_type=id_token`) con un nonce sottoposto a hash; sul dispositivo, nel Keychain, viene salvata solo la sessione Supabase risultante. L'accesso con email/password non è offerto di proposito (Scartato). |
| **Backup cifrato a conoscenza zero** | Free | Busta AES-256-GCM lato client; la chiave casuale del contenuto è racchiusa in slot derivati con PBKDF2-HMAC-SHA256 (210k iterazioni). Su Supabase vengono caricati solo il testo cifrato + metadati non segreti (`user_backups`, RLS per utente). Il server non può decifrare senza un segreto in possesso dell'utente. |
| **Contenuto del backup ridotto al minimo** | Free | Salva gli ID delle liste di blocco attive, i domini consentiti/bloccati, le impostazioni del resolver, le preferenze dei registri locali, l'aspetto del guardiano, ecc. — ed esclude esplicitamente `isPaid`, i flag QA, le diagnostiche, gli snapshot e i byte completi delle liste di blocco. |
| **Slot della chiave con segreto del dispositivo** | Free | Un segreto del dispositivo di 32 byte nel Keychain solo-dispositivo (`...ThisDeviceOnly`, non sincronizzato con iCloud) per un ripristino fluido sullo stesso dispositivo. |
| **Frase di recupero + recupero assistito** | Free | Una frase CVCV di 8 parole (~105 bit) combinata tramite SHA256 con una quota di recupero conservata dal server per sbloccare lo slot di recupero assistito. A due fattori: nessuna delle due metà da sola permette di decifrare. |
| **Slot di recupero con passkey** | Free | Slot facoltativo protetto da WebAuthn, e **a conoscenza zero**: la sua chiave di sblocco è derivata **sul dispositivo** dall'output PRF WebAuthn dell'autenticatore (`hmac-secret`) (HKDF-SHA256). Il server non registra alcuna passkey, non emette challenge, non conserva alcun segreto di recupero e non espone alcun endpoint passkey — il precedente progetto con escrow lato server è stato scartato. La disponibilità in produzione su dispositivi fisici dipende dall'hosting Associated Domains / AASA (Pianificato). |
| **Eliminazione account / diritti sui dati** | Free | Un endpoint Worker autenticato elimina backup, impostazioni, diritti, profilo e allegati delle segnalazioni di bug, poi l'utente di Supabase Auth; l'app esegue il logout e cancella il materiale di sblocco locale. |

---

## 5. Widget e Live Activity

Presenza nella schermata di blocco e nella Dynamic Island.

| Funzione | Livello | Note |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): una singola `Activity<LavaActivityAttributes>` nella schermata di blocco e nella Dynamic Island (centro espanso / guardiano in compactLeading / compactTrailing + glifo di stato minimo). |
| **Visualizzazione della protezione a 5 stati** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — ciascuno corrisponde a una posa del guardiano, a un'icona SF Symbol e a un titolo. |
| **Pulsanti d'azione della Live Activity** | Free | Pausa 5 / 10 min, Riprendi, Riconnetti — `LiveActivityIntent` che vengono eseguiti nel processo dell'app tramite `LavaProtectionCommandService`. Le varianti di pausa autenticate richiedono l'autenticazione locale sul dispositivo. |
| **Riconciliazione singola, deduplicata e regolata per revisione** | Free | `LavaLiveActivityController` mantiene una sola Activity, aggiorna solo quando l'id o il contenuto cambiano davvero e regola gli aggiornamenti in base alla revisione di `ProtectionPauseStore`, così i tentativi ripetuti con intent obsoleti non possono far regredire lo stato. |
| **Interruttore delle Live Activity** | Free | Attivabile dall'utente nelle Impostazioni (`setUsesLiveActivities`), disponibile solo su iPhone/iPad. |

---

## 6. Onboarding

Il flusso al primo avvio che installa la configurazione VPN locale e imposta valori predefiniti sensati.

| Funzione | Livello | Note |
|---|---|---|
| **Flusso al primo avvio su più pagine** | Free | `OnboardingFlowView` — 6 pagine: `lava, guardIntro, features, vpn, notifications, done`. (L'installazione del profilo e la richiesta delle notifiche avvengono al momento giusto, non all'inizio.) |
| **Installazione del profilo VPN locale** | Free | Installa la configurazione VPN locale durante l'onboarding **senza** abilitare Connect-On-Demand, così la protezione non è mai attivata in automatico e in silenzio al termine — l'area Guard resta quella che fa fede. |
| **Richiesta del permesso per le notifiche** | Free | Richiesta durante il flusso, al passaggio delle notifiche. |
| **Valori predefiniti consigliati applicati** | Free | Resolver DNS del dispositivo, ripiego sul DNS del dispositivo attivo, registri locali attivi (conteggi + cronologia + attività), Block List Project Phishing + Scam attive, continua senza account (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Impostazioni

Aree di configurazione, sicurezza, diagnostica e feedback.

| Funzione | Livello | Note |
|---|---|---|
| **Codice di sblocco dell'app + biometria** | Free | `SecurityController`: verificatore del codice con SHA256 e salt nel Keychain + biometria `LAContext`, con una schermata di blocco per lo sblocco dell'app e una maschera per la privacy ai cambi di fase della scena. |
| **Protezione per singola area** | Free | `SecurityProtectedSurface` protegge sei aree: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Ciascuna può richiedere in modo indipendente l'autenticazione locale sul dispositivo (ad esempio la scheda Impostazioni restituisce `.requires(.appSettings)`). |
| **Selettore dell'aspetto di Lava Guard (7 aspetti)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, ciascuno con un colore del glifo abbinato nella Dynamic Island. |
| **Abbina l'icona dell'app** | Free | Icona alternativa facoltativa dell'app, abbinata all'aspetto del guardiano selezionato. |
| **Aspetto** | Free | Combinazione di colori chiara/scura/di sistema. |
| **Controlli dei registri solo locali** | Free | Interruttori per i conteggi del filtraggio, la cronologia dei domini (diagnostica) e l'attività di rete — tutti memorizzati sul dispositivo. |
| **Report / Attività (dettaglio Guard)** | Free | Diagnostica dinamica solo locale: conteggi di blocco/consenso, salute del tunnel, domini più frequenti. Le righe dei domini compaiono solo se è attivo il consenso alla cronologia. Si raggiunge come schermata di dettaglio dalla scheda Guard (`GuardDestination.activity`). |
| **Filtri (dettaglio Guard)** | Free | Schermata dei filtri con panoramica iniziale, dettaglio dei Domini bloccati / Eccezioni permesse e un flusso di bozza a fasi visualizza/modifica/conferma (`GuardDestination.filters`). |
| **Registro attività di Rete e Stato di Lava** | Free | Flusso di eventi solo locale e limitato delle transizioni di rete/runtime/utente, condiviso tramite App Group (`NetworkActivityLog`). |
| **Segnalazione di bug** | Free | Procedura guidata avviata dall'utente che invia un pacchetto anonimo a `POST /v1/bug-reports`; nella v1 nessuna cronologia dei domini. Raggiungibile anche scuotendo il dispositivo (`RageShakeDetector`). |
| **Note legali + Versione** | Free | Le Impostazioni mostrano le note legali di terze parti (vedi [Note di terze parti](../legal/third-party-notices.md)) e una pagina con versione/build. |

---

## Architettura dell'app (per orientarsi)

Tre bundle condividono un App Group `group.com.lavasec`, insieme a una cartella di sorgenti `lavasec-ios: Shared/` compilata al loro interno:

- **LavaSecApp** (`com.lavasec.app`) — il guscio dell'app SwiftUI; in questa build la radice è una `TabView` a due schede (**Guard** + **Settings**), con Filtri e Attività raggiungibili come schermate di dettaglio sotto la scheda Guard.
- **LavaSecTunnel** (`.tunnel`) — il motore di filtro/risoluzione DNS sul dispositivo.
- **LavaSecWidget** (`.widget`) — la Live Activity WidgetKit.
- **Shared/** — sorgenti condivise tra target (non un bundle): App Group, servizio comandi, mascotte, attributi/intent della Live Activity.

Il controllo tra app ed estensione usa i **provider message** di `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), non le notifiche Darwin. Le regole di filtro passano da app a estensione come file di snapshot dell'App Group (`filter-snapshot.json` / `.compact`).

---

## Documenti correlati

- Roadmap — le funzioni pianificate e scartate (posizionamento prezzi Plus/StoreKit, port Android, protezione a livello di URL, disponibilità Associated-Domain per le passkey, mini-gioco easter egg, rilascio open-source GPL-3.0, ecc.) vivono nella roadmap privata, non in questo catalogo pubblico.
- [Decisione di conformità solo-URL-sorgente GPL](../legal/gpl-source-url-only-compliance-decision.md)
- [Esclusione sui termini dei dati delle liste open-source](../legal/open-source-list-data-terms-carveout.md)
- [Note di terze parti](../legal/third-party-notices.md)
