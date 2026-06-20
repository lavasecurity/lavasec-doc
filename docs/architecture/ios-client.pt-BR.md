---
last_reviewed: 2026-06-19
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "1fbab70"}
---

# Arquitetura do cliente iOS

> Público: pessoas de engenharia iOS que trabalham em `lavasec-ios`.

O Lava Security é um app iOS que prioriza a privacidade e filtra o DNS localmente no dispositivo, por meio de um túnel de pacotes NetworkExtension que roda no próprio aparelho. Ele bloqueia domínios indesejados e reconhecidamente arriscados sem encaminhar a sua navegação pelos servidores da Lava. Este documento mostra como o cliente iOS é estruturado: os targets, como o app conversa com a sua extensão de túnel, o ciclo de vida da VPN, o modelo de estado do Guardian, a Live Activity e o widget, o fluxo de boas-vindas e o dono do estado no lado do app (`AppViewModel`).

Para a visão do sistema como um todo (o app, o Worker do catálogo e o Supabase), veja a [Visão geral do sistema](./system-overview.md).

---

## 1. Targets e responsabilidades

O cliente é distribuído como três targets executáveis mais uma biblioteca de núcleo compartilhada. Os três targets participam do mesmo **App Group** (`group.com.lavasec`) e fazem link com `LavaSecCore`.

| Target | Bundle id | Responsabilidade |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | O app em SwiftUI. É dono da interface, possui o entitlement do NetworkExtension e controla o túnel via `NETunnelProviderManager`. O `AppViewModel` é a fonte da verdade do ciclo de vida da VPN. |
| **Túnel de pacotes** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | A subclasse `NEPacketTunnelProvider` chamada `PacketTunnelProvider` (também conhecida como `LavaSecTunnel`). Analisa os pacotes DNS, extrai o domínio consultado, avalia-o contra o snapshot compilado mapeado em memória e encaminha adiante as consultas permitidas. Limitada pelo teto de memória jetsam de aproximadamente 50 MiB por processo. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Um `WidgetBundle` cujo único membro é `LavaProtectionLiveActivityWidget` — a apresentação da Live Activity / Dynamic Island. |

O código compartilhado fica em dois lugares:

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — o núcleo independente de plataforma: o motor de filtragem, os transportes do resolvedor, a matemática de snapshot/orçamento, os stores de proteção e o núcleo `GuardianMascotAnimation`. Conforme `VPNLifecycleController.swift:3-6`, os tipos do NetworkExtension são mantidos de fora deste módulo de propósito, para que sua lógica de ciclo de vida continue testável com objetos falsos; o target do app fornece as conformidades apoiadas em `NetworkExtension`.
- **`Shared/`** — código compilado em mais de um target (por exemplo, `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

Os detalhes internos do túnel de pacotes (análise de DNS, o snapshot compilado, os transportes criptografados do resolvedor e o orçamento de regras de filtro) são abordados a fundo em [Filtragem de DNS e listas de bloqueio](./dns-filtering-and-blocklists.md). Este documento foca na arquitetura do lado do app e na fronteira entre o app e a extensão.

---

## 2. IPC entre app e extensão

O app e a extensão de túnel de pacotes são processos separados. Eles se coordenam por três mecanismos, todos ancorados no App Group.

### Contêiner do App Group

`group.com.lavasec` é o contêiner compartilhado que permite ao app, ao túnel e ao widget ler e escrever o mesmo estado e a mesma configuração do `LavaSecCore`. O `LavaSecAppGroup` (`Shared/AppGroup.swift`) centraliza cada chave e nome de arquivo compartilhado, para que os processos nunca divirjam em constantes de string, incluindo:

- Os artefatos do snapshot compilado (`filter-snapshot.compact`, `filter-snapshot.json`), o `app-configuration.json` serializado, a saúde do túnel (`tunnel-health.json`), os diagnósticos e o log de atividade de rede.
- Chaves de `UserDefaults` compartilhadas para a sessão de proteção e o estado de pausa. Elas referenciam diretamente os stores do `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — de modo que o app, o túnel e as intents da Live Activity compartilham um único layout de chaves, um único contador de revisão e um único esquema de deduplicação.
- O diretório de cache do catálogo e o arquivo de log de depuração no dispositivo.

A URL do contêiner é resolvida via `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Mensagem de comando / provedor (o caminho de controle)

O app comanda o túnel com **`sendProviderMessage`** para todos os comandos. `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) obtém a `NETunnelProviderSession` ativa do manager em cache e chama `session.sendProviderMessage(...)`. O payload é codificado por `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) em um pequeno envelope JSON que carrega um `kind` de mensagem e um `operationID` opcional (usado para rastreamento de latência de ponta a ponta).

Os tipos de mensagem reconhecidos são constantes em `LavaSecAppGroup`:

| Constante da mensagem | Efeito no túnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Força a recarga do snapshot de filtro compilado. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Relê apenas o estado de pausa compartilhado. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Recarrega a configuração; somente uma mudança de *identidade do resolvedor* dispara uma reconexão visível. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Manutenção de diagnósticos/logs. |

No lado do túnel, `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica o envelope e faz um switch no `kind`. Vale notar que `reload-configuration` carrega a nova configuração para que campos não relacionados ao resolvedor (alternâncias de diagnóstico, status pago) entrem em vigor, mas só reinicia o runtime de DNS e reaplica as configurações de rede do túnel — uma reconexão visível — quando a identidade do resolvedor de fato muda (`PacketTunnelProvider.swift:768-792`). Uma mudança de flag de diagnóstico ou de status pago nunca derruba a conexão ativa.

