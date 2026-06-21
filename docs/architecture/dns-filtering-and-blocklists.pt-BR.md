---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Filtragem de DNS e listas de bloqueio

> Público: engenheiros. Este documento descreve o pipeline de DNS no dispositivo, o caminho do resolvedor com transporte criptografado, o mecanismo de decisão de filtragem e o modelo de catálogo de listas de bloqueio baseado apenas em source-url — com os números exatos que o código aplica. O status reflete a realidade confirmada no código. Onde um plano e o código discordam, **o código prevalece** e a divergência é apontada no próprio texto.

Toda a filtragem de DNS acontece no dispositivo; a Lava nunca encaminha sua navegação pelos servidores dela e nunca recebe a sequência de domínios que você visita — o backend guarda apenas os metadados do catálogo, um backup criptografado e opaco por usuário e diagnósticos anonimizados que você escolhe enviar.

A Lava é uma **filtragem local de DNS/listas de bloqueio**, não uma garantia de que todo domínio ou URL malicioso seja bloqueado.

---

## 1. O pipeline de DNS (Implementado) {#1-the-dns-pipeline-implemented}

O mecanismo de filtragem/resolução roda dentro do **túnel de pacotes / NE** — a extensão `NEPacketTunnelProvider` chamada `LavaSecTunnel` (`com.lavasec.app.tunnel`), que intercepta apenas DNS. Os endereços do túnel são `10.255.0.2` (túnel) e `10.255.0.1` (servidor DNS). O processo do app nunca vê o tráfego de consultas; ele apenas grava artefatos compilados no **App Group** (`group.com.lavasec`) e sinaliza o túnel via **mensagens de provedor** do NETunnelProviderSession (não notificações Darwin).

Para cada consulta DNS de entrada, o túnel executa uma **precedência de consultas** fixa no `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap-primeiro é um invariante absoluto.** Uma consulta que resolve o *próprio* nome de host do resolvedor configurado (o endpoint DoH/DoT/DoQ) nunca pode ser bloqueada ou pausada, ou o túnel não conseguiria nem subir o DNS criptografado. O dispatcher usa closures lazy, então cada etapa só é lida quando alcançada, preservando o curto-circuito (nenhuma leitura de snapshot quando existe uma resposta de bootstrap; nenhuma leitura de pausa durante o bootstrap).
- **temporary pause** encaminha para o upstream enquanto um TTL de pausa iniciado pelo usuário está ativo.
- **filter** avalia o domínio contra o snapshot compilado e ou o encaminha ou sintetiza uma resposta de bloqueio.

Uma consulta que passa pelo filtro (ação `.allow`) é entregue ao caminho do resolvedor (§3). O túnel **falha fechado** na partida a frio sem um snapshot reutilizável: ele instala um snapshot de runtime fail-closed que bloqueia todo o tráfego em vez de resolver sem filtro.

---

## 2. O mecanismo de filtragem (Implementado) {#2-the-filtering-engine-implemented}

### 2.1 Precedência de decisão {#21-decision-precedence}

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) aplica a precedência de segurança canônica:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Ordem | Conjunto de regras | Resultado | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | bloquear | `.threatGuardrail` |
| 2 | `allowRules` | permitir | `.localAllowlist` |
| 3 | `blockRules` | bloquear | `.blocklist` |
| 4 | — | permitir | `.defaultAllow` |

Um domínio que falha na normalização é bloqueado com o motivo `.invalidDomain` (fail-safe). A mesma precedência é espelhada na forma binária em disco (`CompactFilterSnapshot`). A barreira contra ameaças fica acima da allowlist local por design: **o pagamento nunca contorna a barreira contra ameaças não permissível**, e uma exceção do usuário não pode desbloquear um domínio da barreira.

> Note: na árvore de trabalho atual, `nonAllowableThreatRules` / `guardrailSources` estão vazios (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); o espaço da precedência está conectado e em vigor, mas é entregue ainda sem entradas de barreira.

### 2.2 Armazenamento de regras e a unidade de memória residente {#22-rule-storage-and-the-resident-memory-unit}

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) armazena os conjuntos `exactDomains` + `suffixDomains`. A correspondência (`containsNormalized`) faz uma busca exata mais uma varredura de sufixo do nível pai (estilo `hasSuffix`) no momento da consulta — **não há subsunção de subdomínios em tempo de compilação**. Uma linha de wildcard válida é **uma regra** e uma entrada na tabela de memória. Essa identidade de 1 linha = 1 regra é o que torna a contagem de regras a métrica honesta de recursos (§4).

### 2.3 Formas do snapshot compilado {#23-compiled-snapshot-forms}

- **`FilterSnapshot`** — o filtro compilado em memória: `blockRules`, `allowRules`, `nonAllowableThreatRules` e o preset do resolvedor.
- **`CompactFilterSnapshot`** — a forma binária em disco, amigável a mmap, que o túnel realmente lê (magic `LSCFSNP1`, `fileVersion 1`). É carregada com cópia zero via mmap (§4.3).

O app grava tanto `filter-snapshot.json` quanto `filter-snapshot.compact` no App Group; o túnel decodifica o artefato compacto. Um caminho de **reúso na partida quente** (`FilterArtifactStore`) permite que o túnel reutilize o artefato compacto em disco sem recompilar, controlado por uma impressão digital de identidade + um manifesto gravado atomicamente; o reúso é rejeitado (motivo seguro para privacidade, apenas o nome do campo) quando o transporte do resolvedor, a cobertura do catálogo ou as entradas do snapshot mudam.

---

## 3. Transportes criptografados e o caminho do resolvedor (Implementado) {#3-encrypted-transports--the-resolver-path-implemented}

### 3.1 Enum de transporte {#31-transport-enum}

Consultas não bloqueadas são encaminhadas ao resolvedor upstream configurado. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) tem **cinco** valores:

| Transporte | Valor bruto | Anotação exibida na interface |
|---|---|---|
| DNS do dispositivo | `device-dns` | *(nenhuma — o nome é o transporte)* |
| DNS comum | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

Os presets integrados são Google, Cloudflare, Quad9, Mullvad (cada um nas variantes IP / DoH / DoT) mais DNS do dispositivo e Personalizado. Resolvedores personalizados aceitam um servidor IPv4/IPv6 comum, uma URL DoH, uma URL DoT (`tls://` / `dot://`), uma URL DoQ (`doq://` / `quic://`) ou um carimbo DNS `sdns://`; nomes de usuário/senhas e localhost são rejeitados. DoH/DoT/DoQ usam por padrão a porta `853` para DoT/DoQ e exigem um caminho para DoH.

