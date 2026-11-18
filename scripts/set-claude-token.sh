#!/bin/bash
# Store the Claude subscription token as SOPS ciphertext (spec 12). Run on the host; the token is read silently and never printed.
# Get one with `claude setup-token` (uses your Claude subscription; no API credits). Then commit the ciphertext and let Flux apply it.
set -euo pipefail
cd "$(dirname "$0")/.."
read -rsp "Paste the Claude subscription token (from 'claude setup-token'): " TOKEN; echo
case "$TOKEN" in sk-ant-oat*) ;; *) echo "That does not look like a subscription token (sk-ant-oat...). An sk-ant-api key bills API credits and is refused." >&2; exit 1;; esac
OUT=deploy/secrets/hermes-claude.sops.yaml
TMP="$(mktemp --suffix=.sops.yaml -p deploy/secrets)"; trap 'rm -f "$TMP"' EXIT
printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: hermes-claude\n  namespace: hermes\ntype: Opaque\nstringData:\n  oauth-token: %s\n' "$TOKEN" > "$TMP"
sops --encrypt "$TMP" > "$OUT"
grep -q hermes-claude.sops.yaml deploy/secrets/kustomization.yaml || echo "  - hermes-claude.sops.yaml" >> deploy/secrets/kustomization.yaml
echo "wrote $OUT; now run scripts/check-sops.sh, commit, and restart hermes after Flux applies it"
