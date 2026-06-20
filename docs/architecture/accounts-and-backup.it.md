---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Account e backup a conoscenza zero

> **Pubblico:** ingegneri.
> **Autorità:** dove questo documento e un piano sono in disaccordo, **vince il codice** — le divergenze sono segnalate caso per caso. Lo stato riflette la realtà confermata dal codice, non le aspirazioni del piano. Legenda degli stati: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente realizzato), **Pianificato** (progettato, non costruito), **Abbandonato** (rifiutato o annullato).

Gli account sono **facoltativi**. La protezione di base è gratuita per sempre e non richiede alcun account; l'accesso serve solo per fare il backup delle tue *impostazioni*, cifrate, così da poterle ripristinare su un nuovo dispositivo. Questo documento illustra il flusso di autenticazione, dove risiede la sessione, l'involucro del backup a conoscenza zero, i percorsi di recupero ed esattamente ciò che il server può e non può vedere.

La promessa di privacy fondamentale a cui questo documento risponde:

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva solo i metadati del catalogo, un backup cifrato per utente non leggibile e diagnostiche anonimizzate che scegli di inviare.

Suddivisione dei componenti: la crittografia pura e la costruzione delle richieste risiedono in `LavaSecCore`; l'orchestrazione e l'interfaccia risiedono in `LavaSecApp`. Documenti correlati: [Panoramica del sistema](./system-overview.md), [Client iOS](./ios-client.md), [Backend e dati](./backend-and-data.md), [Filtraggio DNS e liste di blocco](./dns-filtering-and-blocklists.md).

---

## 1. Flusso di autenticazione

**Provider: solo Apple e Google.** **(Implementato)** `AccountAuthProvider` enumera esattamente `.apple` e `.google` (`AccountAuthService.swift`). L'accesso con email e password — e qualsiasi recupero assistito dall'assistenza che aggiri l'autenticazione — è esplicitamente **Abbandonato**; gestire password comporterebbe obblighi di reimpostazione, MFA, blocco account e gestione delle violazioni che non valgono la complessità, dato che Apple/Google sono sufficienti, e il recupero che aggira l'autenticazione comprometterebbe la garanzia a conoscenza zero.

Entrambi i provider usano la **concessione nativa `id_token`**, non l'SDK Swift di Supabase e non l'OAuth web:

1. **Accesso nativo.** Apple tramite AuthenticationServices; Google tramite l'SDK GoogleSignIn. Ciascuno restituisce un `id_token` del provider (Google anche un access token). L'app genera un nonce grezzo con CSPRNG, lo cifra con SHA256 e passa l'hash al provider, così l'`id_token` emesso vi è vincolato. **(Implementato)**
2. **Scambio presso Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) costruisce una `URLRequest` grezza verso Supabase Auth `auth/v1/token?grant_type=id_token`, inviando `provider` + `id_token` + l'`access_token` facoltativo + il nonce **grezzo** (così Supabase può verificare il vincolo e rifiutare i replay), con l'header `apikey`. Nessun SDK; `LavaSecCore` resta privo di dipendenze di rete/autenticazione. **(Implementato)**
3. **Ricezione della sessione.** Supabase verifica il token e restituisce una sessione: un access token, un refresh token, una scadenza e un record utente (provider/providers). Il refresh usa lo stesso helper con `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orchestra tutto questo — esegue i flussi nativi, effettua lo scambio, salva e aggiorna le sessioni, espone `AccountAuthState` e guida l'eliminazione dell'account attraverso il Worker.

```
Apple / Google (native id_token + raw nonce)
        │
        ▼
SupabaseIDTokenAuth  ──POST──▶  Supabase Auth  auth/v1/token?grant_type=id_token
        │                              │
        ▼                              ▼
AccountAuthService  ◀────── session (access + refresh tokens, expiry, user)
        │
        ▼
AccountSessionKeychainStore  (Keychain, device-local)
```

---

## 2. Archiviazione della sessione e del Keychain

L'**unica** cosa salvata dall'accesso è la sessione Supabase — access token e refresh token come JSON. **Non** esiste alcuna copia lato server di chi sei oltre all'utente di Supabase Auth e alle righe di cui sei proprietario.

- **Dove:** `AccountSessionKeychainStore` (`LavaSecApp`), servizio Keychain `com.lavasec.account-session`, archiviato **per provider** (`supabase-session-apple` / `supabase-session-google`, più una migrazione per gli account legacy). **(Implementato)**
- **Accessibilità:** tutti gli archivi condividono `GenericKeychainStore` (`LavaSecCore`), fissato a `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Questo significa **locale al dispositivo, non sincronizzato con iCloud e non incluso nei backup del dispositivo**. **(Implementato)**

