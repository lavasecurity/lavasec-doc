---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Arquitectura del cliente iOS

> Audiencia: ingenieros de iOS que trabajan en `lavasec-ios`.

Lava Security es una app de iOS centrada en la privacidad que filtra DNS localmente en el dispositivo a través de un túnel de paquetes NetworkExtension en el propio dispositivo, bloqueando dominios conocidos como peligrosos o no deseados sin enrutar tu navegación a través de los servidores de Lava. Este documento cubre cómo está estructurado el cliente iOS: los targets, cómo la app se comunica con su extensión de túnel, el ciclo de vida de la VPN, el modelo de estado de Guardian, la Live Activity y el widget, el flujo de incorporación y el propietario del estado del lado de la app (`AppViewModel`).

Para la visión de todo el sistema (la app, el Worker del catálogo y Supabase), consulta [Visión general del sistema](./system-overview.md).

---

## 1. Targets y responsabilidades

El cliente se distribuye como tres targets ejecutables más una biblioteca core compartida. Los tres targets se unen al mismo **App Group** (`group.com.lavasec`) y enlazan `LavaSecCore`.

| Target | Bundle id | Responsabilidad |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | La app SwiftUI. Es propietaria de la UI, mantiene el entitlement de NetworkExtension y controla el túnel mediante `NETunnelProviderManager`. `AppViewModel` es la fuente de verdad del ciclo de vida de la VPN. |
| **Packet tunnel** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | La subclase de `NEPacketTunnelProvider` `PacketTunnelProvider` (también conocida como `LavaSecTunnel`). Analiza paquetes DNS, extrae el dominio consultado, lo evalúa contra el snapshot compilado mapeado en memoria y reenvía aguas arriba las consultas permitidas. Limitada por el techo de memoria jetsam de ~50 MiB por proceso. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Un `WidgetBundle` cuyo único miembro es `LavaProtectionLiveActivityWidget` — la presentación de la Live Activity / Dynamic Island. |

El código compartido vive en dos lugares:

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — el core independiente de la plataforma: el motor de filtrado, los transportes de resolver, los cálculos de snapshot/presupuesto, los stores de protección y el core de `GuardianMascotAnimation`. Según `VPNLifecycleController.swift:3-6`, los tipos de NetworkExtension se mantienen intencionadamente fuera de este módulo para que su lógica de ciclo de vida siga siendo testeable con fakes; el target de la app proporciona las conformidades respaldadas por `NetworkExtension`.
- **`Shared/`** — código compilado en más de un target (p. ej. `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

Los detalles internos del packet-tunnel (el análisis de DNS, el snapshot compilado, los transportes de resolver cifrados y el presupuesto de reglas de filtrado) se cubren en profundidad en [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md). Este documento se centra en la arquitectura del lado de la app y en el límite entre la app y la extensión.

---

## 2. IPC app ↔ extensión

La app y la extensión del packet-tunnel son procesos separados. Se coordinan a través de tres mecanismos, todos anclados en el App Group.

### Contenedor del App Group

`group.com.lavasec` es el contenedor compartido que permite a la app, al túnel y al widget leer y escribir el mismo estado y configuración de `LavaSecCore`. `LavaSecAppGroup` (`Shared/AppGroup.swift`) centraliza cada clave y nombre de archivo compartido para que los procesos nunca puedan divergir en las constantes de cadena, incluyendo:

- Los artefactos del snapshot compilado (`filter-snapshot.compact`, `filter-snapshot.json`), el `app-configuration.json` serializado, la salud del túnel (`tunnel-health.json`), los diagnósticos y el registro de actividad de red.
- Las claves de `UserDefaults` compartidas para la sesión de protección y el estado de pausa. Estas son alias directos de los stores de `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — de modo que la app, el túnel y los intents de la Live Activity comparten un único diseño de claves, un único contador de revisiones y un único esquema de deduplicación.
- El directorio de caché del catálogo y el archivo de registro de depuración en el dispositivo.

La URL del contenedor se resuelve mediante `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Mensaje de comando / provider (la ruta de control)

La app dirige el túnel con **`sendProviderMessage`** para todos los comandos. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) obtiene la `NETunnelProviderSession` activa del manager en caché y llama a `session.sendProviderMessage(...)`. La carga útil es codificada por `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) en un pequeño sobre JSON que lleva un `kind` de mensaje y un `operationID` opcional (usado para el rastreo de latencia de extremo a extremo).

