---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Visión general del producto

Te damos la bienvenida a Lava Security. Esta página es la puerta de entrada al conjunto de documentación: una introducción breve y sencilla a qué es Lava, qué promete y dónde encontrar más información.

## Qué es Lava

Lava Security es una app de iOS centrada en la privacidad que filtra el DNS localmente en el dispositivo a través de un [túnel de paquetes NetworkExtension](../architecture/ios-client.md) en el propio dispositivo, bloqueando dominios conocidos que sean arriesgados o no deseados sin dirigir tu navegación a través de los servidores de Lava. El túnel de paquetes (`LavaSecTunnel`, un `NEPacketTunnelProvider`) analiza cada consulta DNS en el teléfono, comprueba el dominio solicitado contra una instantánea de filtros compilada y mapeada en memoria, y reenvía hacia el exterior únicamente las consultas permitidas. No hay ningún proxy operado por Lava por el que pase tu tráfico: el filtrado es una decisión local, tomada en tu dispositivo.

iOS lo etiqueta como "VPN" porque un túnel de paquetes es la única forma en que una app puede filtrar el DNS en todo el sistema, pero Lava es **filtrado de DNS y listas de bloqueo**, no enrutamiento de tráfico. Seamos claros sobre su alcance: Lava es filtrado local de dominios DNS, **no** una garantía de que se bloquee cada dominio o URL maliciosa. Ve dominios, no rutas de páginas, así que no puede bloquear una página concreta dentro de un sitio que por lo demás es de confianza. La protección tampoco se activa automáticamente en el momento en que termina la configuración inicial: la pestaña **Guard** dentro de la app es la fuente fiable para saber si la protección está activa en este momento.

## La promesa de privacidad

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca dirige tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas: el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada por usuario que es opaca, y diagnósticos anonimizados que tú decides enviar.

Esta frase es la referencia oficial. Todo lo demás en esta documentación pretende ser coherente con ella. Pagar el plan opcional **no** traslada el filtrado al servidor ni le da a Lava un flujo de los dominios visitados. Cuando una función toca un servidor, la documentación detalla qué **no** se envía: tus consultas DNS habituales, tu historial de navegación y cualquier texto sin cifrar permanecen siempre en el dispositivo. Consulta [el backend y el modelo de datos](../architecture/backend-and-data.md) para ver el panorama completo.

## Para quién es

Lava está pensada para cualquiera que quiera navegar de forma más segura sin tener que gestionarlo. El público incluye deliberadamente a personas sin conocimientos técnicos: familias que configuran la protección para los suyos, personas mayores y cualquiera que no quiera pensar en el DNS en absoluto. La experiencia por defecto simplemente funciona: activa la protección y una lista de bloqueo prudente empieza a filtrar, sin necesidad de cuenta. Al mismo tiempo, los usuarios avanzados pueden acceder a controles más profundos (listas de bloqueo personalizadas, resolutores alternativos) cuando los quieran.

El tono a lo largo de toda la app es sencillo, tranquilo y práctico: el peligro se presenta como una metáfora, no como miedo.

## Principios fundamentales

- **La privacidad es nuestro posicionamiento, no una función de pago.** El filtrado es una decisión local. El backend de Lava es intencionadamente mínimo y nunca recibe los dominios de tu navegación habitual ni flujos de eventos DNS. La copia de seguridad opcional de la cuenta es de [conocimiento cero](../architecture/accounts-and-backup.md): los servidores solo guardan el texto cifrado y metadatos del envoltorio que no son secretos.
- **Protección básica gratuita para siempre.** El interruptor de protección, las actualizaciones de la lista de bloqueo por defecto y los recuentos locales básicos nunca se restringen ni requieren una cuenta.
- **En el dispositivo.** El motor de protección reside por completo en el teléfono: el análisis del DNS, la evaluación de dominios y el reenvío hacia el exterior ocurren todos dentro de la extensión del túnel de paquetes, dentro del límite de memoria de iOS de unos 50 MiB por extensión. Las listas de bloqueo siguen un modelo de [solo URL de origen](../architecture/dns-filtering-and-blocklists.md): la app obtiene cada lista de origen directamente y la analiza localmente; Lava nunca aloja ni sirve los bytes de listas de bloqueo de terceros.
- **El pago desbloquea solo la personalización, nunca la seguridad básica.** La barrera frente a amenazas —un nivel no excepcionable por encima de toda lista de bloqueo que nadie, de pago o no, puede añadir a la lista de permitidos— se hace cumplir mediante una precedencia de decisiones: **barrera frente a amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.** (La posición de precedencia está conectada y se verifica su integridad mediante hashes SHA-256 aceptados; actualmente se distribuye sin entradas.) El túnel ignora `isPaid`.
- **Núcleo tranquilo, profundidad merecida.** Las pantallas por defecto son silenciosas y tranquilizadoras, presentadas por la mascota Soft Shield Guardian y con textos que evitan el lenguaje basado en el miedo. El detalle más rico y técnico está disponible cuando lo buscas, pero nunca se te impone. Esta filosofía de "núcleo tranquilo, profundidad merecida" está formalizada en el modelo de profundidad **LavaTier** (Floor / Window / Workshop); consulta [el sistema de diseño](../design-system/overview.md).

