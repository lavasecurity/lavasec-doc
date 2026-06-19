---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-infra, lavasec-ios]
grounded_at: {lavasec-infra: "5f425af", lavasec-ios: "1fbab70"}
---

# Accounts & Zero-Knowledge Backup

> **Audience:** engineers.
> **Authority:** where this doc and a plan disagree, **code wins** — divergences are called out inline. Status reflects the code-confirmed reality, not plan aspiration. Status legend: **Implemented** (shipped and confirmed in code), **In progress** (partially landed), **Planned** (designed, not built), **Dropped** (rejected or reverted).

Accounts are **optional**. Core protection is free forever and requires no account; sign-in exists only to back up your *settings*, encrypted, so you can restore them on a new device. This document covers the auth flow, where the session lives, the zero-knowledge backup envelope, the recovery paths, and exactly what the server can and cannot see.

The canonical privacy promise this doc serves:

> All DNS filtering happens on the device; Lava never routes your browsing through its servers and never receives the stream of domains you visit — the backend holds only catalog metadata, an opaque per-user encrypted backup, and anonymized diagnostics you choose to send.

Component split: pure crypto + request building lives in `LavaSecCore`; orchestration + UI lives in `LavaSecApp`. Siblings: [System Overview](./system-overview.md), [iOS Client](./ios-client.md), [Backend & Data](./backend-and-data.md), [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md).

---

## 1. Authentication flow

**Providers: Apple and Google only.** **(Implemented)** `AccountAuthProvider` enumerates exactly `.apple` and `.google` (`AccountAuthService.swift`). Email/password — and any support-assisted recovery that bypasses authentication — is explicitly **Dropped**; owning passwords would add reset/MFA/lockout/breach obligations not worth the complexity while Apple/Google suffice, and bypass recovery would break the zero-knowledge guarantee.

Both providers use the **native `id_token` grant**, not the Supabase Swift SDK and not web OAuth:

1. **Sign in natively.** Apple via AuthenticationServices; Google via the GoogleSignIn SDK. Each yields a provider `id_token` (Google also an access token). The app generates a CSPRNG raw nonce, hashes it with SHA256, and passes the hash to the provider so the issued `id_token` is bound to it. **(Implemented)**
2. **Exchange at Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) builds a raw `URLRequest` to Supabase Auth `auth/v1/token?grant_type=id_token`, posting `provider` + `id_token` + optional `access_token` + the **raw** nonce (so Supabase can verify the binding and reject replays), with the `apikey` header. No SDK; `LavaSecCore` stays free of network/auth dependencies. **(Implemented)**
3. **Receive a session.** Supabase verifies the token and returns a session: an access token, a refresh token, an expiry, and a user record (provider/providers). Refresh uses the same helper with `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orchestrates all of this — it runs the native flows, performs the exchange, persists and refreshes sessions, exposes `AccountAuthState`, and drives account deletion through the Worker.

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

## 2. Session & Keychain storage

The **only** thing persisted from sign-in is the Supabase session — access and refresh tokens as JSON. There is **no** server-side mirror of who you are beyond the Supabase Auth user and the rows you own.

- **Where:** `AccountSessionKeychainStore` (`LavaSecApp`), Keychain service `com.lavasec.account-session`, stored **per provider** (`supabase-session-apple` / `supabase-session-google`, plus a legacy-account migration). **(Implemented)**
- **Accessibility:** all stores share `GenericKeychainStore` (`LavaSecCore`), pinned to `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. That means **device-local, not iCloud-synced, and not carried in device backups**. **(Implemented)**

The same `GenericKeychainStore` mechanics back three stores: account session, the backup unlock material (`BackupKeychainStore`, service `com.lavasec.zero-knowledge-backup`), and the app passcode. None of them sync through iCloud Keychain.

