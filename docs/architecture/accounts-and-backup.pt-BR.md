---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Contas e backup com conhecimento zero

> **Público:** engenheiros.
> **Autoridade:** quando este documento e um plano divergem, **o código prevalece** — as divergências são apontadas no próprio texto. O status reflete a realidade confirmada no código, não a aspiração do plano. Legenda de status: **Implementado** (entregue e confirmado no código), **Em andamento** (parcialmente concluído), **Planejado** (projetado, não construído), **Descartado** (rejeitado ou revertido).

As contas são **opcionais**. A proteção essencial é gratuita para sempre e não exige conta; o login existe apenas para fazer backup das suas *configurações*, criptografadas, para que você possa restaurá-las em um novo aparelho. Este documento cobre o fluxo de autenticação, onde a sessão fica armazenada, o envelope de backup com conhecimento zero, os caminhos de recuperação e exatamente o que o servidor pode e não pode ver.

A promessa de privacidade canônica a que este documento serve:

> Toda a filtragem de DNS acontece no aparelho; a Lava nunca roteia sua navegação pelos servidores dela e nunca recebe o fluxo de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado e opaco por usuário e diagnósticos anonimizados que você escolhe enviar.

Divisão de componentes: a criptografia pura + a construção de requisições ficam em `LavaSecCore`; a orquestração + a interface ficam em `LavaSecApp`. Documentos irmãos: [Visão geral do sistema](./system-overview.md), [Cliente iOS](./ios-client.md), [Backend e dados](./backend-and-data.md), [Filtragem de DNS e listas de bloqueio](./dns-filtering-and-blocklists.md).

---

## 1. Fluxo de autenticação

**Provedores: apenas Apple e Google.** **(Implementado)** `AccountAuthProvider` enumera exatamente `.apple` e `.google` (`AccountAuthService.swift`). E-mail/senha — e qualquer recuperação assistida pelo suporte que ignore a autenticação — é explicitamente **Descartado**; manter senhas próprias adicionaria obrigações de redefinição/MFA/bloqueio/vazamento que não compensam a complexidade enquanto Apple/Google forem suficientes, e a recuperação por desvio quebraria a garantia de conhecimento zero.

Ambos os provedores usam a **concessão nativa de `id_token`**, não o SDK Swift do Supabase e não o OAuth web:

1. **Login nativo.** Apple via AuthenticationServices; Google via o SDK GoogleSignIn. Cada um produz um `id_token` do provedor (o Google também um access token). O app gera um nonce bruto via CSPRNG, faz o hash dele com SHA256 e passa o hash ao provedor, de modo que o `id_token` emitido fique vinculado a ele. **(Implementado)**
2. **Troca no Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) monta uma `URLRequest` crua para o Supabase Auth `auth/v1/token?grant_type=id_token`, enviando `provider` + `id_token` + `access_token` opcional + o nonce **bruto** (para que o Supabase possa verificar o vínculo e rejeitar repetições), com o cabeçalho `apikey`. Sem SDK; `LavaSecCore` permanece livre de dependências de rede/autenticação. **(Implementado)**
3. **Recebimento de uma sessão.** O Supabase verifica o token e retorna uma sessão: um access token, um refresh token, uma expiração e um registro de usuário (provider/providers). A renovação usa o mesmo auxiliar com `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orquestra tudo isso — executa os fluxos nativos, faz a troca, persiste e renova as sessões, expõe `AccountAuthState` e conduz a exclusão de conta pelo Worker.

```
Apple / Google (id_token nativo + nonce bruto)
        │
        ▼
SupabaseIDTokenAuth  ──POST──▶  Supabase Auth  auth/v1/token?grant_type=id_token
        │                              │
        ▼                              ▼
AccountAuthService  ◀────── sessão (access + refresh tokens, expiração, usuário)
        │
        ▼
AccountSessionKeychainStore  (Keychain, local do aparelho)
```

---

## 2. Armazenamento de sessão e Keychain

A **única** coisa persistida a partir do login é a sessão do Supabase — os access e refresh tokens em JSON. **Não** há nenhuma cópia no servidor de quem você é além do usuário do Supabase Auth e das linhas que você possui.

- **Onde:** `AccountSessionKeychainStore` (`LavaSecApp`), serviço do Keychain `com.lavasec.account-session`, armazenado **por provedor** (`supabase-session-apple` / `supabase-session-google`, mais uma migração de conta legada). **(Implementado)**
- **Acessibilidade:** todos os armazenamentos compartilham `GenericKeychainStore` (`LavaSecCore`), fixado em `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Isso significa **local do aparelho, não sincronizado pelo iCloud e não incluído em backups do aparelho**. **(Implementado)**

