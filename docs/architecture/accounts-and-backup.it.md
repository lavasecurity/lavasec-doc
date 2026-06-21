---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Account e backup a conoscenza zero

> **Destinatari:** sviluppatori.
> **Autorità:** quando questo documento e un piano sono in disaccordo, **vince il codice** — le divergenze sono segnalate direttamente nel testo. Lo stato riflette la realtà confermata dal codice, non le aspirazioni del piano. Legenda degli stati: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente integrato), **Pianificato** (progettato, non realizzato), **Abbandonato** (respinto o annullato).

Gli account sono **opzionali**. La protezione di base è gratuita per sempre e non richiede alcun account; l'accesso esiste solo per fare il backup delle tue *impostazioni*, in forma crittografata, così da poterle ripristinare su un nuovo dispositivo. Questo documento descrive il flusso di autenticazione, dove risiede la sessione, l'involucro del backup a conoscenza zero, i percorsi di recupero e che cosa esattamente il server può e non può vedere.

La promessa di privacy fondamentale a cui questo documento si attiene:

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva solo i metadati del catalogo, un backup crittografato e opaco per ogni utente e le diagnostiche anonimizzate che scegli di inviare.

Suddivisione dei componenti: la crittografia pura e la costruzione delle richieste vivono in `LavaSecCore`; l'orchestrazione e la UI vivono in `LavaSecApp`. Documenti correlati: [Panoramica del sistema](./system-overview.md), [Client iOS](./ios-client.md), [Backend e dati](./backend-and-data.md), [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md).

---

## 1. Flusso di autenticazione {#1-authentication-flow}

**Provider: solo Apple e Google.** **(Implementato)** `AccountAuthProvider` enumera esattamente `.apple` e `.google` (`AccountAuthService.swift`). Email/password — e qualsiasi recupero assistito dal supporto che aggiri l'autenticazione — sono esplicitamente **Abbandonati**; gestire le password aggiungerebbe obblighi di reset/MFA/blocco/violazione che non valgono la complessità, dato che Apple/Google sono sufficienti, e il recupero tramite aggiramento romperebbe la garanzia di conoscenza zero.

Entrambi i provider usano il **grant nativo `id_token`**, non l'SDK Swift di Supabase né l'OAuth web:

1. **Accedi in modo nativo.** Apple tramite AuthenticationServices; Google tramite l'SDK GoogleSignIn. Ciascuno produce un `id_token` del provider (Google anche un access token). L'app genera un nonce raw CSPRNG, lo sottopone ad hash con SHA256 e passa l'hash al provider, così che l'`id_token` emesso sia legato ad esso. **(Implementato)**
2. **Scambio presso Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) costruisce una `URLRequest` raw verso Supabase Auth `auth/v1/token?grant_type=id_token`, inviando in POST `provider` + `id_token` + l'eventuale `access_token` + il nonce **raw** (così che Supabase possa verificare il legame e rifiutare i replay), con l'header `apikey`. Nessun SDK; `LavaSecCore` resta privo di dipendenze di rete/auth. **(Implementato)**
3. **Ricevi una sessione.** Supabase verifica il token e restituisce una sessione: un access token, un refresh token, una scadenza e un record utente (provider/providers). Il refresh usa lo stesso helper con `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orchestra tutto questo — esegue i flussi nativi, effettua lo scambio, persiste e aggiorna le sessioni, espone `AccountAuthState` e gestisce l'eliminazione dell'account tramite il Worker.

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

## 2. Archiviazione di sessione e Keychain {#2-session--keychain-storage}

L'**unica** cosa persistita dall'accesso è la sessione Supabase — access e refresh token in formato JSON. **Non** esiste alcun mirror lato server della tua identità oltre all'utente Supabase Auth e alle righe di cui sei proprietario.

- **Dove:** `AccountSessionKeychainStore` (`LavaSecApp`), servizio Keychain `com.lavasec.account-session`, archiviato **per provider** (`supabase-session-apple` / `supabase-session-google`, più una migrazione per gli account legacy). **(Implementato)**
- **Accessibilità:** tutti gli store condividono `GenericKeychainStore` (`LavaSecCore`), fissato su `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Ciò significa **locale al dispositivo, non sincronizzato su iCloud e non incluso nei backup del dispositivo**. **(Implementato)**

Lo stesso meccanismo `GenericKeychainStore` sta alla base di tre store: la sessione dell'account, il materiale di sblocco del backup (`BackupKeychainStore`, servizio `com.lavasec.zero-knowledge-backup`) e il passcode dell'app. Nessuno di essi si sincronizza tramite iCloud Keychain.

