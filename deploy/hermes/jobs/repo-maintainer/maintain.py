"""Repo maintainer loop (spec 16): review open swarm PRs with script gates and a Haiku veto, merge the good ones, then start the
next repo-work task. Usage: maintain.py [--plan] [--repo owner/name] | --preflight | revert <owner/name> <pr>
Exit codes: 0 ok or skipped, 1 failed, 2 refused or usage. A model can only veto: a merge needs every gate AND a `merge` verdict."""
import fcntl, hashlib, json, os, re, shutil, subprocess, sys, time, urllib.error, urllib.request
SWARM_DIR = os.environ.get("SWARM_DIR", "/opt/jobs/swarm")
sys.path.insert(0, SWARM_DIR)
import lib, pick_task, repo_work, swarm, workers

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("MAINT_STATE", "/opt/data/maintainer")
SWARM_STATE = os.environ.get("SWARM_STATE", "/opt/data/swarm")
MODES = ("observe", "merge", "merge-and-run")
SEVERE = ("forbidden", "foreign", "unticked", "deletion", "tasklist")  # gate failures that close instead of waiting for a fix
DEFAULTS = {"mode": "observe", "max_merges_per_run": 1, "max_merges_per_day": 100, "max_attempts": 2, "reviewer": "haiku",
            "branch_prefix": "swarm/", "tasklist_path": ".specter/tasklist.md", "merge_deploy": False, "auto_queue": False}


class Refused(Exception):
    pass


def envint(n, d):
    try:
        return int(os.environ.get(n, d))
    except ValueError:
        return d


def csv(name):
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


