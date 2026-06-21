---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Contas e backup de conhecimento zero

> **Público:** engenheiros.
> **Autoridade:** quando este documento e um plano divergirem, **o código prevalece** — as divergências são apontadas ao longo do texto. O status reflete a realidade confirmada no código, não a aspiração do plano. Legenda de status: **Implementado** (lançado e confirmado no código), **Em andamento** (parcialmente concluído), **Planejado** (projetado, mas não construído), **Descartado** (rejeitado ou revertido).

As contas são **opcionais**. A proteção básica é gratuita para sempre e não exige conta; o login existe apenas para fazer backup das suas *configurações*, criptografadas, para que você possa restaurá-las em um novo aparelho. Este documento cobre o fluxo de autenticação, onde a sessão fica armazenada, o envelope de backup de conhecimento zero, os caminhos de recuperação e exatamente o que o servidor pode e não pode ver.

A promessa de privacidade canônica que este documento atende:

> Toda a filtragem de DNS acontece no aparelho; a Lava nunca encaminha sua navegação pelos seus servidores e nunca recebe o fluxo de domínios que você visita — o backend guarda apenas metadados do catálogo, um backup criptografado opaco por usuário e diagnósticos anonimizados que você escolhe enviar.

Divisão de componentes: a criptografia pura + a montagem das requisições ficam no `LavaSecCore`; a orquestração + a interface ficam no `LavaSecApp`. Documentos relacionados: [Visão geral do sistema](./system-overview.md), [Cliente iOS](./ios-client.md), [Backend e dados](./backend-and-data.md), [Filtragem de DNS e listas de bloqueio](./dns-filtering-and-blocklists.md).

---

## 1. Fluxo de autenticação {#1-authentication-flow}

**Provedores: apenas Apple e Google.** **(Implementado)** O `AccountAuthProvider` enumera exatamente `.apple` e `.google` (`AccountAuthService.swift`). E-mail/senha — e qualquer recuperação assistida pelo suporte que ignore a autenticação — foi explicitamente **Descartado**; possuir senhas adicionaria obrigações de redefinição/MFA/bloqueio/vazamento que não valem a complexidade enquanto Apple/Google bastam, e a recuperação por desvio quebraria a garantia de conhecimento zero.

Ambos os provedores usam a **concessão nativa de `id_token`**, não o SDK Swift do Supabase nem o OAuth web:

1. **Login nativo.** Apple via AuthenticationServices; Google via o SDK GoogleSignIn. Cada um produz um `id_token` do provedor (o Google também produz um access token). O app gera um nonce bruto via CSPRNG, faz o hash com SHA256 e passa o hash ao provedor, de modo que o `id_token` emitido fique vinculado a ele. **(Implementado)**
2. **Troca no Supabase.** O `SupabaseIDTokenAuth` (`LavaSecCore`) monta uma `URLRequest` bruta para o Supabase Auth `auth/v1/token?grant_type=id_token`, enviando `provider` + `id_token` + `access_token` opcional + o nonce **bruto** (para que o Supabase possa verificar o vínculo e rejeitar replays), com o cabeçalho `apikey`. Sem SDK; o `LavaSecCore` permanece livre de dependências de rede/autenticação. **(Implementado)**
3. **Recebimento de uma sessão.** O Supabase verifica o token e retorna uma sessão: um access token, um refresh token, uma expiração e um registro de usuário (provider/providers). A renovação usa o mesmo helper com `grant_type=refresh_token`.

O `AccountAuthService` (`@MainActor`, `LavaSecApp`) orquestra tudo isso — ele executa os fluxos nativos, faz a troca, persiste e renova as sessões, expõe o `AccountAuthState` e conduz a exclusão de conta através do Worker.

```
Apple / Google (native id_token + raw nonce)
        │
        ▼
SupabaseIDTokenAuth  ──POST──▶  Supabase Auth  auth/v1/token?grant_type=id_token
        │                              │
        ▼                              ▼
AccountAuthService  ◀────── session (access + refresh tokens, expiry, user)
        │
        ▼
AccountSessionKeychainStore  (Keychain, device-local)
```

---

## 2. Armazenamento de sessão e Keychain {#2-session--keychain-storage}

A **única** coisa persistida a partir do login é a sessão do Supabase — access e refresh tokens em JSON. **Não** há nenhum espelho no servidor de quem você é além do usuário do Supabase Auth e das linhas que você possui.

