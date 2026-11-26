#!/usr/bin/env python3
# Enforces that no token-shaped strings (gh-prefixed GitHub tokens, fine-grained GitHub PATs, Anthropic API keys) appear in tracked text files.
import os
import re
import subprocess
import sys


def build(parts):
    return re.compile("".join(parts))


PATTERNS = [
    build(["gh", "[pousr]_", "[A-Za-z0-9]{36,}"]),
    build(["github", "_pat_", "[A-Za-z0-9_]{22,}"]),
    build(["sk", "-ant-", "[A-Za-z0-9_-]{20,}"]),
]


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    for raw in out.split(b"\0"):
        if raw:
            yield os.fsdecode(raw)


def main():
    problems = 0
    for path in tracked_files():
        if path.endswith(".sops.yaml"):
            continue
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            if any(p.search(line) for p in PATTERNS):
                print(f"{path}:{lineno}: token-shaped string found")
                problems += 1
    if problems:
        return 1
    print("OK no-token-patterns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
