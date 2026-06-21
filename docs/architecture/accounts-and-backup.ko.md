---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# 계정 및 제로 지식 백업

> **대상 독자:** 엔지니어.
> **권위:** 이 문서와 계획(plan)이 충돌할 경우, **코드가 우선합니다** — 차이는 본문에 그때그때 표시됩니다. 상태는 계획상의 목표가 아니라 코드로 확인된 실제를 반영합니다. 상태 범례: **구현됨**(출시되어 코드에서 확인됨), **진행 중**(일부만 반영됨), **계획됨**(설계되었으나 미구현), **폐기됨**(거부되거나 되돌려짐).

계정은 **선택 사항**이에요. 핵심 보호 기능은 영원히 무료이며 계정이 필요 없어요. 로그인은 오직 *설정*을 암호화해서 백업하고 새 기기에서 복원할 수 있도록 하기 위해 존재해요. 이 문서는 인증 흐름, 세션이 저장되는 위치, 제로 지식 백업 봉투(envelope), 복구 경로, 그리고 서버가 무엇을 볼 수 있고 볼 수 없는지를 정확히 다뤄요.

이 문서가 뒷받침하는 핵심 개인정보 약속은 다음과 같아요:

> 모든 DNS 필터링은 기기에서 이루어지며, Lava는 사용자의 브라우징을 자사 서버로 절대 라우팅하지 않고 사용자가 방문하는 도메인의 흐름을 절대 수신하지 않아요 — 백엔드는 오직 카탈로그 메타데이터, 사용자별 불투명한 암호화 백업, 그리고 사용자가 보내기로 선택한 익명화된 진단 정보만 보관해요.

컴포넌트 분리: 순수 암호화 + 요청 구성은 `LavaSecCore`에 있고, 오케스트레이션 + UI는 `LavaSecApp`에 있어요. 형제 문서: [시스템 개요](./system-overview.md), [iOS 클라이언트](./ios-client.md), [백엔드 및 데이터](./backend-and-data.md), [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md).

---

## 1. 인증 흐름

**제공자: Apple과 Google만.** **(구현됨)** `AccountAuthProvider`는 정확히 `.apple`과 `.google`만 열거해요(`AccountAuthService.swift`). 이메일/비밀번호 — 그리고 인증을 우회하는 모든 지원팀 보조 복구 — 는 명시적으로 **폐기됨**이에요. 비밀번호를 직접 관리하면 재설정/MFA/잠금/유출 대응 의무가 추가되는데, Apple/Google만으로 충분한 상황에서 그 복잡성을 감수할 가치가 없으며, 우회 복구는 제로 지식 보장을 깨뜨리기 때문이에요.

두 제공자 모두 Supabase Swift SDK나 웹 OAuth가 아니라 **네이티브 `id_token` grant**를 사용해요:

1. **네이티브로 로그인.** Apple은 AuthenticationServices를 통해, Google은 GoogleSignIn SDK를 통해 로그인해요. 각각 제공자 `id_token`을 반환해요(Google은 액세스 토큰도 함께). 앱은 CSPRNG 원시(raw) 논스를 생성하고 이를 SHA256으로 해시한 뒤 그 해시를 제공자에게 전달하므로, 발급되는 `id_token`이 그 논스에 바인딩돼요. **(구현됨)**
2. **Supabase에서 교환.** `SupabaseIDTokenAuth`(`LavaSecCore`)는 Supabase Auth `auth/v1/token?grant_type=id_token`로 가는 원시 `URLRequest`를 구성하여 `provider` + `id_token` + 선택적 `access_token` + **원시** 논스를 `apikey` 헤더와 함께 POST해요(Supabase가 바인딩을 검증하고 재전송을 거부할 수 있도록). SDK는 없어요. `LavaSecCore`는 네트워크/인증 의존성에서 자유로운 상태를 유지해요. **(구현됨)**
3. **세션 수신.** Supabase는 토큰을 검증하고 세션을 반환해요: 액세스 토큰, 리프레시 토큰, 만료 시각, 그리고 사용자 레코드(provider/providers). 갱신은 동일한 헬퍼를 `grant_type=refresh_token`으로 사용해요.

`AccountAuthService`(`@MainActor`, `LavaSecApp`)가 이 모든 것을 오케스트레이션해요 — 네이티브 흐름을 실행하고, 교환을 수행하고, 세션을 저장하고 갱신하며, `AccountAuthState`를 노출하고, Worker를 통해 계정 삭제를 처리해요.

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

