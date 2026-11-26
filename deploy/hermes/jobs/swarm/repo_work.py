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
    if not path.startswith("deploy/") or path.endswith(".md"):
        return False  # specs, docs, READMEs and the task list are never deploy config, even when their path says "istio"
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


def outcome_record(run, info, status, reason, pr_url):
    """The two messages OpenViking stores for a finished repo-work run (a one-line remember extracts nothing)."""
    info = info or {}
    user = "Swarm repo work run %s on task %r (files: %s), %s." % (run.id, info.get("text", "")[:160], ", ".join(info.get("files", [])) or "none", lib.today())
    if pr_url:
        out = "Outcome: opened pull request %s. Haiku calls %d, local calls %d." % (pr_url, run.calls["haiku"], run.calls["chat"])
    else:
        out = "Outcome: %s%s." % (status, ": " + reason if reason else "")
    return user, out

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


def json_wrapper(path, body):
    """True when a worker returned a JSON object (keys such as file, followups, notes) in place of the file. A JSON object is also
    a valid Python dict literal, so the python-syntax check cannot catch it in a .py file (PR 184). Not applied to .json targets."""
    if path.endswith(".json") or not body.lstrip().startswith("{"):
        return False
    try:
        d = json.loads(body)
    except ValueError:
        return False
    return isinstance(d, dict) and bool({"file", "followups", "notes"} & set(d))


def _tail(text, n=12):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def evidence(workdir, files, cmd, result):
    """What the engine ran in the clone before it pushed, with exit codes and output, for the PR body. The maintainer reviews
    the PR text, and a bare "passed" gave it nothing to check: it closed attempt after attempt for lacking a run. A new check
    script (scripts/check-*.py or .sh) is also run on its own, from the repository root. Redacted and bounded."""
    parts = []
    if cmd and result is not None:
        parts.append("$ %s\n[exit %d]\n%s" % (cmd, result.returncode, _tail(result.stdout + result.stderr)))
    for f in files:
        if not re.match(r"^scripts/check-[^/]+\.(py|sh)$", f) or not os.path.exists(os.path.join(workdir, f)):
            continue
        argv = ["python3", "-I", f] if f.endswith(".py") else ["bash", f]
        try:
            r = subprocess.run(argv, cwd=workdir, capture_output=True, text=True, timeout=120)
            parts.append("$ %s\n[exit %d]\n%s" % (" ".join(argv), r.returncode, _tail(r.stdout + r.stderr, 10)))
        except subprocess.TimeoutExpired:
            parts.append("$ %s\n[timed out after 120 s]" % " ".join(argv))
    return lib.redact("\n\n".join(parts))[:3000]


MAX_FOLLOWUPS = 2     # new [swarm] lines one run may add to the task list
MAX_QUEUED = 20       # the queue is never longer than this, so follow-ups cannot grow without bound
# Planner-only request for follow-up tasks, appended after the planner's rules. Workers must never see it.
FOLLOWUP_ASK = ("\nOptional: the JSON object may also have a top-level key \"followups\" (beside \"steps\", never inside a step): up to %d new "
                "task-list lines, each in exactly this form: - [ ] [swarm] **Short title:** what to change, with 1 to 3 existing files in backticks. "
                "Include a check that proves it. Only for follow-up work this change makes necessary. Use [] when there is none. "
                "Never mention followups in a step's instruction: instructions are for the worker, who only edits its own file." % MAX_FOLLOWUPS)
FOLLOWUP_LINE = re.compile(r"^- \[ \] \[swarm\] \*\*[^*\n]{3,80}:\*\* .{20,}$")


def followup_paths(line):
    return re.findall(r"`([^`]+)`", line)


def followup_problem(line):
    """Why a proposed follow-up task line may not be queued ('' when it may): the swarm's own format, 1 to 3 paths the swarm
    may edit. Existence of the paths is checked where the repository is at hand (the engine and the maintainer)."""
    line = line.strip()
    if not FOLLOWUP_LINE.match(line):
        return "not a [swarm] task line in the queue format"
    if "[swarm-deploy]" in line or "[needs-owner]" in line:
        return "marked deploy or owner-only"
    paths = followup_paths(line)
    if not 1 <= len(paths) <= 3:
        return "must name 1 to 3 files"
    for p in paths:
        if forbidden(p) or deploy_class(p):
            return "names a forbidden or deploy-class path: %s" % p
    return ""


def check_plan(plan, files):
    """One step edits exactly one allowed file, no file twice."""
    seen = []
    for s in plan["steps"]:
        ins = s.get("inputs") or []
        if len(ins) != 1 or ins[0] not in files or ins[0] in seen:
            return ["step %s must edit exactly one listed file, once" % s.get("id")]
        seen.append(ins[0])
    return []


