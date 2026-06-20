---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Backend y datos

> **Público:** ingenieros de backend. **Alcance:** la capa de servidor — los dos Cloudflare Workers, el esquema/RLS/autenticación de Supabase Postgres, los almacenes Cloudflare R2 y D1, toda la superficie de la API HTTP, la configuración y el despliegue, y cómo se aplica en el servidor el modelo de solo-URL-de-origen.
>
> **Referencia autoritativa:** cuando un plan y el código no coinciden, **gana el código** — las divergencias se señalan en línea. Las etiquetas de estado usan la leyenda del conjunto de documentos: **Implementado** (publicado y confirmado en el código), **En curso** (parcialmente incorporado), **Planificado** (diseñado, no construido), **Descartado** (rechazado o revertido).

## 1. La forma del backend

El backend es deliberadamente pequeño y respetuoso con la privacidad. Es un borde de metadatos y cuentas, no un servicio de filtrado. **Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas — el backend guarda únicamente metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.** No hay tablas para consultas DNS rutinarias ni telemetría por dominio, y el inicio de sesión es opcional y nunca obligatorio para la protección.

La capa de servidor se divide en dos componentes: el código del Worker de backend y el esquema de la base de datos.

| Componente | Función |
|---|---|
| **Worker lavasec-api** | Borde principal: lecturas públicas del catálogo, sincronización de listas de bloqueo y publicación del catálogo (admin + cron), informes de errores anónimos, comentarios de ayuda, eliminación de cuentas, réplica de derechos de la App Store, píxeles de sonda de QA, comprobación de acceso de QA de la cuenta, promoción de clasificación de informes de errores |
| **Worker lavasec-email** | Reenviador de solo recepción de Cloudflare Email Routing para `@lavasecurity.app` |
| **Supabase Postgres** (un proyecto de Supabase Postgres) | Cuentas, copias de seguridad cifradas, metadatos del catálogo, tablas accesibles solo con el rol de servicio; RLS en cada tabla pública |
| **Cloudflare R2** (un bucket de producción, con un bucket de vista previa aparte para staging) | Instantáneas del catálogo + el cursor de sincronización; **nunca** los bytes de listas de bloqueo de terceros |
| **Cloudflare D1** (la base de datos de comentarios de ayuda) | Votos anónimos de solo adición sobre los artículos de ayuda |

El Worker accede a Supabase mediante PostgREST (`/rest/v1`) y Auth (`/auth/v1`) usando una credencial de rol de servicio de Supabase — no hay un SDK de Supabase en el servidor; las llamadas son `fetch` directas a través de las funciones auxiliares `supabase()` / `supabaseAuth()`.

Estado: **Implementado**.

## 2. Worker lavasec-api

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, un binding de R2 → el bucket de producción (un bucket de vista previa aparte para staging), un binding de D1 → la base de datos de comentarios de ayuda, y **dos disparadores de cron**: uno que se ejecuta cada 6 horas (sincronización de listas de bloqueo + publicación del catálogo) y otro que se ejecuta cada 2 minutos (promoción de clasificación de informes de errores). Se sirve en `api.lavasecurity.app`.

### 2.1 Superficie de la API

El enrutamiento es un despachador plano `route()`. Todo está **Implementado** salvo que se indique lo contrario.

**Público / sin autenticar**

