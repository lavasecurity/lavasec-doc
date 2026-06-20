---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Filtragem de DNS e listas de bloqueio

> Público: pessoas da engenharia. Este documento descreve o fluxo de DNS que roda no aparelho, o caminho do resolvedor com transporte criptografado, o mecanismo de decisão da filtragem e o modelo de catálogo de listas de bloqueio baseado apenas em source-url — com os números exatos que o código aplica. O status reflete o que está confirmado no código. Onde um plano e o código discordam, **o código prevalece** e a diferença é apontada ali mesmo.

Toda a filtragem de DNS acontece no aparelho; a Lava nunca encaminha sua navegação pelos servidores dela e nunca recebe a sequência de domínios que você visita — o backend guarda apenas os metadados do catálogo, um backup criptografado e opaco por usuário e diagnósticos anônimos que você escolhe enviar.

A Lava faz **filtragem local de DNS/listas de bloqueio**, e não uma garantia de que todo domínio ou URL malicioso será bloqueado.

---

## 1. O fluxo de DNS (Implementado)

O mecanismo de filtragem/resolução roda dentro do **NE / túnel de pacotes** — a extensão `NEPacketTunnelProvider` chamada `LavaSecTunnel` (`com.lavasec.app.tunnel`), que intercepta apenas DNS. Os endereços do túnel são `10.255.0.2` (túnel) e `10.255.0.1` (servidor DNS). O processo do app nunca vê o tráfego de consultas; ele só grava artefatos compilados no **App Group** (`group.com.lavasec`) e sinaliza o túnel via **provider messages** do NETunnelProviderSession (não notificações Darwin).

Para cada consulta DNS recebida, o túnel executa uma **ordem de precedência fixa de consultas** no `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap-first é uma invariante rígida.** Uma consulta que resolve o *próprio* nome de host do resolvedor configurado (o endpoint DoH/DoT/DoQ) nunca pode ser bloqueada ou pausada, caso contrário o túnel não conseguiria sequer levantar o DNS criptografado. O dispatcher usa closures lazy, de modo que cada etapa só é lida quando alcançada, preservando o curto-circuito (não lê o snapshot quando há uma resposta de bootstrap; não lê a pausa durante o bootstrap).
- **temporary pause** encaminha para o upstream enquanto um TTL de pausa iniciada pelo usuário estiver ativo.
- **filter** avalia o domínio contra o snapshot compilado e o encaminha ou sintetiza uma resposta de bloqueio.

Uma consulta que passa pelo filtro (ação `.allow`) é entregue ao caminho do resolvedor (§3). O túnel **falha de forma fechada** (fail closed) em um cold start sem um snapshot reutilizável: ele instala um snapshot de runtime fail-closed que bloqueia todo o tráfego em vez de resolver sem filtragem.

---

## 2. O mecanismo de filtragem (Implementado)

### 2.1 Precedência de decisão

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) aplica a precedência de segurança canônica:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Ordem | Conjunto de regras | Resultado | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | bloqueia | `.threatGuardrail` |
| 2 | `allowRules` | permite | `.localAllowlist` |
| 3 | `blockRules` | bloqueia | `.blocklist` |
| 4 | — | permite | `.defaultAllow` |

Um domínio que falha na normalização é bloqueado com o motivo `.invalidDomain` (fail-safe). A mesma precedência é espelhada na forma binária em disco (`CompactFilterSnapshot`). A proteção contra ameaças (threat guardrail) fica acima da allowlist local por design: **o pagamento nunca contorna a proteção contra ameaças não permitidas**, e uma exceção do usuário não pode desbloquear um domínio protegido pelo guardrail.

> Nota: na árvore de trabalho atual, `nonAllowableThreatRules` / `guardrailSources` estão vazios (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); o espaço na precedência está conectado e em vigor, mas é entregue ainda sem nenhuma entrada de guardrail.

### 2.2 Armazenamento de regras e a unidade de memória residente

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) guarda os conjuntos `exactDomains` + `suffixDomains`. A correspondência (`containsNormalized`) faz uma busca exata mais um percurso por sufixo de domínio pai (no estilo `hasSuffix`) no momento da consulta — **não há subsunção de subdomínios em tempo de compilação**. Uma linha curinga válida é **uma regra** e uma entrada na tabela de memória. Essa identidade 1 linha = 1 regra é o que torna a contagem de regras a métrica honesta de recurso (§4).

### 2.3 Formas compiladas do snapshot

- **`FilterSnapshot`** — o filtro compilado em memória: `blockRules`, `allowRules`, `nonAllowableThreatRules` e o preset do resolvedor.
- **`CompactFilterSnapshot`** — a forma binária em disco, amigável a mmap, que o túnel de fato lê (magic `LSCFSNP1`, `fileVersion 1`). É carregada com zero cópia via mmap (§4.3).

O app grava tanto `filter-snapshot.json` quanto `filter-snapshot.compact` no App Group; o túnel decodifica o artefato compacto. Um caminho de **reuso em warm startup** (`FilterArtifactStore`) permite que o túnel reutilize o artefato compacto em disco sem recompilar, controlado por uma impressão digital de identidade + um manifesto gravado de forma atômica; o reuso é rejeitado (por um motivo seguro para a privacidade, apenas com o nome do campo) quando o transporte do resolvedor, a cobertura do catálogo ou as entradas do snapshot mudam.

---

## 3. Transportes criptografados e o caminho do resolvedor (Implementado)

### 3.1 Enum de transportes

Consultas não bloqueadas são encaminhadas ao resolvedor upstream configurado. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) tem **cinco** valores:

| Transporte | Valor bruto | Anotação exibida na interface |
|---|---|---|
| DNS do aparelho | `device-dns` | *(nenhuma — o nome é o transporte)* |
| DNS comum | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

Os presets embutidos são Google, Cloudflare, Quad9, Mullvad (cada um nas variantes IP / DoH / DoT) mais DNS do aparelho e Personalizado. Resolvedores personalizados aceitam um servidor IPv4/IPv6 comum, uma URL DoH, uma URL DoT (`tls://` / `dot://`), uma URL DoQ (`doq://` / `quic://`) ou um carimbo de DNS `sdns://`; nomes de usuário/senhas e localhost são rejeitados. DoH/DoT/DoQ usam por padrão a porta `853` para DoT/DoQ e exigem um caminho (path) para DoH.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) executa DoH sobre `URLSession`. Toda requisição opta por HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); o carregador da Apple recai para H2/H1 nativamente, então isso nunca torna inacessível um resolvedor que estaria acessível. O protocolo negociado é lido de `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

