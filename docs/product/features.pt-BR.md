---
last_reviewed: 2026-06-20
owner: product
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Catálogo de recursos

> Público: PM / engenharia. Este catálogo cobre apenas o conjunto de recursos **atual e implementado**. Qualquer coisa projetada, mas não construída, fica no roadmap privado, não aqui.

Lava Security é um app iOS com foco em privacidade que filtra DNS **localmente no dispositivo** por meio de um packet tunnel da NetworkExtension, bloqueando domínios maliciosos e indesejados para usuários não técnicos (pais, idosos). A proteção essencial é gratuita para sempre e não exige conta.

A promessa de privacidade por trás de cada recurso abaixo:

> Toda a filtragem de DNS acontece no dispositivo; o Lava nunca roteia sua navegação pelos próprios servidores e nunca recebe o fluxo de domínios que você visita — o backend mantém apenas metadados do catálogo, um backup criptografado opaco por usuário e diagnósticos anonimizados que você escolhe enviar.

## Como ler este catálogo

- **Free** — disponível para todos, sem conta, sem compra.
- **Plus** — desbloqueado pelo Lava Security Plus, o único nível pago opcional. O Plus desbloqueia **apenas a personalização**; ele nunca restringe a segurança básica e nunca permite que um usuário pagante contorne a barreira de proteção contra ameaças.
- Toda linha está **Implementado** salvo indicação em linha. Legenda de status: **Implementado** = lançado e confirmado no código; **Planejado** = projetado, não construído; **Descartado** = rejeitado ou revertido. Itens Planejados/Descartados estão documentados no roadmap privado, não aqui.

Os limites de nível que servem como fonte da verdade ficam em `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift` (`FeatureLimits.free` / `FeatureLimits.paid`, com alias `.plus`). A **barreira** de habilitação do Plus é uma flag local (`isPaid`) — a fonte da verdade. O backend **espelha** as habilitações da App Store (`POST /v1/account/entitlements/app-store-sync` faz upsert de uma linha `entitlements`), mas essa linha é um espelho, não a barreira; nenhuma sincronização de backend controla a restrição ainda.

---

## 1. Proteção e VPN

O produto central: um packet tunnel local somente-DNS e o modelo de estado tranquilo ao redor dele.

| Recurso | Nível | Notas |
|---|---|---|
| **Packet tunnel local somente-DNS** | Free | `LavaSecTunnel` (`NEPacketTunnelProvider`, `com.lavasec.app.tunnel`) intercepta o DNS e avalia cada domínio no dispositivo. Nenhum tráfego de navegação é roteado pelo Lava. Endereço do tunnel `10.255.0.2`, servidor DNS `10.255.0.1`. |
| **Precedência da decisão de filtragem** | Free | `bloqueio da barreira de ameaças > allowlist local (exceções permitidas) > blocklist > permitir-por-padrão`; domínios inválidos são bloqueados. (`FilterSnapshot.decision()`.) |
| **Precedência de consulta (bootstrap primeiro)** | Free | `resolver-bootstrap > temporary-pause > filter` — o próprio hostname do resolver nunca é bloqueado. (`DNSQueryDispatcher`.) |
| **Início a frio fail-closed** | Free | Um tunnel a frio sem snapshot reutilizável instala um `FailClosedRuntimeSnapshot` que bloqueia todo o tráfego em vez de vazar DNS não filtrado. |
| **Connect-On-Demand** | Free | `NEOnDemandRuleConnect` mantém a proteção ativa / reinicia-a automaticamente — habilitado **somente após** uma conexão confirmada, nunca na instalação do perfil, e neutralizado durante um onboarding incompleto para que uma instalação nova não consiga ativar um tunnel impossível de desligar. |
| **Pausa temporária (configurável 1–30 min, padrão 5) + retomar** | Free | Pausar e retomar passam pelo `LavaProtectionCommandService` sob um flock file lock com dedup de revisão. |
| **Pausa com autenticação obrigatória** | Free | Barreira opcional por superfície (`SecurityProtectedSurface.protectionPause`): pausar exige autenticação local do dispositivo; o command service nega uma pausa não autenticada e a Live Activity oculta os botões de pausa. |
| **Reconectar** | Free | Reinicia o tunnel diretamente (contorna o pipeline de pausa do command service). |
| **Modelo de estado Soft Shield Guardian** | Free | 7 estados de expressão — `sleeping, waking, awake, paused, retrying, concerned, grateful` (`GuardianMascotAnimation.swift`, LavaSecCore). 6 severidades de conectividade se reduzem a 4 faces; renderizadas de forma idêntica no app, no onboarding e na Live Activity. |
| **Avaliação de conectividade** | Free | 6 severidades (`healthy, recovering, usingDeviceDNSFallback, dnsSlow, networkUnavailable, needsReconnect`) controlam a face do guardian e o texto de status. |
| **Endurecimento de desempenho** | Free | Ativação cache-first, coalescência de consultas em andamento, busca paralela limitada e coalescência de oscilações (ativação a quente medida em ~112 ms no iPhone 15 Pro conforme o trabalho de aceleração modular). |