### 3.2 DoH / DoH3 {#32-doh--doh3}

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) executa DoH sobre `URLSession`. Toda requisição opta por HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); o carregador da Apple recai nativamente para H2/H1, então isso nunca torna um resolvedor alcançável inalcançável. O protocolo negociado é lido de `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

A interface anota **`DoH3` (sem barra)** — por exemplo, "Quad9 (DoH3)" — **somente quando uma negociação h3 é de fato observada** (`DoHHTTPVersion.dohAnnotation`); caso contrário, exibe `DoH`. DoH3 é preferido, nunca prometido: o rótulo é observacional e restrito ao resolvedor, nunca persistido (o carry-over de "DoH3 confirmado" entre reinícios foi revertido). As requisições enviam POST `application/dns-message`; as respostas são validadas por content-type e comprimento e o ID da transação é restaurado antes da gravação de volta.

### 3.3 DoT {#33-dot}

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection`s em pool, **até 4 conexões por endpoint** (`maxConnectionsPerEndpoint = 4`), em round-robin, para que consultas paralelas evitem bloqueio de cabeça de fila. Ele lida com **obsolescência por ociosidade**: provedores como a Cloudflare fecham conexões DoT ociosas no lado do servidor (~10s) sem sinalizar uma mudança de estado, então uma conexão reutilizada que ficou ociosa por mais de **8 segundos** (`reusedConnectionMaxIdleInterval = 8`) é renovada antes do envio, e um timeout numa conexão reutilizada ganha **exatamente uma nova tentativa com conexão nova**.

### 3.4 DoQ — conexão nova por consulta {#34-doq--fresh-connection-per-query}

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantém um pool limitado de **4 vias por endpoint**, mas **cada consulta abre uma conexão QUIC nova** — um handshake completo por consulta. O pool de 4 vias oferece **concorrência, não reúso de handshake**.

