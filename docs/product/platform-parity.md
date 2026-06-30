# Platform Parity

Lava's platform parity system tracks which product promises are shared across
iOS, Android, and future clients. It is the public contract for feature
behavior: what must mean the same thing everywhere, what is intentionally
platform-native, and what is not promised yet.

The parity docs do not replace implementation plans or tests.

- `lavasec-doc` owns the product and behavior contract.
- Internal plans own delivery state, sequencing, private risks, and
  board sync.
- Platform repositories own code, fixtures, and tests that prove the behavior.

When docs and shipped code disagree, the code wins until the docs are refreshed.
When a plan and this page disagree, treat this page as the product contract and
the plan as the work queue.

## Status vocabulary

| Status | Meaning |
|---|---|
| **Shipped** | Implemented in production code for that platform. |
| **Partial** | Some behavior exists, but the public contract is not fully met. |
| **Planned** | Accepted as part of the platform contract, not yet implemented. |
| **Deferred** | Valid feature, but not required for the next platform milestone. |
| **Platform-native** | Same user promise, different OS-specific implementation. |
| **Not applicable** | No equivalent feature should exist on that platform. |
| **Dropped** | Previously considered or built, then intentionally removed. |

## Feature record format

Every parity-tracked feature needs a stable feature id. Use
`area.capability` names that survive UI copy changes, for example
`filtering.guardrail-precedence` or `dns.encrypted-transports`.

A complete feature record answers:

| Field | Purpose |
|---|---|
| `feature_id` | Stable id used in plans, PRs, tests, and docs. |
| Product promise | What users can rely on, in platform-neutral language. |
| Parity requirement | Whether Android must match iOS exactly, match by intent, or stay intentionally different. |
| Platform status | iOS, Android, and future client state. |
| Enforcement | Tests, fixtures, source files, or review checks that keep the behavior honest. |
| Platform notes | OS-specific differences that must be explicit, not rediscovered later. |

## Update workflow

1. Add or update the feature id when a change alters a product promise,
   privacy claim, tier boundary, or cross-platform behavior.
2. Link the same feature id from the implementation plan when work is needed.
3. Add or update platform tests or golden fixtures for behavior that must match.
4. When a platform ships the behavior, update the status here and refresh the
   relevant feature or architecture page.
5. Keep implementation-only, private, pricing, legal-risk, and operational
   internal details private; summarize only the public contract here.

## Current parity ledger

| Feature id | Product promise | iOS | Android | Parity requirement | Enforcement / source |
|---|---|---:|---:|---|---|
| `protection.local-dns-filtering` | Lava filters DNS locally on the device and does not proxy browsing through Lava servers. | Shipped | Planned | Match by intent; OS tunnel APIs differ. | iOS packet tunnel architecture; Android `VpnService` plan. |
| `protection.vpn-disclosure` | The app explains why the OS calls local DNS filtering a VPN before asking for VPN permission/configuration. | Shipped | Planned | Platform-native copy and permission flow. | Onboarding docs; Android Play disclosure plan. |
| `filtering.guardrail-precedence` | Always-on guardrails override user allowlists; paid status never bypasses guardrails. | Shipped | Planned | Exact behavior parity. | `CompactFilterSnapshotTests`; Android `FilterSnapshotTest` when ported. |
| `filtering.source-url-only-catalog` | Lava publishes catalog metadata and upstream source URLs, not third-party blocklist bytes. | Shipped | Planned | Exact privacy/IP model parity. | Catalog architecture; GPL/source-url-only legal docs. |
| `filtering.on-device-parsing` | Selected lists are fetched and parsed on-device; routine domain history is not uploaded to Lava. | Shipped | Planned | Exact privacy parity, native storage allowed. | `BlocklistParserTests`; Android parser parity tests when ported. |
| `filtering.rule-budget` | Filter limits are based on compiled rule count and device safety, not an arbitrary list count. | Shipped | Planned | Same user-facing model; platform memory caps may differ. | iOS filter budget tests; Android budget tests when device limits are known. |
| `dns.built-in-resolvers` | Users can choose built-in resolver presets without sending allowed lookups to Lava. | Shipped | Planned | Same resolver policy; preset set may launch in phases. | Resolver preset tests; Android resolver DTO tests when ported. |
| `dns.encrypted-transports` | Encrypted upstream DNS is available for allowed queries. | Shipped | Planned | Staged parity allowed; Android v1 may start with DoH before DoT/DoQ. | iOS transport tests; Android resolver tests and device QA. |
| `reports.local-only-diagnostics` | Reports and diagnostics stay local unless the user explicitly sends a support bundle. | Shipped | Planned | Exact privacy parity; UI can differ. | Bug report bundle tests; Android debug-report preview tests when built. |
| `account.optional-sign-in` | Protection works without an account; sign-in is optional. | Shipped | Deferred | Exact product promise before Android exposes account features. | Account auth docs; Android onboarding/settings review. |
| `backup.zero-knowledge-settings` | Optional settings backup stores ciphertext only; Lava cannot read plaintext backup contents. | Shipped | Deferred | Exact privacy parity before Android offers backup. | Zero-knowledge backup tests; Android crypto parity tests when built. |
| `plus.customization-boundary` | Free protection remains useful; Plus unlocks advanced customization and never changes guardrail safety. | Shipped | Planned | Same product boundary; store implementation is platform-native. | Subscription policy tests; Play Billing entitlement tests when built. |
| `design.calm-earned-depth` | Default UX is calm, with deeper technical or celebratory surfaces only when earned or requested. | Partial | Planned | Match by design intent through shared tokens/roles. | Design-system docs and portability foundation plan. |
| `platform.ambient-presence` | Protection status can appear outside the app when the OS supports a native ambient surface. | Platform-native | Planned | Intent parity, not surface parity. | iOS Live Activity docs; Android notification/Quick Settings decision pending. |

## Android readiness use

Before Android implementation starts, this page should be reviewed beside the
Android plan and the design-system portability plan. The minimum Android-ready
contract is:

- every privacy-bearing feature has a feature id;
- exact-parity behavior has an identified iOS test or fixture source;
- platform-native behavior has an explicit Android stance;
- deferred features are named so the Android MVP does not accidentally imply
  they ship.

That review belongs in the implementation plan or review notes, while this page
keeps the public, durable contract.
