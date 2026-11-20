"""Test helpers for the swarm engine (spec 13). Offline, standard library only.

- FakeGateway: stands in for LiteLLM `chat` (POST /v1/chat/completions) and for the model behind the Haiku wrapper
  (POST /haiku). Tracks in-flight and peak chat requests and returns 429 for a third concurrent chat request.
- write_fake_haiku(): a bash script that plays the spec 12 wrapper (logs start/end, FAKE_HAIKU_EXIT, else asks the gateway).
- FakeGitHub: stub /repos/<repo>/commits and /repos/<repo>/commits/<sha> with three files per commit, each with a patch.
- Env: a throwaway world (state dirs, servers, wrapper) that is exported to os.environ and to subprocesses.
- run_swarm() / write_task(): run swarm.py with `python3 -I` and write a task file.

No literal tokens are stored: fake credentials are assembled at runtime."""
import http.server, json, os, re, shlex, shutil, subprocess, sys, tempfile, threading, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)  # deploy/hermes/jobs/swarm
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
SWARM_PY = os.path.join(PARENT, "swarm.py")

FAKE_HERMES_KEY = "fake-" + "hermes-key-for-tests"
FAKE_GH_TOKEN = "gh" + "p_" + "a" * 36
FAKE_GH_PAT = "github" + "_pat_" + "B" * 30
FAKE_ANTHROPIC_KEY = "sk-" + "ant-" + "c" * 24
ALLOWED_REPO = "acme/widgets"

_ACTIVE = None  # the Env whose variables run_swarm() uses


def default_reply(prompt):
    """Planner prompts get a valid plan (one normal step per listed input, then a hard merge). Worker prompts get a
    sentence of 60+ characters that names every input id found between the UNTRUSTED_CONTENT markers."""
    if "planner" in prompt:
        ids = re.findall(r"^- (\S+) \(\d+ chars\)$", prompt, re.M)
        steps = [{"id": "s%d" % n, "title": "summarise " + i, "tag": "normal", "deps": [], "inputs": [i],
                  "instruction": "Summarise the change in input %s and name that input in your answer." % i}
                 for n, i in enumerate(ids, 1)]
        steps.append({"id": "merge", "title": "merge", "tag": "hard", "deps": [s["id"] for s in steps], "inputs": [],
                      "instruction": "Merge the step results into one short report."})
        return json.dumps({"steps": steps})
    ids = re.findall(r"<<<UNTRUSTED_CONTENT input (\S+)", prompt)
    return ("Summary of this step covering %s: the change is described in the listed inputs and the worker "
            "names each one it used." % (", ".join(ids) or "the task"))


def empty_worker_reply(prompt):
    """Planner still works; every other prompt gets empty text (forces a verifier failure)."""
    return default_reply(prompt) if "planner" in prompt else ""


def _serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _send_json(h, code, obj):
    body = json.dumps(obj).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


