---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Design System

> **Público:** design + engenharia trabalhando no app iOS da Lava Security.
> **Autoridade:** Onde este documento e um plano divergirem, **o código prevalece** — as divergências são apontadas ao longo do texto. O status reflete a realidade confirmada no código, não a aspiração do plano. Legenda de status: **Implementado** (lançado e confirmado no código), **Em andamento** (parcialmente concluído), **Planejado** (projetado, mas não construído), **Descartado** (rejeitado ou revertido).

Este documento cobre a filosofia de design, o vocabulário de profundidade LavaTier, o mascote Guardião, as convenções de texto e nomenclatura, a UX de integração e a internacionalização. Para o encanamento arquitetural por trás dessas superfícies (targets, ciclo de vida da VPN, a ligação do modelo de estado de Guardião/proteção), veja [o cliente iOS](../architecture/ios-client.md); para o enquadramento do produto, veja [a visão geral do produto](../product/overview.md).

---

## 1. Filosofia: núcleo tranquilo, profundidade conquistada

O público da Lava é formado por pessoas comuns, não técnicas — pais, mães, pessoas mais velhas — e o design parte disso. A superfície do dia a dia "simplesmente funciona" de forma tranquila para todo mundo; detalhes adicionais, encanto e controle são revelados (**conquistados**) apenas quando a pessoa vai atrás deles. Nada incomoda, nada alarma, e a maquinaria técnica permanece invisível até que se vá procurá-la.

Esse modelo de **"núcleo tranquilo, profundidade conquistada"** se desdobra em três profundidades de produto:

- **Tranquilo** — a proteção padrão, que simplesmente funciona e que todo mundo vê primeiro.
- **Comemorativo** — consciência e encanto opcionais (sequências, desbloqueios, momentos de sucesso). Nunca incomoda.
- **Técnico** — DNS, diagnósticos e estatísticas. Invisível até a pessoa ir procurar.

Duas regras transversais de paleta/tom dão suporte a essa postura tranquila:

- **vermelho = somente perigo.** O vermelho é reservado exclusivamente para perigo e erro; a paleta tranquila é verde/laranja. Isso mantém o vermelho confiável como um sinal de alarme genuíno. O vermelho de perigo é tokenizado como `LavaStyle.dangerRed`, com `LavaStyle.errorText` apontando para ele (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) e consumido pelo texto de erro nas views. O tom de proteção é resolvido pela tabela de papéis semânticos `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7) em vez de `.green`/`.orange` puros. Alguns poucos pontos de chamada `.red` puros realmente persistem (por exemplo, lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrar esses para `LavaStyle.dangerRed` é a limpeza que falta.
- **Sem linguagem de segurança que apela ao medo.** O texto é simples, tranquilo e prático. Veja [§4 Texto e nomenclatura](#4-copy-naming).

### A camada tokenizada que existe hoje **(Implementado)**

O design system é uma camada SwiftUI real e tokenizada, ao lado do vocabulário de profundidade `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — a fonte da verdade para cores adaptativas: ~18 cores semânticas (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), cada uma produzida por uma única fábrica `adaptiveColor(light:dark:)`, para que claro/escuro sejam definidos juntos. O vermelho de perigo é tokenizado aqui como `dangerRed`/`errorText` (linhas 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — papéis de superfície de cartão/painel/seleção e raios de canto: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — a escala de espaçamento: `xs`/`sm`/`md`/`lg`/`xl` mais `screenHorizontal`/`screenTop`/`screenBottom`.
- **`LavaActionRole`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaScaffold.swift, v1.0) — um enum semântico de papel de ação (`.cancel`, `.close`, `.confirm`, `.destructive`) mapeado para o `ButtonRole` do sistema. O `NativeToolbarIconButton` ganhou um parâmetro `role:` e é usado de forma generalizada, então os ícones da barra de ferramentas adotam o estilo nativo de papel em quase todas as folhas/barras de ferramentas.

A lacuna residual que falta é o punhado de pontos de chamada `.red` puros ainda não migrados para `LavaStyle.dangerRed` (veja §1).

> **Rotatividade de componentes (v1.0).** O `LavaTabOverviewCard` foi removido; os blocos de manchete de Filtro e Atividade agora compartilham `LavaInfoCard` + `LavaOverviewMetricBlock`, de modo que ficam alinhados em tamanho e posição. Novos componentes compartilhados chegaram junto com o redesign de Filtro/Atividade: `FiltersFlowDiagram` (o diagrama "Telefone → Lava → Internet"), `ActivityFlowBar` / `ActivityFlowStatRow` (o resumo do fluxo de requisições), `NetworkActivityPrivacyInfoPanel` e `LavaGuardLookPickerSheet` (o seletor de Guarda em folha inferior). Os fluxos de importação/compartilhamento substituíram seu cabeçalho personalizado no conteúdo por um `importFlowToolbar` nativo.

