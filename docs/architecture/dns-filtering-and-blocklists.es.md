---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Filtrado de DNS y listas de bloqueo

> Audiencia: ingeniería. Este documento describe la canalización de DNS en el dispositivo, la ruta del resolvedor por transporte cifrado, el motor de decisión de filtrado y el modelo de catálogo de listas de bloqueo basado únicamente en la URL de origen, con las cifras exactas que el código aplica. El estado refleja la realidad confirmada en el código. Cuando un plan y el código no coinciden, **manda el código** y la divergencia se señala en el propio texto.

Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas: el backend solo guarda los metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y los diagnósticos anonimizados que tú decides enviar.

Lava es **filtrado local de DNS y listas de bloqueo**, no una garantía de que se bloquee cada dominio o URL malicioso.

---

## 1. La canalización de DNS (Implementado)

El motor de filtrado/resolución se ejecuta dentro del **túnel de paquetes / NE**: la extensión `NEPacketTunnelProvider` `LavaSecTunnel` (`com.lavasec.app.tunnel`), que solo intercepta DNS. Las direcciones del túnel son `10.255.0.2` (túnel) y `10.255.0.1` (servidor DNS). El proceso de la app nunca ve el tráfico de consultas; solo escribe los artefactos compilados en el **App Group** (`group.com.lavasec`) y avisa al túnel mediante **mensajes de proveedor** de NETunnelProviderSession (no notificaciones de Darwin).

