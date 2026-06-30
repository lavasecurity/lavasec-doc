---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Account e backup zero-knowledge

> **Destinatari:** ingegneri.
> **Autorità:** dove questo documento e un piano sono in disaccordo, **vince il codice** — le divergenze sono segnalate inline. Lo stato riflette la realtà confermata dal codice, non le aspirazioni del piano. Legenda degli stati: **Implementato** (rilasciato e confermato nel codice), **In corso** (parzialmente integrato), **Pianificato** (progettato, non costruito), **Abbandonato** (rifiutato o annullato).

Gli account sono **opzionali**. La protezione di base è gratuita per sempre e non richiede alcun account; l'accesso esiste solo per eseguire il backup delle tue *impostazioni*, cifrate, così da poterle ripristinare su un nuovo dispositivo. Questo documento copre il flusso di autenticazione, dove risiede la sessione, l'envelope del backup zero-knowledge, i percorsi di ripristino ed esattamente ciò che il server può e non può vedere.

La promessa di privacy canonica che questo documento serve:

> Tutto il filtraggio DNS avviene sul dispositivo; Lava non instrada mai la tua navigazione attraverso i suoi server e non riceve mai il flusso dei domini che visiti — il backend conserva solo i metadati del catalogo, un backup cifrato opaco per utente e diagnostica anonimizzata che scegli di inviare.

Suddivisione dei componenti: la crittografia pura + la costruzione delle richieste risiedono in `LavaSecCore`; l'orchestrazione + l'interfaccia utente risiedono in `LavaSecApp`. Pagine correlate: [Panoramica del sistema](./system-overview.md), [Client iOS](./ios-client.md), [Backend e dati](./backend-and-data.md), [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md).

---

## 1. Flusso di autenticazione

**Provider: solo Apple e Google.** **(Implementato)** `AccountAuthProvider` enumera esattamente `.apple` e `.google` (`AccountAuthService.swift`). Email/password — e qualsiasi ripristino assistito dal supporto che aggira l'autenticazione — è esplicitamente **Abbandonato**; possedere le password aggiungerebbe obblighi di reset/MFA/lockout/violazione mentre Apple/Google sono sufficienti, e il ripristino tramite bypass infrangerebbe la garanzia zero-knowledge.

Entrambi i provider usano il **grant `id_token` nativo**, non l'SDK Supabase Swift e non l'OAuth web:

1. **Accesso nativo.** Apple tramite AuthenticationServices; Google tramite l'SDK GoogleSignIn. Ciascuno produce un `id_token` del provider (Google anche un access token). L'app genera un nonce grezzo CSPRNG, ne calcola l'hash SHA256 e passa l'hash al provider così che l'`id_token` emesso vi sia legato. **(Implementato)**
2. **Scambio presso Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) costruisce una `URLRequest` grezza verso Supabase Auth `auth/v1/token?grant_type=id_token`, inviando `provider` + `id_token` + `access_token` opzionale + il nonce **grezzo** (così che Supabase possa verificare il binding e rifiutare i replay), con l'header `apikey`. Nessun SDK; `LavaSecCore` resta privo di dipendenze di rete/autenticazione. **(Implementato)**
3. **Ricezione di una sessione.** Supabase verifica il token e restituisce una sessione: un access token, un refresh token, una scadenza e un record utente (provider/providers). Il refresh usa lo stesso helper con `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orchestra tutto questo — esegue i flussi nativi, effettua lo scambio, persiste e aggiorna le sessioni, espone `AccountAuthState` e guida l'eliminazione dell'account attraverso il Worker.

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

L'**unica** cosa persistita dall'accesso è la sessione Supabase — access token e refresh token come JSON. **Non** esiste alcun mirror lato server di chi sei oltre all'utente di Supabase Auth e alle righe di cui sei proprietario.

- **Dove:** `AccountSessionKeychainStore` (`LavaSecApp`), servizio Keychain `com.lavasec.account-session`, memorizzato **per provider** (`supabase-session-apple` / `supabase-session-google`, più una migrazione di account legacy). **(Implementato)**
- **Accessibilità:** tutti gli store condividono `GenericKeychainStore` (`LavaSecCore`), fissato a `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Ciò significa **locale al dispositivo, non sincronizzato con iCloud e non incluso nei backup del dispositivo**. **(Implementato)**

