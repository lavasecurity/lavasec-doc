---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# iOS 클라이언트 아키텍처

> 대상 독자: `lavasec-ios`에서 작업하는 iOS 엔지니어.

Lava Security는 프라이버시를 우선하는 iOS 앱으로, 기기 내 NetworkExtension 패킷 터널을 통해 DNS를 기기에서 직접 필터링합니다. 알려진 위험·불필요한 도메인을 차단하면서도 사용자의 인터넷 이용 내역을 Lava 서버로 우회시키지 않아요. 이 문서는 iOS 클라이언트가 어떻게 구성되어 있는지를 다룹니다. 타깃 구성, 앱이 터널 익스텐션과 통신하는 방식, VPN 라이프사이클, Guardian 상태 모델, Live Activity와 위젯, 온보딩 흐름, 그리고 앱 측 상태 소유자(`AppViewModel`)를 살펴봐요.

전체 시스템의 큰 그림(앱, 카탈로그 Worker, Supabase)은 [시스템 개요](./system-overview.md)를 참고하세요.

---

## 1. 타깃과 책임

클라이언트는 세 개의 실행 가능한 타깃과 하나의 공유 코어 라이브러리로 출시됩니다. 세 타깃 모두 동일한 **App Group**(`group.com.lavasec`)에 속하고 `LavaSecCore`를 링크해요.

| 타깃 | 번들 id | 책임 |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | SwiftUI 앱. UI를 소유하고, NetworkExtension 권한을 보유하며, `NETunnelProviderManager`를 통해 터널을 제어합니다. `AppViewModel`이 VPN 라이프사이클의 단일 진실 소스예요. |
| **패킷 터널** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider` 서브클래스인 `PacketTunnelProvider`(일명 `LavaSecTunnel`). DNS 패킷을 파싱해 질의된 도메인을 추출하고, 메모리 매핑된 컴파일 스냅샷과 대조해 평가한 뒤 허용된 질의를 상위로 전달합니다. 프로세스당 약 50 MiB의 jetsam 메모리 상한에 묶여 있어요. |
| **위젯** (`LavaSecWidget`) | `com.lavasec.app.widget` | 유일한 멤버가 `LavaProtectionLiveActivityWidget`인 `WidgetBundle` — Live Activity / Dynamic Island 표현을 담당합니다. |

공유 코드는 두 곳에 있어요.

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — 플랫폼 독립적인 코어입니다. 필터링 엔진, 리졸버 트랜스포트, 스냅샷/예산 계산, 보호 스토어, 그리고 `GuardianMascotAnimation` 코어가 들어 있어요. `VPNLifecycleController.swift:3-6`에 따르면, 라이프사이클 로직을 페이크로 테스트할 수 있게 유지하기 위해 NetworkExtension 타입은 의도적으로 이 모듈 밖에 두었습니다. 앱 타깃이 `NetworkExtension` 기반 구현체를 제공해요.
- **`Shared/`** — 둘 이상의 타깃으로 컴파일되는 코드입니다(예: `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

패킷 터널 내부 구조(DNS 파싱, 컴파일 스냅샷, 암호화 리졸버 트랜스포트, 필터 규칙 예산)는 [DNS 필터링과 차단 목록](./dns-filtering-and-blocklists.md)에서 깊이 있게 다룹니다. 이 문서는 앱 측 아키텍처와 앱·익스텐션 경계에 초점을 맞춰요.

---

## 2. 앱 ↔ 익스텐션 IPC

앱과 패킷 터널 익스텐션은 별개의 프로세스입니다. 이 둘은 세 가지 메커니즘으로 협력하며, 모두 App Group을 기준으로 동작해요.

### App Group 컨테이너

`group.com.lavasec`은 앱, 터널, 위젯이 동일한 `LavaSecCore` 상태와 설정을 읽고 쓸 수 있게 해주는 공유 컨테이너입니다. `LavaSecAppGroup`(`Shared/AppGroup.swift`)은 모든 공유 키와 파일명을 한곳에 모아두어, 프로세스 간에 문자열 상수가 어긋나는 일이 없도록 해요. 여기에는 다음이 포함됩니다.

