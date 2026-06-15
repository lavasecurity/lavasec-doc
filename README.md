# lavasec-doc

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

## Layout

```
docs/
  index.md                      # home / landing
  product/                      # overview, feature catalog
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

CI (`.github/workflows/deploy.yml`) builds the site and deploys it to Cloudflare
Pages on every push to `main`. It needs two repo secrets:

- `CLOUDFLARE_API_TOKEN` — a token with the **Cloudflare Pages: Edit** permission.
- `CLOUDFLARE_ACCOUNT_ID` — the account that owns the `lavasec-doc` Pages project.

The custom domain (`docs.lavasecurity.app`) is attached in the Cloudflare Pages
dashboard. Alternatively, Pages' native Git integration can build the repo
directly with build command `pip install -r requirements.txt && mkdocs build`
and output directory `site`.

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