**Status do reúso de conexão DoQ (Descartado / adiado).** O reúso foi revisado e medido em dispositivo (34 handshakes novos em 35 consultas ≈ sem reúso), então implementado como um caminho `NWConnectionGroup` multi-stream condicionado ao iOS 26, testado em dispositivo contra o DoQ da AdGuard, e **revertido como saldo negativo** (falhas de stream + erros de fallback contra um servidor real). A RFC 9250 mapeia cada consulta para seu próprio stream QUIC, então o reúso exige `NWConnectionGroup`/`openStream`, que é **apenas iOS 26.0+**; o piso de implantação atual é **iOS 17**. O reúso fica adiado até o piso chegar ao iOS 26. O DoQ personalizado é rejeitado em dispositivos que não o suportam ("DNS over QUIC is not supported on this device").

### 3.5 Política de resolução {#35-resolution-policy}

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) é dono da política de upstream:

1. **Roteamento de transporte** pelo transporte configurado.
2. **Degradação para DNS comum** quando um plano criptografado não tem endpoints.
3. **Failover por endpoint** com um portão de backoff — um endpoint em backoff nunca toca a rede (resultado `backed-off`).
4. **Fallback para o DNS do dispositivo** quando o primário não retorna resposta *e* o plano permite (a propriedade do plano é `shouldFallbackToDeviceDNS`, derivada do campo de config `fallbackToDeviceDNS`); o resultado é reanotado como o transporte do dispositivo. A execução na rede é injetada por trás de executores para que a política seja testável em unidade; o estado de backoff fica fora da política pura.

---

## 4. Orçamento de regras de filtro, teto da NE e mmap {#4-filter-rules-budget-ne-ceiling-and-mmap}

A métrica de tier entregue é o **orçamento de regras de filtro**: o total de **regras** de domínio compiladas que um usuário pode habilitar. Isso substituiu o antigo limite de **contagem** de listas habilitadas (3 grátis / 10 pago), que era um proxy desonesto — uma lista pode ter 1 mil ou 1 milhão de regras. Há **duas camadas**: uma barreira de dispositivo para todos e um limite de monetização por tier abaixo dela.

### 4.1 Limites por tier (Implementado) {#41-tier-limits-implemented}

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) é a fonte da verdade:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Listas de bloqueio / DNS personalizados |
|---|---|---|---|---|
| **Grátis** | **500.000** | 25 | 25 | Não |
| **Plus** (`.paid` / `.plus`) | **2.000.000** | 1.000 | 1.000 | Sim |

O limite por tier é uma fronteira de monetização, **nunca um paywall sobre a barreira de dispositivo**. O **Lava Security Plus** desbloqueia apenas a personalização — nunca a segurança básica, nunca a barreira contra ameaças. As listas de bloqueio personalizadas (pagas) são buscadas diretamente do dispositivo do usuário, analisadas e armazenadas em cache localmente, e nunca passam por proxy nos servidores da Lava.

### 4.2 Barreira de memória do dispositivo + teto da NE (Implementado) {#42-device-memory-guardrail--ne-ceiling-implemented}

O túnel de pacotes está sujeito ao **teto de memória de ~50 MiB por extensão** do iOS (um limite de design por tipo de extensão do SO para túneis de pacotes desde o iOS 15, não escalado pela RAM; ele vive num `com.apple.jetsamproperties.{Model}.plist` por modelo de dispositivo e pode ser menor em aparelhos mais antigos). Ultrapassá-lo dispara o jetsam. Não há API para esse teto, então o orçamento mantém uma margem abaixo do precipício.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) faz a conta, denominada em regras de filtro (block + allow + guardrail):

| Constante | Valor |
|---|---|
| `baselineMegabytes` | 4.0 MB (sobrecarga fixa do processo, medida ≈3.5 MB, arredondada para cima) |
| `estimatedBytesPerRule` | 9.0 B residentes sujos por regra (medido ≈8.5 B, arredondado para cima) |
| `maxResidentMegabytes` | 32.0 MB (teto-alvo, deixando ~10 MB de folga abaixo do precipício de jetsam observado de ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1,048,576) / 9 = 3,262,236 regras** |