Os auxiliares `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` do app (`AppViewModel.swift:7062`/`7070`) são invólucros simples que enviam essas mensagens.

### Por que mensagens de provedor para o controle app→túnel

**`sendProviderMessage` é o único caminho de controle app→túnel — não existe um sinal Darwin app→túnel.** Um desenho anterior publicava um sinal Darwin via `CFNotificationCenter` ao pausar e o observava dentro da extensão, mas ele nunca disparava de forma confiável no processo do NetworkExtension e foi removido. O serviço de comando não publica mais `CFNotificationCenterPostNotification`, e o túnel não adiciona mais um `CFNotificationCenterAddObserver` — a ausência de ambos é verificada por testes de introspecção de código-fonte (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` para a publicação no serviço de comando; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` para o observador do túnel), justamente para impedir que sejam reintroduzidos. (As linhas `import Darwin` que permanecem no serviço de comando e no túnel são para primitivas de `flock`/socket, não para notificações.)

Um caminho Darwin *ainda* existe no sentido oposto. O túnel envia ao app um aviso de mudança de saúde: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) publica `CFNotificationCenterPostNotification` no canal `com.lavasec.protection.tunnel-health-changed` (o nome do canal mora em `TunnelHealthSignal.swift`, não em `AppGroup.swift`), e o app o observa via `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), conectado no `AppViewModel` para chamar `handleTunnelHealthNudge()`. A presença desse aviso de saúde túnel→app é verificada por `LavaLiveActivitySourceTests.swift:1059-1075`.

Para o controle app→túnel, a pausa é entregue gravando o `ProtectionPauseStore` compartilhado e, em seguida, enviando a mensagem de provedor `reload-protection-pause`, para que o túnel execute `refreshProtectionPauseStateOnly`. `AppViewModel.swift:4995-4996` documenta a regra diretamente: o app "também nunca depende do observador Darwin de snapshot, usando sempre `sendProviderMessage`." Trate o par App Group (estado compartilhado) + `sendProviderMessage` (o sinal de despertar/controle) como o caminho de controle app→túnel.

### Serviço de comando da Live Activity

`LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) é o ponto de entrada para as ações da Dynamic Island / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`). As `LiveActivityIntent`s em `LavaLiveActivityIntents.swift` rodam no processo do app (que possui o entitlement do NetworkExtension), então:

- **Pausar / retomar** passam por um lock de arquivo entre processos (`protection-command.lock`, `flock`) e pelos `ProtectionPauseStore` / `ProtectionSessionStore` do `LavaSecCore`, que são donos da emissão de revisão e da deduplicação de comandos duplicados (o `commandID` encadeia o id de operação de quem chamou, para que um comando reentregue não emita uma segunda revisão). O resultado agenda uma atualização da Live Activity protegida por revisão.
- **Reconectar** é tratado diretamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): chama `loadAllFromPreferences` e inicia o primeiro manager de túnel instalado via `startVPNTunnel()` (porque `loadAllFromPreferences` já está limitado às configurações NE deste app, esse primeiro manager é o da Lava — diferente de `VPNLifecycleController.matchingManagers()`, ele não faz uma correspondência explícita de identidade). O Conectar Sob Demanda já está ativado, então isso apenas força uma conexão imediata; a reconciliação de status do app então retorna a Live Activity para `.on` assim que conectado.

---

## 3. Ciclo de vida e controle da VPN

`AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) é a fonte da verdade do ciclo de vida da VPN no app. Ele orquestra ligar/desligar, mantém em cache o `NETunnelProviderManager` ativo e publica o status para o SwiftUI.

