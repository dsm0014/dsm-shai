#!/usr/bin/env bash
# Install pinned kubectl, helm, flux and the NVIDIA Container Toolkit. Idempotent. Run with sudo.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root
require_amd64
command -v apt-get >/dev/null || die "the NVIDIA toolkit install needs a Debian/Ubuntu WSL distro"

BIN=/usr/local/bin
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# kubectl. k3s's installer may leave a kubectl -> k3s symlink; replace it with the pinned binary.
if [ -L "$BIN/kubectl" ] && [ "$(basename "$(readlink -f "$BIN/kubectl")")" = k3s ]; then
  rm -f "$BIN/kubectl"
fi
if "$BIN/kubectl" version --client 2>/dev/null | grep -qF "$KUBECTL_VERSION"; then
  log "kubectl $KUBECTL_VERSION already installed"
else
  base="https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64"
  sha=$(curl -fsSL "$base/kubectl.sha256")
  download_verified "$base/kubectl" "$sha" "$tmp/kubectl"
  install -m 0755 "$tmp/kubectl" "$BIN/kubectl"
  changed "installed kubectl $KUBECTL_VERSION"
fi

# helm
if "$BIN/helm" version --template '{{.Version}}' 2>/dev/null | grep -qxF "$HELM_VERSION"; then
  log "helm $HELM_VERSION already installed"
else
  tarball="helm-$HELM_VERSION-linux-amd64.tar.gz"
  sha=$(curl -fsSL "https://get.helm.sh/$tarball.sha256sum" | awk '{print $1}')
  download_verified "https://get.helm.sh/$tarball" "$sha" "$tmp/$tarball"
  tar -xzf "$tmp/$tarball" -C "$tmp" linux-amd64/helm
  install -m 0755 "$tmp/linux-amd64/helm" "$BIN/helm"
  changed "installed helm $HELM_VERSION"
fi

# flux CLI
if "$BIN/flux" --version 2>/dev/null | grep -qF "$FLUX_VERSION"; then
  log "flux $FLUX_VERSION already installed"
else
  rel="https://github.com/fluxcd/flux2/releases/download/v$FLUX_VERSION"
  tarball="flux_${FLUX_VERSION}_linux_amd64.tar.gz"
  sha=$(curl -fsSL "$rel/flux_${FLUX_VERSION}_checksums.txt" | awk -v f="$tarball" '$2 == f {print $1}')
  [ -n "$sha" ] || die "no checksum found for $tarball"
  download_verified "$rel/$tarball" "$sha" "$tmp/$tarball"
  tar -xzf "$tmp/$tarball" -C "$tmp" flux
  install -m 0755 "$tmp/flux" "$BIN/flux"
  changed "installed flux $FLUX_VERSION"
fi

# NVIDIA Container Toolkit (provides nvidia-ctk and the nvidia-container-runtime that k3s auto-detects)
ctk_pkg_version="$NVIDIA_CTK_VERSION-1"
keyring=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
list=/etc/apt/sources.list.d/nvidia-container-toolkit.list
installed=$(dpkg-query -W -f='${Version}' nvidia-container-toolkit 2>/dev/null || true)
if [ "$installed" = "$ctk_pkg_version" ]; then
  log "nvidia-container-toolkit $ctk_pkg_version already installed"
else
  if [ ! -f "$keyring" ]; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --batch --dearmor -o "$keyring"
    changed "added NVIDIA apt keyring"
  fi
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed "s#deb https://#deb [signed-by=$keyring] https://#g" \
    | write_if_changed "$list" || true
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-downgrades \
    "nvidia-container-toolkit=$ctk_pkg_version" \
    "nvidia-container-toolkit-base=$ctk_pkg_version" \
    "libnvidia-container-tools=$ctk_pkg_version" \
    "libnvidia-container1=$ctk_pkg_version"
  apt-mark hold nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools libnvidia-container1 >/dev/null
  changed "installed nvidia-container-toolkit $ctk_pkg_version"
fi
