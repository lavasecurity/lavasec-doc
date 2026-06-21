---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Cuentas y copia de seguridad de conocimiento cero

> **Público:** ingenieros.
> **Autoridad:** cuando este documento y un plan no coincidan, **gana el código** — las divergencias se señalan en línea. El estado refleja la realidad confirmada en el código, no la aspiración del plan. Leyenda de estados: **Implementado** (lanzado y confirmado en el código), **En curso** (parcialmente integrado), **Planeado** (diseñado, no construido), **Descartado** (rechazado o revertido).

Las cuentas son **opcionales**. La protección básica es gratuita para siempre y no requiere ninguna cuenta; el inicio de sesión existe únicamente para respaldar tus *ajustes*, cifrados, de modo que puedas restaurarlos en un dispositivo nuevo. Este documento cubre el flujo de autenticación, dónde reside la sesión, el sobre de copia de seguridad de conocimiento cero, las vías de recuperación y exactamente qué puede y qué no puede ver el servidor.

La promesa de privacidad canónica a la que sirve este documento:

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas — el backend solo conserva metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.

Separación de componentes: la criptografía pura y la construcción de solicitudes viven en `LavaSecCore`; la orquestación y la interfaz viven en `LavaSecApp`. Documentos hermanos: [Visión general del sistema](./system-overview.md), [Cliente iOS](./ios-client.md), [Backend y datos](./backend-and-data.md), [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md).

---

## 1. Flujo de autenticación

**Proveedores: únicamente Apple y Google.** **(Implementado)** `AccountAuthProvider` enumera exactamente `.apple` y `.google` (`AccountAuthService.swift`). El correo/contraseña — y cualquier recuperación asistida por soporte que eluda la autenticación — queda explícitamente **Descartado**; poseer contraseñas añadiría obligaciones de restablecimiento/MFA/bloqueo/filtración que no compensan la complejidad cuando Apple/Google bastan, y la recuperación que elude la autenticación rompería la garantía de conocimiento cero.

Ambos proveedores usan la **concesión nativa de `id_token`**, no el SDK de Supabase para Swift ni el OAuth web:

1. **Inicia sesión de forma nativa.** Apple mediante AuthenticationServices; Google mediante el SDK de GoogleSignIn. Cada uno produce un `id_token` del proveedor (Google también un token de acceso). La app genera un nonce sin procesar con CSPRNG, lo hashea con SHA256 y pasa el hash al proveedor para que el `id_token` emitido quede vinculado a él. **(Implementado)**
2. **Intercambia en Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) construye una `URLRequest` directa hacia Supabase Auth `auth/v1/token?grant_type=id_token`, enviando `provider` + `id_token` + el opcional `access_token` + el nonce **sin procesar** (para que Supabase pueda verificar la vinculación y rechazar reenvíos), con la cabecera `apikey`. Sin SDK; `LavaSecCore` se mantiene libre de dependencias de red/autenticación. **(Implementado)**
3. **Recibe una sesión.** Supabase verifica el token y devuelve una sesión: un token de acceso, un token de actualización, una expiración y un registro de usuario (proveedor/proveedores). La actualización usa el mismo ayudante con `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orquesta todo esto — ejecuta los flujos nativos, realiza el intercambio, persiste y actualiza las sesiones, expone `AccountAuthState` e impulsa el borrado de cuenta a través del Worker.

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

Lo **único** que se persiste del inicio de sesión es la sesión de Supabase — los tokens de acceso y de actualización como JSON. **No** hay ningún reflejo del lado del servidor de quién eres más allá del usuario de Supabase Auth y las filas que posees.

- **Dónde:** `AccountSessionKeychainStore` (`LavaSecApp`), servicio de Keychain `com.lavasec.account-session`, almacenado **por proveedor** (`supabase-session-apple` / `supabase-session-google`, más una migración de cuenta heredada). **(Implementado)**
- **Accesibilidad:** todos los almacenes comparten `GenericKeychainStore` (`LavaSecCore`), fijado a `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Eso significa **local al dispositivo, no sincronizado con iCloud y no incluido en las copias de seguridad del dispositivo**. **(Implementado)**

La misma mecánica de `GenericKeychainStore` respalda tres almacenes: la sesión de cuenta, el material de desbloqueo de la copia de seguridad (`BackupKeychainStore`, servicio `com.lavasec.zero-knowledge-backup`) y el código de acceso de la app. Ninguno de ellos se sincroniza a través de iCloud Keychain.

