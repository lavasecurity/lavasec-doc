---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# DNS 필터링 및 차단 목록

> 대상 독자: 엔지니어. 이 문서는 기기 내 DNS 파이프라인, 암호화 전송 리졸버 경로, 필터링 결정 엔진, 그리고 소스 URL만 사용하는 차단 목록 카탈로그 모델을 코드가 적용하는 정확한 수치와 함께 설명해요. 상태는 코드로 확인된 현실을 반영해요. 계획과 코드가 다를 경우 **코드가 우선**하며, 그 차이는 본문에 직접 표시해요.

모든 DNS 필터링은 기기에서 이루어져요. Lava는 사용자의 브라우징을 자사 서버로 라우팅하지 않으며 사용자가 방문하는 도메인의 흐름을 받지 않아요. 백엔드는 카탈로그 메타데이터, 사용자별 불투명 암호화 백업, 그리고 사용자가 보내기로 선택한 익명화된 진단 정보만 보관해요.

Lava는 **로컬 DNS/차단 목록 필터링**이며, 모든 악성 도메인이나 URL이 차단된다는 보장은 아니에요.

---

## 1. DNS 파이프라인 (구현됨)

필터/리졸브 엔진은 **NE / 패킷 터널** 안에서 실행돼요. DNS만 가로채는 `NEPacketTunnelProvider` 확장 `LavaSecTunnel` (`com.lavasec.app.tunnel`)이에요. 터널 주소는 `10.255.0.2`(터널)와 `10.255.0.1`(DNS 서버)예요. 앱 프로세스는 쿼리 트래픽을 절대 보지 않으며, **App Group** (`group.com.lavasec`)에 컴파일된 산출물만 기록하고 NETunnelProviderSession **프로바이더 메시지**(Darwin 알림이 아니라)로 터널에 신호를 보내요.

각 인바운드 DNS 쿼리에 대해 터널은 `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`)에서 고정된 **쿼리 우선순위**를 실행해요:

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **부트스트랩 우선은 절대 불변 규칙이에요.** 구성된 리졸버 *자신*의 호스트 이름(DoH/DoT/DoQ 엔드포인트)을 해석하는 쿼리는 절대 차단되거나 일시중지되어서는 안 돼요. 그렇지 않으면 터널이 암호화 DNS를 전혀 가동할 수 없어요. 디스패처는 지연 클로저를 받아 각 단계가 도달했을 때만 읽히므로 단락 평가가 유지돼요(부트스트랩 응답이 있으면 스냅샷을 읽지 않고, 부트스트랩 중에는 일시중지를 읽지 않아요).
- **temporary pause**는 사용자가 시작한 일시중지 TTL이 활성인 동안 상위로 전달해요.
- **filter**는 컴파일된 스냅샷에 대해 도메인을 평가하고, 전달하거나 차단 응답을 합성해요.

필터를 통과한 쿼리(동작 `.allow`)는 리졸버 경로(§3)로 넘어가요. 재사용 가능한 스냅샷 없이 콜드 스타트하면 터널은 **닫힌 상태로 실패(fail closed)**해요. 즉, 필터링되지 않은 채 해석하는 대신 모든 트래픽을 차단하는 닫힌-실패 런타임 스냅샷을 설치해요.

---

## 2. 필터링 엔진 (구현됨)

