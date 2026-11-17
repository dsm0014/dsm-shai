"""Merge guard (spec 11). The model never decides whether a diff is allowed; this script does.

  python3 guard.py --repo DIR --base REF --head REF --mode A|B --branch NAME [--allowed-paths FILE]

Exit 0 when the diff passes. Otherwise exit 1 and print one named reason per line:
  BRANCH_PREFIX, TOO_MANY_LINES, TOO_MANY_FILES, PATH_NOT_ALLOWED, FORBIDDEN_PATH, SECRET_IN_DIFF, SPEC_INVALID
"""
import argparse, fnmatch, os, re, subprocess, sys

MAX_LINES = int(os.environ.get("NIGHTLY_MAX_LINES", "400"))
MAX_FILES = int(os.environ.get("NIGHTLY_MAX_FILES", "12"))
MAX_SPEC_FILES_A = int(os.environ.get("NIGHTLY_MAX_SPECS", "3")) + 1  # specs plus the index
FORBIDDEN = [".github/*", "*.sops.yaml", "*.sops.yml", ".env", ".env.*", "*/.env", "*/.env.*",
             "deploy/hermes/jobs/nightly-specter/*", ".nightly-disabled"]
SECRETS = [re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"github[_]pat[_][A-Za-z0-9_]{20,}"),
           re.compile(r"sk-[0-9a-f]{20,}"), re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]{20,}"),
           re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]
SECTIONS = ["## Purpose", "## Behavior", "## Acceptance Criteria"]


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, check=True).stdout


def spec_problems(text):
    probs = []
    for s in SECTIONS:
        if s not in text:
            probs.append("missing " + s)
    if not re.search(r"^# Spec \d+", text, re.M):
        probs.append("missing title")
    if not re.search(r"^\*\*Status:\*\*", text, re.M):
        probs.append("missing status")
    if not re.search(r"^- \[[ x]\] ", text, re.M):
        probs.append("no acceptance checkboxes")
    return probs


def allowed(path, mode, allowed_paths):
    if mode == "A":
        return bool(re.fullmatch(r"specs/[^/]+\.md", path))
    return path in allowed_paths or bool(re.fullmatch(r"specs/00-index\.md", path)) or any(
        path == a or path.startswith(a.rstrip("/") + "/") for a in allowed_paths if a.endswith("/"))


def check(repo, base, head, mode, branch, allowed_paths):
    reasons = []
    if not branch.startswith("nightly/"):
        reasons.append("BRANCH_PREFIX")
    numstat = git(repo, "diff", "--numstat", base + "..." + head).splitlines()
    files, lines = [], 0
    for row in numstat:
        add, dele, path = row.split("\t", 2)
        files.append(path)
        lines += (0 if add == "-" else int(add)) + (0 if dele == "-" else int(dele))
    if lines > MAX_LINES:
        reasons.append("TOO_MANY_LINES")
    if len(files) > (MAX_SPEC_FILES_A if mode == "A" else MAX_FILES):
        reasons.append("TOO_MANY_FILES")
    for p in files:
        if any(fnmatch.fnmatch(p, f) for f in FORBIDDEN):
            reasons.append("FORBIDDEN_PATH")
        elif not allowed(p, mode, allowed_paths):
            reasons.append("PATH_NOT_ALLOWED")
    patch = git(repo, "diff", "--unified=0", base + "..." + head)
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++") and any(r.search(line) for r in SECRETS):
            reasons.append("SECRET_IN_DIFF")
            break
    if mode == "A":
        for p in files:
            if re.fullmatch(r"specs/\d\d-[^/]+\.md", p) and p != "specs/00-index.md":
                text = git(repo, "show", head + ":" + p)
                if spec_problems(text):
                    reasons.append("SPEC_INVALID")
                    break
    return sorted(set(reasons)), {"lines": lines, "files": files}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--mode", choices=["A", "B"], required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--allowed-paths")
    a = ap.parse_args()
    ap_list = [l.strip() for l in open(a.allowed_paths)] if a.allowed_paths else []
    reasons, info = check(a.repo, a.base, a.head, a.mode, a.branch, [p for p in ap_list if p])
    if reasons:
        print("\n".join(reasons), file=sys.stderr)
        sys.exit(1)
    print("guard ok: %d lines, %d files" % (info["lines"], len(info["files"])))
