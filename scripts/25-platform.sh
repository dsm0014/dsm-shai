#!/usr/bin/env bash
# INTERIM (until spec 10): apply deploy/platform/ by hand, i.e. the namespaces, RuntimeClass nvidia and the
# NVIDIA device plugin that Flux will deliver once scripts/bootstrap-flux.sh exists. Idempotent. Run with sudo.
# Skips itself when Flux's HelmRelease CRD is present, so it never fights Flux. Delete this script when spec 10 lands.
# Flux's helm-controller adopts an existing release with the same name and namespace, so the later hand-off is clean.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
PLATFORM="$REPO_ROOT/deploy/platform"
RELEASE=nvidia-device-plugin
NS=nvidia-device-plugin
CHART_REPO=https://nvidia.github.io/k8s-device-plugin

for _ in $(seq 1 60); do kubectl get nodes >/dev/null 2>&1 && break; sleep 2; done
kubectl get nodes >/dev/null 2>&1 || die "cannot reach the k3s API; is k3s running?"

if kubectl get crd helmreleases.helm.toolkit.fluxcd.io >/dev/null 2>&1; then
  log "Flux is installed; deploy/platform/ is delivered by Flux, skipping the interim apply"
  exit 0
fi

# Namespaces and RuntimeClass. 'kubectl diff' exits 1 when something would change.
rc=0
kubectl diff -f "$PLATFORM/namespaces.yaml" -f "$PLATFORM/runtimeclass-nvidia.yaml" >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 0 ]; then
  log "namespaces and RuntimeClass nvidia already applied"
elif [ "$rc" -eq 1 ]; then
  kubectl apply -f "$PLATFORM/namespaces.yaml" -f "$PLATFORM/runtimeclass-nvidia.yaml" >/dev/null
  changed "applied namespaces and RuntimeClass nvidia"
else
  die "kubectl diff failed (exit $rc)"
fi

# NVIDIA device plugin. Values mirror deploy/platform/nvidia-device-plugin/helmrelease.yaml.
want_values='{"affinity":null,"gfd":{"enabled":false},"nfd":{"enabled":false},"runtimeClassName":"nvidia"}'
have_chart=$(helm -n "$NS" list --filter "^$RELEASE\$" --deployed -o json 2>/dev/null | jq -r '.[0].chart // empty')
have_values=$(helm -n "$NS" get values "$RELEASE" -o json 2>/dev/null | jq -cS '.' || true)
want_values=$(jq -cS '.' <<<"$want_values")

if [ "$have_chart" = "nvidia-device-plugin-$NVIDIA_DEVICE_PLUGIN_CHART_VERSION" ] && [ "$have_values" = "$(printf '%s' "$want_values")" ]; then
  log "$RELEASE $NVIDIA_DEVICE_PLUGIN_CHART_VERSION already installed"
else
  helm upgrade --install "$RELEASE" nvidia-device-plugin \
    --repo "$CHART_REPO" --version "$NVIDIA_DEVICE_PLUGIN_CHART_VERSION" \
    -n "$NS" --create-namespace --wait --timeout 5m \
    --set runtimeClassName=nvidia --set affinity=null \
    --set nfd.enabled=false --set gfd.enabled=false >/dev/null
  changed "installed $RELEASE $NVIDIA_DEVICE_PLUGIN_CHART_VERSION"
fi

# The node advertises the GPU shortly after the plugin registers.
for _ in $(seq 1 60); do
  [ "$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}')" = 1 ] && break
  sleep 2
done
[ "$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}')" = 1 ] \
  || die "node does not advertise nvidia.com/gpu: 1; check 'kubectl -n $NS logs ds/$RELEASE'"
log "node advertises nvidia.com/gpu: 1"
