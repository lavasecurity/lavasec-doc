---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Contas e Backup de Conhecimento Zero

> **Público:** engenheiros.
> **Autoridade:** quando este documento e um plano divergem, **o código prevalece** — as divergências são apontadas inline. O status reflete a realidade confirmada no código, não a aspiração do plano. Legenda de status: **Implementado** (lançado e confirmado no código), **Em andamento** (parcialmente concluído), **Planejado** (projetado, não construído), **Descartado** (rejeitado ou revertido).

As contas são **opcionais**. A proteção essencial é gratuita para sempre e não exige conta; o login existe apenas para fazer backup das suas *configurações*, criptografadas, para que você possa restaurá-las em um novo dispositivo. Este documento cobre o fluxo de autenticação, onde a sessão fica, o envelope de backup de conhecimento zero, os caminhos de recuperação e exatamente o que o servidor pode e não pode ver.

A promessa de privacidade canônica que este documento atende:

> Toda a filtragem de DNS acontece no dispositivo; a Lava nunca roteia sua navegação pelos seus servidores e nunca recebe o fluxo de domínios que você visita — o backend mantém apenas metadados de catálogo, um backup criptografado opaco por usuário e diagnósticos anonimizados que você escolhe enviar.

Divisão de componentes: a criptografia pura + a construção de requisições ficam em `LavaSecCore`; a orquestração + a interface ficam em `LavaSecApp`. Irmãos: [System Overview](./system-overview.md), [iOS Client](./ios-client.md), [Backend & Data](./backend-and-data.md), [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md).

---

## 1. Fluxo de autenticação

**Provedores: apenas Apple e Google.** **(Implementado)** `AccountAuthProvider` enumera exatamente `.apple` e `.google` (`AccountAuthService.swift`). E-mail/senha — e qualquer recuperação assistida pelo suporte que ignore a autenticação — é explicitamente **Descartado**; possuir senhas adicionaria obrigações de redefinição/MFA/bloqueio/vazamento que não valem a complexidade enquanto Apple/Google bastam, e a recuperação por bypass quebraria a garantia de conhecimento zero.

Ambos os provedores usam a **concessão nativa `id_token`**, não o SDK Swift do Supabase e nem OAuth via web:

1. **Faça login nativamente.** Apple via AuthenticationServices; Google via o SDK GoogleSignIn. Cada um produz um `id_token` do provedor (o Google também um access token). O app gera um nonce bruto CSPRNG, faz o hash dele com SHA256 e passa o hash ao provedor para que o `id_token` emitido fique vinculado a ele. **(Implementado)**
2. **Troque no Supabase.** `SupabaseIDTokenAuth` (`LavaSecCore`) constrói uma `URLRequest` bruta para o Supabase Auth `auth/v1/token?grant_type=id_token`, postando `provider` + `id_token` + `access_token` opcional + o nonce **bruto** (para que o Supabase possa verificar o vínculo e rejeitar replays), com o cabeçalho `apikey`. Sem SDK; `LavaSecCore` permanece livre de dependências de rede/autenticação. **(Implementado)**
3. **Receba uma sessão.** O Supabase verifica o token e retorna uma sessão: um access token, um refresh token, uma expiração e um registro de usuário (provider/providers). O refresh usa o mesmo helper com `grant_type=refresh_token`.

`AccountAuthService` (`@MainActor`, `LavaSecApp`) orquestra tudo isso — ele executa os fluxos nativos, realiza a troca, persiste e atualiza sessões, expõe `AccountAuthState` e conduz a exclusão de conta através do Worker.

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

## 2. Armazenamento de sessão e Keychain

A **única** coisa persistida a partir do login é a sessão do Supabase — os access e refresh tokens como JSON. **Não há** espelho do lado do servidor de quem você é além do usuário do Supabase Auth e das linhas que você possui.

