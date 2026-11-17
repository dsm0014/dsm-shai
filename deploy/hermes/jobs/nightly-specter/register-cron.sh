#!/bin/sh
# Print (or run) the Hermes cron registration for the nightly job. Nothing runs this automatically.
# Registered PAUSED and agent-less: cron runs run.sh directly, the model is only used inside the job's steps.
# Resume only after the fork rehearsal passes (spec 11):  hermes cron resume <id>
# Verify in the pod that --script accepts a path under /opt/jobs (it may expect HERMES_HOME/scripts); see README.
# Usage: register-cron.sh [--apply]
SCHEDULE="${NIGHTLY_CRON:-30 2 * * *}"
CMD="hermes cron create '$SCHEDULE' --name nightly-specter --script /opt/jobs/nightly-specter/run.sh --interpreter bash --no-agent --paused --paused-reason 'rehearsal pending (spec 11)'"
if [ "${1:-}" = "--apply" ]; then eval "$CMD"; else echo "$CMD"; fi
