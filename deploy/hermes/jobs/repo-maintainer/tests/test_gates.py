"""Unit tests for the spec 16 gates (offline, in-process). Calls maintain.gates(), parse_verdict(), load_repos() and check_repo()
directly. Every hard gate has a case; the engine gaps found while writing these are `expectedFailure` cases that name the
line, so the suite stays green and turns red when a gap is closed (unexpected success)."""
import json, os, shutil, tempfile, unittest, unittest.mock

from helpers import JOBDIR, REPO, TASK_A, TASKLIST_PATH, maint

TL = TASKLIST_PATH


def patch_of(removed=(), added=(), context=()):
    """A GitHub-shaped patch: hunk header and prefixed lines (no ---/+++ file headers, as GitHub never sends them)."""
    lines = ["@@ -1,3 +1,3 @@"] + [" " + c for c in context] + ["-" + r for r in removed] + ["+" + a for a in added]
    return "\n".join(lines)


def f(name, adds=0, dels=0, patch="", status="modified", **extra):
    d = {"filename": name, "status": status, "additions": adds, "deletions": dels, "patch": patch}
    d.update(extra)
    return d


def tl_file(task_line=TASK_A, removed=None, added=(), extra_removed=()):
    rem = [task_line] + list(extra_removed) if removed is None else removed
    return f(TL, 0, len(rem), patch_of(removed=rem, added=added))


def good_files():
    return [tl_file(), f("docs/a.md", 2, 1, patch_of(removed=["Old intro line."], added=["New intro line.", "Another intro line."]))]


def pr(state="clean", ref="swarm/2026-11-19-fix-a"):
    return {"number": 9, "state": "open", "head": {"ref": ref, "sha": "a" * 40}, "user": {"login": "swarm-bot"},
            "labels": [{"name": "swarm"}], "mergeable_state": state, "merged": False, "merge_commit_sha": None}


def settings(**over):
    s = dict(maint.DEFAULTS, repo=REPO)
    s.update(over)
    return s


def cats(files, task_line=None, p=None, default_red=False, **over):
    fails, task = maint.gates(settings(**over), p or pr(), files, default_red)
    return sorted(set(c for c, _ in fails)), task, fails


class GateCase(unittest.TestCase):
    def assertCats(self, files, expected, **kw):
        got, _, fails = cats(files, **kw)
        self.assertEqual(got, expected, fails)


class TestGoodPassesAndForeign(GateCase):
    def test_good_pr_passes_every_gate(self):
        got, task, fails = cats(good_files())
        self.assertEqual(fails, [])
        self.assertEqual(task["files"], ["docs/a.md"])
        self.assertFalse(task["deploy"])

    def test_foreign_file_fails(self):
        files = good_files() + [f("src/evil.py", 1, 0, patch_of(added=["x = 1"]))]
        got, _, _ = cats(files)
        self.assertIn("foreign", got)

    def test_foreign_file_is_the_only_failure(self):
        files = good_files() + [f("src/evil.py", 1, 0)]
        self.assertCats(files, ["foreign"])


class TestForbiddenPaths(GateCase):
    def test_each_forbidden_path_fails(self):
        for path in (".github/x.yml", "deploy/secrets/a.sops.yaml", "CLAUDE.md", "deploy/hermes/jobs/swarm/swarm.py",
                     "deploy/hermes/jobs/claude-haiku/claude-haiku.sh", "ci/pipeline.sh", "docs/.sops.yaml"):
            with self.subTest(path=path):
                got, _, fails = cats(good_files() + [f(path, 1, 0)])
                self.assertIn("forbidden", got, fails)

    def test_forbidden_named_by_task_is_still_forbidden(self):
        task_line = "- [ ] [swarm] Edit `CLAUDE.md`"
        files = [tl_file(task_line), f("CLAUDE.md", 1, 0)]
        self.assertIn("forbidden", cats(files)[0])


