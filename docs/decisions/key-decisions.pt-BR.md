---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Principais Decisões de Design

> Público: engenheiros e liderança. Este é o registro em estilo ADR das decisões de design estruturais por trás da Lava Security — aquelas que moldaram a arquitetura, a promessa de privacidade ou o limite do produto, e especialmente as que foram tentadas e revertidas. Cada entrada apresenta a **Decisão**, seu **Contexto**, a **Justificativa** e um **Status** extraído da legenda de status do projeto (Adotada / Revertida / Substituída / Proposta).
>
> **O código prevalece.** Onde um plano e o código entregue divergem, este registro segue o código e aponta a divergência inline.

**Legenda de status (mapeada para as faixas de status do conjunto de documentos):**

| Status aqui | Significado da faixa do conjunto de documentos |
|---|---|
| **Adotada** | Implementada — entregue e confirmada no código |
| **Revertida** | Abandonada — construída e depois removida/revertida |
| **Substituída** | Uma decisão anterior substituída por uma posterior |
| **Proposta** | Planejada — projetada, recomendada ou registrada, mas ainda não aplicada nesta árvore |

Leitura relacionada: modelo de distribuição do catálogo em [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) e [`../legal/open-source-list-data-terms-carveout.md`](../legal/open-source-list-data-terms-carveout.md); comportamento entregue em [`../product/features.md`](../product/features.md). A direção de longo prazo está no roadmap interno.

---

## 1. Filtragem de DNS no dispositivo via `NEPacketTunnelProvider`

**Decisão.** Filtrar DNS **localmente no dispositivo** através de um packet tunnel `NEPacketTunnelProvider` (`LavaSecTunnel`, `com.lavasec.app.tunnel`), em vez de `NEDNSProxyProvider`, `NEFilterProvider`, `NEDNSSettingsManager` ou um bloqueador de conteúdo do Safari.

**Contexto.** O produto é um filtro com privacidade em primeiro lugar para usuários não técnicos (pais, idosos), distribuído pela App Store de consumo, sem necessidade de conta. Os provedores concorrentes do NetworkExtension e as APIs de DNS gerenciado são restritos a dispositivos supervisionados/gerenciados por MDM ou não cobrem todo o DNS de um aplicativo, e um modelo do lado do resolvedor encaminharia o fluxo de domínios do usuário para fora do dispositivo.

**Justificativa.** O packet tunnel é o único provedor que (a) funciona para dispositivos de consumo não gerenciados e (b) permite que cada decisão de DNS aconteça no dispositivo, o que é a base da promessa de privacidade: *toda a filtragem de DNS acontece no dispositivo; a Lava nunca roteia sua navegação pelos seus servidores e nunca recebe o fluxo de domínios que você visita.* A contrapartida aceita é o **teto de memória de ~50 MiB por extensão** do iOS sob o qual o tunnel deve operar — uma restrição que molda várias decisões posteriores abaixo.

**Status.** **Adotada** (fundacional; no código desde o protótipo inicial).

---

## 2. Distribuição de blocklist somente por source-url

**Decisão.** A Lava publica apenas a **URL** da blocklist upstream **mais os hashes aceitos**; o dispositivo busca os **bytes** da lista diretamente de cada `source_url`, depois faz o parse, normaliza, deduplica e filtra localmente. A Lava **nunca** armazena, espelha, transforma ou serve bytes de blocklists de terceiros. O Worker grava no R2 apenas o JSON de **metadados** do catálogo (`raw_r2_key`/`normalized_r2_key` são null).

**Contexto.** O design anterior espelhava os bytes brutos da blocklist no R2 para que o jurídico pudesse revisar a distribuição. Muitas listas upstream (HaGeZi, OISD) são GPL-3.0, então hospedar seus bytes tornaria a Lava uma redistribuidora de dados GPL.

**Justificativa.** Tratar a Lava como um motor de filtragem local / user agent — em vez de uma distribuidora de blocklist — minimiza a redistribuição sob GPLv3 e a exposição na App Review. O dispositivo busca cada lista por TLS diretamente de seu `source_url` curado e faz o parse localmente sob limites estritos de tamanho/regras; as listas da comunidade são aceitas conforme servidas (os `accepted_source_hashes` do catálogo são consultivos, não uma barreira rígida — um único hash fixado não consegue acompanhar um upstream que rotaciona rapidamente e só produzia rejeições falsas), enquanto o tier de barreira contra ameaças da Lava permanece com hash fixado. A proveniência é imposta no catálogo (uma mudança de `source_url` deve usar um novo `list_id`), não por uma barreira de hash no cliente. Cada conjunto de regras analisado também passa por um filtro de domínios protegidos para que uma lista upstream não possa bloquear domínios da Lava/Apple/provedor de identidade. O modelo é imposto na CI por `check-gpl-blocklist-distribution.sh` (sem código de espelhamento, sem URLs de artefatos hospedados pela Lava, sem fontes GPL habilitadas por padrão, sem gravações de bytes no R2).

