#!/usr/bin/env python3
# Enforces: no token-shaped strings (GitHub and Anthropic credentials) in tracked text files.
import os
import re
import subprocess
import sys

PATTERNS = [
    ("github token", re.compile("g" + "h" + "[pousr]_[A-Za-z0-9]{36,}")),
    ("github fine-grained token", re.compile("github" + "_pat_" + "[A-Za-z0-9_]{22,}")),
    ("anthropic key", re.compile("sk" + "-ant-" + "[A-Za-z0-9_-]{20,}")),
]


def tracked_files():
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        print("error: git ls-files failed: %s" % exc, file=sys.stderr)
        sys.exit(2)
    return [os.fsdecode(p) for p in out.split(b"\0") if p]


def main():
    problems = []
    for path in tracked_files():
        if path.endswith(".sops.yaml"):
            continue
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split("\n"), start=1):
            for name, pattern in PATTERNS:
                if pattern.search(line):
                    problems.append(
                        "%s: line %d: possible credential (%s)" % (path, lineno, name)
                    )
                    break

    if problems:
        for problem in problems:
            print(problem)
        return 1
    print("OK check-no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
