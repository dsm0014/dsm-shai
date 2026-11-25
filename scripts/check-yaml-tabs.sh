#!/usr/bin/env bash
# Enforces that YAML files (.yaml or .yml) contain no tab characters, because tabs are not allowed in YAML indentation.
set -u
set -o pipefail
LC_ALL=C
export LC_ALL

cd "$(git rev-parse --show-toplevel)" || exit 1

tab=$(printf '\t')
failed=0

while IFS= read -r -d '' path; do
  case "$path" in
    *.yaml|*.yml) ;;
    *) continue ;;
  esac
  [ -f "$path" ] && [ ! -L "$path" ] || continue

  matches=$(grep -n -a -F -e "$tab" -- "$path") || true
  if [ -n "$matches" ]; then
    while IFS= read -r m; do
      n=${m%%:*}
      printf '%s: line %s: tab character found\n' "$path" "$n"
      failed=1
    done <<< "$matches"
  fi
done < <(git ls-files -z)

if [ "$failed" -ne 0 ]; then
  exit 1
fi

echo "OK yaml-tabs"
exit 0
