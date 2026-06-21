# Parità tra piattaforme {#platform-parity}

Il sistema di parità tra piattaforme di Lava tiene traccia di quali promesse del
prodotto sono condivise tra iOS, Android e i client futuri. È il contratto
pubblico sul comportamento delle funzioni: cosa deve voler dire la stessa cosa
ovunque, cosa è volutamente specifico di ogni sistema operativo e cosa non è
ancora promesso.

I documenti sulla parità non sostituiscono i piani di implementazione né i test:

- `lavasec-doc` definisce il contratto su prodotto e comportamento.
- I piani interni gestiscono lo stato di rilascio, le sequenze, i rischi privati e
  l'allineamento con il consiglio.
- I repository delle piattaforme contengono il codice, i fixture e i test che
  dimostrano il comportamento.

Quando i documenti e il codice rilasciato non coincidono, vale il codice finché i
documenti non vengono aggiornati. Quando un piano e questa pagina non coincidono,
considera questa pagina come il contratto del prodotto e il piano come la coda dei
lavori da fare.

## Vocabolario degli stati {#status-vocabulary}

| Stato | Significato |
|---|---|
| **Rilasciato** | Implementato nel codice di produzione per quella piattaforma. |
| **Parziale** | Una parte del comportamento esiste, ma il contratto pubblico non è del tutto rispettato. |
| **Pianificato** | Accettato come parte del contratto della piattaforma, non ancora implementato. |
| **Rimandato** | Funzione valida, ma non necessaria per la prossima tappa della piattaforma. |
| **Specifico della piattaforma** | Stessa promessa per l'utente, implementazione diversa a seconda del sistema operativo. |
| **Non applicabile** | Su quella piattaforma non dovrebbe esistere una funzione equivalente. |
| **Abbandonato** | In passato preso in considerazione o realizzato, poi rimosso di proposito. |

## Formato della scheda funzione {#feature-record-format}

Ogni funzione tracciata per la parità dovrebbe avere un identificatore stabile.
Usa nomi nella forma `area.capability` che restino validi anche quando cambia il
testo dell'interfaccia, per esempio `filtering.guardrail-precedence` o
`dns.encrypted-transports`.

Una scheda funzione completa risponde a queste domande:

| Campo | Scopo |
|---|---|
| `feature_id` | Identificatore stabile usato in piani, PR, test e documenti. |
| Promessa del prodotto | Su cosa possono contare gli utenti, in un linguaggio indipendente dalla piattaforma. |
| Requisito di parità | Se Android deve corrispondere a iOS esattamente, corrispondere per intento o restare volutamente diverso. |
| Stato per piattaforma | Stato su iOS, Android e client futuri. |
| Verifica | Test, fixture, file sorgente o controlli di revisione che mantengono onesto il comportamento. |
| Note sulla piattaforma | Differenze legate al sistema operativo che devono essere esplicite, non riscoperte in seguito. |

## Procedura di aggiornamento {#update-workflow}

1. Aggiungi o aggiorna l'identificatore della funzione quando una modifica cambia
   una promessa del prodotto, una garanzia sulla privacy, un confine tra i piani o
   un comportamento tra piattaforme.
2. Collega lo stesso identificatore dal piano di implementazione quando serve del
   lavoro.
3. Aggiungi o aggiorna i test della piattaforma o i golden fixture per i
   comportamenti che devono corrispondere.
4. Quando una piattaforma rilascia il comportamento, aggiorna qui lo stato e
   rinfresca la pagina sulla funzione o sull'architettura interessata.
5. Mantieni privati i dettagli interni legati solo all'implementazione, alla
   riservatezza, ai prezzi, ai rischi legali e alle operazioni; qui riassumi solo
   il contratto pubblico.

## Registro attuale della parità {#current-parity-ledger}

