---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 기능 카탈로그

> 대상 독자: PM / 엔지니어링. 이 카탈로그는 **현재 구현된** 기능 집합만 다룹니다. 설계되었으나 아직 구현되지 않은 항목은 여기가 아니라 비공개 로드맵에 있습니다.

Lava Security는 NetworkExtension 패킷 터널을 통해 **기기에서 로컬로** DNS를 필터링하는 프라이버시 우선 iOS 앱으로, 비기술 사용자(부모, 고령자)를 위해 악성 및 원치 않는 도메인을 차단합니다. 핵심 보호 기능은 영구 무료이며 계정이 필요하지 않습니다.

아래 모든 기능 뒤에 있는 프라이버시 약속:

> 모든 DNS 필터링은 기기에서 이루어집니다. Lava는 사용자의 브라우징을 자사 서버로 라우팅하지 않으며 사용자가 방문하는 도메인 스트림을 받지 않습니다. 백엔드는 카탈로그 메타데이터, 사용자별 불투명 암호화 백업, 그리고 사용자가 보내기로 선택한 익명화된 진단 정보만 보유합니다.

## 이 카탈로그를 읽는 방법

- **Free** — 누구나 사용 가능, 계정 불필요, 구매 불필요.
- **Plus** — Lava Security Plus로 잠금 해제되는 유일한 선택형 유료 등급. Plus는 **커스터마이징만** 잠금 해제하며, 기본 안전 기능을 결코 제한하지 않고 유료 사용자가 위협 가드레일을 우회하도록 절대 허용하지 않습니다.
- 모든 행은 인라인으로 표시되지 않는 한 **Implemented**입니다. 상태 범례: **Implemented** = 출시되어 코드에서 확인됨; **Planned** = 설계됨, 미구현; **Dropped** = 거부 또는 되돌림. Planned/Dropped 항목은 여기가 아니라 비공개 로드맵에 문서화되어 있습니다.

등급별 상한의 단일 진실 공급원(source of truth)은 `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`(`FeatureLimits.free` / `FeatureLimits.paid`, `.plus`로 별칭 지정)에 있습니다. Plus 권한 **게이트**는 로컬 플래그(`isPaid`)이며, 이것이 진실 공급원입니다. 백엔드는 App Store 권한을 **미러링**하지만(`POST /v1/account/entitlements/app-store-sync`가 `entitlements` 행을 upsert함), 그 행은 게이트가 아니라 미러일 뿐입니다. 아직 어떤 백엔드 동기화도 게이팅을 구동하지 않습니다.

---

## 1. 보호 및 VPN

핵심 제품: 로컬 DNS 전용 패킷 터널과 이를 둘러싼 차분한 상태 모델.

