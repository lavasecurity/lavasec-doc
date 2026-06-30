---
last_reviewed: 2026-06-20
owner: engineering
source_repos: [lavasec-ios]
grounded_at: {lavasec-ios: "e1e4fe9"}
---

# Arquitetura do Cliente iOS

> Público-alvo: engenheiros de iOS que trabalham no `lavasec-ios`.

Lava Security é um aplicativo iOS focado em privacidade que filtra DNS localmente no dispositivo por meio de um túnel de pacotes NetworkExtension no próprio aparelho, bloqueando domínios reconhecidamente arriscados e indesejados sem rotear sua navegação pelos servidores da Lava. Este documento aborda como o cliente iOS é estruturado: os targets, a fronteira entre o app e o túnel, o ciclo de vida da VPN, o modelo de estado do Guardian, a Live Activity e o widget, o fluxo de onboarding e o detentor do estado do lado do app (`AppViewModel`).

Para o panorama do sistema completo (o app, o Worker de catálogo e o Supabase), consulte [Visão Geral do Sistema](./system-overview.md).

---

## 1. Targets e responsabilidades

O cliente é distribuído como três targets executáveis mais uma biblioteca de núcleo compartilhada. Todos os três targets participam do mesmo **App Group** (`group.com.lavasec`) e vinculam o `LavaSecCore`.

| Target | Bundle id | Responsabilidade |
|---|---|---|
| **App** (`LavaSecApp`) | `com.lavasec.app` | O app SwiftUI. Detém a UI, possui o entitlement do NetworkExtension e controla o túnel via `NETunnelProviderManager`. O `AppViewModel` é a fonte da verdade do ciclo de vida da VPN. |
| **Packet tunnel** (`LavaSecTunnel`) | `com.lavasec.app.tunnel` | A subclasse de `NEPacketTunnelProvider` chamada `PacketTunnelProvider` (também conhecida como `LavaSecTunnel`). Faz o parse de pacotes DNS, extrai o domínio consultado, avalia-o contra o snapshot compilado mapeado em memória e encaminha as consultas permitidas para o upstream. Limitado pelo teto de memória de jetsam de ~50 MiB por processo. |
| **Widget** (`LavaSecWidget`) | `com.lavasec.app.widget` | Um `WidgetBundle` cujo único membro é o `LavaProtectionLiveActivityWidget` — a apresentação da Live Activity / Dynamic Island. |

O código compartilhado fica em dois lugares:

- **`LavaSecCore`** (`Sources/LavaSecCore/`) — o núcleo independente de plataforma: o mecanismo de filtragem, os transportes de resolver, a matemática de snapshot/budget, os stores de proteção e o núcleo `GuardianMascotAnimation`. Conforme `VPNLifecycleController.swift:3-6`, os tipos do NetworkExtension são intencionalmente mantidos fora desse módulo para que sua lógica de ciclo de vida permaneça testável com fakes; o target do app fornece as conformidades apoiadas em `NetworkExtension`.
- **`Shared/`** — código compilado em mais de um target (por exemplo, `AppGroup.swift`, `LavaActivityAttributes.swift`, `LavaProtectionCommandService.swift`, `SoftShieldGuardian.swift`, `LavaLiveActivityIntents.swift`).

Os detalhes internos do packet tunnel (parse de DNS, o snapshot compilado, os transportes de resolver criptografados e o budget de regras de filtro) são cobertos em profundidade em [Filtragem de DNS e Blocklists](./dns-filtering-and-blocklists.md). Este documento foca na arquitetura do lado do app e na fronteira entre o app e a extensão.

---

## 2. IPC entre app ↔ extensão

O app e a extensão de packet tunnel são processos separados. Eles se coordenam por meio de três mecanismos, todos ancorados no App Group.

### Container do App Group

`group.com.lavasec` é o container compartilhado que permite ao app, ao túnel e ao widget ler e gravar o mesmo estado e configuração do `LavaSecCore`. O `LavaSecAppGroup` (`Shared/AppGroup.swift`) centraliza cada chave e nome de arquivo compartilhado para que os processos nunca divirjam em constantes de string, incluindo:

- Os artefatos do snapshot compilado (`filter-snapshot.compact`, `filter-snapshot.json`), o `app-configuration.json` serializado, a saúde do túnel (`tunnel-health.json`), o diagnóstico e o log de atividade de rede.
- Chaves de `UserDefaults` compartilhadas para a sessão de proteção e o estado de pausa. Essas chaves apontam diretamente para os stores do `LavaSecCore` (`AppGroup.swift:38-41`) — `ProtectionSessionStore.Keys`, `ProtectionPauseStore.Keys` — para que o app, o túnel e os intents da Live Activity compartilhem um único layout de chaves, um único contador de revisão e um único esquema de deduplicação.
- O diretório de cache do catálogo e o arquivo de log de depuração no dispositivo.

A URL do container é resolvida via `FileManager.default.containerURL(forSecurityApplicationGroupIdentifier:)`.

### Mensagem de comando / provider (o caminho de controle)

O app comanda o túnel com **`sendProviderMessage`** para todos os comandos. O `AppViewModel.sendTunnelMessage(_:)` (`AppViewModel.swift:7215`) obtém a `NETunnelProviderSession` ativa do manager em cache e chama `session.sendProviderMessage(...)`. O payload é codificado pelo `LavaSecProviderMessageCodec` (`AppGroup.swift:55-79`) em um pequeno envelope JSON que carrega um `kind` de mensagem e um `operationID` opcional (usado para rastreamento de latência ponta a ponta).

Os tipos de mensagem reconhecidos são constantes no `LavaSecAppGroup`:

| Constante de mensagem | Efeito no túnel |
|---|---|
| `reloadSnapshotMessage` (`"reload-snapshot"`) | Força o recarregamento do snapshot de filtro compilado. |
| `reloadProtectionPauseMessage` (`"reload-protection-pause"`) | Relê apenas o estado de pausa compartilhado. |
| `reloadConfigurationMessage` (`"reload-configuration"`) | Recarrega a configuração; apenas uma mudança de *identidade de resolver* dispara uma reconexão visível. |
| `clearDiagnosticsMessage`, `clearFilteringCountsMessage`, `clearNetworkActivityLogMessage`, `flushTunnelHealthMessage` | Manutenção de diagnósticos/log. |

No lado do túnel, o `PacketTunnelProvider.handleAppMessage(_:completionHandler:)` (`PacketTunnelProvider.swift:729`) decodifica o envelope e faz switch sobre `kind`. Notavelmente, `reload-configuration` carrega a nova configuração para que campos não relacionados ao resolver (toggles de diagnóstico, status pago) entrem em vigor, mas só reinicia o runtime de DNS e reaplica as configurações de rede do túnel — uma reconexão visível — quando a identidade do resolver realmente muda (`PacketTunnelProvider.swift:768-792`). Uma mudança de flag de diagnóstico ou de status pago nunca derruba a conexão ativa.

Os helpers `notifyTunnelSnapshotUpdated()` / `notifyTunnelProtectionPauseUpdated()` do app (`AppViewModel.swift:7062`/`7070`) são wrappers finos que enviam essas mensagens.

### Por que provider messages para o controle app→túnel

**`sendProviderMessage` é o único caminho de controle app→túnel — não existe um sinal Darwin app→túnel.** Um design anterior postava um sinal Darwin do `CFNotificationCenter` na pausa e o observava dentro da extensão, mas ele nunca disparou de forma confiável no processo do NetworkExtension e foi removido. O serviço de comando não posta mais `CFNotificationCenterPostNotification`, e o túnel não adiciona mais um `CFNotificationCenterAddObserver` — a ausência de ambos é verificada por testes de introspecção de fonte (`Tests/LavaSecCoreTests/LavaLiveActivitySourceTests.swift:574` para o post do serviço de comando; `Tests/LavaSecCoreTests/PacketTunnelDNSRuntimeSourceTests.swift:847` para o observer do túnel) para proteger contra reintrodução. (As linhas `import Darwin` que permanecem no serviço de comando e no túnel são para primitivas de `flock`/socket, não para notificações.)

Um caminho Darwin *ainda* existe na outra direção. O túnel posta um aviso de mudança de saúde ao app: `TunnelHealthSignal.DarwinProtectionSignalNotifier` (`Sources/LavaSecCore/TunnelHealthSignal.swift`) posta `CFNotificationCenterPostNotification` no canal `com.lavasec.protection.tunnel-health-changed` (o nome do canal fica em `TunnelHealthSignal.swift`, não em `AppGroup.swift`), e o app o observa via `DarwinNotificationObserver` (`LavaSecApp/DarwinNotificationObserver.swift`, `CFNotificationCenterAddObserver`), conectado no `AppViewModel` para chamar `handleTunnelHealthNudge()`. A presença desse aviso de saúde túnel→app é verificada por `LavaLiveActivitySourceTests.swift:1059-1075`.

