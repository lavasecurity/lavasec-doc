---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# DNS 필터링 및 차단 목록

> 대상 독자: 엔지니어. 이 문서는 기기 내 DNS 파이프라인, 암호화 전송 리졸버 경로, 필터링 결정 엔진, 그리고 source-url 전용 차단 목록 카탈로그 모델을 코드가 적용하는 정확한 수치와 함께 설명해요. 상태는 코드로 확인된 실제 현황을 반영해요. 계획과 코드가 어긋나는 경우 **코드가 우선**하며, 그 차이는 본문에 함께 표시해요.

모든 DNS 필터링은 기기에서 이루어져요. Lava는 사용자의 인터넷 사용을 자사 서버로 경유시키지 않으며, 방문한 도메인의 흐름도 받지 않아요. 백엔드는 카탈로그 메타데이터, 사용자별 암호화된 불투명 백업, 그리고 사용자가 보내기로 선택한 익명 진단 정보만 보관해요.

Lava는 **기기 내 DNS/차단 목록 필터링**이며, 모든 악성 도메인이나 URL을 빠짐없이 차단한다는 보장은 아니에요.

---

## 1. DNS 파이프라인 (구현됨)

필터/리졸브 엔진은 **NE / 패킷 터널** 안에서 실행돼요. DNS만 가로채는 `NEPacketTunnelProvider` 확장 `LavaSecTunnel`(`com.lavasec.app.tunnel`)이에요. 터널 주소는 `10.255.0.2`(터널)와 `10.255.0.1`(DNS 서버)예요. 앱 프로세스는 쿼리 트래픽을 전혀 보지 않아요. 컴파일된 산출물을 **App Group**(`group.com.lavasec`)에 기록하고, NETunnelProviderSession **provider message**(Darwin 알림이 아님)로 터널에 신호를 보낼 뿐이에요.

들어오는 각 DNS 쿼리에 대해 터널은 `DNSQueryDispatcher`(`Sources/LavaSecCore/DNSQueryDispatcher.swift`)에서 고정된 **쿼리 우선순위**를 적용해요:

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap 우선은 깨질 수 없는 불변식이에요.** 구성된 리졸버 *자신의* 호스트명(DoH/DoT/DoQ 엔드포인트)을 해석하는 쿼리는 절대 차단되거나 일시 중지되어서는 안 돼요. 그렇지 않으면 터널이 암호화 DNS를 아예 띄울 수 없어요. 디스패처는 지연 클로저를 받아 각 단계가 도달했을 때만 읽히도록 해서 단락 평가를 보존해요(bootstrap 응답이 있으면 스냅샷을 읽지 않고, bootstrap 중에는 pause를 읽지 않음).
- **temporary pause**는 사용자가 시작한 일시 중지 TTL이 활성인 동안 상위로 전달해요.
- **filter**는 도메인을 컴파일된 스냅샷에 대조해 전달하거나 차단 응답을 합성해요.

필터를 통과한 쿼리(액션 `.allow`)는 리졸버 경로(§3)로 넘겨져요. 재사용 가능한 스냅샷 없이 콜드 스타트가 일어나면 터널은 **닫힌 상태로 동작해요(fail closed)**. 즉 필터링 없이 해석하는 대신 모든 트래픽을 차단하는 fail-closed 런타임 스냅샷을 설치해요.

---

## 2. 필터링 엔진 (구현됨)

### 2.1 결정 우선순위

`FilterSnapshot.decision(forNormalizedDomain:)`(`Sources/LavaSecCore/FilterSnapshot.swift:57-71`)는 표준 안전 우선순위를 적용해요:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| 순서 | 규칙 집합 | 결과 | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | 차단 | `.threatGuardrail` |
| 2 | `allowRules` | 허용 | `.localAllowlist` |
| 3 | `blockRules` | 차단 | `.blocklist` |
| 4 | — | 허용 | `.defaultAllow` |

정규화에 실패한 도메인은 `.invalidDomain` 사유로 차단돼요(fail-safe). 동일한 우선순위가 디스크상의 바이너리 형식(`CompactFilterSnapshot`)에도 그대로 반영돼요. threat guardrail이 로컬 allowlist보다 위에 놓인 것은 의도된 설계예요. **결제는 non-allowable threat guardrail을 절대 우회하지 못하며**, 사용자 예외 처리로 guardrail 도메인의 차단을 해제할 수 없어요.

