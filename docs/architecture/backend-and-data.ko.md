---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 백엔드 및 데이터

> **대상 독자:** 백엔드 엔지니어. **범위:** 서버 계층 — 두 개의 Cloudflare Workers, Supabase Postgres 스키마/RLS/인증, Cloudflare R2 및 D1 스토어, 전체 HTTP API 표면, 설정 및 배포, 그리고 source-url-only가 서버에서 어떻게 강제되는지.
>
> **권위 있는 참조:** 계획과 코드가 어긋날 때는 **코드가 우선**입니다 — 차이점은 본문에서 인라인으로 표시됩니다. 상태 레이블은 문서 세트의 범례를 사용합니다: **Implemented**(출시되어 코드에서 확인됨), **In progress**(부분적으로 반영됨), **Planned**(설계되었으나 미구현), **Dropped**(거부되거나 되돌려짐).

## 1. 백엔드의 형태

백엔드는 의도적으로 작고 프라이버시를 보존하도록 설계되었습니다. 이것은 필터링 서비스가 아니라 메타데이터-및-계정 엣지입니다. **모든 DNS 필터링은 기기에서 일어납니다. Lava는 절대 여러분의 브라우징을 자사 서버를 통해 라우팅하지 않으며, 여러분이 방문하는 도메인의 스트림을 절대 수신하지 않습니다 — 백엔드는 오직 카탈로그 메타데이터, 사용자별 불투명 암호화 백업, 그리고 여러분이 보내기로 선택한 익명화된 진단 정보만 보관합니다.** 일상적인 DNS 쿼리나 도메인별 텔레메트리를 위한 테이블은 없으며, 계정 로그인은 선택 사항이고 보호를 위해 절대 요구되지 않습니다.

서버 계층은 두 가지 구성 요소로 나뉩니다: 백엔드 Worker 코드와 DB 스키마.

| 구성 요소 | 역할 |
|---|---|
| **lavasec-api Worker** | 주 엣지: 공개 카탈로그 읽기, 관리자+cron 블록리스트 동기화 및 카탈로그 게시, 익명 버그 리포트, 도움말 피드백, 계정 삭제, App Store 자격(entitlement) 미러링, QA 프로브 픽셀, 계정 QA-액세스 확인, 버그 리포트 트리아지 승격 |
| **lavasec-email Worker** | `@lavasecurity.app`에 대한 수신 전용 Cloudflare Email Routing 포워더 |
| **Supabase Postgres** (Supabase Postgres 프로젝트) | 계정, 암호화된 백업, 카탈로그 메타데이터, 서비스 역할 전용 테이블; 모든 공개 테이블에 RLS 적용 |
| **Cloudflare R2** (프로덕션 버킷, 스테이징용 별도 프리뷰 버킷 포함) | 카탈로그 스냅샷 + 동기화 커서; **절대** 서드파티 블록리스트 바이트는 저장하지 않음 |
| **Cloudflare D1** (도움말 피드백 데이터베이스) | 추가 전용 익명 도움말 문서 피드백 투표 |

Worker는 Supabase 서비스 역할 자격 증명을 사용해 PostgREST(`/rest/v1`)와 Auth(`/auth/v1`)를 통해 Supabase에 도달합니다 — 서버에는 Supabase SDK가 없으며, 호출은 `supabase()` / `supabaseAuth()` 헬퍼를 통한 원시 `fetch`입니다.

상태: **Implemented**.

## 2. lavasec-api Worker

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, R2 바인딩 → 프로덕션 버킷(스테이징용 별도 프리뷰 버킷), D1 바인딩 → 도움말 피드백 데이터베이스, 그리고 **두 개의 cron 트리거**: 하나는 6시간마다 실행(블록리스트 동기화 + 카탈로그 게시)되고 다른 하나는 2분마다 실행(버그 리포트 트리아지 승격)됩니다. `api.lavasecurity.app`에서 제공됩니다.

### 2.1 API 표면

라우팅은 플랫한 `route()` 디스패처입니다. 명시되지 않은 한 모든 것이 **Implemented**입니다.

**공개 / 미인증**

