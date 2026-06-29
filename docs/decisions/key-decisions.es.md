---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Decisiones de diseño clave

> Audiencia: ingeniería y liderazgo. Este es el registro al estilo ADR de las decisiones de diseño de carga estructural detrás de Lava Security — las que dieron forma a la arquitectura, a la promesa de privacidad o al límite del producto, y especialmente las que se probaron y se revirtieron. Cada entrada ofrece la **Decisión**, su **Contexto**, la **Justificación** y un **Estado** extraído de la leyenda de estados del proyecto (Adoptada / Revertida / Reemplazada / Propuesta).
>
> **El código manda.** Cuando un plan y el código entregado discrepan, este registro sigue al código y señala la divergencia en línea.

**Leyenda de estados (mapeada a los carriles de estado del conjunto de documentos):**

| Estado aquí | Significado del carril del conjunto de documentos |
|---|---|
| **Adoptada** | Implementada — entregada y confirmada en el código |
| **Revertida** | Descartada — construida y luego eliminada/revertida |
| **Reemplazada** | Una decisión anterior sustituida por una posterior |
| **Propuesta** | Planificada — diseñada, recomendada o registrada, pero aún no aplicada en este árbol |

Lectura relacionada: el modelo de distribución del catálogo en [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) y [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); el comportamiento entregado en [`../product/features.md`](../product/features.md). La dirección a futuro vive en la hoja de ruta interna.

---

## 1. Filtrado de DNS en el dispositivo mediante `NEPacketTunnelProvider`

