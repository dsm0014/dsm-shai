"""Autonomous repo work tests (spec 14). swarm.py runs with `kind: repo_work` as a subprocess against:
- a bare git remote made from a seed repo in a temp dir (SWARM_CLONE_URL), so clone, branch, commit and push are real;
- a stub GitHub REST API (SWARM_GITHUB_API) that records every request and answers 404 to anything unexpected;
- the fake LiteLLM gateway and fake Haiku wrapper from helpers.py (the planner and workers are scripted replies).
Offline. The only push target is the local bare remote. No test ever sends a merge request: the stub records it if the
engine tries, and the assertions check that nothing did."""
import http.server, json, os, re, shutil, subprocess, tempfile, threading, unittest, urllib.parse

from helpers import ALLOWED_REPO, FAKE_GH_TOKEN, PARENT, open_env, run_swarm
import repo_work

REPO = ALLOWED_REPO
TODAY = "2026-11-18"
TASKLIST = ("# Tasks\n\n## Open work\n\n- [x] Old finished item\n"
            "- [ ] [swarm] Rewrite the intro in `docs/a.md`\n- [ ] Unmarked item for later\n")
TASK_YAML = ("name: repo-work-test\nkind: repo_work\nrepo: %s\ngoal: Work through one swarm task in this repository.\n"
             "max_steps: 6\nmax_haiku_calls: 4\ntimeout_minutes: 5\n") % REPO
GIT_ID = {"GIT_AUTHOR_NAME": "Swarm Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
          "GIT_COMMITTER_NAME": "Swarm Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}


def seed_files(tasklist=TASKLIST):
    return {"Makefile": "test:\n\t@true\n", "docs/a.md": "# Widgets\n\nOld intro, to be replaced.\n",
            "deploy/foo/bar.yaml": "replicas: 1\n", ".specter/tasklist.md": tasklist}


def fence(text):
    return "```file\n" + text.rstrip("\n") + "\n```"


def planner_for(files):
    steps = [{"id": "s%d" % n, "title": "edit " + f, "tag": "normal", "deps": [], "inputs": [f],
              "instruction": "Rewrite " + f + " as the task asks."} for n, f in enumerate(files, 1)]
    return json.dumps({"steps": steps})


def worker_reply(prompt):
    ids = re.findall(r"<<<UNTRUSTED_CONTENT input (\S+)", prompt)
    return fence("# Rewritten\n\nThis content was written for %s by the swarm test worker.\n" % ", ".join(ids or ["nothing"]))


def reply_for(files, worker=worker_reply):
    def reply(prompt):
        return planner_for(files) if "planner" in prompt else worker(prompt)
    return reply


def _git_env(home):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_TERMINAL_PROMPT": "0"}
    env.update(GIT_ID)
    return env


def git(cwd, home, *args):
    p = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, capture_output=True, text=True,
                       env=_git_env(home), timeout=120)
    if p.returncode:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p.stdout


