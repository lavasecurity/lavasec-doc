---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Backend y datos

> **Público:** ingenieros de backend. **Alcance:** la capa de servidor — los dos Workers de Cloudflare, el esquema/RLS/autenticación de Postgres en Supabase, los almacenes Cloudflare R2 y D1, toda la superficie de la API HTTP, la configuración y el despliegue, y cómo se aplica «solo URL de origen» en el servidor.
>
> **Referencia autorizada:** cuando un plan y el código no coinciden, **manda el código** — las divergencias se señalan en línea. Las etiquetas de estado usan la leyenda del conjunto de documentos: **Implementado** (entregado y confirmado en el código), **En curso** (parcialmente incorporado), **Planificado** (diseñado, no construido), **Descartado** (rechazado o revertido).

## 1. La forma del backend {#1-the-shape-of-the-backend}

El backend es deliberadamente pequeño y respetuoso con la privacidad. Es un borde de metadatos y cuentas, no un servicio de filtrado. **Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas — el backend guarda únicamente metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.** No hay tablas para consultas DNS rutinarias ni telemetría por dominio, y el inicio de sesión de la cuenta es opcional y nunca se requiere para la protección.

La capa de servidor se divide en dos componentes: el código del Worker de backend y el esquema de la base de datos.

| Componente | Función |
|---|---|
| **Worker lavasec-api** | Borde principal: lecturas públicas del catálogo, sincronización admin+cron de listas de bloqueo y publicación del catálogo, informes de errores anónimos, comentarios de ayuda, eliminación de cuentas, reflejo de derechos del App Store, píxeles de sondeo QA, comprobación de acceso QA de la cuenta, promoción de clasificación de informes de errores |
| **Worker lavasec-email** | Reenviador de solo recepción de Cloudflare Email Routing para `@lavasecurity.app` |
| **Postgres de Supabase** (un proyecto Postgres de Supabase) | Cuentas, copias de seguridad cifradas, metadatos del catálogo, tablas exclusivas del rol de servicio; RLS en cada tabla pública |
| **Cloudflare R2** (un bucket de producción, con un bucket de vista previa aparte para staging) | Instantáneas del catálogo + el cursor de sincronización; **nunca** bytes de listas de bloqueo de terceros |
| **Cloudflare D1** (la base de datos de comentarios de ayuda) | Votos de comentarios anónimos sobre artículos de ayuda, de solo añadido |

El Worker accede a Supabase mediante PostgREST (`/rest/v1`) y Auth (`/auth/v1`) usando una credencial de rol de servicio de Supabase — no hay SDK de Supabase en el servidor; las llamadas son `fetch` en crudo mediante los ayudantes `supabase()` / `supabaseAuth()`.

Estado: **Implementado**.

## 2. Worker lavasec-api {#2-lavasec-api-worker}

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, un enlace R2 → el bucket de producción (un bucket de vista previa aparte para staging), un enlace D1 → la base de datos de comentarios de ayuda, y **dos disparadores cron**: uno que se activa cada 6 horas (sincronización de listas de bloqueo + publicación del catálogo) y otro que se activa cada 2 minutos (promoción de clasificación de informes de errores). Se sirve en `api.lavasecurity.app`.

### 2.1 Superficie de la API {#21-api-surface}

El enrutamiento es un despachador plano `route()`. Todo está **Implementado** salvo que se indique lo contrario.

**Público / sin autenticación**

| Método y ruta | Manejador | Notas |
|---|---|---|
| `GET /healthz` | en línea | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Sirve `catalog/latest.json` desde R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Sirve `catalog/{version}.json` desde R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (por defecto 300 s) |
| `POST /v1/bug-reports` | `createBugReport` | Anónimo, inicio de sesión opcional; solo campos de depuración en lista de permitidos |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto anónimo sobre artículo → **D1**, no Supabase |

