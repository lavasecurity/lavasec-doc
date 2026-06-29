# Paridad de plataformas

El sistema de paridad de plataformas de Lava registra qué promesas del producto
se comparten entre iOS, Android y futuros clientes. Es el contrato público para
el comportamiento de las funciones: qué debe significar lo mismo en todas
partes, qué es intencionalmente nativo de la plataforma y qué aún no se promete.

Los documentos de paridad no reemplazan los planes de implementación ni las pruebas:

- `lavasec-doc` es dueño del contrato de producto y comportamiento.
- Los planes internos son dueños del estado de entrega, la secuenciación, los
  riesgos privados y la sincronización con la junta.
- Los repositorios de plataforma son dueños del código, los fixtures y las
  pruebas que demuestran el comportamiento.

Cuando los documentos y el código publicado no coinciden, el código gana hasta
que los documentos se actualicen. Cuando un plan y esta página no coinciden,
trata esta página como el contrato de producto y el plan como la cola de trabajo.

## Vocabulario de estado

| Estado | Significado |
|---|---|
| **Shipped** | Implementado en código de producción para esa plataforma. |
| **Partial** | Existe algún comportamiento, pero el contrato público no se cumple por completo. |
| **Planned** | Aceptado como parte del contrato de plataforma, aún no implementado. |
| **Deferred** | Función válida, pero no requerida para el próximo hito de la plataforma. |
| **Platform-native** | Misma promesa al usuario, implementación específica del sistema operativo distinta. |
| **Not applicable** | No debe existir ninguna función equivalente en esa plataforma. |
| **Dropped** | Previamente considerada o construida, luego eliminada intencionalmente. |

## Formato del registro de funciones

Cada función con seguimiento de paridad debe tener un id de función estable. Usa
nombres `area.capability` que sobrevivan a los cambios de texto en la interfaz,
por ejemplo `filtering.guardrail-precedence` o `dns.encrypted-transports`.

Un registro de función completo responde:

| Campo | Propósito |
|---|---|
| `feature_id` | Id estable usado en planes, PR, pruebas y documentos. |
| Promesa del producto | Aquello en lo que los usuarios pueden confiar, en lenguaje neutral respecto a la plataforma. |
| Requisito de paridad | Si Android debe coincidir con iOS exactamente, coincidir por intención o mantenerse intencionalmente distinto. |
| Estado de plataforma | Estado en iOS, Android y futuros clientes. |
| Cumplimiento | Pruebas, fixtures, archivos fuente o revisiones que mantienen el comportamiento honesto. |
| Notas de plataforma | Diferencias específicas del sistema operativo que deben ser explícitas, no redescubiertas más tarde. |

## Flujo de actualización

1. Agrega o actualiza el id de función cuando un cambio altere una promesa del
   producto, una afirmación de privacidad, un límite de nivel o un comportamiento
   entre plataformas.
2. Vincula el mismo id de función desde el plan de implementación cuando se
   necesite trabajo.
3. Agrega o actualiza pruebas de plataforma o golden fixtures para el
   comportamiento que debe coincidir.
4. Cuando una plataforma publique el comportamiento, actualiza el estado aquí y
   refresca la página de función o de arquitectura correspondiente.
5. Mantén privados los detalles internos exclusivos de implementación, privados,
   de precios, de riesgo legal y operativos; resume aquí solo el contrato público.

## Libro de paridad actual

