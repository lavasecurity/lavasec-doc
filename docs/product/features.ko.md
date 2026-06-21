---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 기능 카탈로그

> 대상 독자: PM / 엔지니어링. 이 카탈로그는 **현재 구현된** 기능만 다뤄요. 설계만 되고 아직 만들어지지 않은 것은 여기가 아니라 비공개 로드맵에 있어요.

Lava Security는 NetworkExtension 패킷 터널을 통해 **기기 내부에서 로컬로** DNS를 필터링하는 프라이버시 우선 iOS 앱으로, 비전문 사용자(부모, 어르신)를 위해 악성 및 원치 않는 도메인을 차단해요. 핵심 보호 기능은 영구 무료이며 계정도 필요 없어요.

아래 모든 기능 뒤에 있는 프라이버시 약속이에요.

> 모든 DNS 필터링은 기기에서 이뤄져요. Lava는 여러분의 브라우징을 자사 서버로 절대 우회시키지 않으며, 여러분이 방문하는 도메인의 흐름도 절대 받지 않아요. 백엔드는 카탈로그 메타데이터, 사용자별 불투명 암호화 백업, 그리고 여러분이 보내기로 선택한 익명화된 진단 정보만 보관해요.

## 이 카탈로그를 읽는 법

- **Free** — 모든 사람이 사용할 수 있어요. 계정도, 구매도 필요 없어요.
- **Plus** — 단 하나뿐인 선택적 유료 등급인 Lava Security Plus로 잠금 해제돼요. Plus는 **맞춤 설정만** 해제해 줘요. 기본 안전 기능을 절대 막지 않으며, 유료 사용자가 위협 가드레일을 우회하게 두지도 않아요.
- 인라인으로 별도 표시가 없는 한 모든 항목은 **Implemented(구현됨)** 상태예요. 상태 범례: **Implemented** = 출시되었고 코드에서 확인됨, **Planned** = 설계됨, 아직 미구현, **Dropped** = 거절 또는 되돌림. Planned/Dropped 항목은 여기가 아니라 비공개 로드맵에 문서화돼 있어요.

등급별 상한의 단일 진실 공급원은 `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`(`FeatureLimits.free` / `FeatureLimits.paid`, `.plus`로 별칭 지정)에 있어요. Plus 권한 **게이트**는 로컬 플래그(`isPaid`)이며, 이것이 진실 공급원이에요. 백엔드는 App Store 권한을 **미러링**하지만(`POST /v1/account/entitlements/app-store-sync`가 `entitlements` 행을 upsert함), 그 행은 게이트가 아니라 미러일 뿐이에요. 아직은 어떤 백엔드 동기화도 게이팅을 구동하지 않아요.

---

## 1. 보호 및 VPN

핵심 제품: 로컬 DNS 전용 패킷 터널과 그것을 둘러싼 차분한 상태 모델이에요.

