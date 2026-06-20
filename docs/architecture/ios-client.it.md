---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Architettura del client iOS

> Pubblico: ingegneri iOS che lavorano in `lavasec-ios`.

Lava Security è un'app iOS che mette la privacy al primo posto e filtra il DNS localmente sul dispositivo tramite un tunnel a pacchetti NetworkExtension che gira sul dispositivo stesso, bloccando i domini noti come rischiosi o indesiderati senza far passare la tua navigazione attraverso i server di Lava. Questo documento spiega come è strutturato il client iOS: i target, come l'app comunica con la sua estensione tunnel, il ciclo di vita della VPN, il modello di stato del Guardian, la Live Activity e il widget, il flusso di onboarding e il proprietario dello stato lato app (`AppViewModel`).

Per una visione dell'intero sistema (l'app, il Worker del catalogo e Supabase), vedi [Panoramica del sistema](./system-overview.md).

---

## 1. Target e responsabilità

Il client viene distribuito come tre target eseguibili più una libreria core condivisa. Tutti e tre i target fanno parte dello stesso **App Group** (`group.com.lavasec`) e collegano `LavaSecCore`.

| Target | Bundle id | Responsabilità |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | L'app SwiftUI. Possiede l'interfaccia, detiene l'entitlement NetworkExtension e controlla il tunnel tramite `NETunnelProviderManager`. `AppViewModel` è la fonte di verità del ciclo di vita della VPN. |
| **Tunnel a pacchetti** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | La sottoclasse `NEPacketTunnelProvider` chiamata `PacketTunnelProvider` (alias `LavaSecTunnel`). Analizza i pacchetti DNS, estrae il dominio richiesto, lo valuta rispetto allo snapshot compilato mappato in memoria e inoltra a monte le richieste consentite. È vincolata dal tetto di memoria jetsam per processo di circa 50 MiB. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Un `WidgetBundle` il cui unico membro è `LavaProtectionLiveActivityWidget` — la presentazione Live Activity / Dynamic Island. |