| 메서드 및 경로 | 핸들러 | 비고 |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | R2에서 `catalog/latest.json` 제공 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | R2에서 `catalog/{version}.json` 제공; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS`(기본 300s) |
| `POST /v1/bug-reports` | `createBugReport` | 익명, 로그인 선택 사항; 허용 목록에 있는 디버그 필드만 허용 |
| `POST /v1/help-feedback` | `createHelpFeedback` | 익명 문서 투표 → **D1**, Supabase 아님 |

> 첨부파일 업로드(이전의 `PUT /v1/bug-reports/:id/attachment` 라우트)는 **제거**되었습니다; 스크린샷과 추가 세부 정보는 사람이 중개하는 지원 채널을 통해 처리됩니다. Worker는 계정 삭제 중 레거시 첨부파일 객체를 베스트-에포트로 삭제만 합니다.

**계정 (Supabase 액세스 토큰 필요)**

| 메서드 및 경로 | 핸들러 | 비고 |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | 사용자의 액세스 토큰을 검증하고, 해당 사용자의 행 + 모든 레거시 R2 첨부파일 객체를 삭제한 다음, 서비스 역할로 Supabase Auth 사용자를 삭제 |
| `GET /v1/account/qa-access` | `accountQAAccess` | 서비스 역할 전용 `qa_developers` 허용 목록에서 `is_developer` 반환 |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | 클라이언트가 검증한 StoreKit JWS로부터 `entitlements` 행(plan `lava_security_plus`)을 upsert |

> **`/v1/backup` 라우트 없음.** 패스키 보조 백업 복구는 이제 **제로 지식(zero-knowledge)** 방식이며 완전히 클라이언트 측에서 이루어집니다(§4.3 및 §5 참조); Worker에는 `/v1/backup/*` 라우트도 없고 WebAuthn/패스키 코드도 없습니다.

**관리자 (`requireAdmin`을 통한 관리자 API 키)**

| 메서드 및 경로 | 핸들러 |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> 관리자 HTTP 엔드포인트는 관리자 API 키로 게이트됩니다. 예약된(cron) 동기화 경로는 이러한 HTTP 라우트를 호출하지 **않습니다** — `scheduled` 핸들러 내부에서 동기화 로직(`syncBlocklistSources`)을 직접 호출합니다.

**QA 프로브 호스트** — 네 개의 `*.qa-probe.lavasecurity.app` 호스트(`allowed`/`blocked`/`exception`/`guardrail`)에 대한 요청은 라우팅 이전에 단락(short-circuit)되며 `getQAProbePixel`을 통해 1×1 `no-store` PNG를 반환합니다. 이들은 Supabase나 R2에 기록되지 않습니다.

### 2.2 바인딩 및 cron

- **R2 바인딩** — `catalog/latest.json`, `catalog/{version}.json`, 그리고 라운드 로빈 커서 `catalog/scheduled-sync-cursor.json`. **서드파티 블록리스트 바이트는 절대 저장하지 않습니다.** (레거시 버그 리포트 첨부파일 객체는 *삭제*만 됩니다 — 계정 삭제 중 베스트-에포트로 — 절대 기록되지 않습니다.)
- **D1 바인딩** — 추가 전용 익명 `article_id` / `locale` / `vote` / `path` 행; 설계상 Supabase와 분리되어 유지됩니다.
- **Cron (`scheduled`)** — 핸들러는 cron id에 따라 분기합니다:
  - **6시간마다** — R2 커서(`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`)를 통해 라운드 로빈으로 실행당 소스 **하나**를 동기화한 다음, 카탈로그를 다시 게시합니다. 부하를 분산하면 모든 업스트림을 한 번에 두드리는 것을 피할 수 있습니다.
  - **2분마다** — 새로운 익명 리포트를 내부 이슈 트래커 큐로 승격하는 내부 버그 리포트 트리아지 경로를 실행하며, 자체 워터마크 커서를 전진시킵니다. 이것은 내부 운영 도구입니다; 이슈 트래커/알림 식별자는 설정이며 공개 API의 일부가 아닙니다.

## 3. 카탈로그 및 source-url-only 강제

이것은 Lava의 컴플라이언스 자세에 가장 특화된 백엔드 부분이므로 서버 측에서 강력하게 적용됩니다.

### 3.1 source-url-only 모델

> **source-url-only:** GPL/IP 컴플라이언스 배포 모델: Lava는 업스트림 URL + 허용된 해시만 게시하고, 기기가 직접 목록을 가져와 파싱합니다. Lava는 서드파티 블록리스트 바이트를 **절대** 저장, 미러링, 변환, 또는 제공하지 않습니다.

각 `blocklist_sources` 행은 `redistribution_mode`를 가지며, 유일하게 허용된 값은 `"source_url_only"`입니다. 기기가 읽는 카탈로그(`/v1/catalog`, `schema_version` 2)는 항목을 `sources[]`와 `guardrails[]`로 나눕니다; 모든 항목은 업스트림 `source_url` 더하기 `accepted_source_hashes`(SHA-256 + 바이트 크기 + 항목 수 + `reviewed_at` + 상태 `accepted`)를 가집니다 — 목록 바이트는 절대 포함하지 않습니다. `formatCatalogEntry`를 참조하세요.

> **Dropped:** 이전 설계는 바이트가 보존된 GPL 목록 파일을 R2에 미러링했습니다(GPL-raw-R2 컴플라이언스 계획). 이것은 **2026-05-25에 source-url-only로 대체**되었습니다. Lava는 더 이상 서드파티 블록리스트 바이트를 저장하거나 제공하지 않습니다. `mirror_events` 테이블 이름은 그 폐기된 설계에서 남은 레거시 잔재입니다 — 이제는 그저 동기화/게시 감사 로그일 뿐입니다.

### 3.2 Worker가 쓰기에서 이를 강제하는 방법

동기화 경로(`syncOneBlocklist`, 관리자 및 cron)는 각 업스트림 `source_url`을 가져오고, **오직 메타데이터를 계산하기 위해 Worker 내부에서만 로컬로** 정규화/검증(`entry_count`, `source_hash`, `normalized_hash`, `byte_size`)한 뒤, `blocklist_versions` 행을 기록하고 다시 게시합니다. 바이트 저장 키는 null로 강제 기록됩니다:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

마이그레이션(`20260525000000_add_blocklist_distribution_mode.sql`)이 이 컬럼들을 nullable로 변경하고 기존 값을 null로 설정했으므로, no-mirror 입장은 스키마 수준에서도 강제됩니다. 게시된 카탈로그는 R2의 `catalog/{version}.json`과 `catalog/latest.json` **둘 다**에 기록됩니다(`publishCatalog`).

### 3.3 정규화 가드레일(메타데이터 전용)

Worker 측 정규화(`normalizeBlocklist`)는 보호된 도메인을 필터링하고, 상한선을 강제하며, 중복 제거+정렬을 수행합니다. 이것은 순전히 신뢰할 수 있는 메타데이터를 계산하기 위한 것입니다; **커뮤니티 목록**의 경우 기기는 다운로드를 해시-게이트하지 **않습니다** — 큐레이션된 `source_url`에서 TLS로 가져와 상한선 하에서 파싱합니다(카탈로그의 허용된 해시는 권고 사항). 따라서 이 Worker 측 정규화는 그 자체로 보안 경계가 아닙니다. (Lava의 위협-가드레일 티어는 기기에서 해시-고정된 상태로 유지되며, `source_url` 출처는 게시 시점에 강제됩니다 — URL 변경은 반드시 새로운 `list_id`를 사용해야 합니다.) 주요 상수:

- `PROTECTED_SUFFIXES` — Apple/iCloud/`mzstatic`/Lava Security 도메인/Supabase/Cloudflare/Google/GitHub와 일치하는 모든 규칙을 제거하여, 오염된 업스트림이 Lava 자체 인프라나 로그인 제공자를 차단할 수 없도록 합니다.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 게시 가능한 것

`isPublicBlocklistSource`는 `status`가 `sync` 또는 `nosync`이고, `redistribution_mode === "source_url_only"`이며, **그리고** `isAllowedLaunchGPLSource`를 통과할 때만 소스를 게시합니다. 런치-GPL 게이트(`isAllowedLaunchGPLSource`)는 비-GPL 소스를 자유롭게 허용하고, 정리된 GPL-3.0 소스 계열을 `list_id` 접두사로 허용합니다: `hagezi-`, `oisd-`, `adguard-`.

### 3.5 시드된 소스 및 default-enabled

큐레이션된 소스는 표준 [Blocklist Catalog](../legal/blocklist-catalog.md) 명세에서 생성되어 마이그레이션을 통해 source-url-only 메타데이터로 시드됩니다(HaGeZi, OISD, The Block List Project, Phishing.Database, StevenBlack, AdGuard, 1Hosts). 카테고리 확장 마이그레이션은 방어 심층(defensive-depth) 카테고리(nsfw/social/gambling/piracy)를 추가하고, 새 설치 기본값을 **Block List Basic**으로 재정렬하며, AdGuard DNS Filter를 법무 검토 플래그가 붙은 기본 비활성화 옵션으로 다시 활성화합니다. 상태: **Implemented**.

> **카탈로그 기본값은 클라이언트와 일치합니다.** 카탈로그의 `default_enabled` 집합은 **{Block List Basic}**입니다 — 이전의 Phishing + Scam 쌍을 대체하는 광범위하고 관대한 결합 목록 — iOS 권장 기본값(`AppConfiguration.lavaRecommendedDefaults`)과 일치합니다. 제공되는 `default_enabled` 컬럼과 번들된 iOS `DefaultCatalog`는 모두 동일한 표준 명세에서 생성되므로, 구성상 일치합니다(이로써 이전의 클라이언트↔백엔드 기본값 불일치가 해결됩니다). `default_enabled`는 정보 제공용임에 유의하세요: 실제 티어 게이트는 목록 수가 아니라 **필터-규칙 예산(Free 500K / Plus 2M)**입니다. URL을 게시하는(바이트가 아닌) 법적 근거는 [GPL source-url-only compliance decision](../legal/gpl-source-url-only-compliance-decision.md)에 있습니다.

## 4. Supabase Postgres

Supabase Postgres 프로젝트. RLS는 **모든** 공개 테이블에서 활성화되어 있습니다.

### 4.1 핵심 스키마

`20260516034033_backend_core.sql`은 기반을 생성합니다(7개의 모든 공개 테이블에 RLS 활성화):

- **`profiles`, `user_settings`, `entitlements`** — 사용자별 계정 상태. 트리거 `handle_new_user()`가 `auth.users` 삽입 시 `profiles` + `user_settings` 행을 자동 생성합니다.
- **`blocklist_sources`, `blocklist_versions`** — 카탈로그 메타데이터 테이블. 소스는 큐레이션된 업스트림 목록(`list_id`, `source_url`, 라이선스, 위험도, `default_enabled`, `status`, `redistribution_mode`)이고; 버전은 동기화된 스냅샷의 메타데이터(해시, `entry_count`, `byte_size`)로, `latest_version_id`를 통해 다시 연결됩니다.
- **`mirror_events`** — `sync` / `catalog_publish` 이벤트의 서비스 역할 전용 감사 로그(레거시 이름; §3.1 참조).
- **`bug_reports`** — 서비스 역할 전용 익명 리포트.

이후 마이그레이션은 **`user_backups`**(§4.3)와 **`qa_developers`**(`20260608000000_qa_developers_allowlist.sql`)를 추가합니다.

### 4.2 RLS 모델

| 테이블 | 정책 | 효과 |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | 사용자별 `auth.uid() = user_id` | 각 사용자는 자신의 행만 봄 |
| `blocklist_sources` | `status in ('sync','nosync')`인 경우 공개 읽기 (`backend_core.sql:262-266`) | 누구나 큐레이션된, 동기화 가능한 소스를 읽을 수 있음 |
| `blocklist_versions` | `validation_status = 'published'`인 경우 공개 읽기 (`backend_core.sql:268-272`) | 누구나 게시된 버전 메타데이터를 읽을 수 있음 |
| `bug_reports`, `mirror_events` | 명시적 `using(false)` (`20260516034136_backend_core_advisor_fixes.sql`) | anon/authenticated 액세스 없음 — Worker가 서비스 역할 사용 |
| `qa_developers` | RLS 켜짐 + **anon, authenticated에서 모두 revoke** | 서비스 역할 전용; QA 허용 목록은 클라이언트에서 절대 읽을 수 없음 |

이 분리가 중요합니다: 익명 버그 리포트는 클라이언트가 *읽을* 수 없으면서도 Worker가 *삽입할* 수 있어야 하고, QA 허용 목록은 오직 서비스 역할만 읽을 수 있어야 합니다.

### 4.3 인증 및 암호화된 백업 봉투(envelope)

**인증**은 선택 사항입니다. 로그인은 **Apple + Google 전용**입니다(이메일/비밀번호는 **Dropped**). 둘 다 해시된 nonce와 함께 Supabase Auth `auth/v1/token?grant_type=id_token`에서 교환되는 네이티브 `id_token` 그랜트를 사용합니다; 앱은 결과로 나온 세션만 Keychain에 기기-로컬로 저장합니다. 클라이언트 측 흐름은 iOS 앱(`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`)에 있습니다 — 전체 계정/백업 모델은 [Accounts & Backup](./accounts-and-backup.md)을 참조하세요.

> **제로 지식 백업:** 클라이언트 측 AES-256-GCM 봉투; 오직 암호문 + 비밀이 아닌 메타데이터만 Supabase `user_backups`(사용자별 RLS)에 업로드됩니다. 서버는 사용자가 보유한 비밀 없이는 복호화할 수 없습니다.

핵심 백엔드 사실: **iOS 클라이언트는 사용자별 RLS 하에서 Supabase PostgREST를 통해 `user_backups`를 직접 읽고 씁니다**(`user_id`에 대한 upsert, 액세스 토큰으로 범위 지정됨). Worker에는 `/v1/backup` 라우트가 전혀 **없습니다**. Worker가 `user_backups`를 건드리는 것은 정확히 한 번뿐입니다: 계정 삭제 중 이를 삭제할 때(`deleteAccount`).

`user_backups`는 오직 불투명한 암호문 + 비밀이 아닌 봉투 메타데이터(KDF 파라미터/솔트, nonce, 키-슬롯 레이블, 클라이언트 스키마 힌트)만 저장합니다. 크기 상한선(`20260605000000_tighten_backup_envelope_constraints.sql`): 암호문 ≤ 262144 바이트(256 KiB) / ≤ 349528 문자, 메타데이터 ≤ 32768 바이트(32 KiB). DB는 절대 평문 설정, 비밀번호, 구절(phrase), 또는 키를 저장하지 않습니다.

### 4.4 계정 삭제

`POST /v1/account/delete`는 사용자의 액세스 토큰을 검증한 다음, 해당 사용자의 `bug_reports`(및 일치하는 모든 레거시 R2 첨부파일 객체), `user_backups`, `entitlements`, `user_settings`, `profiles` 행을 삭제하고, 마지막으로 서비스 역할 `/admin/users` 엔드포인트를 통해 Supabase Auth 사용자를 삭제합니다. 삭제 상태 + 연결된 제공자만 반환합니다. 상태: **Implemented**(계획의 frontmatter는 `status: Done`이며 파일은 `plans/implemented/`에 있습니다; 오래된 **본문 내** 주석은 여전히 "Backlog"라고 표시되어 있지만, 레인 폴더 + 코드 존재가 출시되었음을 보여줍니다).

### 4.5 App Store 자격(entitlement) 미러링

`POST /v1/account/entitlements/app-store-sync`는 클라이언트가 검증한 StoreKit 트랜잭션 JWS로부터 `entitlements` 행(plan `lava_security_plus`)을 upsert하며, `user_id`에 대한 충돌 시 처리합니다. 저장된 `verification_status`는 문자 그대로 `"client_verified_storekit"`입니다 — 서버는 JWS를 재검증하지 **않습니다**. 허용된 제품 ID: `lava_security_plus_{monthly,yearly}`.

> 미러링은 **Implemented**입니다; **서버 측 JWS 검증은 Planned**(아직 미구현)입니다. 서명된 JWS는 나중의 검증을 위해 저장됩니다. 다른 곳의 티어 모델에 유의하세요: 앱 자격은 로컬(`isPaid`)이며 진실의 원천으로서 **아직 백엔드 동기화가 없습니다** — 이 행은 미러이지, 게이트가 아닙니다.

## 5. 패스키 보조 복구(제로 지식)

패스키 보조 백업 복구는 **제로 지식**이며 완전히 클라이언트 측에서 이루어집니다. 복구 키 자료는 패스키의 **WebAuthn PRF / hmac-secret** 출력으로부터 기기에서 파생됩니다; 서버는 복구 비밀을 **전혀** 저장하지 않고, 패스키를 **전혀** 등록하지 않으며, WebAuthn 챌린지를 **전혀** 발급하지 않습니다. 서버 게이트 에스크로 경로는 없습니다.

이전 설계가 사용한 에스크로 테이블(`backup_passkey_recovery`, `backup_passkey_challenges`)은 출시 전에 삭제되었고, Worker에는 `/v1/backup/*` 라우트도 WebAuthn/패스키 코드도 없습니다. (Worker의 `package.json`에 `@simplewebauthn/server` 항목이 사용되지 않는 잔여 의존성으로 남아 있습니다.)

클라이언트 측은 iOS 앱에 있습니다: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift`가 PRF 지원 패스키 생성/어설션을 구동하고, `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`가 hmac-secret 출력으로부터 슬롯을 파생합니다. PRF 출력은 어설션 중에만 읽히며 절대 기기를 떠나지 않습니다. 비-PRF 패스키 제공자는 제로 지식 슬롯을 뒷받침할 수 없으므로, 설정이 일찍 실패하고 사용자는 복구 구절로 폴백합니다. 상태: **Implemented**.

## 6. lavasec-email Worker

수신-및-전달 전용입니다. `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app`를 검증된 운영자 받은편지함으로 전달하고, 알 수 없는 수신자와 10 MiB를 초과하는 메일을 거부하며, **이메일 본문을 저장하지 않습니다**. 지원 자동 회신은 코드화되어 있지만 유료 Cloudflare 아웃바운드 이메일 뒤에 게이트되어 있습니다(연기됨). 라우팅 상수는 `email-service.ts:9`(`ROUTED_RECIPIENTS`)에 있습니다; 인바운드 핸들러는 `handleInboundEmail`입니다. 상태: **Implemented**(자동 회신 경로 **Planned**/연기됨).

