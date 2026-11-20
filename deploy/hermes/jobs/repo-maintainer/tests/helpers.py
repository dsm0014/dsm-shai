"""Test helpers for the repo maintainer (spec 16). Offline, standard library only.

- MaintStub: stub GitHub REST API for maintain.py (and the spec 14 repo-work child it may start). Records every request as
  (method, path-with-query, body) and answers 404 to anything it does not serve.
- Remote / git helpers: a real bare git remote built from a seed repo, so clone, branch, push, diff and merge are real.
- MaintWorld: one throwaway world per test (state dirs, remote, stub, fake gateway, fake Haiku wrapper) plus run() that
  starts maintain.py as `python3 -I` with an explicit environment.
- load_maintain(): imports maintain.py in-process (for the gate unit tests).
- The swarm test helpers (FakeGateway, write_fake_haiku) are loaded by path under a private module name, so this package's
  `helpers` name is not shadowed. Nothing in the swarm tests directory is edited.

No literal tokens are stored: fake credentials are assembled at runtime."""
import atexit, http.server, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.parse, warnings

# lib.load_task (swarm, not ours to change) leaves a file open; keep the test output readable.
warnings.filterwarnings("ignore", category=ResourceWarning)

TESTS = os.path.dirname(os.path.abspath(__file__))
JOBDIR = os.path.dirname(TESTS)                     # deploy/hermes/jobs/repo-maintainer
JOBS = os.path.dirname(JOBDIR)                      # deploy/hermes/jobs
SWARM_DIR = os.path.join(JOBS, "swarm")
SWARM_TESTS = os.path.join(SWARM_DIR, "tests")
MAINT_PY = os.path.join(JOBDIR, "maintain.py")

REPO = "acme/widgets"
OTHER_REPO = "acme/gadgets"
LOGIN = "swarm-bot"
TODAY = "2026-11-19"
FAKE_TOKEN = "gh" + "p_" + "a" * 36
FAKE_LITELLM_KEY = "fake-" + "hermes-key-for-maint-tests"

TASK_A = "- [ ] [swarm] Fix the intro in `docs/a.md`"
TASK_B = "- [ ] [swarm] Fix the outro in `docs/b.md`"
TASKLIST_PATH = ".specter/tasklist.md"
TASKLIST = ("# Tasks\n\n## Open work\n\n- [x] Old finished item\n%s\n%s\n- [ ] Unmarked item for later\n" % (TASK_A, TASK_B))
SEED = {"Makefile": "test:\n\t@true\n", "docs/a.md": "# Widgets\n\nOld intro line.\nThird line.\n",
        "docs/b.md": "# Outro\n\nOld outro line.\n", TASKLIST_PATH: TASKLIST}
GOOD_EDITS = {TASK_A: {"docs/a.md": "# Widgets\n\nNew intro line.\nAnother intro line.\nThird line.\n"},
              TASK_B: {"docs/b.md": "# Outro\n\nNew outro line.\n"}}
CHILD_DOC = "# Widgets\n\nNew intro line.\nAnother intro line.\nThird line.\n"

VERDICT_MERGE = json.dumps({"verdict": "merge", "reasons": ["ok"], "concerns": []})
VERDICT_FIX = json.dumps({"verdict": "fix", "reasons": [], "concerns": ["tighten the intro"]})
VERDICT_CLOSE = json.dumps({"verdict": "close", "reasons": [], "concerns": ["unrelated change"]})

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# The swarm helpers come in by path under a private name (their module is also called `helpers`).
swarm_helpers = _load("swarm_test_helpers", os.path.join(SWARM_TESTS, "helpers.py"))

# ---- in-process import of maintain.py (gate unit tests). Its state constants are read at import time, so point them at a
# throwaway directory for the duration of the import and restore the environment afterwards.
_IMPORT_ROOT = tempfile.mkdtemp(prefix="maint-import-")
atexit.register(shutil.rmtree, _IMPORT_ROOT, True)
GIT_HOME = os.path.join(_IMPORT_ROOT, "home")
os.makedirs(GIT_HOME)

def load_maintain():
    keys = {"SWARM_DIR": SWARM_DIR, "SWARM_STATE": os.path.join(_IMPORT_ROOT, "swarm-state"),
            "MAINT_STATE": os.path.join(_IMPORT_ROOT, "maint-state")}
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    try:
        if JOBDIR not in sys.path:
            sys.path.insert(0, JOBDIR)
        import maintain
        return maintain
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