def make_remote(root, name, files):
    """Seed repo on branch main, then a bare clone of it. Returns the bare remote path."""
    seed = os.path.join(root, "seed-" + name)
    os.makedirs(seed)
    git(seed, root, "init", "-q")
    git(seed, root, "symbolic-ref", "HEAD", "refs/heads/main")
    for rel, text in files.items():
        p = os.path.join(seed, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
    git(seed, root, "add", "-A")
    git(seed, root, "commit", "-q", "-m", "seed")
    remote = os.path.join(root, "remote-" + name + ".git")
    git(root, root, "clone", "-q", "--bare", seed, remote)
    return remote


class RepoStub:
    """Stub GitHub REST API for one repo. Records every request as (method, path, body)."""

    def __init__(self, tasklist):
        self.tasklist, self.open_pulls, self.default_branch = tasklist, [], "main"
        self.requests = []
        self.lock = threading.Lock()
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self, method):
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(n).decode() if n else ""
                with stub.lock:
                    stub.requests.append((method, self.path, body))
                code, payload, ctype = stub.answer(method, urllib.parse.urlparse(self.path).path)
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

    def answer(self, method, path):
        base = "/repos/" + REPO
        js = "application/json"
        if method == "GET" and path == base:
            return 200, json.dumps({"default_branch": self.default_branch}), js
        if method == "GET" and path == base + "/pulls":
            return 200, json.dumps(self.open_pulls), js
        if method == "GET" and path == base + "/contents/.specter/tasklist.md":
            return 200, self.tasklist, "text/plain"
        if method == "POST" and path == base + "/pulls":
            return 201, json.dumps({"number": 7, "html_url": "https://example.invalid/pr/7"}), js
        if method == "POST" and path == base + "/issues/7/labels":
            return 200, "{}", js
        return 404, json.dumps({"message": "Not Found"}), js

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RepoWorkCase(unittest.TestCase):
    """Shared world: a bare remote with SEED files, a stub API, a task file, and the fake gateway (planner and workers)."""

    def setUp(self):
        self.env = open_env(self, delay=0.0)
        self.root = tempfile.mkdtemp(prefix="swarm-repo-work-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.work = os.path.join(self.root, "work")
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.work)
        os.makedirs(self.home)
        self.remote = make_remote(self.root, "main", seed_files())
        self.main_sha = git(self.remote, self.root, "rev-parse", "main").strip()
        self.stub = RepoStub(TASKLIST)
        self.addCleanup(self.stub.close)
        self.task = os.path.join(self.root, "task.yaml")
        with open(self.task, "w") as f:
            f.write(TASK_YAML)
        self.env.gateway.reply = reply_for(["docs/a.md"])

    def run_repo(self, *args, **over):
        env = {"SWARM_REPO_WORK": "1", "SWARM_WORK": self.work, "SWARM_CLONE_URL": self.remote,
               "SWARM_GITHUB_API": self.stub.url, "GITHUB_TOKEN": FAKE_GH_TOKEN, "SWARM_TODAY": TODAY,
               "SWARM_ORCHESTRATOR": "chat", "HOME": self.home, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_TERMINAL_PROMPT": "0"}
        env.update(GIT_ID)
        env.update(over)
        return run_swarm(self.task, *args, **env)

    # ---- observations
    def audit(self):
        return self.env.audit()

    def last(self):
        return self.env.audit()[-1]

    def posts(self):
        return [r for r in self.stub.requests if r[0] == "POST"]

    def branches(self):
        return git(self.remote, self.root, "for-each-ref", "--format=%(refname:short)", "refs/heads/swarm/").split()

    def show(self, ref, path):
        return git(self.remote, self.root, "show", "%s:%s" % (ref, path))

    def main_now(self):
        return git(self.remote, self.root, "rev-parse", "main").strip()

    def workdirs(self):
        return os.listdir(self.work)

    # ---- assertions
    def assertNothingPushed(self):
        self.assertEqual(self.branches(), [], "a swarm branch was pushed")
        self.assertEqual(self.main_now(), self.main_sha, "main moved")
        self.assertEqual(self.posts(), [], "a pull request or label was posted")

    def assertNoWorkerCalls(self):
        self.assertEqual(self.env.gateway.chat_calls, 0)
        self.assertEqual(self.env.gateway.haiku_calls, 0)
        self.assertEqual(self.env.haiku_events()[0], 0)

    def assertNoMergeRequest(self):
        for method, path, _ in self.stub.requests:
            self.assertNotIn("merge", path, "merge request recorded: %s %s" % (method, path))
            self.assertIn(method, ("GET", "POST"), "unexpected write: %s %s" % (method, path))


class HappyPath(RepoWorkCase):
    def test_one_task_becomes_one_pull_request_and_nothing_is_merged(self):
        rc, out, err = self.run_repo("--run-id", "run-happy")
        self.assertEqual(rc, 0, out + err)
        last = self.last()
        self.assertEqual(last["status"], "ok", last)
        self.assertEqual(last["pr_url"], "https://example.invalid/pr/7")
        self.assertEqual(last["files"], ["docs/a.md"])
        self.assertEqual(last["chat_calls"], 2)  # planner and one worker
        self.assertEqual(last["haiku_calls"], 0)

        pulls = [r for r in self.posts() if r[1] == "/repos/%s/pulls" % REPO]
        self.assertEqual(len(pulls), 1)
        pr = json.loads(pulls[0][2])
        branch = pr["head"]
        self.assertRegex(branch, r"^swarm/%s-" % TODAY)
        self.assertEqual(pr["base"], "main")
        self.assertIn("Haiku calls: 0", pr["body"])
        labels = [json.loads(r[2])["labels"] for r in self.posts() if r[1].endswith("/labels")]
        self.assertEqual(labels, [["swarm"]])

        self.assertEqual(self.branches(), [branch])
        self.assertIn("Rewritten", self.show(branch, "docs/a.md"))
        tasklist = self.show(branch, ".specter/tasklist.md")
        self.assertNotIn("Rewrite the intro", tasklist)  # the task is removed in the same commit
        self.assertIn("- [x] Old finished item", tasklist)
        self.assertIn("Unmarked item for later", tasklist)

        self.assertNoMergeRequest()
        self.assertEqual(self.main_now(), self.main_sha)
        self.assertEqual(self.workdirs(), [], "the work dir was not removed")
        self.assertIn("swarm_prs_opened_total 1", self.env.metrics())
        self.assertIn("https://example.invalid/pr/7", self.env.digest())

        # no token in anything the job writes or prints
        with open(os.path.join(self.env.state, "audit.jsonl")) as f:
            audit_text = f.read()
        written = out + err + audit_text + self.env.digest() + self.env.metrics() + pr["body"] + pr["title"]
        self.assertNotIn(FAKE_GH_TOKEN, written)


class DryRun(RepoWorkCase):
    def test_dry_run_prints_the_task_and_plan_and_calls_nothing(self):
        rc, out, err = self.run_repo("--dry-run", "--run-id", "run-dry")
        self.assertEqual(rc, 0, out + err)
        data = json.JSONDecoder().raw_decode(out)[0]
        self.assertEqual(data["task"]["files"], ["docs/a.md"])
        self.assertEqual(data["allowed_paths"], ["docs/a.md"])
        self.assertEqual([s["inputs"] for s in data["plan"]["steps"]], [["docs/a.md"]])
        self.assertNoWorkerCalls()
        self.assertNothingPushed()
        self.assertNoMergeRequest()
        last = self.last()
        self.assertTrue(last["dry_run"])
        self.assertEqual(last["status"], "ok")
        self.assertEqual(last["pr_url"], "")
        self.assertEqual(self.workdirs(), [])


class Guards(RepoWorkCase):
    def test_unset_repo_work_flag_refuses_before_any_request(self):
        rc, out, err = self.run_repo("--run-id", "run-off", SWARM_REPO_WORK=None)
        self.assertEqual(rc, 2, out + err)
        self.assertEqual(self.last()["status"], "refused")
        self.assertEqual(self.last()["reason"], "SWARM_REPO_WORK is not 1")
        self.assertEqual(self.stub.requests, [])
        self.assertNoWorkerCalls()
        self.assertNothingPushed()

    def test_repo_not_in_allowlist_refuses_before_any_request(self):
        rc, out, err = self.run_repo("--run-id", "run-allow", SWARM_ALLOWED_REPOS="other/thing")
        self.assertEqual(rc, 2, out + err)
        self.assertIn("SWARM_ALLOWED_REPOS", err)
        self.assertEqual(self.stub.requests, [])
        self.assertNoWorkerCalls()
        self.assertNothingPushed()

    def test_open_swarm_pull_request_skips_the_run(self):
        self.stub.open_pulls = [{"number": 3, "head": {"ref": "swarm/2026-11-01-old-task"}}]
        rc, out, err = self.run_repo("--run-id", "run-open")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.last()["status"], "skipped")
        self.assertEqual(self.last()["reason"], "skipped: pr open")
        self.assertNoWorkerCalls()
        self.assertNothingPushed()

    def test_open_human_pull_request_does_not_block_a_swarm_run(self):
        self.stub.open_pulls = [{"number": 4, "head": {"ref": "feature/docs"}}]
        rc, out, err = self.run_repo("--run-id", "run-human")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.last()["status"], "ok", self.last())
        self.assertEqual(len([r for r in self.posts() if r[1].endswith("/pulls")]), 1)

    def test_daily_limit_skips_after_a_pull_request_today(self):
        os.makedirs(self.env.state, exist_ok=True)
        with open(os.path.join(self.env.state, "audit.jsonl"), "a") as f:
            f.write(json.dumps({"task": "repo-work-test", "kind": "repo_work", "status": "ok", "date": TODAY,
                                "pr_url": "https://example.invalid/pr/6"}) + "\n")
        rc, out, err = self.run_repo("--run-id", "run-limit")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.last()["status"], "skipped")
        self.assertEqual(self.last()["reason"], "skipped: daily limit")
        self.assertNoWorkerCalls()
        self.assertNothingPushed()

    def test_no_eligible_task_skips(self):
        for label, text in (("unmarked only", "# Tasks\n- [ ] Plain item `docs/a.md`\n"),
                            ("started only", "# Tasks\n- [~] [swarm] Started `docs/a.md`\n")):
            with self.subTest(label):
                self.stub.tasklist = text
                rc, out, err = self.run_repo("--run-id", "run-none")
                self.assertEqual(rc, 0, out + err)
                self.assertEqual(self.last()["status"], "skipped")
                self.assertEqual(self.last()["reason"], "skipped: no eligible task")
                self.assertNoWorkerCalls()
                self.assertNothingPushed()

    def test_forbidden_paths_are_refused_before_any_worker_call(self):
        for path in (".github/workflows/x.yml", "deploy/secrets/a.sops.yaml", "CLAUDE.md",
                     "deploy/hermes/jobs/swarm/swarm.py"):
            with self.subTest(path):
                self.stub.tasklist = "# Tasks\n\n- [ ] [swarm] Edit `%s` now\n" % path
                rc, out, err = self.run_repo("--run-id", "run-forbid")
                self.assertEqual(rc, 2, out + err)
                self.assertEqual(self.last()["status"], "refused")
                self.assertTrue(self.last()["reason"].startswith("forbidden path in task"), self.last())
                self.assertNoWorkerCalls()
                self.assertNothingPushed()

    def test_more_than_the_file_cap_is_refused(self):
        self.stub.tasklist = "# Tasks\n\n- [ ] [swarm] Edit `a/1.md` `a/2.md` `a/3.md` `a/4.md` `a/5.md` `a/6.md` `a/7.md`\n"
        rc, out, err = self.run_repo("--run-id", "run-many")
        self.assertEqual(rc, 2, out + err)
        self.assertIn("SWARM_MAX_FILES", self.last()["reason"])
        self.assertNoWorkerCalls()
        self.assertNothingPushed()

    def test_deploy_path_without_marker_is_refused(self):
        self.stub.tasklist = "# Tasks\n\n- [ ] [swarm] Tune `deploy/foo/bar.yaml`\n"
        rc, out, err = self.run_repo("--run-id", "run-deploy-no")
        self.assertEqual(rc, 2, out + err)
        self.assertEqual(self.last()["reason"], "deploy-class path needs [swarm-deploy]")
        self.assertNoWorkerCalls()
        self.assertNothingPushed()

    def test_deploy_path_with_marker_is_accepted_in_dry_run(self):
        self.stub.tasklist = "# Tasks\n\n- [ ] [swarm-deploy] Tune `deploy/foo/bar.yaml`\n"
        rc, out, err = self.run_repo("--dry-run", "--run-id", "run-deploy-dry")
        self.assertEqual(rc, 0, out + err)
        data = json.JSONDecoder().raw_decode(out)[0]
        self.assertTrue(data["task"]["deploy"])
        self.assertEqual(data["allowed_paths"], ["deploy/foo/bar.yaml"])
        self.assertNoWorkerCalls()
        self.assertNothingPushed()

    def test_disabled_flag_and_hermes_pause_skip_repo_work(self):
        os.makedirs(self.env.state, exist_ok=True)
        open(os.path.join(self.env.state, "disabled"), "w").close()
        rc, out, err = self.run_repo("--run-id", "run-flag")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("skipped: swarm disabled flag", out)
        self.assertEqual(self.last()["status"], "skipped")
        os.remove(os.path.join(self.env.state, "disabled"))
        open(os.path.join(self.env.hermes_home, "ESTOP"), "w").close()
        rc, out, err = self.run_repo("--run-id", "run-estop")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.last()["reason"], "hermes paused")
        self.assertNoWorkerCalls()
        self.assertNothingPushed()

    def test_job_source_has_no_merge_call(self):
        with open(os.path.join(PARENT, "repo_work.py")) as f:
            src = f.read()
        for needle in ("/merge", "auto_merge", "merge_method", '"PUT"', '"PATCH"', '"DELETE"'):
            self.assertNotIn(needle, src)


