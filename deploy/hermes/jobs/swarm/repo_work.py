"""Autonomous repo work (spec 14). The swarm picks one `[swarm]` task from the target repo's task list, workers return the new
content of each file, scripts apply it on a branch, run the repo's tests and open a pull request. Nothing here merges: there is
no merge call anywhere in this file. Reuses swarm.py's Run (routing, caps, retries, verifiers) as `swarm.Run`."""
import json, os, re, shutil, subprocess, sys, time, urllib.error, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lib, pick_task, workers

FORBIDDEN_PREFIXES = (".github/", "ci/", "deploy/secrets/", "deploy/hermes/jobs/swarm", "deploy/hermes/jobs/claude-haiku", ".git/")
FORBIDDEN_NAMES = ("CLAUDE.md", ".sops.yaml")
TASKLIST = ".specter/tasklist.md"
FENCE = re.compile(r"```(?:file|[A-Za-z0-9_+.-]*)\n(.*?)\n```", re.S)


def envint(n, d):
    try:
        return int(os.environ.get(n, d))
    except ValueError:
        return d


def forbidden(path):
    return path.startswith(FORBIDDEN_PREFIXES) or path.endswith(".sops.yaml") or os.path.basename(path) in FORBIDDEN_NAMES or ".." in path.split("/")


def deploy_class(path):
    """Manifests, mesh or egress config: allowed only for tasks marked [swarm-deploy]."""
    if not path.startswith("deploy/"):
        return False  # specs, docs and the task list are never deploy config, even when their name says "istio"
    return path.endswith((".yaml", ".yml")) or "istio" in path or "egress" in path or "networkpolicy" in path.lower()


class Refused(Exception):
    pass


class GitError(Exception):
    """A git command failed (clone, push, commit): the run failed, it was not refused by a guard."""


def api(method, path, body=None, raw=False):
    base = os.environ.get("SWARM_GITHUB_API", "https://api.github.com")
    h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json", "User-Agent": "dsm-shai-swarm"}
    tok = os.environ.get("GITHUB_TOKEN", "")
    if tok:
        h["Authorization"] = "Bearer " + tok
    data = json.dumps(body).encode() if body is not None else None
    if data:
        h["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(base + path, data=data, method=method, headers=h), timeout=60) as r:
        text = r.read().decode()
    return text if raw else (json.loads(text) if text else {})


def git(*a, cwd, check=True):
    p = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, timeout=600)
    if check and p.returncode != 0:
        raise GitError("git %s failed: %s" % (a[0], lib.redact(p.stderr.strip()[:200])))
    return p.stdout


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"`[^`]*`|\[[^\]]*\]", " ", text.lower())).strip("-")[:40] or "task"


def static_plan(task_info):
    steps = [{"id": "f%d" % n, "title": "edit " + f, "tag": "hard" if task_info["deploy"] else "normal", "deps": [], "inputs": [f],
              "instruction": "Make the change the task asks for in this one file."} for n, f in enumerate(task_info["files"][:12], 1)]
    return {"steps": steps}


def extract_block(text):
    """The file is everything between the opening fence line and the LAST closing fence, so a file that contains its own
    code fences (markdown) is kept whole."""
    m = re.search(r"^```[^\n]*\n", text, re.M)  # the first fence line, whatever its info string ("file", "file path/x.md", "markdown")
    if not m:
        return None
    end = text.rfind("\n```")
    if end < m.end() - 1:
        return None
    body = text[m.end():end]
    # the model sometimes echoes the delimiter lines it was given; they are never part of a file
    body = "\n".join(l for l in body.split("\n") if l.strip() not in (workers.MARK_OPEN, workers.MARK_CLOSE) and not l.startswith(workers.MARK_OPEN + " "))
    return body + "\n"


def check_plan(plan, files):
    """One step edits exactly one allowed file, no file twice."""
    seen = []
    for s in plan["steps"]:
        ins = s.get("inputs") or []
        if len(ins) != 1 or ins[0] not in files or ins[0] in seen:
            return ["step %s must edit exactly one listed file, once" % s.get("id")]
        seen.append(ins[0])
    return []