Gli stessi meccanismi di `GenericKeychainStore` supportano tre store: la sessione dell'account, il materiale di sblocco del backup (`BackupKeychainStore`, servizio `com.lavasec.zero-knowledge-backup`) e il passcode dell'app. Nessuno di essi si sincronizza tramite iCloud Keychain.

> **Elemento di revisione aperto (non un comportamento dichiarato):** la classe di accessibilità attuale non ha alcun gate biometrico/di presenza utente (nessun `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Se inasprire il materiale di sblocco verso un controllo di accesso con gate di presenza è tracciato come elemento di revisione di release-gate; il valore rilasciato oggi è after-first-unlock-this-device-only. **(Pianificato)**

---

## 3. Backup zero-knowledge

### 3.1 Cos'è, con precisione

Quando attivi il backup cifrato, il **client iOS** cifra una copia minimizzata delle tue *impostazioni* e carica solo il testo cifrato più metadati non segreti su Supabase. Il telefono è l'unico luogo in cui esistono il testo in chiaro e i segreti di decifratura.

> **Backup zero-knowledge:** envelope AES-256-GCM lato client; la chiave di payload casuale è avvolta in key slot, uno per segreto — PBKDF2-HMAC-SHA256 (210k iter) per gli slot password/frase/dispositivo/assistito, HKDF-SHA256 per lo slot passkey PRF. Solo testo cifrato + metadati non segreti vengono caricati su Supabase `user_backups` (RLS per utente). Il server non può decifrare senza un segreto detenuto dall'utente. Lo slot passkey è **anch'esso** zero-knowledge: la sua chiave di unwrap è derivata sul dispositivo dall'output WebAuthn PRF (`hmac-secret`) dell'autenticatore, e il server non detiene alcun segreto passkey (vedi §4.3).

### 3.2 Cosa viene sottoposto a backup (il payload minimizzato)

`BackupConfigurationPayload` (`LavaSecCore`) è il testo in chiaro che viene sigillato. È deliberatamente piccolo e fa round-trip con `AppConfiguration`. **(Implementato)**

**Incluso:** gli **ID** delle blocklist abilitate (riferimenti al catalogo, non i byte delle liste), domini consentiti/bloccati, preset del resolver / resolver personalizzato, preferenze di log locale, il registro LavaGuard, un suggerimento di protezione e i metadati delle sorgenti di blocklist personalizzate.

**Escluso:** `isPaid` (l'entitlement è locale), flag QA, diagnostica, snapshot dei Filtri e il contenuto completo delle blocklist (riferito solo tramite ID di catalogo). La tua cronologia di navigazione e le tue query DNS non fanno mai parte di questo payload; il dispositivo non le registra mai come flusso di telemetria di routine.

### 3.3 L'envelope (crittografia lato client)

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa la crittografia. **(Implementato)**

1. **Cifratura del payload.** Il payload minimizzato viene sigillato una volta con **AES-256-GCM** sotto una **chiave di payload casuale da 32 byte** (generata con `SecRandomCopyBytes`).
2. **Wrapping delle chiavi (key slot).** Quella singola chiave di payload è avvolta indipendentemente in uno o più **key slot**, uno per segreto; ciascuno slot avvolge in AES-GCM una copia della chiave di payload. Il segreto di qualsiasi singolo slot sblocca l'intero backup. La derivazione della chiave di wrapping è per tipo di slot: gli slot `password` / `recoveryPhrase` / `keychain` (dispositivo) / `assistedRecovery` usano **PBKDF2-HMAC-SHA256, 210.000 iterazioni** (produzione; `defaultPasswordIterations = 210_000`) con un nuovo salt casuale da 16 byte per slot; lo slot `passkey` usa **HKDF-SHA256** sull'output PRF dell'autenticatore (info `"LavaSec passkey backup PRF v1"`), con il salt PRF non segreto persistito nello slot così che il ripristino possa riprodurre l'output.
3. **Tipi di slot.** L'envelope supporta cinque tipi di slot: `password`, `recoveryPhrase`, `keychain` (segreto del dispositivo), `assistedRecovery` e `passkey`.

La configurazione rilasciata è **senza password** (`makePasswordless`, guidata da `AppViewModel.turnOnEncryptedBackup`). Crea uno **slot `keychain` (dispositivo) + uno slot `assistedRecovery` + uno slot `passkey` opzionale**. Le factory `password` / `recoveryPhrase` e i metodi di decifratura esistono ancora per envelope legacy/retrocompatibili (esercitati solo dai test) ma l'interfaccia attiva non crea mai un envelope solo-password — considera il backup con password come non rilasciato. **(Implementato; slot password Abbandonato dal flusso live.)**

**Integrità / anti-downgrade:** `envelopeVersion` è fissato in modo rigido a `1`, e la KDF di ciascuno slot è fissata per tipo — `PBKDF2-HMAC-SHA256` per gli slot password/frase/dispositivo/assistito, `HKDF-SHA256` per lo slot passkey PRF. Versioni non supportate o KDF non corrispondenti vengono rifiutate, così che metadati falsificati o sottoposti a downgrade non possano indebolire l'unwrap. **(Implementato)**

### 3.4 Caricamento e archiviazione

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) carica l'envelope **direttamente** sulla tabella PostgREST di Supabase `user_backups`, facendo upsert su `user_id`, con ambito definito dall'access token dell'utente. **Non esiste alcuna route Worker per il caricamento dell'envelope** — il client parla direttamente con Supabase sotto RLS; il Worker tocca `user_backups` solo per eliminarlo durante l'eliminazione dell'account. **(Implementato)**

Cosa finisce in `user_backups`:

- il **testo cifrato**, e
- **solo metadati non segreti:** nome del cipher, i record dei key slot (salt, conteggi di iterazione, chiavi avvolte, etichette degli slot), il `server_recovery_share`, `createdAt` e la dimensione in byte.

La riga è protetta da **row-level security**: ogni riga è leggibile/scrivibile solo dal suo proprietario (`auth.uid() = user_id`); il ruolo anonimo non ha accesso. La dimensione è limitata a ~256 KiB di testo cifrato / 32 KiB di metadati a livello di DB (`20260518000000_zero_knowledge_backups.sql`, inasprito in `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementato)**

