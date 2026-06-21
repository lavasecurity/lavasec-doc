---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Visão geral do produto

Boas-vindas ao Lava Security. Esta página é a porta de entrada do conjunto de documentação: uma introdução curta e simples sobre o que é o Lava, o que ele promete e onde ler mais.

## O que é o Lava

O Lava Security é um app de iOS que prioriza a privacidade e filtra o DNS localmente no aparelho por meio de um [túnel de pacotes do NetworkExtension](../architecture/ios-client.md) executado no próprio aparelho, bloqueando domínios conhecidos como arriscados ou indesejados sem encaminhar a sua navegação pelos servidores do Lava. O túnel de pacotes (`LavaSecTunnel`, um `NEPacketTunnelProvider`) analisa cada consulta de DNS no celular, verifica o domínio solicitado contra um snapshot de filtro compilado e mapeado em memória, e encaminha adiante apenas as consultas permitidas. Não existe um proxy operado pelo Lava por onde o seu tráfego passe: a filtragem é uma decisão local, feita no seu aparelho.

O iOS chama isso de "VPN" porque um túnel de pacotes é a única forma de um app filtrar o DNS em todo o sistema — mas o Lava faz **filtragem de DNS/lista de bloqueio**, e não roteamento de tráfego. É bom ser claro sobre o alcance: o Lava é uma filtragem local de domínios de DNS, e **não** uma garantia de que todo domínio ou URL mal-intencionado seja bloqueado. Ele enxerga domínios, e não os caminhos das páginas, então não consegue bloquear uma única página ruim em um site de resto confiável. A proteção também não fica ativa automaticamente assim que a configuração inicial termina — a aba **Guarda** dentro do app é a fonte definitiva para saber se a proteção está ativa no momento.

## A promessa de privacidade

> Toda a filtragem de DNS acontece no aparelho; o Lava nunca encaminha a sua navegação pelos seus servidores e nunca recebe o fluxo dos domínios que você visita — o backend guarda apenas os metadados do catálogo, um backup criptografado e opaco por usuário, e diagnósticos anônimos que você escolhe enviar.

Esta frase é a referência central. Todo o resto desta documentação foi pensado para ser coerente com ela. Pagar pelo plano opcional **não** transfere a filtragem para o servidor nem dá ao Lava um fluxo dos domínios visitados. Quando um recurso envolve um servidor, a documentação explica o que **não** é enviado — as suas consultas de DNS do dia a dia, o seu histórico de navegação e qualquer conteúdo em texto puro permanecem todos no aparelho. Veja [o backend e o modelo de dados](../architecture/backend-and-data.md) para o panorama completo.

## Para quem é

O Lava foi feito para qualquer pessoa que queira navegar com mais segurança sem precisar ficar gerenciando isso. O público inclui de propósito pessoas não técnicas — pais e mães configurando proteção para a família, pessoas mais velhas e qualquer um que não queira pensar em DNS de jeito nenhum. A experiência padrão simplesmente funciona: você ativa a proteção e uma lista de bloqueio conservadora começa a filtrar, sem precisar de conta. Ao mesmo tempo, usuários avançados podem acessar controles mais profundos (listas de bloqueio personalizadas, resolvedores alternativos) quando quiserem.

O tom em toda a comunicação é simples, tranquilo e prático — o perigo é apresentado como uma metáfora, não como medo.

## Princípios centrais

- **Privacidade é posicionamento, não um recurso pago.** A filtragem é uma decisão local. O backend do Lava é propositalmente mínimo e nunca recebe os domínios da sua navegação do dia a dia nem fluxos de eventos de DNS. O backup opcional de conta é [conhecimento zero](../architecture/accounts-and-backup.md): os servidores guardam apenas o texto cifrado e metadados de envelope que não são secretos.
- **Proteção básica gratuita para sempre.** O botão de proteção, as atualizações da lista de bloqueio padrão e as contagens locais básicas nunca ficam atrás de um paywall e nunca exigem uma conta.
- **No aparelho.** O motor de proteção vive inteiramente no celular — a análise de DNS, a avaliação de domínios e o encaminhamento adiante acontecem todos dentro da extensão de túnel de pacotes, dentro do limite de memória de cerca de 50 MiB por extensão imposto pelo iOS. As listas de bloqueio seguem um modelo de [somente URL de origem](../architecture/dns-filtering-and-blocklists.md): o app busca cada lista de origem diretamente e a analisa localmente; o Lava nunca hospeda nem distribui bytes de listas de bloqueio de terceiros.
- **O pagamento libera personalização — nunca a segurança básica.** A proteção contra ameaças — um nível não anulável acima de toda lista de bloqueio, que ninguém, pagante ou não, consegue colocar em lista de permissão — é garantida por uma ordem de precedência nas decisões: **proteção contra ameaças > lista de permissão local (exceções permitidas) > lista de bloqueio > permitir por padrão.** (A posição na ordem de precedência está implementada e tem a integridade verificada por hashes SHA-256 aceitos; no momento ela é distribuída sem nenhuma entrada.) O túnel ignora `isPaid`.
- **Núcleo tranquilo, profundidade conquistada.** As telas padrão são silenciosas e reconfortantes, encabeçadas pelo mascote Guardião do Escudo Suave e por textos que evitam linguagem que gera medo. Detalhes mais ricos e mais técnicos estão disponíveis quando você vai atrás, mas nunca são impostos. Essa filosofia de "núcleo tranquilo, profundidade conquistada" está formalizada no modelo de profundidade **LavaTier** (Térreo / Janela / Oficina) — veja [o design system](../design-system/overview.md).