def main(task, run, swarm, lockf, state_name):
    """Returns the exit code. `run` is a swarm.Run; `swarm` the swarm module (passed in to avoid a circular import)."""
    repo = task["repo"]
    status, reason, pr_url, info, t0 = "ok", "", "", None, time.time()
    workdir = os.path.join(os.environ.get("SWARM_WORK", "/workspace"), "swarm-repo-work-" + run.id)
    plan, results = {"steps": []}, []
    try:
        if os.environ.get("SWARM_REPO_WORK") != "1":
            raise Refused("SWARM_REPO_WORK is not 1")
        # guards, in order: open swarm PR (one at a time), pick. There is no per-day limit (owner decision 2026-11-19).
        pulls = api("GET", "/repos/%s/pulls?state=open&per_page=100" % repo)
        if any((p.get("head") or {}).get("ref", "").startswith("swarm/") for p in pulls):
            raise Refused("skipped: pr open")
        md = api("GET", "/repos/%s/contents/%s" % (repo, TASKLIST), raw=True)
        info, skipped = pick_task.pick(md)
        for n, why in skipped:
            lib.digest("repo-work: line %d skipped (%s)" % (n, why))
        if not info:
            raise Refused("skipped: no eligible task")
        bad = [f for f in info["files"] if forbidden(f)]
        if bad:
            raise Refused("forbidden path in task: %s" % bad[0])
        if not info["deploy"] and any(deploy_class(f) for f in info["files"]):
            raise Refused("deploy-class path needs [swarm-deploy]")
        if len(info["files"]) > envint("SWARM_MAX_FILES", 6):
            raise Refused("task names more than SWARM_MAX_FILES files")
        if run.dry:
            plan = static_plan(info)
            print(json.dumps({"task": info, "allowed_paths": info["files"], "plan": plan}, indent=1))
            raise Refused("ok-dry")
        # clone and branch
        default = api("GET", "/repos/%s" % repo).get("default_branch", "main")
        url = os.environ.get("SWARM_CLONE_URL") or "https://github.com/%s.git" % repo
        os.makedirs(os.path.dirname(workdir), exist_ok=True)
        git("clone", "--quiet", "--depth", "50", "--branch", default, url, workdir, cwd=os.path.dirname(workdir))
        branch = "swarm/%s-%s" % (lib.today(), slug(info["text"]))
        git("checkout", "-q", "-b", branch, cwd=workdir)
        items = []
        for f in info["files"]:
            p = os.path.join(workdir, f)
            text = open(p, errors="replace").read() if os.path.exists(p) else "(new file)"
            if len(text) > envint("SWARM_MAX_FILE_CHARS", 24000):  # a worker that cannot see the whole file would rewrite it from a part
                raise Refused("refused: %s is larger than the worker can see whole (SWARM_MAX_FILE_CHARS)" % f)
            items.append({"id": f, "text": text})
        # plan with the orchestrator, then run the steps under the swarm's caps
        run.task["goal"] = "Complete this repository task by editing the listed files, one step per file: " + info["text"]
        run.task["verifiers"] = ["file_block", "keeps_size"]
        tier = "chat" if run.orch == "chat" else "haiku"
        problems = []
        for _ in (1, 2):
            p = swarm.prompt_text("plan", goal=run.task["goal"], items=workers.untrusted("input names", "\n".join("- %s" % i["id"] for i in items)),
                                  max_steps=len(items), problems=("Your previous plan was invalid: " + "; ".join(problems)) if problems else "")
            plan = swarm.json_in(run.call(tier, p, json_mode=True)) or {}
            problems = swarm.validate_plan(plan, items, len(items)) or (check_plan(plan, info["files"]) if plan.get("steps") else ["no steps"])
            if not problems:
                break
        if problems:
            raise swarm.Failed("invalid plan: " + "; ".join(problems)[:160])
        text_of = {i["id"]: i["text"] for i in items}
        for s in plan["steps"]:
            s["orig_len"] = 0 if text_of[s["inputs"][0]] == "(new file)" else len(text_of[s["inputs"][0]])
            s["min_keep_pct"] = envint("SWARM_MIN_KEEP_PCT", 70)
            s["instruction"] = (s["instruction"] + "\nTask: " + info["text"] + "\nReply with the COMPLETE new content of the file in one fenced block (```file ... ```), nothing else. "
                                "Return the WHOLE file: every line that does not need to change must be copied unchanged. Do not return only the changed part.")
        run.execute(plan, items)
        # apply
        for s in plan["steps"]:
            f = s["inputs"][0]
            body = extract_block(run.outputs[s["id"]])
            if body is None or not body.strip():
                raise swarm.Failed("step %s returned no file block" % s["id"])
            orig = next(i["text"] for i in items if i["id"] == f)
            keep = envint("SWARM_MIN_KEEP_PCT", 70)
            if orig != "(new file)" and len(body) * 100 < len(orig) * keep:  # a 9B worker can return a cut-down file that passes every other check
                raise swarm.Failed("output shrank %s to %d%% of its size (minimum %d%%)" % (f, len(body) * 100 // max(1, len(orig)), keep))
            os.makedirs(os.path.dirname(os.path.join(workdir, f)) or workdir, exist_ok=True)
            open(os.path.join(workdir, f), "w").write(body)
        # tick the task off: remove its line, as the task-list convention says
        tl = os.path.join(workdir, TASKLIST)
        if os.path.exists(tl):
            lines = open(tl).read().split("\n")
            if info["line"] - 1 < len(lines) and lines[info["line"] - 1].lstrip().startswith("- [ ]"):
                del lines[info["line"] - 1]
                open(tl, "w").write("\n".join(lines))
        # script-only verification
        changed = [l.split("\t")[-1] for l in git("diff", "--numstat", cwd=workdir).splitlines()] + git("ls-files", "--others", "--exclude-standard", cwd=workdir).split()
        allowed = set(info["files"]) | {TASKLIST}
        for f in changed:
            if f not in allowed or forbidden(f) and f != TASKLIST:
                raise swarm.Failed("change outside allowed paths: %s" % f)
        for l in git("diff", "--numstat", cwd=workdir).splitlines():  # a rewrite that throws most of a file away is a bad edit
            a, d, f = l.split("\t")[:3]
            if f != TASKLIST and d.isdigit() and int(d) > max(10, len(git("show", "HEAD:" + f, cwd=workdir).splitlines()) * envint("SWARM_MAX_DELETE_PCT", 50) // 100):
                raise swarm.Failed("change deletes too much of %s (%s lines)" % (f, d))
        lines_changed = sum(int(a) + int(d) for a, d, *_ in (l.split("\t") for l in git("diff", "--numstat", cwd=workdir).splitlines()) if a.isdigit() and d.isdigit())
        if len(changed) > envint("SWARM_MAX_FILES", 6) + 1 or lines_changed > envint("SWARM_MAX_LINES", 300):
            raise swarm.Failed("change over the file or line cap (%d files, %d lines)" % (len(changed), lines_changed))
        cmd = os.environ.get("SWARM_TEST_CMD") or ("make test" if re.search(r"^test:", open(os.path.join(workdir, "Makefile")).read(), re.M) else "")
        if os.path.exists(os.path.join(workdir, "scripts/check-sops.sh")):
            cmd = (cmd + " && " if cmd else "") + "bash scripts/check-sops.sh"
        if cmd:
            t = subprocess.run(["bash", "-c", cmd], cwd=workdir, capture_output=True, text=True, timeout=envint("SWARM_TEST_TIMEOUT", 1200))
            if t.returncode != 0:
                raise swarm.Failed("tests failed (exit %d)" % t.returncode)
        git("add", "-A", cwd=workdir)
        git("commit", "-q", "-m", "swarm: " + re.sub(r"\[[^\]]*\]\s*", "", info["text"])[:70], "-m", "Run %s. Opened by the Hermes swarm; review before merging." % run.id, cwd=workdir)
        git("push", "-q", "origin", branch, cwd=workdir)
        body = ("Task: %s\n\nFiles: %s\nRun: %s. Haiku calls: %d, local calls: %d. Verifiers: file block, allowed paths, caps, `%s` passed.\n"
                "Opened by the swarm. It never merges; review and merge it yourself." % (info["text"], ", ".join("`%s`" % f for f in info["files"]), run.id,
                                                                                      run.calls["haiku"], run.calls["chat"], cmd or "no tests"))
        pr = api("POST", "/repos/%s/pulls" % repo, {"title": "swarm: " + re.sub(r"\[[^\]]*\]\s*|`", "", info["text"])[:70], "head": branch, "base": default, "body": body})
        pr_url = pr.get("html_url", "")
        try:
            api("POST", "/repos/%s/issues/%d/labels" % (repo, pr["number"]), {"labels": ["swarm"] + (["needs-careful-review"] if info["deploy"] else [])})
        except (urllib.error.URLError, OSError):
            pass  # the label is a convenience
        results = [{"id": s["id"], "file": s["inputs"][0]} for s in plan["steps"]]
    except Refused as e:
        msg = str(e)
        status = "ok" if msg == "ok-dry" else ("skipped" if msg.startswith("skipped") else "refused")
        reason = "" if msg == "ok-dry" else msg
    except (swarm.Failed, GitError, workers.WorkerError, subprocess.TimeoutExpired, urllib.error.URLError, OSError, KeyError, ValueError) as e:
        status, reason = "failed", lib.redact("%s: %s" % (type(e).__name__, e))[:200]
    except swarm.Capped as e:
        status, reason = "capped", str(e)
    shutil.rmtree(workdir, ignore_errors=True)  # a failed or finished run leaves nothing behind; the branch only exists remotely after a push
    entry = lib.audit({"task": state_name, "kind": "repo_work", "run_id": run.id, "status": status, "reason": reason, "dry_run": run.dry,
                       "orchestrator": run.orch, "picked": (info or {}).get("text", "")[:120], "files": (info or {}).get("files", []), "pr_url": pr_url,
                       "steps": run.steps, "chat_calls": run.calls["chat"], "haiku_calls": run.calls["haiku"], "bytes_in": run.bytes["in"],
                       "bytes_out": run.bytes["out"], "chat_tokens": run.chat_tokens, "seconds": int(time.time() - t0)})
    lib.digest("repo-work %s%s%s%s" % (status, " dry-run" if run.dry else "", ": " + reason if reason else "", " " + pr_url if pr_url else ""))
    lib.write_metrics()
    print(lib.redact("repo-work: %s %s %s" % (status, reason, pr_url)))
    return {"ok": 0, "skipped": 0, "capped": 3}.get(status, 1 if status == "failed" else 2)