class TestCaps(GateCase):
    def test_line_cap_uses_swarm_max_lines(self):
        with unittest.mock.patch.dict(os.environ, {"SWARM_MAX_LINES": "2"}):
            self.assertIn("caps", cats(good_files())[0])  # 3 lines against a cap of 2

    def test_line_cap_boundary_is_inclusive(self):
        files = [tl_file(), f("docs/a.md", 151, 150)]  # 301 lines, default cap 300
        self.assertIn("caps", cats(files)[0])
        files = [tl_file(), f("docs/a.md", 150, 150)]  # 300 lines
        self.assertNotIn("caps", cats(files)[0])

    def test_file_cap_uses_swarm_max_files(self):
        with unittest.mock.patch.dict(os.environ, {"SWARM_MAX_FILES": "1"}):
            files = good_files() + [f("docs/b.md", 1, 0)]  # tasklist + 2 files against a cap of 1 (+1 for the tasklist)
            self.assertIn("caps", cats(files)[0])

    def test_six_named_files_plus_the_tasklist_pass_the_default_file_cap(self):
        names = ["docs/%d.md" % i for i in range(6)]
        files = [tl_file(), f("docs/a.md", 1, 0)] + [f(n, 1, 0) for n in names[1:]]
        self.assertNotIn("caps", cats(files)[0])

    def test_eight_files_fail_the_default_file_cap(self):
        files = [tl_file()] + [f("docs/%d.md" % i, 1, 0) for i in range(7)]
        self.assertIn("caps", cats(files)[0])


class TestDeletionHeuristic(GateCase):
    def test_cut_down_file_fails(self):
        self.assertCats([tl_file(), f("docs/a.md", 0, 34)], ["deletion"])

    def test_one_added_two_removed_passes(self):
        self.assertCats([tl_file(), f("docs/a.md", 1, 2)], [])

    def test_threshold_is_ten_plus_twice_the_additions(self):
        self.assertCats([tl_file(), f("docs/a.md", 0, 10)], [])
        self.assertCats([tl_file(), f("docs/a.md", 0, 11)], ["deletion"])
        self.assertCats([tl_file(), f("docs/a.md", 5, 20)], [])
        self.assertCats([tl_file(), f("docs/a.md", 5, 21)], ["deletion"])


class TestTaskListChange(GateCase):
    def assertTaskListFails(self, files):
        got, task, fails = cats(files)
        self.assertIn("tasklist", got, fails)
        self.assertIsNone(task)

    def test_removing_two_lines_fails(self):
        self.assertTaskListFails([tl_file(extra_removed=["- [ ] Unmarked item for later"]), f("docs/a.md", 2, 1)])

    def test_adding_a_line_fails(self):
        self.assertTaskListFails([tl_file(added=["- [ ] [swarm] Something else in `docs/z.md`"]), f("docs/a.md", 2, 1)])

    def test_replacing_the_line_fails(self):
        self.assertTaskListFails([tl_file(added=["- [x] [swarm] Fix the intro in `docs/a.md`"]), f("docs/a.md", 2, 1)])

    def test_removing_a_line_that_is_not_an_unstarted_swarm_task_fails(self):
        self.assertTaskListFails([tl_file(task_line="- [ ] Unmarked item for later"), f("docs/a.md", 2, 1)])

    def test_missing_task_list_fails(self):
        self.assertTaskListFails([f("docs/a.md", 2, 1)])

    def test_removed_markdown_rule_is_counted(self):
        """ENGINE BUG (maintain.py patch_lines, line 129-132): a removed line whose content starts with `--` (here a markdown
        rule `---`, patch line `----`) is dropped as a file header, so removing a task line plus a rule passes 'exactly one line'."""
        self.assertTaskListFails([tl_file(extra_removed=["---"]), f("docs/a.md", 2, 1)])

    def test_added_plus_plus_line_is_counted(self):
        """ENGINE BUG (maintain.py patch_lines, line 129): an added line whose content starts with `++` is dropped as a file
        header, so a task-list edit that adds `++ note` passes the 'nothing else' rule."""
        self.assertTaskListFails([tl_file(added=["++ note"]), f("docs/a.md", 2, 1)])



class TestUntick(GateCase):
    SPEC = "specs/16-x.md"

    def spec_files(self, rem, add):
        task = "- [ ] [swarm] Tick the criteria in `%s`" % self.SPEC
        return [tl_file(task), f(self.SPEC, len(add), len(rem), patch_of(removed=rem, added=add))]

    def test_ticked_criterion_turned_unticked_fails(self):
        """The PR 60 case: a verified `- [x]` criterion comes back as `- [ ]`."""
        files = self.spec_files(["- [x] The proxy allows GitHub only"], ["- [ ] The proxy allows GitHub only"])
        got, _, fails = cats(files)
        self.assertEqual(got, ["unticked"], fails)

    def test_unrelated_edit_of_a_ticked_line_passes(self):
        files = self.spec_files(["- [x] The proxy allows GitHub only"], ["- [x] The proxy allows GitHub and the registry"])
        self.assertEqual(cats(files)[0], [], "an edit that keeps the tick must pass")

    def test_unticked_new_criterion_passes(self):
        files = self.spec_files([], ["- [ ] A brand new criterion"])
        self.assertEqual(cats(files)[0], [])

    def test_indented_ticked_criterion_turned_unticked_fails(self):
        """ENGINE BUG (maintain.py gates, lines 169-171): for an indented `  - [x]` line, `r[len("- [x]"):]` slices the
        un-stripped line, so the ticked text is wrong and the untick is not detected."""
        files = self.spec_files(["  - [x] The proxy allows GitHub only"], ["  - [ ] The proxy allows GitHub only"])
        self.assertIn("unticked", cats(files)[0])


