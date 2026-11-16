#!/usr/bin/env bash
# Bootstraps Flux (spec 10) on a k3s cluster. Idempotent: re-running makes no changes.
#
#   1. Applies clusters/dsm-shai/flux-system (pinned controllers, public HTTPS GitRepository, self-sync).
#   2. Creates the sops-age Secret in flux-system from the age private key OUTSIDE the repo.
#      The key is read from SOPS_AGE_KEY_FILE (default ~/.config/sops/age/keys.txt) and never echoed.
#
# The age key is the sole protection for committed ciphertext. It is never committed (spec 07/10).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/versions.env"

log()  { printf '[bootstrap-flux] %s\n' "$*"; }
changed() { printf '[bootstrap-flux] CHANGED: %s\n' "$*"; }
die()  { printf '[bootstrap-flux] ERROR: %s\n' "$*" >&2; exit 1; }

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
command -v kubectl >/dev/null || die "kubectl not found; run scripts/10-tools.sh"
command -v flux >/dev/null    || die "flux not found; run scripts/10-tools.sh"
kubectl get nodes >/dev/null 2>&1 || die "cannot reach the k3s API (KUBECONFIG=$KUBECONFIG)"

AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
[ -r "$AGE_KEY_FILE" ] || die "age private key not readable at $AGE_KEY_FILE (set SOPS_AGE_KEY_FILE); refusing to continue"
grep -q '^AGE-SECRET-KEY-' "$AGE_KEY_FILE" || die "$AGE_KEY_FILE does not contain an age secret key"

# 1. Flux components and sync source. Two phases: the CRDs must exist before the GitRepository and
#    Kustomization objects can be created, so the components are applied and awaited first.
FLUX_DIR="$REPO_ROOT/clusters/dsm-shai/flux-system"
rc=0
kubectl diff -k "$FLUX_DIR" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 0 ]; then
  log "flux-system already matches the repo"
else
  if ! kubectl get crd kustomizations.kustomize.toolkit.fluxcd.io >/dev/null 2>&1; then
    kubectl apply -f "$FLUX_DIR/gotk-components.yaml" >/dev/null
    kubectl wait --for=condition=established --timeout=2m \
      crd/kustomizations.kustomize.toolkit.fluxcd.io \
      crd/gitrepositories.source.toolkit.fluxcd.io \
      crd/helmreleases.helm.toolkit.fluxcd.io \
      crd/helmrepositories.source.toolkit.fluxcd.io >/dev/null \
      || die "Flux CRDs did not become established"
  fi
  kubectl apply -k "$FLUX_DIR" >/dev/null
  changed "applied flux-system components from $FLUX_DIR"
fi

# 2. sops-age Secret. Built client-side and applied; the key never appears in argv or logs.
if kubectl -n flux-system get secret sops-age >/dev/null 2>&1; then
  current=$(kubectl -n flux-system get secret sops-age -o jsonpath='{.data.age\.agekey}' | base64 -d)
  desired=$(cat "$AGE_KEY_FILE")
  if [ "$current" = "$desired" ]; then
    log "sops-age secret already current"
  else
    kubectl -n flux-system create secret generic sops-age --from-file=age.agekey="$AGE_KEY_FILE" \
      --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    changed "updated sops-age secret"
  fi
else
  kubectl -n flux-system create secret generic sops-age --from-file=age.agekey="$AGE_KEY_FILE" >/dev/null
  changed "created sops-age secret"
fi

# 3. Wait for the controllers.
for deploy in source-controller kustomize-controller helm-controller; do
  kubectl -n flux-system rollout status "deploy/$deploy" --timeout=5m >/dev/null \
    || die "deploy/$deploy did not become ready; see kubectl -n flux-system describe deploy/$deploy"
done
log "source, kustomize and helm controllers are ready"
log "run 'flux get kustomizations' to watch the stage reconciliation"
