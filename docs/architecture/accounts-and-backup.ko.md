---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 계정 및 제로 지식 백업

> **대상 독자:** 엔지니어.
> **권위:** 이 문서와 계획(plan)이 일치하지 않을 경우 **코드가 우선한다** — 불일치는 본문 내에 표시된다. 상태는 계획상의 지향점이 아니라 코드로 확인된 현실을 반영한다. 상태 범례: **Implemented**(출시되어 코드로 확인됨), **In progress**(부분적으로 반영됨), **Planned**(설계되었으나 구현되지 않음), **Dropped**(거부되거나 되돌려짐).

계정은 **선택 사항**이다. 핵심 보호 기능은 영원히 무료이며 계정이 필요 없다. 로그인은 *설정*을 암호화하여 백업하고 새 기기에서 복원할 수 있도록 하기 위해서만 존재한다. 이 문서는 인증 흐름, 세션이 저장되는 위치, 제로 지식 백업 봉투(envelope), 복구 경로, 그리고 서버가 볼 수 있는 것과 볼 수 없는 것을 정확히 다룬다.

이 문서가 따르는 표준 개인정보 보호 약속:

> 모든 DNS 필터링은 기기에서 이루어진다. Lava는 사용자의 브라우징을 자사 서버로 라우팅하지 않으며, 사용자가 방문하는 도메인 스트림을 절대 수신하지 않는다 — 백엔드는 카탈로그 메타데이터, 사용자별 불투명 암호화 백업, 그리고 사용자가 보내기로 선택한 익명화된 진단 정보만 보유한다.

컴포넌트 분리: 순수 암호화 + 요청 생성은 `LavaSecCore`에 있고, 오케스트레이션 + UI는 `LavaSecApp`에 있다. 관련 문서: [System Overview](./system-overview.md), [iOS Client](./ios-client.md), [Backend & Data](./backend-and-data.md), [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md).

---

## 1. 인증 흐름

**제공자: Apple과 Google만 지원.** **(Implemented)** `AccountAuthProvider`는 정확히 `.apple`과 `.google`만 열거한다(`AccountAuthService.swift`). 이메일/비밀번호 — 그리고 인증을 우회하는 모든 지원팀 보조 복구 — 는 명시적으로 **Dropped**다. 비밀번호를 보유하면 재설정/MFA/잠금/유출 대응 의무가 추가되지만 Apple/Google로 충분하며, 우회 복구는 제로 지식 보장을 깨뜨린다.

두 제공자 모두 Supabase Swift SDK나 웹 OAuth가 아닌 **네이티브 `id_token` grant**를 사용한다:

1. **네이티브로 로그인.** Apple은 AuthenticationServices를 통해, Google은 GoogleSignIn SDK를 통해 로그인한다. 각각 제공자 `id_token`(Google은 access token도)을 산출한다. 앱은 CSPRNG raw nonce를 생성하고 SHA256으로 해시한 뒤 그 해시를 제공자에게 전달하여, 발급된 `id_token`이 그것에 바인딩되도록 한다. **(Implemented)**
2. **Supabase에서 교환.** `SupabaseIDTokenAuth`(`LavaSecCore`)는 Supabase Auth `auth/v1/token?grant_type=id_token`에 대한 raw `URLRequest`를 만들어, `provider` + `id_token` + 선택적 `access_token` + **raw** nonce(Supabase가 바인딩을 검증하고 재생 공격을 거부할 수 있도록)를 `apikey` 헤더와 함께 POST한다. SDK 없음. `LavaSecCore`는 네트워크/인증 의존성을 갖지 않는다. **(Implemented)**
3. **세션 수신.** Supabase는 토큰을 검증하고 세션을 반환한다: access token, refresh token, 만료 시간, 그리고 사용자 레코드(provider/providers). 갱신은 동일한 헬퍼를 `grant_type=refresh_token`으로 사용한다.

`AccountAuthService`(`@MainActor`, `LavaSecApp`)가 이 모든 것을 오케스트레이션한다 — 네이티브 흐름을 실행하고, 교환을 수행하고, 세션을 영속화 및 갱신하며, `AccountAuthState`를 노출하고, Worker를 통한 계정 삭제를 구동한다.

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