| Método y ruta | Manejador | Notas |
|---|---|---|
| `GET /healthz` | en línea | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Sirve `catalog/latest.json` desde R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Sirve `catalog/{version}.json` desde R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (predeterminado 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anónimo, inicio de sesión opcional; solo campos de depuración de la lista permitida |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto anónimo sobre un artículo → **D1**, no Supabase |

> La carga de adjuntos (una antigua ruta `PUT /v1/bug-reports/:id/attachment`) se ha **eliminado**; las capturas de pantalla y los detalles adicionales se gestionan a través de un canal de soporte con intervención humana. El Worker solo elimina, con el mejor esfuerzo posible, cualquier objeto adjunto heredado durante la eliminación de la cuenta.

**Cuenta (se requiere un token de acceso de Supabase)**

| Método y ruta | Manejador | Notas |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valida el token de acceso del usuario, elimina sus filas + cualquier objeto adjunto heredado en R2, y luego elimina el usuario de Supabase Auth con el rol de servicio |
| `GET /v1/account/qa-access` | `accountQAAccess` | Devuelve `is_developer` de la lista permitida `qa_developers`, accesible solo con el rol de servicio |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Inserta o actualiza una fila de `entitlements` (plan `lava_security_plus`) a partir de un JWS de StoreKit verificado por el cliente |

> **Sin rutas `/v1/backup`.** La recuperación de copias de seguridad asistida por llave de acceso es ahora de **conocimiento cero** y completamente del lado del cliente (véanse §4.3 y §5); el Worker no tiene rutas `/v1/backup/*` ni código de WebAuthn/llaves de acceso.

**Admin (una clave de API de admin mediante `requireAdmin`)**

| Método y ruta | Manejador |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Los endpoints HTTP de admin están protegidos por una clave de API de admin. La ruta de sincronización programada (cron) **no** llama a estas rutas HTTP — invoca la lógica de sincronización (`syncBlocklistSources`) directamente dentro del manejador `scheduled`.

**Hosts de sonda de QA** — las solicitudes a los cuatro hosts `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) se atajan antes del enrutamiento y devuelven un PNG de 1×1 con `no-store` a través de `getQAProbePixel`. Estos no se escriben en Supabase ni en R2.

### 2.2 Bindings y cron

- **Binding de R2** — `catalog/latest.json`, `catalog/{version}.json` y el cursor rotatorio `catalog/scheduled-sync-cursor.json`. **Nunca almacena los bytes de listas de bloqueo de terceros.** (Los objetos adjuntos heredados de informes de errores solo se *eliminan* — con el mejor esfuerzo durante la eliminación de la cuenta — nunca se escriben.)
- **Binding de D1** — filas anónimas de solo adición con `article_id` / `locale` / `vote` / `path`; se mantiene separado de Supabase por diseño.
- **Cron (`scheduled`)** — el manejador se ramifica según el id de cron:
  - **Cada 6 horas** — sincroniza **una** fuente por ejecución, rotando mediante el cursor de R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), y luego vuelve a publicar el catálogo. Repartir la carga evita golpear todas las fuentes de origen a la vez.
  - **Cada 2 minutos** — ejecuta una ruta interna de clasificación de informes de errores que promueve los nuevos informes anónimos a una cola de seguimiento de incidencias interna, avanzando su propio cursor de marca de agua. Esto es herramienta de operaciones interna; los identificadores del seguimiento de incidencias/notificaciones son configuración, no parte de la API pública.

## 3. Catálogo y aplicación del modelo de solo-URL-de-origen

Esta es la parte del backend más específica de la postura de cumplimiento de Lava, así que recibe respaldo del lado del servidor.

### 3.1 El modelo de solo-URL-de-origen

> **Solo-URL-de-origen:** modelo de distribución conforme con GPL/propiedad intelectual: Lava publica únicamente la URL de origen + los hashes aceptados; el dispositivo descarga/analiza las listas por sí mismo. Lava **nunca** almacena, replica, transforma ni sirve los bytes de listas de bloqueo de terceros.

Cada fila de `blocklist_sources` lleva `redistribution_mode`, cuyo único valor permitido es `"source_url_only"`. El catálogo que lee el dispositivo (`/v1/catalog`, `schema_version` 2) divide las entradas en `sources[]` y `guardrails[]`; cada entrada lleva la `source_url` de origen más `accepted_source_hashes` (SHA-256 + tamaño en bytes + número de entradas + `reviewed_at` + estado `accepted`) — nunca los bytes de la lista. Véase `formatCatalogEntry`.

> **Descartado:** un diseño anterior replicaba en R2 los archivos de listas GPL con sus bytes preservados (el plan de cumplimiento de GPL-raw-R2). Fue **sustituido el 2026-05-25** por el modelo de solo-URL-de-origen. Lava ya no almacena ni sirve los bytes de listas de bloqueo de terceros. El nombre de la tabla `mirror_events` es un vestigio heredado de ese diseño abandonado — ahora es simplemente el registro de auditoría de sincronización/publicación.

### 3.2 Cómo lo aplica el Worker en las escrituras

La ruta de sincronización (`syncOneBlocklist`, admin y cron) descarga cada `source_url` de origen, normaliza/valida **localmente en el Worker solo para calcular metadatos** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), escribe una fila de `blocklist_versions` y vuelve a publicar. Las claves de almacenamiento de bytes se fijan a null de forma fija:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Una migración (`20260525000000_add_blocklist_distribution_mode.sql`) convirtió estas columnas a nullable y puso los valores existentes a null, de modo que la postura de no-réplica también se aplica a nivel de esquema. El catálogo publicado se escribe en **ambos** `catalog/{version}.json` y `catalog/latest.json` en R2 (`publishCatalog`).

### 3.3 Salvaguardas de normalización (solo metadatos)

La normalización del lado del Worker (`normalizeBlocklist`) filtra dominios protegidos, aplica los límites máximos y deduplica+ordena. Esto sirve puramente para calcular metadatos fiables; el **dispositivo vuelve a validar los hashes aceptados** cuando descarga la lista real, así que esto no es por sí solo un límite de seguridad. Constantes clave:

- `PROTECTED_SUFFIXES` — descarta cualquier regla que coincida con dominios de Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, de modo que una fuente de origen comprometida no pueda bloquear la propia infraestructura de Lava ni los proveedores de inicio de sesión.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 Qué es publicable

`isPublicBlocklistSource` solo publica una fuente cuando `status` es `sync` o `nosync`, `redistribution_mode === "source_url_only"`, **y** `isAllowedLaunchGPLSource` lo permite. La verificación de lanzamiento de GPL (`isAllowedLaunchGPLSource`) permite las fuentes no-GPL sin restricción, pero limita las fuentes GPL-3.0 a los prefijos de `list_id` `hagezi-` u `oisd-`.

### 3.5 Fuentes precargadas y habilitadas por defecto

Las fuentes seleccionadas se precargan como metadatos de solo-URL-de-origen mediante migraciones (HaGeZi, OISD, The Block List Project, Phishing.Database, AdGuard). La migración de bajo riesgo (`20260526000000_low_risk_blocklist_sources.sql`) inicialmente precargó `blocklistproject-basic` (Unlicense) con `default_enabled = true`, forzó **todas las fuentes GPL (HaGeZi/OISD) a `default_enabled = false`** a la espera de asesoría legal, y aparcó AdGuard DNS Filter en `license_review`. **Esa precarga inicial de Basic-por-defecto se sustituyó más tarde** — la migración de alineación que sigue cambia Basic a `false` y Phishing + Scam a `true` (el valor predeterminado servido actual). Estado: **Implementado**.

> **Los valores predeterminados del catálogo coinciden con el cliente.** El conjunto `default_enabled` del catálogo es ahora **{Block List Project Phishing, Block List Project Scam}**, coincidiendo con el valor recomendado por defecto de iOS (`AppConfiguration.lavaRecommendedDefaults`, en `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`). Una migración establece `blocklistproject-basic default_enabled = false` y `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`, de modo que los metadatos servidos son veraces. (la decisión de alineación ya está publicada.) Ten en cuenta que `default_enabled` es informativo: la verdadera puerta de nivel es el **presupuesto de reglas de filtrado (Free 500K / Plus 2M)**, no el número de listas. La justificación legal para publicar URLs (no bytes) está en [decisión de cumplimiento de GPL solo-URL-de-origen](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres

Un proyecto de Supabase Postgres. RLS está habilitado en **cada** tabla pública.

### 4.1 Esquema principal

`20260516034033_backend_core.sql` crea la base (RLS habilitado en las 7 tablas públicas):

- **`profiles`, `user_settings`, `entitlements`** — estado de la cuenta por usuario. Un disparador `handle_new_user()` crea automáticamente las filas de `profiles` + `user_settings` al insertar en `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — las tablas de metadatos del catálogo. Una fuente es una lista de origen seleccionada (`list_id`, `source_url`, licencia, riesgo, `default_enabled`, `status`, `redistribution_mode`); una versión son los metadatos de una instantánea sincronizada (hashes, `entry_count`, `byte_size`), enlazada de vuelta mediante `latest_version_id`.
- **`mirror_events`** — registro de auditoría de eventos `sync` / `catalog_publish` accesible solo con el rol de servicio (nombre heredado; véase §3.1).
- **`bug_reports`** — informes anónimos accesibles solo con el rol de servicio.

Migraciones posteriores añaden **`user_backups`** (§4.3) y **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modelo de RLS

| Tabla(s) | Política | Efecto |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | por usuario `auth.uid() = user_id` | cada usuario ve solo sus propias filas |
| `blocklist_sources` | lectura pública donde `status in ('sync','nosync')` (`backend_core.sql:262-266`) | cualquiera puede leer las fuentes seleccionadas y elegibles para sincronización |
| `blocklist_versions` | lectura pública donde `validation_status = 'published'` (`backend_core.sql:268-272`) | cualquiera puede leer los metadatos de las versiones publicadas |
| `bug_reports`, `mirror_events` | `using(false)` explícito (`20260516034136_backend_core_advisor_fixes.sql`) | sin acceso anónimo/autenticado — el Worker usa el rol de servicio |
| `qa_developers` | RLS activado + **revocar todo a anon, authenticated** | accesible solo con el rol de servicio; la lista permitida de QA nunca es legible por el cliente |

La separación importa: los informes de errores anónimos deben poder ser *insertados* por el Worker sin ser *legibles* por los clientes, y la lista permitida de QA solo debe poder leerse con el rol de servicio.

### 4.3 Autenticación y el sobre de copia de seguridad cifrada

La **autenticación** es opcional. El inicio de sesión es **solo con Apple + Google** (correo/contraseña está **Descartado**). Ambos usan la concesión nativa `id_token` intercambiada en Supabase Auth `auth/v1/token?grant_type=id_token` con un nonce con hash; la app guarda únicamente la sesión resultante de forma local en el dispositivo, en el Keychain. El flujo del lado del cliente vive en la app de iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — véase [Cuentas y copia de seguridad](./accounts-and-backup.md) para el modelo completo de cuenta/copia de seguridad.

> **Copia de seguridad de conocimiento cero:** sobre AES-256-GCM del lado del cliente; solo el texto cifrado + metadatos no secretos suben a Supabase `user_backups` (RLS por usuario). El servidor no puede descifrar sin un secreto que custodia el usuario.

El hecho clave del backend: **el cliente de iOS lee/escribe `user_backups` directamente mediante Supabase PostgREST bajo RLS por usuario** (upsert sobre `user_id`, acotado por el token de acceso). **No hay rutas `/v1/backup`** en el Worker en absoluto. El Worker toca `user_backups` exactamente una vez: para eliminarlo durante la eliminación de la cuenta (`deleteAccount`).

`user_backups` almacena únicamente texto cifrado opaco + metadatos no secretos del sobre (parámetros/sales de KDF, nonces, etiquetas de ranura de clave, pistas de esquema del cliente). Límites de tamaño (`20260605000000_tighten_backup_envelope_constraints.sql`): texto cifrado ≤ 262144 bytes (256 KiB) / ≤ 349528 caracteres, metadatos ≤ 32768 bytes (32 KiB). La base de datos nunca almacena ajustes en texto plano, contraseñas, frases ni claves.

### 4.4 Eliminación de cuentas

`POST /v1/account/delete` valida el token de acceso del usuario y luego elimina sus filas de `bug_reports` (y cualquier objeto adjunto heredado coincidente en R2), `user_backups`, `entitlements`, `user_settings` y `profiles`, y finalmente elimina el usuario de Supabase Auth a través del endpoint `/admin/users` del rol de servicio. Devuelve únicamente un estado de eliminación + los proveedores vinculados. Estado: **Implementado** (el frontmatter del plan indica `status: Done` y el archivo está en `plans/implemented/`; una anotación obsoleta **en el cuerpo** todavía dice "Backlog", pero la carpeta de la vía + la presencia en el código lo dan por publicado).

### 4.5 Réplica de derechos de la App Store

`POST /v1/account/entitlements/app-store-sync` inserta o actualiza una fila de `entitlements` (plan `lava_security_plus`) a partir de un JWS de transacción de StoreKit verificado por el cliente, resolviendo conflictos por `user_id`. El `verification_status` almacenado es literalmente `"client_verified_storekit"` — el servidor **no** vuelve a verificar el JWS. IDs de producto permitidos: `lava_security_plus_{monthly,yearly,lifetime}`.

> La réplica está **Implementada**; la **verificación del JWS del lado del servidor está Planificada** (aún no construida). El JWS firmado se almacena para verificarlo más adelante. Ten en cuenta el modelo de niveles en otro lugar: el derecho de la app es local (`isPaid`) **sin sincronización con el backend todavía** como fuente de verdad — esta fila es una réplica, no la puerta.

## 5. Recuperación asistida por llave de acceso (conocimiento cero)

La recuperación de copias de seguridad asistida por llave de acceso es de **conocimiento cero** y completamente del lado del cliente. El material de la clave de recuperación se deriva en el dispositivo a partir de la salida **WebAuthn PRF / hmac-secret** de la llave de acceso; el servidor no almacena **ningún** secreto de recuperación, no registra **ninguna** llave de acceso y no emite **ningún** desafío de WebAuthn. No hay una ruta de custodia controlada por el servidor.

Las tablas de custodia que usaba un diseño anterior (`backup_passkey_recovery`, `backup_passkey_challenges`) se eliminaron antes del lanzamiento, y el Worker no lleva rutas `/v1/backup/*` ni código de WebAuthn/llaves de acceso. (Queda una entrada `@simplewebauthn/server` en el `package.json` del Worker como dependencia sobrante sin usar.)

El lado del cliente vive en la app de iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` controla la creación/aserción de la llave de acceso con capacidad PRF, y `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva la ranura a partir de la salida hmac-secret. La salida PRF se lee solo durante la aserción y nunca sale del dispositivo. Un proveedor de llaves de acceso sin PRF no puede respaldar una ranura de conocimiento cero, así que la configuración falla pronto y el usuario recurre a una frase de recuperación. Estado: **Implementado**.

## 6. Worker lavasec-email

Solo recibe y reenvía. Reenvía `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` a un buzón de operador verificado, rechaza destinatarios desconocidos y el correo de más de 10 MiB, y **no almacena los cuerpos de los correos**. Las respuestas automáticas de soporte están programadas pero condicionadas al envío de correo saliente de pago de Cloudflare (aplazado). Las constantes de enrutamiento viven en `email-service.ts:9` (`ROUTED_RECIPIENTS`); el manejador de entrada es `handleInboundEmail`. Estado: **Implementado** (la ruta de respuesta automática **Planificada**/aplazada).

## 7. Configuración y despliegue

- **La configuración está en `wrangler.toml`, que está en gitignore**; `wrangler.toml.example` es la plantilla incluida en el repositorio. Trata el `wrangler.toml` local como autoritativo para los valores específicos del entorno.
- **Vars** (no secretas, en `[vars]`): la URL de Supabase, el origen público de la API (`https://api.lavasecurity.app`), el TTL de caché del catálogo (predeterminado 300s), un límite de tamaño de informe de errores, un interruptor de auditoría de eliminación de cuentas y una marca de aceleración del runtime de Workers. La clasificación interna de informes de errores añade una clave de cola de clasificación interna y un origen de panel usado al componer los enlaces de clasificación.
- **Secretos** (mediante `wrangler secret put`): una credencial de rol de servicio de Supabase, una clave de API de admin y — para la ruta de clasificación de informes de errores — una clave de API del seguimiento de incidencias y un webhook opcional de notificación de chat.
- **El despliegue es manual**: `npm run deploy` → `wrangler deploy`. No hay CI para el Worker.
- **Enrutamiento de Cloudflare**: `lavasecurity.app` permanece en Pages; `api.lavasecurity.app` y `*.qa-probe.lavasecurity.app` se resuelven a este Worker.
- **Compatibilidad**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` está definido en vars pero el código del Worker no lo referencia; es una marca de aceleración del runtime de Workers, no un ajuste de la aplicación.

## 8. Invariantes de privacidad (qué hay y qué no hay aquí)

Una lista rápida de comprobación para quien amplíe el backend — ninguno de estos puntos puede romperse en silencio:

1. **Sin telemetría de DNS/navegación.** No hay tabla para consultas DNS rutinarias ni telemetría por dominio. El filtrado se queda en el dispositivo.
2. **Sin bytes de listas de bloqueo de terceros** en R2 ni en Postgres — solo `source_url` + hashes aceptados (§3).
3. **`user_backups` es opaco** — solo texto cifrado + metadatos no secretos; lo escribe el cliente (no el Worker) bajo RLS (§4.3).
4. **Aislamiento por rol de servicio** para `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Todas las rutas de copia de seguridad son de conocimiento cero** — incluida la recuperación asistida por llave de acceso, cuyo material de clave se deriva del lado del cliente a partir de la salida WebAuthn PRF/hmac-secret. El servidor no almacena ningún secreto de recuperación y no ejecuta WebAuthn (§5).

## Véase también

- [Visión general del sistema](./system-overview.md) — todo el sistema en una página, incluidos los límites de confianza.
- [Cliente de iOS](./ios-client.md) — el lado del dispositivo que consume este backend.
- [Cuentas y copia de seguridad](./accounts-and-backup.md) — autenticación del lado del cliente, el sobre AES-256-GCM, las ranuras de clave y las frases de recuperación.
- [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) — el lado del dispositivo del catálogo: descarga directa desde el origen, análisis/normalización y el presupuesto de reglas de filtrado.
- [Decisión de cumplimiento de GPL solo-URL-de-origen](../legal/gpl-source-url-only-compliance-decision.md) — por qué el catálogo publica URLs, no bytes.
- **Niveles y monetización** (interno) — el presupuesto de reglas de filtrado (Free 500K / Plus 2M) que es la verdadera puerta entre Free/Plus.
- **Registro de riesgos de propiedad intelectual** (interno) — la justificación de propiedad intelectual/cumplimiento detrás del modelo de solo-URL-de-origen.
