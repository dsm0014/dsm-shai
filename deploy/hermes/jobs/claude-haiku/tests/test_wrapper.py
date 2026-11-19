"""Offline tests for claude-haiku.sh (spec 12). A fake CLI stands in for `claude`; no network, no cluster."""
import json, os, stat, subprocess, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(HERE, "..", "claude-haiku.sh")


def slurp(path):
    with open(path) as f:
        return f.read()


class Wrapper(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.state = os.path.join(self.d, "state")
        self.fake = os.path.join(self.d, "claude")
        self.log = os.path.join(self.d, "calls.log")
        self.write_fake("cat; echo ' [fake]'")

    def write_fake(self, body):
        with open(self.fake, "w") as f:
            f.write(f"#!/bin/sh\necho \"$ANTHROPIC_API_KEY|$*\" >> {self.log}\n{body}\n")
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)

    def env(self, **kw):
        e = {"PATH": os.environ["PATH"], "CLAUDE_BIN": self.fake, "CLAUDE_HAIKU_STATE": self.state,
             "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-test-token"}
        e.update(kw)
        return e

    def run_w(self, stdin="hello", args=(), **kw):
        return subprocess.run(["bash", WRAPPER, *args], input=stdin, capture_output=True, text=True, env=self.env(**kw), timeout=30)

    def audit(self):
        p = os.path.join(self.state, "audit.jsonl")
        return [json.loads(l) for l in slurp(p).splitlines()] if os.path.exists(p) else []

    def test_ok_returns_answer_and_audits_without_content(self):
        r = self.run_w("secret prompt text")
        self.assertEqual(r.returncode, 0)
        self.assertIn("[fake]", r.stdout)
        a = self.audit()
        self.assertEqual(a[-1]["status"], "ok")
        raw = slurp(os.path.join(self.state, "audit.jsonl"))
        self.assertNotIn("secret prompt text", raw)
        self.assertNotIn("sk-ant", raw)

    def test_cli_gets_no_tools_and_pinned_model(self):
        self.run_w()
        line = slurp(self.log)
        self.assertIn("--tools", line)
        self.assertIn("--model haiku", line)

    def test_api_key_is_unset_before_the_call(self):
        r = self.run_w(ANTHROPIC_API_KEY="sk-ant-api-must-not-leak", ANTHROPIC_AUTH_TOKEN="x")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(slurp(self.log).startswith("|"), "ANTHROPIC_API_KEY reached the CLI")

    def test_preflight_ok_and_fails_with_api_key_or_missing_token(self):
        self.assertEqual(self.run_w(args=["--preflight"]).returncode, 0)
        r = self.run_w(args=["--preflight"], ANTHROPIC_API_KEY="sk-ant-api-x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ANTHROPIC_API_KEY is set", r.stdout)
        e = self.env(); e.pop("CLAUDE_CODE_OAUTH_TOKEN")
        r = subprocess.run(["bash", WRAPPER, "--preflight"], capture_output=True, text=True, env=e)
        self.assertNotEqual(r.returncode, 0)

    def test_no_token_fails_closed(self):
        e = self.env(); e.pop("CLAUDE_CODE_OAUTH_TOKEN")
        r = subprocess.run(["bash", WRAPPER], input="x", capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 3)
        self.assertFalse(os.path.exists(self.log), "CLI must not run without a token")

    def test_disabled_flag(self):
        os.makedirs(self.state)
        open(os.path.join(self.state, "disabled"), "w").close()
        r = self.run_w()
        self.assertEqual(r.returncode, 4)
        self.assertFalse(os.path.exists(self.log))

    def test_daily_cap(self):
        self.assertEqual(self.run_w(CLAUDE_HAIKU_DAILY_CALLS="2").returncode, 0)
        self.assertEqual(self.run_w(CLAUDE_HAIKU_DAILY_CALLS="2").returncode, 0)
        r = self.run_w(CLAUDE_HAIKU_DAILY_CALLS="2")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(slurp(self.log).count("\n"), 2)
        self.assertEqual(self.audit()[-1]["status"], "capped")

    def test_parallel_cap_two_run_third_waits(self):
        marks = os.path.join(self.d, "marks")
        # each call records start/end with a timestamp and holds its slot for 2 s
        self.write_fake(f"echo \"start $(date +%s%N)\" >> {marks}; sleep 2; echo \"end $(date +%s%N)\" >> {marks}; cat")
        results = []
        def go():
            results.append(self.run_w(CLAUDE_HAIKU_PARALLEL="2", CLAUDE_HAIKU_TIMEOUT="30"))
        ts = [threading.Thread(target=go) for _ in range(3)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        ev = sorted((int(l.split()[1]), l.split()[0]) for l in slurp(marks).splitlines())
        inflight = peak = 0
        for _, kind in ev:
            inflight += 1 if kind == "start" else -1
            peak = max(peak, inflight)
        self.assertEqual(peak, 2, "never more than 2 in flight, and 2 did run together")

    def test_timeout_is_reported_as_error(self):
        self.write_fake("sleep 5")
        r = self.run_w(CLAUDE_HAIKU_TIMEOUT="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(self.audit()[-1]["status"].startswith("error"))


    def test_research_mode_limits_tools_and_uses_open_web_proxy(self):
        self.write_fake('echo "$HTTPS_PROXY|$PWD" >> %s.env; cat' % self.log)
        r = self.run_w(CLAUDE_HAIKU_WEB="1", HTTPS_PROXY="http://restricted:3128")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = slurp(self.log)
        self.assertIn('--tools WebSearch,WebFetch', argv)
        self.assertIn('--permission-mode dontAsk', argv)
        for t in ("Bash", "Edit", "Write", "Agent", "mcp__*"):
            self.assertIn(t, argv.split("--disallowedTools")[1])
        proxy, cwd = slurp(self.log + ".env").strip().split("|")
        self.assertEqual(proxy, "http://squid.egress-proxy.svc:3129")   # not the pod-wide 3128 listener
        self.assertNotEqual(cwd, os.getcwd())                             # empty scratch dir, no project settings

    def test_default_mode_keeps_no_tools_and_pod_proxy(self):
        self.write_fake('echo "$HTTPS_PROXY" >> %s.env; cat' % self.log)
        r = self.run_w(HTTPS_PROXY="http://restricted:3128")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--tools  ', slurp(self.log).replace('--tools ', '--tools  ', 1))
        self.assertNotIn("WebFetch", slurp(self.log))
        self.assertEqual(slurp(self.log + ".env").strip(), "http://restricted:3128")


if __name__ == "__main__":
    unittest.main()
