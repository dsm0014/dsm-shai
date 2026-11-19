"""Swarm scheduler (spec 13): Haiku plans and judges, local qwen does bounded steps, scripts own routing, caps and verification.
Usage: swarm.py <task.yaml> [--dry-run] [--run-id ID]   |   swarm.py --preflight
Exit codes: 0 ok / skipped / dry-run, 1 failed, 2 usage or refused, 3 capped."""
import concurrent.futures as cf, fcntl, json, os, re, shutil, sys, threading, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lib, route, verifiers, workers

MAX_PLAN_STEPS = 12
CHAT_PARALLEL = 2
CTX_CHARS = 40000  # about 10K tokens of context per step, under the 16K budget


class Capped(Exception):
    pass


class Failed(Exception):
    pass


def envint(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def paused():
    return os.path.exists(os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "ESTOP"))


def prompt_text(name, **kw):
    t = open(os.path.join(HERE, "prompts", name + ".v1.txt")).read()
    for k, v in kw.items():
        t = t.replace("{{%s}}" % k, str(v))
    return t


def refuse(msg):
    print("refused: " + msg, file=sys.stderr)
    sys.exit(2)


def check_repo(task):
    repo = task.get("repo", "")
    allowed = [r.strip() for r in os.environ.get("SWARM_ALLOWED_REPOS", "").split(",") if r.strip()]
    if repo and repo not in allowed:
        refuse("repo %r is not in SWARM_ALLOWED_REPOS (unset means none)" % repo)


def fetch_items(task):
    """Inputs for the plan. Only source type github_changes (public repo, unauthenticated, through the egress proxy)."""
    src = task.get("source") or {}
    if not src:
        return []
    if src.get("type") != "github_changes":
        raise Failed("unknown source type")
    api = os.environ.get("SWARM_GITHUB_API", "https://api.github.com")
    repo = task["repo"]

    def get(path):
        req = urllib.request.Request(api + path, headers={"Accept": "application/vnd.github+json", "User-Agent": "dsm-shai-swarm"})
        return json.load(urllib.request.urlopen(req, timeout=30))
    try:
        commits = get("/repos/%s/commits?per_page=%d" % (repo, int(src.get("commits", 5))))
        items, seen = [], set()
        for c in commits:
            for f in get("/repos/%s/commits/%s" % (repo, c["sha"])).get("files", []):
                if f["filename"] in seen or len(items) >= int(src.get("max_items", 6)):
                    continue
                seen.add(f["filename"])
                items.append({"id": f["filename"], "text": (f.get("patch") or "(no textual patch)")[:3000]})
    except (OSError, ValueError, KeyError) as e:
        raise Failed("source fetch failed: %s" % type(e).__name__)
    return items


def validate_plan(plan, items, max_steps):
    """Return a list of problems (empty means valid). Capped is raised by the caller for a plan over max_steps."""
    bad = []
    steps = plan.get("steps") if isinstance(plan, dict) else None
    if not isinstance(steps, list) or not steps:
        return ["steps missing"]
    if len(steps) > MAX_PLAN_STEPS:
        return ["more than %d steps" % MAX_PLAN_STEPS]
    if not all(isinstance(s, dict) for s in steps):
        return ["step is not an object"]
    ids = [s.get("id") for s in steps]
    if len(set(ids)) != len(steps) or not all(isinstance(i, str) and i for i in ids):
        return ["step ids missing or duplicated"]
    known = {i["id"] for i in items}
    for s in steps:
        if s.get("tag") not in route.TAGS:
            bad.append("%s: tag must be normal or hard" % s["id"])
        if not isinstance(s.get("instruction"), str) or not s["instruction"].strip():
            bad.append("%s: instruction missing" % s["id"])
        deps, inputs = s.get("deps", []), s.get("inputs", [])
        if not isinstance(deps, list) or any(d not in ids or d == s["id"] for d in deps):
            bad.append("%s: bad deps" % s["id"])
        if not isinstance(inputs, list) or any(i not in known for i in inputs):
            bad.append("%s: unknown input" % s["id"])
    if not bad:  # acyclic: peel steps whose deps are all peeled
        left = {s["id"]: set(s.get("deps") or []) for s in steps}
        while left:
            ready = [k for k, d in left.items() if not d]
            if not ready:
                return ["dependency cycle"]
            for k in ready:
                del left[k]
            for d in left.values():
                d.difference_update(ready)
    return bad


