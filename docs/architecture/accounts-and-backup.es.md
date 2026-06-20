---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Cuentas y copia de seguridad de conocimiento cero

> **Público:** ingenieros.
> **Autoridad:** cuando este documento y un plan no coincidan, **manda el código**: las divergencias se señalan en línea. El estado refleja la realidad confirmada en el código, no las aspiraciones de un plan. Leyenda de estados: **Implementado** (lanzado y confirmado en el código), **En curso** (parcialmente integrado), **Planeado** (diseñado, no construido), **Descartado** (rechazado o revertido).

Las cuentas son **opcionales**. La protección básica es gratuita para siempre y no requiere ninguna cuenta; el inicio de sesión solo existe para hacer una copia de seguridad de tus *ajustes*, cifrada, de modo que puedas restaurarlos en un dispositivo nuevo. Este documento cubre el flujo de autenticación, dónde reside la sesión, el sobre de copia de seguridad de conocimiento cero, las rutas de recuperación y exactamente qué puede y qué no puede ver el servidor.

La promesa de privacidad canónica a la que sirve este documento:

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas: el backend solo conserva metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que decidas enviar.

División de componentes: la criptografía pura y la construcción de peticiones residen en `LavaSecCore`; la orquestación y la interfaz residen en `LavaSecApp`. Documentos relacionados: [Visión general del sistema](./system-overview.md), [Cliente iOS](./ios-client.md), [Backend y datos](./backend-and-data.md), [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md).

---

## 1. Flujo de autenticación

**Proveedores: solo Apple y Google.** **(Implementado)** `AccountAuthProvider` enumera exactamente `.apple` y `.google` (`AccountAuthService.swift`). El correo y contraseña —y cualquier recuperación asistida por soporte que se salte la autenticación— está explícitamente **Descartado**; poseer contraseñas añadiría obligaciones de restablecimiento, MFA, bloqueo de cuenta y filtraciones que no compensan la complejidad mientras Apple/Google basten, y la recuperación con bypass rompería la garantía de conocimiento cero.

Ambos proveedores usan la **concesión nativa de `id_token`**, no el SDK de Supabase para Swift ni OAuth web:

1. **Inicia sesión de forma nativa.** Apple mediante AuthenticationServices; Google mediante el SDK de GoogleSignIn. Cada uno produce un `id_token` del proveedor (Google también un token de acceso). La app genera un nonce sin procesar con CSPRNG, lo hashea con SHA256 y pasa el hash al proveedor para que el `id_token` emitido quede vinculado a él. **(Implementado)**
2. **Intercambio en Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) construye una `URLRequest` directa hacia Supabase Auth `auth/v1/token?grant_type=id_token`, enviando `provider` + `id_token` + un `access_token` opcional + el nonce **sin procesar** (para que Supabase pueda verificar el vínculo y rechazar reenvíos), con la cabecera `apikey`. Sin SDK; `LavaSecCore` se mantiene libre de dependencias de red o autenticación. **(Implementado)**
3. **Recibe una sesión.** Supabase verifica el token y devuelve una sesión: un token de acceso, un token de refresco, una caducidad y un registro de usuario (proveedor/proveedores). El refresco usa el mismo helper con `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orquesta todo esto: ejecuta los flujos nativos, realiza el intercambio, persiste y refresca sesiones, expone `AccountAuthState` y gestiona la eliminación de cuenta a través del Worker.

```
Apple / Google (id_token nativo + nonce sin procesar)
        │
        ▼
SupabaseIDTokenAuth  ──POST──▶  Supabase Auth  auth/v1/token?grant_type=id_token
        │                              │
        ▼                              ▼
AccountAuthService  ◀────── sesión (tokens de acceso + refresco, caducidad, usuario)
        │
        ▼
AccountSessionKeychainStore  (Keychain, local del dispositivo)
```

---

## 2. Almacenamiento de sesión y Keychain

Lo **único** que se persiste al iniciar sesión es la sesión de Supabase: los tokens de acceso y refresco como JSON. **No** hay ningún espejo en el servidor de quién eres más allá del usuario de Supabase Auth y las filas que te pertenecen.

- **Dónde:** `AccountSessionKeychainStore` (`LavaSecApp`), servicio de Keychain `com.lavasec.account-session`, almacenado **por proveedor** (`supabase-session-apple` / `supabase-session-google`, más una migración de cuentas heredadas). **(Implementado)**
- **Accesibilidad:** todos los almacenes comparten `GenericKeychainStore` (`LavaSecCore`), fijado a `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Eso significa **local del dispositivo, no sincronizado con iCloud y no incluido en las copias de seguridad del dispositivo**. **(Implementado)**

