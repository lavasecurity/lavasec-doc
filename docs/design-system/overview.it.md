---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Design System

> **Destinatari:** design + ingegneria al lavoro sull'app iOS di Lava Security.
> **Autorità:** Dove questo documento e un piano divergono, **vince il codice** — le divergenze sono segnalate inline. Lo stato riflette la realtà confermata dal codice, non le aspirazioni del piano. Legenda dello stato: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente integrato), **Pianificato** (progettato, non costruito), **Abbandonato** (rifiutato o annullato).

Questo documento copre la filosofia di design, il vocabolario di profondità LavaTier, la mascotte Guardian, le convenzioni di copy e denominazione, la UX di onboarding e l'internazionalizzazione. Per l'infrastruttura architetturale dietro queste superfici (target, ciclo di vita della VPN, il cablaggio del modello di stato Guardian/protezione), vedi [il client iOS](../architecture/ios-client.md); per l'inquadramento di prodotto, vedi [la panoramica di prodotto](../product/overview.md).

---

## 1. Filosofia: nucleo calmo, profondità conquistata

Il pubblico di Lava è composto da utenti comuni non tecnici — genitori, persone anziane — e il design ne deriva di conseguenza. La superficie quotidiana "funziona e basta" in modo calmo per tutti; dettagli aggiuntivi, piacere e controllo vengono rivelati (**conquistati**) solo quando l'utente va a cercarli. Niente assilla, niente allarma e i meccanismi tecnici restano invisibili finché non vengono cercati.

Questo modello **"nucleo calmo, profondità conquistata"** si risolve in tre profondità di prodotto:

- **Calmo** — la protezione predefinita, che funziona e basta, che tutti vedono per primi.
- **Celebrativo** — consapevolezza e piacere a scelta (serie, sblocchi, momenti di successo). Non assilla mai.
- **Tecnico** — DNS, diagnostica e statistiche. Invisibile finché l'utente non li cerca.

Due regole trasversali di palette/tono sostengono la postura calma:

- **rosso = solo pericolo.** Il rosso è riservato esclusivamente al pericolo e all'errore; la palette calma è verde/arancione. Questo mantiene il rosso affidabile come autentico segnale di allarme. Il rosso-pericolo è tokenizzato come `LavaStyle.dangerRed`, con `LavaStyle.errorText` aliasato ad esso (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) e consumato dal testo di errore nelle view. La tinta di protezione è risolta tramite la tabella di ruoli semantica `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) piuttosto che il grezzo `.green`/`.orange`. Alcuni punti di chiamata grezzi `.red` persistono effettivamente (ad es. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrarli a `LavaStyle.dangerRed` è la pulizia rimanente.
- **Nessun linguaggio di sicurezza incentrato sulla paura.** Il copy è semplice, calmo e pratico. Vedi [§4 Copy e denominazione](#4-copy-naming).

### Lo strato tokenizzato che esiste oggi **(Implementato)**

Il design system è un vero strato SwiftUI tokenizzato, insieme al vocabolario di profondità `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — la fonte di verità dei colori adattivi: ~18 colori semantici (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), ciascuno prodotto da un'unica factory `adaptiveColor(light:dark:)` in modo che chiaro/scuro siano definiti insieme. Il rosso-pericolo è tokenizzato qui come `dangerRed`/`errorText` (righe 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — ruoli delle superfici di card/pannello/selezione e raggi degli angoli: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — la scala di spaziatura: `xs`/`sm`/`md`/`lg`/`xl` più `screenHorizontal`/`screenTop`/`screenBottom`.
- **`LavaActionRole`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift, v1.0) — un enum semantico di ruolo d'azione (`.cancel`, `.close`, `.confirm`, `.destructive`) mappato sul `ButtonRole` di sistema. `NativeToolbarIconButton` ha acquisito un parametro `role:` ed è usato in modo pervasivo, così i glifi della toolbar adottano lo stile di ruolo nativo in quasi ogni sheet/toolbar.

Il divario residuo rimanente è la manciata di punti di chiamata grezzi `.red` non ancora migrati a `LavaStyle.dangerRed` (vedi §1).

> **Avvicendamento dei componenti (v1.0).** `LavaTabOverviewCard` è stato rimosso; i blocchi di intestazione di Filtro e Attività ora condividono `LavaInfoCard` + `LavaOverviewMetricBlock` così da allinearsi in dimensione e posizione. Nuovi componenti condivisi sono arrivati insieme alla riprogettazione di Filtro/Attività: `FiltersFlowDiagram` (il diagramma "Phone → Lava → Internet"), `ActivityFlowBar` / `ActivityFlowStatRow` (il digest del flusso di richieste), `NetworkActivityPrivacyInfoPanel` e `LavaGuardLookPickerSheet` (il selettore Guard a bottom-sheet). I flussi di import/condivisione hanno sostituito la loro intestazione personalizzata in-contenuto con una `importFlowToolbar` nativa.

---

## 2. LavaTier — Floor / Window / Workshop **(Implementato)**

`LavaTier` è il vocabolario di profondità leggero che codifica "nucleo calmo, profondità conquistata" direttamente nello strato dei token. È un vocabolario più alcuni valori predefiniti dei token — non un re-theme completo — e viene rilasciato come enum in lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, cablato in superfici rappresentative anziché adattare retroattivamente ogni view.

| Tier | Profondità | Significato |
|---|---|---|
| **Floor** | calmo | Protezione che funziona e basta per tutti — la superficie predefinita. |
| **Window** | celebrativo | Consapevolezza e piacere a scelta: serie, sblocchi, momenti di successo. Non assilla mai. |
| **Workshop** | tecnico | DNS, Nerd Stats, diagnostica. Invisibile finché non viene cercato. |

`LavaTier` è un enum `calm`/`celebratory`/`technical` che porta con sé valori predefiniti dei token:

- un **colore d'accento** (`accent`),
- `allowsDelightMotion` — vero solo per celebrativo / Window,
- `usesMonospacedMetadata` — vero solo per tecnico / Workshop,

esposto tramite un `EnvironmentKey` più un modificatore `.lavaTier(_:)` e un modificatore `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). È cablato in superfici rappresentative — ad es. `.lavaTier(.technical)` e `.lavaTier(.celebratory)` in lavasec-ios: LavaSecApp/SettingsView.swift — anziché in ogni view. La delimitazione deliberata mantiene le tre profondità di prodotto leggibili nel codice e portabili verso un futuro consumer Android senza riderivare l'intento.

