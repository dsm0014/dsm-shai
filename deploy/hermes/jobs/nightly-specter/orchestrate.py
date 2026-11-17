"""Nightly specter job: one run (spec 11). Called by run.sh after the lock, kill-switch and configuration checks.

Every model call is one `hermes -z` with an exact prompt from prompts/*.v1.txt and is followed by a non-LLM verifier.
A step gets two attempts; a second failure aborts the run and discards the branch. guard.py decides whether a diff
may merge. Only verifier and guard results count as success; the model's own claim of "done" does not.
"""
import argparse, base64, json, os, re, subprocess, sys, time, datetime, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lib, gh_api, select_mode, dedupe, inventory, specutil, guard  # noqa: E402

HERMES = os.environ.get("HERMES_BIN", "hermes")
STEP_TIMEOUT = int(os.environ.get("NIGHTLY_STEP_TIMEOUT", "600"))
PROBATION = int(os.environ.get("IMPL_PROBATION_NIGHTS", "1"))
MAX_REPOS = int(os.environ.get("NIGHTLY_MAX_REPOS", "5"))
MAX_SPECS = int(os.environ.get("NIGHTLY_MAX_SPECS", "3"))
QUERIES = [q for q in os.environ.get("NIGHTLY_QUERIES", "claude code skills;spec-driven development;ai coding agent specs").split(";") if q]
VERIFIERS = []


class StepFailed(Exception):
    pass


def prompt_text(name, **kw):
    t = open(os.path.join(HERE, "prompts", name + ".v1.txt")).read()
    for k, v in kw.items():
        t = t.replace("{{%s}}" % k, v)
    return t


def untrusted(text):
    return "<<<UNTRUSTED_CONTENT\n%s\nUNTRUSTED_CONTENT>>>" % text.replace("UNTRUSTED_CONTENT", "")


def hermes(prompt):
    r = subprocess.run([HERMES, "-z", prompt], capture_output=True, text=True, timeout=STEP_TIMEOUT)
    return r.stdout


def step(name, prompt, verify):
    for attempt in (1, 2):
        try:
            out = hermes(prompt)
            ok, why, val = verify(out)
        except Exception as e:  # malformed output, timeout, hermes error: all count as a failed attempt
            ok, why, val = False, "error: %s" % type(e).__name__, None
        VERIFIERS.append({"step": name, "attempt": attempt, "ok": ok, "why": why})
        if ok:
            return val
    raise StepFailed(name)


def json_in(text):
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a:b + 1])


def git(repo, *a, check=True):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True, check=check)


def git_env(token):
    e = {"GIT_AUTHOR_NAME": "nightly-specter", "GIT_AUTHOR_EMAIL": "nightly-specter@users.noreply.github.com",
         "GIT_COMMITTER_NAME": "nightly-specter", "GIT_COMMITTER_EMAIL": "nightly-specter@users.noreply.github.com",
         "GIT_TERMINAL_PROMPT": "0"}
    if token:  # header via env, not argv, so it is not in the process list or in .git/config
        basic = base64.b64encode(("x-access-token:" + token).encode()).decode()
        e.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader",
                  "GIT_CONFIG_VALUE_0": "Authorization: Basic " + basic})
    return e


def clone(url, dest, token):
    env = dict(os.environ, **git_env(token if url.startswith("https://") else ""))
    subprocess.run(["git", "clone", "--quiet", url, dest], check=True, env=env, capture_output=True)
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        os.environ[k] = env[k]
    return env


def titles_existing(repo, prs):
    out = [s["title"] for s in inventory.inventory(repo)["specs"]]
    return out + [p["title"] for p in prs]