El mismo mecanismo de `GenericKeychainStore` respalda tres almacenes: la sesión de cuenta, el material de desbloqueo de la copia de seguridad (`BackupKeychainStore`, servicio `com.lavasec.zero-knowledge-backup`) y el código de acceso de la app. Ninguno de ellos se sincroniza a través de iCloud Keychain.

> **Punto abierto de revisión (no es un comportamiento garantizado):** la clase de accesibilidad actual no tiene una verificación biométrica ni de presencia de usuario (sin `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Si conviene endurecer el material de desbloqueo con un control de acceso condicionado a la presencia es un punto de revisión previo al lanzamiento; el valor que se envía hoy es after-first-unlock-this-device-only. **(Planeado)**

---

## 3. Copia de seguridad de conocimiento cero

### 3.1 Qué es, con precisión

Cuando activas la copia de seguridad cifrada, el **cliente de iOS** cifra una copia reducida de tus *ajustes* y sube solo el texto cifrado más metadatos no secretos a Supabase. El teléfono es el único lugar donde existen el texto en claro y los secretos de descifrado.

> **Copia de seguridad de conocimiento cero:** sobre AES-256-GCM del lado del cliente; la clave aleatoria del contenido se envuelve en ranuras de clave por ranura: PBKDF2-HMAC-SHA256 (210k iteraciones) para las ranuras de contraseña/frase/dispositivo/asistida, HKDF-SHA256 para la ranura de passkey con PRF. Solo el texto cifrado + los metadatos no secretos suben a la tabla `user_backups` de Supabase (RLS por usuario). El servidor no puede descifrar sin un secreto en poder del usuario. La ranura de passkey **también** es de conocimiento cero: su clave de desenvolvido se deriva en el dispositivo a partir de la salida PRF de WebAuthn (`hmac-secret`) del autenticador, y el servidor no guarda ningún secreto de passkey (ver §4.3).

### 3.2 Qué se respalda (el contenido reducido)

`BackupConfigurationPayload` (`LavaSecCore`) es el texto en claro que se sella. Es deliberadamente pequeño y se convierte de ida y vuelta a `AppConfiguration`. **(Implementado)**

**Incluido:** los **ID** de las listas de bloqueo activadas (referencias al catálogo, no los bytes de la lista), los dominios permitidos/bloqueados, el preajuste de resolutor / resolutor personalizado, las preferencias de registro local, el ledger de LavaGuard, una pista de protección y los metadatos de origen de las listas de bloqueo personalizadas.

**Excluido:** `isPaid` (la suscripción es local), las flags de QA, los diagnósticos, las instantáneas de filtros y el contenido completo de las listas de bloqueo (solo referenciado por ID de catálogo). Tu historial de navegación y tus consultas DNS nunca forman parte de este contenido porque el dispositivo nunca los registra como un flujo rutinario de telemetría.

### 3.3 El sobre (criptografía del lado del cliente)

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa la criptografía. **(Implementado)**

1. **Cifrado del contenido.** El contenido reducido se sella una vez con **AES-256-GCM** bajo una **clave de contenido aleatoria de 32 bytes** (generada con `SecRandomCopyBytes`).
2. **Envoltura de clave (ranuras de clave).** Esa única clave de contenido se envuelve de forma independiente en una o varias **ranuras de clave**, una por secreto, y luego AES-GCM envuelve una copia de la clave de contenido. El secreto de cualquier ranura por sí solo desbloquea toda la copia de seguridad. La derivación de la clave de envoltura depende del tipo de ranura: las ranuras `password` / `recoveryPhrase` / `keychain` (dispositivo) / `assistedRecovery` usan **PBKDF2-HMAC-SHA256, 210 000 iteraciones** (producción; `defaultPasswordIterations = 210_000`) con una sal aleatoria fresca de 16 bytes por ranura; la ranura `passkey` usa **HKDF-SHA256** sobre la salida PRF del autenticador (info `"LavaSec passkey backup PRF v1"`), con la sal PRF no secreta persistida en la ranura para que la restauración pueda reproducir la salida.
3. **Tipos de ranura.** El sobre admite cinco tipos de ranura: `password`, `recoveryPhrase`, `keychain` (secreto del dispositivo), `assistedRecovery` y `passkey`.

La configuración que se envía es **sin contraseña** (`makePasswordless`, gestionada por `AppViewModel.turnOnEncryptedBackup`). Crea una **ranura `keychain` (dispositivo) + una ranura `assistedRecovery` + una ranura `passkey` opcional**. Las fábricas y los métodos de descifrado `password` / `recoveryPhrase` siguen existiendo para sobres heredados o de compatibilidad (solo se ejercitan en pruebas), pero la interfaz activa nunca crea un sobre solo con contraseña: trata la copia de seguridad con contraseña como no lanzada. **(Implementado; la ranura de contraseña está Descartada del flujo activo.)**

**Integridad / anti-degradación:** `envelopeVersion` está fijado de forma estricta a `1`, y la KDF de cada ranura está fijada por tipo: `PBKDF2-HMAC-SHA256` para las ranuras de contraseña/frase/dispositivo/asistida, `HKDF-SHA256` para la ranura de passkey con PRF. Las versiones no admitidas o las KDF que no coincidan se rechazan, de modo que unos metadatos falsificados o degradados no puedan debilitar el desenvolvido. **(Implementado)**

### 3.4 Subida y almacenamiento

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) sube el sobre **directamente** a la tabla de PostgREST `user_backups` de Supabase, haciendo upsert por `user_id`, con el ámbito del token de acceso del usuario. **No hay ninguna ruta del Worker para subir el sobre**: el cliente habla directamente con Supabase bajo RLS; el Worker solo toca `user_backups` para eliminarlo durante la eliminación de la cuenta. **(Implementado)**

Lo que llega a `user_backups`:

- el **texto cifrado**, y
- **solo metadatos no secretos:** el nombre del cifrado, los registros de las ranuras de clave (sales, contadores de iteraciones, claves envueltas, etiquetas de ranura), el `server_recovery_share`, `createdAt` y el tamaño en bytes.

La fila está protegida por **seguridad a nivel de fila**: cada fila solo puede ser leída o escrita por su propietario (`auth.uid() = user_id`); el rol anónimo no tiene acceso. El tamaño está limitado a ~256 KiB de texto cifrado / 32 KiB de metadatos a nivel de base de datos (`20260518000000_zero_knowledge_backups.sql`, endurecido en `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementado)**

