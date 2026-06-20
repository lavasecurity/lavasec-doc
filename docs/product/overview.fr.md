---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Vue d'ensemble du produit {#product-overview}

Bienvenue chez Lava Security. Cette page est la porte d'entrée de toute la documentation : une introduction courte et toute simple pour comprendre ce qu'est Lava, ce qu'il promet, et où aller pour en savoir plus.

## Ce qu'est Lava {#what-lava-is}

Lava Security est une application iOS qui place la confidentialité avant tout. Elle filtre le DNS directement sur l'appareil, via un [tunnel de paquets NetworkExtension](../architecture/ios-client.md) embarqué, et bloque les domaines connus comme risqués ou indésirables — sans jamais faire passer votre navigation par les serveurs de Lava. Le tunnel de paquets (`LavaSecTunnel`, un `NEPacketTunnelProvider`) analyse chaque requête DNS sur le téléphone, compare le domaine demandé à un instantané de filtre compilé et mappé en mémoire, puis ne transmet en amont que les requêtes autorisées. Aucun proxy géré par Lava ne voit passer votre trafic : le filtrage est une décision locale, prise sur votre appareil.

iOS appelle ça un « VPN » parce qu'un tunnel de paquets est le seul moyen pour une app de filtrer le DNS à l'échelle de tout le système — mais Lava fait du **filtrage DNS/par liste de blocage**, pas du routage de trafic. Soyons honnêtes sur la portée : Lava filtre les domaines DNS en local, ce qui **n'est pas** une garantie que tous les domaines ou toutes les URL malveillantes seront bloqués. Il voit les domaines, pas les chemins des pages : il ne peut donc pas bloquer une seule page douteuse sur un hôte par ailleurs fiable. La protection ne s'active pas non plus toute seule à la fin de la configuration — l'onglet **Protection** dans l'app reste la référence pour savoir si la protection est active à un moment donné.

## La promesse de confidentialité {#the-privacy-promise}

> Tout le filtrage DNS se passe sur l'appareil ; Lava ne fait jamais passer votre navigation par ses serveurs et ne reçoit jamais le flux des domaines que vous visitez — le backend ne conserve que les métadonnées du catalogue, une sauvegarde chiffrée opaque propre à chaque utilisateur, et les diagnostics anonymisés que vous choisissez d'envoyer.

Cette phrase fait foi. Tout le reste de cette documentation est censé s'y conformer. Payer pour l'offre optionnelle ne déplace **pas** le filtrage vers le serveur et ne donne pas à Lava un flux des domaines visités. Quand une fonctionnalité touche à un serveur, la documentation précise ce qui n'est **pas** envoyé — vos requêtes DNS courantes, votre historique de navigation et tout contenu en clair restent sur l'appareil. Voir [le backend et le modèle de données](../architecture/backend-and-data.md) pour le tableau complet.

## À qui ça s'adresse {#who-it-is-for}

Lava est fait pour quiconque veut naviguer plus sereinement sans avoir à s'en occuper. Le public visé inclut volontairement les personnes non techniques — des parents qui mettent en place une protection pour la famille, des personnes âgées, et toute personne qui ne veut tout simplement pas penser au DNS. L'expérience par défaut marche toute seule : activez la protection et une liste de blocage prudente commence à filtrer, sans qu'aucun compte ne soit nécessaire. En même temps, les utilisateurs avertis peuvent accéder à des réglages plus poussés (listes de blocage personnalisées, autres résolveurs) quand ils le souhaitent.

Le ton, partout, reste simple, posé et concret — le danger est présenté comme une métaphore, pas comme une source de peur.

## Principes fondateurs {#core-principles}