로그인에서 유일하게 영구 저장되는 것은 Supabase 세션 — JSON 형태의 액세스 및 리프레시 토큰이에요. Supabase Auth 사용자와 사용자가 소유한 행(row)을 넘어서, 사용자가 누구인지에 대한 서버 측 미러는 **없어요**.

- **위치:** `AccountSessionKeychainStore`(`LavaSecApp`), Keychain 서비스 `com.lavasec.account-session`, **제공자별**로 저장(`supabase-session-apple` / `supabase-session-google`, 그리고 레거시 계정 마이그레이션). **(구현됨)**
- **접근성:** 모든 저장소는 `GenericKeychainStore`(`LavaSecCore`)를 공유하며, `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`로 고정돼요. 이는 **기기 로컬이고, iCloud로 동기화되지 않으며, 기기 백업에도 포함되지 않음**을 의미해요. **(구현됨)**

동일한 `GenericKeychainStore` 메커니즘이 세 가지 저장소를 뒷받침해요: 계정 세션, 백업 잠금 해제 자료(`BackupKeychainStore`, 서비스 `com.lavasec.zero-knowledge-backup`), 그리고 앱 패스코드. 이들 중 어느 것도 iCloud Keychain을 통해 동기화되지 않아요.

> **검토 중인 미해결 항목(주장된 동작이 아님):** 현재 접근성 클래스에는 생체 인증/사용자 존재 게이트가 없어요(`SecAccessControl`의 `.userPresence`/`.biometryCurrentSet` 없음). 잠금 해제 자료를 존재 게이트가 적용된 접근 제어로 강화할지는 출시 게이트 검토 항목으로 추적되고 있어요. 오늘 출시된 값은 after-first-unlock-this-device-only예요. **(계획됨)**

---

## 3. 제로 지식 백업

### 3.1 정확히 무엇인가

암호화 백업을 켜면 **iOS 클라이언트**가 *설정*의 최소화된 사본을 암호화하여 암호문과 비밀이 아닌 메타데이터만 Supabase에 업로드해요. 평문과 복호화 비밀이 존재하는 유일한 장소는 전화기예요.

> **제로 지식 백업:** 클라이언트 측 AES-256-GCM 봉투. 무작위 페이로드 키는 슬롯별 키 슬롯에 래핑돼요 — 비밀번호/문구/기기/보조 슬롯에는 PBKDF2-HMAC-SHA256(210k 반복), PRF 패스키 슬롯에는 HKDF-SHA256을 사용해요. 암호문 + 비밀이 아닌 메타데이터만 Supabase `user_backups`(사용자별 RLS)에 업로드돼요. 서버는 사용자가 보유한 비밀 없이는 복호화할 수 없어요. 패스키 슬롯 **역시** 제로 지식이에요: 언래핑 키는 인증기의 WebAuthn PRF(`hmac-secret`) 출력으로부터 기기에서 파생되며, 서버는 패스키 비밀을 보관하지 않아요(§4.3 참조).

### 3.2 무엇이 백업되는가 (최소화된 페이로드)

`BackupConfigurationPayload`(`LavaSecCore`)는 봉인되는 평문이에요. 의도적으로 작게 만들어졌고 `AppConfiguration`으로 왕복(round-trip)돼요. **(구현됨)**

**포함:** 활성화된 차단 목록 **ID**(목록 바이트가 아닌 카탈로그 참조), 허용/차단 도메인, 리졸버 프리셋 / 커스텀 리졸버, 로컬 로그 환경설정, LavaGuard 원장(ledger), 보호 힌트, 그리고 커스텀 차단 목록 소스 메타데이터.

**제외:** `isPaid`(권한은 로컬), QA 플래그, 진단, 필터 스냅샷, 그리고 전체 차단 목록 내용(카탈로그 ID로만 참조). 사용자의 브라우징 기록과 DNS 쿼리는 이 페이로드에 절대 포함되지 않아요. 기기가 그것들을 일상적인 텔레메트리 스트림으로 기록하지 않기 때문이에요.

### 3.3 봉투 (클라이언트 측 암호화)

`ZeroKnowledgeBackupEnvelope`(`LavaSecCore`)가 암호화를 구현해요. **(구현됨)**

