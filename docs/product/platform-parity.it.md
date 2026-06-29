# Parità tra piattaforme

Il sistema di parità tra piattaforme di Lava tiene traccia di quali promesse di
prodotto sono condivise tra iOS, Android e i client futuri. È il contratto
pubblico per il comportamento delle funzionalità: cosa deve significare la
stessa cosa ovunque, cosa è intenzionalmente nativo della piattaforma e cosa non
è ancora promesso.

I documenti di parità non sostituiscono i piani di implementazione o i test:

- `lavasec-doc` possiede il contratto di prodotto e di comportamento.
- I piani interni possiedono lo stato di consegna, la sequenza, i rischi privati e
  la sincronizzazione con il consiglio.
- I repository di piattaforma possiedono il codice, le fixture e i test che
  dimostrano il comportamento.

Quando i documenti e il codice rilasciato sono in disaccordo, il codice prevale
finché i documenti non vengono aggiornati. Quando un piano e questa pagina sono
in disaccordo, considera questa pagina come il contratto di prodotto e il piano
come la coda di lavoro.

## Vocabolario di stato

| Stato | Significato |
|---|---|
| **Shipped** | Implementato nel codice di produzione per quella piattaforma. |
| **Partial** | Esiste un comportamento parziale, ma il contratto pubblico non è pienamente rispettato. |
| **Planned** | Accettato come parte del contratto di piattaforma, non ancora implementato. |
| **Deferred** | Funzionalità valida, ma non richiesta per la prossima milestone della piattaforma. |
| **Platform-native** | Stessa promessa all'utente, implementazione diversa specifica del sistema operativo. |
| **Not applicable** | Non dovrebbe esistere alcuna funzionalità equivalente su quella piattaforma. |
| **Dropped** | Precedentemente considerata o costruita, poi rimossa intenzionalmente. |

## Formato del record di funzionalità

Ogni funzionalità tracciata per la parità dovrebbe avere un id stabile. Usa nomi
`area.capability` che sopravvivono ai cambiamenti del testo dell'interfaccia, ad
esempio `filtering.guardrail-precedence` o `dns.encrypted-transports`.

Un record di funzionalità completo risponde a:

| Campo | Scopo |
|---|---|
| `feature_id` | Id stabile usato in piani, PR, test e documenti. |
| Promessa di prodotto | Ciò su cui gli utenti possono fare affidamento, in un linguaggio neutro rispetto alla piattaforma. |
| Requisito di parità | Se Android deve corrispondere a iOS esattamente, corrispondere per intento o restare intenzionalmente diverso. |
| Stato della piattaforma | Stato di iOS, Android e dei client futuri. |
| Applicazione | Test, fixture, file sorgente o controlli di revisione che mantengono il comportamento corretto. |
| Note di piattaforma | Differenze specifiche del sistema operativo che devono essere esplicite, non riscoperte in seguito. |

## Flusso di aggiornamento

1. Aggiungi o aggiorna l'id della funzionalità quando una modifica altera una
   promessa di prodotto, un'affermazione sulla privacy, un confine di livello o
   un comportamento multipiattaforma.
2. Collega lo stesso id della funzionalità dal piano di implementazione quando è
   necessario del lavoro.
3. Aggiungi o aggiorna i test di piattaforma o le fixture golden per i
   comportamenti che devono corrispondere.
4. Quando una piattaforma rilascia il comportamento, aggiorna lo stato qui e
   aggiorna la relativa pagina di funzionalità o architettura.
5. Mantieni privati i dettagli interni di sola implementazione, privati, di
   prezzo, di rischio legale e operativi; riepiloga qui solo il contratto
   pubblico.

## Registro di parità attuale

