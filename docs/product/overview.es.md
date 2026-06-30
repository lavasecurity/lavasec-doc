---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Resumen del producto

Te damos la bienvenida a Lava Security. Esta página presenta qué es Lava, qué promete y dónde leer más.

## Qué es Lava

Lava Security es una app de iOS centrada en la privacidad que filtra el DNS localmente en el dispositivo a través de un [túnel de paquetes NetworkExtension en el dispositivo](../architecture/ios-client.md), bloqueando dominios conocidos como peligrosos o no deseados sin enrutar tu navegación a través de los servidores de Lava. El túnel de paquetes (`LavaSecTunnel`, un `NEPacketTunnelProvider`) analiza cada consulta DNS en el teléfono, compara el dominio solicitado con una instantánea de filtro compilada y mapeada en memoria, y reenvía aguas arriba únicamente las consultas permitidas. No hay ningún proxy operado por Lava por el que pase tu tráfico: el filtrado es una decisión local, tomada en tu dispositivo.

iOS lo etiqueta como una "VPN" porque un túnel de paquetes es la única manera en que una app puede filtrar el DNS de todo el sistema, pero Lava es **filtrado de DNS/listas de bloqueo**, no enrutamiento de tráfico. Sé honesto sobre el alcance: Lava es filtrado local de dominios DNS, **no** una garantía de que se bloquee todo dominio o URL malicioso. Ve dominios, no rutas de páginas, por lo que no puede bloquear una página dañina en un host por lo demás confiable. La protección tampoco se activa automáticamente en cuanto termina la incorporación: la pestaña **Guard** en la app es la fuente autorizada para saber si la protección está actualmente activa.

## La promesa de privacidad

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas; el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.

Esta frase es canónica. Todo lo demás en estos documentos es coherente con ella. Pagar por el nivel opcional **no** traslada el filtrado al servidor ni le da a Lava un flujo de los dominios visitados. Cuando una función toca un servidor, la documentación detalla qué **no** se envía: tus consultas DNS rutinarias, tu historial de navegación y cualquier texto sin cifrar permanecen en el dispositivo. Consulta [el backend y el modelo de datos](../architecture/backend-and-data.md) para ver el panorama completo.

## Para quién es

Lava está pensada para cualquiera que quiera navegar de forma más segura sin tener que gestionarlo. El público incluye a usuarios no técnicos: padres y madres que configuran la protección para una familia, personas mayores y cualquiera que no quiera pensar en el DNS en absoluto. La experiencia por defecto simplemente funciona: activa la protección y una lista de bloqueo conservadora empieza a filtrar, sin necesidad de cuenta. Al mismo tiempo, los usuarios avanzados pueden acceder a controles más profundos (listas de bloqueo personalizadas, resolutores alternativos) cuando los deseen.

El tono en todo momento es sencillo, sereno y práctico: el peligro se plantea como una metáfora, no como miedo.

## Principios fundamentales

- **La privacidad es un posicionamiento, no una función de pago.** El filtrado es una decisión local. El backend de Lava es intencionadamente mínimo y nunca recibe tus dominios de navegación rutinarios ni flujos de eventos DNS. La copia de seguridad opcional de la cuenta es de [conocimiento cero](../architecture/accounts-and-backup.md): los servidores almacenan solo texto cifrado y metadatos de sobre no secretos.
- **Protección básica gratuita para siempre.** El interruptor de protección, las actualizaciones de la lista de bloqueo por defecto y los recuentos locales básicos nunca están restringidos ni requieren una cuenta.
- **En el dispositivo.** El motor de protección reside por completo en el teléfono: el análisis del DNS, la evaluación de dominios y el reenvío aguas arriba ocurren todos dentro de la extensión del túnel de paquetes, limitados por el techo de memoria de iOS de ~50 MiB por extensión. Las listas de bloqueo siguen un modelo de [solo-URL-de-origen](../architecture/dns-filtering-and-blocklists.md): la app obtiene cada lista aguas arriba directamente y la analiza localmente; Lava nunca aloja ni sirve los bytes de listas de bloqueo de terceros.
- **El pago desbloquea solo la personalización, nunca la seguridad de base.** La barrera contra amenazas —un nivel no exceptuable por encima de toda lista de bloqueo que nadie, pague o no, puede añadir a una lista de permitidos— se aplica mediante la precedencia de decisiones: **barrera contra amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.** (La ranura de precedencia está cableada y verificada en su integridad mediante hashes SHA-256 aceptados; actualmente se distribuye sin entradas.) El túnel ignora `isPaid`.
- **Núcleo sereno, profundidad ganada.** Las superficies por defecto son tranquilas y reconfortantes, presididas por la mascota Soft Shield Guardian y por textos que evitan el lenguaje basado en el miedo. Hay detalles más ricos y técnicos disponibles cuando los buscas, pero nunca se te imponen. Esta filosofía de "núcleo sereno, profundidad ganada" se formaliza en el modelo de profundidad **LavaTier** (Floor / Window / Workshop); consulta [el sistema de diseño](../design-system/overview.md).

