---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Comptes et sauvegarde zéro connaissance

> **Public visé :** ingénieurs.
> **Autorité :** en cas de désaccord entre ce document et un plan, **c'est le code qui tranche** — les écarts sont signalés au fil du texte. Le statut reflète ce que le code confirme réellement, pas les intentions d'un plan. Légende des statuts : **Implémenté** (livré et confirmé dans le code), **En cours** (partiellement en place), **Prévu** (conçu, pas encore construit), **Abandonné** (rejeté ou annulé).

Les comptes sont **facultatifs**. La protection de base est gratuite pour toujours et ne demande aucun compte ; la connexion sert uniquement à sauvegarder vos *réglages*, chiffrés, pour pouvoir les restaurer sur un nouvel appareil. Ce document couvre le flux d'authentification, l'endroit où vit la session, l'enveloppe de sauvegarde zéro connaissance, les chemins de récupération, et exactement ce que le serveur peut voir et ne peut pas voir.

La promesse de confidentialité de référence que ce document soutient :

> Tout le filtrage DNS se fait sur l'appareil ; Lava ne fait jamais passer votre navigation par ses serveurs et ne reçoit jamais le flux des domaines que vous visitez — le backend ne détient que des métadonnées de catalogue, une sauvegarde chiffrée opaque propre à chaque utilisateur, et les diagnostics anonymisés que vous choisissez d'envoyer.

Répartition des composants : la crypto pure et la construction des requêtes vivent dans `LavaSecCore` ; l'orchestration et l'interface vivent dans `LavaSecApp`. Pages voisines : [Vue d'ensemble du système](./system-overview.md), [Client iOS](./ios-client.md), [Backend et données](./backend-and-data.md), [Filtrage DNS et listes de blocage](./dns-filtering-and-blocklists.md).

---

## 1. Flux d'authentification {#1-authentication-flow}

**Fournisseurs : Apple et Google uniquement.** **(Implémenté)** `AccountAuthProvider` énumère exactement `.apple` et `.google` (`AccountAuthService.swift`). L'e-mail/mot de passe — et toute récupération assistée par le support qui contournerait l'authentification — est explicitement **Abandonné** ; posséder les mots de passe ajouterait des obligations de réinitialisation/MFA/verrouillage/fuite qui ne valent pas la complexité alors qu'Apple/Google suffisent, et une récupération par contournement casserait la garantie zéro connaissance.

Les deux fournisseurs utilisent le **grant natif `id_token`**, pas le SDK Swift Supabase et pas l'OAuth web :

1. **Connexion native.** Apple via AuthenticationServices ; Google via le SDK GoogleSignIn. Chacun produit un `id_token` du fournisseur (Google fournit aussi un access token). L'app génère un nonce brut CSPRNG, le hache avec SHA256, et passe le hash au fournisseur pour que l'`id_token` émis y soit lié. **(Implémenté)**
2. **Échange chez Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) construit une `URLRequest` brute vers Supabase Auth `auth/v1/token?grant_type=id_token`, en envoyant `provider` + `id_token` + un `access_token` optionnel + le nonce **brut** (pour que Supabase puisse vérifier le lien et rejeter les rejeux), avec l'en-tête `apikey`. Pas de SDK ; `LavaSecCore` reste exempt de toute dépendance réseau/auth. **(Implémenté)**
3. **Réception d'une session.** Supabase vérifie le token et renvoie une session : un access token, un refresh token, une expiration, et un enregistrement utilisateur (provider/providers). Le rafraîchissement utilise le même helper avec `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orchestre tout ça — il lance les flux natifs, effectue l'échange, conserve et rafraîchit les sessions, expose `AccountAuthState`, et pilote la suppression de compte via le Worker.

```
Apple / Google (native id_token + raw nonce)
        │
        ▼
SupabaseIDTokenAuth  ──POST──▶  Supabase Auth  auth/v1/token?grant_type=id_token
        │                              │
        ▼                              ▼
AccountAuthService  ◀────── session (access + refresh tokens, expiry, user)
        │
        ▼
AccountSessionKeychainStore  (Keychain, device-local)
```

