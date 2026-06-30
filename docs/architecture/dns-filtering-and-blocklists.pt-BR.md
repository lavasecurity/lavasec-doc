---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Filtragem de DNS e Listas de Bloqueio

> Público-alvo: engenheiros. Este documento descreve o pipeline de DNS no dispositivo, o caminho do resolvedor de transporte criptografado, o mecanismo de decisão de filtragem e o modelo de catálogo de listas de bloqueio source-url-only — com os números precisos que o código impõe. O status reflete a realidade confirmada pelo código. Onde um plano e o código divergem, **o código vence** e a divergência é destacada no texto.

Toda a filtragem de DNS acontece no dispositivo; a Lava nunca roteia sua navegação por seus servidores e nunca recebe o fluxo de domínios que você visita — o backend mantém apenas metadados de catálogo, um backup criptografado opaco por usuário e diagnósticos anonimizados que você opta por enviar.

A Lava é **filtragem local de DNS/listas de bloqueio**, não uma garantia de que todo domínio ou URL malicioso seja bloqueado.

---

## 1. O pipeline de DNS (Implementado)

O mecanismo de filtragem/resolução roda dentro do **NE / túnel de pacotes** — a extensão `NEPacketTunnelProvider` `LavaSecTunnel` (`com.lavasec.app.tunnel`), que intercepta apenas DNS. Os endereços do túnel são `10.255.0.2` (túnel) e `10.255.0.1` (servidor DNS). O processo do aplicativo nunca vê o tráfego de consultas; ele apenas grava artefatos compilados no **App Group** (`group.com.lavasec`) e sinaliza o túnel por meio de **provider messages** do NETunnelProviderSession (não notificações Darwin).

Para cada consulta DNS de entrada, o túnel executa uma **precedência de consulta** fixa em `DNSQueryDispatcher` (`Sources/LavaSecCore/DNSQueryDispatcher.swift`):

```
resolver bootstrap  >  temporary pause  >  filter (block / allow)
```

- **bootstrap-first é um invariante rígido.** Uma consulta que resolve o *próprio* nome de host do resolvedor configurado (o endpoint DoH/DoT/DoQ) nunca deve ser bloqueada ou pausada, ou o túnel não conseguiria sequer estabelecer o DNS criptografado. O dispatcher recebe closures preguiçosos para que cada etapa seja lida somente quando alcançada, preservando o curto-circuito (sem leitura de snapshot quando existe uma resposta de bootstrap; sem leitura de pausa durante o bootstrap).
- **temporary pause** encaminha upstream enquanto um TTL de pausa iniciado pelo usuário está ativo.
- **filter** avalia o domínio contra o snapshot compilado e o encaminha ou sintetiza uma resposta bloqueada.

Uma consulta que passa pelo filtro (ação `.allow`) é entregue ao caminho do resolvedor (§3). O túnel **falha fechado** na partida a frio sem um snapshot reutilizável: ele instala um snapshot de runtime fail-closed que bloqueia todo o tráfego em vez de resolver sem filtragem.

---

## 2. O mecanismo de filtragem (Implementado)

### 2.1 Precedência de decisão

`FilterSnapshot.decision(forNormalizedDomain:)` (`Sources/LavaSecCore/FilterSnapshot.swift:57-71`) aplica a precedência canônica de segurança:

```
threat guardrail  >  local allowlist (allowed exceptions)  >  blocklist  >  default-allow
```

| Ordem | Conjunto de regras | Resultado | `FilterDecisionReason` |
|---|---|---|---|
| 1 | `nonAllowableThreatRules` | block | `.threatGuardrail` |
| 2 | `allowRules` | allow | `.localAllowlist` |
| 3 | `blockRules` | block | `.blocklist` |
| 4 | — | allow | `.defaultAllow` |

Um domínio que falha na normalização é bloqueado com o motivo `.invalidDomain` (fail-safe). A mesma precedência é espelhada na forma binária em disco (`CompactFilterSnapshot`). A guarda contra ameaças fica acima da allowlist local por design: **o pagamento nunca contorna a guarda contra ameaças não permissíveis**, e uma exceção do usuário não pode desbloquear um domínio da guarda.

