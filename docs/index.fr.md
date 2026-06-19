---
hide_feedback: true
---

# Documentation Lava Security {#lava-security-documentation}

Lava Security est une **application iOS qui place la confidentialité avant tout** : elle filtre le DNS localement sur
l'appareil grâce à un tunnel par paquets NetworkExtension qui tourne directement sur le téléphone — elle bloque les
domaines connus comme risqués ou indésirables sans faire passer votre navigation par les serveurs de Lava.

!!! quote "La promesse de confidentialité"
    Le filtrage DNS se fait localement sur votre appareil ; Lava ne reçoit jamais vos
    requêtes DNS de tous les jours, votre historique de navigation ni la moindre donnée domaine par domaine, et toute
    sauvegarde de compte facultative est chiffrée de bout en bout — autrement dit, Lava ne peut jamais stocker
    que du texte chiffré.

Ce site est le manuel public qui explique comment Lava fonctionne : son architecture, son
comportement et les choix qui sont derrière. Il suit de près le
[client iOS](https://github.com/lavasecurity/lavasec-ios) open source.

## Par où commencer {#start-here}

<div class="grid cards" markdown>

-   :material-rocket-launch: **Produit**

    Ce que fait Lava et à qui ça s'adresse.

    [Vue d'ensemble](product/overview.md) · [Catalogue des fonctionnalités](product/features.md) ·
    [Parité entre plateformes](product/platform-parity.md)

-   :material-sitemap: **Architecture**

    Comment l'ensemble du système s'assemble.

    [Vue d'ensemble du système](architecture/system-overview.md) ·
    [Client iOS](architecture/ios-client.md) ·
    [Filtrage DNS et listes de blocage](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **Les coulisses de la confidentialité**

    Les éléments qui portent la promesse de confidentialité.

    [Backend et données](architecture/backend-and-data.md) ·
    [Comptes et sauvegarde à connaissance nulle](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Décisions et conformité**

    Pourquoi c'est construit comme ça.

    [Décisions clés (ADR)](decisions/key-decisions.md) ·
    [Mentions tierces](legal/third-party-notices.md)

</div>

## Comment lire cette documentation {#how-to-read-this}

Chaque affirmation ici s'appuie sur le code source. Le statut est indiqué partout :

| Statut | Signification |
|---|---|
| **Implémenté** | Présent dans le code livré |
| **En cours** | En cours de construction |
| **Prévu** | Une orientation, pas encore construite |
| **Abandonné** | Écarté — conservé pour mémoire |

Quand la doc et le code se contredisent, c'est le code qui a raison. Cette doc est un instantané,
régénéré à partir du code source à mesure que le produit évolue.

Le comportement multiplateforme est suivi dans [Parité entre plateformes](product/platform-parity.md) :
on y trouve les identifiants de fonctionnalités stables, le statut par plateforme et les tests ou jeux de données qui
doivent garder iOS et Android alignés.
