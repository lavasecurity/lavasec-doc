---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Architecture du client iOS {#ios-client-architecture}

> Public visé : les ingénieurs iOS qui travaillent dans `lavasec-ios`.

Lava Security est une app iOS qui met la confidentialité au premier plan : elle filtre le DNS directement sur l'appareil grâce à un tunnel de paquets NetworkExtension, ce qui bloque les domaines risqués ou indésirables connus sans jamais faire passer votre navigation par les serveurs de Lava. Ce document explique comment le client iOS est structuré : les targets, la façon dont l'app dialogue avec son extension tunnel, le cycle de vie du VPN, le modèle d'état du Guardian, la Live Activity et le widget, le parcours d'accueil, et le détenteur de l'état côté app (`AppViewModel`).

Pour une vue d'ensemble de tout le système (l'app, le Worker du catalogue et Supabase), voir [Vue d'ensemble du système](./system-overview.md).

---

## 1. Targets et responsabilités {#1-targets-responsibilities}

Le client se compose de trois targets exécutables plus une bibliothèque cœur partagée. Les trois targets rejoignent le même **App Group** (`group.com.lavasec`) et lient `LavaSecCore`.

| Target | Bundle id | Responsabilité |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | L'app SwiftUI. Elle détient l'interface, possède le droit NetworkExtension et pilote le tunnel via `NETunnelProviderManager`. `AppViewModel` est la référence unique pour le cycle de vie du VPN. |
| **Tunnel de paquets** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | La sous-classe de `NEPacketTunnelProvider` appelée `PacketTunnelProvider` (alias `LavaSecTunnel`). Elle analyse les paquets DNS, en extrait le domaine demandé, l'évalue par rapport au snapshot compilé mappé en mémoire, et relaie en amont les requêtes autorisées. Elle est limitée par le plafond mémoire jetsam d'environ 50 Mio par processus. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Un `WidgetBundle` dont le seul membre est `LavaProtectionLiveActivityWidget` — la présentation Live Activity / Dynamic Island. |

Le code partagé vit à deux endroits :

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — le cœur indépendant de la plateforme : le moteur de filtrage, les transports de résolveur, les calculs de snapshot/quota, les stores de protection et le cœur `GuardianMascotAnimation`. D'après `VPNLifecycleController.swift:3-6`, les types NetworkExtension sont volontairement tenus hors de ce module pour que sa logique de cycle de vie reste testable avec des faux ; c'est le target app qui fournit les conformances adossées à `NetworkExtension`.
- **`Shared/`** — du code compilé dans plus d'un target (par ex. `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

Les rouages internes du tunnel de paquets (analyse DNS, snapshot compilé, transports de résolveur chiffrés et quota de règles de filtrage) sont détaillés en profondeur dans [Filtrage DNS et listes de blocage](./dns-filtering-and-blocklists.md). Ce document-ci se concentre sur l'architecture côté app et sur la frontière entre l'app et l'extension.

---

## 2. IPC app ↔ extension {#2-app-extension-ipc}

L'app et l'extension tunnel de paquets sont des processus distincts. Ils se coordonnent via trois mécanismes, tous ancrés sur l'App Group.

### Conteneur App Group {#app-group-container}

`group.com.lavasec` est le conteneur partagé qui permet à l'app, au tunnel et au widget de lire et écrire le même état et la même config `LavaSecCore`. `LavaSecAppGroup` (`Shared/AppGroup.swift`) centralise chaque clé et nom de fichier partagés pour que les processus ne puissent jamais diverger sur des constantes de chaînes, notamment :

- Les artefacts du snapshot compilé (`filter-snapshot.compact`, `filter-snapshot.json`), le `app-configuration.json` sérialisé, la santé du tunnel (`tunnel-health.json`), les diagnostics et le journal d'activité réseau.
- Des clés `UserDefaults` partagées pour la session de protection et l'état de pause. Elles aliasent directement les stores `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — pour que l'app, le tunnel et les intents de la Live Activity partagent une même disposition de clés, un même compteur de révision et un même schéma de déduplication.
- Le répertoire de cache du catalogue et le fichier de log de débogage sur l'appareil.

L'URL du conteneur est résolue via `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Message de commande / provider (le chemin de contrôle) {#command-provider-message-the-control-path}

L'app pilote le tunnel avec **`sendProviderMessage`** pour toutes les commandes. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) récupère la `NETunnelProviderSession` active depuis le manager mis en cache et appelle `session.sendProviderMessage(...)`. La charge utile est encodée par `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) dans une petite enveloppe JSON qui porte un message `kind` et un `operationID` optionnel (utilisé pour le traçage de latence de bout en bout).

Les types de messages reconnus sont des constantes sur `LavaSecAppGroup` :

| Constante de message | Effet dans le tunnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Force le rechargement du snapshot de filtres compilé. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Relit uniquement l'état de pause partagé. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Recharge la config ; seul un changement *d'identité de résolveur* déclenche une reconnexion visible. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Maintenance des diagnostics/journaux. |

Côté tunnel, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) décode l'enveloppe et fait un switch sur `kind`. Notamment, `reload-configuration` charge la nouvelle config pour que les champs hors résolveur (bascules de diagnostics, statut payant) prennent effet, mais ne réinitialise le runtime DNS et ne réapplique les réglages réseau du tunnel — une reconnexion visible — que lorsque l'identité du résolveur a réellement changé (`PacketTunnelProvider.swift:768-792`). Un changement de drapeau de diagnostics ou de statut payant ne coupe jamais la connexion en cours.

