---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Design System

> **Público:** design + engenharia trabalhando no app iOS da Lava Security.
> **Autoridade:** Onde este documento e um plano divergirem, **o código vence** — as divergências são apontadas ao longo do texto. O status reflete a realidade confirmada no código, não a aspiração do plano. Legenda de status: **Implementado** (entregue e confirmado no código), **Em andamento** (parcialmente concluído), **Planejado** (projetado, mas não construído), **Descartado** (rejeitado ou revertido).

Este documento aborda a filosofia de design, o vocabulário de profundidade LavaTier, o mascote Guardian, as convenções de texto e nomenclatura, a experiência de onboarding e a internacionalização. Para a infraestrutura por trás dessas telas (targets, ciclo de vida da VPN, a ligação do modelo de estado Guardian/proteção), veja [o cliente iOS](../architecture/ios-client.md); para o enquadramento de produto, veja [a visão geral do produto](../product/overview.md).

---

## 1. Filosofia: núcleo tranquilo, profundidade conquistada

O público da Lava são pessoas comuns, não técnicas — pais, mães, pessoas idosas — e o design parte disso. A tela do dia a dia "simplesmente funciona" de forma tranquila para todo mundo; detalhes extras, momentos de encanto e controle só aparecem (**são conquistados**) quando a pessoa vai atrás deles. Nada incomoda, nada alarma, e a parte técnica fica invisível até alguém procurá-la.

Esse modelo de **"núcleo tranquilo, profundidade conquistada"** se desdobra em três profundidades de produto:

- **Tranquilo** — a proteção padrão, que simplesmente funciona e que todo mundo vê primeiro.
- **Comemorativo** — reconhecimento e encanto opcionais (sequências, conquistas, momentos de sucesso). Nunca incomoda.
- **Técnico** — DNS, diagnósticos e estatísticas. Invisível até a pessoa ir atrás.

Duas regras transversais de paleta/tom sustentam essa postura tranquila:

- **vermelho = só perigo.** O vermelho é reservado exclusivamente para perigo e erro; a paleta tranquila é verde/laranja. Isso mantém o vermelho confiável como um sinal de alerta de verdade. O vermelho de perigo é representado pelo token `LavaStyle.dangerRed`, com `LavaStyle.errorText` apontando para ele (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:81/86) e usado nos textos de erro das telas. A cor da proteção é resolvida pela tabela de papéis semânticos `ProtectionTintRole` (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7), e não por um `.green`/`.orange` direto. Alguns poucos pontos com `.red` direto realmente persistem (por exemplo, lavasec-ios: LavaSecApp/SettingsView.swift:697, LavaSecApp/SecurityController.swift:600, LavaSecApp/FiltersView.swift) — migrá-los para `LavaStyle.dangerRed` é a limpeza que falta.
- **Sem linguagem de segurança baseada em medo.** O texto é simples, tranquilo e prático. Veja [§4 Texto e nomenclatura](#4-copy-naming).

### A camada tokenizada que existe hoje **(Implementado)**

O design system é uma camada SwiftUI real e tokenizada, ao lado do vocabulário de profundidade `LavaTier` (§2):

- **`LavaStyle`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:5) — a fonte da verdade para cores adaptáveis: ~18 cores semânticas (`safeGreen`, `safeControlGreen`, `softGreen`, `lavaOrange`, `cream`, `ink`, `cardBackground`, `panelBackground`, `guardianSleepGray`, …), cada uma produzida por uma única fábrica `adaptiveColor(light:dark:)`, de modo que claro/escuro são definidos juntos. O vermelho de perigo é representado aqui como `dangerRed`/`errorText` (linhas 81/86).
- **`LavaSurface`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:101) — papéis de superfície de cartão/painel/seleção e raios de canto: `cardCornerRadius` 20, `compactCornerRadius` 16, `selectionCornerRadius` 12.
- **`LavaSpacing`** (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:183) — a escala de espaçamento: `xs`/`sm`/`md`/`lg`/`xl` mais `screenHorizontal`/`screenTop`/`screenBottom`.

