---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# 계정 및 제로 지식 백업

> **대상 독자:** 엔지니어.
> **기준:** 이 문서와 계획(plan)이 다를 경우 **코드가 우선**합니다 — 차이는 본문에서 직접 짚어 둡니다. 상태는 계획상의 지향이 아니라 코드로 확인된 현실을 반영합니다. 상태 범례: **Implemented**(출시되어 코드로 확인됨), **In progress**(일부 반영됨), **Planned**(설계됨, 구현 전), **Dropped**(폐기 또는 되돌림).

계정은 **선택 사항**입니다. 핵심 보호 기능은 영원히 무료이며 계정이 필요 없습니다. 로그인은 *설정*을 암호화해 백업하여 새 기기에서 복원할 수 있도록 하는 용도로만 존재합니다. 이 문서에서는 인증 흐름, 세션이 저장되는 위치, 제로 지식 백업 봉투(envelope), 복구 경로, 그리고 서버가 정확히 무엇을 볼 수 있고 볼 수 없는지를 다룹니다.

이 문서가 따르는 핵심 개인정보 약속:

> 모든 DNS 필터링은 기기에서 이루어집니다. Lava는 사용자의 인터넷 사용을 자사 서버로 우회시키지 않으며, 방문한 도메인 흐름을 받지도 않습니다 — 백엔드는 카탈로그 메타데이터, 사용자별 불투명 암호화 백업, 그리고 사용자가 보내기로 선택한 익명화된 진단 정보만 보관합니다.

구성 요소 분리: 순수 암호화 + 요청 빌드는 `LavaSecCore`에, 오케스트레이션 + UI는 `LavaSecApp`에 있습니다. 관련 문서: [시스템 개요](./system-overview.md), [iOS 클라이언트](./ios-client.md), [백엔드 및 데이터](./backend-and-data.md), [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md).

---

## 1. 인증 흐름

**제공자: Apple과 Google뿐.** **(Implemented)** `AccountAuthProvider`는 정확히 `.apple`과 `.google`만 열거합니다(`AccountAuthService.swift`). 이메일/비밀번호 — 그리고 인증을 우회하는 모든 지원팀 보조 복구 — 는 명시적으로 **Dropped**입니다. 비밀번호를 직접 관리하면 재설정/MFA/잠금/유출 대응 의무가 따르는데, Apple/Google로 충분한 상황에서 그만한 복잡성을 감수할 가치가 없습니다. 또한 우회 복구는 제로 지식 보장을 깨뜨립니다.

두 제공자 모두 Supabase Swift SDK나 웹 OAuth가 아니라 **네이티브 `id_token` 그랜트**를 사용합니다:

1. **네이티브로 로그인.** Apple은 AuthenticationServices로, Google은 GoogleSignIn SDK로 처리합니다. 각각 제공자 `id_token`을 반환합니다(Google은 access token도 함께). 앱은 CSPRNG로 raw nonce를 생성하고 SHA256으로 해시한 뒤 그 해시를 제공자에 전달하므로, 발급된 `id_token`이 해당 nonce에 묶입니다. **(Implemented)**
2. **Supabase에서 교환.** `SupabaseIDTokenAuth`(`LavaSecCore`)는 Supabase Auth `auth/v1/token?grant_type=id_token`로 보내는 raw `URLRequest`를 만들어, `provider` + `id_token` + 선택적 `access_token` + **raw** nonce를 `apikey` 헤더와 함께 POST합니다(이로써 Supabase가 바인딩을 검증하고 재전송을 거부할 수 있습니다). SDK는 쓰지 않으며, `LavaSecCore`는 네트워크/인증 의존성을 두지 않습니다. **(Implemented)**
3. **세션 수신.** Supabase가 토큰을 검증하고 세션을 반환합니다: access token, refresh token, 만료 시각, 사용자 레코드(provider/providers). 갱신은 동일한 헬퍼에서 `grant_type=refresh_token`으로 처리합니다.

`AccountAuthService`(`@MainActor`, `LavaSecApp`)가 이 모든 과정을 오케스트레이션합니다 — 네이티브 흐름을 실행하고, 교환을 수행하며, 세션을 저장·갱신하고, `AccountAuthState`를 노출하며, Worker를 통한 계정 삭제를 처리합니다.

