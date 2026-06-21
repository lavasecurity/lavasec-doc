---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Design System

> **Pubblico:** chi si occupa di design e ingegneria sull'app iOS di Lava Security.
> **Autorità:** Dove questo documento e un piano sono in disaccordo, **vince il codice** — le divergenze sono segnalate inline. Lo stato riflette la realtà confermata dal codice, non le aspirazioni del piano. Legenda degli stati: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente integrato), **Pianificato** (progettato, non costruito), **Abbandonato** (rifiutato o annullato).

Questo documento copre la filosofia di design, il vocabolario di profondità LavaTier, la mascotte Guardian, le convenzioni di testo e denominazione, l'esperienza di onboarding e l'internazionalizzazione. Per l'infrastruttura architetturale dietro queste superfici (target, ciclo di vita della VPN, il collegamento del modello di stato Guardian/protezione), vedi [il client iOS](../architecture/ios-client.md); per l'inquadramento di prodotto, vedi [la panoramica di prodotto](../product/overview.md).

---

## 1. Filosofia: nucleo tranquillo, profondità conquistata {#1-philosophy-calm-core-earned-depth}

Il pubblico di Lava è fatto di utenti comuni non tecnici — genitori, persone anziane — e il design ne deriva direttamente. La superficie quotidiana "funziona e basta" in modo tranquillo per tutti; dettagli aggiuntivi, piacevolezza e controllo vengono rivelati (**conquistati**) solo quando l'utente va a cercarli. Niente assilla, niente allarma, e l'apparato tecnico resta invisibile finché non lo si cerca.

Questo modello **"nucleo tranquillo, profondità conquistata"** si traduce in tre profondità di prodotto:

- **Tranquilla** — la protezione predefinita che funziona e basta, quella che tutti vedono per prima.
- **Celebrativa** — consapevolezza e piacevolezza a scelta dell'utente (serie consecutive, sblocchi, momenti di successo). Non assilla mai.
- **Tecnica** — DNS, diagnostica e statistiche. Invisibile finché l'utente non la cerca.

Due regole trasversali di palette/tono sostengono questo atteggiamento tranquillo:

