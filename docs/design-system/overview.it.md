---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Sistema di design

> **Pubblico:** chi si occupa di design e sviluppo dell'app iOS di Lava Security.
> **Autorità:** Quando questo documento e un piano non concordano, **vince il codice** — le divergenze sono segnalate inline. Lo stato riflette la realtà confermata dal codice, non le aspirazioni del piano. Legenda dello stato: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente realizzato), **Pianificato** (progettato, non costruito), **Abbandonato** (rifiutato o ripristinato).

Questo documento copre la filosofia di design, il vocabolario di profondità LavaTier, la mascotte Guardian, le convenzioni di testo e di denominazione, l'esperienza di onboarding e l'internazionalizzazione. Per l'impianto architetturale dietro queste superfici (target, ciclo di vita della VPN, il collegamento del modello di stato Guardian/protezione), vedi [il client iOS](../architecture/ios-client.md); per l'inquadramento di prodotto, vedi [la panoramica di prodotto](../product/overview.md).

---

## 1. Filosofia: nucleo tranquillo, profondità da scoprire

Il pubblico di Lava è fatto di persone comuni e non tecniche — genitori, persone anziane — e il design nasce da questo. La superficie quotidiana "funziona e basta" in modo tranquillo per tutti; dettagli, sorprese e controllo in più si rivelano (**si conquistano**) solo quando l'utente li va a cercare. Niente assilla, niente allarma, e i meccanismi tecnici restano invisibili finché non li si cerca.

Questo modello **"nucleo tranquillo, profondità da scoprire"** si traduce in tre livelli di profondità del prodotto:

- **Tranquillo** — la protezione predefinita, che funziona e basta, che tutti vedono per prima.
- **Celebrativo** — consapevolezza e piacere facoltativi (serie di giorni, sblocchi, momenti di successo). Non assilla mai.
- **Tecnico** — DNS, diagnostica e statistiche. Invisibile finché l'utente non lo cerca.

Due regole trasversali di palette/tono sostengono questa impostazione tranquilla:

- **rosso = solo pericolo.** Il rosso è riservato esclusivamente al pericolo e all'errore; la palette tranquilla è verde/arancione. Così il rosso resta affidabile come segnale di allarme autentico. Il rosso-pericolo è gestito come token `LavaStyle.dangerRed`, con `LavaStyle.errorText` come suo alias (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) e usato dal testo di errore nelle viste. La tinta di protezione si risolve attraverso la tabella di ruoli semantica `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) anziché tramite `.green`/`.orange` grezzi. Persistono ancora davvero alcune chiamate `.red` grezze (ad es. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrarle a `LavaStyle.dangerRed` è la pulizia che resta da fare.
- **Nessun linguaggio di sicurezza allarmistico.** I testi sono semplici, tranquilli e pratici. Vedi [§4 Testi e denominazione](#4-testi-e-denominazione).

### Il livello a token che esiste oggi **(Implementato)**

Il sistema di design è un vero livello SwiftUI a token, accanto al vocabolario di profondità `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — la fonte di verità per i colori adattivi: ~18 colori semantici (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), ciascuno prodotto da un'unica factory `adaptiveColor(light:dark:)`, così chiaro e scuro vengono definiti insieme. Il rosso-pericolo è gestito qui come token `dangerRed`/`errorText` (righe 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — ruoli delle superfici di card/pannello/selezione e raggi degli angoli: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — la scala di spaziatura: `xs`/`sm`/`md`/`lg`/`xl` più `screenHorizontal`/`screenTop`/`screenBottom`.

Lo scarto residuo che rimane è la manciata di chiamate `.red` grezze non ancora migrate a `LavaStyle.dangerRed` (vedi §1).

---

## 2. LavaTier — Floor / Window / Workshop **(Implementato)**

`LavaTier` è il vocabolario di profondità leggero che codifica "nucleo tranquillo, profondità da scoprire" direttamente nel livello a token. È un vocabolario più alcuni valori predefiniti dei token — non un re-theme completo — e viene rilasciato come enum in lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, collegato a superfici rappresentative anziché applicato a ritroso a ogni vista.

| Livello | Profondità | Significato |
|---|---|---|
| **Floor** | tranquillo | Protezione che funziona e basta per tutti — la superficie predefinita. |
| **Window** | celebrativo | Consapevolezza e piacere facoltativi: serie di giorni, sblocchi, momenti di successo. Non assilla mai. |
| **Workshop** | tecnico | DNS, Nerd Stats, diagnostica. Invisibile finché non viene cercato. |

`LavaTier` è un enum `calm`/`celebratory`/`technical` che porta con sé valori predefiniti dei token:

- un **colore di accento** (`accent`),
- `allowsDelightMotion` — vero solo per celebrativo / Window,
- `usesMonospacedMetadata` — vero solo per tecnico / Workshop,

esposti tramite un `EnvironmentKey` più un modificatore `.lavaTier(_:)` e un modificatore `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). È collegato a superfici rappresentative — ad es. `.lavaTier(.technical)` e `.lavaTier(.celebratory)` in lavasec-ios: LavaSecApp/SettingsView.swift — anziché a ogni vista. La delimitazione deliberata mantiene i tre livelli di profondità del prodotto leggibili nel codice e portabili a un futuro consumatore Android senza dover ricostruire l'intenzione.