Les helpers `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` de l'app (`AppViewModel.swift:7062`/`7070`) sont de fines surcouches qui envoient ces messages.

### Pourquoi les messages provider pour le contrôle app→tunnel {#why-provider-messages-for-apptunnel-control}

**`sendProviderMessage` est le seul chemin de contrôle app→tunnel — il n'y a pas de signal Darwin app→tunnel.** Une conception antérieure publiait un signal Darwin `CFNotificationCenter` à la pause et l'observait dans l'extension, mais il ne se déclenchait jamais de façon fiable dans le processus NetworkExtension et a été supprimé. Le service de commande ne publie plus `CFNotificationCenterPostNotification`, et le tunnel n'ajoute plus de `CFNotificationCenterAddObserver` — leur absence est affirmée par des tests d'introspection du source (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` pour la publication côté service de commande ; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` pour l'observateur côté tunnel) afin d'empêcher toute réintroduction. (Les lignes `import Darwin` qui subsistent dans le service de commande et le tunnel servent aux primitives `flock`/socket, pas aux notifications.)

Un chemin Darwin *subsiste* bel et bien dans l'autre sens. Le tunnel envoie à l'app un coup de pouce signalant un changement de santé : `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) publie `CFNotificationCenterPostNotification` sur le canal `com.lavasec.protection.tunnel-health-changed` (le nom du canal vit dans `TunnelHealthSignal.swift`, pas dans `AppGroup.swift`), et l'app l'observe via `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), branché dans `AppViewModel` pour appeler `handleTunnelHealthNudge()`. La présence de ce coup de pouce de santé tunnel→app est affirmée par `LavaLiveActivitySourceTests.swift:1059-1075`.

Pour le contrôle app→tunnel, la pause est livrée en écrivant le `ProtectionPauseStore` partagé, puis en enchaînant avec le message provider `reload-protection-pause` pour que le tunnel exécute `refreshProtectionPauseStateOnly`. `AppViewModel.swift:4995-4996` énonce la règle directement : l'app « ne s'appuie jamais non plus sur l'observateur Darwin de snapshot, elle utilise toujours `sendProviderMessage` ». Considérez le couple App Group (état partagé) + `sendProviderMessage` (le signal de réveil/contrôle) comme le chemin de contrôle app→tunnel.

### Service de commande Live Activity {#live-activity-command-service}

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) est le point d'entrée des actions Dynamic Island / Live Activity (`LavaLiveActivityActionRequest` : `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes` / `pause-configured` (l'unique bouton Pause de la Live Activity, dont la durée correspond à la valeur configurée par l'utilisateur), `resume`, `reconnect`). Les `LiveActivityIntent` de `LavaLiveActivityIntents.swift` s'exécutent dans le processus de l'app (qui détient le droit NetworkExtension), donc :

