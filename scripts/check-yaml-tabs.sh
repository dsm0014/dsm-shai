#!/usr/bin/env bash
# Enforces that no tracked .yaml or .yml file contains a tab character, since tabs are not allowed in YAML indentation.

status=0
while IFS= read -r -d '' path; do
  case "$path" in
    *.yaml|*.yml)
      [ -f "$path" ] || continue
      while IFS= read -r line; do
        printf '%s: tab character at line %s\n' "$path" "$line"
        status=1
      done < <(grep -n -F $'\t' -- "$path" | cut -d: -f1)
      ;;
    *)
      continue
      ;;
  esac
done < <(git ls-files -z)

if [ "$status" -eq 0 ]; then
  printf 'OK yaml-tabs\n'
fi
exit "$status"