### 2.1 결정 우선순위

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`)는 표준 안전 우선순위를 적용해요:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| 순서 | 규칙 집합 | 결과 | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | 차단 | `.threatGuardrail` |
| 2 | `allowRules` | 허용 | `.localAllowlist` |
| 3 | `blockRules` | 차단 | `.blocklist` |
| 4 | — | 허용 | `.defaultAllow` |

정규화에 실패한 도메인은 `.invalidDomain` 사유로 차단돼요(안전 우선). 동일한 우선순위가 바이너리 디스크 형식(`CompactFilterSnapshot`)에도 그대로 반영돼요. 위협 가드레일이 로컬 허용 목록보다 위에 있는 것은 설계상의 의도예요. **결제는 절대 허용 불가 위협 가드레일을 우회하지 않으며**, 사용자 예외로 가드레일 도메인의 차단을 풀 수 없어요.

> Note: 현재 작업 트리에서는 `nonAllowableThreatRules` / `guardrailSources`가 비어 있어요(`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`). 우선순위 슬롯은 연결되어 적용되지만 아직 가드레일 항목 없이 출시돼요.

### 2.2 규칙 저장과 상주 메모리 단위

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`)은 `exactDomains` + `suffixDomains` 집합을 저장해요. 매칭(`containsNormalized`)은 쿼리 시점에 정확 조회와 상위 접미사 탐색(`hasSuffix` 방식)을 수행해요. **컴파일 시점의 하위 도메인 포함(subsumption)은 없어요.** 유효한 와일드카드 한 줄은 **하나의 규칙**이자 하나의 메모리 테이블 항목이에요. 이 1줄 = 1규칙 동일성 덕분에 규칙 수가 정직한 리소스 지표가 돼요(§4).

### 2.3 컴파일된 스냅샷 형식

- **`FilterSnapshot`** — 메모리 내 컴파일된 필터: `blockRules`, `allowRules`, `nonAllowableThreatRules`, 그리고 리졸버 프리셋.
- **`CompactFilterSnapshot`** — 터널이 실제로 읽는 바이너리, mmap 친화적인 디스크 형식(매직 `LSCFSNP1`, `fileVersion 1`). mmap을 통해 제로 카피로 로드돼요(§4.3).

앱은 `filter-snapshot.json`과 `filter-snapshot.compact`를 모두 App Group에 기록하며, 터널은 compact 산출물을 디코딩해요. **웜 스타트업 재사용** 경로(`FilterArtifactStore`)는 터널이 디스크의 compact 산출물을 다시 컴파일하지 않고 재사용하게 해주는데, 동일성 지문 + 원자적으로 기록된 매니페스트로 통제돼요. 리졸버 전송, 카탈로그 커버리지, 또는 스냅샷 입력이 바뀌면 재사용은 거부돼요(프라이버시 안전, 필드 이름만 사유로 표시).

---

## 3. 암호화 전송과 리졸버 경로 (구현됨)

### 3.1 전송 열거형

차단되지 않은 쿼리는 구성된 상위 리졸버로 전달돼요. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`)는 **다섯 가지** 값을 가져요:

| 전송 | 원시 값 | UI에 표시되는 주석 |
|---|---|---|
| Device DNS | `device-dns` | *(없음 — 이름이 곧 전송이에요)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

기본 제공 프리셋은 Google, Cloudflare, Quad9, Mullvad(각각 IP / DoH / DoT 변형)에 더해 Device DNS와 Custom이에요. 커스텀 리졸버는 일반 IPv4/IPv6 서버, DoH URL, DoT URL(`tls://` / `dot://`), DoQ URL(`doq://` / `quic://`), 또는 `sdns://` DNS 스탬프를 받아요. 사용자 이름/비밀번호와 localhost는 거부돼요. DoT/DoQ는 포트 `853`을 기본으로 하고 DoH는 경로를 요구해요.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`)는 `URLSession`을 통해 DoH를 실행해요. 모든 요청은 HTTP/3을 선택해요(`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`). Apple의 로더가 H2/H1로 네이티브 폴백하므로 이로 인해 도달 가능한 리졸버가 도달 불가가 되는 일은 없어요. 협상된 프로토콜은 `URLSessionTaskTransactionMetrics.networkProtocolName`에서 읽어요(ALPN: `h3`, `h2`, `http/1.1`).

