#!/usr/bin/env bash
# Install and configure single-node k3s with Traefik disabled and the NVIDIA runtime registered. Idempotent. Run with sudo.
#
# The nvidia runtime is registered by k3s itself: it auto-detects nvidia-container-runtime on PATH at start
# and writes it into the generated containerd config, plus a RuntimeClass named "nvidia". We deliberately do not
# run `nvidia-ctk runtime configure` against that generated file because k3s regenerates it on every start.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root
require_amd64

[ "$(ps -p 1 -o comm=)" = systemd ] || die "systemd is not PID 1; run scripts/00-wsl-host.sh, then 'wsl --shutdown' from Windows and restart WSL"
command -v nvidia-container-runtime >/dev/null || die "nvidia-container-runtime not found; run scripts/10-tools.sh first"

CONFIG=/etc/rancher/k3s/config.yaml
CONTAINERD_CONFIG=/var/lib/rancher/k3s/agent/etc/containerd/config.toml
restart=0

# Traefik is disabled because the Istio ingress gateway (spec 08) is the single entry point; servicelb stays default.
# Set K3S_RESOLV_CONF=/path if pods cannot resolve DNS on this WSL2 host.
if write_if_changed "$CONFIG" 0644 < <(
  echo "disable:"
  echo "  - traefik"
  echo 'write-kubeconfig-mode: "0644"'
  [ -z "${K3S_RESOLV_CONF:-}" ] || echo "resolv-conf: $K3S_RESOLV_CONF"
); then
  restart=1
fi

if command -v k3s >/dev/null && k3s --version | head -1 | grep -qF "$K3S_VERSION"; then
  log "k3s $K3S_VERSION already installed"
else
  curl -fsSL https://get.k3s.io \
    | INSTALL_K3S_VERSION="$K3S_VERSION" INSTALL_K3S_SKIP_START=true INSTALL_K3S_SKIP_ENABLE=true sh -
  changed "installed k3s $K3S_VERSION"
  restart=1
fi

systemctl is-enabled --quiet k3s || { systemctl enable k3s; changed "enabled k3s service"; }

if systemctl is-active --quiet k3s; then
  if [ "$restart" -eq 1 ]; then
    systemctl restart k3s
    changed "restarted k3s"
  fi
else
  systemctl start k3s
  changed "started k3s"
fi

# Runtime detection only happens at k3s start; restart once if the toolkit arrived after k3s first ran.
for _ in $(seq 1 60); do [ -f "$CONTAINERD_CONFIG" ] && break; sleep 1; done
if ! grep -q nvidia "$CONTAINERD_CONFIG"; then
  systemctl restart k3s
  changed "restarted k3s to pick up the nvidia runtime"
  for _ in $(seq 1 60); do grep -q nvidia "$CONTAINERD_CONFIG" 2>/dev/null && break; sleep 1; done
  grep -q nvidia "$CONTAINERD_CONFIG" || die "nvidia runtime missing from $CONTAINERD_CONFIG"
fi

user=$(real_user)
if [ "$user" != root ]; then
  kube_dir="$(real_home)/.kube"
  if [ "$(readlink "$kube_dir/config" 2>/dev/null)" != /etc/rancher/k3s/k3s.yaml ]; then
    sudo -u "$user" mkdir -p "$kube_dir"
    sudo -u "$user" ln -sf /etc/rancher/k3s/k3s.yaml "$kube_dir/config"
    changed "linked $kube_dir/config to the k3s kubeconfig"
  fi
fi