A interface anota **`DoH3` (sem barra)** — por exemplo, "Quad9 (DoH3)" — **apenas quando uma negociação h3 é de fato observada** (`DoHHTTPVersion.dohAnnotation`); caso contrário, mostra `DoH`. DoH3 é preferido, nunca prometido: o rótulo é observacional e específico do resolvedor, nunca persistido (a continuidade de "DoH3 confirmado" entre reinícios foi revertida). As requisições fazem POST de `application/dns-message`; as respostas têm content-type e tamanho validados e o ID da transação é restaurado antes da escrita de volta.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection`s em pool, **até 4 conexões por endpoint** (`maxConnectionsPerEndpoint = 4`), em round-robin, para que consultas paralelas evitem bloqueio de cabeça de fila (head-of-line). Ele cuida de **conexões ociosas e desatualizadas**: provedores como a Cloudflare fecham conexões DoT ociosas do lado do servidor (~10s) sem sinalizar a mudança de estado, então uma conexão reaproveitada que ficou ociosa por mais de **8 segundos** (`reusedConnectionMaxIdleInterval = 8`) é renovada antes do envio, e um timeout em uma conexão reaproveitada ganha **exatamente uma nova tentativa com conexão nova**.

### 3.4 DoQ — conexão nova por consulta

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantém um pool limitado de **4 lanes por endpoint**, mas **cada consulta abre uma conexão QUIC nova** — um handshake completo por consulta. O pool de 4 lanes oferece **concorrência, não reuso de handshake**.

**Status do reuso de conexão DoQ (Descartado / adiado).** O reuso foi avaliado e medido no aparelho (34 handshakes novos em 35 consultas ≈ nenhum reuso), depois implementado como um caminho `NWConnectionGroup` multi-stream restrito ao iOS 26, testado no aparelho contra o DoQ da AdGuard e **revertido por ser líquido-negativo** (falhas de stream + erros de fallback contra um servidor real). A RFC 9250 mapeia cada consulta para o seu próprio stream QUIC, então o reuso exige `NWConnectionGroup`/`openStream`, que é **somente iOS 26.0+**; o piso de implantação atual é **iOS 17**. O reuso fica adiado até o piso chegar ao iOS 26. O DoQ personalizado é rejeitado em aparelhos que não o suportam ("DNS over QUIC is not supported on this device").

### 3.5 Política de resolução

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) é dono da política de upstream:

1. **Roteamento de transporte** conforme o transporte configurado.
2. **Degradação para DNS comum** quando um plano criptografado não tem endpoints.
3. **Failover por endpoint** com um portão de backoff — um endpoint em backoff nunca chega à rede (resultado `backed-off`).
4. **Fallback para o DNS do aparelho** quando o primário não retorna resposta *e* o plano permite (a propriedade do plano é `shouldFallbackToDeviceDNS`, derivada do campo de configuração `fallbackToDeviceDNS`); o resultado é reanotado como o transporte do aparelho. A execução na rede é injetada por trás de executores, de modo que a política possa ser testada em unidade; o estado de backoff fica fora da política pura.

---

## 4. Orçamento de regras de filtro, teto do NE e mmap

A métrica de plano em produção é o **orçamento de regras de filtro**: o total de **regras** de domínio compiladas que um usuário pode habilitar. Isso substituiu o antigo limite por **contagem** de listas habilitadas (3 no gratuito / 10 no pago), que era um indicador desonesto — uma lista pode ter 1 mil ou 1 milhão de regras. Há **duas camadas**: uma proteção do aparelho válida para todo mundo, e um limite de monetização por plano abaixo dela.

### 4.1 Limites por plano (Implementado)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) é a fonte da verdade:

| Plano | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Listas de bloqueio / DNS personalizados |
|---|---|---|---|---|
| **Gratuito** | **500.000** | 10 | 10 | Não |
| **Plus** (`.paid` / `.plus`) | **2.000.000** | 500 | 500 | Sim |

O limite do plano é uma fronteira de monetização, **nunca um paywall sobre a proteção do aparelho**. O **Lava Security Plus** libera apenas personalização — nunca a segurança básica, nunca a proteção contra ameaças. Listas de bloqueio personalizadas (pagas) são buscadas diretamente do aparelho do usuário, processadas e armazenadas em cache localmente, e nunca passam pelos servidores da Lava.

### 4.2 Proteção de memória do aparelho + teto do NE (Implementado)

O túnel de pacotes está sujeito ao **teto de memória de ~50 MiB por extensão** do iOS (um limite de design do sistema operacional por tipo de extensão para túneis de pacotes desde o iOS 15, não proporcional à RAM; ele fica em um `com.apple.jetsamproperties.{Model}.plist` por modelo de aparelho e pode ser menor em aparelhos mais antigos). Ultrapassá-lo dispara o jetsam. Não há API para esse teto, então o orçamento mantém uma margem abaixo do limite.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) faz a conta, expressa em regras de filtro (block + allow + guardrail):

| Constante | Valor |
|---|---|
| `baselineMegabytes` | 4,0 MB (overhead fixo do processo, medido ≈3,5 MB, arredondado para cima) |
| `estimatedBytesPerRule` | 9,0 B residentes "dirty" por regra (medido ≈8,5 B, arredondado para cima) |
| `maxResidentMegabytes` | 32,0 MB (teto alvo, deixando ~10 MB de folga sob o limite de jetsam observado de ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1.048.576) / 9 = 3.262.236 regras** |

Essa **proteção do aparelho de ~3,26 milhões de regras** é o piso de segurança rígido para *todo* usuário, ficando acima de qualquer plano de assinatura, e **nunca é um paywall**. Medição de referência (aparelho "chimmy", 13/06/2026): **789.831 regras → 9,9 MB de `phys_footprint`**, ou seja, ≈ baseline + custo por regra.

### 4.3 Estratégia de mmap (Implementado)

O snapshot compacto é carregado com `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), e `CompactBinaryReader` retorna fatias com zero cópia. O blob de texto de domínios, de vários megabytes, permanece **respaldado por arquivo/limpo** (file-backed/clean) e é excluído do `phys_footprint` contabilizado pelo jetsam; apenas as tabelas `[Entry]` decodificadas custam memória residente (~6 B/regra em disco, ~8,5 B residentes "dirty"). Isso eleva o teto de domínios no aparelho: o custo residente são as tabelas de entradas, não o artefato inteiro.

