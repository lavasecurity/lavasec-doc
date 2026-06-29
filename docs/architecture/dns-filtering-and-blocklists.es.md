---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Filtrado DNS y listas de bloqueo

> Audiencia: ingenieros. Este documento describe el flujo DNS en el dispositivo, la ruta del resolutor con transporte cifrado, el motor de decisión de filtrado y el modelo de catálogo de listas de bloqueo source-url-only — con las cifras precisas que el código impone. El estado refleja la realidad confirmada por el código. Cuando un plan y el código no coinciden, **manda el código** y la divergencia se señala en línea.

Todo el filtrado DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas — el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.

Lava es **filtrado local de DNS/listas de bloqueo**, no una garantía de que se bloquee todo dominio o URL malicioso.

---

## 1. El flujo DNS (Implementado)

El motor de filtrado/resolución corre dentro del **NE / packet tunnel** — la extensión `NEPacketTunnelProvider` `LavaSecTunnel` (`com.lavasec.app.tunnel`), que intercepta únicamente DNS. Las direcciones del túnel son `10.255.0.2` (túnel) y `10.255.0.1` (servidor DNS). El proceso de la app nunca ve el tráfico de consultas; solo escribe artefactos compilados en el **App Group** (`group.com.lavasec`) y señaliza al túnel mediante **mensajes de proveedor** de NETunnelProviderSession (no notificaciones de Darwin).

Para cada consulta DNS entrante el túnel ejecuta una **precedencia de consultas** fija en `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap-first es una invariante estricta.** Una consulta que resuelve el *propio* nombre de host del resolutor configurado (el endpoint DoH/DoT/DoQ) nunca debe bloquearse ni pausarse, o el túnel no podría siquiera levantar el DNS cifrado. El dispatcher toma clausuras perezosas para que cada paso se lea solo cuando se alcanza, preservando el cortocircuito (no se lee el snapshot cuando existe una respuesta de bootstrap; no se lee la pausa durante el bootstrap).
- **temporary pause** reenvía hacia el upstream mientras un TTL de pausa iniciada por el usuario está activo.
- **filter** evalúa el dominio contra el snapshot compilado y lo reenvía o sintetiza una respuesta bloqueada.

Una consulta que pasa el filtro (acción `.allow`) se entrega a la ruta del resolutor (§3). El túnel **falla en cerrado** en arranque en frío sin un snapshot reutilizable: instala un snapshot de runtime fail-closed que bloquea todo el tráfico en lugar de resolver sin filtrar.

---

## 2. El motor de filtrado (Implementado)

### 2.1 Precedencia de decisión

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) aplica la precedencia de seguridad canónica:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Orden | Conjunto de reglas | Resultado | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

Un dominio que falla la normalización se bloquea con la razón `.invalidDomain` (a prueba de fallos). La misma precedencia se replica en la forma binaria en disco (`CompactFilterSnapshot`). El threat guardrail se sitúa por encima de la lista de permitidos local por diseño: **el pago nunca evade el threat guardrail no-permitible**, y una excepción de usuario no puede desbloquear un dominio del guardrail.

> Nota: en el árbol de trabajo actual `nonAllowableThreatRules` / `guardrailSources` están vacíos (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); el espacio de precedencia está cableado e impuesto pero se entrega sin entradas de guardrail todavía.

### 2.2 Almacenamiento de reglas y la unidad de memoria residente

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) almacena conjuntos `exactDomains` + `suffixDomains`. La coincidencia (`containsNormalized`) hace una búsqueda exacta más un recorrido de sufijos padre (al estilo `hasSuffix`) en tiempo de consulta — **no hay subsunción de subdominios en tiempo de compilación**. Una línea wildcard válida es **una regla** y una entrada de la tabla de memoria. Esta identidad 1-línea = 1-regla es lo que hace del recuento de reglas la métrica honesta de recursos (§4).

### 2.3 Formas del snapshot compilado

- **`FilterSnapshot`** — el filtro compilado en memoria: `blockRules`, `allowRules`, `nonAllowableThreatRules` y el preset del resolutor.
- **`CompactFilterSnapshot`** — la forma binaria, apta para mmap, en disco, que el túnel realmente lee (magic `LSCFSNP1`, `fileVersion 1`). Se carga sin copia mediante mmap (§4.3).

La app escribe tanto `filter-snapshot.json` como `filter-snapshot.compact` en el App Group; el túnel decodifica el artefacto compacto. Una ruta de **reutilización en arranque en caliente** (`FilterArtifactStore`) permite al túnel reutilizar el artefacto compacto en disco sin recompilar, condicionada por una huella de identidad + un manifiesto escrito atómicamente; la reutilización se rechaza (razón segura para la privacidad, solo nombre de campo) cuando cambian el transporte del resolutor, la cobertura del catálogo o las entradas del snapshot.

---

## 3. Transportes cifrados y la ruta del resolutor (Implementado)

### 3.1 Enumeración de transporte

Las consultas no bloqueadas se reenvían al resolutor upstream configurado. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) tiene **cinco** valores:

| Transporte | Valor crudo | Anotación mostrada en la UI |
|---|---|---|
| Device DNS | `device-dns` | *(ninguna — el nombre es el transporte)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

Los presets integrados son Google, Cloudflare, Quad9, Mullvad (cada uno en variantes IP / DoH / DoT) más Device DNS y Custom. Los resolutores personalizados aceptan un servidor IPv4/IPv6 simple, una URL DoH, una URL DoT (`tls://` / `dot://`), una URL DoQ (`doq://` / `quic://`), o un sello DNS `sdns://`; se rechazan nombres de usuario/contraseñas y localhost. DoT/DoQ usan por defecto el puerto `853`; DoH requiere una ruta.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) ejecuta DoH sobre `URLSession`. Cada petición opta por HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); el cargador de Apple recae en H2/H1 de forma nativa, así que esto nunca convierte un resolutor alcanzable en inalcanzable. El protocolo negociado se lee de `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

