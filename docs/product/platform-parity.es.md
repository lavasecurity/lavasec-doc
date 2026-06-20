# Paridad entre plataformas

El sistema de paridad entre plataformas de Lava lleva el registro de qué
promesas del producto son compartidas entre iOS, Android y los futuros clientes.
Es el contrato público del comportamiento de las funciones: qué debe significar
lo mismo en todas partes, qué es intencionadamente nativo de cada plataforma y
qué todavía no se promete.

La documentación de paridad no sustituye a los planes de implementación ni a las
pruebas:

- `lavasec-doc` es responsable del contrato del producto y del comportamiento.
- Los planes internos son responsables del estado de entrega, la secuenciación,
  los riesgos privados y la sincronización con el equipo.
- Los repositorios de cada plataforma son responsables del código, los datos de
  prueba y los tests que demuestran el comportamiento.

Cuando la documentación y el código publicado no coinciden, prevalece el código
hasta que se actualice la documentación. Cuando un plan y esta página no
coinciden, considera esta página como el contrato del producto y el plan como la
cola de trabajo.

## Vocabulario de estados

| Estado | Significado |
|---|---|
| **Publicado** | Implementado en código de producción para esa plataforma. |
| **Parcial** | Existe parte del comportamiento, pero el contrato público no se cumple del todo. |
| **Planificado** | Aceptado como parte del contrato de la plataforma, aún no implementado. |
| **Aplazado** | Función válida, pero no necesaria para el próximo hito de la plataforma. |
| **Nativo de la plataforma** | Misma promesa al usuario, implementación específica de cada sistema operativo. |
| **No aplica** | No debería existir una función equivalente en esa plataforma. |
| **Descartado** | Antes se consideró o se construyó, y luego se retiró de forma intencionada. |

## Formato del registro de funciones

Cada función con seguimiento de paridad debería tener un identificador de función
estable. Usa nombres del tipo `area.capability` que sobrevivan a los cambios del
texto de la interfaz, por ejemplo `filtering.guardrail-precedence` o
`dns.encrypted-transports`.

Un registro de función completo responde a lo siguiente:

| Campo | Propósito |
|---|---|
| `feature_id` | Identificador estable usado en planes, PR, tests y documentación. |
| Promesa del producto | Aquello en lo que los usuarios pueden confiar, en un lenguaje neutro respecto a la plataforma. |
| Requisito de paridad | Si Android debe coincidir con iOS exactamente, coincidir en intención o mantenerse intencionadamente diferente. |
| Estado por plataforma | Estado en iOS, Android y futuros clientes. |
| Garantía | Tests, datos de prueba, archivos fuente o controles de revisión que mantienen el comportamiento fiel. |
| Notas de plataforma | Diferencias específicas de cada sistema operativo que deben quedar explícitas, no redescubrirse más tarde. |

## Flujo de actualización

1. Añade o actualiza el identificador de función cuando un cambio modifique una
   promesa del producto, una declaración de privacidad, el límite de un plan o el
   comportamiento entre plataformas.
2. Enlaza el mismo identificador de función desde el plan de implementación cuando
   sea necesario trabajar en ello.
3. Añade o actualiza los tests de plataforma o los datos de prueba de referencia
   para el comportamiento que debe coincidir.
4. Cuando una plataforma publique el comportamiento, actualiza aquí el estado y
   pon al día la página de función o de arquitectura correspondiente.
5. Mantén privados los detalles internos de implementación, los datos privados,
   de precios, de riesgo legal y operativos; aquí resume únicamente el contrato
   público.

## Registro de paridad actual

