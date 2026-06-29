---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Backend e Dados

> **Público:** engenheiros de backend. **Escopo:** a camada de servidor — os dois Cloudflare Workers, o esquema/RLS/auth do Postgres do Supabase, os armazenamentos Cloudflare R2 e D1, toda a superfície da API HTTP, configuração e deploy, e como o source-url-only é imposto no servidor.
>
> **Referência autoritativa:** quando um plano e o código divergem, **o código vence** — as divergências são apontadas inline. Os rótulos de status usam a legenda do conjunto de documentos: **Implementado** (lançado e confirmado no código), **Em andamento** (parcialmente entregue), **Planejado** (projetado, não construído), **Descartado** (rejeitado ou revertido).

## 1. O formato do backend

O backend é deliberadamente pequeno e preserva a privacidade. Ele é uma borda de metadados e contas, não um serviço de filtragem. **Toda a filtragem de DNS acontece no dispositivo; a Lava nunca roteia sua navegação pelos seus servidores e nunca recebe o fluxo de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado opaco por usuário e diagnósticos anonimizados que você escolhe enviar.** Não há tabelas para consultas DNS rotineiras ou telemetria por domínio, e o login na conta é opcional e nunca é exigido para a proteção.

A camada de servidor é dividida em dois componentes: o código do Worker de backend e o esquema do BD.

| Componente | Função |
|---|---|
| **Worker lavasec-api** | Borda principal: leituras públicas do catálogo, sincronização de blocklist admin+cron e publicação de catálogo, relatórios de bug anônimos, feedback de ajuda, exclusão de conta, espelhamento de entitlements da App Store, pixels de sonda de QA, verificação de acesso de QA da conta, promoção de triagem de relatórios de bug |
| **Worker lavasec-email** | Encaminhador somente-recebimento do Cloudflare Email Routing para `@lavasecurity.app` |
| **Postgres do Supabase** (um projeto Postgres do Supabase) | Contas, backups criptografados, metadados do catálogo, tabelas somente-service-role; RLS em toda tabela pública |
| **Cloudflare R2** (um bucket de produção, com um bucket de preview separado para staging) | Snapshots do catálogo + o cursor de sincronização; **nunca** bytes de blocklist de terceiros |
| **Cloudflare D1** (o banco de dados de feedback de ajuda) | Votos anônimos somente-append de feedback de artigos de ajuda |

O Worker alcança o Supabase via PostgREST (`/rest/v1`) e Auth (`/auth/v1`) usando uma credencial service-role do Supabase — não há SDK do Supabase no servidor; as chamadas são `fetch` cru via os helpers `supabase()` / `supabaseAuth()`.

Status: **Implementado**.

## 2. Worker lavasec-api

`wrangler.toml`: `name = "lavasec-api"`, `main = "src/index.ts"`, um binding R2 → o bucket de produção (um bucket de preview separado para staging), um binding D1 → o banco de dados de feedback de ajuda, e **dois cron triggers**: um que dispara a cada 6 horas (sincronização de blocklist + publicação de catálogo) e um que dispara a cada 2 minutos (promoção de triagem de relatórios de bug). Ele é servido em `api.lavasecurity.app`.

### 2.1 Superfície da API

O roteamento é um dispatcher `route()` plano. Tudo é **Implementado** salvo indicação em contrário.

**Público / não autenticado**

| Método e caminho | Handler | Notas |
|---|---|---|
| `GET /healthz` | inline | `{ ok: true, service: "lavasec-api" }` |
| `GET /v1/catalog` | `getCatalog(env, null)` | Serve `catalog/latest.json` do R2 |
| `GET /v1/catalog/:version` | `getCatalog(env, version)` | Serve `catalog/{version}.json` do R2; `Cache-Control: public, max-age=` `PUBLIC_CATALOG_CACHE_SECONDS` (padrão 300s) |
| `POST /v1/bug-reports` | `createBugReport` | Anônimo, login-opcional; apenas campos de depuração na allow-list |
| `POST /v1/help-feedback` | `createHelpFeedback` | Voto anônimo de artigo → **D1**, não Supabase |

