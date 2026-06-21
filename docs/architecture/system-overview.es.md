---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Visión general del sistema

> **Público:** ingenieros. Esto es la totalidad de Lava Security en una sola página: qué partes existen, cómo se mueven los datos entre ellas y dónde se sitúan los límites de confianza. Los documentos por componente profundizan más; este existe para que puedas tener el sistema completo en la cabeza antes de leerlos.
>
> **Autoridad:** cuando este documento y un plan no coincidan, **manda el código**. El estado refleja la realidad confirmada en el código, no la aspiración del plan. Consulta la [Leyenda de estados](#8-status-legend) al final.

## 1. Resumen del producto en una línea

Lava Security es una app de iOS centrada en la privacidad que filtra DNS **localmente en el dispositivo** a través de un túnel de paquetes de NetworkExtension, bloqueando dominios maliciosos y no deseados para usuarios no técnicos (padres y madres, personas mayores), con protección básica gratuita para siempre y sin necesidad de cuenta.

## 2. La promesa de privacidad (canónica)

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas: el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada opaca por usuario y diagnósticos anonimizados que tú decides enviar.

Todo lo que sigue está al servicio de mantener esa frase como verdadera. La arquitectura es deliberadamente pequeña en el lado del servidor: el dispositivo hace el trabajo y el backend nunca ve una consulta.

## 3. Componentes

### Cliente iOS (tres objetivos ejecutables + código compartido, un App Group `group.com.lavasec`)

| Componente | Bundle / ubicación | Función | Estado |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Carcasa de la app en SwiftUI; punto de entrada, navegación de dos pestañas Guard + Ajustes (Filtro/Actividad son pantallas de detalle de Guard; Actividad de red se movió a Ajustes → Avanzado). | Implementado |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; el motor de filtrado/resolución de DNS en el dispositivo. Sujeto al **límite de memoria de iOS de ~50 MiB por extensión**. | Implementado |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity de WidgetKit (pantalla de bloqueo + Dynamic Island). | Implementado |
| **Shared/** | `Shared/` | Fuentes compartidas entre objetivos: App Group, servicio de comandos, mascota, atributos/intents de Live Activity. | Implementado |

**Controladores del lado de la app (en LavaSecApp):**

- **AppViewModel** — el controlador del lado de la app (objeto omnipresente): gestiona el ciclo de vida de `NETunnelProviderManager`, la persistencia de estado compartido, la mensajería con el proveedor, la reconciliación de Live Activity, la sincronización del catálogo, la copia de seguridad, StoreKit y la autenticación.
- **RootView** — `TabView` de dos pestañas (Guard + Ajustes), con Filtro y Actividad accesibles como pantallas de detalle bajo Guard; controla la incorporación (onboarding), aloja las superposiciones de bloqueo de seguridad / máscara de privacidad.
- **SecurityController** — código de acceso (SHA256 con sal en el Keychain) + biometría + protección por superficie.
- **LavaLiveActivityController** — reconciliador de una sola Activity, sin duplicados y con control por revisión.
- **OnboardingFlowView** — flujo de primera ejecución de varias páginas (6 páginas: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (paquete SwiftPM agnóstico de plataforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — filtro compilado + precedencia de decisión; la forma compacta es el artefacto en disco compatible con mmap que lee el túnel.
- **DNSQueryDispatcher** — precedencia de consultas: bootstrap > pausa > filtro.
- **ResolverOrchestrator** — enrutamiento de transporte, degradación a DNS sin cifrar, conmutación por error por endpoint, respaldo a DNS del dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — ejecutores de transporte cifrado.
- **FeatureLimits** (en `SubscriptionPolicy.swift`) — límites de nivel (fuente de verdad), mediante los miembros estáticos `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — cálculo de protección del dispositivo + aplicación autoritativa del presupuesto tras la unión.
- **BlocklistCatalogSync / BlocklistParser** — obtención del catálogo, descarga directa desde la fuente original, análisis/normalización/eliminación de duplicados local, filtro de dominios protegidos.
- **GuardianMascotAnimation** — grafo de estados de la mascota con 7 estados (renderizado por `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — criptografía + carga útil de la copia de seguridad.
- **SupabaseIDTokenAuth** — autenticación `id_token` por URLRequest en crudo (sin SDK).

### Backend

| Componente | Función | Estado |
|---|---|---|
| **Worker lavasec-api** | Worker de Cloudflare (`api.lavasecurity.app`): lecturas del catálogo, sincronización y publicación de listas de bloqueo por admin/cron, informes de errores anónimos, eliminación de cuentas, replicación de derechos de App Store, sondas de QA. | Implementado |
| **Worker lavasec-email** | Reenviador de solo recepción de Cloudflare Email Routing para `@lavasecurity.app`; rechaza el correo desconocido o de tamaño excesivo. | Implementado |
| **Supabase Postgres** | Cuentas, `user_backups`, metadatos del catálogo, tablas solo de rol de servicio; **RLS en cada tabla pública**. | Implementado |
| **Cloudflare R2** (el bucket de R2 de producción, un bucket de vista previa separado para staging) | Instantáneas del catálogo + el cursor de sincronización round-robin. **Nunca** bytes de listas de bloqueo de terceros; la ruta de subida de adjuntos de informes de errores se eliminó (los objetos heredados solo se borran al eliminar la cuenta). | Implementado |
| **Cloudflare D1** (la base de datos de comentarios de ayuda) | Votos anónimos de comentarios sobre artículos de ayuda, solo de adición. | Implementado |

## 4. Diagrama de flujo de datos

La propiedad más importante: **la ruta del resolutor de DNS cifrado (lado derecho) nunca toca el backend de Lava (parte inferior).** El dispositivo obtiene *metadatos* del catálogo desde el Worker, pero los *bytes* de las listas y el flujo real de consultas van directamente a terceros.

```
                                  YOUR iPHONE
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                                                                             │
 │   ┌──────────────┐   provider messages    ┌───────────────────────────┐    │
 │   │  LavaSecApp  │ ─────────────────────►  │      LavaSecTunnel        │    │
 │   │ (AppViewModel│   (reload-snapshot /    │  (NEPacketTunnelProvider) │    │
 │   │  controller) │    pause / config)      │                           │    │
 │   └──────┬───────┘                         │   DNSQueryDispatcher       │   │
 │          │                                 │   bootstrap > pause >      │   │
 │          │ writes / reads                  │   ┌──────────────────────┐ │   │
 │          ▼                                 │   │  CompactFilterSnapshot│ │   │
 │   ┌──────────────────────────┐  mmap       │   │  guardrail > allow >  │ │   │
 │   │  App Group container      │ ◄──(read)── │   │  block > default-allow│ │   │
 │   │  group.com.lavasec        │            │   └──────────┬───────────┘ │   │
 │   │  • filter-snapshot.compact│            │              │ allowed     │   │
 │   │  • app-configuration.json │            │              ▼             │   │
 │   │  • tunnel-health.json      │           │   ┌──────────────────────┐ │   │
 │   │  • pause/session UserDefs  │           │   │  ResolverOrchestrator│ │   │
 │   └──────────────────────────┘             │   │  DoH3/DoT/DoQ/IP +   │ │   │
 │          ▲                                 │   │  device-DNS fallback │ │   │
 │          │ reads (Live Activity)           │   └──────────┬───────────┘ │   │
 │   ┌──────┴───────┐                         └──────────────│─────────────┘   │
 │   │ LavaSecWidget│                                        │                 │
 │   │ (Dynamic Isl.│                                        │ encrypted DNS   │
 │   │  + lock scr.)│                                        │ (query stream)  │
 │   └──────────────┘                                        │                 │
 └──────────────────────────────────────────────────────────│─────────────────┘
        │ (a) catalog          │ (b) list bytes              │ (c) blocked → NXDOMAIN
        │  metadata            │  (direct from upstream)     │     allowed → forwarded
        ▼                      ▼                             ▼
 ┌──────────────┐   ┌──────────────────────┐    ┌───────────────────────────────┐
 │ lavasec-api  │   │  Upstream blocklists  │   │  Public DNS resolver           │
 │ Worker       │   │  (HaGeZi, OISD,       │   │  (Quad9 / Cloudflare / Google  │
 │ GET /v1/     │   │   Block List Project) │   │   / Mullvad; user-chosen)       │
 │  catalog     │   └──────────────────────┘    └───────────────────────────────┘
 └──────┬───────┘
        │ reads/writes (metadata only)
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  LAVA BACKEND (sees no DNS queries, no browsing history)                   │
 │  • Supabase Postgres: accounts, user_backups (opaque ciphertext), catalog │
 │  • Cloudflare R2: catalog/latest.json, the round-robin cursor             │
 │  • lavasec-email Worker: receive-only @lavasecurity.app forwarding         │
 └──────────────────────────────────────────────────────────────────────────┘
       ▲
       │ (d) optional: encrypted backup envelope (PostgREST, RLS) — ciphertext only
       │     entitlement mirror, anonymous bug reports, account deletion
       └──── from LavaSecApp, only when the user opts in
```

## 5. Flujos de datos

### A. La ruta de DNS (por consulta, todo en el dispositivo) — Implementado

Esta es la ruta caliente y el núcleo de la privacidad. Se ejecuta enteramente dentro de `LavaSecTunnel`; nada de aquí llega a los servidores de Lava.

1. El túnel de paquetes intercepta una consulta de DNS (servidor DNS del túnel `10.255.0.1`).
2. **`DNSQueryDispatcher`** aplica la precedencia de consultas: **bootstrap > pausa > filtro**. El bootstrap primero es un invariante estricto: el propio nombre de host del resolutor se resuelve antes de cualquier filtrado, de modo que el resolutor nunca pueda bloquearse a sí mismo.
3. Si no es bootstrap y no está en pausa, el dominio se evalúa contra **`CompactFilterSnapshot`** (cargado desde el App Group mediante `Data(contentsOf:options:[.mappedIfSafe])`, mmap sin copia). La precedencia de decisión es **protección contra amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto**; los dominios inválidos se bloquean.
4. **Bloqueado** → el túnel responde localmente (sin contacto con el origen). **Permitido** → la consulta se entrega a **`ResolverOrchestrator`**.
5. `ResolverOrchestrator` enruta al transporte configurado — **`DoH3` / `DoT` / `DoQ` / DNS sin cifrar (`IP`)** — con conmutación por error por endpoint detrás de una puerta de retroceso (backoff), degradación a DNS sin cifrar cuando un plan cifrado no tiene endpoints, y **respaldo a DNS del dispositivo** cuando el primario no devuelve respuesta y el plan lo permite.
6. La respuesta del resolutor se devuelve al sistema operativo. El flujo de consultas del usuario va únicamente al **resolutor público elegido por el usuario**, nunca a Lava.

Notas sobre transporte (convenciones literales): `DoH3` (sin barra) se anota **solo cuando se observa realmente una negociación h3** — preferido, nunca prometido. **`DoT`** agrupa hasta 4 NWConnections por endpoint con refresco por inactividad + un reintento con conexión nueva. **`DoQ`** abre una **conexión QUIC nueva por consulta** (sin reutilización); el grupo de 4 vías da concurrencia, no reutilización de handshake — la reutilización de conexión se construyó, se probó en dispositivo y se **revirtió** (aplazada hasta el piso de despliegue de iOS-26). Consulta [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md).

### B. Obtención del catálogo + carga de listas de bloqueo (solo URL de origen) — Implementado

Cómo llegan las reglas de filtrado al dispositivo. Lava es un distribuidor **solo de URL de origen**: publica únicamente la URL original + los hashes aceptados y **nunca almacena, replica, transforma ni sirve bytes de listas de bloqueo de terceros.**

1. El dispositivo obtiene **metadatos** del catálogo desde el Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servido directamente desde R2 (`catalog/latest.json`), dividido en `sources[]` + `guardrails[]`, cada entrada con `source_url` + `accepted_source_hashes`.
2. Para cada fuente habilitada, el dispositivo descarga los **bytes de la lista directamente desde `source_url`** (el origen — HaGeZi, OISD, Block List Project, etc.), **no** desde Lava.
3. El dispositivo calcula SHA256 y solo acepta los bytes cuya suma de verificación está en `accepted_source_hashes`; si no coincide, recurre a la última caché correcta o falla de forma cerrada (`checksumMismatch`).
4. **`BlocklistParser`** analiza/normaliza/elimina duplicados localmente (formatos auto / plain / hosts / adblock / dnsmasq), y luego **`DomainRuleSet.lavaSecProtectedDomains`** elimina los dominios protegidos (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) para que una lista del origen nunca pueda bloquear dominios de Lava/Apple/proveedores de identidad.
5. **`FilterSnapshotPreparationService`** fusiona la unión sin duplicados y ejecuta la **aplicación autoritativa del presupuesto** (primero el límite del dispositivo, luego el del nivel), y a continuación escribe `filter-snapshot.compact` en el App Group.
6. `AppViewModel` envía un mensaje de proveedor `reload-snapshot`; el túnel recarga.

El lado del Worker refleja esto: su sincronización por admin/cron obtiene cada origen, lo hashea/cuenta, escribe `raw_r2_key = null` / `normalized_r2_key = null` y republica solo los metadatos. El modelo del catálogo de listas de bloqueo y la ruta de sincronización del backend se cubren en [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) y [Backend y datos](./backend-and-data.md).

**Modelo de presupuesto (dos capas):**
- **Protección del dispositivo (para todos, nunca un muro de pago):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 reglas** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule` — un objetivo de 32 MB por debajo del límite de NE de ~50 MiB. Las configuraciones que exceden el presupuesto se rechazan de forma determinista en lugar de dejar que el túnel sea expulsado por jetsam.
- **Límite de nivel (`FeatureLimits`):** **Gratis 500K reglas / Plus 2M reglas**, que queda por debajo de la protección del dispositivo. Esto reemplazó el antiguo límite por **número** de listas habilitadas (gratis 3 / pago 10) — los límites por número de listas están obsoletos.

> **Salvedad sobre lo habilitado por defecto (manda el código):** los valores por defecto gratuitos que se distribuyen son **Block List Project Phishing + Scam** (`OnboardingDefaults.lavaRecommendedDefaults`). Se derivan en el dispositivo a partir del indicador `defaultEnabled` de cada fuente curada (`BlocklistSource.recommendedDefaultSourceIDs`), que es la fuente de verdad en el dispositivo y refleja la columna `default_enabled` del catálogo del backend. El texto del plan/catálogo que dice "Block List Basic es el único valor por defecto" es incorrecto para el dispositivo (registrado internamente).

### C. Copia de seguridad (conocimiento cero, opcional) — Implementado

Opcional, sujeta a tener cuenta, y los únicos datos del usuario que llegan al backend — como **texto cifrado opaco**.

1. El usuario inicia sesión opcionalmente (solo Apple o Google; **el correo/contraseña está Descartado**) mediante un `id_token` nativo intercambiado en Supabase Auth (`grant_type=id_token`, nonce con hash). Solo se almacena la sesión de Supabase resultante, local en el dispositivo, en el Keychain.
2. **`BackupConfigurationPayload`** ensambla un texto plano minimizado (IDs de listas de bloqueo habilitadas, dominios permitidos/bloqueados, preferencias del resolutor, preferencias de registro local, libro mayor de LavaGuard). **Excluye** `isPaid`, QA, diagnósticos y las listas de bloqueo completas.
3. **`ZeroKnowledgeBackupEnvelope`** lo sella con **AES-256-GCM** bajo una clave de carga útil aleatoria de 32 bytes; esa clave se envuelve en **ranuras de clave** por secreto mediante **PBKDF2-HMAC-SHA256 (210k iteraciones)** — ranura de secreto del dispositivo, ranura de recuperación asistida, ranura opcional de passkey. La ranura opcional de passkey se envuelve con una salida **WebAuthn PRF / `hmac-secret`** del autenticador (derivada con HKDF); esa salida nunca abandona el cliente, así que la ranura de passkey es genuinamente de conocimiento cero — ningún valor en poder del servidor la desenvuelve (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** sube **solo texto cifrado + metadatos no secretos** a `user_backups` de Supabase directamente mediante PostgREST, acotado por **RLS** por usuario. (No hay ruta de subida del Worker; el Worker toca `user_backups` solo para eliminarlo durante la eliminación de la cuenta).
5. **Recuperación:** restauración fluida en el mismo dispositivo mediante la ranura de secreto del dispositivo; fuera del dispositivo mediante la **frase de recuperación CVCV de 8 palabras** (~105 bits) combinada con una parte de recuperación en poder del servidor mediante SHA256 (dos factores — ninguna mitad por sí sola descifra); o, cuando se selló una ranura de passkey, mediante la salida WebAuthn PRF / `hmac-secret` del lado del cliente (sin ningún valor en poder del servidor). El servidor nunca registra passkeys, emite desafíos WebAuthn ni almacena ningún secreto de recuperación.

Consulta [Cuentas y copia de seguridad](./accounts-and-backup.md).

### D. Plano de control app ↔ extensión — Implementado

Tres procesos (app, túnel, widget) se coordinan a través del App Group `group.com.lavasec`:

- **Control = mensajes de proveedor de NETunnelProviderSession**, **no** notificaciones de Darwin. `AppViewModel` codifica un `LavaSecProviderMessage {kind, operationID}` y llama a `session.sendProviderMessage`; el `handleAppMessage` del túnel hace switch sobre el tipo (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Los archivos compartidos** llevan reglas/configuración/estado (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **los almacenes UserDefaults compartidos** (`ProtectionSessionStore` / `ProtectionPauseStore`) llevan el estado de sesión + pausa.
- **`LavaProtectionCommandService`** ejecuta los comandos de pausa/reanudación de Live Activity / AppIntent bajo un bloqueo de archivo `flock` con deduplicación por revisión y denegación por autenticación requerida; **la reconexión lo omite** para reiniciar el túnel directamente (`startVPNTunnel`).
- **Connect-On-Demand** se habilita solo *después* de que el túnel confirme la conexión, nunca al instalar el perfil — de modo que un perfil de onboarding recién instalado no pueda levantar un túnel imposible de desactivar.

Consulta [Cliente iOS](./ios-client.md).

## 6. Límites de confianza y diseño que preserva la privacidad

| # | Límite | Qué lo cruza | Qué deliberadamente NO lo cruza |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolutor de DNS público** | Las consultas de DNS permitidas (cifradas: DoH3/DoT/DoQ, o IP sin cifrar) van al resolutor elegido por el usuario. | Lava nunca ve el flujo de consultas; no está en absoluto en esta ruta. |
| 2 | **Dispositivo ↔ hosts de listas de bloqueo de origen** | El dispositivo descarga los bytes de la lista directamente desde `source_url`. | Lava nunca hace de proxy, replica ni almacena bytes de listas de bloqueo de terceros. |
| 3 | **Dispositivo ↔ Worker lavasec-api** | Lecturas de **metadatos** del catálogo; informes de errores anónimos opcionales; replicación de derechos; eliminación de cuenta. | Ninguna consulta de DNS, ningún historial de navegación, ninguna configuración en texto plano. |
| 4 | **Dispositivo ↔ Supabase** | **Sobre de copia de seguridad cifrado** opcional (solo texto cifrado, PostgREST bajo RLS); filas de cuenta. | El servidor no puede descifrar la copia de seguridad sin un secreto en poder del usuario. |
| 5 | **App ↔ extensión del túnel** (en el dispositivo) | Mensajes de proveedor + archivos/defaults del App Group. | El túnel falla de forma **cerrada** en el arranque en frío si no hay una instantánea reutilizable. |

**Principios de diseño que preservan la privacidad, fundamentados en lo anterior:**

- **Filtrado local primero.** El motor de decisión y el resolutor se ejecutan dentro de la extensión NE en el dispositivo. El backend es solo de metadatos por construcción — no hay tablas para consultas DNS rutinarias ni telemetría por dominio.
- **No se requiere cuenta para la protección.** La protección básica es gratis para siempre; la autenticación y la copia de seguridad son estrictamente opcionales.
- **Distribución solo de URL de origen.** Desacopla a Lava de los bytes de listas de terceros (cumplimiento de GPL/propiedad intelectual + seguridad ante App Review) y mantiene una protección en CI que impone "sin código de réplica, sin URLs de artefactos de Lava, sin escrituras de bytes en R2".
- **Copia de seguridad de conocimiento cero en reposo.** AES-256-GCM del lado del cliente; el servidor guarda texto cifrado + metadatos del KDF + una parte de recuperación, nunca el texto plano, la frase de recuperación ni la clave desenvuelta. La ranura opcional de passkey se envuelve con una salida WebAuthn PRF / `hmac-secret` del lado del cliente, así que también es de conocimiento cero — ningún valor en poder del servidor la desenvuelve.
- **Secretos locales del dispositivo.** El material de desbloqueo de la copia de seguridad usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — no se sincroniza con iCloud, no está en las copias de seguridad del dispositivo.
- **Aislamiento por rol de servicio.** `bug_reports`, `mirror_events` y `qa_developers` están revocados para los roles anon/authenticated de PostgREST; solo el Worker (rol de servicio) los toca.
- **La seguridad nunca está a la venta.** El pago desbloquea **solo la personalización**. Nunca evita la **protección contra amenazas** no excepcionable, cuya integridad se hace cumplir mediante hashes de origen SHA256 aceptados (no una firma del servidor). La precedencia es coherente en todas partes: **protección contra amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.**

## 7. Documentos por componente

> Estos son los documentos hermanos del conjunto de documentos de arquitectura. El motor de filtrado de DNS y el catálogo de listas de bloqueo se documentan juntos en un solo archivo.

- [Cliente iOS](./ios-client.md) — objetivos, App Group, plano de control, modelo de estado de protección, onboarding, Live Activity.
- [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) — instantánea del filtro, precedencia de decisión, transportes del resolutor (DoH3/DoT/DoQ), presupuesto de memoria, mmap; además del modelo de catálogo solo de URL de origen, obtención del catálogo, análisis/normalización local, filtro de dominios protegidos y presupuesto por nivel.
- [Cuentas y copia de seguridad](./accounts-and-backup.md) — autenticación con Apple/Google, sobre de conocimiento cero, ranuras de clave, frase de recuperación, recuperación con passkey WebAuthn-PRF del lado del cliente.
- [Backend y datos](./backend-and-data.md) — Workers lavasec-api + lavasec-email, esquema de Supabase + RLS, R2/D1, despliegue.

## 8. Leyenda de estados {#8-status-legend}

Este conjunto de documentos usa un único vocabulario de estados. La **carpeta de carril es el estado autoritativo**; un frontmatter obsoleto dentro de un plan es un error de documentación, no un estado. **El código prevalece sobre los planes.**

| Estado | Significado | Carril del plan | Código |
|---|---|---|---|
| **Implementado** | Distribuido y confirmado en el código | `plans/implemented/` | presente y conectado |
| **En progreso** | En construcción activa; parcialmente integrado | `plans/inflight/`, `plans/under_review/` | parcialmente presente |
| **Planificado** | Diseñado, no construido | `plans/backlog/` | ausente |
| **Descartado** | Rechazado o revertido | `plans/dropped/` (o commit revertido) | ausente / eliminado |

**Estado de lo mencionado en esta página:**

- **Implementado:** los cuatro objetivos de iOS + App Group; el plano de control por mensajes de proveedor; el filtrado de DNS en el dispositivo con transportes DoH3/DoT/DoQ/IP; la obtención del catálogo solo de URL de origen + análisis local; el presupuesto de reglas de filtrado (Gratis 500K / Plus 2M) + la protección del dispositivo de ~3,26M; el onboarding de varias páginas; la seguridad por código de acceso/biometría; una única Live Activity sin duplicados; la copia de seguridad de conocimiento cero; la autenticación con Apple + Google; la eliminación de cuenta; la replicación de derechos; las sondas de QA; la capa de tokens `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluyendo el modelo de profundidad `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), los modificadores `.lavaTier(_:)` / `.lavaTierMetadata()` conectados en superficies representativas (p. ej. `SettingsView`) y los tokens `dangerRed` y `LavaSpacing` — fijados por `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **En progreso:** despliegue continuo de la capa de tokens del sistema de diseño en más superficies (el modelo de profundidad `LavaTier` y la capa de tokens se distribuyen — ver más abajo — pero todavía no existe un `LavaColorRole` dedicado, así que los acentos aún se resuelven a colores en crudo).
- **Planificado:** el minijuego huevo de pascua de Lava Guard; expresiones adicionales de la mascota (la mascota tiene exactamente **7** estados); recuperación con passkey totalmente lista para producción en dispositivos físicos (Associated Domains / AASA); re-verificación de JWS de App Store del lado del servidor (`verification_status` es `client_verified_storekit`); un token `LavaColorRole` dedicado para que los acentos del sistema de diseño se resuelvan a través de un rol semántico en lugar de colores en crudo.
- **Descartado:** la reutilización de conexión de DoQ (conexiones nuevas por consulta); el inicio de sesión con correo/contraseña (solo Apple + Google); el diseño de réplica de GPL en R2 en crudo (sustituido por el de solo URL de origen).