- **Onde:** `AccountSessionKeychainStore` (`LavaSecApp`), serviço de Keychain `com.lavasec.account-session`, armazenado **por provedor** (`supabase-session-apple` / `supabase-session-google`, mais uma migração de conta legada). **(Implementado)**
- **Acessibilidade:** todos os stores compartilham `GenericKeychainStore` (`LavaSecCore`), fixado em `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. Isso significa **local ao dispositivo, não sincronizado via iCloud e não incluído em backups do dispositivo**. **(Implementado)**

Os mesmos mecanismos do `GenericKeychainStore` dão suporte a três stores: a sessão de conta, o material de desbloqueio do backup (`BackupKeychainStore`, serviço `com.lavasec.zero-knowledge-backup`) e o passcode do app. Nenhum deles sincroniza pelo iCloud Keychain.

> **Item de revisão em aberto (não é um comportamento declarado):** a classe de acessibilidade atual não tem barreira biométrica/de presença do usuário (sem `SecAccessControl` `.userPresence`/`.biometryCurrentSet`). Se devemos endurecer o material de desbloqueio para um controle de acesso com barreira de presença está sendo acompanhado como item de revisão de gate de release; o valor lançado hoje é after-first-unlock-this-device-only. **(Planejado)**

---

## 3. Backup de conhecimento zero

### 3.1 O que é, com precisão

Quando você ativa o backup criptografado, o **cliente iOS** criptografa uma cópia minimizada das suas *configurações* e envia apenas o texto cifrado mais metadados não secretos ao Supabase. O telefone é o único lugar onde o texto plano e os segredos de descriptografia jamais existem.

> **Backup de conhecimento zero:** Envelope AES-256-GCM do lado do cliente; a chave aleatória de payload é encapsulada em slots de chave por slot — PBKDF2-HMAC-SHA256 (210 mil iterações) para os slots de senha/frase/dispositivo/assistido, HKDF-SHA256 para o slot de passkey PRF. Apenas texto cifrado + metadados não secretos são enviados ao Supabase `user_backups` (RLS por usuário). O servidor não consegue descriptografar sem um segredo mantido pelo usuário. O slot de passkey é **também** de conhecimento zero: sua chave de desencapsulamento é derivada no dispositivo a partir da saída WebAuthn PRF (`hmac-secret`) do autenticador, e o servidor não mantém nenhum segredo de passkey (veja §4.3).

### 3.2 O que entra no backup (o payload minimizado)

`BackupConfigurationPayload` (`LavaSecCore`) é o texto plano que é selado. Ele é deliberadamente pequeno e faz round-trip com `AppConfiguration`. **(Implementado)**

**Incluído:** **IDs** de blocklists habilitadas (referências de catálogo, não os bytes das listas), domínios permitidos/bloqueados, preset de resolvedor / resolvedor personalizado, preferências de log local, o ledger do LavaGuard, uma dica de proteção e metadados de fontes de blocklist personalizadas.

**Excluído:** `isPaid` (a habilitação é local), flags de QA, diagnósticos, snapshots de Filtro e o conteúdo completo das blocklists (referenciado apenas por ID de catálogo). Seu histórico de navegação e consultas de DNS nunca fazem parte deste payload porque o dispositivo nunca os registra como um fluxo de telemetria de rotina.

### 3.3 O envelope (criptografia do lado do cliente)

`ZeroKnowledgeBackupEnvelope` (`LavaSecCore`) implementa a criptografia. **(Implementado)**

1. **Criptografia do payload.** O payload minimizado é selado uma vez com **AES-256-GCM** sob uma **chave de payload de 32 bytes** aleatória (gerada com `SecRandomCopyBytes`).
2. **Encapsulamento de chave (slots de chave).** Essa única chave de payload é encapsulada de forma independente em um ou mais **slots de chave**, um por segredo, e então faz AES-GCM-wrap de uma cópia da chave de payload. O segredo de qualquer slot único desbloqueia todo o backup. A derivação da chave de encapsulamento é por tipo de slot: os slots `password` / `recoveryPhrase` / `keychain` (dispositivo) / `assistedRecovery` usam **PBKDF2-HMAC-SHA256, 210.000 iterações** (produção; `defaultPasswordIterations = 210_000`) com um salt aleatório novo de 16 bytes por slot; o slot `passkey` usa **HKDF-SHA256** sobre a saída PRF do autenticador (info `"LavaSec passkey backup PRF v1"`), com o salt PRF não secreto persistido no slot para que a restauração possa reproduzir a saída.
3. **Tipos de slot.** O envelope suporta cinco tipos de slot: `password`, `recoveryPhrase`, `keychain` (segredo do dispositivo), `assistedRecovery` e `passkey`.

A configuração lançada é **sem senha** (`makePasswordless`, conduzida por `AppViewModel.turnOnEncryptedBackup`). Ela cria um **slot `keychain` (dispositivo) + um slot `assistedRecovery` + um slot `passkey` opcional**. As fábricas `password` / `recoveryPhrase` e os métodos de descriptografia ainda existem para envelopes legados/retrocompatíveis (exercitados apenas por testes), mas a interface ativa nunca cria um envelope somente-senha — trate o backup por senha como não lançado. **(Implementado; slot de senha Descartado do fluxo ativo.)**

**Integridade / anti-downgrade:** `envelopeVersion` é fixado rigidamente em `1`, e a KDF de cada slot é fixada por tipo — `PBKDF2-HMAC-SHA256` para os slots de senha/frase/dispositivo/assistido, `HKDF-SHA256` para o slot de passkey PRF. Versões não suportadas ou KDFs incompatíveis são rejeitadas, de modo que metadados forjados ou rebaixados não podem enfraquecer o desencapsulamento. **(Implementado)**

### 3.4 Upload e armazenamento

`BackupSyncService` (`SupabaseBackupSyncService`, `LavaSecApp`) faz upload do envelope **diretamente** para a tabela PostgREST `user_backups` do Supabase, fazendo upsert em `user_id`, com escopo pelo access token do usuário. **Não há rota de Worker para upload de envelope** — o cliente fala diretamente com o Supabase sob RLS; o Worker só toca em `user_backups` para excluí-lo durante a exclusão de conta. **(Implementado)**

O que cai em `user_backups`:

- o **texto cifrado**, e
- **apenas metadados não secretos:** nome da cifra, os registros de slot de chave (salts, contagens de iterações, chaves encapsuladas, rótulos de slot), o `server_recovery_share`, `createdAt` e o tamanho em bytes.

A linha é protegida por **segurança em nível de linha**: cada linha é legível/gravável apenas pelo seu proprietário (`auth.uid() = user_id`); o papel anônimo não tem acesso. O tamanho é limitado a ~256 KiB de texto cifrado / 32 KiB de metadados no nível do banco de dados (`20260518000000_zero_knowledge_backups.sql`, endurecido em `20260605000000_tighten_backup_envelope_constraints.sql`). **(Implementado)**

### 3.5 A garantia — o que o servidor pode e não pode ver

**O servidor armazena:** texto cifrado, salts/iterações de KDF, slots de chave encapsulados, o `server_recovery_share` e alguns campos não secretos (cifra, tamanho, timestamp).

**O servidor nunca recebe nem armazena:** as configurações/domínios/preferências de DNS em texto plano, a frase de recuperação, qualquer senha de backup ou a chave de payload desencapsulada.

**Portanto:** o Supabase **não consegue descriptografar um backup** sem um segredo mantido pelo usuário. Todos os três caminhos de restauração — o slot de chave do dispositivo, a frase de recuperação (combinada com o share do servidor, §4.2) e o slot de passkey (a saída PRF do autenticador, §4.3) — descriptografam **no dispositivo**, e o servidor não mantém nenhum segredo de descriptografia para nenhum deles. Isso é afirmado nos comentários de migração e no plano de privacidade, e testado (os testes de envelope confirmam que nenhum texto plano de domínio/URL vaza para o formato enviado).

**Ressalva precisa do modelo de ameaças — não exagere a alegação.** Para o slot de **recuperação assistida**, o servidor mantém *tanto* o `server_recovery_share` *quanto* o slot `assistedRecovery` encapsulado em `user_backups`. A única coisa que lhe falta é a frase de recuperação do usuário, que a Lava nunca recebe. Então, se o servidor fosse totalmente comprometido, a entropia da frase de recuperação (~105 bits, veja §4.1) mais o custo de 210 mil iterações do PBKDF2 seria a **única** barreira contra um ataque de força bruta offline desse slot. Isso é intencional (a recuperação assistida é de dois fatores por design — nenhuma metade sozinha descriptografa), mas significa que a entropia da frase de recuperação é estrutural, não decorativa. O segredo do slot `keychain` (dispositivo) nunca sai do dispositivo, então ele não fica exposto a um comprometimento do servidor de forma alguma.

---

## 4. Recuperação

Um backup só é útil se você puder restaurá-lo. `restoreEncryptedBackup` (em `AppViewModel`) descriptografa tentando os slots disponíveis: chave do dispositivo, frase de recuperação ou passkey. Em todos os modos, o envelope é carregado localmente (ou buscado do Supabase) e então **descriptografado no dispositivo** — o servidor nunca descriptografa.

### 4.1 Frase de recuperação

`BackupRecoveryPhrase` (`LavaSecCore`) gera uma **frase CVCV de 8 palavras** (consoante-vogal-consoante-vogal) a partir de `SecRandom` com amostragem por rejeição (~13,2 bits/token → **~105 bits no total**), normalizada em minúsculas. **(Implementado)** A restauração tolera a formatação do usuário (espaçamento/maiúsculas-minúsculas) via parsing/normalização antes de o slot ser tentado.

Este é o fator de recuperação **fora do dispositivo** do usuário — salvo pelo usuário, nunca enviado. Conforme o endurecimento de privacidade (§5), copiar a frase é **opcional** e, quando usado, passa por uma área de transferência apenas local / expirável (10 minutos) em vez de forçar a exposição na área de transferência global.

### 4.2 Recuperação assistida (a combinação de dois fatores)

A frase de recuperação sozinha **não** desbloqueia o slot `assistedRecovery`. O segredo do slot é derivado de **ambas** as metades:

```
assistedRecoverySecret =
    base64url( SHA256( "LavaSec assisted recovery v1" ‖ serverRecoveryShare ‖ normalizedPhrase ) )