## Capacidades de alto nivel

- **Filtrado de DNS local** — el motor del túnel de paquetes que analiza el DNS, evalúa cada dominio contra la instantánea compilada y reenvía aguas arriba las consultas permitidas con recurso al DNS del dispositivo. Consulta [el cliente de iOS](../architecture/ios-client.md) y [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Listas de bloqueo curadas, solo-URL-de-origen** — Lava publica únicamente las URL de las listas aguas arriba (más hashes informativos para identidad de caché y auditoría); el dispositivo obtiene cada lista por TLS y la analiza localmente bajo límites de tamaño/reglas, y Lava nunca duplica ni sirve los bytes de listas de bloqueo de terceros. Las listas de la comunidad no están fijadas por hash —TLS + la URL curada son el límite de integridad— mientras que el nivel de barrera contra amenazas de Lava sigue aplicándose por hash. El valor por defecto distribuido habilita **Block List Basic** (`AppConfiguration.lavaRecommendedDefaults`, definido en `OnboardingDefaults.swift`); las fuentes copyleft como HaGeZi, OISD, AdGuard y 1Hosts son opcionales. Consulta [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Transportes de DNS cifrado** — DoH (con anotación observacional DoH3), DoT (conexiones agrupadas, reutilizadas y renovadas) y DoQ (conexión nueva por consulta). Los tres están implementados; el DNS del dispositivo (el propio resolutor de la red) es el valor por defecto distribuido, y los preajustes cifrados son opcionales (`AppConfiguration.lavaRecommendedDefaults`, definido en `Sources/LavaSecCore/OnboardingDefaults.swift`). Los preajustes de resolutor integrados (variantes DoH y DoT de Google / Cloudflare / Quad9) son gratuitos; solo un resolutor totalmente personalizado es un desbloqueo de pago. Consulta [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Excepciones permitidas (lista de permitidos)** — añade manualmente dominios para permitirlos a pesar de una lista de bloqueo; la barrera contra amenazas sigue ganando. Consulta [el resumen de funciones del producto](features.md).
- **El Soft Shield Guardian** — una mascota en la pestaña Guard, la Live Activity y la Dynamic Island que expresa el estado de protección a través de 7 estados de expresión. Consulta [el sistema de diseño](../design-system/overview.md).
- **Personalización por niveles (Lava Security Plus)** — un único nivel de pago opcional que desbloquea la personalización (un presupuesto mayor de reglas de filtro —Free 500K / Plus 2M reglas compiladas bajo una barrera de seguridad del dispositivo compartida—, más dominios permitidos/bloqueados, listas de bloqueo personalizadas y resolutores DNS personalizados). Plus nunca elude las barreras siempre activas: el túnel ignora `isPaid`.
- **Cuentas y copia de seguridad opcionales** — inicio de sesión con Apple o Google con una copia de seguridad de ajustes cifrada de extremo a extremo ([conocimiento cero](../architecture/accounts-and-backup.md)) y frase de recuperación; la eliminación de la cuenta es autoservicio. La ranura opcional de recuperación con passkey es **también de conocimiento cero**: su clave se deriva en el dispositivo a partir del PRF WebAuthn del autenticador, sin ningún secreto en poder del servidor; la disponibilidad para producción en el dispositivo todavía depende del alojamiento de Associated Domains / AASA **(Planificado)**. Las cuentas son opcionales; la protección funciona por completo sin sesión iniciada.
- **Actividad e informes solo locales** — recuentos de bloqueo/permiso en el dispositivo, estado del túnel y un paquete de informe de errores opcional, construidos a partir de los datos que el túnel en ejecución conserva en el dispositivo; vacíos cuando está inactivo y en vivo mientras protege. Ningún historial de dominios rutinario sale del dispositivo. Consulta [el resumen de funciones del producto](features.md).

## Plataformas

- **iOS — distribuida.** Lava es hoy una app de iOS: tres paquetes comparten un App Group (`group.com.lavasec`) —la app (`com.lavasec.app`), la extensión del túnel de paquetes (`.tunnel`) y el widget (`.widget`)— más fuentes compartidas, sobre un paquete común `LavaSecCore`.
- **Android — Planificada.** Está planificada una versión nativa en Kotlin / Jetpack Compose sobre el `VpnService` de Android, que llevará la misma promesa de privacidad y un comportamiento de filtrado central probado en paridad. Todavía no se distribuye código de la app de Android.

Consulta [Paridad de plataformas](platform-parity.md) para ver los identificadores de funciones estables y el contrato iOS/Android.