A lacuna residual que resta são os poucos pontos com `.red` direto ainda não migrados para `LavaStyle.dangerRed` (veja §1).

---

## 2. LavaTier — Floor / Window / Workshop **(Implementado)**

`LavaTier` é o vocabulário leve de profundidade que codifica "núcleo tranquilo, profundidade conquistada" diretamente na camada de tokens. É um vocabulário mais alguns valores-padrão de token — não um re-tema completo — e vem como um enum em lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:227, ligado a telas representativas em vez de ser aplicado a cada view.

| Tier | Profundidade | Significado |
|---|---|---|
| **Floor** | tranquilo | Proteção que simplesmente funciona, para todo mundo — a tela padrão. |
| **Window** | comemorativo | Reconhecimento e encanto opcionais: sequências, conquistas, momentos de sucesso. Nunca incomoda. |
| **Workshop** | técnico | DNS, Nerd Stats, diagnósticos. Invisível até a pessoa procurar. |

`LavaTier` é um enum `calm`/`celebratory`/`technical` que carrega valores-padrão de token:

- uma **cor de destaque** (`accent`),
- `allowsDelightMotion` — verdadeiro apenas para comemorativo / Window,
- `usesMonospacedMetadata` — verdadeiro apenas para técnico / Workshop,

exposto por uma `EnvironmentKey` mais um modificador `.lavaTier(_:)` e um modificador `.lavaTierMetadata()` (lavasec-ios: LavaSecApp/LavaDesignSystem/LavaTokens.swift:258/263). Está ligado a telas representativas — por exemplo, `.lavaTier(.technical)` e `.lavaTier(.celebratory)` em lavasec-ios: LavaSecApp/SettingsView.swift — e não a cada view. Esse escopo deliberado mantém as três profundidades de produto legíveis no código e portáveis para um futuro consumidor Android sem ter que re-derivar a intenção.

> **Ressalva (tokenização do destaque Planejada, Fase 3):** `LavaColorRole` ainda não foi criado, então `LavaTier.accent` ainda resolve para cores `LavaStyle` diretas (LavaTokens.swift:~230). Trate a tokenização da cor de destaque como um ponto em aberto, não como uma tela finalizada.

---

## 3. O mascote Soft Shield Guardian **(Implementado)**

O **Soft Shield Guardian** é o mascote da Lava — um escudo arredondado com um rosto simples e que se transforma — que expressa visualmente o estado da proteção na aba Guard, na Live Activity, na Dynamic Island e no onboarding. É o portador mais visível do tom tranquilo.

O grafo de estados é independente de plataforma e vive em `LavaSecCore` (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift); o renderizador SwiftUI é lavasec-ios: Shared/SoftShieldGuardian.swift.

### 3.1 Os 7 estados de expressão

O mascote tem **exatamente 7** estados de expressão, regidos por um grafo de estados com transições permitidas (`GuardianMascotState.allowedNextStates`, travado por lavasec-ios: Tests/LavaSecCoreTests/GuardianMascotAnimationTests.swift):

```
sleeping, waking, awake, paused, retrying, concerned, grateful
```

Restrições do grafo que vale conhecer: a única saída de `sleeping` é `waking`, e `grateful` só volta para `awake`. As transições `awake ↔ grateful` têm quadros de interpolação feitos sob medida — é o único trecho de **movimento de encanto** do sistema (tier Window).

