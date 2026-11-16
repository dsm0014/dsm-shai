# Secrets workflow (SOPS + age)

Spec 07. Secret manifests are committed only as SOPS ciphertext. Only `data` and `stringData` are encrypted (see `.sops.yaml`), so metadata stays readable for Flux. The repository is public: the ciphertext is world-readable, so keep the private key out of git.

## Where the key lives

- Private key: `~/.config/sops/age/keys.txt` (mode 600). Never committed. `.gitignore` covers `*.key` and `*.agekey`.
- Public recipient: in `.sops.yaml`. Safe to commit.
- Offline copy: back this file up separately from the repo and from the restic repository password. Losing it means losing every encrypted secret.

## Generate a key (first time only)

```sh
mkdir -p ~/.config/sops/age && chmod 700 ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt        # prints the public key: put it in .sops.yaml
chmod 600 ~/.config/sops/age/keys.txt
```

## Encrypt a new Secret

Write the manifest without committing it, then encrypt it. Use the `*.sops.yaml` name so the rules in `.sops.yaml` apply and `.gitignore` does not hide it. Pipe plaintext through stdin so it never lands on disk:

```sh
printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: my-secret\n  namespace: my-ns\ntype: Opaque\nstringData:\n  token: %s\n' "$VALUE" \
  | sops --encrypt --filename-override deploy/secrets/my-secret.sops.yaml /dev/stdin \
  > deploy/secrets/my-secret.sops.yaml
```

Then add the file to `deploy/secrets/kustomization.yaml`, commit, and let Flux apply it.

## Edit or view

```sh
sops deploy/secrets/my-secret.sops.yaml          # opens the decrypted content in $EDITOR, re-encrypts on save
sops --decrypt deploy/secrets/my-secret.sops.yaml   # print to stdout only; do not redirect to a file in the repo
```

## Apply

- **Normal:** commit. Flux's `secrets` stage decrypts in-cluster with the `sops-age` Secret in `flux-system`.
- **Break-glass (before Flux, or if the Flux path is broken):** `scripts/apply-secrets.sh`. It decrypts in memory, pipes into `kubectl apply`, writes no plaintext to disk, and exits 1 if the age key is missing.

Never apply an encrypted manifest by hand without decrypting it first.

## Rotate the age key

1. Generate a new key and add its public key to `.sops.yaml` alongside the old one.
2. Re-encrypt every file: `sops updatekeys deploy/secrets/*.sops.yaml` (then confirm each file decrypts with the new key).
3. Remove the old recipient from `.sops.yaml` and re-run `updatekeys`.
4. Update the `sops-age` Secret in `flux-system` with the new private key, and back up the new key offline.
5. Keep the old private key until every encrypted copy (git history included) is re-encrypted or no longer matters.

## Rotate an application credential

Issue a new LiteLLM virtual key (or the app's own credential), re-encrypt the matching Secret with the new value, commit, and let Flux apply it. Then revoke the old key (`/key/delete` on LiteLLM).

## Current secret manifests

| File | Secret | Holds |
|---|---|---|
| `grafana-admin.sops.yaml` | `grafana-admin` (monitoring) | Grafana admin user and password |
| `litellm.sops.yaml` | `litellm-secrets` (litellm) | master key, Postgres password |
| `openviking.sops.yaml` | `openviking-secrets` (openviking) | LiteLLM key, root key, verification user key |
| `hermes.sops.yaml` | `hermes-secrets` (hermes) | LiteLLM key, OpenViking tenant key |
| `open-webui.sops.yaml` | `open-webui-secrets` (open-webui) | LiteLLM key, `WEBUI_SECRET_KEY` |

Check that nothing is in plaintext: `grep -rE "sk-[0-9a-f]{16,}|ovr-[0-9a-f]{16,}" --include=*.yaml . | grep -v ENC` should return nothing.