> La carga de adjuntos (una antigua ruta `PUT /v1/bug-reports/:id/attachment`) ha sido **eliminada**; las capturas de pantalla y los detalles adicionales se gestionan a través de un canal de soporte mediado por personas. El Worker solo elimina, con el mejor esfuerzo, cualquier objeto adjunto heredado durante la eliminación de la cuenta.

**Cuenta (se requiere token de acceso de Supabase)**

| Método y ruta | Manejador | Notas |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valida el token de acceso del usuario, elimina sus filas + cualquier objeto adjunto heredado de R2, y luego elimina al usuario de Supabase Auth con el rol de servicio |
| `GET /v1/account/qa-access` | `accountQAAccess` | Devuelve `is_developer` desde la lista de permitidos `qa_developers`, exclusiva del rol de servicio |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Inserta o actualiza una fila de `entitlements` (plan `lava_security_plus`) a partir de un JWS de StoreKit verificado por el cliente |

> **No hay rutas `/v1/backup`.** La recuperación de copia de seguridad asistida por passkey ahora es de **conocimiento cero** y completamente del lado del cliente (ver §4.3 y §5); el Worker no tiene rutas `/v1/backup/*` ni código de WebAuthn/passkey.

**Admin (una clave de API de admin mediante `requireAdmin`)**

| Método y ruta | Manejador |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Los endpoints HTTP de admin están protegidos por una clave de API de admin. La ruta de sincronización programada (cron) **no** llama a estas rutas HTTP — invoca la lógica de sincronización (`syncBlocklistSources`) directamente dentro del manejador `scheduled`.

