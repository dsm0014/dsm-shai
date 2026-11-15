#!/usr/bin/env bash
# Host prep: enable systemd in WSL and check the Windows profile's .wslconfig (/mnt/c/Users/<you>/.wslconfig). Idempotent. Run with sudo.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root

WSL_CONF=/etc/wsl.conf
if grep -Eq '^\s*systemd\s*=\s*true\s*$' "$WSL_CONF" 2>/dev/null; then
  log "systemd already enabled in $WSL_CONF"
else
  touch "$WSL_CONF"
  if grep -Eq '^\s*systemd\s*=' "$WSL_CONF"; then
    sed -i -E 's/^\s*systemd\s*=.*/systemd=true/' "$WSL_CONF"
  elif grep -Eq '^\[boot\]' "$WSL_CONF"; then
    sed -i '/^\[boot\]/a systemd=true' "$WSL_CONF"
  else
    printf '\n[boot]\nsystemd=true\n' >>"$WSL_CONF"
  fi
  changed "enabled systemd in $WSL_CONF (run 'wsl --shutdown' from Windows, then restart WSL)"
fi

win_profile=""
if command -v cmd.exe >/dev/null 2>&1; then
  win_profile=$(cd /mnt/c && cmd.exe /c 'echo %UserProfile%' 2>/dev/null | tr -d '\r' || true)
  [ -n "$win_profile" ] && win_profile=$(wslpath "$win_profile")
fi

if [ -z "$win_profile" ] || [ ! -d "$win_profile" ]; then
  log "WARNING: cannot locate the Windows profile; copy windows/wslconfig.example to /mnt/c/Users/<you>/.wslconfig manually"
else
  wslconfig="$win_profile/.wslconfig"
  if [ ! -f "$wslconfig" ]; then
    install -m 0644 "$REPO_ROOT/windows/wslconfig.example" "$wslconfig"
    changed "created $wslconfig (run 'wsl --shutdown' from Windows, then restart WSL)"
  elif grep -Eiq '^\s*memory\s*=\s*24GB\s*$' "$wslconfig"; then
    log "$wslconfig already sets memory=24GB"
  else
    log "WARNING: $wslconfig exists without memory=24GB; merge windows/wslconfig.example into it, then run 'wsl --shutdown'"
  fi
fi

total_mb=$(free -m | awk '/^Mem:/ {print $2}')
if [ "$total_mb" -lt 23552 ]; then
  log "WARNING: WSL sees ${total_mb}MB RAM (< 23GB); .wslconfig has not taken effect yet"
fi
