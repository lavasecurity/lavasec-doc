---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Principais decisões de design

> Público: equipe de engenharia e liderança. Este é o registro no estilo ADR das decisões de design estruturantes por trás do Lava Security — aquelas que moldaram a arquitetura, a promessa de privacidade ou os limites do produto, e especialmente as que foram testadas e revertidas. Cada entrada apresenta a **Decisão**, seu **Contexto**, a **Justificativa** e um **Status** retirado da legenda de status do projeto (Adotada / Revertida / Substituída / Proposta).
>
> **O código é a referência.** Quando um plano e o código publicado divergem, este registro segue o código e aponta a divergência no próprio texto.

**Legenda de status (mapeada às faixas de status do conjunto de documentos):**

| Status aqui | Significado na faixa do conjunto de documentos |
|---|---|
| **Adotada** | Implementada — publicada e confirmada no código |
| **Revertida** | Descartada — construída e depois removida/revertida |
| **Substituída** | Uma decisão anterior trocada por outra posterior |
| **Proposta** | Planejada — projetada, recomendada ou registrada, mas ainda não aplicada nesta árvore |

Leitura relacionada: modelo de distribuição do catálogo em [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) e [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); comportamento publicado em [`../product/features.md`](../product/features.md). A direção de longo prazo fica no roadmap interno.

---

## 1. Filtragem de DNS no dispositivo via `NEPacketTunnelProvider`

