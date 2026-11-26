#!/usr/bin/env python3
# Fails when a tracked text file contains a token-shaped string (a GitHub or Anthropic API token).
import re
import subprocess
import sys


def build_patterns():
    gh = re.compile('g' + 'h' + '[posur]_' + '[A-Za-z0-9]{36,}')
    gh_pat = re.compile('github' + '_pat_' + '[A-Za-z0-9_]{22,}')
    ant = re.compile('sk' + '-ant-' + '[A-Za-z0-9_-]{20,}')
    return [gh, gh_pat, ant]


def main():
    patterns = build_patterns()
    try:
        listing = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print('git ls-files failed: %s' % exc, file=sys.stderr)
        return 1

    problems = 0
    for raw in listing.stdout.split(b'\0'):
        if not raw:
            continue
        display = raw.decode('utf-8', 'replace')
        if display.endswith('.sops.yaml'):
            continue
        try:
            with open(raw, 'rb') as fh:
                data = fh.read()
        except OSError:
            print('%s: cannot open file' % display)
            problems += 1
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.split('\n'), 1):
            if any(p.search(line) for p in patterns):
                print('%s: line %d: token-shaped string found' % (display, lineno))
                problems += 1

    if problems:
        return 1
    print('OK: no-token-patterns')
    return 0


if __name__ == '__main__':
    sys.exit(main())
