---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Architettura del client iOS

> Pubblico: ingegneri iOS che lavorano in `lavasec-ios`.

Lava Security è un'app iOS che mette la privacy al primo posto e filtra il DNS in locale sul dispositivo tramite un tunnel di pacchetti NetworkExtension on-device, bloccando i domini noti come rischiosi e indesiderati senza far passare la tua navigazione attraverso i server di Lava. Questo documento spiega come è strutturato il client iOS: i target, come l'app comunica con la sua estensione tunnel, il ciclo di vita della VPN, il modello di stato del Guardian, la Live Activity e il widget, il flusso di onboarding e il responsabile dello stato lato app (`AppViewModel`).

Per una visione dell'intero sistema (l'app, il Worker del catalogo e Supabase), vedi [Panoramica del sistema](./system-overview.md).

---

## 1. Target e responsabilità

Il client viene distribuito come tre target eseguibili più una libreria core condivisa. Tutti e tre i target fanno parte dello stesso **App Group** (`group.com.lavasec`) e collegano `LavaSecCore`.

| Target | Bundle id | Responsabilità |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | L'app SwiftUI. Possiede la UI, detiene l'entitlement NetworkExtension e controlla il tunnel tramite `NETunnelProviderManager`. `AppViewModel` è la fonte di verità del ciclo di vita della VPN. |
| **Tunnel di pacchetti** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | La sottoclasse di `NEPacketTunnelProvider` chiamata `PacketTunnelProvider` (alias `LavaSecTunnel`). Analizza i pacchetti DNS, estrae il dominio interrogato, lo valuta rispetto allo snapshot compilato memory-mapped e inoltra a monte le query consentite. È limitata dal tetto di memoria jetsam per processo di circa 50 MiB. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Un `WidgetBundle` il cui unico membro è `LavaProtectionLiveActivityWidget` — la presentazione Live Activity / Dynamic Island. |

Il codice condiviso vive in due posti:

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — il core indipendente dalla piattaforma: il motore di filtraggio, i transport del resolver, la matematica di snapshot/budget, gli store di protezione e il core `GuardianMascotAnimation`. Come indicato in `VPNLifecycleController.swift:3-6`, i tipi NetworkExtension sono volutamente tenuti fuori da questo modulo affinché la sua logica di ciclo di vita resti testabile con fake; il target app fornisce le conformità supportate da `NetworkExtension`.
- **`Shared/`** — codice compilato in più di un target (ad es. `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

I dettagli interni del tunnel di pacchetti (analisi DNS, snapshot compilato, transport cifrati del resolver e budget delle regole di filtro) sono trattati in profondità in [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md). Questo documento si concentra sull'architettura lato app e sul confine tra l'app e l'estensione.

---

## 2. IPC app ↔ estensione {#2-app-extension-ipc}

L'app e l'estensione tunnel di pacchetti sono processi separati. Si coordinano tramite tre meccanismi, tutti ancorati all'App Group.

### Container dell'App Group

`group.com.lavasec` è il container condiviso che consente all'app, al tunnel e al widget di leggere e scrivere lo stesso stato e la stessa configurazione di `LavaSecCore`. `LavaSecAppGroup` (`Shared/AppGroup.swift`) centralizza ogni chiave e nome file condivisi affinché i processi non possano mai divergere sulle costanti stringa, tra cui:

- Gli artefatti dello snapshot compilato (`filter-snapshot.compact`, `filter-snapshot.json`), il `app-configuration.json` serializzato, lo stato di salute del tunnel (`tunnel-health.json`), la diagnostica e il log dell'attività di rete.
- Le chiavi condivise di `UserDefaults` per la sessione di protezione e lo stato di pausa. Queste fanno da alias diretto agli store di `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — così che app, tunnel e intent della Live Activity condividano un unico layout di chiavi, un unico contatore di revisione e un unico schema di deduplica.
- La directory di cache del catalogo e il file di log di debug on-device.

L'URL del container è risolto tramite `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Messaggio di comando / provider (il percorso di controllo)

L'app pilota il tunnel con **`sendProviderMessage`** per tutti i comandi. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) ottiene la `NETunnelProviderSession` attiva dal manager in cache e chiama `session.sendProviderMessage(...)`. Il payload viene codificato da `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) in una piccola busta JSON che trasporta un `kind` di messaggio e un `operationID` opzionale (usato per il tracciamento della latenza end-to-end).

I tipi di messaggio riconosciuti sono costanti su `LavaSecAppGroup`:

| Costante di messaggio | Effetto nel tunnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Forza la ricarica dello snapshot di filtro compilato. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Rilegge soltanto lo stato di pausa condiviso. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Ricarica la configurazione; solo un cambio di *identità del resolver* innesca una riconnessione visibile. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Manutenzione di diagnostica/log. |

Dal lato del tunnel, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica la busta e fa lo switch su `kind`. In particolare, `reload-configuration` carica la nuova configurazione affinché i campi non legati al resolver (interruttori della diagnostica, stato a pagamento) abbiano effetto, ma reimposta il runtime DNS e riapplica le impostazioni di rete del tunnel — una riconnessione visibile — solo quando l'identità del resolver è effettivamente cambiata (`PacketTunnelProvider.swift:768-792`). Un cambio di flag di diagnostica o di stato a pagamento non interrompe mai la connessione attiva.

Gli helper `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` dell'app (`AppViewModel.swift:7062`/`7070`) sono sottili wrapper che inviano questi messaggi.

### Perché i messaggi del provider per il controllo app→tunnel

**`sendProviderMessage` è l'unico percorso di controllo app→tunnel — non esiste un segnale Darwin app→tunnel.** Un progetto precedente pubblicava un segnale Darwin `CFNotificationCenter` in pausa e lo osservava all'interno dell'estensione, ma non si attivava mai in modo affidabile nel processo NetworkExtension ed è stato rimosso. Il command service non pubblica più `CFNotificationCenterPostNotification`, e il tunnel non aggiunge più un `CFNotificationCenterAddObserver` — entrambi vengono verificati come assenti dai test di introspezione del sorgente (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` per il post del command service; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` per l'observer del tunnel) per evitarne la reintroduzione. (Le righe `import Darwin` che restano nel command service e nel tunnel servono per le primitive `flock`/socket, non per le notifiche.)