| 기능 | 등급 | 비고 |
|---|---|---|
| **로컬 DNS 전용 패킷 터널** | Free | `LavaSecTunnel`(`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`)이 DNS를 가로채 각 도메인을 기기 내부에서 평가해요. 브라우징 트래픽은 Lava를 거치지 않아요. 터널 주소 `10.255.0.2`, DNS 서버 `10.255.0.1`. |
| **필터 결정 우선순위** | Free | `위협 가드레일 차단 > 로컬 허용 목록(허용된 예외) > 차단 목록 > 기본 허용`. 유효하지 않은 도메인은 차단돼요. (`FilterSnapshot.decision()`.) |
| **쿼리 우선순위(부트스트랩 우선)** | Free | `resolver-bootstrap > temporary-pause > filter` — 리졸버 자신의 호스트명은 절대 차단되지 않아요. (`DNSQueryDispatcher`.) |
| **Fail-closed 콜드 스타트** | Free | 재사용 가능한 스냅샷이 없는 콜드 터널은 필터링되지 않은 DNS를 흘려보내는 대신 모든 트래픽을 차단하는 `FailClosedRuntimeSnapshot`을 설치해요. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect`가 보호를 유지하고 자동 재시작해요. **확인된 연결 이후에만** 활성화되며, 프로파일 설치 시점에는 절대 켜지지 않아요. 그리고 온보딩이 완료되지 않은 동안에는 무력화되어, 갓 설치한 상태에서 끌 수 없는 터널이 올라오지 못하게 해요. |
| **임시 일시 정지(5분 / 10분) + 재개** | Free | 일시 정지/재개는 flock 파일 잠금과 리비전 중복 제거를 거쳐 `LavaProtectionCommandService`를 통해 실행돼요. |
| **인증 필요 일시 정지** | Free | 표면별로 옵트인하는 게이트(`SecurityProtectedSurface.protectionPause`). 일시 정지에는 로컬 기기 인증이 필요해요. 명령 서비스는 인증되지 않은 일시 정지를 거부하고, Live Activity는 일시 정지 버튼을 숨겨요. |
| **재연결** | Free | 터널을 직접 재시작해요(명령 서비스의 일시 정지 파이프라인을 우회). |
| **Soft Shield Guardian 상태 모델** | Free | 7가지 표정 상태 — `sleeping, waking, awake, paused, retrying, concerned, grateful`(`GuardianMascotAnimation.swift`, LavaSecCore). 6가지 연결 심각도가 4개 얼굴로 모이며, 앱 내부·온보딩·Live Activity에서 동일하게 렌더링돼요. |
| **연결 상태 평가** | Free | 6가지 심각도(`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`)가 가디언 얼굴과 상태 문구를 구동해요. |
| **성능 강화** | Free | 캐시 우선 켜짐, 진행 중 쿼리 통합, 병렬 수 제한 fetch, 플랩 통합(모듈화 속도 개선 작업 기준 iPhone 15 Pro에서 웜 켜짐이 약 112 ms로 측정됨). |

> **기기 가드레일(모두에게 적용, 절대 유료화 아님):** 모든 등급을 초과해 모든 사용자에게 하드 상한 `~3.26M-rule`(iOS의 `~50 MiB` 확장 프로그램당 메모리 상한 아래에서 32 MB 상주 목표)이 적용돼요(`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). 예산을 초과하는 구성은 터널이 jetsam되도록 두는 대신 결정론적으로 거부돼요(`exceedsDeviceMemoryBudget`).

---

## 2. 차단 목록 및 필터링

무엇이 차단되는지, 목록이 어떻게 선택되는지, 그리고 등급 경계예요.