### Seleção de manager e a matemática do ciclo de vida

A lógica reutilizável de ciclo de vida, livre de NetworkExtension, mora em `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). O app fornece as conformidades de `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting` apoiadas em `NETunnelProviderManager`; o controlador cuida de:

- **Seleção e deduplicação** — `matchingManagers()` filtra para os managers da Lava via `LavaTunnelConfigurationIdentity.matches(...)`, ordena por `selectionPriority` (ativo primeiro, depois o nome de exibição canônico), e `removeDuplicateManagers(keeping:)` converge para um único sobrevivente.
- **Esperas de conectar/parar** — `waitForConnect` / `waitForStop` consultam o status da conexão ativa com uma tolerância `startGraceInterval`, porque logo após `startVPNTunnel` a conexão pode brevemente reportar um status não pendente antes de o iOS fazer a transição para `.connecting`.

### Ligar / desligar

`enableProtection(...)` (`AppViewModel.swift:5764`) é **cache-first**: quando existe um artefato preparado e confirmadamente reutilizável para a configuração atual, a VPN pode subir imediatamente a partir do cache enquanto uma sincronização de catálogo em andamento continua atualizando em segundo plano, e `performCatalogSync` reconcilia o túnel em execução ao concluir. Ela só bloqueia na sincronização quando não há nada válido de onde partir (por exemplo, quando o usuário acabou de mudar o conjunto da lista habilitada, invalidando a identidade do artefato em cache).

`disableProtection(...)` (`AppViewModel.swift:5972`) desliga o Conectar Sob Demanda *antes* de parar o túnel, para que o iOS não o reconecte de imediato. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) instala uma `NEOnDemandRuleConnect` (correspondência de interface `.any`) e salva as preferências — salvar (e não apenas definir) é necessário para que o iOS respeite a mudança.

### Observação de status (e uma ressalva sobre aquecimento)

`AppViewModel` observa `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) e publica `vpnStatus`/`isVPNConfigurationInstalled`. Algo importante: quando um manager já está em cache, ele lê a conexão ativa do manager em cache em vez de forçar uma atualização via `loadAllFromPreferences`: `loadAllFromPreferences` por si só republica `NEVPNStatusDidChange`, e uma atualização forçada dentro do observador produziu uma tempestade autossustentável — o comentário no código (`AppViewModel.swift:1046-1048`) registra os cerca de 370 eventos/s medidos e a regressão de aquecimento de 134% de CPU que isso causou. As propriedades publicadas só mudam em transições reais, de modo que ticks ociosos param de invalidar o SwiftUI.

### Reconciliação fail-closed sob demanda

O Conectar Sob Demanda pode subir o túnel **a frio** no lançamento (ou depois que o iOS o derruba numa mudança de rede) antes de o app ter enviado um snapshot. Um túnel a frio sem um snapshot persistido reutilizável carrega em modo **fail-closed** — bloqueia todo o tráfego — e nunca se recupera sozinho. `AppViewModel` lida com isso em dois caminhos de lançamento, ambos condicionados à conclusão do onboarding (`hasCompletedOnboarding`, espelhando a flag `@AppStorage("hasSeenLavaOnboarding")`):

- **Após o onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) roda sempre que a proteção está ativa no lançamento: ele prepara o snapshot de inicialização, persiste o estado compartilhado e envia `reload-snapshot` para que o túnel recarregue suas regras reais e saia do fail-closed. O fail-closed continua sendo o padrão seguro; isso apenas o substitui rapidamente. (Corrige filtros mostrados em vermelho / tráfego bloqueado depois de reiniciar o app enquanto o Conectar Sob Demanda mantém o túnel de pé.)
- **Durante o onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) roda *antes* de qualquer trabalho de rede quando o onboarding ainda não terminou. O iOS nem sempre remove de forma confiável um perfil de VPN ao apagar o app, então uma reinstalação pode herdar uma configuração órfã, com sob demanda ativado, que sobe um túnel a frio em fail-closed antes de o usuário ter escolhido qualquer lista de bloqueio. Esse caminho **remove** a configuração (`removeFromPreferences`) em vez de salvar uma modificação nela — `saveToPreferences` reexibiria o aviso de sistema "Adicionar Configurações de VPN" em um perfil que esta instalação não possui, disparando a caixa de diálogo no início do app, antes de a tela de onboarding ser renderizada. É uma operação sem efeito numa instalação limpa e quando a configuração herdada já está inerte.

