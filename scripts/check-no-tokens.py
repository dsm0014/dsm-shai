#!/usr/bin/env python3
# Fails when token-shaped strings (GitHub personal, OAuth, user, server, refresh and fine-grained tokens, and Anthropic sk-ant- keys) appear in tracked text files.
import os
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    re.compile("g" + "h" + "[pousr]" + "_" + "[A-Za-z0-9]{36,}"),
    re.compile("github" + "_pat_" + "[A-Za-z0-9_]{22,}"),
    re.compile("sk-" + "ant-" + "[A-Za-z0-9_-]{20,}"),
]


def main():
    listing = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    problems = 0
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        rel = os.fsdecode(raw)
        if rel.endswith(".sops.yaml"):
            continue
        path = Path(rel)
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                print(f"{rel}: line {number}: token-shaped string found")
                problems += 1
    if problems:
        return 1
    print("OK no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