- 컴파일 스냅샷 산출물(`filter-snapshot.compact`, `filter-snapshot.json`), 직렬화된 `app-configuration.json`, 터널 상태(`tunnel-health.json`), 진단 정보, 그리고 네트워크 활동 로그.
- 보호 세션과 일시중지 상태를 위한 공유 `UserDefaults` 키. 이 키들은 `LavaSecCore` 스토어를 직접 가리키는 별칭이며(`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — 덕분에 앱, 터널, Live Activity 인텐트가 하나의 키 레이아웃, 하나의 리비전 카운터, 하나의 중복 제거 방식을 공유해요.
- 카탈로그 캐시 디렉터리와 기기 내 디버그 로그 파일.

컨테이너 URL은 `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`로 확인합니다.

### 명령 / 프로바이더 메시지(제어 경로)

앱은 모든 명령에 **`sendProviderMessage`**를 사용해 터널을 구동합니다. `AppViewModel.sendTunnelMessage(_:)`(`AppViewModel.swift:7215`)는 캐시된 매니저에서 활성 `NETunnelProviderSession`을 가져와 `session.sendProviderMessage(...)`를 호출해요. 페이로드는 `LavaSecProviderMessageCodec`(`AppGroup.swift:55-79`)에 의해, 메시지 `kind`와 선택적 `operationID`(종단 간 지연 추적에 사용)를 담은 작은 JSON 봉투로 인코딩됩니다.

인식되는 메시지 종류는 `LavaSecAppGroup`의 상수예요.

| 메시지 상수 | 터널에서의 효과 |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | 컴파일된 필터 스냅샷을 강제로 다시 로드합니다. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | 공유 일시중지 상태만 다시 읽습니다. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | 설정을 다시 로드합니다. *리졸버 식별자* 변경만 눈에 보이는 재연결을 일으켜요. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | 진단/로그 관리. |

터널 측에서는 `PacketTunnelProvider.handleAppMessage(_:completionHandler:)`(`PacketTunnelProvider.swift:729`)가 봉투를 디코딩하고 `kind`에 따라 분기합니다. 특히 `reload-configuration`은 새 설정을 로드해 리졸버가 아닌 필드(진단 토글, 유료 상태)가 적용되도록 하지만, 리졸버 식별자가 실제로 바뀐 경우에만 DNS 런타임을 재설정하고 터널 네트워크 설정을 다시 적용합니다 — 즉, 눈에 보이는 재연결입니다(`PacketTunnelProvider.swift:768-792`). 진단 플래그나 유료 상태 변경은 살아 있는 연결을 끊지 않아요.

앱의 `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` 헬퍼(`AppViewModel.swift:7062`/`7070`)는 이 메시지들을 보내는 얇은 래퍼입니다.

### 앱→터널 제어에 프로바이더 메시지를 쓰는 이유

**`sendProviderMessage`가 유일한 앱→터널 제어 경로이며, 앱→터널 Darwin 신호는 없습니다.** 초기 설계에서는 일시중지 시 `CFNotificationCenter` Darwin 신호를 게시하고 익스텐션 안에서 이를 관찰했지만, NetworkExtension 프로세스에서 안정적으로 동작하지 않아 제거되었어요. 명령 서비스는 더 이상 `CFNotificationCenterPostNotification`을 게시하지 않고, 터널도 더 이상 `CFNotificationCenterAddObserver`를 추가하지 않습니다 — 재도입을 막기 위해 소스 인트로스펙션 테스트가 둘 다 없음을 확인합니다(명령 서비스 게시는 `Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574`, 터널 관찰자는 `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847`). (명령 서비스와 터널에 남아 있는 `import Darwin` 줄은 알림이 아니라 `flock`/소켓 기본 요소를 위한 것입니다.)

반대 방향으로는 Darwin 경로가 *여전히* 존재합니다. 터널은 앱에 상태 변경 알림을 게시해요. `TunnelHealthSignal.DarwinProtectionSignalNotifier`(`Sources/LavaSecCore/TunnelHealthSignal.swift`)가 `com.lavasec.protection.tunnel-health-changed` 채널에 `CFNotificationCenterPostNotification`을 게시하고(채널 이름은 `AppGroup.swift`가 아니라 `TunnelHealthSignal.swift`에 있습니다), 앱은 `DarwinNotificationObserver`(`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`)로 이를 관찰하며, 이는 `AppViewModel`에서 `handleTunnelHealthNudge()`를 호출하도록 연결되어 있어요. 이 터널→앱 상태 알림은 `LavaLiveActivitySourceTests.swift:1059-1075`에서 존재함이 확인됩니다.

앱→터널 제어의 경우, 일시중지는 공유 `ProtectionPauseStore`에 기록한 뒤 `reload-protection-pause` 프로바이더 메시지를 이어 보내 터널이 `refreshProtectionPauseStateOnly`를 실행하도록 전달됩니다. `AppViewModel.swift:4995-4996`은 이 규칙을 직접 문서화합니다. 앱은 "스냅샷 Darwin 관찰자에도 결코 의존하지 않고 항상 `sendProviderMessage`를 사용한다"고요. App Group(공유 상태) + `sendProviderMessage`(깨우기/제어 신호) 쌍을 앱→터널 제어 경로로 보시면 됩니다.

### Live Activity 명령 서비스

`LavaProtectionCommandService.perform(_:)`(`Shared/LavaProtectionCommandService.swift`)는 Dynamic Island / Live Activity 동작(`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`)의 진입점입니다. `LavaLiveActivityIntents.swift`의 `LiveActivityIntent`들은 앱 프로세스(NetworkExtension 권한을 보유한 쪽)에서 실행되므로 다음과 같이 동작해요.

- **일시중지 / 재개**는 프로세스 간 파일 잠금(`protection-command.lock`, `flock`)과 `LavaSecCore`의 `ProtectionPauseStore` / `ProtectionSessionStore`를 거칩니다. 이들이 리비전 발급과 중복 명령 제거를 담당해요(`commandID`가 호출자의 작업 id를 함께 전달하므로, 재전달된 명령이 두 번째 리비전을 발급하지 못합니다). 그 결과로 리비전 가드가 적용된 Live Activity 업데이트가 예약됩니다.
- **재연결**은 직접 처리됩니다(`performReconnect`, `LavaProtectionCommandService.swift:112-135`). `loadAllFromPreferences`를 호출하고 `startVPNTunnel()`로 처음 설치된 터널 매니저를 시작해요(`loadAllFromPreferences`는 이미 이 앱의 NE 설정으로 범위가 한정되어 있으므로, 그 첫 매니저는 Lava의 것입니다 — `VPNLifecycleController.matchingManagers()`와 달리 명시적 식별자 매칭은 하지 않습니다). Connect-On-Demand가 이미 켜져 있어서, 이는 단지 즉시 연결을 강제할 뿐이에요. 이후 앱의 상태 조정이 연결되면 Live Activity를 다시 `.on`으로 되돌립니다.

---

## 3. VPN 라이프사이클과 제어

`AppViewModel`(`@MainActor final class`, `AppViewModel.swift:723`)은 앱에서 VPN 라이프사이클의 단일 진실 소스입니다. 켜기/끄기를 조율하고, 활성 `NETunnelProviderManager`를 캐시하며, 상태를 SwiftUI에 게시해요.

### 매니저 선택과 라이프사이클 계산

재사용 가능하고 NetworkExtension에 의존하지 않는 라이프사이클 로직은 `VPNLifecycleController<Repository>`(`Sources/LavaSecCore/VPNLifecycleController.swift`)에 있습니다. 앱은 `NETunnelProviderManager` 기반의 `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting` 구현체를 제공하고, 컨트롤러는 다음을 처리해요.

- **선택과 중복 제거** — `matchingManagers()`는 `LavaTunnelConfigurationIdentity.matches(...)`로 Lava 소유 매니저만 거르고, `selectionPriority`(활성 항목 우선, 그다음 정식 표시 이름)로 정렬하며, `removeDuplicateManagers(keeping:)`로 단일 생존자로 수렴합니다.
- **연결/중지 대기** — `waitForConnect` / `waitForStop`는 `startGraceInterval` 허용 범위를 두고 실시간 연결 상태를 폴링합니다. `startVPNTunnel` 직후, iOS가 연결을 `.connecting`으로 전환하기 전에 연결이 잠깐 비대기 상태로 읽힐 수 있기 때문이에요.

### 켜기 / 끄기

`enableProtection(...)`(`AppViewModel.swift:5764`)는 **캐시 우선**입니다. 현재 설정에 대해 재사용 가능함이 확인된 준비된 산출물이 있으면, 진행 중인 카탈로그 동기화가 백그라운드에서 계속 갱신되는 동안 VPN이 캐시에서 즉시 올라올 수 있고, 동기화가 끝나면 `performCatalogSync`가 실행 중인 터널을 조정합니다. 시작할 만한 유효한 것이 전혀 없을 때(예: 사용자가 활성 목록 세트를 막 바꿔 캐시된 산출물 식별자가 무효화된 경우)에만 동기화를 기다려요.

`disableProtection(...)`(`AppViewModel.swift:5972`)는 iOS가 터널을 곧바로 재연결하지 못하도록, 터널을 중지하기 *전에* Connect-On-Demand를 끕니다. `setManagerOnDemand(_:on:)`(`AppViewModel.swift:6253`)는 `NEOnDemandRuleConnect`(인터페이스 매치 `.any`)를 설치하고 설정을 저장합니다 — iOS가 변경을 반영하려면 단순히 설정만 하는 게 아니라 저장이 필요해요.

### 상태 관찰(그리고 발열 주의 사항)

`AppViewModel`은 `.NEVPNStatusDidChange`를 관찰하고(`AppViewModel.swift:1034-1056`) `vpnStatus`/`isVPNConfigurationInstalled`를 게시합니다. 중요한 점은, 매니저가 이미 캐시되어 있을 때 `loadAllFromPreferences` 새로고침을 강제하지 않고 캐시된 매니저의 실시간 연결을 읽는다는 거예요. `loadAllFromPreferences` 자체가 `NEVPNStatusDidChange`를 다시 게시하기 때문에, 관찰자에서 강제로 새로고침하면 스스로 끝없이 이어지는 폭주가 생겼습니다 — 소스 내 주석(`AppViewModel.swift:1046-1048`)에 측정된 초당 약 370건의 이벤트와 그로 인한 134% CPU 발열 회귀가 기록되어 있어요. 게시되는 속성은 실제 전환에서만 바뀌므로, 유휴 틱이 SwiftUI를 무효화하는 일을 멈춥니다.

### Fail-closed 온디맨드 조정

Connect-On-Demand는 앱이 아직 스냅샷을 밀어 넣기 전에, 실행 시점(또는 네트워크 변경으로 iOS가 터널을 내린 뒤)에 터널을 **차갑게(cold)** 올릴 수 있습니다. 재사용 가능한 영속 스냅샷이 없는 차가운 터널은 **fail-closed**로 로드되어 — 모든 트래픽을 차단하고 — 스스로 복구되지 않아요. `AppViewModel`은 이를 두 가지 실행 경로에서 처리하며, 둘 다 온보딩 완료를 전제로 합니다(`hasCompletedOnboarding`, `@AppStorage("hasSeenLavaOnboarding")` 플래그를 반영).

- **온보딩 이후** — `reconcileTunnelSnapshotAfterLaunch()`(`AppViewModel.swift:7122`)는 실행 시점에 보호가 활성화되어 있을 때마다 동작합니다. 시작 스냅샷을 준비하고, 공유 상태를 영속화하며, `reload-snapshot`을 보내 터널이 fail-closed에서 벗어나 실제 규칙을 다시 로드하도록 해요. Fail-closed는 안전한 기본값으로 유지되고, 이 과정은 그것을 신속히 대체할 뿐입니다. (Connect-On-Demand가 터널을 켠 채로 둔 상태에서 앱을 재시작한 뒤 필터가 빨갛게 표시되거나 트래픽이 차단되던 문제를 해결합니다.)
- **온보딩 중** — `neutralizeInheritedProtectionDuringOnboarding()`(`AppViewModel.swift:7181`)는 온보딩이 끝나지 않았을 때 어떤 네트워크 작업보다도 *먼저* 동작합니다. iOS는 앱 삭제 시 VPN 프로필을 안정적으로 제거하지 않으므로, 재설치 시 버려진 온디맨드 활성 설정을 물려받아 사용자가 아직 어떤 차단 목록도 고르기 전에 fail-closed 차가운 터널을 올릴 수 있어요. 이 경로는 설정에 대한 수정을 저장하는 대신 설정을 **제거**합니다(`removeFromPreferences`) — `saveToPreferences`는 이 설치가 소유하지 않은 프로필에 대해 "VPN 구성 추가" 시스템 프롬프트를 다시 띄워, 온보딩 시트가 렌더링되기 전 앱 초기화 시점에 대화상자를 발생시킬 수 있기 때문이에요. 깨끗한 새 설치에서는, 그리고 물려받은 설정이 이미 무력화된 경우에는 아무 동작도 하지 않습니다.

---

## 4. Guardian / 상태 모델

서로 관련된 두 가지 상태 어휘가 있습니다. 연결성 *평가*와 Guardian *마스코트* 상태예요.

### 연결성 평가

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)`(`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`)는 `TunnelHealthSnapshot`을 **여섯 가지 심각도**와 **두 가지 동작** 중 하나를 가진 `ProtectionConnectivityAssessment`로 매핑합니다.

- 심각도: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- 기본 동작: `turnOff` 또는 `reconnect`.

이 단일 평가가 앱 내 Guard 화면과 (추가 매핑을 거친) Dynamic Island 상태를 함께 구동하므로, 둘이 서로 어긋나는 일이 없어요.

### Guardian 마스코트 상태

Soft Shield Guardian 마스코트는 정확히 **일곱 가지** 감정 상태를 가집니다 — `GuardianMascotState`(`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. 각 상태는 `allowedNextStates`를 선언해 전환을 제약합니다(예: `grateful`은 `awake`로만 돌아감; `GuardianMascotAnimation.swift:12-29`). 의미는 다음과 같아요.

- `retrying` = 차분한 자가 복구.
- `concerned` = 부드러운 도움 요청.
- `grateful` = 축하하는 성공(온보딩/설정 화면에서 사용하며, 연결성 맵에서는 쓰지 않음).

`GuardianMascotAnimation`은 `LavaSecCore`의 절차적 애니메이션 코어이고, `SoftShieldGuardian`(`Shared/SoftShieldGuardian.swift`)은 SwiftUI 렌더링이며 `GuardianShieldStyle`로 선택되는 커스터마이즈 스킨을 지원합니다(표시 이름 Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, `displayName` 매핑은 18-35행). 일부 원시 값은 표시 이름과 다르므로(예: `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, 그리고 `purpleObsidian`은 "Amethyst"로 렌더링됨), 레이블이 아니라 원시 값을 영속화하세요.

### 두 어휘가 연결되는 방식

Live Activity의 `LavaActivityAttributes.ProtectionState`(`Shared/LavaActivityAttributes.swift`)는 `guardianState`를 통해 평가를 마스코트 상태로 연결합니다: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned`(`LavaActivityAttributes.swift:95-105`). `AppViewModel`은 동일한 `protectionConnectivityAssessment`에서 Dynamic Island의 보호 상태를 고릅니다(`AppViewModel.swift:3131-3147`): `networkUnavailable` 심각도는 `.networkUnavailable`로, `recovering`은 `.reconnecting`으로, `reconnect` 기본 동작은 `.needsReconnect`로, 그 외에는 `.on`이 돼요.

> 참고: `LavaTier`(차분함 → **Floor** / 축하 → **Window** / 기술적 → **Workshop**의 디자인 시스템 깊이 enum)는 디자인 시스템 레이어(`LavaSecApp/LavaDesignSystem/LavaTokens.swift`)에 들어 있으며 대표 화면에 연결되어 있어요 — [디자인 시스템](../design-system/overview.md)을 참고하세요. 이는 디자인 시스템의 깊이를 다스리는 것이지, 여기서 설명한 보호/터널 클라이언트 경로를 다스리지 않습니다.

---

## 5. Live Activity와 위젯

위젯 타깃은 Live Activity와 Dynamic Island만 렌더링합니다. `LavaSecWidgetBundle`(`LavaSecWidget/LavaSecWidget.swift`)은 단일 `LavaProtectionLiveActivityWidget`을 노출하며, 이는 다음을 가진 `ActivityConfiguration(for: LavaActivityAttributes.self)`예요.

- 잠금 화면 뷰, 확장된 Dynamic Island 중앙 영역, 그리고 `SoftShieldGuardian`과 상태 글리프를 렌더링하는 컴팩트/미니멀 표현. 컴팩트/잠금 뷰는 초 단위 `TimelineView`에서 *유효* 보호 상태를 다시 계산하므로, 푸시 없이도 일시중지 카운트다운이 실시간으로 유지됩니다.

`LavaActivityAttributes.ContentState`는 `protectionState`, (일시중지 카운트다운용) `resumeDate`, `pauseRequiresAuthentication`, 그리고 선택된 `shieldStyle`을 담습니다. 디코딩은 관대해서 — `shieldStyle`이 없으면 `.original`로 대체됩니다 — 오래된 Live Activity 페이로드도 계속 동작해요.

앱 측에서는 `LavaLiveActivityController`(`LavaSecApp/LavaLiveActivityController.swift`)가 실시간 `Activity<LavaActivityAttributes>`를 소유합니다. ActivityKit 권한 변경을 관찰하고, phone/pad idiom에서만 Live Activity를 제공하며, `reconcile(...)`이 요청된 보호 상태에 맞게 액티비티를 시작/업데이트/종료해요. `AppViewModel.reconcileLiveActivity()`(`AppViewModel.swift:3069`)는 원하는 상태를 다시 계산하고 컨트롤러를 호출하는 단일 통로입니다. Dynamic Island 버튼은 `LiveActivityIntent`를 디스패치하고, 이는 [§2](#2-app-extension-ipc)에서 설명한 대로 `LavaProtectionCommandService`를 호출합니다.

---

## 6. 온보딩 흐름

온보딩은 `LavaOnboardingView`(`LavaSecApp/OnboardingFlowView.swift`)가 표시하며, `RootView`(`RootView.swift:32`)에 선언된 `@AppStorage("hasSeenLavaOnboarding")` 플래그로 게이팅됩니다. 흐름은 `OnboardingPage`의 연속이에요(`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

출시되는 시작 설정은 `OnboardingDefaults`(`Sources/LavaSecCore/OnboardingDefaults.swift`)에서 옵니다. `AppConfiguration.lavaRecommendedDefaults`는 관대한 권장 소스(Block List Project Phishing + Scam)만 활성화하고, 리졸버로 **기기 DNS**를 선택하며 — `DNSResolverPreset.device`(id `device-dns`), 네트워크 자체의 DNS입니다. Google DoH 같은 암호화 프리셋은 선택 사항이며 기본값으로 권장하지 않아요 — 기기 DNS 폴백을 켜고, 로컬 로깅을 켜둔 채로 둡니다. `protectionEnabled: false`이므로 보호는 사용자가 선택할 때만 켜져요. `OnboardingDefaultsSummary`는 이 선택들을 표시용으로 포맷합니다("Continue without account"가 계정 기본값).

마지막에 `hasSeenLavaOnboarding = true`로 설정하는 것이 `hasCompletedOnboarding`을 뒤집고, 이것이 다시 [§3](#3-vpn-lifecycle-control)에서 설명한 실행 시 조정 경로를 가동합니다. 그 전까지는 온보딩 중 무력화 경로가 물려받은 fail-closed 터널이 트래픽을 차단하지 못하게 막아요.

---

## 7. 앱 상태: `AppViewModel`

`AppViewModel`(`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`)은 앱 측의 중심 상태 소유자입니다. VPN 라이프사이클을 넘어, UI가 바인딩하는 화면들을 게시하며 다음을 포함해요.

- **보호와 터널** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth`(`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, 그리고 사용자에게 보이는 `vpnMessage`/`vpnMessageIsError`.
- **설정과 카탈로그** — `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, 그리고 컴파일된 규칙 수(`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **진단** — `DiagnosticsStore`와 `NetworkActivityLog`(모두 로컬; 아래 프라이버시 약속 참고).
- **계정과 백업** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, 그리고 **Lava Security Plus** 제공/이용권 상태.
- **커스터마이즈와 표현** — `appearancePreference`, `lavaGuardLook`(`GuardianShieldStyle`), `lavaGuardProgress`, 그리고 `usesLiveActivities`.

라이프사이클 직렬화는 `protectionActionOrchestrator`에 위임하고(그래서 백그라운드 복원이 사용자의 켜기와 뒤섞이지 않아요), 캐시된 `tunnelManager`를 보유하며, 모든 스냅샷/설정/일시중지 변경을 [§2](#2-app-extension-ipc)의 프로바이더 메시지 헬퍼를 통해 익스텐션으로 전달합니다.

> **프라이버시 관점.** DNS 필터링은 이 기기에서 로컬로 이루어집니다. `AppViewModel`이 게시하는 진단과 네트워크 활동 화면은 로컬에만 저장되며 — Lava는 사용자의 일상적인 DNS 질의, 인터넷 이용 내역, 도메인별 정보를 결코 받지 않아요. 선택 사항인 계정 백업은 **제로 지식**이며(기기에서 암호화되어, Lava는 오직 암호문만 저장할 수 있음), 패스키 기반 복구도 마찬가지입니다 — 그 키는 기기에서 PRF로 파생되며 서버가 보유하는 비밀이 없어요. 서버 경계는 [시스템 개요](./system-overview.md)를 참고하세요.

---

## 관련 문서

- [시스템 개요](./system-overview.md) — 한 화면에 담은 전체 시스템: 앱, 카탈로그 Worker, Supabase, 그리고 신뢰 경계와 문서 전반에서 쓰이는 상태 범례.
- [DNS 필터링과 차단 목록](./dns-filtering-and-blocklists.md) — 여기서는 제어 경계에서만 언급한 패킷 터널 내부 구조: 컴파일된 필터링 엔진, 암호화 리졸버 트랜스포트(DoH / DoH3 / DoT / DoQ), 필터 규칙 예산, 차단 목록 카탈로그, 그리고 소스 URL만 제공하는 재배포 모델.
- [계정과 제로 지식 백업](./accounts-and-backup.md) — 로그인 제공자와 `AppViewModel`이 조율하는 제로 지식 백업 봉투(제로 지식이자 PRF 파생인 패스키 복구 슬롯 포함).
- [백엔드와 데이터](./backend-and-data.md) — `lavasec-api` 카탈로그 Worker, Cloudflare R2, 그리고 앱↔서버 경계 반대편에 자리한 Supabase 스키마/RLS.
- [디자인 시스템](../design-system/overview.md) — `LavaTier` 깊이 모델, Soft Shield Guardian의 일곱 가지 상태와 방패 스킨, 그리고 클라이언트가 렌더링하는 문구/현지화 규칙.
- [서드파티 고지](../legal/third-party-notices.md)와 [GPL 소스 URL 전용 준수 결정](../legal/gpl-source-url-only-compliance-decision.md) — 클라이언트가 소비하는 카탈로그/필터 파이프라인 뒤에 있는 배포 제약.