> **Avvertenza (tokenizzazione dell'accento Pianificata, Fase 3):** `LavaColorRole` non è ancora stato creato, quindi `LavaTier.accent` continua a risolversi in colori `LavaStyle` grezzi (LavaTokens.swift:~230). Considera la tokenizzazione del colore di accento un punto aperto, non una superficie finita.

---

## 3. La mascotte Soft Shield Guardian **(Implementato)**

Il **Soft Shield Guardian** è la mascotte di Lava — uno scudo arrotondato con un volto semplice e mutevole — che esprime visivamente lo stato di protezione nella scheda Guard, nella Live Activity, nella Dynamic Island e nell'onboarding. È il portatore più visibile del tono tranquillo.

Il grafo degli stati è indipendente dalla piattaforma e vive in `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); il renderer SwiftUI è lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 I 7 stati di espressione

La mascotte ha **esattamente 7** stati di espressione, regolati da un grafo di transizioni consentite (`GuardianMascotState.allowedNextStates`, bloccato da lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Vincoli del grafo da conoscere: l'unica uscita di `sleeping` è `waking`, e `grateful` torna solo a `awake`. Le transizioni `awake ↔ grateful` hanno fotogrammi di interpolazione su misura — è l'unico tocco di **movimento di piacere** del sistema (livello Window).

> **`retrying` vs `concerned` — la distinzione di tono più importante.** Entrambi segnalano "non perfettamente in salute", ma si leggono in modo molto diverso e non vanno confusi:
> - **`retrying`** è il volto *sereno e che si auto-ripara*: palpebre rilassate (~0,80), occhi a livello, bocca dritta e **nessuna inclinazione di preoccupazione**. Il movimento è portato dal **badge di stato, non dal volto** — un recupero automatico passeggero non deve mai allarmare. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** è una preoccupazione *delicata, che chiede aiuto*: sopracciglia interne sollevate (`concernAmount` 1, `mouthCurve` -0,22) che leggono come "mi servirebbe una mano", **mai uno sguardo severo**. I problemi veri devono invitare ad aiutare, non rimproverare. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mappatura connettività → espressione (6 → 4)

Lo stato di salute della protezione è valutato in `LavaSecCore` come **6 livelli di gravità della connettività** + 2 azioni (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Gravità:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Azioni:** `turnOff`, `reconnect`

La scheda Guard riduce quelle 6 gravità a **4 volti** (`guardianState` in lavasec-ios: LavaSecApp/GuardView.swift:122). Il volto è intenzionalmente un segnale *più grezzo e più tranquillo* del badge di stato — il badge porta il dettaglio, il volto resta semplice:

| Condizione | Stato della mascotte |
|---|---|
| Temporaneamente in pausa | `paused` |
| connesso + `healthy` / `usingDeviceDNSFallback` | `awake` |
| connesso + `recovering` / `networkUnavailable` | `retrying` |
| connesso + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| altrimenti | `sleeping` |

> **Riconciliazione della tinta.** La granularità del colore della tinta di protezione resta riconciliata con questa suddivisione delle espressioni, così tinta e volto non sono mai in disaccordo. La mappatura delle espressioni e la tabella di ruoli semantica `ProtectionTintRole` sono entrambe già rilasciate oggi (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, usata da `AppViewModel.protectionTintRole`). Resta **Pianificata** solo la tokenizzazione dei ruoli di colore `LavaColorRole`, che mapperebbe i ruoli a colori completamente gestiti come token (Fase 3 del piano del DS).

### 3.3 Skin (aspetti) **(Implementato)**

La mascotte viene rilasciata in **7 "aspetti" di scudo selezionabili**, persistiti come `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Ognuno ha la propria combinazione di colori e un colore abbinato per il glifo della Dynamic Island:

`original`, `fireOpal` (valore grezzo `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valore grezzo `strawberryObsidian`), `emerald`, `kiwiCreme`.

I due valori grezzi storici sono intenzionali — non "correggerli"; romperebbero le selezioni utente persistite.

### 3.4 Oscuramento per privacy **(Implementato)**

Il Guardian rispetta l'oscuramento per privacy: l'espressione può essere mascherata quando la superficie è oscurata per privacy mentre lo **scudo stesso resta visibile** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). La presenza della protezione rassicura; è lo stato emotivo specifico la parte che si nasconde.

### 3.5 Non in questo ramo **(Pianificato)**

Un mini-gioco easter-egg in Guard (tocco = animazione di gratitudine; pressione lunga di 10s = un gioco per acchiappare i domini cattivi) è **P3 / backlog**. Aggiungerebbe espressioni extra della mascotte (`confused` / `dazed` / `inZone` / `powerSurge`) viste su un ramo di funzionalità — queste **non** sono nel target dell'app. Secondo i fatti canonici, la mascotte ha esattamente **7** stati; non documentare le espressioni del gioco come rilasciate.

---

## 4. Testi e denominazione

### 4.1 Voce e tono

Semplici, tranquilli, pratici. Evita il linguaggio di sicurezza allarmistico. Sii onesto sull'ambito: Lava è **filtraggio DNS/blocklist locale**, non una garanzia che ogni dominio o URL dannoso venga bloccato, e la protezione **non** è mai descritta come attiva in automatico nel momento in cui l'onboarding finisce — la **scheda Guard è la fonte autorevole** per stabilire se la protezione è attualmente attiva.

### 4.2 Etichette dei trasporti DNS

Le annotazioni di trasporto seguono una convenzione compatta e rigorosa (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 e lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, bloccata da `DNSResolverPresetTests.swift`):

| Trasporto | Etichetta | Note |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Basato su URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (senza slash)** | ad es. "Quad9 (DoH3)". Annotato **solo quando una negoziazione h3 viene effettivamente osservata** — preferito, mai promesso; altrimenti ricade su `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS semplice | `IP` | |
| resolver del dispositivo | *(nessuna annotazione)* | |

La regola qui infranta più spesso è il **`DoH3` senza slash** — scrivi `DoH3`, mai `DoH/3` né `DoH3 (h3)`, e non applicarlo mai in via speculativa. Queste etichette di trasporto sono emesse da `DoHTransport`/`DNSResolverPreset`; mantienile identiche in ogni lingua, ma nota che *non* sono voci del glossario da Non Tradurre (vedi §4.3).

### 4.3 Termini da Non Tradurre

I termini di marchio e di protocollo sono fissati identici in **tutte** le lingue. L'elenco da Non Tradurre del glossario di localizzazione è l'autorità, e fissa: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

Dei trasporti DNS, solo **DoH** è una voce del glossario da Non Tradurre; `DoH3`, `DoT` e `DoQ` sono etichette di trasporto (vedi §4.2), non termini del glossario. Si scrivono comunque identici, ma non citare il glossario come loro fonte.

### 4.4 Inquadramento della sicurezza

Il pagamento non aggira mai la **barriera contro le minacce**, validata tramite hash e non sovrascrivibile. Indica la precedenza in modo coerente: **barriera contro le minacce > elenco locale dei permessi (eccezioni consentite) > blocklist > consenti per impostazione predefinita.**

---

## 5. Esperienza di onboarding **(Implementato)**

L'onboarding al primo avvio è un flusso a più pagine — **6 pagine** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implementato in lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Riutilizza il `SoftShieldGuardian` per il momento di comparsa del guardiano.

Le 6 pagine:

1. **Internet è lava** (`lava`) — il pericolo presentato come metafora; azione principale "Conosci Lava".
2. **Qui veglia Lava** (`guardIntro`) — il momento di comparsa del guardiano.
3. **Presentazione delle funzioni** (`features`) — cosa fa Lava; "Configura la protezione".
4. **Installa la VPN locale di Lava** (`vpn`) — spiega perché iOS dice "VPN" per un tunnel di pacchetti solo-DNS.
5. **Attiva le notifiche** (`notifications`) — la richiesta di consenso, presentata al momento giusto anziché all'inizio.
6. **Configurazione completata** (`done`) — "Apri Guard", con configurazione aggiuntiva facoltativa.

Decisioni di design integrate nel flusso:

- **"Usa predefinito" è l'azione principale, "Personalizza" quella secondaria.** Un percorso predefinito senza attriti per gli utenti non tecnici; il controllo si conquista, non si impone.
- **Il pericolo presentato come metafora, non come paura** ("Internet è lava"), coerente con il tono tranquillo.
- **Il flusso spiega perché iOS dice "VPN"** — un tunnel di pacchetti è l'unico modo per filtrare il DNS a livello di sistema; non è instradamento del traffico.
- **Non afferma mai che la protezione sia attiva in automatico al completamento** — Guard resta la fonte autorevole.
- Indietro solo con il chevron, su un layout di pagina-passo condiviso.

I valori predefiniti che il flusso installa al primo avvio: resolver **Device DNS** (`DNSResolverPreset.device`), **fallback Device DNS ATTIVO**, registrazione attiva (conteggi + cronologia + attività) e "Continua senza account".

> **Divergenza sulla blocklist predefinita (vince il codice).** Il testo del piano di onboarding indica HaGeZi Multi Light come blocklist predefinita, ma il valore predefinito del codice rilasciato è **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definito in lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). Il vero limite tra i livelli è il **budget di regole di filtro (Free 500K / Plus 2M)**, *non* un conteggio di elenchi. Tracciato internamente. Per il modello dei livelli e la configurazione predefinita consigliata, vedi [il catalogo delle funzioni](../product/features.md).

---

## 6. Internazionalizzazione **(In corso)**

Lava è localizzata in **6 lingue**: **en** (sorgente) + **ja, zh-Hant, zh-Hans, de, fr**, tramite i cataloghi di stringhe di Xcode.

- **Il punto di aggancio della localizzazione è `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, basato su `LavaStrings.localized` → `NSLocalizedString` con fallback in inglese; lavasec-ios: LavaSecApp/LavaStrings.swift). **Tutti i testi dei componenti** devono passare di lì — niente stringhe letterali nude nelle viste.
- **zh-Hant** usa formulazioni adatte a Taiwan nella prima passata.
- I metadati per l'App Store esistono per tutte e 6 le lingue.
- Ordine di priorità per la traduzione: ja, zh-Hant, zh-Hans, de, fr.

Le fondamenta sono in posa, ma manca ancora la revisione completa della traduzione umana prima del rilascio, quindi lo stato complessivo è **In corso**.

> **Pulizia del confine di presentazione (Pianificata, Fase 4).** `LavaSecCore`/`Shared` dovrebbero portare *semantica* (enum di gravità/azione, ruoli delle icone), non stringhe in inglese. La presentazione della tinta di gravità è già stata sollevata nel semantico `ProtectionTintRole`. Il residuo che rimane è che i `displayName` dei resolver sono ancora stringhe inglesi cablate ("Google", "Cloudflare", "Quad9", "Device DNS") in lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. La Fase 4 le solleva in una mappa di presentazione lato app per ciascun OS — corretta sia per l'i18n sia per la portabilità su Android.

I meccanismi dell'i18n (il glossario di localizzazione, lo schema dei file di localizzazione e la checklist di revisione delle traduzioni) vivono nei documenti interni sull'i18n, non in questo insieme pubblico.

---

## 7. Materiali di riferimento

Riferimenti di design in HTML (non rilasciati, interni): lo storyboard del flusso di onboarding, uno studio dell'aspetto kiwi-creme del guardiano e le opzioni visive del pulsante principale dentro i pannelli.

Le fondamenta del DS sono arrivate: il gruppo `LavaDesignSystem/`, i token `LavaSpacing`/raggio/`dangerRed`, la semantica di profondità `LavaTier` e il livello di ruoli `LavaIcon` sono tutti rilasciati (lavasec-ios: LavaSecApp/LavaDesignSystem/). Ciò che resta **Pianificato** nel piano di portabilità/fondamenta è la tokenizzazione dell'accento `LavaColorRole` (Fase 3), la mappa di presentazione per ciascun OS per le stringhe inglesi lato core (Fase 4), un JSON di token neutro e multipiattaforma e i più ampi punti di aggancio per la portabilità su Android.