| 기능 | 등급 | 비고 |
|---|---|---|
| **소스 URL 전용 차단 목록** | Free | Lava는 원본 URL과 허용된 해시만 게시하며, 기기가 목록 **바이트**를 직접 가져와 파싱해요. Lava는 제3자 차단 목록 바이트를 **절대** 저장, 미러링, 변환, 제공하지 않아요. [GPL 소스 URL 전용 준수 결정](../legal/gpl-source-url-only-compliance-decision.md)을 참고하세요. |
| **큐레이션 카탈로그(10개 소스)** | 활성화 무료 | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift`(`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **무료 기본 차단 목록** | Free | 갓 설치하면 **Block List Project Phishing + Scam**(`defaultEnabled: true`로 표시된 두 소스, `DefaultCatalog.recommendedDefaultSourceIDs`)이 활성화돼요. |
| **기기 내 파싱 / 정규화 / 중복 제거** | Free | `BlocklistParser`는 auto/plain/hosts/adblock/dnsmasq를 지원하고, 주석/빈 줄/잘못된 항목을 버리고, 정확히 일치하는 문자열을 중복 제거하며, 목록당 1,000,000개 규칙으로 제한해요. 다중 호스트 `hosts` 줄은 이제 첫 번째만이 아니라 그 줄의 **모든** 호스트를 방출해요(파서 규칙 버전 2). |
| **업스트림 바이트 검증** | Free | 가져온 바이트는 SHA-256으로 해시되고, 체크섬이 카탈로그의 `accepted_source_hashes`에 있을 때만 허용돼요. 불일치 시 Lava는 마지막 정상 캐시로 폴백하거나 fail-closed로 처리해요. |
| **보호 도메인 필터** | Free | 파싱된 모든 소스에서 보호 대상인 Lava / Apple / 신원 공급자 도메인(apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com 등)을 제거해, 업스트림 목록이 앱·터널·로그인을 망가뜨리지 못하게 해요. |
| **허용된 예외(허용 목록)** | Free | 차단 목록에도 불구하고 도메인을 허용하는 사용자 관리 허용 목록이에요. 무료 상한: 허용 25개 / 차단 25개 도메인(`FeatureLimits.free`). |
| **필터 규칙 예산(등급 지표)** | Free / Plus | 출시된 등급 지표는 컴파일된 도메인 **규칙** 총수예요: **Free 500K / Plus 2M**(`lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`의 `maxFilterRules`). 기존 목록 개수 상한을 대체해요. 등급을 초과하는 구성은 `exceedsTierFilterRuleLimit`를 표면화해요. |
| **더 높은 도메인 한도** | Plus | 허용 1,000개 / 차단 1,000개 도메인(`FeatureLimits.plus`). |
| **커스텀 차단 목록** | Plus | `allowsCustomBlocklists`. 커스텀 목록은 기기에서 가져와 파싱되고 로컬에 캐시되며, Lava 서버로 절대 프록시되지 않아요. |
| **웜 스타트업 아티팩트 재사용** | Free | 매니페스트 + 신원 핑거프린트 덕분에 터널이 디스크의 컴팩트 스냅샷을 재컴파일 없이 재사용할 수 있어요. 입력이 바뀌면 (프라이버시에 안전하게 필드 이름만 담은 사유와 함께) 재사용이 거부돼요. |
| **Smart Save(약화 시에만 확인)** | Free | 필터를 *강화*하거나 중립적인 편집(차단 목록 추가, 차단 도메인 추가)은 바로 적용돼요. 보호를 *약화*하는 편집 — 차단 목록 제거, 차단 도메인 제거, 허용된 예외 추가 — 은 먼저 검토 확인 시트를 거치며, 예외가 추가되면 "특별히 주의하세요" 패널이 떠요(`FiltersView.saveChanges()`, `weakensProtection`). |
| **예산 미터(저장 가능한 선택)** | Free / Plus | 선택 미터는 개수를 축약해서 표시하고(500K / 1.2M / 2M) 1.10의 소프트 상한 여유를 사용해요(목록별 합계는 중복 제거된 합집합을 약 7~10% 과대 집계함). 허용 오차 내의 개수는 소프트 상한을 넘을 때까지 예를 들어 "500K of 500K"로 표시되도록 고정돼요(`FilterRuleBudget`). |

> 권위 있는 예산 적용은 컴파일 시점에 중복 제거된 합집합에 대해 실행돼요(`FilterSnapshotPreparationService`). 기기 상한을 먼저 확인한 다음 등급 한도를 확인해요. 선택 시점의 UI 미터는 1.10의 소프트 상한 여유와 함께 목록별 합계를 사용해요.

---

## 3. 암호화된 DNS

차단되지 않은 쿼리에 대한 리졸버 전송 방식과 라우팅이에요.

| 기능 | 등급 | 비고 |
|---|---|---|
| **다섯 가지 리졸버 전송 방식** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic`(`DNSResolverTransport`). |
| **DoH / DoH3** | Free | HTTP/3를 선호하는 URLSession 기반 DoH예요. UI는 **실제로 h3 협상이 관측될 때만** **`DoH3`(슬래시 없음)**라고 표기해요(예: "Quad9 (DoH3)"). 선호일 뿐, 약속은 아니에요(`DoHTransport`). |
| **DoT** | Free | 풀링된 `NWConnection`(엔드포인트당 최대 4개), 유휴 노후화 갱신, 그리고 한 번의 새 연결 재시도를 사용해요. |
| **DoQ**(커스텀 전용) | Plus | DNS-over-QUIC에는 **기본 프리셋이 없어요** — **커스텀 `doq://` 리졸버**를 통해서만 도달할 수 있으며, 커스텀 DNS는 Plus예요. **쿼리마다 새 QUIC 연결**을 열어요(4-레인 풀은 동시성을 줄 뿐, 핸드셰이크 재사용은 아님). 연결 재사용은 iOS-26 배포 기준선으로 미뤄졌어요. |
| **프리셋 리졸버** | Free | Device DNS(기본값), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — 제공되는 경우 IP / DoH / DoT 변형으로(`DNSResolverPreset.allPresets`). |
| **리졸버 라우팅 및 페일오버** | Free | `ResolverOrchestrator`가 전송 방식별로 라우팅하고, 암호화된 계획에 엔드포인트가 없으면 plain DNS로 격하하며, 백오프 게이트와 함께 엔드포인트별 페일오버를 수행한 뒤 device-DNS 폴백을 해요. |
| **Device-DNS 폴백** | Free | 선택한 리졸버를 사용할 수 없을 때 현재 네트워크의 리졸버로 폴백해요. **기본값으로 켜짐.** `usingDeviceDNSFallback` 심각도로 표면화돼요. |
| **커스텀 DNS** | Plus | `allowsCustomDNS` — 사용자가 제공하는 리졸버(커스텀 프리셋을 위한 DNS-stamp 파싱 포함). |

