---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Panoramica del prodotto

Benvenuto in Lava Security. Questa pagina è la porta d'ingresso alla documentazione: una breve e semplice introduzione a cosa è Lava, cosa promette e dove approfondire.

## Cos'è Lava

Lava Security è un'app iOS privacy-first che filtra il DNS localmente sul dispositivo attraverso un [packet tunnel NetworkExtension](../architecture/ios-client.md) on-device, bloccando i domini noti come rischiosi e indesiderati senza instradare la tua navigazione attraverso i server di Lava. Il packet tunnel (`LavaSecTunnel`, un `NEPacketTunnelProvider`) analizza ogni query DNS sul telefono, confronta il dominio richiesto con uno snapshot del filtro compilato e mappato in memoria, e inoltra a monte solo le query consentite. Non esiste alcun proxy gestito da Lava attraverso cui passa il tuo traffico: il filtraggio è una decisione locale, presa sul tuo dispositivo.

iOS lo etichetta come "VPN" perché un packet tunnel è l'unico modo in cui un'app può filtrare il DNS a livello di sistema — ma Lava è **filtraggio DNS/blocklist**, non instradamento del traffico. Sii onesto sull'ambito: Lava è filtraggio locale di domini DNS, **non** una garanzia che ogni dominio o URL dannoso venga bloccato. Vede i domini, non i percorsi delle pagine, quindi non può bloccare una singola pagina dannosa su un host altrimenti affidabile. La protezione inoltre non si attiva automaticamente nel momento in cui termina l'onboarding — la scheda **Guard** in-app è la fonte autorevole per sapere se la protezione è attualmente attiva.

## La promessa sulla privacy

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva solo i metadati del catalogo, un backup cifrato e opaco per ogni utente e i dati diagnostici anonimizzati che scegli di inviare.

Questa frase è canonica. Tutto il resto in questa documentazione è pensato per essere coerente con essa. Pagare per il livello opzionale **non** sposta il filtraggio sul server né fornisce a Lava un flusso dei domini visitati. Quando una funzionalità tocca un server, la documentazione specifica cosa **non** viene inviato — le tue query DNS di routine, la tua cronologia di navigazione e qualsiasi testo in chiaro restano tutti sul dispositivo. Vedi [il backend e il modello dei dati](../architecture/backend-and-data.md) per il quadro completo.

## A chi è rivolto

Lava è pensato per chiunque voglia una navigazione più sicura senza doverla gestire. Il pubblico include deliberatamente anche utenti non tecnici — genitori che impostano la protezione per la famiglia, persone anziane e chiunque non voglia pensare affatto al DNS. L'esperienza predefinita funziona e basta: attiva la protezione e una blocklist conservativa inizia a filtrare, senza bisogno di un account. Allo stesso tempo, gli utenti esperti possono raggiungere controlli più avanzati (blocklist personalizzate, resolver alternativi) quando lo desiderano.

Il tono in tutta l'app è semplice, pacato e pratico — il pericolo è presentato come una metafora, non come paura.

## Principi fondamentali

- **La privacy è posizionamento, non una funzione a pagamento.** Il filtraggio è una decisione locale. Il backend di Lava è intenzionalmente minimale e non riceve mai i tuoi domini di navigazione di routine né i flussi di eventi DNS. Il backup opzionale dell'account è [zero-knowledge](../architecture/accounts-and-backup.md): i server memorizzano solo testo cifrato e metadati dell'envelope non segreti.
- **Protezione di base gratuita per sempre.** L'interruttore della protezione, gli aggiornamenti della blocklist predefinita e i conteggi locali di base non sono mai a pagamento e non richiedono mai un account.
- **On-device.** Il motore di protezione risiede interamente sul telefono — l'analisi del DNS, la valutazione dei domini e l'inoltro a monte avvengono tutti all'interno dell'estensione packet-tunnel, vincolati dal limite di memoria di iOS di ~50 MiB per estensione. Le blocklist seguono un modello [source-url-only](../architecture/dns-filtering-and-blocklists.md): l'app recupera direttamente ogni lista a monte e la analizza localmente; Lava non ospita né distribuisce mai byte di blocklist di terze parti.
- **Il pagamento sblocca solo la personalizzazione — mai la sicurezza di base.** La protezione contro le minacce — un livello non escludibile, al di sopra di ogni blocklist, che nessuno, a pagamento o meno, può inserire in allowlist — è imposta dalla precedenza decisionale: **protezione contro le minacce > allowlist locale (eccezioni consentite) > blocklist > consenti per default.** (Lo slot di precedenza è collegato e verificato per integrità tramite hash SHA-256 accettati; attualmente viene distribuito senza voci.) Il tunnel ignora `isPaid`.
- **Nucleo pacato, profondità conquistata.** Le superfici predefinite sono silenziose e rassicuranti, presentate dalla mascotte Soft Shield Guardian e da testi che evitano un linguaggio basato sulla paura. Dettagli più ricchi e tecnici sono disponibili quando vai a cercarli, ma non ti vengono mai imposti. Questa filosofia di "nucleo pacato, profondità conquistata" è formalizzata nel modello di profondità **LavaTier** (Floor / Window / Workshop) — vedi [il design system](../design-system/overview.md).

