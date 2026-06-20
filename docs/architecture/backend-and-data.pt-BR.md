---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Backend e Dados

> **Público:** engenheiros de backend. **Escopo:** a camada de servidor — os dois Cloudflare Workers, o esquema/RLS/auth do Supabase Postgres, os armazenamentos Cloudflare R2 e D1, toda a superfície da API HTTP, configuração e deploy, e como o source-url-only é garantido no servidor.
>
> **Referência autoritativa:** quando um plano e o código divergem, **o código vence** — as divergências são apontadas no próprio texto. Os rótulos de status seguem a legenda do conjunto de docs: **Implementado** (entregue e confirmado no código), **Em andamento** (parcialmente concluído), **Planejado** (projetado, ainda não construído), **Descartado** (rejeitado ou revertido).

## 1. O formato do backend

O backend é deliberadamente pequeno e preserva a privacidade. Ele é uma borda de metadados e contas, não um serviço de filtragem. **Toda a filtragem de DNS acontece no aparelho; a Lava nunca roteia sua navegação pelos servidores dela e nunca recebe o fluxo de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado opaco por usuário e diagnósticos anonimizados que você escolhe enviar.** Não há tabelas para consultas DNS de rotina nem telemetria por domínio, e o login na conta é opcional e nunca exigido para a proteção.

A camada de servidor é dividida em dois componentes: o código do Worker de backend e o esquema do banco de dados.

| Componente | Função |
|---|---|
| **Worker lavasec-api** | Borda principal: leituras públicas do catálogo, sincronização de blocklists e publicação do catálogo por admin+cron, relatórios de bug anônimos, feedback de ajuda, exclusão de conta, espelhamento de direitos da App Store, pixels de sondagem de QA, verificação de acesso de QA da conta, promoção de triagem de relatórios de bug |
| **Worker lavasec-email** | Encaminhador somente-recebimento do Cloudflare Email Routing para `@lavasecurity.app` |
| **Supabase Postgres** (um projeto Supabase Postgres) | Contas, backups criptografados, metadados do catálogo, tabelas somente-service-role; RLS em toda tabela pública |
| **Cloudflare R2** (um bucket de produção, com um bucket de preview separado para o staging) | Snapshots do catálogo + o cursor de sincronização; **nunca** bytes de blocklists de terceiros |
| **Cloudflare D1** (o banco de feedback de ajuda) | Votos de feedback anônimos de artigos de ajuda, somente-acréscimo |

O Worker acessa o Supabase via PostgREST (`/rest/v1`) e Auth (`/auth/v1`) usando uma credencial service-role do Supabase — não há SDK do Supabase no servidor; as chamadas são `fetch` puro através dos helpers `supabase()` / `supabaseAuth()`.

Status: **Implementado**.

## 2. Worker lavasec-api

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, um binding R2 → o bucket de produção (um bucket de preview separado para o staging), um binding D1 → o banco de feedback de ajuda, e **dois gatilhos de cron**: um que dispara a cada 6 horas (sincronização de blocklists + publicação do catálogo) e um que dispara a cada 2 minutos (promoção de triagem de relatórios de bug). Ele é servido em `api.lavasecurity.app`.

### 2.1 Superfície da API

O roteamento é um dispatcher `route()` plano. Tudo é **Implementado**, salvo indicação em contrário.

**Público / sem autenticação**