maint = load_maintain()
pick_task = maint.pick_task
repo_work = maint.repo_work

# ---- git ----------------------------------------------------------------------------------------------------------------------
GIT_IDENTITY = {"GIT_AUTHOR_NAME": "Maint Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Maint Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}

def git_env():
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": GIT_HOME, "GIT_CONFIG_NOSYSTEM": "1",
         "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    e.update(GIT_IDENTITY)
    return e

def git(cwd, *args, check=True):
    p = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, capture_output=True, text=True,
                       env=git_env(), timeout=120)
    if check and p.returncode:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p.stdout

def _read(path):
    with open(path) as fh:
        return fh.read()

def _read_json(path):
    return json.loads(_read(path))

def _read_jsonl(path):
    return [json.loads(l) for l in _read(path).splitlines() if l.strip()]

def write_files(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        if text is None:
            if os.path.exists(p):
                os.remove(p)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

class Remote:
    """A bare remote made from a seed repository on branch main. Branches are made in a work clone and pushed."""

    def __init__(self, root, files=SEED, name="remote"):
        seed = os.path.join(root, name + "-seed")
        os.makedirs(seed)
        git(seed, "init", "-q")
        git(seed, "symbolic-ref", "HEAD", "refs/heads/main")
        write_files(seed, files)
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "seed")
        self.path = os.path.join(root, name + ".git")
        git(root, "clone", "-q", "--bare", seed, self.path)
        self.work = os.path.join(root, name + "-work")
        git(root, "clone", "-q", self.path, self.work)

    def sha(self, ref):
        return git(self.path, "rev-parse", ref).strip()

    def has_branch(self, ref):
        return ref in git(self.path, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()

    def branches(self, prefix=""):
        return [b for b in git(self.path, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split() if b.startswith(prefix)]

    def show(self, ref, path):
        return git(self.path, "show", "%s:%s" % (ref, path))

    def make_branch(self, name, edits):
        """Branch `name` from origin/main with `edits` (path -> text, or None to delete), pushed to the remote. Returns the head sha."""
        git(self.work, "fetch", "-q", "origin")
        git(self.work, "checkout", "-q", "-B", name, "origin/main")
        git(self.work, "reset", "-q", "--hard", "origin/main")
        git(self.work, "clean", "-fdq")
        write_files(self.work, edits)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "change for " + name)
        git(self.work, "push", "-q", "origin", name)
        return git(self.work, "rev-parse", "HEAD").strip()

    def pr_files(self, name):
        """The files of branch `name` against main, shaped like GitHub's pulls/<n>/files (patch = hunks only)."""
        git(self.work, "fetch", "-q", "origin")
        base, head = "origin/main", "origin/" + name
        status = {}
        for l in git(self.work, "diff", "--no-renames", "--name-status", "%s...%s" % (base, head)).splitlines():
            code, path = l.split("\t", 1)
            status[path] = {"A": "added", "D": "removed"}.get(code, "modified")
        out = []
        for l in git(self.work, "diff", "--no-renames", "--numstat", "%s...%s" % (base, head)).splitlines():
            a, d, path = l.split("\t", 2)
            raw = git(self.work, "diff", "--no-renames", "-U3", "%s...%s" % (base, head), "--", path).splitlines()
            start = next((i for i, l in enumerate(raw) if l.startswith("@@")), len(raw))  # GitHub patches start at the hunk
            out.append({"filename": path, "status": status.get(path, "modified"), "additions": int(a) if a.isdigit() else 0,
                        "deletions": int(d) if d.isdigit() else 0, "patch": "\n".join(raw[start:])})
        return out

    def merge_into_main(self, name):
        """Merge branch `name` into main with a merge commit (what the owner's merge does) and push main. Returns the merge sha."""
        git(self.work, "fetch", "-q", "origin")
        git(self.work, "checkout", "-q", "-B", "main", "origin/main")
        git(self.work, "reset", "-q", "--hard", "origin/main")
        git(self.work, "merge", "-q", "--no-ff", "-m", "Merge " + name, "origin/" + name)
        git(self.work, "push", "-q", "origin", "main")
        return git(self.work, "rev-parse", "HEAD").strip()

# ---- stub GitHub API ----------------------------------------------------------------------------------------------------------
class MaintStub:
    """Stub GitHub REST API for maintain.py. Serves the endpoints the job uses; records (method, path-with-query, body).
    `head_script[n]`: successive GETs of pull n return these head shas (the last one sticks), to model a head that moves."""

    def __init__(self):
        self.lock = threading.Lock()
        self.requests = []
        self.repos = {}
        self.new_pr_number = 9
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self, method):
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(n).decode() if n else ""
                with stub.lock:
                    stub.requests.append((method, self.path, body))
                code, payload, ctype = stub.answer(method, self.path, body)
                data = payload.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

            def do_PATCH(self):
                self._handle("PATCH")

            def do_DELETE(self):
                self._handle("DELETE")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # setup
    def add_repo(self, repo, main_sha, tasklist=TASKLIST, default_branch="main"):
        self.repos[repo] = {"default_branch": default_branch, "main_sha": main_sha, "tasklist": tasklist, "pulls": {},
                            "files": {}, "comments": {}, "check_runs": {}, "head_script": {}, "merged_sha": "mergesha"}

    def add_pull(self, repo, n, *, ref, sha, files, author=LOGIN, labels=("swarm",), state="open", merged=False,
                 merge_commit_sha=None, mergeable_state="clean"):
        r = self.repos[repo]
        r["pulls"][n] = {"number": n, "state": state, "merged": merged, "merge_commit_sha": merge_commit_sha,
                         "head": {"ref": ref, "sha": sha}, "base": {"ref": r["default_branch"]},
                         "user": {"login": author}, "labels": [{"name": l} for l in labels],
                         "mergeable_state": mergeable_state, "mergeable": mergeable_state != "dirty",
                         "html_url": "https://example.invalid/pr/%d" % n}
        r["files"][n] = files

    def set_check_runs(self, repo, sha, runs):
        self.repos[repo]["check_runs"][sha] = runs

    def set_head_script(self, repo, n, shas):
        self.repos[repo]["head_script"][n] = list(shas)

    # observation
    def writes(self, method=None, path_part=None):
        """Write requests (anything but GET) in order, optionally filtered by method and a path substring."""
        with self.lock:
            return [r for r in self.requests if r[0] != "GET" and (method is None or r[0] == method)
                    and (path_part is None or path_part in r[1])]

    def all_requests(self):
        with self.lock:
            return list(self.requests)

    def clear(self):
        with self.lock:
            self.requests.clear()

    def pull_state(self, repo, n):
        return self.repos[repo]["pulls"][n]["state"]

    # routing
    def answer(self, method, raw_path, body):
        js = "application/json"
        u = urllib.parse.urlparse(raw_path)
        path = u.path
        if method == "GET" and path == "/user":
            return 200, json.dumps({"login": LOGIN}), js
        m = re.fullmatch(r"/repos/([^/]+/[^/]+)(/.*)?", path)
        if not m:
            return 404, json.dumps({"message": "Not Found"}), js
        repo, rest = m.group(1), m.group(2) or ""
        if repo not in self.repos:
            return 404, json.dumps({"message": "Not Found"}), js
        r = self.repos[repo]
        with self.lock:
            if method == "GET" and rest == "":
                return 200, json.dumps({"default_branch": r["default_branch"]}), js
            mm = re.fullmatch(r"/branches/(.+)", rest)
            if method == "GET" and mm:
                return 200, json.dumps({"commit": {"sha": r["main_sha"]}}), js
            mm = re.fullmatch(r"/commits/([0-9a-f]+)/check-runs", rest)
            if method == "GET" and mm:
                return 200, json.dumps({"check_runs": r["check_runs"].get(mm.group(1), [])}), js
            if rest == "/contents/" + TASKLIST_PATH and method == "GET":
                return 200, r["tasklist"], "text/plain"
            if rest.startswith("/contents/") and rest != "/contents/" + TASKLIST_PATH and method == "GET":
                return (200, json.dumps({"type": "file", "size": r.get("sizes", {}).get(rest[len("/contents/"):], 100)}), js) if rest.endswith(".md") else (404, "{}", js)
            if rest == "/pulls" and method == "GET":
                opened = [p for n, p in sorted(r["pulls"].items()) if p["state"] == "open"]
                return 200, json.dumps(opened), js
            if rest == "/pulls" and method == "POST":
                n = self.new_pr_number
                return 201, json.dumps({"number": n, "html_url": "https://example.invalid/pr/%d" % n}), js
            mm = re.fullmatch(r"/pulls/(\d+)", rest)
            if mm:
                n = int(mm.group(1))
                if n not in r["pulls"]:
                    return 404, json.dumps({"message": "Not Found"}), js
                if method == "GET":
                    pull = dict(r["pulls"][n], head=dict(r["pulls"][n]["head"]))
                    script = r["head_script"].get(n)
                    if script:
                        if len(script) > 1:
                            pull["head"]["sha"] = script.pop(0)
                        else:
                            pull["head"]["sha"] = script[0]
                    return 200, json.dumps(pull), js
                if method == "PATCH":
                    data = json.loads(body or "{}")
                    if data.get("state"):
                        r["pulls"][n]["state"] = data["state"]
                    return 200, json.dumps(r["pulls"][n]), js
            mm = re.fullmatch(r"/pulls/(\d+)/files", rest)
            if method == "GET" and mm:
                page = urllib.parse.parse_qs(u.query).get("page", ["1"])[0]
                files = r["files"].get(int(mm.group(1)), []) if page == "1" else []
                return 200, json.dumps(files), js
            mm = re.fullmatch(r"/pulls/(\d+)/merge", rest)
            if method == "PUT" and mm:
                n = int(mm.group(1))
                if r["pulls"].get(n, {}).get("state") != "open":
                    return 405, json.dumps({"message": "not mergeable"}), js
                r["pulls"][n].update(state="closed", merged=True, merge_commit_sha=r["merged_sha"])
                return 200, json.dumps({"sha": r["merged_sha"], "merged": True}), js
            mm = re.fullmatch(r"/issues/(\d+)/comments", rest)
            if mm:
                n = int(mm.group(1))
                if method == "GET":
                    return 200, json.dumps(r["comments"].get(n, [])), js
                if method == "POST":
                    c = {"id": len(r["comments"].get(n, [])) + 1, "body": json.loads(body or "{}").get("body", "")}
                    r["comments"].setdefault(n, []).append(c)
                    return 201, json.dumps(c), js
            mm = re.fullmatch(r"/issues/(\d+)/labels", rest)
            if method == "POST" and mm:
                return 200, json.dumps([]), js
            if method == "DELETE" and rest.startswith("/git/refs/heads/"):
                return 204, "", js
        return 404, json.dumps({"message": "Not Found"}), js

