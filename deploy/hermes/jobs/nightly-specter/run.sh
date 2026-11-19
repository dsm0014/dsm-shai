#!/bin/bash
# Nightly specter job wrapper (spec 11). Order: disabled check, lock, configuration, kill switches, one run per night.
# Usage: run.sh [--dry-run] [--preflight]
# Scripts are mounted read-only at /opt/jobs/nightly-specter; state is written under /opt/data/nightly-specter.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="${NIGHTLY_STATE:-/opt/data/nightly-specter}"
export NIGHTLY_STATE="$STATE"
PY="${PYTHON:-python3}"
DRY=""; PRE=""
for a in "$@"; do case "$a" in --dry-run) DRY="--dry-run";; --preflight) PRE=1;; esac; done

if [ -n "$PRE" ]; then   # which tools exist in this image; installs nothing
  rc=0
  mkdir -p "$STATE" 2>/dev/null   # the real run creates it too; preflight must not fail only because it is not there yet
  for t in "$PY" git flock curl timeout; do
    if command -v "$t" >/dev/null 2>&1; then echo "ok      $t"; else echo "MISSING $t"; rc=1; fi
  done
  command -v "${HERMES_BIN:-hermes}" >/dev/null 2>&1 && echo "ok      hermes" || { echo "MISSING hermes"; rc=1; }
  touch "$STATE/.w" 2>/dev/null && rm -f "$STATE/.w" && echo "ok      state dir writable ($STATE)" || { echo "MISSING writable $STATE"; rc=1; }
  exit $rc
fi

mkdir -p "$STATE/runs" || exit 1
audit() { "$PY" -I -c "import sys; sys.path.insert(0,'$HERE'); import lib; lib.audit({'status': sys.argv[1], 'reason': sys.argv[2], 'dry_run': bool('$DRY')}); lib.write_metrics()" "$1" "$2"; }

exec 9>"$STATE/lock"
if ! flock -n 9; then
  audit skipped "skipped: locked"; echo "skipped: locked"; exit 0
fi

if [ -z "${GITHUB_TOKEN:-}" ] || [ -z "${NIGHTLY_REPO:-}" ]; then
  audit not_configured "not configured"; "$PY" -I -c "import sys; sys.path.insert(0,'$HERE'); import lib; lib.digest('not configured (GITHUB_TOKEN or NIGHTLY_REPO missing)')"
  echo "not configured"; exit 0
fi

# Isolation guard: the token reaches every repo, so only an allowlisted target may run (fails closed).
case ",${NIGHTLY_ALLOWED_REPOS:-}," in
  *",$NIGHTLY_REPO,"*) ;;
  *) audit refused "refused: NIGHTLY_REPO not in NIGHTLY_ALLOWED_REPOS"; echo "refused: NIGHTLY_REPO not in NIGHTLY_ALLOWED_REPOS" >&2; exit 2;;
esac

if [ -f "$STATE/disabled" ]; then
  audit skipped "skipped: disabled flag"; echo "skipped: disabled flag"; exit 0
fi

DAY="${NIGHTLY_TODAY:-$(date +%F)}"
if [ -z "$DRY" ] && [ -f "$STATE/runs/$DAY.json" ]; then
  audit skipped "one-PR-per-night limit"; echo "one-PR-per-night limit"; exit 0
fi

# GitHub is reached through the egress proxy only; interactive Hermes is not proxied.
if [ -n "${NIGHTLY_HTTPS_PROXY:-}" ]; then
  export HTTPS_PROXY="$NIGHTLY_HTTPS_PROXY" https_proxy="$NIGHTLY_HTTPS_PROXY"
  export NO_PROXY="${NO_PROXY:-},.svc,.cluster.local,localhost,127.0.0.1" no_proxy="${NO_PROXY:-},.svc,.cluster.local,localhost,127.0.0.1"
fi

# Repo-side kill switch (.nightly-disabled on the default branch) is checked after the clone, inside orchestrate.py
timeout "${NIGHTLY_WALL_SECONDS:-5400}" "$PY" -I "$HERE/orchestrate.py" $DRY 2>&1 | "$PY" -I -c "
import sys; sys.path.insert(0,'$HERE'); import lib
for l in sys.stdin: sys.stdout.write(lib.redact(l))"
exit "${PIPESTATUS[0]}"
