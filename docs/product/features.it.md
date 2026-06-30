---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Catalogo delle funzionalità

> Destinatari: PM / ingegneria. Questo catalogo copre esclusivamente l'insieme di funzionalità **attuali e implementate**. Tutto ciò che è progettato ma non costruito risiede nella roadmap privata, non qui.

Lava Security è un'app iOS privacy-first che filtra il DNS **localmente sul dispositivo** attraverso un packet tunnel NetworkExtension, bloccando i domini dannosi e indesiderati per utenti non tecnici (genitori, persone anziane). La protezione di base è gratuita per sempre e non richiede un account.

La promessa sulla privacy alla base di ogni funzionalità qui sotto:

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva soltanto metadati del catalogo, un backup cifrato opaco per ogni utente e diagnostiche anonimizzate che scegli di inviare.

## Come leggere questo catalogo

- **Free** — disponibile per tutti, senza account, senza acquisto.
- **Plus** — sbloccato da Lava Security Plus, l'unico livello a pagamento opzionale. Plus sblocca **solo la personalizzazione**; non limita mai la sicurezza di base e non consente mai a un utente pagante di aggirare la protezione contro le minacce.
- Ogni riga è **Implementata** salvo diversa indicazione in linea. Legenda dello stato: **Implementata** = rilasciata e confermata nel codice; **Pianificata** = progettata, non costruita; **Abbandonata** = rifiutata o annullata. Le voci Pianificate/Abbandonate sono documentate nella roadmap privata, non qui.