### 3.5 La garantía: qué puede y qué no puede ver el servidor

**El servidor almacena:** el texto cifrado, las sales/iteraciones de la KDF, las ranuras de clave envueltas, el `server_recovery_share` y algunos campos no secretos (cifrado, tamaño, marca de tiempo).

**El servidor nunca recibe ni almacena:** los ajustes/dominios/preferencias de DNS en claro, la frase de recuperación, ninguna contraseña de copia de seguridad ni la clave de contenido desenvuelta.

**Por tanto:** Supabase **no puede descifrar una copia de seguridad** sin un secreto en poder del usuario. Las tres rutas de restauración —la ranura de clave del dispositivo, la frase de recuperación (combinada con la parte del servidor, §4.2) y la ranura de passkey (la salida PRF del autenticador, §4.3)— descifran **en el dispositivo**, y el servidor no guarda ningún secreto de descifrado para ninguna de ellas. Esto se afirma en los comentarios de la migración y en el plan de privacidad, y está probado (las pruebas del sobre confirman que ningún dominio/URL en claro se filtra a la forma subida).

**Matiz preciso del modelo de amenazas: no exageres la garantía.** Para la ranura de **recuperación asistida**, el servidor guarda *tanto* el `server_recovery_share` *como* la ranura `assistedRecovery` envuelta en `user_backups`. Lo único que le falta es la frase de recuperación del usuario, que Lava nunca recibe. Así que, si el servidor estuviera totalmente comprometido, la entropía de la frase de recuperación (~105 bits, ver §4.1) más el coste de PBKDF2 con 210k iteraciones es la **única** barrera frente a un ataque de fuerza bruta offline de esa ranura. Esto es intencionado (la recuperación asistida es de dos factores por diseño: ninguna mitad descifra por sí sola), pero implica que la entropía de la frase de recuperación es funcional, no decorativa. El secreto de la ranura `keychain` (dispositivo) nunca sale del dispositivo, así que no queda expuesto en absoluto ante un compromiso del servidor.

---

## 4. Recuperación

Una copia de seguridad solo es útil si puedes restaurarla. `restoreEncryptedBackup` (en `AppViewModel`) descifra probando las ranuras disponibles: la clave del dispositivo, la frase de recuperación o la passkey. En todos los modos el sobre se carga localmente (o se obtiene de Supabase) y luego se **descifra en el dispositivo**: el servidor nunca descifra.

### 4.1 Frase de recuperación