**Decisión.** Filtrar DNS **localmente en el dispositivo** a través de un túnel de paquetes `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), en lugar de `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` o un bloqueador de contenido de Safari.

**Contexto.** El producto es un filtro centrado en la privacidad para usuarios no técnicos (padres, adultos mayores) que se distribuye a través de la App Store de consumo, sin requerir cuenta. Los proveedores de NetworkExtension competidores y las API de DNS gestionado están restringidos a dispositivos supervisados/gestionados por MDM o no cubren todo el DNS de una app, y un modelo del lado del resolvedor enrutaría el flujo de dominios del usuario fuera del dispositivo.

**Justificación.** El túnel de paquetes es el único proveedor que (a) funciona para dispositivos de consumo no gestionados y (b) permite que cada decisión de DNS ocurra en el dispositivo, lo cual es la base de la promesa de privacidad: *todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas.* La contrapartida aceptada a cambio es el **techo de memoria de ~50 MiB por extensión** de iOS bajo el que debe vivir el túnel — una restricción que da forma a varias de las decisiones posteriores a continuación.

**Estado.** **Adoptada** (fundacional; en el código desde el prototipo inicial).

---

## 2. Distribución de listas de bloqueo solo por URL de origen

**Decisión.** Lava publica únicamente la **URL** de la lista de bloqueo upstream **más los hashes aceptados**; el dispositivo descarga los **bytes** de la lista directamente desde cada `source_url`, luego los analiza, normaliza, deduplica y filtra localmente. Lava **nunca** almacena, replica, transforma ni sirve bytes de listas de bloqueo de terceros. El Worker escribe en R2 únicamente los **metadatos** del catálogo en JSON (`raw_r2_key`/`normalized_r2_key` son null).

**Contexto.** El diseño anterior replicaba los bytes crudos de las listas de bloqueo en R2 para que los abogados pudieran revisar la distribución. Muchas listas upstream (HaGeZi, OISD) son GPL-3.0, por lo que alojar sus bytes convertiría a Lava en un redistribuidor de datos GPL.

**Justificación.** Tratar a Lava como un motor de filtrado local / agente de usuario — en lugar de un distribuidor de listas de bloqueo — minimiza la redistribución GPLv3 y la exposición ante App Review. El dispositivo descarga cada lista por TLS directamente desde su `source_url` curada y la analiza localmente bajo límites estrictos de tamaño/reglas; las listas comunitarias se aceptan tal como se sirven (los `accepted_source_hashes` del catálogo son orientativos, no una barrera estricta — un único hash fijado no puede seguir el ritmo de un upstream que rota rápido y solo producía rechazos falsos), mientras que el nivel de barrera contra amenazas de Lava se mantiene fijado por hash. La procedencia se aplica en el catálogo (un cambio de `source_url` debe usar un nuevo `list_id`), no mediante una barrera de hash del cliente. Cada conjunto de reglas analizado también se pasa por un filtro de dominios protegidos para que una lista upstream no pueda bloquear dominios de Lava/Apple/proveedores de identidad. El modelo se aplica en CI mediante `check-gpl-blocklist-distribution.sh` (sin código de réplica, sin URL de artefactos alojados por Lava, sin fuentes GPL habilitadas por defecto, sin escrituras de bytes en R2).

**Estado.** **Adoptada**, y **Reemplazó** el abandonado plan de réplica cruda en R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, encabezado "Superseded by the source-url-only implementation"). Ver [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Transportes de resolvedor cifrados (DoH / DoH3 / DoT / DoQ)

**Decisión.** Distribuir cuatro transportes upstream cifrados junto con DNS en claro y un respaldo a DNS del dispositivo, extraídos en LavaSecCore: **DoH** (URLSession), **DoH3** (DoH que prefiere HTTP/3), **DoT** (`NWConnection`s agrupadas, hasta 4 por endpoint, con refresco por obsolescencia inactiva y un reintento con conexión nueva) y **DoQ** (DNS sobre QUIC). El enrutamiento, la degradación a DNS en claro, el failover por endpoint con una barrera de backoff y el respaldo a DNS del dispositivo viven en `ResolverOrchestrator`.

**Contexto.** Reenviar consultas no bloqueadas en texto claro a un resolvedor filtra justamente el flujo de dominios que el modelo en el dispositivo está pensado para proteger. Los transportes se construyeron de forma incremental (DoH → DoH3 → DoT → DoQ).

**Justificación.** El transporte upstream cifrado mantiene privadas las consultas no bloqueadas de extremo a extremo. **DoH3** se etiqueta de forma puramente observacional — se establece `assumesHTTP3Capable=true` y se observa el protocolo negociado, y la interfaz anota `DoH3` (sin barra) **solo cuando se observa realmente una negociación h3**, nunca se promete, porque h3 es de mejor esfuerzo por conexión y una afirmación fija sobreestimaría el comportamiento detrás de cortafuegos que bloquean UDP. La agrupación de DoT con refresco por inactividad fue una corrección directa para el cierre silencioso de Cloudflare de conexiones DoT inactivas.

**Estado.** **Adoptada** (los cuatro transportes presentes y conectados).

---

## 4. Reutilización de conexiones DoQ — construida, probada en dispositivo, revertida

**Decisión.** **No** reutilizar conexiones QUIC para DoQ. `DoQTransport` abre una **conexión QUIC nueva por consulta**; el grupo de 4 carriles proporciona concurrencia, no reutilización de handshake.

**Contexto.** RFC 9250 mapea cada consulta DNS a su propio flujo QUIC, por lo que una reutilización real necesita la API multiflujo `NWConnectionGroup`/`openStream` que es **solo iOS 26.0+**, mientras que el piso de despliegue es iOS 17. No obstante, se implementó una ruta de reutilización limitada a iOS 26 (compilada en Debug+Release contra el SDK de Xcode 26) y se **probó en dispositivo con iOS 26.5** contra DoQ de AdGuard.

**Justificación.** La ruta de reutilización falló en cada intento en el dispositivo (`openStream`/`receive` dieron error, luego el respaldo encontró "Socket is not connected"), midiendo **netamente peor** que la línea base por consulta (control: 34 handshakes / 35 consultas, todas con éxito). Esto confirmó empíricamente la guía de Apple DTS de "esperar con QUIC con el nuevo Network framework", por lo que el trabajo se revirtió en lugar de entregarse; solo la documentación y la justificación de la prueba de barrera conservan el hallazgo para que no se vuelva a intentar antes de que la API madure.

**Estado.** **Revertida** (diferida hasta que el piso de despliegue alcance iOS 26). Describir DoQ como conexiones nuevas por consulta.

---

## 5. Rechazar un protocolo unificador `DNSResolvingTransport`

**Decisión.** **No** unificar los transportes del resolvedor bajo un único protocolo `DNSResolvingTransport`; mantener la costura basada en clausuras `ResolverOrchestrator.Executors`.

**Contexto.** Una refactorización (issue 407) propuso un protocolo único sobre todos los transportes.

**Justificación.** Los transportes son demasiado disímiles — ejecutores cifrados asíncronos (DoH/DoT/DoQ) frente a transportes síncronos en claro/del dispositivo con múltiples direcciones — por lo que un protocolo unificador sería una peor abstracción que la actual costura de clausuras inyectables, que ya mantiene comprobable la ejecución sobre el cable.

**Estado.** **Revertida** / no se implementará (cerrada como una mala abstracción).

---

## 6. Respaldo cifrado de conocimiento cero (sin contraseña, con excepción de passkey señalada)

**Decisión.** Respaldar una carga útil de ajustes **minimizada** del lado del cliente: AES-256-GCM la sella bajo una clave de carga útil aleatoria de 32 bytes, que se envuelve en **ranuras de clave** por secreto mediante PBKDF2-HMAC-SHA256 (**210.000** iteraciones en producción). Solo el texto cifrado más los metadatos no secretos se suben a la tabla `user_backups` de Supabase (RLS por usuario). El flujo entregado es **sin contraseña**: ranura de secreto del dispositivo (Keychain local del dispositivo) + ranura de recuperación asistida + ranura opcional de passkey.

**Contexto.** El inicio de sesión opcional con cuenta (solo Apple + Google) habilita la restauración de ajustes entre dispositivos. El servidor nunca debe poder leer las listas de bloqueo, listas de permitidos, elección de resolvedor u otros ajustes de un usuario.

**Justificación.** El texto plano y los secretos de descifrado existen solo en el dispositivo; el servidor guarda un sobre opaco por usuario. La recuperación asistida es deliberadamente de dos factores — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (entrada delimitada por NUL) requiere **tanto** la porción en poder del servidor **como** la frase de recuperación de 8 palabras del usuario (~105 bits), de modo que ninguna mitad por sí sola descifra. El material de desbloqueo se almacena local en el dispositivo (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **no** en el Keychain de iCloud sincronizable — un endurecimiento de privacidad que revirtió el diseño sincronizable del plan original. La **ranura de passkey también es genuinamente de conocimiento cero**: se envuelve con una salida de autenticador WebAuthn **PRF / `hmac-secret`** (derivada con HKDF-SHA256) que nunca sale del cliente, de modo que ningún valor en poder del servidor puede desenvolverla. No hay tabla de passkey con rol de servicio ni barrera de aserción WebAuthn en el Worker — el diseño anterior de passkey con barrera en el servidor se descartó, eliminando todo el estado de passkey del lado del servidor (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Estado.** **Adoptada** (modelo sin contraseña, recuperación asistida y una ranura de passkey de conocimiento cero derivada de PRF, todo en el código). Hacer de la passkey un factor recuperable totalmente listo para producción en dispositivos físicos (Associated Domains / alojamiento de AASA para el modelo PRF) está **Propuesta** (backlog).

---

## 7. Connect-On-Demand a prueba de fallos cerrados

**Decisión.** Añadir una regla `NEOnDemandRuleConnect` para que un túnel detenido por el SO se reinicie automáticamente, con **fail-closed** como el valor seguro por defecto: cuando no hay una instantánea de filtro reutilizable, el túnel bloquea todo el tráfico en lugar de dejarlo pasar sin filtrar. On-demand se **deshabilita antes de cualquier detención** para que la VPN siga pudiéndose apagar.

**Contexto.** iOS estaba deteniendo silenciosamente el túnel (razón 17) sin que nada lo reiniciara durante ~45 minutos, dejando a los usuarios desprotegidos. Habilitar on-demand de forma ingenua hace imposible apagar la VPN, y un valor por defecto fail-open dejaría pasar tráfico durante el hueco.

**Justificación.** On-demand cierra el hueco de detención silenciosa; deshabilitar-antes-de-detener preserva la capacidad del usuario de apagar la protección; fail-closed garantiza que el hueco sea seguro en lugar de quedar silenciosamente sin filtrar, recuperado por `reconcileTunnelSnapshotAfterLaunch`. El cambio tuvo efectos secundarios — on-demand volvía a disparar el aviso del sistema "Add VPN Configurations" durante el onboarding — lo que generó una cadena de correcciones en múltiples commits: dejar de habilitar on-demand en la instalación, condicionar el lanzamiento/restauración de protección a la finalización del onboarding, y **neutralizar una configuración heredada/huérfana eliminándola** (`removeFromPreferences`, silencioso) en lugar de guardando `on-demand=false` (`saveToPreferences` volvía a mostrar el aviso).

**Estado.** **Adoptada** (reinicio on-demand más la cadena de correcciones de onboarding/fail-closed).

---

## 8. Refactorización modular de la VPN y la disciplina de regresión de calor

**Decisión.** Reestructurar la ruta de la VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) para un encendido con caché primero, descarga en paralelo acotado y fusión de oscilaciones — tratando batería/latencia como requisitos del producto con objetivos explícitos p50/p95 y perfilado **en el dispositivo** (no en el Simulator).

**Contexto.** El encendido / refresco / pausa / reanudación eran lentos. Durante la refactorización apareció una regresión de calor (134% de CPU, energía alta, teléfono caliente). Un gran panel de agentes primero refutó la causa sospechada usando evidencia previa a la regresión; luego una captura en vivo en el dispositivo la confirmó.

**Justificación.** La causa real fue un bucle de refresco autosostenido `NEVPNStatusDidChange` — un bucle de fusión que se rearmaba para siempre (~370 eventos/s, hilo principal ~100%, `vpn-debug-log.jsonl` crecido a ~180–210 MB) después de que se reemplazara una barrera de descarte-reentrante. La corrección lee el estado del gestor en caché y acota el bucle. El propio artefacto de dispositivo antes/después del plan registra que el encendido en caliente (`action.turnOn`) bajó de **2.722 ms → 287 ms** en un iPhone 15 Pro; una revisión de oportunidades post-modular separada y posterior midió la ruta en caliente en **112 ms** (decodificación 51 + managerSetup 57) en el mismo dispositivo. El episodio fijó el estándar: las refactorizaciones estructurales se pausan hasta que una regresión de calor medida quede acotada, y los resultados térmicos/de batería del Simulator se rechazan por carecer de sentido.

**Estado.** **Adoptada** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Una revisión post-modular mantiene `PacketTunnelProvider` y `AppViewModel` como objetos-dios sobrevivientes conocidos.

---

## 9. Presupuesto de reglas de filtro en lugar de un límite por número de listas

**Decisión.** Limitar los niveles por un **presupuesto de reglas de filtro** — **Free 500K / Plus 2M** reglas de dominio compiladas — no por número de listas habilitadas. Una barrera dura del dispositivo de **~3,26M de reglas** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`) aplica a **todos** y **nunca es un muro de pago**. El blob compacto de dominios se mapea con `mmap` (`.mappedIfSafe`) para que permanezca respaldado por archivo y fuera del `phys_footprint` contabilizado por jetsam; solo las tablas de entradas decodificadas cuestan memoria residente.