- **Onde:** `AccountSessionKeychainStore` (`LavaSecApp`), serviço de Keychain `com.lavasec.account-session`, armazenado **por provedor** (`supabase-session-apple` / `supabase-session-google`, mais uma migração de contas legadas). **(Implementado)**
- **Acessibilidade:** todos os armazenamentos compartilham o `GenericKeychainStore` (`LavaSecCore`), fixado em `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Isso significa **local ao aparelho, não sincronizado pelo iCloud e não incluído em backups do aparelho**. **(Implementado)**

A mesma mecânica do `GenericKeychainStore` sustenta três armazenamentos: a sessão da conta, o material de desbloqueio do backup (`BackupKeychainStore`, serviço `com.lavasec.zero-knowledge-backup`) e a senha do app. Nenhum deles sincroniza através do iCloud Keychain.

> **Item aberto em revisão (não é um comportamento afirmado):** a classe de acessibilidade atual não tem nenhuma trava biométrica/de presença do usuário (sem `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Se devemos endurecer o material de desbloqueio para um controle de acesso com trava de presença é algo rastreado como item de revisão de portão de lançamento; o valor atualmente em produção é after-first-unlock-this-device-only. **(Planejado)**

---

## 3. Backup de conhecimento zero {#3-zero-knowledge-backup}

### 3.1 O que é, com precisão {#31-what-it-is-precisely}

Quando você ativa o backup criptografado, o **cliente iOS** criptografa uma cópia minimizada das suas *configurações* e envia apenas o texto cifrado mais metadados não secretos ao Supabase. O telefone é o único lugar onde o texto puro e os segredos de descriptografia existem.

> **Backup de conhecimento zero:** Envelope AES-256-GCM no lado do cliente; a chave aleatória de payload é envolvida em slots de chave por slot — PBKDF2-HMAC-SHA256 (210k iterações) para os slots de senha/frase/aparelho/assistido, HKDF-SHA256 para o slot de passkey PRF. Apenas texto cifrado + metadados não secretos são enviados ao Supabase `user_backups` (RLS por usuário). O servidor não consegue descriptografar sem um segredo em posse do usuário. O slot de passkey é **também** de conhecimento zero: sua chave de desempacotamento é derivada no aparelho a partir da saída do PRF WebAuthn do autenticador (`hmac-secret`), e o servidor não guarda nenhum segredo de passkey (veja §4.3).

### 3.2 O que é incluído no backup (o payload minimizado) {#32-what-gets-backed-up-the-minimized-payload}

O `BackupConfigurationPayload` (`LavaSecCore`) é o texto puro que é selado. Ele é deliberadamente pequeno e converte de ida e volta para `AppConfiguration`. **(Implementado)**

**Incluído:** os **IDs** das listas de bloqueio ativas (referências do catálogo, não os bytes das listas), domínios permitidos/bloqueados, preset de resolver / resolver personalizado, preferências de log local, o registro do LavaGuard, uma dica de proteção e os metadados de fonte de listas de bloqueio personalizadas.

**Excluído:** `isPaid` (a habilitação é local), flags de QA, diagnósticos, snapshots de filtro e o conteúdo completo das listas de bloqueio (referenciado apenas pelo ID do catálogo). Seu histórico de navegação e suas consultas de DNS nunca fazem parte deste payload, porque o aparelho nunca os registra como um fluxo rotineiro de telemetria.

### 3.3 O envelope (criptografia no lado do cliente) {#33-the-envelope-client-side-crypto}

