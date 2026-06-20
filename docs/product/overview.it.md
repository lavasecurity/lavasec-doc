---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Panoramica del prodotto

Benvenuto in Lava Security. Questa pagina è la porta d'ingresso alla documentazione: una breve introduzione, in parole semplici, a cos'è Lava, cosa promette e dove leggere di più.

## Cos'è Lava

Lava Security è un'app iOS che mette la privacy al primo posto e filtra le richieste DNS in locale, direttamente sul dispositivo, attraverso un [tunnel a pacchetti NetworkExtension](../architecture/ios-client.md) integrato nell'app, bloccando i domini noti come rischiosi o indesiderati senza far passare la tua navigazione dai server di Lava. Il tunnel a pacchetti (`LavaSecTunnel`, un `NEPacketTunnelProvider`) analizza ogni richiesta DNS sul telefono, confronta il dominio richiesto con uno snapshot di filtri compilato e mappato in memoria, e inoltra a monte solo le richieste consentite. Non c'è alcun proxy gestito da Lava attraverso cui passa il tuo traffico: il filtraggio è una decisione locale, presa sul tuo dispositivo.

iOS lo chiama "VPN" perché un tunnel a pacchetti è l'unico modo in cui un'app può filtrare il DNS a livello di tutto il sistema, ma Lava è **filtraggio DNS basato su liste di blocco**, non instradamento del traffico. Diciamo le cose come stanno: Lava è filtraggio DNS locale dei domini, **non** una garanzia che ogni dominio o URL dannoso venga bloccato. Vede i domini, non i percorsi delle pagine, quindi non può bloccare una singola pagina problematica su un sito per il resto affidabile. Inoltre la protezione non si attiva da sola nel momento in cui finisci la configurazione iniziale: la scheda **Guardia** all'interno dell'app è la fonte affidabile per sapere se la protezione è attualmente attiva.

## La promessa sulla privacy

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non fa mai passare la tua navigazione dai propri server e non riceve mai l'elenco dei domini che visiti: il backend conserva solo i metadati del catalogo, un backup cifrato per utente in forma opaca e le diagnostiche anonime che scegli di inviare.

Questa frase è quella di riferimento. Tutto il resto in questa documentazione è pensato per essere coerente con essa. Pagare il livello opzionale **non** sposta il filtraggio sul server né dà a Lava l'elenco dei domini che visiti. Quando una funzione coinvolge un server, la documentazione spiega chiaramente cosa **non** viene inviato: le tue normali richieste DNS, la tua cronologia di navigazione e qualsiasi testo in chiaro restano tutti sul dispositivo. Per il quadro completo vedi [il backend e il modello dei dati](../architecture/backend-and-data.md).

## A chi è rivolto

Lava è pensato per chiunque voglia navigare in modo più sicuro senza doversene occupare. Il pubblico comprende volutamente le persone meno esperte di tecnologia: genitori che impostano la protezione per la famiglia, persone più anziane e chiunque non voglia pensare affatto al DNS. L'esperienza predefinita funziona e basta: attiva la protezione e una lista di blocco prudente inizia a filtrare, senza bisogno di un account. Allo stesso tempo, chi vuole approfondire può raggiungere controlli più avanzati (liste di blocco personalizzate, resolver alternativi) quando lo desidera.

Il tono, ovunque, è semplice, calmo e pratico: il pericolo è presentato come una metafora, non come paura.

## Principi fondamentali

