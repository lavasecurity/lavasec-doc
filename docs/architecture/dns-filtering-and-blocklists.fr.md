---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Filtrage DNS et listes de blocage

> Public : ingénieurs. Ce document décrit le pipeline DNS qui tourne sur l'appareil, le chemin du résolveur avec transport chiffré, le moteur de décision du filtrage, et le modèle de catalogue de listes de blocage basé uniquement sur les URL sources — avec les chiffres exacts que le code fait respecter. Le statut reflète ce que le code fait vraiment. Quand un plan et le code se contredisent, **c'est le code qui gagne**, et l'écart est signalé sur place.

Tout le filtrage DNS se passe sur l'appareil ; Lava ne fait jamais transiter votre navigation par ses serveurs et ne reçoit jamais le flux des domaines que vous visitez — le backend ne garde que les métadonnées du catalogue, une sauvegarde chiffrée opaque propre à chaque utilisateur, et les diagnostics anonymisés que vous choisissez d'envoyer.

Lava, c'est du **filtrage DNS/liste de blocage local**, et non la garantie que chaque domaine ou URL malveillant sera bloqué.

---

## 1. Le pipeline DNS (Implémenté) {#1-the-dns-pipeline-implemented}

Le moteur de filtrage/résolution tourne à l'intérieur du **tunnel de paquets NE** — l'extension `NEPacketTunnelProvider` nommée `LavaSecTunnel` (`com.lavasec.app.tunnel`), qui n'intercepte que le DNS. Les adresses du tunnel sont `10.255.0.2` (tunnel) et `10.255.0.1` (serveur DNS). Le processus de l'app ne voit jamais le trafic des requêtes ; il se contente d'écrire les artefacts compilés dans l'**App Group** (`group.com.lavasec`) et de prévenir le tunnel via des **provider messages** NETunnelProviderSession (et non des notifications Darwin).

Pour chaque requête DNS entrante, le tunnel applique un **ordre de priorité** figé dans `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`) :

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **Le bootstrap d'abord, c'est une règle absolue.** Une requête qui résout le nom d'hôte *du résolveur configuré lui-même* (le point de terminaison DoH/DoT/DoQ) ne doit jamais être bloquée ni mise en pause, sinon le tunnel ne pourrait pas du tout établir le DNS chiffré. Le dispatcher prend des closures paresseuses, donc chaque étape n'est lue que lorsqu'on y arrive, ce qui préserve le court-circuit (pas de lecture du snapshot quand une réponse de bootstrap existe ; pas de lecture de la pause pendant le bootstrap).
- La **mise en pause temporaire** transmet la requête en amont tant qu'une pause TTL déclenchée par l'utilisateur est active.
- Le **filtre** évalue le domaine par rapport au snapshot compilé et soit le transmet, soit fabrique une réponse de blocage.

Une requête qui passe le filtre (action `.allow`) est confiée au chemin du résolveur (§3). Au démarrage à froid sans snapshot réutilisable, le tunnel **se ferme par sécurité** : il installe un snapshot d'exécution « fermé par sécurité » qui bloque tout le trafic plutôt que de résoudre sans filtre.

---

## 2. Le moteur de filtrage (Implémenté) {#2-the-filtering-engine-implemented}

### 2.1 Ordre de priorité des décisions {#21-decision-precedence}

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) applique l'ordre de priorité de sécurité canonique :

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Ordre | Jeu de règles | Résultat | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | bloquer | `.threatGuardrail` |
| 2 | `allowRules` | autoriser | `.localAllowlist` |
| 3 | `blockRules` | bloquer | `.blocklist` |
| 4 | — | autoriser | `.defaultAllow` |

Un domaine qui échoue à la normalisation est bloqué avec la raison `.invalidDomain` (par sécurité). Le même ordre de priorité est reproduit dans la forme binaire stockée sur disque (`CompactFilterSnapshot`). Le garde-fou de sécurité passe avant la liste autorisée locale, et c'est voulu : **un paiement ne contourne jamais le garde-fou de sécurité non-contournable**, et une exception de l'utilisateur ne peut pas débloquer un domaine du garde-fou.

