#!/usr/bin/env python3
# Checks that each specs/NN-name.md has a **Status:** line and a row in specs/00-index.md, that the two agree on the status, and that a DONE spec has no unchecked box.
# Findings are warnings (some specs are known to disagree today): printed as "WARN path: message", exit 0. STRICT=1 makes any warning exit 1.
import os
import re
import subprocess
import sys

INDEX = "specs/00-index.md"
SPEC_RE = re.compile(r"^specs/(\d\d)-[^/]+\.md$")
GROUP = {"DONE": "DONE", "PARTIAL": "ACTIVE", "IN": "ACTIVE", "TODO": "TODO"}  # PARTIAL and IN PROGRESS are one group


def read(path):
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def first_word(text):
    m = re.match(r"\W*([A-Za-z]+)", text.strip())
    return m.group(1).upper() if m else ""


def index_rows(text):
    """NN -> status cell of the table row for that spec."""
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 5 and re.fullmatch(r"\d\d", cells[1]):
            rows[cells[1]] = cells[3]
    return rows


def main():
    tracked = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, check=True).stdout.split("\0")
    specs = sorted(p for p in tracked if SPEC_RE.match(p) and not p.startswith("specs/00-"))
    warnings = []
    rows = index_rows(read(INDEX)) if os.path.exists(INDEX) else {}
    if not rows:
        warnings.append("WARN %s: no table rows found" % INDEX)

    for path in specs:
        nn = SPEC_RE.match(path).group(1)  # the two digits from the file name, not from a split of the path
        text = read(path)
        status = None
        for line in text.splitlines():
            if line.startswith("**Status:**"):
                status = line[len("**Status:**"):].strip()
                break
        if status is None:
            warnings.append("WARN %s: no line starting with **Status:**" % path)
        if nn not in rows:
            warnings.append("WARN %s: no row for %s in %s" % (path, nn, INDEX))
        if status is not None and nn in rows:
            spec_word, index_word = first_word(status), first_word(rows[nn])
            if GROUP.get(spec_word, spec_word) != GROUP.get(index_word, index_word):
                warnings.append("WARN %s: status is %s in the spec and %s in %s" % (path, spec_word or "empty", index_word or "empty", INDEX))
        if status is not None and first_word(status) == "DONE":
            open_boxes = [n for n, line in enumerate(text.splitlines(), 1) if line.startswith("- [ ]")]
            if open_boxes:
                warnings.append("WARN %s: status is DONE but %d acceptance box(es) are unchecked, first at line %d" % (path, len(open_boxes), open_boxes[0]))

    if warnings:
        print("\n".join(warnings))
        return 1 if os.environ.get("STRICT") == "1" else 0
    print("OK spec-consistency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
