"""Scheduler tests (spec 13 acceptance criteria) run swarm.py as a subprocess against the fakes in helpers.py: a fake
LiteLLM gateway, a fake claude-haiku wrapper and a stub GitHub API. No network, no cluster.

Tests named test_bug_* pin defects found while writing these tests. Each one failed on the engine as first read; the
engine was then changed by someone else, so some now pass and stay in as regression tests."""
import json, os, shutil, subprocess, tempfile, time, unittest

from helpers import (FAKE_HERMES_KEY, SWARM_PY, empty_worker_reply, default_reply, open_env, run_swarm, swarm_env,
                     write_task)
import swarm, workers


def _tmpdir(test):
    d = tempfile.mkdtemp(prefix="swarm-sched-")
    test.addCleanup(shutil.rmtree, d, True)
    return d


def _tier_reply(prompt):
    """Planner marks every normal step tier=haiku. The engine must still route by tag only."""
    if "planner" in prompt:
        plan = json.loads(default_reply(prompt))
        for s in plan["steps"]:
            s["tier"] = "haiku"
        return json.dumps(plan)
    return default_reply(prompt)


class DryRun(unittest.TestCase):
    def test_dry_run_prints_a_valid_plan_and_calls_nothing(self):
        env = open_env(self)
        task = write_task(_tmpdir(self))
        rc, out, err = run_swarm(task, "--dry-run")
        self.assertEqual(rc, 0, err)
        plan = json.JSONDecoder().raw_decode(out)[0]["plan"]
        self.assertEqual(len(plan["steps"]), 7)  # six changed inputs and the merge
        items = [{"id": i, "text": "x"} for s in plan["steps"] for i in s["inputs"]]
        self.assertEqual(swarm.validate_plan(plan, items, 12), [])
        self.assertEqual(env.gateway.chat_calls, 0)
        self.assertEqual(env.gateway.haiku_calls, 0)
        self.assertEqual(env.haiku_events()[0], 0)
        self.assertTrue(env.audit()[-1]["dry_run"])

    def test_bug_dry_run_applies_max_steps_like_a_real_run(self):
        # A real run ends `capped` when the plan has more steps than max_steps. The dry run prints the plan as valid.
        open_env(self)
        task = write_task(_tmpdir(self), max_steps=3)
        rc, out, err = run_swarm(task, "--dry-run")
        self.assertEqual(rc, 3, out)


class FullRun(unittest.TestCase):
    def test_six_inputs_end_to_end_within_caps(self):
        env = open_env(self)
        task = write_task(_tmpdir(self))
        rc, out, err = run_swarm(task, "--run-id", "run-b")
        self.assertEqual(rc, 0, out + err)
        last = env.audit()[-1]
        self.assertEqual(last["status"], "ok", last)
        self.assertEqual(last["reason"], "")
        # chat: never more than two in flight, never a 429
        self.assertGreaterEqual(env.gateway.chat_calls, 6)
        self.assertLessEqual(env.gateway.peak, 2)
        self.assertEqual(env.gateway.rejected, 0)
        # haiku: never more than SWARM_HAIKU_PARALLEL (default 2) at once
        starts, peak = env.haiku_events()
        self.assertEqual(starts, 2)  # planner and merge
        self.assertLessEqual(peak, 2)
        # counts and records
        self.assertEqual(last["haiku_calls"], 2)
        self.assertEqual(last["chat_calls"], env.gateway.chat_calls)
        self.assertEqual(len(last["steps"]), 7)
        for s in last["steps"]:
            self.assertTrue(s["ok"], s)
            self.assertEqual(s["verifier"], "ok")
            if s["tag"] == "normal":
                self.assertEqual(s["tiers"], ["chat"])
            else:
                self.assertEqual(s["tiers"], ["haiku"])
        report = os.path.join(env.run_dir("run-b"), "report.md")
        self.assertTrue(os.path.exists(report))
        self.assertTrue(open(report).read().strip())
        self.assertEqual(set(env.gateway.auth), {"Bearer " + FAKE_HERMES_KEY})
        # the public GitHub fetch sends no credential
        self.assertTrue(env.github.auth_headers)
        self.assertEqual(set(env.github.auth_headers), {None})

    def test_bug_planner_listing_is_untrusted_content(self):
        # File names come from the public repo, so they are attacker-influenced. The spec wraps fetched content in
        # delimiters; the planner prompt lists the ids bare.
        env = open_env(self)
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "run-wrap")
        self.assertEqual(rc, 0, out + err)
        planner = [p for p in env.gateway.haiku_prompts if "planner" in p][0]
        self.assertIn(workers.MARK_OPEN, planner)