> Note : dans l'état actuel du dépôt de travail, `nonAllowableThreatRules` / `guardrailSources` sont vides (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`) ; la place dans l'ordre de priorité est câblée et appliquée, mais elle est livrée sans aucune entrée de garde-fou pour l'instant.

### 2.2 Le stockage des règles et l'unité de mémoire résidente {#22-rule-storage-and-the-resident-memory-unit}

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) stocke les ensembles `exactDomains` + `suffixDomains`. La correspondance (`containsNormalized`) fait une recherche exacte plus un parcours des suffixes parents (façon `hasSuffix`) au moment de la requête — il n'y a **aucune absorption des sous-domaines à la compilation**. Une ligne wildcard valide = **une règle** et une entrée dans la table mémoire. C'est cette identité 1 ligne = 1 règle qui fait du nombre de règles la mesure honnête des ressources (§4).

### 2.3 Les formes du snapshot compilé {#23-compiled-snapshot-forms}

- **`FilterSnapshot`** — le filtre compilé en mémoire : `blockRules`, `allowRules`, `nonAllowableThreatRules`, et le préréglage du résolveur.
- **`CompactFilterSnapshot`** — la forme binaire sur disque, adaptée au mmap, que le tunnel lit réellement (magic `LSCFSNP1`, `fileVersion 1`). Elle est chargée sans copie via mmap (§4.3).

L'app écrit à la fois `filter-snapshot.json` et `filter-snapshot.compact` dans l'App Group ; le tunnel décode l'artefact compact. Un chemin de **réutilisation au démarrage à chaud** (`FilterArtifactStore`) permet au tunnel de réutiliser l'artefact compact sur disque sans recompiler, sous réserve d'une empreinte d'identité + d'un manifeste écrit de façon atomique ; la réutilisation est refusée (sans risque pour la vie privée, avec une raison limitée au nom de champ) quand le transport du résolveur, la couverture du catalogue ou les entrées du snapshot changent.

---

## 3. Transports chiffrés et chemin du résolveur (Implémenté) {#3-encrypted-transports--the-resolver-path-implemented}

### 3.1 L'enum de transport {#31-transport-enum}

Les requêtes non bloquées sont transmises au résolveur en amont configuré. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) a **cinq** valeurs :

| Transport | Valeur brute | Annotation affichée dans l'UI |
|---|---|---|
| DNS de l'appareil | `device-dns` | *(aucune — le nom est le transport)* |
| DNS simple | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

Les préréglages intégrés sont Google, Cloudflare, Quad9, Mullvad (chacun en variantes IP / DoH / DoT) plus le DNS de l'appareil et le mode personnalisé. Les résolveurs personnalisés acceptent un serveur IPv4/IPv6 simple, une URL DoH, une URL DoT (`tls://` / `dot://`), une URL DoQ (`doq://` / `quic://`), ou un DNS stamp `sdns://` ; les noms d'utilisateur/mots de passe et localhost sont refusés. DoH/DoT/DoQ utilisent par défaut le port `853` pour DoT/DoQ et exigent un chemin pour DoH.

### 3.2 DoH / DoH3 {#32-doh--doh3}

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) exécute le DoH par-dessus `URLSession`. Chaque requête active HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`) ; le loader d'Apple bascule nativement vers H2/H1, donc ça ne rend jamais injoignable un résolveur qui l'était. Le protocole négocié est lu depuis `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN : `h3`, `h2`, `http/1.1`).

