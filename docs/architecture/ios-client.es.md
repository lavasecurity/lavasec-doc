---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Arquitectura del cliente de iOS

> Audiencia: ingenieros de iOS que trabajan en `lavasec-ios`.

Lava Security es una app de iOS centrada en la privacidad que filtra el DNS de forma local en el dispositivo mediante un túnel de paquetes de NetworkExtension que se ejecuta dentro del propio dispositivo, bloqueando dominios conocidos como riesgosos o no deseados sin enrutar tu navegación a través de los servidores de Lava. Este documento explica cómo está estructurado el cliente de iOS: los targets, cómo la app se comunica con su extensión de túnel, el ciclo de vida del VPN, el modelo de estados del Guardián, la Live Activity y el widget, el flujo de bienvenida y el propietario del estado del lado de la app (`AppViewModel`).

Para ver la imagen completa del sistema (la app, el Worker del catálogo y Supabase), consulta [Resumen del sistema](./system-overview.md).

---

## 1. Targets y responsabilidades

El cliente se distribuye como tres targets ejecutables más una biblioteca central compartida. Los tres targets se unen al mismo **App Group** (`group.com.lavasec`) y enlazan `LavaSecCore`.

| Target | Bundle id | Responsabilidad |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | La app de SwiftUI. Es propietaria de la interfaz, posee el entitlement de NetworkExtension y controla el túnel mediante `NETunnelProviderManager`. `AppViewModel` es la fuente de verdad del ciclo de vida del VPN. |
| **Túnel de paquetes** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | La subclase `PacketTunnelProvider` de `NEPacketTunnelProvider` (también conocida como `LavaSecTunnel`). Analiza los paquetes DNS, extrae el dominio consultado, lo evalúa contra el snapshot compilado mapeado en memoria y reenvía las consultas permitidas hacia el exterior. Limitada por el techo de memoria jetsam de ~50 MiB por proceso. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Un `WidgetBundle` cuyo único miembro es `LavaProtectionLiveActivityWidget`, la presentación de la Live Activity / Isla Dinámica. |

El código compartido vive en dos lugares:

- **`LavaSecCore`** (`Sources/LavaSecCore/`): el núcleo independiente de plataforma: el motor de filtrado, los transportes del resolver, la aritmética de snapshot/presupuesto, los almacenes de protección y el núcleo de `GuardianMascotAnimation`. Según `VPNLifecycleController.swift:3-6`, los tipos de NetworkExtension se mantienen deliberadamente fuera de este módulo para que su lógica de ciclo de vida siga siendo testeable con fakes; el target de la app aporta las conformidades respaldadas por `NetworkExtension`.
- **`Shared/`**: código compilado en más de un target (p. ej. `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

Las interioridades del túnel de paquetes (el análisis de DNS, el snapshot compilado, los transportes cifrados del resolver y el presupuesto de reglas de filtrado) se tratan en profundidad en [Filtrado DNS y listas de bloqueo](./dns-filtering-and-blocklists.md). Este documento se centra en la arquitectura del lado de la app y en la frontera entre la app y la extensión.

---

## 2. IPC app ↔ extensión

La app y la extensión del túnel de paquetes son procesos separados. Se coordinan mediante tres mecanismos, todos anclados en el App Group.

### Contenedor del App Group

`group.com.lavasec` es el contenedor compartido que permite a la app, al túnel y al widget leer y escribir el mismo estado y configuración de `LavaSecCore`. `LavaSecAppGroup` (`Shared/AppGroup.swift`) centraliza cada clave y nombre de archivo compartido para que los procesos nunca puedan divergir en sus constantes de cadena, incluyendo:

- Los artefactos del snapshot compilado (`filter-snapshot.compact`, `filter-snapshot.json`), el `app-configuration.json` serializado, el estado de salud del túnel (`tunnel-health.json`), los diagnósticos y el registro de actividad de red.
- Las claves de `UserDefaults` compartidas para la sesión de protección y el estado de pausa. Estas son alias directos de los almacenes de `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — de modo que la app, el túnel y los intents de la Live Activity comparten un mismo esquema de claves, un mismo contador de revisiones y un mismo mecanismo de deduplicación.
- El directorio de caché del catálogo y el archivo de registro de depuración en el dispositivo.

La URL del contenedor se resuelve mediante `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Mensaje de comando / proveedor (la ruta de control)

La app gobierna el túnel con **`sendProviderMessage`** para todos los comandos. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) obtiene la `NETunnelProviderSession` activa desde el manager en caché y llama a `session.sendProviderMessage(...)`. La carga útil la codifica `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) en un pequeño sobre JSON que transporta un `kind` de mensaje y un `operationID` opcional (usado para el rastreo de latencia de extremo a extremo).