class FakeGateway:
    """Fake LiteLLM. `reply` maps a prompt to text (or to a dict, which is sent as the raw JSON body)."""

    def __init__(self, reply=None, delay=0.05):
        self.reply = reply or default_reply
        self.delay = delay
        self.lock = threading.Lock()
        self.in_flight = self.peak = self.chat_calls = self.rejected = self.haiku_calls = 0
        self.chat_prompts, self.haiku_prompts, self.auth = [], [], []
        gw = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path == "/v1/chat/completions":
                    return gw._chat(self, raw)
                if self.path == "/haiku":
                    return gw._haiku(self, raw)
                _send_json(self, 404, {"error": "no such route"})

        self.server = _serve(Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def _chat(self, h, raw):
        with self.lock:
            reject = self.in_flight >= 2
            if reject:
                self.rejected += 1
            else:
                self.in_flight += 1
                self.peak = max(self.peak, self.in_flight)
                self.chat_calls += 1
                self.auth.append(h.headers.get("Authorization", ""))
        if reject:
            return _send_json(h, 429, {"error": {"message": "too many requests in flight"}})
        try:
            prompt = json.loads(raw)["messages"][0]["content"]
            with self.lock:
                self.chat_prompts.append(prompt)
            time.sleep(self.delay)
            out = self.reply(prompt)
            if isinstance(out, dict):
                return _send_json(h, 200, out)
            return _send_json(h, 200, {"choices": [{"message": {"content": out}}], "usage": {"total_tokens": 10}})
        finally:
            with self.lock:
                self.in_flight -= 1

    def _haiku(self, h, raw):
        prompt = raw.decode()
        with self.lock:
            self.haiku_calls += 1
            self.haiku_prompts.append(prompt)
        time.sleep(self.delay)
        body = str(self.reply(prompt)).encode()
        h.send_response(200)
        h.send_header("Content-Type", "text/plain")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeGitHub:
    """Stub API: /repos/<repo>/commits lists `commits` shas; each sha has `files_per_commit` files with patches.
    File names are unique per commit, so max_items decides how many become swarm inputs."""

    def __init__(self, commits=5, files_per_commit=3, delay=0.0):
        self.commits, self.files_per_commit, self.delay = commits, files_per_commit, delay
        self.lock = threading.Lock()
        self.auth_headers = []
        gh = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                with gh.lock:
                    gh.auth_headers.append(self.headers.get("Authorization"))
                time.sleep(gh.delay)
                path = urllib.parse.urlparse(self.path).path
                if re.fullmatch(r"/repos/[^/]+/[^/]+/commits", path):
                    return _send_json(self, 200, [{"sha": "sha%d" % i} for i in range(gh.commits)])
                m = re.fullmatch(r"/repos/[^/]+/[^/]+/commits/sha(\d+)", path)
                if m:
                    i = int(m.group(1))
                    files = [{"filename": "src/mod_%d_%d.py" % (i, k), "status": "modified",
                              "patch": "@@ -1 +1 @@\n-old line %d\n+new line %d in mod_%d_%d\n" % (k, k, i, k)}
                             for k in range(gh.files_per_commit)]
                    return _send_json(self, 200, {"sha": "sha%d" % i, "files": files})
                _send_json(self, 404, {"message": "Not Found"})

        self.server = _serve(Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeOpenViking:
    """Fake OpenViking MCP endpoint (POST /mcp) for the memory calls: initialize, notifications/initialized and tools/call, answered
    as server-sent events. `find` answers `find_text`; `read` answers read_texts[uri]; `remember` answers isError false unless
    remember_error is set; find_error makes find answer isError true. Every tools/call is recorded as (name, arguments) and every
    X-API-Key header as keys."""

    def __init__(self, find_text="", read_texts=None, remember_error=False, find_error=False):
        self.find_text, self.read_texts = find_text, dict(read_texts or {})
        self.remember_error, self.find_error = remember_error, find_error
        self.calls, self.keys, self.lock = [], [], threading.Lock()
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
                with fake.lock:
                    fake.keys.append(self.headers.get("X-API-Key"))
                msg = json.loads(raw or b"{}")
                if "id" not in msg:  # notifications get no JSON-RPC reply
                    self.send_response(202); self.send_header("Content-Length", "0"); self.end_headers()
                    return
                body = b"event: message\r\ndata: " + json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": fake._result(msg)}).encode() + b"\r\n\r\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Mcp-Session-Id", "fake-session")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = _serve(Handler)
        self.url = "http://127.0.0.1:%d/mcp" % self.server.server_address[1]

    def _result(self, msg):
        if msg.get("method") == "initialize":
            return {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "fake-openviking", "version": "1"}}
        name, args = msg["params"]["name"], msg["params"].get("arguments", {})
        with self.lock:
            self.calls.append((name, args))
        if name == "find":
            return {"isError": self.find_error, "content": [{"type": "text", "text": self.find_text}]}
        if name == "read":
            return {"isError": False, "content": [{"type": "text", "text": self.read_texts.get(args.get("uri"), "")}]}
        if name == "remember":
            return {"isError": self.remember_error, "content": []}
        return {"isError": True, "content": [{"type": "text", "text": "unknown tool"}]}

    def calls_named(self, name):
        with self.lock:
            return [a for n, a in self.calls if n == name]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


PY_ASK = ("import sys, urllib.request\n"
          "req = urllib.request.Request(sys.argv[1], data=sys.stdin.buffer.read(), method='POST')\n"
          "sys.stdout.write(urllib.request.urlopen(req, timeout=20).read().decode())\n")


def write_fake_haiku(path, log, gateway_url):
    """Fake claude-haiku.sh. Every call appends `start <ns>` and `end <ns>` to `log` (peak concurrency is computed from
    these). FAKE_HAIKU_EXIT, when set, makes the call exit with that code; otherwise the prompt on stdin is answered
    by the fake gateway."""
    script = ("#!/bin/bash\n"
              "# Fake claude-haiku wrapper for swarm tests.\n"
              "echo \"start $(date +%s%N)\" >> " + shlex.quote(log) + "\n"
              "if [ -n \"${FAKE_HAIKU_EXIT:-}\" ]; then\n"
              "  echo \"end $(date +%s%N)\" >> " + shlex.quote(log) + "\n"
              "  echo \"fake wrapper exit $FAKE_HAIKU_EXIT\" >&2\n"
              "  exit \"$FAKE_HAIKU_EXIT\"\n"
              "fi\n"
              + shlex.quote(sys.executable) + " -I -c " + shlex.quote(PY_ASK) + " " + shlex.quote(gateway_url + "/haiku") + "\n"
              "rc=$?\n"
              "echo \"end $(date +%s%N)\" >> " + shlex.quote(log) + "\n"
              "exit $rc\n")
    with open(path, "w") as f:
        f.write(script)
    os.chmod(path, 0o755)


class Env:
    """A throwaway world for one test: state dirs, fake gateway, stub GitHub API and fake Haiku wrapper.
    Entering exports the variables to os.environ and to run_swarm(); exiting restores everything and removes the tree."""

    def __init__(self, reply=None, delay=0.05, github_delay=0.0, commits=5, files_per_commit=3):
        self.root = tempfile.mkdtemp(prefix="swarm-test-")
        self.state = os.path.join(self.root, "state")
        self.haiku_state = os.path.join(self.root, "claude-haiku")
        self.hermes_home = os.path.join(self.root, "hermes")
        for d in (self.state, self.haiku_state, self.hermes_home):
            os.makedirs(d)
        self.gateway = FakeGateway(reply=reply, delay=delay)
        self.github = FakeGitHub(commits=commits, files_per_commit=files_per_commit, delay=github_delay)
        self.haiku_log = os.path.join(self.root, "haiku-calls.log")
        self.haiku_bin = os.path.join(self.root, "claude-haiku.sh")
        write_fake_haiku(self.haiku_bin, self.haiku_log, self.gateway.url)
        self.vars = {"SWARM_STATE": self.state, "CLAUDE_HAIKU_STATE": self.haiku_state,
                     "SWARM_LITELLM_URL": self.gateway.url + "/v1", "LITELLM_HERMES_KEY": FAKE_HERMES_KEY,
                     "SWARM_HAIKU_BIN": self.haiku_bin, "SWARM_GITHUB_API": self.github.url,
                     "SWARM_ALLOWED_REPOS": ALLOWED_REPO, "HERMES_HOME": self.hermes_home,
                     "PYTHONDONTWRITEBYTECODE": "1"}
        self._saved = {}

    def __enter__(self):
        global _ACTIVE
        self._saved = {k: os.environ.get(k) for k in self.vars}
        os.environ.update(self.vars)
        _ACTIVE = self
        return self

    def __exit__(self, *exc):
        global _ACTIVE
        _ACTIVE = None
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.gateway.close()
        self.github.close()
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def audit(self):
        """Audit entries as dicts (read directly, so the state dir is not an import-time global)."""
        p = os.path.join(self.state, "audit.jsonl")
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p).read().splitlines() if l.strip()]

    def digest(self):
        p = os.path.join(self.state, "digest.log")
        return open(p).read() if os.path.exists(p) else ""

    def metrics(self):
        p = os.path.join(self.state, "metrics.prom")
        return open(p).read() if os.path.exists(p) else ""

    def run_dir(self, run_id):
        return os.path.join(self.state, "runs", run_id)

    def haiku_events(self):
        """(starts, peak concurrency) from the fake wrapper's log."""
        if not os.path.exists(self.haiku_log):
            return 0, 0
        events, starts = [], 0
        for line in open(self.haiku_log).read().splitlines():
            kind, ts = line.split()
            starts += kind == "start"
            events.append((int(ts), 1 if kind == "start" else -1))
        cur = peak = 0
        for _, d in sorted(events):  # an end and a start at the same instant do not overlap
            cur += d
            peak = max(peak, cur)
        return starts, peak