- **Pause / reprise** passent par un verrou de fichier inter-processus (`protection-command.lock`, `flock`) et les `ProtectionPauseStore` / `ProtectionSessionStore` de `LavaSecCore`, qui possèdent l'attribution des révisions et la déduplication des commandes en double (le `commandID` enfile l'id d'opération de l'appelant pour qu'une commande re-livrée ne puisse pas créer une seconde révision). Le résultat planifie une mise à jour de Live Activity protégée par révision.
- **Reconnexion** est gérée directement (`performReconnect`, `LavaProtectionCommandService.swift:112-135`) : elle appelle `loadAllFromPreferences` et démarre le premier manager tunnel installé via `startVPNTunnel()` (comme `loadAllFromPreferences` est déjà restreint aux configurations NE de cette app, ce premier manager est bien celui de Lava — contrairement à `VPNLifecycleController.matchingManagers()`, elle ne fait pas de correspondance d'identité explicite). Le Connect-On-Demand est déjà activé, donc cela force simplement une connexion immédiate ; la réconciliation de statut de l'app ramène ensuite la Live Activity à `.on` une fois connectée.

---

## 3. Cycle de vie et contrôle du VPN {#3-vpn-lifecycle-control}

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) est la référence unique pour le cycle de vie du VPN dans l'app. Il orchestre l'activation/désactivation, met en cache le `NETunnelProviderManager` actif, et publie le statut vers SwiftUI.

### Sélection du manager et calculs de cycle de vie {#manager-selection-and-lifecycle-math}

La logique de cycle de vie réutilisable et sans NetworkExtension vit dans `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). L'app fournit les conformances adossées à `NETunnelProviderManager` de `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting` ; le contrôleur gère :

- **Sélection et déduplication** — `matchingManagers()` filtre pour ne garder que les managers appartenant à Lava via `LavaTunnelConfigurationIdentity.matches(...)`, trie par `selectionPriority` (actif d'abord, puis nom d'affichage canonique), et `removeDuplicateManagers(keeping:)` converge vers un seul survivant.
- **Attentes de connexion/arrêt** — `waitForConnect` / `waitForStop` interrogent le statut de la connexion en direct avec une tolérance `startGraceInterval`, parce que juste après `startVPNTunnel` la connexion peut brièvement afficher un statut non en attente avant qu'iOS ne la fasse passer à `.connecting`.

### Activation / désactivation {#turn-on-turn-off}

`enableProtection(...)` (`AppViewModel.swift:5764`) est **cache d'abord** : quand un artefact préparé, confirmé réutilisable, existe pour la configuration actuelle, le VPN peut monter immédiatement depuis le cache pendant qu'une synchro de catalogue en cours continue de se rafraîchir en arrière-plan, et `performCatalogSync` réconcilie le tunnel en marche à la fin. Il ne se bloque sur la synchro que lorsqu'il n'y a rien de valide pour démarrer (par ex. l'utilisateur vient de changer l'ensemble de la liste activée, ce qui invalide l'identité de l'artefact en cache).

`disableProtection(...)` (`AppViewModel.swift:5972`) désactive le Connect-On-Demand *avant* d'arrêter le tunnel pour qu'iOS ne le reconnecte pas aussitôt. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) installe une `NEOnDemandRuleConnect` (correspondance d'interface `.any`) et enregistre les préférences — enregistrer (et pas seulement définir) est nécessaire pour qu'iOS prenne le changement en compte.

### Observation du statut (et une mise en garde sur la chauffe) {#status-observation-and-a-heat-caveat}

`AppViewModel` observe `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) et publie `vpnStatus`/`isVPNConfigurationInstalled`. Point crucial : quand un manager est déjà en cache, il lit la connexion en direct du manager en cache plutôt que de forcer un rafraîchissement `loadAllFromPreferences` : `loadAllFromPreferences` re-publie lui-même `NEVPNStatusDidChange`, et un rafraîchissement forcé dans l'observateur produisait une tempête qui s'auto-entretenait — le commentaire dans le source (`AppViewModel.swift:1046-1048`) consigne les ~370 événements/s mesurés et la régression de chauffe à 134 % de CPU qu'elle provoquait. Les propriétés publiées ne changent que sur de vraies transitions, donc les tics au repos cessent d'invalider SwiftUI.

### Réconciliation fail-closed du on-demand {#fail-closed-on-demand-reconcile}

