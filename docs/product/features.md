# Feature Catalog

This is the catalog of features that ship today in Lava Security, grouped by area, written for product and engineering. Lava Security is a privacy-first iOS app that filters DNS locally on the device through an on-device NetworkExtension packet tunnel, blocking known risky and unwanted domains without routing your browsing through Lava's servers.

The canonical privacy promise governs everything below: DNS filtering happens locally on your device; Lava never receives your routine DNS queries, browsing history, or per-domain telemetry, and any optional account backup is end-to-end encrypted so Lava can only ever store ciphertext.

**Scope.** This page documents the **current, implemented** feature set only. A handful of entries are tagged **(In progress)** or **(Dropped)** where that status is load-bearing for understanding what does or doesn't ship. Anything not yet built — Android, URL-level protection, a centralized upsell page, the `LavaTier` design-depth model, scheduled catalog sync with threat-intel validation — lives in the private roadmap. Cross-platform product contracts and Android/iOS status live in [Platform Parity](platform-parity.md).

**Status legend.** **Implemented** = production call sites exist and ship. **(In progress)** = code present but not fully wired / pending QA. **(Dropped)** = built-then-reverted or cancelled. Default unmarked entries describe shipped behavior. Where this page marks Free vs Plus, **Plus** means Lava Security Plus, the optional paid customization tier; **Free** is the default tier that everyone gets without an account.

---

## Protection & VPN

The protection engine is a local DNS filter, not a traffic-routing VPN — allowed lookups go to your chosen upstream resolver, and your browsing is never proxied through Lava.

| Feature | Tier | Notes |
|---|---|---|
| **Local DNS-filtering packet tunnel** | Free | The `PacketTunnelProvider` (`LavaSecTunnel`) parses DNS packets, extracts the queried domain, evaluates it against a memory-mapped compiled snapshot, and forwards allowed queries upstream. Bounded by the ~50 MiB per-process jetsam memory ceiling. (`apps/ios/LavaSecTunnel/PacketTunnelProvider.swift`) |
| **One-tap turn-on with calm status** | Free | The Guard surface turns protection on/off and reports a calm status (`Protected` / "Filtering happens locally on this phone"). `AppViewModel` is the VPN lifecycle source of truth — it orchestrates turn-on, pause/resume, on-demand, and snapshot reload. `VPNLifecycleController` is the underlying NETunnelProviderManager repository: it loads/creates/removes the Lava VPN manager, cleans up duplicate managers, saves-and-reloads the manager config, and waits on connect/stop status transitions. |
| **Temporary pause + auto-resume** | Free | Pause protection for 5, 10, or 15 minutes; it resumes automatically when the timer expires (`AppViewModel.pauseProtectionTemporarily(for:)` / `resumeProtectionNow()`). |
| **Connectivity-aware status & self-healing** | Free | `ProtectionConnectivityPolicy` maps six connectivity severities to two user actions and plain-language titles (`Network Lost`, `Reconnect Needed`, `DNS Slow`, `Reconnecting`). The tunnel coalesces in-flight queries, caches DNS responses, and reuses upstream sockets for speed and lower heat. |
| **Soft Shield Guardian mascot** | Free | A procedurally drawn shield with a face that animates across **7** Guardian states (`sleeping`, `waking`, `awake`, `paused`, `retrying`, `concerned`, `grateful`) to communicate protection status without fear-driven language. `retrying` = calm self-healing; `concerned` = gentle help-seeking; `grateful` = celebratory success on onboarding/settings moments. (`GuardianMascotAnimation`, `SoftShieldGuardian`) |
| **Guardrails always enforced** | Free | The compiled snapshot's `FilterDecision` precedence is guardrail-block > local allow > blocklist-block > default-allow. Always-on, backend-curated `guardrails[]` rules cannot be overridden by the user allowlist, and the tunnel ignores `isPaid` — Plus never bypasses guardrails. (`CompactFilterSnapshot`) |

See [../architecture/ios-client.md](../architecture/ios-client.md) for the app / extension / widget target layout and the App Group (`group.com.lavasec`) that ties them together.

---

## Blocklists & filtering

Lava uses a **source-url-only** distribution model: it publishes only catalog metadata plus each list's upstream `source_url`, and the app fetches and parses every list directly on-device. Lava never hosts, mirrors, or serves third-party blocklist bytes. The earlier R2 raw-mirror approach was **(Dropped)** for GPL/IP compliance.