| 기능 | 등급 | 비고 |
|---|---|---|
| **로컬 DNS 전용 패킷 터널** | Free | `LavaSecTunnel`(`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`)이 DNS를 가로채어 각 도메인을 기기에서 평가합니다. 어떤 브라우징 트래픽도 Lava를 통해 라우팅되지 않습니다. 터널 주소 `10.255.0.2`, DNS 서버 `10.255.0.1`. |
| **필터 결정 우선순위** | Free | `threat guardrail block > local allowlist (allowed exceptions) > blocklist > default-allow`; 유효하지 않은 도메인은 차단됩니다. (`FilterSnapshot.decision()`.) |
| **쿼리 우선순위(부트스트랩 우선)** | Free | `resolver-bootstrap > temporary-pause > filter` — 리졸버 자체의 호스트명은 절대 차단되지 않습니다. (`DNSQueryDispatcher`.) |
| **Fail-closed 콜드 스타트** | Free | 재사용 가능한 스냅샷이 없는 콜드 터널은 필터링되지 않은 DNS를 유출하는 대신 모든 트래픽을 차단하는 `FailClosedRuntimeSnapshot`을 설치합니다. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect`는 보호 기능을 유지하거나 자동 재시작합니다. **확인된 연결 이후에만** 활성화되며, 프로파일 설치 시점에는 절대 활성화되지 않고, 미완료 온보딩 중에는 무력화되어 새로 설치한 경우 끌 수 없는 터널이 올라오지 않습니다. |
| **임시 일시정지(1~30분 설정 가능, 기본값 5) + 재개** | Free | 일시정지/재개는 리비전 중복 제거가 적용된 flock 파일 잠금 하에서 `LavaProtectionCommandService`를 통해 실행됩니다. |
| **인증 필요 일시정지** | Free | 표면별 옵트인 게이트(`SecurityProtectedSurface.protectionPause`): 일시정지에는 로컬 기기 인증이 필요합니다. 커맨드 서비스는 인증되지 않은 일시정지를 거부하고 Live Activity는 일시정지 버튼을 숨깁니다. |
| **재연결** | Free | 터널을 직접 재시작합니다(커맨드 서비스의 일시정지 파이프라인을 우회). |
| **Soft Shield Guardian 상태 모델** | Free | 7가지 표정 상태 — `sleeping, waking, awake, paused, retrying, concerned, grateful`(`GuardianMascotAnimation.swift`, LavaSecCore). 6가지 연결 심각도가 4개의 얼굴로 축약되며, 앱 내, 온보딩, Live Activity에서 동일하게 렌더링됩니다. |
| **연결성 평가** | Free | 6가지 심각도(`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`)가 guardian 얼굴과 상태 문구를 구동합니다. |
| **성능 하드닝** | Free | 캐시 우선 켜기, 진행 중 쿼리 병합, 제한된 병렬 페치, 플랩 병합(모듈식 속도 개선 작업 기준 iPhone 15 Pro에서 웜 켜기 측정값 약 112 ms). |

> **기기 가드레일(모두에게 적용, 절대 유료 장벽 아님):** 모든 사용자에 대해 등급을 초월하여 하드 `~3.26M-rule` 상한(iOS `~50 MiB` 익스텐션당 메모리 상한 아래의 32 MB 상주 목표)이 적용됩니다(`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). 예산 초과 구성은 터널이 jetsam되도록 두는 대신 결정적으로 거부됩니다(`exceedsDeviceMemoryBudget`).

---

## 2. 차단 목록 및 필터링

무엇이 차단되는지, 목록이 어떻게 선택되는지, 그리고 등급 경계.

