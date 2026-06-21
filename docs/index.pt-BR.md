---
hide_feedback: true
---

# Documentação do Lava Security

O Lava Security é um **aplicativo para iOS que coloca a privacidade em primeiro
lugar** e filtra o DNS localmente no próprio aparelho, por meio de um túnel de
pacotes NetworkExtension que roda no dispositivo — bloqueando domínios
conhecidamente arriscados ou indesejados sem direcionar sua navegação pelos
servidores do Lava.

!!! quote "O compromisso com a privacidade"
    A filtragem de DNS acontece localmente no seu aparelho; o Lava nunca recebe
    suas consultas de DNS do dia a dia, seu histórico de navegação ou dados de
    uso por domínio, e qualquer backup de conta opcional é criptografado de
    ponta a ponta, de modo que o Lava só consegue guardar texto cifrado.

Este site é o manual público de como o Lava funciona — sua arquitetura, seu
comportamento e as decisões por trás dele. Ele acompanha o
[cliente iOS](https://github.com/lavasecurity/lavasec-ios) de código aberto.

## Comece por aqui {#start-here}

<div class="grid cards" markdown>

-   :material-rocket-launch: **Produto**

    O que o Lava faz e para quem ele é.

    [Visão geral](product/overview.md) · [Catálogo de recursos](product/features.md) ·
    [Paridade entre plataformas](product/platform-parity.md)

-   :material-sitemap: **Arquitetura**

    Como todo o sistema se encaixa.

    [Visão geral do sistema](architecture/system-overview.md) ·
    [Cliente iOS](architecture/ios-client.md) ·
    [Filtragem de DNS e listas de bloqueio](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **Por dentro da privacidade**

    As partes que sustentam o compromisso com a privacidade.

    [Backend e dados](architecture/backend-and-data.md) ·
    [Contas e backup de conhecimento zero](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Decisões e conformidade**

    Por que foi construído desta forma.

    [Principais decisões (ADRs)](decisions/key-decisions.md) ·
    [Avisos de terceiros](legal/third-party-notices.md)

</div>

## Como ler isto {#how-to-read-this}

Toda afirmação aqui tem base no código-fonte. O status é indicado ao longo do texto:

| Status | Significado |
|---|---|
| **Implementado** | Presente no código já publicado |
| **Em andamento** | Sendo construído agora |
| **Planejado** | Uma direção, ainda não construída |
| **Descartado** | Decidiu-se não fazer — mantido para registro |

Quando a documentação e o código divergem, o código prevalece. Esta documentação
é um retrato do momento, gerado novamente a partir do código à medida que o
produto evolui.

O comportamento entre plataformas é acompanhado em
[Paridade entre plataformas](product/platform-parity.md): ela indica os
identificadores estáveis dos recursos, o status em cada plataforma e os testes
ou fixtures que devem manter o iOS e o Android alinhados.