**Decisão.** Filtrar o DNS **localmente no dispositivo** por meio de um túnel de pacotes `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), em vez de `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` ou um bloqueador de conteúdo do Safari.

**Contexto.** O produto é um filtro com foco em privacidade para pessoas sem perfil técnico (pais, mães, pessoas idosas), distribuído pela App Store de consumo, sem exigir conta. Os outros provedores de NetworkExtension e as APIs de DNS gerenciado são restritos a dispositivos supervisionados/gerenciados por MDM ou não cobrem todo o DNS de um app, e um modelo do lado do resolvedor levaria o fluxo de domínios da pessoa para fora do dispositivo.

**Justificativa.** O túnel de pacotes é o único provedor que (a) funciona em dispositivos de consumo não gerenciados e (b) permite que toda decisão de DNS aconteça no dispositivo, o que é a base da promessa de privacidade: *toda a filtragem de DNS acontece no dispositivo; o Lava nunca roteia sua navegação pelos seus servidores e nunca recebe o fluxo de domínios que você visita.* A contrapartida aceita em troca é o **teto de memória de ~50 MiB por extensão** do iOS, sob o qual o túnel precisa operar — uma restrição que molda várias decisões posteriores abaixo.

**Status.** **Adotada** (estrutural; presente no código desde o protótipo inicial).

---

## 2. Distribuição da blocklist apenas por source-url

**Decisão.** O Lava publica apenas a **URL da blocklist de origem mais os hashes aceitos**; o dispositivo busca os **bytes** da lista diretamente em cada `source_url` e então processa, normaliza, remove duplicatas e filtra localmente. O Lava **nunca** armazena, espelha, transforma ou serve os bytes de blocklists de terceiros. O Worker grava no R2 apenas os **metadados** do catálogo em JSON (`raw_r2_key`/`normalized_r2_key` são nulos).

**Contexto.** O design anterior espelhava os bytes brutos da blocklist no R2 para que a área jurídica pudesse revisar a distribuição. Muitas listas de origem (HaGeZi, OISD) são GPL-3.0, então hospedar seus bytes faria do Lava um redistribuidor de dados GPL.

**Justificativa.** Tratar o Lava como um mecanismo de filtragem local / agente do usuário — em vez de um distribuidor de blocklists — reduz ao mínimo a exposição a redistribuição sob GPLv3 e à revisão da App Store. O dispositivo valida os bytes baixados contra os `accepted_source_hashes` do catálogo e, em caso de divergência, recorre ao último cache válido ou falha de forma fechada, recuperando a propriedade de segurança que o pipeline de espelhamento oferecia. Cada conjunto de regras processado também passa por um filtro de domínios protegidos, para que uma lista de origem não consiga bloquear domínios do Lava/da Apple/do provedor de identidade. O modelo é garantido na CI por `check-gpl-blocklist-distribution.sh` (sem código de espelhamento, sem URLs de artefatos hospedados pelo Lava, sem fontes GPL ativadas por padrão, sem gravação de bytes no R2).

**Status.** **Adotada**, e **Substituiu** o plano abandonado de espelhamento bruto no R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, cabeçalho "Superseded by the source-url-only implementation"). Veja [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Transportes de resolvedor criptografados (DoH / DoH3 / DoT / DoQ)

**Decisão.** Disponibilizar quatro transportes de saída criptografados ao lado do DNS comum e de um fallback para o DNS do dispositivo, extraídos para o LavaSecCore: **DoH** (URLSession), **DoH3** (DoH preferindo HTTP/3), **DoT** (`NWConnection`s em pool, até 4 por endpoint, com atualização por inatividade e uma tentativa com conexão nova) e **DoQ** (DNS-over-QUIC). Roteamento, degradação para DNS comum, failover por endpoint com um gate de backoff e o fallback para o DNS do dispositivo ficam no `ResolverOrchestrator`.

**Contexto.** Encaminhar consultas não bloqueadas em texto puro para um resolvedor vaza justamente o fluxo de domínios que o modelo no dispositivo deveria proteger. Os transportes foram construídos de forma incremental (DoH → DoH3 → DoT → DoQ).

**Justificativa.** O transporte de saída criptografado mantém as consultas não bloqueadas privadas de ponta a ponta. O **DoH3** é rotulado de forma puramente observacional — `assumesHTTP3Capable=true` é definido e o protocolo negociado é observado, e a interface anota `DoH3` (sem barra) **apenas quando uma negociação h3 é de fato observada**, nunca como promessa, porque o h3 é best-effort por conexão e uma afirmação fixa exageraria o comportamento atrás de firewalls que bloqueiam UDP. O pool de DoT com atualização por inatividade foi uma correção direta para o fechamento silencioso, pela Cloudflare, de conexões DoT ociosas.

**Status.** **Adotada** (os quatro transportes presentes e conectados).

---

## 4. Reuso de conexão DoQ — construído, testado em dispositivo, revertido

**Decisão.** **Não** reutilizar conexões QUIC para o DoQ. O `DoQTransport` abre uma **conexão QUIC nova por consulta**; o pool de 4 vias oferece concorrência, não reuso de handshake.

**Contexto.** O RFC 9250 mapeia cada consulta DNS para seu próprio stream QUIC, então o reuso real exige a API de múltiplos streams `NWConnectionGroup`/`openStream`, que é **exclusiva do iOS 26.0+**, enquanto o piso de implantação é o iOS 17. Ainda assim, um caminho de reuso restrito ao iOS 26 foi implementado (compilado em Debug+Release contra o SDK do Xcode 26) e **testado em dispositivo no iOS 26.5** contra o DoQ da AdGuard.

**Justificativa.** O caminho de reuso falhou em todas as tentativas no dispositivo (`openStream`/`receive` deram erro e, em seguida, o fallback caiu em "Socket is not connected"), medindo desempenho **líquido pior** do que o baseline por consulta (controle: 34 handshakes / 35 consultas, todas com sucesso). Isso confirmou empiricamente a orientação do Apple DTS de "segurar o uso de QUIC com o novo Network framework", então o trabalho foi revertido em vez de publicado; apenas a documentação e a justificativa dos testes de guarda preservam o achado, para que não seja tentado de novo antes de a API amadurecer.

**Status.** **Revertida** (adiada até o piso de implantação alcançar o iOS 26). Descreva o DoQ como conexões novas por consulta.

---

## 5. Recusar um protocolo unificador `DNSResolvingTransport`

**Decisão.** **Não** unificar os transportes de resolvedor sob um único protocolo `DNSResolvingTransport`; manter a costura baseada em closures `ResolverOrchestrator.Executors`.

**Contexto.** Uma refatoração (issue 407) propôs um único protocolo sobre todos os transportes.

**Justificativa.** Os transportes são dissimilares demais — executores criptografados assíncronos (DoH/DoT/DoQ) versus transportes síncronos de múltiplos endereços (comum/dispositivo) —, então um protocolo unificador seria uma abstração pior do que a costura de closures injetáveis já existente, que mantém a execução na rede testável.

**Status.** **Revertida** / não será implementada (encerrada como uma abstração ruim).

---

## 6. Backup criptografado de conhecimento zero (sem senha, com exceção de passkey registrada)

**Decisão.** Fazer backup de uma carga de configurações **minimizada** no lado do cliente: o AES-256-GCM a sela sob uma chave de carga aleatória de 32 bytes, que é encapsulada em **slots de chave** por segredo via PBKDF2-HMAC-SHA256 (**210.000** iterações em produção). Apenas o texto cifrado mais metadados não secretos sobem para a tabela `user_backups` do Supabase (RLS por usuário). O fluxo publicado é **sem senha**: slot de segredo do dispositivo (Keychain local do dispositivo) + slot de recuperação assistida + slot opcional de passkey.

**Contexto.** O login opcional em conta (apenas Apple + Google) permite restaurar as configurações entre dispositivos. O servidor nunca pode ser capaz de ler as blocklists, allowlists, escolha de resolvedor ou outras configurações de uma pessoa.

**Justificativa.** O texto puro e os segredos descriptografados existem apenas no dispositivo; o servidor guarda um único envelope opaco por usuário. A recuperação assistida é deliberadamente de dois fatores — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (entrada delimitada por NUL) exige **tanto** a parte guardada no servidor **quanto** a frase de recuperação de 8 palavras do usuário (~105 bits), de modo que nenhuma metade sozinha descriptografa. O material de desbloqueio é guardado localmente no dispositivo (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **não** no Keychain do iCloud sincronizável — um reforço de privacidade que reverteu o design sincronizável do plano original. O **slot de passkey também é genuinamente de conhecimento zero**: ele é encapsulado com uma saída de autenticador WebAuthn **PRF / `hmac-secret`** (derivada por HKDF-SHA256) que nunca sai do cliente, de modo que nenhum valor guardado no servidor consegue desencapsulá-lo. Não há tabela de passkey com service-role nem gate de asserção WebAuthn no Worker — o design anterior de passkey com gate no servidor foi descartado, removendo todo o estado de passkey do lado do servidor (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Status.** **Adotada** (modelo sem senha, recuperação assistida e um slot de passkey de conhecimento zero derivado de PRF, todos no código). Tornar a passkey um fator recuperável totalmente pronto para produção em dispositivos físicos (Associated Domains / hospedagem AASA para o modelo PRF) está **Proposto** (backlog).

---

## 7. Connect-On-Demand com falha fechada

**Decisão.** Adicionar uma regra `NEOnDemandRuleConnect` para que um túnel interrompido pelo sistema reinicie automaticamente, com **falha fechada** como padrão seguro: quando não há um snapshot de filtro reutilizável, o túnel bloqueia todo o tráfego em vez de deixá-lo passar sem filtragem. O on-demand é **desativado antes de qualquer parada** para que a VPN continue podendo ser desligada.

**Contexto.** O iOS estava parando o túnel silenciosamente (reason 17) sem nada reiniciá-lo por ~45 minutos, deixando as pessoas sem proteção. Ativar o on-demand de forma ingênua torna a VPN impossível de desligar, e um padrão de falha aberta deixaria o tráfego passar durante a lacuna.

**Justificativa.** O on-demand fecha a lacuna da parada silenciosa; desativar antes de parar preserva a capacidade da pessoa de desligar a proteção; a falha fechada garante que a lacuna seja segura em vez de ficar sem filtragem silenciosamente, recuperada por `reconcileTunnelSnapshotAfterLaunch`. A mudança teve efeitos colaterais — o on-demand voltou a disparar o aviso de sistema "Adicionar configurações de VPN" durante o onboarding —, o que gerou uma cadeia de correções em vários commits: parar de ativar o on-demand na instalação, condicionar a restauração de inicialização/proteção à conclusão do onboarding e **neutralizar uma configuração herdada/órfã removendo-a** (`removeFromPreferences`, silencioso) em vez de salvar `on-demand=false` (`saveToPreferences` reexibia o aviso).

**Status.** **Adotada** (reinício do on-demand mais a cadeia de correções de onboarding/falha fechada).

---

## 8. Refatoração modular da VPN e a disciplina de regressão de calor

**Decisão.** Reestruturar o caminho da VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) para ativação que prioriza cache, busca com paralelismo limitado e coalescência de oscilações — tratando bateria/latência como requisitos de produto com metas explícitas de p50/p95 e profiling **no dispositivo** (não no Simulador).

**Contexto.** Ativar / atualizar / pausar / retomar estavam lentos. Durante a refatoração surgiu uma regressão de calor (134% de CPU, energia Alta, telefone quente). Um painel amplo de agentes primeiro refutou a causa suspeita usando evidências anteriores à regressão; uma captura ao vivo no dispositivo então a confirmou.

**Justificativa.** A causa real era um loop de atualização autossustentado em `NEVPNStatusDidChange` — um loop de coalescência que se rearmava indefinidamente (~370 eventos/s, thread principal ~100%, `vpn-debug-log.jsonl` crescido para ~180–210 MB) depois que uma guarda de descarte por reentrância foi substituída. A correção lê o estado do gerenciador em cache e limita o loop. Os próprios registros de artefatos antes/depois do plano no dispositivo mostram a ativação a quente (`action.turnOn`) caindo de **2.722 ms → 287 ms** em um iPhone 15 Pro; uma revisão posterior, separada, de oportunidades pós-modular mediu o caminho a quente em **112 ms** (decode 51 + managerSetup 57) no mesmo dispositivo. O episódio definiu o padrão: refatorações estruturais pausam até que uma regressão de calor medida seja contida, e resultados térmicos/de bateria do Simulador são rejeitados como sem significado.

**Status.** **Adotada** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Uma revisão pós-modular mantém `PacketTunnelProvider` e `AppViewModel` como god-objects sobreviventes conhecidos.

---

## 9. Orçamento de regras de filtro em vez de um limite de contagem de listas

**Decisão.** Limitar os planos por um **orçamento de regras de filtro** — **Free 500K / Plus 2M** regras de domínio compiladas — e não pela contagem de listas ativadas. Um **limite rígido de proteção do dispositivo de ~3,26M de regras** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`) vale para **todo mundo** e **nunca é um paywall**. O blob compacto de domínios é mapeado com `mmap` (`.mappedIfSafe`), então permanece respaldado em arquivo e fora do `phys_footprint` contado pelo jetsam; apenas as tabelas de entradas decodificadas custam memória residente.

