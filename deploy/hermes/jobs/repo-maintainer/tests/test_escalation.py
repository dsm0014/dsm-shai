"""Escalation to [needs-owner] (maintain.edit_tasklist_pr) against a real bare remote and a stub API.

The loop this guards against: a `maintainer/needs-owner-<key>` branch already existed on the remote, the push was refused,
the failure was swallowed, and the task was retried for ever. These tests pin the fixed behaviour."""
import os, shutil, tempfile, unittest
from unittest import mock

from helpers import REPO, Remote, maint

TL = ".specter/tasklist.md"
TASK = "- [ ] [swarm] **CI check, token patterns:** create the new file `scripts/check-no-tokens.py`."
TASKLIST = "# Tasks\n\n## S. Swarm queue\n\n" + TASK + "\n- [ ] [swarm] **Other task:** x\n"
SETTINGS = {"repo": REPO, "tasklist_path": TL}


class FakeApi:
    """Answers the three GitHub calls edit_tasklist_pr makes. `open_titles` are PRs already open."""

    def __init__(self, open_titles=()):
        self.open_titles, self.created, self.labels = list(open_titles), [], []

    def __call__(self, method, path, body=None, raw=False):
        if method == "GET" and path.startswith("/repos/%s/pulls?state=open" % REPO):
            return [{"number": i, "title": t, "head": {"ref": "x"}} for i, t in enumerate(self.open_titles, 1)]
        if method == "GET" and path == "/repos/%s" % REPO:
            return {"default_branch": "main"}
        if method == "POST" and path == "/repos/%s/pulls" % REPO:
            self.created.append(body)
            return {"number": 900 + len(self.created), "html_url": "https://example.invalid/pr/%d" % (900 + len(self.created))}
        if method == "POST" and path.endswith("/labels"):
            self.labels.append(path)
            return {}
        raise AssertionError("unexpected %s %s" % (method, path))


def mark(line):
    return line.replace("[swarm-deploy]", "[needs-owner]", 1).replace("[swarm]", "[needs-owner]", 1)


class EscalationTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="esc-")
        self.remote = Remote(self.root, files={"Makefile": "test:\n\t@true\n", TL: TASKLIST})
        self.state = os.path.join(self.root, "maint-state")
        self.env = {"MAINT_CLONE_URL": self.remote.path, "SWARM_WORK": os.path.join(self.root, "work")}
        self.patches = [mock.patch.dict(os.environ, self.env), mock.patch.object(maint, "STATE", self.state)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def digest_lines(self):
        path = os.path.join(self.state, "digest.log")
        return open(path).read().splitlines() if os.path.exists(path) else []

    def test_escalates_even_when_the_branch_name_is_taken_on_the_remote(self):
        # the stale branch from an earlier escalation, never merged
        self.remote.make_branch("maintainer/needs-owner-c581", {"unrelated.txt": "stale\n"})
        api = FakeApi()
        with mock.patch.object(maint, "api", api):
            url = maint.edit_tasklist_pr(SETTINGS, TASK, mark, "maintainer/needs-owner-c581", "maintainer: mark a failing task [needs-owner] (x)")
        self.assertTrue(url.startswith("https://example.invalid/pr/"), url)
        head = api.created[0]["head"]
        self.assertNotEqual(head, "maintainer/needs-owner-c581")
        self.assertTrue(head.startswith("maintainer/needs-owner-c581-"), head)
        self.assertIn("[needs-owner] **CI check, token patterns:**", self.remote.show(head, TL))
        self.assertNotIn("[needs-owner]", self.remote.show("main", TL))
        self.assertEqual(self.digest_lines(), [])

    def test_open_pr_with_the_same_title_is_not_duplicated(self):
        title = "maintainer: mark a failing task [needs-owner] (token patterns)"
        api = FakeApi(open_titles=[title])
        before = self.remote.branches("maintainer/")
        with mock.patch.object(maint, "api", api):
            self.assertEqual(maint.edit_tasklist_pr(SETTINGS, TASK, mark, "maintainer/needs-owner-c581", title), "already open")
        self.assertEqual(api.created, [])
        self.assertEqual(self.remote.branches("maintainer/"), before)

    def test_missing_task_line_is_logged_not_silent(self):
        api = FakeApi()
        with mock.patch.object(maint, "api", api):
            self.assertEqual(maint.edit_tasklist_pr(SETTINGS, "- [ ] [swarm] **Not on main:** y", mark, "maintainer/needs-owner-z", "t"), "")
        self.assertEqual(api.created, [])
        self.assertTrue(any("escalation not applied" in l for l in self.digest_lines()), self.digest_lines())

    def test_failed_clone_is_logged_with_the_step(self):
        api = FakeApi()
        with mock.patch.dict(os.environ, {"MAINT_CLONE_URL": os.path.join(self.root, "missing.git")}), mock.patch.object(maint, "api", api):
            self.assertEqual(maint.edit_tasklist_pr(SETTINGS, TASK, mark, "maintainer/needs-owner-z", "t"), "")
        self.assertEqual(api.created, [])
        self.assertTrue(any("escalation failed at clone" in l for l in self.digest_lines()), self.digest_lines())


if __name__ == "__main__":
    unittest.main()
