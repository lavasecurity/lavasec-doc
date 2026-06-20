---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Catálogo de funciones

> Público: PM / ingeniería. Este catálogo cubre únicamente el conjunto de funciones **actual e implementado**. Cualquier cosa diseñada pero no construida vive en la hoja de ruta privada, no aquí.

Lava Security es una app de iOS que prioriza la privacidad y filtra el DNS **localmente en el dispositivo** a través de un túnel de paquetes de NetworkExtension, bloqueando dominios maliciosos y no deseados para usuarios no técnicos (padres y madres, personas mayores), con la protección básica gratuita para siempre y sin necesidad de cuenta.

La promesa de privacidad que respalda cada una de las funciones siguientes:

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca encamina tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas. El backend solo guarda metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.

## Cómo leer este catálogo

- **Free** — disponible para todo el mundo, sin cuenta y sin compra.
- **Plus** — se desbloquea con Lava Security Plus, el único nivel de pago opcional. Plus desbloquea **solo personalización**; nunca limita la seguridad básica y nunca permite que un usuario de pago eluda la barrera de protección frente a amenazas.
- Cada fila está **Implementada** salvo que se indique lo contrario en línea. Leyenda de estados: **Implementada** = lanzada y confirmada en el código; **Planificada** = diseñada, no construida; **Descartada** = rechazada o revertida. Los elementos Planificados/Descartados están documentados en la hoja de ruta privada, no aquí.

Los límites máximos de cada nivel, como fuente de verdad, viven en `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, con el alias `.plus`). El **control** del derecho a Plus es una marca local (`isPaid`), la fuente de verdad. El backend **refleja** los derechos de la App Store (`POST /v1/account/entitlements/app-store-sync` inserta o actualiza una fila `entitlements`), pero esa fila es un reflejo, no el control; todavía no hay ninguna sincronización con el backend que gobierne el acceso.

---

## 1. Protección y VPN

El producto principal: un túnel de paquetes solo de DNS y local, y el modelo de estados tranquilo que lo rodea.

| Función | Nivel | Notas |
|---|---|---|
| **Túnel de paquetes solo de DNS y local** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercepta el DNS y evalúa cada dominio en el dispositivo. Ningún tráfico de navegación se encamina a través de Lava. Dirección del túnel `10.255.0.2`, servidor DNS `10.255.0.1`. |
| **Precedencia de las decisiones de filtrado** | Free | `barrera frente a amenazas (bloqueo) > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto`; los dominios no válidos se bloquean. (`FilterSnapshot.decision()`.) |
| **Precedencia de consultas (arranque primero)** | Free | `resolver-bootstrap > temporary-pause > filter`: el propio nombre de host del resolver nunca se bloquea. (`DNSQueryDispatcher`.) |
| **Arranque en frío con cierre seguro** | Free | Un túnel en frío sin una instantánea reutilizable instala un `FailClosedRuntimeSnapshot` que bloquea todo el tráfico en lugar de dejar pasar DNS sin filtrar. |
| **Conectar bajo demanda** | Free | `NEOnDemandRuleConnect` mantiene activa la protección / la reinicia automáticamente; se habilita **solo después** de una conexión confirmada, nunca al instalar el perfil, y se neutraliza durante una configuración inicial incompleta, de modo que una instalación nueva no pueda levantar un túnel imposible de desactivar. |
| **Pausa temporal (5 / 10 min) + reanudar** | Free | La pausa y la reanudación pasan por `LavaProtectionCommandService` con un bloqueo de archivo flock y deduplicación por revisión. |
| **Pausa con autenticación requerida** | Free | Control opcional por superficie (`SecurityProtectedSurface.protectionPause`): la pausa requiere autenticación local del dispositivo; el servicio de comandos rechaza una pausa sin autenticar y la Live Activity oculta los botones de pausa. |
| **Reconectar** | Free | Reinicia el túnel directamente (omite el flujo de pausa del servicio de comandos). |
| **Modelo de estados de Soft Shield Guardian** | Free | 7 estados de expresión: `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 niveles de gravedad de conectividad se reducen a 4 caras; se representan de forma idéntica en la app, en la configuración inicial y en la Live Activity. |
| **Evaluación de la conectividad** | Free | 6 niveles de gravedad (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) determinan la cara del guardián y el texto de estado. |
| **Optimización del rendimiento** | Free | Activación priorizando la caché, fusión de consultas en curso, descarga en paralelo limitada y fusión de fluctuaciones (activación en caliente medida en ~112 ms en un iPhone 15 Pro según el trabajo de aceleración modular). |

