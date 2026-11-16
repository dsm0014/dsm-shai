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
