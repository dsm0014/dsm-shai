#!/usr/bin/env bash
# Enforces LF line endings in tracked .sh, .py, .yaml, .yml, .md and .json files, because CRLF line endings break shell scripts under WSL.

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 1

cr="$(printf '\015')"
failed=0

while IFS= read -r -d '' path; do
  case "$path" in
    *.sh|*.py|*.yaml|*.yml|*.md|*.json) ;;
    *) continue ;;
  esac

  if [[ ! -f "$path" ]]; then
    continue
  fi

  if LC_ALL=C grep -q -- "$cr" "$path"; then
    printf '%s: file has CRLF (carriage return) line endings and should use LF\n' "$path"
    failed=1
  fi
done < <(git ls-files -z)

if [[ "$failed" -ne 0 ]]; then
  exit 1
fi

echo "OK check-line-endings"
exit 0