> **Barrera del dispositivo (para todo el mundo, nunca un muro de pago):** se aplica un límite máximo estricto de `~3,26 M de reglas` (objetivo de 32 MB residentes bajo el límite de memoria por extensión de iOS de `~50 MiB`) para todos los usuarios, por encima de cualquier nivel (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Las configuraciones que superan el presupuesto se rechazan de forma determinista (`exceedsDeviceMemoryBudget`) en lugar de dejar que el túnel sea cerrado por el sistema (jetsam). |

---

## 2. Listas de bloqueo y filtrado

Qué se bloquea, cómo se eligen las listas y dónde está el límite entre niveles.

| Función | Nivel | Notas |
|---|---|---|
| **Listas de bloqueo solo por URL de origen** | Free | Lava publica únicamente la URL de origen + los hashes aceptados; el dispositivo descarga y procesa los **bytes** de la lista por sí mismo. Lava **nunca** almacena, replica, transforma ni sirve los bytes de listas de bloqueo de terceros. Consulta la [decisión de cumplimiento de GPL con solo la URL de origen](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catálogo curado (10 fuentes)** | Free para activar | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **Listas de bloqueo por defecto en Free** | Free | Una instalación nueva activa **Block List Project Phishing + Scam** (las dos fuentes marcadas con `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **Procesado / normalización / deduplicación en el dispositivo** | Free | `BlocklistParser` admite auto/plain/hosts/adblock/dnsmasq, descarta comentarios/líneas en blanco/no válidas, deduplica cadenas exactas y limita a 1 000 000 de reglas por lista. |
| **Validación de bytes de origen** | Free | A los bytes descargados se les calcula el SHA-256 y solo se aceptan si la suma de comprobación está en el `accepted_source_hashes` del catálogo; ante una discrepancia, Lava recurre a la última caché válida o cierra de forma segura. |
| **Filtro de dominios protegidos** | Free | A cada fuente procesada se le retiran los dominios protegidos de Lava / Apple / proveedores de identidad (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …) para que una lista externa no pueda romper la app, el túnel ni el inicio de sesión. |
| **Excepciones permitidas (lista de permitidos)** | Free | Lista de permitidos gestionada por el usuario que deja pasar dominios a pesar de las listas de bloqueo. Límite en Free: 10 dominios permitidos / 10 bloqueados (`FeatureLimits.free`). |
| **Presupuesto de reglas de filtrado (métrica de nivel)** | Free / Plus | La métrica de nivel que se aplica es el total de **reglas** de dominio compiladas: **Free 500 K / Plus 2 M** (`maxFilterRules` en `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Sustituye al antiguo límite por número de listas. Las configuraciones que superan el nivel muestran `exceedsTierFilterRuleLimit`. |
| **Límites de dominios más altos** | Plus | 500 dominios permitidos / 500 bloqueados (`FeatureLimits.plus`). |
| **Listas de bloqueo personalizadas** | Plus | `allowsCustomBlocklists`. Las listas personalizadas se descargan y procesan en el dispositivo, se guardan en caché localmente y nunca pasan por los servidores de Lava. |
| **Reutilización de artefactos en el arranque en caliente** | Free | Un manifiesto + una huella de identidad permiten al túnel reutilizar la instantánea compacta del disco sin recompilar; la reutilización se rechaza (con un motivo respetuoso con la privacidad, que solo indica el nombre del campo) cuando cambian las entradas. |

> El control autorizado del presupuesto se ejecuta en tiempo de compilación sobre la unión deduplicada (`FilterSnapshotPreparationService`); primero se comprueba el límite del dispositivo y luego el límite del nivel. El medidor de la interfaz en el momento de la selección usa una suma por lista con un margen flexible de 1,10. |

---

## 3. DNS cifrado

Transportes del resolver y enrutamiento para las consultas no bloqueadas.

| Función | Nivel | Notas |
|---|---|---|
| **Cinco transportes de resolver** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH basado en URLSession que prefiere HTTP/3. La interfaz anota **`DoH3` (sin barra)**, p. ej. "Quad9 (DoH3)", **solo cuando realmente se observa una negociación h3**: se prefiere, nunca se promete (`DoHTransport`). |
| **DoT** | Free | `NWConnection`s agrupadas (hasta 4 por extremo) con refresco por inactividad y un reintento con conexión nueva. |
| **DoQ** (solo personalizado) | Plus | DNS-over-QUIC **no tiene un preajuste integrado**: solo es accesible a través de un **resolver `doq://` personalizado**, y el DNS personalizado es Plus. Abre una **conexión QUIC nueva por consulta** (el grupo de 4 vías aporta concurrencia, no reutilización del handshake); la reutilización de conexiones queda aplazada a un nivel mínimo de despliegue de iOS 26. |
| **Resolvers predefinidos** | Free | Device DNS (por defecto), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad, en variantes IP / DoH / DoT donde se ofrezcan (`DNSResolverPreset.allPresets`). |
| **Enrutamiento del resolver y conmutación por error** | Free | `ResolverOrchestrator` enruta según el transporte, pasa a DNS plano cuando un plan cifrado no tiene extremos, hace conmutación por error por extremo con una puerta de retroceso y, después, recurre al DNS del dispositivo. |
| **Recurso al DNS del dispositivo** | Free | Recurre al resolver de la red actual cuando el resolver seleccionado no está disponible; **activado por defecto**. Se muestra como el nivel de gravedad `usingDeviceDNSFallback`. |
| **DNS personalizado** | Plus | `allowsCustomDNS`: resolver indicado por el usuario (incluido el análisis de DNS-stamp para preajustes personalizados). |

---

## 4. Cuentas y copia de seguridad de conocimiento cero

Inicio de sesión opcional con cuenta y copia de seguridad cifrada de los ajustes. Nada de esto es necesario para usar la protección.

| Función | Nivel | Notas |
|---|---|---|
| **Inicio de sesión opcional con cuenta (Apple + Google)** | Free | Flujo nativo con id_token intercambiado en Supabase Auth (`grant_type=id_token`) con un nonce con hash; solo la sesión de Supabase resultante se guarda localmente en el dispositivo, en el Keychain. El inicio de sesión con correo y contraseña no se ofrece de forma intencionada (Descartado). |
| **Copia de seguridad cifrada de conocimiento cero** | Free | Sobre AES-256-GCM del lado del cliente; la clave aleatoria del contenido se envuelve en ranuras de clave PBKDF2-HMAC-SHA256 (210 000 iteraciones). Solo el texto cifrado + metadatos no secretos se suben a `user_backups` de Supabase (RLS por usuario). El servidor no puede descifrar sin un secreto que posee el usuario. |
| **Contenido de copia de seguridad reducido al mínimo** | Free | Hace copia de seguridad de los ID de las listas de bloqueo activadas, los dominios permitidos/bloqueados, los ajustes del resolver, las preferencias de registro local, el aspecto del guardián, etc., y excluye explícitamente `isPaid`, las marcas de QA, los diagnósticos, las instantáneas y los bytes completos de las listas de bloqueo. |
| **Ranura de clave con secreto del dispositivo** | Free | Un secreto de dispositivo de 32 bytes en el Keychain exclusivo del dispositivo (`...ThisDeviceOnly`, no sincronizado con iCloud) para una restauración fluida en el mismo dispositivo. |
| **Frase de recuperación + recuperación asistida** | Free | Una frase CVCV de 8 palabras (~105 bits) combinada con una parte de recuperación que guarda el servidor mediante SHA256 para desbloquear la ranura de recuperación asistida. Doble factor: ninguna mitad descifra por sí sola. |
| **Ranura de recuperación con passkey** | Free | Ranura opcional protegida por WebAuthn y de **conocimiento cero**: su clave de desenvoltura se deriva **en el dispositivo** a partir de la salida de la WebAuthn PRF (`hmac-secret`) del autenticador (HKDF-SHA256). El servidor no registra ninguna passkey, no emite desafíos, no guarda ningún secreto de recuperación y no expone ninguna ruta de passkey; el diseño anterior con custodia en el servidor se descartó. La preparación para producción en dispositivos físicos depende del alojamiento de Associated Domains / AASA (Planificado). |
| **Eliminación de cuenta / derechos sobre los datos** | Free | Un endpoint autenticado del Worker elimina las copias de seguridad, los ajustes, los derechos, el perfil y los adjuntos de los informes de errores, y después el usuario de Supabase Auth; la app cierra la sesión y borra el material de desbloqueo local. |

---

## 5. Widget y Live Activity

Presencia en la pantalla de bloqueo y en la Dynamic Island.

| Función | Nivel | Notas |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): una única `Activity<LavaActivityAttributes>` en la pantalla de bloqueo y en la Dynamic Island (centro expandido / guardián en compactLeading / compactTrailing + glifo de estado mínimo). |
| **Visualización de protección en 5 estados** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable`, cada uno asociado a una pose del guardián, un símbolo SF y un título. |
| **Botones de acción de la Live Activity** | Free | Pausar 5 / 10 min, Reanudar, Reconectar: `LiveActivityIntent`s que se ejecutan en el proceso de la app a través de `LavaProtectionCommandService`. Las variantes de pausa autenticada requieren autenticación local del dispositivo. |
| **Reconciliación única, deduplicada y controlada por revisión** | Free | `LavaLiveActivityController` mantiene una sola Activity, la actualiza solo ante un cambio real de id/contenido y controla las actualizaciones según la revisión de `ProtectionPauseStore`, de modo que los reintentos de intents obsoletos no puedan revertir el estado. |
| **Interruptor de Live Activities** | Free | El usuario puede activarlo o desactivarlo en Ajustes (`setUsesLiveActivities`), disponible solo en iPhone/iPad. |

---

## 6. Configuración inicial

Flujo de primera ejecución que instala la configuración local de la VPN y establece valores por defecto sensatos.

| Función | Nivel | Notas |
|---|---|---|
| **Flujo de primera ejecución con varias páginas** | Free | `OnboardingFlowView`: 6 páginas: `lava, guardIntro, features, vpn, notifications, done`. (La instalación del perfil y la solicitud de notificaciones ocurren en el paso adecuado, no al principio.) |
| **Instalación del perfil local de la VPN** | Free | Instala la configuración local de la VPN durante la configuración inicial **sin** habilitar Conectar bajo demanda, de modo que la protección nunca quede activada de forma automática y silenciosa al finalizar; la superficie de Guard sigue siendo la autoridad. |
| **Solicitud de permiso de notificaciones** | Free | Se solicita dentro del flujo, en el paso de notificaciones. |
| **Valores por defecto recomendados aplicados** | Free | Resolver Device DNS, recurso al DNS del dispositivo activado, registro local activado (recuentos + historial + actividad), Block List Project Phishing + Scam activadas, continuar sin cuenta (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Ajustes

Superficies de configuración, seguridad, diagnóstico y comentarios.

| Función | Nivel | Notas |
|---|---|---|
| **Código de desbloqueo de la app + biometría** | Free | `SecurityController`: verificador de código con SHA256 y salt en el Keychain + biometría con `LAContext`, con una superposición que bloquea el desbloqueo de la app y una máscara de privacidad ante cambios de fase de escena. |
| **Protección por superficie** | Free | `SecurityProtectedSurface` controla seis superficies: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Cada una puede requerir de forma independiente autenticación local del dispositivo (p. ej., la pestaña de Ajustes devuelve `.requires(.appSettings)`). |
| **Selector de aspecto de Lava Guard (7 aspectos)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, cada uno con un color de glifo de Dynamic Island a juego. |
| **Combinar con el icono de la app** | Free | Icono alternativo opcional de la app, a juego con el aspecto del guardián seleccionado. |
| **Apariencia** | Free | Esquema de color claro/oscuro/del sistema. |
| **Controles de registro solo local** | Free | Interruptores para los recuentos de filtrado, el historial de dominios (diagnóstico) y la actividad de red, todos almacenados en el dispositivo. |
| **Informes / Actividad (detalle de Guard)** | Free | Diagnósticos dinámicos solo locales: recuentos de bloqueos/permisos, salud del túnel, dominios principales. Las filas de dominios solo aparecen cuando el historial está activado. Se accede como pantalla de detalle desde la pestaña de Guard (`GuardDestination.activity`). |
| **Filtros (detalle de Guard)** | Free | Pantalla de filtros con vista general primero, con detalle de Dominios bloqueados / Excepciones permitidas y un flujo de borrador por fases ver/editar/confirmar (`GuardDestination.filters`). |
| **Registro de actividad de red y de estado de Lava** | Free | Flujo de eventos solo local y acotado con las transiciones de red/tiempo de ejecución/usuario, compartido mediante App Group (`NetworkActivityLog`). |
| **Informe de errores** | Free | Asistente activado por el usuario que envía un paquete anonimizado a `POST /v1/bug-reports`; sin historial de dominios en la v1. También accesible agitando el dispositivo para informar (`RageShakeDetector`). |
| **Avisos legales + Versión** | Free | Los Ajustes muestran los avisos legales de terceros (consulta [Avisos de terceros](../legal/third-party-notices.md)) y una página de versión/compilación. |

---

## Arquitectura de la app (a modo de orientación)

Tres paquetes comparten un mismo App Group `group.com.lavasec`, junto con una carpeta de fuentes `lavasec-ios: Shared/` que se compila dentro de ellos:

- **LavaSecApp** (`com.lavasec.app`): la estructura de la app en SwiftUI; en esta compilación la raíz es un `TabView` de dos pestañas (**Guard** + **Ajustes**), con Filtros y Actividad accesibles como pantallas de detalle bajo la pestaña de Guard.
- **LavaSecTunnel** (`.tunnel`): el motor de filtrado/resolución de DNS en el dispositivo.
- **LavaSecWidget** (`.widget`): la Live Activity de WidgetKit.
- **Shared/**: fuentes comunes a varios objetivos (no es un paquete): App Group, servicio de comandos, mascota, atributos/intents de la Live Activity.

El control entre la app y la extensión usa **mensajes de proveedor** de `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), no notificaciones de Darwin. Las reglas de filtrado pasan de la app a la extensión como archivos de instantánea del App Group (`filter-snapshot.json` / `.compact`).

---

## Documentos relacionados

- Hoja de ruta: las funciones planificadas y descartadas (posicionamiento de precios/StoreKit de Plus, port a Android, protección a nivel de URL, preparación de los Associated Domain de las passkeys, minijuego de tipo easter egg, publicación de código abierto bajo GPL-3.0, etc.) viven en la hoja de ruta privada, no en este catálogo público.
- [Decisión de cumplimiento de GPL con solo la URL de origen](../legal/gpl-source-url-only-compliance-decision.md)
- [Excepción en los términos de los datos de listas de código abierto](../legal/open-source-list-data-terms-carveout.md)
- [Avisos de terceros](../legal/third-party-notices.md)