Le Connect-On-Demand peut faire monter le tunnel **à froid** au lancement (ou après qu'iOS l'a démonté lors d'un changement de réseau) avant que l'app n'ait poussé un snapshot. Un tunnel à froid sans snapshot persisté réutilisable charge en **fail-closed** — il bloque tout le trafic — et ne s'en remet jamais tout seul. `AppViewModel` gère cela par deux chemins de lancement, tous deux conditionnés à la fin de l'accueil (`hasCompletedOnboarding`, qui reflète le drapeau `@AppStorage("hasSeenLavaOnboarding")`) :

- **Après l'accueil** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) s'exécute chaque fois que la protection est active au lancement : il prépare le snapshot de démarrage, persiste l'état partagé, et envoie `reload-snapshot` pour que le tunnel recharge ses vraies règles et sorte du fail-closed. Le fail-closed reste le réglage sûr par défaut ; cela ne fait que le remplacer rapidement. (Corrige les filtres affichés en rouge / le trafic bloqué après un redémarrage de l'app pendant que le Connect-On-Demand maintient le tunnel en marche.)
- **Pendant l'accueil** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) s'exécute *avant* tout travail réseau quand l'accueil n'est pas terminé. iOS ne retire pas de façon fiable un profil VPN à la suppression de l'app, donc une réinstallation peut hériter d'une config orpheline, on-demand activé, qui fait monter un tunnel à froid en fail-closed avant que l'utilisateur n'ait choisi la moindre liste de blocage. Ce chemin **retire** la config (`removeFromPreferences`) plutôt que d'enregistrer une modification dessus — `saveToPreferences` re-afficherait l'invite système « Ajouter des configurations VPN » sur un profil que cette installation ne possède pas, déclenchant le dialogue à l'init de l'app avant même que la feuille d'accueil ne s'affiche. C'est un no-op sur une installation propre et quand la config héritée est déjà inerte.

---

## 4. Modèle Guardian / état {#4-guardian-state-model}

Il existe deux vocabulaires d'état apparentés : une *évaluation* de la connectivité et un état de la *mascotte* Guardian.

### Évaluation de la connectivité {#connectivity-assessment}

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) fait correspondre un `TunnelHealthSnapshot` à un `ProtectionConnectivityAssessment` avec l'une de **six gravités** et **deux actions** :

- Gravités : `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Actions principales : `turnOff` ou `reconnect`.

Cette évaluation unique pilote à la fois la surface Guard dans l'app et (après une correspondance supplémentaire) l'état de la Dynamic Island, pour que les deux ne se contredisent jamais.

**Plancher d'honnêteté (v1.0).** Un échec de sonde de fumée DNS actuel et non couvert ne peut jamais se lire comme `.healthy` — l'évaluation expose `.recovering` jusqu'à ce qu'une sonde réussisse réellement, pour que le trafic porté par un repli au-dessus d'un résolveur principal coincé ne soit plus peint en « Protégé ». La logique de reconnexion s'appuie sur `consecutiveDNSSmokeProbeFailureCount` et `lastPrimaryUpstreamSuccessAt` (principal uniquement) plutôt que sur les compteurs amont génériques, et un résolveur qui reste joignable mais continue de **rejeter** la sonde réputée bonne (détournement/captif/périmé) est escaladé jusqu'à mériter un redémarrage via un `consecutiveRejectedSmokeResponseCount` propre à l'identité du résolveur (LAV-87), même quand la série générique continue d'être réinitialisée sur des réseaux à itinérance instable.

### Notifications de connectivité {#connectivity-notifications}

`ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`) transforme l'évaluation en au plus une notification locale en attente, limitée (600 s) et dédupliquée. La v1.0 ajoute :

- Un type **`dnsSlow`** distinct (« Le DNS de Lava est lent ») — le DNS lent réutilisait auparavant le type `reconnectNeeded`, donc une vraie panne ne pouvait pas le supplanter.
- **Escalade/supplantation** — un problème strictement plus urgent (seul `reconnectNeeded` prime sur le reste) peut supplanter une bannière de rang inférieur déjà affichée, en contournant à la fois la garde « problème déjà en attente » et la limitation, pour qu'un blocage après un repli sur le DNS de l'appareil fasse remonter l'invite actionnable « Reconnecter » au lieu de laisser une bannière rassurante.
- Une **migration de persistance** (`ProtectionConnectivityNotificationStore`, schéma v2, branchée via `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) qui rétrograde un marqueur `reconnect-needed` hérité en attente vers `dnsSlow` pour que l'escalade fonctionne d'une mise à niveau à l'autre.

### Nouvelle tentative de capture du DNS de l'appareil {#device-dns-capture-retry}