> Nota: na árvore de trabalho atual, `nonAllowableThreatRules` / `guardrailSources` estão vazios (`DefaultCatalog.guardrailSources = []`, `BlocklistModels.swift:254`); o slot de precedência está conectado e imposto, mas ainda é distribuído sem entradas de guarda.

### 2.2 Armazenamento de regras e a unidade de memória residente

`DomainRuleSet` (`Sources/LavaSecCore/DomainRuleSet.swift`) armazena os conjuntos `exactDomains` + `suffixDomains`. A correspondência (`containsNormalized`) faz uma busca exata mais uma varredura de sufixo pai (no estilo `hasSuffix`) no momento da consulta — **não há subsunção de subdomínio em tempo de compilação**. Uma linha curinga válida é **uma regra** e uma entrada na tabela de memória. Essa identidade 1-linha = 1-regra é o que torna a contagem de regras a métrica honesta de recursos (§4).

### 2.3 Formas de snapshot compilado

- **`FilterSnapshot`** — o filtro compilado em memória: `blockRules`, `allowRules`, `nonAllowableThreatRules` e o preset do resolvedor.
- **`CompactFilterSnapshot`** — a forma binária, amigável a mmap, em disco, que o túnel de fato lê (magic `LSCFSNP1`, `fileVersion 1`). Ela é carregada zero-copy via mmap (§4.3).

O aplicativo grava tanto `filter-snapshot.json` quanto `filter-snapshot.compact` no App Group; o túnel decodifica o artefato compacto. Um caminho de **reuso na partida quente** (`FilterArtifactStore`) permite que o túnel reutilize o artefato compacto em disco sem recompilar, condicionado por uma impressão digital de identidade + um manifesto gravado atomicamente; o reuso é rejeitado (privacy-safe, motivo apenas com nome de campo) quando o transporte do resolvedor, a cobertura do catálogo ou as entradas do snapshot mudam.

---

## 3. Transportes criptografados e o caminho do resolvedor (Implementado)

### 3.1 Enum de transporte

Consultas desbloqueadas são encaminhadas ao resolvedor upstream configurado. `DNSResolverTransport` (`Sources/LavaSecCore/DNSResolverPreset.swift:6-11`) tem **cinco** valores:

| Transporte | Valor bruto | Anotação exibida na UI |
|---|---|---|
| Device DNS | `device-dns` | *(nenhuma — o nome é o transporte)* |
| Plain DNS | `plain-dns` | `IP` |
| DNS-over-HTTPS | `dns-over-https` | `DoH` / `DoH3` |
| DNS-over-TLS | `dns-over-tls` | `DoT` |
| DNS-over-QUIC | `dns-over-quic` | `DoQ` |

Os presets integrados são Google, Cloudflare, Quad9, Mullvad (cada um nas variantes IP / DoH / DoT) mais Device DNS e Custom. Resolvedores personalizados aceitam um servidor IPv4/IPv6 simples, uma URL DoH, uma URL DoT (`tls://` / `dot://`), uma URL DoQ (`doq://` / `quic://`) ou um DNS stamp `sdns://`; nomes de usuário/senhas e localhost são rejeitados. DoT/DoQ usam a porta `853` por padrão; DoH exige um caminho.

### 3.2 DoH / DoH3

`DoHTransport` (`Sources/LavaSecCore/DoHTransport.swift`) executa DoH sobre `URLSession`. Toda requisição opta por HTTP/3 (`request.assumesHTTP3Capable = true`, `DNSOverHTTPSRequest.swift:29`); o loader da Apple faz fallback nativo para H2/H1, então isso nunca torna inalcançável um resolvedor alcançável. O protocolo negociado é lido de `URLSessionTaskTransactionMetrics.networkProtocolName` (ALPN: `h3`, `h2`, `http/1.1`).

