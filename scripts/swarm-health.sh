#!/bin/bash
# Swarm and cluster health check, run every 30 minutes by the dsm-shai-health systemd user timer (scripts/systemd/).
# It checks the things that stop the repo-work swarm and the maintainer from starting on their next timer:
# Flux, the Hermes pod, the maintainer CronJob and its last digest line, repo-work failures and open swarm PRs,
# the kill switches, GitHub reachability from Hermes through Squid, and ztunnel enrolment.
# Auto-remediation is limited to the one documented, idempotent fix: deleting ambient pods that ztunnel did not enrol
# (scripts/mesh-enrolment.sh --apply), capped at MAX_AUTO_DELETE pods per run. Everything else is reported with the action to take.
# Each run appends to $STATE_DIR/swarm-health.log. Exit 0 = healthy (or fixed), 1 = problems remain, 2 = cannot run.
# Usage: bash scripts/swarm-health.sh [--no-fix]
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
KUBECTL=${KUBECTL:-kubectl}
STATE_DIR=${STATE_DIR:-$HOME/.local/state/dsm-shai}
MAX_AUTO_DELETE=${MAX_AUTO_DELETE:-3}
fix=1
[ "${1:-}" = "--no-fix" ] && fix=0
mkdir -p "$STATE_DIR" || exit 2
LOG="$STATE_DIR/swarm-health.log"
problems=0; fixed=0
ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
out() { echo "$ts $*" | tee -a "$LOG"; }
ok()   { out "OK    $*"; }
warn() { out "WARN  $*"; problems=$((problems+1)); }
fixnote() { out "FIXED $*"; fixed=$((fixed+1)); }
hermes_sh() { timeout 60 $KUBECTL -n hermes exec deploy/hermes -c hermes -- sh -c "$1" 2>/dev/null | grep -v 'install out of sync'; }

if ! timeout 30 $KUBECTL get nodes >/dev/null 2>&1; then
  out "FAIL  API server unreachable; nothing else checked"
  exit 2
fi

# 1. Flux: every kustomization Ready
notready=$(timeout 90 flux get kustomizations -A --no-header 2>/dev/null | awk '$5 != "True" {print $2}')
if [ -z "$notready" ]; then ok "flux: all kustomizations Ready"; else warn "flux: not Ready: $(echo $notready) (check: flux get kustomizations -A; flux reconcile kustomization <name>)"; fi