La UI anota **`DoH3` (sin barra)** — p. ej. "Quad9 (DoH3)" — **solo cuando se observa realmente una negociación h3** (`DoHHTTPVersion.dohAnnotation`); de lo contrario muestra `DoH`. DoH3 se prefiere, nunca se promete: la etiqueta es observacional y de alcance por resolutor, nunca se persiste (el arrastre de "DoH3 confirmado" entre reinicios fue revertido). Las peticiones hacen POST de `application/dns-message`; las respuestas se validan por content-type y longitud, y el ID de transacción se restaura antes de la reescritura.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection`s agrupadas, **hasta 4 conexiones por endpoint** (`maxConnectionsPerEndpoint = 4`), round-robin, de modo que las consultas paralelas evitan el bloqueo head-of-line. Incorpora manejo de **obsolescencia por inactividad**: proveedores como Cloudflare cierran del lado del servidor las conexiones DoT inactivas (~10s) sin exponer un cambio de estado, así que una conexión reutilizada inactiva más de **8 segundos** (`reusedConnectionMaxIdleInterval = 8`) se refresca antes de enviar, y un timeout en una conexión reutilizada gana **exactamente un reintento con conexión nueva**.

### 3.4 DoQ — conexión nueva por consulta

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantiene un pool acotado de **4 carriles por endpoint**, pero **cada consulta abre una conexión QUIC nueva** — un handshake completo por consulta. El pool de 4 carriles aporta **concurrencia, no reutilización de handshake**.

**Estado de reutilización de conexión DoQ (Descartado / aplazado).** La reutilización se revisó y se midió en dispositivo (34 handshakes nuevos en 35 consultas ≈ sin reutilización), luego se implementó como una ruta `NWConnectionGroup` multi-stream condicionada a iOS 26, se probó en dispositivo contra AdGuard DoQ, y se **revirtió por ser neta-negativa** (fallos de stream + errores de fallback contra un servidor real). RFC 9250 mapea cada consulta a su propio stream QUIC, así que la reutilización requiere `NWConnectionGroup`/`openStream`, que es **solo iOS 26.0+**; el piso de despliegue actual es **iOS 17**. La reutilización se aplaza hasta que el piso alcance iOS 26. DoQ personalizado se rechaza en dispositivos que no lo soportan ("DNS over QUIC is not supported on this device").

### 3.5 Política de resolución

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) es dueño de la política upstream:

1. **Enrutamiento de transporte** según el transporte configurado.
2. **Degradación a Plain DNS** cuando un plan cifrado no tiene endpoints.
3. **Failover por endpoint** con una puerta de backoff — un endpoint en backoff nunca toca el cable (resultado `backed-off`).
4. **Fallback a Device-DNS** cuando el primario no devuelve respuesta *y* el plan lo permite (la propiedad del plan es `shouldFallbackToDeviceDNS`, derivada del campo de configuración `fallbackToDeviceDNS`); el resultado se re-anota como el transporte del dispositivo. La ejecución sobre el cable se inyecta tras ejecutores para que la política sea testeable por unidades; el estado de backoff queda fuera de la política pura.

---

## 4. Presupuesto de reglas de filtro, techo de NE y mmap

La métrica de tier que se entrega es el **presupuesto de reglas de filtro**: el total de **reglas** de dominio compiladas que un usuario puede habilitar. Esto reemplazó el antiguo tope de **recuento** de listas habilitadas (gratis 3 / de pago 10), que era un proxy deshonesto — una lista puede ser de 1K o de 1M de reglas. Hay **dos capas**: un guardrail de dispositivo para todos, y un límite de monetización por tier por debajo de él.

### 4.1 Límites por tier (Implementado)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) es la fuente de verdad:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Listas de bloqueo / DNS personalizados |
|---|---|---|---|---|
| **Free** | **500,000** | 25 | 25 | No |
| **Plus** (`.paid` / `.plus`) | **2,000,000** | 1,000 | 1,000 | Sí |

El límite por tier es una frontera de monetización, **nunca un muro de pago sobre el guardrail del dispositivo**. **Lava Security Plus** desbloquea solo la personalización — nunca la seguridad base, nunca el threat guardrail. Las listas de bloqueo personalizadas (de pago) se obtienen directamente desde el dispositivo del usuario, se parsean y se cachean localmente, y nunca se proxean a los servidores de Lava.

### 4.2 Guardrail de memoria del dispositivo + techo de NE (Implementado)

El packet tunnel está sujeto al **techo de memoria de iOS de ~50 MiB por extensión** (un límite de diseño del SO por tipo de extensión para packet tunnels desde iOS 15, no escalado con la RAM; vive en un `com.apple.jetsamproperties.{Model}.plist` por modelo de dispositivo y puede ser menor en dispositivos más antiguos). Excederlo dispara jetsam. No hay API para el techo, así que el presupuesto mantiene margen bajo el precipicio.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) hace los cálculos, denominados en reglas de filtro (block + allow + guardrail):

| Constante | Valor |
|---|---|
| `baselineMegabytes` | 4.0 MB (sobrecarga fija del proceso, medida ≈3.5 MB, redondeada al alza) |
| `estimatedBytesPerRule` | 9.0 B residentes sucios por regla (medidos ≈8.5 B, redondeados al alza) |
| `maxResidentMegabytes` | 32.0 MB (techo objetivo, dejando ~10 MB de holgura bajo el precipicio de jetsam observado de ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 reglas** |

Este **guardrail de dispositivo de ~3.26M reglas** es el piso de seguridad duro para *cada* usuario, situado por encima de cualquier tier de suscripción, y **nunca es un muro de pago**. Medición de anclaje (dispositivo "chimmy", 2026-06-13): **789,831 reglas → 9.9 MB de `phys_footprint`**, es decir ≈ baseline + coste por regla.

### 4.3 Estrategia de mmap (Implementado)

El snapshot compacto se carga con `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), y `CompactBinaryReader` devuelve slices sin copia. El blob de texto de dominios de varios megabytes permanece **respaldado por archivo/limpio** y se excluye del `phys_footprint` contado por jetsam; solo las tablas `[Entry]` decodificadas cuestan memoria residente (~6 B/regla en disco, ~8.5 B residentes sucios). Esto eleva el techo de dominios en el dispositivo: el coste residente son las tablas de entradas, no el artefacto entero.

