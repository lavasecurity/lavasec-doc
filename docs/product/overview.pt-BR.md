---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Visão geral do produto

Bem-vindo ao Lava Security. Esta página é a porta de entrada do conjunto de documentação: uma introdução curta e simples sobre o que é o Lava, o que ele promete e onde ler mais.

## O que é o Lava

O Lava Security é um app iOS com prioridade na privacidade que filtra DNS localmente no dispositivo por meio de um [túnel de pacotes NetworkExtension no dispositivo](../architecture/ios-client.md), bloqueando domínios conhecidos como arriscados e indesejados sem rotear sua navegação pelos servidores do Lava. O túnel de pacotes (`LavaSecTunnel`, um `NEPacketTunnelProvider`) analisa cada consulta DNS no telefone, verifica o domínio solicitado contra um snapshot de filtro compilado e mapeado em memória, e encaminha somente as consultas permitidas para o upstream. Não há nenhum proxy operado pelo Lava pelo qual seu tráfego passe: a filtragem é uma decisão local, tomada no seu dispositivo.

O iOS rotula isso como uma "VPN" porque um túnel de pacotes é a única forma de um app filtrar DNS em todo o sistema — mas o Lava é **filtragem de DNS/blocklist**, não roteamento de tráfego. Seja honesto quanto ao escopo: o Lava é filtragem local de domínios DNS, **não** uma garantia de que todo domínio ou URL malicioso seja bloqueado. Ele enxerga domínios, não caminhos de página, então não consegue bloquear uma página ruim em um host de outra forma confiável. A proteção também não é ativada automaticamente no momento em que o onboarding termina — a aba **Guard** no app é a fonte autoritativa sobre se a proteção está atualmente ativa.

## A promessa de privacidade

> Toda a filtragem de DNS acontece no dispositivo; o Lava nunca roteia sua navegação pelos servidores do Lava e nunca recebe o fluxo de domínios que você visita — o backend guarda apenas metadados de catálogo, um backup criptografado opaco por usuário e diagnósticos anonimizados que você opta por enviar.

Esta frase é canônica. Todo o restante destes documentos deve ser consistente com ela. Pagar pelo tier opcional **não** move a filtragem para o servidor nem dá ao Lava um fluxo dos domínios visitados. Quando um recurso toca um servidor, os documentos detalham o que **não** é enviado — suas consultas DNS rotineiras, seu histórico de navegação e qualquer texto em claro permanecem todos no dispositivo. Veja [o backend e o modelo de dados](../architecture/backend-and-data.md) para o panorama completo.

## Para quem é

O Lava é feito para qualquer pessoa que queira uma navegação mais segura sem ter que gerenciá-la. O público inclui deliberadamente usuários não técnicos — pais configurando proteção para a família, pessoas mais velhas e qualquer um que não queira pensar em DNS de jeito nenhum. A experiência padrão simplesmente funciona: ative a proteção e uma blocklist conservadora começa a filtrar, sem necessidade de conta. Ao mesmo tempo, usuários avançados podem acessar controles mais profundos (blocklists personalizadas, resolvedores alternativos) quando os quiserem.

A voz em todo o app é simples, calma e prática — o perigo é apresentado como metáfora, não como medo.

## Princípios centrais

- **Privacidade é posicionamento, não um recurso pago.** A filtragem é uma decisão local. O backend do Lava é intencionalmente mínimo e nunca recebe seus domínios de navegação rotineiros nem fluxos de eventos DNS. O backup de conta opcional é [zero-knowledge](../architecture/accounts-and-backup.md): os servidores armazenam apenas o texto cifrado e metadados de envelope não secretos.
- **Proteção central gratuita para sempre.** O botão de proteção, as atualizações da blocklist padrão e as contagens locais básicas nunca são bloqueados por paywall e nunca exigem uma conta.
- **No dispositivo.** O mecanismo de proteção vive inteiramente no telefone — a análise de DNS, a avaliação de domínios e o encaminhamento para o upstream acontecem todos dentro da extensão de túnel de pacotes, limitados pelo teto de memória de ~50 MiB por extensão do iOS. As blocklists seguem um modelo [source-url-only](../architecture/dns-filtering-and-blocklists.md): o app busca cada lista upstream diretamente e a analisa localmente; o Lava nunca hospeda nem serve bytes de blocklists de terceiros.
- **O pagamento desbloqueia apenas a personalização — nunca a segurança de base.** A barreira de proteção contra ameaças — um tier não permitível acima de toda blocklist que ninguém, pagante ou não, pode colocar em allowlist — é imposta por precedência de decisão: **barreira de ameaças > allowlist local (exceções permitidas) > blocklist > permitir-por-padrão.** (O slot de precedência está conectado e verificado quanto à integridade por hashes SHA-256 aceitos; atualmente ele é lançado sem entradas.) O túnel ignora `isPaid`.
- **Núcleo calmo, profundidade conquistada.** As superfícies padrão são silenciosas e tranquilizadoras, encabeçadas pelo mascote Soft Shield Guardian e por textos que evitam linguagem baseada no medo. Detalhes mais ricos e técnicos estão disponíveis quando você vai procurá-los, mas nunca são impostos a você. Essa filosofia de "núcleo calmo, profundidade conquistada" é formalizada no modelo de profundidade **LavaTier** (Floor / Window / Workshop) — veja [o design system](../design-system/overview.md).

