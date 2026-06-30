# Parité entre plateformes {#platform-parity}

Le système de parité entre plateformes de Lava suit quelles promesses produit
sont communes à iOS, Android et aux futurs clients. C'est le contrat public du
comportement des fonctionnalités : ce qui doit vouloir dire la même chose
partout, ce qui est volontairement propre à chaque OS, et ce qui n'est pas
encore promis.

Les docs de parité ne remplacent pas les plans d'implémentation ni les tests.

- `lavasec-doc` est le contrat produit et comportemental.
- Les plans internes gèrent l'état de livraison, le séquencement, les risques
  privés et la synchro avec le comité.
- Les dépôts de plateforme contiennent le code, les fixtures et les tests qui
  prouvent le comportement.

Quand les docs et le code livré ne sont pas d'accord, le code l'emporte tant que
les docs n'ont pas été mis à jour. Quand un plan et cette page divergent, traitez
cette page comme le contrat produit et le plan comme la file de travaux.

## Vocabulaire des statuts {#status-vocabulary}

| Statut | Signification |
|---|---|
| **Livré** | Implémenté dans le code de production pour cette plateforme. |
| **Partiel** | Une partie du comportement existe, mais le contrat public n'est pas pleinement respecté. |
| **Prévu** | Accepté comme faisant partie du contrat de plateforme, pas encore implémenté. |
| **Reporté** | Fonctionnalité valable, mais pas requise pour la prochaine étape de plateforme. |
| **Propre à la plateforme** | Même promesse pour l'utilisateur, mais implémentation spécifique à l'OS. |
| **Non applicable** | Aucune fonctionnalité équivalente ne devrait exister sur cette plateforme. |
| **Abandonné** | Envisagé ou construit autrefois, puis retiré volontairement. |

## Format d'une fiche de fonctionnalité {#feature-record-format}

Chaque fonctionnalité suivie en parité devrait avoir un identifiant stable.
Utilisez des noms du type `domaine.capacité` qui survivent aux changements de
texte d'interface, par exemple `filtering.guardrail-precedence` ou
`dns.encrypted-transports`.

Une fiche de fonctionnalité complète répond à :

| Champ | Rôle |
|---|---|
| `feature_id` | Identifiant stable utilisé dans les plans, les PR, les tests et les docs. |
| Promesse produit | Ce sur quoi les utilisateurs peuvent compter, dans un langage neutre vis-à-vis de la plateforme. |
| Exigence de parité | Si Android doit reproduire iOS exactement, le reproduire par intention, ou rester volontairement différent. |
| Statut par plateforme | État sur iOS, Android et les futurs clients. |
| Garanties | Tests, fixtures, fichiers source ou revues qui garantissent le comportement. |
| Notes par plateforme | Différences spécifiques à l'OS qui doivent être explicites, et non redécouvertes plus tard. |

## Procédure de mise à jour {#update-workflow}

1. Ajoutez ou mettez à jour l'identifiant de fonctionnalité quand un changement
   modifie une promesse produit, une garantie de confidentialité, une frontière
   entre offres ou un comportement multi-plateforme.
2. Reliez le même identifiant depuis le plan d'implémentation quand du travail
   est nécessaire.
3. Ajoutez ou mettez à jour les tests de plateforme ou les fixtures de référence
   pour le comportement qui doit correspondre.
4. Quand une plateforme livre le comportement, mettez à jour le statut ici et
   actualisez la page de fonctionnalité ou d'architecture concernée.
5. Gardez privés les détails internes purement liés à l'implémentation, aux
   sujets confidentiels, aux prix, aux risques juridiques et à l'exploitation ;
   ne résumez ici que le contrat public.

## Registre de parité actuel {#current-parity-ledger}