Essa **barreira de dispositivo de ~3,26 mi de regras** é o piso de segurança rígido para *todo* usuário, ficando acima de qualquer tier de assinatura, e **nunca é um paywall**. Medição de referência (dispositivo "chimmy", 2026-06-13): **789.831 regras → 9,9 MB de `phys_footprint`**, ou seja, ≈ baseline + custo por regra.

### 4.3 Estratégia de mmap (Implementado) {#43-mmap-strategy-implemented}

O snapshot compacto é carregado com `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), e o `CompactBinaryReader` retorna fatias com cópia zero. O blob de texto de domínios de vários megabytes permanece **respaldado em arquivo/limpo** e é excluído do `phys_footprint` contado pelo jetsam; apenas as tabelas `[Entry]` decodificadas custam memória residente (~6 B/regra em disco, ~8,5 B residentes sujos). Isso eleva o teto de domínios no dispositivo: o custo residente são as tabelas de entradas, não o artefato inteiro.

### 4.4 Aplicação em duas camadas (Implementado) {#44-two-layer-enforcement-implemented}

- **Autoritativa (em tempo de compilação).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) aplica o orçamento sobre a **união deduplicada** de todas as listas habilitadas. A barreira de dispositivo é verificada **primeiro** (o piso rígido); o limite por tier vincula abaixo dela. Configurações acima do orçamento são rejeitadas de forma determinística — `exceedsDeviceMemoryBudget` ou `exceedsTierFilterRuleLimit` — em vez de deixar o túnel sofrer jetsam. O erro nomeia as duas maiores listas contribuintes para que a correção seja óbvia.
- **Consultiva (interface em tempo de seleção).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) move o medidor de seleção usando uma **soma** por lista com uma **margem de teto suave de 1,10** que compensa a sobrecontagem cruzada de ~7–10% entre listas (a soma por lista superestima a união deduplicada).

### 4.5 O parser (Implementado) {#45-the-parser-implemented}

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) conta as regras literalmente: descarta comentários/linhas em branco/linhas inválidas, normaliza, deduplica strings exatas dentro de uma lista (via um `Set`) e limita em **`maxRules = 1,000,000`** por lista (padrão), com comprimento máximo de linha de 4.096 caracteres. Formatos suportados: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (o `auto` tenta hosts → dnsmasq → adblock → plain). Uma linha válida = uma regra = a unidade de memória.

> **Linhas `hosts` com múltiplos hosts (parser rules versão 2).** Uma linha `hosts` que mapeia um IP para vários hosts (`0.0.0.0 a.com b.com c.com`) agora emite **cada** host como sua própria regra, não só o primeiro; o `maxRules` é aplicado **por regra** (não por linha), de modo que uma linha com muitos hosts perto do limite não pode ultrapassá-lo. Como os mesmos bytes de upstream agora podem render mais regras, a versão de regras do parser foi elevada de **1 → 2**, invalidando entradas obsoletas de `RuleSetCache` analisadas sob o antigo comportamento de só o primeiro host.

### 4.6 Robustez de download e decodificação (Implementado) {#46-download--decode-robustness-implemented}

O túnel e a sincronização do catálogo rodam dentro do orçamento de memória da NE, então a ingestão de listas é endurecida contra entradas hostis ou malformadas:

- **Downloads em streaming.** O `defaultDataFetcher` baixa os bytes da lista para um arquivo temporário via `URLSession.download` (pico de memória limitado) com uma checagem de tamanho após o download (`maximumBlocklistBytes`) em vez de bufferizar o corpo inteiro na RAM; um corpo grande demais levanta `BlocklistDownloadSizeLimitExceeded`.
- **Limite de metadados do catálogo (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes` rejeita um catálogo remoto grande demais antes de decodificar, de modo que um host hostil/MITM não pode forçar uma decodificação JSON com OOM na extensão.
- **Decodificação UTF-8 tolerante.** Um único byte UTF-8 inválido não rejeita mais uma lista inteira (o que, sob fail-closed, bloquearia todo o DNS); bytes inválidos viram U+FFFD e apenas a linha problemática falha na validação por linha e é descartada.
- **Erros nomeados de lista de bloqueio personalizada.** Uma lista personalizada que falha agora exibe `customBlocklistUnavailable(displayName:reason:)` — "Couldn't load the custom blocklist '<name>'. <why>" — em vez de um `URLError` cru; o cancelamento é propagado como cancelamento, não como falha de download.

