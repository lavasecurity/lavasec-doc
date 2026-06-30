---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Catalogue des fonctionnalités {#feature-catalog}

> Public visé : PM / ingénierie. Ce catalogue couvre uniquement l'ensemble des fonctionnalités **actuellement implémentées**. Tout ce qui est conçu mais pas encore construit se trouve dans la feuille de route privée, pas ici.

Lava Security est une app iOS axée sur la confidentialité qui filtre le DNS **localement sur l'appareil** via un tunnel de paquets NetworkExtension, en bloquant les domaines malveillants et indésirables pour des utilisateurs non techniques (parents, personnes âgées) — avec une protection de base gratuite pour toujours et sans compte requis.

La promesse de confidentialité derrière chacune des fonctionnalités ci-dessous :

> Tout le filtrage DNS se passe sur l'appareil ; Lava ne fait jamais transiter votre navigation par ses serveurs et ne reçoit jamais la liste des domaines que vous visitez — le backend ne détient que les métadonnées du catalogue, une sauvegarde chiffrée opaque propre à chaque utilisateur, et les diagnostics anonymisés que vous choisissez d'envoyer.

## Comment lire ce catalogue {#how-to-read-this-catalog}

- **Free** — accessible à tout le monde, sans compte, sans achat.
- **Plus** — débloqué par Lava Security Plus, l'unique offre payante optionnelle. Plus débloque **uniquement de la personnalisation** ; il ne verrouille jamais la sécurité de base et ne permet jamais à un utilisateur payant de contourner le garde-fou de sécurité.
- Chaque ligne est **Implémentée** sauf mention contraire en ligne. Légende des statuts : **Implémenté** = livré et confirmé dans le code ; **Prévu** = conçu, pas encore construit ; **Abandonné** = rejeté ou annulé. Les éléments Prévus/Abandonnés sont documentés dans la feuille de route privée, pas ici.

Les plafonds d'offre faisant autorité vivent dans `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, avec l'alias `.plus`). Le **verrou** d'accès Plus est un drapeau local (`isPaid`) — la source de vérité. Le backend **reflète** les droits de l'App Store (`POST /v1/account/entitlements/app-store-sync` insère/met à jour une ligne `entitlements`), mais cette ligne n'est qu'un reflet, pas le verrou ; aucune synchro backend ne pilote encore le verrouillage.

---

## 1. Protection et VPN {#1-protection-vpn}

Le cœur du produit : un tunnel de paquets local réservé au DNS, et le modèle d'état apaisant qui l'entoure.