| Método e caminho | Handler | Notas |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Serve `catalog/latest.json` do R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Serve `catalog/{version}.json` do R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (padrão 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anônimo, login opcional; somente campos de debug em lista de permissão |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto anônimo em artigo → **D1**, não Supabase |

> O upload de anexo (a antiga rota `PUT /v1/bug-reports/:id/attachment`) foi **removido**; capturas de tela e detalhes adicionais são tratados por um canal de suporte mediado por pessoas. O Worker apenas faz, com melhor esforço, a exclusão de qualquer objeto de anexo legado durante a exclusão de conta.

**Conta (requer token de acesso do Supabase)**

| Método e caminho | Handler | Notas |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valida o token de acesso do usuário, exclui as linhas dele + quaisquer objetos de anexo R2 legados, e então exclui o usuário do Supabase Auth com a service role |
| `GET /v1/account/qa-access` | `accountQAAccess` | Retorna `is_developer` da lista de permissão somente-service-role `qa_developers` |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Faz upsert de uma linha em `entitlements` (plano `lava_security_plus`) a partir de um StoreKit JWS verificado pelo cliente |

> **Nenhuma rota `/v1/backup`.** A recuperação de backup assistida por passkey agora é **zero-knowledge** e totalmente do lado do cliente (veja §4.3 e §5); o Worker não tem rotas `/v1/backup/*` nem código de WebAuthn/passkey.

**Admin (uma chave de API admin via `requireAdmin`)**

| Método e caminho | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Os endpoints HTTP de admin são protegidos por uma chave de API admin. O caminho de sincronização agendado (cron) **não** chama essas rotas HTTP — ele invoca a lógica de sincronização (`syncBlocklistSources`) diretamente dentro do handler `scheduled`.

**Hosts de sondagem de QA** — as requisições aos quatro hosts `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) têm curto-circuito antes do roteamento e retornam um PNG 1×1 com `no-store` via `getQAProbePixel`. Esses não são gravados no Supabase nem no R2.

### 2.2 Bindings e cron

- **Binding R2** — `catalog/latest.json`, `catalog/{version}.json` e o cursor round-robin `catalog/scheduled-sync-cursor.json`. **Ele nunca armazena bytes de blocklists de terceiros.** (Objetos de anexo legados de relatórios de bug são apenas *excluídos* — com melhor esforço durante a exclusão de conta — nunca gravados.)
- **Binding D1** — linhas anônimas somente-acréscimo de `article_id` / `locale` / `vote` / `path`; mantidas separadas do Supabase por design.
- **Cron (`scheduled`)** — o handler ramifica conforme o id do cron:
  - **A cada 6 horas** — sincroniza **uma** fonte por execução, em round-robin via o cursor do R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), e então republica o catálogo. Distribuir a carga evita sobrecarregar todas as fontes upstream de uma vez.
  - **A cada 2 minutos** — roda um caminho interno de triagem de relatórios de bug que promove novos relatórios anônimos para uma fila de rastreamento de issues interna, avançando seu próprio cursor de marca d'água. Isso é ferramental de operações interno; os identificadores de rastreador de issues/notificações são configuração, não parte da API pública.

## 3. Catálogo e a garantia do source-url-only

Esta é a parte do backend mais específica da postura de conformidade da Lava, então ela ganha reforço no lado do servidor.

### 3.1 O modelo source-url-only

> **Source-url-only:** modelo de distribuição em conformidade com GPL/IP: a Lava publica apenas a URL upstream + hashes aceitos; o aparelho busca/analisa as listas por conta própria. A Lava **nunca** armazena, espelha, transforma nem serve bytes de blocklists de terceiros.

Cada linha de `blocklist_sources` carrega `redistribution_mode`, cujo único valor permitido é `"source_url_only"`. O catálogo que o aparelho lê (`/v1/catalog`, `schema_version` 2) separa as entradas em `sources[]` e `guardrails[]`; cada entrada carrega a `source_url` upstream mais `accepted_source_hashes` (SHA-256 + tamanho em bytes + contagem de entradas + `reviewed_at` + status `accepted`) — nunca os bytes da lista. Veja `formatCatalogEntry`.

> **Descartado:** um design anterior espelhava no R2 arquivos de listas GPL com bytes preservados (o plano de conformidade GPL-raw-R2). Ele foi **substituído em 2026-05-25** pelo source-url-only. A Lava não armazena mais nem serve bytes de blocklists de terceiros. O nome da tabela `mirror_events` é um resquício legado daquele design abandonado — agora ele é apenas o log de auditoria de sincronização/publicação.

### 3.2 Como o Worker garante isso nas escritas

O caminho de sincronização (`syncOneBlocklist`, admin e cron) busca cada `source_url` upstream, normaliza/valida **localmente, apenas no Worker, só para calcular metadados** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), grava uma linha em `blocklist_versions` e republica. As chaves de armazenamento de bytes são gravadas como null fixo:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Uma migração (`20260525000000_add_blocklist_distribution_mode.sql`) deixou essas colunas anuláveis e definiu os valores existentes como null, de modo que a postura de não-espelhamento também é garantida no nível do esquema. O catálogo publicado é gravado em **ambos** `catalog/{version}.json` e `catalog/latest.json` no R2 (`publishCatalog`).

### 3.3 Guardrails de normalização (somente metadados)

A normalização no Worker (`normalizeBlocklist`) filtra domínios protegidos, aplica limites e remove duplicatas + ordena. Isso serve apenas para calcular metadados confiáveis; o **aparelho revalida os hashes aceitos** quando baixa a lista de verdade, então isso, por si só, não é uma fronteira de segurança. Constantes principais:

- `PROTECTED_SUFFIXES` — remove qualquer regra que corresponda a domínios da Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, de modo que uma fonte upstream comprometida não consiga bloquear a própria infraestrutura da Lava nem os provedores de login.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 O que é publicável

`isPublicBlocklistSource` só publica uma fonte quando `status` é `sync` ou `nosync`, `redistribution_mode === "source_url_only"`, **e** `isAllowedLaunchGPLSource` passa. O portão de GPL de lançamento (`isAllowedLaunchGPLSource`) permite fontes não-GPL livremente, mas restringe fontes GPL-3.0 aos prefixos de `list_id` `hagezi-` ou `oisd-`.

### 3.5 Fontes pré-carregadas e habilitadas por padrão

Fontes curadas são pré-carregadas como metadados source-url-only via migrações (HaGeZi, OISD, Block List Project, Phishing.Database, AdGuard). A migração de baixo risco (`20260526000000_low_risk_blocklist_sources.sql`) inicialmente carregou `blocklistproject-basic` (Unlicense) com `default_enabled = true`, forçou **todas as fontes GPL (HaGeZi/OISD) `default_enabled = false`** aguardando o jurídico, e estacionou o AdGuard DNS Filter em `license_review`. **Esse carregamento inicial com Basic por padrão foi depois substituído** — a migração de alinhamento abaixo muda Basic para `false` e Phishing + Scam para `true` (o padrão servido atual). Status: **Implementado**.

> **Os padrões do catálogo correspondem ao cliente.** O conjunto `default_enabled` do catálogo agora é **{Block List Project Phishing, Block List Project Scam}**, correspondendo ao padrão recomendado do iOS (`AppConfiguration.lavaRecommendedDefaults`, em `lavasec-ios: Sources/LavaSecCore/OnboardingDefaults.swift`). Uma migração define `blocklistproject-basic default_enabled = false` e `blocklistproject-phishing` / `blocklistproject-scam default_enabled = true`, de modo que os metadados servidos sejam verdadeiros. (a decisão de alinhamento já está entregue.) Note que `default_enabled` é informativo: o portão de plano de verdade é o **orçamento de regras de filtro (Free 500K / Plus 2M)**, não a contagem de listas. A justificativa legal para publicar URLs (não bytes) está em [decisão de conformidade GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Supabase Postgres

Um projeto Supabase Postgres. O RLS está habilitado em **toda** tabela pública.

### 4.1 Esquema central

`20260516034033_backend_core.sql` cria a base (RLS habilitado em todas as 7 tabelas públicas):

- **`profiles`, `user_settings`, `entitlements`** — estado da conta por usuário. Um trigger `handle_new_user()` cria automaticamente linhas em `profiles` + `user_settings` ao inserir em `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — as tabelas de metadados do catálogo. Uma fonte é uma lista upstream curada (`list_id`, `source_url`, licença, risco, `default_enabled`, `status`, `redistribution_mode`); uma versão é o metadado de um snapshot sincronizado (hashes, `entry_count`, `byte_size`), ligado de volta via `latest_version_id`.
- **`mirror_events`** — log de auditoria somente-service-role de eventos de `sync` / `catalog_publish` (nome legado; veja §3.1).
- **`bug_reports`** — relatórios anônimos somente-service-role.

Migrações posteriores adicionam **`user_backups`** (§4.3) e **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modelo de RLS

| Tabela(s) | Política | Efeito |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | `auth.uid() = user_id` por usuário | cada usuário vê apenas as próprias linhas |
| `blocklist_sources` | leitura pública onde `status in ('sync','nosync')` (`backend_core.sql:262-266`) | qualquer um pode ler fontes curadas e elegíveis a sincronização |
| `blocklist_versions` | leitura pública onde `validation_status = 'published'` (`backend_core.sql:268-272`) | qualquer um pode ler metadados de versões publicadas |
| `bug_reports`, `mirror_events` | `using(false)` explícito (`20260516034136_backend_core_advisor_fixes.sql`) | sem acesso anônimo/autenticado — o Worker usa a service role |
| `qa_developers` | RLS ligado + **revoke all from anon, authenticated** | somente-service-role; a lista de permissão de QA nunca é legível pelo cliente |

A separação importa: relatórios de bug anônimos precisam ser *inseríveis* pelo Worker sem serem *legíveis* pelos clientes, e a lista de permissão de QA só pode ser lida pela service role.

### 4.3 Auth e o envelope de backup criptografado

A **auth** é opcional. O login é **apenas Apple + Google** (e-mail/senha foi **Descartado**). Ambos usam o grant nativo `id_token` trocado no Supabase Auth `auth/v1/token?grant_type=id_token` com um nonce em hash; o app guarda apenas a sessão resultante localmente no aparelho, na Keychain. O fluxo do lado do cliente fica no app iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — veja [Contas e Backup](./accounts-and-backup.md) para o modelo completo de conta/backup.

> **Backup zero-knowledge:** envelope AES-256-GCM do lado do cliente; apenas o texto cifrado + metadados não secretos sobem para o `user_backups` do Supabase (RLS por usuário). O servidor não consegue descriptografar sem um segredo que fica com o usuário.

O fato crucial de backend: **o cliente iOS lê/escreve `user_backups` diretamente via Supabase PostgREST sob RLS por usuário** (upsert em `user_id`, restrito pelo token de acesso). **Não há rotas `/v1/backup`** no Worker. O Worker toca em `user_backups` exatamente uma vez: para excluí-lo durante a exclusão de conta (`deleteAccount`).

`user_backups` armazena apenas texto cifrado opaco + metadados de envelope não secretos (parâmetros/salts de KDF, nonces, rótulos de key-slot, dicas de esquema do cliente). Limites de tamanho (`20260605000000_tighten_backup_envelope_constraints.sql`): texto cifrado ≤ 262144 bytes (256 KiB) / ≤ 349528 caracteres, metadados ≤ 32768 bytes (32 KiB). O banco nunca armazena configurações, senhas, frases ou chaves em texto plano.

### 4.4 Exclusão de conta

`POST /v1/account/delete` valida o token de acesso do usuário, e então exclui as linhas dele em `bug_reports` (e qualquer objeto de anexo R2 legado correspondente), `user_backups`, `entitlements`, `user_settings` e `profiles`, e por fim exclui o usuário do Supabase Auth via o endpoint `/admin/users` da service role. Ele retorna apenas um status de exclusão + os provedores vinculados. Status: **Implementado** (o frontmatter do plano diz `status: Done` e o arquivo está em `plans/implemented/`; uma anotação **no corpo** desatualizada ainda diz "Backlog", mas a pasta da fase + a presença no código confirmam que está entregue).

### 4.5 Espelhamento de direitos da App Store

`POST /v1/account/entitlements/app-store-sync` faz upsert de uma linha em `entitlements` (plano `lava_security_plus`) a partir de um JWS de transação StoreKit verificado pelo cliente, com conflito por `user_id`. O `verification_status` armazenado é literalmente `"client_verified_storekit"` — o servidor **não** revalida o JWS. IDs de produto permitidos: `lava_security_plus_{monthly,yearly,lifetime}`.

> O espelhamento é **Implementado**; a **verificação do JWS no lado do servidor é Planejada** (ainda não construída). O JWS assinado é armazenado para verificação posterior. Note o modelo de plano em outro lugar: o direito do app é local (`isPaid`) **ainda sem sincronização de backend** como fonte da verdade — esta linha é um espelho, não o portão.

## 5. Recuperação assistida por passkey (zero-knowledge)

A recuperação de backup assistida por passkey é **zero-knowledge** e totalmente do lado do cliente. O material da chave de recuperação é derivado no aparelho a partir da saída **WebAuthn PRF / hmac-secret** da passkey; o servidor não armazena **nenhum** segredo de recuperação, não registra **nenhuma** passkey e não emite **nenhum** desafio WebAuthn. Não há caminho de escrow gerenciado pelo servidor.

As tabelas de escrow que um design anterior usava (`backup_passkey_recovery`, `backup_passkey_challenges`) foram removidas antes do lançamento, e o Worker não tem rotas `/v1/backup/*` nem código de WebAuthn/passkey. (Uma entrada `@simplewebauthn/server` permanece no `package.json` do Worker como uma dependência sobrando, sem uso.)

O lado do cliente fica no app iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` conduz a criação/asserção de passkey com PRF, e `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva o slot a partir da saída hmac-secret. A saída PRF é lida apenas durante a asserção e nunca deixa o aparelho. Um provedor de passkey sem PRF não consegue sustentar um slot zero-knowledge, então a configuração falha cedo e o usuário recorre a uma frase de recuperação. Status: **Implementado**.

## 6. Worker lavasec-email

Somente receber e encaminhar. Ele encaminha `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` para uma caixa de entrada de operador verificada, rejeita destinatários desconhecidos e mensagens acima de 10 MiB, e **não armazena corpos de e-mail**. As respostas automáticas de suporte estão codificadas, mas ficam atrás do envio de e-mail pago do Cloudflare (adiado). As constantes de roteamento ficam em `email-service.ts:9` (`ROUTED_RECIPIENTS`); o handler de entrada é `handleInboundEmail`. Status: **Implementado** (o caminho de resposta automática é **Planejado**/adiado).

## 7. Configuração e deploy

- **A configuração é o `wrangler.toml`, que está no gitignore**; `wrangler.toml.example` é o template versionado. Trate o `wrangler.toml` local como canônico para os valores específicos de ambiente.
- **Vars** (não secretas, em `[vars]`): a URL do Supabase, a origem pública da API (`https://api.lavasecurity.app`), o TTL de cache do catálogo (padrão 300s), um limite de tamanho de relatório de bug, um toggle de auditoria de exclusão de conta e uma flag de aceleração do runtime do Workers. A triagem interna de relatórios de bug adiciona uma chave de fila de triagem interna e uma origem de dashboard usada ao compor links de triagem.
- **Secrets** (via `wrangler secret put`): uma credencial service-role do Supabase, uma chave de API admin e — para o caminho de triagem de relatórios de bug — uma chave de API do rastreador de issues e um webhook opcional de notificação em chat.
- **O deploy é manual**: `npm run deploy` → `wrangler deploy`. Não há CI para o Worker.
- **Roteamento do Cloudflare**: `lavasecurity.app` permanece no Pages; `api.lavasecurity.app` e `*.qa-probe.lavasecurity.app` resolvem para este Worker.
- **Compatibilidade**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` está definido em vars, mas não é referenciado pelo código do Worker; é uma flag de aceleração do runtime do Workers, e não uma configuração da aplicação.

## 8. Invariantes de privacidade (o que está e o que não está aqui)

Um checklist rápido para quem for estender o backend — nenhum destes pode ser quebrado em silêncio:

1. **Sem telemetria de DNS/navegação.** Não há tabela para consultas DNS de rotina nem telemetria por domínio. A filtragem fica no aparelho.
2. **Sem bytes de blocklists de terceiros** no R2 ou no Postgres — apenas `source_url` + hashes aceitos (§3).
3. **`user_backups` é opaco** — apenas texto cifrado + metadados não secretos; o cliente (não o Worker) o escreve sob RLS (§4.3).
4. **Isolamento por service role** para `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Todos os caminhos de backup são zero-knowledge** — incluindo a recuperação assistida por passkey, cujo material de chave é derivado no cliente a partir da saída WebAuthn PRF/hmac-secret. O servidor não armazena segredo de recuperação e não roda WebAuthn (§5).

## Veja também

- [Visão geral do sistema](./system-overview.md) — o sistema inteiro em uma página, incluindo as fronteiras de confiança.
- [Cliente iOS](./ios-client.md) — o lado do aparelho que consome este backend.
- [Contas e Backup](./accounts-and-backup.md) — auth do lado do cliente, o envelope AES-256-GCM, key slots e frases de recuperação.
- [Filtragem de DNS e Blocklists](./dns-filtering-and-blocklists.md) — o lado do aparelho do catálogo: download direto da fonte upstream, parse/normalização e o orçamento de regras de filtro.
- [decisão de conformidade GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — por que o catálogo publica URLs, não bytes.
- **Planos e monetização** (interno) — o orçamento de regras de filtro (Free 500K / Plus 2M) que é o portão real entre Free/Plus.
- **Registro de risco de IP** (interno) — a justificativa de IP/conformidade por trás do source-url-only.
