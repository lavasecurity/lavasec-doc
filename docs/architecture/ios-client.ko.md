---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# iOS 클라이언트 아키텍처

> 대상 독자: `lavasec-ios`에서 작업하는 iOS 엔지니어.

Lava Security는 프라이버시를 최우선으로 하는 iOS 앱으로, 기기 내 NetworkExtension 패킷 터널을 통해 DNS를 로컬에서 필터링하며, 사용자의 브라우징을 Lava의 서버로 라우팅하지 않고도 알려진 위험하거나 원치 않는 도메인을 차단합니다. 이 문서는 iOS 클라이언트의 구조를 다룹니다. 타깃, 앱이 터널 익스텐션과 통신하는 방식, VPN 라이프사이클, Guardian 상태 모델, Live Activity 및 위젯, 온보딩 플로우, 그리고 앱 측 상태 소유자(`AppViewModel`)를 설명합니다.

전체 시스템 그림(앱, 카탈로그 Worker, Supabase)은 [시스템 개요](./system-overview.md)를 참고하세요.

---

## 1. 타깃 및 책임

클라이언트는 세 개의 실행 가능한 타깃과 하나의 공유 코어 라이브러리로 배포됩니다. 세 타깃 모두 동일한 **App Group**(`group.com.lavasec`)에 속하며 `LavaSecCore`를 링크합니다.

| 타깃 | Bundle id | 책임 |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | SwiftUI 앱. UI를 소유하고, NetworkExtension 엔타이틀먼트를 보유하며, `NETunnelProviderManager`를 통해 터널을 제어합니다. `AppViewModel`이 VPN 라이프사이클의 단일 진실 공급원입니다. |
| **Packet tunnel** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider` 서브클래스인 `PacketTunnelProvider`(별칭 `LavaSecTunnel`). DNS 패킷을 파싱하고, 질의된 도메인을 추출하며, 메모리 매핑된 컴파일 스냅샷에 대해 평가하고, 허용된 질의를 업스트림으로 전달합니다. 프로세스당 약 50 MiB의 jetsam 메모리 상한에 제약을 받습니다. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | 유일한 멤버가 `LavaProtectionLiveActivityWidget`인 `WidgetBundle` — Live Activity / Dynamic Island 표현입니다. |

공유 코드는 두 곳에 위치합니다.

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — 플랫폼 독립적인 코어: 필터링 엔진, 리졸버 트랜스포트, 스냅샷/예산 계산, 보호 스토어, 그리고 `GuardianMascotAnimation` 코어. `VPNLifecycleController.swift:3-6`에 따르면, NetworkExtension 타입은 의도적으로 이 모듈 밖에 두어 라이프사이클 로직을 페이크로 테스트할 수 있도록 유지하며, 앱 타깃이 `NetworkExtension` 기반 준수 구현을 제공합니다.
- **`Shared/`** — 둘 이상의 타깃으로 컴파일되는 코드(예: `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

패킷 터널 내부(DNS 파싱, 컴파일 스냅샷, 암호화된 리졸버 트랜스포트, 필터 규칙 예산)는 [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md)에서 심층적으로 다룹니다. 이 문서는 앱 측 아키텍처와 앱과 익스텐션 사이의 경계에 초점을 맞춥니다.

---

## 2. App ↔ 익스텐션 IPC

앱과 패킷 터널 익스텐션은 별개의 프로세스입니다. 둘은 세 가지 메커니즘을 통해 조정하며, 모두 App Group에 기반합니다.

### App Group 컨테이너

`group.com.lavasec`은 앱, 터널, 위젯이 동일한 `LavaSecCore` 상태와 설정을 읽고 쓸 수 있게 해 주는 공유 컨테이너입니다. `LavaSecAppGroup`(`Shared/AppGroup.swift`)은 모든 공유 키와 파일명을 중앙화하여 프로세스들이 문자열 상수에서 절대 어긋나지 않도록 합니다. 여기에는 다음이 포함됩니다.