> **Open review item (not a claimed behavior):** the current accessibility class has no biometric/user-presence gate (no `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Whether to tighten unlock material to a presence-gated access control is tracked as a release-gate review item; the shipped value today is after-first-unlock-this-device-only. **(Planned)**

---

## 3. Zero-knowledge backup

### 3.1 What it is, precisely

When you turn on encrypted backup, the **iOS client** encrypts a minimized copy of your *settings* and uploads only the ciphertext plus non-secret metadata to Supabase. The phone is the only place plaintext and the decrypting secrets ever exist.

> **Zero-knowledge backup:** Client-side AES-256-GCM envelope; the random payload key is wrapped in per-slot key slots — PBKDF2-HMAC-SHA256 (210k iters) for the password/phrase/device/assisted slots, HKDF-SHA256 for the PRF passkey slot. Only ciphertext + non-secret metadata upload to Supabase `user_backups` (RLS per user). Server cannot decrypt without a user-held secret. The passkey slot is **also** zero-knowledge: its unwrap key is derived on-device from the authenticator's WebAuthn PRF (`hmac-secret`) output, and the server holds no passkey secret (see §4.3).

### 3.2 What gets backed up (the minimized payload)

`BackupConfigurationPayload` (`LavaSecCore`) is the plaintext that gets sealed. It is deliberately small and round-trips to `AppConfiguration`. **(Implemented)**

**Included:** enabled blocklist **IDs** (catalog references, not list bytes), allowed/blocked domains, resolver preset / custom resolver, local-log preferences, the LavaGuard ledger, a protection hint, and custom blocklist source metadata.

**Excluded:** `isPaid` (entitlement is local), QA flags, diagnostics, filter snapshots, and the full blocklist contents (referenced by catalog ID only). Your browsing history and DNS queries are never part of this payload because the device never records them as a routine telemetry stream.

### 3.3 The envelope (client-side crypto)

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implements the crypto. **(Implemented)**

1. **Payload encryption.** The minimized payload is sealed once with **AES-256-GCM** under a random **32-byte payload key** (generated with `SecRandomCopyBytes`).
2. **Key wrapping (key slots).** That single payload key is independently wrapped into one or more **key slots**, one per secret, then AES-GCM-wraps a copy of the payload key. Any single slot's secret unlocks the whole backup. The wrapping-key derivation is per slot kind: the `password` / `recoveryPhrase` / `keychain` (device) / `assistedRecovery` slots use **PBKDF2-HMAC-SHA256, 210,000 iterations** (production; `defaultPasswordIterations = 210_000`) with a fresh 16-byte random salt per slot; the `passkey` slot uses **HKDF-SHA256** over the authenticator's PRF output (info `"LavaSec passkey backup PRF v1"`), with the non-secret PRF salt persisted in the slot so restore can reproduce the output.
3. **Slot kinds.** The envelope supports five slot kinds: `password`, `recoveryPhrase`, `keychain` (device secret), `assistedRecovery`, and `passkey`.

The shipped setup is **passwordless** (`makePasswordless`, driven by `AppViewModel.turnOnEncryptedBackup`). It creates a **`keychain` (device) slot + an `assistedRecovery` slot + an optional `passkey` slot**. The `password` / `recoveryPhrase` factories and decrypt methods still exist for legacy/back-compat envelopes (exercised only by tests) but the active UI never creates a password-only envelope — treat password backup as not shipped. **(Implemented; password slot Dropped from the live flow.)**

**Integrity / anti-downgrade:** `envelopeVersion` is hard-pinned to `1`, and each slot's KDF is pinned per kind — `PBKDF2-HMAC-SHA256` for the password/phrase/device/assisted slots, `HKDF-SHA256` for the PRF passkey slot. Unsupported versions or mismatched KDFs are rejected, so forged or downgraded metadata cannot weaken the unwrap. **(Implemented)**

### 3.4 Upload & storage

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) uploads the envelope **directly** to the Supabase PostgREST table `user_backups`, upserting on `user_id`, scoped by the user's access token. **There is no Worker route for envelope upload** — the client talks straight to Supabase under RLS; the Worker only touches `user_backups` to delete it during account deletion. **(Implemented)**

What lands in `user_backups`:

- the **ciphertext**, and
- **non-secret metadata only:** cipher name, the key-slot records (salts, iteration counts, wrapped keys, slot labels), the `server_recovery_share`, `createdAt`, and the byte size.

The row is protected by **row-level security**: each row is readable/writable only by its owner (`auth.uid() = user_id`); the anonymous role has no access. Size is capped at ~256 KiB ciphertext / 32 KiB metadata at the DB level (`20260518000000_zero_knowledge_backups.sql`, tightened in `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implemented)**

### 3.5 The guarantee — what the server can and cannot see

**The server stores:** ciphertext, KDF salts/iterations, wrapped key slots, the `server_recovery_share`, and a few non-secret fields (cipher, size, timestamp).

