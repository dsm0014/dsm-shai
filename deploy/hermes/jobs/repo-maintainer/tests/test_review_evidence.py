"""The reviewer sees only the diff, so it closed attempt after attempt for 'no run'. The maintainer's own run of the tests, and of
any new check script, is now handed to it. run_tests collects that run from a fresh clone of the PR head (real bare remote), and
_review puts it in the prompt as untrusted data."""
import os, shutil, tempfile, unittest
from unittest import mock

from helpers import REPO, Remote, maint


class RunTestsEvidence(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rev-ev-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_collects_the_test_run_and_runs_a_new_check_on_its_own(self):
        remote = Remote(self.root, files={"Makefile": "test:\n\t@echo tests-ran\n", "scripts/check-x.py": "print('OK x')\n"})
        pr = {"head": {"ref": "main", "sha": remote.sha("main")}}
        evidence = []
        with mock.patch.dict(os.environ, {"MAINT_CLONE_URL": remote.path}):
            ok, msg = maint.run_tests({"repo": REPO}, pr, os.path.join(self.root, "work"), evidence=evidence, files=["scripts/check-x.py"])
        self.assertTrue(ok, msg)
        text = "\n".join(evidence)
        self.assertIn("$ make test", text)
        self.assertIn("[exit 0]", text)
        self.assertIn("tests-ran", text)
        self.assertIn("$ python3 -I scripts/check-x.py", text)
        self.assertIn("OK x", text)

    def test_evidence_is_optional(self):
        remote = Remote(self.root, files={"Makefile": "test:\n\t@true\n"})
        pr = {"head": {"ref": "main", "sha": remote.sha("main")}}
        with mock.patch.dict(os.environ, {"MAINT_CLONE_URL": remote.path}):
            ok, _ = maint.run_tests({"repo": REPO}, pr, os.path.join(self.root, "work"))
        self.assertTrue(ok)


class ReviewPrompt(unittest.TestCase):
    FILES = [{"filename": "scripts/check-x.py", "patch": "+print('OK x')", "additions": 1, "deletions": 0}]

    def prompt_for(self, evidence):
        seen = []

        def fake_haiku(prompt):
            seen.append(prompt)
            return '{"verdict": "merge", "reasons": [], "concerns": []}', None

        with mock.patch.object(maint.workers, "call_haiku", fake_haiku):
            maint._review({"reviewer": "haiku"}, {"text": "- [ ] [swarm] **x:** create `scripts/check-x.py`"}, self.FILES, {"haiku": 0}, evidence)
        return seen[0]

    def test_the_run_is_in_the_prompt_as_untrusted_data(self):
        prompt = self.prompt_for("$ make test\n[exit 0]\nall passed")
        self.assertIn("[exit 0]", prompt)
        self.assertIn("all passed", prompt)
        self.assertIn("the maintainer's own run on this pull request head", prompt)
        self.assertIn("do not close or ask for changes for lack of a run", prompt)

    def test_no_run_is_said_plainly(self):
        prompt = self.prompt_for("")
        self.assertIn("(no run recorded)", prompt)
        self.assertNotIn("{{evidence}}", prompt)


if __name__ == "__main__":
    unittest.main()
