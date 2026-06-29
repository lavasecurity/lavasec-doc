---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Design System

> **Público-alvo:** design + engenharia trabalhando no aplicativo iOS da Lava Security.
> **Autoridade:** Onde este documento e um plano divergirem, **o código prevalece** — as divergências são apontadas no texto. O status reflete a realidade confirmada no código, não a aspiração do plano. Legenda de status: **Implementado** (entregue e confirmado no código), **Em andamento** (parcialmente concluído), **Planejado** (projetado, não construído), **Descartado** (rejeitado ou revertido).

Este documento cobre a filosofia de design, o vocabulário de profundidade LavaTier, o mascote Guardian, as convenções de texto e nomenclatura, a UX de onboarding e a internacionalização. Para o encanamento arquitetural por trás dessas superfícies (targets, ciclo de vida da VPN, a fiação do modelo de estado Guardian/proteção), veja [o cliente iOS](../architecture/ios-client.md); para o enquadramento do produto, veja [a visão geral do produto](../product/overview.md).

---

## 1. Filosofia: núcleo calmo, profundidade conquistada

O público da Lava são usuários comuns não técnicos — pais, idosos — e o design decorre disso. A superfície do dia a dia "simplesmente funciona" de forma calma para todos; detalhes adicionais, encanto e controle são revelados (**conquistados**) somente quando o usuário vai atrás deles. Nada incomoda, nada alarma, e a maquinaria técnica permanece invisível até ser buscada.

Esse modelo de **"núcleo calmo, profundidade conquistada"** se resolve em três profundidades de produto:

- **Calmo** — a proteção padrão que simplesmente funciona e que todos veem primeiro.
- **Comemorativo** — consciência e encanto opcionais (sequências, desbloqueios, momentos de sucesso). Nunca incomoda.
- **Técnico** — DNS, diagnósticos e estatísticas. Invisível até o usuário ir atrás.

Duas regras transversais de paleta/tom apoiam a postura calma:

- **vermelho = somente perigo.** O vermelho é reservado exclusivamente para perigo e erro; a paleta calma é verde/laranja. Isso mantém o vermelho confiável como um sinal de alarme genuíno. O vermelho-de-perigo é tokenizado como `LavaStyle.dangerRed`, com `LavaStyle.errorText` definido como alias dele (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) e consumido pelo texto de erro nas views. A cor de destaque da proteção é resolvida através da tabela de papéis semântica `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) em vez de `.green`/`.orange` puros. Alguns poucos pontos de chamada `.red` puro genuinamente persistem (por exemplo, lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrar esses para `LavaStyle.dangerRed` é a limpeza restante.
- **Sem linguagem de segurança carregada de medo.** O texto é simples, calmo e prático. Veja [§4 Texto e nomenclatura](#4-copy-naming).

### A camada tokenizada que existe hoje **(Implementado)**

O design system é uma camada SwiftUI real e tokenizada, ao lado do vocabulário de profundidade `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — a fonte da verdade de cores adaptativas: ~18 cores semânticas (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), cada uma produzida por uma única fábrica `adaptiveColor(light:dark:)` para que claro/escuro sejam definidos juntos. O vermelho-de-perigo é tokenizado aqui como `dangerRed`/`errorText` (linhas 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — papéis de superfície de card/painel/seleção e raios de canto: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — a escala de espaçamento: `xs`/`sm`/`md`/`lg`/`xl` mais `screenHorizontal`/`screenTop`/`screenBottom`.
- **`LavaActionRole`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift, v1.0) — um enum semântico de papel de ação (`.cancel`, `.close`, `.confirm`, `.destructive`) mapeado para o `ButtonRole` do sistema. `NativeToolbarIconButton` ganhou um parâmetro `role:` e é usado de forma generalizada, então os glifos da toolbar adotam o estilo nativo por papel em quase toda sheet/toolbar.

A lacuna residual restante é o punhado de pontos de chamada `.red` puro ainda não migrados para `LavaStyle.dangerRed` (veja §1).

> **Rotatividade de componentes (v1.0).** `LavaTabOverviewCard` foi removido; os blocos de cabeçalho de Filtro e Atividade agora compartilham `LavaInfoCard` + `LavaOverviewMetricBlock` para que se alinhem em tamanho e posição. Novos componentes compartilhados chegaram junto com a redesenhação de Filtro/Atividade: `FiltersFlowDiagram` (o diagrama "Telefone → Lava → Internet"), `ActivityFlowBar` / `ActivityFlowStatRow` (o resumo de fluxo de requisições), `NetworkActivityPrivacyInfoPanel` e `LavaGuardLookPickerSheet` (o seletor de Guard em bottom-sheet). Os fluxos de importar/compartilhar substituíram seu cabeçalho personalizado no conteúdo por um `importFlowToolbar` nativo.

