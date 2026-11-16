"""Logging pass-through proxy for one Hermes request. Run inside the Hermes pod; writes /tmp/cap/N.req.json and N.resp.txt.

  kubectl -n hermes exec -i deploy/hermes -c hermes -- sh -c 'cat > /tmp/cap.py' < scripts/hermes-capture-proxy.py
  kubectl -n hermes exec deploy/hermes -c hermes -- sh -c 'mkdir -p /tmp/hh && cp /opt/data/config.yaml /tmp/hh/ &&
    sed -i "s#http://litellm.litellm.svc:4000/v1#http://127.0.0.1:9999/v1#" /tmp/hh/config.yaml &&
    (nohup /opt/hermes/.venv/bin/python3 /tmp/cap.py >/tmp/cap.log 2>&1 &) && sleep 2 &&
    HERMES_HOME=/tmp/hh hermes -z "your prompt"'

Temporary: the files live in /tmp of the pod and vanish with it. Request bodies contain prompts, so do not commit them.
"""
import http.server, http.client, json, os, sys, threading
UP = ("litellm.litellm.svc", 4000)
OUT = "/tmp/cap"
os.makedirs(OUT, exist_ok=True)
n = [0]
lock = threading.Lock()

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with lock:
            n[0] += 1
            i = n[0]
        open(f"{OUT}/{i}.req.json", "wb").write(body)
        c = http.client.HTTPConnection(*UP, timeout=400)
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")}
        c.request("POST", self.path, body, hdrs)
        r = c.getresponse()
        data = r.read()
        open(f"{OUT}/{i}.resp.txt", "wb").write(data)
        self.send_response(r.status)
        self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        c = http.client.HTTPConnection(*UP, timeout=60)
        hdrs = {k: v for k, v in self.headers.items() if k.lower() != "host"}
        c.request("GET", self.path, headers=hdrs)
        r = c.getresponse(); data = r.read()
        self.send_response(r.status)
        self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

http.server.ThreadingHTTPServer(("127.0.0.1", 9999), H).serve_forever()
