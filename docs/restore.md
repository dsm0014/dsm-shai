# Restore runbook

Spec 07 part B. Restores the state that is not in git: PVC data (Hermes, OpenViking, Open WebUI, Grafana), the LiteLLM Postgres (virtual keys, budgets, spend), the Istio CA, and the SOPS keys. Cluster desired state is in git, so a rebuild is: install k3s, restore the age key, bootstrap Flux, restore data, then verify.

## What you need first (outside this machine)

1. **The age private key** (`keys.txt`). Keep an offline copy. Without it, no encrypted Secret can be decrypted.
2. **The restic repository password** (`~/.config/restic/password`). Keep it separate from the repository.
3. **The repository:** `/mnt/c/Users/danth/Backups/dsm-shai/restic` (on the Windows C: drive, outside the WSL disk). Copy it elsewhere too if you can; it is the only copy of the data.

## 1. Install tooling

- restic (the version used: 0.19.1; `~/.local/bin/restic`). Verify the release SHA256 before installing.
- kubectl, helm, flux, sops, age, k3s (see `scripts/10-tools.sh`, `scripts/20-k3s.sh`).

## 2. Restore the keys

```sh
mkdir -p ~/.config/sops/age ~/.config/restic
cp /path/to/offline/keys.txt ~/.config/sops/age/keys.txt && chmod 600 ~/.config/sops/age/keys.txt
cp /path/to/offline/restic-password ~/.config/restic/password && chmod 600 ~/.config/restic/password
export RESTIC_REPOSITORY=/mnt/c/Users/danth/Backups/dsm-shai/restic RESTIC_PASSWORD_FILE=$HOME/.config/restic/password
restic snapshots --compact                 # must list snapshots; a wrong password fails here
```

## 3. Rebuild the cluster

```sh
scripts/install-all.sh                     # platform (k3s, GPU, namespaces)
scripts/bootstrap-flux.sh                  # Flux and the stage Kustomizations; the secrets stage decrypts with the age key
flux get kustomizations                    # wait for every stage to be Ready
```

If Flux cannot reach the repository or the secrets stage fails, use the break-glass path: `scripts/apply-secrets.sh`.

## 4. Restore data

Restore each snapshot to a staging folder first, then copy into the PVC of a stopped app. Use the `latest` snapshot for each tag.

| Tag | What | Target |
|---|---|---|
| `hermes` | `/opt/data` (config, sessions, skills) | `hermes` deployment, PVC `hermes-home`, mounted at `/opt/data` |
| `openviking` | OpenViking data | `openviking` deployment, PVC `openviking-data`, mounted at `/app/.openviking` |
| `open-webui` | `/app/backend/data` (`webui.db`, uploads) | `open-webui` deployment, PVC `open-webui-data`, mounted at `/app/backend/data` |
| `grafana` | `/var/lib/grafana` (Grafana DB) | `kube-prometheus-stack-grafana` in `monitoring`, PVC of the same name |
| `litellm-postgres` | `pg_dump -Fc` of database `litellm` | restore with `pg_restore` into the `litellm` Postgres |
| `istio` | `istio-ca-secret` and config maps (YAML) | `kubectl apply -f` after Istio is installed |
| `keys` | `sops-age` Secret (YAML) and the age key file | `kubectl apply` for the Secret; the file is the key you already restored in step 2 |

Example for one PVC (scale the app to 0 first, use a helper pod that mounts the PVC):

```sh
kubectl -n hermes scale deploy/hermes --replicas=0
restic dump --tag hermes latest hermes.tar | kubectl -n hermes exec -i <helper-pod> -- tar -C /opt/data -xf -
kubectl -n hermes scale deploy/hermes --replicas=1
```

Postgres:

```sh
restic dump --tag litellm-postgres latest litellm.dump > /path/to/staging/litellm.dump
kubectl -n litellm cp /path/to/staging/litellm.dump postgres-0:/tmp/litellm.dump
kubectl -n litellm exec postgres-0 -- pg_restore -U litellm -d litellm --clean --if-exists /tmp/litellm.dump
```

## 5. Verify

- Hermes: `kubectl -n hermes exec deploy/hermes -- sh -c 'hermes -z "Reply with exactly the word PONG and nothing else."'`.
- Open WebUI: log in with an existing account; check the chat history is there.
- OpenViking: search for a known memory with the `hermes` tenant key.
- LiteLLM: `GET /key/info` or list keys with the master key; `hermes`, `openviking` and `open-webui` must exist.
- Grafana: `grafana.localhost` through the ingress (see `deploy/monitoring/README.md`). Dashboards come from git (ConfigMaps), not from the backup.

## Restore drill record

The drill was run on **2026-11-16** against the first backup, without touching the live PVCs:

| Check | Result |
|---|---|
| Repository needs the password | a wrong password is refused |
| Repository has no plaintext | a search for a known marker string finds nothing |
| Age key from backup matches the live key | match |
| Backed-up age key decrypts a live SOPS Secret | `hermes.sops.yaml` decrypts |
| OpenViking memory recovered | the marker is in the restored `profile.md` |
| Hermes config, sessions and skills recovered | `config.yaml` (LiteLLM URL), `sessions/`, `skills/` and `state.db` (1.2 MB) are in the restored tree |
| Open WebUI users recovered | 1 user with role `admin` |
| LiteLLM virtual keys recovered | the aliases `hermes`, `open-webui` and `openviking` are present after `pg_restore` into a scratch Postgres |
| Grafana | the `grafana` snapshot restores with `grafana.db`; dashboards come from git (ConfigMaps), so they are not part of the backup check |

Not done in the drill: a full live restore over the running PVCs (destructive); a restore into a fresh cluster (needs a second k3s install).

## `wsl --export` fallback (not yet tested)

Coarse, whole-distro fallback, run from Windows (it cannot run from inside the distro it exports):

```powershell
wsl --shutdown
wsl --export Ubuntu D:\backups\dsm-shai-$(Get-Date -Format yyyyMMdd).tar
```

The export is the whole ext4 disk, so it is large: check the size before running it, and keep the cadence to weekly or less. This procedure has not been run on this host yet.