Los tipos de mensaje reconocidos son constantes en `LavaSecAppGroup`:

| Constante de mensaje | Efecto en el túnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Forzar la recarga del snapshot de filtrado compilado. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Releer únicamente el estado de pausa compartido. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Recargar la configuración; solo un cambio de *identidad del resolver* provoca una reconexión visible. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Mantenimiento de diagnósticos/registros. |

Del lado del túnel, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica el sobre y bifurca según `kind`. En particular, `reload-configuration` carga la nueva configuración para que los campos que no son del resolver (interruptores de diagnóstico, estado de pago) surtan efecto, pero solo reinicia el runtime de DNS y vuelve a aplicar la configuración de red del túnel — una reconexión visible — cuando la identidad del resolver realmente cambió (`PacketTunnelProvider.swift:768-792`). Un cambio en un indicador de diagnóstico o en el estado de pago nunca interrumpe la conexión en curso.

Las funciones auxiliares `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` de la app (`AppViewModel.swift:7062`/`7070`) son envoltorios ligeros que envían estos mensajes.

### Por qué se usan mensajes de proveedor para el control app→túnel

**`sendProviderMessage` es la única ruta de control app→túnel — no hay ninguna señal Darwin app→túnel.** Un diseño anterior publicaba una señal Darwin de `CFNotificationCenter` al pausar y la observaba dentro de la extensión, pero nunca se disparaba de forma fiable en el proceso de NetworkExtension y se eliminó. El servicio de comandos ya no publica `CFNotificationCenterPostNotification`, y el túnel ya no añade un `CFNotificationCenterAddObserver` — la ausencia de ambos está verificada por pruebas de introspección de fuente (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` para la publicación del servicio de comandos; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` para el observador del túnel) para evitar su reintroducción. (Las líneas `import Darwin` que permanecen en el servicio de comandos y en el túnel son para primitivas de `flock`/sockets, no para notificaciones.)

Sí sigue existiendo una ruta Darwin en la otra dirección. El túnel envía a la app un aviso de cambio de salud: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) publica `CFNotificationCenterPostNotification` en el canal `com.lavasec.protection.tunnel-health-changed` (el nombre del canal vive en `TunnelHealthSignal.swift`, no en `AppGroup.swift`), y la app lo observa mediante `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), conectado en `AppViewModel` para llamar a `handleTunnelHealthNudge()`. La presencia de este aviso de salud túnel→app está verificada por `LavaLiveActivitySourceTests.swift:1059-1075`.

Para el control app→túnel, la pausa se entrega escribiendo el `ProtectionPauseStore` compartido y siguiéndolo con el mensaje de proveedor `reload-protection-pause` para que el túnel ejecute `refreshProtectionPauseStateOnly`. `AppViewModel.swift:4995-4996` documenta la regla directamente: la app "tampoco depende nunca del observador Darwin del snapshot, usando siempre `sendProviderMessage`". Considera el par formado por el App Group (estado compartido) + `sendProviderMessage` (la señal de activación/control) como la ruta de control app→túnel.

### Servicio de comandos de la Live Activity

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) es el punto de entrada para las acciones de la Isla Dinámica / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`). Los `LiveActivityIntent` de `LavaLiveActivityIntents.swift` se ejecutan en el proceso de la app (que posee el entitlement de NetworkExtension), de modo que:

- **Pausar / reanudar** pasan por un bloqueo de archivo entre procesos (`protection-command.lock`, `flock`) y los `ProtectionPauseStore` / `ProtectionSessionStore` de `LavaSecCore`, que son responsables de generar las revisiones y de la deduplicación de comandos repetidos (el `commandID` propaga el id de operación de quien lo invoca, de modo que un comando reentregado no pueda generar una segunda revisión). El resultado programa una actualización de la Live Activity protegida por revisión.
- **Reconectar** se gestiona directamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): llama a `loadAllFromPreferences` e inicia el primer manager de túnel instalado mediante `startVPNTunnel()` (como `loadAllFromPreferences` ya está acotado a las configuraciones de NE de esta app, ese primer manager es el de Lava — a diferencia de `VPNLifecycleController.matchingManagers()`, no hace una comprobación explícita de identidad). Connect-On-Demand ya está activado, por lo que esto solo fuerza una conexión inmediata; la reconciliación de estado de la app devuelve entonces la Live Activity a `.on` una vez conectado.