**Status.** **Adotada**, e **Substituiu** o plano abandonado de espelhamento bruto no R2 (`plans/implemented/2026-05-25-gpl-raw-r2-blocklist-compliance-plan.md`, cabeçalho "Superseded by the source-url-only implementation"). Veja [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md).

---

## 3. Transportes de resolvedor criptografados (DoH / DoH3 / DoT / DoQ)

**Decisão.** Entregar quatro transportes upstream criptografados ao lado do DNS em texto puro e de um fallback de DNS do dispositivo, extraídos para o LavaSecCore: **DoH** (URLSession), **DoH3** (DoH preferindo HTTP/3), **DoT** (`NWConnection`s em pool, até 4/endpoint, com atualização por obsolescência de ociosidade e uma nova tentativa com conexão nova) e **DoQ** (DNS-over-QUIC). Roteamento, degradação para DNS em texto puro, failover por endpoint com uma barreira de backoff e fallback para o DNS do dispositivo ficam no `ResolverOrchestrator`.

**Contexto.** Encaminhar consultas não bloqueadas em texto claro para um resolvedor vaza justamente o fluxo de domínios que o modelo no dispositivo deve proteger. Os transportes foram construídos incrementalmente (DoH → DoH3 → DoT → DoQ).

**Justificativa.** O transporte upstream criptografado mantém as consultas não bloqueadas privadas de ponta a ponta. O **DoH3** é rotulado de forma puramente observacional — `assumesHTTP3Capable=true` é definido e o protocolo negociado é observado, e a interface anota `DoH3` (sem barra) **somente quando uma negociação h3 é realmente observada**, nunca prometida, porque h3 é best-effort por conexão e uma afirmação fixa exageraria o comportamento atrás de firewalls que bloqueiam UDP. O pooling de DoT com atualização de ociosidade foi uma correção direta para o Cloudflare fechar silenciosamente conexões DoT ociosas.

**Status.** **Adotada** (todos os quatro transportes presentes e conectados).

---

## 4. Reuso de conexão DoQ — construído, testado em dispositivo, revertido

**Decisão.** **Não** reutilizar conexões QUIC para DoQ. O `DoQTransport` abre uma **conexão QUIC nova por consulta**; o pool de 4 lanes provê concorrência, não reuso de handshake.

**Contexto.** A RFC 9250 mapeia cada consulta DNS para seu próprio stream QUIC, então o reuso verdadeiro precisa da API multi-stream `NWConnectionGroup`/`openStream`, que é **apenas iOS 26.0+**, enquanto o piso de implantação é o iOS 17. Um caminho de reuso restrito ao iOS 26 foi, ainda assim, implementado (compilado em Debug+Release contra o SDK do Xcode 26) e **testado em dispositivo no iOS 26.5** contra o DoQ da AdGuard.

**Justificativa.** O caminho de reuso falhou em todas as tentativas no dispositivo (`openStream`/`receive` deram erro, depois o fallback atingiu "Socket is not connected"), medindo **líquido pior** que a baseline por consulta (controle: 34 handshakes / 35 consultas, todas bem-sucedidas). Isso confirmou empiricamente a orientação da Apple DTS de "adiar o QUIC com o novo Network framework", então o trabalho foi revertido em vez de entregue; apenas os docs e a justificativa do teste de barreira retêm o achado para que não seja tentado novamente antes de a API amadurecer.

**Status.** **Revertida** (adiada até o piso de implantação alcançar o iOS 26). Descreva DoQ como conexões novas por consulta.

---

## 5. Rejeitar um protocolo unificador `DNSResolvingTransport`

**Decisão.** **Não** unificar os transportes do resolvedor sob um único protocolo `DNSResolvingTransport`; manter o seam baseado em closures `ResolverOrchestrator.Executors`.

**Contexto.** Uma refatoração (issue 407) propôs um protocolo único sobre todos os transportes.

**Justificativa.** Os transportes são dissimilares demais — executores criptografados assíncronos (DoH/DoT/DoQ) versus transportes síncronos multi-endereço em texto puro/do dispositivo — então um protocolo unificador seria uma abstração pior do que o seam injetável de closures existente, que já mantém a execução do protocolo testável.

