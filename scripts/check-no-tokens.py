#!/usr/bin/env python3
# Fails when token-shaped secrets appear in tracked text files.
import os
import re
import subprocess
import sys


def build_patterns():
    gh = "g" + "h"
    gh_pat = "github" + "_pat_"
    sk_ant = "sk" + "-ant-"
    return [
        re.compile(gh + "[pousr]" + "_" + "[A-Za-z0-9]{36,}"),
        re.compile(gh_pat + "[A-Za-z0-9_]{22,}"),
        re.compile(sk_ant + "[A-Za-z0-9_-]{20,}"),
    ]


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    return [os.fsdecode(p) for p in out.split(b"\0") if p]


def main():
    patterns = build_patterns()
    problems = []
    for path in tracked_files():
        if path.endswith(".sops.yaml"):
            continue
        with open(path, "rb") as fh:
            raw = fh.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split("\n"), start=1):
            if any(p.search(line) for p in patterns):
                problems.append(f"{path}: line {lineno}: token-shaped string found")
    for msg in problems:
        print(msg)
    if problems:
        return 1
    print("OK no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