---

## 3. Ciclo de vida y control del VPN

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) es la fuente de verdad del ciclo de vida del VPN en la app. Orquesta el encendido/apagado, mantiene en caché el `NETunnelProviderManager` activo y publica el estado hacia SwiftUI.

### Selección del manager y aritmética del ciclo de vida

La lógica reutilizable del ciclo de vida, libre de NetworkExtension, vive en `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). La app aporta conformidades respaldadas por `NETunnelProviderManager` de `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; el controlador se encarga de:

- **Selección y deduplicación** — `matchingManagers()` filtra hasta quedarse con los managers propios de Lava mediante `LavaTunnelConfigurationIdentity.matches(...)`, los ordena por `selectionPriority` (primero el activo, luego el nombre canónico de visualización) y `removeDuplicateManagers(keeping:)` converge en un único superviviente.
- **Esperas de conexión/parada** — `waitForConnect` / `waitForStop` consultan el estado de la conexión en vivo con una tolerancia de `startGraceInterval`, porque justo después de `startVPNTunnel` la conexión puede leer brevemente un estado no pendiente antes de que iOS la haga transitar a `.connecting`.

### Encender / apagar

`enableProtection(...)` (`AppViewModel.swift:5764`) prioriza la caché (**cache-first**): cuando existe un artefacto preparado y confirmado como reutilizable para la configuración actual, el VPN puede activarse de inmediato desde la caché mientras una sincronización del catálogo en curso sigue refrescándose en segundo plano, y `performCatalogSync` reconcilia el túnel en ejecución al completarse. Solo se bloquea en la sincronización cuando no hay nada válido desde lo que arrancar (p. ej. el usuario acaba de cambiar el conjunto de listas activadas, invalidando la identidad del artefacto en caché).

`disableProtection(...)` (`AppViewModel.swift:5972`) desactiva Connect-On-Demand *antes* de detener el túnel para que iOS no lo reconecte de inmediato. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) instala una `NEOnDemandRuleConnect` (coincidencia de interfaz `.any`) y guarda las preferencias — guardar (no solo establecer) es necesario para que iOS respete el cambio.

### Observación del estado (y una advertencia sobre el calor)

`AppViewModel` observa `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) y publica `vpnStatus`/`isVPNConfigurationInstalled`. Es crucial que, cuando ya hay un manager en caché, lea la conexión en vivo del manager en caché en lugar de forzar un refresco con `loadAllFromPreferences`: `loadAllFromPreferences` vuelve a publicar `NEVPNStatusDidChange` por sí mismo, y un refresco forzado dentro del observador producía una tormenta autosostenida — el comentario en el código fuente (`AppViewModel.swift:1046-1048`) registra los ~370 eventos/s medidos y la regresión de calor del 134 % de CPU que provocó. Las propiedades publicadas solo cambian en transiciones reales, de modo que los pulsos inactivos dejan de invalidar SwiftUI.

### Reconciliación on-demand con cierre seguro (fail-closed)

Connect-On-Demand puede activar el túnel **en frío** al iniciar (o después de que iOS lo desmonte por un cambio de red) antes de que la app haya enviado un snapshot. Un túnel en frío sin un snapshot persistido reutilizable se carga con **cierre seguro** (fail-closed) — bloquea todo el tráfico — y no se recupera por sí solo. `AppViewModel` gestiona esto en dos rutas de inicio, ambas condicionadas a que la bienvenida esté completa (`hasCompletedOnboarding`, que refleja el indicador `@AppStorage("hasSeenLavaOnboarding")`):

- **Después de la bienvenida** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) se ejecuta siempre que la protección está activa al iniciar: prepara el snapshot de arranque, persiste el estado compartido y envía `reload-snapshot` para que el túnel recargue sus reglas reales y salga del cierre seguro. El cierre seguro sigue siendo el valor predeterminado seguro; esto simplemente lo reemplaza con prontitud. (Soluciona los filtros mostrados en rojo / el tráfico bloqueado tras reiniciar la app mientras Connect-On-Demand mantiene el túnel activo.)
- **Durante la bienvenida** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) se ejecuta *antes* de cualquier trabajo de red cuando la bienvenida no ha terminado. iOS no elimina de forma fiable un perfil de VPN al borrar la app, por lo que una reinstalación puede heredar una configuración huérfana con on-demand activado que active un túnel en frío con cierre seguro antes de que el usuario haya elegido ninguna lista de bloqueo. Esta ruta **elimina** la configuración (`removeFromPreferences`) en lugar de guardar una modificación sobre ella — `saveToPreferences` volvería a mostrar el aviso del sistema "Add VPN Configurations" sobre un perfil que esta instalación no posee, disparando el diálogo en el arranque de la app antes de que se renderice la hoja de bienvenida. Es una operación sin efecto en una instalación limpia y cuando la configuración heredada ya está inerte.

---

## 4. Guardián / modelo de estados

Hay dos vocabularios de estado relacionados: una *evaluación* de conectividad y un estado de la *mascota* Guardián.

### Evaluación de la conectividad

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) mapea un `TunnelHealthSnapshot` a un `ProtectionConnectivityAssessment` con una de **seis severidades** y **dos acciones**:

- Severidades: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Acciones principales: `turnOff` o `reconnect`.

Esta única evaluación impulsa tanto la superficie del Guardián dentro de la app como (con un mapeo adicional) el estado de la Isla Dinámica, de modo que ambos nunca se contradicen.

### Estados de la mascota Guardián

La mascota Soft Shield Guardian tiene exactamente **siete** estados emocionales — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Cada estado declara sus `allowedNextStates`, de modo que las transiciones están restringidas (p. ej. `grateful` solo regresa a `awake`; `GuardianMascotAnimation.swift:12-29`). Semántica:

- `retrying` = autorreparación tranquila.
- `concerned` = petición de ayuda suave.
- `grateful` = éxito celebratorio (usado en las superficies de bienvenida/ajustes, no en el mapa de conectividad).

`GuardianMascotAnimation` es el núcleo de animación procedural en `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) es el renderizado en SwiftUI y admite los acabados de personalización seleccionados por `GuardianShieldStyle` (nombres de visualización Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, con el mapeo de `displayName` en las líneas 18-35). Algunos valores en bruto difieren de sus nombres de visualización (p. ej. `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"` y `purpleObsidian` se muestra como "Amethyst"), así que persiste el valor en bruto, no la etiqueta.

