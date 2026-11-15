#!/usr/bin/env bash
# Checks every spec 01 acceptance criterion on the live host. Exits non-zero if any check fails.
# Usage: scripts/30-verify.sh [--idempotent]   (--idempotent also re-runs install-all.sh with sudo and expects no changes)
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
set +e

TESTS="$REPO_ROOT/deploy/platform/tests"
fails=0

check() { # check <description> <command...>
  local desc=$1; shift
  if "$@" >/dev/null 2>&1; then printf '  PASS  %s\n' "$desc"; else printf '  FAIL  %s\n' "$desc"; fails=$((fails + 1)); fi
}

mem_ok()      { [ "$(free -m | awk '/^Mem:/ {print $2}')" -ge 23552 ]; }
gpu_host_ok() { nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | awk -F', ' '$1 ~ /4080/ && $2+0 >= 15500 {f=1} END {exit !f}'; }
one_node_ready() { [ "$(kubectl get nodes --no-headers | awk '$2 == "Ready"' | wc -l)" -eq 1 ] && [ "$(kubectl get nodes --no-headers | wc -l)" -eq 1 ]; }
no_traefik()  { ! kubectl -n kube-system get pods,deploy,svc -o name | grep -qi traefik; }
traefik_flag(){ grep -Eq '^\s*-\s*traefik\s*$' /etc/rancher/k3s/config.yaml; }
gpu_alloc()   { [ "$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}')" = 1 ]; }
default_sc()  { [ "$(kubectl get sc local-path -o jsonpath='{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}')" = true ]; }
storage_ext4(){ [ "$(df --output=fstype /var/lib/rancher/k3s | tail -1 | tr -d ' ')" = ext4 ]; }
namespaces()  { for n in ollama openviking hermes; do kubectl get ns "$n" || return 1; done; }

job_done() { # job_done <name> : wait for completion, fail fast on failure
  kubectl -n platform-test wait --for=condition=complete "job/$1" --timeout=300s
}

gpu_smoke() {
  kubectl apply -f "$TESTS/namespace.yaml" -f "$TESTS/gpu-smoke-test.yaml" || return 1
  job_done gpu-smoke-test || { kubectl -n platform-test describe job/gpu-smoke-test | tail -20; return 1; }
  kubectl -n platform-test logs job/gpu-smoke-test | grep -q 4080
}

pvc_persistence() {
  kubectl apply -f "$TESTS/namespace.yaml" -f "$TESTS/pvc-test.yaml" || return 1
  job_done pvc-test-writer || return 1
  kubectl -n platform-test delete job pvc-test-writer --wait=true || return 1  # deletes the writer pod
  kubectl apply -f "$TESTS/pvc-test-reader.yaml" || return 1
  job_done pvc-test-reader
}

idempotent() {
  local out
  out=$(sudo "$SCRIPT_DIR/install-all.sh" 2>&1) || { echo "$out"; return 1; }
  ! grep -q 'CHANGED:' <<<"$out" || { grep 'CHANGED:' <<<"$out"; return 1; }
}

echo "Host"
check "WSL sees >= 23GB RAM" mem_ok
check "systemd is PID 1" test "$(ps -p 1 -o comm=)" = systemd
check "k3s service is active" systemctl is-active --quiet k3s
check "k3s service is enabled at boot" systemctl is-enabled --quiet k3s
check "nvidia-smi shows an RTX 4080 with 16GB" gpu_host_ok

echo "Tooling"
check "kubectl version" kubectl version --client
check "helm version" helm version
check "k3s --version" k3s --version
check "nvidia-ctk --version" nvidia-ctk --version
check "flux --version" flux --version

echo "Cluster"
check "one node, Ready" one_node_ready
check "k3s configured with disable: traefik" traefik_flag
check "no Traefik workloads in kube-system" no_traefik
check "RuntimeClass nvidia exists" kubectl get runtimeclass nvidia
check "node advertises nvidia.com/gpu: 1" gpu_alloc

echo "Storage and namespaces"
check "local-path is the default StorageClass" default_sc
check "k3s data dir is on ext4, not /mnt/c" storage_ext4
check "namespaces ollama, openviking, hermes exist" namespaces

echo "Smoke tests (creates and removes namespace platform-test)"
check "GPU smoke test completes and logs the RTX 4080" gpu_smoke
check "PVC binds and data survives pod deletion" pvc_persistence
kubectl delete -f "$TESTS/namespace.yaml" --ignore-not-found --wait=false >/dev/null 2>&1

if [ "${1:-}" = "--idempotent" ]; then
  echo "Idempotency"
  check "install-all.sh re-run changes nothing" idempotent
fi

echo
if [ "$fails" -eq 0 ]; then echo "All checks passed."; else echo "$fails check(s) failed."; exit 1; fi