class ChatOrchestrator(unittest.TestCase):
    def test_chat_only_run_with_no_wrapper_installed(self):
        env = open_env(self)
        task = write_task(_tmpdir(self))
        rc, out, err = run_swarm(task, "--run-id", "run-c", SWARM_ORCHESTRATOR="chat",
                                 SWARM_HAIKU_BIN=os.path.join(env.root, "missing-claude-haiku.sh"))
        self.assertEqual(rc, 0, out + err)
        last = env.audit()[-1]
        self.assertEqual(last["status"], "ok", last)
        self.assertEqual(last["haiku_calls"], 0)
        self.assertEqual(env.gateway.haiku_calls, 0)
        self.assertEqual(env.haiku_events()[0], 0)
        self.assertTrue(all(set(s["tiers"]) == {"chat"} for s in last["steps"]))


class VerifierFailure(unittest.TestCase):
    def test_forced_failure_fails_the_task_and_discards_work(self):
        env = open_env(self, reply=empty_worker_reply)
        task = write_task(_tmpdir(self))
        rc, out, err = run_swarm(task, "--run-id", "run-d")
        self.assertEqual(rc, 1, out + err)
        last = env.audit()[-1]
        self.assertEqual(last["status"], "failed")
        self.assertTrue(any(not s["ok"] for s in last["steps"]))
        self.assertIn("failed", env.digest().splitlines()[-1])
        self.assertIn("swarm_last_run_status 0", env.metrics().splitlines())
        d = env.run_dir("run-d")
        self.assertFalse(os.path.exists(os.path.join(d, "report.md")))
        self.assertFalse(os.path.exists(os.path.join(d, "work")))
        steps_dir = os.path.join(d, "steps")
        if os.path.isdir(steps_dir):
            self.assertEqual([f for f in os.listdir(steps_dir) if f.endswith((".out", ".tmp"))], [])


class Caps(unittest.TestCase):
    def test_max_haiku_calls_caps_the_run(self):
        env = open_env(self)
        rc, out, err = run_swarm(write_task(_tmpdir(self), max_haiku_calls=1), "--run-id", "cap-h")
        self.assertEqual(rc, 3, out + err)
        last = env.audit()[-1]
        self.assertEqual((last["status"], last["reason"]), ("capped", "max_haiku_calls"))
        self.assertLessEqual(env.haiku_events()[0], 1)
        self.assertLessEqual(env.gateway.haiku_calls, 1)

    def test_max_steps_smaller_than_plan_caps_before_any_worker(self):
        env = open_env(self)
        rc, out, err = run_swarm(write_task(_tmpdir(self), max_steps=3), "--run-id", "cap-s")
        self.assertEqual(rc, 3, out + err)
        last = env.audit()[-1]
        self.assertEqual((last["status"], last["reason"]), ("capped", "max_steps"))
        self.assertEqual(env.gateway.chat_calls, 0)

    def test_tiny_timeout_caps_the_run(self):
        # The GitHub stub is slow, so the deadline has passed before the first model call.
        env = open_env(self, github_delay=0.2)
        rc, out, err = run_swarm(write_task(_tmpdir(self), timeout_minutes=0.001), "--run-id", "cap-t")
        self.assertEqual(rc, 3, out + err)
        last = env.audit()[-1]
        self.assertEqual((last["status"], last["reason"]), ("capped", "timeout"))
        self.assertEqual(env.gateway.chat_calls, 0)
        self.assertEqual(env.gateway.haiku_calls, 0)


class Lock(unittest.TestCase):
    def test_second_launch_is_skipped_while_the_first_holds_the_lock(self):
        env = open_env(self, delay=1.0)
        task = write_task(_tmpdir(self))
        first = subprocess.Popen(["python3", "-I", SWARM_PY, task, "--run-id", "first"], env=swarm_env(),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: first.poll() is None and first.kill())
        deadline = time.time() + 20
        while env.haiku_events()[0] == 0 and time.time() < deadline:
            time.sleep(0.02)  # the first run is inside its planner call, holding the lock
        self.assertGreater(env.haiku_events()[0], 0, "first run never started")
        rc, out, err = run_swarm(task, "--run-id", "second")
        self.assertEqual(rc, 0, err)
        self.assertIn("skipped: locked", out)
        self.assertEqual(env.audit()[-1]["reason"], "locked")
        out1, err1 = first.communicate(timeout=60)
        self.assertEqual(first.returncode, 0, out1 + err1)


class KillSwitches(unittest.TestCase):
    def _assert_skipped(self, env, rc, out, err, reason):
        self.assertEqual(rc, 0, err)
        self.assertIn("skipped: " + reason, out)
        self.assertEqual(env.audit()[-1]["status"], "skipped")
        self.assertEqual(env.gateway.chat_calls, 0)
        self.assertEqual(env.gateway.haiku_calls, 0)
        self.assertEqual(env.haiku_events()[0], 0)

    def test_swarm_disabled_flag(self):
        env = open_env(self)
        open(os.path.join(env.state, "disabled"), "w").close()
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "k1")
        self._assert_skipped(env, rc, out, err, "swarm disabled flag")

    def test_claude_haiku_disabled_flag_stops_haiku_orchestrated_runs(self):
        env = open_env(self)
        open(os.path.join(env.haiku_state, "disabled"), "w").close()
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "k2")
        self._assert_skipped(env, rc, out, err, "claude-haiku disabled flag")

    def test_claude_haiku_disabled_flag_does_not_touch_chat_only_runs(self):
        env = open_env(self)
        open(os.path.join(env.haiku_state, "disabled"), "w").close()
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "k2b", SWARM_ORCHESTRATOR="chat")
        self.assertEqual(rc, 0, err)
        self.assertEqual(env.audit()[-1]["status"], "ok")
        self.assertEqual(env.gateway.haiku_calls, 0)

    def test_hermes_pause_estop(self):
        env = open_env(self)
        open(os.path.join(env.hermes_home, "ESTOP"), "w").close()
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "k3")
        self._assert_skipped(env, rc, out, err, "hermes paused")