**Status.** **Revertida** / não será implementada (encerrada como uma abstração ruim).

---

## 6. Backup criptografado de conhecimento zero (sem senha, exceção de passkey anotada)

**Decisão.** Fazer backup de um payload **minimizado** de configurações no lado do cliente: AES-256-GCM o sela sob uma chave de payload aleatória de 32 bytes, que é envolvida em **key slots** por segredo via PBKDF2-HMAC-SHA256 (**210.000** iterações em produção). Apenas o texto cifrado mais metadados não secretos são enviados para a tabela `user_backups` do Supabase (RLS por usuário). O fluxo entregue é **sem senha**: slot de segredo do dispositivo (Keychain local do dispositivo) + slot de recuperação assistida + slot opcional de passkey.

**Contexto.** O login de conta opcional (somente Apple + Google) habilita a restauração de configurações entre dispositivos. O servidor nunca deve conseguir ler as blocklists, allowlists, escolha de resolvedor ou outras configurações de um usuário.

**Justificativa.** O texto plano e os segredos de descriptografia existem apenas no dispositivo; o servidor mantém um envelope opaco por usuário. A recuperação assistida é deliberadamente de dois fatores — `SHA256("LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase)` (entrada delimitada por NUL) requer **ambos** o share mantido pelo servidor e a frase de recuperação de 8 palavras do usuário (~105 bits), de modo que nenhuma metade sozinha descriptografa. O material de desbloqueio é armazenado localmente no dispositivo (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), **não** no iCloud Keychain sincronizável — um endurecimento de privacidade que reverteu o design sincronizável do plano original. O **slot de passkey também é genuinamente de conhecimento zero**: ele é envolvido com uma saída de autenticador WebAuthn **PRF / `hmac-secret`** (derivada por HKDF-SHA256) que nunca deixa o cliente, de modo que nenhum valor mantido pelo servidor pode desfazê-lo. Não há tabela de passkey com service-role e nenhuma barreira de WebAuthn-assertion no Worker — o design anterior de passkey com barreira no servidor foi abandonado, removendo todo o estado de passkey do lado do servidor (`Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`).

**Status.** **Adotada** (modelo sem senha, recuperação assistida e um slot de passkey de conhecimento zero derivado de PRF, tudo no código). Tornar a passkey um fator recuperável totalmente pronto para produção em dispositivos físicos (Associated Domains / hospedagem AASA para o modelo PRF) é **Proposta** (backlog).

---

## 7. Connect-On-Demand fail-closed

**Decisão.** Adicionar uma regra `NEOnDemandRuleConnect` para que um tunnel parado pelo SO reinicie automaticamente, com **fail-closed** como o padrão seguro: quando não há snapshot de filtro reutilizável, o tunnel bloqueia todo o tráfego em vez de passá-lo sem filtragem. O on-demand é **desabilitado antes de qualquer parada** para que a VPN continue podendo ser desligada.

**Contexto.** O iOS estava parando o tunnel silenciosamente (motivo 17) sem nada o reiniciando por ~45 minutos, deixando os usuários desprotegidos. Habilitar o on-demand de forma ingênua torna a VPN impossível de desligar, e um padrão fail-open passaria tráfego durante a lacuna.

**Justificativa.** O on-demand fecha a lacuna de parada silenciosa; desabilitar antes de parar preserva a capacidade do usuário de desligar a proteção; o fail-closed garante que a lacuna seja segura em vez de silenciosamente sem filtragem, recuperada por `reconcileTunnelSnapshotAfterLaunch`. A mudança teve efeitos colaterais — o on-demand reacionou o prompt do sistema "Add VPN Configurations" durante o onboarding — o que gerou uma cadeia de correções em múltiplos commits: parar de habilitar o on-demand na instalação, condicionar a restauração de launch/proteção à conclusão do onboarding e **neutralizar uma config herdada/órfã removendo-a** (`removeFromPreferences`, silencioso) em vez de salvando `on-demand=false` (`saveToPreferences` reexibia o prompt).

**Status.** **Adotada** (reinício on-demand mais a cadeia de correções de onboarding/fail-closed).

---

## 8. Refatoração modular da VPN e a disciplina de regressão de calor