Il codice condiviso si trova in due posti:

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — il core indipendente dalla piattaforma: il motore di filtraggio, i trasporti del resolver, i calcoli su snapshot/budget, gli store di protezione e il core `GuardianMascotAnimation`. Come da `VPNLifecycleController.swift:3-6`, i tipi NetworkExtension sono volutamente tenuti fuori da questo modulo affinché la sua logica di ciclo di vita resti testabile con dei fake; il target app fornisce le conformità basate su `NetworkExtension`.
- **`Shared/`** — codice compilato in più di un target (ad esempio `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

I dettagli interni del tunnel a pacchetti (l'analisi del DNS, lo snapshot compilato, i trasporti cifrati del resolver e il budget delle regole di filtro) sono trattati in profondità in [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md). Questo documento si concentra sull'architettura lato app e sul confine tra l'app e l'estensione.

---

## 2. IPC tra app ed estensione

L'app e l'estensione del tunnel a pacchetti sono processi separati. Si coordinano tramite tre meccanismi, tutti ancorati all'App Group.

### Container dell'App Group

`group.com.lavasec` è il container condiviso che permette ad app, tunnel e widget di leggere e scrivere lo stesso stato e la stessa configurazione di `LavaSecCore`. `LavaSecAppGroup` (`Shared/AppGroup.swift`) centralizza ogni chiave e nome file condiviso, così i processi non possono mai divergere sulle costanti stringa, tra cui:

- Gli artefatti dello snapshot compilato (`filter-snapshot.compact`, `filter-snapshot.json`), il file `app-configuration.json` serializzato, lo stato di salute del tunnel (`tunnel-health.json`), la diagnostica e il registro dell'attività di rete.
- Le chiavi `UserDefaults` condivise per la sessione di protezione e lo stato di pausa. Queste fanno da alias diretto agli store di `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — così app, tunnel e intent della Live Activity condividono un'unica disposizione delle chiavi, un unico contatore di revisione e un unico schema di deduplicazione.
- La directory di cache del catalogo e il file di log di debug sul dispositivo.

L'URL del container viene risolto tramite `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Messaggio di comando / provider (il percorso di controllo)

L'app pilota il tunnel con **`sendProviderMessage`** per tutti i comandi. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) ottiene la `NETunnelProviderSession` attiva dal manager in cache e chiama `session.sendProviderMessage(...)`. Il payload viene codificato da `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) in una piccola busta JSON che porta con sé un `kind` di messaggio e un `operationID` opzionale (usato per il tracciamento della latenza end-to-end).

I tipi di messaggio riconosciuti sono costanti su `LavaSecAppGroup`:

| Costante del messaggio | Effetto nel tunnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Forza la ricarica dello snapshot di filtro compilato. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Rilegge solo lo stato di pausa condiviso. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Ricarica la configurazione; solo un cambio di *identità del resolver* provoca una riconnessione visibile. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Manutenzione di diagnostica/log. |

Sul lato tunnel, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica la busta e fa uno switch sul `kind`. In particolare, `reload-configuration` carica la nuova configurazione così che i campi non legati al resolver (interruttori di diagnostica, stato a pagamento) abbiano effetto, ma reimposta il runtime DNS e riapplica le impostazioni di rete del tunnel — una riconnessione visibile — solo quando l'identità del resolver è effettivamente cambiata (`PacketTunnelProvider.swift:768-792`). Un cambio del flag di diagnostica o dello stato a pagamento non interrompe mai la connessione attiva.

Gli helper `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` dell'app (`AppViewModel.swift:7062`/`7070`) sono sottili wrapper che inviano questi messaggi.

### Perché i messaggi del provider per il controllo app→tunnel

**`sendProviderMessage` è l'unico percorso di controllo app→tunnel — non esiste alcun segnale Darwin app→tunnel.** Un progetto precedente inviava un segnale Darwin tramite `CFNotificationCenter` alla pausa e lo osservava all'interno dell'estensione, ma non si attivava mai in modo affidabile nel processo NetworkExtension ed è stato rimosso. Il servizio dei comandi non invia più `CFNotificationCenterPostNotification` e il tunnel non aggiunge più un `CFNotificationCenterAddObserver` — l'assenza di entrambi è verificata dai test di introspezione del sorgente (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` per l'invio del servizio comandi; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` per l'observer del tunnel) per evitare che vengano reintrodotti. (Le righe `import Darwin` che restano nel servizio comandi e nel tunnel servono per le primitive `flock`/socket, non per le notifiche.)

Un percorso Darwin *esiste ancora* nella direzione opposta. Il tunnel invia all'app un avviso di cambio di salute: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) invia `CFNotificationCenterPostNotification` sul canale `com.lavasec.protection.tunnel-health-changed` (il nome del canale si trova in `TunnelHealthSignal.swift`, non in `AppGroup.swift`), e l'app lo osserva tramite `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), collegato in `AppViewModel` per chiamare `handleTunnelHealthNudge()`. La presenza di questo avviso di salute tunnel→app è verificata da `LavaLiveActivitySourceTests.swift:1059-1075`.

Per il controllo app→tunnel, la pausa viene consegnata scrivendo il `ProtectionPauseStore` condiviso e facendolo seguire dal messaggio del provider `reload-protection-pause`, così il tunnel esegue `refreshProtectionPauseStateOnly`. `AppViewModel.swift:4995-4996` documenta la regola in modo diretto: l'app "non si affida nemmeno all'observer Darwin dello snapshot, usando sempre `sendProviderMessage`." Considera la coppia App Group (stato condiviso) + `sendProviderMessage` (il segnale di sveglia/controllo) come il percorso di controllo app→tunnel.

### Servizio dei comandi della Live Activity

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) è il punto di ingresso per le azioni della Dynamic Island / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`). I `LiveActivityIntent` in `LavaLiveActivityIntents.swift` girano nel processo dell'app (che detiene l'entitlement NetworkExtension), quindi:

- **Pausa / ripresa** passano attraverso un lock di file tra processi (`protection-command.lock`, `flock`) e gli store `ProtectionPauseStore` / `ProtectionSessionStore` di `LavaSecCore`, che gestiscono la creazione delle revisioni e la deduplicazione dei comandi duplicati (il `commandID` propaga l'id di operazione del chiamante, così un comando riconsegnato non può creare una seconda revisione). L'esito programma un aggiornamento della Live Activity protetto da revisione.
- **Riconnessione** è gestita direttamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): chiama `loadAllFromPreferences` e avvia il primo manager del tunnel installato tramite `startVPNTunnel()` (poiché `loadAllFromPreferences` è già limitato alle configurazioni NE di questa app, quel primo manager è quello di Lava — a differenza di `VPNLifecycleController.matchingManagers()`, non esegue un confronto esplicito dell'identità). Connect-On-Demand è già abilitato, quindi questo si limita a forzare una connessione immediata; la riconciliazione dello stato dell'app riporta poi la Live Activity a `.on` una volta connessa.

---

## 3. Ciclo di vita e controllo della VPN

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) è la fonte di verità del ciclo di vita della VPN nell'app. Orchestra l'accensione/spegnimento, mantiene in cache il `NETunnelProviderManager` attivo e pubblica lo stato verso SwiftUI.