**Contexto.** El límite antiguo era un **número** de listas (free 3 / pago 10). Una lista puede contener 1K o 1M de reglas, por lo que el número era un sustituto deshonesto del recurso realmente restringido — el techo de memoria de 50 MiB de NE.

**Justificación.** Las reglas se corresponden con memoria real, por lo que se permite cualquier combinación de listas que quepa. La aplicación autoritativa se ejecuta en tiempo de compilación sobre la unión deduplicada en `FilterSnapshotPreparationService` (primero la barrera del dispositivo, luego el límite del nivel); el medidor de la interfaz en tiempo de selección usa una suma por lista con un margen de techo blando de 1,10. Las configuraciones que exceden el presupuesto se rechazan de forma determinista (manteniendo la protección apagada) en lugar de dejar que el túnel sufra jetsam.

**Estado.** **Adoptada** en el código (`SubscriptionPolicy.swift`), entregada en **v1.0.0**, que **Reemplazó** el límite por número de listas. El presupuesto de reglas es ahora la barrera de nivel en vivo; los límites por dominio también se elevaron en la 1.0 (Free 25 / Plus 1.000 dominios permitidos y bloqueados). Ver [`../product/features.md`](../product/features.md).

---

## 10. Planes como markdown + sincronización unidireccional con Linear

