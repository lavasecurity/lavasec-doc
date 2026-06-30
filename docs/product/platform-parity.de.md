# Plattform-Parität {#platform-parity}

Das Plattform-Paritätssystem von Lava hält fest, welche Produktversprechen plattformübergreifend gelten – also auf
iOS, Android und künftigen Clients. Es ist der öffentliche Vertrag darüber, wie sich Funktionen
verhalten: was überall dasselbe bedeuten muss, was bewusst plattformeigen ist und was noch gar nicht versprochen wird.

Die Paritätsdocs ersetzen weder Umsetzungspläne noch Tests.

- `lavasec-doc` ist die Heimat des Produkt- und Verhaltensvertrags.
- Interne Pläne kümmern sich um den Lieferstatus, die Reihenfolge, vertrauliche Risiken und den
  Abgleich mit dem Board.
- Die Plattform-Repositories enthalten Code, Fixtures und Tests, die das Verhalten belegen.

Wenn Docs und ausgelieferter Code sich widersprechen, gewinnt der Code, bis die Docs aktualisiert sind.
Wenn ein Plan und diese Seite sich widersprechen, gilt diese Seite als Produktvertrag und
der Plan als Arbeitsliste.

## Status-Vokabular {#status-vocabulary}

| Status | Bedeutung |
|---|---|
| **Shipped** | Im Produktivcode dieser Plattform umgesetzt. |
| **Partial** | Ein Teil des Verhaltens existiert, aber der öffentliche Vertrag ist noch nicht ganz erfüllt. |
| **Planned** | Als Teil des Plattformvertrags akzeptiert, aber noch nicht umgesetzt. |
| **Deferred** | Sinnvolle Funktion, aber für den nächsten Plattform-Meilenstein nicht erforderlich. |
| **Platform-native** | Gleiches Nutzerversprechen, je nach Betriebssystem unterschiedlich umgesetzt. |
| **Not applicable** | Auf dieser Plattform sollte es kein entsprechendes Feature geben. |
| **Dropped** | Früher erwogen oder gebaut, dann bewusst entfernt. |

## Format der Feature-Einträge {#feature-record-format}

Jedes paritätsrelevante Feature sollte eine stabile Feature-ID haben. Verwende
`area.capability`-Namen, die UI-Textänderungen überdauern, zum Beispiel
`filtering.guardrail-precedence` oder `dns.encrypted-transports`.

Ein vollständiger Feature-Eintrag beantwortet:

| Feld | Zweck |
|---|---|
| `feature_id` | Stabile ID, die in Plänen, PRs, Tests und Docs verwendet wird. |
| Produktversprechen | Worauf sich Nutzer verlassen können, in plattformneutraler Sprache. |
| Paritätsanforderung | Ob Android iOS exakt nachbilden, nur sinngemäß nachbilden oder bewusst anders bleiben muss. |
| Plattform-Status | Stand auf iOS, Android und künftigen Clients. |
| Absicherung | Tests, Fixtures, Quelldateien oder Review-Checks, die das Verhalten ehrlich halten. |
| Plattform-Hinweise | Betriebssystemspezifische Unterschiede, die ausdrücklich genannt sein müssen und nicht erst später entdeckt werden sollen. |

## Aktualisierungs-Workflow {#update-workflow}

1. Lege eine Feature-ID an oder aktualisiere sie, wenn eine Änderung ein Produktversprechen,
   eine Datenschutzaussage, eine Tarifgrenze oder ein plattformübergreifendes Verhalten betrifft.
2. Verlinke dieselbe Feature-ID aus dem Umsetzungsplan, sobald Arbeit ansteht.
3. Ergänze oder aktualisiere Plattform-Tests oder Golden-Fixtures für Verhalten, das übereinstimmen muss.
4. Sobald eine Plattform das Verhalten ausliefert, aktualisiere hier den Status und überarbeite die
   passende Feature- oder Architekturseite.
5. Halte reine Umsetzungs-, vertrauliche, Preis-, Rechtsrisiko- und betriebliche
   interne Details privat; fasse hier nur den öffentlichen Vertrag zusammen.

## Aktuelles Paritäts-Ledger {#current-parity-ledger}

