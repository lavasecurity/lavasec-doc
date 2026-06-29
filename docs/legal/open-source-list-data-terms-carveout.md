# Open-Source List Data Terms Carve-Out

Last reviewed: 2026-06-21
Status: Engineering self-review (not a formal legal opinion)

## Carve-Out Language

Some blocklist, threat intelligence, or resolver metadata made available through Lava Security may be provided by third-party open-source projects. Those materials are licensed by their respective rights holders under their own license terms. Lava's Terms do not limit, replace, or impose additional restrictions on rights you receive directly under those third-party open-source licenses.

For curated blocklist sources, Lava provides source, license, attribution, warranty disclaimer, and notice metadata. The app fetches selected upstream source URLs directly and processes downloaded list data locally on the user's device. The full set of curated sources, their providers, and their licenses is published in the [Blocklist Catalog](blocklist-catalog.md).

## Aggregated Sources

Some curated sources are themselves aggregations that combine multiple upstream lists, each licensed by its own rights holder (for example, consolidated "hosts" distributions). For these sources, Lava links only to the aggregator's published source URL and never mirrors, re-hosts, or modifies the aggregated data. The aggregator's own license and attribution govern, in addition to the upstream licenses it incorporates. Such sources are not enabled by default; `counsel_status` in the canonical manifest tracks optional review separately from runtime behavior.

## Placement

- **Public docs:** this page plus [Third-Party Notices](third-party-notices.md) and the [Blocklist Catalog](blocklist-catalog.md).
- **App:** the Open-Source / Third-Party Notices screen renders per-source attribution for catalog sources. Adding this prose to the same screen is a recommended follow-up, not a precondition for shipping source-url-only sources.
- **App Store metadata / website short form:** use when optional GPL/MPL sources are mentioned in marketing copy: "Optional blocklist sources are published by third-party open-source projects under their own licenses; when enabled, your device fetches them directly from upstream. Lava does not redistribute that data or restrict your upstream license rights."