Para cada consulta DNS entrante, el túnel aplica una **precedencia de consulta** fija en `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap primero es un invariante estricto.** Una consulta que resuelve el nombre de host *propio* del resolvedor configurado (el extremo DoH/DoT/DoQ) nunca debe bloquearse ni pausarse, o el túnel no podría siquiera levantar el DNS cifrado. El despachador toma cierres perezosos para que cada paso se lea solo cuando se alcanza, preservando el cortocircuito (no se lee el snapshot cuando ya existe una respuesta de bootstrap; no se lee la pausa durante el bootstrap).
- **temporary pause** reenvía a la fuente upstream mientras está activo un TTL de pausa iniciado por el usuario.
- **filter** evalúa el dominio contra el snapshot compilado y lo reenvía o sintetiza una respuesta de bloqueo.

Una consulta que pasa el filtro (acción `.allow`) se entrega a la ruta del resolvedor (§3). El túnel **falla cerrado** en un arranque en frío sin un snapshot reutilizable: instala un snapshot de tiempo de ejecución a prueba de fallos que bloquea todo el tráfico en lugar de resolver sin filtrar.

---

## 2. El motor de filtrado (Implementado)

### 2.1 Precedencia de decisión

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) aplica la precedencia de seguridad canónica:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Orden | Conjunto de reglas | Resultado | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | bloquear | `.threatGuardrail` |
| 2 | `allowRules` | permitir | `.localAllowlist` |
| 3 | `blockRules` | bloquear | `.blocklist` |
| 4 | — | permitir | `.defaultAllow` |

Un dominio que no pasa la normalización se bloquea con el motivo `.invalidDomain` (a prueba de fallos). La misma precedencia se replica en el formato binario en disco (`CompactFilterSnapshot`). La barrera de protección frente a amenazas se sitúa por encima de la lista de permitidos local por diseño: **un pago nunca elude la barrera de protección frente a amenazas no permitibles**, y una excepción del usuario no puede desbloquear un dominio protegido por la barrera.

> Nota: en el árbol de trabajo actual `nonAllowableThreatRules` / `guardrailSources` están vacíos (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); el puesto de precedencia está conectado y se aplica, pero todavía se distribuye sin entradas de barrera de protección.

### 2.2 Almacenamiento de reglas y la unidad de memoria residente

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) almacena conjuntos de `exactDomains` + `suffixDomains`. La coincidencia (`containsNormalized`) hace una búsqueda exacta más un recorrido por sufijo del dominio padre (tipo `hasSuffix`) en el momento de la consulta: **no hay subsunción de subdominios en tiempo de compilación**. Una línea comodín válida es **una regla** y una entrada en la tabla de memoria. Esta identidad 1 línea = 1 regla es lo que convierte el recuento de reglas en la métrica honesta de recursos (§4).

### 2.3 Formatos del snapshot compilado

- **`FilterSnapshot`**: el filtro compilado en memoria: `blockRules`, `allowRules`, `nonAllowableThreatRules` y el preajuste del resolvedor.
- **`CompactFilterSnapshot`**: el formato binario en disco, apto para mmap, que el túnel lee realmente (magic `LSCFSNP1`, `fileVersion 1`). Se carga sin copia (zero-copy) mediante mmap (§4.3).

La app escribe tanto `filter-snapshot.json` como `filter-snapshot.compact` en el App Group; el túnel decodifica el artefacto compacto. Una ruta de **reutilización en arranque en caliente** (`FilterArtifactStore`) permite al túnel reutilizar el artefacto compacto en disco sin recompilar, condicionada a una huella de identidad + un manifiesto escrito de forma atómica; la reutilización se rechaza (de forma segura para la privacidad, indicando solo el nombre del campo) cuando cambian el transporte del resolvedor, la cobertura del catálogo o las entradas del snapshot.

---

## 3. Transportes cifrados y la ruta del resolvedor (Implementado)

### 3.1 Enum de transporte

Las consultas no bloqueadas se reenvían al resolvedor upstream configurado. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) tiene **cinco** valores:

| Transporte | Valor en bruto | Anotación mostrada en la interfaz |
|---|---|---|
| DNS del dispositivo | `device-dns` | *(ninguna; el nombre es el transporte)* |
| DNS sin cifrar | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

Los preajustes integrados son Google, Cloudflare, Quad9, Mullvad (cada uno en variantes IP / DoH / DoT) más DNS del dispositivo y Personalizado. Los resolvedores personalizados aceptan un servidor IPv4/IPv6 sin cifrar, una URL DoH, una URL DoT (`tls://` / `dot://`), una URL DoQ (`doq://` / `quic://`) o un sello DNS `sdns://`; los nombres de usuario/contraseñas y localhost se rechazan. DoH/DoT/DoQ usan por defecto el puerto `853` para DoT/DoQ y DoH requiere una ruta.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) ejecuta DoH sobre `URLSession`. Cada solicitud opta por HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); el cargador de Apple recurre de forma nativa a H2/H1, así que esto nunca deja inalcanzable a un resolvedor que sí lo era. El protocolo negociado se lee de `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