---

## 2. LavaTier — Piso / Janela / Oficina **(Implementado)**

`LavaTier` é o vocabulário leve de profundidade que codifica "núcleo tranquilo, profundidade conquistada" diretamente na camada de tokens. É um vocabulário mais alguns padrões de token — não um re-tema completo — e vem como um enum em lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, ligado a superfícies representativas em vez de adaptar cada view.

| Tier | Profundidade | Significado |
|---|---|---|
| **Piso** | tranquilo | Proteção que simplesmente funciona para todo mundo — a superfície padrão. |
| **Janela** | comemorativo | Consciência e encanto opcionais: sequências, desbloqueios, momentos de sucesso. Nunca incomoda. |
| **Oficina** | técnico | DNS, Nerd Stats, diagnósticos. Invisível até ser procurado. |

`LavaTier` é um enum `calm`/`celebratory`/`technical` que carrega padrões de token:

- uma **cor de destaque** (`accent`),
- `allowsDelightMotion` — verdadeiro apenas para comemorativo / Janela,
- `usesMonospacedMetadata` — verdadeiro apenas para técnico / Oficina,

exposto via uma `EnvironmentKey` mais um modificador `.lavaTier(_:)` e um modificador `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). É ligado a superfícies representativas — por exemplo, `.lavaTier(.technical)` e `.lavaTier(.celebratory)` em lavasec-ios: LavaSecApp/SettingsView.swift — em vez de cada view. O escopo deliberado mantém as três profundidades de produto legíveis no código e portáveis para um futuro consumidor Android sem reconstruir a intenção.

> **Ressalva (tokenização de destaque Planejada, Fase 3):** o `LavaColorRole` ainda não foi criado, então `LavaTier.accent` ainda resolve para cores `LavaStyle` puras (LavaTokens.swift:~230). Trate a tokenização da cor de destaque como um ciclo em aberto, não uma superfície finalizada.

---

## 3. O mascote Guardião Escudo Suave **(Implementado)**

O **Guardião Escudo Suave** é o mascote da Lava — um escudo arredondado com um rosto simples e que se transforma — que expressa visualmente o estado de proteção na aba Guarda, na Live Activity, na Dynamic Island e na integração. É o portador mais visível do tom tranquilo.

O grafo de estados é independente de plataforma e vive em `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); o renderizador SwiftUI é lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 Os 7 estados de expressão

O mascote tem **exatamente 7** estados de expressão, governados por um grafo de estados com transições permitidas (`GuardianMascotState.allowedNextStates`, travado por lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Restrições do grafo que vale conhecer: a única saída de `sleeping` é `waking`, e `grateful` só retorna para `awake`. As transições `awake ↔ grateful` têm quadros de interpolação sob medida — esse é o único toque de **movimento de encanto** do sistema (tier Janela).

> **`retrying` vs `concerned` — a distinção de tom mais importante.** Ambos sinalizam "não perfeitamente saudável", mas se leem de forma muito diferente e não devem ser confundidos:
> - **`retrying`** é o rosto *despreocupado, que se autorrecupera*: pálpebras relaxadas (~0,80), olhos nivelados, boca reta e **sem inclinação de preocupação**. O movimento é carregado pelo **selo de status, não pelo rosto** — a autorrecuperação transitória nunca deve alarmar. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** é uma preocupação *gentil, que pede ajuda*: sobrancelhas internas levantadas (`concernAmount` 1, `mouthCurve` -0,22) que leem como "uma ajudinha cairia bem", **nunca um olhar severo**. Problemas genuínos devem convidar à ajuda, não repreender. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mapeamento conectividade → expressão (6 → 4)

A saúde da proteção é avaliada em `LavaSecCore` como **6 severidades de conectividade** + 2 ações (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Severidades:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Ações:** `turnOff`, `reconnect`

A aba Guarda condensa essas 6 severidades em **4 rostos** (`guardianState` em lavasec-ios: LavaSecApp/GuardView.swift:122). O rosto é intencionalmente um sinal *mais grosseiro e mais tranquilo* do que o selo de status — o selo carrega o detalhe, o rosto fica simples:

| Condição | Estado do mascote |
|---|---|
| Pausado temporariamente | `paused` |
| conectado + `healthy` / `usingDeviceDNSFallback` | `awake` |
| conectado + `recovering` / `networkUnavailable` | `retrying` |
| conectado + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| caso contrário | `sleeping` |

> **Reconciliação de tom.** A granularidade da cor de tom de proteção permanece reconciliada com essa divisão de expressões, para que tom e rosto nunca discordem. O mapeamento de expressões e a tabela de papéis semânticos `ProtectionTintRole` ambos já estão no app hoje (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, consumido por `AppViewModel.protectionTintRole`). Falta apenas a tokenização de papel de cor `LavaColorRole`, que mapearia papéis para cores totalmente tokenizadas, e que permanece **Planejada** (Fase 3 do plano do DS).

### 3.3 Skins (looks) **(Implementado)**

O mascote vem em **7 "looks" de escudo selecionáveis**, persistidos como `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Cada um tem sua própria combinação de cores e uma cor de glifo da Dynamic Island pareada:

`original`, `fireOpal` (valor bruto `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valor bruto `strawberryObsidian`), `emerald`, `kiwiCreme`.

Os dois valores brutos legados são intencionais — não os "conserte"; isso quebraria as seleções de usuário já persistidas.

### 3.4 Redação de privacidade **(Implementado)**

O Guardião respeita a redação de privacidade: a expressão pode ser mascarada quando a superfície está com privacidade redigida, enquanto o **próprio escudo permanece visível** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). A presença da proteção é reconfortante; o estado emocional específico é a parte que se esconde.