### 4.4 Aplicação em duas camadas (Implementado)

- **Autoritativa (em tempo de compilação).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) aplica o orçamento sobre a **união deduplicada** de todas as listas habilitadas. A proteção do aparelho é verificada **primeiro** (o piso rígido); o limite do plano vincula abaixo dela. Configurações acima do orçamento são rejeitadas de forma determinística — `exceedsDeviceMemoryBudget` ou `exceedsTierFilterRuleLimit` — em vez de deixar o túnel sofrer jetsam. O erro nomeia as duas maiores listas contribuintes, para que a correção fique óbvia.
- **Orientativa (interface, no momento da seleção).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) alimenta o medidor de seleção usando uma **soma** por lista com uma **margem de teto suave de 1,10** que compensa a sobrecontagem entre listas de ~7–10% (a soma por lista superestima a união deduplicada).

### 4.5 O parser (Implementado)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) conta regras de forma literal: descarta comentários/linhas em branco/linhas inválidas, normaliza, deduplica strings exatas dentro de uma lista (via um `Set`) e limita em **`maxRules = 1.000.000`** por lista (padrão), com um comprimento máximo de linha de 4.096 caracteres. Formatos suportados: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (o `auto` tenta hosts → dnsmasq → adblock → plain). Uma linha válida = uma regra = a unidade de memória.