La interfaz anota **`DoH3` (sin barra)** —p. ej. "Quad9 (DoH3)"— **solo cuando se observa realmente una negociación h3** (`DoHHTTPVersion.dohAnnotation`); de lo contrario muestra `DoH`. DoH3 es preferido, nunca prometido: la etiqueta es observacional y de alcance por resolvedor, nunca se persiste (se revirtió el arrastre de "DoH3 confirmado" entre reinicios). Las solicitudes hacen POST de `application/dns-message`; las respuestas se validan por tipo de contenido y longitud, y el identificador de transacción se restaura antes de la reescritura.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection`s agrupadas, **hasta 4 conexiones por extremo** (`maxConnectionsPerEndpoint = 4`), por turno rotatorio (round-robin), de modo que las consultas en paralelo evitan el bloqueo en cabecera de línea. Incorpora un manejo de **obsolescencia por inactividad**: proveedores como Cloudflare cierran del lado del servidor las conexiones DoT inactivas (~10 s) sin exponer un cambio de estado, así que una conexión reutilizada que ha estado inactiva más de **8 segundos** (`reusedConnectionMaxIdleInterval = 8`) se refresca antes de enviar, y un tiempo de espera agotado en una conexión reutilizada gana **exactamente un reintento con una conexión nueva**.

### 3.4 DoQ: conexión nueva por consulta

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantiene un grupo acotado de **4 carriles por extremo**, pero **cada consulta abre una conexión QUIC nueva**: un protocolo de enlace completo por consulta. El grupo de 4 carriles proporciona **concurrencia, no reutilización del protocolo de enlace**.

**Estado de la reutilización de conexiones DoQ (Descartado / aplazado).** La reutilización se revisó y se midió en dispositivo (34 protocolos de enlace nuevos en 35 consultas ≈ sin reutilización), luego se implementó como una ruta `NWConnectionGroup` multistream condicionada a iOS 26, se probó en dispositivo contra DoQ de AdGuard y se **revirtió por ser un saldo negativo** (fallos de stream + errores de respaldo contra un servidor real). RFC 9250 asigna cada consulta a su propio stream QUIC, así que la reutilización requiere `NWConnectionGroup`/`openStream`, que **solo existe en iOS 26.0+**; el suelo de despliegue actual es **iOS 17**. La reutilización queda aplazada hasta que el suelo llegue a iOS 26. El DoQ personalizado se rechaza en dispositivos que no lo admiten ("DNS over QUIC is not supported on this device").

### 3.5 Política de resolución

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) es el dueño de la política upstream:

1. **Enrutamiento de transporte** según el transporte configurado.
2. **Degradación a DNS sin cifrar** cuando un plan cifrado no tiene extremos.
3. **Conmutación por error por extremo** con una puerta de retroceso (backoff): un extremo en retroceso nunca llega a la red (resultado `backed-off`).
4. **Respaldo a DNS del dispositivo** cuando el principal no devuelve respuesta *y* el plan lo permite (la propiedad del plan es `shouldFallbackToDeviceDNS`, derivada del campo de configuración `fallbackToDeviceDNS`); el resultado se reanota como el transporte del dispositivo. La ejecución de red se inyecta detrás de ejecutores para que la política sea comprobable con pruebas unitarias; el estado de retroceso queda fuera de la política pura.

---

## 4. Presupuesto de reglas de filtrado, techo de NE y mmap

La métrica de nivel que se distribuye es el **presupuesto de reglas de filtrado**: el total de **reglas** de dominio compiladas que un usuario puede activar. Esto reemplazó el antiguo límite de **recuento** de listas activadas (gratis 3 / de pago 10), que era un indicador deshonesto: una lista puede tener 1K o 1M de reglas. Hay **dos capas**: una barrera de protección de dispositivo para todos, y un límite de monetización por nivel por debajo de ella.

### 4.1 Límites por nivel (Implementado)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) es la fuente de verdad:

| Nivel | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Listas de bloqueo / DNS personalizados |
|---|---|---|---|---|
| **Gratis** | **500.000** | 10 | 10 | No |
| **Plus** (`.paid` / `.plus`) | **2.000.000** | 500 | 500 | Sí |

El límite por nivel es una frontera de monetización, **nunca un muro de pago sobre la barrera de protección del dispositivo**. **Lava Security Plus** desbloquea únicamente la personalización, nunca la seguridad básica, nunca la barrera de protección frente a amenazas. Las listas de bloqueo personalizadas (de pago) se obtienen directamente desde el dispositivo del usuario, se analizan y se almacenan en caché localmente, y nunca se hacen pasar por los servidores de Lava.

### 4.2 Barrera de memoria del dispositivo + techo de NE (Implementado)

El túnel de paquetes está sujeto al **techo de memoria de ~50 MiB por extensión** de iOS (un límite de diseño del sistema operativo por tipo de extensión para túneles de paquetes desde iOS 15, que no escala con la RAM; vive en un `com.apple.jetsamproperties.{Model}.plist` por modelo de dispositivo y puede ser menor en dispositivos antiguos). Superarlo dispara jetsam. No hay ninguna API para el techo, así que el presupuesto mantiene un margen por debajo del precipicio.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) hace el cálculo, expresado en reglas de filtrado (bloqueo + permiso + barrera de protección):

| Constante | Valor |
|---|---|
| `baselineMegabytes` | 4,0 MB (sobrecarga fija de proceso, medida ≈3,5 MB, redondeada al alza) |
| `estimatedBytesPerRule` | 9,0 B residentes sucios por regla (medidos ≈8,5 B, redondeados al alza) |
| `maxResidentMegabytes` | 32,0 MB (techo objetivo, deja ~10 MB de margen bajo el precipicio de jetsam observado de ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1.048.576) / 9 = 3.262.236 reglas** |

Esta **barrera de protección del dispositivo de ~3,26 M de reglas** es el suelo de seguridad firme para *cada* usuario, situado por encima de cualquier nivel de suscripción, y **nunca es un muro de pago**. Medición de referencia (dispositivo "chimmy", 2026-06-13): **789.831 reglas → 9,9 MB de `phys_footprint`**, es decir, ≈ base + coste por regla.

### 4.3 Estrategia de mmap (Implementado)

El snapshot compacto se carga con `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), y `CompactBinaryReader` devuelve segmentos sin copia (zero-copy). El blob de texto de dominios de varios megabytes permanece **respaldado por archivo / limpio** y se excluye del `phys_footprint` que cuenta jetsam; solo las tablas `[Entry]` decodificadas cuestan memoria residente (~6 B/regla en disco, ~8,5 B residentes sucios). Esto eleva el techo de dominios en el dispositivo: el coste residente son las tablas de entradas, no el artefacto completo.