I tetti dei livelli che fanno da fonte di verità risiedono in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, con alias `.plus`). Il **gate** dell'abilitazione Plus è un flag locale (`isPaid`) — la fonte di verità. Il backend **rispecchia** le abilitazioni dell'App Store (`POST /v1/account/entitlements/app-store-sync` esegue l'upsert di una riga `entitlements`), ma quella riga è uno specchio, non il gate; nessuna sincronizzazione del backend governa ancora il gating.

---

## 1. Protezione e VPN

Il prodotto di base: un packet tunnel locale solo-DNS e il modello di stato calmo che lo circonda.

| Funzionalità | Livello | Note |
|---|---|---|
| **Packet tunnel locale solo-DNS** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercetta il DNS e valuta ogni dominio sul dispositivo. Nessun traffico di navigazione viene instradato attraverso Lava. Indirizzo del tunnel `10.255.0.2`, server DNS `10.255.0.1`. |
| **Precedenza delle decisioni di filtraggio** | Free | `threat guardrail block > local allowlist (allowed exceptions) > blocklist > default-allow`; i domini non validi vengono bloccati. (`FilterSnapshot.decision()`.) |
| **Precedenza delle query (bootstrap-first)** | Free | `resolver-bootstrap > temporary-pause > filter` — l'hostname del resolver stesso non viene mai bloccato. (`DNSQueryDispatcher`.) |
| **Avvio a freddo fail-closed** | Free | Un tunnel a freddo senza snapshot riutilizzabile installa un `FailClosedRuntimeSnapshot` che blocca tutto il traffico invece di lasciar trapelare DNS non filtrato. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` mantiene attiva la protezione / la riavvia automaticamente — abilitato **solo dopo** una connessione confermata, mai all'installazione del profilo, e neutralizzato durante un onboarding incompleto, così che una nuova installazione non possa attivare un tunnel non disattivabile. |
| **Pausa temporanea (configurabile 1–30 min, default 5) + ripresa** | Free | Pausa e ripresa passano per `LavaProtectionCommandService` con un blocco file flock e deduplicazione delle revisioni. |
| **Pausa con autenticazione richiesta** | Free | Gate opt-in per superficie (`SecurityProtectedSurface.protectionPause`): la pausa richiede l'autenticazione locale del dispositivo; il servizio di comando nega una pausa non autenticata e la Live Activity nasconde i pulsanti di pausa. |
| **Riconnessione** | Free | Riavvia il tunnel direttamente (bypassa la pipeline di pausa del servizio di comando). |
| **Modello di stato Soft Shield Guardian** | Free | 7 stati espressivi — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 livelli di gravità della connettività si riducono a 4 volti; resi in modo identico nell'app, nell'onboarding e nella Live Activity. |
| **Valutazione della connettività** | Free | 6 livelli di gravità (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) guidano il volto del guardian e il testo di stato. |
| **Ottimizzazione delle prestazioni** | Free | Attivazione cache-first, coalescenza delle query in volo, fetch parallelo limitato e coalescenza dei flap (attivazione a caldo misurata a ~112 ms su iPhone 15 Pro secondo il lavoro di accelerazione modulare). |

> **Protezione del dispositivo (per tutti, mai un paywall):** un tetto rigido di `~3.26M-rule` (obiettivo di 32 MB residenti, entro il limite di memoria per estensione di iOS di `~50 MiB`) è applicato a tutti gli utenti al di sopra di qualsiasi livello (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Le configurazioni fuori budget vengono rifiutate in modo deterministico (`exceedsDeviceMemoryBudget`) invece di lasciare che il tunnel subisca il jetsam.

---

## 2. Blocklist e filtraggio

Cosa viene bloccato, come vengono scelte le liste e il confine tra i livelli.

| Funzionalità | Livello | Note |
|---|---|---|
| **Blocklist solo-source-url** | Free | Lava pubblica solo l'URL upstream + gli hash accettati; il dispositivo recupera/analizza i **byte** della lista da solo. Lava **non** memorizza, rispecchia, trasforma o serve mai i byte delle blocklist di terze parti. Vedi [decisione di conformità GPL solo-source-url](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catalogo curato (categorizzato)** | Gratuito da abilitare | Fonti curate organizzate in categorie a difesa in profondità — Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling, Piracy & Torrent — da HaGeZi, The Block List Project, OISD, StevenBlack, AdGuard, 1Hosts e Phishing.Database. L'insieme completo e attuale è pubblicato nel [Catalogo delle blocklist](../legal/blocklist-catalog.md); ogni piattaforma riflette la versione del catalogo con cui è stata rilasciata. |
| **Blocklist predefinite gratuite** | Free | Un'installazione nuova abilita **Block List Basic** — una lista combinata ampia e permissiva (le fonti contrassegnate con `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). Tutto il resto è opt-in. |
| **Analisi / normalizzazione / deduplicazione sul dispositivo** | Free | `BlocklistParser` supporta auto/plain/hosts/adblock/dnsmasq, scarta commenti/righe vuote/non valide, deduplica le stringhe esatte, limita a 1.000.000 di regole per lista. Una riga `hosts` multi-host ora emette **ogni** host della riga, non solo il primo (versione 2 delle regole del parser). |
| **Integrità upstream (TLS + URL curato)** | Free | I byte della lista della community vengono recuperati tramite TLS direttamente dall'upstream curato `source_url` e accettati nel rispetto dei limiti di dimensione + formato + conteggio regole; gli `accepted_source_hashes` del catalogo sono **indicativi** (identità della cache + audit), non un gate rigido — una lista a rotazione rapida non viene mai rifiutata per essersi discostata da un hash fissato. Il livello **threat-guardrail** di Lava (curato da Lava, non può essere consentito) rimane rigorosamente ancorato all'hash. |
| **Filtro dei domini protetti** | Free | Ogni fonte analizzata viene ripulita dai domini protetti di Lava / Apple / provider di identità (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …) così che una lista upstream non possa danneggiare l'app, il tunnel o l'accesso. |
| **Allowed Exceptions (allowlist)** | Free | Allowlist gestita dall'utente che consente domini nonostante le blocklist. Limite Free: 25 domini consentiti / 25 bloccati (`FeatureLimits.free`). |
| **Budget delle regole di filtro (metrica del livello)** | Free / Plus | La metrica del livello rilasciata è il totale di **regole** di dominio compilate: **Free 500K / Plus 2M** (`maxFilterRules` in `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Sostituisce il vecchio limite sul conteggio delle liste. Le configurazioni fuori livello fanno emergere `exceedsTierFilterRuleLimit`. |
| **Limiti di dominio più alti** | Plus | 1.000 domini consentiti / 1.000 bloccati (`FeatureLimits.plus`). |
| **Blocklist personalizzate** | Plus | `allowsCustomBlocklists`. Le liste personalizzate vengono recuperate e analizzate sul dispositivo, memorizzate localmente nella cache, mai inoltrate ai server di Lava. |
| **Riutilizzo dell'artefatto di avvio a caldo** | Free | Un manifest e un'impronta di identità consentono al tunnel di riutilizzare lo snapshot compatto su disco senza ricompilarlo; il riutilizzo viene rifiutato (con un motivo privacy-safe basato solo sul nome del campo) quando gli input cambiano. |
| **Smart Save (conferma solo per indebolimento)** | Free | Le modifiche al tuo Filtro che solo *rafforzano* o sono neutre (aggiungere una blocklist o un dominio bloccato) si applicano direttamente; le modifiche che *indeboliscono* la protezione — rimuovere una blocklist, rimuovere un dominio bloccato o aggiungere un'eccezione consentita — passano prima attraverso un foglio di conferma di revisione, con un pannello "Fai molta attenzione" quando vengono aggiunte eccezioni (`FiltersView.saveChanges()`, `weakensProtection`). |
| **Indicatore di budget (selezione salvabile)** | Free / Plus | L'indicatore di selezione abbrevia i conteggi (500K / 1.2M / 2M) e usa un margine di soglia morbida di 1,10 (la somma per lista sovrastima l'unione deduplicata di circa il 7–10%); un conteggio ancora entro la tolleranza viene fissato per leggere ad es. "500K di 500K" finché non supera la soglia morbida (`FilterRuleBudget`). |

> L'applicazione autorevole del budget avviene al momento della compilazione sull'unione deduplicata (`FilterSnapshotPreparationService`); viene controllato prima il limite del dispositivo, poi il limite del livello. L'indicatore dell'interfaccia al momento della selezione usa una somma per lista con un margine di soglia morbida di 1,10.

---

## 3. DNS cifrato

Trasporti del resolver e instradamento per le query non bloccate.

| Funzionalità | Livello | Note |
|---|---|---|
| **Cinque trasporti del resolver** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH basato su URLSession che preferisce HTTP/3. L'interfaccia annota **`DoH3` (senza slash)**, ad es. "Quad9 (DoH3)", **solo quando viene effettivamente osservata una negoziazione h3** — preferito, mai promesso (`DoHTransport`). |
| **DoT** | Free | `NWConnection` in pool (fino a 4/endpoint) con aggiornamento per inattività e un nuovo tentativo con connessione fresca. |
| **DoQ** (solo personalizzato) | Plus | DNS-over-QUIC **non ha alcun preset integrato** — è raggiungibile solo tramite un **resolver `doq://` personalizzato**, e il DNS personalizzato è Plus. Apre una **nuova connessione QUIC per ogni query** (il pool a 4 lane offre concorrenza, non riutilizzo dell'handshake); il riutilizzo della connessione è rimandato a un floor di deployment iOS-26. |
| **Resolver preimpostati** | Free | Device DNS (default), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — nelle varianti IP / DoH / DoT dove offerte (`DNSResolverPreset.allPresets`). |
| **Instradamento e failover del resolver** | Free | `ResolverOrchestrator` instrada per trasporto, degrada a DNS in chiaro quando un piano cifrato non ha endpoint, esegue il failover per endpoint con un gate di backoff, poi il fallback su device-DNS. |
| **Fallback su device-DNS** | Free | Ricade sul resolver della rete corrente quando il resolver selezionato non è disponibile; **attivo per impostazione predefinita**. Esposto come livello di gravità `usingDeviceDNSFallback`. |
| **DNS personalizzato** | Plus | `allowsCustomDNS` — resolver fornito dall'utente (inclusa l'analisi dei DNS-stamp per i preset personalizzati). |

