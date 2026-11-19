import os, subprocess, unittest
from helpers import *  # noqa


class RunFlows(unittest.TestCase):
    def setUp(self):
        self.e = None

    def tearDown(self):
        if self.e:
            self.e.close()

    def mkenv(self, specs=None, **kw):
        self.e = Env(specs if specs is not None else {"01-base.md": spec_text(1, "Base", "DONE")}, **kw)
        return self.e

    def last(self):
        return self.e.audit()[-1]

    def test_not_configured_fails_closed(self):
        e = self.mkenv(); r = e.run(GITHUB_TOKEN="")
        self.assertEqual(r.returncode, 0); self.assertIn("not configured", r.stdout)
        self.assertEqual(self.last()["status"], "not_configured"); self.assertEqual(e.requests("POST"), [])

    def test_isolation_guard_refuses_other_repo(self):
        for kw in ({"NIGHTLY_REPO": "acme/other"}, {"NIGHTLY_ALLOWED_REPOS": ""}, {"NIGHTLY_REPO": "acme/target/../x"}):
            e = self.mkenv(); r = e.run(**kw)
            self.assertEqual(r.returncode, 2, kw); self.assertIn("refused", r.stderr)
            self.assertEqual(self.last()["status"], "refused"); self.assertEqual(e.requests("POST"), [])
            self.assertEqual(e.requests("GET"), []); e.close(); self.e = None

    def test_lock_held_skips(self):
        e = self.mkenv(); os.makedirs(e.state, exist_ok=True)
        holder = subprocess.Popen(["flock", os.path.join(e.state, "lock"), "sleep", "6"]); import time; time.sleep(1)
        try:
            r = e.run(); self.assertEqual(r.returncode, 0); self.assertIn("skipped: locked", r.stdout)
            self.assertEqual(self.last()["reason"], "skipped: locked")
        finally:
            holder.kill()

    def test_dry_run_mode_a_pushes_and_merges_nothing(self):
        e = self.mkenv(); r = e.run("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        a = self.last(); self.assertTrue(a["dry_run"]); self.assertEqual(a["mode"], "A"); self.assertEqual(a["status"], "ok")
        self.assertEqual(e.requests("POST"), []); self.assertEqual(e.requests("PUT"), []); self.assertEqual(e.branches(), [])

    def test_mode_a_opens_one_spec_only_pr_and_merges(self):
        e = self.mkenv(); r = e.run(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        a = self.last(); self.assertEqual((a["mode"], a["status"], a["merged"]), ("A", "ok", True))
        self.assertEqual(len(e.requests("POST")), 1); self.assertEqual(len(e.requests("PUT")), 1)
        self.assertEqual(len(e.branches()), 1)
        shown = sh("git", "-C", e.remote, "show", "--stat", "--format=", e.branches()[0])
        self.assertNotIn("src/", shown); self.assertIn("specs/02-", shown)
        self.assertNotIn(FAKE_TOKEN, open(os.path.join(e.state, "audit.jsonl")).read() + r.stdout + r.stderr)

    def test_mode_a_bare_file_paths_are_normalised_and_index_stays_three_columns(self):
        e = self.mkenv(); r = e.run(STUB_BARE_FILES="1"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        branch = e.branches()[0]
        spec = sh("git", "-C", e.remote, "show", branch + ":specs/02-" + [l for l in sh("git", "-C", e.remote, "ls-tree", "--name-only", branch, "specs/").split() if "/02-" in l][0].split("02-")[1])
        self.assertIn("- `tools/x.txt`", spec)
        idx = sh("git", "-C", e.remote, "show", branch + ":specs/00-index.md")
        rows = [l for l in idx.splitlines() if l.startswith("| 02 |") or l.startswith("| 03 |")]
        self.assertTrue(rows); self.assertTrue(all(l.count("|") == 4 for l in rows), rows)

    def test_second_run_same_day_opens_nothing(self):
        e = self.mkenv(); e.run(); n = len(e.requests("POST"))
        r = e.run(); self.assertIn("one-PR-per-night limit", r.stdout)
        self.assertEqual(len(e.requests("POST")), n)

    def test_forced_failure_discards_and_alerts(self):
        e = self.mkenv(); r = e.run(STUB_FAIL="1")
        self.assertEqual(r.returncode, 1)
        a = self.last(); self.assertEqual(a["status"], "failed"); self.assertTrue(any(not v["ok"] for v in a["verifiers"]))
        self.assertEqual(e.requests("POST"), []); self.assertEqual(e.branches(), [])
        self.assertIn("FAILED", open(os.path.join(e.state, "digest.log")).read())
        m = open(os.path.join(e.state, "metrics.prom")).read()
        self.assertIn("nightly_specter_last_run_status 0", m); self.assertIn("nightly_specter_consecutive_failures 1", m)

    def test_hold_when_nightly_pr_open(self):
        e = self.mkenv(); Stub.open_prs = [("nightly: earlier", "nightly/specs-20260101")]
        r = e.run(); self.assertEqual(r.returncode, 0); a = self.last()
        self.assertEqual((a["mode"], a["status"]), ("HOLD", "held")); self.assertEqual(e.requests("POST"), [])

    def test_repo_side_kill_switch(self):
        e = self.mkenv({"01-base.md": spec_text(1, "Base", "DONE")})
        seed = os.path.join(e.root, "seed"); open(os.path.join(seed, ".nightly-disabled"), "w").write("x")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        sh("git", "-C", seed, "add", "-A", env=env); sh("git", "-C", seed, "commit", "-q", "-m", "d", env=env)
        sh("git", "-C", seed, "push", "-q", e.remote, "main")
        r = e.run(); self.assertEqual(r.returncode, 0); self.assertEqual(self.last()["status"], "skipped"); self.assertEqual(e.requests("POST"), [])

    def impl_specs(self):
        return {"01-base.md": spec_text(1, "Base", "DONE"),
                "02-imp.md": spec_text(2, "Imp", "TODO", nightly=True, files=["tools/hello.txt"])}

    def test_mode_b_probation_holds_merge(self):
        e = self.mkenv(self.impl_specs()); r = e.run(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        a = self.last(); self.assertEqual((a["mode"], a["status"], a["merged"]), ("B", "ok", False))
        self.assertIn("probation", a["reason"]); self.assertEqual(len(e.requests("POST")), 1); self.assertEqual(e.requests("PUT"), [])

    def test_mode_b_probation_zero_merges(self):
        e = self.mkenv(self.impl_specs(), IMPL_PROBATION_NIGHTS="0"); r = e.run(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        a = self.last(); self.assertTrue(a["merged"]); self.assertEqual(len(e.requests("PUT")), 1)
        self.assertIn("nightly/impl-02", e.branches()[0])

    def test_mode_b_blocked_without_files_list(self):
        e = self.mkenv({"01-b.md": spec_text(1, "B", "TODO", nightly=True)}); e.run()
        a = self.last(); self.assertTrue(a.get("blocked")); self.assertEqual(a["status"], "ok")

    def test_preflight_reports_tools(self):
        e = self.mkenv(); r = e.run("--preflight")  # state dir deliberately does not exist yet
        self.assertIn("ok      git", r.stdout); self.assertIn("ok      flock", r.stdout); self.assertIn("state dir writable", r.stdout)


if __name__ == "__main__":
    unittest.main()