## Recursos em alto nível

- **Filtragem de DNS local** — o motor do túnel de pacotes que analisa o DNS, avalia cada domínio contra o snapshot compilado e encaminha adiante as consultas permitidas, com fallback para o DNS do aparelho. Veja [o cliente iOS](../architecture/ios-client.md) e [filtragem de DNS e listas de bloqueio](../architecture/dns-filtering-and-blocklists.md).
- **Listas de bloqueio selecionadas, somente URL de origem** — o Lava publica apenas as URLs das listas de origem mais os hashes aceitos; o aparelho busca, valida e analisa os bytes da lista por conta própria, e o Lava nunca espelha nem distribui bytes de listas de bloqueio de terceiros. O padrão de fábrica ativa **Block List Project Phishing + Scam** (`AppConfiguration.lavaRecommendedDefaults`, definido em `OnboardingDefaults.swift`); fontes GPL (HaGeZi, OISD) são opcionais. Veja [filtragem de DNS e listas de bloqueio](../architecture/dns-filtering-and-blocklists.md).
- **Transportes de DNS criptografados** — DoH (com anotação observacional de DoH3), DoT (conexões em pool, reutilizadas e renovadas) e DoQ (uma conexão nova por consulta). Os três estão implementados; o DNS do aparelho (o resolvedor da própria rede) é o padrão de fábrica, e as predefinições criptografadas são opcionais (`AppConfiguration.lavaRecommendedDefaults`, definido em `Sources/LavaSecCore/OnboardingDefaults.swift`). As predefinições de resolvedor embutidas (variantes DoH e DoT do Google / Cloudflare / Quad9) são gratuitas; apenas um resolvedor totalmente personalizado é um desbloqueio pago. Veja [filtragem de DNS e listas de bloqueio](../architecture/dns-filtering-and-blocklists.md).
- **Exceções permitidas (lista de permissão)** — adicione domínios manualmente para liberá-los apesar de uma lista de bloqueio; a proteção contra ameaças ainda prevalece. Veja [a visão geral dos recursos do produto](features.md).
- **O Guardião do Escudo Suave** — um mascote na aba Guarda, na Atividade ao Vivo e na Ilha Dinâmica, que mostra o estado da proteção em 7 estados de expressão. Veja [o design system](../design-system/overview.md).
- **Personalização em planos (Lava Security Plus)** — um único plano pago opcional que libera personalização (um orçamento maior de regras de filtro — Gratuito 500 mil / Plus 2 milhões de regras compiladas, sob uma mesma proteção de segurança do aparelho — mais domínios permitidos/bloqueados, listas de bloqueio personalizadas e resolvedores de DNS personalizados). O Plus nunca contorna as proteções sempre ativas — o túnel ignora `isPaid`.
- **Contas e backup opcionais** — login com Apple ou Google, com um backup de configurações criptografado de ponta a ponta ([conhecimento zero](../architecture/accounts-and-backup.md)) e uma frase de recuperação; a exclusão da conta é feita pelo próprio usuário. A opção de recuperação por passkey **também é de conhecimento zero** — sua chave é derivada no aparelho a partir do WebAuthn PRF do autenticador, sem nenhum segredo guardado no servidor; a prontidão para produção no aparelho ainda depende da hospedagem de Associated Domains / AASA **(Planejado)**. As contas são opcionais; a proteção funciona totalmente sem login.
- **Atividade e relatórios apenas locais** — contagens de bloqueio/permissão no aparelho, estado de saúde do túnel e um pacote opcional de relatório de erros, montados a partir de dados que o túnel em execução guarda no aparelho — vazios quando ocioso e ao vivo enquanto protegem. Nenhum histórico de domínios do dia a dia sai do aparelho. Veja [a visão geral dos recursos do produto](features.md).

## Plataformas

- **iOS — disponível.** O Lava é um app de iOS hoje: três pacotes compartilham um App Group (`group.com.lavasec`) — o app (`com.lavasec.app`), a extensão de túnel de pacotes (`.tunnel`) e o widget (`.widget`) — além de fontes compartilhadas, sobre um pacote `LavaSecCore` comum.
- **Android — Planejado.** Está planejado um port nativo em Kotlin / Jetpack Compose sobre o `VpnService` do Android, mantendo a mesma promessa de privacidade e um comportamento central de filtragem testado para ter paridade. Nenhum código do app Android foi disponibilizado ainda.

Veja [Paridade entre plataformas](platform-parity.md) para os ids estáveis dos recursos e o contrato entre iOS/Android.
