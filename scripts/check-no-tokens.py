#!/usr/bin/env python3
# Fails when token-shaped strings (GitHub and Anthropic keys) appear in tracked text files; prints only path and line number.
import os
import re
import subprocess
import sys


def build_pattern():
    classic = "".join(["g", "h"]) + "[pousr]_[A-Za-z0-9]{36,}"
    fine_grained = "".join(["github", "_pat_"]) + "[A-Za-z0-9_]{22,}"
    anthropic = "".join(["sk", "-ant-"]) + "[A-Za-z0-9_-]{20,}"
    return re.compile("|".join("(?:%s)" % p for p in (classic, fine_grained, anthropic)))


def main():
    try:
        proc = subprocess.run(["git", "ls-files", "-z"], capture_output=True)
    except OSError as exc:
        sys.stderr.write("check-no-tokens: cannot run git: %s\n" % exc)
        return 1
    if proc.returncode != 0:
        sys.stderr.write("check-no-tokens: git ls-files failed\n")
        return 1

    paths = [p for p in os.fsdecode(proc.stdout).split("\0") if p]
    pattern = build_pattern()
    problems = 0

    for path in paths:
        if path.endswith(".sops.yaml"):
            continue
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            sys.stderr.write("check-no-tokens: cannot read %s: %s\n" % (path, exc.strerror))
            return 1
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split("\n"), start=1):
            if pattern.search(line):
                print("%s:%d: token-shaped string found" % (path, lineno))
                problems += 1

    if problems:
        return 1
    print("OK no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
