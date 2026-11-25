#!/usr/bin/env python3
# CI check: every relative markdown link ](target) in every tracked .md file must point to an existing file.
import os
import re
import subprocess
import sys

LINK_RE = re.compile(r"\]\(([^)\s][^)]*)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def tracked_markdown_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    paths = [os.fsdecode(p) for p in out.split(b"\0") if p]
    return [p for p in paths if p.endswith(".md")]


def check_file(md_path):
    problems = []
    base = os.path.dirname(md_path)
    with open(md_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    for match in LINK_RE.finditer(text):
        raw = match.group(1).strip()
        if not raw or raw.startswith(SKIP_PREFIXES):
            continue
        # Try the whole target first (it may contain spaces), then the first
        # whitespace-delimited token (drops an optional "title").
        candidates = []
        for variant in (raw, raw.split()[0]):
            target = variant.split("#", 1)[0]
            if target and target not in candidates:
                candidates.append(target)
        if not candidates:
            continue
        resolved = [
            os.path.normpath(os.path.join(base, c)) for c in candidates
        ]
        if any(os.path.exists(r) for r in resolved):
            continue
        problems.append(f"{md_path}: missing link target '{candidates[-1]}'")
    return problems


def main():
    problems = []
    for md_path in tracked_markdown_files():
        if not os.path.isfile(md_path):
            continue
        problems.extend(check_file(md_path))
    if problems:
        for line in problems:
            print(line)
        return 1
    print("OK markdown-links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
