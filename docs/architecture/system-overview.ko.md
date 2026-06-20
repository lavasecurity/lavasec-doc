---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 시스템 개요

> **대상 독자:** 엔지니어. 이 문서는 Lava Security 전체를 한 페이지에 담은 것으로, 구성 요소가 무엇이고, 그 사이로 데이터가 어떻게 흐르며, 신뢰 경계가 어디에 있는지를 다뤄요. 구성 요소별 문서는 더 깊이 들어가지만, 이 문서는 그 문서들을 읽기 전에 시스템 전체를 머릿속에 그려볼 수 있게 하려고 있어요.
>
> **기준:** 이 문서와 계획(plan)이 어긋날 때는 **코드가 우선이에요**. 상태는 계획상의 목표가 아니라 코드로 확인된 현실을 반영해요. 맨 아래의 [상태 범례](#8-status-legend)를 참고하세요.

## 1. 제품 한 줄 소개

Lava Security는 프라이버시를 최우선으로 하는 iOS 앱으로, NetworkExtension 패킷 터널을 통해 DNS를 **기기 안에서 직접** 필터링해, 기술에 익숙하지 않은 사용자(부모님, 어르신)를 위해 악성 도메인과 원치 않는 도메인을 차단해요. 핵심 보호 기능은 영원히 무료이고 계정도 필요 없어요.

## 2. 프라이버시 약속 (정본)

> 모든 DNS 필터링은 기기에서 이루어져요. Lava는 여러분의 인터넷 사용을 자사 서버로 거치게 하지 않으며, 여러분이 방문하는 도메인 정보를 받지 않아요. 백엔드는 카탈로그 메타데이터, 사용자별로 암호화된 불투명한 백업, 그리고 여러분이 보내기로 선택한 익명 진단 정보만 보관해요.

아래의 모든 내용은 그 한 문장을 참되게 유지하기 위한 거예요. 아키텍처는 서버 쪽이 의도적으로 작아요. 일은 기기가 하고, 백엔드는 쿼리를 절대 보지 않아요.

## 3. 구성 요소

### iOS 클라이언트 (실행 가능한 타깃 3개 + 공유 코드, App Group 하나 `group.com.lavasec`)

| 구성 요소 | 번들 / 위치 | 역할 | 상태 |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | SwiftUI 앱 셸. 진입점, Guard와 설정 두 개 탭 내비게이션(Filters/Activity는 Guard 하위 상세 화면). | 구현됨 |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`. 기기 내 DNS 필터/해석 엔진. iOS의 **익스텐션당 약 50 MiB 메모리 상한**에 묶여 있어요. | 구현됨 |
| **LavaSecWidget** | `com.lavasec.app.widget` | WidgetKit Live Activity (잠금 화면 + Dynamic Island). | 구현됨 |
| **Shared/** | `Shared/` | 타깃 간 공유 소스: App Group, 명령 서비스, 마스코트, Live Activity 속성/인텐트. | 구현됨 |

**앱 쪽 컨트롤러 (LavaSecApp 내):**

- **AppViewModel** — 앱 쪽 컨트롤러(god-object). `NETunnelProviderManager` 라이프사이클, 공유 상태 영속화, 프로바이더 메시징, Live Activity 조정, 카탈로그 동기화, 백업, StoreKit, 인증을 담당해요.
- **RootView** — 두 개 탭 `TabView`(Guard + 설정). Filters와 Activity는 Guard 하위 상세 화면으로 접근하고, 온보딩을 게이팅하며, 보안 잠금 / 프라이버시 마스크 오버레이를 호스팅해요.
- **SecurityController** — 비밀번호(Keychain에 솔트가 적용된 SHA256) + 생체 인증 + 화면별 보호.
- **LavaLiveActivityController** — 단일 Activity 조정기. 중복 제거되고 리비전 게이팅돼요.
- **OnboardingFlowView** — 여러 페이지로 된 첫 실행 흐름(6페이지: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (플랫폼 독립 SwiftPM 패키지, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — 컴파일된 필터 + 결정 우선순위. compact 형태는 터널이 읽는, mmap에 적합한 디스크 상의 아티팩트예요.
- **DNSQueryDispatcher** — 쿼리 우선순위: bootstrap > pause > filter.
- **ResolverOrchestrator** — 전송 경로 라우팅, plain-DNS로의 하향, 엔드포인트별 페일오버, 기기-DNS 폴백.
- **DoHTransport / DoTTransport / DoQTransport** — 암호화 전송 실행기.
- **FeatureLimits** (`SubscriptionPolicy.swift` 내) — 등급별 상한(진실의 원천). 정적 멤버 `.free` / `.paid`를 통해 제공돼요.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — 기기 가드레일 계산 + 병합(union) 이후의 권위 있는 예산 적용.
- **BlocklistCatalogSync / BlocklistParser** — 카탈로그 가져오기, 업스트림 직접 다운로드, 로컬 파싱/정규화/중복 제거, 보호 도메인 필터.
- **GuardianMascotAnimation** — 7개 상태로 된 마스코트 상태 그래프(`Shared/SoftShieldGuardian`가 렌더링).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — 백업 암호화 + 페이로드.
- **SupabaseIDTokenAuth** — raw-URLRequest 기반 `id_token` 인증(SDK 없음).

### 백엔드

| 구성 요소 | 역할 | 상태 |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker (`api.lavasecurity.app`): 카탈로그 읽기, 관리자/크론 차단 목록 동기화 + 게시, 익명 버그 신고, 계정 삭제, App Store 권한 미러링, QA 프로브. | 구현됨 |
| **lavasec-email Worker** | `@lavasecurity.app`용 수신 전용 Cloudflare Email Routing 포워더. 알 수 없거나 용량을 초과한 메일은 거부해요. | 구현됨 |
| **Supabase Postgres** | 계정, `user_backups`, 카탈로그 메타데이터, 서비스 역할 전용 테이블. **모든 public 테이블에 RLS 적용**. | 구현됨 |
| **Cloudflare R2** (프로덕션 R2 버킷, 스테이징용 별도 프리뷰 버킷) | 카탈로그 스냅샷 + 라운드로빈 동기화 커서. 제3자 차단 목록 바이트는 **절대** 저장하지 않아요. 버그 신고 첨부 업로드 경로는 제거됐어요(레거시 객체는 계정 삭제 시에만 삭제돼요). | 구현됨 |
| **Cloudflare D1** (도움말 피드백 데이터베이스) | 추가 전용(append-only) 익명 도움말 문서 피드백 투표. | 구현됨 |

## 4. 데이터 흐름 다이어그램

가장 중요한 한 가지 속성: **암호화된 DNS 해석 경로(오른쪽)는 Lava의 백엔드(아래)에 절대 닿지 않아요.** 기기는 Worker에서 카탈로그 *메타데이터*를 가져오지만, 목록 *바이트*와 실제 쿼리 스트림은 제3자에게 곧장 가요.

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

### A. DNS 경로 (쿼리마다, 전부 기기 내에서) — 구현됨

이건 핫 패스이자 프라이버시의 핵심이에요. 전부 `LavaSecTunnel` 안에서 실행되며, 여기서는 어떤 것도 Lava의 서버에 닿지 않아요.

1. 패킷 터널이 DNS 쿼리를 가로채요(터널 DNS 서버 `10.255.0.1`).
2. **`DNSQueryDispatcher`**가 쿼리 우선순위를 적용해요: **bootstrap > pause > filter**. bootstrap 우선은 절대 깨지지 않는 불변 규칙이에요. 어떤 필터링보다 먼저 해석기 자신의 호스트명을 해석해서, 해석기가 자신을 차단하는 일이 없도록 해요.
3. bootstrap도 아니고 일시정지 상태도 아니면, 도메인을 **`CompactFilterSnapshot`**(App Group에서 `Data(contentsOf:options:[.mappedIfSafe])` 제로카피 mmap으로 로드)에 대조해 평가해요. 결정 우선순위는 **위협 가드레일 > 로컬 허용 목록(허용 예외) > 차단 목록 > 기본 허용**이에요. 유효하지 않은 도메인은 차단돼요.
4. **차단됨** → 터널이 로컬에서 응답해요(업스트림에 연결하지 않음). **허용됨** → 쿼리를 **`ResolverOrchestrator`**에 넘겨요.
5. `ResolverOrchestrator`는 설정된 전송 경로 — **`DoH3` / `DoT` / `DoQ` / plain DNS (`IP`)** — 로 라우팅해요. 백오프 게이트 뒤에서 엔드포인트별 페일오버를 두고, 암호화 플랜에 엔드포인트가 없으면 plain-DNS로 하향하며, 기본 경로가 응답을 반환하지 않고 플랜이 허용하면 **기기-DNS 폴백**을 써요.
6. 해석기 응답이 OS로 반환돼요. 사용자의 쿼리 스트림은 **사용자가 선택한 공용 해석기**로만 가고, Lava에는 절대 가지 않아요.

전송 경로 관련 메모(정확한 표기 규칙): `DoH3`(슬래시 없음)은 **실제로 h3 협상이 관측된 경우에만** 표기돼요. 선호하되, 약속하지는 않아요. **`DoT`**는 엔드포인트당 최대 4개의 NWConnection을 풀로 두고, idle 상태 갱신 + 한 번의 새 연결 재시도를 해요. **`DoQ`**는 **쿼리마다 새 QUIC 연결을 열어요**(재사용 없음). 4레인 풀은 동시성은 주지만 핸드셰이크 재사용은 주지 않아요. 연결 재사용은 만들어져 기기 테스트까지 거쳤지만 **되돌려졌어요**(iOS-26 배포 하한까지 보류). [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md)을 참고하세요.

### B. 카탈로그 가져오기 + 차단 목록 로드 (source-url-only) — 구현됨

필터 규칙이 기기에 들어오는 방식이에요. Lava는 **source-url-only** 배포자예요. 업스트림 URL + 허용 해시만 게시하며, 제3자 차단 목록 바이트를 **저장하거나, 미러링하거나, 변형하거나, 제공하지 않아요.**

1. 기기가 Worker에서 카탈로그 **메타데이터**를 가져와요: `GET https://api.lavasecurity.app/v1/catalog` → R2(`catalog/latest.json`)에서 곧바로 제공되는 JSON으로, `sources[]` + `guardrails[]`로 나뉘고 각 항목은 `source_url` + `accepted_source_hashes`를 담고 있어요.
2. 활성화된 각 소스에 대해, 기기는 목록 **바이트를 `source_url`에서 직접**(업스트림 — HaGeZi, OISD, Block List Project 등) 다운로드해요. Lava에서가 **아니에요**.
3. 기기는 SHA256을 계산하고, 체크섬이 `accepted_source_hashes`에 있는 바이트만 받아들여요. 불일치 시에는 마지막으로 정상이던 캐시로 폴백하거나 닫힌 상태로 실패해요(`checksumMismatch`).
4. **`BlocklistParser`**가 로컬에서 파싱/정규화/중복 제거를 하고(auto / plain / hosts / adblock / dnsmasq 형식), 이어서 **`DomainRuleSet.lavaSecProtectedDomains`**가 보호 도메인(apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …)을 걸러내요. 그래서 업스트림 목록이 Lava/Apple/신원 제공자 도메인을 차단하는 일이 절대 없어요.
5. **`FilterSnapshotPreparationService`**가 중복 제거된 병합본을 합치고 **권위 있는 예산 적용**(먼저 기기 상한, 그다음 등급)을 실행한 뒤, App Group에 `filter-snapshot.compact`를 써요.
6. `AppViewModel`이 `reload-snapshot` 프로바이더 메시지를 보내고, 터널이 다시 로드해요.

Worker 쪽도 이를 그대로 따라요. 관리자/크론 동기화가 각 업스트림을 가져와 해시/개수를 세고, `raw_r2_key = null` / `normalized_r2_key = null`을 쓴 뒤 메타데이터만 다시 게시해요. 차단 목록 카탈로그 모델과 백엔드 동기화 경로는 [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md)과 [백엔드 및 데이터](./backend-and-data.md)에서 다뤄요.

**예산 모델 (두 계층):**
- **기기 가드레일 (모두에게 적용, 유료화 수단이 아님):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3,262,236개 규칙** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule` — 약 50 MiB NE 상한 아래의 32 MB 목표예요. 예산을 초과하는 구성은 터널이 jetsam되게 두는 대신 결정론적으로 거부돼요.
- **등급 상한 (`FeatureLimits`):** **Free 50만 규칙 / Plus 200만 규칙**으로, 기기 가드레일보다 아래에서 적용돼요. 이는 예전의 활성화 목록 **개수** 상한(free 3 / paid 10)을 대체했어요 — 목록 개수 상한은 더 이상 쓰지 않아요.

> **기본 활성화 관련 주의 (코드가 우선):** 출시된 무료 기본값은 **Block List Project Phishing + Scam**(`OnboardingDefaults.lavaRecommendedDefaults`)이에요. 이는 각 큐레이션 소스의 `defaultEnabled` 플래그(`BlocklistSource.recommendedDefaultSourceIDs`)로부터 기기 내에서 도출되며, 이것이 기기 내 진실의 원천이고 백엔드 카탈로그의 `default_enabled` 열을 그대로 반영해요. "Block List Basic이 유일한 기본값"이라고 적힌 계획/카탈로그 문구는 기기 기준으로는 틀려요(내부적으로 추적 중).

### C. 백업 (제로 지식, 옵트인) — 구현됨

선택 사항이고 계정 기반이며, 백엔드에 들어가는 유일한 사용자 데이터예요 — **불투명한 암호문**으로요.

1. 사용자가 선택적으로 로그인해요(Apple 또는 Google만. **이메일/비밀번호는 폐기됨**). 네이티브 `id_token`을 Supabase Auth에서 교환해요(`grant_type=id_token`, 해시된 nonce). 결과로 나온 Supabase 세션만 기기 로컬의 Keychain에 저장돼요.
2. **`BackupConfigurationPayload`**가 최소화된 평문(활성화된 차단 목록 ID, 허용/차단 도메인, 해석기 설정, 로컬 로그 설정, LavaGuard 원장)을 모아요. `isPaid`, QA, 진단, 전체 차단 목록은 **제외해요**.
3. **`ZeroKnowledgeBackupEnvelope`**가 무작위 32바이트 페이로드 키 아래에서 **AES-256-GCM**으로 봉인해요. 그 키는 **PBKDF2-HMAC-SHA256(210k 반복)**을 통해 비밀별 **키 슬롯**으로 감싸져요 — 기기 비밀 슬롯, 보조 복구 슬롯, 선택적 패스키 슬롯. 선택적 패스키 슬롯은 인증기의 **WebAuthn PRF / `hmac-secret`** 출력(HKDF로 파생)으로 감싸지는데, 그 출력은 클라이언트를 절대 떠나지 않아요. 그래서 패스키 슬롯은 진정한 제로 지식이에요 — 그것을 풀어줄 서버 보유 값이 없어요(`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`**가 **암호문 + 비밀이 아닌 메타데이터만** PostgREST를 통해 Supabase `user_backups`에 직접 업로드하며, 사용자별 **RLS**로 범위가 한정돼요. (Worker 업로드 경로는 없어요. Worker는 계정 삭제 시 `user_backups`를 삭제할 때만 건드려요.)
5. **복구:** 기기 비밀 슬롯을 통한 같은 기기에서의 매끄러운 복원. 기기 밖에서는 **8단어 CVCV 복구 구문**(~105비트)을 서버 보유 복구 조각과 SHA256으로 결합(2요소 — 어느 한쪽만으로는 복호화 불가). 또는 패스키 슬롯이 봉인돼 있던 경우, 클라이언트 측 WebAuthn PRF / `hmac-secret` 출력으로 복구해요(서버 보유 값 없이). 서버는 패스키를 등록하거나, WebAuthn 챌린지를 발급하거나, 어떤 복구 비밀도 저장하지 않아요.

[계정 및 백업](./accounts-and-backup.md)을 참고하세요.

### D. 앱 ↔ 익스텐션 제어 평면 — 구현됨

세 개의 프로세스(앱, 터널, 위젯)가 App Group `group.com.lavasec`를 통해 조율해요:

- **제어 = NETunnelProviderSession 프로바이더 메시지**이지, Darwin 알림이 **아니에요**. `AppViewModel`이 `LavaSecProviderMessage {kind, operationID}`를 인코딩해 `session.sendProviderMessage`를 호출하면, 터널의 `handleAppMessage`가 kind에 따라 분기해요(`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **공유 파일**이 규칙/구성/상태를 담아요(`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`). **공유 UserDefaults 저장소**(`ProtectionSessionStore` / `ProtectionPauseStore`)가 세션 + 일시정지 상태를 담아요.
- **`LavaProtectionCommandService`**가 `flock` 파일 잠금 아래에서 Live Activity / AppIntent의 일시정지/재개 명령을 실행하며, 리비전 중복 제거와 인증 필요 시 거부를 적용해요. **재연결은 이를 우회해서** 터널을 직접 재시작해요(`startVPNTunnel`).
- **Connect-On-Demand**는 터널이 연결됐음을 확인한 *이후에만* 활성화되고, 프로파일 설치 시점에는 절대 켜지지 않아요. 그래서 갓 설치된 온보딩 프로파일이 끌 수 없는 터널을 켜버리는 일이 없어요.

[iOS 클라이언트](./ios-client.md)를 참고하세요.

## 6. 신뢰 경계 및 프라이버시 보존 설계

| # | 경계 | 무엇이 넘나드는가 | 의도적으로 넘지 않는 것 |
|---|---|---|---|
| 1 | **기기 ↔ 공용 DNS 해석기** | 허용된 DNS 쿼리(암호화: DoH3/DoT/DoQ, 또는 plain IP)가 사용자가 선택한 해석기로 가요. | Lava는 쿼리 스트림을 절대 보지 않으며, 이 경로에 전혀 끼어 있지 않아요. |
| 2 | **기기 ↔ 업스트림 차단 목록 호스트** | 기기가 `source_url`에서 목록 바이트를 직접 다운로드해요. | Lava는 제3자 차단 목록 바이트를 프록시하거나, 미러링하거나, 저장하지 않아요. |
| 3 | **기기 ↔ lavasec-api Worker** | 카탈로그 **메타데이터** 읽기, 옵트인 익명 버그 신고, 권한 미러, 계정 삭제. | DNS 쿼리도, 인터넷 사용 기록도, 평문 설정도 없어요. |
| 4 | **기기 ↔ Supabase** | 옵트인 **암호화 백업 봉투**(암호문만, RLS 하의 PostgREST), 계정 행. | 서버는 사용자 보유 비밀 없이는 백업을 복호화할 수 없어요. |
| 5 | **앱 ↔ 터널 익스텐션** (기기 내) | 프로바이더 메시지 + App Group 파일/디폴트. | 재사용 가능한 스냅샷이 없는 콜드 스타트에서 터널은 닫힌 상태로 **실패해요**. |

**위 내용에 근거한 프라이버시 보존 설계 원칙:**

- **로컬 우선 필터링.** 결정 엔진과 해석기가 기기의 NE 익스텐션 안에서 실행돼요. 백엔드는 설계상 메타데이터 전용이에요 — 일상적인 DNS 쿼리나 도메인별 텔레메트리를 위한 테이블이 없어요.
- **보호에 계정이 필요 없음.** 핵심 보호 기능은 영원히 무료이고, 인증과 백업은 철저히 옵트인이에요.
- **source-url-only 배포.** Lava를 제3자 목록 바이트로부터 분리하고(GPL/지식재산권 준수 + App Review 안전성), "미러 코드 없음, Lava 아티팩트 URL 없음, R2 바이트 쓰기 없음"을 강제하는 CI 가드레일을 유지해요.
- **저장 시 제로 지식 백업.** 클라이언트 측 AES-256-GCM. 서버는 암호문 + KDF 메타데이터 + 복구 조각을 보유하되, 평문도, 복구 구문도, 풀린 키도 보유하지 않아요. 선택적 패스키 슬롯은 클라이언트 측 WebAuthn PRF / `hmac-secret` 출력으로 감싸져서 이 역시 제로 지식이에요 — 그것을 풀어줄 서버 보유 값이 없어요.
- **기기 로컬 비밀.** 백업 잠금 해제 자료는 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`를 사용해요 — iCloud로 동기화되지 않고, 기기 백업에도 포함되지 않아요.
- **서비스 역할 격리.** `bug_reports`, `mirror_events`, `qa_developers`는 anon/authenticated PostgREST 역할에서 권한이 취소돼 있어요. 오직 Worker(서비스 역할)만 이를 건드려요.
- **안전은 절대 판매 대상이 아님.** 결제는 **커스터마이징만** 잠금 해제해요. 허용 불가한 **위협 가드레일**을 절대 우회하지 않으며, 그 무결성은 (서버 서명이 아니라) 허용된 SHA256 소스 해시로 강제돼요. 우선순위는 어디서나 일관돼요: **위협 가드레일 > 로컬 허용 목록(허용 예외) > 차단 목록 > 기본 허용.**

## 7. 구성 요소별 문서

> 이들은 아키텍처 문서 세트의 형제 문서예요. DNS 필터링 엔진과 차단 목록 카탈로그는 한 파일에 함께 문서화돼 있어요.

- [iOS 클라이언트](./ios-client.md) — 타깃, App Group, 제어 평면, 보호 상태 모델, 온보딩, Live Activity.
- [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md) — 필터 스냅샷, 결정 우선순위, 해석기 전송 경로(DoH3/DoT/DoQ), 메모리 예산, mmap. 그리고 source-url-only 카탈로그 모델, 카탈로그 가져오기, 로컬 파싱/정규화, 보호 도메인 필터, 등급 예산.
- [계정 및 백업](./accounts-and-backup.md) — Apple/Google 인증, 제로 지식 봉투, 키 슬롯, 복구 구문, 클라이언트 측 WebAuthn-PRF 패스키 복구.
- [백엔드 및 데이터](./backend-and-data.md) — lavasec-api + lavasec-email Worker, Supabase 스키마 + RLS, R2/D1, 배포.

## 8. 상태 범례

이 문서 세트는 하나의 상태 어휘를 써요. **레인 폴더가 권위 있는 상태**예요. 계획 안의 오래된 frontmatter는 상태가 아니라 문서 버그예요. **코드가 계획을 무효화해요.**

| 상태 | 의미 | 계획 레인 | 코드 |
|---|---|---|---|
| **구현됨** | 출시됐고 코드에서 확인됨 | `plans/implemented/` | 존재하며 연결됨 |
| **진행 중** | 적극적으로 구축 중. 일부 반영됨 | `plans/inflight/`, `plans/under_review/` | 일부 존재 |
| **계획됨** | 설계됐으나 구축되지 않음 | `plans/backlog/` | 없음 |
| **폐기됨** | 거부되거나 되돌려짐 | `plans/dropped/` (또는 되돌린 커밋) | 없음 / 제거됨 |

**이 페이지에서 언급된 것들의 상태:**

- **구현됨:** 네 개의 iOS 타깃 + App Group. 프로바이더 메시지 제어 평면. DoH3/DoT/DoQ/IP 전송 경로를 갖춘 기기 내 DNS 필터링. source-url-only 카탈로그 가져오기 + 로컬 파싱. 필터 규칙 예산(Free 50만 / Plus 200만) + 약 326만 기기 가드레일. 여러 페이지 온보딩. 비밀번호/생체 인증 보안. 중복 제거된 단일 Live Activity. 제로 지식 백업. Apple + Google 인증. 계정 삭제. 권한 미러링. QA 프로브. `LavaDesignSystem` 토큰 계층(`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`) — 여기에는 `LavaTier` 깊이 모델(Floor/Window/Workshop = `calm`/`celebratory`/`technical`), 대표 화면(예: `SettingsView`)에 연결된 `.lavaTier(_:)` / `.lavaTierMetadata()` 모디파이어, 그리고 `dangerRed`와 `LavaSpacing` 토큰이 포함되며, `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`로 고정돼 있어요.
- **진행 중:** 디자인 시스템 토큰 계층을 더 많은 화면으로 계속 확산 중(`LavaTier` 깊이 모델과 토큰 계층은 출시됐지만 — 아래 참고 — 전용 `LavaColorRole`은 아직 없어서, 강조색은 여전히 원시 색상으로 해석돼요).
- **계획됨:** Lava Guard 이스터에그 미니게임. 추가 마스코트 표정(마스코트는 정확히 **7**개 상태). 실제 기기에서 완전히 프로덕션 준비가 된 패스키 복구(Associated Domains / AASA). 서버 측 App Store JWS 재검증(`verification_status`는 `client_verified_storekit`). 디자인 시스템 강조색이 원시 색상이 아니라 의미적 역할을 거쳐 해석되도록 하는 전용 `LavaColorRole` 토큰.
- **폐기됨:** DoQ 연결 재사용(쿼리마다 새 연결). 이메일/비밀번호 로그인(Apple + Google만). GPL raw-R2 미러 설계(source-url-only로 대체됨).
