#!/bin/sh
# Print (or run) the Hermes cron registration for the repo maintainer, PAUSED and agent-less.
# Hermes accepts only a script FILENAME under /opt/data/scripts/, so --apply writes a one-line wrapper there.
# Usage: register-cron.sh [--apply]   Schedule: MAINT_CRON (default every 30 minutes). Resume: hermes cron resume <id>
SCHEDULE="${MAINT_CRON:-*/30 * * * *}"
SCRIPTS="${HERMES_SCRIPTS:-/opt/data/scripts}"
FILE="repo-maintainer.sh"
CMD="hermes cron create '$SCHEDULE' --name repo-maintainer --script $FILE --interpreter bash --no-agent --paused --paused-reason 'registered paused (spec 16)'"
if [ "${1:-}" = "--apply" ]; then
  mkdir -p "$SCRIPTS" && printf '#!/bin/bash\nexec bash /opt/jobs/repo-maintainer/run.sh "$@"\n' > "$SCRIPTS/$FILE" && chmod 755 "$SCRIPTS/$FILE" && eval "$CMD"
else
  echo "# writes $SCRIPTS/$FILE (exec bash /opt/jobs/repo-maintainer/run.sh), then:"; echo "$CMD"
fi
