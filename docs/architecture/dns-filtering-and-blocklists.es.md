---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Filtrado de DNS y listas de bloqueo

> Audiencia: ingenieros. Este documento describe la canalización de DNS en el dispositivo, la ruta del resolutor con transporte cifrado, el motor de decisión del filtrado y el modelo de catálogo de listas de bloqueo basado solo en la URL de origen, con las cifras exactas que el código aplica. El estado refleja la realidad confirmada por el código. Cuando un plan y el código no coinciden, **manda el código** y la divergencia se señala en línea.

Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas: el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.

Lava es **filtrado local de DNS/listas de bloqueo**, no una garantía de que se bloquee cada dominio o URL malicioso.

---

## 1. La canalización de DNS (Implementado)

El motor de filtrado/resolución se ejecuta dentro del **túnel de paquetes NE** — la extensión `NEPacketTunnelProvider` `LavaSecTunnel` (`com.lavasec.app.tunnel`), que intercepta únicamente DNS. Las direcciones del túnel son `10.255.0.2` (túnel) y `10.255.0.1` (servidor DNS). El proceso de la app nunca ve el tráfico de consultas; solo escribe los artefactos compilados en el **App Group** (`group.com.lavasec`) y avisa al túnel mediante **provider messages** de NETunnelProviderSession (no notificaciones Darwin).

Por cada consulta DNS entrante, el túnel ejecuta una **precedencia de consultas** fija en `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **el arranque (bootstrap) primero es una invariante estricta.** Una consulta que resuelve el nombre de host *propio* del resolutor configurado (el extremo DoH/DoT/DoQ) nunca debe bloquearse ni pausarse, o el túnel no podría siquiera levantar el DNS cifrado. El dispatcher toma cierres perezosos (lazy closures) para que cada paso se lea solo cuando se alcanza, preservando el cortocircuito (no se lee el snapshot cuando existe una respuesta de bootstrap; no se lee la pausa durante el arranque).
- **temporary pause** reenvía hacia el upstream mientras un TTL de pausa iniciado por el usuario esté activo.
- **filter** evalúa el dominio contra el snapshot compilado y lo reenvía o sintetiza una respuesta bloqueada.

Una consulta que pasa el filtro (acción `.allow`) se entrega a la ruta del resolutor (§3). El túnel **falla cerrado** en un arranque en frío sin un snapshot reutilizable: instala un snapshot de runtime que falla cerrado y bloquea todo el tráfico en lugar de resolver sin filtrar.

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

Un dominio que no pasa la normalización se bloquea con el motivo `.invalidDomain` (a prueba de fallos). La misma precedencia se refleja en la forma binaria en disco (`CompactFilterSnapshot`). La barrera de protección frente a amenazas (threat guardrail) se sitúa por encima de la lista de permitidos local por diseño: **el pago nunca evita la barrera de protección frente a amenazas no eximibles**, y una excepción del usuario no puede desbloquear un dominio de la barrera de protección.

> Nota: en el árbol de trabajo actual `nonAllowableThreatRules` / `guardrailSources` están vacíos (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); la ranura de precedencia está cableada y se aplica, pero se entrega aún sin entradas en la barrera de protección.

### 2.2 Almacenamiento de reglas y la unidad de memoria residente

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) almacena los conjuntos `exactDomains` + `suffixDomains`. La coincidencia (`containsNormalized`) hace una búsqueda exacta más un recorrido de sufijos del padre (estilo `hasSuffix`) en el momento de la consulta: **no hay subsunción de subdominios en tiempo de compilación**. Una línea comodín válida es **una regla** y una entrada en la tabla de memoria. Esta identidad 1 línea = 1 regla es lo que hace que el recuento de reglas sea la métrica honesta de recursos (§4).

### 2.3 Formas del snapshot compilado

- **`FilterSnapshot`** — el filtro compilado en memoria: `blockRules`, `allowRules`, `nonAllowableThreatRules` y el preset del resolutor.
- **`CompactFilterSnapshot`** — la forma binaria en disco apta para mmap que el túnel lee realmente (magic `LSCFSNP1`, `fileVersion 1`). Se carga con copia cero (zero-copy) mediante mmap (§4.3).

La app escribe tanto `filter-snapshot.json` como `filter-snapshot.compact` en el App Group; el túnel decodifica el artefacto compacto. Una ruta de **reutilización en arranque en caliente** (`FilterArtifactStore`) permite que el túnel reutilice el artefacto compacto en disco sin recompilar, condicionada por una huella de identidad + un manifiesto escrito de forma atómica; la reutilización se rechaza (motivo seguro para la privacidad, solo nombre de campo) cuando cambian el transporte del resolutor, la cobertura del catálogo o las entradas del snapshot.

---

## 3. Transportes cifrados y la ruta del resolutor (Implementado)

### 3.1 Enum de transporte

Las consultas no bloqueadas se reenvían al resolutor upstream configurado. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) tiene **cinco** valores:

| Transporte | Valor crudo | Anotación mostrada en la interfaz |
|---|---|---|
| DNS del dispositivo | `device-dns` | *(ninguna — el nombre es el transporte)* |
| DNS plano | `plain-dns` | `IP` |
| DNS sobre HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS sobre TLS | `dns-over-tls` | `DoT` |
| DNS sobre QUIC | `dns-over-quic` | `DoQ` |

Los presets integrados son Google, Cloudflare, Quad9, Mullvad (cada uno en variantes IP / DoH / DoT) más DNS del dispositivo y Personalizado. Los resolutores personalizados aceptan un servidor IPv4/IPv6 plano, una URL DoH, una URL DoT (`tls://` / `dot://`), una URL DoQ (`doq://` / `quic://`) o una marca DNS `sdns://`; los nombres de usuario/contraseñas y localhost se rechazan. DoH/DoT/DoQ usan por defecto el puerto `853` para DoT/DoQ y DoH requiere una ruta.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) ejecuta DoH sobre `URLSession`. Cada solicitud opta por HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); el cargador de Apple recurre de forma nativa a H2/H1, de modo que esto nunca convierte un resolutor accesible en inaccesible. El protocolo negociado se lee desde `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