**Decisión.** Los archivos markdown en `plans/<lane>/` son la **fuente de verdad**; la **carpeta del carril es el estado autoritativo** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Un push a `main` sincroniza los planes **de forma unidireccional** a Linear (equipo LAV), refrescando solo título/descripción tras la creación; un tramo de retorno **manual y revisado** por separado trae de vuelta el estado/prioridad/carril de Linear al frontmatter del plan.

**Contexto.** Un equipo pequeño necesita un estado de planificación agnóstico a herramientas y revisable que no pelee con un gestor de proyectos, y un bucle de agente autónomo necesita un lugar estable donde leer y escribir el estado del plan.

**Justificación.** La división de propiedad de campos mantiene los dos sistemas libres de conflictos — markdown es dueño del contenido, Linear es dueño del estado de triaje — de modo que un push nunca pisotea el triaje humano. El carril `dropped/` mantiene los planes cancelados fuera del pipeline de sincronización para que no reaparezcan (creado cuando se rechazó Allowed Exceptions Guardrails / LAV-5). El frontmatter obsoleto dentro de un plan es un error de documentación, no un estado; la carpeta manda, y donde el código muestra que una funcionalidad se entregó a pesar de un frontmatter "Backlog" (p. ej. eliminación de cuenta), el código manda.

