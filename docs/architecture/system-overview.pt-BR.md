---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Visão geral do sistema

> **Público-alvo:** engenheiros. Esta é a totalidade do Lava Security em uma única página — quais são as partes, como os dados se movem entre elas e onde ficam os limites de confiança. Os documentos por componente vão mais a fundo; este existe para que você consiga manter o sistema na cabeça antes de lê-los.
>
> **Autoridade:** onde este documento e um plano divergem, **o código vence**. O status reflete a realidade confirmada pelo código, não a aspiração do plano. Veja a [Legenda de status](#8-status-legend) no final.

## 1. Resumo do produto em uma linha

Lava Security é um aplicativo iOS com foco em privacidade que filtra DNS **localmente no dispositivo** por meio de um túnel de pacotes NetworkExtension, bloqueando domínios maliciosos e indesejados para usuários não técnicos (pais, idosos) — com a proteção essencial gratuita para sempre e sem necessidade de conta.

## 2. A promessa de privacidade (canônica)

> Toda a filtragem de DNS acontece no dispositivo; o Lava nunca roteia sua navegação através de seus servidores e nunca recebe o fluxo de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado opaco por usuário e diagnósticos anonimizados que você escolhe enviar.

Tudo abaixo está a serviço de manter essa frase verdadeira. A arquitetura é deliberadamente pequena no lado do servidor: o dispositivo faz o trabalho, e o backend nunca vê uma consulta.

## 3. Componentes

### Cliente iOS (três alvos executáveis + código compartilhado, um App Group `group.com.lavasec`)

| Componente | Bundle / localização | Função | Status |
|---|---|---|---|
| **LavaSecApp** | `com.lavasec.app` | Casca do app SwiftUI; ponto de entrada, navegação de duas abas Guard + Settings (Filtro/Atividade são telas de detalhe do Guard; Network Activity foi movido para Settings → Advanced). | Implementado |
| **LavaSecTunnel** | `com.lavasec.app.tunnel` | `NEPacketTunnelProvider`; o mecanismo de filtragem/resolução de DNS no dispositivo. Sujeito ao **teto de memória de ~50 MiB por extensão** do iOS. | Implementado |
| **LavaSecWidget** | `com.lavasec.app.widget` | Live Activity do WidgetKit (tela de bloqueio + Dynamic Island). | Implementado |
| **Shared/** | `Shared/` | Fontes entre alvos: App Group, serviço de comandos, mascote, atributos/intents da Live Activity. | Implementado |

**Controladores do lado do app (em LavaSecApp):**

- **AppViewModel** — o controlador do lado do app (objeto-deus): detém o ciclo de vida do `NETunnelProviderManager`, a persistência de estado compartilhado, a mensageria do provider, a reconciliação da Live Activity, a sincronização de catálogo, o backup, o StoreKit e a autenticação.
- **RootView** — `TabView` de duas abas (Guard + Settings), com Filtro e Atividade acessadas como telas de detalhe sob o Guard; controla o onboarding, hospeda as sobreposições de bloqueio de segurança / máscara de privacidade.
- **SecurityController** — código de acesso (SHA256 com sal no Keychain) + biometria + proteção por superfície.
- **LavaLiveActivityController** — reconciliador de Activity única, deduplicado e protegido por revisão.
- **OnboardingFlowView** — fluxo de primeira execução com múltiplas páginas (6 páginas: `lava → guardIntro → features → vpn → notifications → done`).

**LavaSecCore (pacote SwiftPM independente de plataforma, `Sources/LavaSecCore/`):**

- **FilterSnapshot / CompactFilterSnapshot** — Filtro compilado + precedência de decisão; a forma compacta é o artefato em disco amigável a mmap que o túnel lê.
- **DNSQueryDispatcher** — precedência de consulta: bootstrap > pause > filter.
- **ResolverOrchestrator** — roteamento de transporte, degradação para DNS simples, failover por endpoint, fallback para DNS do dispositivo.
- **DoHTransport / DoTTransport / DoQTransport** — executores de transporte criptografado.
- **FeatureLimits** (em `SubscriptionPolicy.swift`) — tetos de tier (fonte da verdade), via os membros estáticos `.free` / `.paid`.
- **FilterSnapshotMemoryBudget / FilterSnapshotPreparationService** — cálculo de barreira de proteção do dispositivo + imposição autoritativa do orçamento pós-união.
- **BlocklistCatalogSync / BlocklistParser** — busca de catálogo, download direto do upstream, parse/normalização/dedup local, filtro de domínios protegidos.
- **GuardianMascotAnimation** — grafo de estados do mascote com 7 estados (renderizado por `Shared/SoftShieldGuardian`).
- **ZeroKnowledgeBackupEnvelope / BackupConfigurationPayload / BackupRecoveryPhrase** — criptografia de backup + payload.
- **SupabaseIDTokenAuth** — autenticação `id_token` via URLRequest cru (sem SDK).

### Backend

| Componente | Função | Status |
|---|---|---|
| **lavasec-api Worker** | Cloudflare Worker (`api.lavasecurity.app`): leituras de catálogo, sincronização + publicação de blocklist por admin/cron, relatórios de bugs anônimos, exclusão de conta, espelhamento de direitos da App Store, sondas de QA. | Implementado |
| **lavasec-email Worker** | Encaminhador somente-recepção do Cloudflare Email Routing para `@lavasecurity.app`; rejeita e-mails desconhecidos/grandes demais. | Implementado |
| **Supabase Postgres** | Contas, `user_backups`, metadados de catálogo, tabelas exclusivas de service-role; **RLS em cada tabela pública**. | Implementado |
| **Cloudflare R2** (o bucket R2 de produção, um bucket de preview separado para staging) | Snapshots de catálogo + o cursor de sincronização round-robin. **Nunca** bytes de blocklist de terceiros; a rota de upload de anexos de relatórios de bugs foi removida (objetos legados só são excluídos na exclusão de conta). | Implementado |
| **Cloudflare D1** (o banco de dados de feedback de ajuda) | Votos de feedback anônimos somente-anexação de artigos de ajuda. | Implementado |

## 4. Diagrama de fluxo de dados

A propriedade mais importante de todas: **o caminho do resolvedor de DNS criptografado (lado direito) nunca toca o backend do Lava (parte inferior).** O dispositivo busca *metadados* de catálogo no Worker, mas os *bytes* das listas e o fluxo real de consultas vão diretamente a terceiros.

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

Este é o caminho quente e o núcleo de privacidade. Ele roda inteiramente dentro do `LavaSecTunnel`; nada aqui chega aos servidores do Lava.

1. O túnel de pacotes intercepta uma consulta de DNS (servidor de DNS do túnel `10.255.0.1`).
2. O **`DNSQueryDispatcher`** aplica a precedência de consulta: **bootstrap > pause > filter**. Bootstrap-em-primeiro é uma invariante rígida — o próprio hostname do resolvedor é resolvido antes de qualquer filtragem, para que o resolvedor jamais possa bloquear a si mesmo.
3. Se não for bootstrap e não estiver pausado, o domínio é avaliado contra o **`CompactFilterSnapshot`** (carregado do App Group via mmap zero-copy `Data(contentsOf:options:[.mappedIfSafe])`). A precedência de decisão é **barreira de ameaças > lista de permissões local (exceções permitidas) > blocklist > permitir-por-padrão**; domínios inválidos são bloqueados.
4. **Bloqueado** → o túnel responde localmente (sem contato com o upstream). **Permitido** → a consulta é entregue ao **`ResolverOrchestrator`**.
5. O `ResolverOrchestrator` roteia para o transporte configurado — **`DoH3` / `DoT` / `DoQ` / DNS simples (`IP`)** — com failover por endpoint atrás de um portão de backoff, degradação para DNS simples quando um plano criptografado não tem endpoints, e **fallback para DNS do dispositivo** quando o primário não retorna resposta e o plano permite.
6. A resposta do resolvedor é devolvida ao SO. O fluxo de consultas do usuário vai apenas para o **resolvedor público escolhido pelo usuário**, nunca para o Lava.

Notas de transporte (convenções literais): `DoH3` (sem barra) é anotado **somente quando uma negociação h3 é de fato observada** — preferido, nunca prometido. O **`DoT`** mantém um pool de até 4 NWConnections por endpoint com atualização por obsolescência de inatividade + uma tentativa de reconexão fresca. O **`DoQ`** abre uma **conexão QUIC fresca por consulta** (sem reutilização); o pool de 4 vias dá concorrência, não reutilização de handshake — a reutilização de conexão foi construída, testada em dispositivo e **revertida** (adiada até o piso de implantação iOS-26). Veja [Filtragem de DNS & Blocklists](./dns-filtering-and-blocklists.md).

### B. Busca de catálogo + carregamento de blocklist (source-url-only) — Implementado

Como as regras de filtragem chegam ao dispositivo. O Lava é um distribuidor **source-url-only**: ele publica apenas a URL do upstream + hashes aceitos e **nunca armazena, espelha, transforma ou serve bytes de blocklist de terceiros.**

1. O dispositivo busca **metadados** de catálogo no Worker: `GET https://api.lavasecurity.app/v1/catalog` → JSON servido diretamente do R2 (`catalog/latest.json`), dividido em `sources[]` + `guardrails[]`, cada entrada carregando `source_url` + `accepted_source_hashes`.
2. Para cada fonte habilitada, o dispositivo baixa os **bytes da lista diretamente de `source_url`** (o upstream — HaGeZi, OISD, Block List Project, etc.), e **não** do Lava.
3. O dispositivo faz o parse dos bytes obtidos localmente sob limites de tamanho/regras. As listas comunitárias são aceitas conforme servidas sobre TLS — os `accepted_source_hashes` do catálogo são consultivos (identidade de cache + auditoria), não um portão rígido — de modo que uma lista rotacionada nunca é rejeitada por divergir de um hash fixado. O tier de barreira de ameaças do Lava permanece com hash fixado.
4. O **`BlocklistParser`** faz parse/normalização/dedup localmente (formatos auto / plain / hosts / adblock / dnsmasq), depois o **`DomainRuleSet.lavaSecProtectedDomains`** remove domínios protegidos (apple.com, icloud.com, lavasecurity.com/.app, google.com, accounts.google.com, …) para que uma lista upstream jamais possa bloquear domínios do Lava/Apple/provedor de identidade.
5. O **`FilterSnapshotPreparationService`** mescla a união deduplicada e executa a **imposição autoritativa de orçamento** (limite do dispositivo primeiro, depois o tier), então escreve `filter-snapshot.compact` no App Group.
6. O `AppViewModel` envia uma mensagem de provider `reload-snapshot`; o túnel recarrega.

O lado do Worker espelha isso: sua sincronização por admin/cron busca cada upstream, calcula hash/contagem, escreve `raw_r2_key = null` / `normalized_r2_key = null` e republica apenas metadados. O modelo de catálogo de blocklist e o caminho de sincronização do backend estão cobertos em [Filtragem de DNS & Blocklists](./dns-filtering-and-blocklists.md) e [Backend & Dados](./backend-and-data.md).

**Modelo de orçamento (duas camadas):**
- **Barreira do dispositivo (todos, nunca um paywall):** `FilterSnapshotMemoryBudget.maxFilterRuleCount` ≈ **3.262.236 regras** = `((32.0 − 4.0) MB × 1,048,576) / 9.0 B/rule` — um alvo de 32 MB sob o teto de ~50 MiB da NE. Configurações acima do orçamento são rejeitadas deterministicamente em vez de deixar o túnel ser eliminado por jetsam.
- **Teto de tier (`FeatureLimits`):** **Free 500K regras / Plus 2M regras**, que se liga abaixo da barreira do dispositivo. Isso substituiu o antigo limite de **contagem** de listas habilitadas (free 3 / paid 10) — limites de contagem de listas estão obsoletos.

> **Fonte da verdade do habilitado-por-padrão:** o padrão gratuito enviado é o **Block List Basic** (`OnboardingDefaults.lavaRecommendedDefaults`). Ele é derivado no dispositivo a partir da flag `defaultEnabled` de cada fonte curada (`BlocklistSource.recommendedDefaultSourceIDs`), que espelha a coluna `default_enabled` do catálogo do backend, gerada a partir da mesma especificação canônica de catálogo.

### C. Backup (conhecimento zero, opt-in) — Implementado

Opcional, restrito a conta, e os únicos dados de usuário que aterrissam no backend — como **texto cifrado opaco**.

1. O usuário opcionalmente faz login (apenas Apple ou Google; **e-mail/senha foi Descartado**) via `id_token` nativo trocado no Supabase Auth (`grant_type=id_token`, nonce com hash). Apenas a sessão Supabase resultante é armazenada, local no dispositivo, no Keychain.
2. O **`BackupConfigurationPayload`** monta um texto-claro minimizado (IDs de blocklist habilitadas, domínios permitidos/bloqueados, preferências de resolvedor, preferências de log local, ledger do LavaGuard). Ele **exclui** `isPaid`, QA, diagnósticos e blocklists completas.
3. O **`ZeroKnowledgeBackupEnvelope`** o sela com **AES-256-GCM** sob uma chave de payload aleatória de 32 bytes; essa chave é embrulhada em **slots de chave** por segredo via **PBKDF2-HMAC-SHA256 (210k iterações)** — slot de segredo do dispositivo, slot de recuperação assistida, slot opcional de passkey. O slot opcional de passkey é embrulhado com uma saída de autenticador **WebAuthn PRF / `hmac-secret`** (derivada via HKDF); essa saída nunca sai do cliente, então o slot de passkey é genuinamente de conhecimento zero — nenhum valor mantido no servidor o desembrulha (`ZeroKnowledgeBackupEnvelope.makeWithPRF`).
4. O **`BackupSyncService`** envia **apenas texto cifrado + metadados não secretos** para o `user_backups` do Supabase diretamente via PostgREST, escopado por **RLS** por usuário. (Não há rota de upload no Worker; o Worker toca em `user_backups` apenas para excluí-lo durante a exclusão de conta.)
5. **Recuperação:** restauração contínua no mesmo dispositivo via o slot de segredo do dispositivo; fora do dispositivo via a **frase de recuperação CVCV de 8 palavras** (~105 bits) combinada com uma parcela de recuperação mantida no servidor via SHA256 (duplo fator — nenhuma metade sozinha descriptografa); ou, quando um slot de passkey foi selado, via a saída WebAuthn PRF / `hmac-secret` no lado do cliente (sem envolver qualquer valor mantido no servidor). O servidor nunca registra passkeys, emite desafios WebAuthn nem armazena qualquer segredo de recuperação.

Veja [Contas & Backup](./accounts-and-backup.md).

### D. Plano de controle App ↔ extensão — Implementado

Três processos (app, túnel, widget) se coordenam através do App Group `group.com.lavasec`:

- **Controle = mensagens de provider NETunnelProviderSession**, **não** notificações Darwin. O `AppViewModel` codifica um `LavaSecProviderMessage {kind, operationID}` e chama `session.sendProviderMessage`; o `handleAppMessage` do túnel faz switch no kind (`reload-snapshot` / `reload-protection-pause` / `reload-configuration` / `clear-*` / `flush-tunnel-health`).
- **Arquivos compartilhados** carregam regras/config/saúde (`filter-snapshot.compact`, `app-configuration.json`, `tunnel-health.json`); **stores compartilhados de UserDefaults** (`ProtectionSessionStore` / `ProtectionPauseStore`) carregam estado de sessão + pausa.
- O **`LavaProtectionCommandService`** executa comandos de pausa/retomada de Live-Activity / AppIntent sob um bloqueio de arquivo `flock` com dedup por revisão e negação de auth-obrigatória; **a reconexão o ignora** para reiniciar o túnel diretamente (`startVPNTunnel`).
- O **Connect-On-Demand** é habilitado apenas *depois* que o túnel confirma a conexão, nunca na instalação do perfil — assim, um perfil de onboarding recém-instalado não pode subir um túnel impossível de desligar.

Veja [Cliente iOS](./ios-client.md).

## 6. Limites de confiança & design preservador de privacidade

| # | Limite | O que o cruza | O que deliberadamente NÃO cruza |
|---|---|---|---|
| 1 | **Dispositivo ↔ resolvedor de DNS público** | Consultas de DNS permitidas (criptografadas: DoH3/DoT/DoQ, ou IP simples) vão ao resolvedor escolhido pelo usuário. | O Lava nunca vê o fluxo de consultas; ele não está nesse caminho de forma alguma. |
| 2 | **Dispositivo ↔ hosts de blocklist upstream** | O dispositivo baixa os bytes da lista diretamente de `source_url`. | O Lava nunca faz proxy, espelha ou armazena bytes de blocklist de terceiros. |
| 3 | **Dispositivo ↔ lavasec-api Worker** | Leituras de **metadados** de catálogo; relatórios de bugs anônimos opt-in; espelho de direitos; exclusão de conta. | Nenhuma consulta de DNS, nenhum histórico de navegação, nenhuma configuração em texto-claro. |
| 4 | **Dispositivo ↔ Supabase** | **Envelope de backup criptografado** opt-in (apenas texto cifrado, PostgREST sob RLS); linhas de conta. | O servidor não consegue descriptografar o backup sem um segredo mantido pelo usuário. |
| 5 | **App ↔ extensão de túnel** (no dispositivo) | Mensagens de provider + arquivos/defaults do App Group. | O túnel falha **fechado** na partida a frio sem um snapshot reutilizável. |

**Princípios de design preservador de privacidade, embasados no acima:**

- **Filtragem local-first.** O mecanismo de decisão e o resolvedor rodam dentro da extensão NE no dispositivo. O backend é apenas-metadados por construção — não há tabelas para consultas de DNS rotineiras ou telemetria por domínio.
- **Nenhuma conta necessária para proteção.** A proteção essencial é gratuita para sempre; auth e backup são estritamente opt-in.
- **Distribuição source-url-only.** Desacopla o Lava dos bytes de listas de terceiros (conformidade GPL/PI + segurança na App Review) e mantém uma barreira de CI impondo "nenhum código de espelho, nenhuma URL de artefato do Lava, nenhuma escrita de bytes no R2."
- **Backup de conhecimento zero em repouso.** AES-256-GCM no lado do cliente; o servidor guarda texto cifrado + metadados de KDF + uma parcela de recuperação, nunca o texto-claro, a frase de recuperação ou a chave desembrulhada. O slot opcional de passkey é embrulhado com uma saída WebAuthn PRF / `hmac-secret` no lado do cliente, de modo que ele também é de conhecimento zero — nenhum valor mantido no servidor o desembrulha.
- **Segredos locais ao dispositivo.** O material de desbloqueio de backup usa `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — não sincronizado com iCloud, não em backups do dispositivo.
- **Isolamento de service-role.** `bug_reports`, `mirror_events` e `qa_developers` têm acesso revogado dos papéis PostgREST anon/authenticated; apenas o Worker (service role) os toca.
- **Segurança nunca está à venda.** O pagamento desbloqueia **apenas customização**. Ele nunca contorna a **barreira de ameaças** não dispensável, cuja integridade é imposta por hashes de fonte SHA256 aceitos (não por uma assinatura do servidor). A precedência é consistente em todos os lugares: **barreira de ameaças > lista de permissões local (exceções permitidas) > blocklist > permitir-por-padrão.**

## 7. Documentos por componente

> Estes são os documentos irmãos no conjunto de documentos de arquitetura. O mecanismo de filtragem de DNS e o catálogo de blocklist são documentados juntos em um único arquivo.

- [Cliente iOS](./ios-client.md) — alvos, App Group, plano de controle, modelo de estado de proteção, onboarding, Live Activity.
- [Filtragem de DNS & Blocklists](./dns-filtering-and-blocklists.md) — snapshot de filtro, precedência de decisão, transportes de resolvedor (DoH3/DoT/DoQ), orçamento de memória, mmap; mais o modelo de catálogo source-url-only, busca de catálogo, parse/normalização local, filtro de domínios protegidos e orçamento de tier.
- [Contas & Backup](./accounts-and-backup.md) — auth Apple/Google, envelope de conhecimento zero, slots de chave, frase de recuperação, recuperação por passkey via WebAuthn-PRF no lado do cliente.
- [Backend & Dados](./backend-and-data.md) — Workers lavasec-api + lavasec-email, esquema Supabase + RLS, R2/D1, implantação.

## 8. Legenda de status

Este conjunto de documentos usa um único vocabulário de status. A **pasta da raia é o status autoritativo**; frontmatter obsoleto dentro de um plano é um bug de documentação, não um status. **O código sobrepõe os planos.**

| Status | Significado | Raia do plano | Código |
|---|---|---|---|
| **Implementado** | Enviado e confirmado no código | `plans/implemented/` | presente & conectado |
| **Em progresso** | Ativamente em construção; parcialmente entregue | `plans/inflight/`, `plans/under_review/` | parcialmente presente |
| **Planejado** | Projetado, não construído | `plans/backlog/` | ausente |
| **Descartado** | Rejeitado ou revertido | `plans/dropped/` (ou commit revertido) | ausente / removido |

**Status das coisas mencionadas nesta página:**

- **Implementado:** os quatro alvos iOS + App Group; plano de controle por mensagens de provider; filtragem de DNS no dispositivo com transportes DoH3/DoT/DoQ/IP; busca de catálogo source-url-only + parse local; orçamento de regras de filtro (Free 500K / Plus 2M) + barreira do dispositivo de ~3,26M; onboarding de múltiplas páginas; segurança por código de acesso/biometria; Live Activity única deduplicada; backup de conhecimento zero; auth Apple + Google; exclusão de conta; espelhamento de direitos; sondas de QA; a camada de tokens `LavaDesignSystem` (`LavaTokens`/`LavaComponents`/`LavaConfirmationDialog`/`LavaIcon`/`LavaScaffold`), incluindo o modelo de profundidade `LavaTier` (Floor/Window/Workshop = `calm`/`celebratory`/`technical`), os modificadores `.lavaTier(_:)` / `.lavaTierMetadata()` conectados a superfícies representativas (ex.: `SettingsView`), e os tokens `dangerRed` e `LavaSpacing` — travados por `Tests/LavaSecCoreTests/LavaDesignTokensSourceTests.swift`.
- **Em progresso:** continuação do lançamento da camada de tokens do design-system para mais superfícies (o modelo de profundidade `LavaTier` e a camada de tokens são enviados — veja abaixo — mas um `LavaColorRole` dedicado ainda não está presente, então os acentos ainda resolvem para cores cruas).
- **Planejado:** o mini-jogo easter-egg do Lava Guard; expressões extras do mascote (o mascote tem exatamente **7** estados); recuperação por passkey totalmente pronta para produção em dispositivos físicos (Associated Domains / AASA); reverificação JWS da App Store no lado do servidor (`verification_status` é `client_verified_storekit`); um token `LavaColorRole` dedicado para que os acentos do design-system resolvam através de um papel semântico em vez de cores cruas.
- **Descartado:** reutilização de conexão DoQ (conexões frescas por consulta); login por e-mail/senha (apenas Apple + Google); o design de espelho GPL raw-R2 (substituído por source-url-only).
