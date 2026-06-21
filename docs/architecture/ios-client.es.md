---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Arquitectura del cliente iOS {#ios-client-architecture}

> Público: ingenieros de iOS que trabajan en `lavasec-ios`.

Lava Security es una app de iOS centrada en la privacidad que filtra DNS localmente en el dispositivo mediante un túnel de paquetes NetworkExtension on-device, bloqueando dominios conocidos como riesgosos o no deseados sin enrutar tu navegación a través de los servidores de Lava. Este documento explica cómo está estructurado el cliente iOS: los targets, cómo la app se comunica con su extensión de túnel, el ciclo de vida de la VPN, el modelo de estados del Guardian, la Live Activity y el widget, el flujo de incorporación y el dueño del estado del lado de la app (`AppViewModel`).

Para ver el sistema completo (la app, el Worker del catálogo y Supabase), consulta [Visión general del sistema](./system-overview.md).

---

## 1. Targets y responsabilidades {#1-targets-responsibilities}

El cliente se distribuye como tres targets ejecutables más una biblioteca core compartida. Los tres targets se unen al mismo **App Group** (`group.com.lavasec`) y enlazan `LavaSecCore`.

| Target | Bundle id | Responsabilidad |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | La app SwiftUI. Posee la UI, mantiene el entitlement de NetworkExtension y controla el túnel mediante `NETunnelProviderManager`. `AppViewModel` es la fuente de verdad del ciclo de vida de la VPN. |
| **Túnel de paquetes** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | La subclase `PacketTunnelProvider` de `NEPacketTunnelProvider` (también conocida como `LavaSecTunnel`). Analiza paquetes DNS, extrae el dominio consultado, lo evalúa contra el snapshot compilado mapeado en memoria y reenvía las consultas permitidas hacia el upstream. Limitada por el techo de memoria jetsam de ~50 MiB por proceso. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Un `WidgetBundle` cuyo único miembro es `LavaProtectionLiveActivityWidget`: la presentación de la Live Activity / Dynamic Island. |

El código compartido vive en dos lugares:

- **`LavaSecCore`** (`Sources/LavaSecCore/`): el core independiente de plataforma: el motor de filtrado, los transportes de resolver, la matemática de snapshot/presupuesto, los stores de protección y el core de `GuardianMascotAnimation`. Según `VPNLifecycleController.swift:3-6`, los tipos de NetworkExtension se mantienen intencionalmente fuera de este módulo para que su lógica de ciclo de vida siga siendo testeable con fakes; el target de la app provee las conformidades respaldadas por `NetworkExtension`.
- **`Shared/`**: código compilado en más de un target (por ejemplo `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

Las interioridades del túnel de paquetes (análisis de DNS, el snapshot compilado, los transportes de resolver cifrados y el presupuesto de reglas de filtrado) se cubren en profundidad en [Filtrado DNS y listas de bloqueo](./dns-filtering-and-blocklists.md). Este documento se centra en la arquitectura del lado de la app y en la frontera entre la app y la extensión.

---

## 2. IPC app ↔ extensión {#2-app-extension-ipc}

La app y la extensión del túnel de paquetes son procesos separados. Se coordinan mediante tres mecanismos, todos anclados en el App Group.

### Contenedor del App Group {#app-group-container}

`group.com.lavasec` es el contenedor compartido que permite que la app, el túnel y el widget lean y escriban el mismo estado y configuración de `LavaSecCore`. `LavaSecAppGroup` (`Shared/AppGroup.swift`) centraliza cada clave y nombre de archivo compartido para que los procesos nunca puedan divergir en constantes de cadena, incluyendo:

- Los artefactos del snapshot compilado (`filter-snapshot.compact`, `filter-snapshot.json`), el `app-configuration.json` serializado, la salud del túnel (`tunnel-health.json`), los diagnósticos y el registro de actividad de red.
- Claves compartidas de `UserDefaults` para la sesión de protección y el estado de pausa. Estas son alias directos de los stores de `LavaSecCore` (`AppGroup.swift:38-41`): `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys`, de modo que la app, el túnel y los intents de la Live Activity comparten un único layout de claves, un único contador de revisiones y un único esquema de deduplicación.
- El directorio de caché del catálogo y el archivo de registro de depuración on-device.

La URL del contenedor se resuelve mediante `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Mensaje de comando / provider (la ruta de control) {#command-provider-message-the-control-path}

La app maneja el túnel con **`sendProviderMessage`** para todos los comandos. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) obtiene la `NETunnelProviderSession` activa del manager en caché y llama a `session.sendProviderMessage(...)`. El payload lo codifica `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) en un pequeño envoltorio JSON que lleva un `kind` de mensaje y un `operationID` opcional (usado para el rastreo de latencia de extremo a extremo).

Los tipos de mensaje reconocidos son constantes en `LavaSecAppGroup`:

| Constante de mensaje | Efecto en el túnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Forzar la recarga del snapshot de filtro compilado. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Releer únicamente el estado de pausa compartido. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Recargar la configuración; solo un cambio de *identidad de resolver* dispara una reconexión visible. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Mantenimiento de diagnósticos/registros. |

Del lado del túnel, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica el envoltorio y hace un switch sobre `kind`. En particular, `reload-configuration` carga la nueva configuración para que los campos no relacionados con el resolver (toggles de diagnósticos, estado de pago) surtan efecto, pero solo reinicia el runtime de DNS y vuelve a aplicar la configuración de red del túnel —una reconexión visible— cuando la identidad del resolver realmente cambió (`PacketTunnelProvider.swift:768-792`). Un cambio de bandera de diagnósticos o de estado de pago nunca interrumpe la conexión activa.

Los helpers `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` de la app (`AppViewModel.swift:7062`/`7070`) son envoltorios delgados que envían estos mensajes.

### Por qué se usan mensajes de provider para el control app→túnel {#why-provider-messages-for-apptunnel-control}

**`sendProviderMessage` es la única ruta de control app→túnel: no hay ninguna señal Darwin app→túnel.** Un diseño anterior publicaba una señal Darwin de `CFNotificationCenter` al pausar y la observaba dentro de la extensión, pero nunca se disparó de forma confiable en el proceso de NetworkExtension y se eliminó. El servicio de comandos ya no publica `CFNotificationCenterPostNotification`, y el túnel ya no agrega un `CFNotificationCenterAddObserver`: ambos se afirman ausentes mediante pruebas de introspección de fuente (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` para la publicación del servicio de comandos; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` para el observador del túnel) a fin de evitar su reintroducción. (Las líneas `import Darwin` que permanecen en el servicio de comandos y en el túnel son para primitivas de `flock`/socket, no para notificaciones.)

Una ruta Darwin *sí* sigue existiendo en la otra dirección. El túnel publica un aviso de cambio de salud hacia la app: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) publica `CFNotificationCenterPostNotification` en el canal `com.lavasec.protection.tunnel-health-changed` (el nombre del canal vive en `TunnelHealthSignal.swift`, no en `AppGroup.swift`), y la app lo observa mediante `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), conectado en `AppViewModel` para llamar a `handleTunnelHealthNudge()`. Este aviso de salud túnel→app se afirma *presente* mediante `LavaLiveActivitySourceTests.swift:1059-1075`.

Para el control app→túnel, la pausa se entrega escribiendo el `ProtectionPauseStore` compartido y siguiéndolo con el mensaje de provider `reload-protection-pause` para que el túnel ejecute `refreshProtectionPauseStateOnly`. `AppViewModel.swift:4995-4996` documenta la regla directamente: la app "tampoco depende nunca del observador Darwin del snapshot, usando siempre `sendProviderMessage`". Trata el par App Group (estado compartido) + `sendProviderMessage` (la señal de despertar/control) como la ruta de control app→túnel.

### Servicio de comandos de la Live Activity {#live-activity-command-service}

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) es el punto de entrada para las acciones de Dynamic Island / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`). Los `LiveActivityIntent` en `LavaLiveActivityIntents.swift` se ejecutan en el proceso de la app (que mantiene el entitlement de NetworkExtension), por lo que:

- **Pausa / reanudación** fluyen a través de un bloqueo de archivo entre procesos (`protection-command.lock`, `flock`) y de los stores `ProtectionPauseStore` / `ProtectionSessionStore` de `LavaSecCore`, que se encargan de acuñar revisiones y de deduplicar comandos duplicados (el `commandID` enlaza el id de operación de quien llama, de modo que un comando reentregado no pueda acuñar una segunda revisión). El resultado programa una actualización de la Live Activity protegida por revisión.
- **Reconexión** se maneja directamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): llama a `loadAllFromPreferences` e inicia el primer manager de túnel instalado mediante `startVPNTunnel()` (como `loadAllFromPreferences` ya está acotado a las configuraciones NE de esta app, ese primer manager es el de Lava; a diferencia de `VPNLifecycleController.matchingManagers()`, no hace una coincidencia de identidad explícita). Connect-On-Demand ya está habilitado, así que esto solo fuerza una conexión inmediata; la reconciliación de estado de la app devuelve entonces la Live Activity a `.on` una vez conectada.

---

## 3. Ciclo de vida y control de la VPN {#3-vpn-lifecycle-control}

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) es la fuente de verdad del ciclo de vida de la VPN en la app. Orquesta el encendido/apagado, cachea el `NETunnelProviderManager` activo y publica el estado a SwiftUI.

### Selección de manager y matemática del ciclo de vida {#manager-selection-and-lifecycle-math}

La lógica de ciclo de vida reutilizable y libre de NetworkExtension vive en `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). La app provee las conformidades de `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting` respaldadas por `NETunnelProviderManager`; el controller se encarga de:

- **Selección y deduplicación**: `matchingManagers()` filtra a los managers propiedad de Lava mediante `LavaTunnelConfigurationIdentity.matches(...)`, ordena por `selectionPriority` (activos primero, luego el nombre canónico de visualización), y `removeDuplicateManagers(keeping:)` converge en un único superviviente.
- **Esperas de conexión/detención**: `waitForConnect` / `waitForStop` consultan el estado de la conexión activa con una tolerancia `startGraceInterval`, porque justo después de `startVPNTunnel` la conexión puede leerse brevemente como un estado no pendiente antes de que iOS la haga pasar a `.connecting`.

### Encendido / apagado {#turn-on-turn-off}

`enableProtection(...)` (`AppViewModel.swift:5764`) es **cache-first**: cuando existe un artefacto preparado confirmado como reutilizable para la configuración actual, la VPN puede levantarse de inmediato desde la caché mientras una sincronización del catálogo en curso sigue refrescando en segundo plano, y `performCatalogSync` reconcilia el túnel en ejecución al completarse. Solo se bloquea en la sincronización cuando no hay nada válido desde donde arrancar (por ejemplo, el usuario acaba de cambiar el conjunto de listas habilitadas, invalidando la identidad del artefacto en caché).

`disableProtection(...)` (`AppViewModel.swift:5972`) desactiva Connect-On-Demand *antes* de detener el túnel para que iOS no lo reconecte de inmediato. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) instala un `NEOnDemandRuleConnect` (coincidencia de interfaz `.any`) y guarda las preferencias; guardar (no solo establecer) es necesario para que iOS respete el cambio.

