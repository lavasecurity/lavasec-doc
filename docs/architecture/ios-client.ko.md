---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# iOS 클라이언트 아키텍처 {#ios-client-architecture}

> 대상 독자: `lavasec-ios`에서 작업하는 iOS 엔지니어.

Lava Security는 프라이버시를 최우선으로 하는 iOS 앱으로, 기기 안에서 동작하는 NetworkExtension 패킷 터널을 통해 DNS를 로컬에서 필터링해, 사용자의 브라우징을 Lava 서버로 보내지 않고도 알려진 위험하고 원치 않는 도메인을 차단해요. 이 문서는 iOS 클라이언트의 구조를 다뤄요. 타깃, 앱이 자신의 터널 익스텐션과 통신하는 방식, VPN 수명 주기, Guardian 상태 모델, Live Activity와 위젯, 온보딩 흐름, 그리고 앱 측 상태 소유자(`AppViewModel`)를 설명해요.

전체 시스템 그림(앱, 카탈로그 Worker, Supabase)은 [시스템 개요](./system-overview.md)를 참고하세요.

---

## 1. 타깃과 책임 {#1-targets-responsibilities}

클라이언트는 세 개의 실행 가능한 타깃과 하나의 공유 코어 라이브러리로 배포돼요. 세 타깃 모두 동일한 **App Group**(`group.com.lavasec`)에 속하고 `LavaSecCore`를 링크해요.

| 타깃 | 번들 id | 책임 |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | SwiftUI 앱. UI를 소유하고, NetworkExtension 권한(entitlement)을 보유하며, `NETunnelProviderManager`를 통해 터널을 제어해요. `AppViewModel`이 VPN 수명 주기의 단일 진실 공급원이에요. |
| **Packet tunnel** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider` 서브클래스인 `PacketTunnelProvider`(일명 `LavaSecTunnel`). DNS 패킷을 파싱하고, 질의된 도메인을 추출하고, 메모리 매핑된 컴파일 스냅샷과 대조해 평가하며, 허용된 질의를 업스트림으로 전달해요. 프로세스당 약 50 MiB의 jetsam 메모리 한도에 묶여 있어요. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | 유일한 멤버가 `LavaProtectionLiveActivityWidget`인 `WidgetBundle` — Live Activity / Dynamic Island 표현이에요. |

공유 코드는 두 곳에 있어요.

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — 플랫폼에 독립적인 코어로, 필터링 엔진, 리졸버 트랜스포트, 스냅샷/버짓 계산, 보호 스토어, 그리고 `GuardianMascotAnimation` 코어를 포함해요. `VPNLifecycleController.swift:3-6`에 따라 NetworkExtension 타입은 이 모듈의 수명 주기 로직을 페이크로 테스트할 수 있도록 의도적으로 이 모듈 밖에 두고, 앱 타깃이 `NetworkExtension` 기반 적합 구현(conformances)을 제공해요.
- **`Shared/`** — 두 개 이상의 타깃에 컴파일되는 코드(예: `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

패킷 터널 내부(DNS 파싱, 컴파일 스냅샷, 암호화된 리졸버 트랜스포트, 필터 규칙 버짓)는 [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md)에서 깊이 있게 다뤄요. 이 문서는 앱 측 아키텍처와 앱과 익스텐션 사이의 경계에 집중해요.

---

## 2. 앱 ↔ 익스텐션 IPC {#2-app-extension-ipc}

앱과 패킷 터널 익스텐션은 별개의 프로세스예요. 둘은 세 가지 메커니즘을 통해 조율되며, 모두 App Group을 기반으로 해요.

### App Group 컨테이너 {#app-group-container}

`group.com.lavasec`은 앱, 터널, 위젯이 동일한 `LavaSecCore` 상태와 설정을 읽고 쓸 수 있게 해주는 공유 컨테이너예요. `LavaSecAppGroup`(`Shared/AppGroup.swift`)은 모든 공유 키와 파일명을 한곳에 모아, 프로세스들이 문자열 상수에서 절대 어긋나지 않도록 해요. 여기에는 다음이 포함돼요.