> **Punto di revisione aperto (non un comportamento dichiarato):** l'attuale classe di accessibilità non ha alcun gate biometrico/di presenza utente (nessun `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). La decisione se irrigidire il materiale di sblocco con un controllo d'accesso condizionato dalla presenza è tracciata come punto di revisione legato al rilascio; il valore rilasciato oggi è after-first-unlock-this-device-only. **(Pianificato)**

---

## 3. Backup a conoscenza zero {#3-zero-knowledge-backup}

### 3.1 Che cos'è, con precisione {#31-what-it-is-precisely}

Quando attivi il backup crittografato, il **client iOS** cripta una copia ridotta al minimo delle tue *impostazioni* e carica su Supabase solo il testo cifrato più i metadati non segreti. Il telefono è l'unico luogo in cui il testo in chiaro e i segreti di decifratura esistono.

> **Backup a conoscenza zero:** involucro AES-256-GCM lato client; la chiave casuale del payload è racchiusa in slot di chiave per ciascun fattore — PBKDF2-HMAC-SHA256 (210k iter) per gli slot password/frase/dispositivo/assistito, HKDF-SHA256 per lo slot passkey PRF. Su Supabase `user_backups` (RLS per utente) vengono caricati solo il testo cifrato + i metadati non segreti. Il server non può decifrare senza un segreto in possesso dell'utente. Anche lo slot passkey è **a conoscenza zero**: la sua chiave di apertura è derivata sul dispositivo dall'output WebAuthn PRF (`hmac-secret`) dell'authenticator, e il server non detiene alcun segreto della passkey (vedi §4.3).

### 3.2 Cosa viene incluso nel backup (il payload minimizzato) {#32-what-gets-backed-up-the-minimized-payload}

`BackupConfigurationPayload` (`LavaSecCore`) è il testo in chiaro che viene sigillato. È volutamente piccolo e converte avanti e indietro con `AppConfiguration`. **(Implementato)**

**Incluso:** gli **ID** delle blocklist abilitate (riferimenti al catalogo, non i byte delle liste), i domini consentiti/bloccati, il preset del resolver / resolver personalizzato, le preferenze sui log locali, il registro LavaGuard, un suggerimento di protezione e i metadati delle sorgenti di blocklist personalizzate.

**Escluso:** `isPaid` (l'abilitazione è locale), i flag QA, le diagnostiche, gli snapshot dei filtri e il contenuto completo delle blocklist (referenziato solo tramite ID di catalogo). La cronologia di navigazione e le query DNS non fanno mai parte di questo payload, perché il dispositivo non le registra come flusso di telemetria di routine.

### 3.3 L'involucro (crittografia lato client) {#33-the-envelope-client-side-crypto}

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa la crittografia. **(Implementato)**

1. **Cifratura del payload.** Il payload minimizzato viene sigillato una volta con **AES-256-GCM** sotto una **chiave del payload casuale di 32 byte** (generata con `SecRandomCopyBytes`).
2. **Avvolgimento delle chiavi (slot di chiave).** Quell'unica chiave del payload viene avvolta in modo indipendente in uno o più **slot di chiave**, uno per ciascun segreto, e poi avvolge tramite AES-GCM una copia della chiave del payload. Il segreto di un qualsiasi singolo slot sblocca l'intero backup. La derivazione della chiave di avvolgimento dipende dal tipo di slot: gli slot `password` / `recoveryPhrase` / `keychain` (dispositivo) / `assistedRecovery` usano **PBKDF2-HMAC-SHA256, 210.000 iterazioni** (produzione; `defaultPasswordIterations = 210_000`) con un nuovo salt casuale di 16 byte per ogni slot; lo slot `passkey` usa **HKDF-SHA256** sull'output PRF dell'authenticator (info `"LavaSec passkey backup PRF v1"`), con il salt PRF non segreto persistito nello slot affinché il ripristino possa riprodurre l'output.
3. **Tipi di slot.** L'involucro supporta cinque tipi di slot: `password`, `recoveryPhrase`, `keychain` (segreto del dispositivo), `assistedRecovery` e `passkey`.

La configurazione rilasciata è **senza password** (`makePasswordless`, gestita da `AppViewModel.turnOnEncryptedBackup`). Crea uno **slot `keychain` (dispositivo) + uno slot `assistedRecovery` + un eventuale slot `passkey`**. Le factory `password` / `recoveryPhrase` e i metodi di decifratura esistono ancora per gli involucri legacy/retrocompatibili (esercitati solo dai test) ma la UI attiva non crea mai un involucro basato solo su password — considera il backup con password come non rilasciato. **(Implementato; slot password Abbandonato dal flusso attivo.)**

**Integrità / anti-downgrade:** `envelopeVersion` è fissato in modo rigido a `1`, e la KDF di ciascuno slot è fissata per tipo — `PBKDF2-HMAC-SHA256` per gli slot password/frase/dispositivo/assistito, `HKDF-SHA256` per lo slot passkey PRF. Le versioni non supportate o le KDF non corrispondenti vengono rifiutate, così che metadati falsificati o sottoposti a downgrade non possano indebolire l'apertura. **(Implementato)**

### 3.4 Caricamento e archiviazione {#34-upload--storage}

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) carica l'involucro **direttamente** sulla tabella PostgREST di Supabase `user_backups`, con upsert su `user_id`, nell'ambito dell'access token dell'utente. **Non esiste alcuna route del Worker per il caricamento dell'involucro** — il client parla direttamente con Supabase sotto RLS; il Worker tocca `user_backups` solo per eliminarlo durante la cancellazione dell'account. **(Implementato)**