| 기능 | 등급 | 비고 |
|---|---|---|
| **소스 URL 전용 차단 목록** | Free | Lava는 업스트림 URL + 허용된 해시만 게시하며, 기기가 직접 목록 **바이트**를 페치/파싱합니다. Lava는 제3자 차단 목록 바이트를 **절대** 저장, 미러링, 변환, 제공하지 않습니다. [GPL 소스 URL 전용 준수 결정](../legal/gpl-source-url-only-compliance-decision.md) 참조. |
| **큐레이션된 카탈로그(분류됨)** | 활성화 무료 | 방어 심층화 카테고리로 구성된 큐레이션 소스 — Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling, Piracy & Torrent — HaGeZi, The Block List Project, OISD, StevenBlack, AdGuard, 1Hosts, Phishing.Database 제공. 전체 최신 집합은 [Blocklist Catalog](../legal/blocklist-catalog.md)에 게시되어 있으며, 각 플랫폼은 함께 출시된 카탈로그 버전을 반영합니다. |
| **무료 기본 차단 목록** | Free | 새로 설치하면 **Block List Basic** — 광범위하고 관대한 결합 목록(소스에 `defaultEnabled: true` 플래그; `DefaultCatalog.recommendedDefaultSourceIDs`)이 활성화됩니다. 나머지 모든 것은 옵트인입니다. |
| **기기 내 파싱 / 정규화 / 중복 제거** | Free | `BlocklistParser`는 auto/plain/hosts/adblock/dnsmasq를 지원하고, 주석/공백/유효하지 않은 항목을 삭제하며, 정확히 일치하는 문자열을 중복 제거하고, 목록당 1,000,000개 규칙으로 상한을 둡니다. 다중 호스트 `hosts` 줄은 이제 첫 번째뿐만 아니라 줄의 **모든** 호스트를 방출합니다(파서 규칙 버전 2). |
| **업스트림 무결성(TLS + 큐레이션 URL)** | Free | 커뮤니티 목록 바이트는 큐레이션된 업스트림 `source_url`에서 직접 TLS로 페치되며 크기 + 형식 + 규칙 수 상한을 조건으로 수락됩니다. 카탈로그의 `accepted_source_hashes`는 **권고용**(캐시 식별 + 감사)이며 하드 게이트가 아닙니다 — 빠르게 회전하는 목록이 고정된 해시에서 벗어났다고 해서 거부되지 않습니다. Lava의 **위협 가드레일** 등급(Lava 큐레이션, 허용 불가)은 엄격하게 해시 고정 상태를 유지합니다. |
| **보호 도메인 필터** | Free | 파싱된 모든 소스에서 보호된 Lava / Apple / 신원 제공자 도메인(apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com 등)이 제거되어, 업스트림 목록이 앱, 터널, 로그인을 망가뜨릴 수 없습니다. |
| **Allowed Exceptions(허용 목록)** | Free | 차단 목록에도 불구하고 도메인을 허용하는 사용자 관리 허용 목록. 무료 상한: 허용 25개 / 차단 25개 도메인(`FeatureLimits.free`). |
| **필터 규칙 예산(등급 지표)** | Free / Plus | 출시된 등급 지표는 컴파일된 총 도메인 **규칙** 수입니다: **Free 500K / Plus 2M**(`lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`의 `maxFilterRules`). 기존 목록 수 상한을 대체합니다. 등급 초과 구성은 `exceedsTierFilterRuleLimit`로 표면화됩니다. |
| **더 높은 도메인 한도** | Plus | 허용 1,000개 / 차단 1,000개 도메인(`FeatureLimits.plus`). |
| **사용자 지정 차단 목록** | Plus | `allowsCustomBlocklists`. 사용자 지정 목록은 기기에서 페치되고 파싱되며, 로컬에 캐시되고, Lava 서버로 프록시되지 않습니다. |
| **웜 스타트업 아티팩트 재사용** | Free | 매니페스트 + 신원 핑거프린트를 통해 터널이 재컴파일 없이 디스크 상의 컴팩트 스냅샷을 재사용할 수 있습니다. 입력이 변경되면 재사용은 (프라이버시에 안전한 필드명 전용 사유와 함께) 거부됩니다. |
| **Smart Save(약화 전용 확인)** | Free | 보호를 *강화*하거나 중립적인 필터 편집(차단 목록 또는 차단 도메인 추가)은 직접 적용됩니다. 보호를 *약화*하는 편집 — 차단 목록 제거, 차단 도메인 제거, 또는 허용 예외 추가 — 은 먼저 검토 확인 시트를 거치며, 예외가 추가될 때는 "각별히 주의하세요" 패널이 표시됩니다(`FiltersView.saveChanges()`, `weakensProtection`). |
| **예산 미터(저장 가능한 선택)** | Free / Plus | 선택 미터는 카운트를 약식 표기(500K / 1.2M / 2M)하고 1.10 소프트 상한 마진을 사용합니다(목록별 합계는 중복 제거된 합집합을 약 7~10% 과대 계상함). 허용 오차 내에 있는 카운트는 소프트 상한을 넘기 전까지 예를 들어 "500K of 500K"로 표시되도록 고정됩니다(`FilterRuleBudget`). |

> 권위 있는 예산 적용은 중복 제거된 합집합에 대해 컴파일 시점에 실행됩니다(`FilterSnapshotPreparationService`). 기기 상한이 먼저 확인된 다음 등급 한도가 확인됩니다. 선택 시점의 UI 미터는 1.10 소프트 상한 마진과 함께 목록별 합계를 사용합니다.

---

## 3. 암호화 DNS

차단되지 않은 쿼리를 위한 리졸버 전송 방식 및 라우팅.