A UI anota **`DoH3` (sem barra)** — por exemplo, "Quad9 (DoH3)" — **somente quando uma negociação h3 é de fato observada** (`DoHHTTPVersion.dohAnnotation`); caso contrário, mostra `DoH`. DoH3 é preferido, nunca prometido: o rótulo é observacional e com escopo de resolvedor, nunca persistido (o carry-over de "confirmed DoH3" entre reinicializações foi revertido). As requisições fazem POST de `application/dns-message`; as respostas têm content-type e comprimento validados e o ID de transação é restaurado antes da gravação de volta.

### 3.3 DoT

`DoTTransport` (`Sources/LavaSecCore/DoTTransport.swift`) usa `NWConnection`s em pool, **até 4 conexões por endpoint** (`maxConnectionsPerEndpoint = 4`), round-robin, para que consultas paralelas evitem bloqueio head-of-line. Ele inclui o tratamento de **idle-staleness**: provedores como Cloudflare fecham conexões DoT ociosas do lado do servidor (~10s) sem expor uma mudança de estado, então uma conexão reutilizada ociosa por mais de **8 segundos** (`reusedConnectionMaxIdleInterval = 8`) é renovada antes do envio, e um timeout em uma conexão reutilizada ganha **exatamente uma nova tentativa com conexão nova**.

### 3.4 DoQ — conexão nova por consulta

`DoQTransport` (`Sources/LavaSecCore/DoQTransport.swift`) mantém um pool limitado de **4 vias por endpoint**, mas **cada consulta abre uma conexão QUIC nova** — um handshake completo por consulta. O pool de 4 vias fornece **concorrência, não reuso de handshake**.

**Status de reuso de conexão DoQ (Descartado / adiado).** O reuso foi revisado e medido em dispositivo (34 handshakes novos em 35 consultas ≈ sem reuso), depois implementado como um caminho `NWConnectionGroup` multi-stream condicionado ao iOS 26, testado em dispositivo contra DoQ da AdGuard e **revertido como saldo negativo** (falhas de stream + erros de fallback contra um servidor real). A RFC 9250 mapeia cada consulta para seu próprio stream QUIC, então o reuso exige `NWConnectionGroup`/`openStream`, que é **apenas iOS 26.0+**; o piso de implantação atual é **iOS 17**. O reuso fica adiado até o piso chegar ao iOS 26. DoQ personalizado é rejeitado em dispositivos que não o suportam ("DNS over QUIC is not supported on this device").

### 3.5 Política de resolução

`ResolverOrchestrator` (`Sources/LavaSecCore/ResolverOrchestrator.swift`) é dono da política de upstream:

1. **Roteamento de transporte** pelo transporte configurado.
2. **Degradação para plain DNS** quando um plano criptografado não tem endpoints.
3. **Failover por endpoint** com um gate de backoff — um endpoint em backoff nunca toca a rede (resultado `backed-off`).
4. **Fallback para Device-DNS** quando o primário não retorna resposta *e* o plano permite (a propriedade do plano é `shouldFallbackToDeviceDNS`, derivada do campo de configuração `fallbackToDeviceDNS`); o resultado é reanotado como o transporte de dispositivo. A execução na rede é injetada por trás de executores para que a política seja testável por unidade; o estado de backoff fica fora da política pura.

---

## 4. Orçamento de regras de filtro, teto do NE e mmap

A métrica de tier distribuída é o **orçamento de regras de filtro**: o total de **regras** de domínio compiladas que um usuário pode habilitar. Isso substituiu o antigo limite de **contagem** de listas habilitadas (free 3 / pago 10), que era um proxy desonesto — uma lista pode ter 1K ou 1M de regras. Há **duas camadas**: uma guarda de dispositivo para todos, e um limite de monetização por tier abaixo dela.

### 4.1 Limites de tier (Implementado)

`FeatureLimits` (`Sources/LavaSecCore/SubscriptionPolicy.swift:29-45`) é a fonte da verdade:

| Tier | `maxFilterRules` | `maxAllowedDomains` | `maxBlockedDomains` | Listas de bloqueio / DNS personalizados |
|---|---|---|---|---|
| **Free** | **500,000** | 25 | 25 | Não |
| **Plus** (`.paid` / `.plus`) | **2,000,000** | 1,000 | 1,000 | Sim |

O limite de tier é uma fronteira de monetização, **nunca um paywall sobre a guarda do dispositivo**. O **Lava Security Plus** desbloqueia apenas a personalização — nunca a segurança básica, nunca a guarda contra ameaças. Listas de bloqueio personalizadas (pagas) são buscadas diretamente do dispositivo do usuário, processadas e armazenadas em cache localmente, e nunca passadas por proxy aos servidores da Lava.

### 4.2 Guarda de memória do dispositivo + teto do NE (Implementado)

O túnel de pacotes está sujeito ao **teto de memória de ~50 MiB por extensão** do iOS (um limite de design por tipo de extensão do SO para túneis de pacotes desde o iOS 15, não escalonado por RAM; ele reside em um `com.apple.jetsamproperties.{Model}.plist` por modelo de dispositivo e pode ser menor em dispositivos mais antigos). Excedê-lo dispara o jetsam. Não há API para o teto, então o orçamento mantém margem abaixo do precipício.

`FilterSnapshotMemoryBudget` (`Sources/LavaSecCore/FilterSnapshotMemoryBudget.swift:30-55`) faz a conta, denominada em regras de filtro (block + allow + guardrail):

| Constante | Valor |
|---|---|
| `baselineMegabytes` | 4.0 MB (overhead fixo de processo, medido ≈3,5 MB, arredondado para cima) |
| `estimatedBytesPerRule` | 9.0 B residentes sujos por regra (medido ≈8,5 B, arredondado para cima) |
| `maxResidentMegabytes` | 32.0 MB (teto-alvo, deixando ~10 MB de folga abaixo do precipício de jetsam observado de ~40–46 MB) |
| **`maxFilterRuleCount`** | **((32 − 4) × 1.048.576) / 9 = 3.262.236 regras** |

Essa **guarda de dispositivo de ~3,26M regras** é o piso rígido de segurança para *cada* usuário, situada acima de qualquer tier de assinatura, e **nunca é um paywall**. Medição de âncora (dispositivo "chimmy", 2026-06-13): **789.831 regras → 9,9 MB de `phys_footprint`**, ou seja, ≈ baseline + custo por regra.

### 4.3 Estratégia de mmap (Implementado)

O snapshot compacto é carregado com `Data(contentsOf:options:[.mappedIfSafe])` (`LavaSecTunnel/PacketTunnelProvider.swift:4431`, `:4665`), e `CompactBinaryReader` retorna fatias zero-copy. O blob de texto de domínio de vários megabytes permanece **file-backed/limpo** e é excluído do `phys_footprint` contado pelo jetsam; apenas as tabelas `[Entry]` decodificadas custam memória residente (~6 B/regra em disco, ~8,5 B residentes sujos). Isso eleva o teto de domínios no dispositivo: o custo residente são as tabelas de entrada, não o artefato inteiro.

### 4.4 Imposição em duas camadas (Implementado)

- **Autoritativa (tempo de compilação).** `FilterSnapshotPreparationService` (`Sources/LavaSecCore/FilterSnapshotPreparationService.swift:146-176`) impõe o orçamento sobre a **união deduplicada** de todas as listas habilitadas. A guarda do dispositivo é verificada **primeiro** (o piso rígido); o limite de tier vincula abaixo dela. Configurações acima do orçamento são rejeitadas deterministicamente — `exceedsDeviceMemoryBudget` ou `exceedsTierFilterRuleLimit` — em vez de deixar o túnel sofrer jetsam. O erro nomeia as duas maiores listas contribuintes para que a correção seja óbvia.
- **Consultiva (UI em tempo de seleção).** `FilterRuleBudget` (`Sources/LavaSecCore/FilterRuleBudget.swift:8-26`) alimenta o medidor de seleção usando uma **soma** por lista com uma **margem de teto suave de 1,10** que compensa a sobrecontagem cruzada entre listas de ~7–10% (a soma por lista superestima a união deduplicada).