---

## 4. Account e backup zero-knowledge

Accesso facoltativo all'account e backup cifrato delle impostazioni. Nulla di tutto ciò è necessario per usare la protezione.

| Funzionalità | Livello | Note |
|---|---|---|
| **Accesso facoltativo all'account (Apple + Google)** | Free | Flusso nativo id_token scambiato presso Supabase Auth (`grant_type=id_token`) con un nonce sottoposto a hash; solo la sessione Supabase risultante viene memorizzata localmente sul dispositivo nel Keychain. L'accesso con email/password non è offerto intenzionalmente (Abbandonato). |
| **Backup cifrato zero-knowledge** | Free | Envelope AES-256-GCM lato client; la chiave casuale del payload è racchiusa in slot di chiave PBKDF2-HMAC-SHA256 (210k iterazioni). Solo il testo cifrato + i metadati non segreti vengono caricati su Supabase `user_backups` (RLS per utente). Il server non può decifrare senza un segreto in possesso dell'utente. |
| **Payload di backup minimizzato** | Free | Esegue il backup degli ID delle blocklist abilitate, dei domini consentiti/bloccati, delle impostazioni del resolver, delle preferenze dei log locali, dell'aspetto del guardian, ecc. — ed esclude esplicitamente `isPaid`, i flag QA, le diagnostiche, gli snapshot e i byte completi delle blocklist. |
| **Slot di chiave con segreto del dispositivo** | Free | Un segreto del dispositivo di 32 byte nel Keychain solo-dispositivo (`...ThisDeviceOnly`, non sincronizzato con iCloud) per un ripristino fluido sullo stesso dispositivo. |
| **Frase di recupero + recupero assistito** | Free | Una frase CVCV di 8 parole (~105 bit) combinata con una quota di recupero conservata dal server tramite SHA256 per sbloccare lo slot di recupero assistito. A due fattori: nessuna delle due metà da sola decifra. |
| **Slot di recupero con passkey** | Free | Slot facoltativo protetto da WebAuthn, e **zero-knowledge**: la sua chiave di unwrap è derivata **sul dispositivo** dall'output PRF WebAuthn (`hmac-secret`) dell'autenticatore (HKDF-SHA256). Il server non registra alcuna passkey, non emette challenge, non conserva alcun segreto di recupero e non espone alcuna route di passkey — il precedente design con escrow lato server è stato abbandonato. La prontezza per la produzione sui dispositivi fisici dipende dall'hosting di Associated Domains / AASA (Pianificato). |
| **Eliminazione dell'account / diritti sui dati** | Free | L'endpoint Worker autenticato elimina i backup, le impostazioni, le abilitazioni, il profilo e gli allegati delle segnalazioni di bug, quindi l'utente Supabase Auth; l'app esegue il logout e cancella il materiale di sblocco locale. |