> **`retrying` vs `concerned` — a distinção de tom mais importante.** Ambos sinalizam "não está perfeitamente saudável", mas são lidos de formas muito diferentes e não podem ser confundidos:
> - **`retrying`** é o rosto *despreocupado, que se recupera sozinho*: pálpebras relaxadas (~0,80), olhos no nível, boca reta e **sem inclinação de preocupação**. O movimento fica por conta do **selo de status, não do rosto** — uma recuperação automática passageira nunca deve alarmar. (lavasec-ios: Sources/LavaSecCore/GuardianMascotAnimation.swift:249)
> - **`concerned`** é uma preocupação *gentil, que pede ajuda*: sobrancelhas internas levantadas (`concernAmount` 1, `mouthCurve` -0,22), lidas como "uma mãozinha viria bem", **nunca um olhar severo**. Problemas de verdade devem convidar à ajuda, não repreender. (lavasec-ios: Shared/SoftShieldGuardian.swift:297)

### 3.2 Mapeamento conectividade → expressão (6 → 4)

A saúde da proteção é avaliada em `LavaSecCore` como **6 severidades de conectividade** + 2 ações (lavasec-ios: Sources/LavaSecCore/ProtectionConnectivityPolicy.swift):

- **Severidades:** `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`
- **Ações:** `turnOff`, `reconnect`

A aba Guard reduz essas 6 severidades a **4 rostos** (`guardianState` em lavasec-ios: LavaSecApp/GuardView.swift:122). O rosto é, de propósito, um sinal *mais grosso e mais calmo* que o selo de status — o selo carrega o detalhe, o rosto se mantém simples:

| Condição | Estado do mascote |
|---|---|
| Pausado temporariamente | `paused` |
| conectado + `healthy` / `usingDeviceDNSFallback` | `awake` |
| conectado + `recovering` / `networkUnavailable` | `retrying` |
| conectado + `dnsSlow` / `needsReconnect` | `concerned` |
| `connecting` / `reasserting` | `waking` |
| caso contrário | `sleeping` |

> **Reconciliação de cor.** A granularidade da cor da proteção fica reconciliada com essa divisão de expressões, para que cor e rosto nunca discordem. O mapeamento de expressões e a tabela de papéis semânticos `ProtectionTintRole` já estão prontos hoje (lavasec-ios: Sources/LavaSecCore/ProtectionPresentation.swift:7, consumida por `AppViewModel.protectionTintRole`). Só falta a tokenização de papéis de cor `LavaColorRole`, que mapearia os papéis para cores totalmente tokenizadas, e ela permanece **Planejada** (Fase 3 do plano do DS).

### 3.3 Skins (visuais) **(Implementado)**

O mascote vem em **7 "visuais" de escudo selecionáveis**, persistidos como `GuardianShieldStyle` (lavasec-ios: Shared/LavaActivityAttributes.swift:5). Cada um tem sua própria combinação de cores e uma cor de glifo da Dynamic Island combinando:

`original`, `fireOpal` (valor bruto `emberObsidian`), `purpleObsidian`, `obsidian`, `cherryQuartz` (valor bruto `strawberryObsidian`), `emerald`, `kiwiCreme`.

Os dois valores brutos legados são intencionais — não os "conserte"; isso quebraria as seleções já salvas dos usuários.

### 3.4 Ocultação por privacidade **(Implementado)**

O Guardian respeita a ocultação por privacidade: a expressão pode ser mascarada quando a tela está com a privacidade oculta, enquanto o **próprio escudo continua visível** (`maskExpressionWhenPrivacyRedacted` / `keepsShieldVisibleWhenRedacted`, lavasec-ios: Shared/SoftShieldGuardian.swift:11). A presença da proteção é reconfortante; o que se esconde é o estado emocional específico.

### 3.5 Fora desta árvore **(Planejado)**

Um minijogo easter-egg no Guard (toque = animação de gratidão; segurar por 10s = um jogo de capturar domínios ruins) é **P3 / backlog**. Ele adicionaria expressões extras ao mascote (`confused` / `dazed` / `inZone` / `powerSurge`) vistas em uma feature branch — elas **não** estão no target do app. Segundo os fatos canônicos, o mascote tem exatamente **7** estados; não documente as expressões do jogo como entregues.

---

## 4. Texto e nomenclatura

### 4.1 Voz e tom

