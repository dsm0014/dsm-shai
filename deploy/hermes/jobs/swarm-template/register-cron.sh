#!/bin/sh
# Print (or run) the Hermes cron registration for a swarm task, PAUSED and agent-less (spec 11 convention).
# Hermes accepts only a script FILENAME under /opt/data/scripts/ (an absolute path is refused), so --apply first writes a
# one-line wrapper there that runs the read-only copy under /opt/jobs.
# Usage: register-cron.sh <job-name> [--apply]    (job-name "example" is /opt/jobs/swarm-example). Schedule: SWARM_CRON.
# Resume only after a clean live run:  hermes cron resume <id>
NAME="${1:?usage: register-cron.sh <job-name> [--apply]}"
SCHEDULE="${SWARM_CRON:-17 3 * * *}"
SCRIPTS="${HERMES_SCRIPTS:-/opt/data/scripts}"
FILE="swarm-$NAME.sh"
CMD="hermes cron create '$SCHEDULE' --name swarm-$NAME --script $FILE --interpreter bash --no-agent --paused --paused-reason 'registered paused (spec 13)'"
if [ "${2:-}" = "--apply" ]; then
  mkdir -p "$SCRIPTS" && printf '#!/bin/bash\nexec bash /opt/jobs/swarm-%s/run.sh "$@"\n' "$NAME" > "$SCRIPTS/$FILE" && chmod 755 "$SCRIPTS/$FILE" && eval "$CMD"
else
  echo "# writes $SCRIPTS/$FILE (exec bash /opt/jobs/swarm-$NAME/run.sh), then:"; echo "$CMD"
fi
