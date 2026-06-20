---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Decisiones de diseño clave

> Audiencia: ingeniería y dirección. Este es el registro, al estilo de un ADR, de las decisiones de diseño que sostienen el producto de Lava Security: las que dieron forma a la arquitectura, a la promesa de privacidad o al alcance del producto, y en especial las que se probaron y luego se revirtieron. Cada entrada indica la **Decisión**, su **Contexto**, la **Justificación** y un **Estado** tomado de la leyenda de estados del proyecto (Adoptada / Revertida / Reemplazada / Propuesta).
>
> **Manda el código.** Cuando un plan y el código publicado no coinciden, este registro sigue al código y señala la diferencia en línea.

**Leyenda de estados (asociada a los carriles de estado del conjunto de documentos):**

| Estado aquí | Significado del carril en el conjunto de documentos |
|---|---|
| **Adoptada** | Implementada — publicada y confirmada en el código |
| **Revertida** | Descartada — construida y luego eliminada o revertida |
| **Reemplazada** | Una decisión anterior sustituida por otra posterior |
| **Propuesta** | Planificada — diseñada, recomendada o registrada, pero aún no aplicada en este árbol |

Lecturas relacionadas: el modelo de distribución del catálogo en [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) y [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); el comportamiento publicado en [`../product/features.md`](../product/features.md). La dirección a futuro está en la hoja de ruta interna.

---

## 1. Filtrado de DNS en el dispositivo mediante `NEPacketTunnelProvider`