## Capacidades de alto nível

- **Filtragem local de DNS** — o mecanismo de túnel de pacotes que analisa o DNS, avalia cada domínio contra o snapshot compilado e encaminha as consultas permitidas para o upstream com fallback para o DNS do dispositivo. Veja [o cliente iOS](../architecture/ios-client.md) e [filtragem de DNS e blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Blocklists curadas, source-url-only** — o Lava publica apenas as URLs das listas upstream (além de hashes consultivos para identidade de cache e auditoria); o dispositivo busca cada lista por TLS e a analisa localmente sob limites de tamanho/regras, e o Lava nunca espelha nem serve bytes de blocklists de terceiros. As listas da comunidade não têm hash fixado — TLS + a URL curada são a fronteira de integridade — enquanto o tier de barreira contra ameaças do Lava permanece com hash imposto. O padrão lançado habilita a **Block List Basic** (`AppConfiguration.lavaRecommendedDefaults`, definida em `OnboardingDefaults.swift`); fontes copyleft como HaGeZi, OISD, AdGuard e 1Hosts são opt-in. Veja [filtragem de DNS e blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Transportes de DNS criptografados** — DoH (com anotação observacional DoH3), DoT (conexões em pool, reutilizadas e renovadas) e DoQ (conexão nova por consulta). Os três estão implementados; o DNS do dispositivo (o resolvedor da própria rede) é o padrão lançado, e os presets criptografados são opt-in (`AppConfiguration.lavaRecommendedDefaults`, definido em `Sources/LavaSecCore/OnboardingDefaults.swift`). Os presets de resolvedores integrados (variantes DoH e DoT de Google / Cloudflare / Quad9) são gratuitos; apenas um resolvedor totalmente personalizado é um desbloqueio pago. Veja [filtragem de DNS e blocklists](../architecture/dns-filtering-and-blocklists.md).
- **Exceções permitidas (allowlist)** — adicione domínios manualmente para permitir apesar de uma blocklist; a barreira contra ameaças ainda prevalece. Veja [a visão geral dos recursos do produto](features.md).
- **O Soft Shield Guardian** — um mascote na aba Guard, na Live Activity e na Dynamic Island que expressa o estado da proteção em 7 estados de expressão. Veja [o design system](../design-system/overview.md).
- **Personalização em tiers (Lava Security Plus)** — um tier pago opcional que desbloqueia a personalização (um orçamento maior de regras de filtro — Free 500K / Plus 2M de regras compiladas sob uma barreira de segurança de dispositivo compartilhada — mais domínios permitidos/bloqueados, blocklists personalizadas e resolvedores DNS personalizados). O Plus nunca contorna as barreiras sempre ativas — o túnel ignora `isPaid`.
- **Contas e backup opcionais** — login com Apple ou Google com um backup de configurações criptografado de ponta a ponta ([zero-knowledge](../architecture/accounts-and-backup.md)) e uma frase de recuperação; a exclusão de conta é autosserviço. O slot opcional de recuperação por passkey é **também zero-knowledge** — sua chave é derivada no dispositivo a partir do WebAuthn PRF do autenticador, sem nenhum segredo guardado no servidor; a prontidão para produção no dispositivo ainda depende da hospedagem de Associated Domains / AASA **(Planejado)**. As contas são opcionais; a proteção funciona totalmente desconectado.
- **Atividade e relatórios apenas locais** — contagens de bloqueio/permissão no dispositivo, saúde do túnel e um pacote de relatório de bug opcional, montados a partir de dados que o túnel em execução mantém no dispositivo — vazios quando ocioso e ao vivo enquanto protege. Nenhum histórico rotineiro de domínios sai do dispositivo. Veja [a visão geral dos recursos do produto](features.md).

## Plataformas

- **iOS — lançado.** O Lava é um app iOS hoje: três bundles compartilham um App Group (`group.com.lavasec`) — o app (`com.lavasec.app`), a extensão de túnel de pacotes (`.tunnel`) e o widget (`.widget`) — além de fontes compartilhadas, sobre um pacote `LavaSecCore` comum.
- **Android — Planejado.** Está planejado um port nativo em Kotlin / Jetpack Compose sobre o `VpnService` do Android, carregando a mesma promessa de privacidade e um comportamento central de filtragem testado para paridade. Nenhum código do app Android é lançado ainda.

Veja [Paridade de plataformas](platform-parity.md) para os ids de recursos estáveis e o contrato iOS/Android.
