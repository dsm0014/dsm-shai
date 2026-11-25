#!/usr/bin/env python3
# Enforces that every relative markdown link ](target) in tracked .md files points to an existing file or directory.
import os
import re
import subprocess
import sys

LINK_RE = re.compile(r'\]\(([^)]*)\)')


def main():
    out = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, text=True, check=True)
    files = [f for f in out.stdout.split('\0') if f.endswith('.md')]
    problems = []
    for md_path in files:
        with open(md_path, encoding='utf-8') as fh:
            text = fh.read()
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if not target or target.startswith(('http://', 'https://', 'mailto:', '#')):
                continue
            target = target.split('#', 1)[0]
            tokens = target.split()
            if not tokens:
                continue
            target = tokens[0]
            if target.startswith('<') and target.endswith('>'):
                target = target[1:-1]
            if not target:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(md_path), target))
            if not os.path.exists(resolved):
                problems.append(f'{md_path}: broken link to missing {target}')
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print('OK markdown-links')
    return 0


if __name__ == '__main__':
    sys.exit(main())