| Identifiant | Promesse produit | iOS | Android | Exigence de parité | Garanties / source |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava filtre le DNS localement sur l'appareil et ne fait pas passer la navigation par les serveurs de Lava. | Livré | Prévu | Parité par intention ; les API de tunnel de l'OS diffèrent. | Architecture du packet tunnel iOS ; plan `VpnService` Android. |
| `protection.vpn-disclosure` | L'app explique pourquoi l'OS qualifie le filtrage DNS local de VPN avant de demander l'autorisation/la configuration du VPN. | Livré | Prévu | Texte et flux d'autorisation propres à la plateforme. | Docs d'intégration ; plan de divulgation pour le Play Store Android. |
| `filtering.guardrail-precedence` | Les garde-fous toujours actifs l'emportent sur les listes d'autorisation des utilisateurs ; le statut payant ne contourne jamais les garde-fous. | Livré | Prévu | Parité de comportement exacte. | `CompactFilterSnapshotTests` ; `FilterSnapshotTest` Android une fois porté. |
| `filtering.source-url-only-catalog` | Lava publie les métadonnées du catalogue et les URL des sources en amont, pas les octets des listes de blocage tierces. | Livré | Prévu | Parité exacte du modèle de confidentialité/propriété intellectuelle. | Architecture du catalogue ; docs juridiques GPL/URL-source-uniquement. |
| `filtering.on-device-parsing` | Les listes sélectionnées sont récupérées et analysées sur l'appareil ; l'historique de domaines courant n'est pas envoyé à Lava. | Livré | Prévu | Parité de confidentialité exacte, stockage natif autorisé. | `BlocklistParserTests` ; tests de parité de l'analyseur Android une fois portés. |
| `filtering.rule-budget` | Les limites de filtres reposent sur le nombre de règles compilées et la sécurité de l'appareil, pas sur un nombre de listes arbitraire. | Livré | Prévu | Même modèle côté utilisateur ; les plafonds mémoire peuvent différer selon la plateforme. | Tests du quota de filtres iOS ; tests de quota Android une fois les limites des appareils connues. |
| `dns.built-in-resolvers` | Les utilisateurs peuvent choisir des résolveurs prédéfinis intégrés sans envoyer à Lava les requêtes autorisées. | Livré | Prévu | Même politique de résolveur ; l'ensemble des préréglages peut sortir par étapes. | Tests des résolveurs prédéfinis ; tests des DTO de résolveur Android une fois portés. |
| `dns.encrypted-transports` | Un DNS amont chiffré est disponible pour les requêtes autorisées. | Livré | Prévu | Parité progressive autorisée ; la v1 Android peut démarrer avec DoH avant DoT/DoQ. | Tests de transport iOS ; tests de résolveur Android et QA sur appareil. |
| `reports.local-only-diagnostics` | Les rapports et diagnostics restent locaux, sauf si l'utilisateur envoie explicitement un paquet de support. | Livré | Prévu | Parité de confidentialité exacte ; l'interface peut différer. | Tests du paquet de rapport de bug ; tests d'aperçu du rapport de débogage Android une fois construits. |
| `account.optional-sign-in` | La protection fonctionne sans compte ; la connexion est facultative. | Livré | Reporté | Promesse produit exacte avant qu'Android n'expose des fonctions de compte. | Docs d'authentification de compte ; revue de l'intégration/des réglages Android. |
| `backup.zero-knowledge-settings` | La sauvegarde facultative des réglages ne stocke que du texte chiffré ; Lava ne peut pas lire le contenu en clair de la sauvegarde. | Livré | Reporté | Parité de confidentialité exacte avant qu'Android ne propose la sauvegarde. | Tests de sauvegarde à divulgation nulle ; tests de parité crypto Android une fois construits. |
| `plus.customization-boundary` | La protection gratuite reste utile ; Plus débloque la personnalisation avancée et ne change jamais la sécurité des garde-fous. | Livré | Prévu | Même frontière produit ; l'implémentation du store est propre à la plateforme. | Tests de la politique d'abonnement ; tests des droits Play Billing une fois construits. |
| `design.calm-earned-depth` | L'UX par défaut est apaisée, les surfaces plus techniques ou festives n'apparaissant que lorsqu'elles sont méritées ou demandées. | Partiel | Prévu | Parité par intention de design via des tokens/rôles partagés. | Docs du design system et plan de fondation pour la portabilité. |
| `platform.ambient-presence` | Le statut de protection peut apparaître hors de l'app quand l'OS propose une surface ambiante native. | Propre à la plateforme | Prévu | Parité d'intention, pas de surface. | Docs Live Activity iOS ; décision notification/Réglages rapides Android en attente. |

## Usage pour la préparation d'Android {#android-readiness-use}

Avant que l'implémentation Android ne commence, cette page devrait être relue aux
côtés du plan Android et du plan de portabilité du design system. Le contrat
minimal pour être prêt pour Android est le suivant :

- chaque fonctionnalité touchant à la confidentialité a un identifiant ;
- le comportement à parité exacte a une source de test ou de fixture iOS identifiée ;
- le comportement propre à la plateforme a une position Android explicite ;
- les fonctionnalités reportées sont nommées pour que le MVP Android ne laisse
  pas accidentellement croire qu'elles sont livrées.

Cette relecture a sa place dans le plan d'implémentation ou les notes de revue,
tandis que cette page conserve le contrat public et durable.
