#!/usr/bin/env bash
# Backup of irreplaceable state (spec 07 part B) to an encrypted restic repository outside the WSL disk.
# Each app is scaled to zero while its PVC is read through a read-only helper pod, so SQLite files are consistent.
# Ollama model weights are excluded (re-pullable). Usage: scripts/backup.sh   (env overrides below)
set -euo pipefail

REPO="${RESTIC_REPOSITORY:-/mnt/c/Users/danth/Backups/dsm-shai/restic}"
PWFILE="${RESTIC_PASSWORD_FILE:-$HOME/.config/restic/password}"
AGE_KEY="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
RESTIC="${RESTIC:-$HOME/.local/bin/restic}"
MIN_FREE_GB="${MIN_FREE_GB:-20}"      # abort below this much free space on the destination
MAX_REPO_GB="${MAX_REPO_GB:-30}"      # warn above this raw repository size
HELPER_IMAGE="docker.io/litellm/litellm:1.109.1@sha256:11175975a3093e05e92faee2fe2fe3412a3ae2fcaa849eb0fe25d5f0d8bcb2e9"
STATUS_DIR="${STATUS_DIR:-$HOME/.local/state/dsm-shai}"

export RESTIC_REPOSITORY="$REPO" RESTIC_PASSWORD_FILE="$PWFILE"
log() { echo "$(date -Is) $*"; }
fail() { log "ERROR: $*"; exit 1; }

# ---- preflight: refuse to run without the keys or with too little space
[ -r "$PWFILE" ] || fail "restic password file missing: $PWFILE (store it outside git)"
[ -r "$AGE_KEY" ] || fail "age key missing: $AGE_KEY (refusing to run without it)"
[ -x "$RESTIC" ] || fail "restic not found at $RESTIC"
mkdir -p "$(dirname "$REPO")" "$STATUS_DIR"
free_gb=$(df -BG --output=avail "$(dirname "$REPO")" | tail -1 | tr -dc '0-9')
[ "$free_gb" -ge "$MIN_FREE_GB" ] || fail "only ${free_gb} GB free on the destination (need ${MIN_FREE_GB} GB)"
log "destination free: ${free_gb} GB"
if ! "$RESTIC" cat config >/dev/null 2>&1; then
  log "initialising repository"
  "$RESTIC" init
fi

# ---- restore the app and clean up even on failure (script-level EXIT trap)
CUR_NS=""; CUR_DEPLOY=""; CUR_HELPER=""
on_exit() {
  if [ -n "$CUR_HELPER" ]; then kubectl -n "$CUR_NS" delete pod "$CUR_HELPER" --ignore-not-found >/dev/null 2>&1 || true; fi
  if [ -n "$CUR_DEPLOY" ]; then kubectl -n "$CUR_NS" scale deploy/"$CUR_DEPLOY" --replicas=1 >/dev/null 2>&1 || true; fi
}
trap on_exit EXIT

# ---- one PVC: quiesce the app, stream its data through a read-only helper, restore the app
backup_pvc() {  # name namespace deployment selector pvc mountpath
  local name=$1 ns=$2 deploy=$3 selector=$4 pvc=$5 path=$6
  local helper="backup-${name}"
  CUR_NS=$ns; CUR_DEPLOY=$deploy; CUR_HELPER=$helper
  log "[$name] quiescing $ns/$deploy"
  kubectl -n "$ns" scale deploy/"$deploy" --replicas=0 >/dev/null
  kubectl -n "$ns" wait --for=delete pod -l "$selector" --timeout=300s >/dev/null 2>&1 || true
  kubectl -n "$ns" delete pod "$helper" --ignore-not-found >/dev/null
  kubectl -n "$ns" run "$helper" --restart=Never --image="$HELPER_IMAGE" \
    --overrides="$(printf '{"spec":{"containers":[{"name":"h","image":"%s","command":["sleep","900"],"volumeMounts":[{"name":"d","mountPath":"%s","readOnly":true}]}],"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"%s","readOnly":true}}]}}' "$HELPER_IMAGE" "$path" "$pvc")" >/dev/null
  kubectl -n "$ns" wait --for=condition=Ready pod/"$helper" --timeout=300s >/dev/null
  kubectl -n "$ns" exec "$helper" -- tar -C "$path" -cf - . \
    | "$RESTIC" backup --stdin --stdin-filename "$name.tar" --tag "$name" --quiet
  kubectl -n "$ns" delete pod "$helper" --ignore-not-found >/dev/null
  CUR_HELPER=""
  log "[$name] backed up; restarting $ns/$deploy"
  kubectl -n "$ns" scale deploy/"$deploy" --replicas=1 >/dev/null
  kubectl -n "$ns" rollout status deploy/"$deploy" --timeout=600s >/dev/null
  CUR_DEPLOY=""
}

backup_pvc hermes      hermes      hermes      "app.kubernetes.io/name=hermes"      hermes-home    /opt/data
backup_pvc openviking  openviking  openviking  "app.kubernetes.io/name=openviking"  openviking-data /app/.openviking
backup_pvc open-webui  open-webui  open-webui  "app.kubernetes.io/name=open-webui"  open-webui-data /app/backend/data
backup_pvc grafana     monitoring  kube-prometheus-stack-grafana "app.kubernetes.io/name=grafana" kube-prometheus-stack-grafana /var/lib/grafana

# ---- LiteLLM Postgres: logical dump (consistent without stopping the app)
log "[litellm-postgres] pg_dump"
kubectl -n litellm exec postgres-0 -- pg_dump -U litellm -d litellm -Fc \
  | "$RESTIC" backup --stdin --stdin-filename litellm.dump --tag litellm-postgres --quiet

# ---- cluster state that is not in git: Istio CA and config, the SOPS age key secret, the age key itself
log "[istio + keys]"
kubectl -n istio-system get secret istio-ca-secret -o yaml \
  | "$RESTIC" backup --stdin --stdin-filename istio-ca-secret.yaml --tag istio --quiet
kubectl -n istio-system get configmap -o yaml \
  | "$RESTIC" backup --stdin --stdin-filename istio-configmaps.yaml --tag istio --quiet
kubectl -n flux-system get secret sops-age -o yaml \
  | "$RESTIC" backup --stdin --stdin-filename sops-age.yaml --tag keys --quiet
"$RESTIC" backup --stdin --stdin-filename age-keys.txt --tag keys --quiet < "$AGE_KEY"

# ---- retention and size
log "[retention]"
"$RESTIC" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 3 --prune --quiet
size_gb=$("$RESTIC" stats --mode raw-data --json | python3 -c 'import sys,json;print(round(json.load(sys.stdin)["total_size"]/2**30,2))')
log "repository raw size: ${size_gb} GiB (warn above ${MAX_REPO_GB} GiB)"
awk -v s="$size_gb" -v m="$MAX_REPO_GB" 'BEGIN{exit !(s>m)}' && log "WARNING: repository above ${MAX_REPO_GB} GiB"

date -Is > "$STATUS_DIR/last-success"
log "backup complete"