Los tipos de mensaje reconocidos son constantes en `LavaSecAppGroup`:

| Constante de mensaje | Efecto en el túnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Forzar la recarga del snapshot de filtro compilado. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Releer únicamente el estado de pausa compartido. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Recargar la configuración; solo un cambio de *identidad del resolver* dispara una reconexión visible. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Mantenimiento de diagnósticos/registros. |

En el lado del túnel, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica el sobre y conmuta según `kind`. En particular, `reload-configuration` carga la nueva configuración para que los campos que no son de resolver (interruptores de diagnósticos, estado de pago) surtan efecto, pero solo reinicia el runtime de DNS y reaplica los ajustes de red del túnel — una reconexión visible — cuando la identidad del resolver realmente cambió (`PacketTunnelProvider.swift:768-792`). Un cambio de flag de diagnósticos o de estado de pago nunca cae la conexión activa.

Los helpers `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` de la app (`AppViewModel.swift:7062`/`7070`) son envoltorios ligeros que envían estos mensajes.

### Por qué provider messages para el control app→túnel

**`sendProviderMessage` es la única ruta de control app→túnel — no hay señal Darwin app→túnel.** Un diseño anterior publicaba una señal Darwin de `CFNotificationCenter` al pausar y la observaba dentro de la extensión, pero nunca se disparaba de forma fiable en el proceso de NetworkExtension y se eliminó. El servicio de comandos ya no publica `CFNotificationCenterPostNotification`, y el túnel ya no agrega un `CFNotificationCenterAddObserver` — la ausencia de ambos se afirma mediante tests de introspección de fuente (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` para la publicación del servicio de comandos; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` para el observador del túnel) para protegerse contra su reintroducción. (Las líneas `import Darwin` que permanecen en el servicio de comandos y en el túnel son para primitivas de `flock`/socket, no para notificaciones.)

Una ruta Darwin *sí* se mantiene en la otra dirección. El túnel publica un aviso de cambio de salud hacia la app: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) publica `CFNotificationCenterPostNotification` en el canal `com.lavasec.protection.tunnel-health-changed` (el nombre del canal vive en `TunnelHealthSignal.swift`, no en `AppGroup.swift`), y la app lo observa mediante `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), conectado en `AppViewModel` para llamar a `handleTunnelHealthNudge()`. La presencia de este aviso de salud túnel→app se afirma en `LavaLiveActivitySourceTests.swift:1059-1075`.

Para el control app→túnel, la pausa se entrega escribiendo el `ProtectionPauseStore` compartido y siguiéndolo con el provider message `reload-protection-pause` para que el túnel ejecute `refreshProtectionPauseStateOnly`. `AppViewModel.swift:4995-4996` documenta la regla directamente: la app "tampoco se apoya nunca en el observador Darwin del snapshot, siempre usa `sendProviderMessage`." Trata el par App Group (estado compartido) + `sendProviderMessage` (la señal de despertar/control) como la ruta de control app→túnel.

### Servicio de comandos de la Live Activity

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) es el punto de entrada para las acciones de Dynamic Island / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes` / `pause-configured` (el único botón de Pausa de la Live Activity, cuya duración es el valor configurado por el usuario), `resume`, `reconnect`). Los `LiveActivityIntent` en `LavaLiveActivityIntents.swift` se ejecutan en el proceso de la app (que mantiene el entitlement de NetworkExtension), por lo que:

- **Pausar / reanudar** fluyen a través de un bloqueo de archivo entre procesos (`protection-command.lock`, `flock`) y los `ProtectionPauseStore` / `ProtectionSessionStore` de `LavaSecCore`, que son propietarios de la acuñación de revisiones y la deduplicación de comandos duplicados (el `commandID` hilvana el id de operación del llamante para que un comando reenviado no pueda acuñar una segunda revisión). El resultado programa una actualización de la Live Activity protegida por revisión.
- **Reconectar** se maneja directamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): llama a `loadAllFromPreferences` e inicia el primer manager de túnel instalado mediante `startVPNTunnel()` (porque `loadAllFromPreferences` ya está acotado a las configuraciones NE de esta app, ese primer manager es el de Lava — a diferencia de `VPNLifecycleController.matchingManagers()`, no realiza una comprobación explícita de identidad). Connect-On-Demand ya está habilitado, así que esto solo fuerza una conexión inmediata; la reconciliación de estado de la app entonces devuelve la Live Activity a `.on` una vez conectada.

---

## 3. Ciclo de vida y control de la VPN

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) es la fuente de verdad del ciclo de vida de la VPN en la app. Orquesta el encendido/apagado, mantiene en caché el `NETunnelProviderManager` activo y publica el estado a SwiftUI.

### Selección de manager y cálculo del ciclo de vida

La lógica reutilizable del ciclo de vida, libre de NetworkExtension, vive en `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). La app proporciona conformidades respaldadas por `NETunnelProviderManager` de `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; el controlador maneja:

- **Selección y deduplicación** — `matchingManagers()` filtra a los managers propiedad de Lava mediante `LavaTunnelConfigurationIdentity.matches(...)`, ordena por `selectionPriority` (primero el activo, luego el nombre de visualización canónico), y `removeDuplicateManagers(keeping:)` converge en un único superviviente.
- **Esperas de conexión/parada** — `waitForConnect` / `waitForStop` sondean el estado de la conexión activa con una tolerancia de `startGraceInterval`, porque justo después de `startVPNTunnel` la conexión puede leer brevemente un estado no pendiente antes de que iOS la transicione a `.connecting`.

### Encendido / apagado

`enableProtection(...)` (`AppViewModel.swift:5764`) es **cache-first**: cuando existe un artefacto preparado confirmado como reutilizable para la configuración actual, la VPN puede levantarse de inmediato desde la caché mientras una sincronización del catálogo en curso sigue refrescándose en segundo plano, y `performCatalogSync` reconcilia el túnel en ejecución al completarse. Solo se bloquea en la sincronización cuando no hay nada válido desde lo cual arrancar (p. ej. el usuario acaba de cambiar el conjunto de la lista habilitada, invalidando la identidad del artefacto en caché).

`disableProtection(...)` (`AppViewModel.swift:5972`) desactiva Connect-On-Demand *antes* de detener el túnel para que iOS no lo reconecte inmediatamente. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) instala un `NEOnDemandRuleConnect` (coincidencia de interfaz `.any`) y guarda las preferencias — guardar (no solo establecer) es necesario para que iOS respete el cambio.

### Observación de estado (y una advertencia sobre el calentamiento)