# ---- state, audit, digest, metrics (own files; same redaction as the swarm) --------------------------------------------------
def audit(entry):
    os.makedirs(STATE, exist_ok=True)
    entry = dict(entry, ts=int(time.time()), date=lib.today())
    fd = os.open(os.path.join(STATE, "audit.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (lib.redact(json.dumps(entry, sort_keys=True)) + "\n").encode())
    finally:
        os.close(fd)


def read_audit():
    out = []
    try:
        for l in open(os.path.join(STATE, "audit.jsonl")):
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    except FileNotFoundError:
        pass
    return out


def digest(line):
    os.makedirs(STATE, exist_ok=True)
    open(os.path.join(STATE, "digest.log"), "a").write("%s maintainer: %s\n" % (lib.today(), lib.redact(line)))


def write_metrics():
    e = [x for x in read_audit() if not x.get("plan")]
    runs = [x for x in e if x.get("event") == "run"]
    ok = max([x["ts"] for x in runs if x.get("status") == "ok"] or [0])
    last = 1 if (not runs or runs[-1].get("status") == "ok") else 0
    body = ("# TYPE maintainer_last_success_timestamp gauge\nmaintainer_last_success_timestamp %d\n"
            "# TYPE maintainer_last_run_status gauge\nmaintainer_last_run_status %d\n"
            "# TYPE maintainer_merges_total counter\nmaintainer_merges_total %d\n"
            "# TYPE maintainer_closed_total counter\nmaintainer_closed_total %d\n"
            % (ok, last, sum(1 for x in e if x.get("event") == "merge"), sum(1 for x in e if x.get("event") == "close")))
    os.makedirs(STATE, exist_ok=True)
    open(os.path.join(STATE, "metrics.prom.tmp"), "w").write(body)
    os.replace(os.path.join(STATE, "metrics.prom.tmp"), os.path.join(STATE, "metrics.prom"))


def attempts_path():
    return os.path.join(STATE, "attempts.json")


def attempts():
    try:
        return json.load(open(attempts_path()))
    except (OSError, ValueError):
        return {}


def bump_attempt(key):
    a = attempts()
    a[key] = a.get(key, 0) + 1
    os.makedirs(STATE, exist_ok=True)
    json.dump(a, open(attempts_path(), "w"))
    return a[key]


# ---- configuration -----------------------------------------------------------------------------------------------------------
def load_repos():
    """{repo: settings}. repos.yaml (one section per repo) wins over MAINT_REPOS; both are filtered by the double allowlist."""
    cfg = {}
    path = os.environ.get("MAINT_REPOS_FILE", os.path.join(HERE, "repos.yaml"))
    if os.path.exists(path):
        cfg = {k: v for k, v in lib.load_task(path).items() if isinstance(v, dict) or v in ([], None)}
        cfg = {k: (v if isinstance(v, dict) else {}) for k, v in cfg.items()}
    for r in csv("MAINT_REPOS"):
        cfg.setdefault(r, {})
    out = {}
    for repo, over in cfg.items():
        s = dict(DEFAULTS, mode=os.environ.get("MAINT_MODE_DEFAULT", "observe"), reviewer=os.environ.get("MAINT_REVIEWER", "haiku"),
                 max_merges_per_day=envint("MAINT_MAX_MERGES_PER_DAY", DEFAULTS["max_merges_per_day"]),  # env sets the default; repos.yaml overrides per repo
                 max_merges_per_run=envint("MAINT_MAX_MERGES_PER_RUN", DEFAULTS["max_merges_per_run"]))
        s.update(over)
        s["repo"] = repo
        out[repo] = s
    return out


def check_repo(repo):
    if os.environ.get("MAINT_MODE") == "off":
        raise Refused("MAINT_MODE=off")
    for var in ("MAINT_ALLOWED_REPOS", "SWARM_ALLOWED_REPOS"):
        if repo not in csv(var):
            raise Refused("repo %s is not in %s (unset means none)" % (repo, var))


# ---- GitHub (GET, POST, PUT for merge, PATCH to close, DELETE for the branch) ----------------------------------------------------
def api(method, path, body=None, raw=False):
    return repo_work.api(method, path, body, raw)


def pull_files(repo, n):
    out, page = [], 1
    while True:
        chunk = api("GET", "/repos/%s/pulls/%d/files?per_page=100&page=%d" % (repo, n, page))
        out += chunk
        if len(chunk) < 100:
            return out
        page += 1


def red(repo, sha):
    runs = api("GET", "/repos/%s/commits/%s/check-runs" % (repo, sha)).get("check_runs", [])
    return any(r.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required") for r in runs)


# ---- gates -------------------------------------------------------------------------------------------------------------------
def patch_lines(patch):
    rem, add = [], []
    for l in (patch or "").splitlines():  # GitHub's `patch` has hunks only (no file headers), so every +/- line is a real change
        if l.startswith("@@") or l.startswith("\\"):
            continue
        if l.startswith("+"):
            add.append(l[1:])
        elif l.startswith("-"):
            rem.append(l[1:])
    return rem, add


def gates(settings, pr, files, default_red):
    """Return (failures, task) where failures is a list of (category, message). Everything here is computed from the real diff."""
    fails, tl = [], settings["tasklist_path"]
    by = {f["filename"]: f for f in files}
    for f in files:  # a rename away from a forbidden path is still a change to it
        if f.get("previous_filename") and repo_work.forbidden(f["previous_filename"]):
            fails.append(("forbidden", "renamed from forbidden path %s" % f["previous_filename"]))
    task = None
    t = by.get(tl)
    if not t:
        fails.append(("tasklist", "the task list file is not part of the change"))
    else:
        rem, add = patch_lines(t.get("patch"))
        if add or len(rem) != 1 or not re.match(r"^\s*- \[ \] \[swarm(-deploy)?\]", rem[0]):
            fails.append(("tasklist", "the task list change must remove exactly one unstarted [swarm] line and nothing else"))
        else:
            task = {"text": rem[0].strip(), "files": pick_task.paths_in(rem[0]), "deploy": "[swarm-deploy]" in rem[0]}
    if task and not task["files"]:
        fails.append(("tasklist", "the task names no file"))
    if task and not [f for f in by if f != tl]:
        fails.append(("tasklist", "the change touches only the task list"))
    named = set(task["files"]) if task else set()
    for f in by:
        if f == tl:
            continue
        if repo_work.forbidden(f):
            fails.append(("forbidden", "forbidden path %s" % f))
        elif task and f not in named:
            fails.append(("foreign", "%s is not a file the task names" % f))
    if task and not task["deploy"] and any(repo_work.deploy_class(f) for f in by):
        fails.append(("forbidden", "deploy-class path without [swarm-deploy]"))
    if task and task["deploy"] and any(repo_work.deploy_class(f) for f in by) and not settings.get("merge_deploy"):
        fails.append(("deploy", "deploy-class change needs the owner (merge_deploy is false)"))
    adds = sum(f.get("additions", 0) for f in files if f["filename"] != tl)
    dels = sum(f.get("deletions", 0) for f in files if f["filename"] != tl)
    if len(files) > envint("SWARM_MAX_FILES", 6) + 1 or adds + dels > envint("SWARM_MAX_LINES", 300):
        fails.append(("caps", "over the file or line cap (%d files, %d lines)" % (len(files), adds + dels)))
    if dels > 10 + 2 * adds:
        fails.append(("deletion", "deletes %d lines while adding %d (a cut-down file)" % (dels, adds)))
    for f in files:  # a removed markdown heading is lost structure, even in a +1/-2 change (the first live review caught one)
        if f["filename"].endswith(".md") and f["filename"] != tl and not (task and re.search(r"\brename\b", task["text"], re.I)):
            rem, add = patch_lines(f.get("patch"))
            lost = [r for r in rem if re.match(r"^#{1,6} \S", r) and r not in add]
            if lost:
                fails.append(("structure", "%s drops the heading %r" % (f["filename"], lost[0][:50])))
    for f in files:  # a verified criterion must never be unticked (PR 60)
        rem, add = patch_lines(f.get("patch"))
        ticked = [r.lstrip()[len("- [x]"):].strip()[:40] for r in rem if r.lstrip().startswith("- [x]")]
        for a in add:
            if a.lstrip().startswith("- [ ]") and any(a.lstrip()[len("- [ ]"):].strip().startswith(t_[:25]) for t_ in ticked if t_):
                fails.append(("unticked", "a verified [x] criterion became [ ] in %s" % f["filename"]))
                break
    if pr.get("mergeable_state") in ("behind", "dirty") or pr.get("mergeable") is False:
        fails.append(("stale", "head is %s the default branch" % pr.get("mergeable_state")))
    if default_red:
        fails.append(("red", "the default branch's last check run is red"))
    return fails, task


def run_tests(settings, pr, workdir):
    """Fresh clone of the PR head; run the repo's test command. Returns (ok, message)."""
    repo = settings["repo"]
    url = os.environ.get("MAINT_CLONE_URL") or "https://github.com/%s.git" % repo
    try:
        subprocess.run(["git", "clone", "--quiet", "--depth", "50", "--branch", pr["head"]["ref"], url, workdir], capture_output=True, text=True, timeout=600, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workdir, capture_output=True, text=True).stdout.strip()
        if sha != pr["head"]["sha"]:
            return (False, "the branch moved since the PR was read")
        cmd = settings.get("test_cmd") or os.environ.get("MAINT_TEST_CMD") or ("make test" if os.path.exists(os.path.join(workdir, "Makefile")) and re.search(r"^test:", open(os.path.join(workdir, "Makefile")).read(), re.M) else "")
        if os.path.exists(os.path.join(workdir, "scripts/check-sops.sh")):
            cmd = (cmd + " && " if cmd else "") + "bash scripts/check-sops.sh"
        if not cmd:
            return (True, "no test command")
        t = subprocess.run(["bash", "-c", cmd], cwd=workdir, capture_output=True, text=True, timeout=envint("MAINT_TEST_TIMEOUT", 1500))
        return (t.returncode == 0, "tests exit %d" % t.returncode)
    except (subprocess.SubprocessError, OSError) as e:
        return (False, "test run failed: %s" % type(e).__name__)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---- reviewer (veto only) ----------------------------------------------------------------------------------------------------
def parse_verdict(text):
    try:
        v = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        return None
    if not isinstance(v, dict) or v.get("verdict") not in ("merge", "fix", "close"):
        return None
    for k in ("reasons", "concerns"):
        if not isinstance(v.get(k, []), list) or not all(isinstance(x, str) for x in v.get(k, [])):
            return None
    return {"verdict": v["verdict"], "reasons": [x[:200] for x in v.get("reasons", [])][:6], "concerns": [x[:200] for x in v.get("concerns", [])][:6]}


def verdicts_path():
    return os.path.join(STATE, "verdicts.json")


def cached_verdict(key):
    try:
        return json.load(open(verdicts_path())).get(key)
    except (OSError, ValueError):
        return None


def cache_verdict(key, verdict):
    try:
        data = json.load(open(verdicts_path()))
    except (OSError, ValueError):
        data = {}
    data[key] = verdict
    for old in list(data)[:-200]:  # keep the last 200
        del data[old]
    os.makedirs(STATE, exist_ok=True)
    json.dump(data, open(verdicts_path(), "w"))


def review(settings, task, files, counters, key=None):
    """Returns a verdict dict. One review per PR head: a model that answers differently on a second ask must not flip the outcome.
    Any failure to get a clean verdict is `fix` (never merge) and is not cached, so a transient outage is retried."""
    hit = cached_verdict(key) if key else None
    if hit:
        return hit
    v = _review(settings, task, files, counters)
    if key and not any("unavailable" in c or "cap reached" in c or "not a valid verdict" in c for c in v.get("concerns", [])):
        cache_verdict(key, v)
    return v


def _review(settings, task, files, counters):
    diff = "\n\n".join("### %s\n%s" % (f["filename"], (f.get("patch") or "(no textual patch)")[:6000]) for f in files)[:30000]
    prompt = open(os.path.join(HERE, "prompts", "review.v1.txt")).read().replace("{{task}}", task["text"] if task else "").replace(
        "{{diff}}", workers.untrusted("pull request diff", diff))
    mode = settings["reviewer"]
    if mode == "chat":
        docs_only = all(f["filename"].endswith(".md") for f in files)
        if not docs_only or sum(f.get("additions", 0) + f.get("deletions", 0) for f in files) > envint("MAINT_CHAT_MAX_LINES", 40):
            return {"verdict": "fix", "reasons": [], "concerns": ["local reviewer may only approve small markdown-only changes"]}
    try:
        if mode == "haiku":
            if counters["haiku"] >= envint("MAINT_MAX_HAIKU_CALLS", 12):
                return {"verdict": "fix", "reasons": [], "concerns": ["Haiku call cap reached"]}
            counters["haiku"] += 1
            text, _ = workers.call_haiku(prompt)
        else:
            text, _ = workers.call_chat(prompt, json_mode=True)
    except workers.WorkerError as e:
        return {"verdict": "fix", "reasons": [], "concerns": ["reviewer unavailable: %s" % str(e)[:80]]}
    return parse_verdict(text) or {"verdict": "fix", "reasons": [], "concerns": ["reviewer reply was not a valid verdict"]}


# ---- actions -----------------------------------------------------------------------------------------------------------------
def remember_outcome(repo, n, task_text, outcome, why):
    """A short OpenViking record of one maintainer outcome (spec 16 memory). Best effort; returns True when it was stored."""
    where = "pull request #%d" % n if n else "the maintainer run"
    user = "Repo maintainer on %s, %s, task %r, %s." % (repo, where, (task_text or "none")[:160], lib.today())
    return swarm.remember_exchange(user, "Outcome: %s. %s" % (outcome, why[:600]))

def comment_once(repo, n, sha, text, plan, kind="note"):
    marker = "<!-- maintainer:%s:%s -->" % (sha[:12], kind)  # one comment per head and outcome kind, whatever the wording
    if plan:
        return False
    if any(marker in (c.get("body") or "") for c in api("GET", "/repos/%s/issues/%d/comments?per_page=100" % (repo, n))):
        return False
    api("POST", "/repos/%s/issues/%d/comments" % (repo, n), {"body": text + "\n\n" + marker})
    return True


def merge_pr(repo, n, sha):
    """The only merge call in the job. Refuses when the head moved since review."""
    cur = api("GET", "/repos/%s/pulls/%d" % (repo, n))
    if cur["head"]["sha"] != sha or cur.get("state") != "open":
        raise Refused("PR %d changed since review" % n)
    res = api("PUT", "/repos/%s/pulls/%d/merge" % (repo, n), {"sha": sha, "merge_method": "merge"})
    try:
        api("DELETE", "/repos/%s/git/refs/heads/%s" % (repo, cur["head"]["ref"]))
    except (urllib.error.URLError, OSError):
        pass
    return res.get("sha", "")


def close_pr(repo, n, ref):
    api("PATCH", "/repos/%s/pulls/%d" % (repo, n), {"state": "closed"})
    try:
        api("DELETE", "/repos/%s/git/refs/heads/%s" % (repo, ref))
    except (urllib.error.URLError, OSError):
        pass


GIT_ID = {"GIT_AUTHOR_NAME": "Hermes maintainer", "GIT_COMMITTER_NAME": "Hermes maintainer",
          "GIT_AUTHOR_EMAIL": "hermes@maintainer.invalid", "GIT_COMMITTER_EMAIL": "hermes@maintainer.invalid"}


def edit_tasklist_pr(settings, line_text, transform, branch, title):
    """Clone, change one task line with `transform`, push a `maintainer/` branch, open a labelled PR. Never merges it."""
    repo = settings["repo"]
    work = os.path.join(os.environ.get("SWARM_WORK", "/workspace"), "maint-" + branch.split("/")[-1])
    url = os.environ.get("MAINT_CLONE_URL") or "https://github.com/%s.git" % repo
    default = api("GET", "/repos/%s" % repo).get("default_branch", "main")
    try:
        subprocess.run(["git", "clone", "--quiet", "--depth", "20", "--branch", default, url, work], capture_output=True, text=True, timeout=600, check=True)
        p = os.path.join(work, settings["tasklist_path"])
        text = open(p).read()
        if line_text not in text:
            return ""
        open(p, "w").write(text.replace(line_text, transform(line_text), 1))
        for c in (["checkout", "-q", "-b", branch], ["add", "-A"], ["commit", "-q", "-m", title], ["push", "-q", "origin", branch]):
            subprocess.run(["git"] + c, cwd=work, capture_output=True, text=True, timeout=300, check=True, env=dict(GIT_ID, **os.environ))
        pr = api("POST", "/repos/%s/pulls" % repo, {"title": title, "head": branch, "base": default, "body": "Opened by the repo maintainer. It never merges its own task-list changes."})
        try:
            api("POST", "/repos/%s/issues/%d/labels" % (repo, pr["number"]), {"labels": ["maintainer"]})
        except (urllib.error.URLError, OSError):
            pass
        return pr.get("html_url", "")
    except (subprocess.SubprocessError, OSError, urllib.error.URLError):
        return ""
    finally:
        shutil.rmtree(work, ignore_errors=True)


def revert(repo, n):
    """Open a revert PR for a merged PR. It never merges it."""
    check_repo(repo)
    pr = api("GET", "/repos/%s/pulls/%d" % (repo, n))
    sha = pr.get("merge_commit_sha")
    if not pr.get("merged") or not sha:
        raise Refused("PR %d is not merged" % n)
    work = os.path.join(os.environ.get("SWARM_WORK", "/workspace"), "maint-revert-%d" % n)
    url = os.environ.get("MAINT_CLONE_URL") or "https://github.com/%s.git" % repo
    default = api("GET", "/repos/%s" % repo).get("default_branch", "main")
    branch = "maintainer/revert-%d" % n
    try:
        for c in (["clone", "--quiet", "--branch", default, url, work],):
            subprocess.run(["git"] + c, capture_output=True, text=True, timeout=600, check=True)
        for c in (["checkout", "-q", "-b", branch], ["revert", "-m", "1", "--no-edit", sha], ["push", "-q", "origin", branch]):
            subprocess.run(["git"] + c, cwd=work, capture_output=True, text=True, timeout=300, check=True, env=dict(GIT_ID, **os.environ))
        out = api("POST", "/repos/%s/pulls" % repo, {"title": "Revert PR #%d" % n, "head": branch, "base": default, "body": "Opened by `maintain.py revert`. Review and merge it yourself."})
        return out.get("html_url", "")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def queue_candidate(markdown, settings):
    """First unstarted, unmarked task a worker can do: a short line naming 1 to 3 existing small files, outside the excluded sections."""
    excluded = None
    for n, line in enumerate(markdown.splitlines(), 1):
        if line.startswith("#"):
            level, title = len(line) - len(line.lstrip("#")), line.lstrip("#").strip().lower()
            if excluded is not None and level <= excluded:
                excluded = None
            if excluded is None and any(h in title for h in pick_task.EXCLUDED_HEADINGS):
                excluded = level
            continue
        m = re.match(r"^\s*- \[ \] (.*)$", line)
        if not m or excluded is not None or "[swarm" in m.group(1) or "[needs-owner]" in m.group(1) or len(m.group(1)) > 600:
            continue
        files = pick_task.paths_in(m.group(1))
        if not files or len(files) > 3 or any(repo_work.forbidden(f) or repo_work.deploy_class(f) for f in files):
            continue
        try:
            sizes = [api("GET", "/repos/%s/contents/%s" % (settings["repo"], f)) for f in files]
        except (urllib.error.URLError, OSError):
            continue
        if all(isinstance(s, dict) and s.get("type") == "file" and s.get("size", 10**9) <= envint("SWARM_MAX_FILE_CHARS", 24000) for s in sizes):
            return line.strip()
    return ""


def auto_queue(settings):
    repo = settings["repo"]
    md = api("GET", "/repos/%s/contents/%s" % (repo, settings["tasklist_path"]), raw=True)
    if pick_task.pick(md)[0]:
        return ""  # a task is already queued
    line = queue_candidate(md, settings)
    if not line:
        return ""
    key = hashlib.sha1((repo + line).encode()).hexdigest()[:10]
    return edit_tasklist_pr(settings, line, lambda l: l.replace("- [ ] ", "- [ ] [swarm] ", 1), "maintainer/queue-" + key, "maintainer: queue a task for the swarm")


def start_repo_work(settings):
    """Run the spec 14 job for this repo once. The maintainer's `merge-and-run` mode is the opt-in for SWARM_REPO_WORK."""
    repo = settings["repo"]
    os.makedirs(os.path.join(STATE, "tasks"), exist_ok=True)
    tf = os.path.join(STATE, "tasks", re.sub(r"[^a-z0-9]+", "-", repo.lower()) + ".yaml")
    open(tf, "w").write("name: repo-work-%s\nkind: repo_work\nrepo: %s\ngoal: Complete the next [swarm] task from the repository task list.\n"
                        "max_steps: 6\nmax_haiku_calls: 8\ntimeout_minutes: 60\nmin_chars: 20\n" % (re.sub(r"[^a-z0-9]+", "-", repo.lower()), repo))
    env = dict(os.environ, SWARM_REPO_WORK="1")
    p = subprocess.run([sys.executable, "-I", os.path.join(SWARM_DIR, "swarm.py"), tf], env=env, capture_output=True, text=True, timeout=envint("MAINT_WORK_TIMEOUT", 7200))
    return lib.redact((p.stdout.strip().splitlines() or [""])[-1])[:200]


# ---- one repository ----------------------------------------------------------------------------------------------------------
def maintain_repo(settings, plan, counters):
    repo, mode = settings["repo"], settings["mode"]
    if mode not in MODES:
        raise Refused("bad mode %r" % mode)
    report = {"repo": repo, "mode": mode, "prs": [], "merged": 0, "closed": 0}
    login = api("GET", "/user").get("login", "")
    default = api("GET", "/repos/%s" % repo).get("default_branch", "main")
    default_sha = api("GET", "/repos/%s/branches/%s" % (repo, default)).get("commit", {}).get("sha", "")
    default_red = red(repo, default_sha) if default_sha else False
    today_merges = sum(1 for e in read_audit() if e.get("event") == "merge" and e.get("date") == lib.today() and e.get("repo") == repo)
    for p in api("GET", "/repos/%s/pulls?state=open&per_page=100" % repo):
        n = p["number"]
        pr = api("GET", "/repos/%s/pulls/%d" % (repo, n))
        labels = [l["name"] for l in pr.get("labels", [])]
        if not pr["head"]["ref"].startswith(settings["branch_prefix"]) or (pr.get("user") or {}).get("login") != login or "swarm" not in labels:
            report["prs"].append({"pr": n, "skip": "not a swarm PR from this account"})
            continue
        files = pull_files(repo, n)
        fails, task = gates(settings, pr, files, default_red)
        if red(repo, pr["head"]["sha"]):  # the PR's own check runs must not be red
            fails.append(("checks", "a check run on the PR head failed"))
        ok_tests, test_msg = (False, "skipped: earlier gate failed")
        if not fails:
            ok_tests, test_msg = run_tests(settings, pr, os.path.join(os.environ.get("SWARM_WORK", "/workspace"), "maint-%d" % n))
            if not ok_tests:
                fails.append(("tests", test_msg))
        verdict = review(settings, task, files, counters, key=repo + ":" + str(n) + ":" + pr["head"]["sha"]) if not fails else {"verdict": "close" if any(c in SEVERE for c, _ in fails) else "fix", "reasons": [], "concerns": []}
        outcome = "merge" if (not fails and verdict["verdict"] == "merge") else ("close" if verdict["verdict"] == "close" or any(c in SEVERE for c, _ in fails) else "fix")
        if outcome == "fix" and mode != "observe":
            # The swarm cannot revise a pull request, and a PR left open blocks the queue (one open swarm PR at a time): close it, count the
            # attempt, and let the task be retried (marked [needs-owner] after max_attempts). Live 2026-11-20: a fix verdict on PR 96 stalled the loop.
            outcome = "close"
        key = hashlib.sha1((repo + (task["text"] if task else str(n))).encode()).hexdigest()[:12]
        entry = {"pr": n, "head": pr["head"]["sha"][:12], "gates": [c for c, _ in fails], "verdict": verdict["verdict"], "outcome": outcome, "remembered": False}
        why = "; ".join(m for _, m in fails) or "; ".join(verdict.get("concerns", []) or verdict.get("reasons", [])) or "ok"
        task_text = task["text"] if task else ""
        if plan or mode == "observe":
            note = "**Maintainer (%s mode):** would %s this PR. Gates: %s." % (mode, outcome, why)
            if not plan and comment_once(repo, n, pr["head"]["sha"], note, plan, kind="observe-" + outcome):
                entry["remembered"] = remember_outcome(repo, n, task_text, "nothing done (observe mode): would " + outcome, why)
        elif outcome == "merge":
            if report["merged"] >= int(settings["max_merges_per_run"]) or today_merges + report["merged"] >= int(settings["max_merges_per_day"]):
                entry["outcome"] = "held"; entry["note"] = "merge limit reached"
            else:
                sha = merge_pr(repo, n, pr["head"]["sha"])
                report["merged"] += 1
                entry["remembered"] = remember_outcome(repo, n, task_text, "merged", "merge commit %s; gates passed and the reviewer said merge." % sha[:12])
                audit({"event": "merge", "repo": repo, "pr": n, "sha": sha, "haiku_calls": counters["haiku"], "remembered": entry["remembered"]})
        elif outcome == "close":
            comment_once(repo, n, pr["head"]["sha"], "**Maintainer:** closing this PR. " + why, plan, kind="close")
            close_pr(repo, n, pr["head"]["ref"])
            report["closed"] += 1
            entry["remembered"] = remember_outcome(repo, n, task_text, "closed", why)
            audit({"event": "close", "repo": repo, "pr": n, "gates": entry["gates"], "remembered": entry["remembered"]})
            if task and bump_attempt(key) >= int(settings["max_attempts"]):
                edit_tasklist_pr(settings, task["text"], lambda l: l.replace("[swarm-deploy]", "[needs-owner]", 1).replace("[swarm]", "[needs-owner]", 1),
                                 "maintainer/needs-owner-" + key, "maintainer: mark a failing task [needs-owner]")
        else:
            if comment_once(repo, n, pr["head"]["sha"], "**Maintainer:** needs changes. " + why, plan, kind="fix"):
                entry["remembered"] = remember_outcome(repo, n, task_text, "needs changes", why)
            if task:
                bump_attempt(key)
        entry["why"] = why[:300]
        report["prs"].append(entry)
    still_open = any(q["head"]["ref"].startswith(settings["branch_prefix"]) for q in api("GET", "/repos/%s/pulls?state=open&per_page=100" % repo))
    maint_open = any(q["head"]["ref"].startswith("maintainer/") for q in api("GET", "/repos/%s/pulls?state=open&per_page=100" % repo))
    if settings.get("auto_queue") and mode != "observe" and not plan and not still_open and not maint_open:
        report["queued"] = auto_queue(settings)  # a PR the owner merges; the maintainer never merges task-list edits it opens
    if mode == "merge-and-run" and not plan and not still_open:
        report["work"] = start_repo_work(settings)
    return report


def preflight():
    rc = 0
    for t in ("git", "make"):
        print("%-8s %s" % ("ok" if shutil.which(t) else "MISSING", t)); rc |= 0 if shutil.which(t) else 1
    os.makedirs(STATE, exist_ok=True)
    try:
        open(os.path.join(STATE, ".w"), "w").close(); os.remove(os.path.join(STATE, ".w")); print("ok       state dir writable (%s)" % STATE)
    except OSError:
        print("MISSING  writable %s" % STATE); rc = 1
    repos = load_repos()
    for r in repos:
        try:
            check_repo(r); print("ok       %s allowed (mode %s)" % (r, repos[r]["mode"]))
        except Refused as e:
            print("REFUSED  %s" % e); rc = 1
    if not repos:
        print("MISSING  no repositories configured (MAINT_REPOS or repos.yaml)"); rc = 1
    print("ok       token present" if os.environ.get("GITHUB_TOKEN") else "MISSING  GITHUB_TOKEN"); rc |= 0 if os.environ.get("GITHUB_TOKEN") else 1
    return rc


def main(argv):
    if argv[:1] == ["--preflight"]:
        return preflight()
    if argv[:1] == ["revert"] and len(argv) == 3:
        try:
            print(revert(argv[1], int(argv[2]))); return 0
        except (Refused, ValueError, subprocess.SubprocessError, urllib.error.URLError) as e:
            print("revert failed: %s" % e, file=sys.stderr); return 2
    plan = "--plan" in argv
    only = argv[argv.index("--repo") + 1] if "--repo" in argv else None
    repos = load_repos()
    if only and only not in repos:
        print("usage: maintain.py [--plan] [--repo <owner/name from the config>]", file=sys.stderr); return 2
    os.makedirs(os.path.join(STATE, "locks"), exist_ok=True)
    if os.path.exists(os.path.join(STATE, "disabled")) or os.path.exists(os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "ESTOP")):
        print("skipped: disabled or hermes paused"); audit({"event": "run", "status": "skipped", "reason": "disabled"}); return 0
    rc, results, counters = 0, [], {"haiku": 0}
    for repo, settings in repos.items():
        if only and repo != only:
            continue
        if "--manual" in argv and "--confirm" not in argv and settings["mode"] != "observe" and not plan:
            print("refused: %s runs in %s mode; a manual run needs CONFIRM=1" % (repo, settings["mode"]), file=sys.stderr); rc = max(rc, 2); continue
        try:
            check_repo(repo)
        except Refused as e:
            print("refused: %s" % e, file=sys.stderr); rc = max(rc, 2); continue
        lock = open(os.path.join(STATE, "locks", re.sub(r"[^a-z0-9]+", "-", repo.lower()) + ".lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("skipped: locked"); continue
        try:
            rep = maintain_repo(settings, plan, counters)
            results.append(rep)
            audit({"event": "run", "status": "ok", "plan": plan, "repo": repo, "mode": rep["mode"], "merged": rep["merged"], "closed": rep["closed"], "prs": rep["prs"], "haiku_calls": counters["haiku"], "work": rep.get("work", "")})
            digest("%s %s%s: %d merged, %d closed, %d PRs seen%s" % (repo, rep["mode"], " plan" if plan else "", rep["merged"], rep["closed"], len(rep["prs"]), (", work: " + rep["work"]) if rep.get("work") else ""))
        except (Refused, urllib.error.URLError, OSError, KeyError, ValueError) as e:
            audit({"event": "run", "status": "failed", "plan": plan, "repo": repo, "reason": lib.redact("%s: %s" % (type(e).__name__, e))[:200]})
            digest("%s failed: %s: %s" % (repo, type(e).__name__, e)); rc = max(rc, 1)
            if not plan:
                remember_outcome(repo, None, "", "failed", lib.redact("%s: %s" % (type(e).__name__, e))[:200])
    write_metrics()
    if plan:
        print(json.dumps(results, indent=1))
    else:
        for r in results:
            print("%s: merged %d, closed %d" % (r["repo"], r["merged"], r["closed"]))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
