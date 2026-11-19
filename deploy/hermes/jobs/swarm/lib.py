"""Shared helpers for the swarm (spec 13). Standard library only (the image has no PyYAML).
State: SWARM_STATE (default /opt/data/swarm): audit.jsonl (append-only), digest.log, metrics.prom, runs/<id>/, locks/, disabled."""
import datetime, json, os, re, time

STATE = os.environ.get("SWARM_STATE", "/opt/data/swarm")
HAIKU_STATE = os.environ.get("CLAUDE_HAIKU_STATE", "/opt/data/claude-haiku")
TOKEN_RES = [re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"github[_]pat[_][A-Za-z0-9_]{20,}"),
             re.compile(r"sk-[A-Za-z0-9_-]{20,}")]


def redact(text):
    for r in TOKEN_RES:
        text = r.sub("[REDACTED]", text)
    return text


def today():
    return os.environ.get("SWARM_TODAY") or datetime.date.today().isoformat()


def audit(entry):
    """Append one JSON line with O_APPEND; never rewritten. No prompt or response text goes in."""
    os.makedirs(STATE, exist_ok=True)
    entry = dict(entry)
    entry.setdefault("ts", int(time.time()))
    entry.setdefault("date", today())
    fd = os.open(os.path.join(STATE, "audit.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (redact(json.dumps(entry, sort_keys=True)) + "\n").encode())
    finally:
        os.close(fd)
    return entry


def read_audit():
    out = []
    try:
        for line in open(os.path.join(STATE, "audit.jsonl")):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    except FileNotFoundError:
        pass
    return out


def digest(line):
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "digest.log"), "a") as f:
        f.write("%s swarm: %s\n" % (today(), redact(line)))


def write_metrics(entries=None):
    entries = read_audit() if entries is None else entries
    real = [e for e in entries if not e.get("dry_run") and e.get("status") in ("ok", "failed", "capped")]
    last_ok = max([e.get("ts", 0) for e in real if e.get("status") == "ok"] or [0])
    last = 1 if (not real or real[-1]["status"] == "ok") else 0
    calls = sum(int(e.get("haiku_calls", 0)) for e in entries if not e.get("dry_run"))
    body = ("# TYPE swarm_last_success_timestamp gauge\nswarm_last_success_timestamp %d\n"
            "# TYPE swarm_last_run_status gauge\nswarm_last_run_status %d\n"
            "# TYPE swarm_haiku_calls_total counter\nswarm_haiku_calls_total %d\n" % (last_ok, last, calls))
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, "metrics.prom.tmp")
    open(tmp, "w").write(body)
    os.replace(tmp, os.path.join(STATE, "metrics.prom"))
    return body


def disabled_reason(need_haiku):
    """Kill switches that are plain files. (`hermes pause` is checked by swarm.py through the hermes CLI.)"""
    if os.path.exists(os.path.join(STATE, "disabled")):
        return "swarm disabled flag"
    if need_haiku and os.path.exists(os.path.join(HAIKU_STATE, "disabled")):
        return "claude-haiku disabled flag"
    return None


def haiku_calls_today():
    try:
        return int(open(os.path.join(HAIKU_STATE, "calls-" + datetime.date.today().isoformat())).read().strip() or 0)
    except (OSError, ValueError):
        return 0


# ---- a restricted YAML subset: `key: value`, block lists (`- item`), values that are JSON (flow lists and maps) or plain scalars
def _scalar(v):
    v = v.strip()
    if v == "":
        return ""
    try:
        return json.loads(v)
    except ValueError:
        pass
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def load_task(path):
    """Parse a task file. Only top-level keys, block lists of scalars, and JSON flow values are supported."""
    out, key = {}, None
    for raw in open(path).read().splitlines():
        line = re.split(r"\s{2,}#", raw)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and key is not None and line.startswith((" ", "-")):
            if not isinstance(out.get(key), list):
                out[key] = []
            out[key].append(_scalar(line.lstrip()[2:]))
        elif ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            out[key] = _scalar(val) if val.strip() else None
        elif line.startswith(" ") and ":" in line and key is not None:  # one level of nested map
            if not isinstance(out.get(key), dict):
                out[key] = {}
            k2, _, v2 = line.strip().partition(":")
            out[key][k2.strip()] = _scalar(v2)
        else:
            raise ValueError("unsupported task syntax: %r" % raw)
    for k, v in list(out.items()):
        if v is None:
            out[k] = []
    return out
