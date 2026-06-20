---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Konten & Zero-Knowledge-Backup

> **Zielgruppe:** Entwickler.
> **Maßgeblichkeit:** Wenn dieses Dokument und ein Plan sich widersprechen, **gewinnt der Code** — Abweichungen werden direkt im Text genannt. Der Status spiegelt die im Code bestätigte Realität wider, nicht die Wunschvorstellung eines Plans. Statuslegende: **Umgesetzt** (ausgeliefert und im Code bestätigt), **In Arbeit** (teilweise gelandet), **Geplant** (entworfen, noch nicht gebaut), **Verworfen** (abgelehnt oder zurückgenommen).

Konten sind **optional**. Der Kernschutz ist für immer kostenlos und braucht kein Konto; die Anmeldung gibt es nur, um deine *Einstellungen* verschlüsselt zu sichern, damit du sie auf einem neuen Gerät wiederherstellen kannst. Dieses Dokument behandelt den Anmeldeablauf, wo die Session lebt, die Zero-Knowledge-Backup-Hülle, die Wiederherstellungswege und ganz genau, was der Server sehen kann und was nicht.

Das zentrale Datenschutzversprechen, dem dieses Dokument dient:

> Die gesamte DNS-Filterung passiert auf dem Gerät; Lava leitet dein Surfen niemals über seine Server und bekommt niemals den Strom der Domains zu sehen, die du besuchst — das Backend hält nur Katalog-Metadaten, ein undurchsichtiges, pro Nutzer verschlüsseltes Backup und anonymisierte Diagnosedaten, die du freiwillig sendest.

Aufteilung der Komponenten: Reine Krypto + das Bauen von Anfragen liegt in `LavaSecCore`; Orchestrierung + UI liegt in `LavaSecApp`. Geschwister: [System-Überblick](./system-overview.md), [iOS-Client](./ios-client.md), [Backend & Daten](./backend-and-data.md), [DNS-Filterung & Blocklisten](./dns-filtering-and-blocklists.md).

---

## 1. Anmeldeablauf {#1-authentication-flow}

**Anbieter: nur Apple und Google.** **(Umgesetzt)** `AccountAuthProvider` zählt genau `.apple` und `.google` auf (`AccountAuthService.swift`). E-Mail/Passwort — und jede support-gestützte Wiederherstellung, die die Authentifizierung umgeht — ist ausdrücklich **Verworfen**; Passwörter selbst zu verwalten würde Pflichten rund um Zurücksetzen/MFA/Sperren/Datenlecks mit sich bringen, die den Aufwand nicht wert sind, solange Apple/Google ausreichen, und eine Umgehungs-Wiederherstellung würde die Zero-Knowledge-Garantie brechen.

Beide Anbieter nutzen den **nativen `id_token`-Grant**, nicht das Supabase Swift SDK und nicht Web-OAuth:

1. **Nativ anmelden.** Apple über AuthenticationServices; Google über das GoogleSignIn SDK. Jeder liefert ein Anbieter-`id_token` (Google zusätzlich ein Access-Token). Die App erzeugt eine CSPRNG-Roh-Nonce, hasht sie mit SHA256 und übergibt den Hash an den Anbieter, damit das ausgestellte `id_token` daran gebunden ist. **(Umgesetzt)**
2. **Bei Supabase eintauschen.** `SupabaseIDTokenAuth` (`LavaSecCore`) baut einen rohen `URLRequest` an Supabase Auth `auth/v1/token?grant_type=id_token` und schickt `provider` + `id_token` + optional `access_token` + die **rohe** Nonce (damit Supabase die Bindung prüfen und Replays ablehnen kann), zusammen mit dem `apikey`-Header. Kein SDK; `LavaSecCore` bleibt frei von Netzwerk-/Auth-Abhängigkeiten. **(Umgesetzt)**
3. **Eine Session erhalten.** Supabase verifiziert das Token und gibt eine Session zurück: ein Access-Token, ein Refresh-Token, ein Ablaufdatum und einen Nutzer-Datensatz (provider/providers). Der Refresh nutzt denselben Helfer mit `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orchestriert das alles — es führt die nativen Abläufe aus, macht den Tausch, speichert und erneuert Sessions, stellt `AccountAuthState` bereit und steuert die Kontolöschung über den Worker.

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

## 2. Session- & Keychain-Speicherung {#2-session--keychain-storage}

Das **Einzige**, was von der Anmeldung gespeichert wird, ist die Supabase-Session — Access- und Refresh-Tokens als JSON. Es gibt **kein** serverseitiges Abbild davon, wer du bist, jenseits des Supabase-Auth-Nutzers und der Zeilen, die dir gehören.

- **Wo:** `AccountSessionKeychainStore` (`LavaSecApp`), Keychain-Service `com.lavasec.account-session`, gespeichert **pro Anbieter** (`supabase-session-apple` / `supabase-session-google`, plus eine Migration für Altkonten). **(Umgesetzt)**
- **Zugänglichkeit:** Alle Stores teilen sich `GenericKeychainStore` (`LavaSecCore`), festgenagelt auf `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Das heißt **gerätelokal, nicht über iCloud synchronisiert und nicht in Gerätebackups enthalten**. **(Umgesetzt)**

