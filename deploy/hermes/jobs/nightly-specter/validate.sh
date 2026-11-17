#!/bin/sh
# Structural validation of a spec repo (spec 11): every specs/NN-*.md has a title, Status, Purpose, Behavior and
# Acceptance Criteria with checkboxes. Used when the target repo has no CI. Usage: validate.sh REPO_DIR
set -eu
REPO="${1:-.}"
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 -I - "$REPO" "$HERE" <<'PY'
import glob, os, sys
repo, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, here)
import guard
bad = []
for p in sorted(glob.glob(os.path.join(repo, "specs", "[0-9][0-9]-*.md"))):
    if p.endswith("00-index.md"):
        continue
    probs = guard.spec_problems(open(p, errors="replace").read())
    if probs:
        bad.append("%s: %s" % (os.path.relpath(p, repo), "; ".join(probs)))
if bad:
    print("\n".join(bad)); sys.exit(1)
print("validate ok")
PY