1. **페이로드 암호화.** 최소화된 페이로드는 무작위 **32바이트 페이로드 키**(`SecRandomCopyBytes`로 생성) 아래에서 **AES-256-GCM**으로 한 번 봉인돼요.
2. **키 래핑 (키 슬롯).** 그 단일 페이로드 키는 비밀마다 하나씩, 하나 이상의 **키 슬롯**으로 독립적으로 래핑되며, 그런 다음 페이로드 키의 사본을 AES-GCM으로 래핑해요. 어느 한 슬롯의 비밀이라도 백업 전체를 잠금 해제해요. 래핑 키 파생은 슬롯 종류별로 달라요: `password` / `recoveryPhrase` / `keychain`(기기) / `assistedRecovery` 슬롯은 슬롯마다 새로운 16바이트 무작위 솔트와 함께 **PBKDF2-HMAC-SHA256, 210,000 반복**(프로덕션; `defaultPasswordIterations = 210_000`)을 사용하고, `passkey` 슬롯은 인증기의 PRF 출력에 대해 **HKDF-SHA256**(info `"LavaSec passkey backup PRF v1"`)을 사용하며, 복원 시 출력을 재현할 수 있도록 비밀이 아닌 PRF 솔트가 슬롯에 영구 저장돼요.
3. **슬롯 종류.** 봉투는 다섯 가지 슬롯 종류를 지원해요: `password`, `recoveryPhrase`, `keychain`(기기 비밀), `assistedRecovery`, 그리고 `passkey`.

출시된 설정은 **비밀번호 없음(passwordless)**이에요(`makePasswordless`, `AppViewModel.turnOnEncryptedBackup`이 구동). 이는 **`keychain`(기기) 슬롯 + `assistedRecovery` 슬롯 + 선택적 `passkey` 슬롯**을 생성해요. `password` / `recoveryPhrase` 팩토리와 복호화 메서드는 레거시/하위 호환 봉투용으로 여전히 존재하지만(테스트로만 실행됨), 활성 UI는 비밀번호 전용 봉투를 절대 만들지 않아요 — 비밀번호 백업은 출시되지 않은 것으로 취급하세요. **(구현됨; 비밀번호 슬롯은 라이브 흐름에서 폐기됨.)**

**무결성 / 다운그레이드 방지:** `envelopeVersion`은 `1`로 강하게 고정되어 있고, 각 슬롯의 KDF는 종류별로 고정돼요 — 비밀번호/문구/기기/보조 슬롯에는 `PBKDF2-HMAC-SHA256`, PRF 패스키 슬롯에는 `HKDF-SHA256`. 지원되지 않는 버전이나 일치하지 않는 KDF는 거부되므로, 위조되거나 다운그레이드된 메타데이터가 언래핑을 약화시킬 수 없어요. **(구현됨)**

### 3.4 업로드 및 저장

`BackupSyncService`(`SupabaseBackupSyncService`, `LavaSecApp`)는 봉투를 Supabase PostgREST 테이블 `user_backups`에 **직접** 업로드하며, `user_id`로 upsert하고 사용자의 액세스 토큰으로 범위가 한정돼요. **봉투 업로드를 위한 Worker 경로는 없어요** — 클라이언트는 RLS 하에서 Supabase와 직접 통신하고, Worker는 계정 삭제 중에 `user_backups`를 삭제할 때만 그것을 건드려요. **(구현됨)**

`user_backups`에 저장되는 것:

- **암호문**, 그리고
- **비밀이 아닌 메타데이터만:** 암호 이름, 키 슬롯 레코드(솔트, 반복 횟수, 래핑된 키, 슬롯 레이블), `server_recovery_share`, `createdAt`, 그리고 바이트 크기.

이 행은 **행 수준 보안(row-level security)**으로 보호돼요: 각 행은 소유자만 읽기/쓰기할 수 있고(`auth.uid() = user_id`), 익명 역할은 접근 권한이 없어요. 크기는 DB 수준에서 암호문 약 256 KiB / 메타데이터 32 KiB로 제한돼요(`20260518000000_zero_knowledge_backups.sql`, `20260605000000_tighten_backup_envelope_constraints.sql`에서 강화됨). **(구현됨)**

### 3.5 보장 — 서버가 볼 수 있는 것과 볼 수 없는 것

