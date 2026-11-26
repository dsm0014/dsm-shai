#!/usr/bin/env bash
# Enforces that the first line of every git-tracked file whose name ends in .sh starts with #!.
cd "$(dirname "$0")/.." || exit 1

if ! git ls-files -z >/dev/null; then
  echo "git ls-files failed" >&2
  exit 1
fi

failed=0
while IFS= read -r -d '' f; do
  [[ $f == *.sh ]] || continue
  if ! first=$(head -n 1 -- "$f" 2>/dev/null); then
    printf '%s: unreadable file\n' "$f"
    failed=1
    continue
  fi
  if [[ $first != '#!'* ]]; then
    printf '%s: missing shebang\n' "$f"
    failed=1
  fi
done < <(git ls-files -z)

if (( failed )); then
  exit 1
fi
echo "OK shebang-check"
exit 0
