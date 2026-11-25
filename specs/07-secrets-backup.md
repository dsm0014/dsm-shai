# Spec 07 — Secrets Management

**Status:** PARTIAL (SOPS workflow and break-glass apply are written; the three acceptance criteria below are not yet ticked against evidence. Backup and restore moved to spec 17.)

## Purpose
Define how secrets are stored in git and applied to the single-node k3s stack. Backup, restore and rebuild are in spec 17 (Disaster Recovery). Depends on spec 01 (cluster, storage) and spec 10 (Flux delivery).

## Behavior

**Secrets (SOPS + age)**
- Kubernetes Secret manifests are committed to git only in SOPS-encrypted form, using age recipients configured in a repo-level `.sops.yaml` (`encrypted_regex: ^(data|stringData)$`).
- The age private key lives outside the repo (e.g. `~/.config/sops/age/keys.txt`) and is never committed. The user backs it up separately (spec 17), and the docs say so explicitly.
- The existing `.gitignore` entries (`.env`, `*.key`, `*.agekey`, `secrets.yaml`, `*.dec.yaml`) stay in force. Encrypted files use a distinct name (e.g. `*.sops.yaml`) so they are not ignored.
- A documented workflow covers generating the key, encrypting, editing (`sops <file>`), decrypting, and applying, plus rotating the key and re-encrypting.
- Delivery is by Flux (spec 10): a Kustomization with `decryption.provider: sops` and a `sops-age` Secret in `flux-system` decrypts and applies encrypted manifests, so the normal path is a commit and encrypted manifests are never applied with `kubectl`. The repo is public, so the ciphertext is world-readable and the age key is the sole protection (rotate on exposure, scan for plaintext before every commit, per spec 10).
- `scripts/apply-secrets.sh` is kept as a break-glass tool for use before Flux is bootstrapped (and to seed `sops-age`). It decrypts with `sops -d` and pipes the output straight into `kubectl apply -f -`. It never writes plaintext to disk, fails closed if the key is missing, and does not echo secret values.
- Consumers: Open WebUI `WEBUI_SECRET_KEY` (spec 05), the Grafana admin credential (spec 06), and the LiteLLM master key, per-consumer virtual keys (`hermes`, `openviking`, `open-webui`) and Postgres password (spec 09). Ollama uses no secrets (spec 02); Hermes, OpenViking and Open WebUI hold only their own LiteLLM virtual key.

## Acceptance Criteria
- [ ] `.sops.yaml` exists, and Secret manifests for Open WebUI and Grafana are committed encrypted. `grep` finds no plaintext values in the git history or working tree.
- [ ] `scripts/apply-secrets.sh` creates the Secrets in the cluster, leaves no plaintext file behind (verified by a filesystem check), and exits non-zero with a clear message if the age key is absent.
- [ ] Open WebUI and Grafana start using the applied secrets (no hardcoded credentials in manifests).

Moved to spec 17 (Disaster Recovery): the backup run, scheduled backup, retention, restore drill, age-key and repository-password separation, and the `wsl --export` fallback.
