---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Cuentas y copia de seguridad de conocimiento cero

> **Audiencia:** ingenieros.
> **Autoridad:** cuando este documento y un plan no coincidan, **gana el código** — las divergencias se señalan en línea. El estado refleja la realidad confirmada en el código, no la aspiración del plan. Leyenda de estado: **Implementado** (lanzado y confirmado en el código), **En curso** (parcialmente incorporado), **Planificado** (diseñado, no construido), **Descartado** (rechazado o revertido).

Las cuentas son **opcionales**. La protección básica es gratuita para siempre y no requiere cuenta; el inicio de sesión existe únicamente para respaldar tus *ajustes*, cifrados, de modo que puedas restaurarlos en un dispositivo nuevo. Este documento cubre el flujo de autenticación, dónde reside la sesión, el sobre de copia de seguridad de conocimiento cero, las rutas de recuperación y exactamente qué puede y qué no puede ver el servidor.

La promesa canónica de privacidad a la que sirve este documento:

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas — el backend solo conserva metadatos del catálogo, una copia de seguridad cifrada opaca por usuario y diagnósticos anonimizados que tú eliges enviar.

División de componentes: la criptografía pura + la construcción de solicitudes residen en `LavaSecCore`; la orquestación + la interfaz de usuario residen en `LavaSecApp`. Documentos relacionados: [System Overview](./system-overview.md), [iOS Client](./ios-client.md), [Backend & Data](./backend-and-data.md), [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md).

---

## 1. Flujo de autenticación

**Proveedores: solo Apple y Google.** **(Implementado)** `AccountAuthProvider` enumera exactamente `.apple` y `.google` (`AccountAuthService.swift`). Email/contraseña — y cualquier recuperación asistida por soporte que omita la autenticación — está explícitamente **Descartado**; poseer contraseñas añadiría obligaciones de restablecimiento/MFA/bloqueo/filtración mientras Apple/Google bastan, y la recuperación de omisión rompería la garantía de conocimiento cero.

Ambos proveedores usan la **concesión nativa de `id_token`**, no el SDK de Supabase para Swift ni OAuth web:

1. **Inicio de sesión nativo.** Apple mediante AuthenticationServices; Google mediante el SDK de GoogleSignIn. Cada uno produce un `id_token` del proveedor (Google también un token de acceso). La app genera un nonce sin procesar con CSPRNG, lo somete a hash con SHA256 y pasa el hash al proveedor para que el `id_token` emitido quede vinculado a él. **(Implementado)**
2. **Intercambio en Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) construye una `URLRequest` sin procesar hacia Supabase Auth `auth/v1/token?grant_type=id_token`, publicando `provider` + `id_token` + el `access_token` opcional + el nonce **sin procesar** (para que Supabase pueda verificar la vinculación y rechazar reproducciones), con la cabecera `apikey`. Sin SDK; `LavaSecCore` permanece libre de dependencias de red/autenticación. **(Implementado)**
3. **Recepción de una sesión.** Supabase verifica el token y devuelve una sesión: un token de acceso, un token de actualización, una caducidad y un registro de usuario (provider/providers). La actualización usa el mismo helper con `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orquesta todo esto — ejecuta los flujos nativos, realiza el intercambio, persiste y actualiza sesiones, expone `AccountAuthState` y dirige la eliminación de cuentas a través del Worker.

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

## 2. Almacenamiento de sesión y Keychain

Lo **único** que se persiste del inicio de sesión es la sesión de Supabase — los tokens de acceso y de actualización como JSON. **No** existe ningún espejo del lado del servidor de quién eres más allá del usuario de Supabase Auth y las filas que posees.

- **Dónde:** `AccountSessionKeychainStore` (`LavaSecApp`), servicio de Keychain `com.lavasec.account-session`, almacenado **por proveedor** (`supabase-session-apple` / `supabase-session-google`, más una migración de cuenta heredada). **(Implementado)**
- **Accesibilidad:** todos los almacenes comparten `GenericKeychainStore` (`LavaSecCore`), fijado a `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Esto significa **local del dispositivo, no sincronizado con iCloud y no incluido en las copias de seguridad del dispositivo**. **(Implementado)**

La misma mecánica de `GenericKeychainStore` respalda tres almacenes: la sesión de cuenta, el material de desbloqueo de la copia de seguridad (`BackupKeychainStore`, servicio `com.lavasec.zero-knowledge-backup`) y el código de acceso de la app. Ninguno de ellos se sincroniza a través de iCloud Keychain.

