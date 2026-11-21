#!/usr/bin/env bash
# Enforces that every git-tracked *.sh file starts with a #! shebang line.
set -u

cd "$(git rev-parse --show-toplevel)" || exit 1

problems=0

report() {
  printf '%s: %s\n' "$1" "$2"
  problems=$((problems + 1))
}

while IFS= read -r -d '' f; do
  case "$f" in
    *.sh) ;;
    *) continue ;;
  esac

  if [[ ! -f $f ]]; then
    report "$f" "file missing from worktree"
    continue
  fi

  first=
  IFS= read -r first < "$f" || true
  if [[ $first != '#!'* ]]; then
    report "$f" "first line does not start with #!"
  fi
done < <(git ls-files -z)

if (( problems == 0 )); then
  echo "OK shebangs"
  exit 0
fi

echo "$problems problem(s) found" >&2
exit 1