**Contexto.** O limite antigo era uma **contagem** de listas (3 no gratuito / 10 no pago). Uma lista pode conter 1K ou 1M de regras, então a contagem era um indicador enganoso do recurso realmente restrito — o teto de memória de 50 MiB da NE.

**Justificativa.** As regras correspondem à memória de fato, então qualquer combinação de listas que caiba é permitida. A aplicação autoritativa roda em tempo de compilação sobre a união deduplicada em `FilterSnapshotPreparationService` (primeiro o limite de proteção do dispositivo, depois o limite do plano); o medidor da interface no momento da seleção usa uma soma por lista com uma margem de teto suave de 1,10. Configurações acima do orçamento são rejeitadas de forma determinística (mantendo a proteção desligada) em vez de deixar o túnel sofrer jetsam.

**Status.** **Adotada** no código (`SubscriptionPolicy.swift`), publicada na **v1.0.0**, o que **Substituiu** o limite por contagem de listas. O orçamento de regras é agora o gate de plano ativo; os limites por domínio também foram elevados na 1.0 (Free 25 / Plus 1.000 domínios permitidos e bloqueados). Veja [`../product/features.md`](../product/features.md).

---

## 10. Planos como markdown + sincronização unidirecional com o Linear

**Decisão.** Arquivos markdown em `plans/<lane>/` são a **fonte da verdade**; a **pasta da faixa é o status autoritativo** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Um push para o `main` sincroniza os planos **de forma unidirecional** com o Linear (time LAV), atualizando apenas título/descrição após a criação; um trajeto de volta separado, **manual e revisado**, traz status/prioridade/faixa do Linear de volta ao frontmatter do plano.