Simples, tranquilo, prático. Evite linguagem de segurança baseada em medo. Seja honesto sobre o escopo: a Lava faz **filtragem local de DNS/blocklist**, não é uma garantia de que todo domínio ou URL malicioso será bloqueado, e a proteção **nunca** é descrita como ligada automaticamente assim que o onboarding termina — a **aba Guard é a fonte autoritativa** sobre se a proteção está ativa no momento.

### 4.2 Rótulos de transporte DNS

As anotações de transporte seguem uma convenção compacta rígida (lavasec-ios: Sources/LavaSecCore/DoHTransport.swift:16 e lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift:270, travada por `DNSResolverPresetTests.swift`):

| Transporte | Rótulo | Observações |
|---|---|---|
| DNS-over-HTTPS | `DoH` | Baseado em URLSession. |
| DNS-over-HTTP/3 | **`DoH3` (sem barra)** | por exemplo, "Quad9 (DoH3)". Anotado **somente quando uma negociação h3 é realmente observada** — preferido, nunca prometido; caso contrário, volta para `DoH`. |
| DNS-over-TLS | `DoT` | |
| DNS-over-QUIC | `DoQ` | |
| DNS comum | `IP` | |
| resolvedor do dispositivo | *(sem anotação)* | |

A regra mais quebrada aqui é o **`DoH3` sem barra** — escreva `DoH3`, nunca `DoH/3` nem `DoH3 (h3)`, e nunca o aplique por suposição. Esses rótulos de transporte são emitidos por `DoHTransport`/`DNSResolverPreset`; mantenha-os exatamente iguais em todos os idiomas, mas note que eles *não* são entradas Não-Traduzir do glossário (veja §4.3).

### 4.3 Termos Não-Traduzir

Termos de marca e de protocolo são fixados exatamente iguais em **todos** os idiomas. A lista Não-Traduzir do glossário de localização é a autoridade, e ela fixa: **Lava Security, Lava Security LLC, lavasecurity.app, support@lavasecurity.app, legal@lavasecurity.app, DNS, VPN, DoH, TCP, Apple, Google, Cloudflare, Quad9, The Block List Project, Phishing.Database, HaGeZi, OISD.**

Dos transportes DNS, apenas **DoH** é uma entrada Não-Traduzir do glossário; `DoH3`, `DoT` e `DoQ` são rótulos de transporte (veja §4.2), não termos do glossário. Mesmo assim são escritos exatamente iguais, mas não cite o glossário como sua fonte.

### 4.4 Enquadramento de segurança

O pagamento nunca contorna a **barreira de proteção contra ameaças**, validada por hash e não passível de exceção. Declare a precedência de forma consistente: **barreira de proteção contra ameaças > allowlist local (exceções permitidas) > blocklist > permitir por padrão.**

---

## 5. Experiência de onboarding **(Implementado)**

O onboarding da primeira execução é um fluxo de várias páginas — **6 páginas** (`OnboardingPage`: `lava → guardIntro → features → vpn → notifications → done`) — implementado em lavasec-ios: LavaSecApp/OnboardingFlowView.swift. Ele reutiliza o `SoftShieldGuardian` para o momento de surgimento do guardião.

As 6 páginas:

1. **A internet é lava** (`lava`) — o perigo enquadrado como metáfora; ação principal "Conheça a Lava".
2. **A Lava fica de guarda aqui** (`guardIntro`) — o momento de surgimento do guardião.
3. **Apresentação dos recursos** (`features`) — o que a Lava faz; "Configurar proteção".
4. **Instale a VPN local da Lava** (`vpn`) — explica por que o iOS diz "VPN" para um túnel de pacotes que só faz DNS.
5. **Ative as notificações** (`notifications`) — o pedido opcional, apresentado no momento certo, e não logo de cara.
6. **Configuração concluída** (`done`) — "Abrir Guard", com configuração adicional opcional.

Decisões de design embutidas no fluxo:

- **"Usar padrão" é a ação principal, "Personalizar" é a secundária.** Um caminho padrão sem atrito para pessoas não técnicas; o controle é conquistado, não imposto.
- **Perigo enquadrado como metáfora, não como medo** ("A internet é lava"), de acordo com o tom tranquilo.
- **O fluxo explica por que o iOS diz "VPN"** — um túnel de pacotes é a única forma de filtrar DNS em todo o sistema; não é roteamento de tráfego.
- **Nunca afirma que a proteção está ligada automaticamente ao concluir** — o Guard continua sendo a fonte autoritativa.
- Voltar apenas pelo chevron, em um layout de página de passo compartilhado.

Os padrões da primeira execução que o fluxo instala: resolvedor **Device DNS** (`DNSResolverPreset.device`), **fallback de Device DNS LIGADO**, registro ligado (contagens + histórico + atividade) e "Continuar sem conta".

> **Divergência da blocklist padrão (o código vence).** O texto do plano de onboarding lista HaGeZi Multi Light como blocklist padrão, mas o padrão que veio no código é **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definido em lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift). O verdadeiro limite de plano é o **orçamento de regras de filtro (Free 500K / Plus 2M)**, *não* uma contagem de listas. Acompanhado internamente. Para o modelo de planos e a configuração recomendada por padrão, veja [o catálogo de recursos](../product/features.md).

---

## 6. Internacionalização **(Em andamento)**

A Lava é localizada em **6 idiomas**: **en** (origem) + **ja, zh-Hant, zh-Hans, de, fr**, via catálogos de strings do Xcode.

- **A costura de localização é `.lavaLocalized`** (`String.lavaLocalized` / `.lavaLocalizedFormat`, sustentada por `LavaStrings.localized` → `NSLocalizedString` com fallback em inglês; lavasec-ios: LavaSecApp/LavaStrings.swift). **Todo texto de componente** deve passar por ela — nada de strings cruas nas views.
- **zh-Hant** usa, na primeira passagem, uma redação adequada a Taiwan.
- Existem metadados da App Store para todos os 6 idiomas.
- Ordem de prioridade para tradução: ja, zh-Hant, zh-Hans, de, fr.

As bases estão prontas, mas a revisão humana completa da tradução ainda está pendente antes do lançamento, então o status geral é **Em andamento**.

> **Limpeza da fronteira de apresentação (Planejada, Fase 4).** `LavaSecCore`/`Shared` devem carregar *semântica* (enums de severidade/ação, papéis de ícone), não strings em inglês. A apresentação da cor de severidade já foi movida para o `ProtectionTintRole` semântico. O que resta é que os `displayName`s dos resolvedores ainda são strings em inglês fixas no código ("Google", "Cloudflare", "Quad9", "Device DNS") em lavasec-ios: Sources/LavaSecCore/DNSResolverPreset.swift. A Fase 4 move isso para um mapa de apresentação por SO, no lado do app — correto tanto para a i18n quanto para a portabilidade Android.

A mecânica da i18n (o glossário de localização, o schema dos arquivos de localização e o checklist de revisão de tradução) vive nos documentos internos de i18n, não neste conjunto público.

---

## 7. Artefatos de referência

Referências de design em HTML (não embarcadas, internas): o storyboard do fluxo de onboarding, um estudo do visual kiwi-creme do guardião e opções visuais de botão principal dentro do painel.

A base do DS já chegou: o grupo `LavaDesignSystem/`, os tokens `LavaSpacing`/raio/`dangerRed`, a semântica de profundidade `LavaTier` e a camada de papéis `LavaIcon` já estão prontos (lavasec-ios: LavaSecApp/LavaDesignSystem/). O que continua **Planejado** no plano de portabilidade/base é a tokenização de destaque `LavaColorRole` (Fase 3), o mapa de apresentação por SO para as strings em inglês do lado do core (Fase 4), um JSON de tokens neutro e multiplataforma, e as costuras mais amplas de portabilidade para Android.