- **La privacy è un punto di partenza, non una funzione a pagamento.** Il filtraggio è una decisione locale. Il backend di Lava è volutamente ridotto al minimo e non riceve mai i domini della tua navigazione abituale né i flussi di eventi DNS. Il backup opzionale dell'account è a [conoscenza zero](../architecture/accounts-and-backup.md): i server conservano solo testo cifrato e i metadati non segreti della "busta".
- **Protezione di base gratuita per sempre.** L'interruttore della protezione, gli aggiornamenti della lista di blocco predefinita e i conteggi locali essenziali non sono mai a pagamento e non richiedono mai un account.
- **Sul dispositivo.** Il motore di protezione vive interamente sul telefono: l'analisi DNS, la valutazione dei domini e l'inoltro a monte avvengono tutti all'interno dell'estensione del tunnel a pacchetti, entro il limite di memoria di iOS di circa 50 MiB per estensione. Le liste di blocco seguono un modello [basato solo sull'URL della fonte](../architecture/dns-filtering-and-blocklists.md): l'app scarica ogni lista a monte direttamente e la analizza in locale; Lava non ospita né distribuisce mai i contenuti delle liste di blocco di terze parti.
- **Il pagamento sblocca solo la personalizzazione, mai la sicurezza di base.** La barriera di protezione dalle minacce — un livello non disattivabile, al di sopra di ogni lista di blocco, che nessuno può inserire tra le eccezioni consentite, a pagamento o meno — è garantita da un ordine di precedenza nelle decisioni: **barriera di protezione dalle minacce > lista locale delle eccezioni consentite > lista di blocco > consenti per impostazione predefinita.** (Lo spazio nell'ordine di precedenza è già predisposto e la sua integrità è verificata tramite hash SHA-256 accettati; al momento viene distribuito senza alcuna voce.) Il tunnel ignora `isPaid`.
- **Nucleo tranquillo, profondità guadagnata.** Le schermate predefinite sono silenziose e rassicuranti, con in primo piano la mascotte Soft Shield Guardian e testi che evitano un linguaggio basato sulla paura. Dettagli più ricchi e tecnici sono disponibili quando vai a cercarli, ma non ti vengono mai imposti. Questa filosofia del "nucleo tranquillo, profondità guadagnata" è formalizzata nel modello di profondità **LavaTier** (Floor / Window / Workshop): vedi [il design system](../design-system/overview.md).

## Funzionalità principali

- **Filtraggio DNS locale** — il motore del tunnel a pacchetti che analizza il DNS, valuta ogni dominio rispetto allo snapshot compilato e inoltra a monte le richieste consentite, con ripiego sul DNS del dispositivo. Vedi [il client iOS](../architecture/ios-client.md) e [filtraggio DNS e liste di blocco](../architecture/dns-filtering-and-blocklists.md).
- **Liste di blocco curate, basate solo sull'URL della fonte** — Lava pubblica solo gli URL delle liste a monte più gli hash accettati; il dispositivo scarica, verifica e analizza da sé i contenuti delle liste, e Lava non duplica né distribuisce mai i contenuti delle liste di blocco di terze parti. L'impostazione predefinita distribuita attiva **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definita in `OnboardingDefaults.swift`); le fonti GPL (HaGeZi, OISD) sono attivabili a scelta. Vedi [filtraggio DNS e liste di blocco](../architecture/dns-filtering-and-blocklists.md).
- **Trasporti DNS cifrati** — DoH (con annotazione osservativa DoH3), DoT (connessioni in pool, riutilizzate e aggiornate) e DoQ (una nuova connessione per ogni richiesta). Tutti e tre sono implementati; il DNS del dispositivo (il resolver della rete stessa) è l'impostazione predefinita distribuita, e i preset cifrati sono attivabili a scelta (`AppConfiguration.lavaRecommendedDefaults`, definita in `Sources/LavaSecCore/OnboardingDefaults.swift`). I preset di resolver integrati (le varianti DoH e DoT di Google / Cloudflare / Quad9) sono gratuiti; solo un resolver completamente personalizzato è uno sblocco a pagamento. Vedi [filtraggio DNS e liste di blocco](../architecture/dns-filtering-and-blocklists.md).
- **Eccezioni consentite (allowlist)** — aggiungi manualmente domini da consentire nonostante una lista di blocco; la barriera di protezione dalle minacce ha comunque la precedenza. Vedi [la panoramica delle funzionalità del prodotto](features.md).
- **Il Soft Shield Guardian** — una mascotte nella scheda Guardia, nella Live Activity e nella Dynamic Island che esprime lo stato della protezione attraverso 7 espressioni. Vedi [il design system](../design-system/overview.md).
- **Personalizzazione a livelli (Lava Security Plus)** — un unico livello a pagamento opzionale che sblocca la personalizzazione (una capacità maggiore per le regole di filtro — 500.000 regole compilate per Free / 2 milioni per Plus, entro una barriera di sicurezza condivisa sul dispositivo — più domini consentiti/bloccati, liste di blocco personalizzate e resolver DNS personalizzati). Plus non aggira mai le protezioni sempre attive: il tunnel ignora `isPaid`.
- **Account e backup opzionali** — accesso con Apple o Google con un backup delle impostazioni cifrato end-to-end ([a conoscenza zero](../architecture/accounts-and-backup.md)) e una frase di recupero; l'eliminazione dell'account è autonoma. Lo slot opzionale di recupero con passkey è **anch'esso a conoscenza zero**: la sua chiave viene derivata sul dispositivo dalla PRF WebAuthn dell'autenticatore, senza alcun segreto conservato dal server; la disponibilità per la produzione sul dispositivo dipende ancora dall'hosting di Associated Domains / AASA **(Pianificato)**. Gli account sono opzionali; la protezione funziona pienamente anche senza accesso.
- **Attività e report solo in locale** — conteggi di blocchi/consensi sul dispositivo, stato del tunnel e un pacchetto di segnalazione bug attivabile a scelta, costruiti a partire dai dati che il tunnel in esecuzione conserva sul dispositivo — vuoti quando è inattivo e aggiornati in tempo reale mentre protegge. Nessuna cronologia abituale dei domini lascia il dispositivo. Vedi [la panoramica delle funzionalità del prodotto](features.md).

## Piattaforme

- **iOS — disponibile.** Oggi Lava è un'app iOS: tre bundle condividono un unico App Group (`group.com.lavasec`) — l'app (`com.lavasec.app`), l'estensione del tunnel a pacchetti (`.tunnel`) e il widget (`.widget`) — più i sorgenti condivisi, basati su un pacchetto comune `LavaSecCore`.
- **Android — Pianificato.** È pianificato un port nativo in Kotlin / Jetpack Compose basato sul `VpnService` di Android, che porta con sé la stessa promessa sulla privacy e un comportamento di filtraggio di base verificato per la parità. Non viene ancora distribuito alcun codice dell'app Android.

Vedi [Parità tra piattaforme](platform-parity.md) per gli id stabili delle funzionalità e il contratto iOS/Android.