# ---- the world for one flow test ------------------------------------------------------------------------------------------------
def repo_section_yaml(repo, over):
    lines = ["%s:" % repo] + ["  %s: %s" % (k, json.dumps(v) if isinstance(v, (bool, int)) else v) for k, v in over.items()]
    return "\n".join(lines) + "\n"

def planner_for(files):
    steps = [{"id": "s%d" % n, "title": "edit " + f, "tag": "normal", "deps": [], "inputs": [f],
              "instruction": "Rewrite " + f + " as the task asks."} for n, f in enumerate(files, 1)]
    return json.dumps({"steps": steps})

class MaintWorld:
    """One throwaway world: state dirs, a bare remote with SEED files, the stub API, the fake gateway (reviewer and the
    spec 14 child's planner and worker) and the fake Haiku wrapper. `self.verdict` is the reviewer's reply text."""

    def __init__(self, test, mode="observe", repos=None, seed=None, tasklist=None):
        self.root = tempfile.mkdtemp(prefix="maint-test-")
        test.addCleanup(shutil.rmtree, self.root, True)
        self.maint_state = os.path.join(self.root, "maintainer")
        self.swarm_state = os.path.join(self.root, "swarm")
        self.hermes_home = os.path.join(self.root, "hermes")
        self.haiku_state = os.path.join(self.root, "claude-haiku")
        self.work_dir = os.path.join(self.root, "work")
        for d in (self.hermes_home, self.haiku_state, self.work_dir):
            os.makedirs(d)
        self.mode = mode
        self.verdict = VERDICT_MERGE
        self.remote = Remote(self.root, seed or SEED)
        self.stub = MaintStub()
        test.addCleanup(self.stub.close)
        self.stub.add_repo(REPO, self.remote.sha("main"), tasklist=tasklist or (seed or SEED)[TASKLIST_PATH])
        self.gateway = swarm_helpers.FakeGateway(reply=self._reply, delay=0.0)
        test.addCleanup(self.gateway.close)
        self.haiku_log = os.path.join(self.root, "haiku.log")
        self.haiku_bin = os.path.join(self.root, "claude-haiku.sh")
        swarm_helpers.write_fake_haiku(self.haiku_bin, self.haiku_log, self.gateway.url)
        self.repos_file = os.path.join(self.root, "no-repos.yaml")  # absent unless `repos` is given
        if repos:
            self.repos_file = os.path.join(self.root, "repos.yaml")
            with open(self.repos_file, "w") as f:
                f.write("".join(repo_section_yaml(REPO, repos)))

    def _reply(self, prompt):
        if "You review one pull request" in prompt:
            return self.verdict
        if "input names" in prompt:
            return planner_for(["docs/a.md"])
        return "```file\n" + CHILD_DOC.rstrip("\n") + "\n```"  # the spec 14 child's worker (its planner is above)

    # ---- fixtures
    def pr(self, n, *, task=TASK_A, remove_task=True, edits=None, ref=None, author=LOGIN, labels=("swarm",),
           mergeable_state="clean"):
        """Branch from main with the task line removed and the task's file edited, pushed to the remote; PR n registered."""
        edits = dict(GOOD_EDITS.get(task, {}) if edits is None else edits)
        if remove_task:
            current = self.remote.show("main", TASKLIST_PATH)
            if task + "\n" not in current:
                raise AssertionError("task line not on main: %r" % task)
            edits[TASKLIST_PATH] = current.replace(task + "\n", "", 1)
        ref = ref or "swarm/2026-11-19-fix-%d" % n
        sha = self.remote.make_branch(ref, edits)
        self.stub.add_pull(REPO, n, ref=ref, sha=sha, files=self.remote.pr_files(ref), author=author, labels=labels,
                           mergeable_state=mergeable_state)
        return sha

    def merge_on_main(self, n):
        """Make PR n really merged in the remote (merge commit on main) and in the stub."""
        ref = self.stub.repos[REPO]["pulls"][n]["head"]["ref"]
        sha = self.remote.merge_into_main(ref)
        self.stub.repos[REPO]["main_sha"] = sha
        self.stub.repos[REPO]["merged_sha"] = "mergesha"
        self.stub.repos[REPO]["pulls"][n].update(state="closed", merged=True, merge_commit_sha=sha)
        return sha

    # ---- running
    def env(self, **over):
        e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": GIT_HOME, "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1",
             "SWARM_DIR": SWARM_DIR, "MAINT_STATE": self.maint_state, "SWARM_STATE": self.swarm_state,
             "HERMES_HOME": self.hermes_home, "CLAUDE_HAIKU_STATE": self.haiku_state, "SWARM_TODAY": TODAY,
             "MAINT_REPOS": REPO, "MAINT_MODE_DEFAULT": self.mode, "MAINT_REPOS_FILE": self.repos_file,
             "MAINT_ALLOWED_REPOS": REPO, "SWARM_ALLOWED_REPOS": REPO,
             "SWARM_GITHUB_API": self.stub.url, "GITHUB_TOKEN": FAKE_TOKEN,
             "MAINT_CLONE_URL": self.remote.path, "SWARM_CLONE_URL": self.remote.path, "SWARM_WORK": self.work_dir,
             "SWARM_HAIKU_BIN": self.haiku_bin, "SWARM_LITELLM_URL": self.gateway.url + "/v1",
             "LITELLM_HERMES_KEY": FAKE_LITELLM_KEY, "SWARM_ORCHESTRATOR": "chat", "MAINT_WORK_TIMEOUT": "120"}
        e.update(GIT_IDENTITY)  # the engine's git commits (needs-owner PR, revert PR) need an identity
        for k, v in over.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    def run(self, *args, timeout=240, **over):
        return subprocess.run([sys.executable, "-I", MAINT_PY, *args], env=self.env(**over), capture_output=True, text=True,
                              timeout=timeout)

    # ---- observation
    def audit(self):
        p = os.path.join(self.maint_state, "audit.jsonl")
        if not os.path.exists(p):
            return []
        return _read_jsonl(p)

    def runs(self):
        return [e for e in self.audit() if e.get("event") == "run"]

    def swarm_audit(self):
        p = os.path.join(self.swarm_state, "audit.jsonl")
        if not os.path.exists(p):
            return []
        return _read_jsonl(p)

    def metrics(self):
        p = os.path.join(self.maint_state, "metrics.prom")
        return _read(p) if os.path.exists(p) else ""

    def attempts(self):
        p = os.path.join(self.maint_state, "attempts.json")
        return _read_json(p) if os.path.exists(p) else {}

    def seed_audit(self, entries):
        os.makedirs(self.maint_state, exist_ok=True)
        with open(os.path.join(self.maint_state, "audit.jsonl"), "a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

def merges(stub):
    return stub.writes("PUT", "/merge")
