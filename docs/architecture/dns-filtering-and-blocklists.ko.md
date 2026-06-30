---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# DNS 필터링 및 차단 목록

> 대상 독자: 엔지니어. 이 문서는 온디바이스 DNS 파이프라인, 암호화 전송 리졸버 경로, 필터링 결정 엔진, 그리고 source-url-only 차단 목록 카탈로그 모델을 코드가 강제하는 정확한 수치와 함께 설명합니다. 상태(Status)는 코드로 확인된 현실을 반영합니다. 계획과 코드가 어긋나는 경우 **코드가 우선**하며, 그 차이를 본문에 명시합니다.

모든 DNS 필터링은 기기에서 일어납니다. Lava는 사용자의 브라우징을 자사 서버로 라우팅하지 않으며, 사용자가 방문하는 도메인의 흐름을 절대 받지 않습니다. 백엔드는 카탈로그 메타데이터, 사용자별 불투명 암호화 백업, 그리고 사용자가 보내기로 선택한 익명화된 진단 정보만 보유합니다.

Lava는 **로컬 DNS/차단 목록 필터링**이며, 모든 악성 도메인이나 URL이 차단된다는 보장이 아닙니다.

---

## 1. DNS 파이프라인 (구현됨)

필터/리졸브 엔진은 **NE / 패킷 터널** 내부에서 실행됩니다. 이는 DNS만 가로채는 `NEPacketTunnelProvider` 확장 `LavaSecTunnel`(`com.lavasec.app.tunnel`)입니다. 터널 주소는 `10.255.0.2`(터널)와 `10.255.0.1`(DNS 서버)입니다. 앱 프로세스는 쿼리 트래픽을 절대 보지 못하며, 컴파일된 아티팩트를 **App Group**(`group.com.lavasec`)에 쓰고 NETunnelProviderSession **provider 메시지**(Darwin 알림이 아님)를 통해 터널에 신호를 보낼 뿐입니다.

각 인바운드 DNS 쿼리에 대해 터널은 `DNSQueryDispatcher`(`Sources/LavaSecCore/DNSQueryDispatcher.swift`)에서 고정된 **쿼리 우선순위**를 실행합니다:

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap-first는 하드 불변 조건입니다.** 구성된 리졸버 *자신의* 호스트명(DoH/DoT/DoQ 엔드포인트)을 해석하는 쿼리는 절대 차단되거나 일시정지되어서는 안 됩니다. 그렇지 않으면 터널이 암호화 DNS를 아예 띄울 수 없습니다. 디스패처는 지연(lazy) 클로저를 사용하므로 각 단계는 도달했을 때만 읽히며, 단락 평가(short-circuit)를 보존합니다(bootstrap 응답이 있으면 스냅샷을 읽지 않고, bootstrapping 중에는 pause를 읽지 않음).
- **temporary pause**는 사용자가 시작한 일시정지 TTL이 활성인 동안 업스트림으로 전달합니다.
- **filter**는 컴파일된 스냅샷에 대해 도메인을 평가하여 전달하거나 차단 응답을 합성합니다.

필터를 통과한 쿼리(액션 `.allow`)는 리졸버 경로(§3)로 넘겨집니다. 재사용 가능한 스냅샷 없이 콜드 스타트할 때 터널은 **fail closed**합니다. 즉, 필터링되지 않은 채로 해석하는 대신 모든 트래픽을 차단하는 fail-closed 런타임 스냅샷을 설치합니다.

---

## 2. 필터링 엔진 (구현됨)

### 2.1 결정 우선순위

`FilterSnapshot.decision(forNormalizedDomain:)`(`Sources/LavaSecCore/FilterSnapshot.swift:57-71`)는 표준 안전 우선순위를 적용합니다:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| 순서 | 규칙 세트 | 결과 | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

정규화에 실패한 도메인은 `.invalidDomain` 사유로 차단됩니다(fail-safe). 동일한 우선순위가 바이너리 온디스크 형식(`CompactFilterSnapshot`)에도 그대로 반영됩니다. 위협 가드레일이 로컬 허용 목록 위에 위치하는 것은 의도된 설계입니다: **결제가 non-allowable 위협 가드레일을 절대 우회할 수 없으며**, 사용자 예외가 가드레일 도메인의 차단을 해제할 수 없습니다.