def open_env(test, **kw):
    """Create an Env for a TestCase and make sure it is torn down."""
    env = Env(**kw)
    env.__enter__()
    test.addCleanup(env.__exit__, None, None, None)
    return env


def swarm_env(**env_overrides):
    """The minimal environment for a swarm.py subprocess: PATH, the active Env's variables, then overrides.
    A value of None unsets the variable."""
    if _ACTIVE is None:
        raise RuntimeError("swarm_env needs an active Env")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    env.update(_ACTIVE.vars)
    for k, v in env_overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = str(v)
    return env


def run_swarm(task_path, *args, timeout=120, **env_overrides):
    """Run `python3 -I swarm.py <task> [args]` with swarm_env(**env_overrides). Returns (rc, stdout, stderr)."""
    p = subprocess.run(["python3", "-I", SWARM_PY, task_path, *args], env=swarm_env(**env_overrides),
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def _yaml_value(v):
    return json.dumps(v) if isinstance(v, (bool, int, float)) else str(v)


def write_task(directory, **overrides):
    """Write <directory>/task.yaml in the restricted syntax lib.load_task reads. Pass None to leave a key out."""
    fields = {"name": "swarm-test", "repo": ALLOWED_REPO,
              "goal": "Summarise each changed input in two sentences.",
              "source": {"type": "github_changes", "commits": 5, "max_items": 6},
              "max_steps": 12, "max_haiku_calls": 10, "timeout_minutes": 5,
              "verifiers": ["min_chars", "max_chars"], "min_chars": 40, "max_chars": 4000}
    fields.update(overrides)
    lines = []
    for k, v in fields.items():
        if v is None:
            continue
        if isinstance(v, dict):
            lines.append(k + ":")
            lines += ["  %s: %s" % (a, _yaml_value(b)) for a, b in v.items()]
        elif isinstance(v, list):
            if v:
                lines.append(k + ":")
                lines += ["  - %s" % x for x in v]
            else:
                lines.append(k + ": []")
        else:
            lines.append("%s: %s" % (k, _yaml_value(v)))
    path = os.path.join(directory, "task.yaml")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path
