---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Principales décisions de conception {#key-design-decisions}

> Public visé : les ingénieurs et la direction. C'est le registre, façon ADR, des décisions de conception qui portent le poids de Lava Security — celles qui ont façonné l'architecture, la promesse de confidentialité ou les limites du produit, et surtout celles qu'on a essayées puis fait machine arrière. Chaque entrée donne la **Décision**, son **Contexte**, la **Logique** derrière, et un **Statut** tiré de la légende de statuts du projet (Adoptée / Annulée / Remplacée / Proposée).
>
> **Le code a le dernier mot.** Quand un plan et le code livré ne s'accordent pas, ce registre suit le code et signale l'écart sur place.

**Légende des statuts (alignée sur les voies de statut de l'ensemble documentaire) :**

| Statut ici | Sens dans la voie de l'ensemble documentaire |
|---|---|
| **Adoptée** | Implémenté — livré et confirmé dans le code |
| **Annulée** | Abandonné — construit, puis retiré/annulé |
| **Remplacée** | Une décision antérieure remplacée par une plus récente |
| **Proposée** | Prévu — conçu, recommandé ou consigné, mais pas encore appliqué dans cette arborescence |

À lire aussi : le modèle de distribution du catalogue dans [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) et [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md) ; le comportement livré dans [`../product/features.md`](../product/features.md). L'orientation à venir vit dans la feuille de route interne.

---

## 1. Filtrage DNS sur l'appareil via `NEPacketTunnelProvider` {#1-on-device-dns-filtering-via-nepackettunnelprovider}

**Décision.** Filtrer le DNS **localement sur l'appareil** via un tunnel de paquets `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), plutôt qu'avec `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` ou un bloqueur de contenu Safari.

**Contexte.** Le produit est un filtre qui met la confidentialité d'abord, pour des gens non techniques (parents, personnes âgées), distribué via l'App Store grand public, sans compte requis. Les autres fournisseurs NetworkExtension et API de DNS géré sont réservés aux appareils supervisés/gérés par MDM ou ne couvrent pas tout le DNS d'une app, et un modèle côté résolveur ferait sortir de l'appareil le flux des domaines de l'utilisateur.

**Logique.** Le tunnel de paquets est le seul fournisseur qui (a) marche pour des appareils grand public non gérés et (b) laisse chaque décision DNS se prendre sur l'appareil, ce qui est le socle de la promesse de confidentialité : *tout le filtrage DNS se fait sur l'appareil ; Lava ne fait jamais transiter votre navigation par ses serveurs et ne reçoit jamais le flux des domaines que vous visitez.* Le compromis accepté en échange, c'est le **plafond mémoire iOS d'environ 50 Mio par extension** sous lequel le tunnel doit tenir — une contrainte qui façonne plusieurs des décisions qui suivent.

**Statut.** **Adoptée** (fondatrice ; dans le code depuis le tout premier prototype).

---

## 2. Distribution de la liste de blocage par URL source uniquement {#2-source-url-only-blocklist-distribution}

**Décision.** Lava ne publie que l'**URL de la liste de blocage en amont, plus les empreintes acceptées** ; l'appareil récupère les **octets** de la liste directement depuis chaque `source_url`, puis les analyse, normalise, déduplique et filtre localement. Lava ne stocke, ne reflète, ne transforme et ne sert **jamais** les octets de listes de blocage tierces. Le Worker n'écrit que les **métadonnées** du catalogue en JSON dans R2 (`raw_r2_key`/`normalized_r2_key` valent null).

**Contexte.** La conception précédente recopiait les octets bruts des listes dans R2 pour que le conseil juridique puisse vérifier la distribution. Beaucoup de listes en amont (HaGeZi, OISD) sont sous GPL-3.0, donc héberger leurs octets ferait de Lava un redistributeur de données GPL.

**Logique.** Traiter Lava comme un moteur de filtrage local / agent utilisateur — plutôt que comme un distributeur de listes de blocage — minimise la redistribution sous GPLv3 et l'exposition à l'App Review. L'appareil valide les octets téléchargés contre les `accepted_source_hashes` du catalogue et retombe sur le dernier cache valide ou échoue en mode fermé en cas de non-correspondance, récupérant ainsi la propriété de sécurité qu'apportait le pipeline de copie. Chaque jeu de règles analysé passe aussi par un filtre de domaines protégés, pour qu'une liste en amont ne puisse pas bloquer les domaines de Lava/Apple/fournisseur d'identité. Le modèle est imposé en CI par `check-gpl-blocklist-distribution.sh` (pas de code de copie, pas d'URL d'artefact hébergé par Lava, aucune source GPL activée par défaut, aucune écriture d'octets dans R2).

**Statut.** **Adoptée**, et elle a **Remplacé** le plan abandonné de copie brute dans R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, en-tête « Superseded by the source-url-only implementation »). Voir [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Transports de résolveur chiffrés (DoH / DoH3 / DoT / DoQ) {#3-encrypted-resolver-transports-doh--doh3--dot--doq}

**Décision.** Livrer quatre transports amont chiffrés en plus du DNS en clair et d'un repli sur le DNS de l'appareil, sortis dans LavaSecCore : **DoH** (URLSession), **DoH3** (DoH préférant HTTP/3), **DoT** (`NWConnection`s mis en pool, jusqu'à 4/point de terminaison, avec rafraîchissement quand une connexion devient inactive et un seul réessai sur connexion neuve), et **DoQ** (DNS-over-QUIC). Le routage, la dégradation vers le DNS en clair, le basculement par point de terminaison avec une porte de temporisation, et le repli sur le DNS de l'appareil vivent dans `ResolverOrchestrator`.

**Contexte.** Transmettre en clair les requêtes non bloquées à un résolveur fait fuiter le flux de domaines même que le modèle sur l'appareil est censé protéger. Les transports ont été construits petit à petit (DoH → DoH3 → DoT → DoQ).

**Logique.** Un transport amont chiffré garde les requêtes non bloquées privées de bout en bout. **DoH3** est étiqueté de façon purement observée — `assumesHTTP3Capable=true` est posé et le protocole négocié est observé, et l'interface affiche `DoH3` (sans barre oblique) **seulement quand une négociation h3 est réellement observée**, jamais promise, parce que h3 est au mieux par connexion et qu'une affirmation persistante surévaluerait le comportement derrière des pare-feux qui bloquent l'UDP. Le pooling DoT avec rafraîchissement à l'inactivité a été un correctif direct au fait que Cloudflare fermait silencieusement les connexions DoT inactives.

**Statut.** **Adoptée** (les quatre transports présents et câblés).

---

## 4. Réutilisation de connexion DoQ — construite, testée sur appareil, annulée {#4-doq-connection-reuse--built-device-tested-reverted}

**Décision.** **Ne pas** réutiliser les connexions QUIC pour DoQ. `DoQTransport` ouvre une **connexion QUIC neuve par requête** ; le pool de 4 voies apporte de la concurrence, pas la réutilisation du handshake.

**Contexte.** La RFC 9250 mappe chaque requête DNS à son propre flux QUIC, donc une vraie réutilisation a besoin de l'API multi-flux `NWConnectionGroup`/`openStream`, **disponible seulement à partir d'iOS 26.0**, alors que le plancher de déploiement est iOS 17. Un chemin de réutilisation conditionné à iOS 26 a quand même été implémenté (compilé en Debug+Release avec le SDK Xcode 26) et **testé sur appareil sous iOS 26.5** contre le DoQ d'AdGuard.

**Logique.** Le chemin de réutilisation a échoué à chaque tentative sur l'appareil (`openStream`/`receive` en erreur, puis le repli tombait sur « Socket is not connected »), mesurant **nettement pire** que la référence par requête (témoin : 34 handshakes / 35 requêtes, tout réussi). Ça a confirmé empiriquement le conseil d'Apple DTS « tenez-vous à l'écart de QUIC avec le nouveau framework Network », donc le travail a été annulé plutôt que livré ; seuls les docs et la logique des tests de garde gardent le constat, pour qu'on ne s'y essaie pas de nouveau avant que l'API ne mûrisse.

**Statut.** **Annulée** (différée jusqu'à ce que le plancher de déploiement atteigne iOS 26). Décrire DoQ comme des connexions neuves par requête.

---

## 5. Rejet d'un protocole unificateur `DNSResolvingTransport` {#5-reject-a-unifying-dnsresolvingtransport-protocol}

**Décision.** **Ne pas** unifier les transports de résolveur sous un unique protocole `DNSResolvingTransport` ; garder le point de jonction `ResolverOrchestrator.Executors` à base de closures.

**Contexte.** Un remaniement (issue 407) proposait un seul protocole pour tous les transports.

**Logique.** Les transports sont trop dissemblables — exécuteurs chiffrés asynchrones (DoH/DoT/DoQ) contre transports synchrones multi-adresses en clair/appareil — donc un protocole unificateur serait une moins bonne abstraction que le point de jonction par closure injectable existant, qui garde déjà l'exécution sur le fil testable.

**Statut.** **Annulée** / ne-sera-pas-implémenté (fermé comme une mauvaise abstraction).

---

## 6. Sauvegarde chiffrée à divulgation nulle (sans mot de passe, exception passkey notée) {#6-zero-knowledge-encrypted-backup-passwordless-passkey-exception-noted}

**Décision.** Sauvegarder une charge utile de réglages **réduite au minimum** côté client : AES-256-GCM la scelle sous une clé de charge utile aléatoire de 32 octets, elle-même enveloppée dans des **emplacements de clé** par secret via PBKDF2-HMAC-SHA256 (**210 000** itérations en production). Seuls le texte chiffré et des métadonnées non secrètes remontent vers la table Supabase `user_backups` (RLS par utilisateur). Le flux livré est **sans mot de passe** : emplacement du secret de l'appareil (Keychain local à l'appareil) + emplacement de récupération assistée + emplacement passkey optionnel.

**Contexte.** La connexion à un compte optionnelle (Apple + Google uniquement) permet de restaurer les réglages d'un appareil à l'autre. Le serveur ne doit jamais pouvoir lire les listes de blocage, les listes d'autorisation, le choix de résolveur ou d'autres réglages d'un utilisateur.

**Logique.** Le texte en clair et les secrets de déchiffrement n'existent que sur l'appareil ; le serveur ne détient qu'une enveloppe opaque par utilisateur. La récupération assistée est volontairement à deux facteurs — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (entrée délimitée par NUL) exige **à la fois** la part détenue par le serveur et la phrase de récupération de 8 mots de l'utilisateur (environ 105 bits), donc aucune moitié seule ne déchiffre. Le matériel de déverrouillage est stocké en local sur l'appareil (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **pas** dans le trousseau iCloud synchronisable — un durcissement de confidentialité qui a inversé la conception synchronisable du plan d'origine. L'**emplacement passkey est lui aussi vraiment à divulgation nulle** : il est enveloppé avec une sortie d'authentificateur WebAuthn **PRF / `hmac-secret`** (dérivée par HKDF-SHA256) qui ne quitte jamais le client, donc aucune valeur détenue par le serveur ne peut le déballer. Il n'y a pas de table passkey en rôle service ni de porte d'assertion WebAuthn côté Worker — l'ancienne conception de passkey contrôlée par le serveur a été abandonnée, retirant tout état passkey côté serveur (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Statut.** **Adoptée** (modèle sans mot de passe, récupération assistée, et un emplacement passkey à divulgation nulle dérivé du PRF, tous dans le code). Faire du passkey un facteur récupérable pleinement prêt pour la production sur des appareils physiques (hébergement Associated Domains / AASA pour le modèle PRF) est **Proposée** (backlog).

---

## 7. Connect-On-Demand à échec fermé {#7-fail-closed-connect-on-demand}

**Décision.** Ajouter une règle `NEOnDemandRuleConnect` pour qu'un tunnel arrêté par l'OS redémarre tout seul, avec l'**échec fermé** comme valeur par défaut sûre : quand il n'y a pas d'instantané de filtre réutilisable, le tunnel bloque tout le trafic au lieu de le laisser passer non filtré. Le mode à la demande est **désactivé avant tout arrêt** pour que le VPN reste désactivable.

**Contexte.** iOS arrêtait silencieusement le tunnel (raison 17) sans rien pour le redémarrer pendant environ 45 minutes, laissant les utilisateurs sans protection. Activer naïvement le mode à la demande rend le VPN impossible à éteindre, et une valeur par défaut à échec ouvert laisserait passer le trafic pendant le creux.

**Logique.** Le mode à la demande comble le creux de l'arrêt silencieux ; désactiver-avant-d'arrêter préserve la capacité de l'utilisateur à couper la protection ; l'échec fermé garantit que le creux est sûr plutôt que silencieusement non filtré, rattrapé par `reconcileTunnelSnapshotAfterLaunch`. Le changement a eu des effets de bord — le mode à la demande relançait l'invite système « Ajouter des configurations VPN » pendant l'onboarding — ce qui a déclenché une chaîne de correctifs sur plusieurs commits : ne plus activer le mode à la demande à l'installation, conditionner le lancement/la restauration de la protection à la fin de l'onboarding, et **neutraliser une config héritée/orpheline en la supprimant** (`removeFromPreferences`, en silence) plutôt qu'en enregistrant `on-demand=false` (`saveToPreferences` réaffichait l'invite).

**Statut.** **Adoptée** (redémarrage à la demande plus la chaîne de correctifs onboarding/échec fermé).

---

## 8. Remaniement VPN modulaire et la discipline de régression thermique {#8-modular-vpn-refactor-and-the-heat-regression-discipline}

**Décision.** Restructurer le chemin VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) pour un démarrage cache-d'abord, une récupération en parallèle bornée et un regroupement des oscillations — en traitant batterie/latence comme des exigences produit avec des cibles p50/p95 explicites et un profilage **sur appareil** (pas sur Simulateur).

**Contexte.** Activer / actualiser / mettre en pause / reprendre étaient lents. Pendant le remaniement, une régression thermique est apparue (134 % CPU, énergie élevée, téléphone chaud). Un grand panel d'agents a d'abord réfuté la cause soupçonnée à partir de preuves d'avant la régression ; une capture en direct sur appareil l'a ensuite confirmée.

**Logique.** La vraie cause était une boucle de rafraîchissement `NEVPNStatusDidChange` qui s'auto-entretenait — une boucle de regroupement qui se réarmait à l'infini (environ 370 événements/s, fil principal à environ 100 %, `vpn-debug-log.jsonl` gonflé à environ 180–210 Mo) après le remplacement d'une garde drop-reentrant. Le correctif lit l'état du gestionnaire mis en cache et borne la boucle. Les artefacts avant/après sur appareil du plan lui-même enregistrent que l'activation à chaud (`action.turnOn`) chute de **2 722 ms à 287 ms** sur iPhone 15 Pro ; une revue d'opportunités post-modulaire séparée et plus tardive a mesuré le chemin à chaud à **112 ms** (décodage 51 + managerSetup 57) sur le même appareil. L'épisode a fixé la norme : les remaniements structurels s'arrêtent jusqu'à ce qu'une régression thermique mesurée soit bornée, et les résultats thermiques/batterie du Simulateur sont rejetés comme sans valeur.

**Statut.** **Adoptée** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Une revue post-modulaire garde `PacketTunnelProvider` et `AppViewModel` comme des objets-dieux survivants connus.

---

## 9. Quota de règles de filtrage plutôt qu'un plafond du nombre de listes {#9-filter-rules-budget-instead-of-a-list-count-cap}

**Décision.** Limiter les offres par un **quota de règles de filtrage** — **Gratuit 500K / Plus 2M** règles de domaines compilées — et non par le nombre de listes activées. Un **garde-fou matériel d'environ 3,26M de règles** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3 262 236`) s'applique à **tout le monde** et n'est **jamais un mur payant**. Le blob de domaines compact est `mmap`'é (`.mappedIfSafe`) pour qu'il reste adossé à un fichier et hors du `phys_footprint` compté par jetsam ; seules les tables d'entrées décodées coûtent de la mémoire résidente.

**Contexte.** L'ancien plafond portait sur un **nombre** de listes (gratuit 3 / payant 10). Une liste peut contenir 1K ou 1M de règles, donc le nombre était un indicateur malhonnête de la vraie ressource contrainte — le plafond mémoire NE de 50 Mio.

**Logique.** Les règles correspondent à de la mémoire réelle, donc toute combinaison de listes qui tient est permise. L'application de référence tourne à la compilation sur l'union dédupliquée dans `FilterSnapshotPreparationService` (garde-fou matériel d'abord, puis limite de l'offre) ; le compteur de l'interface au moment de la sélection utilise une somme par liste avec une marge plafond souple de 1,10. Les configs au-dessus du quota sont rejetées de façon déterministe (la protection reste coupée) plutôt que de laisser le tunnel se faire jetsam.

**Statut.** **Adoptée** dans le code (`SubscriptionPolicy.swift`), ce qui a **Remplacé** le plafond du nombre de listes. Le plan moteur (`plans/under_review/2026-06-13-filter-rules-budget-tier-revamp.md`) est encore en revue et le texte du site public « Listes de blocage activées 3 → 10 » est **périmé** — la vraie limite est le quota de règles. Voir [`../product/features.md`](../product/features.md).

---

## 10. Les plans en markdown + synchro à sens unique vers Linear {#10-plans-as-markdown--one-way-linear-sync}

**Décision.** Les fichiers markdown dans `plans/<lane>/` sont la **source de vérité** ; le **dossier de voie fait foi pour le statut** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Un push sur `main` synchronise les plans **à sens unique** vers Linear (équipe LAV), en rafraîchissant seulement le titre/la description après création ; un trajet retour **manuel et relu** distinct ramène le statut/la priorité/la voie de Linear dans le frontmatter du plan.

**Contexte.** Une petite équipe a besoin d'un état de planification indépendant des outils, relisable, qui ne se bat pas avec un gestionnaire de projet, et une boucle d'agent autonome a besoin d'un endroit stable pour lire et écrire l'état des plans.

**Logique.** La répartition par propriété de champ garde les deux systèmes sans conflit — le markdown possède le contenu, Linear possède l'état de tri — donc un push n'écrase jamais le tri humain. La voie `dropped/` garde les plans annulés hors du pipeline de synchro pour qu'ils ne réapparaissent pas (créée quand Garde-fous des exceptions autorisées / LAV-5 a été rejeté). Un frontmatter périmé à l'intérieur d'un plan est un bug de doc, pas un statut ; le dossier l'emporte, et là où le code montre qu'une fonctionnalité a été livrée malgré un frontmatter « Backlog » (p. ex. la suppression de compte), le code l'emporte.

**Statut.** **Adoptée** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml` ; voie `dropped/` en service).

---

## 11. Découpage du dépôt + open source copyleft du client {#11-repo-split--copyleft-open-source-of-the-client}

**Décision.** Découper le monorepo en dépôts par composant (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) et **rendre le client maison open source sous AGPL-3.0** à la place d'Apache-2.0, sur le précédent copyleft de Mullvad/ProtonVPN.

**Contexte.** Un développement par composant et une mise en open source du client. La question de licence est de savoir si un concurrent pourrait forker le client, le fermer et casser les prix.

**Logique.** Le copyleft force les dérivés à rester ouverts, empêchant un fork fermé du client — une posture « client public, backend/ops privés », avec backend, juridique et ops gardés privés. AGPL-3.0 (plutôt que GPL-3.0 simple) a été choisie pour combler le trou de l'usage en réseau. La tension connue entre GPL et distribution sur l'App Store est gérée par le fait que Lava est lui-même le distributeur du binaire App Store sous son propre droit d'auteur.

**Statut.** **Adoptée.** Le découpage du dépôt est **terminé** : chaque composant vit dans son propre dépôt — le client public `lavasec-ios` au tag v0.4.0, plus des dépôts séparés pour Android, le site marketing, le backend/l'infrastructure, les docs et le pipeline de CI/release — et la section « Repository layout » du `README.md` de `lavasec-ios` ne liste que les contenus par composant de ce dépôt (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`) avec l'infrastructure indiquée comme vivant dans des dépôts privés séparés. Le client est ouvert sous **AGPL-3.0** : le `LICENSE` de `lavasec-ios` est la GNU Affero General Public License v3 et le `README.md` arbore le badge AGPL-3.0.

---

## Annexe — autres annulations et rejets consignés {#appendix--other-recorded-reversals-and-rejections}

Ce sont des décisions plus petites, mais c'étaient de vraies décisions avec un revirement consigné ; listées par souci d'exhaustivité.

| Décision | Logique | Statut |
|---|---|---|
| DNS personnalisé gratuit vs payant | Positionnement de monétisation ; brièvement autorisé en gratuit, puis revenu au payant uniquement | **Annulée**, retour au payant uniquement |
| Connexion par e-mail/mot de passe | Posséder les mots de passe ajoute la charge de réinitialisation/MFA/verrouillage/fuite/usurpation alors qu'Apple + Google suffisent ; une récupération de contournement casserait la divulgation nulle | **Annulée** / jamais livrée (Apple + Google uniquement) |
| Garde-fous des exceptions autorisées (LAV-5) | La priorité des garde-fous a été livrée via la refonte plus simple de l'édition des listes de filtres ; le paiement ne doit jamais contourner le garde-fou de sécurité à haute confiance | **Annulée** (voie `dropped/` créée) |
| Verrouillage de la promotion de branche TestFlight | Verrouillage initial reconsidéré ; remplacé par un verrouillage du runner prévu après l'open source | **Annulée**, remplacée par un plan en backlog |
| Canal de contrôle app↔extension | `sendProviderMessage` (`NETunnelProviderSession`) est le **seul chemin de contrôle app→tunnel** — il porte l'état typé et révisionné et pilote de façon faisant foi la boucle d'exécution de l'extension. L'ancien observateur `CFNotificationCenter` côté extension ne se déclenchait jamais de façon fiable sur appareil et a été **retiré** (son absence est affirmée par les tests d'introspection de source). Les notifications Darwin ne survivent que dans le sens **tunnel→app**, comme un signal de changement de santé. | **Adoptée** (le message de fournisseur est le seul contrôle app→tunnel ; Darwin n'est que tunnel→app pour la santé) |

> Invariant de sécurité transversal référencé partout : le paiement ne contourne jamais le **garde-fou de sécurité** validé par empreinte et non autorisable. La priorité des décisions est **garde-fou de sécurité > liste d'autorisation locale (exceptions autorisées) > liste de blocage > autorisation par défaut.**
