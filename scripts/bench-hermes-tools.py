"""Replay a captured Hermes request (its real system prompt and tool list) against an Ollama model and score it.

Why: the model gets the same ~14k-token agent prompt Hermes sends, and each case checks one behaviour that agent
work depends on: answer in prose when no tool is needed, call a real tool with valid arguments when one is, and
continue a multi-step task instead of declaring it done. Results (2026-11-16) are in deploy/hermes/README.md.

Setup (nothing in the cluster changes):
  1. Capture a request: run scripts/hermes-capture-proxy.py in the Hermes pod, point a throwaway HERMES_HOME
     config at it, run one `hermes -z "..."` and copy /tmp/cap/N.req.json out (see deploy/hermes/README.md).
  2. kubectl -n ollama port-forward svc/ollama 11434:11434
  3. python3 -I scripts/bench-hermes-tools.py MODEL LABEL --base N.req.json [--n 5] [--effort none]
"""
import json, sys, re, time, urllib.request, argparse, collections

ap = argparse.ArgumentParser()
ap.add_argument("model"); ap.add_argument("label")
ap.add_argument("--n", type=int, default=5)
ap.add_argument("--temp", type=float, default=None)
ap.add_argument("--url", default="http://127.0.0.1:11434/v1/chat/completions")
ap.add_argument("--effort", default=None)
ap.add_argument("--ntools", type=int, default=0, help="keep only the K most relevant tools (0=all 29)")
ap.add_argument("--base", required=True, help="captured Hermes request (a chat/completions body with messages and tools)")
ap.add_argument("--maxtok", type=int, default=1500)
a = ap.parse_args()

base = json.load(open(a.base))
SYS = base["messages"][0]["content"]
TOOLS = base["tools"]
if a.ntools:
    keep = ["terminal", "read_file", "write_file", "search_files", "mcp__openviking__remember", "mcp__openviking__find",
            "patch", "todo_list", "web_search", "text_to_speech"][:a.ntools]
    TOOLS = [t for t in TOOLS if t["function"]["name"] in keep]
NAMES = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}

def call(messages):
    body = {"model": a.model, "messages": messages, "tools": TOOLS, "stream": False, "max_tokens": a.maxtok}
    if a.temp is not None: body["temperature"] = a.temp
    if a.effort: body["reasoning_effort"] = a.effort
    req = urllib.request.Request(a.url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=600))
    except Exception as e:
        return {"error": repr(e)[:200]}, time.time() - t
    return r, time.time() - t

def U(text): return [{"role": "system", "content": SYS}, {"role": "user", "content": text}]

def valid_call(tc, want=None):
    """returns (ok, why)"""
    fn = tc["function"]; name = fn["name"]
    if name not in NAMES: return False, "invented_tool:" + name
    try:
        args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
        assert isinstance(args, dict)
    except Exception: return False, "bad_json_args"
    miss = [k for k in NAMES[name].get("required", []) if k not in args]
    if miss: return False, "missing_args:" + ",".join(miss)
    if want and name not in want: return False, "wrong_tool:" + name
    return True, "ok"

# (id, kind, messages, accepted tool names)
def history_write_then():
    m = U("Create the file /workspace/a.txt containing the text hello, then read it back to verify.")
    m.append({"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": "/workspace/a.txt", "content": "hello"})}}]})
    m.append({"role": "tool", "tool_call_id": "c1", "content": json.dumps({"ok": True, "bytes_written": 5})})
    return m

CASES = [
    ("plain-math",  "plain", U("What is 2 plus 2? Answer in plain text."), None),
    ("plain-pong",  "plain", U("Reply with the single word PONG."), None),
    ("plain-k8s",   "plain", U("In one sentence, what is a Kubernetes pod?"), None),
    ("tool-ls",     "tool",  U("List the files in /workspace."), {"terminal", "search_files"}),
    ("tool-read",   "tool",  U("Read the file /workspace/notes.txt and tell me what it says."), {"read_file", "terminal"}),
    ("tool-write",  "tool",  U("Write the text hello to /workspace/hello.txt."), {"write_file", "terminal"}),
    ("tool-memory", "tool",  U("Remember that my favorite color is teal."), {"mcp__openviking__remember"}),
    ("step2-read",  "tool",  history_write_then(), {"read_file", "terminal"}),
]

JSONISH = re.compile(r'^\s*[\[{]\s*"?(name|tool|function)', re.I)
tot = collections.Counter(); per = {}
t0 = time.time(); lat = []
for cid, kind, msgs, want in CASES:
    res = collections.Counter()
    for i in range(a.n):
        r, dt = call(msgs); lat.append(dt)
        if "error" in r: res["http_error"] += 1; continue
        ch = r["choices"][0]["message"]; tcs = ch.get("tool_calls") or []; content = (ch.get("content") or "").strip()
        if kind == "plain":
            if tcs: res["FAIL_called_tool"] += 1
            elif JSONISH.match(content): res["FAIL_toolcall_as_text"] += 1
            elif not content: res["FAIL_empty"] += 1
            else: res["pass"] += 1
        else:
            if tcs:
                ok, why = valid_call(tcs[0], want)
                res["pass" if ok else "FAIL_" + why.split(":")[0]] += 1
            elif JSONISH.match(content): res["FAIL_toolcall_as_text"] += 1
            else: res["FAIL_no_call_prose"] += 1
    per[cid] = res; tot["pass"] += res["pass"]; tot["n"] += a.n
print(f"== {a.label}  model={a.model} temp={a.temp} effort={a.effort} tools={len(TOOLS)} n={a.n}")
for cid, res in per.items(): print(f"  {cid:12s} pass {res['pass']}/{a.n}  " + " ".join(f"{k}={v}" for k, v in res.items() if k != "pass"))
print(f"  TOTAL {tot['pass']}/{tot['n']}  avg_latency {sum(lat)/len(lat):.1f}s  wall {time.time()-t0:.0f}s")
