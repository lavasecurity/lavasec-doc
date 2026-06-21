---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Arquitetura do cliente iOS

> Público: engenheiros de iOS que trabalham no `lavasec-ios`.

O Lava Security é um aplicativo de iOS com foco em privacidade que filtra o DNS localmente, no próprio aparelho, por meio de um túnel de pacotes da NetworkExtension que roda no dispositivo, bloqueando domínios reconhecidamente arriscados e indesejados sem encaminhar a sua navegação pelos servidores da Lava. Este documento descreve como o cliente iOS é estruturado: os targets, como o app conversa com sua extensão de túnel, o ciclo de vida da VPN, o modelo de estados do Guardian, a Live Activity e o widget, o fluxo de integração inicial (onboarding) e o dono do estado no lado do app (`AppViewModel`).

Para uma visão de todo o sistema (o app, o Worker do catálogo e o Supabase), consulte [Visão geral do sistema](./system-overview.md).

---

## 1. Targets e responsabilidades

O cliente é distribuído como três targets executáveis mais uma biblioteca de núcleo compartilhada. Os três targets entram no mesmo **App Group** (`group.com.lavasec`) e fazem link com `LavaSecCore`.

| Target | Bundle id | Responsabilidade |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | O app em SwiftUI. É dono da interface, possui o entitlement da NetworkExtension e controla o túnel via `NETunnelProviderManager`. O `AppViewModel` é a fonte da verdade do ciclo de vida da VPN. |
| **Túnel de pacotes** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | A subclasse de `NEPacketTunnelProvider` chamada `PacketTunnelProvider` (também conhecida como `LavaSecTunnel`). Analisa pacotes de DNS, extrai o domínio consultado, avalia-o contra o snapshot compilado mapeado em memória e encaminha as consultas permitidas para o resolvedor upstream. Limitada pelo teto de memória jetsam de ~50 MiB por processo. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Um `WidgetBundle` cujo único membro é o `LavaProtectionLiveActivityWidget` — a apresentação da Live Activity / Dynamic Island. |

O código compartilhado fica em dois lugares:

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — o núcleo independente de plataforma: o mecanismo de filtragem, os transportes de resolvedor, a matemática de snapshot/orçamento, os stores de proteção e o núcleo da `GuardianMascotAnimation`. Conforme `VPNLifecycleController.swift:3-6`, os tipos da NetworkExtension são mantidos intencionalmente fora deste módulo para que sua lógica de ciclo de vida continue testável com fakes; o target do app fornece as conformidades apoiadas na `NetworkExtension`.
- **`Shared/`** — código compilado em mais de um target (por exemplo, `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

As partes internas do túnel de pacotes (análise de DNS, o snapshot compilado, os transportes de resolvedor criptografados e o orçamento de regras de filtragem) são abordadas em profundidade em [Filtragem de DNS e listas de bloqueio](./dns-filtering-and-blocklists.md). Este documento foca a arquitetura do lado do app e a fronteira entre o app e a extensão.

---

## 2. IPC entre app e extensão {#2-app-extension-ipc}

O app e a extensão do túnel de pacotes são processos separados. Eles se coordenam por meio de três mecanismos, todos ancorados no App Group.

### Container do App Group

`group.com.lavasec` é o container compartilhado que permite ao app, ao túnel e ao widget ler e gravar o mesmo estado e configuração do `LavaSecCore`. O `LavaSecAppGroup` (`Shared/AppGroup.swift`) centraliza cada chave e nome de arquivo compartilhado para que os processos nunca divirjam nas constantes de string, incluindo:

- Os artefatos do snapshot compilado (`filter-snapshot.compact`, `filter-snapshot.json`), o `app-configuration.json` serializado, a saúde do túnel (`tunnel-health.json`), os diagnósticos e o registro de atividade de rede.
- As chaves de `UserDefaults` compartilhadas para a sessão de proteção e o estado de pausa. Elas espelham diretamente os stores do `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — para que o app, o túnel e os intents da Live Activity compartilhem um único layout de chaves, um único contador de revisão e um único esquema de dedução de duplicatas.
- O diretório de cache do catálogo e o arquivo de log de depuração no dispositivo.

A URL do container é resolvida via `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Mensagem de comando / provider (o caminho de controle)

O app comanda o túnel com **`sendProviderMessage`** para todos os comandos. O `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) obtém a `NETunnelProviderSession` ativa a partir do manager em cache e chama `session.sendProviderMessage(...)`. O payload é codificado pelo `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) em um pequeno envelope JSON que carrega um `kind` de mensagem e um `operationID` opcional (usado para rastreamento de latência ponta a ponta).

Os tipos de mensagem reconhecidos são constantes em `LavaSecAppGroup`:

| Constante de mensagem | Efeito no túnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Força a recarga do snapshot de filtragem compilado. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Relê apenas o estado de pausa compartilhado. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Recarrega a configuração; apenas uma mudança de *identidade de resolvedor* dispara uma reconexão visível. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Manutenção de diagnósticos/log. |

No lado do túnel, o `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica o envelope e faz um switch sobre o `kind`. Em particular, `reload-configuration` carrega a nova configuração para que campos não relacionados ao resolvedor (toggles de diagnóstico, status pago) tenham efeito, mas só reseta o runtime de DNS e reaplica as configurações de rede do túnel — uma reconexão visível — quando a identidade do resolvedor realmente muda (`PacketTunnelProvider.swift:768-792`). Uma mudança em uma flag de diagnóstico ou no status pago nunca derruba a conexão ativa.

