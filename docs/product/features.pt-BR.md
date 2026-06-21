---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Catálogo de recursos

> Público: PM / engenharia. Este catálogo cobre apenas o conjunto de recursos **atual e já implementado**. Qualquer coisa projetada mas ainda não construída fica no roadmap privado, não aqui.

Lava Security é um app iOS com a privacidade em primeiro lugar que filtra DNS **localmente no dispositivo** por meio de um túnel de pacotes da NetworkExtension, bloqueando domínios maliciosos e indesejados para pessoas não técnicas (pais, idosos) — com a proteção principal gratuita para sempre e sem precisar de conta.

A promessa de privacidade por trás de cada recurso abaixo:

> Toda a filtragem de DNS acontece no dispositivo; a Lava nunca encaminha sua navegação pelos servidores dela e nunca recebe a sequência de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado e opaco por usuário, e diagnósticos anonimizados que você escolhe enviar.

## Como ler este catálogo

- **Free** — disponível para todo mundo, sem conta, sem compra.
- **Plus** — desbloqueado pelo Lava Security Plus, o único nível pago opcional. O Plus desbloqueia **apenas personalização**; ele nunca trava a segurança básica e nunca deixa um usuário pagante burlar a proteção contra ameaças.
- Toda linha está **Implementada**, a menos que sinalizado em linha. Legenda de status: **Implementado** = entregue e confirmado no código; **Planejado** = projetado, não construído; **Descartado** = rejeitado ou revertido. Itens Planejados/Descartados estão documentados no roadmap privado, não aqui.

Os tetos de cada nível, que são a fonte da verdade, ficam em `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, com alias `.plus`). O **gate** do direito Plus é uma flag local (`isPaid`) — a fonte da verdade. O backend **espelha** os direitos da App Store (`POST /v1/account/entitlements/app-store-sync` insere/atualiza uma linha `entitlements`), mas essa linha é um espelho, não o gate; nenhuma sincronização de backend controla o gating ainda.

---

## 1. Proteção e VPN

O produto principal: um túnel de pacotes local somente de DNS e o modelo de estado calmo ao redor dele.

| Recurso | Nível | Observações |
|---|---|---|
| **Túnel de pacotes local somente de DNS** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercepta o DNS e avalia cada domínio no dispositivo. Nenhum tráfego de navegação é encaminhado pela Lava. Endereço do túnel `10.255.0.2`, servidor DNS `10.255.0.1`. |
| **Precedência da decisão de filtragem** | Free | `bloqueio da proteção contra ameaças > allowlist local (exceções permitidas) > blocklist > permitir por padrão`; domínios inválidos são bloqueados. (`FilterSnapshot.decision()`.) |
| **Precedência de consultas (bootstrap primeiro)** | Free | `resolver-bootstrap > pausa temporária > filtro` — o próprio nome de host do resolver nunca é bloqueado. (`DNSQueryDispatcher`.) |
| **Início a frio à prova de falhas (fail-closed)** | Free | Um túnel a frio sem snapshot reutilizável instala um `FailClosedRuntimeSnapshot` que bloqueia todo o tráfego em vez de vazar DNS não filtrado. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` mantém a proteção ativa / a reinicia automaticamente — habilitado **apenas depois** de uma conexão confirmada, nunca na instalação do perfil, e neutralizado durante uma integração incompleta para que uma instalação nova não suba um túnel impossível de desligar. |
| **Pausa temporária (5 / 10 min) + retomar** | Free | Pausar/retomar passam pelo `LavaProtectionCommandService` sob um bloqueio de arquivo flock com deduplicação por revisão. |
| **Pausa que exige autenticação** | Free | Gate opcional por superfície (`SecurityProtectedSurface.protectionPause`): a pausa exige autenticação local do dispositivo; o serviço de comando nega uma pausa não autenticada e a Live Activity esconde os botões de pausa. |
| **Reconectar** | Free | Reinicia o túnel diretamente (ignora o pipeline de pausa do serviço de comando). |
| **Modelo de estado do Soft Shield Guardian** | Free | 7 estados de expressão — `dormindo, acordando, acordado, pausado, tentando de novo, preocupado, grato` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 severidades de conectividade se reduzem a 4 expressões; renderizadas de forma idêntica no app, na integração e na Live Activity. |
| **Avaliação de conectividade** | Free | 6 severidades (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) controlam a expressão do guardião e o texto de status. |
| **Reforço de desempenho** | Free | Ativação com cache em primeiro lugar, agrupamento de consultas em andamento, busca com paralelismo limitado e agrupamento de oscilações (ativação a quente medida em ~112 ms no iPhone 15 Pro, segundo o trabalho de aceleração modular). |

