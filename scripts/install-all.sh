#!/usr/bin/env bash
# Host-level install: WSL config, tools, k3s. Idempotent. Usage: sudo scripts/install-all.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root

"$SCRIPT_DIR/00-wsl-host.sh"
"$SCRIPT_DIR/10-tools.sh"
"$SCRIPT_DIR/20-k3s.sh"

log "host setup complete. Next: scripts/bootstrap-flux.sh (spec 10) to deliver deploy/, then scripts/30-verify.sh"
