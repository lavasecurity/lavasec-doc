# Paridade entre plataformas {#platform-parity}

O sistema de paridade entre plataformas da Lava acompanha quais promessas do
produto são compartilhadas entre iOS, Android e clientes futuros. Ele é o
contrato público de comportamento dos recursos: o que precisa significar a mesma
coisa em todo lugar, o que é intencionalmente nativo de cada plataforma e o que
ainda não foi prometido.

Os documentos de paridade não substituem os planos de implementação nem os testes:

- O `lavasec-doc` é responsável pelo contrato de produto e de comportamento.
- Os planos internos cuidam do estado de entrega, do sequenciamento, dos riscos
  privados e da sincronização com a diretoria.
- Os repositórios das plataformas cuidam do código, dos fixtures e dos testes
  que comprovam o comportamento.

Quando os documentos e o código publicado divergem, o código prevalece até que os
documentos sejam atualizados. Quando um plano e esta página divergem, trate esta
página como o contrato de produto e o plano como a fila de trabalho.

## Vocabulário de status {#status-vocabulary}

| Status | Significado |
|---|---|
| **Entregue** | Implementado em código de produção para aquela plataforma. |
| **Parcial** | Parte do comportamento existe, mas o contrato público ainda não é totalmente cumprido. |
| **Planejado** | Aceito como parte do contrato da plataforma, mas ainda não implementado. |
| **Adiado** | Recurso válido, mas não necessário para o próximo marco da plataforma. |
| **Nativo da plataforma** | Mesma promessa ao usuário, com implementação específica de cada sistema operacional. |
| **Não aplicável** | Não deve existir um recurso equivalente naquela plataforma. |
| **Removido** | Já foi considerado ou construído e depois retirado de forma intencional. |

## Formato do registro de recurso {#feature-record-format}

Todo recurso acompanhado pela paridade deve ter um id estável. Use nomes no
formato `area.capability` que sobrevivam a mudanças no texto da interface, por
exemplo `filtering.guardrail-precedence` ou `dns.encrypted-transports`.

Um registro completo de recurso responde:

| Campo | Finalidade |
|---|---|
| `feature_id` | Id estável usado em planos, PRs, testes e documentos. |
| Promessa do produto | Aquilo com que os usuários podem contar, em linguagem neutra entre plataformas. |
| Requisito de paridade | Se o Android precisa corresponder ao iOS de forma exata, corresponder pela intenção ou permanecer intencionalmente diferente. |
| Status por plataforma | Estado no iOS, no Android e em clientes futuros. |
| Verificação | Testes, fixtures, arquivos de origem ou revisões que mantêm o comportamento honesto. |
| Notas de plataforma | Diferenças específicas de cada sistema operacional que precisam ficar explícitas, e não ser redescobertas depois. |

## Fluxo de atualização {#update-workflow}

1. Adicione ou atualize o id do recurso quando uma mudança altera uma promessa do
   produto, uma garantia de privacidade, um limite de plano ou um comportamento
   entre plataformas.
2. Vincule o mesmo id do recurso a partir do plano de implementação quando houver
   trabalho a fazer.
3. Adicione ou atualize testes de plataforma ou fixtures de referência para o
   comportamento que precisa corresponder.
4. Quando uma plataforma publica o comportamento, atualize o status aqui e
   atualize a página de recurso ou de arquitetura relevante.
5. Mantenha em sigilo os detalhes internos que dizem respeito apenas à
   implementação, ao que é privado, a preços, a risco jurídico e a operações;
   resuma aqui apenas o contrato público.

## Registro de paridade atual {#current-parity-ledger}