> **Punto de revisión abierto (no es un comportamiento garantizado):** la clase de accesibilidad actual no tiene una barrera biométrica/de presencia de usuario (sin `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Reforzar el material de desbloqueo a un control de acceso protegido por presencia se registra como un punto de revisión de cara al lanzamiento; el valor que se lanza hoy es after-first-unlock-this-device-only. **(Planificado)**

---

## 3. Copia de seguridad de conocimiento cero

### 3.1 Qué es, con precisión

Cuando activas la copia de seguridad cifrada, el **cliente iOS** cifra una copia minimizada de tus *ajustes* y sube solo el texto cifrado más metadatos no secretos a Supabase. El teléfono es el único lugar donde existen el texto plano y los secretos de descifrado.

> **Copia de seguridad de conocimiento cero:** sobre AES-256-GCM del lado del cliente; la clave aleatoria de carga útil se envuelve en ranuras de clave por ranura — PBKDF2-HMAC-SHA256 (210k iteraciones) para las ranuras de contraseña/frase/dispositivo/asistida, HKDF-SHA256 para la ranura de clave de acceso PRF. Solo el texto cifrado + los metadatos no secretos se suben a Supabase `user_backups` (RLS por usuario). El servidor no puede descifrar sin un secreto en poder del usuario. La ranura de clave de acceso es **también** de conocimiento cero: su clave de desenvoltura se deriva en el dispositivo a partir de la salida WebAuthn PRF (`hmac-secret`) del autenticador, y el servidor no conserva ningún secreto de clave de acceso (ver §4.3).

### 3.2 Qué se respalda (la carga útil minimizada)

`BackupConfigurationPayload` (`LavaSecCore`) es el texto plano que se sella. Es deliberadamente pequeño y hace round-trip a `AppConfiguration`. **(Implementado)**

**Incluido:** los **ID** de las listas de bloqueo habilitadas (referencias del catálogo, no los bytes de la lista), dominios permitidos/bloqueados, preajuste de resolutor / resolutor personalizado, preferencias de registro local, el ledger de LavaGuard, una pista de protección y los metadatos de fuentes de lista de bloqueo personalizadas.

**Excluido:** `isPaid` (la titularidad es local), banderas de QA, diagnósticos, instantáneas de Filtro y el contenido completo de las listas de bloqueo (referenciado solo por ID de catálogo). Tu historial de navegación y tus consultas DNS nunca forman parte de esta carga útil; el dispositivo nunca los registra como flujo de telemetría rutinario.

### 3.3 El sobre (criptografía del lado del cliente)

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa la criptografía. **(Implementado)**

1. **Cifrado de la carga útil.** La carga útil minimizada se sella una vez con **AES-256-GCM** bajo una **clave de carga útil aleatoria de 32 bytes** (generada con `SecRandomCopyBytes`).
2. **Envoltura de clave (ranuras de clave).** Esa única clave de carga útil se envuelve de forma independiente en una o más **ranuras de clave**, una por secreto, y luego se envuelve con AES-GCM una copia de la clave de carga útil. El secreto de cualquier ranura individual desbloquea toda la copia de seguridad. La derivación de la clave de envoltura es por tipo de ranura: las ranuras `password` / `recoveryPhrase` / `keychain` (dispositivo) / `assistedRecovery` usan **PBKDF2-HMAC-SHA256, 210.000 iteraciones** (producción; `defaultPasswordIterations = 210_000`) con una sal aleatoria fresca de 16 bytes por ranura; la ranura `passkey` usa **HKDF-SHA256** sobre la salida PRF del autenticador (info `"LavaSec passkey backup PRF v1"`), con la sal PRF no secreta persistida en la ranura para que la restauración pueda reproducir la salida.
3. **Tipos de ranura.** El sobre admite cinco tipos de ranura: `password`, `recoveryPhrase`, `keychain` (secreto del dispositivo), `assistedRecovery` y `passkey`.

La configuración que se lanza es **sin contraseña** (`makePasswordless`, dirigida por `AppViewModel.turnOnEncryptedBackup`). Crea una **ranura `keychain` (dispositivo) + una ranura `assistedRecovery` + una ranura `passkey` opcional**. Las fábricas `password` / `recoveryPhrase` y los métodos de descifrado todavía existen para sobres heredados/compatibles hacia atrás (ejercitados solo por pruebas), pero la interfaz activa nunca crea un sobre exclusivamente de contraseña — trata la copia de seguridad por contraseña como no lanzada. **(Implementado; ranura de contraseña Descartada del flujo en vivo.)**

**Integridad / anti-degradación:** `envelopeVersion` está fijado de forma rígida a `1`, y el KDF de cada ranura está fijado por tipo — `PBKDF2-HMAC-SHA256` para las ranuras de contraseña/frase/dispositivo/asistida, `HKDF-SHA256` para la ranura de clave de acceso PRF. Las versiones no admitidas o los KDF no coincidentes se rechazan, de modo que los metadatos falsificados o degradados no pueden debilitar la desenvoltura. **(Implementado)**

### 3.4 Subida y almacenamiento

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) sube el sobre **directamente** a la tabla PostgREST de Supabase `user_backups`, haciendo upsert sobre `user_id`, con el alcance del token de acceso del usuario. **No existe ninguna ruta del Worker para la subida del sobre** — el cliente habla directamente con Supabase bajo RLS; el Worker solo toca `user_backups` para eliminarlo durante la eliminación de la cuenta. **(Implementado)**

Lo que aterriza en `user_backups`:

- el **texto cifrado**, y
- **solo metadatos no secretos:** el nombre del cifrado, los registros de las ranuras de clave (sales, recuentos de iteraciones, claves envueltas, etiquetas de ranura), el `server_recovery_share`, `createdAt` y el tamaño en bytes.

La fila está protegida por **seguridad a nivel de fila**: cada fila solo es legible/escribible por su propietario (`auth.uid() = user_id`); el rol anónimo no tiene acceso. El tamaño está limitado a ~256 KiB de texto cifrado / 32 KiB de metadatos a nivel de la base de datos (`20260518000000_zero_knowledge_backups.sql`, reforzado en `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementado)**

