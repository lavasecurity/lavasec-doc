---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Backend e dados

> **Público:** engenheiros de backend. **Escopo:** a camada de servidor — os dois Cloudflare Workers, o schema/RLS/auth do Supabase Postgres, os armazenamentos Cloudflare R2 e D1, toda a superfície da API HTTP, configuração e deploy, e como o source-url-only é imposto no servidor.
>
> **Referência autoritativa:** quando um plano e o código divergem, **o código vence** — as divergências são apontadas ao longo do texto. Os rótulos de status usam a legenda do conjunto de documentos: **Implementado** (entregue e confirmado no código), **Em andamento** (parcialmente concluído), **Planejado** (projetado, não construído), **Descartado** (rejeitado ou revertido).

## 1. O formato do backend

O backend é deliberadamente pequeno e preserva a privacidade. É uma borda de metadados e contas, não um serviço de filtragem. **Toda a filtragem de DNS acontece no dispositivo; a Lava nunca direciona sua navegação pelos servidores dela e nunca recebe o fluxo de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado e opaco por usuário, e diagnósticos anonimizados que você opta por enviar.** Não há tabelas para consultas de DNS de rotina nem telemetria por domínio, e o login na conta é opcional e nunca é necessário para a proteção.

A camada de servidor é dividida em dois componentes: o código do Worker de backend e o schema do banco de dados.

| Componente | Função |
|---|---|
| **Worker lavasec-api** | Borda principal: leituras públicas do catálogo, sincronização de blocklists e publicação do catálogo por admin+cron, relatórios de bug anônimos, feedback de ajuda, exclusão de conta, espelhamento de direitos da App Store, pixels de sonda de QA, verificação de acesso de QA da conta, promoção de triagem de relatórios de bug |
| **Worker lavasec-email** | Encaminhador somente-recebimento do Cloudflare Email Routing para `@lavasecurity.app` |
| **Supabase Postgres** (um projeto Supabase Postgres) | Contas, backups criptografados, metadados do catálogo, tabelas somente-service-role; RLS em toda tabela pública |
| **Cloudflare R2** (um bucket de produção, com um bucket de preview separado para staging) | Snapshots do catálogo + o cursor de sincronização; **nunca** bytes de blocklists de terceiros |
| **Cloudflare D1** (o banco de feedback de ajuda) | Votos anônimos somente-acréscimo de feedback de artigos de ajuda |

O Worker acessa o Supabase via PostgREST (`/rest/v1`) e Auth (`/auth/v1`) usando uma credencial service-role do Supabase — não há SDK do Supabase no servidor; as chamadas são `fetch` puro via os helpers `supabase()` / `supabaseAuth()`.

Status: **Implementado**.

## 2. Worker lavasec-api

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, um binding R2 → o bucket de produção (um bucket de preview separado para staging), um binding D1 → o banco de feedback de ajuda, e **dois cron triggers**: um que dispara a cada 6 horas (sincronização de blocklists + publicação do catálogo) e um que dispara a cada 2 minutos (promoção de triagem de relatórios de bug). É servido em `api.lavasecurity.app`.

### 2.1 Superfície da API

O roteamento é um dispatcher `route()` plano. Tudo está **Implementado** salvo indicação em contrário.

**Público / não autenticado**