---

## 5. Catálogo de listas de bloqueio e fontes padrão

### 5.1 Modelo de catálogo (Implementado)

O **catálogo de listas de bloqueio** é a lista publicada de fontes disponíveis. O **Worker lavasec-api** serve metadados em JSON a partir de um bucket R2 em `GET /v1/catalog` (e `/v1/catalog/:version`); o aparelho busca os **bytes** reais da lista diretamente de cada `source_url` upstream. Os endpoints do catálogo no iOS são `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

No aparelho, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Busca os bytes da lista diretamente de `source.sourceURL`, aplicando um limite de tamanho.
2. Calcula o SHA-256 e aceita os bytes apenas se o checksum estiver em `accepted_source_hashes` do catálogo.
3. Em caso de divergência, recai para o último cache local válido ou **falha de forma fechada** (`checksumMismatch`) — a menos que a fonte permita explicitamente a rotação direta no upstream.
4. Processa/normaliza/deduplica localmente.
5. Filtra todo conjunto de regras processado através de `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`), de modo que uma lista upstream nunca consiga bloquear domínios da Lava/Apple/provedor de identidade.

O **conjunto de domínios protegidos** (filtrados antes da ativação): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (todos correspondidos por sufixo). O Worker aplica um filtro `PROTECTED_SUFFIXES` equivalente ao calcular os metadados; o aparelho revalida de qualquer forma.

### 5.2 Fontes curadas (Implementado)

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

`guardrailSources` está vazio. As fontes GPL (HaGeZi, OISD) ficam visíveis no catálogo, mas são **opt-in / desligadas por padrão** enquanto aguardam aprovação jurídica; o Worker restringe a sincronização/publicação de lançamento a `source_url_only` mais os prefixos GPL permitidos (`hagezi-`/`oisd-`).

### 5.3 Listas habilitadas por padrão para usuários gratuitos (Implementado)

A configuração padrão real do plano gratuito é `OnboardingDefaults.lavaRecommendedDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift:7-10`), que habilita **Block List Project Phishing + Block List Project Scam**, com o preset de resolvedor de DNS do aparelho (`resolverPresetID = DNSResolverPreset.device.id`) e o fallback para o DNS do aparelho ligado.

Esse padrão gratuito é **produzido por `defaultEnabled`**, não fixado no código. `blockListProjectPhishing` (`BlocklistModels.swift:139`) e `blockListProjectScam` (`BlocklistModels.swift:148`) ambos definem `defaultEnabled: true`, e `DefaultCatalog.recommendedDefaultSourceIDs` (`BlocklistModels.swift:250-252`) é derivado de `curatedSources.filter(\.defaultEnabled)`. O comentário no código (`BlocklistModels.swift:246-249`) chama `defaultEnabled` de "a única fonte da verdade para o padrão de instalação nova", espelhando a coluna `default_enabled` do catálogo do backend. Fluindo por `recommendedDefaultSourceIDs` até `OnboardingDefaults`, `defaultEnabled` é o mecanismo vivo — basta virar a flag em uma fonte para mudar o padrão.

> **Fonte da verdade do padrão (o código prevalece).** Qualquer texto de plano/catálogo que diga "Block List Basic é o único padrão" está errado para o aparelho; o aparelho entrega Phishing + Scam a partir de `defaultEnabled: true`, e a flag `BlocklistSource.defaultEnabled` do iOS é o mecanismo vivo e autoritativo. A coluna `default_enabled` do catálogo do backend foi realinhada ao mesmo conjunto Phishing + Scam por uma migração, então os metadados servidos por `/v1/catalog` agora coincidem com o cliente. O texto do site público "Listas de bloqueio habilitadas 3 → 10" ainda está **desatualizado** — o gate real é o orçamento de regras de filtro de 500 mil/2 milhões, não uma contagem de listas.

### 5.4 Modelo de distribuição GPL baseado apenas em source-url (Implementado)

**Source-url-only** é o modelo de distribuição de conformidade com GPL/PI: a Lava publica apenas a URL upstream + os hashes aceitos; o aparelho busca e processa as listas por conta própria. A Lava **nunca** armazena, espelha, transforma ou serve os bytes de listas de bloqueio de terceiros. Isso **substituiu o abandonado design de espelho em R2** (o plano original de "espelho R2 bruto" foi revertido em 25/05/2026).

No lado do Worker, `syncOneBlocklist` busca cada fonte upstream e a normaliza+hasheia (calculando `source_hash`, `normalized_hash`, `entry_count`), mas grava `raw_r2_key = null` / `normalized_r2_key = null` — apenas os metadados JSON do catálogo chegam ao R2. `check-gpl-blocklist-distribution.sh` é a barreira de CI que faz cumprir o modelo inteiro: nenhum código de espelho/transformação, nenhuma URL de artefato/download da Lava, nenhuma fonte GPL habilitada por padrão, nenhuma gravação no R2 dos bytes de lista pelo Worker, nenhum texto de "espelho hospedado pela Lava", nenhum `.txt`/`.json` GPL embarcado, e `source_url_only` obrigatório nas migrações + documentos jurídicos.

> **Nota sobre licenças:** o código de primeira parte da Lava é distribuído sob **AGPL-3.0** (o arquivo `LICENSE` é a GNU AGPL v3, condizente com o selo no README). As listas de bloqueio de terceiros (HaGeZi, OISD) permanecem sob **GPL-3.0** segundo suas próprias licenças upstream — o modelo source-url-only existe justamente para que a Lava possa usá-las sem nunca redistribuir bytes licenciados sob GPL. GPL-3.0 aqui é uma propriedade das listas upstream, não do app da Lava.

---

## 6. Resumo de status

| Área | Status |
|---|---|
| Precedência de consultas DNS (bootstrap > pause > filter) | Implementado |
| Precedência de decisão de filtragem (guardrail > allowlist > blocklist > default-allow) | Implementado |
| Espaço de precedência da proteção contra ameaças (conectado; ainda entregue sem entradas) | Implementado |
| DoH / DoH3 (rótulo h3 observacional) | Implementado |
| DoT (pool de 4/endpoint, renovação após 8s de ociosidade, uma nova tentativa) | Implementado |
| DoQ (conexão nova por consulta, concorrência de 4 lanes) | Implementado |
| Reuso de conexão DoQ | Descartado / adiado para o piso iOS 26 |
| Degradação do resolvedor + failover por endpoint + fallback para DNS do aparelho | Implementado |
| Orçamento de regras de filtro (Gratuito 500 mil / Plus 2 milhões) | Implementado |
| Proteção do aparelho de ~3,26 milhões de regras (alvo de 32 MB sob o teto de 50 MiB do NE) | Implementado |
| mmap com zero cópia do snapshot compacto | Implementado |
| Catálogo source-url-only + busca direta no upstream + validação de hash | Implementado |
| Filtro de domínios protegidos | Implementado |
| Padrão gratuito = Phishing + Scam (não Basic) | Implementado (catálogo realinhado para coincidir) |
| Licença do código de primeira parte da Lava | AGPL-3.0 (`LICENSE`); listas de terceiros seguem GPL-3.0 upstream |

---

## Veja também

- [`../product/overview.md`](../product/overview.md) — descrição do produto em uma linha, promessa de privacidade, abas.
- Planos e monetização (referência interna) — Lava Security Plus e o orçamento de regras de filtro como métrica de plano.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — a decisão de conformidade source-url-only.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licenças e atribuições das listas de bloqueio/resolvedores upstream.
