---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Visión general del sistema

> **Público:** ingenieros. Esto es Lava Security al completo en una sola página: qué son las partes, cómo se mueven los datos entre ellas y dónde se sitúan los límites de confianza. La documentación de cada componente profundiza más; esta existe para que puedas tener el sistema en la cabeza antes de leerlas.
>
> **Autoridad:** cuando este documento y un plan no coincidan, **manda el código**. El estado refleja la realidad confirmada en el código, no las aspiraciones del plan. Consulta la [Leyenda de estados](#8-status-legend) al final.

## 1. El producto en una frase

Lava Security es una app de iOS que prioriza la privacidad y que filtra el DNS **localmente en el dispositivo** a través de un túnel de paquetes NetworkExtension, bloqueando dominios maliciosos y no deseados para usuarios sin perfil técnico (padres y madres, personas mayores), con la protección básica gratis para siempre y sin necesidad de cuenta.

## 2. La promesa de privacidad (canónica)

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca dirige tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas: el backend guarda únicamente metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.

Todo lo que viene a continuación está al servicio de mantener esa frase cierta. La arquitectura es deliberadamente pequeña en el lado del servidor: el dispositivo hace el trabajo y el backend nunca ve una consulta.

## 3. Componentes

### Cliente de iOS (tres targets ejecutables + código compartido, un App Group `group.com.lavasec`)

| Componente | Bundle / ubicación | Función | Estado |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Carcasa de la app en SwiftUI; punto de entrada, navegación de dos pestañas Guard + Ajustes (Filtros/Actividad son pantallas de detalle de Guard). | Implementado |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; el motor de filtrado/resolución de DNS en el dispositivo. Sujeto al **límite de memoria de ~50 MiB por extensión** de iOS. | Implementado |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity de WidgetKit (pantalla de bloqueo + Dynamic Island). | Implementado |
| **Shared/** | `Shared/` | Fuentes compartidas entre targets: App Group, servicio de comandos, mascota, atributos/intents de Live Activity. | Implementado |

**Controladores del lado de la app (en LavaSecApp):**

- **AppViewModel** — el controlador del lado de la app (objeto omnipresente): gestiona el ciclo de vida de `NETunnelProviderManager`, la persistencia del estado compartido, la mensajería con el provider, la reconciliación de Live Activity, la sincronización del catálogo, la copia de seguridad, StoreKit y la autenticación.
- **RootView** — `TabView` de dos pestañas (Guard + Ajustes), con Filtros y Actividad accesibles como pantallas de detalle dentro de Guard; controla el onboarding y aloja las superposiciones de bloqueo de seguridad y máscara de privacidad.
- **SecurityController** — código de acceso (SHA256 con sal en el Keychain) + biometría + protección por superficie.
- **LavaLiveActivityController** — reconciliador de una única Activity, con deduplicación y control por revisión.
- **OnboardingFlowView** — flujo multipágina de primer uso (6 páginas: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (paquete SwiftPM agnóstico de plataforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — filtro compilado + precedencia de decisiones; la forma compacta es el artefacto en disco apto para mmap que lee el túnel.
- **DNSQueryDispatcher** — precedencia de consultas: bootstrap > pausa > filtro.
- **ResolverOrchestrator** — enrutamiento de transporte, degradación a DNS sin cifrar, conmutación por error por endpoint, recurso al DNS del dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — ejecutores de transporte cifrado.
- **FeatureLimits** (en `SubscriptionPolicy.swift`) — topes por nivel (fuente de verdad), mediante los miembros estáticos `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — cálculo de los márgenes de seguridad del dispositivo + aplicación autoritativa del presupuesto tras la unión.
- **BlocklistCatalogSync / BlocklistParser** — obtención del catálogo, descarga directa del origen, análisis/normalización/deduplicación en local, filtro de dominios protegidos.
- **GuardianMascotAnimation** — grafo de estados de la mascota de 7 estados (renderizado por `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — criptografía y carga útil de la copia de seguridad.
- **SupabaseIDTokenAuth** — autenticación con `id_token` mediante URLRequest en bruto (sin SDK).

### Backend

| Componente | Función | Estado |
|---|---|---|
| **Worker lavasec-api** | Cloudflare Worker (`api.lavasecurity.app`): lecturas del catálogo, sincronización y publicación de listas de bloqueo por admin/cron, informes de errores anónimos, eliminación de cuentas, reflejo de derechos de la App Store, sondeos de QA. | Implementado |
| **Worker lavasec-email** | Reenviador de solo recepción basado en Cloudflare Email Routing para `@lavasecurity.app`; rechaza el correo desconocido o de tamaño excesivo. | Implementado |
| **Supabase Postgres** | Cuentas, `user_backups`, metadatos del catálogo, tablas solo para el rol de servicio; **RLS en cada tabla pública**. | Implementado |
| **Cloudflare R2** (el bucket de R2 de producción, un bucket de vista previa aparte para staging) | Instantáneas del catálogo + el cursor de sincronización round-robin. **Nunca** bytes de listas de bloqueo de terceros; la ruta de subida de adjuntos de los informes de errores se eliminó (los objetos heredados solo se borran al eliminar la cuenta). | Implementado |
| **Cloudflare D1** (la base de datos de comentarios de ayuda) | Votos anónimos de solo añadido sobre los artículos de ayuda. | Implementado |

## 4. Diagrama de flujo de datos

La propiedad más importante de todas: **la ruta del resolutor de DNS cifrado (lado derecho) nunca toca el backend de Lava (parte inferior).** El dispositivo obtiene *metadatos* del catálogo desde el Worker, pero los *bytes* de las listas y el flujo real de consultas van directamente a terceros.

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

### A. La ruta del DNS (por consulta, todo en el dispositivo) — Implementado

Esta es la ruta crítica y el núcleo de la privacidad. Se ejecuta por completo dentro de `LavaSecTunnel`; nada de lo que ocurre aquí llega a los servidores de Lava.

1. El túnel de paquetes intercepta una consulta de DNS (servidor DNS del túnel `10.255.0.1`).
2. **`DNSQueryDispatcher`** aplica la precedencia de consultas: **bootstrap > pausa > filtro**. Que el bootstrap vaya primero es una invariante estricta: el nombre de host del propio resolutor se resuelve antes de cualquier filtrado, de modo que el resolutor nunca pueda bloquearse a sí mismo.
3. Si no es bootstrap y no está en pausa, el dominio se evalúa frente a **`CompactFilterSnapshot`** (cargado desde el App Group mediante `Data(contentsOf:options:[.mappedIfSafe])`, un mmap de copia cero). La precedencia de decisiones es **margen de seguridad de amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto**; los dominios no válidos se bloquean.
4. **Bloqueado** → el túnel responde localmente (sin contactar con ningún origen). **Permitido** → la consulta pasa a **`ResolverOrchestrator`**.
5. `ResolverOrchestrator` enruta hacia el transporte configurado — **`DoH3` / `DoT` / `DoQ` / DNS sin cifrar (`IP`)** — con conmutación por error por endpoint tras una puerta de espera, degradación a DNS sin cifrar cuando un plan cifrado no tiene endpoints, y **recurso al DNS del dispositivo** cuando el principal no devuelve respuesta y el plan lo permite.
6. La respuesta del resolutor se devuelve al sistema operativo. El flujo de consultas del usuario va únicamente al **resolutor público elegido por el usuario**, nunca a Lava.

Notas sobre el transporte (convenciones literales): `DoH3` (sin barra) se anota **solo cuando realmente se observa una negociación h3** — preferida, nunca prometida. **`DoT`** mantiene un pool de hasta 4 NWConnections por endpoint con renovación por inactividad + un reintento con conexión nueva. **`DoQ`** abre una **conexión QUIC nueva por consulta** (sin reutilización); el pool de 4 carriles aporta concurrencia, no reutilización del handshake — la reutilización de conexiones se construyó, se probó en dispositivo y se **revirtió** (aplazada hasta que el suelo de despliegue sea iOS 26). Consulta [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md).

### B. Obtención del catálogo + carga de listas de bloqueo (solo URL de origen) — Implementado

Cómo llegan las reglas de filtrado al dispositivo. Lava es un distribuidor de **solo URL de origen**: publica únicamente la URL del origen + los hashes aceptados y **nunca almacena, refleja, transforma ni sirve bytes de listas de bloqueo de terceros.**

1. El dispositivo obtiene los **metadatos** del catálogo desde el Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servido directamente desde R2 (`catalog/latest.json`), dividido en `sources[]` + `guardrails[]`, donde cada entrada lleva `source_url` + `accepted_source_hashes`.
2. Para cada origen activado, el dispositivo descarga los **bytes de la lista directamente desde `source_url`** (el origen — HaGeZi, OISD, Block List Project, etc.), **no** desde Lava.
3. El dispositivo calcula el SHA256 y solo acepta los bytes cuya suma de comprobación esté en `accepted_source_hashes`; si no coincide, recurre a la última caché válida o falla de forma cerrada (`checksumMismatch`).
4. **`BlocklistParser`** analiza/normaliza/deduplica en local (formatos auto / plain / hosts / adblock / dnsmasq) y luego **`DomainRuleSet.lavaSecProtectedDomains`** retira los dominios protegidos (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) para que una lista de origen nunca pueda bloquear los dominios de Lava/Apple/proveedor de identidad.
5. **`FilterSnapshotPreparationService`** combina la unión deduplicada y ejecuta la **aplicación autoritativa del presupuesto** (primero el tope del dispositivo, luego el nivel) y, a continuación, escribe `filter-snapshot.compact` en el App Group.
6. `AppViewModel` envía un mensaje de provider `reload-snapshot`; el túnel recarga.

El lado del Worker refleja esto: su sincronización por admin/cron obtiene cada origen, lo hashea/cuenta, escribe `raw_r2_key = null` / `normalized_r2_key = null` y vuelve a publicar solo los metadatos. El modelo del catálogo de listas de bloqueo y la ruta de sincronización del backend se cubren en [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) y [Backend y datos](./backend-and-data.md).

**Modelo de presupuesto (dos capas):**
- **Margen de seguridad del dispositivo (para todos, nunca un muro de pago):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 reglas** = `((32.0 − 4.0) MB × 1.048.576) / 9.0 B/regla` — un objetivo de 32 MB por debajo del límite de NE de ~50 MiB. Las configuraciones que exceden el presupuesto se rechazan de forma determinista en lugar de dejar que el túnel sea descartado por falta de memoria (jetsam).
- **Tope por nivel (`FeatureLimits`):** **500 K reglas en Gratis / 2 M reglas en Plus**, que queda por debajo del margen de seguridad del dispositivo. Esto sustituyó al antiguo tope por **número** de listas activadas (3 en gratis / 10 en pago) — los topes por número de listas están obsoletos.

> **Salvedad de los valores activados por defecto (manda el código):** los valores por defecto gratuitos que se publican son **Block List Project Phishing + Scam** (`OnboardingDefaults.lavaRecommendedDefaults`). Se derivan en el dispositivo a partir del indicador `defaultEnabled` de cada origen curado (`BlocklistSource.recommendedDefaultSourceIDs`), que es la fuente de verdad en el dispositivo y refleja la columna `default_enabled` del catálogo del backend. El texto del plan/catálogo que dice "Block List Basic es el único valor por defecto" es incorrecto para el dispositivo (se sigue internamente).

### C. Copia de seguridad (de conocimiento cero, opcional) — Implementado

Opcional, vinculada a una cuenta, y los únicos datos del usuario que llegan al backend, en forma de **texto cifrado opaco**.

1. El usuario inicia sesión de forma opcional (solo Apple o Google; **el correo/contraseña está Descartado**) mediante un `id_token` nativo intercambiado en Supabase Auth (`grant_type=id_token`, nonce hasheado). Solo se guarda la sesión de Supabase resultante, en local en el dispositivo, dentro del Keychain.
2. **`BackupConfigurationPayload`** ensambla un texto en claro minimizado (IDs de listas de bloqueo activadas, dominios permitidos/bloqueados, preferencias del resolutor, preferencias del registro local, libro mayor de LavaGuard). **Excluye** `isPaid`, QA, diagnósticos y las listas de bloqueo completas.
3. **`ZeroKnowledgeBackupEnvelope`** lo sella con **AES-256-GCM** bajo una clave de carga útil aleatoria de 32 bytes; esa clave se envuelve en **ranuras de clave** por secreto mediante **PBKDF2-HMAC-SHA256 (210k iteraciones)** — ranura de secreto del dispositivo, ranura de recuperación asistida, ranura opcional de passkey. La ranura opcional de passkey se envuelve con una salida de **WebAuthn PRF / `hmac-secret`** del autenticador (derivada con HKDF); esa salida nunca abandona el cliente, por lo que la ranura de passkey es genuinamente de conocimiento cero: ningún valor en poder del servidor la desenvuelve (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. **`BackupSyncService`** sube **solo el texto cifrado + metadatos no secretos** a `user_backups` de Supabase directamente vía PostgREST, acotado por **RLS** por usuario. (No hay ruta de subida del Worker; el Worker solo toca `user_backups` para eliminarla durante la baja de la cuenta.)
5. **Recuperación:** restauración fluida en el mismo dispositivo mediante la ranura de secreto del dispositivo; fuera del dispositivo, mediante la **frase de recuperación CVCV de 8 palabras** (~105 bits) combinada con una porción de recuperación en poder del servidor vía SHA256 (dos factores: ninguna mitad descifra por sí sola); o, cuando se selló una ranura de passkey, mediante la salida de WebAuthn PRF / `hmac-secret` del lado del cliente (sin ningún valor en poder del servidor). El servidor nunca registra passkeys, ni emite desafíos de WebAuthn, ni almacena ningún secreto de recuperación.

Consulta [Cuentas y copia de seguridad](./accounts-and-backup.md).

### D. Plano de control app ↔ extensión — Implementado

Tres procesos (app, túnel, widget) se coordinan a través del App Group `group.com.lavasec`:

- **Control = mensajes de provider de NETunnelProviderSession**, **no** notificaciones de Darwin. `AppViewModel` codifica un `LavaSecProviderMessage {kind, operationID}` y llama a `session.sendProviderMessage`; el `handleAppMessage` del túnel hace switch sobre el tipo (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Los archivos compartidos** transportan reglas/configuración/estado (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **los almacenes compartidos de UserDefaults** (`ProtectionSessionStore` / `ProtectionPauseStore`) transportan el estado de sesión y de pausa.
- **`LavaProtectionCommandService`** ejecuta los comandos de pausa/reanudación de Live Activity / AppIntent bajo un bloqueo de archivo `flock` con deduplicación por revisión y denegación cuando se requiere autenticación; **la reconexión lo elude** para reiniciar el túnel directamente (`startVPNTunnel`).
- **Connect-On-Demand** se activa solo *después* de que el túnel confirme la conexión, nunca al instalar el perfil — de modo que un perfil de onboarding recién instalado no pueda levantar un túnel imposible de desactivar.

Consulta [Cliente de iOS](./ios-client.md).

## 6. Límites de confianza y diseño que preserva la privacidad

| # | Límite | Qué lo cruza | Qué deliberadamente NO |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolutor de DNS público** | Las consultas de DNS permitidas (cifradas: DoH3/DoT/DoQ, o IP sin cifrar) van al resolutor elegido por el usuario. | Lava nunca ve el flujo de consultas; no está en esta ruta en absoluto. |
| 2 | **Dispositivo ↔ hosts de listas de bloqueo de origen** | El dispositivo descarga los bytes de la lista directamente desde `source_url`. | Lava nunca actúa de proxy, ni refleja, ni almacena bytes de listas de bloqueo de terceros. |
| 3 | **Dispositivo ↔ Worker lavasec-api** | Lecturas de **metadatos** del catálogo; informes de errores anónimos opcionales; reflejo de derechos; baja de la cuenta. | Sin consultas de DNS, sin historial de navegación, sin ajustes en texto claro. |
| 4 | **Dispositivo ↔ Supabase** | **Sobre de copia de seguridad cifrado** opcional (solo texto cifrado, PostgREST bajo RLS); filas de la cuenta. | El servidor no puede descifrar la copia de seguridad sin un secreto en poder del usuario. |
| 5 | **App ↔ extensión del túnel** (en el dispositivo) | Mensajes de provider + archivos/defaults del App Group. | El túnel falla de forma **cerrada** en un arranque en frío sin una instantánea reutilizable. |

**Principios de diseño que preservan la privacidad, fundamentados en lo anterior:**

- **Filtrado local primero.** El motor de decisiones y el resolutor se ejecutan dentro de la extensión NE en el dispositivo. El backend es de solo metadatos por construcción — no hay tablas para las consultas de DNS habituales ni para telemetría por dominio.
- **No se requiere cuenta para la protección.** La protección básica es gratis para siempre; la autenticación y la copia de seguridad son estrictamente opcionales.
- **Distribución de solo URL de origen.** Desacopla a Lava de los bytes de las listas de terceros (cumplimiento de GPL/propiedad intelectual + seguridad ante App Review) y mantiene un margen de seguridad de CI que aplica la regla "sin código de réplica, sin URLs de artefactos de Lava, sin escrituras de bytes en R2".
- **Copia de seguridad de conocimiento cero en reposo.** AES-256-GCM del lado del cliente; el servidor guarda el texto cifrado + los metadatos del KDF + una porción de recuperación, nunca el texto en claro, ni la frase de recuperación, ni la clave desenvuelta. La ranura opcional de passkey se envuelve con una salida de WebAuthn PRF / `hmac-secret` del lado del cliente, así que también es de conocimiento cero: ningún valor en poder del servidor la desenvuelve.
- **Secretos en local en el dispositivo.** El material para desbloquear la copia de seguridad usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — no se sincroniza con iCloud, ni aparece en las copias de seguridad del dispositivo.
- **Aislamiento del rol de servicio.** `bug_reports`, `mirror_events` y `qa_developers` están revocados para los roles anon/authenticated de PostgREST; solo el Worker (rol de servicio) los toca.
- **La seguridad nunca está a la venta.** El pago desbloquea **únicamente la personalización**. Nunca elude el **margen de seguridad de amenazas** no negociable, cuya integridad se garantiza mediante los hashes SHA256 de origen aceptados (no una firma del servidor). La precedencia es coherente en todas partes: **margen de seguridad de amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.**

## 7. Documentación por componente

> Estos son los documentos hermanos del conjunto de documentación de arquitectura. El motor de filtrado de DNS y el catálogo de listas de bloqueo se documentan juntos en un mismo archivo.

- [Cliente de iOS](./ios-client.md) — targets, App Group, plano de control, modelo del estado de protección, onboarding, Live Activity.
- [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) — instantánea del filtro, precedencia de decisiones, transportes del resolutor (DoH3/DoT/DoQ), presupuesto de memoria, mmap; además del modelo de catálogo de solo URL de origen, la obtención del catálogo, el análisis/normalización en local, el filtro de dominios protegidos y el presupuesto por nivel.
- [Cuentas y copia de seguridad](./accounts-and-backup.md) — autenticación con Apple/Google, sobre de conocimiento cero, ranuras de clave, frase de recuperación, recuperación con passkey por WebAuthn-PRF del lado del cliente.
- [Backend y datos](./backend-and-data.md) — Workers lavasec-api + lavasec-email, esquema de Supabase + RLS, R2/D1, despliegue.

## 8. Leyenda de estados

Este conjunto de documentación usa un único vocabulario de estados. La **carpeta de carril es el estado autoritativo**; un frontmatter desactualizado dentro de un plan es un error de documentación, no un estado. **El código manda sobre los planes.**

| Estado | Significado | Carril del plan | Código |
|---|---|---|---|
| **Implementado** | Publicado y confirmado en el código | `plans/implemented/` | presente y conectado |
| **En progreso** | En construcción activa; parcialmente integrado | `plans/inflight/`, `plans/under_review/` | parcialmente presente |
| **Planificado** | Diseñado, no construido | `plans/backlog/` | ausente |
| **Descartado** | Rechazado o revertido | `plans/dropped/` (o commit revertido) | ausente / eliminado |

**Estado de las cosas mencionadas en esta página:**

- **Implementado:** los cuatro targets de iOS + App Group; el plano de control por mensajes de provider; el filtrado de DNS en el dispositivo con transportes DoH3/DoT/DoQ/IP; la obtención del catálogo de solo URL de origen + análisis en local; el presupuesto de reglas de filtrado (500 K en Gratis / 2 M en Plus) + margen de seguridad del dispositivo de ~3,26 M; el onboarding multipágina; la seguridad por código de acceso/biometría; una única Live Activity deduplicada; la copia de seguridad de conocimiento cero; la autenticación con Apple + Google; la baja de la cuenta; el reflejo de derechos; los sondeos de QA; la capa de tokens `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluido el modelo de profundidad `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), los modificadores `.lavaTier(_:)` / `.lavaTierMetadata()` conectados en superficies representativas (p. ej. `SettingsView`), y los tokens `dangerRed` y `LavaSpacing` — fijados por `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **En progreso:** la continuación del despliegue de la capa de tokens del sistema de diseño en más superficies (el modelo de profundidad `LavaTier` y la capa de tokens se publican — ver más abajo — pero todavía no existe un `LavaColorRole` dedicado, así que los acentos aún se resuelven a colores en bruto).
- **Planificado:** el minijuego de huevo de pascua de Lava Guard; expresiones adicionales de la mascota (la mascota tiene exactamente **7** estados); la recuperación con passkey totalmente lista para producción en dispositivos físicos (Associated Domains / AASA); la reverificación de JWS de la App Store del lado del servidor (`verification_status` es `client_verified_storekit`); un token `LavaColorRole` dedicado para que los acentos del sistema de diseño se resuelvan mediante un rol semántico en lugar de colores en bruto.
- **Descartado:** la reutilización de conexiones de DoQ (conexiones nuevas por consulta); el inicio de sesión con correo/contraseña (solo Apple + Google); el diseño de réplica GPL en R2 en bruto (sustituido por solo URL de origen).
