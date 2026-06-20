---
hide_feedback: true
---

# Lava Security 문서

Lava Security는 기기 안에서 동작하는 NetworkExtension 패킷 터널을 통해
DNS를 기기에서 직접 필터링하는 **프라이버시 우선 iOS 앱**이에요. 여러분의
인터넷 사용을 Lava 서버로 보내지 않고도, 위험하거나 원치 않는 도메인을 차단해요.

!!! quote "프라이버시 약속"
    DNS 필터링은 여러분의 기기에서 직접 이뤄져요. Lava는 여러분의 일상적인 DNS
    요청이나 방문 기록, 도메인별 사용 정보를 전혀 받지 않아요. 선택적으로 계정에
    백업하는 정보도 종단 간 암호화되기 때문에, Lava는 암호화된 데이터만 보관할 수
    있어요.

이 사이트는 Lava가 어떻게 동작하는지 — 구조와 동작 방식, 그리고 그 뒤에 있는
결정들을 담은 공개 매뉴얼이에요. 오픈소스
[iOS 클라이언트](https://github.com/lavasecurity/lavasec-ios)를 기준으로 해요.

## 여기서 시작하세요

<div class="grid cards" markdown>

-   :material-rocket-launch: **제품**

    Lava가 하는 일과 누구를 위한 앱인지 알려드려요.

    [개요](product/overview.md) · [기능 목록](product/features.md) ·
    [플랫폼 동등성](product/platform-parity.md)

-   :material-sitemap: **구조**

    전체 시스템이 어떻게 맞물려 동작하는지 알려드려요.

    [시스템 개요](architecture/system-overview.md) ·
    [iOS 클라이언트](architecture/ios-client.md) ·
    [DNS 필터링과 차단 목록](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **프라이버시 내부 구조**

    프라이버시 약속을 지탱하는 부분들이에요.

    [백엔드와 데이터](architecture/backend-and-data.md) ·
    [계정과 제로 지식 백업](architecture/accounts-and-backup.md)

-   :material-scale-balance: **결정과 컴플라이언스**

    왜 이렇게 만들었는지 알려드려요.

    [주요 결정 사항 (ADR)](decisions/key-decisions.md) ·
    [제3자 고지](legal/third-party-notices.md)

</div>

## 이 문서를 읽는 법

여기 적힌 모든 내용은 소스 코드에 근거를 두고 있어요. 곳곳에 상태를 표시해 두었어요.

| 상태 | 의미 |
|---|---|
| **구현됨** | 출시된 코드에 포함되어 있음 |
| **진행 중** | 현재 개발 중 |
| **계획됨** | 방향만 정해졌고 아직 만들지 않음 |
| **보류됨** | 도입하지 않기로 결정 — 기록을 위해 남겨 둠 |

문서와 코드가 다를 때는 코드가 기준이에요. 이 문서는 한 시점의 스냅샷이며,
제품이 발전함에 따라 소스를 바탕으로 다시 생성돼요.

플랫폼 간 동작은 [플랫폼 동등성](product/platform-parity.md)에서 다뤄요.
여기에는 안정적인 기능 id와 플랫폼별 상태, 그리고 iOS와 Android를 맞춰 두기 위한
테스트나 픽스처가 정리되어 있어요.
