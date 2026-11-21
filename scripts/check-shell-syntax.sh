#!/usr/bin/env bash
# Enforces that every git-tracked file whose name ends in .sh parses with bash -n.
set -u

cd "$(git rev-parse --show-toplevel)" || exit 1

failures=0

while IFS= read -r -d '' file; do
  case "$file" in
    *.sh) ;;
    *) continue ;;
  esac

  err="$(bash -n -- "$file" 2>&1 >/dev/null)"
  status=$?
  if [ "$status" -ne 0 ]; then
    first_line="$(printf '%s\n' "$err" | head -n 1)"
    if [ -z "$first_line" ]; then
      first_line="bash -n failed"
    fi
    printf '%s: %s\n' "$file" "$first_line"
    failures=$((failures + 1))
  fi
done < <(git ls-files -z)

if [ "$failures" -gt 0 ]; then
  exit 1
fi

echo "OK shell-syntax"
exit 0