def static_plan(task, items):
    """The dry-run plan: built by script, no model call, so a dry run makes no worker call and spends nothing.
    One normal step per input and one hard step that merges them; the live plan comes from the orchestrator."""
    steps = [{"id": "s%d" % n, "title": "summarise " + i["id"], "tag": "normal", "deps": [], "inputs": [i["id"]],
              "instruction": "Summarise what changed in this input in 2 to 3 sentences."} for n, i in enumerate(items[:MAX_PLAN_STEPS - 1], 1)]
    steps.append({"id": "merge", "title": "merge", "tag": "hard", "deps": [s["id"] for s in steps], "inputs": [],
                  "instruction": "Merge the summaries into one short report: " + task["goal"]})
    return {"steps": steps}


def json_in(text):
    try:
        return json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        return None


class Run:
    def __init__(self, task, args):
        self.task, self.dry = task, "--dry-run" in args
        self.id = args[args.index("--run-id") + 1] if "--run-id" in args else time.strftime("%Y%m%dT%H%M%S")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.id) or ".." in self.id:
            refuse("bad run id")
        self.orch = os.environ.get("SWARM_ORCHESTRATOR") or "haiku"  # empty (an unset make variable) means the default
        if self.orch not in ("haiku", "chat"):
            refuse("SWARM_ORCHESTRATOR must be haiku or chat")
        self.haiku_par = envint("SWARM_HAIKU_PARALLEL", 2)
        self.max_steps = int(task.get("max_steps", 12))
        self.max_haiku = int(task.get("max_haiku_calls", 10))
        self.deadline = time.time() + float(task.get("timeout_minutes", 30)) * 60
        self.dir = os.path.join(lib.STATE, "runs", self.id)
        self.sem = {"chat": threading.BoundedSemaphore(CHAT_PARALLEL), "haiku": threading.BoundedSemaphore(self.haiku_par)}
        self.lock = threading.Lock()
        self.calls = {"chat": 0, "haiku": 0}
        self.bytes = {"in": 0, "out": 0}
        self.chat_tokens = 0
        self.steps, self.outputs, self.stop = [], {}, False

    # ---- one worker call, under the caps ----------------------------------------------------------------------------
    def call(self, tier, prompt):
        with self.lock:
            if time.time() > self.deadline:
                raise Capped("timeout")
            if tier == "haiku":
                if self.calls["haiku"] >= self.max_haiku:
                    raise Capped("max_haiku_calls")
                self.calls["haiku"] += 1
            else:
                self.calls["chat"] += 1
            self.bytes["in"] += len(prompt)
        with self.sem[tier]:  # the scheduler is the only flow control; 429s are never used for it
            try:
                text, usage = (workers.call_haiku if tier == "haiku" else workers.call_chat)(prompt)
            except workers.HaikuUnavailable as e:
                if tier == "haiku":
                    with self.lock:
                        self.calls["haiku"] -= 1  # a refused call did not reach Anthropic
                raise Capped(str(e))
        with self.lock:
            self.bytes["out"] += len(text)
            self.chat_tokens += int(usage.get("total_tokens", 0) or 0)
        return text

    def build_plan(self, items):
        listing = workers.untrusted("input names", "\n".join("- %s (%d chars)" % (i["id"], len(i["text"])) for i in items) or "(no inputs)")
        tier = "chat" if self.orch == "chat" else "haiku"
        problems = []
        for attempt in (1, 2):
            p = prompt_text("plan", goal=self.task["goal"], items=listing, max_steps=min(self.max_steps, MAX_PLAN_STEPS),
                            problems=("Your previous plan was invalid: " + "; ".join(problems)) if problems else "")
            plan = json_in(self.call(tier, p))
            problems = ["not JSON"] if plan is None else validate_plan(plan, items, self.max_steps)
            if not problems:
                if len(plan["steps"]) > self.max_steps:
                    raise Capped("max_steps")
                return plan
        raise Failed("invalid plan: " + "; ".join(problems)[:200])

    # ---- one step: the retry ladder is same tier once, next tier once, then fail --------------------------------------
    def step_prompt(self, step, items):
        by_id = {i["id"]: i for i in items}
        parts = [prompt_text("worker", title=step.get("title", step["id"]), instruction=step["instruction"])]
        for i in (step.get("inputs") or []):
            parts.append(workers.untrusted("input " + i, by_id[i]["text"]))
        for d in (step.get("deps") or []):
            parts.append(workers.untrusted("result of step " + d, self.outputs[d][:12000]))
        return "\n\n".join(parts)[:CTX_CHARS]

    def run_step(self, step, items):
        stat = {"id": step["id"], "tag": step["tag"], "attempts": 0, "tiers": [], "verifier": "", "ok": False}
        local_failures, prev = 0, None
        names = list(self.task.get("verifiers") or []) + (["cites_inputs"] if step.get("inputs") else [])
        ctx = {"input_ids": (step.get("inputs") or []), "min_chars": self.task.get("min_chars", 40),
               "allowed_paths": self.task.get("allowed_paths", []), "max_chars": self.task.get("max_chars", 8000)}
        prompt = self.step_prompt(step, items)
        for attempt in (1, 2, 3):
            tier = route.route(step["tag"], local_failures, self.orch)
            if attempt == 3 and tier == prev:
                break  # no higher tier left
            prev = tier
            stat["attempts"] += 1
            stat["tiers"].append(tier)
            if self.stop:
                raise Failed("stopped")
            try:
                text = self.call(tier, prompt)
            except workers.WorkerError as e:
                stat["verifier"] = str(e)[:80]
                if tier == "chat":
                    local_failures += 1
                continue
            ok, why = verifiers.run(names, text, ctx)
            stat["verifier"] = why or "ok"
            if ok:
                os.makedirs(os.path.join(self.dir, "steps"), exist_ok=True)
                tmp = os.path.join(self.dir, "steps", step["id"] + ".out.tmp")
                open(tmp, "w").write(text)
                os.replace(tmp, os.path.join(self.dir, "steps", step["id"] + ".out"))  # only a verified result is kept
                self.outputs[step["id"]] = text
                stat["ok"] = True
                with self.lock:
                    self.steps.append(stat)
                return
            if tier == "chat":
                local_failures += 1
        with self.lock:
            self.steps.append(stat)
        raise Failed("step %s failed its verifier" % step["id"])

    def execute(self, plan, items):
        pending = {s["id"]: s for s in plan["steps"]}
        running, done = {}, set()
        with cf.ThreadPoolExecutor(max_workers=CHAT_PARALLEL + self.haiku_par) as ex:
            err = None
            while (pending or running) and err is None:
                if paused() or lib.disabled_reason(self.orch != "chat"):
                    err = Capped("kill switch")
                    break
                for sid in [k for k, s in pending.items() if all(d in done for d in (s.get("deps") or []))]:
                    running[ex.submit(self.run_step, pending.pop(sid), items)] = sid
                finished, _ = cf.wait(running, timeout=1, return_when=cf.FIRST_COMPLETED)
                for f in finished:
                    sid = running.pop(f)
                    try:
                        f.result()
                        done.add(sid)
                    except (Capped, Failed) as e:
                        err = err or e
            self.stop = True
            for f in running:
                f.cancel()
        if err:
            raise err
        sinks = [s["id"] for s in plan["steps"] if not any(s["id"] in (t.get("deps") or []) for t in plan["steps"])]
        return "\n\n".join(self.outputs[i] for i in sinks)

    def remember(self, task_name, report):
        """Store a short summary in OpenViking through its MCP endpoint. Best effort; the audit records whether it worked."""
        url, key = os.environ.get("SWARM_OPENVIKING_MCP", "http://openviking.openviking.svc:1933/mcp"), os.environ.get("OPENVIKING_KEY", "")
        if not key:
            return False
        def rpc(method, params, sid=None, rid=1):
            h = {"X-API-Key": key, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
            if sid:
                h["Mcp-Session-Id"] = sid
            msg = {"jsonrpc": "2.0", "method": method, "params": params}
            if rid is not None:
                msg["id"] = rid
            body = json.dumps(msg).encode()
            return urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h), timeout=30)
        try:
            r = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "swarm", "version": "1"}})
            sid = r.headers.get("Mcp-Session-Id")
            r.read()
            rpc("notifications/initialized", {}, sid, None).read()
            msgs = [{"role": "user", "content": "Swarm task %s run %s (%s): %s" % (task_name, self.id, lib.today(), self.task["goal"])},
                    {"role": "assistant", "content": report[:1500]}]  # the tool takes a short two-message exchange, not a bare string
            out = rpc("tools/call", {"name": "remember", "arguments": {"messages": msgs}}, sid, 2).read().decode().replace(" ", "")
            return '"isError":false' in out
        except (OSError, ValueError):
            return False


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 2
    task_path = argv[0]
    try:
        task = lib.load_task(task_path)
        for k in ("name", "goal"):
            assert task.get(k), k
    except (OSError, ValueError, AssertionError) as e:
        print("bad task file: %s" % e, file=sys.stderr); return 2
    if not task.get("repo"):
        refuse("task has no repo; every task names its target repo")
    check_repo(task)
    name = str(task["name"])
    run = Run(task, argv[1:])
    if run.haiku_par < 1:
        refuse("SWARM_HAIKU_PARALLEL must be at least 1")
    if run.orch == "haiku" and run.haiku_par > envint("CLAUDE_HAIKU_PARALLEL", 2):
        refuse("SWARM_HAIKU_PARALLEL=%d exceeds CLAUDE_HAIKU_PARALLEL; raise the wrapper variable first" % run.haiku_par)
    os.makedirs(os.path.join(lib.STATE, "locks"), exist_ok=True)
    lockf = open(os.path.join(lib.STATE, "locks", name + ".lock"), "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("skipped: locked"); lib.audit({"task": name, "status": "skipped", "reason": "locked"}); return 0
    why = "hermes paused" if paused() else lib.disabled_reason(run.orch != "chat")
    if why:
        print("skipped: " + why); lib.audit({"task": name, "status": "skipped", "reason": why}); lib.write_metrics(); return 0

    status, reason, report, t0 = "ok", "", "", time.time()
    plan = {"steps": []}
    try:
        items = fetch_items(task)
        plan = static_plan(task, items) if run.dry else run.build_plan(items)
        if run.dry:
            bad = validate_plan(plan, items, run.max_steps)
            if bad:
                raise Failed("invalid plan: " + "; ".join(bad))
            if len(plan["steps"]) > run.max_steps:  # a dry run applies the same cap a real run would
                raise Capped("max_steps")
        os.makedirs(run.dir, exist_ok=True)
        json.dump(plan, open(os.path.join(run.dir, "plan.json"), "w"), indent=1)
        if run.dry:
            print(json.dumps({"task": name, "orchestrator": run.orch, "plan": plan}, indent=1))
        else:
            report = run.execute(plan, items)
            open(os.path.join(run.dir, "report.md"), "w").write(report)
    except Capped as e:
        status, reason = "capped", str(e)
    except (Failed, workers.WorkerError) as e:
        status, reason = "failed", str(e)
    except Exception as e:  # never exit without an audit entry and a digest line
        status, reason = "failed", "internal error: %s" % type(e).__name__
    if status == "failed":  # discard uncommitted work: nothing outside the run dir is ever written, so the work dir goes
        shutil.rmtree(os.path.join(run.dir, "work"), ignore_errors=True)
        for f in os.listdir(os.path.join(run.dir, "steps")) if os.path.isdir(os.path.join(run.dir, "steps")) else []:
            if f.endswith(".tmp"):
                os.remove(os.path.join(run.dir, "steps", f))
    remembered = run.remember(name, report) if (status == "ok" and not run.dry and report) else False
    entry = lib.audit({"task": name, "run_id": run.id, "status": status, "reason": reason, "dry_run": run.dry,
                       "orchestrator": run.orch, "plan_steps": len(plan["steps"]), "steps": run.steps,
                       "chat_calls": run.calls["chat"], "haiku_calls": run.calls["haiku"], "bytes_in": run.bytes["in"],
                       "bytes_out": run.bytes["out"], "chat_tokens": run.chat_tokens, "remembered": remembered,
                       "seconds": int(time.time() - t0)})
    lib.digest("%s %s%s%s (chat %d, haiku %d)" % (name, status, " dry-run" if run.dry else "", ": " + reason if reason else "",
                                                  run.calls["chat"], run.calls["haiku"]))
    lib.write_metrics()
    print(lib.redact("%s: %s %s" % (name, status, reason)))
    return {"ok": 0, "capped": 3}.get(status, 1)


def preflight():
    import subprocess
    rc = 0
    for t in ("git", "curl", "flock", "timeout"):
        found = shutil.which(t)
        print("%-8s %s" % ("ok" if found else "MISSING", t)); rc |= 0 if found else 1
    os.makedirs(lib.STATE, exist_ok=True)
    try:
        open(os.path.join(lib.STATE, ".w"), "w").close(); os.remove(os.path.join(lib.STATE, ".w")); print("ok       state dir writable (%s)" % lib.STATE)
    except OSError:
        print("MISSING  writable %s" % lib.STATE); rc = 1
    p = subprocess.run(["bash", workers.HAIKU_BIN, "--preflight"], capture_output=True, text=True)
    print(p.stdout.strip() + ("" if p.returncode == 0 else "\nnote     haiku preflight failed (SWARM_ORCHESTRATOR=chat still works)"))
    used, cap = lib.haiku_calls_today(), envint("CLAUDE_HAIKU_DAILY_CALLS", 200)
    print(("ok       haiku calls today %d of %d" if used < cap else "FAIL     haiku daily cap spent %d of %d") % (used, cap))
    try:
        workers.call_chat("Reply with the single word OK.", timeout=60); print("ok       chat reachable through LiteLLM")
    except workers.WorkerError as e:
        print("MISSING  chat: %s" % e); rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(preflight() if "--preflight" in sys.argv[1:] else main(sys.argv[1:]))
