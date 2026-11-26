"""Worker output safety (repo_work): a JSON object returned in place of a file is rejected, and the planner-only follow-up request
never enters the goal that workers see. Both came from PR 184, where a .py file was committed as {"file": ..., "followups": ...}."""
import os, re, unittest

from helpers import ALLOWED_REPO  # noqa: F401  (sets up the import path, as the other tests do)
import repo_work

SOURCE = open(repo_work.__file__, encoding="utf-8").read()


class JsonWrapper(unittest.TestCase):
    def test_the_wrapper_seen_in_pr_184_is_rejected(self):
        body = '{"file": "#!/usr/bin/env python3\\nprint(1)\\n", "followups": [], "notes": "not run"}'
        self.assertTrue(repo_work.json_wrapper("scripts/check-task-list.py", body))

    def test_a_real_python_file_is_accepted(self):
        self.assertFalse(repo_work.json_wrapper("scripts/check-x.py", "#!/usr/bin/env python3\nprint('OK')\n"))

    def test_a_dict_literal_without_the_wrapper_keys_is_accepted(self):
        self.assertFalse(repo_work.json_wrapper("scripts/table.py", '{"a": 1, "b": 2}\n'))

    def test_a_json_target_is_not_judged_by_this_rule(self):
        self.assertFalse(repo_work.json_wrapper("deploy/x.json", '{"file": "x", "notes": "y"}'))

    def test_text_that_only_starts_with_a_brace_is_accepted(self):
        self.assertFalse(repo_work.json_wrapper("docs/a.md", "{not json at all"))


class FollowupAskStaysWithThePlanner(unittest.TestCase):
    def test_the_worker_visible_goal_does_not_mention_followups(self):
        goal_lines = [l for l in SOURCE.splitlines() if re.search(r'run\.task\["goal"\]\s*=', l)]
        self.assertTrue(goal_lines, "the goal assignment moved: update this test")
        for l in goal_lines:
            self.assertNotIn("followup", l.lower())

    def test_the_ask_is_planner_only_and_forbids_copying_it_into_instructions(self):
        ask = repo_work.FOLLOWUP_ASK
        self.assertIn("top-level key", ask)
        self.assertIn("never inside a step", ask)
        self.assertIn("Never mention followups in a step's instruction", ask)

    def test_the_ask_is_passed_to_the_planner_through_the_problems_slot(self):
        self.assertRegex(SOURCE, r"problems=FOLLOWUP_ASK")


if __name__ == "__main__":
    unittest.main()
