#!/bin/bash
# Read-only status of the swarm and the cluster it runs on: infrastructure, what is running, what is queued,
# open swarm PRs, the most recent outcomes, and when the next maintainer tick and health check run.
# Nothing is changed. Used by the swarm-status skill (.claude/skills/swarm-status/SKILL.md).
# Usage: bash scripts/swarm-status.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
KUBECTL=${KUBECTL:-kubectl}
hermes_sh() { timeout 60 $KUBECTL -n hermes exec deploy/hermes -c hermes -- sh -c "$1" 2>/dev/null | grep -v 'install out of sync'; }
section() { echo; echo "== $1"; }

section "Infrastructure"
if ! timeout 30 $KUBECTL get nodes >/dev/null 2>&1; then
  echo "  API server unreachable; the rest of the cluster checks are skipped"
else
  nodes=$(timeout 30 $KUBECTL get nodes --no-headers 2>/dev/null | awk '{print $1"="$2}' | tr '\n' ' ')
  echo "  nodes: $nodes"
  notready=$(timeout 90 flux get kustomizations -A --no-header 2>/dev/null | awk '$5 != "True" {print $2}' | tr '\n' ' ')
  [ -z "$notready" ] && echo "  flux: all kustomizations Ready" || echo "  flux: NOT READY: $notready"
  for d in "hermes hermes" "litellm litellm" "ollama ollama" "openviking openviking" "egress-proxy squid" "monitoring prometheus-kube-prometheus-stack-prometheus"; do
    set -- $d
    r=$(timeout 30 $KUBECTL -n "$1" get deploy "$2" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
    [ -z "$r" ] && r=$(timeout 30 $KUBECTL -n "$1" get statefulset "$2" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
    echo "  $1/$2: ready replicas ${r:-0}"
  done
  bad=$(timeout 60 $KUBECTL get pods -A --no-headers 2>/dev/null | awk '$4 != "Running" && $4 != "Completed" && $2 !~ /^repo-maintainer-/ && $2 !~ /^openviking-extraction-watch-/ {print $1"/"$2" "$4}' | tr '\n' ';')
  [ -z "$bad" ] && echo "  pods: none unhealthy" || echo "  pods not Running/Completed: $bad"
  xwatch=$(timeout 60 $KUBECTL -n openviking get pods --no-headers 2>/dev/null | awk '$2 ~ /^openviking-extraction-watch-/ && $3 != "Running" {print $1}' | tail -1)
  [ -n "$xwatch" ] && echo "  openviking extraction watch (last job): $(timeout 60 $KUBECTL -n openviking logs "$xwatch" --tail=1 2>/dev/null | cut -c1-160)"
  unenrolled=$(bash scripts/mesh-enrolment.sh 2>/dev/null | grep -c '^NOT ENROLLED' || true)
  [ "$unenrolled" -eq 0 ] && echo "  mesh: every running ambient pod is enrolled" || echo "  mesh: $unenrolled pod(s) not enrolled by ztunnel (make mesh-enrolment)"
  susp=$(timeout 30 $KUBECTL -n hermes get cronjob repo-maintainer -o jsonpath='{.spec.suspend}' 2>/dev/null)
  echo "  maintainer CronJob: schedule */15, suspended=${susp:-unknown}"
  cfg=$(hermes_sh 'echo "SWARM_REPO_WORK=$SWARM_REPO_WORK MAINT_MODE_DEFAULT=$MAINT_MODE_DEFAULT"')
  echo "  config: ${cfg:-unavailable}"
  switches=$(hermes_sh 'for f in /opt/data/swarm/disabled /opt/data/claude-haiku/disabled /opt/data/ESTOP; do [ -e "$f" ] && echo "$f"; done' | tr '\n' ' ')
  [ -z "$switches" ] && echo "  kill switches: none set" || echo "  kill switches SET: $switches"
  gh_code=$(hermes_sh 'curl -sS -m 20 -o /dev/null -w "%{http_code}" https://api.github.com/zen 2>&1')
  echo "  GitHub from hermes (through Squid): HTTP ${gh_code:-no answer}"
fi

section "Running now"
running=$(timeout 60 $KUBECTL -n hermes get pods -l app.kubernetes.io/component=repo-maintainer --no-headers 2>/dev/null | awk '$3 == "Running" {print $1" (age "$5")"}')
[ -n "$running" ] && echo "  maintainer job: $running" || echo "  maintainer job: none running"
locks=$(hermes_sh 'ls /opt/data/swarm/locks 2>/dev/null | tr "\n" " "')
[ -n "${locks// /}" ] && echo "  swarm locks held: $locks" || echo "  swarm locks held: none"
lastrun=$(hermes_sh 'ls -t /opt/data/swarm/runs 2>/dev/null | head -1')
echo "  latest swarm run: ${lastrun:-none}"

section "Queued tasks (on main, [swarm] and not started)"
queued=$(grep -E '^\s*- \[ \] \[swarm\]' .specter/tasklist.md | sed -E 's/^\s*- \[ \] \[swarm\] \*\*([^*]*)\*\*.*/\1/' | sed -E 's/:\s*$//')
if [ -z "$queued" ]; then echo "  none"; else
  open_titles=$(gh pr list --state open --json number,title,headRefName --jq '.[] | select(.headRefName|startswith("swarm/")) | "\(.number)\t\(.title)"' 2>/dev/null)
  n=0
  while IFS= read -r name; do
    n=$((n+1)); pr=$(echo "$open_titles" | grep -F -- "$name" | head -1 | cut -f1)
    if [ -n "$pr" ]; then echo "  $n. $name  [in review: PR #$pr]"; else echo "  $n. $name"; fi
  done <<<"$queued"
  echo "  total queued on main: $n (one of them may already have an open PR)"
fi

section "Open swarm PRs"
gh pr list --state open --json number,title,headRefName --jq '.[] | select(.headRefName|startswith("swarm/")) | "  #\(.number) \(.title)"' 2>/dev/null | sed -n '1,10p'
[ -z "$(gh pr list --state open --json headRefName --jq '.[]|select(.headRefName|startswith("swarm/"))|.headRefName' 2>/dev/null)" ] && echo "  none"

section "Recent outcomes"
hermes_sh 'tail -4 /opt/data/maintainer/digest.log 2>/dev/null' | sed 's/^/  /' | cut -c1-200
echo "  (swarm digest)"; hermes_sh 'tail -3 /opt/data/swarm/digest.log 2>/dev/null' | sed 's/^/  /' | cut -c1-200

section "Next steps"
now=$(date -u +%s)
next_q=$(( (now / 900 + 1) * 900 ))
echo "  next maintainer tick (every 15 min, UTC): $(date -u -d @$next_q '+%Y-%m-%d %H:%M UTC') in $(( (next_q - now) / 60 )) min"
echo "  per tick: merges maintainer-approved swarm PRs, then starts repo-work on the first queued task if no swarm PR is open"
echo "  health check (every 30 min): $(systemctl --user list-timers dsm-shai-health.timer --no-legend --no-pager 2>/dev/null | head -1 | awk '{print $1" "$2" "$3" "$4" ("$5" "$6")"}')"
echo "  legacy Hermes cron swarm-repo-work: paused (the maintainer starts repo-work)"