Lo stesso meccanismo di `GenericKeychainStore` sostiene tre archivi: la sessione dell'account, il materiale di sblocco del backup (`BackupKeychainStore`, servizio `com.lavasec.zero-knowledge-backup`) e il codice di accesso dell'app. Nessuno di essi si sincronizza tramite iCloud Keychain.

> **Punto di revisione aperto (non è un comportamento garantito):** l'attuale classe di accessibilità non ha alcun controllo biometrico/di presenza utente (nessun `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Se irrigidire il materiale di sblocco con un controllo di accesso vincolato alla presenza è tracciato come punto di revisione per il rilascio; il valore oggi rilasciato è after-first-unlock-this-device-only. **(Pianificato)**

---

## 3. Backup a conoscenza zero

### 3.1 Cos'è, con precisione

Quando attivi il backup cifrato, il **client iOS** cifra una copia ridotta delle tue *impostazioni* e carica su Supabase solo il testo cifrato più metadati non segreti. Il telefono è l'unico luogo in cui il testo in chiaro e i segreti di decifratura esistono mai.

> **Backup a conoscenza zero:** involucro AES-256-GCM lato client; la chiave casuale del payload è racchiusa in slot di chiave per ciascun fattore — PBKDF2-HMAC-SHA256 (210k iterazioni) per gli slot password/frase/dispositivo/assistito, HKDF-SHA256 per lo slot passkey PRF. Su Supabase `user_backups` (RLS per utente) vengono caricati solo testo cifrato + metadati non segreti. Il server non può decifrare senza un segreto in possesso dell'utente. Anche lo slot passkey è **a conoscenza zero**: la sua chiave di sblocco è derivata sul dispositivo dall'output del PRF WebAuthn dell'autenticatore (`hmac-secret`), e il server non conserva alcun segreto della passkey (vedi §4.3).

### 3.2 Cosa viene incluso nel backup (il payload ridotto)

`BackupConfigurationPayload` (`LavaSecCore`) è il testo in chiaro che viene sigillato. È volutamente piccolo e si converte avanti e indietro con `AppConfiguration`. **(Implementato)**

**Incluso:** gli **ID** delle liste di blocco attivate (riferimenti al catalogo, non i byte delle liste), i domini consentiti/bloccati, il preset del resolver / resolver personalizzato, le preferenze dei log locali, il registro LavaGuard, un suggerimento di protezione e i metadati delle origini delle liste di blocco personalizzate.

**Escluso:** `isPaid` (l'abilitazione è locale), i flag QA, le diagnostiche, gli snapshot dei filtri e i contenuti completi delle liste di blocco (riferiti solo tramite ID di catalogo). La tua cronologia di navigazione e le query DNS non fanno mai parte di questo payload, perché il dispositivo non le registra mai come flusso di telemetria di routine.

### 3.3 L'involucro (crittografia lato client)

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa la crittografia. **(Implementato)**

1. **Cifratura del payload.** Il payload ridotto viene sigillato una volta con **AES-256-GCM** sotto una **chiave di payload casuale di 32 byte** (generata con `SecRandomCopyBytes`).
2. **Avvolgimento della chiave (slot di chiave).** Quella singola chiave di payload viene avvolta in modo indipendente in uno o più **slot di chiave**, uno per ciascun segreto, e quindi AES-GCM avvolge una copia della chiave di payload. Il segreto di un singolo slot sblocca l'intero backup. La derivazione della chiave di avvolgimento è specifica per tipo di slot: gli slot `password` / `recoveryPhrase` / `keychain` (dispositivo) / `assistedRecovery` usano **PBKDF2-HMAC-SHA256, 210.000 iterazioni** (produzione; `defaultPasswordIterations = 210_000`) con un nuovo salt casuale di 16 byte per ciascuno slot; lo slot `passkey` usa **HKDF-SHA256** sull'output PRF dell'autenticatore (info `"LavaSec passkey backup PRF v1"`), con il salt PRF non segreto conservato nello slot così che il ripristino possa riprodurre l'output.
3. **Tipi di slot.** L'involucro supporta cinque tipi di slot: `password`, `recoveryPhrase`, `keychain` (segreto del dispositivo), `assistedRecovery` e `passkey`.

La configurazione rilasciata è **senza password** (`makePasswordless`, guidata da `AppViewModel.turnOnEncryptedBackup`). Crea uno **slot `keychain` (dispositivo) + uno slot `assistedRecovery` + uno slot `passkey` facoltativo**. Le factory `password` / `recoveryPhrase` e i metodi di decifratura esistono ancora per gli involucri legacy/retrocompatibili (esercitati solo dai test), ma l'interfaccia attiva non crea mai un involucro con sola password — considera il backup con password come non rilasciato. **(Implementato; slot password Abbandonato dal flusso attivo.)**

**Integrità / anti-downgrade:** `envelopeVersion` è fissato rigidamente a `1`, e la KDF di ogni slot è fissata per tipo — `PBKDF2-HMAC-SHA256` per gli slot password/frase/dispositivo/assistito, `HKDF-SHA256` per lo slot passkey PRF. Le versioni non supportate o le KDF non corrispondenti vengono rifiutate, così metadati falsificati o sottoposti a downgrade non possono indebolire lo sblocco. **(Implementato)**

### 3.4 Caricamento e archiviazione

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) carica l'involucro **direttamente** nella tabella PostgREST `user_backups` di Supabase, con upsert su `user_id`, delimitata dall'access token dell'utente. **Non esiste alcuna route del Worker per il caricamento dell'involucro** — il client comunica direttamente con Supabase sotto RLS; il Worker tocca `user_backups` solo per eliminarlo durante l'eliminazione dell'account. **(Implementato)**

