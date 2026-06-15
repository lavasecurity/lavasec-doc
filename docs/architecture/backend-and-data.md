# Backend & Data

This document is for backend engineers working on Lava Security's edge layer. It covers the two Cloudflare Workers, the Supabase Postgres schema (tables, RLS, auth), the public API surface at `api.lavasecurity.app`, config and deployment, and the server-side enforcement that keeps blocklist distribution **source-url-only**.

The whole backend is deliberately minimal and privacy-preserving. It exists to publish a blocklist *catalog* (metadata plus the upstream `source_url`), authenticate an optional account used only for an encrypted-backup sync, accept anonymous bug reports and help-article votes, and gate passkey recovery. It is built so that it **never receives your routine DNS queries, browsing history, per-domain telemetry, or any third-party blocklist bytes** — DNS filtering happens locally on the device (see [iOS client](./ios-client.md) and [DNS filtering & blocklists](./dns-filtering-and-blocklists.md)).

> Privacy promise: DNS filtering happens locally on your device; Lava never receives your routine DNS queries, browsing history, or per-domain telemetry, and any optional account backup is end-to-end encrypted so Lava can only ever store ciphertext.

## Topology at a glance

| Layer | What it is | Where |
|---|---|---|
| `lavasec-api` (API Worker) | TypeScript Cloudflare Worker: catalog reads, source sync + catalog publish, bug reports, help feedback, account deletion, entitlement sync, QA-access checks, passkey recovery, QA probe pixels | `server/backend/worker/src/index.ts` |
| `lavasec-email` (Email Worker) | Receive-and-forward Cloudflare Email Worker; stores no bodies or attachments | `server/backend/email-worker/src/index.ts`, `src/email-service.ts` |
| Supabase Postgres | Accounts, entitlements, catalog metadata, encrypted backup envelopes, service-role-only recovery/QA tables — all RLS-enabled | `server/supabase/migrations/*.sql` |
| Cloudflare R2 (`LAVASEC_R2`) | Catalog JSON snapshots, scheduled-sync cursor, bug-report attachments. Buckets `lavasec-prod` / `lavasec-dev` | bound in `server/backend/worker/src/index.ts` |
| Cloudflare D1 (`HELP_FEEDBACK_DB`) | SQLite-at-edge store for anonymous help-article votes | `server/backend/worker/migrations/0001_help_article_feedback.sql` |

Hostnames are kept strictly separate (`server/backend/worker/README.md:110-122`):

```text
lavasecurity.app/*              -> Cloudflare Pages public site
api.lavasecurity.app/*          -> the API Worker
*.qa-probe.lavasecurity.app/*   -> the API Worker's QA probe handler
```

The workers.dev fallback URL is `https://lavasec-api.lavasec.workers.dev`. Root `lavasecurity.app` must **not** be pointed at the Worker.

---

## 1. Cloudflare Workers

### 1.1 API Worker (`lavasec-api`)

The API Worker is a single entrypoint with a `fetch()` router and a `scheduled()` cron handler (`server/backend/worker/src/index.ts:280-301`). Its `Env` interface (`:12-23`) declares the bindings and config it consumes:

- `LAVASEC_R2` — R2 bucket (catalog snapshots, sync cursor, attachments).
- `HELP_FEEDBACK_DB?` — optional D1 database for help feedback.
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — Supabase REST access via the service role.
- `ADMIN_API_KEY` — shared secret for admin endpoints.
- `PUBLIC_API_ORIGIN`, `PUBLIC_CATALOG_CACHE_SECONDS`, `MAX_BUG_REPORT_BYTES`, `MAX_ATTACHMENT_BYTES`, `ACCOUNT_DELETION_AUDIT_ENABLED` — non-secret tunables.

Supabase is reached over its PostgREST REST API using the service-role key; the Worker is the only mediator for service-role-only tables.

#### Catalog reads (public)