| Feature id | Promessa di prodotto | iOS | Android | Requisito di parità | Applicazione / sorgente |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava filtra il DNS localmente sul dispositivo e non instrada la navigazione attraverso i server Lava. | Shipped | Planned | Corrispondenza per intento; le API del tunnel del sistema operativo differiscono. | Architettura del packet tunnel iOS; piano `VpnService` per Android. |
| `protection.vpn-disclosure` | L'app spiega perché il sistema operativo chiama VPN il filtraggio DNS locale prima di chiedere il permesso/la configurazione della VPN. | Shipped | Planned | Testo e flusso di permessi nativi della piattaforma. | Documenti di onboarding; piano di disclosure per Android Play. |
| `filtering.guardrail-precedence` | Le protezioni sempre attive prevalgono sulle liste di consenso dell'utente; lo stato a pagamento non aggira mai le protezioni. | Shipped | Planned | Parità esatta del comportamento. | `CompactFilterSnapshotTests`; `FilterSnapshotTest` per Android una volta portato. |
| `filtering.source-url-only-catalog` | Lava pubblica i metadati del catalogo e gli URL delle sorgenti upstream, non i byte delle blocklist di terze parti. | Shipped | Planned | Parità esatta del modello di privacy/IP. | Architettura del catalogo; documenti legali GPL/source-url-only. |
| `filtering.on-device-parsing` | Le liste selezionate vengono scaricate e analizzate sul dispositivo; la cronologia dei domini di routine non viene caricata su Lava. | Shipped | Planned | Parità esatta della privacy, archiviazione nativa consentita. | `BlocklistParserTests`; test di parità del parser Android una volta portati. |
| `filtering.rule-budget` | I limiti del Filtro si basano sul numero di regole compilate e sulla sicurezza del dispositivo, non su un conteggio arbitrario delle liste. | Shipped | Planned | Stesso modello rivolto all'utente; i limiti di memoria della piattaforma possono differire. | Test del budget del Filtro iOS; test del budget Android quando i limiti del dispositivo saranno noti. |
| `dns.built-in-resolvers` | Gli utenti possono scegliere preset di resolver integrati senza inviare a Lava le ricerche consentite. | Shipped | Planned | Stessa policy dei resolver; l'insieme dei preset può essere rilasciato in fasi. | Test dei preset dei resolver; test dei DTO dei resolver Android una volta portati. |
| `dns.encrypted-transports` | Il DNS upstream cifrato è disponibile per le query consentite. | Shipped | Planned | Parità graduale consentita; Android v1 può partire con DoH prima di DoT/DoQ. | Test di trasporto iOS; test dei resolver Android e QA su dispositivo. |
| `reports.local-only-diagnostics` | Report e diagnostica restano locali a meno che l'utente non invii esplicitamente un bundle di supporto. | Shipped | Planned | Parità esatta della privacy; l'interfaccia può differire. | Test del bundle di segnalazione bug; test di anteprima del debug-report Android una volta costruiti. |
| `account.optional-sign-in` | La protezione funziona senza un account; l'accesso è facoltativo. | Shipped | Deferred | Promessa di prodotto esatta prima che Android esponga le funzionalità dell'account. | Documenti di autenticazione dell'account; revisione di onboarding/impostazioni Android. |
| `backup.zero-knowledge-settings` | Il backup facoltativo delle impostazioni archivia solo testo cifrato; Lava non può leggere i contenuti del backup in chiaro. | Shipped | Deferred | Parità esatta della privacy prima che Android offra il backup. | Test di backup zero-knowledge; test di parità crittografica Android una volta costruiti. |
| `plus.customization-boundary` | La protezione gratuita resta utile; Plus sblocca la personalizzazione avanzata e non cambia mai la sicurezza delle protezioni. | Shipped | Planned | Stesso confine di prodotto; l'implementazione dello store è nativa della piattaforma. | Test della policy di abbonamento; test di entitlement Play Billing una volta costruiti. |
| `design.calm-earned-depth` | L'UX predefinita è calma, con superfici tecniche o celebrative più approfondite solo quando guadagnate o richieste. | Partial | Planned | Corrispondenza per intento di design tramite token/ruoli condivisi. | Documenti del design system e piano di base per la portabilità. |
| `platform.ambient-presence` | Lo stato della protezione può apparire al di fuori dell'app quando il sistema operativo supporta una superficie ambientale nativa. | Platform-native | Planned | Parità di intento, non parità di superficie. | Documenti Live Activity iOS; decisione su notifica/Quick Settings Android in sospeso. |

## Uso per la preparazione di Android

Prima che inizi l'implementazione di Android, questa pagina dovrebbe essere
rivista insieme al piano Android e al piano di portabilità del design system. Il
contratto minimo pronto per Android è:

- ogni funzionalità che riguarda la privacy ha un id di funzionalità;
- il comportamento a parità esatta ha una fonte di test o fixture iOS
  identificata;
- il comportamento nativo della piattaforma ha una posizione Android esplicita;
- le funzionalità rinviate sono nominate così che l'MVP Android non implichi
  accidentalmente che vengano rilasciate.

Quella revisione appartiene al piano di implementazione o alle note di revisione,
mentre questa pagina mantiene il contratto pubblico e durevole.
