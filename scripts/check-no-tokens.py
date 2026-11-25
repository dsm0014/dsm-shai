#!/usr/bin/env python3
# Fails when token-shaped secrets (GitHub personal access tokens, GitHub fine-grained tokens, Anthropic API keys) appear in tracked text files.
import os
import re
import subprocess
import sys

PATTERNS = [
    re.compile('gh' + '[pousr]_' + '[A-Za-z0-9]{36,}'),
    re.compile('github' + '_pat_' + '[A-Za-z0-9_]{22,}'),
    re.compile('sk' + '-ant-' + '[A-Za-z0-9_-]{20,}'),
]


def main():
    listing = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, check=True).stdout
    problems = 0
    for raw in listing.split(b'\0'):
        if not raw:
            continue
        name = os.fsdecode(raw)
        if name.endswith('.sops.yaml'):
            continue
        try:
            with open(name, 'rb') as f:
                data = f.read()
            text = data.decode('utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in PATTERNS):
                print(f'{name}:{lineno}: token-shaped string found (check no-tokens)')
                problems += 1
    if problems:
        return 1
    print('OK no-tokens')
    return 0


if __name__ == '__main__':
    sys.exit(main())