class Refusals(unittest.TestCase):
    def _assert_refused_before_any_call(self, env, rc, err):
        self.assertEqual(rc, 2, err)
        self.assertIn("refused", err)
        self.assertEqual(env.gateway.chat_calls, 0)
        self.assertEqual(env.gateway.haiku_calls, 0)
        self.assertEqual(env.haiku_events()[0], 0)

    def test_repo_outside_allowlist_is_refused(self):
        env = open_env(self)
        rc, out, err = run_swarm(write_task(_tmpdir(self), repo="acme/other"), "--run-id", "r1")
        self._assert_refused_before_any_call(env, rc, err)

    def test_unset_allowlist_refuses_every_repo(self):
        env = open_env(self)
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "r2", SWARM_ALLOWED_REPOS=None)
        self._assert_refused_before_any_call(env, rc, err)

    def test_haiku_parallel_above_wrapper_limit_is_refused(self):
        env = open_env(self)
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "r3", SWARM_HAIKU_PARALLEL="4",
                                 CLAUDE_HAIKU_PARALLEL="2")
        self._assert_refused_before_any_call(env, rc, err)

    def test_bug_task_without_repo_is_refused(self):
        # check_repo only compares a repo that is present, so a task with no `repo` key skips the allowlist entirely.
        env = open_env(self)
        rc, out, err = run_swarm(write_task(_tmpdir(self), repo=None, source=None), "--run-id", "r4")
        self._assert_refused_before_any_call(env, rc, err)

    def test_bug_haiku_parallel_zero_does_not_hang(self):
        # BoundedSemaphore(0) blocks forever, and the wall-clock check only runs before a call, so the run never ends.
        env = open_env(self)
        try:
            rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "r5", SWARM_HAIKU_PARALLEL="0", timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("swarm hung with SWARM_HAIKU_PARALLEL=0 instead of refusing it")
        self._assert_refused_before_any_call(env, rc, err)


class Routing(unittest.TestCase):
    def test_plan_tier_field_is_ignored(self):
        env = open_env(self, reply=_tier_reply)
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "k")
        self.assertEqual(rc, 0, out + err)
        last = env.audit()[-1]
        for s in last["steps"]:
            if s["tag"] == "normal":
                self.assertEqual(s["tiers"], ["chat"], s)


class ModelFailures(unittest.TestCase):
    def test_invalid_plan_is_retried_once_then_fails(self):
        env = open_env(self, reply=lambda p: "I will not produce JSON")
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "m1")
        self.assertEqual(rc, 1, out + err)
        last = env.audit()[-1]
        self.assertEqual(last["status"], "failed")
        self.assertTrue(last["reason"].startswith("invalid plan"), last)
        self.assertEqual(env.gateway.haiku_calls, 2)  # first attempt and one retry

    def test_fake_wrapper_exit_five_ends_capped(self):
        env = open_env(self)
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "m2", FAKE_HAIKU_EXIT="5")
        self.assertEqual(rc, 3, out + err)
        last = env.audit()[-1]
        self.assertEqual(last["status"], "capped")
        self.assertIn("exit 5", last["reason"])

    def test_bug_planner_null_inputs_fails_cleanly(self):
        # "inputs": null used to raise TypeError out of validate_plan: a traceback, no retry, no audit entry.
        # The run may succeed (null read as no inputs) or fail, but it must not crash.
        def reply(prompt):
            if "planner" in prompt:
                plan = json.loads(default_reply(prompt))
                for s in plan["steps"]:
                    s["inputs"] = None
                return json.dumps(plan)
            return default_reply(prompt)
        env = open_env(self, reply=reply)
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "m3")
        self.assertNotIn("Traceback", err)
        self.assertIn(rc, (0, 1), err)
        self.assertTrue(env.audit(), "no audit entry was written")

    def test_bug_chat_response_without_choices_fails_cleanly(self):
        # A 200 response without `choices` (a gateway error body, say) raises KeyError out of the scheduler.
        env = open_env(self, reply=lambda p: {"error": {"message": "upstream gone"}})
        rc, out, err = run_swarm(write_task(_tmpdir(self)), "--run-id", "m4", SWARM_ORCHESTRATOR="chat")
        self.assertEqual(rc, 1, err)
        self.assertTrue(env.audit(), "no audit entry was written")
        self.assertEqual(env.audit()[-1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
