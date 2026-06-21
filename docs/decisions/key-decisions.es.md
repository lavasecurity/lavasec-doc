---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Decisiones de diseño clave

> Audiencia: ingeniería y dirección. Este es el registro estilo ADR de las decisiones de diseño estructurales detrás de Lava Security: las que dieron forma a la arquitectura, a la promesa de privacidad o al límite del producto, y especialmente las que se probaron y se revirtieron. Cada entrada indica la **Decisión**, su **Contexto**, la **Justificación** y un **Estado** tomado de la leyenda de estados del proyecto (Adoptada / Revertida / Reemplazada / Propuesta).
>
> **El código manda.** Cuando un plan y el código publicado no coinciden, este registro sigue al código y señala la divergencia en línea.

**Leyenda de estados (asignada a los carriles de estado del conjunto de documentos):**

| Estado aquí | Significado del carril del conjunto de documentos |
|---|---|
| **Adoptada** | Implementada — publicada y confirmada en el código |
| **Revertida** | Descartada — construida y luego eliminada/revertida |
| **Reemplazada** | Una decisión anterior sustituida por una posterior |
| **Propuesta** | Planificada — diseñada, recomendada o registrada, pero aún no aplicada en este árbol |

Lecturas relacionadas: modelo de distribución del catálogo en [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) y [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); comportamiento publicado en [`../product/features.md`](../product/features.md). La dirección a futuro vive en la hoja de ruta interna.

---

## 1. Filtrado de DNS en el dispositivo mediante `NEPacketTunnelProvider`

