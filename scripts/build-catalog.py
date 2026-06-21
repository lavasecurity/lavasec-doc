#!/usr/bin/env python3
"""Validate + render the canonical blocklist catalog.

The canonical source of truth is ``data/blocklist-catalog.yml``. This script:

  * validates it against the schema + the hard legal/product invariants, then
  * regenerates two derived, committed artifacts:
      - ``data/blocklist-catalog.json``      (machine-readable; clients + infra consume this)
      - ``docs/legal/blocklist-catalog.md``  (human-readable index for the public site)

Usage:
    python3 scripts/build-catalog.py            # validate + regenerate artifacts
    python3 scripts/build-catalog.py --check    # validate + fail if artifacts drifted (CI)

Exit code is non-zero on any validation error or, under ``--check``, on drift.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced clearly in CI/local
    sys.exit(
        "PyYAML is required. It ships with MkDocs: `pip install -r requirements.txt`."
    )

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / "data" / "blocklist-catalog.yml"
JSON_PATH = ROOT / "data" / "blocklist-catalog.json"
PAGE_PATH = ROOT / "docs" / "legal" / "blocklist-catalog.md"

PROVIDERS = {"hagezi", "blocklistproject", "stevenblack", "oisd", "phishing_database", "adguard", "onehosts"}
LICENSES = {"GPL-3.0", "MIT", "Unlicense", "MPL-2.0"}
PARSE_FORMATS = {"domain_list", "hosts", "adblock"}
WARNING_LEVELS = {"normal", "advanced", "aggressive"}
SIZE_HINTS = {"small", "medium", "large"}
COUNSEL = {"approved", "required", "not_reviewed", "rejected"}

# Every key a source row must carry. Keeps the YAML honest as it grows.
SOURCE_KEYS = {
    "id", "name", "provider", "category", "license", "license_text_url",
    "source_url", "project_url", "parse_format", "redistribution_mode",
    "warning_level", "default_enabled", "size_hint", "counsel_status",
}
CATEGORY_KEYS = {"id", "order", "label", "description", "icon"}

PROVIDER_DISPLAY = {
    "hagezi": "HaGeZi",
    "blocklistproject": "The Block List Project",
    "stevenblack": "Steven Black",
    "oisd": "OISD",
    "phishing_database": "Phishing.Database",
    "adguard": "AdGuard",
    "onehosts": "1Hosts",
}


def fail(errors: list[str]) -> None:
    print("Catalog validation FAILED:", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    sys.exit(1)


def load() -> dict:
    with YAML_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def validate(doc: dict) -> tuple[list[dict], list[dict]]:
    errors: list[str] = []

    if doc.get("schema_version") != 1:
        errors.append(f"schema_version must be 1, got {doc.get('schema_version')!r}")

    categories = doc.get("categories") or []
    sources = doc.get("sources") or []
    category_ids: set[str] = set()

    for cat in categories:
        missing = CATEGORY_KEYS - cat.keys()
        extra = cat.keys() - CATEGORY_KEYS
        if missing:
            errors.append(f"category {cat.get('id', '?')!r} missing keys: {sorted(missing)}")
        if extra:
            errors.append(f"category {cat.get('id', '?')!r} unexpected keys: {sorted(extra)}")
        cid = cat.get("id")
        if cid in category_ids:
            errors.append(f"duplicate category id: {cid!r}")
        category_ids.add(cid)
        if not isinstance(cat.get("order"), int):
            errors.append(f"category {cid!r} order must be an int")

    seen_ids: set[str] = set()
    used_categories: set[str] = set()

    for src in sources:
        sid = src.get("id", "?")
        missing = SOURCE_KEYS - src.keys()
        extra = src.keys() - SOURCE_KEYS
        if missing:
            errors.append(f"source {sid!r} missing keys: {sorted(missing)}")
        if extra:
            errors.append(f"source {sid!r} unexpected keys: {sorted(extra)}")
        if sid in seen_ids:
            errors.append(f"duplicate source id: {sid!r}")
        seen_ids.add(sid)

        if src.get("provider") not in PROVIDERS:
            errors.append(f"source {sid!r} provider {src.get('provider')!r} not in {sorted(PROVIDERS)}")
        if src.get("category") not in category_ids:
            errors.append(f"source {sid!r} category {src.get('category')!r} is not a defined category")
        else:
            used_categories.add(src["category"])
        if src.get("license") not in LICENSES:
            errors.append(f"source {sid!r} license {src.get('license')!r} not in {sorted(LICENSES)}")
        if src.get("parse_format") not in PARSE_FORMATS:
            errors.append(f"source {sid!r} parse_format {src.get('parse_format')!r} invalid")
        if src.get("warning_level") not in WARNING_LEVELS:
            errors.append(f"source {sid!r} warning_level {src.get('warning_level')!r} invalid")
        if src.get("size_hint") not in SIZE_HINTS:
            errors.append(f"source {sid!r} size_hint {src.get('size_hint')!r} invalid")
        if src.get("counsel_status") not in COUNSEL:
            errors.append(f"source {sid!r} counsel_status {src.get('counsel_status')!r} invalid")
        if not isinstance(src.get("default_enabled"), bool):
            errors.append(f"source {sid!r} default_enabled must be a bool")

        url = src.get("source_url", "")
        if not isinstance(url, str) or not url.startswith("https://"):
            errors.append(f"source {sid!r} source_url must be https")

        # ---- Hard invariants -------------------------------------------------
        if src.get("redistribution_mode") != "source_url_only":
            errors.append(
                f"source {sid!r} redistribution_mode must be 'source_url_only' "
                f"(Lava never mirrors upstream bytes)"
            )
        if src.get("license") == "GPL-3.0":
            if src.get("default_enabled") is True:
                errors.append(f"source {sid!r} is GPL-3.0 and must NOT be default_enabled")
            if not src.get("license_text_url"):
                errors.append(f"source {sid!r} is GPL-3.0 and must set license_text_url")
        if src.get("provider") == "stevenblack":
            if src.get("default_enabled") is True:
                errors.append(f"source {sid!r} (StevenBlack) must NOT be default_enabled until counsel-cleared")

    empty = category_ids - used_categories
    if empty:
        errors.append(f"categories with no sources (remove or populate): {sorted(empty)}")

    if errors:
        fail(errors)

    cat_by_id = {c["id"]: c for c in categories}
    categories_sorted = sorted(categories, key=lambda c: c["order"])
    sources_sorted = sorted(sources, key=lambda s: (cat_by_id[s["category"]]["order"], s["name"]))
    return categories_sorted, sources_sorted


def render_json(doc: dict, categories: list[dict], sources: list[dict]) -> str:
    payload = {
        "schema_version": doc["schema_version"],
        "_generated": "DO NOT EDIT — regenerate via scripts/build-catalog.py from blocklist-catalog.yml",
        "categories": categories,
        "sources": sources,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_page(categories: list[dict], sources: list[dict]) -> str:
    defaults = [s["id"] for s in sources if s["default_enabled"]]
    lines: list[str] = []
    lines.append("<!-- DO NOT EDIT — generated by scripts/build-catalog.py from data/blocklist-catalog.yml -->")
    lines.append("# Blocklist Catalog")
    lines.append("")
    lines.append(
        "This is the canonical index of the curated blocklist sources Lava offers — "
        "the single machine-readable spec that every Lava client (iOS, Android) and the "
        "backend catalog API are generated from. It is the source of truth each platform "
        "is built to match as it adopts the catalog; a given app build reflects this list "
        "as of the catalog version it shipped with."
    )
    lines.append("")
    lines.append("## How Lava uses these lists")
    lines.append("")
    lines.append(
        "Every source is **source-URL-only**: the app fetches the upstream list "
        "directly from the project's own URL and processes it locally on your device. "
        "Lava does not mirror, modify, or redistribute any third-party list data. "
        "Each source keeps its own license; see "
        "[Third-Party Notices](third-party-notices.md) and the "
        "[Open-Source List Data Terms](open-source-list-data-terms-carveout.md)."
    )
    lines.append("")
    if defaults:
        pretty = ", ".join(
            next(s["name"] for s in sources if s["id"] == did) for did in defaults
        )
        lines.append(
            f"**Enabled by default on a fresh install:** {pretty}. "
            "Everything else is opt-in. Copyleft (GPL-3.0) and aggregated lists are "
            "never enabled for you automatically — you choose them."
        )
        lines.append("")

    for cat in categories:
        cat_sources = [s for s in sources if s["category"] == cat["id"]]
        lines.append(f"## {cat['label']}")
        lines.append("")
        lines.append(cat["description"])
        lines.append("")
        lines.append("| List | Provider | License | Size | Default | Source |")
        lines.append("| --- | --- | --- | :---: | :---: | --- |")
        for s in cat_sources:
            default = "✓" if s["default_enabled"] else ""
            provider = PROVIDER_DISPLAY[s["provider"]]
            size = s["size_hint"].capitalize()
            link = f"[link]({s['source_url']})"
            lines.append(
                f"| {s['name']} | {provider} | {s['license']} | {size} | {default} | {link} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"_Catalog spec schema version 1 · {len(sources)} sources across "
        f"{len(categories)} categories._"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and fail if generated artifacts are out of date (for CI).",
    )
    args = parser.parse_args()

    doc = load()
    categories, sources = validate(doc)
    json_text = render_json(doc, categories, sources)
    page_text = render_page(categories, sources)

    if args.check:
        drift = []
        if not JSON_PATH.exists() or JSON_PATH.read_text(encoding="utf-8") != json_text:
            drift.append(str(JSON_PATH.relative_to(ROOT)))
        if not PAGE_PATH.exists() or PAGE_PATH.read_text(encoding="utf-8") != page_text:
            drift.append(str(PAGE_PATH.relative_to(ROOT)))
        if drift:
            print(
                "Generated catalog artifacts are out of date with blocklist-catalog.yml:\n  "
                + "\n  ".join(drift)
                + "\nRun: python3 scripts/build-catalog.py",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Catalog OK — {len(sources)} sources, {len(categories)} categories, artifacts in sync.")
        return

    JSON_PATH.write_text(json_text, encoding="utf-8")
    PAGE_PATH.write_text(page_text, encoding="utf-8")
    print(
        f"Wrote {JSON_PATH.relative_to(ROOT)} and {PAGE_PATH.relative_to(ROOT)} — "
        f"{len(sources)} sources across {len(categories)} categories."
    )


if __name__ == "__main__":
    main()
