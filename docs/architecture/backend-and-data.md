---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-infra, lavasec-ios]
grounded_at: {lavasec-infra: "5f425af", lavasec-ios: "1fbab70"}
---

# Backend & Data

> **Audience:** backend engineers. **Scope:** the server tier — the two Cloudflare Workers, the Supabase Postgres schema/RLS/auth, the Cloudflare R2 and D1 stores, the full HTTP API surface, config & deploy, and how source-url-only is enforced on the server.
>
> **Authoritative reference:** when a plan and the code disagree, **code wins** — divergences are called out inline. Status labels use the doc-set legend: **Implemented** (shipped and confirmed in code), **In progress** (partially landed), **Planned** (designed, not built), **Dropped** (rejected or reverted).

## 1. The shape of the backend

The backend is deliberately small and privacy-preserving. It is a metadata-and-account edge, not a filtering service. **All DNS filtering happens on the device; Lava never routes your browsing through its servers and never receives the stream of domains you visit — the backend holds only catalog metadata, an opaque per-user encrypted backup, and anonymized diagnostics you choose to send.** There are no tables for routine DNS queries or per-domain telemetry, and account login is optional and never required for protection.

Everything lives in lavasec-infra under `backend/` and `supabase/` (the server tier is split across two repos: backend code + DB schema in lavasec-infra):

| Component | Role | Location |
|---|---|---|
| **lavasec-api Worker** | Main edge: public catalog reads, admin+cron blocklist sync & catalog publish, anonymous bug reports, help feedback, account deletion, App Store entitlement mirroring, QA probe pixels, account QA-access check, bug-report triage promotion | `lavasec-infra: backend/worker/src/index.ts` |
| **lavasec-email Worker** | Receive-only Cloudflare Email Routing forwarder for `@lavasecurity.app` | `lavasec-infra: backend/email-worker/src/index.ts`, `backend/email-worker/src/email-service.ts` |
| **Supabase Postgres** (a Supabase Postgres project) | Accounts, encrypted backups, catalog metadata, service-role-only tables; RLS on every public table | `lavasec-infra: supabase/migrations/*.sql`, `lavasec-infra: supabase/README.md` |
| **Cloudflare R2** (production / preview buckets) | Catalog snapshots + the sync cursor; **never** third-party blocklist bytes | binding `LAVASEC_R2` in `wrangler.toml`; usage in `src/index.ts` |
| **Cloudflare D1** (a dedicated help-feedback database) | Append-only anonymous help-article feedback votes | binding `HELP_FEEDBACK_DB`; `lavasec-infra: backend/worker/migrations/0001_help_article_feedback.sql` |

The Worker reaches Supabase over PostgREST (`/rest/v1`) and Auth (`/auth/v1`) using `SUPABASE_SERVICE_ROLE_KEY` — there is no Supabase SDK on the server; calls are raw `fetch` via the `supabase()` / `supabaseAuth()` helpers (`lavasec-infra: backend/worker/src/index.ts:1654`/`1680`).

Status: **Implemented**.

## 2. lavasec-api Worker

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, R2 binding `LAVASEC_R2` → the production bucket (preview bucket for staging), D1 binding `HELP_FEEDBACK_DB` → the help-feedback database, and **two cron triggers**: one that fires every 6 hours (blocklist sync + catalog publish) and one that fires every 2 minutes (bug-report triage promotion). It is served at `api.lavasecurity.app`.

### 2.1 API surface

Routing is a flat `route()` dispatcher at `lavasec-infra: backend/worker/src/index.ts:718`. Everything is **Implemented** unless noted.

**Public / unauthenticated**