> Note: 현재 작업 트리에서 `nonAllowableThreatRules` / `guardrailSources`는 비어 있어요(`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`). 우선순위 슬롯은 연결되어 적용되지만, 아직 guardrail 항목 없이 출시돼요.

### 2.2 규칙 저장과 상주 메모리 단위

`DomainRuleSet`(`Sources/LavaSecCore/DomainRuleSet.swift`)은 `exactDomains` + `suffixDomains` 집합을 저장해요. 매칭(`containsNormalized`)은 쿼리 시점에 정확 조회와 상위 접미사 탐색(`hasSuffix` 방식)을 함께 수행해요. **컴파일 시점에 하위 도메인 포섭은 없어요.** 유효한 와일드카드 한 줄은 **하나의 규칙**이며 메모리 테이블의 한 항목이에요. 이 '1줄 = 1규칙' 동일성 덕분에 규칙 수가 정직한 자원 지표가 돼요(§4).

### 2.3 컴파일된 스냅샷 형식

- **`FilterSnapshot`** — 메모리상의 컴파일된 필터: `blockRules`, `allowRules`, `nonAllowableThreatRules`, 그리고 리졸버 프리셋.
- **`CompactFilterSnapshot`** — 터널이 실제로 읽는 바이너리, mmap 친화적 디스크 형식(매직 `LSCFSNP1`, `fileVersion 1`). mmap을 통해 zero-copy로 로드돼요(§4.3).

앱은 `filter-snapshot.json`과 `filter-snapshot.compact`를 모두 App Group에 기록하고, 터널은 compact 산출물을 디코딩해요. **웜 스타트업 재사용** 경로(`FilterArtifactStore`)는 터널이 재컴파일 없이 디스크상의 compact 산출물을 재사용하게 해주며, 식별 지문(fingerprint)과 원자적으로 기록된 매니페스트로 게이트돼요. 리졸버 전송 방식, 카탈로그 커버리지, 또는 스냅샷 입력이 바뀌면 재사용은 거부돼요(개인정보에 안전한 필드명만 사유로 남김).

---

## 3. 암호화 전송과 리졸버 경로 (구현됨)

### 3.1 전송 enum

차단되지 않은 쿼리는 구성된 상위 리졸버로 전달돼요. `DNSResolverTransport`(`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`)에는 **다섯** 가지 값이 있어요:

| 전송 방식 | Raw value | UI에 표시되는 표기 |
|---|---|---|
| Device DNS | `device-dns` | *(없음 — 이름 자체가 전송 방식)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

기본 제공 프리셋은 Google, Cloudflare, Quad9, Mullvad(각각 IP / DoH / DoT 변형)와 Device DNS, Custom이에요. Custom 리졸버는 일반 IPv4/IPv6 서버, DoH URL, DoT URL(`tls://` / `dot://`), DoQ URL(`doq://` / `quic://`), 또는 `sdns://` DNS 스탬프를 받아요. 사용자명/비밀번호와 localhost는 거부돼요. DoH/DoT/DoQ는 DoT/DoQ의 경우 기본 포트 `853`을 쓰고, DoH는 경로가 필요해요.

### 3.2 DoH / DoH3

`DoHTransport`(`Sources/LavaSecCore/DoHTransport.swift`)는 `URLSession`으로 DoH를 실행해요. 모든 요청은 HTTP/3을 선택해요(`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`). Apple의 로더가 자체적으로 H2/H1로 폴백하므로, 이 설정 때문에 도달 가능한 리졸버가 도달 불가능해지는 일은 없어요. 협상된 프로토콜은 `URLSessionTaskTransactionMetrics.networkProtocolName`(ALPN: `h3`, `h2`, `http/1.1`)에서 읽어요.

UI는 **h3 협상이 실제로 관측될 때만** **`DoH3`(슬래시 없음)** 으로 표기해요. 예: "Quad9 (DoH3)"(`DoHHTTPVersion.dohAnnotation`). 그 외에는 `DoH`로 표시해요. DoH3은 선호되지만 약속되지는 않아요. 라벨은 관측 기반이며 리졸버 범위 안에서만 유효하고, 영속화되지 않아요(재시작 시 "confirmed DoH3" 이월은 되돌려졌어요). 요청은 `application/dns-message`를 POST하고, 응답은 content-type과 길이를 검증한 뒤 쓰기 전에 트랜잭션 ID를 복원해요.