`BackupRecoveryPhrase` (`LavaSecCore`) genera una **frase CVCV de 8 palabras** (consonante-vocal-consonante-vocal) a partir de `SecRandom` con muestreo por rechazo (~13,2 bits/token → **~105 bits en total**), normalizada en minúsculas. **(Implementado)** La restauración tolera el formato del usuario (espacios/mayúsculas) mediante análisis y normalización antes de probar la ranura.

Este es el factor de recuperación **fuera del dispositivo** del usuario: lo guarda el propio usuario y nunca se sube. Según el endurecimiento de privacidad (§5), copiar la frase es **opcional** y, cuando se usa, pasa por un portapapeles local y efímero (de 10 minutos) en lugar de forzar la exposición en el portapapeles global.

### 4.2 Recuperación asistida (la combinación de dos factores)

La frase de recuperación por sí sola **no** desbloquea la ranura `assistedRecovery`. El secreto de la ranura se deriva de **ambas** mitades:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

Los tres segmentos se unen con un **separador de byte NUL (`0x00`)** en la entrada UTF-8 real; es decir, la cadena hasheada es `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase`, de modo que el `‖` de arriba denota una concatenación delimitada por NUL, no una concatenación sin más. `serverRecoveryShare` es un valor aleatorio almacenado en los metadatos del sobre del lado del servidor; `normalizedPhrase` es la frase de recuperación del usuario. **Ninguna mitad descifra por sí sola**: la restauración requiere la parte del servidor (obtenida con la copia de seguridad) *y* la frase en poder del usuario. **(Implementado)**

### 4.3 Recuperación con passkey: conocimiento cero, derivada de PRF

La ranura `passkey` opcional añade un factor respaldado por hardware, y es de **conocimiento cero**: su clave de desenvolvido se deriva **en el dispositivo** a partir de la salida PRF de WebAuthn (`hmac-secret`) del autenticador. El servidor no registra ninguna passkey, no emite desafíos de WebAuthn y no almacena ningún secreto de recuperación: no hay paso de liberación en el servidor.