### 4.5 O parser (Implementado)

`BlocklistParser` (`Sources/LavaSecCore/BlocklistParser.swift`) conta regras literalmente: ele descarta comentários/linhas em branco/linhas inválidas, normaliza, deduplica strings exatas dentro de uma lista (via um `Set`), e limita em **`maxRules = 1,000,000`** por lista (padrão), com comprimento máximo de linha de 4.096 caracteres. Formatos suportados: `auto`, `plainDomains`, `hosts`, `adblock`, `dnsmasq` (auto tenta hosts → dnsmasq → adblock → plain). Uma linha válida = uma regra = a unidade de memória.

> **Linhas `hosts` multi-host (parser rules version 2).** Uma linha `hosts` que mapeia um IP para vários hosts (`0.0.0.0 a.com b.com c.com`) agora emite **cada** host como sua própria regra, não apenas o primeiro; `maxRules` é imposto **por regra** (não por linha), de modo que uma linha multi-host perto do limite não pode ultrapassar. Como os mesmos bytes upstream agora podem gerar mais regras, a versão de regras do parser foi elevada de **1 → 2**, invalidando entradas obsoletas de `RuleSetCache` processadas sob o antigo comportamento de apenas o primeiro host.

### 4.6 Robustez de download e decodificação (Implementado)

O túnel e a sincronização de catálogo rodam dentro do orçamento de memória do NE, então a ingestão de listas é endurecida contra entradas hostis ou malformadas:

- **Downloads em streaming.** `defaultDataFetcher` baixa os bytes da lista para um arquivo temporário via `URLSession.download` (memória de pico limitada) com uma verificação de tamanho pós-download (`maximumBlocklistBytes`) em vez de bufferizar todo o corpo em RAM; um corpo de tamanho excessivo levanta `BlocklistDownloadSizeLimitExceeded`.
- **Limite de metadados de catálogo (8 MB).** `BlocklistCatalogRepository.maximumCatalogBytes` rejeita um catálogo remoto de tamanho excessivo antes da decodificação, de modo que um host hostil/MITM não pode forçar uma decodificação JSON com OOM na extensão.
- **Decodificação UTF-8 leniente.** Um único byte UTF-8 inválido não rejeita mais uma lista inteira (o que, sob fail-closed, bloquearia todo o DNS); bytes inválidos viram U+FFFD e apenas a linha ofensora falha na validação por linha e é descartada.
- **Erros nomeados de lista de bloqueio personalizada.** Uma lista personalizada com falha agora expõe `customBlocklistUnavailable(displayName:reason:)` — "Couldn't load the custom blocklist '<name>'. <why>" — em vez de um `URLError` cru; o cancelamento é propagado como cancelamento, não como falha de download.

---

## 5. Catálogo de listas de bloqueio e fontes padrão

### 5.1 Modelo de catálogo (Implementado)

O **catálogo de listas de bloqueio** é a lista publicada de fontes disponíveis. O **Worker lavasec-api** serve metadados JSON de um bucket R2 em `GET /v1/catalog` (e `/v1/catalog/:version`); o dispositivo busca os **bytes** reais da lista diretamente de cada `source_url` upstream. Os endpoints de catálogo do iOS são `https://api.lavasecurity.app/v1/catalog` (`BlocklistCatalogSync.swift:4-15`).

No dispositivo, `BlocklistCatalogSynchronizer` (`BlocklistCatalogSync.swift`):