Un percorso Darwin *esiste* ancora nella direzione opposta. Il tunnel pubblica all'app un avviso di cambiamento dello stato di salute: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) pubblica `CFNotificationCenterPostNotification` sul canale `com.lavasec.protection.tunnel-health-changed` (il nome del canale vive in `TunnelHealthSignal.swift`, non in `AppGroup.swift`), e l'app lo osserva tramite `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), collegato in `AppViewModel` per chiamare `handleTunnelHealthNudge()`. Questo avviso di salute tunnel→app viene verificato come *presente* da `LavaLiveActivitySourceTests.swift:1059-1075`.

Per il controllo app→tunnel, la pausa viene consegnata scrivendo il `ProtectionPauseStore` condiviso e facendola seguire dal messaggio del provider `reload-protection-pause` affinché il tunnel esegua `refreshProtectionPauseStateOnly`. `AppViewModel.swift:4995-4996` documenta la regola direttamente: l'app "non si affida mai nemmeno all'observer Darwin dello snapshot, usando sempre `sendProviderMessage`." Considera la coppia App Group (stato condiviso) + `sendProviderMessage` (il segnale di risveglio/controllo) come il percorso di controllo app→tunnel.

### Command service della Live Activity

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) è il punto di ingresso per le azioni Dynamic Island / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`). I `LiveActivityIntent` in `LavaLiveActivityIntents.swift` vengono eseguiti nel processo dell'app (che detiene l'entitlement NetworkExtension), quindi:

- **Pausa / ripresa** passano attraverso un file lock cross-process (`protection-command.lock`, `flock`) e i `ProtectionPauseStore` / `ProtectionSessionStore` di `LavaSecCore`, che gestiscono la generazione delle revisioni e la deduplica dei comandi duplicati (il `commandID` instrada l'id operazione del chiamante affinché un comando riconsegnato non possa generare una seconda revisione). L'esito pianifica un aggiornamento della Live Activity protetto da revisione.
- **Riconnessione** è gestita direttamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): chiama `loadAllFromPreferences` e avvia il primo manager del tunnel installato tramite `startVPNTunnel()` (poiché `loadAllFromPreferences` è già limitato alle configurazioni NE di questa app, quel primo manager è quello di Lava — a differenza di `VPNLifecycleController.matchingManagers()`, non esegue un controllo esplicito dell'identità). Connect-On-Demand è già abilitato, quindi questo forza solo una connessione immediata; la riconciliazione dello stato dell'app riporta poi la Live Activity a `.on` una volta connessa.

---

## 3. Ciclo di vita e controllo della VPN {#3-vpn-lifecycle-control}

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) è la fonte di verità del ciclo di vita della VPN nell'app. Orchestra l'accensione/spegnimento, mette in cache il `NETunnelProviderManager` attivo e pubblica lo stato a SwiftUI.

### Selezione del manager e matematica del ciclo di vita

La logica di ciclo di vita riutilizzabile e priva di NetworkExtension vive in `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). L'app fornisce le conformità supportate da `NETunnelProviderManager` di `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; il controller gestisce:

- **Selezione e deduplica** — `matchingManagers()` filtra ai manager di proprietà di Lava tramite `LavaTunnelConfigurationIdentity.matches(...)`, li ordina per `selectionPriority` (prima quelli attivi, poi per nome visualizzato canonico), e `removeDuplicateManagers(keeping:)` converge su un unico sopravvissuto.
- **Attese di connessione/arresto** — `waitForConnect` / `waitForStop` sondano lo stato della connessione attiva con una tolleranza `startGraceInterval`, perché subito dopo `startVPNTunnel` la connessione può brevemente leggere uno stato non in attesa prima che iOS la faccia transitare a `.connecting`.

### Accensione / spegnimento

`enableProtection(...)` (`AppViewModel.swift:5764`) è **cache-first**: quando esiste un artefatto preparato confermato come riutilizzabile per la configurazione corrente, la VPN può attivarsi immediatamente dalla cache mentre una sincronizzazione del catalogo in corso continua ad aggiornare in background, e `performCatalogSync` riconcilia il tunnel in esecuzione al completamento. Si blocca sulla sincronizzazione solo quando non c'è nulla di valido da cui partire (ad es. l'utente ha appena cambiato l'insieme di elenchi abilitati, invalidando l'identità dell'artefatto in cache).

