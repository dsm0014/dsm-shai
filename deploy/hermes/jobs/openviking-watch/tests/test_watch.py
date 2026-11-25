"""Offline tests for watch.py: parks are counted once, log rotation resets the offset, and output is silent when healthy."""
import http.server
import importlib
import io
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def load_watch(log, state, health):
    os.environ["OV_WATCH_LOG"] = str(log)
    os.environ["OV_WATCH_STATE"] = str(state)
    os.environ["OV_WATCH_HEALTH"] = health
    import sys
    sys.path.insert(0, str(HERE))
    try:
        if "watch" in sys.modules:
            del sys.modules["watch"]
        return importlib.import_module("watch")
    finally:
        sys.path.pop(0)


class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = Path(self.dir, "gateway.log")
        self.state = Path(self.dir, "state.json")
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Health)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.healthy = f"http://127.0.0.1:{self.server.server_port}/health"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def run_watch(self, health):
        watch = load_watch(self.log, self.state, health)
        out = io.StringIO()
        with redirect_stdout(out):
            watch.main()
        return out.getvalue()

    def test_silent_when_healthy_and_no_parks(self):
        self.log.write_text("2026-11-25 INFO all good\n")
        self.assertEqual(self.run_watch(self.healthy), "")

    def test_counts_parks_once(self):
        self.log.write_text("WARNING tools.mcp_tool: MCP server 'openviking' failed initial connection after 3 attempts\n")
        first = self.run_watch(self.healthy)
        self.assertIn("1 MCP park(s)", first)
        # the same log content is not counted again on the next run
        self.assertEqual(self.run_watch(self.healthy), "")
        with self.log.open("a") as fh:
            fh.write("WARNING tools.mcp_tool: MCP server 'openviking' failed initial connection after 3 attempts\n")
        self.assertIn("1 MCP park(s)", self.run_watch(self.healthy))

    def test_log_rotation_restarts_the_offset(self):
        self.log.write_text("x" * 500 + "\n")
        self.run_watch(self.healthy)
        self.log.write_text("WARNING MCP server 'openviking' parked\n")
        self.assertIn("1 MCP park(s)", self.run_watch(self.healthy))

    def test_reports_unreachable_health(self):
        self.log.write_text("")
        out = self.run_watch("http://127.0.0.1:9/health")
        self.assertIn("OpenViking health check failed", out)


if __name__ == "__main__":
    unittest.main()
