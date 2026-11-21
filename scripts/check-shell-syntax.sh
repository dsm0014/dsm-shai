#!/usr/bin/env bash
# Checks that bash -n parses every tracked file whose name ends in .sh, and reports each file that fails to parse.
set -u

problems=0

while IFS= read -r -d '' f; do
  case "$f" in
    *.sh) ;;
    *) continue ;;
  esac
  err=$(bash -n -- "$f" 2>&1 >/dev/null)
  status=$?
  if [ "$status" -ne 0 ]; then
    problems=$((problems + 1))
    while IFS= read -r line || [ -n "$line" ]; do
      printf '%s: %s\n' "$f" "$line"
    done <<< "$err"
  fi
done < <(git ls-files -z)

if [ "$problems" -gt 0 ]; then
  exit 1
fi

echo "OK shell-syntax"
exit 0
