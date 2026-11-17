import json, os, subprocess, tempfile, unittest
from helpers import *  # noqa
import select_mode, guard, dedupe, lib, specutil, inventory


class SelectMode(unittest.TestCase):
    def mk(self, files):
        d = tempfile.mkdtemp()
        for fn, t in files.items():
            open(os.path.join(d, fn), "w").write(t)
        return d

    def test_b_when_nightly_todo(self):
        d = self.mk({"01-a.md": spec_text(1, "A", "DONE"), "02-b.md": spec_text(2, "B", "TODO", nightly=True)})
        self.assertEqual(select_mode.select(d, [])[0], "B")

    def test_a_when_only_done_or_human(self):
        d = self.mk({"01-a.md": spec_text(1, "A", "DONE", nightly=True), "02-b.md": spec_text(2, "B", "DONE")})
        self.assertEqual(select_mode.select(d, [])[0], "A")

    def test_a_when_todo_lacks_origin(self):
        d = self.mk({"01-a.md": spec_text(1, "A", "TODO")})
        self.assertEqual(select_mode.select(d, [])[0], "A")

    def test_hold_when_nightly_pr_open(self):
        d = self.mk({"01-a.md": spec_text(1, "A", "TODO", nightly=True)})
        self.assertEqual(select_mode.select(d, [{"branch": "nightly/impl-01-x", "url": "u"}])[0], "HOLD")

    def test_lowest_number_first(self):
        d = self.mk({"05-e.md": spec_text(5, "E", "TODO", nightly=True), "03-c.md": spec_text(3, "C", "PARTIAL", nightly=True)})
        self.assertTrue(select_mode.select(d, [])[1].endswith("03-c.md"))