Dieselbe `GenericKeychainStore`-Mechanik trägt drei Stores: die Konto-Session, das Backup-Entsperrmaterial (`BackupKeychainStore`, Service `com.lavasec.zero-knowledge-backup`) und den App-Passcode. Keiner davon synchronisiert über die iCloud-Keychain.

> **Offener Prüfpunkt (kein zugesichertes Verhalten):** Die aktuelle Zugänglichkeitsklasse hat kein Biometrie-/Anwesenheits-Gate (kein `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Ob das Entsperrmaterial auf eine anwesenheitsgeschützte Zugriffskontrolle verschärft wird, ist als Prüfpunkt vor dem Release vermerkt; der ausgelieferte Wert ist heute after-first-unlock-this-device-only. **(Geplant)**

---

## 3. Zero-Knowledge-Backup {#3-zero-knowledge-backup}

### 3.1 Was es genau ist {#31-what-it-is-precisely}

Wenn du das Verschlüsselte Backup einschaltest, verschlüsselt der **iOS-Client** eine minimierte Kopie deiner *Einstellungen* und lädt nur den Chiffretext plus geheimnisfreie Metadaten zu Supabase hoch. Das Telefon ist der einzige Ort, an dem der Klartext und die entschlüsselnden Geheimnisse je existieren.

> **Zero-Knowledge-Backup:** Clientseitige AES-256-GCM-Hülle; der zufällige Payload-Schlüssel wird in Schlüssel-Slots pro Slot eingepackt — PBKDF2-HMAC-SHA256 (210k Iterationen) für die Passwort-/Phrase-/Geräte-/Assisted-Slots, HKDF-SHA256 für den PRF-Passkey-Slot. Nur Chiffretext + geheimnisfreie Metadaten gehen zu Supabase `user_backups` (RLS pro Nutzer). Der Server kann ohne ein nutzergehaltenes Geheimnis nicht entschlüsseln. Der Passkey-Slot ist **ebenfalls** Zero-Knowledge: Sein Entpack-Schlüssel wird auf dem Gerät aus der WebAuthn-PRF-Ausgabe (`hmac-secret`) des Authentifikators abgeleitet, und der Server hält kein Passkey-Geheimnis (siehe §4.3).

### 3.2 Was gesichert wird (der minimierte Payload) {#32-what-gets-backed-up-the-minimized-payload}

`BackupConfigurationPayload` (`LavaSecCore`) ist der Klartext, der versiegelt wird. Er ist bewusst klein und lässt sich verlustfrei in `AppConfiguration` und zurück wandeln. **(Umgesetzt)**

**Enthalten:** aktivierte Blocklisten-**IDs** (Katalogverweise, nicht die Listen-Bytes), erlaubte/blockierte Domains, Resolver-Preset / eigener Resolver, Einstellungen zum lokalen Verlauf, das LavaGuard-Ledger, ein Schutz-Hinweis und Quell-Metadaten zu eigenen Blocklisten.

**Ausgeschlossen:** `isPaid` (die Berechtigung ist lokal), QA-Flags, Diagnosedaten, Filter-Snapshots und der vollständige Inhalt der Blocklisten (nur per Katalog-ID referenziert). Dein Browserverlauf und deine DNS-Anfragen sind nie Teil dieses Payloads, weil das Gerät sie nie als laufenden Telemetrie-Strom aufzeichnet.

### 3.3 Die Hülle (clientseitige Krypto) {#33-the-envelope-client-side-crypto}

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) setzt die Krypto um. **(Umgesetzt)**

1. **Payload-Verschlüsselung.** Der minimierte Payload wird einmal mit **AES-256-GCM** unter einem zufälligen **32-Byte-Payload-Schlüssel** versiegelt (erzeugt mit `SecRandomCopyBytes`).
2. **Schlüssel einpacken (Schlüssel-Slots).** Dieser eine Payload-Schlüssel wird unabhängig in einen oder mehrere **Schlüssel-Slots** eingepackt, einen pro Geheimnis, und packt dann per AES-GCM eine Kopie des Payload-Schlüssels ein. Das Geheimnis jedes einzelnen Slots entsperrt das gesamte Backup. Die Ableitung des Einpack-Schlüssels ist pro Slot-Art unterschiedlich: Die `password`- / `recoveryPhrase`- / `keychain`- (Gerät) / `assistedRecovery`-Slots nutzen **PBKDF2-HMAC-SHA256, 210.000 Iterationen** (Produktion; `defaultPasswordIterations = 210_000`) mit einem frischen 16-Byte-Zufalls-Salt pro Slot; der `passkey`-Slot nutzt **HKDF-SHA256** über die PRF-Ausgabe des Authentifikators (info `"LavaSec passkey backup PRF v1"`), wobei das geheimnisfreie PRF-Salt im Slot gespeichert wird, damit die Wiederherstellung die Ausgabe reproduzieren kann.
3. **Slot-Arten.** Die Hülle unterstützt fünf Slot-Arten: `password`, `recoveryPhrase`, `keychain` (Gerätegeheimnis), `assistedRecovery` und `passkey`.

Das ausgelieferte Setup ist **passwortlos** (`makePasswordless`, getrieben von `AppViewModel.turnOnEncryptedBackup`). Es erstellt einen **`keychain`- (Gerät) Slot + einen `assistedRecovery`-Slot + einen optionalen `passkey`-Slot**. Die `password`- / `recoveryPhrase`-Factories und Entschlüsselungsmethoden existieren weiterhin für alte/abwärtskompatible Hüllen (nur von Tests ausgeübt), aber die aktive UI erstellt nie eine reine Passwort-Hülle — behandle Passwort-Backup als nicht ausgeliefert. **(Umgesetzt; Passwort-Slot Verworfen im Live-Ablauf.)**

**Integrität / Anti-Downgrade:** `envelopeVersion` ist hart auf `1` festgenagelt, und die KDF jedes Slots ist pro Art festgenagelt — `PBKDF2-HMAC-SHA256` für die Passwort-/Phrase-/Geräte-/Assisted-Slots, `HKDF-SHA256` für den PRF-Passkey-Slot. Nicht unterstützte Versionen oder unpassende KDFs werden abgelehnt, sodass gefälschte oder herabgestufte Metadaten das Entpacken nicht schwächen können. **(Umgesetzt)**

### 3.4 Hochladen & Speichern {#34-upload--storage}

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) lädt die Hülle **direkt** in die Supabase-PostgREST-Tabelle `user_backups` hoch, mit Upsert auf `user_id`, eingegrenzt durch das Access-Token des Nutzers. **Es gibt keine Worker-Route für das Hochladen der Hülle** — der Client spricht unter RLS direkt mit Supabase; der Worker fasst `user_backups` nur an, um sie bei der Kontolöschung zu löschen. **(Umgesetzt)**

Was in `user_backups` landet:

- der **Chiffretext** und
- **nur geheimnisfreie Metadaten:** Chiffren-Name, die Schlüssel-Slot-Datensätze (Salts, Iterationszahlen, eingepackte Schlüssel, Slot-Labels), der `server_recovery_share`, `createdAt` und die Byte-Größe.

Die Zeile ist durch **Row-Level Security** geschützt: Jede Zeile ist nur von ihrem Besitzer lesbar/schreibbar (`auth.uid() = user_id`); die anonyme Rolle hat keinen Zugriff. Die Größe ist auf DB-Ebene auf ~256 KiB Chiffretext / 32 KiB Metadaten gedeckelt (`20260518000000_zero_knowledge_backups.sql`, verschärft in `20260605000000_tighten_backup_envelope_constraints.sql`). **(Umgesetzt)**

### 3.5 Die Garantie — was der Server sehen kann und was nicht {#35-the-guarantee--what-the-server-can-and-cannot-see}

**Der Server speichert:** Chiffretext, KDF-Salts/-Iterationen, eingepackte Schlüssel-Slots, den `server_recovery_share` und ein paar geheimnisfreie Felder (Chiffre, Größe, Zeitstempel).

**Der Server bekommt oder speichert nie:** die Klartext-Einstellungen/-Domains/-DNS-Präferenzen, den Wiederherstellungscode, irgendein Backup-Passwort oder den ausgepackten Payload-Schlüssel.

**Daher:** Supabase **kann ein Backup nicht entschlüsseln** ohne ein nutzergehaltenes Geheimnis. Alle drei Wiederherstellungswege — der Gerät-Schlüssel-Slot, der Wiederherstellungscode (kombiniert mit dem Server-Anteil, §4.2) und der Passkey-Slot (die PRF-Ausgabe des Authentifikators, §4.3) — entschlüsseln **auf dem Gerät**, und der Server hält für keinen davon ein Entschlüsselungsgeheimnis. Das wird in den Migrations-Kommentaren und im Datenschutzplan zugesichert und getestet (die Hüllen-Tests bestätigen, dass kein Klartext-Domain/-URL in die hochgeladene Form durchsickert).

**Präzise Bedrohungsmodell-Einschränkung — nicht überverkaufen.** Beim **Assisted-Recovery**-Slot hält der Server *sowohl* den `server_recovery_share` *als auch* den eingepackten `assistedRecovery`-Slot in `user_backups`. Das Einzige, was ihm fehlt, ist der Wiederherstellungscode des Nutzers, den Lava nie bekommt. Wenn der Server also vollständig kompromittiert wäre, ist die Entropie des Wiederherstellungscodes (~105 Bit, siehe §4.1) plus die 210k-Iterationen-PBKDF2-Kosten die **einzige** Barriere gegen ein Offline-Brute-Forcen dieses Slots. Das ist Absicht (Assisted Recovery ist von Natur aus zweistufig — keine Hälfte allein entschlüsselt), aber es heißt, dass die Entropie des Wiederherstellungscodes tragend ist, nicht dekorativ. Das Geheimnis des `keychain`- (Gerät) Slots verlässt nie das Gerät, ist also einer Server-Kompromittierung überhaupt nicht ausgesetzt.

---

## 4. Wiederherstellung {#4-recovery}

Ein Backup ist nur nützlich, wenn du es wiederherstellen kannst. `restoreEncryptedBackup` (in `AppViewModel`) entschlüsselt, indem es die verfügbaren Slots durchprobiert: Geräteschlüssel, Wiederherstellungscode oder Passkey. In jedem Modus wird die Hülle lokal geladen (oder von Supabase geholt) und dann **auf dem Gerät entschlüsselt** — der Server entschlüsselt nie.

### 4.1 Wiederherstellungscode {#41-recovery-phrase}

`BackupRecoveryPhrase` (`LavaSecCore`) erzeugt einen **8-Wort-CVCV-Code** (Konsonant-Vokal-Konsonant-Vokal) aus `SecRandom` mit Rejection Sampling (~13,2 Bit/Token → **~105 Bit insgesamt**), normalisiert kleingeschrieben. **(Umgesetzt)** Die Wiederherstellung verträgt die Formatierung des Nutzers (Leerzeichen/Groß-Klein) durch Parsen/Normalisieren, bevor der Slot probiert wird.

Das ist der **geräteunabhängige** Wiederherstellungsfaktor des Nutzers — vom Nutzer gespeichert, nie hochgeladen. Gemäß der Datenschutzhärtung (§5) ist das Kopieren des Codes **optional** und läuft, wenn genutzt, über eine nur-lokale / ablaufende (10-Minuten-)Zwischenablage statt einer erzwungenen globalen Zwischenablage-Exposition.

### 4.2 Assisted Recovery (die Zwei-Faktor-Kombination) {#42-assisted-recovery-the-two-factor-combination}

Der Wiederherstellungscode allein entsperrt den `assistedRecovery`-Slot **nicht**. Das Slot-Geheimnis wird aus **beiden** Hälften abgeleitet:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

Die drei Segmente werden in der tatsächlichen UTF-8-Eingabe durch einen **NUL-Byte-(`0x00`)-Trenner** verbunden — d.h. der gehashte String ist `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — das `‖` oben bezeichnet also eine NUL-getrennte Verkettung, keine bloße Aneinanderreihung. `serverRecoveryShare` ist ein zufälliger Wert, der serverseitig in den Hüllen-Metadaten gespeichert ist; `normalizedPhrase` ist der Wiederherstellungscode des Nutzers. **Keine Hälfte allein entschlüsselt** — die Wiederherstellung braucht den Server-Anteil (mit dem Backup geholt) *und* den nutzergehaltenen Code. **(Umgesetzt)**

### 4.3 Passkey-Wiederherstellung — Zero-Knowledge, PRF-abgeleitet {#43-passkey-recovery--zero-knowledge-prf-derived}

Der optionale `passkey`-Slot fügt einen hardwaregestützten Faktor hinzu, und er ist **Zero-Knowledge**: Sein Entpack-Schlüssel wird **auf dem Gerät** aus der WebAuthn-PRF-Ausgabe (`hmac-secret`) des Authentifikators abgeleitet. Der Server registriert keinen Passkey, stellt keine WebAuthn-Challenges aus und speichert kein Wiederherstellungsgeheimnis — es gibt keinen Server-Freigabeschritt.

- **Registrierung/Assertion:** `BackupPasskeyCoordinator` (`LavaSecApp`) führt WebAuthn über `ASAuthorizationPlatformPublicKeyCredentialProvider` aus, mit Relying Party **`lavasecurity.app`**, fordert die PRF-Erweiterung auf einem Salt pro Credential an und verlangt eine Nutzerverifizierung.
- **Schlüsselableitung (Zero-Knowledge):** Der Authentifikator gibt eine PRF-Ausgabe zurück, die **nie das Gerät verlässt**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) leitet per HKDF-SHA256 den Einpack-Schlüssel des Slots aus dieser PRF-Ausgabe ab (info `"LavaSec passkey backup PRF v1"`) und packt per AES-GCM den Payload-Schlüssel ein; nur das geheimnisfreie PRF-Salt und die Credential-ID werden im Slot gespeichert. Bei der Wiederherstellung asserten `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` das Credential erneut, um dieselbe PRF-Ausgabe zu reproduzieren, und `decryptWithPasskeyPRFOutput` packt den Slot lokal aus. Der Server hält **kein** Passkey-Geheimnis, also kann kein Service-Role-Pfad ein passkey-geschütztes Backup wiederherstellen.

