---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Backend et données

> **Public :** ingénieurs backend. **Portée :** la couche serveur — les deux Cloudflare Workers, le schéma Postgres de Supabase (RLS et auth), les stockages Cloudflare R2 et D1, toute la surface de l'API HTTP, la config et le déploiement, et la façon dont le « source-url-only » est appliqué côté serveur.
>
> **Référence qui fait foi :** quand un plan et le code se contredisent, **c'est le code qui gagne** — les écarts sont signalés au fil du texte. Les étiquettes de statut suivent la légende de la doc : **Implémenté** (livré et confirmé dans le code), **En cours** (en partie en place), **Prévu** (conçu, mais pas encore construit), **Abandonné** (rejeté ou annulé).

## 1. À quoi ressemble le backend {#1-the-shape-of-the-backend}

Le backend est volontairement minimaliste et respectueux de la vie privée. C'est une couche périphérique pour les métadonnées et les comptes, pas un service de filtrage. **Tout le filtrage DNS se passe sur l'appareil ; Lava ne fait jamais passer votre navigation par ses serveurs et ne reçoit jamais le flux des domaines que vous visitez — le backend ne garde que les métadonnées du catalogue, une sauvegarde chiffrée opaque propre à chaque utilisateur, et les diagnostics anonymisés que vous choisissez d'envoyer.** Il n'existe aucune table pour les requêtes DNS courantes ni pour la télémétrie par domaine, et la connexion au compte est facultative : elle n'est jamais nécessaire pour être protégé.

La couche serveur se répartit sur deux composants : le code du Worker backend et le schéma de la BD.