```

Os três segmentos são unidos por um **separador de byte NUL (`0x00`)** na entrada UTF-8 real — ou seja, a string hasheada é `"LavaSec assisted recovery v1\0" + serverRecoveryShare + "\0" + normalizedPhrase` — de modo que o `‖` acima denota concatenação delimitada por NUL, não concatenação simples. `serverRecoveryShare` é um valor aleatório armazenado nos metadados do envelope do lado do servidor; `normalizedPhrase` é a frase de recuperação do usuário. **Nenhuma metade sozinha descriptografa** — a restauração requer o share do servidor (buscado com o backup) *e* a frase mantida pelo usuário. **(Implementado)**

### 4.3 Recuperação por passkey — conhecimento zero, derivada de PRF

O slot `passkey` opcional adiciona um fator com respaldo de hardware, e é de **conhecimento zero**: sua chave de desencapsulamento é derivada **no dispositivo** a partir da saída WebAuthn PRF (`hmac-secret`) do autenticador. O servidor não registra nenhuma passkey, não emite nenhum desafio WebAuthn e não armazena nenhum segredo de recuperação — não há etapa de liberação no servidor.

- **Registro/asserção:** `BackupPasskeyCoordinator` (`LavaSecApp`) executa WebAuthn via `ASAuthorizationPlatformPublicKeyCredentialProvider`, relying party **`lavasecurity.app`**, solicitando a extensão PRF em um salt por credencial e exigindo verificação do usuário.
- **Derivação de chave (conhecimento zero):** o autenticador retorna uma saída PRF que **nunca sai do dispositivo**. `ZeroKnowledgeBackupEnvelope.makeWithPRF` (`lavasec-ios: Sources/LavaSecCore/ZeroKnowledgeBackupEnvelope.swift`) deriva via HKDF-SHA256 a chave de encapsulamento do slot a partir dessa saída PRF (info `"LavaSec passkey backup PRF v1"`) e faz AES-GCM-wrap da chave de payload; apenas o salt PRF não secreto e o ID da credencial são persistidos no slot. Na restauração, `passkeyPRFOutputForRestore` → `BackupPasskeyCoordinator.assertPasskeyPRFOutput` reasserta a credencial para reproduzir a mesma saída PRF, e `decryptWithPasskeyPRFOutput` desencapsula o slot localmente. O servidor **não** mantém nenhum segredo de passkey, então nenhum caminho de service-role pode recuperar um backup protegido por passkey.

O design de escrow anterior (uma tabela `backup_passkey_recovery` de service-role mantendo um `recovery_secret` do lado do servidor, mais uma tabela `backup_passkey_challenges` e endpoints de Worker `/v1/backup/passkeys/*`) foi **Descartado**: as tabelas foram removidas em uma migração de backend, o Worker não carrega nenhuma rota de passkey, e `lavasec-ios: Tests/LavaSecCoreTests/BackupSetupSourceTests.swift` afirma positivamente que `BackupPasskeyRecoveryService` e qualquer caminho de escrow no servidor estão ausentes. **(Implementado)**

> **Ressalva de prontidão para produção:** tratar passkeys salvas como um fator recuperável totalmente pronto para produção em dispositivos físicos ainda depende da associação webcredentials para `lavasecurity.app`. A metade do iOS está declarada — `lavasec-ios: LavaSecApp/LavaSecApp.entitlements` carrega `webcredentials:lavasecurity.app` — e a metade do servidor (o arquivo `apple-app-site-association` e os cabeçalhos) agora está hospedada no site de marketing. Até que essa associação seja resolvida em um dado dispositivo, o caminho de associação webcredentials pode falhar e expõe `BackupPasskeyError.webCredentialsAssociationUnavailable`. O fator de passkey em si está implementado; sua prontidão de ponta a ponta em hardware real é **Planejada**.

---

## 5. Minimização de dados e postura de privacidade

- **Conta opcional.** A proteção funciona sem conta; o login só habilita o backup das configurações.
- **Texto plano apenas local.** O telefone é o único lugar onde as configurações em texto plano e os segredos de descriptografia existem; o Supabase mantém um envelope opaco por usuário.
- **Payload minimizado.** Apenas as configurações em §3.2 entram no backup; `isPaid`, flags de QA, diagnósticos, snapshots e os bytes completos das blocklists são excluídos. As blocklists são referenciadas por ID de catálogo, nunca embutidas.
- **Sem telemetria de navegação/DNS.** Não há tabela do lado do servidor para consultas de DNS de rotina ou telemetria por domínio; a filtragem permanece no dispositivo.
- **O material de desbloqueio é local ao dispositivo.** O material de desbloqueio do backup é armazenado com acessibilidade `…ThisDeviceOnly` e **não** é sincronizado via iCloud. Isso **reverteu** o design de Keychain sincronizável do plano original, então a Lava não sincroniza silenciosamente o material de desbloqueio pelo iCloud (`plans/implemented/2026-05-25-backup-privacy-secret-handling-plan.md`). **(Implementado; reverte plano anterior.)**

### Exclusão de conta

A exclusão está **Implementada** e roda através de um endpoint de Worker autenticado, não exclusões diretas do cliente. `AccountAuthService.deleteAccount` envia o access token do usuário para `POST /v1/account/delete`; o Worker `lavasec-api` (service role) exclui os `bug_reports` do usuário (e seus anexos no R2), `user_backups`, `entitlements`, `user_settings` e as linhas de `profiles`, depois exclui o usuário do Supabase Auth via a API de admin, retornando apenas um status de excluído + os provedores vinculados. O app então faz logout localmente e limpa o material de desbloqueio do backup (`plans/implemented/2026-05-25-account-deletion-data-rights-plan.md`).

> Nota: o frontmatter YAML do plano de exclusão já indica `status: Done` e ele fica em `plans/implemented/`. Uma anotação **no corpo** desatualizada indica `Status: Backlog.`, mas conforme a regra da pasta de lane (a pasta é a autoridade) e a presença de código (app + Worker existem), o recurso está **Implementado**; a linha no corpo é um bug de documentação, não o frontmatter.

---

## 6. Resumo de status

| Área | Detalhe | Status |
|---|---|---|
| Login Apple / Google via `id_token` pelo Supabase | Fluxos nativos, nonce hasheado, troca via URLRequest bruta | Implementado |
| Login por e-mail/senha | Posse de senhas rejeitada | Descartado |
| Sessão no Keychain (local ao dispositivo, por provedor) | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | Implementado |
| Envelope AES-256-GCM + slots de chave PBKDF2-HMAC-SHA256 (210k) | Do lado do cliente; apenas texto cifrado + metadados não secretos para `user_backups` (RLS) | Implementado |
| Configuração sem senha (slots de dispositivo + recuperação assistida + passkey opcional) | `makePasswordless` | Implementado |
| Slot de chave de senha no fluxo ativo | Sobrevive em `LavaSecCore` apenas para testes | Descartado |
| Frase de recuperação (CVCV de 8 palavras, ~105 bits) | Fator fora do dispositivo | Implementado |
| Recuperação assistida (share do servidor + frase via SHA256, delimitado por NUL) | Dois fatores; nenhuma metade sozinha | Implementado |
| Recuperação por passkey (conhecimento zero, WebAuthn PRF/`hmac-secret`, RP `lavasecurity.app`) | Slot derivado da saída PRF via HKDF, sem segredo no servidor | Implementado |
| Passkey como fator pronto para produção em hardware | Precisa da associação webcredentials (AASA hospedado no site de marketing) | Planejado |
| Exclusão de conta (Worker autenticado, service role) | Remove backups/configurações/entitlements/perfil/anexos + usuário do Auth | Implementado |
| Barreira biométrica/de presença do usuário no material de desbloqueio | Item de revisão de gate de release | Planejado |
| Extração de `EncryptedBackupCoordinator` de `AppViewModel` | Apenas modularização; sem mudança no modelo de segurança | Em andamento |

---

## Relacionados

- [System Overview](./system-overview.md) — o sistema inteiro em uma tela, incluindo as fronteiras de confiança.
- [iOS Client](./ios-client.md) — `AppViewModel` e os targets do app que conduzem o backup.
- [Backend & Data](./backend-and-data.md) — o Worker `lavasec-api`, o RLS do Supabase e o armazenamento de `user_backups`.
- [DNS Filtering & Blocklists](./dns-filtering-and-blocklists.md) — os presets de resolvedor e os transportes cujas configurações são carregadas no payload de backup.
