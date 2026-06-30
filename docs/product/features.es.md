---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Catálogo de funciones

> Audiencia: PM / ingeniería. Este catálogo cubre únicamente el conjunto de funciones **actual e implementado**. Todo lo diseñado pero no construido vive en la hoja de ruta privada, no aquí.

Lava Security es una app de iOS centrada en la privacidad que filtra DNS **localmente en el dispositivo** a través de un túnel de paquetes NetworkExtension, bloqueando dominios maliciosos y no deseados para usuarios no técnicos (padres, personas mayores). La protección esencial es gratuita para siempre y no requiere cuenta.

La promesa de privacidad detrás de cada función a continuación:

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas — el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú elijas enviar.

## Cómo leer este catálogo

- **Free** — disponible para todos, sin cuenta, sin compra.
- **Plus** — desbloqueado por Lava Security Plus, el único nivel de pago opcional. Plus desbloquea **solo la personalización**; nunca limita la seguridad básica y nunca permite que un usuario de pago eluda la barrera de protección frente a amenazas.
- Cada fila está **Implementada** salvo que se indique lo contrario en línea. Leyenda de estado: **Implementada** = lanzada y confirmada en el código; **Planeada** = diseñada, no construida; **Descartada** = rechazada o revertida. Los elementos Planeados/Descartados se documentan en la hoja de ruta privada, no aquí.

Los topes de nivel que sirven como fuente de verdad viven en `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, con alias `.plus`). La **barrera** del derecho a Plus es una bandera local (`isPaid`) — la fuente de verdad. El backend **refleja** los derechos de App Store (`POST /v1/account/entitlements/app-store-sync` inserta/actualiza una fila `entitlements`), pero esa fila es un reflejo, no la barrera; todavía no hay ninguna sincronización de backend que controle el acceso.

---

## 1. Protección y VPN

El producto central: un túnel de paquetes local solo para DNS y el modelo de estado sereno que lo rodea.

| Función | Nivel | Notas |
|---|---|---|
| **Túnel de paquetes local solo para DNS** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercepta DNS y evalúa cada dominio en el dispositivo. Ningún tráfico de navegación se enruta a través de Lava. Dirección del túnel `10.255.0.2`, servidor DNS `10.255.0.1`. |
| **Precedencia de la decisión de filtrado** | Free | `bloqueo por barrera de amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto`; los dominios no válidos se bloquean. (`FilterSnapshot.decision()`.) |
| **Precedencia de consultas (bootstrap primero)** | Free | `resolver-bootstrap > temporary-pause > filter` — el propio nombre de host del resolver nunca se bloquea. (`DNSQueryDispatcher`.) |
| **Arranque en frío con cierre seguro** | Free | Un túnel en frío sin instantánea reutilizable instala un `FailClosedRuntimeSnapshot` que bloquea todo el tráfico en lugar de dejar pasar DNS sin filtrar. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` mantiene la protección activa / la reinicia automáticamente — habilitado **solo después** de una conexión confirmada, nunca al instalar el perfil, y neutralizado durante un onboarding incompleto para que una instalación nueva no pueda levantar un túnel imposible de desactivar. |
| **Pausa temporal (configurable 1–30 min, por defecto 5) + reanudar** | Free | Pausar/reanudar pasan por `LavaProtectionCommandService` bajo un bloqueo de archivo flock con deduplicación por revisión. |
| **Pausa que requiere autenticación** | Free | Barrera opcional por superficie (`SecurityProtectedSurface.protectionPause`): la pausa requiere autenticación local del dispositivo; el servicio de comandos rechaza una pausa no autenticada y la Live Activity oculta los botones de pausa. |
| **Reconectar** | Free | Reinicia el túnel directamente (omite la canalización de pausa del servicio de comandos). |
| **Modelo de estado Soft Shield Guardian** | Free | 7 estados de expresión — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 severidades de conectividad se condensan en 4 caras; se renderizan de forma idéntica en la app, en el onboarding y en la Live Activity. |
| **Evaluación de conectividad** | Free | 6 severidades (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) determinan la cara del guardián y el texto de estado. |
| **Optimización de rendimiento** | Free | Activación con caché primero, fusión de consultas en curso, obtención en paralelo acotada y agrupación de oscilaciones (activación en caliente medida en ~112 ms en iPhone 15 Pro según el trabajo de aceleración modular). |