La interfaz anota **`DoH3` (sin barra)** — por ejemplo, "Quad9 (DoH3)" — **solo cuando se observa realmente una negociación h3** (`DoHHTTPVersion.dohAnnotation`); de lo contrario muestra `DoH`. DoH3 se prefiere, nunca se promete: la etiqueta es observacional y de alcance por resolutor, nunca persistida (se revirtió el arrastre de "DoH3 confirmado" entre reinicios). Las solicitudes envían POST `application/dns-message`; las respuestas se validan por tipo de contenido y longitud, y el identificador de transacción se restaura antes de la reescritura.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection`s agrupadas en un pool, **hasta 4 conexiones por extremo** (`maxConnectionsPerEndpoint = 4`), por turno rotativo (round-robin), de modo que las consultas paralelas evitan el bloqueo de cabecera de línea (head-of-line). Incluye manejo de **caducidad por inactividad** (idle-staleness): proveedores como Cloudflare cierran del lado del servidor las conexiones DoT inactivas (~10 s) sin notificar un cambio de estado, así que una conexión reutilizada que ha estado inactiva más de **8 segundos** (`reusedConnectionMaxIdleInterval = 8`) se refresca antes de enviar, y un timeout en una conexión reutilizada gana **exactamente un reintento con conexión nueva**.

### 3.4 DoQ — conexión nueva por consulta

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantiene un pool acotado de **4 carriles por extremo**, pero **cada consulta abre una conexión QUIC nueva** — un handshake completo por consulta. El pool de 4 carriles proporciona **concurrencia, no reutilización de handshake**.

**Estado de reutilización de conexión DoQ (Descartado / aplazado).** La reutilización se revisó y se midió en dispositivo (34 handshakes nuevos en 35 consultas ≈ sin reutilización), luego se implementó como una ruta `NWConnectionGroup` multi-stream condicionada a iOS 26, se probó en dispositivo contra DoQ de AdGuard y se **revirtió por ser un saldo negativo** (fallos de stream + errores de respaldo contra un servidor real). RFC 9250 asigna cada consulta a su propio stream QUIC, así que la reutilización requiere `NWConnectionGroup`/`openStream`, que es **solo iOS 26.0+**; el piso de despliegue actual es **iOS 17**. La reutilización se aplaza hasta que el piso llegue a iOS 26. El DoQ personalizado se rechaza en dispositivos que no lo admiten ("DNS over QUIC is not supported on this device").

### 3.5 Política de resolución

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) posee la política del upstream:

1. **Enrutamiento de transporte** según el transporte configurado.
2. **Degradación a DNS plano** cuando un plan cifrado no tiene extremos.
3. **Failover por extremo** con una compuerta de backoff: un extremo en backoff nunca toca el cable (resultado `backed-off`).
4. **Respaldo a DNS del dispositivo** cuando el primario no devuelve respuesta *y* el plan lo permite (la propiedad del plan es `shouldFallbackToDeviceDNS`, derivada del campo de configuración `fallbackToDeviceDNS`); el resultado se reanota como el transporte del dispositivo. La ejecución sobre el cable se inyecta detrás de ejecutores para que la política se pueda probar de forma unitaria; el estado de backoff queda fuera de la política pura.

---

## 4. Presupuesto de reglas de filtrado, techo NE y mmap

La métrica de tier que se entrega es el **presupuesto de reglas de filtrado**: el total de **reglas** de dominio compiladas que un usuario puede activar. Esto reemplazó el antiguo tope por **recuento** de listas activadas (3 gratis / 10 de pago), que era un proxy deshonesto: una lista puede ser de 1K o 1M de reglas. Hay **dos capas**: una barrera de protección del dispositivo para todos, y un límite de monetización por tier por debajo de ella.

### 4.1 Límites por tier (Implementado)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) es la fuente de verdad:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Listas de bloqueo / DNS personalizados |
|---|---|---|---|---|
| **Free** | **500,000** | 25 | 25 | No |
| **Plus** (`.paid` / `.plus`) | **2,000,000** | 1,000 | 1,000 | Sí |

El límite por tier es una frontera de monetización, **nunca un muro de pago sobre la barrera de protección del dispositivo**. **Lava Security Plus** desbloquea solo la personalización — nunca la seguridad básica, nunca la barrera de protección frente a amenazas. Las listas de bloqueo personalizadas (de pago) se obtienen directamente desde el dispositivo del usuario, se analizan y se almacenan en caché localmente, y nunca se enrutan a través de los servidores de Lava.

### 4.2 Barrera de protección de memoria del dispositivo + techo NE (Implementado)

El túnel de paquetes está sujeto al **techo de memoria de ~50 MiB por extensión** de iOS (un límite de diseño del SO por tipo de extensión para túneles de paquetes desde iOS 15, no escalado con la RAM; reside en un `com.apple.jetsamproperties.{Model}.plist` por modelo de dispositivo y puede ser menor en dispositivos antiguos). Excederlo dispara jetsam. No hay API para el techo, así que el presupuesto mantiene margen por debajo del precipicio.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) hace el cálculo, expresado en reglas de filtrado (bloqueo + permitir + barrera de protección):

| Constante | Valor |
|---|---|
| `baselineMegabytes` | 4.0 MB (sobrecarga fija del proceso, medida ≈3.5 MB, redondeada hacia arriba) |
| `estimatedBytesPerRule` | 9.0 B residentes sucios (dirty) por regla (medida ≈8.5 B, redondeada hacia arriba) |
| `maxResidentMegabytes` | 32.0 MB (techo objetivo, dejando ~10 MB de holgura bajo el precipicio de jetsam observado de ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 reglas** |

Esta **barrera de protección del dispositivo de ~3.26M de reglas** es el piso de seguridad estricto para *cada* usuario, situado por encima de cualquier tier de suscripción, y **nunca es un muro de pago**. Medición de referencia (dispositivo "chimmy", 2026-06-13): **789,831 reglas → 9.9 MB de `phys_footprint`**, es decir, ≈ baseline + coste por regla.

### 4.3 Estrategia mmap (Implementado)

El snapshot compacto se carga con `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), y `CompactBinaryReader` devuelve segmentos con copia cero. El blob de texto de dominios de varios megabytes permanece **respaldado en archivo/limpio** y se excluye del `phys_footprint` contado por jetsam; solo las tablas `[Entry]` decodificadas cuestan memoria residente (~6 B/regla en disco, ~8.5 B residentes sucios). Esto eleva el techo de dominios en el dispositivo: el coste residente son las tablas de entradas, no el artefacto completo.