### Observación de estado (y una advertencia sobre el calentamiento) {#status-observation-and-a-heat-caveat}

`AppViewModel` observa `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) y publica `vpnStatus`/`isVPNConfigurationInstalled`. Algo crucial: cuando ya hay un manager en caché, lee la conexión activa del manager cacheado en lugar de forzar un refresco con `loadAllFromPreferences`: `loadAllFromPreferences` por sí solo vuelve a publicar `NEVPNStatusDidChange`, y un refresco forzado en el observador producía una tormenta que se autoalimentaba; el comentario en el código (`AppViewModel.swift:1046-1048`) registra los ~370 eventos/s medidos y la regresión de calentamiento del 134% de CPU que provocó. Las propiedades publicadas solo cambian en transiciones reales, de modo que los ticks inactivos dejan de invalidar SwiftUI.

### Reconciliación fail-closed de on-demand {#fail-closed-on-demand-reconcile}

Connect-On-Demand puede levantar el túnel **en frío** al iniciar (o después de que iOS lo desmonte por un cambio de red) antes de que la app haya enviado un snapshot. Un túnel en frío sin snapshot persistido reutilizable carga **fail-closed** —bloquea todo el tráfico— y nunca se recupera por sí solo. `AppViewModel` maneja esto en dos rutas de inicio, ambas condicionadas a que la incorporación esté completa (`hasCompletedOnboarding`, que refleja la bandera `@AppStorage("hasSeenLavaOnboarding")`):

- **Después de la incorporación**: `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) se ejecuta cada vez que la protección está activa al iniciar: prepara el snapshot de arranque, persiste el estado compartido y envía `reload-snapshot` para que el túnel recargue sus reglas reales y salga del fail-closed. El fail-closed sigue siendo el valor por defecto seguro; esto simplemente lo reemplaza con prontitud. (Corrige los filtros mostrados en rojo / el tráfico bloqueado tras un reinicio de la app mientras Connect-On-Demand mantiene el túnel activo.)
- **Durante la incorporación**: `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) se ejecuta *antes* de cualquier trabajo de red cuando la incorporación no ha terminado. iOS no elimina de forma confiable un perfil de VPN al borrar la app, por lo que una reinstalación puede heredar una configuración huérfana con on-demand habilitado que levanta un túnel en frío fail-closed antes de que el usuario haya elegido lista de bloqueo alguna. Esta ruta **elimina** la configuración (`removeFromPreferences`) en lugar de guardar una modificación sobre ella; `saveToPreferences` volvería a mostrar el aviso del sistema "Agregar configuraciones de VPN" sobre un perfil que esta instalación no posee, disparando el diálogo en la inicialización de la app antes de que se renderice la hoja de incorporación. Es una operación nula en una instalación limpia y cuando la configuración heredada ya está inerte.

---

## 4. Modelo de Guardian / estados {#4-guardian-state-model}

Hay dos vocabularios de estado relacionados: una *evaluación* de conectividad y un estado de *mascota* Guardian.

### Evaluación de conectividad {#connectivity-assessment}

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) asigna un `TunnelHealthSnapshot` a un `ProtectionConnectivityAssessment` con una de **seis severidades** y **dos acciones**:

- Severidades: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Acciones primarias: `turnOff` o `reconnect`.

Esta única evaluación impulsa tanto la superficie de Guard dentro de la app como (mapeada más allá) el estado de la Dynamic Island, de modo que ambas nunca se contradicen.

**Piso de honestidad (v1.0).** Un fallo actual y no cubierto de la sonda de humo de DNS nunca puede leerse como `.healthy`: la evaluación muestra `.recovering` hasta que una sonda realmente tenga éxito, de modo que el tráfico transportado por fallback sobre un primario atascado ya no se pinta como "Protegido". La lógica de reconexión se basa en `consecutiveDNSSmokeProbeFailureCount` y `lastPrimaryUpstreamSuccessAt` (solo primario) en lugar de los contadores genéricos de upstream, y un resolver que sigue siendo alcanzable pero que sigue **rechazando** la sonda conocida como buena (secuestro/cautivo/obsoleto) se escala a digno de reinicio mediante un `consecutiveRejectedSmokeResponseCount` acotado a la identidad del resolver (LAV-87), incluso cuando la racha genérica se sigue reseteando en redes de roaming inestables.

### Notificaciones de conectividad {#connectivity-notifications}

`ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`) convierte la evaluación en como máximo una notificación local pendiente, regulada (600s) y deduplicada. v1.0 agrega:

- Un tipo distinto **`dnsSlow`** ("El DNS de Lava está lento"): el DNS lento solía reutilizar el tipo `reconnectNeeded`, por lo que una interrupción real no podía reemplazarlo.
- **Escalado/reemplazo**: un problema estrictamente más urgente (solo `reconnectNeeded` supera al resto) puede reemplazar un banner pendiente de rango inferior, esquivando tanto la protección de "problema ya pendiente" como la regulación, de modo que un atasco tras un fallback de DNS del dispositivo muestre el aviso accionable de "Reconectar" en lugar de dejar un banner tranquilizador.
- Una **migración de persistencia** (`ProtectionConnectivityNotificationStore`, esquema v2, conectada vía `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) degrada un marcador heredado `reconnect-needed` pendiente a `dnsSlow` para que el escalado funcione tras una actualización.

