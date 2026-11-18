#!/bin/bash
# Claude Haiku through the Claude Code CLI on the owner's subscription (spec 12). No API key, no API credits.
# Text in, text out: the prompt comes from stdin, the answer goes to stdout. The CLI gets no tools, so it cannot read files or run commands.
# Usage: claude-haiku.sh [--preflight] < prompt.txt
# Guards: disabled flag, one call at a time per slot (CLAUDE_HAIKU_PARALLEL, default 2), daily call cap, timeout, audit line (no prompt text).
set -u
STATE="${CLAUDE_HAIKU_STATE:-/opt/data/claude-haiku}"
CLI="${CLAUDE_BIN:-/opt/claude/bin/claude}"
MODEL="${CLAUDE_HAIKU_MODEL:-haiku}"          # the only place the model name is pinned
PAR="${CLAUDE_HAIKU_PARALLEL:-2}"
DAILY="${CLAUDE_HAIKU_DAILY_CALLS:-200}"
TMO="${CLAUDE_HAIKU_TIMEOUT:-120}"
mkdir -p "$STATE/slots" 2>/dev/null || { echo "claude-haiku: cannot write $STATE" >&2; exit 1; }

audit() { printf '{"ts":"%s","status":"%s","model":"%s","bytes_in":%s,"ms":%s}\n' "$(date -u +%FT%TZ)" "$1" "$MODEL" "${2:-0}" "${3:-0}" >> "$STATE/audit.jsonl"; }

if [ "${1:-}" = "--preflight" ]; then
  rc=0
  [ -x "$CLI" ] && echo "ok      claude CLI ($CLI)" || { echo "MISSING claude CLI at $CLI (see deploy/hermes/README.md, Claude Haiku)"; rc=1; }
  [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && echo "ok      subscription token present" || { echo "MISSING CLAUDE_CODE_OAUTH_TOKEN"; rc=1; }
  [ -z "${ANTHROPIC_API_KEY:-}" ] && echo "ok      no API key set" || { echo "FAIL    ANTHROPIC_API_KEY is set; it would bill API credits"; rc=1; }
  [ -f "$STATE/disabled" ] && echo "note    disabled flag is set"
  exit $rc
fi

# Never bill the API: a key in the environment would override the subscription token.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] || { echo "claude-haiku: not configured (CLAUDE_CODE_OAUTH_TOKEN missing)" >&2; audit not_configured; exit 3; }
[ -f "$STATE/disabled" ] && { echo "claude-haiku: disabled flag" >&2; audit disabled; exit 4; }

DAY="$(date +%F)"; CNT="$STATE/calls-$DAY"
n=$(cat "$CNT" 2>/dev/null || echo 0)
[ "$n" -ge "$DAILY" ] && { echo "claude-haiku: daily cap $DAILY reached" >&2; audit capped; exit 5; }

# Acquire one of PAR slots (flock), waiting up to TMO seconds.
got=""; i=0
while [ -z "$got" ] && [ "$i" -lt "$TMO" ]; do
  for s in $(seq 1 "$PAR"); do
    exec 8>"$STATE/slots/$s"
    if flock -n 8; then got=$s; break; fi
  done
  [ -z "$got" ] && { sleep 1; i=$((i+1)); }
done
[ -n "$got" ] || { echo "claude-haiku: no free slot" >&2; audit busy; exit 6; }

IN="$(mktemp)"; trap 'rm -f "$IN"' EXIT; cat > "$IN"
bytes=$(wc -c < "$IN"); t0=$(date +%s%3N)
echo $((n+1)) > "$CNT"
# --tools "": no tools. Telemetry and auto-update off; settings isolated on the PVC.
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-/opt/data/claude}" DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_TELEMETRY=1 \
  timeout "$TMO" "$CLI" -p --model "$MODEL" --tools "" --output-format text < "$IN"
rc=$?
audit "$([ $rc -eq 0 ] && echo ok || echo "error:$rc")" "$bytes" "$(( $(date +%s%3N) - t0 ))"
exit $rc
