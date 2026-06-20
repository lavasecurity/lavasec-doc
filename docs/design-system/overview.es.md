---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Sistema de diseño

> **Público:** equipos de diseño e ingeniería que trabajan en la app de iOS de Lava Security.
> **Autoridad:** cuando este documento y un plan no coincidan, **manda el código**: las divergencias se señalan en línea. El estado refleja la realidad confirmada en el código, no las aspiraciones del plan. Leyenda de estados: **Implementado** (publicado y confirmado en el código), **En progreso** (parcialmente incorporado), **Planeado** (diseñado, no construido), **Descartado** (rechazado o revertido).

Este documento cubre la filosofía de diseño, el vocabulario de profundidad LavaTier, la mascota Guardián, las convenciones de textos y nomenclatura, la experiencia de incorporación (onboarding) y la internacionalización. Para la infraestructura técnica que hay detrás de estas superficies (targets, ciclo de vida del VPN, el cableado del modelo de estado de protección del Guardián), consulta [el cliente de iOS](../architecture/ios-client.md); para el encuadre del producto, consulta [la visión general del producto](../product/overview.md).

---

## 1. Filosofía: núcleo tranquilo, profundidad que se gana

El público de Lava son personas no técnicas que usan la app a diario —padres y madres, personas mayores— y el diseño parte de ahí. La superficie cotidiana "simplemente funciona" con calma para todo el mundo; el detalle adicional, los pequeños momentos de disfrute y el control se revelan (**se ganan**) solo a medida que la persona los va buscando. Nada insiste, nada alarma, y la maquinaria técnica permanece invisible hasta que se busca.

Este modelo de **"núcleo tranquilo, profundidad que se gana"** se concreta en tres profundidades de producto:

- **Tranquila** — la protección por defecto, que simplemente funciona y que todo el mundo ve primero.
- **Celebratoria** — conciencia y disfrute opcionales (rachas, desbloqueos, momentos de éxito). Nunca insiste.
- **Técnica** — DNS, diagnósticos y estadísticas. Invisible hasta que la persona la busca.

Dos reglas transversales de paleta y tono apoyan esta postura de calma:

- **rojo = solo peligro.** El rojo se reserva exclusivamente para el peligro y el error; la paleta tranquila es verde/naranja. Así el rojo mantiene su credibilidad como señal de alarma genuina. El rojo de peligro está tokenizado como `LavaStyle.dangerRed`, con `LavaStyle.errorText` como alias suyo (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) y se utiliza en el texto de error de las vistas. El tinte de protección se resuelve a través de la tabla de roles semántica `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) en lugar de `.green`/`.orange` directos. Aún persisten unos pocos usos de `.red` directo (p. ej. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift); migrarlos a `LavaStyle.dangerRed` es la limpieza que queda pendiente.
- **Sin lenguaje de seguridad cargado de miedo.** Los textos son sencillos, tranquilos y prácticos. Consulta [§4 Textos y nomenclatura](#4-copy-naming).

### La capa tokenizada que existe hoy **(Implementado)**

El sistema de diseño es una capa de SwiftUI real y tokenizada, junto con el vocabulario de profundidad `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — la fuente única de verdad para los colores adaptativos: ~18 colores semánticos (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), cada uno producido por una única fábrica `adaptiveColor(light:dark:)` para que el modo claro y el oscuro se definan juntos. El rojo de peligro se tokeniza aquí como `dangerRed`/`errorText` (líneas 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — roles de superficie de tarjeta/panel/selección y radios de esquina: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — la escala de espaciado: `xs`/`sm`/`md`/`lg`/`xl` más `screenHorizontal`/`screenTop`/`screenBottom`.

La carencia residual que queda es el puñado de usos de `.red` directo aún no migrados a `LavaStyle.dangerRed` (ver §1).

---

## 2. LavaTier — Floor / Window / Workshop **(Implementado)**

`LavaTier` es el vocabulario ligero de profundidad que codifica "núcleo tranquilo, profundidad que se gana" directamente en la capa de tokens. Es un vocabulario más unos pocos valores de token por defecto —no un re-tematizado completo— y se incluye como un enum en lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, cableado en superficies representativas en lugar de adaptar cada vista.

| Nivel | Profundidad | Significado |
|---|---|---|
| **Floor** | tranquila | Protección que simplemente funciona para todo el mundo: la superficie por defecto. |
| **Window** | celebratoria | Conciencia y disfrute opcionales: rachas, desbloqueos, momentos de éxito. Nunca insiste. |
| **Workshop** | técnica | DNS, Estadísticas avanzadas, diagnósticos. Invisible hasta que se busca. |

`LavaTier` es un enum `calm`/`celebratory`/`technical` que lleva valores de token por defecto:

- un **color de acento** (`accent`),
- `allowsDelightMotion` — verdadero solo para celebratoria / Window,
- `usesMonospacedMetadata` — verdadero solo para técnica / Workshop,

expuesto mediante una `EnvironmentKey` más un modificador `.lavaTier(_:)` y un modificador `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). Está cableado en superficies representativas —p. ej. `.lavaTier(.technical)` y `.lavaTier(.celebratory)` en lavasec-ios: LavaSecApp/SettingsView.swift— en lugar de en cada vista. Este alcance deliberado mantiene las tres profundidades de producto legibles en el código y portables a un futuro consumidor de Android sin tener que volver a derivar la intención.

> **Salvedad (tokenización del acento Planeada, Fase 3):** `LavaColorRole` aún no se ha creado, por lo que `LavaTier.accent` todavía se resuelve a colores `LavaStyle` directos (LavaTokens.swift:~230). Trata la tokenización del color de acento como un asunto abierto, no como una superficie terminada.

---

## 3. La mascota Guardián Escudo Suave **(Implementado)**

El **Guardián Escudo Suave** es la mascota de Lava —un escudo redondeado con una cara sencilla que cambia de forma— que expresa visualmente el estado de protección en la pestaña Guard, la Live Activity, la Dynamic Island y el onboarding. Es el portador más visible del tono tranquilo.

El grafo de estados es independiente de la plataforma y reside en `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); el renderizador de SwiftUI es lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 Los 7 estados de expresión

