---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Sistema de diseño

> **Público:** equipos de diseño e ingeniería que trabajan en la app de iOS de Lava Security.
> **Autoridad:** Cuando este documento y un plan no coincidan, **gana el código** — las divergencias se señalan en el propio texto. El estado refleja la realidad confirmada en el código, no la aspiración del plan. Leyenda de estados: **Implementado** (publicado y confirmado en el código), **En curso** (parcialmente incorporado), **Planeado** (diseñado, no construido), **Descartado** (rechazado o revertido).

Este documento cubre la filosofía de diseño, el vocabulario de profundidad LavaTier, la mascota Guardian, las convenciones de textos y nomenclatura, la experiencia de incorporación (onboarding) y la internacionalización. Para la infraestructura arquitectónica detrás de estas superficies (targets, ciclo de vida del VPN, el cableado del modelo de estado Guardian/protección), consulta [el cliente de iOS](../architecture/ios-client.md); para el enfoque de producto, consulta [la visión general del producto](../product/overview.md).

---

## 1. Filosofía: núcleo tranquilo, profundidad ganada {#1-philosophy-calm-core-earned-depth}

El público de Lava son usuarios cotidianos no técnicos — padres y madres, personas mayores — y el diseño se desprende de eso. La superficie cotidiana "simplemente funciona" con tranquilidad para todo el mundo; el detalle adicional, el deleite y el control se revelan (**se ganan**) solo cuando el usuario va a buscarlos. Nada insiste, nada alarma, y la maquinaria técnica permanece invisible hasta que se la busca.

Este modelo de **"núcleo tranquilo, profundidad ganada"** se resuelve en tres profundidades de producto:

- **Tranquila** — la protección por defecto, que simplemente funciona y todo el mundo ve primero.
- **Celebratoria** — conciencia y deleite opcionales (rachas, desbloqueos, momentos de éxito). Nunca insiste.
- **Técnica** — DNS, diagnósticos y estadísticas. Invisible hasta que el usuario la busca.

Dos reglas transversales de paleta/tono sustentan la postura tranquila:

- **rojo = solo peligro.** El rojo se reserva exclusivamente para el peligro y el error; la paleta tranquila es verde/naranja. Esto mantiene el rojo fiable como señal de alarma genuina. El rojo de peligro está tokenizado como `LavaStyle.dangerRed`, con `LavaStyle.errorText` como alias suyo (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) y lo consume el texto de error en las vistas. El tinte de protección se resuelve a través de la tabla de roles semántica `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) en lugar de `.green`/`.orange` en crudo. Persisten genuinamente unos pocos puntos de llamada con `.red` en crudo (p. ej. lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrarlos a `LavaStyle.dangerRed` es la limpieza pendiente.
- **Sin lenguaje de seguridad cargado de miedo.** Los textos son sencillos, tranquilos y prácticos. Consulta [§4 Textos y nomenclatura](#4-copy-naming).

### La capa tokenizada que existe hoy **(Implementado)** {#the-tokenized-layer-that-exists-today-implemented}

El sistema de diseño es una capa SwiftUI real y tokenizada, junto al vocabulario de profundidad `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — la fuente de verdad de color adaptativo: ~18 colores semánticos (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), cada uno producido por una única factoría `adaptiveColor(light:dark:)` para que el modo claro/oscuro se definan juntos. El rojo de peligro está tokenizado aquí como `dangerRed`/`errorText` (líneas 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — roles de superficie de tarjeta/panel/selección y radios de esquina: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — la escala de espaciado: `xs`/`sm`/`md`/`lg`/`xl` más `screenHorizontal`/`screenTop`/`screenBottom`.
- **`LavaActionRole`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift, v1.0) — un enum semántico de rol de acción (`.cancel`, `.close`, `.confirm`, `.destructive`) mapeado al `ButtonRole` del sistema. `NativeToolbarIconButton` ganó un parámetro `role:` y se usa de forma generalizada, de modo que los glifos de la barra de herramientas adoptan el estilo de rol nativo en casi todas las hojas/barras de herramientas.

