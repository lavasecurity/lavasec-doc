# Accounts & Zero-Knowledge Backup

A Lava account is **optional** and exists for exactly one purpose: to authenticate the sync of an encrypted settings backup. DNS filtering works with no login — the [packet-tunnel engine](./dns-filtering-and-blocklists.md) never needs an account, and turning protection on never prompts for one. This page is for engineers and explains how sign-in works, where session material lives, how the zero-knowledge backup envelope is built, and what the server can and cannot see.

> **The privacy promise:** DNS filtering happens locally on your device; Lava never receives your routine DNS queries, browsing history, or per-domain telemetry, and any optional account backup is end-to-end encrypted so Lava can only ever store ciphertext.

Status is marked **Implemented**, **(In progress)**, **(Planned)**, or **(Dropped)** per the [status legend](./system-overview.md#status-legend). Default unmarked statements describe shipped behavior. The component split here lives in `LavaSecCore` (pure crypto + request building) and `LavaSecApp` (orchestration + UI); the server side is covered in [backend & data](./backend-and-data.md).

---

## 1. Auth providers & flow

Lava supports exactly two sign-in providers: **Sign in with Apple** and **Google**. Email/password sign-in is intentionally **not** implemented — owning passwords would add reset, MFA, recovery, and lockout obligations not justified while Apple and Google cover the use case; magic-link/OTP is reserved only as a possible future path (**Dropped**; `plans/implemented/2026-05-18-defer-email-sign-in-plan.md`).

Both providers funnel into Supabase Auth's native **ID-token grant** (`grant_type=id_token`) rather than a hosted web/OAuth redirect. This keeps a single Supabase auth authority while using the native Apple/Google credential UX.

| Component | Role |
|---|---|
| `SupabaseIDTokenAuth` (`LavaSecCore`) | Pure request/response helper that builds the `auth/v1/token` `id_token` and `refresh_token` grant requests and decodes the Supabase session/user. |
| `AccountAuthService` (`LavaSecApp`, `@MainActor`) | Auth orchestrator: Apple (`ASAuthorization`) and Google (GoogleSignIn SDK) flows, nonce generation, session refresh, multi-provider reconciliation, sign-out, and the account-deletion client. |

### Flow

1. **Obtain a provider ID token on-device.** For Apple, the app runs `ASAuthorization` with `requestedScopes = [.email]`, generating a raw nonce locally and setting `request.nonce = SHA256(rawNonce)` (`AccountAuthService.swift:386-401,221-232`). For Google, the GoogleSignIn SDK returns an `idToken` (and access token) with the same SHA-256-hashed nonce binding (`AccountAuthService.swift:403-461,741-755`). The hashed nonce goes to the provider; the **raw** nonce is what Supabase later verifies — this binding mitigates token replay.
2. **Exchange for a Supabase session.** The app POSTs the provider `id_token`, the **raw** nonce, and the publishable (anon) `apikey` to `{projectURL}/auth/v1/token` (`SupabaseIDTokenAuth.swift:131-201`). Supabase verifies the token and returns a session (access + refresh tokens) plus a minimal user (`id`, optional `email`, and the provider list derived from `app_metadata` + `identities`).
3. **Persist only the session** (see §2). No provider credential, password, or raw token beyond the Supabase session is stored.

### Session refresh

Sessions are refreshed via `grant_type=refresh_token` with a 90-second pre-expiry buffer (`AccountAuthService.swift:492-509,779-786`; `SupabaseIDTokenAuth.swift:150-159`). A failed refresh deletes the stored session for that provider, so a revoked or expired account fails closed rather than lingering.

---

## 2. Session & keychain storage

The only thing persisted from sign-in is the Supabase session itself — access token, refresh token, and the minimal user — written as a **per-provider** generic-password Keychain item.

| Store | Service | What it holds |
|---|---|---|
| `AccountSessionKeychainStore` (`LavaSecApp`) | `com.lavasec.account-session` | One Supabase session per provider (with legacy single-session migration) (`AccountSessionKeychainStore.swift:19-27,83-94`). |
| `BackupKeychainStore` (`LavaSecApp`) | `com.lavasec.zero-knowledge-backup` | Backup **unlock material**: device secret, passkey credential ID, recovery code (`BackupKeychainStore.swift:19-27`). |

Both go through `GenericKeychainStore` (`LavaSecCore`), which centralizes accessibility as `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` (`GenericKeychainStore.swift:41-43`). That `…ThisDeviceOnly` attribute is load-bearing: it means session and backup-unlock material are **device-only** and are **not** carried into iCloud Keychain or device backups. Decryption material can therefore never be silently synced to another device.

This was a deliberate hardening over the original 2026-05-18 design, which used synchronizable Keychain items (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md:18-26`).

**(Planned) open decision (P2-4):** backup Keychain items currently rely on app-level auth, not Keychain biometric/user-presence access control (no `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Whether to tighten this is tracked but not yet decided (`plans/backlog/2026-06-12-ios-release-gate-review.md:199-210,308`).

---

## 3. Zero-knowledge encrypted backup

When you turn on backup, your settings are encrypted **entirely on-device** before anything leaves the phone. The server stores only ciphertext and non-secret envelope metadata. This is what "zero-knowledge" means here — and §3.4 states the guarantee precisely, including its boundaries.

### 3.1 The envelope

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) is a versioned container holding the encrypted payload plus one or more **key slots**:

| Field | Meaning |
|---|---|
| `cipher` | `"AES-256-GCM"` |
| `payloadCiphertext` | AES-256-GCM ciphertext of the settings payload (base64) |
| `keySlots[]` | One record per unlock method, each wrapping the payload key |
| `serverRecoveryShare` | Optional server-held share for assisted recovery (see §4) |
| `ciphertextByteSize`, `createdAt` | Non-secret metadata |

### 3.2 Client-side encryption (envelope + key slots)

The crypto is two-layered (`ZeroKnowledgeBackupEnvelope.swift:258-311`, key derivation at `:346-377`):

1. **Payload encryption.** A random 32-byte **payload key** is generated with `SecRandomCopyBytes` and used to AES-256-GCM-seal the settings payload. The app is the only place this plaintext or this key ever exists.
2. **Key-slot wrapping.** The payload key is then independently wrapped into one slot per unlock method. Each slot derives a wrapping key from its own secret via **PBKDF2-HMAC-SHA256** (`kCCPBKDF2` / `kCCPRFHmacAlgSHA256`, `:358,363`) over a per-slot random 16-byte salt at **210,000 iterations** in production (`defaultPasswordIterations`), then AES-GCM-seals the payload key under that wrapping key.

Because each slot wraps the *same* payload key, any one valid secret recovers the payload — but no slot, salt, or wrapped key reveals anything about the plaintext or the other secrets.

Slot kinds in code are `keychain`, `assistedRecovery`, `passkey`, `recoveryPhrase`, and `password`. The shipped passwordless flow builds three of them.

### 3.3 The passwordless flow (canonical)

`makePasswordless` (`ZeroKnowledgeBackupEnvelope.swift:143-172`), wired by `AppViewModel.turnOnEncryptedBackup` (`AppViewModel.swift:4101-4161`), creates:

- a **`.keychain`** slot, unlocked by a random base64url 32-byte **device secret** stored in the device-only Keychain ("This Device" restore);
- an **`.assistedRecovery`** slot, unlocked by combining the recovery phrase with a server-held share (see §4);
- an optional **`.passkey`** slot (see §4).

> **(Dropped) password support.** A `.password` key slot, `decryptWithPassword`, `makeForTesting`, and `BackupPasswordPolicy` survive in `LavaSecCore` but are **not wired into the live UI or `AppViewModel`** — they are exercised only by tests. The passwordless flow superseded them (`ZeroKnowledgeBackupEnvelope.swift:17-23,204-206`; `plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). Treat password backup as not shipped.

### 3.4 Exactly what the server can vs cannot see

The encrypted envelope is uploaded to Supabase `user_backups` via PostgREST by `SupabaseBackupSyncService` (`BackupSyncService.swift:170-253`), and is RLS-scoped to `auth.uid() = user_id`.

**The server stores only:**

- the opaque `payloadCiphertext`;
- non-secret envelope metadata: schema/envelope/backup version, `key_slots` metadata (KDF name, salt, iterations, wrapped-key bytes), `ciphertext_byte_size`, `created_at`;
- the `server_recovery_share` (one half of assisted recovery — see §4).

**The server never receives, and cannot derive:**

- the settings plaintext;
- the random payload key or any slot's wrapping key;
- the recovery phrase;
- (in the passwordless flow) any password.

This is enforced both by what the client sends and by the database itself. The `user_backups` table caps ciphertext at ~256 KiB / 349,528 chars and metadata at 32 KiB, which prevents accidental upload of diagnostics, snapshots, or full blocklists (`20260518000000_zero_knowledge_backups.sql`; `20260605000000_tighten_backup_envelope_constraints.sql`). RLS denies cross-user reads (`20260518000000_zero_knowledge_backups.sql:36-63`). A server compromise that read every byte of `user_backups` would obtain ciphertext and metadata — never plaintext.

**Precise guarantee:** for backups created and restored through the passwordless device-secret or recovery-phrase paths, Lava's servers hold only ciphertext plus non-secret metadata and a server recovery share that is useless on its own; the decryption secrets exist only on-device or in the user's saved recovery phrase. The one documented exception is **passkey recovery**, which is **server-gated and not zero-knowledge** — see §4.3.

### 3.5 What's inside the payload (data-minimization)

The single plaintext placed inside the envelope is `BackupConfigurationPayload` (`LavaSecCore`), which is deliberately data-minimized (`BackupConfigurationPayload.swift:3-40`; `plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md:43-50`). It carries only the settings needed to reconstitute a configuration: enabled blocklist IDs, allow/block domains, resolver preset + custom resolver settings, local-log preferences, custom-blocklist source metadata, the LavaGuard achievement ledger, and a `protectionEnabledHint`. It does **not** carry diagnostics, compiled snapshots, full blocklist bytes, `isPaid`/entitlement state, or QA state. See §5.

---

## 4. Recovery

Restore offers three on-device unlock modes (`BackupRestoreView.swift:184-215`, `AppViewModel.swift:4182-4225,6419-6442`): **This Device**, **Recovery phrase**, and **Passkey**. In every mode the envelope is loaded locally (or fetched from Supabase) and then **decrypted on-device** — the server never decrypts.

### 4.1 This Device (device secret)

The fastest path: the `.keychain` slot is unlocked by the device secret already in the device-only Keychain. This works only on the device that created the backup, since the secret never syncs.

### 4.2 Recovery phrase (assisted recovery)

For new-device restore without a passkey, Lava splits the decryption secret across two parties so neither side alone can decrypt.

- The **recovery phrase** is **8 locally CSPRNG-generated** pseudo-word tokens (consonant-vowel-consonant-vowel), normalized case- and spacing-insensitively (`BackupRecoveryPhrase.swift:4-13,56-93`). The user saves it outside Lava; it is **never sent to the server**. Copy-to-clipboard is optional and uses a local-only, 10-minute-expiring pasteboard write (`BackupSetupView.swift:137-151`).
- The **server recovery share** is a random secret stored in envelope metadata / Supabase. It is required *alongside* the phrase but useless without it.

The actual secret for the `.assistedRecovery` slot is:

```
assistedRecoverySecret =
  base64url( SHA-256( "LavaSec assisted recovery v1" ‖ \0 ‖ serverRecoveryShare ‖ \0 ‖ normalizedPhrase ) )
```

(`ZeroKnowledgeBackupEnvelope.swift:25-42,216-226`). The recovery phrase alone cannot decrypt without the server's share, and the server's share alone cannot decrypt without the phrase — preserving the zero-knowledge property while still enabling account-assisted restore on a new device.

### 4.3 Passkey recovery — server-gated, **not** zero-knowledge

Passkey recovery is an explicit, documented exception to the zero-knowledge guarantee. Call it **server-gated recovery**, never zero-knowledge.

The app registers/asserts a platform passkey (WebAuthn, RP id `lavasecurity.app`) via `BackupPasskeyCoordinator` and exchanges credentials with the `lavasec-api` Worker's `v1/backup/passkeys/*` endpoints through `BackupPasskeyRecoveryService` (`BackupPasskeyCoordinator.swift:11-14,122-206`; `BackupPasskeyRecoveryService.swift:60-126`; `AppViewModel.swift:4258-4286`). The Worker issues short-lived (5-min) challenges and, after a successful WebAuthn assertion, **releases a stored `recovery_secret`** that decrypts the `.passkey` slot.

Why this is weaker: the recovery secret is escrowed server-side (Supabase `backup_passkey_recovery`, a service-role-only table). A system holding service-role access to **both** `user_backups` and `backup_passkey_recovery` could recover a passkey-protected backup (`server/supabase/README.md:40`; `20260605010000_backup_passkey_recovery.sql:24-27`). The device-secret and recovery-phrase paths have no such server-held secret. Do not describe passkey recovery as zero-knowledge.

| Component | Role |
|---|---|
| `BackupSetupView` | 3-step passwordless setup (overview, recovery-phrase save, confirm) → `turnOnEncryptedBackup`. |
| `BackupRestoreView` | Restore UI with This Device / Passkey / Recovery modes → `restoreEncryptedBackup`. |
| `BackupPasskeyCoordinator` | WebAuthn registration/assertion via `ASAuthorizationPlatformPublicKeyCredentialProvider`. |
| `BackupPasskeyRecoveryService` | `lavasec-api` client that escrows/returns the passkey recovery secret. |

---

## 5. Data-minimization stance

Lava's account and backup surface is built to hold as little as possible.

- **Account is optional and single-purpose.** Sign-in exists only to authenticate backup sync; protection never requires it.
- **Only a session is stored.** No password is owned (email/password is **Dropped**); only the Supabase session lives in the device-only Keychain.
- **Server stores only ciphertext + metadata.** The payload is encrypted client-side; the database cannot read settings, domains, the recovery phrase, or keys (§3.4).
- **The plaintext payload is minimized** to reconstitution-only fields — no diagnostics, snapshots, full blocklists, `isPaid`, or QA state (§3.5).
- **No routine DNS queries, browsing history, or per-domain telemetry are ever sent** to any Lava service. Filtering stays local to the device; there is no passive telemetry table on the backend.
- **Deletion is real.** Authenticated account deletion calls the `lavasec-api` Worker (`v1/account/delete`) with the Supabase access token; the Worker deletes the user's `user_backups`, bug reports (and their R2 attachments), entitlements, settings, and profile rows, then deletes the Supabase Auth user, and the app signs out and clears local sessions (`AccountAuthService.swift:357-365,616-657`; `plans/implemented/2026-05-25-account-deletion-data-rights-plan.md:40-48`).

---

## Related

- [System overview](./system-overview.md) — the whole system on one screen, including trust boundaries.
- [iOS client](./ios-client.md) — `AppViewModel` and the app targets that drive backup.
- [Backend & data](./backend-and-data.md) — the `lavasec-api` Worker, Supabase RLS, and `user_backups` storage.
- [DNS filtering & blocklists](./dns-filtering-and-blocklists.md) — the resolver presets and transports whose settings are carried in the backup payload.