- **rosso = solo pericolo.** Il rosso è riservato esclusivamente al pericolo e all'errore; la palette tranquilla è verde/arancione. Questo mantiene il rosso affidabile come segnale di allarme genuino. Il rosso-pericolo è tokenizzato come `LavaStyle.dangerRed`, con `LavaStyle.errorText` come suo alias (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) e usato dal testo di errore nelle viste. La tinta di protezione si risolve attraverso la tabella di ruoli semantica `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) anziché tramite `.green`/`.orange` grezzi. Alcuni punti di chiamata con `.red` grezzo persistono davvero (ad es. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrarli a `LavaStyle.dangerRed` è la pulizia rimanente.
- **Nessun linguaggio di sicurezza che fa leva sulla paura.** Il testo è semplice, tranquillo e pratico. Vedi [§4 Testo e denominazione](#4-copy-naming).

### Lo strato tokenizzato che esiste oggi **(Implementato)** {#the-tokenized-layer-that-exists-today-implemented}

Il design system è un vero strato SwiftUI tokenizzato, affiancato dal vocabolario di profondità `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — la fonte di verità per i colori adattivi: ~18 colori semantici (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), ciascuno prodotto da un'unica factory `adaptiveColor(light:dark:)` così che chiaro/scuro siano definiti insieme. Il rosso-pericolo è tokenizzato qui come `dangerRed`/`errorText` (righe 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — ruoli delle superfici di card/pannello/selezione e raggi degli angoli: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — la scala delle spaziature: `xs`/`sm`/`md`/`lg`/`xl` più `screenHorizontal`/`screenTop`/`screenBottom`.
- **`LavaActionRole`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift, v1.0) — un enum semantico di ruoli d'azione (`.cancel`, `.close`, `.confirm`, `.destructive`) mappato al `ButtonRole` di sistema. `NativeToolbarIconButton` ha acquisito un parametro `role:` ed è usato in modo pervasivo, così i glifi della barra strumenti adottano lo stile nativo dei ruoli in quasi ogni sheet/barra strumenti.

La lacuna residua rimanente è la manciata di punti di chiamata con `.red` grezzo non ancora migrati a `LavaStyle.dangerRed` (vedi §1).

> **Ricambio di componenti (v1.0).** `LavaTabOverviewCard` è stato rimosso; i blocchi titolo di Filter e Activity ora condividono `LavaInfoCard` + `LavaOverviewMetricBlock` così da allinearsi per dimensione e posizione. Nuovi componenti condivisi sono arrivati insieme al ridisegno di Filter/Activity: `FiltersFlowDiagram` (il diagramma "Phone → Lava → Internet"), `ActivityFlowBar` / `ActivityFlowStatRow` (il riepilogo del flusso delle richieste), `NetworkActivityPrivacyInfoPanel` e `LavaGuardLookPickerSheet` (il selettore Guard a sheet inferiore). I flussi di importazione/condivisione hanno sostituito la loro intestazione personalizzata nei contenuti con una `importFlowToolbar` nativa.

---

## 2. LavaTier — Floor / Window / Workshop **(Implementato)** {#2-lavatier-floor-window-workshop-implemented}

`LavaTier` è il vocabolario di profondità leggero che codifica "nucleo tranquillo, profondità conquistata" direttamente nello strato dei token. È un vocabolario più alcuni valori predefiniti dei token — non un re-tema completo — e viene rilasciato come enum in lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, collegato a superfici rappresentative anziché adattare retroattivamente ogni vista.

| Tier | Profondità | Significato |
|---|---|---|
| **Floor** | tranquilla | Protezione che funziona e basta per tutti — la superficie predefinita. |
| **Window** | celebrativa | Consapevolezza e piacevolezza a scelta dell'utente: serie consecutive, sblocchi, momenti di successo. Non assilla mai. |
| **Workshop** | tecnica | DNS, Nerd Stats, diagnostica. Invisibile finché non la si cerca. |

`LavaTier` è un enum `calm`/`celebratory`/`technical` che porta con sé valori predefiniti dei token:

- un **colore d'accento** (`accent`),
- `allowsDelightMotion` — vero solo per celebrativa / Window,
- `usesMonospacedMetadata` — vero solo per tecnica / Workshop,

esposto tramite un `EnvironmentKey` più un modificatore `.lavaTier(_:)` e un modificatore `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). È collegato a superfici rappresentative — ad es. `.lavaTier(.technical)` e `.lavaTier(.celebratory)` in lavasec-ios: LavaSecApp/SettingsView.swift — anziché a ogni vista. La delimitazione deliberata mantiene le tre profondità di prodotto leggibili nel codice e portabili verso un futuro consumatore Android senza dover ri-derivare l'intento.