**Decisión.** Filtrar el DNS **localmente en el dispositivo** a través de un túnel de paquetes `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), en lugar de `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` o un bloqueador de contenido de Safari.

**Contexto.** El producto es un filtro centrado en la privacidad para personas no técnicas (madres y padres, personas mayores) que se distribuye en la App Store de consumo, sin necesidad de cuenta. Los demás proveedores de NetworkExtension y las API de DNS administrado están restringidos a dispositivos supervisados o gestionados por MDM, o no cubren todo el DNS de una aplicación, y un modelo del lado del resolver enviaría el flujo de dominios del usuario fuera del dispositivo.

**Justificación.** El túnel de paquetes es el único proveedor que (a) funciona en dispositivos de consumo no gestionados y (b) permite que cada decisión de DNS ocurra en el dispositivo, que es la base de la promesa de privacidad: *todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas.* El compromiso aceptado a cambio es el **límite de memoria de iOS de ~50 MiB por extensión** bajo el que debe vivir el túnel, una restricción que da forma a varias de las decisiones posteriores.

**Estado.** **Adoptada** (fundacional; presente en el código desde el prototipo inicial).

---

## 2. Distribución de listas de bloqueo solo mediante la URL de origen

**Decisión.** Lava publica únicamente la **URL** de la lista de bloqueo original **más los hashes aceptados**; el dispositivo descarga los **bytes** de la lista directamente desde cada `source_url`, y luego los analiza, normaliza, deduplica y filtra localmente. Lava **nunca** almacena, replica, transforma ni sirve los bytes de listas de bloqueo de terceros. El Worker escribe en R2 solo los **metadatos** del catálogo en JSON (`raw_r2_key`/`normalized_r2_key` son nulos).

**Contexto.** El diseño anterior replicaba los bytes en bruto de las listas de bloqueo en R2 para que el equipo legal pudiera revisar la distribución. Muchas listas originales (HaGeZi, OISD) son GPL-3.0, así que alojar sus bytes convertiría a Lava en un redistribuidor de datos GPL.

**Justificación.** Tratar a Lava como un motor de filtrado local / agente de usuario —en lugar de un distribuidor de listas de bloqueo— reduce al mínimo la exposición a la redistribución bajo GPLv3 y a la revisión de la App Store. El dispositivo valida los bytes descargados con los `accepted_source_hashes` del catálogo y, si hay discrepancia, recurre a la última copia en caché válida o falla de forma cerrada, recuperando la propiedad de seguridad que aportaba la canalización de réplica. Cada conjunto de reglas analizado pasa además por un filtro de dominios protegidos, de modo que una lista original no pueda bloquear los dominios de Lava, Apple o de los proveedores de identidad. El modelo se hace cumplir en la CI mediante `check-gpl-blocklist-distribution.sh` (sin código de réplica, sin URL de artefactos alojados por Lava, sin fuentes GPL activadas por defecto y sin escrituras de bytes en R2).

**Estado.** **Adoptada**, y **Reemplazó** el abandonado plan de réplica en bruto en R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, con el encabezado "Superseded by the source-url-only implementation"). Véase [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Transportes de resolver cifrados (DoH / DoH3 / DoT / DoQ)

**Decisión.** Ofrecer cuatro transportes cifrados hacia el resolver junto al DNS sin cifrar y un mecanismo de respaldo con el DNS del dispositivo, extraídos a LavaSecCore: **DoH** (URLSession), **DoH3** (DoH que prefiere HTTP/3), **DoT** (conexiones `NWConnection` agrupadas, hasta 4 por extremo, con renovación por inactividad y un reintento con conexión nueva) y **DoQ** (DNS sobre QUIC). El enrutamiento, la degradación a DNS sin cifrar, la conmutación por error por extremo con una puerta de reintento progresivo y el respaldo con el DNS del dispositivo residen en `ResolverOrchestrator`.

**Contexto.** Reenviar las consultas no bloqueadas en texto plano a un resolver filtra justo el flujo de dominios que el modelo en el dispositivo busca proteger. Los transportes se construyeron de forma incremental (DoH → DoH3 → DoT → DoQ).

**Justificación.** El transporte cifrado hacia el resolver mantiene privadas de extremo a extremo las consultas no bloqueadas. **DoH3** se etiqueta de forma puramente observacional: se fija `assumesHTTP3Capable=true` y se observa el protocolo negociado, y la interfaz anota `DoH3` (sin barra) **solo cuando realmente se observa una negociación h3**, nunca como promesa, porque h3 es el mejor esfuerzo posible por conexión y una afirmación fija exageraría el comportamiento detrás de cortafuegos que bloquean UDP. La agrupación de DoT con renovación por inactividad fue una corrección directa para el cierre silencioso de conexiones DoT inactivas por parte de Cloudflare.

**Estado.** **Adoptada** (los cuatro transportes están presentes y conectados).

---

## 4. Reutilización de conexiones DoQ — construida, probada en dispositivo, revertida

**Decisión.** **No** reutilizar conexiones QUIC para DoQ. `DoQTransport` abre una **conexión QUIC nueva por cada consulta**; el grupo de 4 vías aporta concurrencia, no reutilización del intercambio inicial.

**Contexto.** El RFC 9250 asigna cada consulta DNS a su propio flujo QUIC, por lo que la verdadera reutilización requiere la API multiflujo `NWConnectionGroup`/`openStream`, que es **solo para iOS 26.0+**, mientras que el mínimo de despliegue es iOS 17. Aun así se implementó una ruta de reutilización limitada a iOS 26 (compilada en Debug y Release con el SDK de Xcode 26) y se **probó en un dispositivo con iOS 26.5** contra el DoQ de AdGuard.

**Justificación.** La ruta de reutilización falló en todos los intentos en el dispositivo (`openStream`/`receive` daban error y luego el respaldo se topaba con "Socket is not connected"), midiendo un resultado **netamente peor** que la base por consulta (control: 34 intercambios / 35 consultas, todas con éxito). Esto confirmó empíricamente la recomendación del DTS de Apple de "esperar antes de usar QUIC con el nuevo framework Network", así que el trabajo se revirtió en lugar de publicarse; solo la documentación y la justificación de la prueba de protección conservan el hallazgo para que no se vuelva a intentar antes de que la API madure.

**Estado.** **Revertida** (aplazada hasta que el mínimo de despliegue alcance iOS 26). Describir DoQ como conexiones nuevas por consulta.

---

## 5. Rechazo de un protocolo unificador `DNSResolvingTransport`

**Decisión.** **No** unificar los transportes del resolver bajo un único protocolo `DNSResolvingTransport`; conservar la juntura basada en cierres `ResolverOrchestrator.Executors`.

**Contexto.** Una refactorización (incidencia 407) propuso un solo protocolo para todos los transportes.

**Justificación.** Los transportes son demasiado dispares —ejecutores cifrados asíncronos (DoH/DoT/DoQ) frente a transportes sincrónicos de múltiples direcciones, sin cifrar y del dispositivo—, de modo que un protocolo unificador sería una abstracción peor que la juntura de cierres inyectables ya existente, que ya mantiene comprobable la ejecución sobre el cable.

**Estado.** **Revertida** / no se implementará (cerrada por ser una mala abstracción).

---

## 6. Copia de seguridad cifrada de conocimiento cero (sin contraseña, con la excepción de passkey señalada)

**Decisión.** Hacer una copia de seguridad de una carga **minimizada** de ajustes en el lado del cliente: AES-256-GCM la sella con una clave de carga aleatoria de 32 bytes, que se envuelve en **ranuras de clave** por cada secreto mediante PBKDF2-HMAC-SHA256 (**210 000** iteraciones en producción). A la tabla `user_backups` de Supabase (con RLS por usuario) solo se suben el texto cifrado y los metadatos no secretos. El flujo publicado es **sin contraseña**: ranura de secreto del dispositivo (Keychain local del dispositivo) + ranura de recuperación asistida + ranura opcional de passkey.

**Contexto.** El inicio de sesión opcional con cuenta (solo Apple + Google) permite restaurar los ajustes entre dispositivos. El servidor nunca debe poder leer las listas de bloqueo, las listas de permitidos, la elección de resolver ni otros ajustes de un usuario.

**Justificación.** Los secretos en texto plano y el descifrado existen solo en el dispositivo; el servidor guarda un único sobre opaco por usuario. La recuperación asistida es deliberadamente de dos factores —`SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (entrada delimitada por NUL) requiere **tanto** la parte que guarda el servidor **como** la frase de recuperación de 8 palabras del usuario (~105 bits), de modo que ninguna mitad por sí sola descifra. El material de desbloqueo se almacena localmente en el dispositivo (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **no** en el Keychain sincronizable de iCloud, un refuerzo de privacidad que revirtió el diseño sincronizable del plan original. La **ranura de passkey también es genuinamente de conocimiento cero**: se envuelve con una salida de autenticador **PRF / `hmac-secret`** de WebAuthn (derivada con HKDF-SHA256) que nunca sale del cliente, de modo que ningún valor en poder del servidor puede desenvolverla. No hay tabla de passkey con rol de servicio ni puerta de aserción WebAuthn en el Worker; el diseño anterior de passkey controlado por el servidor se descartó, eliminando todo el estado de passkey del lado del servidor (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Estado.** **Adoptada** (el modelo sin contraseña, la recuperación asistida y una ranura de passkey de conocimiento cero derivada de PRF, todo en el código). Convertir la passkey en un factor recuperable totalmente listo para producción en dispositivos físicos (alojamiento de Associated Domains / AASA para el modelo PRF) está **Propuesto** (pendiente en el backlog).

---

## 7. Connect-On-Demand con fallo cerrado

**Decisión.** Añadir una regla `NEOnDemandRuleConnect` para que un túnel detenido por el sistema operativo se reinicie automáticamente, con el **fallo cerrado** como valor predeterminado seguro: cuando no hay una instantánea de filtro reutilizable, el túnel bloquea todo el tráfico en lugar de dejarlo pasar sin filtrar. La regla bajo demanda se **desactiva antes de cualquier detención** para que la VPN siga pudiendo apagarse.

**Contexto.** iOS detenía el túnel de forma silenciosa (motivo 17) sin que nada lo reiniciara durante ~45 minutos, dejando a los usuarios sin protección. Activar la regla bajo demanda de forma ingenua hace imposible apagar la VPN, y un valor predeterminado de fallo abierto dejaría pasar tráfico durante el intervalo.

**Justificación.** La regla bajo demanda cierra la brecha de la detención silenciosa; desactivarla antes de detener preserva la capacidad del usuario de apagar la protección; el fallo cerrado garantiza que la brecha sea segura en lugar de quedar sin filtrar en silencio, y se recupera con `reconcileTunnelSnapshotAfterLaunch`. El cambio tuvo efectos secundarios —la regla bajo demanda volvía a activar el aviso del sistema "Añadir configuraciones de VPN" durante la configuración inicial—, lo que dio lugar a una cadena de correcciones en varios commits: dejar de activar la regla bajo demanda en la instalación, condicionar el lanzamiento y la restauración de la protección a que se complete la configuración inicial, y **neutralizar una configuración heredada o huérfana eliminándola** (`removeFromPreferences`, en silencio) en lugar de guardar `on-demand=false` (`saveToPreferences` volvía a mostrar el aviso).

**Estado.** **Adoptada** (el reinicio bajo demanda más la cadena de correcciones de configuración inicial / fallo cerrado).

---

## 8. Refactorización modular de la VPN y la disciplina de regresión de temperatura

**Decisión.** Reestructurar la ruta de la VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) para activación con caché primero, descarga con paralelismo acotado y agrupación de cambios rápidos de estado, tratando la batería y la latencia como requisitos del producto con objetivos explícitos de p50/p95 y perfilado **en el dispositivo** (no en el Simulator).

**Contexto.** Activar, refrescar, pausar y reanudar eran operaciones lentas. Durante la refactorización apareció una regresión de temperatura (134 % de CPU, energía alta, teléfono caliente). Un panel grande de agentes primero refutó la causa sospechada usando evidencia anterior a la regresión; una captura en vivo en el dispositivo la confirmó después.

**Justificación.** La causa real era un bucle de refresco autosostenido de `NEVPNStatusDidChange`, un bucle de agrupación que se rearmaba indefinidamente (~370 eventos/s, hilo principal al ~100 %, `vpn-debug-log.jsonl` crecido hasta ~180–210 MB) después de que se sustituyera una protección de reentrada por descarte. La corrección lee el estado del gestor en caché y acota el bucle. Los propios artefactos de antes/después en el dispositivo del plan registran que la activación en caliente (`action.turnOn`) bajó de **2722 ms a 287 ms** en un iPhone 15 Pro; una revisión de oportunidades posterior, ya en la etapa posmodular, midió la ruta en caliente en **112 ms** (decodificación 51 + managerSetup 57) en el mismo dispositivo. El episodio fijó el estándar: las refactorizaciones estructurales se pausan hasta que una regresión de temperatura medida quede acotada, y los resultados térmicos o de batería del Simulator se rechazan por carecer de significado.

**Estado.** **Adoptada** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Una revisión posmodular mantiene `PacketTunnelProvider` y `AppViewModel` como objetos-dios que siguen presentes y conocidos.

---

## 9. Presupuesto de reglas de filtrado en lugar de un tope por número de listas

**Decisión.** Diferenciar los planes por un **presupuesto de reglas de filtrado** —**Free 500 K / Plus 2 M** reglas de dominio compiladas— y no por el número de listas activadas. Una **barrera de protección del dispositivo de ~3,26 M de reglas** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3 262 236`) se aplica a **todos** y **nunca es un muro de pago**. El blob compacto de dominios se mapea en memoria con `mmap` (`.mappedIfSafe`) para que permanezca respaldado por archivo y fuera del `phys_footprint` que cuenta jetsam; solo las tablas de entradas decodificadas consumen memoria residente.

**Contexto.** El tope anterior era un **número** de listas (3 en Free / 10 en pago). Una lista puede contener 1 K o 1 M de reglas, así que el número era un sustituto poco honesto del recurso realmente limitado: el límite de memoria de 50 MiB de la NE.

**Justificación.** Las reglas se corresponden con memoria real, así que se permite cualquier combinación de listas que quepa. La verificación autoritativa se ejecuta en tiempo de compilación sobre la unión deduplicada en `FilterSnapshotPreparationService` (primero la barrera del dispositivo, luego el límite del plan); el medidor de la interfaz en el momento de la selección usa una suma por lista con un margen de techo flexible de 1,10. Las configuraciones que superan el presupuesto se rechazan de forma determinista (manteniendo la protección apagada) en lugar de dejar que el túnel sufra un cierre por jetsam.

**Estado.** **Adoptada** en el código (`SubscriptionPolicy.swift`), que **Reemplazó** el tope por número de listas. El plan impulsor (`plans/under_review/2026-06-13-filter-rules-budget-tier-revamp.md`) sigue en revisión y el texto del sitio público "Listas de bloqueo activadas 3 → 10" está **desactualizado**: la verdadera diferenciación es el presupuesto de reglas. Véase [`../product/features.md`](../product/features.md).

---

## 10. Planes como markdown + sincronización unidireccional con Linear

**Decisión.** Los archivos markdown en `plans/<lane>/` son la **fuente de la verdad**; la **carpeta del carril es el estado autoritativo** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Un push a `main` sincroniza los planes **en un solo sentido** hacia Linear (equipo LAV), actualizando solo título y descripción tras la creación; un tramo de retorno **manual y revisado** distinto trae el estado, la prioridad y el carril de Linear de vuelta al frontmatter del plan.

**Contexto.** Un equipo pequeño necesita un estado de planificación independiente de las herramientas y revisable, que no pelee con un gestor de proyectos, y un bucle de agente autónomo necesita un lugar estable donde leer y escribir el estado de los planes.

**Justificación.** La separación de la propiedad de los campos mantiene ambos sistemas sin conflictos —el markdown posee el contenido, Linear posee el estado de clasificación—, de modo que un push nunca pisa la clasificación hecha por personas. El carril `dropped/` mantiene los planes cancelados fuera de la canalización de sincronización para que no reaparezcan (se creó cuando se rechazó Allowed Exceptions Guardrails / LAV-5). El frontmatter desactualizado dentro de un plan es un error de documentación, no un estado; manda la carpeta, y cuando el código muestra que una función se publicó pese a un frontmatter de "Backlog" (por ejemplo, la eliminación de cuenta), manda el código.

**Estado.** **Adoptada** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; el carril `dropped/` está en uso).

---

## 11. División del repositorio + cliente de código abierto con copyleft

**Decisión.** Dividir el monorepo en repositorios por componente (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) y **publicar el cliente propio como código abierto bajo AGPL-3.0** en lugar de Apache-2.0, siguiendo el precedente de copyleft de Mullvad/ProtonVPN.

**Contexto.** Desarrollo por componente y apertura del cliente como código abierto. La cuestión de la licencia es si un competidor podría bifurcar el cliente, cerrarlo y competir a la baja en precio.

**Justificación.** El copyleft obliga a que las obras derivadas sigan siendo abiertas, lo que impide una bifurcación cerrada del cliente: una postura de "cliente público, backend/operaciones privados", con el backend, lo legal y las operaciones en privado. Se eligió AGPL-3.0 (en vez de GPL-3.0 a secas) para cerrar la brecha del uso en red. La conocida tensión entre la distribución bajo GPL y la App Store se resuelve porque la propia Lava es la distribuidora del binario de la App Store bajo su propio copyright.

**Estado.** **Adoptada.** La división del repositorio está **completa**: cada componente vive en su propio repositorio —el cliente público `lavasec-ios` en la etiqueta v0.4.0, más repositorios separados para Android, el sitio de marketing, el backend/la infraestructura, la documentación y la canalización de CI/publicación— y la sección "Repository layout" del `README.md` de `lavasec-ios` enumera solo los contenidos por componente de ese repositorio (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`), con la infraestructura indicada como residente en repositorios privados separados. El cliente es de código abierto bajo **AGPL-3.0**: la `LICENSE` de `lavasec-ios` es la GNU Affero General Public License v3 y su `README.md` muestra la insignia de AGPL-3.0.