`AppViewModel` observa `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) y publica `vpnStatus`/`isVPNConfigurationInstalled`. Crucialmente, cuando un manager ya está en caché, lee la conexión activa del manager en caché en lugar de forzar un refresco de `loadAllFromPreferences`: el propio `loadAllFromPreferences` vuelve a publicar `NEVPNStatusDidChange`, y un refresco forzado en el observador producía una tormenta autosostenida — el comentario en el código fuente (`AppViewModel.swift:1046-1048`) registra los ~370 eventos/s medidos y la regresión de calentamiento del 134% de CPU que causó. Las propiedades publicadas solo cambian en transiciones reales, así que los ticks en reposo dejan de invalidar SwiftUI.

### Reconciliación fail-closed de on-demand

Connect-On-Demand puede levantar el túnel **en frío** al iniciar (o después de que iOS lo derribe en un cambio de red) antes de que la app haya enviado un snapshot. Un túnel en frío sin un snapshot persistido reutilizable carga **fail-closed** — bloquea todo el tráfico — y nunca se recupera por sí solo. `AppViewModel` maneja esto en dos rutas de inicio, ambas condicionadas a que la incorporación esté completa (`hasCompletedOnboarding`, reflejando el flag `@AppStorage("hasSeenLavaOnboarding")`):

- **Después de la incorporación** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) se ejecuta siempre que la protección esté activa al iniciar: prepara el snapshot de arranque, persiste el estado compartido y envía `reload-snapshot` para que el túnel recargue sus reglas reales saliendo de fail-closed. Fail-closed sigue siendo el valor por defecto seguro; esto simplemente lo reemplaza con prontitud. (Corrige los filtros mostrados en rojo / el tráfico bloqueado después de reiniciar la app mientras Connect-On-Demand mantiene el túnel levantado.)
- **A mitad de la incorporación** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) se ejecuta *antes* de cualquier trabajo de red cuando la incorporación no ha terminado. iOS no elimina de forma fiable un perfil de VPN al eliminar la app, por lo que una reinstalación puede heredar una configuración huérfana con on-demand habilitado que levanta un túnel en frío fail-closed antes de que el usuario haya elegido ninguna lista de bloqueo. Esta ruta **elimina** la configuración (`removeFromPreferences`) en lugar de guardar una modificación de la misma — `saveToPreferences` volvería a mostrar el aviso del sistema "Añadir configuraciones de VPN" en un perfil que esta instalación no posee, disparando el diálogo al iniciar la app antes de que se renderice la hoja de incorporación. Es una operación nula en una instalación limpia y cuando la configuración heredada ya está inerte.

---

## 4. Modelo de Guardian / estado

Hay dos vocabularios de estado relacionados: una *evaluación* de conectividad y un estado de *mascota* Guardian.

### Evaluación de conectividad

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) mapea un `TunnelHealthSnapshot` a un `ProtectionConnectivityAssessment` con una de **seis severidades** y **dos acciones**:

- Severidades: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Acciones primarias: `turnOff` o `reconnect`.

Esta única evaluación dirige tanto la superficie de Guard en la app como (mapeada más allá) el estado de la Dynamic Island, así que las dos nunca discrepan.

**Suelo de honestidad (v1.0).** Un fallo actual y no cubierto de la prueba de humo de DNS nunca puede leerse como `.healthy` — la evaluación expone `.recovering` hasta que una prueba realmente tenga éxito, así que el tráfico transportado por fallback sobre un primario atascado ya no se pinta como "Protegido." La lógica de reconexión se basa en `consecutiveDNSSmokeProbeFailureCount` y `lastPrimaryUpstreamSuccessAt` (solo del primario) en lugar de los contadores genéricos de aguas arriba, y un resolver que sigue siendo alcanzable pero sigue **rechazando** la prueba conocida como buena (secuestro/cautivo/obsoleto) se escala a digno de reinicio mediante un `consecutiveRejectedSmokeResponseCount` acotado a la identidad del resolver (LAV-87), incluso cuando la racha genérica sigue reiniciándose en redes de roaming inestables.

### Notificaciones de conectividad

`ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`) convierte la evaluación en como máximo una notificación local pendiente, regulada (600s) y deduplicada. v1.0 agrega:

- Un tipo **`dnsSlow`** distinto ("Lava DNS es lento") — el DNS lento solía reutilizar el tipo `reconnectNeeded`, así que una interrupción real no podía reemplazarlo.
- **Escalada/reemplazo** — un problema estrictamente más urgente (solo `reconnectNeeded` supera al resto) puede reemplazar un banner pendiente de menor rango, evitando tanto la salvaguarda de "problema ya pendiente" como la regulación, así que un atasco tras un fallback a Device-DNS expone el aviso accionable de "Reconectar" en lugar de dejar un banner tranquilizador.
- Una **migración de persistencia** (`ProtectionConnectivityNotificationStore`, esquema v2, conectada mediante `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) degrada un marcador heredado pendiente de `reconnect-needed` a `dnsSlow` para que la escalada funcione entre actualizaciones.

### Reintento de captura de Device-DNS

Cuando la configuración activa depende del resolver del dispositivo (como primario o como fallback), un traspaso/despertar de red puede dejar el túnel sosteniendo una captura vacía del resolver del sistema — un atasco silencioso. `DeviceDNSFallbackPolicy` dirige un **reintento acotado** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1s, `deviceDNSCaptureMaxRetryAttempts` 5): el túnel relee los resolvers del sistema cada segundo durante hasta cinco intentos hasta que la captura no esté vacía, y luego la adopta en su lugar — recuperándose automáticamente sin un reinicio del túnel (eventos `device-dns-capture-retry` / `-exhausted`). Es una operación nula para configuraciones DoH/DoT/DoQ puras (`currentConfigurationDependsOnDeviceDNS()`).

