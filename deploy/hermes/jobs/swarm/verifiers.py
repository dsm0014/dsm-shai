"""Non-LLM verifiers (spec 13). Only a verifier result counts as step success. Each takes (text, ctx) and returns (ok, why).
A step's `verify` list in the plan may only name verifiers from this table; the task file sets the defaults and the minimum."""
import json, re

SECRET_RES = [re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"github[_]pat[_][A-Za-z0-9_]{20,}"), re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")]


def v_nonempty(text, ctx):
    return (len(text.strip()) > 0, "empty output")


def v_min_chars(text, ctx):
    n = int(ctx.get("min_chars", 40))
    return (len(text.strip()) >= n, "shorter than %d chars" % n)


def v_max_chars(text, ctx):
    n = int(ctx.get("max_chars", 8000))
    return (len(text) <= n, "longer than %d chars" % n)


def v_json(text, ctx):
    try:
        json.loads(text[text.index("{"):text.rindex("}") + 1])
        return (True, "")
    except ValueError:
        return (False, "no parseable JSON object")


def v_no_secrets(text, ctx):
    return (not any(r.search(text) for r in SECRET_RES), "looks like it contains a credential")


def v_cites_inputs(text, ctx):
    """A summary must mention each input it was given (by path or id), which catches off-topic output."""
    missing = [i for i in ctx.get("input_ids", []) if i not in text]
    return (not missing, "does not mention input %s" % ",".join(missing[:3]))


def v_diff_allowed(text, ctx):
    """A unified diff may only touch allowed_paths and stay under max_diff_lines changed lines."""
    allowed = [p.rstrip("/") for p in ctx.get("allowed_paths", [])]
    files = re.findall(r"^\+\+\+ b/(\S+)", text, re.M) + re.findall(r"^--- a/(\S+)", text, re.M)
    if not files or re.search(r"^(\+\+\+|---) /dev/null", text, re.M) and not re.search(r"^(\+\+\+ b/|--- a/)", text, re.M):
        return (False, "no diff headers")
    for f in files:
        if ".." in f.split("/") or not any(f == a or f.startswith(a + "/") for a in allowed):
            return (False, "path outside allowed_paths: %s" % f)
    changed = sum(1 for l in text.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")))
    return (changed <= int(ctx.get("max_diff_lines", 200)), "diff over the line cap")


TABLE = {"nonempty": v_nonempty, "min_chars": v_min_chars, "max_chars": v_max_chars, "json": v_json,
         "no_secrets": v_no_secrets, "cites_inputs": v_cites_inputs, "diff_allowed": v_diff_allowed}
DEFAULT = ["nonempty", "no_secrets"]


def run(names, text, ctx):
    """Return (ok, why). Unknown verifier names fail closed."""
    for n in list(dict.fromkeys(DEFAULT + list(names))):
        fn = TABLE.get(n)
        if fn is None:
            return (False, "unknown verifier %s" % n)
        ok, why = fn(text, ctx)
        if not ok:
            return (False, "%s: %s" % (n, why))
    return (True, "")
