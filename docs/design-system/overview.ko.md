---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 디자인 시스템

> **대상 독자:** Lava Security iOS 앱을 다루는 디자인 + 엔지니어링 팀.
> **권위:** 이 문서와 계획이 충돌할 경우 **코드가 우선한다** — 차이점은 본문에 인라인으로 명시된다. 상태는 계획상의 지향이 아니라 코드로 확인된 현실을 반영한다. 상태 범례: **구현됨**(출시되어 코드에서 확인됨), **진행 중**(부분적으로 반영됨), **계획됨**(설계되었으나 미구현), **폐기됨**(거부되거나 되돌려짐).

이 문서는 디자인 철학, LavaTier 깊이 어휘, Guardian 마스코트, 카피 및 명명 규칙, 온보딩 UX, 국제화를 다룬다. 이 화면들 뒤에 있는 아키텍처 기반 구조(타깃, VPN 수명 주기, Guardian/보호 상태 모델 배선)에 대해서는 [iOS 클라이언트](../architecture/ios-client.md)를 참고하라. 제품 관점의 정리는 [제품 개요](../product/overview.md)를 참고하라.

---

## 1. 철학: 차분한 핵심, 얻어내는 깊이

Lava의 대상 사용자는 부모, 고령자 같은 비기술적인 일상 사용자이며, 디자인은 거기서 비롯된다. 일상적인 표면은 모두에게 차분하게 "그냥 작동한다". 추가적인 세부 사항, 즐거움, 제어는 사용자가 직접 찾아 나설 때에만 드러난다(**얻어낸다**). 어떤 것도 잔소리하지 않고, 어떤 것도 경보를 울리지 않으며, 기술적 장치는 찾기 전까지 보이지 않는다.

이 **"차분한 핵심, 얻어내는 깊이"** 모델은 세 가지 제품 깊이로 정리된다:

- **Calm** — 기본값, 모두가 가장 먼저 보는 그냥 작동하는 보호.
- **Celebratory** — 선택적으로 켜는 인식과 즐거움(연속 기록, 잠금 해제, 성공의 순간). 절대 잔소리하지 않는다.
- **Technical** — DNS, 진단, 통계. 사용자가 찾아 나서기 전까지 보이지 않는다.

차분한 자세를 뒷받침하는 두 가지 교차적 팔레트/톤 규칙이 있다:

- **빨강 = 위험 전용.** 빨강은 오직 위험과 오류에만 예약되며, 차분한 팔레트는 초록/주황이다. 이로써 빨강은 진짜 경보 신호로서 신뢰성을 유지한다. 위험 빨강은 `LavaStyle.dangerRed`로 토큰화되어 있으며, `LavaStyle.errorText`가 이를 별칭으로 가리킨다(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86). 뷰의 오류 텍스트가 이를 소비한다. 보호 틴트는 원시 `.green`/`.orange`가 아니라 의미론적 `ProtectionTintRole` 역할 테이블(lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7)을 통해 해석된다. 원시 `.red` 호출 지점이 몇 군데 실제로 남아 있으며(예: lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift), 이를 `LavaStyle.dangerRed`로 이전하는 것이 남은 정리 작업이다.
- **공포를 자극하는 보안 언어 금지.** 카피는 평이하고, 차분하며, 실용적이다. [§4 카피 및 명명](#4-카피-및-명명)을 참고하라.

### 오늘 존재하는 토큰화된 레이어 **(구현됨)**

디자인 시스템은 `LavaTier` 깊이 어휘(§2)와 함께 실제로 토큰화된 SwiftUI 레이어다:

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — 적응형 색상의 단일 진리원: ~18개의 의미론적 색상(`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …)이며, 각각 단일 `adaptiveColor(light:dark:)` 팩토리로 생성되어 라이트/다크가 함께 정의된다. 위험 빨강은 여기서 `dangerRed`/`errorText`로 토큰화된다(81/86행).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — 카드/패널/선택 표면 역할과 모서리 반경: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — 간격 척도: `xs`/`sm`/`md`/`lg`/`xl`와 `screenHorizontal`/`screenTop`/`screenBottom`.
- **`LavaActionRole`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift, v1.0) — 시스템 `ButtonRole`에 매핑된 의미론적 액션 역할 열거형(`.cancel`, `.close`, `.confirm`, `.destructive`). `NativeToolbarIconButton`에 `role:` 매개변수가 추가되어 광범위하게 사용되므로, 거의 모든 시트/툴바에서 툴바 글리프가 네이티브 역할 스타일링을 가져간다.

남은 격차는 아직 `LavaStyle.dangerRed`로 이전되지 않은 소수의 원시 `.red` 호출 지점이다(§1 참고).

> **컴포넌트 변동(v1.0).** `LavaTabOverviewCard`가 제거되었다. 필터 및 활동 헤드라인 블록은 이제 `LavaInfoCard` + `LavaOverviewMetricBlock`을 공유하여 크기와 위치가 정렬된다. 필터/활동 재설계와 함께 새로운 공유 컴포넌트가 도입되었다: `FiltersFlowDiagram`("Phone → Lava → Internet" 다이어그램), `ActivityFlowBar` / `ActivityFlowStatRow`(요청 흐름 다이제스트), `NetworkActivityPrivacyInfoPanel`, 그리고 `LavaGuardLookPickerSheet`(하단 시트 Guard 선택기). 가져오기/공유 흐름은 자체 콘텐츠 내 헤더를 네이티브 `importFlowToolbar`로 교체했다.

---

## 2. LavaTier — Floor / Window / Workshop **(구현됨)**

`LavaTier`는 "차분한 핵심, 얻어내는 깊이"를 토큰 레이어에 직접 인코딩하는 경량 깊이 어휘다. 전면적인 재테마가 아니라 어휘에 몇 가지 토큰 기본값을 더한 것이며, lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227의 열거형으로 출시되어 모든 뷰를 개조하는 대신 대표적인 표면에 배선되었다.

| 티어 | 깊이 | 의미 |
|---|---|---|
| **Floor** | calm | 모두를 위한 그냥 작동하는 보호 — 기본 표면. |
| **Window** | celebratory | 선택적으로 켜는 인식과 즐거움: 연속 기록, 잠금 해제, 성공의 순간. 절대 잔소리하지 않는다. |
| **Workshop** | technical | DNS, Nerd Stats, 진단. 찾기 전까지 보이지 않는다. |

`LavaTier`는 토큰 기본값을 지니는 `calm`/`celebratory`/`technical` 열거형이다:

- **강조 색상**(`accent`),
- `allowsDelightMotion` — celebratory / Window에서만 true,
- `usesMonospacedMetadata` — technical / Workshop에서만 true,

이는 `EnvironmentKey`와 `.lavaTier(_:)` 수정자, `.lavaTierMetadata()` 수정자를 통해 노출된다(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). 모든 뷰가 아니라 대표적인 표면에 배선되어 있다 — 예를 들어 lavasec-ios: LavaSecApp/SettingsView.swift의 `.lavaTier(.technical)`와 `.lavaTier(.celebratory)`. 의도적인 범위 한정은 세 가지 제품 깊이를 코드에서 읽기 쉽게 유지하고, 의도를 다시 도출하지 않고도 미래의 Android 소비자로 이식 가능하게 한다.

> **유의 사항(강조 색상 토큰화 계획됨, Phase 3):** `LavaColorRole`이 아직 생성되지 않아 `LavaTier.accent`는 여전히 원시 `LavaStyle` 색상으로 해석된다(LavaTokens.swift:~230). 강조 색상 토큰화는 완성된 표면이 아니라 열린 루프로 취급하라.

---

## 3. Soft Shield Guardian 마스코트 **(구현됨)**

**Soft Shield Guardian**는 Lava의 마스코트다 — 단순하게 모핑하는 얼굴을 가진 둥근 방패 — 로서 Guard 탭, Live Activity, Dynamic Island, 온보딩에서 보호 상태를 시각적으로 표현한다. 차분한 톤의 가장 눈에 띄는 전달자다.

상태 그래프는 플랫폼 비종속적이며 `LavaSecCore`에 위치한다(lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift). SwiftUI 렌더러는 lavasec-ios: Shared/SoftShieldGuardian.swift다.

### 3.1 7가지 표정 상태

마스코트는 **정확히 7개**의 표정 상태를 가지며, 허용된 전이 상태 그래프(`GuardianMascotState.allowedNextStates`, lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift로 고정됨)에 의해 통제된다:

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

알아둘 만한 그래프 제약: `sleeping`의 유일한 출구는 `waking`이며, `grateful`은 오직 `awake`로만 돌아간다. `awake ↔ grateful` 전이는 맞춤형 보간 프레임을 가진다 — 이것이 시스템의 유일한 **즐거움 모션**(Window 티어)이다.

> **`retrying` 대 `concerned` — 가장 중요한 톤 구분.** 둘 다 "완벽하게 건강하지는 않음"을 신호하지만, 매우 다르게 읽히며 혼동되어서는 안 된다:
> - **`retrying`**은 *걱정 없는, 자가 치유* 얼굴이다: 편안한(~0.80) 눈꺼풀, 수평인 눈, 평평한 입, 그리고 **걱정 기울임 없음**. 모션은 **얼굴이 아니라 상태 배지**가 담당한다 — 일시적 자가 복구는 절대 경보를 울려서는 안 된다. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`**은 *부드럽고, 도움을 구하는* 걱정이다: 올라간 안쪽 눈썹(`concernAmount` 1, `mouthCurve` -0.22)이 "손이 좀 필요해요"로 읽히며, **절대 험상궂은 노려봄이 아니다**. 진짜 문제는 꾸짖는 것이 아니라 도움을 청해야 한다. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 연결성 → 표정 매핑 (6 → 4)

보호 건강 상태는 `LavaSecCore`에서 **6개의 연결성 심각도** + 2개의 액션으로 평가된다(lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **심각도:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **액션:** `turnOff`, `reconnect`

Guard 탭은 그 6개의 심각도를 **4개의 얼굴**로 축약한다(`guardianState` in lavasec-ios: LavaSecApp/GuardView.swift:122). 얼굴은 의도적으로 상태 배지보다 *더 거칠고 차분한* 신호다 — 배지가 세부 사항을 담고, 얼굴은 단순하게 유지된다:

| 조건 | 마스코트 상태 |
|---|---|
| 일시적으로 일시정지됨 | `paused` |
| 연결됨 + `healthy` / `usingDeviceDNSFallback` | `awake` |
| 연결됨 + `recovering` / `networkUnavailable` | `retrying` |
| 연결됨 + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| 그 외 | `sleeping` |

> **틴트 조정.** 보호 틴트 색상의 세분성은 이 표정 분할과 조정된 상태로 유지되어 틴트와 얼굴이 절대 어긋나지 않는다. 표정 매핑과 의미론적 `ProtectionTintRole` 역할 테이블은 둘 다 오늘 출시되어 있다(lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, `AppViewModel.protectionTintRole`이 소비함). 역할을 완전히 토큰화된 색상으로 매핑할 `LavaColorRole` 색상 역할 토큰화만이 **계획됨** 상태로 남아 있다(DS 계획의 Phase 3).

### 3.3 스킨(룩) **(구현됨)**

마스코트는 **선택 가능한 7가지 방패 "룩"**으로 출시되며, `GuardianShieldStyle`로 영속화된다(lavasec-ios: Shared/LavaActivityAttributes.swift:5). 각각은 고유한 색상 구성과 짝지어진 Dynamic Island 글리프 색상을 가진다:

`original`, `fireOpal`(원시 값 `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz`(원시 값 `strawberryObsidian`), `emerald`, `kiwiCreme`.

두 개의 레거시 원시 값은 의도적이다 — "고치지" 말라. 영속화된 사용자 선택을 깨뜨릴 것이다.

### 3.4 개인정보 가림 **(구현됨)**

Guardian은 개인정보 가림을 존중한다: 표면이 개인정보 가림 처리될 때 **방패 자체는 보이는 상태로 유지하면서** 표정을 가릴 수 있다(`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). 보호의 존재는 안심을 준다. 가려지는 부분은 구체적인 감정 상태다.

### 3.5 이 트리에 없는 것 **(계획됨)**

Guard 이스터에그 미니 게임(탭 = 감사 애니메이션; 10초 길게 누르기 = 나쁜 도메인을 잡는 게임)은 **P3 / 백로그**다. 이는 기능 브랜치에서 보이는 추가 마스코트 표정(`confused` / `dazed` / `inZone` / `powerSurge`)을 더하게 된다 — 이들은 앱 타깃에 **없다**. 정본 사실에 따르면 마스코트는 정확히 **7개**의 상태를 가진다. 게임 표정을 출시된 것으로 문서화하지 말라.

---

## 4. 카피 및 명명

### 4.1 보이스 & 톤

평이하고, 차분하며, 실용적. 공포를 자극하는 보안 언어를 피하라. 범위에 대해 정직하라: Lava는 **로컬 DNS/차단 목록 필터링**이지, 모든 악성 도메인이나 URL이 차단된다는 보장이 아니다. 그리고 보호는 온보딩이 완료되는 순간 자동으로 켜진다고 **절대** 설명되지 않는다 — 현재 보호가 활성 상태인지에 대해서는 **Guard 탭이 권위를 가진다**.

### 4.2 DNS 전송 레이블

전송 주석은 엄격한 간결 규약을 따른다(lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 및 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, `DNSResolverPresetTests.swift`로 고정됨):

| 전송 | 레이블 | 비고 |
|---|---|---|
| DNS-over-HTTPS | `DoH` | URLSession 기반. |
| DNS-over-HTTP/3 | **`DoH3` (슬래시 없음)** | 예: "Quad9 (DoH3)". **실제로 h3 협상이 관찰될 때에만** 주석을 단다 — 선호하되 약속하지 않는다. 그 외에는 `DoH`로 되돌아간다. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| 일반 DNS | `IP` | |
| 디바이스 리졸버 | *(주석 없음)* | |

여기서 가장 많이 깨지는 규칙은 **슬래시 없는 `DoH3`**다 — `DoH3`라고 쓰고, 절대 `DoH/3`나 `DoH3 (h3)`라고 쓰지 말며, 추측으로 적용하지 말라. 이 전송 레이블들은 `DoHTransport`/`DNSResolverPreset`에서 방출된다. 모든 로케일에서 그대로 유지하되, 이들은 용어집의 번역 금지 항목이 *아니라는* 점에 유의하라(§4.3 참고).

### 4.3 번역 금지 용어

브랜드 및 프로토콜 용어는 **모든** 로케일에서 그대로 고정된다. 국제화 용어집의 번역 금지 목록이 권위를 가지며, 다음을 고정한다: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD, AdGuard, 1Hosts, StevenBlack.**

DNS 전송 중에서는 **DoH**만이 용어집의 번역 금지 항목이다. `DoH3`, `DoT`, `DoQ`는 용어집 용어가 아니라 전송 레이블이다(§4.2 참고). 이들도 여전히 그대로 쓰지만, 그 출처로 용어집을 인용하지 말라.

### 4.4 안전 프레이밍

결제는 해시 검증된, 허용 불가능한 **위협 가드레일**을 절대 우회하지 못한다. 우선순위를 일관되게 명시하라: **위협 가드레일 > 로컬 허용 목록(허용된 예외) > 차단 목록 > 기본 허용.**

---

## 5. 온보딩 UX **(구현됨)**

첫 실행 온보딩은 다중 페이지 흐름이다 — **6페이지**(`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — lavasec-ios: LavaSecApp/OnboardingFlowView.swift에 구현되어 있다. guardian 출현 순간에 `SoftShieldGuardian`을 재사용한다.

6페이지:

1. **The Internet Is Lava** (`lava`) — 위험을 은유로 표현; 주 액션 "Meet Lava".
2. **Lava Stands Guard Here** (`guardIntro`) — guardian 출현 순간.
3. **Feature Handoff** (`features`) — Lava가 하는 일; "Set Up Protection".
4. **Install Lava's Local VPN** (`vpn`) — iOS가 DNS 전용 패킷 터널을 "VPN"이라고 부르는 이유를 설명.
5. **Enable Notifications** (`notifications`) — 앞부분이 아니라 적절한 단계에서 제시되는 옵트인 프롬프트.
6. **Setup Complete** (`done`) — "Open Guard", 선택적 추가 설정 포함.

흐름에 내재된 디자인 결정:

- **"Use Default"가 주 액션, "Customize"가 보조 액션.** 비기술적 사용자를 위한 마찰 없는 기본 경로; 제어는 강요되는 것이 아니라 얻어내는 것이다.
- **위험을 공포가 아닌 은유로 표현**("The Internet Is Lava"), 차분한 톤과 일관됨.
- **흐름은 iOS가 왜 "VPN"이라고 말하는지 설명한다** — 패킷 터널은 DNS를 시스템 전역으로 필터링하는 유일한 방법이다; 트래픽 라우팅이 아니다.
- **완료 시 보호가 자동으로 켜진다고 절대 주장하지 않는다** — Guard가 권위를 유지한다.
- 공유 단계 페이지 레이아웃에서 셰브론 전용 뒤로 가기.

첫 실행이 흐름에서 설치하는 기본값: **Device DNS** 리졸버(`DNSResolverPreset.device`), **Device DNS 폴백 ON**, 로깅 켜짐(횟수 + 기록 + 활동), 그리고 "Continue without account."

> **기본 차단 목록 진리원.** 출시된 코드 기본값은 **Block List Basic**이다(`AppConfiguration.lavaRecommendedDefaults`, lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift에 정의됨). 실제 티어 게이트는 목록 개수가 *아니라* **필터 규칙 예산(Free 500K / Plus 2M)**이다. 티어 모델과 권장 기본 구성에 대해서는 [기능 카탈로그](../product/features.md)를 참고하라.

---

## 6. 국제화 **(진행 중)**

Lava는 **6개 로케일**로 현지화된다: **en**(원본) + **ja, zh-Hant, zh-Hans, de, fr**, Xcode 문자열 카탈로그를 통해.

- **현지화 이음매는 `.lavaLocalized`**다(`String.lavaLocalized` / `.lavaLocalizedFormat`, `LavaStrings.localized` → `NSLocalizedString`이 영어 폴백으로 뒷받침; lavasec-ios: LavaSecApp/LavaStrings.swift). **모든 컴포넌트 카피**는 이를 거쳐야 한다 — 뷰에 맨 문자열 리터럴 금지.
- **zh-Hant**는 첫 패스에서 대만 친화적 표현을 사용한다.
- App Store 메타데이터는 6개 로케일 모두에 존재한다.
- 번역 우선순위: ja, zh-Hant, zh-Hans, de, fr.
- v1.0 릴리스는 5개 로케일 문자열 카탈로그 검토(≈56건 수정)를 포함했고, 제품 명사가 복수형 **"Filters"**에서 단수형 **"Filter"**로 모든 로케일에서 변경되었다 — 번역을 단수형 "my filter" 모델과 일관되게 유지하라.

기반은 마련되었으나 릴리스 전 전체 인간 번역 검토가 아직 보류 중이므로, 전체 상태는 **진행 중**이다.

> **프레젠테이션 경계 정리(계획됨, Phase 4).** `LavaSecCore`/`Shared`는 영어 문자열이 아니라 *의미론*(심각도/액션 열거형, 아이콘 역할)을 담아야 한다. 심각도 틴트 프레젠테이션은 이미 의미론적 `ProtectionTintRole`로 끌어올려졌다. 남은 부분은 리졸버 `displayName`이 여전히 하드코딩된 영어 문자열("Google", "Cloudflare", "Quad9", "Device DNS")로 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift에 남아 있다는 점이다. Phase 4는 이를 OS별 앱 측 프레젠테이션 맵으로 끌어올린다 — i18n과 Android 이식성 모두에 올바른 방향이다.

i18n 메커니즘(현지화 용어집, 현지화 파일 스키마, 번역 검토 체크리스트)은 이 공개 세트가 아니라 내부 i18n 문서에 있다.

---

## 7. 참조 산출물

HTML 디자인 참조(비출시, 내부용): 온보딩 흐름 스토리보드, kiwi-creme guardian 룩 연구, 그리고 패널 내 주 버튼 시각 옵션.

DS 기반은 도입되었다: `LavaDesignSystem/` 그룹, `LavaSpacing`/반경/`dangerRed` 토큰, `LavaTier` 깊이 의미론, `LavaIcon` 역할 레이어가 모두 출시되었다(lavasec-ios: LavaSecApp/LavaDesignSystem/). 이식성/기반 계획에서 **계획됨** 상태로 남은 것은 `LavaColorRole` 강조 토큰화(Phase 3), 코어 측 영어 문자열을 위한 OS별 프레젠테이션 맵(Phase 4), 중립적 크로스 플랫폼 토큰 JSON, 그리고 더 넓은 Android 이식성 이음매다.