---

## 5. Catálogo de listas de bloqueio e fontes padrão {#5-blocklist-catalog--default-sources}

### 5.1 Modelo de catálogo (Implementado) {#51-catalog-model-implemented}

O **catálogo de listas de bloqueio** é a lista publicada de fontes disponíveis. O **Worker lavasec-api** serve os metadados JSON a partir de um bucket R2 em `GET /v1/catalog` (e `/v1/catalog/:version`); o dispositivo busca os **bytes** reais da lista diretamente de cada `source_url` upstream. Os endpoints de catálogo do iOS são `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

No dispositivo, o `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Busca os bytes da lista diretamente de `source.sourceURL`, aplicando um limite de tamanho.
2. Calcula o SHA-256 e aceita os bytes apenas se o checksum estiver em `accepted_source_hashes` do catálogo.
3. Em caso de incompatibilidade, recai para o último cache local válido ou **falha fechado** (`checksumMismatch`) — a menos que a fonte permita explicitamente a rotação direta de upstream.
4. Analisa/normaliza/deduplica localmente.
5. Filtra cada conjunto de regras analisado através de `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`), para que uma lista de upstream nunca possa bloquear domínios da Lava/Apple/provedor de identidade.

O **conjunto de domínios protegidos** (filtrados antes da ativação): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (todos por correspondência de sufixo). O Worker aplica um filtro `PROTECTED_SUFFIXES` equivalente ao calcular os metadados; o dispositivo revalida de qualquer modo.

### 5.2 Fontes curadas (Implementado) {#52-curated-sources-implemented}

`DefaultCatalog.curatedSources` (`BlocklistModels.swift:232-243`) lista **10** fontes:

| Fonte | Licença |
|---|---|
| Block List Basic | Unlicense |
| Block List Project Phishing | Unlicense |
| Block List Project Scam | Unlicense |
| Block List Project Ransomware | Unlicense |
| Phishing.Database Active Domains | MIT |
| HaGeZi Multi Light | GPL-3.0 |
| HaGeZi Multi Normal | GPL-3.0 |
| HaGeZi Multi PRO mini | GPL-3.0 |
| HaGeZi Multi PRO | GPL-3.0 |
| OISD Small | GPL-3.0 |

`guardrailSources` está vazio. As fontes GPL (HaGeZi, OISD) são visíveis no catálogo, mas **opt-in / DESLIGADAS por padrão** à espera da aprovação jurídica; o Worker restringe a sincronização/publicação de lançamento a `source_url_only` mais os prefixos GPL permitidos (`hagezi-`/`oisd-`).

### 5.3 Listas habilitadas por padrão para usuários grátis (Implementado) {#53-default-enabled-lists-for-free-users-implemented}

A configuração padrão grátis de fato é `OnboardingDefaults.lavaRecommendedDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`), que habilita **Block List Project Phishing + Block List Project Scam**, com o preset de resolvedor DNS do dispositivo (`resolverPresetID = DNSResolverPreset.device.id`) e o fallback para o DNS do dispositivo ligado.

Esse padrão grátis é **produzido por `defaultEnabled`**, não fixado no código. `blockListProjectPhishing` (`BlocklistModels.swift:139`) e `blockListProjectScam` (`BlocklistModels.swift:148`) definem ambos `defaultEnabled: true`, e `DefaultCatalog.recommendedDefaultSourceIDs` (`BlocklistModels.swift:250-252`) é derivado de `curatedSources.filter(\.defaultEnabled)`. O comentário no código-fonte (`BlocklistModels.swift:246-249`) chama o `defaultEnabled` de "the single source of truth for the fresh-install default", espelhando a coluna `default_enabled` do catálogo do backend. Fluindo através de `recommendedDefaultSourceIDs` para dentro de `OnboardingDefaults`, o `defaultEnabled` é o mecanismo vivo — basta virar a flag numa fonte para mudar o padrão.

