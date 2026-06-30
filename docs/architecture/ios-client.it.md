---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Architettura del client iOS

> Destinatari: ingegneri iOS che lavorano in `lavasec-ios`.

Lava Security è un'app iOS privacy-first che filtra il DNS localmente sul dispositivo tramite un packet tunnel NetworkExtension on-device, bloccando i domini rischiosi e indesiderati noti senza instradare la tua navigazione attraverso i server di Lava. Questo documento illustra come è strutturato il client iOS: i target, il confine app-tunnel, il ciclo di vita della VPN, il modello di stato Guardian, la Live Activity e il widget, il flusso di onboarding e il proprietario dello stato lato app (`AppViewModel`).

Per la visione d'insieme dell'intero sistema (l'app, il Worker del catalogo e Supabase), vedi [Panoramica del sistema](./system-overview.md).

---

## 1. Target e responsabilità

Il client viene distribuito come tre target eseguibili più una libreria core condivisa. Tutti e tre i target appartengono allo stesso **App Group** (`group.com.lavasec`) e collegano `LavaSecCore`.

| Target | Bundle id | Responsabilità |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | L'app SwiftUI. Possiede l'interfaccia utente, detiene l'entitlement NetworkExtension e controlla il tunnel tramite `NETunnelProviderManager`. `AppViewModel` è la fonte di verità del ciclo di vita della VPN. |
| **Packet tunnel** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | La sottoclasse `NEPacketTunnelProvider` `PacketTunnelProvider` (alias `LavaSecTunnel`). Analizza i pacchetti DNS, estrae il dominio interrogato, lo valuta rispetto allo snapshot compilato memory-mapped e inoltra a monte le query consentite. Limitata dal tetto di memoria jetsam per-processo di ~50 MiB. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Un `WidgetBundle` il cui unico membro è `LavaProtectionLiveActivityWidget` — la presentazione Live Activity / Dynamic Island. |

Il codice condiviso risiede in due punti:

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — il core indipendente dalla piattaforma: il motore di filtraggio, i transport dei resolver, la matematica di snapshot/budget, gli store di protezione e il core `GuardianMascotAnimation`. Secondo `VPNLifecycleController.swift:3-6`, i tipi NetworkExtension sono intenzionalmente tenuti fuori da questo modulo affinché la sua logica di ciclo di vita resti testabile con dei fake; il target app fornisce le conformanze basate su `NetworkExtension`.
- **`Shared/`** — codice compilato in più di un target (ad es. `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

Gli interni del packet tunnel (parsing DNS, lo snapshot compilato, i transport cifrati dei resolver e il budget delle regole di filtraggio) sono trattati in dettaglio in [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md). Questo documento si concentra sull'architettura lato app e sul confine tra l'app e l'estensione.

---

## 2. IPC App ↔ estensione

L'app e l'estensione packet tunnel sono processi separati. Si coordinano attraverso tre meccanismi, tutti ancorati all'App Group.

### Container App Group

`group.com.lavasec` è il container condiviso che permette ad app, tunnel e widget di leggere e scrivere lo stesso stato e la stessa configurazione di `LavaSecCore`. `LavaSecAppGroup` (`Shared/AppGroup.swift`) centralizza ogni chiave e nome file condivisi affinché i processi non possano mai divergere sulle costanti stringa, inclusi:

- Gli artifact dello snapshot compilato (`filter-snapshot.compact`, `filter-snapshot.json`), il file serializzato `app-configuration.json`, la salute del tunnel (`tunnel-health.json`), la diagnostica e il log dell'attività di rete.
- Le chiavi condivise di `UserDefaults` per la sessione di protezione e lo stato di pausa. Queste fanno da alias diretto agli store di `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — così che app, tunnel e intent della Live Activity condividano un unico layout di chiavi, un unico contatore di revisione e un unico schema di dedup.
- La directory cache del catalogo e il file di log di debug on-device.

L'URL del container viene risolto tramite `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Messaggio di comando / provider (il percorso di controllo)

L'app pilota il tunnel con **`sendProviderMessage`** per tutti i comandi. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) ottiene la `NETunnelProviderSession` attiva dal manager in cache e chiama `session.sendProviderMessage(...)`. Il payload viene codificato da `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) in una piccola envelope JSON che trasporta un `kind` di messaggio e un `operationID` opzionale (usato per il tracciamento della latenza end-to-end).

I tipi di messaggio riconosciuti sono costanti su `LavaSecAppGroup`:

| Costante di messaggio | Effetto nel tunnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Forza il ricaricamento dello snapshot di filtraggio compilato. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Rilegge solo lo stato di pausa condiviso. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Ricarica la config; solo un cambiamento di *identità del resolver* innesca una riconnessione visibile. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Manutenzione di diagnostica/log. |

Sul lato tunnel, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica l'envelope e fa switch su `kind`. In particolare, `reload-configuration` carica la nuova config affinché i campi non relativi al resolver (toggle di diagnostica, stato a pagamento) abbiano effetto, ma reimposta il runtime DNS e riapplica le impostazioni di rete del tunnel — una riconnessione visibile — solo quando l'identità del resolver è effettivamente cambiata (`PacketTunnelProvider.swift:768-792`). Un cambiamento di flag di diagnostica o di stato a pagamento non interrompe mai la connessione attiva.

Gli helper `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` dell'app (`AppViewModel.swift:7062`/`7070`) sono wrapper sottili che inviano questi messaggi.

### Perché i provider message per il controllo app→tunnel

**`sendProviderMessage` è l'unico percorso di controllo app→tunnel — non esiste un segnale Darwin app→tunnel.** Un design precedente pubblicava un segnale Darwin `CFNotificationCenter` alla messa in pausa e lo osservava all'interno dell'estensione, ma non si attivava mai in modo affidabile nel processo NetworkExtension ed è stato rimosso. Il command service non pubblica più `CFNotificationCenterPostNotification` e il tunnel non aggiunge più un `CFNotificationCenterAddObserver` — la loro assenza è asserita dai test di introspezione del sorgente (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` per il post del command service; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` per l'observer del tunnel) a tutela contro la reintroduzione. (Le righe `import Darwin` che rimangono nel command service e nel tunnel servono per le primitive `flock`/socket, non per le notifiche.)

Un percorso Darwin *continua* invece a essere presente nella direzione opposta. Il tunnel invia all'app un nudge di cambio salute: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) pubblica `CFNotificationCenterPostNotification` sul canale `com.lavasec.protection.tunnel-health-changed` (il nome del canale risiede in `TunnelHealthSignal.swift`, non in `AppGroup.swift`), e l'app lo osserva tramite `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), cablato in `AppViewModel` per chiamare `handleTunnelHealthNudge()`. La presenza di questo nudge di salute tunnel→app è asserita da `LavaLiveActivitySourceTests.swift:1059-1075`.

Per il controllo app→tunnel, la pausa viene consegnata scrivendo lo `ProtectionPauseStore` condiviso e facendola seguire dal provider message `reload-protection-pause` affinché il tunnel esegua `refreshProtectionPauseStateOnly`. `AppViewModel.swift:4995-4996` documenta la regola direttamente: l'app "non si affida mai nemmeno all'observer Darwin dello snapshot, usando sempre `sendProviderMessage`". Considera la coppia App Group (stato condiviso) + `sendProviderMessage` (il segnale di wake/controllo) come il percorso di controllo app→tunnel.

### Command service della Live Activity

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) è il punto di ingresso per le azioni Dynamic Island / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes` / `pause-configured` (l'unico pulsante Pausa della Live Activity, la cui durata è il valore configurato dall'utente), `resume`, `reconnect`). I `LiveActivityIntent` in `LavaLiveActivityIntents.swift` vengono eseguiti nel processo dell'app (che detiene l'entitlement NetworkExtension), quindi:

- **Pausa / ripresa** passano attraverso un file lock cross-processo (`protection-command.lock`, `flock`) e gli store `ProtectionPauseStore` / `ProtectionSessionStore` di `LavaSecCore`, che possiedono il conio delle revisioni e il dedup dei comandi duplicati (il `commandID` collega l'operation id del chiamante così che un comando riconsegnato non possa coniare una seconda revisione). L'esito programma un aggiornamento della Live Activity protetto da revisione.
- **Reconnect** è gestito direttamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): chiama `loadAllFromPreferences` e avvia il primo tunnel manager installato tramite `startVPNTunnel()` (poiché `loadAllFromPreferences` è già limitato alle configurazioni NE di questa app, quel primo manager è quello di Lava — a differenza di `VPNLifecycleController.matchingManagers()`, non esegue un match esplicito di identità). Connect-On-Demand è già abilitato, quindi questo si limita a forzare una connessione immediata; la riconciliazione dello stato dell'app riporta poi la Live Activity a `.on` una volta connessa.

---

## 3. Ciclo di vita e controllo della VPN

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) è la fonte di verità del ciclo di vita della VPN nell'app. Orchestra accensione/spegnimento, mette in cache il `NETunnelProviderManager` attivo e pubblica lo stato verso SwiftUI.