L'UI annote **`DoH3` (sans slash)** — par exemple « Quad9 (DoH3) » — **uniquement quand une négociation h3 est réellement observée** (`DoHHTTPVersion.dohAnnotation`) ; sinon elle affiche `DoH`. DoH3 est préféré, jamais promis : le label est une observation, propre au résolveur, et n'est jamais conservé (le report d'un « DoH3 confirmé » d'un redémarrage à l'autre a été annulé). Les requêtes envoient en POST du `application/dns-message` ; les réponses sont validées en type de contenu et en longueur, et l'ID de transaction est restauré avant la réécriture.

### 3.3 DoT {#33-dot}

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) utilise un pool de `NWConnection`, **jusqu'à 4 connexions par point de terminaison** (`maxConnectionsPerEndpoint = 4`), en round-robin, pour que les requêtes en parallèle évitent le blocage en tête de file. Il gère la **péremption en inactivité** : des fournisseurs comme Cloudflare ferment côté serveur les connexions DoT inactives (~10 s) sans signaler de changement d'état, donc une connexion réutilisée restée inactive plus de **8 secondes** (`reusedConnectionMaxIdleInterval = 8`) est rafraîchie avant l'envoi, et un timeout sur une connexion réutilisée vaut **exactement un nouvel essai avec une connexion neuve**.

### 3.4 DoQ — une connexion neuve par requête {#34-doq--fresh-connection-per-query}

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) garde un pool borné de **4 voies par point de terminaison**, mais **chaque requête ouvre une connexion QUIC neuve** — un handshake complet par requête. Le pool de 4 voies fournit de la **concurrence, pas de la réutilisation de handshake**.

**Statut de la réutilisation de connexion DoQ (Abandonné / reporté).** La réutilisation a été étudiée et mesurée sur appareil (34 handshakes neufs sur 35 requêtes ≈ aucune réutilisation), puis implémentée sous forme d'un chemin multi-flux `NWConnectionGroup` réservé à iOS 26, testée sur appareil contre AdGuard DoQ, et **annulée car globalement négative** (échecs de flux + erreurs de repli face à un vrai serveur). RFC 9250 fait correspondre chaque requête à son propre flux QUIC, donc la réutilisation exige `NWConnectionGroup`/`openStream`, qui est **disponible uniquement sur iOS 26.0+** ; le plancher de déploiement actuel est **iOS 17**. La réutilisation est reportée jusqu'à ce que le plancher atteigne iOS 26. Le DoQ personnalisé est refusé sur les appareils qui ne le prennent pas en charge (« DNS over QUIC is not supported on this device »).

### 3.5 La politique de résolution {#35-resolution-policy}

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) gère la politique en amont :

1. **Routage du transport** selon le transport configuré.
2. **Repli vers le DNS simple** quand un plan chiffré n'a aucun point de terminaison.
3. **Bascule par point de terminaison** avec un verrou de backoff — un point de terminaison en backoff ne touche jamais le réseau (résultat `backed-off`).
4. **Repli sur le DNS de l'appareil** quand le résolveur principal ne renvoie aucune réponse *et* que le plan l'autorise (la propriété du plan est `shouldFallbackToDeviceDNS`, dérivée du champ de config `fallbackToDeviceDNS`) ; le résultat est ré-annoté comme le transport de l'appareil. L'exécution réseau est injectée derrière des executors pour que la politique soit testable unitairement ; l'état de backoff reste en dehors de la politique pure.

---

## 4. Quota des règles de filtrage, plafond NE et mmap {#4-filter-rules-budget-ne-ceiling-and-mmap}

La mesure de niveau qui est livrée, c'est le **quota des règles de filtrage** : le total des **règles** de domaine compilées qu'un utilisateur peut activer. Elle remplace l'ancien plafond sur le **nombre** de listes activées (3 en gratuit / 10 en payant), qui était un indicateur trompeur — une liste peut faire 1 K comme 1 M de règles. Il y a **deux couches** : un garde-fou d'appareil pour tout le monde, et une limite de monétisation par niveau, en dessous.

### 4.1 Limites par niveau (Implémenté) {#41-tier-limits-implemented}

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) fait foi :