---

## 5. Widget e Live Activity

Presenza sulla schermata di blocco e nella Dynamic Island.

| Funzionalità | Livello | Note |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): una singola `Activity<LavaActivityAttributes>` sulla schermata di blocco e nella Dynamic Island (centro espanso / guardian compactLeading / compactTrailing + glifo di stato minimale). |
| **Visualizzazione della protezione a 5 stati** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — ciascuno mappato a una posa del guardian, un SF Symbol e un titolo. |
| **Pulsanti azione della Live Activity** | Free | Metti in pausa per N min (durata configurata, default 5), Riprendi, Riconnetti — `LiveActivityIntent` che vengono eseguiti nel processo dell'app tramite `LavaProtectionCommandService`. Le varianti di pausa autenticate richiedono l'autenticazione locale del dispositivo. |
| **Riconciliazione singola, deduplicata, con gate di revisione** | Free | `LavaLiveActivityController` mantiene una sola Activity, aggiorna solo su un reale cambiamento di id/contenuto e applica un gate agli aggiornamenti tramite la revisione di `ProtectionPauseStore`, così che i tentativi di intent obsoleti non possano far regredire lo stato. |
| **Interruttore delle Live Activity** | Free | Attivabile dall'utente nelle Impostazioni (`setUsesLiveActivities`), disponibile solo su iPhone/iPad. |