**The server never receives or stores:** the plaintext settings/domains/DNS preferences, the recovery phrase, any backup password, or the unwrapped payload key.

**Therefore:** Supabase **cannot decrypt a backup** without a user-held secret. All three restore paths — the device-key slot, the recovery phrase (combined with the server share, §4.2), and the passkey slot (the authenticator's PRF output, §4.3) — decrypt **on-device**, and the server holds no decryption secret for any of them. This is asserted in the migration comments and the privacy plan, and tested (the envelope tests confirm no plaintext domain/URL leaks into the uploaded shape).

**Precise threat-model caveat — do not overclaim.** For the **assisted-recovery** slot, the server holds *both* the `server_recovery_share` *and* the wrapped `assistedRecovery` slot in `user_backups`. The only thing it lacks is the user's recovery phrase, which Lava never receives. So if the server were fully compromised, the recovery phrase's entropy (~105 bits, see §4.1) plus the 210k-iteration PBKDF2 cost is the **sole** barrier against an offline brute-force of that slot. This is intentional (assisted recovery is two-factor by design — neither half alone decrypts), but it means recovery-phrase entropy is load-bearing, not decorative. The `keychain` (device) slot's secret never leaves the device, so it is not exposed to a server compromise at all.

---

## 4. Recovery

A backup is only useful if you can restore it. `restoreEncryptedBackup` (in `AppViewModel`) decrypts by trying the available slots: device key, recovery phrase, or passkey. In every mode the envelope is loaded locally (or fetched from Supabase) and then **decrypted on-device** — the server never decrypts.

### 4.1 Recovery phrase

`BackupRecoveryPhrase` (`LavaSecCore`) generates an **8-word CVCV phrase** (consonant-vowel-consonant-vowel) from `SecRandom` with rejection sampling (~13.2 bits/token → **~105 bits total**), normalized lowercase. **(Implemented)** Restore tolerates user formatting (spacing/case) via parsing/normalization before the slot is tried.

This is the user's **off-device** recovery factor — saved by the user, never uploaded. Per the privacy hardening (§5), copying the phrase is **optional** and, when used, goes through a local-only / expiring (10-minute) pasteboard rather than forcing global-pasteboard exposure.

### 4.2 Assisted recovery (the two-factor combination)

The recovery phrase alone does **not** unlock the `assistedRecovery` slot. The slot secret is derived from **both** halves:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

The three segments are joined by a **NUL byte (`0x00`) separator** in the actual UTF-8 input — i.e. the hashed string is `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — so the `‖` above denotes NUL-delimited concatenation, not bare concatenation. `serverRecoveryShare` is a random value stored in the envelope metadata server-side; `normalizedPhrase` is the user's recovery phrase. **Neither half alone decrypts** — restore requires the server share (fetched with the backup) *and* the user-held phrase. **(Implemented)**

### 4.3 Passkey recovery — zero-knowledge, PRF-derived

The optional `passkey` slot adds a hardware-backed factor, and it is **zero-knowledge**: its unwrap key is derived **on-device** from the authenticator's WebAuthn PRF (`hmac-secret`) output. The server registers no passkey, issues no WebAuthn challenges, and stores no recovery secret — there is no server release step.

- **Registration/assertion:** `BackupPasskeyCoordinator` (`LavaSecApp`) runs WebAuthn via `ASAuthorizationPlatformPublicKeyCredentialProvider`, relying party **`lavasecurity.app`**, requesting the PRF extension on a per-credential salt and requiring user verification.
- **Key derivation (zero-knowledge):** the authenticator returns a PRF output that **never leaves the device**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) HKDF-SHA256-derives the slot's wrapping key from that PRF output (info `"LavaSec passkey backup PRF v1"`) and AES-GCM-wraps the payload key; only the non-secret PRF salt and credential ID are persisted in the slot. On restore, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` re-asserts the credential to reproduce the same PRF output, and `decryptWithPasskeyPRFOutput` unwraps the slot locally. The server holds **no** passkey secret, so no service-role path can recover a passkey-protected backup.

The earlier escrow design (a service-role `backup_passkey_recovery` table holding a server-side `recovery_secret`, plus a `backup_passkey_challenges` table and `/v1/backup/passkeys/*` Worker endpoints) was **Dropped**: the tables were removed in `lavasec-infra: supabase/migrations/20260616000000_drop_backup_passkey_recovery.sql` (LAV-64), the Worker carries no passkey routes, and `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` affirmatively asserts that `BackupPasskeyRecoveryService` and any server-escrow path are absent. **(Implemented)**

> **Production-readiness caveat:** treating saved passkeys as a fully production-ready recoverable factor on physical devices still depends on the webcredentials association for `lavasecurity.app`. The iOS half is declared — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` carries `webcredentials:lavasecurity.app` — and the server half (the `apple-app-site-association` file and headers) is now hosted in the marketing site (`lavasec-web`, validated in that repo). Until that association resolves on a given device, the webcredentials-association path can fail and surfaces `BackupPasskeyError.webCredentialsAssociationUnavailable`. The passkey factor itself is implemented; its end-to-end readiness on real hardware is **Planned**.

---

## 5. Data minimization & privacy posture

- **Optional account.** Protection works with no account; sign-in only enables settings backup.
- **Local plaintext only.** The phone is the sole place plaintext settings and decrypting secrets exist; Supabase holds one opaque envelope per user.
- **Minimized payload.** Only the settings in §3.2 are backed up; `isPaid`, QA flags, diagnostics, snapshots, and full blocklist bytes are excluded. Blocklists are referenced by catalog ID, never embedded.
- **No browsing/DNS telemetry.** There is no server-side table for routine DNS queries or per-domain telemetry; filtering stays on the device.
- **Unlock material is device-local.** Backup unlock material is stored with `…ThisDeviceOnly` accessibility and is **not** iCloud-synced. This **reversed** the original plan's synchronizable-Keychain design, so Lava does not silently sync unlock material through iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implemented; reverses earlier plan.)**

### Account deletion

Deletion is **Implemented** and runs through an authenticated Worker endpoint, not direct client deletes. `AccountAuthService.deleteAccount` sends the user's access token to `POST /v1/account/delete`; the `lavasec-api` Worker (service role) deletes the user's `bug_reports` (and their R2 attachments), `user_backups`, `entitlements`, `user_settings`, and `profiles` rows, then deletes the Supabase Auth user via the admin API, returning only a deleted status + linked providers. The app then signs out locally and clears backup unlock material (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Note: the deletion plan's YAML frontmatter already reads `status: Done` and it lives in `plans/implemented/`. A stale **in-body** annotation reads `Status: Backlog.`, but per the lane-folder rule (the folder is authoritative) and code presence (app + Worker both exist), the feature is **Implemented**; the in-body line is a doc bug, not the frontmatter.

---

## 6. Status summary

| Area | Detail | Status |
|---|---|---|
| Apple / Google `id_token` sign-in via Supabase | Native flows, hashed nonce, raw-URLRequest exchange | Implemented |
| Email/password sign-in | Owning passwords rejected | Dropped |
| Session in Keychain (device-local, per provider) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implemented |
| AES-256-GCM envelope + PBKDF2-HMAC-SHA256 (210k) key slots | Client-side; ciphertext + non-secret metadata only to `user_backups` (RLS) | Implemented |
| Passwordless setup (device + assisted-recovery + optional passkey slots) | `makePasswordless` | Implemented |
| Password key slot in the live flow | Survives in `LavaSecCore` for tests only | Dropped |
| Recovery phrase (8-word CVCV, ~105 bits) | Off-device factor | Implemented |
| Assisted recovery (server share + phrase via SHA256, NUL-delimited) | Two-factor; neither half alone | Implemented |
| Passkey recovery (zero-knowledge, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | PRF output HKDF-derived slot, no server secret | Implemented |
| Passkey as production-ready factor on hardware | Needs webcredentials association (AASA hosted in lavasec-web) | Planned |
| Account deletion (authenticated Worker, service role) | Removes backups/settings/entitlements/profile/attachments + Auth user | Implemented |
| Biometric/user-presence gate on unlock material | Release-gate review item | Planned |
| `EncryptedBackupCoordinator` extraction from `AppViewModel` | Modularization only; no security-model change | In progress |

---

## Related

- [System Overview](./system-overview.md) — the whole system on one screen, including trust boundaries.
- [iOS Client](./ios-client.md) — `AppViewModel` and the app targets that drive backup.
- [Backend & Data](./backend-and-data.md) — the `lavasec-api` Worker, Supabase RLS, and `user_backups` storage.
- [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) — the resolver presets and transports whose settings are carried in the backup payload.