### Reintento de captura de DNS del dispositivo {#device-dns-capture-retry}

Cuando la configuración activa depende del resolver del dispositivo (como primario o como fallback), un traspaso/reactivación de red puede dejar al túnel con una captura del resolver del sistema vacía: un atasco silencioso. `DeviceDNSFallbackPolicy` impulsa un **reintento acotado** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1s, `deviceDNSCaptureMaxRetryAttempts` 5): el túnel relee los resolvers del sistema cada segundo durante hasta cinco intentos hasta que la captura no esté vacía, y entonces la adopta in situ, recuperándose automáticamente sin reiniciar el túnel (eventos `device-dns-capture-retry` / `-exhausted`). Es una operación nula para configuraciones puramente DoH/DoT/DoQ (`currentConfigurationDependsOnDeviceDNS()`).

### Estados de la mascota Guardian {#guardian-mascot-states}

La mascota Soft Shield Guardian tiene exactamente **siete** estados emocionales: `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Cada estado declara sus `allowedNextStates` de modo que las transiciones están restringidas (por ejemplo, `grateful` solo regresa a `awake`; `GuardianMascotAnimation.swift:12-29`). Semántica:

- `retrying` = autorreparación tranquila.
- `concerned` = búsqueda de ayuda suave.
- `grateful` = éxito celebratorio (usado en las superficies de incorporación/ajustes, no en el mapa de conectividad).

`GuardianMascotAnimation` es el core de animación procedural en `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) es el renderizado SwiftUI y soporta los skins de personalización seleccionados por `GuardianShieldStyle` (nombres de visualización Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, con el mapeo de `displayName` en las líneas 18-35). Algunos valores raw difieren de sus nombres de visualización (por ejemplo `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, y `purpleObsidian` se renderiza como "Amethyst"), así que persiste el valor raw, no la etiqueta.

### Cómo se conectan ambos {#how-the-two-connect}

El `LavaActivityAttributes.ProtectionState` de la Live Activity (`Shared/LavaActivityAttributes.swift`) enlaza la evaluación con un estado de mascota mediante `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). `AppViewModel` elige el estado de protección para la Dynamic Island a partir del mismo `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): una severidad `networkUnavailable` se convierte en `.networkUnavailable`, `recovering` se convierte en `.reconnecting`, una acción primaria `reconnect` se convierte en `.needsReconnect`, y en cualquier otro caso `.on`.

> Nota: `LavaTier` (el enum de profundidad del sistema de diseño calmo → **Floor** / celebratorio → **Window** / técnico → **Workshop**) se distribuye en la capa del sistema de diseño (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), conectado a superficies representativas; consulta [el sistema de diseño](../design-system/overview.md). Gobierna la profundidad del sistema de diseño, no la ruta del cliente de protección/túnel descrita aquí.

---

## 5. Live Activity y widget {#5-live-activity-widget}

El target del widget renderiza únicamente la Live Activity y la Dynamic Island. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) expone un solo `LavaProtectionLiveActivityWidget`, un `ActivityConfiguration(for: LavaActivityAttributes.self)` con:

- Una vista de pantalla de bloqueo, una región central expandida de la Dynamic Island y presentaciones compactas/mínimas que renderizan `SoftShieldGuardian` más un glifo de estado. Las vistas compacta/de bloqueo recalculan el estado de protección *efectivo* en un `TimelineView` por segundo, de modo que una cuenta regresiva de pausa se mantiene en vivo sin un push.

`LavaActivityAttributes.ContentState` lleva `protectionState`, un `resumeDate` (para las cuentas regresivas de pausa), `pauseRequiresAuthentication` y el `shieldStyle` elegido. La decodificación es tolerante —un `shieldStyle` ausente recae en `.original`—, de modo que los payloads más antiguos de la Live Activity siguen funcionando.

Del lado de la app, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) posee la `Activity<LavaActivityAttributes>` activa: observa los cambios de autorización de ActivityKit, solo ofrece Live Activities en los idiomas de teléfono/tableta, y `reconcile(...)` inicia/actualiza/finaliza la actividad para que coincida con el estado de protección solicitado. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) es el único embudo que recalcula el estado deseado y llama al controller. Los botones de la Dynamic Island despachan `LiveActivityIntent`s, que llaman a `LavaProtectionCommandService` como se describe en [§2](#2-app-extension-ipc).

---

## 6. Flujo de incorporación {#6-onboarding-flow}

La incorporación la presenta `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) y está condicionada por la bandera `@AppStorage("hasSeenLavaOnboarding")` declarada en `RootView` (`RootView.swift:32`). El flujo es una secuencia de `OnboardingPage`s (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

La configuración inicial distribuida proviene de `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` habilita únicamente las fuentes recomendadas permisivas (Block List Project Phishing + Scam), selecciona **Device DNS** como resolver —`DNSResolverPreset.device` (id `device-dns`), el propio DNS de la red; los presets cifrados como Google DoH son opcionales y no se promueven a valor por defecto—, habilita el fallback de DNS del dispositivo y mantiene activo el registro local, con `protectionEnabled: false`, de modo que la protección solo se activa cuando el usuario la elige. `OnboardingDefaultsSummary` formatea esas elecciones para mostrarlas ("Continuar sin cuenta" es el valor por defecto de la cuenta).

Establecer `hasSeenLavaOnboarding = true` al final es lo que activa `hasCompletedOnboarding`, que a su vez arma la ruta de reconciliación de inicio descrita en [§3](#3-vpn-lifecycle-control). Hasta entonces, la ruta de neutralización durante la incorporación evita que cualquier túnel fail-closed heredado bloquee el tráfico.

---

## 7. Estado de la app: `AppViewModel` {#7-app-state-appviewmodel}

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) es el dueño central del estado del lado de la app. Más allá del ciclo de vida de la VPN, publica las superficies a las que se vincula la UI, incluyendo:

- **Protección y túnel**: `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil` y los `vpnMessage`/`vpnMessageIsError` orientados al usuario.
- **Configuración y catálogo**: la `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt` y los conteos de reglas compiladas (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnósticos**: `DiagnosticsStore` y `NetworkActivityLog` (todo local; consulta la promesa de privacidad más abajo).
- **Cuenta y respaldo**: `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled` y el estado de ofertas/derechos de **Lava Security Plus**.
- **Personalización y presentación**: `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress` y `usesLiveActivities`.

Delega la serialización del ciclo de vida a un `protectionActionOrchestrator` (de modo que una restauración en segundo plano no se intercale con un encendido del usuario), mantiene el `tunnelManager` en caché e impulsa todos los cambios de snapshot/configuración/pausa hacia la extensión mediante los helpers de mensajes de provider de [§2](#2-app-extension-ipc).

> **Encuadre de privacidad.** El filtrado de DNS ocurre localmente en este dispositivo. Las superficies de diagnósticos y de actividad de red que publica `AppViewModel` se almacenan solo localmente: Lava nunca recibe tus consultas DNS rutinarias, tu historial de navegación ni telemetría por dominio. Cualquier respaldo opcional de cuenta es de **conocimiento cero** (cifrado en el dispositivo; Lava solo puede llegar a almacenar texto cifrado), incluida la recuperación basada en passkey: su clave se deriva por PRF en el dispositivo, sin secreto alguno en poder del servidor. Consulta [Visión general del sistema](./system-overview.md) para conocer la frontera del servidor.

---

## Documentos relacionados {#related-docs}

- [Visión general del sistema](./system-overview.md): todo el sistema en una sola pantalla: la app, el Worker del catálogo y Supabase, además de las fronteras de confianza y la leyenda de estados usada en todo el conjunto.
- [Filtrado DNS y listas de bloqueo](./dns-filtering-and-blocklists.md): las interioridades del túnel de paquetes referenciadas aquí solo en la frontera de control: el motor de filtrado compilado, los transportes de resolver cifrados (DoH / DoH3 / DoT / DoQ), el presupuesto de reglas de filtrado, el catálogo de listas de bloqueo y el modelo de redistribución solo-por-URL-de-fuente.
- [Cuentas y respaldo de conocimiento cero](./accounts-and-backup.md): los proveedores de inicio de sesión y el sobre de respaldo de conocimiento cero que `AppViewModel` orquesta (incluida la ranura de recuperación por passkey de conocimiento cero, derivada por PRF).
- [Backend y datos](./backend-and-data.md): el Worker del catálogo `lavasec-api`, Cloudflare R2 y el esquema/RLS de Supabase que están al otro lado de la frontera app↔servidor.
- [Sistema de diseño](../design-system/overview.md): el modelo de profundidad `LavaTier`, los siete estados del Soft Shield Guardian y los skins de escudo, y las convenciones de texto/localización que el cliente renderiza.
- [Avisos de terceros](../legal/third-party-notices.md) y [Decisión de cumplimiento GPL solo-por-URL-de-fuente](../legal/gpl-source-url-only-compliance-decision.md): las restricciones de distribución detrás del pipeline de catálogo/filtro que el cliente consume.