| 기능 | 등급 | 비고 |
|---|---|---|
| **5가지 리졸버 전송 방식** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic`(`DNSResolverTransport`). |
| **DoH / DoH3** | Free | HTTP/3를 선호하는 URLSession 기반 DoH. UI는 **실제로 h3 협상이 관측될 때만** **`DoH3`(슬래시 없음)**를 주석으로 표시합니다(예: "Quad9 (DoH3)"). 보장이 아니라 선호일 뿐입니다(`DoHTransport`). |
| **DoT** | Free | 유휴 노후화 갱신과 1회 신규 연결 재시도를 갖춘 풀링된 `NWConnection`(엔드포인트당 최대 4개). |
| **DoQ**(사용자 지정 전용) | Plus | DNS-over-QUIC에는 **내장 프리셋이 없습니다** — 오직 **사용자 지정 `doq://` 리졸버**를 통해서만 접근 가능하며, 사용자 지정 DNS는 Plus입니다. **쿼리마다 새 QUIC 연결을 엽니다**(4레인 풀은 동시성을 제공하지만 핸드셰이크 재사용은 제공하지 않음). 연결 재사용은 iOS-26 배포 기준점으로 연기되었습니다. |
| **프리셋 리졸버** | Free | Device DNS(기본값), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — 제공되는 경우 IP / DoH / DoT 변형으로(`DNSResolverPreset.allPresets`). |
| **리졸버 라우팅 및 페일오버** | Free | `ResolverOrchestrator`는 전송 방식별로 라우팅하고, 암호화 계획에 엔드포인트가 없으면 plain DNS로 강등하며, 백오프 게이트와 함께 엔드포인트별 페일오버를 수행한 다음 device-DNS 폴백을 합니다. |
| **Device-DNS 폴백** | Free | 선택한 리졸버를 사용할 수 없을 때 현재 네트워크의 리졸버로 폴백합니다. **기본값으로 켜져 있음**. `usingDeviceDNSFallback` 심각도로 표면화됩니다. |
| **사용자 지정 DNS** | Plus | `allowsCustomDNS` — 사용자가 제공하는 리졸버(사용자 지정 프리셋을 위한 DNS-stamp 파싱 포함). |

---

## 4. 계정 및 영지식 백업

선택적 계정 로그인 및 암호화된 설정 백업. 이 중 어떤 것도 보호 기능 사용에 필수가 아닙니다.

| 기능 | 등급 | 비고 |
|---|---|---|
| **선택적 계정 로그인(Apple + Google)** | Free | 해시된 nonce와 함께 Supabase Auth(`grant_type=id_token`)에서 교환되는 네이티브 id_token 플로우; 결과로 생성된 Supabase 세션만 기기 로컬의 Keychain에 저장됩니다. 이메일/비밀번호 로그인은 의도적으로 제공하지 않습니다(Dropped). |
| **영지식 암호화 백업** | Free | 클라이언트 측 AES-256-GCM 봉투; 무작위 페이로드 키는 PBKDF2-HMAC-SHA256(210k 반복) 키 슬롯에 래핑됩니다. 암호문 + 비밀이 아닌 메타데이터만 Supabase `user_backups`(사용자별 RLS)에 업로드됩니다. 서버는 사용자가 보유한 비밀 없이는 복호화할 수 없습니다. |
| **최소화된 백업 페이로드** | Free | 활성화된 차단 목록 ID, 허용/차단 도메인, 리졸버 설정, 로컬 로그 환경설정, guardian 룩 등을 백업하며 — `isPaid`, QA 플래그, 진단, 스냅샷, 전체 차단 목록 바이트는 명시적으로 제외합니다. |
| **기기 비밀 키 슬롯** | Free | 동일 기기에서의 매끄러운 복원을 위해 기기 전용 Keychain(`...ThisDeviceOnly`, iCloud 동기화 안 됨)에 있는 32바이트 기기 비밀. |
| **복구 문구 + 보조 복구** | Free | 8단어 CVCV 문구(약 105비트)를 SHA256을 통해 서버 보유 복구 셰어와 결합하여 보조 복구 슬롯을 잠금 해제합니다. 이중 요소: 어느 한쪽만으로는 복호화되지 않습니다. |
| **패스키 복구 슬롯** | Free | 선택적 WebAuthn 게이트 슬롯이며 **영지식**입니다: 그 언랩 키는 인증기의 WebAuthn PRF(`hmac-secret`) 출력에서 **기기에서** 파생됩니다(HKDF-SHA256). 서버는 패스키를 등록하지 않고, 챌린지를 발급하지 않으며, 복구 비밀을 보유하지 않고, 패스키 경로를 노출하지 않습니다 — 이전의 서버 에스크로 설계는 폐기되었습니다. 실물 기기에서의 프로덕션 준비 상태는 Associated Domains / AASA 호스팅에 달려 있습니다(Planned). |
| **계정 삭제 / 데이터 권리** | Free | 인증된 Worker 엔드포인트가 백업, 설정, 권한, 프로필, 버그 리포트 첨부 파일을 삭제한 다음 Supabase Auth 사용자를 삭제합니다. 앱은 로그아웃하고 로컬 잠금 해제 자료를 지웁니다. |

---

## 5. 위젯 및 Live Activity

잠금 화면 및 Dynamic Island 표시.