### 3.3 DoT

`DoTTransport`(`Sources/LavaSecCore/DoTTransport.swift`)는 풀링된 `NWConnection`을 사용해요. **엔드포인트당 최대 4개 연결**(`maxConnectionsPerEndpoint = 4`)을 라운드 로빈으로 써서 병렬 쿼리가 head-of-line 블로킹을 피하도록 해요. **유휴 만료(idle-staleness)** 처리도 포함해요. Cloudflare 같은 제공자는 유휴 DoT 연결을 서버 측에서(약 10초) 상태 변화 노출 없이 닫는데, **8초**(`reusedConnectionMaxIdleInterval = 8`)보다 오래 유휴 상태였던 재사용 연결은 전송 전에 갱신하고, 재사용 연결에서 타임아웃이 나면 **정확히 한 번** 새 연결로 재시도해요.

### 3.4 DoQ — 쿼리마다 새 연결

`DoQTransport`(`Sources/LavaSecCore/DoQTransport.swift`)는 **엔드포인트당 4개 레인**의 제한된 풀을 유지하지만, **각 쿼리는 새 QUIC 연결을 열어요** — 쿼리마다 전체 핸드셰이크예요. 4레인 풀은 **동시성을 제공할 뿐, 핸드셰이크 재사용은 아니에요.**

**DoQ 연결 재사용 상태 (취소 / 보류).** 재사용은 기기에서 검토 및 벤치마크되었고(35개 쿼리에 걸쳐 34번의 새 핸드셰이크 ≈ 재사용 없음), 이후 iOS 26 게이트의 다중 스트림 `NWConnectionGroup` 경로로 구현되어 AdGuard DoQ를 상대로 기기 테스트되었으나, **순효과가 마이너스로 판단되어 되돌려졌어요**(실제 서버 상대로 스트림 실패 + 폴백 오류). RFC 9250은 각 쿼리를 자체 QUIC 스트림에 매핑하므로, 재사용에는 `NWConnectionGroup`/`openStream`이 필요하고, 이는 **iOS 26.0+ 전용**이에요. 현재 배포 최저 기준은 **iOS 17**이에요. 재사용은 최저 기준이 iOS 26에 도달할 때까지 보류돼요. Custom DoQ는 지원하지 않는 기기에서는 거부돼요("DNS over QUIC is not supported on this device").

### 3.5 해석 정책

`ResolverOrchestrator`(`Sources/LavaSecCore/ResolverOrchestrator.swift`)가 상위 정책을 담당해요:

1. 구성된 전송 방식에 따른 **전송 라우팅**.
2. 암호화 플랜에 엔드포인트가 없을 때 **plain DNS로 강등**.
3. 백오프 게이트를 둔 **엔드포인트별 페일오버** — 백오프된 엔드포인트는 회선에 절대 닿지 않아요(결과 `backed-off`).
4. 기본(primary) 리졸버가 응답을 반환하지 않고 *동시에* 플랜이 허용할 때 **Device DNS 폴백**(플랜 속성 `shouldFallbackToDeviceDNS`, 구성 필드 `fallbackToDeviceDNS`에서 파생). 결과는 device 전송 방식으로 다시 표기돼요. 회선 실행은 실행기(executor) 뒤에 주입되어 정책을 단위 테스트할 수 있고, 백오프 상태는 순수 정책 바깥에 머물러요.

---

## 4. 필터 규칙 예산, NE 상한, mmap

출시된 등급 지표는 **필터 규칙 예산**이에요. 사용자가 활성화할 수 있는 컴파일된 도메인 **규칙**의 총합이에요. 이는 예전의 활성 목록 **개수** 상한(무료 3 / 유료 10)을 대체했어요. 한 목록이 1천 개일 수도 100만 개일 수도 있으니 개수 상한은 정직하지 못한 대용 지표였어요. **두 개의 층**이 있어요. 모든 사용자에게 공통인 기기 guardrail과, 그 아래에 놓인 등급별 수익화 한도예요.

### 4.1 등급 한도 (구현됨)

`FeatureLimits`(`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`)가 단일 진실 공급원이에요:

| 등급 | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | 커스텀 차단 목록 / DNS |
|---|---|---|---|---|
| **Free** | **500,000** | 10 | 10 | 불가 |
| **Plus** (`.paid` / `.plus`) | **2,000,000** | 500 | 500 | 가능 |