UI는 **실제로 h3 협상이 관측될 때만** **`DoH3`(슬래시 없음)** 를 주석으로 붙여요. 예: "Quad9 (DoH3)" (`DoHHTTPVersion.dohAnnotation`). 그 외에는 `DoH`로 표시해요. DoH3은 선호되지만 약속되지는 않아요. 라벨은 관측 기반이며 리졸버 범위 한정이고 절대 영속화되지 않아요("confirmed DoH3" 재시작 간 이월은 되돌려졌어요). 요청은 `application/dns-message`를 POST하고, 응답은 content-type과 길이가 검증되며 트랜잭션 ID는 다시 기록되기 전에 복원돼요.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`)는 풀링된 `NWConnection`을 사용해요. **엔드포인트당 최대 4개 연결**(`maxConnectionsPerEndpoint = 4`)을 라운드 로빈으로 사용하므로, 병렬 쿼리가 헤드 오브 라인 블로킹을 피해요. **유휴 노후화(idle-staleness)** 처리도 포함해요. Cloudflare 같은 프로바이더는 상태 변화를 노출하지 않고 유휴 DoT 연결을 서버 측에서 닫는데(~10초), 그래서 **8초**(`reusedConnectionMaxIdleInterval = 8`)보다 오래 유휴 상태였던 재사용 연결은 전송 전에 새로 고쳐지고, 재사용 연결에서 타임아웃이 나면 **새 연결로 정확히 한 번** 재시도해요.

### 3.4 DoQ — 쿼리마다 새 연결

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`)는 **엔드포인트당 4개 레인**의 제한된 풀을 유지하지만, **각 쿼리는 새 QUIC 연결을 열어요** — 쿼리마다 전체 핸드셰이크예요. 4개 레인 풀은 **동시성**을 제공하지, 핸드셰이크 재사용을 제공하지 않아요.

**DoQ 연결 재사용 상태 (폐기 / 연기됨).** 재사용은 기기에서 검토되고 벤치마크되었으나(35개 쿼리에 걸쳐 34회의 새 핸드셰이크 ≈ 재사용 없음), 이후 iOS 26 게이트된 멀티 스트림 `NWConnectionGroup` 경로로 구현되어 AdGuard DoQ를 상대로 기기 테스트되었고, **순효과 음수로 되돌려졌어요**(실제 서버 대상 스트림 실패 + 폴백 오류). RFC 9250은 각 쿼리를 자체 QUIC 스트림에 매핑하므로 재사용에는 `NWConnectionGroup`/`openStream`이 필요한데, 이는 **iOS 26.0+ 전용**이에요. 현재 배포 최저 버전은 **iOS 17**이에요. 최저 버전이 iOS 26에 도달할 때까지 재사용은 연기돼요. 커스텀 DoQ는 이를 지원하지 않는 기기에서 거부돼요("DNS over QUIC is not supported on this device").

### 3.5 해석 정책

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`)는 상위 정책을 담당해요:

1. **전송 라우팅** — 구성된 전송에 따라.
2. **plain DNS로의 격하** — 암호화 플랜에 엔드포인트가 없을 때.
3. **엔드포인트별 페일오버** — 백오프 게이트와 함께. 백오프된 엔드포인트는 절대 와이어에 닿지 않아요(결과 `backed-off`).
4. **Device-DNS 폴백** — 주 경로가 응답을 반환하지 않고 *그리고* 플랜이 허용할 때(플랜 속성은 `shouldFallbackToDeviceDNS`로, `fallbackToDeviceDNS` 구성 필드에서 파생). 결과는 기기 전송으로 다시 주석 처리돼요. 와이어 실행은 실행기 뒤로 주입되어 정책이 단위 테스트 가능하며, 백오프 상태는 순수 정책 바깥에 머물러요.

---

## 4. 필터 규칙 예산, NE 상한, 그리고 mmap

출시된 등급 지표는 **필터 규칙 예산**이에요. 즉, 사용자가 활성화할 수 있는 컴파일된 도메인 **규칙**의 총합이에요. 이는 기존의 활성 목록 **개수** 상한(무료 3 / 유료 10)을 대체했는데, 그건 정직하지 못한 대리 지표였어요 — 한 목록이 1K일 수도 1M 규칙일 수도 있으니까요. **두 개의 층**이 있어요: 모두에게 적용되는 기기 가드레일, 그리고 그 아래에 있는 등급별 수익화 한도예요.

### 4.1 등급 한도 (구현됨)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`)가 진실의 원천이에요:

| 등급 | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | 커스텀 차단 목록 / DNS |
|---|---|---|---|---|
| **Free** | **500,000** | 25 | 25 | 아니요 |
| **Plus** (`.paid` / `.plus`) | **2,000,000** | 1,000 | 1,000 | 예 |

등급 한도는 수익화 경계이지, **기기 가드레일에 대한 결제 장벽이 결코 아니에요**. **Lava Security Plus**는 커스터마이징만 잠금 해제해요 — 기본 안전이나 위협 가드레일은 절대 아니에요. 커스텀(유료) 차단 목록은 사용자 기기에서 직접 가져와 로컬에서 파싱·캐시되며, 절대 Lava 서버로 프록시되지 않아요.

### 4.2 기기 메모리 가드레일 + NE 상한 (구현됨)

패킷 터널은 iOS의 **확장당 약 50 MiB 메모리 상한**의 적용을 받아요(iOS 15부터 패킷 터널에 적용되는 OS의 확장 유형별 설계 한도이며, RAM에 비례하지 않아요. 이는 기기 모델별 `com.apple.jetsamproperties.{Model}.plist`에 있고 구형 기기에서는 더 낮을 수 있어요). 이를 초과하면 jetsam이 발동돼요. 상한에 대한 API가 없으므로 예산은 그 절벽 아래로 여유를 남겨요.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`)이 계산을 하며, 필터 규칙(차단 + 허용 + 가드레일) 단위로 표시돼요:

| 상수 | 값 |
|---|---|
| `baselineMegabytes` | 4.0 MB (고정 프로세스 오버헤드, 측정값 ≈3.5 MB, 올림) |
| `estimatedBytesPerRule` | 규칙당 9.0 B 더티 상주 메모리(측정값 ≈8.5 B, 올림) |
| `maxResidentMegabytes` | 32.0 MB (목표 상한, 관측된 ~40–46 MB jetsam 절벽 아래로 ~10 MB 여유를 둠) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 규칙** |

이 **약 3.26M 규칙 기기 가드레일**은 *모든* 사용자를 위한 하드 안전 하한이며, 어떤 구독 등급보다도 위에 있고, **결코 결제 장벽이 아니에요**. 앵커 측정(기기 "chimmy", 2026-06-13): **789,831 규칙 → 9.9 MB `phys_footprint`**, 즉 ≈ 기준선 + 규칙당 비용.

### 4.3 mmap 전략 (구현됨)

compact 스냅샷은 `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`)로 로드되며, `CompactBinaryReader`는 제로 카피 슬라이스를 반환해요. 멀티 메가바이트 도메인 텍스트 블롭은 **파일 기반/클린** 상태로 남아 jetsam 집계 대상인 `phys_footprint`에서 제외돼요. 디코딩된 `[Entry]` 테이블만 상주 메모리를 차지해요(디스크에서 ~6 B/규칙, ~8.5 B 더티 상주). 이로써 기기 내 도메인 상한이 올라가요: 상주 비용은 산출물 전체가 아니라 엔트리 테이블이에요.

### 4.4 2층 적용 (구현됨)

- **권위적(컴파일 시점).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`)는 활성화된 모든 목록의 **중복 제거된 합집합**에 예산을 적용해요. 기기 가드레일이 **먼저** 검사되고(하드 하한), 등급 한도는 그 아래에서 적용돼요. 예산 초과 구성은 결정론적으로 거부돼요 — `exceedsDeviceMemoryBudget` 또는 `exceedsTierFilterRuleLimit` — 터널이 jetsam되도록 두는 대신에요. 오류는 가장 크게 기여한 두 목록을 명시해 수정이 명확하도록 해요.
- **권고적(선택 시점 UI).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`)은 목록별 **합계**에 **1.10 소프트 상한 마진**을 적용해 선택 미터를 구동하는데, 이 마진은 목록 간 ~7–10% 과대 집계를 보정해요(목록별 합계는 중복 제거된 합집합을 과대 추정해요).

### 4.5 파서 (구현됨)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`)는 규칙을 문자 그대로 세요: 주석/빈 줄/유효하지 않은 줄을 버리고, 정규화하고, 목록 내에서 정확 문자열을 중복 제거하며(`Set`을 통해), 목록당 **`maxRules = 1,000,000`**(기본값)으로 제한하고, 줄당 최대 길이는 4,096자예요. 지원 형식: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (`auto`는 hosts → dnsmasq → adblock → plain 순으로 시도). 유효한 한 줄 = 하나의 규칙 = 메모리 단위예요.

