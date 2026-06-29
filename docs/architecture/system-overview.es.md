---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Descripción general del sistema

> **Audiencia:** ingenieros. Esto es la totalidad de Lava Security en una sola página: qué son las partes, cómo se mueven los datos entre ellas y dónde se sitúan los límites de confianza. Los documentos por componente profundizan más; este existe para que puedas tener el sistema en la cabeza antes de leerlos.
>
> **Autoridad:** donde este documento y un plan no coincidan, **el código gana**. El estado refleja la realidad confirmada en el código, no la aspiración del plan. Consulta la [Leyenda de estados](#8-leyenda-de-estados) al final.

## 1. El sistema en una frase

Lava Security es una app de iOS centrada en la privacidad que filtra DNS **localmente en el dispositivo** a través de un túnel de paquetes de NetworkExtension, bloqueando dominios maliciosos y no deseados para usuarios no técnicos (padres, personas mayores), con la protección esencial gratis para siempre y sin necesidad de cuenta.

## 2. La promesa de privacidad (canónica)

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas: el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú elijas enviar.

Todo lo que sigue está al servicio de mantener verdadera esa frase. La arquitectura es deliberadamente pequeña del lado del servidor: el dispositivo hace el trabajo y el backend nunca ve una consulta.

## 3. Componentes

### Cliente iOS (tres objetivos ejecutables + código compartido, un App Group `group.com.lavasec`)

| Componente | Bundle / ubicación | Rol | Estado |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Carcasa de la app en SwiftUI; punto de entrada, navegación de dos pestañas Guard + Ajustes (Filtro/Actividad son pantallas de detalle de Guard; Actividad de red se movió a Ajustes → Avanzado). | Implementado |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; el motor de filtrado/resolución de DNS en el dispositivo. Sujeto al **techo de memoria de ~50 MiB por extensión** de iOS. | Implementado |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity de WidgetKit (pantalla de bloqueo + Dynamic Island). | Implementado |
| **Shared/** | `Shared/` | Fuentes compartidas entre objetivos: App Group, servicio de comandos, mascota, atributos/intents de Live Activity. | Implementado |

**Controladores del lado de la app (en LavaSecApp):**

- **AppViewModel** — el controlador del lado de la app (objeto-dios): posee el ciclo de vida de `NETunnelProviderManager`, la persistencia de estado compartido, la mensajería con el provider, la reconciliación de Live Activity, la sincronización del catálogo, la copia de seguridad, StoreKit y la autenticación.
- **RootView** — `TabView` de dos pestañas (Guard + Ajustes), con Filtro y Actividad accesibles como pantallas de detalle bajo Guard; controla el onboarding, aloja las superposiciones de bloqueo de seguridad / máscara de privacidad.
- **SecurityController** — código de acceso (SHA256 con sal en el Keychain) + biometría + protección por superficie.
- **LavaLiveActivityController** — reconciliador de una sola Activity, deduplicado y con control de revisiones.
- **OnboardingFlowView** — flujo de primer arranque multipágina (6 páginas: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (paquete SwiftPM agnóstico de plataforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — filtro compilado + precedencia de decisión; la forma compacta es el artefacto en disco apto para mmap que lee el túnel.
- **DNSQueryDispatcher** — precedencia de consultas: bootstrap > pausa > filtro.
- **ResolverOrchestrator** — enrutamiento de transporte, degradación a DNS plano, conmutación por error por endpoint, repliegue a DNS del dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — ejecutores de transporte cifrado.
- **FeatureLimits** (en `SubscriptionPolicy.swift`) — topes por nivel (fuente de verdad), mediante los miembros estáticos `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — cálculo de la barrera de protección del dispositivo + aplicación autoritativa del presupuesto tras la unión.
- **BlocklistCatalogSync / BlocklistParser** — obtención del catálogo, descarga directa del upstream, análisis/normalización/deduplicación local, filtro de dominios protegidos.
- **GuardianMascotAnimation** — grafo de estados de la mascota de 7 estados (renderizado por `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — criptografía + carga útil de la copia de seguridad.
- **SupabaseIDTokenAuth** — autenticación `id_token` con URLRequest en bruto (sin SDK).

### Backend

| Componente | Rol | Estado |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker (`api.lavasecurity.app`): lecturas del catálogo, sincronización + publicación de la blocklist por admin/cron, informes de errores anónimos, eliminación de cuenta, reflejo de derechos de App Store, sondas de QA. | Implementado |
| **lavasec-email Worker** | Reenviador de Cloudflare Email Routing de solo recepción para `@lavasecurity.app`; rechaza correo desconocido/sobredimensionado. | Implementado |
| **Supabase Postgres** | Cuentas, `user_backups`, metadatos del catálogo, tablas solo de rol de servicio; **RLS en cada tabla pública**. | Implementado |
| **Cloudflare R2** (el bucket R2 de producción, un bucket de vista previa separado para staging) | Instantáneas del catálogo + el cursor de sincronización round-robin. **Nunca** bytes de blocklists de terceros; la ruta de subida de adjuntos de informes de errores se eliminó (los objetos heredados solo se borran al eliminar la cuenta). | Implementado |
| **Cloudflare D1** (la base de datos de comentarios de ayuda) | Votos anónimos, solo de adición, de comentarios sobre artículos de ayuda. | Implementado |

## 4. Diagrama de flujo de datos

La propiedad más importante de todas: **la ruta del resolutor de DNS cifrado (lado derecho) nunca toca el backend de Lava (abajo).** El dispositivo obtiene *metadatos* del catálogo desde el Worker, pero los *bytes* de las listas y el flujo de consultas real van directamente a terceros.

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

1. El túnel de paquetes intercepta una consulta DNS (servidor DNS del túnel `10.255.0.1`).
2. **`DNSQueryDispatcher`** aplica la precedencia de consultas: **bootstrap > pausa > filtro**. Bootstrap primero es un invariante estricto: el propio nombre de host del resolutor se resuelve antes de cualquier filtrado, de modo que el resolutor nunca pueda bloquearse a sí mismo.
3. Si no es bootstrap y no está en pausa, el dominio se evalúa contra **`CompactFilterSnapshot`** (cargado desde el App Group mediante `Data(contentsOf:options:[.mappedIfSafe])`, mmap de copia cero). La precedencia de decisión es **barrera de amenazas > lista de permitidos local (excepciones permitidas) > blocklist > permitir por defecto**; los dominios inválidos se bloquean.
4. **Bloqueado** → el túnel responde localmente (sin contacto con el upstream). **Permitido** → la consulta se entrega a **`ResolverOrchestrator`**.
5. `ResolverOrchestrator` enruta al transporte configurado — **`DoH3` / `DoT` / `DoQ` / DNS plano (`IP`)** — con conmutación por error por endpoint detrás de una puerta de backoff, degradación a DNS plano cuando un plan cifrado no tiene endpoints, y **repliegue a DNS del dispositivo** cuando el primario no devuelve respuesta y el plan lo permite.
6. La respuesta del resolutor se devuelve al sistema operativo. El flujo de consultas del usuario va únicamente al **resolutor público elegido por el usuario**, nunca a Lava.

Notas sobre el transporte (convenciones literales): `DoH3` (sin barra) se anota **solo cuando se observa realmente una negociación h3** — preferido, nunca prometido. **`DoT`** mantiene un grupo de hasta 4 NWConnections por endpoint con renovación por obsolescencia por inactividad + un reintento con conexión nueva. **`DoQ`** abre una **conexión QUIC nueva por consulta** (sin reutilización); el grupo de 4 vías da concurrencia, no reutilización de handshake — la reutilización de conexión se construyó, se probó en dispositivo y se **revirtió** (aplazada hasta el suelo de despliegue de iOS-26). Consulta [Filtrado de DNS y blocklists](./dns-filtering-and-blocklists.md).

### B. Obtención del catálogo + carga de la blocklist (solo URL de origen) — Implementado

Cómo llegan las reglas de filtrado al dispositivo. Lava es un distribuidor de **solo URL de origen**: publica únicamente la URL del upstream + los hashes aceptados y **nunca almacena, refleja, transforma ni sirve bytes de blocklists de terceros.**

1. El dispositivo obtiene los **metadatos** del catálogo desde el Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servido directamente desde R2 (`catalog/latest.json`), dividido en `sources[]` + `guardrails[]`, donde cada entrada lleva `source_url` + `accepted_source_hashes`.
2. Para cada fuente habilitada, el dispositivo descarga los **bytes de la lista directamente desde `source_url`** (el upstream: HaGeZi, OISD, Block List Project, etc.), **no** desde Lava.
3. El dispositivo analiza localmente los bytes obtenidos bajo topes de tamaño/reglas. Las listas comunitarias se aceptan tal como se sirven sobre TLS — los `accepted_source_hashes` del catálogo son consultivos (identidad de caché + auditoría), no una puerta estricta — de modo que una lista rotada nunca se rechaza por desviarse de un hash fijado. El nivel de barrera de amenazas de Lava se mantiene con hash fijado.
4. **`BlocklistParser`** analiza/normaliza/deduplica localmente (formatos auto / plano / hosts / adblock / dnsmasq), luego **`DomainRuleSet.lavaSecProtectedDomains`** elimina los dominios protegidos (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) para que una lista del upstream nunca pueda bloquear dominios de Lava/Apple/proveedor de identidad.
5. **`FilterSnapshotPreparationService`** fusiona la unión deduplicada y ejecuta la **aplicación autoritativa del presupuesto** (primero el tope del dispositivo, luego el nivel), y luego escribe `filter-snapshot.compact` en el App Group.
6. `AppViewModel` envía un mensaje de provider `reload-snapshot`; el túnel recarga.

El lado del Worker refleja esto: su sincronización por admin/cron obtiene cada upstream, lo hashea/cuenta, escribe `raw_r2_key = null` / `normalized_r2_key = null`, y vuelve a publicar solo los metadatos. El modelo del catálogo de blocklists y la ruta de sincronización del backend se cubren en [Filtrado de DNS y blocklists](./dns-filtering-and-blocklists.md) y [Backend y datos](./backend-and-data.md).

**Modelo de presupuesto (dos capas):**
- **Barrera de protección del dispositivo (para todos, nunca un muro de pago):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 reglas** = `((32.0 − 4.0) MB × 1.048.576) / 9.0 B/rule` — un objetivo de 32 MB bajo el techo de ~50 MiB de NE. Las configuraciones que exceden el presupuesto se rechazan de forma determinista en lugar de dejar que el túnel sufra un jetsam.
- **Tope por nivel (`FeatureLimits`):** **Free 500K reglas / Plus 2M reglas**, que queda por debajo de la barrera de protección del dispositivo. Esto reemplazó el antiguo tope de **recuento** de listas habilitadas (free 3 / paid 10); los topes de recuento de listas son obsoletos.

> **Fuente de verdad de habilitado por defecto:** el valor por defecto gratuito que se distribuye es **Block List Basic** (`OnboardingDefaults.lavaRecommendedDefaults`). Se deriva en el dispositivo a partir del indicador `defaultEnabled` de cada fuente curada (`BlocklistSource.recommendedDefaultSourceIDs`), que refleja la columna `default_enabled` del catálogo del backend generada a partir de la misma especificación canónica del catálogo.

### C. Copia de seguridad (de conocimiento cero, opcional) — Implementado

Opcional, condicionada a cuenta, y los únicos datos de usuario que aterrizan en el backend — como **texto cifrado opaco**.

1. El usuario opcionalmente inicia sesión (solo Apple o Google; **email/contraseña está Descartado**) mediante `id_token` nativo intercambiado en Supabase Auth (`grant_type=id_token`, nonce hasheado). Solo se almacena la sesión de Supabase resultante, local en el dispositivo, en el Keychain.
2. **`BackupConfigurationPayload`** ensambla un texto plano minimizado (IDs de blocklists habilitadas, dominios permitidos/bloqueados, preferencias del resolutor, preferencias de registro local, libro mayor de LavaGuard). **Excluye** `isPaid`, QA, diagnósticos y las blocklists completas.
3. **`ZeroKnowledgeBackupEnvelope`** lo sella con **AES-256-GCM** bajo una clave de carga útil aleatoria de 32 bytes; esa clave se envuelve en **ranuras de clave** por secreto mediante **PBKDF2-HMAC-SHA256 (210k iteraciones)** — ranura de secreto del dispositivo, ranura de recuperación asistida, ranura opcional de clave de acceso. La ranura opcional de clave de acceso se envuelve con una salida **WebAuthn PRF / `hmac-secret`** del autenticador (derivada con HKDF); esa salida nunca abandona el cliente, por lo que la ranura de clave de acceso es genuinamente de conocimiento cero — ningún valor en poder del servidor la desenvuelve (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** sube **solo texto cifrado + metadatos no secretos** a `user_backups` de Supabase directamente mediante PostgREST, delimitado por **RLS** por usuario. (No existe ruta de subida del Worker; el Worker toca `user_backups` solo para eliminarlo durante la eliminación de la cuenta.)
5. **Recuperación:** restauración fluida en el mismo dispositivo mediante la ranura de secreto del dispositivo; fuera del dispositivo mediante la **frase de recuperación CVCV de 8 palabras** (~105 bits) combinada con una porción de recuperación en poder del servidor mediante SHA256 (de dos factores — ninguna mitad por sí sola descifra); o, cuando se selló una ranura de clave de acceso, mediante la salida WebAuthn PRF / `hmac-secret` del lado del cliente (sin involucrar ningún valor en poder del servidor). El servidor nunca registra claves de acceso, emite desafíos WebAuthn ni almacena ningún secreto de recuperación.

Consulta [Cuentas y copia de seguridad](./accounts-and-backup.md).

### D. Plano de control app ↔ extensión — Implementado

Tres procesos (app, túnel, widget) se coordinan a través del App Group `group.com.lavasec`:

- **El control = mensajes de provider de NETunnelProviderSession**, **no** notificaciones de Darwin. `AppViewModel` codifica un `LavaSecProviderMessage {kind, operationID}` y llama a `session.sendProviderMessage`; el `handleAppMessage` del túnel hace switch sobre el kind (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Los archivos compartidos** transportan reglas/config/salud (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **los almacenes de UserDefaults compartidos** (`ProtectionSessionStore` / `ProtectionPauseStore`) transportan el estado de sesión + pausa.
- **`LavaProtectionCommandService`** ejecuta comandos de pausa/reanudación de Live-Activity / AppIntent bajo un bloqueo de archivo `flock` con deduplicación por revisión y denegación cuando se requiere autenticación; **la reconexión lo evita** para reiniciar el túnel directamente (`startVPNTunnel`).
- **Connect-On-Demand** se habilita solo *después* de que el túnel confirme la conexión, nunca en la instalación del perfil — de modo que un perfil de onboarding recién instalado no pueda levantar un túnel imposible de apagar.

Consulta [Cliente iOS](./ios-client.md).

## 6. Límites de confianza y diseño que preserva la privacidad

| # | Límite | Qué lo cruza | Qué deliberadamente NO |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolutor de DNS público** | Las consultas DNS permitidas (cifradas: DoH3/DoT/DoQ, o IP plana) van al resolutor elegido por el usuario. | Lava nunca ve el flujo de consultas; no está en esta ruta en absoluto. |
| 2 | **Dispositivo ↔ hosts de blocklists upstream** | El dispositivo descarga los bytes de la lista directamente desde `source_url`. | Lava nunca hace de proxy, refleja ni almacena bytes de blocklists de terceros. |
| 3 | **Dispositivo ↔ lavasec-api Worker** | Lecturas de **metadatos** del catálogo; informes de errores anónimos opcionales; reflejo de derechos; eliminación de cuenta. | Ni consultas DNS, ni historial de navegación, ni ajustes en texto plano. |
| 4 | **Dispositivo ↔ Supabase** | **Sobre de copia de seguridad cifrado** opcional (solo texto cifrado, PostgREST bajo RLS); filas de cuenta. | El servidor no puede descifrar la copia de seguridad sin un secreto en poder del usuario. |
| 5 | **App ↔ extensión del túnel** (en el dispositivo) | Mensajes de provider + archivos/defaults del App Group. | El túnel falla **cerrado** en el arranque en frío sin una instantánea reutilizable. |

**Principios de diseño que preservan la privacidad, fundamentados en lo anterior:**

- **Filtrado local primero.** El motor de decisión y el resolutor se ejecutan dentro de la extensión NE en el dispositivo. El backend es por construcción solo de metadatos: no hay tablas para consultas DNS rutinarias ni telemetría por dominio.
- **No se requiere cuenta para la protección.** La protección esencial es gratis para siempre; la autenticación y la copia de seguridad son estrictamente opcionales.
- **Distribución de solo URL de origen.** Desacopla a Lava de los bytes de listas de terceros (cumplimiento de GPL/PI + seguridad ante App Review) y mantiene una barrera de CI que impone "sin código de espejo, sin URLs de artefactos de Lava, sin escrituras de bytes en R2."
- **Copia de seguridad de conocimiento cero en reposo.** AES-256-GCM del lado del cliente; el servidor guarda texto cifrado + metadatos de KDF + una porción de recuperación, nunca el texto plano, la frase de recuperación ni la clave desenvuelta. La ranura opcional de clave de acceso se envuelve con una salida WebAuthn PRF / `hmac-secret` del lado del cliente, así que también es de conocimiento cero — ningún valor en poder del servidor la desenvuelve.
- **Secretos locales del dispositivo.** El material de desbloqueo de la copia de seguridad usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — no se sincroniza con iCloud, no está en las copias de seguridad del dispositivo.
- **Aislamiento de rol de servicio.** `bug_reports`, `mirror_events` y `qa_developers` están revocados para los roles anon/authenticated de PostgREST; solo el Worker (rol de servicio) los toca.
- **La seguridad nunca está a la venta.** El pago desbloquea **solo la personalización**. Nunca evita la **barrera de amenazas** no negociable, cuya integridad se impone mediante hashes SHA256 de origen aceptados (no una firma del servidor). La precedencia es consistente en todas partes: **barrera de amenazas > lista de permitidos local (excepciones permitidas) > blocklist > permitir por defecto.**

## 7. Documentos por componente

> Estos son los documentos hermanos del conjunto de documentos de arquitectura. El motor de filtrado de DNS y el catálogo de blocklists están documentados juntos en un solo archivo.

- [Cliente iOS](./ios-client.md) — objetivos, App Group, plano de control, modelo de estado de protección, onboarding, Live Activity.
- [Filtrado de DNS y blocklists](./dns-filtering-and-blocklists.md) — instantánea del filtro, precedencia de decisión, transportes del resolutor (DoH3/DoT/DoQ), presupuesto de memoria, mmap; además del modelo de catálogo de solo URL de origen, obtención del catálogo, análisis/normalización local, filtro de dominios protegidos y presupuesto por nivel.
- [Cuentas y copia de seguridad](./accounts-and-backup.md) — autenticación Apple/Google, sobre de conocimiento cero, ranuras de clave, frase de recuperación, recuperación con clave de acceso WebAuthn-PRF del lado del cliente.
- [Backend y datos](./backend-and-data.md) — Workers lavasec-api + lavasec-email, esquema de Supabase + RLS, R2/D1, despliegue.

## 8. Leyenda de estados

Este conjunto de documentos usa un único vocabulario de estados. La **carpeta del carril es el estado autoritativo**; el frontmatter obsoleto dentro de un plan es un error de documentación, no un estado. **El código anula los planes.**

| Estado | Significado | Carril del plan | Código |
|---|---|---|---|
| **Implementado** | Distribuido y confirmado en el código | `plans/implemented/` | presente y conectado |
| **En progreso** | En construcción activa; parcialmente aterrizado | `plans/inflight/`, `plans/under_review/` | parcialmente presente |
| **Planificado** | Diseñado, no construido | `plans/backlog/` | ausente |
| **Descartado** | Rechazado o revertido | `plans/dropped/` (o commit revertido) | ausente / eliminado |

**Estado de las cosas mencionadas en esta página:**

- **Implementado:** los cuatro objetivos de iOS + App Group; plano de control por mensajes de provider; filtrado de DNS en el dispositivo con transportes DoH3/DoT/DoQ/IP; obtención de catálogo de solo URL de origen + análisis local; presupuesto de reglas de filtrado (Free 500K / Plus 2M) + barrera de protección del dispositivo de ~3,26M; onboarding multipágina; seguridad por código de acceso/biometría; una sola Live Activity deduplicada; copia de seguridad de conocimiento cero; autenticación Apple + Google; eliminación de cuenta; reflejo de derechos; sondas de QA; la capa de tokens `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluido el modelo de profundidad `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), los modificadores `.lavaTier(_:)` / `.lavaTierMetadata()` conectados a superficies representativas (p. ej. `SettingsView`) y los tokens `dangerRed` y `LavaSpacing` — fijados por `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **En progreso:** despliegue continuo de la capa de tokens del sistema de diseño en más superficies (el modelo de profundidad `LavaTier` y la capa de tokens se distribuyen — ver abajo — pero todavía no existe un `LavaColorRole` dedicado, por lo que los acentos aún se resuelven a colores en bruto).
- **Planificado:** el minijuego de huevo de pascua de Lava Guard; expresiones adicionales de la mascota (la mascota tiene exactamente **7** estados); recuperación con clave de acceso totalmente lista para producción en dispositivos físicos (Associated Domains / AASA); reverificación de JWS de App Store del lado del servidor (`verification_status` es `client_verified_storekit`); un token `LavaColorRole` dedicado para que los acentos del sistema de diseño se resuelvan a través de un rol semántico en lugar de colores en bruto.
- **Descartado:** reutilización de conexión DoQ (conexiones nuevas por consulta); inicio de sesión con email/contraseña (solo Apple + Google); el diseño de espejo raw-R2 de GPL (reemplazado por solo URL de origen).