**Decisão.** Reestruturar o caminho da VPN (VPNLifecycleController, ProtectionActionOrchestrator, ResolverOrchestrator, FilterArtifactStore, DNSResponseCache, RuleSetCache, FilterSnapshotPreparationService) para turn-on com cache em primeiro lugar, fetch com paralelismo limitado e coalescência de flaps — tratando bateria/latência como requisitos de produto com metas explícitas p50/p95 e profiling **no dispositivo** (não no Simulador).

**Contexto.** Turn-on / refresh / pause / resume estavam lentos. Durante a refatoração surgiu uma regressão de calor (134% de CPU, energia Alta, telefone quente). Um grande painel de agentes primeiro refutou a causa suspeita usando evidências pré-regressão; uma captura ao vivo no dispositivo então a confirmou.

**Justificativa.** A causa real era um loop de refresh `NEVPNStatusDidChange` autossustentável — um loop de coalescência que se rearmava para sempre (~370 eventos/s, thread principal ~100%, `vpn-debug-log.jsonl` crescido para ~180–210 MB) depois que uma guarda drop-reentrant foi substituída. A correção lê o estado do manager em cache e limita o loop. O artefato de dispositivo antes/depois do próprio plano registra o turn-on quente (`action.turnOn`) caindo de **2.722 ms → 287 ms** no iPhone 15 Pro; uma revisão separada e posterior de oportunidades pós-modular mediu o caminho quente em **112 ms** (decode 51 + managerSetup 57) no mesmo dispositivo. O episódio estabeleceu o padrão: refatorações estruturais pausam até que uma regressão de calor medida seja limitada, e resultados térmicos/de bateria do Simulador são rejeitados como sem sentido.

**Status.** **Adotada** (`plans/implemented/2026-06-12-modular-speed-up-plan.md`). Uma revisão pós-modular mantém `PacketTunnelProvider` e `AppViewModel` como god-objects remanescentes conhecidos.

---

## 9. Orçamento de regras de filtro em vez de um limite de contagem de listas

**Decisão.** Limitar os tiers por um **orçamento de regras de filtro** — **Free 500K / Plus 2M** regras de domínio compiladas — não pela contagem de listas habilitadas. Uma **barreira rígida de dispositivo de ~3,26M de regras** (`maxResidentMegabytes 32.0`, `baselineMegabytes 4.0`, `estimatedBytesPerRule 9.0` → `maxFilterRuleCount = 3,262,236`) aplica-se a **todos** e **nunca é um paywall**. O blob compacto de domínios é mapeado via `mmap` (`.mappedIfSafe`) para que permaneça respaldado por arquivo e fora do `phys_footprint` contabilizado pelo jetsam; apenas as tabelas de entradas decodificadas custam memória residente.

**Contexto.** O limite antigo era uma **contagem** de listas (free 3 / pago 10). Uma lista pode conter 1K ou 1M de regras, então a contagem era um proxy desonesto para o recurso realmente restrito — o teto de memória de 50 MiB do NE.

**Justificativa.** As regras mapeiam para memória real, então qualquer combinação de listas que caiba é permitida. A imposição definitiva roda em tempo de compilação sobre a união deduplicada em `FilterSnapshotPreparationService` (barreira de dispositivo primeiro, depois o limite do tier); o medidor de interface em tempo de seleção usa uma soma por lista com uma margem de teto suave de 1.10. Configs acima do orçamento são rejeitadas deterministicamente (mantendo a proteção desligada) em vez de deixar o tunnel sofrer jetsam.

**Status.** **Adotada** no código (`SubscriptionPolicy.swift`), entregue na **v1.0.0**, que **Substituiu** o limite de contagem de listas. O orçamento de regras é agora a barreira de tier ativa; os limites por domínio também foram elevados na 1.0 (Free 25 / Plus 1.000 domínios permitidos e bloqueados). Veja [`../product/features.md`](../product/features.md).

---

## 10. Planos como markdown + sincronização unidirecional com o Linear

**Decisão.** Arquivos markdown em `plans/<lane>/` são a **fonte da verdade**; a **pasta da lane é o status autoritativo** (`implemented`, `inflight`, `under_review`, `backlog`, `dropped`). Um push para `main` sincroniza os planos **unidirecionalmente** com o Linear (time LAV), atualizando apenas título/descrição após a criação; uma **perna de retorno manual e revisada** separada puxa status/prioridade/lane do Linear de volta para o frontmatter do plano.

**Contexto.** Um time pequeno precisa de um estado de planejamento agnóstico a ferramentas e revisável, que não brigue com um rastreador de projetos, e um loop de agente autônomo precisa de um lugar estável para ler e escrever o estado dos planos.