O `ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa a criptografia. **(Implementado)**

1. **Criptografia do payload.** O payload minimizado é selado uma vez com **AES-256-GCM** sob uma **chave de payload aleatória de 32 bytes** (gerada com `SecRandomCopyBytes`).
2. **Empacotamento de chave (slots de chave).** Essa única chave de payload é empacotada de forma independente em um ou mais **slots de chave**, um por segredo, e então o AES-GCM empacota uma cópia da chave de payload. O segredo de qualquer slot, sozinho, destrava o backup inteiro. A derivação da chave de empacotamento é por tipo de slot: os slots `password` / `recoveryPhrase` / `keychain` (aparelho) / `assistedRecovery` usam **PBKDF2-HMAC-SHA256, 210.000 iterações** (produção; `defaultPasswordIterations = 210_000`) com um salt aleatório novo de 16 bytes por slot; o slot `passkey` usa **HKDF-SHA256** sobre a saída do PRF do autenticador (info `"LavaSec passkey backup PRF v1"`), com o salt PRF não secreto persistido no slot para que a restauração possa reproduzir a saída.
3. **Tipos de slot.** O envelope suporta cinco tipos de slot: `password`, `recoveryPhrase`, `keychain` (segredo do aparelho), `assistedRecovery` e `passkey`.

A configuração lançada é **sem senha** (`makePasswordless`, conduzida por `AppViewModel.turnOnEncryptedBackup`). Ela cria um **slot `keychain` (aparelho) + um slot `assistedRecovery` + um slot `passkey` opcional**. As fábricas `password` / `recoveryPhrase` e os métodos de descriptografia ainda existem para envelopes legados/de retrocompatibilidade (exercitados apenas por testes), mas a interface ativa nunca cria um envelope apenas com senha — trate o backup com senha como não lançado. **(Implementado; slot de senha Descartado do fluxo ativo.)**

**Integridade / anti-downgrade:** o `envelopeVersion` é fixado rigidamente em `1`, e o KDF de cada slot é fixado por tipo — `PBKDF2-HMAC-SHA256` para os slots de senha/frase/aparelho/assistido, `HKDF-SHA256` para o slot de passkey PRF. Versões não suportadas ou KDFs incompatíveis são rejeitados, de modo que metadados forjados ou rebaixados não conseguem enfraquecer o desempacotamento. **(Implementado)**

### 3.4 Envio e armazenamento {#34-upload--storage}

O `BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) envia o envelope **diretamente** para a tabela PostgREST do Supabase `user_backups`, fazendo upsert por `user_id`, com escopo do access token do usuário. **Não há rota de Worker para o envio do envelope** — o cliente fala direto com o Supabase sob RLS; o Worker só toca em `user_backups` para excluí-lo durante a exclusão de conta. **(Implementado)**

O que vai parar em `user_backups`:

- o **texto cifrado**, e
- **apenas metadados não secretos:** nome do cifrador, os registros de slots de chave (salts, contagens de iteração, chaves empacotadas, rótulos de slot), o `server_recovery_share`, `createdAt` e o tamanho em bytes.