| Feature id | Promesa del producto | iOS | Android | Requisito de paridad | Cumplimiento / fuente |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava filtra DNS localmente en el dispositivo y no enruta la navegación a través de servidores de Lava. | Shipped | Planned | Coincidencia por intención; las API de túnel del SO difieren. | Arquitectura de packet tunnel de iOS; plan de `VpnService` de Android. |
| `protection.vpn-disclosure` | La app explica por qué el SO llama VPN al filtrado de DNS local antes de pedir el permiso/configuración de VPN. | Shipped | Planned | Texto y flujo de permisos nativos de la plataforma. | Documentos de onboarding; plan de divulgación de Android Play. |
| `filtering.guardrail-precedence` | Las protecciones siempre activas anulan las listas de permitidos del usuario; el estado de pago nunca evade las protecciones. | Shipped | Planned | Paridad exacta de comportamiento. | `CompactFilterSnapshotTests`; `FilterSnapshotTest` de Android cuando se porte. |
| `filtering.source-url-only-catalog` | Lava publica metadatos de catálogo y URL de fuentes upstream, no bytes de listas de bloqueo de terceros. | Shipped | Planned | Paridad exacta de modelo de privacidad/PI. | Arquitectura de catálogo; documentos legales GPL/source-url-only. |
| `filtering.on-device-parsing` | Las listas seleccionadas se obtienen y analizan en el dispositivo; el historial rutinario de dominios no se sube a Lava. | Shipped | Planned | Paridad exacta de privacidad, se permite almacenamiento nativo. | `BlocklistParserTests`; pruebas de paridad del analizador de Android cuando se porten. |
| `filtering.rule-budget` | Los límites de los Filtros se basan en el número de reglas compiladas y la seguridad del dispositivo, no en un conteo arbitrario de listas. | Shipped | Planned | Mismo modelo de cara al usuario; los límites de memoria de la plataforma pueden diferir. | Pruebas de presupuesto de Filtros de iOS; pruebas de presupuesto de Android cuando se conozcan los límites del dispositivo. |
| `dns.built-in-resolvers` | Los usuarios pueden elegir presets de resolvedores integrados sin enviar las búsquedas permitidas a Lava. | Shipped | Planned | Misma política de resolvedores; el conjunto de presets puede lanzarse por fases. | Pruebas de presets de resolvedores; pruebas de DTO de resolvedores de Android cuando se porten. |
| `dns.encrypted-transports` | DNS upstream cifrado está disponible para las consultas permitidas. | Shipped | Planned | Se permite paridad por etapas; la v1 de Android puede empezar con DoH antes de DoT/DoQ. | Pruebas de transporte de iOS; pruebas de resolvedores y QA en dispositivo de Android. |
| `reports.local-only-diagnostics` | Los informes y diagnósticos permanecen locales a menos que el usuario envíe explícitamente un paquete de soporte. | Shipped | Planned | Paridad exacta de privacidad; la interfaz puede diferir. | Pruebas del paquete de informe de errores; pruebas de vista previa del informe de depuración de Android cuando se construyan. |
| `account.optional-sign-in` | La protección funciona sin una cuenta; el inicio de sesión es opcional. | Shipped | Deferred | Promesa de producto exacta antes de que Android exponga funciones de cuenta. | Documentos de autenticación de cuenta; revisión de onboarding/ajustes de Android. |
| `backup.zero-knowledge-settings` | La copia de seguridad opcional de ajustes almacena solo texto cifrado; Lava no puede leer el contenido en texto plano de la copia. | Shipped | Deferred | Paridad exacta de privacidad antes de que Android ofrezca copias de seguridad. | Pruebas de copia de seguridad de conocimiento cero; pruebas de paridad de criptografía de Android cuando se construyan. |
| `plus.customization-boundary` | La protección gratuita sigue siendo útil; Plus desbloquea personalización avanzada y nunca cambia la seguridad de las protecciones. | Shipped | Planned | Mismo límite de producto; la implementación de la tienda es nativa de la plataforma. | Pruebas de política de suscripción; pruebas de derechos de Play Billing cuando se construyan. |
| `design.calm-earned-depth` | La UX por defecto es calmada, con superficies técnicas o de celebración más profundas solo cuando se ganan o se solicitan. | Partial | Planned | Coincidencia por intención de diseño a través de tokens/roles compartidos. | Documentos del sistema de diseño y plan de la base de portabilidad. |
| `platform.ambient-presence` | El estado de protección puede aparecer fuera de la app cuando el SO admite una superficie ambiental nativa. | Platform-native | Planned | Paridad de intención, no paridad de superficie. | Documentos de Live Activity de iOS; decisión sobre notificación/Ajustes rápidos de Android pendiente. |

## Uso para preparación de Android

Antes de que comience la implementación en Android, esta página debe revisarse
junto al plan de Android y al plan de portabilidad del sistema de diseño. El
contrato mínimo listo para Android es:

- cada función con implicaciones de privacidad tiene un id de función;
- el comportamiento de paridad exacta tiene una fuente de prueba o fixture de iOS identificada;
- el comportamiento nativo de la plataforma tiene una postura explícita de Android;
- las funciones diferidas se nombran para que el MVP de Android no implique
  accidentalmente que se publican.

Esa revisión pertenece al plan de implementación o a las notas de revisión,
mientras que esta página mantiene el contrato público y duradero.