1. Busca os bytes da lista diretamente de `source.sourceURL`, impondo um limite de tamanho.
2. Calcula o SHA-256 e aceita os bytes somente se o checksum estiver em `accepted_source_hashes` do catálogo.
3. Em caso de incompatibilidade, faz fallback para o último cache local válido, ou **falha fechado** (`checksumMismatch`) — a menos que a fonte permita explicitamente rotação direta de upstream.
4. Processa/normaliza/deduplica localmente.
5. Filtra cada conjunto de regras processado por `DomainRuleSet.lavaSecProtectedDomains` (`AppConfiguration.swift:262-276`) para que uma lista upstream nunca possa bloquear domínios da Lava/Apple/provedor de identidade.

O **conjunto de domínios protegidos** (filtrado antes da ativação): `apple.com`, `icloud.com`, `mzstatic.com`, `itunes.apple.com`, `apps.apple.com`, `lavasecurity.com`, `lavasecurity.app`, `api.lavasecurity.app`, `lavasec.app`, `lavasec.example`, `accounts.google.com`, `google.com` (todos correspondidos por sufixo). O Worker aplica um filtro `PROTECTED_SUFFIXES` equivalente ao computar os metadados; o dispositivo revalida de qualquer forma.

### 5.2 Fontes curadas (Implementado)

`DefaultCatalog.curatedSources` é gerado a partir do [Blocklist Catalog](../legal/blocklist-catalog.md) canônico, atualmente **32** fontes em sete categorias: Security & Threat Intel, Multi-purpose, Ads & Trackers, Social Media, Adult Content, Gambling e Piracy & Torrent. As famílias de fontes incluem The Block List Project, Phishing.Database, HaGeZi, OISD, StevenBlack, AdGuard e 1Hosts.

`guardrailSources` está vazio. Fontes GPL (HaGeZi, OISD, AdGuard) são visíveis no catálogo, mas **opt-in / DESLIGADAS por padrão**; o Worker condiciona a sincronização/publicação de lançamento a `source_url_only` mais os prefixos GPL liberados (`hagezi-`, `oisd-`, `adguard-`).

### 5.3 Listas habilitadas por padrão para usuários free (Implementado)

A configuração padrão free é `OnboardingDefaults.lavaRecommendedDefaults`, que habilita o **Block List Basic** — uma lista combinada ampla e licenciada de forma permissiva (ads + tracking + malware + phishing/scam) — com o preset de resolvedor device-DNS (`resolverPresetID = DNSResolverPreset.device.id`) e o fallback criptografado de Device-DNS **ligado** (`usesEncryptedDeviceDNSFallback = true`), roteando para **Mullvad DoH** (`fallbackResolverPresetID = DNSResolverPreset.mullvadDoH.id`): se o próprio DNS do dispositivo travar, as buscas permitidas são transportadas transitoriamente sobre Mullvad DoH e depois voltam ao DNS do dispositivo automaticamente. (O inicializador `AppConfiguration()` puro deixa esse fallback **desligado** por padrão — ele só é habilitado ao aceitar os padrões recomendados de onboarding.) Isso substitui o par anterior Block List Project Phishing + Scam: a cobertura combinada do Basic os subsume, e ambos permanecem como listas opt-in selecionáveis.

Esse padrão free é **produzido por `defaultEnabled`**, não codificado. `blockListProjectBasic` define `defaultEnabled: true`, e `DefaultCatalog.recommendedDefaultSourceIDs` é derivado de `curatedSources.filter(\.defaultEnabled)`. `defaultEnabled` é "a única fonte da verdade para o padrão de instalação nova", espelhando a coluna `default_enabled` do catálogo do backend. Fluindo por `recommendedDefaultSourceIDs` até `OnboardingDefaults`, ele é o mecanismo vivo — vire a flag em uma fonte para mudar o padrão.

> **Fonte da verdade do padrão (uma spec gerada).** O catálogo é gerado a partir de uma única spec canônica ([Blocklist Catalog](../legal/blocklist-catalog.md)) que produz tanto o `DefaultCatalog` do iOS quanto o seed do backend, de modo que o dispositivo e os metadados servidos em `/v1/catalog` concordam por construção. O padrão de instalação nova é o **Block List Basic**, a partir de sua flag `defaultEnabled: true`. O verdadeiro gate de tier é o orçamento de regras de filtro de 500K/2M, não uma contagem de listas.