Para o controle app→túnel, a pausa é entregue gravando o `ProtectionPauseStore` compartilhado e seguindo-a com a provider message `reload-protection-pause` para que o túnel execute `refreshProtectionPauseStateOnly`. O `AppViewModel.swift:4995-4996` documenta a regra diretamente: o app "nunca depende do observer Darwin de snapshot tampouco, sempre usando `sendProviderMessage`." Trate o par App Group (estado compartilhado) + `sendProviderMessage` (o sinal de wake/controle) como o caminho de controle app→túnel.

### Serviço de comando da Live Activity

O `LavaProtectionCommandService.perform(_:)` (`Shared/LavaProtectionCommandService.swift`) é o ponto de entrada para as ações da Dynamic Island / Live Activity (`LavaLiveActivityActionRequest`: `pause-5-minutes` / `pause-10-minutes` / `pause-15-minutes` / `pause-configured` (o único botão de Pausa da Live Activity, cuja duração é o valor configurado pelo usuário), `resume`, `reconnect`). Os `LiveActivityIntent`s em `LavaLiveActivityIntents.swift` rodam no processo do app (que detém o entitlement do NetworkExtension), então:

- **Pausa / retomada** fluem por um lock de arquivo entre processos (`protection-command.lock`, `flock`) e pelos `ProtectionPauseStore` / `ProtectionSessionStore` do `LavaSecCore`, que cuidam da geração de revisões e da deduplicação de comandos duplicados (o `commandID` carrega o id de operação do chamador para que um comando reentregue não possa gerar uma segunda revisão). O resultado agenda uma atualização da Live Activity protegida por revisão.
- **Reconexão** é tratada diretamente (`performReconnect`, `LavaProtectionCommandService.swift:112-135`): ela chama `loadAllFromPreferences` e inicia o primeiro manager de túnel instalado via `startVPNTunnel()` (como `loadAllFromPreferences` já está restrito às configurações NE deste app, esse primeiro manager é o da Lava — diferente de `VPNLifecycleController.matchingManagers()`, ela não faz uma correspondência explícita de identidade). O Connect-On-Demand já está habilitado, então isso apenas força uma conexão imediata; a reconciliação de status do app retorna a Live Activity para `.on` assim que conectada.

---

## 3. Ciclo de vida e controle da VPN

O `AppViewModel` (`@MainActor final class`, `AppViewModel.swift:723`) é a fonte da verdade do ciclo de vida da VPN no app. Ele orquestra ligar/desligar, mantém em cache o `NETunnelProviderManager` ativo e publica o status para o SwiftUI.

### Seleção de manager e matemática de ciclo de vida

A lógica de ciclo de vida reutilizável e livre de NetworkExtension fica em `VPNLifecycleController<Repository>` (`Sources/LavaSecCore/VPNLifecycleController.swift`). O app fornece conformidades apoiadas em `NETunnelProviderManager` de `VPNManagerControlling` / `VPNManagerRepositoryProtocol` / `VPNStatusChangeWaiting`; o controller trata:

- **Seleção e deduplicação** — `matchingManagers()` filtra para managers de propriedade da Lava via `LavaTunnelConfigurationIdentity.matches(...)`, ordena por `selectionPriority` (ativo primeiro, depois nome de exibição canônico), e `removeDuplicateManagers(keeping:)` converge para um único sobrevivente.
- **Esperas de conexão/parada** — `waitForConnect` / `waitForStop` fazem polling do status da conexão ativa com uma tolerância de `startGraceInterval`, porque logo após `startVPNTunnel` a conexão pode brevemente ler um status não-pending antes de o iOS transicioná-la para `.connecting`.

### Ligar / desligar