| Id do recurso | Promessa do produto | iOS | Android | Requisito de paridade | Verificação / origem |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | A Lava filtra o DNS localmente no dispositivo e não encaminha a navegação por servidores da Lava. | Entregue | Planejado | Corresponder pela intenção; as APIs de túnel de cada sistema diferem. | Arquitetura do túnel de pacotes no iOS; plano de `VpnService` no Android. |
| `protection.vpn-disclosure` | O app explica por que o sistema operacional chama a filtragem local de DNS de VPN antes de pedir a permissão/configuração de VPN. | Entregue | Planejado | Texto e fluxo de permissão nativos de cada plataforma. | Documentos de integração; plano de divulgação na Play do Android. |
| `filtering.guardrail-precedence` | As proteções sempre ativas têm prioridade sobre as listas de permissão do usuário; ter um plano pago nunca contorna essas proteções. | Entregue | Planejado | Paridade exata de comportamento. | `CompactFilterSnapshotTests`; `FilterSnapshotTest` no Android quando portado. |
| `filtering.source-url-only-catalog` | A Lava publica metadados de catálogo e as URLs de origem upstream, não os bytes de listas de bloqueio de terceiros. | Entregue | Planejado | Paridade exata do modelo de privacidade/propriedade intelectual. | Arquitetura do catálogo; documentos jurídicos sobre GPL/uso apenas de URL de origem. |
| `filtering.on-device-parsing` | As listas selecionadas são baixadas e processadas no dispositivo; o histórico rotineiro de domínios não é enviado para a Lava. | Entregue | Planejado | Paridade exata de privacidade, com armazenamento nativo permitido. | `BlocklistParserTests`; testes de paridade do leitor no Android quando portado. |
| `filtering.rule-budget` | Os limites de filtragem se baseiam na quantidade de regras compiladas e na segurança do dispositivo, não em um número de listas escolhido de forma arbitrária. | Entregue | Planejado | Mesmo modelo voltado ao usuário; os limites de memória de cada plataforma podem variar. | Testes de orçamento de filtragem do iOS; testes de orçamento do Android quando os limites do dispositivo forem conhecidos. |
| `dns.built-in-resolvers` | Os usuários podem escolher predefinições de resolvedor integradas sem enviar à Lava as consultas permitidas. | Entregue | Planejado | Mesma política de resolvedores; o conjunto de predefinições pode ser lançado em etapas. | Testes de predefinições de resolvedor; testes de DTO de resolvedor no Android quando portado. |
| `dns.encrypted-transports` | DNS upstream criptografado fica disponível para as consultas permitidas. | Entregue | Planejado | Paridade em etapas permitida; a v1 do Android pode começar com DoH antes de DoT/DoQ. | Testes de transporte do iOS; testes de resolvedor e QA em dispositivo no Android. |
| `reports.local-only-diagnostics` | Os relatórios e diagnósticos permanecem locais, a menos que o usuário envie explicitamente um pacote de suporte. | Entregue | Planejado | Paridade exata de privacidade; a interface pode diferir. | Testes do pacote de relatório de erros; testes de prévia do relatório de depuração no Android quando construído. |
| `account.optional-sign-in` | A proteção funciona sem uma conta; o login é opcional. | Entregue | Adiado | Promessa de produto exata antes de o Android expor recursos de conta. | Documentos de autenticação de conta; revisão de integração/configurações do Android. |
| `backup.zero-knowledge-settings` | O backup opcional de configurações armazena apenas texto cifrado; a Lava não consegue ler o conteúdo do backup em texto legível. | Entregue | Adiado | Paridade exata de privacidade antes de o Android oferecer backup. | Testes de backup de conhecimento zero; testes de paridade de criptografia no Android quando construído. |
| `plus.customization-boundary` | A proteção gratuita continua útil; o Plus libera personalização avançada e nunca altera a segurança das proteções sempre ativas. | Entregue | Planejado | Mesmo limite de produto; a implementação na loja é nativa de cada plataforma. | Testes da política de assinatura; testes de direito de uso da Play Billing quando construídos. |
| `design.calm-earned-depth` | A experiência padrão é tranquila, com superfícies técnicas ou comemorativas mais profundas apenas quando merecidas ou solicitadas. | Parcial | Planejado | Corresponder pela intenção de design por meio de tokens/papéis compartilhados. | Documentos do sistema de design e plano de base de portabilidade. |
| `platform.ambient-presence` | O status da proteção pode aparecer fora do app quando o sistema operacional oferece uma superfície ambiente nativa. | Nativo da plataforma | Planejado | Paridade de intenção, não de superfície. | Documentos de Live Activity do iOS; decisão sobre notificação/Configurações Rápidas do Android pendente. |

## Uso na preparação do Android {#android-readiness-use}

Antes de a implementação no Android começar, esta página deve ser revisada junto
ao plano do Android e ao plano de portabilidade do sistema de design. O contrato
mínimo para o Android ficar pronto é:

- todo recurso que envolve privacidade tem um id de recurso;
- comportamento de paridade exata tem uma origem de teste ou fixture do iOS
  identificada;
- comportamento nativo da plataforma tem uma posição explícita para o Android;
- recursos adiados são nomeados para que o MVP do Android não sugira por engano
  que eles já estão disponíveis.

Essa revisão pertence ao plano de implementação ou às notas de revisão, enquanto
esta página mantém o contrato público e duradouro.
