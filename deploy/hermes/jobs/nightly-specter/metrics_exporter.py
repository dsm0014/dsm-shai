"""Serve metrics.prom read-only on port 9101 (spec 11). Standard library; the file is written by lib.write_metrics."""
import http.server, os

STATE = os.environ.get("NIGHTLY_STATE", "/opt/data/nightly-specter")
PORT = int(os.environ.get("NIGHTLY_METRICS_PORT", "9101"))


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404); self.end_headers(); return
        try:
            body = open(os.path.join(STATE, "metrics.prom"), "rb").read()
        except OSError:
            body = b"# no metrics yet\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