| Fonctionnalité | Offre | Notes |
|---|---|---|
| **Tunnel de paquets local réservé au DNS** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercepte le DNS et évalue chaque domaine sur l'appareil. Aucun trafic de navigation ne transite par Lava. Adresse du tunnel `10.255.0.2`, serveur DNS `10.255.0.1`. |
| **Priorité des décisions de filtrage** | Free | `blocage du garde-fou de sécurité > liste d'autorisation locale (exceptions autorisées) > liste de blocage > autoriser par défaut` ; les domaines invalides sont bloqués. (`FilterSnapshot.decision()`.) |
| **Priorité des requêtes (bootstrap d'abord)** | Free | `bootstrap du résolveur > pause temporaire > filtre` — le nom d'hôte du résolveur lui-même n'est jamais bloqué. (`DNSQueryDispatcher`.) |
| **Démarrage à froid « fail-closed »** | Free | Un tunnel démarré à froid sans instantané réutilisable installe un `FailClosedRuntimeSnapshot` qui bloque tout le trafic plutôt que de laisser fuiter du DNS non filtré. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` maintient la protection active / la relance automatiquement — activé **seulement après** une connexion confirmée, jamais à l'installation du profil, et neutralisé pendant une configuration incomplète, pour qu'une nouvelle installation ne puisse pas monter un tunnel impossible à désactiver. |
| **Pause temporaire (configurable 1–30 min, 5 par défaut) + reprise** | Free | La pause et la reprise passent par `LavaProtectionCommandService`, sous un verrou de fichier flock avec déduplication par révision. |
| **Pause nécessitant une authentification** | Free | Verrou opt-in par surface (`SecurityProtectedSurface.protectionPause`) : la pause exige une authentification locale de l'appareil ; le service de commande refuse une pause non authentifiée et la Live Activity masque les boutons de pause. |
| **Reconnecter** | Free | Relance directement le tunnel (en contournant le pipeline de pause du service de commande). |
| **Modèle d'état du Soft Shield Guardian** | Free | 7 états d'expression — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 niveaux de gravité de connectivité se ramènent à 4 visages ; rendus à l'identique dans l'app, dans l'onboarding et dans la Live Activity. |
| **Évaluation de la connectivité** | Free | 6 niveaux de gravité (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) pilotent le visage du gardien et le texte de statut. |
| **Optimisations de performance** | Free | Activation cache-first, regroupement des requêtes en cours, récupération en parallèle borné et regroupement des oscillations (activation à chaud mesurée à ~112 ms sur iPhone 15 Pro lors des travaux de modularisation et d'accélération). |

> **Garde-fou de l'appareil (pour tout le monde, jamais payant) :** un plafond strict de `~3,26 M de règles` (cible de 32 Mo résidents sous le plafond mémoire iOS de `~50 Mio` par extension) est appliqué à tous les utilisateurs, au-dessus de toute offre (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Les configurations qui dépassent le budget sont rejetées de façon déterministe (`exceedsDeviceMemoryBudget`) plutôt que de laisser le tunnel se faire tuer par jetsam.

---

## 2. Listes de blocage et filtrage {#2-blocklists-filtering}

Ce qui est bloqué, comment les listes sont choisies, et la frontière entre les offres.

| Fonctionnalité | Offre | Notes |
|---|---|---|
| **Listes de blocage par URL source uniquement** | Free | Lava ne publie que l'URL en amont + les hachages acceptés ; l'appareil récupère/analyse lui-même les **octets** de la liste. Lava ne stocke, ne reflète, ne transforme ni ne sert **jamais** les octets d'une liste de blocage tierce. Voir [la décision de conformité GPL « URL source uniquement »](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catalogue sélectionné (catégorisé)** | Free, activable | Des sources sélectionnées, organisées en catégories de défense en profondeur — Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling, Piracy & Torrent — issues de HaGeZi, The Block List Project, OISD, StevenBlack, AdGuard, 1Hosts et Phishing.Database. L'ensemble complet et actuel est publié dans le [Catalogue de listes de blocage](../legal/blocklist-catalog.md) ; chaque plateforme reflète la version du catalogue avec laquelle elle est livrée. |
| **Listes de blocage par défaut (gratuites)** | Free | Une nouvelle installation active **Block List Basic** — une liste combinée large et permissive (la source marquée `defaultEnabled: true` ; `DefaultCatalog.recommendedDefaultSourceIDs`). Tout le reste est opt-in. |
| **Analyse / normalisation / déduplication sur l'appareil** | Free | `BlocklistParser` prend en charge auto/plain/hosts/adblock/dnsmasq, supprime les commentaires/lignes vides/entrées invalides, déduplique les chaînes exactes, et plafonne à 1 000 000 de règles par liste. Une ligne `hosts` multi-hôtes émet désormais **chaque** hôte de la ligne, pas seulement le premier (version 2 des règles d'analyse). |
| **Intégrité en amont (TLS + URL sélectionnée)** | Free | Les octets des listes communautaires sont récupérés en TLS directement depuis le `source_url` sélectionné en amont et acceptés sous réserve des plafonds de taille + format + nombre de règles ; les `accepted_source_hashes` du catalogue sont **indicatifs** (identité du cache + audit), pas un verrou strict — une liste à rotation rapide n'est jamais rejetée parce qu'elle s'écarte d'un hachage figé. L'offre **garde-fou de sécurité** de Lava (sélectionnée par Lava, impossible à autoriser) reste strictement figée par hachage. |
| **Filtre des domaines protégés** | Free | Chaque source analysée est purgée des domaines protégés de Lava / Apple / fournisseurs d'identité (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …), pour qu'une liste en amont ne puisse pas casser l'app, le tunnel ou la connexion. |
| **Exceptions autorisées (liste d'autorisation)** | Free | Liste d'autorisation gérée par l'utilisateur, qui permet certains domaines malgré les listes de blocage. Plafond Free : 25 domaines autorisés / 25 bloqués (`FeatureLimits.free`). |
| **Quota de règles de filtrage (métrique d'offre)** | Free / Plus | La métrique d'offre livrée correspond au total de **règles** de domaine compilées : **Free 500 K / Plus 2 M** (`maxFilterRules` dans `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Remplace l'ancien plafond par nombre de listes. Les configurations qui dépassent l'offre déclenchent `exceedsTierFilterRuleLimit`. |
| **Limites de domaines plus élevées** | Plus | 1 000 domaines autorisés / 1 000 bloqués (`FeatureLimits.plus`). |
| **Listes de blocage personnalisées** | Plus | `allowsCustomBlocklists`. Les listes personnalisées sont récupérées et analysées sur l'appareil, mises en cache localement, jamais relayées aux serveurs de Lava. |
| **Réutilisation de l'artefact de démarrage à chaud** | Free | Un manifeste + une empreinte d'identité permettent au tunnel de réutiliser l'instantané compact sur disque sans recompiler ; la réutilisation est rejetée (avec une raison limitée au nom de champ, sûre pour la confidentialité) quand les entrées changent. |
| **Smart Save (confirmation des affaiblissements uniquement)** | Free | Les modifications de votre Filtre qui ne font que le *renforcer* ou qui sont neutres (ajouter une liste de blocage ou un domaine bloqué) s'appliquent directement ; les modifications qui *affaiblissent* la protection — retirer une liste de blocage, retirer un domaine bloqué, ou ajouter une exception autorisée — passent d'abord par une feuille de confirmation de revue, avec un panneau « Soyez très prudent » quand des exceptions sont ajoutées (`FiltersView.saveChanges()`, `weakensProtection`). |
| **Jauge de quota (sélection sauvegardable)** | Free / Plus | La jauge de sélection abrège les nombres (500 K / 1,2 M / 2 M) et applique une marge de plafond souple de 1,10 (la somme par liste surestime l'union dédupliquée de ~7–10 %) ; un nombre encore dans la tolérance est ramené pour afficher par ex. « 500 K sur 500 K » jusqu'à ce qu'il dépasse le plafond souple (`FilterRuleBudget`). |

> L'application du quota faisant autorité tourne à la compilation, sur l'union dédupliquée (`FilterSnapshotPreparationService`) ; le plafond de l'appareil est vérifié en premier, puis la limite de l'offre. Le compteur de l'UI au moment de la sélection utilise une somme par liste avec une marge de plafond souple de 1,10.

---

## 3. DNS chiffré {#3-encrypted-dns}

Les transports du résolveur et le routage des requêtes non bloquées.

| Fonctionnalité | Offre | Notes |
|---|---|---|
| **Cinq transports de résolveur** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH basé sur URLSession qui privilégie HTTP/3. L'UI annote **`DoH3` (sans slash)**, par ex. « Quad9 (DoH3) », **uniquement quand une négociation h3 est réellement observée** — privilégié, jamais promis (`DoHTransport`). |
| **DoT** | Free | `NWConnection` regroupées (jusqu'à 4/point de terminaison) avec rafraîchissement sur inactivité et une tentative sur connexion neuve. |
| **DoQ** (custom uniquement) | Plus | DNS-over-QUIC n'a **aucun préréglage intégré** — il n'est accessible que via un **résolveur custom `doq://`**, et le DNS personnalisé fait partie de Plus. Ouvre une **nouvelle connexion QUIC par requête** (le pool à 4 voies apporte de la concurrence, pas la réutilisation du handshake) ; la réutilisation de connexion est reportée à un plancher de déploiement iOS 26. |
| **Résolveurs préréglés** | Free | Device DNS (par défaut), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — en variantes IP / DoH / DoT là où elles sont proposées (`DNSResolverPreset.allPresets`). |
| **Routage et bascule du résolveur** | Free | `ResolverOrchestrator` route selon le transport, retombe en DNS clair quand un plan chiffré n'a aucun point de terminaison, fait une bascule par point de terminaison avec un palier de temporisation, puis un repli sur le DNS de l'appareil. |
| **Repli sur le DNS de l'appareil** | Free | Retombe sur le résolveur du réseau courant quand le résolveur choisi est indisponible ; **activé par défaut**. Exposé via le niveau de gravité `usingDeviceDNSFallback`. |
| **DNS personnalisé** | Plus | `allowsCustomDNS` — résolveur fourni par l'utilisateur (avec analyse de DNS-stamp pour les préréglages custom). |

---

## 4. Comptes et sauvegarde zero-knowledge {#4-accounts-zero-knowledge-backup}

Connexion à un compte optionnelle et sauvegarde chiffrée des réglages. Rien de tout ça n'est nécessaire pour utiliser la protection.

| Fonctionnalité | Offre | Notes |
|---|---|---|
| **Connexion à un compte optionnelle (Apple + Google)** | Free | Flux id_token natif échangé auprès de Supabase Auth (`grant_type=id_token`) avec un nonce haché ; seule la session Supabase obtenue est stockée localement sur l'appareil, dans le Keychain. La connexion par e-mail/mot de passe n'est volontairement pas proposée (Abandonné). |
| **Sauvegarde chiffrée zero-knowledge** | Free | Enveloppe AES-256-GCM côté client ; la clé de charge utile aléatoire est encapsulée dans des emplacements de clé PBKDF2-HMAC-SHA256 (210 000 itérations). Seuls le texte chiffré + des métadonnées non secrètes sont envoyés vers `user_backups` de Supabase (RLS par utilisateur). Le serveur ne peut pas déchiffrer sans un secret détenu par l'utilisateur. |
| **Charge utile de sauvegarde minimisée** | Free | Sauvegarde les IDs des listes de blocage activées, les domaines autorisés/bloqués, les réglages du résolveur, les préférences de journaux locaux, l'apparence du gardien, etc. — et exclut explicitement `isPaid`, les drapeaux QA, les diagnostics, les instantanés et les octets complets des listes de blocage. |
| **Emplacement de clé par secret d'appareil** | Free | Un secret d'appareil de 32 octets dans le Keychain propre à l'appareil (`...ThisDeviceOnly`, non synchronisé iCloud) pour une restauration fluide sur le même appareil. |
| **Phrase de récupération + récupération assistée** | Free | Une phrase CVCV de 8 mots (~105 bits) combinée à un partage de récupération détenu par le serveur, via SHA256, pour déverrouiller l'emplacement de récupération assistée. À deux facteurs : aucune moitié ne déchiffre seule. |
| **Emplacement de récupération par passkey** | Free | Emplacement optionnel protégé par WebAuthn, et **zero-knowledge** : sa clé de déverrouillage est dérivée **sur l'appareil** à partir de la sortie WebAuthn PRF (`hmac-secret`) de l'authentificateur (HKDF-SHA256). Le serveur n'enregistre aucun passkey, n'émet aucun défi, ne détient aucun secret de récupération et n'expose aucune route passkey — l'ancienne conception à séquestre serveur a été abandonnée. La disponibilité en production sur appareils physiques dépend de l'hébergement Associated Domains / AASA (Prévu). |
| **Suppression de compte / droits sur les données** | Free | Un endpoint Worker authentifié supprime les sauvegardes, les réglages, les droits, le profil et les pièces jointes des rapports de bug, puis l'utilisateur Supabase Auth ; l'app se déconnecte et efface le matériel de déverrouillage local. |

---

## 5. Widget et Live Activity {#5-widget-live-activity}

Présence sur l'écran verrouillé et dans la Dynamic Island.

| Fonctionnalité | Offre | Notes |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`) : une seule `Activity<LavaActivityAttributes>` sur l'écran verrouillé et dans la Dynamic Island (centre étendu / gardien en compactLeading / compactTrailing + petit glyphe de statut minimal). |
| **Affichage de protection à 5 états** | Free | `ProtectionState` : `on, paused, reconnecting, needsReconnect, networkUnavailable` — chacun correspond à une pose du gardien, un SF Symbol et un titre. |
| **Boutons d'action de la Live Activity** | Free | Pause pour N min (durée configurée, 5 par défaut), Reprise, Reconnecter — des `LiveActivityIntent` qui s'exécutent dans le processus de l'app via `LavaProtectionCommandService`. Les variantes de pause authentifiée exigent une authentification locale de l'appareil. |
| **Une seule réconciliation dédupliquée et contrôlée par révision** | Free | `LavaLiveActivityController` garde une seule Activity, ne la met à jour que sur un vrai changement d'id/de contenu, et conditionne les mises à jour à la révision de `ProtectionPauseStore` pour que des intents périmés rejoués ne fassent pas régresser l'état. |
| **Bascule des Live Activities** | Free | Activable/désactivable par l'utilisateur dans Réglages (`setUsesLiveActivities`), disponible sur iPhone/iPad uniquement. |

---

## 6. Onboarding {#6-onboarding}

Le parcours de première utilisation qui installe la config du VPN local et met en place des valeurs par défaut judicieuses.

| Fonctionnalité | Offre | Notes |
|---|---|---|
| **Parcours de première utilisation multi-pages** | Free | `OnboardingFlowView` — 6 pages : `lava, guardIntro, features, vpn, notifications, done`. (L'installation du profil et la demande de notifications surviennent à la bonne étape, pas dès le départ.) |
| **Installation du profil VPN local** | Free | Installe la config du VPN local pendant l'onboarding **sans** activer Connect-On-Demand, pour que la protection ne soit jamais activée en silence à la fin — la surface Guard reste la référence. |
| **Demande d'autorisation de notifications** | Free | Demandée en cours de parcours, à l'étape notifications. |
| **Valeurs par défaut recommandées appliquées** | Free | Résolveur Device DNS, repli sur le DNS de l'appareil activé, journalisation locale activée (compteurs + historique + activité), Block List Basic activée, continuer sans compte (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Réglages {#7-settings}

Surfaces de configuration, de sécurité, de diagnostic et de retours.

| Fonctionnalité | Offre | Notes |
|---|---|---|
| **Code de déverrouillage de l'app + biométrie** | Free | `SecurityController` : vérificateur de code SHA256 salé dans le Keychain + biométrie `LAContext`, avec une surcouche de blocage au déverrouillage de l'app et un masque de confidentialité lors des changements de phase de scène. |
| **Protection par surface** | Free | `SecurityProtectedSurface` verrouille six surfaces : `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Chacune peut exiger indépendamment une authentification locale de l'appareil (par ex. l'onglet Réglages renvoie `.requires(.appSettings)`). |
| **Sélecteur d'apparence Lava Guard (7 apparences)** | Free | `GuardianShieldStyle` : `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, chacune avec une couleur de glyphe Dynamic Island assortie. Choisie depuis un sélecteur radio en feuille du bas (« Choisissez votre Guard », `LavaGuardLookPickerSheet`) ; les apparences encore verrouillées portent un glyphe de cadenas et le panneau de déverrouillage/mise à niveau vit dans la feuille. |
| **Assortir l'icône de l'app** | Free | Icône d'app alternative optionnelle, assortie à l'apparence de gardien choisie. |
| **Apparence** | Free | Thème de couleurs clair/sombre/système. |
| **Contrôles de journalisation locale uniquement** | Free | Bascules pour les compteurs de filtrage, l'historique des domaines (diagnostics) et l'activité réseau — tout est stocké sur l'appareil. Les journaux détaillés (historique des domaines + activité réseau) sont élagués sur une fenêtre de **7 jours** (`LocalLogRetention.fineGrainedDays = 7`) ; les compteurs et la progression Lava Guard sont conservés plus longtemps. |
| **Activité / Journaux de domaines (détail Guard)** | Free | Diagnostics dynamiques, locaux uniquement, accessibles depuis l'onglet Guard (`GuardDestination.activity`). Le digest est un **flux** de requêtes — un total de « requêtes traitées » réparti en une barre de volume Autorisées/Bloquées avec « % protégé localement » (arrondi honnête : une part infime affiche `<1 %`, une part quasi totale affiche `>99 %`). Une section **Journaux de domaines** contient les **Principaux domaines** (les plus bloqués et autorisés, classés par nombre de requêtes) et l'**Historique des domaines** (recherches et décisions récentes) ; les lignes de domaines n'apparaissent que si l'option historique est activée. |
| **Filtre (détail Guard)** | Free | Écran de filtre unifié unique, accessible depuis l'onglet Guard. Un hub « Mon filtre » ouvre un seul écran **Mon filtre** consolidé avec deux rayons — **« Lava bloque ceci »** (listes de blocage + domaines bloqués individuellement) et **« Lava laisse passer ceci »** (exceptions autorisées) — sous un même flux de brouillon Modifier/Enregistrer. Un schéma de flux « Téléphone → Lava → Internet » figure en tête de l'onglet, et ouvrir Mon filtre rafraîchit automatiquement le catalogue. |
| **Activité réseau (Réglages → Avancé)** | Free | Flux d'événements borné, local uniquement, des transitions réseau/runtime/utilisateur, partagé via l'App Group (`NetworkActivityLog`). Déplacé de la surface Activité vers **Réglages → Avancé** (après « Nerd Stats », `SettingsRoute.networkActivity`), derrière le verrou `.activityViewing`, avec son propre panneau de confidentialité (« Reste sur cet iPhone », conservé 7 jours). |
| **Rapport de bug** | Free | Assistant déclenché par l'utilisateur, qui envoie un paquet anonymisé à `POST /v1/bug-reports` ; pas d'historique des domaines en v1. Le paquet porte désormais aussi la provenance du build (`appVersion`/`appBuild`/`sourceRevision`) et des compteurs d'honnêteté de connectivité. Aussi accessible en secouant l'appareil pour signaler (`RageShakeDetector`). |
| **Gestion de l'abonnement** | Plus | Pour les abonnés actifs, l'écran de mise à niveau affiche Gérer l'abonnement (offres à renouvellement automatique, via `AppStore.showManageSubscriptions`), Restaurer l'achat, et la date d'expiration du droit. |
| **Mentions légales + Version** | Free | Les Réglages exposent les mentions légales tierces (voir [Mentions tierces](../legal/third-party-notices.md)) et une page version/build. |

---

## Architecture de l'app (pour s'orienter) {#app-architecture-for-orientation}

Trois bundles partagent un même App Group `group.com.lavasec`, aux côtés d'un dossier de sources `lavasec-ios: Shared/` compilé dans chacun d'eux :

- **LavaSecApp** (`com.lavasec.app`) — la coquille de l'app SwiftUI ; dans ce build, la racine est un `TabView` à deux onglets (**Guard** + **Réglages**), avec Filtre et Activité accessibles comme écrans de détail sous l'onglet Guard (Activité réseau vit désormais sous Réglages → Avancé).
- **LavaSecTunnel** (`.tunnel`) — le moteur de filtrage/résolution DNS sur l'appareil.
- **LavaSecWidget** (`.widget`) — la Live Activity WidgetKit.
- **Shared/** — sources transversales (ce n'est pas un bundle) : App Group, service de commande, mascotte, attributs/intents de Live Activity.

Le contrôle App ↔ extension utilise les **provider messages** de `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), pas les notifications Darwin. Les règles de filtrage passent de l'app à l'extension sous forme de fichiers d'instantané App-Group (`filter-snapshot.json` / `.compact`).

---

## Docs liées {#related-docs}

- Feuille de route — les fonctionnalités prévues et abandonnées (tarification Plus/positionnement StoreKit, portage Android, protection au niveau des URL, disponibilité Associated-Domain pour les passkeys, mini-jeu easter-egg, publication open-source GPL-3.0, etc.) vivent dans la feuille de route privée, pas dans ce catalogue public.
- [Décision de conformité GPL « URL source uniquement »](../legal/gpl-source-url-only-compliance-decision.md)
- [Clause d'exclusion sur les conditions des données de listes open-source](../legal/open-source-list-data-terms-carveout.md)
- [Mentions tierces](../legal/third-party-notices.md)