> **Punto de revisión abierto (no es un comportamiento afirmado):** la clase de accesibilidad actual no tiene una verificación biométrica/de presencia del usuario (sin `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Si conviene endurecer el material de desbloqueo a un control de acceso con verificación de presencia se rastrea como un punto de revisión de la puerta de lanzamiento; el valor que se entrega hoy es after-first-unlock-this-device-only. **(Planeado)**

---

## 3. Copia de seguridad de conocimiento cero

### 3.1 Qué es, con precisión

Cuando activas la copia de seguridad cifrada, el **cliente iOS** cifra una copia minimizada de tus *ajustes* y sube a Supabase únicamente el texto cifrado más metadatos no secretos. El teléfono es el único lugar donde existen el texto plano y los secretos de descifrado.

> **Copia de seguridad de conocimiento cero:** sobre AES-256-GCM del lado del cliente; la clave aleatoria de la carga útil se envuelve en ranuras de clave por ranura — PBKDF2-HMAC-SHA256 (210k iteraciones) para las ranuras de contraseña/frase/dispositivo/asistida, HKDF-SHA256 para la ranura de passkey con PRF. Solo el texto cifrado + metadatos no secretos suben a la tabla `user_backups` de Supabase (RLS por usuario). El servidor no puede descifrar sin un secreto en poder del usuario. La ranura de passkey es **también** de conocimiento cero: su clave de desenvolvimiento se deriva en el dispositivo a partir de la salida del PRF de WebAuthn (`hmac-secret`) del autenticador, y el servidor no conserva ningún secreto de passkey (ver §4.3).

### 3.2 Qué se respalda (la carga útil minimizada)

`BackupConfigurationPayload` (`LavaSecCore`) es el texto plano que se sella. Es deliberadamente pequeño y se convierte de ida y vuelta a `AppConfiguration`. **(Implementado)**

**Incluido:** los **ID** de las listas de bloqueo activadas (referencias del catálogo, no los bytes de la lista), los dominios permitidos/bloqueados, el preajuste de resolutor / resolutor personalizado, las preferencias de registro local, el libro mayor de LavaGuard, una pista de protección y los metadatos de origen de las listas de bloqueo personalizadas.

**Excluido:** `isPaid` (la habilitación es local), banderas de QA, diagnósticos, instantáneas de filtros y el contenido completo de las listas de bloqueo (referenciado solo por ID de catálogo). Tu historial de navegación y tus consultas DNS nunca forman parte de esta carga útil porque el dispositivo nunca los registra como un flujo de telemetría rutinario.

### 3.3 El sobre (criptografía del lado del cliente)

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa la criptografía. **(Implementado)**

1. **Cifrado de la carga útil.** La carga útil minimizada se sella una vez con **AES-256-GCM** bajo una **clave de carga útil de 32 bytes** aleatoria (generada con `SecRandomCopyBytes`).
2. **Envoltura de clave (ranuras de clave).** Esa única clave de carga útil se envuelve de forma independiente en una o más **ranuras de clave**, una por secreto, que luego envuelven con AES-GCM una copia de la clave de carga útil. El secreto de cualquier ranura individual desbloquea toda la copia de seguridad. La derivación de la clave de envoltura es específica por tipo de ranura: las ranuras `password` / `recoveryPhrase` / `keychain` (dispositivo) / `assistedRecovery` usan **PBKDF2-HMAC-SHA256, 210 000 iteraciones** (producción; `defaultPasswordIterations = 210_000`) con una sal aleatoria fresca de 16 bytes por ranura; la ranura `passkey` usa **HKDF-SHA256** sobre la salida del PRF del autenticador (info `"LavaSec passkey backup PRF v1"`), con la sal no secreta del PRF persistida en la ranura para que la restauración pueda reproducir la salida.
3. **Tipos de ranura.** El sobre admite cinco tipos de ranura: `password`, `recoveryPhrase`, `keychain` (secreto del dispositivo), `assistedRecovery` y `passkey`.

La configuración que se entrega es **sin contraseña** (`makePasswordless`, impulsada por `AppViewModel.turnOnEncryptedBackup`). Crea una **ranura `keychain` (dispositivo) + una ranura `assistedRecovery` + una ranura opcional `passkey`**. Las fábricas `password` / `recoveryPhrase` y los métodos de descifrado todavía existen para sobres heredados/retrocompatibles (ejercitados solo por las pruebas), pero la interfaz activa nunca crea un sobre solo de contraseña — trata la copia de seguridad con contraseña como no entregada. **(Implementado; ranura de contraseña Descartada del flujo en vivo.)**

**Integridad / antidegradación:** `envelopeVersion` está fijado rígidamente a `1`, y el KDF de cada ranura está fijado por tipo — `PBKDF2-HMAC-SHA256` para las ranuras de contraseña/frase/dispositivo/asistida, `HKDF-SHA256` para la ranura de passkey con PRF. Las versiones no admitidas o los KDF no coincidentes se rechazan, de modo que los metadatos falsificados o degradados no pueden debilitar el desenvolvimiento. **(Implementado)**

### 3.4 Subida y almacenamiento

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) sube el sobre **directamente** a la tabla PostgREST `user_backups` de Supabase, haciendo upsert sobre `user_id`, acotado por el token de acceso del usuario. **No hay ninguna ruta del Worker para subir el sobre** — el cliente habla directamente con Supabase bajo RLS; el Worker solo toca `user_backups` para borrarlo durante el borrado de cuenta. **(Implementado)**

Lo que llega a `user_backups`:

- el **texto cifrado**, y
- **únicamente metadatos no secretos:** el nombre del cifrado, los registros de ranuras de clave (sales, recuentos de iteraciones, claves envueltas, etiquetas de ranura), el `server_recovery_share`, `createdAt` y el tamaño en bytes.

La fila está protegida por **seguridad a nivel de fila**: cada fila solo es legible/escribible por su propietario (`auth.uid() = user_id`); el rol anónimo no tiene acceso. El tamaño está limitado a ~256 KiB de texto cifrado / 32 KiB de metadatos a nivel de la base de datos (`20260518000000_zero_knowledge_backups.sql`, endurecido en `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementado)**

