"""Verifier use in run_step. A file-writing step is not judged by cites_inputs (it returns a whole file, which need not name its own
path), a summary step still is, and a failed step says why in its message. The model call is replaced by a fixed reply; offline."""
import tempfile, unittest

import helpers  # noqa: F401  (sets the state directories and the import path, as the other tests do)
import swarm


def make_run(task):
    run = swarm.Run(task, ["--run-id", "verifier-reasons"])
    run.dir = tempfile.mkdtemp(prefix="vr-")
    return run


def reply_with(run, text):
    run.call = lambda tier, prompt, json_mode=False: text
    run.step_prompt = lambda step, items: "prompt"


STEP = {"id": "s1", "tag": "normal", "inputs": ["docs/a.md"], "orig_len": 0}


class CitesInputsOnlyForSummaries(unittest.TestCase):
    def test_a_file_writing_step_may_omit_its_own_path(self):
        run = make_run({"verifiers": ["file_block", "keeps_size"]})
        reply_with(run, "```file\nThe whole new file, which never says its own name.\n```")
        run.run_step(dict(STEP), [])
        self.assertIn("s1", run.outputs)
        self.assertTrue(run.steps[-1]["ok"])

    def test_a_summary_step_must_still_name_its_input(self):
        run = make_run({"verifiers": []})
        reply_with(run, "A summary that never names the file it was given.")
        with self.assertRaises(swarm.Failed) as cm:
            run.run_step(dict(STEP), [])
        self.assertIn("cites_inputs: does not mention input docs/a.md", str(cm.exception))


class FailureSaysWhy(unittest.TestCase):
    def test_the_message_carries_the_last_verifier_reason(self):
        run = make_run({"verifiers": ["file_block"]})
        reply_with(run, "Here is the file, but not in a fenced block.")
        with self.assertRaises(swarm.Failed) as cm:
            run.run_step(dict(STEP), [])
        msg = str(cm.exception)
        self.assertIn("step s1 failed its verifier", msg)
        self.assertIn("file_block: no fenced file block", msg)

    def test_the_message_never_carries_the_model_text(self):
        run = make_run({"verifiers": ["file_block"]})
        reply_with(run, "SECRET-MODEL-TEXT without a fenced block")
        with self.assertRaises(swarm.Failed) as cm:
            run.run_step(dict(STEP), [])
        self.assertNotIn("SECRET-MODEL-TEXT", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