> 참고: 현재 작업 트리에서 `nonAllowableThreatRules` / `guardrailSources`는 비어 있습니다(`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`). 우선순위 슬롯은 연결되고 강제되지만 아직 가드레일 항목 없이 출시됩니다.

### 2.2 규칙 저장과 상주 메모리 단위

`DomainRuleSet`(`Sources/LavaSecCore/DomainRuleSet.swift`)는 `exactDomains` + `suffixDomains` 세트를 저장합니다. 매칭(`containsNormalized`)은 쿼리 시점에 정확 조회와 부모 접미사 탐색(`hasSuffix` 방식)을 수행합니다. **컴파일 시점의 서브도메인 포섭(subsumption)은 없습니다.** 유효한 와일드카드 한 줄은 **하나의 규칙**이자 하나의 메모리 테이블 항목입니다. 이 1줄 = 1규칙 동일성이 규칙 수를 정직한 리소스 지표로 만드는 근거입니다(§4).

### 2.3 컴파일된 스냅샷 형식

- **`FilterSnapshot`** — 인메모리 컴파일된 필터: `blockRules`, `allowRules`, `nonAllowableThreatRules`, 그리고 리졸버 프리셋.
- **`CompactFilterSnapshot`** — 터널이 실제로 읽는 바이너리, mmap 친화적 온디스크 형식(매직 `LSCFSNP1`, `fileVersion 1`). mmap을 통해 zero-copy로 로드됩니다(§4.3).

앱은 `filter-snapshot.json`과 `filter-snapshot.compact`를 모두 App Group에 씁니다. 터널은 compact 아티팩트를 디코딩합니다. **warm-startup 재사용** 경로(`FilterArtifactStore`)는 터널이 재컴파일 없이 온디스크 compact 아티팩트를 재사용할 수 있게 하며, 신원 지문(identity fingerprint)과 원자적으로 작성된 manifest로 게이트됩니다. 리졸버 전송, 카탈로그 커버리지, 또는 스냅샷 입력이 변경되면 재사용이 거부됩니다(프라이버시 안전, 필드명만 표시하는 사유).

---

## 3. 암호화 전송 및 리졸버 경로 (구현됨)

### 3.1 전송 enum

차단되지 않은 쿼리는 구성된 업스트림 리졸버로 전달됩니다. `DNSResolverTransport`(`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`)는 **다섯 개**의 값을 가집니다:

| 전송 | Raw 값 | UI에 표시되는 주석 |
|---|---|---|
| Device DNS | `device-dns` | *(없음 — 이름 자체가 전송 방식)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

내장 프리셋은 Google, Cloudflare, Quad9, Mullvad(각각 IP / DoH / DoT 변형)에 더해 Device DNS와 Custom입니다. 커스텀 리졸버는 일반 IPv4/IPv6 서버, DoH URL, DoT URL(`tls://` / `dot://`), DoQ URL(`doq://` / `quic://`), 또는 `sdns://` DNS 스탬프를 받습니다. 사용자명/비밀번호와 localhost는 거부됩니다. DoT/DoQ는 포트 `853`을 기본값으로 하며, DoH는 경로를 요구합니다.

### 3.2 DoH / DoH3

`DoHTransport`(`Sources/LavaSecCore/DoHTransport.swift`)는 `URLSession`을 통해 DoH를 실행합니다. 모든 요청은 HTTP/3을 선택합니다(`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`). Apple의 로더는 H2/H1로 네이티브하게 폴백하므로, 이로 인해 도달 가능한 리졸버가 도달 불가능해지는 일은 절대 없습니다. 협상된 프로토콜은 `URLSessionTaskTransactionMetrics.networkProtocolName`(ALPN: `h3`, `h2`, `http/1.1`)에서 읽습니다.

UI는 **`DoH3`(슬래시 없음)** — 예: "Quad9 (DoH3)" — 을 **실제로 h3 협상이 관측될 때만** 주석으로 표시합니다(`DoHHTTPVersion.dohAnnotation`). 그 외에는 `DoH`로 표시합니다. DoH3는 선호되지만 약속되지는 않습니다: 라벨은 관측적이고 리졸버 범위로 한정되며, 절대 영구 저장되지 않습니다("confirmed DoH3"의 재시작 간 이월은 되돌려졌습니다). 요청은 `application/dns-message`를 POST하며, 응답은 content-type과 길이가 검증되고 write-back 전에 트랜잭션 ID가 복원됩니다.