### Selezione del manager e matematica del ciclo di vita

La logica di ciclo di vita riutilizzabile e priva di NetworkExtension risiede in `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). L'app fornisce le conformanze basate su `NETunnelProviderManager` di `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; il controller gestisce:

- **Selezione e dedup** — `matchingManagers()` filtra ai manager di proprietà di Lava tramite `LavaTunnelConfigurationIdentity.matches(...)`, ordina per `selectionPriority` (prima quello attivo, poi il nome visualizzato canonico), e `removeDuplicateManagers(keeping:)` converge su un unico sopravvissuto.
- **Attese di connect/stop** — `waitForConnect` / `waitForStop` interrogano lo stato della connessione attiva con una tolleranza `startGraceInterval`, perché subito dopo `startVPNTunnel` la connessione può leggere brevemente uno stato non in attesa prima che iOS la faccia transitare a `.connecting`.

### Accensione / spegnimento

`enableProtection(...)` (`AppViewModel.swift:5764`) è **cache-first**: quando esiste un artifact preparato confermato-riutilizzabile per la configurazione corrente, la VPN può attivarsi immediatamente dalla cache mentre una sincronizzazione del catalogo in corso continua ad aggiornare in background, e `performCatalogSync` riconcilia il tunnel in esecuzione al completamento. Si blocca sulla sincronizzazione solo quando non c'è nulla di valido da cui partire (ad es. l'utente ha appena cambiato l'insieme della enabled-list, invalidando l'identità dell'artifact in cache).

`disableProtection(...)` (`AppViewModel.swift:5972`) disattiva Connect-On-Demand *prima* di fermare il tunnel così che iOS non lo riconnetta immediatamente. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) installa un `NEOnDemandRuleConnect` (match interfaccia `.any`) e salva le preferenze — il salvataggio (non il semplice settaggio) è necessario affinché iOS onori il cambiamento.

### Osservazione dello stato (e un avvertimento sul calore)

