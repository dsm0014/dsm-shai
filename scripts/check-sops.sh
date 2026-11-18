#!/usr/bin/env bash
# Secret hygiene check (spec 07 / spec 10): every tracked *.sops.yaml is real SOPS ciphertext, and no plaintext
# key material appears in tracked files. Run by pre-commit and CI. Exits 1 on any finding.
set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
fail=0

# 1. Every *.sops.yaml must have a sops: block and encrypted data or stringData.
while IFS= read -r f; do
  if ! grep -q '^sops:' "$f"; then echo "NOT ENCRYPTED: $f (missing sops: block)"; fail=1; fi
  if ! grep -q 'ENC\[AES256_GCM' "$f"; then echo "NO CIPHERTEXT: $f"; fail=1; fi
done < <(git ls-files 2>/dev/null | grep -E '\.sops\.yaml$' | grep -v '^\.sops\.yaml$')

# 2. Plaintext patterns in tracked files: LiteLLM keys, OpenViking keys, age private keys, PEM keys, GitHub tokens.
pat='sk-[0-9a-f]{20,}|ovr-[0-9a-f]{20,}|AGE-SECRET-KEY-1[0-9A-Z]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[0-9A-Za-z]{30,}|github[_]pat[_][0-9A-Za-z_]{30,}|sk-ant-[0-9A-Za-z_-]{20,}'
hits=$(git grep -n -E "$pat" -- . ':!*.md' 2>/dev/null | grep -v 'check-sops.sh' || true)
if [ -n "$hits" ]; then echo "PLAINTEXT KEY MATERIAL FOUND:"; echo "$hits" | cut -d: -f1,2; fail=1; fi

[ "$fail" -eq 0 ] && echo "check-sops: ok" || echo "check-sops: FAILED"
exit "$fail"
