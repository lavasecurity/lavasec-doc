---
hide_feedback: true
---

# Documentación de Lava Security

Lava Security es una **aplicación de iOS centrada en la privacidad** que filtra DNS localmente en el
dispositivo a través de un túnel de paquetes NetworkExtension en el propio dispositivo, bloqueando dominios conocidos
como riesgosos y no deseados sin enrutar tu navegación a través de los servidores de Lava.

!!! quote "La promesa de privacidad"
    El filtrado de DNS ocurre localmente en tu dispositivo; Lava nunca recibe tus
    consultas DNS rutinarias, tu historial de navegación ni telemetría por dominio, y cualquier
    copia de seguridad opcional de la cuenta está cifrada de extremo a extremo, de modo que Lava solo puede llegar a almacenar
    texto cifrado.

Este sitio es el manual público de cómo funciona Lava: su arquitectura, su
comportamiento y las decisiones que hay detrás. Sigue el
[cliente de iOS](https://github.com/lavasecurity/lavasec-ios) de código abierto.

## Empieza aquí

<div class="grid cards" markdown>

-   :material-rocket-launch: **Producto**

    Qué hace Lava y para quién es.

    [Visión general](product/overview.md) · [Catálogo de funciones](product/features.md) ·
    [Paridad entre plataformas](product/platform-parity.md)

-   :material-sitemap: **Arquitectura**

    Cómo encaja todo el sistema.

    [Visión general del sistema](architecture/system-overview.md) ·
    [Cliente de iOS](architecture/ios-client.md) ·
    [Filtrado de DNS y listas de bloqueo](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **Mecanismos internos de privacidad**

    Las partes que sostienen la promesa de privacidad.

    [Backend y datos](architecture/backend-and-data.md) ·
    [Cuentas y copia de seguridad de conocimiento cero](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Decisiones y cumplimiento**

    Por qué está construido así.

    [Decisiones clave (ADR)](decisions/key-decisions.md) ·
    [Avisos de terceros](legal/third-party-notices.md)

</div>

## Cómo leer esto

Cada afirmación aquí está fundamentada en el código fuente. El estado se indica en todo el documento:

| Estado | Significado |
|---|---|
| **Implementado** | Presente en el código publicado |
| **En progreso** | Se está construyendo ahora |
| **Planificado** | Una dirección, aún no construida |
| **Descartado** | Decidido en contra — se conserva para dejar constancia |

Cuando la documentación y el código no coinciden, gana el código. Esta documentación es una instantánea,
regenerada a partir del código fuente a medida que el producto evoluciona.

El comportamiento multiplataforma se rastrea en [Paridad entre plataformas](product/platform-parity.md):
nombra ids de funciones estables, el estado por plataforma y las pruebas o fixtures que
deberían mantener alineados iOS y Android.