| Feature | Tier | Notes |
|---|---|---|
| **Curated blocklist catalog** | Free | An R2-hosted JSON catalog (`schema_version` 2), served via `GET /v1/catalog`, lists available `sources[]` and always-on `guardrails[]` with metadata, `source_url`, hashes, and license. Curated sources include Block List Project (basic/malware/phishing/scam/ransomware, Unlicense), Phishing.Database Active (MIT), HaGeZi tiers (GPL-3.0), and OISD Small (GPL-3.0). (`BlocklistModels` / `DefaultCatalog`) |
| **Recommended default config** | Free | The wired default (`lavaRecommendedDefaults`) enables **Block List Project Phishing + Scam**, with Google plain DNS as the resolver. (Block List Basic exists in the catalog but is not part of the shipped default.) GPL sources (HaGeZi / OISD) are opt-in and off by default pending counsel; AdGuard stays inactive. (`OnboardingDefaults`) |
| **On-device parsing & dedup** | Free | `BlocklistParser` parses hosts / adblock / plain / dnsmasq formats, normalizes and dedups, drops invalid/comment/IP lines, and enforces a 1M-rule per-list cap. Protected domains (Apple, Lava, Google, Supabase, GitHub, etc.) are filtered out of every list before rules reach the snapshot. |
| **Fail-closed catalog verification** | Free | `BlocklistCatalogSync` verifies downloaded bytes against the catalog's accepted-hash allowlist and fails closed to the last-good cache or rejects when bytes don't match. |
| **Allowed Exceptions (allowlist)** | Free | Exception-led allowing of specific domains; guardrails still win over the allowlist. Free caps: 10 allowed / 10 blocked manual domains; Plus raises these to 500 / 500. (`SubscriptionPolicy`) |
| **Filter-rules budget (honest tier limit)** | Free / Plus | Tier limit is measured in compiled filter **rules**, not list count: **Free 500K / Plus 2M**, under a ~3.26M hard device guardrail derived from the ~50 MiB NE ceiling. The device cap is a safety floor, never a paywall, and replaced the old enabled-list-count cap (free 3 / paid 10). Authoritative enforcement is at compile time on the deduped union (device-cap first, then tier). (`FilterSnapshotMemoryBudget`, `FilterRuleTierLimit`, `FilterSnapshotPreparationService`) |
| **Selection meter** | Free / Plus | A live UI meter sums per-list rule counts with a 1.10 soft margin to show budget headroom while you pick lists; advisory only — the compile-time post-union check is authoritative. (`FilterRuleBudget`) |
| **Custom blocklists (Pi-hole-style URLs)** | **Plus** | Add custom HTTPS blocklist URLs fetched directly on-device, never proxied through or logged to Lava servers and excluded from bug-report payloads. (`SubscriptionPolicy.allowsCustomBlocklists`) |
| **Staged Filters edit flow** | Free | An overview-first Filters tab plus a draft → view/edit → confirm → prepare flow for Blocked Domains and Allowed Exceptions; the previous config stays active if preparation fails. (`FiltersView`, `FilterReviewFlowView`) |

More detail on the catalog, parser, and snapshot lives in [../architecture/blocklist-catalog.md](../architecture/dns-filtering-and-blocklists.md).

---

## Encrypted DNS

All three encrypted upstream transports are implemented and wired into the tunnel. They encrypt **allowed** lookups between your device and the resolver; the default resolver is Google plain DNS, and encrypted transports are opt-in.

| Feature | Tier | Notes |
|---|---|---|
| **DoH (DNS-over-HTTPS)** | Free | Encrypted upstream over HTTPS (URLSession), selectable from the built-in **DNS Transport** picker for any built-in resolver (Google / Cloudflare / Quad9 / DNS.SB). Every request opts into HTTP/3, but the **DoH3** annotation (no slash, e.g. `Quad9 (DoH3)`) is earned only by an observed h3 ALPN negotiation — preferred, never promised; falls back to `DoH`. (`DoHTransport`) |
| **DoT (DNS-over-TLS)** | Free | Encrypted upstream with a bounded per-endpoint connection pool (round-robin, max 4) that reuses connections and refreshes idle/stale ones, with a single fresh-connection retry on timeout. Selectable from the same built-in DNS Transport picker. (`DoTTransport`) |
| **DoQ (DNS-over-QUIC)** | **Plus** | Encrypted upstream that opens a **fresh QUIC connection per query**; connection reuse is deferred (tracked as a Track 4 item — one device-tested reuse attempt was reverted on iOS 26.5). There is no built-in DoQ preset, so DoQ is reachable only via a custom DNS stamp (`sdns://` protocol `0x04`) or DoQ URL, which requires the Plus custom-resolver path. (`DoQTransport`) |
| **Resolver presets** | Free | Built-in plain/DoH/DoT presets for Google, Cloudflare, Quad9, and DNS.SB; Google plain DNS is the default. The DNS Transport picker is ungated — any Free user can switch a built-in resolver to DoH or DoT. (`DNSResolverPreset` / `DNSResolverTransport`) |
| **Custom DNS resolver** | **Plus** | Bring-your-own resolver, including custom DNS stamps/URLs (the only path to DoQ). Gated by `allowsCustomDNS`. (`SubscriptionPolicy.allowsCustomDNS`) |