- 컴파일 스냅샷 아티팩트(`filter-snapshot.compact`, `filter-snapshot.json`), 직렬화된 `app-configuration.json`, 터널 상태(`tunnel-health.json`), 진단, 그리고 네트워크 활동 로그.
- 보호 세션과 일시 중지 상태를 위한 공유 `UserDefaults` 키. 이들은 `LavaSecCore` 스토어를 직접 별칭으로 가리키므로(`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — 앱, 터널, Live Activity 인텐트가 하나의 키 레이아웃, 하나의 리비전 카운터, 하나의 중복 제거 방식을 공유해요.
- 카탈로그 캐시 디렉터리와 기기 내 디버그 로그 파일.

컨테이너 URL은 `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`를 통해 해석돼요.

### 커맨드 / 프로바이더 메시지 (제어 경로) {#command-provider-message-the-control-path}

앱은 모든 명령에 대해 **`sendProviderMessage`**로 터널을 구동해요. `AppViewModel.sendTunnelMessage(_:)`(`AppViewModel.swift:7215`)는 캐시된 매니저에서 활성 `NETunnelProviderSession`을 가져와 `session.sendProviderMessage(...)`를 호출해요. 페이로드는 `LavaSecProviderMessageCodec`(`AppGroup.swift:55-79`)에 의해 메시지 `kind`와 선택적 `operationID`(엔드 투 엔드 지연 추적에 사용)를 담은 작은 JSON 봉투(envelope)로 인코딩돼요.

인식되는 메시지 종류는 `LavaSecAppGroup`의 상수예요.

| 메시지 상수 | 터널에서의 효과 |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | 컴파일된 필터 스냅샷을 강제로 다시 로드해요. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | 공유 일시 중지 상태만 다시 읽어요. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | 설정을 다시 로드해요. *리졸버 식별자* 변경만 눈에 보이는 재연결을 유발해요. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | 진단/로그 유지 관리. |

터널 측에서는 `PacketTunnelProvider.handleAppMessage(_:completionHandler:)`(`PacketTunnelProvider.swift:729`)가 봉투를 디코딩하고 `kind`에 따라 분기해요. 특히 `reload-configuration`은 새 설정을 로드해 리졸버가 아닌 필드(진단 토글, 유료 상태)가 적용되게 하지만, 리졸버 식별자가 실제로 변경됐을 때만 DNS 런타임을 리셋하고 터널 네트워크 설정을 다시 적용해요 — 즉 눈에 보이는 재연결이에요(`PacketTunnelProvider.swift:768-792`). 진단 플래그나 유료 상태 변경은 절대 활성 연결을 끊지 않아요.

앱의 `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` 헬퍼(`AppViewModel.swift:7062`/`7070`)는 이 메시지들을 보내는 얇은 래퍼예요.

### 앱→터널 제어에 프로바이더 메시지를 쓰는 이유 {#why-provider-messages-for-apptunnel-control}

**`sendProviderMessage`가 유일한 앱→터널 제어 경로예요 — 앱→터널 Darwin 신호는 없어요.** 이전 설계에서는 일시 중지 시 `CFNotificationCenter` Darwin 신호를 게시하고 익스텐션 내부에서 그것을 관찰했지만, NetworkExtension 프로세스에서 안정적으로 발화하지 않아 제거됐어요. 커맨드 서비스는 더 이상 `CFNotificationCenterPostNotification`을 게시하지 않고, 터널도 더 이상 `CFNotificationCenterAddObserver`를 추가하지 않아요 — 재도입을 방지하기 위해 두 가지 모두 소스 인트로스펙션 테스트로 부재가 단언돼요(커맨드 서비스의 게시에 대해서는 `Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574`, 터널 관찰자에 대해서는 `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847`). (커맨드 서비스와 터널에 남아 있는 `import Darwin` 줄은 알림이 아니라 `flock`/소켓 프리미티브를 위한 거예요.)

Darwin 경로는 *반대 방향*으로는 여전히 동작해요. 터널은 앱에 상태 변경 알림(nudge)을 게시해요. `TunnelHealthSignal.DarwinProtectionSignalNotifier`(`Sources/LavaSecCore/TunnelHealthSignal.swift`)가 `com.lavasec.protection.tunnel-health-changed` 채널에 `CFNotificationCenterPostNotification`을 게시하고(채널 이름은 `AppGroup.swift`가 아니라 `TunnelHealthSignal.swift`에 있어요), 앱은 `DarwinNotificationObserver`(`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`)를 통해 그것을 관찰하며, 이는 `AppViewModel`에 연결되어 `handleTunnelHealthNudge()`를 호출해요. 이 터널→앱 상태 알림은 `LavaLiveActivitySourceTests.swift:1059-1075`에 의해 존재함이 단언돼요.

앱→터널 제어에서, 일시 중지는 공유 `ProtectionPauseStore`에 기록하고 이어서 `reload-protection-pause` 프로바이더 메시지를 보내 터널이 `refreshProtectionPauseStateOnly`를 실행하도록 함으로써 전달돼요. `AppViewModel.swift:4995-4996`은 그 규칙을 직접 기록해요. 앱은 "스냅샷 Darwin 관찰자에도 결코 의존하지 않고, 항상 `sendProviderMessage`를 사용해요." App Group(공유 상태)과 `sendProviderMessage`(깨우기/제어 신호) 쌍을 앱→터널 제어 경로로 취급하세요.

### Live Activity 커맨드 서비스 {#live-activity-command-service}

`LavaProtectionCommandService.perform(_:)`(`Shared/LavaProtectionCommandService.swift`)는 Dynamic Island / Live Activity 동작(`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`)의 진입점이에요. `LavaLiveActivityIntents.swift`의 `LiveActivityIntent`들은 앱 프로세스(NetworkExtension 권한을 보유한 쪽)에서 실행되므로 다음과 같아요.

- **일시 중지 / 재개**는 프로세스 간 파일 잠금(`protection-command.lock`, `flock`)과 `LavaSecCore`의 `ProtectionPauseStore` / `ProtectionSessionStore`를 통해 흐르며, 이들이 리비전 발행과 중복 명령 제거를 소유해요(`commandID`가 호출자의 작업 id를 이어 붙여, 재전달된 명령이 두 번째 리비전을 발행하지 못하게 해요). 그 결과는 리비전 보호된 Live Activity 업데이트를 예약해요.
- **재연결**은 직접 처리돼요(`performReconnect`, `LavaProtectionCommandService.swift:112-135`): `loadAllFromPreferences`를 호출하고 `startVPNTunnel()`을 통해 첫 번째로 설치된 터널 매니저를 시작해요(`loadAllFromPreferences`가 이미 이 앱의 NE 설정으로 범위가 한정되어 있어 그 첫 번째 매니저가 Lava의 것이기 때문에 — `VPNLifecycleController.matchingManagers()`와 달리 명시적 식별자 매칭은 하지 않아요). Connect-On-Demand가 이미 활성화되어 있으므로 이는 즉각적인 연결을 강제할 뿐이고, 앱의 상태 조정(reconcile)이 연결되면 Live Activity를 `.on`으로 되돌려요.

---

## 3. VPN 수명 주기와 제어 {#3-vpn-lifecycle-control}

`AppViewModel`(`@MainActor final class`, `AppViewModel.swift:723`)은 앱에서 VPN 수명 주기의 단일 진실 공급원이에요. 켜기/끄기를 조율하고, 활성 `NETunnelProviderManager`를 캐시하며, 상태를 SwiftUI에 게시해요.

### 매니저 선택과 수명 주기 계산 {#manager-selection-and-lifecycle-math}

재사용 가능하고 NetworkExtension에 의존하지 않는 수명 주기 로직은 `VPNLifecycleController<Repository>`(`Sources/LavaSecCore/VPNLifecycleController.swift`)에 있어요. 앱은 `NETunnelProviderManager` 기반의 `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting` 적합 구현을 제공하고, 컨트롤러는 다음을 처리해요.

- **선택과 중복 제거** — `matchingManagers()`는 `LavaTunnelConfigurationIdentity.matches(...)`를 통해 Lava 소유 매니저로 필터링하고, `selectionPriority`(활성 먼저, 그다음 정식 표시 이름)로 정렬하며, `removeDuplicateManagers(keeping:)`가 단일 생존자로 수렴시켜요.
- **연결/중지 대기** — `waitForConnect` / `waitForStop`는 `startGraceInterval` 허용 오차를 두고 활성 연결 상태를 폴링해요. `startVPNTunnel` 직후 iOS가 연결을 `.connecting`으로 전환하기 전에 잠깐 비대기(non-pending) 상태로 읽힐 수 있기 때문이에요.

### 켜기 / 끄기 {#turn-on-turn-off}

`enableProtection(...)`(`AppViewModel.swift:5764`)는 **캐시 우선**이에요. 현재 설정에 대해 재사용이 확인된 준비 아티팩트가 존재하면, 진행 중인 카탈로그 동기화가 백그라운드에서 계속 갱신되는 동안 VPN이 캐시에서 즉시 올라올 수 있고, 완료 시 `performCatalogSync`가 실행 중인 터널을 조정해요. 시작할 만한 유효한 것이 전혀 없을 때만(예: 사용자가 방금 활성화 목록 집합을 변경해 캐시된 아티팩트 식별자가 무효화된 경우) 동기화에서 블로킹해요.

`disableProtection(...)`(`AppViewModel.swift:5972`)는 iOS가 즉시 재연결하지 않도록 터널을 중지하기 *전에* Connect-On-Demand를 꺼요. `setManagerOnDemand(_:on:)`(`AppViewModel.swift:6253`)은 `NEOnDemandRuleConnect`(인터페이스 매치 `.any`)를 설치하고 설정을 저장해요 — iOS가 변경 사항을 반영하려면 단지 설정하는 것이 아니라 저장이 필요해요.

### 상태 관찰 (그리고 발열 주의 사항) {#status-observation-and-a-heat-caveat}

`AppViewModel`은 `.NEVPNStatusDidChange`(`AppViewModel.swift:1034-1056`)를 관찰하고 `vpnStatus`/`isVPNConfigurationInstalled`를 게시해요. 결정적으로, 매니저가 이미 캐시되어 있으면 `loadAllFromPreferences` 갱신을 강제하지 않고 캐시된 매니저의 활성 연결을 읽어요. `loadAllFromPreferences`는 그 자체로 `NEVPNStatusDidChange`를 다시 게시하므로, 관찰자에서 강제 갱신을 하면 자기 지속적인 폭주가 발생했어요 — 소스 내 주석(`AppViewModel.swift:1046-1048`)은 측정된 초당 약 370건의 이벤트와 그것이 유발한 134% CPU 발열 회귀를 기록하고 있어요. 게시되는 프로퍼티는 실제 전환에서만 바뀌므로 유휴 틱이 SwiftUI를 무효화하지 않아요.

### 실패 시 차단(fail-closed) 온디맨드 조정 {#fail-closed-on-demand-reconcile}

Connect-On-Demand는 앱이 스냅샷을 푸시하기 전에 출시 시점(또는 iOS가 네트워크 변경으로 터널을 해체한 후) 터널을 **콜드(cold)** 상태로 올릴 수 있어요. 재사용 가능한 영속 스냅샷이 없는 콜드 터널은 **실패 시 차단**으로 로드돼 — 모든 트래픽을 차단하고 — 스스로 복구하지 못해요. `AppViewModel`은 이를 두 가지 출시 경로에서 처리하며, 둘 다 온보딩 완료를 조건으로 해요(`hasCompletedOnboarding`, `@AppStorage("hasSeenLavaOnboarding")` 플래그를 미러링).

- **온보딩 이후** — `reconcileTunnelSnapshotAfterLaunch()`(`AppViewModel.swift:7122`)는 출시 시점에 보호가 활성 상태일 때마다 실행돼요. 시작 스냅샷을 준비하고, 공유 상태를 영속화하며, `reload-snapshot`을 보내 터널이 실패 시 차단에서 벗어나 실제 규칙을 다시 로드하게 해요. 실패 시 차단은 안전한 기본값으로 유지되고, 이는 단지 그것을 신속히 대체할 뿐이에요. (Connect-On-Demand가 터널을 계속 띄워 놓은 상태에서 앱 재시작 후 필터가 빨갛게 표시되거나 트래픽이 차단되던 문제를 해결해요.)
- **온보딩 도중** — `neutralizeInheritedProtectionDuringOnboarding()`(`AppViewModel.swift:7181`)은 온보딩이 끝나지 않았을 때 어떤 네트워크 작업보다 *먼저* 실행돼요. iOS는 앱 삭제 시 VPN 프로필을 안정적으로 제거하지 않으므로, 재설치 시 사용자가 어떤 차단 목록도 선택하기 전에 실패 시 차단 콜드 터널을 올리는, 온디맨드가 활성화된 고아 설정을 물려받을 수 있어요. 이 경로는 설정에 대한 수정을 저장하는 대신 설정을 **제거**해요(`removeFromPreferences`) — `saveToPreferences`는 이 설치가 소유하지 않은 프로필에 대해 "VPN 구성 추가" 시스템 프롬프트를 다시 표시해, 온보딩 시트가 렌더링되기 전 앱 초기화 시점에 그 대화 상자를 띄우게 돼요. 깨끗한 설치에서는, 그리고 물려받은 설정이 이미 비활성 상태일 때는 아무 동작도 하지 않아요(no-op).

---

## 4. Guardian / 상태 모델 {#4-guardian-state-model}

서로 관련된 두 가지 상태 어휘가 있어요. 연결성 *평가*와 Guardian *마스코트* 상태예요.

### 연결성 평가 {#connectivity-assessment}

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)`(`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`)는 `TunnelHealthSnapshot`을 **여섯 가지 심각도**와 **두 가지 동작** 중 하나를 가진 `ProtectionConnectivityAssessment`로 매핑해요.

- 심각도: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- 기본 동작: `turnOff` 또는 `reconnect`.

이 단일 평가가 앱 내 Guard 화면과 (추가 매핑되어) Dynamic Island 상태를 모두 구동하므로, 둘은 결코 어긋나지 않아요.

**정직성 하한선(v1.0).** 현재 시점의, 가려지지 않은 DNS 스모크 프로브 실패는 결코 `.healthy`로 읽힐 수 없어요 — 평가는 프로브가 실제로 성공할 때까지 `.recovering`을 표시하므로, 막힌(wedged) 기본 경로 위에서 폴백으로 운반되는 트래픽이 더 이상 "보호됨"으로 그려지지 않아요. 재연결 로직은 일반 업스트림 카운터가 아니라 `consecutiveDNSSmokeProbeFailureCount`와 `lastPrimaryUpstreamSuccessAt`(기본 경로 전용)에 키를 맞추고, 도달은 가능하지만 알려진 정상 프로브를 계속 **거부**하는 리졸버(하이재킹/캡티브/오래됨)는 일반 연속 카운터가 변동이 잦은 로밍 네트워크에서 계속 리셋되더라도, 리졸버 식별자 범위의 `consecutiveRejectedSmokeResponseCount`(LAV-87)를 통해 재시작이 필요한 수준으로 격상돼요.

### 연결성 알림 {#connectivity-notifications}

`ProtectionConnectivityNotificationPolicy`(`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`)는 평가를 최대 하나의 미해결 로컬 알림으로 바꾸며, 스로틀(600초)되고 중복이 제거돼요. v1.0에서 추가된 점은 다음과 같아요.

- 별도의 **`dnsSlow`** 종류("Lava DNS가 느려요") — 예전에는 느린 DNS가 `reconnectNeeded` 종류를 재사용했기 때문에 실제 장애가 그것을 대체할 수 없었어요.
- **격상/대체** — 엄밀히 더 긴급한 문제(`reconnectNeeded`만이 나머지보다 우위)는 "문제가 이미 미해결" 가드와 스로틀을 모두 우회해, 현재 표시된 낮은 순위의 배너를 대체할 수 있어요. 그래서 Device-DNS 폴백 이후의 막힘 상태가 안심시키는 배너를 띄워 두는 대신 실행 가능한 "재연결" 안내를 표시해요.
- **영속성 마이그레이션**(`ProtectionConnectivityNotificationStore`, 스키마 v2, `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`를 통해 연결)은 레거시의 미해결 `reconnect-needed` 마커를 `dnsSlow`로 강등해, 업그레이드 전반에 걸쳐 격상이 동작하게 해요.

### Device-DNS 캡처 재시도 {#device-dns-capture-retry}

활성 설정이 기기 리졸버에 (기본 또는 폴백으로) 의존할 때, 네트워크 핸드오프/깨우기로 인해 터널이 빈 시스템 리졸버 캡처를 들고 있게 될 수 있어요 — 조용한 막힘이에요. `DeviceDNSFallbackPolicy`는 **제한된 재시도**(`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1초, `deviceDNSCaptureMaxRetryAttempts` 5)를 구동해요. 터널은 캡처가 비어 있지 않을 때까지 최대 다섯 번, 매초 시스템 리졸버를 다시 읽고, 그 자리에서 그것을 채택해요 — 터널 재시작 없이 자동 복구돼요(이벤트 `device-dns-capture-retry` / `-exhausted`). 순수 DoH/DoT/DoQ 설정에서는 아무 동작도 하지 않아요(`currentConfigurationDependsOnDeviceDNS()`).

### Guardian 마스코트 상태 {#guardian-mascot-states}

Soft Shield Guardian 마스코트는 정확히 **일곱 가지** 감정 상태를 가져요 — `GuardianMascotState`(`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. 각 상태는 자신의 `allowedNextStates`를 선언해 전환이 제약돼요(예: `grateful`은 `awake`로만 돌아가요; `GuardianMascotAnimation.swift:12-29`). 의미는 다음과 같아요.

- `retrying` = 차분한 자가 복구.
- `concerned` = 부드러운 도움 요청.
- `grateful` = 축하하는 성공(온보딩/설정 화면에서 사용되며, 연결성 맵에서는 쓰이지 않아요).

`GuardianMascotAnimation`은 `LavaSecCore`의 프로시저럴 애니메이션 코어예요. `SoftShieldGuardian`(`Shared/SoftShieldGuardian.swift`)은 SwiftUI 렌더링이며 `GuardianShieldStyle`로 선택되는 커스터마이징 스킨(표시 이름 Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, `displayName` 매핑은 18-35행)을 지원해요. 몇몇 원시 값은 표시 이름과 다르므로(예: `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, 그리고 `purpleObsidian`은 "Amethyst"로 렌더링), 레이블이 아니라 원시 값을 영속화하세요.

### 둘이 연결되는 방식 {#how-the-two-connect}

Live Activity의 `LavaActivityAttributes.ProtectionState`(`Shared/LavaActivityAttributes.swift`)는 `guardianState`를 통해 평가를 마스코트 상태로 이어 줘요: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned`(`LavaActivityAttributes.swift:95-105`). `AppViewModel`은 동일한 `protectionConnectivityAssessment`로부터 Dynamic Island의 보호 상태를 선택해요(`AppViewModel.swift:3131-3147`): `networkUnavailable` 심각도는 `.networkUnavailable`이 되고, `recovering`은 `.reconnecting`이 되며, `reconnect` 기본 동작은 `.needsReconnect`가 되고, 그 외에는 `.on`이 돼요.

> 참고: `LavaTier`(차분함 → **Floor** / 축하 → **Window** / 기술적 → **Workshop**의 디자인 시스템 깊이 enum)는 디자인 시스템 레이어(`LavaSecApp/LavaDesignSystem/LavaTokens.swift`)에서 배포되며 대표적인 화면들에 연결돼요 — [디자인 시스템](../design-system/overview.md)을 참고하세요. 이것은 디자인 시스템의 깊이를 다스리는 것이지, 여기서 설명하는 보호/터널 클라이언트 경로를 다스리는 것은 아니에요.

---

## 5. Live Activity와 위젯 {#5-live-activity-widget}

위젯 타깃은 Live Activity와 Dynamic Island만 렌더링해요. `LavaSecWidgetBundle`(`LavaSecWidget/LavaSecWidget.swift`)은 단일 `LavaProtectionLiveActivityWidget`을 노출하는데, 이는 다음을 가진 `ActivityConfiguration(for: LavaActivityAttributes.self)`예요.

- 잠금 화면 뷰, 확장된 Dynamic Island 중앙 영역, 그리고 `SoftShieldGuardian`과 상태 글리프를 렌더링하는 compact/minimal 표현. compact/잠금 뷰는 초당 `TimelineView`에서 *유효한* 보호 상태를 다시 계산하므로 일시 중지 카운트다운이 푸시 없이도 실시간으로 유지돼요.

`LavaActivityAttributes.ContentState`는 `protectionState`, `resumeDate`(일시 중지 카운트다운용), `pauseRequiresAuthentication`, 그리고 선택된 `shieldStyle`을 운반해요. 디코딩은 관대해서 — `shieldStyle`이 없으면 `.original`로 폴백돼요 — 더 오래된 Live Activity 페이로드도 계속 동작해요.

앱 측에서는 `LavaLiveActivityController`(`LavaSecApp/LavaLiveActivityController.swift`)가 활성 `Activity<LavaActivityAttributes>`를 소유해요. ActivityKit 권한 변경을 관찰하고, phone/pad 관용구에서만 Live Activity를 제공하며, `reconcile(...)`이 요청된 보호 상태에 맞게 액티비티를 시작/업데이트/종료해요. `AppViewModel.reconcileLiveActivity()`(`AppViewModel.swift:3069`)는 원하는 상태를 다시 계산하고 컨트롤러를 호출하는 단일 깔때기예요. Dynamic Island 버튼은 `LiveActivityIntent`를 디스패치하고, 이는 [§2](#2-app-extension-ipc)에서 설명한 대로 `LavaProtectionCommandService`를 호출해요.

---

## 6. 온보딩 흐름 {#6-onboarding-flow}

온보딩은 `LavaOnboardingView`(`LavaSecApp/OnboardingFlowView.swift`)에 의해 표시되고, `RootView`(`RootView.swift:32`)에 선언된 `@AppStorage("hasSeenLavaOnboarding")` 플래그로 게이트돼요. 이 흐름은 `OnboardingPage`들의 시퀀스예요(`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

배포되는 시작 설정은 `OnboardingDefaults`(`Sources/LavaSecCore/OnboardingDefaults.swift`)에서 와요. `AppConfiguration.lavaRecommendedDefaults`는 관대한 권장 소스(Block List Project Phishing + Scam)만 활성화하고, 리졸버로 **Device DNS**를 선택하며 — `DNSResolverPreset.device`(id `device-dns`), 즉 네트워크 자체의 DNS예요. Google DoH 같은 암호화 프리셋은 옵트인이며 기본값으로 승격되지 않아요 — device-DNS 폴백을 활성화하고, 로컬 로깅을 켜진 채로 유지해요 — `protectionEnabled: false`로 두어, 사용자가 선택할 때만 보호가 켜져요. `OnboardingDefaultsSummary`는 그 선택들을 표시용으로 형식화해요("계정 없이 계속하기"가 계정 기본값이에요).

마지막에 `hasSeenLavaOnboarding = true`로 설정하는 것이 `hasCompletedOnboarding`를 뒤집고, 이는 다시 [§3](#3-vpn-lifecycle-control)에서 설명한 출시 조정 경로를 가동해요. 그전까지는 온보딩 도중 무력화 경로가 물려받은 어떤 실패 시 차단 터널도 트래픽을 차단하지 못하게 막아요.

---

## 7. 앱 상태: `AppViewModel` {#7-app-state-appviewmodel}

`AppViewModel`(`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`)은 앱 측의 중앙 상태 소유자예요. VPN 수명 주기 외에도 UI가 바인딩하는 화면들을 게시하며, 여기에는 다음이 포함돼요.

- **보호 및 터널** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth`(`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, 그리고 사용자 대상 `vpnMessage`/`vpnMessageIsError`.
- **설정 및 카탈로그** — `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, 그리고 컴파일된 규칙 수(`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **진단** — `DiagnosticsStore`와 `NetworkActivityLog`(모두 로컬; 아래 프라이버시 약속 참고).
- **계정 및 백업** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, 그리고 **Lava Security Plus** 제안/권한 상태.
- **커스터마이징 및 표현** — `appearancePreference`, `lavaGuardLook`(`GuardianShieldStyle`), `lavaGuardProgress`, 그리고 `usesLiveActivities`.

수명 주기 직렬화는 `protectionActionOrchestrator`에 위임하고(백그라운드 복원이 사용자 켜기와 섞이지 않도록), 캐시된 `tunnelManager`를 보유하며, 모든 스냅샷/설정/일시 중지 변경을 [§2](#2-app-extension-ipc)의 프로바이더 메시지 헬퍼를 통해 익스텐션으로 구동해요.

> **프라이버시 관점.** DNS 필터링은 이 기기에서 로컬로 일어나요. `AppViewModel`이 게시하는 진단과 네트워크 활동 화면은 로컬에만 저장돼요 — Lava는 사용자의 일상적인 DNS 질의, 브라우징 기록, 도메인별 텔레메트리를 절대 받지 않아요. 선택적인 계정 백업은 **제로 지식(zero-knowledge)**이며(기기에서 암호화되고, Lava는 오직 암호문만 저장할 수 있어요), 패스키 기반 복구도 마찬가지예요 — 그 키는 기기에서 PRF로 파생되며 서버가 보유하는 비밀이 없어요. 서버 경계에 대해서는 [시스템 개요](./system-overview.md)를 참고하세요.

---

## 관련 문서 {#related-docs}

- [시스템 개요](./system-overview.md) — 한 화면에 담은 전체 시스템: 앱, 카탈로그 Worker, Supabase, 그리고 전반에 사용되는 신뢰 경계와 상태 범례.
- [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md) — 여기서는 제어 경계에서만 참조한 패킷 터널 내부: 컴파일된 필터링 엔진, 암호화된 리졸버 트랜스포트(DoH / DoH3 / DoT / DoQ), 필터 규칙 버짓, 차단 목록 카탈로그, 그리고 소스 URL 전용 재배포 모델.
- [계정 및 제로 지식 백업](./accounts-and-backup.md) — `AppViewModel`이 조율하는 로그인 제공자와 제로 지식 백업 봉투(제로 지식, PRF 파생 패스키 복구 슬롯 포함).
- [백엔드 및 데이터](./backend-and-data.md) — `lavasec-api` 카탈로그 Worker, Cloudflare R2, 그리고 앱↔서버 경계의 반대편에 있는 Supabase 스키마/RLS.
- [디자인 시스템](../design-system/overview.md) — `LavaTier` 깊이 모델, Soft Shield Guardian의 일곱 가지 상태와 실드 스킨, 그리고 클라이언트가 렌더링하는 카피/현지화 규칙.
- [서드파티 고지](../legal/third-party-notices.md)와 [GPL 소스 URL 전용 컴플라이언스 결정](../legal/gpl-source-url-only-compliance-decision.md) — 클라이언트가 소비하는 카탈로그/필터 파이프라인 뒤에 있는 배포 제약.
