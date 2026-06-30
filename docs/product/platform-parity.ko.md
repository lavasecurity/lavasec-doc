# 플랫폼 패리티

Lava의 플랫폼 패리티 시스템은 어떤 제품 약속이 iOS, Android, 그리고 향후
클라이언트 전반에서 공유되는지를 추적합니다. 이는 기능 동작에 대한 공개
계약입니다. 즉 어디서나 동일한 의미여야 하는 것, 의도적으로 플랫폼 네이티브인
것, 그리고 아직 약속되지 않은 것이 무엇인지를 정의합니다.

패리티 문서는 구현 계획이나 테스트를 대체하지 않습니다.

- `lavasec-doc`은 제품 및 동작 계약을 소유합니다.
- 내부 계획은 전달 상태, 순서, 비공개 위험, 그리고 이사회 동기화를
  소유합니다.
- 플랫폼 저장소는 동작을 입증하는 코드, 픽스처, 테스트를 소유합니다.

문서와 출시된 코드가 일치하지 않을 때는 문서가 갱신될 때까지 코드가 우선합니다.
계획과 이 페이지가 일치하지 않을 때는 이 페이지를 제품 계약으로,
계획을 작업 대기열로 취급하십시오.

## 상태 용어

| Status | Meaning |
|---|---|
| **Shipped** | 해당 플랫폼의 프로덕션 코드에 구현됨. |
| **Partial** | 일부 동작은 존재하지만 공개 계약이 완전히 충족되지는 않음. |
| **Planned** | 플랫폼 계약의 일부로 승인되었으나 아직 구현되지 않음. |
| **Deferred** | 유효한 기능이지만 다음 플랫폼 마일스톤에는 필요하지 않음. |
| **Platform-native** | 동일한 사용자 약속, OS별로 다른 구현. |
| **Not applicable** | 해당 플랫폼에 동등한 기능이 존재해서는 안 됨. |
| **Dropped** | 이전에 고려되거나 구축되었으나 의도적으로 제거됨. |

## 기능 레코드 형식

패리티 추적 대상 기능은 모두 안정적인 기능 id를 가져야 합니다. UI 문구
변경에도 살아남는 `area.capability` 형식의 이름을 사용하십시오. 예를 들어
`filtering.guardrail-precedence` 또는 `dns.encrypted-transports`처럼 작성합니다.

완전한 기능 레코드는 다음 항목에 답합니다.

| Field | Purpose |
|---|---|
| `feature_id` | 계획, PR, 테스트, 문서에서 사용하는 안정적인 id. |
| Product promise | 사용자가 의존할 수 있는 것을 플랫폼 중립적 언어로 표현. |
| Parity requirement | Android가 iOS를 정확히 일치시켜야 하는지, 의도로 일치시켜야 하는지, 의도적으로 다르게 유지하는지. |
| Platform status | iOS, Android, 향후 클라이언트 상태. |
| Enforcement | 동작을 정직하게 유지하는 테스트, 픽스처, 소스 파일, 또는 리뷰 검사. |
| Platform notes | 나중에 재발견되지 않고 명시적이어야 하는 OS별 차이. |

## 업데이트 워크플로

1. 변경이 제품 약속, 개인정보 보호 주장, 등급 경계, 또는 크로스 플랫폼
   동작을 바꿀 때 기능 id를 추가하거나 업데이트하십시오.
2. 작업이 필요할 때 구현 계획에서 동일한 기능 id를 링크하십시오.
3. 일치해야 하는 동작에 대해 플랫폼 테스트 또는 골든 픽스처를 추가하거나 업데이트하십시오.
4. 플랫폼이 동작을 출시하면 여기에서 상태를 업데이트하고 관련
   기능 또는 아키텍처 페이지를 갱신하십시오.
5. 구현 전용, 비공개, 가격, 법적 위험, 운영상의 내부 세부사항은
   비공개로 유지하고, 여기에는 공개 계약만 요약하십시오.

## 현재 패리티 원장