### 3.5 Fora desta árvore **(Planejado)**

Um mini-jogo easter-egg na Guarda (toque = animação de gratidão; pressionar e segurar por 10s = um jogo de capturar domínios ruins) é **P3 / backlog**. Ele adicionaria expressões extras de mascote (`confused` / `dazed` / `inZone` / `powerSurge`) vistas em um branch de feature — essas **não** estão no target do app. Pelos fatos canônicos, o mascote tem exatamente **7** estados; não documente as expressões do jogo como lançadas.

---

## 4. Texto e nomenclatura {#4-copy-naming}

### 4.1 Voz e tom

Simples, tranquilo, prático. Evite linguagem de segurança que apela ao medo. Seja honesto sobre o alcance: a Lava é **filtragem local de DNS/blocklist**, não uma garantia de que todo domínio ou URL malicioso seja bloqueado, e a proteção **nunca** é descrita como ativada automaticamente no momento em que a integração termina — a **aba Guarda é a autoridade** sobre se a proteção está ativa no momento.

### 4.2 Rótulos de transporte de DNS

As anotações de transporte seguem uma convenção compacta e rígida (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 e lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, travada por `DNSResolverPresetTests.swift`):

| Transporte | Rótulo | Notas |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Baseado em URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (sem barra)** | por exemplo, "Quad9 (DoH3)". Anotado **apenas quando uma negociação h3 é de fato observada** — preferido, nunca prometido; caso contrário, recai para `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS comum | `IP` | |
| resolvedor do dispositivo | *(sem anotação)* | |

A regra mais quebrada aqui é o **`DoH3` sem barra** — escreva `DoH3`, nunca `DoH/3` ou `DoH3 (h3)`, e nunca o aplique de forma especulativa. Esses rótulos de transporte são emitidos por `DoHTransport`/`DNSResolverPreset`; mantenha-os literais em todos os locais, mas note que eles *não* são entradas Não-Traduzir do glossário (veja §4.3).

### 4.3 Termos a Não Traduzir

Termos de marca e protocolo ficam fixados literalmente em **todos** os locais. A lista Não-Traduzir do glossário de localização é a autoridade, e ela fixa: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

Dos transportes de DNS, apenas **DoH** é uma entrada Não-Traduzir do glossário; `DoH3`, `DoT` e `DoQ` são rótulos de transporte (veja §4.2), não termos do glossário. Eles ainda são escritos literalmente, mas não cite o glossário como sua fonte.

### 4.4 Enquadramento de segurança

O pagamento nunca contorna a **barreira de proteção contra ameaças**, validada por hash e não dispensável. Declare a precedência de forma consistente: **barreira de ameaças > lista de permissões local (exceções permitidas) > blocklist > permitir-por-padrão.**

---

## 5. UX de integração **(Implementado)**

A integração de primeira execução é um fluxo de várias páginas — **6 páginas** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implementado em lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Ela reutiliza o `SoftShieldGuardian` para o momento de surgimento do guardião.

As 6 páginas:

1. **A Internet É Lava** (`lava`) — perigo enquadrado como metáfora; ação principal "Conhecer a Lava".
2. **A Lava Monta Guarda Aqui** (`guardIntro`) — o momento de surgimento do guardião.
3. **Apresentação de Funcionalidades** (`features`) — o que a Lava faz; "Configurar Proteção".
4. **Instalar a VPN Local da Lava** (`vpn`) — explica por que o iOS diz "VPN" para um túnel de pacotes só de DNS.
5. **Ativar Notificações** (`notifications`) — o pedido de opt-in, apresentado na etapa certa em vez de logo no começo.
6. **Configuração Concluída** (`done`) — "Abrir Guarda", com configuração adicional opcional.

Decisões de design embutidas no fluxo:

- **"Usar Padrão" é a ação principal, "Personalizar" a secundária.** Um caminho padrão sem atrito para pessoas não técnicas; o controle é conquistado, não forçado.
- **Perigo enquadrado como metáfora, não como medo** ("A Internet É Lava"), em linha com o tom tranquilo.
- **O fluxo explica por que o iOS diz "VPN"** — um túnel de pacotes é a única forma de filtrar DNS em todo o sistema; não é roteamento de tráfego.
- **Nunca afirma que a proteção está ativa automaticamente ao concluir** — a Guarda continua sendo a autoridade.
- Voltar apenas por chevron, em um layout de página de etapa compartilhado.

Os padrões de primeira execução que o fluxo instala: resolvedor **Device DNS** (`DNSResolverPreset.device`), **fallback de Device DNS ATIVADO**, registro ativo (contagens + histórico + atividade) e "Continuar sem conta".

> **Divergência de blocklist padrão (o código prevalece).** O texto do plano de integração lista o HaGeZi Multi Light como blocklist padrão, mas o padrão do código lançado é **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definido em lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). O verdadeiro portão de tier é o **orçamento de regras de filtro (Free 500K / Plus 2M)**, *não* uma contagem de listas. Acompanhado internamente. Para o modelo de tiers e a configuração de padrão recomendado, veja [o catálogo de funcionalidades](../product/features.md).

---

## 6. Internacionalização **(Em andamento)**

A Lava é localizada em **6 locais**: **en** (origem) + **ja, zh-Hant, zh-Hans, de, fr**, via catálogos de strings do Xcode.

- **A junção de localização é `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, apoiado por `LavaStrings.localized` → `NSLocalizedString` com fallback para o inglês; lavasec-ios: LavaSecApp/LavaStrings.swift). **Todo o texto de componente** deve passar por ela — sem literais de string crus nas views.
- **zh-Hant** usa fraseado amigável a Taiwan na primeira passagem.
- Existem metadados da App Store para todos os 6 locais.
- Ordem de prioridade para tradução: ja, zh-Hant, zh-Hans, de, fr.
- O lançamento v1.0 incorporou uma revisão de catálogo de strings em cinco locais (≈56 correções), e o substantivo do produto mudou de plural **"Filters"** para singular **"Filter"** em todos os locais — mantenha as traduções consistentes com o modelo singular "meu filtro".