---

## 2. LavaTier — Floor / Window / Workshop **(Implementado)**

`LavaTier` é o vocabulário de profundidade leve que codifica "núcleo calmo, profundidade conquistada" diretamente na camada de tokens. É um vocabulário mais alguns padrões de tokens — não um re-tema completo — e é entregue como um enum em lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, conectado a superfícies representativas em vez de readaptar cada view.

| Tier | Profundidade | Significado |
|---|---|---|
| **Floor** | calmo | Proteção que simplesmente funciona para todos — a superfície padrão. |
| **Window** | comemorativo | Consciência e encanto opcionais: sequências, desbloqueios, momentos de sucesso. Nunca incomoda. |
| **Workshop** | técnico | DNS, Nerd Stats, diagnósticos. Invisível até ser buscado. |

`LavaTier` é um enum `calm`/`celebratory`/`technical` que carrega padrões de tokens:

- uma **cor de destaque** (`accent`),
- `allowsDelightMotion` — verdadeiro somente para comemorativo / Window,
- `usesMonospacedMetadata` — verdadeiro somente para técnico / Workshop,

exposto via um `EnvironmentKey` mais um modificador `.lavaTier(_:)` e um modificador `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). Ele é conectado a superfícies representativas — por exemplo, `.lavaTier(.technical)` e `.lavaTier(.celebratory)` em lavasec-ios: LavaSecApp/SettingsView.swift — e não a todas as views. O escopo deliberado mantém as três profundidades de produto legíveis no código e portáveis para um futuro consumidor Android sem rederivar a intenção.

> **Ressalva (tokenização do destaque Planejada, Fase 3):** `LavaColorRole` ainda não foi criado, então `LavaTier.accent` ainda resolve para cores `LavaStyle` puras (LavaTokens.swift:~230). Trate a tokenização da cor de destaque como um ciclo aberto, não como uma superfície finalizada.

---

## 3. O mascote Soft Shield Guardian **(Implementado)**

O **Soft Shield Guardian** é o mascote da Lava — um escudo arredondado com um rosto simples que se transforma — que expressa visualmente o estado da proteção na aba Guard, na Live Activity, na Dynamic Island e no onboarding. É o portador mais visível do tom calmo.

O grafo de estados é agnóstico de plataforma, residindo em `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); o renderizador SwiftUI é lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 Os 7 estados de expressão

O mascote tem **exatamente 7** estados de expressão, governados por um grafo de estados de transições permitidas (`GuardianMascotState.allowedNextStates`, travado por lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Restrições do grafo que vale conhecer: a única saída de `sleeping` é `waking`, e `grateful` só retorna para `awake`. As transições `awake ↔ grateful` têm quadros de interpolação sob medida — este é o único pedaço de **movimento de encanto** do sistema (tier Window).

> **`retrying` vs `concerned` — a distinção de tom mais importante.** Ambos sinalizam "não perfeitamente saudável", mas se leem de forma muito diferente e não devem ser confundidos:
> - **`retrying`** é o rosto *despreocupado e autocurativo*: pálpebras relaxadas (~0,80), olhos nivelados, boca reta e **sem inclinação de preocupação**. O movimento é carregado pelo **selo de status, não pelo rosto** — a autorrecuperação transitória nunca deve alarmar. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** é uma preocupação *gentil, que pede ajuda*: sobrancelhas internas erguidas (`concernAmount` 1, `mouthCurve` -0.22) lendo-se como "eu poderia usar uma mãozinha", **nunca um olhar severo**. Problemas genuínos devem convidar à ajuda, não repreender. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mapeamento conectividade → expressão (6 → 4)

A saúde da proteção é avaliada em `LavaSecCore` como **6 severidades de conectividade** + 2 ações (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Severidades:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Ações:** `turnOff`, `reconnect`

A aba Guard colapsa essas 6 severidades em **4 rostos** (`guardianState` em lavasec-ios: LavaSecApp/GuardView.swift:122). O rosto é intencionalmente um sinal *mais grosseiro e mais calmo* que o selo de status — o selo carrega o detalhe, o rosto permanece simples:

| Condição | Estado do mascote |
|---|---|
| Pausado temporariamente | `paused` |
| conectado + `healthy` / `usingDeviceDNSFallback` | `awake` |
| conectado + `recovering` / `networkUnavailable` | `retrying` |
| conectado + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| caso contrário | `sleeping` |

> **Reconciliação da cor de destaque.** A granularidade da cor de destaque da proteção permanece reconciliada com essa divisão de expressões, para que a cor e o rosto nunca discordem. O mapeamento de expressões e a tabela de papéis semântica `ProtectionTintRole` ambos são entregues hoje (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, consumido por `AppViewModel.protectionTintRole`). Apenas a tokenização de papel de cor `LavaColorRole` que mapearia papéis para cores totalmente tokenizadas permanece **Planejada** (Fase 3 do plano do DS).

### 3.3 Skins (looks) **(Implementado)**

O mascote é entregue em **7 "looks" de escudo selecionáveis**, persistidos como `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Cada um tem sua própria combinação de cores e uma cor de glifo da Dynamic Island pareada:

`original`, `fireOpal` (valor bruto `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valor bruto `strawberryObsidian`), `emerald`, `kiwiCreme`.

Os dois valores brutos legados são intencionais — não os "corrija"; eles quebrariam as seleções de usuário persistidas.

### 3.4 Redação de privacidade **(Implementado)**

O Guardian honra a redação de privacidade: a expressão pode ser mascarada quando a superfície está com a privacidade redigida enquanto o **próprio escudo permanece visível** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). A presença da proteção é tranquilizadora; o estado emocional específico é a parte que se esconde.