Os helpers `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` do app (`AppViewModel.swift:7062`/`7070`) são wrappers finos que enviam essas mensagens.

### Por que mensagens de provider para o controle app→túnel

**`sendProviderMessage` é o único caminho de controle app→túnel — não há sinal Darwin app→túnel.** Um design anterior postava um sinal Darwin via `CFNotificationCenter` na pausa e o observava dentro da extensão, mas ele nunca disparava de forma confiável no processo da NetworkExtension e foi removido. O serviço de comando não posta mais `CFNotificationCenterPostNotification`, e o túnel não adiciona mais um `CFNotificationCenterAddObserver` — a ausência de ambos é afirmada por testes de introspecção de fonte (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` para o post do serviço de comando; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` para o observer do túnel) como proteção contra reintrodução. (As linhas `import Darwin` que permanecem no serviço de comando e no túnel são para primitivas de `flock`/socket, não para notificações.)

Um caminho Darwin *ainda* existe na outra direção. O túnel posta um cutucão de mudança de saúde para o app: o `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) posta `CFNotificationCenterPostNotification` no canal `com.lavasec.protection.tunnel-health-changed` (o nome do canal mora em `TunnelHealthSignal.swift`, não em `AppGroup.swift`), e o app o observa via `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), conectado no `AppViewModel` para chamar `handleTunnelHealthNudge()`. A presença desse cutucão de saúde túnel→app é afirmada por `LavaLiveActivitySourceTests.swift:1059-1075`.

Para o controle app→túnel, a pausa é entregue gravando o `ProtectionPauseStore` compartilhado e seguindo-a com a mensagem de provider `reload-protection-pause`, para que o túnel execute `refreshProtectionPauseStateOnly`. O `AppViewModel.swift:4995-4996` documenta a regra diretamente: o app "nunca depende do observer Darwin de snapshot também, sempre usando `sendProviderMessage`." Trate o par App Group (estado compartilhado) + `sendProviderMessage` (o sinal de despertar/controle) como o caminho de controle app→túnel.

### Serviço de comando da Live Activity

O `LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) é o ponto de entrada para as ações da Dynamic Island / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes`, `resume`, `reconnect`). Os `LiveActivityIntent`s em `LavaLiveActivityIntents.swift` rodam no processo do app (que possui o entitlement da NetworkExtension), então:

