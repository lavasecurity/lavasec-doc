---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 백엔드 및 데이터

> **대상 독자:** 백엔드 엔지니어. **범위:** 서버 계층 — 두 개의 Cloudflare Worker, Supabase Postgres 스키마/RLS/인증, Cloudflare R2 및 D1 저장소, 전체 HTTP API 표면, 설정 및 배포, 그리고 서버에서 source-url-only가 어떻게 강제되는지.
>
> **권위 있는 기준:** 계획과 코드가 어긋날 때는 **코드가 우선**이며, 차이는 본문에 직접 표시했어요. 상태 라벨은 문서 세트의 범례를 따라요: **구현됨**(출시되어 코드에서 확인됨), **진행 중**(부분적으로 반영됨), **계획됨**(설계되었으나 미구현), **폐기됨**(거부되거나 되돌려짐).

## 1. 백엔드의 형태 {#1-the-shape-of-the-backend}

백엔드는 의도적으로 작고 프라이버시를 보호하도록 만들어졌어요. 이것은 필터링 서비스가 아니라 메타데이터와 계정을 위한 엣지예요. **모든 DNS 필터링은 기기에서 이루어지고, Lava는 절대 여러분의 브라우징을 자사 서버로 라우팅하지 않으며, 여러분이 방문하는 도메인의 흐름을 받지도 않아요 — 백엔드는 카탈로그 메타데이터, 사용자별 불투명한 암호화 백업, 그리고 여러분이 보내기로 선택한 익명 진단 정보만 보관해요.** 일상적인 DNS 질의나 도메인별 텔레메트리를 위한 테이블은 없으며, 계정 로그인은 선택 사항이고 보호를 위해 절대 요구되지 않아요.

서버 계층은 두 가지 구성 요소로 나뉘어요: 백엔드 Worker 코드와 DB 스키마.

| 구성 요소 | 역할 |
|---|---|
| **lavasec-api Worker** | 메인 엣지: 공개 카탈로그 읽기, 관리자+크론 차단 목록 동기화 및 카탈로그 게시, 익명 버그 리포트, 도움말 피드백, 계정 삭제, App Store 권한 미러링, QA 프로브 픽셀, 계정 QA 접근 확인, 버그 리포트 분류 승격 |
| **lavasec-email Worker** | `@lavasecurity.app`에 대한 수신 전용 Cloudflare Email Routing 전달기 |
| **Supabase Postgres** (Supabase Postgres 프로젝트) | 계정, 암호화된 백업, 카탈로그 메타데이터, 서비스 롤 전용 테이블; 모든 공개 테이블에 RLS 적용 |
| **Cloudflare R2** (프로덕션 버킷, 스테이징용 별도 프리뷰 버킷 포함) | 카탈로그 스냅샷 + 동기화 커서; 서드파티 차단 목록 바이트는 **절대** 저장하지 않음 |
| **Cloudflare D1** (도움말 피드백 데이터베이스) | 추가 전용 익명 도움말 문서 피드백 투표 |

Worker는 Supabase 서비스 롤 자격 증명을 사용해 PostgREST(`/rest/v1`)와 Auth(`/auth/v1`)를 통해 Supabase에 접근해요 — 서버에는 Supabase SDK가 없고, `supabase()` / `supabaseAuth()` 헬퍼를 통한 원시 `fetch` 호출이에요.

상태: **구현됨**.

## 2. lavasec-api Worker {#2-lavasec-api-worker}

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, R2 바인딩 → 프로덕션 버킷(스테이징용 별도 프리뷰 버킷), D1 바인딩 → 도움말 피드백 데이터베이스, 그리고 **두 개의 크론 트리거**: 6시간마다 실행되는 것(차단 목록 동기화 + 카탈로그 게시) 하나와 2분마다 실행되는 것(버그 리포트 분류 승격) 하나. `api.lavasecurity.app`에서 제공돼요.

### 2.1 API 표면 {#21-api-surface}

라우팅은 평탄한 `route()` 디스패처예요. 별도 표시가 없으면 모두 **구현됨**이에요.

**공개 / 미인증**

| 메서드 및 경로 | 핸들러 | 비고 |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | R2에서 `catalog/latest.json` 제공 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | R2에서 `catalog/{version}.json` 제공; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (기본값 300초) |
| `POST /v1/bug-reports` | `createBugReport` | 익명, 로그인 선택; 허용 목록에 있는 디버그 필드만 |
| `POST /v1/help-feedback` | `createHelpFeedback` | 익명 문서 투표 → Supabase가 아닌 **D1**로 |

