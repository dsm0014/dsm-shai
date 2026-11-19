#!/bin/sh
# Print (or run) the Hermes cron registration for a swarm task, PAUSED and agent-less (spec 11 convention).
# Usage: register-cron.sh <task-name> [--apply]     Schedule: SWARM_CRON (default below). Resume with: hermes cron resume <id>
NAME="${1:?usage: register-cron.sh <task-name> [--apply]}"
SCHEDULE="${SWARM_CRON:-17 3 * * *}"
CMD="hermes cron create '$SCHEDULE' --name swarm-$NAME --script /opt/jobs/swarm-$NAME/run.sh --interpreter bash --no-agent --paused --paused-reason 'registered paused (spec 13)'"
if [ "${2:-}" = "--apply" ]; then eval "$CMD"; else echo "$CMD"; fi
