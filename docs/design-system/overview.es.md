---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Sistema de diseño

> **Audiencia:** diseño + ingeniería que trabajan en la app de iOS de Lava Security.
> **Autoridad:** Cuando este documento y un plan no coincidan, **el código manda** — las divergencias se señalan en línea. El estado refleja la realidad confirmada en el código, no la aspiración del plan. Leyenda de estado: **Implementado** (lanzado y confirmado en el código), **En curso** (parcialmente integrado), **Planificado** (diseñado, no construido), **Descartado** (rechazado o revertido).

Este documento cubre la filosofía de diseño, el vocabulario de profundidad LavaTier, la mascota Guardian, las convenciones de texto y nomenclatura, la UX de onboarding y la internacionalización. Para la infraestructura arquitectónica detrás de estas superficies (targets, ciclo de vida del VPN, el cableado del modelo de estado de Guardian/protección), consulta [el cliente de iOS](../architecture/ios-client.md); para el encuadre de producto, consulta [la visión general del producto](../product/overview.md).

---

## 1. Filosofía: núcleo tranquilo, profundidad ganada

La audiencia de Lava son usuarios cotidianos no técnicos — padres, personas mayores — y el diseño parte de ahí. La superficie cotidiana "simplemente funciona" con calma para todos; el detalle adicional, el deleite y el control se revelan (**se ganan**) solo cuando el usuario los busca. Nada incordia, nada alarma, y la maquinaria técnica permanece invisible hasta que se la busca.

Este modelo de **"núcleo tranquilo, profundidad ganada"** se resuelve en tres profundidades de producto:

- **Calm** — la protección por defecto, que simplemente funciona, que todos ven primero.
- **Celebratory** — conciencia y deleite opcionales (rachas, desbloqueos, momentos de éxito). Nunca incordia.
- **Technical** — DNS, diagnósticos y estadísticas. Invisible hasta que el usuario los busca.

Dos reglas transversales de paleta/tono apoyan la postura tranquila:

- **rojo = solo peligro.** El rojo se reserva exclusivamente para peligro y error; la paleta tranquila es verde/naranja. Esto mantiene el rojo fiable como auténtica señal de alarma. El rojo de peligro está tokenizado como `LavaStyle.dangerRed`, con `LavaStyle.errorText` como alias de él (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) y consumido por el texto de error en las vistas. El tinte de protección se resuelve a través de la tabla de roles semántica `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) en lugar de `.green`/`.orange` en crudo. Persisten genuinamente algunos sitios de llamada con `.red` en crudo (p. ej. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrarlos a `LavaStyle.dangerRed` es la limpieza pendiente.
- **Sin lenguaje de seguridad cargado de miedo.** El texto es sencillo, tranquilo y práctico. Consulta [§4 Texto y nomenclatura](#4-texto-y-nomenclatura).

### La capa tokenizada que existe hoy **(Implementado)**

El sistema de diseño es una capa de SwiftUI real y tokenizada, junto al vocabulario de profundidad `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — la fuente de verdad del color adaptativo: ~18 colores semánticos (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), cada uno producido por una única fábrica `adaptiveColor(light:dark:)` para que claro/oscuro se definan juntos. El rojo de peligro está tokenizado aquí como `dangerRed`/`errorText` (líneas 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — roles de superficie de tarjeta/panel/selección y radios de esquina: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — la escala de espaciado: `xs`/`sm`/`md`/`lg`/`xl` más `screenHorizontal`/`screenTop`/`screenBottom`.
- **`LavaActionRole`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift, v1.0) — un enum semántico de rol de acción (`.cancel`, `.close`, `.confirm`, `.destructive`) mapeado al `ButtonRole` del sistema. `NativeToolbarIconButton` incorporó un parámetro `role:` y se usa de forma generalizada, por lo que los glifos de la barra de herramientas adoptan el estilo de rol nativo en casi todas las hojas/barras de herramientas.

La brecha residual restante es el puñado de sitios de llamada con `.red` en crudo que aún no se han migrado a `LavaStyle.dangerRed` (consulta §1).

> **Cambios de componentes (v1.0).** Se eliminó `LavaTabOverviewCard`; los bloques de titular de Filtro y Actividad ahora comparten `LavaInfoCard` + `LavaOverviewMetricBlock` para que coincidan en tamaño y posición. Nuevos componentes compartidos llegaron junto con el rediseño de Filtro/Actividad: `FiltersFlowDiagram` (el diagrama "Teléfono → Lava → Internet"), `ActivityFlowBar` / `ActivityFlowStatRow` (el resumen del flujo de solicitudes), `NetworkActivityPrivacyInfoPanel` y `LavaGuardLookPickerSheet` (el selector de Guard en hoja inferior). Los flujos de importar/compartir reemplazaron su cabecera personalizada dentro del contenido por una `importFlowToolbar` nativa.