### 3.3 DoT

`DoTTransport`(`Sources/LavaSecCore/DoTTransport.swift`)는 풀링된 `NWConnection`을 사용하며, **엔드포인트당 최대 4개 연결**(`maxConnectionsPerEndpoint = 4`)을 라운드 로빈으로 사용하여 병렬 쿼리가 head-of-line 블로킹을 피하도록 합니다. 또한 **idle-staleness** 처리를 담고 있습니다: Cloudflare 같은 제공자는 상태 변화를 노출하지 않은 채 유휴 DoT 연결을 서버 측에서(~10초) 닫으므로, **8초**(`reusedConnectionMaxIdleInterval = 8`)보다 오래 유휴 상태였던 재사용 연결은 전송 전에 갱신되며, 재사용 연결에서의 타임아웃은 **정확히 한 번의 새 연결 재시도**를 얻습니다.

### 3.4 DoQ — 쿼리당 새 연결

`DoQTransport`(`Sources/LavaSecCore/DoQTransport.swift`)는 **엔드포인트당 4개 레인**의 제한된 풀을 유지하지만, **각 쿼리는 새 QUIC 연결을 엽니다** — 쿼리당 완전한 핸드셰이크. 4-레인 풀은 **핸드셰이크 재사용이 아니라 동시성**을 제공합니다.

**DoQ 연결 재사용 상태 (폐기 / 연기됨).** 재사용은 검토되고 기기에서 벤치마크되었으며(35개 쿼리에 걸쳐 34개의 새 핸드셰이크 ≈ 재사용 없음), 이후 iOS-26 게이트 멀티스트림 `NWConnectionGroup` 경로로 구현되어 AdGuard DoQ에 대해 기기 테스트되었으나, **순효과가 음수로 판단되어 되돌려졌습니다**(실제 서버에 대한 스트림 실패 + 폴백 오류). RFC 9250은 각 쿼리를 자신의 QUIC 스트림에 매핑하므로, 재사용은 `NWConnectionGroup`/`openStream`을 요구하며, 이는 **iOS 26.0+ 전용**입니다. 현재 배포 하한은 **iOS 17**입니다. 하한이 iOS 26에 도달할 때까지 재사용은 연기됩니다. 커스텀 DoQ는 지원하지 않는 기기에서 거부됩니다("DNS over QUIC is not supported on this device").

### 3.5 해석 정책

`ResolverOrchestrator`(`Sources/LavaSecCore/ResolverOrchestrator.swift`)는 업스트림 정책을 소유합니다:

1. 구성된 전송에 의한 **전송 라우팅**.
2. 암호화 계획에 엔드포인트가 없을 때 **plain DNS로의 강등**.
3. 백오프 게이트를 통한 **엔드포인트별 페일오버** — 백오프된 엔드포인트는 절대 와이어에 닿지 않습니다(결과 `backed-off`).
4. 기본(primary)이 응답을 반환하지 않고 *동시에* 계획이 허용할 때의 **Device-DNS 폴백**(계획 속성은 `shouldFallbackToDeviceDNS`로, `fallbackToDeviceDNS` 구성 필드에서 파생). 결과는 디바이스 전송으로 재주석됩니다. 와이어 실행은 정책이 단위 테스트 가능하도록 executor 뒤에 주입됩니다. 백오프 상태는 순수 정책 바깥에 머무릅니다.

---

## 4. 필터 규칙 예산, NE 상한, mmap

출시된 티어 지표는 **필터 규칙 예산**입니다: 사용자가 활성화할 수 있는 컴파일된 도메인 **규칙**의 총합. 이는 이전의 활성 목록 **개수** 상한(무료 3 / 유료 10)을 대체했는데, 그것은 정직하지 못한 대리 지표였습니다 — 한 목록이 1K일 수도 1M 규칙일 수도 있기 때문입니다. **두 개의 계층**이 있습니다: 전체 사용자 공통의 기기 가드레일과, 그 아래의 티어별 수익화 한도.