# 2. Hermes pod ready
hready=$(timeout 30 $KUBECTL -n hermes get deploy hermes -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
if [ "${hready:-0}" = "1" ]; then ok "hermes: deployment ready"; else warn "hermes: not ready (kubectl -n hermes get pods; kubectl -n hermes describe deploy hermes)"; fi

# 3. Maintainer CronJob: not suspended and ran within the last 20 minutes (it runs every 15)
susp=$(timeout 30 $KUBECTL -n hermes get cronjob repo-maintainer -o jsonpath='{.spec.suspend}' 2>/dev/null)
last=$(timeout 30 $KUBECTL -n hermes get cronjob repo-maintainer -o jsonpath='{.status.lastScheduleTime}' 2>/dev/null)
if [ "$susp" = "true" ]; then
  warn "maintainer: CronJob is suspended; nothing will start on the timer (kubectl -n hermes patch cronjob repo-maintainer -p '{\"spec\":{\"suspend\":false}}' or the owner's Flux change)"
elif [ -z "$last" ]; then
  warn "maintainer: CronJob has never scheduled a run"
else
  age=$(( $(date -u +%s) - $(date -u -d "$last" +%s) ))
  if [ "$age" -gt 1200 ]; then warn "maintainer: last scheduled run was $((age/60)) min ago (expected every 15)"; else ok "maintainer: scheduled, last run $((age/60)) min ago"; fi
fi

# 4. Maintainer and repo-work outcome from the Hermes digest logs (the last line of each)
mlast=$(hermes_sh 'tail -1 /opt/data/maintainer/digest.log 2>/dev/null')
if [ -z "$mlast" ]; then
  warn "maintainer: no digest line yet"
elif echo "$mlast" | grep -q 'failed'; then
  warn "maintainer: last run failed: $(echo "$mlast" | cut -c1-200)"
else
  ok "maintainer: last run ok ($(echo "$mlast" | cut -c1-120))"
fi
rlast3=$(hermes_sh 'tail -3 /opt/data/swarm/digest.log 2>/dev/null')
rfail=$(echo "$rlast3" | grep -c 'repo-work failed')
if [ "$rfail" -ge 3 ]; then
  warn "repo-work: last 3 runs all failed ($(echo "$rlast3" | tail -1 | cut -c1-160)); read /opt/data/swarm/runs/ for the verifier output and fix the task format, or mark the task [needs-owner]"
else
  ok "repo-work: $rfail of last 3 runs failed"
fi

# 5. Kill switches and live config
switches=$(hermes_sh 'for f in /opt/data/swarm/disabled /opt/data/claude-haiku/disabled /opt/data/ESTOP; do [ -e "$f" ] && echo "$f"; done')
if [ -n "$switches" ]; then warn "kill switch set: $(echo $switches) (remove the file to resume)"; else ok "kill switches: none set"; fi
rw=$(hermes_sh 'echo $SWARM_REPO_WORK')
mm=$(hermes_sh 'echo $MAINT_MODE_DEFAULT')
if [ "$rw" = "1" ] && [ -n "$mm" ] && [ "$mm" != "off" ]; then ok "config: SWARM_REPO_WORK=1, MAINT_MODE_DEFAULT=$mm"; else warn "config: SWARM_REPO_WORK='$rw' MAINT_MODE_DEFAULT='$mm' (expected 1 and merge or merge-and-run)"; fi

# 6. Open swarm PRs: more than one means the queue is stuck behind a PR the maintainer has not merged
open=$(timeout 60 gh pr list --state open --json headRefName --jq '[.[] | select(.headRefName | startswith("swarm/"))] | length' 2>/dev/null)
if [ -z "$open" ]; then warn "github: cannot list PRs (gh auth or GitHub outage)"
elif [ "$open" -gt 1 ]; then warn "swarm: $open open swarm/ PRs; the queue waits on the maintainer (check gh pr list and the maintainer digest)"
else ok "swarm: open swarm PRs: $open"; fi

# 7. GitHub reachable from Hermes through Squid
gh_code=$(hermes_sh 'curl -sS -m 20 -o /dev/null -w "%{http_code}" https://api.github.com/zen 2>&1')
if [ "$gh_code" = "200" ]; then ok "egress: api.github.com reachable from hermes"; else warn "egress: api.github.com from hermes returned '$gh_code' (see deploy/istio/README.md, Restart recovery)"; fi

# 8. ztunnel enrolment: pods that were already running when ztunnel restarted are unenrolled (plaintext, rejected by STRICT mTLS)
unenrolled=$(bash scripts/mesh-enrolment.sh 2>&1 | grep '^NOT ENROLLED' || true)
n=$(echo "$unenrolled" | grep -c 'NOT ENROLLED' || true)
if [ "$n" -eq 0 ]; then
  ok "mesh: every running ambient pod is enrolled"
elif [ "$fix" = 1 ] && [ "$n" -le "$MAX_AUTO_DELETE" ]; then
  warn "mesh: $n unenrolled pod(s); deleting them so they re-enrol (runbook fix)"
  echo "$unenrolled" | while read -r line; do out "      $line"; done
  bash scripts/mesh-enrolment.sh --apply 2>&1 | grep 'deleted' | while read -r line; do out "      $line"; done
  fixnote "mesh: deleted $n pod(s); recheck next run"
else
  warn "mesh: $n unenrolled pod(s), above the auto-fix cap of $MAX_AUTO_DELETE or --no-fix; run make mesh-enrolment and decide"
  echo "$unenrolled" | while read -r line; do out "      $line"; done
fi

# 9. Pods that are not Running or Completed. Maintainer job pods are skipped: a failed maintainer run is already reported in step 4.
bad=$(timeout 60 $KUBECTL get pods -A --no-headers 2>/dev/null | awk '$4 != "Running" && $4 != "Completed" && $2 !~ /^repo-maintainer-/ {print $1"/"$2" "$4}' | head -20)
if [ -z "$bad" ]; then ok "pods: none unhealthy"; else warn "pods not Running or Completed: $(echo $bad | tr '\n' ';')"; fi

out "SUMMARY problems=$problems fixed=$fixed"
[ "$problems" -eq 0 ] && exit 0
exit 1