`AppViewModel` osserva `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) e pubblica `vpnStatus`/`isVPNConfigurationInstalled`. È cruciale che, quando un manager è già in cache, legga la connessione attiva del manager in cache anziché forzare un refresh di `loadAllFromPreferences`: `loadAllFromPreferences` stesso ri-posta `NEVPNStatusDidChange`, e un refresh forzato nell'observer ha prodotto una tempesta autosostenuta — il commento in-sorgente (`AppViewModel.swift:1046-1048`) registra i ~370 eventi/s misurati e la regressione di calore al 134% di CPU che ha causato. Le proprietà pubblicate cambiano solo su transizioni reali, così i tick a riposo smettono di invalidare SwiftUI.

### Riconciliazione on-demand fail-closed

Connect-On-Demand può attivare il tunnel **a freddo** all'avvio (o dopo che iOS lo smonta su un cambio di rete) prima che l'app abbia inviato uno snapshot. Un tunnel a freddo senza snapshot persistito riutilizzabile carica **fail-closed** — blocca tutto il traffico — e non si riprende mai da solo. `AppViewModel` gestisce questo in due percorsi di avvio, entrambi subordinati al completamento dell'onboarding (`hasCompletedOnboarding`, che rispecchia il flag `@AppStorage("hasSeenLavaOnboarding")`):

- **Dopo l'onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) viene eseguito ogni volta che la protezione è attiva all'avvio: prepara lo snapshot di avvio, persiste lo stato condiviso e invia `reload-snapshot` affinché il tunnel ricarichi le sue regole reali uscendo dal fail-closed. Il fail-closed resta il default sicuro; questo si limita a sostituirlo prontamente. (Risolve i filtri mostrati in rosso / traffico bloccato dopo un riavvio dell'app mentre Connect-On-Demand mantiene il tunnel attivo.)
- **A metà onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) viene eseguito *prima* di qualsiasi lavoro di rete quando l'onboarding non è terminato. iOS non rimuove in modo affidabile un profilo VPN alla cancellazione dell'app, quindi una reinstallazione può ereditare una config orfana con on-demand abilitato che attiva un tunnel a freddo fail-closed prima che l'utente abbia scelto qualsiasi blocklist. Questo percorso **rimuove** la config (`removeFromPreferences`) anziché salvarvi una modifica — `saveToPreferences` ri-mostrerebbe il prompt di sistema "Add VPN Configurations" su un profilo che questa installazione non possiede, facendo scattare la finestra all'init dell'app prima che il sheet di onboarding venga renderizzato. È un no-op su un'installazione pulita e quando la config ereditata è già inerte.

---

## 4. Modello Guardian / di stato

Esistono due vocabolari di stato correlati: una *valutazione* di connettività e uno stato *mascotte* Guardian.

### Valutazione della connettività

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) mappa un `TunnelHealthSnapshot` a una `ProtectionConnectivityAssessment` con una di **sei severità** e **due azioni**:

- Severità: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Azioni primarie: `turnOff` o `reconnect`.

Questa singola valutazione pilota sia la superficie Guard in-app sia (mappata ulteriormente) lo stato della Dynamic Island, così che le due non siano mai in disaccordo.

**Soglia di onestà (v1.0).** Un fallimento di smoke-probe DNS attuale e non coperto non può mai apparire come `.healthy` — la valutazione mostra `.recovering` finché un probe non ha effettivamente successo, così che il traffico portato dal fallback su un primario incagliato non venga più dipinto come "Protetto." La logica di reconnect si basa su `consecutiveDNSSmokeProbeFailureCount` e `lastPrimaryUpstreamSuccessAt` (solo-primario) anziché sui contatori upstream generici, e un resolver che resta raggiungibile ma continua a **rifiutare** il probe known-good (hijack/captive/stale) viene escalato a degno-di-restart tramite un `consecutiveRejectedSmokeResponseCount` con ambito identità-resolver (LAV-87), anche quando lo streak generico continua a venire azzerato su reti roaming instabili.

### Notifiche di connettività

`ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`) trasforma la valutazione in al massimo una notifica locale in sospeso, con throttling (600s) e dedup. La v1.0 aggiunge:

- Un tipo **`dnsSlow`** distinto ("Lava DNS è lento") — il DNS lento riutilizzava il tipo `reconnectNeeded`, così che un'interruzione reale non potesse sostituirlo.
- **Escalation/sostituzione** — un problema strettamente più urgente (solo `reconnectNeeded` supera gli altri) può sostituire un banner di rango inferiore già presente, bypassando sia la guardia "problema già in sospeso" sia il throttle, così che un blocco dopo un fallback su Device-DNS faccia emergere il prompt azionabile "Reconnect" anziché lasciare su un banner rassicurante.
- Una **migrazione di persistenza** (`ProtectionConnectivityNotificationStore`, schema v2, cablata tramite `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) declassa un marker legacy `reconnect-needed` in sospeso a `dnsSlow` così che l'escalation funzioni attraverso l'aggiornamento.

### Retry di cattura Device-DNS