- **La confidentialité est notre positionnement, pas une fonctionnalité payante.** Le filtrage est une décision locale. Le backend de Lava est volontairement minimal et ne reçoit jamais vos domaines de navigation courants ni vos flux d'événements DNS. La sauvegarde de compte optionnelle est [à divulgation nulle de connaissance](../architecture/accounts-and-backup.md) : les serveurs ne stockent que du texte chiffré et des métadonnées d'enveloppe non secrètes.
- **La protection de base, gratuite pour toujours.** L'interrupteur de protection, les mises à jour de la liste de blocage par défaut et les compteurs locaux de base ne sont jamais réservés à une offre payante et n'exigent jamais de compte.
- **Tout sur l'appareil.** Le moteur de protection vit entièrement sur le téléphone — analyse du DNS, évaluation des domaines et transmission en amont, tout se passe à l'intérieur de l'extension tunnel de paquets, dans la limite du plafond mémoire iOS d'environ 50 Mio par extension. Les listes de blocage suivent un modèle [uniquement par URL source](../architecture/dns-filtering-and-blocklists.md) : l'app récupère chaque liste en amont directement et la traite en local ; Lava n'héberge ni ne sert jamais les octets de listes de blocage tierces.
- **Le paiement débloque la personnalisation, jamais la sécurité de base.** Le garde-fou de sécurité — un niveau non contournable au-dessus de toutes les listes de blocage, que personne, payant ou non, ne peut mettre en liste d'autorisation — est appliqué par ordre de priorité des décisions : **garde-fou de sécurité > liste d'autorisation locale (exceptions autorisées) > liste de blocage > autorisation par défaut.** (Cet emplacement de priorité est en place et son intégrité est vérifiée par des hachages SHA-256 acceptés ; pour l'instant il est livré sans aucune entrée.) Le tunnel ignore `isPaid`.
- **Un cœur apaisant, une profondeur qui se mérite.** Les surfaces par défaut sont calmes et rassurantes, mises en avant par la mascotte Soft Shield Guardian et des textes qui évitent le langage anxiogène. Des détails plus riches et techniques sont disponibles quand vous allez les chercher, mais ne vous sont jamais imposés. Cette philosophie du « cœur apaisant, profondeur méritée » est formalisée dans le modèle de profondeur **LavaTier** (Floor / Window / Workshop) — voir [le design system](../design-system/overview.md).

## Capacités générales {#high-level-capabilities}

- **Filtrage DNS local** — le moteur du tunnel de paquets qui analyse le DNS, évalue chaque domaine par rapport à l'instantané compilé, et transmet en amont les requêtes autorisées, avec repli sur le DNS de l'appareil. Voir [le client iOS](../architecture/ios-client.md) et [le filtrage DNS et les listes de blocage](../architecture/dns-filtering-and-blocklists.md).
- **Listes de blocage sélectionnées, uniquement par URL source** — Lava ne publie que les URL des listes en amont et les hachages acceptés ; l'appareil récupère, valide et traite les octets de la liste lui-même, et Lava ne réplique ni ne sert jamais les octets de listes de blocage tierces. La valeur par défaut livrée active **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, défini dans `OnboardingDefaults.swift`) ; les sources GPL (HaGeZi, OISD) sont en option. Voir [le filtrage DNS et les listes de blocage](../architecture/dns-filtering-and-blocklists.md).
- **Transports DNS chiffrés** — DoH (avec annotation DoH3 à titre d'observation), DoT (connexions mutualisées, réutilisées et rafraîchies) et DoQ (une connexion neuve par requête). Les trois sont implémentés ; le DNS de l'appareil (le résolveur du réseau lui-même) est la valeur par défaut livrée, et les préréglages chiffrés sont en option (`AppConfiguration.lavaRecommendedDefaults`, défini dans `Sources/LavaSecCore/OnboardingDefaults.swift`). Les préréglages de résolveur intégrés (variantes DoH et DoT de Google / Cloudflare / Quad9) sont gratuits ; seul un résolveur entièrement personnalisé est un déblocage payant. Voir [le filtrage DNS et les listes de blocage](../architecture/dns-filtering-and-blocklists.md).
- **Exceptions autorisées (liste d'autorisation)** — ajoutez manuellement des domaines à autoriser malgré une liste de blocage ; le garde-fou de sécurité l'emporte toujours. Voir [la vue d'ensemble des fonctionnalités](features.md).
- **Le Soft Shield Guardian** — une mascotte présente sur l'onglet Protection, dans la Live Activity et le Dynamic Island, qui exprime l'état de la protection à travers 7 états d'expression. Voir [le design system](../design-system/overview.md).
- **Personnalisation par paliers (Lava Security Plus)** — une seule offre payante optionnelle qui débloque la personnalisation (un quota de règles de filtrage plus large — gratuit 500 K / Plus 2 M de règles compilées sous un garde-fou de sécurité commun à l'appareil — plus de domaines autorisés/bloqués, des listes de blocage personnalisées et des résolveurs DNS personnalisés). Plus ne contourne jamais les garde-fous toujours actifs — le tunnel ignore `isPaid`.
- **Comptes et sauvegarde optionnels** — connexion avec Apple ou Google, avec une sauvegarde des réglages chiffrée de bout en bout ([à divulgation nulle de connaissance](../architecture/accounts-and-backup.md)) et une phrase de récupération ; la suppression du compte se fait en libre-service. L'emplacement optionnel de récupération par passkey est **lui aussi à divulgation nulle de connaissance** — sa clé est dérivée sur l'appareil à partir du PRF WebAuthn de l'authentificateur, sans aucun secret détenu par le serveur ; sa mise en production sur l'appareil dépend encore de l'hébergement Associated Domains / AASA **(Prévu)**. Les comptes sont optionnels ; la protection fonctionne pleinement sans être connecté.
- **Activité et rapports locaux uniquement** — compteurs de blocage/autorisation sur l'appareil, état de santé du tunnel et un lot de rapport de bug avec consentement, construits à partir de données que le tunnel en cours conserve sur l'appareil — vides au repos et vivants pendant la protection. Aucun historique de domaines courant ne quitte l'appareil. Voir [la vue d'ensemble des fonctionnalités](features.md).

## Plateformes {#platforms}

- **iOS — livré.** Lava est une app iOS aujourd'hui : trois bundles partagent un même App Group (`group.com.lavasec`) — l'app (`com.lavasec.app`), l'extension tunnel de paquets (`.tunnel`) et le widget (`.widget`) — plus des sources partagées, au-dessus d'un package commun `LavaSecCore`.
- **Android — Prévu.** Un portage natif Kotlin / Jetpack Compose au-dessus du `VpnService` d'Android est prévu, portant la même promesse de confidentialité et un comportement de filtrage de base testé pour la parité. Aucun code d'app Android n'est livré pour l'instant.

Voir [Parité entre plateformes](platform-parity.md) pour les identifiants de fonctionnalités stables et le contrat iOS/Android.
