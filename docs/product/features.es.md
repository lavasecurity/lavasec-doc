---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Catálogo de funciones {#feature-catalog}

> Público: PM / ingeniería. Este catálogo cubre únicamente el conjunto de funciones **actual e implementado**. Cualquier cosa diseñada pero no construida vive en la hoja de ruta privada, no aquí.

Lava Security es una app de iOS centrada en la privacidad que filtra el DNS **localmente en el dispositivo** a través de un túnel de paquetes de NetworkExtension, bloqueando dominios maliciosos y no deseados para usuarios no técnicos (padres, personas mayores), con la protección principal gratuita para siempre y sin necesidad de cuenta.

La promesa de privacidad detrás de cada función a continuación:

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas — el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.

## Cómo leer este catálogo {#how-to-read-this-catalog}

- **Free** — disponible para todos, sin cuenta, sin compra.
- **Plus** — desbloqueado por Lava Security Plus, el único nivel de pago opcional. Plus desbloquea **solo personalización**; nunca limita la seguridad básica y nunca permite que un usuario de pago eluda la barrera de protección frente a amenazas.
- Cada fila está **Implementada** salvo que se indique lo contrario en línea. Leyenda de estados: **Implementada** = lanzada y confirmada en el código; **Planificada** = diseñada, no construida; **Descartada** = rechazada o revertida. Los elementos Planificados/Descartados se documentan en la hoja de ruta privada, no aquí.

Los topes de nivel que sirven como fuente de verdad viven en `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, con alias `.plus`). La **barrera** de derecho a Plus es un indicador local (`isPaid`) — la fuente de verdad. El backend **refleja** los derechos de la App Store (`POST /v1/account/entitlements/app-store-sync` inserta o actualiza una fila `entitlements`), pero esa fila es un reflejo, no la barrera; todavía no hay ninguna sincronización del backend que controle el acceso.

---

## 1. Protección y VPN {#1-protection-vpn}

El producto principal: un túnel de paquetes local solo para DNS y el modelo de estados calmado a su alrededor.

| Función | Nivel | Notas |
|---|---|---|
| **Túnel de paquetes local solo para DNS** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercepta el DNS y evalúa cada dominio en el dispositivo. Ningún tráfico de navegación se enruta a través de Lava. Dirección del túnel `10.255.0.2`, servidor DNS `10.255.0.1`. |
| **Precedencia de la decisión de filtrado** | Free | `bloqueo de la barrera frente a amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto`; los dominios inválidos se bloquean. (`FilterSnapshot.decision()`.) |
| **Precedencia de consultas (bootstrap primero)** | Free | `resolver-bootstrap > temporary-pause > filter` — el nombre de host del propio resolver nunca se bloquea. (`DNSQueryDispatcher`.) |
| **Arranque en frío con fallo cerrado** | Free | Un túnel en frío sin una instantánea reutilizable instala un `FailClosedRuntimeSnapshot` que bloquea todo el tráfico en lugar de filtrar DNS sin protección. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` mantiene la protección activa / la reinicia automáticamente — se habilita **solo después** de una conexión confirmada, nunca al instalar el perfil, y se neutraliza durante una incorporación incompleta para que una instalación nueva no pueda levantar un túnel que no se pueda desactivar. |
| **Pausa temporal (5 / 10 min) + reanudar** | Free | Pausar/reanudar pasan por `LavaProtectionCommandService` bajo un bloqueo de archivo flock con deduplicación por revisión. |
| **Pausa con autenticación requerida** | Free | Barrera opcional por superficie (`SecurityProtectedSurface.protectionPause`): pausar requiere autenticación local del dispositivo; el servicio de comandos deniega una pausa no autenticada y la Live Activity oculta los botones de pausa. |
| **Reconectar** | Free | Reinicia el túnel directamente (omite el flujo de pausa del servicio de comandos). |
| **Modelo de estados Soft Shield Guardian** | Free | 7 estados de expresión — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 niveles de gravedad de conectividad se reducen a 4 caras; se representan igual en la app, en la incorporación y en la Live Activity. |
| **Evaluación de conectividad** | Free | 6 niveles de gravedad (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) controlan la cara del guardián y el texto de estado. |
| **Endurecimiento del rendimiento** | Free | Encendido con caché primero, fusión de consultas en curso, descarga con paralelismo limitado y fusión de oscilaciones (encendido en caliente medido en ~112 ms en un iPhone 15 Pro según el trabajo de aceleración modular). |

> **Barrera del dispositivo (para todos, nunca un muro de pago):** se aplica un tope fijo de `~3.26M de reglas` (objetivo de 32 MB residentes bajo el límite de memoria de iOS de `~50 MiB` por extensión) para todos los usuarios, por encima de cualquier nivel (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Las configuraciones que exceden el presupuesto se rechazan de forma determinista (`exceedsDeviceMemoryBudget`) en lugar de dejar que el túnel sufra un jetsam.

---

## 2. Listas de bloqueo y filtrado {#2-blocklists-filtering}

Qué se bloquea, cómo se eligen las listas y el límite entre niveles.

| Función | Nivel | Notas |
|---|---|---|
| **Listas de bloqueo solo por URL de origen** | Free | Lava publica únicamente la URL original + los hashes aceptados; el dispositivo descarga/analiza los **bytes** de la lista por sí mismo. Lava **nunca** almacena, refleja, transforma ni sirve bytes de listas de bloqueo de terceros. Consulta [Decisión de cumplimiento de GPL solo por URL de origen](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catálogo curado (10 fuentes)** | Gratis de habilitar | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **Listas de bloqueo por defecto gratuitas** | Free | Una instalación nueva habilita **Block List Project Phishing + Scam** (las dos fuentes marcadas con `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **Análisis / normalización / deduplicación en el dispositivo** | Free | `BlocklistParser` admite auto/plain/hosts/adblock/dnsmasq, descarta comentarios/líneas en blanco/inválidas, deduplica cadenas exactas y limita a 1.000.000 de reglas por lista. Una línea `hosts` con varios hosts ahora emite **todos** los hosts de la línea, no solo el primero (reglas del analizador versión 2). |
| **Validación de bytes originales** | Free | A los bytes descargados se les calcula el SHA-256 y se aceptan solo si la suma de verificación está en `accepted_source_hashes` del catálogo; ante una discrepancia Lava recurre a la última caché correcta o falla en cerrado. |
| **Filtro de dominios protegidos** | Free | A cada fuente analizada se le retiran los dominios protegidos de Lava / Apple / proveedor de identidad (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …) para que una lista externa no pueda romper la app, el túnel ni el inicio de sesión. |
| **Excepciones permitidas (lista de permitidos)** | Free | Lista de permitidos gestionada por el usuario que permite dominios a pesar de las listas de bloqueo. Tope gratuito: 25 dominios permitidos / 25 bloqueados (`FeatureLimits.free`). |
| **Presupuesto de reglas de filtro (métrica de nivel)** | Free / Plus | La métrica de nivel que se distribuye es el total de **reglas** de dominio compiladas: **Free 500K / Plus 2M** (`maxFilterRules` en `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Reemplaza el antiguo tope por número de listas. Las configuraciones por encima del nivel muestran `exceedsTierFilterRuleLimit`. |
| **Límites de dominios más altos** | Plus | 1.000 dominios permitidos / 1.000 bloqueados (`FeatureLimits.plus`). |
| **Listas de bloqueo personalizadas** | Plus | `allowsCustomBlocklists`. Las listas personalizadas se descargan y analizan en el dispositivo, se almacenan localmente en caché y nunca se enrutan a los servidores de Lava. |
| **Reutilización de artefactos de arranque en caliente** | Free | Un manifiesto + huella de identidad permite que el túnel reutilice la instantánea compacta del disco sin recompilar; la reutilización se rechaza (con un motivo seguro para la privacidad, solo el nombre del campo) cuando cambian las entradas. |
| **Smart Save (confirmación solo al debilitar)** | Free | Las ediciones de tu filtro que solo *refuerzan* o son neutrales (añadir una lista de bloqueo o un dominio bloqueado) se aplican directamente; las ediciones que *debilitan* la protección — quitar una lista de bloqueo, quitar un dominio bloqueado o añadir una excepción permitida — pasan primero por una hoja de confirmación de revisión, con un panel "Ten especial cuidado" cuando se añaden excepciones (`FiltersView.saveChanges()`, `weakensProtection`). |
| **Medidor de presupuesto (selección guardable)** | Free / Plus | El medidor de selección abrevia los recuentos (500K / 1.2M / 2M) y usa un margen de techo flexible de 1.10 (la suma por lista sobreestima la unión deduplicada en ~7–10%); un recuento que aún está dentro de la tolerancia se fija para que se lea, por ejemplo, "500K de 500K" hasta que supera el techo flexible (`FilterRuleBudget`). |

> La aplicación autoritativa del presupuesto se ejecuta en tiempo de compilación sobre la unión deduplicada (`FilterSnapshotPreparationService`); primero se comprueba el tope del dispositivo y luego el límite del nivel. El medidor de la interfaz en el momento de la selección usa una suma por lista con un margen de techo flexible de 1.10.

---

## 3. DNS cifrado {#3-encrypted-dns}

Transportes del resolver y enrutamiento de las consultas no bloqueadas.

| Función | Nivel | Notas |
|---|---|---|
| **Cinco transportes de resolver** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH basado en URLSession que prefiere HTTP/3. La interfaz anota **`DoH3` (sin barra)**, por ejemplo "Quad9 (DoH3)", **solo cuando realmente se observa una negociación h3** — preferido, nunca prometido (`DoHTransport`). |
| **DoT** | Free | `NWConnection`s agrupadas (hasta 4 por endpoint) con actualización por inactividad y un reintento de conexión nueva. |
| **DoQ** (solo personalizado) | Plus | DNS-over-QUIC **no tiene ningún preajuste integrado** — solo se alcanza a través de un **resolver `doq://` personalizado**, y el DNS personalizado es Plus. Abre una **conexión QUIC nueva por consulta** (el grupo de 4 vías da concurrencia, no reutilización del handshake); la reutilización de conexiones se aplaza a un piso de despliegue de iOS-26. |
| **Resolvers preestablecidos** | Free | Device DNS (por defecto), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — en variantes IP / DoH / DoT donde se ofrecen (`DNSResolverPreset.allPresets`). |
| **Enrutamiento y conmutación por error del resolver** | Free | `ResolverOrchestrator` enruta por transporte, degrada a DNS plano cuando un plan cifrado no tiene endpoints, hace conmutación por error por endpoint con una barrera de retroceso y luego recurre al device-DNS. |
| **Respaldo de device-DNS** | Free | Recurre al resolver de la red actual cuando el resolver seleccionado no está disponible; **activado por defecto**. Se muestra con el nivel de gravedad `usingDeviceDNSFallback`. |
| **DNS personalizado** | Plus | `allowsCustomDNS` — resolver proporcionado por el usuario (incluido el análisis de DNS-stamp para preajustes personalizados). |

---

## 4. Cuentas y copia de seguridad de conocimiento cero {#4-accounts-zero-knowledge-backup}

Inicio de sesión opcional de cuenta y copia de seguridad cifrada de la configuración. Nada de esto es necesario para usar la protección.

| Función | Nivel | Notas |
|---|---|---|
| **Inicio de sesión opcional de cuenta (Apple + Google)** | Free | Flujo nativo de id_token intercambiado en Supabase Auth (`grant_type=id_token`) con un nonce con hash; solo la sesión de Supabase resultante se almacena localmente en el dispositivo, en el Keychain. El inicio de sesión con correo/contraseña no se ofrece deliberadamente (Descartado). |
| **Copia de seguridad cifrada de conocimiento cero** | Free | Sobre AES-256-GCM del lado del cliente; la clave aleatoria de la carga útil se envuelve en ranuras de clave PBKDF2-HMAC-SHA256 (210k iteraciones). Solo se suben a Supabase `user_backups` (RLS por usuario) el texto cifrado + los metadatos no secretos. El servidor no puede descifrar sin un secreto en poder del usuario. |
| **Carga útil de copia de seguridad minimizada** | Free | Hace copia de seguridad de los IDs de listas de bloqueo habilitadas, los dominios permitidos/bloqueados, la configuración del resolver, las preferencias de registro local, el aspecto del guardián, etc. — y excluye explícitamente `isPaid`, los indicadores de QA, los diagnósticos, las instantáneas y los bytes completos de las listas de bloqueo. |
| **Ranura de clave de secreto del dispositivo** | Free | Un secreto de dispositivo de 32 bytes en el Keychain solo del dispositivo (`...ThisDeviceOnly`, no sincronizado con iCloud) para una restauración fluida en el mismo dispositivo. |
| **Frase de recuperación + recuperación asistida** | Free | Una frase CVCV de 8 palabras (~105 bits) combinada con una porción de recuperación en poder del servidor mediante SHA256 para desbloquear la ranura de recuperación asistida. De dos factores: ninguna mitad por sí sola descifra. |
| **Ranura de recuperación con passkey** | Free | Ranura opcional protegida por WebAuthn, y de **conocimiento cero**: su clave de desenvoltura se deriva **en el dispositivo** a partir de la salida de la PRF de WebAuthn (`hmac-secret`) del autenticador (HKDF-SHA256). El servidor no registra ninguna passkey, no emite desafíos, no guarda ningún secreto de recuperación y no expone rutas de passkey — el diseño anterior de custodia en el servidor se descartó. La preparación para producción en dispositivos físicos depende del alojamiento de Associated Domains / AASA (Planificado). |
| **Eliminación de cuenta / derechos sobre los datos** | Free | Un endpoint del Worker autenticado elimina las copias de seguridad, la configuración, los derechos, el perfil y los adjuntos de informes de errores, y luego el usuario de Supabase Auth; la app cierra la sesión y borra el material de desbloqueo local. |

---

## 5. Widget y Live Activity {#5-widget-live-activity}

Presencia en la pantalla de bloqueo y en la Dynamic Island.

| Función | Nivel | Notas |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): una única `Activity<LavaActivityAttributes>` en la pantalla de bloqueo y en la Dynamic Island (centro expandido / guardián compactLeading / compactTrailing + glifo de estado mínimo). |
| **Visualización de protección de 5 estados** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — cada uno se asigna a una pose del guardián, un símbolo SF y un título. |
| **Botones de acción de la Live Activity** | Free | Pausar 5 / 10 min, Reanudar, Reconectar — `LiveActivityIntent`s que se ejecutan en el proceso de la app a través de `LavaProtectionCommandService`. Las variantes de pausa autenticada requieren autenticación local del dispositivo. |
| **Reconciliación única, deduplicada y controlada por revisión** | Free | `LavaLiveActivityController` mantiene una sola Activity, actualiza solo ante un cambio real de id/contenido y limita las actualizaciones según la revisión de `ProtectionPauseStore` para que los reintentos de intents obsoletos no puedan revertir el estado. |
| **Conmutador de Live Activities** | Free | Activable por el usuario en Ajustes (`setUsesLiveActivities`), disponible solo en iPhone/iPad. |

---

## 6. Incorporación {#6-onboarding}

Flujo de primer uso que instala la configuración local de VPN y establece valores por defecto sensatos.

| Función | Nivel | Notas |
|---|---|---|
| **Flujo de primer uso de varias páginas** | Free | `OnboardingFlowView` — 6 páginas: `lava, guardIntro, features, vpn, notifications, done`. (La instalación del perfil y la solicitud de notificaciones ocurren en el paso correcto, no al principio.) |
| **Instalación del perfil local de VPN** | Free | Instala la configuración local de VPN durante la incorporación **sin** habilitar Connect-On-Demand, para que la protección nunca se active automáticamente y en silencio al finalizar — la superficie Guard sigue siendo la autoritativa. |
| **Solicitud de permiso de notificaciones** | Free | Se solicita dentro del flujo, en el paso de notificaciones. |
| **Valores por defecto recomendados aplicados** | Free | Resolver Device DNS, respaldo de device-DNS activado, registro local activado (recuentos + historial + actividad), Block List Project Phishing + Scam habilitadas, continuar sin cuenta (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Ajustes {#7-settings}

Superficies de configuración, seguridad, diagnósticos y comentarios.

| Función | Nivel | Notas |
|---|---|---|
| **Código de desbloqueo de la app + biometría** | Free | `SecurityController`: verificador de código SHA256 con sal en el Keychain + biometría `LAContext`, con una superposición de bloqueo de desbloqueo de la app y una máscara de privacidad ante cambios de fase de escena. |
| **Protección por superficie** | Free | `SecurityProtectedSurface` controla seis superficies: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Cada una puede requerir de forma independiente autenticación local del dispositivo (por ejemplo, la pestaña Ajustes devuelve `.requires(.appSettings)`). |
| **Selector de aspecto de Lava Guard (7 aspectos)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, cada uno con un color de glifo de Dynamic Island emparejado. Se elige desde un selector tipo radio en hoja inferior ("Elige tu Guard", `LavaGuardLookPickerSheet`); los aspectos aún bloqueados llevan un glifo de candado y el panel de desbloqueo/mejora vive en la hoja. |
| **Coincidir con el icono de la app** | Free | Icono alternativo opcional de la app emparejado con el aspecto del guardián seleccionado. |
| **Apariencia** | Free | Esquema de color claro/oscuro/sistema. |
| **Controles de registro solo local** | Free | Conmutadores para los recuentos de filtrado, el historial de dominios (diagnósticos) y la actividad de red — todo almacenado en el dispositivo. Los registros detallados (historial de dominios + actividad de red) se podan a una ventana de **7 días** (`LocalLogRetention.fineGrainedDays = 7`); los recuentos y el progreso de Lava Guard se conservan más tiempo. |
| **Registros de actividad / dominios (detalle de Guard)** | Free | Diagnósticos dinámicos solo locales, accesibles desde la pestaña Guard (`GuardDestination.activity`). El resumen es un **flujo** de solicitudes — un total de "solicitudes procesadas" dividido en una barra de volumen Permitidas/Bloqueadas con "% protegido localmente" (redondeo honesto: una porción mínima se lee como `<1%`, una porción casi total se lee como `>99%`). Una sección de **Registros de dominios** contiene **Dominios principales** (los más bloqueados y permitidos, ordenados por número de consultas) e **Historial de dominios** (búsquedas y decisiones recientes); las filas de dominios solo aparecen cuando está activada la participación en el historial. |
| **Filtro (detalle de Guard)** | Free | Una única pantalla de filtro unificada accesible desde la pestaña Guard. Un centro "Mi filtro" abre una pantalla consolidada de **Mi filtro** con dos estantes — **"Lava bloquea estos"** (listas de bloqueo + dominios bloqueados individualmente) y **"Lava deja pasar estos"** (excepciones permitidas) — bajo un único flujo de borrador Editar/Guardar. Un diagrama de flujo "Teléfono → Lava → Internet" encabeza la pestaña, y al abrir Mi filtro se actualiza automáticamente el catálogo. |
| **Actividad de red (Ajustes → Avanzado)** | Free | Flujo de eventos solo local y acotado de transiciones de red/tiempo de ejecución/usuario, compartido a través del App Group (`NetworkActivityLog`). Movido de la superficie de Actividad a **Ajustes → Avanzado** (después de "Nerd Stats", `SettingsRoute.networkActivity`), tras la barrera `.activityViewing`, con su propio panel de privacidad ("Se queda en este iPhone", conservado 7 días). |
| **Informe de errores** | Free | Asistente activado por el usuario que envía un paquete anonimizado a `POST /v1/bug-reports`; sin historial de dominios en la v1. El paquete ahora también lleva la procedencia de la compilación (`appVersion`/`appBuild`/`sourceRevision`) y contadores de honestidad de conectividad. También accesible mediante sacudir para informar (`RageShakeDetector`). |
| **Gestión de la suscripción** | Plus | Para los suscriptores activos, la pantalla de Mejora muestra Gestionar suscripción (planes de renovación automática, vía `AppStore.showManageSubscriptions`), Restaurar compra y la fecha de vencimiento del derecho; un desbloqueo de por vida no muestra la fila Gestionar. |
| **Avisos legales + Versión** | Free | Ajustes muestra los avisos legales de terceros (consulta [Avisos de terceros](../legal/third-party-notices.md)) y una página de versión/compilación. |

---

## Arquitectura de la app (para orientarse) {#app-architecture-for-orientation}

Tres paquetes comparten un App Group `group.com.lavasec`, junto con una carpeta de fuentes `lavasec-ios: Shared/` compilada en ellos:

- **LavaSecApp** (`com.lavasec.app`) — shell de la app SwiftUI; en esta compilación la raíz es un `TabView` de dos pestañas (**Guard** + **Settings**), con Filtro y Actividad accesibles como pantallas de detalle bajo la pestaña Guard (Actividad de red ahora vive en Ajustes → Avanzado).
- **LavaSecTunnel** (`.tunnel`) — el motor de filtrado/resolución de DNS en el dispositivo.
- **LavaSecWidget** (`.widget`) — la Live Activity de WidgetKit.
- **Shared/** — fuentes compartidas entre objetivos (no es un paquete): App Group, servicio de comandos, mascota, atributos/intents de Live Activity.

El control App ↔ extensión usa **mensajes de proveedor** de `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), no notificaciones Darwin. Las reglas de filtro cruzan de la app a la extensión como archivos de instantánea del App Group (`filter-snapshot.json` / `.compact`).

---

## Documentos relacionados {#related-docs}

- Hoja de ruta — las funciones planificadas y descartadas (posicionamiento de precios/StoreKit de Plus, port a Android, protección a nivel de URL, preparación de Associated-Domain para passkey, minijuego de huevo de pascua, lanzamiento de código abierto bajo GPL-3.0, etc.) viven en la hoja de ruta privada, no en este catálogo público.
- [Decisión de cumplimiento de GPL solo por URL de origen](../legal/gpl-source-url-only-compliance-decision.md)
- [Excepción de los términos de datos de listas de código abierto](../legal/open-source-list-data-terms-carveout.md)
- [Avisos de terceros](../legal/third-party-notices.md)
