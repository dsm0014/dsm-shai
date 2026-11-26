#!/usr/bin/env bash
# Checks that the first line of every git-tracked file whose name ends in .sh starts with #!.
set -u

cd "$(git rev-parse --show-toplevel)" || exit 1

bad=0
while IFS= read -r -d '' f; do
  case $f in
    *.sh) ;;
    *) continue ;;
  esac
  if [ ! -r "$f" ]; then
    printf '%s: file is unreadable\n' "$f"
    bad=1
    continue
  fi
  first=''
  IFS= read -r first < "$f" || true
  case $first in
    '#!'*) ;;
    *)
      printf '%s: first line does not start with #!\n' "$f"
      bad=1
      ;;
  esac
done < <(git ls-files -z)

if [ "$bad" -ne 0 ]; then
  exit 1
fi
printf 'OK check-shebangs\n'
exit 0
