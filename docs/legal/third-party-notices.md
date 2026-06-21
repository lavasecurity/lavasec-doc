# Third-Party Notices

Last reviewed: 2026-06-21
Status: Engineering self-review (not a formal legal opinion)

Lava publishes catalog metadata for launch sources and the app fetches selected
source URLs directly on the user's device. Lava does not publish third-party
blocklist bytes from Lava-controlled R2, Worker, CDN, or app bundle locations.
The full active source list, including provider, license, and upstream URL for
each source, is published in the [Blocklist Catalog](blocklist-catalog.md).

Lava's terms do not restrict users' rights under upstream licenses; see
[`open-source-list-data-terms-carveout.md`](open-source-list-data-terms-carveout.md).

## Upstream License Terms

- **The Block List Project** — Unlicense (public-domain dedication); no notice
  requirement beyond attribution in the catalog.
- **Phishing.Database** — MIT; Lava records the license and links to the
  upstream source URL, which carries the MIT copyright/permission notice, and
  does not mirror or modify the bytes.
- **StevenBlack hosts variants** — MIT; Lava links only to the published hosts
  files and does not mirror or modify the bytes.
- **HaGeZi**, **OISD**, and **AdGuard DNS Filter** — GPL-3.0. Lava references
  them source-url-only, off by default, and does not redistribute the list bytes.
- **1Hosts** — MPL-2.0. Under source-url-only Lava neither modifies nor
  redistributes the list, so share-alike obligations are not triggered.

## Copyleft Source Posture

Copyleft sources in the catalog are source-url-only and off by default. The
fresh-install set is Block List Basic, the only source currently flagged
`defaultEnabled: true`; changing that default for a GPL-3.0 or MPL-2.0 source
would require a deliberate catalog change and a counsel check first.

The `counsel_status` field in the canonical manifest is a review-tracking
annotation, not a runtime gate. Aggregated / meta-lists (for example,
StevenBlack, OISD, and 1Hosts) compile multiple upstreams under their published
license; Lava links only to their source URLs and never mirrors or modifies the
bytes.
