---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Descripción general del producto

Te damos la bienvenida a Lava Security. Esta página es la puerta de entrada al conjunto de documentación: una introducción breve y sencilla a qué es Lava, qué promete y dónde leer más.

## Qué es Lava

Lava Security es una app de iOS que prioriza la privacidad y filtra el DNS localmente en el dispositivo a través de un [túnel de paquetes de NetworkExtension](../architecture/ios-client.md) que se ejecuta en el propio dispositivo, bloqueando dominios riesgosos y no deseados conocidos sin enrutar tu navegación a través de los servidores de Lava. El túnel de paquetes (`LavaSecTunnel`, un `NEPacketTunnelProvider`) analiza cada consulta DNS en el teléfono, comprueba el dominio solicitado contra una instantánea de filtro compilada y mapeada en memoria, y reenvía hacia el servidor de origen solo las consultas permitidas. No hay ningún proxy operado por Lava por el que pase tu tráfico: el filtrado es una decisión local, tomada en tu dispositivo.

iOS llama a esto una "VPN" porque un túnel de paquetes es la única forma en que una app puede filtrar el DNS en todo el sistema, pero Lava es **filtrado de DNS/listas de bloqueo**, no enrutamiento de tráfico. Seamos honestos sobre el alcance: Lava es filtrado local de dominios DNS, **no** una garantía de que se bloquee todo dominio o URL malicioso. Ve dominios, no rutas de página, por lo que no puede bloquear una página dañina concreta dentro de un host por lo demás confiable. La protección tampoco se activa automáticamente en el momento en que termina la configuración inicial: la pestaña **Guard** dentro de la app es la fuente autorizada para saber si la protección está activa en este momento.

## La promesa de privacidad

> Todo el filtrado de DNS ocurre en el dispositivo; Lava nunca enruta tu navegación a través de sus servidores y nunca recibe el flujo de dominios que visitas: el backend solo guarda metadatos del catálogo, una copia de seguridad cifrada y opaca por usuario, y diagnósticos anonimizados que tú decides enviar.

Esta frase es canónica. Todo lo demás en estos documentos está pensado para ser coherente con ella. Pagar por el nivel opcional **no** traslada el filtrado al servidor ni le da a Lava un flujo de los dominios visitados. Cuando una función toca un servidor, la documentación detalla qué **no** se envía: tus consultas DNS habituales, tu historial de navegación y cualquier texto sin cifrar permanecen siempre en el dispositivo. Consulta [el backend y el modelo de datos](../architecture/backend-and-data.md) para tener el panorama completo.

## Para quién es

Lava está pensado para cualquiera que quiera navegar de forma más segura sin tener que gestionarlo. El público incluye deliberadamente a usuarios sin conocimientos técnicos: padres y madres que configuran la protección para la familia, personas mayores y cualquiera que no quiera pensar en el DNS en absoluto. La experiencia predeterminada simplemente funciona: activa la protección y una lista de bloqueo conservadora empieza a filtrar, sin necesidad de cuenta. Al mismo tiempo, los usuarios avanzados pueden acceder a controles más profundos (listas de bloqueo personalizadas, resolutores alternativos) cuando lo deseen.

El tono en todo momento es sencillo, calmado y práctico: el peligro se presenta como una metáfora, no como miedo.

## Principios fundamentales

- **La privacidad es posicionamiento, no una función de pago.** El filtrado es una decisión local. El backend de Lava es intencionadamente mínimo y nunca recibe los dominios de tu navegación habitual ni flujos de eventos DNS. La copia de seguridad opcional de la cuenta es de [conocimiento cero](../architecture/accounts-and-backup.md): los servidores almacenan solo texto cifrado y metadatos de sobre no secretos.
- **Protección básica gratuita para siempre.** El interruptor de protección, las actualizaciones de la lista de bloqueo predeterminada y los conteos locales básicos nunca están restringidos y nunca requieren una cuenta.
- **En el dispositivo.** El motor de protección reside por completo en el teléfono: el análisis del DNS, la evaluación de dominios y el reenvío al servidor de origen ocurren todos dentro de la extensión del túnel de paquetes, limitados por el techo de memoria de iOS de ~50 MiB por extensión. Las listas de bloqueo siguen un modelo de [solo URL de origen](../architecture/dns-filtering-and-blocklists.md): la app obtiene cada lista de origen directamente y la analiza localmente; Lava nunca aloja ni sirve los bytes de listas de bloqueo de terceros.
- **El pago desbloquea solo personalización, nunca la seguridad básica.** La barrera de protección frente a amenazas —un nivel no permisible por encima de toda lista de bloqueo que nadie, de pago o no, puede agregar a la lista de permitidos— se aplica mediante la precedencia de decisión: **barrera frente a amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.** (La posición de precedencia está conectada y se verifica su integridad mediante hashes SHA-256 aceptados; actualmente se distribuye sin entradas.) El túnel ignora `isPaid`.
- **Núcleo calmado, profundidad ganada.** Las superficies predeterminadas son tranquilas y reconfortantes, presentadas por la mascota Soft Shield Guardian y textos que evitan el lenguaje basado en el miedo. Hay detalles más ricos y técnicos disponibles cuando vas a buscarlos, pero nunca se te imponen. Esta filosofía de "núcleo calmado, profundidad ganada" se formaliza en el modelo de profundidad **LavaTier** (Floor / Window / Workshop): consulta [el sistema de diseño](../design-system/overview.md).

