#!/usr/bin/env bash
# Break-glass: apply every SOPS-encrypted Secret in deploy/secrets/ straight to the cluster (spec 07).
# Normal delivery is Flux (the `secrets` stage decrypts in-cluster). Use this only before Flux is bootstrapped,
# or to recover a broken Flux secret path. Decrypts in memory, pipes into kubectl, never writes plaintext to disk,
# and refuses to run without the age key.
set -euo pipefail

AGE_KEY="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
cd "$(dirname "$0")/.."

if [ ! -r "$AGE_KEY" ]; then
  echo "ERROR: age private key not found or unreadable at: $AGE_KEY" >&2
  echo "       Restore it from the offline backup first (see docs/restore.md). Nothing was applied." >&2
  exit 1
fi
export SOPS_AGE_KEY_FILE="$AGE_KEY"

shopt -s nullglob
files=(deploy/secrets/*.sops.yaml)
if [ "${#files[@]}" -eq 0 ]; then
  echo "ERROR: no *.sops.yaml files under deploy/secrets/" >&2
  exit 1
fi

for f in "${files[@]}"; do
  echo "applying $f"
  sops --decrypt "$f" | kubectl apply -f - >/dev/null
done
echo "done: ${#files[@]} secret manifest(s) applied"