**서버가 저장하는 것:** 암호문, KDF 솔트/반복 횟수, 래핑된 키 슬롯, `server_recovery_share`, 그리고 몇 가지 비밀이 아닌 필드(암호, 크기, 타임스탬프).

**서버가 절대 수신하거나 저장하지 않는 것:** 평문 설정/도메인/DNS 환경설정, 복구 문구, 모든 백업 비밀번호, 또는 언래핑된 페이로드 키.

**따라서:** Supabase는 사용자가 보유한 비밀 없이는 **백업을 복호화할 수 없어요**. 세 가지 복원 경로 — 기기 키 슬롯, 복구 문구(서버 공유와 결합, §4.2), 그리고 패스키 슬롯(인증기의 PRF 출력, §4.3) — 모두 **기기에서** 복호화되며, 서버는 그 어느 것에 대해서도 복호화 비밀을 보관하지 않아요. 이는 마이그레이션 주석과 개인정보 계획에서 단언되며, 테스트로 검증돼요(봉투 테스트는 업로드되는 형태에 평문 도메인/URL이 누출되지 않음을 확인해요).

**정확한 위협 모델 단서 — 과장하지 마세요.** **보조 복구(assisted-recovery)** 슬롯의 경우, 서버는 `user_backups`에서 `server_recovery_share`와 래핑된 `assistedRecovery` 슬롯을 *둘 다* 보관해요. 서버에 없는 유일한 것은 사용자의 복구 문구이며, Lava는 이를 절대 수신하지 않아요. 따라서 서버가 완전히 침해되더라도, 복구 문구의 엔트로피(약 105비트, §4.1 참조)와 210k 반복 PBKDF2 비용이 그 슬롯에 대한 오프라인 무차별 대입 공격을 막는 **유일한** 장벽이에요. 이는 의도적이에요(보조 복구는 설계상 2요소이며 — 어느 한쪽만으로는 복호화되지 않아요). 다만 이는 복구 문구 엔트로피가 장식이 아니라 핵심적인 역할을 한다는 것을 의미해요. `keychain`(기기) 슬롯의 비밀은 기기를 절대 떠나지 않으므로, 서버 침해에 전혀 노출되지 않아요.

---

## 4. 복구

백업은 복원할 수 있어야만 유용해요. `restoreEncryptedBackup`(`AppViewModel` 내)은 사용 가능한 슬롯을 시도하여 복호화해요: 기기 키, 복구 문구, 또는 패스키. 모든 모드에서 봉투는 로컬에서 로드되고(또는 Supabase에서 가져오고) 그런 다음 **기기에서 복호화**돼요 — 서버는 절대 복호화하지 않아요.

### 4.1 복구 문구

`BackupRecoveryPhrase`(`LavaSecCore`)는 `SecRandom`으로부터 거부 샘플링을 사용해 **8단어 CVCV 문구**(자음-모음-자음-모음)를 생성해요(토큰당 약 13.2비트 → **총 약 105비트**), 소문자로 정규화돼요. **(구현됨)** 복원은 슬롯을 시도하기 전에 파싱/정규화를 통해 사용자 서식(간격/대소문자)을 허용해요.

이는 사용자의 **기기 외부(off-device)** 복구 요소예요 — 사용자가 저장하며, 절대 업로드되지 않아요. 개인정보 강화(§5)에 따라, 문구 복사는 **선택 사항**이며, 사용될 때는 전역 클립보드 노출을 강제하는 대신 로컬 전용 / 만료되는(10분) 클립보드를 통해 이루어져요.

### 4.2 보조 복구 (2요소 결합)

복구 문구만으로는 `assistedRecovery` 슬롯을 잠금 해제하지 **못해요**. 슬롯 비밀은 **두** 절반 모두로부터 파생돼요:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

세 세그먼트는 실제 UTF-8 입력에서 **NUL 바이트(`0x00`) 구분자**로 결합돼요 — 즉, 해시되는 문자열은 `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase`이에요 — 따라서 위의 `‖`는 단순 연결이 아니라 NUL로 구분된 연결을 의미해요. `serverRecoveryShare`는 서버 측 봉투 메타데이터에 저장된 무작위 값이고, `normalizedPhrase`는 사용자의 복구 문구예요. **어느 한쪽만으로는 복호화되지 않아요** — 복원에는 서버 공유(백업과 함께 가져옴) *그리고* 사용자가 보유한 문구가 모두 필요해요. **(구현됨)**