Cosa finisce in `user_backups`:

- il **testo cifrato**, e
- **solo metadati non segreti:** il nome del cifrario, i record degli slot di chiave (salt, conteggi delle iterazioni, chiavi avvolte, etichette degli slot), il `server_recovery_share`, `createdAt` e la dimensione in byte.

La riga è protetta da **row-level security**: ogni riga è leggibile/scrivibile solo dal suo proprietario (`auth.uid() = user_id`); il ruolo anonimo non ha accesso. La dimensione è limitata a circa 256 KiB di testo cifrato / 32 KiB di metadati a livello di database (`20260518000000_zero_knowledge_backups.sql`, irrigidito in `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementato)**

### 3.5 La garanzia — cosa il server può e non può vedere

**Il server archivia:** testo cifrato, salt/iterazioni delle KDF, slot di chiave avvolti, il `server_recovery_share` e alcuni campi non segreti (cifrario, dimensione, marca temporale).

**Il server non riceve né archivia mai:** le impostazioni/i domini/le preferenze DNS in chiaro, la frase di recupero, alcuna password di backup o la chiave di payload non avvolta.

**Pertanto:** Supabase **non può decifrare un backup** senza un segreto in possesso dell'utente. Tutti e tre i percorsi di ripristino — lo slot della chiave del dispositivo, la frase di recupero (combinata con la share del server, §4.2) e lo slot passkey (l'output PRF dell'autenticatore, §4.3) — decifrano **sul dispositivo**, e il server non conserva alcun segreto di decifratura per nessuno di essi. Ciò è asserito nei commenti della migrazione e nel piano di privacy, ed è testato (i test sull'involucro confermano che nessun dominio/URL in chiaro trapela nella struttura caricata).

**Avvertenza precisa sul modello di minaccia — non esagerare le affermazioni.** Per lo slot di **recupero assistito**, il server conserva *sia* il `server_recovery_share` *sia* lo slot avvolto `assistedRecovery` in `user_backups`. L'unica cosa che gli manca è la frase di recupero dell'utente, che Lava non riceve mai. Quindi, se il server fosse completamente compromesso, l'entropia della frase di recupero (~105 bit, vedi §4.1) più il costo del PBKDF2 a 210k iterazioni sarebbe l'**unica** barriera contro un attacco a forza bruta offline di quello slot. Questo è intenzionale (il recupero assistito è a due fattori per progettazione — nessuna delle due metà decifra da sola), ma significa che l'entropia della frase di recupero è portante, non decorativa. Il segreto dello slot `keychain` (dispositivo) non lascia mai il dispositivo, quindi non è affatto esposto a una compromissione del server.

---

## 4. Recupero

Un backup è utile solo se puoi ripristinarlo. `restoreEncryptedBackup` (in `AppViewModel`) decifra provando gli slot disponibili: chiave del dispositivo, frase di recupero o passkey. In ogni modalità l'involucro viene caricato localmente (o recuperato da Supabase) e poi **decifrato sul dispositivo** — il server non decifra mai.

### 4.1 Frase di recupero

`BackupRecoveryPhrase` (`LavaSecCore`) genera una **frase CVCV di 8 parole** (consonante-vocale-consonante-vocale) da `SecRandom` con campionamento per rifiuto (~13,2 bit/token → **~105 bit in totale**), normalizzata in minuscolo. **(Implementato)** Il ripristino tollera la formattazione dell'utente (spaziatura/maiuscole) tramite analisi/normalizzazione prima che lo slot venga provato.

Questo è il fattore di recupero **fuori dal dispositivo** dell'utente — salvato dall'utente, mai caricato. Secondo il rafforzamento della privacy (§5), copiare la frase è **facoltativo** e, quando usato, passa attraverso un appunti locale / a scadenza (10 minuti) anziché forzare l'esposizione negli appunti globali.

### 4.2 Recupero assistito (la combinazione a due fattori)

La sola frase di recupero **non** sblocca lo slot `assistedRecovery`. Il segreto dello slot è derivato da **entrambe** le metà:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

I tre segmenti sono uniti da un **separatore byte NUL (`0x00`)** nell'input UTF-8 effettivo — cioè la stringa sottoposta ad hash è `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — quindi il `‖` qui sopra indica una concatenazione delimitata da NUL, non una semplice concatenazione. `serverRecoveryShare` è un valore casuale archiviato nei metadati dell'involucro lato server; `normalizedPhrase` è la frase di recupero dell'utente. **Nessuna delle due metà decifra da sola** — il ripristino richiede la share del server (recuperata con il backup) *e* la frase in possesso dell'utente. **(Implementato)**

### 4.3 Recupero con passkey — a conoscenza zero, derivato dal PRF

Lo slot `passkey` facoltativo aggiunge un fattore basato su hardware, ed è **a conoscenza zero**: la sua chiave di sblocco è derivata **sul dispositivo** dall'output del PRF WebAuthn dell'autenticatore (`hmac-secret`). Il server non registra alcuna passkey, non emette alcuna sfida WebAuthn e non archivia alcun segreto di recupero — non esiste alcun passaggio di rilascio lato server.

- **Registrazione/asserzione:** `BackupPasskeyCoordinator` (`LavaSecApp`) esegue WebAuthn tramite `ASAuthorizationPlatformPublicKeyCredentialProvider`, parte affidataria **`lavasecurity.app`**, richiedendo l'estensione PRF su un salt per credenziale e richiedendo la verifica dell'utente.
- **Derivazione della chiave (a conoscenza zero):** l'autenticatore restituisce un output PRF che **non lascia mai il dispositivo**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva con HKDF-SHA256 la chiave di avvolgimento dello slot da quell'output PRF (info `"LavaSec passkey backup PRF v1"`) e AES-GCM avvolge la chiave di payload; solo il salt PRF non segreto e l'ID della credenziale sono conservati nello slot. Al ripristino, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` riasserisce la credenziale per riprodurre lo stesso output PRF, e `decryptWithPasskeyPRFOutput` sblocca lo slot localmente. Il server **non** conserva alcun segreto della passkey, quindi nessun percorso con ruolo di servizio può recuperare un backup protetto da passkey.

Il precedente progetto di escrow (una tabella `backup_passkey_recovery` con ruolo di servizio che conservava un `recovery_secret` lato server, più una tabella `backup_passkey_challenges` ed endpoint Worker `/v1/backup/passkeys/*`) è stato **Abbandonato**: le tabelle sono state rimosse in una migrazione del backend, il Worker non porta alcuna route per le passkey, e `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` asserisce in modo affermativo che `BackupPasskeyRecoveryService` e qualsiasi percorso di escrow lato server siano assenti. **(Implementato)**

> **Avvertenza sulla prontezza per la produzione:** trattare le passkey salvate come fattore recuperabile pienamente pronto per la produzione su dispositivi fisici dipende ancora dall'associazione webcredentials per `lavasecurity.app`. La metà iOS è dichiarata — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` porta `webcredentials:lavasecurity.app` — e la metà server (il file `apple-app-site-association` e gli header) è ora ospitata nel sito marketing. Finché quell'associazione non si risolve su un determinato dispositivo, il percorso dell'associazione webcredentials può fallire e fa emergere `BackupPasskeyError.webCredentialsAssociationUnavailable`. Il fattore passkey in sé è implementato; la sua prontezza end-to-end su hardware reale è **Pianificata**.

---

## 5. Minimizzazione dei dati e impostazione della privacy

- **Account facoltativo.** La protezione funziona senza alcun account; l'accesso abilita solo il backup delle impostazioni.
- **Testo in chiaro solo locale.** Il telefono è l'unico luogo in cui esistono le impostazioni in chiaro e i segreti di decifratura; Supabase conserva un involucro non leggibile per utente.
- **Payload ridotto.** Solo le impostazioni in §3.2 vengono incluse nel backup; `isPaid`, i flag QA, le diagnostiche, gli snapshot e i byte completi delle liste di blocco sono esclusi. Le liste di blocco sono riferite tramite ID di catalogo, mai incorporate.
- **Nessuna telemetria di navigazione/DNS.** Non esiste alcuna tabella lato server per le query DNS di routine o la telemetria per dominio; il filtraggio resta sul dispositivo.
- **Il materiale di sblocco è locale al dispositivo.** Il materiale di sblocco del backup è archiviato con accessibilità `…ThisDeviceOnly` e **non** è sincronizzato con iCloud. Questo ha **invertito** il progetto originale del piano basato su un Keychain sincronizzabile, così Lava non sincronizza silenziosamente il materiale di sblocco tramite iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementato; inverte il piano precedente.)**