> **Avvertenza (tokenizzazione dell'accento Pianificata, Fase 3):** `LavaColorRole` non è ancora stato creato, quindi `LavaTier.accent` si risolve ancora in colori `LavaStyle` grezzi (LavaTokens.swift:~230). Considera la tokenizzazione del colore d'accento come un anello aperto, non una superficie finita.

---

## 3. La mascotte Soft Shield Guardian **(Implementato)** {#3-the-soft-shield-guardian-mascot}

La **Soft Shield Guardian** è la mascotte di Lava — uno scudo arrotondato con un volto semplice e mutevole — che esprime visivamente lo stato di protezione sulla scheda Guard, sulla Live Activity, sulla Dynamic Island e durante l'onboarding. È il portatore più visibile del tono tranquillo.

Il grafo di stato è agnostico rispetto alla piattaforma e vive in `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); il renderer SwiftUI è lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 I 7 stati di espressione {#31-the-7-expression-states}

La mascotte ha **esattamente 7** stati di espressione, governati da un grafo di stati con transizioni consentite (`GuardianMascotState.allowedNextStates`, bloccato da lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Vincoli del grafo che vale la pena conoscere: l'unica uscita di `sleeping` è `waking`, e `grateful` torna solo ad `awake`. Le transizioni `awake ↔ grateful` hanno frame di interpolazione su misura — questo è l'unico frammento di **delight motion** del sistema (tier Window).

> **`retrying` vs `concerned` — la distinzione di tono più importante.** Entrambi segnalano "non perfettamente in salute", ma si leggono in modo molto diverso e non vanno confusi:
> - **`retrying`** è il volto *senza preoccupazioni, che si auto-ripara*: palpebre rilassate (~0,80), occhi a livello, una bocca dritta e **nessuna inclinazione di preoccupazione**. Il movimento è portato dal **badge di stato, non dal volto** — un recupero automatico transitorio non dovrebbe mai allarmare. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** è una preoccupazione *gentile, che chiede aiuto*: sopracciglia interne sollevate (`concernAmount` 1, `mouthCurve` -0,22) che si leggono come "mi servirebbe una mano", **mai uno sguardo severo**. I problemi veri dovrebbero invitare all'aiuto, non rimproverare. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mappatura connettività → espressione (6 → 4) {#32-connectivity-expression-mapping-6-4}

La salute della protezione è valutata in `LavaSecCore` come **6 livelli di gravità di connettività** + 2 azioni (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Livelli di gravità:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Azioni:** `turnOff`, `reconnect`

La scheda Guard riduce quei 6 livelli di gravità a **4 volti** (`guardianState` in lavasec-ios: LavaSecApp/GuardView.swift:122). Il volto è intenzionalmente un segnale *più grossolano e più tranquillo* rispetto al badge di stato — il badge porta il dettaglio, il volto resta semplice:

| Condizione | Stato della mascotte |
|---|---|
| Temporaneamente in pausa | `paused` |
| connesso + `healthy` / `usingDeviceDNSFallback` | `awake` |
| connesso + `recovering` / `networkUnavailable` | `retrying` |
| connesso + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| altrimenti | `sleeping` |

> **Riconciliazione della tinta.** La granularità del colore della tinta di protezione resta riconciliata con questa suddivisione delle espressioni, così che tinta e volto non siano mai in disaccordo. La mappatura delle espressioni e la tabella di ruoli semantica `ProtectionTintRole` sono entrambe rilasciate oggi (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, usata da `AppViewModel.protectionTintRole`). Resta **Pianificata** solo la tokenizzazione dei ruoli di colore `LavaColorRole` che mapperebbe i ruoli a colori completamente tokenizzati (Fase 3 del piano del DS).

### 3.3 Skin (look) **(Implementato)** {#33-skins-looks-implemented}

La mascotte viene rilasciata in **7 "look" di scudo selezionabili**, persistiti come `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Ciascuno ha la propria combinazione di colori e un colore di glifo della Dynamic Island abbinato:

`original`, `fireOpal` (valore grezzo `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valore grezzo `strawberryObsidian`), `emerald`, `kiwiCreme`.

I due valori grezzi legacy sono intenzionali — non "correggerli"; romperebbero le selezioni utente persistite.

### 3.4 Oscuramento per la privacy **(Implementato)** {#34-privacy-redaction-implemented}

La Guardian rispetta l'oscuramento per la privacy: l'espressione può essere mascherata quando la superficie è oscurata per privacy mentre lo **scudo stesso resta visibile** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). La presenza della protezione è rassicurante; è lo specifico stato emotivo la parte che si nasconde.

### 3.5 Non in questo albero **(Pianificato)** {#35-not-in-this-tree-planned}

Un mini-gioco easter-egg su Guard (tocco = animazione di gratitudine; pressione prolungata di 10s = un gioco per acchiappare i domini cattivi) è **P3 / backlog**. Aggiungerebbe espressioni extra della mascotte (`confused` / `dazed` / `inZone` / `powerSurge`) viste su un branch di funzionalità — queste **non** sono nel target dell'app. Secondo i fatti canonici, la mascotte ha esattamente **7** stati; non documentare le espressioni del gioco come rilasciate.

---

## 4. Testo e denominazione {#4-copy-naming}

### 4.1 Voce e tono {#41-voice-tone}

Semplice, tranquillo, pratico. Evita il linguaggio di sicurezza che fa leva sulla paura. Sii onesto riguardo all'ambito: Lava è **filtraggio DNS/blocklist locale**, non una garanzia che ogni dominio o URL malevolo venga bloccato, e la protezione **non** viene **mai** descritta come attivata automaticamente nel momento in cui l'onboarding si completa — la **scheda Guard è autorevole** per stabilire se la protezione è attualmente attiva.

### 4.2 Etichette dei trasporti DNS {#42-dns-transport-labels}

Le annotazioni dei trasporti seguono una convenzione compatta rigorosa (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 e lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, bloccata da `DNSResolverPresetTests.swift`):

| Trasporto | Etichetta | Note |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Basato su URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (senza barra)** | ad es. "Quad9 (DoH3)". Annotato **solo quando una negoziazione h3 viene effettivamente osservata** — preferito, mai promesso; altrimenti ripiega su `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS in chiaro | `IP` | |
| resolver del dispositivo | *(nessuna annotazione)* | |

La regola più infranta qui in assoluto è il **`DoH3` senza barra** — scrivi `DoH3`, mai `DoH/3` o `DoH3 (h3)`, e non applicarlo mai in modo speculativo. Queste etichette di trasporto sono emesse da `DoHTransport`/`DNSResolverPreset`; tienile identiche in ogni locale, ma nota che *non* sono voci Da-Non-Tradurre del glossario (vedi §4.3).

### 4.3 Termini Da-Non-Tradurre {#43-do-not-translate-terms}

I termini di marchio e protocollo sono fissati identici in **tutti** i locale. L'elenco Da-Non-Tradurre del glossario di localizzazione è l'autorità, e fissa: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

Dei trasporti DNS, solo **DoH** è una voce Da-Non-Tradurre del glossario; `DoH3`, `DoT` e `DoQ` sono etichette di trasporto (vedi §4.2), non termini del glossario. Si scrivono comunque identici, ma non citare il glossario come loro fonte.

### 4.4 Inquadramento della sicurezza {#44-safety-framing}

Il pagamento non aggira mai la **barriera di protezione dalle minacce** convalidata tramite hash e non aggirabile. Indica la precedenza in modo coerente: **barriera di protezione dalle minacce > allowlist locale (eccezioni consentite) > blocklist > permesso predefinito.**

---

## 5. Esperienza di onboarding **(Implementato)** {#5-onboarding-ux-implemented}

L'onboarding al primo avvio è un flusso a più pagine — **6 pagine** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implementato in lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Riutilizza la `SoftShieldGuardian` per il momento di comparsa della guardiana.

Le 6 pagine:

1. **Internet è lava** (`lava`) — il pericolo inquadrato come metafora; azione principale "Conosci Lava".
2. **Lava fa la guardia qui** (`guardIntro`) — il momento di comparsa della guardiana.
3. **Presentazione delle funzionalità** (`features`) — cosa fa Lava; "Imposta la protezione".
4. **Installa la VPN locale di Lava** (`vpn`) — spiega perché iOS dice "VPN" per un tunnel di pacchetti solo-DNS.
5. **Attiva le notifiche** (`notifications`) — la richiesta di adesione, presentata al passo giusto anziché in anticipo.
6. **Configurazione completata** (`done`) — "Apri Guard", con configurazione aggiuntiva opzionale.

Decisioni di design integrate nel flusso:

- **"Usa predefinito" è l'azione principale, "Personalizza" quella secondaria.** Un percorso predefinito senza attriti per utenti non tecnici; il controllo si conquista, non si impone.
- **Pericolo inquadrato come metafora, non come paura** ("Internet è lava"), coerente con il tono tranquillo.
- **Il flusso spiega perché iOS dice "VPN"** — un tunnel di pacchetti è l'unico modo per filtrare il DNS a livello di sistema; non è instradamento del traffico.
- **Non afferma mai che la protezione sia attivata automaticamente al completamento** — Guard resta autorevole.
- Indietro solo con il chevron, su un layout di pagina-passo condiviso.

I valori predefiniti del primo avvio che il flusso installa: resolver **Device DNS** (`DNSResolverPreset.device`), **fallback Device DNS ATTIVO**, logging attivo (conteggi + cronologia + attività) e "Continua senza account".

> **Divergenza della blocklist predefinita (vince il codice).** Il testo del piano di onboarding elenca HaGeZi Multi Light come blocklist predefinita, ma il valore predefinito nel codice rilasciato è **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definito in lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). Il vero limite di tier è il **budget di regole di filtro (Free 500K / Plus 2M)**, *non* un conteggio di liste. Tracciato internamente. Per il modello di tier e la configurazione predefinita consigliata, vedi [il catalogo delle funzionalità](../product/features.md).

---

## 6. Internazionalizzazione **(In corso)** {#6-internationalization-in-progress}

Lava si localizza in **6 locale**: **en** (sorgente) + **ja, zh-Hant, zh-Hans, de, fr**, tramite i cataloghi di stringhe di Xcode.

- **Il punto di giunzione della localizzazione è `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, basato su `LavaStrings.localized` → `NSLocalizedString` con un fallback in inglese; lavasec-ios: LavaSecApp/LavaStrings.swift). **Tutto il testo dei componenti** deve passare attraverso di esso — nessun letterale di stringa nudo nelle viste.
- **zh-Hant** usa una formulazione adatta a Taiwan al primo passaggio.
- I metadati dell'App Store esistono per tutti i 6 locale.
- Ordine di priorità per la traduzione: ja, zh-Hant, zh-Hans, de, fr.
- La release v1.0 ha incorporato una revisione dei cataloghi di stringhe in cinque locale (≈56 correzioni), e il sostantivo di prodotto è cambiato dal plurale **"Filters"** al singolare **"Filter"** in tutti i locale — mantieni le traduzioni coerenti con il modello al singolare "il mio filtro".

Le fondamenta sono in posto ma la revisione completa della traduzione umana è ancora in attesa prima della release, quindi lo stato complessivo è **In corso**.

> **Pulizia del confine di presentazione (Pianificata, Fase 4).** `LavaSecCore`/`Shared` dovrebbero portare *semantica* (enum di gravità/azione, ruoli delle icone), non stringhe inglesi. La presentazione della tinta di gravità è già stata sollevata nel semantico `ProtectionTintRole`. Il residuo rimanente è che i `displayName` dei resolver sono ancora stringhe inglesi hardcoded ("Google", "Cloudflare", "Quad9", "Device DNS") in lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. La Fase 4 solleva questi in una mappa di presentazione lato app per-OS — corretta sia per l'i18n sia per la portabilità Android.

Le meccaniche dell'i18n (il glossario di localizzazione, lo schema dei file di localizzazione e la checklist di revisione della traduzione) vivono nei documenti i18n interni, non in questo set pubblico.

---

## 7. Artefatti di riferimento {#7-reference-artifacts}

Riferimenti di design in HTML (non rilasciati, interni): lo storyboard del flusso di onboarding, uno studio del look kiwi-creme della guardiana e le opzioni visive del pulsante principale all'interno dei pannelli.

Le fondamenta del DS sono arrivate: il gruppo `LavaDesignSystem/`, i token `LavaSpacing`/raggi/`dangerRed`, la semantica di profondità `LavaTier` e lo strato di ruoli `LavaIcon` sono tutti rilasciati (lavasec-ios: LavaSecApp/LavaDesignSystem/). Ciò che resta **Pianificato** nel piano di portabilità/fondamenta è la tokenizzazione dell'accento `LavaColorRole` (Fase 3), la mappa di presentazione per-OS per le stringhe inglesi lato core (Fase 4), un JSON di token neutrale e multipiattaforma, e le giunzioni più ampie di portabilità Android.