| Endpoint | Behavior |
|---|---|
| `GET /v1/catalog` | Serves the R2 object `catalog/latest.json`. |
| `GET /v1/catalog/:version` | Serves `catalog/{version}.json`. |

Both stream the R2 object directly with `Cache-Control: public, max-age=<PUBLIC_CATALOG_CACHE_SECONDS>` (default `300` seconds) and 404 when the object is absent (`getCatalog` `:405-419`). The catalog is a `CatalogDocument` with `schema_version: 2`, a `catalog_version`, `generated_at`, and two arrays of `CatalogEntry` — `sources[]` (user-selectable blocklists) and `guardrails[]` (always-on, backend-curated safety rules) (`:102-139`). Each entry carries `id`, `name`, `category`, `risk_level`, `source_url`, `redistribution_mode`, `parse_format`, license/notice URLs, `version_id`, `entry_count`, `byte_size`, `source_hash`, `accepted_source_hashes`, and `normalized_hash` (`formatCatalogEntry` `:556-588`). The iOS app fetches each list directly from `source_url` and parses it on-device; Lava never serves the list bytes.

#### Blocklist source sync + catalog publish (admin)

| Endpoint | Behavior |
|---|---|
| `POST /v1/admin/blocklists/sync` | Fetches each upstream `source_url`, normalizes domains, records a `blocklist_versions` row, and republishes `catalog/latest.json` + `catalog/{version}.json` to R2. |
| `POST /v1/admin/catalog/publish` | Recomputes and republishes the catalog from current published versions. |

Both require the header `X-Lava-Admin-Key` to match the `ADMIN_API_KEY` secret (`requireAdmin`; routes `:390-400`). Normalization parses hosts / adblock / plain formats, strips `PROTECTED_SUFFIXES` (Apple, iCloud, mzstatic/itunes/apps, `lavasecurity.com`/`lavasecurity.app`/`api.lavasecurity.app`/`lavasec.app`, `supabase.co`, `cloudflare.com`, Google/`accounts.google.com`, GitHub) so filtering can never block Lava, identity, or update infrastructure (`:172-187`), and enforces a `MAX_BLOCKLIST_BYTES` of 25 MiB upstream cap and a `MAX_NORMALIZED_DOMAINS` cap of 500,000 (`:189-191`). It computes SHA-256 `source_hash` and `normalized_hash`. Sync is idempotent: when the upstream `source_hash` is unchanged the existing version is reused and the catalog is not republished. Each sync/publish writes an audit row to `mirror_events` (`recordSourceEvent`).

#### Scheduled catalog sync (cron)

A cron trigger `"17 */6 * * *"` (every 6 hours) drives `scheduled() -> syncScheduledCatalog` (`:298-322`; trigger in `wrangler.toml.example:35-36`). It round-robins **one source per tick** using an R2-stored cursor at `catalog/scheduled-sync-cursor.json` (`SCHEDULED_SYNC_CURSOR_KEY :193`), so a 6-hour tick re-syncs only the next source and avoids churn.

#### Anonymous bug reports (public)

| Endpoint | Behavior |
|---|---|
| `POST /v1/bug-reports` | Inserts an anonymous report via the service role into `bug_reports`. |
| `PUT /v1/bug-reports/:report_id/attachment` | Stores one file in R2 under `bug-reports/{id}/attachment`. |

Reports are user-triggered and anonymous: account identifiers are stripped (`has_account_info: false`), only a known allowlist of scalar debug fields (`BUG_REPORT_DEBUG_DETAIL_KEYS`, `:211-267`) is accepted, and `recent_dns_events` is accepted **only** when the client sends `include_recent_dns_events: true` (`createBugReport :590-685`). Body size is capped by `MAX_BUG_REPORT_BYTES` (default 64 KiB) and attachments by `MAX_ATTACHMENT_BYTES` (default 1 MiB). No login is required; default fields are app/build/iOS version, device family, locale, VPN status, resolver preset, network kind, catalog version, enabled list IDs, tunnel health counters, and the user's written description (`server/backend/worker/README.md:124-142`).