O `enableProtection(...)` (`AppViewModel.swift:5764`) é **cache-first**: quando existe um artefato preparado confirmado-reutilizável para a configuração atual, a VPN pode subir imediatamente a partir do cache enquanto uma sincronização de catálogo em andamento continua atualizando em segundo plano, e `performCatalogSync` reconcilia o túnel em execução na conclusão. Ele só bloqueia na sincronização quando não há nada válido para iniciar (por exemplo, o usuário acabou de alterar o conjunto da lista habilitada, invalidando a identidade do artefato em cache).

O `disableProtection(...)` (`AppViewModel.swift:5972`) desativa o Connect-On-Demand *antes* de parar o túnel para que o iOS não o reconecte imediatamente. O `setManagerOnDemand(_:on:)` (`AppViewModel.swift:6253`) instala uma `NEOnDemandRuleConnect` (correspondência de interface `.any`) e salva as preferências — salvar (não apenas definir) é necessário para que o iOS honre a mudança.

### Observação de status (e uma ressalva sobre aquecimento)

O `AppViewModel` observa `.NEVPNStatusDidChange` (`AppViewModel.swift:1034-1056`) e publica `vpnStatus`/`isVPNConfigurationInstalled`. Crucialmente, quando um manager já está em cache, ele lê a conexão ativa do manager em cache em vez de forçar uma atualização via `loadAllFromPreferences`: o próprio `loadAllFromPreferences` reposta `NEVPNStatusDidChange`, e uma atualização forçada no observer produzia uma tempestade auto-sustentável — o comentário no código-fonte (`AppViewModel.swift:1046-1048`) registra os ~370 eventos/s medidos e a regressão de aquecimento de CPU de 134% que ela provocou. As propriedades publicadas só mudam em transições reais, de modo que ticks ociosos param de invalidar o SwiftUI.

### Reconciliação on-demand fail-closed

O Connect-On-Demand pode subir o túnel **a frio** na inicialização (ou após o iOS derrubá-lo em uma mudança de rede) antes que o app tenha enviado um snapshot. Um túnel a frio sem snapshot persistido reutilizável carrega em **fail-closed** — ele bloqueia todo o tráfego — e nunca se recupera sozinho. O `AppViewModel` trata isso em dois caminhos de inicialização, ambos condicionados à conclusão do onboarding (`hasCompletedOnboarding`, espelhando a flag `@AppStorage("hasSeenLavaOnboarding")`):

- **Após o onboarding** — `reconcileTunnelSnapshotAfterLaunch()` (`AppViewModel.swift:7122`) roda sempre que a proteção está ativa na inicialização: ele prepara o snapshot de inicialização, persiste o estado compartilhado e envia `reload-snapshot` para que o túnel recarregue suas regras reais saindo do fail-closed. O fail-closed permanece o padrão seguro; isso apenas o substitui prontamente. (Corrige filtros exibidos em vermelho / tráfego bloqueado após uma reinicialização do app enquanto o Connect-On-Demand mantém o túnel no ar.)
- **No meio do onboarding** — `neutralizeInheritedProtectionDuringOnboarding()` (`AppViewModel.swift:7181`) roda *antes* de qualquer trabalho de rede quando o onboarding não está concluído. O iOS não remove de forma confiável um perfil de VPN ao deletar o app, então uma reinstalação pode herdar uma configuração órfã, com on-demand habilitado, que sobe um túnel a frio em fail-closed antes que o usuário tenha escolhido qualquer blocklist. Esse caminho **remove** a configuração (`removeFromPreferences`) em vez de salvar uma modificação nela — `saveToPreferences` reexibiria o prompt de sistema "Add VPN Configurations" em um perfil que esta instalação não possui, disparando o diálogo na inicialização do app antes de a folha de onboarding renderizar. É um no-op em uma instalação limpa e quando a configuração herdada já está inerte.

---

## 4. Modelo de Guardian / estado

Há dois vocabulários de estado relacionados: uma *avaliação* de conectividade e um estado do *mascote* Guardian.

### Avaliação de conectividade

O `ProtectionConnectivityPolicy.assessment(isConnected:health:now:)` (`Sources/LavaSecCore/ProtectionConnectivityPolicy.swift`) mapeia um `TunnelHealthSnapshot` para um `ProtectionConnectivityAssessment` com uma de **seis severidades** e **duas ações**:

- Severidades: `healthy`, `recovering`, `usingDeviceDNSFallback`, `dnsSlow`, `networkUnavailable`, `needsReconnect`.
- Ações primárias: `turnOff` ou `reconnect`.