def run_tests(repo):
    """The repo's own test command when it has one, then the structural check. No CI means local validation only."""
    cmd = inventory.test_command(repo)
    if cmd:
        r = subprocess.run(cmd, shell=True, cwd=repo, capture_output=True, text=True, timeout=900)
        VERIFIERS.append({"step": "tests", "ok": r.returncode == 0, "why": cmd})
        if r.returncode:
            raise StepFailed("tests")
    else:
        VERIFIERS.append({"step": "tests", "ok": True, "why": "no CI: local validation only"})
    r = subprocess.run(["sh", os.path.join(HERE, "validate.sh"), repo], capture_output=True, text=True)
    VERIFIERS.append({"step": "validate", "ok": r.returncode == 0, "why": (r.stdout + r.stderr).strip()[:200]})
    if r.returncode:
        raise StepFailed("validate")


def finish(repo, branch, base, mode, title, body, allowed, dry_run, may_merge, extra=None):
    """guard, then (unless dry-run) push, open the PR and merge when permitted."""
    reasons, info = guard.check(repo, base, branch, mode, branch, allowed)
    VERIFIERS.append({"step": "guard", "ok": not reasons, "why": ",".join(reasons) or "ok"})
    if reasons:
        raise StepFailed("guard:" + ",".join(reasons))
    result = {"pr_url": "", "merged": False, "lines": info["lines"], "files": info["files"]}
    if dry_run:
        result["reason"] = "dry run: nothing pushed"
        return result
    git(repo, "push", "--quiet", "origin", branch)
    pr = gh_api.create_pr(branch, title, body, base)
    result["pr_url"] = pr.get("html_url", "")
    if not may_merge:
        result["reason"] = (extra or "merge not permitted yet")
        return result
    try:
        gh_api.merge_pr(pr["number"])
        result["merged"] = True
    except gh_api.ApiError as e:
        result["reason"] = "merge blocked (branch protection or checks): %s" % e
    return result


def mode_a(repo, base, prs, dry_run):
    inv = inventory.inventory(repo)
    summary = "Skills: %s\nAgents: %s\nSpecs: %s\nTop files: %s" % (
        ", ".join(inv["skills"][:40]), ", ".join(inv["agents"][:40]), "; ".join(s["title"] for s in inv["specs"][:40]),
        ", ".join(f["path"] for f in inv["files"][:80]))
    summary = inventory.chunk(summary)[0]
    seen, cands = set(), []
    cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    for q in QUERIES:
        for c in gh_api.search_repos(q, MAX_REPOS):
            if c["full_name"] != gh_api.repo() and c["full_name"] not in seen and c["pushed_at"][:10] >= cutoff:
                seen.add(c["full_name"]); cands.append(c)
        if len(cands) >= MAX_REPOS:
            break
    cands = cands[:MAX_REPOS]
    if not cands:
        raise StepFailed("candidates:none")
    features = []
    for c in cands:
        text = (gh_api.readme(c["full_name"])[:6000] + "\n\nTop-level: " + ", ".join(gh_api.top_tree(c["full_name"])[:60]))
        def v_feat(out):
            j = json_in(out); ok = isinstance(j.get("features"), list) and len(j["features"]) > 0
            return ok, "features=%d" % len(j.get("features", [])) if ok else "no features", j["features"] if ok else None
        feats = step("summarise:" + c["full_name"], prompt_text("a-summarise", repo=c["full_name"], content=untrusted(text)), v_feat)
        features.append({"repo": c["full_name"], "url": c["url"], "license": c["license"], "features": [str(f)[:200] for f in feats[:8]]})
    def v_vec(out):
        j = json_in(out); vs = j.get("vectors")
        ok = isinstance(vs, list) and 1 <= len(vs) <= 10 and all(isinstance(v, dict) and v.get("title") for v in vs)
        return ok, "vectors=%d" % (len(vs) if isinstance(vs, list) else 0), vs if ok else None
    vectors = step("vectors", prompt_text("a-vectors", inventory=summary, features=untrusted(json.dumps(features)[:20000])), v_vec)
    existing = titles_existing(repo, prs + gh_api.prs("closed"))
    kept = dedupe.dedupe(vectors, existing)[:MAX_SPECS]
    if not kept:
        return {"status": "ok", "reason": "no new improvement vectors after dedupe", "pr_url": "", "merged": False, "n_specs": 0}
    branch = "nightly/specs-" + lib.today().replace("-", "")
    git(repo, "checkout", "-b", branch)
    specs_dir = os.path.join(repo, "specs")
    os.makedirs(specs_dir, exist_ok=True)
    index_path = os.path.join(specs_dir, "00-index.md")
    index = open(index_path).read() if os.path.exists(index_path) else "# Specs Index\n\n| # | Spec | Status | Open items |\n|---|------|--------|-----------|\n"
    for v in kept:
        n = specutil.next_number(specs_dir)
        def v_spec(out, n=n):
            t = specutil.ensure_origin(out.strip(), n)
            probs = guard.spec_problems(t)
            return (not probs), ("; ".join(probs) or "ok"), t
        body = step("spec:" + v["title"][:40], prompt_text("a-spec", number="%02d" % n, vector=json.dumps(v), inventory=summary), v_spec)
        srcs = [f for f in features if f["repo"] in json.dumps(v)] or features[:3]
        body += "\n\n## Comparison sources\n\n" + "\n".join("- %s (licence %s, fetched %s). Ideas only; no code or text copied." % (f["url"], f["license"], lib.today()) for f in srcs) + "\n"
        title = (re.search(r"^# Spec \d+\s*[—-]\s*(.+)$", body, re.M) or [None, v["title"]])[1].strip()
        fn = "%02d-%s.md" % (n, specutil.slugify(title))
        open(os.path.join(specs_dir, fn), "w").write(body)
        index = specutil.index_add(index, n, title, fn)
        open(index_path, "w").write(index)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "spec: add %d nightly improvement spec(s)" % len(kept))
    run_tests(repo)
    res = finish(repo, branch, base, "A", "spec: %d nightly improvement spec(s)" % len(kept),
                 "Authored by the nightly specter job (spec 11). Spec files and the index only.\n\nSources are listed in each spec.", [], dry_run, True)
    res.update(status="ok", n_specs=len(kept))
    return res