## Capacidades de alto nivel

- **Filtrado de DNS local** — el motor del túnel de paquetes que analiza el DNS, evalúa cada dominio contra la instantánea compilada y reenvía hacia el exterior las consultas permitidas, con respaldo en el DNS del dispositivo. Consulta [el cliente de iOS](../architecture/ios-client.md) y [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Listas de bloqueo seleccionadas, solo con URL de origen** — Lava publica únicamente las URL de las listas de origen junto con los hashes aceptados; el dispositivo obtiene, valida y analiza por sí mismo los bytes de la lista, y Lava nunca replica ni sirve los bytes de listas de bloqueo de terceros. La configuración por defecto distribuida activa **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definido en `OnboardingDefaults.swift`); las fuentes GPL (HaGeZi, OISD) son opcionales. Consulta [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Transportes de DNS cifrado** — DoH (con anotación observacional de DoH3), DoT (conexiones agrupadas, reutilizadas y renovadas) y DoQ (conexión nueva por cada consulta). Los tres están implementados; el DNS del dispositivo (el propio resolutor de la red) es el valor por defecto distribuido, y los ajustes predefinidos cifrados son opcionales (`AppConfiguration.lavaRecommendedDefaults`, definido en `Sources/LavaSecCore/OnboardingDefaults.swift`). Los ajustes predefinidos de resolutor integrados (variantes DoH y DoT de Google / Cloudflare / Quad9) son gratuitos; solo un resolutor totalmente personalizado es un desbloqueo de pago. Consulta [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Excepciones permitidas (lista de permitidos)** — añade dominios manualmente para permitirlos a pesar de una lista de bloqueo; la barrera frente a amenazas sigue teniendo prioridad. Consulta [la visión general de funciones del producto](features.md).
- **El Soft Shield Guardian** — una mascota en la pestaña Guard, en la Live Activity y en la Dynamic Island que expresa el estado de la protección a través de 7 estados de expresión. Consulta [el sistema de diseño](../design-system/overview.md).
- **Personalización por niveles (Lava Security Plus)** — un único plan de pago opcional que desbloquea la personalización (un presupuesto mayor de reglas de filtrado —500 K reglas compiladas en Free / 2 M en Plus, bajo una barrera de seguridad del dispositivo compartida—, más dominios permitidos o bloqueados, listas de bloqueo personalizadas y resolutores DNS personalizados). Plus nunca sortea las barreras siempre activas: el túnel ignora `isPaid`.
- **Cuentas y copia de seguridad opcionales** — inicio de sesión con Apple o Google con una copia de seguridad de ajustes cifrada de extremo a extremo (de [conocimiento cero](../architecture/accounts-and-backup.md)) y una frase de recuperación; la eliminación de la cuenta es autoservicio. La ranura opcional de recuperación con passkey **también es de conocimiento cero**: su clave se deriva en el dispositivo a partir de la PRF de WebAuthn del autenticador, sin ningún secreto guardado en el servidor; la disponibilidad para producción en el dispositivo todavía depende del alojamiento de Associated Domains / AASA **(Planificado)**. Las cuentas son opcionales; la protección funciona por completo sin iniciar sesión.
- **Actividad e informes solo locales** — recuentos de bloqueos y permisos en el dispositivo, estado del túnel y un paquete opcional de informe de errores, construidos a partir de los datos que el túnel en ejecución guarda en el dispositivo: vacíos cuando está inactivo y en vivo mientras protege. Ningún historial de dominios habitual sale del dispositivo. Consulta [la visión general de funciones del producto](features.md).

## Plataformas

- **iOS — disponible.** Lava es hoy una app de iOS: tres paquetes comparten un mismo App Group (`group.com.lavasec`) —la app (`com.lavasec.app`), la extensión del túnel de paquetes (`.tunnel`) y el widget (`.widget`)—, además de las fuentes compartidas, sobre un paquete común `LavaSecCore`.
- **Android — Planificado.** Está planificada una versión nativa en Kotlin / Jetpack Compose sobre el `VpnService` de Android, que mantendrá la misma promesa de privacidad y un comportamiento de filtrado básico verificado para mantener la paridad. Todavía no se distribuye ningún código de app para Android.

Consulta [Paridad entre plataformas](platform-parity.md) para conocer los identificadores de funciones estables y el contrato entre iOS y Android.