> O upload de anexos (uma antiga rota `PUT /v1/bug-reports/:id/attachment`) foi **removido**; capturas de tela e detalhes extras são tratados via um canal de suporte mediado por humanos. O Worker apenas faz best-effort para excluir qualquer objeto de anexo legado durante a exclusão de conta.

**Conta (token de acesso do Supabase obrigatório)**

| Método e caminho | Handler | Notas |
|---|---|---|
| `POST /v1/account/delete` | `deleteAccount` | Valida o token de acesso do usuário, exclui suas linhas + quaisquer objetos de anexo R2 legados, depois exclui o usuário do Supabase Auth com a service role |
| `GET /v1/account/qa-access` | `accountQAAccess` | Retorna `is_developer` da allowlist `qa_developers` somente-service-role |
| `POST /v1/account/entitlements/app-store-sync` | `syncAppStoreEntitlement` | Faz upsert de uma linha `entitlements` (plano `lava_security_plus`) a partir de um StoreKit JWS verificado pelo cliente |

> **Sem rotas `/v1/backup`.** A recuperação de backup assistida por passkey agora é **zero-knowledge** e inteiramente do lado do cliente (ver §4.3 e §5); o Worker não tem rotas `/v1/backup/*` e nenhum código de WebAuthn/passkey.

**Admin (uma chave de API admin via `requireAdmin`)**

| Método e caminho | Handler |
|---|---|
| `POST /v1/admin/blocklists/sync` | `syncBlocklists` |
| `POST /v1/admin/catalog/publish` | `publishCatalog` |

> Os endpoints HTTP de admin são protegidos por uma chave de API admin. O caminho de sincronização agendado (cron) **não** chama essas rotas HTTP — ele invoca a lógica de sincronização (`syncBlocklistSources`) diretamente dentro do handler `scheduled`.

**Hosts de sonda de QA** — requisições aos quatro hosts `*.qa-probe.lavasecurity.app` (`allowed`/`blocked`/`exception`/`guardrail`) sofrem short-circuit antes do roteamento e retornam um PNG `no-store` 1×1 via `getQAProbePixel`. Esses não são gravados no Supabase ou no R2.

### 2.2 Bindings e cron

- **Binding R2** — `catalog/latest.json`, `catalog/{version}.json`, e o cursor round-robin `catalog/scheduled-sync-cursor.json`. **Ele nunca armazena bytes de blocklist de terceiros.** (Objetos de anexo de relatórios de bug legados são apenas *excluídos* — best-effort durante a exclusão de conta — nunca gravados.)
- **Binding D1** — linhas anônimas somente-append `article_id` / `locale` / `vote` / `path`; mantidas separadas do Supabase por design.
- **Cron (`scheduled`)** — o handler ramifica conforme o id do cron:
  - **A cada 6 horas** — sincroniza **uma** fonte por execução, em round-robin via o cursor R2 (`nextScheduledSyncSourceID`, `SCHEDULED_SYNC_CURSOR_KEY`), depois republica o catálogo. Espalhar a carga evita martelar todos os upstreams de uma só vez.
  - **A cada 2 minutos** — executa um caminho interno de triagem de relatórios de bug que promove novos relatórios anônimos para uma fila de issue-tracker interno, avançando seu próprio cursor watermark. Isso é ferramental de operações interno; os identificadores de issue-tracker/notificação são configuração, não parte da API pública.

## 3. Catálogo e imposição do source-url-only

Esta é a parte do backend mais específica à postura de conformidade da Lava, então ela ganha dentes do lado do servidor.

### 3.1 O modelo source-url-only

> **Source-url-only:** modelo de distribuição de conformidade GPL/IP: a Lava publica apenas a URL de upstream + hashes aceitos; o dispositivo busca/parseia as listas ele mesmo. A Lava **nunca** armazena, espelha, transforma ou serve bytes de blocklist de terceiros.