| Feature-ID | Produktversprechen | iOS | Android | Paritätsanforderung | Absicherung / Quelle |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava filtert DNS lokal auf dem Gerät und leitet das Surfen nicht über Lava-Server um. | Shipped | Planned | Sinngemäße Parität; die Tunnel-APIs der Betriebssysteme unterscheiden sich. | iOS-Packet-Tunnel-Architektur; Android-`VpnService`-Plan. |
| `protection.vpn-disclosure` | Die App erklärt, warum das Betriebssystem das lokale DNS-Filtern ein VPN nennt, bevor sie nach der VPN-Berechtigung/-Konfiguration fragt. | Shipped | Planned | Plattformeigener Text und Berechtigungsablauf. | Onboarding-Docs; Android-Play-Offenlegungsplan. |
| `filtering.guardrail-precedence` | Immer aktive Schutzbarrieren setzen sich über erlaubte Domains der Nutzer hinweg; ein bezahlter Status umgeht die Schutzbarrieren nie. | Shipped | Planned | Exakte Verhaltensparität. | `CompactFilterSnapshotTests`; Android-`FilterSnapshotTest` nach der Portierung. |
| `filtering.source-url-only-catalog` | Lava veröffentlicht Katalog-Metadaten und Upstream-Quell-URLs, nicht die Bytes fremder Blocklisten. | Shipped | Planned | Exakte Parität beim Datenschutz-/IP-Modell. | Katalog-Architektur; GPL-/Source-URL-only-Rechtsdocs. |
| `filtering.on-device-parsing` | Ausgewählte Listen werden auf dem Gerät geladen und verarbeitet; der normale Domainverlauf wird nicht zu Lava hochgeladen. | Shipped | Planned | Exakte Datenschutzparität, native Speicherung erlaubt. | `BlocklistParserTests`; Android-Parser-Paritätstests nach der Portierung. |
| `filtering.rule-budget` | Filtergrenzen richten sich nach der Anzahl kompilierter Regeln und der Gerätesicherheit, nicht nach einer willkürlichen Listenanzahl. | Shipped | Planned | Gleiches Modell für Nutzer; die Speichergrenzen der Plattformen können sich unterscheiden. | iOS-Filterbudget-Tests; Android-Budget-Tests, sobald die Gerätegrenzen bekannt sind. |
| `dns.built-in-resolvers` | Nutzer können eingebaute Resolver-Voreinstellungen wählen, ohne erlaubte Abfragen an Lava zu senden. | Shipped | Planned | Gleiche Resolver-Richtlinie; das Set an Voreinstellungen kann in Phasen starten. | Resolver-Voreinstellungs-Tests; Android-Resolver-DTO-Tests nach der Portierung. |
| `dns.encrypted-transports` | Verschlüsseltes Upstream-DNS steht für erlaubte Abfragen zur Verfügung. | Shipped | Planned | Schrittweise Parität erlaubt; Android v1 darf mit DoH starten, bevor DoT/DoQ folgen. | iOS-Transport-Tests; Android-Resolver-Tests und Geräte-QA. |
| `reports.local-only-diagnostics` | Berichte und Diagnosen bleiben lokal, es sei denn, der Nutzer schickt ausdrücklich ein Support-Paket. | Shipped | Planned | Exakte Datenschutzparität; die UI darf abweichen. | Fehlerberichts-Paket-Tests; Android-Debug-Report-Vorschau-Tests, sobald gebaut. |
| `account.optional-sign-in` | Der Schutz funktioniert ohne Konto; die Anmeldung ist optional. | Shipped | Deferred | Exaktes Produktversprechen, bevor Android Kontofunktionen anbietet. | Konto-Auth-Docs; Android-Onboarding-/Einstellungs-Review. |
| `backup.zero-knowledge-settings` | Das optionale Einstellungs-Backup speichert nur Chiffretext; Lava kann den Klartext des Backups nicht lesen. | Shipped | Deferred | Exakte Datenschutzparität, bevor Android ein Backup anbietet. | Zero-Knowledge-Backup-Tests; Android-Krypto-Paritätstests, sobald gebaut. |
| `plus.customization-boundary` | Der kostenlose Schutz bleibt nützlich; Plus schaltet erweiterte Anpassung frei und ändert nie die Sicherheit der Schutzbarrieren. | Shipped | Planned | Gleiche Produktgrenze; die Store-Umsetzung ist plattformeigen. | Abo-Richtlinien-Tests; Play-Billing-Berechtigungstests, sobald gebaut. |
| `design.calm-earned-depth` | Die Standard-UX ist ruhig; tiefere technische oder feierliche Oberflächen erscheinen nur, wenn man sie sich verdient oder anfordert. | Partial | Planned | Sinngemäße Parität über gemeinsame Tokens/Rollen. | Design-System-Docs und Portabilitäts-Fundamentplan. |
| `platform.ambient-presence` | Der Schutzstatus kann auch außerhalb der App erscheinen, wenn das Betriebssystem eine native Ambient-Oberfläche unterstützt. | Platform-native | Planned | Parität in der Absicht, nicht in der Oberfläche. | iOS-Live-Activity-Docs; Android-Entscheidung zu Benachrichtigung/Quick Settings steht aus. |

## Nutzung für die Android-Bereitschaft {#android-readiness-use}

Bevor die Android-Umsetzung startet, sollte diese Seite zusammen mit dem
Android-Plan und dem Design-System-Portabilitätsplan durchgesehen werden. Der minimale Android-fertige
Vertrag lautet:

- jedes datenschutzrelevante Feature hat eine Feature-ID;
- Verhalten mit exakter Parität hat eine benannte iOS-Test- oder Fixture-Quelle;
- plattformeigenes Verhalten hat eine ausdrückliche Android-Haltung;
- verschobene Features sind benannt, damit das Android-MVP nicht versehentlich nahelegt,
  dass sie ausgeliefert werden.

Diese Durchsicht gehört in den Umsetzungsplan oder die Review-Notizen; diese Seite
bewahrt den öffentlichen, dauerhaften Vertrag.