```
Apple / Google (native id_token + raw nonce)
        │
        ▼
SupabaseIDTokenAuth  ──POST──▶  Supabase Auth  auth/v1/token?grant_type=id_token
        │                              │
        ▼                              ▼
AccountAuthService  ◀────── session (access + refresh tokens, expiry, user)
        │
        ▼
AccountSessionKeychainStore  (Keychain, device-local)
```

---

## 2. 세션 및 Keychain 저장

로그인에서 저장되는 **유일한** 항목은 Supabase 세션 — access token과 refresh token을 JSON으로 — 입니다. Supabase Auth 사용자와 사용자가 소유한 행(row) 외에 당신이 누구인지에 대한 서버 측 사본은 **없습니다**.

- **위치:** `AccountSessionKeychainStore`(`LavaSecApp`), Keychain 서비스 `com.lavasec.account-session`, **제공자별로** 저장됩니다(`supabase-session-apple` / `supabase-session-google`, 여기에 레거시 계정 마이그레이션 포함). **(Implemented)**
- **접근성:** 모든 저장소는 `GenericKeychainStore`(`LavaSecCore`)를 공유하며 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`로 고정됩니다. 즉 **기기 로컬에 저장되고, iCloud로 동기화되지 않으며, 기기 백업에도 포함되지 않습니다**. **(Implemented)**

동일한 `GenericKeychainStore` 메커니즘이 세 가지 저장소를 뒷받침합니다: 계정 세션, 백업 잠금 해제 자료(`BackupKeychainStore`, 서비스 `com.lavasec.zero-knowledge-backup`), 그리고 앱 패스코드. 이 중 어느 것도 iCloud Keychain을 통해 동기화되지 않습니다.

> **검토 중인 항목(확정된 동작 아님):** 현재 접근성 클래스에는 생체 인증/사용자 확인 게이트가 없습니다(`SecAccessControl`의 `.userPresence`/`.biometryCurrentSet` 없음). 잠금 해제 자료를 확인 게이트가 있는 접근 제어로 강화할지는 릴리스 게이트 검토 항목으로 추적 중이며, 현재 출시된 값은 첫 잠금 해제 후 이 기기 전용(after-first-unlock-this-device-only)입니다. **(Planned)**

---

## 3. 제로 지식 백업

### 3.1 정확히 무엇인가

암호화 백업을 켜면 **iOS 클라이언트**가 *설정*의 최소화된 사본을 암호화하여 암호문과 비밀이 아닌 메타데이터만 Supabase에 업로드합니다. 평문과 복호화 비밀이 존재하는 유일한 장소는 휴대폰입니다.

> **제로 지식 백업:** 클라이언트 측 AES-256-GCM 봉투; 무작위 페이로드 키는 슬롯별 키 슬롯에 래핑됩니다 — 비밀번호/구문/기기/보조 슬롯은 PBKDF2-HMAC-SHA256(210k 반복), PRF 패스키 슬롯은 HKDF-SHA256을 사용합니다. 암호문 + 비밀이 아닌 메타데이터만 Supabase `user_backups`(사용자별 RLS)에 업로드됩니다. 서버는 사용자가 보유한 비밀 없이는 복호화할 수 없습니다. 패스키 슬롯 **역시** 제로 지식입니다: 언래핑 키는 인증기의 WebAuthn PRF(`hmac-secret`) 출력에서 기기 내에서 파생되며, 서버는 어떤 패스키 비밀도 보관하지 않습니다(§4.3 참조).

### 3.2 무엇이 백업되는가 (최소화된 페이로드)

`BackupConfigurationPayload`(`LavaSecCore`)는 봉인되는 평문입니다. 의도적으로 작게 유지되며 `AppConfiguration`과 양방향으로 변환됩니다. **(Implemented)**

**포함:** 활성화된 차단 목록 **ID**(목록 바이트가 아니라 카탈로그 참조), 허용/차단 도메인, 리졸버 프리셋 / 사용자 지정 리졸버, 로컬 로그 환경설정, LavaGuard 원장(ledger), 보호 힌트, 사용자 지정 차단 목록 소스 메타데이터.

**제외:** `isPaid`(권한은 로컬에 있음), QA 플래그, 진단 정보, 필터 스냅샷, 그리고 전체 차단 목록 내용(카탈로그 ID로만 참조). 기기는 도메인 방문 기록과 DNS 쿼리를 일상적인 텔레메트리 스트림으로 기록하지 않으므로 이들은 이 페이로드에 절대 포함되지 않습니다.

### 3.3 봉투 (클라이언트 측 암호화)

`ZeroKnowledgeBackupEnvelope`(`LavaSecCore`)가 암호화를 구현합니다. **(Implemented)**

1. **페이로드 암호화.** 최소화된 페이로드는 무작위 **32바이트 페이로드 키**(`SecRandomCopyBytes`로 생성) 아래에서 **AES-256-GCM**으로 한 번 봉인됩니다.
2. **키 래핑(키 슬롯).** 이 단일 페이로드 키는 비밀 하나당 하나씩, 하나 이상의 **키 슬롯**으로 독립적으로 래핑되며, 각 슬롯은 페이로드 키 사본을 AES-GCM으로 래핑합니다. 어떤 슬롯이든 그 비밀 하나만 있으면 백업 전체가 열립니다. 래핑 키 파생은 슬롯 종류별로 다릅니다: `password` / `recoveryPhrase` / `keychain`(기기) / `assistedRecovery` 슬롯은 슬롯마다 새로운 16바이트 무작위 솔트와 함께 **PBKDF2-HMAC-SHA256, 210,000회 반복**(프로덕션; `defaultPasswordIterations = 210_000`)을 사용하고, `passkey` 슬롯은 인증기의 PRF 출력에 대해 **HKDF-SHA256**(info `"LavaSec passkey backup PRF v1"`)을 사용하며, 복원 시 동일한 출력을 재현할 수 있도록 비밀이 아닌 PRF 솔트를 슬롯에 보관합니다.
3. **슬롯 종류.** 봉투는 다섯 가지 슬롯 종류를 지원합니다: `password`, `recoveryPhrase`, `keychain`(기기 비밀), `assistedRecovery`, `passkey`.

출시된 설정은 **비밀번호 없는(passwordless)** 방식입니다(`makePasswordless`, `AppViewModel.turnOnEncryptedBackup`가 구동). 이 방식은 **`keychain`(기기) 슬롯 + `assistedRecovery` 슬롯 + 선택적 `passkey` 슬롯**을 생성합니다. `password` / `recoveryPhrase` 팩토리와 복호화 메서드는 레거시/하위 호환 봉투를 위해 여전히 존재하지만(테스트에서만 사용됨) 활성 UI는 비밀번호 전용 봉투를 절대 생성하지 않습니다 — 비밀번호 백업은 출시되지 않은 것으로 보세요. **(Implemented; 라이브 흐름에서 password 슬롯은 Dropped.)**

**무결성 / 다운그레이드 방지:** `envelopeVersion`은 `1`로 하드 고정되어 있고, 각 슬롯의 KDF는 종류별로 고정됩니다 — 비밀번호/구문/기기/보조 슬롯은 `PBKDF2-HMAC-SHA256`, PRF 패스키 슬롯은 `HKDF-SHA256`. 지원되지 않는 버전이나 일치하지 않는 KDF는 거부되므로, 위조되거나 다운그레이드된 메타데이터로는 언래핑을 약화시킬 수 없습니다. **(Implemented)**

### 3.4 업로드 및 저장

`BackupSyncService`(`SupabaseBackupSyncService`, `LavaSecApp`)는 봉투를 Supabase PostgREST 테이블 `user_backups`에 **직접** 업로드하며, `user_id`로 upsert하고 사용자의 access token으로 범위를 한정합니다. **봉투 업로드를 위한 Worker 경로는 없습니다** — 클라이언트는 RLS 하에서 Supabase와 직접 통신하고, Worker는 계정 삭제 시 `user_backups`를 삭제할 때만 이를 건드립니다. **(Implemented)**

`user_backups`에 들어가는 것:

- **암호문**, 그리고
- **비밀이 아닌 메타데이터만:** cipher 이름, 키 슬롯 레코드(솔트, 반복 횟수, 래핑된 키, 슬롯 레이블), `server_recovery_share`, `createdAt`, 바이트 크기.

행은 **행 수준 보안(row-level security)**으로 보호됩니다: 각 행은 소유자만 읽고 쓸 수 있으며(`auth.uid() = user_id`), 익명 역할은 접근 권한이 없습니다. 크기는 DB 수준에서 암호문 약 256 KiB / 메타데이터 32 KiB로 제한됩니다(`20260518000000_zero_knowledge_backups.sql`, `20260605000000_tighten_backup_envelope_constraints.sql`에서 강화됨). **(Implemented)**

### 3.5 보장 — 서버가 볼 수 있는 것과 볼 수 없는 것

**서버가 저장하는 것:** 암호문, KDF 솔트/반복 횟수, 래핑된 키 슬롯, `server_recovery_share`, 그리고 비밀이 아닌 몇몇 필드(cipher, 크기, 타임스탬프).

**서버가 절대 받거나 저장하지 않는 것:** 평문 설정/도메인/DNS 환경설정, 복구 구문, 백업 비밀번호, 또는 언래핑된 페이로드 키.

**따라서:** Supabase는 사용자가 보유한 비밀 없이는 **백업을 복호화할 수 없습니다**. 세 가지 복원 경로 모두 — 기기 키 슬롯, 복구 구문(서버 share와 결합, §4.2), 패스키 슬롯(인증기의 PRF 출력, §4.3) — 은 **기기에서** 복호화되며, 서버는 그 어느 것에 대해서도 복호화 비밀을 보관하지 않습니다. 이는 마이그레이션 주석과 개인정보 계획에 명시되어 있으며 테스트로 검증됩니다(봉투 테스트는 업로드 형태에 평문 도메인/URL이 새어 나가지 않음을 확인합니다).

**정확한 위협 모델 단서 — 과장하지 말 것.** **보조 복구(assisted-recovery)** 슬롯의 경우, 서버는 `user_backups`에 `server_recovery_share` *와* 래핑된 `assistedRecovery` 슬롯을 *둘 다* 보관합니다. 서버에 없는 유일한 것은 사용자의 복구 구문이며, Lava는 이를 받지 않습니다. 따라서 서버가 완전히 침해되더라도 복구 구문의 엔트로피(약 105비트, §4.1 참조)와 210k 반복 PBKDF2 비용이 해당 슬롯에 대한 오프라인 무차별 대입을 막는 **유일한** 장벽입니다. 이는 의도된 설계입니다(보조 복구는 설계상 이중 요소이며 — 어느 한쪽만으로는 복호화되지 않습니다). 다만 이는 복구 구문 엔트로피가 장식이 아니라 실질적 역할을 한다는 뜻입니다. `keychain`(기기) 슬롯의 비밀은 기기를 절대 떠나지 않으므로, 서버 침해에 전혀 노출되지 않습니다.

---

## 4. 복구

백업은 복원할 수 있어야 비로소 쓸모가 있습니다. `restoreEncryptedBackup`(`AppViewModel` 내)은 사용 가능한 슬롯을 차례로 시도하여 복호화합니다: 기기 키, 복구 구문, 또는 패스키. 모든 모드에서 봉투는 로컬로 로드되거나(또는 Supabase에서 가져와) **기기에서 복호화됩니다** — 서버는 절대 복호화하지 않습니다.

### 4.1 복구 구문

`BackupRecoveryPhrase`(`LavaSecCore`)는 거부 샘플링과 함께 `SecRandom`으로 **8단어 CVCV 구문**(자음-모음-자음-모음)을 생성하며(토큰당 약 13.2비트 → **총 약 105비트**), 소문자로 정규화합니다. **(Implemented)** 복원은 슬롯을 시도하기 전에 파싱/정규화를 통해 사용자의 형식(띄어쓰기/대소문자)을 허용합니다.

이것은 사용자의 **기기 외부(off-device)** 복구 요소입니다 — 사용자가 직접 저장하며 업로드되지 않습니다. 개인정보 강화(§5)에 따라 구문 복사는 **선택 사항**이며, 사용할 경우 전역 클립보드 노출을 강제하지 않고 로컬 전용 / 만료(10분) 클립보드를 거칩니다.

### 4.2 보조 복구 (이중 요소 조합)

복구 구문만으로는 `assistedRecovery` 슬롯이 열리지 **않습니다**. 슬롯 비밀은 **두 부분 모두**에서 파생됩니다:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

세 구간은 실제 UTF-8 입력에서 **NUL 바이트(`0x00`) 구분자**로 결합됩니다 — 즉 해시되는 문자열은 `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase`이며, 위의 `‖`는 단순 연결이 아니라 NUL로 구분된 연결을 나타냅니다. `serverRecoveryShare`는 봉투 메타데이터에 서버 측에 저장된 무작위 값이고, `normalizedPhrase`는 사용자의 복구 구문입니다. **어느 한쪽만으로는 복호화되지 않으며** — 복원에는 (백업과 함께 가져온) 서버 share *와* 사용자가 보유한 구문이 모두 필요합니다. **(Implemented)**

### 4.3 패스키 복구 — 제로 지식, PRF 파생

선택적 `passkey` 슬롯은 하드웨어 기반 요소를 추가하며, **제로 지식**입니다: 언래핑 키는 인증기의 WebAuthn PRF(`hmac-secret`) 출력에서 **기기 내에서** 파생됩니다. 서버는 패스키를 등록하지 않고, WebAuthn 챌린지를 발급하지 않으며, 복구 비밀을 저장하지 않습니다 — 서버 릴리스 단계가 없습니다.

- **등록/어서션:** `BackupPasskeyCoordinator`(`LavaSecApp`)는 `ASAuthorizationPlatformPublicKeyCredentialProvider`를 통해 WebAuthn을 실행하며, 신뢰 당사자(relying party)는 **`lavasecurity.app`**, 자격 증명별 솔트에 대해 PRF 확장을 요청하고 사용자 확인을 요구합니다.
- **키 파생(제로 지식):** 인증기는 **기기를 절대 떠나지 않는** PRF 출력을 반환합니다. `ZeroKnowledgeBackupEnvelope.makeWithPRF`(`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`)는 그 PRF 출력에서 슬롯의 래핑 키를 HKDF-SHA256으로 파생하고(info `"LavaSec passkey backup PRF v1"`) 페이로드 키를 AES-GCM으로 래핑합니다. 슬롯에는 비밀이 아닌 PRF 솔트와 자격 증명 ID만 보관됩니다. 복원 시 `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput`가 자격 증명을 다시 어서트하여 동일한 PRF 출력을 재현하고, `decryptWithPasskeyPRFOutput`가 슬롯을 로컬에서 언래핑합니다. 서버는 패스키 비밀을 **전혀** 보관하지 않으므로, 어떤 service-role 경로로도 패스키로 보호된 백업을 복구할 수 없습니다.

이전의 에스크로 설계(서버 측 `recovery_secret`을 보관하는 service-role `backup_passkey_recovery` 테이블, 그리고 `backup_passkey_challenges` 테이블과 `/v1/backup/passkeys/*` Worker 엔드포인트)는 **Dropped**되었습니다: 해당 테이블은 백엔드 마이그레이션에서 제거되었고, Worker는 패스키 경로를 두지 않으며, `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift`는 `BackupPasskeyRecoveryService`와 모든 서버 에스크로 경로가 없음을 명확히 단언합니다. **(Implemented)**

> **프로덕션 준비 단서:** 실제 기기에서 저장된 패스키를 완전히 프로덕션 수준의 복구 요소로 다루는 것은 여전히 `lavasecurity.app`에 대한 webcredentials 연결에 달려 있습니다. iOS 쪽은 선언되어 있고 — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements`가 `webcredentials:lavasecurity.app`를 담고 있습니다 — 서버 쪽(`apple-app-site-association` 파일과 헤더)도 이제 마케팅 사이트에 호스팅됩니다. 특정 기기에서 그 연결이 확인되기 전까지는 webcredentials 연결 경로가 실패할 수 있으며 `BackupPasskeyError.webCredentialsAssociationUnavailable`를 표면화합니다. 패스키 요소 자체는 구현되어 있지만, 실제 하드웨어에서의 종단 간 준비 상태는 **Planned**입니다.

---

## 5. 데이터 최소화 및 개인정보 태세

- **선택적 계정.** 보호 기능은 계정 없이 작동하며, 로그인은 설정 백업만 활성화합니다.
- **평문은 로컬에만.** 평문 설정과 복호화 비밀이 존재하는 유일한 장소는 휴대폰입니다. Supabase는 사용자당 불투명 봉투 하나만 보관합니다.
- **최소화된 페이로드.** §3.2의 설정만 백업되며, `isPaid`, QA 플래그, 진단 정보, 스냅샷, 전체 차단 목록 바이트는 제외됩니다. 차단 목록은 카탈로그 ID로 참조될 뿐 절대 내장되지 않습니다.
- **인터넷 사용/DNS 텔레메트리 없음.** 일상적인 DNS 쿼리나 도메인별 텔레메트리를 위한 서버 측 테이블은 없습니다. 필터링은 기기에 머뭅니다.
- **잠금 해제 자료는 기기 로컬.** 백업 잠금 해제 자료는 `…ThisDeviceOnly` 접근성으로 저장되며 iCloud로 동기화되지 **않습니다**. 이는 원래 계획의 동기화 가능 Keychain 설계를 **뒤집은** 것이며, 그 결과 Lava는 잠금 해제 자료를 iCloud를 통해 조용히 동기화하지 않습니다(`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implemented; 이전 계획을 뒤집음.)**

### 계정 삭제

삭제는 **Implemented**이며, 클라이언트의 직접 삭제가 아니라 인증된 Worker 엔드포인트를 통해 실행됩니다. `AccountAuthService.deleteAccount`는 사용자의 access token을 `POST /v1/account/delete`로 보냅니다. `lavasec-api` Worker(service role)는 사용자의 `bug_reports`(및 해당 R2 첨부 파일), `user_backups`, `entitlements`, `user_settings`, `profiles` 행을 삭제한 뒤 admin API로 Supabase Auth 사용자를 삭제하고, 삭제 상태 + 연결된 제공자만 반환합니다. 그런 다음 앱은 로컬에서 로그아웃하고 백업 잠금 해제 자료를 지웁니다(`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> 참고: 삭제 계획의 YAML 프런트매터는 이미 `status: Done`으로 되어 있고 `plans/implemented/`에 위치합니다. 오래된 **본문 내** 주석에 `Status: Backlog.`로 적혀 있지만, 레인 폴더 규칙(폴더가 권위를 가짐)과 코드 존재(앱 + Worker가 모두 있음)에 따라 이 기능은 **Implemented**이며, 본문 내 그 줄은 프런트매터가 아니라 문서 버그입니다.

---

## 6. 상태 요약

| 영역 | 세부 | 상태 |
|---|---|---|
| Supabase를 통한 Apple / Google `id_token` 로그인 | 네이티브 흐름, 해시된 nonce, raw-URLRequest 교환 | Implemented |
| 이메일/비밀번호 로그인 | 비밀번호 직접 관리 거부 | Dropped |
| Keychain 내 세션(기기 로컬, 제공자별) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implemented |
| AES-256-GCM 봉투 + PBKDF2-HMAC-SHA256(210k) 키 슬롯 | 클라이언트 측; 암호문 + 비밀이 아닌 메타데이터만 `user_backups`(RLS)로 | Implemented |
| 비밀번호 없는 설정(기기 + 보조 복구 + 선택적 패스키 슬롯) | `makePasswordless` | Implemented |
| 라이브 흐름의 비밀번호 키 슬롯 | `LavaSecCore`에는 테스트용으로만 남음 | Dropped |
| 복구 구문(8단어 CVCV, 약 105비트) | 기기 외부 요소 | Implemented |
| 보조 복구(SHA256 통한 서버 share + 구문, NUL 구분) | 이중 요소; 어느 한쪽만으로는 불가 | Implemented |
| 패스키 복구(제로 지식, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | PRF 출력 HKDF 파생 슬롯, 서버 비밀 없음 | Implemented |
| 하드웨어에서 프로덕션 수준 요소로서의 패스키 | webcredentials 연결 필요(AASA는 마케팅 사이트에 호스팅됨) | Planned |
| 계정 삭제(인증된 Worker, service role) | 백업/설정/권한/프로필/첨부 파일 + Auth 사용자 제거 | Implemented |
| 잠금 해제 자료의 생체 인증/사용자 확인 게이트 | 릴리스 게이트 검토 항목 | Planned |
| `AppViewModel`에서 `EncryptedBackupCoordinator` 분리 | 모듈화만; 보안 모델 변경 없음 | In progress |

---

## 관련 문서

- [시스템 개요](./system-overview.md) — 신뢰 경계를 포함해 전체 시스템을 한 화면에서.
- [iOS 클라이언트](./ios-client.md) — `AppViewModel`과 백업을 구동하는 앱 타깃.
- [백엔드 및 데이터](./backend-and-data.md) — `lavasec-api` Worker, Supabase RLS, 그리고 `user_backups` 저장.
- [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md) — 백업 페이로드에 담기는 설정의 리졸버 프리셋과 전송 방식.
