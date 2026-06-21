---
hide_feedback: true
---

# Documentazione di Lava Security

Lava Security è un'**app iOS che mette al primo posto la privacy** e filtra il DNS
localmente sul dispositivo tramite un tunnel di pacchetti NetworkExtension che
funziona sul dispositivo stesso: blocca i domini noti come rischiosi o indesiderati
senza far passare la tua navigazione dai server di Lava.

!!! quote "La promessa sulla privacy"
    Il filtraggio DNS avviene localmente sul tuo dispositivo; Lava non riceve mai
    le tue normali richieste DNS, la cronologia di navigazione o dati per singolo
    dominio, e ogni eventuale backup dell'account è cifrato end-to-end, così Lava
    può conservare soltanto testo cifrato.

Questo sito è il manuale pubblico che spiega come funziona Lava: la sua
architettura, il suo comportamento e le scelte che ci stanno dietro. Segue il
[client iOS](https://github.com/lavasecurity/lavasec-ios) open source.

## Inizia da qui {#start-here}

<div class="grid cards" markdown>

-   :material-rocket-launch: **Prodotto**

    Che cosa fa Lava e a chi è rivolto.

    [Panoramica](product/overview.md) · [Catalogo delle funzioni](product/features.md) ·
    [Parità tra piattaforme](product/platform-parity.md)

-   :material-sitemap: **Architettura**

    Come si incastrano insieme tutte le parti del sistema.

    [Panoramica del sistema](architecture/system-overview.md) ·
    [Client iOS](architecture/ios-client.md) ·
    [Filtraggio DNS e liste di blocco](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **Dettagli sulla privacy**

    Le parti che mantengono la promessa sulla privacy.

    [Backend e dati](architecture/backend-and-data.md) ·
    [Account e backup a conoscenza zero](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Decisioni e conformità**

    Perché è fatto così.

    [Decisioni chiave (ADR)](decisions/key-decisions.md) ·
    [Avvisi sui componenti di terze parti](legal/third-party-notices.md)

</div>

## Come leggere questa documentazione {#how-to-read-this}

Ogni affermazione qui presente è basata sul codice sorgente. Lo stato è indicato
ovunque:

| Stato | Significato |
|---|---|
| **Implementato** | Presente nel codice rilasciato |
| **In corso** | In fase di sviluppo ora |
| **Pianificato** | Una direzione, non ancora realizzata |
| **Scartato** | Deciso di non procedere, conservato per memoria |

Quando la documentazione e il codice non coincidono, vince il codice. Questa
documentazione è un'istantanea, rigenerata dal codice man mano che il prodotto
evolve.

Il comportamento multipiattaforma è descritto in [Parità tra piattaforme](product/platform-parity.md):
indica gli identificatori stabili delle funzioni, lo stato per ciascuna
piattaforma e i test o le fixture che dovrebbero mantenere allineati iOS e Android.