---

## 2. Stockage de la session et du Keychain {#2-session-keychain-storage}

La **seule** chose conservée à la connexion, c'est la session Supabase — les access et refresh tokens en JSON. Il n'y a **aucun** miroir côté serveur de qui vous êtes au-delà de l'utilisateur Supabase Auth et des lignes que vous possédez.

- **Où :** `AccountSessionKeychainStore` (`LavaSecApp`), service Keychain `com.lavasec.account-session`, stocké **par fournisseur** (`supabase-session-apple` / `supabase-session-google`, plus une migration d'ancien compte). **(Implémenté)**
- **Accessibilité :** tous les stores partagent `GenericKeychainStore` (`LavaSecCore`), épinglé à `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Ça veut dire **local à l'appareil, non synchronisé iCloud, et non inclus dans les sauvegardes de l'appareil**. **(Implémenté)**

Les mêmes mécaniques `GenericKeychainStore` soutiennent trois stores : la session de compte, le matériel de déverrouillage de la sauvegarde (`BackupKeychainStore`, service `com.lavasec.zero-knowledge-backup`), et le code d'accès de l'app. Aucun d'eux ne se synchronise via iCloud Keychain.

> **Point de revue ouvert (pas un comportement revendiqué) :** la classe d'accessibilité actuelle n'a aucune barrière biométrique/présence utilisateur (pas de `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Faut-il resserrer le matériel de déverrouillage vers un contrôle d'accès exigeant une présence ? C'est suivi comme point de revue avant publication ; la valeur livrée aujourd'hui reste after-first-unlock-this-device-only. **(Prévu)**

---

## 3. Sauvegarde zéro connaissance {#3-zero-knowledge-backup}

### 3.1 Ce que c'est, précisément {#31-what-it-is-precisely}

Quand vous activez la sauvegarde chiffrée, le **client iOS** chiffre une copie minimisée de vos *réglages* et n'envoie à Supabase que le texte chiffré plus des métadonnées non secrètes. Le téléphone est le seul endroit où le texte en clair et les secrets de déchiffrement existent jamais.

> **Sauvegarde zéro connaissance :** enveloppe AES-256-GCM côté client ; la clé de payload aléatoire est emballée dans des emplacements de clé par slot — PBKDF2-HMAC-SHA256 (210k itérations) pour les slots mot de passe/phrase/appareil/assistée, HKDF-SHA256 pour le slot passkey PRF. Seuls le texte chiffré + des métadonnées non secrètes montent vers la table Supabase `user_backups` (RLS par utilisateur). Le serveur ne peut pas déchiffrer sans un secret détenu par l'utilisateur. Le slot passkey est **lui aussi** zéro connaissance : sa clé de déballage est dérivée sur l'appareil à partir de la sortie WebAuthn PRF (`hmac-secret`) de l'authentificateur, et le serveur ne détient aucun secret passkey (voir §4.3).

### 3.2 Ce qui est sauvegardé (le payload minimisé) {#32-what-gets-backed-up-the-minimized-payload}

`BackupConfigurationPayload` (`LavaSecCore`) est le texte en clair qui se fait sceller. Il est volontairement petit et fait l'aller-retour avec `AppConfiguration`. **(Implémenté)**

**Inclus :** les **ID** des listes de blocage activées (références au catalogue, pas les octets des listes), les domaines autorisés/bloqués, le préréglage de résolveur / résolveur personnalisé, les préférences de journaux locaux, le registre LavaGuard, un indice de protection, et les métadonnées de source de liste de blocage personnalisée.

**Exclus :** `isPaid` (le droit d'accès est local), les drapeaux QA, les diagnostics, les instantanés de filtres, et le contenu complet des listes de blocage (référencé uniquement par ID de catalogue). Votre historique de navigation et vos requêtes DNS ne font jamais partie de ce payload, parce que l'appareil ne les enregistre jamais comme flux de télémétrie de routine.

### 3.3 L'enveloppe (crypto côté client) {#33-the-envelope-client-side-crypto}

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implémente la crypto. **(Implémenté)**

1. **Chiffrement du payload.** Le payload minimisé est scellé une seule fois en **AES-256-GCM** sous une **clé de payload aléatoire de 32 octets** (générée avec `SecRandomCopyBytes`).
2. **Emballage de clé (emplacements de clé).** Cette unique clé de payload est emballée indépendamment dans un ou plusieurs **emplacements de clé**, un par secret, qui chiffrent alors en AES-GCM une copie de la clé de payload. Le secret de n'importe quel emplacement, à lui seul, déverrouille toute la sauvegarde. La dérivation de la clé d'emballage dépend du type de slot : les slots `password` / `recoveryPhrase` / `keychain` (appareil) / `assistedRecovery` utilisent **PBKDF2-HMAC-SHA256, 210 000 itérations** (production ; `defaultPasswordIterations = 210_000`) avec un sel aléatoire frais de 16 octets par slot ; le slot `passkey` utilise **HKDF-SHA256** sur la sortie PRF de l'authentificateur (info `"LavaSec passkey backup PRF v1"`), avec le sel PRF non secret conservé dans le slot pour que la restauration puisse reproduire la sortie.
3. **Types d'emplacements.** L'enveloppe gère cinq types d'emplacements : `password`, `recoveryPhrase`, `keychain` (secret d'appareil), `assistedRecovery`, et `passkey`.

La configuration livrée est **sans mot de passe** (`makePasswordless`, piloté par `AppViewModel.turnOnEncryptedBackup`). Elle crée un **slot `keychain` (appareil) + un slot `assistedRecovery` + un slot `passkey` optionnel**. Les fabriques `password` / `recoveryPhrase` et les méthodes de déchiffrement existent toujours pour les enveloppes anciennes/rétrocompatibles (exercées uniquement par les tests), mais l'interface active ne crée jamais d'enveloppe à mot de passe seul — considérez la sauvegarde par mot de passe comme non livrée. **(Implémenté ; slot mot de passe Abandonné du flux en production.)**

**Intégrité / anti-rétrogradation :** `envelopeVersion` est figé en dur à `1`, et le KDF de chaque slot est épinglé par type — `PBKDF2-HMAC-SHA256` pour les slots mot de passe/phrase/appareil/assistée, `HKDF-SHA256` pour le slot passkey PRF. Les versions non gérées ou les KDF qui ne correspondent pas sont rejetés, donc des métadonnées forgées ou rétrogradées ne peuvent pas affaiblir le déballage. **(Implémenté)**

### 3.4 Envoi et stockage {#34-upload-storage}

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) envoie l'enveloppe **directement** vers la table PostgREST Supabase `user_backups`, en faisant un upsert sur `user_id`, cadré par l'access token de l'utilisateur. **Il n'y a pas de route Worker pour l'envoi de l'enveloppe** — le client parle directement à Supabase sous RLS ; le Worker ne touche `user_backups` que pour la supprimer lors de la suppression de compte. **(Implémenté)**