| Composant | Rôle |
|---|---|
| **Worker lavasec-api** | Couche périphérique principale : lectures publiques du catalogue, synchro des listes de blocage et publication du catalogue (admin + cron), rapports de bug anonymes, retours sur l'aide, suppression de compte, miroir des droits App Store, pixels de sonde QA, vérification d'accès QA du compte, promotion de tri des rapports de bug |
| **Worker lavasec-email** | Redirecteur Cloudflare Email Routing en réception seule pour `@lavasecurity.app` |
| **Supabase Postgres** (un projet Supabase Postgres) | Comptes, sauvegardes chiffrées, métadonnées du catalogue, tables réservées au rôle de service ; RLS sur chaque table publique |
| **Cloudflare R2** (un bucket de production, avec un bucket d'aperçu distinct pour la pré-prod) | Instantanés du catalogue + le curseur de synchro ; **jamais** les octets des listes de blocage tierces |
| **Cloudflare D1** (la base de retours sur l'aide) | Votes anonymes de retours sur les articles d'aide, en ajout seul |

Le Worker joint Supabase via PostgREST (`/rest/v1`) et Auth (`/auth/v1`) avec un identifiant de rôle de service Supabase — il n'y a pas de SDK Supabase côté serveur ; les appels sont des `fetch` bruts via les helpers `supabase()` / `supabaseAuth()`.

Statut : **Implémenté**.

## 2. Worker lavasec-api {#2-lavasec-api-worker}

`wrangler.toml` : `name = "lavasec-api"`, `main = "src/index.ts"`, un binding R2 → le bucket de production (un bucket d'aperçu distinct pour la pré-prod), un binding D1 → la base de retours sur l'aide, et **deux déclencheurs cron** : un qui se lance toutes les 6 heures (synchro des listes de blocage + publication du catalogue) et un qui se lance toutes les 2 minutes (promotion de tri des rapports de bug). Il est servi sur `api.lavasecurity.app`.

### 2.1 Surface de l'API {#21-api-surface}

Le routage est un dispatcher `route()` à plat. Tout est **Implémenté** sauf mention contraire.

**Public / non authentifié**

| Méthode et chemin | Handler | Notes |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Sert `catalog/latest.json` depuis R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Sert `catalog/{version}.json` depuis R2 ; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (par défaut 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anonyme, connexion facultative ; uniquement les champs de debug autorisés |
| `POST /v1/help-feedback` | `createHelpFeedback` | Vote anonyme sur un article → **D1**, pas Supabase |

> L'envoi de pièce jointe (l'ancienne route `PUT /v1/bug-reports/:id/attachment`) a été **retiré** ; les captures d'écran et les détails supplémentaires passent par un canal de support géré par un humain. Le Worker se contente, au mieux, de supprimer tout ancien objet de pièce jointe lors de la suppression de compte.

**Compte (jeton d'accès Supabase requis)**

| Méthode et chemin | Handler | Notes |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valide le jeton d'accès de l'utilisateur, supprime ses lignes + tout ancien objet de pièce jointe R2, puis supprime l'utilisateur Supabase Auth avec le rôle de service |
| `GET /v1/account/qa-access` | `accountQAAccess` | Renvoie `is_developer` depuis l'allowlist `qa_developers` réservée au rôle de service |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Insère/met à jour une ligne `entitlements` (offre `lava_security_plus`) à partir d'un JWS StoreKit vérifié par le client |

> **Aucune route `/v1/backup`.** La récupération de sauvegarde assistée par passkey est désormais **à divulgation nulle (zero-knowledge)** et entièrement côté client (voir §4.3 et §5) ; le Worker n'a aucune route `/v1/backup/*` ni aucun code WebAuthn/passkey.

**Admin (une clé d'API admin via `requireAdmin`)**

| Méthode et chemin | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Les endpoints HTTP admin sont protégés par une clé d'API admin. Le chemin de synchro planifié (cron) n'appelle **pas** ces routes HTTP — il invoque directement la logique de synchro (`syncBlocklistSources`) à l'intérieur du handler `scheduled`.

**Hôtes de sonde QA** — les requêtes vers les quatre hôtes `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) sont court-circuitées avant le routage et renvoient un PNG 1×1 `no-store` via `getQAProbePixel`. Rien n'est écrit dans Supabase ou R2.

### 2.2 Bindings et cron {#22-bindings-cron}

- **Binding R2** — `catalog/latest.json`, `catalog/{version}.json`, et le curseur en tourniquet `catalog/scheduled-sync-cursor.json`. **Il ne stocke jamais les octets des listes de blocage tierces.** (Les anciens objets de pièces jointes de rapports de bug ne sont jamais qu'*effacés* — au mieux, lors de la suppression de compte — jamais écrits.)
- **Binding D1** — lignes anonymes `article_id` / `locale` / `vote` / `path` en ajout seul ; gardées séparées de Supabase à dessein.
- **Cron (`scheduled`)** — le handler choisit selon l'id du cron :
  - **Toutes les 6 heures** — synchronise **une** source par exécution, en tourniquet via le curseur R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), puis republie le catalogue. Étaler la charge évite de marteler toutes les sources en amont d'un coup.
  - **Toutes les 2 minutes** — exécute un chemin interne de tri des rapports de bug qui fait remonter les nouveaux rapports anonymes dans une file d'attente d'un outil de suivi interne, en avançant son propre curseur de repère. C'est de l'outillage opérationnel interne ; les identifiants du suivi de tickets et des notifications sont de la configuration, pas une partie de l'API publique.

## 3. Catalogue et application du « source-url-only » {#3-catalog-source-url-only-enforcement}

C'est la partie du backend la plus spécifique à la posture de conformité de Lava, donc elle est dotée de garde-fous côté serveur.

### 3.1 Le modèle source-url-only {#31-the-source-url-only-model}

> **Source-url-only :** modèle de distribution conforme GPL/PI : Lava ne publie que l'URL en amont + les hachages acceptés ; l'appareil télécharge/analyse les listes lui-même. Lava ne stocke, ne réplique, ne transforme et ne sert **jamais** les octets de listes de blocage tierces.

Chaque ligne `blocklist_sources` porte un `redistribution_mode` dont la seule valeur autorisée est `"source_url_only"`. Le catalogue que l'appareil lit (`/v1/catalog`, `schema_version` 2) répartit les entrées entre `sources[]` et `guardrails[]` ; chaque entrée porte le `source_url` en amont plus `accepted_source_hashes` (SHA-256 + taille en octets + nombre d'entrées + `reviewed_at` + statut `accepted`) — jamais les octets des listes. Voir `formatCatalogEntry`.

> **Abandonné :** une conception antérieure répliquait dans R2 des fichiers de listes GPL préservés octet pour octet (le plan de conformité GPL-raw-R2). Elle a été **remplacée le 2026-05-25** par le source-url-only. Lava ne stocke ni ne sert plus les octets de listes de blocage tierces. Le nom de table `mirror_events` est un reliquat de cette conception abandonnée — ce n'est plus qu'un journal d'audit de synchro/publication.

### 3.2 Comment le Worker l'applique à l'écriture {#32-how-the-worker-enforces-it-on-writes}

Le chemin de synchro (`syncOneBlocklist`, admin et cron) télécharge chaque `source_url` en amont, normalise/valide **localement dans le Worker uniquement pour calculer des métadonnées** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), écrit une ligne `blocklist_versions`, et republie. Les clés de stockage d'octets sont mises en dur à null :

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Une migration (`20260525000000_add_blocklist_distribution_mode.sql`) a rendu ces colonnes nullables et mis les valeurs existantes à null, de sorte que la position « pas de miroir » est aussi appliquée au niveau du schéma. Le catalogue publié est écrit dans **les deux** fichiers `catalog/{version}.json` et `catalog/latest.json` dans R2 (`publishCatalog`).

### 3.3 Garde-fous de normalisation (métadonnées seulement) {#33-normalization-guardrails-metadata-only}

La normalisation côté Worker (`normalizeBlocklist`) filtre les domaines protégés, applique des plafonds, et dédoublonne+trie. C'est purement pour calculer des métadonnées fiables ; pour les **listes communautaires**, l'appareil **ne** verrouille **pas** le téléchargement par un hachage — il télécharge en TLS depuis le `source_url` sélectionné et analyse sous des plafonds (les hachages acceptés du catalogue sont indicatifs), donc cette normalisation côté Worker n'est pas une frontière de sécurité à elle seule. (Le niveau garde-fou anti-menaces de Lava reste épinglé par hachage sur l'appareil, et la provenance du `source_url` est appliquée au moment de la publication — un changement d'URL doit utiliser un nouveau `list_id`.) Constantes clés :

- `PROTECTED_SUFFIXES` — retire toute règle qui correspond aux domaines Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, pour qu'une source en amont empoisonnée ne puisse pas bloquer l'infrastructure de Lava ou ses fournisseurs de connexion.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 Ce qui est publiable {#34-what-is-publishable}

`isPublicBlocklistSource` ne publie une source que si son `status` est `sync` ou `nosync`, `redistribution_mode === "source_url_only"`, **et** `isAllowedLaunchGPLSource` passe. Le filtre GPL de lancement (`isAllowedLaunchGPLSource`) autorise librement les sources non-GPL et permet les familles de sources GPL-3.0 validées par préfixe de `list_id` : `hagezi-`, `oisd-`, et `adguard-`.

### 3.5 Sources préchargées et activées par défaut {#35-seeded-sources-default-enabled}

Les sources sélectionnées sont préchargées comme métadonnées source-url-only via des migrations, générées à partir de la spécification canonique du [Catalogue des listes de blocage](../legal/blocklist-catalog.md) (HaGeZi, OISD, The Block List Project, Phishing.Database, StevenBlack, AdGuard, 1Hosts). La migration d'expansion des catégories ajoute les catégories de défense en profondeur (nsfw/social/gambling/piracy), réaligne le défaut d'installation neuve sur **Block List Basic**, et réactive AdGuard DNS Filter comme une option signalée par le conseil juridique, désactivée par défaut. Statut : **Implémenté**.

> **Les valeurs par défaut du catalogue correspondent au client.** L'ensemble `default_enabled` du catalogue est **{Block List Basic}** — une liste combinée large et permissive qui remplace l'ancienne paire Phishing + Scam — correspondant au défaut recommandé iOS (`AppConfiguration.lavaRecommendedDefaults`). À la fois la colonne `default_enabled` servie et le `DefaultCatalog` iOS embarqué sont générés à partir de la même spécification canonique, donc ils concordent par construction (cela résout l'ancienne divergence de défaut client↔backend). À noter que `default_enabled` est informatif : la vraie barrière de niveau est le **quota de règles de filtrage (Gratuit 500 K / Plus 2 M)**, pas le nombre de listes. La justification juridique pour publier des URL (et pas des octets) est dans [Décision de conformité GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres {#4-supabase-postgres}

Un projet Supabase Postgres. La RLS est activée sur **chaque** table publique.

### 4.1 Schéma de base {#41-core-schema}

`20260516034033_backend_core.sql` crée les fondations (RLS activée sur les 7 tables publiques) :

- **`profiles`, `user_settings`, `entitlements`** — état du compte par utilisateur. Un trigger `handle_new_user()` crée automatiquement les lignes `profiles` + `user_settings` à l'insertion dans `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — les tables de métadonnées du catalogue. Une source est une liste en amont sélectionnée (`list_id`, `source_url`, licence, risque, `default_enabled`, `status`, `redistribution_mode`) ; une version est l'ensemble des métadonnées d'un instantané synchronisé (hachages, `entry_count`, `byte_size`), reliée via `latest_version_id`.
- **`mirror_events`** — journal d'audit réservé au rôle de service des événements `sync` / `catalog_publish` (nom historique ; voir §3.1).
- **`bug_reports`** — rapports anonymes réservés au rôle de service.

Des migrations ultérieures ajoutent **`user_backups`** (§4.3) et **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modèle RLS {#42-rls-model}

| Table(s) | Politique | Effet |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | par utilisateur `auth.uid() = user_id` | chaque utilisateur ne voit que ses propres lignes |
| `blocklist_sources` | lecture publique où `status in ('sync','nosync')` (`backend_core.sql:262-266`) | n'importe qui peut lire les sources sélectionnées éligibles à la synchro |
| `blocklist_versions` | lecture publique où `validation_status = 'published'` (`backend_core.sql:268-272`) | n'importe qui peut lire les métadonnées des versions publiées |
| `bug_reports`, `mirror_events` | `using(false)` explicite (`20260516034136_backend_core_advisor_fixes.sql`) | aucun accès anon/authentifié — le Worker utilise le rôle de service |
| `qa_developers` | RLS activée + **révocation de tout pour anon, authenticated** | réservé au rôle de service ; l'allowlist QA n'est jamais lisible par le client |

La distinction est importante : les rapports de bug anonymes doivent pouvoir être *insérés* par le Worker sans être *lisibles* par les clients, et l'allowlist QA ne doit jamais être lue que par le rôle de service.

### 4.3 Auth et l'enveloppe de sauvegarde chiffrée {#43-auth-the-encrypted-backup-envelope}

**L'auth** est facultative. La connexion se fait **uniquement avec Apple + Google** (e-mail/mot de passe est **Abandonné**). Les deux utilisent le grant natif `id_token` échangé sur Supabase Auth `auth/v1/token?grant_type=id_token` avec un nonce haché ; l'app ne stocke que la session résultante, verrouillée localement sur l'appareil dans le Keychain. Le flux côté client vit dans l'app iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — voir [Comptes et sauvegarde](./accounts-and-backup.md) pour le modèle complet de compte/sauvegarde.

> **Sauvegarde à divulgation nulle (zero-knowledge) :** enveloppe AES-256-GCM côté client ; seuls le texte chiffré + des métadonnées non secrètes sont envoyés à `user_backups` de Supabase (RLS par utilisateur). Le serveur ne peut pas déchiffrer sans un secret détenu par l'utilisateur.

Le fait backend crucial : **le client iOS lit/écrit `user_backups` directement via Supabase PostgREST sous RLS par utilisateur** (upsert sur `user_id`, cadré par le jeton d'accès). Il n'y a **aucune route `/v1/backup`** sur le Worker. Le Worker touche `user_backups` exactement une fois : pour la supprimer lors de la suppression de compte (`deleteAccount`).

`user_backups` ne stocke que du texte chiffré opaque + des métadonnées d'enveloppe non secrètes (paramètres/sels KDF, nonces, étiquettes d'emplacements de clés, indices de schéma client). Plafonds de taille (`20260605000000_tighten_backup_envelope_constraints.sql`) : texte chiffré ≤ 262144 octets (256 KiB) / ≤ 349528 caractères, métadonnées ≤ 32768 octets (32 KiB). La BD ne stocke jamais de réglages, mots de passe, phrases ni clés en clair.

### 4.4 Suppression de compte {#44-account-deletion}

`POST /v1/account/delete` valide le jeton d'accès de l'utilisateur, puis supprime ses lignes `bug_reports` (et tout ancien objet de pièce jointe R2 correspondant), `user_backups`, `entitlements`, `user_settings`, et `profiles`, et supprime enfin l'utilisateur Supabase Auth via l'endpoint `/admin/users` du rôle de service. Il ne renvoie qu'un statut de suppression + les fournisseurs liés. Statut : **Implémenté** (le frontmatter du plan indique `status: Done` et le fichier est dans `plans/implemented/` ; une annotation **dans le corps** désormais périmée dit encore « Backlog », mais le dossier de la voie + la présence du code en font une fonctionnalité livrée).

### 4.5 Miroir des droits App Store {#45-app-store-entitlement-mirroring}

`POST /v1/account/entitlements/app-store-sync` insère/met à jour une ligne `entitlements` (offre `lava_security_plus`) à partir d'un JWS de transaction StoreKit vérifié par le client, sur conflit par `user_id`. Le `verification_status` stocké est littéralement `"client_verified_storekit"` — le serveur ne **revérifie pas** le JWS. Identifiants de produit autorisés : `lava_security_plus_{monthly,yearly}`.

> Le miroir est **Implémenté** ; **la vérification du JWS côté serveur est Prévue** (pas encore construite). Le JWS signé est stocké pour vérification ultérieure. À noter le modèle de niveaux ailleurs : le droit de l'app est local (`isPaid`) **sans synchro backend pour l'instant** comme source de vérité — cette ligne est un miroir, pas la barrière.

## 5. Récupération assistée par passkey (zero-knowledge) {#5-passkey-assisted-recovery-zero-knowledge}

La récupération de sauvegarde assistée par passkey est **à divulgation nulle (zero-knowledge)** et entièrement côté client. Le matériel de la clé de récupération est dérivé sur l'appareil à partir de la sortie **WebAuthn PRF / hmac-secret** du passkey ; le serveur ne stocke **aucun** secret de récupération, n'enregistre **aucun** passkey, et n'émet **aucun** challenge WebAuthn. Il n'y a aucun chemin d'entiercement (escrow) géré par le serveur.

Les tables d'entiercement qu'une conception antérieure utilisait (`backup_passkey_recovery`, `backup_passkey_challenges`) ont été supprimées avant le lancement, et le Worker ne porte aucune route `/v1/backup/*` ni aucun code WebAuthn/passkey. (Une entrée `@simplewebauthn/server` reste dans le `package.json` du Worker comme dépendance résiduelle inutilisée.)

Le côté client vit dans l'app iOS : `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` pilote la création/assertion du passkey compatible PRF, et `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` dérive l'emplacement à partir de la sortie hmac-secret. La sortie PRF n'est lue que pendant l'assertion et ne quitte jamais l'appareil. Un fournisseur de passkey non-PRF ne peut pas soutenir un emplacement zero-knowledge, donc la configuration échoue tôt et l'utilisateur se rabat sur une phrase de récupération. Statut : **Implémenté**.

## 6. Worker lavasec-email {#6-lavasec-email-worker}

Réception et redirection uniquement. Il redirige `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` vers une boîte de réception opérateur vérifiée, rejette les destinataires inconnus et les e-mails de plus de 10 MiB, et **ne stocke pas le corps des e-mails**. Les réponses automatiques de support sont codées mais bloquées derrière l'envoi d'e-mails sortants payant de Cloudflare (différé). Les constantes de routage vivent dans `email-service.ts:9` (`ROUTED_RECIPIENTS`) ; le handler entrant est `handleInboundEmail`. Statut : **Implémenté** (le chemin de réponse automatique est **Prévu**/différé).

## 7. Config et déploiement {#7-config-deploy}

- **La config est `wrangler.toml`, qui est gitignored** ; `wrangler.toml.example` est le modèle commité. Considérez le `wrangler.toml` local comme la référence pour les valeurs spécifiques à l'environnement.
- **Variables** (non secrètes, dans `[vars]`) : l'URL Supabase, l'origine publique de l'API (`https://api.lavasecurity.app`), le TTL du cache de catalogue (par défaut 300s), un plafond de taille des rapports de bug, un interrupteur d'audit de suppression de compte, et un drapeau d'accélération du runtime Workers. Le tri interne des rapports de bug ajoute une clé de file d'attente de tri interne et une origine de tableau de bord utilisée pour composer les liens de tri.
- **Secrets** (via `wrangler secret put`) : un identifiant de rôle de service Supabase, une clé d'API admin, et — pour le chemin de tri des rapports de bug — une clé d'API du suivi de tickets et un webhook de notification de chat facultatif.
- **Le déploiement est manuel** : `npm run deploy` → `wrangler deploy`. Il n'y a pas de CI pour le Worker.
- **Routage Cloudflare** : `lavasecurity.app` reste sur Pages ; `api.lavasecurity.app` et `*.qa-probe.lavasecurity.app` résolvent vers ce Worker.
- **Compatibilité** : `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` est défini dans les vars mais n'est référencé par aucun code du Worker ; c'est un drapeau d'accélération du runtime Workers, pas un réglage applicatif.

## 8. Invariants de confidentialité (ce qui est ici et ce qui ne l'est pas) {#8-privacy-invariants-what-is-and-isnt-here}

Une checklist rapide pour quiconque étend le backend — aucun de ces points ne doit être cassé en douce :

1. **Pas de télémétrie DNS/navigation.** Il n'existe aucune table pour les requêtes DNS courantes ni pour la télémétrie par domaine. Le filtrage reste sur l'appareil.
2. **Pas d'octets de listes de blocage tierces** dans R2 ou Postgres — seulement le `source_url` + les hachages acceptés (§3).
3. **`user_backups` est opaque** — texte chiffré + métadonnées non secrètes uniquement ; c'est le client (pas le Worker) qui l'écrit sous RLS (§4.3).
4. **Isolation par rôle de service** pour `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Tous les chemins de sauvegarde sont zero-knowledge** — y compris la récupération assistée par passkey, dont le matériel de clé est dérivé côté client à partir de la sortie WebAuthn PRF/hmac-secret. Le serveur ne stocke aucun secret de récupération et n'exécute aucun WebAuthn (§5).

## Voir aussi

- [Vue d'ensemble du système](./system-overview.md) — tout le système sur une page, y compris les frontières de confiance.
- [Client iOS](./ios-client.md) — le côté appareil qui consomme ce backend.
- [Comptes et sauvegarde](./accounts-and-backup.md) — l'auth côté client, l'enveloppe AES-256-GCM, les emplacements de clés, et les phrases de récupération.
- [Filtrage DNS et listes de blocage](./dns-filtering-and-blocklists.md) — le côté appareil du catalogue : téléchargement direct depuis l'amont, analyse/normalisation, et le quota de règles de filtrage.
- [Décision de conformité GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — pourquoi le catalogue publie des URL, pas des octets.
- **Niveaux et monétisation** (interne) — le quota de règles de filtrage (Gratuit 500 K / Plus 2 M) qui est la vraie barrière Gratuit/Plus.
- **Registre des risques PI** (interne) — la justification PI/conformité derrière le source-url-only.