> 첨부 파일 업로드(이전의 `PUT /v1/bug-reports/:id/attachment` 경로)는 **제거되었어요**; 스크린샷과 추가 세부 정보는 사람이 중개하는 지원 채널을 통해 처리돼요. Worker는 계정 삭제 중에 레거시 첨부 객체가 있으면 최선의 노력으로 삭제만 할 뿐이에요.

**계정 (Supabase 액세스 토큰 필요)**

| 메서드 및 경로 | 핸들러 | 비고 |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | 사용자의 액세스 토큰을 검증하고, 해당 행 + 레거시 R2 첨부 객체를 삭제한 다음, 서비스 롤로 Supabase Auth 사용자를 삭제 |
| `GET /v1/account/qa-access` | `accountQAAccess` | 서비스 롤 전용 `qa_developers` 허용 목록에서 `is_developer`를 반환 |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | 클라이언트가 검증한 StoreKit JWS로부터 `entitlements` 행(플랜 `lava_security_plus`)을 업서트 |

> **`/v1/backup` 경로는 없어요.** 패스키 보조 백업 복구는 이제 **제로 지식**이고 전적으로 클라이언트 측이에요(§4.3 및 §5 참조); Worker에는 `/v1/backup/*` 경로도, WebAuthn/패스키 코드도 없어요.

**관리자 (`requireAdmin`을 통한 관리자 API 키)**

| 메서드 및 경로 | 핸들러 |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> 관리자 HTTP 엔드포인트는 관리자 API 키로 보호돼요. 예약(크론) 동기화 경로는 이 HTTP 경로들을 호출하지 **않아요** — `scheduled` 핸들러 내부에서 동기화 로직(`syncBlocklistSources`)을 직접 실행해요.

**QA 프로브 호스트** — 네 개의 `*.qa-probe.lavasecurity.app` 호스트(`allowed`/`blocked`/`exception`/`guardrail`)로의 요청은 라우팅 전에 단락 처리되어 `getQAProbePixel`을 통해 1×1 `no-store` PNG를 반환해요. 이것들은 Supabase나 R2에 기록되지 않아요.

### 2.2 바인딩 및 크론 {#22-bindings--cron}

- **R2 바인딩** — `catalog/latest.json`, `catalog/{version}.json`, 그리고 라운드 로빈 커서 `catalog/scheduled-sync-cursor.json`. **서드파티 차단 목록 바이트는 절대 저장하지 않아요.** (레거시 버그 리포트 첨부 객체는 오직 *삭제*만 돼요 — 계정 삭제 중 최선의 노력으로 — 절대 기록되지 않아요.)
- **D1 바인딩** — 추가 전용 익명 `article_id` / `locale` / `vote` / `path` 행; 설계상 Supabase와 분리되어 있어요.
- **크론 (`scheduled`)** — 핸들러는 크론 id에 따라 분기해요:
  - **6시간마다** — 실행마다 R2 커서로 라운드 로빈되며(`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`) **하나의** 소스를 동기화한 다음, 카탈로그를 다시 게시해요. 부하를 분산하면 모든 업스트림을 한꺼번에 두드리는 것을 피할 수 있어요.
  - **2분마다** — 새로운 익명 리포트를 내부 이슈 트래커 큐로 승격하는 내부 버그 리포트 분류 경로를 실행하며, 자체 워터마크 커서를 전진시켜요. 이것은 내부 운영 도구이며, 이슈 트래커/알림 식별자는 설정이지 공개 API의 일부가 아니에요.

## 3. 카탈로그 및 source-url-only 강제 {#3-catalog--source-url-only-enforcement}

이 부분은 Lava의 컴플라이언스 태세에 가장 특화된 백엔드 영역이라, 서버 측에 강제 장치를 두고 있어요.

### 3.1 source-url-only 모델 {#31-the-source-url-only-model}

> **source-url-only:** GPL/IP 컴플라이언스 배포 모델: Lava는 업스트림 URL + 승인된 해시만 게시하고, 기기가 직접 목록을 가져와 파싱해요. Lava는 서드파티 차단 목록 바이트를 **절대** 저장하거나, 미러링하거나, 변환하거나, 제공하지 않아요.