| Method & path | Handler | Notes |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Serves `catalog/latest.json` from R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Serves `catalog/{version}.json` from R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (default 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anonymous, login-optional; allow-listed debug fields only |
| `POST /v1/help-feedback` | `createHelpFeedback` | Anonymous article vote → **D1**, not Supabase |

> Attachment upload (a former `PUT /v1/bug-reports/:id/attachment` route) has been **removed**; screenshots and extra detail are handled via a human-mediated support channel. The Worker only best-effort deletes any legacy attachment object during account deletion.

**Account (Supabase access token required)**

| Method & path | Handler | Notes |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Validates the user's access token, deletes their rows + any legacy R2 attachment objects, then deletes the Supabase Auth user with the service role |
| `GET /v1/account/qa-access` | `accountQAAccess` | Returns `is_developer` from the service-role-only `qa_developers` allowlist |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Upserts an `entitlements` row (plan `lava_security_plus`) from a client-verified StoreKit JWS |

> **No `/v1/backup` routes.** Passkey-assisted backup recovery is now **zero-knowledge** and entirely client-side (see §4.3 and §5); the Worker has no `/v1/backup/*` routes and no WebAuthn/passkey code.

**Admin (`ADMIN_API_KEY` via `requireAdmin`)**

| Method & path | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Admin HTTP endpoints are `ADMIN_API_KEY`-gated. The scheduled (cron) sync path does **not** call these HTTP routes — it invokes the sync logic (`syncBlocklistSources`) directly inside the `scheduled` handler.

**QA probe hosts** — requests to the four `*.qa-probe.lavasecurity.app` hosts (`allowed`/`blocked`/`exception`/`guardrail`) are short-circuited before routing and return a 1×1 `no-store` PNG via `getQAProbePixel`. These are not written to Supabase or R2.

### 2.2 Bindings & cron

- **R2 (`LAVASEC_R2`)** — `catalog/latest.json`, `catalog/{version}.json`, and the round-robin cursor `catalog/scheduled-sync-cursor.json`. **It never stores third-party blocklist bytes.** (Legacy bug-report attachment objects are only ever *deleted* — best-effort during account deletion — never written.)
- **D1 (`HELP_FEEDBACK_DB`)** — append-only anonymous `article_id` / `locale` / `vote` / `path` rows; kept separate from Supabase by design.
- **Cron (`scheduled`)** — the handler branches on the cron id:
  - **Every 6 hours** — syncs **one** source per run, round-robined via the R2 cursor (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), then republishes the catalog. Spreading the load avoids hammering all upstreams at once.
  - **Every 2 minutes** — runs `promoteBugReportsToLinear` (`src/index.ts:359`), an internal bug-report triage path that promotes new anonymous reports into an internal issue-tracker queue, advancing its own watermark cursor. This is internal operations tooling; the issue-tracker/notification identifiers are configuration, not part of the public API.

## 3. Catalog & source-url-only enforcement

This is the part of the backend most specific to Lava's compliance posture, so it gets server-side teeth.

### 3.1 The source-url-only model

> **Source-url-only:** GPL/IP-compliance distribution model: Lava publishes only the upstream URL + accepted hashes; the device fetches/parses lists itself. Lava **never** stores, mirrors, transforms, or serves third-party blocklist bytes.

Each `blocklist_sources` row carries `redistribution_mode` whose only allowed value is `"source_url_only"`. The catalog the device reads (`/v1/catalog`, `schema_version` 2) splits entries into `sources[]` and `guardrails[]`; every entry carries the upstream `source_url` plus `accepted_source_hashes` (SHA-256 + byte size + entry count + `reviewed_at` + status `accepted`) — never list bytes. See `formatCatalogEntry` (`lavasec-infra: backend/worker/src/index.ts:925`).

> **Dropped:** an earlier design mirrored byte-preserved GPL list files in R2 (the GPL-raw-R2 compliance plan). It was **superseded on 2026-05-25** by source-url-only. Lava no longer stores or serves third-party blocklist bytes. The `mirror_events` table name is a legacy holdover from that abandoned design — it is now just the sync/publish audit log.

### 3.2 How the Worker enforces it on writes

The sync path (`syncOneBlocklist`, admin and cron) fetches each upstream `source_url`, normalizes/validates **locally in the Worker only to compute metadata** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), writes a `blocklist_versions` row, and republishes. The byte-storage keys are hard-written to null:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