### 3.5 La garantía — qué puede y qué no puede ver el servidor

**El servidor almacena:** texto cifrado, sales/iteraciones de KDF, ranuras de clave envueltas, el `server_recovery_share` y unos pocos campos no secretos (cifrado, tamaño, marca de tiempo).

**El servidor nunca recibe ni almacena:** los ajustes/dominios/preferencias de DNS en texto plano, la frase de recuperación, ninguna contraseña de copia de seguridad ni la clave de carga útil desenvuelta.

**Por lo tanto:** Supabase **no puede descifrar una copia de seguridad** sin un secreto en poder del usuario. Las tres rutas de restauración — la ranura de clave de dispositivo, la frase de recuperación (combinada con el server share, §4.2) y la ranura de clave de acceso (la salida PRF del autenticador, §4.3) — descifran **en el dispositivo**, y el servidor no conserva ningún secreto de descifrado para ninguna de ellas. Esto se afirma en los comentarios de la migración y en el plan de privacidad, y está probado (las pruebas del sobre confirman que no se filtran dominios/URL en texto plano en la forma subida).

**Salvedad precisa del modelo de amenazas — no exagerar.** Para la ranura de **recuperación asistida**, el servidor conserva *tanto* el `server_recovery_share` *como* la ranura `assistedRecovery` envuelta en `user_backups`. Lo único que le falta es la frase de recuperación del usuario, que Lava nunca recibe. Así que si el servidor estuviera totalmente comprometido, la entropía de la frase de recuperación (~105 bits, ver §4.1) más el costo de PBKDF2 de 210k iteraciones es la **única** barrera contra un ataque de fuerza bruta sin conexión de esa ranura. Esto es intencional (la recuperación asistida es de dos factores por diseño — ninguna mitad por sí sola descifra), pero significa que la entropía de la frase de recuperación es funcional, no decorativa. El secreto de la ranura `keychain` (dispositivo) nunca sale del dispositivo, por lo que no queda expuesto en absoluto a un compromiso del servidor.

---

## 4. Recuperación

`restoreEncryptedBackup` (en `AppViewModel`) descifra probando las ranuras disponibles: clave de dispositivo, frase de recuperación o clave de acceso. En todos los modos el sobre se carga localmente (o se obtiene de Supabase) y luego se **descifra en el dispositivo** — el servidor nunca descifra.

### 4.1 Frase de recuperación

`BackupRecoveryPhrase` (`LavaSecCore`) genera una **frase CVCV de 8 palabras** (consonante-vocal-consonante-vocal) a partir de `SecRandom` con muestreo por rechazo (~13,2 bits/token → **~105 bits en total**), normalizada en minúsculas. **(Implementado)** La restauración tolera el formato del usuario (espaciado/mayúsculas) mediante análisis/normalización antes de probar la ranura.