La mascota tiene **exactamente 7** estados de expresión, gobernados por un grafo de estados de transiciones permitidas (`GuardianMascotState.allowedNextStates`, fijado por lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Restricciones del grafo que conviene conocer: la única salida de `sleeping` es `waking`, y `grateful` solo vuelve a `awake`. Las transiciones `awake ↔ grateful` tienen fotogramas de interpolación a medida: este es el único toque de **movimiento de disfrute** del sistema (nivel Window).

> **`retrying` frente a `concerned` — la distinción de tono más importante.** Ambos indican "no del todo en plena salud", pero se leen de forma muy distinta y no deben confundirse:
> - **`retrying`** es la cara *despreocupada y autorreparadora*: párpados relajados (~0,80), ojos a nivel, boca recta y **sin inclinación de preocupación**. El movimiento lo lleva la **insignia de estado, no la cara**: una recuperación transitoria nunca debería alarmar. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** es una preocupación *suave, que pide ayuda*: cejas internas levantadas (`concernAmount` 1, `mouthCurve` -0,22) que se leen como "me vendría bien una mano", **nunca una mirada severa**. Los problemas reales deberían invitar a la ayuda, no reprender. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mapeo de conectividad → expresión (6 → 4)

La salud de la protección se evalúa en `LavaSecCore` como **6 niveles de gravedad de conectividad** + 2 acciones (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Gravedades:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Acciones:** `turnOff`, `reconnect`

La pestaña Guard colapsa esas 6 gravedades en **4 caras** (`guardianState` en lavasec-ios: LavaSecApp/GuardView.swift:122). La cara es, de forma intencionada, una señal *más gruesa y más tranquila* que la insignia de estado: la insignia lleva el detalle, la cara se mantiene simple:

| Condición | Estado de la mascota |
|---|---|
| Pausada temporalmente | `paused` |
| conectado + `healthy` / `usingDeviceDNSFallback` | `awake` |
| conectado + `recovering` / `networkUnavailable` | `retrying` |
| conectado + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| en otro caso | `sleeping` |

> **Reconciliación del tinte.** La granularidad del color de tinte de protección se mantiene reconciliada con esta división de expresiones para que el tinte y la cara nunca se contradigan. Tanto el mapeo de expresiones como la tabla de roles semántica `ProtectionTintRole` ya se incluyen hoy (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, consumida por `AppViewModel.protectionTintRole`). Solo queda **Planeada** la tokenización de roles de color `LavaColorRole` que mapearía los roles a colores totalmente tokenizados (Fase 3 del plan del sistema de diseño).

### 3.3 Aspectos (looks) **(Implementado)**

La mascota se incluye en **7 "aspectos" de escudo seleccionables**, persistidos como `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Cada uno tiene su propia gama de colores y un color de glifo de Dynamic Island a juego:

`original`, `fireOpal` (valor en bruto `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valor en bruto `strawberryObsidian`), `emerald`, `kiwiCreme`.

Los dos valores en bruto heredados son intencionados; no los "arregles": romperían las selecciones de usuario ya persistidas.

### 3.4 Ocultación por privacidad **(Implementado)**

El Guardián respeta la ocultación por privacidad: la expresión puede enmascararse cuando la superficie está oculta por privacidad mientras el **escudo en sí permanece visible** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). La presencia de la protección tranquiliza; la parte que se oculta es el estado emocional concreto.

