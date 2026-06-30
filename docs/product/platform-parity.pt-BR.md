# Paridade entre Plataformas

O sistema de paridade entre plataformas da Lava acompanha quais promessas de
produto são compartilhadas entre iOS, Android e clientes futuros. Ele é o
contrato público para o comportamento de funcionalidades: o que deve significar
a mesma coisa em todos os lugares, o que é intencionalmente nativo da
plataforma e o que ainda não foi prometido.

A documentação de paridade não substitui planos de implementação ou testes.

- `lavasec-doc` é dono do contrato de produto e de comportamento.
- Planos internos são donos do estado de entrega, sequenciamento, riscos
  privados e sincronização com o board.
- Os repositórios de plataforma são donos do código, fixtures e testes que
  comprovam o comportamento.

Quando a documentação e o código entregue divergem, o código prevalece até que
a documentação seja atualizada. Quando um plano e esta página divergem, trate
esta página como o contrato de produto e o plano como a fila de trabalho.

## Vocabulário de status

| Status | Significado |
|---|---|
| **Shipped** | Implementado em código de produção para aquela plataforma. |
| **Partial** | Algum comportamento existe, mas o contrato público não é totalmente cumprido. |
| **Planned** | Aceito como parte do contrato da plataforma, ainda não implementado. |
| **Deferred** | Funcionalidade válida, mas não obrigatória para o próximo marco da plataforma. |
| **Platform-native** | Mesma promessa ao usuário, implementação específica de cada sistema operacional. |
| **Not applicable** | Nenhuma funcionalidade equivalente deve existir naquela plataforma. |
| **Dropped** | Considerada ou construída anteriormente e então removida intencionalmente. |

## Formato do registro de funcionalidade

Toda funcionalidade acompanhada por paridade deve ter um id de funcionalidade
estável. Use nomes `area.capability` que sobrevivam a mudanças no texto da
interface, por exemplo `filtering.guardrail-precedence` ou
`dns.encrypted-transports`.

Um registro de funcionalidade completo responde a:

| Campo | Propósito |
|---|---|
| `feature_id` | Id estável usado em planos, PRs, testes e documentação. |
| Promessa de produto | Aquilo em que os usuários podem confiar, em linguagem neutra de plataforma. |
| Requisito de paridade | Se o Android deve corresponder ao iOS exatamente, corresponder por intenção ou permanecer intencionalmente diferente. |
| Status da plataforma | Estado no iOS, Android e clientes futuros. |
| Enforcement | Testes, fixtures, arquivos de código-fonte ou verificações de revisão que mantêm o comportamento honesto. |
| Notas de plataforma | Diferenças específicas do sistema operacional que devem ser explícitas, não redescobertas depois. |

## Fluxo de atualização

1. Adicione ou atualize o id de funcionalidade quando uma mudança alterar uma
   promessa de produto, uma alegação de privacidade, um limite de tier ou um
   comportamento entre plataformas.
2. Vincule o mesmo id de funcionalidade a partir do plano de implementação
   quando houver trabalho necessário.
3. Adicione ou atualize testes de plataforma ou golden fixtures para o
   comportamento que deve corresponder.
4. Quando uma plataforma entregar o comportamento, atualize o status aqui e
   atualize a página de funcionalidade ou arquitetura relevante.
5. Mantenha privados os detalhes internos exclusivos de implementação,
   privados, de precificação, de risco legal e operacionais; resuma aqui
   apenas o contrato público.

## Registro de paridade atual

