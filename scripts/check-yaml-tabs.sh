#!/usr/bin/env bash
# Enforces that YAML files contain no tab characters, because tabs are not allowed in YAML indentation.
set -u

root=$(git rev-parse --show-toplevel 2>/dev/null) || root=""
if [ -n "$root" ]; then
  cd "$root" || exit 1
fi

fail=0
tab=$'\t'

while IFS= read -r -d '' path; do
  case "$path" in
    *.yaml|*.yml) ;;
    *) continue ;;
  esac

  if [ ! -f "$path" ]; then
    continue
  fi

  while IFS= read -r match; do
    lineno=${match%%:*}
    printf '%s: line %s: tab character found in YAML\n' "$path" "$lineno"
    fail=1
  done < <(grep -n -F -e "$tab" -- "$path" || true)
done < <(git ls-files -z)

if [ "$fail" -ne 0 ]; then
  exit 1
fi

printf 'OK yaml-tabs\n'
exit 0
