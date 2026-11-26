"""Unit tests for pick_task (spec 14): which task line is eligible, why others are skipped, and how allowed paths are
derived. Pure functions, no subprocess, no fakes."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
import pick_task


def _list(*lines):
    return "\n".join(lines) + "\n"


ELIGIBLE = "- [ ] [swarm] Rewrite the intro in `docs/a.md`"


class Pick(unittest.TestCase):
    def test_picks_first_eligible_task_with_file_list(self):
        md = _list("# Tasks", "", "- [ ] [swarm] Rewrite the intro in `docs/a.md`", "- [ ] [swarm] Fix `docs/b.md` too")
        task, skipped = pick_task.pick(md)
        self.assertEqual(task["line"], 3)
        self.assertEqual(task["files"], ["docs/a.md"])
        self.assertFalse(task["deploy"])
        self.assertEqual(skipped, [])
        self.assertIn("Rewrite the intro", task["text"])

    def test_first_in_file_order_wins_even_with_later_eligible_tasks(self):
        md = _list("- [ ] [swarm] First `one/x.py`", "- [ ] [swarm] Second `two/y.py`")
        task, _ = pick_task.pick(md)
        self.assertEqual(task["files"], ["one/x.py"])

    def test_unmarked_task_is_never_picked_and_not_listed_as_skipped(self):
        # Unmarked lines are the normal case in a task list; they are not digest noise, so they are not reported.
        md = _list("- [ ] Rewrite the intro in `docs/a.md`")
        task, skipped = pick_task.pick(md)
        self.assertIsNone(task)
        self.assertEqual(skipped, [])

    def test_started_task_is_skipped_with_reason(self):
        md = _list("- [~] [swarm] Half done `docs/a.md`", ELIGIBLE)
        task, skipped = pick_task.pick(md)
        self.assertEqual(task["line"], 2)
        self.assertEqual(skipped, [(1, "not unstarted")])

    def test_done_task_is_skipped(self):
        md = _list("- [x] [swarm] Finished `docs/a.md`")
        task, skipped = pick_task.pick(md)
        self.assertIsNone(task)
        self.assertEqual(skipped, [(1, "not unstarted")])

    def test_needs_owner_is_skipped_with_reason(self):
        md = _list("- [ ] [swarm] [needs-owner] Decide `docs/a.md`")
        task, skipped = pick_task.pick(md)
        self.assertIsNone(task)
        self.assertEqual(skipped, [(1, "needs-owner")])

    def test_items_under_excluded_headings_are_skipped(self):
        for heading in ("## Needs you at the machine", "## Proposed, not decided", "## Not planned",
                        "## NOT PLANNED (old)"):
            with self.subTest(heading=heading):
                md = _list(heading, "", "- [ ] [swarm] Do it `docs/a.md`")
                task, skipped = pick_task.pick(md)
                self.assertIsNone(task)
                self.assertEqual(skipped, [(3, "excluded heading")])

    def test_excluded_heading_does_not_leak_into_later_sections(self):
        md = _list("## Needs you at the machine", "- [ ] [swarm] Hidden `docs/a.md`", "## Open work",
                   "- [ ] [swarm] Visible `docs/b.md`")
        task, skipped = pick_task.pick(md)
        self.assertEqual(task["files"], ["docs/b.md"])
        self.assertEqual(skipped, [(2, "excluded heading")])

    def test_task_without_file_list_is_skipped_with_reason(self):
        md = _list("- [ ] [swarm] Improve the docs, no files named")
        task, skipped = pick_task.pick(md)
        self.assertIsNone(task)
        self.assertEqual(skipped, [(1, "no file list")])

    def test_swarm_deploy_marker_sets_deploy(self):
        md = _list("- [ ] [swarm-deploy] Add a limit to `deploy/foo/bar.yaml`")
        task, _ = pick_task.pick(md)
        self.assertTrue(task["deploy"])
        self.assertEqual(task["files"], ["deploy/foo/bar.yaml"])

    def test_unknown_marker_variant_is_skipped_as_bad_marker(self):
        md = _list("- [ ] [swarm-later] Do it `docs/a.md`")
        task, skipped = pick_task.pick(md)
        self.assertIsNone(task)
        self.assertEqual(skipped, [(1, "bad marker")])

    def test_allowed_paths_come_only_from_the_task_line(self):
        # Paths named elsewhere in the file (headings, other tasks, prose) never become allowed paths.
        md = _list("## Files `secret/other.py`", "Notes mention `evil/x.py`.", ELIGIBLE, "Trailing `zzz/q.py`.")
        task, _ = pick_task.pick(md)
        self.assertEqual(task["files"], ["docs/a.md"])

    def test_empty_task_list(self):
        self.assertEqual(pick_task.pick(""), (None, []))


class PathsIn(unittest.TestCase):
    def test_accepts_relative_paths_and_bare_make_files(self):
        self.assertEqual(pick_task.paths_in("edit `a/b.py` and `Makefile`"), ["a/b.py", "Makefile"])

    def test_rejects_commands(self):
        self.assertEqual(pick_task.paths_in("run `make test` to check"), [])

    def test_rejects_parent_traversal(self):
        self.assertEqual(pick_task.paths_in("`../x.py`"), [])
        self.assertEqual(pick_task.paths_in("`a/../b.py`"), [])

    def test_rejects_absolute_paths(self):
        self.assertEqual(pick_task.paths_in("`/etc/passwd`"), [])
        self.assertEqual(pick_task.paths_in("`/etc/hosts.conf`"), [])

    def test_rejects_urls(self):
        self.assertEqual(pick_task.paths_in("see `https://example.com/a.md`"), [])
        self.assertEqual(pick_task.paths_in("see `http://example.com/a/b.md`"), [])

    def test_never_returns_the_task_list_itself(self):
        self.assertEqual(pick_task.paths_in("tick it in `.specter/tasklist.md`"), [])
        self.assertEqual(pick_task.paths_in("`.specter/tasklist.md` and `docs/a.md`"), ["docs/a.md"])

    def test_rejects_wildcards_and_spaces(self):
        self.assertEqual(pick_task.paths_in("`docs/*.md`"), [])
        self.assertEqual(pick_task.paths_in("`docs/a file.md`"), [])

    def test_dedupes_and_keeps_order(self):
        self.assertEqual(pick_task.paths_in("`b/x.py` then `a/y.py` then `b/x.py`"), ["b/x.py", "a/y.py"])


class FormerGap(unittest.TestCase):
    def test_subsection_under_excluded_heading_is_still_excluded(self):
        # Engine gap (pick_task.py, pick(): `heading` is overwritten by any heading, so `### Sub` under
        # "## Needs you at the machine" makes an item count as not excluded). Spec 14 says anything under the
        # heading is never picked. Fixed: pick() now tracks the enclosing excluded section.
        md = _list("## Needs you at the machine", "### Hardware", "- [ ] [swarm] Plug in `docs/a.md`")
        task, skipped = pick_task.pick(md)
        self.assertIsNone(task)


class SkipsIneligibleToTheNextTask(unittest.TestCase):
    """An ineligible line is skipped and the picker goes on to the next proper swarm task."""

    def test_a_description_that_mentions_needs_owner_is_eligible(self):
        md = _list("- [ ] [swarm] **CI check, task list lint:** create `scripts/check-task-list.py`. Refuse a line that contains [needs-owner].")
        task, skipped = pick_task.pick(md)
        self.assertIsNotNone(task)
        self.assertEqual(skipped, [])

    def test_owner_tag_before_the_title_still_skips(self):
        md = _list("- [ ] [swarm] [needs-owner] **Decide:** change `docs/a.md`")
        task, skipped = pick_task.pick(md)
        self.assertIsNone(task)
        self.assertEqual(skipped, [(1, "needs-owner")])

    def test_skips_an_owner_item_and_picks_the_next_proper_one(self):
        md = _list("- [ ] [swarm] [needs-owner] **Decide:** change `docs/a.md`",
                   "- [ ] [swarm] **Fix intro:** rewrite `docs/b.md`.")
        task, skipped = pick_task.pick(md)
        self.assertEqual(task["line"], 2)
        self.assertEqual(skipped, [(1, "needs-owner")])

    def test_skips_a_finished_item_and_picks_the_next_proper_one(self):
        md = _list("- [x] [swarm] **Done:** change `docs/a.md`", "- [ ] [swarm] **Next:** rewrite `docs/b.md`.")
        task, skipped = pick_task.pick(md)
        self.assertEqual(task["line"], 2)
        self.assertEqual(skipped, [(1, "not unstarted")])


if __name__ == "__main__":
    unittest.main()