A migration (`20260525000000_add_blocklist_distribution_mode.sql`) dropped these columns to nullable and set existing values to null, so the no-mirror stance is enforced at the schema level too. The published catalog is written to **both** `catalog/{version}.json` and `catalog/latest.json` in R2 (`publishCatalog`).

### 3.3 Normalization guardrails (metadata only)

Worker-side normalization (`normalizeBlocklist`) filters protected domains, enforces caps, and dedupes+sorts. This is purely to compute trustworthy metadata; the **device re-validates accepted hashes** when it downloads the real list, so this is not a security boundary on its own. Constants in `lavasec-infra: backend/worker/src/index.ts:179-199`:

- `PROTECTED_SUFFIXES` — strips any rule matching Apple/iCloud/`mzstatic`/Lava Security domains/Supabase/Cloudflare/Google/GitHub, so a poisoned upstream cannot block Lava's own infrastructure or sign-in providers.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 What is publishable

`isPublicBlocklistSource` only publishes a source when `status` is `sync` or `nosync`, `redistribution_mode === "source_url_only"`, **and** `isAllowedLaunchGPLSource` passes. The launch-GPL gate (`isAllowedLaunchGPLSource`) allows non-GPL sources freely but restricts GPL-3.0 sources to `list_id` prefixes `hagezi-` or `oisd-`.

### 3.5 Seeded sources & default-enabled

Curated sources are seeded as source-url-only metadata via migrations (HaGeZi, OISD, Block List Project, Phishing.Database, AdGuard). The low-risk migration (`20260526000000_low_risk_blocklist_sources.sql`) sets `blocklistproject-basic` (Unlicense) `default_enabled = true`, forces **all GPL (HaGeZi/OISD) sources `default_enabled = false`** pending counsel, and parks AdGuard DNS Filter in `license_review`. Status: **Implemented**.

> **Catalog defaults match the client.** The catalog's `default_enabled` set is now **{Block List Project Phishing, Block List Project Scam}**, matching the iOS recommended default (`AppConfiguration.lavaRecommendedDefaults`, in `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`). A migration (`lavasec-infra: supabase/migrations/20260616000000_default_enabled_phishing_scam.sql`) sets `blocklistproject-basic default_enabled = false` and `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`, so the served metadata is truthful. (lavasec-infra#13 is the alignment decision — now shipped.) Note that `default_enabled` is informational: the real tier gate is the **filter-rules budget (Free 500K / Plus 2M)**, not list count. The legal rationale for publishing URLs (not bytes) is in [GPL source-url-only compliance decision](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres

A Supabase Postgres project. RLS is enabled on **every** public table.

### 4.1 Core schema

`20260516034033_backend_core.sql` creates the foundation (RLS enabled on all 7 public tables):

- **`profiles`, `user_settings`, `entitlements`** — per-user account state. A trigger `handle_new_user()` auto-creates `profiles` + `user_settings` rows on `auth.users` insert.
- **`blocklist_sources`, `blocklist_versions`** — the catalog metadata tables. A source is a curated upstream list (`list_id`, `source_url`, license, risk, `default_enabled`, `status`, `redistribution_mode`); a version is a synced snapshot's metadata (hashes, `entry_count`, `byte_size`), linked back via `latest_version_id`.
- **`mirror_events`** — service-role-only audit log of `sync` / `catalog_publish` events (legacy name; see §3.1).
- **`bug_reports`** — service-role-only anonymous reports.

Later migrations add **`user_backups`** (§4.3) and **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 RLS model

