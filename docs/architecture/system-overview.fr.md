---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Vue d'ensemble du système {#system-overview}

> **Public visé :** les ingénieurs. Voici l'intégralité de Lava Security sur une seule page — quelles sont les pièces, comment les données circulent entre elles, et où se situent les frontières de confiance. Les docs propres à chaque composant entrent dans les détails ; celle-ci existe pour que vous puissiez avoir le système en tête avant de les lire.
>
> **Autorité :** quand cette doc et un plan se contredisent, **c'est le code qui gagne**. Le statut reflète la réalité confirmée par le code, pas ce que le plan espérait. Voir la [Légende des statuts](#8-status-legend) tout en bas.

## 1. Le produit en une phrase {#1-product-one-liner}

Lava Security est une app iOS qui met la confidentialité d'abord et qui filtre le DNS **localement, sur l'appareil**, à travers un tunnel de paquets NetworkExtension. Elle bloque les domaines malveillants et indésirables pour les gens non techniques (parents, personnes âgées) — avec une protection de base gratuite pour toujours et sans aucun compte requis.

## 2. La promesse de confidentialité (canonique) {#2-the-privacy-promise-canonical}

> Tout le filtrage DNS se passe sur l'appareil ; Lava ne fait jamais transiter votre navigation par ses serveurs et ne reçoit jamais le flux des domaines que vous visitez — le backend ne détient que les métadonnées du catalogue, une sauvegarde chiffrée opaque propre à chaque utilisateur, et les diagnostics anonymisés que vous choisissez d'envoyer.

Tout ce qui suit sert à garder cette phrase vraie. L'architecture est volontairement réduite côté serveur : c'est l'appareil qui fait le travail, et le backend ne voit jamais une seule requête.

## 3. Composants {#3-components}

### Client iOS (trois cibles exécutables + code partagé, un seul App Group `group.com.lavasec`) {#ios-client-three-executable-targets-shared-code-one-app-group-groupcomlavasec}

| Composant | Bundle / emplacement | Rôle | Statut |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Coquille SwiftUI de l'app ; point d'entrée, navigation à deux onglets Protection + Réglages (Filtres/Activité sont des écrans de détail sous Protection). | Implémenté |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider` ; le moteur de filtrage/résolution DNS qui tourne sur l'appareil. Soumis au **plafond mémoire iOS d'environ 50 Mio par extension**. | Implémenté |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity WidgetKit (écran verrouillé + Dynamic Island). | Implémenté |
| **Shared/** | `Shared/` | Sources communes à plusieurs cibles : App Group, service de commandes, mascotte, attributs/intents de Live Activity. | Implémenté |

**Contrôleurs côté app (dans LavaSecApp) :**

- **AppViewModel** — le contrôleur côté app (l'objet-dieu) : il gère le cycle de vie du `NETunnelProviderManager`, la persistance de l'état partagé, la messagerie avec le provider, la réconciliation des Live Activity, la synchro du catalogue, la sauvegarde, StoreKit et l'authentification.
- **RootView** — un `TabView` à deux onglets (Protection + Réglages), avec Filtres et Activité accessibles en écrans de détail sous Protection ; gère l'arrivée à l'onboarding, héberge les surcouches de verrouillage de sécurité / de masquage pour la confidentialité.
- **SecurityController** — code (SHA256 salé dans le Keychain) + biométrie + protection par surface.
- **LavaLiveActivityController** — réconciliateur d'une seule Activity, dédoublonné et contrôlé par révision.
- **OnboardingFlowView** — flux multi-pages au premier lancement (6 pages : `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (package SwiftPM indépendant de la plateforme, `Sources/LavaSecCore/`) :**