| Feature id | Product promise | iOS | Android | Parity requirement | Enforcement / source |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava는 기기에서 로컬로 DNS를 필터링하며 브라우징을 Lava 서버로 프록시하지 않습니다. | Shipped | Planned | 의도로 일치; OS 터널 API가 다름. | iOS 패킷 터널 아키텍처; Android `VpnService` 계획. |
| `protection.vpn-disclosure` | 앱은 VPN 권한/구성을 요청하기 전에 OS가 로컬 DNS 필터링을 VPN이라고 부르는 이유를 설명합니다. | Shipped | Planned | 플랫폼 네이티브 문구 및 권한 흐름. | 온보딩 문서; Android Play 공개 계획. |
| `filtering.guardrail-precedence` | 상시 가드레일은 사용자 허용 목록보다 우선하며, 유료 상태는 가드레일을 절대 우회하지 않습니다. | Shipped | Planned | 정확한 동작 패리티. | `CompactFilterSnapshotTests`; 이식 시 Android `FilterSnapshotTest`. |
| `filtering.source-url-only-catalog` | Lava는 서드파티 차단 목록 바이트가 아니라 카탈로그 메타데이터와 업스트림 소스 URL을 게시합니다. | Shipped | Planned | 정확한 개인정보 보호/지식재산 모델 패리티. | 카탈로그 아키텍처; GPL/source-url-only 법률 문서. |
| `filtering.on-device-parsing` | 선택된 목록은 기기에서 가져와 파싱되며, 일상적인 도메인 기록은 Lava에 업로드되지 않습니다. | Shipped | Planned | 정확한 개인정보 보호 패리티, 네이티브 저장소 허용. | `BlocklistParserTests`; 이식 시 Android 파서 패리티 테스트. |
| `filtering.rule-budget` | 필터 한도는 임의의 목록 개수가 아니라 컴파일된 규칙 수와 기기 안전성을 기반으로 합니다. | Shipped | Planned | 동일한 사용자 대면 모델; 플랫폼 메모리 상한은 다를 수 있음. | iOS 필터 예산 테스트; 기기 한도가 알려질 때 Android 예산 테스트. |
| `dns.built-in-resolvers` | 사용자는 허용된 조회를 Lava로 보내지 않고 내장 리졸버 프리셋을 선택할 수 있습니다. | Shipped | Planned | 동일한 리졸버 정책; 프리셋 세트는 단계적으로 출시될 수 있음. | 리졸버 프리셋 테스트; 이식 시 Android 리졸버 DTO 테스트. |
| `dns.encrypted-transports` | 허용된 쿼리에 대해 암호화된 업스트림 DNS를 사용할 수 있습니다. | Shipped | Planned | 단계적 패리티 허용; Android v1은 DoT/DoQ 이전에 DoH로 시작할 수 있음. | iOS 전송 테스트; Android 리졸버 테스트 및 기기 QA. |
| `reports.local-only-diagnostics` | 사용자가 명시적으로 지원 번들을 보내지 않는 한 보고서와 진단은 로컬에 머무릅니다. | Shipped | Planned | 정확한 개인정보 보호 패리티; UI는 다를 수 있음. | 버그 보고 번들 테스트; 구축 시 Android 디버그 보고 미리보기 테스트. |
| `account.optional-sign-in` | 보호 기능은 계정 없이 작동하며, 로그인은 선택 사항입니다. | Shipped | Deferred | Android가 계정 기능을 노출하기 전 정확한 제품 약속. | 계정 인증 문서; Android 온보딩/설정 리뷰. |
| `backup.zero-knowledge-settings` | 선택적 설정 백업은 암호문만 저장하며, Lava는 평문 백업 내용을 읽을 수 없습니다. | Shipped | Deferred | Android가 백업을 제공하기 전 정확한 개인정보 보호 패리티. | 제로 지식 백업 테스트; 구축 시 Android 암호화 패리티 테스트. |
| `plus.customization-boundary` | 무료 보호 기능은 계속 유용하며, Plus는 고급 커스터마이징을 잠금 해제하되 가드레일 안전성은 절대 변경하지 않습니다. | Shipped | Planned | 동일한 제품 경계; 스토어 구현은 플랫폼 네이티브임. | 구독 정책 테스트; 구축 시 Play Billing 권한 테스트. |
| `design.calm-earned-depth` | 기본 UX는 차분하며, 더 깊은 기술적 또는 축하성 화면은 충족되거나 요청될 때만 나타납니다. | Partial | Planned | 공유 토큰/역할을 통한 디자인 의도로 일치. | 디자인 시스템 문서 및 이식성 기반 계획. |
| `platform.ambient-presence` | OS가 네이티브 앰비언트 화면을 지원할 때 보호 상태가 앱 외부에 나타날 수 있습니다. | Platform-native | Planned | 화면 패리티가 아니라 의도 패리티. | iOS Live Activity 문서; Android 알림/빠른 설정 결정 보류 중. |

## Android 준비 용도

Android 구현이 시작되기 전에, 이 페이지는 Android 계획 및 디자인 시스템
이식성 계획과 나란히 검토되어야 합니다. 최소한의 Android 준비
계약은 다음과 같습니다.

- 개인정보 보호를 수반하는 모든 기능에 기능 id가 있어야 합니다.
- 정확한 패리티 동작에는 식별된 iOS 테스트 또는 픽스처 소스가 있어야 합니다.
- 플랫폼 네이티브 동작에는 명시적인 Android 입장이 있어야 합니다.
- 지연된 기능은 명명되어 Android MVP가 해당 기능이 출시된다고 실수로
  암시하지 않게 합니다.

그 검토는 구현 계획 또는 리뷰 노트에 속하며, 이 페이지는
공개적이고 지속적인 계약을 유지합니다.