- **Pausar / retomar** fluem através de um lock de arquivo entre processos (`protection-command.lock`, `flock`) e dos `ProtectionPauseStore` / `ProtectionSessionStore` do `LavaSecCore`, que são donos da emissão de revisão e da dedução de comandos duplicados (o `commandID` carrega o id de operação do chamador, para que um comando reentregue não consiga emitir uma segunda revisão). O resultado agenda uma atualização da Live Activity protegida por revisão.
- **Reconectar** é tratado diretamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): ele chama `loadAllFromPreferences` e inicia o primeiro manager de túnel instalado via `startVPNTunnel()` (como `loadAllFromPreferences` já está limitado às configurações de NE deste app, esse primeiro manager é o da Lava — diferente de `VPNLifecycleController.matchingManagers()`, ele não faz uma verificação explícita de identidade). O Connect-On-Demand já está ativado, então isso apenas força uma conexão imediata; a reconciliação de status do app então retorna a Live Activity para `.on` assim que conectado.

---

## 3. Ciclo de vida e controle da VPN {#3-vpn-lifecycle-control}

O `AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) é a fonte da verdade do ciclo de vida da VPN no app. Ele orquestra o liga/desliga, mantém em cache o `NETunnelProviderManager` ativo e publica o status para o SwiftUI.

### Seleção de manager e matemática do ciclo de vida

A lógica reutilizável de ciclo de vida, livre de NetworkExtension, mora em `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). O app fornece as conformidades apoiadas em `NETunnelProviderManager` de `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; o controller cuida de:

- **Seleção e dedução** — `matchingManagers()` filtra para os managers de propriedade da Lava via `LavaTunnelConfigurationIdentity.matches(...)`, ordena por `selectionPriority` (ativos primeiro, depois pelo nome de exibição canônico), e `removeDuplicateManagers(keeping:)` converge para um único sobrevivente.
- **Esperas de conexão/parada** — `waitForConnect` / `waitForStop` fazem polling do status da conexão ativa com uma tolerância de `startGraceInterval`, porque logo após `startVPNTunnel` a conexão pode brevemente reportar um status não pendente antes de o iOS fazer a transição para `.connecting`.

### Ligar / desligar

`enableProtection(...)` (`AppViewModel.swift:5764`) é **cache-first**: quando existe um artefato preparado confirmado como reutilizável para a configuração atual, a VPN pode subir imediatamente a partir do cache enquanto uma sincronização de catálogo em andamento continua atualizando ao fundo, e `performCatalogSync` reconcilia o túnel em execução na conclusão. Ele só bloqueia na sincronização quando não há nada válido de onde partir (por exemplo, o usuário acabou de mudar o conjunto da lista de ativados, invalidando a identidade do artefato em cache).

`disableProtection(...)` (`AppViewModel.swift:5972`) desliga o Connect-On-Demand *antes* de parar o túnel, para que o iOS não o reconecte imediatamente. `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) instala uma `NEOnDemandRuleConnect` (correspondência de interface `.any`) e salva as preferências — salvar (não apenas definir) é necessário para que o iOS honre a mudança.

### Observação de status (e uma ressalva sobre calor)

