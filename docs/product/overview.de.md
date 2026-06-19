---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Produktübersicht {#product-overview}

Willkommen bei Lava Security. Diese Seite ist der Einstieg in die gesamte Doku: eine kurze, leicht verständliche Einführung in das, was Lava ist, was es verspricht und wo du mehr nachlesen kannst.

## Was Lava ist {#what-lava-is}

Lava Security ist eine iOS-App, bei der Datenschutz an erster Stelle steht. Sie filtert DNS direkt auf dem Gerät über einen lokalen [NetworkExtension-Pakettunnel](../architecture/ios-client.md) und blockiert bekannte riskante und unerwünschte Domains, ohne dein Surfen über die Server von Lava zu leiten. Der Pakettunnel (`LavaSecTunnel`, ein `NEPacketTunnelProvider`) wertet jede DNS-Anfrage auf dem Handy aus, gleicht die angefragte Domain mit einem kompilierten, speicherabgebildeten Filter-Snapshot ab und leitet nur erlaubte Anfragen nach außen weiter. Es gibt keinen von Lava betriebenen Proxy, durch den dein Datenverkehr läuft: Das Filtern ist eine lokale Entscheidung, die auf deinem Gerät getroffen wird.

iOS bezeichnet das als "VPN", weil ein Pakettunnel die einzige Möglichkeit für eine App ist, DNS systemweit zu filtern — aber Lava ist **DNS-/Blocklisten-Filterung**, kein Umleiten von Datenverkehr. Sei ehrlich, was den Umfang angeht: Lava filtert lokal DNS-Domains und ist **keine** Garantie dafür, dass wirklich jede schädliche Domain oder URL blockiert wird. Lava sieht Domains, nicht einzelne Seitenpfade, und kann deshalb keine einzelne schlechte Seite auf einem ansonsten vertrauenswürdigen Host blockieren. Der Schutz ist außerdem nicht automatisch an, sobald die Einrichtung fertig ist — der **Schutz**-Tab in der App ist die maßgebliche Stelle, an der du siehst, ob der Schutz gerade aktiv ist.

## Das Datenschutzversprechen {#the-privacy-promise}

> Das gesamte DNS-Filtern passiert auf dem Gerät; Lava leitet dein Surfen nie über seine Server und bekommt nie den Strom der Domains, die du besuchst — das Backend hält nur Katalog-Metadaten, ein undurchsichtiges, pro Nutzer verschlüsseltes Backup und anonymisierte Diagnosedaten, die du selbst zum Senden auswählst.

Dieser Satz ist verbindlich. Alles andere in dieser Doku soll dazu passen. Wenn du für die optionale Stufe bezahlst, wandert das Filtern **nicht** auf den Server und Lava bekommt auch keinen Strom deiner besuchten Domains. Wenn eine Funktion einen Server berührt, schreibt die Doku ausdrücklich auf, was **nicht** gesendet wird — deine alltäglichen DNS-Anfragen, dein Browserverlauf und jeglicher Klartext bleiben alle auf dem Gerät. Das ganze Bild findest du unter [Backend und Datenmodell](../architecture/backend-and-data.md).

## Für wen es gedacht ist {#who-it-is-for}

Lava ist für alle gemacht, die sicherer surfen wollen, ohne sich darum kümmern zu müssen. Zur Zielgruppe gehören ganz bewusst auch nicht-technische Leute — Eltern, die Schutz für die Familie einrichten, ältere Menschen und alle, die über DNS überhaupt nicht nachdenken wollen. Die Standarderfahrung funktioniert einfach: Schutz einschalten, und schon fängt eine vorsichtig gewählte Blockliste an zu filtern — ganz ohne Konto. Gleichzeitig kommen Power-User an tiefere Einstellungen (eigene Blocklisten, andere Resolver), wenn sie das möchten.

Der Ton ist durchgehend schlicht, ruhig und praktisch — Gefahr wird als Bild beschrieben, nicht als Angstmacherei.

## Grundprinzipien {#core-principles}

- **Datenschutz ist Haltung, keine kostenpflichtige Funktion.** Das Filtern ist eine lokale Entscheidung. Das Backend von Lava ist bewusst minimal und bekommt nie deine alltäglichen Browser-Domains oder DNS-Ereignisströme. Das optionale Konto-Backup ist [Zero-Knowledge](../architecture/accounts-and-backup.md): Die Server speichern nur Chiffretext und nicht-geheime Umschlag-Metadaten.
- **Kostenloser Basisschutz für immer.** Der Schutzschalter, die Updates der Standard-Blockliste und die einfachen lokalen Zähler sind nie eingeschränkt und brauchen nie ein Konto.
- **Auf dem Gerät.** Die Schutz-Engine lebt komplett auf dem Handy — das Auswerten von DNS, das Bewerten der Domains und das Weiterleiten nach außen passiert alles innerhalb der Pakettunnel-Erweiterung, begrenzt durch das iOS-Limit von rund 50 MiB Speicher pro Erweiterung. Blocklisten folgen einem [Modell, das nur Quell-URLs nutzt](../architecture/dns-filtering-and-blocklists.md): Die App holt jede vorgelagerte Liste direkt und wertet sie lokal aus; Lava hostet oder liefert nie die Blocklisten-Bytes Dritter.
- **Bezahlen schaltet nur Anpassungen frei — nie die grundlegende Sicherheit.** Die Schutzbarriere — eine nicht-erlaubbare Ebene über jeder Blockliste, die niemand, egal ob zahlend oder nicht, auf die Erlaubt-Liste setzen kann — wird über eine Entscheidungsreihenfolge durchgesetzt: **Schutzbarriere > lokale Erlaubt-Liste (Erlaubte Ausnahmen) > Blockliste > standardmäßig erlauben.** (Der Platz in der Reihenfolge ist verdrahtet und per akzeptierter SHA-256-Hashes integritätsgeprüft; aktuell wird er ohne Einträge ausgeliefert.) Der Tunnel ignoriert `isPaid`.
- **Ruhiger Kern, verdiente Tiefe.** Die Standardoberflächen sind leise und beruhigend, vorne dran die Soft-Shield-Guardian-Maskottchen-Figur und Texte, die auf angstmachende Sprache verzichten. Reichere, technischere Details gibt es, wenn du sie suchst, aber sie werden dir nie aufgedrängt. Diese Philosophie "ruhiger Kern, verdiente Tiefe" ist im **LavaTier**-Tiefenmodell (Floor / Window / Workshop) festgehalten — siehe [das Designsystem](../design-system/overview.md).

## Funktionen im Überblick {#high-level-capabilities}

- **Lokale DNS-Filterung** — die Pakettunnel-Engine, die DNS auswertet, jede Domain gegen den kompilierten Snapshot prüft und erlaubte Anfragen mit Geräte-DNS-Ausweichoption nach außen weiterleitet. Siehe [den iOS-Client](../architecture/ios-client.md) und [DNS-Filterung und Blocklisten](../architecture/dns-filtering-and-blocklists.md).
- **Kuratierte Blocklisten, nur über Quell-URLs** — Lava veröffentlicht nur die URLs vorgelagerter Listen plus akzeptierte Hashes; das Gerät holt, prüft und wertet die Listen-Bytes selbst aus, und Lava spiegelt oder liefert nie die Blocklisten-Bytes Dritter. Der ausgelieferte Standard aktiviert **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definiert in `OnboardingDefaults.swift`); GPL-Quellen (HaGeZi, OISD) sind optional zuschaltbar. Siehe [DNS-Filterung und Blocklisten](../architecture/dns-filtering-and-blocklists.md).
- **Verschlüsselte DNS-Transporte** — DoH (mit beobachtender DoH3-Annotation), DoT (gepoolte Verbindungen, wiederverwendet und aufgefrischt) und DoQ (frische Verbindung pro Anfrage). Alle drei sind umgesetzt; Geräte-DNS (der Resolver des Netzwerks selbst) ist der ausgelieferte Standard, und die verschlüsselten Voreinstellungen sind optional zuschaltbar (`AppConfiguration.lavaRecommendedDefaults`, definiert in `Sources/LavaSecCore/OnboardingDefaults.swift`). Die eingebauten Resolver-Voreinstellungen (Google / Cloudflare / Quad9 in DoH- und DoT-Varianten) sind kostenlos; nur ein vollständig eigener Resolver ist eine kostenpflichtige Freischaltung. Siehe [DNS-Filterung und Blocklisten](../architecture/dns-filtering-and-blocklists.md).
- **Erlaubte Ausnahmen (Erlaubt-Liste)** — füge Domains von Hand hinzu, die trotz einer Blockliste erlaubt sein sollen; die Schutzbarriere gewinnt trotzdem. Siehe [die Übersicht der Produktfunktionen](features.md).
- **Der Soft Shield Guardian** — eine Maskottchen-Figur im Schutz-Tab, in der Live Activity und in der Dynamic Island, die den Schutzzustand über 7 Ausdruckszustände zeigt. Siehe [das Designsystem](../design-system/overview.md).
- **Gestufte Anpassung (Lava Security Plus)** — eine optionale kostenpflichtige Stufe, die Anpassungen freischaltet (ein größeres Budget für Filterregeln — kostenlos 500K / Plus 2M kompilierte Regeln unter einer gemeinsamen Schutzbarriere auf dem Gerät — mehr erlaubte/blockierte Domains, eigene Blocklisten und eigene DNS-Resolver). Plus umgeht nie die immer aktiven Schutzbarrieren — der Tunnel ignoriert `isPaid`.
- **Optionale Konten und Backup** — Anmeldung mit Apple oder Google samt Ende-zu-Ende-verschlüsseltem ([Zero-Knowledge](../architecture/accounts-and-backup.md)) Einstellungs-Backup und Wiederherstellungscode; das Löschen des Kontos geht selbst. Der optionale Passkey-Wiederherstellungsplatz ist **ebenfalls Zero-Knowledge** — sein Schlüssel wird auf dem Gerät aus der WebAuthn-PRF des Authentifikators abgeleitet, ohne ein vom Server gehaltenes Geheimnis; ob das auf dem Gerät produktiv einsatzbereit ist, hängt noch vom Hosting der Associated Domains / AASA ab **(Geplant)**. Konten sind optional; der Schutz funktioniert auch komplett abgemeldet.
- **Nur lokale Aktivität und Berichte** — Block-/Erlaubt-Zähler auf dem Gerät, Tunnel-Zustand und ein optionales Bug-Report-Paket, gebaut aus Daten, die der laufende Tunnel auf dem Gerät behält — leer im Ruhezustand und live, während geschützt wird. Kein alltäglicher Domainverlauf verlässt das Gerät. Siehe [die Übersicht der Produktfunktionen](features.md).

## Plattformen {#platforms}

- **iOS — ausgeliefert.** Lava ist heute eine iOS-App: Drei Bundles teilen sich eine App Group (`group.com.lavasec`) — die App (`com.lavasec.app`), die Pakettunnel-Erweiterung (`.tunnel`) und das Widget (`.widget`) — plus gemeinsame Quellen, über ein gemeinsames `LavaSecCore`-Paket.
- **Android — Geplant.** Eine native Kotlin-/Jetpack-Compose-Portierung über Androids `VpnService` ist geplant und trägt dasselbe Datenschutzversprechen sowie ein paritätsgeprüftes Kern-Filterverhalten. Es wird noch kein Android-App-Code ausgeliefert.

Siehe [Plattform-Parität](platform-parity.md) für die stabilen Feature-IDs und den iOS-/Android-Vertrag.