### 3.5 La garantía — qué puede y qué no puede ver el servidor

**El servidor almacena:** el texto cifrado, las sales/iteraciones del KDF, las ranuras de clave envueltas, el `server_recovery_share` y unos pocos campos no secretos (cifrado, tamaño, marca de tiempo).

**El servidor nunca recibe ni almacena:** los ajustes/dominios/preferencias de DNS en texto plano, la frase de recuperación, ninguna contraseña de copia de seguridad ni la clave de carga útil desenvuelta.

**Por lo tanto:** Supabase **no puede descifrar una copia de seguridad** sin un secreto en poder del usuario. Las tres vías de restauración — la ranura de clave del dispositivo, la frase de recuperación (combinada con la parte del servidor, §4.2) y la ranura de passkey (la salida del PRF del autenticador, §4.3) — descifran **en el dispositivo**, y el servidor no conserva ningún secreto de descifrado para ninguna de ellas. Esto se afirma en los comentarios de la migración y en el plan de privacidad, y se prueba (las pruebas del sobre confirman que ningún dominio/URL en texto plano se filtra a la forma subida).

**Salvedad precisa del modelo de amenazas — no exageres.** Para la ranura de **recuperación asistida**, el servidor conserva *tanto* el `server_recovery_share` *como* la ranura `assistedRecovery` envuelta en `user_backups`. Lo único que le falta es la frase de recuperación del usuario, que Lava nunca recibe. Así que, si el servidor estuviera totalmente comprometido, la entropía de la frase de recuperación (~105 bits, ver §4.1) más el coste PBKDF2 de 210k iteraciones es la **única** barrera contra un ataque de fuerza bruta sin conexión de esa ranura. Esto es intencional (la recuperación asistida es de dos factores por diseño — ninguna mitad por sí sola descifra), pero significa que la entropía de la frase de recuperación es funcional, no decorativa. El secreto de la ranura `keychain` (dispositivo) nunca sale del dispositivo, así que no queda expuesto en absoluto a un compromiso del servidor.

---

## 4. Recuperación

Una copia de seguridad solo es útil si puedes restaurarla. `restoreEncryptedBackup` (en `AppViewModel`) descifra probando las ranuras disponibles: clave del dispositivo, frase de recuperación o passkey. En todos los modos el sobre se carga localmente (o se obtiene de Supabase) y luego se **descifra en el dispositivo** — el servidor nunca descifra.

### 4.1 Frase de recuperación

`BackupRecoveryPhrase` (`LavaSecCore`) genera una **frase CVCV de 8 palabras** (consonante-vocal-consonante-vocal) a partir de `SecRandom` con muestreo por rechazo (~13,2 bits/token → **~105 bits en total**), normalizada en minúsculas. **(Implementado)** La restauración tolera el formato del usuario (espacios/mayúsculas) mediante análisis/normalización antes de probar la ranura.