---

## 2. LavaTier — Floor / Window / Workshop **(Implementado)**

`LavaTier` es el vocabulario ligero de profundidad que codifica "núcleo tranquilo, profundidad ganada" directamente en la capa de tokens. Es un vocabulario más unos pocos valores por defecto de tokens — no un re-tematizado completo — y se entrega como un enum en lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, cableado en superficies representativas en lugar de readaptar cada vista.

| Tier | Profundidad | Significado |
|---|---|---|
| **Floor** | calm | Protección que simplemente funciona para todos — la superficie por defecto. |
| **Window** | celebratory | Conciencia y deleite opcionales: rachas, desbloqueos, momentos de éxito. Nunca incordia. |
| **Workshop** | technical | DNS, Nerd Stats, diagnósticos. Invisible hasta que se busca. |

`LavaTier` es un enum `calm`/`celebratory`/`technical` que lleva valores por defecto de tokens:

- un **color de acento** (`accent`),
- `allowsDelightMotion` — verdadero solo para celebratory / Window,
- `usesMonospacedMetadata` — verdadero solo para technical / Workshop,

expuesto mediante un `EnvironmentKey` más un modificador `.lavaTier(_:)` y un modificador `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). Está cableado en superficies representativas — p. ej. `.lavaTier(.technical)` y `.lavaTier(.celebratory)` en lavasec-ios: LavaSecApp/SettingsView.swift — en lugar de en cada vista. El alcance deliberado mantiene las tres profundidades de producto legibles en el código y portables a un futuro consumidor Android sin volver a derivar la intención.

> **Salvedad (tokenización de acento Planificada, Fase 3):** `LavaColorRole` aún no se ha creado, por lo que `LavaTier.accent` todavía se resuelve a colores `LavaStyle` en crudo (LavaTokens.swift:~230). Trata la tokenización del color de acento como un cabo suelto, no como una superficie terminada.

---

## 3. La mascota Soft Shield Guardian **(Implementado)**

El **Soft Shield Guardian** es la mascota de Lava — un escudo redondeado con una cara simple y cambiante — que expresa visualmente el estado de protección en la pestaña de Guard, la Live Activity, la Dynamic Island y el onboarding. Es el portador más visible del tono tranquilo.

El grafo de estados es agnóstico de plataforma y vive en `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); el renderizador de SwiftUI es lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 Los 7 estados de expresión

La mascota tiene **exactamente 7** estados de expresión, gobernados por un grafo de estados de transiciones permitidas (`GuardianMascotState.allowedNextStates`, fijado por lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Restricciones del grafo que conviene conocer: la única salida de `sleeping` es `waking`, y `grateful` solo vuelve a `awake`. Las transiciones `awake ↔ grateful` tienen fotogramas de interpolación a medida — este es el único toque de **movimiento de deleite** (nivel Window) del sistema.

> **`retrying` vs `concerned` — la distinción de tono más importante.** Ambos señalan "no del todo en buen estado", pero se leen de forma muy distinta y no deben confundirse:
> - **`retrying`** es la cara *despreocupada, de autorreparación*: párpados relajados (~0,80), ojos nivelados, boca plana y **sin inclinación de preocupación**. El movimiento lo lleva la **insignia de estado, no la cara** — una autorecuperación transitoria nunca debería alarmar. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** es preocupación *suave, que busca ayuda*: cejas internas elevadas (`concernAmount` 1, `mouthCurve` -0,22) que se leen como "me vendría bien una mano", **nunca una mirada severa**. Los problemas genuinos deberían invitar a ayudar, no regañar. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mapeo de conectividad → expresión (6 → 4)

La salud de la protección se evalúa en `LavaSecCore` como **6 severidades de conectividad** + 2 acciones (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Severidades:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Acciones:** `turnOff`, `reconnect`

La pestaña de Guard colapsa esas 6 severidades en **4 caras** (`guardianState` en lavasec-ios: LavaSecApp/GuardView.swift:122). La cara es intencionadamente una señal *más gruesa y tranquila* que la insignia de estado — la insignia lleva el detalle, la cara permanece simple:

| Condición | Estado de la mascota |
|---|---|
| Pausado temporalmente | `paused` |
| conectado + `healthy` / `usingDeviceDNSFallback` | `awake` |
| conectado + `recovering` / `networkUnavailable` | `retrying` |
| conectado + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| en otro caso | `sleeping` |

> **Reconciliación del tinte.** La granularidad del color de tinte de protección se mantiene reconciliada con esta división de expresiones, de modo que tinte y cara nunca discrepen. El mapeo de expresiones y la tabla de roles semántica `ProtectionTintRole` se entregan ambos hoy (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, consumida por `AppViewModel.protectionTintRole`). Solo la tokenización de rol de color `LavaColorRole`, que mapearía los roles a colores totalmente tokenizados, queda **Planificada** (Fase 3 del plan del DS).

### 3.3 Skins (looks) **(Implementado)**

La mascota se entrega en **7 "looks" de escudo seleccionables**, persistidos como `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Cada uno tiene su propia gama de colores y un color de glifo de Dynamic Island emparejado:

`original`, `fireOpal` (valor en crudo `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valor en crudo `strawberryObsidian`), `emerald`, `kiwiCreme`.

Los dos valores en crudo heredados son intencionales — no los "arregles"; romperían las selecciones de usuario persistidas.

### 3.4 Redacción de privacidad **(Implementado)**

El Guardian respeta la redacción de privacidad: la expresión puede enmascararse cuando la superficie está redactada por privacidad mientras el **escudo en sí permanece visible** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). La presencia de la protección es tranquilizadora; el estado emocional específico es la parte que se oculta.

