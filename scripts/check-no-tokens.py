#!/usr/bin/env python3
# Fails when token-shaped secrets appear in tracked text files.
import os
import re
import subprocess
import sys

# Fragments are joined at run time so this file never holds a full token prefix.
PATTERNS = [
    ("possible GitHub token", re.compile("gh" + "[pousr]" + "_" + "[A-Za-z0-9]{36,}")),
    ("possible GitHub fine-grained token", re.compile("github" + "_pat_" + "[A-Za-z0-9_]{22,}")),
    ("possible Anthropic API key", re.compile("sk" + "-ant-" + "[A-Za-z0-9_-]{20,}")),
]
SKIP_SUFFIX = ".sops.yaml"


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    return [os.fsdecode(p) for p in out.split(b"\0") if p]


def main():
    problems = []
    for path in tracked_files():
        if path.endswith(SKIP_SUFFIX):
            continue
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split("\n"), start=1):
            for message, pattern in PATTERNS:
                if pattern.search(line):
                    problems.append(f"{path}:{lineno}: {message}")
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("OK no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