| Identificador de función | Promesa del producto | iOS | Android | Requisito de paridad | Garantía / origen |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava filtra el DNS localmente en el dispositivo y no canaliza la navegación a través de servidores de Lava. | Publicado | Planificado | Coincidir en intención; las API de túnel del sistema operativo difieren. | Arquitectura del túnel de paquetes de iOS; plan de `VpnService` de Android. |
| `protection.vpn-disclosure` | La app explica por qué el sistema operativo llama VPN al filtrado de DNS local antes de pedir el permiso o la configuración de VPN. | Publicado | Planificado | Texto y flujo de permisos nativos de la plataforma. | Documentación de incorporación; plan de divulgación en Play de Android. |
| `filtering.guardrail-precedence` | Las protecciones permanentes prevalecen sobre las listas de permitidos del usuario; tener un plan de pago nunca las omite. | Publicado | Planificado | Paridad exacta de comportamiento. | `CompactFilterSnapshotTests`; `FilterSnapshotTest` de Android cuando se porte. |
| `filtering.source-url-only-catalog` | Lava publica los metadatos del catálogo y las URL de las fuentes de origen, no los bytes de listas de bloqueo de terceros. | Publicado | Planificado | Paridad exacta del modelo de privacidad y propiedad intelectual. | Arquitectura del catálogo; documentación legal de GPL y de solo URL de origen. |
| `filtering.on-device-parsing` | Las listas seleccionadas se descargan y procesan en el dispositivo; el historial habitual de dominios no se sube a Lava. | Publicado | Planificado | Paridad exacta de privacidad, se permite almacenamiento nativo. | `BlocklistParserTests`; tests de paridad del analizador de Android cuando se porten. |
| `filtering.rule-budget` | Los límites de filtrado se basan en el número de reglas compiladas y en la seguridad del dispositivo, no en un recuento arbitrario de listas. | Publicado | Planificado | Mismo modelo de cara al usuario; los límites de memoria de cada plataforma pueden diferir. | Tests de presupuesto de filtros de iOS; tests de presupuesto de Android cuando se conozcan los límites del dispositivo. |
| `dns.built-in-resolvers` | Los usuarios pueden elegir entre ajustes predefinidos de resolvedores integrados sin enviar a Lava las consultas permitidas. | Publicado | Planificado | Misma política de resolvedores; el conjunto de ajustes predefinidos puede lanzarse por fases. | Tests de ajustes predefinidos de resolvedores; tests del DTO de resolvedores de Android cuando se porten. |
| `dns.encrypted-transports` | El DNS cifrado de origen está disponible para las consultas permitidas. | Publicado | Planificado | Se permite paridad por fases; la v1 de Android puede empezar con DoH antes que DoT/DoQ. | Tests de transporte de iOS; tests de resolvedores de Android y QA en dispositivo. |
| `reports.local-only-diagnostics` | Los informes y diagnósticos se quedan en el dispositivo salvo que el usuario envíe de forma explícita un paquete de soporte. | Publicado | Planificado | Paridad exacta de privacidad; la interfaz puede diferir. | Tests del paquete de informe de errores; tests de vista previa del informe de depuración de Android cuando se construyan. |
| `account.optional-sign-in` | La protección funciona sin una cuenta; iniciar sesión es opcional. | Publicado | Aplazado | Promesa de producto exacta antes de que Android exponga funciones de cuenta. | Documentación de autenticación de cuenta; revisión de incorporación y ajustes de Android. |
| `backup.zero-knowledge-settings` | La copia de seguridad opcional de los ajustes almacena solo texto cifrado; Lava no puede leer el contenido en texto plano de la copia. | Publicado | Aplazado | Paridad exacta de privacidad antes de que Android ofrezca copia de seguridad. | Tests de copia de seguridad de conocimiento cero; tests de paridad criptográfica de Android cuando se construyan. |
| `plus.customization-boundary` | La protección gratuita sigue siendo útil; Plus desbloquea personalización avanzada y nunca cambia la seguridad de las protecciones permanentes. | Publicado | Planificado | Mismo límite de producto; la implementación de la tienda es nativa de la plataforma. | Tests de la política de suscripción; tests de derechos de Play Billing cuando se construyan. |
| `design.calm-earned-depth` | La experiencia por defecto es tranquila, con superficies más técnicas o de celebración solo cuando se ganan o se solicitan. | Parcial | Planificado | Coincidir en intención de diseño mediante tokens y roles compartidos. | Documentación del sistema de diseño y plan de la base de portabilidad. |
| `platform.ambient-presence` | El estado de protección puede aparecer fuera de la app cuando el sistema operativo admite una superficie ambiental nativa. | Nativo de la plataforma | Planificado | Paridad de intención, no paridad de superficie. | Documentación de Live Activity de iOS; decisión sobre notificación y Ajustes rápidos de Android pendiente. |

## Uso para la preparación de Android

Antes de que comience la implementación de Android, esta página debería revisarse
junto con el plan de Android y el plan de portabilidad del sistema de diseño. El
contrato mínimo para estar listos en Android es:

- cada función con implicaciones de privacidad tiene un identificador de función;
- el comportamiento de paridad exacta tiene un origen identificado de test o
  datos de prueba en iOS;
- el comportamiento nativo de la plataforma tiene una postura explícita para
  Android;
- las funciones aplazadas están nombradas para que el MVP de Android no dé a
  entender por accidente que se publican.

Esa revisión corresponde al plan de implementación o a las notas de revisión,
mientras que esta página mantiene el contrato público y duradero.