### 4.4 Imposición de dos capas (Implementado)

- **Autoritativa (en tiempo de compilación).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) impone el presupuesto sobre la **unión deduplicada** de todas las listas habilitadas. El guardrail del dispositivo se comprueba **primero** (el piso duro); el límite por tier vincula por debajo de él. Las configuraciones que exceden el presupuesto se rechazan de forma determinista — `exceedsDeviceMemoryBudget` o `exceedsTierFilterRuleLimit` — en lugar de dejar que el túnel sufra jetsam. El error nombra las dos listas que más contribuyen para que la solución sea obvia.
- **Orientativa (UI en tiempo de selección).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) alimenta el medidor de selección usando una **suma** por lista con un **margen de techo suave de 1.10** que compensa el sobre-recuento entre listas de ~7–10% (la suma por lista sobreestima la unión deduplicada).

### 4.5 El parser (Implementado)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) cuenta reglas literalmente: descarta comentarios/líneas en blanco/líneas inválidas, normaliza, deduplica cadenas exactas dentro de una lista (mediante un `Set`), y tope en **`maxRules = 1,000,000`** por lista (por defecto), con una longitud máxima de línea de 4,096 caracteres. Formatos soportados: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (auto prueba hosts → dnsmasq → adblock → plain). Una línea válida = una regla = la unidad de memoria.