A mesma mecânica de `GenericKeychainStore` sustenta três armazenamentos: a sessão da conta, o material de desbloqueio do backup (`BackupKeychainStore`, serviço `com.lavasec.zero-knowledge-backup`) e a senha do app. Nenhum deles sincroniza pelo iCloud Keychain.

> **Item em revisão aberta (não é um comportamento garantido):** a classe de acessibilidade atual não tem barreira biométrica/de presença do usuário (sem `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). A decisão de restringir o material de desbloqueio a um controle de acesso com presença está registrada como item de revisão para liberação; o valor que vai no app hoje é after-first-unlock-this-device-only. **(Planejado)**

---

## 3. Backup com conhecimento zero

### 3.1 O que é, com precisão

Quando você ativa o backup criptografado, o **cliente iOS** criptografa uma cópia reduzida das suas *configurações* e envia somente o texto cifrado mais metadados não secretos ao Supabase. O telefone é o único lugar onde o texto puro e os segredos de descriptografia chegam a existir.

> **Backup com conhecimento zero:** envelope AES-256-GCM no lado do cliente; a chave aleatória do conteúdo é envolvida em compartimentos de chave por slot — PBKDF2-HMAC-SHA256 (210 mil iterações) para os slots de senha/frase/aparelho/assistido, HKDF-SHA256 para o slot de passkey com PRF. Apenas texto cifrado + metadados não secretos são enviados ao `user_backups` do Supabase (RLS por usuário). O servidor não consegue descriptografar sem um segredo em posse do usuário. O slot de passkey **também** é de conhecimento zero: sua chave de desempacotamento é derivada no aparelho a partir da saída do PRF WebAuthn (`hmac-secret`) do autenticador, e o servidor não guarda nenhum segredo de passkey (veja a §4.3).

### 3.2 O que entra no backup (o conteúdo reduzido)

`BackupConfigurationPayload` (`LavaSecCore`) é o texto puro que é selado. Ele é deliberadamente pequeno e converte de ida e volta para `AppConfiguration`. **(Implementado)**

**Incluído:** os **IDs** das listas de bloqueio habilitadas (referências de catálogo, não os bytes das listas), domínios permitidos/bloqueados, preset de resolvedor / resolvedor personalizado, preferências de registro local, o ledger do LavaGuard, uma dica de proteção e os metadados de origem das listas de bloqueio personalizadas.

**Excluído:** `isPaid` (o direito de uso é local), flags de QA, diagnósticos, snapshots de filtros e o conteúdo completo das listas de bloqueio (referenciado apenas pelo ID de catálogo). Seu histórico de navegação e suas consultas de DNS nunca fazem parte desse conteúdo, porque o aparelho nunca os registra como um fluxo rotineiro de telemetria.

### 3.3 O envelope (criptografia no lado do cliente)

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa a criptografia. **(Implementado)**

1. **Criptografia do conteúdo.** O conteúdo reduzido é selado uma vez com **AES-256-GCM** sob uma **chave de conteúdo aleatória de 32 bytes** (gerada com `SecRandomCopyBytes`).
2. **Empacotamento de chave (compartimentos de chave).** Essa única chave de conteúdo é empacotada independentemente em um ou mais **compartimentos de chave**, um por segredo, e então o AES-GCM empacota uma cópia da chave de conteúdo. O segredo de qualquer compartimento sozinho desbloqueia o backup inteiro. A derivação da chave de empacotamento varia por tipo de compartimento: os slots `password` / `recoveryPhrase` / `keychain` (aparelho) / `assistedRecovery` usam **PBKDF2-HMAC-SHA256, 210.000 iterações** (produção; `defaultPasswordIterations = 210_000`) com um salt aleatório novo de 16 bytes por slot; o slot `passkey` usa **HKDF-SHA256** sobre a saída do PRF do autenticador (info `"LavaSec passkey backup PRF v1"`), com o salt não secreto do PRF persistido no slot para que a restauração possa reproduzir a saída.
3. **Tipos de compartimento.** O envelope suporta cinco tipos de compartimento: `password`, `recoveryPhrase`, `keychain` (segredo do aparelho), `assistedRecovery` e `passkey`.

A configuração que vai no app é **sem senha** (`makePasswordless`, conduzida por `AppViewModel.turnOnEncryptedBackup`). Ela cria um **slot `keychain` (aparelho) + um slot `assistedRecovery` + um slot `passkey` opcional**. As fábricas `password` / `recoveryPhrase` e os métodos de descriptografia ainda existem para envelopes legados/de compatibilidade (exercitados apenas pelos testes), mas a interface ativa nunca cria um envelope só com senha — trate o backup por senha como não disponível. **(Implementado; slot de senha Descartado do fluxo ativo.)**

**Integridade / anti-downgrade:** `envelopeVersion` é fixado rigidamente em `1`, e o KDF de cada slot é fixado por tipo — `PBKDF2-HMAC-SHA256` para os slots de senha/frase/aparelho/assistido, `HKDF-SHA256` para o slot de passkey com PRF. Versões não suportadas ou KDFs incompatíveis são rejeitados, de modo que metadados forjados ou rebaixados não conseguem enfraquecer o desempacotamento. **(Implementado)**

### 3.4 Envio e armazenamento

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) envia o envelope **diretamente** para a tabela PostgREST `user_backups` do Supabase, fazendo upsert em `user_id`, com escopo do access token do usuário. **Não há rota no Worker para o envio do envelope** — o cliente fala direto com o Supabase sob RLS; o Worker só toca em `user_backups` para apagá-lo durante a exclusão da conta. **(Implementado)**

O que vai parar em `user_backups`:

- o **texto cifrado**, e
- **apenas metadados não secretos:** o nome da cifra, os registros dos compartimentos de chave (salts, contagens de iteração, chaves empacotadas, rótulos dos slots), o `server_recovery_share`, o `createdAt` e o tamanho em bytes.

A linha é protegida por **segurança em nível de linha (RLS)**: cada linha só pode ser lida/escrita pelo seu dono (`auth.uid() = user_id`); o papel anônimo não tem acesso. O tamanho é limitado a cerca de 256 KiB de texto cifrado / 32 KiB de metadados no nível do banco (`20260518000000_zero_knowledge_backups.sql`, reforçado em `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementado)**

