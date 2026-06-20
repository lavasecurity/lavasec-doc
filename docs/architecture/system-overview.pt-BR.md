---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Visão geral do sistema

> **Público:** pessoas da engenharia. Esta é toda a Lava Security em uma única página — quais são as partes, como os dados se movem entre elas e onde ficam os limites de confiança. As páginas de cada componente vão mais fundo; esta existe para que você consiga ter o sistema todo na cabeça antes de lê-las.
>
> **Autoridade:** quando este documento e um plano discordarem, **o código vence**. O status reflete a realidade confirmada pelo código, não a aspiração do plano. Veja a [Legenda de status](#8-legenda-de-status) no final.

## 1. Resumo do produto em uma frase

A Lava Security é um app de iOS que coloca a privacidade em primeiro lugar e filtra DNS **localmente no dispositivo** por meio de um túnel de pacotes da NetworkExtension, bloqueando domínios maliciosos e indesejados para pessoas não técnicas (mães e pais, pessoas mais velhas) — com a proteção essencial gratuita para sempre e sem precisar de conta.

## 2. A promessa de privacidade (canônica)

> Toda a filtragem de DNS acontece no dispositivo; a Lava nunca encaminha sua navegação pelos servidores dela e nunca recebe a sequência de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado e opaco por usuário e diagnósticos anonimizados que você escolhe enviar.

Tudo o que vem abaixo serve para manter essa frase verdadeira. A arquitetura é propositalmente pequena no lado do servidor: o dispositivo faz o trabalho, e o backend nunca vê uma consulta.

## 3. Componentes

### Cliente iOS (três alvos executáveis + código compartilhado, um App Group `group.com.lavasec`)

| Componente | Bundle / local | Função | Status |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Casca do app em SwiftUI; ponto de entrada, navegação em duas abas Guard + Configurações (Filtros/Atividade são telas de detalhe do Guard). | Implementado |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; o mecanismo de filtragem/resolução de DNS no dispositivo. Sujeito ao **teto de memória de ~50 MiB por extensão** do iOS. | Implementado |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity do WidgetKit (tela de bloqueio + Dynamic Island). | Implementado |
| **Shared/** | `Shared/` | Fontes usadas por vários alvos: App Group, serviço de comandos, mascote, atributos/intents da Live Activity. | Implementado |

**Controladores do lado do app (em LavaSecApp):**

- **AppViewModel** — o controlador do lado do app (objeto-deus): cuida do ciclo de vida do `NETunnelProviderManager`, da persistência do estado compartilhado, das mensagens para o provider, da reconciliação da Live Activity, da sincronização do catálogo, do backup, do StoreKit e da autenticação.
- **RootView** — `TabView` de duas abas (Guard + Configurações), com Filtros e Atividade acessados como telas de detalhe dentro do Guard; controla a apresentação do onboarding e hospeda as sobreposições de bloqueio de segurança / máscara de privacidade.
- **SecurityController** — código de acesso (SHA256 com sal no Keychain) + biometria + proteção por superfície.
- **LavaLiveActivityController** — reconciliador de Activity única, com remoção de duplicatas e controle por revisão.
- **OnboardingFlowView** — fluxo de várias páginas para a primeira execução (6 páginas: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (pacote SwiftPM independente de plataforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — filtro compilado + precedência de decisão; a forma compacta é o artefato em disco, amigável a mmap, que o túnel lê.
- **DNSQueryDispatcher** — precedência de consulta: bootstrap > pausa > filtro.
- **ResolverOrchestrator** — roteamento de transporte, degradação para DNS simples, failover por endpoint, fallback para o DNS do dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — executores de transporte criptografado.
- **FeatureLimits** (em `SubscriptionPolicy.swift`) — tetos de cada plano (fonte da verdade), via os membros estáticos `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — cálculo de proteção do dispositivo + aplicação definitiva do orçamento após a união.
- **BlocklistCatalogSync / BlocklistParser** — busca do catálogo, download direto da origem, análise/normalização/remoção de duplicatas local, filtro de domínios protegidos.
- **GuardianMascotAnimation** — grafo de estados do mascote com 7 estados (renderizado por `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — criptografia + payload do backup.
- **SupabaseIDTokenAuth** — autenticação `id_token` com URLRequest bruto (sem SDK).

### Backend

| Componente | Função | Status |
|---|---|---|
| **Worker lavasec-api** | Cloudflare Worker (`api.lavasecurity.app`): leituras do catálogo, sincronização e publicação da blocklist via admin/cron, relatórios de bug anônimos, exclusão de conta, espelhamento de direitos da App Store, sondas de QA. | Implementado |
| **Worker lavasec-email** | Encaminhador apenas de recebimento do Cloudflare Email Routing para `@lavasecurity.app`; recusa mensagens desconhecidas/grandes demais. | Implementado |
| **Supabase Postgres** | Contas, `user_backups`, metadados do catálogo, tabelas exclusivas do service-role; **RLS em toda tabela pública**. | Implementado |
| **Cloudflare R2** (o bucket R2 de produção, com um bucket de preview separado para staging) | Snapshots do catálogo + o cursor de sincronização em rodízio. **Nunca** os bytes da blocklist de terceiros; a rota de upload de anexos de relatórios de bug foi removida (objetos legados só são apagados na exclusão da conta). | Implementado |
| **Cloudflare D1** (o banco de dados de feedback da ajuda) | Votos de feedback anônimos sobre artigos de ajuda, apenas com inserção. | Implementado |

## 4. Diagrama de fluxo de dados

A propriedade mais importante de todas: **o caminho do resolvedor de DNS criptografado (lado direito) nunca toca o backend da Lava (parte de baixo).** O dispositivo busca os *metadados* do catálogo no Worker, mas os *bytes* das listas e a própria sequência de consultas vão direto para terceiros.

```
                                  SEU iPHONE
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                                                                             │
 │   ┌──────────────┐   provider messages    ┌───────────────────────────┐    │
 │   │  LavaSecApp  │ ─────────────────────►  │      LavaSecTunnel        │    │
 │   │ (AppViewModel│   (reload-snapshot /    │  (NEPacketTunnelProvider) │    │
 │   │  controller) │    pause / config)      │                           │    │
 │   └──────┬───────┘                         │   DNSQueryDispatcher       │   │
 │          │                                 │   bootstrap > pause >      │   │
 │          │ writes / reads                  │   ┌──────────────────────┐ │   │
 │          ▼                                 │   │  CompactFilterSnapshot│ │   │
 │   ┌──────────────────────────┐  mmap       │   │  guardrail > allow >  │ │   │
 │   │  App Group container      │ ◄──(read)── │   │  block > default-allow│ │   │
 │   │  group.com.lavasec        │            │   └──────────┬───────────┘ │   │
 │   │  • filter-snapshot.compact│            │              │ allowed     │   │
 │   │  • app-configuration.json │            │              ▼             │   │
 │   │  • tunnel-health.json      │           │   ┌──────────────────────┐ │   │
 │   │  • pause/session UserDefs  │           │   │  ResolverOrchestrator│ │   │
 │   └──────────────────────────┘             │   │  DoH3/DoT/DoQ/IP +   │ │   │
 │          ▲                                 │   │  device-DNS fallback │ │   │
 │          │ reads (Live Activity)           │   └──────────┬───────────┘ │   │
 │   ┌──────┴───────┐                         └──────────────│─────────────┘   │
 │   │ LavaSecWidget│                                        │                 │
 │   │ (Dynamic Isl.│                                        │ encrypted DNS   │
 │   │  + lock scr.)│                                        │ (query stream)  │
 │   └──────────────┘                                        │                 │
 └──────────────────────────────────────────────────────────│─────────────────┘
        │ (a) catalog          │ (b) list bytes              │ (c) blocked → NXDOMAIN
        │  metadata            │  (direct from upstream)     │     allowed → forwarded
        ▼                      ▼                             ▼
 ┌──────────────┐   ┌──────────────────────┐    ┌───────────────────────────────┐
 │ lavasec-api  │   │  Upstream blocklists  │   │  Public DNS resolver           │
 │ Worker       │   │  (HaGeZi, OISD,       │   │  (Quad9 / Cloudflare / Google  │
 │ GET /v1/     │   │   Block List Project) │   │   / Mullvad; user-chosen)       │
 │  catalog     │   └──────────────────────┘    └───────────────────────────────┘
 └──────┬───────┘
        │ reads/writes (metadata only)
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  LAVA BACKEND (sees no DNS queries, no browsing history)                   │
 │  • Supabase Postgres: accounts, user_backups (opaque ciphertext), catalog │
 │  • Cloudflare R2: catalog/latest.json, the round-robin cursor             │
 │  • lavasec-email Worker: receive-only @lavasecurity.app forwarding         │
 └──────────────────────────────────────────────────────────────────────────┘
       ▲
       │ (d) optional: encrypted backup envelope (PostgREST, RLS) — ciphertext only
       │     entitlement mirror, anonymous bug reports, account deletion
       └──── from LavaSecApp, only when the user opts in
```

## 5. Fluxos de dados

### A. O caminho do DNS (por consulta, tudo no dispositivo) — Implementado

Este é o caminho quente e o núcleo da privacidade. Ele roda inteiramente dentro do `LavaSecTunnel`; nada aqui chega aos servidores da Lava.

1. O túnel de pacotes intercepta uma consulta de DNS (servidor de DNS do túnel `10.255.0.1`).
2. O **`DNSQueryDispatcher`** aplica a precedência de consulta: **bootstrap > pausa > filtro**. O bootstrap em primeiro lugar é uma invariante rígida — o próprio nome do host do resolvedor é resolvido antes de qualquer filtragem, para que o resolvedor nunca consiga bloquear a si mesmo.
3. Se não for bootstrap e não estiver em pausa, o domínio é avaliado contra o **`CompactFilterSnapshot`** (carregado do App Group via mmap de cópia zero com `Data(contentsOf:options:[.mappedIfSafe])`). A precedência de decisão é **proteção contra ameaças > lista de permissões local (exceções permitidas) > blocklist > permitir por padrão**; domínios inválidos são bloqueados.
4. **Bloqueado** → o túnel responde localmente (sem contato com a origem). **Permitido** → a consulta é entregue ao **`ResolverOrchestrator`**.
5. O `ResolverOrchestrator` roteia para o transporte configurado — **`DoH3` / `DoT` / `DoQ` / DNS simples (`IP`)** — com failover por endpoint atrás de uma trava de backoff, degradação para DNS simples quando um plano criptografado não tem endpoints, e **fallback para o DNS do dispositivo** quando o primário não retorna resposta e o plano permite.
6. A resposta do resolvedor é devolvida ao sistema operacional. A sequência de consultas do usuário vai apenas para o **resolvedor público escolhido pelo usuário**, nunca para a Lava.

Notas de transporte (convenções literais): `DoH3` (sem barra) é anotado **somente quando uma negociação h3 é de fato observada** — preferido, nunca prometido. O **`DoT`** mantém um pool de até 4 NWConnections por endpoint, com renovação por inatividade + uma tentativa com conexão nova. O **`DoQ`** abre uma **conexão QUIC nova por consulta** (sem reuso); o pool de 4 vias dá concorrência, não reuso de handshake — o reuso de conexão chegou a ser construído, testado em dispositivo e **revertido** (adiado até o piso de implantação do iOS-26). Veja [Filtragem de DNS e blocklists](./dns-filtering-and-blocklists.md).

### B. Busca do catálogo + carregamento da blocklist (apenas URL de origem) — Implementado

Como as regras do filtro chegam ao dispositivo. A Lava é uma distribuidora **apenas com URL de origem**: ela publica apenas a URL da origem + os hashes aceitos e **nunca armazena, espelha, transforma ou serve os bytes da blocklist de terceiros.**

1. O dispositivo busca os **metadados** do catálogo no Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servido direto do R2 (`catalog/latest.json`), dividido em `sources[]` + `guardrails[]`, cada entrada carregando `source_url` + `accepted_source_hashes`.
2. Para cada origem habilitada, o dispositivo baixa os **bytes da lista direto de `source_url`** (a origem — HaGeZi, OISD, Block List Project etc.), e **não** da Lava.
3. O dispositivo calcula o SHA256 e só aceita os bytes cujo checksum esteja em `accepted_source_hashes`; em caso de divergência, ele recorre ao último cache válido ou falha de forma segura (`checksumMismatch`).
4. O **`BlocklistParser`** analisa/normaliza/remove duplicatas localmente (formatos auto / plain / hosts / adblock / dnsmasq), e então o **`DomainRuleSet.lavaSecProtectedDomains`** remove os domínios protegidos (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) para que uma lista de origem nunca possa bloquear domínios da Lava/Apple/provedor de identidade.
5. O **`FilterSnapshotPreparationService`** mescla a união sem duplicatas e executa a **aplicação definitiva do orçamento** (limite do dispositivo primeiro, depois o do plano), e então grava o `filter-snapshot.compact` no App Group.
6. O `AppViewModel` envia uma mensagem `reload-snapshot` ao provider; o túnel recarrega.

O lado do Worker espelha isso: a sincronização via admin/cron busca cada origem, gera o hash/contagem dela, grava `raw_r2_key = null` / `normalized_r2_key = null` e republica apenas os metadados. O modelo de catálogo de blocklists e o caminho de sincronização do backend são tratados em [Filtragem de DNS e blocklists](./dns-filtering-and-blocklists.md) e [Backend e dados](./backend-and-data.md).

**Modelo de orçamento (duas camadas):**
- **Proteção do dispositivo (para todos, nunca um paywall):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 regras** = `((32.0 − 4.0) MB × 1.048.576) / 9.0 B/regra` — um alvo de 32 MB sob o teto de ~50 MiB da NE. Configurações acima do orçamento são rejeitadas de forma determinística, em vez de deixar o túnel ser encerrado por falta de memória.
- **Teto do plano (`FeatureLimits`):** **Gratuito 500 mil regras / Plus 2 milhões de regras**, que fica abaixo da proteção do dispositivo. Isso substituiu o antigo limite de **contagem** de listas habilitadas (gratuito 3 / pago 10) — limites de contagem de listas estão obsoletos.

> **Ressalva sobre o que vem habilitado por padrão (o código vence):** os padrões gratuitos entregues são **Block List Project Phishing + Scam** (`OnboardingDefaults.lavaRecommendedDefaults`). Eles são derivados no dispositivo a partir do sinalizador `defaultEnabled` de cada origem curada (`BlocklistSource.recommendedDefaultSourceIDs`), que é a fonte da verdade no dispositivo e espelha a coluna `default_enabled` do catálogo no backend. O texto de plano/catálogo que diz que "Block List Basic é o único padrão" está errado para o dispositivo (acompanhado internamente).

### C. Backup (conhecimento zero, opcional) — Implementado

Opcional, ligado à conta, e o único dado do usuário que chega ao backend — como **texto cifrado opaco**.

1. O usuário, se quiser, entra na conta (apenas Apple ou Google; **e-mail/senha foi Descartado**) via troca nativa de `id_token` na Supabase Auth (`grant_type=id_token`, nonce com hash). Apenas a sessão resultante da Supabase é armazenada, localmente no dispositivo, no Keychain.
2. O **`BackupConfigurationPayload`** monta um texto simples minimizado (IDs das blocklists habilitadas, domínios permitidos/bloqueados, preferências de resolvedor, preferências de log local, registro do LavaGuard). Ele **exclui** `isPaid`, QA, diagnósticos e as blocklists completas.
3. O **`ZeroKnowledgeBackupEnvelope`** o sela com **AES-256-GCM** sob uma chave de payload aleatória de 32 bytes; essa chave é envelopada em **slots de chave** por segredo via **PBKDF2-HMAC-SHA256 (210 mil iterações)** — slot de segredo do dispositivo, slot de recuperação assistida, slot opcional de passkey. O slot opcional de passkey é envelopado com uma saída de autenticador **WebAuthn PRF / `hmac-secret`** (derivada por HKDF); essa saída nunca sai do cliente, então o slot de passkey é genuinamente de conhecimento zero — nenhum valor guardado no servidor o desenvelopa (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. O **`BackupSyncService`** envia **apenas o texto cifrado + metadados não secretos** para o `user_backups` da Supabase, direto via PostgREST, delimitado por **RLS** por usuário. (Não existe rota de upload no Worker; o Worker só toca o `user_backups` para apagá-lo durante a exclusão da conta.)
5. **Recuperação:** restauração contínua no mesmo dispositivo via o slot de segredo do dispositivo; fora do dispositivo via a **frase de recuperação de 8 palavras CVCV** (~105 bits) combinada com uma parte de recuperação guardada no servidor via SHA256 (dois fatores — nenhuma metade sozinha decifra); ou, quando um slot de passkey foi selado, via a saída WebAuthn PRF / `hmac-secret` do lado do cliente (sem nenhum valor guardado no servidor). O servidor nunca registra passkeys, emite desafios WebAuthn nem armazena qualquer segredo de recuperação.

Veja [Contas e backup](./accounts-and-backup.md).

### D. Plano de controle app ↔ extensão — Implementado

Três processos (app, túnel, widget) se coordenam por meio do App Group `group.com.lavasec`:

- **O controle = provider messages do NETunnelProviderSession**, e **não** notificações Darwin. O `AppViewModel` codifica uma `LavaSecProviderMessage {kind, operationID}` e chama `session.sendProviderMessage`; o `handleAppMessage` do túnel decide pelo kind (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Arquivos compartilhados** carregam regras/config/saúde (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **stores de UserDefaults compartilhados** (`ProtectionSessionStore` / `ProtectionPauseStore`) carregam o estado de sessão + pausa.
- O **`LavaProtectionCommandService`** executa os comandos de pausar/retomar da Live Activity / AppIntent sob uma trava de arquivo `flock`, com remoção de duplicatas por revisão e negação quando há exigência de autenticação; **a reconexão o ignora** para reiniciar o túnel diretamente (`startVPNTunnel`).
- O **Connect-On-Demand** só é habilitado *depois* que o túnel confirma a conexão, nunca na instalação do perfil — assim, um perfil de onboarding recém-instalado não consegue subir um túnel impossível de desligar.

Veja [Cliente iOS](./ios-client.md).

## 6. Limites de confiança e design que preserva a privacidade

| # | Limite | O que cruza | O que propositalmente NÃO cruza |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolvedor de DNS público** | As consultas de DNS permitidas (criptografadas: DoH3/DoT/DoQ, ou IP simples) vão para o resolvedor escolhido pelo usuário. | A Lava nunca vê a sequência de consultas; ela não está nesse caminho de jeito nenhum. |
| 2 | **Dispositivo ↔ hosts de blocklist de origem** | O dispositivo baixa os bytes das listas direto de `source_url`. | A Lava nunca faz proxy, espelha ou armazena os bytes da blocklist de terceiros. |
| 3 | **Dispositivo ↔ Worker lavasec-api** | Leituras de **metadados** do catálogo; relatórios de bug anônimos opcionais; espelho de direitos; exclusão de conta. | Nenhuma consulta de DNS, nenhum histórico de navegação, nenhuma configuração em texto simples. |
| 4 | **Dispositivo ↔ Supabase** | **Envelope de backup criptografado** opcional (apenas texto cifrado, PostgREST sob RLS); registros da conta. | O servidor não consegue decifrar o backup sem um segredo guardado pelo usuário. |
| 5 | **App ↔ extensão do túnel** (no dispositivo) | Provider messages + arquivos/defaults do App Group. | O túnel falha de forma **segura** em uma inicialização a frio sem um snapshot reutilizável. |

**Princípios de design que preservam a privacidade, fundamentados no que está acima:**

- **Filtragem local em primeiro lugar.** O mecanismo de decisão e o resolvedor rodam dentro da extensão de NE no dispositivo. O backend é, por construção, apenas de metadados — não há tabelas para consultas de DNS de rotina nem telemetria por domínio.
- **Nenhuma conta exigida para a proteção.** A proteção essencial é gratuita para sempre; autenticação e backup são estritamente opcionais.
- **Distribuição apenas com URL de origem.** Desacopla a Lava dos bytes das listas de terceiros (conformidade GPL/PI + segurança na App Review) e mantém uma proteção de CI que exige "sem código de espelho, sem URLs de artefatos da Lava, sem gravação de bytes no R2".
- **Backup de conhecimento zero em repouso.** AES-256-GCM do lado do cliente; o servidor guarda texto cifrado + metadados de KDF + uma parte de recuperação, nunca o texto simples, a frase de recuperação ou a chave desenvelopada. O slot opcional de passkey é envelopado com uma saída WebAuthn PRF / `hmac-secret` do lado do cliente, então ele também é de conhecimento zero — nenhum valor guardado no servidor o desenvelopa.
- **Segredos locais no dispositivo.** O material para desbloquear o backup usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — não sincronizado no iCloud, não presente nos backups do dispositivo.
- **Isolamento de service-role.** `bug_reports`, `mirror_events` e `qa_developers` têm o acesso revogado dos papéis anon/authenticated do PostgREST; só o Worker (service role) os toca.
- **Segurança nunca está à venda.** O pagamento libera **apenas personalização**. Ele nunca contorna a **proteção contra ameaças** não negociável, cuja integridade é garantida pelos hashes SHA256 de origem aceitos (não por uma assinatura do servidor). A precedência é consistente em todo lugar: **proteção contra ameaças > lista de permissões local (exceções permitidas) > blocklist > permitir por padrão.**

## 7. Documentos de cada componente

> Estes são os documentos irmãos no conjunto de documentos de arquitetura. O mecanismo de filtragem de DNS e o catálogo de blocklists estão documentados juntos em um único arquivo.

- [Cliente iOS](./ios-client.md) — alvos, App Group, plano de controle, modelo de estado da proteção, onboarding, Live Activity.
- [Filtragem de DNS e blocklists](./dns-filtering-and-blocklists.md) — snapshot do filtro, precedência de decisão, transportes do resolvedor (DoH3/DoT/DoQ), orçamento de memória, mmap; além do modelo de catálogo apenas com URL de origem, busca do catálogo, análise/normalização local, filtro de domínios protegidos e orçamento por plano.
- [Contas e backup](./accounts-and-backup.md) — autenticação Apple/Google, envelope de conhecimento zero, slots de chave, frase de recuperação, recuperação por passkey via WebAuthn-PRF do lado do cliente.
- [Backend e dados](./backend-and-data.md) — Workers lavasec-api + lavasec-email, schema da Supabase + RLS, R2/D1, implantação.

## 8. Legenda de status

Este conjunto de documentos usa um único vocabulário de status. A **pasta da via é o status autoritativo**; um frontmatter desatualizado dentro de um plano é um bug de documentação, não um status. **O código se sobrepõe aos planos.**

| Status | Significado | Via do plano | Código |
|---|---|---|---|
| **Implementado** | Entregue e confirmado no código | `plans/implemented/` | presente e conectado |
| **Em andamento** | Sendo construído ativamente; parcialmente entregue | `plans/inflight/`, `plans/under_review/` | parcialmente presente |
| **Planejado** | Desenhado, não construído | `plans/backlog/` | ausente |
| **Descartado** | Rejeitado ou revertido | `plans/dropped/` (ou commit revertido) | ausente / removido |

**Status das coisas mencionadas nesta página:**

- **Implementado:** os quatro alvos iOS + App Group; plano de controle por provider message; filtragem de DNS no dispositivo com transportes DoH3/DoT/DoQ/IP; busca do catálogo apenas com URL de origem + análise local; orçamento de regras de filtro (Gratuito 500 mil / Plus 2 milhões) + proteção do dispositivo de ~3,26 milhões; onboarding de várias páginas; segurança por código de acesso/biometria; Live Activity única sem duplicatas; backup de conhecimento zero; autenticação Apple + Google; exclusão de conta; espelhamento de direitos; sondas de QA; a camada de tokens `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluindo o modelo de profundidade `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), os modificadores `.lavaTier(_:)` / `.lavaTierMetadata()` conectados a superfícies representativas (por exemplo, `SettingsView`), e os tokens `dangerRed` e `LavaSpacing` — travados por `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **Em andamento:** a continuação da expansão da camada de tokens do design system para mais superfícies (o modelo de profundidade `LavaTier` e a camada de tokens já estão entregues — veja abaixo — mas um `LavaColorRole` dedicado ainda não existe, então os destaques ainda resolvem para cores cruas).
- **Planejado:** o minijogo easter-egg do Lava Guard; expressões extras do mascote (o mascote tem exatamente **7** estados); recuperação por passkey totalmente pronta para produção em dispositivos físicos (Associated Domains / AASA); reverificação JWS da App Store no lado do servidor (`verification_status` é `client_verified_storekit`); um token `LavaColorRole` dedicado para que os destaques do design system resolvam por um papel semântico em vez de cores cruas.
- **Descartado:** reuso de conexão DoQ (conexões novas por consulta); login por e-mail/senha (apenas Apple + Google); o design de espelho GPL no R2 bruto (substituído por apenas URL de origem).