### Cómo se conectan los dos

El `LavaActivityAttributes.ProtectionState` de la Live Activity (`Shared/LavaActivityAttributes.swift`) puentea la evaluación con un estado de mascota mediante `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). `AppViewModel` elige el estado de protección para la Isla Dinámica a partir de la misma `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): una severidad `networkUnavailable` se convierte en `.networkUnavailable`, `recovering` se convierte en `.reconnecting`, una acción principal `reconnect` se convierte en `.needsReconnect` y, en los demás casos, `.on`.

> Nota: `LavaTier` (el enum de profundidad del sistema de diseño: tranquilo → **Floor** / celebratorio → **Window** / técnico → **Workshop**) se distribuye en la capa del sistema de diseño (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), conectado a superficies representativas — consulta [el sistema de diseño](../design-system/overview.md). Gobierna la profundidad del sistema de diseño, no la ruta del cliente de protección/túnel descrita aquí.

---

## 5. Live Activity y widget

El target del widget renderiza únicamente la Live Activity y la Isla Dinámica. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) expone un único `LavaProtectionLiveActivityWidget`, una `ActivityConfiguration(for: LavaActivityAttributes.self)` con:

- Una vista de pantalla de bloqueo, una región central expandida de la Isla Dinámica y presentaciones compacta/mínima que renderizan `SoftShieldGuardian` más un glifo de estado. Las vistas compacta/de bloqueo recalculan el estado de protección *efectivo* en un `TimelineView` por segundo, de modo que una cuenta atrás de pausa se mantiene en vivo sin necesidad de un push.

`LavaActivityAttributes.ContentState` transporta `protectionState`, una `resumeDate` (para las cuentas atrás de pausa), `pauseRequiresAuthentication` y el `shieldStyle` elegido. La decodificación es tolerante — si falta `shieldStyle`, recurre a `.original` — de modo que las cargas útiles de Live Activity más antiguas siguen funcionando.