### 3.5 La garanzia — cosa il server può e non può vedere

**Il server memorizza:** testo cifrato, salt/iterazioni KDF, key slot avvolti, il `server_recovery_share` e pochi campi non segreti (cipher, dimensione, timestamp).

**Il server non riceve né memorizza mai:** le impostazioni/i domini/le preferenze DNS in chiaro, la frase di recupero, qualsiasi password di backup, o la chiave di payload non avvolta.

**Pertanto:** Supabase **non può decifrare un backup** senza un segreto detenuto dall'utente. Tutti e tre i percorsi di ripristino — lo slot della chiave di dispositivo, la frase di recupero (combinata con la condivisione del server, §4.2) e lo slot passkey (l'output PRF dell'autenticatore, §4.3) — decifrano **sul dispositivo**, e il server non detiene alcun segreto di decifratura per nessuno di essi. Ciò è affermato nei commenti della migrazione e nel piano di privacy, ed è testato (i test dell'envelope confermano che nessun dominio/URL in chiaro trapela nella forma caricata).

**Avvertenza precisa sul modello di minaccia — non sovradichiarare.** Per lo slot di **ripristino assistito**, il server detiene *sia* il `server_recovery_share` *sia* lo slot `assistedRecovery` avvolto in `user_backups`. L'unica cosa che gli manca è la frase di recupero dell'utente, che Lava non riceve mai. Quindi, se il server fosse completamente compromesso, l'entropia della frase di recupero (~105 bit, vedi §4.1) più il costo PBKDF2 a 210k iterazioni è l'**unica** barriera contro un brute-force offline di quello slot. Ciò è intenzionale (il ripristino assistito è a due fattori per progettazione — nessuna delle due metà da sola decifra), ma implica che l'entropia della frase di recupero è portante, non decorativa. Il segreto dello slot `keychain` (dispositivo) non lascia mai il dispositivo, quindi non è affatto esposto a una compromissione del server.

---

## 4. Ripristino

`restoreEncryptedBackup` (in `AppViewModel`) decifra provando gli slot disponibili: chiave di dispositivo, frase di recupero o passkey. In ogni modalità l'envelope viene caricato localmente (o recuperato da Supabase) e poi **decifrato sul dispositivo** — il server non decifra mai.

### 4.1 Frase di recupero

`BackupRecoveryPhrase` (`LavaSecCore`) genera una **frase CVCV di 8 parole** (consonante-vocale-consonante-vocale) da `SecRandom` con campionamento per rifiuto (~13,2 bit/token → **~105 bit totali**), normalizzata in minuscolo. **(Implementato)** Il ripristino tollera la formattazione dell'utente (spaziatura/maiuscole) tramite parsing/normalizzazione prima che lo slot venga provato.

