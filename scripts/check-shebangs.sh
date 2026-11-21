#!/usr/bin/env bash
# CI check: enforces that every tracked file whose name ends in .sh starts with a #! line.
set -u

problems=0

while IFS= read -r -d '' path; do
  if [[ $path == *.sh ]]; then
    if [[ ! -f $path || ! -r $path ]]; then
      printf '%s: not a readable regular file\n' "$path"
      problems=$((problems + 1))
      continue
    fi
    if [[ $(head -c 2 -- "$path") != '#!' ]]; then
      printf '%s: first line does not start with #!\n' "$path"
      problems=$((problems + 1))
    fi
  fi
done < <(git ls-files -z)

if (( problems > 0 )); then
  exit 1
fi

printf 'OK shebangs\n'
exit 0