La brecha residual que queda es el puñado de puntos de llamada con `.red` en crudo aún no migrados a `LavaStyle.dangerRed` (consulta §1).

> **Rotación de componentes (v1.0).** Se eliminó `LavaTabOverviewCard`; los bloques de titular de Filter y Activity ahora comparten `LavaInfoCard` + `LavaOverviewMetricBlock` para que coincidan en tamaño y posición. Junto al rediseño de Filter/Activity llegaron nuevos componentes compartidos: `FiltersFlowDiagram` (el diagrama "Teléfono → Lava → Internet"), `ActivityFlowBar` / `ActivityFlowStatRow` (el resumen del flujo de solicitudes), `NetworkActivityPrivacyInfoPanel` y `LavaGuardLookPickerSheet` (el selector de Guard en hoja inferior). Los flujos de importar/compartir sustituyeron su cabecera personalizada dentro del contenido por una `importFlowToolbar` nativa.

---

## 2. LavaTier — Floor / Window / Workshop **(Implementado)** {#2-lavatier-floor-window-workshop-implemented}

`LavaTier` es el vocabulario ligero de profundidad que codifica "núcleo tranquilo, profundidad ganada" directamente en la capa de tokens. Es un vocabulario más unos pocos valores por defecto de tokens — no un retematizado completo — y se publica como un enum en lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, cableado en superficies representativas en lugar de readaptar todas las vistas.

| Tier | Profundidad | Significado |
|---|---|---|
| **Floor** | tranquila | Protección que simplemente funciona para todo el mundo — la superficie por defecto. |
| **Window** | celebratoria | Conciencia y deleite opcionales: rachas, desbloqueos, momentos de éxito. Nunca insiste. |
| **Workshop** | técnica | DNS, Nerd Stats, diagnósticos. Invisible hasta que se busca. |

`LavaTier` es un enum `calm`/`celebratory`/`technical` que lleva valores por defecto de tokens:

- un **color de acento** (`accent`),
- `allowsDelightMotion` — verdadero solo para celebratoria / Window,
- `usesMonospacedMetadata` — verdadero solo para técnica / Workshop,

