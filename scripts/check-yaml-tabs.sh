#!/usr/bin/env bash
# Enforces that YAML files contain no tab characters, because tabs are not allowed in YAML indentation.
set -u

cd "$(git rev-parse --show-toplevel)" || exit 1

fail=0

while IFS= read -r -d '' path; do
  case "$path" in
    *.yaml|*.yml) ;;
    *) continue ;;
  esac

  rc=0
  matches=$(grep -n -a -- $'\t' "$path") || rc=$?
  if [ "$rc" -eq 1 ]; then
    # No tab characters in this file.
    continue
  fi
  if [ "$rc" -gt 1 ]; then
    printf '%s: could not read file\n' "$path"
    fail=1
    continue
  fi

  while IFS= read -r m; do
    printf '%s: line %s contains a tab character\n' "$path" "${m%%:*}"
    fail=1
  done <<< "$matches"
done < <(git ls-files -z)

if [ "$fail" -ne 0 ]; then
  exit 1
fi

echo 'OK yaml-tabs'
exit 0