**Hosts de sondeo QA** — las solicitudes a los cuatro hosts `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) se interceptan antes del enrutamiento y devuelven un PNG `no-store` de 1×1 mediante `getQAProbePixel`. Estos no se escriben en Supabase ni en R2.

### 2.2 Enlaces y cron {#22-bindings--cron}

- **Enlace R2** — `catalog/latest.json`, `catalog/{version}.json`, y el cursor de turno rotatorio `catalog/scheduled-sync-cursor.json`. **Nunca almacena bytes de listas de bloqueo de terceros.** (Los objetos adjuntos heredados de informes de errores solo se *eliminan* — con el mejor esfuerzo durante la eliminación de la cuenta — nunca se escriben.)
- **Enlace D1** — filas anónimas de solo añadido `article_id` / `locale` / `vote` / `path`; mantenidas separadas de Supabase por diseño.
- **Cron (`scheduled`)** — el manejador se ramifica según el id del cron:
  - **Cada 6 horas** — sincroniza **un** origen por ejecución, en turno rotatorio mediante el cursor de R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), y luego republica el catálogo. Repartir la carga evita golpear todos los orígenes upstream a la vez.
  - **Cada 2 minutos** — ejecuta una ruta interna de clasificación de informes de errores que promueve los nuevos informes anónimos a una cola interna de seguimiento de incidencias, avanzando su propio cursor de marca de agua. Esto es herramienta interna de operaciones; los identificadores del seguidor de incidencias/notificaciones son configuración, no forman parte de la API pública.

## 3. Catálogo y aplicación de «solo URL de origen» {#3-catalog--source-url-only-enforcement}

Esta es la parte del backend más específica de la postura de cumplimiento de Lava, así que se le da fuerza del lado del servidor.

### 3.1 El modelo de solo URL de origen {#31-the-source-url-only-model}

> **Solo URL de origen:** modelo de distribución conforme a GPL/propiedad intelectual: Lava publica únicamente la URL upstream + los hashes aceptados; el dispositivo descarga/analiza las listas por sí mismo. Lava **nunca** almacena, refleja, transforma ni sirve bytes de listas de bloqueo de terceros.

Cada fila de `blocklist_sources` lleva `redistribution_mode`, cuyo único valor permitido es `"source_url_only"`. El catálogo que lee el dispositivo (`/v1/catalog`, `schema_version` 2) divide las entradas en `sources[]` y `guardrails[]`; cada entrada lleva la `source_url` upstream más `accepted_source_hashes` (SHA-256 + tamaño en bytes + número de entradas + `reviewed_at` + estado `accepted`) — nunca los bytes de la lista. Ver `formatCatalogEntry`.

> **Descartado:** un diseño anterior reflejaba en R2 archivos de listas GPL con los bytes preservados (el plan de cumplimiento GPL-raw-R2). Fue **reemplazado el 2026-05-25** por «solo URL de origen». Lava ya no almacena ni sirve bytes de listas de bloqueo de terceros. El nombre de la tabla `mirror_events` es un vestigio heredado de aquel diseño abandonado — ahora es simplemente el registro de auditoría de sincronización/publicación.

### 3.2 Cómo lo aplica el Worker en las escrituras {#32-how-the-worker-enforces-it-on-writes}

La ruta de sincronización (`syncOneBlocklist`, admin y cron) descarga cada `source_url` upstream, normaliza/valida **localmente en el Worker solo para calcular metadatos** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), escribe una fila de `blocklist_versions` y republica. Las claves de almacenamiento de bytes se escriben de forma fija a null:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Una migración (`20260525000000_add_blocklist_distribution_mode.sql`) dejó estas columnas como anulables y puso a null los valores existentes, de modo que la postura de no reflejo también se aplica a nivel de esquema. El catálogo publicado se escribe en **ambos** `catalog/{version}.json` y `catalog/latest.json` en R2 (`publishCatalog`).

### 3.3 Salvaguardas de normalización (solo metadatos) {#33-normalization-guardrails-metadata-only}

La normalización del lado del Worker (`normalizeBlocklist`) filtra dominios protegidos, aplica límites y deduplica+ordena. Esto es puramente para calcular metadatos fiables; el **dispositivo revalida los hashes aceptados** cuando descarga la lista real, así que esto no es por sí solo una frontera de seguridad. Constantes clave:

- `PROTECTED_SUFFIXES` — elimina cualquier regla que coincida con dominios de Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, de modo que un origen upstream envenenado no pueda bloquear la propia infraestructura de Lava ni sus proveedores de inicio de sesión.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 Qué es publicable {#34-what-is-publishable}

`isPublicBlocklistSource` solo publica un origen cuando `status` es `sync` o `nosync`, `redistribution_mode === "source_url_only"`, **y** `isAllowedLaunchGPLSource` da el visto bueno. La compuerta de lanzamiento GPL (`isAllowedLaunchGPLSource`) permite libremente los orígenes no GPL, pero restringe los orígenes GPL-3.0 a los prefijos de `list_id` `hagezi-` u `oisd-`.

### 3.5 Orígenes sembrados y habilitados por defecto {#35-seeded-sources--default-enabled}

Los orígenes curados se siembran como metadatos de solo URL de origen mediante migraciones (HaGeZi, OISD, The Block List Project, Phishing.Database, AdGuard). La migración de bajo riesgo (`20260526000000_low_risk_blocklist_sources.sql`) sembró inicialmente `blocklistproject-basic` (Unlicense) con `default_enabled = true`, forzó **todos los orígenes GPL (HaGeZi/OISD) a `default_enabled = false`** a la espera de asesoría legal, y dejó AdGuard DNS Filter en `license_review`. **Esa siembra inicial con Basic por defecto fue reemplazada después** — la migración de alineación de más abajo cambia Basic a `false` y Phishing + Scam a `true` (el valor por defecto servido actual). Estado: **Implementado**.

> **Los valores por defecto del catálogo coinciden con el cliente.** El conjunto `default_enabled` del catálogo ahora es **{Block List Project Phishing, Block List Project Scam}**, coincidiendo con el valor por defecto recomendado de iOS (`AppConfiguration.lavaRecommendedDefaults`, en `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`). Una migración establece `blocklistproject-basic default_enabled = false` y `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`, de modo que los metadatos servidos son veraces. (la decisión de alineación ya está entregada.) Ten en cuenta que `default_enabled` es informativo: la verdadera compuerta de nivel es el **presupuesto de reglas de filtrado (Free 500K / Plus 2M)**, no el número de listas. El fundamento legal para publicar URLs (no bytes) está en [Decisión de cumplimiento GPL solo URL de origen](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Postgres de Supabase {#4-supabase-postgres}

Un proyecto Postgres de Supabase. RLS está habilitado en **cada** tabla pública.

### 4.1 Esquema central {#41-core-schema}

`20260516034033_backend_core.sql` crea la base (RLS habilitado en las 7 tablas públicas):

- **`profiles`, `user_settings`, `entitlements`** — estado de cuenta por usuario. Un disparador `handle_new_user()` crea automáticamente filas de `profiles` + `user_settings` al insertar en `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — las tablas de metadatos del catálogo. Un origen es una lista upstream curada (`list_id`, `source_url`, licencia, riesgo, `default_enabled`, `status`, `redistribution_mode`); una versión son los metadatos de una instantánea sincronizada (hashes, `entry_count`, `byte_size`), vinculados de vuelta mediante `latest_version_id`.
- **`mirror_events`** — registro de auditoría exclusivo del rol de servicio de eventos `sync` / `catalog_publish` (nombre heredado; ver §3.1).
- **`bug_reports`** — informes anónimos exclusivos del rol de servicio.

