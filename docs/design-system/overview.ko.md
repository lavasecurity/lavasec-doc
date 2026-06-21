---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 디자인 시스템

> **대상 독자:** Lava Security iOS 앱을 작업하는 디자인 + 엔지니어링.
> **권위:** 이 문서와 계획이 어긋날 때는 **코드가 우선**이에요 — 차이점은 본문에 함께 표시했어요. 상태는 계획상의 목표가 아니라 코드로 확인된 현실을 반영해요. 상태 범례: **구현됨**(출시되어 코드에서 확인됨), **진행 중**(일부만 반영됨), **계획됨**(설계되었으나 미구현), **중단됨**(거부 또는 되돌림).

이 문서는 디자인 철학, LavaTier 깊이 어휘, Guardian 마스코트, 문구 및 명명 규칙, 온보딩 UX, 국제화를 다뤄요. 이러한 화면 뒤의 아키텍처 연결(타깃, VPN 수명 주기, Guardian/보호 상태 모델 배선)에 대해서는 [iOS 클라이언트](../architecture/ios-client.md)를 참고하세요. 제품 관점에 대해서는 [제품 개요](../product/overview.md)를 참고하세요.

---

## 1. 철학: 차분한 핵심, 노력으로 얻는 깊이

Lava의 대상 독자는 기술에 익숙하지 않은 일상 사용자예요 — 부모님, 어르신 — 그리고 디자인은 거기서 출발해요. 일상적인 화면은 모두에게 차분하게 "그냥 작동"하고, 추가적인 세부 정보, 즐거움, 제어 기능은 사용자가 직접 찾아 나설 때만 드러나요(**노력으로 얻어요**). 무엇도 잔소리하지 않고, 무엇도 놀라게 하지 않으며, 기술적 장치는 찾기 전까지 보이지 않게 남아 있어요.

이 **"차분한 핵심, 노력으로 얻는 깊이"** 모델은 세 가지 제품 깊이로 정리돼요.

- **Calm** — 모두가 가장 먼저 보는, 그냥 작동하는 기본 보호.
- **Celebratory** — 선택적으로 켜는 인식과 즐거움(연속 기록, 잠금 해제, 성공의 순간). 절대 잔소리하지 않아요.
- **Technical** — DNS, 진단, 통계. 사용자가 찾아 나서기 전까지 보이지 않아요.

차분한 태도를 뒷받침하는 두 가지 전반적 팔레트/톤 규칙이 있어요.

