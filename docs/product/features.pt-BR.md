---
last_reviewed: 2026-06-19
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Catálogo de recursos

> Público: PM / engenharia. Este catálogo cobre apenas o conjunto de recursos **atual, já implementado**. Tudo o que foi projetado mas ainda não construído fica no roteiro privado, não aqui.

Lava Security é um app de iOS com foco em privacidade que filtra DNS **localmente no aparelho** por meio de um túnel de pacotes NetworkExtension, bloqueando domínios maliciosos e indesejados para usuários não técnicos (pais, mães e pessoas idosas) — com a proteção essencial gratuita para sempre e sem precisar de conta.

A promessa de privacidade por trás de cada recurso abaixo:

> Toda a filtragem de DNS acontece no aparelho; o Lava nunca roteia sua navegação pelos servidores dele e nunca recebe a sequência de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado e opaco por usuário, e diagnósticos anônimos que você escolhe enviar.

## Como ler este catálogo

- **Free** — disponível para todos, sem conta, sem compra.
- **Plus** — liberado pelo Lava Security Plus, o único nível pago opcional. O Plus libera **apenas personalização**; ele nunca restringe a segurança básica e nunca permite que um usuário pagante contorne a proteção contra ameaças.
- Toda linha é **Implementado** a menos que sinalizada no próprio texto. Legenda de status: **Implementado** = entregue e confirmado no código; **Planejado** = projetado, ainda não construído; **Descartado** = rejeitado ou revertido. Itens Planejados/Descartados ficam documentados no roteiro privado, não aqui.

Os tetos de cada nível, fonte da verdade, ficam em `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, com o apelido `.plus`). A **trava** do direito ao Plus é um sinalizador local (`isPaid`) — a fonte da verdade. O backend **espelha** os direitos da App Store (`POST /v1/account/entitlements/app-store-sync` insere/atualiza uma linha `entitlements`), mas essa linha é um espelho, não a trava; nenhuma sincronização do backend controla a liberação por enquanto.

---

## 1. Proteção e VPN

O núcleo do produto: um túnel de pacotes local apenas de DNS e o modelo de estados tranquilo ao redor dele.

| Recurso | Nível | Observações |
|---|---|---|
| **Túnel de pacotes local apenas de DNS** | Free | O `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercepta o DNS e avalia cada domínio no próprio aparelho. Nenhum tráfego de navegação é roteado pelo Lava. Endereço do túnel `10.255.0.2`, servidor DNS `10.255.0.1`. |
| **Ordem de prioridade da decisão de filtro** | Free | `bloqueio da proteção contra ameaças > lista de permissões local (exceções permitidas) > lista de bloqueio > permitir por padrão`; domínios inválidos são bloqueados. (`FilterSnapshot.decision()`.) |
| **Ordem de prioridade das consultas (bootstrap primeiro)** | Free | `bootstrap do resolvedor > pausa temporária > filtro` — o próprio hostname do resolvedor nunca é bloqueado. (`DNSQueryDispatcher`.) |
| **Início a frio com falha segura (fail-closed)** | Free | Um túnel iniciado a frio, sem um snapshot reutilizável, instala um `FailClosedRuntimeSnapshot` que bloqueia todo o tráfego em vez de deixar vazar DNS não filtrado. |
| **Conectar sob demanda** | Free | O `NEOnDemandRuleConnect` mantém a proteção ativa / a reinicia automaticamente — habilitado **somente após** uma conexão confirmada, nunca na instalação do perfil, e neutralizado durante uma configuração inicial incompleta, para que uma instalação nova não suba um túnel impossível de desligar. |
| **Pausa temporária (5 / 10 min) + retomar** | Free | Pausar/retomar passam pelo `LavaProtectionCommandService` sob um bloqueio de arquivo flock com deduplicação por revisão. |
| **Pausa que exige autenticação** | Free | Trava opcional por superfície (`SecurityProtectedSurface.protectionPause`): a pausa exige autenticação local do aparelho; o serviço de comandos recusa uma pausa não autenticada e a Live Activity oculta os botões de pausa. |
| **Reconectar** | Free | Reinicia o túnel diretamente (ignora o fluxo de pausa do serviço de comandos). |
| **Modelo de estados do Guardião Soft Shield** | Free | 7 estados de expressão — `dormindo, acordando, desperto, pausado, tentando de novo, preocupado, agradecido` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 níveis de gravidade de conectividade se resumem a 4 rostos; renderizados de forma idêntica no app, na configuração inicial e na Live Activity. |
| **Avaliação de conectividade** | Free | 6 níveis de gravidade (`saudável, recuperando, usando o DNS do aparelho como reserva, DNS lento, rede indisponível, precisa reconectar`) definem o rosto do guardião e o texto de status. |
| **Otimização de desempenho** | Free | Ativação a partir do cache, junção de consultas em andamento, busca com paralelismo limitado e junção de oscilações (ativação a quente medida em ~112 ms no iPhone 15 Pro, conforme o trabalho de aceleração modular). |