Cada linha `blocklist_sources` carrega `redistribution_mode`, cujo único valor permitido é `"source_url_only"`. O catálogo que o dispositivo lê (`/v1/catalog`, `schema_version` 2) divide as entradas em `sources[]` e `guardrails[]`; cada entrada carrega o `source_url` de upstream mais `accepted_source_hashes` (SHA-256 + tamanho em bytes + contagem de entradas + `reviewed_at` + status `accepted`) — nunca os bytes da lista. Ver `formatCatalogEntry`.

> **Descartado:** um design anterior espelhava arquivos de lista GPL com bytes preservados no R2 (o plano de conformidade GPL-raw-R2). Ele foi **substituído em 2026-05-25** pelo source-url-only. A Lava não armazena nem serve mais bytes de blocklist de terceiros. O nome de tabela `mirror_events` é um resquício legado daquele design abandonado — agora é apenas o log de auditoria de sincronização/publicação.

### 3.2 Como o Worker o impõe em gravações

O caminho de sincronização (`syncOneBlocklist`, admin e cron) busca cada `source_url` de upstream, normaliza/valida **localmente no Worker apenas para computar metadados** (`entry_count`, `source_hash`, `normalized_hash`, `byte_size`), grava uma linha `blocklist_versions`, e republica. As chaves de armazenamento de bytes são gravadas de forma rígida como null:

```ts
raw_r2_key: null,
normalized_r2_key: null,
```

Uma migração (`20260525000000_add_blocklist_distribution_mode.sql`) tornou essas colunas nullable e definiu os valores existentes como null, de modo que a postura de não-espelhamento também é imposta no nível do esquema. O catálogo publicado é gravado em **ambos** `catalog/{version}.json` e `catalog/latest.json` no R2 (`publishCatalog`).

### 3.3 Guardrails de normalização (apenas metadados)

A normalização do lado do Worker (`normalizeBlocklist`) filtra domínios protegidos, impõe limites e faz dedup+ordenação. Isso é puramente para computar metadados confiáveis; para **listas da comunidade** o dispositivo **não** faz hash-gate do download — ele busca via TLS a partir do `source_url` curado e parseia sob limites (os hashes aceitos do catálogo são consultivos), então essa normalização do lado do Worker não é uma fronteira de segurança por si só. (A camada de threat-guardrail da Lava permanece hash-pinned no dispositivo, e a procedência do `source_url` é imposta no momento da publicação — uma mudança de URL deve usar um novo `list_id`.) Constantes-chave:

- `PROTECTED_SUFFIXES` — remove qualquer regra que corresponda a domínios da Apple/iCloud/`mzstatic`/Lava Security/Supabase/Cloudflare/Google/GitHub, para que um upstream envenenado não possa bloquear a própria infraestrutura da Lava ou os provedores de sign-in.
- `MAX_BLOCKLIST_BYTES = 25 MiB`, `MAX_BLOCKLIST_LINE_LENGTH = 2048`, `MAX_NORMALIZED_DOMAINS = 500_000`.

### 3.4 O que é publicável

`isPublicBlocklistSource` só publica uma fonte quando `status` é `sync` ou `nosync`, `redistribution_mode === "source_url_only"`, **e** `isAllowedLaunchGPLSource` passa. O gate de launch-GPL (`isAllowedLaunchGPLSource`) permite fontes não-GPL livremente e permite as famílias de fontes GPL-3.0 liberadas por prefixo de `list_id`: `hagezi-`, `oisd-`, e `adguard-`.

### 3.5 Fontes pré-populadas e default-enabled

As fontes curadas são pré-populadas como metadados source-url-only via migrações, geradas a partir da especificação canônica do [Catálogo de Blocklists](../legal/blocklist-catalog.md) (HaGeZi, OISD, The Block List Project, Phishing.Database, StevenBlack, AdGuard, 1Hosts). A migração de expansão de categorias adiciona as categorias de defesa em profundidade (nsfw/social/gambling/piracy), realinha o padrão de instalação nova para **Block List Basic**, e reativa o AdGuard DNS Filter como uma opção sinalizada pela assessoria jurídica, desabilitada por padrão. Status: **Implementado**.

