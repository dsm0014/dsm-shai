#!/bin/bash
# Find ambient-mesh pods that ztunnel did not enrol after it last started (the "Restart recovery" gap in deploy/istio/README.md).
# A pod that was already running when ztunnel restarted is never enrolled: its traffic is plaintext and STRICT mTLS rejects it.
# Default: report only. --apply deletes the flagged pods so their controllers recreate them (PVCs are kept).
# Pods on host networking, pods without a controller, and pods in namespaces not labelled istio.io/dataplane-mode=ambient are skipped.
# Usage: bash scripts/mesh-enrolment.sh [--apply]
set -euo pipefail
apply=0
[ "${1:-}" = "--apply" ] && apply=1
KUBECTL=${KUBECTL:-kubectl}
ztunnels=$($KUBECTL -n istio-system get pods -l app=ztunnel -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.nodeName}{" "}{.status.containerStatuses[0].state.running.startedAt}{"\n"}{end}')
[ -n "$ztunnels" ] || { echo "no ztunnel pods found in istio-system"; exit 2; }
ambient_ns=$($KUBECTL get ns -l istio.io/dataplane-mode=ambient -o jsonpath='{.items[*].metadata.name}')
flagged=0
while read -r zt node started; do
  [ -n "$zt" ] || continue
  # ISO timestamps compare correctly as strings (all UTC, same format)
  enrolled=$($KUBECTL -n istio-system logs "$zt" 2>/dev/null | grep -o 'pod received, starting proxy.*' | grep -o 'name="[^"]*" namespace="[^"]*"' | sort -u || true)
  for ns in $ambient_ns; do
    $KUBECTL -n "$ns" get pods --field-selector="spec.nodeName=$node,status.phase=Running" \
      -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.startTime}{" "}{.spec.hostNetwork}{" "}{.metadata.ownerReferences[0].kind}{"\n"}{end}' 2>/dev/null |
    while read -r pod pstart hostnet owner; do
      [ -n "$pod" ] || continue
      [ "$hostnet" = "true" ] && continue
      [ -n "$owner" ] || continue
      # Started after ztunnel: enrolled on arrival, so not a gap.
      [[ "$pstart" > "$started" ]] && continue
      if ! grep -q "name=\"$pod\" namespace=\"$ns\"" <<<"$enrolled"; then
        echo "NOT ENROLLED: $ns/$pod (node $node, started $pstart, ztunnel $zt started $started)"
        if [ "$apply" = 1 ]; then
          $KUBECTL -n "$ns" delete pod "$pod" --wait=false
          echo "  deleted $ns/$pod"
        fi
      fi
    done
  done
done <<<"$ztunnels"
echo "done (apply=$apply)"