O `AppViewModel` observa `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) e publica `vpnStatus`/`isVPNConfigurationInstalled`. Crucialmente, quando um manager já está em cache, ele lê a conexão ativa do manager em cache em vez de forçar uma atualização via `loadAllFromPreferences`: o próprio `loadAllFromPreferences` re-posta `NEVPNStatusDidChange`, e uma atualização forçada no observer produziu uma tempestade auto-sustentada — o comentário no código (`AppViewModel.swift:1046-1048`) registra os ~370 eventos/s medidos e a regressão de calor de 134% de CPU que isso causou. As propriedades publicadas só mudam em transições reais, então ticks ociosos param de invalidar o SwiftUI.

### Reconciliação fail-closed do on-demand

O Connect-On-Demand pode subir o túnel **a frio** na inicialização (ou depois que o iOS o derruba em uma mudança de rede) antes de o app ter enviado um snapshot. Um túnel a frio sem um snapshot persistido reutilizável carrega em **fail-closed** — ele bloqueia todo o tráfego — e nunca se recupera sozinho. O `AppViewModel` trata isso em dois caminhos de inicialização, ambos condicionados ao onboarding estar concluído (`hasCompletedOnboarding`, espelhando a flag `@AppStorage("hasSeenLavaOnboarding")`):

- **Após o onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) roda sempre que a proteção está ativa na inicialização: ele prepara o snapshot de partida, persiste o estado compartilhado e envia `reload-snapshot` para que o túnel recarregue suas regras reais e saia do fail-closed. O fail-closed continua sendo o padrão seguro; isso apenas o substitui prontamente. (Corrige filtros mostrados em vermelho / tráfego bloqueado após uma reinicialização do app enquanto o Connect-On-Demand mantém o túnel ativo.)
- **Durante o onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) roda *antes* de qualquer trabalho de rede quando o onboarding não está concluído. O iOS não remove de forma confiável um perfil de VPN ao excluir o app, então uma reinstalação pode herdar uma configuração órfã com on-demand habilitado que sobe um túnel a frio em fail-closed antes de o usuário ter escolhido qualquer lista de bloqueio. Esse caminho **remove** a configuração (`removeFromPreferences`) em vez de salvar uma modificação nela — `saveToPreferences` exibiria de novo o prompt de sistema "Add VPN Configurations" em um perfil que esta instalação não possui, disparando o diálogo na inicialização do app antes de a folha de onboarding renderizar. É um no-op em uma instalação limpa e quando a configuração herdada já está inerte.

---

## 4. Modelo de Guardian / estados

Há dois vocabulários de estado relacionados: uma *avaliação* de conectividade e um estado do *mascote* Guardian.

### Avaliação de conectividade

`ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) mapeia um `TunnelHealthSnapshot` para um `ProtectionConnectivityAssessment` com uma de **seis severidades** e **duas ações**:

- Severidades: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Ações primárias: `turnOff` ou `reconnect`.

Essa única avaliação comanda tanto a superfície do Guard no app quanto (mapeada adiante) o estado da Dynamic Island, então as duas nunca discordam.

**Piso de honestidade (v1.0).** Uma falha atual e não coberta na sonda de DNS (smoke-probe) nunca pode aparecer como `.healthy` — a avaliação mostra `.recovering` até que uma sonda realmente tenha sucesso, para que o tráfego carregado por fallback sobre um primário travado não seja mais pintado como "Protegido". A lógica de reconexão se baseia em `consecutiveDNSSmokeProbeFailureCount` e `lastPrimaryUpstreamSuccessAt` (apenas o primário) em vez dos contadores genéricos de upstream, e um resolvedor que permanece acessível mas continua **rejeitando** a sonda comprovadamente boa (hijack/captive/desatualizado) é escalado para nível de reinício via um `consecutiveRejectedSmokeResponseCount` com escopo na identidade do resolvedor (LAV-87), mesmo quando a sequência genérica fica sendo resetada em redes de roaming instáveis.

### Notificações de conectividade

`ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`) transforma a avaliação em no máximo uma notificação local pendente, com throttle (600s) e dedução. A v1.0 adiciona:

- Um tipo **`dnsSlow`** distinto ("O DNS da Lava está lento") — o DNS lento costumava reusar o tipo `reconnectNeeded`, então uma queda real não conseguia substituí-lo.
- **Escalonamento/substituição** — um problema estritamente mais urgente (somente `reconnectNeeded` supera os demais) pode substituir um banner de menor prioridade já em exibição, contornando tanto a proteção de "problema já pendente" quanto o throttle, para que um travamento depois de um fallback de DNS do dispositivo exiba o prompt acionável "Reconectar" em vez de deixar no ar um banner tranquilizador.
- Uma **migração de persistência** (`ProtectionConnectivityNotificationStore`, schema v2, conectado via `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) rebaixa um marcador legado `reconnect-needed` pendente para `dnsSlow`, para que o escalonamento funcione através da atualização.

### Retry de captura do DNS do dispositivo

Quando a configuração ativa depende do resolvedor do dispositivo (como primário ou como fallback), um handoff de rede / despertar pode deixar o túnel segurando uma captura vazia do resolvedor do sistema — um travamento silencioso. `DeviceDNSFallbackPolicy` comanda um **retry limitado** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1s, `deviceDNSCaptureMaxRetryAttempts` 5): o túnel relê os resolvedores do sistema a cada segundo por até cinco tentativas até que a captura seja não vazia, então a adota no lugar — recuperando-se automaticamente sem reiniciar o túnel (eventos `device-dns-capture-retry` / `-exhausted`). É um no-op para configurações puramente DoH/DoT/DoQ (`currentConfigurationDependsOnDeviceDNS()`).

### Estados do mascote Guardian

O mascote Soft Shield Guardian tem exatamente **sete** estados emocionais — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Cada estado declara seus `allowedNextStates` para que as transições sejam restritas (por exemplo, `grateful` só volta para `awake`; `GuardianMascotAnimation.swift:12-29`). Semântica:

- `retrying` = autocura tranquila.
- `concerned` = busca gentil por ajuda.
- `grateful` = sucesso comemorativo (usado nas superfícies de onboarding/ajustes, não no mapa de conectividade).

`GuardianMascotAnimation` é o núcleo de animação procedural em `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) é a renderização em SwiftUI e dá suporte às skins de customização selecionadas por `GuardianShieldStyle` (nomes de exibição Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, com o mapeamento de `displayName` nas linhas 18-35). Alguns valores brutos divergem de seus nomes de exibição (por exemplo, `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"` e `purpleObsidian` é renderizado como "Amethyst"), então persista o valor bruto, não o rótulo.