def mode_b(repo, base, spec_path, dry_run):
    text = open(spec_path).read()
    num = int(re.match(r"(\d+)-", os.path.basename(spec_path)).group(1))
    rel_spec = os.path.relpath(spec_path, repo)
    allowed = specutil.allowed_paths(text)
    branch = "nightly/impl-%02d-%s" % (num, lib.today().replace("-", ""))
    git(repo, "checkout", "-b", branch)
    index_path = os.path.join(repo, "specs", "00-index.md")
    if not allowed:  # nothing to implement safely: mark the spec BLOCKED, in a spec-only PR
        open(spec_path, "w").write(specutil.set_status(text, "BLOCKED", "no parseable Files list"))
        if os.path.exists(index_path):
            open(index_path, "w").write(specutil.index_set_status(open(index_path).read(), num, "BLOCKED"))
        git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "spec(%02d): mark BLOCKED, no Files list" % num)
        res = finish(repo, branch, base, "A", "spec(%02d): mark BLOCKED" % num, "The spec has no parseable Files list, so the nightly job did not implement it.", [], dry_run, True)
        res.update(status="ok", spec=rel_spec, blocked=True)
        return res
    files = [p for p in allowed if not p.endswith("/")][:12]
    unmet = []
    for p in files:
        cur = open(os.path.join(repo, p), errors="replace").read() if os.path.exists(os.path.join(repo, p)) else ""
        def v_file(out, p=p):
            m = re.search(r"=== FILE: (.+?) ===\n(.*?)\n=== END ===", out, re.S)
            ok = bool(m) and m.group(1).strip() == p and bool(m.group(2).strip())
            u = re.search(r"^UNMET:\s*(.+)$", out, re.M)
            return ok, "ok" if ok else "bad or wrong-path block", (m.group(2) if ok else None, (u.group(1).strip() if u else "none"))
        content, um = step("implement:" + p, prompt_text("b-implement", path=p, spec=untrusted(text[:20000]), current=untrusted(inventory.chunk(cur)[0] if cur else "(new file)")), v_file)
        if p not in files:  # the only writer; refuses any path not named in the spec
            raise StepFailed("write:path-not-allowed")
        os.makedirs(os.path.dirname(os.path.join(repo, p)) or repo, exist_ok=True)
        open(os.path.join(repo, p), "w").write(content + "\n")
        if um.lower() != "none":
            unmet.append(um)
    run_tests(repo)
    status = "PARTIAL" if unmet else "DONE"
    open(spec_path, "w").write(specutil.set_status(open(spec_path).read(), status, ("unmet: " + "; ".join(unmet))[:200] if unmet else ""))
    if os.path.exists(index_path):
        open(index_path, "w").write(specutil.index_set_status(open(index_path).read(), num, status))
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "feat(spec-%02d): implement (nightly specter job)" % num)
    clean = lib.clean_nights()
    may_merge = PROBATION == 0 or clean >= PROBATION
    res = finish(repo, branch, base, "B", "feat(spec-%02d): implement (nightly)" % num,
                 "Implemented by the nightly specter job (spec 11). Status set to %s. Review the diff; the job does not trust its own report." % status,
                 files + [rel_spec], dry_run, may_merge,
                 "probation: %d of %d clean nights; PR left open for review" % (clean, PROBATION))
    res.update(status="ok", spec=rel_spec, spec_status=status)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--work", default=os.environ.get("NIGHTLY_WORK", "/workspace/claude-specter"))
    a = ap.parse_args()
    t0 = time.time()
    run_id = "%s-%d" % (lib.today(), int(t0))
    entry = {"run_id": run_id, "dry_run": a.dry_run}
    os.makedirs(os.path.dirname(lib.state_file()), exist_ok=True)
    if not a.dry_run:
        open(lib.state_file(), "w").write(json.dumps({"run_id": run_id, "started": int(t0)}))
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        if os.path.exists(a.work):
            subprocess.run(["rm", "-rf", a.work], check=True)
        url = os.environ.get("NIGHTLY_CLONE_URL") or "https://github.com/%s.git" % gh_api.repo()
        clone(url, a.work, token)
        base = git(a.work, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if os.path.exists(os.path.join(a.work, ".nightly-disabled")):
            entry.update(status="skipped", reason="skipped: .nightly-disabled on the default branch", verifiers=[])
            lib.digest("skipped, .nightly-disabled present")
            lib.audit(entry); lib.write_metrics()
            return 0
        prs = gh_api.prs("open")
        pr_file = os.path.join(lib.STATE, "open-prs.json"); open(pr_file, "w").write(json.dumps(prs))
        mode, extra = select_mode.select(os.path.join(a.work, "specs"), prs)
        entry["mode"] = mode
        if mode == "HOLD":
            entry.update(status="held", reason=extra)
            lib.digest("HOLD, %s" % extra)
        else:
            res = mode_a(a.work, base, prs, a.dry_run) if mode == "A" else mode_b(a.work, base, extra, a.dry_run)
            entry.update(res)
            lib.digest("%s mode %s: %s %s" % ("dry-run" if a.dry_run else "ok", mode, res.get("pr_url") or "no PR", ("(" + res["reason"] + ")") if res.get("reason") else ""))
    except StepFailed as e:
        entry.update(status="failed", reason=str(e))
        lib.digest("FAILED at %s" % e)
        # nothing was pushed before the guard passed; drop the local branch so a retry starts clean
        git(a.work, "checkout", "-q", "--detach", check=False)
        for b in git(a.work, "branch", "--list", "nightly/*", "--format=%(refname:short)", check=False).stdout.split():
            git(a.work, "branch", "-D", b, check=False)
    except Exception as e:  # network, clone or API failure: fail closed and alert
        entry.update(status="failed", reason="%s: %s" % (type(e).__name__, lib.redact(str(e))[:200]))
        lib.digest("FAILED: %s" % entry["reason"])
    entry.update(verifiers=VERIFIERS, duration=int(time.time() - t0))
    lib.audit(entry)
    lib.write_metrics()
    return 0 if entry["status"] in ("ok", "held") else 1


if __name__ == "__main__":
    sys.exit(main())