| Table(s) | Policy | Effect |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | per-user `auth.uid() = user_id` | each user sees only their own rows |
| `blocklist_sources` | public-read where `status in ('sync','nosync')` (`backend_core.sql:262-266`) | anyone can read curated, sync-eligible sources |
| `blocklist_versions` | public-read where `validation_status = 'published'` (`backend_core.sql:268-272`) | anyone can read published version metadata |
| `bug_reports`, `mirror_events` | explicit `using(false)` (`20260516034136_backend_core_advisor_fixes.sql`) | no anon/authenticated access — Worker uses the service role |
| `qa_developers` | RLS on + **revoke all from anon, authenticated** | service-role-only; the QA allowlist is never client-readable |

The split matters: anonymous bug reports must be *insertable* by the Worker without being *readable* by clients, and the QA allowlist must only ever be read by the service role.

### 4.3 Auth & the encrypted backup envelope

**Auth** is optional. Sign-in is **Apple + Google only** (email/password is **Dropped**). Both use the native `id_token` grant exchanged at Supabase Auth `auth/v1/token?grant_type=id_token` with a hashed nonce; the app stores only the resulting session device-locally in the Keychain. The client-side flow lives in the iOS app (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — see [Accounts & Backup](./accounts-and-backup.md) for the full account/backup model.

> **Zero-knowledge backup:** Client-side AES-256-GCM envelope; only ciphertext + non-secret metadata upload to Supabase `user_backups` (RLS per user). Server cannot decrypt without a user-held secret.

The crucial backend fact: **the iOS client reads/writes `user_backups` directly via Supabase PostgREST under per-user RLS** (upsert on `user_id`, scoped by the access token). There are **no `/v1/backup` routes** on the Worker at all. The Worker touches `user_backups` exactly once: to delete it during account deletion (`deleteAccount`, `lavasec-infra: backend/worker/src/index.ts:1103`; the `user_backups` delete is at line 1130).

`user_backups` stores only opaque ciphertext + non-secret envelope metadata (KDF params/salts, nonces, key-slot labels, client schema hints). Size caps (`20260605000000_tighten_backup_envelope_constraints.sql`): ciphertext ≤ 262144 bytes (256 KiB) / ≤ 349528 chars, metadata ≤ 32768 bytes (32 KiB). The DB never stores plaintext settings, passwords, phrases, or keys.

### 4.4 Account deletion

`POST /v1/account/delete` validates the user's access token, then deletes their `bug_reports` (and any matching legacy R2 attachment object), `user_backups`, `entitlements`, `user_settings`, and `profiles` rows, and finally deletes the Supabase Auth user via the service-role `/admin/users` endpoint. It returns only a deleted status + the linked providers. Status: **Implemented** (the plan frontmatter says "Backlog" but the file is in `plans/implemented/` and the code exists, so by the lane-folder + code-wins rule it is shipped).

### 4.5 App Store entitlement mirroring

`POST /v1/account/entitlements/app-store-sync` upserts an `entitlements` row (plan `lava_security_plus`) from a client-verified StoreKit transaction JWS, on conflict by `user_id`. The stored `verification_status` is literally `"client_verified_storekit"` — the server does **not** re-verify the JWS. Allowed product IDs: `lava_security_plus_{monthly,yearly,lifetime}`.

> Mirroring is **Implemented**; **server-side JWS verification is Planned** (not yet built). The signed JWS is stored for later verification. Note the tier model elsewhere: app entitlement is local (`isPaid`) with **no backend sync yet** as the source of truth — this row is a mirror, not the gate.

## 5. Passkey-assisted recovery (zero-knowledge)

Passkey-assisted backup recovery is **zero-knowledge** and entirely client-side. The recovery key material is derived on-device from the passkey's **WebAuthn PRF / hmac-secret** output; the server stores **no** recovery secret, registers **no** passkeys, and issues **no** WebAuthn challenges. There is no server-gated escrow path.

The escrow tables that an earlier design used (`backup_passkey_recovery`, `backup_passkey_challenges`) were dropped before launch (`lavasec-infra: supabase/migrations/20260616000000_drop_backup_passkey_recovery.sql`), and the Worker carries no `/v1/backup/*` routes and no WebAuthn/passkey code. (A `@simplewebauthn/server` entry remains in the Worker's `package.json` as an unused leftover dependency.)

The client side lives in the iOS app: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` drives the PRF-capable passkey creation/assertion, and `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` derives the slot from the hmac-secret output. The PRF output is read only during assertion and never leaves the device. A non-PRF passkey provider cannot back a zero-knowledge slot, so setup fails early and the user falls back to a recovery phrase. Status: **Implemented**.

## 6. lavasec-email Worker

Receive-and-forward only. It forwards `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` to a verified operator inbox, rejects unknown recipients and mail over 10 MiB, and **does not store email bodies**. Support auto-replies are coded but gated behind paid Cloudflare outbound email (deferred). Routing constants live in `email-service.ts:9` (`ROUTED_RECIPIENTS`); the inbound handler is `handleInboundEmail`. Status: **Implemented** (auto-reply path **Planned**/deferred).

## 7. Config & deploy

- **Config is `wrangler.toml`, which is gitignored**; `wrangler.toml.example` is the committed template. Treat the local `wrangler.toml` as canonical for environment-specific values.
- **Vars** (non-secret, in `[vars]`): `SUPABASE_URL`, `PUBLIC_API_ORIGIN = https://api.lavasecurity.app`, `PUBLIC_CATALOG_CACHE_SECONDS = "300"`, `MAX_BUG_REPORT_BYTES = "65536"`, `ACCOUNT_DELETION_AUDIT_ENABLED = "false"`, `CBOR_NATIVE_ACCELERATION_DISABLED = "true"`. Internal bug-report triage adds `LINEAR_TRIAGE_TEAM_KEY` (the triage queue key) and `PUBLIC_SUPABASE_DASHBOARD_ORIGIN` (a dashboard origin used when composing triage links).
- **Secrets** (via `wrangler secret put`): `SUPABASE_SERVICE_ROLE_KEY`, `ADMIN_API_KEY`, and — for the bug-report triage path — an issue-tracker API key (`LINEAR_API_KEY`) and an optional chat notification webhook (`SLACK_TRIAGE_WEBHOOK_URL`).
- **Deploy is manual**: `npm run deploy` → `wrangler deploy`. There is no CI for the Worker.
- **Cloudflare routing**: `lavasecurity.app` stays on Pages; `api.lavasecurity.app` and `*.qa-probe.lavasecurity.app` resolve to this Worker.
- **Compatibility**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` is set in vars but is not referenced by the Worker code; it is a Workers-runtime acceleration flag rather than an application setting.

## 8. Privacy invariants (what is and isn't here)

A quick checklist for anyone extending the backend — none of these may be quietly broken:

1. **No DNS/browsing telemetry.** There is no table for routine DNS queries or per-domain telemetry. Filtering stays on the device.
2. **No third-party blocklist bytes** in R2 or Postgres — only `source_url` + accepted hashes (§3).
3. **`user_backups` is opaque** — ciphertext + non-secret metadata only; the client (not the Worker) writes it under RLS (§4.3).
4. **Service-role isolation** for `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **All backup paths are zero-knowledge** — including passkey-assisted recovery, whose key material is derived client-side from the WebAuthn PRF/hmac-secret output. The server stores no recovery secret and runs no WebAuthn (§5).

## See also

- [System Overview](./system-overview.md) — the whole system on one page, including trust boundaries.
- [iOS client](./ios-client.md) — the device side that consumes this backend.
- [Accounts & Backup](./accounts-and-backup.md) — client-side auth, the AES-256-GCM envelope, key slots, and recovery phrases.
- [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) — the device side of the catalog: direct upstream download, parse/normalize, and the filter-rules budget.
- [GPL source-url-only compliance decision](../legal/gpl-source-url-only-compliance-decision.md) — why the catalog publishes URLs, not bytes.
- **Tiers & monetization** (internal) — the filter-rules budget (Free 500K / Plus 2M) that is the real Free/Plus gate.
- **IP risk register** (internal) — the IP/compliance rationale behind source-url-only.