> **Barrera del dispositivo (para todos, nunca un muro de pago):** se aplica un tope estricto de `~3.26M-rule` (objetivo de 32 MB residentes bajo el techo de memoria de iOS de `~50 MiB` por extensión) para todos los usuarios por encima de cualquier nivel (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Las configuraciones que exceden el presupuesto se rechazan de forma determinista (`exceedsDeviceMemoryBudget`) en lugar de dejar que el túnel sufra jetsam.

---

## 2. Listas de bloqueo y filtrado

Qué se bloquea, cómo se eligen las listas y el límite entre niveles.

| Función | Nivel | Notas |
|---|---|---|
| **Listas de bloqueo solo por URL de origen** | Free | Lava publica únicamente la URL upstream + los hashes aceptados; el dispositivo obtiene/analiza los **bytes** de la lista por sí mismo. Lava **nunca** almacena, refleja, transforma ni sirve los bytes de listas de bloqueo de terceros. Consulta la [decisión de cumplimiento GPL solo por URL de origen](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catálogo curado (categorizado)** | Gratis de habilitar | Fuentes curadas organizadas en categorías de defensa en profundidad — Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling, Piracy & Torrent — de HaGeZi, The Block List Project, OISD, StevenBlack, AdGuard, 1Hosts y Phishing.Database. El conjunto completo y actual se publica en el [Catálogo de listas de bloqueo](../legal/blocklist-catalog.md); cada plataforma refleja la versión del catálogo con la que se lanzó. |
| **Listas de bloqueo predeterminadas gratis** | Free | Una instalación nueva habilita **Block List Basic** — una lista combinada amplia y permisiva (la fuente marcada con `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). Todo lo demás es opcional. |
| **Análisis / normalización / deduplicación en el dispositivo** | Free | `BlocklistParser` admite auto/plain/hosts/adblock/dnsmasq, descarta comentarios/líneas en blanco/no válidas, deduplica cadenas exactas y limita a 1.000.000 de reglas por lista. Una línea `hosts` con varios hosts ahora emite **todos** los hosts de la línea, no solo el primero (reglas del parser versión 2). |
| **Integridad upstream (TLS + URL curada)** | Free | Los bytes de las listas comunitarias se obtienen por TLS directamente desde el `source_url` upstream curado y se aceptan sujetos a topes de tamaño + formato + número de reglas; los `accepted_source_hashes` del catálogo son **orientativos** (identidad de caché + auditoría), no una barrera estricta — una lista que rota rápido nunca se rechaza por desviarse de un hash fijado. El nivel de **barrera de amenazas** de Lava (curado por Lava, no se puede permitir) permanece estrictamente fijado por hash. |
| **Filtro de dominios protegidos** | Free | Toda fuente analizada se depura de los dominios protegidos de Lava / Apple / proveedores de identidad (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …) para que una lista upstream no pueda romper la app, el túnel ni el inicio de sesión. |
| **Excepciones permitidas (lista de permitidos)** | Free | Lista de permitidos gestionada por el usuario que admite dominios pese a las listas de bloqueo. Tope gratis: 25 dominios permitidos / 25 bloqueados (`FeatureLimits.free`). |
| **Presupuesto de reglas de filtrado (métrica de nivel)** | Free / Plus | La métrica de nivel lanzada es el total de **reglas** de dominio compiladas: **Free 500K / Plus 2M** (`maxFilterRules` en `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Reemplaza el antiguo tope por número de listas. Las configuraciones por encima del nivel muestran `exceedsTierFilterRuleLimit`. |
| **Límites de dominios más altos** | Plus | 1.000 dominios permitidos / 1.000 bloqueados (`FeatureLimits.plus`). |
| **Listas de bloqueo personalizadas** | Plus | `allowsCustomBlocklists`. Las listas personalizadas se obtienen y analizan en el dispositivo, se almacenan en caché localmente y nunca se transmiten a los servidores de Lava. |
| **Reutilización de artefactos en arranque en caliente** | Free | Un manifiesto + huella de identidad permite al túnel reutilizar la instantánea compacta en disco sin recompilar; la reutilización se rechaza (con un motivo que solo expone el nombre del campo, seguro para la privacidad) cuando las entradas cambian. |
| **Smart Save (confirmación solo al debilitar)** | Free | Las ediciones de tu Filtro que solo lo *refuerzan* o son neutrales (añadir una lista de bloqueo o un dominio bloqueado) se aplican directamente; las ediciones que *debilitan* la protección — quitar una lista de bloqueo, quitar un dominio bloqueado o añadir una excepción permitida — pasan primero por una hoja de confirmación de revisión, con un panel de "Ten especial cuidado" cuando se añaden excepciones (`FiltersView.saveChanges()`, `weakensProtection`). |
| **Medidor de presupuesto (selección guardable)** | Free / Plus | El medidor de selección abrevia los recuentos (500K / 1.2M / 2M) y usa un margen de techo flexible de 1.10 (la suma por lista sobrecuenta la unión deduplicada en ~7–10%); un recuento todavía dentro de la tolerancia se ajusta para mostrar, p. ej., "500K de 500K" hasta que supera el techo flexible (`FilterRuleBudget`). |

> La aplicación autoritativa del presupuesto se ejecuta en tiempo de compilación sobre la unión deduplicada (`FilterSnapshotPreparationService`); primero se comprueba el tope del dispositivo, luego el límite del nivel. El medidor de la interfaz en tiempo de selección usa una suma por lista con un margen de techo flexible de 1.10.

---

## 3. DNS cifrado

Transportes del resolver y enrutamiento para las consultas no bloqueadas.

| Función | Nivel | Notas |
|---|---|---|
| **Cinco transportes de resolver** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH basado en URLSession que prefiere HTTP/3. La interfaz anota **`DoH3` (sin barra)**, p. ej. "Quad9 (DoH3)", **solo cuando se observa realmente una negociación h3** — preferido, nunca prometido (`DoHTransport`). |
| **DoT** | Free | `NWConnection`s agrupadas (hasta 4 por endpoint) con renovación por inactividad y un reintento con conexión fresca. |
| **DoQ** (solo personalizado) | Plus | DNS-over-QUIC **no tiene preajuste integrado** — solo es accesible mediante un **resolver `doq://` personalizado**, y el DNS personalizado es Plus. Abre una **conexión QUIC fresca por consulta** (el grupo de 4 carriles da concurrencia, no reutilización de handshake); la reutilización de conexión se difiere a un piso de despliegue de iOS-26. |
| **Resolvers preestablecidos** | Free | Device DNS (por defecto), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — en variantes IP / DoH / DoT donde se ofrecen (`DNSResolverPreset.allPresets`). |
| **Enrutamiento y conmutación por error del resolver** | Free | `ResolverOrchestrator` enruta por transporte, degrada a DNS plano cuando un plan cifrado no tiene endpoints, hace conmutación por error por endpoint con una barrera de retroceso, y por último recurre a device-DNS. |
| **Recurso a device-DNS** | Free | Recurre al resolver de la red actual cuando el resolver seleccionado no está disponible; **activado por defecto**. Se muestra como la severidad `usingDeviceDNSFallback`. |
| **DNS personalizado** | Plus | `allowsCustomDNS` — resolver proporcionado por el usuario (incluido el análisis de DNS-stamp para preajustes personalizados). |

---

## 4. Cuentas y copia de seguridad de conocimiento cero

Inicio de sesión de cuenta opcional y copia de seguridad cifrada de los ajustes. Nada de esto es necesario para usar la protección.

| Función | Nivel | Notas |
|---|---|---|
| **Inicio de sesión de cuenta opcional (Apple + Google)** | Free | Flujo nativo de id_token intercambiado en Supabase Auth (`grant_type=id_token`) con un nonce con hash; solo la sesión de Supabase resultante se almacena localmente en el dispositivo, en el Keychain. El inicio de sesión con correo/contraseña intencionadamente no se ofrece (Descartado). |
| **Copia de seguridad cifrada de conocimiento cero** | Free | Sobre AES-256-GCM del lado del cliente; la clave de carga útil aleatoria se envuelve en ranuras de clave PBKDF2-HMAC-SHA256 (210k iteraciones). Solo el texto cifrado + metadatos no secretos se suben a Supabase `user_backups` (RLS por usuario). El servidor no puede descifrar sin un secreto en poder del usuario. |
| **Carga útil de copia de seguridad minimizada** | Free | Respalda los IDs de listas de bloqueo habilitadas, dominios permitidos/bloqueados, ajustes del resolver, preferencias de registro local, apariencia del guardián, etc. — y excluye explícitamente `isPaid`, banderas de QA, diagnósticos, instantáneas y los bytes completos de las listas de bloqueo. |
| **Ranura de clave con secreto del dispositivo** | Free | Un secreto de dispositivo de 32 bytes en el Keychain solo del dispositivo (`...ThisDeviceOnly`, no sincronizado con iCloud) para una restauración fluida en el mismo dispositivo. |
| **Frase de recuperación + recuperación asistida** | Free | Una frase CVCV de 8 palabras (~105 bits) combinada con una porción de recuperación en poder del servidor mediante SHA256 para desbloquear la ranura de recuperación asistida. Doble factor: ninguna mitad por sí sola descifra. |
| **Ranura de recuperación con passkey** | Free | Ranura opcional protegida por WebAuthn, y de **conocimiento cero**: su clave de desenvoltura se deriva **en el dispositivo** a partir de la salida WebAuthn PRF (`hmac-secret`) del autenticador (HKDF-SHA256). El servidor no registra ninguna passkey, no emite retos, no guarda ningún secreto de recuperación ni expone rutas de passkey — el diseño anterior de custodia en el servidor se descartó. La preparación para producción en dispositivos físicos depende del alojamiento de Associated Domains / AASA (Planeado). |
| **Eliminación de cuenta / derechos sobre los datos** | Free | El endpoint autenticado del Worker elimina copias de seguridad, ajustes, derechos, perfil y archivos adjuntos de informes de errores, y luego el usuario de Supabase Auth; la app cierra la sesión y borra el material de desbloqueo local. |

---

## 5. Widget y Live Activity

Presencia en la pantalla de bloqueo y en la Dynamic Island.

| Función | Nivel | Notas |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): una única `Activity<LavaActivityAttributes>` en la pantalla de bloqueo y en la Dynamic Island (centro expandido / guardián compactLeading / compactTrailing + glifo de estado mínimo). |
| **Visualización de protección de 5 estados** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — cada uno se asigna a una pose del guardián, un SF Symbol y un título. |
| **Botones de acción de la Live Activity** | Free | Pausar por N min (duración configurada, por defecto 5), Reanudar, Reconectar — `LiveActivityIntent`s que se ejecutan en el proceso de la app a través de `LavaProtectionCommandService`. Las variantes de pausa autenticadas requieren autenticación local del dispositivo. |
| **Reconciliación única, deduplicada y limitada por revisión** | Free | `LavaLiveActivityController` mantiene una sola Activity, actualiza solo ante un cambio real de id/contenido y limita las actualizaciones por la revisión de `ProtectionPauseStore`, de modo que los reintentos de intents obsoletos no puedan retroceder el estado. |
| **Interruptor de Live Activities** | Free | Activable por el usuario en Ajustes (`setUsesLiveActivities`), disponible solo en iPhone/iPad. |

---

## 6. Onboarding

Flujo de primera ejecución que instala la configuración de VPN local y establece valores predeterminados sensatos.

| Función | Nivel | Notas |
|---|---|---|
| **Flujo de primera ejecución de varias páginas** | Free | `OnboardingFlowView` — 6 páginas: `lava, guardIntro, features, vpn, notifications, done`. (La instalación del perfil y la solicitud de notificaciones ocurren en el paso adecuado, no al principio.) |
| **Instalación del perfil de VPN local** | Free | Instala la configuración de VPN local durante el onboarding **sin** habilitar Connect-On-Demand, de modo que la protección nunca se activa de forma silenciosa al completar — la superficie de Guard sigue siendo autoritativa. |
| **Solicitud de permiso de notificaciones** | Free | Solicitado dentro del flujo, en el paso de notificaciones. |
| **Valores predeterminados recomendados aplicados** | Free | Resolver Device DNS, recurso a device-DNS activado, registro local activado (recuentos + historial + actividad), Block List Basic habilitada, continuar sin cuenta (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Ajustes

Superficies de configuración, seguridad, diagnóstico y comentarios.

| Función | Nivel | Notas |
|---|---|---|
| **Código de desbloqueo de app + biometría** | Free | `SecurityController`: verificador de código con SHA256 y sal en el Keychain + biometría con `LAContext`, con una superposición de bloqueo de desbloqueo de la app y máscara de privacidad ante cambios de fase de escena. |
| **Protección por superficie** | Free | `SecurityProtectedSurface` controla seis superficies: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Cada una puede requerir de forma independiente autenticación local del dispositivo (p. ej., la pestaña de Ajustes devuelve `.requires(.appSettings)`). |
| **Selector de apariencia de Lava Guard (7 apariencias)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, cada una con un color de glifo de Dynamic Island emparejado. Se elige desde un selector tipo radio en hoja inferior ("Choose your Guard", `LavaGuardLookPickerSheet`); las apariencias aún bloqueadas llevan un glifo de candado y el panel de desbloqueo/mejora vive dentro de la hoja. |
| **Coincidir con el icono de la app** | Free | Icono alternativo opcional de la app emparejado con la apariencia del guardián seleccionada. |
| **Apariencia** | Free | Esquema de color claro/oscuro/del sistema. |
| **Controles de registro solo local** | Free | Interruptores para recuentos de filtrado, historial de dominios (diagnósticos) y actividad de red — todo almacenado en el dispositivo. Los registros de grano fino (historial de dominios + actividad de red) se podan a una ventana de **7 días** (`LocalLogRetention.fineGrainedDays = 7`); los recuentos y el progreso de Lava Guard se conservan más tiempo. |
| **Registros de actividad / dominios (detalle de Guard)** | Free | Diagnósticos dinámicos solo locales, accesibles desde la pestaña de Guard (`GuardDestination.activity`). El resumen es un **flujo** de solicitudes — un total de "solicitudes procesadas" dividido en una barra de volumen Permitido/Bloqueado con "% protegido localmente" (redondeo honesto: una proporción ínfima se lee `<1%`, una proporción casi total se lee `>99%`). Una sección de **Registros de dominios** contiene **Dominios principales** (los más bloqueados y permitidos, ordenados por número de consultas) e **Historial de dominios** (búsquedas y decisiones recientes); las filas de dominios solo aparecen cuando la suscripción al historial está activada. |
| **Filtro (detalle de Guard)** | Free | Pantalla de Filtro única y unificada accesible desde la pestaña de Guard. Un centro de "Mi filtro" abre una pantalla consolidada de **Mi filtro** con dos estantes — **"Lava bloquea estos"** (listas de bloqueo + dominios bloqueados individualmente) y **"Lava deja pasar estos"** (excepciones permitidas) — bajo un único flujo de borrador Editar/Guardar. Un diagrama de flujo "Teléfono → Lava → Internet" encabeza la pestaña, y al abrir Mi filtro se actualiza automáticamente el catálogo. |
| **Actividad de red (Ajustes → Avanzado)** | Free | Flujo de eventos acotado y solo local de transiciones de red/runtime/usuario, compartido mediante App Group (`NetworkActivityLog`). Trasladado de la superficie de Actividad a **Ajustes → Avanzado** (después de "Nerd Stats", `SettingsRoute.networkActivity`), tras la barrera `.activityViewing`, con su propio panel de privacidad ("Se queda en este iPhone", conservado 7 días). |
| **Informe de errores** | Free | Asistente activado por el usuario que envía un paquete anonimizado a `POST /v1/bug-reports`; sin historial de dominios en v1. El paquete también incluye la procedencia de la compilación (`appVersion`/`appBuild`/`sourceRevision`) y contadores de honestidad de conectividad. También accesible mediante agitar para informar (`RageShakeDetector`). |
| **Gestión de la suscripción** | Plus | Para suscriptores activos, la pantalla de Mejora muestra Gestionar suscripción (planes de renovación automática, vía `AppStore.showManageSubscriptions`), Restaurar compra y la fecha de vencimiento del derecho. |
| **Avisos legales + Versión** | Free | Ajustes muestra avisos legales de terceros (consulta [Avisos de terceros](../legal/third-party-notices.md)) y una página de versión/compilación. |

---

## Arquitectura de la app (para orientación)

Tres paquetes comparten un App Group `group.com.lavasec`, junto con una carpeta de fuentes `lavasec-ios: Shared/` compilada en ellos:

- **LavaSecApp** (`com.lavasec.app`) — el contenedor de la app en SwiftUI; en esta compilación la raíz es un `TabView` de dos pestañas (**Guard** + **Settings**), con Filtro y Actividad accesibles como pantallas de detalle bajo la pestaña de Guard (Actividad de red ahora vive bajo Ajustes → Avanzado).
- **LavaSecTunnel** (`.tunnel`) — el motor de filtrado/resolución de DNS en el dispositivo.
- **LavaSecWidget** (`.widget`) — la Live Activity de WidgetKit.
- **Shared/** — fuentes entre objetivos (no es un paquete): App Group, servicio de comandos, mascota, atributos/intents de Live Activity.

El control App ↔ extensión usa **mensajes de proveedor** de `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), no notificaciones de Darwin. Las reglas de filtrado cruzan de app → extensión como archivos de instantánea del App Group (`filter-snapshot.json` / `.compact`).

---

## Documentos relacionados

- Hoja de ruta — las funciones planeadas y descartadas (posicionamiento de precios de Plus/StoreKit, port a Android, protección a nivel de URL, preparación de passkey para Associated-Domain, minijuego de huevo de pascua, lanzamiento de código abierto GPL-3.0, etc.) viven en la hoja de ruta privada, no en este catálogo público.
- [Decisión de cumplimiento GPL solo por URL de origen](../legal/gpl-source-url-only-compliance-decision.md)
- [Exención de los términos de datos de listas de código abierto](../legal/open-source-list-data-terms-carveout.md)
- [Avisos de terceros](../legal/third-party-notices.md)