`disableProtection(...)` (`AppViewModel.swift:5972`) disattiva Connect-On-Demand *prima* di fermare il tunnel affinché iOS non lo riconnetta immediatamente. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) installa un `NEOnDemandRuleConnect` (match dell'interfaccia `.any`) e salva le preferenze — il salvataggio (non il semplice setting) è necessario perché iOS rispetti la modifica.

### Osservazione dello stato (e un'avvertenza sul calore)

`AppViewModel` osserva `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) e pubblica `vpnStatus`/`isVPNConfigurationInstalled`. Cosa fondamentale, quando un manager è già in cache, legge la connessione attiva del manager in cache anziché forzare un refresh `loadAllFromPreferences`: `loadAllFromPreferences` ripubblica esso stesso `NEVPNStatusDidChange`, e un refresh forzato nell'observer produceva una tempesta auto-sostenuta — il commento nel sorgente (`AppViewModel.swift:1046-1048`) registra i circa 370 eventi/s misurati e la regressione di calore con il 134% di CPU che ha causato. Le proprietà pubblicate cambiano solo su transizioni reali, così i tick a riposo smettono di invalidare SwiftUI.

### Riconciliazione on-demand fail-closed

Connect-On-Demand può attivare il tunnel **a freddo** all'avvio (o dopo che iOS lo smonta a un cambio di rete) prima che l'app abbia inviato uno snapshot. Un tunnel a freddo senza uno snapshot persistito riutilizzabile si carica **fail-closed** — blocca tutto il traffico — e non si riprende mai da solo. `AppViewModel` gestisce questo in due percorsi di avvio, entrambi condizionati al completamento dell'onboarding (`hasCompletedOnboarding`, che rispecchia il flag `@AppStorage("hasSeenLavaOnboarding")`):

- **Dopo l'onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) viene eseguito ogni volta che la protezione è attiva all'avvio: prepara lo snapshot di avvio, persiste lo stato condiviso e invia `reload-snapshot` affinché il tunnel ricarichi le sue regole reali uscendo dal fail-closed. Il fail-closed rimane l'impostazione predefinita sicura; questo lo sostituisce solo prontamente. (Risolve i filtri mostrati in rosso / traffico bloccato dopo un riavvio dell'app mentre Connect-On-Demand mantiene il tunnel attivo.)
- **A metà onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) viene eseguito *prima* di qualsiasi lavoro di rete quando l'onboarding non è terminato. iOS non rimuove in modo affidabile un profilo VPN alla disinstallazione dell'app, quindi una reinstallazione può ereditare una configurazione orfana con on-demand abilitato che attiva un tunnel a freddo fail-closed prima che l'utente abbia scelto alcuna blocklist. Questo percorso **rimuove** la configurazione (`removeFromPreferences`) anziché salvarne una modifica — `saveToPreferences` rimostrerebbe il prompt di sistema "Aggiungi configurazioni VPN" su un profilo che questa installazione non possiede, facendo apparire la finestra all'init dell'app prima che venga visualizzato il foglio di onboarding. È un no-op su un'installazione pulita e quando la configurazione ereditata è già inerte.

---

## 4. Guardian / modello di stato

Esistono due vocabolari di stato correlati: una *valutazione* di connettività e uno stato del *mascotte* Guardian.

### Valutazione della connettività

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) mappa un `TunnelHealthSnapshot` su un `ProtectionConnectivityAssessment` con una delle **sei gravità** e **due azioni**:

- Gravità: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Azioni primarie: `turnOff` o `reconnect`.

Questa singola valutazione pilota sia la superficie Guard in-app sia (mappata ulteriormente) lo stato Dynamic Island, così i due non sono mai in disaccordo.

**Soglia di onestà (v1.0).** Un fallimento attuale e non coperto del probe smoke DNS non può mai essere letto come `.healthy` — la valutazione mostra `.recovering` finché un probe non riesce davvero, così il traffico portato da fallback su un primario incastrato non viene più dipinto come "Protetto." La logica di riconnessione si basa su `consecutiveDNSSmokeProbeFailureCount` e `lastPrimaryUpstreamSuccessAt` (solo primario) anziché sui contatori upstream generici, e un resolver che resta raggiungibile ma continua a **rifiutare** il probe noto come buono (hijack/captive/stale) viene escalato a livello di riavvio tramite un `consecutiveRejectedSmokeResponseCount` con ambito all'identità del resolver (LAV-87), anche quando la serie generica continua a resettarsi su reti in roaming instabili.

### Notifiche di connettività

`ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`) trasforma la valutazione in al massimo una notifica locale in sospeso, con throttling (600s) e deduplica. La v1.0 aggiunge:

- Un tipo **`dnsSlow`** distinto ("Il DNS di Lava è lento") — il DNS lento riutilizzava il tipo `reconnectNeeded`, così un'interruzione reale non poteva sostituirlo.
- **Escalation/sostituzione** — un problema decisamente più urgente (solo `reconnectNeeded` supera gli altri) può sostituire un banner in essere di rango inferiore, aggirando sia la guardia "problema già in sospeso" sia il throttle, così un incaglio dopo un fallback su Device-DNS fa emergere il prompt "Riconnetti" azionabile invece di lasciare in piedi un banner rassicurante.
- Una **migrazione di persistenza** (`ProtectionConnectivityNotificationStore`, schema v2, collegata tramite `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) declassa un marker legacy `reconnect-needed` in sospeso a `dnsSlow` affinché l'escalation funzioni attraverso l'aggiornamento.

### Retry della cattura Device-DNS

Quando la configurazione attiva dipende dal resolver del dispositivo (come primario o come fallback), un handoff/risveglio di rete può lasciare il tunnel con una cattura del resolver di sistema vuota — un incaglio silenzioso. `DeviceDNSFallbackPolicy` pilota un **retry limitato** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1s, `deviceDNSCaptureMaxRetryAttempts` 5): il tunnel rilegge i resolver di sistema ogni secondo per un massimo di cinque tentativi finché la cattura non è non vuota, quindi la adotta sul posto — auto-ripristinandosi senza un riavvio del tunnel (eventi `device-dns-capture-retry` / `-exhausted`). È un no-op per configurazioni DoH/DoT/DoQ pure (`currentConfigurationDependsOnDeviceDNS()`).