### 4.4 Aplicación de dos capas (Implementado)

- **Autoritativa (en tiempo de compilación).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) aplica el presupuesto sobre la **unión deduplicada** de todas las listas activadas. La barrera de protección del dispositivo se comprueba **primero** (el piso estricto); el límite por tier vincula por debajo de ella. Las configuraciones que exceden el presupuesto se rechazan de forma determinista — `exceedsDeviceMemoryBudget` o `exceedsTierFilterRuleLimit` — en lugar de dejar que el túnel sufra jetsam. El error nombra las dos listas que más contribuyen para que la solución sea obvia.
- **Indicativa (interfaz en tiempo de selección).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) impulsa el medidor de selección usando una **suma** por lista con un **margen de techo flexible de 1.10** que compensa el sobreconteo entre listas de ~7–10% (la suma por lista sobreestima la unión deduplicada).

### 4.5 El analizador (Implementado)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) cuenta reglas de forma literal: descarta comentarios/líneas en blanco/líneas inválidas, normaliza, deduplica cadenas exactas dentro de una lista (mediante un `Set`) y limita en **`maxRules = 1,000,000`** por lista (por defecto), con una longitud máxima de línea de 4,096 caracteres. Formatos admitidos: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (auto prueba hosts → dnsmasq → adblock → plain). Una línea válida = una regla = la unidad de memoria.