### 4.3 패스키 복구 — 제로 지식, PRF 파생

선택적 `passkey` 슬롯은 하드웨어 기반 요소를 추가하며, **제로 지식**이에요: 그 언래핑 키는 인증기의 WebAuthn PRF(`hmac-secret`) 출력으로부터 **기기에서** 파생돼요. 서버는 패스키를 등록하지 않고, WebAuthn 챌린지를 발급하지 않으며, 복구 비밀을 저장하지 않아요 — 서버 릴리스 단계가 없어요.

- **등록/어서션:** `BackupPasskeyCoordinator`(`LavaSecApp`)는 `ASAuthorizationPlatformPublicKeyCredentialProvider`를 통해 WebAuthn을 실행하며, 신뢰 당사자(relying party)는 **`lavasecurity.app`**이고, 자격 증명별 솔트에 대해 PRF 확장을 요청하며 사용자 검증을 요구해요.
- **키 파생 (제로 지식):** 인증기는 **기기를 절대 떠나지 않는** PRF 출력을 반환해요. `ZeroKnowledgeBackupEnvelope.makeWithPRF`(`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`)는 그 PRF 출력으로부터 슬롯의 래핑 키를 HKDF-SHA256으로 파생하고(info `"LavaSec passkey backup PRF v1"`) 페이로드 키를 AES-GCM으로 래핑해요. 비밀이 아닌 PRF 솔트와 자격 증명 ID만 슬롯에 영구 저장돼요. 복원 시 `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput`이 자격 증명을 다시 어서트하여 동일한 PRF 출력을 재현하고, `decryptWithPasskeyPRFOutput`이 슬롯을 로컬에서 언래핑해요. 서버는 패스키 비밀을 **전혀** 보관하지 않으므로, 어떤 서비스 역할 경로도 패스키로 보호된 백업을 복구할 수 없어요.

이전의 에스크로 설계(서버 측 `recovery_secret`을 보관하는 서비스 역할 `backup_passkey_recovery` 테이블, 그리고 `backup_passkey_challenges` 테이블과 `/v1/backup/passkeys/*` Worker 엔드포인트)는 **폐기됨**이에요: 해당 테이블들은 백엔드 마이그레이션에서 제거되었고, Worker는 패스키 경로를 갖지 않으며, `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift`는 `BackupPasskeyRecoveryService`와 모든 서버 에스크로 경로가 부재함을 적극적으로 단언해요. **(구현됨)**

> **프로덕션 준비 단서:** 저장된 패스키를 물리적 기기에서 완전히 프로덕션 준비가 된 복구 가능 요소로 취급하는 것은 여전히 `lavasecurity.app`에 대한 webcredentials 연결에 달려 있어요. iOS 쪽은 선언되어 있어요 — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements`가 `webcredentials:lavasecurity.app`을 담고 있어요 — 그리고 서버 쪽(`apple-app-site-association` 파일과 헤더)은 이제 마케팅 사이트에 호스팅돼요. 특정 기기에서 그 연결이 해석되기 전까지는 webcredentials 연결 경로가 실패할 수 있으며 `BackupPasskeyError.webCredentialsAssociationUnavailable`을 표면화해요. 패스키 요소 자체는 구현되어 있어요. 실제 하드웨어에서의 종단 간(end-to-end) 준비 상태는 **계획됨**이에요.

---

## 5. 데이터 최소화 및 개인정보 자세

- **선택적 계정.** 보호는 계정 없이 작동해요. 로그인은 설정 백업만 활성화해요.
- **로컬 평문만.** 전화기는 평문 설정과 복호화 비밀이 존재하는 유일한 장소예요. Supabase는 사용자당 불투명한 봉투 하나를 보관해요.
- **최소화된 페이로드.** §3.2의 설정만 백업돼요. `isPaid`, QA 플래그, 진단, 스냅샷, 전체 차단 목록 바이트는 제외돼요. 차단 목록은 카탈로그 ID로 참조되며, 절대 임베드되지 않아요.
- **브라우징/DNS 텔레메트리 없음.** 일상적인 DNS 쿼리나 도메인별 텔레메트리를 위한 서버 측 테이블은 없어요. 필터링은 기기에 머물러요.
- **잠금 해제 자료는 기기 로컬.** 백업 잠금 해제 자료는 `…ThisDeviceOnly` 접근성으로 저장되며 iCloud로 동기화되지 **않아요**. 이는 원래 계획의 동기화 가능 Keychain 설계를 **뒤집은** 것으로, Lava는 잠금 해제 자료를 iCloud를 통해 조용히 동기화하지 않아요(`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(구현됨; 이전 계획을 뒤집음.)**

