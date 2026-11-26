"""PR evidence (repo_work.evidence): the engine records what it ran before it opened the PR, so the maintainer's review has
a run to look at. Real temp directories and real subprocesses; offline."""
import os, shutil, tempfile, types, unittest

from helpers import ALLOWED_REPO  # noqa: F401  (sets up the import path, as the other tests do)
import repo_work


def result(code, out="", err=""):
    return types.SimpleNamespace(returncode=code, stdout=out, stderr=err)


class Evidence(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="evidence-")
        os.makedirs(os.path.join(self.root, "scripts"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), "w") as fh:
            fh.write(text)

    def test_records_the_test_command_exit_code_and_output_tail(self):
        out = repo_work.evidence(self.root, [], "make test", result(0, "\n".join("line %d" % i for i in range(30)) + "\nALL OK\n"))
        self.assertIn("$ make test", out)
        self.assertIn("[exit 0]", out)
        self.assertIn("ALL OK", out)
        self.assertNotIn("line 0\n", out)  # only the tail is kept

    def test_runs_a_new_python_check_on_its_own(self):
        self.write("scripts/check-x.py", "print('OK x')\n")
        out = repo_work.evidence(self.root, ["scripts/check-x.py"], "", None)
        self.assertIn("$ python3 -I scripts/check-x.py", out)
        self.assertIn("[exit 0]", out)
        self.assertIn("OK x", out)

    def test_runs_a_new_shell_check_and_reports_its_failure(self):
        self.write("scripts/check-y.sh", "echo 'bad.txt: broken'\nexit 1\n")
        out = repo_work.evidence(self.root, ["scripts/check-y.sh"], "", None)
        self.assertIn("$ bash scripts/check-y.sh", out)
        self.assertIn("[exit 1]", out)
        self.assertIn("bad.txt: broken", out)

    def test_a_file_that_is_not_a_check_script_is_not_run(self):
        self.write("scripts/helper.py", "raise SystemExit('must not run')\n")
        self.write("docs.md", "text\n")
        self.assertEqual(repo_work.evidence(self.root, ["scripts/helper.py", "docs.md"], "", None), "")

    def test_the_result_is_bounded(self):
        out = repo_work.evidence(self.root, [], "make test", result(0, "x" * 20000))
        self.assertLessEqual(len(out), 3000)


if __name__ == "__main__":
    unittest.main()