### Estados de la mascota Guardian

La mascota Soft Shield Guardian tiene exactamente **siete** estados emocionales — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Cada estado declara sus `allowedNextStates` de modo que las transiciones están restringidas (p. ej. `grateful` solo vuelve a `awake`; `GuardianMascotAnimation.swift:12-29`). Semántica:

- `retrying` = autocuración tranquila.
- `concerned` = búsqueda de ayuda suave.
- `grateful` = éxito celebratorio (usado en superficies de incorporación/ajustes, no en el mapa de conectividad).

`GuardianMascotAnimation` es el core de animación procedural en `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) es el renderizado SwiftUI y soporta las skins de personalización seleccionadas por `GuardianShieldStyle` (nombres de visualización Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, con el mapeo de `displayName` en las líneas 18-35). Algunos valores en bruto divergen de sus nombres de visualización (p. ej. `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, y `purpleObsidian` se renderiza como "Amethyst"), así que persiste el valor en bruto, no la etiqueta.

### Cómo se conectan los dos

El `LavaActivityAttributes.ProtectionState` de la Live Activity (`Shared/LavaActivityAttributes.swift`) hace de puente entre la evaluación y un estado de mascota mediante `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). `AppViewModel` elige el estado de protección para la Dynamic Island desde la misma `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): una severidad `networkUnavailable` se convierte en `.networkUnavailable`, `recovering` se convierte en `.reconnecting`, una acción primaria `reconnect` se convierte en `.needsReconnect`, y en caso contrario `.on`.

> Nota: `LavaTier` (el enum de profundidad del sistema de diseño tranquilo → **Floor** / celebratorio → **Window** / técnico → **Workshop**) se distribuye en la capa del sistema de diseño (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), conectado en superficies representativas — consulta [el sistema de diseño](../design-system/overview.md). Gobierna la profundidad del sistema de diseño, no la ruta del cliente de protección/túnel descrita aquí.

---

## 5. Live Activity y widget

El target del widget renderiza únicamente la Live Activity y la Dynamic Island. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) expone un único `LavaProtectionLiveActivityWidget`, un `ActivityConfiguration(for: LavaActivityAttributes.self)` con:

- Una vista de pantalla de bloqueo, una región central expandida de la Dynamic Island y presentaciones compactas/mínimas que renderizan `SoftShieldGuardian` más un glifo de estado. Las vistas compactas/de bloqueo recalculan el estado de protección *efectivo* en un `TimelineView` por segundo para que una cuenta regresiva de pausa se mantenga en vivo sin un push.

`LavaActivityAttributes.ContentState` lleva `protectionState`, un `resumeDate` (para las cuentas regresivas de pausa), `pauseRequiresAuthentication` y el `shieldStyle` elegido. La decodificación es tolerante — un `shieldStyle` ausente recurre a `.original` — así que las cargas útiles de Live Activity más antiguas siguen funcionando.