Este es el factor de recuperación **fuera del dispositivo** del usuario — guardado por el usuario, nunca subido. Según el endurecimiento de privacidad (§5), copiar la frase es **opcional** y, cuando se usa, pasa por un portapapeles local/caducable (10 minutos) en lugar de forzar la exposición al portapapeles global.

### 4.2 Recuperación asistida (la combinación de dos factores)

La frase de recuperación por sí sola **no** desbloquea la ranura `assistedRecovery`. El secreto de la ranura se deriva de **ambas** mitades:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

Los tres segmentos se unen mediante un separador de **byte NUL (`0x00`)** en la entrada UTF-8 real — es decir, la cadena sometida a hash es `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — de modo que el `‖` anterior denota concatenación delimitada por NUL, no concatenación simple. `serverRecoveryShare` es un valor aleatorio almacenado en los metadatos del sobre del lado del servidor; `normalizedPhrase` es la frase de recuperación del usuario. **Ninguna mitad por sí sola descifra** — la restauración requiere el server share (obtenido con la copia de seguridad) *y* la frase en poder del usuario. **(Implementado)**

### 4.3 Recuperación por clave de acceso — conocimiento cero, derivada por PRF

La ranura `passkey` opcional añade un factor respaldado por hardware, y es de **conocimiento cero**: su clave de desenvoltura se deriva **en el dispositivo** a partir de la salida WebAuthn PRF (`hmac-secret`) del autenticador. El servidor no registra ninguna clave de acceso, no emite ningún desafío WebAuthn y no almacena ningún secreto de recuperación — no hay ningún paso de liberación del lado del servidor.

- **Registro/aserción:** `BackupPasskeyCoordinator` (`LavaSecApp`) ejecuta WebAuthn mediante `ASAuthorizationPlatformPublicKeyCredentialProvider`, con la parte que confía **`lavasecurity.app`**, solicitando la extensión PRF sobre una sal por credencial y exigiendo verificación del usuario.
- **Derivación de clave (conocimiento cero):** el autenticador devuelve una salida PRF que **nunca sale del dispositivo**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva con HKDF-SHA256 la clave de envoltura de la ranura a partir de esa salida PRF (info `"LavaSec passkey backup PRF v1"`) y envuelve con AES-GCM la clave de carga útil; solo la sal PRF no secreta y el ID de credencial se persisten en la ranura. En la restauración, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` vuelve a afirmar la credencial para reproducir la misma salida PRF, y `decryptWithPasskeyPRFOutput` desenvuelve la ranura localmente. El servidor **no** conserva ningún secreto de clave de acceso, de modo que ninguna ruta con rol de servicio puede recuperar una copia de seguridad protegida por clave de acceso.

El diseño anterior de custodia (una tabla `backup_passkey_recovery` con rol de servicio que conservaba un `recovery_secret` del lado del servidor, más una tabla `backup_passkey_challenges` y los endpoints del Worker `/v1/backup/passkeys/*`) fue **Descartado**: las tablas se eliminaron en una migración del backend, el Worker no lleva ninguna ruta de clave de acceso, y `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` afirma de forma positiva que `BackupPasskeyRecoveryService` y cualquier ruta de custodia del servidor están ausentes. **(Implementado)**