> **Líneas `hosts` multi-host (versión 2 de las reglas del analizador).** Una línea `hosts` que asigna una IP a varios hosts (`0.0.0.0 a.com b.com c.com`) ahora emite **cada** host como su propia regla, no solo el primero; `maxRules` se aplica **por regla** (no por línea), de modo que una línea multi-host cerca del tope no pueda excederlo. Como los mismos bytes upstream pueden ahora producir más reglas, la versión de reglas del analizador se subió **1 → 2**, invalidando entradas obsoletas de `RuleSetCache` analizadas bajo el comportamiento anterior de solo el primer host.

### 4.6 Robustez de descarga y decodificación (Implementado)

El túnel y la sincronización del catálogo se ejecutan dentro del presupuesto de memoria de NE, así que la ingesta de listas está endurecida contra entradas hostiles o malformadas:

- **Descargas en streaming.** `defaultDataFetcher` descarga los bytes de la lista a un archivo temporal mediante `URLSession.download` (memoria pico acotada) con una comprobación de tamaño posterior a la descarga (`maximumBlocklistBytes`) en lugar de almacenar el cuerpo completo en RAM; un cuerpo de tamaño excesivo lanza `BlocklistDownloadSizeLimitExceeded`.
- **Tope de metadatos del catálogo (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes` rechaza un catálogo remoto de tamaño excesivo antes de decodificar, de modo que un host hostil/MITM no pueda forzar una decodificación JSON con agotamiento de memoria (OOM) en la extensión.
- **Decodificación UTF-8 tolerante.** Un único byte UTF-8 inválido ya no rechaza una lista entera (lo que, bajo el modo de fallo cerrado, bloquearía todo el DNS); los bytes inválidos se convierten en U+FFFD y solo la línea infractora falla la validación por línea y se descarta.
- **Errores nombrados de lista de bloqueo personalizada.** Una lista personalizada fallida ahora muestra `customBlocklistUnavailable(displayName:reason:)` — "No se pudo cargar la lista de bloqueo personalizada '<name>'. <why>" — en lugar de un `URLError` crudo; la cancelación se propaga como cancelación, no como fallo de descarga.

---

## 5. Catálogo de listas de bloqueo y fuentes por defecto

### 5.1 Modelo de catálogo (Implementado)

El **catálogo de listas de bloqueo** es la lista publicada de fuentes disponibles. El **Worker de lavasec-api** sirve metadatos JSON desde un bucket de R2 en `GET /v1/catalog` (y `/v1/catalog/:version`); el dispositivo obtiene los **bytes** reales de la lista directamente desde cada `source_url` upstream. Los extremos del catálogo de iOS son `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

En el dispositivo, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Obtiene los bytes de la lista directamente desde `source.sourceURL`, aplicando un tope de tamaño.
2. Calcula SHA-256 y acepta los bytes solo si la suma de verificación está en los `accepted_source_hashes` del catálogo.
3. Ante una discrepancia, recurre a la última caché local correcta, o **falla cerrado** (`checksumMismatch`) — a menos que la fuente permita explícitamente la rotación directa desde el upstream.
4. Analiza/normaliza/deduplica localmente.
5. Filtra cada conjunto de reglas analizado a través de `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`), de modo que una lista upstream nunca pueda bloquear dominios de Lava/Apple/proveedor de identidad.