Este es el factor de recuperación **fuera del dispositivo** del usuario — el usuario lo guarda y nunca se sube. Según el endurecimiento de privacidad (§5), copiar la frase es **opcional** y, cuando se usa, pasa por un portapapeles local/expirante (10 minutos) en lugar de forzar la exposición en el portapapeles global.

### 4.2 Recuperación asistida (la combinación de dos factores)

La frase de recuperación por sí sola **no** desbloquea la ranura `assistedRecovery`. El secreto de la ranura se deriva de **ambas** mitades:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

Los tres segmentos se unen mediante un **separador de byte NUL (`0x00`)** en la entrada UTF-8 real — es decir, la cadena hasheada es `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — de modo que el `‖` anterior denota concatenación delimitada por NUL, no concatenación simple. `serverRecoveryShare` es un valor aleatorio almacenado en los metadatos del sobre del lado del servidor; `normalizedPhrase` es la frase de recuperación del usuario. **Ninguna mitad por sí sola descifra** — la restauración requiere la parte del servidor (obtenida junto con la copia de seguridad) *y* la frase en poder del usuario. **(Implementado)**

### 4.3 Recuperación con passkey — conocimiento cero, derivada del PRF

La ranura opcional `passkey` añade un factor respaldado por hardware, y es de **conocimiento cero**: su clave de desenvolvimiento se deriva **en el dispositivo** a partir de la salida del PRF de WebAuthn (`hmac-secret`) del autenticador. El servidor no registra ningún passkey, no emite desafíos de WebAuthn y no almacena ningún secreto de recuperación — no hay paso de liberación del servidor.

- **Registro/aserción:** `BackupPasskeyCoordinator` (`LavaSecApp`) ejecuta WebAuthn mediante `ASAuthorizationPlatformPublicKeyCredentialProvider`, parte confiable **`lavasecurity.app`**, solicitando la extensión PRF sobre una sal por credencial y exigiendo verificación del usuario.
- **Derivación de clave (conocimiento cero):** el autenticador devuelve una salida del PRF que **nunca sale del dispositivo**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva con HKDF-SHA256 la clave de envoltura de la ranura a partir de esa salida del PRF (info `"LavaSec passkey backup PRF v1"`) y envuelve con AES-GCM la clave de carga útil; solo la sal no secreta del PRF y el ID de la credencial se persisten en la ranura. En la restauración, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` vuelve a aseverar la credencial para reproducir la misma salida del PRF, y `decryptWithPasskeyPRFOutput` desenvuelve la ranura localmente. El servidor **no** conserva ningún secreto de passkey, así que ninguna vía con rol de servicio puede recuperar una copia de seguridad protegida con passkey.

El diseño anterior de custodia (una tabla `backup_passkey_recovery` con rol de servicio que contenía un `recovery_secret` del lado del servidor, más una tabla `backup_passkey_challenges` y endpoints `/v1/backup/passkeys/*` del Worker) fue **Descartado**: las tablas se eliminaron en una migración del backend, el Worker no lleva rutas de passkey, y `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` afirma de forma positiva que `BackupPasskeyRecoveryService` y cualquier vía de custodia en el servidor están ausentes. **(Implementado)**

