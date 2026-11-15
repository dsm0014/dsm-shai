# restic: Local Repository Backups, Retention and Restore

**Tags:** restic, backup, restore, retention, encryption, spec-07

Source: restic.readthedocs.io/en/stable. This is condensed from a summarizing fetch of the pages 030, 040, 045, 050, 060, 070 and 075, so check flags against `restic --help` for the pinned version.

## Repository and password

- Local repo: `restic init --repo /path/to/repo` (repository format v2 is the default, needs restic 0.14+, and adds compression).
- **Losing the password makes the data unrecoverable.** Store it outside the repo. Several keys can unlock one repo (`restic key list|add|remove|passwd`).
- Non-interactive password sources: `RESTIC_PASSWORD_FILE` / `--password-file` (preferred here, mounted from a SOPS-managed Secret), `RESTIC_PASSWORD_COMMAND`, or `RESTIC_PASSWORD` (avoid, since it leaks via the environment). Repo location: `-r`, `RESTIC_REPOSITORY`.
- `--insecure-no-password` (0.17+) creates a passwordless repo. Do not use it.

## Backup

- `restic -r REPO backup PATH...` deduplicates and compresses. Unchanged files are detected via the parent snapshot (mtime, ctime, size, inode). Use `--skip-if-unchanged` to avoid empty snapshots, and keep the backup paths stable so parents match.
- Useful flags: `--exclude`/`--exclude-file`, `--exclude-caches`, `--one-file-system`, `--tag`, `--dry-run -vv`, `--files-from`.
- Database dumps: `restic backup --stdin-from-command --stdin-filename NAME -- pg_dump ...` (preferred over `--stdin` because it propagates errors). This fits the LiteLLM Postgres dump in spec 07/09.
- restic has no scheduler. Use a Kubernetes `CronJob`, and make sure runs cannot overlap (`concurrencyPolicy: Forbid`).
- Exit codes: 0 ok, 1 fatal (no snapshot), 3 some source files unreadable (incomplete snapshot), 10 repo missing, 11 lock failure, 12 wrong password.

## Retention

- `restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune` (policies are ORed, and the default grouping is `host,paths`). Preview with `--dry-run`.
- `forget` removes snapshots, and `prune` frees unreferenced data. Prune takes an exclusive lock, so schedule it outside the backup window.
- Prune tuning: `--max-unused` (default 5%), `--max-repack-size`. `--max-repack-size 0` minimises scratch space when disk is tight.

## Verify and restore

- `restic check` verifies structure. `--read-data` (or `--read-data-subset 10%`) reads pack contents. Run a subset check periodically.
- Restore: `restic restore latest --target DIR` (`--host`, `--path` pick the snapshot). `--include`/`--exclude` limit files, `--overwrite always|if-changed|if-newer|never`, `--delete` removes extras (preview first with `--dry-run -vv`). `restic mount` and `restic dump` help with spot checks.
- Treat restore as the real test: spec 07 requires a restore rehearsal.

## Scripting

`--json` gives machine-readable output. Relevant env vars: `RESTIC_CACHE_DIR` (put it on a PVC or emptyDir), `RESTIC_COMPRESSION`, `RESTIC_PACK_SIZE`.

## dsm-shai notes

- Repository target: a folder outside the WSL ext4 disk (for example a mounted Windows path). Mind the C: drive being 90% full.
- Consistent snapshots of PVC data (Ollama models excluded, since they are re-pullable) need either quiescing or a logical dump for Postgres and OpenViking data.