> **Barreira do dispositivo (para todos, nunca um paywall):** um teto rígido de `~3,26M de regras` (alvo de 32 MB residentes sob o teto de memória por extensão do iOS de `~50 MiB`) é imposto para todos os usuários acima de qualquer nível (`lavasec-ios: Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift`, `maxFilterRuleCount`). Configurações acima do orçamento são rejeitadas de forma determinística (`exceedsDeviceMemoryBudget`) em vez de deixar o tunnel sofrer jetsam.

---

## 2. Blocklists e filtragem

O que é bloqueado, como as listas são escolhidas e a fronteira entre níveis.

| Recurso | Nível | Notas |
|---|---|---|
| **Blocklists somente source-url** | Free | O Lava publica apenas a URL upstream + os hashes aceitos; o dispositivo busca/processa os **bytes** da lista por conta própria. O Lava **nunca** armazena, espelha, transforma ou serve bytes de blocklists de terceiros. Veja a [decisão de conformidade source-url-only com a GPL](../legal/gpl-source-url-only-compliance-decision.md). |
| **Catálogo curado (categorizado)** | Free para habilitar | Fontes curadas organizadas em categorias de defesa em profundidade — Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling, Piracy & Torrent — de HaGeZi, The Block List Project, OISD, StevenBlack, AdGuard, 1Hosts e Phishing.Database. O conjunto completo e atual está publicado no [Catálogo de Blocklists](../legal/blocklist-catalog.md); cada plataforma reflete a versão do catálogo com que foi lançada. |
| **Blocklists padrão gratuitas** | Free | Uma instalação nova habilita o **Block List Basic** — uma lista combinada ampla e permissiva (a fonte marcada com `defaultEnabled: true`; `DefaultCatalog.recommendedDefaultSourceIDs`). Todo o resto é opt-in. |
| **Parse / normalização / dedup no dispositivo** | Free | `BlocklistParser` suporta auto/plain/hosts/adblock/dnsmasq, descarta comentários/linhas em branco/inválidos, faz dedup de strings exatas, limita a 1.000.000 de regras por lista. Uma linha `hosts` com vários hosts agora emite **todos** os hosts da linha, não apenas o primeiro (regras do parser versão 2). |
| **Integridade upstream (TLS + URL curada)** | Free | Os bytes das listas da comunidade são buscados por TLS diretamente do `source_url` upstream curado e aceitos sujeitos a limites de tamanho + formato + contagem de regras; os `accepted_source_hashes` do catálogo são **consultivos** (identidade de cache + auditoria), não uma barreira rígida — uma lista que rotaciona rápido nunca é rejeitada por divergir de um hash fixado. O nível de **barreira de ameaças** do Lava (curado pelo Lava, não pode ser permitido) permanece estritamente fixado por hash. |
| **Filtro de domínios protegidos** | Free | Toda fonte processada tem removidos os domínios protegidos do Lava / Apple / provedor de identidade (apple.com, icloud.com, lavasecurity.app, google.com, accounts.google.com, …) para que uma lista upstream não possa quebrar o app, o tunnel ou o login. |
| **Exceções permitidas (allowlist)** | Free | Allowlist gerenciada pelo usuário que permite domínios apesar das blocklists. Limite Free: 25 domínios permitidos / 25 bloqueados (`FeatureLimits.free`). |
| **Orçamento de regras de filtro (métrica de nível)** | Free / Plus | A métrica de nível lançada é o total de **regras** de domínio compiladas: **Free 500K / Plus 2M** (`maxFilterRules` em `lavasec-ios: Sources/LavaSecCore/SubscriptionPolicy.swift`). Substitui o antigo limite de contagem de listas. Configurações acima do nível surgem como `exceedsTierFilterRuleLimit`. |
| **Limites de domínios maiores** | Plus | 1.000 permitidos / 1.000 bloqueados (`FeatureLimits.plus`). |
| **Blocklists personalizadas** | Plus | `allowsCustomBlocklists`. Listas personalizadas são buscadas e processadas no dispositivo, armazenadas localmente em cache, nunca intermediadas pelos servidores do Lava. |
| **Reuso de artefato de inicialização a quente** | Free | Um manifest + impressão digital de identidade permite que o tunnel reutilize o snapshot compacto em disco sem recompilar; o reuso é rejeitado (com um motivo seguro para privacidade, apenas o nome do campo) quando as entradas mudam. |
| **Smart Save (confirmação só para enfraquecimento)** | Free | Edições no seu Filtro que apenas *fortalecem* ou são neutras (adicionar uma blocklist ou um domínio bloqueado) aplicam-se diretamente; edições que *enfraquecem* a proteção — remover uma blocklist, remover um domínio bloqueado ou adicionar uma exceção permitida — passam primeiro por uma folha de confirmação de revisão, com um painel "Tenha cuidado extra" quando exceções são adicionadas (`FiltersView.saveChanges()`, `weakensProtection`). |
| **Medidor de orçamento (seleção salvável)** | Free / Plus | O medidor de seleção abrevia contagens (500K / 1.2M / 2M) e usa uma margem de teto suave de 1,10 (a soma por lista superestima a união deduplicada em ~7–10%); uma contagem ainda dentro da tolerância é fixada para ler, por exemplo, "500K de 500K" até ultrapassar o teto suave (`FilterRuleBudget`). |