Questo è il fattore di recupero **fuori dispositivo** dell'utente — salvato dall'utente, mai caricato. Secondo l'irrobustimento della privacy (§5), copiare la frase è **opzionale** e, quando usato, passa attraverso una pasteboard solo locale / a scadenza (10 minuti) anziché forzare l'esposizione alla pasteboard globale.

### 4.2 Ripristino assistito (la combinazione a due fattori)

La sola frase di recupero **non** sblocca lo slot `assistedRecovery`. Il segreto dello slot è derivato da **entrambe** le metà:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

I tre segmenti sono uniti da un **separatore byte NUL (`0x00`)** nell'effettivo input UTF-8 — ovvero la stringa hashata è `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — quindi il `‖` qui sopra denota una concatenazione delimitata da NUL, non una concatenazione nuda. `serverRecoveryShare` è un valore casuale memorizzato nei metadati dell'envelope lato server; `normalizedPhrase` è la frase di recupero dell'utente. **Nessuna delle due metà da sola decifra** — il ripristino richiede la condivisione del server (recuperata con il backup) *e* la frase detenuta dall'utente. **(Implementato)**

### 4.3 Ripristino tramite passkey — zero-knowledge, derivato da PRF

Lo slot `passkey` opzionale aggiunge un fattore con supporto hardware, ed è **zero-knowledge**: la sua chiave di unwrap è derivata **sul dispositivo** dall'output WebAuthn PRF (`hmac-secret`) dell'autenticatore. Il server non registra alcun passkey, non emette challenge WebAuthn e non memorizza alcun segreto di recupero — non esiste alcun passaggio di rilascio lato server.

- **Registrazione/asserzione:** `BackupPasskeyCoordinator` (`LavaSecApp`) esegue WebAuthn tramite `ASAuthorizationPlatformPublicKeyCredentialProvider`, relying party **`lavasecurity.app`**, richiedendo l'estensione PRF su un salt per credenziale e richiedendo la verifica dell'utente.
- **Derivazione della chiave (zero-knowledge):** l'autenticatore restituisce un output PRF che **non lascia mai il dispositivo**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva con HKDF-SHA256 la chiave di wrapping dello slot da quell'output PRF (info `"LavaSec passkey backup PRF v1"`) e avvolge in AES-GCM la chiave di payload; solo il salt PRF non segreto e l'ID credenziale vengono persistiti nello slot. Al ripristino, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` ri-asserisce la credenziale per riprodurre lo stesso output PRF, e `decryptWithPasskeyPRFOutput` sblocca lo slot localmente. Il server **non** detiene alcun segreto passkey, quindi nessun percorso service-role può recuperare un backup protetto da passkey.

Il precedente design di escrow (una tabella service-role `backup_passkey_recovery` che deteneva un `recovery_secret` lato server, più una tabella `backup_passkey_challenges` ed endpoint Worker `/v1/backup/passkeys/*`) è stato **Abbandonato**: le tabelle sono state rimosse in una migrazione del backend, il Worker non porta alcuna route passkey, e `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` asserisce affermativamente che `BackupPasskeyRecoveryService` e qualsiasi percorso di escrow lato server sono assenti. **(Implementato)**

> **Avvertenza sulla prontezza per la produzione:** trattare le passkey salvate come un fattore recuperabile completamente pronto per la produzione su dispositivi fisici dipende ancora dall'associazione webcredentials per `lavasecurity.app`. La metà iOS è dichiarata — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` porta `webcredentials:lavasecurity.app` — e la metà server (il file `apple-app-site-association` e gli header) è ora ospitata nel sito di marketing. Finché quell'associazione non si risolve su un dato dispositivo, il percorso di associazione webcredentials può fallire e fa emergere `BackupPasskeyError.webCredentialsAssociationUnavailable`. Il fattore passkey stesso è implementato; la sua prontezza end-to-end su hardware reale è **Pianificata**.

---

## 5. Minimizzazione dei dati e posizione sulla privacy