As fundações estão no lugar, mas a revisão completa de tradução humana ainda está pendente antes do lançamento, então o status geral é **Em andamento**.

> **Limpeza de fronteira de apresentação (Planejada, Fase 4).** `LavaSecCore`/`Shared` devem carregar *semântica* (enums de severidade/ação, papéis de ícone), não strings em inglês. A apresentação do tom de severidade já foi elevada ao semântico `ProtectionTintRole`. O resíduo que falta é que os `displayName`s dos resolvedores ainda são strings em inglês hardcoded ("Google", "Cloudflare", "Quad9", "Device DNS") em lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. A Fase 4 eleva isso a um mapa de apresentação por SO no lado do app — correto tanto para i18n quanto para portabilidade Android.

A mecânica de i18n (o glossário de localização, o esquema de arquivos de localização e a checklist de revisão de tradução) vive nos docs internos de i18n, não neste conjunto público.

---

## 7. Artefatos de referência

Referências de design em HTML (não lançadas, internas): o storyboard do fluxo de integração, um estudo do look de guardião kiwi-creme e as opções visuais de botão principal dentro de painel.

A fundação do DS chegou: o grupo `LavaDesignSystem/`, os tokens `LavaSpacing`/raio/`dangerRed`, a semântica de profundidade `LavaTier` e a camada de papel `LavaIcon` já estão no app (lavasec-ios: LavaSecApp/LavaDesignSystem/). O que permanece **Planejado** no plano de portabilidade/fundação é a tokenização de destaque `LavaColorRole` (Fase 3), o mapa de apresentação por SO para as strings em inglês do lado do core (Fase 4), um JSON de tokens neutro e multiplataforma, e as junções mais amplas de portabilidade Android.