> **Líneas `hosts` multi-host (versión 2 de reglas del parser).** Una línea `hosts` que mapea una IP a varios hosts (`0.0.0.0 a.com b.com c.com`) ahora emite **cada** host como su propia regla, no solo el primero; `maxRules` se impone **por regla** (no por línea) para que una línea multi-host cerca del tope no pueda excederse. Como los mismos bytes upstream ahora pueden producir más reglas, la versión de reglas del parser se subió de **1 → 2**, invalidando las entradas obsoletas de `RuleSetCache` parseadas bajo el antiguo comportamiento de solo-primer-host.

### 4.6 Robustez de descarga y decodificación (Implementado)

El túnel y la sincronización del catálogo corren dentro del presupuesto de memoria de NE, así que la ingesta de listas está endurecida frente a entradas hostiles o malformadas:

- **Descargas en streaming.** `defaultDataFetcher` descarga los bytes de la lista a un archivo temporal mediante `URLSession.download` (memoria pico acotada) con una comprobación de tamaño posterior a la descarga (`maximumBlocklistBytes`) en lugar de bufferizar todo el cuerpo en RAM; un cuerpo demasiado grande lanza `BlocklistDownloadSizeLimitExceeded`.
- **Tope de metadatos del catálogo (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes` rechaza un catálogo remoto demasiado grande antes de decodificar, así que un host hostil/MITM no puede forzar un decode JSON con OOM en la extensión.
- **Decodificación UTF-8 tolerante.** Un único byte UTF-8 inválido ya no rechaza una lista entera (lo que bajo fail-closed bloquearía todo el DNS); los bytes inválidos se vuelven U+FFFD y solo la línea ofensiva falla la validación por línea y se descarta.
- **Errores nombrados de listas de bloqueo personalizadas.** Una lista personalizada fallida ahora expone `customBlocklistUnavailable(displayName:reason:)` — "Couldn't load the custom blocklist '<name>'. <why>" — en lugar de un `URLError` crudo; la cancelación se propaga como cancelación, no como un fallo de descarga.

---

## 5. Catálogo de listas de bloqueo y fuentes por defecto

### 5.1 Modelo de catálogo (Implementado)

El **catálogo de listas de bloqueo** es la lista publicada de fuentes disponibles. El **Worker lavasec-api** sirve metadatos JSON desde un bucket de R2 en `GET /v1/catalog` (y `/v1/catalog/:version`); el dispositivo obtiene los **bytes** reales de la lista directamente desde cada `source_url` upstream. Los endpoints del catálogo en iOS son `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

En el dispositivo, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Obtiene los bytes de la lista directamente desde `source.sourceURL`, imponiendo un tope de tamaño.
2. Calcula SHA-256 y acepta los bytes solo si el checksum está en `accepted_source_hashes` del catálogo.
3. En caso de discrepancia, recae en la última caché local válida, o **falla en cerrado** (`checksumMismatch`) — a menos que la fuente permita explícitamente la rotación upstream directa.
4. Parsea/normaliza/deduplica localmente.
5. Filtra cada conjunto de reglas parseado a través de `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`) para que una lista upstream nunca pueda bloquear dominios de Lava/Apple/proveedor de identidad.