- **빨강 = 위험 전용.** 빨강은 오직 위험과 오류에만 쓰여요. 차분한 팔레트는 초록/주황이에요. 이렇게 해서 빨강은 진짜 경보 신호로서의 신뢰성을 유지해요. 위험-빨강은 `LavaStyle.dangerRed`로 토큰화되어 있고, `LavaStyle.errorText`가 거기에 별칭으로 연결되어 있으며(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) 뷰의 오류 텍스트에서 사용돼요. 보호 색조는 원시 `.green`/`.orange`가 아니라 의미론적 `ProtectionTintRole` 역할 표(lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7)를 통해 해석돼요. 몇몇 원시 `.red` 호출 지점이 실제로 남아 있어요(예: lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — 이것들을 `LavaStyle.dangerRed`로 옮기는 게 남은 정리 작업이에요.
- **공포를 자극하는 보안 언어 금지.** 문구는 평이하고, 차분하고, 실용적이에요. [§4 문구 및 명명](#4-copy-naming)을 참고하세요.

### 오늘날 존재하는 토큰화된 계층 **(구현됨)**

디자인 시스템은 `LavaTier` 깊이 어휘(§2)와 더불어 실재하는, 토큰화된 SwiftUI 계층이에요.

- **`LavaStyle`**(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — 적응형 색상의 단일 진실 원천: 약 18개의 의미론적 색상(`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …)이며, 각각 하나의 `adaptiveColor(light:dark:)` 팩토리로 생성되어 라이트/다크가 함께 정의돼요. 위험-빨강은 여기서 `dangerRed`/`errorText`로 토큰화돼요(81/86행).
- **`LavaSurface`**(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — 카드/패널/선택 표면 역할과 모서리 반경: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`**(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — 간격 스케일: `xs`/`sm`/`md`/`lg`/`xl` 그리고 `screenHorizontal`/`screenTop`/`screenBottom`.
- **`LavaActionRole`**(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift, v1.0) — 시스템 `ButtonRole`에 매핑된 의미론적 액션-역할 열거형(`.cancel`, `.close`, `.confirm`, `.destructive`). `NativeToolbarIconButton`에 `role:` 매개변수가 추가되어 널리 사용되며, 그래서 도구 모음 글리프가 거의 모든 시트/도구 모음에서 네이티브 역할 스타일을 갖게 돼요.

남은 잔여 격차는 아직 `LavaStyle.dangerRed`로 옮겨지지 않은 소수의 원시 `.red` 호출 지점이에요(§1 참고).

> **컴포넌트 변동(v1.0).** `LavaTabOverviewCard`가 제거되었고, 이제 Filter와 Activity 표제 블록은 `LavaInfoCard` + `LavaOverviewMetricBlock`을 공유해서 크기와 위치가 맞춰져요. Filter/Activity 재설계와 함께 새로운 공유 컴포넌트가 들어왔어요: `FiltersFlowDiagram`("Phone → Lava → Internet" 다이어그램), `ActivityFlowBar` / `ActivityFlowStatRow`(요청-흐름 요약), `NetworkActivityPrivacyInfoPanel`, 그리고 `LavaGuardLookPickerSheet`(하단 시트 Guard 선택기). 가져오기/공유 흐름은 콘텐츠 안의 맞춤 헤더를 네이티브 `importFlowToolbar`로 교체했어요.

---

## 2. LavaTier — Floor / Window / Workshop **(구현됨)**

`LavaTier`는 "차분한 핵심, 노력으로 얻는 깊이"를 토큰 계층에 직접 담아내는 가벼운 깊이 어휘예요. 전체를 다시 테마링하는 게 아니라 어휘에 몇 가지 토큰 기본값을 더한 것이며, lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227에 열거형으로 출시되어, 모든 뷰를 개조하는 대신 대표적인 화면에 연결돼요.

| Tier | 깊이 | 의미 |
|---|---|---|
| **Floor** | calm | 모두를 위한 그냥 작동하는 보호 — 기본 화면. |
| **Window** | celebratory | 선택적으로 켜는 인식과 즐거움: 연속 기록, 잠금 해제, 성공의 순간. 절대 잔소리하지 않아요. |
| **Workshop** | technical | DNS, Nerd Stats, 진단. 찾기 전까지 보이지 않아요. |

`LavaTier`는 토큰 기본값을 담는 `calm`/`celebratory`/`technical` 열거형이에요.

- **강조 색상**(`accent`),
- `allowsDelightMotion` — celebratory / Window일 때만 true,
- `usesMonospacedMetadata` — technical / Workshop일 때만 true,

이는 `EnvironmentKey`와 `.lavaTier(_:)` 수정자, `.lavaTierMetadata()` 수정자를 통해 노출돼요(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). 모든 뷰가 아니라 대표적인 화면에 연결돼요 — 예: lavasec-ios: LavaSecApp/SettingsView.swift의 `.lavaTier(.technical)`와 `.lavaTier(.celebratory)`. 이렇게 의도적으로 범위를 좁히면 세 가지 제품 깊이가 코드에서 읽기 쉽게 유지되고, 의도를 다시 도출할 필요 없이 향후 Android 소비자로 이식할 수 있어요.

> **주의(강조 색상 토큰화는 계획됨, Phase 3):** `LavaColorRole`이 아직 만들어지지 않아서 `LavaTier.accent`는 여전히 원시 `LavaStyle` 색상으로 해석돼요(LavaTokens.swift:~230). 강조-색상 토큰화는 완성된 화면이 아니라 열린 과제로 여기세요.

---

## 3. Soft Shield Guardian 마스코트 **(구현됨)**

**Soft Shield Guardian**는 Lava의 마스코트예요 — 단순하게 변형되는 얼굴을 가진 둥근 방패 — Guard 탭, Live Activity, Dynamic Island, 온보딩에서 보호 상태를 시각적으로 표현해요. 차분한 톤을 가장 눈에 띄게 전달하는 매개체예요.

상태 그래프는 플랫폼에 무관하며 `LavaSecCore`(lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift)에 있어요. SwiftUI 렌더러는 lavasec-ios: Shared/SoftShieldGuardian.swift예요.

### 3.1 7가지 표정 상태

마스코트는 허용된-전환 상태 그래프(`GuardianMascotState.allowedNextStates`, lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift로 고정됨)에 의해 관리되는 **정확히 7가지** 표정 상태를 가져요.

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

알아둘 만한 그래프 제약: `sleeping`의 유일한 출구는 `waking`이고, `grateful`은 `awake`로만 돌아가요. `awake ↔ grateful` 전환에는 맞춤 보간 프레임이 있어요 — 이것이 시스템의 유일한 **즐거움 모션**(Window 등급)이에요.

> **`retrying` 대 `concerned` — 가장 중요한 톤 구분.** 둘 다 "완벽하게 건강하지는 않음"을 알리지만, 매우 다르게 읽히며 혼동해서는 안 돼요.
> - **`retrying`**은 *걱정 없이 스스로 회복하는* 얼굴이에요: 느슨한(~0.80) 눈꺼풀, 수평한 눈, 평평한 입, 그리고 **걱정 기울임 없음**. 모션은 **얼굴이 아니라 상태 배지**가 담당해요 — 일시적인 자가 회복은 절대 놀라게 해서는 안 돼요. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`**은 *부드럽게 도움을 청하는* 걱정이에요: 안쪽 눈썹이 올라가(`concernAmount` 1, `mouthCurve` -0.22) "손이 좀 필요해요"처럼 읽히고, **절대 엄한 노려봄이 아니에요**. 진짜 문제는 꾸짖는 게 아니라 도움을 청해야 해요. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 연결성 → 표정 매핑 (6 → 4)

보호 건강은 `LavaSecCore`에서 **6가지 연결성 심각도** + 2가지 동작으로 평가돼요(lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift).

- **심각도:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **동작:** `turnOff`, `reconnect`

Guard 탭은 그 6가지 심각도를 **4가지 얼굴**로 압축해요(lavasec-ios: LavaSecApp/GuardView.swift:122의 `guardianState`). 얼굴은 의도적으로 상태 배지보다 *더 거칠고 더 차분한* 신호예요 — 배지가 세부 정보를 담고, 얼굴은 단순하게 남아요.

| 조건 | 마스코트 상태 |
|---|---|
| 일시적으로 멈춤 | `paused` |
| connected + `healthy` / `usingDeviceDNSFallback` | `awake` |
| connected + `recovering` / `networkUnavailable` | `retrying` |
| connected + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| 그 외 | `sleeping` |

> **색조 일치.** 보호 색조 색상의 세분성은 이 표정 분할과 일치하게 유지되어, 색조와 얼굴이 절대 어긋나지 않아요. 표정 매핑과 의미론적 `ProtectionTintRole` 역할 표는 둘 다 오늘 출시되어 있어요(lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, `AppViewModel.protectionTintRole`에서 사용됨). 역할을 완전히 토큰화된 색상에 매핑할 `LavaColorRole` 색상-역할 토큰화만 **계획됨**으로 남아 있어요(DS 계획의 Phase 3).

### 3.3 스킨(룩) **(구현됨)**

마스코트는 `GuardianShieldStyle`로 저장되는 **7가지 선택 가능한 방패 "룩"**으로 출시돼요(lavasec-ios: Shared/LavaActivityAttributes.swift:5). 각각 고유한 색 조합과 짝을 이루는 Dynamic Island 글리프 색상을 가져요.

`original`, `fireOpal`(원시 값 `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz`(원시 값 `strawberryObsidian`), `emerald`, `kiwiCreme`.

두 개의 레거시 원시 값은 의도적이에요 — "고치지" 마세요. 저장된 사용자 선택을 깨뜨릴 거예요.

### 3.4 개인정보 가림 **(구현됨)**

Guardian은 개인정보 가림을 따라요: 화면이 개인정보 가림 상태일 때 **방패 자체는 보이는 채로** 표정을 가릴 수 있어요(`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). 보호가 존재한다는 점은 안심을 주고, 가려지는 부분은 구체적인 감정 상태예요.

### 3.5 이 트리에 없음 **(계획됨)**

Guard 이스터에그 미니게임(탭 = 감사 애니메이션, 10초 길게 누르기 = 나쁜 도메인 잡기 게임)은 **P3 / 백로그**예요. 이것은 기능 브랜치에서 보이는 추가 마스코트 표정(`confused` / `dazed` / `inZone` / `powerSurge`)을 더하게 되는데 — 이것들은 앱 타깃에 **없어요**. 정식 사실에 따르면 마스코트는 정확히 **7가지** 상태를 가지므로, 게임 표정을 출시된 것으로 문서화하지 마세요.

---

## 4. 문구 및 명명 {#4-copy-naming}

### 4.1 목소리와 톤

평이하고, 차분하고, 실용적으로. 공포를 자극하는 보안 언어는 피하세요. 범위에 대해 정직하게: Lava는 **로컬 DNS/차단 목록 필터링**이지, 모든 악성 도메인이나 URL이 차단된다는 보장이 아니에요. 그리고 보호가 온보딩이 완료되는 순간 자동으로 켜진다고 **절대** 설명하지 않아요 — 보호가 현재 활성 상태인지에 대해서는 **Guard 탭이 권위 있는 기준**이에요.

### 4.2 DNS 전송 레이블

전송 주석은 엄격한 간결 규칙을 따라요(lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 및 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, `DNSResolverPresetTests.swift`로 고정됨).

| 전송 | 레이블 | 비고 |
|---|---|---|
| DNS-over-HTTPS | `DoH` | URLSession 기반. |
| DNS-over-HTTP/3 | **`DoH3`(슬래시 없음)** | 예: "Quad9 (DoH3)". **실제로 h3 협상이 관찰될 때만** 주석을 달아요 — 선호하되 절대 약속하지 않아요. 그 외에는 `DoH`로 대체돼요. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| 평문 DNS | `IP` | |
| 기기 해석기 | *(주석 없음)* | |

여기서 가장 자주 어겨지는 규칙은 **슬래시 없는 `DoH3`**예요 — `DoH3`라고 쓰고, 절대 `DoH/3`나 `DoH3 (h3)`라고 쓰지 말고, 절대 추측으로 적용하지 마세요. 이 전송 레이블은 `DoHTransport`/`DNSResolverPreset`에서 나오므로 모든 로케일에서 그대로 유지하되, 용어집의 번역 금지 항목은 *아니라는* 점에 유의하세요(§4.3 참고).

### 4.3 번역 금지 용어

브랜드 및 프로토콜 용어는 **모든** 로케일에서 그대로 고정돼요. 현지화 용어집의 번역 금지 목록이 권위 있는 기준이며, 다음을 고정해요: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

DNS 전송 중에서는 **DoH**만 용어집 번역 금지 항목이에요. `DoH3`, `DoT`, `DoQ`는 전송 레이블이지(§4.2 참고) 용어집 용어가 아니에요. 이것들도 그대로 적되, 출처로 용어집을 인용하지는 마세요.

### 4.4 안전 프레이밍

결제는 해시로 검증된, 허용 불가능한 **위협 가드레일**을 절대 우회하지 못해요. 우선순위를 일관되게 진술하세요: **위협 가드레일 > 로컬 허용 목록(허용된 예외) > 차단 목록 > 기본 허용.**

---

## 5. 온보딩 UX **(구현됨)**

첫 실행 온보딩은 여러 페이지로 된 흐름이에요 — **6페이지**(`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — lavasec-ios: LavaSecApp/OnboardingFlowView.swift에 구현되어 있어요. guardian 등장 순간에 `SoftShieldGuardian`을 재사용해요.

6페이지:

1. **인터넷은 용암이에요**(`lava`) — 위험을 은유로 표현, 기본 동작은 "Meet Lava".
2. **여기서 Lava가 지켜요**(`guardIntro`) — guardian 등장 순간.
3. **기능 인계**(`features`) — Lava가 하는 일, "Set Up Protection".
4. **Lava의 로컬 VPN 설치**(`vpn`) — iOS가 DNS 전용 패킷 터널을 왜 "VPN"이라고 부르는지 설명.
5. **알림 켜기**(`notifications`) — 처음부터가 아니라 적절한 단계에서 제시되는 선택적 허용 프롬프트.
6. **설정 완료**(`done`) — "Open Guard", 선택적 추가 설정 포함.

이 흐름에 녹아 있는 디자인 결정:

- **"Use Default"가 기본 동작이고, "Customize"가 보조 동작이에요.** 기술에 익숙하지 않은 사용자를 위한 마찰 없는 기본 경로이고, 제어는 강요되는 게 아니라 노력으로 얻어요.
- **위험을 공포가 아니라 은유로 표현**("인터넷은 용암이에요"), 차분한 톤과 일관돼요.
- **이 흐름은 iOS가 왜 "VPN"이라고 하는지 설명해요** — 패킷 터널은 시스템 전반에서 DNS를 필터링하는 유일한 방법이며, 트래픽 라우팅이 아니에요.
- **완료 시 보호가 자동으로 켜진다고 절대 주장하지 않아요** — Guard가 권위 있는 기준으로 남아요.
- 셰브론만 있는 뒤로 가기, 공유된 단계-페이지 레이아웃 위에서.

이 흐름이 설치하는 첫 실행 기본값: **Device DNS** 해석기(`DNSResolverPreset.device`), **기기 DNS 대체 켜짐**, 로깅 켜짐(횟수 + 기록 + 활동), 그리고 "계정 없이 계속하기."

> **기본-차단 목록 차이(코드가 우선).** 온보딩 계획 문구는 HaGeZi Multi Light를 기본 차단 목록으로 나열하지만, 출시된 코드 기본값은 **Block List Project Phishing + Scam**이에요(`AppConfiguration.lavaRecommendedDefaults`, lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift에 정의됨). 실제 등급 게이트는 목록 개수가 *아니라* **필터-규칙 예산(Free 500K / Plus 2M)**이에요. 내부적으로 추적 중이에요. 등급 모델과 권장 기본 구성에 대해서는 [기능 카탈로그](../product/features.md)를 참고하세요.

---

## 6. 국제화 **(진행 중)**

Lava는 **6개 로케일**로 현지화돼요: **en**(소스) + **ja, zh-Hant, zh-Hans, de, fr**, Xcode 문자열 카탈로그를 통해서요.

- **현지화 이음새는 `.lavaLocalized`예요**(`String.lavaLocalized` / `.lavaLocalizedFormat`, `LavaStrings.localized` → `NSLocalizedString`로 뒷받침되며 영어 대체 포함; lavasec-ios: LavaSecApp/LavaStrings.swift). **모든 컴포넌트 문구**는 이것을 거쳐야 해요 — 뷰에 맨 문자열 리터럴 금지.
- **zh-Hant**는 첫 패스에서 대만 친화적 표현을 써요.
- App Store 메타데이터가 6개 로케일 모두에 존재해요.
- 번역 우선순위: ja, zh-Hant, zh-Hans, de, fr.
- v1.0 릴리스는 다섯 개 로케일 문자열-카탈로그 검토(≈56건 수정)를 포함했고, 제품 명사가 복수형 **"Filters"**에서 단수형 **"Filter"**로 모든 로케일에서 바뀌었어요 — 단수형 "my filter" 모델과 일관되게 번역을 유지하세요.

기반은 마련되어 있지만 릴리스 전 완전한 인간 번역 검토가 아직 남아 있어서, 전체 상태는 **진행 중**이에요.

> **표현-경계 정리(계획됨, Phase 4).** `LavaSecCore`/`Shared`는 영어 문자열이 아니라 *의미론*(심각도/동작 열거형, 아이콘 역할)을 담아야 해요. 심각도 색조 표현은 이미 의미론적 `ProtectionTintRole`로 끌어올려졌어요. 남은 잔여물은 해석기 `displayName`이 여전히 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift에 하드코딩된 영어 문자열("Google", "Cloudflare", "Quad9", "Device DNS")이라는 점이에요. Phase 4는 이것들을 OS별 앱 측 표현 맵으로 끌어올려요 — i18n과 Android 이식성 모두에 맞아요.

i18n 메커니즘(현지화 용어집, 현지화-파일 스키마, 번역-검토 체크리스트)은 이 공개 문서 세트가 아니라 내부 i18n 문서에 있어요.

---

## 7. 참고 산출물

HTML 디자인 참고 자료(미출시, 내부용): 온보딩 흐름 스토리보드, kiwi-creme guardian 룩 연구, 패널 내 기본-버튼 시각 옵션.

DS 기반은 출시되었어요: `LavaDesignSystem/` 그룹, `LavaSpacing`/반경/`dangerRed` 토큰, `LavaTier` 깊이 의미론, `LavaIcon` 역할 계층이 모두 출시돼요(lavasec-ios: LavaSecApp/LavaDesignSystem/). 이식성/기반 계획에서 **계획됨**으로 남은 것은 `LavaColorRole` 강조 토큰화(Phase 3), 코어 측 영어 문자열을 위한 OS별 표현 맵(Phase 4), 중립적인 크로스 플랫폼 토큰 JSON, 그리고 더 넓은 Android-이식성 이음새예요.
