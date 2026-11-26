#!/usr/bin/env python3
# Fails when a tracked text file contains a token-shaped string (GitHub personal access tokens with the gh prefix, fine-grained GitHub tokens, Anthropic API keys); matched text is never printed.
import os
import re
import subprocess
import sys


def build_patterns():
    gh = "g" + "h"
    fine = "github" + "_pat_"
    ant = "sk" + "-ant-"
    return [
        re.compile(gh + "[posur]_[A-Za-z0-9]{36,}"),
        re.compile(fine + "[A-Za-z0-9_]{22,}"),
        re.compile(ant + "[A-Za-z0-9_-]{20,}"),
    ]


def main():
    patterns = build_patterns()
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    failed = False
    for raw in out.split(b"\0"):
        if not raw:
            continue
        path = os.fsdecode(raw)
        if path.endswith(".sops.yaml") or os.path.islink(path) or not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            if any(p.search(line) for p in patterns):
                print(f"{path}:{lineno}: token-shaped string found")
                failed = True
    if failed:
        return 1
    print("OK no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