### Eliminazione dell'account

L'eliminazione è **Implementata** e passa attraverso un endpoint Worker autenticato, non eliminazioni dirette dal client. `AccountAuthService.deleteAccount` invia l'access token dell'utente a `POST /v1/account/delete`; il Worker `lavasec-api` (ruolo di servizio) elimina le righe `bug_reports` dell'utente (e i loro allegati R2), `user_backups`, `entitlements`, `user_settings` e `profiles`, quindi elimina l'utente di Supabase Auth tramite l'API di amministrazione, restituendo solo uno stato di eliminazione + i provider collegati. L'app poi disconnette localmente e cancella il materiale di sblocco del backup (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Nota: il frontmatter YAML del piano di eliminazione riporta già `status: Done` ed esso risiede in `plans/implemented/`. Un'annotazione **interna al corpo** ormai obsoleta riporta `Status: Backlog.`, ma secondo la regola della cartella di corsia (la cartella fa fede) e la presenza nel codice (esistono sia l'app sia il Worker), la funzionalità è **Implementata**; la riga interna al corpo è un errore del documento, non del frontmatter.

---

## 6. Riepilogo dello stato

| Area | Dettaglio | Stato |
|---|---|---|
| Accesso `id_token` Apple / Google tramite Supabase | Flussi nativi, nonce con hash, scambio con URLRequest grezza | Implementato |
| Accesso con email/password | Gestione delle password rifiutata | Abbandonato |
| Sessione nel Keychain (locale al dispositivo, per provider) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementato |
| Involucro AES-256-GCM + slot di chiave PBKDF2-HMAC-SHA256 (210k) | Lato client; solo testo cifrato + metadati non segreti su `user_backups` (RLS) | Implementato |
| Configurazione senza password (slot dispositivo + recupero assistito + passkey facoltativo) | `makePasswordless` | Implementato |
| Slot di chiave password nel flusso attivo | Sopravvive in `LavaSecCore` solo per i test | Abbandonato |
| Frase di recupero (CVCV di 8 parole, ~105 bit) | Fattore fuori dal dispositivo | Implementato |
| Recupero assistito (share del server + frase tramite SHA256, delimitato da NUL) | Due fattori; nessuna metà da sola | Implementato |
| Recupero con passkey (a conoscenza zero, PRF WebAuthn/`hmac-secret`, RP `lavasecurity.app`) | Slot derivato con HKDF dall'output PRF, nessun segreto sul server | Implementato |
| Passkey come fattore pronto per la produzione su hardware | Necessita l'associazione webcredentials (AASA ospitato nel sito marketing) | Pianificato |
| Eliminazione dell'account (Worker autenticato, ruolo di servizio) | Rimuove backup/impostazioni/abilitazioni/profilo/allegati + utente Auth | Implementato |
| Controllo biometrico/di presenza utente sul materiale di sblocco | Punto di revisione per il rilascio | Pianificato |
| Estrazione di `EncryptedBackupCoordinator` da `AppViewModel` | Solo modularizzazione; nessun cambiamento al modello di sicurezza | In corso |

---

## Correlati

- [Panoramica del sistema](./system-overview.md) — l'intero sistema su un'unica schermata, inclusi i confini di fiducia.
- [Client iOS](./ios-client.md) — `AppViewModel` e i target dell'app che guidano il backup.
- [Backend e dati](./backend-and-data.md) — il Worker `lavasec-api`, la RLS di Supabase e l'archiviazione `user_backups`.
- [Filtraggio DNS e liste di blocco](./dns-filtering-and-blocklists.md) — i preset del resolver e i trasporti le cui impostazioni sono contenute nel payload del backup.
