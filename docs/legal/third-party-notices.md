# Third-Party Notices

Last reviewed: 2026-07-27
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
fresh-install set is Block List Basic plus the MIT-cleared, counsel-approved
StevenBlack Unified Hosts; changing that default for a GPL-3.0 or MPL-2.0
source would require a deliberate catalog change and a counsel check first.

Aggregated / meta-lists (for example, StevenBlack, OISD, and 1Hosts) compile
multiple upstreams under their published license; Lava links only to their
source URLs and never mirrors or modifies the bytes. StevenBlack sources can be
default-enabled only when their catalog row records `counsel_status: approved`.

## Bundled Software

Everything above concerns blocklist data the app **fetches at runtime and never
redistributes**, which is why linking to a source URL discharges those
obligations. Software compiled into the app is a different category: it ships
inside the app binary, so it is a binary redistribution, and the permissive
licenses involved require the copyright notice, the condition list, and the
warranty disclaimer to travel with it. A link is not reproduction.

Lava's packet-tunnel extension links a WireGuard-protocol engine built from
[BoringTun](https://github.com/cloudflare/boringtun) (BSD-3-Clause, Cloudflare,
Inc.) together with its Rust dependencies, which are licensed under MIT,
Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, and Unicode-3.0. It is compiled from
pinned sources into a static library at build time; **no code is downloaded at
runtime.**

The complete notices — every package, its version, its license text, and its
copyright holders — ship inside the app and are readable without a network
connection at **Settings → Legal → Third-Party Notices**. They are generated from
the engine's own dependency lock and from the archive that actually ships, so the
list cannot drift from what is linked.

WireGuard is a registered trademark of Jason A. Donenfeld; neither BoringTun nor
Lava Security is sponsored or endorsed by him. Cloudflare is a trademark or
registered trademark of Cloudflare, Inc. in the United States and other
jurisdictions.
