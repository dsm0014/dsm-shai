#!/usr/bin/env python3
# Checks that every .PHONY target in the root Makefile has a help comment and every target with a help comment is .PHONY.
import re
import subprocess
import sys

HELP_RE = re.compile(r'^([A-Za-z0-9_.-]+)\s*:(?![=:]).*?##\s*\S')
PHONY_RE = re.compile(r'^\.PHONY\s*:(.*)$')


def find_makefile():
    result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, check=True)
    for entry in result.stdout.splitlines():
        if entry == 'Makefile':
            return entry
    return None


def logical_lines(text):
    out = []
    buf = ''
    for raw in text.splitlines():
        if raw.endswith('\\'):
            buf += raw[:-1] + ' '
        else:
            out.append(buf + raw)
            buf = ''
    if buf:
        out.append(buf)
    return out


def main():
    path = find_makefile()
    if path is None:
        print('Makefile: not tracked')
        return 1

    with open(path, encoding='utf-8') as fh:
        lines = logical_lines(fh.read())

    phony = set()
    helped = set()
    for line in lines:
        m = PHONY_RE.match(line)
        if m:
            phony.update(m.group(1).split())
            continue
        m = HELP_RE.match(line)
        if m and m.group(1) != '.PHONY':
            helped.add(m.group(1))

    problems = []
    for target in sorted(phony - helped):
        problems.append(f'Makefile: {target} is .PHONY but has no help comment')
    for target in sorted(helped - phony):
        problems.append(f'Makefile: {target} has a help comment but is not .PHONY')

    for problem in problems:
        print(problem)
    if problems:
        return 1

    print('OK makefile-help')
    return 0


if __name__ == '__main__':
    sys.exit(main())