Ce qui atterrit dans `user_backups` :

- le **texte chiffré**, et
- **uniquement des métadonnées non secrètes :** le nom du chiffrement, les enregistrements des emplacements de clé (sels, nombres d'itérations, clés emballées, étiquettes de slot), le `server_recovery_share`, `createdAt`, et la taille en octets.

La ligne est protégée par **la sécurité au niveau ligne** : chaque ligne n'est lisible/modifiable que par son propriétaire (`auth.uid() = user_id`) ; le rôle anonyme n'a aucun accès. La taille est plafonnée à environ 256 Kio de texte chiffré / 32 Kio de métadonnées au niveau de la base (`20260518000000_zero_knowledge_backups.sql`, resserré dans `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implémenté)**

### 3.5 La garantie — ce que le serveur peut et ne peut pas voir {#35-the-guarantee-what-the-server-can-and-cannot-see}

**Le serveur stocke :** le texte chiffré, les sels/itérations KDF, les emplacements de clé emballés, le `server_recovery_share`, et quelques champs non secrets (chiffrement, taille, horodatage).

**Le serveur ne reçoit ni ne stocke jamais :** les réglages/domaines/préférences DNS en clair, la phrase de récupération, aucun mot de passe de sauvegarde, ni la clé de payload déballée.

**Donc :** Supabase **ne peut pas déchiffrer une sauvegarde** sans un secret détenu par l'utilisateur. Les trois chemins de restauration — le slot de clé d'appareil, la phrase de récupération (combinée au partage serveur, §4.2), et le slot passkey (la sortie PRF de l'authentificateur, §4.3) — déchiffrent **sur l'appareil**, et le serveur ne détient aucun secret de déchiffrement pour aucun d'eux. C'est affirmé dans les commentaires de migration et le plan de confidentialité, et testé (les tests d'enveloppe confirment qu'aucun domaine/URL en clair ne fuit dans la forme envoyée).

**Réserve précise sur le modèle de menace — ne surpromettez pas.** Pour le slot de **récupération assistée**, le serveur détient *à la fois* le `server_recovery_share` *et* le slot `assistedRecovery` emballé dans `user_backups`. La seule chose qui lui manque, c'est la phrase de récupération de l'utilisateur, que Lava ne reçoit jamais. Donc si le serveur était entièrement compromis, l'entropie de la phrase de récupération (environ 105 bits, voir §4.1) plus le coût du PBKDF2 à 210k itérations seraient la **seule** barrière contre une attaque par force brute hors ligne de ce slot. C'est intentionnel (la récupération assistée est à deux facteurs par conception — aucune moitié seule ne déchiffre), mais ça veut dire que l'entropie de la phrase de récupération porte vraiment le poids, elle n'est pas décorative. Le secret du slot `keychain` (appareil) ne quitte jamais l'appareil, donc il n'est pas exposé du tout à une compromission du serveur.

---

## 4. Récupération {#4-recovery}

Une sauvegarde n'est utile que si vous pouvez la restaurer. `restoreEncryptedBackup` (dans `AppViewModel`) déchiffre en essayant les slots disponibles : clé d'appareil, phrase de récupération, ou passkey. Dans tous les modes, l'enveloppe est chargée localement (ou récupérée depuis Supabase) puis **déchiffrée sur l'appareil** — le serveur ne déchiffre jamais.

### 4.1 Phrase de récupération {#41-recovery-phrase}

`BackupRecoveryPhrase` (`LavaSecCore`) génère une **phrase de récupération de 8 mots CVCV** (consonne-voyelle-consonne-voyelle) à partir de `SecRandom` avec échantillonnage par rejet (environ 13,2 bits/jeton → **environ 105 bits au total**), normalisée en minuscules. **(Implémenté)** La restauration tolère le formatage de l'utilisateur (espacement/casse) via une analyse/normalisation avant d'essayer le slot.

C'est le facteur de récupération **hors appareil** de l'utilisateur — enregistré par l'utilisateur, jamais envoyé. Selon le durcissement de confidentialité (§5), copier la phrase est **facultatif** et, quand c'est utilisé, ça passe par un presse-papier local uniquement / qui expire (10 minutes) plutôt que de forcer une exposition au presse-papier global.

### 4.2 Récupération assistée (la combinaison à deux facteurs) {#42-assisted-recovery-the-two-factor-combination}

La phrase de récupération à elle seule ne déverrouille **pas** le slot `assistedRecovery`. Le secret du slot est dérivé des **deux** moitiés :

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

Les trois segments sont joints par un **séparateur octet NUL (`0x00`)** dans l'entrée UTF-8 réelle — c'est-à-dire que la chaîne hachée est `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — donc le `‖` ci-dessus désigne une concaténation délimitée par NUL, pas une concaténation nue. `serverRecoveryShare` est une valeur aléatoire stockée dans les métadonnées de l'enveloppe côté serveur ; `normalizedPhrase` est la phrase de récupération de l'utilisateur. **Aucune moitié seule ne déchiffre** — la restauration exige le partage serveur (récupéré avec la sauvegarde) *et* la phrase détenue par l'utilisateur. **(Implémenté)**

### 4.3 Récupération par passkey — zéro connaissance, dérivée du PRF {#43-passkey-recovery-zero-knowledge-prf-derived}

Le slot `passkey` optionnel ajoute un facteur soutenu par le matériel, et il est **zéro connaissance** : sa clé de déballage est dérivée **sur l'appareil** à partir de la sortie WebAuthn PRF (`hmac-secret`) de l'authentificateur. Le serveur n'enregistre aucun passkey, n'émet aucun défi WebAuthn, et ne stocke aucun secret de récupération — il n'y a pas d'étape de libération côté serveur.

- **Enregistrement/assertion :** `BackupPasskeyCoordinator` (`LavaSecApp`) exécute WebAuthn via `ASAuthorizationPlatformPublicKeyCredentialProvider`, partie de confiance **`lavasecurity.app`**, en demandant l'extension PRF sur un sel par identifiant et en exigeant une vérification utilisateur.
- **Dérivation de clé (zéro connaissance) :** l'authentificateur renvoie une sortie PRF qui **ne quitte jamais l'appareil**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) dérive en HKDF-SHA256 la clé d'emballage du slot à partir de cette sortie PRF (info `"LavaSec passkey backup PRF v1"`) et emballe la clé de payload en AES-GCM ; seuls le sel PRF non secret et l'ID d'identifiant sont conservés dans le slot. À la restauration, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` ré-asserte l'identifiant pour reproduire la même sortie PRF, et `decryptWithPasskeyPRFOutput` déballe le slot localement. Le serveur ne détient **aucun** secret passkey, donc aucun chemin par rôle de service ne peut récupérer une sauvegarde protégée par passkey.

L'ancienne conception par séquestre (une table `backup_passkey_recovery` à rôle de service détenant un `recovery_secret` côté serveur, plus une table `backup_passkey_challenges` et des endpoints Worker `/v1/backup/passkeys/*`) a été **Abandonnée** : les tables ont été retirées dans une migration backend, le Worker ne porte aucune route passkey, et `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` affirme positivement que `BackupPasskeyRecoveryService` et tout chemin de séquestre serveur sont absents. **(Implémenté)**

> **Réserve sur la maturité pour la production :** traiter les passkeys enregistrés comme un facteur récupérable pleinement prêt pour la production sur des appareils physiques dépend encore de l'association webcredentials pour `lavasecurity.app`. La moitié iOS est déclarée — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` porte `webcredentials:lavasecurity.app` — et la moitié serveur (le fichier `apple-app-site-association` et les en-têtes) est désormais hébergée sur le site marketing. Tant que cette association ne se résout pas sur un appareil donné, le chemin d'association webcredentials peut échouer et fait remonter `BackupPasskeyError.webCredentialsAssociationUnavailable`. Le facteur passkey lui-même est implémenté ; sa maturité de bout en bout sur du vrai matériel est **Prévue**.

---

## 5. Minimisation des données et posture de confidentialité {#5-data-minimization-privacy-posture}

- **Compte facultatif.** La protection fonctionne sans compte ; la connexion active uniquement la sauvegarde des réglages.
- **Texte en clair local uniquement.** Le téléphone est le seul endroit où existent les réglages en clair et les secrets de déchiffrement ; Supabase détient une enveloppe opaque par utilisateur.
- **Payload minimisé.** Seuls les réglages du §3.2 sont sauvegardés ; `isPaid`, les drapeaux QA, les diagnostics, les instantanés, et les octets complets des listes de blocage sont exclus. Les listes de blocage sont référencées par ID de catalogue, jamais intégrées.
- **Aucune télémétrie de navigation/DNS.** Il n'y a aucune table côté serveur pour les requêtes DNS de routine ou la télémétrie par domaine ; le filtrage reste sur l'appareil.
- **Le matériel de déverrouillage est local à l'appareil.** Le matériel de déverrouillage de la sauvegarde est stocké avec une accessibilité `…ThisDeviceOnly` et n'est **pas** synchronisé iCloud. Ça **a inversé** la conception du plan d'origine avec Keychain synchronisable, donc Lava ne synchronise pas silencieusement le matériel de déverrouillage via iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implémenté ; inverse le plan antérieur.)**

### Suppression de compte {#account-deletion}

La suppression est **Implémentée** et passe par un endpoint Worker authentifié, pas par des suppressions directes côté client. `AccountAuthService.deleteAccount` envoie l'access token de l'utilisateur vers `POST /v1/account/delete` ; le Worker `lavasec-api` (rôle de service) supprime les `bug_reports` de l'utilisateur (et leurs pièces jointes R2), les `user_backups`, `entitlements`, `user_settings`, et les lignes `profiles`, puis supprime l'utilisateur Supabase Auth via l'API admin, en ne renvoyant qu'un statut de suppression + les fournisseurs liés. L'app se déconnecte ensuite localement et efface le matériel de déverrouillage de la sauvegarde (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Note : la frontmatter YAML du plan de suppression lit déjà `status: Done` et le plan vit dans `plans/implemented/`. Une annotation **dans le corps** périmée lit `Status: Backlog.`, mais selon la règle du dossier de voie (le dossier fait foi) et la présence du code (l'app et le Worker existent tous deux), la fonctionnalité est **Implémentée** ; la ligne dans le corps est un bug de doc, pas la frontmatter.

