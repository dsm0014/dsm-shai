#!/bin/bash
# Run a swarm task: run.sh [--dry-run]. Copy this file next to your task.yaml. Lock, caps and kill switches are in swarm.py.
HERE="$(cd "$(dirname "$0")" && pwd)"
exec bash /opt/jobs/swarm/run.sh "${SWARM_TASK:-$HERE/task.yaml}" "$@"