> **Os padrões do catálogo correspondem ao cliente.** O conjunto `default_enabled` do catálogo é **{Block List Basic}** — uma lista combinada ampla e permissiva que substitui o par Phishing + Scam anterior — correspondendo ao padrão recomendado do iOS (`AppConfiguration.lavaRecommendedDefaults`). Tanto a coluna `default_enabled` servida quanto o `DefaultCatalog` embarcado no iOS são gerados a partir da mesma especificação canônica, então eles concordam por construção (isso resolve a discrepância anterior de padrão entre cliente↔backend). Note que `default_enabled` é informacional: o gate real de tier é o **orçamento de filter-rules (Free 500K / Plus 2M)**, não a contagem de listas. O fundamento jurídico para publicar URLs (não bytes) está em [decisão de conformidade GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md).

## 4. Postgres do Supabase

Um projeto Postgres do Supabase. RLS está habilitado em **toda** tabela pública.

### 4.1 Esquema central

`20260516034033_backend_core.sql` cria a fundação (RLS habilitado em todas as 7 tabelas públicas):

- **`profiles`, `user_settings`, `entitlements`** — estado de conta por usuário. Um trigger `handle_new_user()` auto-cria linhas `profiles` + `user_settings` na inserção de `auth.users`.
- **`blocklist_sources`, `blocklist_versions`** — as tabelas de metadados do catálogo. Uma fonte é uma lista de upstream curada (`list_id`, `source_url`, licença, risco, `default_enabled`, `status`, `redistribution_mode`); uma versão são os metadados de um snapshot sincronizado (hashes, `entry_count`, `byte_size`), linkado de volta via `latest_version_id`.
- **`mirror_events`** — log de auditoria somente-service-role de eventos `sync` / `catalog_publish` (nome legado; ver §3.1).
- **`bug_reports`** — relatórios anônimos somente-service-role.

Migrações posteriores adicionam **`user_backups`** (§4.3) e **`qa_developers`** (`20260608000000_qa_developers_allowlist.sql`).

### 4.2 Modelo de RLS

| Tabela(s) | Política | Efeito |
|---|---|---|
| `profiles`, `user_settings`, `entitlements`, `user_backups` | `auth.uid() = user_id` por usuário | cada usuário vê apenas suas próprias linhas |
| `blocklist_sources` | leitura pública onde `status in ('sync','nosync')` (`backend_core.sql:262-266`) | qualquer um pode ler fontes curadas, elegíveis para sincronização |
| `blocklist_versions` | leitura pública onde `validation_status = 'published'` (`backend_core.sql:268-272`) | qualquer um pode ler metadados de versão publicada |
| `bug_reports`, `mirror_events` | `using(false)` explícito (`20260516034136_backend_core_advisor_fixes.sql`) | sem acesso anon/authenticated — o Worker usa a service role |
| `qa_developers` | RLS ativo + **revoke all from anon, authenticated** | somente-service-role; a allowlist de QA nunca é legível pelo cliente |

A divisão importa: relatórios de bug anônimos devem ser *inseríveis* pelo Worker sem serem *legíveis* pelos clientes, e a allowlist de QA só pode ser lida pela service role.

### 4.3 Auth e o envelope de backup criptografado

**Auth** é opcional. O sign-in é **somente Apple + Google** (email/senha foi **Descartado**). Ambos usam o grant nativo `id_token` trocado no Supabase Auth `auth/v1/token?grant_type=id_token` com um nonce com hash; o app armazena apenas a sessão resultante, travada no dispositivo no Keychain. O fluxo do lado do cliente vive no app iOS (`lavasec-ios: LavaSecApp/AccountAuthService.swift`, `lavasec-ios: Sources/LavaSecCore/SupabaseIDTokenAuth.swift`) — ver [Contas e Backup](./accounts-and-backup.md) para o modelo completo de conta/backup.