Quand la configuration active dépend du résolveur de l'appareil (en principal ou en repli), un transfert/réveil de réseau peut laisser le tunnel avec une capture de résolveur système vide — un blocage silencieux. `DeviceDNSFallbackPolicy` pilote une **nouvelle tentative bornée** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1 s, `deviceDNSCaptureMaxRetryAttempts` 5) : le tunnel relit les résolveurs système chaque seconde, jusqu'à cinq tentatives, jusqu'à ce que la capture soit non vide, puis l'adopte sur place — récupération automatique sans redémarrage du tunnel (événements `device-dns-capture-retry` / `-exhausted`). C'est un no-op pour les configs purement DoH/DoT/DoQ (`currentConfigurationDependsOnDeviceDNS()`).

### États de la mascotte Guardian {#guardian-mascot-states}

La mascotte Soft Shield Guardian a exactement **sept** états émotionnels — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`) : `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Chaque état déclare ses `allowedNextStates`, ce qui contraint les transitions (par ex. `grateful` ne revient qu'à `awake` ; `GuardianMascotAnimation.swift:12-29`). Sémantique :

- `retrying` = auto-réparation calme.
- `concerned` = recherche d'aide en douceur.
- `grateful` = succès à fêter (utilisé sur les surfaces accueil/réglages, pas sur la carte de connectivité).

`GuardianMascotAnimation` est le cœur d'animation procédurale dans `LavaSecCore` ; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) est le rendu SwiftUI et prend en charge les skins de personnalisation sélectionnés par `GuardianShieldStyle` (noms d'affichage Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, avec la correspondance `displayName` aux lignes 18-35). Quelques valeurs brutes divergent de leur nom d'affichage (par ex. `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, et `purpleObsidian` s'affiche comme « Amethyst »), alors persistez la valeur brute, pas le libellé.

### Comment les deux se rejoignent {#how-the-two-connect}

Le `LavaActivityAttributes.ProtectionState` de la Live Activity (`Shared/LavaActivityAttributes.swift`) fait le pont entre l'évaluation et un état de mascotte via `guardianState` : `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). `AppViewModel` choisit l'état de protection pour la Dynamic Island à partir du même `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`) : une gravité `networkUnavailable` devient `.networkUnavailable`, `recovering` devient `.reconnecting`, une action principale `reconnect` devient `.needsReconnect`, et sinon `.on`.

> Note : `LavaTier` (l'enum de profondeur du design-system calme → **Floor** / festif → **Window** / technique → **Workshop**) se trouve dans la couche design-system (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), branché sur des surfaces représentatives — voir [le design system](../design-system/overview.md). Il régit la profondeur du design-system, pas le chemin client protection/tunnel décrit ici.

---

## 5. Live Activity et widget {#5-live-activity-widget}

Le target widget ne fait le rendu que de la Live Activity et de la Dynamic Island. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) expose un unique `LavaProtectionLiveActivityWidget`, une `ActivityConfiguration(for: LavaActivityAttributes.self)` avec :

- Une vue écran verrouillé, une région centrale étendue de Dynamic Island, et des présentations compacte/minimale qui affichent `SoftShieldGuardian` plus un glyphe de statut. Les vues compacte/écran verrouillé recalculent l'état de protection *effectif* sur une `TimelineView` rythmée à la seconde pour qu'un compte à rebours de pause reste vivant sans push.

`LavaActivityAttributes.ContentState` porte `protectionState`, une `resumeDate` (pour les comptes à rebours de pause), `pauseRequiresAuthentication` et le `shieldStyle` choisi. Le décodage est tolérant — un `shieldStyle` manquant retombe sur `.original` — pour que les anciennes charges utiles de Live Activity continuent de fonctionner.