**Decisión.** Filtrar el DNS **localmente en el dispositivo** a través de un túnel de paquetes `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), en lugar de `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` o un bloqueador de contenido de Safari.

**Contexto.** El producto es un filtro centrado en la privacidad para usuarios no técnicos (madres y padres, personas mayores) que se distribuye a través de la App Store de consumo, sin necesidad de cuenta. Los proveedores de NetworkExtension de la competencia y las API de DNS gestionado están restringidos a dispositivos supervisados/administrados por MDM o no cubren todo el DNS de una app, y un modelo del lado del resolutor enviaría el flujo de dominios del usuario fuera del dispositivo.

**Justificación.** El túnel de paquetes es el único proveedor que (a) funciona en dispositivos de consumo no administrados y (b) permite que cada decisión de DNS ocurra en el dispositivo, que es la base de la promesa de privacidad: *todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas.* La contrapartida que se acepta a cambio es el **límite de memoria de iOS de ~50 MiB por extensión** bajo el cual debe vivir el túnel, una restricción que da forma a varias de las decisiones posteriores que figuran más abajo.

**Estado.** **Adoptada** (fundacional; en el código desde el prototipo inicial).

---

## 2. Distribución de la lista de bloqueo solo por URL de origen

**Decisión.** Lava publica únicamente la **URL** de la lista de bloqueo original **más los hashes aceptados**; el dispositivo descarga los **bytes** de la lista directamente desde cada `source_url`, y luego los analiza, normaliza, deduplica y filtra localmente. Lava **nunca** almacena, replica, transforma ni sirve los bytes de listas de bloqueo de terceros. El Worker escribe en R2 solo los **metadatos** del catálogo en JSON (`raw_r2_key`/`normalized_r2_key` son null).

**Contexto.** El diseño anterior replicaba los bytes en bruto de las listas de bloqueo en R2 para que el asesoramiento legal pudiera revisar la distribución. Muchas listas originales (HaGeZi, OISD) son GPL-3.0, por lo que alojar sus bytes convertiría a Lava en un redistribuidor de datos GPL.

**Justificación.** Tratar a Lava como un motor de filtrado local / agente de usuario, en lugar de un distribuidor de listas de bloqueo, minimiza la redistribución bajo GPLv3 y la exposición ante la revisión de la App Store. El dispositivo valida los bytes descargados contra los `accepted_source_hashes` del catálogo y recurre a la última caché válida o falla de forma cerrada ante una discordancia, recuperando la propiedad de seguridad que aportaba la canalización de replicación. Cada conjunto de reglas analizado también pasa por un filtro de dominios protegidos para que una lista original no pueda bloquear los dominios de Lava/Apple/proveedor de identidad. El modelo se aplica en la CI mediante `check-gpl-blocklist-distribution.sh` (sin código de replicación, sin URL de artefactos alojados por Lava, sin fuentes GPL habilitadas por defecto, sin escrituras de bytes en R2).

**Estado.** **Adoptada**, y **Reemplazó** el plan abandonado de replicación en bruto en R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, encabezado "Superseded by the source-url-only implementation"). Consulta [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Transportes de resolutor cifrados (DoH / DoH3 / DoT / DoQ)

**Decisión.** Incluir cuatro transportes ascendentes cifrados junto con el DNS plano y un respaldo de DNS del dispositivo, extraídos a LavaSecCore: **DoH** (URLSession), **DoH3** (DoH que prefiere HTTP/3), **DoT** (`NWConnection`s agrupadas, hasta 4 por endpoint, con renovación por inactividad y un reintento de conexión nueva) y **DoQ** (DNS-over-QUIC). El enrutamiento, la degradación a DNS plano, la conmutación por error por endpoint con una compuerta de retroceso y el respaldo de DNS del dispositivo viven en `ResolverOrchestrator`.

**Contexto.** Reenviar consultas no bloqueadas en texto claro a un resolutor filtra justamente el flujo de dominios que el modelo en el dispositivo está pensado para proteger. Los transportes se construyeron de forma incremental (DoH → DoH3 → DoT → DoQ).

**Justificación.** El transporte ascendente cifrado mantiene las consultas no bloqueadas privadas de extremo a extremo. **DoH3** se etiqueta de forma puramente observacional: se establece `assumesHTTP3Capable=true` y se observa el protocolo negociado, y la interfaz anota `DoH3` (sin barra) **solo cuando realmente se observa una negociación h3**, nunca de forma anticipada, porque h3 es de mejor esfuerzo por conexión y una afirmación fija sobreestimaría el comportamiento detrás de cortafuegos que bloquean UDP. La agrupación de DoT con renovación por inactividad fue una solución directa al cierre silencioso de Cloudflare de las conexiones DoT inactivas.

**Estado.** **Adoptada** (los cuatro transportes presentes y conectados).

---

## 4. Reutilización de conexiones DoQ — construida, probada en dispositivo, revertida

**Decisión.** **No** reutilizar conexiones QUIC para DoQ. `DoQTransport` abre una **conexión QUIC nueva por consulta**; el grupo de 4 carriles aporta concurrencia, no reutilización del handshake.

**Contexto.** El RFC 9250 asigna cada consulta de DNS a su propio flujo QUIC, por lo que la verdadera reutilización requiere la API de múltiples flujos `NWConnectionGroup`/`openStream`, que es **solo iOS 26.0+**, mientras que el piso de despliegue es iOS 17. No obstante, se implementó una ruta de reutilización condicionada a iOS 26 (compilada en Debug+Release contra el SDK de Xcode 26) y se **probó en dispositivo con iOS 26.5** contra DoQ de AdGuard.

**Justificación.** La ruta de reutilización falló en cada intento en el dispositivo (`openStream`/`receive` dieron error, y luego el respaldo dio "Socket is not connected"), midiendo **netamente peor** que la línea base por consulta (control: 34 handshakes / 35 consultas, todas exitosas). Esto confirmó empíricamente la recomendación de Apple DTS de "esperar con QUIC con el nuevo Network framework", por lo que el trabajo se revirtió en lugar de publicarse; solo la documentación y la justificación de la prueba de guardia conservan el hallazgo para que no se vuelva a intentar antes de que la API madure.

**Estado.** **Revertida** (aplazada hasta que el piso de despliegue alcance iOS 26). Describir DoQ como conexiones nuevas por consulta.

---

## 5. Rechazar un protocolo unificador `DNSResolvingTransport`

**Decisión.** **No** unificar los transportes del resolutor bajo un único protocolo `DNSResolvingTransport`; mantener la costura basada en clausuras `ResolverOrchestrator.Executors`.

**Contexto.** Una refactorización (issue 407) propuso un solo protocolo para todos los transportes.

**Justificación.** Los transportes son demasiado dispares — ejecutores cifrados asíncronos (DoH/DoT/DoQ) frente a transportes planos/del dispositivo síncronos de múltiples direcciones — por lo que un protocolo unificador sería una peor abstracción que la costura de clausuras inyectables existente, que ya mantiene comprobable la ejecución sobre el cable.

**Estado.** **Revertida** / no se implementará (cerrada como una mala abstracción).

---

## 6. Copia de seguridad cifrada de conocimiento cero (sin contraseña, con la excepción de la passkey señalada)

**Decisión.** Respaldar una carga de configuración **minimizada** del lado del cliente: AES-256-GCM la sella bajo una clave de carga aleatoria de 32 bytes, que se envuelve en **ranuras de clave** por secreto mediante PBKDF2-HMAC-SHA256 (**210.000** iteraciones en producción). Solo el texto cifrado más los metadatos no secretos se suben a la tabla `user_backups` de Supabase (RLS por usuario). El flujo publicado es **sin contraseña**: ranura de secreto del dispositivo (Keychain local del dispositivo) + ranura de recuperación asistida + ranura opcional de passkey.

**Contexto.** El inicio de sesión opcional con cuenta (solo Apple + Google) habilita la restauración de la configuración entre dispositivos. El servidor nunca debe poder leer las listas de bloqueo, listas de permitidos, elección de resolutor u otras configuraciones de un usuario.

**Justificación.** El texto plano y los secretos de descifrado existen solo en el dispositivo; el servidor guarda un único sobre opaco por usuario. La recuperación asistida es deliberadamente de dos factores — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (entrada delimitada por NUL) requiere **tanto** la porción que guarda el servidor **como** la frase de recuperación de 8 palabras del usuario (~105 bits), de modo que ninguna mitad por sí sola descifra. El material de desbloqueo se almacena de forma local en el dispositivo (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **no** en el Keychain sincronizable de iCloud — un endurecimiento de privacidad que revirtió el diseño sincronizable del plan original. La **ranura de passkey también es genuinamente de conocimiento cero**: se envuelve con una salida de autenticador **PRF / `hmac-secret`** de WebAuthn (derivada con HKDF-SHA256) que nunca sale del cliente, por lo que ningún valor guardado por el servidor puede desenvolverla. No existe una tabla de passkeys con rol de servicio ni una compuerta de aserción WebAuthn en el Worker — el diseño anterior de passkey controlado por el servidor se descartó, eliminando todo estado de passkey del lado del servidor (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Estado.** **Adoptada** (modelo sin contraseña, recuperación asistida y una ranura de passkey derivada de PRF de conocimiento cero, todo en el código). Convertir la passkey en un factor recuperable plenamente listo para producción en dispositivos físicos (alojamiento de Associated Domains / AASA para el modelo PRF) está **Propuesta** (backlog).

---

## 7. Connect-On-Demand con falla cerrada

**Decisión.** Agregar una regla `NEOnDemandRuleConnect` para que un túnel detenido por el sistema operativo se reinicie automáticamente, con **falla cerrada** como valor seguro por defecto: cuando no hay una instantánea de filtro reutilizable, el túnel bloquea todo el tráfico en lugar de dejarlo pasar sin filtrar. La función bajo demanda se **desactiva antes de cualquier detención** para que la VPN siga siendo apagable.

**Contexto.** iOS estaba deteniendo el túnel de forma silenciosa (razón 17) sin que nada lo reiniciara durante ~45 minutos, dejando a los usuarios desprotegidos. Habilitar la función bajo demanda de forma ingenua hace que la VPN sea imposible de apagar, y un valor por defecto de falla abierta dejaría pasar tráfico durante el intervalo.

**Justificación.** La función bajo demanda cierra el intervalo de detención silenciosa; desactivarla antes de detener preserva la capacidad del usuario de apagar la protección; la falla cerrada garantiza que el intervalo sea seguro en lugar de quedar sin filtrar en silencio, recuperado por `reconcileTunnelSnapshotAfterLaunch`. El cambio tuvo efectos secundarios — la función bajo demanda volvió a activar el aviso del sistema "Add VPN Configurations" durante la incorporación — lo que generó una cadena de correcciones en varios commits: dejar de habilitar la función bajo demanda en la instalación, condicionar la restauración de lanzamiento/protección a la finalización de la incorporación y **neutralizar una configuración heredada/huérfana eliminándola** (`removeFromPreferences`, en silencio) en lugar de guardar `on-demand=false` (`saveToPreferences` volvía a mostrar el aviso).

**Estado.** **Adoptada** (reinicio bajo demanda más la cadena de correcciones de incorporación/falla cerrada).

---

## 8. Refactorización modular de la VPN y la disciplina de regresión térmica

**Decisión.** Reestructurar la ruta de la VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) para un encendido que prioriza la caché, descargas en paralelo acotado y agrupación de fluctuaciones — tratando la batería/latencia como requisitos de producto con objetivos explícitos p50/p95 y perfilado **en el dispositivo** (no en el simulador).

**Contexto.** Encender / actualizar / pausar / reanudar eran lentos. Durante la refactorización apareció una regresión térmica (134% de CPU, energía alta, teléfono caliente). Un panel de agentes grande primero refutó la causa sospechada usando evidencia previa a la regresión; una captura en dispositivo en vivo luego la confirmó.

**Justificación.** La causa real era un bucle de actualización `NEVPNStatusDidChange` que se autoalimentaba — un bucle de agrupación que se rearmaba para siempre (~370 eventos/s, hilo principal ~100%, `vpn-debug-log.jsonl` crecido a ~180–210 MB) después de reemplazar una guardia de descarte de reentrada. La solución lee el estado en caché del gestor y acota el bucle. El propio artefacto de dispositivo de antes/después del plan registra que el encendido en caliente (`action.turnOn`) baja de **2.722 ms → 287 ms** en el iPhone 15 Pro; una revisión posterior y separada de oportunidades posmodular midió la ruta en caliente en **112 ms** (decode 51 + managerSetup 57) en el mismo dispositivo. El episodio estableció el estándar: las refactorizaciones estructurales se pausan hasta que una regresión térmica medida quede acotada, y los resultados térmicos/de batería del simulador se rechazan por carecer de significado.

**Estado.** **Adoptada** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Una revisión posmodular mantiene `PacketTunnelProvider` y `AppViewModel` como conocidos objetos-dios sobrevivientes.

---

## 9. Presupuesto de reglas de filtrado en lugar de un tope por número de listas

**Decisión.** Limitar los niveles por un **presupuesto de reglas de filtrado** — **Free 500K / Plus 2M** reglas de dominio compiladas — no por la cantidad de listas habilitadas. Una **barrera de protección del dispositivo de ~3,26M de reglas** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`) se aplica a **todos** y **nunca es un muro de pago**. El blob de dominios compacto se mapea con `mmap` (`.mappedIfSafe`) para que permanezca respaldado por archivo y fuera del `phys_footprint` contabilizado por jetsam; solo las tablas de entradas decodificadas consumen memoria residente.