### Selezione del manager e calcoli del ciclo di vita

La logica di ciclo di vita riutilizzabile e priva di NetworkExtension si trova in `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). L'app fornisce le conformità basate su `NETunnelProviderManager` di `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; il controller gestisce:

- **Selezione e deduplicazione** — `matchingManagers()` filtra i manager di proprietà di Lava tramite `LavaTunnelConfigurationIdentity.matches(...)`, li ordina per `selectionPriority` (prima quelli attivi, poi per nome visualizzato canonico), e `removeDuplicateManagers(keeping:)` converge su un unico sopravvissuto.
- **Attese di connessione/arresto** — `waitForConnect` / `waitForStop` interrogano lo stato della connessione attiva con una tolleranza `startGraceInterval`, perché subito dopo `startVPNTunnel` la connessione può leggere brevemente uno stato non in attesa prima che iOS la porti in `.connecting`.

### Accensione / spegnimento

`enableProtection(...)` (`AppViewModel.swift:5764`) è **cache-first**: quando esiste un artefatto preparato e confermato riutilizzabile per la configurazione corrente, la VPN può attivarsi immediatamente dalla cache mentre una sincronizzazione del catalogo in corso continua ad aggiornare in background, e `performCatalogSync` riconcilia il tunnel attivo al completamento. Si blocca sulla sincronizzazione solo quando non c'è nulla di valido da cui partire (ad esempio l'utente ha appena cambiato l'insieme delle liste abilitate, invalidando l'identità dell'artefatto in cache).

`disableProtection(...)` (`AppViewModel.swift:5972`) disattiva Connect-On-Demand *prima* di fermare il tunnel, così iOS non lo riconnette immediatamente. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) installa una `NEOnDemandRuleConnect` (corrispondenza dell'interfaccia `.any`) e salva le preferenze — salvare (non solo impostare) è necessario perché iOS rispetti la modifica.

### Osservazione dello stato (e un avvertimento sul surriscaldamento)

`AppViewModel` osserva `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) e pubblica `vpnStatus`/`isVPNConfigurationInstalled`. Soprattutto, quando un manager è già in cache, legge la connessione attiva del manager in cache invece di forzare un aggiornamento `loadAllFromPreferences`: `loadAllFromPreferences` stesso ripubblica `NEVPNStatusDidChange`, e un aggiornamento forzato nell'observer produceva una tempesta autoalimentata — il commento nel sorgente (`AppViewModel.swift:1046-1048`) registra i circa 370 eventi/s misurati e la regressione di surriscaldamento al 134% di CPU che causava. Le proprietà pubblicate cambiano solo su transizioni reali, così i tick a riposo smettono di invalidare SwiftUI.

### Riconciliazione fail-closed on-demand

Connect-On-Demand può attivare il tunnel **a freddo** all'avvio (o dopo che iOS lo smonta a seguito di un cambio di rete) prima che l'app abbia inviato uno snapshot. Un tunnel a freddo senza uno snapshot persistente riutilizzabile si carica in modalità **fail-closed** — blocca tutto il traffico — e non recupera da solo. `AppViewModel` gestisce questo in due percorsi di avvio, entrambi vincolati al completamento dell'onboarding (`hasCompletedOnboarding`, che rispecchia il flag `@AppStorage("hasSeenLavaOnboarding")`):

- **Dopo l'onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) viene eseguito ogni volta che la protezione è attiva all'avvio: prepara lo snapshot di avvio, persiste lo stato condiviso e invia `reload-snapshot` così il tunnel ricarica le sue regole reali uscendo dal fail-closed. Il fail-closed resta il valore predefinito sicuro; questo si limita a sostituirlo prontamente. (Risolve i filtri mostrati in rosso / il traffico bloccato dopo un riavvio dell'app mentre Connect-On-Demand mantiene il tunnel attivo.)
- **Durante l'onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) viene eseguito *prima* di qualsiasi attività di rete quando l'onboarding non è terminato. iOS non rimuove sempre in modo affidabile un profilo VPN alla disinstallazione dell'app, quindi una reinstallazione può ereditare una configurazione orfana con on-demand abilitato che attiva un tunnel a freddo in fail-closed prima che l'utente abbia scelto qualsiasi blocklist. Questo percorso **rimuove** la configurazione (`removeFromPreferences`) invece di salvarne una modifica — `saveToPreferences` rimostrerebbe il prompt di sistema "Add VPN Configurations" su un profilo che questa installazione non possiede, facendo apparire la finestra di dialogo all'avvio dell'app prima che venga mostrato il foglio di onboarding. È un'operazione senza effetto su un'installazione pulita e quando la configurazione ereditata è già inerte.

---

## 4. Guardian / modello di stato

Esistono due vocabolari di stato correlati: una *valutazione* della connettività e uno stato del *mascotte* Guardian.

### Valutazione della connettività

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) mappa uno `TunnelHealthSnapshot` su un `ProtectionConnectivityAssessment` con una delle **sei gravità** e **due azioni**:

- Gravità: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Azioni primarie: `turnOff` o `reconnect`.

Questa singola valutazione guida sia la superficie Guard nell'app sia (con un'ulteriore mappatura) lo stato della Dynamic Island, così le due non sono mai in disaccordo.

### Stati del mascotte Guardian

Il mascotte Soft Shield Guardian ha esattamente **sette** stati emotivi — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Ogni stato dichiara i suoi `allowedNextStates`, così le transizioni sono vincolate (ad esempio `grateful` torna solo ad `awake`; `GuardianMascotAnimation.swift:12-29`). Semantica:

- `retrying` = auto-riparazione tranquilla.
- `concerned` = richiesta di aiuto delicata.
- `grateful` = successo celebrativo (usato nelle superfici di onboarding/impostazioni, non nella mappa della connettività).

`GuardianMascotAnimation` è il core di animazione procedurale in `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) è il rendering SwiftUI e supporta le skin di personalizzazione selezionate da `GuardianShieldStyle` (nomi visualizzati Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, con la mappatura `displayName` alle righe 18-35). Alcuni valori grezzi divergono dai loro nomi visualizzati (ad esempio `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"` e `purpleObsidian` viene reso come "Amethyst"), quindi persisti il valore grezzo, non l'etichetta.

