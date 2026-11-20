"""Pick the next swarm-eligible task from a task list (spec 14). A script picks, never a model.
Eligible: an unstarted `- [ ]` item carrying the marker `[swarm]`, with a backtick file list, outside the excluded headings,
not marked `[needs-owner]`. `[swarm-deploy]` additionally allows manifests and mesh or egress config."""
import re

EXCLUDED_HEADINGS = ("needs you at the machine", "proposed, not decided", "not planned")
PATH_RE = re.compile(r"`([A-Za-z0-9_.][A-Za-z0-9_./-]*)`")
NEVER_WORKER_PATHS = (".specter/tasklist.md",)
BARE_NAMES = ("Makefile", "Dockerfile", "LICENSE")


def paths_in(text):
    """Backtick tokens that look like repo paths: contain a slash or a file extension, no wildcard or space."""
    out = []
    for m in PATH_RE.findall(text):
        if m.startswith(("http", "make", "git ")):
            continue
        if ("/" in m or m in BARE_NAMES or re.search(r"\.[A-Za-z0-9]{1,5}$", m)) and ".." not in m.split("/") and not m.startswith("/"):
            if m not in out and m not in NEVER_WORKER_PATHS:
                out.append(m)
    return out


def pick(markdown, reject=None):
    """Return {"line": n, "text": str, "files": [...], "deploy": bool} for the first eligible task, plus skipped reasons.
    `reject(files, deploy)` may return a reason string: that task is skipped and the next one is tried, so one unrunnable
    task never blocks the queue. Result: (task or None, [(line_no, reason), ...])."""
    skipped, excluded_level = [], None
    for n, line in enumerate(markdown.splitlines(), 1):
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line.lstrip("#").strip().lower()
            if excluded_level is not None and level <= excluded_level:
                excluded_level = None  # a heading at the same or a higher level ends the excluded section
            if excluded_level is None and any(h in title for h in EXCLUDED_HEADINGS):
                excluded_level = level
            continue
        m = re.match(r"^\s*- \[(.)\] (.*)$", line)
        if not m:
            continue
        state, body = m.groups()
        if "[swarm" not in body:
            continue
        if state != " ":
            skipped.append((n, "not unstarted")); continue
        if excluded_level is not None:
            skipped.append((n, "excluded heading")); continue
        if "[needs-owner]" in body:
            skipped.append((n, "needs-owner")); continue
        if not re.search(r"\[swarm(-deploy)?\]", body):
            skipped.append((n, "bad marker")); continue
        files = paths_in(body)
        if not files:
            skipped.append((n, "no file list")); continue
        deploy = "[swarm-deploy]" in body
        why = reject(files, deploy) if reject else None
        if why:
            skipped.append((n, why)); continue
        return ({"line": n, "text": body, "files": files, "deploy": deploy}, skipped)
    return (None, skipped)