Côté app, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) possède l'`Activity<LavaActivityAttributes>` en direct : il observe les changements d'autorisation ActivityKit, n'offre les Live Activities que sur les idiomes téléphone/tablette, et `reconcile(...)` démarre/met à jour/termine l'activité pour qu'elle corresponde à l'état de protection demandé. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) est l'unique entonnoir qui recalcule l'état souhaité et appelle le contrôleur. Les boutons de la Dynamic Island envoient des `LiveActivityIntent`, qui appellent `LavaProtectionCommandService` comme décrit au [§2](#2-app-extension-ipc).

---

## 6. Parcours d'accueil {#6-onboarding-flow}

L'accueil est présenté par `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) et conditionné par le drapeau `@AppStorage("hasSeenLavaOnboarding")` déclaré dans `RootView` (`RootView.swift:32`). Le parcours est une séquence d'`OnboardingPage` (`OnboardingFlowView.swift:403-409`) : `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

La configuration de départ livrée vient de `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` n'active que la source recommandée permissive (Block List Basic), sélectionne le **DNS de l'appareil** comme résolveur — `DNSResolverPreset.device` (id `device-dns`), le DNS propre au réseau ; les presets chiffrés comme Google DoH sont en option et ne sont pas promus par défaut — active le repli sur le DNS de l'appareil, et garde la journalisation locale activée — avec `protectionEnabled: false`, pour que la protection ne s'active que lorsque l'utilisateur le choisit. `OnboardingDefaultsSummary` met en forme ces choix pour l'affichage (« Continuer sans compte » est le réglage de compte par défaut).

Définir `hasSeenLavaOnboarding = true` à la fin est ce qui bascule `hasCompletedOnboarding`, ce qui à son tour arme le chemin de réconciliation au lancement décrit au [§3](#3-vpn-lifecycle-control). Jusque-là, le chemin de neutralisation pendant l'accueil empêche tout tunnel hérité en fail-closed de bloquer le trafic.

---

## 7. État de l'app : `AppViewModel` {#7-app-state-appviewmodel}

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) est le détenteur central de l'état côté app. Au-delà du cycle de vie du VPN, il publie les surfaces auxquelles l'UI se lie, notamment :

- **Protection et tunnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, et les `vpnMessage`/`vpnMessageIsError` destinés à l'utilisateur.
- **Config et catalogue** — l'`AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, et les compteurs de règles compilées (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnostics** — `DiagnosticsStore` et `NetworkActivityLog` (tout est local ; voir la promesse de confidentialité ci-dessous).
- **Compte et sauvegarde** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, et l'état des offres/droit **Lava Security Plus**.
- **Personnalisation et présentation** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress`, et `usesLiveActivities`.

Il délègue la sérialisation du cycle de vie à un `protectionActionOrchestrator` (pour qu'une restauration en arrière-plan ne s'entremêle pas avec une activation par l'utilisateur), détient le `tunnelManager` mis en cache, et pilote tous les changements de snapshot/config/pause vers l'extension via les helpers de message provider du [§2](#2-app-extension-ipc).

> **Cadre de confidentialité.** Le filtrage DNS se fait localement sur cet appareil. Les surfaces de diagnostics et d'activité réseau que publie `AppViewModel` sont stockées uniquement en local — Lava ne reçoit jamais vos requêtes DNS courantes, votre historique de navigation, ni de télémétrie par domaine. Toute sauvegarde de compte optionnelle est **zero-knowledge** (chiffrée sur l'appareil ; Lava ne peut jamais stocker que du texte chiffré), y compris la récupération par passkey — sa clé est dérivée par PRF sur l'appareil, sans aucun secret détenu par le serveur. Voir [Vue d'ensemble du système](./system-overview.md) pour la frontière côté serveur.

---

## Docs liées {#related-docs}

- [Vue d'ensemble du système](./system-overview.md) — tout le système sur un seul écran : l'app, le Worker du catalogue et Supabase, ainsi que les frontières de confiance et la légende des statuts utilisée partout.
- [Filtrage DNS et listes de blocage](./dns-filtering-and-blocklists.md) — les rouages internes du tunnel de paquets, ici référencés seulement à la frontière de contrôle : le moteur de filtrage compilé, les transports de résolveur chiffrés (DoH / DoH3 / DoT / DoQ), le quota de règles de filtrage, le catalogue de listes de blocage, et le modèle de redistribution par URL source uniquement.
- [Comptes et sauvegarde zero-knowledge](./accounts-and-backup.md) — les fournisseurs de connexion et l'enveloppe de sauvegarde zero-knowledge qu'orchestre `AppViewModel` (y compris l'emplacement de récupération par passkey, zero-knowledge et dérivé par PRF).
- [Backend et données](./backend-and-data.md) — le Worker de catalogue `lavasec-api`, Cloudflare R2, et le schéma/RLS Supabase qui se trouvent de l'autre côté de la frontière app↔serveur.
- [Design System](../design-system/overview.md) — le modèle de profondeur `LavaTier`, les sept états du Soft Shield Guardian et ses skins de bouclier, et les conventions de copie/localisation que le client affiche.
- [Mentions des tiers](../legal/third-party-notices.md) et [décision de conformité GPL par URL source uniquement](../legal/gpl-source-url-only-compliance-decision.md) — les contraintes de distribution derrière le pipeline catalogue/filtre que consomme le client.