> **Backup zero-knowledge:** envelope AES-256-GCM do lado do cliente; apenas ciphertext + metadados não-secretos sobem para o `user_backups` do Supabase (RLS por usuário). O servidor não consegue descriptografar sem um segredo mantido pelo usuário.

O fato crucial do backend: **o cliente iOS lê/grava `user_backups` diretamente via Supabase PostgREST sob RLS por usuário** (upsert em `user_id`, com escopo pelo token de acesso). **Não há rotas `/v1/backup`** no Worker, de forma alguma. O Worker toca em `user_backups` exatamente uma vez: para excluí-lo durante a exclusão de conta (`deleteAccount`).

`user_backups` armazena apenas ciphertext opaco + metadados de envelope não-secretos (parâmetros/salts de KDF, nonces, rótulos de key-slot, dicas de esquema do cliente). Limites de tamanho (`20260605000000_tighten_backup_envelope_constraints.sql`): ciphertext ≤ 262144 bytes (256 KiB) / ≤ 349528 chars, metadados ≤ 32768 bytes (32 KiB). O BD nunca armazena configurações em texto plano, senhas, frases ou chaves.

### 4.4 Exclusão de conta

`POST /v1/account/delete` valida o token de acesso do usuário, depois exclui suas linhas `bug_reports` (e qualquer objeto de anexo R2 legado correspondente), `user_backups`, `entitlements`, `user_settings`, e `profiles`, e finalmente exclui o usuário do Supabase Auth via o endpoint service-role `/admin/users`. Ele retorna apenas um status de exclusão + os provedores vinculados. Status: **Implementado** (o frontmatter do plano lê `status: Done` e o arquivo está em `plans/implemented/`; uma anotação **no corpo** desatualizada ainda diz "Backlog", mas a pasta da raia + a presença do código o tornam lançado).

### 4.5 Espelhamento de entitlement da App Store

`POST /v1/account/entitlements/app-store-sync` faz upsert de uma linha `entitlements` (plano `lava_security_plus`) a partir de um JWS de transação StoreKit verificado pelo cliente, on conflict por `user_id`. O `verification_status` armazenado é literalmente `"client_verified_storekit"` — o servidor **não** re-verifica o JWS. IDs de produto permitidos: `lava_security_plus_{monthly,yearly}`.

> O espelhamento é **Implementado**; a **verificação de JWS do lado do servidor é Planejada** (ainda não construída). O JWS assinado é armazenado para verificação posterior. Note o modelo de tier em outro lugar: o entitlement do app é local (`isPaid`) **sem sincronização de backend ainda** como fonte da verdade — esta linha é um espelho, não o gate.

## 5. Recuperação assistida por passkey (zero-knowledge)

A recuperação de backup assistida por passkey é **zero-knowledge** e inteiramente do lado do cliente. O material da chave de recuperação é derivado no dispositivo a partir da saída do **WebAuthn PRF / hmac-secret** do passkey; o servidor armazena **nenhum** segredo de recuperação, registra **nenhum** passkey, e emite **nenhum** challenge WebAuthn. Não há caminho de escrow controlado pelo servidor.

As tabelas de escrow que um design anterior usava (`backup_passkey_recovery`, `backup_passkey_challenges`) foram removidas antes do lançamento, e o Worker não carrega rotas `/v1/backup/*` nem código de WebAuthn/passkey. (Uma entrada `@simplewebauthn/server` permanece no `package.json` do Worker como uma dependência sobrante não utilizada.)

O lado do cliente vive no app iOS: `lavasec-ios: LavaSecApp/BackupPasskeyCoordinator.swift` dirige a criação/asserção de passkey capaz de PRF, e `lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift` deriva o slot a partir da saída do hmac-secret. A saída do PRF é lida apenas durante a asserção e nunca sai do dispositivo. Um provedor de passkey sem PRF não pode sustentar um slot zero-knowledge, então a configuração falha cedo e o usuário recai para uma frase de recuperação. Status: **Implementado**.

## 6. Worker lavasec-email

