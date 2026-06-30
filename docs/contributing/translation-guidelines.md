---
last_reviewed: 2026-06-30
owner: localization
source_repos: [lavasec-ios, lavasec-web, lavasec-doc]
---

# Translation & Localization Guidelines

This page is the single source of truth for how Lava writes user-facing copy and
how that copy is translated. It applies to everyone — author or reviewer, human
or AI — touching strings in the iOS app (`Localizable.xcstrings`,
`InfoPlist.xcstrings`, `LavaSecCore` notification strings), the website
(`content/pages.<locale>.json`), and these docs (`*.<locale>.md`).

## The one rule

> Copy should read as if a thoughtful native speaker wrote it for that surface —
> **concise, clear, and native.** It must never read like a machine translation
> or like AI: no over-explanation, no hedging, no restating the same idea twice.

If a sentence already meets the bar, leave it alone. This is a polish pass, not a
blanket rewrite — don't regress good copy to prove you did something.

## Languages

English is the source. Ten locales ship: `en`, `de`, `es`, `fr`, `it`, `ja`,
`ko`, `pt-BR`, `zh-Hans`, `zh-Hant`.

## Voice & register by surface

Register is chosen per surface, not globally.

| Surface | Register | What it means |
| --- | --- | --- |
| App — onboarding, marketing, general UI | **Conversational** | Natural, lightly spoken. Warmth comes from word choice and rhythm. |
| App — warnings, security, errors | **Careful + precise** | Unambiguous, slightly formal. Prefer the clearest standard term over a colloquial one. Never breezy. |
| Website | **Conversational** (matches the app) | Same voice as the app; headlines and taglines may be a touch punchier. |
| Docs (these pages) | **Concise + precise, neutral** | Tighten and de-AI, but stay professional and exact — not chatty. |
| Brand / voice lines | **Vivid + faithful** | Keep the metaphor with flair; preserve the first-person founder voice ("I", "my dad"). Never flatten or translate word-for-word. |

### English source copy

Edit English **actively**: restructure for concision and kill AI tells. Never
change meaning, and leave deliberate voice lines alone (the "internet is lava"
tagline, the "my dad" lines). Typical fixes: collapse a symmetric triad to one
clause, cut a hedge, drop an over-explanation.

## Address form

Apple-style: **informal where idiomatic**, with the conventional exceptions.

| Locale | Form | Notes |
| --- | --- | --- |
| `zh-Hant`, `zh-Hans` | 你 | informal; matches Apple's zh UI |
| `de` | du | Apple moved to `du` (~2021) |
| `es` | tú | |
| `it` | tu | |
| `pt-BR` | você | the neutral default |
| `fr` | **vous** | French app convention resists `tu`; keep `vous` |
| `ja` | です／ます | polite-neutral; no casual form for a stranger-facing app |
| `ko` | 해요체 | polite; never 반말 |
| `en` | "you" | default informal |

## The de-AI checklist

- **One idea per panel.** No restating the same point two or three ways. This is
  the most common AI tell.
