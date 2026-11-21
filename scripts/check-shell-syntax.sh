#!/usr/bin/env bash
# Enforces that every git-tracked file whose name ends in .sh parses with bash -n.
set -u

root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1

failed=0
while IFS= read -r -d '' path; do
  case "$path" in
    *.sh) ;;
    *) continue ;;
  esac
  if ! err=$(bash -n -- "$path" 2>&1 >/dev/null); then
    first=$(printf '%s\n' "$err" | head -n 1)
    if [ -z "$first" ]; then
      first="bash -n failed"
    fi
    printf '%s: %s\n' "$path" "$first"
    failed=1
  fi
done < <(git ls-files -z)

if [ "$failed" -ne 0 ]; then
  exit 1
fi

printf 'OK shell-syntax\n'
exit 0