---

## 4. 계정 및 제로 지식 백업

선택적 계정 로그인과 암호화된 설정 백업이에요. 보호를 사용하는 데 이 중 무엇도 필요하지 않아요.

| 기능 | 등급 | 비고 |
|---|---|---|
| **선택적 계정 로그인(Apple + Google)** | Free | 해시된 nonce와 함께 Supabase Auth(`grant_type=id_token`)에서 교환되는 네이티브 id_token 흐름이에요. 그 결과로 생긴 Supabase 세션만 기기 로컬의 Keychain에 저장돼요. 이메일/비밀번호 로그인은 의도적으로 제공하지 않아요(Dropped). |
| **제로 지식 암호화 백업** | Free | 클라이언트 측 AES-256-GCM 봉투예요. 무작위 페이로드 키는 PBKDF2-HMAC-SHA256(21만 회 반복) 키 슬롯에 래핑돼요. 암호문 + 비밀이 아닌 메타데이터만 Supabase `user_backups`(사용자별 RLS)에 업로드돼요. 서버는 사용자가 보유한 비밀 없이는 복호화할 수 없어요. |
| **최소화된 백업 페이로드** | Free | 활성화된 차단 목록 ID, 허용/차단 도메인, 리졸버 설정, 로컬 로그 환경설정, 가디언 외형 등을 백업해요. 그리고 `isPaid`, QA 플래그, 진단, 스냅샷, 전체 차단 목록 바이트는 명시적으로 제외해요. |
| **기기 비밀 키 슬롯** | Free | 동일 기기에서 매끄럽게 복원하기 위한, 기기 전용 Keychain(`...ThisDeviceOnly`, iCloud 동기화 안 됨)의 32바이트 기기 비밀이에요. |
| **복구 문구 + 지원 복구** | Free | 8단어 CVCV 문구(약 105비트)를 서버 보유 복구 share와 SHA256으로 결합해 지원 복구 슬롯을 잠금 해제해요. 이중 요소: 어느 한쪽만으로는 복호화할 수 없어요. |
| **패스키 복구 슬롯** | Free | 선택적 WebAuthn 게이트 슬롯이며 **제로 지식**이에요. 잠금 해제 키는 인증기의 WebAuthn PRF(`hmac-secret`) 출력에서 **기기 내부에서** 파생돼요(HKDF-SHA256). 서버는 패스키를 등록하지 않고, 챌린지를 발급하지 않으며, 복구 비밀을 보유하지 않고, 패스키 경로도 노출하지 않아요 — 이전의 서버 에스크로 설계는 폐기됐어요. 실제 기기에서의 프로덕션 준비는 Associated Domains / AASA 호스팅에 달려 있어요(Planned). |
| **계정 삭제 / 데이터 권리** | Free | 인증된 Worker 엔드포인트가 백업, 설정, 권한, 프로필, 버그 리포트 첨부 파일을 삭제한 뒤 Supabase Auth 사용자를 삭제해요. 그러면 앱은 로그아웃하고 로컬 잠금 해제 자료를 지워요. |

---

## 5. 위젯 및 Live Activity

잠금 화면과 Dynamic Island 존재감이에요.