**Contexto.** El tope antiguo era un **número** de listas (gratis 3 / pago 10). Una lista puede contener 1K o 1M de reglas, por lo que el número era un sustituto deshonesto del recurso realmente restringido — el límite de memoria de NE de 50 MiB.

**Justificación.** Las reglas se corresponden con memoria real, así que se permite cualquier combinación de listas que quepa. La aplicación autoritativa se ejecuta en tiempo de compilación sobre la unión deduplicada en `FilterSnapshotPreparationService` (primero la barrera del dispositivo, luego el límite del nivel); el medidor de la interfaz en tiempo de selección usa una suma por lista con un margen de tope blando de 1,10. Las configuraciones por encima del presupuesto se rechazan de forma determinista (manteniendo la protección apagada) en lugar de dejar que el túnel sufra jetsam.

**Estado.** **Adoptada** en el código (`SubscriptionPolicy.swift`), publicada en **v1.0.0**, que **Reemplazó** el tope por número de listas. El presupuesto de reglas es ahora la compuerta de nivel en vivo; los topes por dominio también se elevaron en la 1.0 (Free 25 / Plus 1.000 dominios permitidos y bloqueados). Consulta [`../product/features.md`](../product/features.md).

---

## 10. Planes como markdown + sincronización unidireccional con Linear