expuesto a través de un `EnvironmentKey` más un modificador `.lavaTier(_:)` y un modificador `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). Está cableado en superficies representativas — p. ej. `.lavaTier(.technical)` y `.lavaTier(.celebratory)` en lavasec-ios: LavaSecApp/SettingsView.swift — en lugar de en todas las vistas. El alcance deliberado mantiene las tres profundidades de producto legibles en el código y portables a un futuro consumidor Android sin tener que volver a derivar la intención.

> **Salvedad (tokenización de acento Planeada, Fase 3):** `LavaColorRole` aún no se ha creado, por lo que `LavaTier.accent` todavía se resuelve a colores `LavaStyle` en crudo (LavaTokens.swift:~230). Trata la tokenización del color de acento como un asunto abierto, no como una superficie terminada.

---

## 3. La mascota Soft Shield Guardian **(Implementado)** {#3-the-soft-shield-guardian-mascot}

El **Soft Shield Guardian** es la mascota de Lava — un escudo redondeado con una cara simple y cambiante — que expresa visualmente el estado de protección en la pestaña Guard, la Live Activity, la Dynamic Island y la incorporación. Es el portador más visible del tono tranquilo.

El grafo de estados es independiente de plataforma y vive en `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); el renderizador SwiftUI es lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 Los 7 estados de expresión {#31-the-7-expression-states}

La mascota tiene **exactamente 7** estados de expresión, regidos por un grafo de estados de transiciones permitidas (`GuardianMascotState.allowedNextStates`, fijado por lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Restricciones del grafo que conviene conocer: la única salida de `sleeping` es `waking`, y `grateful` solo vuelve a `awake`. Las transiciones `awake ↔ grateful` tienen fotogramas de interpolación a medida — este es el único toque de **movimiento de deleite** del sistema (tier Window).

> **`retrying` vs `concerned` — la distinción de tono más importante.** Ambos señalan "no está perfectamente sano", pero se leen de forma muy distinta y no deben confundirse:
> - **`retrying`** es la cara *despreocupada y autorreparadora*: párpados relajados (~0,80), ojos a nivel, una boca plana y **sin inclinación de preocupación**. El movimiento lo lleva la **insignia de estado, no la cara** — una autorecuperación transitoria nunca debería alarmar. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** es una preocupación *suave que pide ayuda*: cejas internas levantadas (`concernAmount` 1, `mouthCurve` -0,22) que se leen como "me vendría bien una mano", **nunca una mirada severa**. Los problemas reales deberían invitar a ayudar, no a regañar. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mapeo conectividad → expresión (6 → 4) {#32-connectivity-expression-mapping-6-4}

La salud de la protección se evalúa en `LavaSecCore` como **6 severidades de conectividad** + 2 acciones (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Severidades:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Acciones:** `turnOff`, `reconnect`

La pestaña Guard colapsa esas 6 severidades en **4 caras** (`guardianState` en lavasec-ios: LavaSecApp/GuardView.swift:122). La cara es intencionadamente una señal *más gruesa y tranquila* que la insignia de estado — la insignia lleva el detalle, la cara se mantiene simple:

| Condición | Estado de la mascota |
|---|---|
| Pausado temporalmente | `paused` |
| conectado + `healthy` / `usingDeviceDNSFallback` | `awake` |
| conectado + `recovering` / `networkUnavailable` | `retrying` |
| conectado + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| en cualquier otro caso | `sleeping` |

> **Reconciliación del tinte.** La granularidad del color de tinte de protección se mantiene reconciliada con esta división de expresiones para que el tinte y la cara nunca se contradigan. El mapeo de expresiones y la tabla de roles semántica `ProtectionTintRole` se publican ambos hoy (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, consumida por `AppViewModel.protectionTintRole`). Solo queda **Planeada** la tokenización de roles de color `LavaColorRole` que mapearía los roles a colores totalmente tokenizados (Fase 3 del plan del DS).

### 3.3 Aspectos (looks) **(Implementado)** {#33-skins-looks-implemented}

La mascota se publica en **7 "aspectos" de escudo seleccionables**, persistidos como `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Cada uno tiene su propia gama de colores y un color de glifo emparejado para la Dynamic Island:

`original`, `fireOpal` (valor en crudo `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valor en crudo `strawberryObsidian`), `emerald`, `kiwiCreme`.

Los dos valores en crudo heredados son intencionados — no los "corrijas"; romperían las selecciones de usuario persistidas.

### 3.4 Redacción por privacidad **(Implementado)** {#34-privacy-redaction-implemented}

El Guardian respeta la redacción por privacidad: la expresión puede enmascararse cuando la superficie está redactada por privacidad mientras el **propio escudo permanece visible** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). La presencia de protección tranquiliza; el estado emocional concreto es la parte que se oculta.

### 3.5 Fuera de este árbol **(Planeado)** {#35-not-in-this-tree-planned}

Un minijuego huevo de pascua en Guard (toque = animación de gratitud; pulsación larga de 10 s = un juego de atrapar dominios maliciosos) está en **P3 / pendientes (backlog)**. Añadiría expresiones extra de la mascota (`confused` / `dazed` / `inZone` / `powerSurge`) vistas en una rama de funcionalidad — estas **no** están en el target de la app. Según los hechos canónicos, la mascota tiene exactamente **7** estados; no documentes las expresiones del juego como publicadas.

---

## 4. Textos y nomenclatura {#4-copy-naming}

### 4.1 Voz y tono {#41-voice-tone}

Sencillos, tranquilos, prácticos. Evita el lenguaje de seguridad cargado de miedo. Sé honesto sobre el alcance: Lava es **filtrado local de DNS/listas de bloqueo**, no una garantía de que todo dominio o URL malicioso quede bloqueado, y la protección **nunca** se describe como activada automáticamente en cuanto termina la incorporación — la **pestaña Guard es la autoridad** sobre si la protección está activa en ese momento.

### 4.2 Etiquetas de transporte DNS {#42-dns-transport-labels}

Las anotaciones de transporte siguen una convención compacta estricta (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 y lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, fijada por `DNSResolverPresetTests.swift`):

| Transporte | Etiqueta | Notas |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Basado en URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (sin barra)** | p. ej. "Quad9 (DoH3)". Se anota **solo cuando realmente se observa una negociación h3** — preferido, nunca prometido; en caso contrario recae en `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS sin cifrar | `IP` | |
| resolver del dispositivo | *(sin anotación)* | |

La regla que más se incumple aquí es la del **`DoH3` sin barra** — escribe `DoH3`, nunca `DoH/3` ni `DoH3 (h3)`, y nunca lo apliques de forma especulativa. Estas etiquetas de transporte las emiten `DoHTransport`/`DNSResolverPreset`; mantenlas literales en todas las configuraciones regionales, pero ten en cuenta que *no* son entradas de No-Traducir del glosario (consulta §4.3).

### 4.3 Términos de No-Traducir {#43-do-not-translate-terms}

Los términos de marca y de protocolo se fijan literalmente en **todas** las configuraciones regionales. La lista de No-Traducir del glosario de localización es la autoridad, y fija: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

De los transportes DNS, solo **DoH** es una entrada de No-Traducir del glosario; `DoH3`, `DoT` y `DoQ` son etiquetas de transporte (consulta §4.2), no términos del glosario. Aun así se escriben literalmente, pero no cites el glosario como su fuente.

### 4.4 Encuadre de seguridad {#44-safety-framing}

El pago nunca sortea el **guardarraíl de amenazas** no anulable y validado por hash. Enuncia la precedencia de forma consistente: **guardarraíl de amenazas > lista de permitidos local (excepciones permitidas) > lista de bloqueo > permitir por defecto.**

---

## 5. Experiencia de incorporación (onboarding) **(Implementado)** {#5-onboarding-ux-implemented}

La incorporación de primera ejecución es un flujo de varias páginas — **6 páginas** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implementado en lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Reutiliza el `SoftShieldGuardian` para el momento de aparición del guardián.

Las 6 páginas:

1. **Internet es lava** (`lava`) — el peligro enmarcado como metáfora; acción principal "Conoce a Lava".
2. **Aquí Lava monta guardia** (`guardIntro`) — el momento de aparición del guardián.
3. **Entrega de funcionalidades** (`features`) — lo que hace Lava; "Configurar protección".
4. **Instala el VPN local de Lava** (`vpn`) — explica por qué iOS dice "VPN" para un túnel de paquetes solo de DNS.
5. **Activa las notificaciones** (`notifications`) — el aviso opcional, presentado en el paso adecuado en lugar de al principio.
6. **Configuración completada** (`done`) — "Abrir Guard", con configuración adicional opcional.

Decisiones de diseño integradas en el flujo:

- **"Usar valores por defecto" es la acción principal, "Personalizar" la secundaria.** Una ruta por defecto sin fricción para usuarios no técnicos; el control se gana, no se impone.
- **El peligro enmarcado como metáfora, no como miedo** ("Internet es lava"), en consonancia con el tono tranquilo.
- **El flujo explica por qué iOS dice "VPN"** — un túnel de paquetes es la única forma de filtrar DNS en todo el sistema; no es enrutamiento de tráfico.
- **Nunca afirma que la protección esté activada automáticamente al completar** — Guard sigue siendo la autoridad.
- Atrás solo con chevrón, sobre un diseño compartido de página de paso.

Los valores por defecto de primera ejecución que instala el flujo: resolver de **DNS del dispositivo** (`DNSResolverPreset.device`), **respaldo de DNS del dispositivo ACTIVADO**, registro activado (recuentos + historial + actividad) y "Continuar sin cuenta".

> **Divergencia de lista de bloqueo por defecto (gana el código).** El texto del plan de incorporación lista HaGeZi Multi Light como lista de bloqueo por defecto, pero el valor por defecto del código publicado es **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definido en lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). El verdadero límite de plan es el **presupuesto de reglas de filtrado (Free 500K / Plus 2M)**, *no* un recuento de listas. Se hace seguimiento internamente. Para el modelo de planes y la configuración recomendada por defecto, consulta [el catálogo de funcionalidades](../product/features.md).

---

## 6. Internacionalización **(En curso)** {#6-internationalization-in-progress}

Lava se localiza en **6 configuraciones regionales**: **en** (fuente) + **ja, zh-Hant, zh-Hans, de, fr**, mediante catálogos de cadenas de Xcode.

- **La costura de localización es `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, respaldada por `LavaStrings.localized` → `NSLocalizedString` con un respaldo en inglés; lavasec-ios: LavaSecApp/LavaStrings.swift). **Todos los textos de componentes** deben pasar por ella — sin literales de cadena sueltos en las vistas.
- **zh-Hant** usa una redacción adaptada a Taiwán en la primera pasada.
- Existen metadatos de App Store para las 6 configuraciones regionales.
- Orden de prioridad para la traducción: ja, zh-Hant, zh-Hans, de, fr.
- La versión v1.0 incorporó una revisión de catálogo de cadenas en cinco configuraciones regionales (≈56 correcciones), y el sustantivo de producto cambió del plural **"Filters"** al singular **"Filter"** en todas las configuraciones regionales — mantén las traducciones coherentes con el modelo singular "mi filtro".

Los cimientos están en su sitio, pero todavía falta la revisión completa de traducción humana antes del lanzamiento, por lo que el estado general es **En curso**.

> **Limpieza del límite de presentación (Planeada, Fase 4).** `LavaSecCore`/`Shared` deberían llevar *semántica* (enums de severidad/acción, roles de icono), no cadenas en inglés. La presentación del tinte de severidad ya se ha elevado al `ProtectionTintRole` semántico. El residuo restante es que los `displayName` de los resolvers siguen siendo cadenas en inglés codificadas a mano ("Google", "Cloudflare", "Quad9", "Device DNS") en lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. La Fase 4 eleva estos a un mapa de presentación del lado de la app por sistema operativo — correcto tanto para la i18n como para la portabilidad a Android.

La mecánica de i18n (el glosario de localización, el esquema de archivos de localización y la lista de comprobación de revisión de traducción) vive en los documentos internos de i18n, no en este conjunto público.

---

## 7. Artefactos de referencia {#7-reference-artifacts}

Referencias de diseño HTML (no se publican, internas): el storyboard del flujo de incorporación, un estudio del aspecto kiwi-creme del guardián y opciones visuales para el botón principal dentro del panel.

Los cimientos del DS ya han llegado: el grupo `LavaDesignSystem/`, los tokens `LavaSpacing`/radio/`dangerRed`, la semántica de profundidad `LavaTier` y la capa de roles `LavaIcon` se publican todos (lavasec-ios: LavaSecApp/LavaDesignSystem/). Lo que queda **Planeado** en el plan de portabilidad/cimientos es la tokenización de acento `LavaColorRole` (Fase 3), el mapa de presentación por sistema operativo para las cadenas en inglés del lado del core (Fase 4), un JSON de tokens neutral multiplataforma y las costuras más amplias de portabilidad a Android.
