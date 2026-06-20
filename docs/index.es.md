---
hide_feedback: true
---

# Documentación de Lava Security

Lava Security es una **app de iOS centrada en la privacidad** que filtra el DNS de forma local en
el dispositivo mediante un túnel de paquetes NetworkExtension dentro del propio dispositivo, bloqueando dominios conocidos
arriesgados y no deseados sin enrutar tu navegación a través de los servidores de Lava.

!!! quote "La promesa de privacidad"
    El filtrado de DNS ocurre localmente en tu dispositivo; Lava nunca recibe tus
    consultas DNS habituales, tu historial de navegación ni datos por dominio, y cualquier
    copia de seguridad opcional de la cuenta está cifrada de extremo a extremo, de modo que Lava solo puede llegar a almacenar
    texto cifrado.

Este sitio es el manual público sobre cómo funciona Lava: su arquitectura, su
comportamiento y las decisiones que hay detrás. Sigue al
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

-   :material-lock: **Funcionamiento interno de la privacidad**

    Las partes que sostienen la promesa de privacidad.

    [Backend y datos](architecture/backend-and-data.md) ·
    [Cuentas y copia de seguridad sin conocimiento](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Decisiones y cumplimiento**

    Por qué está hecho así.

    [Decisiones clave (ADR)](decisions/key-decisions.md) ·
    [Avisos de terceros](legal/third-party-notices.md)

</div>

## Cómo leer esto

Cada afirmación aquí está fundamentada en el código fuente. El estado se indica en todo momento:

| Estado | Significado |
|---|---|
| **Implementado** | Presente en el código publicado |
| **En curso** | En construcción ahora mismo |
| **Previsto** | Una dirección, todavía sin construir |
| **Descartado** | Decidido en contra; se conserva como registro |

Cuando la documentación y el código no coinciden, manda el código. Esta documentación es una instantánea,
regenerada a partir del código fuente a medida que el producto evoluciona.

El comportamiento entre plataformas se recoge en [Paridad entre plataformas](product/platform-parity.md):
nombra identificadores de funciones estables, el estado en cada plataforma y las pruebas o fixtures que
deberían mantener iOS y Android alineados.
