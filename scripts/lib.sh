#!/usr/bin/env bash
# Shared helpers. Source this file; do not execute it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=versions.env
source "$SCRIPT_DIR/versions.env"

log() { printf '[%s] %s\n' "$(basename "$0")" "$*"; }
# install-all.sh --check and 30-verify.sh --idempotent fail on any "CHANGED:" line.
changed() { printf '[%s] CHANGED: %s\n' "$(basename "$0")" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

need_root() { [ "$(id -u)" -eq 0 ] || die "run with sudo"; }

require_amd64() {
  [ "$(uname -m)" = "x86_64" ] || die "only x86_64 is supported (got $(uname -m))"
}

# write_if_changed <path> [mode]  (content on stdin). Returns 0 if the file was written, 1 if unchanged.
write_if_changed() {
  local path=$1 mode=${2:-0644} tmp
  tmp=$(mktemp)
  cat >"$tmp"
  if [ -f "$path" ] && cmp -s "$tmp" "$path"; then
    rm -f "$tmp"
    return 1
  fi
  mkdir -p "$(dirname "$path")"
  install -m "$mode" "$tmp" "$path"
  rm -f "$tmp"
  changed "wrote $path"
  return 0
}

# download_verified <url> <sha256> <dest>
download_verified() {
  local url=$1 sha=$2 dest=$3
  curl -fsSL --retry 3 -o "$dest" "$url"
  echo "$sha  $dest" | sha256sum -c --quiet - || die "checksum mismatch for $url"
}

# The invoking (non-root) user when run through sudo.
real_user() { echo "${SUDO_USER:-$(id -un)}"; }
real_home() { getent passwd "$(real_user)" | cut -d: -f6; }