> **Salvedad de preparación para producción:** tratar las claves de acceso guardadas como un factor recuperable totalmente listo para producción en dispositivos físicos todavía depende de la asociación de webcredentials para `lavasecurity.app`. La mitad de iOS está declarada — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` lleva `webcredentials:lavasecurity.app` — y la mitad del servidor (el archivo `apple-app-site-association` y las cabeceras) está ahora alojada en el sitio de marketing. Hasta que esa asociación se resuelva en un dispositivo dado, la ruta de asociación de webcredentials puede fallar y aflora `BackupPasskeyError.webCredentialsAssociationUnavailable`. El factor de clave de acceso en sí está implementado; su preparación de extremo a extremo en hardware real está **Planificada**.

---

## 5. Minimización de datos y postura de privacidad

- **Cuenta opcional.** La protección funciona sin cuenta; el inicio de sesión solo habilita la copia de seguridad de ajustes.
- **Solo texto plano local.** El teléfono es el único lugar donde existen los ajustes en texto plano y los secretos de descifrado; Supabase conserva un sobre opaco por usuario.
- **Carga útil minimizada.** Solo se respaldan los ajustes de §3.2; `isPaid`, banderas de QA, diagnósticos, instantáneas y los bytes completos de las listas de bloqueo quedan excluidos. Las listas de bloqueo se referencian por ID de catálogo, nunca se incrustan.
- **Sin telemetría de navegación/DNS.** No existe ninguna tabla del lado del servidor para las consultas DNS rutinarias ni la telemetría por dominio; el filtrado permanece en el dispositivo.
- **El material de desbloqueo es local del dispositivo.** El material de desbloqueo de la copia de seguridad se almacena con accesibilidad `…ThisDeviceOnly` y **no** se sincroniza con iCloud. Esto **revirtió** el diseño de Keychain sincronizable del plan original, de modo que Lava no sincroniza silenciosamente el material de desbloqueo a través de iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementado; revierte un plan anterior.)**

### Eliminación de cuenta

La eliminación está **Implementada** y se ejecuta a través de un endpoint del Worker autenticado, no mediante eliminaciones directas del cliente. `AccountAuthService.deleteAccount` envía el token de acceso del usuario a `POST /v1/account/delete`; el Worker `lavasec-api` (rol de servicio) elimina las filas `bug_reports` del usuario (y sus adjuntos en R2), `user_backups`, `entitlements`, `user_settings` y `profiles`, y luego elimina el usuario de Supabase Auth mediante la API de administrador, devolviendo únicamente un estado de eliminación + los proveedores vinculados. La app entonces cierra sesión localmente y borra el material de desbloqueo de la copia de seguridad (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Nota: el frontmatter YAML del plan de eliminación ya indica `status: Done` y reside en `plans/implemented/`. Una anotación obsoleta **en el cuerpo** indica `Status: Backlog.`, pero según la regla de la carpeta de lane (la carpeta es la autoridad) y la presencia en el código (app + Worker ambos existen), la función está **Implementada**; la línea en el cuerpo es un error de documentación, no del frontmatter.

---

## 6. Resumen de estado

| Área | Detalle | Estado |
|---|---|---|
| Inicio de sesión Apple / Google con `id_token` vía Supabase | Flujos nativos, nonce con hash, intercambio con URLRequest sin procesar | Implementado |
| Inicio de sesión con email/contraseña | Poseer contraseñas rechazado | Descartado |
| Sesión en Keychain (local del dispositivo, por proveedor) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementado |
| Sobre AES-256-GCM + ranuras de clave PBKDF2-HMAC-SHA256 (210k) | Del lado del cliente; solo texto cifrado + metadatos no secretos a `user_backups` (RLS) | Implementado |
| Configuración sin contraseña (ranuras de dispositivo + recuperación asistida + clave de acceso opcional) | `makePasswordless` | Implementado |
| Ranura de clave de contraseña en el flujo en vivo | Sobrevive en `LavaSecCore` solo para pruebas | Descartado |
| Frase de recuperación (CVCV de 8 palabras, ~105 bits) | Factor fuera del dispositivo | Implementado |
| Recuperación asistida (server share + frase vía SHA256, delimitada por NUL) | Dos factores; ninguna mitad por sí sola | Implementado |
| Recuperación por clave de acceso (conocimiento cero, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | Ranura derivada por HKDF de la salida PRF, sin secreto en el servidor | Implementado |
| Clave de acceso como factor listo para producción en hardware | Necesita la asociación de webcredentials (AASA alojada en el sitio de marketing) | Planificado |
| Eliminación de cuenta (Worker autenticado, rol de servicio) | Elimina copias de seguridad/ajustes/titularidades/perfil/adjuntos + usuario de Auth | Implementado |
| Barrera biométrica/de presencia de usuario en el material de desbloqueo | Punto de revisión de cara al lanzamiento | Planificado |
| Extracción de `EncryptedBackupCoordinator` desde `AppViewModel` | Solo modularización; sin cambio en el modelo de seguridad | En curso |

---

## Relacionado

- [System Overview](./system-overview.md) — todo el sistema en una sola pantalla, incluidos los límites de confianza.
- [iOS Client](./ios-client.md) — `AppViewModel` y los targets de la app que dirigen la copia de seguridad.
- [Backend & Data](./backend-and-data.md) — el Worker `lavasec-api`, la RLS de Supabase y el almacenamiento de `user_backups`.
- [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) — los preajustes de resolutor y los transportes cuyos ajustes se transportan en la carga útil de la copia de seguridad.