> **Proteção do dispositivo (todo mundo, nunca um paywall):** um teto rígido de `~3,26M de regras` (alvo de 32 MB residentes sob o limite de memória do iOS de `~50 MiB` por extensão) é aplicado a todos os usuários, acima de qualquer nível (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Configurações acima do orçamento são rejeitadas de forma determinística (`exceedsDeviceMemoryBudget`) em vez de deixar o túnel sofrer jetsam.

---

## 2. Blocklists e filtragem

O que é bloqueado, como as listas são escolhidas e a fronteira entre os níveis.

| Recurso | Nível | Observações |
|---|---|---|
| **Blocklists só por URL de origem** | Free | A Lava publica apenas a URL de origem + hashes aceitos; o dispositivo busca/analisa os **bytes** da lista por conta própria. A Lava **nunca** armazena, espelha, transforma ou serve bytes de blocklists de terceiros. Veja [decisão de conformidade GPL somente por URL de origem](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catálogo curado (10 fontes)** | Free para habilitar | `lavasec-ios: Sources/LavaSecCore/BlocklistModels.swift` (`DefaultCatalog.curatedSources`): Block List Basic, Block List Project Phishing / Scam / Ransomware, Phishing.Database Active Domains, HaGeZi Multi Light / Normal / PRO mini / PRO, OISD Small. |
| **Blocklists padrão gratuitas** | Free | Uma instalação nova habilita **Block List Project Phishing + Scam** (as duas fontes marcadas com `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). |
| **Análise / normalização / deduplicação no dispositivo** | Free | O `BlocklistParser` suporta auto/plain/hosts/adblock/dnsmasq, descarta comentários/linhas em branco/inválidas, deduplica strings exatas e limita a 1.000.000 de regras por lista. Uma linha `hosts` com vários hosts agora emite **todos** os hosts da linha, não só o primeiro (regras do parser versão 2). |
| **Validação de bytes da origem** | Free | Os bytes buscados passam por SHA-256 e só são aceitos se o checksum estiver em `accepted_source_hashes` do catálogo; em caso de divergência, a Lava recorre ao último cache bom ou falha de forma fechada. |
| **Filtro de domínios protegidos** | Free | Toda fonte analisada tem removidos os domínios protegidos da Lava / Apple / provedores de identidade (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …) para que uma lista de origem não consiga quebrar o app, o túnel ou o login. |
| **Exceções permitidas (allowlist)** | Free | Allowlist gerenciada pelo usuário que permite domínios apesar das blocklists. Limite Free: 25 permitidos / 25 bloqueados (`FeatureLimits.free`). |
| **Orçamento de regras de filtro (métrica de nível)** | Free / Plus | A métrica de nível em uso é o total de **regras** de domínio compiladas: **Free 500K / Plus 2M** (`maxFilterRules` em `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Substitui o antigo limite por contagem de listas. Configurações acima do nível mostram `exceedsTierFilterRuleLimit`. |
| **Limites de domínio maiores** | Plus | 1.000 permitidos / 1.000 bloqueados (`FeatureLimits.plus`). |
| **Blocklists personalizadas** | Plus | `allowsCustomBlocklists`. As listas personalizadas são buscadas e analisadas no dispositivo, armazenadas em cache localmente, nunca repassadas aos servidores da Lava. |
| **Reutilização de artefato na inicialização a quente** | Free | Um manifesto + impressão digital de identidade permitem que o túnel reutilize o snapshot compacto em disco sem recompilar; a reutilização é rejeitada (com um motivo seguro para a privacidade, apenas com o nome do campo) quando as entradas mudam. |
| **Smart Save (confirmação só ao enfraquecer)** | Free | Edições no seu filtro que apenas *fortalecem* ou são neutras (adicionar uma blocklist ou um domínio bloqueado) se aplicam diretamente; edições que *enfraquecem* a proteção — remover uma blocklist, remover um domínio bloqueado ou adicionar uma exceção permitida — passam antes por uma folha de confirmação de revisão, com um painel "Tenha um cuidado extra" quando exceções são adicionadas (`FiltersView.saveChanges()`, `weakensProtection`). |
| **Medidor de orçamento (seleção salvável)** | Free / Plus | O medidor de seleção abrevia as contagens (500K / 1.2M / 2M) e usa uma margem de teto suave de 1,10 (a soma por lista superestima a união deduplicada em ~7–10%); uma contagem ainda dentro da tolerância é fixada para mostrar, por exemplo, "500K de 500K" até passar do teto suave (`FilterRuleBudget`). |

> A aplicação autoritativa do orçamento roda em tempo de compilação sobre a união deduplicada (`FilterSnapshotPreparationService`); o limite do dispositivo é checado primeiro, depois o limite do nível. O medidor da interface, no momento da seleção, usa uma soma por lista com uma margem de teto suave de 1,10.

---

## 3. DNS criptografado

Transportes do resolver e roteamento para consultas não bloqueadas.

| Recurso | Nível | Observações |
|---|---|---|
| **Cinco transportes de resolver** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH baseado em URLSession que prefere HTTP/3. A interface anota **`DoH3` (sem barra)**, por exemplo "Quad9 (DoH3)", **apenas quando uma negociação h3 é de fato observada** — preferido, nunca prometido (`DoHTransport`). |
| **DoT** | Free | `NWConnection`s em pool (até 4 por endpoint) com atualização por inatividade e uma tentativa de reconexão com conexão nova. |
| **DoQ** (somente personalizado) | Plus | O DNS-over-QUIC **não tem preset embutido** — só é acessível por meio de um **resolver `doq://` personalizado**, e o DNS personalizado é Plus. Abre uma **nova conexão QUIC por consulta** (o pool de 4 vias dá concorrência, não reuso de handshake); o reuso de conexão fica adiado para um piso de implantação no iOS 26. |
| **Resolvers predefinidos** | Free | Device DNS (padrão), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — nas variantes IP / DoH / DoT onde oferecidas (`DNSResolverPreset.allPresets`). |
| **Roteamento e failover do resolver** | Free | O `ResolverOrchestrator` roteia por transporte, faz downgrade para DNS comum quando um plano criptografado não tem endpoints, faz failover por endpoint com um gate de backoff e, então, recorre ao device-DNS. |
| **Fallback para DNS do dispositivo** | Free | Recorre ao resolver da rede atual quando o resolver selecionado está indisponível; **ativo por padrão**. Exibido como a severidade `usingDeviceDNSFallback`. |
| **DNS personalizado** | Plus | `allowsCustomDNS` — resolver informado pelo usuário (incluindo a análise de DNS-stamp para presets personalizados). |

---

## 4. Contas e backup de conhecimento zero

Login de conta opcional e backup criptografado das configurações. Nada disso é necessário para usar a proteção.

| Recurso | Nível | Observações |
|---|---|---|
| **Login de conta opcional (Apple + Google)** | Free | Fluxo nativo de id_token trocado no Supabase Auth (`grant_type=id_token`) com um nonce com hash; apenas a sessão do Supabase resultante é armazenada localmente no dispositivo, no Keychain. Login por e-mail/senha intencionalmente não é oferecido (Descartado). |
| **Backup criptografado de conhecimento zero** | Free | Envelope AES-256-GCM no lado do cliente; a chave aleatória do payload é envolvida em slots de chave PBKDF2-HMAC-SHA256 (210 mil iterações). Apenas o texto cifrado + metadados não secretos sobem para o `user_backups` do Supabase (RLS por usuário). O servidor não consegue descriptografar sem um segredo em posse do usuário. |
| **Payload de backup minimizado** | Free | Faz backup dos IDs de blocklists habilitadas, domínios permitidos/bloqueados, configurações do resolver, preferências de log local, aparência do guardião etc. — e exclui explicitamente `isPaid`, flags de QA, diagnósticos, snapshots e os bytes completos das blocklists. |
| **Slot de chave com segredo do dispositivo** | Free | Um segredo de dispositivo de 32 bytes no Keychain exclusivo do dispositivo (`...ThisDeviceOnly`, não sincronizado pelo iCloud) para uma restauração contínua no mesmo dispositivo. |
| **Frase de recuperação + recuperação assistida** | Free | Uma frase CVCV de 8 palavras (~105 bits) combinada com uma parte de recuperação em posse do servidor, via SHA256, para desbloquear o slot de recuperação assistida. Dois fatores: nenhuma metade sozinha descriptografa. |
| **Slot de recuperação por passkey** | Free | Slot opcional, controlado por WebAuthn, e de **conhecimento zero**: sua chave de desembrulho é derivada **no dispositivo** a partir da saída do WebAuthn PRF (`hmac-secret`) do autenticador (HKDF-SHA256). O servidor não registra nenhuma passkey, não emite desafios, não guarda segredo de recuperação e não expõe rotas de passkey — o projeto anterior de custódia no servidor foi descartado. A prontidão de produção em dispositivos físicos depende de Associated Domains / hospedagem AASA (Planejado). |
| **Exclusão de conta / direitos sobre dados** | Free | Um endpoint do Worker autenticado exclui backups, configurações, direitos, perfil e anexos de relatórios de bug e, então, o usuário do Supabase Auth; o app desconecta e limpa o material de desbloqueio local. |

---

## 5. Widget e Live Activity

Presença na tela de bloqueio e na Dynamic Island.

| Recurso | Nível | Observações |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): uma única `Activity<LavaActivityAttributes>` na tela de bloqueio e na Dynamic Island (centro expandido / guardião compactLeading / compactTrailing + glifo de status mínimo). |
| **Exibição de proteção em 5 estados** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — cada um mapeia para uma pose do guardião, um SF Symbol e um título. |
| **Botões de ação da Live Activity** | Free | Pausar 5 / 10 min, Retomar, Reconectar — `LiveActivityIntent`s que rodam no processo do app via `LavaProtectionCommandService`. As variantes de pausa autenticada exigem autenticação local do dispositivo. |
| **Reconciliação única, deduplicada e controlada por revisão** | Free | O `LavaLiveActivityController` mantém uma única Activity, atualiza apenas em mudança real de id/conteúdo e controla as atualizações pela revisão do `ProtectionPauseStore`, para que novas tentativas de intent obsoletas não revertam o estado. |
| **Alternar Live Activities** | Free | Pode ser ativado/desativado pelo usuário nas Configurações (`setUsesLiveActivities`), disponível só no iPhone/iPad. |

---

## 6. Integração (onboarding)

Fluxo de primeira execução que instala a config local de VPN e define padrões sensatos.

| Recurso | Nível | Observações |
|---|---|---|
| **Fluxo de primeira execução com várias páginas** | Free | `OnboardingFlowView` — 6 páginas: `lava, guardIntro, features, vpn, notifications, done`. (A instalação do perfil e o pedido de notificação acontecem no passo certo, não logo de cara.) |
| **Instalação do perfil de VPN local** | Free | Instala a config de VPN local durante a integração **sem** habilitar o Connect-On-Demand, para que a proteção nunca fique silenciosamente ativada ao concluir — a superfície do Guard continua sendo a autoridade. |
| **Pedido de permissão de notificação** | Free | Solicitado no fluxo, no passo de notificações. |
| **Padrões recomendados aplicados** | Free | Resolver Device DNS, fallback para device-DNS ativo, log local ativo (contagens + histórico + atividade), Block List Project Phishing + Scam habilitados, continuar sem conta (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Configurações

Superfícies de configuração, segurança, diagnóstico e feedback.

| Recurso | Nível | Observações |
|---|---|---|
| **Senha de desbloqueio do app + biometria** | Free | `SecurityController`: verificador de senha SHA256 com salt no Keychain + biometria `LAContext`, com uma sobreposição de bloqueio de desbloqueio do app e máscara de privacidade nas mudanças de fase de cena. |
| **Proteção por superfície** | Free | O `SecurityProtectedSurface` controla seis superfícies: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Cada uma pode exigir, de forma independente, autenticação local do dispositivo (por exemplo, a aba Configurações retorna `.requires(.appSettings)`). |
| **Seletor de aparência do Lava Guard (7 visuais)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, cada um com uma cor de glifo combinada na Dynamic Island. Escolhido em um seletor de rádio em folha inferior ("Escolha seu Guard", `LavaGuardLookPickerSheet`); visuais ainda bloqueados levam um glifo de cadeado e o painel de desbloqueio/upgrade fica na folha. |
| **Combinar com o ícone do app** | Free | Ícone alternativo opcional do app combinado com o visual de guardião selecionado. |
| **Aparência** | Free | Esquema de cores claro/escuro/sistema. |
| **Controles de log somente local** | Free | Alternadores para contagens de filtragem, histórico de domínios (diagnósticos) e atividade de rede — todos armazenados no dispositivo. Logs detalhados (histórico de domínios + atividade de rede) são podados para uma janela de **7 dias** (`LocalLogRetention.fineGrainedDays = 7`); contagens e o progresso do Lava Guard são mantidos por mais tempo. |
| **Logs de Atividade / Domínios (detalhe do Guard)** | Free | Diagnósticos dinâmicos somente locais, acessados pela aba Guard (`GuardDestination.activity`). O resumo é um **fluxo** de requisições — um total de "requisições processadas" dividido em uma barra de volume Permitido/Bloqueado com "% protegido localmente" (arredondamento honesto: uma fatia minúscula aparece como `<1%`, uma fatia quase total aparece como `>99%`). Uma seção de **Logs de Domínios** contém **Principais Domínios** (mais bloqueados e permitidos, classificados por contagem de consultas) e **Histórico de Domínios** (consultas e decisões recentes); as linhas de domínio aparecem só quando a participação no histórico está ativada. |
| **Filtro (detalhe do Guard)** | Free | Tela de filtro única e unificada, acessada pela aba Guard. Um hub "Meu filtro" abre uma única tela consolidada de **Meu filtro** com duas prateleiras — **"A Lava bloqueia estes"** (blocklists + domínios bloqueados individualmente) e **"A Lava deixa estes passarem"** (exceções permitidas) — sob um mesmo fluxo de rascunho Editar/Salvar. Um diagrama de fluxo "Telefone → Lava → Internet" abre a aba, e abrir Meu filtro atualiza automaticamente o catálogo. |
| **Atividade de Rede (Configurações → Avançado)** | Free | Fluxo de eventos limitado e somente local de transições de rede/runtime/usuário, compartilhado via App Group (`NetworkActivityLog`). Movido da superfície de Atividade para **Configurações → Avançado** (depois de "Nerd Stats", `SettingsRoute.networkActivity`), atrás do bloqueio `.activityViewing`, com seu próprio painel de privacidade ("Fica neste iPhone", mantido por 7 dias). |
| **Relatório de bug** | Free | Assistente acionado pelo usuário que envia um pacote anonimizado para `POST /v1/bug-reports`; sem histórico de domínios na v1. O pacote agora também carrega a procedência do build (`appVersion`/`appBuild`/`sourceRevision`) e contadores de honestidade de conectividade. Também acessível por sacudir-para-reportar (`RageShakeDetector`). |
| **Gerenciamento de assinatura** | Plus | Para assinantes ativos, a tela de Upgrade mostra Gerenciar Assinatura (planos com renovação automática, via `AppStore.showManageSubscriptions`), Restaurar Compra e a data de expiração do direito; um desbloqueio vitalício não mostra a linha Gerenciar. |
| **Avisos legais + Versão** | Free | As Configurações exibem avisos legais de terceiros (veja [Avisos de terceiros](../legal/third-party-notices.md)) e uma página de versão/build. |

---

## Arquitetura do app (para orientação)

Três bundles compartilham um App Group `group.com.lavasec`, junto com uma pasta de fontes `lavasec-ios: Shared/` compilada dentro deles:

- **LavaSecApp** (`com.lavasec.app`) — shell do app em SwiftUI; neste build, a raiz é um `TabView` de duas abas (**Guard** + **Configurações**), com Filtro e Atividade acessados como telas de detalhe sob a aba Guard (a Atividade de Rede agora fica em Configurações → Avançado).
- **LavaSecTunnel** (`.tunnel`) — o motor de filtragem/resolução de DNS no dispositivo.
- **LavaSecWidget** (`.widget`) — a Live Activity do WidgetKit.
- **Shared/** — fontes entre alvos (não é um bundle): App Group, serviço de comando, mascote, atributos/intents da Live Activity.

O controle App ↔ extensão usa **mensagens de provedor** do `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), não notificações Darwin. As regras de filtro cruzam app → extensão como arquivos de snapshot do App Group (`filter-snapshot.json` / `.compact`).

---

## Docs relacionados

- Roadmap — recursos planejados e descartados (preço do Plus/posicionamento do StoreKit, port para Android, proteção em nível de URL, prontidão de Associated-Domain para passkey, mini-jogo easter-egg, lançamento open-source GPL-3.0 etc.) ficam no roadmap privado, não neste catálogo público.
- [Decisão de conformidade GPL somente por URL de origem](../legal/gpl-source-url-only-compliance-decision.md)
- [Ressalva sobre os termos dos dados de listas open-source](../legal/open-source-list-data-terms-carveout.md)
- [Avisos de terceiros](../legal/third-party-notices.md)
