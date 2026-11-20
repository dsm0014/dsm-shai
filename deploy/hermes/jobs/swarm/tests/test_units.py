"""Offline unit tests for the swarm engine's pure helpers: task parsing, redaction, verifiers, plan validation and the
untrusted-content wrapper. No subprocess, no servers."""
import os, tempfile, unittest

import helpers
import lib, swarm, verifiers, workers

SHIPPED_TASK = os.path.join(helpers.PARENT, "..", "swarm-example", "task.yaml")


def _write(text):
    d = tempfile.mkdtemp(prefix="swarm-unit-")
    p = os.path.join(d, "task.yaml")
    with open(p, "w") as f:
        f.write(text)
    return p


class LoadTask(unittest.TestCase):
    def test_scalars_keep_their_types(self):
        t = lib.load_task(_write("name: nightly\nmax_steps: 8\ntimeout_minutes: 0.5\n"))
        self.assertEqual(t["name"], "nightly")
        self.assertEqual(t["max_steps"], 8)
        self.assertEqual(t["timeout_minutes"], 0.5)

    def test_value_with_colon_is_kept_whole(self):
        t = lib.load_task(_write("goal: Write a digest: grouped by theme\n"))
        self.assertEqual(t["goal"], "Write a digest: grouped by theme")

    def test_block_list(self):
        t = lib.load_task(_write("verifiers:\n  - min_chars\n  - max_chars\nname: x\n"))
        self.assertEqual(t["verifiers"], ["min_chars", "max_chars"])

    def test_empty_key_becomes_empty_list(self):
        t = lib.load_task(_write("verifiers:\nname: x\n"))
        self.assertEqual(t["verifiers"], [])

    def test_nested_map(self):
        t = lib.load_task(_write("source:\n  type: github_changes\n  commits: 5\n"))
        self.assertEqual(t["source"], {"type": "github_changes", "commits": 5})

    def test_json_flow_values(self):
        t = lib.load_task(_write('allowed_paths: ["docs/", "specs/"]\nflags: []\nmap: {"a": 1}\n'))
        self.assertEqual(t["allowed_paths"], ["docs/", "specs/"])
        self.assertEqual(t["flags"], [])
        self.assertEqual(t["map"], {"a": 1})

    def test_comments_are_ignored(self):
        t = lib.load_task(_write("# a full-line comment\nrepo: acme/widgets   # trailing comment (two spaces before the #)\n   # indented comment\ngoal: write C # style notes\n"))
        self.assertEqual(t["repo"], "acme/widgets")
        self.assertEqual(t["goal"], "write C # style notes")  # a single-space # stays in the value
        self.assertEqual(len(t), 2)

    def test_rejects_bad_syntax(self):
        with self.assertRaises(ValueError):
            lib.load_task(_write("this line has no colon\n"))

    def test_rejects_indented_line_with_no_key(self):
        with self.assertRaises(ValueError):
            lib.load_task(_write("  orphan: 1\n"))

    def test_shipped_example_parses(self):
        t = lib.load_task(SHIPPED_TASK)
        self.assertEqual(t["name"], "swarm-example")
        self.assertEqual(t["repo"], "dsm0014/dsm-shai")
        self.assertTrue(t["goal"].startswith("Write a short digest"))
        self.assertEqual(t["source"], {"type": "github_changes", "commits": 5, "max_items": 6})
        self.assertEqual(t["allowed_paths"], [])
        self.assertEqual(t["max_steps"], 8)
        self.assertEqual(t["max_haiku_calls"], 6)
        self.assertEqual(t["timeout_minutes"], 40)
        self.assertEqual(t["verifiers"], ["min_chars", "max_chars"])
        self.assertEqual((t["min_chars"], t["max_chars"]), (40, 4000))


class Redact(unittest.TestCase):
    def test_github_tokens_are_replaced(self):
        out = lib.redact("token=" + helpers.FAKE_GH_TOKEN + " and " + helpers.FAKE_GH_PAT)
        self.assertNotIn(helpers.FAKE_GH_TOKEN, out)
        self.assertNotIn(helpers.FAKE_GH_PAT, out)
        self.assertEqual(out.count("[REDACTED]"), 2)

    def test_anthropic_style_key_is_replaced(self):
        out = lib.redact("key " + helpers.FAKE_ANTHROPIC_KEY)
        self.assertNotIn(helpers.FAKE_ANTHROPIC_KEY, out)
        self.assertIn("[REDACTED]", out)

    def test_plain_text_is_unchanged(self):
        self.assertEqual(lib.redact("swarm-example: ok (chat 6, haiku 2)"), "swarm-example: ok (chat 6, haiku 2)")