## 2. 세션 및 Keychain 저장소

로그인에서 영속화되는 **유일한** 것은 Supabase 세션이다 — access token과 refresh token을 JSON으로 저장한다. Supabase Auth 사용자와 사용자가 소유한 행(row)을 넘어, 사용자가 누구인지에 대한 서버 측 미러는 **없다**.

- **위치:** `AccountSessionKeychainStore`(`LavaSecApp`), Keychain 서비스 `com.lavasec.account-session`, **제공자별로** 저장됨(`supabase-session-apple` / `supabase-session-google`, 그리고 레거시 계정 마이그레이션 추가). **(Implemented)**
- **접근성:** 모든 저장소는 `GenericKeychainStore`(`LavaSecCore`)를 공유하며 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`로 고정된다. 이는 **기기 로컬, iCloud 동기화 안 됨, 기기 백업에 포함되지 않음**을 의미한다. **(Implemented)**

동일한 `GenericKeychainStore` 메커니즘이 세 가지 저장소를 뒷받침한다: 계정 세션, 백업 잠금 해제 자료(`BackupKeychainStore`, 서비스 `com.lavasec.zero-knowledge-backup`), 그리고 앱 passcode. 이들 중 어느 것도 iCloud Keychain을 통해 동기화되지 않는다.

> **열린 검토 항목(주장된 동작 아님):** 현재 접근성 클래스에는 생체 인증/사용자 존재 게이트가 없다(`SecAccessControl`의 `.userPresence`/`.biometryCurrentSet` 없음). 잠금 해제 자료를 존재 게이트 기반 access control로 강화할지는 릴리스 게이트 검토 항목으로 추적된다. 오늘 출시된 값은 after-first-unlock-this-device-only다. **(Planned)**

---

## 3. 제로 지식 백업

### 3.1 정확히 무엇인가

암호화 백업을 켜면 **iOS 클라이언트**가 *설정*의 최소화된 사본을 암호화하고, 암호문과 비밀이 아닌 메타데이터만 Supabase에 업로드한다. 평문과 복호화 비밀은 오직 전화기에만 존재한다.

> **제로 지식 백업:** 클라이언트 측 AES-256-GCM 봉투. 무작위 payload key는 슬롯별 키 슬롯에 래핑된다 — password/phrase/device/assisted 슬롯은 PBKDF2-HMAC-SHA256(210k 반복), PRF passkey 슬롯은 HKDF-SHA256. 암호문 + 비밀이 아닌 메타데이터만 Supabase `user_backups`(사용자별 RLS)에 업로드된다. 서버는 사용자가 보유한 비밀 없이는 복호화할 수 없다. passkey 슬롯 **또한** 제로 지식이다: 그 unwrap key는 authenticator의 WebAuthn PRF(`hmac-secret`) 출력으로부터 기기에서 파생되며, 서버는 passkey 비밀을 보유하지 않는다(§4.3 참조).

### 3.2 무엇이 백업되는가(최소화된 payload)

`BackupConfigurationPayload`(`LavaSecCore`)는 봉인되는 평문이다. 의도적으로 작게 유지되며 `AppConfiguration`으로 왕복(round-trip)한다. **(Implemented)**

**포함:** 활성화된 blocklist **ID**(목록 바이트가 아닌 카탈로그 참조), 허용/차단 도메인, resolver 프리셋 / 커스텀 resolver, 로컬 로그 환경설정, LavaGuard ledger, 보호 힌트, 그리고 커스텀 blocklist 소스 메타데이터.

**제외:** `isPaid`(엔타이틀먼트는 로컬), QA 플래그, 진단, 필터 스냅샷, 그리고 전체 blocklist 내용(카탈로그 ID로만 참조). 사용자의 브라우징 기록과 DNS 쿼리는 이 payload의 일부가 절대 아니다. 기기가 그것들을 일상적인 텔레메트리 스트림으로 기록하지 않기 때문이다.

### 3.3 봉투(클라이언트 측 암호화)

`ZeroKnowledgeBackupEnvelope`(`LavaSecCore`)가 암호화를 구현한다. **(Implemented)**

1. **Payload 암호화.** 최소화된 payload는 무작위 **32바이트 payload key**(`SecRandomCopyBytes`로 생성) 아래 **AES-256-GCM**으로 한 번 봉인된다.
2. **키 래핑(키 슬롯).** 그 단일 payload key는 하나 이상의 **키 슬롯**으로 독립적으로 래핑되며, 비밀마다 하나씩 있고, 각각 payload key의 사본을 AES-GCM으로 래핑한다. 단일 슬롯의 비밀 하나로 전체 백업이 잠금 해제된다. 래핑 키 파생은 슬롯 종류별로 다르다: `password` / `recoveryPhrase` / `keychain`(device) / `assistedRecovery` 슬롯은 슬롯마다 새로운 16바이트 무작위 salt와 함께 **PBKDF2-HMAC-SHA256, 210,000 반복**(프로덕션; `defaultPasswordIterations = 210_000`)을 사용한다. `passkey` 슬롯은 authenticator의 PRF 출력에 대해 **HKDF-SHA256**(info `"LavaSec passkey backup PRF v1"`)을 사용하며, 복원 시 출력을 재현할 수 있도록 비밀이 아닌 PRF salt를 슬롯에 영속화한다.
3. **슬롯 종류.** 봉투는 다섯 가지 슬롯 종류를 지원한다: `password`, `recoveryPhrase`, `keychain`(device secret), `assistedRecovery`, `passkey`.

출시된 설정은 **passwordless**(`makePasswordless`, `AppViewModel.turnOnEncryptedBackup`로 구동)다. 이는 **`keychain`(device) 슬롯 + `assistedRecovery` 슬롯 + 선택적 `passkey` 슬롯**을 생성한다. `password` / `recoveryPhrase` 팩토리와 복호화 메서드는 레거시/하위 호환 봉투를 위해 여전히 존재하지만(테스트로만 실행됨) 활성 UI는 password 전용 봉투를 절대 생성하지 않는다 — password 백업은 출시되지 않은 것으로 취급하라. **(Implemented; password 슬롯은 라이브 흐름에서 Dropped.)**

**무결성 / 다운그레이드 방지:** `envelopeVersion`은 `1`로 강하게 고정되어 있고, 각 슬롯의 KDF는 종류별로 고정된다 — password/phrase/device/assisted 슬롯은 `PBKDF2-HMAC-SHA256`, PRF passkey 슬롯은 `HKDF-SHA256`. 지원되지 않는 버전이나 불일치하는 KDF는 거부되므로, 위조되거나 다운그레이드된 메타데이터가 unwrap을 약화시킬 수 없다. **(Implemented)**

### 3.4 업로드 및 저장

`BackupSyncService`(`SupabaseBackupSyncService`, `LavaSecApp`)는 봉투를 Supabase PostgREST 테이블 `user_backups`에 **직접** 업로드하며, `user_id`로 upsert하고 사용자의 access token으로 범위를 한정한다. **봉투 업로드를 위한 Worker 경로는 없다** — 클라이언트는 RLS 아래에서 Supabase와 직접 통신한다. Worker는 계정 삭제 중 `user_backups`를 삭제할 때만 그것을 건드린다. **(Implemented)**

`user_backups`에 저장되는 것:

- **암호문**, 그리고
- **비밀이 아닌 메타데이터만:** cipher 이름, 키 슬롯 레코드(salt, 반복 횟수, 래핑된 키, 슬롯 라벨), `server_recovery_share`, `createdAt`, 그리고 바이트 크기.

행은 **행 수준 보안(row-level security)**으로 보호된다: 각 행은 소유자만 읽기/쓰기할 수 있으며(`auth.uid() = user_id`), 익명 역할은 접근 권한이 없다. 크기는 DB 수준에서 암호문 ~256 KiB / 메타데이터 32 KiB로 제한된다(`20260518000000_zero_knowledge_backups.sql`, `20260605000000_tighten_backup_envelope_constraints.sql`에서 강화됨). **(Implemented)**

### 3.5 보장 — 서버가 볼 수 있는 것과 볼 수 없는 것

**서버가 저장하는 것:** 암호문, KDF salt/반복 횟수, 래핑된 키 슬롯, `server_recovery_share`, 그리고 몇 가지 비밀이 아닌 필드(cipher, 크기, 타임스탬프).

**서버가 절대 수신하거나 저장하지 않는 것:** 평문 설정/도메인/DNS 환경설정, 복구 문구(recovery phrase), 백업 비밀번호, 또는 unwrap된 payload key.

**따라서:** Supabase는 사용자가 보유한 비밀 없이는 **백업을 복호화할 수 없다**. 세 가지 복원 경로 — device-key 슬롯, (서버 share와 결합된) 복구 문구(§4.2), 그리고 passkey 슬롯(authenticator의 PRF 출력, §4.3) — 은 모두 **기기에서** 복호화되며, 서버는 그중 어느 것에 대해서도 복호화 비밀을 보유하지 않는다. 이는 마이그레이션 주석과 개인정보 보호 계획에서 명시되어 있고, 테스트되어 있다(봉투 테스트는 업로드된 형태에 평문 도메인/URL이 누출되지 않음을 확인한다).

**정확한 위협 모델 주의사항 — 과장하지 말 것.** **assisted-recovery** 슬롯의 경우, 서버는 `user_backups`에 `server_recovery_share` *그리고* 래핑된 `assistedRecovery` 슬롯을 *둘 다* 보유한다. 서버가 갖지 못하는 유일한 것은 사용자의 복구 문구이며, Lava는 이를 절대 수신하지 않는다. 따라서 서버가 완전히 침해되더라도, 복구 문구의 엔트로피(~105비트, §4.1 참조)와 210k 반복 PBKDF2 비용이 해당 슬롯에 대한 오프라인 무차별 대입 공격에 맞서는 **유일한** 장벽이다. 이는 의도적이다(assisted recovery는 설계상 2요소다 — 어느 한쪽만으로는 복호화되지 않는다). 하지만 이는 복구 문구의 엔트로피가 장식이 아니라 핵심을 지탱한다는 것을 의미한다. `keychain`(device) 슬롯의 비밀은 기기를 절대 떠나지 않으므로, 서버 침해에 전혀 노출되지 않는다.

---

## 4. 복구

`restoreEncryptedBackup`(`AppViewModel` 내)은 사용 가능한 슬롯을 시도하며 복호화한다: device key, 복구 문구, 또는 passkey. 모든 모드에서 봉투는 로컬에서 로드되거나 Supabase에서 가져온 뒤 **기기에서 복호화된다** — 서버는 절대 복호화하지 않는다.

### 4.1 복구 문구

`BackupRecoveryPhrase`(`LavaSecCore`)는 `SecRandom`으로부터 거부 표집(rejection sampling)을 사용하여 **8단어 CVCV 문구**(자음-모음-자음-모음)를 생성하며(토큰당 ~13.2비트 → **총 ~105비트**), 소문자로 정규화한다. **(Implemented)** 복원은 슬롯을 시도하기 전에 파싱/정규화를 통해 사용자 포맷팅(공백/대소문자)을 허용한다.

이것은 사용자의 **기기 외부(off-device)** 복구 요소다 — 사용자가 저장하며, 절대 업로드되지 않는다. 개인정보 보호 강화(§5)에 따라, 문구 복사는 **선택 사항**이며, 사용될 때는 전역 pasteboard 노출을 강제하는 대신 로컬 전용 / 만료되는(10분) pasteboard를 통한다.

### 4.2 Assisted recovery(2요소 조합)

복구 문구만으로는 `assistedRecovery` 슬롯이 잠금 해제되지 **않는다**. 슬롯 비밀은 **두** 절반 모두에서 파생된다:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

세 세그먼트는 실제 UTF-8 입력에서 **NUL 바이트(`0x00`) 구분자**로 연결된다 — 즉, 해시되는 문자열은 `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase`이며, 위의 `‖`는 단순 연결이 아니라 NUL로 구분된 연결을 나타낸다. `serverRecoveryShare`는 서버 측 봉투 메타데이터에 저장되는 무작위 값이며, `normalizedPhrase`는 사용자의 복구 문구다. **어느 한쪽만으로는 복호화되지 않는다** — 복원에는 (백업과 함께 가져온) 서버 share *그리고* 사용자가 보유한 문구가 필요하다. **(Implemented)**

### 4.3 Passkey 복구 — 제로 지식, PRF 파생

선택적 `passkey` 슬롯은 하드웨어 기반 요소를 추가하며, **제로 지식**이다: 그 unwrap key는 authenticator의 WebAuthn PRF(`hmac-secret`) 출력으로부터 **기기에서** 파생된다. 서버는 passkey를 등록하지 않고, WebAuthn 챌린지를 발급하지 않으며, 복구 비밀을 저장하지 않는다 — 서버 릴리스 단계가 없다.

- **등록/assertion:** `BackupPasskeyCoordinator`(`LavaSecApp`)는 `ASAuthorizationPlatformPublicKeyCredentialProvider`를 통해 WebAuthn을 실행하며, relying party는 **`lavasecurity.app`**, credential별 salt에 대해 PRF 확장을 요청하고 사용자 확인을 요구한다.
- **키 파생(제로 지식):** authenticator는 **기기를 절대 떠나지 않는** PRF 출력을 반환한다. `ZeroKnowledgeBackupEnvelope.makeWithPRF`(`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`)는 그 PRF 출력으로부터 슬롯의 래핑 키를 HKDF-SHA256으로 파생하고(info `"LavaSec passkey backup PRF v1"`) payload key를 AES-GCM으로 래핑한다. 비밀이 아닌 PRF salt와 credential ID만 슬롯에 영속화된다. 복원 시 `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput`이 credential을 다시 assert하여 동일한 PRF 출력을 재현하고, `decryptWithPasskeyPRFOutput`이 슬롯을 로컬에서 unwrap한다. 서버는 passkey 비밀을 **전혀** 보유하지 않으므로, 어떤 service-role 경로도 passkey로 보호된 백업을 복구할 수 없다.

이전의 에스크로 설계(서버 측 `recovery_secret`을 보유하는 service-role `backup_passkey_recovery` 테이블, 그리고 `backup_passkey_challenges` 테이블과 `/v1/backup/passkeys/*` Worker 엔드포인트)는 **Dropped**되었다: 테이블은 백엔드 마이그레이션에서 제거되었고, Worker는 passkey 경로를 갖지 않으며, `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift`는 `BackupPasskeyRecoveryService`와 모든 서버 에스크로 경로가 부재함을 명시적으로 단언한다. **(Implemented)**

> **프로덕션 준비도 주의사항:** 저장된 passkey를 물리적 기기에서 완전히 프로덕션 준비된 복구 가능 요소로 취급하는 것은 여전히 `lavasecurity.app`에 대한 webcredentials 연결에 의존한다. iOS 측은 선언되어 있고 — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements`가 `webcredentials:lavasecurity.app`을 담고 있음 — 서버 측(`apple-app-site-association` 파일과 헤더)은 이제 마케팅 사이트에서 호스팅된다. 특정 기기에서 해당 연결이 해소될 때까지, webcredentials 연결 경로는 실패할 수 있으며 `BackupPasskeyError.webCredentialsAssociationUnavailable`을 표출한다. passkey 요소 자체는 구현되어 있다. 실제 하드웨어에서의 종단 간(end-to-end) 준비도는 **Planned**다.

---

## 5. 데이터 최소화 및 개인정보 보호 태세

- **선택적 계정.** 보호 기능은 계정 없이 작동한다. 로그인은 설정 백업만 활성화한다.
- **로컬 평문만.** 전화기는 평문 설정과 복호화 비밀이 존재하는 유일한 곳이다. Supabase는 사용자당 하나의 불투명 봉투를 보유한다.
- **최소화된 payload.** §3.2의 설정만 백업된다. `isPaid`, QA 플래그, 진단, 스냅샷, 전체 blocklist 바이트는 제외된다. blocklist는 카탈로그 ID로 참조되며 절대 임베드되지 않는다.
- **브라우징/DNS 텔레메트리 없음.** 일상적인 DNS 쿼리나 도메인별 텔레메트리를 위한 서버 측 테이블은 없다. 필터링은 기기에 머문다.
- **잠금 해제 자료는 기기 로컬.** 백업 잠금 해제 자료는 `…ThisDeviceOnly` 접근성으로 저장되며 iCloud 동기화되지 **않는다**. 이는 원래 계획의 동기화 가능 Keychain 설계를 **뒤집은** 것으로, Lava는 iCloud를 통해 잠금 해제 자료를 조용히 동기화하지 않는다(`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implemented; 이전 계획을 뒤집음.)**

### 계정 삭제

삭제는 **Implemented**이며 직접 클라이언트 삭제가 아니라 인증된 Worker 엔드포인트를 통해 실행된다. `AccountAuthService.deleteAccount`는 사용자의 access token을 `POST /v1/account/delete`로 보낸다. `lavasec-api` Worker(service role)는 사용자의 `bug_reports`(그리고 그 R2 첨부 파일), `user_backups`, `entitlements`, `user_settings`, `profiles` 행을 삭제한 뒤, admin API를 통해 Supabase Auth 사용자를 삭제하고, 삭제된 상태 + 연결된 제공자만 반환한다. 그 후 앱은 로컬에서 로그아웃하고 백업 잠금 해제 자료를 지운다(`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> 참고: 삭제 계획의 YAML frontmatter는 이미 `status: Done`으로 읽히며 `plans/implemented/`에 위치한다. 오래된 **본문 내** 주석은 `Status: Backlog.`로 읽히지만, lane-folder 규칙(폴더가 권위 있음)과 코드 존재(앱 + Worker 둘 다 존재함)에 따라 이 기능은 **Implemented**다. 본문 내 줄은 frontmatter가 아니라 문서 버그다.

---

## 6. 상태 요약

| 영역 | 세부 내용 | 상태 |
|---|---|---|
| Supabase를 통한 Apple / Google `id_token` 로그인 | 네이티브 흐름, 해시된 nonce, raw-URLRequest 교환 | Implemented |
| 이메일/비밀번호 로그인 | 비밀번호 보유 거부됨 | Dropped |
| Keychain의 세션(기기 로컬, 제공자별) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implemented |
| AES-256-GCM 봉투 + PBKDF2-HMAC-SHA256(210k) 키 슬롯 | 클라이언트 측; 암호문 + 비밀이 아닌 메타데이터만 `user_backups`(RLS)로 | Implemented |
| Passwordless 설정(device + assisted-recovery + 선택적 passkey 슬롯) | `makePasswordless` | Implemented |
| 라이브 흐름의 password 키 슬롯 | 테스트용으로만 `LavaSecCore`에 남아 있음 | Dropped |
| 복구 문구(8단어 CVCV, ~105비트) | 기기 외부 요소 | Implemented |
| Assisted recovery(SHA256를 통한 서버 share + 문구, NUL 구분) | 2요소; 어느 한쪽만으로는 안 됨 | Implemented |
| Passkey 복구(제로 지식, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | PRF 출력 HKDF 파생 슬롯, 서버 비밀 없음 | Implemented |
| 하드웨어에서 프로덕션 준비 요소로서의 passkey | webcredentials 연결 필요(AASA는 마케팅 사이트에서 호스팅됨) | Planned |
| 계정 삭제(인증된 Worker, service role) | 백업/설정/엔타이틀먼트/프로필/첨부 + Auth 사용자 제거 | Implemented |
| 잠금 해제 자료에 대한 생체 인증/사용자 존재 게이트 | 릴리스 게이트 검토 항목 | Planned |
| `AppViewModel`에서 `EncryptedBackupCoordinator` 추출 | 모듈화만; 보안 모델 변경 없음 | In progress |

---

## 관련 문서

- [System Overview](./system-overview.md) — 신뢰 경계를 포함한 전체 시스템을 한 화면에서.
- [iOS Client](./ios-client.md) — `AppViewModel`과 백업을 구동하는 앱 타깃.
- [Backend & Data](./backend-and-data.md) — `lavasec-api` Worker, Supabase RLS, 그리고 `user_backups` 저장소.
- [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) — 백업 payload에 담기는 설정을 가진 resolver 프리셋과 전송 방식.