### Como os dois se conectam

O `LavaActivityAttributes.ProtectionState` da Live Activity (`Shared/LavaActivityAttributes.swift`) faz a ponte entre a avaliação e um estado de mascote via `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). O `AppViewModel` escolhe o estado de proteção para a Dynamic Island a partir da mesma `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): uma severidade `networkUnavailable` vira `.networkUnavailable`, `recovering` vira `.reconnecting`, uma ação primária `reconnect` vira `.needsReconnect` e, caso contrário, `.on`.

> Nota: o `LavaTier` (o enum de profundidade do design-system calmo → **Floor** / comemorativo → **Window** / técnico → **Workshop**) é entregue na camada do design-system (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), conectado a superfícies representativas — veja [o design system](../design-system/overview.md). Ele governa a profundidade do design-system, não o caminho do cliente de proteção/túnel descrito aqui.

---

## 5. Live Activity e widget

O target do widget renderiza apenas a Live Activity e a Dynamic Island. O `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) expõe um único `LavaProtectionLiveActivityWidget`, um `ActivityConfiguration(for: LavaActivityAttributes.self)` com:

- Uma visualização de tela de bloqueio, uma região central expandida da Dynamic Island e apresentações compacta/mínima que renderizam o `SoftShieldGuardian` mais um glifo de status. As visualizações compacta/de tela de bloqueio recalculam o estado de proteção *efetivo* em um `TimelineView` por segundo, para que a contagem regressiva de uma pausa permaneça ao vivo sem um push.

O `LavaActivityAttributes.ContentState` carrega `protectionState`, uma `resumeDate` (para contagens regressivas de pausa), `pauseRequiresAuthentication` e o `shieldStyle` escolhido. A decodificação é tolerante — um `shieldStyle` ausente recai para `.original` — para que payloads de Live Activity mais antigos continuem funcionando.

No lado do app, o `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) é dono da `Activity<LavaActivityAttributes>` ao vivo: ele observa mudanças de autorização do ActivityKit, só oferece Live Activities em idiomas de telefone/tablet, e `reconcile(...)` inicia/atualiza/encerra a activity para casar com o estado de proteção solicitado. O `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) é o único funil que recalcula o estado desejado e chama o controller. Os botões da Dynamic Island despacham `LiveActivityIntent`s, que chamam o `LavaProtectionCommandService` como descrito em [§2](#2-app-extension-ipc).

---

## 6. Fluxo de onboarding

O onboarding é apresentado por `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) e condicionado pela flag `@AppStorage("hasSeenLavaOnboarding")` declarada em `RootView` (`RootView.swift:32`). O fluxo é uma sequência de `OnboardingPage`s (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

A configuração inicial entregue vem de `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` habilita apenas as fontes recomendadas permissivas (Block List Project Phishing + Scam), seleciona **Device DNS** como resolvedor — `DNSResolverPreset.device` (id `device-dns`), o DNS da própria rede; presets criptografados como o Google DoH são opt-in e não são promovidos a padrão — habilita o fallback de DNS do dispositivo e mantém o registro local ligado — com `protectionEnabled: false`, de modo que a proteção só é ativada quando o usuário escolhe. `OnboardingDefaultsSummary` formata essas escolhas para exibição ("Continuar sem conta" é o padrão de conta).

Definir `hasSeenLavaOnboarding = true` no fim é o que vira `hasCompletedOnboarding`, que por sua vez arma o caminho de reconciliação de inicialização descrito em [§3](#3-vpn-lifecycle-control). Até lá, o caminho de neutralização durante o onboarding impede que qualquer túnel herdado em fail-closed bloqueie o tráfego.

---

## 7. Estado do app: `AppViewModel`

O `AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) é o dono central do estado no lado do app. Além do ciclo de vida da VPN, ele publica as superfícies às quais a interface se vincula, incluindo:

- **Proteção e túnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil` e as mensagens voltadas ao usuário `vpnMessage`/`vpnMessageIsError`.
- **Configuração e catálogo** — a `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt` e as contagens de regras compiladas (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnósticos** — `DiagnosticsStore` e `NetworkActivityLog` (tudo local; veja a promessa de privacidade abaixo).
- **Conta e backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled` e o estado de ofertas/entitlement do **Lava Security Plus**.
- **Customização e apresentação** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress` e `usesLiveActivities`.

Ele delega a serialização do ciclo de vida a um `protectionActionOrchestrator` (para que uma restauração em segundo plano não se intercale com um liga manual do usuário), mantém o `tunnelManager` em cache e comanda todas as mudanças de snapshot/configuração/pausa para a extensão via os helpers de mensagem de provider em [§2](#2-app-extension-ipc).

> **Enquadramento de privacidade.** A filtragem de DNS acontece localmente neste dispositivo. As superfícies de diagnósticos e atividade de rede que o `AppViewModel` publica são armazenadas apenas localmente — a Lava nunca recebe suas consultas de DNS rotineiras, seu histórico de navegação ou telemetria por domínio. Qualquer backup opcional de conta é **zero-knowledge** (criptografado no dispositivo; a Lava só pode armazenar texto cifrado), incluindo a recuperação baseada em passkey — sua chave é derivada por PRF no dispositivo, sem segredo guardado no servidor. Veja [Visão geral do sistema](./system-overview.md) para a fronteira do servidor.

---

## Documentos relacionados

- [Visão geral do sistema](./system-overview.md) — todo o sistema em uma tela: o app, o Worker do catálogo e o Supabase, além das fronteiras de confiança e da legenda de status usada por todo o documento.
- [Filtragem de DNS e listas de bloqueio](./dns-filtering-and-blocklists.md) — as partes internas do túnel de pacotes referenciadas aqui apenas na fronteira de controle: o mecanismo de filtragem compilado, os transportes de resolvedor criptografados (DoH / DoH3 / DoT / DoQ), o orçamento de regras de filtragem, o catálogo de listas de bloqueio e o modelo de redistribuição apenas por URL de origem.
- [Contas e backup zero-knowledge](./accounts-and-backup.md) — os provedores de login e o envelope de backup zero-knowledge que o `AppViewModel` orquestra (incluindo o slot de recuperação por passkey, zero-knowledge e derivado por PRF).
- [Backend e dados](./backend-and-data.md) — o Worker de catálogo `lavasec-api`, o Cloudflare R2 e o schema/RLS do Supabase que ficam do outro lado da fronteira app↔servidor.
- [Design System](../design-system/overview.md) — o modelo de profundidade `LavaTier`, os sete estados do Soft Shield Guardian e as skins de escudo, e as convenções de copy/localização que o cliente renderiza.
- [Avisos de terceiros](../legal/third-party-notices.md) e [Decisão de conformidade GPL apenas por URL de origem](../legal/gpl-source-url-only-compliance-decision.md) — as restrições de distribuição por trás do pipeline de catálogo/filtragem que o cliente consome.