class TestStaleRedAndDeploy(GateCase):
    def test_behind_or_dirty_head_is_stale(self):
        for state in ("behind", "dirty"):
            with self.subTest(state=state):
                got, _, fails = cats(good_files(), p=pr(state))
                self.assertEqual(got, ["stale"], fails)

    def test_clean_head_passes(self):
        self.assertEqual(cats(good_files(), p=pr("clean"))[0], [])

    def test_red_default_branch_fails(self):
        self.assertEqual(cats(good_files(), default_red=True)[0], ["red"])

    def test_deploy_class_without_swarm_deploy_fails(self):
        task_line = "- [ ] [swarm] Tune the mesh in `deploy/istio/mesh.yaml`"
        files = [tl_file(task_line), f("deploy/istio/mesh.yaml", 1, 1)]
        got, _, fails = cats(files)
        self.assertEqual(got, ["forbidden"], fails)
        self.assertIn("deploy-class", fails[0][1])

    def test_swarm_deploy_with_merge_deploy_false_fails(self):
        task_line = "- [ ] [swarm-deploy] Tune the mesh in `deploy/istio/mesh.yaml`"
        files = [tl_file(task_line), f("deploy/istio/mesh.yaml", 1, 1)]
        self.assertEqual(cats(files, merge_deploy=False)[0], ["deploy"])

    def test_swarm_deploy_with_merge_deploy_true_is_marked_deploy(self):
        task_line = "- [ ] [swarm-deploy] Tune the mesh in `deploy/istio/mesh.yaml`"
        files = [tl_file(task_line), f("deploy/istio/mesh.yaml", 1, 1)]
        _, task, _ = cats(files, merge_deploy=True)
        self.assertTrue(task["deploy"])

    def test_deploy_with_the_marker_and_merge_deploy_true_may_merge(self):
        """Owner decision: [swarm-deploy] on the task plus merge_deploy: true in repos.yaml is the explicit opt-in; without
        either, the PR is held for the owner (see the tests above)."""
        task_line = "- [ ] [swarm-deploy] Tune the mesh in `deploy/istio/mesh.yaml`"
        files = [tl_file(task_line), f("deploy/istio/mesh.yaml", 1, 1)]
        self.assertNotIn("deploy", cats(files, merge_deploy=True)[0])


class TestEngineGapsElsewhere(GateCase):
    def test_rename_away_from_a_forbidden_path_is_seen(self):
        """ENGINE BUG (maintain.py gates, line 150-156): only `filename` is checked; a rename out of `CLAUDE.md` (GitHub sets
        previous_filename) removes a forbidden file without any gate seeing it."""
        files = [tl_file(), f("docs/a.md", 0, 0, status="renamed", previous_filename="CLAUDE.md")]
        self.assertIn("forbidden", cats(files)[0])

    def test_task_with_no_named_file_is_not_a_merge(self):
        """ENGINE GAP (maintain.py gates, line 149-160): a task whose line names no file yields an empty allow-list, so a PR
        that only deletes the task line passes every gate and would reach review and merge."""
        files = [tl_file("- [ ] [swarm] Tidy the notes")]
        self.assertTrue(cats(files)[2], "a PR that changes no named file must fail a gate")


class TestParseVerdict(unittest.TestCase):
    def test_valid_json_is_accepted(self):
        v = maint.parse_verdict('{"verdict":"merge","reasons":["ok"],"concerns":[]}')
        self.assertEqual(v, {"verdict": "merge", "reasons": ["ok"], "concerns": []})

    def test_json_inside_prose_is_accepted(self):
        self.assertEqual(maint.parse_verdict('Here: {"verdict":"fix","reasons":[],"concerns":["x"]} done')["verdict"], "fix")

    def test_non_json_is_rejected(self):
        self.assertIsNone(maint.parse_verdict("I think this is fine, merge it."))
        self.assertIsNone(maint.parse_verdict(""))

    def test_bad_verdict_word_is_rejected(self):
        self.assertIsNone(maint.parse_verdict('{"verdict":"approve","reasons":[],"concerns":[]}'))
        self.assertIsNone(maint.parse_verdict('{"verdict":"MERGE"}'))
        self.assertIsNone(maint.parse_verdict('{"reasons":["ok"]}'))

    def test_non_list_reasons_are_rejected(self):
        self.assertIsNone(maint.parse_verdict('{"verdict":"merge","reasons":"ok","concerns":[]}'))
        self.assertIsNone(maint.parse_verdict('{"verdict":"merge","reasons":[],"concerns":"none"}'))
        self.assertIsNone(maint.parse_verdict('{"verdict":"merge","reasons":[1,2],"concerns":[]}'))

    def test_lists_are_capped(self):
        v = maint.parse_verdict(json.dumps({"verdict": "fix", "reasons": ["r"] * 9, "concerns": ["c" * 500]}))
        self.assertEqual(len(v["reasons"]), 6)
        self.assertEqual(len(v["concerns"][0]), 200)