| 기능 | 등급 | 비고 |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget`(`com.lavasec.app.widget`): 잠금 화면과 Dynamic Island에 표시되는 단일 `Activity<LavaActivityAttributes>`(확장 중앙 / compactLeading guardian / compactTrailing + minimal 상태 글리프). |
| **5상태 보호 표시** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — 각각 guardian 포즈, SF Symbol, 제목에 매핑됩니다. |
| **Live Activity 액션 버튼** | Free | N분 일시정지(설정된 길이, 기본값 5), 재개, 재연결 — `LavaProtectionCommandService`를 통해 앱 프로세스에서 실행되는 `LiveActivityIntent`. 인증 일시정지 변형은 로컬 기기 인증을 요구합니다. |
| **단일 중복 제거 및 리비전 게이트 조정** | Free | `LavaLiveActivityController`는 단일 Activity를 유지하고, 실제 id/콘텐츠 변경 시에만 업데이트하며, `ProtectionPauseStore` 리비전으로 업데이트를 게이트하여 오래된 인텐트 재시도가 상태를 후퇴시킬 수 없도록 합니다. |
| **Live Activities 토글** | Free | 설정에서 사용자가 토글 가능(`setUsesLiveActivities`)하며, iPhone/iPad에서만 사용할 수 있습니다. |

---

## 6. 온보딩

로컬 VPN 구성을 설치하고 합리적인 기본값을 설정하는 첫 실행 플로우.

| 기능 | 등급 | 비고 |
|---|---|---|
| **다중 페이지 첫 실행 플로우** | Free | `OnboardingFlowView` — 6페이지: `lava, guardIntro, features, vpn, notifications, done`. (프로파일 설치와 알림 프롬프트는 미리가 아니라 적절한 단계에서 발생합니다.) |
| **로컬 VPN 프로파일 설치** | Free | 온보딩 중 Connect-On-Demand를 활성화하지 **않고** 로컬 VPN 구성을 설치하므로, 완료 시점에 보호가 조용히 자동으로 켜지지 않습니다 — Guard 표면이 권위를 유지합니다. |
| **알림 권한 프롬프트** | Free | 알림 단계에서 플로우 내에서 요청됩니다. |
| **권장 기본값 적용** | Free | Device DNS 리졸버, device-DNS 폴백 켜짐, 로컬 로깅 켜짐(카운트 + 기록 + 활동), Block List Basic 활성화, 계정 없이 계속(`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. 설정

구성, 보안, 진단, 피드백 표면.

