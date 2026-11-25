#!/usr/bin/env python3
# Enforces that every relative markdown link ](target) in tracked .md files points to an existing file.
import os
import re
import subprocess
import sys

LINK_RE = re.compile(r'\]\(([^)\s]+)\)')
SKIP_PREFIXES = ('http://', 'https://', 'mailto:', '#')


def tracked_markdown_files():
    out = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split('\0') if p.endswith('.md')]


def main():
    problems = []
    for path in tracked_markdown_files():
        with open(path, encoding='utf-8') as f:
            text = f.read()
        for match in LINK_RE.finditer(text):
            raw = match.group(1)
            if raw.startswith(SKIP_PREFIXES):
                continue
            target = raw.split('#', 1)[0]
            if not target:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
            if not os.path.exists(resolved):
                problems.append(f'{path}: link target does not exist: {target}')
    if problems:
        print('\n'.join(problems))
        return 1
    print('OK markdown links')
    return 0


if __name__ == '__main__':
    sys.exit(main())