---

## 4. Guardian / modelo de estado

Existem dois vocabulários de estado relacionados: uma *avaliação* de conectividade e um estado do *mascote* Guardian.

### Avaliação de conectividade

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) mapeia um `TunnelHealthSnapshot` para um `ProtectionConnectivityAssessment` com uma de **seis severidades** e **duas ações**:

- Severidades: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Ações primárias: `turnOff` ou `reconnect`.

Essa avaliação única comanda tanto a superfície do Guard dentro do app quanto (após um mapeamento adicional) o estado da Dynamic Island, de modo que os dois nunca se contradigam.

### Estados do mascote Guardian

O mascote Soft Shield Guardian tem exatamente **sete** estados emocionais — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Cada estado declara seus `allowedNextStates`, de modo que as transições são restritas (por exemplo, `grateful` só retorna a `awake`; `GuardianMascotAnimation.swift:12-29`). Semântica:

- `retrying` = autorrecuperação tranquila.
- `concerned` = pedido de ajuda gentil.
- `grateful` = comemoração de sucesso (usado nas superfícies de onboarding/configurações, não no mapa de conectividade).

`GuardianMascotAnimation` é o núcleo de animação procedural em `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) é a renderização em SwiftUI e dá suporte às peles de personalização selecionadas por `GuardianShieldStyle` (nomes de exibição Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, com o mapeamento de `displayName` nas linhas 18-35). Alguns valores brutos divergem de seus nomes de exibição (por exemplo, `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"` e `purpleObsidian` é exibido como "Amethyst"), então persista o valor bruto, não o rótulo.

### Como os dois se conectam

O `LavaActivityAttributes.ProtectionState` da Live Activity (`Shared/LavaActivityAttributes.swift`) faz a ponte entre a avaliação e um estado do mascote via `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). O `AppViewModel` escolhe o estado de proteção da Dynamic Island a partir do mesmo `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): uma severidade `networkUnavailable` vira `.networkUnavailable`, `recovering` vira `.reconnecting`, uma ação primária `reconnect` vira `.needsReconnect` e, caso contrário, `.on`.

> Nota: `LavaTier` (o enum de profundidade do design system: calmo → **Floor** / comemorativo → **Window** / técnico → **Workshop**) é distribuído na camada do design system (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), conectado a superfícies representativas — veja [o design system](../design-system/overview.md). Ele governa a profundidade do design system, não o caminho de proteção/túnel do cliente descrito aqui.

---

## 5. Live Activity e widget