등급 한도는 수익화 경계일 뿐, **기기 guardrail에 대한 유료 장벽은 절대 아니에요.** **Lava Security Plus**는 커스터마이즈만 풀어줘요. 기본 안전이나 threat guardrail은 절대 아니에요. 커스텀(유료) 차단 목록은 사용자 기기에서 직접 가져와 로컬에서 파싱·캐시되며, Lava 서버로 절대 프록시되지 않아요.

### 4.2 기기 메모리 guardrail + NE 상한 (구현됨)

패킷 터널은 iOS의 **확장당 약 50 MiB 메모리 상한**의 적용을 받아요(iOS 15부터 패킷 터널에 적용된 확장 유형별 OS 설계 한도이며, RAM에 비례하지 않아요. 기기 모델별 `com.apple.jetsamproperties.{Model}.plist`에 들어 있고 구형 기기에서는 더 낮을 수 있어요). 이를 초과하면 jetsam이 발동돼요. 상한을 알려주는 API가 없으므로, 예산은 한계 직전에 여유를 남겨요.

`FilterSnapshotMemoryBudget`(`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`)가 필터 규칙(block + allow + guardrail) 단위로 계산해요:

| 상수 | 값 |
|---|---|
| `baselineMegabytes` | 4.0 MB (고정 프로세스 오버헤드, 측정값 ≈3.5 MB, 올림) |
| `estimatedBytesPerRule` | 규칙당 9.0 B dirty resident (측정값 ≈8.5 B, 올림) |
| `maxResidentMegabytes` | 32.0 MB (목표 상한, 관측된 ~40–46 MB jetsam 한계 아래로 ~10 MB 여유 확보) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 규칙** |

이 **약 326만 규칙 기기 guardrail**은 *모든* 사용자에게 적용되는 강제 안전 하한이며, 어떤 구독 등급보다 위에 있고 **유료 장벽이 절대 아니에요.** 기준 측정(기기 "chimmy", 2026-06-13): **789,831 규칙 → 9.9 MB `phys_footprint`**, 즉 ≈ baseline + 규칙당 비용.

### 4.3 mmap 전략 (구현됨)

compact 스냅샷은 `Data(contentsOf:options:[.mappedIfSafe])`(`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`)로 로드되며, `CompactBinaryReader`는 zero-copy 슬라이스를 반환해요. 수 메가바이트에 이르는 도메인 텍스트 블롭은 **파일 기반/clean** 상태로 남아 jetsam이 집계하는 `phys_footprint`에서 제외돼요. 상주 메모리를 차지하는 것은 디코딩된 `[Entry]` 테이블뿐이에요(디스크상 ~6 B/규칙, dirty resident ~8.5 B). 덕분에 기기 내 도메인 상한이 올라가요. 상주 비용은 산출물 전체가 아니라 엔트리 테이블이에요.

### 4.4 두 층 적용 (구현됨)

- **권위적 적용(컴파일 시점).** `FilterSnapshotPreparationService`(`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`)는 활성화된 모든 목록의 **중복 제거된 합집합**에 예산을 적용해요. 기기 guardrail을 **먼저** 확인하고(강제 하한), 등급 한도는 그 아래에서 묶여요. 예산을 초과하는 구성은 터널이 jetsam되게 두지 않고 결정적으로 거부돼요 — `exceedsDeviceMemoryBudget` 또는 `exceedsTierFilterRuleLimit`. 오류는 가장 크게 기여한 두 목록을 명시해서 해결책이 분명하도록 해요.
- **권고적 적용(선택 시점 UI).** `FilterRuleBudget`(`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`)는 목록별 **합**에 **1.10 소프트 상한 여유**를 적용해 선택 미터를 구동해요. 이 여유는 ~7–10%의 목록 간 중복 과대 집계를 보정해요(목록별 합은 중복 제거된 합집합을 과대 추정함).

### 4.5 파서 (구현됨)