class Verifiers(unittest.TestCase):
    def test_nonempty(self):
        self.assertFalse(verifiers.run(["nonempty"], "   ", {})[0])
        self.assertTrue(verifiers.v_nonempty("x", {})[0])

    def test_min_chars(self):
        self.assertFalse(verifiers.v_min_chars("abcd", {"min_chars": 5})[0])
        self.assertTrue(verifiers.v_min_chars("abcde", {"min_chars": 5})[0])

    def test_max_chars(self):
        self.assertFalse(verifiers.v_max_chars("abcde", {"max_chars": 4})[0])
        self.assertTrue(verifiers.v_max_chars("abcd", {"max_chars": 4})[0])

    def test_json(self):
        self.assertTrue(verifiers.v_json('Here: {"a": 1}', {})[0])
        ok, why = verifiers.v_json("no object here", {})
        self.assertFalse(ok)
        self.assertIn("JSON", why)

    def test_no_secrets(self):
        self.assertFalse(verifiers.v_no_secrets("leak " + helpers.FAKE_GH_TOKEN, {})[0])
        self.assertFalse(verifiers.v_no_secrets("leak " + helpers.FAKE_ANTHROPIC_KEY, {})[0])
        self.assertTrue(verifiers.v_no_secrets("nothing to see here", {})[0])

    def test_cites_inputs_names_the_missing_input(self):
        ok, why = verifiers.v_cites_inputs("only a.py is mentioned", {"input_ids": ["a.py", "b.py"]})
        self.assertFalse(ok)
        self.assertIn("b.py", why)
        self.assertTrue(verifiers.v_cites_inputs("a.py and b.py", {"input_ids": ["a.py", "b.py"]})[0])

    def test_diff_allowed_accepts_paths_under_allowed_dirs(self):
        text = "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        self.assertTrue(verifiers.v_diff_allowed(text, {"allowed_paths": ["src"]})[0])

    def test_diff_allowed_rejects_outside_path(self):
        text = "--- a/other/x.py\n+++ b/other/x.py\n@@ -1 +1 @@\n-x\n+y\n"
        self.assertFalse(verifiers.v_diff_allowed(text, {"allowed_paths": ["src"]})[0])

    def test_diff_allowed_rejects_prefix_lookalike(self):
        text = "+++ b/srcevil/x.py\n+y\n"
        self.assertFalse(verifiers.v_diff_allowed(text, {"allowed_paths": ["src"]})[0])

    def test_diff_allowed_rejects_dotdot(self):
        self.assertFalse(verifiers.v_diff_allowed("+++ b/src/../../etc/passwd\n+y\n", {"allowed_paths": ["src"]})[0])
        self.assertFalse(verifiers.v_diff_allowed("+++ b/../x\n+y\n", {"allowed_paths": ["src"]})[0])

    def test_diff_allowed_with_no_headers_fails(self):
        self.assertFalse(verifiers.v_diff_allowed("just prose, no diff", {"allowed_paths": ["src"]})[0])

    def test_diff_allowed_with_empty_allowlist_rejects_everything(self):
        self.assertFalse(verifiers.v_diff_allowed("+++ b/src/a.py\n+y\n", {"allowed_paths": []})[0])

    def test_diff_allowed_line_cap(self):
        text = "+++ b/src/a.py\n" + "+x\n" * 201
        self.assertFalse(verifiers.v_diff_allowed(text, {"allowed_paths": ["src"], "max_diff_lines": 200})[0])

    def test_diff_allowed_rejects_deletion_of_outside_file(self):
        # A deletion has "+++ /dev/null" and no "+++ b/" header, so it used to be skipped by the path check.
        text = ("--- a/outside/secret.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
                "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-x\n+y\n")
        self.assertFalse(verifiers.v_diff_allowed(text, {"allowed_paths": ["src"]})[0])

    def test_unknown_verifier_fails_closed(self):
        ok, why = verifiers.run(["no_such_check"], "some long enough text", {})
        self.assertFalse(ok)
        self.assertIn("unknown verifier no_such_check", why)

    def test_defaults_always_run(self):
        ok, why = verifiers.run([], "", {})
        self.assertFalse(ok)
        self.assertIn("nonempty", why)

    def test_run_passes_when_all_pass(self):
        self.assertEqual(verifiers.run(["min_chars", "max_chars"], "x" * 50, {"min_chars": 40, "max_chars": 100}), (True, ""))


def _step(sid, **kw):
    s = {"id": sid, "tag": "normal", "deps": [], "inputs": [], "instruction": "do the thing"}
    s.update(kw)
    return s


