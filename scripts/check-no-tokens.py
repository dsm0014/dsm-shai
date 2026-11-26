#!/usr/bin/env python3
# Enforces that no token-shaped secrets (GitHub classic and fine-grained PATs, GitHub OAuth, user-to-server, server-to-server and refresh tokens, and Anthropic API keys) appear in tracked text files.
import os
import re
import subprocess
import sys

# Patterns are assembled from fragments so this file never contains a full literal prefix.
PATTERNS = [
    re.compile("g" + "h" + "[pousr]_" + "[A-Za-z0-9]{36,}"),
    re.compile("github" + "_pat_" + "[A-Za-z0-9_]{22,}"),
    re.compile("sk" + "-ant-" + "[A-Za-z0-9_-]{20,}"),
]


def main():
    listing = subprocess.run(
        ['git', 'ls-files', '-z'], capture_output=True, check=True
    ).stdout
    problems = 0
    for raw in listing.split(b'\0'):
        if not raw:
            continue
        path = os.fsdecode(raw)
        if path.endswith('.sops.yaml'):
            continue
        if not os.path.isfile(path):
            continue
        with open(path, 'rb') as fh:
            data = fh.read()
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split('\n'), 1):
            if any(rx.search(line) for rx in PATTERNS):
                print(f'{path}:{lineno}: token-shaped string found')
                problems += 1
    if problems:
        return 1
    print('OK check-no-tokens')
    return 0


if __name__ == '__main__':
    sys.exit(main())
