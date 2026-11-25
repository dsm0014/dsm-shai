# Spec 17 — Disaster Recovery

**Status:** PARTIAL (no backup run has been verified against this criteria list yet; see the acceptance criteria. Restore drill, datastore snapshot, `wsl --export`, prune observation and fresh-cluster rebuild are open.)

## Purpose

One place for backing up, restoring and rebuilding the single-node k3s stack. Specs 07 (secrets and backup), 09 (LiteLLM gateway) and 10 (Flux GitOps) each named recovery work. That work now lives here, so those specs can close on their own criteria. Protects against loss of the WSL ext4 volume, which holds every local-path PVC.

Depends on spec 01 (cluster, storage), spec 07 (SOPS and age key), spec 10 (Flux bootstrap), and the data owners in specs 03-06, 08 and 09.

## Behavior

**Backup scope** (moved from spec 07)
- Hermes `~/.hermes` (sessions, learned skills; spec 04).
- OpenViking data (spec 03).
- Open WebUI data (spec 05).
- Grafana data (spec 06).
- LiteLLM Postgres (spec 09), captured with `pg_dump`, not a file copy.
- Istio configuration and the istiod root CA secret in `istio-system` (spec 08).
- The age private key, kept offline, and the `sops-age` Secret in `flux-system` (spec 10).
- A k3s datastore snapshot, taken with `k3s etcd-snapshot save` or a consistent copy of the SQLite state.
- Out of scope: Ollama model weights, which are re-pullable.

**Destination, tooling and consistency**
- The repository lives outside the WSL virtual disk: a Windows-side folder (for example `/mnt/c/Users/<user>/Backups/dsm-shai`) or an external drive. The path is configurable.
- Use restic. The repository password is stored outside git (or as a SOPS secret) and backed up separately from the repo.
- SQLite-backed stores (Open WebUI, Grafana) are quiesced or snapshotted, or use the app's own export or `sqlite3 .backup`.
- The script logs repository size and warns or aborts when free space on C: falls below a configured threshold (C: is about 90% full).

**Scheduling and retention**
- A systemd timer (or a k3s CronJob) runs a daily backup. Failures are logged and visible through `systemctl status` or job status, and ideally exposed as a metric in spec 06.
- `wsl.conf` needs `systemd=true`. The docs say how the timer behaves when WSL is idle or stopped.
- Retention: `--keep-daily 7 --keep-weekly 4 --keep-monthly 3`, then `prune`. Repository size stays under the documented cap.

**Restore** (`docs/restore.md`, one procedure end to end)
- Install tooling, restore the age key, `restic restore` to a staging path, re-create PVC data, apply secrets, restart workloads, verify.
- Fresh-cluster rebuild: install k3s, restore the age key, run `scripts/bootstrap-flux.sh`, restore PVC data. Cluster desired state comes from git, not from the backup.
- Coarse fallback: `wsl --export <distro> <path>.tar` or a copy of `ext4.vhdx`, with a recommended cadence and a note on its size.

## Acceptance Criteria

- [ ] A manual backup run produces an encrypted repository outside the WSL virtual disk containing all in-scope data and no Ollama model weights. (from spec 07)
- [ ] The scheduled backup runs unattended, and a log or status shows a successful run within the last 24 hours. (from spec 07)
- [ ] Retention prunes old snapshots, and repository size stays under the documented cap. (from spec 07)
- [ ] The k3s datastore snapshot is taken and restorable. (needs root; from spec 07)
- [ ] Restore drill: after deleting the PVC data (or on a fresh namespace or cluster), following `docs/restore.md` alone recovers Hermes sessions and skills, OpenViking data, Open WebUI users and chats, Grafana dashboards, and LiteLLM virtual keys. The drill outcome and date are recorded. (from spec 07)
- [ ] The restore drill confirms the backup cannot be read without the repository password, and that secrets decrypt only with the backed-up age key. (from spec 07)
- [ ] A Postgres backup and restore preserves LiteLLM virtual keys, and each consumer key still authenticates afterwards. (from spec 09)
- [ ] A rebuild from scratch (wiped k3s, restored age key, `scripts/bootstrap-flux.sh`, restored data) matches the previous cluster state, and the procedure is documented in `docs/restore.md`. (from spec 10)
- [ ] `wsl --export` fallback steps are documented and tested once. (from spec 07)
- [ ] One restic prune is observed in a live run, after enough snapshots exist for retention to remove one. (from the task list)