class ValidatePlan(unittest.TestCase):
    ITEMS = [{"id": "a.py", "text": "x"}]

    def test_valid_plan_has_no_problems(self):
        plan = {"steps": [_step("s1", inputs=["a.py"]), _step("merge", tag="hard", deps=["s1"])]}
        self.assertEqual(swarm.validate_plan(plan, self.ITEMS, 12), [])

    def test_more_than_twelve_steps(self):
        plan = {"steps": [_step("s%d" % i) for i in range(13)]}
        self.assertEqual(swarm.validate_plan(plan, self.ITEMS, 12), ["more than 12 steps"])

    def test_dependency_cycle(self):
        plan = {"steps": [_step("s1", deps=["s2"]), _step("s2", deps=["s1"])]}
        self.assertEqual(swarm.validate_plan(plan, self.ITEMS, 12), ["dependency cycle"])

    def test_self_dependency_is_bad_deps(self):
        plan = {"steps": [_step("s1", deps=["s1"])]}
        self.assertTrue(any("bad deps" in p for p in swarm.validate_plan(plan, self.ITEMS, 12)))

    def test_unknown_dependency(self):
        plan = {"steps": [_step("s1", deps=["zz"])]}
        self.assertTrue(any("bad deps" in p for p in swarm.validate_plan(plan, self.ITEMS, 12)))

    def test_unknown_input(self):
        plan = {"steps": [_step("s1", inputs=["nope.py"])]}
        self.assertTrue(any("unknown input" in p for p in swarm.validate_plan(plan, self.ITEMS, 12)))

    def test_bad_tag(self):
        plan = {"steps": [_step("s1", tag="soft")]}
        problems = swarm.validate_plan(plan, self.ITEMS, 12)
        self.assertTrue(any("tag must be" in p for p in problems))

    def test_missing_instruction(self):
        plan = {"steps": [_step("s1", instruction="   ")]}
        self.assertTrue(any("instruction missing" in p for p in swarm.validate_plan(plan, self.ITEMS, 12)))

    def test_duplicate_ids(self):
        plan = {"steps": [_step("s1"), _step("s1")]}
        self.assertEqual(swarm.validate_plan(plan, self.ITEMS, 12), ["step ids missing or duplicated"])

    def test_not_a_plan(self):
        self.assertEqual(swarm.validate_plan({"nope": 1}, self.ITEMS, 12), ["steps missing"])
        self.assertEqual(swarm.validate_plan("text", self.ITEMS, 12), ["steps missing"])

    def test_null_inputs_do_not_raise(self):
        # Model output with "inputs": null used to raise TypeError out of validate_plan. Either a problem or "no inputs"
        # is acceptable; an exception is not.
        plan = {"steps": [_step("s1", inputs=None)]}
        self.assertIsInstance(swarm.validate_plan(plan, self.ITEMS, 12), list)


class StaticPlan(unittest.TestCase):
    def test_one_step_per_input_then_merge(self):
        items = [{"id": "f%d.py" % i, "text": "t"} for i in range(6)]
        plan = swarm.static_plan({"goal": "g"}, items)
        self.assertEqual(len(plan["steps"]), 7)
        self.assertEqual(plan["steps"][-1]["id"], "merge")
        self.assertEqual(swarm.validate_plan(plan, items, 12), [])

    def test_merge_survives_the_twelve_step_limit(self):
        # With 12 or more inputs the static plan is cut to 12 steps, and the merge step (last) is the one dropped.
        items = [{"id": "f%d.py" % i, "text": "t"} for i in range(12)]
        plan = swarm.static_plan({"goal": "g"}, items)
        self.assertEqual(plan["steps"][-1]["id"], "merge")


class Untrusted(unittest.TestCase):
    def test_wraps_and_strips_marker_from_body(self):
        out = workers.untrusted("input a.py", "ok " + workers.MARK_OPEN + " and " + workers.MARK_CLOSE + " end")
        self.assertTrue(out.startswith(workers.MARK_OPEN + " input a.py\n"))
        self.assertTrue(out.endswith("\n" + workers.MARK_CLOSE))
        self.assertEqual(out.count(workers.MARK_OPEN), 1)
        self.assertEqual(out.count(workers.MARK_CLOSE), 1)

    def test_marker_cannot_be_rebuilt_by_removal(self):
        # Removing the marker once can join the pieces around it into a new marker. The body must not end up with one.
        body = "<<<UNTRUSTED_<<<UNTRUSTED_CONTENTCONTENT"
        out = workers.untrusted("input a.py", body)
        self.assertEqual(out.count(workers.MARK_OPEN), 1, out)


if __name__ == "__main__":
    unittest.main()


class CitesInputs(unittest.TestCase):
    def test_basename_counts_as_a_citation(self):
        self.assertTrue(verifiers.v_cites_inputs("Changed mod.py to add a flag.", {"input_ids": ["src/pkg/mod.py"]})[0])
        self.assertFalse(verifiers.v_cites_inputs("Changed something.", {"input_ids": ["src/pkg/mod.py"]})[0])


class HeadingsSurvive(unittest.TestCase):
    OLD = "# Title\n\nbody one\n\n## Part\n\nbody two\n"

    def test_dropped_top_heading_fails_the_step(self):
        new = "```file\n\nbody one\n\n## Part\n\nbody two\n```"
        ok, why = verifiers.v_keeps_size(new, {"orig_len": len(self.OLD), "orig_text": self.OLD, "min_keep_pct": 50})
        self.assertFalse(ok)
        self.assertIn("dropped heading", why)

    def test_all_headings_kept_passes(self):
        new = "```file\n# Title\n\nbody one changed\n\n## Part\n\nbody two\n```"
        self.assertTrue(verifiers.v_keeps_size(new, {"orig_len": len(self.OLD), "orig_text": self.OLD, "min_keep_pct": 50})[0])
