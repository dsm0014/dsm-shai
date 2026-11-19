"""Shared helpers for the nightly specter job (spec 11). Standard library only.

State lives under NIGHTLY_STATE (default /opt/data/nightly-specter): audit.jsonl (append-only), runs/<date>.json,
metrics.prom, lock. Nothing in this file talks to the network or to the model.
"""
import datetime, json, os, re, sys, time

STATE = os.environ.get("NIGHTLY_STATE", "/opt/data/nightly-specter")
TOKEN_RES = [re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"github[_]pat[_][A-Za-z0-9_]{20,}"),
             re.compile(r"sk-[0-9a-f]{20,}")]


def redact(text):
    for r in TOKEN_RES:
        text = r.sub("[REDACTED]", text)
    return text


def today():
    return os.environ.get("NIGHTLY_TODAY") or datetime.date.today().isoformat()


def audit_path():
    return os.path.join(STATE, "audit.jsonl")


def audit(entry):
    """Append one JSON line. O_APPEND, never rewritten."""
    os.makedirs(STATE, exist_ok=True)
    entry = dict(entry)
    entry.setdefault("ts", int(time.time()))
    entry.setdefault("date", today())
    line = redact(json.dumps(entry, sort_keys=True)) + "\n"
    fd = os.open(audit_path(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)
    return entry


def read_audit():
    out = []
    try:
        for line in open(audit_path()):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass  # a corrupt line never counts as a clean night
    except FileNotFoundError:
        pass
    return out


def clean_nights(entries=None):
    """Consecutive most-recent runs that ended status ok (not dry-run), stopping at any failure or revert.
    Missing or unreadable audit gives 0, which fails safe: implementation PRs are held."""
    entries = read_audit() if entries is None else entries
    n = 0
    for e in reversed(entries):
        st = e.get("status")
        if e.get("dry_run") or st in ("skipped", "held", "not_configured", "paused", "refused"):
            continue
        if st == "ok":
            n += 1
        else:  # failed, revert, anything else resets the streak
            break
    return n


def consecutive_failures(entries=None):
    entries = read_audit() if entries is None else entries
    n = 0
    for e in reversed(entries):
        st = e.get("status")
        if e.get("dry_run") or st in ("skipped", "held", "not_configured", "paused", "refused"):
            continue
        if st == "failed":
            n += 1
        else:
            break
    return n


def write_metrics(entries=None):
    entries = read_audit() if entries is None else entries
    last_ok = max([e.get("ts", 0) for e in entries if e.get("status") == "ok" and not e.get("dry_run")] or [0])
    real = [e for e in entries if not e.get("dry_run") and e.get("status") in ("ok", "failed")]
    last = 1 if (real and real[-1]["status"] == "ok") else (0 if real else 1)
    body = ("# TYPE nightly_specter_last_success_timestamp gauge\nnightly_specter_last_success_timestamp %d\n"
            "# TYPE nightly_specter_last_run_status gauge\nnightly_specter_last_run_status %d\n"
            "# TYPE nightly_specter_consecutive_failures gauge\nnightly_specter_consecutive_failures %d\n"
            % (last_ok, last, consecutive_failures(entries)))
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, "metrics.prom.tmp")
    open(tmp, "w").write(body)
    os.replace(tmp, os.path.join(STATE, "metrics.prom"))
    return body


def state_file(date=None):
    return os.path.join(STATE, "runs", (date or today()) + ".json")


def have_real_run_today():
    return os.path.exists(state_file())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "record-revert":  # operator tool: a merged nightly PR was reverted, reset the clean-night count
        audit({"status": "revert", "reason": " ".join(sys.argv[2:]) or "manual revert"})
        write_metrics()
    elif cmd == "clean-nights":
        print(clean_nights())
    elif cmd == "metrics":
        sys.stdout.write(write_metrics())
    else:
        sys.exit("usage: lib.py record-revert [reason] | clean-nights | metrics")


def digest(line):
    """Append one line to the daily digest (the primary failure alert; metrics.prom is for dashboards)."""
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "digest.log"), "a") as f:
        f.write("%s nightly-specter: %s\n" % (today(), redact(line)))
