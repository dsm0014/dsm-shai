#!/usr/bin/env python3
# Fails when a git-tracked text file contains a token-shaped GitHub or Anthropic secret string; *.sops.yaml and non-UTF-8 files are skipped.
import os
import re
import subprocess
import sys

PATTERNS = [
    ('classic GitHub token', re.compile('gh' + '[posur]_' + '[A-Za-z0-9]{36,}')),
    ('fine-grained GitHub token', re.compile('github' + '_pat_' + '[A-Za-z0-9_]{22,}')),
    ('Anthropic API key', re.compile('sk' + '-ant-' + '[A-Za-z0-9_-]{20,}')),
]


def main():
    out = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, check=True).stdout
    problems = []
    for raw in out.split(b'\0'):
        if not raw:
            continue
        path = os.fsdecode(raw)
        if path.endswith('.sops.yaml') or not os.path.isfile(path):
            continue
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
        except OSError:
            problems.append(f'{path}: cannot read file')
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split('\n'), 1):
            label = next((lab for lab, pat in PATTERNS if pat.search(line)), None)
            if label is not None:
                problems.append(f'{path}:{lineno}: matches {label}')
    if problems:
        for p in problems:
            print(p)
        return 1
    print('OK check-no-tokens')
    return 0


if __name__ == '__main__':
    sys.exit(main())