> A imposição autoritativa do orçamento roda em tempo de compilação sobre a união deduplicada (`FilterSnapshotPreparationService`); o limite do dispositivo é verificado primeiro, depois o limite do nível. O medidor de UI em tempo de seleção usa uma soma por lista com uma margem de teto suave de 1,10.

---

## 3. DNS criptografado

Transportes de resolver e roteamento para consultas não bloqueadas.

| Recurso | Nível | Notas |
|---|---|---|
| **Cinco transportes de resolver** | Free | `device-dns, plain-dns (IP), dns-over-https, dns-over-tls, dns-over-quic` (`DNSResolverTransport`). |
| **DoH / DoH3** | Free | DoH baseado em URLSession que prefere HTTP/3. A UI anota **`DoH3` (sem barra)**, por exemplo "Quad9 (DoH3)", **somente quando uma negociação h3 é de fato observada** — preferido, nunca prometido (`DoHTransport`). |
| **DoT** | Free | `NWConnection`s em pool (até 4/endpoint) com atualização por inatividade e uma tentativa de reconexão nova. |
| **DoQ** (apenas personalizado) | Plus | DNS-over-QUIC **não tem preset embutido** — só é acessível via um **resolver `doq://` personalizado**, e DNS personalizado é Plus. Abre uma **conexão QUIC nova por consulta** (o pool de 4 lanes dá concorrência, não reuso de handshake); o reuso de conexão foi adiado para um piso de implantação iOS-26. |
| **Resolvers preset** | Free | Device DNS (padrão), Google Public DNS, Cloudflare 1.1.1.1, Quad9 Secure, Mullvad — em variantes IP / DoH / DoT onde oferecidas (`DNSResolverPreset.allPresets`). |
| **Roteamento e failover de resolver** | Free | `ResolverOrchestrator` roteia por transporte, degrada para plain DNS quando um plano criptografado não tem endpoints, faz failover por endpoint com uma barreira de backoff, depois fallback para device-DNS. |
| **Fallback para device-DNS** | Free | Recorre ao resolver da rede atual quando o resolver selecionado está indisponível; **ativado por padrão**. Surge como a severidade `usingDeviceDNSFallback`. |
| **DNS personalizado** | Plus | `allowsCustomDNS` — resolver fornecido pelo usuário (incluindo parsing de DNS-stamp para presets personalizados). |

