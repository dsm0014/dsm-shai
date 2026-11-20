#!/bin/bash
# Run every repository check: scripts/check-*.sh (bash) and scripts/check-*.py (python3 -I) except this file. Each check prints its own
# findings and exits non-zero on a problem; every check runs even if an earlier one failed. Part of `make test`, so the repo
# maintainer runs it in a fresh clone of every pull request before it can merge. Add a check by adding a script here.
# Usage: bash scripts/check-all.sh [name-fragment]     (a fragment runs only the checks whose file name contains it)
cd "$(dirname "$0")/.." || exit 2
fail=0; ran=0; failed=()
for f in scripts/check-*.sh scripts/check-*.py; do
  [ -f "$f" ] || continue
  case "$f" in scripts/check-all.sh) continue;; esac
  case "$f" in *"${1:-}"*) ;; *) continue;; esac
  ran=$((ran+1))
  case "$f" in *.py) cmd=(python3 -I "$f");; *) cmd=(bash "$f");; esac
  if out="$(timeout "${CHECK_TIMEOUT:-120}" "${cmd[@]}" 2>&1)"; then
    echo "PASS  $f"
  else
    echo "FAIL  $f"; printf '%s\n' "$out" | head -40 | sed 's/^/      /'; fail=1; failed+=("$f")
  fi
done
echo "checks: $ran run, ${#failed[@]} failed"
exit $fail