### 5.4 Modelo de distribuição GPL source-url-only (Implementado)

**Source-url-only** é o modelo de distribuição de conformidade GPL/IP: a Lava publica apenas a URL upstream + os hashes aceitos; o dispositivo busca e processa as listas por conta própria. A Lava **nunca** armazena, espelha, transforma ou serve bytes de listas de bloqueio de terceiros. Isso **substituiu o abandonado design de espelho R2** (o plano original de "raw R2 mirror" foi revertido em 2026-05-25).

No lado do Worker, `syncOneBlocklist` busca cada fonte upstream e a normaliza+faz hash (computando `source_hash`, `normalized_hash`, `entry_count`), mas grava `raw_r2_key = null` / `normalized_r2_key = null` — apenas os metadados JSON do catálogo chegam ao R2. `check-gpl-blocklist-distribution.sh` é a guarda de CI que impõe todo o modelo: nenhum código de espelho/transformação, nenhuma URL de artefato/download da Lava, nenhuma fonte GPL habilitada por padrão, nenhuma gravação no R2 do Worker de bytes de listas, nenhuma cópia de "espelho hospedado pela Lava", nenhum `.txt`/`.json` GPL embutido, e `source_url_only` obrigatório nas migrações + documentos legais.

> **Nota de licença:** o código próprio da Lava é distribuído sob **AGPL-3.0** (o arquivo `LICENSE` é GNU AGPL v3, correspondendo ao badge do README). As listas de bloqueio de terceiros (incluindo HaGeZi, OISD e AdGuard) permanecem sob suas próprias licenças upstream — o modelo source-url-only existe precisamente para que a Lava possa usá-las sem nunca redistribuir bytes de listas copyleft. GPL-3.0 aqui é uma propriedade das listas upstream, não do aplicativo Lava.

---

## 6. Resumo de status

| Área | Status |
|---|---|
| Precedência de consulta DNS (bootstrap > pause > filter) | Implementado |
| Precedência de decisão de filtro (guardrail > allowlist > blocklist > default-allow) | Implementado |
| Slot de precedência da guarda contra ameaças (conectado; distribuído ainda sem entradas) | Implementado |
| DoH / DoH3 (rótulo h3 observacional) | Implementado |
| DoT (pool de 4/endpoint, refresh de ociosidade de 8s, uma nova tentativa com conexão nova) | Implementado |
| DoQ (conexão nova por consulta, concorrência de 4 vias) | Implementado |
| Reuso de conexão DoQ | Descartado / adiado para o piso iOS-26 |
| Degradação de resolvedor + failover por endpoint + fallback de device-DNS | Implementado |
| Orçamento de regras de filtro (Free 500K / Plus 2M) | Implementado |
| Guarda de dispositivo de ~3,26M regras (alvo de 32 MB abaixo do teto NE de 50 MiB) | Implementado |
| mmap zero-copy do snapshot compacto | Implementado |
| Catálogo source-url-only + busca direta de upstream + validação de hash | Implementado |
| Filtro de domínio protegido | Implementado |
| Padrão free = Block List Basic | Implementado (catálogo gerado + projeções iOS/backend concordam) |
| Licença do código próprio da Lava | AGPL-3.0 (`LICENSE`); listas de terceiros permanecem GPL-3.0 upstream |

---

## Veja também

- [`../product/overview.md`](../product/overview.md) — frase de resumo do produto, promessa de privacidade, abas.
- Tiers e monetização (referência interna) — Lava Security Plus e o orçamento de regras de filtro como a métrica de tier.
- [`../legal/gpl-source-url-only-compliance-decision.md`](../legal/gpl-source-url-only-compliance-decision.md) — a decisão de conformidade source-url-only.
- [`../legal/third-party-notices.md`](../legal/third-party-notices.md) — licenças e atribuições de listas de bloqueio/resolvedores upstream.