## Capacidades de alto nivel

- **Filtrado local de DNS**: el motor del túnel de paquetes que analiza el DNS, evalúa cada dominio contra la instantánea compilada y reenvía las consultas permitidas al servidor de origen, con respaldo en el DNS del dispositivo. Consulta [el cliente de iOS](../architecture/ios-client.md) y [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Listas de bloqueo curadas, solo URL de origen**: Lava publica únicamente las URL de las listas de origen más los hashes aceptados; el dispositivo obtiene, valida y analiza por sí mismo los bytes de la lista, y Lava nunca duplica ni sirve los bytes de listas de bloqueo de terceros. El valor predeterminado distribuido activa **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definido en `OnboardingDefaults.swift`); las fuentes GPL (HaGeZi, OISD) son opcionales. Consulta [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Transportes de DNS cifrado**: DoH (con anotación observacional DoH3), DoT (conexiones agrupadas, reutilizadas y renovadas) y DoQ (conexión nueva por consulta). Los tres están implementados; el DNS del dispositivo (el propio resolutor de la red) es el predeterminado distribuido, y los ajustes preestablecidos cifrados son opcionales (`AppConfiguration.lavaRecommendedDefaults`, definido en `Sources/LavaSecCore/OnboardingDefaults.swift`). Los ajustes preestablecidos de resolutor integrados (variantes DoH y DoT de Google / Cloudflare / Quad9) son gratuitos; solo un resolutor totalmente personalizado es un desbloqueo de pago. Consulta [filtrado de DNS y listas de bloqueo](../architecture/dns-filtering-and-blocklists.md).
- **Excepciones permitidas (lista de permitidos)**: agrega dominios manualmente para permitirlos a pesar de una lista de bloqueo; la barrera frente a amenazas sigue prevaleciendo. Consulta [la descripción general de las funciones del producto](features.md).
- **El Soft Shield Guardian**: una mascota en la pestaña Guard, en la Live Activity y en la Dynamic Island que expresa el estado de protección a través de 7 estados de expresión. Consulta [el sistema de diseño](../design-system/overview.md).
- **Personalización por niveles (Lava Security Plus)**: un único nivel de pago opcional que desbloquea la personalización (un presupuesto mayor de reglas de filtro —Free 500K / Plus 2M reglas compiladas bajo una barrera de seguridad del dispositivo compartida—, más dominios permitidos/bloqueados, listas de bloqueo personalizadas y resolutores DNS personalizados). Plus nunca elude las barreras siempre activas: el túnel ignora `isPaid`.
- **Cuentas y copia de seguridad opcionales**: inicio de sesión con Apple o Google con una copia de seguridad de ajustes cifrada de extremo a extremo ([conocimiento cero](../architecture/accounts-and-backup.md)) y una frase de recuperación; la eliminación de la cuenta es autogestionada. La ranura opcional de recuperación con passkey **también es de conocimiento cero**: su clave se deriva en el dispositivo a partir del PRF de WebAuthn del autenticador, sin ningún secreto guardado en el servidor; la preparación para producción en el dispositivo aún depende del alojamiento de Associated Domains / AASA **(Planeado)**. Las cuentas son opcionales; la protección funciona por completo sin haber iniciado sesión.
- **Actividad e informes solo locales**: conteos de bloqueo/permiso en el dispositivo, estado del túnel y un paquete opcional de informe de errores, creados a partir de datos que el túnel en ejecución conserva en el dispositivo: vacíos cuando está inactivo y en vivo mientras protege. Ningún historial de dominios habitual sale del dispositivo. Consulta [la descripción general de las funciones del producto](features.md).

## Plataformas

- **iOS: disponible.** Hoy Lava es una app de iOS: tres paquetes comparten un App Group (`group.com.lavasec`) —la app (`com.lavasec.app`), la extensión del túnel de paquetes (`.tunnel`) y el widget (`.widget`)— además de fuentes compartidas, sobre un paquete `LavaSecCore` común.
- **Android: Planeado.** Se planea una versión nativa en Kotlin / Jetpack Compose sobre el `VpnService` de Android, que mantendrá la misma promesa de privacidad y un comportamiento de filtrado básico probado para que tenga paridad. Aún no se distribuye ningún código de la app de Android.

Consulta [Paridad entre plataformas](platform-parity.md) para conocer los identificadores de funciones estables y el contrato iOS/Android.