- **Cut hedges and filler:** 可能／基本上, "just", "simply", "very", "in order to".
- **Native verbs over translationese** (in conversational copy): 放行 not 通過,
  擋下 not 命中, 不經過 not 繞經. (In *warning* copy, precision wins — use the
  clearest standard term even if it's less colloquial.)
- **Trim Chinese over-determiners** (一個／某個／該) where natural; use subject-drop
  in marketing copy.
- **No symmetric triads / over-explanation** — the "X, and also Y, and Z too" shape.
- **Match the surface register** from the table above.

## Plain language (the "dad test")

Lava's promise is "even my dad can use it." In the **app and on the website**,
prefer plain words a non-technical parent understands; keep protocol acronyms and
internals to **Advanced settings and these docs**, where the audience expects them.

| Jargon | Use instead (user-facing) |
| --- | --- |
| DNS resolver / resolver | DNS provider |
| DNS Transport | Encryption |
| DNS lookups / queries | requests to find a website's address |
| network extension | on-device filter |
| payload / ciphertext | encrypted data |

Glossary acronyms (`DNS`, `DoH`) may appear in Advanced DNS settings and docs.
User-visible diagnostics say plain things — "protection status", "connection
health", "your active filter" — not "Tunnel Lifecycle" or "Filter Snapshot".

## Capitalization & punctuation (English UI)

- **Sentence case** for every label — titles, nav, section headers, settings
  rows, buttons. Capitalize only the first word, proper nouns, and acronyms
  (`DNS`, `IP`, `VPN`, `ID`). e.g. "DNS providers", "Information sent", "Nerd
  stats".
- **No terminal punctuation** on labels. Exceptions: `?` on a genuine question,
  `:` on a `key: value` row, and named toasts (`Copied!`).
- A button verb that takes the feature noun keeps the noun capitalized as a
  control — **Add Filter** — and the tab/screen is **Filters**; but in prose the
  feature noun is lowercase ("import a filter", "your current filter").

## Localization robustness (plurals, numbers, length)

- **Plurals:** never ship hand-authored singular/plural English pairs as the
  contract. Use CLDR plural rules — `.xcstrings` plural *variations* (iOS) / ICU
  `plural{}` (web) — so each locale supplies its own forms (zero/one/few/many/
  other). The English one/other is only the seed.
- **Numbers:** format injected counts through a locale `NumberFormatter`
  (grouping on) before substitution — `2,000` (en) must render `2.000` (de) /
  `2 000` (fr). Prefer `%lld` over `%@`-as-`String` for counts.
- **Length:** truncation-sensitive labels (table headers, status chips, primary
  CTAs, nav) carry a `maxLength` budget, and the build gate validates
  translations against it — not just completeness.

## CJK typography (`zh-Hant`, `zh-Hans`, `ja`)

- **Space between Han and Latin/digits:** 你的 iPhone, 封鎖 200 萬個網域.
- **Full-width punctuation:** ，。；：「」（）— not half-width.
- **Em-dash:** EN `—` → `——` in CJK (or restructure the sentence).
- **Ellipsis:** `…` (single glyph), not `...`.
- **No sentence-final particles** (喔／啦／吧／囉). Conversational warmth comes from
  phrasing and rhythm, not particles. (`ja`: prefer the long-vowel katakana —
  フィルター, not フィルタ.)

## Glossary — keep, localize, or translate

**Keep in English (never translate):**

- Brand: `Lava Security`, `Lava Security Plus`
- Protocol / tech: `DNS`, `DoH`, `DNS-over-HTTPS`, `IP`, `VPN`, `TLS`, `HTTPS`, `QUIC`
- Units / formats: `QR`, `KB`/`MB`, SPDX license IDs (`GPL-3.0`, `MPL-2.0`, `MIT`,
  `Unlicense`), the `LF1-` setup-code prefix (verbatim token)
- Proper names (verbatim): source/provider names — `1Hosts`, `Quad9`, `OISD`,
  `StevenBlack`, `DNS.SB`
- Common loanwords: `App`, `iPhone`, `iOS`

**Product vocabulary (use exactly):**

- **filter** — the switchable bundle a user imports, switches (including via
  Focus), and shares. This is the canonical word; **never call the bundle a
  "list".**
- **blocklist** (one word) / **list** — a single rule source (1Hosts, OISD, a
  category). "list" always means *one source*, never the bundle.

**Use Apple's localized platform term** (example: `zh-Hant`):

| English | zh-Hant |
| --- | --- |
| Focus | 專注模式 |
| Live Activity | 即時動態 |
| Settings | 設定 |
| Shortcuts | 捷徑 |
| Widget | 小工具 |

**Translate fully** — filter presets (Core / Balanced / Extra → 核心／均衡／進階),
category names (Adult Content → 成人內容; Privacy & Data → 隱私權與資料), and all UI
prose, labels, and body copy.

**Per-locale term notes:** `zh-Hant` 篩選器 (not 過濾器); `de` Blockliste (not
Sperrliste).

`zh-Hans` is a **true mainland-China localization, not a script conversion** of
`zh-Hant` — keep mainland conventions and never converge it back to Taiwan terms:
域名 (not 網域), 拦截/屏蔽 (not 封鎖), 应用 (not App where 应用 reads natural), 软件
(not 軟體), 你 + 拦截列表 (not 拦截清单). When polishing, preserve the mainland term
choices; only fix wording quality.

## Worked examples (before → after)

Current copy on the left, the polished target on the right, with the principle it
demonstrates. These are the calibration set — when in doubt, match their feel.

### 1 · App marketing — Focus how-to (conversational)

- **EN:** ~~Pick a filter for a Focus and Lava switches to it on its own whenever
  that Focus turns on — no taps needed.~~
  → **Tie a filter to a Focus and Lava switches to it whenever that Focus turns on.**
- **繁中:** ~~為某個專注模式選擇一個篩選器，每當該專注模式開啟時，Lava 都會自動切換，無需手動操作。~~
  → **為專注模式指定篩選器，該模式一開啟，Lava 就自動切換。**
- *Why:* the source said "automatic" three ways — collapse to one. Drop 某個／一個／該;
  use the natural 一…就 rhythm.

### 2 · App warning — allowed exceptions (careful + precise)

- **EN:** ~~Allowed exceptions can let a domain through even when a blocklist
  catches it. Double-check before saving.~~
  → **An allowed exception lets a domain through even if a blocklist would catch
  it — double-check before you save.**
- **繁中:** ~~允許的例外可能會讓某個網域通過，即使它被封鎖清單命中。儲存前請再次檢查~~
  → **允許的例外會讓網域通過，即使封鎖清單原本會封鎖它；儲存前請仔細檢查。**
- *Why:* warnings stay precise and complete. Drop the hedge (可能) and determiner
  (某個), fix the missing period, but keep the clearest standard terms
  (通過／封鎖) — unambiguous beats breezy here.

### 3 · Website — hero subhead (conversational)

- **EN:** It blocks known-bad domains right on your iPhone — no account, and
  nothing routed through us. *(already good — keep)*
- **繁中:** ~~它會直接在你的 iPhone 上封鎖已知的惡意網域，不用帳號，也不會把流量繞經我們。~~
  → **直接在你的 iPhone 上封鎖已知的惡意網域；不用帳號，流量也不經過我們。**
- *Why:* subject-drop reads natural in zh marketing; 繞經 is translationese →
  不經過. Han↔Latin spacing kept (你的 iPhone).

### 4 · Brand line (vivid + faithful)

- **EN:** The internet is lava — so I made a blocklist app even my dad can use.
- **繁中:** **網路充滿了岩漿，所以我做了一個連我爸都能上手的封鎖清單 App。**
- *Why:* keep the metaphor vivid (the net is *full of* lava), keep the
  first-person founder voice (我／我爸), keep the `App` loanword.

### 5 · Docs — overview opening (concise + precise, neutral)

- **EN:** ~~This page is the front door to the documentation set: a short, plain
  introduction to what Lava is, what it promises, and where to read more.~~
  → **This page is the entry point to the docs — a short, plain overview of what
  Lava is, what it promises, and where to go next.**
- **繁中:** ~~本頁是整套文件的入口：以簡短、平實的方式介紹 Lava 是什麼、它承諾什麼，以及到哪裡可以閱讀更多內容。~~
  → **本頁是整套文件的入口，簡要說明 Lava 是什麼、提供什麼，以及接下來該看哪裡。**
- *Why:* docs stay neutral and exact — tighten the wordiness (以簡短平實的方式介紹 →
  簡要說明) without making it chatty.

## Calibrating direction (the interview method)

Before a large copy or translation pass, **calibrate the direction with the
owner rather than guessing.** Taste decisions (register, formality, how
colloquial, how much to simplify) can't be reverse-engineered from the code —
ask, then write them down here.

Run it as a short **interview, one decision at a time**:

- **One question per decision.** Don't batch unrelated choices; let each answer
  inform the next.
- **Ground every question in context + a real string.** State what the string is
  and where it appears, then show the **English** and — when it's a translation
  call — the **target-language** candidates. Never ask in the abstract.
- **Offer concrete candidates, not adjectives.** Give 2–4 real phrasings the
  reader can compare side by side, mark one **recommended**, and keep the actual
  translation text *visible in the options* (don't bury it).
- **Anchor tone with before→after pairs.** Show current copy vs the proposed
  polish so the choice is felt, not described.
- **If the owner is unsure, supply the convention first.** e.g. "Apple uses
  informal 你 in zh-Hant; Microsoft uses formal 您" — decide against a real
  baseline, not a vacuum.
- **Surface decisions from the real corpus.** Audit the existing strings for
  inconsistencies (terminology, capitalization, jargon, number formats) and bring
  those as grounded questions, instead of inventing hypotheticals.
- **Write every locked decision back into this page.** The interview output is
  this guide; the guide is the contract the polish pass and reviewers hold to.

The "Voice & register", "Address form", and "Glossary" sections above are the
durable result of one such interview.

## How this is enforced

| Surface | Files | Gate |
| --- | --- | --- |
| iOS | `Localizable.xcstrings`, `InfoPlist.xcstrings`, `LavaSecCore/.../*.lproj/*.strings` | `check-localization.mjs` (completeness) + `swift test` |
| Website | `content/pages.<locale>.json` | `npm run check` |
| Docs | `docs/**/*.<locale>.md` | `scripts/check-translations.sh` + `mkdocs build --strict` |

Code review adds a second pass: Codex on every repo, plus Kilo on public
`lavasec-ios` PRs. `legal/*` and `contributing/*` are English-authoritative and
are not required to be translated.