| Niveau | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Listes de blocage / DNS personnalisés |
|---|---|---|---|---|
| **Gratuit** | **500 000** | 25 | 25 | Non |
| **Plus** (`.paid` / `.plus`) | **2 000 000** | 1 000 | 1 000 | Oui |

La limite de niveau est une frontière de monétisation, **jamais un paywall sur le garde-fou de l'appareil**. **Lava Security Plus** débloque seulement la personnalisation — jamais la sécurité de base, jamais le garde-fou de sécurité. Les listes de blocage personnalisées (payantes) sont récupérées directement depuis l'appareil de l'utilisateur, analysées et mises en cache localement, et ne transitent jamais par les serveurs de Lava.

### 4.2 Garde-fou mémoire de l'appareil + plafond NE (Implémenté) {#42-device-memory-guardrail--ne-ceiling-implemented}

Le tunnel de paquets est soumis au **plafond mémoire iOS de ~50 Mio par extension** (une limite de conception de l'OS par type d'extension pour les tunnels de paquets depuis iOS 15, qui ne s'adapte pas à la RAM ; elle vit dans un fichier `com.apple.jetsamproperties.{Model}.plist` propre au modèle d'appareil et peut être plus basse sur les anciens appareils). Le dépasser déclenche le jetsam. Il n'y a aucune API pour connaître ce plafond, donc le quota garde une marge sous la falaise.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) fait le calcul, exprimé en règles de filtrage (block + allow + garde-fou) :

| Constante | Valeur |
|---|---|
| `baselineMegabytes` | 4,0 Mo (surcoût fixe du processus, mesuré ≈ 3,5 Mo, arrondi au-dessus) |
| `estimatedBytesPerRule` | 9,0 o de résident sali par règle (mesuré ≈ 8,5 o, arrondi au-dessus) |
| `maxResidentMegabytes` | 32,0 Mo (plafond cible, laissant ~10 Mo de marge sous la falaise de jetsam observée à ~40–46 Mo) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1 048 576) / 9 = 3 262 236 règles** |

Ce **garde-fou d'appareil de ~3,26 M de règles** est le seuil de sécurité absolu pour *chaque* utilisateur, il se situe au-dessus de tout niveau d'abonnement, et n'est **jamais un paywall**. Mesure de référence (appareil « chimmy », 2026-06-13) : **789 831 règles → 9,9 Mo de `phys_footprint`**, soit ≈ baseline + coût par règle.

### 4.3 La stratégie mmap (Implémenté) {#43-mmap-strategy-implemented}

Le snapshot compact est chargé avec `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), et `CompactBinaryReader` renvoie des tranches sans copie. Le gros blob de texte de domaines de plusieurs Mo reste **adossé au fichier / propre** et est exclu du `phys_footprint` compté par le jetsam ; seules les tables `[Entry]` décodées coûtent de la mémoire résidente (~6 o/règle sur disque, ~8,5 o de résident sali). Ça repousse le plafond de domaines sur l'appareil : le coût résident, ce sont les tables d'entrées, pas l'artefact entier.

### 4.4 Application sur deux couches (Implémenté) {#44-two-layer-enforcement-implemented}

- **Faisant autorité (à la compilation).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) applique le quota sur l'**union dédupliquée** de toutes les listes activées. Le garde-fou de l'appareil est vérifié **en premier** (le seuil absolu) ; la limite de niveau s'applique en dessous. Les configs hors quota sont rejetées de façon déterministe — `exceedsDeviceMemoryBudget` ou `exceedsTierFilterRuleLimit` — plutôt que de laisser le tunnel se faire jetsam. L'erreur nomme les deux plus grosses listes qui contribuent, pour que la correction soit évidente.
- **Indicative (UI au moment de la sélection).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) alimente la jauge de sélection à partir d'une **somme** par liste, avec une **marge de plafond souple de 1,10** qui compense le sur-comptage inter-listes de ~7–10 % (la somme par liste surestime l'union dédupliquée).

### 4.5 Le parseur (Implémenté) {#45-the-parser-implemented}

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) compte les règles au pied de la lettre : il jette les commentaires/lignes vides/lignes invalides, normalise, dédup les chaînes exactes à l'intérieur d'une liste (via un `Set`), et plafonne à **`maxRules = 1 000 000`** par liste (par défaut), avec une longueur de ligne max de 4 096 caractères. Formats pris en charge : `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (le mode `auto` essaie hosts → dnsmasq → adblock → plain). Une ligne valide = une règle = l'unité de mémoire.

