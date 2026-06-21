# Open-Source List Data Terms Carve-Out

Last reviewed: 2026-05-25
Status: Draft for counsel review

## Draft Language

Some blocklist, threat intelligence, or resolver metadata made available through Lava Security may be provided by third-party open-source projects. Those materials are licensed by their respective rights holders under their own license terms. Lava's Terms do not limit, replace, or impose additional restrictions on rights you receive directly under those third-party open-source licenses.

For curated blocklist sources, Lava provides source, license, attribution, warranty disclaimer, and notice metadata. The app fetches selected upstream source URLs directly and processes downloaded list data locally on the user's device. The full set of curated sources, their providers, and their licenses is published in the [Blocklist Catalog](blocklist-catalog.md).

## Aggregated Sources

Some curated sources are themselves aggregations that combine multiple upstream lists, each licensed by its own rights holder (for example, consolidated "hosts" distributions). For these sources, Lava links only to the aggregator's published source URL and never mirrors, re-hosts, or modifies the aggregated data. The aggregator's own license and attribution govern, in addition to the upstream licenses it incorporates. Such sources are not enabled by default and are marked for counsel review before they ship to production, so that any copyleft-licensed upstream they incorporate is cleared first.

## Counsel Review Questions

- Does this language preserve GPL downstream rights without implying Lava distributes third-party list copies?
- For aggregated sources (e.g. consolidated hosts files), is "link to the aggregator's source URL only, never mirror" sufficient, or do we need to enumerate each incorporated upstream's license?
- Should the carve-out appear in the app, public website, App Store metadata, or all three?
- Should Lava include a specific no-warranty statement for third-party list data in the main Terms?