Quando la configurazione attiva dipende dal resolver del dispositivo (come primario o come fallback), un handoff/wake di rete può lasciare il tunnel con una cattura vuota del resolver di sistema — un blocco silenzioso. `DeviceDNSFallbackPolicy` pilota un **retry limitato** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1s, `deviceDNSCaptureMaxRetryAttempts` 5): il tunnel rilegge i resolver di sistema ogni secondo per fino a cinque tentativi finché la cattura non è non vuota, poi la adotta sul posto — recuperando automaticamente senza un riavvio del tunnel (eventi `device-dns-capture-retry` / `-exhausted`). È un no-op per le config puramente DoH/DoT/DoQ (`currentConfigurationDependsOnDeviceDNS()`).

### Stati della mascotte Guardian

La mascotte Soft Shield Guardian ha esattamente **sette** stati emotivi — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Ogni stato dichiara i suoi `allowedNextStates` così che le transizioni siano vincolate (ad es. `grateful` ritorna solo ad `awake`; `GuardianMascotAnimation.swift:12-29`). Semantica:

- `retrying` = auto-guarigione calma.
- `concerned` = ricerca di aiuto gentile.
- `grateful` = successo celebrativo (usato sulle superfici di onboarding/impostazioni, non sulla mappa di connettività).

`GuardianMascotAnimation` è il core di animazione procedurale in `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) è il rendering SwiftUI e supporta le skin di personalizzazione selezionate da `GuardianShieldStyle` (nomi visualizzati Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, con il mapping `displayName` alle righe 18-35). Alcuni valori grezzi divergono dai loro nomi visualizzati (ad es. `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, e `purpleObsidian` viene reso come "Amethyst"), quindi persisti il valore grezzo, non l'etichetta.

### Come si collegano le due cose

Il `LavaActivityAttributes.ProtectionState` della Live Activity (`Shared/LavaActivityAttributes.swift`) collega la valutazione a uno stato mascotte tramite `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). `AppViewModel` sceglie lo stato di protezione per la Dynamic Island dalla stessa `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): una severità `networkUnavailable` diventa `.networkUnavailable`, `recovering` diventa `.reconnecting`, un'azione primaria `reconnect` diventa `.needsReconnect`, e altrimenti `.on`.

> Nota: `LavaTier` (l'enum di profondità del design system calmo → **Floor** / celebrativo → **Window** / tecnico → **Workshop**) è distribuito nel layer del design system (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), cablato in superfici rappresentative — vedi [il design system](../design-system/overview.md). Governa la profondità del design system, non il percorso del client di protezione/tunnel descritto qui.

---

## 5. Live Activity e widget

Il target widget renderizza solo la Live Activity e la Dynamic Island. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) espone un singolo `LavaProtectionLiveActivityWidget`, una `ActivityConfiguration(for: LavaActivityAttributes.self)` con:

- Una vista lock-screen, una regione centrale espansa della Dynamic Island, e presentazioni compact/minimal che renderizzano `SoftShieldGuardian` più un glifo di stato. Le viste compact/lock ricalcolano lo stato di protezione *effettivo* su un `TimelineView` al secondo così che un countdown di pausa resti aggiornato senza una push.

`LavaActivityAttributes.ContentState` trasporta `protectionState`, un `resumeDate` (per i countdown di pausa), `pauseRequiresAuthentication`, e lo `shieldStyle` scelto. La decodifica è tollerante — uno `shieldStyle` mancante ricade su `.original` — così che i payload più vecchi della Live Activity continuino a funzionare.

Sul lato app, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) possiede l'`Activity<LavaActivityAttributes>` attiva: osserva i cambiamenti di autorizzazione di ActivityKit, offre le Live Activity solo sugli idiom phone/pad, e `reconcile(...)` avvia/aggiorna/termina l'activity per corrispondere allo stato di protezione richiesto. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) è l'unico imbuto che ricalcola lo stato desiderato e chiama il controller. I pulsanti della Dynamic Island dispatchano `LiveActivityIntent`, che chiamano `LavaProtectionCommandService` come descritto in [§2](#2-ipc-app-estensione).

---

## 6. Flusso di onboarding

L'onboarding è presentato da `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) ed è subordinato al flag `@AppStorage("hasSeenLavaOnboarding")` dichiarato in `RootView` (`RootView.swift:32`). Il flusso è una sequenza di `OnboardingPage` (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

