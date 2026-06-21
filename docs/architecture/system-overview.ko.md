---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 시스템 개요

> **대상 독자:** 엔지니어. 이 문서는 Lava Security 전체를 한 페이지에 담은 것으로, 각 구성 요소가 무엇인지, 데이터가 그 사이를 어떻게 이동하는지, 신뢰 경계가 어디에 있는지를 다룹니다. 구성 요소별 문서가 더 깊이 들어가며, 이 문서는 그것들을 읽기 전에 시스템 전체를 머릿속에 담을 수 있도록 존재합니다.
>
> **권위:** 이 문서와 플랜이 어긋날 때는 **코드가 우선**입니다. 상태는 플랜의 지향점이 아니라 코드로 확인된 현실을 반영합니다. 하단의 [상태 범례](#8-status-legend)를 참고하세요.

## 1. 제품 한 줄 소개

Lava Security는 프라이버시를 최우선으로 하는 iOS 앱으로, NetworkExtension 패킷 터널을 통해 **기기에서 로컬로** DNS를 필터링하여, 기술에 익숙하지 않은 사용자(부모, 어르신)를 대상으로 악성 도메인과 원치 않는 도메인을 차단합니다 — 핵심 보호 기능은 영원히 무료이며 계정이 필요 없습니다.

## 2. 프라이버시 약속 (정본)

> 모든 DNS 필터링은 기기에서 이루어집니다. Lava는 사용자의 브라우징을 자사 서버로 라우팅하지 않으며, 사용자가 방문하는 도메인의 흐름을 결코 받지 않습니다 — 백엔드는 카탈로그 메타데이터, 사용자별 불투명한 암호화 백업, 그리고 사용자가 보내기로 선택한 익명화된 진단 정보만 보관합니다.

아래의 모든 내용은 그 문장을 참으로 유지하기 위한 것입니다. 아키텍처는 서버 측에서 의도적으로 작게 설계되어 있습니다. 작업은 기기가 수행하고, 백엔드는 결코 쿼리를 보지 않습니다.

## 3. 구성 요소

### iOS 클라이언트 (실행 가능한 타깃 3개 + 공유 코드, 하나의 App Group `group.com.lavasec`)

| 구성 요소 | 번들 / 위치 | 역할 | 상태 |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | SwiftUI 앱 셸. 진입점, 두 개의 탭으로 된 Guard + 설정 내비게이션(Filter/Activity는 Guard 세부 화면이며, Network Activity는 설정 → 고급 아래로 이동). | 구현됨 |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`. 기기 내 DNS 필터/해석 엔진. iOS의 **확장당 약 50 MiB 메모리 상한**의 적용을 받습니다. | 구현됨 |
| **LavaSecWidget** | `com.lavasec.app.widget` | WidgetKit Live Activity(잠금 화면 + Dynamic Island). | 구현됨 |
| **Shared/** | `Shared/` | 타깃 간 공유 소스: App Group, 명령 서비스, 마스코트, Live Activity 속성/인텐트. | 구현됨 |

**앱 측 컨트롤러 (LavaSecApp 내부):**

- **AppViewModel** — 앱 측 컨트롤러(갓 오브젝트). `NETunnelProviderManager` 라이프사이클, 공유 상태 영속화, provider 메시징, Live Activity 조정, 카탈로그 동기화, 백업, StoreKit, 인증을 담당합니다.
- **RootView** — 두 개의 탭으로 된 `TabView`(Guard + 설정)이며, Filter와 Activity는 Guard 아래의 세부 화면으로 도달합니다. 온보딩을 게이팅하고, 보안 잠금 / 프라이버시 마스크 오버레이를 호스팅합니다.
- **SecurityController** — 패스코드(Keychain에 솔트가 적용된 SHA256) + 생체 인증 + 표면별 보호.
- **LavaLiveActivityController** — 단일 Activity 조정자로, 중복 제거 및 리비전 게이팅이 적용됩니다.
- **OnboardingFlowView** — 여러 페이지로 된 최초 실행 플로우(6페이지: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (플랫폼 독립적인 SwiftPM 패키지, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — 컴파일된 필터 + 결정 우선순위. compact 형식은 터널이 읽는, mmap에 친화적인 디스크 상 아티팩트입니다.
- **DNSQueryDispatcher** — 쿼리 우선순위: bootstrap > pause > filter.
- **ResolverOrchestrator** — 전송 라우팅, plain-DNS 다운그레이드, 엔드포인트별 페일오버, 기기 DNS 폴백.
- **DoHTransport / DoTTransport / DoQTransport** — 암호화 전송 실행기.
- **FeatureLimits** (`SubscriptionPolicy.swift` 내부) — 등급 상한(진실의 원천)이며, 정적 멤버 `.free` / `.paid`를 통해 제공됩니다.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — 기기 가드레일 계산 + 합집합 이후의 권위 있는 예산 강제.
- **BlocklistCatalogSync / BlocklistParser** — 카탈로그 가져오기, 업스트림 직접 다운로드, 로컬 파싱/정규화/중복 제거, 보호 도메인 필터.
- **GuardianMascotAnimation** — 7가지 상태의 마스코트 상태 그래프(`Shared/SoftShieldGuardian`이 렌더링).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — 백업 암호화 + 페이로드.
- **SupabaseIDTokenAuth** — 순수 URLRequest 기반 `id_token` 인증(SDK 없음).

### 백엔드

| 구성 요소 | 역할 | 상태 |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker(`api.lavasecurity.app`): 카탈로그 읽기, 관리자/크론 차단목록 동기화 + 게시, 익명 버그 리포트, 계정 삭제, App Store 권한 미러링, QA 프로브. | 구현됨 |
| **lavasec-email Worker** | `@lavasecurity.app`을 위한 수신 전용 Cloudflare Email Routing 전달기. 알 수 없거나 크기가 과도한 메일은 거부합니다. | 구현됨 |
| **Supabase Postgres** | 계정, `user_backups`, 카탈로그 메타데이터, 서비스 역할 전용 테이블. **모든 public 테이블에 RLS 적용**. | 구현됨 |
| **Cloudflare R2** (프로덕션 R2 버킷, 스테이징용으로는 별도의 프리뷰 버킷) | 카탈로그 스냅샷 + 라운드 로빈 동기화 커서. 제3자 차단목록 바이트는 **결코** 저장하지 않습니다. 버그 리포트 첨부 업로드 경로는 제거되었습니다(레거시 객체는 계정 삭제 시에만 삭제됨). | 구현됨 |
| **Cloudflare D1** (도움말 피드백 데이터베이스) | 추가 전용 익명 도움말 문서 피드백 투표. | 구현됨 |

## 4. 데이터 흐름 다이어그램

가장 중요한 단 하나의 속성: **암호화된 DNS 해석기 경로(오른쪽)는 Lava 백엔드(하단)에 결코 닿지 않습니다.** 기기는 Worker로부터 카탈로그 *메타데이터*를 가져오지만, 목록 *바이트*와 실제 쿼리 흐름은 제3자에게 직접 전달됩니다.

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

### A. DNS 경로 (쿼리마다, 전부 기기 내) — 구현됨

이것이 핫 패스이자 프라이버시의 핵심입니다. 전적으로 `LavaSecTunnel` 내부에서 실행되며, 여기서는 어떤 것도 Lava의 서버에 닿지 않습니다.

1. 패킷 터널이 DNS 쿼리를 가로챕니다(터널 DNS 서버 `10.255.0.1`).
2. **`DNSQueryDispatcher`**가 쿼리 우선순위를 적용합니다: **bootstrap > pause > filter**. bootstrap 우선은 엄격한 불변 규칙입니다 — 해석기 자신의 호스트명이 어떤 필터링보다 먼저 해석되므로, 해석기가 결코 자기 자신을 차단할 수 없습니다.
3. bootstrap이 아니고 일시 정지 상태도 아니면, 도메인이 **`CompactFilterSnapshot`**(App Group에서 `Data(contentsOf:options:[.mappedIfSafe])` 제로카피 mmap으로 로드됨)에 대해 평가됩니다. 결정 우선순위는 **위협 가드레일 > 로컬 허용목록(허용된 예외) > 차단목록 > 기본 허용**이며, 유효하지 않은 도메인은 차단됩니다.
4. **차단됨** → 터널이 로컬에서 응답합니다(업스트림 접촉 없음). **허용됨** → 쿼리가 **`ResolverOrchestrator`**에 넘겨집니다.
5. `ResolverOrchestrator`는 구성된 전송 방식 — **`DoH3` / `DoT` / `DoQ` / plain DNS(`IP`)** — 로 라우팅하며, 백오프 게이트 뒤에서 엔드포인트별 페일오버, 암호화 플랜에 엔드포인트가 없을 때의 plain-DNS 다운그레이드, 그리고 기본 응답이 없고 플랜이 허용할 때의 **기기 DNS 폴백**을 수행합니다.
6. 해석기 응답이 OS로 반환됩니다. 사용자의 쿼리 흐름은 오직 **사용자가 선택한 공개 해석기**로만 가며, 결코 Lava로 가지 않습니다.

전송 방식 메모(표기 관례 그대로): `DoH3`(슬래시 없음)은 **실제로 h3 협상이 관찰될 때만** 표기됩니다 — 약속이 아니라 우선 선호. **`DoT`**는 엔드포인트당 최대 4개의 NWConnection을 풀링하며, 유휴 상태 노후화 갱신 + 새 연결 재시도 1회가 적용됩니다. **`DoQ`**는 **쿼리마다 새로운 QUIC 연결**을 엽니다(재사용 없음). 4레인 풀은 핸드셰이크 재사용이 아니라 동시성을 제공합니다 — 연결 재사용은 구축되어 기기에서 테스트되었으나 **되돌려졌습니다**(iOS-26 배포 하한까지 보류). [DNS 필터링 및 차단목록](./dns-filtering-and-blocklists.md)을 참고하세요.

### B. 카탈로그 가져오기 + 차단목록 로드 (source-url 전용) — 구현됨

필터 규칙이 어떻게 기기에 올라오는지에 대한 것입니다. Lava는 **source-url 전용** 배포자입니다. 업스트림 URL + 허용된 해시만 게시하며, 제3자 차단목록 바이트를 **결코 저장, 미러링, 변환, 제공하지 않습니다.**

1. 기기는 Worker로부터 카탈로그 **메타데이터**를 가져옵니다: `GET https://api.lavasecurity.app/v1/catalog` → R2(`catalog/latest.json`)에서 바로 제공되는 JSON으로, `sources[]` + `guardrails[]`로 나뉘며, 각 항목은 `source_url` + `accepted_source_hashes`를 담고 있습니다.
2. 활성화된 각 소스에 대해, 기기는 목록 **바이트를 `source_url`에서 직접** 다운로드합니다(업스트림 — HaGeZi, OISD, Block List Project 등). Lava에서가 **아닙니다.**
3. 기기는 SHA256을 계산하고 체크섬이 `accepted_source_hashes`에 있는 바이트만 받아들입니다. 불일치 시에는 마지막 정상 캐시로 폴백하거나 안전하게 닫힙니다(`checksumMismatch`).
4. **`BlocklistParser`**가 로컬에서 파싱/정규화/중복 제거를 수행하며(auto / plain / hosts / adblock / dnsmasq 형식), 이어서 **`DomainRuleSet.lavaSecProtectedDomains`**가 보호 도메인(apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …)을 제거하므로, 업스트림 목록이 결코 Lava/Apple/신원 제공자 도메인을 차단할 수 없습니다.
5. **`FilterSnapshotPreparationService`**가 중복 제거된 합집합을 병합하고 **권위 있는 예산 강제**(기기 상한 먼저, 그다음 등급)를 실행한 뒤, `filter-snapshot.compact`를 App Group에 씁니다.
6. `AppViewModel`이 `reload-snapshot` provider 메시지를 보내고, 터널이 다시 로드합니다.

Worker 측도 이를 반영합니다: 관리자/크론 동기화가 각 업스트림을 가져와 해시/카운트하고, `raw_r2_key = null` / `normalized_r2_key = null`을 쓰며, 메타데이터만 다시 게시합니다. 차단목록 카탈로그 모델과 백엔드 동기화 경로는 [DNS 필터링 및 차단목록](./dns-filtering-and-blocklists.md)과 [백엔드 및 데이터](./backend-and-data.md)에서 다룹니다.

**예산 모델 (두 계층):**
- **기기 가드레일(모두에게 적용, 결코 유료 장벽이 아님):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3,262,236 규칙** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule` — 약 50 MiB NE 상한 아래의 32 MB 목표치입니다. 예산을 초과하는 구성은 터널이 jetsam되게 두는 대신 결정론적으로 거부됩니다.
- **등급 상한(`FeatureLimits`):** **무료 500K 규칙 / Plus 2M 규칙**으로, 기기 가드레일 아래에서 바인딩됩니다. 이는 예전의 활성 목록 **개수** 상한(무료 3 / 유료 10)을 대체했습니다 — 목록 개수 상한은 더 이상 사용되지 않습니다.

> **기본 활성화 단서(코드 우선):** 출시된 무료 기본값은 **Block List Project Phishing + Scam**(`OnboardingDefaults.lavaRecommendedDefaults`)입니다. 이들은 큐레이션된 각 소스의 `defaultEnabled` 플래그(`BlocklistSource.recommendedDefaultSourceIDs`)로부터 기기 내에서 도출되며, 이것이 기기 내 진실의 원천이고 백엔드 카탈로그의 `default_enabled` 열을 반영합니다. "Block List Basic이 유일한 기본값"이라고 말하는 플랜/카탈로그 문구는 기기에 대해서는 틀렸습니다(내부적으로 추적 중).

### C. 백업 (제로 지식, 옵트인) — 구현됨

선택 사항이며, 계정으로 게이팅되고, 백엔드에 들어가는 유일한 사용자 데이터입니다 — **불투명한 암호문**으로서.

1. 사용자는 선택적으로 로그인합니다(Apple 또는 Google만. **이메일/비밀번호는 폐기됨**). Supabase Auth에서 교환되는 네이티브 `id_token`(`grant_type=id_token`, 해시된 nonce)을 통합니다. 결과로 나온 Supabase 세션만 기기 로컬로 Keychain에 저장됩니다.
2. **`BackupConfigurationPayload`**가 최소화된 평문(활성화된 차단목록 ID, 허용/차단 도메인, 해석기 설정, 로컬 로그 설정, LavaGuard 원장)을 조립합니다. 여기에는 `isPaid`, QA, 진단, 전체 차단목록이 **제외됩니다.**
3. **`ZeroKnowledgeBackupEnvelope`**가 무작위 32바이트 페이로드 키 아래에서 **AES-256-GCM**으로 봉인합니다. 그 키는 **PBKDF2-HMAC-SHA256(210k 반복)**을 통해 비밀별 **키 슬롯** — 기기 비밀 슬롯, 보조 복구 슬롯, 선택적 패스키 슬롯 — 으로 래핑됩니다. 선택적 패스키 슬롯은 인증기의 **WebAuthn PRF / `hmac-secret`** 출력(HKDF로 도출)으로 래핑되며, 그 출력은 클라이언트를 결코 벗어나지 않으므로 패스키 슬롯은 진정으로 제로 지식입니다 — 서버가 보유한 어떤 값도 그것을 풀지 못합니다(`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`**가 **암호문 + 비밀이 아닌 메타데이터만** PostgREST를 통해 Supabase `user_backups`에 직접 업로드하며, 사용자별 **RLS**로 범위가 지정됩니다. (Worker 업로드 경로는 없습니다. Worker는 계정 삭제 시 `user_backups`를 삭제하기 위해서만 접촉합니다.)
5. **복구:** 기기 비밀 슬롯을 통한 매끄러운 동일 기기 복원. 기기 밖에서는 **8단어 CVCV 복구 문구**(~105비트)를 SHA256을 통해 서버 보유 복구 셰어와 결합하여(두 요소 — 어느 한쪽만으로는 복호화 불가); 또는 패스키 슬롯이 봉인되었을 때는 클라이언트 측 WebAuthn PRF / `hmac-secret` 출력을 통해(서버 보유 값이 관여하지 않음) 복구합니다. 서버는 패스키를 결코 등록하지 않고, WebAuthn 챌린지를 발급하지 않으며, 어떤 복구 비밀도 저장하지 않습니다.

[계정 및 백업](./accounts-and-backup.md)을 참고하세요.

### D. 앱 ↔ 확장 제어 평면 — 구현됨

세 개의 프로세스(앱, 터널, 위젯)가 App Group `group.com.lavasec`을 통해 협응합니다:

- **제어 = NETunnelProviderSession provider 메시지**이며, Darwin 알림이 **아닙니다.** `AppViewModel`이 `LavaSecProviderMessage {kind, operationID}`를 인코딩하고 `session.sendProviderMessage`를 호출하면, 터널의 `handleAppMessage`가 kind에 따라 분기합니다(`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **공유 파일**이 규칙/구성/상태를 운반하고(`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`), **공유 UserDefaults 저장소**(`ProtectionSessionStore` / `ProtectionPauseStore`)가 세션 + 일시 정지 상태를 운반합니다.
- **`LavaProtectionCommandService`**가 Live Activity / AppIntent의 일시 정지/재개 명령을 `flock` 파일 잠금 아래에서 리비전 중복 제거 및 인증 필요 시 거부와 함께 실행합니다. **재연결은 이를 우회하여** 터널을 직접 재시작합니다(`startVPNTunnel`).
- **Connect-On-Demand**는 터널이 연결됨을 확인한 *이후에만* 활성화되며, 프로필 설치 시점에는 결코 활성화되지 않습니다 — 그래서 갓 설치된 온보딩 프로필이 끌 수 없는 터널을 띄울 수 없습니다.

[iOS 클라이언트](./ios-client.md)를 참고하세요.

## 6. 신뢰 경계 및 프라이버시 보존 설계

| # | 경계 | 무엇이 넘나드는가 | 의도적으로 넘지 않는 것 |
|---|---|---|---|
| 1 | **기기 ↔ 공개 DNS 해석기** | 허용된 DNS 쿼리(암호화: DoH3/DoT/DoQ, 또는 plain IP)가 사용자가 선택한 해석기로 갑니다. | Lava는 쿼리 흐름을 결코 보지 않으며, 이 경로에 전혀 없습니다. |
| 2 | **기기 ↔ 업스트림 차단목록 호스트** | 기기가 목록 바이트를 `source_url`에서 직접 다운로드합니다. | Lava는 제3자 차단목록 바이트를 결코 프록시, 미러링, 저장하지 않습니다. |
| 3 | **기기 ↔ lavasec-api Worker** | 카탈로그 **메타데이터** 읽기; 옵트인 익명 버그 리포트; 권한 미러; 계정 삭제. | DNS 쿼리 없음, 브라우징 기록 없음, 평문 설정 없음. |
| 4 | **기기 ↔ Supabase** | 옵트인 **암호화 백업 봉투**(암호문만, RLS 아래 PostgREST); 계정 행. | 서버는 사용자 보유 비밀 없이는 백업을 복호화할 수 없습니다. |
| 5 | **앱 ↔ 터널 확장** (기기 내) | provider 메시지 + App Group 파일/defaults. | 재사용 가능한 스냅샷이 없는 콜드 스타트에서 터널은 안전하게 **닫힙니다.** |

**위에 근거한 프라이버시 보존 설계 원칙:**

- **로컬 우선 필터링.** 결정 엔진과 해석기는 기기의 NE 확장 내부에서 실행됩니다. 백엔드는 구조적으로 메타데이터 전용입니다 — 일상적인 DNS 쿼리나 도메인별 텔레메트리를 위한 테이블이 없습니다.
- **보호에 계정 불필요.** 핵심 보호는 영원히 무료이며, 인증과 백업은 엄격히 옵트인입니다.
- **source-url 전용 배포.** Lava를 제3자 목록 바이트로부터 분리하고(GPL/IP 준수 + App Review 안전), "미러 코드 없음, Lava 아티팩트 URL 없음, R2 바이트 쓰기 없음"을 강제하는 CI 가드레일을 유지합니다.
- **저장 시 제로 지식 백업.** 클라이언트 측 AES-256-GCM. 서버는 암호문 + KDF 메타데이터 + 복구 셰어를 보유하며, 평문, 복구 문구, 풀린 키는 결코 보유하지 않습니다. 선택적 패스키 슬롯은 클라이언트 측 WebAuthn PRF / `hmac-secret` 출력으로 래핑되므로 그것 역시 제로 지식입니다 — 서버 보유 값이 그것을 풀지 못합니다.
- **기기 로컬 비밀.** 백업 잠금 해제 자료는 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`를 사용합니다 — iCloud 동기화되지 않고, 기기 백업에 포함되지 않습니다.
- **서비스 역할 격리.** `bug_reports`, `mirror_events`, `qa_developers`는 anon/authenticated PostgREST 역할로부터 철회되어 있으며, Worker(서비스 역할)만 그것들을 접촉합니다.
- **안전은 결코 판매 대상이 아님.** 결제는 **커스터마이징만** 잠금 해제합니다. 결제는 허용되지 않는 **위협 가드레일**을 결코 우회하지 않으며, 그 무결성은 (서버 서명이 아니라) 허용된 SHA256 소스 해시로 강제됩니다. 우선순위는 어디서나 일관됩니다: **위협 가드레일 > 로컬 허용목록(허용된 예외) > 차단목록 > 기본 허용.**

## 7. 구성 요소별 문서

> 이들은 아키텍처 문서 세트의 형제 문서들입니다. DNS 필터링 엔진과 차단목록 카탈로그는 하나의 파일에 함께 문서화되어 있습니다.

- [iOS 클라이언트](./ios-client.md) — 타깃, App Group, 제어 평면, 보호 상태 모델, 온보딩, Live Activity.
- [DNS 필터링 및 차단목록](./dns-filtering-and-blocklists.md) — 필터 스냅샷, 결정 우선순위, 해석기 전송 방식(DoH3/DoT/DoQ), 메모리 예산, mmap. 더불어 source-url 전용 카탈로그 모델, 카탈로그 가져오기, 로컬 파싱/정규화, 보호 도메인 필터, 등급 예산.
- [계정 및 백업](./accounts-and-backup.md) — Apple/Google 인증, 제로 지식 봉투, 키 슬롯, 복구 문구, 클라이언트 측 WebAuthn-PRF 패스키 복구.
- [백엔드 및 데이터](./backend-and-data.md) — lavasec-api + lavasec-email Worker, Supabase 스키마 + RLS, R2/D1, 배포.

## 8. 상태 범례 {#8-status-legend}

이 문서 세트는 하나의 상태 어휘를 사용합니다. **레인 폴더가 권위 있는 상태**이며, 플랜 내부의 오래된 프론트매터는 상태가 아니라 문서 버그입니다. **코드가 플랜을 우선합니다.**

| 상태 | 의미 | 플랜 레인 | 코드 |
|---|---|---|---|
| **구현됨** | 출시되었고 코드에서 확인됨 | `plans/implemented/` | 존재하며 연결됨 |
| **진행 중** | 적극적으로 구축 중. 일부 반영됨 | `plans/inflight/`, `plans/under_review/` | 일부 존재 |
| **계획됨** | 설계됨, 구축되지 않음 | `plans/backlog/` | 부재 |
| **폐기됨** | 거부되거나 되돌려짐 | `plans/dropped/`(또는 되돌린 커밋) | 부재 / 제거됨 |

**이 페이지에서 언급된 것들의 상태:**

- **구현됨:** 네 개의 iOS 타깃 + App Group; provider 메시지 제어 평면; DoH3/DoT/DoQ/IP 전송 방식을 갖춘 기기 내 DNS 필터링; source-url 전용 카탈로그 가져오기 + 로컬 파싱; 필터 규칙 예산(무료 500K / Plus 2M) + 약 3.26M 기기 가드레일; 여러 페이지 온보딩; 패스코드/생체 보안; 단일 중복 제거된 Live Activity; 제로 지식 백업; Apple + Google 인증; 계정 삭제; 권한 미러링; QA 프로브; `LavaDesignSystem` 토큰 계층(`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), 여기에는 `LavaTier` 깊이 모델(Floor/Window/Workshop = `calm`/`celebratory`/`technical`), 대표 표면(예: `SettingsView`)에 연결된 `.lavaTier(_:)` / `.lavaTierMetadata()` 수정자, 그리고 `dangerRed`와 `LavaSpacing` 토큰이 포함되며 — `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`로 고정되어 있습니다.
- **진행 중:** 더 많은 표면에 걸친 디자인 시스템 토큰 계층의 지속적인 롤아웃(`LavaTier` 깊이 모델과 토큰 계층은 출시되었으나 — 아래 참고 — 전용 `LavaColorRole`은 아직 존재하지 않아 액센트는 여전히 원시 색상으로 해석됩니다).
- **계획됨:** Lava Guard 이스터에그 미니 게임; 추가 마스코트 표정(마스코트는 정확히 **7**가지 상태); 실제 기기에서 완전히 프로덕션 준비된 패스키 복구(Associated Domains / AASA); 서버 측 App Store JWS 재검증(`verification_status`는 `client_verified_storekit`); 디자인 시스템 액센트가 원시 색상이 아니라 의미론적 역할을 통해 해석되도록 하는 전용 `LavaColorRole` 토큰.
- **폐기됨:** DoQ 연결 재사용(쿼리마다 새로운 연결); 이메일/비밀번호 로그인(Apple + Google만); GPL raw-R2 미러 설계(source-url 전용으로 대체됨).