El **conjunto de dominios protegidos** (filtrados antes de la activación): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (todos por coincidencia de sufijo). El Worker aplica un filtro `PROTECTED_SUFFIXES` equivalente al calcular los metadatos; el dispositivo revalida de todos modos.

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

`guardrailSources` está vacío. Las fuentes GPL (HaGeZi, OISD) son visibles en el catálogo pero están **opcionales / DESACTIVADAS por defecto** a la espera de la aprobación de los asesores legales; el Worker restringe la sincronización/publicación de lanzamiento a `source_url_only` más los prefijos GPL permitidos (`hagezi-`/`oisd-`).

### 5.3 Listas activadas por defecto para usuarios gratuitos (Implementado)

La configuración real por defecto para usuarios gratuitos es `OnboardingDefaults.lavaRecommendedDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`), que activa **Block List Project Phishing + Block List Project Scam**, con el preset de resolutor DNS del dispositivo (`resolverPresetID = DNSResolverPreset.device.id`) y el respaldo a DNS del dispositivo activado.

Ese valor por defecto gratuito lo **produce `defaultEnabled`**, no está codificado de forma fija. `blockListProjectPhishing` (`BlocklistModels.swift:139`) y `blockListProjectScam` (`BlocklistModels.swift:148`) ambos establecen `defaultEnabled: true`, y `DefaultCatalog.recommendedDefaultSourceIDs` (`BlocklistModels.swift:250-252`) se deriva de `curatedSources.filter(\.defaultEnabled)`. El comentario en el código fuente (`BlocklistModels.swift:246-249`) llama a `defaultEnabled` "la única fuente de verdad para el valor por defecto de instalación nueva", reflejando la columna `default_enabled` del catálogo del backend. Fluyendo a través de `recommendedDefaultSourceIDs` hacia `OnboardingDefaults`, `defaultEnabled` es el mecanismo en vivo — activa la bandera en una fuente para cambiar el valor por defecto.

> **Fuente de verdad del valor por defecto (manda el código).** Cualquier texto del plan/catálogo que diga "Block List Basic es el único valor por defecto" es incorrecto para el dispositivo; el dispositivo entrega Phishing + Scam a partir de `defaultEnabled: true`, y la bandera `BlocklistSource.defaultEnabled` de iOS es el mecanismo en vivo autoritativo. La columna `default_enabled` del catálogo del backend se realineó al mismo conjunto Phishing + Scam mediante una migración, de modo que los metadatos servidos por `/v1/catalog` ahora coinciden con el cliente. El texto del sitio público "Listas de bloqueo activadas 3 → 10" sigue **desactualizado** — la puerta real es el presupuesto de reglas de filtrado de 500K/2M, no un recuento de listas.