## 7. 설정 및 배포

- **설정은 `wrangler.toml`이며, gitignore되어 있습니다**; `wrangler.toml.example`이 커밋된 템플릿입니다. 환경별 값에 대해서는 로컬 `wrangler.toml`을 표준으로 취급하세요.
- **Vars**(비밀 아님, `[vars]` 내): Supabase URL, 공개 API 오리진(`https://api.lavasecurity.app`), 카탈로그 캐시 TTL(기본 300s), 버그 리포트 크기 상한선, 계정 삭제 감사 토글, 그리고 Workers-런타임 가속 플래그. 내부 버그 리포트 트리아지는 내부 트리아지-큐 키와 트리아지 링크를 구성할 때 사용되는 대시보드 오리진을 추가합니다.
- **Secrets**(`wrangler secret put`을 통해): Supabase 서비스 역할 자격 증명, 관리자 API 키, 그리고 — 버그 리포트 트리아지 경로를 위한 — 이슈 트래커 API 키와 선택적 채팅 알림 웹훅.
- **배포는 수동입니다**: `npm run deploy` → `wrangler deploy`. Worker를 위한 CI는 없습니다.
- **Cloudflare 라우팅**: `lavasecurity.app`은 Pages에 그대로 있습니다; `api.lavasecurity.app`과 `*.qa-probe.lavasecurity.app`은 이 Worker로 해석됩니다.
- **호환성**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"`는 vars에 설정되어 있지만 Worker 코드에서 참조되지 않습니다; 이것은 애플리케이션 설정이라기보다 Workers-런타임 가속 플래그입니다.

