#!/bin/sh
# Print (or run) the Hermes cron registration for the nightly job. Nothing runs this automatically.
# Registered PAUSED and agent-less: cron runs run.sh directly, the model is only used inside the job's steps.
# Hermes accepts only a script FILENAME under /opt/data/scripts/ (an absolute path is refused), so --apply first writes a
# one-line wrapper there that runs the read-only copy under /opt/jobs. Verified for the swarm job, 2026-11-19.
# Resume only after the fork rehearsal passes (spec 11):  hermes cron resume <id>
# Usage: register-cron.sh [--apply]
SCHEDULE="${NIGHTLY_CRON:-30 2 * * *}"
SCRIPTS="${HERMES_SCRIPTS:-/opt/data/scripts}"
FILE="nightly-specter.sh"
CMD="hermes cron create '$SCHEDULE' --name nightly-specter --script $FILE --interpreter bash --no-agent --paused --paused-reason 'rehearsal pending (spec 11)'"
if [ "${1:-}" = "--apply" ]; then
  mkdir -p "$SCRIPTS" && printf '#!/bin/bash\nexec bash /opt/jobs/nightly-specter/run.sh "$@"\n' > "$SCRIPTS/$FILE" && chmod 755 "$SCRIPTS/$FILE" && eval "$CMD"
else
  echo "# writes $SCRIPTS/$FILE (exec bash /opt/jobs/nightly-specter/run.sh), then:"; echo "$CMD"
fi