Somente recebe-e-encaminha. Ele encaminha `support@` / `hello@` / `jimmy@` / `legal@lavasecurity.app` para uma caixa de entrada de operador verificada, rejeita destinatários desconhecidos e e-mails acima de 10 MiB, e **não armazena corpos de e-mail**. As respostas automáticas de suporte estão codificadas mas bloqueadas atrás do e-mail de saída pago do Cloudflare (adiado). As constantes de roteamento vivem em `email-service.ts:9` (`ROUTED_RECIPIENTS`); o handler de entrada é `handleInboundEmail`. Status: **Implementado** (caminho de resposta automática **Planejado**/adiado).

## 7. Configuração e deploy

- **A configuração é `wrangler.toml`, que está no gitignore**; `wrangler.toml.example` é o template versionado. Trate o `wrangler.toml` local como canônico para valores específicos de ambiente.
- **Vars** (não-secretos, em `[vars]`): a URL do Supabase, a origin pública da API (`https://api.lavasecurity.app`), o TTL de cache do catálogo (padrão 300s), um limite de tamanho de relatório de bug, um toggle de auditoria de exclusão de conta, e uma flag de aceleração do runtime do Workers. A triagem interna de relatórios de bug adiciona uma chave de fila de triagem interna e uma origin de dashboard usada ao compor links de triagem.
- **Secrets** (via `wrangler secret put`): uma credencial service-role do Supabase, uma chave de API admin, e — para o caminho de triagem de relatórios de bug — uma chave de API de issue-tracker e um webhook opcional de notificação de chat.
- **O deploy é manual**: `npm run deploy` → `wrangler deploy`. Não há CI para o Worker.
- **Roteamento do Cloudflare**: `lavasecurity.app` permanece no Pages; `api.lavasecurity.app` e `*.qa-probe.lavasecurity.app` resolvem para este Worker.
- **Compatibilidade**: `compatibility_date = "2026-05-16"`, `compatibility_flags = ["nodejs_compat"]`.

> `CBOR_NATIVE_ACCELERATION_DISABLED = "true"` está definido em vars mas não é referenciado pelo código do Worker; é uma flag de aceleração do runtime do Workers, e não uma configuração da aplicação.

## 8. Invariantes de privacidade (o que está e o que não está aqui)

Uma checklist rápida para qualquer um que estenda o backend — nenhuma destas pode ser quebrada silenciosamente:

1. **Sem telemetria de DNS/navegação.** Não há tabela para consultas DNS rotineiras ou telemetria por domínio. A filtragem permanece no dispositivo.
2. **Sem bytes de blocklist de terceiros** no R2 ou no Postgres — apenas `source_url` + hashes aceitos (§3).
3. **`user_backups` é opaco** — apenas ciphertext + metadados não-secretos; o cliente (não o Worker) o grava sob RLS (§4.3).
4. **Isolamento de service-role** para `bug_reports`, `mirror_events`, `qa_developers` (§4.2).
5. **Todos os caminhos de backup são zero-knowledge** — incluindo a recuperação assistida por passkey, cujo material de chave é derivado do lado do cliente a partir da saída do WebAuthn PRF/hmac-secret. O servidor não armazena segredo de recuperação e não roda WebAuthn (§5).

## Veja também

- [Visão Geral do Sistema](./system-overview.md) — o sistema inteiro em uma página, incluindo fronteiras de confiança.
- [Cliente iOS](./ios-client.md) — o lado do dispositivo que consome este backend.
- [Contas e Backup](./accounts-and-backup.md) — auth do lado do cliente, o envelope AES-256-GCM, key slots, e frases de recuperação.
- [Filtragem de DNS e Blocklists](./dns-filtering-and-blocklists.md) — o lado do dispositivo do catálogo: download direto de upstream, parse/normalização, e o orçamento de filter-rules.
- [decisão de conformidade GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — por que o catálogo publica URLs, não bytes.
- **Tiers e monetização** (interno) — o orçamento de filter-rules (Free 500K / Plus 2M) que é o gate real Free/Plus.
- **Registro de risco de IP** (interno) — o fundamento de IP/conformidade por trás do source-url-only.