> **Avvertenza (tokenizzazione dell'accento Pianificata, Fase 3):** `LavaColorRole` non è ancora stato creato, quindi `LavaTier.accent` si risolve ancora in colori grezzi `LavaStyle` (LavaTokens.swift:~230). Tratta la tokenizzazione del colore d'accento come un anello aperto, non una superficie finita.

---

## 3. La mascotte Soft Shield Guardian **(Implementato)**

Il **Soft Shield Guardian** è la mascotte di Lava — uno scudo arrotondato con un volto semplice e mutevole — che esprime visivamente lo stato di protezione sulla scheda Guard, sulla Live Activity, sulla Dynamic Island e durante l'onboarding. È il portatore più visibile del tono calmo.

Il grafo degli stati è indipendente dalla piattaforma, e risiede in `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); il renderer SwiftUI è lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 I 7 stati di espressione

La mascotte ha **esattamente 7** stati di espressione, governati da un grafo di stati a transizioni consentite (`GuardianMascotState.allowedNextStates`, bloccato da lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Vincoli del grafo che vale la pena conoscere: l'unica uscita di `sleeping` è `waking`, e `grateful` torna solo a `awake`. Le transizioni `awake ↔ grateful` hanno fotogrammi di interpolazione su misura — questo è l'unico tratto di **movimento di piacere** del sistema (Window-tier).

> **`retrying` vs `concerned` — la distinzione di tono più importante.** Entrambi segnalano "non perfettamente in salute," ma si leggono in modo molto diverso e non devono essere confusi:
> - **`retrying`** è il volto *sereno, auto-riparante*: palpebre rilassate (~0,80), occhi a livello, una bocca piatta e **nessuna inclinazione di preoccupazione**. Il movimento è portato dal **badge di stato, non dal volto** — un recupero transitorio non dovrebbe mai allarmare. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** è una preoccupazione *gentile, che cerca aiuto*: sopracciglia interne sollevate (`concernAmount` 1, `mouthCurve` -0,22) che si leggono come "mi servirebbe una mano," **mai uno sguardo severo**. I problemi autentici dovrebbero invitare all'aiuto, non rimproverare. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mappatura connettività → espressione (6 → 4)

La salute della protezione è valutata in `LavaSecCore` come **6 gravità di connettività** + 2 azioni (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Gravità:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Azioni:** `turnOff`, `reconnect`

La scheda Guard riduce quelle 6 gravità a **4 volti** (`guardianState` in lavasec-ios: LavaSecApp/GuardView.swift:122). Il volto è intenzionalmente un segnale *più grezzo e più calmo* del badge di stato — il badge porta il dettaglio, il volto resta semplice:

| Condizione | Stato della mascotte |
|---|---|
| Temporaneamente in pausa | `paused` |
| connesso + `healthy` / `usingDeviceDNSFallback` | `awake` |
| connesso + `recovering` / `networkUnavailable` | `retrying` |
| connesso + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| altrimenti | `sleeping` |

> **Riconciliazione della tinta.** La granularità del colore di tinta della protezione resta riconciliata con questa suddivisione delle espressioni, così tinta e volto non sono mai in disaccordo. La mappatura delle espressioni e la tabella di ruoli semantica `ProtectionTintRole` sono entrambe rilasciate oggi (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, consumata da `AppViewModel.protectionTintRole`). Solo la tokenizzazione dei ruoli di colore `LavaColorRole` che mapperebbe i ruoli su colori completamente tokenizzati rimane **Pianificata** (Fase 3 del piano DS).

### 3.3 Skin (look) **(Implementato)**

La mascotte è disponibile in **7 "look" di scudo selezionabili**, persistiti come `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Ciascuno ha la propria combinazione di colori e un colore di glifo Dynamic Island abbinato:

`original`, `fireOpal` (valore grezzo `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valore grezzo `strawberryObsidian`), `emerald`, `kiwiCreme`.

I due valori grezzi legacy sono intenzionali — non "correggerli"; romperebbero le selezioni utente persistite.

### 3.4 Oscuramento per privacy **(Implementato)**

Il Guardian rispetta l'oscuramento per privacy: l'espressione può essere mascherata quando la superficie è oscurata per privacy mentre lo **scudo stesso resta visibile** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). La presenza della protezione è rassicurante; lo specifico stato emotivo è la parte che si nasconde.

### 3.5 Non in questo albero **(Pianificato)**

Un mini-gioco easter-egg di Guard (tocco = animazione di gratitudine; pressione prolungata di 10s = un gioco di cattura dei domini cattivi) è **P3 / backlog**. Aggiungerebbe espressioni extra della mascotte (`confused` / `dazed` / `inZone` / `powerSurge`) viste su un branch di feature — queste **non** sono nel target dell'app. Secondo i fatti canonici, la mascotte ha esattamente **7** stati; non documentare le espressioni del gioco come rilasciate.

---

## 4. Copy e denominazione

### 4.1 Voce e tono

Semplice, calmo, pratico. Evita il linguaggio di sicurezza incentrato sulla paura. Sii onesto sull'ambito: Lava è **filtraggio locale DNS/blocklist**, non una garanzia che ogni dominio o URL malevolo sia bloccato, e la protezione non è **mai** descritta come auto-attiva nel momento in cui l'onboarding si completa — la **scheda Guard è autorevole** per stabilire se la protezione è attualmente attiva.

### 4.2 Etichette di trasporto DNS

Le annotazioni di trasporto seguono una convenzione compatta rigorosa (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 e lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, bloccata da `DNSResolverPresetTests.swift`):

| Trasporto | Etichetta | Note |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Basato su URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (senza slash)** | ad es. "Quad9 (DoH3)". Annotato **solo quando una negoziazione h3 è effettivamente osservata** — preferito, mai promesso; altrimenti ripiega su `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS semplice | `IP` | |
| resolver del dispositivo | *(nessuna annotazione)* | |

La regola più frequentemente infranta qui è il **`DoH3` senza slash** — scrivi `DoH3`, mai `DoH/3` o `DoH3 (h3)`, e non applicarlo mai in modo speculativo. Queste etichette di trasporto sono emesse da `DoHTransport`/`DNSResolverPreset`; mantienile verbatim in ogni locale, ma nota che *non* sono voci Do-Not-Translate del glossario (vedi §4.3).

### 4.3 Termini Do-Not-Translate

I termini di brand e protocollo sono fissati verbatim in **tutti** i locali. La lista Do-Not-Translate del glossario di localizzazione è l'autorità, e fissa: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD, AdGuard, 1Hosts, StevenBlack.**

Dei trasporti DNS, solo **DoH** è una voce Do-Not-Translate del glossario; `DoH3`, `DoT` e `DoQ` sono etichette di trasporto (vedi §4.2), non termini del glossario. Sono comunque scritti verbatim, ma non citare il glossario come loro fonte.

### 4.4 Inquadramento della sicurezza

Il pagamento non aggira mai la **barriera di protezione contro le minacce** validata tramite hash e non disattivabile. Esprimi la precedenza in modo coerente: **barriera contro le minacce > allowlist locale (eccezioni consentite) > blocklist > default-allow.**

---

## 5. UX di onboarding **(Implementato)**

L'onboarding al primo avvio è un flusso multi-pagina — **6 pagine** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implementato in lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Riutilizza il `SoftShieldGuardian` per il momento di emersione del guardiano.

Le 6 pagine:

1. **The Internet Is Lava** (`lava`) — il pericolo inquadrato come metafora; azione primaria "Meet Lava".
2. **Lava Stands Guard Here** (`guardIntro`) — il momento di emersione del guardiano.
3. **Feature Handoff** (`features`) — cosa fa Lava; "Set Up Protection".
4. **Install Lava's Local VPN** (`vpn`) — spiega perché iOS dice "VPN" per un tunnel di pacchetti solo-DNS.
5. **Enable Notifications** (`notifications`) — il prompt di opt-in, presentato al passo giusto anziché all'inizio.
6. **Setup Complete** (`done`) — "Open Guard", con configurazione aggiuntiva facoltativa.

Decisioni di design integrate nel flusso:

- **"Use Default" è l'azione primaria, "Customize" la secondaria.** Un percorso predefinito privo di attriti per utenti non tecnici; il controllo è conquistato, non imposto.
- **Pericolo inquadrato come metafora, non come paura** ("The Internet Is Lava"), coerente con il tono calmo.
- **Il flusso spiega perché iOS dice "VPN"** — un tunnel di pacchetti è l'unico modo per filtrare il DNS a livello di sistema; non è instradamento del traffico.
- **Non afferma mai che la protezione sia auto-attiva al completamento** — Guard resta autorevole.
- Back solo a chevron, su un layout di pagina-passo condiviso.

I valori predefiniti del primo avvio che il flusso installa: resolver **Device DNS** (`DNSResolverPreset.device`), **fallback Device DNS ON**, logging attivo (conteggi + cronologia + attività) e "Continue without account."

> **Fonte di verità della blocklist predefinita.** Il valore predefinito nel codice rilasciato è **Block List Basic** (`AppConfiguration.lavaRecommendedDefaults`, definito in lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). Il vero gate di tier è il **budget di regole del filtro (Free 500K / Plus 2M)**, *non* un conteggio di liste. Per il modello dei tier e la configurazione predefinita raccomandata, vedi [il catalogo delle funzionalità](../product/features.md).

---

## 6. Internazionalizzazione **(In corso)**

Lava è localizzata in **6 locali**: **en** (sorgente) + **ja, zh-Hant, zh-Hans, de, fr**, tramite i cataloghi di stringhe di Xcode.

- **La cucitura di localizzazione è `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, supportato da `LavaStrings.localized` → `NSLocalizedString` con un fallback inglese; lavasec-ios: LavaSecApp/LavaStrings.swift). **Tutto il copy dei componenti** deve passare attraverso di essa — niente literal di stringa nudi nelle view.
- **zh-Hant** usa una formulazione adatta a Taiwan nella prima passata.
- I metadati dell'App Store esistono per tutti e 6 i locali.
- Ordine di priorità per la traduzione: ja, zh-Hant, zh-Hans, de, fr.
- La release v1.0 ha incorporato una revisione dei cataloghi di stringhe a cinque locali (≈56 correzioni), e il sostantivo di prodotto è cambiato dal plurale **"Filters"** al singolare **"Filter"** in tutti i locali — mantieni le traduzioni coerenti con il modello singolare "my filter".

Le fondamenta sono in posizione ma la revisione completa della traduzione umana è ancora in sospeso prima della release, quindi lo stato complessivo è **In corso**.

> **Pulizia del confine di presentazione (Pianificato, Fase 4).** `LavaSecCore`/`Shared` dovrebbero portare *semantica* (enum di gravità/azione, ruoli di icona), non stringhe inglesi. La presentazione della tinta di gravità è già stata sollevata nel semantico `ProtectionTintRole`. Il residuo rimanente è che i `displayName` dei resolver sono ancora stringhe inglesi hardcoded ("Google", "Cloudflare", "Quad9", "Device DNS") in lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. La Fase 4 le solleva in una mappa di presentazione lato-app per-OS — corretta sia per l'i18n sia per la portabilità Android.

I meccanismi dell'i18n (il glossario di localizzazione, lo schema dei file di localizzazione e la checklist di revisione della traduzione) risiedono nei documenti i18n interni, non in questo insieme pubblico.

---

## 7. Artefatti di riferimento

Riferimenti di design HTML (non rilasciati, interni): lo storyboard del flusso di onboarding, uno studio del look del guardiano kiwi-creme e le opzioni visive del pulsante primario in-pannello.

La fondazione del DS è arrivata: il gruppo `LavaDesignSystem/`, i token `LavaSpacing`/raggio/`dangerRed`, la semantica di profondità `LavaTier` e lo strato di ruoli `LavaIcon` sono tutti rilasciati (lavasec-ios: LavaSecApp/LavaDesignSystem/). Ciò che resta **Pianificato** nel piano di portabilità/fondazione è la tokenizzazione dell'accento `LavaColorRole` (Fase 3), la mappa di presentazione per-OS per le stringhe inglesi lato-core (Fase 4), un JSON di token neutro multipiattaforma e le più ampie cuciture di portabilità Android.