### 3.5 Lo que no está en este árbol **(Planeado)**

Un mini-juego tipo easter egg en Guard (un toque = animación de gratitud; mantener pulsado 10 s = un juego de atrapar dominios maliciosos) está en **P3 / backlog**. Añadiría expresiones extra de la mascota (`confused` / `dazed` / `inZone` / `powerSurge`) vistas en una rama de funcionalidad; estas **no** están en el target de la app. Según los hechos canónicos, la mascota tiene exactamente **7** estados; no documentes las expresiones del juego como si estuvieran publicadas.

---

## 4. Textos y nomenclatura

### 4.1 Voz y tono

Sencillo, tranquilo, práctico. Evita el lenguaje de seguridad cargado de miedo. Sé honesto sobre el alcance: Lava es **filtrado local de DNS/listas de bloqueo**, no una garantía de que se bloquee todo dominio o URL malicioso, y la protección **nunca** se describe como activada automáticamente en cuanto termina el onboarding: la **pestaña Guard es la autoridad** sobre si la protección está activa en ese momento.

### 4.2 Etiquetas de transporte de DNS

Las anotaciones de transporte siguen una convención compacta estricta (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 y lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, fijada por `DNSResolverPresetTests.swift`):

| Transporte | Etiqueta | Notas |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Basado en URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (sin barra)** | p. ej. "Quad9 (DoH3)". Se anota **solo cuando realmente se observa una negociación h3**: preferido, nunca prometido; en otro caso vuelve a `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS plano | `IP` | |
| resolver del dispositivo | *(sin anotación)* | |

La regla que más se incumple aquí es la del **`DoH3` sin barra**: escribe `DoH3`, nunca `DoH/3` ni `DoH3 (h3)`, y nunca lo apliques de forma especulativa. Estas etiquetas de transporte las emiten `DoHTransport`/`DNSResolverPreset`; mantenlas literales en todos los idiomas, pero ten en cuenta que *no* son entradas del glosario de No-Traducir (ver §4.3).

### 4.3 Términos que no se traducen

Los términos de marca y de protocolo se mantienen literales en **todos** los idiomas. La lista de No-Traducir del glosario de localización es la autoridad, y fija: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

De los transportes de DNS, solo **DoH** es una entrada de No-Traducir del glosario; `DoH3`, `DoT` y `DoQ` son etiquetas de transporte (ver §4.2), no términos del glosario. Aun así se escriben literales, pero no cites el glosario como su fuente.

### 4.4 Encuadre de la seguridad

El pago nunca esquiva la **barrera de protección frente a amenazas** validada por hash y no anulable. Indica la precedencia de forma coherente: **barrera frente a amenazas > lista local de permitidos (excepciones permitidas) > lista de bloqueo > permitir por defecto.**

---

## 5. Experiencia de incorporación (onboarding) **(Implementado)**

La incorporación de primer uso es un flujo de varias páginas —**6 páginas** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`)— implementado en lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Reutiliza el `SoftShieldGuardian` para el momento de aparición del guardián.

Las 6 páginas:

1. **Internet es lava** (`lava`) — el peligro planteado como metáfora; acción principal "Conoce a Lava".
2. **Lava monta guardia aquí** (`guardIntro`) — el momento de aparición del guardián.
3. **Presentación de funciones** (`features`) — lo que hace Lava; "Configurar protección".
4. **Instalar el VPN local de Lava** (`vpn`) — explica por qué iOS dice "VPN" para un túnel de paquetes solo de DNS.
5. **Activar notificaciones** (`notifications`) — la solicitud opcional, presentada en el paso adecuado en lugar de al principio.
6. **Configuración completada** (`done`) — "Abrir Guard", con configuración adicional opcional.

