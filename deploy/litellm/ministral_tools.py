"""LiteLLM response hook: structured tool calls for Ministral 3 (spec 02 amendment, 2026-11-20).

Ollama 0.40.16 does not parse Ministral 3's tool-call format, `name[ARGS]{json}` (the model's `[TOOL_CALLS]` marker is stripped), so a tool
call comes back as plain text in `message.content` and Hermes sees no `tool_calls`. This hook, loaded by LiteLLM as a callback, rewrites
a NON-STREAMING response whose whole content is one or more such calls (for tools named in the request) into real `tool_calls`.
Anything else is left untouched, and any error returns the response unchanged: the hook can never break a request.
Hermes must not stream (`streaming: false` in deploy/hermes/config.yaml) because LiteLLM's success hook does not run on streamed replies.
Delete this file and its config lines when Ollama parses the format natively (task list). Standard library only apart from LiteLLM itself."""
import json, re, uuid
from types import SimpleNamespace

try:  # LiteLLM is present in the proxy; the tests run without it
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # pragma: no cover
    CustomLogger = object

CALL_RE = re.compile(r"\s*(?:\[TOOL_CALLS\])?\s*([A-Za-z_][\w.-]*)\[ARGS\]")


def parse_calls(text, allowed):
    """Return [(name, arguments_json)] if the whole text is tool calls for names in `allowed`, else None."""
    if not text or "[ARGS]" not in text:
        return None
    dec, pos, end, calls = json.JSONDecoder(), 0, len(text.rstrip()), []
    while pos < end:
        m = CALL_RE.match(text, pos)
        if not m or m.group(1) not in allowed:
            return None
        try:
            obj, pos = dec.raw_decode(text, m.end())
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        calls.append((m.group(1), json.dumps(obj)))
        while pos < end and text[pos].isspace():
            pos += 1
    return calls or None


def _make_call(name, args):
    try:
        from litellm.types.utils import ChatCompletionMessageToolCall, Function
        return ChatCompletionMessageToolCall(id="call_" + uuid.uuid4().hex[:24], type="function", function=Function(name=name, arguments=args))
    except ImportError:  # tests without LiteLLM
        return SimpleNamespace(id="call_" + uuid.uuid4().hex[:24], type="function", function=SimpleNamespace(name=name, arguments=args))


class MinistralToolCalls(CustomLogger):
    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        try:
            names = {t["function"]["name"] for t in (data.get("tools") or []) if t.get("type") == "function"}
            if not names:
                return response
            for choice in getattr(response, "choices", None) or []:
                msg = getattr(choice, "message", None)
                if msg is None or getattr(msg, "tool_calls", None):
                    continue
                calls = parse_calls(getattr(msg, "content", None) or "", names)
                if calls:
                    msg.tool_calls = [_make_call(n, a) for n, a in calls]
                    msg.content = None
                    choice.finish_reason = "tool_calls"
        except Exception:  # never break a request
            return response
        return response


handler = MinistralToolCalls()