---

## 4. Contas e backup zero-knowledge

Login de conta opcional e backup criptografado de configurações. Nada disso é necessário para usar a proteção.

| Recurso | Nível | Notas |
|---|---|---|
| **Login de conta opcional (Apple + Google)** | Free | Fluxo nativo de id_token trocado no Supabase Auth (`grant_type=id_token`) com um nonce em hash; apenas a sessão Supabase resultante é armazenada localmente no dispositivo, no Keychain. Login por e-mail/senha não é oferecido intencionalmente (Descartado). |
| **Backup criptografado zero-knowledge** | Free | Envelope AES-256-GCM do lado do cliente; a chave aleatória do payload é embrulhada em key slots PBKDF2-HMAC-SHA256 (210k iterações). Apenas ciphertext + metadados não secretos são enviados ao `user_backups` do Supabase (RLS por usuário). O servidor não consegue descriptografar sem um segredo mantido pelo usuário. |
| **Payload de backup minimizado** | Free | Faz backup dos IDs de blocklists habilitadas, domínios permitidos/bloqueados, configurações de resolver, preferências de log local, aparência do guardian, etc. — e exclui explicitamente `isPaid`, flags de QA, diagnósticos, snapshots e bytes completos de blocklists. |
| **Key slot de segredo do dispositivo** | Free | Um segredo de dispositivo de 32 bytes no Keychain somente-do-dispositivo (`...ThisDeviceOnly`, não sincronizado com iCloud) para restauração transparente no mesmo dispositivo. |
| **Frase de recuperação + recuperação assistida** | Free | Uma frase CVCV de 8 palavras (~105 bits) combinada com uma parte de recuperação mantida no servidor via SHA256 para desbloquear o slot de recuperação assistida. Two-factor: nenhuma metade sozinha descriptografa. |
| **Key slot de recuperação por passkey** | Free | Slot opcional protegido por WebAuthn, e **zero-knowledge**: sua chave de unwrap é derivada **no dispositivo** a partir da saída WebAuthn PRF (`hmac-secret`) do autenticador (HKDF-SHA256). O servidor não registra nenhuma passkey, não emite desafios, não mantém nenhum segredo de recuperação e não expõe nenhuma rota de passkey — o projeto anterior de escrow no servidor foi descartado. A prontidão para produção em dispositivos físicos depende de Associated Domains / hospedagem AASA (Planejado). |
| **Exclusão de conta / direitos sobre os dados** | Free | Um endpoint Worker autenticado exclui backups, configurações, habilitações, perfil e anexos de relatórios de bug, depois o usuário do Supabase Auth; o app faz logout e limpa o material de desbloqueio local. |

---

## 5. Widget e Live Activity

Presença na tela de bloqueio e na Dynamic Island.