---

## Apéndice — otras reversiones y rechazos registrados

Estos son menores, pero fueron decisiones reales con un cambio registrado; se enumeran para que la lista esté completa.

| Decisión | Justificación | Estado |
|---|---|---|
| DNS personalizado gratis frente a de pago | Posicionamiento de monetización; se permitió brevemente en el plan gratuito y luego se volvió a dejar solo en el de pago | **Revertida** a solo de pago |
| Inicio de sesión con correo/contraseña | Gestionar contraseñas añade la carga de restablecimientos, MFA, bloqueos, filtraciones y robos de cuenta, mientras que Apple + Google bastan; una recuperación de emergencia rompería el conocimiento cero | **Revertida** / nunca se publicó (solo Apple + Google) |
| Allowed Exceptions Guardrails (LAV-5) | La precedencia de las barreras de protección se publicó mediante la revisión más simple de edición de listas de filtrado; el pago nunca debe saltarse la barrera de protección frente a amenazas de alta confianza | **Revertida** (se creó el carril `dropped/`) |
| Bloqueo de promoción de ramas en TestFlight | El bloqueo inicial se reconsideró; se reemplazó por un bloqueo del runner previsto tras la apertura del código | **Revertida**, reemplazada por un plan en el backlog |
| Canal de control app↔extensión | `sendProviderMessage` (`NETunnelProviderSession`) es la **única ruta de control app→túnel**: transporta el estado tipado y con versión y dirige de forma autoritativa el bucle de ejecución de la extensión. El observador `CFNotificationCenter` anterior del lado de la extensión nunca se disparaba de forma fiable en el dispositivo y se **eliminó** (su ausencia se afirma mediante pruebas de introspección de código). Las notificaciones de Darwin sobreviven solo en el sentido **túnel→app**, como un aviso de cambio de estado de salud. | **Adoptada** (el mensaje de proveedor es el único control app→túnel; Darwin es solo salud túnel→app) |

> Invariante de seguridad transversal referenciada a lo largo del documento: el pago nunca se salta la **barrera de protección frente a amenazas**, validada por hash y no anulable. La precedencia de las decisiones es **barrera frente a amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.**