각 `blocklist_sources` 행은 유일하게 허용된 값이 `"source_url_only"`인 `redistribution_mode`를 가져요. 기기가 읽는 카탈로그(`/v1/catalog`, `schema_version` 2)는 항목을 `sources[]`와 `guardrails[]`로 나누며, 모든 항목은 업스트림 `source_url`과 `accepted_source_hashes`(SHA-256 + 바이트 크기 + 항목 수 + `reviewed_at` + 상태 `accepted`)를 가져요 — 목록 바이트는 절대 아니에요. `formatCatalogEntry`를 참고하세요.

> **폐기됨:** 이전 설계는 바이트가 보존된 GPL 목록 파일을 R2에 미러링했어요(GPL-raw-R2 컴플라이언스 계획). 이것은 **2026-05-25에** source-url-only로 **대체되었어요**. Lava는 더 이상 서드파티 차단 목록 바이트를 저장하거나 제공하지 않아요. `mirror_events` 테이블 이름은 그 폐기된 설계의 레거시 잔재이며 — 이제는 그냥 동기화/게시 감사 로그예요.

### 3.2 Worker가 쓰기 시점에 이를 강제하는 방법 {#32-how-the-worker-enforces-it-on-writes}

동기화 경로(`syncOneBlocklist`, 관리자 및 크론)는 각 업스트림 `source_url`을 가져와서, **오직 메타데이터 계산을 위해 Worker 내부에서만 로컬로** 정규화/검증하고(`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), `blocklist_versions` 행을 기록한 뒤, 다시 게시해요. 바이트 저장 키는 null로 하드코딩되어 있어요:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

마이그레이션(`20260525000000_add_blocklist_distribution_mode.sql`)이 이 컬럼들을 nullable로 떨어뜨리고 기존 값을 null로 설정해서, 미러링 없음 입장이 스키마 수준에서도 강제돼요. 게시된 카탈로그는 R2의 `catalog/{version}.json`과 `catalog/latest.json` **둘 다**에 기록돼요(`publishCatalog`).

### 3.3 정규화 가드레일 (메타데이터 전용) {#33-normalization-guardrails-metadata-only}

Worker 측 정규화(`normalizeBlocklist`)는 보호된 도메인을 필터링하고, 상한을 강제하며, 중복을 제거하고 정렬해요. 이것은 순전히 신뢰할 수 있는 메타데이터를 계산하기 위함이며, 기기가 실제 목록을 다운로드할 때 **승인된 해시를 다시 검증**하므로 그 자체로 보안 경계는 아니에요. 주요 상수:

- `PROTECTED_SUFFIXES` — Apple/iCloud/`mzstatic`/Lava Security 도메인/Supabase/Cloudflare/Google/GitHub와 일치하는 모든 규칙을 제거해서, 오염된 업스트림이 Lava 자체 인프라나 로그인 제공자를 차단할 수 없게 해요.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 게시 가능한 것 {#34-what-is-publishable}

`isPublicBlocklistSource`는 `status`가 `sync` 또는 `nosync`이고, `redistribution_mode === "source_url_only"`이며, **그리고** `isAllowedLaunchGPLSource`를 통과할 때만 소스를 게시해요. 출시-GPL 게이트(`isAllowedLaunchGPLSource`)는 비-GPL 소스를 자유롭게 허용하지만 GPL-3.0 소스는 `list_id` 접두사가 `hagezi-` 또는 `oisd-`인 것으로 제한해요.

### 3.5 시드된 소스 및 기본 활성화 {#35-seeded-sources--default-enabled}

큐레이션된 소스는 마이그레이션을 통해 source-url-only 메타데이터로 시드돼요(HaGeZi, OISD, Block List Project, Phishing.Database, AdGuard). 저위험 마이그레이션(`20260526000000_low_risk_blocklist_sources.sql`)은 처음에 `blocklistproject-basic`(Unlicense)을 `default_enabled = true`로 시드하고, **모든 GPL(HaGeZi/OISD) 소스를 `default_enabled = false`로** 강제했으며(법률 검토 대기), AdGuard DNS Filter를 `license_review`에 보류했어요. **그 초기 Basic 기본값 시드는 나중에 대체되었어요** — 아래의 정렬 마이그레이션이 Basic을 `false`로, Phishing + Scam을 `true`로 뒤집어요(현재 제공되는 기본값). 상태: **구현됨**.

> **카탈로그 기본값이 클라이언트와 일치해요.** 카탈로그의 `default_enabled` 집합은 이제 **{Block List Project Phishing, Block List Project Scam}**이며, iOS 권장 기본값(`AppConfiguration.lavaRecommendedDefaults`, `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`)과 일치해요. 마이그레이션이 `blocklistproject-basic default_enabled = false`, `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`로 설정해서, 제공되는 메타데이터가 진실되어요. (정렬 결정은 이제 출시되었어요.) `default_enabled`는 정보 제공용이라는 점에 유의하세요: 실제 등급 게이트는 목록 수가 아니라 **필터 규칙 예산(Free 500K / Plus 2M)**이에요. URL을 게시하는(바이트가 아닌) 법적 근거는 [GPL source-url-only 컴플라이언스 결정](../legal/gpl-source-url-only-compliance-decision.md)에 있어요.

## 4. Supabase Postgres {#4-supabase-postgres}

Supabase Postgres 프로젝트. RLS는 **모든** 공개 테이블에서 활성화되어 있어요.

### 4.1 핵심 스키마 {#41-core-schema}

`20260516034033_backend_core.sql`이 기반을 만들어요(7개 공개 테이블 전체에 RLS 활성화):

- **`profiles`, `user_settings`, `entitlements`** — 사용자별 계정 상태. 트리거 `handle_new_user()`가 `auth.users` 삽입 시 `profiles` + `user_settings` 행을 자동 생성해요.
- **`blocklist_sources`, `blocklist_versions`** — 카탈로그 메타데이터 테이블. 소스는 큐레이션된 업스트림 목록이고(`list_id`, `source_url`, license, risk, `default_enabled`, `status`, `redistribution_mode`), 버전은 동기화된 스냅샷의 메타데이터예요(해시, `entry_count`, `byte_size`). `latest_version_id`로 다시 연결돼요.
- **`mirror_events`** — `sync` / `catalog_publish` 이벤트의 서비스 롤 전용 감사 로그(레거시 이름; §3.1 참조).
- **`bug_reports`** — 서비스 롤 전용 익명 리포트.

이후 마이그레이션이 **`user_backups`**(§4.3)와 **`qa_developers`**(`20260608000000_qa_developers_allowlist.sql`)를 추가해요.

### 4.2 RLS 모델 {#42-rls-model}

| 테이블 | 정책 | 효과 |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | 사용자별 `auth.uid() = user_id` | 각 사용자는 자신의 행만 봄 |
| `blocklist_sources` | `status in ('sync','nosync')`인 경우 공개 읽기 (`backend_core.sql:262-266`) | 누구나 큐레이션된 동기화 대상 소스를 읽을 수 있음 |
| `blocklist_versions` | `validation_status = 'published'`인 경우 공개 읽기 (`backend_core.sql:268-272`) | 누구나 게시된 버전 메타데이터를 읽을 수 있음 |
| `bug_reports`, `mirror_events` | 명시적 `using(false)` (`20260516034136_backend_core_advisor_fixes.sql`) | anon/authenticated 접근 없음 — Worker가 서비스 롤 사용 |
| `qa_developers` | RLS 활성화 + **anon, authenticated에서 모든 권한 회수** | 서비스 롤 전용; QA 허용 목록은 절대 클라이언트에서 읽을 수 없음 |

이 구분은 중요해요: 익명 버그 리포트는 클라이언트가 *읽을* 수는 없으면서 Worker가 *삽입할* 수 있어야 하고, QA 허용 목록은 오직 서비스 롤만 읽을 수 있어야 해요.

### 4.3 인증 및 암호화된 백업 봉투 {#43-auth--the-encrypted-backup-envelope}

**인증**은 선택 사항이에요. 로그인은 **Apple + Google만** 가능해요(이메일/비밀번호는 **폐기됨**). 둘 다 해시된 nonce와 함께 Supabase Auth `auth/v1/token?grant_type=id_token`에서 교환되는 네이티브 `id_token` 그랜트를 사용하며, 앱은 결과 세션을 기기 로컬 Keychain에만 저장해요. 클라이언트 측 흐름은 iOS 앱에 있어요(`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — 전체 계정/백업 모델은 [계정 및 백업](./accounts-and-backup.md)을 참고하세요.

> **제로 지식 백업:** 클라이언트 측 AES-256-GCM 봉투; 암호문 + 비밀이 아닌 메타데이터만 Supabase `user_backups`(사용자별 RLS)에 업로드돼요. 서버는 사용자가 보유한 비밀 없이는 복호화할 수 없어요.

핵심 백엔드 사실: **iOS 클라이언트는 사용자별 RLS 하에서 Supabase PostgREST를 통해 `user_backups`를 직접 읽고 써요**(`user_id`에 대한 업서트, 액세스 토큰으로 범위 지정). Worker에는 `/v1/backup` 경로가 아예 **없어요**. Worker는 정확히 한 번 `user_backups`를 건드려요: 계정 삭제(`deleteAccount`) 중에 삭제할 때.

`user_backups`는 불투명한 암호문 + 비밀이 아닌 봉투 메타데이터(KDF 매개변수/솔트, nonce, 키 슬롯 라벨, 클라이언트 스키마 힌트)만 저장해요. 크기 상한(`20260605000000_tighten_backup_envelope_constraints.sql`): 암호문 ≤ 262144바이트(256 KiB) / ≤ 349528자, 메타데이터 ≤ 32768바이트(32 KiB). DB는 평문 설정, 비밀번호, 구문, 키를 절대 저장하지 않아요.

### 4.4 계정 삭제 {#44-account-deletion}

`POST /v1/account/delete`는 사용자의 액세스 토큰을 검증한 다음, 해당 사용자의 `bug_reports`(및 일치하는 레거시 R2 첨부 객체가 있으면), `user_backups`, `entitlements`, `user_settings`, `profiles` 행을 삭제하고, 마지막으로 서비스 롤 `/admin/users` 엔드포인트를 통해 Supabase Auth 사용자를 삭제해요. 반환값은 삭제 상태 + 연결된 제공자뿐이에요. 상태: **구현됨**(계획의 프런트매터에는 `status: Done`이라 적혀 있고 파일은 `plans/implemented/`에 있어요; **본문 내** 주석에는 여전히 "Backlog"라고 적혀 있지만, 레인 폴더 + 코드 존재로 보아 출시되었어요).

### 4.5 App Store 권한 미러링 {#45-app-store-entitlement-mirroring}

`POST /v1/account/entitlements/app-store-sync`는 클라이언트가 검증한 StoreKit 트랜잭션 JWS로부터 `entitlements` 행(플랜 `lava_security_plus`)을 `user_id` 충돌 기준으로 업서트해요. 저장되는 `verification_status`는 문자 그대로 `"client_verified_storekit"`이에요 — 서버는 JWS를 다시 검증하지 **않아요**. 허용된 제품 ID: `lava_security_plus_{monthly,yearly,lifetime}`.

> 미러링은 **구현됨**이고; **서버 측 JWS 검증은 계획됨**이에요(아직 미구현). 서명된 JWS는 나중의 검증을 위해 저장돼요. 다른 곳의 등급 모델에 유의하세요: 앱 권한은 로컬(`isPaid`)이며 아직 진실의 원천으로서의 **백엔드 동기화는 없어요** — 이 행은 미러이지 게이트가 아니에요.

## 5. 패스키 보조 복구 (제로 지식) {#5-passkey-assisted-recovery-zero-knowledge}

패스키 보조 백업 복구는 **제로 지식**이고 전적으로 클라이언트 측이에요. 복구 키 자료는 패스키의 **WebAuthn PRF / hmac-secret** 출력으로부터 기기에서 파생돼요; 서버는 복구 비밀을 **전혀** 저장하지 않고, 패스키를 **전혀** 등록하지 않으며, WebAuthn 챌린지를 **전혀** 발급하지 않아요. 서버가 게이트하는 에스크로 경로는 없어요.

이전 설계가 사용했던 에스크로 테이블(`backup_passkey_recovery`, `backup_passkey_challenges`)은 출시 전에 제거되었고, Worker에는 `/v1/backup/*` 경로도, WebAuthn/패스키 코드도 없어요. (Worker의 `package.json`에 `@simplewebauthn/server` 항목이 사용되지 않는 잔여 의존성으로 남아 있어요.)

클라이언트 측은 iOS 앱에 있어요: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift`가 PRF 지원 패스키 생성/어서션을 구동하고, `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`가 hmac-secret 출력으로부터 슬롯을 파생해요. PRF 출력은 어서션 중에만 읽히고 절대 기기를 떠나지 않아요. 비-PRF 패스키 제공자는 제로 지식 슬롯을 뒷받침할 수 없으므로, 설정이 일찍 실패하고 사용자는 복구 구문으로 대체돼요. 상태: **구현됨**.

## 6. lavasec-email Worker {#6-lavasec-email-worker}

수신 후 전달만 해요. `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app`을 검증된 운영자 받은편지함으로 전달하고, 알 수 없는 수신자와 10 MiB를 초과하는 메일을 거부하며, **이메일 본문을 저장하지 않아요**. 지원 자동 응답은 코딩되어 있지만 유료 Cloudflare 아웃바운드 이메일 뒤에 게이트되어 있어요(연기됨). 라우팅 상수는 `email-service.ts:9`(`ROUTED_RECIPIENTS`)에 있고, 인바운드 핸들러는 `handleInboundEmail`이에요. 상태: **구현됨**(자동 응답 경로는 **계획됨**/연기됨).

## 7. 설정 및 배포 {#7-config--deploy}

- **설정은 `wrangler.toml`이며 gitignore 처리되어 있어요**; `wrangler.toml.example`이 커밋된 템플릿이에요. 환경별 값은 로컬 `wrangler.toml`을 정본으로 취급하세요.
- **Vars**(비밀이 아님, `[vars]` 내): Supabase URL, 공개 API 오리진(`https://api.lavasecurity.app`), 카탈로그 캐시 TTL(기본값 300초), 버그 리포트 크기 상한, 계정 삭제 감사 토글, 그리고 Workers 런타임 가속 플래그. 내부 버그 리포트 분류는 내부 분류 큐 키와 분류 링크를 구성할 때 사용되는 대시보드 오리진을 추가해요.
- **Secrets**(`wrangler secret put`을 통해): Supabase 서비스 롤 자격 증명, 관리자 API 키, 그리고 — 버그 리포트 분류 경로를 위해 — 이슈 트래커 API 키와 선택적 채팅 알림 웹훅.
- **배포는 수동이에요**: `npm run deploy` → `wrangler deploy`. Worker에 대한 CI는 없어요.
- **Cloudflare 라우팅**: `lavasecurity.app`은 Pages에 남아 있고; `api.lavasecurity.app`과 `*.qa-probe.lavasecurity.app`은 이 Worker로 해석돼요.
- **호환성**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"`는 vars에 설정되어 있지만 Worker 코드에서 참조되지 않아요; 애플리케이션 설정이라기보다는 Workers 런타임 가속 플래그예요.

## 8. 프라이버시 불변 조건 (무엇이 여기에 있고 없는지) {#8-privacy-invariants-what-is-and-isnt-here}

백엔드를 확장하려는 누구에게나 빠른 체크리스트예요 — 이 중 어느 것도 조용히 깨뜨려서는 안 돼요:

1. **DNS/브라우징 텔레메트리 없음.** 일상적인 DNS 질의나 도메인별 텔레메트리를 위한 테이블은 없어요. 필터링은 기기에 머물러요.
2. R2나 Postgres에 **서드파티 차단 목록 바이트 없음** — `source_url` + 승인된 해시만(§3).
3. **`user_backups`는 불투명함** — 암호문 + 비밀이 아닌 메타데이터만; Worker가 아니라 클라이언트가 RLS 하에서 기록해요(§4.3).
4. `bug_reports`, `mirror_events`, `qa_developers`에 대한 **서비스 롤 격리**(§4.2).
5. **모든 백업 경로는 제로 지식** — 키 자료가 WebAuthn PRF/hmac-secret 출력으로부터 클라이언트 측에서 파생되는 패스키 보조 복구를 포함해서요. 서버는 복구 비밀을 저장하지 않고 WebAuthn을 실행하지 않아요(§5).

## 함께 보기 {#see-also}

- [시스템 개요](./system-overview.md) — 신뢰 경계를 포함한 전체 시스템을 한 페이지에.
- [iOS 클라이언트](./ios-client.md) — 이 백엔드를 사용하는 기기 측.
- [계정 및 백업](./accounts-and-backup.md) — 클라이언트 측 인증, AES-256-GCM 봉투, 키 슬롯, 복구 구문.
- [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md) — 카탈로그의 기기 측: 직접 업스트림 다운로드, 파싱/정규화, 그리고 필터 규칙 예산.
- [GPL source-url-only 컴플라이언스 결정](../legal/gpl-source-url-only-compliance-decision.md) — 카탈로그가 바이트가 아닌 URL을 게시하는 이유.
- **등급 및 수익화**(내부) — 실제 Free/Plus 게이트인 필터 규칙 예산(Free 500K / Plus 2M).
- **IP 위험 등록부**(내부) — source-url-only 뒤의 IP/컴플라이언스 근거.