---

## 6. Récapitulatif des statuts {#6-status-summary}

| Domaine | Détail | Statut |
|---|---|---|
| Connexion `id_token` Apple / Google via Supabase | Flux natifs, nonce haché, échange par URLRequest brute | Implémenté |
| Connexion e-mail/mot de passe | Possession des mots de passe rejetée | Abandonné |
| Session dans le Keychain (local à l'appareil, par fournisseur) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implémenté |
| Enveloppe AES-256-GCM + emplacements de clé PBKDF2-HMAC-SHA256 (210k) | Côté client ; uniquement texte chiffré + métadonnées non secrètes vers `user_backups` (RLS) | Implémenté |
| Configuration sans mot de passe (slots appareil + récupération assistée + passkey optionnel) | `makePasswordless` | Implémenté |
| Slot de clé mot de passe dans le flux en production | Survit dans `LavaSecCore` pour les tests uniquement | Abandonné |
| Phrase de récupération (8 mots CVCV, environ 105 bits) | Facteur hors appareil | Implémenté |
| Récupération assistée (partage serveur + phrase via SHA256, délimité par NUL) | Deux facteurs ; aucune moitié seule | Implémenté |
| Récupération par passkey (zéro connaissance, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | Slot HKDF dérivé de la sortie PRF, aucun secret serveur | Implémenté |
| Passkey comme facteur prêt pour la production sur matériel | Nécessite l'association webcredentials (AASA hébergé sur le site marketing) | Prévu |
| Suppression de compte (Worker authentifié, rôle de service) | Retire sauvegardes/réglages/droits/profil/pièces jointes + utilisateur Auth | Implémenté |
| Barrière biométrique/présence utilisateur sur le matériel de déverrouillage | Point de revue avant publication | Prévu |
| Extraction d'`EncryptedBackupCoordinator` hors d'`AppViewModel` | Modularisation seule ; aucun changement du modèle de sécurité | En cours |

---

## Voisins {#related}

- [Vue d'ensemble du système](./system-overview.md) — tout le système sur un seul écran, y compris les frontières de confiance.
- [Client iOS](./ios-client.md) — `AppViewModel` et les cibles d'app qui pilotent la sauvegarde.
- [Backend et données](./backend-and-data.md) — le Worker `lavasec-api`, la RLS Supabase, et le stockage `user_backups`.
- [Filtrage DNS et listes de blocage](./dns-filtering-and-blocklists.md) — les préréglages de résolveur et les transports dont les réglages sont transportés dans le payload de sauvegarde.
