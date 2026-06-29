---
hide_feedback: true
---

# Lava Security 문서

Lava Security는 기기 내 NetworkExtension 패킷 터널을 통해 DNS를
기기에서 로컬로 필터링하는 **프라이버시 우선 iOS 앱**입니다 — 알려진
위험하고 원치 않는 도메인을 차단하되 사용자의 브라우징을 Lava의 서버로 라우팅하지 않습니다.

!!! quote "프라이버시 약속"
    DNS 필터링은 사용자의 기기에서 로컬로 이루어집니다. Lava는 사용자의
    일상적인 DNS 쿼리, 브라우징 기록, 도메인별 텔레메트리를 결코 수신하지 않으며,
    선택적인 계정 백업은 종단 간 암호화되어 Lava는 오직 암호문만
    저장할 수 있습니다.

이 사이트는 Lava가 어떻게 동작하는지에 대한 공개 매뉴얼입니다 — 아키텍처,
동작 방식, 그리고 그 이면의 결정들을 다룹니다. 오픈 소스
[iOS 클라이언트](https://github.com/lavasecurity/lavasec-ios)를 추적합니다.

## 여기서 시작하세요

<div class="grid cards" markdown>

-   :material-rocket-launch: **제품**

    Lava가 무엇을 하며 누구를 위한 것인지.

    [개요](product/overview.md) · [기능 카탈로그](product/features.md) ·
    [플랫폼 패리티](product/platform-parity.md)

-   :material-sitemap: **아키텍처**

    전체 시스템이 어떻게 맞물려 동작하는지.

    [시스템 개요](architecture/system-overview.md) ·
    [iOS 클라이언트](architecture/ios-client.md) ·
    [DNS 필터링 및 차단 목록](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **프라이버시 내부 구조**

    프라이버시 약속을 떠받치는 부분들.

    [백엔드 및 데이터](architecture/backend-and-data.md) ·
    [계정 및 제로 지식 백업](architecture/accounts-and-backup.md)

-   :material-scale-balance: **결정 사항 및 규정 준수**

    왜 이런 방식으로 만들어졌는지.

    [핵심 결정 사항 (ADRs)](decisions/key-decisions.md) ·
    [서드파티 고지](legal/third-party-notices.md)

</div>

## 이 문서를 읽는 방법

여기 있는 모든 주장은 소스에 근거합니다. 상태는 전반에 걸쳐 표시됩니다.

| 상태 | 의미 |
|---|---|
| **Implemented** | 출시된 코드에 존재함 |
| **In progress** | 현재 개발 중 |
| **Planned** | 방향성이며, 아직 구축되지 않음 |
| **Dropped** | 채택하지 않기로 결정 — 기록을 위해 보존 |

문서와 코드가 일치하지 않을 때는 코드가 우선합니다. 이 문서는 스냅샷이며,
제품이 발전함에 따라 소스로부터 재생성됩니다.

크로스 플랫폼 동작은 [플랫폼 패리티](product/platform-parity.md)에서 추적합니다.
안정적인 기능 id, 플랫폼 상태, 그리고 iOS와 Android를 정렬된 상태로
유지해야 하는 테스트나 픽스처를 명시합니다.