> **Lignes `hosts` multi-hôtes (version 2 des règles d'analyse).** Une ligne `hosts` qui associe une même IP à plusieurs hôtes (`0.0.0.0 a.com b.com c.com`) émet désormais **chaque** hôte comme sa propre règle, pas seulement le premier ; `maxRules` est appliqué **par règle** (et non par ligne) pour qu'une ligne multi-hôtes proche du plafond ne puisse pas le dépasser. Comme les mêmes octets en amont peuvent désormais produire plus de règles, la version des règles du parseur est passée de **1 à 2**, ce qui invalide les entrées périmées de `RuleSetCache` analysées sous l'ancien comportement « premier hôte uniquement ».

### 4.6 Robustesse du téléchargement et du décodage (Implémenté) {#46-download--decode-robustness-implemented}

Le tunnel et la synchro du catalogue tournent à l'intérieur du budget mémoire NE, donc l'ingestion des listes est durcie contre les entrées hostiles ou malformées :

- **Téléchargements en flux.** `defaultDataFetcher` télécharge les octets de la liste vers un fichier temporaire via `URLSession.download` (pic mémoire borné) avec une vérification de taille après téléchargement (`maximumBlocklistBytes`) plutôt que de tamponner tout le corps en RAM ; un corps surdimensionné lève `BlocklistDownloadSizeLimitExceeded`.
- **Plafond des métadonnées du catalogue (8 Mo).** `BlocklistCatalogRepository.maximumCatalogBytes` rejette un catalogue distant surdimensionné avant le décodage, pour qu'un hôte hostile/MITM ne puisse pas forcer un décodage JSON en OOM dans l'extension.
- **Décodage UTF-8 indulgent.** Un seul octet UTF-8 invalide ne rejette plus une liste entière (ce qui, en fail-closed, bloquerait tout le DNS) ; les octets invalides deviennent U+FFFD et seule la ligne fautive échoue à la validation par ligne et est écartée.
- **Erreurs nommées pour les listes de blocage personnalisées.** Une liste personnalisée en échec fait désormais remonter `customBlocklistUnavailable(displayName:reason:)` — « Impossible de charger la liste de blocage personnalisée '<nom>'. <pourquoi> » — au lieu d'une `URLError` brute ; une annulation est propagée comme une annulation, pas comme un échec de téléchargement.

---

## 5. Le catalogue de listes de blocage et les sources par défaut {#5-blocklist-catalog--default-sources}

### 5.1 Le modèle de catalogue (Implémenté) {#51-catalog-model-implemented}

Le **catalogue de listes de blocage** est la liste publiée des sources disponibles. Le **Worker lavasec-api** sert les métadonnées JSON depuis un bucket R2 sur `GET /v1/catalog` (et `/v1/catalog/:version`) ; l'appareil récupère les **octets** de la liste elle-même directement depuis chaque `source_url` en amont. Les points de terminaison du catalogue iOS sont `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

Sur l'appareil, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`) :

1. Récupère les octets de la liste directement depuis `source.sourceURL`, en appliquant un plafond de taille.
2. Calcule le SHA-256 et n'accepte les octets que si la somme de contrôle figure dans les `accepted_source_hashes` du catalogue.
3. En cas de non-correspondance, revient au dernier cache local valide, ou **se ferme par sécurité** (`checksumMismatch`) — sauf si la source autorise explicitement la rotation directe en amont.
4. Analyse / normalise / dédup localement.
5. Filtre chaque jeu de règles analysé à travers `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`) pour qu'une liste en amont ne puisse jamais bloquer les domaines de Lava / Apple / fournisseur d'identité.