A linha é protegida por **segurança em nível de linha (RLS)**: cada linha só pode ser lida/escrita pelo seu dono (`auth.uid() = user_id`); o papel anônimo não tem acesso. O tamanho é limitado a ~256 KiB de texto cifrado / 32 KiB de metadados no nível do banco de dados (`20260518000000_zero_knowledge_backups.sql`, restringido em `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementado)**

### 3.5 A garantia — o que o servidor pode e não pode ver {#35-the-guarantee--what-the-server-can-and-cannot-see}

**O servidor armazena:** texto cifrado, salts/iterações do KDF, slots de chave empacotados, o `server_recovery_share` e alguns campos não secretos (cifrador, tamanho, carimbo de data/hora).

**O servidor nunca recebe nem armazena:** as configurações/domínios/preferências de DNS em texto puro, a frase de recuperação, qualquer senha de backup ou a chave de payload desempacotada.

**Portanto:** o Supabase **não consegue descriptografar um backup** sem um segredo em posse do usuário. Todos os três caminhos de restauração — o slot da chave do aparelho, a frase de recuperação (combinada com a parte do servidor, §4.2) e o slot de passkey (a saída do PRF do autenticador, §4.3) — descriptografam **no aparelho**, e o servidor não guarda nenhum segredo de descriptografia para nenhum deles. Isso é afirmado nos comentários da migração e no plano de privacidade, e testado (os testes de envelope confirmam que nenhum domínio/URL em texto puro vaza para o formato enviado).

**Ressalva precisa do modelo de ameaças — não exagere a afirmação.** Para o slot de **recuperação assistida**, o servidor guarda *tanto* o `server_recovery_share` *quanto* o slot `assistedRecovery` empacotado em `user_backups`. A única coisa que lhe falta é a frase de recuperação do usuário, que a Lava nunca recebe. Então, se o servidor fosse totalmente comprometido, a entropia da frase de recuperação (~105 bits, veja §4.1) mais o custo do PBKDF2 de 210k iterações é a **única** barreira contra um ataque de força bruta offline desse slot. Isso é intencional (a recuperação assistida é de dois fatores por design — nenhuma metade sozinha descriptografa), mas significa que a entropia da frase de recuperação é estrutural, não decorativa. O segredo do slot `keychain` (aparelho) nunca sai do aparelho, então ele não fica exposto a um comprometimento do servidor de forma alguma.

---

## 4. Recuperação {#4-recovery}

Um backup só é útil se você puder restaurá-lo. O `restoreEncryptedBackup` (em `AppViewModel`) descriptografa tentando os slots disponíveis: chave do aparelho, frase de recuperação ou passkey. Em todos os modos, o envelope é carregado localmente (ou buscado no Supabase) e então **descriptografado no aparelho** — o servidor nunca descriptografa.

### 4.1 Frase de recuperação {#41-recovery-phrase}

O `BackupRecoveryPhrase` (`LavaSecCore`) gera uma **frase CVCV de 8 palavras** (consoante-vogal-consoante-vogal) a partir do `SecRandom` com amostragem por rejeição (~13,2 bits/token → **~105 bits no total**), normalizada em minúsculas. **(Implementado)** A restauração tolera a formatação do usuário (espaçamento/caixa) por meio de parsing/normalização antes de o slot ser tentado.

Esse é o fator de recuperação **fora do aparelho** do usuário — salvo pelo próprio usuário, nunca enviado. Conforme o endurecimento de privacidade (§5), copiar a frase é **opcional** e, quando usado, passa por uma área de transferência local / com expiração (10 minutos) em vez de forçar a exposição na área de transferência global.

### 4.2 Recuperação assistida (a combinação de dois fatores) {#42-assisted-recovery-the-two-factor-combination}

A frase de recuperação sozinha **não** destrava o slot `assistedRecovery`. O segredo do slot é derivado de **ambas** as metades:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

Os três segmentos são unidos por um **separador de byte NUL (`0x00`)** na entrada UTF-8 real — ou seja, a string que sofre o hash é `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — de modo que o `‖` acima denota concatenação delimitada por NUL, não concatenação simples. O `serverRecoveryShare` é um valor aleatório armazenado nos metadados do envelope, do lado do servidor; o `normalizedPhrase` é a frase de recuperação do usuário. **Nenhuma das metades descriptografa sozinha** — a restauração exige a parte do servidor (buscada junto com o backup) *e* a frase em posse do usuário. **(Implementado)**

### 4.3 Recuperação por passkey — conhecimento zero, derivada de PRF {#43-passkey-recovery--zero-knowledge-prf-derived}

O slot `passkey` opcional adiciona um fator respaldado por hardware, e ele é de **conhecimento zero**: sua chave de desempacotamento é derivada **no aparelho** a partir da saída do PRF WebAuthn do autenticador (`hmac-secret`). O servidor não registra nenhum passkey, não emite desafios WebAuthn e não armazena nenhum segredo de recuperação — não há etapa de liberação pelo servidor.

- **Registro/asserção:** o `BackupPasskeyCoordinator` (`LavaSecApp`) executa o WebAuthn via `ASAuthorizationPlatformPublicKeyCredentialProvider`, com a parte confiante **`lavasecurity.app`**, solicitando a extensão PRF sobre um salt por credencial e exigindo verificação do usuário.
- **Derivação da chave (conhecimento zero):** o autenticador retorna uma saída de PRF que **nunca sai do aparelho**. O `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva a chave de empacotamento do slot dessa saída de PRF via HKDF-SHA256 (info `"LavaSec passkey backup PRF v1"`) e empacota a chave de payload com AES-GCM; apenas o salt PRF não secreto e o ID da credencial são persistidos no slot. Na restauração, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` reafirma a credencial para reproduzir a mesma saída de PRF, e o `decryptWithPasskeyPRFOutput` desempacota o slot localmente. O servidor **não** guarda nenhum segredo de passkey, então nenhum caminho de papel de serviço pode recuperar um backup protegido por passkey.

O design de custódia anterior (uma tabela `backup_passkey_recovery` de papel de serviço guardando um `recovery_secret` do lado do servidor, mais uma tabela `backup_passkey_challenges` e os endpoints de Worker `/v1/backup/passkeys/*`) foi **Descartado**: as tabelas foram removidas em uma migração do backend, o Worker não carrega nenhuma rota de passkey, e o `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` afirma de forma assertiva que o `BackupPasskeyRecoveryService` e qualquer caminho de custódia no servidor estão ausentes. **(Implementado)**

> **Ressalva de prontidão para produção:** tratar passkeys salvos como um fator recuperável totalmente pronto para produção em aparelhos físicos ainda depende da associação de webcredentials para `lavasecurity.app`. A metade do iOS está declarada — o `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` carrega `webcredentials:lavasecurity.app` — e a metade do servidor (o arquivo `apple-app-site-association` e os cabeçalhos) agora está hospedada no site de marketing. Até que essa associação resolva em um determinado aparelho, o caminho de associação de webcredentials pode falhar e expõe `BackupPasskeyError.webCredentialsAssociationUnavailable`. O fator passkey em si está implementado; sua prontidão de ponta a ponta em hardware real está **Planejada**.

---

## 5. Minimização de dados e postura de privacidade {#5-data-minimization--privacy-posture}

- **Conta opcional.** A proteção funciona sem conta; o login só habilita o backup das configurações.
- **Texto puro apenas local.** O telefone é o único lugar onde existem as configurações em texto puro e os segredos de descriptografia; o Supabase guarda um envelope opaco por usuário.
- **Payload minimizado.** Apenas as configurações da §3.2 entram no backup; `isPaid`, flags de QA, diagnósticos, snapshots e os bytes completos das listas de bloqueio são excluídos. As listas de bloqueio são referenciadas pelo ID do catálogo, nunca embutidas.
- **Sem telemetria de navegação/DNS.** Não há nenhuma tabela no servidor para consultas rotineiras de DNS ou telemetria por domínio; a filtragem permanece no aparelho.
- **O material de desbloqueio é local ao aparelho.** O material de desbloqueio do backup é armazenado com acessibilidade `…ThisDeviceOnly` e **não** é sincronizado pelo iCloud. Isso **reverteu** o design original do plano, que usava Keychain sincronizável, de modo que a Lava não sincroniza silenciosamente o material de desbloqueio pelo iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementado; reverte plano anterior.)**

