---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 시스템 개요

> **대상 독자:** 엔지니어. 이 문서는 Lava Security 전체를 한 페이지에 담은 것으로, 구성 요소가 무엇인지, 데이터가 그 사이를 어떻게 이동하는지, 신뢰 경계가 어디에 있는지를 설명합니다. 구성 요소별 문서는 더 깊이 들어가며, 이 문서는 그것들을 읽기 전에 시스템 전체를 머릿속에 담을 수 있도록 존재합니다.
>
> **권위:** 이 문서와 계획이 충돌할 경우 **코드가 우선합니다**. 상태는 계획의 지향점이 아니라 코드로 확인된 현실을 반영합니다. 하단의 [상태 범례](#8-status-legend)를 참고하세요.

## 1. 제품 한 줄 요약

Lava Security는 NetworkExtension 패킷 터널을 통해 **기기 내부에서 로컬로** DNS를 필터링하는 프라이버시 우선 iOS 앱으로, 비기술 사용자(부모, 고령자)를 위해 악성 및 원치 않는 도메인을 차단합니다 — 핵심 보호 기능은 영구 무료이며 계정이 필요하지 않습니다.

## 2. 프라이버시 약속 (정식)

> 모든 DNS 필터링은 기기에서 이루어집니다. Lava는 사용자의 브라우징을 자사 서버를 통해 라우팅하지 않으며, 사용자가 방문하는 도메인 스트림을 절대 수신하지 않습니다 — 백엔드는 카탈로그 메타데이터, 사용자별 불투명한 암호화 백업, 그리고 사용자가 보내기로 선택한 익명화된 진단 정보만 보유합니다.

아래의 모든 내용은 그 문장을 참으로 지키기 위한 것입니다. 아키텍처는 서버 측에서 의도적으로 작게 설계되어 있습니다. 기기가 작업을 수행하고, 백엔드는 쿼리를 절대 보지 않습니다.

## 3. 구성 요소

### iOS 클라이언트 (세 개의 실행 가능 타깃 + 공유 코드, 하나의 App Group `group.com.lavasec`)

| 구성 요소 | 번들 / 위치 | 역할 | 상태 |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | SwiftUI 앱 셸. 진입점, 두 탭 Guard + Settings 내비게이션 (Filter/Activity는 Guard 상세 화면이며, Network Activity는 Settings → Advanced 아래로 이동). | 구현됨 |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`. 기기 내 DNS 필터/리졸브 엔진. iOS의 **익스텐션당 ~50 MiB 메모리 상한**의 적용을 받습니다. | 구현됨 |
| **LavaSecWidget** | `com.lavasec.app.widget` | WidgetKit Live Activity (잠금 화면 + Dynamic Island). | 구현됨 |
| **Shared/** | `Shared/` | 타깃 간 공유 소스: App Group, 명령 서비스, 마스코트, Live Activity 속성/인텐트. | 구현됨 |

**앱 측 컨트롤러 (LavaSecApp 내부):**

- **AppViewModel** — 앱 측 컨트롤러(갓 오브젝트). `NETunnelProviderManager` 라이프사이클, 공유 상태 영속화, 프로바이더 메시징, Live Activity 조정, 카탈로그 동기화, 백업, StoreKit, 인증을 소유합니다.
- **RootView** — 두 탭 `TabView` (Guard + Settings)로, Filter와 Activity는 Guard 아래 상세 화면으로 도달합니다. 온보딩을 게이팅하고, 보안 잠금 / 프라이버시 마스크 오버레이를 호스팅합니다.
- **SecurityController** — 패스코드(Keychain 내 솔트 처리된 SHA256) + 생체 인증 + 표면별 보호.
- **LavaLiveActivityController** — 단일 Activity 조정기로, 중복 제거 및 리비전 게이팅됩니다.
- **OnboardingFlowView** — 다중 페이지 최초 실행 플로우 (6페이지: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (플랫폼 비종속 SwiftPM 패키지, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — 컴파일된 필터 + 결정 우선순위. compact 형식은 터널이 읽는 mmap 친화적인 온디스크 아티팩트입니다.
- **DNSQueryDispatcher** — 쿼리 우선순위: bootstrap > pause > filter.
- **ResolverOrchestrator** — 전송 라우팅, 평문 DNS 다운그레이드, 엔드포인트별 페일오버, device-DNS 폴백.
- **DoHTransport / DoTTransport / DoQTransport** — 암호화된 전송 실행기.
- **FeatureLimits** (`SubscriptionPolicy.swift` 내) — 티어 상한(진실의 원천), 정적 `.free` / `.paid` 멤버를 통해 제공됩니다.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — 기기 가드레일 계산 + union 이후의 권위 있는 예산 강제.
- **BlocklistCatalogSync / BlocklistParser** — 카탈로그 페치, 업스트림 직접 다운로드, 로컬 파싱/정규화/중복 제거, 보호 도메인 필터.
- **GuardianMascotAnimation** — 7상태 마스코트 상태 그래프 (`Shared/SoftShieldGuardian`에 의해 렌더링됨).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — 백업 암호화 + 페이로드.
- **SupabaseIDTokenAuth** — 원시 URLRequest `id_token` 인증 (SDK 없음).

### 백엔드

| 구성 요소 | 역할 | 상태 |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker (`api.lavasecurity.app`): 카탈로그 읽기, 관리자/cron 블록리스트 동기화 + 게시, 익명 버그 리포트, 계정 삭제, App Store 엔타이틀먼트 미러링, QA 프로브. | 구현됨 |
| **lavasec-email Worker** | `@lavasecurity.app`용 수신 전용 Cloudflare Email Routing 포워더. 알 수 없거나 과대한 메일은 거부합니다. | 구현됨 |
| **Supabase Postgres** | 계정, `user_backups`, 카탈로그 메타데이터, 서비스 역할 전용 테이블. **모든 public 테이블에 RLS 적용**. | 구현됨 |
| **Cloudflare R2** (프로덕션 R2 버킷, 스테이징용 별도 프리뷰 버킷) | 카탈로그 스냅샷 + 라운드로빈 동기화 커서. **절대로** 서드파티 블록리스트 바이트를 저장하지 않습니다. 버그 리포트 첨부 파일 업로드 경로는 제거되었습니다 (레거시 객체는 계정 삭제 시에만 삭제됨). | 구현됨 |
| **Cloudflare D1** (도움말 피드백 데이터베이스) | 추가 전용 익명 도움말 문서 피드백 투표. | 구현됨 |

## 4. 데이터 흐름 다이어그램

가장 중요한 단 하나의 속성: **암호화된 DNS 리졸버 경로(오른쪽)는 Lava의 백엔드(하단)와 절대 접촉하지 않습니다.** 기기는 Worker로부터 카탈로그 *메타데이터*를 페치하지만, 리스트 *바이트*와 실제 쿼리 스트림은 서드파티로 직접 전달됩니다.

```
                                  YOUR iPHONE
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                                                                             │
 │   ┌──────────────┐   provider messages    ┌───────────────────────────┐    │
 │   │  LavaSecApp  │ ─────────────────────►  │      LavaSecTunnel        │    │
 │   │ (AppViewModel│   (reload-snapshot /    │  (NEPacketTunnelProvider) │    │
 │   │  controller) │    pause / config)      │                           │    │
 │   └──────┬───────┘                         │   DNSQueryDispatcher       │   │
 │          │                                 │   bootstrap > pause >      │   │
 │          │ writes / reads                  │   ┌──────────────────────┐ │   │
 │          ▼                                 │   │  CompactFilterSnapshot│ │   │
 │   ┌──────────────────────────┐  mmap       │   │  guardrail > allow >  │ │   │
 │   │  App Group container      │ ◄──(read)── │   │  block > default-allow│ │   │
 │   │  group.com.lavasec        │            │   └──────────┬───────────┘ │   │
 │   │  • filter-snapshot.compact│            │              │ allowed     │   │
 │   │  • app-configuration.json │            │              ▼             │   │
 │   │  • tunnel-health.json      │           │   ┌──────────────────────┐ │   │
 │   │  • pause/session UserDefs  │           │   │  ResolverOrchestrator│ │   │
 │   └──────────────────────────┘             │   │  DoH3/DoT/DoQ/IP +   │ │   │
 │          ▲                                 │   │  device-DNS fallback │ │   │
 │          │ reads (Live Activity)           │   └──────────┬───────────┘ │   │
 │   ┌──────┴───────┐                         └──────────────│─────────────┘   │
 │   │ LavaSecWidget│                                        │                 │
 │   │ (Dynamic Isl.│                                        │ encrypted DNS   │
 │   │  + lock scr.)│                                        │ (query stream)  │
 │   └──────────────┘                                        │                 │
 └──────────────────────────────────────────────────────────│─────────────────┘
        │ (a) catalog          │ (b) list bytes              │ (c) blocked → NXDOMAIN
        │  metadata            │  (direct from upstream)     │     allowed → forwarded
        ▼                      ▼                             ▼
 ┌──────────────┐   ┌──────────────────────┐    ┌───────────────────────────────┐
 │ lavasec-api  │   │  Upstream blocklists  │   │  Public DNS resolver           │
 │ Worker       │   │  (HaGeZi, OISD,       │   │  (Quad9 / Cloudflare / Google  │
 │ GET /v1/     │   │   Block List Project) │   │   / Mullvad; user-chosen)       │
 │  catalog     │   └──────────────────────┘    └───────────────────────────────┘
 └──────┬───────┘
        │ reads/writes (metadata only)
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  LAVA BACKEND (sees no DNS queries, no browsing history)                   │
 │  • Supabase Postgres: accounts, user_backups (opaque ciphertext), catalog │
 │  • Cloudflare R2: catalog/latest.json, the round-robin cursor             │
 │  • lavasec-email Worker: receive-only @lavasecurity.app forwarding         │
 └──────────────────────────────────────────────────────────────────────────┘
       ▲
       │ (d) optional: encrypted backup envelope (PostgREST, RLS) — ciphertext only
       │     entitlement mirror, anonymous bug reports, account deletion
       └──── from LavaSecApp, only when the user opts in
```

## 5. 데이터 흐름

### A. DNS 경로 (쿼리당, 전부 기기 내부) — 구현됨

이것이 핫 패스이자 프라이버시의 핵심입니다. 전적으로 `LavaSecTunnel` 내부에서 실행되며, 여기 어떤 것도 Lava의 서버에 도달하지 않습니다.

1. 패킷 터널이 DNS 쿼리를 가로챕니다 (터널 DNS 서버 `10.255.0.1`).
2. **`DNSQueryDispatcher`**가 쿼리 우선순위를 적용합니다: **bootstrap > pause > filter**. bootstrap 우선은 엄격한 불변 조건으로, 리졸버 자신의 호스트네임이 어떤 필터링보다 먼저 해석되어 리졸버가 결코 자기 자신을 차단할 수 없도록 합니다.
3. bootstrap이 아니고 일시 정지 상태도 아니라면, 도메인은 **`CompactFilterSnapshot`**(App Group에서 `Data(contentsOf:options:[.mappedIfSafe])` 제로 카피 mmap으로 로드됨)에 대해 평가됩니다. 결정 우선순위는 **위협 가드레일 > 로컬 허용 목록(허용된 예외) > 블록리스트 > 기본 허용**이며, 유효하지 않은 도메인은 차단됩니다.
4. **차단됨** → 터널이 로컬에서 응답합니다 (업스트림 접촉 없음). **허용됨** → 쿼리가 **`ResolverOrchestrator`**로 전달됩니다.
5. `ResolverOrchestrator`는 구성된 전송 방식 — **`DoH3` / `DoT` / `DoQ` / 평문 DNS (`IP`)** — 으로 라우팅하며, 백오프 게이트 뒤의 엔드포인트별 페일오버, 암호화 플랜에 엔드포인트가 없을 때의 평문 DNS 다운그레이드, 그리고 기본 경로가 응답을 반환하지 않고 플랜이 허용할 때의 **device-DNS 폴백**을 포함합니다.
6. 리졸버 응답이 OS로 반환됩니다. 사용자의 쿼리 스트림은 **사용자가 선택한 공개 리졸버**에만 전달되며, Lava에는 절대 전달되지 않습니다.

전송 방식 참고 (정확한 표기 규약): `DoH3`(슬래시 없음)은 **실제로 h3 협상이 관찰될 때만** 표기됩니다 — 선호되지만 결코 보장되지는 않습니다. **`DoT`**는 엔드포인트당 최대 4개의 NWConnection을 풀링하며, 유휴 노후화 갱신 + 한 번의 새 연결 재시도를 동반합니다. **`DoQ`**는 **쿼리마다 새로운 QUIC 연결**을 엽니다 (재사용 없음). 4레인 풀은 동시성을 제공할 뿐 핸드셰이크 재사용을 제공하지 않습니다 — 연결 재사용은 구축되어 기기 테스트까지 거쳤으나 **되돌려졌습니다** (iOS-26 배포 하한이 정해질 때까지 연기). [DNS 필터링 & 블록리스트](./dns-filtering-and-blocklists.md)를 참고하세요.

### B. 카탈로그 페치 + 블록리스트 로드 (source-url-only) — 구현됨

필터 규칙이 기기에 올라오는 방식입니다. Lava는 **source-url-only** 배포자입니다: 업스트림 URL + 승인된 해시만 게시하며 **서드파티 블록리스트 바이트를 절대 저장, 미러링, 변환, 제공하지 않습니다.**

1. 기기가 Worker로부터 카탈로그 **메타데이터**를 페치합니다: `GET https://api.lavasecurity.app/v1/catalog` → R2(`catalog/latest.json`)에서 곧바로 제공되는 JSON으로, `sources[]` + `guardrails[]`로 나뉘며 각 항목은 `source_url` + `accepted_source_hashes`를 담고 있습니다.
2. 활성화된 각 소스에 대해, 기기는 리스트 **바이트를 `source_url`에서 직접** 다운로드합니다 (업스트림 — HaGeZi, OISD, Block List Project 등), Lava에서 다운로드하지 **않습니다**.
3. 기기는 페치한 바이트를 크기/규칙 상한 하에서 로컬로 파싱합니다. 커뮤니티 리스트는 TLS를 통해 제공된 그대로 수용됩니다 — 카탈로그의 `accepted_source_hashes`는 권고 사항(캐시 식별 + 감사)이지 엄격한 게이트가 아니므로 — 회전된 리스트가 고정된 해시에서 벗어났다는 이유로 거부되는 일은 결코 없습니다. Lava의 위협 가드레일 티어는 해시 고정 상태를 유지합니다.
4. **`BlocklistParser`**가 로컬에서 파싱/정규화/중복 제거합니다 (auto / plain / hosts / adblock / dnsmasq 형식). 그런 다음 **`DomainRuleSet.lavaSecProtectedDomains`**가 보호 도메인(apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …)을 제거하여, 업스트림 리스트가 Lava/Apple/신원 제공자 도메인을 결코 차단할 수 없도록 합니다.
5. **`FilterSnapshotPreparationService`**가 중복 제거된 union을 병합하고 **권위 있는 예산 강제**(기기 상한 먼저, 그다음 티어)를 실행한 뒤, `filter-snapshot.compact`를 App Group에 씁니다.
6. `AppViewModel`이 `reload-snapshot` 프로바이더 메시지를 보내고, 터널이 다시 로드합니다.

Worker 측은 이를 미러링합니다: 관리자/cron 동기화가 각 업스트림을 페치하고, 해시/카운트한 뒤, `raw_r2_key = null` / `normalized_r2_key = null`을 쓰고, 메타데이터만 다시 게시합니다. 블록리스트 카탈로그 모델과 백엔드 동기화 경로는 [DNS 필터링 & 블록리스트](./dns-filtering-and-blocklists.md) 및 [백엔드 & 데이터](./backend-and-data.md)에서 다룹니다.

**예산 모델 (두 계층):**
- **기기 가드레일 (모두에게 적용, 결코 유료 장벽이 아님):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3,262,236 규칙** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule` — ~50 MiB NE 상한 아래의 32 MB 목표. 예산을 초과하는 구성은 터널이 jetsam되도록 두지 않고 결정론적으로 거부됩니다.
- **티어 상한 (`FeatureLimits`):** **Free 500K 규칙 / Plus 2M 규칙**으로, 기기 가드레일보다 아래에서 적용됩니다. 이것은 기존의 활성화 목록 **개수** 상한(free 3 / paid 10)을 대체했습니다 — 목록 개수 상한은 더 이상 사용되지 않습니다.

> **기본 활성화 진실의 원천:** 출시된 무료 기본값은 **Block List Basic** (`OnboardingDefaults.lavaRecommendedDefaults`)입니다. 이것은 각 큐레이션된 소스의 `defaultEnabled` 플래그(`BlocklistSource.recommendedDefaultSourceIDs`)로부터 기기 내에서 도출되며, 이는 동일한 정식 카탈로그 사양에서 생성된 백엔드 카탈로그 `default_enabled` 컬럼을 미러링합니다.

### C. 백업 (제로 지식, 선택 가입) — 구현됨

선택 사항이며 계정 게이팅되어 있고, 백엔드에 도달하는 유일한 사용자 데이터입니다 — **불투명한 암호문** 형태로요.

1. 사용자는 Supabase Auth에서 교환되는 네이티브 `id_token`(`grant_type=id_token`, 해시된 nonce)을 통해 선택적으로 로그인할 수 있습니다 (Apple 또는 Google만. **이메일/비밀번호는 폐기됨**). 결과로 생성된 Supabase 세션만 기기 로컬의 Keychain에 저장됩니다.
2. **`BackupConfigurationPayload`**가 최소화된 평문(활성화된 블록리스트 ID, 허용/차단 도메인, 리졸버 설정, 로컬 로그 설정, LavaGuard 원장)을 조립합니다. 이는 `isPaid`, QA, 진단 정보, 전체 블록리스트를 **제외합니다**.
3. **`ZeroKnowledgeBackupEnvelope`**가 무작위 32바이트 페이로드 키 하에 **AES-256-GCM**으로 봉인합니다. 그 키는 **PBKDF2-HMAC-SHA256 (210k 반복)**을 통해 시크릿별 **키 슬롯** — 기기 시크릿 슬롯, 보조 복구 슬롯, 선택적 패스키 슬롯 — 으로 래핑됩니다. 선택적 패스키 슬롯은 인증기의 **WebAuthn PRF / `hmac-secret`** 출력(HKDF로 도출됨)으로 래핑됩니다. 그 출력은 클라이언트를 결코 떠나지 않으므로, 패스키 슬롯은 진정으로 제로 지식입니다 — 어떤 서버 보유 값도 그것을 언래핑하지 못합니다 (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`**가 **암호문 + 비밀이 아닌 메타데이터만**을 PostgREST를 통해 Supabase `user_backups`에 직접 업로드하며, 사용자별 **RLS**로 범위가 지정됩니다. (Worker 업로드 경로는 없습니다. Worker는 계정 삭제 중 `user_backups`를 삭제할 때만 접촉합니다.)
5. **복구:** 기기 시크릿 슬롯을 통한 매끄러운 동일 기기 복원. 기기 외부에서는 **8단어 CVCV 복구 문구**(~105비트)를 SHA256을 통해 서버 보유 복구 셰어와 결합하여 복구합니다 (이중 요소 — 어느 한쪽만으로는 복호화되지 않음). 또는 패스키 슬롯이 봉인되어 있었던 경우, 클라이언트 측 WebAuthn PRF / `hmac-secret` 출력(서버 보유 값 미관여)을 통해 복구합니다. 서버는 패스키를 등록하거나, WebAuthn 챌린지를 발급하거나, 어떤 복구 시크릿도 저장하지 않습니다.

[계정 & 백업](./accounts-and-backup.md)을 참고하세요.

### D. 앱 ↔ 익스텐션 제어 평면 — 구현됨

세 개의 프로세스(앱, 터널, 위젯)가 App Group `group.com.lavasec`을 통해 조정합니다:

- **제어 = NETunnelProviderSession 프로바이더 메시지**이며, Darwin 알림이 **아닙니다**. `AppViewModel`이 `LavaSecProviderMessage {kind, operationID}`를 인코딩하고 `session.sendProviderMessage`를 호출하면, 터널의 `handleAppMessage`가 kind(`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`)에 따라 분기합니다.
- **공유 파일**이 규칙/구성/상태를 운반합니다 (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`). **공유 UserDefaults 저장소**(`ProtectionSessionStore` / `ProtectionPauseStore`)가 세션 + 일시 정지 상태를 운반합니다.
- **`LavaProtectionCommandService`**가 Live Activity / AppIntent 일시 정지/재개 명령을 `flock` 파일 잠금 하에서 리비전 중복 제거 및 인증 필요 거부와 함께 실행합니다. **재연결은 이를 우회하여** 터널을 직접 재시작합니다 (`startVPNTunnel`).
- **Connect-On-Demand**는 터널이 연결을 확인한 *이후에만* 활성화되며, 프로파일 설치 시점에는 절대 활성화되지 않습니다 — 따라서 갓 설치된 온보딩 프로파일이 끌 수 없는 터널을 띄울 수 없습니다.

[iOS 클라이언트](./ios-client.md)를 참고하세요.

## 6. 신뢰 경계 & 프라이버시 보존 설계

| # | 경계 | 무엇이 그것을 넘나드는가 | 무엇이 의도적으로 넘나들지 않는가 |
|---|---|---|---|
| 1 | **기기 ↔ 공개 DNS 리졸버** | 허용된 DNS 쿼리(암호화: DoH3/DoT/DoQ, 또는 평문 IP)가 사용자가 선택한 리졸버로 갑니다. | Lava는 쿼리 스트림을 결코 보지 않으며, 이 경로에 전혀 존재하지 않습니다. |
| 2 | **기기 ↔ 업스트림 블록리스트 호스트** | 기기가 `source_url`에서 리스트 바이트를 직접 다운로드합니다. | Lava는 서드파티 블록리스트 바이트를 결코 프록시, 미러링, 저장하지 않습니다. |
| 3 | **기기 ↔ lavasec-api Worker** | 카탈로그 **메타데이터** 읽기. 선택 가입 익명 버그 리포트. 엔타이틀먼트 미러. 계정 삭제. | DNS 쿼리 없음, 브라우징 기록 없음, 평문 설정 없음. |
| 4 | **기기 ↔ Supabase** | 선택 가입 **암호화된 백업 봉투** (암호문만, RLS 하의 PostgREST). 계정 행. | 서버는 사용자 보유 시크릿 없이는 백업을 복호화할 수 없습니다. |
| 5 | **앱 ↔ 터널 익스텐션** (기기 내) | 프로바이더 메시지 + App Group 파일/디폴트. | 터널은 재사용 가능한 스냅샷이 없는 콜드 스타트에서 **닫힘**으로 실패합니다. |

**위 내용에 근거한 프라이버시 보존 설계 원칙:**

- **로컬 우선 필터링.** 결정 엔진과 리졸버는 기기의 NE 익스텐션 내부에서 실행됩니다. 백엔드는 구성상 메타데이터 전용입니다 — 일상적인 DNS 쿼리나 도메인별 텔레메트리를 위한 테이블이 없습니다.
- **보호에 계정 불필요.** 핵심 보호는 영구 무료이며, 인증과 백업은 엄격히 선택 가입입니다.
- **source-url-only 배포.** Lava를 서드파티 리스트 바이트로부터 분리하며 (GPL/IP 준수 + App Review 안전), "미러 코드 없음, Lava 아티팩트 URL 없음, R2 바이트 쓰기 없음"을 강제하는 CI 가드레일을 유지합니다.
- **저장 시 제로 지식 백업.** 클라이언트 측 AES-256-GCM. 서버는 암호문 + KDF 메타데이터 + 복구 셰어를 보유하며, 평문, 복구 문구, 언래핑된 키는 결코 보유하지 않습니다. 선택적 패스키 슬롯은 클라이언트 측 WebAuthn PRF / `hmac-secret` 출력으로 래핑되므로, 그것 역시 제로 지식입니다 — 어떤 서버 보유 값도 그것을 언래핑하지 못합니다.
- **기기 로컬 시크릿.** 백업 잠금 해제 자료는 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`를 사용합니다 — iCloud 동기화 안 됨, 기기 백업에 포함 안 됨.
- **서비스 역할 격리.** `bug_reports`, `mirror_events`, `qa_developers`는 anon/authenticated PostgREST 역할에서 회수되었으며, Worker(서비스 역할)만 그것들에 접촉합니다.
- **안전은 결코 판매 대상이 아닙니다.** 결제는 **커스터마이징만** 잠금 해제합니다. 결코 허용 불가능한 **위협 가드레일**을 우회하지 않으며, 그 무결성은 (서버 서명이 아닌) 승인된 SHA256 소스 해시로 강제됩니다. 우선순위는 어디에서나 일관됩니다: **위협 가드레일 > 로컬 허용 목록(허용된 예외) > 블록리스트 > 기본 허용.**

## 7. 구성 요소별 문서

> 이것들은 아키텍처 문서 세트의 형제 문서들입니다. DNS 필터링 엔진과 블록리스트 카탈로그는 하나의 파일에 함께 문서화되어 있습니다.

- [iOS 클라이언트](./ios-client.md) — 타깃, App Group, 제어 평면, 보호 상태 모델, 온보딩, Live Activity.
- [DNS 필터링 & 블록리스트](./dns-filtering-and-blocklists.md) — 필터 스냅샷, 결정 우선순위, 리졸버 전송 방식(DoH3/DoT/DoQ), 메모리 예산, mmap. 더불어 source-url-only 카탈로그 모델, 카탈로그 페치, 로컬 파싱/정규화, 보호 도메인 필터, 티어 예산.
- [계정 & 백업](./accounts-and-backup.md) — Apple/Google 인증, 제로 지식 봉투, 키 슬롯, 복구 문구, 클라이언트 측 WebAuthn-PRF 패스키 복구.
- [백엔드 & 데이터](./backend-and-data.md) — lavasec-api + lavasec-email Worker, Supabase 스키마 + RLS, R2/D1, 배포.

## 8. 상태 범례

이 문서 세트는 하나의 상태 어휘를 사용합니다. **레인 폴더가 권위 있는 상태**이며, 계획 내부의 오래된 프론트매터는 상태가 아니라 문서 버그입니다. **코드가 계획을 무시합니다.**

| 상태 | 의미 | 계획 레인 | 코드 |
|---|---|---|---|
| **구현됨** | 출시되어 코드에서 확인됨 | `plans/implemented/` | 존재 & 연결됨 |
| **진행 중** | 적극적으로 구축 중. 부분적으로 도착함 | `plans/inflight/`, `plans/under_review/` | 부분적으로 존재 |
| **계획됨** | 설계되었으나 구축되지 않음 | `plans/backlog/` | 부재 |
| **폐기됨** | 거부되거나 되돌려짐 | `plans/dropped/` (또는 되돌려진 커밋) | 부재 / 제거됨 |

**이 페이지에서 언급된 것들의 상태:**

- **구현됨:** 네 개의 iOS 타깃 + App Group; 프로바이더 메시지 제어 평면; DoH3/DoT/DoQ/IP 전송 방식을 사용한 기기 내 DNS 필터링; source-url-only 카탈로그 페치 + 로컬 파싱; 필터 규칙 예산(Free 500K / Plus 2M) + ~3.26M 기기 가드레일; 다중 페이지 온보딩; 패스코드/생체 보안; 단일 중복 제거된 Live Activity; 제로 지식 백업; Apple + Google 인증; 계정 삭제; 엔타이틀먼트 미러링; QA 프로브; `LavaDesignSystem` 토큰 계층(`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), 여기에는 `LavaTier` 깊이 모델(Floor/Window/Workshop = `calm`/`celebratory`/`technical`), 대표 표면(예: `SettingsView`)에 연결된 `.lavaTier(_:)` / `.lavaTierMetadata()` 수정자, 그리고 `dangerRed`와 `LavaSpacing` 토큰이 포함됩니다 — `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`로 잠금됨.
- **진행 중:** 디자인 시스템 토큰 계층의 더 많은 표면으로의 지속적인 롤아웃 (`LavaTier` 깊이 모델과 토큰 계층은 출시됨 — 아래 참고 — 그러나 전용 `LavaColorRole`은 아직 존재하지 않으므로 액센트는 여전히 원시 색상으로 해석됨).
- **계획됨:** Lava Guard 이스터에그 미니 게임; 추가 마스코트 표정 (마스코트는 정확히 **7**개 상태를 가짐); 물리적 기기에서 완전히 프로덕션 준비된 패스키 복구 (Associated Domains / AASA); 서버 측 App Store JWS 재검증 (`verification_status`는 `client_verified_storekit`); 디자인 시스템 액센트가 원시 색상이 아닌 의미론적 역할을 통해 해석되도록 하는 전용 `LavaColorRole` 토큰.
- **폐기됨:** DoQ 연결 재사용 (쿼리마다 새 연결); 이메일/비밀번호 로그인 (Apple + Google만); GPL 원시 R2 미러 설계 (source-url-only로 대체됨).