### 3.5 A garantia — o que o servidor pode e não pode ver

**O servidor armazena:** texto cifrado, salts/iterações de KDF, compartimentos de chave empacotados, o `server_recovery_share` e alguns campos não secretos (cifra, tamanho, data/hora).

**O servidor nunca recebe nem armazena:** as configurações em texto puro/domínios/preferências de DNS, a frase de recuperação, qualquer senha de backup ou a chave de conteúdo desempacotada.

**Portanto:** o Supabase **não consegue descriptografar um backup** sem um segredo em posse do usuário. Todos os três caminhos de restauração — o slot da chave do aparelho, a frase de recuperação (combinada com o server share, §4.2) e o slot de passkey (a saída do PRF do autenticador, §4.3) — descriptografam **no aparelho**, e o servidor não guarda nenhum segredo de descriptografia para nenhum deles. Isso está afirmado nos comentários da migração e no plano de privacidade, e é testado (os testes do envelope confirmam que nenhum domínio/URL em texto puro vaza para o formato enviado).

**Ressalva precisa do modelo de ameaças — não exagere na afirmação.** Para o slot de **recuperação assistida**, o servidor guarda *tanto* o `server_recovery_share` *quanto* o slot `assistedRecovery` empacotado em `user_backups`. A única coisa que falta a ele é a frase de recuperação do usuário, que a Lava nunca recebe. Então, se o servidor fosse totalmente comprometido, a entropia da frase de recuperação (~105 bits, veja a §4.1) somada ao custo do PBKDF2 de 210 mil iterações seria a **única** barreira contra um ataque de força bruta offline desse slot. Isso é intencional (a recuperação assistida é de dois fatores por design — nenhuma metade sozinha descriptografa), mas significa que a entropia da frase de recuperação é estrutural, não decorativa. O segredo do slot `keychain` (aparelho) nunca sai do aparelho, então não fica exposto a um comprometimento do servidor de forma alguma.

---

## 4. Recuperação

Um backup só é útil se você puder restaurá-lo. `restoreEncryptedBackup` (em `AppViewModel`) descriptografa tentando os slots disponíveis: chave do aparelho, frase de recuperação ou passkey. Em todos os modos, o envelope é carregado localmente (ou buscado do Supabase) e então **descriptografado no aparelho** — o servidor nunca descriptografa.