- **Registro/aserción:** `BackupPasskeyCoordinator` (`LavaSecApp`) ejecuta WebAuthn mediante `ASAuthorizationPlatformPublicKeyCredentialProvider`, con la parte de confianza **`lavasecurity.app`**, solicitando la extensión PRF sobre una sal por credencial y exigiendo verificación de usuario.
- **Derivación de clave (conocimiento cero):** el autenticador devuelve una salida PRF que **nunca sale del dispositivo**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva con HKDF-SHA256 la clave de envoltura de la ranura a partir de esa salida PRF (info `"LavaSec passkey backup PRF v1"`) y envuelve con AES-GCM la clave de contenido; solo se persisten en la ranura la sal PRF no secreta y el ID de la credencial. En la restauración, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` vuelve a aseverar la credencial para reproducir la misma salida PRF, y `decryptWithPasskeyPRFOutput` desenvuelve la ranura localmente. El servidor **no** guarda ningún secreto de passkey, así que ninguna ruta con rol de servicio puede recuperar una copia de seguridad protegida con passkey.

El diseño anterior de custodia (una tabla `backup_passkey_recovery` con rol de servicio que guardaba un `recovery_secret` del lado del servidor, más una tabla `backup_passkey_challenges` y los endpoints del Worker `/v1/backup/passkeys/*`) fue **Descartado**: las tablas se eliminaron en una migración del backend, el Worker no lleva ninguna ruta de passkey y `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` afirma de forma explícita que `BackupPasskeyRecoveryService` y cualquier ruta de custodia en el servidor están ausentes. **(Implementado)**

> **Matiz sobre la preparación para producción:** tratar las passkeys guardadas como un factor recuperable plenamente listo para producción en dispositivos físicos todavía depende de la asociación webcredentials para `lavasecurity.app`. La mitad de iOS está declarada —`lavasec-ios: LavaSecApp/LavaSecApp.entitlements` lleva `webcredentials:lavasecurity.app`— y la mitad del servidor (el fichero `apple-app-site-association` y sus cabeceras) ya se aloja en el sitio de marketing. Hasta que esa asociación se resuelva en un dispositivo dado, la ruta de asociación webcredentials puede fallar y devuelve `BackupPasskeyError.webCredentialsAssociationUnavailable`. El factor de passkey en sí está implementado; su preparación de extremo a extremo en hardware real está **Planeada**.

---

## 5. Minimización de datos y postura de privacidad

- **Cuenta opcional.** La protección funciona sin ninguna cuenta; el inicio de sesión solo habilita la copia de seguridad de los ajustes.
- **Texto en claro solo en local.** El teléfono es el único lugar donde existen los ajustes en claro y los secretos de descifrado; Supabase guarda un sobre opaco por usuario.
- **Contenido reducido.** Solo se respaldan los ajustes de la §3.2; `isPaid`, las flags de QA, los diagnósticos, las instantáneas y los bytes completos de las listas de bloqueo quedan excluidos. Las listas de bloqueo se referencian por ID de catálogo, nunca se incrustan.
- **Sin telemetría de navegación/DNS.** No hay ninguna tabla en el servidor para las consultas DNS rutinarias ni para la telemetría por dominio; el filtrado se queda en el dispositivo.
- **El material de desbloqueo es local del dispositivo.** El material de desbloqueo de la copia de seguridad se almacena con la accesibilidad `…ThisDeviceOnly` y **no** se sincroniza con iCloud. Esto **revirtió** el diseño de Keychain sincronizable del plan original, de modo que Lava no sincroniza en silencio el material de desbloqueo a través de iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementado; revierte un plan anterior.)**

### Eliminación de cuenta

La eliminación está **Implementada** y se ejecuta a través de un endpoint autenticado del Worker, no mediante eliminaciones directas desde el cliente. `AccountAuthService.deleteAccount` envía el token de acceso del usuario a `POST /v1/account/delete`; el Worker `lavasec-api` (rol de servicio) elimina las filas de `bug_reports` del usuario (y sus adjuntos en R2), `user_backups`, `entitlements`, `user_settings` y `profiles`, y luego elimina el usuario de Supabase Auth mediante la API de administración, devolviendo solo un estado de eliminación + los proveedores vinculados. A continuación, la app cierra la sesión localmente y borra el material de desbloqueo de la copia de seguridad (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Nota: el frontmatter YAML del plan de eliminación ya indica `status: Done` y reside en `plans/implemented/`. Una anotación **en el cuerpo** desactualizada indica `Status: Backlog.`, pero según la regla de la carpeta de carril (la carpeta es la autoridad) y la presencia en el código (existen tanto la app como el Worker), la función está **Implementada**; la línea en el cuerpo es un error de documentación, no del frontmatter.

---

## 6. Resumen de estado

| Área | Detalle | Estado |
|---|---|---|
| Inicio de sesión con `id_token` de Apple / Google vía Supabase | Flujos nativos, nonce hasheado, intercambio con URLRequest directa | Implementado |
| Inicio de sesión con correo/contraseña | Poseer contraseñas rechazado | Descartado |
| Sesión en Keychain (local del dispositivo, por proveedor) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementado |
| Sobre AES-256-GCM + ranuras de clave PBKDF2-HMAC-SHA256 (210k) | Del lado del cliente; solo texto cifrado + metadatos no secretos a `user_backups` (RLS) | Implementado |
| Configuración sin contraseña (ranuras de dispositivo + recuperación asistida + passkey opcional) | `makePasswordless` | Implementado |
| Ranura de clave de contraseña en el flujo activo | Sobrevive en `LavaSecCore` solo para pruebas | Descartado |
| Frase de recuperación (CVCV de 8 palabras, ~105 bits) | Factor fuera del dispositivo | Implementado |
| Recuperación asistida (parte del servidor + frase vía SHA256, delimitada por NUL) | Dos factores; ninguna mitad por sí sola | Implementado |
| Recuperación con passkey (conocimiento cero, PRF de WebAuthn/`hmac-secret`, RP `lavasecurity.app`) | Ranura derivada con HKDF de la salida PRF, sin secreto en el servidor | Implementado |
| Passkey como factor listo para producción en hardware | Necesita la asociación webcredentials (AASA alojado en el sitio de marketing) | Planeado |
| Eliminación de cuenta (Worker autenticado, rol de servicio) | Elimina copias de seguridad/ajustes/suscripciones/perfil/adjuntos + usuario de Auth | Implementado |
| Verificación biométrica/de presencia de usuario en el material de desbloqueo | Punto de revisión previo al lanzamiento | Planeado |
| Extracción de `EncryptedBackupCoordinator` de `AppViewModel` | Solo modularización; sin cambios en el modelo de seguridad | En curso |

---

## Relacionado

- [Visión general del sistema](./system-overview.md) — todo el sistema en una sola pantalla, incluidos los límites de confianza.
- [Cliente iOS](./ios-client.md) — `AppViewModel` y los targets de la app que gestionan la copia de seguridad.
- [Backend y datos](./backend-and-data.md) — el Worker `lavasec-api`, la RLS de Supabase y el almacenamiento en `user_backups`.
- [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) — los preajustes de resolutor y los transportes cuyos ajustes se llevan en el contenido de la copia de seguridad.