---

## 6. Onboarding

Flusso al primo avvio che installa la configurazione VPN locale e imposta valori predefiniti sensati.

| Funzionalità | Livello | Note |
|---|---|---|
| **Flusso multi-pagina al primo avvio** | Free | `OnboardingFlowView` — 6 pagine: `lava, guardIntro, features, vpn, notifications, done`. (L'installazione del profilo e la richiesta di notifica avvengono al passo giusto, non all'inizio.) |
| **Installazione del profilo VPN locale** | Free | Installa la configurazione VPN locale durante l'onboarding **senza** abilitare Connect-On-Demand, così che la protezione non sia mai attivata automaticamente in modo silenzioso al completamento — la superficie Guard resta autorevole. |
| **Richiesta di autorizzazione alle notifiche** | Free | Richiesta nel flusso al passo delle notifiche. |
| **Valori predefiniti consigliati applicati** | Free | Resolver Device DNS, fallback su device-DNS attivo, logging locale attivo (conteggi + cronologia + attività), Block List Basic abilitata, continua senza account (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Impostazioni

Superfici di configurazione, sicurezza, diagnostica e feedback.

| Funzionalità | Livello | Note |
|---|---|---|
| **Codice di sblocco dell'app + biometria** | Free | `SecurityController`: verificatore di codice SHA256 con salt nel Keychain + biometria `LAContext`, con un overlay di blocco allo sblocco dell'app e una maschera di privacy sui cambiamenti di fase della scena. |
| **Protezione per superficie** | Free | `SecurityProtectedSurface` applica un gate a sei superfici: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Ciascuna può richiedere indipendentemente l'autenticazione locale del dispositivo (ad es. la scheda Impostazioni restituisce `.requires(.appSettings)`). |
| **Selettore dell'aspetto di Lava Guard (7 aspetti)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, ciascuno con un colore di glifo della Dynamic Island abbinato. Scelti da un selettore radio a bottom-sheet ("Scegli il tuo Guard", `LavaGuardLookPickerSheet`); gli aspetti ancora bloccati riportano un glifo a lucchetto e il pannello di sblocco/aggiornamento si trova nel foglio. |
| **Abbina l'icona dell'app** | Free | Icona dell'app alternativa facoltativa abbinata all'aspetto del guardian selezionato. |
| **Aspetto** | Free | Schema di colori chiaro/scuro/sistema. |
| **Controlli di logging solo-locale** | Free | Interruttori per i conteggi del filtraggio, la cronologia dei domini (diagnostica) e l'attività di rete — tutti memorizzati sul dispositivo. I log a grana fine (cronologia dei domini + attività di rete) vengono ridotti a una finestra di **7 giorni** (`LocalLogRetention.fineGrainedDays = 7`); i conteggi e i progressi di Lava Guard vengono conservati più a lungo. |
| **Log attività / domini (dettaglio Guard)** | Free | Diagnostica dinamica solo-locale, raggiunta dalla scheda Guard (`GuardDestination.activity`). Il riepilogo è un **flusso** di richieste — un totale di "richieste elaborate" suddiviso in una barra di volume Consentite/Bloccate con "% protetta localmente" (arrotondamento onesto: una quota minima si legge `<1%`, una quota quasi totale si legge `>99%`). Una sezione **Log dei domini** contiene i **Domini principali** (più bloccati e consentiti, ordinati per conteggio delle query) e la **Cronologia dei domini** (ricerche e decisioni recenti); le righe dei domini compaiono solo quando l'opt-in alla cronologia è attivo. |
| **Filtro (dettaglio Guard)** | Free | Schermata di filtro unificata raggiunta dalla scheda Guard. Un hub "Il mio filtro" apre un'unica schermata consolidata **Il mio filtro** con due ripiani — **"Lava blocca questi"** (blocklist + domini bloccati individualmente) e **"Lava lascia passare questi"** (eccezioni consentite) — sotto un unico flusso di bozza Modifica/Salva. Un diagramma di flusso "Telefono → Lava → Internet" apre la scheda, e all'apertura di Il mio filtro il catalogo viene aggiornato automaticamente. |
| **Attività di rete (Impostazioni → Avanzate)** | Free | Flusso di eventi limitato solo-locale di transizioni di rete/runtime/utente, condiviso tramite App Group (`NetworkActivityLog`). Spostato dalla superficie Attività in **Impostazioni → Avanzate** (dopo "Nerd Stats", `SettingsRoute.networkActivity`), dietro il lock `.activityViewing`, con il proprio pannello sulla privacy ("Resta su questo iPhone", conservato 7 giorni). |
| **Segnalazione di bug** | Free | Procedura guidata attivata dall'utente che invia un pacchetto anonimizzato a `POST /v1/bug-reports`; nessuna cronologia dei domini nella v1. Il pacchetto ora trasporta anche la provenienza della build (`appVersion`/`appBuild`/`sourceRevision`) e i contatori di onestà sulla connettività. Raggiungibile anche tramite shake-to-report (`RageShakeDetector`). |
| **Gestione dell'abbonamento** | Plus | Per gli abbonati attivi la schermata Aggiorna mostra Gestisci abbonamento (piani a rinnovo automatico, tramite `AppStore.showManageSubscriptions`), Ripristina acquisto e la data di scadenza dell'abilitazione. |
| **Note legali + Versione** | Free | Le Impostazioni espongono le note legali di terze parti (vedi [Note di terze parti](../legal/third-party-notices.md)) e una pagina di versione/build. |

---

## Architettura dell'app (per orientamento)

Tre bundle condividono un App Group `group.com.lavasec`, insieme a una cartella di sorgenti `lavasec-ios: Shared/` compilata al loro interno:

- **LavaSecApp** (`com.lavasec.app`) — shell dell'app SwiftUI; in questa build la root è un `TabView` a due schede (**Guard** + **Settings**), con Filtro e Attività raggiunti come schermate di dettaglio sotto la scheda Guard (Attività di rete ora risiede sotto Impostazioni → Avanzate).
- **LavaSecTunnel** (`.tunnel`) — il motore di filtro/risoluzione DNS sul dispositivo.
- **LavaSecWidget** (`.widget`) — la Live Activity WidgetKit.
- **Shared/** — sorgenti cross-target (non un bundle): App Group, servizio di comando, mascotte, attributi/intent della Live Activity.

Il controllo App ↔ estensione usa i **provider messages** di `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), non le notifiche Darwin. Le regole di filtro attraversano app → estensione come file di snapshot App-Group (`filter-snapshot.json` / `.compact`).

---

## Documenti correlati

- Roadmap — le funzionalità pianificate e abbandonate (prezzi Plus/posizionamento StoreKit, port Android, protezione a livello di URL, prontezza passkey con Associated-Domain, mini-gioco easter-egg, rilascio open-source GPL-3.0, ecc.) risiedono nella roadmap privata, non in questo catalogo pubblico.
- [Decisione di conformità GPL solo-source-url](../legal/gpl-source-url-only-compliance-decision.md)
- [Esclusione dei termini sui dati delle liste open-source](../legal/open-source-list-data-terms-carveout.md)
- [Note di terze parti](../legal/third-party-notices.md)