class DeployLive(RepoWorkCase):
    def test_deploy_task_opens_a_pull_request_labelled_for_careful_review(self):
        tasklist = "# Tasks\n\n## Open work\n\n- [ ] [swarm-deploy] Tune `deploy/foo/bar.yaml`\n"
        self.stub.tasklist = tasklist
        self.remote = make_remote(self.root, "deploy", seed_files(tasklist))
        self.env.gateway.reply = reply_for(["deploy/foo/bar.yaml"])
        rc, out, err = self.run_repo("--run-id", "run-deploy")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.last()["status"], "ok", self.last())
        labels = [json.loads(r[2])["labels"] for r in self.posts() if r[1].endswith("/labels")]
        self.assertEqual(labels, [["swarm", "needs-careful-review"]])
        branch = self.branches()[0]
        self.assertIn("deploy/foo/bar.yaml", self.show(branch, "deploy/foo/bar.yaml"))
        self.assertNoMergeRequest()


class Verifiers(RepoWorkCase):
    def test_line_cap_fails_and_pushes_nothing(self):
        big = lambda prompt: fence("\n".join("line %d" % i for i in range(10)) + "\nmentions docs/a.md")
        self.env.gateway.reply = reply_for(["docs/a.md"], worker=big)
        rc, out, err = self.run_repo("--run-id", "run-cap", SWARM_MAX_LINES="1")
        self.assertEqual(rc, 1, out + err)
        self.assertEqual(self.last()["status"], "failed")
        self.assertIn("over the file or line cap", self.last()["reason"])
        self.assertNothingPushed()
        self.assertNoMergeRequest()
        self.assertEqual(self.workdirs(), [])
        self.assertIn("repo-work failed", self.env.digest())

    def test_failing_tests_fail_the_run_and_push_nothing(self):
        rc, out, err = self.run_repo("--run-id", "run-tests", SWARM_TEST_CMD="false")
        self.assertEqual(rc, 1, out + err)
        self.assertEqual(self.last()["status"], "failed")
        self.assertIn("tests failed", self.last()["reason"])
        self.assertNothingPushed()
        self.assertNoMergeRequest()
        self.assertEqual(self.workdirs(), [])
        self.assertIn("repo-work failed", self.env.digest())

    def test_worker_without_a_file_block_fails_after_retries(self):
        self.env.gateway.reply = reply_for(["docs/a.md"], worker=lambda p: "I would rather not change this file.")
        rc, out, err = self.run_repo("--run-id", "run-noblock")
        self.assertEqual(rc, 1, out + err)
        self.assertEqual(self.last()["status"], "failed")
        self.assertIn("failed its verifier", self.last()["reason"])
        self.assertEqual(self.env.gateway.chat_calls, 3)  # one planner call and two worker attempts
        self.assertNothingPushed()
        self.assertNoMergeRequest()

    def test_plan_naming_a_file_outside_the_task_fails_and_pushes_nothing(self):
        outside = json.dumps({"steps": [{"id": "s1", "title": "x", "tag": "normal", "deps": [], "inputs": ["README.md"],
                                         "instruction": "Edit the README."}]})
        self.env.gateway.reply = lambda p: outside if "planner" in p else worker_reply(p)
        rc, out, err = self.run_repo("--run-id", "run-outside")
        self.assertEqual(rc, 1, out + err)
        self.assertEqual(self.last()["status"], "failed")
        self.assertIn("invalid plan", self.last()["reason"])
        self.assertEqual(self.env.gateway.chat_calls, 2)  # the planner gets one retry
        self.assertNothingPushed()


class FormerGap(unittest.TestCase):
    def test_worker_file_containing_a_code_fence_is_kept_whole(self):
        # Engine gap (repo_work.py FENCE and extract_block; the same pattern is in verifiers.v_file_block). The worker's
        # file block closes at the first "\n```", so a markdown file with its own code fence is truncated before the
        # diff is written. The truncated file still passes every check. Remove the expectedFailure once fixed.
        reply = "```file\n# T\n\n```bash\nmake test\n```\n\nafter the block\n```"
        body = repo_work.extract_block(reply)
        self.assertEqual(body, "# T\n\n```bash\nmake test\n```\n\nafter the block\n")


if __name__ == "__main__":
    unittest.main()