Essa única avaliação comanda tanto a superfície do Guard no app quanto (mapeada adiante) o estado da Dynamic Island, de modo que as duas nunca discordam.

**Piso de honestidade (v1.0).** Uma falha de smoke-probe de DNS atual e não coberta nunca pode ser lida como `.healthy` — a avaliação exibe `.recovering` até que um probe realmente tenha sucesso, de modo que o tráfego carregado por fallback sobre um primário travado não seja mais pintado como "Protegido." A lógica de reconexão chaveia em `consecutiveDNSSmokeProbeFailureCount` e `lastPrimaryUpstreamSuccessAt` (apenas primário) em vez dos contadores genéricos de upstream, e um resolver que permanece alcançável mas continua **rejeitando** o probe conhecido-bom (hijack/captive/stale) é escalado para merecedor de reinício via um `consecutiveRejectedSmokeResponseCount` com escopo de identidade-de-resolver (LAV-87), mesmo quando a sequência genérica continua sendo zerada em redes de roaming instáveis.

### Notificações de conectividade

O `ProtectionConnectivityNotificationPolicy` (`Sources/LavaSecCore/ProtectionConnectivityNotificationPolicy.swift`) transforma a avaliação em no máximo uma notificação local pendente, com throttle (600s) e deduplicada. A v1.0 adiciona:

- Um tipo **`dnsSlow`** distinto ("Lava DNS is slow") — DNS lento costumava reutilizar o tipo `reconnectNeeded`, de modo que uma interrupção real não conseguia substituí-lo.
- **Escalonamento/substituição** — um problema estritamente mais urgente (apenas `reconnectNeeded` supera o resto) pode substituir um banner pendente de menor classificação, ignorando tanto a guarda "problema já pendente" quanto o throttle, de modo que um travamento após um fallback para Device-DNS exiba o prompt acionável "Reconnect" em vez de deixar um banner tranquilizador no ar.
- Uma **migração de persistência** (`ProtectionConnectivityNotificationStore`, esquema v2, conectada via `LavaSecAppGroup.migrateProtectionNotificationStateIfNeeded`) rebaixa um marcador legado pendente de `reconnect-needed` para `dnsSlow` para que o escalonamento funcione ao longo da atualização.

### Retentativa de captura de Device-DNS

Quando a configuração ativa depende do resolver do dispositivo (como primário ou como fallback), um handoff/wake de rede pode deixar o túnel segurando uma captura vazia de resolver de sistema — um travamento silencioso. O `DeviceDNSFallbackPolicy` comanda uma **retentativa limitada** (`shouldRetryDeviceDNSCapture`, `deviceDNSCaptureRetryInterval` 1s, `deviceDNSCaptureMaxRetryAttempts` 5): o túnel relê os resolvers de sistema a cada segundo por até cinco tentativas até que a captura seja não-vazia, então a adota no lugar — auto-recuperando sem reiniciar o túnel (eventos `device-dns-capture-retry` / `-exhausted`). É um no-op para configs puras de DoH/DoT/DoQ (`currentConfigurationDependsOnDeviceDNS()`).

### Estados do mascote Guardian

O mascote Soft Shield Guardian tem exatamente **sete** estados emocionais — `GuardianMascotState` (`GuardianMascotAnimation.swift:3`): `sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`. Cada estado declara seus `allowedNextStates` para que as transições sejam restritas (por exemplo, `grateful` só retorna a `awake`; `GuardianMascotAnimation.swift:12-29`). Semântica:

- `retrying` = auto-cura tranquila.
- `concerned` = busca gentil por ajuda.
- `grateful` = sucesso comemorativo (usado em superfícies de onboarding/configurações, não no mapa de conectividade).

`GuardianMascotAnimation` é o núcleo de animação procedural no `LavaSecCore`; `SoftShieldGuardian` (`Shared/SoftShieldGuardian.swift`) é a renderização SwiftUI e suporta as skins de personalização selecionadas por `GuardianShieldStyle` (nomes de exibição Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème — `LavaActivityAttributes.swift:5-56`, com o mapeamento de `displayName` nas linhas 18-35). Alguns valores brutos divergem de seus nomes de exibição (por exemplo, `fireOpal = "emberObsidian"`, `cherryQuartz = "strawberryObsidian"`, e `purpleObsidian` renderiza como "Amethyst"), então persista o valor bruto, não o rótulo.