### 4.1 Frase de recuperação

`BackupRecoveryPhrase` (`LavaSecCore`) gera uma **frase CVCV de 8 palavras** (consoante-vogal-consoante-vogal) a partir de `SecRandom` com amostragem por rejeição (~13,2 bits/token → **~105 bits no total**), normalizada em minúsculas. **(Implementado)** A restauração tolera a formatação do usuário (espaçamento/maiúsculas) por meio de análise/normalização antes de o slot ser tentado.

Esse é o fator de recuperação **fora do aparelho** do usuário — salvo pelo próprio usuário, nunca enviado. Conforme o reforço de privacidade (§5), copiar a frase é **opcional** e, quando usado, passa por uma área de transferência local / com expiração (10 minutos) em vez de forçar a exposição na área de transferência global.

### 4.2 Recuperação assistida (a combinação de dois fatores)

A frase de recuperação sozinha **não** desbloqueia o slot `assistedRecovery`. O segredo do slot é derivado de **ambas** as metades:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

Os três segmentos são unidos por um **separador de byte NUL (`0x00`)** na entrada UTF-8 real — ou seja, a string com hash é `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — então o `‖` acima denota concatenação delimitada por NUL, não concatenação simples. `serverRecoveryShare` é um valor aleatório armazenado nos metadados do envelope no lado do servidor; `normalizedPhrase` é a frase de recuperação do usuário. **Nenhuma metade sozinha descriptografa** — a restauração exige o server share (buscado com o backup) *e* a frase em posse do usuário. **(Implementado)**

### 4.3 Recuperação por passkey — conhecimento zero, derivada do PRF

O slot `passkey` opcional adiciona um fator apoiado em hardware, e ele é de **conhecimento zero**: sua chave de desempacotamento é derivada **no aparelho** a partir da saída do PRF WebAuthn (`hmac-secret`) do autenticador. O servidor não registra nenhuma passkey, não emite nenhum desafio WebAuthn e não armazena nenhum segredo de recuperação — não há etapa de liberação pelo servidor.

- **Registro/asserção:** `BackupPasskeyCoordinator` (`LavaSecApp`) executa WebAuthn via `ASAuthorizationPlatformPublicKeyCredentialProvider`, parte confiável **`lavasecurity.app`**, solicitando a extensão PRF sobre um salt por credencial e exigindo verificação do usuário.
- **Derivação de chave (conhecimento zero):** o autenticador retorna uma saída de PRF que **nunca sai do aparelho**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva a chave de empacotamento do slot dessa saída de PRF via HKDF-SHA256 (info `"LavaSec passkey backup PRF v1"`) e empacota a chave de conteúdo com AES-GCM; apenas o salt não secreto do PRF e o ID da credencial são persistidos no slot. Na restauração, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` reafirma a credencial para reproduzir a mesma saída de PRF, e `decryptWithPasskeyPRFOutput` desempacota o slot localmente. O servidor **não** guarda nenhum segredo de passkey, então nenhum caminho com papel de serviço consegue recuperar um backup protegido por passkey.

O design de custódia anterior (uma tabela `backup_passkey_recovery` com papel de serviço guardando um `recovery_secret` no lado do servidor, mais uma tabela `backup_passkey_challenges` e endpoints `/v1/backup/passkeys/*` no Worker) foi **Descartado**: as tabelas foram removidas em uma migração do backend, o Worker não carrega nenhuma rota de passkey, e `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` afirma positivamente que `BackupPasskeyRecoveryService` e qualquer caminho de custódia no servidor estão ausentes. **(Implementado)**