> Status note: DoH device QA is **(In progress)** — verified on Wi-Fi (iPhone 15 Pro / iOS 26.4.2), with cellular and Wi-Fi↔cellular transition cases still pending manual network switching.

Transport internals are documented in [../architecture/dns-transports.md](../architecture/dns-filtering-and-blocklists.md).

---

## Accounts & zero-knowledge backup

An account is **optional** and exists only to authenticate an encrypted-backup sync — protection works fully with no login. Backup is zero-knowledge: the server stores only ciphertext and non-secret envelope metadata.

| Feature | Tier | Notes |
|---|---|---|
| **Sign in with Apple / Google** | Free | Optional login via Supabase Auth's native id_token grant (`grant_type=id_token`): the app obtains a provider ID token plus a SHA-256-hashed nonce locally and exchanges it for a Supabase session, stored only in a device-only Keychain. Apple + Google only — email/password sign-in is **(Dropped)**. (`SupabaseIDTokenAuth`, `AccountAuthService`) |
| **Zero-knowledge encrypted backup** | Free | The settings payload is encrypted on-device with AES-256-GCM under a random payload key, wrapped into independent PBKDF2-HMAC-SHA256 key slots. Servers store only ciphertext, envelope metadata, and a server recovery share — never plaintext, the recovery phrase, or any decryption key. (`ZeroKnowledgeBackupEnvelope`) |
| **Data-minimized backup payload** | Free | The only plaintext inside the envelope is a minimized settings payload (blocklist IDs, allow/block domains, resolver settings, local-log prefs, custom-list metadata, Lava Guard ledger, a protection-enabled hint) — no diagnostics, snapshots, full blocklists, or `isPaid`. (`BackupConfigurationPayload`) |
| **Passwordless setup & restore** | Free | A 3-step setup creates a device-secret (Keychain) slot, an assisted-recovery slot, and an optional passkey slot. Restore offers **This Device**, **Passkey**, and **Recovery phrase** unlock modes. (A vestigial password slot survives in core but is unwired — passwordless is canonical; password support is **(Dropped)**.) |
| **8-word recovery phrase + server share** | Free | The recovery phrase is 8 locally CSPRNG-generated pseudo-word tokens you save outside Lava. It is combined with a server-held recovery share via SHA-256 to unlock assisted recovery — never sent to the server, and useless to the server alone. (`BackupRecoveryPhrase`) |
| **Passkey recovery (server-gated)** | Free | Optional unlock via a platform passkey (WebAuthn, RP id `lavasecurity.app`). Explicitly **server-gated, not zero-knowledge**: the Worker releases a stored recovery secret after a successful WebAuthn assertion. (`BackupPasskeyCoordinator`, `BackupPasskeyRecoveryService`) |
| **Account deletion & data rights** | Free | In-app deletion calls an authenticated Worker endpoint (`v1/account/delete`) with the Supabase access token, deletes backup rows server-side, then signs out and clears local sessions. |

Device-only unlock material uses the shared `GenericKeychainStore` (`AfterFirstUnlockThisDeviceOnly`, not synchronizable). Full crypto and recovery design: [../architecture/zero-knowledge-backup.md](../architecture/accounts-and-backup.md).

---

## Widget & Live Activity

Lava ships a **Live Activity / Dynamic Island** experience for protection status. There is no Home Screen timeline widget today — the `LavaSecWidget` target's widget bundle contains only the Live Activity configuration (`LavaProtectionLiveActivityWidget`).

| Feature | Tier | Notes |
|---|---|---|
| **Protection Live Activity** | Free | An `ActivityConfiguration` over `LavaActivityAttributes` shows live protection status on the Lock Screen and in the Dynamic Island (compact, expanded, and minimal presentations). Managed by `LavaLiveActivityController`, gated to iPhone/iPad and on the user's Live Activity authorization. |
| **Interactive pause / resume / reconnect** | Free | `LiveActivityIntent`-backed controls pause protection for 5 or 10 minutes (with authenticated variants), resume, and reconnect directly from the activity. The widget renders only "5 min" and "10 min" pause buttons. (`LavaLiveActivityIntents`, `LavaLiveActivityActionRequest`) |
| **Skin-aware Dynamic Island glyph** | Free | The activity renders the selected Guardian shield style and a per-skin Dynamic Island glyph accent color. |