**Decisión.** Los archivos markdown en `plans/<lane>/` son la **fuente de verdad**; la **carpeta del carril es el estado autoritativo** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Un push a `main` sincroniza los planes de forma **unidireccional** con Linear (equipo LAV), refrescando solo título/descripción tras la creación; un tramo de retorno **manual y revisado** separado trae de vuelta el estado/prioridad/carril de Linear al frontmatter del plan.

**Contexto.** Un equipo pequeño necesita un estado de planificación agnóstico a la herramienta y revisable que no pelee con un gestor de proyectos, y un bucle de agente autónomo necesita un lugar estable donde leer y escribir el estado de los planes.

**Justificación.** La división de propiedad de campos mantiene los dos sistemas libres de conflictos — el markdown es dueño del contenido, Linear es dueño del estado de triage — de modo que un push nunca pisa el triage humano. El carril `dropped/` mantiene los planes cancelados fuera de la canalización de sincronización para que no reaparezcan (creado cuando se rechazaron las Barreras de Excepciones Permitidas / LAV-5). El frontmatter desactualizado dentro de un plan es un error de documentación, no un estado; la carpeta gana, y cuando el código muestra que una función se publicó a pesar de un frontmatter "Backlog" (p. ej., eliminación de cuenta), el código gana.

**Estado.** **Adoptada** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; carril `dropped/` en uso).

