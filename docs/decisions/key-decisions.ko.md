---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 주요 설계 결정

> 대상 독자: 엔지니어와 리더십. 이 문서는 Lava Security를 떠받치는 핵심 설계 결정들을 ADR 형식으로 기록한 것입니다 — 아키텍처, 개인정보 보호 약속, 또는 제품 경계를 형성한 결정들, 그리고 특히 시도했다가 되돌린 결정들입니다. 각 항목은 **결정**, 그 **맥락**, **근거**, 그리고 프로젝트 상태 범례(채택됨 / 되돌림 / 대체됨 / 제안됨)에서 가져온 **상태**를 제공합니다.
>
> **코드가 이깁니다.** 계획과 실제 출시된 코드가 어긋날 때, 이 기록은 코드를 따르며 그 차이를 본문에서 짚어 줍니다.

**상태 범례(문서 세트의 상태 레인에 매핑됨):**

| 여기서의 상태 | 문서 세트 레인의 의미 |
|---|---|
| **채택됨** | 구현됨 — 출시되었고 코드에서 확인됨 |
| **되돌림** | 폐기됨 — 만들었다가 제거/되돌림 |
| **대체됨** | 이전 결정이 이후 결정으로 교체됨 |
| **제안됨** | 계획됨 — 설계, 권고, 또는 기록되었으나 아직 이 트리에 적용되지 않음 |

관련 읽을거리: 카탈로그 배포 모델은 [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md)와 [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md)에, 출시된 동작은 [`../product/features.md`](../product/features.md)에 있습니다. 앞으로의 방향성은 내부 로드맵에 담겨 있습니다.

---

## 1. `NEPacketTunnelProvider`를 통한 온디바이스 DNS 필터링 {#1-on-device-dns-filtering-via-nepackettunnelprovider}

**결정.** `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager`, 또는 Safari 콘텐츠 차단기가 아니라, `NEPacketTunnelProvider` 패킷 터널(`LavaSecTunnel`, `com.lavasec.app.tunnel`)을 통해 DNS를 **기기에서 로컬로** 필터링합니다.

**맥락.** 이 제품은 비기술 사용자(부모, 어르신)를 위한 개인정보 우선 필터로, 계정 없이 일반 소비자용 App Store를 통해 출시됩니다. 경쟁하는 NetworkExtension 제공자들과 관리형 DNS API들은 감독/MDM 관리 기기로 제한되거나 앱의 모든 DNS를 다루지 못하며, 리졸버 측 모델은 사용자의 도메인 스트림을 기기 밖으로 보내게 됩니다.

**근거.** 패킷 터널은 (a) 관리되지 않는 일반 소비자 기기에서 작동하면서 (b) 모든 DNS 결정이 기기에서 일어나게 하는 유일한 제공자이며, 이것이 개인정보 보호 약속의 토대입니다: *모든 DNS 필터링은 기기에서 이루어집니다; Lava는 결코 여러분의 브라우징을 자사 서버로 라우팅하지 않으며, 여러분이 방문하는 도메인 스트림을 결코 수신하지 않습니다.* 그 대가로 받아들인 절충은 터널이 그 아래에서 동작해야 하는 iOS의 **확장당 ~50 MiB 메모리 상한**으로, 이는 아래의 여러 후속 결정을 형성하는 제약입니다.

**상태.** **채택됨**(기반이 되는 결정; 최초 프로토타입부터 코드에 존재).

---

## 2. 소스 URL만 제공하는 차단 목록 배포 {#2-source-url-only-blocklist-distribution}

**결정.** Lava는 업스트림 차단 목록의 **URL과 허용된 해시**만 게시합니다; 기기는 각 `source_url`에서 목록의 **바이트**를 직접 가져온 뒤, 로컬에서 파싱, 정규화, 중복 제거, 필터링합니다. Lava는 제3자 차단 목록 바이트를 **결코** 저장, 미러링, 변환, 제공하지 않습니다. Worker는 카탈로그 **메타데이터** JSON만 R2에 기록합니다(`raw_r2_key`/`normalized_r2_key`는 null).

**맥락.** 이전 설계는 변호사가 배포를 검토할 수 있도록 원본 차단 목록 바이트를 R2에 미러링했습니다. 많은 업스트림 목록(HaGeZi, OISD)은 GPL-3.0이므로, 그 바이트를 호스팅하면 Lava가 GPL 데이터의 재배포자가 됩니다.