- **FilterSnapshot / CompactFilterSnapshot** — filtre compilé + ordre de priorité des décisions ; la forme compacte est l'artefact sur disque adapté au mmap que lit le tunnel.
- **DNSQueryDispatcher** — priorité des requêtes : bootstrap > pause > filtre.
- **ResolverOrchestrator** — routage des transports, repli en DNS en clair, bascule par endpoint, repli sur le DNS de l'appareil.
- **DoHTransport / DoTTransport / DoQTransport** — exécuteurs des transports chiffrés.
- **FeatureLimits** (dans `SubscriptionPolicy.swift`) — plafonds par offre (source de vérité), via les membres statiques `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — calcul du garde-fou de l'appareil + application autoritaire du quota après l'union.
- **BlocklistCatalogSync / BlocklistParser** — récupération du catalogue, téléchargement direct depuis la source amont, parsing/normalisation/dédup en local, filtre des domaines protégés.
- **GuardianMascotAnimation** — graphe d'états de la mascotte à 7 états (rendu par `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — crypto de la sauvegarde + charge utile.
- **SupabaseIDTokenAuth** — auth `id_token` en URLRequest brute (sans SDK).

### Backend {#backend}

| Composant | Rôle | Statut |
|---|---|---|
| **Worker lavasec-api** | Cloudflare Worker (`api.lavasecurity.app`) : lectures du catalogue, synchro admin/cron de la liste de blocage + publication, rapports de bug anonymes, suppression de compte, miroir des droits App Store, sondes QA. | Implémenté |
| **Worker lavasec-email** | Redirecteur Cloudflare Email Routing en réception seule pour `@lavasecurity.app` ; rejette les mails inconnus ou trop volumineux. | Implémenté |
| **Supabase Postgres** | Comptes, `user_backups`, métadonnées du catalogue, tables réservées au rôle de service ; **RLS sur chaque table publique**. | Implémenté |
| **Cloudflare R2** (le bucket R2 de production, un bucket de prévisualisation séparé pour la préprod) | Snapshots du catalogue + le curseur de synchro en tourniquet. **Jamais** d'octets de listes de blocage tierces ; la route d'upload des pièces jointes de rapport de bug a été retirée (les anciens objets ne sont supprimés qu'à la suppression du compte). | Implémenté |
| **Cloudflare D1** (la base des retours sur l'aide) | Votes anonymes en ajout seul sur les retours des articles d'aide. | Implémenté |

## 4. Schéma du flux de données {#4-data-flow-diagram}

La propriété la plus importante de toutes : **le chemin du résolveur DNS chiffré (à droite) ne touche jamais au backend de Lava (en bas).** L'appareil récupère les *métadonnées* du catalogue depuis le Worker, mais les *octets* des listes et le vrai flux des requêtes vont directement chez des tiers.

```
                                  YOUR iPHONE
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                                                                             │
 │   ┌──────────────┐   provider messages    ┌───────────────────────────┐    │
 │   │  LavaSecApp  │ ─────────────────────►  │      LavaSecTunnel        │    │
 │   │ (AppViewModel│   (reload-snapshot /    │  (NEPacketTunnelProvider) │    │
 │   │  controller) │    pause / config)      │                           │    │
 │   └──────┬───────┘                         │   DNSQueryDispatcher       │   │
 │          │                                 │   bootstrap > pause >      │   │
 │          │ writes / reads                  │   ┌──────────────────────┐ │   │
 │          ▼                                 │   │  CompactFilterSnapshot│ │   │
 │   ┌──────────────────────────┐  mmap       │   │  guardrail > allow >  │ │   │
 │   │  App Group container      │ ◄──(read)── │   │  block > default-allow│ │   │
 │   │  group.com.lavasec        │            │   └──────────┬───────────┘ │   │
 │   │  • filter-snapshot.compact│            │              │ allowed     │   │
 │   │  • app-configuration.json │            │              ▼             │   │
 │   │  • tunnel-health.json      │           │   ┌──────────────────────┐ │   │
 │   │  • pause/session UserDefs  │           │   │  ResolverOrchestrator│ │   │
 │   └──────────────────────────┘             │   │  DoH3/DoT/DoQ/IP +   │ │   │
 │          ▲                                 │   │  device-DNS fallback │ │   │
 │          │ reads (Live Activity)           │   └──────────┬───────────┘ │   │
 │   ┌──────┴───────┐                         └──────────────│─────────────┘   │
 │   │ LavaSecWidget│                                        │                 │
 │   │ (Dynamic Isl.│                                        │ encrypted DNS   │
 │   │  + lock scr.)│                                        │ (query stream)  │
 │   └──────────────┘                                        │                 │
 └──────────────────────────────────────────────────────────│─────────────────┘
        │ (a) catalog          │ (b) list bytes              │ (c) blocked → NXDOMAIN
        │  metadata            │  (direct from upstream)     │     allowed → forwarded
        ▼                      ▼                             ▼
 ┌──────────────┐   ┌──────────────────────┐    ┌───────────────────────────────┐
 │ lavasec-api  │   │  Upstream blocklists  │   │  Public DNS resolver           │
 │ Worker       │   │  (HaGeZi, OISD,       │   │  (Quad9 / Cloudflare / Google  │
 │ GET /v1/     │   │   Block List Project) │   │   / Mullvad; user-chosen)       │
 │  catalog     │   └──────────────────────┘    └───────────────────────────────┘
 └──────┬───────┘
        │ reads/writes (metadata only)
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  LAVA BACKEND (sees no DNS queries, no browsing history)                   │
 │  • Supabase Postgres: accounts, user_backups (opaque ciphertext), catalog │
 │  • Cloudflare R2: catalog/latest.json, the round-robin cursor             │
 │  • lavasec-email Worker: receive-only @lavasecurity.app forwarding         │
 └──────────────────────────────────────────────────────────────────────────┘
       ▲
       │ (d) optional: encrypted backup envelope (PostgREST, RLS) — ciphertext only
       │     entitlement mirror, anonymous bug reports, account deletion
       └──── from LavaSecApp, only when the user opts in
```

## 5. Flux de données {#5-data-flows}

### A. Le chemin DNS (par requête, tout sur l'appareil) — Implémenté {#a-the-dns-path-per-query-all-on-device-implemented}

C'est le chemin chaud et le cœur de la confidentialité. Il tourne entièrement dans `LavaSecTunnel` ; rien ici n'atteint les serveurs de Lava.

1. Le tunnel de paquets intercepte une requête DNS (serveur DNS du tunnel `10.255.0.1`).
2. **`DNSQueryDispatcher`** applique la priorité des requêtes : **bootstrap > pause > filtre**. Le bootstrap-d'abord est une règle inviolable — le nom d'hôte du résolveur lui-même est résolu avant tout filtrage, pour que le résolveur ne puisse jamais se bloquer lui-même.
3. Si ce n'est pas du bootstrap et que ce n'est pas en pause, le domaine est évalué face à **`CompactFilterSnapshot`** (chargé depuis l'App Group via un mmap zéro-copie `Data(contentsOf:options:[.mappedIfSafe])`). L'ordre de décision est **garde-fou de sécurité > liste d'autorisation locale (exceptions autorisées) > liste de blocage > autorisation par défaut** ; les domaines invalides sont bloqués.
4. **Bloqué** → le tunnel répond en local (aucun contact avec l'amont). **Autorisé** → la requête est confiée à **`ResolverOrchestrator`**.
5. `ResolverOrchestrator` route vers le transport configuré — **`DoH3` / `DoT` / `DoQ` / DNS en clair (`IP`)** — avec bascule par endpoint derrière une barrière de backoff, repli en DNS en clair quand un plan chiffré n'a aucun endpoint, et **repli sur le DNS de l'appareil** quand le résolveur principal ne renvoie rien et que le plan l'autorise.
6. La réponse du résolveur est renvoyée à l'OS. Le flux de requêtes de l'utilisateur ne va qu'au **résolveur public choisi par l'utilisateur**, jamais à Lava.

Notes sur les transports (conventions verbatim) : `DoH3` (sans barre oblique) n'est annoté **que lorsqu'une négociation h3 est réellement observée** — préféré, jamais promis. **`DoT`** maintient un pool d'au plus 4 NWConnections par endpoint, avec rafraîchissement quand une connexion devient inactive + une nouvelle tentative sur connexion fraîche. **`DoQ`** ouvre une **nouvelle connexion QUIC par requête** (pas de réutilisation) ; le pool à 4 voies apporte de la concurrence, pas la réutilisation du handshake — la réutilisation de connexion a été construite, testée sur appareil, puis **annulée** (reportée jusqu'à ce que le plancher de déploiement passe à iOS 26). Voir [Filtrage DNS & listes de blocage](./dns-filtering-and-blocklists.md).

### B. Récupération du catalogue + chargement de la liste de blocage (URL source uniquement) — Implémenté {#b-catalog-fetch-blocklist-load-source-url-only-implemented}

Comment les règles de filtrage arrivent sur l'appareil. Lava est un distributeur **par URL source uniquement** : il ne publie que l'URL amont + les hachages acceptés et **ne stocke, ne reflète, ne transforme ni ne sert jamais les octets des listes de blocage tierces.**

1. L'appareil récupère les **métadonnées** du catalogue depuis le Worker : `GET https://api.lavasecurity.app/v1/catalog` → un JSON servi directement depuis R2 (`catalog/latest.json`), découpé en `sources[]` + `guardrails[]`, chaque entrée portant un `source_url` + des `accepted_source_hashes`.
2. Pour chaque source activée, l'appareil télécharge les **octets de la liste directement depuis `source_url`** (l'amont — HaGeZi, OISD, Block List Project, etc.), **pas** depuis Lava.
3. L'appareil calcule le SHA256 et n'accepte que les octets dont la somme de contrôle figure dans `accepted_source_hashes` ; en cas de non-correspondance, il se rabat sur le dernier cache valide ou échoue en mode fermé (`checksumMismatch`).
4. **`BlocklistParser`** parse/normalise/dédoublonne en local (formats auto / plain / hosts / adblock / dnsmasq), puis **`DomainRuleSet.lavaSecProtectedDomains`** retire les domaines protégés (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) pour qu'une liste amont ne puisse jamais bloquer les domaines de Lava/Apple/fournisseur d'identité.
5. **`FilterSnapshotPreparationService`** fusionne l'union dédoublonnée et applique le **quota de façon autoritaire** (le plafond de l'appareil d'abord, puis l'offre), puis écrit `filter-snapshot.compact` dans l'App Group.
6. `AppViewModel` envoie un provider message `reload-snapshot` ; le tunnel recharge.

Côté Worker, c'est le miroir de ça : sa synchro admin/cron récupère chaque amont, le hache/compte, écrit `raw_r2_key = null` / `normalized_r2_key = null`, et ne republie que les métadonnées. Le modèle de catalogue de listes de blocage et le chemin de synchro du backend sont couverts dans [Filtrage DNS & listes de blocage](./dns-filtering-and-blocklists.md) et [Backend & données](./backend-and-data.md).

**Modèle de quota (deux couches) :**
- **Garde-fou de l'appareil (pour tout le monde, jamais un mur payant) :** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3 262 236 règles** = `((32.0 − 4.0) MB × 1 048 576) / 9.0 B/règle` — une cible de 32 Mo sous le plafond NE d'environ 50 Mio. Les configurations qui dépassent le quota sont rejetées de façon déterministe, plutôt que de laisser le tunnel se faire tuer par le jetsam.
- **Plafond par offre (`FeatureLimits`) :** **Gratuit 500 K règles / Plus 2 M règles**, qui contraint en dessous du garde-fou de l'appareil. Cela a remplacé l'ancien plafond sur le **nombre** de listes activées (gratuit 3 / payant 10) — les plafonds sur le nombre de listes sont obsolètes.

> **Mise en garde sur les valeurs activées par défaut (c'est le code qui gagne) :** les défauts gratuits livrés sont **Block List Project Phishing + Scam** (`OnboardingDefaults.lavaRecommendedDefaults`). Ils sont dérivés sur l'appareil à partir du drapeau `defaultEnabled` de chaque source sélectionnée (`BlocklistSource.recommendedDefaultSourceIDs`), qui est la source de vérité sur l'appareil et reflète la colonne `default_enabled` du catalogue backend. Le texte de l'offre/du catalogue qui dit « Block List Basic est le seul défaut » est faux pour l'appareil (suivi en interne).

### C. Sauvegarde (zéro connaissance, opt-in) — Implémenté {#c-backup-zero-knowledge-opt-in-implemented}

Optionnelle, conditionnée à un compte, et la seule donnée utilisateur qui atterrit dans le backend — sous forme de **texte chiffré opaque**.

1. L'utilisateur se connecte éventuellement (Apple ou Google uniquement ; **e-mail/mot de passe est Abandonné**) via un `id_token` natif échangé chez Supabase Auth (`grant_type=id_token`, nonce haché). Seule la session Supabase qui en résulte est stockée, en local sur l'appareil, dans le Keychain.
2. **`BackupConfigurationPayload`** assemble un texte en clair minimisé (IDs des listes de blocage activées, domaines autorisés/bloqués, préférences de résolveur, préférences des journaux locaux, registre LavaGuard). Il **exclut** `isPaid`, la QA, les diagnostics et les listes de blocage complètes.
3. **`ZeroKnowledgeBackupEnvelope`** le scelle en **AES-256-GCM** sous une clé de charge utile aléatoire de 32 octets ; cette clé est emballée dans des **emplacements de clé** par secret via **PBKDF2-HMAC-SHA256 (210k itérations)** — emplacement secret-de-l'appareil, emplacement de récupération assistée, emplacement passkey optionnel. L'emplacement passkey optionnel est emballé avec une sortie **WebAuthn PRF / `hmac-secret`** d'un authentificateur (dérivée par HKDF) ; cette sortie ne quitte jamais le client, donc l'emplacement passkey est véritablement à zéro connaissance — aucune valeur détenue par le serveur ne le déballe (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** téléverse **uniquement le texte chiffré + des métadonnées non secrètes** vers Supabase `user_backups`, directement via PostgREST, cantonné par la **RLS** propre à chaque utilisateur. (Il n'y a pas de route d'upload côté Worker ; le Worker ne touche à `user_backups` que pour le supprimer lors de la suppression du compte.)
5. **Récupération :** restauration fluide sur le même appareil via l'emplacement secret-de-l'appareil ; hors appareil via la **phrase de récupération CVCV de 8 mots** (~105 bits) combinée à un partage de récupération détenu par le serveur via SHA256 (deux facteurs — aucune moitié seule ne déchiffre) ; ou, quand un emplacement passkey a été scellé, via la sortie WebAuthn PRF / `hmac-secret` côté client (aucune valeur détenue par le serveur n'intervient). Le serveur n'enregistre jamais de passkeys, n'émet pas de défis WebAuthn et ne stocke aucun secret de récupération.

Voir [Comptes & sauvegarde](./accounts-and-backup.md).

### D. Plan de contrôle app ↔ extension — Implémenté {#d-app-extension-control-plane-implemented}

Trois processus (app, tunnel, widget) se coordonnent à travers l'App Group `group.com.lavasec` :

- **Le contrôle = des provider messages NETunnelProviderSession**, **pas** des notifications Darwin. `AppViewModel` encode un `LavaSecProviderMessage {kind, operationID}` et appelle `session.sendProviderMessage` ; le `handleAppMessage` du tunnel aiguille selon le kind (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Des fichiers partagés** portent les règles/la config/la santé (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`) ; **des stores UserDefaults partagés** (`ProtectionSessionStore` / `ProtectionPauseStore`) portent l'état de session + de pause.
- **`LavaProtectionCommandService`** exécute les commandes de pause/reprise venant de la Live Activity / d'AppIntent sous un verrou de fichier `flock`, avec dédup par révision et refus quand une auth est requise ; **la reconnexion le contourne** pour relancer le tunnel directement (`startVPNTunnel`).
- **Connect-On-Demand** n'est activé qu'*après* que le tunnel a confirmé sa connexion, jamais à l'installation du profil — pour qu'un profil d'onboarding fraîchement installé ne puisse pas faire monter un tunnel qu'on ne pourrait plus désactiver.

Voir [Client iOS](./ios-client.md).

## 6. Frontières de confiance & conception qui préserve la confidentialité {#6-trust-boundaries-privacy-preserving-design}

| # | Frontière | Ce qui la traverse | Ce qui ne la traverse délibérément PAS |
|---|---|---|---|
| 1 | **Appareil ↔ résolveur DNS public** | Les requêtes DNS autorisées (chiffrées : DoH3/DoT/DoQ, ou IP en clair) vont au résolveur choisi par l'utilisateur. | Lava ne voit jamais le flux de requêtes ; il n'est pas du tout sur ce chemin. |
| 2 | **Appareil ↔ hôtes amont des listes de blocage** | L'appareil télécharge les octets de la liste directement depuis `source_url`. | Lava ne fait jamais proxy, ne reflète ni ne stocke les octets des listes de blocage tierces. |
| 3 | **Appareil ↔ Worker lavasec-api** | Lectures des **métadonnées** du catalogue ; rapports de bug anonymes opt-in ; miroir des droits ; suppression de compte. | Aucune requête DNS, aucun historique de navigation, aucun réglage en clair. |
| 4 | **Appareil ↔ Supabase** | **Enveloppe de sauvegarde chiffrée** opt-in (texte chiffré uniquement, PostgREST sous RLS) ; lignes de compte. | Le serveur ne peut pas déchiffrer la sauvegarde sans un secret détenu par l'utilisateur. |
| 5 | **App ↔ extension tunnel** (sur l'appareil) | Provider messages + fichiers/defaults de l'App Group. | Le tunnel échoue en mode **fermé** au démarrage à froid s'il n'a aucun snapshot réutilisable. |

**Principes de conception qui préservent la confidentialité, ancrés dans ce qui précède :**

- **Filtrage local d'abord.** Le moteur de décision et le résolveur tournent dans l'extension NE, sur l'appareil. Le backend ne contient que des métadonnées, par construction — il n'y a aucune table pour les requêtes DNS courantes ni pour de la télémétrie par domaine.
- **Aucun compte requis pour la protection.** La protection de base est gratuite pour toujours ; l'auth et la sauvegarde sont strictement opt-in.
- **Distribution par URL source uniquement.** Cela découple Lava des octets des listes tierces (conformité GPL/PI + sécurité face à l'App Review) et garde un garde-fou CI qui impose « pas de code de miroir, pas d'URL d'artefact Lava, pas d'écriture d'octets dans R2 ».
- **Sauvegarde zéro connaissance au repos.** AES-256-GCM côté client ; le serveur détient le texte chiffré + les métadonnées de KDF + un partage de récupération, jamais le texte en clair, la phrase de récupération ni la clé déballée. L'emplacement passkey optionnel est emballé avec une sortie WebAuthn PRF / `hmac-secret` côté client, donc lui aussi est à zéro connaissance — aucune valeur détenue par le serveur ne le déballe.
- **Secrets locaux à l'appareil.** Le matériau de déverrouillage de la sauvegarde utilise `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — pas synchronisé via iCloud, pas dans les sauvegardes de l'appareil.
- **Isolation du rôle de service.** `bug_reports`, `mirror_events` et `qa_developers` sont révoqués des rôles PostgREST anon/authenticated ; seul le Worker (rôle de service) y touche.
- **La sécurité n'est jamais à vendre.** Le paiement débloque **uniquement la personnalisation**. Il ne contourne jamais le **garde-fou de sécurité** non négociable, dont l'intégrité est garantie par les hachages source SHA256 acceptés (et non par une signature serveur). L'ordre de priorité est cohérent partout : **garde-fou de sécurité > liste d'autorisation locale (exceptions autorisées) > liste de blocage > autorisation par défaut.**

## 7. Docs par composant {#7-per-component-docs}

> Ce sont les documents frères dans l'ensemble des docs d'architecture. Le moteur de filtrage DNS et le catalogue de listes de blocage sont documentés ensemble dans un seul fichier.

- [Client iOS](./ios-client.md) — cibles, App Group, plan de contrôle, modèle d'état de la protection, onboarding, Live Activity.
- [Filtrage DNS & listes de blocage](./dns-filtering-and-blocklists.md) — snapshot de filtre, ordre de décision, transports du résolveur (DoH3/DoT/DoQ), quota mémoire, mmap ; plus le modèle de catalogue par URL source uniquement, la récupération du catalogue, le parsing/la normalisation en local, le filtre des domaines protégés et le quota par offre.
- [Comptes & sauvegarde](./accounts-and-backup.md) — auth Apple/Google, enveloppe à zéro connaissance, emplacements de clé, phrase de récupération, récupération par passkey WebAuthn-PRF côté client.
- [Backend & données](./backend-and-data.md) — Workers lavasec-api + lavasec-email, schéma Supabase + RLS, R2/D1, déploiement.

## 8. Légende des statuts {#8-status-legend}

Cet ensemble de docs utilise un seul vocabulaire de statuts. **C'est le dossier de la voie qui fait autorité pour le statut** ; un frontmatter périmé à l'intérieur d'un plan est un bug de doc, pas un statut. **Le code prime sur les plans.**

| Statut | Signification | Voie du plan | Code |
|---|---|---|---|
| **Implémenté** | Livré et confirmé dans le code | `plans/implemented/` | présent & branché |
| **En cours** | En cours de construction ; partiellement arrivé | `plans/inflight/`, `plans/under_review/` | partiellement présent |
| **Prévu** | Conçu, pas construit | `plans/backlog/` | absent |
| **Abandonné** | Rejeté ou annulé | `plans/dropped/` (ou commit annulé) | absent / retiré |

**Statut des choses mentionnées sur cette page :**

- **Implémenté :** les quatre cibles iOS + l'App Group ; le plan de contrôle par provider messages ; le filtrage DNS sur l'appareil avec les transports DoH3/DoT/DoQ/IP ; la récupération du catalogue par URL source uniquement + le parsing local ; le quota de règles de filtrage (Gratuit 500 K / Plus 2 M) + le garde-fou de l'appareil d'environ 3,26 M ; l'onboarding multi-pages ; la sécurité par code/biométrie ; une Live Activity unique dédoublonnée ; la sauvegarde à zéro connaissance ; l'auth Apple + Google ; la suppression de compte ; le miroir des droits ; les sondes QA ; la couche de tokens `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), y compris le modèle de profondeur `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), les modificateurs `.lavaTier(_:)` / `.lavaTierMetadata()` branchés sur des surfaces représentatives (par ex. `SettingsView`), et les tokens `dangerRed` et `LavaSpacing` — verrouillés par `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **En cours :** le déploiement continu de la couche de tokens du design-system sur plus de surfaces (le modèle de profondeur `LavaTier` et la couche de tokens sont livrés — voir ci-dessous — mais un `LavaColorRole` dédié n'est pas encore là, donc les accents se résolvent toujours en couleurs brutes).
- **Prévu :** le mini-jeu easter-egg Lava Guard ; des expressions supplémentaires de la mascotte (la mascotte a exactement **7** états) ; la récupération par passkey pleinement prête pour la production sur appareils physiques (Associated Domains / AASA) ; la re-vérification JWS App Store côté serveur (`verification_status` est `client_verified_storekit`) ; un token `LavaColorRole` dédié pour que les accents du design-system se résolvent à travers un rôle sémantique plutôt que des couleurs brutes.
- **Abandonné :** la réutilisation de connexion DoQ (connexions fraîches par requête) ; la connexion par e-mail/mot de passe (Apple + Google uniquement) ; la conception du miroir GPL raw-R2 (remplacée par l'URL source uniquement).