> **다중 호스트 `hosts` 줄 (파서 규칙 버전 2).** 한 IP를 여러 호스트에 매핑하는 `hosts` 줄(`0.0.0.0 a.com b.com c.com`)은 이제 첫 번째만이 아니라 **모든** 호스트를 각각의 규칙으로 방출해요. `maxRules`는 **규칙별**(줄별이 아니라)로 적용되므로 상한 근처의 다중 호스트 줄이 초과할 수 없어요. 동일한 상위 바이트가 이제 더 많은 규칙을 낼 수 있으므로 파서의 규칙 버전이 **1 → 2**로 올라갔고, 기존 첫-호스트-전용 동작으로 파싱된 오래된 `RuleSetCache` 항목이 무효화됐어요.

### 4.6 다운로드 및 디코드 견고성 (구현됨)

터널과 카탈로그 동기화는 NE 메모리 예산 안에서 실행되므로, 목록 수집은 악의적이거나 잘못된 입력에 대해 강화돼 있어요:

- **스트리밍 다운로드.** `defaultDataFetcher`는 `URLSession.download`를 통해 목록 바이트를 임시 파일로 다운로드하고(피크 메모리 제한), 본문 전체를 RAM에 버퍼링하는 대신 다운로드 후 크기 검사(`maximumBlocklistBytes`)를 해요. 크기 초과 본문은 `BlocklistDownloadSizeLimitExceeded`를 일으켜요.
- **카탈로그 메타데이터 상한 (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes`는 디코드 전에 크기 초과 원격 카탈로그를 거부하므로, 악의적/MITM 호스트가 확장에서 OOM JSON 디코드를 강제할 수 없어요.
- **관대한 UTF-8 디코딩.** 유효하지 않은 단일 UTF-8 바이트 하나가 더 이상 목록 전체를 거부하지 않아요(닫힌-실패 상태에서는 이것이 모든 DNS를 차단했을 거예요). 유효하지 않은 바이트는 U+FFFD가 되고, 문제가 된 줄만 줄별 검증에 실패해 버려져요.
- **이름이 붙은 커스텀 차단 목록 오류.** 실패한 커스텀 목록은 이제 원시 `URLError` 대신 `customBlocklistUnavailable(displayName:reason:)`을 표시해요 — "Couldn't load the custom blocklist '<name>'. <why>" — 취소는 다운로드 실패가 아니라 취소로 전파돼요.

---

## 5. 차단 목록 카탈로그 및 기본 소스

### 5.1 카탈로그 모델 (구현됨)

**차단 목록 카탈로그**는 사용 가능한 소스의 게시된 목록이에요. **lavasec-api Worker**는 R2 버킷에서 `GET /v1/catalog`(및 `/v1/catalog/:version`)로 JSON 메타데이터를 제공하고, 기기는 실제 목록 **바이트**를 각 상위 `source_url`에서 직접 가져와요. iOS 카탈로그 엔드포인트는 `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`)예요.

기기에서 `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`)는:

1. `source.sourceURL`에서 목록 바이트를 직접 가져오며 크기 상한을 적용해요.
2. SHA-256을 계산하고, 체크섬이 카탈로그의 `accepted_source_hashes`에 있을 때만 바이트를 수락해요.
3. 불일치 시 마지막으로 유효했던 로컬 캐시로 폴백하거나, **닫힌 상태로 실패**해요(`checksumMismatch`) — 소스가 직접 상위 회전을 명시적으로 허용하는 경우는 제외하고요.
4. 로컬에서 파싱/정규화/중복 제거해요.
5. 파싱된 모든 규칙 집합을 `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`)로 필터링해, 상위 목록이 절대 Lava/Apple/신원 제공자 도메인을 차단할 수 없게 해요.

**보호 도메인 집합**(활성화 전에 걸러짐): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com`(모두 접미사 매칭). Worker는 메타데이터를 계산할 때 동등한 `PROTECTED_SUFFIXES` 필터를 적용하고, 기기는 그와 무관하게 다시 검증해요.

### 5.2 큐레이션된 소스 (구현됨)

`DefaultCatalog.curatedSources` (`BlocklistModels.swift:232-243`)는 **10개** 소스를 나열해요:

| 소스 | 라이선스 |
|---|---|
| Block List Basic | Unlicense |
| Block List Project Phishing | Unlicense |
| Block List Project Scam | Unlicense |
| Block List Project Ransomware | Unlicense |
| Phishing.Database Active Domains | MIT |
| HaGeZi Multi Light | GPL-3.0 |
| HaGeZi Multi Normal | GPL-3.0 |
| HaGeZi Multi PRO mini | GPL-3.0 |
| HaGeZi Multi PRO | GPL-3.0 |
| OISD Small | GPL-3.0 |

`guardrailSources`는 비어 있어요. GPL 소스(HaGeZi, OISD)는 카탈로그에서 보이지만 자문 승인이 날 때까지 **옵트인 / 기본 OFF**예요. Worker는 출시 동기화/게시를 `source_url_only`와 허용된 GPL 접두사(`hagezi-`/`oisd-`)로 통제해요.

### 5.3 무료 사용자용 기본 활성화 목록 (구현됨)

실제 무료 기본 구성은 `OnboardingDefaults.lavaRecommendedDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`)인데, 이는 **Block List Project Phishing + Block List Project Scam**을 활성화하고, device-DNS 리졸버 프리셋(`resolverPresetID = DNSResolverPreset.device.id`)과 device-DNS 폴백을 켜요.