### Stati del mascotte Guardian

Il mascotte Soft Shield Guardian ha esattamente **sette** stati emotivi — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Ogni stato dichiara i propri `allowedNextStates` così che le transizioni siano vincolate (ad es. `grateful` torna solo a `awake`; `GuardianMascotAnimation.swift:12-29`). Semantica:

- `retrying` = auto-guarigione tranquilla.
- `concerned` = richiesta di aiuto gentile.
- `grateful` = successo da festeggiare (usato sulle superfici di onboarding/impostazioni, non sulla mappa di connettività).

`GuardianMascotAnimation` è il core dell'animazione procedurale in `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) è il rendering SwiftUI e supporta gli skin di personalizzazione selezionati da `GuardianShieldStyle` (nomi visualizzati Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, con il mapping del `displayName` alle righe 18-35). Alcuni valori grezzi divergono dai loro nomi visualizzati (ad es. `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, e `purpleObsidian` viene reso come "Amethyst"), quindi persisti il valore grezzo, non l'etichetta.

### Come i due si collegano

Il `LavaActivityAttributes.ProtectionState` della Live Activity (`Shared/LavaActivityAttributes.swift`) collega la valutazione a uno stato del mascotte tramite `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). `AppViewModel` sceglie lo stato di protezione per la Dynamic Island dallo stesso `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): una gravità `networkUnavailable` diventa `.networkUnavailable`, `recovering` diventa `.reconnecting`, un'azione primaria `reconnect` diventa `.needsReconnect`, e altrimenti `.on`.

> Nota: `LavaTier` (l'enum di profondità del design system: calmo → **Floor** / festoso → **Window** / tecnico → **Workshop**) è distribuito nel layer del design system (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), collegato a superfici rappresentative — vedi [il design system](../design-system/overview.md). Governa la profondità del design system, non il percorso del client di protezione/tunnel descritto qui.

---

## 5. Live Activity e widget

Il target widget esegue il rendering solo della Live Activity e della Dynamic Island. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) espone un singolo `LavaProtectionLiveActivityWidget`, un `ActivityConfiguration(for: LavaActivityAttributes.self)` con:

- Una vista per la schermata di blocco, una regione centrale espansa della Dynamic Island e presentazioni compatte/minimali che eseguono il rendering di `SoftShieldGuardian` più un glifo di stato. Le viste compatte/lock ricalcolano lo stato di protezione *effettivo* su un `TimelineView` al secondo così che un conto alla rovescia di pausa resti aggiornato senza un push.

`LavaActivityAttributes.ContentState` trasporta `protectionState`, un `resumeDate` (per i conti alla rovescia di pausa), `pauseRequiresAuthentication` e lo `shieldStyle` scelto. La decodifica è tollerante — uno `shieldStyle` mancante ricade su `.original` — così i payload più vecchi della Live Activity continuano a funzionare.

Dal lato app, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) possiede l'`Activity<LavaActivityAttributes>` attiva: osserva i cambiamenti di autorizzazione di ActivityKit, offre le Live Activity solo sugli idiomi phone/pad, e `reconcile(...)` avvia/aggiorna/termina l'attività per corrispondere allo stato di protezione richiesto. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) è l'unico imbuto che ricalcola lo stato desiderato e chiama il controller. I pulsanti della Dynamic Island inviano i `LiveActivityIntent`, che chiamano `LavaProtectionCommandService` come descritto in [§2](#2-app-extension-ipc).

---

## 6. Flusso di onboarding

L'onboarding è presentato da `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) ed è regolato dal flag `@AppStorage("hasSeenLavaOnboarding")` dichiarato in `RootView` (`RootView.swift:32`). Il flusso è una sequenza di `OnboardingPage` (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