**Contexto.** Uma equipe pequena precisa de um estado de planejamento agnóstico de ferramenta e revisável, que não brigue com um rastreador de projetos, e um loop de agente autônomo precisa de um lugar estável para ler e gravar o estado dos planos.

**Justificativa.** A divisão de propriedade de campos mantém os dois sistemas livres de conflito — o markdown é dono do conteúdo, o Linear é dono do estado de triagem —, então um push nunca sobrescreve a triagem feita por pessoas. A faixa `dropped/` mantém os planos cancelados fora do pipeline de sincronização para que não reapareçam (criada quando o Allowed Exceptions Guardrails / LAV-5 foi rejeitado). Frontmatter desatualizado dentro de um plano é um bug de documentação, não um status; a pasta prevalece, e onde o código mostra um recurso publicado apesar de um frontmatter "Backlog" (por exemplo, exclusão de conta), o código prevalece.

**Status.** **Adotada** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; faixa `dropped/` em uso).

---

## 11. Divisão de repositórios + código aberto copyleft do cliente

**Decisão.** Dividir o monorepo em repositórios por componente (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) e **abrir o código do cliente próprio sob AGPL-3.0** no lugar de Apache-2.0, com base no precedente copyleft da Mullvad/ProtonVPN.

**Contexto.** Desenvolvimento por componente e abertura do código do cliente. A questão da licença é se um concorrente poderia fazer um fork do cliente, fechá-lo e competir por preço.