### 3.5 No está en este árbol **(Planificado)**

Un minijuego de easter-egg en Guard (tap = animación de gratitud; pulsación larga de 10s = un juego de atrapar dominios malos) es **P3 / backlog**. Añadiría expresiones extra de la mascota (`confused` / `dazed` / `inZone` / `powerSurge`) vistas en una rama de funcionalidad — estas **no** están en el target de la app. Según los hechos canónicos, la mascota tiene exactamente **7** estados; no documentes las expresiones del juego como lanzadas.

---

## 4. Texto y nomenclatura

### 4.1 Voz y tono

Sencillo, tranquilo, práctico. Evita el lenguaje de seguridad cargado de miedo. Sé honesto sobre el alcance: Lava es **filtrado local de DNS/blocklist**, no una garantía de que todo dominio o URL malicioso quede bloqueado, y la protección **nunca** se describe como activada automáticamente en cuanto se completa el onboarding — la **pestaña de Guard es la autoridad** sobre si la protección está actualmente activa.

### 4.2 Etiquetas de transporte DNS

Las anotaciones de transporte siguen una convención compacta estricta (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 y lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, fijada por `DNSResolverPresetTests.swift`):

| Transporte | Etiqueta | Notas |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Basado en URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (sin barra)** | p. ej. "Quad9 (DoH3)". Anotado **solo cuando realmente se observa una negociación h3** — preferido, nunca prometido; en otro caso recae en `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS simple | `IP` | |
| resolver del dispositivo | *(sin anotación)* | |

La regla que más se rompe aquí es el **`DoH3` sin barra** — escribe `DoH3`, nunca `DoH/3` ni `DoH3 (h3)`, y nunca lo apliques de forma especulativa. Estas etiquetas de transporte se emiten desde `DoHTransport`/`DNSResolverPreset`; mantenlas literales en cada idioma, pero ten en cuenta que *no* son entradas Do-Not-Translate del glosario (consulta §4.3).

### 4.3 Términos Do-Not-Translate

Los términos de marca y protocolo se fijan literales en **todos** los idiomas. La lista Do-Not-Translate del glosario de localización es la autoridad, y fija: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD, AdGuard, 1Hosts, StevenBlack.**

De los transportes DNS, solo **DoH** es una entrada Do-Not-Translate del glosario; `DoH3`, `DoT` y `DoQ` son etiquetas de transporte (consulta §4.2), no términos del glosario. Aun así se escriben literales, pero no cites el glosario como su fuente.

### 4.4 Encuadre de seguridad

El pago nunca evita la **barrera de protección contra amenazas** validada por hash y no anulable. Enuncia la precedencia de forma consistente: **barrera contra amenazas > allowlist local (excepciones permitidas) > blocklist > permitir-por-defecto.**

---

## 5. UX de onboarding **(Implementado)**

El onboarding de primera ejecución es un flujo de varias páginas — **6 páginas** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implementado en lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Reutiliza el `SoftShieldGuardian` para el momento de emergencia del guardian.

Las 6 páginas:

1. **The Internet Is Lava** (`lava`) — el peligro encuadrado como metáfora; acción principal "Meet Lava".
2. **Lava Stands Guard Here** (`guardIntro`) — el momento de emergencia del guardian.
3. **Feature Handoff** (`features`) — lo que hace Lava; "Set Up Protection".
4. **Install Lava's Local VPN** (`vpn`) — explica por qué iOS dice "VPN" para un túnel de paquetes solo de DNS.
5. **Enable Notifications** (`notifications`) — el aviso de opt-in, presentado en el paso adecuado en lugar de al principio.
6. **Setup Complete** (`done`) — "Open Guard", con configuración adicional opcional.

Decisiones de diseño integradas en el flujo:

- **"Use Default" es la acción principal, "Customize" la secundaria.** Una ruta por defecto sin fricción para usuarios no técnicos; el control se gana, no se impone.
- **El peligro encuadrado como metáfora, no como miedo** ("The Internet Is Lava"), coherente con el tono tranquilo.
- **El flujo explica por qué iOS dice "VPN"** — un túnel de paquetes es la única forma de filtrar DNS a nivel de todo el sistema; no es enrutamiento de tráfico.
- **Nunca afirma que la protección esté activada automáticamente al completar** — Guard sigue siendo la autoridad.
- Botón Atrás solo con chevron, sobre un diseño compartido de página de paso.

Los valores por defecto de primera ejecución que instala el flujo: resolver **Device DNS** (`DNSResolverPreset.device`), **fallback de Device DNS ACTIVADO**, registro activado (recuentos + historial + actividad) y "Continue without account."

> **Fuente de verdad de la blocklist por defecto.** El valor por defecto del código lanzado es **Block List Basic** (`AppConfiguration.lavaRecommendedDefaults`, definido en lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). La verdadera puerta de nivel es el **presupuesto de reglas del filtro (Free 500K / Plus 2M)**, *no* un recuento de listas. Para el modelo de niveles y la configuración recomendada por defecto, consulta [el catálogo de funcionalidades](../product/features.md).

---

## 6. Internacionalización **(En curso)**

Lava se localiza en **6 idiomas**: **en** (origen) + **ja, zh-Hant, zh-Hans, de, fr**, mediante catálogos de cadenas de Xcode.

- **La costura de localización es `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, respaldado por `LavaStrings.localized` → `NSLocalizedString` con un fallback en inglés; lavasec-ios: LavaSecApp/LavaStrings.swift). **Todo el texto de componentes** debe pasar por ella — sin literales de cadena desnudos en las vistas.
- **zh-Hant** usa redacción amigable para Taiwán en la primera pasada.
- Existen metadatos de App Store para los 6 idiomas.
- Orden de prioridad para la traducción: ja, zh-Hant, zh-Hans, de, fr.
- El lanzamiento v1.0 incorporó una revisión de catálogo de cadenas de cinco idiomas (≈56 correcciones), y el sustantivo de producto cambió del plural **"Filters"** al singular **"Filter"** en todos los idiomas — mantén las traducciones coherentes con el modelo singular "mi filtro".