| 기능 | 등급 | 비고 |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget`(`com.lavasec.app.widget`): 잠금 화면과 Dynamic Island에 표시되는 단일 `Activity<LavaActivityAttributes>`(확장 중앙 / compactLeading 가디언 / compactTrailing + 최소 상태 글리프). |
| **5가지 상태 보호 표시** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — 각각 가디언 포즈, SF Symbol, 제목에 매핑돼요. |
| **Live Activity 동작 버튼** | Free | 5분 / 10분 일시 정지, 재개, 재연결 — `LavaProtectionCommandService`를 통해 앱 프로세스에서 실행되는 `LiveActivityIntent`예요. 인증이 필요한 일시 정지 변형은 로컬 기기 인증을 요구해요. |
| **단일·중복 제거·리비전 게이트 조정** | Free | `LavaLiveActivityController`는 하나의 Activity를 유지하고, 실제 ID/콘텐츠가 바뀔 때만 업데이트하며, `ProtectionPauseStore` 리비전으로 업데이트를 게이팅해 오래된 인텐트 재시도가 상태를 되돌리지 못하게 해요. |
| **Live Activities 토글** | Free | 설정에서 사용자가 켜고 끌 수 있어요(`setUsesLiveActivities`). iPhone/iPad에서만 사용 가능해요. |

---

## 6. 온보딩

로컬 VPN 구성을 설치하고 합리적인 기본값을 설정하는 첫 실행 흐름이에요.

| 기능 | 등급 | 비고 |
|---|---|---|
| **다중 페이지 첫 실행 흐름** | Free | `OnboardingFlowView` — 6페이지: `lava, guardIntro, features, vpn, notifications, done`. (프로파일 설치와 알림 요청은 처음이 아니라 알맞은 단계에서 일어나요.) |
| **로컬 VPN 프로파일 설치** | Free | 온보딩 중 로컬 VPN 구성을 Connect-On-Demand 활성화 **없이** 설치해요. 그래서 완료 시점에 보호가 조용히 자동으로 켜지지 않고, Guard 표면이 권위를 유지해요. |
| **알림 권한 요청** | Free | 흐름 중 알림 단계에서 요청돼요. |
| **권장 기본값 적용** | Free | Device DNS 리졸버, device-DNS 폴백 켜짐, 로컬 로깅 켜짐(횟수 + 기록 + 활동), Block List Project Phishing + Scam 활성화, 계정 없이 계속(`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. 설정

구성, 보안, 진단, 피드백 표면이에요.