| Método e caminho | Handler | Observações |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Serve `catalog/latest.json` do R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Serve `catalog/{version}.json` do R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (padrão 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anônimo, login opcional; apenas campos de debug em allow-list |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto anônimo de artigo → **D1**, não Supabase |

> O upload de anexos (uma antiga rota `PUT /v1/bug-reports/:id/attachment`) foi **removido**; capturas de tela e detalhes extras são tratados por um canal de suporte mediado por humanos. O Worker apenas faz, com best-effort, a exclusão de qualquer objeto de anexo legado durante a exclusão da conta.

**Conta (token de acesso do Supabase obrigatório)**

| Método e caminho | Handler | Observações |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valida o token de acesso do usuário, exclui as linhas dele + quaisquer objetos de anexo legados no R2, e então exclui o usuário do Supabase Auth com o service role |
| `GET /v1/account/qa-access` | `accountQAAccess` | Retorna `is_developer` da allowlist `qa_developers` somente-service-role |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Faz upsert de uma linha de `entitlements` (plano `lava_security_plus`) a partir de um JWS do StoreKit verificado pelo cliente |

> **Nenhuma rota `/v1/backup`.** A recuperação de backup assistida por passkey agora é **zero-knowledge** e totalmente no lado do cliente (veja §4.3 e §5); o Worker não tem rotas `/v1/backup/*` nem código de WebAuthn/passkey.

**Admin (uma chave de API de admin via `requireAdmin`)**

| Método e caminho | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Os endpoints HTTP de admin são protegidos por uma chave de API de admin. O caminho de sincronização agendado (cron) **não** chama essas rotas HTTP — ele invoca a lógica de sincronização (`syncBlocklistSources`) diretamente dentro do handler `scheduled`.

**Hosts de sonda de QA** — requisições aos quatro hosts `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) sofrem um curto-circuito antes do roteamento e retornam um PNG 1×1 `no-store` via `getQAProbePixel`. Esses não são gravados no Supabase nem no R2.

### 2.2 Bindings e cron

- **Binding R2** — `catalog/latest.json`, `catalog/{version}.json` e o cursor de round-robin `catalog/scheduled-sync-cursor.json`. **Ele nunca armazena bytes de blocklists de terceiros.** (Objetos de anexo legados de relatórios de bug são apenas *excluídos* — best-effort durante a exclusão da conta — nunca gravados.)
- **Binding D1** — linhas anônimas somente-acréscimo de `article_id` / `locale` / `vote` / `path`; mantidas separadas do Supabase por design.
- **Cron (`scheduled`)** — o handler ramifica conforme o id do cron:
  - **A cada 6 horas** — sincroniza **uma** fonte por execução, em round-robin via o cursor R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), e então republica o catálogo. Distribuir a carga evita martelar todos os upstreams de uma vez.
  - **A cada 2 minutos** — executa um caminho interno de triagem de relatórios de bug que promove novos relatórios anônimos para uma fila interna de issue-tracker, avançando seu próprio cursor de watermark. Isso é ferramental de operações internas; os identificadores de issue-tracker/notificação são configuração, não parte da API pública.

## 3. Catálogo e imposição do source-url-only

Esta é a parte do backend mais específica da postura de conformidade da Lava, então ela ganha mecanismos do lado do servidor.

### 3.1 O modelo source-url-only

> **Source-url-only:** modelo de distribuição em conformidade com GPL/PI: a Lava publica apenas a URL do upstream + hashes aceitos; o dispositivo busca/analisa as listas por conta própria. A Lava **nunca** armazena, espelha, transforma ou serve bytes de blocklists de terceiros.

Cada linha de `blocklist_sources` carrega `redistribution_mode`, cujo único valor permitido é `"source_url_only"`. O catálogo que o dispositivo lê (`/v1/catalog`, `schema_version` 2) divide as entradas em `sources[]` e `guardrails[]`; cada entrada carrega a `source_url` do upstream mais os `accepted_source_hashes` (SHA-256 + tamanho em bytes + contagem de entradas + `reviewed_at` + status `accepted`) — nunca os bytes da lista. Veja `formatCatalogEntry`.

> **Descartado:** um design anterior espelhava arquivos de lista GPL com bytes preservados no R2 (o plano de conformidade GPL-raw-R2). Ele foi **substituído em 2026-05-25** pelo source-url-only. A Lava não armazena nem serve mais bytes de blocklists de terceiros. O nome da tabela `mirror_events` é uma herança legada daquele design abandonado — agora é apenas o log de auditoria de sincronização/publicação.

### 3.2 Como o Worker impõe isso nas gravações

O caminho de sincronização (`syncOneBlocklist`, admin e cron) busca cada `source_url` upstream, normaliza/valida **localmente no Worker apenas para calcular metadados** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), grava uma linha de `blocklist_versions` e republica. As chaves de armazenamento de bytes são fixadas em null por código:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Uma migração (`20260525000000_add_blocklist_distribution_mode.sql`) tornou essas colunas nullable e definiu os valores existentes como null, de modo que a postura no-mirror também é imposta no nível do schema. O catálogo publicado é gravado em **ambos** `catalog/{version}.json` e `catalog/latest.json` no R2 (`publishCatalog`).

### 3.3 Guardrails de normalização (somente metadados)

A normalização do lado do Worker (`normalizeBlocklist`) filtra domínios protegidos, impõe limites e faz dedupe+ordenação. Isso serve puramente para calcular metadados confiáveis; o **dispositivo revalida os hashes aceitos** quando baixa a lista real, então isso por si só não é uma fronteira de segurança. Constantes principais:

- `PROTECTED_SUFFIXES` — remove qualquer regra que corresponda a domínios de Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, de modo que um upstream envenenado não possa bloquear a própria infraestrutura da Lava nem os provedores de login.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 O que é publicável

`isPublicBlocklistSource` só publica uma fonte quando `status` é `sync` ou `nosync`, `redistribution_mode === "source_url_only"`, **e** `isAllowedLaunchGPLSource` passa. O gate de GPL-de-lançamento (`isAllowedLaunchGPLSource`) permite fontes não-GPL livremente, mas restringe fontes GPL-3.0 aos prefixos de `list_id` `hagezi-` ou `oisd-`.

### 3.5 Fontes seedadas e habilitadas por padrão

As fontes curadas são seedadas como metadados source-url-only via migrações (HaGeZi, OISD, Block List Project, Phishing.Database, AdGuard). A migração de baixo risco (`20260526000000_low_risk_blocklist_sources.sql`) inicialmente seedava `blocklistproject-basic` (Unlicense) com `default_enabled = true`, forçava **todas as fontes GPL (HaGeZi/OISD) com `default_enabled = false`** pendente de parecer jurídico, e estacionava o AdGuard DNS Filter em `license_review`. **Esse seed inicial de Basic-por-padrão foi posteriormente substituído** — a migração de alinhamento abaixo vira o Basic para `false` e Phishing + Scam para `true` (o padrão servido atual). Status: **Implementado**.

> **Os padrões do catálogo coincidem com o cliente.** O conjunto `default_enabled` do catálogo agora é **{Block List Project Phishing, Block List Project Scam}**, coincidindo com o padrão recomendado do iOS (`AppConfiguration.lavaRecommendedDefaults`, em `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`). Uma migração define `blocklistproject-basic default_enabled = false` e `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`, de modo que os metadados servidos sejam verdadeiros. (a decisão de alinhamento já está entregue.) Note que `default_enabled` é informativo: o verdadeiro gate de tier é o **orçamento de regras de filtro (Free 500K / Plus 2M)**, não a contagem de listas. A justificativa jurídica para publicar URLs (não bytes) está em [decisão de conformidade GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres

Um projeto Supabase Postgres. O RLS está habilitado em **toda** tabela pública.

### 4.1 Schema central

`20260516034033_backend_core.sql` cria a fundação (RLS habilitado em todas as 7 tabelas públicas):

- **`profiles`, `user_settings`, `entitlements`** — estado de conta por usuário. Um trigger `handle_new_user()` cria automaticamente as linhas de `profiles` + `user_settings` no insert de `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — as tabelas de metadados do catálogo. Uma fonte é uma lista upstream curada (`list_id`, `source_url`, licença, risco, `default_enabled`, `status`, `redistribution_mode`); uma versão é o metadado de um snapshot sincronizado (hashes, `entry_count`, `byte_size`), ligada de volta via `latest_version_id`.
- **`mirror_events`** — log de auditoria somente-service-role de eventos `sync` / `catalog_publish` (nome legado; veja §3.1).
- **`bug_reports`** — relatórios anônimos somente-service-role.

Migrações posteriores adicionam **`user_backups`** (§4.3) e **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modelo de RLS

| Tabela(s) | Política | Efeito |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | por usuário `auth.uid() = user_id` | cada usuário vê apenas as próprias linhas |
| `blocklist_sources` | leitura pública onde `status in ('sync','nosync')` (`backend_core.sql:262-266`) | qualquer um pode ler fontes curadas e elegíveis para sincronização |
| `blocklist_versions` | leitura pública onde `validation_status = 'published'` (`backend_core.sql:268-272`) | qualquer um pode ler metadados de versão publicada |
| `bug_reports`, `mirror_events` | `using(false)` explícito (`20260516034136_backend_core_advisor_fixes.sql`) | sem acesso anon/autenticado — o Worker usa o service role |
| `qa_developers` | RLS ligado + **revoke all de anon, authenticated** | somente-service-role; a allowlist de QA nunca é legível pelo cliente |

A separação importa: relatórios de bug anônimos precisam ser *inseríveis* pelo Worker sem serem *legíveis* pelos clientes, e a allowlist de QA só pode ser lida pelo service role.

### 4.3 Auth e o envelope de backup criptografado

O **Auth** é opcional. O login é **apenas Apple + Google** (e-mail/senha está **Descartado**). Ambos usam o grant nativo `id_token` trocado no Supabase Auth `auth/v1/token?grant_type=id_token` com um nonce hasheado; o app armazena apenas a sessão resultante de forma local ao dispositivo no Keychain. O fluxo do lado do cliente vive no app iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — veja [Contas e backup](./accounts-and-backup.md) para o modelo completo de conta/backup.

> **Backup zero-knowledge:** envelope AES-256-GCM do lado do cliente; apenas o texto cifrado + metadados não secretos são enviados ao `user_backups` do Supabase (RLS por usuário). O servidor não consegue descriptografar sem um segredo de posse do usuário.

O fato crucial de backend: **o cliente iOS lê/grava `user_backups` diretamente via Supabase PostgREST sob RLS por usuário** (upsert em `user_id`, escopado pelo token de acesso). **Não há rotas `/v1/backup`** no Worker, de jeito nenhum. O Worker toca em `user_backups` exatamente uma vez: para excluí-lo durante a exclusão da conta (`deleteAccount`).

`user_backups` armazena apenas texto cifrado opaco + metadados não secretos do envelope (parâmetros/salts de KDF, nonces, rótulos de slots de chave, dicas de schema do cliente). Limites de tamanho (`20260605000000_tighten_backup_envelope_constraints.sql`): texto cifrado ≤ 262144 bytes (256 KiB) / ≤ 349528 caracteres, metadados ≤ 32768 bytes (32 KiB). O banco nunca armazena configurações, senhas, frases ou chaves em texto puro.

### 4.4 Exclusão de conta

`POST /v1/account/delete` valida o token de acesso do usuário e então exclui as linhas de `bug_reports` dele (e qualquer objeto de anexo legado correspondente no R2), `user_backups`, `entitlements`, `user_settings` e `profiles`, e por fim exclui o usuário do Supabase Auth via o endpoint service-role `/admin/users`. Ele retorna apenas um status de exclusão + os provedores vinculados. Status: **Implementado** (o frontmatter do plano diz `status: Done` e o arquivo está em `plans/implemented/`; uma anotação **no corpo** desatualizada ainda diz "Backlog", mas a pasta de lane + a presença no código tornam o recurso entregue).

### 4.5 Espelhamento de direitos da App Store

`POST /v1/account/entitlements/app-store-sync` faz upsert de uma linha de `entitlements` (plano `lava_security_plus`) a partir de um JWS de transação do StoreKit verificado pelo cliente, com conflito por `user_id`. O `verification_status` armazenado é literalmente `"client_verified_storekit"` — o servidor **não** revalida o JWS. IDs de produto permitidos: `lava_security_plus_{monthly,yearly,lifetime}`.

> O espelhamento está **Implementado**; a **verificação de JWS do lado do servidor está Planejada** (ainda não construída). O JWS assinado é armazenado para verificação posterior. Note o modelo de tier em outras partes: o direito do app é local (`isPaid`) com **nenhuma sincronização de backend ainda** como fonte da verdade — esta linha é um espelho, não o gate.

## 5. Recuperação assistida por passkey (zero-knowledge)

A recuperação de backup assistida por passkey é **zero-knowledge** e totalmente do lado do cliente. O material de chave de recuperação é derivado no dispositivo a partir da saída **WebAuthn PRF / hmac-secret** da passkey; o servidor não armazena **nenhum** segredo de recuperação, não registra **nenhuma** passkey e não emite **nenhum** desafio WebAuthn. Não há caminho de escrow controlado pelo servidor.

As tabelas de escrow que um design anterior usava (`backup_passkey_recovery`, `backup_passkey_challenges`) foram removidas antes do lançamento, e o Worker não carrega rotas `/v1/backup/*` nem código de WebAuthn/passkey. (Uma entrada `@simplewebauthn/server` permanece no `package.json` do Worker como uma dependência sobrando, não usada.)

O lado do cliente vive no app iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` conduz a criação/assertion da passkey capaz de PRF, e `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva o slot da saída hmac-secret. A saída do PRF é lida apenas durante a assertion e nunca sai do dispositivo. Um provedor de passkey sem PRF não consegue dar suporte a um slot zero-knowledge, então a configuração falha cedo e o usuário recai sobre uma frase de recuperação. Status: **Implementado**.

## 6. Worker lavasec-email

Somente recebe-e-encaminha. Ele encaminha `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` para uma caixa de entrada de operador verificada, rejeita destinatários desconhecidos e mensagens acima de 10 MiB, e **não armazena os corpos dos e-mails**. As respostas automáticas de suporte estão codificadas, mas ficam atrás do envio de e-mail pago do Cloudflare (adiado). As constantes de roteamento vivem em `email-service.ts:9` (`ROUTED_RECIPIENTS`); o handler de entrada é `handleInboundEmail`. Status: **Implementado** (caminho de resposta automática **Planejado**/adiado).

## 7. Configuração e deploy

- **A configuração é o `wrangler.toml`, que está no gitignore**; `wrangler.toml.example` é o template versionado. Trate o `wrangler.toml` local como canônico para valores específicos de ambiente.
- **Vars** (não secretas, em `[vars]`): a URL do Supabase, a origem pública da API (`https://api.lavasecurity.app`), o TTL de cache do catálogo (padrão 300s), um limite de tamanho de relatório de bug, um toggle de auditoria de exclusão de conta, e uma flag de aceleração do runtime do Workers. A triagem interna de relatórios de bug adiciona uma chave de fila de triagem interna e uma origem de dashboard usada ao compor links de triagem.
- **Secrets** (via `wrangler secret put`): uma credencial service-role do Supabase, uma chave de API de admin, e — para o caminho de triagem de relatórios de bug — uma chave de API do issue-tracker e um webhook opcional de notificação de chat.
- **O deploy é manual**: `npm run deploy` → `wrangler deploy`. Não há CI para o Worker.
- **Roteamento do Cloudflare**: `lavasecurity.app` permanece no Pages; `api.lavasecurity.app` e `*.qa-probe.lavasecurity.app` resolvem para este Worker.
- **Compatibilidade**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` está definido nas vars, mas não é referenciado pelo código do Worker; é uma flag de aceleração do runtime do Workers, e não uma configuração da aplicação.

## 8. Invariantes de privacidade (o que está e o que não está aqui)

Um checklist rápido para quem for estender o backend — nenhum destes pode ser quebrado silenciosamente:

1. **Nenhuma telemetria de DNS/navegação.** Não há tabela para consultas de DNS de rotina nem telemetria por domínio. A filtragem permanece no dispositivo.
2. **Nenhum byte de blocklist de terceiros** no R2 ou no Postgres — apenas `source_url` + hashes aceitos (§3).
3. **`user_backups` é opaco** — apenas texto cifrado + metadados não secretos; o cliente (não o Worker) o grava sob RLS (§4.3).
4. **Isolamento por service role** para `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Todos os caminhos de backup são zero-knowledge** — incluindo a recuperação assistida por passkey, cujo material de chave é derivado no lado do cliente a partir da saída WebAuthn PRF/hmac-secret. O servidor não armazena nenhum segredo de recuperação e não executa nenhum WebAuthn (§5).

## Veja também

- [Visão geral do sistema](./system-overview.md) — o sistema inteiro em uma página, incluindo as fronteiras de confiança.
- [Cliente iOS](./ios-client.md) — o lado do dispositivo que consome este backend.
- [Contas e backup](./accounts-and-backup.md) — auth do lado do cliente, o envelope AES-256-GCM, os slots de chave e as frases de recuperação.
- [Filtragem de DNS e blocklists](./dns-filtering-and-blocklists.md) — o lado do dispositivo do catálogo: download direto do upstream, parse/normalização e o orçamento de regras de filtro.
- [Decisão de conformidade GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — por que o catálogo publica URLs, não bytes.
- **Tiers e monetização** (interno) — o orçamento de regras de filtro (Free 500K / Plus 2M) que é o verdadeiro gate Free/Plus.
- **Registro de risco de PI** (interno) — a justificativa de PI/conformidade por trás do source-url-only.
