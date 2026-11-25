#!/usr/bin/env bash
# Enforces that tracked .yaml and .yml files contain no tab characters, since tabs are not allowed in YAML indentation.

failed=0
tab=$'\t'

while IFS= read -r -d '' path; do
  case "$path" in
    *.yaml|*.yml) ;;
    *) continue ;;
  esac
  [ -f "$path" ] || continue

  hits=$(grep -nF -e "$tab" -- "$path")
  if [ -n "$hits" ]; then
    while IFS= read -r hit; do
      printf '%s: line %s: tab character found\n' "$path" "${hit%%:*}"
      failed=1
    done <<< "$hits"
  fi
done < <(git ls-files -z)

if [ "$failed" -ne 0 ]; then
  exit 1
fi

echo "OK yaml-tabs"
exit 0