### 5.4 Modelo de distribución GPL basado solo en la URL de origen (Implementado)

**Solo URL de origen** (source-url-only) es el modelo de distribución conforme con GPL/propiedad intelectual: Lava publica únicamente la URL upstream + los hashes aceptados; el dispositivo obtiene y analiza las listas por sí mismo. Lava **nunca** almacena, replica (mirror), transforma ni sirve bytes de listas de bloqueo de terceros. Esto **reemplazó el diseño abandonado de réplica en R2** (el plan original de "réplica cruda en R2" se revirtió el 2026-05-25).

Del lado del Worker, `syncOneBlocklist` obtiene cada fuente upstream y la normaliza+hashea (calculando `source_hash`, `normalized_hash`, `entry_count`) pero escribe `raw_r2_key = null` / `normalized_r2_key = null` — solo los metadatos JSON del catálogo llegan a R2. `check-gpl-blocklist-distribution.sh` es la salvaguarda de CI que aplica todo el modelo: sin código de réplica/transformación, sin URLs de artefacto/descarga de Lava, sin fuentes GPL activadas por defecto, sin escrituras de bytes de listas en R2 por el Worker, sin texto de "réplica alojada por Lava", sin `.txt`/`.json` GPL empaquetados, y `source_url_only` requerido en las migraciones + documentos legales.

> **Nota de licencia:** el código propio de Lava se entrega bajo **AGPL-3.0** (el archivo `LICENSE` es GNU AGPL v3, coincidiendo con la insignia del README). Las listas de bloqueo de terceros (HaGeZi, OISD) siguen siendo **GPL-3.0** bajo sus propias licencias upstream — el modelo de solo URL de origen existe precisamente para que Lava pueda usarlas sin redistribuir jamás bytes con licencia GPL. GPL-3.0 aquí es una propiedad de las listas upstream, no de la app de Lava.

---

## 6. Resumen de estado

| Área | Estado |
|---|---|
| Precedencia de consultas DNS (bootstrap > pause > filter) | Implementado |
| Precedencia de decisión del filtrado (guardrail > allowlist > blocklist > default-allow) | Implementado |
| Ranura de precedencia de la barrera de protección frente a amenazas (cableada; se entrega aún sin entradas) | Implementado |
| DoH / DoH3 (etiqueta h3 observacional) | Implementado |
| DoT (pool de 4/extremo, refresco por inactividad de 8 s, un reintento nuevo) | Implementado |
| DoQ (conexión nueva por consulta, concurrencia de 4 carriles) | Implementado |
| Reutilización de conexión DoQ | Descartado / aplazado al piso de iOS 26 |
| Degradación del resolutor + failover por extremo + respaldo a DNS del dispositivo | Implementado |
| Presupuesto de reglas de filtrado (Free 500K / Plus 2M) | Implementado |
| Barrera de protección del dispositivo de ~3.26M de reglas (objetivo de 32 MB bajo el techo NE de 50 MiB) | Implementado |
| mmap con copia cero del snapshot compacto | Implementado |
| Catálogo basado solo en la URL de origen + obtención directa del upstream + validación de hash | Implementado |
| Filtro de dominios protegidos | Implementado |
| Valor por defecto gratuito = Phishing + Scam (no Basic) | Implementado (catálogo realineado para coincidir) |
| Licencia del código propio de Lava | AGPL-3.0 (`LICENSE`); las listas de terceros siguen GPL-3.0 upstream |

---

## Véase también

- [`../product/overview.md`](../product/overview.md) — resumen del producto en una línea, promesa de privacidad, pestañas.
- Tiers y monetización (referencia interna) — Lava Security Plus y el presupuesto de reglas de filtrado como métrica del tier.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — la decisión de cumplimiento basada solo en la URL de origen.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licencias y atribuciones de listas de bloqueo/resolutores upstream.
