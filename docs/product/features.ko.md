---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 기능 카탈로그

> 대상: PM / 엔지니어링. 이 카탈로그는 **현재 구현된** 기능만 다뤄요. 설계는 됐지만 아직 만들지 않은 항목은 여기가 아니라 비공개 로드맵에 있어요.

Lava Security는 NetworkExtension 패킷 터널을 통해 **기기에서 직접** DNS를 필터링하는 프라이버시 우선 iOS 앱이에요. 비기술적인 사용자(부모님, 어르신)를 위해 악성·원치 않는 도메인을 차단하며, 핵심 보호 기능은 평생 무료이고 계정도 필요 없어요.

아래 모든 기능의 바탕에 있는 프라이버시 약속이에요.

> 모든 DNS 필터링은 기기에서 이뤄져요. Lava는 사용자의 브라우징을 자사 서버로 보내지 않고, 방문하는 도메인 흐름도 받지 않아요. 백엔드에는 카탈로그 메타데이터, 사용자별 암호화된 불투명 백업, 그리고 사용자가 직접 보내기로 선택한 익명 진단 정보만 있어요.

## 이 카탈로그를 읽는 법

- **Free** — 누구나 사용할 수 있어요. 계정도 구매도 필요 없어요.
- **Plus** — 하나뿐인 선택형 유료 등급인 Lava Security Plus로 잠금이 풀려요. Plus는 **커스터마이징만** 열어 주며, 기본 안전 기능을 막거나 유료 사용자가 위협 가드레일을 우회하게 하지 않아요.
- 별도 표시가 없으면 모든 항목은 **구현됨**이에요. 상태 표기: **구현됨** = 출시되어 코드에서 확인된 기능, **계획됨** = 설계됐지만 아직 만들지 않음, **중단됨** = 거부되거나 되돌림. 계획됨/중단됨 항목은 여기가 아니라 비공개 로드맵에 기록돼 있어요.

각 등급의 상한선에 대한 단일 진실 공급원은 `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`에 있어요 (`FeatureLimits.free` / `FeatureLimits.paid`, `.plus`로 별칭 지정). Plus 권한 **게이트**는 로컬 플래그(`isPaid`)이며, 이것이 진실 공급원이에요. 백엔드는 App Store 권한을 **그대로 반영**하지만 (`POST /v1/account/entitlements/app-store-sync`가 `entitlements` 행을 upsert) 그 행은 거울일 뿐 게이트가 아니에요. 아직 백엔드 동기화가 게이팅을 좌우하지는 않아요.

---

## 1. 보호 및 VPN

핵심 제품이에요. 로컬 DNS 전용 패킷 터널과 그 주변의 차분한 상태 모델이죠.

| 기능 | 등급 | 설명 |
|---|---|---|
| **로컬 DNS 전용 패킷 터널** | Free | `LavaSecTunnel`(`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`)이 DNS를 가로채 각 도메인을 기기에서 평가해요. 브라우징 트래픽은 Lava를 거치지 않아요. 터널 주소 `10.255.0.2`, DNS 서버 `10.255.0.1`. |
| **필터 판정 우선순위** | Free | `위협 가드레일 차단 > 로컬 허용 목록(허용된 예외) > 차단 목록 > 기본 허용`; 유효하지 않은 도메인은 차단돼요. (`FilterSnapshot.decision()`.) |
| **쿼리 우선순위 (부트스트랩 우선)** | Free | `resolver-bootstrap > temporary-pause > filter` — 리졸버 자신의 호스트네임은 절대 차단되지 않아요. (`DNSQueryDispatcher`.) |
| **실패 시 차단(fail-closed) 콜드 스타트** | Free | 재사용 가능한 스냅샷이 없는 콜드 터널은 `FailClosedRuntimeSnapshot`을 설치해, 필터링되지 않은 DNS가 새어 나가는 대신 모든 트래픽을 차단해요. |
| **요청 시 연결(Connect-On-Demand)** | Free | `NEOnDemandRuleConnect`가 보호를 유지하고 자동으로 다시 켜요 — **확인된 연결 이후에만** 켜지고, 프로필 설치 시점엔 켜지지 않으며, 온보딩이 끝나지 않은 동안엔 비활성화돼요. 그래서 새로 설치해도 끌 수 없는 터널이 올라오는 일은 없어요. |
| **일시 중지 (5분 / 10분) + 재개** | Free | 일시 중지/재개는 flock 파일 잠금과 리비전 중복 제거를 통해 `LavaProtectionCommandService`로 처리돼요. |
| **인증 필요 일시 중지** | Free | 화면별로 켤 수 있는 게이트(`SecurityProtectedSurface.protectionPause`): 일시 중지에 기기 로컬 인증이 필요해요. 인증되지 않은 일시 중지는 명령 서비스가 거부하고, Live Activity는 일시 중지 버튼을 숨겨요. |
| **다시 연결** | Free | 터널을 바로 다시 시작해요 (명령 서비스의 일시 중지 파이프라인을 건너뛰어요). |
| **소프트 실드 가디언 상태 모델** | Free | 7가지 표정 상태 — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6단계 연결 심각도가 4가지 표정으로 모이며, 앱 안·온보딩·Live Activity에서 동일하게 그려져요. |
| **연결 상태 평가** | Free | 6단계 심각도(`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`)가 가디언 표정과 상태 문구를 결정해요. |
| **성능 최적화** | Free | 캐시 우선 켜짐, 진행 중 쿼리 합치기, 병렬 수 제한 가져오기, 깜빡임 합치기 (모듈화 속도 개선 작업 기준, 따뜻한 상태에서 켜질 때 iPhone 15 Pro에서 약 112ms로 측정). |