def last_attempt_decision(repo, task_text):
    """(PR number, text) for the latest closed, unmerged swarm PR for this task: the maintainer's reason for closing it
    when it left one, else an empty text. (None, "") when the task has never been attempted. The title is the one the
    engine gives its PRs (the same expression below), so the match is exact."""
    title = "swarm: " + re.sub(r"\[[^\]]*\]\s*|`", "", task_text)[:70]
    pulls = api("GET", "/repos/%s/pulls?state=closed&per_page=100" % repo)
    for p in sorted(pulls, key=lambda p: p.get("number", 0), reverse=True):
        if p.get("title") != title or p.get("merged_at"):
            continue
        for c in reversed(api("GET", "/repos/%s/issues/%d/comments?per_page=100" % (repo, p["number"]))):
            body = c.get("body") or ""
            if "closing this PR" in body:
                return p["number"], body[:1500]
        return p["number"], ""
    return None, ""


def main(task, run, swarm, lockf, state_name):
    """Returns the exit code. `run` is a swarm.Run; `swarm` the swarm module (passed in to avoid a circular import)."""
    repo = task["repo"]
    status, reason, pr_url, info, t0 = "ok", "", "", None, time.time()
    workdir = os.path.join(os.environ.get("SWARM_WORK", "/workspace"), "swarm-repo-work-" + run.id)
    plan, results, history, remembered = {"steps": []}, [], "", False
    queued_followups = []  # follow-up [swarm] lines this run adds to the task list, checked before they are written
    try:
        if os.environ.get("SWARM_REPO_WORK") != "1":
            raise Refused("SWARM_REPO_WORK is not 1")
        # guards, in order: open swarm PR (one at a time), pick. There is no per-day limit (owner decision 2026-11-19).
        pulls = api("GET", "/repos/%s/pulls?state=open&per_page=100" % repo)
        if any((p.get("head") or {}).get("ref", "").startswith("swarm/") for p in pulls):
            raise Refused("skipped: pr open")
        md = api("GET", "/repos/%s/contents/%s" % (repo, TASKLIST), raw=True)
        # A task this job may never do must not block the queue: skip it (digest line) and take the next eligible one.
        refused, info = set(), None
        for _ in range(50):
            info, skipped = pick_task.pick(md, skip=refused)
            for n, why in skipped:
                lib.digest("repo-work: line %d skipped (%s)" % (n, why))
            if not info:
                raise Refused("skipped: no eligible task")
            bad = [f for f in info["files"] if forbidden(f)]
            problem = ("forbidden path in task: %s" % bad[0] if bad else
                       "deploy-class path needs [swarm-deploy]" if not info["deploy"] and any(deploy_class(f) for f in info["files"]) else
                       "task names more than SWARM_MAX_FILES files" if len(info["files"]) > envint("SWARM_MAX_FILES", 6) else "")
            if not problem:
                break
            lib.digest("repo-work: task at line %d skipped (%s)" % (info["line"], problem))
            refused.add(info["text"])
        else:
            raise Refused("skipped: no eligible task")
        if run.dry:
            plan = static_plan(info)
            print(json.dumps({"task": info, "allowed_paths": info["files"], "plan": plan}, indent=1))
            raise Refused("ok-dry")
        # decision log: if this task was attempted before, the maintainer's reason for closing that attempt goes to the worker
        attempt_no, decision = None, ""
        try:
            attempt_no, decision = last_attempt_decision(repo, info["text"])
        except Exception as exc:  # GitHub unreachable: the attempt still runs, without the history
            lib.digest("repo-work: attempt history unavailable (%s)" % exc)
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
        history = swarm.recall(" ".join(info["files"]))  # earlier outcomes for these files: memory, untrusted, bounded
        # The goal reaches the planner and, through its step instructions, the workers, so it carries the task and nothing else.
        # The follow-up request below goes to the planner alone (see FOLLOWUP_ASK): when it sat in the goal, workers copied it and
        # returned a JSON object with file, followups and notes keys in place of the file (PR 184).
        run.task["goal"] = "Complete this repository task by editing the listed files, one step per file: " + info["text"]
        run.task["verifiers"] = ["file_block", "keeps_size"]
        tier = "chat" if run.orch == "chat" else "haiku"
        problems = []
        for _ in (1, 2):
            p = swarm.prompt_text("plan", goal=run.task["goal"], items=workers.untrusted("input names", "\n".join("- %s" % i["id"] for i in items)),
                                  history=workers.untrusted("earlier outcomes for these files", history) if history else "(none recorded)",
                                  max_steps=len(items),
                                  problems=FOLLOWUP_ASK + (("\nYour previous plan was invalid: " + "; ".join(problems)) if problems else ""))
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
            s["allow_heading_change"] = bool(re.search(r"\brename\b", info["text"], re.I))  # a task that says "rename" may change a heading
            s["orig_text"] = "" if text_of[s["inputs"][0]] == "(new file)" else text_of[s["inputs"][0]]
            s["instruction"] = (s["instruction"] + "\nTask: " + info["text"] + "\nReply with the COMPLETE new content of the file in one fenced block (```file ... ```), nothing else. "
                                "Return the WHOLE file: every line that does not need to change must be copied unchanged. Do not return only the changed part.")
            if decision:  # a re-attempt: the maintainer's reason for closing the last one is the decision log the new file must answer
                s["instruction"] += ("\nThis task was attempted before in PR #%s and the maintainer closed that attempt. The new file must not repeat these defects:\n%s"
                                     % (attempt_no, workers.untrusted("maintainer's reason for closing the previous attempt", decision)))
        run.execute(plan, items)
        # apply
        for s in plan["steps"]:
            f = s["inputs"][0]
            body = extract_block(run.outputs[s["id"]])
            if body is None or not body.strip():
                raise swarm.Failed("step %s returned no file block" % s["id"])
            if json_wrapper(f, body):
                raise swarm.Failed("step %s returned a JSON object in place of the file" % s["id"])
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
                # follow-up tasks the plan asked for take the finished task's place: each one is checked, and skipped with a digest line if not
                queued = sum(1 for l in lines if l.startswith("- [ ] [swarm]"))
                for line in (plan.get("followups") or [])[:MAX_FOLLOWUPS]:
                    line = str(line).strip()
                    why = followup_problem(line)
                    if not why and not all(os.path.exists(os.path.join(workdir, p)) for p in followup_paths(line)):
                        why = "names a file that does not exist"
                    if not why and queued >= MAX_QUEUED:
                        why = "queue is full (%d)" % MAX_QUEUED
                    if why:
                        lib.digest("repo-work: follow-up not queued (%s): %s" % (why, line[:120]))
                        continue
                    queued_followups.append(line)
                    queued += 1
                del lines[info["line"] - 1]
                lines[info["line"] - 1:info["line"] - 1] = queued_followups
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
        t = None
        if cmd:
            t = subprocess.run(["bash", "-c", cmd], cwd=workdir, capture_output=True, text=True, timeout=envint("SWARM_TEST_TIMEOUT", 1200))
            if t.returncode != 0:
                raise swarm.Failed("tests failed (exit %d)" % t.returncode)
        proof = evidence(workdir, info["files"], cmd, t)  # run before the commit, in the same clone the branch is pushed from
        git("add", "-A", cwd=workdir)
        git("commit", "-q", "-m", "swarm: " + re.sub(r"\[[^\]]*\]\s*", "", info["text"])[:70], "-m", "Run %s. Opened by the Hermes swarm; review before merging." % run.id, cwd=workdir)
        git("push", "-q", "origin", branch, cwd=workdir)
        body = ("Task: %s\n\nFiles: %s\nRun: %s. Haiku calls: %d, local calls: %d. Verifiers: file block, allowed paths, caps, `%s` passed.\n"
                "Opened by the swarm. It never merges; review and merge it yourself." % (info["text"], ", ".join("`%s`" % f for f in info["files"]), run.id,
                                                                                      run.calls["haiku"], run.calls["chat"], cmd or "no tests"))
        if proof:
            body += "\n\nEvidence, run by the engine in a clone of this branch before the PR was opened (commands, exit codes, output):\n```\n" + proof + "\n```"
        if queued_followups:
            body += "\n\nFollow-up tasks this change queues (task-list lines added, each checked for format and paths):\n" + "\n".join("- %s" % l for l in queued_followups)
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
    if not run.dry and status != "skipped":  # skipped runs (open pull request, no task) are not worth a memory
        remembered = swarm.remember_exchange(*outcome_record(run, info, status, reason, pr_url))
    entry = lib.audit({"task": state_name, "kind": "repo_work", "run_id": run.id, "status": status, "reason": reason, "dry_run": run.dry,
                       "orchestrator": run.orch, "picked": (info or {}).get("text", "")[:120], "files": (info or {}).get("files", []), "pr_url": pr_url,
                       "remembered": remembered, "recalled": len(history),
                       "steps": run.steps, "chat_calls": run.calls["chat"], "haiku_calls": run.calls["haiku"], "bytes_in": run.bytes["in"],
                       "bytes_out": run.bytes["out"], "chat_tokens": run.chat_tokens, "seconds": int(time.time() - t0)})
    lib.digest("repo-work %s%s%s%s" % (status, " dry-run" if run.dry else "", ": " + reason if reason else "", " " + pr_url if pr_url else ""))
    lib.write_metrics()
    print(lib.redact("repo-work: %s %s %s" % (status, reason, pr_url)))
    return {"ok": 0, "skipped": 0, "capped": 3}.get(status, 1 if status == "failed" else 2)