### 3.5 Fora desta árvore **(Planejado)**

Um mini-jogo easter-egg do Guard (toque = animação de gratidão; pressionar por 10s = um jogo de pegar-domínios-maus) é **P3 / backlog**. Ele adicionaria expressões extras do mascote (`confused` / `dazed` / `inZone` / `powerSurge`) vistas em um branch de funcionalidade — essas **não** estão no target do app. Conforme os fatos canônicos, o mascote tem exatamente **7** estados; não documente as expressões do jogo como entregues.

---

## 4. Texto e nomenclatura

### 4.1 Voz e tom

Simples, calmo, prático. Evite linguagem de segurança carregada de medo. Seja honesto sobre o escopo: a Lava é **filtragem local de DNS/blocklist**, não uma garantia de que todo domínio ou URL malicioso seja bloqueado, e a proteção **nunca** é descrita como automaticamente ativada no momento em que o onboarding termina — a **aba Guard é a autoridade** sobre se a proteção está atualmente ativa.

### 4.2 Rótulos de transporte de DNS

As anotações de transporte seguem uma convenção compacta estrita (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 e lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, travada por `DNSResolverPresetTests.swift`):

| Transporte | Rótulo | Notas |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Baseado em URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (sem barra)** | por exemplo, "Quad9 (DoH3)". Anotado **somente quando uma negociação h3 é de fato observada** — preferido, nunca prometido; caso contrário, recai para `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS simples | `IP` | |
| resolvedor do dispositivo | *(sem anotação)* | |

A regra mais quebrada aqui é o **`DoH3` sem barra** — escreva `DoH3`, nunca `DoH/3` ou `DoH3 (h3)`, e nunca o aplique especulativamente. Esses rótulos de transporte são emitidos por `DoHTransport`/`DNSResolverPreset`; mantenha-os literais em todos os locais, mas note que eles *não* são entradas Não-Traduzir do glossário (veja §4.3).

### 4.3 Termos Não-Traduzir

Termos de marca e protocolo são fixados literalmente em **todos** os locais. A lista Não-Traduzir do glossário de localização é a autoridade, e ela fixa: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD, AdGuard, 1Hosts, StevenBlack.**

Dos transportes de DNS, apenas **DoH** é uma entrada Não-Traduzir do glossário; `DoH3`, `DoT` e `DoQ` são rótulos de transporte (veja §4.2), não termos do glossário. Eles ainda são escritos literalmente, mas não cite o glossário como sua fonte.

### 4.4 Enquadramento de segurança

O pagamento nunca contorna o **guardrail de ameaças** não permissível e validado por hash. Declare a precedência de forma consistente: **guardrail de ameaças > allowlist local (exceções permitidas) > blocklist > permissão por padrão.**

---

## 5. UX de onboarding **(Implementado)**

O onboarding de primeira execução é um fluxo de múltiplas páginas — **6 páginas** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implementado em lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Ele reutiliza o `SoftShieldGuardian` para o momento de emergência do guardião.

As 6 páginas:

1. **A Internet É Lava** (`lava`) — perigo enquadrado como metáfora; ação primária "Conhecer a Lava".
2. **A Lava Monta Guarda Aqui** (`guardIntro`) — o momento de emergência do guardião.
3. **Apresentação de Funcionalidades** (`features`) — o que a Lava faz; "Configurar Proteção".
4. **Instalar a VPN Local da Lava** (`vpn`) — explica por que o iOS diz "VPN" para um túnel de pacotes somente-DNS.
5. **Ativar Notificações** (`notifications`) — o prompt opcional, apresentado no passo certo em vez de logo de cara.
6. **Configuração Concluída** (`done`) — "Abrir Guard", com configuração adicional opcional.

Decisões de design embutidas no fluxo:

- **"Usar Padrão" é a ação primária, "Personalizar" a secundária.** Um caminho padrão sem atrito para usuários não técnicos; o controle é conquistado, não forçado.
- **Perigo enquadrado como metáfora, não como medo** ("A Internet É Lava"), consistente com o tom calmo.
- **O fluxo explica por que o iOS diz "VPN"** — um túnel de pacotes é a única forma de filtrar DNS em todo o sistema; não é roteamento de tráfego.
- **Nunca afirma que a proteção está automaticamente ativada ao concluir** — o Guard permanece a autoridade.
- Voltar apenas por chevron, em um layout de página de passo compartilhado.

Os padrões de primeira execução que o fluxo instala: resolvedor **Device DNS** (`DNSResolverPreset.device`), **fallback de Device DNS ATIVADO**, registro ativado (contagens + histórico + atividade) e "Continuar sem conta".

> **Fonte da verdade da blocklist padrão.** O padrão entregue no código é **Block List Basic** (`AppConfiguration.lavaRecommendedDefaults`, definido em lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). O verdadeiro portão de tier é o **orçamento de regras de filtro (Free 500K / Plus 2M)**, *não* uma contagem de listas. Para o modelo de tiers e a configuração recomendada por padrão, veja [o catálogo de funcionalidades](../product/features.md).

---

## 6. Internacionalização **(Em andamento)**

A Lava localiza em **6 locais**: **en** (fonte) + **ja, zh-Hant, zh-Hans, de, fr**, via catálogos de strings do Xcode.

- **A costura de localização é `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, apoiada por `LavaStrings.localized` → `NSLocalizedString` com fallback em inglês; lavasec-ios: LavaSecApp/LavaStrings.swift). **Todo o texto de componentes** deve passar por ela — sem literais de string crus nas views.
- **zh-Hant** usa redação amigável a Taiwan na primeira passagem.
- Os metadados da App Store existem para todos os 6 locais.
- Ordem de prioridade para tradução: ja, zh-Hant, zh-Hans, de, fr.
- O lançamento v1.0 incorporou uma revisão de catálogo de strings de cinco locais (≈56 correções), e o substantivo do produto mudou de plural **"Filters"** para singular **"Filter"** em todos os locais — mantenha as traduções consistentes com o modelo singular "meu filtro".