| Identificatore funzione | Promessa del prodotto | iOS | Android | Requisito di parità | Verifica / sorgente |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava filtra il DNS localmente sul dispositivo e non instrada la navigazione attraverso i server di Lava. | Rilasciato | Pianificato | Corrispondenza per intento; le API dei tunnel del sistema operativo sono diverse. | Architettura del packet tunnel su iOS; piano `VpnService` su Android. |
| `protection.vpn-disclosure` | L'app spiega perché il sistema operativo chiama VPN il filtraggio DNS locale prima di chiedere il permesso/la configurazione della VPN. | Rilasciato | Pianificato | Testo e flusso dei permessi specifici della piattaforma. | Documenti di onboarding; piano di comunicazione per Android su Play. |
| `filtering.guardrail-precedence` | Le protezioni sempre attive prevalgono sulle liste consentite dall'utente; lo stato a pagamento non aggira mai le protezioni. | Rilasciato | Pianificato | Parità esatta del comportamento. | `CompactFilterSnapshotTests`; `FilterSnapshotTest` su Android una volta portato. |
| `filtering.source-url-only-catalog` | Lava pubblica i metadati del catalogo e gli URL delle sorgenti originali, non i byte delle blocklist di terze parti. | Rilasciato | Pianificato | Parità esatta del modello di privacy/proprietà intellettuale. | Architettura del catalogo; documenti legali GPL/solo-URL-sorgente. |
| `filtering.on-device-parsing` | Le liste selezionate vengono scaricate ed elaborate sul dispositivo; la cronologia ordinaria dei domini non viene inviata a Lava. | Rilasciato | Pianificato | Parità esatta sulla privacy, archiviazione nativa consentita. | `BlocklistParserTests`; test di parità del parser Android una volta portati. |
| `filtering.rule-budget` | I limiti dei filtri si basano sul numero di regole compilate e sulla sicurezza del dispositivo, non su un conteggio arbitrario delle liste. | Rilasciato | Pianificato | Stesso modello per l'utente; i limiti di memoria della piattaforma possono variare. | Test del budget dei filtri su iOS; test del budget su Android quando i limiti del dispositivo saranno noti. |
| `dns.built-in-resolvers` | Gli utenti possono scegliere i resolver predefiniti integrati senza inviare a Lava le richieste consentite. | Rilasciato | Pianificato | Stessa politica sui resolver; l'insieme dei preset può uscire a fasi. | Test sui preset dei resolver; test sui DTO dei resolver Android una volta portati. |
| `dns.encrypted-transports` | Per le richieste consentite è disponibile il DNS cifrato verso l'upstream. | Rilasciato | Pianificato | Parità graduale consentita; la v1 di Android può partire con DoH prima di DoT/DoQ. | Test sui trasporti iOS; test sui resolver Android e QA sul dispositivo. |
| `reports.local-only-diagnostics` | Report e diagnostica restano in locale finché l'utente non invia esplicitamente un pacchetto di supporto. | Rilasciato | Pianificato | Parità esatta sulla privacy; l'interfaccia può differire. | Test del pacchetto di segnalazione bug; test dell'anteprima del report di debug su Android quando sarà realizzato. |
| `account.optional-sign-in` | La protezione funziona senza un account; l'accesso è facoltativo. | Rilasciato | Rimandato | Promessa del prodotto identica prima che Android esponga le funzioni dell'account. | Documenti sull'autenticazione dell'account; revisione di onboarding/impostazioni su Android. |
| `backup.zero-knowledge-settings` | Il backup facoltativo delle impostazioni memorizza solo testo cifrato; Lava non può leggere il contenuto in chiaro del backup. | Rilasciato | Rimandato | Parità esatta sulla privacy prima che Android offra il backup. | Test sul backup zero-knowledge; test di parità crittografica su Android quando sarà realizzato. |
| `plus.customization-boundary` | La protezione gratuita resta utile; Plus sblocca la personalizzazione avanzata e non cambia mai la sicurezza delle protezioni. | Rilasciato | Pianificato | Stesso confine del prodotto; l'implementazione nello store è specifica della piattaforma. | Test sulla politica degli abbonamenti; test sui diritti di Play Billing quando saranno realizzati. |
| `design.calm-earned-depth` | L'esperienza predefinita è tranquilla, con superfici tecniche più approfondite o celebrative solo quando ce n'è motivo o quando vengono richieste. | Parziale | Pianificato | Corrispondenza per intento di design tramite token/ruoli condivisi. | Documenti del design system e piano per le basi della portabilità. |
| `platform.ambient-presence` | Lo stato della protezione può comparire fuori dall'app quando il sistema operativo offre una superficie ambientale nativa. | Specifico della piattaforma | Pianificato | Parità di intento, non di superficie. | Documenti sulle Live Activity di iOS; decisione su notifica/Impostazioni rapide di Android in sospeso. |

## Uso per la preparazione di Android {#android-readiness-use}

Prima di iniziare l'implementazione su Android, questa pagina va riesaminata
insieme al piano per Android e al piano di portabilità del design system. Il
contratto minimo per essere pronti su Android è:

- ogni funzione che riguarda la privacy ha un identificatore;
- il comportamento a parità esatta ha un test o un fixture sorgente iOS
  identificato;
- il comportamento specifico della piattaforma ha una posizione esplicita per
  Android;
- le funzioni rimandate sono indicate per nome, così l'MVP di Android non lascia
  intendere per sbaglio che vengano rilasciate.

Quel riesame appartiene al piano di implementazione o alle note di revisione,
mentre questa pagina mantiene il contratto pubblico e duraturo.