### Exclusão de conta {#account-deletion}

A exclusão está **Implementada** e roda através de um endpoint de Worker autenticado, não de exclusões diretas pelo cliente. O `AccountAuthService.deleteAccount` envia o access token do usuário para `POST /v1/account/delete`; o Worker `lavasec-api` (papel de serviço) exclui as linhas de `bug_reports` do usuário (e seus anexos no R2), `user_backups`, `entitlements`, `user_settings` e `profiles`, depois exclui o usuário do Supabase Auth via a API de admin, retornando apenas um status de exclusão + os provedores vinculados. O app então faz logout localmente e limpa o material de desbloqueio do backup (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Observação: o frontmatter YAML do plano de exclusão já consta como `status: Done` e ele fica em `plans/implemented/`. Uma anotação **no corpo do texto** desatualizada diz `Status: Backlog.`, mas, pela regra de pasta de faixa (a pasta é a autoridade) e pela presença no código (app + Worker existem), o recurso está **Implementado**; a linha no corpo é um bug de documentação, não o frontmatter.

---

## 6. Resumo de status {#6-status-summary}

| Área | Detalhe | Status |
|---|---|---|
| Login Apple / Google via `id_token` no Supabase | Fluxos nativos, nonce com hash, troca via URLRequest bruta | Implementado |
| Login por e-mail/senha | Possuir senhas rejeitado | Descartado |
| Sessão no Keychain (local ao aparelho, por provedor) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementado |
| Envelope AES-256-GCM + slots de chave PBKDF2-HMAC-SHA256 (210k) | Lado do cliente; apenas texto cifrado + metadados não secretos para `user_backups` (RLS) | Implementado |
| Configuração sem senha (slots de aparelho + recuperação assistida + passkey opcional) | `makePasswordless` | Implementado |
| Slot de chave de senha no fluxo ativo | Sobrevive no `LavaSecCore` apenas para testes | Descartado |
| Frase de recuperação (CVCV de 8 palavras, ~105 bits) | Fator fora do aparelho | Implementado |
| Recuperação assistida (parte do servidor + frase via SHA256, delimitado por NUL) | Dois fatores; nenhuma metade sozinha | Implementado |
| Recuperação por passkey (conhecimento zero, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | Slot derivado da saída do PRF via HKDF, sem segredo no servidor | Implementado |
| Passkey como fator pronto para produção em hardware | Precisa da associação de webcredentials (AASA hospedado no site de marketing) | Planejado |
| Exclusão de conta (Worker autenticado, papel de serviço) | Remove backups/configurações/habilitações/perfil/anexos + usuário do Auth | Implementado |
| Trava biométrica/de presença do usuário no material de desbloqueio | Item de revisão de portão de lançamento | Planejado |
| Extração de `EncryptedBackupCoordinator` do `AppViewModel` | Apenas modularização; nenhuma mudança no modelo de segurança | Em andamento |

---

## Relacionados {#related}

- [Visão geral do sistema](./system-overview.md) — todo o sistema em uma tela, incluindo as fronteiras de confiança.
- [Cliente iOS](./ios-client.md) — o `AppViewModel` e os targets do app que conduzem o backup.
- [Backend e dados](./backend-and-data.md) — o Worker `lavasec-api`, o RLS do Supabase e o armazenamento em `user_backups`.
- [Filtragem de DNS e listas de bloqueio](./dns-filtering-and-blocklists.md) — os presets de resolver e os transportes cujas configurações são carregadas no payload de backup.