Las bases están en su sitio, pero la revisión completa de traducción humana sigue pendiente antes del lanzamiento, por lo que el estado general es **En curso**.

> **Limpieza del límite de presentación (Planificada, Fase 4).** `LavaSecCore`/`Shared` deberían llevar *semántica* (enums de severidad/acción, roles de icono), no cadenas en inglés. La presentación del tinte de severidad ya se ha elevado al semántico `ProtectionTintRole`. El residuo restante es que los `displayName`s de los resolvers siguen siendo cadenas en inglés codificadas en duro ("Google", "Cloudflare", "Quad9", "Device DNS") en lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. La Fase 4 eleva estas a un mapa de presentación por SO en el lado de la app — correcto tanto para i18n como para la portabilidad a Android.

La mecánica de i18n (el glosario de localización, el esquema de archivos de localización y la lista de comprobación de revisión de traducción) vive en los documentos internos de i18n, no en este conjunto público.

---

## 7. Artefactos de referencia

Referencias de diseño en HTML (no lanzadas, internas): el storyboard del flujo de onboarding, un estudio del look del guardian en kiwi-creme y opciones visuales de botón principal dentro del panel.

La base del DS ha llegado: el grupo `LavaDesignSystem/`, los tokens `LavaSpacing`/radio/`dangerRed`, la semántica de profundidad `LavaTier` y la capa de roles `LavaIcon` se entregan todos (lavasec-ios: LavaSecApp/LavaDesignSystem/). Lo que queda **Planificado** en el plan de portabilidad/base es la tokenización de acento `LavaColorRole` (Fase 3), el mapa de presentación por SO para las cadenas en inglés del lado del core (Fase 4), un JSON de tokens neutral multiplataforma y las costuras más amplias de portabilidad a Android.
