# GPL Blocklist Launch Decision

Last reviewed: 2026-06-21
Review type: Engineering self-review (not a formal legal opinion)
Engineering owner: Lava Security
Launch status: HaGeZi, OISD, and AdGuard GPL-3.0 sources ship as opt-in, off-by-default, source-url-only catalog options. 1Hosts (MPL-2.0) ships under the same source-url-only posture. The canonical manifest's `counsel_status` field is review bookkeeping, not a runtime gate.

This document records Lava Security's engineering decision. It is not legal
advice. The decision was self-reviewed against the upstream licenses and project
terms rather than by retained counsel; a one-off counsel check remains optional
before any copyleft source becomes default-enabled or Lava-hosted.

## Distribution Mode

Lava does not publish GPL blocklist bytes. Curated copyleft sources are
source-url-only options that the app fetches directly from upstream only when
the user selects them. The fresh-install default is Block List Basic
(Unlicense), and user-provided Pi-hole-compatible HTTPS URLs are fetched
directly by the user's device.

Because Lava never conveys the list bytes, the GPL-3.0 distribution obligations
attach to the upstream projects' own distribution, not to Lava. The app being
AGPL-3.0 (GPLv3-compatible) removes any separate app-license conflict if a list
were ever bundled in future.

## Required Engineering Controls

| Control | Required state |
| --- | --- |
| R2 blocklist objects | Not written for third-party blocklist content |
| Worker blocklist routes | No public `/v1/blocklists/.../domains.txt` artifact route |
| Active curated GPL catalog entries | HaGeZi, OISD, and AdGuard source-url-only metadata only |
| App defaults | Block List Basic (the source flagged `defaultEnabled: true`); Unlicense |
| Custom URLs | User-provided, paid, fetched on-device, not sent to Lava servers |
| On-device cache | Raw downloaded lists and compiled snapshots stay local to the device |
| IPA content | Third-party list content is not bundled in production app artifacts |
| Off-by-default | Copyleft sources ship `defaultEnabled: false`; the fresh-install set is `DefaultCatalog.recommendedDefaultSourceIDs`, currently Block List Basic. |

## Source Decisions

| Source family | License | State | Notes |
| --- | --- | --- | --- |
| HaGeZi DNS Blocklists | GPL-3.0 | Shipped: source-url-only, off by default | Show attribution/license/source URL; do not bundle, proxy, transform, or default-enable. |
| OISD | GPL-3.0 | Shipped: source-url-only, off by default | Show attribution/license/source URL; do not bundle, proxy, transform, or default-enable. |
| AdGuard DNS Filter | GPL-3.0 | Shipped: source-url-only, off by default | Same copyright posture as HaGeZi/OISD. Non-copyright note: "AdGuard" is a commercial trademark; use the name nominatively to identify the source only, with no implied endorsement. |
| 1Hosts | MPL-2.0 | Shipped: source-url-only, off by default | MPL-2.0 is weak / file-level copyleft; under source-url-only Lava neither modifies nor redistributes the list, so share-alike obligations are not triggered. |

## Upstream Terms Checked

- **HaGeZi** (`github.com/hagezi/dns-blocklists`): GPL-3.0. The README
  disclaimer states redistribution and adaptation are permitted within the
  applicable open-source license terms, with no additional permission gate and
  an as-is / no-warranty disclaimer. HaGeZi's separate public resolvers are
  described as non-commercial; that applies to their hosted DNS servers, not the
  blocklists, and Lava does not use them.
- **OISD** (`github.com/sjhgvr/oisd`): GPL-3.0, with no additional terms in the
  repo or on oisd.nl beyond a voluntary donation request.
- **AdGuard DNS Filter** (`github.com/AdguardTeam/AdGuardSDNSFilter`):
  GPL-3.0, with the same source-url-only analysis as HaGeZi/OISD.
- **1Hosts** (`github.com/badmojr/1Hosts`): MPL-2.0 (weak / file-level
  copyleft). Source-url-only does not trigger the share-alike obligation.

Net: for the bytes Lava references, the upstream license governs and no active
upstream imposes a permission requirement beyond it. Lava's source-url-only
posture means it is not redistributing those bytes in any case.

## Self-Review Findings

- Listing GPL source metadata and fetching upstream URLs on-device, without
  proxying bytes, means Lava does not convey GPL list copies.
- App Store path: Lava distributes only its own AGPL-3.0 app code plus
  permissively licensed dependencies; it ships no third-party GPL code and no
  GPL list data through Apple, so the "GPL on the App Store" conflict does not
  arise.
- Carve-out wording is recorded in
  [`open-source-list-data-terms-carveout.md`](open-source-list-data-terms-carveout.md).
- No active upstream requires explicit permission for source-url-only reference
  (see "Upstream Terms Checked").

## Residual / Deferred

- Default-enabling or Lava-hosting any copyleft source would change the analysis
  and should get a counsel check first.
- Patent freedom-to-operate and trademark items are tracked separately in the
  internal IP risk register.

## Launch Decision

Ship with Block List Basic as the fresh-install default and copyleft sources
(GPL-3.0, MPL-2.0) as opt-in, off-by-default, source-url-only choices.
Off-by-default is enforced by each source's `defaultEnabled: false`; the
fresh-install set is derived from `DefaultCatalog.recommendedDefaultSourceIDs`.
The `counsel_status` field in the canonical catalog manifest is a
review-tracking annotation, not a runtime control.

Default-enabling any copyleft source would require a deliberate catalog change to
its `defaultEnabled` flag and a counsel check first; Lava-hosting one would
likewise require counsel review.
