"""Decision log for re-attempts (repo_work.last_attempt_decision). The GitHub API is replaced by a fake that answers the
closed-pull-request list and each PR's comments. Offline; no request leaves the process."""
import re, unittest

from helpers import ALLOWED_REPO  # noqa: F401  (sets up the import path, as the other tests do)
import repo_work

REPO = ALLOWED_REPO
TASK = "[swarm] **CI check, markdown links:** create the new file `scripts/check-markdown-links.py`. Create only this one file."
TITLE = "swarm: " + re.sub(r"\[[^\]]*\]\s*|`", "", TASK)[:70]


def fake_api(pulls, comments):
    def api(method, path, body=None, raw=False):
        assert method == "GET", "the history lookup only reads"
        if path.startswith("/repos/%s/pulls?state=closed" % REPO):
            return pulls
        m = re.match(r"/repos/%s/issues/(\d+)/comments" % re.escape(REPO), path)
        if m:
            return comments.get(int(m.group(1)), [])
        raise AssertionError("unexpected path " + path)
    return api


def pr(number, title=TITLE, head="swarm/2026-11-25-x", merged_at=None):
    return {"number": number, "title": title, "merged_at": merged_at, "head": {"ref": head}}


def close_comment(reason):
    return {"body": "**Maintainer:** closing this PR. " + reason + "\n\n<!-- maintainer:abc:close -->"}


class LastAttemptDecision(unittest.TestCase):
    def setUp(self):
        self.orig = repo_work.api

    def tearDown(self):
        repo_work.api = self.orig

    def test_latest_closed_attempt_reason_wins(self):
        repo_work.api = fake_api(
            [pr(146), pr(147), pr(149)],
            {146: [close_comment("first reason")], 147: [{"body": "thanks"}, close_comment("second reason")],
             149: [close_comment("third reason")]})
        number, text = repo_work.last_attempt_decision(REPO, TASK)
        self.assertEqual(number, 149)
        self.assertIn("third reason", text)

    def test_merged_and_other_tasks_are_ignored(self):
        repo_work.api = fake_api(
            [pr(140, merged_at="2026-11-25T20:00:00Z"), pr(141, title="swarm: **CI check, yaml tabs:** other"),
             pr(142, title=TITLE, head="feature/not-swarm"), pr(143)],
            {143: [close_comment("only this one counts")], 140: [close_comment("merged, so ignored")]})
        number, text = repo_work.last_attempt_decision(REPO, TASK)
        self.assertEqual(number, 143)
        self.assertIn("only this one counts", text)

    def test_no_attempt_returns_none(self):
        repo_work.api = fake_api([pr(9, title="swarm: **Another task:** x")], {})
        self.assertEqual(repo_work.last_attempt_decision(REPO, TASK), (None, ""))

    def test_closed_attempt_without_reason_still_reports_the_number(self):
        repo_work.api = fake_api([pr(150)], {150: [{"body": "a note, not a close"}]})
        self.assertEqual(repo_work.last_attempt_decision(REPO, TASK), (150, ""))


class LastFailedRunReason(unittest.TestCase):
    """A run that stopped before opening a PR leaves no close comment, so the next attempt learns from the audit entry instead."""
    TEXT = "[swarm] **CI check, task list lint:** create the new file `scripts/check-task-list.py`. " + "x" * 200

    def reason_for(self, rows, text=None):
        from unittest import mock
        with mock.patch.object(repo_work.lib, "read_audit", lambda: rows):
            return repo_work.last_failed_run_reason(text or self.TEXT)

    def row(self, status, reason="", pr_url="", text=None, kind="repo_work"):
        return {"kind": kind, "status": status, "reason": reason, "pr_url": pr_url, "picked": (text or self.TEXT)[:120]}

    def test_the_latest_failure_before_a_pr_is_returned(self):
        rows = [self.row("failed", "Failed: tests failed (exit 2): tasklist.md:69: expected 1-3 repository path tokens")]
        self.assertIn("tasklist.md:69", self.reason_for(rows))

    def test_a_later_success_clears_it(self):
        rows = [self.row("failed", "Failed: old"), self.row("ok", pr_url="https://example.invalid/pr/5")]
        self.assertEqual(self.reason_for(rows), "")

    def test_only_the_newest_run_for_the_task_counts(self):
        rows = [self.row("failed", "Failed: older"), self.row("failed", "Failed: newer")]
        self.assertEqual(self.reason_for(rows), "Failed: newer")

    def test_other_tasks_and_other_kinds_are_ignored(self):
        rows = [self.row("failed", "Failed: elsewhere", text="[swarm] **Another task:** `a.md` " + "y" * 200),
                self.row("failed", "Failed: not repo work", kind="swarm")]
        self.assertEqual(self.reason_for(rows), "")

    def test_a_failure_that_reached_a_pr_is_left_to_the_decision_log(self):
        rows = [self.row("failed", "Failed: after a PR", pr_url="https://example.invalid/pr/6")]
        self.assertEqual(self.reason_for(rows), "")

    def test_the_reason_is_bounded(self):
        self.assertEqual(len(self.reason_for([self.row("failed", "Failed: " + "z" * 5000)])), 600)

    def test_the_reason_reaches_the_worker_as_untrusted_text(self):
        source = open(repo_work.__file__, encoding="utf-8").read()
        self.assertIn("why the latest attempt failed", source)
        self.assertIn("failed before a pull request opened", source)


if __name__ == "__main__":
    unittest.main()
