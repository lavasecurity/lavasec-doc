#!/usr/bin/env bash
# Translation-completeness + staleness check for the localized manual.
#
# Completeness (HARD FAIL): every non-legal English doc under docs/ must have a
#   translation in every locale configured in mkdocs.yml (other than the en
#   default). Catches: a new core doc added without translations, or a locale
#   added/configured without full coverage.
# Staleness (WARNING, non-blocking): a translation whose English source has a
#   newer last-commit than the translation itself — surfaces drift as the docs
#   evolve without blocking English-only edits. (Needs full git history;
#   ci.yml checks out with fetch-depth: 0.)
#
# legal/* is intentionally English-authoritative and is NOT required to be
# translated (compliance language is kept in English).
set -euo pipefail
cd "$(dirname "$0")/.."

LOCALES=$(grep -E '^[[:space:]]+- locale:' mkdocs.yml | awk '{print $3}' | grep -vx en || true)
if [ -z "$LOCALES" ]; then echo "No non-default locales configured; nothing to check."; exit 0; fi

is_variant() { # true if $1 (a .md path) is itself a <locale> translation file
  local base="${1%.md}"
  for L in $LOCALES; do [ "${base%.$L}" != "$base" ] && return 0; done
  return 1
}

missing=0; stale=0; checked=0
while IFS= read -r en; do
  case "$en" in docs/legal/*) continue ;; esac   # English-authoritative
  is_variant "$en" && continue                    # skip translation files
  base="${en%.md}"; checked=$((checked+1))
  for L in $LOCALES; do
    tr="${base}.${L}.md"
    if [ ! -f "$tr" ]; then
      echo "::error file=$tr::missing $L translation of ${en#docs/}"
      missing=$((missing+1))
      continue
    fi
    ten=$(git log -1 --format=%ct -- "$en" 2>/dev/null || echo 0)
    ttr=$(git log -1 --format=%ct -- "$tr" 2>/dev/null || echo 0)
    if [ "${ten:-0}" -gt "${ttr:-0}" ]; then
      echo "::warning file=$tr::$L translation may be stale — ${en#docs/} changed more recently"
      stale=$((stale+1))
    fi
  done
done < <(find docs -name '*.md' | sort)

echo "translatable docs: $checked | locales: $(echo $LOCALES | tr '\n' ' ')| missing: $missing | stale-warnings: $stale"
if [ "$missing" -ne 0 ]; then
  echo "::error::translation completeness FAILED — $missing missing translation file(s). Add them (or, if a page should stay English-only, move it under legal/ or drop the locale)."
  exit 1
fi
echo "Translation completeness OK."