> **Limite de proteção do aparelho (para todos, nunca atrás de pagamento):** um teto rígido de `~3,26 mi de regras` (meta de 32 MB residentes dentro do teto de memória do iOS de `~50 MiB` por extensão) é aplicado a todos os usuários, acima de qualquer nível (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Configurações acima do orçamento são rejeitadas de forma determinística (`exceedsDeviceMemoryBudget`) em vez de deixar o túnel ser encerrado pelo jetsam.

---

## 2. Listas de bloqueio e filtragem

O que é bloqueado, como as listas são escolhidas e a divisão entre os níveis.

| Recurso | Nível | Observações |
|---|---|---|
| **Listas de bloqueio só com a URL de origem** | Free | O Lava publica apenas a URL de origem + os hashes aceitos; o próprio aparelho busca/processa os **bytes** da lista. O Lava **nunca** armazena, espelha, transforma ou serve os bytes de listas de bloqueio de terceiros. Veja a [decisão de conformidade GPL com URL de origem somente](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catálogo curado (10 fontes)** | Gratuito para ativar | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **Listas de bloqueio padrão gratuitas** | Free | Uma instalação nova ativa o **Block List Project Phishing + Scam** (as duas fontes marcadas com `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **Processamento / normalização / deduplicação no aparelho** | Free | O `BlocklistParser` suporta auto/plain/hosts/adblock/dnsmasq, descarta comentários/linhas em branco/entradas inválidas, deduplica strings exatas e limita em 1.000.000 de regras por lista. |
| **Validação dos bytes de origem** | Free | Os bytes buscados passam por SHA-256 e só são aceitos se a soma de verificação estiver em `accepted_source_hashes` do catálogo; em caso de divergência, o Lava recorre ao último cache válido ou falha de forma segura. |
| **Filtro de domínios protegidos** | Free | Toda fonte processada tem removidos os domínios protegidos do Lava / Apple / provedores de identidade (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …), para que uma lista de origem não quebre o app, o túnel ou o login. |
| **Exceções permitidas (lista de permissões)** | Free | Lista de permissões gerenciada pelo usuário, que libera domínios apesar das listas de bloqueio. Limite Free: 10 permitidos / 10 bloqueados (`FeatureLimits.free`). |
| **Orçamento de regras de filtro (métrica de nível)** | Free / Plus | A métrica de nível que vai no app é o total de **regras** de domínio compiladas: **Free 500 mil / Plus 2 mi** (`maxFilterRules` em `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Substitui o antigo limite por contagem de listas. Configurações acima do nível geram `exceedsTierFilterRuleLimit`. |
| **Limites de domínios maiores** | Plus | 500 permitidos / 500 bloqueados (`FeatureLimits.plus`). |
| **Listas de bloqueio personalizadas** | Plus | `allowsCustomBlocklists`. Listas personalizadas são buscadas e processadas no aparelho, armazenadas localmente em cache, nunca repassadas aos servidores do Lava. |
| **Reuso de artefato em início a quente** | Free | Um manifesto + impressão digital de identidade permitem que o túnel reutilize o snapshot compacto em disco sem recompilar; o reuso é rejeitado (com um motivo seguro para a privacidade, contendo só o nome do campo) quando as entradas mudam. |

> A aplicação autoritativa do orçamento acontece em tempo de compilação sobre a união deduplicada (`FilterSnapshotPreparationService`); o limite do aparelho é verificado primeiro, depois o limite do nível. O medidor da interface, no momento da seleção, usa uma soma por lista com uma margem de teto suave de 1,10.

---

## 3. DNS criptografado

Transportes de resolvedor e roteamento para consultas não bloqueadas.

| Recurso | Nível | Observações |
|---|---|---|
| **Cinco transportes de resolvedor** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH baseado em URLSession que prefere HTTP/3. A interface anota **`DoH3` (sem barra)**, por exemplo "Quad9 (DoH3)", **somente quando uma negociação h3 é de fato observada** — preferido, nunca prometido (`DoHTransport`). |
| **DoT** | Free | `NWConnection`s reaproveitadas (até 4 por endpoint) com renovação por inatividade e uma nova tentativa com conexão nova. |
| **DoQ** (apenas personalizado) | Plus | O DNS-over-QUIC **não tem predefinição embutida** — só é acessível por um **resolvedor `doq://` personalizado**, e DNS personalizado é Plus. Abre uma **conexão QUIC nova por consulta** (o pool de 4 vias dá concorrência, não reaproveitamento de handshake); o reaproveitamento de conexão fica adiado para um piso de implantação no iOS 26. |
| **Resolvedores predefinidos** | Free | DNS do aparelho (padrão), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — nas variantes IP / DoH / DoT onde oferecidas (`DNSResolverPreset.allPresets`). |
| **Roteamento de resolvedores e failover** | Free | O `ResolverOrchestrator` roteia por transporte, recorre ao DNS comum quando um plano criptografado não tem endpoints, faz failover por endpoint com uma trava de backoff e, então, recorre ao DNS do aparelho. |
| **Reserva para o DNS do aparelho** | Free | Recorre ao resolvedor da rede atual quando o resolvedor selecionado está indisponível; **ativado por padrão**. Aparece como o nível de gravidade `usingDeviceDNSFallback`. |
| **DNS personalizado** | Plus | `allowsCustomDNS` — resolvedor fornecido pelo usuário (incluindo a leitura de DNS stamps para predefinições personalizadas). |

---

## 4. Contas e backup com conhecimento zero

Login de conta opcional e backup criptografado das configurações. Nada disso é necessário para usar a proteção.

| Recurso | Nível | Observações |
|---|---|---|
| **Login de conta opcional (Apple + Google)** | Free | Fluxo nativo de id_token trocado no Supabase Auth (`grant_type=id_token`) com um nonce em hash; apenas a sessão Supabase resultante fica armazenada localmente no aparelho, na Keychain. O login com e-mail/senha foi intencionalmente deixado de fora (Descartado). |
| **Backup criptografado com conhecimento zero** | Free | Envelope AES-256-GCM no lado do cliente; a chave aleatória do conteúdo é envolvida em slots de chave PBKDF2-HMAC-SHA256 (210 mil iterações). Só o texto cifrado + metadados não secretos sobem para o `user_backups` do Supabase (RLS por usuário). O servidor não consegue descriptografar sem um segredo que fica com o usuário. |
| **Conteúdo de backup minimizado** | Free | Faz backup dos IDs de listas de bloqueio ativadas, domínios permitidos/bloqueados, configurações de resolvedor, preferências de registro local, aparência do guardião etc. — e exclui explicitamente `isPaid`, sinalizadores de QA, diagnósticos, snapshots e os bytes completos das listas de bloqueio. |
| **Slot de chave do segredo do aparelho** | Free | Um segredo de 32 bytes do aparelho, na Keychain exclusiva do aparelho (`...ThisDeviceOnly`, não sincronizada com o iCloud), para restauração tranquila no mesmo aparelho. |
| **Frase de recuperação + recuperação assistida** | Free | Uma frase CVCV de 8 palavras (~105 bits) combinada com uma parte de recuperação guardada no servidor, via SHA256, para destravar o slot de recuperação assistida. Dois fatores: nenhuma das metades sozinha descriptografa. |
| **Slot de recuperação por passkey** | Free | Slot opcional protegido por WebAuthn, e com **conhecimento zero**: sua chave de desbloqueio é derivada **no aparelho** a partir da saída PRF WebAuthn do autenticador (`hmac-secret`) (HKDF-SHA256). O servidor não registra nenhuma passkey, não emite desafios, não guarda nenhum segredo de recuperação e não expõe rotas de passkey — o desenho anterior de custódia no servidor foi descartado. A prontidão para produção em aparelhos físicos depende da hospedagem de Associated Domains / AASA (Planejado). |
| **Exclusão de conta / direitos sobre os dados** | Free | Um endpoint autenticado do Worker exclui backups, configurações, direitos, perfil e anexos de relatórios de bug, e depois o usuário do Supabase Auth; o app encerra a sessão e limpa o material de desbloqueio local. |

---

## 5. Widget e Live Activity

Presença na tela de bloqueio e na Dynamic Island.

| Recurso | Nível | Observações |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): uma única `Activity<LavaActivityAttributes>` na tela de bloqueio e na Dynamic Island (centro expandido / guardião compactLeading / compactTrailing + glifo de status mínimo). |
| **Exibição de proteção em 5 estados** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — cada um mapeia para uma pose do guardião, um SF Symbol e um título. |
| **Botões de ação da Live Activity** | Free | Pausar 5 / 10 min, Retomar, Reconectar — `LiveActivityIntent`s que rodam no processo do app via `LavaProtectionCommandService`. As variantes de pausa autenticada exigem autenticação local do aparelho. |
| **Reconciliação única, deduplicada e controlada por revisão** | Free | O `LavaLiveActivityController` mantém uma só Activity, atualiza apenas quando o id/conteúdo muda de verdade e controla as atualizações pela revisão do `ProtectionPauseStore`, para que novas tentativas de intents antigos não revertam o estado. |
| **Interruptor das Live Activities** | Free | Pode ser ativado/desativado pelo usuário em Ajustes (`setUsesLiveActivities`), disponível só em iPhone/iPad. |

---

## 6. Configuração inicial

Fluxo de primeira execução que instala a configuração de VPN local e define padrões sensatos.

| Recurso | Nível | Observações |
|---|---|---|
| **Fluxo de primeira execução com várias telas** | Free | `OnboardingFlowView` — 6 telas: `lava, guardIntro, features, vpn, notifications, done`. (A instalação do perfil e o pedido de notificação acontecem no passo certo, não logo de cara.) |
| **Instalação do perfil de VPN local** | Free | Instala a configuração de VPN local durante a configuração inicial **sem** habilitar o Conectar sob demanda, para que a proteção nunca fique silenciosamente ligada ao terminar — a superfície do Guard continua sendo a autoridade. |
| **Pedido de permissão de notificações** | Free | Solicitado dentro do fluxo, no passo de notificações. |
| **Padrões recomendados aplicados** | Free | Resolvedor DNS do aparelho, reserva para o DNS do aparelho ativada, registro local ativado (contagens + histórico + atividade), Block List Project Phishing + Scam ativados, continuar sem conta (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Ajustes

Superfícies de configuração, segurança, diagnóstico e feedback.

| Recurso | Nível | Observações |
|---|---|---|
| **Senha de desbloqueio do app + biometria** | Free | `SecurityController`: verificador de senha SHA256 com sal na Keychain + biometria `LAContext`, com uma sobreposição que bloqueia o desbloqueio do app e uma máscara de privacidade nas mudanças de fase da cena. |
| **Proteção por superfície** | Free | O `SecurityProtectedSurface` controla seis superfícies: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Cada uma pode exigir, de forma independente, autenticação local do aparelho (por exemplo, a aba Ajustes retorna `.requires(.appSettings)`). |
| **Seletor de aparência do Lava Guard (7 aparências)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, cada um com uma cor de glifo combinada na Dynamic Island. |
| **Combinar com o ícone do app** | Free | Ícone alternativo opcional do app, combinado com a aparência do guardião selecionada. |
| **Aparência** | Free | Esquema de cores claro/escuro/sistema. |
| **Controles de registro só local** | Free | Interruptores para contagens de filtragem, histórico de domínios (diagnósticos) e atividade de rede — tudo armazenado no aparelho. |
| **Relatórios / Atividade (detalhe do Guard)** | Free | Diagnósticos dinâmicos só locais: contagens de bloqueio/permissão, saúde do túnel, principais domínios. As linhas de domínio só aparecem quando a opção de histórico está ativada. Acessado como uma tela de detalhe a partir da aba Guard (`GuardDestination.activity`). |
| **Filtros (detalhe do Guard)** | Free | Tela de filtros começando por uma visão geral, com detalhes de Domínios Bloqueados / Exceções Permitidas e um fluxo de rascunho em etapas de visualizar/editar/confirmar (`GuardDestination.filters`). |
| **Registro de atividade de Rede e Estado do Lava** | Free | Fluxo limitado e só local de eventos das transições de rede/tempo de execução/usuário, compartilhado via App Group (`NetworkActivityLog`). |
| **Relatório de bug** | Free | Assistente acionado pelo usuário que envia um pacote anônimo para `POST /v1/bug-reports`; sem histórico de domínios na v1. Também acessível chacoalhando o aparelho para reportar (`RageShakeDetector`). |
| **Avisos legais + Versão** | Free | Os Ajustes mostram avisos legais de terceiros (veja [Avisos de terceiros](../legal/third-party-notices.md)) e uma página de versão/build. |

---

## Arquitetura do app (para orientação)

Três bundles compartilham um App Group `group.com.lavasec`, junto de uma pasta de fontes `lavasec-ios: Shared/` compilada dentro deles:

- **LavaSecApp** (`com.lavasec.app`) — a casca do app em SwiftUI; nesta build, a raiz é um `TabView` de duas abas (**Guard** + **Ajustes**), com Filtros e Atividade acessados como telas de detalhe dentro da aba Guard.
- **LavaSecTunnel** (`.tunnel`) — o mecanismo de filtragem/resolução de DNS no aparelho.
- **LavaSecWidget** (`.widget`) — a Live Activity do WidgetKit.
- **Shared/** — fontes compartilhadas entre os alvos (não é um bundle): App Group, serviço de comandos, mascote, atributos/intents da Live Activity.

O controle entre app ↔ extensão usa **mensagens de provedor** do `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), não notificações Darwin. As regras de filtro vão do app → extensão como arquivos de snapshot do App Group (`filter-snapshot.json` / `.compact`).

---

## Documentos relacionados

- Roteiro — recursos planejados e descartados (posicionamento de preço/StoreKit do Plus, port para Android, proteção em nível de URL, prontidão de Associated Domain para passkey, minijogo easter-egg, lançamento de código aberto GPL-3.0 etc.) ficam no roteiro privado, não neste catálogo público.
- [Decisão de conformidade GPL com URL de origem somente](../legal/gpl-source-url-only-compliance-decision.md)
- [Ressalva sobre os termos de dados de listas de código aberto](../legal/open-source-list-data-terms-carveout.md)
- [Avisos de terceiros](../legal/third-party-notices.md)
