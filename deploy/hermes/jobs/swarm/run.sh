#!/bin/bash
# Swarm job wrapper (spec 13). Usage: run.sh <task.yaml> [--dry-run]   |   run.sh --preflight
# Scripts are mounted read-only at /opt/jobs/swarm; state is written under /opt/data/swarm.
# The per-task lock (`skipped: locked`) and the kill switches live in swarm.py; this adds the wall clock and redaction.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
export SWARM_STATE="${SWARM_STATE:-/opt/data/swarm}"
PY="${PYTHON:-python3}"
mkdir -p "$SWARM_STATE" 2>/dev/null
if [ "${1:-}" = "--preflight" ]; then exec "$PY" -I "$HERE/swarm.py" --preflight; fi
[ -n "${1:-}" ] || { echo "usage: run.sh <task.yaml> [--dry-run]" >&2; exit 2; }
timeout "${SWARM_WALL_SECONDS:-7200}" "$PY" -I "$HERE/swarm.py" "$@" 2>&1 | "$PY" -I -c "
import sys; sys.path.insert(0,'$HERE'); import lib
for l in sys.stdin: sys.stdout.write(lib.redact(l))"
exit "${PIPESTATUS[0]}"