> Naming note: the Live Activity carries an Apple SF Symbol id (`statusSymbolName`) and English copy inside the otherwise platform-agnostic Shared layer. Lifting these into a per-OS presentation map is **(Planned)** — see roadmap-and-directions.md.

---

## Onboarding

A multi-page first-run flow explains local protection, installs the VPN config at the right moment, asks for notification permission, and lets you accept or customize defaults — with copy deliberately tightened to avoid over-promising.

| Feature | Tier | Notes |
|---|---|---|
| **Multi-page onboarding** | Free | An 8-page `OnboardingPage` flow: *The Internet Is Lava* (`lava`) → guard scene (`guardIntro` + `features` share one animated scene) → *Install Lava Local VPN* (`vpn`) → notifications → settings → customize → done. Uses the Guardian mascot, including the `grateful` success expression. (`OnboardingFlowView`) |
| **Honest, calm copy** | Free | Copy avoids fear and over-claiming: "blocks known risky domains from selected blocklists," "Install Lava local VPN configuration," "traffic not sent through Lava servers," and a "Continue without account" path so free protection never requires sign-in. |
| **Right-moment VPN install** | Free | The VPN configuration is installed at the dedicated install step (not on launch); onboarding neutralization removes the config cleanly rather than re-saving it, avoiding orphaned-profile re-prompts. |

---

## Settings & customization

| Feature | Tier | Notes |
|---|---|---|
| **Lava Security Plus purchase** | Free → **Plus** | StoreKit is the purchase truth. `LavaSecurityPlusStore` loads products, runs `purchase`, and observes `Transaction.updates` / `currentEntitlements`. Plans (`LavaSecurityPlusPolicy`): monthly `$0.99/month`, yearly `$9.99/year`, lifetime `$29.99` (product IDs `lava_security_plus_{monthly,yearly,lifetime}`; live prices come from the App Store, with these as fallback copy). Plus unlocks custom blocklists, custom DNS (including DoQ via custom stamps), and the 2M filter-rules budget — and never bypasses guardrails. |
| **Guardian shield skins & app icons** | Free | 7 swappable shield skins, each paired with an alternate app icon: Original, Fire Opal, Amethyst, Obsidian, Cherry Quartz, Emerald, Kiwi Crème. An option matches the app icon to the selected Lava Guard look. (`GuardianShieldStyle`) |
| **Custom resolver & encrypted-DNS settings** | Free / **Plus** | Switch any built-in resolver to DoH or DoT from the **DNS Transport** picker (Free). Custom resolvers and DNS stamps (the only route to DoQ) require Plus. (See Encrypted DNS above.) |
| **Dynamic Reports** | Free | The Reports surface shows local-only data from the running tunnel and App Group storage — empty when idle, live when protecting. No domain history is sent anywhere. |
| **Network Activity & state log** | Free | A bounded, local-only chronological stream of network changes, user actions, and protection-state transitions, with privacy-safe log text. (`NetworkActivityLog`) |
| **Nerd Stats (version & tunnel health)** | Free | A `VersionNerdStatsView` surfaces the running app version + build number (`CFBundleShortVersionString` / `CFBundleVersion`) alongside tunnel health, for QA and bug reporting. |
| **Bug report bundle** | Free | A staged, topic-led bug-report flow previews a minimized, anonymized support bundle (no domain history) before sending it to the API Worker. (`BugReportSettingsView`) |
| **Legal Notices** | Free | A Legal Notices screen with nominative, plain-text third-party brand references implying no endorsement. (`LegalNoticesView`) |
| **Diagnostics opt-in** | Free | An explicit toggle controls whether domain diagnostics are kept locally (`keepDomainDiagnostics`). The product default is **on** (kept locally) — both the `AppConfiguration` init default and `lavaRecommendedDefaults` set it true. Diagnostics never leave the device automatically. |
| **Battery-friendly UI sampling** | Free | The UI is event-driven: report files are read only on mtime change, and Activity refreshes on appearance/foreground/manual action rather than on a fixed timer, reducing avoidable drain. |

---

## See also

- [Platform Parity](platform-parity.md) — stable feature ids, Android/iOS status, and the behavioral contract that platform tests should enforce.
- [../architecture/ios-client.md](../architecture/ios-client.md) — app / packet-tunnel / widget targets and shared `LavaSecCore` state.
- [../architecture/dns-transports.md](../architecture/dns-filtering-and-blocklists.md) — DoH / DoT / DoQ transport internals.
- [../architecture/blocklist-catalog.md](../architecture/dns-filtering-and-blocklists.md) — catalog, parser, snapshot, and the filter-rules budget.
- [../architecture/zero-knowledge-backup.md](../architecture/accounts-and-backup.md) — account auth and encrypted-backup crypto.
