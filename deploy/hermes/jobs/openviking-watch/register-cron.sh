#!/bin/sh
# Print (or run) the Hermes cron registration for the OpenViking link watch, PAUSED and agent-less (spec 11 convention).
# Hermes accepts only a script FILENAME under /opt/data/scripts/, so --apply first writes a one-line wrapper there that
# runs the read-only copy under /opt/jobs/openviking-watch. Schedule: OV_WATCH_CRON (default every 30 minutes).
# Resume only after a clean live run:  hermes cron resume <id>
SCHEDULE="${OV_WATCH_CRON:-*/30 * * * *}"
SCRIPTS="${HERMES_SCRIPTS:-/opt/data/scripts}"
FILE="openviking-watch.sh"
CMD="hermes cron create '$SCHEDULE' --name openviking-watch --script $FILE --interpreter bash --no-agent --paused --paused-reason 'registered paused (memory link watch)'"
if [ "${1:-}" = "--apply" ]; then
  mkdir -p "$SCRIPTS" && printf '#!/bin/bash\nexec python3 -I /opt/jobs/openviking-watch/watch.py "$@"\n' > "$SCRIPTS/$FILE" && chmod 755 "$SCRIPTS/$FILE" && eval "$CMD"
else
  echo "# writes $SCRIPTS/$FILE (exec python3 -I /opt/jobs/openviking-watch/watch.py), then:"; echo "$CMD"
fi