`BlocklistParser`(`Sources/LavaSecCore/BlocklistParser.swift`)는 규칙을 문자 그대로 세요. 주석/빈 줄/잘못된 줄을 버리고, 정규화하고, 목록 내 정확 문자열을 중복 제거하고(`Set` 사용), 목록당 **`maxRules = 1,000,000`**(기본값)에서 상한을 두며, 최대 줄 길이는 4,096자예요. 지원 형식: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq`(auto는 hosts → dnsmasq → adblock → plain 순으로 시도). 유효한 한 줄 = 하나의 규칙 = 메모리 단위예요.

---

## 5. 차단 목록 카탈로그와 기본 소스

### 5.1 카탈로그 모델 (구현됨)

**차단 목록 카탈로그**는 사용 가능한 소스의 게시된 목록이에요. **lavasec-api Worker**는 R2 버킷에서 `GET /v1/catalog`(및 `/v1/catalog/:version`)으로 JSON 메타데이터를 제공해요. 기기는 실제 목록 **바이트**를 각 상위 `source_url`에서 직접 가져와요. iOS 카탈로그 엔드포인트는 `https://api.lavasecurity.app/v1/catalog`(`BlocklistCatalogSync.swift:4-15`)예요.

기기에서 `BlocklistCatalogSynchronizer`(`BlocklistCatalogSync.swift`)는:

1. `source.sourceURL`에서 목록 바이트를 직접 가져오며 크기 상한을 적용해요.
2. SHA-256을 계산하고, 체크섬이 카탈로그의 `accepted_source_hashes`에 있을 때만 바이트를 받아들여요.
3. 불일치 시 마지막으로 정상이었던 로컬 캐시로 폴백하거나, **닫힌 상태로 동작해요**(`checksumMismatch`) — 소스가 직접 상위 로테이션을 명시적으로 허용하지 않는 한.
4. 로컬에서 파싱/정규화/중복 제거를 해요.
5. 파싱된 모든 규칙 집합을 `DomainRuleSet.lavaSecProtectedDomains`(`AppConfiguration.swift:262-276`)로 필터링해서, 상위 목록이 Lava/Apple/신원 제공자 도메인을 절대 차단하지 못하도록 해요.