> **(Planned)** Bug-report hardening — rejecting `recent_dns_events` entirely, signed short-lived attachment-upload tokens, and blocking attachment-replacement uploads — is a P0 plan still in the backlog (`plans/backlog/2026-05-25-bug-report-data-minimization-plan.md`). The current Worker still accepts `recent_dns_events` behind the client flag and allows attachment `PUT` without a signed token.

#### Help-article feedback (public)

`POST /v1/help-feedback` writes an anonymous vote to Cloudflare **D1** (`lavasec-help-feedback`, table `help_article_feedback`) (`createHelpFeedback :687-728`). `vote` is constrained to `helpful` / `not_helpful` and `locale` to `en` / `ja` / `zh-Hant` / `zh-Hans` / `de` / `fr` (`:203-204`). The response is only `{ "saved": true }`; totals are never displayed.

#### Account & entitlements (authenticated)

All authenticated endpoints require the user's Supabase access token in `Authorization: Bearer <token>`, which the Worker validates against Supabase Auth.

| Endpoint | Behavior |
|---|---|
| `POST /v1/account/delete` | Deletes the user's `bug_reports` (and their R2 attachments), `user_backups`, `entitlements`, `user_settings`, and `profiles` rows, then deletes the Supabase Auth user with the service-role key; returns `{ deleted: true, providers }` (`deleteAccount :762-810`). |
| `GET /v1/account/qa-access` | Returns `{ is_developer }` by checking the service-role-only `qa_developers` allowlist (`accountQAAccess` / `isAccountQADeveloper :421-425, :489-496`). |
| `POST /v1/account/entitlements/app-store-sync` | Upserts an `entitlements` row keyed by `user_id` (plan `lava_security_plus`, source `app-store-local`) (`syncAppStoreEntitlement :427-487`). |

Entitlement sync currently records `verification_status: "client_verified_storekit"` — the StoreKit transaction is **client/StoreKit-verified, not yet verified server-side against Apple's App Store Server API**. The signed JWS and `original_transaction_id` are stored for later server-side verification (`:449-456`). Note that `Lava Security Plus` never bypasses guardrails — the tunnel ignores `isPaid`; entitlement state here only governs paid customization. See [accounts & backup](./accounts-and-backup.md).

#### Passkey recovery (authenticated)

Six endpoints implement WebAuthn-gated recovery for encrypted backups (`:365-383`):

```text
POST /v1/backup/passkeys/registration-challenge
POST /v1/backup/passkeys/register
POST /v1/backup/passkeys/recovery-secret
POST /v1/backup/passkeys/assertion-challenge
POST /v1/backup/passkeys/recover
```

They issue and consume short-lived WebAuthn challenges (5-minute TTL, RP id `lavasecurity.app`, expected origin `https://lavasecurity.app`) and verify registration/assertion via `@simplewebauthn/server` (`:194-196`, `register/recover :829-963`). On success the Worker **releases a stored `recovery_secret`** from `backup_passkey_recovery`, which the app uses to unwrap the `.passkey` key slot.

This is **server-gated recovery, not zero-knowledge.** Because common passkey providers do not expose a portable decryption secret, the Worker holds a recovery secret; a system with service-role access to *both* `user_backups` and `backup_passkey_recovery` could recover passkey-protected backups. That table is service-role-only and must never be exposed to anon or authenticated PostgREST roles (`server/supabase/README.md:40`; `server/backend/worker/README.md:97`). Call this path **server-gated**, never zero-knowledge.

#### QA probe pixels (public)

