#!/usr/bin/env python3
# Fails when token-shaped strings (GitHub personal, OAuth, user, server, or refresh tokens, fine-grained GitHub PATs, and Anthropic API keys) appear in tracked text files.
import os
import re
import stat
import subprocess
import sys

# Fragments are joined at run time so this file never contains a complete token prefix.
PATTERNS = [
    ("GitHub", re.compile("gh" + "[pousr]_" + "[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained PAT", re.compile("github" + "_pat_" + "[A-Za-z0-9_]{22,}")),
    ("Anthropic API key", re.compile("sk-" + "ant-" + "[A-Za-z0-9_-]{20,}")),
]


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True).stdout
    return [os.fsdecode(p) for p in out.split(b"\0") if p]


def main():
    problems = []
    for path in tracked_files():
        if path.endswith(".sops.yaml"):
            continue
        try:
            if not stat.S_ISREG(os.lstat(path).st_mode):
                continue
            with open(path, "rb") as f:
                text = f.read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            for kind, pattern in PATTERNS:
                if pattern.search(line):
                    problems.append(f"{path}: line {lineno}: possible {kind} token")
    if problems:
        print("\n".join(problems))
        return 1
    print("OK no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
