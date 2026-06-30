---
hide_feedback: true
---

# Documentazione di Lava Security

Lava Security è una **app iOS privacy-first** che filtra il
DNS localmente sul dispositivo attraverso un packet tunnel NetworkExtension
on-device, bloccando i domini noti rischiosi e indesiderati senza instradare la
tua navigazione attraverso i server di Lava.

!!! quote "La promessa sulla privacy"
    Il filtraggio DNS avviene localmente sul tuo dispositivo; Lava non riceve mai
    le tue query DNS abituali, la cronologia di navigazione o la telemetria per
    singolo dominio, e qualsiasi backup opzionale dell'account è cifrato
    end-to-end, così che Lava possa archiviare solo testo cifrato.

Questo sito è il manuale pubblico di come funziona Lava: la sua architettura, il
suo comportamento e le decisioni che vi stanno dietro. Segue il
[client iOS](https://github.com/lavasecurity/lavasec-ios) open-source.

## Inizia qui

<div class="grid cards" markdown>

-   :material-rocket-launch: **Prodotto**

    Cosa fa Lava e a chi è rivolto.

    [Panoramica](product/overview.md) · [Catalogo delle funzionalità](product/features.md) ·
    [Parità tra piattaforme](product/platform-parity.md)

-   :material-sitemap: **Architettura**

    Come l'intero sistema si compone.

    [Panoramica del sistema](architecture/system-overview.md) ·
    [Client iOS](architecture/ios-client.md) ·
    [Filtraggio DNS e blocklist](architecture/dns-filtering-and-blocklists.md)

-   :material-lock: **Interni della privacy**

    Le parti che reggono la promessa sulla privacy.

    [Backend e dati](architecture/backend-and-data.md) ·
    [Account e backup a conoscenza zero](architecture/accounts-and-backup.md)

-   :material-scale-balance: **Decisioni e conformità**

    Perché è costruito in questo modo.

    [Decisioni chiave (ADR)](decisions/key-decisions.md) ·
    [Avvisi di terze parti](legal/third-party-notices.md)

</div>

## Come leggere questo manuale

Ogni affermazione qui è fondata sul codice sorgente. Lo stato è indicato ovunque:

| Stato | Significato |
|---|---|
| **Implementato** | Presente nel codice rilasciato |
| **In corso** | In fase di sviluppo ora |
| **Pianificato** | Una direzione, non ancora costruita |
| **Abbandonato** | Deciso di non farlo — conservato agli atti |

Quando la documentazione e il codice non concordano, vince il codice. Questa
documentazione è un'istantanea, rigenerata dal codice sorgente man mano che il
prodotto evolve.

Il comportamento multipiattaforma è tracciato in
[Parità tra piattaforme](product/platform-parity.md): indica gli id stabili
delle funzionalità, lo stato per piattaforma e i test o le fixture che dovrebbero
mantenere iOS e Android allineati.