- **Account opzionale.** La protezione funziona senza alcun account; l'accesso abilita solo il backup delle impostazioni.
- **Testo in chiaro solo locale.** Il telefono è l'unico luogo in cui esistono le impostazioni in chiaro e i segreti di decifratura; Supabase detiene un envelope opaco per utente.
- **Payload minimizzato.** Vengono sottoposte a backup solo le impostazioni nella §3.2; `isPaid`, flag QA, diagnostica, snapshot e i byte completi delle blocklist sono esclusi. Le blocklist sono riferite tramite ID di catalogo, mai incorporate.
- **Nessuna telemetria di navigazione/DNS.** Non esiste alcuna tabella lato server per query DNS di routine o telemetria per dominio; il filtraggio resta sul dispositivo.
- **Il materiale di sblocco è locale al dispositivo.** Il materiale di sblocco del backup è memorizzato con accessibilità `…ThisDeviceOnly` e **non** è sincronizzato con iCloud. Questo ha **invertito** il design a Keychain sincronizzabile del piano originale, così che Lava non sincronizzi silenziosamente il materiale di sblocco tramite iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementato; inverte il piano precedente.)**

### Eliminazione dell'account

L'eliminazione è **Implementata** e passa attraverso un endpoint Worker autenticato, non eliminazioni dirette dal client. `AccountAuthService.deleteAccount` invia l'access token dell'utente a `POST /v1/account/delete`; il Worker `lavasec-api` (service role) elimina le righe `bug_reports` dell'utente (e i loro allegati R2), `user_backups`, `entitlements`, `user_settings` e `profiles`, poi elimina l'utente di Supabase Auth tramite l'admin API, restituendo solo uno stato di eliminazione + i provider collegati. L'app quindi esegue il sign-out localmente e cancella il materiale di sblocco del backup (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Nota: il frontmatter YAML del piano di eliminazione riporta già `status: Done` e risiede in `plans/implemented/`. Un'annotazione **nel corpo** obsoleta riporta `Status: Backlog.`, ma secondo la regola della cartella-corsia (la cartella è autorevole) e la presenza nel codice (sia app che Worker esistono), la funzionalità è **Implementata**; la riga nel corpo è un bug di documentazione, non il frontmatter.

---

## 6. Riepilogo dello stato

| Area | Dettaglio | Stato |
|---|---|---|
| Accesso Apple / Google `id_token` tramite Supabase | Flussi nativi, nonce hashato, scambio raw-URLRequest | Implementato |
| Accesso email/password | Possedere password rifiutato | Abbandonato |
| Sessione nel Keychain (locale al dispositivo, per provider) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementato |
| Envelope AES-256-GCM + key slot PBKDF2-HMAC-SHA256 (210k) | Lato client; solo testo cifrato + metadati non segreti su `user_backups` (RLS) | Implementato |
| Configurazione senza password (slot dispositivo + ripristino assistito + passkey opzionale) | `makePasswordless` | Implementato |
| Key slot password nel flusso live | Sopravvive in `LavaSecCore` solo per i test | Abbandonato |
| Frase di recupero (CVCV di 8 parole, ~105 bit) | Fattore fuori dispositivo | Implementato |
| Ripristino assistito (condivisione del server + frase tramite SHA256, delimitato da NUL) | A due fattori; nessuna delle due metà da sola | Implementato |
| Ripristino tramite passkey (zero-knowledge, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | Slot derivato HKDF dall'output PRF, nessun segreto lato server | Implementato |
| Passkey come fattore pronto per la produzione su hardware | Necessita dell'associazione webcredentials (AASA ospitato nel sito di marketing) | Pianificato |
| Eliminazione dell'account (Worker autenticato, service role) | Rimuove backup/impostazioni/entitlement/profilo/allegati + utente Auth | Implementato |
| Gate biometrico/di presenza utente sul materiale di sblocco | Elemento di revisione di release-gate | Pianificato |
| Estrazione di `EncryptedBackupCoordinator` da `AppViewModel` | Solo modularizzazione; nessuna modifica al modello di sicurezza | In corso |

---

## Correlati

- [Panoramica del sistema](./system-overview.md) — l'intero sistema su una schermata, inclusi i confini di fiducia.
- [Client iOS](./ios-client.md) — `AppViewModel` e i target dell'app che guidano il backup.
- [Backend e dati](./backend-and-data.md) — il Worker `lavasec-api`, la RLS di Supabase e l'archiviazione `user_backups`.
- [Filtraggio DNS e blocklist](./dns-filtering-and-blocklists.md) — i preset del resolver e i transport le cui impostazioni sono trasportate nel payload del backup.