El **conjunto de dominios protegidos** (filtrados antes de la activación): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (todos por coincidencia de sufijo). El Worker aplica un filtro `PROTECTED_SUFFIXES` equivalente al calcular los metadatos; el dispositivo revalida de todos modos.

### 5.2 Fuentes curadas (Implementado)

`DefaultCatalog.curatedSources` se genera a partir del [Catálogo de listas de bloqueo](../legal/blocklist-catalog.md) canónico, actualmente **32** fuentes en siete categorías: Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling y Piracy & Torrent. Las familias de fuentes incluyen The Block List Project, Phishing.Database, HaGeZi, OISD, StevenBlack, AdGuard y 1Hosts.

`guardrailSources` está vacío. Las fuentes GPL (HaGeZi, OISD, AdGuard) son visibles en el catálogo pero **opt-in / OFF por defecto**; el Worker restringe la sincronización/publicación de lanzamiento a `source_url_only` más los prefijos GPL autorizados (`hagezi-`, `oisd-`, `adguard-`).

### 5.3 Listas habilitadas por defecto para usuarios gratuitos (Implementado)

La configuración por defecto gratuita es `OnboardingDefaults.lavaRecommendedDefaults`, que habilita **Block List Basic** — una lista combinada amplia y de licencia permisiva (anuncios + rastreo + malware + phishing/scam) — con el preset de resolutor device-DNS (`resolverPresetID = DNSResolverPreset.device.id`) y el fallback cifrado Device-DNS **activado** (`usesEncryptedDeviceDNSFallback = true`), enrutando a **Mullvad DoH** (`fallbackResolverPresetID = DNSResolverPreset.mullvadDoH.id`): si el propio DNS del dispositivo se atasca, las búsquedas permitidas se llevan transitoriamente sobre Mullvad DoH y luego regresan al DNS del dispositivo automáticamente. (El inicializador escueto `AppConfiguration()` deja este fallback **desactivado** por defecto — solo se habilita aceptando los valores por defecto recomendados del onboarding.) Esto reemplaza el par anterior Block List Project Phishing + Scam: la cobertura combinada de Basic los subsume, y ambos siguen siendo listas opt-in seleccionables.

Ese valor por defecto gratuito está **producido por `defaultEnabled`**, no codificado a mano. `blockListProjectBasic` fija `defaultEnabled: true`, y `DefaultCatalog.recommendedDefaultSourceIDs` se deriva de `curatedSources.filter(\.defaultEnabled)`. `defaultEnabled` es "la única fuente de verdad para el valor por defecto de instalación nueva", reflejando la columna `default_enabled` del catálogo del backend. Fluyendo a través de `recommendedDefaultSourceIDs` hacia `OnboardingDefaults`, es el mecanismo vivo — cambia la bandera en una fuente para cambiar el valor por defecto.