**Estado.** **Adoptada** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; carril `dropped/` en uso).

---

## 11. División del repositorio + código abierto copyleft del cliente

**Decisión.** Dividir el monorepo en repositorios por componente (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) y **liberar el código del cliente de primera parte bajo AGPL-3.0** en lugar de Apache-2.0, sobre el precedente copyleft de Mullvad/ProtonVPN.

**Contexto.** Desarrollo por componente y una liberación del código del cliente. La cuestión de la licencia es si un competidor podría bifurcar el cliente, cerrarlo y socavar el precio.

**Justificación.** El copyleft obliga a que los derivados permanezcan abiertos, evitando una bifurcación cerrada del cliente — una postura de "cliente público, backend/operaciones privados", con el backend, lo legal y las operaciones mantenidos privados. Se eligió AGPL-3.0 (en lugar de GPL-3.0 a secas) para cerrar el hueco de uso en red. La conocida tensión de distribución entre GPL y la App Store se maneja siendo Lava misma la distribuidora del binario de la App Store bajo su propio copyright.

**Estado.** **Adoptada.** La división del repositorio está **completa**: cada componente vive en su propio repositorio — el cliente público `lavasec-ios` en la etiqueta v0.4.0, más repositorios separados para Android, el sitio de marketing, backend/infraestructura, documentación y el pipeline de CI/release — y la sección "Repository layout" del `README.md` de `lavasec-ios` enumera solo los contenidos por componente de ese repositorio (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`) con la infraestructura señalada como viviendo en repositorios privados separados. El cliente se libera bajo **AGPL-3.0**: el `LICENSE` de `lavasec-ios` es la GNU Affero General Public License v3 y el `README.md` lleva el distintivo AGPL-3.0.

---

## Apéndice — otras reversiones y rechazos registrados

Estos son más pequeños pero fueron decisiones genuinas con un giro registrado; se enumeran por completitud.

| Decisión | Justificación | Estado |
|---|---|---|
| DNS personalizado gratis vs. de pago | Posicionamiento de monetización; brevemente permitido en gratis, luego devuelto a solo de pago | **Revertida** a solo de pago |
| Inicio de sesión con email/contraseña | Poseer contraseñas añade carga de restablecimiento/MFA/bloqueo/filtración/secuestro mientras que Apple + Google bastan; una recuperación que lo eludiera rompería el conocimiento cero | **Revertida** / nunca entregada (solo Apple + Google) |
| Allowed Exceptions Guardrails (LAV-5) | La precedencia de barreras se entregó mediante la renovación más simple de edición de listas de filtro; el pago nunca debe eludir la barrera de amenazas de alta confianza | **Revertida** (carril `dropped/` creado) |
| Bloqueo de promoción de ramas en TestFlight | El bloqueo inicial se reconsideró; reemplazado por un bloqueo planificado del runner posterior al código abierto | **Revertida**, reemplazada por un plan en backlog |
| Canal de control app↔extensión | `sendProviderMessage` (`NETunnelProviderSession`) es la **única ruta de control app→túnel** — lleva el estado tipado y versionado e impulsa de forma autoritativa el bucle de ejecución de la extensión. El observador anterior `CFNotificationCenter` del lado de la extensión nunca se disparaba de forma fiable en el dispositivo y fue **eliminado** (su ausencia se afirma mediante pruebas de introspección de fuente). Las notificaciones Darwin sobreviven solo en la dirección **túnel→app**, como un empujón de cambio de salud. | **Adoptada** (el mensaje de proveedor es el único control app→túnel; Darwin es solo salud túnel→app) |

> Invariante de seguridad transversal referenciado a lo largo del documento: el pago nunca elude la **barrera de amenazas** validada por hash y no permisible. La precedencia de decisiones es **barrera de amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.**