### Como os dois se conectam

A `LavaActivityAttributes.ProtectionState` da Live Activity (`Shared/LavaActivityAttributes.swift`) faz a ponte da avaliação para um estado de mascote via `guardianState`: `on → awake`, `paused → paused`, `reconnecting`/`networkUnavailable → retrying`, `needsReconnect → concerned` (`LavaActivityAttributes.swift:95-105`). O `AppViewModel` escolhe o estado de proteção para a Dynamic Island a partir do mesmo `protectionConnectivityAssessment` (`AppViewModel.swift:3131-3147`): uma severidade `networkUnavailable` torna-se `.networkUnavailable`, `recovering` torna-se `.reconnecting`, uma ação primária `reconnect` torna-se `.needsReconnect`, e caso contrário `.on`.

> Nota: `LavaTier` (o enum de profundidade do design-system tranquilo → **Floor** / comemorativo → **Window** / técnico → **Workshop**) é distribuído na camada de design-system (`LavaSecApp/LavaDesignSystem/LavaTokens.swift`), conectado a superfícies representativas — veja [o design system](../design-system/overview.md). Ele governa a profundidade do design-system, não o caminho do cliente de proteção/túnel descrito aqui.

---

## 5. Live Activity e widget

O target do widget renderiza apenas a Live Activity e a Dynamic Island. O `LavaSecWidgetBundle` (`LavaSecWidget/LavaSecWidget.swift`) expõe um único `LavaProtectionLiveActivityWidget`, uma `ActivityConfiguration(for: LavaActivityAttributes.self)` com:

- Uma view de tela de bloqueio, uma região central expandida da Dynamic Island e apresentações compact/minimal que renderizam `SoftShieldGuardian` mais um glifo de status. As views compact/lock recomputam o estado de proteção *efetivo* em uma `TimelineView` por segundo para que uma contagem regressiva de pausa permaneça ao vivo sem um push.

`LavaActivityAttributes.ContentState` carrega `protectionState`, uma `resumeDate` (para contagens regressivas de pausa), `pauseRequiresAuthentication` e a `shieldStyle` escolhida. A decodificação é tolerante — um `shieldStyle` ausente recai para `.original` — de modo que payloads de Live Activity mais antigos continuam funcionando.