`GET /pixel.png` is served only on the four fixed hosts `allowed` / `blocked` / `exception` / `guardrail`.`qa-probe.lavasecurity.app` (`QA_PROBE_HOSTS :205-210`, `getQAProbePixel :498-515`). It returns a tiny `no-store` 1×1 PNG and **does not write probe requests to Supabase or R2** — it exists purely so on-device QA can confirm allow/block/exception/guardrail behavior end-to-end.

`GET /healthz` returns `{ ok: true, service: "lavasec-api" }`.

### 1.2 Email Worker (`lavasec-email`)

`lavasec-email` is **receive-and-forward only** (`server/backend/email-worker/src/email-service.ts`, `index.ts:23-26`). It routes `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` to a single verified operator inbox (`SUPPORT_FORWARD_TO` secret), rejects unknown recipients and `noreply@` (outbound-only, inbound dropped), and enforces a 10 MiB inbound cap. It **never stores email bodies or attachments**; there is no catch-all mailbox (`server/backend/email-worker/README.md:6-17`).

Outbound support auto-reply code (`buildSupportAutoReply` / `sendAutoReply` via the `EMAIL` send binding) exists in the worker, but is **(In progress)** — auto-replies are deferred until paid Cloudflare Email Sending is enabled (`README.md:17`; backlog plan `plans/backlog/2026-05-17-email-sending-auto-replies-plan.md`, status Todo). Treat outbound as not live in production.

---

## 2. Supabase (schema, RLS, auth)

Project `lava-sec`, ref `yhuziqpmfghttfkzxnsx`, region `ap-southeast-1` (`server/supabase/README.md:1-8`). Migrations live in `server/supabase/migrations/`.

### 2.1 Key tables

| Table | Purpose | Defined in |
|---|---|---|
| `profiles` | Optional account profile (display name, preferred provider), 1:1 with `auth.users` | `20260516034033_backend_core.sql:25-32` |
| `user_settings` | **Legacy/plaintext-shaped** sync table from the initial foundation — *do not use for backup* | `:38-54` |
| `entitlements` | Subscription/entitlement state (plan, active, source, original transaction id, raw status) | `:87-98` |
| `blocklist_sources` | Curated source catalog metadata: `source_url`, license, category, risk, parser, `redistribution_mode`, counsel approval | `:104-132` |
| `blocklist_versions` | Per-sync version: hashes, `entry_count`, `byte_size`, validation status; `raw_r2_key`/`normalized_r2_key` now nullable and forced NULL | `:138-156`, `20260525000000_add_blocklist_distribution_mode.sql:15-22` |
| `mirror_events` | Audit log of catalog sync/publish events (`event_type`, `status`, `details` jsonb) | `:164-173` |
| `bug_reports` | Anonymous user-triggered reports + attachment key + triage status | `:175-202` |
| `user_backups` | One zero-knowledge encrypted backup envelope per user (ciphertext + non-secret metadata) | `20260518000000_zero_knowledge_backups.sql:7-23` |
| `backup_passkey_recovery` | Service-role-only WebAuthn credentials + server-gated `recovery_secret` | `20260605010000_backup_passkey_recovery.sql:7-22` |
| `backup_passkey_challenges` | Short-lived service-role-only WebAuthn challenges | `:36-45` |
| `qa_developers` | Service-role-only allowlist of account UUIDs that get in-app QA controls | `20260608000000_qa_developers_allowlist.sql` |

`user_settings` is explicitly a legacy table: it must **not** be used for zero-knowledge backup and must **not** be extended with backup payload fields (`README.md:53, :87`). The actual data-minimized backup payload lives only inside the encrypted envelope on-device (`BackupConfigurationPayload`).

### 2.2 Zero-knowledge backup storage