| 기능 | 등급 | 비고 |
|---|---|---|
| **앱 잠금 해제 비밀번호 + 생체 인증** | Free | `SecurityController`: Keychain에 저장된 솔트 적용 SHA256 비밀번호 검증기 + `LAContext` 생체 인증. 앱 잠금 해제 차단 오버레이와 scene-phase 변경 시 프라이버시 마스크를 동반해요. |
| **표면별 보호** | Free | `SecurityProtectedSurface`가 여섯 가지 표면을 게이팅해요: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. 각각 독립적으로 로컬 기기 인증을 요구할 수 있어요(예: 설정 탭은 `.requires(.appSettings)`를 반환). |
| **Lava Guard 외형 선택(7가지 외형)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`. 각각 짝지어진 Dynamic Island 글리프 색상이 있어요. 바텀시트 라디오 선택기("Choose your Guard", `LavaGuardLookPickerSheet`)에서 고르며, 아직 잠겨 있는 외형에는 잠금 글리프가 붙고 잠금 해제/업그레이드 패널이 시트 안에 있어요. |
| **앱 아이콘 맞추기** | Free | 선택한 가디언 외형에 짝지어진 선택적 대체 앱 아이콘이에요. |
| **외관** | Free | 라이트/다크/시스템 색상 구성표예요. |
| **로컬 전용 로깅 컨트롤** | Free | 필터링 횟수, 도메인 기록(진단), 네트워크 활동 토글 — 모두 기기에 저장돼요. 세분화된 로그(도메인 기록 + 네트워크 활동)는 **7일** 창으로 정리돼요(`LocalLogRetention.fineGrainedDays = 7`). 횟수와 Lava Guard 진행 상황은 더 오래 보관돼요. |
| **활동 / 도메인 로그(Guard 상세)** | Free | Guard 탭에서 도달하는 동적 로컬 전용 진단이에요(`GuardDestination.activity`). 다이제스트는 요청 **흐름**이에요 — "처리된 요청" 총수를 허용/차단 볼륨 막대로 나누고 "% 로컬 보호"를 표시해요(정직한 반올림: 아주 작은 비율은 `<1%`, 거의 전부인 비율은 `>99%`로 표시). **도메인 로그** 섹션에는 **Top Domains**(가장 많이 차단·허용된 것, 쿼리 횟수로 순위)와 **Domain History**(최근 조회 및 결정)가 있어요. 도메인 행은 기록 옵트인이 켜졌을 때만 나타나요. |
| **필터(Guard 상세)** | Free | Guard 탭에서 도달하는 단일 통합 필터 화면이에요. "My filter" 허브를 열면 두 선반이 있는 하나의 통합된 **My filter** 화면이 열려요 — **"Lava blocks these"**(차단 목록 + 개별 차단 도메인)와 **"Lava lets these through"**(허용된 예외) — 하나의 편집/저장 초안 흐름 아래에 있어요. 탭 상단에는 "Phone → Lava → Internet" 흐름 다이어그램이 있고, My filter를 열면 카탈로그가 자동으로 새로 고쳐져요. |
| **네트워크 활동(설정 → 고급)** | Free | 네트워크/런타임/사용자 전환의 한도 있는 로컬 전용 이벤트 스트림으로, App Group을 통해 공유돼요(`NetworkActivityLog`). 활동 표면에서 빠져 **설정 → 고급**("Nerd Stats" 다음, `SettingsRoute.networkActivity`)으로 이동했고, `.activityViewing` 잠금 뒤에 있으며 자체 프라이버시 패널("이 iPhone에만 남아요", 7일 보관)이 있어요. |
| **버그 리포트** | Free | 익명화된 번들을 `POST /v1/bug-reports`로 보내는 사용자 트리거 마법사예요. v1에는 도메인 기록이 없어요. 이제 번들은 빌드 출처(`appVersion`/`appBuild`/`sourceRevision`)와 연결 상태 정직성 카운터도 함께 담아요. 흔들어서 신고(`RageShakeDetector`)로도 도달할 수 있어요. |
| **구독 관리** | Plus | 활성 구독자의 경우 업그레이드 화면에 구독 관리(자동 갱신 플랜, `AppStore.showManageSubscriptions`를 통해), 구매 복원, 권한 만료 날짜가 표시돼요. 평생 잠금 해제는 관리 행이 표시되지 않아요. |
| **법적 고지 + 버전** | Free | 설정에는 제3자 법적 고지(자세히는 [제3자 고지](../legal/third-party-notices.md))와 버전/빌드 페이지가 표시돼요. |

---

## 앱 아키텍처(방향 잡기용)

세 개의 번들이 하나의 App Group `group.com.lavasec`을 공유하며, 이들에 컴파일되는 `lavasec-ios: Shared/` 소스 폴더가 함께 있어요.

- **LavaSecApp**(`com.lavasec.app`) — SwiftUI 앱 셸. 이 빌드에서 루트는 두 탭짜리 `TabView`(**Guard** + **Settings**)이며, 필터와 활동은 Guard 탭 아래 상세 화면으로 도달해요(네트워크 활동은 이제 설정 → 고급에 있어요).
- **LavaSecTunnel**(`.tunnel`) — 기기 내 DNS 필터/리졸브 엔진이에요.
- **LavaSecWidget**(`.widget`) — WidgetKit Live Activity예요.
- **Shared/** — 타깃 간 공유 소스(번들 아님): App Group, 명령 서비스, 마스코트, Live Activity 속성/인텐트.

앱 ↔ 확장 프로그램 제어는 Darwin 알림이 아니라 `NETunnelProviderSession` **provider message**(`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`)를 사용해요. 필터 규칙은 App Group 스냅샷 파일(`filter-snapshot.json` / `.compact`)로 앱 → 확장 프로그램을 건너가요.

---

## 관련 문서

- 로드맵 — 계획되었거나 폐기된 기능(Plus 가격/StoreKit 포지셔닝, Android 포팅, URL 수준 보호, 패스키 Associated-Domain 준비, 이스터에그 미니 게임, GPL-3.0 오픈소스 공개 등)은 이 공개 카탈로그가 아니라 비공개 로드맵에 있어요.
- [GPL 소스 URL 전용 준수 결정](../legal/gpl-source-url-only-compliance-decision.md)
- [오픈소스 목록 데이터 약관 예외](../legal/open-source-list-data-terms-carveout.md)
- [제3자 고지](../legal/third-party-notices.md)
