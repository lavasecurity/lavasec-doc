---
hide_feedback: true
---

# Lava Security Dokumentation

Lava Security ist eine **iOS-App mit Fokus auf Privatsphäre**, die DNS direkt auf
dem Gerät filtert — über einen lokalen NetworkExtension-Paket-Tunnel. So werden
bekannte gefährliche und unerwünschte Domains blockiert, ohne dass dein Surfen
über die Server von Lava läuft.

!!! quote "Das Versprechen zur Privatsphäre"
    Die DNS-Filterung passiert lokal auf deinem Gerät. Lava erhält deine
    alltäglichen DNS-Anfragen, deinen Browserverlauf oder Telemetriedaten zu
    einzelnen Domains nie, und jedes optionale Konto-Backup ist
    Ende-zu-Ende verschlüsselt — Lava kann also immer nur den verschlüsselten
    Text speichern.

Diese Seite ist das öffentliche Handbuch dafür, wie Lava funktioniert — die
Architektur, das Verhalten und die Entscheidungen dahinter. Sie folgt dem
quelloffenen [iOS-Client](https://github.com/lavasecurity/lavasec-ios).

## Hier anfangen {#start-here}

<div class="grid cards" markdown>

-   :material-rocket-launch: **Produkt**

    Was Lava macht und für wen es gedacht ist.

    [Überblick](product/overview.md) · [Funktionskatalog](product/features.md) ·
    [Plattform-Gleichstand](product/platform-parity.md)

-   :material-sitemap: **Architektur**

    Wie das ganze System zusammenpasst.

    [Systemüberblick](architecture/system-overview.md) ·
    [iOS-Client](architecture/ios-client.md) ·
    [DNS-Filterung & Blocklisten](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **Innenleben zur Privatsphäre**

    Die Teile, die das Versprechen zur Privatsphäre tragen.

    [Backend & Daten](architecture/backend-and-data.md) ·
    [Konten & Zero-Knowledge-Backup](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Entscheidungen & Compliance**

    Warum es so gebaut ist.

    [Wichtige Entscheidungen (ADRs)](decisions/key-decisions.md) ·
    [Hinweise zu Drittanbietern](legal/third-party-notices.md)

</div>

## So liest du das hier {#how-to-read-this}

Jede Aussage hier ist im Quellcode verankert. Der Status ist überall markiert:

| Status | Bedeutung |
|---|---|
| **Umgesetzt** | Im ausgelieferten Code vorhanden |
| **In Arbeit** | Wird gerade gebaut |
| **Geplant** | Eine Richtung, noch nicht gebaut |
| **Verworfen** | Dagegen entschieden — fürs Protokoll behalten |

Wenn die Doku und der Code sich widersprechen, gewinnt der Code. Diese Doku ist
eine Momentaufnahme, die aus dem Quellcode neu erzeugt wird, während sich das
Produkt weiterentwickelt.

Das plattformübergreifende Verhalten wird im
[Plattform-Gleichstand](product/platform-parity.md) verfolgt: Dort stehen stabile
Feature-IDs, der Status je Plattform und die Tests oder Fixtures, die iOS und
Android aufeinander abgestimmt halten sollen.
