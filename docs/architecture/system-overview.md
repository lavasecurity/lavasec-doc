# System Overview

Lava Security is a privacy-first iOS app that filters DNS locally on the device through an on-device NetworkExtension packet tunnel, blocking known risky and unwanted domains without routing your browsing through Lava's servers.

This page is the whole system on one screen, written for engineers. It names every component, shows how they connect, traces the three data flows that matter, and states the trust boundaries that make the privacy promise true. Each component links to its own deeper doc.

> **The privacy promise:** DNS filtering happens locally on your device; Lava never receives your routine DNS queries, browsing history, or per-domain telemetry, and any optional account backup is end-to-end encrypted so Lava can only ever store ciphertext.

Status is marked throughout as **Implemented**, **(In progress)**, **(Planned)**, or **(Dropped)** per the [status legend](#status-legend). Default unmarked statements describe shipped behavior.

---

## Components

### On device (iOS)

Three app targets share `LavaSecCore` and the **App Group** `group.com.lavasec`, which is how the app, the packet-tunnel extension, and the widget read the same compiled snapshot and config.

| Component | Role | Doc |
|---|---|---|
| **iOS app** (`AppViewModel`) | VPN lifecycle source of truth; orchestrates turn-on, onboarding, and backup. Controls the tunnel via `NETunnelProviderManager` + `sendProviderMessage` (a **command / provider message**), not Darwin `CFNotification` observers. | [iOS client](./ios-client.md) |
| **Packet-tunnel extension** (`PacketTunnelProvider` / `LavaSecTunnel`) | The `NEPacketTunnelProvider` that parses DNS packets, extracts the queried domain, evaluates it against the memory-mapped compiled snapshot, and forwards allowed queries upstream. Bounded by the ~50 MiB per-process jetsam memory ceiling. `VPNLifecycleController` handles turn-on/pause/resume, on-demand, and snapshot reload. | [DNS filtering engine](./dns-filtering-and-blocklists.md) |
| **Widget** | Shares `LavaSecCore` state and config through the same App Group. | [iOS client](./ios-client.md) |

The encrypted upstream transports live in `LavaSecCore`: `DoHTransport` (**DoH**, with observational **DoH3** annotation), `DoTTransport` (**DoT**, pooled/reused connections), `DoQTransport` (**DoQ**, fresh QUIC connection per query). See [DNS transports](./dns-filtering-and-blocklists.md).

### Backend (Cloudflare + Supabase)

A deliberately minimal, privacy-preserving edge layer.

| Component | Role | Doc |
|---|---|---|
| **`lavasec-api`** (API Worker) | Cloudflare Worker at `api.lavasecurity.app`: serves the public blocklist catalog, runs source sync/publish (admin + cron), accepts anonymous bug reports and help-article feedback, handles authenticated account deletion and App Store entitlement sync, gates passkey recovery, and serves QA probe pixels. `fetch()` router + `scheduled()` cron. | [backend](./backend-and-data.md) |
| **`lavasec-email`** (Email Worker) | Receive-and-forward email worker for `support@`/`hello@`/`jimmy@`/`legal@`. Stores no bodies or attachments; outbound auto-replies are **(In progress)** (code present, gated behind paid Email Sending). | [backend](./backend-and-data.md) |
| **Supabase Postgres** | Account profiles, entitlements, blocklist catalog metadata, encrypted backup envelopes, and service-role-only passkey-recovery / QA-allowlist tables — **all RLS-enabled**. Project `lava-sec`, region `ap-southeast-1`. | [backend](./backend-and-data.md) |
| **Cloudflare R2** (`LAVASEC_R2`) | Object storage for `catalog/latest.json` + `catalog/{version}.json`, the scheduled-sync cursor, and bug-report attachments. Does **not** store third-party blocklist bytes. | [backend](./backend-and-data.md) |
| **Cloudflare D1** (`HELP_FEEDBACK_DB`) | SQLite-at-edge store for anonymous help-article feedback votes. | [backend](./backend-and-data.md) |

### Third-party blocklist sources

Lava does not host blocklist data. The catalog publishes only metadata plus the upstream `source_url` for each list (**source-url-only**); the app fetches each list directly from its origin (e.g. HaGeZi, OISD, Block List Project, Phishing.Database) and parses it on-device. See [blocklist catalog](./dns-filtering-and-blocklists.md).

---

## Component & data-flow diagram

```
                            THIRD-PARTY BLOCKLIST ORIGINS
                     (HaGeZi, OISD, Block List Project, Phishing.Database …)
                                          │
                    direct upstream fetch │ (metadata says where; bytes come from origin)
                    + SHA-256 verify      │           ▲
                    + on-device parse     │           │ admin sync / 6h cron
                                          ▼           │ normalize → hash → metadata only
┌───────────────────────────── iOS DEVICE ──────────┼─────┐     ┌──── CLOUDFLARE ─────────────┐
│                                                    │     │     │                              │
│  ┌────────────┐   provider msg    ┌─────────────┐  │     │     │  lavasec-api (API Worker)    │
│  │  iOS app   │◄────────────────► │ packet-tunnel│ │     │     │  api.lavasecurity.app        │
│  │ AppViewModel│  pause/resume/    │  extension   │─┼─────┼────►│  GET /v1/catalog ───────┐    │
│  │            │   reload          │ LavaSec      │  │catalog    │  (R2 JSON, metadata)    │    │
│  │  widget ───┼── App Group ──────┤  Tunnel      │  │fetch│     │  POST /v1/bug-reports   │    │
│  └─────┬──────┘  group.com.lavasec└──────┬───────┘  │     │     │  /v1/account/* , passkey│    │
│        │                                 │          │     │     └──────┬─────────┬────────┘    │
│        │ sign-in (id_token grant)        │ allowed  │     │            │ R2      │ service-role │
│        │ encrypted backup (ciphertext)   │ DNS only │     │     ┌──────▼──┐  ┌───▼──────────┐  │
│        │                                 ▼ DoH/DoT/ │     │     │   R2    │  │  Supabase    │  │
│        │                         ┌───────────────┐  │ DoQ │     │ catalog │  │  Postgres    │  │
│        │                         │ upstream DNS  │  │     │     │  + sync │  │  (RLS on all │  │
│        │                         │  resolver     │  │     │     │  cursor │  │   tables)    │  │
│        │                         └───────────────┘  │     │     │ + attach│  │ user_backups │  │
│        │                                            │     │     └─────────┘  │ entitlements │  │
│        └───────────────── HTTPS ────────────────────┼─────┼─────────────────►│ profiles …   │  │
│                                                     │     │     ┌─────────┐  └──────────────┘  │
│  ✗ routine DNS queries  ✗ browsing history          │     │     │   D1    │  (help feedback)   │
│  ✗ per-domain telemetry  ✗ plaintext settings       │     │     └─────────┘                    │
└─────────────────────────────────────────────────────┘     └──────────────────────────────────┘

   Local-only, never leaves device ──────┘          Server-stored (metadata / ciphertext only) ─┘
```

The dotted line down the middle of the device box is the trust boundary: everything to its left stays on the device. The only things that cross to Cloudflare/Supabase are catalog reads, account auth tokens, and opaque backup ciphertext — never the DNS queries themselves.

---

## Data flows

### 1. DNS query path (local, hot path)

This is the path that runs for every DNS lookup on the device. It never touches Lava's servers.

1. The OS routes the device's DNS through the **packet tunnel** (`PacketTunnelProvider` / `LavaSecTunnel`).
2. The tunnel parses the DNS packet and extracts the queried domain.
3. It evaluates the domain against the memory-mapped `CompactFilterSnapshot` using fixed precedence — **guardrail (block) > allowlist (allow) > blocklist (block) > default-allow**. Guardrails cannot be overridden by the user allowlist.
4. **Blocked:** the tunnel answers locally; nothing is forwarded.
5. **Allowed:** the tunnel forwards the query to the selected upstream resolver over the configured transport — plain DNS (default: Google), **DoH** (with **DoH3** preference), **DoT** (pooled connections), or **DoQ** (custom stamp/URL only, fresh QUIC connection per query). An in-memory response cache, in-flight query coalescing, and a reused UDP socket per upstream keep the path fast.

Lava's backend is not in this loop. Routine DNS queries, browsing history, and per-domain telemetry never leave the device. See the [DNS filtering engine](./dns-filtering-and-blocklists.md) and [DNS transports](./dns-filtering-and-blocklists.md).

### 2. Catalog fetch (list distribution)

How the device learns which blocklists exist and gets their contents — without Lava ever serving list bytes.

1. The app calls `GET /v1/catalog` on the API Worker, which returns `catalog/latest.json` from R2 (`schema_version` 2). The document lists `sources[]` and always-on `guardrails[]`, each entry carrying `id`, `source_url`, `accepted_source_hashes`, `parse_format`, `license_name`, and `entry_count` — **metadata only**.
2. For each enabled source, the app fetches the list **directly from its upstream `source_url`** (`BlocklistCatalogSync`), not from Lava.
3. The app verifies the downloaded bytes against the catalog's non-empty accepted-hash allowlist and **fails closed** (cached last-good, or reject) on mismatch.
4. `BlocklistParser` normalizes the list (hosts/adblock/plain/dnsmasq), drops invalid/comment/IP lines and protected domains (Apple, iCloud, Lava, Supabase, Google, GitHub, …), and dedups, capped at 1M rules per list.
5. `FilterSnapshotPreparationService` merges/dedups the union and enforces the budget at compile time — device cap first (~3.26M rules), then tier cap (Free 500K / Plus 2M).

On the server side, the catalog is refreshed by an admin `POST /v1/admin/blocklists/sync` or a 6-hour cron that fetches each `source_url`, normalizes it only to compute `entry_count`/hashes, records a `blocklist_versions` row, and republishes the catalog JSON to R2 — **never storing the list bytes** (`raw_r2_key`/`normalized_r2_key` are forced NULL). See the [blocklist catalog](./dns-filtering-and-blocklists.md) and [backend](./backend-and-data.md).

### 3. Account / backup sync (optional, zero-knowledge)

Protection works with no login. An account exists only to authenticate **zero-knowledge backup** of your settings.

1. **Sign-in:** the user signs in with Apple or Google. `AccountAuthService` obtains a provider ID token + a SHA-256-hashed nonce, and `SupabaseIDTokenAuth` exchanges it via Supabase Auth's native id_token grant (`grant_type=id_token`). Only the resulting Supabase session is persisted, in a device-only Keychain (`GenericKeychainStore`, `AfterFirstUnlockThisDeviceOnly`). Email/password sign-in is **(Dropped)**.
2. **Encrypt on device:** `BackupConfigurationPayload` (the only plaintext — blocklist IDs, allow/block domains, resolver settings, prefs) is sealed by `ZeroKnowledgeBackupEnvelope` with AES-256-GCM under a random payload key, which is wrapped into PBKDF2-HMAC-SHA256 key slots (device secret, assisted-recovery phrase, optional passkey).
3. **Upload ciphertext:** `SupabaseBackupSyncService` upserts the `user_backups` row over PostgREST. The server receives only ciphertext, envelope metadata, the server recovery share, and timestamps — never plaintext, the recovery phrase, or any key. RLS scopes the row to `auth.uid()`.
4. **Restore:** on a new device the envelope is fetched and decrypted **locally** via one of three unlock modes — This Device (device secret), Recovery phrase (8 CSPRNG tokens combined with the server recovery share via SHA-256), or Passkey.

**Passkey recovery is server-gated, not zero-knowledge:** the API Worker releases a stored `recovery_secret` after a successful WebAuthn assertion (RP id `lavasecurity.app`). See [accounts & backup](./accounts-and-backup.md).

---

## Trust boundaries & privacy-preserving design

The device is the trust boundary. Filtering is local; the backend is designed so it cannot receive the sensitive data even if it wanted to.

### What never leaves the device

- **Routine DNS queries, browsing history, and per-domain telemetry.** Filtering happens entirely in the packet tunnel; there are no passive telemetry tables. Bug reports are anonymous, user-triggered, and field-allowlisted (`has_account_info:false`).
- **Plaintext settings.** The backup payload is encrypted on-device before any upload; the server sees only ciphertext.
- **Backup decryption material.** The device secret, passkey credential ID, and recovery code live in a device-only Keychain (`AfterFirstUnlockThisDeviceOnly`), not synchronizable iCloud Keychain. The recovery phrase is never sent to the server.
- **Custom Plus blocklist URLs.** Custom Pi-hole HTTPS list URLs are fetched directly on-device, never proxied through or logged to Lava, and are excluded from bug-report payloads.

### Source-url-only

Lava publishes only catalog **metadata plus the upstream `source_url`**; the app fetches each list directly from its origin and parses it on-device. Lava never hosts, mirrors, or serves third-party blocklist bytes from R2 — `source_url_only` is the only allowed `redistribution_mode`, enforced by a DB CHECK constraint and a CI guardrail (`scripts/check-gpl-blocklist-distribution.sh`). The earlier R2 raw-mirror approach was built then **(Dropped)** in favor of this model. This keeps Lava a local filtering engine rather than a redistributor, and means the backend never sees which lists a given device actually uses.

### Zero-knowledge backup

Optional account backup is encrypted entirely on-device (AES-256-GCM under a random payload key, wrapped into PBKDF2-HMAC-SHA256 key slots). Supabase stores only opaque ciphertext + non-secret envelope metadata (KDF params, salts, nonces), capped at ~256 KiB — never plaintext, the recovery phrase, or any decryption key. **Defense in depth at the DB layer:** RLS is enabled on every public table; `profiles`/`user_settings`/`entitlements`/`user_backups` allow only `auth.uid()=owner`, and sensitive tables (`bug_reports`, `mirror_events`, `backup_passkey_recovery`, `backup_passkey_challenges`, `qa_developers`) `REVOKE ALL` from anon/authenticated and are reachable only by the Worker's service role.

The one explicit exception is **passkey recovery**, which is **server-gated, not zero-knowledge**: a system with service-role access to both `user_backups` and `backup_passkey_recovery` could recover a passkey-protected backup. This is called out deliberately rather than advertised as zero-knowledge. See [accounts & backup](./accounts-and-backup.md).

---

## Status legend

| Status | Meaning |
|---|---|
| **Implemented** | Production call sites exist and ship. |
| **(In progress)** | Some code present but not fully wired, not on `main`, or pending QA/review. |
| **(Planned)** | Plan only, little or no code (e.g. URL-level protection, the Android app). |
| **(Dropped)** | Built-then-reverted or cancelled (e.g. R2 raw-mirror, email sign-in, the backup password slot). |

## Per-component docs

- [iOS client](./ios-client.md) — app, packet-tunnel extension, widget, App Group, VPN lifecycle.
- [DNS filtering engine](./dns-filtering-and-blocklists.md) — packet parsing, compiled snapshot, decision precedence, memory budget.
- [DNS transports](./dns-filtering-and-blocklists.md) — DoH/DoH3, DoT, DoQ, resolver presets and DNS stamps.
- [Blocklist catalog](./dns-filtering-and-blocklists.md) — source-url-only model, hashes, parsing, filter-rules budget.
- [Backend](./backend-and-data.md) — `lavasec-api`, `lavasec-email`, Supabase, R2, D1.
- [Accounts & backup](./accounts-and-backup.md) — sign-in, zero-knowledge envelope, passkey recovery, account deletion.
