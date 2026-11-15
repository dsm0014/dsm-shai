# Spec 07 — Secrets Management and Backup/Restore

**Status:** TODO

## Purpose
Define how secrets are stored in git and how irreplaceable cluster state is backed up and restored on the single-node k3s stack. Protect against loss of the WSL ext4 volume, which is a single point of failure for all local-path PVCs. Depends on spec 01 (cluster, storage) and specs 03-06 and 08-09 (the data to protect).

## Behavior

**Secrets (SOPS + age)**
- Kubernetes Secret manifests are committed to git only in SOPS-encrypted form, using age recipients configured in a repo-level `.sops.yaml` (`encrypted_regex: ^(data|stringData)$`).
- The age private key lives outside the repo (e.g. `~/.config/sops/age/keys.txt`) and is never committed. The user backs it up separately, and the docs say so explicitly.
- The existing `.gitignore` entries (`.env`, `*.key`, `*.agekey`, `secrets.yaml`, `*.dec.yaml`) stay in force. Encrypted files use a distinct name (e.g. `*.sops.yaml`) so they are not ignored.
- A documented workflow covers generating the key, encrypting, editing (`sops <file>`), decrypting, and applying, plus rotating the key and re-encrypting.
- `scripts/apply-secrets.sh` decrypts with `sops -d` and pipes the output straight into `kubectl apply -f -`. It never writes plaintext to disk, fails closed if the key is missing, and does not echo secret values.
- Consumers: Open WebUI `WEBUI_SECRET_KEY` (spec 05), the Grafana admin credential (spec 06), and the LiteLLM master key, per-consumer virtual keys (`hermes`, `openviking`, `open-webui`) and Postgres password (spec 09). Ollama uses no secrets (spec 02); Hermes, OpenViking and Open WebUI hold only their own LiteLLM virtual key.

**Backup scope and destination**
- In scope:
  - Hermes `~/.hermes` (sessions, learned skills; spec 04)
  - OpenViking data (spec 03)
  - Open WebUI data (spec 05)
  - Grafana data (spec 06)
  - LiteLLM Postgres (spec 09), captured with `pg_dump` rather than a file copy
  - Istio configuration and the istiod root CA secret in `istio-system` (spec 08)
  - A k3s datastore snapshot (etcd/SQLite) taken via `k3s etcd-snapshot save` or a consistent copy of the SQLite state.
- Out of scope: Ollama model weights (re-pullable), which are explicitly excluded.
- The destination is outside the WSL virtual disk, either a Windows-side folder (e.g. `/mnt/c/Users/<user>/Backups/dsm-shai`) or an external drive. The path is configurable.
- Use restic (or an equivalent single-binary tool). Backups are encrypted by the repository password, which is stored outside git (or as a SOPS secret) and backed up separately from the repo.
- Data is captured consistently. Apps are quiesced or snapshotted for SQLite-backed stores (Open WebUI, Grafana), or use the app's own export or `sqlite3 .backup`.
- Size and retention are bounded because C: is about 90% full (about 197 GB free). Retention is e.g. `--keep-daily 7 --keep-weekly 4 --keep-monthly 3` followed by `prune`. The script logs repository size and aborts or warns if free space falls below a configured threshold.

**Scheduling**
- Runs are scheduled by a systemd timer (or a k3s CronJob) with a daily default. Failures are logged and visible via `systemctl status` or job status, and ideally exposed as a metric or alert in the spec 06 stack.
- The scheduler works in WSL, so document the `systemd=true` requirement in `wsl.conf` and how the timer starts when WSL is idle or stopped.

**Restore and fallback**
- `docs/restore.md` documents the procedure end to end: install tooling, restore the age key, `restic restore` to a staging path, re-create PVC data, apply secrets, restart workloads, and verify.
- As a coarse fallback, `wsl --export <distro> <path>.tar` (or a copy of `ext4.vhdx`) is documented, with a recommended cadence and a note on its size.

## Acceptance Criteria
- [ ] `.sops.yaml` exists, and Secret manifests for Open WebUI and Grafana are committed encrypted. `grep` finds no plaintext values in the git history or working tree.
- [ ] `scripts/apply-secrets.sh` creates the Secrets in the cluster, leaves no plaintext file behind (verified by a filesystem check), and exits non-zero with a clear message if the age key is absent.
- [ ] Open WebUI and Grafana start using the applied secrets (no hardcoded credentials in manifests).
- [ ] A manual backup run produces an encrypted repository outside the WSL virtual disk containing all in-scope data and no Ollama model weights.
- [ ] The scheduled job runs unattended, and a log or status shows a successful run within the last 24h.
- [ ] Retention prunes old snapshots, and repository size stays under the documented cap.
- [ ] Restore drill: after deleting the PVC data (or on a fresh namespace or cluster), following `docs/restore.md` alone recovers Hermes sessions and skills, OpenViking data, Open WebUI users and chats, Grafana dashboards, and LiteLLM virtual keys. The drill outcome and date are recorded.
- [ ] The restore drill also confirms that the backup cannot be read without the repository password, and that secrets decrypt only with the backed-up age key.
- [ ] `wsl --export` fallback steps are documented and tested once.
