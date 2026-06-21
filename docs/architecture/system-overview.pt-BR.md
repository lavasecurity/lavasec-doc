---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Visão geral do sistema

> **Público:** engenheiros. Esta é a totalidade do Lava Security em uma única página — quais são as partes, como os dados se movem entre elas e onde ficam as fronteiras de confiança. Os documentos de cada componente vão mais a fundo; este existe para que você consiga manter o sistema inteiro na cabeça antes de lê-los.
>
> **Autoridade:** onde este documento e um plano divergirem, **o código vence**. O status reflete a realidade confirmada no código, não a aspiração do plano. Veja a [legenda de status](#8-status-legend) no final.

## 1. Resumo do produto em uma frase

O Lava Security é um app de iOS com a privacidade em primeiro lugar que filtra DNS **localmente no dispositivo** por meio de um túnel de pacotes NetworkExtension, bloqueando domínios maliciosos e indesejados para usuários não técnicos (pais, idosos) — com a proteção essencial gratuita para sempre e sem necessidade de conta.

## 2. A promessa de privacidade (canônica)

> Toda a filtragem de DNS acontece no dispositivo; o Lava nunca roteia sua navegação pelos servidores dele e nunca recebe o fluxo de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado e opaco por usuário e diagnósticos anonimizados que você escolher enviar.

Tudo o que vem a seguir existe para manter essa frase verdadeira. A arquitetura é deliberadamente pequena do lado do servidor: o dispositivo faz o trabalho, e o backend nunca vê uma consulta.

## 3. Componentes

### Cliente iOS (três alvos executáveis + código compartilhado, um App Group `group.com.lavasec`)

| Componente | Bundle / local | Função | Status |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Casca do app em SwiftUI; ponto de entrada, navegação de duas abas Guard + Configurações (Filtro/Atividade são telas de detalhe do Guard; Atividade de Rede passou para Configurações → Avançado). | Implementado |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; o motor de filtragem/resolução de DNS no dispositivo. Sujeito ao **teto de memória de ~50 MiB por extensão** do iOS. | Implementado |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity do WidgetKit (tela de bloqueio + Dynamic Island). | Implementado |
| **Shared/** | `Shared/` | Fontes compartilhadas entre alvos: App Group, serviço de comandos, mascote, atributos/intents da Live Activity. | Implementado |

**Controladores do lado do app (em LavaSecApp):**

- **AppViewModel** — o controlador do lado do app (objeto-deus): cuida do ciclo de vida do `NETunnelProviderManager`, da persistência de estado compartilhado, da troca de mensagens com o provider, da reconciliação da Live Activity, da sincronização do catálogo, do backup, do StoreKit e da autenticação.
- **RootView** — `TabView` de duas abas (Guard + Configurações), com Filtro e Atividade alcançados como telas de detalhe dentro do Guard; controla o onboarding, hospeda as sobreposições de bloqueio de segurança / máscara de privacidade.
- **SecurityController** — código de acesso (SHA256 com salt no Keychain) + biometria + proteção por superfície.
- **LavaLiveActivityController** — reconciliador de Activity única, com deduplicação e controle por revisão.
- **OnboardingFlowView** — fluxo de primeira execução com várias páginas (6 páginas: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (pacote SwiftPM independente de plataforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — filtro compilado + precedência de decisão; a forma compacta é o artefato em disco amigável a mmap que o túnel lê.
- **DNSQueryDispatcher** — precedência de consulta: bootstrap > pausa > filtro.
- **ResolverOrchestrator** — roteamento de transporte, degradação para DNS simples, failover por endpoint, fallback para o DNS do dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — executores de transporte criptografado.
- **FeatureLimits** (em `SubscriptionPolicy.swift`) — tetos por nível (fonte da verdade), via os membros estáticos `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — cálculo das salvaguardas do dispositivo + imposição autoritativa do orçamento após a união.
- **BlocklistCatalogSync / BlocklistParser** — busca do catálogo, download direto do upstream, parse/normalização/deduplicação local, filtro de domínios protegidos.
- **GuardianMascotAnimation** — grafo de estados do mascote com 7 estados (renderizado por `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — criptografia + payload do backup.
- **SupabaseIDTokenAuth** — autenticação `id_token` por URLRequest cru (sem SDK).

### Backend

| Componente | Função | Status |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker (`api.lavasecurity.app`): leituras do catálogo, sincronização/publicação da blocklist por admin/cron, relatórios de bugs anônimos, exclusão de conta, espelhamento de direitos da App Store, sondagens de QA. | Implementado |
| **lavasec-email Worker** | Encaminhador somente de recebimento do Cloudflare Email Routing para `@lavasecurity.app`; rejeita e-mails desconhecidos/grandes demais. | Implementado |
| **Supabase Postgres** | Contas, `user_backups`, metadados do catálogo, tabelas só de service-role; **RLS em toda tabela pública**. | Implementado |
| **Cloudflare R2** (o bucket R2 de produção, com um bucket de preview separado para staging) | Snapshots do catálogo + o cursor de sincronização em round-robin. **Nunca** bytes de blocklists de terceiros; a rota de upload de anexos de relatórios de bug foi removida (objetos legados só são excluídos na exclusão da conta). | Implementado |
| **Cloudflare D1** (o banco de feedback da ajuda) | Votos de feedback anônimo de artigos de ajuda, somente de inserção. | Implementado |

## 4. Diagrama de fluxo de dados

A propriedade mais importante de todas: **o caminho do resolvedor de DNS criptografado (lado direito) nunca toca no backend do Lava (parte inferior).** O dispositivo busca *metadados* do catálogo no Worker, mas os *bytes* das listas e o fluxo real de consultas vão direto para terceiros.

```
                                  YOUR iPHONE
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

### A. O caminho do DNS (por consulta, todo no dispositivo) — Implementado

Este é o caminho quente e o núcleo da privacidade. Ele roda inteiramente dentro do `LavaSecTunnel`; nada aqui chega aos servidores do Lava.

1. O túnel de pacotes intercepta uma consulta de DNS (servidor DNS do túnel `10.255.0.1`).
2. O **`DNSQueryDispatcher`** aplica a precedência de consulta: **bootstrap > pausa > filtro**. Bootstrap primeiro é um invariante rígido — o próprio hostname do resolvedor é resolvido antes de qualquer filtragem, para que o resolvedor jamais possa bloquear a si mesmo.
3. Se não for bootstrap e não estiver pausado, o domínio é avaliado contra o **`CompactFilterSnapshot`** (carregado do App Group via mmap zero-copy `Data(contentsOf:options:[.mappedIfSafe])`). A precedência de decisão é **salvaguarda de ameaça > lista de permissões local (exceções permitidas) > blocklist > permissão por padrão**; domínios inválidos são bloqueados.
4. **Bloqueado** → o túnel responde localmente (sem contato com o upstream). **Permitido** → a consulta é entregue ao **`ResolverOrchestrator`**.
5. O `ResolverOrchestrator` roteia para o transporte configurado — **`DoH3` / `DoT` / `DoQ` / DNS simples (`IP`)** — com failover por endpoint atrás de uma trava de backoff, degradação para DNS simples quando um plano criptografado não tem endpoints, e **fallback para o DNS do dispositivo** quando o primário não retorna resposta e o plano permite.
6. A resposta do resolvedor é devolvida ao SO. O fluxo de consultas do usuário vai apenas para o **resolvedor público escolhido pelo usuário**, nunca para o Lava.

Notas de transporte (convenções verbatim): `DoH3` (sem barra) só é anotado **quando uma negociação h3 é de fato observada** — preferido, nunca prometido. O **`DoT`** mantém um pool de até 4 NWConnections por endpoint com renovação por inatividade + uma tentativa de reconexão com conexão nova. O **`DoQ`** abre uma **conexão QUIC nova por consulta** (sem reutilização); o pool de 4 vias dá concorrência, não reutilização de handshake — a reutilização de conexão foi construída, testada em dispositivo e **revertida** (adiada até o piso de implantação iOS-26). Veja [Filtragem de DNS e blocklists](./dns-filtering-and-blocklists.md).

### B. Busca do catálogo + carga da blocklist (somente source-url) — Implementado

Como as regras de filtro chegam ao dispositivo. O Lava é um distribuidor **somente source-url**: ele publica apenas a URL do upstream + os hashes aceitos e **nunca armazena, espelha, transforma ou serve bytes de blocklists de terceiros.**

1. O dispositivo busca os **metadados** do catálogo no Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servido direto do R2 (`catalog/latest.json`), dividido em `sources[]` + `guardrails[]`, com cada entrada carregando `source_url` + `accepted_source_hashes`.
2. Para cada fonte habilitada, o dispositivo baixa os **bytes da lista diretamente de `source_url`** (o upstream — HaGeZi, OISD, Block List Project, etc.), e **não** do Lava.
3. O dispositivo calcula o SHA256 e só aceita bytes cujo checksum esteja em `accepted_source_hashes`; em caso de divergência, ele recorre ao último cache bom ou falha fechado (`checksumMismatch`).
4. O **`BlocklistParser`** faz parse/normalização/deduplicação localmente (formatos auto / plain / hosts / adblock / dnsmasq), e então o **`DomainRuleSet.lavaSecProtectedDomains`** remove os domínios protegidos (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) para que uma lista do upstream jamais possa bloquear domínios do Lava/Apple/provedor de identidade.
5. O **`FilterSnapshotPreparationService`** mescla a união deduplicada e roda a **imposição autoritativa do orçamento** (primeiro o limite do dispositivo, depois o nível), e então grava `filter-snapshot.compact` no App Group.
6. O `AppViewModel` envia uma mensagem de provider `reload-snapshot`; o túnel recarrega.

O lado do Worker espelha isso: a sincronização por admin/cron busca cada upstream, calcula hash/contagem, grava `raw_r2_key = null` / `normalized_r2_key = null` e republica apenas os metadados. O modelo do catálogo de blocklist e o caminho de sincronização do backend estão cobertos em [Filtragem de DNS e blocklists](./dns-filtering-and-blocklists.md) e [Backend e dados](./backend-and-data.md).

**Modelo de orçamento (duas camadas):**
- **Salvaguarda do dispositivo (para todos, nunca um paywall):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 regras** = `((32.0 − 4.0) MB × 1.048.576) / 9.0 B/regra` — um alvo de 32 MB sob o teto de ~50 MiB da NE. Configurações que estouram o orçamento são rejeitadas de forma determinística em vez de deixar o túnel sofrer jetsam.
- **Teto por nível (`FeatureLimits`):** **Free 500 mil regras / Plus 2 milhões de regras**, que fica abaixo da salvaguarda do dispositivo. Isso substituiu o antigo limite de **contagem** de listas habilitadas (free 3 / pago 10) — os limites por contagem de listas estão obsoletos.

> **Ressalva dos padrões habilitados (o código vence):** os padrões gratuitos que vão no app são **Block List Project Phishing + Scam** (`OnboardingDefaults.lavaRecommendedDefaults`). Eles são derivados no dispositivo a partir da flag `defaultEnabled` de cada fonte curada (`BlocklistSource.recommendedDefaultSourceIDs`), que é a fonte da verdade no dispositivo e espelha a coluna `default_enabled` do catálogo no backend. O texto do plano/catálogo que diz que "Block List Basic é o único padrão" está errado para o dispositivo (rastreado internamente).

### C. Backup (zero-knowledge, opt-in) — Implementado

Opcional, restrito a conta, e o único dado do usuário que chega ao backend — como **texto cifrado opaco**.

1. O usuário opcionalmente faz login (apenas Apple ou Google; **e-mail/senha foi Descontinuado**) via `id_token` nativo trocado no Supabase Auth (`grant_type=id_token`, nonce com hash). Apenas a sessão Supabase resultante é armazenada, localmente no dispositivo, no Keychain.
2. O **`BackupConfigurationPayload`** monta um texto simples minimizado (IDs de blocklists habilitadas, domínios permitidos/bloqueados, preferências do resolvedor, preferências de log local, ledger do LavaGuard). Ele **exclui** `isPaid`, QA, diagnósticos e blocklists completas.
3. O **`ZeroKnowledgeBackupEnvelope`** o sela com **AES-256-GCM** sob uma chave de payload aleatória de 32 bytes; essa chave é encapsulada em **slots de chave** por segredo via **PBKDF2-HMAC-SHA256 (210 mil iterações)** — slot de segredo do dispositivo, slot de recuperação assistida, slot opcional de passkey. O slot opcional de passkey é encapsulado com uma saída de **WebAuthn PRF / `hmac-secret`** do autenticador (derivada por HKDF); essa saída nunca deixa o cliente, então o slot de passkey é genuinamente zero-knowledge — nenhum valor mantido no servidor o desencapsula (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. O **`BackupSyncService`** envia **apenas texto cifrado + metadados não secretos** para o `user_backups` do Supabase diretamente via PostgREST, restrito por **RLS** por usuário. (Não há rota de upload pelo Worker; o Worker só toca em `user_backups` para excluí-lo durante a exclusão da conta.)
5. **Recuperação:** restauração contínua no mesmo dispositivo via o slot de segredo do dispositivo; fora do dispositivo via a **frase de recuperação CVCV de 8 palavras** (~105 bits) combinada com uma parcela de recuperação mantida no servidor via SHA256 (dois fatores — nenhuma metade sozinha descriptografa); ou, quando um slot de passkey foi selado, via a saída de WebAuthn PRF / `hmac-secret` do lado do cliente (sem nenhum valor mantido no servidor). O servidor nunca registra passkeys, nunca emite desafios WebAuthn nem armazena qualquer segredo de recuperação.

Veja [Contas e backup](./accounts-and-backup.md).

### D. Plano de controle app ↔ extensão — Implementado

Três processos (app, túnel, widget) se coordenam através do App Group `group.com.lavasec`:

- **Controle = mensagens de provider via NETunnelProviderSession**, e **não** notificações Darwin. O `AppViewModel` codifica um `LavaSecProviderMessage {kind, operationID}` e chama `session.sendProviderMessage`; o `handleAppMessage` do túnel faz switch no kind (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Arquivos compartilhados** carregam regras/configuração/saúde (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **armazenamentos UserDefaults compartilhados** (`ProtectionSessionStore` / `ProtectionPauseStore`) carregam o estado de sessão + pausa.
- O **`LavaProtectionCommandService`** executa comandos de pausar/retomar da Live Activity / AppIntent sob uma trava de arquivo `flock` com deduplicação por revisão e negação quando há autenticação exigida; **a reconexão o ignora** para reiniciar o túnel diretamente (`startVPNTunnel`).
- O **Connect-On-Demand** só é habilitado *depois* que o túnel confirma que está conectado, nunca na instalação do perfil — para que um perfil de onboarding recém-instalado não consiga subir um túnel impossível de desligar.

Veja [Cliente iOS](./ios-client.md).

## 6. Fronteiras de confiança e design que preserva a privacidade

| # | Fronteira | O que a cruza | O que deliberadamente NÃO a cruza |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolvedor de DNS público** | Consultas de DNS permitidas (criptografadas: DoH3/DoT/DoQ, ou IP simples) vão para o resolvedor escolhido pelo usuário. | O Lava nunca vê o fluxo de consultas; ele não está nesse caminho de jeito nenhum. |
| 2 | **Dispositivo ↔ hosts de blocklist do upstream** | O dispositivo baixa os bytes da lista diretamente de `source_url`. | O Lava nunca faz proxy, espelha ou armazena bytes de blocklists de terceiros. |
| 3 | **Dispositivo ↔ lavasec-api Worker** | Leituras de **metadados** do catálogo; relatórios de bug anônimos opt-in; espelho de direitos; exclusão de conta. | Nenhuma consulta de DNS, nenhum histórico de navegação, nenhuma configuração em texto simples. |
| 4 | **Dispositivo ↔ Supabase** | **Envelope de backup criptografado** opt-in (só texto cifrado, PostgREST sob RLS); linhas de conta. | O servidor não consegue descriptografar o backup sem um segredo de posse do usuário. |
| 5 | **App ↔ extensão de túnel** (no dispositivo) | Mensagens de provider + arquivos/defaults do App Group. | O túnel falha **fechado** na partida fria sem um snapshot reutilizável. |

**Princípios de design que preservam a privacidade, fundamentados no acima:**

- **Filtragem local em primeiro lugar.** O motor de decisão e o resolvedor rodam dentro da extensão NE no dispositivo. O backend é, por construção, apenas de metadados — não há tabelas para consultas de DNS rotineiras nem telemetria por domínio.
- **Nenhuma conta exigida para a proteção.** A proteção essencial é gratuita para sempre; autenticação e backup são estritamente opt-in.
- **Distribuição somente source-url.** Desacopla o Lava dos bytes de listas de terceiros (conformidade GPL/PI + segurança no App Review) e mantém uma salvaguarda de CI impondo "nenhum código de espelho, nenhuma URL de artefato do Lava, nenhuma gravação de bytes no R2".
- **Backup zero-knowledge em repouso.** AES-256-GCM do lado do cliente; o servidor guarda texto cifrado + metadados de KDF + uma parcela de recuperação, nunca o texto simples, a frase de recuperação ou a chave desencapsulada. O slot opcional de passkey é encapsulado com uma saída de WebAuthn PRF / `hmac-secret` do lado do cliente, então ele também é zero-knowledge — nenhum valor mantido no servidor o desencapsula.
- **Segredos locais no dispositivo.** O material de desbloqueio do backup usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — não sincronizado com o iCloud, não presente em backups do dispositivo.
- **Isolamento de service-role.** `bug_reports`, `mirror_events` e `qa_developers` são revogados dos papéis PostgREST anon/authenticated; apenas o Worker (service role) os toca.
- **Segurança nunca está à venda.** O pagamento desbloqueia **apenas a personalização**. Ele nunca contorna a **salvaguarda de ameaça** não negociável, cuja integridade é imposta por hashes SHA256 de fonte aceitos (não por uma assinatura do servidor). A precedência é consistente em todo lugar: **salvaguarda de ameaça > lista de permissões local (exceções permitidas) > blocklist > permissão por padrão.**

## 7. Documentos por componente

> Estes são os documentos irmãos no conjunto de documentos de arquitetura. O motor de filtragem de DNS e o catálogo de blocklist são documentados juntos em um único arquivo.

- [Cliente iOS](./ios-client.md) — alvos, App Group, plano de controle, modelo de estado da proteção, onboarding, Live Activity.
- [Filtragem de DNS e blocklists](./dns-filtering-and-blocklists.md) — snapshot do filtro, precedência de decisão, transportes do resolvedor (DoH3/DoT/DoQ), orçamento de memória, mmap; além do modelo de catálogo somente source-url, busca do catálogo, parse/normalização local, filtro de domínios protegidos e orçamento por nível.
- [Contas e backup](./accounts-and-backup.md) — autenticação Apple/Google, envelope zero-knowledge, slots de chave, frase de recuperação, recuperação por passkey via WebAuthn-PRF do lado do cliente.
- [Backend e dados](./backend-and-data.md) — Workers lavasec-api + lavasec-email, esquema do Supabase + RLS, R2/D1, implantação.

## 8. Legenda de status {#8-status-legend}

Este conjunto de documentos usa um único vocabulário de status. A **pasta da lane é o status autoritativo**; frontmatter desatualizado dentro de um plano é um bug de documentação, não um status. **O código sobrepõe os planos.**

| Status | Significado | Lane do plano | Código |
|---|---|---|---|
| **Implementado** | Lançado e confirmado no código | `plans/implemented/` | presente e conectado |
| **Em andamento** | Sendo construído ativamente; parcialmente entregue | `plans/inflight/`, `plans/under_review/` | parcialmente presente |
| **Planejado** | Projetado, não construído | `plans/backlog/` | ausente |
| **Descontinuado** | Rejeitado ou revertido | `plans/dropped/` (ou commit revertido) | ausente / removido |

**Status das coisas mencionadas nesta página:**

- **Implementado:** os quatro alvos do iOS + App Group; plano de controle por mensagens de provider; filtragem de DNS no dispositivo com transportes DoH3/DoT/DoQ/IP; busca de catálogo somente source-url + parse local; orçamento de regras de filtro (Free 500 mil / Plus 2 milhões) + salvaguarda do dispositivo de ~3,26 milhões; onboarding com várias páginas; segurança por código de acesso/biometria; Live Activity única deduplicada; backup zero-knowledge; autenticação Apple + Google; exclusão de conta; espelhamento de direitos; sondagens de QA; a camada de tokens `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluindo o modelo de profundidade `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), os modificadores `.lavaTier(_:)` / `.lavaTierMetadata()` conectados a superfícies representativas (por exemplo, `SettingsView`) e os tokens `dangerRed` e `LavaSpacing` — travados por `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **Em andamento:** continuação do lançamento da camada de tokens do design-system por mais superfícies (o modelo de profundidade `LavaTier` e a camada de tokens já vão no app — veja abaixo — mas um `LavaColorRole` dedicado ainda não está presente, então os destaques ainda resolvem para cores cruas).
- **Planejado:** o mini-jogo easter-egg do Lava Guard; expressões extras do mascote (o mascote tem exatamente **7** estados); recuperação por passkey totalmente pronta para produção em dispositivos físicos (Associated Domains / AASA); re-verificação JWS da App Store do lado do servidor (`verification_status` é `client_verified_storekit`); um token `LavaColorRole` dedicado para que os destaques do design-system resolvam por um papel semântico em vez de cores cruas.
- **Descontinuado:** reutilização de conexão DoQ (conexões novas por consulta); login por e-mail/senha (apenas Apple + Google); o design de espelho GPL no R2 cru (substituído por somente source-url).