**근거.** Lava를 차단 목록 배포자가 아니라 로컬 필터링 엔진 / 사용자 에이전트로 취급하면 GPLv3 재배포와 App Review 노출이 최소화됩니다. 기기는 다운로드한 바이트를 카탈로그의 `accepted_source_hashes`에 대해 검증하고, 불일치 시 마지막 정상 캐시로 폴백하거나 닫힘으로 실패(fail closed)하여, 미러 파이프라인이 제공했던 안전 속성을 회복합니다. 파싱된 모든 규칙 세트는 또한 보호 도메인 필터를 거치므로, 업스트림 목록이 Lava/Apple/신원 공급자 도메인을 차단할 수 없습니다. 이 모델은 CI에서 `check-gpl-blocklist-distribution.sh`로 강제됩니다(미러 코드 없음, Lava 호스팅 아티팩트 URL 없음, 기본 활성화된 GPL 소스 없음, R2 바이트 쓰기 없음).

**상태.** **채택됨**, 그리고 폐기된 R2 원본 미러 계획을 **대체함**(`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, 헤더 "Superseded by the source-url-only implementation"). [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) 참조.

---

## 3. 암호화된 리졸버 전송(DoH / DoH3 / DoT / DoQ) {#3-encrypted-resolver-transports-doh--doh3--dot--doq}

**결정.** 평문 DNS 및 기기 DNS 폴백과 함께 네 가지 암호화된 업스트림 전송을 출시하며, 이를 LavaSecCore로 추출합니다: **DoH**(URLSession), **DoH3**(HTTP/3를 우선하는 DoH), **DoT**(풀링된 `NWConnection`, 엔드포인트당 최대 4개, 유휴 노후화 갱신 및 신규 연결 1회 재시도 포함), **DoQ**(DNS-over-QUIC). 라우팅, 평문 DNS 강등, 백오프 게이트가 있는 엔드포인트별 페일오버, 기기 DNS 폴백은 `ResolverOrchestrator`에 있습니다.

**맥락.** 차단되지 않은 쿼리를 평문으로 리졸버에 전달하면, 온디바이스 모델이 보호하려는 바로 그 도메인 스트림이 새어 나갑니다. 전송들은 점진적으로 만들어졌습니다(DoH → DoH3 → DoT → DoQ).

**근거.** 암호화된 업스트림 전송은 차단되지 않은 쿼리를 종단 간 비공개로 유지합니다. **DoH3**는 순전히 관찰적으로만 표시됩니다 — `assumesHTTP3Capable=true`를 설정하고 협상된 프로토콜을 관찰하며, UI는 **실제로 h3 협상이 관찰될 때에만** `DoH3`(슬래시 없음)를 주석으로 달고 결코 약속하지 않습니다. h3는 연결마다 최선 노력(best-effort)일 뿐이며, 고정된 주장은 UDP를 차단하는 방화벽 뒤에서 동작을 과장하기 때문입니다. 유휴 갱신이 포함된 DoT 풀링은 Cloudflare가 유휴 DoT 연결을 조용히 닫는 문제에 대한 직접적인 해결책이었습니다.

**상태.** **채택됨**(네 가지 전송 모두 존재하고 배선됨).

---

## 4. DoQ 연결 재사용 — 만들고, 기기에서 테스트하고, 되돌림 {#4-doq-connection-reuse--built-device-tested-reverted}

**결정.** DoQ용 QUIC 연결을 **재사용하지 않습니다**. `DoQTransport`는 **쿼리마다 새 QUIC 연결**을 엽니다; 4레인 풀은 핸드셰이크 재사용이 아니라 동시성을 제공합니다.

**맥락.** RFC 9250은 각 DNS 쿼리를 자체 QUIC 스트림에 매핑하므로, 진정한 재사용에는 **iOS 26.0 이상에서만** 제공되는 다중 스트림 `NWConnectionGroup`/`openStream` API가 필요하지만, 배포 하한선은 iOS 17입니다. 그럼에도 iOS 26으로 게이트된 재사용 경로가 구현되어(Xcode 26 SDK에 대해 Debug+Release 컴파일됨) **iOS 26.5에서** AdGuard DoQ를 상대로 **기기 테스트**되었습니다.

**근거.** 재사용 경로는 기기에서 모든 시도에 실패했고(`openStream`/`receive`가 오류를 냈고, 이어 폴백이 "Socket is not connected"에 부딪힘), 쿼리별 기준선보다 **순 성능이 더 나빴습니다**(대조군: 핸드셰이크 34회 / 쿼리 35회, 전부 성공). 이는 Apple DTS의 "새 Network 프레임워크로 QUIC는 보류하라"는 지침을 경험적으로 확인해 주었고, 그래서 이 작업은 출시되지 않고 되돌려졌습니다; 문서와 가드 테스트 근거만이 이 발견을 보존하여, API가 성숙하기 전에 재시도되지 않도록 합니다.

**상태.** **되돌림**(배포 하한선이 iOS 26에 이를 때까지 보류). DoQ는 쿼리별 새 연결로 기술하세요.

---

## 5. 통합 `DNSResolvingTransport` 프로토콜 거부 {#5-reject-a-unifying-dnsresolvingtransport-protocol}

**결정.** 리졸버 전송들을 단일 `DNSResolvingTransport` 프로토콜로 **통합하지 않습니다**; 클로저 기반의 `ResolverOrchestrator.Executors` 이음새를 유지합니다.

**맥락.** 한 리팩터(이슈 407)가 모든 전송에 대해 하나의 프로토콜을 제안했습니다.

**근거.** 전송들은 너무 이질적입니다 — 비동기 암호화 실행기(DoH/DoT/DoQ) 대 동기식 다중 주소 평문/기기 전송 — 그래서 통합 프로토콜은 기존의 주입 가능한 클로저 이음새보다 더 나쁜 추상화가 됩니다. 이 이음새는 이미 와이어 실행을 테스트 가능하게 유지합니다.

**상태.** **되돌림** / 구현 안 함(나쁜 추상화로 종결).

---

## 6. 제로 지식 암호화 백업(비밀번호 없음, 패스키 예외 명시) {#6-zero-knowledge-encrypted-backup-passwordless-passkey-exception-noted}

**결정.** **최소화된** 설정 페이로드를 클라이언트 측에서 백업합니다: AES-256-GCM이 임의의 32바이트 페이로드 키로 봉인하고, 그 키는 PBKDF2-HMAC-SHA256(프로덕션에서 **210,000**회 반복)을 통해 비밀별 **키 슬롯**으로 감쌉니다. 암호문과 비비밀 메타데이터만 Supabase `user_backups` 테이블(사용자별 RLS)에 업로드됩니다. 출시된 플로우는 **비밀번호가 없습니다**: 기기 비밀 슬롯(기기 로컬 Keychain) + 보조 복구 슬롯 + 선택적 패스키 슬롯.

**맥락.** 선택적 계정 로그인(Apple + Google만)으로 기기 간 설정 복원이 가능합니다. 서버는 사용자의 차단 목록, 허용 목록, 리졸버 선택, 기타 설정을 결코 읽을 수 없어야 합니다.

**근거.** 평문과 복호화하는 비밀은 기기에만 존재하고; 서버는 사용자당 불투명한 봉투 하나만 보관합니다. 보조 복구는 의도적으로 2요소입니다 — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)`(NUL로 구분된 입력)는 서버가 보관하는 share와 사용자의 8단어 복구 문구(~105비트)를 **둘 다** 요구하므로, 어느 한쪽만으로는 복호화되지 않습니다. 잠금 해제 자료는 기기 로컬(`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`)에 저장되며, 동기화되는 iCloud Keychain에는 **저장되지 않습니다** — 이는 원래 계획의 동기화 설계를 되돌린 개인정보 강화입니다. **패스키 슬롯 또한 진정으로 제로 지식입니다**: 이는 클라이언트를 결코 떠나지 않는 WebAuthn **PRF / `hmac-secret`** 인증자 출력(HKDF-SHA256으로 파생)으로 감싸지므로, 서버가 보관하는 어떤 값으로도 풀 수 없습니다. service-role 패스키 테이블도 없고 Worker WebAuthn 어서션 게이트도 없습니다 — 이전의 서버 게이트 방식 패스키 설계는 폐기되어, 모든 서버 측 패스키 상태를 제거했습니다(`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**상태.** **채택됨**(비밀번호 없는 모델, 보조 복구, 제로 지식 PRF 파생 패스키 슬롯이 모두 코드에 존재). 실제 기기에서 패스키를 완전히 프로덕션 수준의 복구 가능한 요소로 만드는 것(PRF 모델을 위한 Associated Domains / AASA 호스팅)은 **제안됨**(백로그)입니다.

---

## 7. 닫힘 실패(Fail-closed) Connect-On-Demand {#7-fail-closed-connect-on-demand}

**결정.** OS가 중단한 터널이 자동 재시작되도록 `NEOnDemandRuleConnect` 규칙을 추가하되, 안전한 기본값으로 **닫힘 실패**를 둡니다: 재사용 가능한 필터 스냅샷이 없을 때 터널은 트래픽을 필터링 없이 통과시키는 대신 모두 차단합니다. 온디맨드는 **모든 중단에 앞서 비활성화**되므로 VPN은 계속 끌 수 있는 상태로 유지됩니다.

**맥락.** iOS가 터널을 조용히 중단시키고(사유 17) 약 45분 동안 아무것도 재시작하지 않아, 사용자가 보호받지 못하는 상태가 되곤 했습니다. 온디맨드를 순진하게 켜면 VPN을 끌 수 없게 되고, 열림 실패(fail-open) 기본값은 그 공백 동안 트래픽을 통과시킵니다.

**근거.** 온디맨드는 조용한 중단의 공백을 메우고; 중단 전 비활성화는 사용자가 보호를 끌 수 있는 능력을 보존하며; 닫힘 실패는 그 공백이 조용히 필터링 안 된 상태가 아니라 안전하도록 보장하고, 이는 `reconcileTunnelSnapshotAfterLaunch`로 회복됩니다. 이 변경에는 부작용이 있었습니다 — 온디맨드가 온보딩 중에 "VPN 구성 추가" 시스템 프롬프트를 재유발했습니다 — 그래서 다중 커밋 수정 체인이 생겼습니다: 설치 시 온디맨드 활성화를 중단하고, 실행/보호 복원을 온보딩 완료에 게이트하고, **상속/고아 구성을 저장(`saveToPreferences`, 프롬프트를 다시 띄움)이 아니라 제거(`removeFromPreferences`, 조용함)로 무력화**했습니다(`on-demand=false` 저장이 아님).

**상태.** **채택됨**(온디맨드 재시작과 온보딩/닫힘 실패 수정 체인).

---

## 8. 모듈식 VPN 리팩터와 발열 회귀 규율 {#8-modular-vpn-refactor-and-the-heat-regression-discipline}

**결정.** VPN 경로(VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService)를 캐시 우선 켜기, 경계 있는 병렬 가져오기, 플랩 합치기를 위해 재구조화하며 — 배터리/지연을 명시적 p50/p95 목표가 있는 제품 요구사항으로 다루고 (Simulator가 아닌) **기기에서** 프로파일링합니다.

**맥락.** 켜기 / 갱신 / 일시정지 / 재개가 느렸습니다. 리팩터 중에 발열 회귀가 나타났습니다(CPU 134%, 높은 에너지, 뜨거운 폰). 대규모 에이전트 패널이 먼저 회귀 이전 증거로 의심된 원인을 반박했고; 그 뒤 실시간 기기 캡처가 이를 확인했습니다.

**근거.** 진짜 원인은 자기 지속적인 `NEVPNStatusDidChange` 갱신 루프였습니다 — drop-reentrant 가드가 교체된 뒤 영원히 재무장하는 합치기 루프(~초당 370 이벤트, 메인 스레드 ~100%, `vpn-debug-log.jsonl`이 ~180–210 MB로 불어남)였습니다. 수정은 캐시된 매니저 상태를 읽고 루프를 경계 짓습니다. 계획 자체의 전/후 기기 아티팩트는 iPhone 15 Pro에서 웜 켜기(`action.turnOn`)가 **2,722 ms → 287 ms**로 떨어진 것을 기록합니다; 별도의 후속 모듈화 이후 기회 검토는 동일 기기에서 웜 경로를 **112 ms**(디코드 51 + 매니저 설정 57)로 측정했습니다. 이 일화는 기준을 세웠습니다: 구조적 리팩터는 측정된 발열 회귀가 경계 지어질 때까지 멈추며, Simulator의 발열/배터리 결과는 무의미한 것으로 거부됩니다.

**상태.** **채택됨**(`plans/implemented/2026-06-12-modular-speed-up-plan.md`). 모듈화 이후 검토는 `PacketTunnelProvider`와 `AppViewModel`을 알려진 채로 살아남은 거대 객체(god-object)로 유지합니다.

---

## 9. 목록 개수 상한 대신 필터 규칙 예산 {#9-filter-rules-budget-instead-of-a-list-count-cap}

**결정.** 등급을 활성화된 목록 개수가 아니라 **필터 규칙 예산** — **무료 500K / Plus 2M** 컴파일된 도메인 규칙 — 으로 제한합니다. 단단한 **~3.26M 규칙 기기 가드레일**(`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`)이 **모두에게** 적용되며 **결코 유료 장벽이 아닙니다**. 컴팩트 도메인 블롭은 `mmap`(`.mappedIfSafe`)되므로 파일 기반으로 유지되고 jetsam이 계산하는 `phys_footprint` 밖에 있습니다; 디코드된 엔트리 테이블만 상주 메모리를 차지합니다.

**맥락.** 옛 상한은 목록 **개수**(무료 3 / 유료 10)였습니다. 한 목록이 1K 또는 1M 규칙을 담을 수 있으므로, 개수는 실제로 제약된 자원 — NE 50 MiB 메모리 상한 — 의 정직하지 못한 대리 지표였습니다.

**근거.** 규칙은 실제 메모리에 대응되므로, 들어맞는 어떤 목록 조합이든 허용됩니다. 권위 있는 강제는 `FilterSnapshotPreparationService`에서 중복 제거된 합집합에 대해 컴파일 시점에 실행됩니다(먼저 기기 가드레일, 그다음 등급 한도); 선택 시점 UI 미터는 1.10 소프트 상한 여유를 둔 목록별 합계를 사용합니다. 예산 초과 구성은 터널이 jetsam되게 두는 대신 결정론적으로 거부됩니다(보호를 꺼 둠).

**상태.** 코드에서 **채택됨**(`SubscriptionPolicy.swift`), **v1.0.0**에 출시되어 목록 개수 상한을 **대체함**. 규칙 예산은 이제 실제 등급 게이트입니다; 도메인별 상한도 1.0에서 상향되었습니다(허용 및 차단 도메인 무료 25 / Plus 1,000). [`../product/features.md`](../product/features.md) 참조.

---

## 10. 마크다운 계획 + 단방향 Linear 동기화 {#10-plans-as-markdown--one-way-linear-sync}

**결정.** `plans/<lane>/`의 마크다운 파일이 **진실의 원천**입니다; **레인 폴더가 권위 있는 상태**입니다(`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). `main`으로의 푸시는 계획을 Linear(팀 LAV)로 **단방향** 동기화하며, 생성 후에는 제목/설명만 갱신합니다; 별도의 **수동, 검토된** 역방향은 Linear의 상태/우선순위/레인을 계획 프런트매터로 다시 가져옵니다.

**맥락.** 소규모 팀에는 프로젝트 트래커와 다투지 않는, 도구 독립적이고 검토 가능한 계획 상태가 필요하며, 자율 에이전트 루프에는 계획 상태를 읽고 쓸 안정적인 장소가 필요합니다.

**근거.** 필드 소유권 분리는 두 시스템을 충돌 없이 유지합니다 — 마크다운은 콘텐츠를, Linear는 분류 상태를 소유합니다 — 그래서 푸시가 사람의 분류를 결코 덮어쓰지 않습니다. `dropped/` 레인은 취소된 계획을 동기화 파이프라인에서 빼내어 다시 나타나지 않게 합니다(Allowed Exceptions Guardrails / LAV-5가 거부되었을 때 생성됨). 계획 내부의 낡은 프런트매터는 상태가 아니라 문서 버그입니다; 폴더가 이기며, "Backlog" 프런트매터에도 불구하고 코드가 기능 출시를 보여 주는 경우(예: 계정 삭제)에는 코드가 이깁니다.

**상태.** **채택됨**(`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; `dropped/` 레인 사용 중).

---

## 11. 저장소 분할 + 클라이언트의 카피레프트 오픈소스화 {#11-repo-split--copyleft-open-source-of-the-client}

**결정.** 모노레포를 컴포넌트별 저장소(`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`)로 분할하고, Apache-2.0 대신 Mullvad/ProtonVPN 카피레프트 선례에 따라 **퍼스트파티 클라이언트를 AGPL-3.0로 오픈소스화**합니다.

**맥락.** 컴포넌트별 개발과 클라이언트의 오픈소스화. 라이선스 문제는 경쟁자가 클라이언트를 포크해 닫고 가격으로 우리를 깎아내릴 수 있느냐입니다.

**근거.** 카피레프트는 파생물이 계속 열려 있도록 강제하여 클라이언트의 닫힌 포크를 막습니다 — 백엔드, 법무, 운영을 비공개로 유지하는 "공개 클라이언트, 비공개 백엔드/운영" 자세입니다. 네트워크 사용 공백을 메우기 위해 (단순 GPL-3.0가 아니라) AGPL-3.0를 선택했습니다. 알려진 GPL 대 App Store 배포 긴장은 Lava 자신이 자체 저작권 아래 App Store 바이너리의 배포자가 됨으로써 처리됩니다.

**상태.** **채택됨.** 저장소 분할은 **완료**되었습니다: 각 컴포넌트가 자체 저장소에 있습니다 — 태그 v0.4.0의 공개 `lavasec-ios` 클라이언트와, Android, 마케팅 사이트, 백엔드/인프라, 문서, CI/릴리스 파이프라인을 위한 별도 저장소들 — 그리고 `lavasec-ios`의 `README.md` "Repository layout" 섹션은 그 저장소의 컴포넌트별 내용(`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`)만 나열하며 인프라는 별도의 비공개 저장소에 있다고 명시합니다. 클라이언트는 **AGPL-3.0** 아래 오픈소스화되었습니다: `lavasec-ios`의 `LICENSE`는 GNU Affero General Public License v3이며 `README.md`는 AGPL-3.0 배지를 답니다.

---

## 부록 — 그 밖에 기록된 되돌림과 거부 {#appendix--other-recorded-reversals-and-rejections}

이들은 더 작지만 기록된 전환이 있는 진짜 결정이었습니다; 완전성을 위해 나열합니다.

| 결정 | 근거 | 상태 |
|---|---|---|
| 커스텀 DNS 무료 대 유료 | 수익화 포지셔닝; 잠시 무료에서 허용했다가 유료 전용으로 복귀 | 유료 전용으로 **되돌림** |
| 이메일/비밀번호 로그인 | 비밀번호를 소유하면 재설정/MFA/잠금/유출/탈취 부담이 늘어나는 반면 Apple + Google로 충분하며; 복구 우회는 제로 지식을 깨뜨림 | **되돌림** / 출시 안 됨(Apple + Google만) |
| Allowed Exceptions Guardrails (LAV-5) | 더 단순한 필터 목록 편집 개편을 통해 가드레일 우선순위가 출시됨; 결제는 결코 고신뢰 위협 가드레일을 우회해서는 안 됨 | **되돌림**(`dropped/` 레인 생성됨) |
| TestFlight 브랜치 승격 잠금 | 초기 잠금을 재검토; 계획된 오픈소스 이후 러너 잠금으로 교체 | **되돌림**, 백로그 계획으로 대체됨 |
| 앱↔확장 제어 채널 | `sendProviderMessage`(`NETunnelProviderSession`)가 **유일한 앱→터널 제어 경로**입니다 — 이는 타입이 지정되고 버전이 매겨진 상태를 운반하며 확장 실행 루프를 권위 있게 구동합니다. 이전의 확장 측 `CFNotificationCenter` 옵저버는 기기에서 안정적으로 작동하지 않아 **제거**되었습니다(소스 인트로스펙션 테스트로 부재가 단언됨). Darwin 알림은 상태 변경 알림(nudge)으로 **터널→앱** 방향에서만 살아남습니다. | **채택됨**(프로바이더 메시지가 유일한 앱→터널 제어; Darwin은 터널→앱 상태 전용) |

> 문서 전반에서 참조되는 횡단 안전 불변식: 결제는 해시로 검증된, 허용 불가능한 **위협 가드레일**을 결코 우회하지 않습니다. 결정 우선순위는 **위협 가드레일 > 로컬 허용 목록(허용 예외) > 차단 목록 > 기본 허용**입니다.