`user_backups` (`20260518000000_zero_knowledge_backups.sql`) stores only opaque client `ciphertext` plus non-secret `metadata` (KDF params, salts, nonces, key-slot labels, client schema hints) and `ciphertext_byte_size`. Table/column comments and the `server/supabase/README.md` both state the DB **never stores plaintext settings, domains, backup passwords, recovery phrases, or keys** (`:25-30`). A later migration caps envelope size to prevent accidental uploads of diagnostics, full blocklists, or plaintext: 256 KiB declared ciphertext bytes (`262144`), 349528 encoded characters, and 32 KiB metadata (`20260605000000_tighten_backup_envelope_constraints.sql:7-17`; `README.md:42`). Normal envelopes are ~4 KiB.

The client-side crypto (`ZeroKnowledgeBackupEnvelope` — AES-256-GCM payload key wrapped into PBKDF2-HMAC-SHA256 key slots) is documented in [accounts & backup](./accounts-and-backup.md); this doc covers only what the server stores.

### 2.3 Row Level Security

RLS is enabled on **every** public table.

- **Owner-scoped** (`auth.uid() = owner`): `profiles`, `user_settings`, `entitlements`, and `user_backups` allow a signed-in user to access only their own row (`20260516034033_backend_core.sql:216-272`; `user_backups` policies `20260518000000_zero_knowledge_backups.sql:36-63`). `user_backups` grants `select/insert/update/delete` to `authenticated`, each gated on `auth.uid() = user_id`.
- **Anon-readable only when published**: `blocklist_sources` is readable by `anon` and `authenticated` only when `status in ('sync', 'nosync')`; `blocklist_versions` only when `validation_status = 'published'` (`:262-272`).
- **Service-role only (deny anon + authenticated)**: `bug_reports` and `mirror_events` get explicit no-direct-access policies (`20260516034136_backend_core_advisor_fixes.sql:84-96`). `backup_passkey_recovery`, `backup_passkey_challenges`, and `qa_developers` have RLS enabled and `REVOKE ALL` from anon + authenticated (`20260605010000_backup_passkey_recovery.sql:33-34, :50-51`; `20260608000000_qa_developers_allowlist.sql`). These are reachable only through the Worker's service-role key.

This is defense in depth: anon/authenticated PostgREST roles cannot read recovery secrets, bug reports, sync audit logs, or the QA allowlist. Bug reports are inserted *through the Worker* with the service role, never via direct unauthenticated DB writes (`README.md:32`).

Post-migration checks to run after applying migrations (`README.md:78-89`): run Supabase security advisors; confirm RLS is on every public table; confirm anon cannot read `bug_reports`; confirm anon reads only published blocklist metadata; confirm a user can CRUD only their own `user_backups`; confirm `user_settings` is unused for backup; confirm anon/authenticated cannot touch the passkey tables.

### 2.4 Auth

Accounts are optional — protection works with no login. Auth runs through **Supabase Auth's native ID-token grant** (`grant_type=id_token`) for Apple and Google. The iOS app obtains a provider ID token plus a SHA-256-hashed nonce locally, exchanges it for a Supabase session, and stores only that session in a device-only Keychain (`server/supabase/README.md:67-76`). Email/password sign-in is **(Dropped)** — Apple + Google only. Provider/auth-helper details (`SupabaseIDTokenAuth`, `AccountAuthService`) live in [accounts & backup](./accounts-and-backup.md).

The `handle_new_user()` trigger seeds a `profiles` row and a `user_settings` row on auth-user creation (`20260516034033_backend_core.sql:56-85`).

### 2.5 Catalog seed data

`blocklist_sources` is seeded across migrations with HaGeZi (multi-pro-mini / light / normal / pro / pro-plus-mini / ultimate-mini), OISD (big / small), the AdGuard DNS filter, blocklistproject-* and phishing-database-active sources. `20260516034033_backend_core.sql:274-344` seeds only the two launch GPL sources (`hagezi-multi-pro-mini`, `oisd-big`); the broader inventory comes from later seed migrations — `20260516040325_add_open_source_blocklists.sql` (AdGuard, blocklistproject-*, phishing-database-active), `20260517133000_add_hagezi_phase1_catalog.sql` (the additional HaGeZi variants), and `20260526000000_low_risk_blocklist_sources.sql`. GPL-licensed sources are gated to `hagezi-` / `oisd-` prefixes for launch by `isAllowedLaunchGPLSource` (`server/backend/worker/src/index.ts:539-545`).