L'**ensemble des domaines protégés** (filtrés avant l'activation) : `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (tous en correspondance de suffixe). Le Worker applique un filtre `PROTECTED_SUFFIXES` équivalent au moment de calculer les métadonnées ; l'appareil revalide de toute façon.

### 5.2 Sources sélectionnées (Implémenté) {#52-curated-sources-implemented}

`DefaultCatalog.curatedSources` (`BlocklistModels.swift:232-243`) liste **10** sources :

| Source | Licence |
|---|---|
| Block List Basic | Unlicense |
| Block List Project Phishing | Unlicense |
| Block List Project Scam | Unlicense |
| Block List Project Ransomware | Unlicense |
| Phishing.Database Active Domains | MIT |
| HaGeZi Multi Light | GPL-3.0 |
| HaGeZi Multi Normal | GPL-3.0 |
| HaGeZi Multi PRO mini | GPL-3.0 |
| HaGeZi Multi PRO | GPL-3.0 |
| OISD Small | GPL-3.0 |

`guardrailSources` est vide. Les sources GPL (HaGeZi, OISD) sont visibles dans le catalogue mais **optionnelles / DÉSACTIVÉES par défaut** en attendant l'aval du service juridique ; le Worker limite la synchro/publication au lancement à `source_url_only` plus les préfixes GPL autorisés (`hagezi-` / `oisd-`).

### 5.3 Listes activées par défaut pour les utilisateurs gratuits (Implémenté) {#53-default-enabled-lists-for-free-users-implemented}

La vraie config par défaut en gratuit est `OnboardingDefaults.lavaRecommendedDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`), qui active **Block List Project Phishing + Block List Project Scam**, avec le préréglage de résolveur DNS de l'appareil (`resolverPresetID = DNSResolverPreset.device.id`) et le repli sur le DNS de l'appareil activé.

Ce défaut gratuit est **produit par `defaultEnabled`**, il n'est pas codé en dur. `blockListProjectPhishing` (`BlocklistModels.swift:139`) et `blockListProjectScam` (`BlocklistModels.swift:148`) mettent tous les deux `defaultEnabled: true`, et `DefaultCatalog.recommendedDefaultSourceIDs` (`BlocklistModels.swift:250-252`) est dérivé de `curatedSources.filter(\.defaultEnabled)`. Le commentaire dans le code (`BlocklistModels.swift:246-249`) appelle `defaultEnabled` « la source de vérité unique pour le défaut à l'installation fraîche », ce qui reflète la colonne `default_enabled` du catalogue côté backend. En passant par `recommendedDefaultSourceIDs` jusqu'à `OnboardingDefaults`, `defaultEnabled` est le mécanisme vivant — il suffit de basculer le flag sur une source pour changer le défaut.

> **Source de vérité du défaut (c'est le code qui gagne).** Tout texte de plan/catalogue qui dit « Block List Basic est le seul défaut » est faux pour l'appareil ; l'appareil livre Phishing + Scam via `defaultEnabled: true`, et le flag iOS `BlocklistSource.defaultEnabled` est le mécanisme vivant qui fait autorité. La colonne `default_enabled` du catalogue backend a été réalignée sur le même ensemble Phishing + Scam par une migration, donc les métadonnées servies par `/v1/catalog` correspondent maintenant au client. Le texte « Listes de blocage activées 3 → 10 » du site public est encore **périmé** — la vraie barrière, c'est le quota des règles de filtrage de 500 K / 2 M, pas un nombre de listes.

### 5.4 Modèle de distribution GPL basé uniquement sur l'URL source (Implémenté) {#54-source-url-only-gpl-distribution-model-implemented}

**Source-url-only** est le modèle de distribution conforme GPL / propriété intellectuelle : Lava ne publie que l'URL en amont + les hashes acceptés ; l'appareil récupère et analyse les listes lui-même. Lava ne stocke, ne miroite, ne transforme et ne sert **jamais** les octets des listes de blocage tierces. Ça **remplace la conception abandonnée de miroir R2** (le plan d'origine « miroir R2 brut » a été annulé le 2026-05-25).

Côté Worker, `syncOneBlocklist` récupère chaque source en amont, la normalise et la hashe (en calculant `source_hash`, `normalized_hash`, `entry_count`) mais écrit `raw_r2_key = null` / `normalized_r2_key = null` — seules les métadonnées JSON du catalogue arrivent dans R2. `check-gpl-blocklist-distribution.sh` est le garde-fou de CI qui fait respecter tout le modèle : aucun code de miroir/transformation, aucune URL d'artefact/téléchargement Lava, aucune source GPL activée par défaut, aucune écriture R2 d'octets de liste par le Worker, aucun texte « miroir hébergé par Lava », aucun `.txt`/`.json` GPL embarqué, et `source_url_only` exigé dans les migrations + les documents juridiques.

> **Note sur les licences :** le code Lava de première partie est livré sous **AGPL-3.0** (le fichier `LICENSE` est la GNU AGPL v3, en accord avec le badge du README). Les listes de blocage tierces (HaGeZi, OISD) restent en **GPL-3.0** sous leurs propres licences en amont — le modèle source-url-only existe précisément pour que Lava puisse les utiliser sans jamais redistribuer d'octets sous licence GPL. La GPL-3.0 ici est une propriété des listes en amont, pas de l'app Lava.

---

## 6. Récapitulatif des statuts {#6-status-summary}

| Domaine | Statut |
|---|---|
| Ordre de priorité des requêtes DNS (bootstrap > pause > filtre) | Implémenté |
| Ordre de priorité des décisions de filtrage (garde-fou > liste autorisée > liste de blocage > autorisation par défaut) | Implémenté |
| Place du garde-fou de sécurité dans l'ordre de priorité (câblée ; livrée sans entrées pour l'instant) | Implémenté |
| DoH / DoH3 (label h3 par observation) | Implémenté |
| DoT (pool de 4/point de terminaison, rafraîchissement à 8 s d'inactivité, un nouvel essai neuf) | Implémenté |
| DoQ (connexion neuve par requête, concurrence sur 4 voies) | Implémenté |
| Réutilisation de connexion DoQ | Abandonné / reporté au plancher iOS 26 |
| Repli du résolveur + bascule par point de terminaison + repli sur le DNS de l'appareil | Implémenté |
| Quota des règles de filtrage (Gratuit 500 K / Plus 2 M) | Implémenté |
| Garde-fou d'appareil de ~3,26 M de règles (cible 32 Mo sous le plafond NE de 50 Mio) | Implémenté |
| mmap sans copie du snapshot compact | Implémenté |
| Catalogue source-url-only + récupération directe en amont + validation par hash | Implémenté |
| Filtre des domaines protégés | Implémenté |
| Défaut gratuit = Phishing + Scam (pas Basic) | Implémenté (catalogue réaligné pour correspondre) |
| Licence du code Lava de première partie | AGPL-3.0 (`LICENSE`) ; les listes tierces restent en GPL-3.0 en amont |

---

## Voir aussi {#see-also}

- [`../product/overview.md`](../product/overview.md) — la phrase d'accroche produit, la promesse de confidentialité, les onglets.
- Niveaux et monétisation (référence interne) — Lava Security Plus et le quota des règles de filtrage comme mesure de niveau.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — la décision de conformité source-url-only.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — les licences et attributions des listes de blocage / résolveurs en amont.