**Justificativa.** A divisão de propriedade de campos mantém os dois sistemas livres de conflitos — o markdown é dono do conteúdo, o Linear é dono do estado de triagem — então um push nunca atropela a triagem humana. A lane `dropped/` mantém os planos cancelados fora do pipeline de sincronização para que não reapareçam (criada quando Allowed Exceptions Guardrails / LAV-5 foi rejeitada). Frontmatter desatualizado dentro de um plano é um bug de doc, não um status; a pasta vence, e onde o código mostra um recurso entregue apesar de um frontmatter "Backlog" (por exemplo, exclusão de conta), o código vence.

**Status.** **Adotada** (`scripts/sync-plans-to-linear.mjs`, `.github/workflows/sync-plans.yml`; lane `dropped/` em uso).

---

## 11. Divisão de repositório + open-source copyleft do cliente

**Decisão.** Dividir o monorepo em repositórios por componente (`lavasec-ios`, `-android`, `-web`, `-infra`, `-doc`, `-runner`) e **abrir o código do cliente first-party sob AGPL-3.0** no lugar de Apache-2.0, sobre o precedente copyleft do Mullvad/ProtonVPN.

**Contexto.** Desenvolvimento por componente e uma abertura do código do cliente. A questão da licença é se um concorrente poderia fazer um fork do cliente, fechá-lo e competir por preço.

**Justificativa.** O copyleft força os derivados a permanecerem abertos, evitando um fork fechado do cliente — uma postura de "cliente público, backend/ops privados", com backend, jurídico e ops mantidos privados. AGPL-3.0 (em vez de GPL-3.0 simples) foi escolhida para fechar a lacuna de uso em rede. A conhecida tensão de distribuição GPL-vs-App-Store é resolvida pela própria Lava ser a distribuidora do binário da App Store sob seu próprio copyright.

**Status.** **Adotada.** A divisão de repositório está **completa**: cada componente vive em seu próprio repositório — o cliente público `lavasec-ios` na tag v0.4.0, mais repositórios separados para Android, o site de marketing, backend/infraestrutura, docs e o pipeline de CI/release — e a seção "Repository layout" do `README.md` do `lavasec-ios` lista apenas o conteúdo por componente daquele repositório (`LavaSecApp/`, `LavaSecTunnel/`, `LavaSecWidget/`, `Shared/`, `Sources/`, `Tests/`) com a infraestrutura anotada como residindo em repositórios privados separados. O cliente tem código aberto sob **AGPL-3.0**: o `LICENSE` do `lavasec-ios` é a GNU Affero General Public License v3 e o `README.md` carrega o badge AGPL-3.0.

---

## Apêndice — outras reversões e rejeições registradas

Estas são decisões menores, mas cada uma teve uma virada registrada.

| Decisão | Justificativa | Status |
|---|---|---|
| DNS personalizado free vs pago | Posicionamento de monetização; brevemente permitido no free, depois retornou a somente pago | **Revertida** para somente pago |
| Login por e-mail/senha | Ser dono de senhas adiciona o ônus de reset/MFA/bloqueio/vazamento/sequestro enquanto Apple + Google bastam; recuperação que contorne quebraria o conhecimento zero | **Revertida** / nunca entregue (somente Apple + Google) |
| Allowed Exceptions Guardrails (LAV-5) | A precedência de barreiras foi entregue via a reformulação mais simples de edição de filter-list; o pagamento nunca deve contornar a barreira de ameaça de alta confiança | **Revertida** (lane `dropped/` criada) |
| Lockdown de promoção de branch do TestFlight | Lockdown inicial reconsiderado; substituído por um lockdown de runner planejado para após o open-source | **Revertida**, substituída por um plano de backlog |
| Canal de controle app↔extensão | `sendProviderMessage` (`NETunnelProviderSession`) é o **único caminho de controle app→tunnel** — ele carrega o estado tipado e versionado e dirige autoritativamente o run loop da extensão. O observador `CFNotificationCenter` do lado da extensão anterior nunca disparava de forma confiável no dispositivo e foi **removido** (afirmado ausente por testes de introspecção de fonte). As notificações Darwin sobrevivem apenas na direção **tunnel→app**, como um aviso de health-changed. | **Adotada** (provider-message é o único controle app→tunnel; Darwin é apenas health tunnel→app) |

> Invariante de segurança transversal referenciada ao longo do documento: o pagamento nunca contorna a **barreira de ameaça** não permissível e validada por hash. A precedência de decisão é **barreira de ameaça > allowlist local (exceções permitidas) > blocklist > permitir por padrão.**
