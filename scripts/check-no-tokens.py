#!/usr/bin/env python3
# Fails if any tracked text file contains a token-shaped string for GitHub or Anthropic keys.
import re
import subprocess
import sys


def build_patterns():
    # Fragments are joined at run time so this file never contains a full literal prefix.
    gh = "g" + "h"
    github_pat = "github" + "_pat" + "_"
    sk_ant = "sk" + "-ant" + "-"
    return [
        ("github-token", re.compile(gh + "[pousr]_[A-Za-z0-9]{36,}")),
        ("github-pat", re.compile(github_pat + "[A-Za-z0-9_]{22,}")),
        ("anthropic-key", re.compile(sk_ant + "[A-Za-z0-9_-]{20,}")),
    ]


def list_tracked():
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        print("error: git ls-files failed", file=sys.stderr)
        sys.exit(2)
    return [p for p in out.split(b"\0") if p]


def main():
    patterns = build_patterns()
    problems = 0
    for raw in list_tracked():
        path = raw.decode("utf-8", errors="replace")
        if path.endswith(".sops.yaml"):
            continue
        try:
            with open(raw, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            for name, rx in patterns:
                if rx.search(line):
                    print(f"{path}:{lineno}: token-shaped string ({name})")
                    problems += 1
    if problems:
        return 1
    print("OK no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
