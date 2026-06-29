---
hide_feedback: true
---

# Documentação do Lava Security

O Lava Security é um **aplicativo iOS que prioriza a privacidade** e que filtra DNS localmente no
dispositivo por meio de um túnel de pacotes NetworkExtension on-device — bloqueando domínios
conhecidos como arriscados e indesejados sem rotear sua navegação pelos servidores da Lava.

!!! quote "A promessa de privacidade"
    A filtragem de DNS acontece localmente no seu dispositivo; a Lava nunca recebe suas
    consultas DNS de rotina, seu histórico de navegação ou telemetria por domínio, e qualquer
    backup opcional da conta é criptografado de ponta a ponta, de modo que a Lava só pode
    armazenar texto cifrado.

Este site é o manual público de como o Lava funciona — sua arquitetura, seu
comportamento e as decisões por trás dele. Ele acompanha o
[cliente iOS](https://github.com/lavasecurity/lavasec-ios) de código aberto.

## Comece por aqui

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

-   :material-lock: **Detalhes internos de privacidade**

    As partes que sustentam a promessa de privacidade.

    [Backend e dados](architecture/backend-and-data.md) ·
    [Contas e backup de conhecimento zero](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Decisões e conformidade**

    Por que ele é construído desta forma.

    [Decisões-chave (ADRs)](decisions/key-decisions.md) ·
    [Avisos de terceiros](legal/third-party-notices.md)

</div>

## Como ler isto

Toda afirmação aqui é fundamentada no código-fonte. O status é marcado ao longo do texto:

| Status | Significado |
|---|---|
| **Implementado** | Presente no código já publicado |
| **Em andamento** | Sendo construído agora |
| **Planejado** | Uma direção, ainda não construída |
| **Descartado** | Decidido contra — mantido para registro |

Quando a documentação e o código divergem, o código prevalece. Esta documentação é um instantâneo,
regenerado a partir do código-fonte conforme o produto evolui.

O comportamento entre plataformas é acompanhado em [Paridade entre plataformas](product/platform-parity.md):
ela nomeia ids estáveis de recursos, o status por plataforma e os testes ou fixtures que
devem manter iOS e Android alinhados.