Cosa finisce in `user_backups`:

- il **testo cifrato**, e
- **solo metadati non segreti:** il nome del cifrario, i record degli slot di chiave (salt, conteggi di iterazioni, chiavi avvolte, etichette degli slot), il `server_recovery_share`, `createdAt` e la dimensione in byte.

La riga è protetta da **row-level security**: ogni riga è leggibile/scrivibile solo dal suo proprietario (`auth.uid() = user_id`); il ruolo anonimo non ha accesso. La dimensione è limitata a ~256 KiB di testo cifrato / 32 KiB di metadati a livello di DB (`20260518000000_zero_knowledge_backups.sql`, irrigidito in `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementato)**

### 3.5 La garanzia — cosa il server può e non può vedere {#35-the-guarantee--what-the-server-can-and-cannot-see}

**Il server memorizza:** il testo cifrato, i salt/le iterazioni della KDF, gli slot di chiave avvolti, il `server_recovery_share` e alcuni campi non segreti (cifrario, dimensione, timestamp).

**Il server non riceve né memorizza mai:** le impostazioni/i domini/le preferenze DNS in chiaro, la frase di recupero, alcuna password di backup, né la chiave del payload non avvolta.

**Pertanto:** Supabase **non può decifrare un backup** senza un segreto in possesso dell'utente. Tutti e tre i percorsi di ripristino — lo slot della chiave del dispositivo, la frase di recupero (combinata con la quota del server, §4.2) e lo slot passkey (l'output PRF dell'authenticator, §4.3) — decifrano **sul dispositivo**, e il server non detiene alcun segreto di decifratura per nessuno di essi. Ciò è affermato nei commenti delle migrazioni e nel piano sulla privacy, ed è testato (i test sull'involucro confermano che nessun dominio/URL in chiaro trapeli nella forma caricata).

**Avvertenza precisa sul modello di minaccia — non sovrastimare.** Per lo slot di **recupero assistito**, il server detiene *sia* il `server_recovery_share` *sia* lo slot `assistedRecovery` avvolto in `user_backups`. L'unica cosa che gli manca è la frase di recupero dell'utente, che Lava non riceve mai. Quindi, se il server fosse interamente compromesso, l'entropia della frase di recupero (~105 bit, vedi §4.1) più il costo del PBKDF2 a 210k iterazioni sarebbe l'**unica** barriera contro un attacco a forza bruta offline su quello slot. Questo è intenzionale (il recupero assistito è a due fattori per progettazione — nessuna delle due metà da sola decifra), ma significa che l'entropia della frase di recupero è portante, non decorativa. Il segreto dello slot `keychain` (dispositivo) non lascia mai il dispositivo, quindi non è affatto esposto a una compromissione del server.

---

## 4. Recupero {#4-recovery}

Un backup è utile solo se puoi ripristinarlo. `restoreEncryptedBackup` (in `AppViewModel`) decifra provando gli slot disponibili: chiave del dispositivo, frase di recupero o passkey. In ogni modalità l'involucro viene caricato localmente (o recuperato da Supabase) e poi **decifrato sul dispositivo** — il server non decifra mai.

### 4.1 Frase di recupero {#41-recovery-phrase}

`BackupRecoveryPhrase` (`LavaSecCore`) genera una **frase CVCV di 8 parole** (consonante-vocale-consonante-vocale) da `SecRandom` con rejection sampling (~13,2 bit/token → **~105 bit in totale**), normalizzata in minuscolo. **(Implementato)** Il ripristino tollera la formattazione dell'utente (spaziatura/maiuscole) tramite parsing/normalizzazione prima di provare lo slot.

Questo è il fattore di recupero **fuori dal dispositivo** dell'utente — salvato dall'utente, mai caricato. In base all'irrobustimento della privacy (§5), copiare la frase è **opzionale** e, quando usato, passa attraverso un pasteboard solo locale / a scadenza (10 minuti) anziché forzare l'esposizione al pasteboard globale.

### 4.2 Recupero assistito (la combinazione a due fattori) {#42-assisted-recovery-the-two-factor-combination}

La sola frase di recupero **non** sblocca lo slot `assistedRecovery`. Il segreto dello slot è derivato da **entrambe** le metà:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

I tre segmenti sono uniti da un **separatore byte NUL (`0x00`)** nell'effettivo input UTF-8 — cioè la stringa sottoposta ad hash è `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — quindi il simbolo `‖` qui sopra indica una concatenazione delimitata da NUL, non una concatenazione semplice. `serverRecoveryShare` è un valore casuale archiviato nei metadati dell'involucro lato server; `normalizedPhrase` è la frase di recupero dell'utente. **Nessuna delle due metà da sola decifra** — il ripristino richiede la quota del server (recuperata con il backup) *e* la frase in possesso dell'utente. **(Implementato)**

### 4.3 Recupero tramite passkey — a conoscenza zero, derivato da PRF {#43-passkey-recovery--zero-knowledge-prf-derived}

Lo slot opzionale `passkey` aggiunge un fattore supportato dall'hardware, ed è **a conoscenza zero**: la sua chiave di apertura è derivata **sul dispositivo** dall'output WebAuthn PRF (`hmac-secret`) dell'authenticator. Il server non registra alcuna passkey, non emette alcuna challenge WebAuthn e non memorizza alcun segreto di recupero — non esiste alcun passaggio di rilascio lato server.

- **Registrazione/asserzione:** `BackupPasskeyCoordinator` (`LavaSecApp`) esegue WebAuthn tramite `ASAuthorizationPlatformPublicKeyCredentialProvider`, con relying party **`lavasecurity.app`**, richiedendo l'estensione PRF su un salt per-credenziale e imponendo la verifica dell'utente.
- **Derivazione della chiave (a conoscenza zero):** l'authenticator restituisce un output PRF che **non lascia mai il dispositivo**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva tramite HKDF-SHA256 la chiave di avvolgimento dello slot da quell'output PRF (info `"LavaSec passkey backup PRF v1"`) e avvolge la chiave del payload tramite AES-GCM; nello slot vengono persistiti solo il salt PRF non segreto e l'ID della credenziale. Al ripristino, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` riasserisce la credenziale per riprodurre lo stesso output PRF, e `decryptWithPasskeyPRFOutput` apre lo slot localmente. Il server **non** detiene alcun segreto della passkey, quindi nessun percorso con service-role può recuperare un backup protetto da passkey.

Il precedente design di escrow (una tabella `backup_passkey_recovery` con service-role contenente un `recovery_secret` lato server, più una tabella `backup_passkey_challenges` ed endpoint Worker `/v1/backup/passkeys/*`) è stato **Abbandonato**: le tabelle sono state rimosse in una migrazione del backend, il Worker non porta alcuna route per le passkey, e `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` afferma esplicitamente che `BackupPasskeyRecoveryService` e qualsiasi percorso di escrow lato server sono assenti. **(Implementato)**

> **Avvertenza sulla prontezza per la produzione:** considerare le passkey salvate come un fattore recuperabile pienamente pronto per la produzione su dispositivi fisici dipende ancora dall'associazione webcredentials per `lavasecurity.app`. La metà iOS è dichiarata — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` porta `webcredentials:lavasecurity.app` — e la metà server (il file `apple-app-site-association` e gli header) è ora ospitata nel sito di marketing. Finché quell'associazione non si risolve su un dato dispositivo, il percorso dell'associazione webcredentials può fallire e produce `BackupPasskeyError.webCredentialsAssociationUnavailable`. Il fattore passkey in sé è implementato; la sua prontezza end-to-end su hardware reale è **Pianificata**.

---

## 5. Minimizzazione dei dati e postura sulla privacy {#5-data-minimization--privacy-posture}

- **Account opzionale.** La protezione funziona senza alcun account; l'accesso abilita solo il backup delle impostazioni.
- **Solo testo in chiaro locale.** Il telefono è l'unico luogo in cui esistono le impostazioni in chiaro e i segreti di decifratura; Supabase detiene un involucro opaco per utente.
- **Payload minimizzato.** Vengono incluse nel backup solo le impostazioni in §3.2; `isPaid`, i flag QA, le diagnostiche, gli snapshot e i byte completi delle blocklist sono esclusi. Le blocklist sono referenziate tramite ID di catalogo, mai incorporate.
- **Nessuna telemetria di navigazione/DNS.** Non esiste alcuna tabella lato server per le query DNS di routine o la telemetria per dominio; il filtraggio resta sul dispositivo.
- **Il materiale di sblocco è locale al dispositivo.** Il materiale di sblocco del backup è archiviato con accessibilità `…ThisDeviceOnly` e **non** è sincronizzato su iCloud. Questo ha **invertito** il design del Keychain sincronizzabile del piano originale, così che Lava non sincronizzi silenziosamente il materiale di sblocco tramite iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementato; inverte un piano precedente.)**