| 기능 | 등급 | 비고 |
|---|---|---|
| **앱 잠금 해제 비밀번호 + 생체 인증** | Free | `SecurityController`: Keychain 내 솔트 처리된 SHA256 비밀번호 검증기 + `LAContext` 생체 인증, 앱 잠금 해제 차단 오버레이 및 scene-phase 변경 시 프라이버시 마스크 포함. |
| **표면별 보호** | Free | `SecurityProtectedSurface`는 6개 표면을 게이트합니다: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. 각각은 독립적으로 로컬 기기 인증을 요구할 수 있습니다(예: 설정 탭은 `.requires(.appSettings)`를 반환). |
| **Lava Guard 룩 선택기(7가지 룩)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, 각각 Dynamic Island 글리프 색상과 짝지어져 있습니다. 바텀 시트 라디오 선택기("Choose your Guard", `LavaGuardLookPickerSheet`)에서 선택합니다. 아직 잠겨 있는 룩에는 잠금 글리프가 표시되며 잠금 해제/업그레이드 패널이 시트 안에 있습니다. |
| **앱 아이콘 맞춤** | Free | 선택한 guardian 룩에 짝지어진 선택적 대체 앱 아이콘. |
| **외관** | Free | 라이트/다크/시스템 색상 구성. |
| **로컬 전용 로깅 제어** | Free | 필터링 카운트, 도메인 기록(진단), 네트워크 활동에 대한 토글 — 모두 기기에 저장됩니다. 세분화된 로그(도메인 기록 + 네트워크 활동)는 **7일** 창으로 정리됩니다(`LocalLogRetention.fineGrainedDays = 7`); 카운트와 Lava Guard 진행 상황은 더 오래 보관됩니다. |
| **활동 / 도메인 로그(Guard 상세)** | Free | Guard 탭(`GuardDestination.activity`)에서 도달하는 동적 로컬 전용 진단. 다이제스트는 요청 **플로우**입니다 — "처리된 요청" 총계가 "로컬에서 보호된 %"와 함께 허용/차단 볼륨 막대로 나뉩니다(정직한 반올림: 아주 작은 비율은 `<1%`로, 거의 전체에 가까운 비율은 `>99%`로 표시됨). **도메인 로그** 섹션에는 **Top Domains**(가장 많이 차단·허용됨, 쿼리 수 기준 순위)와 **Domain History**(최근 조회 및 결정)가 있습니다. 도메인 행은 기록 옵트인이 켜져 있을 때만 나타납니다. |
| **필터(Guard 상세)** | Free | Guard 탭에서 도달하는 단일 통합 필터 화면. "My filter" 허브는 하나의 통합된 **My filter** 화면을 열며 두 개의 선반 — **"Lava blocks these"**(차단 목록 + 개별 차단 도메인)와 **"Lava lets these through"**(허용 예외) — 을 하나의 Edit/Save 초안 플로우 아래에 둡니다. "Phone → Lava → Internet" 플로우 다이어그램이 탭 상단에 있으며, My filter를 열면 카탈로그가 자동 새로 고침됩니다. |
| **네트워크 활동(설정 → 고급)** | Free | App Group을 통해 공유되는, 네트워크/런타임/사용자 전환의 제한된 로컬 전용 이벤트 스트림(`NetworkActivityLog`). 활동 표면에서 **설정 → 고급**으로 이동되었으며("Nerd Stats" 다음, `SettingsRoute.networkActivity`), `.activityViewing` 잠금 뒤에 있고, 자체 프라이버시 패널("이 iPhone에만 유지됨", 7일 보관)이 있습니다. |
| **버그 리포트** | Free | 익명화된 번들을 `POST /v1/bug-reports`로 보내는 사용자 트리거 마법사; v1에는 도메인 기록 없음. 번들은 이제 빌드 출처(`appVersion`/`appBuild`/`sourceRevision`)와 연결성 정직성 카운터도 함께 전달합니다. 흔들어서 리포트하기(`RageShakeDetector`)로도 도달할 수 있습니다. |
| **구독 관리** | Plus | 활성 구독자의 경우 업그레이드 화면에 구독 관리(자동 갱신 플랜, `AppStore.showManageSubscriptions`를 통해), 구매 복원, 권한 만료 날짜가 표시됩니다. |
| **법적 고지 + 버전** | Free | 설정은 제3자 법적 고지([Third-party notices](../legal/third-party-notices.md) 참조)와 버전/빌드 페이지를 표면화합니다. |

---

## 앱 아키텍처(방향 잡기용)

세 개의 번들이 하나의 App Group `group.com.lavasec`를 공유하며, 그 안으로 컴파일되는 `lavasec-ios: Shared/` 소스 폴더와 함께합니다:

- **LavaSecApp**(`com.lavasec.app`) — SwiftUI 앱 셸; 이 빌드에서 루트는 두 탭 `TabView`(**Guard** + **Settings**)이며, 필터와 활동은 Guard 탭 아래의 상세 화면으로 도달합니다(네트워크 활동은 이제 설정 → 고급 아래에 있음).
- **LavaSecTunnel**(`.tunnel`) — 기기 내 DNS 필터/리졸브 엔진.
- **LavaSecWidget**(`.widget`) — WidgetKit Live Activity.
- **Shared/** — 교차 타깃 소스(번들 아님): App Group, 커맨드 서비스, 마스코트, Live Activity 속성/인텐트.

앱 ↔ 익스텐션 제어는 Darwin 알림이 아니라 `NETunnelProviderSession` **provider messages**(`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`)를 사용합니다. 필터 규칙은 App-Group 스냅샷 파일(`filter-snapshot.json` / `.compact`)로 앱 → 익스텐션으로 교차됩니다.

---

## 관련 문서

- 로드맵 — 계획된 기능과 폐기된 기능(Plus 가격/StoreKit 포지셔닝, Android 포팅, URL 수준 보호, 패스키 Associated-Domain 준비, 이스터에그 미니 게임, GPL-3.0 오픈소스 릴리스 등)은 이 공개 카탈로그가 아니라 비공개 로드맵에 있습니다.
- [GPL 소스 URL 전용 준수 결정](../legal/gpl-source-url-only-compliance-decision.md)
- [오픈소스 목록 데이터 약관 예외 조항](../legal/open-source-list-data-terms-carveout.md)
- [Third-party notices](../legal/third-party-notices.md)