---

## 11. División del repositorio + apertura del cliente con copyleft

**Decisión.** Dividir el monorepo en repositorios por componente (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) y **abrir el código del cliente propio bajo AGPL-3.0** en lugar de Apache-2.0, siguiendo el precedente copyleft de Mullvad/ProtonVPN.

**Contexto.** Desarrollo por componente y una apertura del código del cliente. La cuestión de la licencia es si un competidor podría bifurcar el cliente, cerrarlo y competir en precio por debajo.

**Justificación.** El copyleft obliga a que las obras derivadas permanezcan abiertas, evitando una bifurcación cerrada del cliente — una postura de "cliente público, backend/operaciones privados", con el backend, lo legal y las operaciones mantenidos en privado. Se eligió AGPL-3.0 (en lugar de GPL-3.0 simple) para cerrar la brecha de uso en red. La conocida tensión de distribución entre GPL y la App Store se maneja siendo Lava misma la distribuidora del binario de la App Store bajo su propio derecho de autor.

**Estado.** **Adoptada.** La división del repositorio está **completa**: cada componente vive en su propio repositorio — el cliente público `lavasec-ios` en el tag v0.4.0, más repositorios separados para Android, el sitio de marketing, el backend/infraestructura, la documentación y la canalización de CI/release — y la sección "Repository layout" del `README.md` de `lavasec-ios` enumera solo los contenidos por componente de ese repositorio (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`) con la infraestructura señalada como residente en repositorios privados separados. El cliente se abre bajo **AGPL-3.0**: el `LICENSE` de `lavasec-ios` es la GNU Affero General Public License v3 y el `README.md` lleva el distintivo de AGPL-3.0.

---

## Apéndice — otras reversiones y rechazos registrados

Estos son más pequeños pero fueron decisiones genuinas con un giro registrado; se enumeran por completitud.

| Decisión | Justificación | Estado |
|---|---|---|
| DNS personalizado gratis vs. de pago | Posicionamiento de monetización; brevemente permitido en gratis, luego se volvió a solo de pago | **Revertida** a solo de pago |
| Inicio de sesión con correo/contraseña | Gestionar contraseñas añade la carga de restablecimiento/MFA/bloqueos/filtraciones/secuestros mientras que Apple + Google bastan; una recuperación de respaldo rompería el conocimiento cero | **Revertida** / nunca publicada (solo Apple + Google) |
| Barreras de Excepciones Permitidas (LAV-5) | La precedencia de barreras se publicó mediante la renovación más simple de edición de listas de filtrado; el pago nunca debe saltarse la barrera de amenazas de alta confianza | **Revertida** (carril `dropped/` creado) |
| Bloqueo de promoción de ramas en TestFlight | El bloqueo inicial se reconsideró; reemplazado por un bloqueo del runner planificado tras la apertura del código | **Revertida**, reemplazada por un plan en backlog |
| Canal de control app↔extensión | `sendProviderMessage` (`NETunnelProviderSession`) es la **única ruta de control app→túnel** — lleva el estado tipado y versionado y dirige de forma autoritativa el bucle de ejecución de la extensión. El observador `CFNotificationCenter` anterior del lado de la extensión nunca se disparó de forma fiable en el dispositivo y se **eliminó** (afirmado ausente por pruebas de introspección de fuente). Las notificaciones de Darwin sobreviven solo en la dirección **túnel→app**, como un aviso de cambio de estado de salud. | **Adoptada** (el mensaje de proveedor es el único control app→túnel; Darwin es salud túnel→app únicamente) |

> Invariante de seguridad transversal referenciado a lo largo del documento: el pago nunca se salta la **barrera de amenazas** no permisible y validada por hash. La precedencia de decisión es **barrera de amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.**
