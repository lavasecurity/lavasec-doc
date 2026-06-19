---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Design System

> **Zielgruppe:** Design + Engineering, die an der Lava Security iOS-App arbeiten.
> **Maßgeblich:** Wenn dieses Dokument und ein Plan sich widersprechen, **gewinnt der Code** — Abweichungen werden direkt im Text genannt. Der Status spiegelt die im Code bestätigte Realität wider, nicht das, was im Plan geplant war. Status-Legende: **Umgesetzt** (ausgeliefert und im Code bestätigt), **In Arbeit** (teilweise gelandet), **Geplant** (entworfen, aber noch nicht gebaut), **Verworfen** (abgelehnt oder zurückgenommen).

Dieses Dokument behandelt die Designphilosophie, das LavaTier-Tiefenvokabular, das Lava-Maskottchen, Texte und Namenskonventionen, die Onboarding-UX und die Internationalisierung. Für die architektonische Verkabelung hinter diesen Oberflächen (Targets, VPN-Lebenszyklus, das Lava-/Schutz-Zustandsmodell) siehe [den iOS-Client](../architecture/ios-client.md); für die Produkt-Einordnung siehe [die Produktübersicht](../product/overview.md).

---

## 1. Philosophie: ruhiger Kern, verdiente Tiefe {#1-philosophy-calm-core-earned-depth}

Lavas Zielgruppe sind nicht-technische Alltagsnutzer — Eltern, ältere Menschen — und das Design folgt daraus. Die Alltagsoberfläche „funktioniert einfach" und bleibt für alle ruhig; zusätzliche Details, Freude und Kontrolle tauchen erst dann auf (sind also **verdient**), wenn die Nutzerin danach sucht. Nichts nervt, nichts schreckt auf, und das technische Innenleben bleibt unsichtbar, bis man danach sucht.

Dieses Modell **„ruhiger Kern, verdiente Tiefe"** lässt sich in drei Produkt-Tiefen auflösen:

- **Calm** — der Standard, der Schutz, der einfach funktioniert und den alle zuerst sehen.
- **Celebratory** — freiwilliges Bewusstsein und Freude (Serien, Freischaltungen, Erfolgsmomente). Nervt nie.
- **Technical** — DNS, Diagnose und Statistiken. Unsichtbar, bis die Nutzerin danach sucht.

Zwei übergreifende Paletten-/Ton-Regeln stützen die ruhige Haltung:

- **Rot = nur Gefahr.** Rot ist ausschließlich für Gefahr und Fehler reserviert; die ruhige Palette ist grün/orange. So bleibt Rot vertrauenswürdig als echtes Alarmsignal. Gefahren-Rot ist als `LavaStyle.dangerRed` tokenisiert, mit `LavaStyle.errorText` als Alias darauf (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86), und wird vom Fehlertext in den Views verwendet. Der Schutz-Farbton wird über die semantische `ProtectionTintRole`-Rollentabelle aufgelöst (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) statt über rohes `.green`/`.orange`. Ein paar rohe `.red`-Aufrufstellen bestehen tatsächlich noch (z. B. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — diese auf `LavaStyle.dangerRed` umzustellen, ist der letzte Rest an Aufräumarbeit.
- **Keine angstbeladene Sicherheitssprache.** Die Texte sind schlicht, ruhig und praktisch. Siehe [§4 Texte & Namen](#4-copy-naming).

### Die tokenisierte Ebene, die heute existiert **(Umgesetzt)** {#the-tokenized-layer-that-exists-today-implemented}

Das Design System ist eine echte, tokenisierte SwiftUI-Ebene, neben dem `LavaTier`-Tiefenvokabular (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — die adaptive Farb-Quelle der Wahrheit: ~18 semantische Farben (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), jede erzeugt von einer einzigen `adaptiveColor(light:dark:)`-Factory, sodass hell/dunkel zusammen definiert sind. Gefahren-Rot ist hier als `dangerRed`/`errorText` tokenisiert (Zeilen 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — Karten-/Panel-/Auswahl-Oberflächenrollen und Eckenradien: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — die Abstandsskala: `xs`/`sm`/`md`/`lg`/`xl` plus `screenHorizontal`/`screenTop`/`screenBottom`.

Die verbleibende Restlücke ist die Handvoll roher `.red`-Aufrufstellen, die noch nicht auf `LavaStyle.dangerRed` umgestellt sind (siehe §1).

---

## 2. LavaTier — Floor / Window / Workshop **(Umgesetzt)** {#2-lavatier-floor-window-workshop-implemented}

`LavaTier` ist das schlanke Tiefenvokabular, das „ruhiger Kern, verdiente Tiefe" direkt in der Token-Ebene festschreibt. Es ist ein Vokabular plus ein paar Token-Standards — kein vollständiges Re-Theme — und kommt als Enum bei lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, verkabelt in repräsentative Oberflächen, statt jede View nachzurüsten.

| Tier | Tiefe | Bedeutung |
|---|---|---|
| **Floor** | calm | Schutz, der für alle einfach funktioniert — die Standardoberfläche. |
| **Window** | celebratory | Freiwilliges Bewusstsein & Freude: Serien, Freischaltungen, Erfolgsmomente. Nervt nie. |
| **Workshop** | technical | DNS, Nerd Stats, Diagnose. Unsichtbar, bis man danach sucht. |

`LavaTier` ist ein `calm`/`celebratory`/`technical`-Enum, das Token-Standards mitbringt:

- eine **Akzentfarbe** (`accent`),
- `allowsDelightMotion` — nur für celebratory / Window wahr,
- `usesMonospacedMetadata` — nur für technical / Workshop wahr,

bereitgestellt über einen `EnvironmentKey` plus einen `.lavaTier(_:)`-Modifier und einen `.lavaTierMetadata()`-Modifier (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). Es ist in repräsentative Oberflächen verkabelt — z. B. `.lavaTier(.technical)` und `.lavaTier(.celebratory)` in lavasec-ios: LavaSecApp/SettingsView.swift — statt in jede View. Diese bewusste Begrenzung hält die drei Produkt-Tiefen im Code lesbar und portierbar zu einem künftigen Android-Consumer, ohne die Absicht neu herleiten zu müssen.

> **Vorbehalt (Akzent-Tokenisierung Geplant, Phase 3):** `LavaColorRole` ist noch nicht erstellt, daher löst `LavaTier.accent` weiterhin zu rohen `LavaStyle`-Farben auf (LavaTokens.swift:~230). Behandle die Akzentfarben-Tokenisierung als offene Schleife, nicht als fertige Oberfläche.

---

## 3. Das Soft-Shield-Guardian-Maskottchen **(Umgesetzt)** {#3-the-soft-shield-guardian-mascot}

Der **Soft Shield Guardian** ist Lavas Maskottchen — ein abgerundeter Schild mit einem einfachen, sich verformenden Gesicht — das den Schutzzustand visuell auf dem Schutz-Tab, der Live Activity, der Dynamic Island und im Onboarding ausdrückt. Es ist der sichtbarste Träger des ruhigen Tons.

Der Zustandsgraph ist plattformunabhängig und lebt in `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); der SwiftUI-Renderer ist lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 Die 7 Ausdruckszustände {#31-the-7-expression-states}

Das Maskottchen hat **genau 7** Ausdruckszustände, gesteuert von einem Zustandsgraphen mit erlaubten Übergängen (`GuardianMascotState.allowedNextStates`, festgeschrieben durch lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Graph-Einschränkungen, die man kennen sollte: Der einzige Ausgang von `sleeping` ist `waking`, und `grateful` kehrt nur zu `awake` zurück. Die `awake ↔ grateful`-Übergänge haben maßgeschneiderte Interpolationsframes — das ist das eine bisschen **Delight-Motion** des Systems (Window-Tier).

> **`retrying` vs `concerned` — die wichtigste Tonunterscheidung.** Beide signalisieren „nicht ganz gesund", aber sie lesen sich sehr unterschiedlich und dürfen nicht verwechselt werden:
> - **`retrying`** ist das *unbesorgte, selbstheilende* Gesicht: entspannte (~0.80) Lider, gerade Augen, ein flacher Mund und **keine Sorgen-Neigung**. Die Bewegung trägt das **Status-Badge, nicht das Gesicht** — vorübergehende Selbstheilung sollte nie alarmieren. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** ist *sanfte, hilfesuchende* Sorge: angehobene innere Brauen (`concernAmount` 1, `mouthCurve` -0.22), die sich lesen wie „Ich könnte etwas Hilfe gebrauchen", **niemals ein strenger Blick**. Echte Probleme sollten zur Hilfe einladen, nicht schimpfen. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Konnektivität → Ausdruck-Zuordnung (6 → 4) {#32-connectivity-expression-mapping-6-4}

Der Schutzzustand wird in `LavaSecCore` als **6 Konnektivitäts-Schweregrade** + 2 Aktionen bewertet (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Schweregrade:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Aktionen:** `turnOff`, `reconnect`

Der Schutz-Tab fasst diese 6 Schweregrade auf **4 Gesichter** zusammen (`guardianState` in lavasec-ios: LavaSecApp/GuardView.swift:122). Das Gesicht ist absichtlich ein *gröberes, ruhigeres* Signal als das Status-Badge — das Badge trägt die Details, das Gesicht bleibt einfach:

| Bedingung | Maskottchen-Zustand |
|---|---|
| Vorübergehend pausiert | `paused` |
| verbunden + `healthy` / `usingDeviceDNSFallback` | `awake` |
| verbunden + `recovering` / `networkUnavailable` | `retrying` |
| verbunden + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| ansonsten | `sleeping` |

> **Farbton-Abgleich.** Die Granularität der Schutz-Farbtöne bleibt mit dieser Ausdrucks-Aufteilung abgeglichen, sodass Farbton und Gesicht nie widersprechen. Die Ausdruck-Zuordnung und die semantische `ProtectionTintRole`-Rollentabelle werden beide heute ausgeliefert (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, verwendet von `AppViewModel.protectionTintRole`). Nur die `LavaColorRole`-Farbrollen-Tokenisierung, die Rollen auf vollständig tokenisierte Farben abbilden würde, bleibt **Geplant** (Phase 3 des DS-Plans).

### 3.3 Skins (Looks) **(Umgesetzt)** {#33-skins-looks-implemented}

Das Maskottchen kommt in **7 auswählbaren Schild-„Looks"**, gespeichert als `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Jeder hat seine eigene Farbwelt und eine dazu passende Dynamic-Island-Glyphenfarbe:

`original`, `fireOpal` (Rohwert `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (Rohwert `strawberryObsidian`), `emerald`, `kiwiCreme`.

Die zwei alten Rohwerte sind Absicht — „repariere" sie nicht; sie würden gespeicherte Nutzerauswahlen kaputtmachen.

### 3.4 Datenschutz-Schwärzung **(Umgesetzt)** {#34-privacy-redaction-implemented}

Der Guardian respektiert die Datenschutz-Schwärzung: Der Ausdruck kann maskiert werden, wenn die Oberfläche datenschutz-geschwärzt ist, während der **Schild selbst sichtbar bleibt** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). Dass Schutz da ist, ist beruhigend; der konkrete emotionale Zustand ist der Teil, der sich versteckt.

### 3.5 Nicht in diesem Tree **(Geplant)** {#35-not-in-this-tree-planned}

Ein Schutz-Easter-Egg-Minispiel (Tippen = Dankbarkeits-Animation; 10 s langes Drücken = ein Spiel, bei dem man böse Domains fängt) ist **P3 / Backlog**. Es würde zusätzliche Maskottchen-Ausdrücke hinzufügen (`confused` / `dazed` / `inZone` / `powerSurge`), die auf einem Feature-Branch zu sehen sind — diese sind **nicht** im App-Target. Laut den kanonischen Fakten hat das Maskottchen genau **7** Zustände; dokumentiere die Spiel-Ausdrücke nicht als ausgeliefert.

---

## 4. Texte & Namen {#4-copy-naming}

### 4.1 Stimme & Ton {#41-voice-tone}

Schlicht, ruhig, praktisch. Vermeide angstbeladene Sicherheitssprache. Sei ehrlich über den Umfang: Lava ist **lokale DNS-/Blocklisten-Filterung**, keine Garantie, dass jede bösartige Domain oder URL blockiert wird, und Schutz wird **niemals** so beschrieben, als wäre er automatisch an, sobald das Onboarding fertig ist — der **Schutz-Tab ist maßgeblich** dafür, ob der Schutz gerade aktiv ist.

### 4.2 DNS-Transport-Labels {#42-dns-transport-labels}

Transport-Annotationen folgen einer strengen kompakten Konvention (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 und lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, festgeschrieben durch `DNSResolverPresetTests.swift`):

| Transport | Label | Hinweise |
|---|---|---|
| DNS-over-HTTPS | `DoH` | URLSession-basiert. |
| DNS-over-HTTP/3 | **`DoH3` (kein Schrägstrich)** | z. B. „Quad9 (DoH3)". Wird **nur annotiert, wenn eine h3-Aushandlung tatsächlich beobachtet wird** — bevorzugt, nie versprochen; ansonsten Rückfall auf `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| einfaches DNS | `IP` | |
| Geräte-Resolver | *(keine Annotation)* | |

Die mit Abstand am häufigsten gebrochene Regel hier ist das **schrägstrichlose `DoH3`** — schreibe `DoH3`, niemals `DoH/3` oder `DoH3 (h3)`, und wende es nie spekulativ an. Diese Transport-Labels werden von `DoHTransport`/`DNSResolverPreset` ausgegeben; halte sie in jeder Sprache wörtlich, aber beachte, dass sie *keine* Do-Not-Translate-Einträge des Glossars sind (siehe §4.3).

### 4.3 Do-Not-Translate-Begriffe {#43-do-not-translate-terms}

Marken- und Protokollbegriffe sind in **allen** Sprachen wörtlich festgepinnt. Die Do-Not-Translate-Liste des Lokalisierungs-Glossars ist maßgeblich, und sie pinnt fest: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

Von den DNS-Transporten ist nur **DoH** ein Do-Not-Translate-Eintrag des Glossars; `DoH3`, `DoT` und `DoQ` sind Transport-Labels (siehe §4.2), keine Glossar-Begriffe. Sie werden trotzdem wörtlich geschrieben, aber führe das Glossar nicht als ihre Quelle an.

### 4.4 Sicherheits-Einordnung {#44-safety-framing}

Bezahlung umgeht niemals die hash-validierte, nicht aufhebbare **Schutzbarriere**. Nenne die Vorrangordnung konsistent: **Schutzbarriere > lokale Erlaubt-Liste (Erlaubte Ausnahmen) > Sperrliste > Standard-Erlauben.**

---

## 5. Onboarding-UX **(Umgesetzt)** {#5-onboarding-ux-implemented}

Das Erststart-Onboarding ist ein mehrseitiger Ablauf — **6 Seiten** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — umgesetzt in lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Es nutzt den `SoftShieldGuardian` für den Moment, in dem der Guardian auftaucht, wieder.

Die 6 Seiten:

1. **The Internet Is Lava** (`lava`) — Gefahr als Metapher dargestellt; Hauptaktion „Meet Lava".
2. **Lava passt hier auf** (`guardIntro`) — der Moment, in dem der Guardian auftaucht.
3. **Feature Handoff** (`features`) — was Lava tut; „Set Up Protection".
4. **Install Lava's Local VPN** (`vpn`) — erklärt, warum iOS bei einem reinen DNS-Pakettunnel „VPN" sagt.
5. **Enable Notifications** (`notifications`) — die Opt-in-Abfrage, beim richtigen Schritt präsentiert statt gleich am Anfang.
6. **Setup Complete** (`done`) — „Open Guard", mit optionaler zusätzlicher Einrichtung.

Designentscheidungen, die fest in den Ablauf eingebaut sind:

- **„Use Default" ist die Hauptaktion, „Customize" die zweite.** Ein reibungsfreier Standardpfad für nicht-technische Nutzer; Kontrolle wird verdient, nicht erzwungen.
- **Gefahr als Metapher dargestellt, nicht als Angst** („The Internet Is Lava"), im Einklang mit dem ruhigen Ton.
- **Der Ablauf erklärt, warum iOS „VPN" sagt** — ein Pakettunnel ist der einzige Weg, DNS systemweit zu filtern; es ist kein Traffic-Routing.
- **Behauptet nie, dass Schutz bei Abschluss automatisch an ist** — Schutz bleibt maßgeblich.
- Nur-Chevron-Zurück, auf einem gemeinsamen Schritt-Seiten-Layout.

Die Erststart-Standards, die der Ablauf installiert: **Device DNS**-Resolver (`DNSResolverPreset.device`), **Geräte-DNS-Ausweichoption AN**, Logging an (Zähler + Verlauf + Aktivität) und „Ohne Konto fortfahren".

> **Standard-Sperrlisten-Abweichung (Code gewinnt).** Der Onboarding-Plan-Text listet HaGeZi Multi Light als Standard-Sperrliste, aber der ausgelieferte Code-Standard ist **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definiert in lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). Das eigentliche Tier-Gate ist das **Filter-Regel-Budget (Free 500K / Plus 2M)**, *nicht* eine Listenanzahl. Intern nachverfolgt. Für das Tier-Modell und die empfohlene Standard-Konfiguration siehe [den Feature-Katalog](../product/features.md).

---

## 6. Internationalisierung **(In Arbeit)** {#6-internationalization-in-progress}

Lava lokalisiert in **6 Sprachen**: **en** (Quelle) + **ja, zh-Hant, zh-Hans, de, fr**, über Xcode-String-Kataloge.

- **Die Lokalisierungsnaht ist `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, gestützt durch `LavaStrings.localized` → `NSLocalizedString` mit englischem Fallback; lavasec-ios: LavaSecApp/LavaStrings.swift). **Alle Komponenten-Texte** müssen darüber laufen — keine nackten String-Literale in den Views.
- **zh-Hant** verwendet im ersten Durchgang taiwan-freundliche Formulierungen.
- App-Store-Metadaten existieren für alle 6 Sprachen.
- Prioritätsreihenfolge für die Übersetzung: ja, zh-Hant, zh-Hans, de, fr.

Die Grundlagen sind vorhanden, aber die vollständige menschliche Übersetzungsprüfung steht vor dem Release noch aus, daher ist der Gesamtstatus **In Arbeit**.

> **Aufräumarbeit an der Präsentationsgrenze (Geplant, Phase 4).** `LavaSecCore`/`Shared` sollten *Semantik* tragen (Schweregrad-/Aktions-Enums, Icon-Rollen), keine englischen Strings. Die Schweregrad-Farbton-Präsentation wurde bereits in die semantische `ProtectionTintRole` gehoben. Der verbleibende Rest ist, dass die `displayName`s der Resolver immer noch fest verdrahtete englische Strings sind („Google", „Cloudflare", „Quad9", „Device DNS") in lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. Phase 4 hebt diese in eine app-seitige Präsentations-Map pro Betriebssystem — richtig sowohl für i18n als auch für Android-Portabilität.

Die i18n-Mechanik (das Lokalisierungs-Glossar, das Schema der Lokalisierungsdateien und die Checkliste für die Übersetzungsprüfung) lebt in den internen i18n-Dokumenten, nicht in diesem öffentlichen Satz.

---

## 7. Referenz-Artefakte {#7-reference-artifacts}

HTML-Design-Referenzen (nicht ausgeliefert, intern): das Storyboard des Onboarding-Ablaufs, eine Kiwi-Creme-Guardian-Look-Studie und Visual-Optionen für den primären Button im Panel.

Die DS-Grundlage ist gelandet: die `LavaDesignSystem/`-Gruppe, die `LavaSpacing`-/Radius-/`dangerRed`-Tokens, die `LavaTier`-Tiefen-Semantik und die `LavaIcon`-Rollenebene werden alle ausgeliefert (lavasec-ios: LavaSecApp/LavaDesignSystem/). Was im Portabilitäts-/Grundlagen-Plan **Geplant** bleibt, ist die `LavaColorRole`-Akzent-Tokenisierung (Phase 3), die Präsentations-Map pro Betriebssystem für die englischen Strings auf der Core-Seite (Phase 4), ein neutrales plattformübergreifendes Token-JSON und die breiteren Android-Portabilitätsnähte.