### Eliminazione dell'account {#account-deletion}

L'eliminazione è **Implementata** e passa attraverso un endpoint Worker autenticato, non tramite cancellazioni dirette del client. `AccountAuthService.deleteAccount` invia l'access token dell'utente a `POST /v1/account/delete`; il Worker `lavasec-api` (service role) elimina le righe `bug_reports` dell'utente (e i loro allegati R2), `user_backups`, `entitlements`, `user_settings` e `profiles`, poi elimina l'utente Supabase Auth tramite l'API admin, restituendo solo uno stato di eliminazione + i provider collegati. L'app quindi effettua il logout localmente e cancella il materiale di sblocco del backup (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Nota: il frontmatter YAML del piano di eliminazione riporta già `status: Done` e il piano vive in `plans/implemented/`. Un'annotazione **nel corpo** ormai obsoleta riporta `Status: Backlog.`, ma in base alla regola della cartella di lane (la cartella fa fede) e alla presenza nel codice (esistono sia l'app sia il Worker), la funzione è **Implementata**; la riga nel corpo è un bug della documentazione, non del frontmatter.

---

## 6. Riepilogo dello stato {#6-status-summary}

| Area | Dettaglio | Stato |
|---|---|---|
| Accesso `id_token` Apple / Google tramite Supabase | Flussi nativi, nonce sottoposto ad hash, scambio con URLRequest raw | Implementato |
| Accesso email/password | Gestione delle password respinta | Abbandonato |
| Sessione nel Keychain (locale al dispositivo, per provider) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementato |
| Involucro AES-256-GCM + slot di chiave PBKDF2-HMAC-SHA256 (210k) | Lato client; solo testo cifrato + metadati non segreti su `user_backups` (RLS) | Implementato |
| Configurazione senza password (slot dispositivo + recupero assistito + passkey opzionale) | `makePasswordless` | Implementato |
| Slot di chiave password nel flusso attivo | Sopravvive in `LavaSecCore` solo per i test | Abbandonato |
| Frase di recupero (CVCV di 8 parole, ~105 bit) | Fattore fuori dal dispositivo | Implementato |
| Recupero assistito (quota del server + frase tramite SHA256, delimitato da NUL) | A due fattori; nessuna metà da sola | Implementato |
| Recupero tramite passkey (a conoscenza zero, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | Slot derivato dall'output PRF con HKDF, nessun segreto lato server | Implementato |
| Passkey come fattore pronto per la produzione su hardware | Richiede l'associazione webcredentials (AASA ospitato nel sito di marketing) | Pianificato |
| Eliminazione dell'account (Worker autenticato, service role) | Rimuove backup/impostazioni/abilitazioni/profilo/allegati + utente Auth | Implementato |
| Gate biometrico/di presenza utente sul materiale di sblocco | Punto di revisione legato al rilascio | Pianificato |
| Estrazione di `EncryptedBackupCoordinator` da `AppViewModel` | Solo modularizzazione; nessuna modifica al modello di sicurezza | In corso |

---

## Correlati {#related}

- [Panoramica del sistema](./system-overview.md) — l'intero sistema in una schermata, inclusi i confini di fiducia.
- [Client iOS](./ios-client.md) — `AppViewModel` e i target dell'app che gestiscono il backup.
- [Backend e dati](./backend-and-data.md) — il Worker `lavasec-api`, l'RLS di Supabase e l'archiviazione di `user_backups`.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — i preset del resolver e i trasporti le cui impostazioni sono incluse nel payload del backup.