En el lado de la app, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) es propietario de la `Activity<LavaActivityAttributes>` en vivo: observa los cambios de autorización de ActivityKit, solo ofrece Live Activities en los idioms de teléfono/tableta, y `reconcile(...)` inicia/actualiza/finaliza la actividad para que coincida con el estado de protección solicitado. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) es el único embudo que recalcula el estado deseado y llama al controlador. Los botones de la Dynamic Island despachan `LiveActivityIntent`, que llaman a `LavaProtectionCommandService` como se describe en [§2](#2-ipc-app-extensión).

---

## 6. Flujo de incorporación

La incorporación es presentada por `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) y condicionada por el flag `@AppStorage("hasSeenLavaOnboarding")` declarado en `RootView` (`RootView.swift:32`). El flujo es una secuencia de `OnboardingPage`s (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

La configuración inicial que se distribuye proviene de `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` habilita únicamente la fuente recomendada permisiva (Block List Basic), selecciona **Device DNS** como resolver — `DNSResolverPreset.device` (id `device-dns`), el propio DNS de la red; los presets cifrados como Google DoH son opcionales y no se promueven a valor por defecto — habilita el fallback de device-DNS, y mantiene el registro local activado — con `protectionEnabled: false`, de modo que la protección solo se activa cuando el usuario la elige. `OnboardingDefaultsSummary` formatea esas elecciones para mostrarlas ("Continuar sin cuenta" es el valor por defecto de cuenta).

Establecer `hasSeenLavaOnboarding = true` al final es lo que activa `hasCompletedOnboarding`, que a su vez arma la ruta de reconciliación de inicio descrita en [§3](#3-ciclo-de-vida-y-control-de-la-vpn). Hasta entonces, la ruta de neutralización a mitad de la incorporación evita que cualquier túnel fail-closed heredado bloquee el tráfico.

---

## 7. Estado de la app: `AppViewModel`

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) es el propietario central del estado del lado de la app. Más allá del ciclo de vida de la VPN, publica las superficies a las que se vincula la UI, incluyendo:

- **Protección y túnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, y los `vpnMessage`/`vpnMessageIsError` orientados al usuario.
- **Configuración y catálogo** — la `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, y los recuentos de reglas compiladas (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnósticos** — `DiagnosticsStore` y `NetworkActivityLog` (todo local; consulta la promesa de privacidad más abajo).
- **Cuenta y respaldo** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, y el estado de ofertas/entitlement de **Lava Security Plus**.
- **Personalización y presentación** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress`, y `usesLiveActivities`.

Delega la serialización del ciclo de vida a un `protectionActionOrchestrator` (para que una restauración en segundo plano no se intercale con un encendido del usuario), mantiene el `tunnelManager` en caché, y dirige todos los cambios de snapshot/configuración/pausa a la extensión mediante los helpers de provider-message en [§2](#2-ipc-app-extensión).

> **Encuadre de privacidad.** El filtrado de DNS ocurre localmente en este dispositivo. Las superficies de diagnósticos y de actividad de red que publica `AppViewModel` se almacenan únicamente de forma local — Lava nunca recibe tus consultas DNS rutinarias, tu historial de navegación ni telemetría por dominio. Cualquier respaldo de cuenta opcional es de **conocimiento cero** (cifrado en el dispositivo; Lava solo puede llegar a almacenar texto cifrado), incluyendo la recuperación basada en passkey — su clave se deriva mediante PRF en el dispositivo sin ningún secreto guardado en el servidor. Consulta [Visión general del sistema](./system-overview.md) para conocer el límite del servidor.

---

## Documentos relacionados

- [Visión general del sistema](./system-overview.md) — todo el sistema en una sola pantalla: la app, el Worker del catálogo y Supabase, además de los límites de confianza y la leyenda de estado usada en todo el documento.
- [Filtrado de DNS y listas de bloqueo](./dns-filtering-and-blocklists.md) — los detalles internos del packet-tunnel referenciados aquí solo en el límite de control: el motor de filtrado compilado, los transportes de resolver cifrados (DoH / DoH3 / DoT / DoQ), el presupuesto de reglas de filtrado, el catálogo de listas de bloqueo y el modelo de redistribución source-url-only.
- [Cuentas y respaldo de conocimiento cero](./accounts-and-backup.md) — los proveedores de inicio de sesión y el sobre de respaldo de conocimiento cero que orquesta `AppViewModel` (incluyendo el slot de recuperación por passkey de conocimiento cero y derivado por PRF).
- [Backend y datos](./backend-and-data.md) — el Worker del catálogo `lavasec-api`, Cloudflare R2 y el esquema/RLS de Supabase que se sitúan al otro lado del límite app↔servidor.
- [Sistema de diseño](../design-system/overview.md) — el modelo de profundidad `LavaTier`, los siete estados del Soft Shield Guardian y las skins del escudo, y las convenciones de copia/localización que renderiza el cliente.
- [Avisos de terceros](../legal/third-party-notices.md) y [decisión de cumplimiento GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — las restricciones de distribución detrás del pipeline de catálogo/filtro que consume el cliente.