| Feature id | Promessa de produto | iOS | Android | Requisito de paridade | Enforcement / fonte |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | A Lava filtra DNS localmente no dispositivo e não faz proxy da navegação pelos servidores da Lava. | Shipped | Planned | Corresponder por intenção; as APIs de túnel do sistema operacional diferem. | Arquitetura do packet tunnel no iOS; plano de `VpnService` no Android. |
| `protection.vpn-disclosure` | O app explica por que o sistema operacional chama a filtragem local de DNS de VPN antes de pedir permissão/configuração de VPN. | Shipped | Planned | Texto e fluxo de permissão nativos da plataforma. | Documentação de onboarding; plano de divulgação na Play do Android. |
| `filtering.guardrail-precedence` | Guardrails sempre ativos têm precedência sobre as allowlists do usuário; o status pago nunca contorna os guardrails. | Shipped | Planned | Paridade de comportamento exata. | `CompactFilterSnapshotTests`; `FilterSnapshotTest` do Android quando portado. |
| `filtering.source-url-only-catalog` | A Lava publica metadados do catálogo e URLs de fontes upstream, não os bytes de blocklists de terceiros. | Shipped | Planned | Paridade exata do modelo de privacidade/PI. | Arquitetura do catálogo; documentação legal de source-url-only/GPL. |
| `filtering.on-device-parsing` | As listas selecionadas são buscadas e analisadas no dispositivo; o histórico rotineiro de domínios não é enviado para a Lava. | Shipped | Planned | Paridade de privacidade exata, armazenamento nativo permitido. | `BlocklistParserTests`; testes de paridade do parser do Android quando portados. |
| `filtering.rule-budget` | Os limites do Filtro são baseados na contagem de regras compiladas e na segurança do dispositivo, não em uma contagem arbitrária de listas. | Shipped | Planned | Mesmo modelo voltado ao usuário; os limites de memória da plataforma podem diferir. | Testes de orçamento de Filtro no iOS; testes de orçamento no Android quando os limites do dispositivo forem conhecidos. |
| `dns.built-in-resolvers` | Os usuários podem escolher predefinições de resolvers integrados sem enviar consultas permitidas para a Lava. | Shipped | Planned | Mesma política de resolver; o conjunto de predefinições pode ser lançado em fases. | Testes de predefinições de resolver; testes do DTO de resolver do Android quando portados. |
| `dns.encrypted-transports` | DNS upstream criptografado está disponível para consultas permitidas. | Shipped | Planned | Paridade em etapas permitida; o Android v1 pode começar com DoH antes de DoT/DoQ. | Testes de transporte do iOS; testes de resolver e QA em dispositivo do Android. |
| `reports.local-only-diagnostics` | Relatórios e diagnósticos permanecem locais, a menos que o usuário envie explicitamente um pacote de suporte. | Shipped | Planned | Paridade de privacidade exata; a interface pode diferir. | Testes do pacote de relatório de bugs; testes de pré-visualização do relatório de depuração do Android quando construídos. |
| `account.optional-sign-in` | A proteção funciona sem uma conta; o login é opcional. | Shipped | Deferred | Promessa de produto exata antes de o Android expor funcionalidades de conta. | Documentação de autenticação de conta; revisão de onboarding/configurações do Android. |
| `backup.zero-knowledge-settings` | O backup opcional de configurações armazena somente o texto cifrado; a Lava não consegue ler o conteúdo do backup em texto puro. | Shipped | Deferred | Paridade de privacidade exata antes de o Android oferecer backup. | Testes de backup zero-knowledge; testes de paridade de criptografia do Android quando construídos. |
| `plus.customization-boundary` | A proteção gratuita permanece útil; o Plus desbloqueia personalização avançada e nunca altera a segurança dos guardrails. | Shipped | Planned | Mesmo limite de produto; a implementação da loja é nativa da plataforma. | Testes de política de assinatura; testes de entitlement do Play Billing quando construídos. |
| `design.calm-earned-depth` | A UX padrão é calma, com superfícies técnicas ou comemorativas mais profundas apenas quando merecidas ou solicitadas. | Partial | Planned | Corresponder por intenção de design via tokens/papéis compartilhados. | Documentação do design system e plano de fundação de portabilidade. |
| `platform.ambient-presence` | O status de proteção pode aparecer fora do app quando o sistema operacional oferece uma superfície ambiente nativa. | Platform-native | Planned | Paridade de intenção, não paridade de superfície. | Documentação de Live Activity do iOS; decisão de notificação/Quick Settings do Android pendente. |

## Uso para prontidão do Android

Antes de a implementação do Android começar, esta página deve ser revisada
junto ao plano do Android e ao plano de portabilidade do design system. O
contrato mínimo de prontidão para o Android é:

- toda funcionalidade que carrega privacidade tem um id de funcionalidade;
- comportamento de paridade exata tem uma fonte de teste ou fixture do iOS
  identificada;
- comportamento nativo da plataforma tem uma posição explícita do Android;
- funcionalidades adiadas são nomeadas para que o MVP do Android não dê a
  entender acidentalmente que já foram entregues.

Essa revisão pertence ao plano de implementação ou às notas de revisão,
enquanto esta página mantém o contrato público e durável.