class TestPatchLines(unittest.TestCase):
    def test_splits_added_and_removed_content(self):
        rem, add = maint.patch_lines("@@ -1 +1 @@\n-old\n+new\n context")
        self.assertEqual((rem, add), (["old"], ["new"]))

    def test_empty_patch(self):
        self.assertEqual(maint.patch_lines(None), ([], []))


class TestLoadRepos(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="maint-cfg-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def env(self, **kv):
        """Replace the maintainer's config variables for one test (restored afterwards)."""
        patcher = unittest.mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ("MAINT_REPOS", "MAINT_REPOS_FILE", "MAINT_MODE_DEFAULT"):
            os.environ.pop(k, None)
        os.environ["MAINT_REPOS_FILE"] = os.path.join(self.dir, "absent.yaml")
        os.environ.update(kv)

    def test_maint_repos_env_gives_defaults(self):
        self.env(MAINT_REPOS="acme/a, acme/b")
        repos = maint.load_repos()
        self.assertEqual(sorted(repos), ["acme/a", "acme/b"])
        for r in repos.values():
            self.assertEqual(r["mode"], "observe")
            self.assertEqual(r["max_merges_per_run"], 1)
            self.assertEqual(r["max_merges_per_day"], 100)
            self.assertEqual(r["branch_prefix"], "swarm/")
            self.assertFalse(r["merge_deploy"])

    def test_default_mode_comes_from_env(self):
        self.env(MAINT_REPOS="acme/a", MAINT_MODE_DEFAULT="merge")
        self.assertEqual(maint.load_repos()["acme/a"]["mode"], "merge")

    def test_repos_yaml_gives_each_repo_its_own_settings(self):
        path = os.path.join(self.dir, "repos.yaml")
        with open(path, "w") as fh:
            fh.write("acme/a:\n  mode: merge\n  max_merges_per_run: 2\n  reviewer: chat\n"
                     "acme/b:\n  mode: observe\n  merge_deploy: true\n  tasklist_path: docs/tasks.md  # the list\n")
        self.env(MAINT_REPOS_FILE=path, MAINT_REPOS="acme/c")
        repos = maint.load_repos()
        self.assertEqual(sorted(repos), ["acme/a", "acme/b", "acme/c"])
        self.assertEqual((repos["acme/a"]["mode"], repos["acme/a"]["max_merges_per_run"], repos["acme/a"]["reviewer"]),
                         ("merge", 2, "chat"))
        self.assertEqual((repos["acme/b"]["mode"], repos["acme/b"]["merge_deploy"], repos["acme/b"]["tasklist_path"]),
                         ("observe", True, "docs/tasks.md"))
        self.assertEqual(repos["acme/c"]["mode"], "observe")
        self.assertEqual(repos["acme/a"]["repo"], "acme/a")

    def test_example_config_parses(self):
        self.env(MAINT_REPOS_FILE=os.path.join(JOBDIR, "repos.yaml.example"))
        repos = maint.load_repos()
        self.assertEqual(len(repos), 1)
        only = next(iter(repos.values()))
        self.assertIn(only["mode"], maint.MODES)
        self.assertFalse(only["merge_deploy"])


class TestCheckRepo(unittest.TestCase):
    def check(self, **kv):
        base = {"MAINT_ALLOWED_REPOS": REPO, "SWARM_ALLOWED_REPOS": REPO, "MAINT_MODE": None}
        base.update(kv)
        with unittest.mock.patch.dict(os.environ, {k: v for k, v in base.items() if v is not None}):
            for k, v in base.items():
                if v is None:
                    os.environ.pop(k, None)
            maint.check_repo(REPO)

    def test_both_allowlists_admit_the_repo(self):
        self.check()

    def test_comma_lists_with_spaces_are_read(self):
        self.check(MAINT_ALLOWED_REPOS="x/y, %s ,z/w" % REPO, SWARM_ALLOWED_REPOS=" %s" % REPO)

    def test_missing_from_maint_allowlist_is_refused(self):
        with self.assertRaises(maint.Refused):
            self.check(MAINT_ALLOWED_REPOS="other/one")

    def test_missing_from_swarm_allowlist_is_refused(self):
        with self.assertRaises(maint.Refused):
            self.check(SWARM_ALLOWED_REPOS="other/one")

    def test_unset_or_empty_allowlists_are_refused(self):
        for kv in ({"MAINT_ALLOWED_REPOS": None}, {"SWARM_ALLOWED_REPOS": None}, {"MAINT_ALLOWED_REPOS": ""},
                   {"SWARM_ALLOWED_REPOS": ""}, {"MAINT_ALLOWED_REPOS": None, "SWARM_ALLOWED_REPOS": None}):
            with self.subTest(kv=kv), self.assertRaises(maint.Refused):
                self.check(**kv)

    def test_mode_off_refuses_even_when_allowed(self):
        with self.assertRaises(maint.Refused):
            self.check(MAINT_MODE="off")


if __name__ == "__main__":
    unittest.main()


class TestHeadingGate(GateCase):
    def test_a_removed_heading_is_a_structure_failure(self):
        task_line = "- [ ] [swarm] Update the row in `docs/a.md`"
        patch = "@@ -1,3 +1,2 @@\n-# Title\n \n text\n"
        files = [tl_file(task_line), {"filename": "docs/a.md", "status": "modified", "additions": 0, "deletions": 1, "patch": patch}]
        self.assertIn("structure", cats(files)[0])

    def test_a_reworded_heading_that_is_re_added_passes(self):
        task_line = "- [ ] [swarm] Update the row in `docs/a.md`"
        patch = "@@ -1,2 +1,2 @@\n-# Title\n+# Title\n text\n"
        files = [tl_file(task_line), {"filename": "docs/a.md", "status": "modified", "additions": 1, "deletions": 1, "patch": patch}]
        self.assertNotIn("structure", cats(files)[0])


class TestMergeLimitConfig(unittest.TestCase):
    """The daily merge limit defaults to 100 and is configurable by env (all repos) and by repos.yaml (one repo)."""

    def _load(self, env, yaml_text=None):
        import tempfile
        old = dict(os.environ)
        try:
            os.environ.update(env)
            if yaml_text is not None:
                fh = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
                fh.write(yaml_text); fh.close()
                os.environ["MAINT_REPOS_FILE"] = fh.name
            return maint.load_repos()
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_default_is_100_per_day_and_1_per_run(self):
        r = self._load({"MAINT_REPOS": "acme/a", "MAINT_REPOS_FILE": "/nonexistent"})["acme/a"]
        self.assertEqual((r["max_merges_per_day"], r["max_merges_per_run"]), (100, 1))

    def test_env_changes_the_default_for_every_repo(self):
        repos = self._load({"MAINT_REPOS": "acme/a,acme/b", "MAINT_REPOS_FILE": "/nonexistent", "MAINT_MAX_MERGES_PER_DAY": "250", "MAINT_MAX_MERGES_PER_RUN": "5"})
        self.assertEqual([(r["max_merges_per_day"], r["max_merges_per_run"]) for r in repos.values()], [(250, 5), (250, 5)])

    def test_repos_yaml_overrides_the_env_for_one_repo(self):
        repos = self._load({"MAINT_MAX_MERGES_PER_DAY": "250"}, "acme/a:\n  max_merges_per_day: 7\nacme/b:\n  mode: observe\n")
        self.assertEqual((repos["acme/a"]["max_merges_per_day"], repos["acme/b"]["max_merges_per_day"]), (7, 250))


class TestHeadingRenameAllowed(GateCase):
    def _files(self, task_line):
        patch = "@@ -1,3 +1,3 @@\n-## Not yet applied\n+## Applied\n text\n"
        return [tl_file(task_line), {"filename": "docs/a.md", "status": "modified", "additions": 1, "deletions": 1, "patch": patch}]

    def test_a_renamed_heading_fails_without_the_word_rename_in_the_task(self):
        self.assertIn("structure", cats(self._files("- [ ] [swarm] Reword a section in `docs/a.md`"))[0])

    def test_a_task_that_says_rename_may_rename_a_heading(self):
        self.assertNotIn("structure", cats(self._files("- [ ] [swarm] Rename the section heading in `docs/a.md`"))[0])