La configurazione di partenza distribuita proviene da `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` abilita solo la sorgente raccomandata permissiva (Block List Basic), seleziona **Device DNS** come resolver — `DNSResolverPreset.device` (id `device-dns`), il DNS della rete stessa; i preset cifrati come Google DoH sono opt-in e non promossi a default — abilita il fallback device-DNS, e mantiene attivo il logging locale — con `protectionEnabled: false`, così che la protezione venga attivata solo quando l'utente la sceglie. `OnboardingDefaultsSummary` formatta quelle scelte per la visualizzazione ("Continue without account" è il default dell'account).

Impostare `hasSeenLavaOnboarding = true` alla fine è ciò che fa scattare `hasCompletedOnboarding`, che a sua volta arma il percorso di riconciliazione all'avvio descritto in [§3](#3-ciclo-di-vita-e-controllo-della-vpn). Fino ad allora, il percorso di neutralizzazione a metà onboarding impedisce a qualsiasi tunnel fail-closed ereditato di bloccare il traffico.

---

## 7. Stato dell'app: `AppViewModel`

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) è il proprietario centrale dello stato lato app. Oltre al ciclo di vita della VPN, pubblica le superfici a cui l'interfaccia utente si lega, inclusi:

- **Protezione e tunnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, e i messaggi rivolti all'utente `vpnMessage`/`vpnMessageIsError`.
- **Config e catalogo** — l'`AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, e i conteggi delle regole compilate (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnostica** — `DiagnosticsStore` e `NetworkActivityLog` (tutti locali; vedi la promessa di privacy qui sotto).
- **Account e backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, e lo stato di offerte/entitlement di **Lava Security Plus**.
- **Personalizzazione e presentazione** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress`, e `usesLiveActivities`.

Delega la serializzazione del ciclo di vita a un `protectionActionOrchestrator` (così che un ripristino in background non si interlacci con un'accensione da parte dell'utente), detiene il `tunnelManager` in cache, e pilota tutti i cambiamenti di snapshot/config/pausa verso l'estensione tramite gli helper di provider message in [§2](#2-ipc-app-estensione).

> **Inquadramento sulla privacy.** Il filtraggio DNS avviene localmente su questo dispositivo. Le superfici di diagnostica e attività di rete che `AppViewModel` pubblica sono archiviate solo localmente — Lava non riceve mai le tue query DNS di routine, la cronologia di navigazione o la telemetria per-dominio. Qualsiasi backup opzionale dell'account è **zero-knowledge** (cifrato on-device; Lava può sempre e solo archiviare cifrato), inclusa la recovery basata su passkey — la sua chiave è derivata tramite PRF on-device senza alcun segreto detenuto dal server. Vedi [Panoramica del sistema](./system-overview.md) per il confine del server.

---

## Documenti correlati

- [Panoramica del sistema](./system-overview.md) — l'intero sistema in una schermata: l'app, il Worker del catalogo e Supabase, più i confini di fiducia e la legenda di stato usata ovunque.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — gli interni del packet tunnel qui referenziati solo al confine di controllo: il motore di filtraggio compilato, i transport cifrati dei resolver (DoH / DoH3 / DoT / DoQ), il budget delle regole di filtraggio, il catalogo delle blocklist e il modello di redistribuzione source-url-only.
- [Account e backup zero-knowledge](./accounts-and-backup.md) — i provider di accesso e l'envelope di backup zero-knowledge che `AppViewModel` orchestra (incluso lo slot di recovery passkey zero-knowledge, derivato tramite PRF).
- [Backend e dati](./backend-and-data.md) — il Worker del catalogo `lavasec-api`, Cloudflare R2, e lo schema/RLS Supabase che si trovano dall'altro lato del confine app↔server.
- [Design System](../design-system/overview.md) — il modello di profondità `LavaTier`, i sette stati della Soft Shield Guardian e le skin dello scudo, e le convenzioni di copy/localizzazione che il client renderizza.
- [Avvisi di terze parti](../legal/third-party-notices.md) e [Decisione di conformità GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — i vincoli di distribuzione dietro la pipeline catalogo/filtro che il client consuma.