그 무료 기본값은 하드코딩이 아니라 **`defaultEnabled`로 생성돼요**. `blockListProjectPhishing` (`BlocklistModels.swift:139`)과 `blockListProjectScam` (`BlocklistModels.swift:148`)은 둘 다 `defaultEnabled: true`를 설정하고, `DefaultCatalog.recommendedDefaultSourceIDs` (`BlocklistModels.swift:250-252`)는 `curatedSources.filter(\.defaultEnabled)`에서 파생돼요. 소스 주석(`BlocklistModels.swift:246-249`)은 `defaultEnabled`를 "새 설치 기본값의 유일한 진실의 원천"이라 부르며, 이는 백엔드 카탈로그의 `default_enabled` 열을 반영해요. `recommendedDefaultSourceIDs`를 거쳐 `OnboardingDefaults`로 흐르면서, `defaultEnabled`가 실제 작동 메커니즘이에요 — 소스의 플래그를 뒤집어 기본값을 바꿔요.

> **기본값 진실의 원천 (코드가 우선).** "Block List Basic이 유일한 기본값"이라고 말하는 계획/카탈로그 문구는 기기에 대해서는 틀렸어요. 기기는 `defaultEnabled: true`에 따라 Phishing + Scam을 출시하며, iOS `BlocklistSource.defaultEnabled` 플래그가 권위 있는 실제 메커니즘이에요. 백엔드 카탈로그의 `default_enabled` 열은 마이그레이션으로 동일한 Phishing + Scam 집합에 맞춰졌으므로, 제공되는 `/v1/catalog` 메타데이터는 이제 클라이언트와 일치해요. 공개 사이트의 "Enabled blocklists 3 → 10" 문구는 여전히 **오래된** 것이에요 — 실제 게이트는 목록 개수가 아니라 500K/2M 필터 규칙 예산이에요.

### 5.4 소스 URL 전용 GPL 배포 모델 (구현됨)