> **Fonte da verdade do padrão (o código prevalece).** Qualquer texto de plano/catálogo que diga "Block List Basic é o único padrão" está errado para o dispositivo; o dispositivo entrega Phishing + Scam a partir de `defaultEnabled: true`, e a flag `BlocklistSource.defaultEnabled` do iOS é o mecanismo vivo autoritativo. A coluna `default_enabled` do catálogo do backend foi realinhada ao mesmo conjunto Phishing + Scam por uma migração, então os metadados servidos em `/v1/catalog` agora batem com o cliente. O texto "Listas de bloqueio habilitadas 3 → 10" do site público ainda está **obsoleto** — o gate real é o orçamento de regras de filtro de 500K/2M, não uma contagem de listas.

### 5.4 Modelo de distribuição GPL baseado apenas em source-url (Implementado) {#54-source-url-only-gpl-distribution-model-implemented}

**Source-url-only** é o modelo de distribuição de conformidade GPL/PI: a Lava publica apenas a URL de upstream + os hashes aceitos; o dispositivo busca e analisa as listas por conta própria. A Lava **nunca** armazena, espelha, transforma ou serve os bytes de listas de bloqueio de terceiros. Isso **substituiu o design abandonado de espelho em R2** (o plano original de "espelho R2 cru" foi revertido em 2026-05-25).

No lado do Worker, `syncOneBlocklist` busca cada fonte upstream e a normaliza+hash (calculando `source_hash`, `normalized_hash`, `entry_count`) mas grava `raw_r2_key = null` / `normalized_r2_key = null` — apenas os metadados JSON do catálogo chegam ao R2. O `check-gpl-blocklist-distribution.sh` é a barreira de CI que aplica o modelo inteiro: nenhum código de espelho/transformação, nenhuma URL de artefato/download da Lava, nenhuma fonte GPL habilitada por padrão, nenhuma gravação de bytes de lista no R2 pelo Worker, nenhum texto de "espelho hospedado pela Lava", nenhum `.txt`/`.json` GPL empacotado, e `source_url_only` obrigatório nas migrações + documentos jurídicos.

> **Nota de licença:** o código próprio da Lava é entregue sob **AGPL-3.0** (o arquivo `LICENSE` é a GNU AGPL v3, batendo com o badge do README). As listas de bloqueio de terceiros (HaGeZi, OISD) permanecem **GPL-3.0** sob suas próprias licenças de upstream — o modelo source-url-only existe justamente para que a Lava possa usá-las sem nunca redistribuir bytes licenciados sob GPL. A GPL-3.0 aqui é uma propriedade das listas de upstream, não do app da Lava.

---

## 6. Resumo de status {#6-status-summary}

| Área | Status |
|---|---|
| Precedência de consultas DNS (bootstrap > pause > filter) | Implementado |
| Precedência de decisão de filtro (guardrail > allowlist > blocklist > default-allow) | Implementado |
| Espaço de precedência da barreira contra ameaças (conectado; entregue ainda sem entradas) | Implementado |
| DoH / DoH3 (rótulo h3 observacional) | Implementado |
| DoT (pool de 4/endpoint, renovação por 8s de ociosidade, uma nova tentativa) | Implementado |
| DoQ (conexão nova por consulta, concorrência de 4 vias) | Implementado |
| Reúso de conexão DoQ | Descartado / adiado para o piso iOS 26 |
| Degradação do resolvedor + failover por endpoint + fallback para DNS do dispositivo | Implementado |
| Orçamento de regras de filtro (Grátis 500K / Plus 2M) | Implementado |
| Barreira de dispositivo de ~3,26 mi de regras (alvo de 32 MB sob o teto de 50 MiB da NE) | Implementado |
| mmap com cópia zero do snapshot compacto | Implementado |
| Catálogo source-url-only + busca direta de upstream + validação de hash | Implementado |
| Filtro de domínios protegidos | Implementado |
| Padrão grátis = Phishing + Scam (não Basic) | Implementado (catálogo realinhado para coincidir) |
| Licença do código próprio da Lava | AGPL-3.0 (`LICENSE`); listas de terceiros permanecem GPL-3.0 no upstream |

---

## Veja também {#see-also}

- [`../product/overview.md`](../product/overview.md) — resumo do produto em uma frase, promessa de privacidade, abas.
- Tiers e monetização (referência interna) — o Lava Security Plus e o orçamento de regras de filtro como métrica de tier.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — a decisão de conformidade source-url-only.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licenças e atribuições das listas de bloqueio/resolvedores de upstream.