### 계정 삭제

삭제는 **구현됨**이며, 직접 클라이언트 삭제가 아니라 인증된 Worker 엔드포인트를 통해 실행돼요. `AccountAuthService.deleteAccount`는 사용자의 액세스 토큰을 `POST /v1/account/delete`로 보내요. `lavasec-api` Worker(서비스 역할)는 사용자의 `bug_reports`(및 그 R2 첨부 파일), `user_backups`, `entitlements`, `user_settings`, `profiles` 행을 삭제한 다음, 관리자 API를 통해 Supabase Auth 사용자를 삭제하며, 삭제 상태 + 연결된 제공자만 반환해요. 그런 다음 앱은 로컬에서 로그아웃하고 백업 잠금 해제 자료를 지워요(`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> 참고: 삭제 계획의 YAML 프런트매터는 이미 `status: Done`으로 되어 있고 `plans/implemented/`에 있어요. 오래된 **본문 내** 주석은 `Status: Backlog.`으로 되어 있지만, 레인 폴더 규칙(폴더가 권위 있음)과 코드 존재(앱 + Worker 모두 존재함)에 따라 이 기능은 **구현됨**이에요. 본문 내 줄은 프런트매터가 아니라 문서 버그예요.

---

## 6. 상태 요약

| 영역 | 세부 | 상태 |
|---|---|---|
| Supabase를 통한 Apple / Google `id_token` 로그인 | 네이티브 흐름, 해시된 논스, 원시 URLRequest 교환 | 구현됨 |
| 이메일/비밀번호 로그인 | 비밀번호 직접 관리 거부 | 폐기됨 |
| Keychain 세션 (기기 로컬, 제공자별) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | 구현됨 |
| AES-256-GCM 봉투 + PBKDF2-HMAC-SHA256(210k) 키 슬롯 | 클라이언트 측; 암호문 + 비밀이 아닌 메타데이터만 `user_backups`(RLS)로 | 구현됨 |
| 비밀번호 없는 설정 (기기 + 보조 복구 + 선택적 패스키 슬롯) | `makePasswordless` | 구현됨 |
| 라이브 흐름의 비밀번호 키 슬롯 | 테스트용으로만 `LavaSecCore`에 남음 | 폐기됨 |
| 복구 문구 (8단어 CVCV, 약 105비트) | 기기 외부 요소 | 구현됨 |
| 보조 복구 (서버 공유 + 문구를 SHA256으로, NUL 구분) | 2요소; 어느 한쪽만으로는 불가 | 구현됨 |
| 패스키 복구 (제로 지식, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | PRF 출력 HKDF 파생 슬롯, 서버 비밀 없음 | 구현됨 |
| 하드웨어에서 프로덕션 준비 요소로서의 패스키 | webcredentials 연결 필요(AASA는 마케팅 사이트에 호스팅됨) | 계획됨 |
| 계정 삭제 (인증된 Worker, 서비스 역할) | 백업/설정/권한/프로필/첨부 파일 + Auth 사용자 제거 | 구현됨 |
| 잠금 해제 자료에 대한 생체 인증/사용자 존재 게이트 | 출시 게이트 검토 항목 | 계획됨 |
| `AppViewModel`에서 `EncryptedBackupCoordinator` 추출 | 모듈화만; 보안 모델 변경 없음 | 진행 중 |

---

## 관련 문서

- [시스템 개요](./system-overview.md) — 신뢰 경계를 포함해 전체 시스템을 한 화면에.
- [iOS 클라이언트](./ios-client.md) — 백업을 구동하는 `AppViewModel`과 앱 타깃.
- [백엔드 및 데이터](./backend-and-data.md) — `lavasec-api` Worker, Supabase RLS, 그리고 `user_backups` 저장.
- [DNS 필터링 및 차단 목록](./dns-filtering-and-blocklists.md) — 백업 페이로드에 담기는 설정인 리졸버 프리셋과 전송 방식.
