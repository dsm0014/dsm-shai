"""Test helpers: fixture repos built at runtime, a stub GitHub API, and a stub `hermes`. No literal tokens are stored."""
import base64, datetime, http.server, json, os, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
JOB = os.path.dirname(HERE)
sys.path.insert(0, JOB)
FAKE_TOKEN = "gh" + "p_" + "a" * 36  # built at runtime so the repo's secret scan never sees a literal


def sh(*a, cwd=None, env=None):
    return subprocess.run(list(a), cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


GOOD_SPEC = """# Spec {n} — {title}

**Status:** {status}
{origin}
## Purpose

Do a thing.

## Behavior

- It does the thing.

## Acceptance Criteria

- [ ] The thing is done.
{files}"""


def spec_text(n, title="Thing", status="TODO", nightly=False, files=None):
    return GOOD_SPEC.format(n="%02d" % n, title=title, status=status,
                            origin=("\n**Origin:** nightly-improvement\n" if nightly else "\n"),
                            files=("\n## Files\n\n" + "\n".join("- `%s`" % f for f in files) + "\n") if files else "")


def make_remote(root, specs):
    """specs: {filename: text}. Returns path of a bare repo with branch main."""
    work = os.path.join(root, "seed"); os.makedirs(os.path.join(work, "specs"))
    sh("git", "init", "-q", "-b", "main", work)
    for fn, text in specs.items():
        open(os.path.join(work, "specs", fn), "w").write(text)
    open(os.path.join(work, "specs", "00-index.md"), "w").write(
        "# Specs Index\n\n| # | Spec | Status |\n|---|------|--------|\n" +
        "".join("| %s | x | TODO |\n" % fn[:2] for fn in sorted(specs)))
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    sh("git", "-C", work, "add", "-A", env=env); sh("git", "-C", work, "commit", "-q", "-m", "seed", env=env)
    bare = os.path.join(root, "remote.git")
    sh("git", "clone", "-q", "--bare", work, bare)
    return bare


class Stub(http.server.BaseHTTPRequestHandler):
    log = []
    open_prs = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        Stub.log.append(("GET", self.path))
        p = self.path
        recent = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if "/pulls?state=open" in p:
            return self._send([{"title": t, "html_url": "http://x/pr", "head": {"ref": b}, "number": 7, "created_at": ""} for t, b in Stub.open_prs])
        if "/pulls?state=closed" in p:
            return self._send([])
        if p.startswith("/search/repositories"):
            return self._send({"items": [{"full_name": "acme/specs-%d" % i, "html_url": "http://gh/acme/specs-%d" % i,
                                          "stargazers_count": 90, "pushed_at": recent, "license": {"spdx_id": "MIT"}} for i in (1, 2)]})
        if p.endswith("/readme"):
            return self._send({"content": base64.b64encode(b"# Specs\nA toolkit with drift detection and spec linting.").decode()})
        if p.endswith("/contents"):
            return self._send([{"name": "README.md", "type": "file"}, {"name": "src", "type": "dir"}])
        return self._send({"default_branch": "main"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        Stub.log.append(("POST", self.path, body.get("head")))
        self._send({"html_url": "http://x/pr/9", "number": 9}, 201)

    def do_PUT(self):
        Stub.log.append(("PUT", self.path)); self._send({"merged": True})

    def do_DELETE(self):
        Stub.log.append(("DELETE", self.path)); self._send({})


def start_stub():
    Stub.log = []; Stub.open_prs = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


STUB_HERMES = r'''#!/usr/bin/env python3
import json, os, re, sys
p = sys.argv[2] if len(sys.argv) > 2 else ""
if os.environ.get("STUB_FAIL"):
    print("garbage that is not what was asked for"); sys.exit(0)
if p.startswith("You are summarising"):
    print(json.dumps({"features": ["drift detection between specs and code", "spec linting in CI"]}))
elif p.startswith("You are finding improvement vectors"):
    print(json.dumps({"vectors": [{"title": "Spec drift detection", "keywords": ["drift", "detect"], "rationale": "r", "sources": ["acme/specs-1"]},
                                  {"title": "Spec linting command", "keywords": ["lint", "ci"], "rationale": "r", "sources": ["acme/specs-2"]}]}))
elif p.startswith("Write one specification"):
    n = re.search(r"# Spec (\d+)", p).group(1)
    t = re.search(r'"title": "([^"]+)"', p).group(1)
    f = "tools/x.txt" if os.environ.get("STUB_BARE_FILES") else "`tools/x.txt`"
    print("# Spec %s — %s\n\n**Status:** TODO\n\n## Purpose\n\nExample.\n\n## Behavior\n\n- Does it.\n\n## Acceptance Criteria\n\n- [ ] Done.\n\n## Files\n\n- %s\n" % (n, t, f))
elif p.startswith("Implement one file"):
    path = re.search(r"=== FILE: (\S+) ===", p).group(1)
    print("=== FILE: %s ===\nhello from the nightly job\n=== END ===\nUNMET: none" % path)
'''


class Env:
    """A throwaway state dir, remote repo, stub API and stub hermes."""
    def __init__(self, specs, **extra):
        self.root = tempfile.mkdtemp(prefix="nightly-test-")
        self.remote = make_remote(self.root, specs)
        self.srv, self.api = start_stub()
        self.state = os.path.join(self.root, "state")
        hb = os.path.join(self.root, "hermes"); open(hb, "w").write(STUB_HERMES); os.chmod(hb, 0o755)
        self.env = dict(os.environ, NIGHTLY_STATE=self.state, NIGHTLY_REPO="acme/target", NIGHTLY_ALLOWED_REPOS="acme/target", GITHUB_TOKEN=FAKE_TOKEN,
                        NIGHTLY_API_BASE=self.api, NIGHTLY_CLONE_URL=self.remote, HERMES_BIN=hb,
                        NIGHTLY_WORK=os.path.join(self.root, "work"), PYTHONDONTWRITEBYTECODE="1", NIGHTLY_STEP_TIMEOUT="30")
        self.env.update(extra)

    def run(self, *args, **env):
        e = dict(self.env, **env)
        r = subprocess.run(["bash", os.path.join(JOB, "run.sh")] + list(args), env=e, capture_output=True, text=True, timeout=120)
        return r

    def audit(self):
        import lib
        old = lib.STATE; lib.STATE = self.state
        try:
            return lib.read_audit()
        finally:
            lib.STATE = old

    def requests(self, method):
        return [r for r in Stub.log if r[0] == method]

    def branches(self):
        return sh("git", "-C", self.remote, "branch", "--list", "nightly/*").split()

    def close(self):
        self.srv.shutdown()
