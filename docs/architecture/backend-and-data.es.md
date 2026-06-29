---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Backend y datos

> **Audiencia:** ingenieros de backend. **Alcance:** la capa de servidor — los dos Cloudflare Workers, el esquema/RLS/auth de Supabase Postgres, los almacenes Cloudflare R2 y D1, toda la superficie de la API HTTP, configuración y despliegue, y cómo se hace cumplir source-url-only en el servidor.
>
> **Referencia autoritativa:** cuando un plan y el código no coinciden, **manda el código** — las divergencias se señalan en línea. Las etiquetas de estado usan la leyenda del conjunto de documentos: **Implementado** (entregado y confirmado en el código), **En progreso** (parcialmente integrado), **Planeado** (diseñado, no construido), **Descartado** (rechazado o revertido).

## 1. La forma del backend

El backend es deliberadamente pequeño y preserva la privacidad. Es un borde de metadatos y cuentas, no un servicio de filtrado. **Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas — el backend solo guarda metadatos del catálogo, una copia de seguridad opaca cifrada por usuario, y diagnósticos anonimizados que tú eliges enviar.** No hay tablas para consultas de DNS rutinarias ni telemetría por dominio, y el inicio de sesión en la cuenta es opcional y nunca es necesario para la protección.

La capa de servidor se divide en dos componentes: el código del Worker de backend y el esquema de la base de datos.

| Componente | Función |
|---|---|
| **Worker lavasec-api** | Borde principal: lecturas públicas del catálogo, sincronización de blocklists admin+cron y publicación del catálogo, informes de errores anónimos, comentarios de ayuda, eliminación de cuentas, replicación de derechos de App Store, píxeles de sondeo de QA, comprobación de acceso QA de la cuenta, promoción de triaje de informes de errores |
| **Worker lavasec-email** | Reenviador de solo recepción de Cloudflare Email Routing para `@lavasecurity.app` |
| **Supabase Postgres** (un proyecto de Supabase Postgres) | Cuentas, copias de seguridad cifradas, metadatos del catálogo, tablas solo de rol de servicio; RLS en cada tabla pública |
| **Cloudflare R2** (un bucket de producción, con un bucket de previsualización aparte para staging) | Instantáneas del catálogo + el cursor de sincronización; **nunca** bytes de blocklists de terceros |
| **Cloudflare D1** (la base de datos de comentarios de ayuda) | Votos de comentarios de artículos de ayuda anónimos y solo de anexión |

El Worker accede a Supabase a través de PostgREST (`/rest/v1`) y Auth (`/auth/v1`) usando una credencial de rol de servicio de Supabase — no hay SDK de Supabase en el servidor; las llamadas son `fetch` crudas a través de los helpers `supabase()` / `supabaseAuth()`.

Estado: **Implementado**.

## 2. Worker lavasec-api

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, un binding de R2 → el bucket de producción (un bucket de previsualización aparte para staging), un binding de D1 → la base de datos de comentarios de ayuda, y **dos disparadores cron**: uno que se activa cada 6 horas (sincronización de blocklists + publicación del catálogo) y otro que se activa cada 2 minutos (promoción de triaje de informes de errores). Se sirve en `api.lavasecurity.app`.

### 2.1 Superficie de la API

El enrutamiento es un despachador `route()` plano. Todo está **Implementado** salvo que se indique.

**Público / no autenticado**