### 4.4 Aplicación en dos capas (Implementado)

- **Autoritativa (en tiempo de compilación).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) aplica el presupuesto sobre la **unión sin duplicados** de todas las listas activadas. La barrera de protección del dispositivo se comprueba **primero** (el suelo firme); el límite por nivel obliga por debajo de ella. Las configuraciones que exceden el presupuesto se rechazan de forma determinista —`exceedsDeviceMemoryBudget` o `exceedsTierFilterRuleLimit`— en lugar de dejar que el túnel sufra jetsam. El error nombra las dos listas que más contribuyen, de modo que la solución sea evidente.
- **Orientativa (interfaz en el momento de la selección).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) alimenta el medidor de selección usando una **suma** por lista con un **margen de techo flexible de 1,10** que compensa el ~7–10 % de recuento excesivo entre listas (la suma por lista sobreestima la unión sin duplicados).

### 4.5 El analizador (Implementado)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) cuenta las reglas de forma literal: descarta comentarios/líneas en blanco/líneas no válidas, normaliza, elimina cadenas exactas duplicadas dentro de una lista (mediante un `Set`) y limita a **`maxRules = 1.000.000`** por lista (por defecto), con una longitud máxima de línea de 4.096 caracteres. Formatos admitidos: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (`auto` prueba hosts → dnsmasq → adblock → plain). Una línea válida = una regla = la unidad de memoria.

---

## 5. Catálogo de listas de bloqueo y fuentes por defecto

### 5.1 Modelo de catálogo (Implementado)