No lado do app, o `LavaLiveActivityController` (`LavaSecApp/LavaLiveActivityController.swift`) detém a `Activity<LavaActivityAttributes>` ativa: ele observa mudanças de autorização do ActivityKit, só oferece Live Activities em idiomas de phone/pad, e `reconcile(...)` inicia/atualiza/encerra a activity para corresponder ao estado de proteção solicitado. O `AppViewModel.reconcileLiveActivity()` (`AppViewModel.swift:3069`) é o único funil que recomputa o estado desejado e chama o controller. Os botões da Dynamic Island despacham `LiveActivityIntent`s, que chamam `LavaProtectionCommandService` conforme descrito em [§2](#2-ipc-entre-app--extensão).

---

## 6. Fluxo de onboarding

O onboarding é apresentado por `LavaOnboardingView` (`LavaSecApp/OnboardingFlowView.swift`) e condicionado pela flag `@AppStorage("hasSeenLavaOnboarding")` declarada em `RootView` (`RootView.swift:32`). O fluxo é uma sequência de `OnboardingPage`s (`OnboardingFlowView.swift:403-409`): `lava` → `guardIntro` → `features` → `vpn` → `notifications` → `done`.

A configuração inicial distribuída vem de `OnboardingDefaults` (`Sources/LavaSecCore/OnboardingDefaults.swift`). `AppConfiguration.lavaRecommendedDefaults` habilita apenas a fonte recomendada permissiva (Block List Basic), seleciona **Device DNS** como o resolver — `DNSResolverPreset.device` (id `device-dns`), o próprio DNS da rede; presets criptografados como Google DoH são opt-in e não são promovidos ao padrão — habilita o fallback de device-DNS e mantém o log local ligado — com `protectionEnabled: false`, de modo que a proteção só é ativada quando o usuário a escolhe. O `OnboardingDefaultsSummary` formata essas escolhas para exibição ("Continue without account" é o padrão de conta).

Definir `hasSeenLavaOnboarding = true` ao final é o que aciona `hasCompletedOnboarding`, que por sua vez arma o caminho de reconciliação de inicialização descrito em [§3](#3-ciclo-de-vida-e-controle-da-vpn). Até lá, o caminho de neutralização no meio do onboarding impede que qualquer túnel fail-closed herdado bloqueie o tráfego.

---

## 7. Estado do app: `AppViewModel`

O `AppViewModel` (`@MainActor final class AppViewModel: ObservableObject`, `AppViewModel.swift:723`) é o detentor central do estado do lado do app. Além do ciclo de vida da VPN, ele publica as superfícies às quais a UI se vincula, incluindo:

- **Proteção e túnel** — `vpnStatus`, `isVPNConfigurationInstalled`, `isConfiguringVPN`, `tunnelHealth` (`TunnelHealthSnapshot`), `temporaryProtectionPauseUntil`, e `vpnMessage`/`vpnMessageIsError` voltados ao usuário.
- **Config e catálogo** — a `AppConfiguration`, `isSyncingCatalog`, `catalogVersion`/`catalogGeneratedAt`, e contagens de regras compiladas (`compiledRuleCount`, `protectedRuleCount`, `compiledBlocklistRuleCount`).
- **Diagnósticos** — `DiagnosticsStore` e `NetworkActivityLog` (tudo local; veja a promessa de privacidade abaixo).
- **Conta e backup** — `accountAuthState`, `encryptedBackupState`, `isAutomaticBackupEnabled`, e o estado de ofertas/entitlement do **Lava Security Plus**.
- **Personalização e apresentação** — `appearancePreference`, `lavaGuardLook` (`GuardianShieldStyle`), `lavaGuardProgress`, e `usesLiveActivities`.

Ele delega a serialização do ciclo de vida a um `protectionActionOrchestrator` (para que uma restauração em segundo plano não se intercale com um ligar acionado pelo usuário), mantém o `tunnelManager` em cache e comanda todas as mudanças de snapshot/config/pausa à extensão via os helpers de provider-message em [§2](#2-ipc-entre-app--extensão).

> **Enquadramento de privacidade.** A filtragem de DNS acontece localmente neste dispositivo. As superfícies de diagnóstico e atividade de rede que o `AppViewModel` publica são armazenadas apenas localmente — a Lava nunca recebe suas consultas DNS de rotina, histórico de navegação ou telemetria por domínio. Qualquer backup de conta opcional é **zero-knowledge** (criptografado no dispositivo; a Lava só pode armazenar texto cifrado), incluindo a recuperação baseada em passkey — sua chave é derivada por PRF no dispositivo, sem segredo mantido no servidor. Veja [Visão Geral do Sistema](./system-overview.md) para a fronteira do servidor.

---

## Documentos relacionados

- [Visão Geral do Sistema](./system-overview.md) — todo o sistema em uma tela: o app, o Worker de catálogo e o Supabase, mais as fronteiras de confiança e a legenda de status usada ao longo do documento.
- [Filtragem de DNS e Blocklists](./dns-filtering-and-blocklists.md) — os detalhes internos do packet tunnel referenciados aqui apenas na fronteira de controle: o mecanismo de filtragem compilado, os transportes de resolver criptografados (DoH / DoH3 / DoT / DoQ), o budget de regras de filtro, o catálogo de blocklists e o modelo de redistribuição source-url-only.
- [Contas e Backup Zero-Knowledge](./accounts-and-backup.md) — os provedores de login e o envelope de backup zero-knowledge que o `AppViewModel` orquestra (incluindo o slot de recuperação por passkey zero-knowledge, derivado por PRF).
- [Backend e Dados](./backend-and-data.md) — o Worker de catálogo `lavasec-api`, o Cloudflare R2 e o esquema/RLS do Supabase que ficam do outro lado da fronteira app↔servidor.
- [Design System](../design-system/overview.md) — o modelo de profundidade `LavaTier`, os sete estados do Soft Shield Guardian e as skins de escudo, e as convenções de copy/localização que o cliente renderiza.
- [Avisos de Terceiros](../legal/third-party-notices.md) e [decisão de conformidade GPL source-url-only](../legal/gpl-source-url-only-compliance-decision.md) — as restrições de distribuição por trás do pipeline de catálogo/filtro que o cliente consome.