### Come si collegano i due

Il `LavaActivityAttributes.ProtectionState` della Live Activity (`Shared/LavaActivityAttributes.swift`) fa da ponte tra la valutazione e uno stato del mascotte tramite `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). `AppViewModel` sceglie lo stato di protezione per la Dynamic Island dalla stessa `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): una gravità `networkUnavailable` diventa `.networkUnavailable`, `recovering` diventa `.reconnecting`, un'azione primaria `reconnect` diventa `.needsReconnect` e altrimenti `.on`.

> Nota: `LavaTier` (l'enum di profondità del design system calmo → **Floor** / celebrativo → **Window** / tecnico → **Workshop**) viene distribuito nel livello del design system (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), collegato a superfici rappresentative — vedi [il design system](../design-system/overview.md). Governa la profondità del design system, non il percorso del client di protezione/tunnel descritto qui.

---

## 5. Live Activity e widget

Il target del widget esegue il rendering solo della Live Activity e della Dynamic Island. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) espone un singolo `LavaProtectionLiveActivityWidget`, un `ActivityConfiguration(for: LavaActivityAttributes.self)` con:

- Una vista per la schermata di blocco, una regione centrale espansa della Dynamic Island e presentazioni compatte/minime che rendono `SoftShieldGuardian` più un glifo di stato. Le viste compatte/di blocco ricalcolano lo stato di protezione *effettivo* su una `TimelineView` al secondo, così il conto alla rovescia di una pausa resta aggiornato senza bisogno di una push.

`LavaActivityAttributes.ContentState` porta con sé `protectionState`, una `resumeDate` (per i conti alla rovescia delle pause), `pauseRequiresAuthentication` e lo `shieldStyle` scelto. La decodifica è tollerante — uno `shieldStyle` mancante ricade su `.original` — così i payload più vecchi della Live Activity continuano a funzionare.

Sul lato app, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) possiede l'`Activity<LavaActivityAttributes>` attiva: osserva i cambi di autorizzazione di ActivityKit, offre Live Activity solo sugli idiomi telefono/tablet e `reconcile(...)` avvia/aggiorna/termina l'activity per allinearla allo stato di protezione richiesto. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) è l'unico imbuto che ricalcola lo stato desiderato e chiama il controller. I pulsanti della Dynamic Island inviano dei `LiveActivityIntent`, che chiamano `LavaProtectionCommandService` come descritto nel [§2](#2-app-extension-ipc).

---

## 6. Flusso di onboarding