Migraciones posteriores añaden **`user_backups`** (§4.3) y **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modelo RLS {#42-rls-model}

| Tabla(s) | Política | Efecto |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | `auth.uid() = user_id` por usuario | cada usuario ve solo sus propias filas |
| `blocklist_sources` | lectura pública donde `status in ('sync','nosync')` (`backend_core.sql:262-266`) | cualquiera puede leer orígenes curados y elegibles para sincronización |
| `blocklist_versions` | lectura pública donde `validation_status = 'published'` (`backend_core.sql:268-272`) | cualquiera puede leer metadatos de versiones publicadas |
| `bug_reports`, `mirror_events` | `using(false)` explícito (`20260516034136_backend_core_advisor_fixes.sql`) | sin acceso anónimo/autenticado — el Worker usa el rol de servicio |
| `qa_developers` | RLS activado + **revocar todo a anon, authenticated** | exclusivo del rol de servicio; la lista de permitidos de QA nunca es legible por el cliente |

La división importa: los informes de errores anónimos deben ser *insertables* por el Worker sin ser *legibles* por los clientes, y la lista de permitidos de QA solo debe ser leída por el rol de servicio.

### 4.3 Autenticación y el sobre de copia de seguridad cifrado {#43-auth--the-encrypted-backup-envelope}

La **autenticación** es opcional. El inicio de sesión es **solo con Apple + Google** (correo/contraseña está **Descartado**). Ambos usan la concesión nativa `id_token` intercambiada en Supabase Auth `auth/v1/token?grant_type=id_token` con un nonce con hash; la app guarda únicamente la sesión resultante de forma local en el dispositivo, en el Keychain. El flujo del lado del cliente vive en la app de iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — ver [Cuentas y copia de seguridad](./accounts-and-backup.md) para el modelo completo de cuenta/copia de seguridad.

> **Copia de seguridad de conocimiento cero:** sobre AES-256-GCM del lado del cliente; solo el texto cifrado + los metadatos no secretos se suben a `user_backups` de Supabase (RLS por usuario). El servidor no puede descifrar sin un secreto en poder del usuario.

El hecho crucial del backend: **el cliente de iOS lee/escribe `user_backups` directamente mediante Supabase PostgREST bajo RLS por usuario** (upsert sobre `user_id`, acotado por el token de acceso). **No hay rutas `/v1/backup`** en el Worker en absoluto. El Worker toca `user_backups` exactamente una vez: para eliminarlo durante la eliminación de la cuenta (`deleteAccount`).

`user_backups` almacena únicamente texto cifrado opaco + metadatos no secretos del sobre (parámetros/sales de KDF, nonces, etiquetas de ranura de clave, pistas de esquema del cliente). Límites de tamaño (`20260605000000_tighten_backup_envelope_constraints.sql`): texto cifrado ≤ 262144 bytes (256 KiB) / ≤ 349528 caracteres, metadatos ≤ 32768 bytes (32 KiB). La base de datos nunca almacena ajustes, contraseñas, frases ni claves en texto plano.

### 4.4 Eliminación de cuenta {#44-account-deletion}

`POST /v1/account/delete` valida el token de acceso del usuario, luego elimina sus filas de `bug_reports` (y cualquier objeto adjunto heredado de R2 que coincida), `user_backups`, `entitlements`, `user_settings` y `profiles`, y finalmente elimina al usuario de Supabase Auth mediante el endpoint `/admin/users` del rol de servicio. Devuelve únicamente un estado de eliminado + los proveedores vinculados. Estado: **Implementado** (el frontmatter del plan dice `status: Done` y el archivo está en `plans/implemented/`; una anotación obsoleta **en el cuerpo** todavía dice «Backlog», pero la carpeta de fase + la presencia del código lo hacen entregado).

### 4.5 Reflejo de derechos del App Store {#45-app-store-entitlement-mirroring}

`POST /v1/account/entitlements/app-store-sync` inserta o actualiza una fila de `entitlements` (plan `lava_security_plus`) a partir de un JWS de transacción de StoreKit verificado por el cliente, en conflicto por `user_id`. El `verification_status` almacenado es literalmente `"client_verified_storekit"` — el servidor **no** vuelve a verificar el JWS. IDs de producto permitidos: `lava_security_plus_{monthly,yearly,lifetime}`.

> El reflejo está **Implementado**; la **verificación del JWS del lado del servidor está Planificada** (todavía no construida). El JWS firmado se almacena para una verificación posterior. Ten en cuenta el modelo de niveles en otra parte: el derecho de la app es local (`isPaid`) **sin sincronización con el backend todavía** como fuente de verdad — esta fila es un reflejo, no la compuerta.

## 5. Recuperación asistida por passkey (conocimiento cero) {#5-passkey-assisted-recovery-zero-knowledge}

La recuperación de copia de seguridad asistida por passkey es de **conocimiento cero** y completamente del lado del cliente. El material de clave de recuperación se deriva en el dispositivo a partir de la salida **PRF / hmac-secret de WebAuthn** del passkey; el servidor **no** almacena ningún secreto de recuperación, **no** registra ningún passkey y **no** emite ningún desafío de WebAuthn. No hay ninguna ruta de custodia controlada por el servidor.

Las tablas de custodia que usaba un diseño anterior (`backup_passkey_recovery`, `backup_passkey_challenges`) se eliminaron antes del lanzamiento, y el Worker no lleva rutas `/v1/backup/*` ni código de WebAuthn/passkey. (Una entrada `@simplewebauthn/server` permanece en el `package.json` del Worker como una dependencia sobrante sin uso.)

El lado del cliente vive en la app de iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` impulsa la creación/aserción del passkey con capacidad PRF, y `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva la ranura a partir de la salida hmac-secret. La salida PRF se lee solo durante la aserción y nunca sale del dispositivo. Un proveedor de passkey sin PRF no puede respaldar una ranura de conocimiento cero, así que la configuración falla pronto y el usuario recurre a una frase de recuperación. Estado: **Implementado**.

## 6. Worker lavasec-email {#6-lavasec-email-worker}

Solo recibe y reenvía. Reenvía `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` a un buzón de operador verificado, rechaza destinatarios desconocidos y el correo de más de 10 MiB, y **no almacena los cuerpos de los correos**. Las respuestas automáticas de soporte están programadas pero condicionadas al correo saliente de pago de Cloudflare (aplazado). Las constantes de enrutamiento viven en `email-service.ts:9` (`ROUTED_RECIPIENTS`); el manejador de entrada es `handleInboundEmail`. Estado: **Implementado** (la ruta de respuesta automática **Planificada**/aplazada).

## 7. Configuración y despliegue {#7-config--deploy}

- **La configuración es `wrangler.toml`, que está en gitignore**; `wrangler.toml.example` es la plantilla incluida en el repositorio. Trata el `wrangler.toml` local como la fuente canónica para los valores específicos del entorno.
- **Vars** (no secretas, en `[vars]`): la URL de Supabase, el origen público de la API (`https://api.lavasecurity.app`), el TTL de caché del catálogo (por defecto 300 s), un límite de tamaño de informe de errores, un interruptor de auditoría de eliminación de cuentas, y un indicador de aceleración del runtime de Workers. La clasificación interna de informes de errores añade una clave de cola de clasificación interna y un origen de panel usado al componer los enlaces de clasificación.
- **Secretos** (mediante `wrangler secret put`): una credencial de rol de servicio de Supabase, una clave de API de admin y — para la ruta de clasificación de informes de errores — una clave de API del seguidor de incidencias y un webhook opcional de notificación por chat.
- **El despliegue es manual**: `npm run deploy` → `wrangler deploy`. No hay CI para el Worker.
- **Enrutamiento de Cloudflare**: `lavasecurity.app` permanece en Pages; `api.lavasecurity.app` y `*.qa-probe.lavasecurity.app` se resuelven a este Worker.
- **Compatibilidad**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` está definido en vars pero no es referenciado por el código del Worker; es un indicador de aceleración del runtime de Workers más que un ajuste de la aplicación.

## 8. Invariantes de privacidad (qué hay y qué no hay aquí) {#8-privacy-invariants-what-is-and-isnt-here}

Una lista de comprobación rápida para cualquiera que extienda el backend — ninguna de estas puede romperse en silencio:

1. **Sin telemetría de DNS/navegación.** No hay tabla para consultas DNS rutinarias ni telemetría por dominio. El filtrado permanece en el dispositivo.
2. **Sin bytes de listas de bloqueo de terceros** en R2 ni en Postgres — solo `source_url` + hashes aceptados (§3).
3. **`user_backups` es opaco** — solo texto cifrado + metadatos no secretos; lo escribe el cliente (no el Worker) bajo RLS (§4.3).
4. **Aislamiento del rol de servicio** para `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Todas las rutas de copia de seguridad son de conocimiento cero** — incluida la recuperación asistida por passkey, cuyo material de clave se deriva del lado del cliente a partir de la salida PRF/hmac-secret de WebAuthn. El servidor no almacena ningún secreto de recuperación y no ejecuta ningún WebAuthn (§5).

## Véase también {#see-also}

- [Visión general del sistema](./system-overview.md) — todo el sistema en una página, incluidas las fronteras de confianza.
- [Cliente de iOS](./ios-client.md) — el lado del dispositivo que consume este backend.
- [Cuentas y copia de seguridad](./accounts-and-backup.md) — autenticación del lado del cliente, el sobre AES-256-GCM, las ranuras de clave y las frases de recuperación.
- [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) — el lado del dispositivo del catálogo: descarga directa desde el upstream, análisis/normalización, y el presupuesto de reglas de filtrado.
- [Decisión de cumplimiento GPL solo URL de origen](../legal/gpl-source-url-only-compliance-decision.md) — por qué el catálogo publica URLs, no bytes.
- **Niveles y monetización** (interno) — el presupuesto de reglas de filtrado (Free 500K / Plus 2M) que es la verdadera compuerta Free/Plus.
- **Registro de riesgos de PI** (interno) — el fundamento de PI/cumplimiento detrás de «solo URL de origen».