La configurazione iniziale distribuita proviene da `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` abilita solo le fonti consigliate permissive (Block List Project Phishing + Scam), seleziona **Device DNS** come resolver — `DNSResolverPreset.device` (id `device-dns`), il DNS proprio della rete; i preset cifrati come Google DoH sono opt-in e non vengono promossi a predefiniti — abilita il fallback su device-DNS, e mantiene attivo il logging locale — con `protectionEnabled: false`, così la protezione viene attivata solo quando l'utente la sceglie. `OnboardingDefaultsSummary` formatta queste scelte per la visualizzazione ("Continua senza account" è l'impostazione predefinita dell'account).

Impostare `hasSeenLavaOnboarding = true` alla fine è ciò che fa scattare `hasCompletedOnboarding`, che a sua volta arma il percorso di riconciliazione all'avvio descritto in [§3](#3-vpn-lifecycle-control). Fino ad allora, il percorso di neutralizzazione a metà onboarding impedisce a qualsiasi tunnel fail-closed ereditato di bloccare il traffico.

---

## 7. Stato dell'app: `AppViewModel`

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) è il responsabile centrale dello stato lato app. Oltre al ciclo di vita della VPN, pubblica le superfici a cui la UI si lega, tra cui:

- **Protezione e tunnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, e i `vpnMessage`/`vpnMessageIsError` rivolti all'utente.
- **Configurazione e catalogo** — l'`AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, e i conteggi delle regole compilate (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnostica** — `DiagnosticsStore` e `NetworkActivityLog` (tutto locale; vedi la promessa sulla privacy più sotto).
- **Account e backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, e lo stato di offerte/entitlement di **Lava Security Plus**.
- **Personalizzazione e presentazione** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress`, e `usesLiveActivities`.

Delega la serializzazione del ciclo di vita a un `protectionActionOrchestrator` (così un ripristino in background non si intreccia con un'accensione da parte dell'utente), detiene il `tunnelManager` in cache, e pilota tutte le modifiche di snapshot/configurazione/pausa verso l'estensione tramite gli helper dei messaggi del provider in [§2](#2-app-extension-ipc).

> **Inquadramento sulla privacy.** Il filtraggio DNS avviene in locale su questo dispositivo. Le superfici di diagnostica e attività di rete che `AppViewModel` pubblica sono archiviate solo in locale — Lava non riceve mai le tue query DNS di routine, la cronologia di navigazione o la telemetria per dominio. Qualsiasi backup di account opzionale è **a conoscenza zero** (cifrato sul dispositivo; Lava può solo archiviare testo cifrato), incluso il recupero basato su passkey — la sua chiave è derivata via PRF sul dispositivo senza alcun segreto detenuto dal server. Vedi [Panoramica del sistema](./system-overview.md) per il confine del server.

---

## Documenti correlati

- [Panoramica del sistema](./system-overview.md) — l'intero sistema su una sola schermata: l'app, il Worker del catalogo e Supabase, oltre ai confini di fiducia e alla legenda di stato usata ovunque.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — i dettagli interni del tunnel di pacchetti qui richiamati solo al confine di controllo: il motore di filtraggio compilato, i transport cifrati del resolver (DoH / DoH3 / DoT / DoQ), il budget delle regole di filtro, il catalogo delle blocklist e il modello di ridistribuzione basato solo su source-url.
- [Account e backup a conoscenza zero](./accounts-and-backup.md) — i provider di accesso e la busta di backup a conoscenza zero che `AppViewModel` orchestra (incluso lo slot di recupero passkey derivato via PRF, a conoscenza zero).
- [Backend e dati](./backend-and-data.md) — il Worker del catalogo `lavasec-api`, Cloudflare R2, e lo schema/RLS Supabase che stanno dall'altro lato del confine app↔server.
- [Design System](../design-system/overview.md) — il modello di profondità `LavaTier`, i sette stati del Soft Shield Guardian e gli skin dello scudo, e le convenzioni di copy/localizzazione che il client esegue.
- [Avvisi di terze parti](../legal/third-party-notices.md) e [Decisione di conformità GPL basata solo su source-url](../legal/gpl-source-url-only-compliance-decision.md) — i vincoli di distribuzione dietro la pipeline catalogo/filtro che il client consuma.