Decisiones de diseño integradas en el flujo:

- **"Usar valores por defecto" es la acción principal; "Personalizar", la secundaria.** Una ruta por defecto sin fricción para personas no técnicas; el control se gana, no se impone.
- **El peligro se plantea como metáfora, no como miedo** ("Internet es lava"), en consonancia con el tono tranquilo.
- **El flujo explica por qué iOS dice "VPN"**: un túnel de paquetes es la única forma de filtrar DNS en todo el sistema; no es un enrutamiento de tráfico.
- **Nunca afirma que la protección se active automáticamente al completar**: Guard sigue siendo la autoridad.
- Botón Atrás solo con chevron, sobre un diseño de página de paso compartido.

Los valores por defecto que el flujo instala en el primer uso: resolver **Device DNS** (`DNSResolverPreset.device`), **reserva de Device DNS ACTIVADA**, registro activado (recuentos + historial + actividad) y "Continuar sin cuenta".

> **Divergencia de la lista de bloqueo por defecto (manda el código).** El texto del plan de onboarding indica HaGeZi Multi Light como lista de bloqueo por defecto, pero el valor por defecto del código publicado es **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definido en lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). El verdadero límite por nivel es el **presupuesto de reglas de filtrado (Free 500K / Plus 2M)**, *no* un recuento de listas. Registrado internamente. Para el modelo de niveles y la configuración por defecto recomendada, consulta [el catálogo de funciones](../product/features.md).

---

## 6. Internacionalización **(En progreso)**

Lava se localiza en **6 idiomas**: **en** (origen) + **ja, zh-Hant, zh-Hans, de, fr**, mediante los catálogos de cadenas de Xcode.

- **La costura de localización es `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, respaldada por `LavaStrings.localized` → `NSLocalizedString` con reserva en inglés; lavasec-ios: LavaSecApp/LavaStrings.swift). **Todos los textos de componentes** deben pasar por ella; sin literales de cadena sueltos en las vistas.
- **zh-Hant** usa una redacción adecuada para Taiwán en la primera pasada.
- Existen metadatos de la App Store para los 6 idiomas.
- Orden de prioridad para la traducción: ja, zh-Hant, zh-Hans, de, fr.

Las bases están listas, pero todavía queda pendiente la revisión completa de traducción humana antes del lanzamiento, por lo que el estado general es **En progreso**.

> **Limpieza del límite de presentación (Planeada, Fase 4).** `LavaSecCore`/`Shared` deberían llevar *semántica* (enums de gravedad/acción, roles de icono), no cadenas en inglés. La presentación del tinte de gravedad ya se ha trasladado al rol semántico `ProtectionTintRole`. Lo que queda como residuo es que los `displayName` de los resolvers siguen siendo cadenas en inglés codificadas a fuego ("Google", "Cloudflare", "Quad9", "Device DNS") en lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. La Fase 4 traslada estas a un mapa de presentación por sistema operativo del lado de la app, correcto tanto para la i18n como para la portabilidad a Android.

Las mecánicas de i18n (el glosario de localización, el esquema del archivo de localización y la lista de comprobación de revisión de traducción) viven en los documentos internos de i18n, no en este conjunto público.

---

## 7. Artefactos de referencia

Referencias de diseño en HTML (no se publican, internas): el storyboard del flujo de onboarding, un estudio del aspecto kiwi-creme del guardián y opciones visuales del botón principal dentro del panel.

La base del sistema de diseño ya está incorporada: el grupo `LavaDesignSystem/`, los tokens `LavaSpacing`/radio/`dangerRed`, la semántica de profundidad `LavaTier` y la capa de roles `LavaIcon` ya se incluyen (lavasec-ios: LavaSecApp/LavaDesignSystem/). Lo que queda como **Planeado** en el plan de portabilidad/base es la tokenización del acento `LavaColorRole` (Fase 3), el mapa de presentación por sistema operativo para las cadenas en inglés del lado del núcleo (Fase 4), un JSON de tokens neutral y multiplataforma, y las costuras más amplias de portabilidad a Android.
