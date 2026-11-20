"""OpenViking memory for the repo maintainer (spec 16). maintain.py runs as a subprocess against the MaintWorld (bare remote, stub
GitHub API, fake gateway) with a fake OpenViking MCP endpoint from the swarm test helpers. Offline. Checked: each merge, close and
first "needs changes" or observe note is remembered once; OpenViking down never changes what the maintainer does."""
import json, unittest

from helpers import REPO, VERDICT_CLOSE, VERDICT_FIX, MaintWorld, merges, swarm_helpers

KEY = "k-" + "y" * 12
DOWN = "http://127.0.0.1:1/mcp"  # nothing listens on port 1


class Memory(unittest.TestCase):
    def fake(self, **kw):
        f = swarm_helpers.FakeOpenViking(**kw)
        self.addCleanup(f.close)
        return f

    def memo(self, url):
        return {"SWARM_OPENVIKING_MCP": url, "OPENVIKING_KEY": KEY}

    def texts(self, f):
        return [m["content"] for c in f.calls_named("remember") for m in c["messages"]]

    def test_merge_is_remembered_once_and_recorded_in_the_audit(self):
        f = self.fake()
        w = MaintWorld(self, mode="merge")
        w.pr(9)
        r = w.run(**self.memo(f.url))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(merges(w.stub)), 1)
        calls = f.calls_named("remember")
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual([m["role"] for m in calls[0]["messages"]], ["user", "assistant"])
        self.assertIn("pull request #9", calls[0]["messages"][0]["content"])
        self.assertIn("Outcome: merged", calls[0]["messages"][1]["content"])
        self.assertEqual([e for e in w.audit() if e.get("event") == "merge"][0]["remembered"], True)
        self.assertTrue(w.runs()[-1]["prs"][0]["remembered"])

    def test_close_is_remembered_with_its_reason(self):
        f = self.fake()
        w = MaintWorld(self, mode="merge")
        w.pr(9)
        w.verdict = VERDICT_CLOSE
        r = w.run(**self.memo(f.url))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(w.stub.pull_state(REPO, 9), "closed")
        self.assertIn("Outcome: closed", self.texts(f)[1])
        self.assertIn("unrelated change", self.texts(f)[1])
        self.assertEqual([e for e in w.audit() if e.get("event") == "close"][0]["remembered"], True)

    def test_needs_changes_is_remembered_once_per_head(self):
        f = self.fake()
        w = MaintWorld(self, mode="merge")
        w.pr(9)
        w.verdict = VERDICT_FIX
        w.run(**self.memo(f.url))
        w.run(**self.memo(f.url))
        self.assertEqual(len(f.calls_named("remember")), 1, "the same head must not be remembered twice")
        self.assertIn("Outcome: closed", self.texts(f)[1])  # a fix verdict closes the PR now

    def test_observe_note_is_remembered_once(self):
        f = self.fake()
        w = MaintWorld(self, mode="observe")
        w.pr(9)
        w.run(**self.memo(f.url))
        w.run(**self.memo(f.url))
        self.assertEqual(len(f.calls_named("remember")), 1)
        self.assertIn("nothing done (observe mode)", self.texts(f)[1])
        self.assertEqual(w.stub.pull_state(REPO, 9), "open")

    def test_openviking_down_does_not_change_the_merge(self):
        w = MaintWorld(self, mode="merge")
        head = w.pr(9)
        r = w.run(**self.memo(DOWN))
        self.assertEqual(r.returncode, 0, r.stderr)
        puts = merges(w.stub)
        self.assertEqual(len(puts), 1)
        self.assertEqual(json.loads(puts[0][2])["sha"], head)
        self.assertEqual([e for e in w.audit() if e.get("event") == "merge"][0]["remembered"], False)
        self.assertFalse(w.runs()[-1]["prs"][0]["remembered"])

    def test_no_key_means_no_memory_call(self):
        f = self.fake()
        w = MaintWorld(self, mode="merge")
        w.pr(9)
        r = w.run(SWARM_OPENVIKING_MCP=f.url)  # URL set, key absent: nothing is sent
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(merges(w.stub)), 1)
        self.assertEqual(f.calls, [])

    def test_failed_run_is_remembered(self):
        f = self.fake()
        w = MaintWorld(self, mode="merge")
        w.pr(9)
        r = w.run(SWARM_GITHUB_API="http://127.0.0.1:1", **self.memo(f.url))  # GitHub unreachable: the run fails
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(w.runs()[-1]["status"], "failed")
        self.assertIn("Outcome: failed", self.texts(f)[1])
        self.assertIn("the maintainer run", self.texts(f)[0])


if __name__ == "__main__":
    unittest.main()
