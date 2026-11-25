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


if __name__ == "__main__":
    unittest.main()