> **Ressalva de prontidão para produção:** tratar as passkeys salvas como um fator recuperável totalmente pronto para produção em aparelhos físicos ainda depende da associação webcredentials para `lavasecurity.app`. A metade do iOS está declarada — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` carrega `webcredentials:lavasecurity.app` — e a metade do servidor (o arquivo `apple-app-site-association` e os cabeçalhos) agora está hospedada no site de marketing. Até que essa associação resolva em um dado aparelho, o caminho da associação webcredentials pode falhar e expõe `BackupPasskeyError.webCredentialsAssociationUnavailable`. O fator passkey em si está implementado; sua prontidão de ponta a ponta em hardware real é **Planejada**.

---

## 5. Minimização de dados e postura de privacidade

- **Conta opcional.** A proteção funciona sem conta; o login só habilita o backup das configurações.
- **Texto puro só localmente.** O telefone é o único lugar onde as configurações em texto puro e os segredos de descriptografia existem; o Supabase guarda um envelope opaco por usuário.
- **Conteúdo reduzido.** Apenas as configurações da §3.2 entram no backup; `isPaid`, flags de QA, diagnósticos, snapshots e os bytes completos das listas de bloqueio são excluídos. As listas de bloqueio são referenciadas pelo ID de catálogo, nunca embutidas.
- **Sem telemetria de navegação/DNS.** Não há tabela no servidor para consultas rotineiras de DNS ou telemetria por domínio; a filtragem permanece no aparelho.
- **O material de desbloqueio é local do aparelho.** O material de desbloqueio do backup é armazenado com acessibilidade `…ThisDeviceOnly` e **não** é sincronizado pelo iCloud. Isso **reverteu** o design de Keychain sincronizável do plano original, então a Lava não sincroniza silenciosamente o material de desbloqueio pelo iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementado; reverte o plano anterior.)**

### Exclusão de conta

A exclusão está **Implementada** e roda por um endpoint autenticado do Worker, não por exclusões diretas pelo cliente. `AccountAuthService.deleteAccount` envia o access token do usuário para `POST /v1/account/delete`; o Worker `lavasec-api` (papel de serviço) apaga as linhas de `bug_reports` do usuário (e seus anexos no R2), `user_backups`, `entitlements`, `user_settings` e `profiles`, e então apaga o usuário do Supabase Auth pela API de admin, retornando apenas um status de exclusão + os provedores vinculados. O app então faz logout localmente e limpa o material de desbloqueio do backup (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Observação: o frontmatter YAML do plano de exclusão já indica `status: Done` e ele fica em `plans/implemented/`. Uma anotação **no corpo** desatualizada indica `Status: Backlog.`, mas, pela regra da pasta de pista (a pasta é autoritativa) e pela presença no código (app + Worker existem), o recurso está **Implementado**; a linha no corpo é um erro de documentação, não do frontmatter.

---

## 6. Resumo de status

| Área | Detalhe | Status |
|---|---|---|
| Login com `id_token` Apple / Google via Supabase | Fluxos nativos, nonce com hash, troca via URLRequest crua | Implementado |
| Login com e-mail/senha | Manter senhas próprias rejeitado | Descartado |
| Sessão no Keychain (local do aparelho, por provedor) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementado |
| Envelope AES-256-GCM + compartimentos de chave PBKDF2-HMAC-SHA256 (210k) | No lado do cliente; só texto cifrado + metadados não secretos em `user_backups` (RLS) | Implementado |
| Configuração sem senha (slots de aparelho + recuperação assistida + passkey opcional) | `makePasswordless` | Implementado |
| Compartimento de chave por senha no fluxo ativo | Sobrevive em `LavaSecCore` só para testes | Descartado |
| Frase de recuperação (CVCV de 8 palavras, ~105 bits) | Fator fora do aparelho | Implementado |
| Recuperação assistida (server share + frase via SHA256, delimitada por NUL) | Dois fatores; nenhuma metade sozinha | Implementado |
| Recuperação por passkey (conhecimento zero, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | Slot derivado da saída do PRF por HKDF, sem segredo no servidor | Implementado |
| Passkey como fator pronto para produção em hardware | Precisa da associação webcredentials (AASA hospedado no site de marketing) | Planejado |
| Exclusão de conta (Worker autenticado, papel de serviço) | Remove backups/configurações/direitos/perfil/anexos + usuário do Auth | Implementado |
| Barreira biométrica/de presença do usuário no material de desbloqueio | Item de revisão para liberação | Planejado |
| Extração de `EncryptedBackupCoordinator` do `AppViewModel` | Apenas modularização; nenhuma mudança no modelo de segurança | Em andamento |

---

## Relacionados

- [Visão geral do sistema](./system-overview.md) — o sistema inteiro em uma só tela, incluindo as fronteiras de confiança.
- [Cliente iOS](./ios-client.md) — `AppViewModel` e os targets do app que conduzem o backup.
- [Backend e dados](./backend-and-data.md) — o Worker `lavasec-api`, a RLS do Supabase e o armazenamento `user_backups`.
- [Filtragem de DNS e listas de bloqueio](./dns-filtering-and-blocklists.md) — os presets de resolvedor e os transportes cujas configurações são carregadas no conteúdo do backup.