| Recurso | Nível | Notas |
|---|---|---|
| **Live Activity** | Free | `LavaSecWidget` (`com.lavasec.app.widget`): uma única `Activity<LavaActivityAttributes>` na tela de bloqueio e na Dynamic Island (center expandido / guardian compactLeading / compactTrailing + glifo de status minimal). |
| **Exibição de proteção com 5 estados** | Free | `ProtectionState`: `on, paused, reconnecting, needsReconnect, networkUnavailable` — cada um mapeia para uma pose do guardian, um SF Symbol e um título. |
| **Botões de ação da Live Activity** | Free | Pausar por N min (duração configurada, padrão 5), Retomar, Reconectar — `LiveActivityIntent`s que rodam no processo do app via `LavaProtectionCommandService`. As variantes de pausa autenticada exigem autenticação local do dispositivo. |
| **Reconciliação única deduplicada e barrada por revisão** | Free | `LavaLiveActivityController` mantém uma Activity, atualiza apenas em mudança real de id/conteúdo e barra atualizações pela revisão do `ProtectionPauseStore` para que retentativas de intent obsoletas não revertam o estado. |
| **Alternância de Live Activities** | Free | Alternável pelo usuário nas Configurações (`setUsesLiveActivities`), disponível apenas em iPhone/iPad. |

---

## 6. Onboarding

Fluxo de primeira execução que instala a configuração de VPN local e define padrões sensatos.

| Recurso | Nível | Notas |
|---|---|---|
| **Fluxo de primeira execução com várias páginas** | Free | `OnboardingFlowView` — 6 páginas: `lava, guardIntro, features, vpn, notifications, done`. (A instalação do perfil e o prompt de notificação acontecem no passo certo, não logo de cara.) |
| **Instalação do perfil de VPN local** | Free | Instala a configuração de VPN local durante o onboarding **sem** habilitar o Connect-On-Demand, para que a proteção nunca fique silenciosamente auto-ativada ao concluir — a superfície do Guard permanece autoritativa. |
| **Prompt de permissão de notificações** | Free | Solicitado no fluxo, no passo de notificações. |
| **Padrões recomendados aplicados** | Free | Resolver Device DNS, fallback para device-DNS ativado, logging local ativado (contagens + histórico + atividade), Block List Basic habilitado, continuar sem conta (`lavasec-ios: Sources/LavaSecCore/AppConfiguration.swift`, `lavaRecommendedDefaults`). |

---

## 7. Configurações

Superfícies de configuração, segurança, diagnóstico e feedback.

