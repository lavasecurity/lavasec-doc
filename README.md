# lavasec-doc

[![Build check](https://github.com/lavasecurity/lavasec-doc/actions/workflows/ci.yml/badge.svg)](https://github.com/lavasecurity/lavasec-doc/actions/workflows/ci.yml)
[![Security](https://github.com/lavasecurity/lavasec-doc/actions/workflows/security.yml/badge.svg)](https://github.com/lavasecurity/lavasec-doc/actions/workflows/security.yml)
[![Built with MkDocs Material](https://img.shields.io/badge/built%20with-MkDocs%20Material-526CFE?logo=materialformkdocs&logoColor=white)](https://squidfunk.github.io/mkdocs-material/)
[![Docs](https://img.shields.io/badge/docs-docs.lavasecurity.app-F38020?logo=cloudflare&logoColor=white)](https://docs.lavasecurity.app)
[![License: CC BY 4.0](https://img.shields.io/badge/license-CC%20BY%204.0-lightgrey?logo=creativecommons&logoColor=white)](LICENSE)

The public documentation site for **Lava Security** — the "manual" for how the
product works: architecture, behavior, design system, and the decisions behind
it. Built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
and deployed to Cloudflare Pages at **https://docs.lavasecurity.app**.

> **Scope.** This repo holds only the *public* manual (architecture, product
> overview, design system, ADRs, compliance notices). Internal material —
> roadmap, pricing/monetization, the IP risk register, ops runbooks, the
> security audit — stays private in `lavasec-infra`. The docs are **distilled
> from the source** (plans, code, commits) and regenerated as the product
> evolves; see [Regenerating the docs](#regenerating-the-docs).

## Develop

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
mkdocs serve            # live preview at http://127.0.0.1:8000
mkdocs build --strict   # production build into ./site (CI gate)
```

`--strict` fails the build on broken internal links, so keep cross-links valid.

## Feature tracking and platform parity

`docs/product/platform-parity.md` is the public source of truth for
cross-platform feature contracts. It records stable feature ids, the user-facing
promise, per-platform status, and the test or fixture family that should enforce
behavior.

Use it when a change affects:

- a privacy promise;
- local DNS filtering behavior;
- Free vs Plus boundaries;
- Android/iOS parity expectations;
- platform-native differences that should be intentional.

Keep delivery state, private risk, pricing strategy, and operational work in
`lavasec-infra/plans`. The docs define the contract; plans track the work; tests
prove the behavior.

## Layout

```
docs/
  index.md                      # home / landing
  product/                      # overview, feature catalog, platform parity
  architecture/                 # system, iOS client, DNS filtering, backend, accounts
  design-system/                # calm core, earned depth
  decisions/                    # ADR-style key decisions
  legal/                        # third-party notices, source-url-only/GPL compliance
mkdocs.yml                      # site config + nav + theme
requirements.txt                # mkdocs-material, mkdocs-static-i18n
.github/workflows/deploy.yml    # build + deploy to Cloudflare Pages
```

## Internationalization

The site uses [`mkdocs-static-i18n`](https://github.com/ultrabug/mkdocs-static-i18n)
with the **suffix** structure: untranslated pages are English (the default), and
a translation is a sibling file named `<page>.<locale>.md` — e.g.
`product/overview.fr.md`. To enable a language:

1. Add it under `plugins.i18n.languages` in `mkdocs.yml` (e.g. `fr` / Français).
2. Add the translated `*.fr.md` files. Untranslated pages fall back to English.

A language switcher appears automatically once more than one language is built.
This mirrors the app's localization targets (de, fr, ja, zh-Hans, zh-Hant).

## Deploy

Deployed to **Cloudflare Workers (static assets)** via Cloudflare's git-connected
**Workers Builds** — Cloudflare builds and deploys on every push to `main`, and
**no GitHub Actions secrets are needed** (Cloudflare authenticates the deploy).

In the Cloudflare dashboard, the `lavasec-doc` project's build settings are:

- **Build command:** `pip install -r requirements.txt && mkdocs build`
- **Deploy command:** `npx wrangler deploy`  (reads [`wrangler.toml`](wrangler.toml), which serves `./site` as an assets-only Worker with a custom 404)
- If the build can't find Python, add a build variable `PYTHON_VERSION=3.12`.

Attach **docs.lavasecurity.app** under the project's **Custom Domains**.

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) only runs
`mkdocs build --strict` as a PR quality gate — it does **not** deploy. To deploy
manually: `npx wrangler deploy` after a local `mkdocs build`.

## Feedback

Each content page has a privacy-respecting **"Was this page helpful?"** widget
(no analytics, no cookies). 👎 opens a pre-filled issue labelled `docs-feedback`.

Treat these as a **qualitative docs bug backlog, not a metric**: the signal is
biased toward dissatisfaction and technical users (silence ≠ good docs), so act
on *repetition*, not single clicks. The label needs an owner and a light triage
cadence; if no one will read it, hide the widget (`hide_feedback: true` in a
page's front matter, or remove the include in `overrides/main.html`) rather than
collect into a void. For aggregate "worst pages" metrics, add Cloudflare Web
Analytics later — don't add Google Analytics.

## License

Documentation content is licensed [CC BY 4.0](LICENSE). Code samples are under
the license of the project they describe.