| Método y ruta | Manejador | Notas |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Sirve `catalog/latest.json` desde R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Sirve `catalog/{version}.json` desde R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (por defecto 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anónimo, inicio de sesión opcional; solo campos de depuración en la lista de permitidos |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto de artículo anónimo → **D1**, no Supabase |

> La subida de adjuntos (una antigua ruta `PUT /v1/bug-reports/:id/attachment`) ha sido **eliminada**; las capturas de pantalla y el detalle adicional se gestionan mediante un canal de soporte mediado por humanos. El Worker solo elimina con el mejor esfuerzo cualquier objeto de adjunto heredado durante la eliminación de la cuenta.

**Cuenta (se requiere token de acceso de Supabase)**

| Método y ruta | Manejador | Notas |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valida el token de acceso del usuario, elimina sus filas + cualquier objeto de adjunto R2 heredado, luego elimina el usuario de Supabase Auth con el rol de servicio |
| `GET /v1/account/qa-access` | `accountQAAccess` | Devuelve `is_developer` desde la lista de permitidos `qa_developers` solo de rol de servicio |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Hace upsert de una fila `entitlements` (plan `lava_security_plus`) desde un JWS de StoreKit verificado por el cliente |

> **Sin rutas `/v1/backup`.** La recuperación de copias de seguridad asistida por passkey ahora es de **conocimiento cero** y completamente del lado del cliente (ver §4.3 y §5); el Worker no tiene rutas `/v1/backup/*` ni código de WebAuthn/passkey.

**Admin (una clave de API de admin vía `requireAdmin`)**

| Método y ruta | Manejador |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Los endpoints HTTP de admin están protegidos por una clave de API de admin. La ruta de sincronización programada (cron) **no** llama a estas rutas HTTP — invoca la lógica de sincronización (`syncBlocklistSources`) directamente dentro del manejador `scheduled`.

**Hosts de sondeo de QA** — las solicitudes a los cuatro hosts `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) se cortocircuitan antes del enrutamiento y devuelven un PNG `no-store` de 1×1 vía `getQAProbePixel`. Estos no se escriben en Supabase ni en R2.

### 2.2 Bindings y cron

- **Binding de R2** — `catalog/latest.json`, `catalog/{version}.json`, y el cursor round-robin `catalog/scheduled-sync-cursor.json`. **Nunca almacena bytes de blocklists de terceros.** (Los objetos de adjuntos de informes de errores heredados solo se *eliminan* — con el mejor esfuerzo durante la eliminación de la cuenta — nunca se escriben.)
- **Binding de D1** — filas anónimas y solo de anexión de `article_id` / `locale` / `vote` / `path`; mantenidas separadas de Supabase por diseño.
- **Cron (`scheduled`)** — el manejador se ramifica según el id del cron:
  - **Cada 6 horas** — sincroniza **una** fuente por ejecución, en round-robin a través del cursor de R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), luego vuelve a publicar el catálogo. Repartir la carga evita martillear todos los upstreams a la vez.
  - **Cada 2 minutos** — ejecuta una ruta interna de triaje de informes de errores que promueve nuevos informes anónimos a una cola interna de seguimiento de incidencias, avanzando su propio cursor de marca de agua. Esto es herramienta de operaciones internas; los identificadores de seguimiento de incidencias/notificación son configuración, no parte de la API pública.

## 3. Catálogo y cumplimiento de source-url-only

Esta es la parte del backend más específica de la postura de cumplimiento de Lava, así que recibe refuerzo del lado del servidor.

### 3.1 El modelo source-url-only

> **Source-url-only:** modelo de distribución de cumplimiento GPL/IP: Lava publica solo la URL upstream + los hashes aceptados; el dispositivo descarga/parsea las listas él mismo. Lava **nunca** almacena, replica, transforma ni sirve bytes de blocklists de terceros.

Cada fila `blocklist_sources` lleva `redistribution_mode`, cuyo único valor permitido es `"source_url_only"`. El catálogo que lee el dispositivo (`/v1/catalog`, `schema_version` 2) divide las entradas en `sources[]` y `guardrails[]`; cada entrada lleva la `source_url` upstream más `accepted_source_hashes` (SHA-256 + tamaño en bytes + recuento de entradas + `reviewed_at` + estado `accepted`) — nunca los bytes de la lista. Ver `formatCatalogEntry`.

> **Descartado:** un diseño anterior replicaba archivos de listas GPL con bytes preservados en R2 (el plan de cumplimiento GPL-raw-R2). Fue **reemplazado el 2026-05-25** por source-url-only. Lava ya no almacena ni sirve bytes de blocklists de terceros. El nombre de tabla `mirror_events` es un remanente heredado de ese diseño abandonado — ahora es solo el registro de auditoría de sincronización/publicación.

### 3.2 Cómo lo hace cumplir el Worker en las escrituras

La ruta de sincronización (`syncOneBlocklist`, admin y cron) descarga cada `source_url` upstream, normaliza/valida **localmente en el Worker solo para calcular metadatos** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), escribe una fila `blocklist_versions`, y vuelve a publicar. Las claves de almacenamiento de bytes están escritas a fuerza en null:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Una migración (`20260525000000_add_blocklist_distribution_mode.sql`) cambió estas columnas a nullable y puso los valores existentes en null, de modo que la postura de no-replicación también se hace cumplir a nivel de esquema. El catálogo publicado se escribe en **ambos** `catalog/{version}.json` y `catalog/latest.json` en R2 (`publishCatalog`).

### 3.3 Guardarraíles de normalización (solo metadatos)

La normalización del lado del Worker (`normalizeBlocklist`) filtra dominios protegidos, hace cumplir los topes, y deduplica+ordena. Esto es puramente para calcular metadatos confiables; para **listas de la comunidad** el dispositivo **no** hace una comprobación de hash en la descarga — la descarga sobre TLS desde la `source_url` curada y la parsea bajo topes (los hashes aceptados del catálogo son orientativos), por lo que esta normalización del lado del Worker no es por sí sola un límite de seguridad. (El nivel de guardarraíl de amenazas de Lava sigue estando anclado por hash en el dispositivo, y la procedencia de `source_url` se hace cumplir en el momento de la publicación — un cambio de URL debe usar un nuevo `list_id`.) Constantes clave:

- `PROTECTED_SUFFIXES` — elimina cualquier regla que coincida con dominios de Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, de modo que un upstream envenenado no pueda bloquear la propia infraestructura de Lava ni los proveedores de inicio de sesión.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 Qué es publicable

`isPublicBlocklistSource` solo publica una fuente cuando `status` es `sync` o `nosync`, `redistribution_mode === "source_url_only"`, **y** `isAllowedLaunchGPLSource` pasa. La compuerta de GPL de lanzamiento (`isAllowedLaunchGPLSource`) permite libremente las fuentes no GPL y autoriza las familias de fuentes GPL-3.0 aprobadas por prefijo de `list_id`: `hagezi-`, `oisd-`, y `adguard-`.

### 3.5 Fuentes sembradas y habilitadas por defecto

Las fuentes curadas se siembran como metadatos source-url-only vía migraciones, generadas a partir de la especificación canónica del [Catálogo de Blocklists](../legal/blocklist-catalog.md) (HaGeZi, OISD, The Block List Project, Phishing.Database, StevenBlack, AdGuard, 1Hosts). La migración de expansión de categorías agrega las categorías de defensa en profundidad (nsfw/social/gambling/piracy), realinea el valor por defecto de instalación nueva a **Block List Basic**, y reactiva AdGuard DNS Filter como una opción marcada por asesoría legal y desactivada por defecto. Estado: **Implementado**.

> **Los valores por defecto del catálogo coinciden con el cliente.** El conjunto `default_enabled` del catálogo es **{Block List Basic}** — una lista combinada amplia y permisiva que reemplaza el par anterior de Phishing + Scam — coincidiendo con el valor por defecto recomendado de iOS (`AppConfiguration.lavaRecommendedDefaults`). Tanto la columna `default_enabled` servida como el `DefaultCatalog` de iOS empaquetado se generan a partir de la misma especificación canónica, por lo que coinciden por construcción (esto resuelve la discrepancia anterior de valor por defecto cliente↔backend). Nótese que `default_enabled` es informativo: la verdadera compuerta de nivel es el **presupuesto de reglas de filtro (Free 500K / Plus 2M)**, no el número de listas. La justificación legal para publicar URLs (no bytes) está en [decisión de cumplimiento GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres

Un proyecto de Supabase Postgres. RLS está habilitado en **cada** tabla pública.

### 4.1 Esquema central

`20260516034033_backend_core.sql` crea la base (RLS habilitado en las 7 tablas públicas):

- **`profiles`, `user_settings`, `entitlements`** — estado de cuenta por usuario. Un trigger `handle_new_user()` crea automáticamente filas `profiles` + `user_settings` al insertar en `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — las tablas de metadatos del catálogo. Una fuente es una lista upstream curada (`list_id`, `source_url`, licencia, riesgo, `default_enabled`, `status`, `redistribution_mode`); una versión es los metadatos de una instantánea sincronizada (hashes, `entry_count`, `byte_size`), vinculada de vuelta vía `latest_version_id`.
- **`mirror_events`** — registro de auditoría solo de rol de servicio de los eventos `sync` / `catalog_publish` (nombre heredado; ver §3.1).
- **`bug_reports`** — informes anónimos solo de rol de servicio.

Migraciones posteriores agregan **`user_backups`** (§4.3) y **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modelo de RLS

| Tabla(s) | Política | Efecto |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | por usuario `auth.uid() = user_id` | cada usuario ve solo sus propias filas |
| `blocklist_sources` | lectura pública donde `status in ('sync','nosync')` (`backend_core.sql:262-266`) | cualquiera puede leer fuentes curadas y elegibles para sincronización |
| `blocklist_versions` | lectura pública donde `validation_status = 'published'` (`backend_core.sql:268-272`) | cualquiera puede leer metadatos de versiones publicadas |
| `bug_reports`, `mirror_events` | `using(false)` explícito (`20260516034136_backend_core_advisor_fixes.sql`) | sin acceso anónimo/autenticado — el Worker usa el rol de servicio |
| `qa_developers` | RLS activo + **revoke all from anon, authenticated** | solo de rol de servicio; la lista de permitidos de QA nunca es legible por el cliente |

La separación importa: los informes de errores anónimos deben ser *insertables* por el Worker sin ser *legibles* por los clientes, y la lista de permitidos de QA solo debe poder ser leída por el rol de servicio.

### 4.3 Auth y el sobre de copia de seguridad cifrada

**Auth** es opcional. El inicio de sesión es **solo Apple + Google** (email/contraseña está **Descartado**). Ambos usan la concesión nativa `id_token` intercambiada en Supabase Auth `auth/v1/token?grant_type=id_token` con un nonce hasheado; la app almacena solo la sesión resultante bloqueada en el dispositivo en el Keychain. El flujo del lado del cliente vive en la app de iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — ver [Cuentas y copias de seguridad](./accounts-and-backup.md) para el modelo completo de cuentas/copias de seguridad.

> **Copia de seguridad de conocimiento cero:** sobre AES-256-GCM del lado del cliente; solo el texto cifrado + metadatos no secretos se suben a `user_backups` de Supabase (RLS por usuario). El servidor no puede descifrar sin un secreto en poder del usuario.

El hecho crucial del backend: **el cliente de iOS lee/escribe `user_backups` directamente vía Supabase PostgREST bajo RLS por usuario** (upsert en `user_id`, acotado por el token de acceso). **No hay rutas `/v1/backup`** en el Worker en absoluto. El Worker toca `user_backups` exactamente una vez: para eliminarlo durante la eliminación de la cuenta (`deleteAccount`).

`user_backups` almacena solo texto cifrado opaco + metadatos del sobre no secretos (parámetros/salts de KDF, nonces, etiquetas de ranura de clave, pistas de esquema del cliente). Topes de tamaño (`20260605000000_tighten_backup_envelope_constraints.sql`): texto cifrado ≤ 262144 bytes (256 KiB) / ≤ 349528 caracteres, metadatos ≤ 32768 bytes (32 KiB). La base de datos nunca almacena configuraciones en texto plano, contraseñas, frases ni claves.

### 4.4 Eliminación de cuenta

`POST /v1/account/delete` valida el token de acceso del usuario, luego elimina sus filas `bug_reports` (y cualquier objeto de adjunto R2 heredado coincidente), `user_backups`, `entitlements`, `user_settings`, y `profiles`, y finalmente elimina el usuario de Supabase Auth vía el endpoint `/admin/users` de rol de servicio. Devuelve solo un estado de eliminación + los proveedores vinculados. Estado: **Implementado** (el frontmatter del plan dice `status: Done` y el archivo está en `plans/implemented/`; una anotación obsoleta **en el cuerpo** todavía dice "Backlog", pero la carpeta del carril + la presencia en el código lo hacen entregado).

### 4.5 Replicación de derechos de App Store

`POST /v1/account/entitlements/app-store-sync` hace upsert de una fila `entitlements` (plan `lava_security_plus`) desde un JWS de transacción de StoreKit verificado por el cliente, con conflicto por `user_id`. El `verification_status` almacenado es literalmente `"client_verified_storekit"` — el servidor **no** vuelve a verificar el JWS. IDs de producto permitidos: `lava_security_plus_{monthly,yearly}`.

> La replicación está **Implementada**; **la verificación del JWS del lado del servidor está Planeada** (aún no construida). El JWS firmado se almacena para verificación posterior. Nótese el modelo de niveles en otra parte: el derecho de la app es local (`isPaid`) **sin sincronización con el backend todavía** como fuente de verdad — esta fila es un espejo, no la compuerta.

## 5. Recuperación asistida por passkey (conocimiento cero)

La recuperación de copias de seguridad asistida por passkey es de **conocimiento cero** y completamente del lado del cliente. El material de clave de recuperación se deriva en el dispositivo a partir de la salida de **WebAuthn PRF / hmac-secret** del passkey; el servidor no almacena **ningún** secreto de recuperación, no registra **ningún** passkey, y no emite **ningún** desafío de WebAuthn. No hay ruta de custodia controlada por el servidor.

Las tablas de custodia que usaba un diseño anterior (`backup_passkey_recovery`, `backup_passkey_challenges`) fueron eliminadas antes del lanzamiento, y el Worker no lleva rutas `/v1/backup/*` ni código de WebAuthn/passkey. (Una entrada `@simplewebauthn/server` permanece en el `package.json` del Worker como una dependencia sobrante sin uso.)

El lado del cliente vive en la app de iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` impulsa la creación/aserción de passkey con capacidad PRF, y `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva la ranura a partir de la salida de hmac-secret. La salida de PRF se lee solo durante la aserción y nunca sale del dispositivo. Un proveedor de passkey sin PRF no puede respaldar una ranura de conocimiento cero, por lo que la configuración falla pronto y el usuario recurre a una frase de recuperación. Estado: **Implementado**.

## 6. Worker lavasec-email

Solo recibir y reenviar. Reenvía `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` a una bandeja de entrada de operador verificada, rechaza destinatarios desconocidos y correo de más de 10 MiB, y **no almacena cuerpos de correo electrónico**. Las respuestas automáticas de soporte están codificadas pero bloqueadas tras el correo saliente de pago de Cloudflare (aplazado). Las constantes de enrutamiento viven en `email-service.ts:9` (`ROUTED_RECIPIENTS`); el manejador de entrada es `handleInboundEmail`. Estado: **Implementado** (la ruta de respuesta automática **Planeada**/aplazada).

## 7. Configuración y despliegue

- **La configuración es `wrangler.toml`, que está en gitignore**; `wrangler.toml.example` es la plantilla confirmada. Trata el `wrangler.toml` local como canónico para valores específicos del entorno.
- **Vars** (no secretas, en `[vars]`): la URL de Supabase, el origen público de la API (`https://api.lavasecurity.app`), el TTL de caché del catálogo (por defecto 300s), un tope de tamaño de informe de errores, un interruptor de auditoría de eliminación de cuenta, y un flag de aceleración del runtime de Workers. El triaje interno de informes de errores agrega una clave de cola de triaje interna y un origen de dashboard usado al componer enlaces de triaje.
- **Secretos** (vía `wrangler secret put`): una credencial de rol de servicio de Supabase, una clave de API de admin, y — para la ruta de triaje de informes de errores — una clave de API de seguimiento de incidencias y un webhook opcional de notificación de chat.
- **El despliegue es manual**: `npm run deploy` → `wrangler deploy`. No hay CI para el Worker.
- **Enrutamiento de Cloudflare**: `lavasecurity.app` permanece en Pages; `api.lavasecurity.app` y `*.qa-probe.lavasecurity.app` resuelven a este Worker.
- **Compatibilidad**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` está fijado en vars pero el código del Worker no lo referencia; es un flag de aceleración del runtime de Workers en lugar de una configuración de aplicación.

## 8. Invariantes de privacidad (qué está y qué no está aquí)

Una lista de comprobación rápida para cualquiera que extienda el backend — ninguno de estos puede romperse silenciosamente:

1. **Sin telemetría de DNS/navegación.** No hay tabla para consultas de DNS rutinarias ni telemetría por dominio. El filtrado permanece en el dispositivo.
2. **Sin bytes de blocklists de terceros** en R2 ni Postgres — solo `source_url` + hashes aceptados (§3).
3. **`user_backups` es opaco** — solo texto cifrado + metadatos no secretos; el cliente (no el Worker) lo escribe bajo RLS (§4.3).
4. **Aislamiento de rol de servicio** para `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Todas las rutas de copia de seguridad son de conocimiento cero** — incluida la recuperación asistida por passkey, cuyo material de clave se deriva del lado del cliente a partir de la salida de WebAuthn PRF/hmac-secret. El servidor no almacena ningún secreto de recuperación y no ejecuta WebAuthn (§5).

## Ver también

- [Visión general del sistema](./system-overview.md) — todo el sistema en una página, incluidos los límites de confianza.
- [Cliente de iOS](./ios-client.md) — el lado del dispositivo que consume este backend.
- [Cuentas y copias de seguridad](./accounts-and-backup.md) — auth del lado del cliente, el sobre AES-256-GCM, las ranuras de clave, y las frases de recuperación.
- [Filtrado de DNS y blocklists](./dns-filtering-and-blocklists.md) — el lado del dispositivo del catálogo: descarga directa desde upstream, parseo/normalización, y el presupuesto de reglas de filtro.
- [decisión de cumplimiento GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — por qué el catálogo publica URLs, no bytes.
- **Niveles y monetización** (interno) — el presupuesto de reglas de filtro (Free 500K / Plus 2M) que es la verdadera compuerta Free/Plus.
- **Registro de riesgos de IP** (interno) — la justificación de IP/cumplimiento detrás de source-url-only.