## 8. 프라이버시 불변 조건(무엇이 여기에 있고 없는가)

백엔드를 확장하는 누구에게나 유용한 빠른 체크리스트 — 이 중 어느 것도 조용히 깨뜨려서는 안 됩니다:

1. **DNS/브라우징 텔레메트리 없음.** 일상적인 DNS 쿼리나 도메인별 텔레메트리를 위한 테이블이 없습니다. 필터링은 기기에 머뭅니다.
2. R2나 Postgres에 **서드파티 블록리스트 바이트 없음** — 오직 `source_url` + 허용된 해시만(§3).
3. **`user_backups`는 불투명** — 암호문 + 비밀이 아닌 메타데이터만; 클라이언트(Worker가 아님)가 RLS 하에서 이를 씁니다(§4.3).
4. `bug_reports`, `mirror_events`, `qa_developers`에 대한 **서비스 역할 격리**(§4.2).
5. **모든 백업 경로는 제로 지식** — 패스키 보조 복구를 포함하며, 그 키 자료는 WebAuthn PRF/hmac-secret 출력으로부터 클라이언트 측에서 파생됩니다. 서버는 복구 비밀을 저장하지 않고 WebAuthn을 실행하지 않습니다(§5).

## 함께 보기

- [System Overview](./system-overview.md) — 신뢰 경계를 포함한 전체 시스템을 한 페이지에.
- [iOS client](./ios-client.md) — 이 백엔드를 소비하는 기기 측.
- [Accounts & Backup](./accounts-and-backup.md) — 클라이언트 측 인증, AES-256-GCM 봉투, 키 슬롯, 그리고 복구 구절.
- [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) — 카탈로그의 기기 측: 직접 업스트림 다운로드, 파싱/정규화, 그리고 필터-규칙 예산.
- [GPL source-url-only compliance decision](../legal/gpl-source-url-only-compliance-decision.md) — 카탈로그가 왜 바이트가 아닌 URL을 게시하는지.
- **티어 및 수익화**(내부) — 실제 Free/Plus 게이트인 필터-규칙 예산(Free 500K / Plus 2M).
- **IP 위험 등록부**(내부) — source-url-only 뒤의 IP/컴플라이언스 근거.