## Capacità ad alto livello

- **Filtraggio DNS locale** — il motore packet-tunnel che analizza il DNS, valuta ogni dominio rispetto allo snapshot compilato e inoltra a monte le query consentite con fallback al DNS del dispositivo. Vedi [il client iOS](../architecture/ios-client.md) e [filtraggio DNS e blocklist](../architecture/dns-filtering-and-blocklists.md).
- **Blocklist curate, source-url-only** — Lava pubblica solo gli URL delle liste a monte (più hash indicativi per l'identità della cache e l'audit); il dispositivo recupera ogni lista su TLS e la analizza localmente entro limiti di dimensione/regole, e Lava non rispecchia né distribuisce mai byte di blocklist di terze parti. Le liste della community non sono ancorate tramite hash — TLS + l'URL curato sono il confine di integrità — mentre il livello di protezione contro le minacce di Lava resta imposto tramite hash. Il valore predefinito distribuito abilita **Block List Basic** (`AppConfiguration.lavaRecommendedDefaults`, definito in `OnboardingDefaults.swift`); le fonti copyleft come HaGeZi, OISD, AdGuard e 1Hosts sono opt-in. Vedi [filtraggio DNS e blocklist](../architecture/dns-filtering-and-blocklists.md).
- **Trasporti DNS cifrati** — DoH (con annotazione osservativa DoH3), DoT (connessioni in pool, riutilizzate e aggiornate) e DoQ (connessione nuova per ogni query). Tutti e tre sono implementati; Device DNS (il resolver della rete stessa) è il valore predefinito distribuito, e i preset cifrati sono opt-in (`AppConfiguration.lavaRecommendedDefaults`, definito in `Sources/LavaSecCore/OnboardingDefaults.swift`). I preset di resolver integrati (varianti DoH e DoT di Google / Cloudflare / Quad9) sono gratuiti; solo un resolver completamente personalizzato è uno sblocco a pagamento. Vedi [filtraggio DNS e blocklist](../architecture/dns-filtering-and-blocklists.md).
- **Eccezioni consentite (allowlist)** — aggiungi manualmente domini da permettere nonostante una blocklist; la protezione contro le minacce vince comunque. Vedi [la panoramica delle funzionalità del prodotto](features.md).
- **Il Soft Shield Guardian** — una mascotte sulla scheda Guard, sulla Live Activity e sulla Dynamic Island che esprime lo stato della protezione attraverso 7 stati espressivi. Vedi [il design system](../design-system/overview.md).
- **Personalizzazione a livelli (Lava Security Plus)** — un unico livello opzionale a pagamento che sblocca la personalizzazione (un budget più ampio di regole del filtro — Free 500K / Plus 2M regole compilate sotto una protezione di sicurezza del dispositivo condivisa — più domini consentiti/bloccati, blocklist personalizzate e resolver DNS personalizzati). Plus non aggira mai le protezioni sempre attive — il tunnel ignora `isPaid`.
- **Account e backup opzionali** — accesso con Apple o Google con un backup delle impostazioni cifrato end-to-end ([zero-knowledge](../architecture/accounts-and-backup.md)) e una frase di recupero; l'eliminazione dell'account è self-service. Lo slot opzionale di recupero tramite passkey è **anch'esso zero-knowledge** — la sua chiave è derivata on-device dalla PRF WebAuthn dell'autenticatore, senza alcun segreto conservato sul server; la prontezza per la produzione on-device dipende ancora dall'hosting di Associated Domains / AASA **(Pianificato)**. Gli account sono opzionali; la protezione funziona completamente anche senza login.
- **Attività e report solo locali** — conteggi di blocco/consenso on-device, stato di salute del tunnel e un pacchetto di segnalazione bug opt-in, costruiti a partire dai dati che il tunnel in esecuzione conserva sul dispositivo — vuoti quando è inattivo e attivi mentre protegge. Nessuna cronologia di routine dei domini lascia il dispositivo. Vedi [la panoramica delle funzionalità del prodotto](features.md).

## Piattaforme

- **iOS — distribuito.** Lava è oggi un'app iOS: tre bundle condividono un unico App Group (`group.com.lavasec`) — l'app (`com.lavasec.app`), l'estensione packet-tunnel (`.tunnel`) e il widget (`.widget`) — più sorgenti condivisi, su un pacchetto comune `LavaSecCore`.
- **Android — Pianificato.** È pianificato un port nativo in Kotlin / Jetpack Compose su `VpnService` di Android, che porta con sé la stessa promessa sulla privacy e un comportamento di filtraggio di base testato per la parità. Nessun codice dell'app Android è ancora distribuito.

Vedi [Parità tra piattaforme](platform-parity.md) per gli id stabili delle funzionalità e il contratto iOS/Android.
