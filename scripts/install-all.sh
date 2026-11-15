#!/usr/bin/env bash
# Host-level install: WSL config, tools, k3s, and (until Flux exists) the platform namespaces and GPU device plugin. Idempotent. Usage: sudo scripts/install-all.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root

"$SCRIPT_DIR/00-wsl-host.sh"
"$SCRIPT_DIR/10-tools.sh"
"$SCRIPT_DIR/20-k3s.sh"
"$SCRIPT_DIR/25-platform.sh"  # interim until spec 10 (Flux) delivers deploy/platform/

log "host setup complete. Run scripts/30-verify.sh. (Once spec 10 lands, scripts/bootstrap-flux.sh delivers deploy/ and 25-platform.sh is removed.)"