As fundações estão no lugar, mas a revisão completa de tradução humana ainda está pendente antes do lançamento, então o status geral é **Em andamento**.

> **Limpeza de fronteira de apresentação (Planejada, Fase 4).** `LavaSecCore`/`Shared` devem carregar *semântica* (enums de severidade/ação, papéis de ícones), não strings em inglês. A apresentação da cor de destaque por severidade já foi elevada para o `ProtectionTintRole` semântico. O residual restante é que os `displayName`s de resolvedores ainda são strings em inglês codificadas ("Google", "Cloudflare", "Quad9", "Device DNS") em lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. A Fase 4 eleva esses para um mapa de apresentação por SO no lado do app — correto tanto para i18n quanto para portabilidade Android.

A mecânica de i18n (o glossário de localização, o esquema de arquivos de localização e a checklist de revisão de tradução) reside nos documentos internos de i18n, não neste conjunto público.

---

## 7. Artefatos de referência

Referências de design em HTML (não entregues, internas): o storyboard do fluxo de onboarding, um estudo de look do guardião kiwi-creme e opções visuais de botão primário dentro do painel.

A fundação do DS chegou: o grupo `LavaDesignSystem/`, os tokens `LavaSpacing`/raio/`dangerRed`, a semântica de profundidade `LavaTier` e a camada de papel `LavaIcon` todos são entregues (lavasec-ios: LavaSecApp/LavaDesignSystem/). O que permanece **Planejado** no plano de portabilidade/fundação é a tokenização do destaque `LavaColorRole` (Fase 3), o mapa de apresentação por SO para as strings em inglês do lado do core (Fase 4), um JSON de tokens neutro multiplataforma e as costuras mais amplas de portabilidade Android.
