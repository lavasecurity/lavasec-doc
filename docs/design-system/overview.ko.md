---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 디자인 시스템

> **대상 독자:** Lava Security iOS 앱을 만드는 디자인 + 엔지니어링 팀.
> **기준:** 이 문서와 계획이 어긋날 때는 **코드가 우선**이에요 — 차이가 나는 부분은 본문에서 바로 짚어드려요. 상태는 계획상의 목표가 아니라 코드로 확인된 실제 상황을 반영해요. 상태 범례: **구현됨**(출시되어 코드에서 확인됨), **진행 중**(일부만 반영됨), **계획됨**(설계는 됐지만 아직 만들지 않음), **중단됨**(반려되거나 되돌려짐).

이 문서는 디자인 철학, LavaTier 깊이 용어, Guardian 마스코트, 카피 및 네이밍 규칙, 온보딩 UX, 국제화를 다뤄요. 이 화면들 뒤에 있는 아키텍처 배관(타깃, VPN 수명 주기, Guardian/보호 상태 모델 연결)은 [iOS 클라이언트](../architecture/ios-client.md)를, 제품 관점의 설명은 [제품 개요](../product/overview.md)를 참고하세요.

---

## 1. 철학: 차분한 코어, 차근차근 드러나는 깊이

Lava의 사용자는 기술에 익숙하지 않은 일상적인 사람들 — 부모님, 어르신 — 이고, 디자인은 거기에서 출발해요. 일상적으로 보이는 화면은 누구에게나 차분하게 "그냥 작동"하고, 더 자세한 정보와 즐거움, 그리고 제어 기능은 사용자가 직접 찾아 들어갈 때에만 **차근차근** 드러나요. 어떤 것도 보채지 않고, 어떤 것도 놀라게 하지 않으며, 기술적인 장치는 찾기 전까지는 보이지 않아요.

이 **"차분한 코어, 차근차근 드러나는 깊이"** 모델은 세 가지 제품 깊이로 정리돼요:

- **차분함(Calm)** — 누구나 가장 먼저 보는, 그냥 작동하는 기본 보호.
- **즐거움(Celebratory)** — 선택해서 켜는 인식과 즐거움(연속 기록, 잠금 해제, 성공의 순간). 절대 보채지 않아요.
- **기술(Technical)** — DNS, 진단, 통계. 사용자가 직접 찾기 전까지는 보이지 않아요.

차분한 자세를 떠받치는 두 가지 공통 팔레트/톤 규칙이 있어요:

- **빨강 = 위험 전용.** 빨강은 오직 위험과 오류에만 써요. 차분한 팔레트는 초록/주황이에요. 이렇게 해야 빨강이 진짜 경보 신호로서 신뢰를 유지해요. 위험-빨강은 `LavaStyle.dangerRed`로 토큰화되어 있고 `LavaStyle.errorText`가 여기에 별칭으로 연결돼요(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86). 뷰의 오류 텍스트가 이 값을 사용해요. 보호 색조는 원시 `.green`/`.orange`가 아니라 의미 기반 `ProtectionTintRole` 역할 테이블(lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7)을 통해 결정돼요. 원시 `.red`를 그대로 쓰는 곳이 몇 군데 정말로 남아 있어요(예: lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift). 이를 `LavaStyle.dangerRed`로 옮기는 게 남은 정리 작업이에요.
- **두려움을 자극하는 보안 표현 금지.** 카피는 쉽고, 차분하고, 실용적이에요. [§4 카피 및 네이밍](#4-copy-naming)을 참고하세요.

### 지금 존재하는 토큰화 레이어 **(구현됨)**

디자인 시스템은 실제로 토큰화된 SwiftUI 레이어이고, `LavaTier` 깊이 용어(§2)와 나란히 동작해요:

- **`LavaStyle`**(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — 적응형 색상의 단일 출처: 약 18개의 의미 기반 색상(`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …). 각 색상은 단일 `adaptiveColor(light:dark:)` 팩토리로 만들어져서 라이트/다크가 함께 정의돼요. 위험-빨강은 여기서 `dangerRed`/`errorText`로 토큰화돼요(81/86행).
- **`LavaSurface`**(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — 카드/패널/선택 표면 역할과 모서리 반경: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`**(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — 간격 스케일: `xs`/`sm`/`md`/`lg`/`xl`에 더해 `screenHorizontal`/`screenTop`/`screenBottom`.

남은 잔여 격차는 아직 `LavaStyle.dangerRed`로 옮기지 않은 몇 안 되는 원시 `.red` 사용 지점이에요(§1 참고).

---

## 2. LavaTier — Floor / Window / Workshop **(구현됨)**

`LavaTier`는 "차분한 코어, 차근차근 드러나는 깊이"를 토큰 레이어에 곧바로 담아내는 가벼운 깊이 용어예요. 전면적인 리테마가 아니라 용어와 몇 가지 토큰 기본값일 뿐이고, lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227에 enum으로 출시되어 모든 뷰를 손보는 대신 대표적인 화면에 연결돼 있어요.

| 티어 | 깊이 | 의미 |
|---|---|---|
| **Floor** | 차분함 | 누구에게나 그냥 작동하는 보호 — 기본 표면. |
| **Window** | 즐거움 | 선택해서 켜는 인식과 즐거움: 연속 기록, 잠금 해제, 성공의 순간. 절대 보채지 않아요. |
| **Workshop** | 기술 | DNS, Nerd Stats, 진단. 찾기 전까지는 보이지 않아요. |

`LavaTier`는 토큰 기본값을 담은 `calm`/`celebratory`/`technical` enum이에요:

- **강조 색상**(`accent`),
- `allowsDelightMotion` — 즐거움 / Window일 때만 true,
- `usesMonospacedMetadata` — 기술 / Workshop일 때만 true,

이는 `EnvironmentKey`와 `.lavaTier(_:)` 모디파이어, `.lavaTierMetadata()` 모디파이어를 통해 노출돼요(lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). 모든 뷰가 아니라 대표적인 화면에 연결돼 있어요 — 예를 들어 lavasec-ios: LavaSecApp/SettingsView.swift의 `.lavaTier(.technical)`과 `.lavaTier(.celebratory)`. 이렇게 의도적으로 범위를 좁히면 세 가지 제품 깊이가 코드에서 읽기 쉽게 드러나고, 의도를 다시 풀어내지 않고도 향후 Android 사용자 환경으로 이식할 수 있어요.

> **유의(강조 색상 토큰화는 계획됨, Phase 3):** `LavaColorRole`이 아직 만들어지지 않아서 `LavaTier.accent`는 여전히 원시 `LavaStyle` 색상으로 결정돼요(LavaTokens.swift:~230). 강조 색상 토큰화는 완성된 화면이 아니라 열린 과제로 보세요.

---

## 3. Soft Shield Guardian 마스코트 **(구현됨)**

**Soft Shield Guardian**은 Lava의 마스코트예요 — 둥근 방패에 단순하면서 변형되는 얼굴이 있는 캐릭터로, Guard 탭, Live Activity, Dynamic Island, 온보딩에서 보호 상태를 시각적으로 표현해요. 차분한 톤을 가장 잘 보여주는 매개체예요.

상태 그래프는 플랫폼에 종속되지 않고 `LavaSecCore`에 들어 있어요(lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift). SwiftUI 렌더러는 lavasec-ios: Shared/SoftShieldGuardian.swift예요.

### 3.1 7가지 표정 상태

마스코트에는 **정확히 7가지** 표정 상태가 있고, 허용된 전환 상태 그래프(`GuardianMascotState.allowedNextStates`, lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift로 고정)로 관리돼요:

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

알아둘 만한 그래프 제약: `sleeping`의 유일한 출구는 `waking`이고, `grateful`은 `awake`로만 돌아가요. `awake ↔ grateful` 전환에는 전용 보간 프레임이 있는데, 이게 이 시스템에서 유일한 **즐거움 모션**(Window 티어)이에요.

> **`retrying` vs `concerned` —가장 중요한 톤 구분.** 둘 다 "완벽하게 건강하진 않음"을 나타내지만, 읽히는 느낌이 아주 다르므로 섞으면 안 돼요:
> - **`retrying`**은 *걱정 없이 스스로 회복하는* 얼굴이에요: 느슨한(~0.80) 눈꺼풀, 수평인 눈, 평평한 입, 그리고 **걱정스러운 기울기 없음**. 움직임은 **얼굴이 아니라 상태 배지**가 담당해요 — 잠깐의 자가 회복이 사용자를 놀라게 해서는 안 돼요.(lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`**은 *부드럽게 도움을 청하는* 걱정이에요: 안쪽 눈썹이 올라가고(`concernAmount` 1, `mouthCurve` -0.22) "도와주면 좋겠어요"처럼 읽혀요. **절대 매서운 눈빛이 아니에요.** 진짜 문제는 도움을 청하는 느낌이어야지, 꾸짖는 느낌이면 안 돼요.(lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 연결 상태 → 표정 매핑 (6 → 4)

보호 상태는 `LavaSecCore`에서 **6가지 연결 심각도** + 2가지 동작으로 평가돼요(lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **심각도:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **동작:** `turnOff`, `reconnect`

Guard 탭은 이 6가지 심각도를 **4가지 얼굴**로 모아요(`guardianState`, lavasec-ios: LavaSecApp/GuardView.swift:122). 얼굴은 의도적으로 상태 배지보다 *더 거칠고 차분한* 신호예요 — 세부 정보는 배지가 담고, 얼굴은 단순하게 유지돼요:

| 조건 | 마스코트 상태 |
|---|---|
| 일시적으로 멈춤 | `paused` |
| 연결됨 + `healthy` / `usingDeviceDNSFallback` | `awake` |
| 연결됨 + `recovering` / `networkUnavailable` | `retrying` |
| 연결됨 + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| 그 외 | `sleeping` |

> **색조 일치.** 보호 색조의 세분화는 이 표정 구분과 계속 맞춰져 있어서 색조와 얼굴이 어긋나지 않아요. 표정 매핑과 의미 기반 `ProtectionTintRole` 역할 테이블은 모두 지금 출시돼 있어요(lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, `AppViewModel.protectionTintRole`에서 사용). 역할을 완전히 토큰화된 색상으로 매핑할 `LavaColorRole` 색상-역할 토큰화만 **계획됨** 상태로 남아 있어요(DS 계획의 Phase 3).

### 3.3 스킨(룩) **(구현됨)**

마스코트는 **선택 가능한 7가지 방패 "룩"**으로 출시되고, `GuardianShieldStyle`로 저장돼요(lavasec-ios: Shared/LavaActivityAttributes.swift:5). 각 룩은 고유한 색 조합과 짝을 이루는 Dynamic Island 글리프 색상을 가져요:

`original`, `fireOpal`(원시값 `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz`(원시값 `strawberryObsidian`), `emerald`, `kiwiCreme`.

두 개의 레거시 원시값은 의도적인 거예요 — "고치지" 마세요. 고치면 저장된 사용자 선택이 깨져요.

### 3.4 개인정보 가림 **(구현됨)**

Guardian은 개인정보 가림을 지켜요: 화면이 개인정보 가림 상태일 때 표정은 가릴 수 있지만 **방패 자체는 계속 보여요**(`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). 보호가 있다는 사실은 안심을 주고, 숨겨지는 건 구체적인 감정 상태예요.

### 3.5 이 트리에는 없음 **(계획됨)**

Guard 이스터에그 미니게임(탭 = 감사 애니메이션, 10초 길게 누르기 = 나쁜 도메인 잡기 게임)은 **P3 / 백로그**예요. 기능 브랜치에서 보이는 추가 마스코트 표정(`confused` / `dazed` / `inZone` / `powerSurge`)을 더하게 되지만, 이는 앱 타깃에 **없어요**. 정식 사실에 따르면 마스코트의 상태는 정확히 **7가지**예요. 게임 표정을 출시된 것으로 문서화하지 마세요.

---

## 4. 카피 및 네이밍

### 4.1 목소리와 톤

쉽고, 차분하고, 실용적으로. 두려움을 자극하는 보안 표현은 피해요. 범위를 정직하게 밝혀요: Lava는 **로컬 DNS/차단목록 필터링**이지, 모든 악성 도메인이나 URL을 차단한다는 보장이 아니에요. 그리고 보호는 온보딩이 끝나는 순간 **자동으로 켜진다고** 절대 설명하지 않아요 — 현재 보호가 켜져 있는지는 **Guard 탭이 기준**이에요.

### 4.2 DNS 전송 방식 라벨

전송 방식 표기는 엄격한 간결 규칙을 따라요(lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 및 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, `DNSResolverPresetTests.swift`로 고정):

| 전송 방식 | 라벨 | 비고 |
|---|---|---|
| DNS-over-HTTPS | `DoH` | URLSession 기반. |
| DNS-over-HTTP/3 | **`DoH3`(슬래시 없음)** | 예: "Quad9 (DoH3)". **실제로 h3 협상이 관찰될 때에만** 표기 — 약속이 아니라 선호일 뿐이고, 그렇지 않으면 `DoH`로 돌아가요. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| 일반 DNS | `IP` | |
| 기기 리졸버 | *(표기 없음)* | |

여기서 가장 자주 어기는 규칙은 **슬래시 없는 `DoH3`**예요 — `DoH/3`이나 `DoH3 (h3)`가 아니라 `DoH3`로 쓰고, 추측해서 붙이지 마세요. 이 전송 방식 라벨은 `DoHTransport`/`DNSResolverPreset`에서 나와요. 모든 로케일에서 그대로 두되, 이것들은 용어집의 번역 금지 항목이 *아니라는* 점에 유의하세요(§4.3 참고).

### 4.3 번역 금지 용어

브랜드와 프로토콜 용어는 **모든** 로케일에서 그대로 고정돼요. 로컬라이제이션 용어집의 번역 금지 목록이 기준이고, 다음을 고정해요: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

DNS 전송 방식 중에서는 **DoH**만 용어집의 번역 금지 항목이에요. `DoH3`, `DoT`, `DoQ`는 용어집 용어가 아니라 전송 방식 라벨이에요(§4.2 참고). 여전히 그대로 쓰지만, 출처로 용어집을 인용하지는 마세요.

### 4.4 안전 표현 방식

결제로는 해시 검증을 거친, 예외를 둘 수 없는 **위협 가드레일**을 절대 우회할 수 없어요. 우선순위를 일관되게 명시하세요: **위협 가드레일 > 로컬 허용목록(허용된 예외) > 차단목록 > 기본 허용.**

---

## 5. 온보딩 UX **(구현됨)**

첫 실행 온보딩은 여러 페이지로 된 흐름이에요 — **6페이지**(`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — lavasec-ios: LavaSecApp/OnboardingFlowView.swift에 구현돼 있어요. guardian이 등장하는 순간에는 `SoftShieldGuardian`을 재사용해요.

6페이지는 다음과 같아요:

1. **인터넷은 용암이에요**(`lava`) — 위험을 비유로 표현, 기본 동작은 "Lava 만나기".
2. **Lava가 여기를 지켜요**(`guardIntro`) — guardian이 등장하는 순간.
3. **기능 안내**(`features`) — Lava가 하는 일, "보호 설정하기".
4. **Lava의 로컬 VPN 설치**(`vpn`) — DNS 전용 패킷 터널을 iOS가 왜 "VPN"이라고 부르는지 설명.
5. **알림 켜기**(`notifications`) — 처음부터가 아니라 알맞은 단계에서 보여주는 선택 안내.
6. **설정 완료**(`done`) — "Guard 열기", 선택적으로 추가 설정 가능.

흐름에 담긴 디자인 결정들:

- **"기본값 사용"이 기본 동작, "직접 설정"이 보조 동작.** 기술에 익숙하지 않은 사용자를 위한 마찰 없는 기본 경로 — 제어는 강요되는 게 아니라 차근차근 얻어가는 거예요.
- **위험은 두려움이 아니라 비유로 표현**("인터넷은 용암이에요") — 차분한 톤과 일관돼요.
- **흐름은 iOS가 왜 "VPN"이라고 하는지 설명해요** — 패킷 터널은 시스템 전체에서 DNS를 필터링하는 유일한 방법이고, 트래픽을 우회시키는 게 아니에요.
- **완료 시점에 보호가 자동으로 켜진다고 절대 주장하지 않아요** — Guard가 계속 기준이에요.
- 뒤로 가기는 셰브론만, 공유 단계-페이지 레이아웃 위에서.

첫 실행 흐름이 설치하는 기본값: **기기 DNS** 리졸버(`DNSResolverPreset.device`), **기기 DNS 폴백 켜짐**, 로깅 켜짐(횟수 + 기록 + 활동), 그리고 "계정 없이 계속하기".

> **기본 차단목록 차이(코드가 우선).** 온보딩 계획 카피에는 기본 차단목록이 HaGeZi Multi Light로 적혀 있지만, 출시된 코드 기본값은 **Block List Project Phishing + Scam**이에요(`AppConfiguration.lavaRecommendedDefaults`, lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift에 정의). 실제 티어 기준은 목록 개수가 *아니라* **필터 규칙 예산(Free 500K / Plus 2M)**이에요. 내부적으로 추적 중이에요. 티어 모델과 권장 기본 설정은 [기능 카탈로그](../product/features.md)를 참고하세요.

---

## 6. 국제화 **(진행 중)**

Lava는 **6개 로케일**로 현지화돼요: **en**(원본) + **ja, zh-Hant, zh-Hans, de, fr**, Xcode 문자열 카탈로그를 통해서.

- **현지화 이음매는 `.lavaLocalized`예요**(`String.lavaLocalized` / `.lavaLocalizedFormat`, `LavaStrings.localized` → `NSLocalizedString`을 영어 폴백과 함께 사용; lavasec-ios: LavaSecApp/LavaStrings.swift). **모든 컴포넌트 카피**는 이걸 거쳐야 해요 — 뷰에 그대로 박은 문자열 리터럴은 안 돼요.
- **zh-Hant**는 첫 번째 작업에서 대만에 맞는 표현을 써요.
- App Store 메타데이터는 6개 로케일 모두에 존재해요.
- 번역 우선순위: ja, zh-Hant, zh-Hans, de, fr.

기초는 갖춰져 있지만 출시 전 전체 사람 번역 검수가 아직 남아 있어서, 전반적인 상태는 **진행 중**이에요.

> **표현 경계 정리(계획됨, Phase 4).** `LavaSecCore`/`Shared`는 영어 문자열이 아니라 *의미*(심각도/동작 enum, 아이콘 역할)를 담아야 해요. 심각도 색조 표현은 이미 의미 기반 `ProtectionTintRole`로 옮겨졌어요. 남은 잔여는 리졸버 `displayName`이 여전히 lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift에 영어 문자열("Google", "Cloudflare", "Quad9", "Device DNS")로 하드코딩돼 있다는 점이에요. Phase 4에서 이를 OS별 앱 측 표현 맵으로 끌어올려요 — i18n과 Android 이식성 모두에 맞는 방식이에요.

i18n 작동 방식(로컬라이제이션 용어집, 로컬라이제이션 파일 스키마, 번역 검수 체크리스트)은 이 공개 문서가 아니라 내부 i18n 문서에 있어요.

---

## 7. 참고 산출물

HTML 디자인 참고 자료(출시되지 않는 내부용): 온보딩 흐름 스토리보드, kiwi-creme guardian 룩 연구, 패널 내 기본 버튼 비주얼 옵션.

DS 기초는 안착했어요: `LavaDesignSystem/` 그룹, `LavaSpacing`/반경/`dangerRed` 토큰, `LavaTier` 깊이 의미, `LavaIcon` 역할 레이어가 모두 출시됐어요(lavasec-ios: LavaSecApp/LavaDesignSystem/). 이식성/기초 계획에서 **계획됨**으로 남은 건 `LavaColorRole` 강조 색상 토큰화(Phase 3), 코어 측 영어 문자열을 위한 OS별 표현 맵(Phase 4), 중립적인 크로스 플랫폼 토큰 JSON, 그리고 더 넓은 Android 이식성 이음매예요.
