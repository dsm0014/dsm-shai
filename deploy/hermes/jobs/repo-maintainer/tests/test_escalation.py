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


def pr_files(*files):
    """What GitHub's pulls/<n>/files returns for a PR: each file with its status and hunk-only patch."""
    return lambda method, path, body=None, raw=False: list(files)


def f(name, *changes, status="modified"):
    lines = ["@@ -26,1 +26,1 @@"]
    for old, new in changes:
        lines += ["-" + old, "+" + new]
    return {"filename": name, "status": status, "patch": "\n".join(lines)}


SWARM = "- [ ] [swarm] **CI check, makefile help:** create the new file `scripts/check-makefile-help.py`."
DEMOTED = SWARM.replace("[swarm]", "[needs-owner]", 1)


class DemotionOnly(unittest.TestCase):
    def check(self, *files):
        with mock.patch.object(maint, "api", pr_files(*files)):
            return maint.demotion_only(REPO, 7, TL)

    def test_one_line_swarm_to_needs_owner_is_merged(self):
        self.assertTrue(self.check(f(TL, (SWARM, DEMOTED))))

    def test_swarm_deploy_to_needs_owner_is_merged(self):
        self.assertTrue(self.check(f(TL, (SWARM.replace("[swarm]", "[swarm-deploy]"), DEMOTED))))

    def test_text_changed_on_the_same_line_is_refused(self):
        self.assertFalse(self.check(f(TL, (SWARM, DEMOTED.replace("makefile help", "make help")))))

    def test_two_changed_lines_are_refused(self):
        self.assertFalse(self.check(f(TL, (SWARM, DEMOTED), ("- [ ] [swarm] **x:** y", "- [ ] [needs-owner] **x:** y"))))

    def test_another_file_in_the_pr_is_refused(self):
        self.assertFalse(self.check(f(TL, (SWARM, DEMOTED)), f("scripts/x.py", ("a", "b"))))

    def test_a_line_already_needs_owner_is_refused(self):
        self.assertFalse(self.check(f(TL, (DEMOTED, DEMOTED))))

    def test_a_line_that_is_not_a_swarm_item_is_refused(self):
        self.assertFalse(self.check(f(TL, ("- [ ] Plain item.", "- [ ] [needs-owner] Plain item."))))


PLAIN = "- [ ] **CI check, makefile help:** create the new file `scripts/check-makefile-help.py`."


class QueueOnly(unittest.TestCase):
    def check(self, line_old, line_new, existing=("scripts/check-makefile-help.py",), files=None):
        def api(method, path, body=None, raw=False):
            if "/contents/" in path:
                target = path.split("/contents/")[1].split("?")[0]
                if target in existing:
                    return {}
                raise OSError("404 %s" % target)
            return files_resp
        files_resp = [f(TL, (line_old, line_new))] if files is None else files
        with mock.patch.object(maint, "api", api):
            return maint.queue_only(REPO, 9, TL, "main")

    def test_adds_the_marker_to_an_existing_file_task(self):
        self.assertTrue(self.check(PLAIN, PLAIN.replace("- [ ] ", "- [ ] [swarm] ", 1)))

    def test_missing_file_is_refused(self):
        self.assertFalse(self.check(PLAIN, PLAIN.replace("- [ ] ", "- [ ] [swarm] ", 1), existing=()))

    def test_forbidden_path_is_refused(self):
        bad = PLAIN.replace("scripts/check-makefile-help.py", ".github/workflows/ci.yml")
        self.assertFalse(self.check(bad, bad.replace("- [ ] ", "- [ ] [swarm] ", 1), existing=(".github/workflows/ci.yml",)))

    def test_deploy_class_path_is_refused(self):
        bad = PLAIN.replace("scripts/check-makefile-help.py", "deploy/istio/egress/proxy.yaml")
        self.assertFalse(self.check(bad, bad.replace("- [ ] ", "- [ ] [swarm] ", 1), existing=("deploy/istio/egress/proxy.yaml",)))

    def test_more_than_three_files_is_refused(self):
        many = PLAIN.replace("`scripts/check-makefile-help.py`", "`a.py` `b.py` `c.py` `d.py`")
        self.assertFalse(self.check(many, many.replace("- [ ] ", "- [ ] [swarm] ", 1), existing=("a.py", "b.py", "c.py", "d.py")))

    def test_other_text_changed_is_refused(self):
        self.assertFalse(self.check(PLAIN, PLAIN.replace("- [ ] ", "- [ ] [swarm] ", 1).replace("makefile", "make")))


class MergeDemotions(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="demote-")
        self.patch = mock.patch.object(maint, "STATE", self.state)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.state, ignore_errors=True)

    def test_merges_only_the_one_line_demotion(self):
        one_line = f(TL, (SWARM, DEMOTED))
        two_lines = f(TL, (SWARM, DEMOTED), ("- [ ] [swarm] **x:** y", "- [ ] [needs-owner] **x:** y"))
        title = "maintainer: mark a failing task [needs-owner] (makefile help)"
        pulls = [{"number": 1, "title": title, "head": {"ref": "maintainer/needs-owner-a", "sha": "s1"}},
                 {"number": 2, "title": title, "head": {"ref": "maintainer/needs-owner-b", "sha": "s2"}},
                 {"number": 3, "title": "swarm: something", "head": {"ref": "swarm/x", "sha": "s3"}}]
        calls = []

        def api(method, path, body=None, raw=False):
            calls.append((method, path))
            if method == "GET" and path.startswith("/repos/%s/pulls?state=open" % REPO):
                return pulls
            if method == "GET" and path.endswith("/files?per_page=100&page=1"):
                return [one_line] if "/pulls/1/" in path else [two_lines]
            if method == "GET" and path == "/repos/%s/pulls/1" % REPO:
                return {"head": {"sha": "s1", "ref": "maintainer/needs-owner-a"}, "state": "open"}
            if method == "PUT" and path == "/repos/%s/pulls/1/merge" % REPO:
                return {"sha": "merged1"}
            return {}

        report = {"merged": 0}
        with mock.patch.object(maint, "api", api):
            maint.merge_demotions({"repo": REPO, "tasklist_path": TL, "max_merges_per_run": 1}, report)
        self.assertEqual(report["merged"], 1)
        merges = [p for m, p in calls if m == "PUT"]
        self.assertEqual(merges, ["/repos/%s/pulls/1/merge" % REPO])
        self.assertFalse(any(p.startswith("/repos/%s/pulls/3" % REPO) for _, p in calls), "swarm PRs are never touched here")


if __name__ == "__main__":
    unittest.main()