**보호 도메인 집합**(활성화 전에 걸러냄): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com`(모두 접미사 매칭). Worker는 메타데이터를 계산할 때 동등한 `PROTECTED_SUFFIXES` 필터를 적용하고, 기기는 그와 무관하게 다시 검증해요.

### 5.2 큐레이트된 소스 (구현됨)

`DefaultCatalog.curatedSources`(`BlocklistModels.swift:232-243`)는 **10**개 소스를 나열해요:

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

`guardrailSources`는 비어 있어요. GPL 소스(HaGeZi, OISD)는 카탈로그에는 보이지만 법무 승인 전까지 **선택 가입 / 기본 OFF**예요. Worker는 출시 동기화/게시를 `source_url_only` 및 허용된 GPL 접두사(`hagezi-`/`oisd-`)로 게이트해요.

### 5.3 무료 사용자 기본 활성화 목록 (구현됨)

실제 무료 기본 구성은 `OnboardingDefaults.lavaRecommendedDefaults`(`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`)이며, **Block List Project Phishing + Block List Project Scam**을 활성화하고, Device DNS 리졸버 프리셋(`resolverPresetID = DNSResolverPreset.device.id`)과 Device DNS 폴백을 켜요.

이 무료 기본값은 **`defaultEnabled`로 산출돼요.** 하드코딩되지 않았어요. `blockListProjectPhishing`(`BlocklistModels.swift:139`)와 `blockListProjectScam`(`BlocklistModels.swift:148`)은 둘 다 `defaultEnabled: true`로 설정되고, `DefaultCatalog.recommendedDefaultSourceIDs`(`BlocklistModels.swift:250-252`)는 `curatedSources.filter(\.defaultEnabled)`에서 파생돼요. 소스 주석(`BlocklistModels.swift:246-249`)은 `defaultEnabled`를 "새 설치 기본값의 단일 진실 공급원"이라 부르며, 백엔드 카탈로그의 `default_enabled` 열을 그대로 반영해요. `recommendedDefaultSourceIDs`를 거쳐 `OnboardingDefaults`로 흐르는 `defaultEnabled`가 실제 동작 메커니즘이에요. 소스의 플래그를 뒤집으면 기본값이 바뀌어요.

> **기본값 진실 공급원(코드 우선).** "Block List Basic이 유일한 기본값"이라고 말하는 계획/카탈로그 문구는 기기 기준으로는 틀려요. 기기는 `defaultEnabled: true`에 따라 Phishing + Scam을 출시하며, iOS `BlocklistSource.defaultEnabled` 플래그가 권위 있는 실제 동작 메커니즘이에요. 백엔드 카탈로그의 `default_enabled` 열은 마이그레이션으로 동일한 Phishing + Scam 집합에 맞춰 재정렬되어, 이제 제공되는 `/v1/catalog` 메타데이터가 클라이언트와 일치해요. 공개 사이트의 "활성 차단 목록 3 → 10" 문구는 여전히 **오래된 내용**이에요 — 실제 게이트는 목록 개수가 아니라 500K/2M 필터 규칙 예산이에요.

### 5.4 source-url 전용 GPL 배포 모델 (구현됨)

**source-url 전용**은 GPL/IP 준수 배포 모델이에요. Lava는 상위 URL과 허용 해시만 게시하고, 기기가 직접 목록을 가져와 파싱해요. Lava는 제3자 차단 목록 바이트를 **절대** 저장·미러링·변환·제공하지 않아요. 이는 **폐기된 R2 미러 설계를 대체했어요**(원래의 "raw R2 mirror" 계획은 2026-05-25에 되돌려졌어요).

Worker 측에서 `syncOneBlocklist`는 각 상위 소스를 가져와 정규화하고 해시를 계산하지만(`source_hash`, `normalized_hash`, `entry_count` 산출), `raw_r2_key = null` / `normalized_r2_key = null`로 기록해요 — R2에는 카탈로그 JSON 메타데이터만 들어가요. `check-gpl-blocklist-distribution.sh`는 모델 전체를 강제하는 CI 가드레일이에요: 미러/변환 코드 금지, Lava 산출물/다운로드 URL 금지, 기본 활성화된 GPL 소스 금지, Worker의 목록 바이트 R2 쓰기 금지, "Lava 호스팅 미러" 문구 금지, 번들된 GPL `.txt`/`.json` 금지, 그리고 마이그레이션 + 법무 문서에 `source_url_only` 필수.

> **라이선스 참고:** Lava의 자체(first-party) 코드는 **AGPL-3.0**으로 출시돼요(`LICENSE` 파일은 GNU AGPL v3로, README 배지와 일치). 제3자 차단 목록(HaGeZi, OISD)은 각자의 상위 라이선스에 따라 **GPL-3.0**으로 남아요 — source-url 전용 모델은 바로 Lava가 GPL 라이선스 바이트를 절대 재배포하지 않으면서도 이들을 사용할 수 있도록 존재해요. 여기서 GPL-3.0은 상위 목록의 속성이지 Lava 앱의 속성이 아니에요.

---

## 6. 상태 요약

| 영역 | 상태 |
|---|---|
| DNS 쿼리 우선순위 (bootstrap > pause > filter) | 구현됨 |
| 필터 결정 우선순위 (guardrail > allowlist > blocklist > default-allow) | 구현됨 |
| Threat-guardrail 우선순위 슬롯 (연결됨; 아직 항목 없이 출시) | 구현됨 |
| DoH / DoH3 (관측 기반 h3 라벨) | 구현됨 |
| DoT (엔드포인트당 4, 8초 유휴 갱신, 한 번 새 재시도) | 구현됨 |
| DoQ (쿼리마다 새 연결, 4레인 동시성) | 구현됨 |
| DoQ 연결 재사용 | 취소 / iOS 26 최저 기준까지 보류 |
| 리졸버 강등 + 엔드포인트별 페일오버 + Device DNS 폴백 | 구현됨 |
| 필터 규칙 예산 (Free 500K / Plus 2M) | 구현됨 |
| 약 326만 규칙 기기 guardrail (50 MiB NE 상한 아래 32 MB 목표) | 구현됨 |
| compact 스냅샷의 zero-copy mmap | 구현됨 |
| source-url 전용 카탈로그 + 상위 직접 가져오기 + 해시 검증 | 구현됨 |
| 보호 도메인 필터 | 구현됨 |
| 무료 기본값 = Phishing + Scam (Basic 아님) | 구현됨 (카탈로그를 맞춰 재정렬) |
| Lava 자체 코드 라이선스 | AGPL-3.0 (`LICENSE`); 제3자 목록은 상위 GPL-3.0 유지 |

---

## 함께 보기

- [`../product/overview.md`](../product/overview.md) — 제품 한 줄 소개, 개인정보 약속, 탭.
- 등급 및 수익화 (내부 참고) — 등급 지표로서의 Lava Security Plus와 필터 규칙 예산.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — source-url 전용 준수 결정.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — 상위 차단 목록/리졸버 라이선스 및 출처 표기.
