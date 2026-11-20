#!/bin/bash
# Repo maintainer wrapper (spec 16). Usage: run.sh [--plan] [--repo owner/name] | --preflight | revert <owner/name> <pr>
# Scripts are mounted read-only at /opt/jobs/repo-maintainer (the swarm engine at /opt/jobs/swarm); state under /opt/data/maintainer.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
export MAINT_STATE="${MAINT_STATE:-/opt/data/maintainer}"
mkdir -p "$MAINT_STATE" 2>/dev/null
PY="${PYTHON:-python3}"
timeout "${MAINT_WALL_SECONDS:-7200}" "$PY" -I "$HERE/maintain.py" "$@" 2>&1 | "$PY" -I -c "
import sys; sys.path.insert(0,'${SWARM_DIR:-/opt/jobs/swarm}'); import lib
for l in sys.stdin: sys.stdout.write(lib.redact(l))"
exit "${PIPESTATUS[0]}"