**Justificativa.** O copyleft obriga os derivados a permanecerem abertos, impedindo um fork fechado do cliente — uma postura de "cliente público, backend/operações privados", com backend, jurídico e operações mantidos privados. A AGPL-3.0 (em vez da GPL-3.0 simples) foi escolhida para fechar a brecha de uso em rede. A conhecida tensão de distribuição entre GPL e App Store é resolvida pelo próprio Lava ser o distribuidor do binário da App Store sob seu próprio copyright.

**Status.** **Adotada.** A divisão de repositórios está **concluída**: cada componente vive em seu próprio repositório — o cliente público `lavasec-ios` na tag v0.4.0, além de repositórios separados para Android, o site de marketing, backend/infraestrutura, documentação e o pipeline de CI/release — e a seção "Repository layout" do `README.md` do `lavasec-ios` lista apenas o conteúdo por componente daquele repositório (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`), com a infraestrutura indicada como residente em repositórios privados separados. O cliente é de código aberto sob **AGPL-3.0**: o `LICENSE` do `lavasec-ios` é a GNU Affero General Public License v3 e o `README.md` exibe o selo AGPL-3.0.

---

## Apêndice — outras reversões e rejeições registradas

São menores, mas foram decisões genuínas com uma virada registrada; listadas para completude.

| Decisão | Justificativa | Status |
|---|---|---|
| DNS personalizado no gratuito vs pago | Posicionamento de monetização; permitido brevemente no gratuito e depois retornado a apenas pago | **Revertida** para apenas pago |
| Login com e-mail/senha | Ter senhas próprias adiciona o ônus de redefinição/MFA/bloqueio/vazamento/sequestro de conta, enquanto Apple + Google bastam; recuperação por bypass quebraria o conhecimento zero | **Revertida** / nunca publicada (apenas Apple + Google) |
| Allowed Exceptions Guardrails (LAV-5) | A precedência de proteção foi publicada via a revisão mais simples de edição da lista de filtros; o pagamento nunca pode burlar a proteção de ameaça de alta confiança | **Revertida** (faixa `dropped/` criada) |
| Bloqueio de promoção de branch no TestFlight | O bloqueio inicial foi reconsiderado; substituído por um bloqueio de runner planejado para depois da abertura do código | **Revertida**, substituída por um plano no backlog |
| Canal de controle app↔extensão | `sendProviderMessage` (`NETunnelProviderSession`) é o **único caminho de controle app→túnel** — ele carrega o estado tipado e versionado e comanda de forma autoritativa o run loop da extensão. O observador `CFNotificationCenter` anterior no lado da extensão nunca disparava de forma confiável no dispositivo e foi **removido** (ausência afirmada por testes de introspecção de fonte). As notificações Darwin sobrevivem apenas na direção **túnel→app**, como um aviso de mudança de saúde. | **Adotada** (a mensagem de provedor é o único controle app→túnel; o Darwin é apenas saúde túnel→app) |

> Invariante de segurança transversal referenciada ao longo do documento: o pagamento nunca burla a **proteção de ameaça** não dispensável e validada por hash. A precedência de decisão é **proteção de ameaça > allowlist local (exceções permitidas) > blocklist > permitir por padrão.**