> **기기 가드레일 (모두에게 적용, 절대 유료 장벽 아님):** 모든 사용자에게 등급과 무관하게 `약 326만 규칙` 상한(iOS의 `약 50 MiB` 확장 프로그램별 메모리 상한 아래에서 32 MB 상주 목표)이 적용돼요 (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). 예산을 넘는 설정은 터널이 jetsam으로 죽게 두는 대신 결정적으로 거부돼요 (`exceedsDeviceMemoryBudget`). |

---

## 2. 차단 목록 및 필터링

무엇이 차단되는지, 목록은 어떻게 고르는지, 그리고 등급 경계예요.

| 기능 | 등급 | 설명 |
|---|---|---|
| **소스 URL 전용 차단 목록** | Free | Lava는 원본 URL과 허용 해시만 게시하고, **목록 바이트** 자체는 기기가 직접 가져와 파싱해요. Lava는 서드파티 차단 목록 바이트를 **절대** 저장·미러링·변환·제공하지 않아요. [GPL 소스 URL 전용 준수 결정](../legal/gpl-source-url-only-compliance-decision.md)을 참고하세요. |
| **선별 카탈로그 (10개 소스)** | 활성화 무료 | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **기본 차단 목록 (무료)** | Free | 새로 설치하면 **Block List Project Phishing + Scam**이 켜져요 (`defaultEnabled: true`로 표시된 두 소스; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **기기 내 파싱 / 정규화 / 중복 제거** | Free | `BlocklistParser`는 auto/plain/hosts/adblock/dnsmasq를 지원하고, 주석·빈 줄·잘못된 항목을 걸러내고, 똑같은 문자열을 중복 제거하며, 목록당 1,000,000개 규칙으로 제한해요. |
| **원본 바이트 검증** | Free | 가져온 바이트는 SHA-256으로 처리되어, 체크섬이 카탈로그의 `accepted_source_hashes`에 있을 때만 받아들여져요. 일치하지 않으면 Lava는 마지막으로 정상이던 캐시로 돌아가거나 실패 시 차단해요. |
| **보호 도메인 필터** | Free | 파싱된 모든 소스에서 보호 대상인 Lava / Apple / 신원 제공자 도메인(apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com 등)이 제거돼요. 그래서 원본 목록이 앱·터널·로그인을 망가뜨릴 수 없어요. |
| **허용된 예외 (허용 목록)** | Free | 차단 목록에도 불구하고 도메인을 허용하는, 사용자가 관리하는 허용 목록이에요. 무료 한도: 허용 10개 / 차단 10개 도메인 (`FeatureLimits.free`). |
| **필터 규칙 예산 (등급 지표)** | Free / Plus | 출시된 등급 지표는 컴파일된 도메인 **규칙** 총수예요: **Free 50만 / Plus 200만** (`lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`의 `maxFilterRules`). 기존 목록 개수 상한을 대체해요. 등급을 넘는 설정은 `exceedsTierFilterRuleLimit`로 표시돼요. |
| **더 높은 도메인 한도** | Plus | 허용 500개 / 차단 500개 도메인 (`FeatureLimits.plus`). |
| **커스텀 차단 목록** | Plus | `allowsCustomBlocklists`. 커스텀 목록은 기기에서 가져와 파싱하고 로컬에 캐싱하며, Lava 서버로는 절대 전달되지 않아요. |
| **웜 스타트업 산출물 재사용** | Free | 매니페스트와 신원 지문 덕분에 터널이 디스크의 컴팩트 스냅샷을 다시 컴파일하지 않고 재사용해요. 입력이 바뀌면 (프라이버시에 안전한 필드 이름만 담은 이유와 함께) 재사용이 거부돼요. |

> 권위 있는 예산 적용은 중복 제거된 합집합에 대해 컴파일 시점에 이뤄지며 (`FilterSnapshotPreparationService`), 기기 상한을 먼저 확인한 뒤 등급 한도를 확인해요. 선택 시점의 UI 미터는 목록별 합계에 1.10의 여유 상한 마진을 더해 표시해요.

---

## 3. 암호화된 DNS

차단되지 않은 쿼리에 대한 리졸버 전송 방식과 라우팅이에요.

| 기능 | 등급 | 설명 |
|---|---|---|
| **5가지 리졸버 전송 방식** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | HTTP/3을 우선하는 URLSession 기반 DoH예요. UI는 **실제로 h3 협상이 관찰될 때에만** **`DoH3`(슬래시 없음)**을 붙여 표시해요. 예: "Quad9 (DoH3)" — 약속이 아니라 우선이에요 (`DoHTransport`). |
| **DoT** | Free | 풀링된 `NWConnection`(엔드포인트당 최대 4개), 유휴 상태 갱신과 새 연결 1회 재시도를 사용해요. |
| **DoQ** (커스텀 전용) | Plus | DNS-over-QUIC는 **기본 프리셋이 없어요** — **커스텀 `doq://` 리졸버**로만 접근할 수 있고, 커스텀 DNS는 Plus예요. **쿼리마다 새 QUIC 연결**을 열어요 (4레인 풀은 동시성을 줄 뿐 핸드셰이크 재사용은 아니에요). 연결 재사용은 iOS-26 배포 기준선으로 미뤄졌어요. |
| **프리셋 리졸버** | Free | Device DNS(기본값), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — 제공되는 경우 IP / DoH / DoT 변형으로 제공돼요 (`DNSResolverPreset.allPresets`). |
| **리졸버 라우팅 및 장애 조치** | Free | `ResolverOrchestrator`가 전송 방식별로 라우팅하고, 암호화 계획에 엔드포인트가 없으면 일반 DNS로 낮추며, 백오프 게이트와 함께 엔드포인트별 장애 조치를 한 뒤 device-DNS로 폴백해요. |
| **Device-DNS 폴백** | Free | 선택한 리졸버를 쓸 수 없을 때 현재 네트워크의 리졸버로 폴백해요. **기본으로 켜져 있어요.** `usingDeviceDNSFallback` 심각도로 표시돼요. |
| **커스텀 DNS** | Plus | `allowsCustomDNS` — 사용자가 지정한 리졸버예요 (커스텀 프리셋용 DNS 스탬프 파싱 포함). |

---

## 4. 계정 및 제로 지식 백업

선택형 계정 로그인과 암호화된 설정 백업이에요. 보호 기능을 쓰는 데 이 중 어느 것도 필요하지 않아요.

| 기능 | 등급 | 설명 |
|---|---|---|
| **선택형 계정 로그인 (Apple + Google)** | Free | 해시된 nonce와 함께 Supabase Auth에서 교환되는 네이티브 id_token 흐름(`grant_type=id_token`)이에요. 그 결과로 생긴 Supabase 세션만 기기 로컬 Keychain에 저장돼요. 이메일/비밀번호 로그인은 의도적으로 제공하지 않아요 (중단됨). |
| **제로 지식 암호화 백업** | Free | 클라이언트 측 AES-256-GCM 봉투예요. 무작위 페이로드 키는 PBKDF2-HMAC-SHA256(반복 21만 회) 키 슬롯으로 감싸요. 암호문과 비밀이 아닌 메타데이터만 Supabase `user_backups`에 업로드돼요 (사용자별 RLS). 사용자가 가진 비밀 없이는 서버가 복호화할 수 없어요. |
| **최소화된 백업 페이로드** | Free | 활성화된 차단 목록 ID, 허용/차단 도메인, 리졸버 설정, 로컬 로그 환경설정, 가디언 모양 등을 백업하고, `isPaid`, QA 플래그, 진단 정보, 스냅샷, 전체 차단 목록 바이트는 명시적으로 제외해요. |
| **기기 비밀 키 슬롯** | Free | 같은 기기에서 매끄럽게 복원하기 위해, 기기 전용 Keychain(`...ThisDeviceOnly`, iCloud 비동기화)에 32바이트 기기 비밀을 둬요. |
| **복구 문구 + 도움 복구** | Free | 8단어 CVCV 문구(약 105비트)를 서버가 가진 복구 조각과 SHA256으로 합쳐 도움 복구 슬롯을 풀어요. 2단계 방식이라 어느 한쪽만으로는 복호화할 수 없어요. |
| **패스키 복구 슬롯** | Free | 선택형 WebAuthn 보호 슬롯이며 **제로 지식**이에요: 해제 키는 인증기의 WebAuthn PRF(`hmac-secret`) 출력에서 **기기에서** 파생돼요 (HKDF-SHA256). 서버는 패스키를 등록하지 않고, 챌린지를 발급하지 않고, 복구 비밀을 보관하지 않으며, 패스키 경로를 노출하지 않아요 — 이전의 서버 에스크로 설계는 중단됐어요. 실제 기기에서의 운영 준비는 Associated Domains / AASA 호스팅에 달려 있어요 (계획됨). |
| **계정 삭제 / 데이터 권리** | Free | 인증된 Worker 엔드포인트가 백업, 설정, 권한, 프로필, 버그 신고 첨부 파일을 삭제한 뒤 Supabase Auth 사용자를 삭제해요. 앱은 로그아웃하고 로컬 해제 자료를 지워요. |

---

## 5. 위젯 및 Live Activity

잠금 화면과 다이내믹 아일랜드에서의 표시예요.

| 기능 | 등급 | 설명 |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget`(`com.lavasec.app.widget`): 잠금 화면과 다이내믹 아일랜드에 표시되는 단일 `Activity<LavaActivityAttributes>`예요 (확장 시 중앙 / compactLeading 가디언 / compactTrailing + 최소 상태 글리프). |
| **5가지 상태 보호 표시** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — 각각 가디언 포즈, SF Symbol, 제목에 매핑돼요. |
| **Live Activity 동작 버튼** | Free | 5분 / 10분 일시 중지, 재개, 다시 연결 — 앱 프로세스 안에서 `LavaProtectionCommandService`로 실행되는 `LiveActivityIntent`예요. 인증이 필요한 일시 중지 변형은 기기 로컬 인증을 요구해요. |
| **단일 중복 제거 · 리비전 게이트 조정** | Free | `LavaLiveActivityController`는 Activity를 하나만 유지하고, 실제 id/내용 변경 시에만 갱신하며, `ProtectionPauseStore` 리비전으로 갱신을 게이트해서 오래된 인텐트 재시도가 상태를 되돌리지 못하게 해요. |
| **Live Activities 토글** | Free | 설정에서 사용자가 켜고 끌 수 있어요 (`setUsesLiveActivities`). iPhone/iPad에서만 제공돼요. |

---

## 6. 온보딩

로컬 VPN 설정을 설치하고 합리적인 기본값을 정하는 첫 실행 흐름이에요.

| 기능 | 등급 | 설명 |
|---|---|---|
| **여러 페이지로 된 첫 실행 흐름** | Free | `OnboardingFlowView` — 6페이지: `lava, guardIntro, features, vpn, notifications, done`. (프로필 설치와 알림 요청은 처음이 아니라 알맞은 단계에서 일어나요.) |
| **로컬 VPN 프로필 설치** | Free | 온보딩 중에 Connect-On-Demand를 켜지 **않고** 로컬 VPN 설정을 설치해요. 그래서 완료 시점에 보호가 조용히 자동으로 켜지지 않고, Guard 화면이 기준점으로 남아요. |
| **알림 권한 요청** | Free | 흐름 안 알림 단계에서 요청해요. |
| **추천 기본값 적용** | Free | Device DNS 리졸버, device-DNS 폴백 켜짐, 로컬 로깅 켜짐(횟수 + 기록 + 활동), Block List Project Phishing + Scam 활성화, 계정 없이 계속 (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. 설정

구성, 보안, 진단, 피드백 화면이에요.

| 기능 | 등급 | 설명 |
|---|---|---|
| **앱 잠금 해제 암호 + 생체 인증** | Free | `SecurityController`: Keychain에 저장된 솔트 적용 SHA256 암호 검증기 + `LAContext` 생체 인증이에요. 앱 잠금 차단 오버레이와 화면 전환 시 프라이버시 마스크가 함께 동작해요. |
| **화면별 보호** | Free | `SecurityProtectedSurface`가 여섯 화면을 보호해요: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. 각각 독립적으로 기기 로컬 인증을 요구할 수 있어요 (예: 설정 탭은 `.requires(.appSettings)`를 반환). |
| **Lava Guard 모양 선택기 (7가지 모양)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, 각각 짝지어진 다이내믹 아일랜드 글리프 색상이 있어요. |
| **앱 아이콘 맞춤** | Free | 선택한 가디언 모양에 맞춘 선택형 대체 앱 아이콘이에요. |
| **외관** | Free | 라이트/다크/시스템 색 구성이에요. |
| **로컬 전용 로깅 제어** | Free | 필터링 횟수, 도메인 기록(진단), 네트워크 활동 토글이에요 — 모두 기기에 저장돼요. |
| **리포트 / 활동 (Guard 상세)** | Free | 동적인 로컬 전용 진단이에요: 차단/허용 횟수, 터널 상태, 상위 도메인. 도메인 행은 기록 동의를 켰을 때만 나타나요. Guard 탭에서 상세 화면으로 들어가요 (`GuardDestination.activity`). |
| **필터 (Guard 상세)** | Free | 개요 우선 필터 화면이에요. 차단된 도메인 / 허용된 예외 상세와 단계적 보기/편집/확인 임시 저장 흐름이 있어요 (`GuardDestination.filters`). |
| **네트워크 및 Lava 상태 활동 로그** | Free | 네트워크/런타임/사용자 전환의 경계가 있는 로컬 전용 이벤트 스트림이에요. App Group을 통해 공유돼요 (`NetworkActivityLog`). |
| **버그 신고** | Free | 사용자가 시작하는 마법사로, 익명화된 묶음을 `POST /v1/bug-reports`로 보내요. v1에는 도메인 기록이 없어요. 흔들어서 신고하기로도 열 수 있어요 (`RageShakeDetector`). |
| **법적 고지 + 버전** | Free | 설정에 서드파티 법적 고지(​[서드파티 고지](../legal/third-party-notices.md) 참고)와 버전/빌드 페이지가 표시돼요. |

---

## 앱 아키텍처 (방향 잡기용)

세 번들이 하나의 App Group `group.com.lavasec`를 공유하고, 함께 컴파일되는 `lavasec-ios: Shared/` 소스 폴더가 곁에 있어요.

- **LavaSecApp** (`com.lavasec.app`) — SwiftUI 앱 셸이에요. 이 빌드에서 루트는 두 탭짜리 `TabView`(**Guard** + **Settings**)이며, 필터와 활동은 Guard 탭 아래 상세 화면으로 들어가요.
- **LavaSecTunnel** (`.tunnel`) — 기기 내 DNS 필터/해석 엔진이에요.
- **LavaSecWidget** (`.widget`) — WidgetKit Live Activity예요.
- **Shared/** — 타깃을 가로지르는 소스예요 (번들 아님): App Group, 명령 서비스, 마스코트, Live Activity 속성/인텐트.

앱 ↔ 확장 프로그램 제어는 Darwin 알림이 아니라 `NETunnelProviderSession` **프로바이더 메시지**(`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`)를 써요. 필터 규칙은 App Group 스냅샷 파일(`filter-snapshot.json` / `.compact`)로 앱 → 확장 프로그램으로 건너가요.

---

## 관련 문서

- 로드맵 — 계획되거나 중단된 기능(Plus 가격/StoreKit 포지셔닝, Android 이식, URL 수준 보호, 패스키 Associated-Domain 준비, 이스터에그 미니게임, GPL-3.0 오픈소스 공개 등)은 이 공개 카탈로그가 아니라 비공개 로드맵에 있어요.
- [GPL 소스 URL 전용 준수 결정](../legal/gpl-source-url-only-compliance-decision.md)
- [오픈소스 목록 데이터 약관 예외](../legal/open-source-list-data-terms-carveout.md)
- [서드파티 고지](../legal/third-party-notices.md)