**소스 URL 전용**은 GPL/지식재산권 준수 배포 모델이에요: Lava는 상위 URL + 수락된 해시만 게시하고, 기기가 직접 목록을 가져와 파싱해요. Lava는 제3자 차단 목록 바이트를 **절대** 저장, 미러링, 변환, 제공하지 않아요. 이는 **폐기된 R2 미러 설계를 대체했어요**(원래의 "원시 R2 미러" 계획은 2026-05-25에 되돌려졌어요).

Worker 측에서 `syncOneBlocklist`는 각 상위 소스를 가져와 정규화+해싱(`source_hash`, `normalized_hash`, `entry_count` 계산)하지만 `raw_r2_key = null` / `normalized_r2_key = null`을 기록해요 — 카탈로그 JSON 메타데이터만 R2에 도달해요. `check-gpl-blocklist-distribution.sh`는 전체 모델을 강제하는 CI 가드레일이에요: 미러/변환 코드 없음, Lava 산출물/다운로드 URL 없음, GPL 소스 기본 활성화 없음, Worker의 목록 바이트 R2 기록 없음, "Lava 호스팅 미러" 문구 없음, 번들된 GPL `.txt`/`.json` 없음, 그리고 마이그레이션 + 법무 문서에 `source_url_only` 필수.

> **라이선스 참고:** 퍼스트파티 Lava 코드는 **AGPL-3.0**으로 출시돼요(`LICENSE` 파일은 GNU AGPL v3이며 README 배지와 일치). 제3자 차단 목록(HaGeZi, OISD)은 각자의 상위 라이선스에 따라 **GPL-3.0**을 유지해요 — 소스 URL 전용 모델은 Lava가 GPL 라이선스 바이트를 절대 재배포하지 않으면서 이를 사용할 수 있도록 바로 그 목적으로 존재해요. 여기서 GPL-3.0은 상위 목록의 속성이지, Lava 앱의 속성이 아니에요.

---

## 6. 상태 요약

| 영역 | 상태 |
|---|---|
| DNS 쿼리 우선순위 (bootstrap > pause > filter) | 구현됨 |
| 필터 결정 우선순위 (guardrail > allowlist > blocklist > default-allow) | 구현됨 |
| 위협 가드레일 우선순위 슬롯 (연결됨; 아직 항목 없이 출시) | 구현됨 |
| DoH / DoH3 (관측 기반 h3 라벨) | 구현됨 |
| DoT (엔드포인트당 4개 풀, 8초 유휴 새로 고침, 새 연결 한 번 재시도) | 구현됨 |
| DoQ (쿼리마다 새 연결, 4레인 동시성) | 구현됨 |
| DoQ 연결 재사용 | 폐기 / iOS 26 최저 버전까지 연기 |
| 리졸버 격하 + 엔드포인트별 페일오버 + device-DNS 폴백 | 구현됨 |
| 필터 규칙 예산 (Free 500K / Plus 2M) | 구현됨 |
| ~3.26M 규칙 기기 가드레일 (50 MiB NE 상한 아래 32 MB 목표) | 구현됨 |
| compact 스냅샷의 제로 카피 mmap | 구현됨 |
| 소스 URL 전용 카탈로그 + 직접 상위 가져오기 + 해시 검증 | 구현됨 |
| 보호 도메인 필터 | 구현됨 |
| 무료 기본값 = Phishing + Scam (Basic 아님) | 구현됨 (카탈로그가 맞춰 정렬됨) |
| 퍼스트파티 Lava 코드 라이선스 | AGPL-3.0 (`LICENSE`); 제3자 목록은 상위에서 GPL-3.0 유지 |

---

## 참고

- [`../product/overview.md`](../product/overview.md) — 제품 한 줄 소개, 프라이버시 약속, 탭.
- 등급 및 수익화(내부 참고) — Lava Security Plus와 등급 지표로서의 필터 규칙 예산.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — 소스 URL 전용 준수 결정.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — 상위 차단 목록/리졸버 라이선스 및 출처 표시.