> **Fuente de verdad del valor por defecto (una spec generada).** El catálogo se genera a partir de una única spec canónica ([Catálogo de listas de bloqueo](../legal/blocklist-catalog.md)) que produce tanto el `DefaultCatalog` de iOS como la semilla del backend, de modo que el dispositivo y los metadatos servidos de `/v1/catalog` coinciden por construcción. El valor por defecto de instalación nueva es **Block List Basic**, derivado de su bandera `defaultEnabled: true`. La verdadera puerta por tier es el presupuesto de reglas de filtro de 500K/2M, no un recuento de listas.

### 5.4 Modelo de distribución GPL source-url-only (Implementado)

**Source-url-only** es el modelo de distribución de cumplimiento GPL/IP: Lava publica solo la URL upstream + los hashes aceptados; el dispositivo obtiene y parsea las listas él mismo. Lava **nunca** almacena, replica, transforma ni sirve bytes de listas de bloqueo de terceros. Esto **reemplazó el abandonado diseño de mirror en R2** (el plan original de "mirror crudo en R2" se revirtió el 2026-05-25).

Del lado del Worker, `syncOneBlocklist` obtiene cada fuente upstream y la normaliza+hashea (calculando `source_hash`, `normalized_hash`, `entry_count`) pero escribe `raw_r2_key = null` / `normalized_r2_key = null` — solo los metadatos JSON del catálogo llegan a R2. `check-gpl-blocklist-distribution.sh` es el guardarraíl de CI que impone el modelo completo: nada de código de mirror/transformación, nada de URLs de artefactos/descargas de Lava, ninguna fuente GPL habilitada por defecto, ninguna escritura en R2 de bytes de listas por el Worker, ninguna copia de "mirror alojado por Lava", ningún `.txt`/`.json` GPL empaquetado, y `source_url_only` requerido en las migraciones + documentos legales.

> **Nota de licencia:** el código propio de Lava se entrega bajo **AGPL-3.0** (el archivo `LICENSE` es GNU AGPL v3, coincidiendo con la insignia del README). Las listas de bloqueo de terceros (incluyendo HaGeZi, OISD y AdGuard) permanecen bajo sus propias licencias upstream — el modelo source-url-only existe precisamente para que Lava pueda usarlas sin redistribuir jamás bytes de listas copyleft. GPL-3.0 aquí es una propiedad de las listas upstream, no de la app de Lava.

---

## 6. Resumen de estado

| Área | Estado |
|---|---|
| Precedencia de consultas DNS (bootstrap > pause > filter) | Implementado |
| Precedencia de decisión de filtro (guardrail > allowlist > blocklist > default-allow) | Implementado |
| Espacio de precedencia del threat-guardrail (cableado; se entrega sin entradas todavía) | Implementado |
| DoH / DoH3 (etiqueta h3 observacional) | Implementado |
| DoT (pool de 4/endpoint, refresco por inactividad de 8s, un reintento nuevo) | Implementado |
| DoQ (conexión nueva por consulta, concurrencia de 4 carriles) | Implementado |
| Reutilización de conexión DoQ | Descartado / aplazado hasta el piso iOS-26 |
| Degradación del resolutor + failover por endpoint + fallback a device-DNS | Implementado |
| Presupuesto de reglas de filtro (Free 500K / Plus 2M) | Implementado |
| Guardrail de dispositivo de ~3.26M reglas (objetivo 32 MB bajo el techo de NE de 50 MiB) | Implementado |
| mmap sin copia del snapshot compacto | Implementado |
| Catálogo source-url-only + obtención directa upstream + validación de hash | Implementado |
| Filtro de dominios protegidos | Implementado |
| Valor por defecto gratuito = Block List Basic | Implementado (catálogo generado + proyecciones iOS/backend coinciden) |
| Licencia del código propio de Lava | AGPL-3.0 (`LICENSE`); las listas de terceros siguen GPL-3.0 upstream |

---

## Véase también

- [`../product/overview.md`](../product/overview.md) — eslogan del producto, promesa de privacidad, pestañas.
- Tiers y monetización (referencia interna) — Lava Security Plus y el presupuesto de reglas de filtro como la métrica del tier.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — la decisión de cumplimiento source-url-only.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licencias y atribuciones de listas de bloqueo/resolutores upstream.