Del lado de la app, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) es propietario de la `Activity<LavaActivityAttributes>` en vivo: observa los cambios de autorización de ActivityKit, solo ofrece Live Activities en los idiomas de teléfono/tableta, y `reconcile(...)` inicia/actualiza/finaliza la actividad para que coincida con el estado de protección solicitado. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) es el único embudo que recalcula el estado deseado y llama al controlador. Los botones de la Isla Dinámica despachan `LiveActivityIntent`, que llaman a `LavaProtectionCommandService` tal como se describe en [§2](#2-ipc-app-extension).

---

## 6. Flujo de bienvenida

La bienvenida la presenta `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) y está condicionada por el indicador `@AppStorage("hasSeenLavaOnboarding")` declarado en `RootView` (`RootView.swift:32`). El flujo es una secuencia de `OnboardingPage` (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

La configuración inicial que se distribuye proviene de `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` activa únicamente las fuentes recomendadas y permisivas (Block List Project Phishing + Scam), selecciona **DNS del dispositivo** como resolver — `DNSResolverPreset.device` (id `device-dns`), el propio DNS de la red; los presets cifrados como Google DoH son opcionales y no se promueven como predeterminados — activa el respaldo de DNS del dispositivo y mantiene el registro local activado — con `protectionEnabled: false`, de modo que la protección solo se activa cuando el usuario la elige. `OnboardingDefaultsSummary` da formato a esas elecciones para mostrarlas ("Continuar sin cuenta" es el valor predeterminado de cuenta).

Establecer `hasSeenLavaOnboarding = true` al final es lo que activa `hasCompletedOnboarding`, que a su vez arma la ruta de reconciliación de inicio descrita en [§3](#3-ciclo-de-vida-y-control-del-vpn). Hasta entonces, la ruta de neutralización durante la bienvenida evita que cualquier túnel heredado con cierre seguro bloquee el tráfico.

---

## 7. Estado de la app: `AppViewModel`

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) es el propietario central del estado del lado de la app. Más allá del ciclo de vida del VPN, publica las superficies a las que se enlaza la interfaz, incluyendo:

- **Protección y túnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, y los `vpnMessage`/`vpnMessageIsError` orientados al usuario.
- **Configuración y catálogo** — la `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt` y los recuentos de reglas compiladas (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnósticos** — `DiagnosticsStore` y `NetworkActivityLog` (todo local; consulta la promesa de privacidad más abajo).
- **Cuenta y copia de seguridad** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled` y el estado de ofertas/entitlement de **Lava Security Plus**.
- **Personalización y presentación** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress` y `usesLiveActivities`.

Delega la serialización del ciclo de vida a un `protectionActionOrchestrator` (para que una restauración en segundo plano no se entrelace con un encendido del usuario), mantiene el `tunnelManager` en caché e impulsa todos los cambios de snapshot/configuración/pausa hacia la extensión mediante las funciones auxiliares de mensaje de proveedor de [§2](#2-ipc-app-extension).

> **Encuadre de privacidad.** El filtrado de DNS ocurre de forma local en este dispositivo. Las superficies de diagnósticos y de actividad de red que publica `AppViewModel` se almacenan únicamente en local — Lava nunca recibe tus consultas DNS habituales, tu historial de navegación ni telemetría por dominio. Cualquier copia de seguridad de cuenta opcional es de **conocimiento cero** (cifrada en el dispositivo; Lava solo puede almacenar texto cifrado), incluida la recuperación basada en passkey — su clave se deriva con PRF en el dispositivo, sin ningún secreto guardado en el servidor. Consulta [Resumen del sistema](./system-overview.md) para la frontera con el servidor.

---

## Documentos relacionados

- [Resumen del sistema](./system-overview.md) — todo el sistema en una sola pantalla: la app, el Worker del catálogo y Supabase, además de las fronteras de confianza y la leyenda de estados usada en todo el documento.
- [Filtrado DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) — las interioridades del túnel de paquetes referenciadas aquí solo en la frontera de control: el motor de filtrado compilado, los transportes cifrados del resolver (DoH / DoH3 / DoT / DoQ), el presupuesto de reglas de filtrado, el catálogo de listas de bloqueo y el modelo de redistribución basado solo en la URL de origen.
- [Cuentas y copia de seguridad de conocimiento cero](./accounts-and-backup.md) — los proveedores de inicio de sesión y el sobre de copia de seguridad de conocimiento cero que orquesta `AppViewModel` (incluida la ranura de recuperación por passkey, de conocimiento cero y derivada con PRF).
- [Backend y datos](./backend-and-data.md) — el Worker del catálogo `lavasec-api`, Cloudflare R2 y el esquema/RLS de Supabase que se sitúan al otro lado de la frontera app↔servidor.
- [Sistema de diseño](../design-system/overview.md) — el modelo de profundidad `LavaTier`, los siete estados de la mascota Soft Shield Guardian y los acabados del escudo, y las convenciones de texto/localización que renderiza el cliente.
- [Avisos de terceros](../legal/third-party-notices.md) y [Decisión de cumplimiento de la GPL basada solo en la URL de origen](../legal/gpl-source-url-only-compliance-decision.md) — las restricciones de distribución que sustentan la canalización de catálogo/filtros que consume el cliente.
