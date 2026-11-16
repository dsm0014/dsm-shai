"""GPU and Ollama exporter (spec 06, nvidia-smi fallback; DCGM is not used on this WSL2 host).

Reads GPU state with nvidia-smi and loaded-model state from Ollama's /api/ps, and serves Prometheus text on :9400.
Stdlib only, so it runs in the LiteLLM image, which already has python3 and is pinned by digest.
"""
import http.server
import json
import os
import subprocess
import threading
import time
import urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama.ollama.svc:11434")
INTERVAL = float(os.environ.get("SCRAPE_INTERVAL", "15"))
GPU_FIELDS = "memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"

_lock = threading.Lock()
_text = "# exporter starting\n"


def gpu_lines():
    out = subprocess.run(
        ["nvidia-smi", f"--query-gpu={GPU_FIELDS}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        return ["gpu_up 0"]
    lines = ["gpu_up 1"]
    for i, row in enumerate(out.stdout.strip().splitlines()):
        used, total, util, temp, power = [x.strip() for x in row.split(",")]
        lab = f'gpu="{i}"'
        lines += [
            f"gpu_memory_used_mib{{{lab}}} {used}",
            f"gpu_memory_total_mib{{{lab}}} {total}",
            f"gpu_utilization_percent{{{lab}}} {util}",
            f"gpu_temperature_celsius{{{lab}}} {temp}",
            f"gpu_power_watts{{{lab}}} {power}",
        ]
    return lines


def ollama_lines():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=10) as r:
            data = json.load(r)
    except Exception:
        return ["ollama_up 0"]
    lines = ["ollama_up 1", f"ollama_loaded_models {len(data.get('models', []))}"]
    for m in data.get("models", []):
        model = m.get("name", "unknown").replace('"', "")
        lab = f'model="{model}"'
        lines += [
            f"ollama_model_vram_bytes{{{lab}}} {m.get('size_vram', 0)}",
            f"ollama_model_size_bytes{{{lab}}} {m.get('size', 0)}",
            f"ollama_model_context_length{{{lab}}} {m.get('context_length', 0)}",
        ]
    return lines


def collect_loop():
    global _text
    while True:
        lines = []
        for fn in (gpu_lines, ollama_lines):
            try:
                lines += fn()
            except Exception as exc:  # keep serving even if one source fails
                lines.append(f'exporter_error{{source="{fn.__name__}"}} 1')
        with _lock:
            _text = "\n".join(lines) + "\n"
        time.sleep(INTERVAL)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/metrics", "/metrics/"):
            self.send_response(404)
            self.end_headers()
            return
        with _lock:
            body = _text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=collect_loop, daemon=True).start()
    http.server.ThreadingHTTPServer(("0.0.0.0", 9400), Handler).serve_forever()
