"""Worker calls (spec 13). `chat` goes to LiteLLM with the hermes key; Haiku goes only through the spec 12 wrapper.
Content is untrusted: it is wrapped in delimiters and the marker is stripped from it."""
import json, os, subprocess, time, urllib.request, urllib.error

LITELLM = os.environ.get("SWARM_LITELLM_URL", "http://litellm.litellm.svc:4000/v1")
HAIKU_BIN = os.environ.get("SWARM_HAIKU_BIN", "/opt/jobs/claude-haiku/claude-haiku.sh")
MARK_OPEN, MARK_CLOSE = "<<<UNTRUSTED_CONTENT", "UNTRUSTED_CONTENT>>>"


class WorkerError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code  # wrapper exit code or HTTP status


class HaikuUnavailable(WorkerError):
    """Disabled flag (4), daily cap (5) or not configured (3): not retryable, the task falls to `capped`."""


def untrusted(label, text):
    while MARK_OPEN in text or MARK_CLOSE in text:  # repeat: removing one marker can splice a new one together
        text = text.replace(MARK_OPEN, "").replace(MARK_CLOSE, "")
    label = " ".join(str(label).split())  # one line, so a name cannot break the delimiter structure
    return "%s %s\n%s\n%s" % (MARK_OPEN, label, text, MARK_CLOSE)


def call_chat(prompt, timeout=180, json_mode=False):
    """Return (text, usage_dict). Never retried here; the scheduler owns retries."""
    key = os.environ.get("LITELLM_HERMES_KEY", "")
    max_tokens = int(os.environ.get("SWARM_CHAT_MAX_TOKENS", "8000"))  # thinking is on: a small cap can leave the reply empty
    payload = {"model": "chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}  # the planner must return one JSON object
    body = json.dumps(payload).encode()
    req = urllib.request.Request(LITELLM + "/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        raise WorkerError("chat HTTP %d" % e.code, e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise WorkerError("chat unreachable: %s" % type(e).__name__)
    try:
        return (r["choices"][0]["message"].get("content") or "", r.get("usage") or {})
    except (KeyError, IndexError, TypeError, AttributeError):
        raise WorkerError("chat reply has no choices")


def call_haiku(prompt, timeout=150):
    try:
        p = subprocess.run(["bash", HAIKU_BIN], input=prompt, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise WorkerError("haiku timeout")
    except OSError as e:
        raise HaikuUnavailable("haiku wrapper missing: %s" % e, 3)
    if p.returncode in (3, 4, 5):
        raise HaikuUnavailable("haiku wrapper exit %d: %s" % (p.returncode, p.stderr.strip()[:100]), p.returncode)
    if p.returncode != 0:
        raise WorkerError("haiku wrapper exit %d" % p.returncode, p.returncode)
    return (p.stdout, {})