O target do widget renderiza apenas a Live Activity e a Dynamic Island. `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) expõe um único `LavaProtectionLiveActivityWidget`, um `ActivityConfiguration(for: LavaActivityAttributes.self)` com:

- Uma visão de tela bloqueada, uma região central expandida da Dynamic Island e apresentações compacta/minimal que renderizam `SoftShieldGuardian` mais um glifo de status. As visões compacta/de tela bloqueada recalculam o estado de proteção *efetivo* num `TimelineView` por segundo, de modo que a contagem regressiva de pausa permanece ao vivo sem precisar de um push.

`LavaActivityAttributes.ContentState` carrega `protectionState`, um `resumeDate` (para as contagens regressivas de pausa), `pauseRequiresAuthentication` e o `shieldStyle` escolhido. A decodificação é tolerante — um `shieldStyle` ausente recai para `.original` — de modo que payloads de Live Activity mais antigos continuam funcionando.

No lado do app, `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) é dono do `Activity<LavaActivityAttributes>` ao vivo: ele observa mudanças de autorização do ActivityKit, só oferece Live Activities nos formatos de telefone/tablet, e `reconcile(...)` inicia/atualiza/encerra a activity para corresponder ao estado de proteção solicitado. `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) é o único funil que recalcula o estado desejado e chama o controlador. Os botões da Dynamic Island despacham `LiveActivityIntent`s, que chamam `LavaProtectionCommandService` como descrito em [§2](#2-ipc-entre-app-e-extensao).

---

## 6. Fluxo de boas-vindas

O onboarding é apresentado por `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) e controlado pela flag `@AppStorage("hasSeenLavaOnboarding")` declarada em `RootView` (`RootView.swift:32`). O fluxo é uma sequência de `OnboardingPage`s (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

A configuração inicial distribuída vem de `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` habilita apenas as fontes recomendadas mais permissivas (Block List Project, Phishing + Scam), seleciona **DNS do dispositivo** como resolvedor — `DNSResolverPreset.device` (id `device-dns`), o próprio DNS da rede; presets criptografados como o Google DoH são opcionais e não são promovidos a padrão — habilita o fallback de DNS do dispositivo e mantém o registro local ativado — com `protectionEnabled: false`, de modo que a proteção só é ligada quando o usuário escolhe. `OnboardingDefaultsSummary` formata essas escolhas para exibição ("Continuar sem conta" é o padrão de conta).

Definir `hasSeenLavaOnboarding = true` ao final é o que ativa `hasCompletedOnboarding`, que por sua vez arma o caminho de reconciliação de lançamento descrito em [§3](#3-ciclo-de-vida-e-controle-da-vpn). Até então, o caminho de neutralização durante o onboarding impede que qualquer túnel herdado em fail-closed bloqueie o tráfego.

---

## 7. Estado do app: `AppViewModel`

`AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) é o dono central do estado no lado do app. Além do ciclo de vida da VPN, ele publica as superfícies às quais a UI se vincula, incluindo:

- **Proteção e túnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil` e os textos voltados ao usuário `vpnMessage`/`vpnMessageIsError`.
- **Config e catálogo** — a `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt` e as contagens de regras compiladas (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnósticos** — `DiagnosticsStore` e `NetworkActivityLog` (tudo local; veja a promessa de privacidade abaixo).
- **Conta e backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled` e o estado de ofertas/entitlement do **Lava Security Plus**.
- **Personalização e apresentação** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress` e `usesLiveActivities`.

Ele delega a serialização do ciclo de vida a um `protectionActionOrchestrator` (para que uma restauração em segundo plano não se entrelace com um ligar feito pelo usuário), mantém o `tunnelManager` em cache e conduz todas as mudanças de snapshot/config/pausa para a extensão por meio dos auxiliares de mensagem de provedor descritos em [§2](#2-ipc-entre-app-e-extensao).

> **Enquadramento de privacidade.** A filtragem de DNS acontece localmente neste dispositivo. As superfícies de diagnóstico e de atividade de rede que o `AppViewModel` publica são armazenadas apenas localmente — a Lava nunca recebe as suas consultas de DNS do dia a dia, o seu histórico de navegação ou telemetria por domínio. Qualquer backup opcional de conta é **de conhecimento zero** (criptografado no dispositivo; a Lava só consegue armazenar texto cifrado), incluindo a recuperação baseada em passkey — sua chave é derivada via PRF no dispositivo, sem nenhum segredo guardado no servidor. Veja a [Visão geral do sistema](./system-overview.md) para a fronteira do servidor.

---

## Documentos relacionados

- [Visão geral do sistema](./system-overview.md) — o sistema inteiro em uma tela: o app, o Worker do catálogo e o Supabase, mais as fronteiras de confiança e a legenda de status usada ao longo dos documentos.
- [Filtragem de DNS e listas de bloqueio](./dns-filtering-and-blocklists.md) — os detalhes internos do túnel de pacotes, aqui referenciados apenas na fronteira de controle: o motor de filtragem compilado, os transportes criptografados do resolvedor (DoH / DoH3 / DoT / DoQ), o orçamento de regras de filtro, o catálogo de listas de bloqueio e o modelo de redistribuição apenas por URL de origem.
- [Contas e backup de conhecimento zero](./accounts-and-backup.md) — os provedores de login e o envelope de backup de conhecimento zero que o `AppViewModel` orquestra (incluindo o slot de recuperação por passkey, de conhecimento zero e derivado via PRF).
- [Backend e dados](./backend-and-data.md) — o Worker de catálogo `lavasec-api`, o Cloudflare R2 e o esquema/RLS do Supabase que ficam do outro lado da fronteira app↔servidor.
- [Design System](../design-system/overview.md) — o modelo de profundidade `LavaTier`, os sete estados do Soft Shield Guardian e as peles do escudo, além das convenções de texto/localização que o cliente renderiza.
- [Avisos de terceiros](../legal/third-party-notices.md) e a [decisão de conformidade GPL apenas por URL de origem](../legal/gpl-source-url-only-compliance-decision.md) — as restrições de distribuição por trás do pipeline de catálogo/filtro que o cliente consome.