L'onboarding è presentato da `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) ed è regolato dal flag `@AppStorage("hasSeenLavaOnboarding")` dichiarato in `RootView` (`RootView.swift:32`). Il flusso è una sequenza di `OnboardingPage` (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

La configurazione di partenza distribuita proviene da `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` abilita solo le fonti consigliate permissive (Block List Project Phishing + Scam), seleziona **Device DNS** come resolver — `DNSResolverPreset.device` (id `device-dns`), il DNS della rete stessa; i preset cifrati come Google DoH sono opzionali e non vengono promossi come predefiniti — abilita il fallback su Device DNS e mantiene attivo il logging locale — con `protectionEnabled: false`, così la protezione viene attivata solo quando l'utente la sceglie. `OnboardingDefaultsSummary` formatta queste scelte per la visualizzazione ("Continua senza account" è l'impostazione predefinita dell'account).

Impostare `hasSeenLavaOnboarding = true` alla fine è ciò che fa scattare `hasCompletedOnboarding`, che a sua volta arma il percorso di riconciliazione all'avvio descritto nel [§3](#3-vpn-lifecycle-control). Fino ad allora, il percorso di neutralizzazione durante l'onboarding impedisce a qualsiasi tunnel fail-closed ereditato di bloccare il traffico.

---

## 7. Stato dell'app: `AppViewModel`

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) è il proprietario centrale dello stato lato app. Oltre al ciclo di vita della VPN, pubblica le superfici a cui l'interfaccia si lega, tra cui:

- **Protezione e tunnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil` e i messaggi rivolti all'utente `vpnMessage`/`vpnMessageIsError`.
- **Configurazione e catalogo** — l'`AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt` e i conteggi delle regole compilate (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnostica** — `DiagnosticsStore` e `NetworkActivityLog` (tutto locale; vedi la promessa sulla privacy più sotto).
- **Account e backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled` e lo stato delle offerte/diritti di **Lava Security Plus**.
- **Personalizzazione e presentazione** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress` e `usesLiveActivities`.

Delega la serializzazione del ciclo di vita a un `protectionActionOrchestrator` (così un ripristino in background non si intreccia con un'accensione da parte dell'utente), mantiene il `tunnelManager` in cache e guida tutte le modifiche di snapshot/configurazione/pausa verso l'estensione tramite gli helper dei messaggi del provider del [§2](#2-app-extension-ipc).

> **Inquadramento sulla privacy.** Il filtraggio DNS avviene localmente su questo dispositivo. Le superfici di diagnostica e di attività di rete che `AppViewModel` pubblica sono memorizzate solo localmente — Lava non riceve mai le tue normali richieste DNS, la cronologia di navigazione o telemetria per dominio. Qualsiasi backup opzionale dell'account è **a conoscenza zero** (cifrato sul dispositivo; Lava può solo memorizzare testo cifrato), incluso il recupero basato su passkey — la sua chiave è derivata tramite PRF sul dispositivo, senza alcun segreto custodito dal server. Vedi [Panoramica del sistema](./system-overview.md) per il confine lato server.

---

## Documenti correlati

- [Panoramica del sistema](./system-overview.md) — l'intero sistema in una schermata: l'app, il Worker del catalogo e Supabase, più i confini di fiducia e la legenda di stato usata in tutto il documento.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — i dettagli interni del tunnel a pacchetti, qui richiamati solo al confine di controllo: il motore di filtraggio compilato, i trasporti cifrati del resolver (DoH / DoH3 / DoT / DoQ), il budget delle regole di filtro, il catalogo delle blocklist e il modello di ridistribuzione basato solo sull'url della fonte.
- [Account e backup a conoscenza zero](./accounts-and-backup.md) — i provider di accesso e la busta di backup a conoscenza zero che `AppViewModel` orchestra (incluso lo slot di recupero passkey a conoscenza zero, derivato tramite PRF).
- [Backend e dati](./backend-and-data.md) — il Worker del catalogo `lavasec-api`, Cloudflare R2 e lo schema/RLS di Supabase che si trovano dall'altra parte del confine app↔server.
- [Design System](../design-system/overview.md) — il modello di profondità `LavaTier`, i sette stati del Soft Shield Guardian e le skin dello scudo, e le convenzioni di testo/localizzazione che il client rende.
- [Avvisi di terze parti](../legal/third-party-notices.md) e [Decisione di conformità GPL basata solo sull'url della fonte](../legal/gpl-source-url-only-compliance-decision.md) — i vincoli di distribuzione dietro la pipeline catalogo/filtro che il client consuma.