### 4.1 티어 한도 (구현됨)

`FeatureLimits`(`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`)가 진실의 원천입니다:

| 티어 | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | 커스텀 차단 목록 / DNS |
|---|---|---|---|---|
| **Free** | **500,000** | 25 | 25 | 아니오 |
| **Plus** (`.paid` / `.plus`) | **2,000,000** | 1,000 | 1,000 | 예 |

티어 한도는 수익화 경계이며, **기기 가드레일에 대한 페이월이 절대 아닙니다**. **Lava Security Plus**는 커스터마이징만 잠금 해제합니다 — 절대 기본 안전성이나 위협 가드레일이 아닙니다. 커스텀(유료) 차단 목록은 사용자 기기에서 직접 가져와 로컬에서 파싱·캐시되며, 절대 Lava 서버로 프록시되지 않습니다.

### 4.2 기기 메모리 가드레일 + NE 상한 (구현됨)

패킷 터널은 iOS의 **확장당 ~50 MiB 메모리 상한**을 적용받습니다(iOS 15 이래 패킷 터널을 위한 OS의 확장-유형별 설계 한도로, RAM에 비례하지 않습니다. 이는 기기 모델별 `com.apple.jetsamproperties.{Model}.plist`에 존재하며 구형 기기에서는 더 낮을 수 있습니다). 이를 초과하면 jetsam이 트리거됩니다. 상한을 알려주는 API가 없으므로, 예산은 그 한계선 아래로 여유를 둡니다.

`FilterSnapshotMemoryBudget`(`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`)가 필터 규칙(block + allow + guardrail) 단위로 계산을 수행합니다:

| 상수 | 값 |
|---|---|
| `baselineMegabytes` | 4.0 MB (고정 프로세스 오버헤드, 측정값 ≈3.5 MB, 올림) |
| `estimatedBytesPerRule` | 규칙당 9.0 B dirty resident (측정값 ≈8.5 B, 올림) |
| `maxResidentMegabytes` | 32.0 MB (목표 상한, 관측된 ~40–46 MB jetsam 절벽 아래로 ~10 MB 여유) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 규칙** |

이 **~3.26M 규칙 기기 가드레일**은 *모든* 사용자를 위한 하드 안전 하한으로, 어떤 구독 티어보다도 위에 위치하며 **절대 페이월이 아닙니다**. 앵커 측정(기기 "chimmy", 2026-06-13): **789,831 규칙 → 9.9 MB `phys_footprint`**, 즉 ≈ baseline + 규칙당 비용.

### 4.3 mmap 전략 (구현됨)

compact 스냅샷은 `Data(contentsOf:options:[.mappedIfSafe])`(`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`)로 로드되며, `CompactBinaryReader`는 zero-copy 슬라이스를 반환합니다. 수 메가바이트의 도메인 텍스트 blob은 **파일 백업/클린(file-backed/clean)** 상태로 유지되어 jetsam 집계 대상인 `phys_footprint`에서 제외됩니다. 디코딩된 `[Entry]` 테이블만 상주 메모리를 차지합니다(디스크에서 ~6 B/규칙, ~8.5 B dirty resident). 이것이 온디바이스 도메인 상한을 끌어올립니다: 상주 비용은 전체 아티팩트가 아니라 엔트리 테이블입니다.

### 4.4 2계층 강제 (구현됨)

- **권위적(컴파일 시점).** `FilterSnapshotPreparationService`(`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`)는 활성화된 모든 목록의 **중복 제거된 합집합(deduped union)**에 대해 예산을 강제합니다. 기기 가드레일이 **먼저** 검사되고(하드 하한), 티어 한도가 그 아래에 묶입니다. 예산 초과 구성은 터널이 jetsam되도록 두는 대신 결정론적으로 거부됩니다 — `exceedsDeviceMemoryBudget` 또는 `exceedsTierFilterRuleLimit`. 오류는 기여도가 가장 큰 두 목록의 이름을 명시하여 해결책을 명확히 합니다.
- **권고적(선택 시점 UI).** `FilterRuleBudget`(`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`)는 목록별 **합계**에 **1.10 소프트 상한 마진**을 적용하여 선택 미터를 구동하며, 이는 ~7–10%의 목록 간 과다 집계를 보정합니다(목록별 합계는 중복 제거된 합집합을 과대 추정함).