El **catálogo de listas de bloqueo** es la lista publicada de fuentes disponibles. El **Worker lavasec-api** sirve metadatos JSON desde un bucket de R2 en `GET /v1/catalog` (y `/v1/catalog/:version`); el dispositivo obtiene los **bytes** reales de la lista directamente de cada `source_url` upstream. Los extremos de catálogo de iOS son `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

En el dispositivo, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Obtiene los bytes de la lista directamente de `source.sourceURL`, aplicando un límite de tamaño.
2. Calcula SHA-256 y acepta los bytes solo si la suma de comprobación está en los `accepted_source_hashes` del catálogo.
3. Ante una discrepancia, recurre a la última caché local en buen estado o **falla cerrado** (`checksumMismatch`), a menos que la fuente permita explícitamente la rotación directa upstream.
4. Analiza/normaliza/elimina duplicados localmente.
5. Filtra cada conjunto de reglas analizado a través de `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`) para que una lista upstream nunca pueda bloquear dominios de Lava/Apple/proveedores de identidad.

El **conjunto de dominios protegidos** (filtrados antes de la activación): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (todos con coincidencia por sufijo). El Worker aplica un filtro equivalente `PROTECTED_SUFFIXES` al calcular los metadatos; el dispositivo revalida de todas formas.

### 5.2 Fuentes curadas (Implementado)

`DefaultCatalog.curatedSources` (`BlocklistModels.swift:232-243`) enumera **10** fuentes:

| Fuente | Licencia |
|---|---|
| Block List Basic | Unlicense |
| Block List Project Phishing | Unlicense |
| Block List Project Scam | Unlicense |
| Block List Project Ransomware | Unlicense |
| Phishing.Database Active Domains | MIT |
| HaGeZi Multi Light | GPL-3.0 |
| HaGeZi Multi Normal | GPL-3.0 |
| HaGeZi Multi PRO mini | GPL-3.0 |
| HaGeZi Multi PRO | GPL-3.0 |
| OISD Small | GPL-3.0 |

`guardrailSources` está vacío. Las fuentes GPL (HaGeZi, OISD) son visibles en el catálogo, pero están **desactivadas por defecto / requieren activación manual** a la espera de la aprobación de asesoría legal; el Worker restringe la sincronización/publicación de lanzamiento a `source_url_only` más los prefijos GPL permitidos (`hagezi-`/`oisd-`).

### 5.3 Listas activadas por defecto para usuarios gratuitos (Implementado)

La configuración gratuita real por defecto es `OnboardingDefaults.lavaRecommendedDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`), que activa **Block List Project Phishing + Block List Project Scam**, con el preajuste de resolvedor de DNS del dispositivo (`resolverPresetID = DNSResolverPreset.device.id`) y el respaldo a DNS del dispositivo activado.

Ese valor gratuito por defecto se **produce mediante `defaultEnabled`**, no está fijado en el código. `blockListProjectPhishing` (`BlocklistModels.swift:139`) y `blockListProjectScam` (`BlocklistModels.swift:148`) establecen ambas `defaultEnabled: true`, y `DefaultCatalog.recommendedDefaultSourceIDs` (`BlocklistModels.swift:250-252`) se deriva de `curatedSources.filter(\.defaultEnabled)`. El comentario del código fuente (`BlocklistModels.swift:246-249`) llama a `defaultEnabled` "la única fuente de verdad para el valor por defecto en una instalación nueva", reflejando la columna `default_enabled` del catálogo del backend. Fluyendo a través de `recommendedDefaultSourceIDs` hacia `OnboardingDefaults`, `defaultEnabled` es el mecanismo en vivo: cambia la marca en una fuente para cambiar el valor por defecto.

> **Fuente de verdad del valor por defecto (manda el código).** Cualquier texto de plan/catálogo que diga "Block List Basic es el único valor por defecto" es incorrecto para el dispositivo; el dispositivo distribuye Phishing + Scam a partir de `defaultEnabled: true`, y la marca `BlocklistSource.defaultEnabled` de iOS es el mecanismo en vivo autoritativo. La columna `default_enabled` del catálogo del backend se realineó al mismo conjunto Phishing + Scam mediante una migración, así que los metadatos servidos en `/v1/catalog` ahora coinciden con el cliente. El texto del sitio público "Listas de bloqueo activadas 3 → 10" sigue estando **desactualizado**: la verdadera frontera es el presupuesto de reglas de filtrado de 500K/2M, no un recuento de listas.

### 5.4 Modelo de distribución GPL basado únicamente en la URL de origen (Implementado)

**Basado únicamente en la URL de origen** (source-url-only) es el modelo de distribución conforme a GPL/propiedad intelectual: Lava publica solo la URL upstream + los hashes aceptados; el dispositivo obtiene y analiza las listas por sí mismo. Lava **nunca** almacena, replica, transforma ni sirve bytes de listas de bloqueo de terceros. Esto **reemplazó el diseño abandonado de réplica en R2** (el plan original de "réplica en bruto en R2" se revirtió el 2026-05-25).

Del lado del Worker, `syncOneBlocklist` obtiene cada fuente upstream y la normaliza + hashea (calculando `source_hash`, `normalized_hash`, `entry_count`), pero escribe `raw_r2_key = null` / `normalized_r2_key = null`: solo los metadatos JSON del catálogo llegan a R2. `check-gpl-blocklist-distribution.sh` es el guardián de CI que aplica todo el modelo: nada de código de réplica/transformación, nada de URLs de artefactos/descargas de Lava, ninguna fuente GPL activada por defecto, ninguna escritura en R2 de bytes de listas por parte del Worker, ningún texto de "réplica alojada por Lava", ningún `.txt`/`.json` GPL incluido en el paquete, y `source_url_only` requerido en las migraciones + documentos legales.

> **Nota sobre licencias:** el código propio de Lava se distribuye bajo **AGPL-3.0** (el archivo `LICENSE` es GNU AGPL v3, coincidiendo con la insignia del README). Las listas de bloqueo de terceros (HaGeZi, OISD) permanecen bajo **GPL-3.0** según sus propias licencias upstream: el modelo basado únicamente en la URL de origen existe precisamente para que Lava pueda usarlas sin redistribuir nunca bytes con licencia GPL. GPL-3.0 aquí es una propiedad de las listas upstream, no de la app de Lava.

---

## 6. Resumen de estado

| Área | Estado |
|---|---|
| Precedencia de consulta DNS (bootstrap > pausa > filtro) | Implementado |
| Precedencia de decisión de filtrado (barrera > lista de permitidos > lista de bloqueo > permitir por defecto) | Implementado |
| Puesto de precedencia de la barrera frente a amenazas (conectado; se distribuye sin entradas todavía) | Implementado |
| DoH / DoH3 (etiqueta h3 observacional) | Implementado |
| DoT (grupo de 4/extremo, refresco por 8 s de inactividad, un reintento nuevo) | Implementado |
| DoQ (conexión nueva por consulta, concurrencia de 4 carriles) | Implementado |
| Reutilización de conexiones DoQ | Descartado / aplazado al suelo de iOS 26 |
| Degradación del resolvedor + conmutación por error por extremo + respaldo a DNS del dispositivo | Implementado |
| Presupuesto de reglas de filtrado (Gratis 500K / Plus 2M) | Implementado |
| Barrera de protección del dispositivo de ~3,26 M de reglas (objetivo de 32 MB bajo el techo de NE de 50 MiB) | Implementado |
| mmap sin copia del snapshot compacto | Implementado |
| Catálogo basado únicamente en la URL de origen + obtención directa upstream + validación por hash | Implementado |
| Filtro de dominios protegidos | Implementado |
| Valor gratuito por defecto = Phishing + Scam (no Basic) | Implementado (catálogo realineado para coincidir) |
| Licencia del código propio de Lava | AGPL-3.0 (`LICENSE`); las listas de terceros siguen siendo GPL-3.0 upstream |

---

## Véase también

- [`../product/overview.md`](../product/overview.md) — resumen del producto en una línea, promesa de privacidad, pestañas.
- Niveles y monetización (referencia interna) — Lava Security Plus y el presupuesto de reglas de filtrado como métrica de nivel.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — la decisión de cumplimiento basada únicamente en la URL de origen.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licencias y atribuciones de listas de bloqueo/resolvedores upstream.