---

## 3. API surface (`api.lavasecurity.app/v1/...`)

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /healthz` | none | Liveness. |
| `GET /pixel.png` (on the 4 `*.qa-probe` hosts) | none | QA probe pixel (no-store, never logged). |
| `GET /v1/catalog` | none | Latest catalog (`catalog/latest.json`). |
| `GET /v1/catalog/:version` | none | A specific catalog version. |
| `POST /v1/bug-reports` | none | Anonymous bug report. |
| `PUT /v1/bug-reports/:report_id/attachment` | none | Upload one debug attachment to R2. |
| `POST /v1/help-feedback` | none | Anonymous help-article vote (D1). |
| `POST /v1/account/delete` | Bearer | Full account + data deletion. |
| `GET /v1/account/qa-access` | Bearer | `{ is_developer }` from the QA allowlist. |
| `POST /v1/account/entitlements/app-store-sync` | Bearer | Upsert Plus entitlement (client-verified StoreKit). |
| `POST /v1/backup/passkeys/registration-challenge` | Bearer | Begin passkey registration. |
| `POST /v1/backup/passkeys/register` | Bearer | Verify + store passkey credential. |
| `POST /v1/backup/passkeys/recovery-secret` | Bearer | Store the server-gated recovery secret. |
| `POST /v1/backup/passkeys/assertion-challenge` | Bearer | Begin passkey assertion. |
| `POST /v1/backup/passkeys/recover` | Bearer | Verify assertion + release recovery secret. |
| `POST /v1/admin/blocklists/sync` | `X-Lava-Admin-Key` | Sync sources + republish catalog. |
| `POST /v1/admin/catalog/publish` | `X-Lava-Admin-Key` | Republish catalog from published versions. |

`OPTIONS` returns a 204 CORS preflight; unmatched routes return `{ "error": "Not found" }` with status 404 (`server/backend/worker/src/index.ts:282-284, :402`).

---

## 4. Config & deployment

### 4.1 API Worker

Config lives in `wrangler.toml`, copied from `server/backend/worker/wrangler.toml.example` (the real file is gitignored when it carries environment-specific values). Key parts:

- **`name = "lavasec-api"`**, `main = "src/index.ts"`, `compatibility_flags = ["nodejs_compat"]`.
- **`[vars]`** (non-secret): `SUPABASE_URL`, `PUBLIC_API_ORIGIN = "https://api.lavasecurity.app"`, `PUBLIC_CATALOG_CACHE_SECONDS = "300"`, `MAX_BUG_REPORT_BYTES = "65536"`, `MAX_ATTACHMENT_BYTES = "1048576"`, `ACCOUNT_DELETION_AUDIT_ENABLED = "false"` (`wrangler.toml.example:15-21`).
- **R2 binding** `LAVASEC_R2` → `lavasec-prod` (preview `lavasec-dev`) (`:24-27`).
- **D1 binding** `HELP_FEEDBACK_DB` → `lavasec-help-feedback`; the `database_id` / `preview_database_id` are `REPLACE_WITH_*` placeholders because the real `wrangler.toml` is gitignored (`:29-33`).
- **Cron** `crons = ["17 */6 * * *"]` (`:35-36`).
- **Secrets** set out-of-band, never in `[vars]`: `wrangler secret put SUPABASE_SERVICE_ROLE_KEY` and `wrangler secret put ADMIN_API_KEY` (`:38-40`). Local secrets go in `.dev.vars`.

Setup and deploy (`server/backend/worker/README.md:36-70`): enable R2 + D1, create `lavasec-dev` / `lavasec-prod` buckets, copy the wrangler example, create the D1 database and apply its migration (`wrangler d1 migrations apply lavasec-help-feedback --local|--remote`), set both secrets, then `npm run dev` / `npm run deploy`.

### 4.2 Email Worker

Copy `server/backend/email-worker/wrangler.toml.example` to `wrangler.toml`, set the forward target with `npx wrangler secret put SUPPORT_FORWARD_TO` (a verified Cloudflare Email Routing destination), then `npm test` / `npm run check` / `npm run deploy`. Configure Cloudflare routing rules for the four inbound addresses (`server/backend/email-worker/README.md:19-44`).

### 4.3 Supabase

Apply the SQL in `server/supabase/migrations/` in order, then run the post-migration RLS checks in §2.3.

---

## 5. Server-side source-url-only enforcement

**source-url-only** is the live, and only allowed, redistribution model: Lava publishes catalog metadata plus the upstream `source_url`, and the app fetches and parses each list on-device. Lava never hosts, mirrors, or serves third-party blocklist bytes from R2. This is enforced at three layers:

1. **Database constraint.** `blocklist_sources.redistribution_mode` has a CHECK that allows only the single value `'source_url_only'` (`20260516034033_backend_core.sql:130`; reasserted in `20260525000000_add_blocklist_distribution_mode.sql:8-13`). The same migration makes `blocklist_versions.raw_r2_key` / `normalized_r2_key` nullable and **forces every existing row's R2 keys to NULL** (`:15-22`), so no list bytes are referenced from R2.

2. **Worker publish/sync logic.** `isPublicBlocklistSource` requires `redistribution_mode === "source_url_only"` (plus a published status and the GPL-launch gate) before a source is exposed in the catalog (`server/backend/worker/src/index.ts:530-533`); `isSyncableLaunchSource` applies the same gate to syncing (`:547-550`). `formatCatalogEntry` emits only metadata, `source_url`, hashes, and license info — never bytes (`:556-588`).

3. **Normalization stays transient.** During sync the Worker fetches upstream bytes only to compute hashes and counts, applies `PROTECTED_SUFFIXES` stripping and the 25 MiB / 500K caps, and discards them; the normalized list is **not** persisted to R2.

The earlier GPL raw-R2 mirror approach (storing/serving third-party list bytes from R2) was built and then **(Dropped)** in favor of source-url-only on 2026-05-25 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, "Superseded … by the source-url-only implementation"). The rationale is GPLv3 redistribution / App Store compliance and privacy: Lava avoids becoming a redistributor of third-party blocklist artifacts. See the [DNS filtering & blocklists](./dns-filtering-and-blocklists.md) and [iOS client](./ios-client.md) docs for how the device consumes the catalog and parses each `source_url`.

---

## Source references

Workers: `server/backend/worker/src/index.ts`, `server/backend/worker/README.md`, `server/backend/worker/wrangler.toml.example`, `server/backend/worker/migrations/0001_help_article_feedback.sql`, `server/backend/email-worker/src/index.ts`, `server/backend/email-worker/src/email-service.ts`, `server/backend/email-worker/README.md`.

Supabase: `server/supabase/README.md`, `server/supabase/migrations/20260516034033_backend_core.sql`, `20260516034136_backend_core_advisor_fixes.sql`, `20260518000000_zero_knowledge_backups.sql`, `20260525000000_add_blocklist_distribution_mode.sql`, `20260605000000_tighten_backup_envelope_constraints.sql`, `20260605010000_backup_passkey_recovery.sql`, `20260608000000_qa_developers_allowlist.sql`.

Plans: `plans/implemented/2026-05-16-supabase-r2-backend-plan.md`, `plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, `plans/implemented/2026-05-18-zero-knowledge-account-backup-plan.md`, `plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`, `plans/backlog/2026-05-25-bug-report-data-minimization-plan.md`, `plans/backlog/2026-05-17-email-sending-auto-replies-plan.md`.