### 4.5 파서 (구현됨)

`BlocklistParser`(`Sources/LavaSecCore/BlocklistParser.swift`)는 규칙을 문자 그대로 셉니다: 주석/공백/무효 줄을 버리고, 정규화하고, 목록 내에서 정확 문자열을 중복 제거하며(`Set` 사용), 목록당 **`maxRules = 1,000,000`**(기본값)으로 제한하고, 최대 줄 길이는 4,096자입니다. 지원 형식: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq`(auto는 hosts → dnsmasq → adblock → plain 순으로 시도). 유효한 한 줄 = 하나의 규칙 = 메모리 단위.

> **다중 호스트 `hosts` 줄 (파서 rules version 2).** 하나의 IP를 여러 호스트에 매핑하는 `hosts` 줄(`0.0.0.0 a.com b.com c.com`)은 이제 첫 번째 호스트만이 아니라 **모든** 호스트를 각각의 규칙으로 방출합니다. `maxRules`는 줄당이 아니라 **규칙당** 강제되므로, 상한 근처의 다중 호스트 줄이 초과하지 못합니다. 동일한 업스트림 바이트가 이제 더 많은 규칙을 산출할 수 있으므로, 파서의 rules version이 **1 → 2**로 올라가, 이전의 첫-호스트-전용 동작으로 파싱된 오래된 `RuleSetCache` 항목을 무효화합니다.

### 4.6 다운로드 & 디코드 견고성 (구현됨)

터널과 카탈로그 동기화는 NE 메모리 예산 내에서 실행되므로, 목록 수집은 악의적이거나 잘못된 입력에 대해 강화되어 있습니다:

- **스트리밍 다운로드.** `defaultDataFetcher`는 전체 본문을 RAM에 버퍼링하는 대신 `URLSession.download`로 목록 바이트를 임시 파일에 다운로드하며(피크 메모리 제한), 다운로드 후 크기 검사(`maximumBlocklistBytes`)를 수행합니다. 본문이 너무 크면 `BlocklistDownloadSizeLimitExceeded`를 발생시킵니다.
- **카탈로그 메타데이터 상한(8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes`는 디코드 전에 너무 큰 원격 카탈로그를 거부하므로, 악의적/MITM 호스트가 확장에서 OOM JSON 디코드를 강제할 수 없습니다.
- **관대한 UTF-8 디코딩.** 단일 무효 UTF-8 바이트가 더 이상 전체 목록을 거부하지 않습니다(fail-closed 하에서는 모든 DNS를 차단함). 무효 바이트는 U+FFFD가 되며, 문제가 되는 줄만 줄별 검증에 실패하여 버려집니다.
- **이름 있는 커스텀 차단 목록 오류.** 실패한 커스텀 목록은 이제 원시 `URLError` 대신 `customBlocklistUnavailable(displayName:reason:)` — "Couldn't load the custom blocklist '<name>'. <why>" — 를 노출합니다. 취소는 다운로드 실패가 아니라 취소로 전파됩니다.

---

## 5. 차단 목록 카탈로그 & 기본 소스

### 5.1 카탈로그 모델 (구현됨)

**차단 목록 카탈로그**는 사용 가능한 소스의 게시된 목록입니다. **lavasec-api Worker**는 R2 버킷에서 `GET /v1/catalog`(및 `/v1/catalog/:version`)로 JSON 메타데이터를 제공합니다. 기기는 실제 목록 **바이트**를 각 업스트림 `source_url`에서 직접 가져옵니다. iOS 카탈로그 엔드포인트는 `https://api.lavasecurity.app/v1/catalog`(`BlocklistCatalogSync.swift:4-15`)입니다.

기기에서 `BlocklistCatalogSynchronizer`(`BlocklistCatalogSync.swift`)는:

1. `source.sourceURL`에서 목록 바이트를 직접 가져오며 크기 상한을 강제합니다.
2. SHA-256을 계산하고 체크섬이 카탈로그의 `accepted_source_hashes`에 있을 때만 바이트를 수락합니다.
3. 불일치 시, 마지막으로 양호했던 로컬 캐시로 폴백하거나 **fail closed**합니다(`checksumMismatch`) — 소스가 직접 업스트림 로테이션을 명시적으로 허용하는 경우는 예외입니다.
4. 로컬에서 파싱/정규화/중복 제거합니다.
5. 파싱된 모든 규칙 세트를 `DomainRuleSet.lavaSecProtectedDomains`(`AppConfiguration.swift:262-276`)로 필터링하여, 업스트림 목록이 Lava/Apple/신원 제공자 도메인을 절대 차단할 수 없게 합니다.

**보호 도메인 세트**(활성화 전에 걸러짐): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com`(모두 접미사 매칭). Worker는 메타데이터를 계산할 때 동등한 `PROTECTED_SUFFIXES` 필터를 적용하며, 기기는 그와 무관하게 재검증합니다.

### 5.2 큐레이션된 소스 (구현됨)

`DefaultCatalog.curatedSources`는 표준 [Blocklist Catalog](../legal/blocklist-catalog.md)에서 생성되며, 현재 일곱 개 카테고리에 걸쳐 **32**개 소스입니다: Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling, Piracy & Torrent. 소스 패밀리에는 The Block List Project, Phishing.Database, HaGeZi, OISD, StevenBlack, AdGuard, 1Hosts가 포함됩니다.

`guardrailSources`는 비어 있습니다. GPL 소스(HaGeZi, OISD, AdGuard)는 카탈로그에 보이지만 **opt-in / 기본 OFF**입니다. Worker는 출시 동기화/게시를 `source_url_only`와 정리된 GPL 접두사(`hagezi-`, `oisd-`, `adguard-`)로 게이트합니다.

### 5.3 무료 사용자를 위한 기본 활성 목록 (구현됨)

무료 기본 구성은 `OnboardingDefaults.lavaRecommendedDefaults`이며, **Block List Basic** — 광범위하고 허용적인 라이선스의 결합 목록(광고 + 추적 + 멀웨어 + 피싱/스캠) — 을 device-DNS 리졸버 프리셋(`resolverPresetID = DNSResolverPreset.device.id`)과 함께 활성화하고, 암호화 Device-DNS 폴백을 **켠**(`usesEncryptedDeviceDNSFallback = true`) 상태로 **Mullvad DoH**(`fallbackResolverPresetID = DNSResolverPreset.mullvadDoH.id`)로 라우팅합니다: 기기 자체의 DNS가 막히면 허용된 조회가 일시적으로 Mullvad DoH로 운반되었다가 자동으로 기기의 DNS로 돌아옵니다. (기본 `AppConfiguration()` 초기화기는 이 폴백을 **꺼진** 상태로 기본 설정합니다 — 권장 온보딩 기본값을 수락해야만 활성화됩니다.) 이는 이전의 Block List Project Phishing + Scam 쌍을 대체합니다: Basic의 결합 커버리지가 그것들을 포섭하며, 둘 다 opt-in 선택 가능 목록으로 남아 있습니다.

그 무료 기본값은 하드코딩된 것이 아니라 **`defaultEnabled`에 의해 생성**됩니다. `blockListProjectBasic`이 `defaultEnabled: true`를 설정하고, `DefaultCatalog.recommendedDefaultSourceIDs`는 `curatedSources.filter(\.defaultEnabled)`에서 파생됩니다. `defaultEnabled`는 "신규 설치 기본값의 단일 진실의 원천"으로, 백엔드 카탈로그의 `default_enabled` 컬럼을 미러링합니다. `recommendedDefaultSourceIDs`를 거쳐 `OnboardingDefaults`로 흐르는 이것이 살아있는 메커니즘입니다 — 소스의 플래그를 뒤집으면 기본값이 바뀝니다.

> **기본값 진실의 원천(하나의 생성된 스펙).** 카탈로그는 iOS `DefaultCatalog`와 백엔드 시드를 모두 생성하는 단일 표준 스펙([Blocklist Catalog](../legal/blocklist-catalog.md))에서 생성되므로, 기기와 제공되는 `/v1/catalog` 메타데이터는 구성상 일치합니다. 신규 설치 기본값은 그 `defaultEnabled: true` 플래그에 따라 **Block List Basic**입니다. 실제 티어 게이트는 목록 개수가 아니라 500K/2M 필터 규칙 예산입니다.

### 5.4 Source-url-only GPL 배포 모델 (구현됨)

**Source-url-only**는 GPL/IP 준수 배포 모델입니다: Lava는 업스트림 URL + 수락된 해시만 게시하고, 기기가 직접 목록을 가져와 파싱합니다. Lava는 제3자 차단 목록 바이트를 **절대** 저장, 미러링, 변형, 또는 제공하지 않습니다. 이는 **폐기된 R2-미러 설계를 대체한 것입니다**(원래의 "raw R2 mirror" 계획은 2026-05-25에 되돌려졌습니다).

Worker 측에서 `syncOneBlocklist`는 각 업스트림 소스를 가져와 정규화+해시하지만(`source_hash`, `normalized_hash`, `entry_count` 계산) `raw_r2_key = null` / `normalized_r2_key = null`을 씁니다 — 카탈로그 JSON 메타데이터만 R2에 도달합니다. `check-gpl-blocklist-distribution.sh`는 전체 모델을 강제하는 CI 가드레일입니다: 미러/변형 코드 없음, Lava 아티팩트/다운로드 URL 없음, GPL 소스 기본 활성화 없음, 목록 바이트의 Worker R2 쓰기 없음, "Lava-hosted mirror" 문구 없음, 번들된 GPL `.txt`/`.json` 없음, 그리고 마이그레이션 + 법무 문서에 `source_url_only` 필수.

> **라이선스 참고:** 일급(first-party) Lava 코드는 **AGPL-3.0** 하에 출시됩니다(`LICENSE` 파일은 GNU AGPL v3로, README 배지와 일치). 제3자 차단 목록(HaGeZi, OISD, AdGuard 포함)은 각자의 업스트림 라이선스 하에 남아 있습니다 — source-url-only 모델은 정확히 Lava가 카피레프트 목록 바이트를 절대 재배포하지 않고도 그것들을 사용할 수 있도록 존재합니다. 여기서 GPL-3.0은 Lava 앱이 아니라 업스트림 목록의 속성입니다.

---

## 6. 상태 요약

| 영역 | 상태 |
|---|---|
| DNS 쿼리 우선순위 (bootstrap > pause > filter) | 구현됨 |
| 필터 결정 우선순위 (guardrail > allowlist > blocklist > default-allow) | 구현됨 |
| 위협 가드레일 우선순위 슬롯 (연결됨; 아직 항목 없이 출시) | 구현됨 |
| DoH / DoH3 (관측적 h3 라벨) | 구현됨 |
| DoT (엔드포인트당 4개 풀, 8초 유휴 갱신, 한 번의 새 재시도) | 구현됨 |
| DoQ (쿼리당 새 연결, 4-레인 동시성) | 구현됨 |
| DoQ 연결 재사용 | 폐기 / iOS-26 하한까지 연기 |
| 리졸버 강등 + 엔드포인트별 페일오버 + device-DNS 폴백 | 구현됨 |
| 필터 규칙 예산 (Free 500K / Plus 2M) | 구현됨 |
| ~3.26M 규칙 기기 가드레일 (50 MiB NE 상한 아래 32 MB 목표) | 구현됨 |
| compact 스냅샷의 zero-copy mmap | 구현됨 |
| Source-url-only 카탈로그 + 직접 업스트림 가져오기 + 해시 검증 | 구현됨 |
| 보호 도메인 필터 | 구현됨 |
| 무료 기본값 = Block List Basic | 구현됨 (생성된 카탈로그 + iOS/백엔드 프로젝션 일치) |
| 일급 Lava 코드 라이선스 | AGPL-3.0 (`LICENSE`); 제3자 목록은 업스트림에서 GPL-3.0 유지 |

---

## 함께 보기

- [`../product/overview.md`](../product/overview.md) — 제품 한 줄 소개, 프라이버시 약속, 탭.
- 티어 & 수익화 (내부 참조) — Lava Security Plus와 티어 지표로서의 필터 규칙 예산.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — source-url-only 준수 결정.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — 업스트림 차단 목록/리졸버 라이선스 및 출처 표기.
