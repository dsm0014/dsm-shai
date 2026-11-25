# Backup schedule (systemd user timer)

Install on the WSL host (systemd must be enabled in `/etc/wsl.conf`, `[boot] systemd=true`):

```sh
mkdir -p ~/.config/systemd/user
cp scripts/systemd/dsm-shai-backup.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dsm-shai-backup.timer
loginctl enable-linger "$USER"        # lets the timer run while no session is open
```

The service runs `scripts/backup.sh` at 03:30 local time (plus up to 10 minutes of random delay). `Persistent=true` runs a missed run at the next start. Check runs with `systemctl --user list-timers dsm-shai-backup.timer` and `journalctl --user -u dsm-shai-backup.service`. The last successful run time is in `~/.local/state/dsm-shai/last-success`.

The service path in `dsm-shai-backup.service` is absolute (`/mnt/c/Users/danth/Code/dsm-shai/...`). Edit it if the repository moves.

During each run, Hermes, OpenViking, Open WebUI and Grafana are scaled to zero for about 1 to 4 minutes each, then restored. Ollama and LiteLLM keep running.

# Swarm health check (systemd user timer, every 30 minutes)

`dsm-shai-health.timer` runs `scripts/swarm-health.sh` at :00 and :30. It checks Flux, the Hermes pod, the maintainer CronJob and its last run, repo-work failures, open swarm PRs, kill switches, GitHub reachability through Squid, ztunnel enrolment and unhealthy pods. Its one automatic fix is deleting ambient pods that ztunnel did not enrol (the runbook fix), capped at three pods per run. Everything else is reported with the action to take. Each run appends to `~/.local/state/dsm-shai/swarm-health.log`; the exit code is 0 when healthy, 1 when problems remain.

Install (after the backup timer):

```sh
cp scripts/systemd/dsm-shai-health.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dsm-shai-health.timer
```

Check runs with `systemctl --user list-timers dsm-shai-health.timer` and `tail ~/.local/state/dsm-shai/swarm-health.log`. Run once by hand with `bash scripts/swarm-health.sh --no-fix` to see the report without any fix.
