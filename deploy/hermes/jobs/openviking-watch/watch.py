#!/usr/bin/env python3
"""Watch the OpenViking link from Hermes (spec 17 follow-up, 2026-11-25).

Reads the gateway log from the last run and reports MCP parks of the 'openviking' server (the link dropped and Hermes
stopped using it until a reconnect). Also checks OpenViking's /health from this pod. Prints one line per problem and
nothing when all is well, so a no-agent cron job posts only when there is something to see.

Offline tests: deploy/hermes/jobs/openviking-watch/tests/test_watch.py (no cluster needed).
"""
import json
import os
import sys
import urllib.request

LOG = os.environ.get("OV_WATCH_LOG", "/opt/data/logs/gateway.log")
STATE = os.environ.get("OV_WATCH_STATE", "/opt/data/openviking-watch.state")
HEALTH = os.environ.get("OV_WATCH_HEALTH", "http://openviking.openviking.svc:1933/health")
PARK_MARKERS = ("MCP server 'openviking' failed initial connection", "MCP server 'openviking' parked")


def read_offset():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return int(json.load(fh).get("offset", 0))
    except (OSError, ValueError):
        return 0


def write_offset(offset):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"offset": offset}, fh)
    os.replace(tmp, STATE)


def new_park_lines():
    """Return (park_lines, new_offset) for log bytes written since the last run."""
    try:
        size = os.path.getsize(LOG)
    except OSError:
        return [], 0
    offset = read_offset()
    if size < offset:  # the log was rotated or truncated: start again
        offset = 0
    with open(LOG, "rb") as fh:
        fh.seek(offset)
        chunk = fh.read().decode("utf-8", errors="replace")
    parks = [line.strip() for line in chunk.splitlines() if any(m in line for m in PARK_MARKERS)]
    return parks, size


def health_problem():
    try:
        with urllib.request.urlopen(HEALTH, timeout=10) as resp:
            if resp.status == 200:
                return None
            return f"OpenViking health returned HTTP {resp.status}"
    except Exception as exc:  # any failure to reach it is the signal we want
        return f"OpenViking health check failed: {type(exc).__name__}: {str(exc)[:120]}"


def main():
    parks, new_offset = new_park_lines()
    problems = []
    if parks:
        last = parks[-1][:160]
        problems.append(f"openviking-watch: {len(parks)} MCP park(s) since the last run; last: {last}")
    health = health_problem()
    if health:
        problems.append(f"openviking-watch: {health}")
    write_offset(new_offset)
    for line in problems:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