class Guard(unittest.TestCase):
    def repo(self, files):
        d = tempfile.mkdtemp(); sh("git", "init", "-q", "-b", "main", d)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        os.makedirs(d + "/specs"); open(d + "/specs/00-index.md", "w").write("| # |\n")
        sh("git", "-C", d, "add", "-A", env=env); sh("git", "-C", d, "commit", "-q", "-m", "s", env=env)
        sh("git", "-C", d, "checkout", "-q", "-b", "nightly/x")
        for p, t in files.items():
            os.makedirs(os.path.dirname(os.path.join(d, p)), exist_ok=True); open(os.path.join(d, p), "w").write(t)
        sh("git", "-C", d, "add", "-A", env=env); sh("git", "-C", d, "commit", "-q", "-m", "c", env=env)
        return d

    def check(self, d, mode="A", allowed=(), branch="nightly/x"):
        return guard.check(d, "main", "nightly/x", mode, branch, list(allowed))[0]

    def test_clean_spec_pr_passes(self):
        self.assertEqual(self.check(self.repo({"specs/02-a.md": spec_text(2)})), [])

    def test_outside_allowlist(self):
        self.assertIn("PATH_NOT_ALLOWED", self.check(self.repo({"src/app.py": "x\n"})))

    def test_github_dir_forbidden(self):
        self.assertIn("FORBIDDEN_PATH", self.check(self.repo({".github/workflows/a.yml": "x\n"})))

    def test_oversize_lines(self):
        self.assertIn("TOO_MANY_LINES", self.check(self.repo({"specs/02-a.md": spec_text(2) + "x\n" * 450})))

    def test_too_many_files_mode_b(self):
        files = {"f%d.txt" % i: "x\n" for i in range(13)}
        self.assertIn("TOO_MANY_FILES", self.check(self.repo(files), "B", list(files)))

    def test_spec_missing_section(self):
        bad = spec_text(2).replace("## Acceptance Criteria", "## Other")
        self.assertIn("SPEC_INVALID", self.check(self.repo({"specs/02-a.md": bad})))

    def test_secret_in_diff(self):
        self.assertIn("SECRET_IN_DIFF", self.check(self.repo({"specs/02-a.md": spec_text(2) + FAKE_TOKEN + "\n"})))

    def test_branch_prefix(self):
        self.assertIn("BRANCH_PREFIX", self.check(self.repo({"specs/02-a.md": spec_text(2)}), branch="feature/x"))

    def test_mode_b_only_named_paths(self):
        d = self.repo({"tools/a.txt": "x\n", "tools/b.txt": "y\n"})
        self.assertEqual(self.check(d, "B", ["tools/a.txt"]), ["PATH_NOT_ALLOWED"])

    def test_cli_exit_code(self):
        d = self.repo({"src/app.py": "x\n"})
        r = subprocess.run([sys.executable, "-I", os.path.join(JOB, "guard.py"), "--repo", d, "--base", "main", "--head", "nightly/x",
                            "--mode", "A", "--branch", "nightly/x"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1); self.assertIn("PATH_NOT_ALLOWED", r.stderr)


class Dedupe(unittest.TestCase):
    def test_drops_overlap_keeps_new(self):
        kept = dedupe.dedupe([{"title": "Spec drift detection", "keywords": ["drift"]}, {"title": "Export to PDF", "keywords": ["pdf"]}],
                             ["Spec drift detection command"])
        self.assertEqual([v["title"] for v in kept], ["Export to PDF"])


class Lib(unittest.TestCase):
    def test_probation_counting(self):
        ok = {"status": "ok"}; bad = {"status": "failed"}
        self.assertEqual(lib.clean_nights([]), 0)  # missing audit fails safe
        self.assertEqual(lib.clean_nights([bad] + [ok] * 7), 7)
        self.assertEqual(lib.clean_nights([ok] * 7 + [bad]), 0)
        self.assertEqual(lib.clean_nights([ok] * 7 + [{"status": "revert"}]), 0)
        self.assertEqual(lib.clean_nights([ok] * 3 + [{"status": "held"}, {"status": "ok", "dry_run": True}]), 3)

    def test_redact(self):
        self.assertNotIn(FAKE_TOKEN, lib.redact("x " + FAKE_TOKEN))
        self.assertNotIn("github" + "_pat_" + "B" * 30, lib.redact("github" + "_pat_" + "B" * 30))


class SpecUtil(unittest.TestCase):
    def test_allowed_paths(self):
        self.assertEqual(specutil.allowed_paths(spec_text(1, files=["a/b.py", "docs/"])), ["a/b.py", "docs/"])
        self.assertEqual(specutil.allowed_paths(spec_text(1)), [])
        self.assertEqual(specutil.allowed_paths("## Files\n\n- `../etc/passwd`\n"), [])

    def test_normalize_files_wraps_bare_paths(self):
        t = "## Files\n- .claude/settings.json\n- docs/i18n/\n- `already/ok.py`\n\n## Next\n- not/a/path.txt\n"
        n = specutil.normalize_files(t)
        self.assertIn("- `.claude/settings.json`", n); self.assertIn("- `docs/i18n/`", n)
        self.assertIn("- not/a/path.txt", n)  # outside the Files section, untouched
        self.assertEqual(specutil.allowed_paths(n), [".claude/settings.json", "already/ok.py", "docs/i18n/"])

    def test_index_row_matches_column_count(self):
        three = "| # | Spec | Status |\n|---|---|---|\n| 01 | a | DONE |\n"
        four = "| # | Spec | Status | Open items |\n|---|---|---|---|\n| 01 | a | DONE | x |\n"
        r3 = specutil.index_add(three, 2, "T", "02-t.md").splitlines()[-1]
        r4 = specutil.index_add(four, 2, "T", "02-t.md").splitlines()[-1]
        self.assertEqual(r3.count("|"), 4); self.assertEqual(r4.count("|"), 5)

    def test_next_number_and_index(self):
        d = tempfile.mkdtemp(); open(d + "/03-a.md", "w").write("x")
        self.assertEqual(specutil.next_number(d), 4)
        idx = specutil.index_add("| # | S | St |\n|--|--|--|\n| 03 | a | TODO |\n", 4, "T", "04-t.md")
        self.assertIn("| 04 | [T](./04-t.md) | TODO |", idx)
        self.assertIn("| DONE |", specutil.index_set_status(idx, 4, "DONE"))


class Inventory(unittest.TestCase):
    def test_chunk_never_exceeds_limit(self):
        for c in inventory.chunk(("word " * 2000 + "\n\n") * 10, 5000):
            self.assertLessEqual(len(c), 5000 + 2)


if __name__ == "__main__":
    unittest.main()