Das frühere Escrow-Design (eine Service-Role-Tabelle `backup_passkey_recovery`, die ein serverseitiges `recovery_secret` hielt, plus eine `backup_passkey_challenges`-Tabelle und `/v1/backup/passkeys/*`-Worker-Endpunkte) wurde **Verworfen**: Die Tabellen wurden in einer Backend-Migration entfernt, der Worker trägt keine Passkey-Routen, und `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` stellt ausdrücklich fest, dass `BackupPasskeyRecoveryService` und jeglicher Server-Escrow-Pfad fehlen. **(Umgesetzt)**

> **Produktionsreife-Einschränkung:** Gespeicherte Passkeys als voll produktionsreifen, wiederherstellbaren Faktor auf echten Geräten zu behandeln, hängt weiterhin von der webcredentials-Verknüpfung für `lavasecurity.app` ab. Die iOS-Hälfte ist deklariert — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` trägt `webcredentials:lavasecurity.app` — und die Server-Hälfte (die `apple-app-site-association`-Datei und die Header) wird jetzt auf der Marketing-Website gehostet. Bis diese Verknüpfung auf einem gegebenen Gerät auflöst, kann der webcredentials-Verknüpfungspfad fehlschlagen und meldet `BackupPasskeyError.webCredentialsAssociationUnavailable`. Der Passkey-Faktor selbst ist umgesetzt; seine End-to-End-Reife auf echter Hardware ist **Geplant**.

---

## 5. Datensparsamkeit & Datenschutzhaltung {#5-data-minimization--privacy-posture}

- **Optionales Konto.** Der Schutz funktioniert ohne Konto; die Anmeldung ermöglicht nur das Backup der Einstellungen.
- **Nur lokaler Klartext.** Das Telefon ist der einzige Ort, an dem Klartext-Einstellungen und entschlüsselnde Geheimnisse existieren; Supabase hält eine undurchsichtige Hülle pro Nutzer.
- **Minimierter Payload.** Nur die Einstellungen in §3.2 werden gesichert; `isPaid`, QA-Flags, Diagnosedaten, Snapshots und die vollständigen Blocklisten-Bytes sind ausgeschlossen. Blocklisten werden per Katalog-ID referenziert, nie eingebettet.
- **Keine Browser-/DNS-Telemetrie.** Es gibt keine serverseitige Tabelle für laufende DNS-Anfragen oder Telemetrie pro Domain; die Filterung bleibt auf dem Gerät.
- **Entsperrmaterial ist gerätelokal.** Das Backup-Entsperrmaterial wird mit `…ThisDeviceOnly`-Zugänglichkeit gespeichert und ist **nicht** über iCloud synchronisiert. Das **kehrte** das ursprüngliche, auf synchronisierbarer Keychain basierende Design des Plans um, sodass Lava Entsperrmaterial nicht stillschweigend über iCloud synchronisiert (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Umgesetzt; kehrt früheren Plan um.)**

### Kontolöschung {#account-deletion}

Die Löschung ist **Umgesetzt** und läuft über einen authentifizierten Worker-Endpunkt, nicht über direkte Client-Löschungen. `AccountAuthService.deleteAccount` sendet das Access-Token des Nutzers an `POST /v1/account/delete`; der `lavasec-api`-Worker (Service-Role) löscht die `bug_reports` des Nutzers (und ihre R2-Anhänge), `user_backups`, `entitlements`, `user_settings` und `profiles`-Zeilen und löscht dann den Supabase-Auth-Nutzer über die Admin-API, wobei nur ein Lösch-Status + verknüpfte Anbieter zurückgegeben werden. Die App meldet sich danach lokal ab und löscht das Backup-Entsperrmaterial (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Hinweis: Das YAML-Frontmatter des Löschplans liest bereits `status: Done` und der Plan liegt in `plans/implemented/`. Eine veraltete **Inline-Annotation** im Text liest `Status: Backlog.`, aber gemäß der Lane-Folder-Regel (der Ordner ist maßgeblich) und der Code-Präsenz (App + Worker existieren beide) ist das Feature **Umgesetzt**; die Inline-Zeile ist ein Doku-Fehler, nicht das Frontmatter.

---

## 6. Statusübersicht {#6-status-summary}

| Bereich | Detail | Status |
|---|---|---|
| Apple-/Google-`id_token`-Anmeldung über Supabase | Native Abläufe, gehashte Nonce, Roh-URLRequest-Tausch | Umgesetzt |
| E-Mail/Passwort-Anmeldung | Passwörter selbst zu verwalten abgelehnt | Verworfen |
| Session in der Keychain (gerätelokal, pro Anbieter) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Umgesetzt |
| AES-256-GCM-Hülle + PBKDF2-HMAC-SHA256 (210k) Schlüssel-Slots | Clientseitig; nur Chiffretext + geheimnisfreie Metadaten zu `user_backups` (RLS) | Umgesetzt |
| Passwortloses Setup (Gerät- + Assisted-Recovery- + optionaler Passkey-Slot) | `makePasswordless` | Umgesetzt |
| Passwort-Schlüssel-Slot im Live-Ablauf | Überlebt in `LavaSecCore` nur für Tests | Verworfen |
| Wiederherstellungscode (8-Wort-CVCV, ~105 Bit) | Geräteunabhängiger Faktor | Umgesetzt |
| Assisted Recovery (Server-Anteil + Code via SHA256, NUL-getrennt) | Zwei-Faktor; keine Hälfte allein | Umgesetzt |
| Passkey-Wiederherstellung (Zero-Knowledge, WebAuthn-PRF/`hmac-secret`, RP `lavasecurity.app`) | PRF-Ausgabe HKDF-abgeleiteter Slot, kein Server-Geheimnis | Umgesetzt |
| Passkey als produktionsreifer Faktor auf Hardware | Braucht webcredentials-Verknüpfung (AASA auf der Marketing-Website gehostet) | Geplant |
| Kontolöschung (authentifizierter Worker, Service-Role) | Entfernt Backups/Einstellungen/Berechtigungen/Profil/Anhänge + Auth-Nutzer | Umgesetzt |
| Biometrie-/Anwesenheits-Gate auf dem Entsperrmaterial | Prüfpunkt vor dem Release | Geplant |
| `EncryptedBackupCoordinator`-Auslagerung aus `AppViewModel` | Nur Modularisierung; keine Änderung am Sicherheitsmodell | In Arbeit |

---

## Verwandtes {#related}

- [System-Überblick](./system-overview.md) — das ganze System auf einem Bildschirm, inklusive Vertrauensgrenzen.
- [iOS-Client](./ios-client.md) — `AppViewModel` und die App-Targets, die das Backup antreiben.
- [Backend & Daten](./backend-and-data.md) — der `lavasec-api`-Worker, Supabase RLS und die `user_backups`-Speicherung.
- [DNS-Filterung & Blocklisten](./dns-filtering-and-blocklists.md) — die Resolver-Presets und Transporte, deren Einstellungen im Backup-Payload mitgetragen werden.