> **Salvedad de preparación para producción:** tratar los passkeys guardados como un factor recuperable totalmente listo para producción en dispositivos físicos todavía depende de la asociación de webcredentials para `lavasecurity.app`. La mitad de iOS está declarada — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` lleva `webcredentials:lavasecurity.app` — y la mitad del servidor (el archivo `apple-app-site-association` y las cabeceras) ahora se aloja en el sitio de marketing. Hasta que esa asociación se resuelva en un dispositivo dado, la vía de asociación de webcredentials puede fallar y surge `BackupPasskeyError.webCredentialsAssociationUnavailable`. El factor de passkey en sí está implementado; su preparación de extremo a extremo en hardware real está **Planeada**.

---

## 5. Minimización de datos y postura de privacidad

- **Cuenta opcional.** La protección funciona sin ninguna cuenta; el inicio de sesión solo habilita la copia de seguridad de los ajustes.
- **Solo texto plano local.** El teléfono es el único lugar donde existen los ajustes en texto plano y los secretos de descifrado; Supabase conserva un sobre opaco por usuario.
- **Carga útil minimizada.** Solo se respaldan los ajustes de §3.2; `isPaid`, las banderas de QA, los diagnósticos, las instantáneas y los bytes completos de las listas de bloqueo quedan excluidos. Las listas de bloqueo se referencian por ID de catálogo, nunca se incrustan.
- **Sin telemetría de navegación/DNS.** No hay ninguna tabla del lado del servidor para las consultas DNS rutinarias ni la telemetría por dominio; el filtrado permanece en el dispositivo.
- **El material de desbloqueo es local al dispositivo.** El material de desbloqueo de la copia de seguridad se almacena con accesibilidad `…ThisDeviceOnly` y **no** se sincroniza con iCloud. Esto **revirtió** el diseño original del plan basado en Keychain sincronizable, de modo que Lava no sincroniza silenciosamente el material de desbloqueo a través de iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementado; revierte un plan anterior.)**

### Borrado de cuenta

El borrado está **Implementado** y se ejecuta a través de un endpoint autenticado del Worker, no mediante borrados directos del cliente. `AccountAuthService.deleteAccount` envía el token de acceso del usuario a `POST /v1/account/delete`; el Worker `lavasec-api` (rol de servicio) borra las filas de `bug_reports` del usuario (y sus adjuntos en R2), `user_backups`, `entitlements`, `user_settings` y `profiles`, luego borra el usuario de Supabase Auth mediante la API de administración, devolviendo solo un estado de borrado + los proveedores vinculados. Después la app cierra la sesión localmente y limpia el material de desbloqueo de la copia de seguridad (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Nota: el frontmatter YAML del plan de borrado ya dice `status: Done` y vive en `plans/implemented/`. Una anotación obsoleta **dentro del cuerpo** dice `Status: Backlog.`, pero según la regla de carpeta de carril (la carpeta es autoritativa) y la presencia de código (existen tanto la app como el Worker), la función está **Implementada**; la línea dentro del cuerpo es un error del documento, no del frontmatter.

---

## 6. Resumen de estado

| Área | Detalle | Estado |
|---|---|---|
| Inicio de sesión con `id_token` de Apple / Google vía Supabase | Flujos nativos, nonce hasheado, intercambio con URLRequest directa | Implementado |
| Inicio de sesión con correo/contraseña | Poseer contraseñas rechazado | Descartado |
| Sesión en Keychain (local al dispositivo, por proveedor) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementado |
| Sobre AES-256-GCM + ranuras de clave PBKDF2-HMAC-SHA256 (210k) | Del lado del cliente; solo texto cifrado + metadatos no secretos a `user_backups` (RLS) | Implementado |
| Configuración sin contraseña (ranuras de dispositivo + recuperación asistida + passkey opcional) | `makePasswordless` | Implementado |
| Ranura de clave de contraseña en el flujo en vivo | Sobrevive en `LavaSecCore` solo para las pruebas | Descartado |
| Frase de recuperación (CVCV de 8 palabras, ~105 bits) | Factor fuera del dispositivo | Implementado |
| Recuperación asistida (parte del servidor + frase vía SHA256, delimitada por NUL) | Dos factores; ninguna mitad por sí sola | Implementado |
| Recuperación con passkey (conocimiento cero, PRF/`hmac-secret` de WebAuthn, RP `lavasecurity.app`) | Ranura derivada con HKDF de la salida del PRF, sin secreto del servidor | Implementado |
| Passkey como factor listo para producción en hardware | Necesita la asociación de webcredentials (AASA alojado en el sitio de marketing) | Planeado |
| Borrado de cuenta (Worker autenticado, rol de servicio) | Elimina copias de seguridad/ajustes/habilitaciones/perfil/adjuntos + usuario de Auth | Implementado |
| Verificación biométrica/de presencia del usuario en el material de desbloqueo | Punto de revisión de la puerta de lanzamiento | Planeado |
| Extracción de `EncryptedBackupCoordinator` de `AppViewModel` | Solo modularización; sin cambio en el modelo de seguridad | En curso |

---

## Relacionado

- [Visión general del sistema](./system-overview.md) — todo el sistema en una sola pantalla, incluidas las fronteras de confianza.
- [Cliente iOS](./ios-client.md) — `AppViewModel` y los destinos de la app que impulsan la copia de seguridad.
- [Backend y datos](./backend-and-data.md) — el Worker `lavasec-api`, el RLS de Supabase y el almacenamiento de `user_backups`.
- [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) — los preajustes de resolutor y los transportes cuyos ajustes se llevan en la carga útil de la copia de seguridad.