| Recurso | Nível | Notas |
|---|---|---|
| **Senha de desbloqueio do app + biometria** | Free | `SecurityController`: verificador de senha SHA256 com salt no Keychain + biometria `LAContext`, com uma sobreposição de bloqueio no desbloqueio do app e máscara de privacidade nas mudanças de scene-phase. |
| **Proteção por superfície** | Free | `SecurityProtectedSurface` barra seis superfícies: `appUnlock, protectionControl, protectionPause, filterEditing, activityViewing, appSettings`. Cada uma pode exigir independentemente autenticação local do dispositivo (por exemplo, a aba de Configurações retorna `.requires(.appSettings)`). |
| **Seletor de aparência do Lava Guard (7 aparências)** | Free | `GuardianShieldStyle`: `original, fireOpal, purpleObsidian, obsidian, cherryQuartz, emerald, kiwiCreme`, cada uma com uma cor de glifo de Dynamic Island pareada. Escolhido em um seletor de rádio em bottom-sheet ("Escolha seu Guard", `LavaGuardLookPickerSheet`); aparências ainda bloqueadas carregam um glifo de cadeado e o painel de desbloqueio/upgrade fica na folha. |
| **Combinar com o ícone do app** | Free | Ícone de app alternativo opcional pareado à aparência do guardian selecionada. |
| **Aparência** | Free | Esquema de cores claro/escuro/sistema. |
| **Controles de logging somente local** | Free | Alternâncias para contagens de filtragem, histórico de domínios (diagnósticos) e atividade de rede — todos armazenados no dispositivo. Logs granulares (histórico de domínios + atividade de rede) são podados para uma janela de **7 dias** (`LocalLogRetention.fineGrainedDays = 7`); contagens e progresso do Lava Guard são mantidos por mais tempo. |
| **Logs de Atividade / Domínios (detalhe do Guard)** | Free | Diagnósticos dinâmicos somente locais, acessados pela aba Guard (`GuardDestination.activity`). O resumo é um **fluxo** de requisições — um total de "requisições processadas" dividido em uma barra de volume Permitido/Bloqueado com "% protegido localmente" (arredondamento honesto: uma fração mínima lê `<1%`, uma fração quase total lê `>99%`). Uma seção de **Logs de Domínios** contém **Top Domínios** (mais bloqueados e permitidos, classificados por contagem de consultas) e **Histórico de Domínios** (consultas e decisões recentes); as linhas de domínio aparecem apenas quando o opt-in de histórico está ativado. |
| **Filtro (detalhe do Guard)** | Free | Tela única e unificada de Filtro acessada pela aba Guard. Um hub "Meu filtro" abre uma tela **Meu filtro** consolidada com duas prateleiras — **"O Lava bloqueia estes"** (blocklists + domínios bloqueados individualmente) e **"O Lava deixa estes passar"** (exceções permitidas) — sob um único fluxo de rascunho Editar/Salvar. Um diagrama de fluxo "Telefone → Lava → Internet" encabeça a aba, e abrir Meu filtro atualiza o catálogo automaticamente. |
| **Atividade de Rede (Configurações → Avançado)** | Free | Fluxo de eventos limitado e somente local de transições de rede/runtime/usuário, compartilhado via App Group (`NetworkActivityLog`). Movido da superfície de Atividade para **Configurações → Avançado** (depois de "Nerd Stats", `SettingsRoute.networkActivity`), atrás da barreira `.activityViewing`, com seu próprio painel de privacidade ("Permanece neste iPhone", mantido por 7 dias). |
| **Relatório de bug** | Free | Assistente acionado pelo usuário que envia um pacote anonimizado para `POST /v1/bug-reports`; sem histórico de domínios na v1. O pacote agora também carrega proveniência de build (`appVersion`/`appBuild`/`sourceRevision`) e contadores de honestidade de conectividade. Também acessível por shake-to-report (`RageShakeDetector`). |
| **Gerenciamento de assinatura** | Plus | Para assinantes ativos, a tela de Upgrade mostra Gerenciar Assinatura (planos renováveis automaticamente, via `AppStore.showManageSubscriptions`), Restaurar Compra e a data de expiração da habilitação. |
| **Avisos Legais + Versão** | Free | As Configurações exibem avisos legais de terceiros (veja [Avisos de terceiros](../legal/third-party-notices.md)) e uma página de versão/build. |

---

## Arquitetura do app (para orientação)

Três bundles compartilham um App Group `group.com.lavasec`, ao lado de uma pasta de fontes `lavasec-ios: Shared/` compilada para dentro deles:

- **LavaSecApp** (`com.lavasec.app`) — shell do app em SwiftUI; neste build a raiz é uma `TabView` de duas abas (**Guard** + **Configurações**), com Filtro e Atividade acessados como telas de detalhe sob a aba Guard (Atividade de Rede agora fica em Configurações → Avançado).
- **LavaSecTunnel** (`.tunnel`) — o motor de filtragem/resolução de DNS no dispositivo.
- **LavaSecWidget** (`.widget`) — a Live Activity do WidgetKit.
- **Shared/** — fontes cross-target (não um bundle): App Group, command service, mascote, atributos/intents da Live Activity.

O controle App ↔ extensão usa **provider messages** de `NETunnelProviderSession` (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`), não notificações Darwin. As regras de filtro cruzam app → extensão como arquivos de snapshot do App Group (`filter-snapshot.json` / `.compact`).

---

## Docs relacionados

- Roadmap — recursos planejados e descartados (precificação do Plus/posicionamento de StoreKit, port para Android, proteção em nível de URL, prontidão de Associated-Domain para passkey, mini-jogo easter-egg, lançamento open-source GPL-3.0, etc.) ficam no roadmap privado, não neste catálogo público.
- [Decisão de conformidade source-url-only com a GPL](../legal/gpl-source-url-only-compliance-decision.md)
- [Carve-out de termos de dados de listas open-source](../legal/open-source-list-data-terms-carveout.md)
- [Avisos de terceiros](../legal/third-party-notices.md)