- 컴파일 스냅샷 아티팩트(`filter-snapshot.compact`, `filter-snapshot.json`), 직렬화된 `app-configuration.json`, 터널 헬스(`tunnel-health.json`), 진단, 그리고 네트워크 활동 로그.
- 보호 세션 및 일시중지 상태에 대한 공유 `UserDefaults` 키. 이들은 `LavaSecCore` 스토어를 직접 별칭 처리하므로(`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — 앱, 터널, Live Activity 인텐트가 하나의 키 레이아웃, 하나의 리비전 카운터, 하나의 중복 제거 체계를 공유합니다.
- 카탈로그 캐시 디렉터리 및 기기 내 디버그 로그 파일.

컨테이너 URL은 `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`를 통해 해석됩니다.

### 명령 / 프로바이더 메시지(제어 경로)

앱은 모든 명령에 대해 **`sendProviderMessage`**로 터널을 구동합니다. `AppViewModel.sendTunnelMessage(_:)`(`AppViewModel.swift:7215`)는 캐시된 매니저로부터 활성 `NETunnelProviderSession`을 가져와 `session.sendProviderMessage(...)`를 호출합니다. 페이로드는 `LavaSecProviderMessageCodec`(`AppGroup.swift:55-79`)에 의해 메시지 `kind`와 선택적 `operationID`(엔드투엔드 지연 추적에 사용)를 담은 작은 JSON 봉투로 인코딩됩니다.

인식되는 메시지 종류는 `LavaSecAppGroup`의 상수입니다.

| 메시지 상수 | 터널에서의 효과 |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | 컴파일된 필터 스냅샷을 강제로 다시 로드합니다. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | 공유 일시중지 상태만 다시 읽습니다. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | 설정을 다시 로드합니다. *리졸버 식별자* 변경만이 눈에 보이는 재연결을 유발합니다. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | 진단/로그 유지 관리. |

터널 측에서 `PacketTunnelProvider.handleAppMessage(_:completionHandler:)`(`PacketTunnelProvider.swift:729`)는 봉투를 디코딩하고 `kind`에 따라 분기합니다. 특히 `reload-configuration`은 새 설정을 로드하여 리졸버가 아닌 필드(진단 토글, 유료 상태)가 적용되도록 하지만, 리졸버 식별자가 실제로 변경된 경우에만 DNS 런타임을 리셋하고 터널 네트워크 설정을 다시 적용합니다 — 눈에 보이는 재연결(`PacketTunnelProvider.swift:768-792`). 진단 플래그나 유료 상태 변경은 라이브 연결을 절대 끊지 않습니다.

앱의 `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` 헬퍼(`AppViewModel.swift:7062`/`7070`)는 이 메시지를 보내는 얇은 래퍼입니다.

### 앱→터널 제어에 프로바이더 메시지를 쓰는 이유

**`sendProviderMessage`는 유일한 앱→터널 제어 경로입니다 — 앱→터널 Darwin 신호는 없습니다.** 초기 설계에서는 일시중지 시 `CFNotificationCenter` Darwin 신호를 게시하고 익스텐션 내부에서 관찰했지만, NetworkExtension 프로세스에서 안정적으로 발화하지 않아 제거되었습니다. 명령 서비스는 더 이상 `CFNotificationCenterPostNotification`을 게시하지 않으며, 터널도 더 이상 `CFNotificationCenterAddObserver`를 추가하지 않습니다 — 둘 다 재도입을 방지하기 위해 소스 인트로스펙션 테스트(`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574`는 명령 서비스 게시에 대해, `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847`은 터널 옵저버에 대해)로 부재가 단언됩니다. (명령 서비스와 터널에 남아 있는 `import Darwin` 라인은 알림이 아니라 `flock`/소켓 프리미티브를 위한 것입니다.)

다른 방향으로는 Darwin 경로가 *여전히* 배포됩니다. 터널은 헬스 변경 너지를 앱에 게시합니다. `TunnelHealthSignal.DarwinProtectionSignalNotifier`(`Sources/LavaSecCore/TunnelHealthSignal.swift`)는 `com.lavasec.protection.tunnel-health-changed` 채널(채널 이름은 `AppGroup.swift`가 아니라 `TunnelHealthSignal.swift`에 있음)에 `CFNotificationCenterPostNotification`을 게시하고, 앱은 `DarwinNotificationObserver`(`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`)를 통해 이를 관찰하며, `AppViewModel`에서 `handleTunnelHealthNudge()`를 호출하도록 연결됩니다. 이 터널→앱 헬스 너지는 `LavaLiveActivitySourceTests.swift:1059-1075`에 의해 존재가 *단언*됩니다.

앱→터널 제어에서, 일시중지는 공유 `ProtectionPauseStore`에 쓰고 이어서 `reload-protection-pause` 프로바이더 메시지를 보내 터널이 `refreshProtectionPauseStateOnly`를 실행하도록 함으로써 전달됩니다. `AppViewModel.swift:4995-4996`은 이 규칙을 직접 문서화합니다. 앱은 "스냅샷 Darwin 옵저버에도 절대 의존하지 않고, 항상 `sendProviderMessage`를 사용한다." App Group(공유 상태) + `sendProviderMessage`(웨이크/제어 신호) 쌍을 앱→터널 제어 경로로 간주하세요.

### Live Activity 명령 서비스

`LavaProtectionCommandService.perform(_:)`(`Shared/LavaProtectionCommandService.swift`)은 Dynamic Island / Live Activity 액션(`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes` / `pause-configured`(Live Activity의 단일 일시중지 버튼으로, 길이는 사용자가 설정한 값), `resume`, `reconnect`)의 진입점입니다. `LavaLiveActivityIntents.swift`의 `LiveActivityIntent`들은 앱 프로세스(NetworkExtension 엔타이틀먼트를 보유)에서 실행되므로:

- **일시중지 / 재개**는 크로스 프로세스 파일 락(`protection-command.lock`, `flock`)과 `LavaSecCore`의 `ProtectionPauseStore` / `ProtectionSessionStore`를 거쳐 흐르며, 이들이 리비전 발행과 중복 명령 제거를 소유합니다(`commandID`는 호출자의 오퍼레이션 id를 스레딩하므로 재전달된 명령이 두 번째 리비전을 발행할 수 없습니다). 결과는 리비전 가드가 적용된 Live Activity 업데이트를 스케줄링합니다.
- **재연결**은 직접 처리됩니다(`performReconnect`, `LavaProtectionCommandService.swift:112-135`). `loadAllFromPreferences`를 호출하고 `startVPNTunnel()`을 통해 첫 번째로 설치된 터널 매니저를 시작합니다(`loadAllFromPreferences`가 이미 이 앱의 NE 설정으로 범위가 한정되어 있으므로, 그 첫 번째 매니저가 Lava의 것입니다 — `VPNLifecycleController.matchingManagers()`와 달리 명시적 식별자 매칭을 하지 않습니다). Connect-On-Demand가 이미 활성화되어 있으므로 이는 즉각적인 연결을 강제할 뿐이며, 이후 앱의 상태 재조정이 연결되면 Live Activity를 `.on`으로 되돌립니다.

---

## 3. VPN 라이프사이클 및 제어

`AppViewModel`(`@MainActor final class`, `AppViewModel.swift:723`)은 앱에서 VPN 라이프사이클의 단일 진실 공급원입니다. 켜기/끄기를 오케스트레이션하고, 활성 `NETunnelProviderManager`를 캐시하며, 상태를 SwiftUI로 게시합니다.

### 매니저 선택 및 라이프사이클 계산

재사용 가능하고 NetworkExtension에 의존하지 않는 라이프사이클 로직은 `VPNLifecycleController<Repository>`(`Sources/LavaSecCore/VPNLifecycleController.swift`)에 있습니다. 앱은 `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`의 `NETunnelProviderManager` 기반 준수 구현을 제공하며, 컨트롤러는 다음을 처리합니다.

- **선택 및 중복 제거** — `matchingManagers()`는 `LavaTunnelConfigurationIdentity.matches(...)`를 통해 Lava 소유 매니저로 필터링하고, `selectionPriority`(활성 우선, 그다음 정규 표시 이름)로 정렬하며, `removeDuplicateManagers(keeping:)`이 단일 생존자로 수렴합니다.
- **연결/중지 대기** — `waitForConnect` / `waitForStop`은 `startGraceInterval` 허용치를 두고 라이브 연결 상태를 폴링합니다. `startVPNTunnel` 직후에는 iOS가 `.connecting`으로 전환하기 전에 연결이 잠시 non-pending 상태로 읽힐 수 있기 때문입니다.

### 켜기 / 끄기

`enableProtection(...)`(`AppViewModel.swift:5764`)는 **캐시 우선**입니다. 현재 설정에 대해 재사용이 확인된 준비된 아티팩트가 존재하면, 진행 중인 카탈로그 동기화가 백그라운드에서 계속 새로 고치는 동안 VPN이 캐시에서 즉시 켜질 수 있으며, `performCatalogSync`는 완료 시 실행 중인 터널을 재조정합니다. 시작할 유효한 것이 전혀 없을 때(예: 사용자가 방금 활성화 목록 집합을 변경하여 캐시된 아티팩트 식별자가 무효화된 경우)에만 동기화에서 블록됩니다.

`disableProtection(...)`(`AppViewModel.swift:5972`)는 터널을 중지하기 *전에* Connect-On-Demand를 꺼서 iOS가 즉시 재연결하지 않도록 합니다. `setManagerOnDemand(_:on:)`(`AppViewModel.swift:6253`)는 `NEOnDemandRuleConnect`(인터페이스 매치 `.any`)를 설치하고 설정을 저장합니다 — iOS가 변경을 적용하려면 설정만 하는 것이 아니라 저장이 필요합니다.

### 상태 관찰(그리고 발열 주의점)

`AppViewModel`은 `.NEVPNStatusDidChange`(`AppViewModel.swift:1034-1056`)를 관찰하고 `vpnStatus`/`isVPNConfigurationInstalled`를 게시합니다. 결정적으로, 매니저가 이미 캐시되어 있을 때는 `loadAllFromPreferences` 새로 고침을 강제하는 대신 캐시된 매니저의 라이브 연결을 읽습니다. `loadAllFromPreferences` 자체가 `NEVPNStatusDidChange`를 다시 게시하므로, 옵저버에서의 강제 새로 고침은 자가 지속되는 폭주를 일으켰습니다 — 소스 내 주석(`AppViewModel.swift:1046-1048`)은 측정된 초당 약 370 이벤트와 그것이 야기한 134% CPU 발열 회귀를 기록합니다. 게시 프로퍼티는 실제 전환에서만 변경되므로 유휴 틱이 더 이상 SwiftUI를 무효화하지 않습니다.

### Fail-closed on-demand 재조정

Connect-On-Demand는 앱이 스냅샷을 푸시하기 전에 시작 시(또는 iOS가 네트워크 변경에서 터널을 해제한 후) 터널을 **콜드**로 올릴 수 있습니다. 재사용 가능한 영속 스냅샷이 없는 콜드 터널은 **fail-closed**로 로드되어 — 모든 트래픽을 차단하며 — 스스로 회복하지 못합니다. `AppViewModel`은 이를 두 개의 시작 경로에서 처리하며, 둘 다 온보딩 완료(`hasCompletedOnboarding`, `@AppStorage("hasSeenLavaOnboarding")` 플래그를 미러링)를 조건으로 합니다.

- **온보딩 이후** — `reconcileTunnelSnapshotAfterLaunch()`(`AppViewModel.swift:7122`)는 시작 시 보호가 활성 상태일 때마다 실행됩니다. 시작 스냅샷을 준비하고, 공유 상태를 영속화하며, `reload-snapshot`을 보내 터널이 fail-closed에서 벗어나 실제 규칙을 다시 로드하도록 합니다. fail-closed는 안전한 기본값으로 유지되며, 이는 그것을 신속하게 대체할 뿐입니다. (Connect-On-Demand가 터널을 계속 올려 두는 동안 앱 재시작 후 필터가 빨간색으로 표시되거나 트래픽이 차단되는 문제를 해결합니다.)
- **온보딩 도중** — `neutralizeInheritedProtectionDuringOnboarding()`(`AppViewModel.swift:7181`)는 온보딩이 끝나지 않은 경우 어떤 네트워크 작업보다도 *먼저* 실행됩니다. iOS는 앱 삭제 시 VPN 프로파일을 안정적으로 제거하지 않으므로, 재설치 시 사용자가 어떤 차단 목록도 선택하기 전에 fail-closed 콜드 터널을 올리는, 고아가 되고 on-demand가 활성화된 설정을 상속받을 수 있습니다. 이 경로는 수정 사항을 저장하는 대신 설정을 **제거**합니다(`removeFromPreferences`) — `saveToPreferences`는 이 설치가 소유하지 않은 프로파일에 대해 "Add VPN Configurations" 시스템 프롬프트를 다시 표시하여, 온보딩 시트가 렌더링되기 전 앱 초기화 시점에 다이얼로그를 띄우게 됩니다. 클린 설치 시, 그리고 상속된 설정이 이미 비활성일 때는 no-op입니다.

---

## 4. Guardian / 상태 모델

관련된 두 가지 상태 어휘가 있습니다. 연결성 *평가*와 Guardian *마스코트* 상태입니다.

### 연결성 평가

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)`(`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`)는 `TunnelHealthSnapshot`을 **여섯 가지 심각도**와 **두 가지 액션** 중 하나를 갖는 `ProtectionConnectivityAssessment`로 매핑합니다.

- 심각도: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- 기본 액션: `turnOff` 또는 `reconnect`.

이 단일 평가가 인앱 Guard 표면과 (추가 매핑되어) Dynamic Island 상태를 모두 구동하므로, 둘은 결코 불일치하지 않습니다.

**정직성 하한선(v1.0).** 현재의, 커버되지 않은 DNS 스모크 프로브 실패는 절대 `.healthy`로 읽힐 수 없습니다 — 평가는 프로브가 실제로 성공할 때까지 `.recovering`을 표면화하므로, 막힌 primary 위로 fallback이 운반한 트래픽이 더 이상 "보호됨"으로 칠해지지 않습니다. 재연결 로직은 일반 업스트림 카운터가 아니라 `consecutiveDNSSmokeProbeFailureCount`와 `lastPrimaryUpstreamSuccessAt`(primary 전용)를 키로 삼으며, 도달 가능한 상태를 유지하면서도 알려진 정상 프로브를 계속 **거부**하는 리졸버(하이재킹/캡티브/오래됨)는 일반 연속 실패 횟수가 변동이 잦은 로밍 네트워크에서 계속 리셋되더라도, 리졸버 식별자 범위의 `consecutiveRejectedSmokeResponseCount`(LAV-87)를 통해 재시작이 필요한 수준으로 에스컬레이션됩니다.

### 연결성 알림

`ProtectionConnectivityNotificationPolicy`(`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`)는 평가를 최대 하나의 미해결 로컬 알림으로 변환하며, 스로틀링(600초)과 중복 제거를 적용합니다. v1.0은 다음을 추가합니다.

- 별개의 **`dnsSlow`** 종류("Lava DNS가 느립니다") — 느린 DNS는 예전에 `reconnectNeeded` 종류를 재사용했기 때문에, 실제 장애가 그것을 대체할 수 없었습니다.
- **에스컬레이션/대체** — 엄격하게 더 긴급한 문제(오직 `reconnectNeeded`만이 나머지를 능가)는 "문제가 이미 미해결" 가드와 스로틀을 모두 우회하여 현재 떠 있는 더 낮은 순위의 배너를 대체할 수 있으므로, Device-DNS fallback 이후의 막힘이 안심시키는 배너를 그대로 두는 대신 실행 가능한 "재연결" 프롬프트를 표면화합니다.
- **영속화 마이그레이션**(`ProtectionConnectivityNotificationStore`, 스키마 v2, `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`를 통해 연결)은 레거시의 미해결 `reconnect-needed` 마커를 `dnsSlow`로 강등하여 업그레이드 전반에서 에스컬레이션이 작동하도록 합니다.

### Device-DNS 캡처 재시도

활성 설정이 기기 리졸버에 (primary로 또는 fallback으로) 의존할 때, 네트워크 핸드오프/웨이크는 터널이 빈 시스템 리졸버 캡처를 보유한 채로 남겨둘 수 있습니다 — 조용한 막힘입니다. `DeviceDNSFallbackPolicy`는 **제한된 재시도**(`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1초, `deviceDNSCaptureMaxRetryAttempts` 5)를 구동합니다. 터널은 캡처가 비어 있지 않을 때까지 최대 다섯 번의 시도 동안 매초 시스템 리졸버를 다시 읽은 다음, 제자리에서 그것을 채택합니다 — 터널 재시작 없이 자동 회복합니다(이벤트 `device-dns-capture-retry` / `-exhausted`). 순수 DoH/DoT/DoQ 설정에서는 no-op입니다(`currentConfigurationDependsOnDeviceDNS()`).

### Guardian 마스코트 상태

Soft Shield Guardian 마스코트는 정확히 **일곱 가지** 감정 상태를 가집니다 — `GuardianMascotState`(`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. 각 상태는 자신의 `allowedNextStates`를 선언하므로 전환이 제약됩니다(예: `grateful`은 오직 `awake`로만 돌아감, `GuardianMascotAnimation.swift:12-29`). 의미는 다음과 같습니다.

- `retrying` = 차분한 자가 치유.
- `concerned` = 부드러운 도움 요청.
- `grateful` = 축하하는 성공(연결성 맵이 아니라 온보딩/설정 표면에서 사용).

`GuardianMascotAnimation`은 `LavaSecCore`의 절차적 애니메이션 코어입니다. `SoftShieldGuardian`(`Shared/SoftShieldGuardian.swift`)은 SwiftUI 렌더링이며 `GuardianShieldStyle`로 선택되는 커스터마이징 스킨(표시 이름 Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, `displayName` 매핑은 18-35행)을 지원합니다. 일부 raw 값은 표시 이름과 다르므로(예: `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, 그리고 `purpleObsidian`은 "Amethyst"로 렌더링됨), 레이블이 아니라 raw 값을 영속화하세요.

### 둘이 어떻게 연결되는가

Live Activity의 `LavaActivityAttributes.ProtectionState`(`Shared/LavaActivityAttributes.swift`)는 `guardianState`를 통해 평가를 마스코트 상태에 연결합니다: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned`(`LavaActivityAttributes.swift:95-105`). `AppViewModel`은 동일한 `protectionConnectivityAssessment`(`AppViewModel.swift:3131-3147`)로부터 Dynamic Island의 보호 상태를 선택합니다. `networkUnavailable` 심각도는 `.networkUnavailable`이 되고, `recovering`은 `.reconnecting`이 되며, `reconnect` 기본 액션은 `.needsReconnect`가 되고, 그 외에는 `.on`이 됩니다.

> 참고: `LavaTier`(차분함 → **Floor** / 축하함 → **Window** / 기술적 → **Workshop** 디자인 시스템 깊이 enum)는 디자인 시스템 레이어(`LavaSecApp/LavaDesignSystem/LavaTokens.swift`)에 배포되어 대표적인 표면들에 연결됩니다 — [디자인 시스템](../design-system/overview.md)을 참고하세요. 이는 여기서 설명하는 보호/터널 클라이언트 경로가 아니라 디자인 시스템 깊이를 관장합니다.

---

## 5. Live Activity 및 위젯

위젯 타깃은 Live Activity와 Dynamic Island만 렌더링합니다. `LavaSecWidgetBundle`(`LavaSecWidget/LavaSecWidget.swift`)은 단일 `LavaProtectionLiveActivityWidget`을 노출하며, 이는 다음을 갖춘 `ActivityConfiguration(for: LavaActivityAttributes.self)`입니다.

- 잠금 화면 뷰, 확장된 Dynamic Island 중앙 영역, 그리고 `SoftShieldGuardian`과 상태 글리프를 렌더링하는 compact/minimal 표현. compact/잠금 뷰는 초당 `TimelineView`에서 *유효* 보호 상태를 재계산하므로 일시중지 카운트다운이 푸시 없이도 라이브로 유지됩니다.

`LavaActivityAttributes.ContentState`는 `protectionState`, `resumeDate`(일시중지 카운트다운용), `pauseRequiresAuthentication`, 그리고 선택된 `shieldStyle`를 운반합니다. 디코딩은 관대하여 — `shieldStyle`이 없으면 `.original`로 폴백 — 오래된 Live Activity 페이로드도 계속 작동합니다.

앱 측에서 `LavaLiveActivityController`(`LavaSecApp/LavaLiveActivityController.swift`)는 라이브 `Activity<LavaActivityAttributes>`를 소유합니다. ActivityKit 권한 변경을 관찰하고, phone/pad idiom에서만 Live Activity를 제공하며, `reconcile(...)`은 요청된 보호 상태에 맞추어 액티비티를 시작/업데이트/종료합니다. `AppViewModel.reconcileLiveActivity()`(`AppViewModel.swift:3069`)는 원하는 상태를 재계산하고 컨트롤러를 호출하는 단일 깔때기입니다. Dynamic Island 버튼은 `LiveActivityIntent`들을 디스패치하며, 이들은 [§2](#2-app-extension-ipc)에서 설명한 대로 `LavaProtectionCommandService`를 호출합니다.

---

## 6. 온보딩 플로우

온보딩은 `LavaOnboardingView`(`LavaSecApp/OnboardingFlowView.swift`)에 의해 제시되며 `RootView`(`RootView.swift:32`)에 선언된 `@AppStorage("hasSeenLavaOnboarding")` 플래그로 게이팅됩니다. 플로우는 `OnboardingPage`들의 시퀀스입니다(`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

배포되는 시작 설정은 `OnboardingDefaults`(`Sources/LavaSecCore/OnboardingDefaults.swift`)에서 옵니다. `AppConfiguration.lavaRecommendedDefaults`는 관대한 권장 소스(Block List Basic)만 활성화하고, 리졸버로 **Device DNS**를 선택하며 — `DNSResolverPreset.device`(id `device-dns`), 네트워크 자체의 DNS이며, Google DoH 같은 암호화 프리셋은 옵트인이고 기본값으로 승격되지 않음 — device-DNS fallback을 활성화하고, 로컬 로깅을 켠 상태로 유지합니다 — `protectionEnabled: false`로, 보호는 사용자가 선택할 때만 켜집니다. `OnboardingDefaultsSummary`는 이 선택들을 표시용으로 포맷합니다("Continue without account"가 계정 기본값입니다).

마지막에 `hasSeenLavaOnboarding = true`를 설정하는 것이 `hasCompletedOnboarding`을 뒤집으며, 이는 다시 [§3](#3-vpn-lifecycle-control)에서 설명한 시작 재조정 경로를 무장시킵니다. 그때까지는 온보딩 도중 무력화 경로가 상속된 fail-closed 터널이 트래픽을 차단하지 못하도록 유지합니다.

---

## 7. 앱 상태: `AppViewModel`

`AppViewModel`(`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`)은 앱 측의 중심 상태 소유자입니다. VPN 라이프사이클을 넘어, UI가 바인딩하는 표면들을 게시하며, 여기에는 다음이 포함됩니다.

- **보호 및 터널** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth`(`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, 그리고 사용자 대상 `vpnMessage`/`vpnMessageIsError`.
- **설정 및 카탈로그** — `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, 그리고 컴파일된 규칙 카운트(`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **진단** — `DiagnosticsStore`와 `NetworkActivityLog`(모두 로컬, 아래 프라이버시 약속 참고).
- **계정 및 백업** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, 그리고 **Lava Security Plus** 오퍼/엔타이틀먼트 상태.
- **커스터마이징 및 표현** — `appearancePreference`, `lavaGuardLook`(`GuardianShieldStyle`), `lavaGuardProgress`, 그리고 `usesLiveActivities`.

라이프사이클 직렬화를 `protectionActionOrchestrator`에 위임하고(백그라운드 복원이 사용자 켜기와 끼어들지 않도록), 캐시된 `tunnelManager`를 보유하며, 모든 스냅샷/설정/일시중지 변경을 [§2](#2-app-extension-ipc)의 프로바이더 메시지 헬퍼를 통해 익스텐션으로 구동합니다.

> **프라이버시 프레이밍.** DNS 필터링은 이 기기에서 로컬로 일어납니다. `AppViewModel`이 게시하는 진단 및 네트워크 활동 표면은 로컬에만 저장됩니다 — Lava는 사용자의 일상적인 DNS 질의, 브라우징 기록, 또는 도메인별 텔레메트리를 결코 수신하지 않습니다. 선택적 계정 백업은 모두 **제로 지식**(기기에서 암호화되며, Lava는 오직 암호문만 저장 가능)이며, 패스키 기반 복구를 포함합니다 — 그 키는 서버 보유 시크릿 없이 기기에서 PRF로 파생됩니다. 서버 경계는 [시스템 개요](./system-overview.md)를 참고하세요.

---

## 관련 문서

- [시스템 개요](./system-overview.md) — 전체 시스템을 한 화면에: 앱, 카탈로그 Worker, Supabase, 그리고 전반에 사용되는 신뢰 경계와 상태 범례.
- [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md) — 여기서는 제어 경계에서만 참조되는 패킷 터널 내부: 컴파일된 필터링 엔진, 암호화된 리졸버 트랜스포트(DoH / DoH3 / DoT / DoQ), 필터 규칙 예산, 차단 목록 카탈로그, 그리고 source-url-only 재배포 모델.
- [계정 및 제로 지식 백업](./accounts-and-backup.md) — `AppViewModel`이 오케스트레이션하는 로그인 제공자와 제로 지식 백업 봉투(제로 지식, PRF 파생 패스키 복구 슬롯 포함).
- [백엔드 및 데이터](./backend-and-data.md) — 앱↔서버 경계의 반대편에 있는 `lavasec-api` 카탈로그 Worker, Cloudflare R2, 그리고 Supabase 스키마/RLS.
- [디자인 시스템](../design-system/overview.md) — `LavaTier` 깊이 모델, Soft Shield Guardian의 일곱 가지 상태와 실드 스킨, 그리고 클라이언트가 렌더링하는 카피/현지화 규약.
- [서드파티 고지](../legal/third-party-notices.md)와 [GPL source-url-only 컴플라이언스 결정](../legal/gpl-source-url-only-compliance-decision.md) — 클라이언트가 소비하는 카탈로그/필터 파이프라인 뒤에 있는 배포 제약.
