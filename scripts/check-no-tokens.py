#!/usr/bin/env python3
# Fails if any tracked text file contains a GitHub or Anthropic token-shaped string.
import os
import re
import subprocess
import sys

PATTERNS = [
    re.compile("".join(["g", "h", "[pousr]", "_", "[A-Za-z0-9]{36,}"])),
    re.compile("".join(["git", "hub_pa", "t_"]) + "[A-Za-z0-9_]{22,}"),
    re.compile("".join(["sk", "-ant", "-"]) + "[A-Za-z0-9_-]{20,}"),
]


def main():
    try:
        result = subprocess.run(["git", "ls-files", "-z"], capture_output=True)
    except OSError as exc:
        print(f"git ls-files failed: {exc}", file=sys.stderr)
        return 2
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode(errors="replace") or "git ls-files failed\n")
        return 2

    problems = 0
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        path = os.fsdecode(raw)
        if path.endswith(".sops.yaml") or os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            if any(p.search(line) for p in PATTERNS):
                print(f"{path}:{lineno}: token-shaped string found")
                problems += 1

    if problems:
        return 1
    print("OK check-no-tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
